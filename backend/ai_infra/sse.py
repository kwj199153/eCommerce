"""
SSE（Server-Sent Events）流式输出工具

为业务 Agent 提供统一的 SSE 事件流封装，把 LLM 的逐 token 输出
转发给前端实现打字机效果。

统一事件协议（text/event-stream，每条以 \\n\\n 分隔）：
    event: delta         # 增量文本
    data: {"text": "..."}

    event: progress      # 阶段进度（耗时步骤前的状态提示，非正文）
    data: {"text": "正在挖掘蓝海品类数据…"}

    event: preview       # 正文**预览**增量（临时管道：随时被替换/作废，非正文）
    data: {"text": "...", "segment": "<触发它的那次模型调用的 run_id>"}

    event: meta          # 元信息（可选：结构化结果、展示类型）
    data: {"display_type": "...", "data": {...}}

    event: done          # 结束
    data: {"text": "完整文本"}

    event: error         # 出错
    data: {"message": "..."}

使用方式：
    from ai_infra.sse import sse_event_stream, progress

    @router.post("/chat/stream")
    async def chat_stream(request: ...):
        async def gen():
            async for chunk in agent.llm_stream(prompt, ...):
                yield sse_event("delta", {"text": chunk})
            yield sse_event("done", {"text": full})
        return StreamingResponse(gen(), media_type="text/event-stream")

    # 迭代器里混入 progress：yield 一个 dict 即会被识别成 progress 事件
    async def gen():
        yield progress("正在分析…")          # → event: progress
        yield "正文片段"                      # → event: delta
"""

import json
import time
from typing import AsyncIterable, Callable, Optional


def sse_event(event: str, data: dict) -> str:
    """构造单条 SSE 消息（含 event 字段和 JSON data）"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def progress(text: str) -> dict:
    """构造一条「阶段进度」标记。

    供各业务 Agent 的 stream_chat 在**耗时步骤之前** yield，
    让前端把「AI 正在思考…」换成具体的阶段文案（如「正在挖掘蓝海品类数据…」），
    避免长任务期间零输出导致的「卡死」错觉。

    注意：这是迭代器里的**结构化 chunk**（dict），由 sse_event_stream 识别并
    转成 `event: progress`；它不计入正文，因此不会被拼进最终文本。
    """
    return {"event": "progress", "text": text}


def preview(text: str, *, segment: str = "") -> dict:
    """构造一条「正文**预览**增量」标记（结构化 chunk，**非正文**）。

    ★ 与 `delta` 的分工（都是"流式文本"，但**可靠性级别完全不同**）：

    | | `delta`（正文增量） | `preview`（预览增量） |
    |---|---|---|
    | 权威性 | **就是**正文，被 `done` 采纳 | 预览：随时会被作废 / 整段替换 |
    | 累计 | 进 `done.accumulated` | **不进**（`sse_event_stream` 只累 `str`） |
    | 落库 | 会（router 从 `meta` 取权威正文） | **不会** |
    | 前端 | 直接拼进正文 | 只拼进"预览"，权威正文一到就整段替换 |

    ★ 为什么店秘书需要它、而不是像 `product_research` 那样直接 `yield text`：
      那家的 token **就是**最终答复（边收边发、不再重发一遍）；
      而店秘书的权威正文**必须**走 `_digest_graph_state`（唯一取口 —— 它要带上
      `TRUNCATED_NOTICE` 前缀、要与 `/chat` 逐字相同）。若把 token 也发成
      `delta`，`done.accumulated` 与落库都会变成「预览 + 正文」拼两遍，
      而且**零报错**（表现只是"那段话变长了"）。所以预览必须走一条
      **不会被采纳**的通道 —— 这条通道就是本函数。

    ★ `segment` = 触发这段预览的那次模型调用的 `run_id`。ReAct 一轮里模型会开口
      多次（中间轮"我先查一下…"、末轮给结论），前端据此**换段即清零**；
      否则中间轮的碎话会留在屏上，与"最终用 state 正文替换"互相打架。

    ★ 载荷恒为 `{"text": ...}`；`segment` 只在非空时带上 —— 缺字段时前端按
      "还是同一段"处理。宁可两段黏在一起，也不要因为拿不到 id 就**丢掉预览**
      （那是静默丢内容，正是本轮要治的那个病）。
    """
    payload: dict = {"text": text}
    if segment:
        payload["segment"] = segment
    return {"event": "preview", "data": payload}


def step(
    kind: str,
    title: str,
    *,
    tool: str = "",
    detail: str = "",
    result: str = "",
    status: str = "running",
    ms: Optional[int] = None,
    step_id: str = "",
) -> dict:
    """构造一条「思考过程」步骤事件（结构化 chunk，**不计入正文**）。

    与 `progress()` 的分工（两者都走 `event:` 通道，但语义完全不同）：

    | | `progress()` | `step()` |
    |---|---|---|
    | 形态 | 单行、会被**覆盖**的阶段提示 | 逐条**追加**的轨迹条目 |
    | 前端用法 | loading 的 tip 文案（用完即弃） | 累积成可回看的「思考过程」 |
    | 生命周期 | 结果一到就丢 | 结果到达后**折叠保留** |

    ⇒ 「过程折叠掉」这个需求不能靠 `progress` 实现：它在 `setLoading(false)` 里
      就被清空了，**过程从未被留存**。所以过程要能被折叠，先得有一条
      「值得留」的事件 —— 那就是本函数。

    载荷（`data` 字段）：

        kind    "tool" | "note"          步骤类别
        title   人话标题（如「正在调用工具」）
        tool    原始工具名（可选）
        detail  入参摘要（**开始态**；已截断，可选）
        result  返回值 / 报错摘要（**结束态**；已截断，可选）
        status  "running" | "done" | "error"
        ms      耗时毫秒（仅结束态，可选）
        id      本步骤在本次轨迹内的唯一 id（前端 `v-for` 的 key、去重依据）

    ★ `title` 由**调用方**给（本函数不查表）：工具的人话标题住在业务侧的
      工具目录里，而本模块属基础设施层 —— `ai_infra` 反向依赖业务模块是本仓的
      硬红线（`tests/test_infra_layering.py` 连**字符串字面量**都查）。
      ⇒ 人话标题只能**注入**：`ToolTrace` / `StreamDigest` 收一个
        `title_resolver` 回调（业务侧传它的唯一查询口），本函数拿到的是
        解析后的结果。未注入 / 解析失败 / 解析出空 ⇒ 回落通用措辞 +
        原始工具名 —— 是**可见的降级**，既不静默丢步骤，也不静默显示错名字。
    """
    payload: dict = {"kind": kind, "title": title, "status": status}
    if tool:
        payload["tool"] = tool
    if detail:
        payload["detail"] = detail
    if result:
        payload["result"] = result
    if ms is not None:
        payload["ms"] = int(ms)
    if step_id:
        payload["id"] = step_id
    return {"event": "step", "data": payload}


def chunk_text(chunk) -> str:
    """把一条模型 chunk 的 `content` 取成字符串 —— **全仓唯一实现**。

    ★ 为什么提到模块级（原先是 `StreamDigest._chunk_text`）：现在有**两个**消费方
      （`StreamDigest` 攒答复、`ToolTrace` 转发预览 token）。各留一份 =
      「同一判定两份实现」，而它们的差别恰在**边缘形态**（`content` 是列表 /
      是 None / 是别的类型）—— 最易漏测、又最易只修一处。本仓上一个同形坑：
      只处理 str 形态 ⇒ 分段列表**静默变成空答复**，上层以为"这轮没内容"而走兜底。

    `content` 的两种形态：普通字符串（OpenAI 系），以及分段列表
    （部分模型 / 多模态返回 `[{"type": "text", "text": "..."}]`）。
    """
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")


class ToolTrace:
    """把 LangChain `astream_events` 的工具事件翻译成面向用户的**步骤事件**。

    ★ 为什么需要一个**有状态**的翻译器，而不是各 Agent 里手写 if/else：
      `on_tool_start` 与 `on_tool_end` 是**两条独立事件** —— 要算出「这个工具跑了
      多久」必须把 start 时的时刻存下来，等 end 时相减。各家各写一份计时逻辑，
      必然出现「有的算有的不算」；更隐蔽的是**键选错**：用工具名当键，
      两个同名工具并行（或在同一轮里被调两次）时会互相覆盖，耗时算到别人头上。
      这里统一用 `run_id`（LangChain 每次调用的唯一 id）当键。

    ★ 它**不产出正文**：返回值交给 `sse_event_stream` 时命中 dict 分支，
      转成 `event: step`，不进 `accumulated`。所以「过程」与「答复」天然分离 ——
      这正是「只做加法、正文零变化」在代码形态上的保证。

    ★★ 第 238 轮加的**第二条出口**：`on_model_stream`（模型 token 转发）。
      为什么不放在各 Agent 自己的 if/elif 里：`on_chat_model_stream` 的解包
      （chunk → 文本）与 `on_tool_*` 一样是**协议细节**，抄一份就多一份漂移
      （`_chunk_text` 的列表形态就是这么漏的，现已提成模块级 `chunk_text`）。
      本类只做「解包 + 转发」，**发不发、发成什么事件名**由注入的回调决定 ——
      于是「token 即正文」（`product_research` 发 `delta`）与
      「token 只是预览」（`secretary` 发 `preview`）能共用同一条解包逻辑。

    ★ 用法（业务侧）：

        trace = ToolTrace(title_resolver=tool_title)   # ← 注入人话标题（见下）
        async for ev in router.stream_session(...):
            s = trace.feed(ev)
            if s is not None:
                yield s            # → event: step
            ...                    # 其余分支照旧

    ★ `title_resolver` 是**依赖注入**（`tool_name -> 人话名`），不是配置项：
      业务侧把它唯一的工具目录查询口传进来，本类只负责调用。
      为什么不干脆在这里 import 一张表 —— 那会同时犯两个错：
        ① `ai_infra` 反向依赖业务（分层硬红线）；
        ② 表抄成第二份 ⇒ 与业务侧真源**必然漂移**。
      为什么**默认 None 而不是必填**：本类在无业务的场景（纯协议单测、
        第三方图）也必须能用；拿不到标题时回落通用措辞，是可见的降级。
    """

    def __init__(
        self,
        max_detail: int = 200,
        title_resolver: Optional[Callable[[str], str]] = None,
        on_model_stream: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        #: `run_id` → 开始时刻（单调时钟，不受系统时间调整影响）
        self._open: dict = {}
        self._max_detail = int(max_detail)
        self._seq = 0
        #: `tool_name -> 人话标题`；None ⇒ 一律用通用措辞（**可见的降级**）。
        #: 由业务侧注入（见类 docstring）—— 本层不查表、不 import 业务模块。
        self._title_resolver = title_resolver
        #: `(text, segment) -> None` —— 模型 token 的**转发口**（见类 docstring）。
        #: None ⇒ 丢弃 token（= 只做工具轨迹的旧行为，默认档）。
        #: 刻意**不给默认实现**：发成 `preview` 还是 `delta` 是调用方的语义决定，
        #: 本层不越权替它选（选错的表现是"正文被拼脏"，且零报错）。
        self._on_model_stream = on_model_stream

    # ------------------------------------------------------------ 内部

    def _keys(self, ev: dict) -> tuple:
        name = ev.get("name") or ""
        # `run_id` 缺失时退回工具名 —— 宁可退化成「同名并发会串」，
        # 也不要因为拿不到 id 就整条步骤不发（那是静默丢失过程）。
        return name, str(ev.get("run_id") or name)

    def _brief(self, value) -> str:
        """把任意入参 / 返回值压成**一行**可读摘要（超长截断）。"""
        if value is None:
            return ""
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = repr(value)
        text = " ".join(text.split())          # 折掉换行，避免把界面撑爆
        if len(text) > self._max_detail:
            text = text[: self._max_detail] + "…"
        return text

    def _title(self, tool: str, fallback: str) -> str:
        """取该工具的人话标题；拿不到就用 `fallback`（**可见的降级**）。

        ★ 三档回落都回到 `fallback`（未注入 / 抛异常 / 返回空），原因分别是：

        · **未注入** —— 纯协议单测、第三方图不带业务目录，此时通用措辞 + 原始
          工具名仍让用户看得见「有这一步」，比空白好；
        · **抛异常** —— `title_resolver` 是**业务侧注入的回调**，它抛异常会顺着
          `feed()` 炸掉整条 SSE 流。为一个**展示用**的名字把「过程 + 答复」
          全丢掉，代价与收益完全不对称；
        · **返回空** —— 查到了但给空串 ⇒ 界面渲染出一个空白步骤（看着像丢了），
          与「没查到」应当表现一致。
        """
        if self._title_resolver is None or not tool:
            return fallback
        try:
            got = self._title_resolver(tool)
        except Exception:  # noqa: BLE001 —— 见 docstring：展示用字段不配炸流
            return fallback
        return str(got or "").strip() or fallback

    def _finish(self, ev: dict, status: str, fallback: str) -> dict:
        name, run_id = self._keys(ev)
        started = self._open.pop(run_id, None)
        ms = None if started is None else int((time.monotonic() - started) * 1000)
        data = ev.get("data") or {}
        raw = data.get("output") if status == "done" else data.get("error")
        return step(
            "tool",
            self._title(name, fallback),
            tool=name,
            result=self._brief(raw),
            status=status,
            ms=ms,
            step_id=run_id,
        )

    # ------------------------------------------------------------ 出口

    def feed(self, ev: dict):
        """消费一条 `astream_events` 事件；命中工具事件时返回 step，否则 None。

        ★ 两类事件、两条出口（其余事件原样放过）：

          · 工具事件（`on_tool_*`）⇒ **返回** step，由调用方 yield 成 `event: step`；
          · 模型 token（`on_chat_model_stream`）⇒ **转给**注入的 `on_model_stream`。
            本方法只转发、**不产出事件** —— 发成 `preview` 还是 `delta` 是调用方的
            语义决定（见类 docstring），本层不越权替它选。

        ★ 转发的回调是**同步**的 —— 调用方若要把 token 变成 SSE 帧，**不能在回调里
          yield**（同步函数没有 yield 口）。唯一可行的形态是"回调入队、回到调用方
          的异步循环里再吐"（`modules/secretary/agent.py::route_stream` 的 `pending`
          就是干这个的）。写在这里，是因为下一个接线的人会先撞上它。
        """
        kind = (ev or {}).get("event")
        if kind == "on_chat_model_stream":
            if self._on_model_stream is not None:
                text = chunk_text((ev.get("data") or {}).get("chunk"))
                if text:                       # 空块不转发：省得前端收一堆空帧
                    self._on_model_stream(text, str(ev.get("run_id") or ""))
            return None
        if kind == "on_tool_start":
            name, run_id = self._keys(ev)
            self._seq += 1
            self._open[run_id] = time.monotonic()
            data = ev.get("data") or {}
            return step(
                "tool",
                # 有 resolver ⇒ 人话名（如「出价优化」）；否则通用措辞。
                # ★「做到哪一步」由 `status` 承载，**不再塞进 title**：
                #   否则同一字段一半是「对象名」、一半是「状态」，前端必然
                #   长出两套判据（本仓：同一判定两份实现 = 必漂移）。
                self._title(name, "正在调用工具"),
                tool=name,
                detail=self._brief(data.get("input")),
                status="running",
                step_id=run_id,
            )
        if kind == "on_tool_end":
            return self._finish(ev, "done", "工具调用完成")
        if kind == "on_tool_error":
            return self._finish(ev, "error", "工具调用失败")
        return None


class StreamDigest:
    """一趟流式会话的**消化器**：工具轨迹 + 最终答复，一次遍历同时产出两者。

    ★ 为什么需要它（而不是各 Agent 各写一遍循环）：
      「取工具轨迹」与「取最终答复」是同一趟 `astream_events` 遍历的两件事。
      各写一份的后果不是报错，而是**缓慢漂移** —— 某一家改了过滤条件，
      其余几家不知道，也没有任何红灯。

    ★ 为什么答复只取「**最后一段有内容的**模型输出」：
      ReAct 一轮里模型会开口多次（中间轮说「我先查一下…」、末轮给结论）。
      非流式路径（`run_session` + 扫 `messages`）取的是消息序列里**最后一条**
      有内容的 `AIMessage`。这里按 `run_id` 分组累积、只保留最后一段非空的，
      就是为了让「换成流式」**不改变正文** —— 不把中间轮的碎话混进答复里。
      （要不要把中间轮文本挪去思考区是**另一件事**，别在这里顺手改。）

    ★★ 答复有**两个**来源，缺一不可：
      · `on_chat_model_stream` —— 只有模型**真流式**时才出现；
      · 根图 `on_chain_end` 的 `data.output["messages"]` —— **图跑完的最终 state**。

    ★ 第 210 轮曾据"实测一条 `on_chat_model_stream` 都没有"把它写成"只作兜底"。
      **那个实测结论是错的**（第 238 轮用真图复测：闲聊 10 条、带工具 11 条）。
      当时测不出来的原因：测试环境把 `_get_default_llm` 换成了离线桩
      （`tests/conftest.py`）—— 桩不是 `BaseChatModel`，`astream_events` 不会给它挂
      流式 handler，`_should_stream` 于是恒 False；真 `ChatOpenAI` 上不是这样。
      **但"以图最终 state 为准"这条结论不变**，理由反而更硬：流式累积拿不到
      `TRUNCATED_NOTICE` 前缀，也拿不到"最后一条有内容的 AIMessage"这个口径
      ⇒ 只盯 stream 会让正文与 `/chat` 漂移。
      （结论不变、理由换掉 —— 不要因为"当时测错了"就把它反过来。）

    ★ 用法（业务侧）：

        digest = StreamDigest(title_resolver=tool_title)   # ← 同上：注入人话标题
        async for ev in router.stream_session({...}):
            s = digest.feed(ev)
            if s is not None:
                yield s            # → event: step（实时）
        reply = digest.reply       # → 原样按旧时序吐出，正文零变化
    """

    def __init__(
        self,
        max_detail: int = 200,
        title_resolver: Optional[Callable[[str], str]] = None,
    ) -> None:
        #: 工具事件 → 步骤事件（有状态：算耗时）；
        #: `title_resolver` **原样透传**（语义与回落见 `ToolTrace._title`）。
        self.trace = ToolTrace(max_detail=max_detail, title_resolver=title_resolver)
        #: `run_id` → 该次模型调用已累积的文本
        self._by_run: dict = {}
        #: 最后一个**产出过文本**的 run_id
        self._last_run: str = ""
        #: 图最终 state 里取到的答复（与非流式路径同源，优先于流式累积）
        self._final_reply: str = ""

    @staticmethod
    def _last_ai_text(messages) -> str:
        """从图最终 state 的 `messages` 里取**最后一条有内容的 AIMessage**。

        取法与竞品 `_route_via_tools`（非流式）逐字同构 —— 这是「换成流式
        **不改变正文**」的落点，而不是一句口号。`langchain_core` 惰性导入：
        `ai_infra.sse` 是纯协议模块，顶层不引 langchain。
        """
        from langchain_core.messages import AIMessage

        reply = ""
        for m in messages or []:
            if isinstance(m, AIMessage) and m.content:
                reply = m.content if isinstance(m.content, str) else str(m.content)
        return reply.strip()

    def feed(self, ev: dict):
        """吃一条事件：返回 step（若有），否则 None；模型文本顺手累积。"""
        et = (ev or {}).get("event")
        if et == "on_chat_model_stream":
            text = chunk_text((ev.get("data") or {}).get("chunk"))
            if text:
                run_id = str(ev.get("run_id") or "")
                self._by_run[run_id] = self._by_run.get(run_id, "") + text
                self._last_run = run_id
            return None
        if et == "on_chain_end":
            out = (ev.get("data") or {}).get("output")
            if isinstance(out, dict):
                text = self._last_ai_text(out.get("messages"))
                if text:
                    # 根图的 `on_chain_end` 排在所有子事件之后 ⇒ 最后写进来的是
                    # 整张图的最终 state（子节点的中间态会被它覆盖）。
                    self._final_reply = text
        return self.trace.feed(ev)

    @property
    def reply(self) -> str:
        """最终答复（= 非流式路径会取到的那条 `AIMessage.content`）。

        优先**图最终 state**（本仓 `_llm_call_node` 用 `ainvoke`，stream 事件
        根本不会出现）；没有根图输出时才退回流式累积（图被中断、或模型确实
        逐块下发的实现）。
        """
        if self._final_reply:
            return self._final_reply
        return (self._by_run.get(self._last_run) or "").strip()


def sse_comment(text: str) -> str:
    """发送 SSE 注释（用于 keep-alive，前端会忽略）"""
    return f": {text}\n\n"



async def sse_keepalive() -> AsyncIterable[str]:
    """心跳占位（可选，由调用方按需使用）"""
    yield sse_comment("keep-alive")


async def sse_event_stream(
    chunks: AsyncIterable,
    meta: Optional[dict] = None,
    full_text: str = "",
) -> AsyncIterable[str]:
    """
    把逐段文本流包装成标准 SSE 事件流。

    迭代器可混入两类元素：
    - str：正文增量 → `event: delta`
    - dict：结构化事件 → 按 `event` 字段分发（默认 progress），
      例如 `{"event": "progress", "text": "正在分析…"}`。
      结构化事件**不计入正文**。

    Args:
        chunks: 逐 token 文本 / 结构化事件迭代器
        meta: 可选的元信息（结构化数据 + 展示类型），在 done 前发送
        full_text: 累计的完整文本（若不传则内部累加）
    """
    accumulated = full_text

    async for chunk in chunks:
        if chunk is None:
            continue

        # 结构化事件（进度提示等）：不拼进正文，单独发一条对应事件
        if isinstance(chunk, dict):
            event_type = chunk.get("event") or "progress"
            payload = chunk.get("data")
            if payload is None:
                payload = {"text": str(chunk.get("text", ""))}
            yield sse_event(event_type, payload)
            continue

        chunk = str(chunk)
        if not chunk:
            continue
        accumulated += chunk
        yield sse_event("delta", {"text": chunk})

    if meta:
        yield sse_event("meta", meta)

    yield sse_event("done", {"text": accumulated})

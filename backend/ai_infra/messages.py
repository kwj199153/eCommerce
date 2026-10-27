"""消息结构与「本轮」口径 —— 两件事的唯一真源（第 400 轮 · P2 拆分）。

## 本模块管什么

| 关注点 | 入口 |
| --- | --- |
| 内容取文本（`str | list[...]` 多模态） | `content_text()` |
| tool_calls / ToolMessage **配对自愈** | `sanitize_tool_call_pairing()` |
| 「本轮」= 最后一条 `HumanMessage` 之后 | `iterations_in_current_turn()` / `tool_activity_in_turn()` / `previous_turn_was_clarification()` |
| 本轮**此前**已耗 token | `carried_tokens()` |

## 为什么从 `base_agent.py` 搬出来（第 400 轮 P2）

这些都是**只吃消息列表、不吃 `self`** 的纯函数，却长期挂在 `BaseAgent` 的
`@staticmethod` 上。后果是 `base_agent.py` 长到 1871 行，而**任何**想复用
「本轮是第几次迭代」的地方都得先拿到一个 Agent 实例（或被迫 `BaseAgent.xxx`
这种对基类的硬依赖）。搬出来之后 `BaseAgent` 上仍保留**同名薄壳**，见下。

## ★ 三条口径必须一致，否则静默错位

`iterations_in_current_turn` / `tool_activity_in_turn` /
`previous_turn_was_clarification` 三者的切轮口径**必须完全一致**：都锚在
「最后一条 `HumanMessage` 之后」（`previous_turn_was_clarification` 取的是
它**之前**那一段）。口径不一致**不会报错**，只会让摘要、迭代计数、追问判定
在多轮会话里指向不同的两段 —— 这是本仓第 159 / 250 轮各咬过一次的形态。

## ★ 与 `ai_infra/context.py` 的分工（不是重复实现）

  · `context.py` 回答「**多大**」：超窗口就折叠旧工具结果、整轮裁历史；
  · 本模块回答「**长得对不对**」与「**本轮是哪一段**」：配对断裂就剔孤儿、
    切轮只认 HumanMessage。两者都只作用在**发给模型的副本**上，都不改
    state / checkpoint（`sanitize_tool_call_pairing` 的立场，同
    `_sanitize_history_for_model`）。

## 消费方

  · `ai_infra/base_agent.py` —— 同名薄壳（`staticmethod`）+ `_llm_call_node`
    里的实际调用；★ 薄壳之所以必须留：`tests/` 里四处直接写
    `BaseAgent._iterations_in_current_turn(...)`，而 `self.` 查找还是
    monkeypatch 的通道（P0-6 五刀同一条方法论）。
  · `ai_infra/context.py` —— 注释里引用 `sanitize_tool_call_pairing` 的立场
    （文档指向，不是 import）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def content_text(content: Any) -> str:
    """把 `BaseMessage.content` 取成纯文本。

    ★ 第 346 轮新增。它的静态类型是 `str | list[str | dict]`（多模态内容块），
      而原先 `sanitize_tool_call_pairing` 里写的是 `(m.content or "").strip()`
      —— content 是**列表**时会抛
      `AttributeError: 'list' object has no attribute 'strip'`。
      mypy 的 union-attr 指的正是这个潜在崩溃。

    对 `str` 的输入与原来**逐字一致**（原样返回）；对列表取其中的文本块拼接。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return "" if content is None else str(content)


def sanitize_tool_call_pairing(messages: list) -> Tuple[list, int]:
    """清洗消息序列，修复 tool_calls / ToolMessage 配对断裂（读时自愈）。

    背景：checkpointer 恢复的历史里可能存在「AIMessage 带 tool_calls，但没有
    对应 ToolMessage」的孤儿消息（成因：工具执行中途异常、达成 max_iterations
    被强制结束、HITL 中断、或修复前的旧数据）。OpenAI 兼容 API（DashScope）
    对历史做严格校验，会以 400 拒绝整条会话：

        400 An assistant message with "tool_calls" must be followed by tool
        messages responding to each "tool_call_id".

    这里只清洗「传给 LLM 的副本」，**不修改 state / checkpoint**，
    保证历史仍可被 route() 的 prev_count、action 提取等逻辑正常读取。
    旧数据因此无需手工清理，任何会话都能自愈。

    Returns:
        (清洗后的消息列表, 被剔除/修剪的消息条数)
    """
    # 1) 声明方：所有 AIMessage 声明的 tool_call_id
    declared: set = set()
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in (getattr(m, "tool_calls", None) or []):
                if tc.get("id"):
                    declared.add(tc["id"])

    # 2) 响应方：所有 ToolMessage 回应的 tool_call_id
    responded = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
    }

    # 3) 有效集合 = 声明 ∩ 响应（双向都满足才算配对成功）
    valid = declared & responded

    changed = 0
    out: list = []
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            kept = [tc for tc in m.tool_calls if tc.get("id") in valid]
            if len(kept) != len(m.tool_calls):
                changed += 1
                m = m.model_copy(
                    update={"tool_calls": kept, "invalid_tool_calls": []}
                )
                # 剥空且无文本内容 → 整条丢弃，避免产生空 AIMessage
                # ★ 第 346 轮：`content` 是 `str | list[...]`，原写法
                #   `(m.content or "").strip()` 在列表形态下抛 AttributeError。
                #   统一走 `content_text`（对 str 与原行为逐字一致）。
                if not kept and not content_text(m.content):
                    continue
        elif isinstance(m, ToolMessage):
            # 孤立的 ToolMessage（其 AIMessage 已不在或未声明该 id）→ 丢弃
            if getattr(m, "tool_call_id", None) not in valid:
                changed += 1
                continue
        out.append(m)

    return out, changed


def iterations_in_current_turn(messages: list) -> int:
    """统计「本轮」的 AI 迭代次数（最后一条 HumanMessage 之后的 AIMessage 数）。

    为什么不能直接数全部 AIMessage：
    checkpointer 恢复的 messages 是**跨轮完整历史**。若直接用「AIMessage 总数」
    判断迭代上限，多轮会话累积几条 AIMessage 后就会立刻判定「已达上限」，
    症状是——
      • `_llm_call_node`：每轮都被判超限，强制清空 tool_calls；
      • `_should_continue`：直接 return "respond"，永不进入 tool_node。
    结果 LLM 再也无法调用任何工具，前端一直收到「处理完成」、actions 为空。

    因此迭代计数必须锚定在**本轮输入**（最后一条 HumanMessage）之后。
    LLM 只产出 AIMessage / ToolMessage，不会再产生 HumanMessage，
    故最后一条 HumanMessage 必然是本轮输入。
    """
    last_human_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage) or m.__class__.__name__ == "HumanMessage":
            last_human_idx = i
    turn_messages = messages[last_human_idx + 1:]
    return sum(
        1 for m in turn_messages
        if isinstance(m, AIMessage) or m.__class__.__name__ == "AIMessage"
    )


def tool_activity_in_turn(messages: list) -> Dict[str, Any]:
    """把「本轮」的工具活动收成**结构化摘要**（第 159 轮 批 D1：委派契约）。

    返回 `{"tool_calls": [名…], "tool_result": …, "reply": …}`；
    **本轮没有任何工具活动时返回 `{}`** —— 不是「全空骨架」：
    恒带三个空键会让消费方分不清「这轮没调工具」与「摘要压根没生成」。

    ★ 为什么必须有它（批 D1 的另一半）：
      父层（`listing` / `product_research` 的路由子层调用方）此前必须
      **自己扫整段 `messages`** 才能还原「调了哪个工具、结果是什么、
      最后由谁作答」—— 也就是「拿原始 state 自行组装业务响应」。
      那种写法让父层对**历史形态**（消息顺序 / 类型 / 条数）产生硬依赖：
      换个图、加个节点、改一次上下文裁剪，父层的解析就**静默错位**
      （不报错，只是工具名变空 ⇒ `display_type` 退化成默认值）。
      摘要把这件事前移到**源头**（`_respond_node`），父层只依赖契约。

    ★ 为什么切轮口径与 `iterations_in_current_turn` **完全一致**：
      都锚在「最后一条 `HumanMessage` 之后」。两份口径若不一致，
      摘要与迭代计数会在多轮会话里指向不同的两段 —— 而**不会报错**。

    ★ 为什么 `tool_calls` 保序去重：父层要的是「这轮用了哪些工具」（用于定
      `display_type`），同一工具调 3 次不该产生 3 个候选。

    ★ 为什么 `tool_result` 取**最后一个非空**：工具链的最后一步才是决定性的
      （前置工具常常只做查询）。

    ★ 为什么**不截断** `tool_result`：父层把它交给 `_parse_tool_output` 解析 JSON，
      截断会破坏解析。体积上不会累积 —— `structured_response` 是每轮**覆盖写**
      的终态快照，只保留最新一份。
    """
    last_human_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage) or m.__class__.__name__ == "HumanMessage":
            last_human_idx = i
    turn = messages[last_human_idx + 1:]

    names: List[str] = []
    tool_result = None
    reply = ""
    for m in turn:
        cn = m.__class__.__name__
        if isinstance(m, AIMessage) or cn == "AIMessage":
            for tc in (getattr(m, "tool_calls", None) or []):
                name = tc.get("name") if isinstance(tc, dict) else None
                if name and name not in names:
                    names.append(name)
            if getattr(m, "content", None):
                reply = m.content
        elif isinstance(m, ToolMessage) or cn == "ToolMessage":
            if getattr(m, "content", None):
                tool_result = m.content

    # ★ 判据是「**有没有工具活动**」，不是「有没有内容」：
    #   只有 AI 回复、没调工具的轮次同样返回 `{}` ⇒ 父层走回退路径扫历史
    #   （那条路径能拿到 reply），行为与改造前**完全一致**。
    if not names and tool_result is None:
        return {}
    out: dict = {}
    if names:
        out["tool_calls"] = names
    if tool_result is not None:
        out["tool_result"] = tool_result
    if reply:
        out["reply"] = reply
    return out


def previous_turn_was_clarification(messages: list) -> bool:
    """上一轮是不是「追问 / 澄清」—— 本判定**只有这一份实现**（第 250 轮）。

    ★ 为什么需要它（一次真实漏判）：
      工具环路的 LLM 信息不足时不会硬凑结果，它会**反问**（如「你想基于
      哪一期？」）。老板的答案（「基于月报」）**必然包含追问里的关键词** ——
      因为那正是被问到的词。于是各 Agent 的「关键词命中即短路」会把答案
      当成一个**新任务**直接执行，追问就此丢失。
      这是**结构性**的：问句与答案是同一批词，任何纯关键词判定都躲不开。

    ★ 判据：上一轮**有最终回复、但一个工具都没调** ⇒ 它不是在产出结果，
      而是在问话。反过来，只要调过工具，那一轮就是在干活（哪怕最后还补了
      一句说明文字）⇒ 不是追问。

    ★ 切轮口径与 `iterations_in_current_turn` / `tool_activity_in_turn`
      **完全一致**：都锚在「最后一条 `HumanMessage` 之后」。「上一轮」= 最后
      一条 `HumanMessage` **之前**、上一条 `HumanMessage` **之后**的那一段。
      三份口径若不一致，在多轮会话里会指向不同的两段 —— 而**不会报错**。

    ★ 为什么**不**复用 `tool_activity_in_turn`：它对本轮**无工具活动**恒返回
      `{}`，把「纯文本回复」与「什么都没有」压成同一个值；而本判定要区分的
      恰恰是这两者 ⇒ 必须自己扫。这是刻意的不复用，不是漏掉。

    ★ 第 400 轮：从 `BaseAgent` 的 `@staticmethod` 搬到本模块。`BaseAgent`
      上仍留**同名属性**（`staticmethod(...)` 赋值，不是 `def`）⇒
      「全仓只有一份实现」的门禁（`test_review_clarification_answer.py`）
      数的仍是 1，而 `self.previous_turn_was_clarification(...)` 的调用形态不变。
    """
    msgs = messages or []
    human_idx = [
        i for i, m in enumerate(msgs)
        if isinstance(m, HumanMessage) or m.__class__.__name__ == "HumanMessage"
    ]
    if not human_idx:
        return False
    end = human_idx[-1]
    start = human_idx[-2] + 1 if len(human_idx) >= 2 else 0
    has_reply = False
    has_tool = False
    for m in msgs[start:end]:
        cn = m.__class__.__name__
        if isinstance(m, AIMessage) or cn == "AIMessage":
            if getattr(m, "content", None):
                has_reply = True
            if getattr(m, "tool_calls", None):
                has_tool = True
        elif isinstance(m, ToolMessage) or cn == "ToolMessage":
            has_tool = True
    return has_reply and not has_tool


def carried_tokens(state: Mapping[str, Any], *, iterations_done: int) -> int:
    """本轮**此前**已消耗的 token（0 表示本轮第一次迭代）。

    ★ 为什么从 state 读、不记在实例上：Agent 实例是**进程内单例**
      （`get_secretary_agent()` 就是），记在 `self` 上等于把一个会话的
      耗用记到另一个会话头上 —— 并发下预算会随机误伤。state 随图执行走，
      一次调用一份。

    ★ 为什么 `iterations_done == 0` 一定要归零：`state["budget"]` 会随
      checkpointer **跨轮持久化**。不归零的话预算会被历史越攒越多，
      一个健康的会话聊到第 N 轮突然被判「token 超限」。口径与
      `iterations_in_current_turn` 一致：预算按**轮**算，不按会话算。
    """
    if iterations_done <= 0:
        return 0
    return int((state.get("budget") or {}).get("spent_tokens") or 0)

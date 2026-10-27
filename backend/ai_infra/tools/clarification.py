"""澄清工具 —— HITL 里「问」的那一半（第 145 轮 · 批 B3；第 400 轮 P0-3 改为真挂起）。

## 为什么需要它

改造前，「参数不够就问一句」这件事**只存在于提示词里**：

    # modules/secretary/agent.py 的 SECRETARY_SYSTEM_PROMPT
    6.【重要】老板提出专业生成类需求但关键信息不足（≥2 个核心参数缺失）时，
      调 handoff_to_agent 交接给专职 Agent 追问，不要自己硬凑。

这是**规则**，不是**能力**。规则的问题在于：模型不遵守时没有任何信号 ——
它不会报错，只会「硬凑一个默认值」或者「默默交接走」。而且 `handoff_to_agent`
本身是**交接**（产出 `{"action": "handoff"}` 交给前端切 Agent），不是**提问**：
即便走通了，也是「换个人来问」，而不是「在当前会话里问清楚」。

本模块把「提问」做成**工具**：

* 它可被 LLM 自主选择（与其它工具同权，受同一套 prompt 与 schema 约束）；
* 它的产出是**结构化数据**（`type=clarification_request`），前端可以像
  `PendingApprovalCard` 消费审批请求那样消费它 —— 渲染成提问卡而不是一段文字；
* 它明确声明**不执行任何动作**（`metadata=READ_ONLY_METADATA`），
  所以它自己不需要审批 —— 「问一句」不该被审批闸门拦住。

## 第 400 轮 P0-3：从「吐字符串」改成「真挂起」

改造前它只是 `return json.dumps(payload)` —— 模型读到这条 tool result 后
**在正文里把问题复述一遍**，本轮就结束了。于是：

* 老板回答的那句话进的是**下一轮的新对话**，模型不记得自己问过什么
  （上一轮的 AIMessage 只有 `tool_calls`，没有正文可承接）；
* 前端没有任何结构化入口 —— `clarification_request` 这个 type **零消费者**，
  「协议定义了、执行侧只吐字符串、UI 侧没人接」＝ 半条链。

现在在工具内部调 `interrupt(payload)`：图停在**这一步**，前端渲染提问卡，
老板的回答经 `Command(resume=...)` 回到 `interrupt()` 的**返回值**，
工具再把答案作为 tool result 交回模型 —— **同一轮继续**，模型自己记得问过什么。

## ★★ 两个必须知道的坑

① `interrupt()` 的「暂停」是**抛异常**实现的（`GraphInterrupt` → `GraphBubbleUp`
   → `Exception`）。所以降级用的 `except Exception` **必须把 `GraphBubbleUp`
   先接住再抛出去**，否则「暂停」会被当成「环境不支持」吞掉 ——
   表现是：卡片不出现、正文照旧复述问题，而且**一条日志都没有**。
② `config` 的参数注解必须**逐字**是 `RunnableConfig`。写成
   `Optional[RunnableConfig]` 会让 langchain 的注入识别失效（它不认这个注解）⇒
   工具拿不到 config ⇒ **永远不挂起且零报错**（eEducation 第 559 轮实测）。

## 降级（没有会话 / 没有 checkpointer 时）

`interrupt()` 在非图上下文里会抛 `RuntimeError`（`get_config()` 无 run）。
这时退回改造前的行为：把 payload 当 tool result 返回，让模型在正文里反问。
**降级不静默** —— 日志里带 `clarification-degraded` 标记，payload 里带
`suspend: "unavailable"`（前端据此知道"这次没有卡片，别等"）。

## 为什么它在 `ai_infra` 而不是某个业务模块

「参数不足就提问」是与业务无关的**交互模式**（类比 `AgentState` 的消息协议）。
工具名 `ask_clarification`、字段 `question` / `options` / `missing_fields`
都不含业务语义，因此放在基础设施层不违反分层门禁
（`tests/test_infra_layering.py`）。

★ 对照组：`handoff_to_agent` 仍在 `modules/secretary/navigation_tools.py` ——
  因为它产出的 `{"action": "handoff", "agent_id": ...}` 是**业务动作**（跨 Agent 路由），
  与「提问」不是一回事。两者都需要：先在当前会话问清楚，问不清楚再交接。

## 前端的消费契约

挂起时 `interrupt()` 的 value（= 前端卡片拿到的 `data`）形如：

    {
      "type": "clarification_request",
      "action": "ask_user",
      "question": "做这张主图时，你希望突出什么卖点？",
      "options": [{"label": "防水", "description": "...", "recommended": true}, ...],
      "missing_fields": ["卖点"],
      "status": "awaiting_user_input"
    }

老板回答后，工具读到的 resume 值会变成：

    {"type": "clarification_answer", "question": "...", "answer": "...", "status": "ok"}

★ `status` 是**给编排层看的**：与业务成功的 `success: true` 区分开。
  它表达的是「这一轮没有完成任何动作，在等老板回话」——
  与「失败」也不同（不是错误，是正常的交互中间态）。

★ 选项**对象化**（`{label, description?, recommended?}`）但**不设上限**：
  eEducation 那边卡在 4 个（他们的 UI 只排得下 4 个）。我们这边卡片是可滚动的
  单选列表，截断反而是**静默丢信息** —— 模型给了 6 个候选项，老板只看到 4 个，
  而没人会去数「怎么少了两个」。旧形态（纯字符串）仍然接受，归一化在这里做。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from ai_infra.tools.side_effects import READ_ONLY_METADATA

#: 澄清请求的类型标记（前端据此选择渲染组件；不要与 `type` 的其它取值混用）。
CLARIFICATION_TYPE = "clarification_request"

#: 澄清**回答**的类型标记（工具续跑后交回模型的那条 tool result）。
CLARIFICATION_ANSWER_TYPE = "clarification_answer"

#: 等待用户输入的状态标记（区别于成功 / 失败）。
CLARIFICATION_STATUS = "awaiting_user_input"

#: 工具名（唯一真源 —— 注册表、测试、前端都引用它）。
CLARIFICATION_TOOL_NAME = "ask_clarification"

CLARIFICATION_DESCRIPTION = (
    "向老板**提问**以补齐继续执行所必需的信息，**本身不执行任何动作**。"
    "当关键参数缺失（例如要做图但没说材质 / 视角 / 卖点）、或同一句话有两种"
    "合理解读时，用这个工具把问题**显式问出来**，而不是自己猜一个默认值硬做、"
    "也不要为此把对话交接走。\n"
    "调用后本轮会**停在这里**等老板回答，答案会自动接回这一步 —— "
    "所以你不需要在正文里再重复一遍问题。\n"
    "参数：question —— 要问的问题（可含多个子问题，用换行分隔）；"
    "options —— 可选，候选答案列表（能枚举就给，让老板点选而不是手打；"
    "元素可以是字符串，也可以是 {label, description, recommended} 对象）；"
    "missing_fields —— 可选，缺失字段名清单（便于界面高亮「在等什么」）。"
)


def normalize_options(options: Optional[list]) -> list[dict]:
    """把选项归一成 `{label, description?, recommended?}` 对象列表。

    ★ 为什么在这里归一而不是让前端兼容两种形态：**两处解析＝两份实现**，
      而漂移的表现是前端把整个对象当字符串渲染成 `[object Object]`
      （本仓判过同族问题）。模型偶尔会照旧给字符串，所以输入侧必须宽容；
      输出侧只能是**一种**形态。
    """
    out: list[dict] = []
    for o in (options or []):
        if isinstance(o, dict):
            label = str(o.get("label") or o.get("text") or o.get("value") or "").strip()
            if not label:
                continue
            item: dict = {"label": label}
            desc = str(o.get("description") or "").strip()
            if desc:
                item["description"] = desc
            if o.get("recommended"):
                item["recommended"] = True
            out.append(item)
        else:
            s = str(o).strip()
            if s:
                out.append({"label": s})
    return out


def build_clarification_payload(
    question: str,
    options: Optional[list] = None,
    missing_fields: Optional[list] = None,
) -> dict:
    """组装澄清请求体（唯一实现 —— 工具与测试都走它，避免两处结构漂移）。"""
    return {
        "type": CLARIFICATION_TYPE,
        "action": "ask_user",
        "question": question,
        "options": normalize_options(options),
        "missing_fields": [str(f) for f in (missing_fields or []) if str(f).strip()],
        "status": CLARIFICATION_STATUS,
    }


def _answer_text(answer: Any) -> str:
    """把 `Command(resume=...)` 带回来的值读成一句话。

    ★ 容忍三种形态：裸字符串（前端图省事）、`{answer: ...}`（本模块的规范形态）、
      其它（`str()` 兜底）。宽容的代价远小于「用户答了但模型看到空串」。
    """
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer.strip()
    if isinstance(answer, dict):
        for key in ("answer", "text", "value", "feedback"):
            v = answer.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(answer).strip()


async def ask_clarification(
    question: str,
    options: Optional[list] = None,
    missing_fields: Optional[list] = None,
    # ★★ 注解必须**逐字**是 `RunnableConfig`（见模块头注释坑 ②）。
    #   加了 `Optional[...]` 之后 langchain 不再把它当注入参数 ⇒ 永远不挂起。
    config: RunnableConfig = None,  # noqa: ARG001 —— 仅供 langgraph 注入，本函数不直接读
) -> str:
    """澄清工具的实现体：**把图停在这里**，等老板回答后再继续。

    返回值永远是**合法 JSON 字符串**（tool result 必须是字符串）：

    * 挂起后恢复 ⇒ `{"type": "clarification_answer", "answer": "...", ...}`
    * 无法挂起   ⇒ 澄清请求体本身 + `"suspend": "unavailable"`（降级为正文反问）

    ★ 为什么 `question` 为空要显式拒绝而不是照样返回：空问题会让前端渲染出
      一张没有内容的卡片 —— 用户那边表现为「AI 卡住了」，而这实际上是
      LLM 调用参数错误。宁可返回一个可读的失败，也不要产出一张空卡。
    """
    q = (question or "").strip()
    if not q:
        return json.dumps(
            {
                "type": CLARIFICATION_TYPE,
                "status": "error",
                "error": "澄清问题为空 —— 请提供 question（要问老板什么）。",
            },
            ensure_ascii=False,
        )

    payload = build_clarification_payload(q, options, missing_fields)

    try:
        answer = interrupt(payload)
    except GraphBubbleUp:
        # ★★ 这就是「暂停」本身（langgraph 用异常冒泡中断图）—— 必须原样抛出。
        #   被 `except Exception` 吞掉的话，图根本不会停，且**没有任何痕迹**。
        raise
    except Exception as e:  # noqa: BLE001 —— 无会话 / 无 checkpointer / 不在图上下文
        # 降级：退回改造前的行为（模型在正文里反问）。**不静默** ——
        # 日志带固定标记，payload 带 `suspend: unavailable`。
        from core.logger import get_logger

        get_logger("tools.clarification").warning(
            f"clarification-degraded: interrupt 不可用（{type(e).__name__}: {e}）"
            " —— 本轮退回「正文反问」，前端不会出现提问卡"
        )
        return json.dumps(
            {**payload, "suspend": "unavailable"}, ensure_ascii=False
        )

    text = _answer_text(answer)
    return json.dumps(
        {
            "type": CLARIFICATION_ANSWER_TYPE,
            "question": q,
            "answer": text,
            # ★ 空答案也要回给模型（而不是在这里报错）：它可能只是老板点了「跳过」，
            #   模型据此决定再问一次还是按已知信息先做 —— 这个判断属于业务，
            #   不属于工具。`status` 让模型能一眼分辨"答了"与"没答"。
            "status": "ok" if text else "empty",
        },
        ensure_ascii=False,
    )


def make_clarification_tool() -> BaseTool:
    """构造 `ask_clarification` 工具（供各 Agent 装配）。

    ★ 为什么是工厂而不是模块级单例：与 `build_product_tools()` / `build_shop_tools()`
      一致 —— 调用方拿到的是一份可以自由组合进自己注册表的工具。
      （同时也是为了不在本模块留下"可被别处改坏"的共享对象。）
    """
    return StructuredTool.from_function(
        coroutine=ask_clarification,
        name=CLARIFICATION_TOOL_NAME,
        description=CLARIFICATION_DESCRIPTION,
        metadata=READ_ONLY_METADATA,
    )


__all__ = [
    "CLARIFICATION_TYPE",
    "CLARIFICATION_ANSWER_TYPE",
    "CLARIFICATION_STATUS",
    "CLARIFICATION_TOOL_NAME",
    "CLARIFICATION_DESCRIPTION",
    "build_clarification_payload",
    "normalize_options",
    "ask_clarification",
    "make_clarification_tool",
]

"""澄清工具 —— HITL 里「问」的那一半（第 145 轮 · 批 B3）。

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
  `PendingApprovalCard` 消费审批请求那样消费它 —— 渲染成选项卡片而不是一段文字；
* 它明确声明**不执行任何动作**（`metadata=READ_ONLY_METADATA`），
  所以它自己不需要审批 —— 「问一句」不该被审批闸门拦住。

## 为什么它在 `ai_infra` 而不是某个业务模块

「参数不足就提问」是与业务无关的**交互模式**（类比 `AgentState` 的消息协议）。
工具名 `ask_clarification`、字段 `question` / `options` / `missing_fields`
都不含业务语义，因此放在基础设施层不违反分层门禁
（`tests/test_infra_layering.py`）。

★ 对照组：`handoff_to_agent` 仍在 `modules/secretary/navigation_tools.py` ——
  因为它产出的 `{"action": "handoff", "agent_id": ...}` 是**业务动作**（跨 Agent 路由），
  与「提问」不是一回事。两者都需要：先在当前会话问清楚，问不清楚再交接。

## 前端的消费契约（与本模块同批定义，避免两边对着猜）

返回体形如：

    {
      "type": "clarification_request",
      "action": "ask_user",
      "question": "做这张主图时，你希望突出什么卖点？",
      "options": ["防水", "轻便", "续航", "性价比"],
      "missing_fields": ["卖点"],
      "status": "awaiting_user_input"
    }

★ `status` 是**给编排层看的**：与业务成功的 `success: true` 区分开。
  它表达的是「这一轮没有完成任何动作，在等老板回话」——
  与「失败」也不同（不是错误，是正常的交互中间态）。
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import BaseTool, StructuredTool

from ai_infra.tools.side_effects import READ_ONLY_METADATA

#: 澄清请求的类型标记（前端据此选择渲染组件；不要与 `type` 的其它取值混用）。
CLARIFICATION_TYPE = "clarification_request"

#: 等待用户输入的状态标记（区别于成功 / 失败）。
CLARIFICATION_STATUS = "awaiting_user_input"

#: 工具名（唯一真源 —— 注册表、测试、前端都引用它）。
CLARIFICATION_TOOL_NAME = "ask_clarification"

CLARIFICATION_DESCRIPTION = (
    "向老板**提问**以补齐继续执行所必需的信息，**本身不执行任何动作**。"
    "当关键参数缺失（例如要做图但没说材质 / 视角 / 卖点）、或同一句话有两种"
    "合理解读时，用这个工具把问题**显式问出来**，而不是自己猜一个默认值硬做、"
    "也不要为此把对话交接走。\n"
    "参数：question —— 要问的问题（可含多个子问题，用换行分隔）；"
    "options —— 可选，候选答案列表（能枚举就给，让老板点选而不是手打）；"
    "missing_fields —— 可选，缺失字段名清单（便于界面高亮「在等什么」）。"
)


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
        "options": [str(o) for o in (options or [])],
        "missing_fields": [str(f) for f in (missing_fields or [])],
        "status": CLARIFICATION_STATUS,
    }


async def ask_clarification(
    question: str,
    options: Optional[list] = None,
    missing_fields: Optional[list] = None,
) -> str:
    """澄清工具的实现体：**只组装并返回请求体，不产生任何副作用**。

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
    return json.dumps(payload, ensure_ascii=False)


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
    "CLARIFICATION_STATUS",
    "CLARIFICATION_TOOL_NAME",
    "CLARIFICATION_DESCRIPTION",
    "build_clarification_payload",
    "ask_clarification",
    "make_clarification_tool",
]

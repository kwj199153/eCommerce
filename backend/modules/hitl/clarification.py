# -*- coding: utf-8 -*-
"""会话横切层 —— **澄清挂起**（第 400 轮 P0-3）。

## 为什么它单独一个文件（而不是塞进 `hitl.py`）

`hitl.py` 讲的是「一次工具调用停下来等人**拍板**」，本文件讲的是
「一次对话停下来等人**回话**」。两者共享的是「图停住了、要人、要续跑」
这套机制，不同之处在于：

| | 审批（approval） | 澄清（clarification） |
|---|---|---|
| 停在哪 | `_wrap_hitl_tools` 包的**写工具**内 | `ask_clarification` **工具**内 |
| 前端卡片 | 批准 / 拒绝 / 改写 / 回复 四档 | 选项 + 一句话 |
| 续跑值 | `{"type": "accept", ...}`（包装器协议） | 老板的原话（工具直接读） |
| 有没有副作用 | 有（放行后真执行） | 无（只问一句） |

混进 `hitl.py` 会让「四档决策」这个审批专有的概念被澄清复用，
而它的语义（`accept/reject/edit/response`）对纯提问毫无意义。

## 契约

与 `hitl.py` 一致：返回**中立 dict** `{content, data, display_type}`，
由各 Agent 自己包成它的响应类型。`display_type` 与
`ai_infra.tools.clarification.CLARIFICATION_TYPE` **逐字相同**
（`"clarification_request"`）—— 前端按它选卡片。

★ 常量从 `ai_infra` **import 而不是重写一遍**：两处各写一份字符串，
  改名时漏一处就是「后端发了、前端认不出、静默按纯文本渲染」。
  门禁 `tests/test_hitl_layer_shape.py::test_no_business_imports`
  的白名单里放行 `ai_infra`（它是底座，不含业务语义），
  仍然禁止 `modules.*`（那才是这一层要隔离的东西）。

## 这一层不许做什么

与 `hitl.py` 相同：不 import 业务模块、不碰数据库、不构造业务响应类型。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from core.logger import get_logger

from ai_infra.tools.clarification import (
    CLARIFICATION_ANSWER_TYPE,
    CLARIFICATION_TYPE,
)

__all__ = [
    "DISPLAY_CLARIFICATION",
    "DISPLAY_CLARIFICATION_ANSWERED",
    "CLARIFICATION_TYPE",
    "pending_clarification_payload",
    "clarification_from_state",
    "detect_pending_clarification",
    "build_clarification_resume",
]

logger = get_logger("conversation.clarification")

#: 前端据此渲染「提问卡」。★ 与 `ai_infra.tools.clarification.CLARIFICATION_TYPE` 同源
DISPLAY_CLARIFICATION = CLARIFICATION_TYPE
DISPLAY_CLARIFICATION_ANSWERED = CLARIFICATION_ANSWER_TYPE

#: 只回传「谁在问」需要的最小事实；`thread_id` 一律不出服务端（同审批的口径）。
_PAYLOAD_FIELDS = ("action", "question", "options", "missing_fields", "status")


def pending_clarification_payload(
    interrupt_obj, context_id: Optional[str], agent_id: Optional[str] = None
) -> Optional[dict]:
    """把一次「澄清型中断」渲染成前端可展示的提问卡；不是澄清就返回 `None`。

    ★ 为什么用 `None` 而不是抛错：调用方拿到的是**任意**中断 ——
      图可能停在审批上（同一个 Agent 既有写工具也有提问工具）。
      判定职责在这里，调用方只需要 `if payload is not None`。

    ★ 刻意**不回传 `thread_id`**（与审批同一个理由）：前端把同一个
      `session_id` 交回来，服务端按与首轮完全相同的口径重算 thread_id。
      把 thread_id 交给客户端等于把「这条待回答的提问归谁」交给请求方。
    """
    value = getattr(interrupt_obj, "value", None)
    if not isinstance(value, dict) or value.get("type") != CLARIFICATION_TYPE:
        return None

    question = str(value.get("question") or "").strip()
    if not question:
        # 空问题＝渲染出一张没有内容的卡（用户侧表现为"卡住了"）。
        # 这不是「没有澄清」，而是「模型给了个坏澄清」—— 记日志，当没有。
        logger.warning("clarification interrupt 的 question 为空，已跳过（模型调用参数有误）")
        return None

    data = {k: value.get(k) for k in _PAYLOAD_FIELDS if k in value}
    data["type"] = CLARIFICATION_TYPE
    data["agent"] = agent_id
    data["session_id"] = context_id
    data["interrupt_id"] = getattr(interrupt_obj, "id", None)
    data["options"] = data.get("options") or []
    data["missing_fields"] = data.get("missing_fields") or []

    return {
        # 正文就是问题本身 —— 卡片渲染失败时用户仍然读得到要回答什么
        # （「卡片没出来 ⇒ 什么都没显示」是最糟的降级）。
        "content": question,
        "data": data,
        "display_type": DISPLAY_CLARIFICATION,
    }


def clarification_from_state(
    state: Any, context_id: Optional[str], agent_id: Optional[str] = None
) -> Optional[dict]:
    """从 `graph.ainvoke()` 返回的**状态字典**里取澄清挂起（不查库）。

    ★ 为什么需要这个入口：`ainvoke` 的返回值里就带着 `__interrupt__`
      （流式与非流式都有 —— 流式只是过程不可见，最终状态是一样的），
      没必要为此再 `aget_state()` 打一次库。店秘书走的就是这条。
    ★ `aget_state()` 版本（`detect_pending_clarification`）留给"手上只有
      会话 ID"的调用方（例如多 Agent 编排里回头看一眼），两者判定逻辑同源
      —— 都落到 `pending_clarification_payload`。
    """
    if not isinstance(state, dict):
        return None
    interrupts = state.get("__interrupt__") or ()
    if not isinstance(interrupts, (list, tuple)):
        interrupts = (interrupts,)
    for it in interrupts:
        payload = pending_clarification_payload(it, context_id, agent_id)
        if payload is not None:
            return payload
    return None


async def detect_pending_clarification(
    context_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    get_router: Callable[[], Any],
    log_tag: str = "clarification",
    agent_id: Optional[str] = None,
) -> Optional[dict]:
    """按会话 ID 探一次「这张图此刻是不是停在一次澄清上」。

    ★ 为什么必须先确认 `context_id and user_id`：缺任一时
      `graph_for_session()` 返回**不带 checkpointer** 的图，
      对它调 `aget_state()` 会直接抛（"checkpointer 未设置"）。
    """
    if not (context_id and user_id):
        return None

    router = get_router()
    if router is None or getattr(router, "checkpointer", None) is None:
        return None

    try:
        graph, cfg = router.graph_for_session(context_id, user_id)
        snapshot = await graph.aget_state(cfg)
    except Exception as e:  # noqa: BLE001 —— 探测失败不该让整轮对话崩
        logger.warning(f"[{log_tag}] pending-clarification probe failed: {e}")
        return None

    for task in (getattr(snapshot, "tasks", None) or []):
        for it in (getattr(task, "interrupts", None) or []):
            payload = pending_clarification_payload(it, context_id, agent_id)
            if payload is not None:
                return payload
    return None


def build_clarification_resume(answer: str) -> dict:
    """把老板的原话包成 `Command(resume=...)` 的值。

    ★ 为什么包一层 dict 而不是直接传字符串：`ask_clarification` 要能区分
      「这是一句回答」与「这是别的东西」（同一个 `interrupt()` 位置将来可能
      承载别的形态）。工具侧 `_answer_text()` 对裸字符串也兼容。
    """
    return {"type": DISPLAY_CLARIFICATION_ANSWERED, "answer": answer}

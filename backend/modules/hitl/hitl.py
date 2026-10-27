# -*- coding: utf-8 -*-
"""会话横切层 —— 与具体业务 Agent 无关的 **HITL 审批** 与 **澄清挂起**。

## 为什么要有这一层

第 399 轮对标发现：`modules/product_research/agent_hitl.py` 里的 5 个函数
（`pending_approval_from_interrupt` / `build_resume_payload` /
`unwrap_hitl_tool_output` / `detect_pending_approval` / `resume_approval`）
除了 import 一个 `AgentResponse` 之外，**与选品业务毫无关系** ——
它描述的是「一次工具调用停下来等人拍板」这件普适的事。

后果（第 400 轮实测）：智能客服的 `create_ticket` 与 trade 域的
`propose_review_disposition` 明明声明了 `side_effect=write`、也确实被
`_wrap_hitl_tools()` 包上了 `interrupt()`，但**整条闭环只接通了选品分析师**
—— resume 端点、审批卡渲染、编排全部绑死在 `product-research` 上。
于是那两个工具在生产上永远抛 `HITLPrerequisiteError`。

⇒ 本层把「审批的领域逻辑」从业务模块里摘出来，**返回中立 dict payload**
（`content` / `data` / `display_type`），由各 Agent 自己包成它的响应类型。
这样：
  · 逻辑只有**一份**（不会长出「选品弹卡、客服静默吞掉」的不一致）；
  · 各 Agent 的响应类型不被强行统一（本仓 5 个 `AgentResponse` 副本字段相同
    但类身份不同，合并它们属于另一件事）。

## 契约

每个函数返回的 dict 都是**可直接解包**进任一 Agent 的响应模型：

    {"content": str, "data": dict, "display_type": str}

`display_type` 是前端选择结果卡的唯一依据，取值见 `DISPLAY_*` 常量。

## 这一层不许做什么

  · 不 import 任何业务模块（`modules.product_research` / `modules.customer_service` …）；
  · 不 import 数据库 / 会话持久化 / 平台取数；
  · 不自己构造业务响应类型（只吐 dict）。

门禁：`tests/test_conversation_hitl_layer.py`。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from core.logger import get_logger
from langgraph.types import Command

__all__ = [
    "DISPLAY_PENDING_APPROVAL",
    "DISPLAY_APPROVAL_RESOLVED",
    "DISPLAY_APPROVAL_FAILED",
    "pending_approval_payload",
    "build_resume_payload",
    "unwrap_hitl_tool_output",
    "detect_pending_approval",
    "resume_approval",
]

logger = get_logger("conversation.hitl")

#: 前端据此渲染「审批卡」。★ 与 `display_type` 的其它取值（table / chart / text…）
#: 同一命名空间，改名必须同步前端（`frontend/src/api/agentApproval.ts` 的判据）。
DISPLAY_PENDING_APPROVAL = "pending_approval"
DISPLAY_APPROVAL_RESOLVED = "approval_resolved"
DISPLAY_APPROVAL_FAILED = "approval_failed"


def pending_approval_payload(interrupt_obj, context_id: Optional[str]) -> dict:
    """把 LangGraph 的 `Interrupt` 渲染成前端可直接展示的审批请求。

    ★ 刻意**不回传 `thread_id`**：前端只要把同一个 `session_id` 交回来，
      服务端会按**与首轮完全相同的口径**重算 thread_id
      （`BaseAgent.resolve_thread_id`）。把 thread_id 交给客户端，等于把
      「这条待审批操作归谁」交给请求方 —— 而 thread_id 里就含 user_id。
    """
    req = getattr(interrupt_obj, "value", None) or {}
    action = (req.get("action_request") or {}) if isinstance(req, dict) else {}
    tool_name = action.get("action") or "未知操作"
    return {
        "content": (
            f"这一步需要你确认：准备执行「{tool_name}」，"
            "在批准之前它不会被真正执行。请选择「批准」或「拒绝」。"
        ),
        "data": {
            "type": DISPLAY_PENDING_APPROVAL,
            "approval": {
                "interrupt_id": getattr(interrupt_obj, "id", None),
                "action": tool_name,
                "args": action.get("args") or {},
                "require_reason": bool(action.get("require_reason")),
                "timeout_seconds": action.get("timeout"),
                "description": req.get("description") or "",
            },
            "session_id": context_id,
        },
        "display_type": DISPLAY_PENDING_APPROVAL,
    }


def build_resume_payload(
    decision: str,
    *,
    reason: Optional[str] = None,
    args: Optional[dict] = None,
    feedback: Optional[str] = None,
) -> dict:
    """把外部的「决策」翻译成 `hitl_decorator.call_tool_with_hitl` 认得的载荷。

    ★ 契约在包装器那一侧（`response.get("type")` /
      `response.get("args", {}).get(...)`）。两边结构必须逐字段对齐 ——
      结构对不上的表现是「点了批准但什么都没发生」（`type` 认不出 ⇒
      落到 else 分支抛 `不支持的 HITL 响应类型`），而不是任何显式报错。
    """
    d = (decision or "").strip().lower()
    if d == "accept":
        return {"type": "accept", "args": {}}
    if d == "reject":
        return {"type": "reject", "args": {"reason": reason or "未提供原因"}}
    if d == "edit":
        if not isinstance(args, dict) or not args:
            raise ValueError("decision=edit 时必须提供非空的 args（改写后的工具入参）")
        return {"type": "edit", "args": {"args": args}}
    if d == "response":
        return {"type": "response", "args": feedback or ""}
    raise ValueError(
        f"不支持的审批决策: {decision!r}（可选 accept / reject / edit / response）"
    )


def unwrap_hitl_tool_output(raw: str) -> Optional[dict]:
    """从 HITL 包装器的返回文案里取回**内层工具的原始结构化结果**。

    包装器的返回形如：

        ✅ 操作已执行 [save_candidate]
        结果: {"type": "candidate_saved", ...}

    ★ 为什么值得做这层解包：审批通过后的结果应该与「没走审批」时
      **长得一模一样**（同一个结果卡、同一套字段）。否则前端要为
      「审批后」单独写一套渲染 —— 两边字段一旦漂移，就又回到
      「同一件事两种表现」的老问题。
    ★ 解包失败一律返回 `None`（调用方降级为展示原始文案），
      不让「文案改了」升级成「审批流程报错」。
    """
    if not raw:
        return None
    marker = "结果: "
    idx = raw.find(marker)
    if idx < 0:
        return None
    try:
        parsed = json.loads(raw[idx + len(marker):])
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else None


async def detect_pending_approval(
    context_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    get_router: Callable[[], Any],
    log_tag: str = "hitl",
) -> Optional[dict]:
    """判断「这张图此刻是不是停在一次人工审批上」；是则返回审批卡 payload。

    ★ 为什么走 `aget_state()` 而不是读 `ainvoke` 的返回值：
      流式与非流式都要判同一件事。非流式的 state 里有 `__interrupt__` 可读，
      但**流式没有**（`astream_events` 只给事件、不给最终 state）。
      两边各写一份判定，就会长出「非流式弹卡、流式静默吞掉」的不一致。
      `aget_state()` 对两条路径**语义完全相同**，是这里唯一正确的口径。

    ★ 为什么必须先确认 `context_id and user_id`：两者缺任一时
      `graph_for_session()` 返回的是**不带 checkpointer 的图**，
      对它调 `aget_state()` 会直接抛（连接层报 checkpointer 未设置）。

    ★ `log_tag` 只影响日志前缀，不参与判定 —— 出问题时要能看出是哪个
      Agent 探的（否则日志里全是 `[hitl]`，无法判断是谁在反复探测）。
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
        logger.warning(f"[{log_tag}] pending-approval probe failed: {e}")
        return None

    for task in (getattr(snapshot, "tasks", None) or []):
        for it in (getattr(task, "interrupts", None) or []):
            return pending_approval_payload(it, context_id)
    return None


def _failed(content: str, error: str, **extra) -> dict:
    return {
        "content": content,
        "data": {"type": DISPLAY_APPROVAL_FAILED, "error": error, **extra},
        "display_type": "text",
    }


async def resume_approval(
    context_id: str,
    decision: str,
    *,
    user_id: Optional[str] = None,
    shop_id: Optional[str] = None,
    reason: Optional[str] = None,
    args: Optional[dict] = None,
    feedback: Optional[str] = None,
    get_router: Callable[[], Any],
    bind_context: Callable[..., None],
    hydrate_state: Optional[Callable[..., Awaitable[None]]] = None,
    compose_reply: Optional[Callable[[dict], str]] = None,
    detect_pending: Optional[Callable[..., Awaitable[Optional[dict]]]] = None,
    log_tag: str = "hitl",
) -> dict:
    """把审批决策回传给**被中断的那张图**，让它续跑到结束。

    ★ 为什么必须重新 `bind_context()`：续跑时被中断的工具会**重新执行**，
      而它靠 ContextVar 拿会话与店铺归属（见各业务 `tools.py`）。
      不重新绑定 ⇒ `shop_id` 拿不到 ⇒ 写路径**硬拒绝** ——
      用户「批准了」却收到「请先选一个店铺」，是这条链路上最迷惑的表现。

    ★ `hydrate_state` / `detect_pending` / `compose_reply` 是**可选**的：
      选品有"会话状态要读回内存 + 多步审批 + 结果文案合成"三件事，
      客服没有（它的会话上下文在内存对象里，不受 checkpoint 影响）。
      用 `None` 表示"本 Agent 不需要"，而不是造一个空实现 ——
      空实现会让下一个人以为"这里真的做了一件事"。
    """
    router = get_router()
    if router is None:
        return _failed("审批通道暂时不可用（工具路由层未就绪），请稍后重试。",
                       "router_unavailable")
    if not (context_id and user_id):
        return _failed("审批必须带上会话与登录身份，否则定位不到你那条待审批的操作。",
                       "missing_session_or_identity")
    if getattr(router, "checkpointer", None) is None:
        return _failed("审批通道暂时不可用（会话存储未就绪），请稍后重试。",
                       "checkpointer_unavailable")

    try:
        payload = build_resume_payload(
            decision, reason=reason, args=args, feedback=feedback
        )
    except ValueError as e:
        return _failed(str(e), "bad_decision")

    # 续跑前重新绑定上下文（被中断的工具会重新执行，需要会话 + 归属 + 身份）
    # ★ 身份也要绑 —— 会话状态的作用域键含 user_id，漏传会让被中断的工具在
    #   **另一个作用域**里找会话状态（选品的 `_save_candidate` 要靠它把
    #   「第 1 个」解析成具体商品）。
    bind_context(context_id, shop_id, user_id)
    if hydrate_state is not None:
        await hydrate_state(context_id)

    graph, cfg = router.graph_for_session(context_id, user_id)
    try:
        state = await graph.ainvoke(Command(resume=payload), config=cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{log_tag}] resume failed: {e}")
        return _failed("审批回传失败，请重试；若反复失败请重新发起这次操作。",
                       "resume_failed", detail=str(e)[:200])

    # 多步审批：续跑后可能又停在**下一个**中断上，别把它当成功
    if detect_pending is not None:
        again = await detect_pending(context_id, user_id)
        if again is not None:
            return again

    messages = state.get("messages", []) if isinstance(state, dict) else []
    tool_content = ""
    reply = ""
    for m in messages:
        if m.__class__.__name__ == "ToolMessage":
            tool_content = str(m.content)
        elif m.__class__.__name__ == "AIMessage":
            c = getattr(m, "content", "")
            if isinstance(c, str) and c.strip():
                reply = c

    unwrapped = unwrap_hitl_tool_output(tool_content)
    if unwrapped is not None:
        content = reply or (compose_reply(unwrapped) if compose_reply else "")
        return {
            "content": content or "已按你的决定执行完成。",
            "data": {**unwrapped, "approval_decision": decision},
            "display_type": unwrapped.get("type", "text"),
        }
    return {
        "content": tool_content or reply or "已记录你的审批决定。",
        "data": {"type": DISPLAY_APPROVAL_RESOLVED, "decision": decision},
        "display_type": "text",
    }

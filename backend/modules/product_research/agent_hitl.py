# -*- coding: utf-8 -*-
"""选品 Agent 的 **HITL（人工审批）层**（P0-6 第三刀：从 `agent_product_research.py` 外移）。

## 这一层是什么

「一次工具调用停下来等人拍板」这件事的**全部领域逻辑**，5 个函数共 226 行：

    pending_approval_from_interrupt  把 LangGraph 的 Interrupt 渲染成前端审批卡
    build_resume_payload             把「批准 / 拒绝 / 改写 / 补充」翻译成包装器认得的载荷
    unwrap_hitl_tool_output          从包装器文案里取回内层工具的原始结构化结果
    detect_pending_approval          判断「这张图此刻是不是停在一次审批上」
    resume_approval                  把决策回传给被中断的图，让它续跑到结束

## 与第二刀（`agent_analyzers.py`）同法：显式传参，不用 mixin

理由见 `agent_analyzers.py` 模块 docstring。本层的签名同样是**依赖清单**：

    context_id / user_id / shop_id / decision / reason / args / feedback
                                    审批的输入（透传，语义不变）
    get_router                      工具路由层（原 `self._get_router()`）
    bind_context                    续跑前重新绑定 ContextVar（原 `self._bind_context`）
    hydrate_state                   续跑前把会话状态读回内存（原 `self._hydrate_state`）
    compose_reply                   兜底正文组装（原 `self._compose_reply`）
    detect_pending                  多步审批：续跑后再探一次（原 `self._detect_pending_approval`）

★ `bind_context` / `hydrate_state` 由**调用方传进来**，本层不自己 import：
  它们是「入口编排」职责 —— 与本类其它入口 `invoke` / `stream_chat` **同形**
  （绑上下文 → hydrate → 委托 → flush），归 Agent 本体；本层只管审批业务。
  副作用也要求它们留在调用方：`hydrate_state` 会触发「补写上一轮没落盘的改动」，
  必须发生在**校验通过之后**，不能因为提前到入口就多写一次库。

## 主文件侧

`ProductResearchAgent` 保留 5 个**同名薄壳**（`resume_approval` + 4 个私有方法），
体里只做「显式传参 + 委托」。不删方法、直接改调用点的原因：

  · `tests/test_hitl_approval_flow.py` 有 5 处**类级静态调用**
    （`ProductResearchAgent._build_resume_payload` / `._pending_approval_from_interrupt`
    / `._unwrap_hitl_tool_output`）；
  · `tests/test_thinking_trace.py` 用
    `monkeypatch.setattr(agent, "_detect_pending_approval", ...)` 打在**实例**上 ——
    薄壳必须继续走 `self.` 查找，补丁才生效。

两者都是本仓既有的测试契约；改它们等于替第三方改契约。

## 归位约束（门禁会钉住）

`tests/test_product_research_hitl_layer.py` 断言本模块：
  · 5 个函数体里不出现 `self`；
  · 不 import `agent_product_research`（不许反向回流）；
  · 不 import 数据库 / 会话持久化 / 平台取数模块；
  · 只允许依赖 `core.logger`、`langgraph.types` 与同层 `agent_models`。
"""
import json
from typing import Any, Awaitable, Callable, Optional

from core.logger import get_logger
# ★ 第 131 轮 item2-B：resume 要把审批决策喂回被中断的图，必须用 `Command(resume=...)`
from langgraph.types import Command

from .agent_models import AgentResponse

logger = get_logger("product_research.hitl")


def pending_approval_from_interrupt(
    interrupt_obj, context_id: Optional[str]
) -> AgentResponse:
    """
    把 LangGraph 的 `Interrupt` 渲染成前端可直接展示的审批请求。

    ★ 刻意**不回传 `thread_id`**：前端只要把同一个 `session_id` 交回来，
      服务端会按**与首轮完全相同的口径**重算 thread_id
      （`resolve_thread_id`）。把 thread_id 交给客户端，等于把
      「这条待审批操作归谁」交给请求方 —— 而 thread_id 里就含 user_id。
    """
    req = getattr(interrupt_obj, "value", None) or {}
    action = (req.get("action_request") or {}) if isinstance(req, dict) else {}
    tool_name = action.get("action") or "未知操作"
    return AgentResponse(
        content=(
            f"这一步需要你确认：准备执行「{tool_name}」，"
            "在批准之前它不会被真正执行。请选择「批准」或「拒绝」。"
        ),
        data={
            "type": "pending_approval",
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
        display_type="pending_approval",
    )


def build_resume_payload(
    decision: str,
    *,
    reason: Optional[str] = None,
    args: Optional[dict] = None,
    feedback: Optional[str] = None,
) -> dict:
    """
    把外部的「决策」翻译成 `hitl_decorator.call_tool_with_hitl` 认得的载荷。

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
    """
    从 HITL 包装器的返回文案里取回**内层工具的原始结构化结果**。

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
) -> Optional[AgentResponse]:
    """
    判断「这张图此刻是不是停在一次人工审批上」；是则渲染成 `pending_approval`。

    ★ 为什么走 `aget_state()` 而不是读 `ainvoke` 的返回值：
      流式与非流式都要判同一件事。非流式的 state 里有 `__interrupt__` 可读，
      但**流式没有**（`astream_events` 只给事件、不给最终 state）。
      两边各写一份判定，就会长出「非流式弹卡、流式静默吞掉」的不一致。
      `aget_state()` 对两条路径**语义完全相同**，是这里唯一正确的口径。

    ★ 为什么必须先确认 `context_id and user_id`：两者缺任一时
      `graph_for_session()` 返回的是**不带 checkpointer 的图**，
      对它调 `aget_state()` 会直接抛（连接层报 checkpointer 未设置）。
    """
    if not (context_id and user_id):
        return None

    router = get_router()
    if router is None or router.checkpointer is None:
        return None

    try:
        graph, cfg = router.graph_for_session(context_id, user_id)
        snapshot = await graph.aget_state(cfg)
    except Exception as e:  # noqa: BLE001 —— 探测失败不该让整轮对话崩
        logger.warning(f"[product_research] pending-approval probe failed: {e}")
        return None

    for task in (getattr(snapshot, "tasks", None) or []):
        for it in (getattr(task, "interrupts", None) or []):
            return pending_approval_from_interrupt(it, context_id)
    return None


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
    hydrate_state: Callable[..., Awaitable[None]],
    compose_reply: Callable[[dict], str],
    detect_pending: Callable[..., Awaitable[Optional[AgentResponse]]],
) -> AgentResponse:
    """
    把审批决策回传给**被中断的那张图**，让它续跑到结束。

    ★ 为什么必须重新 `bind_context()`：续跑时被中断的工具会**重新执行**，
      而它靠 ContextVar 拿会话与店铺归属（见 `tools.py::_save_candidate_tool`）。
      不重新绑定 ⇒ `shop_id` 拿不到 ⇒ `_write_candidates` **硬拒绝写入** ——
      用户「批准了」却收到「请先选一个店铺」，是这条链路上最迷惑的表现。
    """
    router = get_router()
    if router is None:
        return AgentResponse(
            content="审批通道暂时不可用（工具路由层未就绪），请稍后重试。",
            data={"type": "approval_failed", "error": "router_unavailable"},
            display_type="text",
        )
    if not (context_id and user_id):
        return AgentResponse(
            content="审批必须带上会话与登录身份，否则定位不到你那条待审批的操作。",
            data={"type": "approval_failed", "error": "missing_session_or_identity"},
            display_type="text",
        )
    if router.checkpointer is None:
        return AgentResponse(
            content="审批通道暂时不可用（会话存储未就绪），请稍后重试。",
            data={"type": "approval_failed", "error": "checkpointer_unavailable"},
            display_type="text",
        )

    try:
        payload = build_resume_payload(
            decision, reason=reason, args=args, feedback=feedback
        )
    except ValueError as e:
        return AgentResponse(
            content=str(e),
            data={"type": "approval_failed", "error": "bad_decision"},
            display_type="text",
        )

    # 续跑前重新绑定上下文（被中断的工具会重新执行，需要会话 + 归属 + 身份）
    # ★ 第 145 轮批 C1：身份也要绑 —— 会话状态的作用域键含 user_id，漏传会让
    #   被中断的工具在**另一个作用域**里找会话状态（`_save_candidate` 要靠它
    #   把「第 1 个」解析成具体商品）。
    # ★ 为什么这里只 hydrate 不 flush：本次调用能触达的写路径（`_save_candidate`
    #   → `_write_candidates`）**不改会话状态**（不写也不删任何键）。若将来它
    #   改了，入口 hydrate 的"先补写"仍会把它写出去，不会永久滞留。
    bind_context(context_id, shop_id, user_id)
    await hydrate_state(context_id)

    graph, cfg = router.graph_for_session(context_id, user_id)
    try:
        state = await graph.ainvoke(Command(resume=payload), config=cfg)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[product_research] resume failed: {e}")
        return AgentResponse(
            content="审批回传失败，请重试；若反复失败请重新发起这次操作。",
            data={
                "type": "approval_failed",
                "error": "resume_failed",
                "detail": str(e)[:200],
            },
            display_type="text",
        )

    # 多步审批：续跑后可能又停在**下一个**中断上，别把它当成功
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
        return AgentResponse(
            content=reply or compose_reply(unwrapped),
            data={**unwrapped, "approval_decision": decision},
            display_type=unwrapped.get("type", "text"),
        )
    return AgentResponse(
        content=tool_content or reply or "已记录你的审批决定。",
        data={"type": "approval_resolved", "decision": decision},
        display_type="text",
    )

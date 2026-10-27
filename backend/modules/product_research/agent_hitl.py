# -*- coding: utf-8 -*-
"""选品 Agent 的 HITL **适配壳**（第 400 轮 P0-2：逻辑已外移到 `modules/hitl/`）。

## 这一层现在只剩什么

5 个同名函数，每个体里只做两件事：

    1. 把本 Agent 的能力（`get_router` / `bind_context` / `hydrate_state` /
       `compose_reply` / `detect_pending`）作为 callable 显式传给中立层；
    2. 把中立层返回的 dict 包成本模块的 `AgentResponse`。

## 为什么逻辑要外移

第 399 轮对标发现：这 5 个函数除了 import 一个 `AgentResponse` 之外，
与选品业务**毫无关系** —— 它描述的是「一次工具调用停下来等人拍板」这件普适的事。
住在选品模块里的直接后果是：resume 端点、审批卡渲染全部绑死 `product-research`，
于是智能客服的 `create_ticket`、trade 域的 `propose_review_disposition`
在生产上**永远抛 `HITLPrerequisiteError`**（图画停了，没有任何端点能放行）。

现在逻辑只有一份（`modules/hitl/hitl.py`），每个 Agent 各留一个这样的薄壳。
判据：同一件事不许有两份实现 —— 否则迟早长出「选品弹卡、客服静默吞掉」。

## 为什么保留这 5 个壳、不直接把调用点改成中立层

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
  · **只允许**把能力当参数传给 `modules.hitl`，并把结果包成 `AgentResponse` ——
    E 档判的是「壳里不许出现 `Command(resume=...)` 与业务逻辑」，
    而不是「壳里不许出现 `AgentResponse`」（后者在第 400 轮已不可能：
    壳的职责就是类型适配）。
"""
from typing import Any, Awaitable, Callable, Optional

from core.logger import get_logger

# ★ 用 `import modules.hitl as _hitl` 而不是 `from modules import hitl`：
#   后者的 AST 目标只有 `modules`（顶层），形态门禁会认为壳 import 了整个
#   modules 层；前者的目标是 `modules.hitl`，白名单可以精确到这一层。
import modules.hitl as _hitl

from .agent_models import AgentResponse

logger = get_logger("product_research.hitl")


def pending_approval_from_interrupt(
    interrupt_obj, context_id: Optional[str]
) -> AgentResponse:
    """把 LangGraph 的 `Interrupt` 渲染成前端可直接展示的审批请求。"""
    return AgentResponse(**_hitl.pending_approval_payload(interrupt_obj, context_id))


def build_resume_payload(
    decision: str,
    *,
    reason: Optional[str] = None,
    args: Optional[dict] = None,
    feedback: Optional[str] = None,
) -> dict:
    """把外部的「决策」翻译成 `hitl_decorator.call_tool_with_hitl` 认得的载荷。"""
    return _hitl.build_resume_payload(
        decision, reason=reason, args=args, feedback=feedback
    )


def unwrap_hitl_tool_output(raw: str) -> Optional[dict]:
    """从 HITL 包装器的返回文案里取回内层工具的原始结构化结果。"""
    return _hitl.unwrap_hitl_tool_output(raw)


async def detect_pending_approval(
    context_id: Optional[str],
    user_id: Optional[str] = None,
    *,
    get_router: Callable[[], Any],
) -> Optional[AgentResponse]:
    """判断「这张图此刻是不是停在一次人工审批上」；是则渲染成 `pending_approval`。"""
    payload = await _hitl.detect_pending_approval(
        context_id, user_id, get_router=get_router, log_tag="product_research"
    )
    return AgentResponse(**payload) if payload is not None else None


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
    """把审批决策回传给被中断的图，让它续跑到结束。"""
    # ★ 类型适配：中立层要 dict，而 `self._detect_pending_approval` 返回本模块的
    #   `AgentResponse`（它被 `_hitl` 的"续跑后再探一次"调用）。
    #   直接把它传下去会让 `AgentResponse(**again)` 炸在"不是 mapping"上 ——
    #   而那一步正是**多步审批**才会走到的分支，只测单步永远发现不了。
    async def _detect_as_payload(cid, uid):
        found = await detect_pending(cid, uid)
        if found is None:
            return None
        return {
            "content": found.content,
            "data": found.data or {},
            "display_type": found.display_type,
        }

    payload = await _hitl.resume_approval(
        context_id,
        decision,
        user_id=user_id,
        shop_id=shop_id,
        reason=reason,
        args=args,
        feedback=feedback,
        get_router=get_router,
        bind_context=bind_context,
        hydrate_state=hydrate_state,
        compose_reply=compose_reply,
        detect_pending=_detect_as_payload,
        log_tag="product_research",
    )
    return AgentResponse(**payload)

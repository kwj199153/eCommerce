# -*- coding: utf-8 -*-
"""审批续跑的**通用**端点（第 400 轮 P0-2）。

## 为什么要有它

改造前只有 `POST /api/v1/product-research/approval/resume` 一个端点。
智能客服的 `create_ticket`、trade 域的 `propose_review_disposition` 同样被
`interrupt()` 挂起，却没有任何端点能把它们放行 ⇒ 用户看到审批卡、点批准、
什么也不会发生（甚至看不到卡，因为客服根本没有探测中断的代码）。

## 路径设计

    POST /api/v1/agents/{agent}/approval/resume

`{agent}` 接受 `AGENT_CATALOG` 的 id（`product-research` / `customer-service`），
也接受 `product_research` / `ProductResearcher` / `智能客服` 等别名 ——
归一化在 `modules.hitl.registry.canonical_agent_id`，本文件不自己判名字
（否则前端换个写法就 404，而这看起来像"这个 Agent 不支持审批"）。

## 归属与隔离

`thread_id` 由服务端按 `(命名空间, 用户, 会话)` 重算（`BaseAgent.resolve_thread_id`），
**不接受**客户端传入。`session_id` 属于别人时算出的 thread_id 与对方不同 ⇒
找不到那条中断 ⇒ 天然无法替别人批准（`user_id` 是键的一部分）。

## 与旧端点的关系

`/api/v1/product-research/approval/resume` **保留**（已发布的前端在用它），
但两者走**同一个** `get_resumer()` 分发 —— 不存两份实现。
旧端点标 `deprecated=True`，前端迁移完后由下一轮删除。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.auth.dependencies import require_auth_if_enabled
from core.identity.models import User
from core.tenant.middleware import get_current_shop_id_optional
from modules.hitl.registry import canonical_agent_id, get_resumer, supported_agents

router = APIRouter(prefix="/agents", tags=["人机协同"])


class ApprovalResumeRequest(BaseModel):
    """审批决策请求体（与旧端点同字段，前端可复用同一个构造函数）。"""

    context_id: str = Field(..., min_length=1, description="会话 ID（首轮返回的那个）")
    decision: str = Field(..., description="accept / reject / edit / response")
    reason: Optional[str] = Field(None, description="拒绝时的原因")
    args: Optional[Dict[str, Any]] = Field(None, description="edit 时的改写后入参")
    feedback: Optional[str] = Field(None, description="response 时的补充说明")


class ApprovalResumeResponse(BaseModel):
    """续跑结果。

    ★ 只回 `reply` / `display_type` / `data` 三个字段 —— 这是 5 个业务
      `ChatResponse` 的**公共子集**。通用端点不能把某个 Agent 的完整响应
      模型当契约（那会让别的 Agent 被迫实现它用不上的字段）。
    """

    reply: str
    display_type: str = "text"
    data: Optional[Dict[str, Any]] = None


@router.post(
    "/{agent}/approval/resume",
    response_model=ApprovalResumeResponse,
    summary="回传人工审批决策（通用，按 agent 分发）",
)
async def resume_approval(
    agent: str,
    request: ApprovalResumeRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """把审批决策回传给被 `interrupt()` 冻结的会话，让它续跑到结束。

    ★ 为什么不是一个"万能"端点、由请求体指明 agent：
      路径里带 agent，才能让**网关/日志/限流**按 agent 归集，
      也才能让前端在渲染审批卡时就知道该打哪个地址（见
      `frontend/src/api/agentApproval.ts`）。
    """
    agent_id = canonical_agent_id(agent)
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Agent {agent!r} 没有登记审批续跑通道；"
                f"已登记：{sorted(supported_agents())}。"
                "登记表见 modules/hitl/registry.py（新增写工具必须同时登记）。"
            ),
        )

    resumer = get_resumer(agent_id)
    if resumer is None:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="resumer 缺失")

    try:
        payload = await resumer(
            request.context_id,
            request.decision,
            shop_id=shop_id,
            user_id=current_user.id if current_user else None,
            reason=request.reason,
            args=request.args,
            feedback=request.feedback,
        )
    except ValueError as e:
        # 决策载荷本身不合法（如 edit 缺 args）⇒ 422，不是服务端故障
        raise HTTPException(status_code=422, detail=str(e)) from e

    # 各 Agent 的实现都返回中立 dict（{content,data,display_type}），
    # 或它们自己的响应对象（旧 service 返回 ChatResponse）—— 统一取值。
    content = _get(payload, "content", "reply")
    display_type = _get(payload, "display_type") or "text"
    data = _get(payload, "data")
    return ApprovalResumeResponse(reply=content or "", display_type=display_type, data=data)


@router.get(
    "/approval/channels",
    summary="哪些 Agent 支持审批续跑（排查/前端能力发现用）",
)
async def approval_channels():
    """列出已登记 resume 通道的 agent_id。

    ★ 存在的理由：**"这个 Agent 支持审批吗"必须能被问到**。
      没有它，前端想知道就只能硬编码一份名单 —— 而那份名单一定会漂移
      （第 399 轮的洞就是"名单只有 product-research"）。
    """
    return {"agents": sorted(supported_agents())}


def _get(obj: Any, *names: str) -> Any:
    """从 dict 或对象里按候选字段名取值（中立层给 dict、旧 service 给对象）。"""
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return None

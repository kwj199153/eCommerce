"""会话持久化 API 路由（决策层 B）

提供 sessionId 的创建 / 历史读取 / 消息追加，供前端跨会话恢复对话。

注意：这些端点只做「会话元数据 + 消息历史」的存取，不承载 LLM 推理。
LLM 推理仍在 /orchestrator/chat 里，由前端把 sessionId 传过去。

★ P0-1（2026-09-18）：本文件此前**三个端点全无鉴权依赖**，且 `owner_id`
  是请求体里的客户端自报字段。实测（生产模式 `auth_required=True`）：
  B 持自己的有效 token → `GET .../history` 得 **200 + A 的完整对话内容**，
  `POST .../messages` 得 200 且 A 侧会话真被写入。修复后：

    1. 每个端点都**显式声明** `current_user = Depends(require_auth_if_enabled)`。
       ★ 不能只靠 `main.py` 的 router 级 `BUSINESS_AUTH` —— 路由级依赖
         **不向 handler 注入参数**，只挂 router 级的话 handler 根本拿不到
         `current_user`，归属判定也就无从谈起。这是本次缺陷最容易复发的形态：
         "路由挂了一层依赖"看起来像有鉴权，而它只是挡住了匿名。
       ★ 该依赖与 router 级是同一个函数、同一请求 ⇒ FastAPI 依赖缓存命中，
         不会重复查库。
    2. `owner_id` / `shop_id` 从请求体**删除** —— 归属只能由服务端注入。
       客户端照旧发这两个字段不会 422（pydantic 默认忽略多余字段），
       但**不会被采纳**。
    3. 读 / 写历史一律先过 `service` 的归属判定，不可访问 ⇒ **404**，
       且"不存在"与"不是你的"共用同一句文案（不泄露 session_id 是否存在）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth.dependencies import require_auth_if_enabled
from core.identity.models import User

from . import service

router = APIRouter(prefix="/conversations", tags=["会话持久化"])


class ConversationCreateRequest(BaseModel):
    """创建会话的入参。

    ★ 这里**只有**非归属类字段。`owner_id` / `shop_id` 曾经也在此列，
      而它们是客户端的自报值 —— 归属必须来自服务端身份，不能来自 body。
    """

    agent_id: str = Field("secretary", description="对话所属 Agent")
    title: str = Field("新对话", description="会话标题")


class ConversationCreateResponse(BaseModel):
    session_id: str = Field(..., description="会话 ID（前端持久化，后续请求带回）")


class MessageAppendRequest(BaseModel):
    role: str = Field(..., description="user / assistant")
    content: str = Field(..., description="消息内容")


class HistoryResponse(BaseModel):
    session_id: str
    history: list = Field(default=[], description="[{role, content}] 历史消息")


@router.post("", response_model=ConversationCreateResponse, summary="创建会话")
async def create_conversation(
    request: ConversationCreateRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """新建会话。归属取自**服务端身份**（`current_user`），不接受任何自报字段。"""
    session_id = await service.create_conversation(
        agent_id=request.agent_id,
        owner_id=current_user.id if current_user else None,
        title=request.title,
    )
    return ConversationCreateResponse(session_id=session_id)


@router.get("/{session_id}/history", response_model=HistoryResponse, summary="读取会话历史")
async def get_history(
    session_id: str,
    limit: int = 20,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """读取会话历史。**不可访问 ⇒ 404**（与"不存在"同一响应）。"""
    history = await service.get_history(current_user, session_id, limit=limit)
    return HistoryResponse(session_id=session_id, history=history)


@router.post("/{session_id}/messages", summary="追加消息")
async def append_message(
    session_id: str,
    request: MessageAppendRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """追加一条消息。**不可访问 ⇒ 404**，不产生任何写入。

    ★ `role` 校验放在判权**之前**：它是纯入参校验、零数据库往返，
      提前拒绝能省掉一次无谓的查询，也不泄露会话是否存在。
    """
    if request.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role 必须是 user 或 assistant")
    await service.append_message(current_user, session_id, request.role, request.content)
    return {"success": True}

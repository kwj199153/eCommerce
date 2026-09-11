"""会话持久化 API 路由（决策层 B）

提供 sessionId 的创建 / 历史读取 / 消息追加，供前端跨会话恢复对话。

注意：这些端点只做「会话元数据 + 消息历史」的存取，不承载 LLM 推理。
LLM 推理仍在 /orchestrator/chat 里，由前端把 sessionId 传过去。
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import service

router = APIRouter(prefix="/conversations", tags=["会话持久化"])


class ConversationCreateRequest(BaseModel):
    agent_id: str = Field("secretary", description="对话所属 Agent")
    owner_id: Optional[str] = Field(None, description="归属用户")
    shop_id: Optional[str] = Field(None, description="归属店铺")
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
async def create_conversation(request: ConversationCreateRequest):
    session_id = await service.create_conversation(
        agent_id=request.agent_id,
        owner_id=request.owner_id,
        shop_id=request.shop_id,
        title=request.title,
    )
    return ConversationCreateResponse(session_id=session_id)


@router.get("/{session_id}/history", response_model=HistoryResponse, summary="读取会话历史")
async def get_history(session_id: str, limit: int = 20):
    if not await service.conversation_exists(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    history = await service.get_history(session_id, limit=limit)
    return HistoryResponse(session_id=session_id, history=history)


@router.post("/{session_id}/messages", summary="追加消息")
async def append_message(session_id: str, request: MessageAppendRequest):
    if not await service.conversation_exists(session_id):
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if request.role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role 必须是 user 或 assistant")
    await service.append_message(session_id, request.role, request.content)
    return {"success": True}

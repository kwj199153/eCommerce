"""店秘书（主 Agent）路由 —— 轻量编排端点"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.billing.usage_tracker import meter_agent_chat
# ★ 用 `_optional` 变体而不是 `get_current_shop_id`：本端点是 **POST 但属对话入口**，
#   不是业务数据写入口。用严格版会让「刚注册、还没有店铺」的用户一进来就被 400
#   挡住 —— 而这时候他恰恰只能靠店秘书去创建第一家店铺。
#   详见 `get_current_shop_id_optional` 的 docstring 使用边界。
from core.tenant.middleware import get_current_shop_id_optional
from modules.secretary.agent import route

router = APIRouter(prefix="/api/v1/orchestrator", tags=["店秘书"])


class HistoryMessage(BaseModel):
    role: str = Field(..., description="消息角色：user / assistant")
    content: str = Field(..., description="消息内容")


class OrchestratorRequest(BaseModel):
    message: str = Field(..., description="用户一句话", min_length=1)
    history: list[HistoryMessage] = Field(
        default=[],
        description="本会话历史消息（不含当前 message），用于多轮上下文连贯",
    )
    session_id: Optional[str] = Field(
        None,
        description="会话 ID（跨会话记忆）。非空时后端从 DB 读取历史 + 用 checkpoint 持久化",
    )


class OrchestratorResponse(BaseModel):
    reply: str = Field(..., description="面向用户的回复")
    actions: list = Field(default=[], description="有序动作列表，前端按顺序执行")
    action: dict | None = Field(
        None,
        description=(
            "动作（向后兼容，= actions 最后一个）："
            "{action: switch_agent, agentId} 或 {action: navigate, view} "
            "或 {action: select_product, product:{id,title,asin}}"
        ),
    )
    tool_calls: list = Field(default=[], description="本次实际调用的工具名列表")
    route_mode: str = Field(
        "llm",
        description="决策路径：shortcut=关键词短路（未调 LLM）/ llm=LLM 兜底",
    )
    session_id: Optional[str] = Field(
        None, description="会话 ID（回显，未传时后端新建并返回，供前端持久化）"
    )


@router.post("/chat", response_model=OrchestratorResponse, summary="店秘书对话（意图路由）")
async def secretary_chat(
    request: OrchestratorRequest,
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    _meter=Depends(meter_agent_chat),
):
    """
    店秘书全局入口：识别用户意图，调用业务工具或返回导航/选择动作。

    决策层 B（跨会话记忆）+ C（checkpointer）：
    - 请求带 session_id → 从 DB 读历史（若历史为空）注入 + checkpoint 持久化
    - 请求不带 session_id → 新建会话，返回新 session_id 供前端持久化

    返回：
    - reply：面向用户的回复文本
    - actions：有序动作列表（选产品 → 切 Agent 等），前端按顺序 dispatchAppAction
    - action：向后兼容字段（= actions 最后一个）
    - tool_calls：本次调用的工具名（调试/埋点用）
    - session_id：会话 ID（前端持久化，后续请求带回）
    """
    try:
        session_id = request.session_id

        # 决策层 B：带 session_id 时，优先从 DB 读历史（比前端显式传的 history 更权威）
        history = [h.model_dump() for h in request.history]
        if session_id:
            from modules.conversation import service as conv_service
            if await conv_service.conversation_exists(session_id):
                db_history = await conv_service.get_history(session_id, limit=20)
                if db_history:
                    # DB 历史为准（跨会话恢复场景）
                    history = db_history
            else:
                # 会话不存在（如换环境），退回前端 history 并新建
                session_id = None
        else:
            # 无 session_id：新建会话
            from modules.conversation import service as conv_service
            session_id = await conv_service.create_conversation(agent_id="secretary")

        result = await route(
            request.message,
            shop_id=shop_id,
            history=history,
            session_id=session_id,
        )

        # 决策层 B：把本轮 user + assistant 消息写入会话（异步持久化，失败不阻断响应）
        try:
            from modules.conversation import service as conv_service
            await conv_service.append_message(session_id, "user", request.message)
            await conv_service.append_message(session_id, "assistant", result.get("reply", ""))
        except Exception as e:
            # 写历史失败不影响主流程（如 DB 未就绪）
            import logging
            logging.getLogger(__name__).warning(f"会话消息持久化失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return OrchestratorResponse(
        reply=result.get("reply", "处理完成"),
        actions=result.get("actions", []),
        action=result.get("action"),
        tool_calls=result.get("tool_calls", []),
        route_mode=result.get("route_mode", "llm"),
        session_id=session_id,
    )

"""店秘书（主 Agent）路由 —— 轻量编排端点"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.billing.usage_tracker import meter_agent_chat
from core.tenant.middleware import get_current_shop_id
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


@router.post("/chat", response_model=OrchestratorResponse, summary="店秘书对话（意图路由）")
async def secretary_chat(
    request: OrchestratorRequest,
    shop_id: Optional[str] = Depends(get_current_shop_id),
    _meter=Depends(meter_agent_chat),
):
    """
    店秘书全局入口：识别用户意图，调用业务工具或返回导航/选择动作。

    返回：
    - reply：面向用户的回复文本
    - actions：有序动作列表（选产品 → 切 Agent 等），前端按顺序 dispatchAppAction
    - action：向后兼容字段（= actions 最后一个）
    - tool_calls：本次调用的工具名（调试/埋点用）
    """
    try:
        result = await route(
            request.message,
            shop_id=shop_id,
            history=[h.model_dump() for h in request.history],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return OrchestratorResponse(
        reply=result.get("reply", "处理完成"),
        actions=result.get("actions", []),
        action=result.get("action"),
        tool_calls=result.get("tool_calls", []),
    )

"""
智能客服模块 - API 路由 (Router)

提供客服相关的 RESTful API 端点
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from .schemas import (
    ChatRequest, ChatResponse,
    FAQSearchRequest, FAQSearchResponse,
    TicketCreateRequest, TicketResponse,
    OrderTrackRequest, OrderTrackResponse,
    SentimentAnalysisRequest, SentimentResponse,
    ApiResponse, ErrorResponse,
    CapabilityResponse
)
from .service import CustomerServiceService


# 创建路由器（带前缀）
router = APIRouter(
    prefix="/customer-service",
    tags=["智能客服"]
)


# ====== 对话接口 ======

@router.post("/chat", response_model=ApiResponse, summary="客服对话")
async def chat_endpoint(request: ChatRequest):
    """
    智能客服对话主入口

    支持多轮对话、FAQ 匹配、情感分析、意图识别
    """
    try:
        response = await CustomerServiceService.chat(request)
        return ApiResponse(
            data={
                "reply": response.reply,
                "conversation_id": response.conversation_id,
                "intent": response.intent,
                "sentiment": response.sentiment,
                "display_type": response.display_type,
                "data": response.data,
                "suggested_actions": response.suggested_actions,
                "should_escalate": response.should_escalate
            },
            message="对话处理完成"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick-reply", response_model=ApiResponse, summary="快速回复")
async def quick_reply_endpoint(request: ChatRequest):
    """简化版对话接口，用于快捷入口"""
    try:
        result = await CustomerServiceService.quick_reply(request.message)
        return ApiResponse(data=result, message="OK")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ====== FAQ 接口 ======

@router.post("/faq/search", response_model=FAQSearchResponse, summary="搜索知识库")
async def search_faq_endpoint(request: FAQSearchRequest):
    """
    在 FAQ 知识库中搜索相关问题

    支持语义匹配和关键词检索
    """
    return await CustomerServiceService.search_faq(request)


@router.get("/faq/categories", response_model=ApiResponse, summary="获取 FAQ 分类")
async def get_faq_categories():
    """获取所有 FAQ 分类"""
    caps = CustomerServiceService.get_capabilities()
    categories = []

    for cat in caps.categories:
        # 统计每个分类的 FAQ 数量
        agent = CustomerServiceService.get_cs_agent()
        count = sum(1 for f in agent.faq_database if f.category == cat)
        categories.append({
            "name": cat,
            "count": count,
            "icon": _get_category_icon(cat)
        })

    return ApiResponse(data=categories)


def _get_category_icon(category: str) -> str:
    """获取分类图标"""
    icons = {
        "物流": "🚚",
        "退换货": "🔄",
        "订单": "📦",
        "售后": "🔧",
        "支付": "💳",
        "其他": "❓"
    }
    return icons.get(category, "📋")


# ====== 工单接口 ======

@router.post("/ticket/create", response_model=TicketResponse, summary="创建工单")
async def create_ticket_endpoint(request: TicketCreateRequest):
    """
    创建客户服务工单

    自动计算优先级和 SLA
    """
    return await CustomerServiceService.create_ticket(request)


# ====== 订单追踪接口 ======

@router.post("/order/track", response_model=OrderTrackResponse, summary="订单追踪")
async def track_order_endpoint(request: OrderTrackRequest):
    """
    查询订单状态和物流信息

    支持订单号/邮箱/手机号查询
    """
    return await CustomerServiceService.track_order(request)


# ====== 情感分析接口 ======

@router.post("/analyze/sentiment", response_model=SentimentResponse, summary="情感分析")
async def analyze_sentiment_endpoint(request: SentimentAnalysisRequest):
    """
    分析文本的情感倾向

    用于实时监控客户情绪
    """
    return await CustomerServiceService.analyze_sentiment(request)


# ====== 对话管理接口 ======

@router.get("/conversation/{conversation_id}", response_model=ApiResponse, summary="对话摘要")
async def get_conversation_endpoint(conversation_id: str):
    """
    获取指定会话的摘要信息
    """
    summary = await CustomerServiceService.get_conversation_summary(conversation_id)

    if not summary:
        raise HTTPException(status_code=404, detail="会话不存在")

    return ApiResponse(data=summary.model_dump())


# ====== 能力描述 ======

@router.get("/capabilities", response_model=CapabilityResponse, summary="Agent 能力")
async def capabilities_endpoint():
    """
    获取智能客服 Agent 的能力描述
    """
    return CustomerServiceService.get_capabilities()


# ====== 健康检查 ======

@router.get("/health", summary="健康检查")
async def health_check():
    """服务健康检查"""
    agent = CustomerServiceService.get_cs_agent()
    return {
        "status": "healthy",
        "agent_name": agent.agent_name,
        "faq_count": len(agent.faq_database),
        "active_conversations": len(agent.conversations)
    }

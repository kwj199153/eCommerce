"""
智能客服模块 - 业务逻辑层 (Service)

处理客服相关的业务逻辑
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from .agent_cs import CustomerServiceAgent, AgentResponse
from .schemas import (
    ChatRequest, ChatResponse, FAQSearchRequest, FAQSearchResponse,
    TicketCreateRequest, TicketResponse, OrderTrackRequest, OrderTrackResponse,
    SentimentAnalysisRequest, SentimentResponse,
    ConversationSummaryResponse, CapabilityResponse
)


# 单例 Agent 实例
_agent_instance: Optional[CustomerServiceAgent] = None


def get_cs_agent() -> CustomerServiceAgent:
    """获取或创建 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerServiceAgent()
    return _agent_instance


class CustomerServiceService:
    """智能客服业务逻辑层"""

    @staticmethod
    async def chat(request: ChatRequest) -> ChatResponse:
        """
        处理客服对话

        Args:
            request: 对话请求

        Returns:
            ChatResponse 包含回复、意图、情感等
        """
        agent = get_cs_agent()

        # 调用 Agent 处理
        result: AgentResponse = await agent.invoke(
            query=request.message,
            context=request.context,
            conversation_id=request.conversation_id
        )

        # 构建响应
        response = ChatResponse(
            reply=result.content,
            conversation_id=request.conversation_id or agent._generate_conversation_id(),
            intent=result.data.get("type", "unknown") if result.data else "general",
            sentiment=result.data.get("sentiment") if result.data else None,
            data=result.data,
            display_type=result.display_type,
            should_escalate=result.data.get("type") == "escalation" if result.data else False
        )

        # 根据类型添加建议操作
        if result.display_type == "ticket_prompt":
            response.suggested_actions = ["创建工单", "查看退换货政策"]
        elif result.display_type == "order_query_prompt":
            response.suggested_actions = ["输入订单号", "通过邮箱查询"]
        elif result.display_type == "faq_answer":
            response.suggested_actions = ["这个回答有帮助", "查看相关问题"]
        elif result.display_type == "escalation_notice":
            response.suggested_actions = ["提供联系方式", "立即转人工"]

        return response

    @staticmethod
    async def stream_chat(message: str):
        """流式对话入口（返回逐 token 异步迭代器）"""
        agent = get_cs_agent()
        async for chunk in agent.stream_chat(message):
            yield chunk

    @staticmethod
    async def search_faq(request: FAQSearchRequest) -> FAQSearchResponse:
        """
        搜索知识库

        Args:
            request: 搜索请求

        Returns:
            FAQSearchResponse 匹配结果列表
        """
        agent = get_cs_agent()

        results = await agent.search_knowledge_base(
            query=request.query,
            limit=request.limit
        )

        best_match = results[0] if results else None

        return FAQSearchResponse(
            query=request.query,
            results=results,
            total=len(results),
            best_match=best_match
        )

    @staticmethod
    async def create_ticket(request: TicketCreateRequest) -> TicketResponse:
        """
        创建工单

        Args:
            request: 工单创建请求

        Returns:
            TicketResponse 工单信息 + 预计响应时间
        """
        agent = get_cs_agent()

        result = await agent.create_ticket(
            subject=request.subject,
            description=request.description,
            category=request.category,
            order_id=request.order_id,
            priority=request.priority,
            customer_id=request.customer_id
        )

        if result.success and result.ticket:
            return TicketResponse(
                success=True,
                ticket=result.ticket.model_dump(),
                estimated_response_time=result.estimated_response_time,
                auto_replies=result.auto_replies,
                message=f"工单 {result.ticket.ticket_id} 创建成功！"
            )
        else:
            return TicketResponse(
                success=False,
                message="工单创建失败，请稍后重试或联系人工客服"
            )

    @staticmethod
    async def track_order(request: OrderTrackRequest) -> OrderTrackResponse:
        """
        追踪订单

        Args:
            request: 订单追踪请求

        Returns:
            OrderTrackResponse 订单信息
        """
        agent = get_cs_agent()

        order_id = request.order_id

        if not order_id and (request.email or request.phone_last4):
            # 模拟通过邮箱/手机查找订单
            order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}{hash(request.email or '') % 10000:08d}"

        if order_id:
            # 调用 Agent 的订单追踪能力
            result: AgentResponse = await agent.invoke(
                query=f"查询订单 {order_id}",
                context={"order_id": order_id}
            )

            if result.data and result.data.get("type") == "order_detail":
                return OrderTrackResponse(
                    found=True,
                    order=result.data["order"],
                    message="订单信息获取成功"
                )

        return OrderTrackResponse(
            found=False,
            message="未找到匹配的订单，请检查订单号或联系客服"
        )

    @staticmethod
    async def analyze_sentiment(request: SentimentAnalysisRequest) -> SentimentResponse:
        """
        分析文本情感

        Args:
            request: 待分析文本

        Returns:
            SentimentResponse 情感分析结果
        """
        agent = get_cs_agent()
        result = agent._analyze_sentiment(request.text)

        return SentimentResponse(
            sentiment=result.sentiment,
            confidence=result.confidence,
            intensity=result.intensity,
            key_emotions=result.key_emotions,
            should_escalate=result.should_escalate,
            escalate_reason=result.escalate_reason
        )

    @staticmethod
    async def get_conversation_summary(conversation_id: str) -> Optional[ConversationSummaryResponse]:
        """
        获取对话摘要

        Args:
            conversation_id: 会话 ID

        Returns:
            ConversationSummaryResponse 对话摘要
        """
        agent = get_cs_agent()
        summary = await agent.get_conversation_summary(conversation_id)

        if summary:
            return ConversationSummaryResponse(**summary)
        return None

    @staticmethod
    def get_capabilities() -> CapabilityResponse:
        """
        获取 Agent 能力描述

        Returns:
            CapabilityResponse 能力列表
        """
        agent = get_cs_agent()
        caps = agent.get_capabilities()
        return CapabilityResponse(**caps)

    @staticmethod
    async def quick_reply(query: str) -> Dict[str, Any]:
        """
        快速回复（简化接口）

        用于前端快捷入口调用

        Args:
            query: 用户输入

        Returns:
            简化的响应字典
        """
        service = CustomerServiceService()
        request = ChatRequest(message=query)
        response = await service.chat(request)

        return {
            "reply": response.reply,
            "intent": response.intent,
            "display_type": response.display_type,
            "data": response.data,
            "conversation_id": response.conversation_id
        }

"""
智能客服模块 - 业务逻辑层 (Service)

处理客服相关的业务逻辑

★ 第 143 轮 A4：`create_ticket` 从「只造对象不落库」改为**真的写 PG**
  （`cs_tickets` 表）。此前响应写「工单 XXX 创建成功！」而那个工单号
  指向不了任何记录 —— 刷新即消失，属"伪成功"。
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from core.database import async_session_factory
from core.tenant.middleware import MissingShopContext, require_shop_context

from .agent_cs import CustomerServiceAgent, AgentResponse
from .db_model import TicketRecord
from .schemas import (
    ChatRequest, ChatResponse, FAQSearchRequest, FAQSearchResponse,
    TicketCreateRequest, TicketResponse, OrderTrackRequest, OrderTrackResponse,
    SentimentAnalysisRequest, SentimentResponse,
    ConversationSummaryResponse, CapabilityResponse
)

logger = logging.getLogger(__name__)


# 单例 Agent 实例
_agent_instance: Optional[CustomerServiceAgent] = None


async def _persist_ticket(ticket, request: TicketCreateRequest, shop_id: str,
                          estimated_response_time: str) -> Optional[str]:
    """把工单写进 `cs_tickets`，返回**最终落库**的工单号；三次都冲突则返回 None。

    ★ 为什么需要重试：Agent 生成的工单号形如 `TKT-20260918-48213`，
      末 5 位是 `random.randint(10000, 99999)` —— 同一天内并非全局唯一。
      直接 insert 撞主键会抛 `IntegrityError`，若不处理就是 500
      （用户看到"服务器内部错误"，但工单其实只是编号撞车）。

    ★ 为什么是「换后缀重试」而不是「先查后插」：先 `SELECT` 再 `INSERT`
      是非原子的 —— 并发下两个请求可以同时查到"不存在"然后双双插入，
      一个成功一个 500。让**数据库**来裁决唯一性，捕获冲突再换号，才是原子的。

    ★ 三次都失败 ⇒ 返回 None，由调用方转成 `success=False` + 可读原因。
      **绝不**在写库失败时仍然回 `success=True`（那正是本批次要修的形态）。
    """
    base = ticket.ticket_id
    last_err: Optional[Exception] = None
    for attempt in range(3):
        # 第 0 次用 Agent 生成的原始号；之后追加短后缀（uuid4 前 4 位 hex）
        tid = base if attempt == 0 else f"{base}-{uuid4().hex[:4]}"
        async with async_session_factory() as db:
            db.add(TicketRecord(
                id=tid,
                shop_id=shop_id,
                subject=ticket.subject,
                description=ticket.description,
                category=ticket.category,
                priority=ticket.priority,
                status=ticket.status,
                customer_id=ticket.customer_id,
                order_id=ticket.order_id,
                created_at=ticket.created_at,
                updated_at=ticket.created_at,
                sla_deadline=ticket.sla_deadline,
                estimated_response_time=estimated_response_time,
                auto_replies=None,
                tags=list(ticket.tags or []),
                attachments=list(request.attachments or []),
            ))
            try:
                await db.commit()
                return tid
            except IntegrityError as e:
                await db.rollback()
                last_err = e
                logger.warning(
                    "工单号冲突，换后缀重试：id=%s attempt=%d", tid, attempt + 1
                )
    logger.error("工单落库连续 3 次冲突，放弃：base=%s err=%s", base, last_err)
    return None



def get_cs_agent() -> CustomerServiceAgent:
    """获取或创建 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CustomerServiceAgent()
    return _agent_instance


class CustomerServiceService:
    """智能客服业务逻辑层"""

    @staticmethod
    async def chat(request: ChatRequest,
                   store_id: Optional[str] = None) -> ChatResponse:
        """
        处理客服对话

        Args:
            request: 对话请求
            store_id: 当前店铺（**服务端从 `X-Shop-ID` 注入**，第 286 轮）。
                话术是租户隔离数据（`knowledge_faqs.shop_id`），没有它就
                读不到这个店铺的话术 —— 与订单追踪同理。

        Returns:
            ChatResponse 包含回复、意图、情感等
        """
        agent = get_cs_agent()

        # ★ 归属注入：**服务端值后写** —— 请求体里即便也带 `store_id`
        #   也会被覆盖。归属不由客户端决定（与 `create_ticket` 同纪律）。
        context = dict(request.context or {})
        context["store_id"] = store_id

        # 调用 Agent 处理
        result: AgentResponse = await agent.invoke(
            query=request.message,
            context=context,
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
    async def stream_chat(message: str, store_id: Optional[str] = None):
        """流式对话入口（返回逐 token 异步迭代器）。

        ★ 第 204 轮：`store_id` 由 router 从请求头解析后传入，供 agent 的工具
          环路注入归属（`create_ticket` 落库必须带租户维度）。工具**入参**由
          LLM 生成，归属绝不能走工具形参。
        """
        agent = get_cs_agent()
        async for chunk in agent.stream_chat(message, {"store_id": store_id}):
            yield chunk

    @staticmethod
    async def search_faq(request: FAQSearchRequest,
                         store_id: Optional[str] = None) -> FAQSearchResponse:
        """
        搜索知识库（**真源：`knowledge_faqs` 表**）

        Args:
            request: 搜索请求
            store_id: 当前店铺（服务端注入）。话术按店铺隔离，缺了读不到。

        Returns:
            FAQSearchResponse 匹配结果列表

        Raises:
            PermissionError: 缺店铺（端点转 400）
            RuntimeError:    话术库读不出来（端点转 503）
        """
        agent = get_cs_agent()

        results = await agent.search_knowledge_base(
            query=request.query,
            limit=request.limit,
            shop_id=store_id,
        )

        best_match = results[0] if results else None

        return FAQSearchResponse(
            query=request.query,
            results=results,
            total=len(results),
            best_match=best_match
        )

    @staticmethod
    async def create_ticket(request: TicketCreateRequest,
                            store_id: str) -> TicketResponse:
        """
        创建工单（**落库**）

        Args:
            request: 工单创建请求
            store_id: 当前店铺 ID —— **由服务端注入**（router 的 strict 守卫），
                不来自请求体。缺/空即抛 `MissingShopContext`（fail-closed）。

        Returns:
            TicketResponse 工单信息 + 预计响应时间

        ★ 第 143 轮 A4：返回的 `ticket_id` 是**真的写进 `cs_tickets` 的那个**
          （若发生编号冲突会被换成带后缀的号）—— 前端/客服报的单号必须能查到记录。
        ★ 写库失败时返回 `success=False` + 可读原因，**不谎报成功**。
        """
        shop_id = require_shop_context(store_id)
        agent = get_cs_agent()

        result = await agent.create_ticket(
            subject=request.subject,
            description=request.description,
            category=request.category,
            order_id=request.order_id,
            priority=request.priority,
            customer_id=request.customer_id
        )

        if not (result.success and result.ticket):
            return TicketResponse(
                success=False,
                message="工单创建失败，请稍后重试或联系人工客服"
            )

        persisted_id = await _persist_ticket(
            result.ticket, request, shop_id, result.estimated_response_time
        )
        if persisted_id is None:
            return TicketResponse(
                success=False,
                ticket=None,
                estimated_response_time=result.estimated_response_time,
                auto_replies=result.auto_replies,
                message="工单创建失败：工单号冲突，请重试",
            )

        data = result.ticket.model_dump()
        data["ticket_id"] = persisted_id     # ★ 回给调用方的是**落库那个号**
        return TicketResponse(
            success=True,
            ticket=data,
            estimated_response_time=result.estimated_response_time,
            auto_replies=result.auto_replies,
            message=f"工单 {persisted_id} 创建成功！"
        )

    @staticmethod
    async def track_order(
        request: OrderTrackRequest,
        store_id: Optional[str] = None,
    ) -> OrderTrackResponse:
        """
        追踪订单

        ★ 第 285 轮：`store_id` 由端点从 `X-Shop-ID` 注入（**服务端注入**，
          请求体里没有这个字段）。缺了它就查不了自有订单库（租户隔离），
          只能退回平台适配层 —— 所以这是「能不能用自己的数据」的分水岭。

        Args:
            request: 订单追踪请求
            store_id: 当前店铺（服务端注入，可空）

        Returns:
            OrderTrackResponse 订单信息
        """
        agent = get_cs_agent()

        order_id = request.order_id

        if not order_id:
            # ★ 这里曾经用 `hash(email) % 10000` **编一个订单号**再去查
            #   （形如 ORD-YYYYMMDDxxxxxxxx）。那个号在平台侧永远不存在，
            #   而当时的订单查询是随机 mock —— 任何输入都会「查到」一张
            #   随机生成的订单表。于是「编造订单号 + 编造订单」形成闭环：
            #   用户只给邮箱，也会收到一份 found=True 的假订单。
            #   按 fail-closed：没有订单号就不假装查。
            return OrderTrackResponse(
                found=False,
                message=(
                    "请提供订单号（Amazon 订单号形如 123-1234567-1234567）。"
                    "按邮箱 / 手机号后四位检索需要卖家后台授权，暂未开放。"
                ),
            )

        # 调用 Agent 的订单追踪能力
        result: AgentResponse = await agent.invoke(
            query=f"查询订单 {order_id}",
            # ★ `store_id` 必须进 context：agent 的 `_handle_order_tracking`
            #   从 context 取它传给 `_fetch_order_info`，用于查自有订单库。
            #   此前这里只传 `order_id` ⇒ 范式 B 全程没有店铺归属。
            context={"order_id": order_id, "store_id": store_id},
        )

        if result.data and result.data.get("type") == "order_detail":
            return OrderTrackResponse(
                found=True,
                order=result.data["order"],
                message="订单信息获取成功"
            )

        # ★ 把真实原因带回调用方：此前一律回「未找到匹配的订单」，
        #   会让「店铺没接数据源」和「订单号打错了」看起来一模一样。
        reason = (result.data or {}).get("reason")
        return OrderTrackResponse(
            found=False,
            message=(
                f"未能查询到订单 {order_id}：{reason}" if reason
                else "未找到匹配的订单，请检查订单号或联系客服"
            )
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
    async def list_faq_categories(store_id: Optional[str] = None) -> Dict[str, Any]:
        """话术分类统计（**按店铺**，读 `knowledge_faqs`）。

        ★ 为什么 `faq_error` 要一并返回：分类列表为空有两种截然不同的原因
          ——「这个店铺还没配话术」（正常）与「话术库读不出来」（故障）。
          只回一个空数组，前端只能显示「暂无分类」，把故障显示成正常。
        """
        agent = get_cs_agent()
        err = await agent.ensure_faq(store_id)

        counts: Dict[str, int] = {}
        for f in agent.faq_database:
            counts[f.category] = counts.get(f.category, 0) + 1

        return {
            "categories": [
                {"name": name, "count": count}
                for name, count in sorted(counts.items())
            ],
            "faq_error": err,
        }

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
    async def quick_reply(query: str,
                          store_id: Optional[str] = None) -> Dict[str, Any]:
        """
        快速回复（简化接口）

        用于前端快捷入口调用

        Args:
            query: 用户输入
            store_id: 当前店铺（服务端注入，供读话术）

        Returns:
            简化的响应字典
        """
        service = CustomerServiceService()
        request = ChatRequest(message=query)
        response = await service.chat(request, store_id)

        return {
            "reply": response.reply,
            "intent": response.intent,
            "display_type": response.display_type,
            "data": response.data,
            "conversation_id": response.conversation_id
        }

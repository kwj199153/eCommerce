"""工单：投诉/升级/兜底话术、工单创建、优先级与自动回复、共情。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from uuid import uuid4
from ._base import (
    AgentResponse,
    ConversationContext,
    SentimentAnalysis,
    TicketCreateResult,
    TicketInfo,
)

class MixinTickets:
    """工单：投诉/升级/兜底话术、工单创建、优先级与自动回复、共情。"""

    async def _handle_complaint(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理投诉/质量问题"""

        # 情感安抚
        empathy = self._generate_empathy(sentiment)

        reply = f"{empathy}\n\n"
        reply += "我非常重视您反馈的问题，让我来帮您处理。\n\n"

        # 匹配相关 FAQ
        quality_faq = next(
            (f for f in self.faq_database if f.id == "faq-005"), None
        )
        if quality_faq:
            reply += f"**质量问题处理流程**：\n{quality_faq.answer[:300]}...\n\n"

        # 创建工单建议
        reply += "---\n"
        reply += "我建议为您**创建一个优先工单**，会有专人跟进处理。\n"
        reply += "请补充以下信息：\n"
        reply += "- 订单号\n"
        reply += "- 问题描述（越详细越好）\n"
        reply += "- 相关照片（如有）\n\n"

        if sentiment.should_escalate:
            reply += "⚠️ 由于问题的严重性，我会将此工单标记为**高优先级**并升级给主管。"

        return AgentResponse(
            content=reply,
            data={
                "type": "complaint_handling",
                "sentiment": sentiment.model_dump(),
                "suggest_ticket": True,
                "priority": "high" if sentiment.should_escalate else "medium"
            },
            display_type="ticket_prompt"
        )


    async def _handle_escalation(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理升级/严重投诉"""

        reply = "我理解这件事对您非常重要，让我立即为您安排专人处理。\n\n"
        reply += "---\n"
        reply += "**已触发升级流程** 🔴\n\n"
        reply += "- 您的对话已被标记为**紧急**\n"
        reply += "- 主管将在 **30 分钟内** 联系您\n"
        reply += "- 同时为您创建**优先工单**\n\n"

        reply += "为了更快地帮助您，请告知：\n"
        reply += "1. 最好联系方式（电话/邮箱）\n"
        reply += "2. 方便接听的时间\n"
        reply += "3. 事件简要经过\n\n"

        reply += "再次为给您带来的困扰致歉，我们会认真对待每一个反馈。"

        # 标记对话需要升级
        conv.escalation_triggered = True

        return AgentResponse(
            content=reply,
            data={
                "type": "escalation",
                "sentiment": sentiment.model_dump(),
                "sla": "30分钟内响应",
                "urgent": True
            },
            display_type="escalation_notice"
        )

    async def _handle_general(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理通用查询"""

        if self._faq_error:
            return self._faq_unavailable_response(query, self._faq_error)
        if not self.faq_database:
            return self._faq_empty_response(query)

        # 尝试模糊匹配 FAQ
        match_result = self._search_faq(query, threshold=0.2)

        if match_result.matches:
            top_match = match_result.matches[0]
            reply = f"关于「{query}」，我找到以下相关信息：\n\n"
            reply += f"{top_match.answer[:200]}...\n\n"
            reply += "这是您想要的吗？如果不是，请换个说法再试试。"

            return AgentResponse(
                content=reply,
                data={
                    "type": "general_faq",
                    "match": top_match.model_dump()
                },
                display_type="text"
            )

        # 无法匹配时的兜底回复
        replies = [
            "感谢您的提问！我还在学习中，这个问题我暂时无法准确回答。\n\n您可以：\n- 换个方式描述问题\n- 查看【常见问题】列表\n- 联系人工客服获取帮助",
            "这是个好问题！让我想想... 😊\n\n目前我没有找到完全匹配的答案。建议您：\n1. 提供更多细节（比如订单号、具体场景）\n2. 或直接联系人工客服：support@example.com",
        ]

        return AgentResponse(
            # ★ 修复：此前是 random.choice(replies) —— 同一问题两次得到不同兜底话术。
            #   这两条只是措辞差异、语义等价，随机没有价值；取第一条即可（可测、可复现）。
            content=replies[0],
            data={"type": "no_match", "original_query": query},
            display_type="text"
        )

    # ---- 工单管理 ----

    async def create_ticket(
        self,
        subject: str,
        description: str,
        category: str = "general",
        order_id: Optional[str] = None,
        priority: Optional[str] = None,
        customer_id: str = ""
    ) -> TicketCreateResult:
        """
        创建工单

        Args:
            subject: 工单标题
            description: 问题描述
            category: 分类
            order_id: 关联订单号
            priority: 优先级（可选，自动计算）
            customer_id: 客户 ID

        Returns:
            TicketCreateResult
        """
        # 自动确定优先级
        if not priority:
            priority = self._calculate_ticket_priority(subject, description, category)

        # 生成工单号
        ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"

        # SLA 计算
        sla_map = {"urgent": "2h", "high": "4h", "medium": "24h", "low": "48h"}
        sla_hours = {"urgent": 2, "high": 4, "medium": 24, "low": 48}
        sla_deadline = (datetime.now() + timedelta(hours=sla_hours.get(priority, 24))).isoformat()

        ticket = TicketInfo(
            ticket_id=ticket_id,
            subject=subject,
            description=description,
            category=category,
            priority=priority,
            status="open",
            customer_id=customer_id,
            order_id=order_id,
            created_at=datetime.now().isoformat(),
            sla_deadline=sla_deadline,
            tags=[category, priority]
        )

        # 生成自动回复建议
        auto_replies = self._generate_auto_replies(category, priority)

        return TicketCreateResult(
            success=True,
            ticket=ticket,
            estimated_response_time=sla_map.get(priority, "24h"),
            auto_replies=auto_replies
        )


    def _calculate_ticket_priority(self, subject: str, description: str, category: str) -> str:
        """自动计算工单优先级"""
        text = (subject + " " + description).lower()

        # 紧急关键词
        urgent_keywords = ["无法", "不能用", "丢失", "被盗", "安全", "dangerous", "urgent"]
        if any(kw in text for kw in urgent_keywords):
            return "urgent"

        # 高优先级
        high_keywords = ["退款", "投诉", "质量问题", "错误", "wrong", "broken"]
        if any(kw in text for kw in high_keywords):
            return "high"

        # 中等优先级
        medium_categories = ["售后", "物流"]
        if category in medium_categories:
            return "medium"

        return "low"

    def _generate_auto_replies(self, category: str, priority: str) -> List[str]:
        """生成自动回复模板"""
        templates = {
            "售后": [
                "您好！我们已收到您的售后申请，将在 24 小时内处理完毕。",
                "请您放心，我们会全力协助您解决问题。",
            ],
            "物流": [
                "物流问题已记录，正在与承运商核实最新状态。",
                "如急需，我们可以发起内部催查流程。",
            ],
            "general": [
                "感谢您的反馈，我们已收到您的工单。",
            ],
        }

        base = templates.get(category, templates["general"])
        if priority in ["urgent", "high"]:
            base.append("由于问题较紧急，已升级为优先处理。")

        return base

    def _generate_empathy(self, sentiment: SentimentAnalysis) -> str:
        """根据情感生成共情语句"""
        if sentiment.sentiment == "angry":
            return "我完全理解您的心情，遇到这种情况确实令人沮丧。😔"
        elif sentiment.sentiment == "negative":
            return "很抱歉给您带来不便，我来帮您解决。"
        elif sentiment.sentiment == "positive":
            return "很高兴能为您提供帮助！😊"
        else:
            return "好的，让我来看看怎么帮您。"

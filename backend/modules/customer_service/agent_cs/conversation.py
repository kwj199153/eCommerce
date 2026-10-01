"""会话：多轮上下文读写、意图分派、能力与摘要出口。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

from typing import Dict, Optional
from datetime import datetime
from uuid import uuid4
from ._base import AgentResponse, ConversationContext, ConversationTurn, SentimentAnalysis

class MixinConversation:
    """会话：多轮上下文读写、意图分派、能力与摘要出口。"""

    # ---- 路由分发 ----

    async def _route_by_intent(
        self,
        intent: str,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """根据意图路由到对应处理方法"""

        # ★ 话术是几乎所有分支的原料 ⇒ 在**路由之前**统一加载一次，
        #   而不是让每个 handler 各自去取（那会把 await 撒得到处都是，
        #   漏一处就静默用空列表作答，看起来只是「没找到答案」）。
        #   失败原因落在 `self._faq_error`，由各分支决定怎么表达。
        await self.ensure_faq((context or {}).get("store_id"))

        handlers = {
            "faq_query": self._handle_faq_query,
            "order_tracking": self._handle_order_tracking,
            "return_refund": self._handle_return_refund,
            "complaint": self._handle_complaint,
            "shipping_inquiry": self._handle_shipping_inquiry,
            "payment_issue": self._handle_payment_issue,
            "escalation": self._handle_escalation,
            "general": self._handle_general,
        }

        handler = handlers.get(intent, self._handle_faq_query)
        return await handler(query, context, conv, sentiment)


    # ---- 辅助方法 ----

    def _generate_conversation_id(self) -> str:
        """生成唯一会话 ID"""
        return f"conv-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"

    def _get_or_create_conversation(self, conversation_id: str) -> ConversationContext:
        """获取或创建对话上下文"""
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = ConversationContext(
                conversation_id=conversation_id
            )
        return self.conversations[conversation_id]

    def _add_user_turn(self, conv: ConversationContext, content: str, intent: str, sentiment: SentimentAnalysis):
        """添加用户消息到对话历史"""
        turn = ConversationTurn(
            role="user",
            content=content,
            timestamp=datetime.now().isoformat(),
            intent=intent,
            sentiment=sentiment.sentiment,
            entities=self._extract_entities(content)
        )
        conv.turns.append(turn)
        conv.turn_count += 1

    def _add_assistant_turn(self, conv: ConversationContext, content: str, intent: str):
        """添加助手回复到对话历史"""
        turn = ConversationTurn(
            role="assistant",
            content=content,
            timestamp=datetime.now().isoformat(),
            intent=intent
        )
        conv.turns.append(turn)


    async def get_conversation_summary(self, conversation_id: str) -> Optional[Dict]:
        """获取对话摘要"""
        conv = self.conversations.get(conversation_id)
        if not conv:
            return None

        return {
            "conversation_id": conv.conversation_id,
            "turn_count": conv.turn_count,
            "current_topic": conv.current_topic,
            "resolved_topics": conv.resolved_topics,
            "escalation_triggered": conv.escalation_triggered,
            "last_message": conv.turns[-1].content if conv.turns else None
        }

    def get_capabilities(self) -> Dict:
        """返回 Agent 能力描述"""
        return {
            "name": self.agent_name,
            "role": self.agent_role,
            "capabilities": [
                {"name": "FAQ 智能问答", "description": "基于知识库的语义匹配 + 自然语言生成"},
                {"name": "订单追踪", "description": "订单状态查询、物流信息跟踪"},
                {"name": "退换货处理", "description": "退货退款流程指引、工单创建"},
                {"name": "情感分析", "description": "客户情绪识别、升级转人工判断"},
                {"name": "工单管理", "description": "自动分类、优先级计算、SLA 管理"},
                {"name": "多轮对话", "description": "上下文保持、话题切换、实体记忆"},
            ],
            # ★ 语义变了：这是「**当前已加载**的话术条数」，不是「全库条数」。
            #   单例 Agent 在没有店铺上下文时是 0（话术是租户隔离数据）。
            "faq_count": len(self.faq_database),
            "categories": list(set(f.category for f in self.faq_database))
        }

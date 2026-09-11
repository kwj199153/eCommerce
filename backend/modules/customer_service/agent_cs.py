"""
智能客服 Agent (Customer Service Agent - RAG + LLM)

跨境电商 AI 客服专家，基于 RAG 架构实现知识库问答。
已集成 DashScope Qwen LLM + SKLearnVectorStore 混合检索。

功能模块：
1. FAQ 智能匹配 - RAG 向量检索 + 关键词混合 + LLM 生成自然回复
2. 多轮对话上下文 - 订单追踪、退换货、物流查询
3. 工单自动分类 - 问题类型识别 + 优先级判断
4. 情感分析 - 客户情绪检测 + 升级转人工决策
5. 常见问题自动回复 - 高频问题模板匹配
6. 知识库管理 - FAQ 导入/更新/搜索

架构升级：
- Phase 5: 纯关键词匹配模拟响应
- Phase 8: 接入真实 LLM (DashScope Qwen) + RAG 混合检索引擎
"""

import json
import re
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime, timedelta
import random
import hashlib

from pydantic import BaseModel, Field

# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    # 定义空基类作为降级
    class LLMEnabledAgent:
        ENABLE_LLM = False
        ENABLE_RAG = False
        def __init__(self): pass


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型


# ---- FAQ 相关 ----

class FAQItem(BaseModel):
    """FAQ 条目"""
    id: str
    question: str
    answer: str
    category: str  # 物流/退换货/支付/账户/产品/其他
    keywords: List[str] = []
    priority: int = 0  # 显示优先级
    views: int = 0  # 浏览次数
    helpful_count: int = 0  # 有用反馈数


class FAQMatchResult(BaseModel):
    """FAQ 匹配结果"""
    query: str
    matches: List[FAQItem]
    best_match: Optional[FAQItem] = None
    confidence: float = 0.0  # 匹配置信度 0-1
    suggested_questions: List[str] = []  # 相关问题建议


# ---- 工单相关 ----

class TicketInfo(BaseModel):
    """工单信息"""
    ticket_id: str
    subject: str
    description: str
    category: str  # 售后/物流/质量/投诉/咨询
    priority: str  # low/medium/high/urgent
    status: str  # open/in_progress/resolved/closed
    customer_id: str = ""
    order_id: Optional[str] = None
    created_at: str
    assigned_to: str = ""
    sla_deadline: Optional[str] = None
    tags: List[str] = []


class TicketCreateResult(BaseModel):
    """工单创建结果"""
    success: bool
    ticket: Optional[TicketInfo] = None
    estimated_response_time: str = ""
    auto_replies: List[str] = []  # 自动回复建议


# ---- 对话上下文 ----

class ConversationTurn(BaseModel):
    """对话轮次"""
    role: str  # user/assistant/system
    content: str
    timestamp: str
    intent: Optional[str] = None
    sentiment: Optional[str] = None  # positive/neutral/negative/angry
    entities: Dict[str, str] = {}  # 提取的实体（订单号、ASIN等）


class ConversationContext(BaseModel):
    """对话上下文"""
    conversation_id: str
    turns: List[ConversationTurn] = []
    customer_info: Dict[str, str] = {}  # 客户信息缓存
    current_topic: str = ""  # 当前话题
    resolved_topics: List[str] = []  # 已解决问题
    escalation_triggered: bool = False  # 是否触发升级
    turn_count: int = 0


# ---- 情感分析结果 ----

class SentimentAnalysis(BaseModel):
    """情感分析"""
    sentiment: str  # positive/neutral/negative/angry
    confidence: float  # 0-1
    intensity: float  # 0-1 情感强度
    key_emotions: List[str] = []  # 关键情绪词
    should_escalate: bool = False  # 是否需要升级人工
    escalate_reason: str = ""


# ====== 模拟知识库数据 ======

MOCK_FAQ_DB: List[Dict[str, Any]] = [
    {
        "id": "faq-001",
        "question": "发货时间要多久？",
        "answer": "标准发货时间如下：\n\n**国内仓发货**：下单后 1-3 个工作日发出，快递 3-5 天送达\n**美国 FBA 仓**：Prime 会员 1-2 天，普通 3-5 个工作日\n**海外直邮**：7-15 个工作日（取决于目的地和清关速度）\n\n您可以在订单详情页查看实时物流跟踪信息。",
        "category": "物流",
        "keywords": ["发货", "时间", "多久", "几天", "配送", "快递", "物流"],
        "priority": 100,
        "views": 1520,
        "helpful_count": 1280
    },
    {
        "id": "faq-002",
        "question": "如何申请退货？",
        "answer": "**退货流程**：\n\n1. 登录账户 → 「我的订单」→ 选择需退货的订单\n2. 点击「申请售后」→ 选择退货原因\n3. 填写退货说明 → 提交申请\n4. 等待审核（1-2 个工作日）\n5. 审核通过后寄回商品（我们提供 prepaid label）\n6. 仓库验收后 3-5 个工作日内退款\n\n**退货条件**：\n- 收到商品 30 天内\n- 商品未使用、原包装完整\n- 非定制类商品\n\n特殊情况请联系客服处理。",
        "category": "退换货",
        "keywords": ["退货", "退款", "退换", "return", "refund", "不满意"],
        "priority": 95,
        "views": 980,
        "helpful_count": 856
    },
    {
        "id": "faq-003",
        "question": "运费怎么计算？",
        "answer": "**运费标准**：\n\n| 订单金额 | 运费 |\n|---------|------|\n| ≥ $35 | **免费** |\n| $20-$34.99 | $4.99 |\n| <$20 | $6.99 |\n\n**特殊商品**：\n- 大件家具/家电：按实际重量计算\n- 危险品：额外 $5 处理费\n- 加急配送：$12.99 起\n\n**Prime 会员**：全站免运费",
        "category": "物流",
        "keywords": ["运费", "包邮", "shipping", "费用", "多少钱", "快递费"],
        "priority": 90,
        "views": 876,
        "helpful_count": 720
    },
    {
        "id": "faq-004",
        "question": "我的订单在哪里？怎么查？",
        "answer": "**订单查询方式**：\n\n1. **网站查询**：登录 → 「我的订单」→ 输入订单号或选择日期范围\n2. **邮件查询**：订单确认邮件中包含订单详情链接\n3. **客服查询**：提供注册邮箱或订单号，客服帮您查找\n\n**订单状态说明**：\n- `待付款`：请尽快完成支付\n- `已确认`：订单已接收，准备拣货\n- `已发货`：商品已在途中（可查看物流）\n- `已签收`：交易完成\n- `已取消`：订单已取消（如有扣款将退款）\n\n如需帮助，请提供您的订单号或下单邮箱。",
        "category": "订单",
        "keywords": ["订单", "哪里", "查询", "tracking", "order", "单号", "物流"],
        "priority": 92,
        "views": 1340,
        "helpful_count": 1100
    },
    {
        "id": "faq-005",
        "question": "产品质量有问题怎么办？",
        "answer": "**质量问题处理流程**：\n\n1. **拍照留存**：拍摄清晰的问题部位照片（2-3 张不同角度）\n2. **联系客服**：通过在线客服或邮件说明情况\n3. **提交证据**：上传照片 + 订单号 + 问题描述\n4. **解决方案**（根据具体情况）：\n   - **换货**：免费补发全新商品\n   - **退款**：原路退回（3-5 个工作日到账）\n   - **部分退款**：保留商品但获得部分补偿\n   - **维修**：提供维修服务或配件\n\n**承诺**：正品保障，假一赔十；质量问题 30 天无理由退换。",
        "category": "售后",
        "keywords": ["质量", "问题", " defective", "坏了", "损坏", "瑕疵", "不合格"],
        "priority": 98,
        "views": 654,
        "helpful_count": 589
    },
    {
        "id": "faq-006",
        "question": "可以修改收货地址吗？",
        "answer": "**地址修改规则**：\n\n| 订单状态 | 能否修改 |\n|---------|----------|\n| 待付款 | ✅ 可以 |\n| 已确认（未发货）| ⚠️ 联系客服 |\n| 已发货 | ❌ 无法修改 |\n\n**修改方式**：\n1. 如订单还在「待付款」状态：直接在订单页点击「编辑」\n2. 如已确认但未发货：立即联系客服，我们尽力协调\n3. 如已发货：只能尝试联系物流公司改派（不保证成功）\n\n⚠️ 请务必在下单前确认地址准确！",
        "category": "订单",
        "keywords": ["地址", "修改", "更改", "收货", "送货", "address"],
        "priority": 85,
        "views": 567,
        "helpful_count": 490
    },
    {
        "id": "faq-007",
        "question": "支持哪些支付方式？",
        "answer": "**支持的支付方式**：\n\n💳 **信用卡/借记卡**：Visa、Mastercard、American Express、Discover\n📱 **数字钱包**：Apple Pay、Google Pay、PayPal\n🏦 **银行转账**：支持主流银行（处理时间 1-3 天）\n💰 **分期付款**：订单满 $50 可选 3/6/12 期免息分期\n\n**安全保证**：\n- PCI DSS Level 1 认证\n- SSL 加密传输\n- 3D Secure 验证\n\n所有交易均以 USD 结算。",
        "category": "支付",
        "keywords": ["支付", "付款", "pay", "信用卡", "paypal", "分期"],
        "priority": 88,
        "views": 789,
        "helpful_count": 650
    },
    {
        "id": "faq-008",
        "question": "如何联系人工客服？",
        "answer": "**联系我们**：\n\n🕐 **在线客服**：周一至周日 8:00-24:00 (EST)\n📧 **邮箱**：support@example.com（24 小时内回复）\n📱 **电话**：1-800-XXX-XXXX（9:00-21:00 EST）\n\n**自助服务推荐**：\n- 80% 的常见问题可在 FAQ 中找到答案\n- 订单问题优先使用「订单查询」功能\n- 退换货直接走线上申请流程\n\n如需人工服务，建议准备好：订单号、问题描述、相关截图。",
        "category": "其他",
        "keywords": ["客服", "联系", "人工", "电话", "email", "help"],
        "priority": 75,
        "views": 456,
        "helpful_count": 398
    },
    {
        "id": "faq-009",
        "question": "关税和进口税谁承担？",
        "answer": "**税费政策**：\n\n**美国境内订单**：价格已含税，无额外税费\n\n**国际订单**：\n- **DDP（完税后交货）**：显示的价格包含预估关税，无需额外支付\n- **DDP 未覆盖国家**：收货时可能需要缴纳进口税（由收件人承担）\n\n**关税估算**：\n- 大多数国家：商品价值的 5-20%\n- 免税额度因国而异（如欧盟 €150 以下免税）\n\n结账时会显示预估税费（最终以海关为准）。",
        "category": "物流",
        "keywords": ["关税", "税", "进口税", "customs", "duty", "tax"],
        "priority": 70,
        "views": 432,
        "helpful_count": 378
    },
    {
        "id": "faq-010",
        "question": "如何修改或取消订单？",
        "answer": "**订单修改/取消**：\n\n**取消订单**：\n- 「待付款」状态：可直接取消\n- 「已确认」状态：1 小时内可自助取消，之后需联系客服\n- 「已发货」状态：无法取消（收到后可申请退货）\n\n**修改订单**：\n- 数量增减：仅限「待付款」状态\n- 商品更换：需取消原订单重新下单\n- 地址修改：见 FAQ #006\n\n⚠️ 订单进入拣货流程后将无法修改，请尽早操作。",
        "category": "订单",
        "keywords": ["取消", "修改", "cancel", "改", "不要了"],
        "priority": 87,
        "views": 623,
        "helpful_count": 545
    },
    {
        "id": "faq-011",
        "question": "收到商品破损怎么办？",
        "answer": "**运输破损处理**：\n\n**立即行动**：\n1. **拍照留证**：外箱 + 内部商品 + 破损部位（多角度）\n2. **保留包装**：不要丢弃原始包装（可能需要退回）\n3. **24小时内报告**：越快越好，超过 48 小时可能影响理赔\n\n**赔偿方案**：\n- **全额退款** + 重新发货（首选）\n- **部分退款**（如仍想保留可用部分）\n- **补发配件**（如只是零件损坏）\n\n**我们的承诺**：运输破损 100% 赔偿，运费我们承担。",
        "category": "售后",
        "keywords": ["破损", "碎", "坏了", "damaged", "broken", "运输损坏"],
        "priority": 96,
        "views": 445,
        "helpful_count": 401
    },
    {
        "id": "faq-012",
        "question": "Prime 会员有什么权益？",
        "answer": "**Prime 会员权益**：\n\n🚚 **免费配送**\n- 全站免运费（无最低消费）\n- Prime 商品 1-2 日达\n- 部分地区当日达\n\n🎬 **娱乐权益**\n- Prime Video 流媒体\n- Prime Music 无限听歌\n- Kindle 借阅图书馆\n\n🛒 **购物特权**\n- 限时抢购（Lightning Deals）提前 30 分钟入场\n- 专属折扣区\n- 生日礼遇\n\n💰 **费用**：$14.99/月 或 $139/年\n**试用**：新用户可享 30 天免费试用",
        "category": "其他",
        "keywords": ["prime", "会员", "vip", "权益", "订阅"],
        "priority": 72,
        "views": 567,
        "helpful_count": 489
    }
]


# ====== 智能客服 Agent 主类 ======

class CustomerServiceAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
    """
    跨境电商 AI 智能客服 Agent

    基于 RAG 架构的知识库问答系统，
    支持多轮对话、情感分析、工单管理。

    升级特性：
    - ✅ DashScope Qwen LLM 真实调用
    - ✅ SKLearnVectorStore + TF-IDF 混合检索
    - ✅ 自动降级（LLM 不可用时使用模拟响应）
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-plus"       # 客服场景用均衡模型
    ENABLE_LLM = True                 # 启用 LLM
    ENABLE_RAG = True                 # 启用 RAG 检索
    FALLBACK_TO_MOCK = True           # 允许降级

    def __init__(self):
        # 初始化 LLM 基类
        if LLM_AVAILABLE:
            super().__init__()

        self.agent_name = "智能客服"
        self.agent_role = "跨境电商 AI 客服专家"

        # 加载知识库（保留作为降级方案）
        self.faq_database = [FAQItem(**item) for item in MOCK_FAQ_DB]

        # 会话管理（模拟：生产环境用 Redis）
        self.conversations: Dict[str, ConversationContext] = {}

        # 情感词典
        self._init_sentiment_lexicon()

        # RAG 引擎（延迟初始化）
        self._rag_initialized = False

    def _init_sentiment_lexicon(self):
        """初始化情感词典"""
        self.positive_words = [
            "满意", "喜欢", "好", "棒", "优秀", "感谢", "赞", "给力",
            "good", "great", "excellent", "happy", "love", "perfect",
            "thanks", "thank you", "awesome", "nice", "helpful"
        ]
        self.negative_words = [
            "差", "烂", "垃圾", "失望", "生气", "愤怒", "投诉", "退款",
            "骗", "欺诈", "慢", "坏", "broken", "bad", "terrible",
            "angry", "frustrating", "disappointed", "worst", "waste",
            "unacceptable", "ridiculous", "never again", "demand"
        ]
        self.escalation_triggers = [
            "投诉", "举报", "律师", "诉讼", "消费者协会", "媒体曝光",
            "lawyer", "sue", "lawsuit", "BBB", "attorney", "court",
            " scam", "fraud", "report to", " authorities"
        ]

    async def invoke(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None
    ) -> AgentResponse:
        """
        主入口：处理用户查询

        Args:
            query: 用户输入
            context: 附加上下文（订单号、客户信息等）
            conversation_id: 会话 ID（用于多轮对话）

        Returns:
            AgentResponse 结构化响应
        """
        # 1. 意图分类
        intent = self._classify_intent(query)

        # 2. 情感分析
        sentiment = self._analyze_sentiment(query)

        # 3. 获取或创建对话上下文
        if not conversation_id:
            conversation_id = self._generate_conversation_id()

        conv_context = self._get_or_create_conversation(conversation_id)

        # 4. 记录用户消息
        self._add_user_turn(conv_context, query, intent, sentiment)

        # 5. 路由到对应处理方法
        result = await self._route_by_intent(intent, query, context, conv_context, sentiment)

        # 6. 记录助手回复
        self._add_assistant_turn(conv_context, result.content, intent)

        return result

    async def stream_chat(self, query: str) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        客服对话类意图走 LLM 流式；结构化意图（订单追踪/工单等）退化为一次性文本。

        Yields:
            文本片段（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        intent = self._classify_intent(query)

        # 结构化意图：走 invoke 一次性返回（含结构化卡片数据）
        if intent in ("order_tracking", "ticket_create", "escalation"):
            result = await self.invoke(query)
            yield result.content
            return

        # 对话类：走 LLM 流式（RAG 客服优先用 RAG 回答，此处简化走 LLM）
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
            result = await self.invoke(query)
            yield result.content
            return

        try:
            async for chunk in self.llm_stream(
                query,
                system_prompt=self.get_prompt_template("customer_service"),
                model=self.DEFAULT_MODEL,
                temperature=0.7,
                max_tokens=1024,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[customer_service] stream_chat failed: {e}")
            result = await self.invoke(query)
            yield result.content

    # ---- 意图分类 ----

    def _classify_intent(self, query: str) -> str:
        """
        分类用户意图

        Returns:
            faq_query / order_tracking / return_refund / complaint /
            shipping inquiry / payment_issue / general / escalation
        """
        query_lower = query.lower()

        # 升级/投诉意图（最高优先级）
        escalation_patterns = [
            "投诉", "举报", "律师", "诉讼", "消费者协会", "媒体",
            "complaint", "sue", "lawsuit", "scam", "fraud", " BBB",
            "经理", "主管", "领导", "manager", "supervisor"
        ]
        for p in escalation_patterns:
            if p in query_lower:
                return "escalation"

        # 订单追踪
        order_patterns = [
            "订单", "order", "单号", "物流", "tracking", "快递",
            "发货", "delivery", "到哪里了", "查一下", "status"
        ]
        if any(p in query_lower for p in order_patterns):
            return "order_tracking"

        # 退换货
        return_patterns = [
            "退货", "退款", "退换", "return", "refund", "不满意",
            "不要了", "换一个", "exchange", "cancel order"
        ]
        if any(p in query_lower for p in return_patterns):
            return "return_refund"

        # 投诉/质量问题
        complaint_patterns = [
            "质量", "问题", "坏的", "破损", "缺陷", "defective",
            "broken", "damaged", "wrong", "error", "mistake",
            "欺骗", "虚假", "misleading"
        ]
        if any(p in query_lower for p in complaint_patterns):
            return "complaint"

        # 物流询问
        shipping_patterns = [
            "运费", "包邮", "shipping", "多久到", "几天", "配送",
            "地址", "关税", "税", "customs", "duties"
        ]
        if any(p in query_lower for p in shipping_patterns):
            return "shipping_inquiry"

        # 支付问题
        payment_patterns = [
            "支付", "付款", "pay", "信用卡", "paypal", "charge",
            "扣款", "账单", "invoice", "billing"
        ]
        if any(p in query_lower for p in payment_patterns):
            return "payment_issue"

        # 默认走 FAQ 匹配
        return "faq_query"

    # ---- 情感分析 ----

    def _analyze_sentiment(self, text: str) -> SentimentAnalysis:
        """
        分析文本情感

        Returns:
            SentimentAnalysis 包含情感标签、置信度、是否需要升级
        """
        text_lower = text.lower()

        positive_count = sum(1 for w in self.positive_words if w in text_lower)
        negative_count = sum(1 for w in self.negative_words if w in text_lower)
        escalation_match = any(t in text_lower for t in self.escalation_triggers)

        total = positive_count + negative_count
        if total == 0:
            return SentimentAnalysis(
                sentiment="neutral",
                confidence=0.5,
                intensity=0.2,
                key_emotions=[],
                should_escalate=False
            )

        negative_ratio = negative_count / total
        intensity = min(1.0, (positive_count + negative_count) / 5)

        if negative_ratio > 0.6 or escalation_match:
            sentiment = "angry" if escalation_match else "negative"
            should_escalate = escalation_match or negative_ratio > 0.8
        elif negative_ratio < 0.3 and positive_count > 0:
            sentiment = "positive"
            should_escalate = False
        else:
            sentiment = "neutral"
            should_escalate = False

        # 提取关键情感词
        key_emotions = []
        for w in self.positive_words:
            if w in text_lower:
                key_emotions.append(w)
        for w in self.negative_words:
            if w in text_lower:
                key_emotions.append(w)

        return SentimentAnalysis(
            sentiment=sentiment,
                    confidence=max(0.5, 1.0 - abs(negative_ratio - 0.5) * 2),
            intensity=intensity,
            key_emotions=key_emotions[:5],
            should_escalate=should_escalate,
            escalate_reason="检测到升级关键词" if escalation_match else (
                "负面情感过强" if should_escalate else ""
            )
        )

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

    # ---- 各意图处理器 ----

    async def _handle_faq_query(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理 FAQ 查询（支持 RAG + LLM 增强）"""

        # ====== 升级：优先使用 RAG + LLM ======
        if LLM_AVAILABLE and self.ENABLE_RAG and self.rag_engine:
            try:
                return await self._handle_faq_with_rag(query, context, conv, sentiment)
            except Exception as e:
                logger.warning(f"RAG 处理失败，降级到关键词匹配: {e}")

        # ====== 降级方案：原始关键词匹配 ======

        # 1. 在知识库中检索匹配
        match_result = self._search_faq(query)

        # 2. 如果有高置信度匹配，直接返回答案
        if match_result.confidence >= 0.7 and match_result.best_match:
            faq = match_result.best_match

            # 个性化回复
            reply = f"**找到了相关问题解答** 👇\n\n{faq.answer}\n\n"
            reply += "---\n*这个回答对您有帮助吗？*\n"

            # 追加相关问题建议
            if match_result.suggested_questions:
                reply += "\n**您可能还想知道**：\n"
                for sq in match_result.suggested_questions[:3]:
                    reply += f"- {sq}\n"

            return AgentResponse(
                content=reply,
                data={
                    "type": "faq_match",
                    "query": query,
                    "match": faq.model_dump(),
                    "confidence": match_result.confidence,
                    "suggested": match_result.suggested_questions[:5],
                    "source": "keyword_match",  # 标记来源
                },
                display_type="faq_answer"
            )

        # 3. 低置信度：返回多个可能相关的 FAQ
        if match_result.matches:
            reply = "我找到几个可能与您问题相关的内容：\n\n"
            for i, m in enumerate(match_result.matches[:3], 1):
                reply += f"**{i}. {m.question}**\n"
                reply += f"{m.answer[:100]}...\n\n"

            reply += "请问以上哪个更符合您的情况？或者您可以详细描述一下问题。"

            return AgentResponse(
                content=reply,
                data={
                    "type": "faq_suggestions",
                    "matches": [m.model_dump() for m in match_result.matches[:3]],
                    "confidence": match_result.confidence,
                    "source": "keyword_match",
                },
                display_type="faq_list"
            )

        # 4. 无匹配：尝试 LLM 或生成通用回复
        if LLM_AVAILABLE and self.llm_client:
            try:
                llm_result = await self.llm_chat(
                    user_message=query,
                    system_prompt=self.get_prompt_template("customer_service"),
                )
                return AgentResponse(
                    content=llm_result.content,
                    data={"type": "llm_generated", "fallback": llm_result.fallback},
                    display_type="text",
                )
            except Exception as e:
                logger.warning(f"LLM FAQ fallback error: {e}")

        return await self._handle_general(query, context, conv, sentiment)

    async def _handle_faq_with_rag(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """使用 RAG 引擎处理 FAQ 查询"""

        # 确保 RAG 已初始化
        if not self._rag_initialized:
            await self.initialize_rag(faq_items=[
                {"question": f.question, "answer": f.answer, "category": f.category}
                for f in self.faq_database
            ])
            self._rag_initialized = True

        # 调用 RAG 回答
        rag_result = await self.llm_rag_answer(
            query=query,
            system_prompt=self.get_prompt_template("customer_service"),
            top_k=3,
        )

        # 构建响应
        sources_info = []
        if hasattr(rag_result, '_sources') and rag_result._sources:
            sources_info = rag_result._sources

        reply = rag_result.content

        # 如果有引用来源，追加说明
        if sources_info and not rag_result.fallback:
            reply += "\n\n---\n*📚 参考了 {} 条知识库文献*".format(len(sources_info))

        # 根据情感调整语气后缀
        if sentiment.level == "negative":
            reply += "\n\n如果您的问题没有得到解决，可以点击下方「转人工」按钮。"
        elif sentiment.level == "angry":
            reply += "\n\n非常抱歉给您带来不好的体验，我已将您的问题标记为紧急，会有专人尽快跟进。"

        return AgentResponse(
            content=reply,
            data={
                "type": "rag_answer",
                "query": query,
                "confidence": getattr(rag_result, 'confidence', 0),
                "sources": sources_info,
                "fallback": rag_result.fallback,
                "source": "rag_hybrid",  # 标记为 RAG 来源
            },
            display_type="faq_answer"
        )

    async def _handle_order_tracking(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理订单追踪"""

        # 尝试从查询或上下文中提取订单号
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")

        if order_id:
            # 模拟订单查询结果
            order_info = self._mock_order_info(order_id)

            reply = f"**订单信息** 📦\n\n"
            reply += f"| 项目 | 详情 |\n|------|------|\n"
            reply += f"| 订单号 | `{order_info['order_id']}` |\n"
            reply += f"| 状态 | **{order_info['status_text']}** |\n"
            reply += f"| 下单时间 | {order_info['created_at']} |\n"
            reply += f"| 商品 | {order_info['product_name']} |\n"
            reply += f"| 金额 | ${order_info['total']} |\n"

            if order_info.get("tracking_number"):
                reply += f"\n**物流信息** 🚚\n"
                reply += f"- 快递单号：`{order_info['tracking_number']}`\n"
                reply += f"- 承运商：{order_info['carrier']}\n"
                reply += f"- 预计送达：{order_info['estimated_delivery']}\n"
                reply += f"\n[查看详细物流轨迹](#)"

            reply += f"\n---\n还有其他关于这个订单的问题吗？"

            return AgentResponse(
                content=reply,
                data={
                    "type": "order_detail",
                    "order": order_info
                },
                display_type="order_info"
            )

        # 无订单号时引导用户提供
        reply = "我可以帮您查询订单状态！请提供以下任一信息：\n\n"
        reply += "1. **订单号**（格式如 ORD-XXXXXXXX）\n"
        reply += "2. **下单时用的邮箱**\n"
        reply += "3. **下单手机号后四位**\n\n"
        reply += "您也可以告诉我大概的下单时间和购买的商品名称。"

        return AgentResponse(
            content=reply,
            data={"type": "order_query_prompt"},
            display_type="text"
        )

    async def _handle_return_refund(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理退换货请求"""

        # 先匹配 FAQ 中的退换货指南
        refund_faq = next(
            (f for f in self.faq_database if f.id == "faq-002"), None
        )

        if refund_faq:
            reply = f"**退换货指南** 🔄\n\n{refund_faq.answer}\n\n"

            # 根据情感调整语气
            if sentiment.sentiment == "negative" or sentiment.sentiment == "angry":
                reply += "非常抱歉给您带来不好的体验 😔 我理解您的感受，让我们尽快帮您解决这个问题。\n\n"

            reply += "---\n"
            reply += "需要我帮您**创建退换货工单**吗？请告诉我：\n"
            reply += "- 订单号\n"
            reply += "- 退换原因（质量问题/不喜欢/发错货/其他）"

            return AgentResponse(
                content=reply,
                data={
                    "type": "return_guide",
                    "faq_id": refund_faq.id,
                    "sentiment": sentiment.sentiment
                },
                display_type="return_guide"
            )

        return AgentResponse(content="抱歉，暂时无法处理退换货请求，请联系人工客服。")

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

    async def _handle_shipping_inquiry(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理物流询问"""

        # 匹配相关 FAQ
        shipping_faqs = [f for f in self.faq_database if f.category == "物流"]

        if shipping_faqs:
            # 找最相关的
            best_match = self._find_best_faq_match(query, shipping_faqs)

            reply = f"**关于物流问题** 📦\n\n{best_match.answer}\n\n"

            # 补充其他常见物流问题
            other_shipping = [f for f in shipping_faqs if f.id != best_match.id][:2]
            if other_shipping:
                reply += "**其他物流常见问题**：\n"
                for f in other_shipping:
                    reply += f"- Q: {f.question}\n"

            return AgentResponse(
                content=reply,
                data={
                    "type": "shipping_info",
                    "faq_id": best_match.id,
                    "related_faqs": [f.id for f in other_shipping]
                },
                display_type="faq_answer"
            )

        return await self._handle_faq_query(query, context, conv, sentiment)

    async def _handle_payment_issue(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理支付问题"""

        payment_faq = next(
            (f for f in self.faq_database if f.id == "faq-007"), None
        )

        if payment_faq:
            reply = f"**支付相关问题** 💳\n\n{payment_faq.answer}"

            return AgentResponse(
                content=reply,
                data={"type": "payment_info", "faq_id": payment_faq.id},
                display_type="faq_answer"
            )

        return AgentResponse(content="关于支付问题，请联系客服或查看帮助中心。")

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
            content=random.choice(replies),
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
        ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{random.randint(10000, 99999)}"

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

    # ---- FAQ 搜索引擎 ----

    def _search_faq(self, query: str, threshold: float = 0.3) -> FAQMatchResult:
        """
        在 FAQ 数据库中搜索匹配项

        使用关键词匹配 + 类别权重算法
        （生产环境替换为向量相似度检索）
        """
        query_lower = query.lower()
        query_terms = re.findall(r'\w+', query_lower)

        scored_matches = []

        for faq in self.faq_database:
            score = 0.0

            # 1. 标题精确匹配（权重最高）
            if any(term in faq.question.lower() for term in query_terms):
                score += 0.5
                # 完全包含得分更高
                if query_lower in faq.question.lower():
                    score += 0.3

            # 2. 关键词匹配
            keyword_matches = sum(1 for kw in faq.keywords if kw in query_lower)
            score += min(0.3, keyword_matches * 0.1)

            # 3. 类别热门度加权
            category_weight = {"物流": 1.1, "退换货": 1.15, "订单": 1.05}.get(faq.category, 1.0)
            score *= category_weight

            # 4. 优先级加权
            score *= (1 + faq.priority / 1000)

            if score >= threshold:
                scored_matches.append((score, faq))

        # 按分数排序
        scored_matches.sort(key=lambda x: x[0], reverse=True)

        matches = [m[1] for m in scored_matches[:5]]
        best_match = scored_matches[0][1] if scored_matches else None
        confidence = scored_matches[0][0] if scored_matches else 0.0

        # 生成相关问题建议
        suggested = [m.question for m in matches[1:4]] if len(matches) > 1 else []

        return FAQMatchResult(
            query=query,
            matches=matches,
            best_match=best_match,
            confidence=min(1.0, confidence),
            suggested_questions=suggested
        )

    def _find_best_faq_match(self, query: str, faq_list: List[FAQItem]) -> FAQItem:
        """从指定列表中找最佳匹配"""
        result = self._search_faq(query, threshold=0.1)
        # 过滤只在列表中的
        for m in result.matches:
            if m in faq_list:
                return m
        return faq_list[0] if faq_list else self.faq_database[0]

    # ---- 辅助方法 ----

    def _generate_conversation_id(self) -> str:
        """生成唯一会话 ID"""
        return f"conv-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"

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

    def _extract_order_id(self, text: str) -> Optional[str]:
        """从文本提取订单号"""
        patterns = [
            r'ORD[-–]?\d{8,}',
            r'order[- ]?(\d{8,})',
            r'(\d{10,})',  # 纯数字长串
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0) if match.lastindex is None else f"ORD-{match.group(1)}"
        return None

    def _extract_entities(self, text: str) -> Dict[str, str]:
        """提取实体信息"""
        entities = {}

        # 订单号
        order_id = self._extract_order_id(text)
        if order_id:
            entities["order_id"] = order_id

        # ASIN
        asin_match = re.search(r'B\d[A-Z0-9]{9}', text.upper())
        if asin_match:
            entities["asin"] = asin_match.group(0)

        # 邮箱
        email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', text)
        if email_match:
            entities["email"] = email_match.group(0)

        # 金额
        amount_match = re.search(r'\$(\d+\.?\d*)', text)
        if amount_match:
            entities["amount"] = amount_match.group(0)

        return entities

    def _mock_order_info(self, order_id: str) -> Dict[str, Any]:
        """模拟订单信息（生产环境对接真实订单系统）"""
        statuses = [
            ("delivered", "已签收"),
            ("shipped", "已发货"),
            ("processing", "处理中"),
        ]
        status = random.choice(statuses)

        products = [
            "Portable Coffee Grinder Pro",
            "Wireless Bluetooth Earbuds",
            "Smart Home Security Camera",
            "Stainless Steel Water Bottle",
        ]

        carriers = ["UPS", "FedEx", "USPS", "Amazon Logistics"]

        info = {
            "order_id": order_id,
            "status": status[0],
            "status_text": status[1],
            "created_at": (datetime.now() - timedelta(days=random.randint(1, 14))).strftime("%Y-%m-%d %H:%M"),
            "product_name": random.choice(products),
            "quantity": random.randint(1, 3),
            "total": round(random.uniform(19.99, 199.99), 2),
        }

        if status[0] == "shipped":
            info.update({
                "tracking_number": f"1Z{random.randint(1000000000, 9999999999)}",
                "carrier": random.choice(carriers),
                "estimated_delivery": (datetime.now() + timedelta(days=random.randint(1, 5))).strftime("%Y-%m-%d"),
            })

        return info

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

    # ---- 公开 API 方法 ----

    async def search_knowledge_base(self, query: str, limit: int = 5) -> List[Dict]:
        """公开接口：搜索知识库"""
        result = self._search_faq(query)
        return [m.model_dump() for m in result.matches[:limit]]

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
            "faq_count": len(self.faq_database),
            "categories": list(set(f.category for f in self.faq_database))
        }

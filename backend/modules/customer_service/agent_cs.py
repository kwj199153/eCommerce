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

import asyncio
import json
import re
from contextvars import ContextVar
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from core.logger import get_logger

# ★ 历史缺陷（已修）：3 处 logger.warning 曾在 except 里引用**未定义**的
#   `logger`，其中 `stream_chat failed` 那条最严重 —— 流式失败后本该回退到
#   `self.invoke(query)` 再答一次，NameError 会让回退根本不执行。
#   现已在下一行定义模块级 logger，修复即闭合。
#   ⚠️ 插值口径：本 logger 来自 loguru（`get_logger`），按 `str.format` 插值 ——
#      只能写 f-string / `{}`。写 `%s` **不报错**，参数被静默丢弃、
#      日志原样打出 "%s"（实测：`logger.warning("a=%s", 1)` → `a=%s`）。
#      标准库 `logging.getLogger(__name__)` 才用 `%s`。
logger = get_logger("customer_service.agent")

#: 请求级店铺归属（第 204 轮）。
#:
#: ★★★ `create_ticket` 必须带租户维度（`cs_tickets.shop_id` 有外键），而工具入参
#:   由 LLM 生成 —— 归属只能由**服务端**注入。改造前 `_create_ticket_tool` 把它
#:   写成普通形参，docstring 却写着「由系统注入，LLM 不得自行指定」：
#:   **注释承诺型假门禁**，模型照填不误。
#:
#: ★ 唯一写入点 = `_route_via_tools()`（工具环路的唯一入口），且必须在工具被调用
#:   之前 —— 否则第一次 `create_ticket` 会带着 `store_id=None` 落库，
#:   被 service 的 `require_shop_context` 拒掉（fail-closed，不会写脏行）。
_current_shop_id: ContextVar[Optional[str]] = ContextVar(
    "customer_service_current_shop_id", default=None
)


from pydantic import BaseModel, Field

# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.customer_service import prompts as _prompts  # noqa: F401


from ai_infra.sse import StreamDigest, progress


# 结构化意图 → 阶段进度文案（stream_chat 在耗时处理前发给前端，避免空转）
_INTENT_PROGRESS = {
    "order_tracking": "正在查询订单状态…",
    "ticket_create": "正在创建工单…",
    "escalation": "正在转接人工并整理上下文…",
}


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
    views: int = 0  # 浏览次数（表内无对应列，恒 0；不拿 usage_count 冒充实测）
    helpful_count: int = 0  # 有用反馈数
    usage_count: int = 0  # 被客服命中次数（来自 knowledge_faqs.usage_count）


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


# ====== 话术从哪里来 ======
#
# ★ 第 286 轮：客服话术的**唯一真源**是 `knowledge_faqs` 表，经
#   `modules/customer_service/faq_source.load_faq_items(shop_id)` 按店铺读取。
#
#   此前这里是一份 12 条的内存常量 `MOCK_FAQ_DB`：改不动、不落库、重启即回原样；
#   而运营在【资料库 → 业务话术库】里维护的那批真数据**从来没被检索到**
#   （审查见 docs/cs-data-source-audit-r285.md 第 2.3 节：名字叫
#   `search_knowledge_base`，检索源却是内存 12 条）。
#
#   那 12 条内容已逐字迁到 `cs_faq_seed.json`，由 `faq_source.seed_cs_faqs()`
#   灌进表 —— 数据还在，只是从「锁在源码里」变成「摆在库里、可编辑、可删」。
#
# ★ 本文件**不再**有任何内存话术常量。取不到就是取不到，如实报错，
#   绝不静默回退到一份假数据（本仓对静默降级的一贯立场）。


# ====== 智能客服 Agent 主类 ======

#: 订单状态 → 中文标签（**客服回复**用）
#:
#: ★ 为什么这张表放在客服这一层，而不是 trade 域：trade 的 `order_status` 是
#:   **平台无关**的英文码（将来接 Shopee / 独立站也沿用同一套码），把它翻成
#:   消费者能看懂的话是「展示层」的事 —— 放进 trade 就等于让数据模型去承担
#:   某一处 UI 的措辞。同理，`CAUSE_LABELS`（归因中文名）也住在 trade，因为
#:   那是业务口径；而「已签收」这种说法只服务客服话术。
_ORDER_STATUS_LABELS: dict = {
    "pending": "待处理",
    "unshipped": "未发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "cancelled": "已取消",
}


class CustomerServiceAgent(BaseAgent):
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
        super().__init__()

        self.agent_name = "智能客服"
        self.agent_role = "跨境电商 AI 客服专家"
        # ★ 第 204 轮：工具化路由子层（懒加载）。**不能**在 __init__ 里构建 ——
        #   那会触发 `tools → service → agent_cs` 循环导入。
        self._router: Optional[Any] = None

        # 话术库：**按需从 knowledge_faqs 表加载**（见 `ensure_faq`）。
        # ★ 这里刻意留空：Agent 是进程级单例，构造时还没有店铺上下文，
        #   而话术是**租户隔离**数据 —— 没有店铺就读不了，也不该读。
        self.faq_database: List[FAQItem] = []
        #: 上一次加载的店铺（诊断用：看这批话术属于哪个店铺）
        self._faq_shop: Optional[str] = None
        #: 上一次加载的失败原因（"" = 成功）。★ **空列表 ≠ 失败**：
        #   店铺还没配话术是正常的业务状态，与「库读不出来」必须分开表达。
        self._faq_error: str = ""
        #: 失败**原因的异常对象**（保类型用）。★ 为什么要留：字符串能显示给
        #   人看，但端点要靠**类型**区分 400（缺店铺）与 503（数据源不可用）
        #   —— 把 PermissionError 也降级成 RuntimeError 会让二者混成一种码。
        self._faq_error_exc: Optional[BaseException] = None

        # 会话管理（模拟：生产环境用 Redis）
        self.conversations: Dict[str, ConversationContext] = {}

        # 情感词典
        self._init_sentiment_lexicon()

        # RAG 引擎（延迟初始化）
        self._rag_initialized = False

    # ==================== 工具化路由（第 204 轮）====================
    #
    # 本 Agent 此前是**范式 B**：`invoke()` / `stream_chat()` → `_classify_intent()`
    # （关键词表）→ `_handle_*` 规则引擎；LLM 只出现在写文案的辅助方法里。
    # 于是 `customer_service_tools`（4 个）**零装配** —— 注册了、却没有任何 Agent
    # 绑定它（全仓 `from .tools import customer_service_tools` 零命中）。
    #
    # 现在接到**范式 A**（LLM 自主 bind_tools），做法与
    # `competitor_intel` / `listing_generator` / `product_research` 的
    # `_build_router()` 逐字同构。

    def _get_router(self):
        """懒加载工具化路由层，返回 None 表示不可用（回退关键词路由）。"""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def _build_router(self):
        """构建工具化路由层（BaseAgent 实例，注入 4 个客服工具）。

        ★★★ 为什么必须**组合一个 BaseAgent**，而不能只在 `super().__init__()`
          里多写一个 `tools=`：
            工具只在 `BaseAgent._llm_with_tools()` 里被 `bind_tools`，而它
            只被图节点 `_llm_call_node` 调用。本 Agent 自己的 `invoke()` /
            `stream_chat()` **从不驱动那张图** ⇒ 只加 `tools=` 是**装饰性接线**：
            注册表不再「悬空」、门禁变绿，而模型手里依旧没有工具 ——
            比不接更糟（把缺口藏起来）。
        """
        if not self.ENABLE_LLM:
            return None
        try:
            from .tools import customer_service_tools

            from ai_infra.base_agent import BaseAgent
            from ai_infra.budget import BUDGET_ROUTER
            from ai_infra.context import CONTEXT_ROUTER
            from core.checkpoint import get_checkpointer

            return BaseAgent(
                # ★ 子层名字带 `_router` 后缀（同 competitor / listing / PR），
                #   技能注入边界由 `modules.skills.agents.business_agent_name()` 归一回业务名。
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.get_prompt_template("customer_service"),
                tools=customer_service_tools,
                # 路由子层是「单次决策 + 一串工具调用、用完即答」⇒ 用 ROUTER 档。
                budget=BUDGET_ROUTER,
                context_policy=CONTEXT_ROUTER,
                checkpointer=get_checkpointer(),
                checkpoint_ns="customer_service",
            )
        except Exception as e:  # noqa: BLE001 —— 路由层不可用时回退，不影响主流程
            logger.warning(f"[customer_service] router build failed: {e}")
            return None

    async def _stream_via_tools(self, query: str,
                                context: Optional[Dict[str, Any]] = None) -> AsyncIterable:
        """流式工具路由：**实时**下发思考过程（step），答复文本仍一次性给出。

        ★ 与 `_route_via_tools` 是**同一条决策路径**（router 的 LLM 自主选工具），
          差别只在「过程能不能边跑边看」：
          · `run_session` 一次性返回 state ⇒ 轨迹**事后**才拿得到，而调用方
            只取最后一条 AIMessage ⇒ 轨迹被整段丢掉，前端只看到一个转圈
            （这正是第 210 轮老板的原始诉求）；
          · 这里改走 `stream_session` + `StreamDigest`：工具事件**逐条**转成
            step 事件下发，答复按原时序**攒齐一次吐出** ——
            即「只做加法、正文行为零变化」。

        Yields:
            step 事件（dict）/ 整段答复文本（str）；**没有产出就什么都没 yield**，
            由调用方按空结果回退关键词路由（与 `_route_via_tools` 返回 None 同义）。
        """
        router = self._get_router()
        if router is None:
            return

        # ★★★ 归属的**唯一写入点**：必须在这里（工具被调用之前）。
        #   与非流式路径**同源** —— 换成流式却漏掉这一句，工具就拿不到
        #   店铺归属（而漏掉不会报错，只会静默按「无店铺」取数）。
        _current_shop_id.set((context or {}).get("store_id"))

        prompt = query
        if context:
            try:
                ctx_json = json.dumps(context, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                ctx_json = str(list(context.keys()))
            prompt = f"{query}\n\n[上下文数据] {ctx_json[:2000]}"

        from langchain_core.messages import HumanMessage

        # ★ 工具人话标题走**注入**：真源在业务侧
        #   （`modules/skills/tools_catalog.py::tool_title`，全仓唯一查询口），
        #   而 `ai_infra` 不许依赖业务（分层硬红线）⇒ 只能把查询口传进去。
        #   惰性 import：Agent 的**模块导入期**无需把 `modules.skills` 拉进依赖图，
        #   只有真跑流式工具环路时才需要它。
        # 走**包门面**（本仓条款 1：跨模块引用不得伸手进包内部）。
        from modules.skills import tool_title

        digest = StreamDigest(title_resolver=tool_title)
        try:
            async for ev in router.stream_session(
                {"messages": [HumanMessage(content=prompt)]},
            ):
                s = digest.feed(ev)
                if s is not None:
                    yield s
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[customer_service] stream tool routing failed: {e}")
            return

        if digest.reply:
            yield digest.reply

    async def _route_via_tools(self, query: str,
                               context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """工具化路由：LLM 自主选工具执行，返回可读回复文本。

        返回 None 表示不可用或失败，调用方回退关键词路由（`_classify_intent`）。
        """
        router = self._get_router()
        if router is None:
            return None

        # ★★★ 归属的**唯一写入点**：必须在这里（工具被调用之前）。
        #   `context` 由 service 用请求头解析出的 store_id 填好，
        #   模型看不到也改不了它。
        _current_shop_id.set((context or {}).get("store_id"))

        prompt = query
        if context:
            try:
                ctx_json = json.dumps(context, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                ctx_json = str(list(context.keys()))
            prompt = f"{query}\n\n[上下文数据] {ctx_json[:2000]}"

        from langchain_core.messages import AIMessage, HumanMessage

        try:
            state = await router.run_session(
                {"messages": [HumanMessage(content=prompt)]},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[customer_service] tool routing failed: {e}")
            return None

        reply = ""
        for m in state.get("messages") or []:
            if isinstance(m, AIMessage) and m.content:
                reply = m.content if isinstance(m.content, str) else str(m.content)
        return reply.strip() or None

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

    async def stream_chat(self, query: str,
                          context: Optional[Dict[str, Any]] = None) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        ★ 第 204 轮新增 `context`：工具环路要从中取 `store_id` 注入归属
          （`create_ticket` 落库必须带租户维度）。归属只能由服务端注入。

        客服对话类意图走 LLM 流式；结构化意图（订单追踪/工单等）退化为一次性文本，
        但开跑前先发阶段进度，避免长任务期间「AI 正在思考…」空转。

        Yields:
            文本片段 / progress 事件（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        # ★ 第 204 轮：工具环路优先（LLM 用 bind_tools 自主选那 4 个客服工具）。
        #   不可用 / 失败 ⇒ 回退下面的关键词路由（确定性、离线可跑）。
        # ★ 第 210 轮：改走**流式版**工具环路 —— 思考过程（step）实时下发，
        #   答复文本仍按原来的时序**攒齐一次吐出**（正文行为零变化）。
        #   `tool_chunks` 为空 = 工具路没产出任何文本 ⇒ 与原来返回 None 一样
        #   落到下面的关键词回退链（降级链一行没动）。
        tool_chunks: list = []
        async for chunk in self._stream_via_tools(query, context):
            if isinstance(chunk, dict):
                yield chunk
            else:
                tool_chunks.append(chunk)
        if tool_chunks:
            yield progress("正在调用客服工具…")
            yield "".join(tool_chunks)
            return

        # ★ 点名技能、但技能通道（工具环路）没产出 ⇒ **如实说，不落下面的
        #   关键词短路**（第 246 轮）：那条短路不构造 system prompt，拿它的
        #   结果顶替用户点的技能，界面上完全看不出来（静默退化）。
        #   ★ 未点名时这一句不生效 ⇒ 下面整条降级链**一行没动**。
        if is_skill_requested():
            yield SKILL_CHANNEL_UNAVAILABLE
            return

        intent = self._classify_intent(query)

        # 结构化意图：走 invoke 一次性返回（含结构化卡片数据）
        # 注：CS 的 invoke 承载会话状态维护（add_user_turn/add_assistant_turn），
        # 必须保留，仅在其前补一条阶段进度。
        if intent in ("order_tracking", "ticket_create", "escalation"):
            yield progress(_INTENT_PROGRESS.get(intent, "正在处理你的请求…"))
            # ★ 必须把 context 传下去：它带着 `store_id`，而话术与订单
            #   都是租户隔离数据 —— 丢了它，invoke 里那次 ensure_faq
            #   只能以「缺店铺」收场。
            result = await self.invoke(query, context)
            yield result.content
            return

        # 对话类：走 LLM 流式（RAG 客服优先用 RAG 回答，此处简化走 LLM）
        if not (self.ENABLE_LLM and self.llm_client):
            result = await self.invoke(query, context)
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
            result = await self.invoke(query, context)
            yield result.content

    # ---- 意图分类 ----

    #: 意图路由表（**策略数据**留业务模块；控制流见 `ai_infra.intent.first_match`）。
    #: 顺序即优先级（`escalation` 最高），逐项保持收敛前的原序。
    #: ★ `" BBB"`（带前导空格）与收敛前**逐字一致**：它本来就命不中小写归一后的
    #:   查询，属既有现象，本轮原样保留 —— 收敛是搬逻辑，不是改策略。
    _INTENT_ROUTES = (
        Route("escalation", ("投诉", "举报", "律师", "诉讼", "消费者协会", "媒体",
                             "complaint", "sue", "lawsuit", "scam", "fraud", " BBB",
                             "经理", "主管", "领导", "manager", "supervisor")),
        # ★★ 第 286 轮：把 `return_refund` 提到 `order_tracking` **之前**。
        #
        #   原序里 `order_tracking` 在前，而它的关键词含「订单」「order」——
        #   买家说「我要退货，订单号是 AMZN123456789」时，**一定**先命中
        #   order_tracking ⇒ 退货分支永远走不到。实测（真库探针）：
        #     Q: 我要退货 订单 AMZN123456789
        #     改造前 → order_tracking（回一张订单表，答非所问）
        #
        #   ★ 根子上的一个原则：**订单号是参数，不是意图**。
        #     决定意图的是动词（退货 / 查询 / 投诉），订单号只是这次动作的
        #     入参。所以带明确动词的分支必须排在「只凭『订单』这个泛词」之前。
        #
        #   ⚠️ 同类问题还剩 `complaint`（「订单 AMZN123 质量有问题」仍会被
        #      order_tracking 截走）。本轮不一并改：那需要重排更多分支、
        #      影响面更大，先留作 P2（见 cs-data-source-audit-r286.md）。
        Route("return_refund", ("退货", "退款", "退换", "return", "refund", "不满意",
                                "不要了", "换一个", "exchange", "cancel order")),
        Route("order_tracking", ("订单", "order", "单号", "物流", "tracking", "快递",
                                 "发货", "delivery", "到哪里了", "查一下", "status")),
        Route("complaint", ("质量", "问题", "坏的", "破损", "缺陷", "defective",
                            "broken", "damaged", "wrong", "error", "mistake",
                            "欺骗", "虚假", "misleading")),
        Route("shipping_inquiry", ("运费", "包邮", "shipping", "多久到", "几天", "配送",
                                   "地址", "关税", "税", "customs", "duties")),
        Route("payment_issue", ("支付", "付款", "pay", "信用卡", "paypal", "charge",
                                "扣款", "账单", "invoice", "billing")),
    )

    def _classify_intent(self, query: str) -> str:
        """分类用户意图（兜底 `faq_query`；控制流见 `ai_infra.intent.first_match`）。

        Returns:
            faq_query / order_tracking / return_refund / complaint /
            shipping inquiry / payment_issue / general / escalation
        """
        return first_match(query, self._INTENT_ROUTES, "faq_query")

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

    # ---- 话术加载（真源：knowledge_faqs 表） ----

    async def ensure_faq(self, shop_id: Optional[str]) -> str:
        """把**当前店铺**的话术读进 `self.faq_database`。

        ★ 每次调用都读库，**不做进程内缓存**：运营在资料库里改了一条话术，
          下一次问答就该生效；一次查询只有几十行，成本可忽略。
          （`_faq_shop` 只用于诊断 —— 标明这批话术属于哪个店铺。）

        Returns:
            失败原因（"" = 成功）。**不抛**：「话术读不出来」不该让整段
            对话 500，它只是一部分能力不可用，由调用方决定怎么表达。
        """
        # 惰性 import：`faq_source` 带数据库依赖，而本模块在**导入期**就被
        #   bind_tools 装配 —— 模块级 import 会把 DB 依赖提前到启动路径。
        from .faq_source import load_faq_items

        try:
            items = await load_faq_items(shop_id)
        except Exception as e:  # noqa: BLE001
            self.faq_database = []
            self._faq_shop = None
            self._faq_error = str(e)
            self._faq_error_exc = e
            logger.warning(f"[customer_service] 话术库加载失败 shop={shop_id}: {e}")
            return self._faq_error

        self.faq_database = [FAQItem(**item) for item in items]
        self._faq_shop = shop_id
        self._faq_error = ""
        self._faq_error_exc = None
        return ""

    def _faq_unavailable_response(self, query: str, reason: str) -> AgentResponse:
        """话术库**读不出来**时的回复。

        ★ 与「没有这条话术」**严格分开**：前者是数据源没读到（要修数据源），
          后者是内容没配（去资料库补一条）。混成一句「没找到答案」，
          会让运营往错的地方使劲 —— 这正是以前内存 mock 掩盖掉的事。
        """
        reply = (
            "**话术库暂时读不出来** ⚠️\n\n"
            f"原因：{reason}\n\n"
            "这与「没有这条话术」不是一回事：前者是数据源没读到，"
            "后者可以在【资料库 → 业务话术库】里补一条。\n\n"
            "您可以换个说法再问我，或联系人工客服：support@example.com"
        )
        return AgentResponse(
            content=reply,
            data={"type": "faq_unavailable", "reason": reason, "query": query},
            display_type="text",
        )

    def _faq_empty_response(self, query: str) -> AgentResponse:
        """店铺**还没配话术**（表里 0 行）时的回复。"""
        reply = (
            "这个店铺**还没有配置话术** 📚\n\n"
            "我现在只能按通用规则回答，给不出针对您店铺的准确答复。\n\n"
            "请在【资料库 → 业务话术库】添加问答条目，添加后立刻生效。\n\n"
            f"（您问的是：{query}）"
        )
        return AgentResponse(
            content=reply,
            data={"type": "faq_empty", "query": query},
            display_type="text",
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

    # ---- 各意图处理器 ----

    async def _handle_faq_query(
        self,
        query: str,
        context: Optional[Dict],
        conv: ConversationContext,
        sentiment: SentimentAnalysis
    ) -> AgentResponse:
        """处理 FAQ 查询（支持 RAG + LLM 增强）"""

        # ★ 先把三种「没答上来」分清：**读不出来** / **没配** / **没命中**。
        if self._faq_error:
            return self._faq_unavailable_response(query, self._faq_error)
        if not self.faq_database:
            return self._faq_empty_response(query)

        # ====== 升级：优先使用 RAG + LLM ======
        if self.ENABLE_RAG and self.rag_engine:
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
        if self.llm_client:
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
        # ★ 原写法 `hasattr(rag_result, '_sources')` —— 该属性在 LLMCallResult 上
        # 从来不存在（字段名是 `sources`，无下划线前缀）。hasattr 恒 False ⇒
        # sources_info 恒 [] ⇒ 「参考了 N 条知识库文献」永不追加，RAG 引用来源
        # 静默丢失（不报错、不降级、测试全绿）。改为直接读真实字段：字段若改名会
        # 立刻 AttributeError，而不是悄悄退化成空列表。
        sources_info = list(rag_result.sources or [])

        reply = rag_result.content

        # 如果有引用来源，追加说明
        if sources_info and not rag_result.fallback:
            reply += "\n\n---\n*📚 参考了 {} 条知识库文献*".format(len(sources_info))

        # 根据情感调整语气后缀
        # ★ 原写法 `sentiment.level` —— SentimentAnalysis 没有该字段（字段是
        # `sentiment`，取值 positive/neutral/negative/angry）。此处必抛
        # AttributeError，被 _handle_faq_query 的 except 吞掉 ⇒ 每次客服 FAQ 都
        # 静默降级到关键词匹配，RAG 路径从未真正生效。同文件 1126 行用的就是
        # 正确的 `sentiment.sentiment`。
        if sentiment.sentiment == "negative":
            reply += "\n\n如果您的问题没有得到解决，可以点击下方「转人工」按钮。"
        elif sentiment.sentiment == "angry":
            reply += "\n\n非常抱歉给您带来不好的体验，我已将您的问题标记为紧急，会有专人尽快跟进。"

        return AgentResponse(
            content=reply,
            data={
                "type": "rag_answer",
                "query": query,
                "confidence": rag_result.confidence,
                "sources": sources_info,
                "fallback": rag_result.fallback,
                "source": "rag_hybrid",  # 标记为 RAG 来源
            },
            display_type="faq_answer"
        )

    #: 退货窗口天数。
    #:
    #: ★ 当前是**常量**，与话术里写的「收到商品 30 天内」保持一致。
    #:   将来它应当是**店铺可配置**的售后政策（不同类目 / 不同站点窗口不同），
    #:   那时这里要换成「读政策表」，而不是让话术文案与判断逻辑各说一套 ——
    #:   两套口径一旦漂移，买家就会得到「话术说能退、系统说不能退」的矛盾答复。
    RETURN_WINDOW_DAYS: int = 30

    @staticmethod
    def _render_shipping_block(info: Dict[str, Any]) -> str:
        """把订单字典里的物流字段渲染成一段文本。

        ★ **物流段只有这一份实现**：订单追踪（买家问订单）与物流咨询
          （买家问货到哪了）渲染的是同一批字段。若各写一份，改一个字段
          （比如新增「预计派送时间」）就会只改一处 —— 同一个订单两种说法。

        Returns:
            渲染文本；**没有任何物流信息时返回空串**（调用方据此另说一句）。
        """
        if not any(info.get(k) for k in (
                "tracking_number", "carrier", "ship_status_text",
                "last_location", "last_event_text")):
            return ""

        out = "\n**物流** 🚚\n"
        if info.get("carrier"):
            out += f"- 承运商：{info['carrier']}\n"
        if info.get("tracking_number"):
            out += f"- 运单号：`{info['tracking_number']}`\n"
        if info.get("ship_status_text"):
            out += f"- 物流状态：**{info['ship_status_text']}**\n"
        if info.get("last_location"):
            out += f"- 最新位置：{info['last_location']}\n"
        if info.get("last_event_text"):
            out += f"- 最新轨迹：{info['last_event_text']}\n"

        delay = info.get("delay_days")
        if isinstance(delay, int) and delay > 0:
            extra = (f"（实际在途 {info['transit_days']} 天）"
                     if info.get("transit_days") is not None else "")
            out += f"\n⚠️ 比承诺时效晚了 **{delay} 天**{extra}\n"
        return out

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
            # ★ fail-closed：查真源，拿不到就如实说拿不到。
            #   历史实现 `_mock_order_info()` 会随机生成状态 / 商品名 /
            #   金额 / 运单号并渲染成下面这张表 —— 等于把编造的订单
            #   直接告诉终端消费者。
            #
            # ★★ 第 285 轮：取数顺序改成「**自有订单库 → 平台适配层**」。
            #   自有库（`modules.trade` 的 `orders` / `shipments`）是**唯一真源**：
            #   平台适配层（SP-API Orders）不返回运单号与承运商，而演示剧本里
            #   那条差评的根因证据正是物流事件 —— 只有自有库给得出。
            #
            # ★ 店铺归属必须**显式传参**，不能靠 `_current_shop_id` 这个
            #   ContextVar：本方法在范式 B（`invoke()`）下被调用，而范式 B
            #   **从不设置**那个 ContextVar（只有 `stream_chat` 的 418/466 行设）。
            #   读它会拿到上一次范式 A 留下的值 ⇒ 跨调用串味，查到别家店铺的订单。
            shop_id = (context or {}).get("store_id") or None
            order_info, failure_reason = await self._fetch_order_info(order_id, shop_id)

            if order_info is None:
                reply = "**未能查到该订单** ⚠️\n\n"
                reply += f"订单号 `{order_id}` 查询失败。\n\n"
                reply += f"原因：{failure_reason}\n\n"
                reply += "请确认订单号是否正确（Amazon 订单号形如 `123-1234567-1234567`）。"
                return AgentResponse(
                    content=reply,
                    data={
                        "type": "order_not_found",
                        "order_id": order_id,
                        "reason": failure_reason,
                    },
                    display_type="text"
                )

            reply = f"**订单信息** 📦\n\n"
            reply += f"| 项目 | 详情 |\n|------|------|\n"
            reply += f"| 订单号 | `{order_info['order_id']}` |\n"
            reply += f"| 状态 | **{order_info['status_text']}** |\n"
            reply += f"| 下单时间 | {order_info['created_at']} |\n"
            reply += f"| 商品 | {order_info['product_name']} |\n"
            reply += f"| 金额 | {order_info['total_text']} |\n"

            if order_info.get("shipping_to"):
                reply += f"| 收货地 | {order_info['shipping_to']} |\n"

            # ---- 自有库才有的字段：运单号 / 承运商 / 迟到天数 ----
            # ★ 走 `_render_shipping_block`（与物流咨询**同一份实现**）。
            #   只有走 trade 域才会产出这几个键（SP-API Orders 接口不返回
            #   运单号与承运商），没有就整段不渲染 —— 不编、也不留空标题。
            reply += self._render_shipping_block(order_info)

            delay = order_info.get("delay_days")
            if isinstance(delay, int) and delay > 0:
                reply += "，如因此产生差评可在后续处理中作为证据。\n"

            if order_info.get("estimated_delivery"):
                reply += f"\n承诺送达：{order_info['estimated_delivery']}\n"

            # ★ 演示数据必须让消费者看得见 —— 与 trade 域 `is_mock_source` 同口径
            if order_info.get("is_mock_data"):
                reply += ("\n> ℹ️ 以上为**演示数据**（来源：mock_seed），"
                          "店铺接入平台接口后将自动切换为真实订单。\n")

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
        # ★ 只引导订单号：按邮箱 / 手机号检索需要卖家后台授权，尚未开放。
        #   历史文案列出了这两个选项，但那是配合「编造订单号」的假功能
        #   （service.track_order 曾用 hash(email) 造一个 ORD- 号去查）。
        reply = "我可以帮您查询订单状态！请提供**订单号**"
        reply += "（Amazon 订单号形如 `123-1234567-1234567`）。\n\n"
        reply += "如需按邮箱 / 手机号后四位检索，请转人工客服核验身份后查询。"

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
        """处理退换货请求 —— **先查订单，再判断在不在退货窗口内**。

        ★ 第 286 轮之前：这里把一条写死的退货指南原样吐出来，
          **完全不校验这笔订单** —— 于是「买了两年的东西」和「昨天刚签收」
          得到同一份答复，窗口 / 是否已签收一概不管。
          现在用 `delivered_at`（**签收日**，不是下单日）起算窗口，
          **算不出来就如实说算不出来**（不猜、不默认放行）。
        """
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")
        shop_id = (context or {}).get("store_id") or None

        verdict, verdict_data = await self._judge_return_window(order_id, shop_id)

        if self._faq_error:
            # ★ 话术读不出来时**照给判断**（判断来自订单数据，与话术无关），
            #   但要写明文档没读到 —— 不能让「流程细节缺失」看起来像「没有流程」。
            guide = (f"\n> ⚠️ 退货流程文档暂时读不出来（{self._faq_error}），"
                     "以下判断来自订单数据，不受影响。\n")
        elif self.faq_database:
            return_faqs = [f for f in self.faq_database if f.category == "退换货"]
            best = self._find_best_faq_match(query, return_faqs)
            guide = f"\n**退换货流程** 🔄\n\n{best.answer}\n" if best else ""
        else:
            guide = "\n（这个店铺还没配置退换货话术，流程细节请转人工确认。）\n"

        reply = f"**退换货判断** 🔄\n\n{verdict}\n" + guide

        if sentiment.sentiment in ("negative", "angry"):
            reply += "\n非常抱歉给您带来不好的体验 😔 我会尽快帮您处理。\n"

        reply += "\n---\n需要我帮您**创建退换货工单**吗？请告诉我：\n"
        reply += "- 订单号\n" if not order_id else ""
        reply += "- 退换原因（质量问题/不喜欢/发错货/其他）"

        data = {"type": "return_guide", "sentiment": sentiment.sentiment}
        data.update(verdict_data)
        return AgentResponse(content=reply, data=data,
                             display_type="return_guide")

    async def _judge_return_window(
        self, order_id: Optional[str], shop_id: Optional[str],
    ) -> "tuple[str, Dict[str, Any]]":
        """判断一笔订单在不在退货窗口内。

        Returns:
            (给买家看的结论, 结构化数据)

        ★ 三种**必须分开**的结局：还在窗口内 / 已超窗口 / **算不出来**。
          第三种最容易糊 —— 签收时间解析失败时若默认「可以退」，
          就是把「不知道」包装成「批准」（fail-open，本仓禁止）。
        """
        if not order_id:
            return (
                "请先提供**订单号**：我需要看这笔订单的签收时间，"
                f"才能判断它是否还在 {self.RETURN_WINDOW_DAYS} 天退货窗口内"
                "（不同订单的签收时间不同，不能笼统答复）。",
                {"need_order_id": True},
            )

        info, why = await self._fetch_order_info(order_id, shop_id)
        if info is None:
            return (
                f"订单 `{order_id}` 没查到，无法判断退货窗口。\n\n"
                f"原因：{why}",
                {"order_id": order_id, "reason": why,
                 "order_found": False},
            )

        delivered = info.get("delivered_at") or ""
        if not delivered:
            # ★ 没签收 ⇒ 还没进入退货窗口；该走的是「未收到货 / 物流异常」
            return (
                f"这笔订单**尚未签收**（当前状态：{info.get('status_text') or '—'}），"
                "退货窗口从签收日起算，因此现在还谈不上超期。\n\n"
                "如果您是「**没收到货**」，请告诉我，我按未收到货的流程处理。",
                {"order_id": order_id, "order_found": True,
                 "delivered": False},
            )

        from modules.trade import parse_iso  # 跨包走门面，不深引用 service

        dt = parse_iso(delivered)
        if dt is None:
            return (
                f"签收时间 `{delivered}` 解析不出来，我**不据此判断**是否可以退 —— "
                "请转人工核对（宁可多问一句，也不拿猜测当结论）。",
                {"order_id": order_id, "order_found": True,
                 "delivered": True, "window_unknown": True},
            )

        # ★ 平台同步来的时间戳可能带时区（`...Z` / `+08:00`），自有库的是 naive。
        #   一个 aware、一个 naive 直接相减会 TypeError ⇒ 整个分支崩掉。
        #   统一按 **UTC 挂钟**比较（库里存的就是 UTC 串）。
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

        days = (datetime.utcnow() - dt).days
        left = self.RETURN_WINDOW_DAYS - days
        if days > self.RETURN_WINDOW_DAYS:
            text = (
                f"这笔订单已签收 **{days} 天**，超出 {self.RETURN_WINDOW_DAYS} 天"
                f"退货窗口 **{days - self.RETURN_WINDOW_DAYS} 天** ⇒ "
                "标准退货流程可能不适用，需要人工审核。\n\n"
                "⚠️ 质量问题 / 运输破损通常**不受**这个窗口限制，"
                "如果是这两种情况请说明。"
            )
        else:
            text = (
                f"这笔订单已签收 **{days} 天**，"
                f"**仍在 {self.RETURN_WINDOW_DAYS} 天退货窗口内**"
                f"（还剩 {left} 天）⇒ 可以走标准退货流程。"
            )
        return (text, {"order_id": order_id, "order_found": True,
                       "delivered": True, "days_since_delivery": days,
                       "days_left": left,
                       "within_window": days <= self.RETURN_WINDOW_DAYS})

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
        """处理物流询问 —— **有订单号就查真实物流**。

        ★ 第 286 轮之前：这里只从话术库里挑一条「物流」分类的静态文案，
          于是买家问「我的货到哪了」，系统回「登录账户 → 我的订单 →
          查看物流」—— 让他自己去别处看，而 `shipments` 表里那几行连
          运单号、轨迹、迟到天数都存好了（审查见 cs-data-source-audit-r285）。

        ★ 现在的顺序：**订单号 ⇒ 查自有订单库（`_fetch_order_info`）**；
          查不到 / 没给订单号 ⇒ 才回话术，并**明确告诉他给订单号能查到什么**。
        """
        order_id = self._extract_order_id(query) or (context or {}).get("order_id")
        shop_id = (context or {}).get("store_id") or None

        if order_id:
            info, why = await self._fetch_order_info(order_id, shop_id)
            if info is None:
                reply = (
                    f"**没能查到订单 {order_id} 的物流** ⚠️\n\n"
                    f"原因：{why}\n\n"
                    "请确认订单号是否正确（Amazon 订单号形如 "
                    "`123-1234567-1234567`）。"
                )
                return AgentResponse(
                    content=reply,
                    data={"type": "shipping_order_not_found",
                          "order_id": order_id, "reason": why},
                    display_type="text",
                )

            block = self._render_shipping_block(info)
            if not block:
                # ★ 查到了订单但还没有运单信息 ⇒ 如实说「系统里没有」，
                #   不用「请登录账户自行查看」这类话把缺口糊过去。
                block = (
                    "\n**物流** 🚚\n"
                    "- 目前物流系统里**还没有这笔订单的运单信息**\n"
                    f"- 订单状态：{info.get('status_text') or '—'}\n"
                )
            reply = f"**订单 {info['order_id']} 的物流进度** 🚚\n" + block
            if info.get("estimated_delivery"):
                reply += f"\n承诺送达：{info['estimated_delivery']}\n"
            if info.get("is_mock_data"):
                reply += ("\n> ℹ️ 以上为**演示数据**，店铺接入平台接口后"
                          "自动切换为真实物流。\n")
            return AgentResponse(
                content=reply,
                data={"type": "shipping_tracking", "order": info},
                display_type="order_info",
            )

        # ---- 没给订单号：回话术 + 明说「给订单号能查到什么」 ----
        if self._faq_error:
            return self._faq_unavailable_response(query, self._faq_error)
        if not self.faq_database:
            return self._faq_empty_response(query)

        shipping_faqs = [f for f in self.faq_database if f.category == "物流"]
        reply = ""
        best = self._find_best_faq_match(query, shipping_faqs)
        if best is not None:
            reply += f"**关于物流问题** 📦\n\n{best.answer}\n\n"
            others = [f for f in shipping_faqs if f.id != best.id][:2]
            if others:
                reply += "**其他物流常见问题**：\n"
                for f in others:
                    reply += f"- Q: {f.question}\n"
                reply += "\n"
            return AgentResponse(
                content=reply +
                    "---\n给我**订单号**，我可以帮您查这笔订单的实时轨迹"
                    "（承运商 / 运单号 / 最新位置 / 是否迟到）。",
                data={"type": "shipping_info", "faq_id": best.id,
                      "need_order_id": True},
                display_type="faq_answer",
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

    # ---- FAQ 搜索引擎 ----

    def _search_faq(self, query: str, threshold: float = 0.3) -> FAQMatchResult:
        """
        在 FAQ 数据库中搜索匹配项

        使用关键词匹配 + 类别权重算法
        （生产环境替换为向量相似度检索）
        """
        query_lower = query.lower()
        # ★ 中文没有空格：`\w+` 会把「我要退货」当成**一个词**，于是「标题精确
        #   匹配」对中文几乎永不生效（整串自然不在标题里）。保留它只为英文；
        #   中文的主信号是下面的**关键词命中**（那正是 `knowledge_faqs.keywords`
        #   这一列存在的意义 —— 运营为每条话术标了「买家会怎么问」）。
        query_terms = re.findall(r'\w+', query_lower)

        scored_matches = []

        for faq in self.faq_database:
            score = 0.0

            # 1. 标题精确匹配（权重最高；英文有效、中文基本无效，见上）
            if any(term in faq.question.lower() for term in query_terms):
                score += 0.5
                # 完全包含得分更高
                if query_lower in faq.question.lower():
                    score += 0.3

            # 2. 关键词匹配 —— **中文场景的主信号**
            #    ★ 改造前每个关键词只加 0.1，而阈值是 0.3 ⇒ 买家说「我要退货」
            #      命中 1 个关键词也只拿 0.1×权重，永远够不到阈值，界面上就是
            #      「没找到答案」。把单个关键词提到 0.3（命中即过线），
            #      多个叠加最高 0.9。
            keyword_matches = sum(
                1 for kw in faq.keywords if kw and kw.lower() in query_lower
            )
            score += min(0.9, keyword_matches * 0.3)

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

    def _find_best_faq_match(self, query: str,
                             faq_list: List[FAQItem]) -> Optional[FAQItem]:
        """从指定列表中找最佳匹配（列表为空 ⇒ None，不抛 IndexError）"""
        result = self._search_faq(query, threshold=0.1)
        # 过滤只在列表中的
        for m in result.matches:
            if m in faq_list:
                return m
        return faq_list[0] if faq_list else None

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

    def _extract_order_id(self, text: str) -> Optional[str]:
        """从文本提取订单号。

        ★ 第 286 轮补了第 2 条：库里 seed 的订单号就是 `AMZN123456789` 这种
          「平台前缀 + 数字」形态，而此前的规则只认 Amazon 的真实格式
          （`123-1234567-1234567`）和 `ORD-` 开头 —— 于是在演示环境里，
          买家把订单号**原样贴进来也提取不出来**，物流/退货两条分支
          就都掉回「请提供订单号」那句。缺陷不会报错，只会让人以为没接数据。
        """
        patterns = [
            r'\d{3}-\d{7}-\d{7}',   # Amazon 真实订单号，如 112-1234567-8901234
            r'AMZN[-_]?\d{6,}',     # 演示库 / 内部单号（seed 落的就是这一类）
            r'ORD[-–]?\d{8,}',      # 本项目历史演示格式（保留兼容）
            r'order[- ]?(\d{8,})',
            r'[A-Za-z]{2,6}[-_]?\d{6,}',  # 其它平台前缀单号（如 SP / SHOPEE 前缀）
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

    async def _fetch_order_info(
        self, order_id: str, shop_id: Optional[str] = None
    ) -> "tuple[Optional[Dict[str, Any]], str]":
        """
        查询订单信息（真实数据源，fail-closed）。

        ★ 历史实现 `_mock_order_info()` 用 random 生成状态 / 商品名 / 金额 /
          运单号，把假数据直接回复给终端消费者 —— 本项目最恶劣的一处伪数据，
          已整体删除，不再留任何 mock 回退。

        ============================================================
        ★★ 取数顺序（第 285 轮定）：自有订单库 → 平台适配层
        ============================================================
        ① **自有订单库**（`modules.trade` 的 `orders` / `shipments`）—— 唯一真源。
           数据由「订单落库同步任务」从平台适配层拉回来后**按我们自己的数据模型**
           落库，字段是平台无关的：运单号 / 承运商 / 物流事件轨迹 / 迟到天数
           都在这里。演示阶段由 `seed` 灌入 mock 数据（带 `source=mock_seed`
           标记，界面必须如实标注）。

        ② **平台适配层**（SP-API Orders）—— 只在①查不到时兜底。
           定位是「**上游取数**」：它给的是平台原生字段，信息量**少于**自有库
           （Orders 接口不返回运单号与承运商，那是 Shipping API 的活）。

        ★ 为什么①查不到还要回退②，而不是像 `modules/trade/tools.py` 头部注释
          写的那样「表是唯一真源、查不到就如实说查不到」：
            那条纪律管的是**同一个工具内部**不许出现两种答案。而这里是**同步
            任务尚未跑过**（或该订单还没落库）的情形 —— 平台上有、我们库里暂时
            没有。此时回退适配层是「补拉」，不是「给第二个答案」：
            两条路径的产出都带 `data_source`，上层看得到差别。

        ★ 不落库：本方法是**查询**路径（`fetch_order_tracking` 标记为 READ_ONLY），
          在查询里写库会让「读」产生副作用。把平台数据变成自有数据的正确落点是
          `modules/trade.sync.sync_orders_from_source`（订单同步任务）。

        约定：
          - 两个源都拿不到 ⇒ 返回 (None, 原因)，**绝不编造**
          - 查得到 ⇒ 返回 (订单字典, "")，字段沿用历史上消费者依赖的键名

        Args:
            order_id: 平台订单号或内部订单 id
            shop_id: 当前店铺。**显式传参**，不读 `_current_shop_id`
                     （范式 B 从不设置它，读了会串味到别的店铺）

        Returns:
            (order_info | None, 失败原因)
        """
        # ---- ① 自有订单库（真源） ----
        if shop_id:
            try:
                own = await self._fetch_order_from_trade(shop_id, order_id)
            except Exception as e:
                # ★ 自有库查询失败**不能**被当成「没有这笔订单」而静默回退：
                #   那会把「数据库连不上」伪装成「平台没有这笔订单」，归因反向。
                #   这里如实记录，并继续走②（②失败时会带上①的原因一起报）。
                logger.warning(f"自有订单库查询异常 order={order_id} shop={shop_id}: {e}")
                own = None
                own_error = f"自有订单库查询失败：{e}"
            else:
                own_error = ""
            if own is not None:
                return own, ""
            # ★ 库里**查无此单**也要记一笔（它不是异常，但是一条独立的失败线索）：
            #   最终若两个源都没查到，只报平台那条会让「还没同步进库」与
            #   「库里根本没有」混成同一句话 —— 归因会指向错的地方。
            if not own_error:
                own_error = "自有订单库中查无此订单"
        else:
            own_error = "未携带店铺上下文，跳过自有订单库"

        # ---- ② 平台适配层（兜底） ----
        try:
            # 走数据源工厂（唯一入口）——门禁 test_import_boundaries §1 强制
            from modules.amazon_sp import get_data_source
        except Exception as e:  # pragma: no cover
            return None, f"订单数据源模块不可用：{e}"

        def _query() -> Dict[str, Any]:
            # prefer="sp_api"：凭据缺失时工厂**抛 RuntimeError**，不静默回退 Mock
            source = get_data_source(prefer="sp_api")
            return source.fetch_order_tracking(order_id)

        try:
            raw = await asyncio.to_thread(_query)
        except RuntimeError as e:
            # ★ 插值口径：本文件用的是 `core.logger.get_logger()`（loguru），
            #   它按 `str.format` 插值 —— 写 `%s` 会把参数**静默丢掉**
            #   并原样打出 "%s"。loguru 用 f-string / `{}`，
            #   标准库 `logging.getLogger` 才用 `%s`。
            logger.warning(f"订单查询不可用（未接入 SP-API，不编造订单内容）order={order_id}: {e}")
            # ★ 两个源都失败时**两个原因都要说**：只报平台那条，会把
            #   「库里有但连不上」和「压根没同步过」混成同一句。
            detail = f"当前店铺未接入 SP-API 订单数据源（{e}）"
            return None, (f"{own_error}；且{detail}" if own_error else detail)
        except Exception as e:
            logger.warning(f"订单查询失败 order={order_id}: {e}")
            detail = f"平台订单接口调用失败：{e}"
            return None, (f"{own_error}；且{detail}" if own_error else detail)

        if not raw or not raw.get("found"):
            why = (raw or {}).get("error") or "平台侧查不到这笔订单"
            return None, (f"{own_error}；且{why}" if own_error else why)

        # ★ 走适配层拿到的数据，`data_source` 必须标成平台来源 —— 上层靠它
        #   区分「我们自己的库」与「平台实时拉回来的」，不标就等于两种答案
        #   长得一样，正是 `modules/trade/tools.py` 头部警告的那件事。
        info = self._map_order_info(order_id, raw)
        info["data_source"] = "platform_api"
        info["is_mock_data"] = False
        return info, ""

    async def _fetch_order_from_trade(
        self, shop_id: str, order_id: str
    ) -> Optional[Dict[str, Any]]:
        """在**自有订单库**里查一笔订单（取数顺序①）。

        ★ 走 `modules.trade` 包门面，不深引用 `modules.trade.service` / `db_model`
          —— 本仓铁律：跨包引用走 `__init__`，否则模型搬家变成全仓搜索。

        Returns:
            订单字典 | None（None = **库里没有**，调用方可继续走适配层）
        """
        from core.database import async_session_factory

        # 函数内 import：`modules.trade` 依赖 `core.database`，而本模块被
        # `bind_tools` 在**导入期**就装配，模块级 import 会把数据库依赖
        # 提前到进程启动路径上（与 `modules/trade/tools.py` 同款处理）。
        # ★ 走**门面**取函数，不取子模块：`modules.trade` 是跨模块契约面
        #   （`tests/test_facade_monkeypatch_targets.py` 钉的就是这件事）。
        #   取子模块时，测试把桩打在门面上 ⇒ 桩永远不生效 ⇒ 真函数照跑
        #   ⇒ 轻则断言红、重则「测试因错误的原因通过」。
        from modules.trade import get_order_context

        async with async_session_factory() as session:
            ctx = await get_order_context(session, shop_id, order_id)

        if not ctx.get("found"):
            return None
        return self._map_order_from_trade(order_id, ctx)

    @staticmethod
    def _map_order_from_trade(order_id: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """把自有订单库的上下文映射成客服回复所用的字段名。

        ★ 与 `_map_order_info`（平台适配层版）**共用同一套对外键名** —— 上层
          渲染逻辑写一次即可，换取数源不需要改渲染。差异只在「多出来的键」：
          自有库有运单号 / 承运商 / 迟到天数 / 演示数据标记，平台版没有。

        ★ 只做改名与搬运，不补任何没拿到的字段：缺就是缺，如实留空。
        """
        order = ctx.get("order") or {}
        items = ctx.get("items") or []
        ship = ctx.get("shipment") or {}

        if len(items) > 1:
            first = items[0].get("title") or items[0].get("sku") or "\u2014"
            product_name = f"{first} 等 {len(items)} 件商品"
        elif items:
            product_name = items[0].get("title") or items[0].get("sku") or "\u2014"
        else:
            product_name = "\u2014"

        amount = order.get("order_total")
        currency = order.get("currency") or "USD"
        if amount is None:
            total_text = "\u2014"
        elif currency == "USD":
            total_text = f"${amount:.2f}"
        else:
            total_text = f"{amount:.2f} {currency}"

        status_code = order.get("order_status") or ""
        ship_code = ship.get("ship_status") or ""
        source = order.get("source") or ""

        # ★ 中文标签只在这里查表：见 `_ORDER_STATUS_LABELS` 的注释
        where = " / ".join(
            x for x in (order.get("ship_state"), order.get("ship_country")) if x
        )

        return {
            "order_id": order.get("external_order_id") or order_id,
            "status": status_code,
            "status_text": _ORDER_STATUS_LABELS.get(status_code, status_code or "\u2014"),
            "created_at": order.get("purchase_at") or "\u2014",
            "product_name": product_name,
            "quantity": sum(int(i.get("quantity") or 0) for i in items),
            "total": amount,
            "total_text": total_text,
            "estimated_delivery": order.get("promised_at") or "",
            "shipping_to": where,
            # ↓ 退货窗口要按**签收日**起算（不是下单日），见 `_handle_return_refund`
            "shipped_at": order.get("shipped_at") or "",
            "delivered_at": order.get("delivered_at") or "",
            # ↓ 以下为自有库专属（平台适配层给不出）
            "tracking_number": ship.get("tracking_no") or "",
            "carrier": ship.get("carrier") or "",
            "ship_status_text": _ORDER_STATUS_LABELS.get(ship_code, ship_code or "\u2014")
            if ship_code else "",
            "transit_days": order.get("transit_days"),
            "delay_days": order.get("delay_days"),
            "last_location": ship.get("last_location") or "",
            "last_event_text": ship.get("last_event_text") or "",
            # ↓ 谁给的这批数据，上层必须看得见（演示数据不得冒充真实数据）
            "data_source": source,
            "is_mock_data": source == "mock_seed",
        }

    @staticmethod
    def _map_order_info(order_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        把 SP-API 的订单追踪结果映射成客服回复所用的字段名。

        ★ 只做「改名 / 取首项」这类搬运，**不补任何平台没给的字段**：
          运单号与承运商 Orders 接口不返回，因此这里也不产出
          `tracking_number` / `carrier` 两个键（历史 mock 会编）。
        """
        items = raw.get("items") or []
        total = raw.get("order_total") or {}
        amount = total.get("amount")
        currency = total.get("currency") or "USD"

        if len(items) > 1:
            first = items[0].get("title") or items[0].get("asin") or "—"
            product_name = f"{first} 等 {len(items)} 件商品"
        elif items:
            product_name = items[0].get("title") or items[0].get("asin") or "—"
        else:
            product_name = "—"

        if amount is None:
            total_text = "—"
        elif currency == "USD":
            total_text = f"${amount:.2f}"
        else:
            total_text = f"{amount:.2f} {currency}"

        current = raw.get("current_status") or {}
        info: Dict[str, Any] = {
            "order_id": order_id,
            "status": current.get("code", ""),
            "status_text": current.get("label", ""),
            "created_at": raw.get("purchase_date") or "—",
            "product_name": product_name,
            "quantity": raw.get("item_count") or 0,
            "total": amount,
            "total_text": total_text,
        }
        if raw.get("estimated_delivery"):
            info["estimated_delivery"] = raw["estimated_delivery"]
        if raw.get("shipping_to") and raw["shipping_to"] != "N/A":
            info["shipping_to"] = raw["shipping_to"]
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

    async def search_knowledge_base(
        self, query: str, limit: int = 5, shop_id: Optional[str] = None
    ) -> List[Dict]:
        """公开接口：搜索知识库 —— **真源是 `knowledge_faqs` 表**。

        ★ 第 286 轮之前，这个函数搜的是**内存里 12 条硬编码 FAQ**：
          名叫「知识库」，却与库里那 24 条真话术毫无关系（命名欺骗）。
          现在走 `ensure_faq` ⇒ `faq_source.load_faq_items`。

        Raises:
            PermissionError: 缺店铺上下文（话术是租户隔离数据）⇒ 端点转 400。
            RuntimeError:    数据库不可用 ⇒ 端点转 503。
                ★ 两种都**不返回空列表**：那会把「读不出来」伪装成「没有相关话术」。
        """
        err = await self.ensure_faq(shop_id)
        if err:
            # ★ 保类型抛出：让调用方能按类型分码，而不是靠字符串猜
            if isinstance(self._faq_error_exc, PermissionError):
                raise self._faq_error_exc
            raise RuntimeError(err)
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
            # ★ 语义变了：这是「**当前已加载**的话术条数」，不是「全库条数」。
            #   单例 Agent 在没有店铺上下文时是 0（话术是租户隔离数据）。
            "faq_count": len(self.faq_database),
            "categories": list(set(f.category for f in self.faq_database))
        }

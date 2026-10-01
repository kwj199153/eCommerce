"""核心：构造、工具化路由子层、invoke/stream_chat 主入口、意图分类、情感分析。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

import json
from typing import List, Dict, Any, Optional, AsyncIterable
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
from ai_infra.sse import StreamDigest, progress
from ._base import (
    AgentResponse,
    ConversationContext,
    FAQItem,
    SentimentAnalysis,
    _INTENT_PROGRESS,
    _current_shop_id,
    logger,
)

class MixinCore:
    """核心：构造、工具化路由子层、invoke/stream_chat 主入口、意图分类、情感分析。"""

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
            from ..tools import customer_service_tools

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

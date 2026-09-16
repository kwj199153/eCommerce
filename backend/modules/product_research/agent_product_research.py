"""
选品分析 Agent (Product Research Agent)

继承 BaseAgent 基类，实现跨境电商选品分析的核心能力。

功能模块：
1. 蓝海品类挖掘 - 发现高潜力低竞争的细分市场
2. 痛点机会识别 - 分析竞品评论提取用户痛点
3. SKU 利润计算 - FBA费用/定价策略/ROI分析
4. 竞品深度对比 - 多维度对比竞品优劣势
5. 季节性趋势 - 市场热度时间轴
6. 避坑指南 - 侵权风险/合规检查

设计来源：
- 推理循环：继承 ai_infra.base_agent.BaseAgent
- 工具调用：使用 platforms.amazon.AmazonAdapter 获取数据
- HITL 机制：关键操作（如导出报告）需人工审批

升级特性（Phase 8）：
- ✅ DashScope Qwen LLM 智能增强分析
- ✅ 自动降级到模拟响应
"""

import json
from typing import List, Dict, Any, Optional, AsyncIterable
from contextvars import ContextVar
from datetime import datetime

from pydantic import BaseModel, Field

from platforms import get_platform_adapter, PlatformType
from platforms.base import (
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
    CompetitorAnalysis,
)
from ai_infra.sse import progress

from core.logger import get_logger

# ★ 本文件此前有 9 处 `logger.warning(...)`，但**从未定义 logger** ——
#   而它们全在 except 分支里，意味着「LLM/工具调用失败时本该降级」的路径
#   会自己抛 `NameError: name 'logger' is not defined`，把可恢复错误变成 500。
#   接上统一日志出口后，这些降级日志也会带上 request_id 落进日志文件。
logger = get_logger("product_research.agent")

# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.product_research import prompts as _prompts  # noqa: F401


# 深层分层路由：子 Agent 的工具化路由层（bind_tools + LangGraph 图）。
# 深层分层路由：工具化路由层（bind_tools + LangGraph 图），以**组合**方式引入。
# 本类继承 BaseAgent 只为拿 LLM 原语；router 是本类内部一个独立的 BaseAgent 实例，
# 让「分析逻辑」与「工具编排」各归其位（而非让本类自己成为一张图）。
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型：table/chart/text/report


class BlueOceanOpportunity(BaseModel):
    """蓝海机会"""
    category: str = Field(..., description="品类名称")
    search_volume: int = Field(..., description="月搜索量")
    competition: float = Field(..., description="竞争指数（0-1）")
    trend: str = Field(default="", description="趋势方向")
    opportunity_score: float = Field(..., description="机会评分（0-100）")
    reason: str = Field(default="", description="推荐理由")
    suggested_price_range: str = Field(default="", description="建议售价区间")
    estimated_margin: str = Field(default="", description="预估利润率")


class ProfitAnalysis(BaseModel):
    """利润分析结果"""
    product_name: str
    cost_price: float  # 采购成本
    selling_price: float  # 售价
    fees: FeeStructure
    total_cost: float
    net_profit: float
    roi_percentage: float
    break_even_quantity: int  # 盈亏平衡销量


class PainPointAnalysis(BaseModel):
    """痛点分析结果"""
    product_asin: str
    total_reviews_analyzed: int
    negative_review_count: int
    pain_points: List[Dict[str, Any]]  # [{pain_point, count, percentage}]
    improvement_suggestions: List[str]
    market_gap_score: float  # 市场空白度评分


class ResearchReport(BaseModel):
    """选品研究报告"""
    report_id: str
    created_at: str
    query: str
    platform: str
    summary: str
    opportunities: List[BlueOceanOpportunity] = []
    profit_analysis: Optional[ProfitAnalysis] = None
    pain_point_analysis: Optional[PainPointAnalysis] = None
    competitor_analysis: List[CompetitorAnalysis] = []
    recommendations: List[str] = []
    confidence_level: str  # high / medium / low


# ====== System Prompt ======

PRODUCT_RESEARCH_SYSTEM_PROMPT = """
你是一位专业的**跨境电商选品分析师**，拥有 8 年 Amazon 运营经验，擅长：

## 核心能力

### 1️⃣ 蓝海品类挖掘
- 通过关键词数据分析发现高搜索量、低竞争的细分市场
- 识别新兴趋势和季节性机会
- 评估市场容量和进入门槛

### 2️⃣ 竞品深度分析
- 拆解竞品的 Listing 质量、价格策略、用户反馈
- 提取差评中的共性痛点和未满足需求
- 发现差异化切入点和市场空白

### 3️⃣ 利润与风险评估
- 精确计算 FBA 费用、广告成本、净利润
- 评估供应链风险和资金周转周期
- 判断侵权风险和合规要求

## 工作原则

1. **数据驱动**：所有结论必须有数据支撑，不凭感觉
2. **结构化输出**：用表格、列表、评分等方式清晰呈现
3. **可执行建议**：给出具体的行动项，而非空泛的建议
4. **风险提示**：主动指出潜在风险和避坑要点
5. **诚实客观**：不确定的信息标注 confidence: low

## 输出格式

根据用户问题类型，选择合适的输出格式：
- **蓝海分析**：表格 + 机会评分 + 推荐理由
- **利润计算**：明细表 + ROI + 盈亏平衡点
- **痛点分析**：痛点云图 + 改进方向 + 市场空白
- **竞品对比**：雷达图数据 + 优劣势列表
- **综合报告**：完整的研究报告结构

## 当前平台

当前聚焦 **Amazon 美国站**，使用美元计价。
"""


# 结构化意图 → 阶段进度文案（stream_chat 在耗时分析前发给前端，避免空转）
_INTENT_PROGRESS = {
    "blue_ocean": "正在挖掘蓝海品类数据…",
    "profit": "正在测算利润空间…",
    "pain_points": "正在分析用户痛点…",
    "competitor": "正在对比竞品数据…",
    "save_candidate": "正在写入选品库…",
}

# 当前会话 ID（ContextVar）。
#
# 用途：走 LLM 工具路由时，工具函数（tools.py）需要知道「这是哪个会话」——
# 工具的入参由 LLM 生成，塞不进 context_id，只能靠上下文传递。
# 不传的后果：工具里的 `_save_candidate` 落在 `_default` 会话，既看不到该会话的
# 蓝海结果（「把第 1 个入库」解析不出目标），也接不上待补槽位（多轮补齐断链）。
_current_context_id: ContextVar[Optional[str]] = ContextVar(
    "product_research_context_id", default=None
)

# 当前店铺 ID（ContextVar）。
#
# 用途：与 `_current_context_id` 同因 —— 走 LLM 工具路由时，工具函数的入参由
# LLM 生成，**塞不进 shop_id**，只能靠上下文传递。
#
# ★★★ 与旧写法的关键区别（P0 安全修复 2026-09-16）
#   修复前：写库路径直读 `core.tenant.middleware.tenant_context.shop_id`
#           （★ C4 2026-09-16：该符号已随账户侧收拢删除，此处仅为事故记录），
#           而那个值由 `TenantMiddleware` 用**未校验的原始 `X-Shop-ID` 头**
#           对每个请求写入 ⇒ 任何带有效 token 的用户改一下请求头，就能把候选
#           写进别人的选品库（探针 r84d 实测：落库 shop_id = 受害店铺，200）。
#   现在：本 ContextVar **只**由 `invoke` / `stream_chat` 写入，值来自 service
#           层显式传入的、**已过归属校验**的 shop_id（`get_current_shop_id*`）。
#           ⇒ 中间件不再碰业务上下文，注入通道被物理切断。
#
# ★ 并且 `_write_candidates` 在 shop_id 缺失时**硬拒绝写入**（不是写空分区），
#   所以"拿不到已校验的店铺"= 不落数据，而不是落到别人的分区。
_current_shop_id: ContextVar[Optional[str]] = ContextVar(
    "product_research_shop_id", default=None
)

# 全类目高潜关键词——老板没指定类目时用它，替代原先的 "general" 泛化词表。
#
# 为什么不用泛化词（smart home / organizer / portable…）：这些词在关键词库里
# **命中不到**，会走 `AmazonAdapter.get_keyword_data` 的「未匹配 → 随机估算」
# 分支（search_volume 随机 5k~80k、competition 随机 0.2~0.85、trend 随机），
# 于是机会分数完全随机、「发现 6 个蓝海机会」这个结论不可信。
#
# 下面这批词取自 `platforms/amazon/client.py` 的 MOCK_KEYWORDS（有真实量级的
# 搜索量/竞争度/趋势），跨 kitchen / pet / office / garden / sports 五个类目。
_TRENDING_KEYWORDS = [
    "coffee grinder", "portable coffee maker", "pet feeder automatic",
    "desk organizer mesh", "led grow lights indoor", "yoga mat non slip",
    "cat food dispenser", "exercise mat alignment lines",
]

# ASIN 正则：真实 ASIN 是 `B0` + 8 位字母数字（如 B0C1234567、B01N4ABCD1），
# 共 10 位。**不是 `[Bb]\d{9}`**——那个要求 B 后 9 位纯数字，会把
# `B0C1234567`（第 3 位是字母 C）全部漏掉，导致「对比 B0C… B0C…」
# 被判成「未提供 ASIN」。
_ASIN_RE = r"[Bb]0[0-9A-Za-z]{8}"


# ====== 选品 Agent 实现 ======

class ProductResearchAgent(BaseAgent):
    """
    选品分析 Agent

    Phase 2: 独立实现核心功能（不依赖 BaseAgent 的 LLM 调用）
    Phase 3: 集成 BaseAgent 实现完整的 LangGraph 推理循环
    Phase 8: 接入 DashScope Qwen LLM 实现智能增强

    使用示例：
        agent = ProductResearchAgent()

        # 蓝海挖掘
        result = await agent.invoke("帮我找厨房用品类的蓝海机会")

        # 利润计算
        result = await agent.invoke("分析便携式咖啡研磨器的利润空间")
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-max"       # 分析任务用最强模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    def __init__(self, platform: str = "amazon"):
        """
        初始化选品 Agent

        Args:
            platform: 目标平台（默认 amazon）
        """
        # 初始化 LLM 基类
        super().__init__()

        self.platform = platform
        self.adapter = get_platform_adapter(platform)
        self.agent_name = "ProductResearcher"
        self.system_prompt = PRODUCT_RESEARCH_SYSTEM_PROMPT

        # 深层分层路由：工具化路由层（懒加载，避免 tools→service→agent 循环导入）
        self._router = None

        # 会话级状态（key = context_id），见下方 `_session()`：
        #   last_blue_ocean —— 最近一次蓝海结果，供「第 1 个」「这个品」这类指代解析
        #   pending_save    —— 入库槽位填充进行中（必填项没补齐）时，记录待补内容
        #
        # ⚠️ 必须按会话隔离。service 层持有的是**全局单例** Agent，早先把状态直接
        # 挂在实例上（`self._last_blue_ocean`）→ A 会话挖完蓝海，B 会话说
        # 「把第 1 个加进选品库」会存进 A 的商品，**跨会话串数据**。
        self._session_state: dict = {}

    # ====== 会话级状态 ======

    def _session(self, context_id: Optional[str] = None) -> dict:
        """
        取（必要时创建）该会话的状态容器。

        没有 context_id 时退化为 `_default` —— 单会话场景（含既有测试）仍可用；
        多会话并发下**必须由调用方传 context_id**，否则还是会串。
        """
        return self._session_state.setdefault(context_id or "_default", {})

    def _last_products(self, context_id: Optional[str] = None) -> List[dict]:
        """该会话上一轮蓝海产出的候选商品（没有则空列表）。"""
        cached = self._session(context_id).get("last_blue_ocean") or {}
        return cached.get("products") or []

    @property
    def _last_blue_ocean(self) -> Optional[dict]:
        """
        默认会话的蓝海结果（**兼容旧引用的只读别名**；新代码请用 `_last_products(context_id)`）。

        保留它是因为既有测试与 `_session_context_block` 按「单会话」语义书写。
        """
        return self._session(None).get("last_blue_ocean")

    @staticmethod
    def _bind_context(
        context_id: Optional[str], shop_id: Optional[str] = None
    ) -> None:
        """
        把会话 ID 与**已校验的**店铺 ID 绑定到 ContextVar，供 tools.py 读回。

        **有意不 reset**：每个请求是独立的 asyncio Task，ContextVar 天然按 Task 隔离，
        且下一次调用会覆盖 —— 这样可省掉「用 try/finally 缩进整个 async 生成器体」。

        `shop_id` 必须是**服务端校验过归属**的值（来自 `get_current_shop_id*`
        依赖），绝不能是原始请求头 —— 详见 `_current_shop_id` 的注释。
        """
        _current_context_id.set(context_id)
        _current_shop_id.set(shop_id)

    async def invoke(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        同步调用 Agent（简单任务）

        Args:
            query: 用户查询
            context_id: 会话上下文 ID（可选）
            shop_id: **已校验归属**的店铺 ID（可选）。入库类意图必须传，
                     否则 `_write_candidates` 会硬拒绝写入。

        Returns:
            AgentResponse 包含结果和展示数据

        决策路径（与 `stream_chat` **完全一致** —— 流式与否只是输出形式，不是两套智能）：
          1. 有 pending 入库槽位 → 优先续填
          2. 关键词表命中结构化意图 → 直接执行（省一次 LLM 往返）
          3. 未命中（general）→ LLM 工具路由兜底（router 自主选工具）
          4. 路由不可用 → 关键词表的 general 分支
        """
        # 0. 绑定会话 ID + 已校验的店铺 ID
        #    （LLM 工具路由里的 tools.py 需要读回它们才能找到本会话状态与写库归属）
        self._bind_context(context_id, shop_id)

        # 1. 入库槽位续填优先（上一轮追问过「还差什么」，本轮回答直接当槽位填充）
        if self._session(context_id).get("pending_save"):
            resumed = await self._resume_pending_save(query, context_id, shop_id)
            if resumed is not None:
                return AgentResponse(
                    content=self._compose_reply(resumed),
                    data=resumed,
                    display_type=resumed.get("type", "general"),
                )

        # 2. 关键词表优先
        intent = await self._classify_intent(query)
        if intent != "general":
            return await self._process_query(query, context_id, intent, shop_id)

        # 3. 未命中 → 工具路由兜底（关键词表从「唯一门」降为「加速器」）
        router = self._get_router()
        if router is not None:
            result = await self._route_via_tools(query, context_id)
            if result is not None:
                return result

        # 4. 最后兜底
        return await self._process_query(query, context_id, "general")

    def _get_router(self):
        """懒加载工具化路由层，返回 None 表示不可用（回退关键词表）。"""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def _build_router(self):
        """构建工具化路由层（BaseAgent 实例，注入 4 个工具）。"""
        if not (self.ENABLE_LLM):
            return None
        try:
            from .tools import product_research_tools
            return BaseAgent(
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.system_prompt,
                tools=product_research_tools,
                max_iterations=4,
                metadata={"role": "sub_agent_router"},
            )
        except Exception as e:
            logger.warning(f"[product_research] router build failed: {e}")
            return None

    # 工具名 → display_type（对齐 _process_query 的 type 语义）
    _TOOL_TYPE_MAP = {
        "analyze_blue_ocean": "blue_ocean_analysis",
        "analyze_profit": "profit_analysis",
        "analyze_pain_points": "pain_point_analysis",
        "compare_competitors": "competitor_analysis",
        "save_candidate": "candidate_saved",
    }

    def _parse_tool_output(self, tool_name: str, tool_result) -> Optional[dict]:
        """
        工具返回的 JSON 文本 → 带 `type` 的 dict（解析不出来返回 None）。

        抽出来给非流式（`_route_via_tools`）与流式（`_stream_via_tools`）共用 ——
        两条路径对同一份工具输出必须给出同一种 type 语义。
        """
        if not tool_result:
            return None
        try:
            data = json.loads(tool_result)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        return {**data, "type": self._TOOL_TYPE_MAP.get(tool_name, "analysis")}

    async def _route_via_tools(
        self, query: str, context_id: Optional[str] = None
    ) -> Optional[AgentResponse]:
        """工具化路由：LLM 自主选工具执行，把工具结果包装回 AgentResponse。

        返回 None 表示路由失败，调用方继续兜底。
        """
        try:
            state = await self._router.graph.ainvoke(
                {"messages": [HumanMessage(content=query)]},
                config={"configurable": {
                    "thread_id": f"product-research-{context_id or id(self)}"
                }},
            )

            messages = state.get("messages", [])
            tool_result = None
            tool_name = ""
            final_reply = ""
            for m in messages:
                if isinstance(m, AIMessage):
                    if getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            if tc.get("name"):
                                tool_name = tc["name"]
                    if m.content:
                        final_reply = m.content
                elif isinstance(m, ToolMessage):
                    tool_result = m.content

            data = self._parse_tool_output(tool_name, tool_result)
            if data is not None:
                return AgentResponse(
                    # 同样不裸吐 JSON：优先 LLM 归纳的 final_reply，
                    # 否则用 summary / error 压成人话（见 _compose_reply）
                    content=final_reply or self._compose_reply(data),
                    data=data,
                    display_type=data.get("type", "analysis"),
                )

            if final_reply:
                return AgentResponse(content=final_reply, data=None, display_type="text")

            return None
        except Exception as e:
            logger.warning(f"[product_research] tool routing failed: {e}")
            return None

    async def _stream_via_tools(
        self, query: str, context_id: Optional[str] = None
    ) -> AsyncIterable:
        """
        LLM 工具路由（**流式版**）。

        与 `_route_via_tools` 是**同一条决策路径**（router 的 LLM 自主选工具），
        差别只在输出形式：文本逐 token 下发，而不是攒完一次性返回。
        这正是「流式与非流式只是输出形式」的落地 —— 先前流式路径只走关键词表，
        表漏一个词就掉进 general 闲聊，同一句话在两条路径上表现不一致（实测踩坑）。

        兜底链：router 不可用 / 异常 / 无输出 → 带会话语境的 LLM 闲聊。
        保证**永远有输出**，不会给老板一个空白回复。
        """
        router = self._get_router()
        tool_name = ""
        tool_output = None
        replied = False

        if router is not None:
            try:
                async for ev in router.graph.astream_events(
                    {"messages": [HumanMessage(content=query)]},
                    config={"configurable": {
                        "thread_id": f"product-research-{context_id or id(self)}"
                    }},
                    version="v2",
                ):
                    et = ev.get("event")
                    if et == "on_chat_model_stream":
                        chunk = ev.get("data", {}).get("chunk")
                        text = getattr(chunk, "content", "") or ""
                        if text:
                            replied = True
                            yield text
                    elif et == "on_tool_start":
                        tool_name = ev.get("name") or tool_name
                    elif et == "on_tool_end":
                        tool_output = ev.get("data", {}).get("output")
            except Exception as e:
                logger.warning(f"[product_research] stream tool routing failed: {e}")

        data = self._parse_tool_output(tool_name, tool_output)
        if data is not None:
            # LLM 没自己总结过工具结果 → 由我们把结论压成人话补上
            if not replied:
                yield self._compose_reply(data)
            yield {
                "event": "meta",
                "data": {"display_type": data.get("type", "analysis"), "data": data},
            }
            return

        if replied:
            return

        # 既没调到工具、也没吐出文本 → 闲聊兜底（带会话语境，别让它编通用知识）
        async for chunk in self._general_stream(query, context_id):
            yield chunk

    async def _general_stream(
        self, query: str, context_id: Optional[str] = None
    ) -> AsyncIterable[str]:
        """闲聊流式（带本轮会话语境；LLM 不可用时退化为能力引导文案）。"""
        if not (self.ENABLE_LLM and self.llm_client):
            result = await self._general_chat(query)
            yield result.get("response", "")
            return

        try:
            async for chunk in self.llm_stream(
                query,
                # 角色提示词 + **本轮会话语境**：不带上文时 LLM 手里没有真实数据，
                # 只能照提示词骨架编通用知识（实测编出 Google Trends / CE 认证 / 物流风险）。
                system_prompt=self.get_prompt_template("product_research", market="全球")
                + self._session_context_block(context_id),
                model=self.DEFAULT_MODEL,
                temperature=0.7,
                max_tokens=1024,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[product_research] general stream failed: {e}")
            result = await self._general_chat(query)
            yield result.get("response", "")

    async def stream(self, query: str, context_id: str = None) -> AsyncIterable[dict]:
        """
        流式调用 Agent（复杂任务，支持进度推送）

        Yields:
            进度事件：{type: "thinking"|"tool_call"|"result", data: ...}
        """
        yield {"type": "thinking", "data": f"正在分析: {query}"}

        # 1. 意图识别
        intent = await self._classify_intent(query)
        yield {"type": "progress", "data": f"已识别意图: {intent}"}

        # 2. 执行对应工具
        if intent == "blue_ocean":
            yield {"type": "tool_call", "data": "正在挖掘蓝海品类..."}
            result = await self._analyze_blue_ocean(query)
        elif intent == "profit":
            yield {"type": "tool_call", "data": "正在计算利润..."}
            result = await self._analyze_profit(query)
        elif intent == "pain_points":
            yield {"type": "tool_call", "data": "正在分析用户痛点..."}
            result = await self._analyze_pain_points(query)
        elif intent == "competitor":
            yield {"type": "tool_call", "data": "正在对比竞品..."}
            result = await self._analyze_competitors(query)
        else:
            # 通用对话
            result = await self._general_chat(query)

        yield {"type": "result", "data": result}

    # ====== 意图分类 ======

    async def _classify_intent(self, query: str) -> str:
        """
        分类用户意图

        Returns:
            blue_ocean / profit / pain_points / competitor / save_candidate / general
        """
        query_lower = query.lower()

        # 「≥2 个 ASIN」是竞品对比的强信号，比关键词可靠，优先判定
        if len(self._extract_multiple_asins(query)) >= 2:
            return "competitor"

        # ⚠️ 「加入选品库 / 存入选品库」必须先于 blue_ocean 判定：
        # 「选品库」里含有「选品」，而「选品」是 blue_ocean 的关键词 ——
        # 实测「这个品帮我进入选品库」会被判成 blue_ocean，把挖掘重跑一遍。
        #
        # ⚠️ 口语化的「入库」必须收录。旧表只有「加入库 / 存进选品」这类书面说法，
        # 实测老板说「Portable Mini Humidifier …帮我入库」→ 一个关键词都没命中 →
        # 判成 general → 把商品名**裸丢给 LLM 闲聊**，编出一大段通用市场分析
        # （Google Trends「搜索热度较高」/ CE·FCC 认证 / 液体容器物流风险，全是套话），
        # 而商品池里恰好就有这个品（B0HUMI0001），本该一句话入库成功。
        # 「入库」是电商语境里最高频的说法，漏它 = 漏掉最常见的表达。
        save_keywords = [
            "选品库", "候选库", "候选池", "入库",  # 「入库」覆盖 加入库/存进库/加进库
            "加入候选", "加入选品", "添加到选品", "加到选品",
            "保存到选品", "存入选品", "加进选品", "存进选品",
        ]
        for kw in save_keywords:
            if kw in query_lower:
                return "save_candidate"

        # 关键词匹配规则
        blue_ocean_keywords = [
            "蓝海", "机会", "选品", "挖掘", "品类", "趋势", "什么好卖", "好卖", "好销",
            "热销", "热门", "爆款", "比较火", "很火", "火爆", "有市场", "值得做", "潜力",
            "好做", "能做吗", "有前途", "冷门",
        ]
        profit_keywords = ["利润", "费用", "FBA", "成本", "ROI", "售价", "定价", "赚钱"]
        pain_keywords = ["痛点", "差评", "评论", "问题", "不满意", "抱怨"]
        # ⚠️ 绝不能收裸 "比较"：中文里 "比较" 绝大多数是**副词**（比较好卖 / 比较火 /
        # 比较便宜），只有带被比较对象时才是「对比」语义。收裸 "比较" 会让
        # 「现在有哪些比较火的产品」被判成竞品对比（实测 bug）。
        competitor_keywords = [
            "对比", "竞品", "竞争对手", "比较一下", "比较下", "比较两", "比较这",
            "哪个更好", "哪个好", "哪款好", "买哪个", "选哪个", "vs", "versus", "analysis",
        ]

        for kw in blue_ocean_keywords:
            if kw in query_lower:
                return "blue_ocean"

        for kw in profit_keywords:
            if kw in query_lower:
                return "profit"

        for kw in pain_keywords:
            if kw in query_lower:
                return "pain_points"

        for kw in competitor_keywords:
            if kw in query_lower:
                return "competitor"

        return "general"

    # ====== 核心分析方法 ======

    async def _analyze_blue_ocean(self, query: str, context_id: Optional[str] = None) -> dict:
        """
        蓝海品类挖掘（支持 LLM 增强）

        类目识别为 None 时**不再兜底成 "general" 泛词表**（那批词在关键词库中
        命中不到，会走「未匹配 → 随机估算」路径，分数随机、结论不可信），
        改用跨类目精选的全类目高潜关键词（`_TRENDING_KEYWORDS`）。

        `context_id` 用于把本轮结果**按会话**缓存（`_last_products`），
        供「把第 1 个加进选品库」这类指代解析；不传则落在默认会话。
        """
        # 1. 提取目标类目（None = 未识别出具体类目 → 全类目扫描）
        category = self._extract_category(query)

        # 2. 获取相关关键词数据
        keywords_to_check = self._generate_search_keywords(category)
        keyword_data_list = []
        for kw in keywords_to_check[:8]:  # 检查前8个关键词
            data = await self.adapter.get_keyword_data(kw)
            keyword_data_list.append(data)

        # 3. 计算机会评分并排序
        opportunities = []
        for kd in keyword_data_list:
            score = self._calculate_opportunity_score(kd)
            if score >= 50:  # 只保留高分机会
                opp = BlueOceanOpportunity(
                    category=kd.keyword,
                    search_volume=kd.search_volume,
                    competition=kd.competition,
                    trend=kd.trend_direction,
                    opportunity_score=score,
                    reason=self._generate_reason(kd),
                    suggested_price_range=self._estimate_price_range(category),
                    estimated_margin=self._estimate_margin(kd.competition),
                )
                opportunities.append(opp)

        # 按分数降序排列
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

        top_opportunities = opportunities[:5]  # Top 5
        total = len(opportunities)

        # ===== 词 → 商品：把「方向」落到「具体的货」 =====
        #
        # 为什么必须做这一步：词级机会**没有 ASIN**，而候选选品库以 `asin` 为核心
        # 标识。只给词，老板既存不进库、也没法横向对比；「把这个品加进选品库」
        # 这类指令也就无从解析。这里把每条机会回查商品池，并把**该词的市场层指标**
        # 随商品带下去（市场层 + 商品层两个维度都要留，不是二选一）。
        opp_dicts: List[dict] = []
        products: List[dict] = []
        seen_asins: set = set()

        for opp in top_opportunities:
            try:
                matched = await self.adapter.match_products(opp.category, limit=2)
            except Exception as e:
                logger.warning(f"[product_research] match_products failed for {opp.category}: {e}")
                matched = []

            opp_dict = opp.dict()
            opp_dict["matched_count"] = len(matched)
            opp_dicts.append(opp_dict)

            for m in matched:
                asin = m.get("asin")
                if not asin or asin in seen_asins:
                    continue
                seen_asins.add(asin)
                products.append({
                    **m,
                    "source_keyword": opp.category,
                    "keyword_search_volume": opp.search_volume,
                    "keyword_competition": opp.competition,
                    "keyword_trend": opp.trend,
                    "keyword_opportunity_score": opp.opportunity_score,
                })

        # 面向老板的文案：绝不回显内部标识（如 general）；未指定类目时说人话
        where = f"在「{category}」领域" if category else "全类目高潜方向"
        prefix = where if category else "未识别出具体类目，已按全类目高潜方向扫描，"
        if total == 0:
            summary = f"{where}暂未发现评分达标的蓝海机会，建议换个类目或放宽筛选条件"
        elif products:
            summary = f"{prefix}发现 {total} 个蓝海方向，对应 {len(products)} 个候选商品"
        else:
            summary = f"{prefix}发现 {total} 个蓝海方向，但商品池里暂无匹配的具体商品"

        result = {
            "type": "blue_ocean_analysis",
            "query": query,
            "category": category or "all",
            # 主列表（商品层）：可直接对比 / 入库
            "products": products,
            # 市场层：词与其搜索量/竞争度/趋势（词不再是独立卡片，降级为商品的来源标注）
            "opportunities": opp_dicts,
            "summary": summary,
        }

        # 缓存本轮结果，供「把第 N 个 / 这个品加进选品库」这类指代解析。
        # 按会话存 —— 否则 A 会话挖的蓝海会被 B 会话的「第 1 个」取走。
        self._session(context_id)["last_blue_ocean"] = result

        # ====== LLM 增强：智能总结与建议 ======
        if self.ENABLE_LLM:
            try:
                llm_result = await self.llm_structured(
                    user_message=f"""
基于以下蓝海分析数据，请提供：
1. **市场机会总结**（2-3句话概括）
2. **Top 3 推荐进入的细分品类**（附理由）
3. **风险提示**（可能的市场壁垒或竞争威胁）
4. **行动建议**（具体的下一步行动）

数据：
{json.dumps([{'keyword': o['category'], 'score': o['opportunity_score'], 'volume': o['search_volume']} for o in result['opportunities']], ensure_ascii=False)}
""",
                    system_prompt=self.get_prompt_template("product_research", market="全球"),
                    output_format="json",
                )

                if llm_result.success and isinstance(llm_result.content, dict):
                    result["llm_insights"] = llm_result.content
                    result["enhanced"] = True
                    result["llm_fallback"] = llm_result.fallback

            except Exception as e:
                logger.warning(f"Blue ocean LLM enhancement failed: {e}")

        return result

    async def _analyze_profit(self, query: str) -> dict:
        """SKU 利润分析"""
        # 1. 尝试从查询中提取产品信息
        product_info = self._extract_product_info(query)

        # 2. 如果有 ASIN，获取产品详情
        product = None
        if product_info.get("asin"):
            product = await self.adapter.get_product_detail(product_info["asin"])
            if product is None and not product_info.get("price"):
                # 查不到详情又没给售价 → 没法算，别抛 AttributeError（会变成 500）
                return {
                    "type": "profit_analysis",
                    "query": query,
                    "error": "查不到该 ASIN 的售价",
                    "summary": (
                        f"没查到 {product_info['asin']} 的售价，先算不了利润。"
                        f"你可以把售价一起告诉我，比如「分析 {product_info['asin']} 的利润，售价 $29.99」。"
                    ),
                }

        if product is None:
            # 使用用户提供的参数估算
            product = ProductData(
                product_id=product_info.get("asin") or "estimated",
                title=(
                    product_info.get("name")
                    or (f"ASIN {product_info['asin']}" if product_info.get("asin") else "待定产品")
                ),
                price=product_info.get("price", 29.99),
                platform=self.adapter.platform_type,
            )

        # 3. 计算费用
        fees = self.adapter.calculate_fees(
            price=product.price,
            category=product.category or "",
            weight_lbs=product_info.get("weight", 1.5),
        )

        # 4. 计算利润（假设采购成本为售价的 30%）
        cost_price = product.price * 0.30
        ad_cost = product.price * 0.15  # 广告 ACOS 15%
        total_cost = cost_price + fees.total_fees + ad_cost
        net_profit = product.price - total_cost
        roi = (net_profit / total_cost) * 100 if total_cost > 0 else 0
        break_even = int(total_cost / net_profit) if net_profit > 0 else 9999

        analysis = ProfitAnalysis(
            product_name=product.title,
            cost_price=round(cost_price, 2),
            selling_price=product.price,
            fees=fees,
            total_cost=round(total_cost, 2),
            net_profit=round(net_profit, 2),
            roi_percentage=round(roi, 1),
            break_even_quantity=break_even,
        )

        return {
            "type": "profit_analysis",
            "query": query,
            "product": product.title if product else "未知产品",
            "analysis": analysis.dict(),
            "fees_breakdown": {
                "采购成本": round(cost_price, 2),
                "平台佣金": round(fees.referral_fee_pct * product.price / 100, 2),
                "FBA配送费": fees.fba_fulfillment_fee,
                "仓储费": fees.storage_fee_monthly,
                "广告费": round(ad_cost, 2),
            },
            "summary": (
                f"{product.title}：售价 ${product.price:.2f}，"
                f"总成本 ${analysis.total_cost:.2f}"
                f"（采购 ${analysis.cost_price:.2f} + 平台费 ${fees.total_fees:.2f} + 广告 ${ad_cost:.2f}），"
                f"净利润 ${analysis.net_profit:.2f}，ROI {analysis.roi_percentage:.1f}%，"
                f"约 {break_even} 件回本。"
            ),
        }

    async def _analyze_pain_points(self, query: str) -> dict:
        """痛点机会识别"""
        # 1. 提取 ASIN 或产品名称
        asin = self._extract_asin(query)
        if not asin:
            return {
                "type": "pain_point_analysis",
                "query": query,
                "error": "需要产品 ASIN",
                "summary": (
                    "痛点分析得先知道是哪个产品——把产品 ASIN（形如 B0C1234567）发我，"
                    "我就去看它的中差评、提炼可改进点。"
                ),
            }

        # 2. 获取评论（重点看差评）
        reviews_1_2_star = await self.adapter.get_reviews(asin, rating_filter=2)
        reviews_3_star = await self.adapter.get_reviews(asin, rating_filter=3)
        all_negative = reviews_1_2_star + reviews_3_star

        # 3. 统计痛点频率
        pain_point_counts = {}
        for review in all_negative:
            for pp in review.pain_points:
                pain_point_counts[pp] = pain_point_counts.get(pp, 0) + 1

        total_reviews = len(all_negative)
        pain_points_sorted = sorted(
            pain_point_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]

        pain_points_formatted = [
            {
                "pain_point": pp,
                "count": count,
                "percentage": round(count / total_reviews * 100, 1) if total_reviews > 0 else 0,
            }
            for pp, count in pain_points_sorted
        ]

        # 4. 生成改进建议
        suggestions = self._generate_improvement_suggestions(pain_points_formatted)

        # 5. 计算市场空白度评分
        gap_score = min(100, sum([pp["percentage"] for pp in pain_points_formatted[:3]]))

        analysis = PainPointAnalysis(
            product_asin=asin,
            total_reviews_analyzed=len(all_negative),
            negative_review_count=len(reviews_1_2_star),
            pain_points=pain_points_formatted,
            improvement_suggestions=suggestions,
            market_gap_score=gap_score,
        )

        return {
            "type": "pain_point_analysis",
            "query": query,
            "asin": asin,
            "analysis": analysis.dict(),
            "top_pain_points": pain_points_formatted[:5],
            "summary": (
                f"{asin} 共分析 {len(all_negative)} 条中差评，"
                + (
                    # 只报「最集中的 1 个」等于没说全——老板问「有哪些痛点」要的是清单
                    "主要痛点：" + "、".join(
                        f"「{pp['pain_point']}」({pp['percentage']}%)"
                        for pp in pain_points_formatted[:3]
                    )
                    if pain_points_formatted else "暂未提炼出明显痛点"
                )
                + f"，市场空白度评分 {gap_score}。"
            ),
        }

    async def _analyze_competitors(self, query: str) -> dict:
        """竞品对比分析"""
        # 1. 提取多个 ASIN
        asins = self._extract_multiple_asins(query)
        if len(asins) < 2:
            return {
                "type": "competitor_analysis",
                "query": query,
                "competitors": [],
                "error": "需要至少 2 个产品 ASIN",
                "summary": (
                    "竞品对比需要至少 2 个产品 ASIN（形如 B0C1234567）。"
                    "把两个竞品的 ASIN 发我即可；也可以在右侧「竞品圈选」里挑好，再让我对比。"
                ),
            }

        # 2. 批量分析竞品
        competitor_results = await self.adapter.analyze_competitors(asins)
        if not competitor_results:
            return {
                "type": "competitor_analysis",
                "query": query,
                "competitors": [],
                "error": "未取到竞品数据",
                "summary": (
                    f"拿到了 ASIN（{', '.join(asins)}），但平台没返回可对比的竞品数据。"
                    "换个 ASIN 或稍后重试。"
                ),
            }

        return {
            "type": "competitor_analysis",
            "query": query,
            "competitors": [c.dict() for c in competitor_results],
            "summary": f"已对比 {len(competitor_results)} 个竞品：{', '.join(asins)}。",
        }

    def _session_context_block(self, context_id: Optional[str] = None) -> str:
        """
        给「对话类」LLM 回复注入**本轮会话语境**。

        为什么必须注入：general 分支原先把 query 裸丢给 LLM —— 只给了角色提示词，
        既没有上下文也没有工具。LLM 手里没有任何真实数据，只能照着 system prompt 里
        「数据驱动 / 趋势洞察 / 风险意识」的骨架**编通用知识**：实测编出了
        「Google Trends 搜索热度较高」「CE、FCC 认证」「液体容器国际运输限制」
        这类放之四海皆准的套话，读起来像通用聊天机器人而不是选品助手。

        注意这跟「有没有接 LLM」无关 —— LLM 接了，但没给它干活的条件。
        把真实候选商品摆到它面前，它才答得出「你要入库的是不是这个」。
        """
        lines: List[str] = []
        products = self._last_products(context_id)

        if products:
            lines.append("")
            lines.append("【本轮会话上下文】")
            lines.append("上一轮蓝海挖掘产出的候选商品（用户说「这个 / 那个 / 第 N 个」时指的是这些）：")
            for i, p in enumerate(products[:10], 1):
                lines.append(
                    f"  {i}. {p.get('title') or '未命名'}（{p.get('asin') or '无 ASIN'}）"
                    f" 售价 ${float(p.get('price') or 0):.2f}"
                    f" ｜ 预估 ROI {p.get('roi') or 0}%"
                )

        lines.append("")
        lines.append("【输出约束】")
        lines.append(
            "1. 只依据上面的真实数据和用户原话回答；"
            "**严禁编造**搜索趋势、销量、专利、认证、物流限制等外部数据。"
            "拿不到的数据就说拿不到，并告诉用户该走哪个分析动作。"
        )
        lines.append(
            "2. 你**没有执行任何写操作**。若用户想入库但目标商品不在上面、也没给 ASIN，"
            "直接追问要入库哪一个（让他给 ASIN 或商品标题），不要替他猜、也不要假装已完成。"
        )
        return "\n".join(lines)

    async def _general_chat(self, query: str) -> dict:
        """通用对话（降级路径：LLM 不可用时返回能力引导文案）"""
        return {
            "type": "general_response",
            "query": query,
            "response": f"收到您的关于「{query}」的问题。作为选品分析师，我可以帮您：\n\n"
                       f"1. 🔍 挖掘蓝海品类机会\n"
                       f"2. 💰 计算 SKU 利润空间\n"
                       f"3. 📊 分析竞品用户痛点\n"
                       f"4. ⚔️ 对比多个竞品\n"
                       f"5. 📥 把看中的商品加进选品库（说「把第 1 个加进选品库」即可）\n\n"
                       f"请告诉我您想了解哪个方面？",
        }

    def _named_tokens(self, query: str) -> List[str]:
        """
        查询里用于「点名商品」的实词 token。

        `tokenize` 以非字母数字切分 → 中文（「帮我加进选品库」「这个品」「第 2 个」）
        自然落空，只剩英文实词；再滤掉英文动作词（add / candidate / library …）。
        因此返回非空 == 用户**点名了某个商品**，空 == 纯指代或纯中文指令。
        """
        from platforms.amazon.client import tokenize

        return [t for t in tokenize(query) if t not in self._SAVE_ACTION_WORDS]

    async def _resolve_named_product(
        self, query: str, context_id: Optional[str] = None
    ) -> Optional[dict]:
        """
        查询里点名了商品标题 → 在商品池里按词边界匹配 Top 1；找不到返回 None。

        为什么必须有这一步：原先的解析只有「ASIN / 序数 / 否则 Top1」三条路，
        用户把**整条商品标题**贴进来时既没 ASIN 也没序数 → 直接落到「上一轮 Top1」。
        实测踩坑：上一轮蓝海 Top1 是瑜伽垫，这轮点名
        「Automatic Pet Feeder, Smart Food Dispenser…」→ 又把瑜伽垫存了一遍（存了 3 条重复）。
        """
        tokens = self._named_tokens(query)
        if not tokens:
            return None

        try:
            hits = await self.adapter.match_products(" ".join(tokens), limit=1)
        except Exception as e:  # noqa: BLE001 —— 匹配失败按「没找到」处理，别阻断入库
            logger.warning(f"[product_research] resolve named product failed: {e}")
            return None
        if not hits:
            return None

        hit = hits[0]
        # 上一轮蓝海结果里已有同一商品时优先用它（自带来源机会词等市场层上下文）
        asin = (hit.get("asin") or hit.get("product_id") or "").upper()
        if asin:
            for p in self._last_products(context_id):
                if (p.get("asin") or "").upper() == asin:
                    return p
        return hit

    # ====== 入库：面板流程的「对话免填版」 ======

    def _candidate_payload_from_product(self, p: dict) -> dict:
        """
        商品记录 → 候选 payload。

        字段语义**对齐前端面板**（`BlueOceanResult.vue` 的 `mapToCandidate()`）：
        sku / margin / tags / notes 全部自动生成，用户什么都不用填。
        可选字段这里「有数据就带上」，缺省由 `candidates/service.build_candidate_record`
        补默认值 —— 两处默认值不再各写一份。
        """
        price = float(p.get("price") or 0)
        roi = float(p.get("roi") or p.get("roi_estimated") or 0)
        margin = (
            round((price - price / (1 + roi / 100)) / price * 100)
            if price > 0 and roi > 0 else 0
        )
        raw_category = p.get("category") or ""
        asin = (p.get("asin") or "").strip()
        score = int(p.get("keyword_opportunity_score") or p.get("blue_ocean_score") or 0)
        source_keyword = p.get("source_keyword") or ""
        sales = int(p.get("estimated_monthly_sales") or 0)

        return {
            "asin": asin,
            "sku": f"SKU-CAND-{asin[2:] if asin.upper().startswith('B0') else (asin or 'MANUAL')}",
            # 注意：这里**不兜底**「未命名候选」—— 必填校验要能看见「标题是空的」，
            # 兜底交给 build_candidate_record（那是「写入时」的职责，不是「校验时」的）。
            "title": (p.get("title") or "").strip(),
            "brand": p.get("brand") or "",
            "category": (raw_category.split(" > ")[0] or "other") if raw_category else "other",
            "sub_category": raw_category.split(" > ")[-1] if raw_category else "",
            "price": price,
            "currency": "USD",
            "site": p.get("marketplace") or "Amazon US",
            "estimated_monthly_sales": sales,
            "review_count": int(p.get("review_count") or 0),
            "rating": float(p.get("rating") or 0),
            "bsr": p.get("bsr_rank"),
            "bsr_category": raw_category,
            "roi_estimated": roi,
            "margin": margin,
            "blue_ocean_score": score,
            "main_image": p.get("main_image") or p.get("image_url") or "",
            "source": "blue_ocean",
            "keywords": [source_keyword] if source_keyword else [],
            "tags": ["蓝海挖掘", f"评分:{score}", f"ROI:{roi}%"],
            "notes": (
                f"来源：蓝海挖掘 | 评分：{score} | 预估月销：{sales} | ROI：{roi}%"
                + (f" | 来源机会词：{source_keyword}" if source_keyword else "")
                + "（由选品分析师从对话写入）"
            ),
            # 分组是面板里唯一的人工交互（可选项）—— 对话入库由后台兜底，不为它打断用户
            "groups": [],
        }

    def _ask_for_save(
        self,
        context_id: Optional[str],
        draft: dict,
        missing: List[str],
        hint: str = "",
    ) -> dict:
        """
        记下待补槽位并追问。

        **有状态**才是关键：下一轮用户回「B0KLMN3456」时不再重新做意图分类，
        而是直接当答案填进来（见 `_resume_pending_save`）。
        没有这个状态，「多轮补齐」根本进行不下去 —— 用户回一句
        「就那个加湿器」会被判成 general 直接跑偏（实测）。
        """
        from modules.candidates.service import describe_missing_fields

        self._session(context_id)["pending_save"] = {
            "draft": draft,
            "awaiting": list(missing),
            "hint": hint,
        }
        return {
            "type": "candidate_save_failed",
            # soft_error：这是**追问**（对话的正常一步），不是失败 ——
            # 让 `_compose_reply` 别给它套上「这次没跑通」。
            "soft_error": True,
            "awaiting": list(missing),
            "error": f"还缺 {describe_missing_fields(missing)}，补齐我就直接入库。{hint}",
        }

    _SAVE_CANCEL_WORDS = ("算了", "取消", "不用了", "不弄了", "不要了", "先不放", "放弃")

    async def _resume_pending_save(
        self,
        query: str,
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        入库槽位续填：把这一轮消息当作「上一轮追问的答案」处理。

        返回 None 表示「用户显然在说别的事」→ 调用方清掉 pending 回到常规流程。
        `shop_id` 一路带到 `_write_candidates`（槽位补齐的**终点就是一次写库**，
        漏传会让"多轮补齐"在最后一步被拒）。
        """
        from modules.candidates.service import missing_required_fields

        session = self._session(context_id)
        pending = session.get("pending_save") or {}
        q = (query or "").strip()
        draft = dict(pending.get("draft") or {})

        # ① 明确放弃
        if any(w in q for w in self._SAVE_CANCEL_WORDS):
            session.pop("pending_save", None)
            return {
                "type": "candidate_save_failed",
                "soft_error": True,
                "error": "好，这次不入库了。想存的时候说一声「把这个品加进选品库」就行。",
            }

        # ② 用户在说别的事（含其他结构化意图）→ 放弃 pending，回到常规分类
        if await self._classify_intent(q) != "general":
            session.pop("pending_save", None)
            return None

        asins = self._extract_multiple_asins(q)
        if asins and not draft.get("asin"):
            asin = asins[0]
            draft["asin"] = asin
            # 顺手把标题补上：先看本会话蓝海结果，再查商品详情
            hit = next(
                (p for p in self._last_products(context_id)
                 if (p.get("asin") or "").upper() == asin),
                None,
            )
            if hit:
                draft["product"] = hit
                draft["title"] = draft.get("title") or (hit.get("title") or "").strip()
            else:
                try:
                    detail = await self.adapter.get_product_detail(asin)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[product_research] pending save detail failed: {e}")
                    detail = None
                if detail:
                    draft["title"] = draft.get("title") or (detail.title or "").strip()

        elif not draft.get("title"):
            # 没给 ASIN → 当作「补商品名 / 标题」
            named = await self._resolve_named_product(q, context_id)
            if named:
                draft["product"] = named
                draft.setdefault("asin", (named.get("asin") or "").strip())
                draft["title"] = (named.get("title") or "").strip()
            else:
                # 拿用户原话当标题（去掉首尾标点与动作词残留）
                text = q.strip(" \t\r\n「」\"'。,.，")
                if text:
                    draft["title"] = text

        missing = missing_required_fields(draft)
        if missing:
            return self._ask_for_save(context_id, draft, missing, pending.get("hint") or "")

        session.pop("pending_save", None)
        product = dict(draft.get("product") or {})
        product["asin"] = product.get("asin") or draft.get("asin") or ""
        product["title"] = product.get("title") or draft.get("title") or ""
        return await self._write_candidates([product], context_id, shop_id)

    async def _write_candidates(
        self,
        targets: List[dict],
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> dict:
        """
        真正写库：判重 + 批量。

        与面板走**同一个写入口**（`candidates/service.create_candidate`），
        所以字段默认值与前端按钮完全一致。

        ★★★ `shop_id` 必须**显式传入**（P0 安全修复 2026-09-16，BOLA）
            修复前这里直读 `core.tenant.middleware.tenant_context.shop_id`
            （★ C4 2026-09-16：该符号已随账户侧收拢删除，此处仅为事故记录），
            而那个值由 `TenantMiddleware` 用**未校验的原始 `X-Shop-ID` 头**写入
            ⇒ 「带自己的 token + 改一下请求头」就能把候选写进别人的选品库
              （探针 r84d 实测三段对照：有校验的端点 403，本路径 200 且落库
                 shop_id = 受害店铺）。
            为什么旧写法特别隐蔽：读的是"看起来很干净"的 request-scoped 缓存，
            脏数据在上游写进去，本处完全看不出问题。

        ★ 无店铺上下文 ⇒ **硬拒绝**（可读失败 + 零数据库往返）。
          不用"写空分区"兜底：`shop_id` 为空会撞 `fk_*_shop_id_stores_store`
          外键 → 500 且把 SQLAlchemy 报错与约束名吐给客户端（见 shop_id 空值
          守卫那段修复），而且归因文案会变成"数据库不可用"，误导排查方向。
        """
        from modules.candidates.service import candidate_exists, create_candidate

        shop_id = (shop_id or "").strip() or None
        if shop_id is None:
            return {
                "type": "candidate_save_failed",
                "error": (
                    "还没选择店铺，我这边没法入库。请先在界面左上角选一个店铺，"
                    "再说一次「把……加进选品库」。"
                ),
            }

        saved: List[dict] = []
        skipped: List[str] = []
        failed: List[str] = []
        for p in targets:
            payload = self._candidate_payload_from_product(p)
            # 判重：同一店铺下同 ASIN 已存在就不再写。否则反复说「加进选品库」
            # 会累积多条同商品记录，评审时无法分辨哪条是最新评估。
            try:
                if await candidate_exists(payload["asin"], shop_id):
                    skipped.append(
                        f"{(payload['title'] or '未命名')[:28]}（{payload['asin'] or '—'}）"
                    )
                    continue
            except Exception as e:  # noqa: BLE001 —— 判重失败不阻断写入
                logger.warning(f"[product_research] dedupe check failed for {payload['asin']}: {e}")
            try:
                saved.append(await create_candidate(payload, shop_id=shop_id))
            except Exception as e:
                logger.warning(f"[product_research] save_candidate failed for {payload['asin']}: {e}")
                failed.append(payload["asin"] or "未知 ASIN")

        if not saved and not skipped:
            return {
                "type": "candidate_save_failed",
                "error": "写入选品库失败（数据库不可用），请稍后重试。",
            }

        parts: List[str] = []
        if saved:
            names = "、".join(
                f"{(s.get('title') or '未命名')[:28]}（{s.get('asin') or '—'}）" for s in saved
            )
            parts.append(f"已加入选品库（待评审）：{names}")
        if skipped:
            parts.append(f"已在选品库中、未重复写入：{'、'.join(skipped)}")
        if failed:
            parts.append(f"{len(failed)} 个写入失败（{', '.join(failed)}）")

        return {
            "type": "candidate_saved",
            "saved": saved,
            "skipped": skipped,
            "failed": failed,
            "summary": "；".join(parts),
        }

    async def _save_candidate(
        self,
        query: str,
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> dict:
        """
        把商品写入选品库（对话直达）。

        `shop_id` 是**已校验归属**的店铺 ID（来自 `get_current_shop_id*` 依赖）。
        不传 = 拿不到归属 = `_write_candidates` 拒绝写入，绝不"猜一个"。

        这是前端「蓝海结果卡 → 勾选 → 选分组 → 保存」那条**面板流程的免填版**：
        字段契约与面板一致（必填 ASIN / 商品标题，单点定义在 `modules/candidates/service.py`），
        差别只在交互方式：
          - 必填缺失 → **多轮追问补齐**（`_ask_for_save` 记 pending，`_resume_pending_save` 续填）
          - 可选缺失 → 后台按默认值自动补，**不打扰用户**（含面板里那个人工交互「选分组」）

        目标商品解析优先级：
          1. 查询里显式写了 ASIN → 用提到的（支持多个）
          2. 查询里写了序数（第一个 / 第2个 / top1）→ 取本会话上一次蓝海结果的对应位
             （越界则**追问**并告知实际条数，绝不静默折回 Top1）
          3. 查询里**点名了商品**（如整条标题）→ 去商品池按词边界匹配 Top1
          4. 纯指代（「这个品」「刚才那个」）→ 本会话上一次蓝海结果的 Top 1
        解析不到 / 必填凑不齐 → 追问，**绝不写半成品或空壳**。

        另有**同店铺同 ASIN 判重**（在 `_write_candidates` 里）：已在库中则不重复写入。
        """
        last_products: List[dict] = self._last_products(context_id)

        targets: List[dict] = []
        asins = self._extract_multiple_asins(query)
        if asins:
            for a in asins:
                hit = next(
                    (p for p in last_products if (p.get("asin") or "").upper() == a),
                    None,
                )
                if hit is None:
                    detail = await self.adapter.get_product_detail(a)
                    if detail:
                        hit = {**detail.model_dump(), "asin": detail.product_id,
                               "main_image": detail.image_url}
                if hit:
                    targets.append(hit)
                else:
                    # 给了 ASIN，但本会话蓝海结果与商品库里都没有它 → 标题就是缺的。
                    # 面板里标题是必填项，所以这里追问补齐，而不是拿 ASIN 当标题硬写。
                    return self._ask_for_save(
                        context_id,
                        draft={"asin": a},
                        missing=["title"],
                        hint=f"商品 {a} 不在商品库里，把它的标题发我就能入库。",
                    )
        else:
            idx = self._extract_ordinal(query)
            if idx is not None:
                # 序数越界**不能静默折回 Top1**：「把第 9 个加进去」存成第 1 个
                # 属于「答非所问地写库」，比不写更糟（用户会以为存对了）。
                if not last_products:
                    return {
                        "type": "candidate_save_failed",
                        "error": f"还没有可选的商品清单。先让我挖一轮蓝海，"
                                 f"再说「把第 {idx + 1} 个加进选品库」。",
                    }
                if not (0 <= idx < len(last_products)):
                    return {
                        "type": "candidate_save_failed",
                        "error": f"上一轮只有 {len(last_products)} 个商品，没有第 {idx + 1} 个。"
                                 f"可以说「把第 1~{len(last_products)} 个加进选品库」。",
                    }
                targets.append(last_products[idx])
            else:
                # 查询里若**点名了商品**（如整条标题），必须去商品池核对；
                # 否则一旦落到「上一轮 Top1」，就会出现「点名宠物喂食器、存进瑜伽垫」。
                named = await self._resolve_named_product(query, context_id)
                if named:
                    targets.append(named)
                elif self._named_tokens(query):
                    # 点名了但池里匹配不到 → 不能改存别的商品充数（实测会存成上一轮 Top1），
                    # 转成「缺 ASIN」的待补项：用户给了 ASIN 就能入库。
                    hint = " ".join(self._named_tokens(query))[:60]
                    return self._ask_for_save(
                        context_id,
                        draft={"title": hint},
                        missing=["asin"],
                        hint=f"商品库里没找到「{hint}」，给我 ASIN（如 B0KLMN3456）就能入库。",
                    )
                elif last_products:
                    # 纯指代（「这个品」「刚才那个」）——才允许取上一轮 Top1
                    targets.append(last_products[0])

        if not targets:
            # 完全没说清要入哪个：记 pending 追问，用户下一句回答会被当槽位填充
            return self._ask_for_save(
                context_id,
                draft={},
                missing=["asin", "title"],
                hint="可以直接给我 ASIN（如 B0KLMN3456），或把商品标题贴给我。",
            )

        # 目标解析完成 → 写库（与前端面板同一个写入口）
        return await self._write_candidates(targets, context_id, shop_id)

    async def stream_chat(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
    ) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        **决策路径与 `invoke` 完全一致** —— 流式只是输出形式，不是另一套智能：
          1. pending 入库槽位 → 续填
          2. 关键词表命中结构化意图 → 执行；结论仍一次性下发（它本就是结构化清单，
             不是逐字生成的），并补 `meta` 让前端出卡
          3. 未命中 → **LLM 工具路由（流式版 `_stream_via_tools`）**，与非流式同路径
          4. 路由不可用 → 带会话语境的 LLM 闲聊流式

        先前「流式只走关键词表」的分叉，会让表里没有的说法在两条路径上表现不一致：
        实测「…帮我入库」在流式下被判成 general，丢掉商品名去编通用市场分析。

        Yields:
            文本片段 / progress / meta 事件（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        # 0. 绑定会话 ID + **已校验的**店铺 ID
        #    （工具路由里的 tools.py 要读回它们才能找到会话状态与写库归属）
        self._bind_context(context_id, shop_id)

        # 1. 入库槽位续填优先：上一轮追问过「还差什么」，本轮回答直接当槽位填充。
        #    少了这一步，「多轮补齐」就无从进行 —— 用户回「就那个加湿器」会被判成 general。
        if self._session(context_id).get("pending_save"):
            resumed = await self._resume_pending_save(query, context_id, shop_id)
            if resumed is not None:
                yield self._compose_reply(resumed)
                return

        # 2. 关键词表命中结构化意图 → 直接执行
        intent = await self._classify_intent(query)
        if intent in ("blue_ocean", "profit", "pain_points", "competitor", "save_candidate"):
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析…"))
            result = await self._process_query(query, context_id, intent, shop_id)
            yield result.content
            # 结构化载荷随流下发：前端据此在**同一列**（对话消息内）渲染「结论卡」，
            # 并写入「最近结果」槽（清空会话后仍可找回）。
            # 注意：content 已自带完整结论清单，即便前端不认 display_type 也能读懂；
            # meta 只是把同一份结论的**结构化形态**补上，属于增强而非依赖。
            # 追问/报错类结果（含 error 键）不出卡——那不是结论，弹卡反而制造噪音。
            # 入库类结果同样不出卡：它是「动作回执」不是「分析结论」，
            # 出卡会污染「最近结果」槽（把刚存进库的商品卡顶掉）。
            _META_SKIP_TYPES = {"candidate_saved", "candidate_save_failed", "general_response"}
            is_conclusive = (
                isinstance(result.data, dict)
                and not result.data.get("error")
                and result.data.get("type") not in _META_SKIP_TYPES
            )
            if result.data and is_conclusive:
                yield {
                    "event": "meta",
                    "data": {
                        "display_type": result.display_type or "general",
                        "data": result.data,
                    },
                }
            return

        # 3/4. 未命中关键词表 → 与非流式同一条 LLM 工具路由（内部已含闲聊兜底）
        async for chunk in self._stream_via_tools(query, context_id):
            yield chunk

    # ====== 工具函数（供 LLM 调用）======

    async def _tool_search_blue_ocean(self, category: str) -> List[BlueOceanOpportunity]:
        """工具：搜索蓝海品类（category 留空 = 全类目扫描）"""
        scope = f"{category.strip()}类的" if (category or "").strip() else ""
        result = await self._analyze_blue_ocean(f"帮我找{scope}蓝海机会")
        return [BlueOceanOpportunity(**opp) for opp in result["opportunities"]]

    async def _tool_analyze_profit(self, asin: str, cost_price: float = None) -> ProfitAnalysis:
        """工具：分析 SKU 利润"""
        query = f"分析 {asin} 的利润"
        if cost_price:
            query += f"，采购成本 ${cost_price}"
        result = await self._analyze_profit(query)
        return ProfitAnalysis(**result["analysis"])

    async def _tool_extract_pain_points(self, asin: str) -> PainPointAnalysis:
        """工具：提取产品痛点"""
        result = await self._analyze_pain_points(f"分析 {asin} 的用户痛点")
        return PainPointAnalysis(**result["analysis"])

    async def _tool_compare_competitors(self, asins: List[str]) -> List[CompetitorAnalysis]:
        """工具：对比竞品"""
        result = await self._analyze_competitors(f"对比这些产品: {', '.join(asins)}")
        return [CompetitorAnalysis(**c) for c in result["competitors"]]

    async def _tool_get_keyword_data(self, keyword: str) -> KeywordData:
        """工具：获取关键词数据"""
        return await self.adapter.get_keyword_data(keyword)

    async def _tool_search_products(self, query: str) -> List[ProductData]:
        """工具：搜索产品"""
        return await self.adapter.search_products(query)

    async def _tool_save_candidate(self, asin: str, source_keyword: str = "") -> dict:
        """
        工具：把商品写入候选选品库。

        只接受**明确的 ASIN**——LLM 无法可靠地指代「上一轮结果里的第几个」，
        与其让它猜，不如强制它先拿到 ASIN（它可以先调 analyze_blue_ocean 取到）。
        """
        query = f"把 {asin} 加入选品库"
        if source_keyword:
            query += f"，来源机会词 {source_keyword}"
        # 会话 ID 与店铺 ID 都从 ContextVar 取回（工具入参由 LLM 生成，塞不进去）。
        # 两者都由 `_bind_context()` 在**入口处**用已校验的值写入。
        return await self._save_candidate(
            query,
            context_id=_current_context_id.get(),
            shop_id=_current_shop_id.get(),
        )

    # ====== 内部辅助方法 ======

    @staticmethod
    def _extract_category(query: str) -> Optional[str]:
        """从查询中提取类目"""
        categories = {
            "厨房": "kitchen", "家居": "home", "电子": "electronics",
            "户外": "outdoor", "运动": "sports", "宠物": "pet",
            "美妆": "beauty", "办公": "office", "母婴": "baby",
            "服装": "clothing", "玩具": "toys", "园艺": "garden",
        }
        for cn, en in categories.items():
            if cn in query or en in query.lower():
                return en
        return None

    @staticmethod
    def _generate_search_keywords(category: Optional[str]) -> List[str]:
        """
        生成搜索关键词列表

        Args:
            category: 平台英文类目标识；None / 未收录的类目 → 全类目高潜关键词

        Returns:
            关键词列表
        """
        keyword_templates = {
            "kitchen": ["coffee grinder", "portable blender", "air fryer accessories"],
            "home": ["desk organizer", "storage bins", "led strip lights"],
            "electronics": ["wireless charger", "bluetooth speaker", "usb hub"],
            "outdoor": ["camping gear", "solar lights", "garden tools"],
            "sports": ["yoga mat", "resistance bands", "water bottle"],
            "pet": ["automatic feeder", "cat tree", "dog harness"],
        }
        base = keyword_templates.get(category) if category else None
        if not base:
            # 未识别出具体类目（或类目未收录）→ 全类目高潜关键词，
            # 而不是原先的 general 泛化词表（那会走随机估算，分数不可信）
            return list(_TRENDING_KEYWORDS)
        # 添加修饰词（base 已以该修饰词开头时跳过，否则会拼出 "portable portable blender"）
        modifiers = ["portable", "smart", "mini", "professional", "premium"]
        expanded = [
            f"{m} {b}" for m in modifiers[:2] for b in base[:2] if not b.startswith(m)
        ]
        return base + expanded

    @staticmethod
    def _calculate_opportunity_score(keyword_data: KeywordData) -> float:
        """
        计算机会评分（0-100）

        公式：
        score = (search_volume_factor * 40) +
               (low_competition_factor * 35) +
               (trend_factor * 25)
        """
        # 搜索量因子（对数缩放）
        import math
        if keyword_data.search_volume > 0:
            sv_normalized = min(math.log10(keyword_data.search_volume + 1) / 5, 1)
        else:
            sv_normalized = 0
        sv_score = sv_normalized * 40

        # 低竞争因子（竞争越低越好）
        comp_score = (1 - keyword_data.competition) * 35

        # 趋势因子
        trend_scores = {"rising": 25, "stable": 15, "declining": 0}
        trend_score = trend_scores.get(keyword_data.trend_direction, 15)

        return round(sv_score + comp_score + trend_score, 1)

    @staticmethod
    def _generate_reason(keyword_data: KeywordData) -> str:
        """生成推荐理由"""
        reasons = []

        if keyword_data.trend_direction == "rising":
            reasons.append(f"搜索量呈上升趋势 (+{keyword_data.search_volume:,}/月)")

        if keyword_data.competition < 0.5:
            reasons.append(f"竞争度较低 ({keyword_data.competition:.0%})")

        if keyword_data.search_volume > 20000:
            reasons.append("市场需求充足")

        if keyword_data.suggested_bid and keyword_data.suggested_bid < 1.5:
            reasons.append(f"广告成本低 (${keyword_data.suggested_bid:.2f})")

        return "；".join(reasons) if reasons else "综合指标表现良好"

    @staticmethod
    def _estimate_price_range(category: str) -> str:
        """估算建议售价区间"""
        ranges = {
            "kitchen": "$15-$45", "home": "$12-$35", "electronics": "$20-$80",
            "outdoor": "$18-$55", "sports": "$15-$40", "pet": "$20-$60",
        }
        return ranges.get(category, "$15-$50")

    @staticmethod
    def _estimate_margin(competition: float) -> str:
        """估算利润率"""
        if competition < 0.4:
            return "35%-50%"
        elif competition < 0.7:
            return "25%-35%"
        else:
            return "15%-25%"

    @staticmethod
    def _extract_product_info(query: str) -> dict:
        """从查询中提取产品信息"""
        info = {}

        # 尝试提取价格（`$29.99` / `售价 29.99` / `价格 29.99` 都认）
        import re
        prices = re.findall(r'(?:\$|售价|价格|定价)\s*(\d+(?:\.\d+)?)', query)
        if prices:
            info["price"] = float(prices[0])

        # 尝试提取 ASIN
        asin_match = re.search(_ASIN_RE, query)
        if asin_match:
            info["asin"] = asin_match.group().upper()
        else:
            # 尝试提取产品名称（简化处理）
            info["name"] = query.replace("分析", "").replace("利润", "").strip()[:50]

        return info

    @staticmethod
    def _extract_asin(query: str) -> Optional[str]:
        """提取单个 ASIN"""
        import re
        match = re.search(_ASIN_RE, query)
        return match.group().upper() if match else None

    @staticmethod
    def _extract_multiple_asins(query: str) -> List[str]:
        """提取多个 ASIN"""
        import re
        return [a.upper() for a in re.findall(_ASIN_RE, query)]

    # 中文数字（用于解析「第一个 / 第 2 个」这类序数指代）
    _CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    # 英文「动作/指令」词：出现它们**不代表**用户点名了商品。
    # 若不过滤，「add this to candidate library」会被判成「点名了商品但池里没匹配上」→ 误追问。
    _SAVE_ACTION_WORDS = {
        "add", "save", "insert", "put", "into", "to", "my", "this", "that", "it",
        "please", "candidate", "candidates", "library", "pool", "list", "collection",
        "item", "items", "product", "products", "cart", "wishlist", "new",
    }

    @classmethod
    def _extract_ordinal(cls, query: str) -> Optional[int]:
        """
        从查询里抽「第几个」，返回 **0-based** 下标；没写返回 None。

        支持「第 1 个 / 第2个 / 第一个 / 第一款 / top1」等说法，
        供「把第 N 个加进选品库」定位目标商品。
        """
        import re

        m = re.search(r"第\s*([0-9]+|[一二两三四五六七八九十])\s*(?:个|款|条|名|项)?", query)
        if m:
            raw = m.group(1)
            n = int(raw) if raw.isdigit() else cls._CN_NUM.get(raw)
            if n and n >= 1:
                return n - 1

        m2 = re.search(r"top\s*([0-9]+)", query, re.IGNORECASE)
        if m2:
            n = int(m2.group(1))
            if n >= 1:
                return n - 1

        return None

    @staticmethod
    def _generate_improvement_suggestions(pain_points: List[dict]) -> List[str]:
        """基于痛点生成改进建议"""
        suggestions = []
        pain_mapping = {
            "电池续航不足": "开发长续航版本或支持快充",
            "连接不稳定": "优化蓝牙/WiFi模块，强调稳定连接",
            "质量问题": "提升材质和工艺，增加质保期",
            "APP问题": "重构 APP，简化操作流程",
            "缺少功能": "调研用户需求，补充核心功能",
            "使用困难": "优化产品设计，提供详细教程",
            "速度慢": "升级硬件配置，提升性能",
            "性价比低": "优化供应链降低成本，或提升附加值",
        }

        seen = set()
        for pp in pain_points[:5]:
            pain = pp["pain_point"]
            if pain in pain_mapping and pain not in seen:
                suggestions.append(pain_mapping[pain])
                seen.add(pain)

        return suggestions[:4]  # 最多返回4条建议

    async def _process_query(
        self,
        query: str,
        context_id: str = None,
        intent: str = None,
        shop_id: Optional[str] = None,
    ) -> AgentResponse:
        """处理查询（内部方法）。

        `intent` 由调用方传入时跳过重复分类 —— `invoke`/`stream_chat` 已经判过一次，
        再判一次纯属浪费；而且两条路径必须落在**同一个** intent 上。
        """
        if intent is None:
            intent = await self._classify_intent(query)

        if intent == "blue_ocean":
            result = await self._analyze_blue_ocean(query, context_id)
        elif intent == "profit":
            result = await self._analyze_profit(query)
        elif intent == "pain_points":
            result = await self._analyze_pain_points(query)
        elif intent == "competitor":
            result = await self._analyze_competitors(query)
        elif intent == "save_candidate":
            result = await self._save_candidate(query, context_id, shop_id)
        else:
            result = await self._general_chat(query)

        return AgentResponse(
            content=self._compose_reply(result),
            data=result,
            display_type=result.get("type", "general"),
        )

    # 趋势英文标识 → 中文（面向老板的文案不出现 rising/stable）
    _TREND_CN = {"rising": "上升", "up": "上升", "stable": "平稳", "flat": "平稳", "declining": "下滑", "falling": "下滑", "down": "下滑"}

    @classmethod
    def _format_blue_ocean_reply(cls, result: dict) -> str:
        """
        蓝海结果 → **自带清单**的正文。

        `summary` 只报汇总数，答不了老板真正问的「有哪些」，所以正文必须逐条列出。

        主列表列的是**商品**而不是关键词：
          - 商品有 ASIN / 售价 / 月销 / ROI，能直接对比、直接入库；
          - 关键词只是中间产物（「往哪个方向找」），且**无法入库**
            （候选库以 asin 为核心标识）。
        词没有消失，而是降级为商品的**来源标注**（连同该词的市场层指标）。
        商品池无匹配时才降级回词清单。
        """
        products = result.get("products") or []
        opportunities = result.get("opportunities") or []
        summary = result.get("summary") or ""

        # 去掉「（已列出高潜 Top N）」这类空承诺——下面真的会列出来
        overview = summary.split("（已列出")[0].rstrip("，,。 ") + "："

        if products:
            lines = [overview, ""]
            for idx, p in enumerate(products, 1):
                trend = cls._TREND_CN.get(
                    (p.get("keyword_trend") or "").lower(), p.get("keyword_trend") or "—"
                )
                competition = p.get("keyword_competition")
                competition_text = (
                    f"{competition:.0%}" if isinstance(competition, (int, float)) else "—"
                )
                roi = p.get("roi") or p.get("roi_estimated") or 0
                lines.append(
                    f"{idx}. **{p.get('title') or '未命名商品'}**（{p.get('asin') or '—'}）"
                )
                lines.append(
                    f"   - 售价 ${float(p.get('price') or 0):.2f}"
                    f" ｜ 月销 {int(p.get('estimated_monthly_sales') or 0):,}"
                    f" ｜ 评论 {int(p.get('review_count') or 0):,}"
                    f" ｜ 预估 ROI {roi}%"
                )
                lines.append(
                    f"   - 来源机会词：{p.get('source_keyword') or '—'}"
                    f"（月搜索 {int(p.get('keyword_search_volume') or 0):,}"
                    f" ｜ 竞争度 {competition_text} ｜ 趋势 {trend}）"
                )
            lines += ["", "要入库直接说「把第 1 个加进选品库」；换类目说「找厨房用品的蓝海机会」。"]
            return "\n".join(lines)

        if not opportunities:
            return summary or "这次没跑出达标的蓝海机会，建议换个类目或放宽筛选条件。"

        # ===== 降级：商品池无匹配，只能给词方向 =====
        lines = [overview, ""]
        for idx, opp in enumerate(opportunities, 1):
            name = opp.get("category") or "未命名"
            score = opp.get("opportunity_score") or 0
            volume = opp.get("search_volume") or 0
            competition = opp.get("competition")
            trend = cls._TREND_CN.get((opp.get("trend") or "").lower(), opp.get("trend") or "—")
            competition_text = f"{competition:.0%}" if isinstance(competition, (int, float)) else "—"

            lines.append(
                f"{idx}. **{name}** ｜ 机会分 {score:.0f} ｜ 月搜索 {volume:,} "
                f"｜ 竞争度 {competition_text} ｜ 趋势 {trend}"
            )
            if opp.get("reason"):
                lines.append(f"   - 理由：{opp['reason']}")
            if not opp.get("matched_count"):
                lines.append("   - 商品池暂无匹配商品，可先用这个词去找货源")

        lines += ["", "想看某个类目的更多细节，可以直接说「找厨房用品的蓝海机会」。"]
        return "\n".join(lines)

    @classmethod
    def _compose_reply(cls, result: dict) -> str:
        """
        把分析结果压成给老板看的一段话。

        **绝不用 `json.dumps(result)` 当正文**——那会把内部结构原样丢给用户，
        实测出现过 `{"error":"请提供至少 2 个产品 ASIN 进行对比"}` 这种裸 JSON。
        """
        if result.get("type") == "blue_ocean_analysis":
            # 蓝海类结论「说有几个」不够，必须「列出有哪些」
            return cls._format_blue_ocean_reply(result)
        if result.get("summary"):
            return result["summary"]
        if result.get("response"):
            # _general_chat 的正文（能力引导文案）
            return result["response"]
        if result.get("error"):
            # soft_error 标记的是「追问 / 用户主动取消」这类**对话的正常步骤**，
            # 文案本身已是人话；套上「这次没跑通」会把一次正常交互说成事故。
            if result.get("soft_error"):
                return result["error"]
            return f"这次没跑通：{result['error']}"
        return "分析已完成。"

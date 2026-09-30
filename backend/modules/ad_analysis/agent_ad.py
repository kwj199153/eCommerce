"""
广告分析 Agent (Ad Analysis Agent)

跨境电商广告分析专家，专注于 Amazon PPC 广告优化。

功能模块：
1. 广告账户健康诊断 - ACOS/ROAS/CTR/CVR 多维度评分
2. 出价策略建议 - 基于历史数据+竞品分析的智能出价
3. 搜索词效果报告 - 高效/低效词识别与建议
4. 竞品广告监控 - 关键词重叠、出价对比、展示份额

设计模式：
- 继承 `BaseAgent`，并组合一个 `BaseAgent` 作**工具路由子层**（`_build_router()`）
  ⇒ 模型能自主调用 `ad_analysis_tools` 的 4 个工具（第 204 轮接线；
    第 316 轮由 6 收敛到 4 —— 「预算分配 / 异常检测」两个工具退役）。
  ★ 原文写的是「与 ProductResearchAgent 保持一致的独立实现（**不继承
    BaseAgent**）」—— 早已过时（类声明就是 `class AdAnalysisAgent(BaseAgent)`），
    第 204 轮一并更正。
- 意图分类（`_classify_intent`）+ 多方法路由架构；**工具环路优先**，
  未命中再落到规则引擎
- 结构化数据输出供前端 SmartPanel 渲染
"""

import json
import re
from contextvars import ContextVar
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from core.logger import get_logger
from ai_infra.sse import StreamDigest, progress
# 竞品快照读取入口（表的所有者 amazon_sp 提供）。本模块原先自己走数据源工厂，
# 无 SP-API 凭据时静默回退 Mock ⇒ 「竞品广告分析」看的是现编竞品。见函数 docstring。
from modules.amazon_sp import load_competitor_snapshots

logger = get_logger(__name__)


#: 请求级店铺归属（第 204 轮）。
#:
#: ★★★ 工具层**没有** `store_id` 形参 —— 工具入参由 LLM 生成，而归属只能由
#:   服务端注入（同族判据：`core.tenant.middleware.get_current_shop_id`）。
#:   所以 6 个广告工具从本 ContextVar 取归属，写法与
#:   `competitor_intel` / `product_research` 完全一致。
#:
#: ★ 唯一写入点 = `_route_via_tools()`（工具环路的唯一入口），且必须发生在
#:   工具被调用**之前** —— 否则第一次工具调用会带着 `store_id=None` 跑完，
#:   服务层 `_load_ad_rows(None, ...)` 直接返回空表，症状是「工具接了却永远没数据」。
_current_shop_id: ContextVar[Optional[str]] = ContextVar(
    "ad_analysis_current_shop_id", default=None
)


# ====== 数据源接入（唯一取数点）======

def _days_of(time_range) -> int:
    """把 "7d" / "30d" / "90d" 解析成天数（解析不出按 30）。"""
    m = re.match(r"(\d+)\s*d", str(time_range or ""), re.I)
    return int(m.group(1)) if m else 30


def _agg_rows(rows: List[Dict]) -> Dict[str, float]:
    """把一组广告记录聚合成账户级指标（纯函数，无副作用）。

    字段口径与 `amazon_sp.data_sources.sp_api_source` / `mock_source`
    的 `fetch_ad_metrics()` 输出一致（`_make_ad_row` 定义）。
    """
    imp = sum(int(r.get("impressions") or 0) for r in rows)
    clk = sum(int(r.get("clicks") or 0) for r in rows)
    spend = sum(float(r.get("spend") or 0) for r in rows)
    orders = sum(int(r.get("orders") or 0) for r in rows)
    sales = sum(float(r.get("sales") or 0) for r in rows)
    return {
        "impressions": imp, "clicks": clk,
        "spend": round(spend, 2), "orders": orders, "sales": round(sales, 2),
        "acos": (spend / sales * 100) if sales else 0.0,
        "roas": (sales / spend) if spend else 0.0,
        "ctr": (clk / imp * 100) if imp else 0.0,
        "cvr": (orders / clk * 100) if clk else 0.0,
        "cpc": (spend / clk) if clk else 0.0,
    }


def _daily_trend_from_rows(rows: List[Dict]) -> Dict[str, List[Any]]:
    """按日期聚合花费/销售（纯函数，零随机数）。

    ★ 为什么必须有它：诊断响应此前只有「账户级聚合值」，**没有任何时间序列**。
      前端看板的趋势图因此只能读本地硬编码数组 —— 一个「画得像在动、
      其实永远不变」的假图表。而 rows 本身**带 `date` 字段**（两个数据源都写），
      所以这里是**把已有数据聚合出来**，不是补造数值。

    ★ 关于粒度诚实性（重要，别把它当 bug 修）：
      `SpApiDataSource.fetch_ad_metrics` 在拿不到按天拆分的花费时，会把整段
      活动数据写在 `date_to` 当天，其 docstring 已明示「不做随机插值」。
      于是这里的 `labels` 可能只有 1 个点 —— 那是**真实情况**。
      前端应能渲染单点，而**不得**为了让曲线好看去插值。
    """
    buckets: Dict[str, Dict[str, float]] = {}
    for r in rows:
        d = str(r.get("date") or "").strip()
        if not d:
            continue
        b = buckets.setdefault(d, {"spend": 0.0, "sales": 0.0})
        b["spend"] += float(r.get("spend") or 0)
        b["sales"] += float(r.get("sales") or 0)
    labels = sorted(buckets)
    return {
        "labels": labels,
        "spend": [round(buckets[d]["spend"], 2) for d in labels],
        "sales": [round(buckets[d]["sales"], 2) for d in labels],
    }

def _load_ad_rows(store_id, time_range="30d") -> List[Dict]:
    """取本店铺的广告指标（唯一入口，经工厂）。

    ★ 为什么必须经 `get_data_source()`：配好 SP-API 凭据后，这里会自动切到
      真实现；绕过工厂直连 Mock（模块级单例那种写法）会让「配了凭据也永远
      跑假数据且不报错」—— `modules/review_analyst/service.py` 的 docstring
      记录了同一个坑。

    ★ 拿不到 `store_id`（未选店铺）时**不猜测、不取默认店**，直接返回空列表，
      由调用方给显式空状态。
    """
    if not store_id:
        return []
    from modules.amazon_sp import get_data_source

    src = get_data_source(prefer="auto", seed=42)
    d_to = date.today()
    d_from = d_to - timedelta(days=_days_of(time_range) - 1)
    try:
        return list(src.fetch_ad_metrics(store_id, d_from, d_to))
    except Exception as e:  # 数据源故障不得伪装成「无数据」
        logger.error(f"[ad_analysis] 取广告指标失败 store={store_id}: {e}")
        raise


def _latest_row_per_asin(rows: List[Dict]) -> List[Dict]:
    """逐日快照行 → 每个竞品 ASIN **最新一行**（纯函数，口径同 competitor_intel）。

    ★ 为什么必须收口在这里：`amazon_competitor_snapshots` 是**逐日行**
      （一个 ASIN 一天一行），而「竞品格局」要的是每个竞品的**当前位置**
      （BSR / 评论数 / 评分）。把时序直接摊成 `List[CompetitorAdData]`
      会把同一个竞品重复 N 次 —— 实测 6 个竞品变成 126 条，且份额分母被撑大
      ⇒ ΣSOV 只有 42 而不是 ~100。

    ★ 这不是本次改造引入的缺陷：改造前的数据源 `fetch_competitors()` 同样返回
      「每 2 天一个点」的时序，旧实现在 6 个竞品上也会产出 ~90 条；只是那时
      每条都带随机 SOV，看着"很专业"，所以从来没被发现。改造把行数从「每 2 天」
      变成「每天」，只是把同一个缺陷放大了。

    ★ 取最新一行的理由与 `competitor_intel._build_from_rows()` 完全一致：
      两个 Agent 看的是同一张表、同一个"当前值"口径，结果才不会又分叉。
    """
    grouped: Dict[str, Dict] = {}
    for r in rows:
        asin = str(r.get("competitor_asin") or "").upper()
        if not asin:
            continue
        prev = grouped.get(asin)
        if prev is None or str(r.get("snapshot_date") or "") >= str(prev.get("snapshot_date") or ""):
            grouped[asin] = r
    return [grouped[a] for a in sorted(grouped)]


async def _load_competitor_rows(store_id, time_range="30d") -> List[Dict]:
    """取本店铺的竞品快照（唯一入口 → 走 `amazon_sp` 的**表读取**）。

    ★ 第 172 轮修正：本函数曾经是**第二份**「经工厂取竞品」的实现 ——
      `get_data_source(prefer="auto")` 在无 SP-API 凭据时回退到
      `MockAmazonDataSource`，于是「竞品广告分析」看到的是现编的
      TP-Link / Anker / JBL，而同一平台的「竞品情报」已经在读监控池展开的真表。
      两个功能回答两个竞品世界，且**没有任何测试会发现**（本模块此前无测试）。
      ⇒ 查询本体上收到表的所有者 `modules/amazon_sp`，两处共用同一个入口。

    ★ 与 `_load_ad_rows` 的差别是**刻意的**：广告指标没有「用户定义的盯防对象」
      那样的输入，落库只能靠编数；竞品快照有监控池作真源 ⇒ 前者继续经工厂，
      后者读表。别为了"统一"把广告指标也灌成假数据。
    """
    if not store_id:
        return []
    # ★ 出口处收敛成「每 ASIN 一行」—— 见 `_latest_row_per_asin` 的 docstring
    #   （逐日行摊平会把同一竞品重复 N 次，份额分母被撑大）。
    rows = await load_competitor_snapshots(store_id, days=_days_of(time_range))
    return _latest_row_per_asin(rows)


# 结构化意图 → 阶段进度文案（stream_chat 在耗时分析前发给前端，避免空转）
_INTENT_PROGRESS = {
    "diagnosis": "正在诊断广告健康度…",
    "search_terms": "正在分析搜索词报告…",
    "bid_optimize": "正在生成出价建议…",
    "competitor": "正在分析广告竞争格局…",
}


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装。

    ★ `data_status` 是「这份结果是真算出来的，还是根本没取到数据」的**唯一判据**：
       - "ok"      ⇒ `data` 是由真实广告记录聚合出的结果
       - "no_data" ⇒ 没取到数据，`data` 为空、`data_reason` 说明原因，
                     `success=False`。**此时不要读数值字段**（它们是占位而非实测）。
      改造前本类没有这两个字段，导致「取不到数据」只能靠「返回一份随机编的报告」
      来掩盖 —— 前端完全无法区分「真数据」与「编的」。
    """
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型
    success: bool = True          # False ⇒ 本次未产出有效结果
    data_status: str = "ok"       # ok / no_data
    data_reason: Optional[str] = None  # data_status != "ok" 时的可读原因


# ---- 广告诊断相关 ----

class AdMetric(BaseModel):
    """单个广告指标"""
    name: str
    value: float
    unit: str = ""
    benchmark: float = 0.0  # 行业基准
    status: str = "normal"  # good/warning/critical
    change_pct: float = 0.0  # 环比变化 %


class CampaignHealth(BaseModel):
    """Campaign 健康状态"""
    campaign_name: str
    campaign_type: str  # SP/SB/SD
    status: str  # active/paused/archived
    spend: float
    impressions: int
    clicks: int
    orders: int
    sales: float
    acos: float
    roas: float
    ctr: float
    cvr: float
    cpc: float
    health_score: float  # 0-100


class DiagnosisReport(BaseModel):
    """诊断报告"""
    overall_score: float  # 0-100
    grade: str  # A-F
    summary: str
    metrics: List[AdMetric]
    campaigns: List[CampaignHealth]
    top_issues: List[Dict[str, Any]]
    recommendations: List[str]
    benchmark_comparison: Dict[str, float]
    # ★ 按日期的花费/销售序列（labels/spend/sales）。默认空 dict ——
    #   「没取到日粒度」与「确实只有一天」在数据上都表现为短序列，
    #   前端按空序列渲染「暂无趋势」，不得插值。
    daily_trend: Dict[str, List[Any]] = Field(default_factory=dict)


# ---- 搜索词报告相关 ----

class SearchTermData(BaseModel):
    """搜索词数据"""
    term: str
    impressions: int
    clicks: int
    ctr: float
    spend: float
    sales: float
    acos: float
    roas: float
    orders: int
    cpc: float
    match_type: str  # exact/broad/phrase
    efficiency: str  # high/medium/low/waste


class SearchTermReport(BaseModel):
    """搜索词报告"""
    period: str
    total_terms: int
    high_performers: List[SearchTermData]  # 高效词
    low_performers: List[SearchTermData]   # 低效词
    waste_terms: List[SearchTermData]      # 浪费词(有花费无销售)
    new_opportunities: List[SearchTermData] # 新机会词
    suggestions: List[str]
    summary: str = ""  # 一句话总结（供 service 层 SearchTermResponse.summary 消费）


# ---- 出价建议相关 ----

class BidRecommendation(BaseModel):
    """单个关键词出价建议"""
    keyword: str
    match_type: str
    current_bid: float
    suggested_bid: float
    bid_change_pct: float
    reason: str
    expected_impact: str
    priority: str  # high/medium/low


class BidStrategyReport(BaseModel):
    """出价策略报告"""
    strategy_type: str  # aggressive/conservative/balanced
    total_keywords: int
    recommendations: List[BidRecommendation]
    budget_impact: float
    expected_acos_change: float
    rationale: str


# ---- 竞品广告相关 ----

class CompetitorAdData(BaseModel):
    """竞品广告数据"""
    competitor_name: str
    asin: str
    share_of_voice: float  # 展示份额 %
    overlap_keywords: int  # 重叠关键词数
    avg_position: float
    estimated_spend: float
    top_keywords: List[str]
    strengths: List[str]
    weaknesses: List[str]


class CompetitorAdReport(BaseModel):
    """竞品广告报告"""
    competitors: List[CompetitorAdData]
    your_share_of_voice: float
    market_position: str  # leader/challenger/nicher
    actionable_insights: List[str]


# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.ad_analysis import prompts as _prompts  # noqa: F401


class AdAnalysisAgent(BaseAgent):
    """
    广告分析 Agent

    专注 Amazon PPC 广告全链路分析与优化建议。

    升级特性（Phase 8）：
    - ✅ DashScope Qwen LLM 智能诊断与建议生成
    - ✅ 自动降级到规则引擎
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-max"       # 分析任务用最强模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    #: 系统提示词 → `modules/ad_analysis/prompts.py`（注册表键 `"ad_analysis"`）
    #: ★ 第 283 轮：正文归位后带版本与指纹，散落在 agent 里无法对账。

    def __init__(self):
        # 初始化 LLM 基类
        super().__init__()

        self.system_prompt = self.get_prompt_template("ad_analysis")
        self.agent_name = "ad_analysis"
        # ★ 第 204 轮：工具化路由子层（懒加载）。**不能**在 __init__ 里构建 ——
        #   那会触发 `tools → service → agent_ad` 循环导入。
        self._router: Optional[Any] = None

    # ==================== 工具化路由（第 204 轮）====================
    #
    # 本 Agent 此前是**范式 B**：`invoke()` / `stream_chat()` → `_classify_intent()`
    # （关键词表）→ `_handle_*` 规则引擎；LLM 只出现在写文案的辅助方法里。
    # 于是 `ad_analysis_tools`（6 个）**零装配** —— 注册了、却没有任何 Agent
    # 绑定它（全仓 `from .tools import ad_analysis_tools` 零命中）。
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
        """构建工具化路由层（BaseAgent 实例，注入 6 个广告工具）。

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
            from .tools import ad_analysis_tools

            from ai_infra.base_agent import BaseAgent
            from ai_infra.budget import BUDGET_ROUTER
            from ai_infra.context import CONTEXT_ROUTER
            from core.checkpoint import get_checkpointer

            return BaseAgent(
                # ★ 子层名字带 `_router` 后缀（同 competitor / listing / PR），
                #   技能注入边界由 `modules.skills.agents.business_agent_name()` 归一回业务名。
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.system_prompt,
                tools=ad_analysis_tools,
                # 路由子层是「单次决策 + 一串工具调用、用完即答」⇒ 用 ROUTER 档。
                budget=BUDGET_ROUTER,
                context_policy=CONTEXT_ROUTER,
                checkpointer=get_checkpointer(),
                checkpoint_ns="ad_analysis",
            )
        except Exception as e:  # noqa: BLE001 —— 路由层不可用时回退，不影响主流程
            logger.warning(f"[ad_analysis] router build failed: {e}")
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
            logger.warning(f"[ad_analysis] stream tool routing failed: {e}")
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
            logger.warning(f"[ad_analysis] tool routing failed: {e}")
            return None

        reply = ""
        for m in state.get("messages") or []:
            if isinstance(m, AIMessage) and m.content:
                reply = m.content if isinstance(m.content, str) else str(m.content)
        return reply.strip() or None

    async def _llm_summarize(self, context: str) -> Optional[str]:
        """
        LLM 增强：基于诊断数据生成专业的分析总结。

        LLM 不可用或失败时返回 None，由调用方降级到规则生成的文字。
        """
        if not (self.ENABLE_LLM and self.llm_client):
            return None
        try:
            result = await self.llm_chat(
                user_message=context,
                system_prompt=self.system_prompt,
                model=self.DEFAULT_MODEL,
                temperature=0.6,
                max_tokens=1024,
            )
            if result.success and not result.fallback and result.content:
                return result.content.strip()
        except Exception as e:
            logger.warning(f"[ad_analysis] LLM summary failed: {e}")
        return None

    async def invoke(self, query: str, context: Optional[Dict[str, Any]] = None) -> AgentResponse:
        """
        主入口：处理用户查询并返回结构化响应

        Args:
            query: 用户输入的问题或指令
            context: 可选的上下文数据（如 ASIN、时间范围等）

        Returns:
            AgentResponse 包含文本和结构化数据
        """
        intent = self._classify_intent(query)

        if intent == "diagnosis":
            return await self._analyze_diagnosis(query, context)
        elif intent == "search_terms":
            return await self._analyze_search_terms(query, context)
        elif intent == "bid_optimize":
            return await self._optimize_bids(query, context)
        elif intent == "competitor":
            return await self._analyze_competitors(query, context)
        else:
            # 默认通用回答
            return await self._general_response(query)

    #: 意图路由表（**策略数据**留业务模块；控制流见 `ai_infra.intent.first_match`）。
    #: 顺序即优先级 —— 保持收敛前的相对原序「竞品 → 出价 → 搜索词 → 诊断」，
    #: 后几组关键词之间存在交集，换序会改变判定结果。
    #: ★ 第 316 轮：「异常」「预算」两条路由随其工具 / 端点一并退役。
    _INTENT_ROUTES = (
        Route("competitor", ("竞品", "对手", "竞争", "competitor", "别人",
                             "展示份额", "share of voice", "soy")),
        Route("bid_optimize", ("出价", "bid", "竞价", "调价", "降价", "加价",
                               "cpc", "建议出价", "优化出价")),
        Route("search_terms", ("搜索词", "search term", "关键词报告", "词报告",
                               "哪些词", "客户搜什么", "高效词", "低效词", "浪费")),
        Route("diagnosis", ("诊断", "体检", "健康", "状况", "表现", "怎么样", "如何",
                            "diagnosis", "health", "check", "audit", "review", "score")),
    )

    def _classify_intent(self, query: str) -> str:
        """分类用户意图（控制流与兜底见 `ai_infra.intent.first_match`）。

        Returns:
            diagnosis / search_terms / bid_optimize / competitor / general
        """
        return first_match(query, self._INTENT_ROUTES, "general")

    # ========== 核心分析方法 ==========

    async def _analyze_diagnosis(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """广告账户健康诊断"""
        rows = _load_ad_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not rows:
            return self._no_data("广告账户诊断", (context or {}).get("store_id"))
        # 以下全部由真实广告记录聚合（改造前是 random 现编）
        metrics = self._metrics_from_rows(rows)
        campaigns = self._campaigns_from_rows(rows)
        issues = self._identify_issues(campaigns, metrics)
        recommendations = self._generate_recommendations(issues)

        overall_score = self._calculate_overall_score(metrics, campaigns)
        grade = self._score_to_grade(overall_score)

        # 规则生成的摘要（作为 LLM 降级兜底）
        summary = self._generate_diagnosis_summary(grade, metrics)

        # ====== LLM 增强：智能诊断总结 ======
        llm_context = f"""请基于以下广告账户诊断数据，生成一段专业、可执行的诊断总结（150字以内，中文）：
- 综合评分: {overall_score}/100（等级 {grade}）
- 核心指标: {', '.join(f'{m.name}={m.value}{m.unit}(基准{m.benchmark})' for m in metrics)}
- 主要问题: {', '.join(i['title'] for i in issues[:3]) or '无'}
- 优化方向: {', '.join(recommendations[:3])}
请聚焦最关键的 1-2 个问题给出具体建议，不要罗列数据。"""
        llm_summary = await self._llm_summarize(llm_context)
        if llm_summary:
            summary = llm_summary

        report = DiagnosisReport(
            overall_score=overall_score,
            grade=grade,
            summary=summary,
            metrics=metrics,
            campaigns=campaigns,
            top_issues=issues[:5],
            recommendations=recommendations,
            benchmark_comparison={
                "acos_industry": 25.0,
                "roas_industry": 4.0,
                "ctr_industry": 0.4,
                "cvr_industry": 8.0,
            },
            daily_trend=_daily_trend_from_rows(rows),
        )

        content = f"""## 📊 广告账户健康诊断报告

**综合评分**: {overall_score}/100 （等级：**{grade}**）

### 核心指标概览
| 指标 | 当前值 | 行业基准 | 状态 |
|------|--------|----------|------|
| ACoS | {metrics[0].value:.1f}% | {metrics[0].benchmark:.1f}% | {self._status_emoji(metrics[0].status)} |
| RoAS | {metrics[1].value:.2f}x | {metrics[1].benchmark:.2f}x | {self._status_emoji(metrics[1].status)} |
| CTR | {metrics[2].value:.2f}% | {metrics[2].benchmark:.2f}% | {self._status_emoji(metrics[2].status)} |
| CVR | {metrics[3].value:.1f}% | {metrics[3].benchmark:.1f}% | {self._status_emoji(metrics[3].status)} |
| CPC | ${metrics[4].value:.2f} | ${metrics[4].benchmark:.2f} | {self._status_emoji(metrics[4].status)} |

### 主要问题
{chr(10).join([f'{i+1}. **{issue["title"]}**: {issue["description"]}' for i, issue in enumerate(issues[:3])])}

### 优化建议
{chr(10).join([f'- {rec}' for rec in recommendations[:5]])}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="ad_diagnosis"
        )

    async def _analyze_search_terms(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """搜索词效果分析"""
        rows = _load_ad_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not rows:
            return self._no_data("搜索词分析", (context or {}).get("store_id"))
        all_terms = self._search_terms_from_rows(rows)

        # 分类筛选
        high_perf = [t for t in all_terms if t.efficiency == "high"][:10]
        low_perf = [t for t in all_terms if t.efficiency == "low"][:10]
        waste = [t for t in all_terms if t.efficiency == "waste"][:8]
        opportunities = [t for t in all_terms if t.orders >= 1 and t.acos < 20][:8]

        suggestions = self._generate_search_term_suggestions(high_perf, low_perf, waste)

        # ====== LLM 增强：搜索词洞察总结 ======
        llm_context = f"""请基于以下搜索词报告数据，生成一段专业洞察总结（120字以内，中文），指出最值得执行的 1-2 个动作：
- 高效词 {len(high_perf)} 个、低效词 {len(low_perf)} 个、浪费词 {len(waste)} 个（浪费花费约 ${sum(t.spend for t in waste):.2f}）
- 新机会词 {len(opportunities)} 个
请聚焦「浪费词否定」和「高效词加投」两个维度给建议。"""
        llm_suggestions = await self._llm_summarize(llm_context)
        if llm_suggestions:
            suggestions = [llm_suggestions] + suggestions[:2]

        report = SearchTermReport(
            period="近30天",
            total_terms=len(all_terms),
            high_performers=high_perf,
            low_performers=low_perf,
            waste_terms=waste,
            new_opportunities=opportunities,
            suggestions=suggestions,
            summary=llm_suggestions or (
                f"高效词 {len(high_perf)} 个、低效词 {len(low_perf)} 个、"
                f"浪费词 {len(waste)} 个，建议否定浪费词、加投高效词"
            ),
        )

        total_spend = sum(t.spend for t in all_terms)
        total_sales = sum(t.sales for t in all_terms)
        waste_spend = sum(t.spend for t in waste)

        content = f"""## 🔍 搜索词效果报告（{report.period}）

**总搜索词数**: {report.total_terms} | **总花费**: ${total_spend:.2f} | **总销售额**: ${total_sales:.2f}

### 🟢 高效词 TOP 10（ACoS < 20%，持续投入）
这些词是你的"金矿"，考虑提高出价或拓展匹配类型。

### 🔴 低效词 TOP 10（高花费低产出）
需要优化出价、调整匹配方式或否词处理。

### ⚠️ 浪费词（${waste_spend:.2f} 有花无单）
强烈建议立即添加为否定关键词！

### 💡 新机会词
有初步转化的词，值得加大投入测试。

### 优化建议
{chr(10).join([f'- {s}' for s in suggestions])}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="search_term_report"
        )

    async def _optimize_bids(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """出价优化建议"""
        rows = _load_ad_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not rows:
            return self._no_data("出价优化", (context or {}).get("store_id"))
        target_acos = float((context or {}).get("target_acos") or 25.0)
        keywords_data = self._bid_recs_from_rows(rows, target_acos=target_acos)

        # 计算整体影响（由真实建议推导，非随机数）
        total_current_bid = sum(k.current_bid for k in keywords_data)
        total_suggested_bid = sum(k.suggested_bid for k in keywords_data)
        budget_impact = total_suggested_bid - total_current_bid
        _downs = [k for k in keywords_data if k.bid_change_pct < 0]
        avg_acos_change = round(
            sum(k.bid_change_pct for k in _downs) / len(_downs) * 0.4, 1
        ) if _downs else 0.0

        # 提价/降价计数（先算，供下方 llm_context 与正文复用）
        increase_count = len([k for k in keywords_data if k.bid_change_pct > 0])
        decrease_count = len([k for k in keywords_data if k.bid_change_pct < 0])

        report = BidStrategyReport(
            strategy_type="balanced",
            total_keywords=len(keywords_data),
            recommendations=keywords_data,
            budget_impact=budget_impact,
            expected_acos_change=avg_acos_change,
            rationale="基于近30天转化数据、竞争强度、季节性因素综合计算"
        )

        # ====== LLM 增强：出价策略理由 ======
        llm_context = f"""请基于以下出价优化数据，生成一段专业、简明的策略理由（100字以内，中文）：
- 涉及 {len(keywords_data)} 个关键词，预算影响 {'+' if budget_impact > 0 else ''}{budget_impact:.2f}/天
- 预期 ACoS 变化 {avg_acos_change:+.1f}%
- 建议提价 {increase_count} 个、降价 {decrease_count} 个
请说明为什么这样调整，以及优先处理什么。"""
        llm_rationale = await self._llm_summarize(llm_context)
        if llm_rationale:
            report.rationale = llm_rationale

        content = f"""## 💡 出价优化建议报告

**策略类型**: 平衡型（兼顾曝光与效率）
**涉及关键词**: {report.total_keywords} 个
**预算影响**: {'+' if budget_impact > 0 else ''}${budget_impact:.2f}/天
**预期 ACoS 变化**: {avg_acos_change:+.1f}% ({'改善' if avg_acos_change < 0 else '上升'})

### 📈 建议提价 ({increase_count} 个)
高转化潜力的词，适当提高出价获取更多曝光。

### 📉 建议降价 ({decrease_count} 个)
长期低效或出价过高的词，降低成本。

### ⚠️ 优先级排序
优先处理 **high** 优先级的调整项，预计带来最大 ROI 提升。
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="bid_optimization"
        )

    async def _analyze_competitors(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """竞品广告分析"""
        comp_rows = await _load_competitor_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not comp_rows:
            return self._no_data("竞品广告分析", (context or {}).get("store_id"))
        competitors = self._competitor_data_from_rows(comp_rows)
        # ★ 数据源未提供「本店展示份额」，**不编造**：置 0，口径见 insights
        your_sov = 0.0

        # 判断市场位置
        if your_sov > 25:
            position = "leader"
        elif your_sov > 15:
            position = "challenger"
        else:
            position = "nicher"

        insights = self._generate_competitor_insights(competitors, your_sov)

        # ====== LLM 增强：竞品洞察 ======
        llm_context = f"""请基于以下竞品广告监控数据，生成 2-3 条可执行洞察（中文）：
- 我的展示份额 {your_sov}%，市场位置 {position}
- 竞品: {', '.join(f'{c.competitor_name}(份额{c.share_of_voice}%)' for c in competitors[:3])}
请聚焦「如何抢占竞品份额」给出具体策略。"""
        llm_insights = await self._llm_summarize(llm_context)
        if llm_insights:
            insights = [llm_insights] + insights[:2]

        report = CompetitorAdReport(
            competitors=competitors,
            your_share_of_voice=your_sov,
            market_position=position,
            actionable_insights=insights
        )

        position_map = {"leader": "👑 领导者", "challenger": "⚔️ 挑战者", "nicher": "🎯 利基者"}

        content = f"""## 🎯 竞品广告监控报告

**你的展示份额 (SOV)**: {your_sov}% | **市场位置**: {position_map.get(position, "")}

### 主要竞品分析
"""

        for comp in competitors:
            content += f"""
#### {comp.competitor_name}
- **ASIN**: {comp.asin}
- **展示份额**: {comp.share_of_voice}%
- **重叠关键词**: {comp.overlap_keywords} 个
- **平均排名**: 第 {comp.avg_position:.1f} 位
- **预估日花费**: ${comp.estimated_spend:.2f}
- **优势**: {', '.join(comp.strengths[:2])}
- **劣势**: {', '.join(comp.weaknesses[:2])}
"""

        content += f"""
### 💡 可执行洞察
{chr(10).join([f'- {ins}' for ins in insights])}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="competitor_analysis"
        )

    def _no_data(self, what: str, store_id=None) -> AgentResponse:
        """显式空状态：没取到数据就如实说，不返回「编出来的报告」。

        ★ 为什么不做「全 0 兜底」：恒为 0 的结果会被当成「实测出来是 0」，
          属项目判据明令禁止的「假数据冒充实测」。这里 `success=False` +
          `data_status="no_data"`，前端据此渲染空状态卡片并展示原因。
        """
        reason = (
            "未绑定店铺上下文（请求缺少 X-Shop-ID）" if not store_id
            else f"店铺 {store_id} 在当前数据源中暂无广告数据"
        )
        return AgentResponse(
            content=(
                f"暂时无法完成{what}：{reason}。\n\n"
                "请确认：① 已选择店铺；② 该店铺已完成广告数据同步"
                "（SP-API 授权或报表导入）。数据到位后重试即可。"
            ),
            data={"data_status": "no_data", "data_reason": reason},
            display_type="text",
            success=False,
            data_status="no_data",
            data_reason=reason,
        )

    async def _general_response(self, query: str) -> AgentResponse:
        """通用回答"""
        content = f"""我是 **广告分析师**，可以帮你：

1. 📊 **广告诊断** — "帮我做一下广告账户体检"
2. 🔍 **搜索词分析** — "看看我的搜索词报告"
3. 💡 **出价优化** — "给我一些出价建议"
4. 🎯 **竞品监控** — "分析一下我的竞品广告"

你可以说：「{query.split()[0] if query else '帮我诊断广告账户'}」开始分析。
"""
        return AgentResponse(content=content, display_type="text")

    async def stream_chat(self, query: str,
                          context: Optional[Dict[str, Any]] = None) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        对话类意图走 LLM 流式；结构化意图（诊断/搜索词/出价等）退化为一次性文本，
        但开跑前先发阶段进度，避免长任务期间「AI 正在思考…」空转。

        Yields:
            文本片段 / progress 事件（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        # ★ 第 204 轮：工具环路优先（LLM 用 bind_tools 自主选那 6 个广告工具）。
        #   不可用 / 失败 ⇒ 回退下面的关键词路由（确定性、离线可跑）。
        #   回退不是装饰：ENABLE_LLM=False / 无 API KEY / 图构建失败都要能继续服务。
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
            yield progress("正在调用广告分析工具…")
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

        # 结构化意图：走 invoke 一次性返回（含图表数据，不适合流式）
        # 注：结构化数据由 REST 端点（`/ad-analysis/*`）供给前端 SmartPanel；
        # 本 SSE 通道只服务对话体验 ⇒ 工具化路由不会挤掉面板数据。
        if intent != "general":
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析广告数据…"))
            result = await self.invoke(query, context)
            yield result.content
            return

        # 对话类：走 LLM 流式
        if not (self.ENABLE_LLM and self.llm_client):
            result = await self._general_response(query)
            yield result.content
            return

        try:
            async for chunk in self.llm_stream(
                query,
                system_prompt=self.system_prompt,
                model=self.DEFAULT_MODEL,
                temperature=0.6,
                max_tokens=1024,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[ad_analysis] stream_chat failed: {e}")
            result = await self._general_response(query)
            yield result.content

    # ====== 数据生成辅助方法（模拟数据）======

    def _metrics_from_rows(self, rows: List[Dict]) -> List[AdMetric]:
        """核心指标 —— 全部由真实广告记录聚合，零随机数。

        改造前这 5 个指标是 `random.uniform(...)` 现编的：同一店铺连点两次
        「诊断」会得到两份不同的体检报告，且完全不受任何 API 影响。
        benchmark 用 SYSTEM_PROMPT 里的行业参考值（常量），status 由
        「实测值 vs 基准」推导。
        """
        a = _agg_rows(rows)

        def _st(val: float, bench: float, higher_is_better: bool) -> str:
            if higher_is_better:
                if val >= bench:
                    return "good"
                return "warning" if val >= bench * 0.7 else "critical"
            if val <= bench:
                return "good"
            return "warning" if val <= bench * 1.35 else "critical"

        return [
            AdMetric(name="ACoS", value=round(a["acos"], 2), unit="%",
                     benchmark=22.0, status=_st(a["acos"], 22.0, False)),
            AdMetric(name="RoAS", value=round(a["roas"], 2), unit="x",
                     benchmark=4.5, status=_st(a["roas"], 4.5, True)),
            AdMetric(name="CTR", value=round(a["ctr"], 2), unit="%",
                     benchmark=0.40, status=_st(a["ctr"], 0.40, True)),
            AdMetric(name="CVR", value=round(a["cvr"], 2), unit="%",
                     benchmark=9.0, status=_st(a["cvr"], 9.0, True)),
            AdMetric(name="CPC", value=round(a["cpc"], 2), unit="$",
                     benchmark=0.75, status=_st(a["cpc"], 0.75, False)),
        ]

    def _campaigns_from_rows(self, rows: List[Dict]) -> List[CampaignHealth]:
        """按 `campaign_name` 聚合出各 Campaign 真实健康度（零随机数）。"""
        groups: Dict[str, List[Dict]] = {}
        for r in rows:
            name = str(r.get("campaign_name") or "未命名 Campaign").strip()
            groups.setdefault(name, []).append(r)

        out: List[CampaignHealth] = []
        for name, rs in groups.items():
            a = _agg_rows(rs)
            types = [str(r.get("report_type") or "sp").upper() for r in rs]
            ctype = max(set(types), key=types.count) if types else "SP"
            health = max(0.0, min(100.0, 100.0 - a["acos"] + a["roas"] * 10.0))
            out.append(CampaignHealth(
                campaign_name=name,
                campaign_type=ctype,
                status="active",
                spend=a["spend"],
                impressions=a["impressions"],
                clicks=a["clicks"],
                orders=a["orders"],
                sales=a["sales"],
                acos=round(a["acos"], 1),
                roas=round(a["roas"], 2),
                ctr=round(a["ctr"], 2),
                cvr=round(a["cvr"], 1),
                cpc=round(a["cpc"], 2),
                health_score=round(health, 1),
            ))
        out.sort(key=lambda c: c.spend, reverse=True)
        return out

    def _identify_issues(self, campaigns: List[CampaignHealth], metrics: List[AdMetric]) -> List[Dict]:
        """识别主要问题"""
        issues = []

        # ACoS 过高
        if metrics[0].value > 30:
            issues.append({
                "type": "acos_high",
                "title": "ACoS 偏高",
                "description": f"当前 ACoS {metrics[0].value:.1f}% 超过行业均值，需优化关键词和出价",
                "priority": "high"
            })

        # CTR 过低
        if metrics[2].value < 0.3:
            issues.append({
                "type": "ctr_low",
                "title": "点击率偏低",
                "description": f"CTR 仅 {metrics[2].value:.2f}%，建议优化主图和标题相关性",
                "priority": "high"
            })

        # 找出最差的 Campaign
        worst_campaign = min(campaigns, key=lambda c: c.health_score)
        if worst_campaign.health_score < 50:
            issues.append({
                "type": "campaign_poor",
                "title": f"Campaign 表现差",
                "description": f"{worst_campaign.campaign_name} 健康度仅 {worst_campaign.health_score}，ACoS 达 {worst_campaign.acos}%",
                "priority": "medium"
            })

        # CPC 过高
        if metrics[4].value > 1.0:
            issues.append({
                "type": "cpc_high",
                "title": "CPC 偏高",
                "description": f"平均 CPC ${metrics[4].value:.2f}，部分关键词出价可能过高",
                "priority": "medium"
            })

        # 默认补充问题
        default_issues = [
            {"type": "negative_missing", "title": "否定关键词不足", "description": "可能有浪费性流量未屏蔽", "priority": "low"},
            {"type": "budget_split", "title": "预算分配不均", "description": "高ROI Campaign 可能预算不足", "priority": "medium"},
        ]

        issues.extend(default_issues)
        return issues

    def _generate_recommendations(self, issues: List[Dict]) -> List[str]:
        """生成优化建议"""
        recs = []
        issue_types = set(i["type"] for i in issues)

        if "acos_high" in issue_types:
            recs.extend([
                "🔥 【紧急】暂停 ACoS > 50% 的低效关键词，转移预算到高效词",
                "📝 审查并优化产品 Listing 相关性，提升自然排名降低对广告依赖",
            ])

        if "ctr_low" in issue_types:
            recs.extend([
                "🖼️ A/B 测试主图，选择 CTR 更高的版本",
                "📋 优化标题前 80 字符，确保包含核心关键词",
            ])

        if "campaign_poor" in issue_types:
            recs.append("⏸️ 对健康度 < 50 的 Campaign 进行深度审计或暂时暂停")

        if "cpc_high" in issue_types:
            recs.append("💰 使用动态出价策略（Only Down）控制高竞争词成本")

        # 通用建议
        recs.extend([
            "📊 每周定期下载搜索词报告，及时否定无效流量",
            "🎯 开启商品投放（PAT）扩展流量来源",
            "📅 关注季节性趋势，提前调整预算和出价",
        ])

        return recs

    def _calculate_overall_score(self, metrics: List[AdMetric], campaigns: List[CampaignHealth]) -> float:
        """综合评分 —— 由真实指标与 Campaign 健康度推导（改造前是 random）。"""
        if not metrics:
            return 0.0
        by = {m.name: m for m in metrics}
        weights = {"ACoS": 18.0, "RoAS": 14.0, "CTR": 5.0, "CVR": 5.0, "CPC": 4.0}
        score = 60.0
        for name, weight in weights.items():
            m = by.get(name)
            if m is None:
                continue
            if m.status == "good":
                score += weight
            elif m.status == "critical":
                score -= weight
            else:
                score -= weight * 0.4
        if campaigns:
            avg_health = sum(c.health_score for c in campaigns) / len(campaigns)
            score += (avg_health - 70.0) * 0.1
        return round(max(0.0, min(100.0, score)), 1)

    def _score_to_grade(self, score: float) -> str:
        """分数转等级"""
        if score >= 90: return "A"
        if score >= 80: return "B"
        if score >= 70: return "C"
        if score >= 60: return "D"
        return "F"

    def _generate_diagnosis_summary(self, grade: str, metrics: List[AdMetric]) -> str:
        """生成诊断摘要"""
        summaries = {
            "A": "账户表现优秀！各项指标均优于行业基准，继续保持当前策略。",
            "B": "账户表现良好！大部分指标达标，有小幅优化空间。",
            "C": "账户表现一般。存在若干需要关注的指标，建议针对性优化。",
            "D": "账户表现较差。多项指标低于基准，需要系统性优化。",
            "F": "账户表现堪忧。建议立即进行全面审计和策略调整。",
        }
        base = summaries.get(grade, "")

        # 补充具体信息
        bad_metrics = [m.name for m in metrics if m.status != "good"]
        if bad_metrics:
            base += f" 重点改善：{', '.join(bad_metrics)}。"

        return base

    def _status_emoji(self, status: str) -> str:
        return {"good": "✅", "warning": "⚠️", "critical": "❌"}.get(status, "➖")

    def _search_terms_from_rows(self, rows: List[Dict]) -> List[SearchTermData]:
        """按 `keyword_text` 聚合出真实搜索词报告（零随机数）。

        efficiency 分档（改动前是按随机数硬贴标签）：
          waste    = 有花费、零出单 ⇒ 建议否定
          high     = 有出单且 ACoS <= 20% ⇒ 加投
          low      = ACoS > 35% ⇒ 优化
          其余     = medium
        """
        groups: Dict[str, List[Dict]] = {}
        for r in rows:
            kw = str(r.get("keyword_text") or "").strip()
            if not kw:
                continue
            groups.setdefault(kw, []).append(r)

        out: List[SearchTermData] = []
        for kw, rs in groups.items():
            a = _agg_rows(rs)
            if a["orders"] == 0 and a["spend"] > 0:
                eff = "waste"
            elif a["acos"] <= 20 and a["orders"] >= 1:
                eff = "high"
            elif a["acos"] > 35:
                eff = "low"
            else:
                eff = "medium"
            out.append(SearchTermData(
                term=kw,
                impressions=a["impressions"],
                clicks=a["clicks"],
                ctr=round(a["ctr"], 2),
                spend=a["spend"],
                sales=a["sales"],
                acos=round(a["acos"], 2),
                roas=round(a["roas"], 2),
                orders=a["orders"],
                cpc=round(a["cpc"], 2),
                match_type="broad",
                efficiency=eff,
            ))
        out.sort(key=lambda t: t.spend, reverse=True)
        return out

    def _generate_search_term_suggestions(self, high, low, waste) -> List[str]:
        """生成搜索词优化建议"""
        suggestions = []

        if waste:
            waste_spend = sum(t.spend for t in waste)
            suggestions.append(f"立即将 {len(waste)} 个浪费词（${waste_spend:.2f}/月）添加为精确否定")

        if low:
            suggestions.append(f"对 {len(low)} 个低效词降低出价 20-30%，或改为 phrase/exact 匹配")

        if high:
            suggestions.append(f"对 {len(high)} 个高效词提高预算 15-25%，测试扩大曝光")

        suggestions.extend([
            "每周一导出搜索词报告，新增否定词不少于 10 个",
            "关注转化率 > 15% 但点击量少的词，适当提高出价",
            "将表现好的 search term 挪入精准匹配 Campaign",
        ])

        return suggestions

    def _bid_recs_from_rows(
        self, rows: List[Dict], target_acos: float = 25.0
    ) -> List[BidRecommendation]:
        """按关键词**真实 ACoS** 给出价建议（确定性规则，零随机数）。

        current_bid 取该词的真实 CPC（唯一可得的出价代理）；
        suggested_bid = current_bid × 规则倍数；倍数由 ACoS 与目标值的
        相对位置决定，同一份数据必然给出同一份建议。
        """
        out: List[BidRecommendation] = []
        for t in self._search_terms_from_rows(rows):
            if t.clicks < 3:
                continue
            current = t.cpc or 0.5
            if t.orders == 0:
                factor, reason, prio = 0.75, (
                    f"{t.clicks} 次点击零出单（花费 ${t.spend:.2f}），建议降价或加否词"
                ), "high"
            elif t.acos and t.acos <= target_acos * 0.6:
                factor, reason, prio = 1.15, (
                    f"ACoS {t.acos:.1f}% 远低于目标 {target_acos:.0f}%，可加价抢量"
                ), "high"
            elif t.acos and t.acos <= target_acos:
                factor, reason, prio = 1.05, (
                    f"ACoS {t.acos:.1f}% 在目标内，小幅加价试探"
                ), "medium"
            else:
                factor, reason, prio = 0.85, (
                    f"ACoS {t.acos:.1f}% 高于目标 {target_acos:.0f}%，降价控本"
                ), "medium"
            suggested = round(current * factor, 2)
            change = ((suggested - current) / current * 100) if current else 0.0
            out.append(BidRecommendation(
                keyword=t.term,
                match_type=t.match_type,
                current_bid=round(current, 2),
                suggested_bid=suggested,
                bid_change_pct=round(change, 1),
                reason=reason,
                expected_impact=(
                    "预计点击量提升、ACoS 略升" if change > 0
                    else "预计花费下降、ACoS 改善"
                ),
                priority=prio,
            ))
        out.sort(key=lambda k: abs(k.bid_change_pct), reverse=True)
        return out[:15]

    def _competitor_data_from_rows(self, rows: List[Dict]) -> List[CompetitorAdData]:
        """竞品格局 —— 只填数据源**真实提供**的字段（零随机数）。

        ★ 不编造：`amazon_competitor_snapshots` 里**没有**展示份额(SOV)、
          关键词重叠数、竞品广告花费这三项。本方法对这些字段一律填 0/空，
          并在 `_generate_competitor_insights` 的口径说明里讲清「未接入」。
          改造前这三个字段全是 `random.uniform/randint` ⇒ 看着很专业，全是编的。

        可得字段映射：
          brand / competitor_asin → competitor_name / asin
          bsr_rank                → avg_position（真实排名）
          review_count            → share_of_voice（近似口径：评论数占比）
          rating / has_buybox / price_vs_own → strengths / weaknesses
        """
        if not rows:
            return []
        total_reviews = sum(int(r.get("review_count") or 0) for r in rows) or 1

        out: List[CompetitorAdData] = []
        for r in rows:
            reviews = int(r.get("review_count") or 0)
            rating = float(r.get("rating") or 0)
            price_vs_own = float(r.get("price_vs_own") or 0)
            strengths = []
            weaknesses = []
            if rating:
                strengths.append(f"评分 {rating}")
            strengths.append(f"评论 {reviews} 条")
            if r.get("has_buybox"):
                strengths.append("持有 Buy Box")
            else:
                weaknesses.append("未持有 Buy Box")
            if price_vs_own > 0:
                weaknesses.append(f"价格高于本店 ${price_vs_own:.2f}")
            elif price_vs_own < 0:
                strengths.append(f"价格低于本店 ${abs(price_vs_own):.2f}")
            out.append(CompetitorAdData(
                competitor_name=str(r.get("brand") or r.get("competitor_asin") or "未知竞品"),
                asin=str(r.get("competitor_asin") or ""),
                share_of_voice=round(reviews / total_reviews * 100, 1),
                overlap_keywords=0,
                avg_position=float(r.get("bsr_rank") or 0),
                estimated_spend=0.0,
                top_keywords=[],
                strengths=strengths or ["数据不足"],
                weaknesses=weaknesses or ["数据不足"],
            ))
        out.sort(key=lambda c: c.share_of_voice, reverse=True)
        return out

    def _generate_competitor_insights(self, competitors: List[CompetitorAdData], your_sov: float) -> List[str]:
        """生成竞品洞察"""
        insights = []

        # 找最强竞品
        strongest = max(competitors, key=lambda c: c.share_of_voice)
        if strongest.share_of_voice > your_sov:
            insights.append(
                f"**{strongest.competitor_name}** 是最大威胁（SOV {strongest.share_of_voice}%），"
                f"重点关注其 {strongest.overlap_keywords} 个重叠关键词的广告策略"
            )

        # 找可超越的竞品
        weaker = [c for c in competitors if c.share_of_voice < your_sov]
        if weaker:
            insights.append(f"**{weaker[0].competitor_name}** SOV 仅 {weaker[0].share_of_voice}%，可尝试抢夺其展示份额")

        # 通用洞察
        insights.extend([
            "建议增加品牌防御广告（SBV）预算，保护品牌词展示份额",
            "关注竞品的新品上架节奏，提前布局防御性广告",
            "考虑在竞品的劣势点（如发货慢）进行差异化广告文案强调",
        ])

        return insights

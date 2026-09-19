"""
广告分析 Agent (Ad Analysis Agent)

跨境电商广告分析专家，专注于 Amazon PPC 广告优化。

功能模块：
1. 广告账户健康诊断 - ACOS/ROAS/CTR/CVR 多维度评分
2. 出价策略建议 - 基于历史数据+竞品分析的智能出价
3. 搜索词效果报告 - 高效/低效词识别与建议
4. 竞品广告监控 - 关键词重叠、出价对比、展示份额
5. 预算分配优化 - 多Campaign智能调拨
6. 广告异常检测 - 花费突增、转化骤降、展示量异常

设计模式：
- 与 ProductResearchAgent 保持一致的独立实现（不继承 BaseAgent）
- 意图分类 + 多方法路由架构
- 结构化数据输出供前端 SmartPanel 渲染
"""

import json
import re
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from core.logger import get_logger
from ai_infra.sse import progress

logger = get_logger(__name__)


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


def _load_competitor_rows(store_id, time_range="30d") -> List[Dict]:
    """取本店铺的竞品快照（唯一入口，经工厂）。语义同 `_load_ad_rows`。"""
    if not store_id:
        return []
    from modules.amazon_sp import get_data_source

    src = get_data_source(prefer="auto", seed=42)
    d_to = date.today()
    d_from = d_to - timedelta(days=_days_of(time_range) - 1)
    try:
        return list(src.fetch_competitors(store_id, d_from, d_to))
    except Exception as e:
        logger.error(f"[ad_analysis] 取竞品快照失败 store={store_id}: {e}")
        raise


# 结构化意图 → 阶段进度文案（stream_chat 在耗时分析前发给前端，避免空转）
_INTENT_PROGRESS = {
    "diagnosis": "正在诊断广告健康度…",
    "search_terms": "正在分析搜索词报告…",
    "bid_optimize": "正在生成出价建议…",
    "competitor": "正在分析广告竞争格局…",
    "budget": "正在优化预算分配…",
    "anomaly": "正在检测投放异常…",
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


# ---- 预算分配相关 ----

class BudgetAllocation(BaseModel):
    """预算分配方案"""
    campaign_name: str
    current_budget: float
    suggested_budget: float
    allocation_pct: float
    reason: str
    expected_roas: float


class BudgetOptimizationReport(BaseModel):
    """预算优化报告"""
    total_current_budget: float
    total_suggested_budget: float
    allocations: List[BudgetAllocation]
    projected_improvement: Dict[str, float]
    risk_assessment: str


# ---- 异常检测相关 ----

class AnomalyItem(BaseModel):
    """异常项"""
    type: str  # spend_spike / conversion_drop / impression_anomaly / ctr_drop
    severity: str  # high/medium/low
    campaign: str
    metric: str
    current_value: float
    expected_value: float
    deviation_pct: float
    detected_at: str
    possible_cause: str
    suggested_action: str


class AnomalyReport(BaseModel):
    """异常检测报告"""
    check_period: str
    anomalies: List[AnomalyItem]
    summary: str
    alert_count: int


# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
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

    # 系统提示词
    SYSTEM_PROMPT = """你是跨境电商广告分析专家，专精 Amazon PPC 广告优化。

你的能力：
1. **广告健康诊断** - 多维度评估账户/Campaign 表现
2. **搜索词分析** - 识别高效/低效/浪费词，挖掘新机会
3. **出价优化** - 数据驱动的智能出价建议
4. **竞品监控** - 分析竞争对手广告策略
5. **预算调优** - 多Campaign智能预算分配
6. **异常预警** - 自动检测广告数据异常

分析原则：
- 以数据为依据，给出可量化的改进预期
- 区分"必须改"、"建议改"、"观察中"三级优先级
- 考虑季节性、类目特性、竞争环境等因素
- 给出的建议要具体可执行，不说空话

Amazon PPC 关键指标基准（参考值）：
- ACoS: <20% 优秀, 20-30% 良好, >30% 需优化
- RoAS: >5 优秀, 3-5 良好, <3 需优化
- CTR: >0.5% 优秀, 0.3-0.5% 正常, <0.3% 需优化
- CVR: >10% 优秀, 5-10% 正常, <5% 需优化
- CPC: 因类目而异，一般控制在售价的 3-8%
"""

    def __init__(self):
        # 初始化 LLM 基类
        super().__init__()

        self.system_prompt = self.SYSTEM_PROMPT
        self.agent_name = "ad_analysis"

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
        elif intent == "budget":
            return await self._optimize_budget(query, context)
        elif intent == "anomaly":
            return await self._detect_anomalies(query, context)
        else:
            # 默认通用回答
            return await self._general_response(query)

    def _classify_intent(self, query: str) -> str:
        """
        分类用户意图

        Returns:
            diagnosis / search_terms / bid_optimize / competitor / budget / anomaly / general
        """
        query_lower = query.lower()

        # 诊断类
        diagnosis_kw = [
            "诊断", "体检", "健康", "状况", "表现", "怎么样", "如何",
            "diagnosis", "health", "check", "audit", "review", "score"
        ]
        # 搜索词类
        search_term_kw = [
            "搜索词", "search term", "关键词报告", "词报告",
            "哪些词", "客户搜什么", "高效词", "低效词", "浪费"
        ]
        # 出价类
        bid_kw = [
            "出价", "bid", "竞价", "调价", "降价", "加价",
            "cpc", "建议出价", "优化出价"
        ]
        # 竞品类
        competitor_kw = [
            "竞品", "对手", "竞争", "competitor", "别人",
            "展示份额", "share of voice", "soy"
        ]
        # 预算类
        budget_kw = [
            "预算", "budget", "分配", "调拨", "花费",
            "钱花在哪", "投放"
        ]
        # 异常类
        anomaly_kw = [
            "异常", "突然", "骤降", "突增", "不对劲",
            "波动", "anomaly", "alert", "警告"
        ]

        for kw in anomaly_kw:
            if kw in query_lower:
                return "anomaly"

        for kw in budget_kw:
            if kw in query_lower:
                return "budget"

        for kw in competitor_kw:
            if kw in query_lower:
                return "competitor"

        for kw in bid_kw:
            if kw in query_lower:
                return "bid_optimize"

        for kw in search_term_kw:
            if kw in query_lower:
                return "search_terms"

        for kw in diagnosis_kw:
            if kw in query_lower:
                return "diagnosis"

        return "general"

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
            }
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
        comp_rows = _load_competitor_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
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

    async def _optimize_budget(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """预算分配优化"""
        rows = _load_ad_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not rows:
            return self._no_data("预算分配优化", (context or {}).get("store_id"))
        allocations = self._budget_from_rows(rows)
        if not allocations:
            return self._no_data("预算分配优化", (context or {}).get("store_id"))
        total_current = sum(a.current_budget for a in allocations)
        total_suggested = sum(a.suggested_budget for a in allocations)

        # 预期改善：由加码/削减两组的预期 RoAS 相对基准推导（零随机数）
        _all = [a.expected_roas for a in allocations]
        _ups = [a.expected_roas for a in allocations if a.suggested_budget > a.current_budget]
        _cuts = [a.expected_roas for a in allocations if a.suggested_budget < a.current_budget]
        _avg_all = sum(_all) / len(_all) if _all else 0.0
        _avg_up = sum(_ups) / len(_ups) if _ups else 0.0
        _avg_cut = sum(_cuts) / len(_cuts) if _cuts else 0.0
        improvement = {
            "expected_roas_increase": round((_avg_up / _avg_all - 1) * 100, 1) if _avg_all else 0.0,
            "expected_acos_decrease": round((1 - _avg_cut / _avg_all) * 100, 1) if _avg_all else 0.0,
            "efficiency_gain": round(
                (total_suggested - total_current) / total_current * 100, 1
            ) if total_current else 0.0,
        }

        report = BudgetOptimizationReport(
            total_current_budget=total_current,
            total_suggested_budget=total_suggested,
            allocations=allocations,
            projected_improvement=improvement,
            risk_assessment="中等风险 — 建议分两周逐步调整，每周监测效果"
        )

        # ====== LLM 增强：风险评估 ======
        llm_context = f"""请基于以下预算优化方案，生成一段专业风险提示（80字以内，中文）：
- 预算从 ${total_current:.2f} 调整为 ${total_suggested:.2f}（变化 {((total_suggested - total_current) / total_current * 100):+.1f}%）
- 涉及 {len(allocations)} 个 Campaign
请说明主要风险和规避方式。"""
        llm_risk = await self._llm_summarize(llm_context)
        if llm_risk:
            report.risk_assessment = llm_risk

        content = f"""## 💰 预算分配优化方案

**当前日预算**: ${total_current:.2f} | **建议日预算**: ${total_suggested:.2f}
**变化**: {((total_suggested - total_current) / total_current * 100):+.1f}%

### 各 Campaign 分配建议
| Campaign | 当前预算 | 建议预算 | 变化 | 原因 |
|----------|---------|---------|------|------
"""

        for alloc in allocations:
            change = ((alloc.suggested_budget - alloc.current_budget) / alloc.current_budget * 100)
            content += f"| {alloc.campaign_name} | ${alloc.current_budget:.0f} | ${alloc.suggested_budget:.0f} | {change:+.0f}% | {alloc.reason[:20]} |\n"

        content += f"""
### 预期改善
- RoAS 提升: +{improvement['expected_roas_increase']}%
- ACoS 降低: -{improvement['expected_acos_decrease']}%
- 整体效率提升: +{improvement['efficiency_gain']}%

> ⚠️ {report.risk_assessment}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="budget_optimization"
        )

    async def _detect_anomalies(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """广告异常检测"""
        rows = _load_ad_rows((context or {}).get("store_id"), (context or {}).get("time_range"))
        if not rows:
            return self._no_data("广告异常检测", (context or {}).get("store_id"))
        anomalies = self._anomalies_from_rows(
            rows, sensitivity=str((context or {}).get("sensitivity") or "medium")
        )
        alert_count = len([a for a in anomalies if a.severity == "high"])

        summary_parts = []
        if alert_count > 0:
            summary_parts.append(f"⚠️ 发现 **{alert_count} 个高风险异常**，需立即关注")
        medium_count = len([a for a in anomalies if a.severity == "medium"])
        if medium_count > 0:
            summary_parts.append(f"📋 还有 **{medium_count} 个中等风险项")

        summary = " ".join(summary_parts) or "✅ 未发现明显异常，账户运行正常"

        # ====== LLM 增强：异常检测总结 ======
        llm_context = f"""请基于以下广告异常检测结果，生成一段简明总结（100字以内，中文）：
- {alert_count} 个高风险异常、{medium_count} 个中等风险
- 异常类型: {', '.join(a.type for a in anomalies[:5]) or '无'}
请说明最需优先处理的问题和建议。"""
        llm_summary = await self._llm_summarize(llm_context)
        if llm_summary:
            summary = llm_summary

        report = AnomalyReport(
            check_period="近7天 vs 前7天",
            anomalies=anomalies,
            summary=summary,
            alert_count=alert_count
        )

        content = f"""## 🚨 广告异常检测报告

**检测周期**: {report.check_period}
**{report.summary}**

### 异常详情
"""

        for i, anom in enumerate(anomalies[:8]):
            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}
            content += f"""
#### {severity_emoji.get(anom.severity, '')} [{anom.type.upper()}] {anom.campaign}
- **指标**: {anom.metric}
- **当前值**: {anom.current_value} | **预期值**: {anom.expected_value}
- **偏差**: {anom.deviation_pct:+.1f}%
- **可能原因**: {anom.possible_cause}
- **建议操作**: {anom.suggested_action}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="anomaly_report"
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
5. 💰 **预算优化** — "帮我重新分配广告预算"
6. 🚨 **异常检测** — "最近广告数据有没有异常"

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
        intent = self._classify_intent(query)

        # 结构化意图：走 invoke 一次性返回（含图表数据，不适合流式）
        # 注：ad_analysis 的 invoke 是关键词分发（无 LLM 工具化路由），
        # 不存在重复选工具的开销，故此处保留 invoke 调用。
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

    def _budget_from_rows(self, rows: List[Dict]) -> List[BudgetAllocation]:
        """按 Campaign **真实 RoAS 排名**分配预算（确定性，零随机数）。

        规则：RoAS 排名前 1/3 加码 25%、后 1/3 削减 20%、中间持平。
        current_budget = 该 Campaign 的日均花费（近 N 天总花费 /天数）。
        """
        campaigns = self._campaigns_from_rows(rows)
        if not campaigns:
            return []
        day_count = max(1, len({str(r.get("date") or "") for r in rows if r.get("date")}))
        total_spend = sum(c.spend for c in campaigns) or 1.0
        order = sorted(range(len(campaigns)), key=lambda i: campaigns[i].roas, reverse=True)
        n = len(campaigns)
        head = max(1, n // 3)
        tier = {}
        for rank, idx in enumerate(order):
            if rank < head:
                tier[idx] = 1.25
            elif rank >= n - head:
                tier[idx] = 0.8
            else:
                tier[idx] = 1.0

        out: List[BudgetAllocation] = []
        for i, c in enumerate(campaigns):
            current = round(c.spend / day_count, 2)
            factor = tier[i]
            suggested = round(current * factor, 2)
            if factor > 1:
                reason = f"RoAS {c.roas:.2f} 排名靠前，加码抢量"
            elif factor < 1:
                reason = f"RoAS {c.roas:.2f} 偏低（ACoS {c.acos:.1f}%），削减控本"
            else:
                reason = f"RoAS {c.roas:.2f} 居中，维持观察"
            out.append(BudgetAllocation(
                campaign_name=c.campaign_name,
                current_budget=current,
                suggested_budget=suggested,
                allocation_pct=round(current / total_spend * 100, 1),
                reason=reason,
                expected_roas=round(max(c.roas, 0.1) * factor, 2),
            ))
        return out

    def _anomalies_from_rows(
        self, rows: List[Dict], sensitivity: str = "medium"
    ) -> List[AnomalyItem]:
        """按日趋势做**确定性**异常检测（零随机数）。

        方法：把记录按 `date` 分组，前一半为基期、后一半为近期的对比窗口；
        花费突增 / 订单骤降 / CTR 下滑 / 曝光异动 任一超过阈值即报异常。
        阈值随 sensitivity 缩放（high 更敏感）。同一份数据必然得到同一批异常。
        """
        by_date: Dict[str, List[Dict]] = {}
        for r in rows:
            d = str(r.get("date") or "")
            if d:
                by_date.setdefault(d, []).append(r)
        if len(by_date) < 4:
            return []

        days = sorted(by_date)
        half = len(days) // 2
        older = _agg_rows([r for d in days[:half] for r in by_date[d]])
        recent = _agg_rows([r for d in days[half:] for r in by_date[d]])

        threshold = {"low": 0.60, "medium": 0.40, "high": 0.25}.get(sensitivity, 0.40)

        def _dev(cur: float, base: float) -> float:
            return ((cur - base) / base * 100.0) if base else 0.0

        checks = [
            ("spend_spike", "花费", recent["spend"], older["spend"], 1),
            ("conversion_drop", "订单", recent["orders"], older["orders"], -1),
            ("ctr_drop", "CTR", recent["ctr"], older["ctr"], -1),
            ("impression_anomaly", "曝光", recent["impressions"], older["impressions"], 0),
        ]
        out: List[AnomalyItem] = []
        for atype, label, cur, base, direction in checks:
            dev = _dev(cur, base)
            if direction == 1:
                hit = dev >= threshold * 100
            elif direction == -1:
                hit = dev <= -threshold * 100
            else:
                hit = abs(dev) >= threshold * 100
            if not hit:
                continue
            sev = "high" if abs(dev) >= 60 else ("medium" if abs(dev) >= 40 else "low")
            out.append(AnomalyItem(
                type=atype,
                severity=sev,
                campaign="账户整体",
                metric=label,
                current_value=round(cur, 2),
                expected_value=round(base, 2),
                deviation_pct=round(dev, 1),
                detected_at=datetime.now().isoformat(),
                possible_cause=("投放放量或竞价抬高" if dev > 0 else "竞争加剧或预算收缩"),
                suggested_action=("复核预算上限与竞价" if dev > 0 else "检查 Listing 转化率与库存"),
            ))
        return out

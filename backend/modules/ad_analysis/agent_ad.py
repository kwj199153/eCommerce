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
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime, timedelta
import random

from pydantic import BaseModel, Field

from core.logger import get_logger

logger = get_logger(__name__)


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型


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


# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    class LLMEnabledAgent:
        ENABLE_LLM = False
        def __init__(self): pass


class AdAnalysisAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
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
        if LLM_AVAILABLE:
            super().__init__()

        self.system_prompt = self.SYSTEM_PROMPT
        self.agent_name = "ad_analysis"

    async def _llm_summarize(self, context: str) -> Optional[str]:
        """
        LLM 增强：基于诊断数据生成专业的分析总结。

        LLM 不可用或失败时返回 None，由调用方降级到规则生成的文字。
        """
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
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
        # 模拟生成诊断数据（实际对接 Amazon Advertising API）
        metrics = self._generate_metrics()
        campaigns = self._generate_campaigns()
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
        all_terms = self._generate_search_terms(50)

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
            suggestions=suggestions
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
        keywords_data = self._generate_bid_recommendations(15)

        # 计算整体影响
        total_current_bid = sum(k.current_bid for k in keywords_data)
        total_suggested_bid = sum(k.suggested_bid for k in keywords_data)
        budget_impact = total_suggested_bid - total_current_bid
        avg_acos_change = random.uniform(-8, -2)  # 预期 ACoS 改善

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

        increase_count = len([k for k in keywords_data if k.bid_change_pct > 0])
        decrease_count = len([k for k in keywords_data if k.bid_change_pct < 0])

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
        competitors = self._generate_competitor_data(5)
        your_sov = round(random.uniform(12, 28), 1)  # 你的展示份额

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
        allocations = self._generate_budget_allocations(6)
        total_current = sum(a.current_budget for a in allocations)
        total_suggested = sum(a.suggested_budget for a in allocations)

        improvement = {
            "expected_roas_increase": f"+{random.uniform(15, 35):.1f}%",
            "expected_acos_decrease": f"-{random.uniform(3, 8):.1f}%",
            "efficiency_gain": f"+{random.uniform(10, 25):.1f}%",
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
- RoAS 提升: {improvement['expected_roas_increase']}
- ACoS 降低: {improvement['expected_acos_decrease']}
- 整体效率提升: {improvement['efficiency_gain']}

> ⚠️ {report.risk_assessment}
"""

        return AgentResponse(
            content=content,
            data=report.model_dump(),
            display_type="budget_optimization"
        )

    async def _detect_anomalies(self, query: str, context: Optional[Dict] = None) -> AgentResponse:
        """广告异常检测"""
        anomalies = self._generate_anomalies()
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

    async def stream_chat(self, query: str) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        对话类意图走 LLM 流式；结构化意图（诊断/搜索词/出价等）退化为一次性文本。

        Yields:
            文本片段（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        intent = self._classify_intent(query)

        # 结构化意图：走 invoke 一次性返回（含图表数据，不适合流式）
        if intent != "general":
            result = await self.invoke(query)
            yield result.content
            return

        # 对话类：走 LLM 流式
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
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

    def _generate_metrics(self) -> List[AdMetric]:
        """生成核心指标"""
        return [
            AdMetric(name="ACoS", value=random.uniform(18, 35), unit="%", benchmark=22.0,
                     status="warning" if random.random() > 0.5 else "good"),
            AdMetric(name="RoAS", value=random.uniform(2.8, 5.5), unit="x", benchmark=4.5,
                     status="good" if random.random() > 0.4 else "warning"),
            AdMetric(name="CTR", value=random.uniform(0.25, 0.65), unit="%", benchmark=0.40,
                     status="good" if random.random() > 0.4 else "warning"),
            AdMetric(name="CVR", value=random.uniform(5, 14), unit="%", benchmark=9.0,
                     status="warning" if random.random() > 0.6 else "good"),
            AdMetric(name="CPC", value=random.uniform(0.45, 1.2), unit="$", benchmark=0.75,
                     status="good" if random.random() > 0.5 else "warning"),
        ]

    def _generate_campaigns(self, count: int = 5) -> List[CampaignHealth]:
        """生成 Campaign 健康数据"""
        campaign_names = [
            ("自动广告-广泛", "SP"),
            ("手动-精准-核心词", "SP"),
            ("手动-短语-长尾词", "SP"),
            ("品牌-SB-品牌词", "SB"),
            ("展示-SD-竞品定向", "SD"),
        ]
        types_short = ["SP", "SP", "SP", "SB", "SD"]

        campaigns = []
        for i in range(min(count, len(campaign_names))):
            name, ctype = campaign_names[i]
            spend = random.uniform(200, 1500)
            impr = random.randint(50000, 500000)
            clicks = random.randint(500, 5000)
            orders = random.randint(20, 200)
            sales = orders * random.uniform(18, 45)
            acos = (spend / sales * 100) if sales > 0 else 0
            roas = sales / spend if spend > 0 else 0
            ctr = clicks / impr * 100 if impr > 0 else 0
            cvr = orders / clicks * 100 if clicks > 0 else 0
            cpc = spend / clicks if clicks > 0 else 0
            health = max(0, min(100, 100 - acos + roas * 10 - (30 - ctr * 50)))

            campaigns.append(CampaignHealth(
                campaign_name=name,
                campaign_type=ctype,
                status="active",
                spend=round(spend, 2),
                impressions=impr,
                clicks=clicks,
                orders=orders,
                sales=round(sales, 2),
                acos=round(acos, 1),
                roas=round(roas, 2),
                ctr=round(ctr, 2),
                cvr=round(cvr, 1),
                cpc=round(cpc, 2),
                health_score=round(health)
            ))

        return campaigns

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
        """计算综合评分"""
        # 指标权重
        metric_weights = [0.25, 0.25, 0.15, 0.15, 0.10]  # acos, roas, ctr, cvr, cpc
        metric_scores = []

        for m, w in zip(metrics, metric_weights):
            if m.status == "good":
                score = 85 + random.uniform(0, 15)
            elif m.status == "warning":
                score = 55 + random.uniform(0, 25)
            else:
                score = 30 + random.uniform(0, 20)
            metric_scores.append(score * w)

        # Campaign 平均健康分
        avg_campaign_health = sum(c.health_score for c in campaigns) / len(campaigns) if campaigns else 50
        campaign_score = avg_campaign_health * 0.3

        return round(sum(metric_scores) + campaign_score, 0)

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

    def _generate_search_terms(self, count: int) -> List[SearchTermData]:
        """生成搜索词数据"""
        terms_pool = [
            "portable coffee grinder manual", "ceramic burr coffee grinder small",
            "hand coffee bean grinder travel", "espresso grinder manual ceramic",
            "coffee mill hand crank stainless steel", "mini coffee grinder portable",
            "adjustable coffee grinder manual", "best coffee grinder under 30",
            "camping coffee grinder compact", "aeropress coffee grinder recommendation",
            "cold brew coffee grinder coarse", "french press coffee grinder burr",
            "electric vs manual coffee grinder", "coffee grinder cleaning brush",
            "coffee grinder parts replacement", "kitchen aid coffee grinder attachment",
            "hario mini mill slim plus", "porlex tall grinder review",
            "comandante c40 review", "1zpresso jx pro review",
            "timemore c2 review", "kingrinder k6 review",
            "wholesale coffee grinder bulk", "amazon coffee grinder best seller",
            "coffee gift set for dad", "barista tools kit beginner",
        ]

        match_types = ["exact", "phrase", "broad"]
        efficiencies = ["high", "high", "medium", "medium", "low", "low", "waste"]

        result = []
        for i in range(min(count, len(terms_pool))):
            term = terms_pool[i % len(terms_pool)]
            eff = efficiencies[i % len(efficiencies)]

            impr = random.randint(100, 20000)
            clicks = random.randint(5, int(impr * 0.01))
            spend = round(clicks * random.uniform(0.3, 1.5), 2)

            if eff == "high":
                sales = round(spend * random.uniform(3, 8), 2)
                orders = random.randint(3, 20)
            elif eff == "medium":
                sales = round(spend * random.uniform(1.5, 3.5), 2)
                orders = random.randint(1, 8)
            elif eff == "low":
                sales = round(spend * random.uniform(0.5, 1.5), 2)
                orders = random.choice([0, 0, 1])
            else:  # waste
                sales = 0
                orders = 0

            acos = (spend / sales * 100) if sales > 0 else 999
            roas = sales / spend if spend > 0 else 0
            ctr = clicks / impr * 100 if impr > 0 else 0
            cvr = orders / clicks * 100 if clicks > 0 else 0
            cpc = spend / clicks if clicks > 0 else 0

            result.append(SearchTermData(
                term=term,
                impressions=impr,
                clicks=clicks,
                ctr=round(ctr, 2),
                spend=spend,
                sales=sales,
                acos=round(acos, 1),
                roas=round(roas, 2),
                orders=orders,
                cpc=round(cpc, 2),
                match_type=match_types[i % 3],
                efficiency=eff
            ))

        return result

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

    def _generate_bid_recommendations(self, count: int) -> List[BidRecommendation]:
        """生成出价建议"""
        keywords = [
            "coffee grinder manual", "portable coffee grinder", "ceramic burr grinder",
            "hand coffee grinder", "small coffee grinder", "travel coffee maker",
            "espresso grinder manual", "coffee bean grinder electric",
            "best coffee grinder 2024", "affordable burr grinder",
            "camping coffee equipment", "office coffee accessories",
            "gift for coffee lover", "kitchen gadgets unique", "amazon choice coffee",
        ]

        reasons_up = [
            "该词转化率高且 ACoS 优于平均，提高出价可获得更多优质流量",
            "近期该词转化有明显上升趋势，建议抢占更多曝光",
            "竞品在该词上减少投放，是扩大份额的好时机",
            "该词属于高价值长尾词，竞争相对较小但转化稳定",
        ]

        reasons_down = [
            "该词长期 ACoS 偏高，降低出价以控制成本",
            "该词点击量大但转化不稳定，先降低出价观察",
            "该词 CPC 偏高但 ROI 不理想，建议降低至合理区间",
            "季节性下降趋势，应随市场热度调整出价",
        ]

        result = []
        for i in range(count):
            keyword = keywords[i % len(keywords)]
            current_bid = round(random.uniform(0.5, 2.5), 2)

            is_increase = random.random() > 0.45
            if is_increase:
                change_pct = round(random.uniform(10, 35), 0)
                suggested_bid = round(current_bid * (1 + change_pct / 100), 2)
                reason = random.choice(reasons_up)
                priority = "high" if change_pct > 25 else "medium"
            else:
                change_pct = round(random.uniform(-30, -5), 0)
                suggested_bid = round(current_bid * (1 + change_pct / 100), 2)
                reason = random.choice(reasons_down)
                priority = "high" if change_pct < -20 else "low"

            impact = f"预计{'+' if is_increase else ''}{abs(change_pct):.0f}% 点击量，ACoS {'↓' if is_increase and random.random() > 0.3 else '↑' if not is_increase else '~'}"

            result.append(BidRecommendation(
                keyword=keyword,
                match_type=random.choice(["exact", "phrase"]),
                current_bid=current_bid,
                suggested_bid=suggested_bid,
                bid_change_pct=change_pct,
                reason=reason,
                expected_impact=impact,
                priority=priority
            ))

        return result

    def _generate_competitor_data(self, count: int) -> List[CompetitorAdData]:
        """生成竞品数据"""
        competitors_info = [
            ("BrewMaster Pro", "B08XXXXXX1", ["高品质陶瓷磨芯", "调节粗细度高", "品牌知名度强"], ["价格偏高", "款式单一"]),
            ("GrindElite", "B09XXXXXX2", ["性价比突出", "评价数量多", "促销频繁"], ["质量参差", "退货率略高"]),
            ("CoffeeCraft", "B07XXXXXX3", ["设计精美", "配件丰富", "包装用心"], ["价格虚高", "发货慢"]),
            ("BaristaBasics", "B0AXXXXXX4", ["SKU丰富", "物流快", "客服好"], ["缺乏创新", "同质化严重"]),
            ("GrindKing", "B0BXXXXXX5", ["新品冲量", "价格激进", "广告强势"], ["口碑不稳", "复购率低"]),
        ]

        result = []
        for i in range(min(count, len(competitors_info))):
            name, asin, strengths, weaknesses = competitors_info[i]

            result.append(CompetitorAdData(
                competitor_name=name,
                asin=asin,
                share_of_voice=round(random.uniform(8, 25), 1),
                overlap_keywords=random.randint(15, 60),
                avg_position=round(random.uniform(1.5, 4.5), 1),
                estimated_spend=round(random.uniform(100, 800), 2),
                top_keywords=[f"keyword_{j}" for j in range(3)],
                strengths=strengths,
                weaknesses=weaknesses
            ))

        return result

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

    def _generate_budget_allocations(self, count: int) -> List[BudgetAllocation]:
        """生成预算分配"""
        campaigns = [
            ("自动广告-广泛", 300, "流量入口，保持稳定"),
            ("手动-精准-核心词", 450, "主力转化，建议加码"),
            ("手动-短语-长尾词", 250, "低成本拓量"),
            ("品牌-SB-品牌词", 180, "品牌防御，维持现状"),
            ("展示-SD-竞品定向", 220, "抢量渠道，适度增加"),
            ("SD-再营销", 120, "高ROI，建议翻倍"),
        ]

        result = []
        for i in range(min(count, len(campaigns))):
            name, base_budget, reason = campaigns[i]

            # 模拟优化后的预算调整
            if "核心词" in name or "再营销" in name:
                multiplier = random.uniform(1.2, 1.5)
            elif "自动" in name or "品牌" in name:
                multiplier = random.uniform(0.85, 1.05)
            else:
                multiplier = random.uniform(0.95, 1.2)

            suggested = round(base_budget * multiplier, 0)

            result.append(BudgetAllocation(
                campaign_name=name,
                current_budget=base_budget,
                suggested_budget=suggested,
                allocation_pct=round(suggested / sum([c[1] * (random.uniform(1.2, 1.5) if "核心词" in c[0] or "再营销" in c[0] else 1) for c in campaigns[:count]]) * 100, 1),
                reason=reason,
                expected_roas=round(random.uniform(3, 7), 1)
            ))

        return result

    def _generate_anomalies(self) -> List[AnomalyItem]:
        """生成异常数据"""
        anomaly_templates = [
            AnomalyItem(
                type="spend_spike", severity="high",
                campaign="手动-精准-核心词",
                metric="日花费", current_value=280, expected_value=150,
                deviation_pct=86.7,
                detected_at=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                possible_cause="某关键词出价被意外调高或竞争加剧导致 CPC 飙升",
                suggested_action="立即检查出价设置，必要时暂停高价词"
            ),
            AnomalyItem(
                type="conversion_drop", severity="high",
                campaign="自动广告-广泛",
                metric="转化率", current_value=3.2, expected_value=8.5,
                deviation_pct=-62.4,
                detected_at=(datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
                possible_cause="Listing 被差评拉低转化率，或出现恶意竞争点击",
                suggested_action="检查 Listing 评价情况，排查无效点击"
            ),
            AnomalyItem(
                type="impression_anomaly", severity="medium",
                campaign="品牌-SB-品牌词",
                metric="展示量", current_value=8500, expected_value=25000,
                deviation_pct=-66.0,
                detected_at=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                possible_cause="品牌词搜索量季节性下降或预算耗尽提前",
                suggested_action="确认预算是否充足，考虑拓展非品牌词"
            ),
            AnomalyItem(
                type="ctr_drop", severity="medium",
                campaign="展示-SD-竞品定向",
                metric="CTR", current_value=0.12, expected_value=0.35,
                deviation_pct=-65.7,
                detected_at=(datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M"),
                possible_cause="创意素材疲劳或竞品更新了更有吸引力的素材",
                suggested_action="轮换 SD 广告创意，A/B 测试新素材"
            ),
            AnomalyItem(
                type="spend_spike", severity="low",
                campaign="手动-短语-长尾词",
                metric="周花费", current_value=420, expected_value=310,
                deviation_pct=35.5,
                detected_at=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                possible_cause="正常波动范围，可能是某个长尾词突然获得更多曝光",
                suggested_action="观察 3 天，如持续增长则检查具体来源词"
            ),
        ]

        return anomaly_templates

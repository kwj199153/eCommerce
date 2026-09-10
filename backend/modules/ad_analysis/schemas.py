"""
广告分析模块 - 数据模型 (Schemas)

定义请求/响应的 Pydantic 模型
"""

from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field


# ====== 请求模型 ======

class AdDiagnosisRequest(BaseModel):
    """广告诊断请求"""
    time_range: str = Field(default="30d", description="时间范围: 7d/30d/90d")
    campaign_ids: Optional[List[str]] = Field(default=None, description="指定 Campaign ID，空则全部")
    include_benchmark: bool = Field(default=True, description="是否包含行业基准对比")


class SearchTermAnalysisRequest(BaseModel):
    """搜索词分析请求"""
    time_range: str = Field(default="30d", description="时间范围")
    campaign_type: Optional[str] = Field(default=None, description="Campaign 类型: SP/SB/SD")
    min_spend: float = Field(default=5.0, description="最小花费过滤")
    min_clicks: int = Field(default=5, description="最小点击过滤")
    sort_by: str = Field(default="spend", description="排序字段: spend/sales/acos/ctr")


class BidOptimizationRequest(BaseModel):
    """出价优化请求"""
    strategy: str = Field(default="balanced", description="策略: aggressive/conservative/balanced")
    keywords: Optional[List[str]] = Field(default=None, description="指定关键词，空则自动分析")
    max_budget_change: float = Field(default=0.3, description="最大预算变动比例 (0-1)")
    target_acos: Optional[float] = Field(default=None, description="目标 ACoS")


class CompetitorAnalysisRequest(BaseModel):
    """竞品分析请求"""
    competitor_asins: Optional[List[str]] = Field(default=None, description="竞品 ASIN 列表")
    auto_detect: bool = Field(default=True, description="是否自动检测竞品")
    include_keywords: bool = Field(default=True, description="是否包含关键词重叠分析")
    time_range: str = Field(default="30d", description="分析时间范围")


class BudgetOptimizationRequest(BaseModel):
    """预算优化请求"""
    total_daily_budget: Optional[float] = Field(default=None, description="总日预算（空则基于当前）")
    target_roas: Optional[float] = Field(default=None, description="目标 RoAS")
    min_campaign_budget: float = Field(default=20, description="单 Campaign 最小预算")
    seasonality_factor: str = Field(default="normal", description="季节性: low/normal/high/peak")


class AnomalyDetectionRequest(BaseModel):
    """异常检测请求"""
    check_period: str = Field(default="7d", description="检测周期: 1d/7d/14d/30d")
    sensitivity: str = Field(default="medium", description="灵敏度: low/medium/high")
    alert_thresholds: Optional[Dict[str, float]] = Field(
        default=None,
        description="自定义阈值: {spend_spike_pct, conversion_drop_pct, ctr_drop_pct}"
    )
    notify: bool = Field(default=False, description="是否发送通知")


class AdChatRequest(BaseModel):
    """广告对话请求（自然语言入口）"""
    message: str = Field(..., description="用户问题")
    context_id: Optional[str] = Field(default=None, description="上下文 ID（多轮对话）")
    stream: bool = Field(default=False, description="是否流式输出")


# ====== 响应模型 ======

class ApiResponse(BaseModel):
    """通用 API 响应"""
    success: bool = True
    message: str = "操作成功"
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    code: int = 400
    details: Optional[Dict] = None


# ====== 简化的诊断响应 ======

class MetricItem(BaseModel):
    """指标项"""
    name: str
    value: float
    unit: str = ""
    benchmark: float = 0.0
    status: str = "normal"
    change_pct: float = 0.0


class CampaignHealthItem(BaseModel):
    """Campaign 健康项"""
    campaign_name: str
    campaign_type: str
    status: str
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
    health_score: float


class DiagnosisResponse(BaseModel):
    """诊断响应"""
    overall_score: float
    grade: str
    summary: str
    metrics: List[MetricItem]
    campaigns: List[CampaignHealthItem]
    top_issues: List[Dict[str, Any]]
    recommendations: List[str]


# ====== 搜索词响应 ======

class SearchTermItem(BaseModel):
    """搜索词项"""
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
    match_type: str
    efficiency: str


class SearchTermResponse(BaseModel):
    """搜索词报告响应"""
    period: str
    total_terms: int
    high_performers: List[SearchTermItem]
    low_performers: List[SearchTermItem]
    waste_terms: List[SearchTermItem]
    new_opportunities: List[SearchTermItem]
    suggestions: List[str]
    summary: str


# ====== 出价建议响应 ======

class BidRecommendationItem(BaseModel):
    """出价建议项"""
    keyword: str
    match_type: str
    current_bid: float
    suggested_bid: float
    bid_change_pct: float
    reason: str
    expected_impact: str
    priority: str


class BidStrategyResponse(BaseModel):
    """出价策略响应"""
    strategy_type: str
    total_keywords: int
    recommendations: List[BidRecommendationItem]
    budget_impact: float
    expected_acos_change: float
    rationale: str


# ====== 竞品分析响应 ======

class CompetitorAdItem(BaseModel):
    """竞品项"""
    competitor_name: str
    asin: str
    share_of_voice: float
    overlap_keywords: int
    avg_position: float
    estimated_spend: float
    top_keywords: List[str]
    strengths: List[str]
    weaknesses: List[str]


class CompetitorResponse(BaseModel):
    """竞品分析响应"""
    competitors: List[CompetitorAdItem]
    your_share_of_voice: float
    market_position: str
    actionable_insights: List[str]


# ====== 预算优化响应 ======

class BudgetAllocationItem(BaseModel):
    """预算分配项"""
    campaign_name: str
    current_budget: float
    suggested_budget: float
    allocation_pct: float
    reason: str
    expected_roas: float


class BudgetOptimizationResponse(BaseModel):
    """预算优化响应"""
    total_current_budget: float
    total_suggested_budget: float
    allocations: List[BudgetAllocationItem]
    projected_improvement: Dict[str, float]
    risk_assessment: str


# ====== 异常检测响应 ======

class AnomalyItemResponse(BaseModel):
    """异常项响应"""
    type: str
    severity: str
    campaign: str
    metric: str
    current_value: float
    expected_value: float
    deviation_pct: float
    detected_at: str
    possible_cause: str
    suggested_action: str


class AnomalyResponse(BaseModel):
    """异常检测响应"""
    check_period: str
    anomalies: List[AnomalyItemResponse]
    summary: str
    alert_count: int


# ====== 对话响应 ======

class ChatResponse(BaseModel):
    """对话响应"""
    reply: str
    data: Optional[Any] = None
    display_type: str = "text"
    suggestions: Optional[List[str]] = None

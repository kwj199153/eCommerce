"""
竞品情报监控 - 数据模型定义
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ==================== 请求模型 ====================

class CompetitorMonitorRequest(BaseModel):
    """竞品监控请求"""
    asin: Optional[str] = Field(None, description="竞品ASIN，为空则返回所有")
    days: int = Field(30, ge=7, le=90, description="分析天数")


class BatchTrackRequest(BaseModel):
    """批量追踪请求"""
    asins: List[str] = Field(..., description="ASIN列表", min_length=1, max_length=20)
    include_history: bool = Field(True, description="是否包含历史数据")


class MarketShareRequest(BaseModel):
    """市场份额分析请求"""
    category: str = Field(..., description="产品类目")
    estimate_method: str = Field("bsr_based", description="估算方法: bsr_based / revenue_based")


class PricingAnalysisRequest(BaseModel):
    """定价分析请求"""
    asin: Optional[str] = Field(None, description="目标ASIN")
    compare_asins: Optional[List[str]] = Field(None, description="对比ASIN列表")
    analysis_depth: str = Field("standard", description="分析深度: basic / standard / deep")


class ReviewAnalysisRequest(BaseModel):
    """评论分析请求"""
    asin: str = Field(..., description="目标ASIN")
    aspects: Optional[List[str]] = Field(None, description="关注维度，为空则全部分析")
    sample_size: int = Field(100, ge=10, le=1000, description="评论采样数")


class IntruderDetectionRequest(BaseModel):
    """入侵者检测请求"""
    category: str = Field(..., description="监控类目")
    lookback_days: int = Field(30, ge=7, le=90, description="回溯天数")
    min_reviews_threshold: int = Field(50, description="新卖家最低评论阈值")


class BuyBoxAnalysisRequest(BaseModel):
    """Buy Box 分析请求"""
    asin: Optional[str] = Field(None, description="目标ASIN")
    marketplace: str = Field("US", description="站点: US / UK / DE / JP")


class CompetitorCompareRequest(BaseModel):
    """竞品对比请求"""
    asins: List[str] = Field(..., description="要对比的ASIN列表", min_length=2, max_length=10)
    dimensions: List[str] = Field(
        default=["price", "rating", "reviews", "bsr", "value"],
        description="对比维度"
    )


# ==================== 响应模型 ====================

class CompetitorInfo(BaseModel):
    """竞品基本信息"""
    asin: str
    title: str
    brand: str
    price: float
    currency: str = "USD"
    bsr_rank: int = 0
    review_count: int = 0
    rating: float = 0.0
    category: str = ""
    is_prime: bool = False
    stock_status: str = "In Stock"
    last_updated: str = ""


class PricePoint(BaseModel):
    """价格数据点"""
    date: str
    price: float


class RankingPoint(BaseModel):
    """排名数据点"""
    date: str
    bsr_rank: int


class MonitorAlert(BaseModel):
    """监控警报"""
    type: str  # price_drop / rank_change / stock_issue
    severity: str  # info / warning / critical
    message: str
    timestamp: str


class CompetitorMonitorResponse(BaseModel):
    """竞品监控响应"""
    type: str = "monitor_dashboard"
    total_competitors: int
    competitors: List[Dict[str, Any]]
    summary: Dict[str, Any]


class SingleMonitorResponse(BaseModel):
    """单品监控响应"""
    type: str = "single_monitor"
    product: Dict[str, Any]
    price_trend: List[PricePoint]
    ranking_trend: List[RankingPoint]
    analysis: Dict[str, Any]


class BatchTrackResponse(BaseModel):
    """批量追踪响应"""
    type: str = "batch_track"
    tracked_count: int
    competitors: List[Dict[str, Any]]
    comparison_matrix: Dict[str, Any]


class MarketShareEstimateItem(BaseModel):
    """市场份额单项"""
    competitor_asin: str
    brand_name: str
    estimated_market_share: float
    bsr_rank: int
    revenue_estimate: float
    trend: str  # rising/stable/declining


class MarketShareResponse(BaseModel):
    """市场份额分析响应"""
    type: str = "market_share"
    category: str
    total_market_estimate: float
    competitors: List[MarketShareEstimateItem]
    insights: List[str]
    concentration_ratio: Dict[str, float]


class PricingStrategyItem(BaseModel):
    """定价策略单项"""
    strategy_type: str  # premium/economy/competitive/dynamic
    base_price: float
    avg_discount: float
    promo_frequency: str
    price_elasticity: float
    price_volatility: float
    recommendations: List[str]


class PricingStrategyResponse(BaseModel):
    """定价策略响应"""
    type: str = "pricing_strategy"
    analyzed_count: int
    strategies: List[PricingStrategyItem]
    market_positioning_map: Dict[str, Any]


class ReviewInsightItem(BaseModel):
    """评论洞察项"""
    aspect: str
    topic: str
    sentiment_score: float
    mention_count: int
    example_quotes: List[str]


class ReviewSWOT(BaseModel):
    """评论 SWOT"""
    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]


class ReviewAnalysisItem(BaseModel):
    """单个产品的评论分析"""
    asin: str
    brand: str
    product: str
    overall_rating: float
    total_reviews: int
    insights: List[ReviewInsightItem]
    swot: ReviewSWOT
    actionable_intelligence: List[str]


class ReviewAnalysisResponse(BaseModel):
    """评论分析响应"""
    type: str = "review_analysis"
    analyzed_products: int
    analyses: List[ReviewAnalysisItem]


class IntruderAlertItem(BaseModel):
    """入侵者警报项"""
    asin: str
    title: str
    brand: str
    entry_date: str
    price: float
    threat_level: str  # high/medium/low
    reasons: List[str]
    our_product_affected: bool = False


class ResponseStrategy(BaseModel):
    """应对策略"""
    target: str
    strategy: str
    actions: List[str]
    priority: str  # P0/P1/P2


class IntruderDetectionResponse(BaseModel):
    """入侵者检测响应"""
    type: str = "intruder_detection"
    category: str
    detection_date: str
    new_competitors: List[IntruderAlertItem]
    threat_summary: Dict[str, int]
    response_strategies: List[ResponseStrategy]


class BuyBoxSellerInfo(BaseModel):
    """Buy Box 卖家信息"""
    seller_name: str
    price: float
    shipping: float
    in_stock: bool


class BuyBoxAnalysisItem(BaseModel):
    """Buy Box 分析项"""
    asin: str
    brand: str
    product: str
    buy_box_analysis: Dict[str, Any]
    competitiveness_score: float


class BuyBoxAnalysisResponse(BaseModel):
    """Buy Box 分析响应"""
    type: str = "buy_box_analysis"
    analyzed_count: int
    analyses: List[BuyBoxAnalysisItem]
    best_practices: List[str]


class DimensionComparison(BaseModel):
    """维度对比"""
    dimension: str
    values: List[Dict[str, Any]]
    best: str
    best_value: Any


class ValueScoreItem(BaseModel):
    """性价比得分项"""
    asin: str
    brand: str
    value_score: float
    rating: float
    price: float


class OverallRankingItem(BaseModel):
    """总体排名项"""
    asin: str
    brand: str
    overall_score: float
    rank: int


class DifferentiationAnalysis(BaseModel):
    """差异化分析"""
    price_spread: float
    rating_spread: float
    market_segments: List[Dict[str, str]]
    gap_opportunities: List[str]


class CompetitorComparisonResponse(BaseModel):
    """竞品对比响应"""
    type: str = "competitor_comparison"
    compared_count: int
    competitors: List[Dict[str, str]]
    comparison: Dict[str, Any]


# ==================== 通用响应 ====================

class CompetitorAnalysisResponse(BaseModel):
    """通用竞品分析响应（Agent 主入口）"""
    success: bool = True
    intent: str = ""
    data: Dict[str, Any] = {}
    message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

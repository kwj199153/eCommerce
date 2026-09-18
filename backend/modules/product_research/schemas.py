"""
选品分析模块 - 数据模型定义

Pydantic schemas 用于 API 请求/响应验证。
"""

from typing import List, Optional, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# ====== 请求模型 ======

class BlueOceanRequest(BaseModel):
    """蓝海挖掘请求（MVP 完整版）"""
    # 市场基础
    marketplace: str = Field(default="amazon_us", description="目标站点")
    category: Optional[List[str]] = Field(None, description="类目路径（多级，如 ['home_kitchen', 'kitchen_dining']）")

    # 价格区间
    price_min: Optional[float] = Field(None, description="最低售价 (USD)")
    price_max: Optional[float] = Field(None, description="最高售价 (USD)")

    # 竞争筛选（蓝海核心规则）
    max_reviews: int = Field(default=100, description="评论数上限（控制低竞争）")
    min_monthly_sales: int = Field(default=100, description="最小月销量（保证需求）")
    min_roi: float = Field(default=20, description="最低目标 ROI (%)")

    # 高级筛选
    exclude_seasonal: bool = Field(default=False, description="排除季节性商品")
    exclude_brand_dominant: bool = Field(default=False, description="排除品牌垄断商品")
    exclude_high_risk: bool = Field(default=False, description="排除侵权高危品类")

    # 兼容旧参数
    keywords: Optional[List[str]] = Field(None, description="自定义关键词列表（可选）")
    min_search_volume: int = Field(default=5000, description="最小搜索量过滤（兼容）")
    max_competition: float = Field(default=0.8, description="最大竞争度过滤（兼容）")


class ProfitAnalysisRequest(BaseModel):
    """利润分析请求"""
    asin: Optional[str] = Field(None, description="产品 ASIN（可选，有则查询真实数据）")
    product_name: str = Field(default="", description="产品名称")
    selling_price: float = Field(..., gt=0, description="售价 (USD)")
    cost_price: float = Field(..., ge=0, description="采购成本 (USD)")
    weight_lbs: float = Field(default=1.5, description="重量 (磅)")
    dimensions: str = Field(default="10x7x5", description="尺寸 (长x宽高 英寸)")
    category: str = Field(default="", description="类目（影响佣金比例）")
    ad_acos_pct: float = Field(default=15.0, description="预期广告 ACOS (%)")


class PainPointRequest(BaseModel):
    """痛点分析请求"""
    asin: str = Field(..., description="产品 ASIN")
    analyze_positive: bool = Field(default=False, description="是否同时分析好评")


class CompetitorCompareRequest(BaseModel):
    """竞品对比请求"""
    asins: List[str] = Field(..., min_length=2, max_length=5, description="竞品 ASIN 列表（2-5个）")
    include_reviews: bool = Field(default=True, description="是否包含评论分析")


class ChatRequest(BaseModel):
    """对话请求（自然语言）"""
    message: str = Field(..., min_length=1, description="用户消息")
    context_id: Optional[str] = Field(None, description="会话上下文 ID")
    stream: bool = Field(default=False, description="是否流式返回")


# ====== 响应模型 ======

class BlueOceanProductItem(BaseModel):
    """蓝海挖掘 - 单个商品结果"""
    asin: str
    title: str
    price: float
    estimated_monthly_sales: int
    review_count: int
    roi_estimated: float
    blue_ocean_score: int  # 0-100，越高蓝海潜力越强
    marketplace: str
    category: str


class BlueOceanAnalysisResponse(BaseModel):
    """蓝海挖掘 - 完整分析响应"""
    total_candidates: int
    premium_count: int  # 评分 >=70（优质蓝海）
    moderate_count: int  # 评分 40-69（一般潜力）
    high_competition_count: int  # 评分 <40（高竞争）
    products: List[BlueOceanProductItem]
    analysis_summary: str
    filters_applied: dict
    execution_time_seconds: float


class BlueOceanOpportunityResponse(BaseModel):
    """蓝海机会响应"""
    category: str
    search_volume: int
    competition: float
    trend: str
    opportunity_score: float
    reason: str
    suggested_price_range: str
    estimated_margin: str


class FeeBreakdownItem(BaseModel):
    """费用明细项"""
    name: str
    amount: float


class ProfitAnalysisResponse(BaseModel):
    """利润分析响应"""
    product_name: str
    selling_price: float
    cost_price: float
    fees_total: float
    total_cost: float
    net_profit: float
    roi_percentage: float
    break_even_quantity: int
    fee_breakdown: List[FeeBreakdownItem]
    margin_percentage: float


class PainPointItem(BaseModel):
    """痛点条目"""
    pain_point: str
    count: int
    percentage: float


class PainPointAnalysisResponse(BaseModel):
    """痛点分析响应"""
    product_asin: str
    total_reviews_analyzed: int
    negative_review_count: int
    pain_points: List[PainPointItem]
    improvement_suggestions: List[str]
    market_gap_score: float


class CompetitorItem(BaseModel):
    """竞品条目"""
    asin: str
    title: str
    price: float
    rating: float
    review_count: int
    bsr_rank: Optional[int] = None
    strengths: List[str]
    weaknesses: List[str]
    listing_quality_score: float
    price_positioning: str


class CompetitorCompareResponse(BaseModel):
    """竞品对比响应"""
    competitors: List[CompetitorItem]
    comparison_summary: str
    recommendation: str


class ChatResponse(BaseModel):
    """对话响应"""
    reply: str
    display_type: str  # table / chart / text / report
    data: Optional[dict] = None
    suggestions: Optional[List[str]] = None


# ====== 人工审批（HITL，第 131 轮）======

class ApprovalResumeRequest(BaseModel):
    """把人工审批的**决策**回传给被中断的会话。

    为什么需要这个端点（而不是让前端「再发一句话」）：
      有副作用的工具被 `interrupt()` 挂起后，整张图**停在 tool_node 上**，
      等的是一个 `Command(resume=...)`。用户在前端点「批准」并不是在对话，
      而是在**恢复一张被冻结的图** —— 用普通的 `/chat` 再发一句话，
      只会开一轮全新的对话，那个待审批的操作仍永远挂着。

    `context_id` 必须是**首轮那次对话的同一个会话 ID**：thread_id 由
    服务端按 `(命名空间, 用户, 会话)` 重算（见 `BaseAgent.resolve_thread_id`），
    所以**不接受**客户端传 thread_id —— 那等于把「谁的操作能被恢复」
    交给请求方决定（thread_id 里含 user_id）。

    `decision` 四档与 `hitl_decorator` 的响应契约逐字对应：
      · accept   → 执行操作
      · reject   → 拒绝执行（可带 `reason`，会展示给模型与用户）
      · edit     → 用 `args` 改写入参后再执行
      · response → 不执行，把 `feedback` 直接当作回复
    结构对不上的表现是「点了批准但什么都没发生」（落到 else 分支抛错），
    因此这里用 `Literal` 在入口处就把非法值挡掉。
    """

    context_id: str = Field(..., description="会话 ID（与首轮对话同一个）")
    decision: Literal["accept", "reject", "edit", "response"] = Field(
        ..., description="审批决策：accept / reject / edit / response"
    )
    reason: Optional[str] = Field(None, description="拒绝原因（decision=reject 时展示）")
    args: Optional[dict] = Field(None, description="改写后的工具入参（decision=edit 时必填）")
    feedback: Optional[str] = Field(None, description="直接回复内容（decision=response 时使用）")


# ====== 通用响应包装 ======

class ApiResponse(BaseModel):
    """统一 API 响应格式"""
    success: bool = True
    message: str = "操作成功"
    data: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

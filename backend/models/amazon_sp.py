"""
Amazon SP-API 数据模型（Pydantic Schema）

用于 API 请求/响应序列化，与 modules/amazon_sp/db_model.py 的 ORM 模型对应。
前端和 Agent 通过这些 Schema 与后端交互。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


# ====== 枚举 ======

class CredentialStatus(str, Enum):
    PENDING = "pending"       # 已创建授权链接，等待回调
    ACTIVE = "active"         # token 有效，可正常调用 API
    EXPIRED = "expired"       # refresh_token 过期或被撤销
    REVOKED = "revoked"       # 卖家主动撤销授权
    ERROR = "error"           # 连续刷新失败


class ReportTaskStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AdReportType(str, Enum):
    SP = "sp"     # Sponsored Products
    SB = "sb"     # Sponsored Brands (原 Headline Search)
    SD = "sd"     # Sponsored Display


class InventoryHealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    STAGNANT = "stagnant"
    STOCKOUT = "stockout"


# ====== OAuth 凭证 Schema ======

class AmazonCredentialCreate(BaseModel):
    """创建凭证（OAuth 回调时由系统自动创建，一般不手动调用）"""
    store_id: str
    authorization_code: str = Field(..., description="OAuth 回调 code")


class AmazonCredentialResponse(BaseModel):
    """凭证响应（不含敏感 token 信息）"""
    id: int
    store_id: str
    seller_id: Optional[str] = None
    marketplace_participant_id: Optional[str] = None
    aws_region: str
    credential_status: str
    last_refresh_at: Optional[datetime] = None
    token_expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AmazonCredentialDetail(AmazonCredentialResponse):
    """凭证详情（含脱敏后的 token 状态信息）"""
    has_refresh_token: bool = False
    access_token_expires_in: Optional[int] = Field(None, description="access_token 剩余秒数")
    error_count: int = 0
    refresh_error: Optional[str] = None


# ====== 授权日志 Schema ======

class AuthLogResponse(BaseModel):
    """授权日志条目"""
    id: int
    store_id: str
    action: str
    detail: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ====== 销售数据 Schema ======

class DailySalesResponse(BaseModel):
    """每日销售数据"""
    id: int
    store_id: str
    date: datetime
    asin: str
    sku: Optional[str] = None
    product_name: Optional[str] = None
    units_ordered: int
    units_refunded: int
    ordered_revenue: float
    refund_amount: float
    net_revenue: float
    ordered_revenue_usd: Optional[float] = None
    net_revenue_usd: Optional[float] = None
    estimated_fees: Optional[float] = None
    estimated_fba_fee: Optional[float] = None
    estimated_ad_spend: Optional[float] = None
    estimated_profit: Optional[float] = None
    currency: str
    order_count: int
    bsr_rank: Optional[int] = None
    buybox_price: Optional[float] = None

    class Config:
        from_attributes = True


class DailySalesSummary(BaseModel):
    """销售汇总（Agent 查询用）"""
    store_id: str
    date_from: datetime
    date_to: datetime
    total_revenue: float = 0.0
    total_orders: int = 0
    total_units: int = 0
    total_refunds: float = 0.0
    avg_order_value: float = 0.0
    top_asins: List[Dict[str, Any]] = Field(default_factory=list)
    day_over_day_change: Optional[Dict[str, float]] = None  # {revenue_pct, orders_pct, units_pct}


# ====== 广告数据 Schema =====#

class AdMetricResponse(BaseModel):
    """广告指标单条"""
    id: int
    store_id: str
    date: datetime
    report_type: str
    granularity: str
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    ad_group_id: Optional[str] = None
    ad_group_name: Optional[str] = None
    targeting_type: Optional[str] = None
    keyword_text: Optional[str] = None
    target_id: Optional[str] = None
    target_expression: Optional[str] = None
    asin: Optional[str] = None
    sku: Optional[str] = None
    impressions: int
    clicks: int
    ctr: float
    cpc: float
    spend: float
    currency: str
    orders: int
    units_sold: int
    sales: float
    cvr: float
    acos: float
    roas: float
    cpa: Optional[float] = None

    class Config:
        from_attributes = True


class AdMetricsSummary(BaseModel):
    """广告汇总（Agent 查询用）"""
    store_id: str
    date_from: datetime
    date_to: datetime
    report_type: Optional[str] = None  # 不传则聚合所有类型

    # 汇总指标
    total_impressions: int = 0
    total_clicks: int = 0
    total_spend: float = 0.0
    total_sales: float = 0.0
    total_orders: int = 0
    overall_ctr: float = 0.0
    overall_cvr: float = 0.0
    overall_acos: float = 0.0
    overall_roas: float = 0.0

    # 按类型拆分
    by_report_type: List[Dict[str, Any]] = Field(default_factory=list)

    # Top 排行
    top_campaigns_by_spend: List[Dict[str, Any]] = Field(default_factory=list)
    top_keywords_by_acos: List[Dict[str, Any]] = Field(default_factory=list)
    top_asins_by_roas: List[Dict[str, Any]] = Field(default_factory=list)


# ====== Listing Schema =====#

class ListingSnapshotResponse(BaseModel):
    """Listing 快照"""
    id: int
    store_id: str
    asin: str
    sku: Optional[str] = None
    title: Optional[str] = None
    brand: Optional[str] = None
    standard_price: Optional[float] = None
    buybox_price: Optional[float] = None
    currency: Optional[str] = None
    fulfillment_channel: Optional[str] = None
    available_quantity: Optional[int] = None
    bsr_rank: Optional[int] = None
    main_image_url: Optional[str] = None
    snapshot_date: datetime

    class Config:
        from_attributes = True


# ====== 报表任务 Schema =====#

class ReportTaskCreate(BaseModel):
    """创建报表任务请求"""
    report_type: str = Field(..., description="SP-API Report Type")
    data_start_time: Optional[datetime] = None
    data_end_time: Optional[datetime] = None


class ReportTaskResponse(BaseModel):
    """报表任务响应"""
    id: int
    store_id: str
    report_type: str
    data_start_time: Optional[datetime] = None
    data_end_time: Optional[datetime] = None
    report_id: Optional[str] = None
    document_id: Optional[str] = None
    status: str
    processing_status: Optional[str] = None
    retry_count: int
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    downloaded_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ====== 库存健康 Schema =====#

class InventoryHealthResponse(BaseModel):
    """库存健康单条"""
    id: int
    store_id: str
    snapshot_date: datetime
    asin: str
    sku: Optional[str] = None
    fn_sku: Optional[str] = None
    product_name: Optional[str] = None
    fulfillable_quantity: int
    inbound_working_quantity: int
    inbound_shipped_quantity: int
    total_quantity: int
    days_supply: Optional[int] = None
    aged_30_days: Optional[int] = None
    aged_61_90_days: Optional[int] = None
    aged_91_180_days: Optional[int] = None
    aged_181_270_days: Optional[int] = None
    aged_271_365_days: Optional[int] = None
    aged_365_plus_days: Optional[int] = None
    is_stagnant: bool
    has_stockout_risk: bool
    health_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class InventoryHealthSummary(BaseModel):
    """库存健康汇总"""
    store_id: str
    snapshot_date: datetime
    total_skus: int = 0
    healthy_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    stagnant_count: int = 0
    stockout_risk_count: int = 0
    total_invested_value: Optional[float] = None  # 滞销库存估算金额
    top_stagnant_items: List[Dict[str, Any]] = Field(default_factory=list)
    stockout_risk_items: List[Dict[str, Any]] = Field(default_factory=list)


# ====== 竞品快照 Schema [新增] ======

class CompetitorSnapshotResponse(BaseModel):
    """竞品快照单条"""
    id: int
    store_id: str
    snapshot_date: datetime
    competitor_asin: str
    brand: Optional[str] = None
    title: Optional[str] = None
    competes_with_asin: Optional[str] = None
    price: Optional[float] = None
    price_vs_own: Optional[float] = None
    price_change: Optional[str] = None
    has_buybox: Optional[bool] = None
    buybox_price: Optional[float] = None
    bsr_rank: Optional[int] = None
    review_count: Optional[int] = None
    rating: Optional[float] = None
    fulfillment: Optional[str] = None

    class Config:
        from_attributes = True


class CompetitorAnalysisSummary(BaseModel):
    """竞品分析汇总（运营复盘用）"""
    store_id: str
    date_from: datetime
    date_to: datetime
    total_competitors: int = 0
    price_war_alerts: List[Dict[str, Any]] = Field(default_factory=list)   # 价格战预警（竞品大幅降价）
    bsr_gainers: List[Dict[str, Any]] = Field(default_factory=list)       # BSR 上升的竞品（份额威胁）
    bsr_losers: List[Dict[str, Any]] = Field(default_factory=list)        # BSR 下降的竞品
    price_positioning: Dict[str, Any] = Field(default_factory=dict)      # 我们 vs 竞品价格矩阵
    review_gap_analysis: List[Dict[str, Any]] = Field(default_factory=list)  # Review 差距分析


# ====== OAuth 流程 Schema =====#

class AuthUrlResponse(BaseModel):
    """生成授权 URL 响应"""
    auth_url: str = Field(..., description="亚马逊 OAuth 授权跳转 URL")
    state: str = Field(..., description="CSRF 防重放 token")


class OAuthCallbackRequest(BaseModel):
    """OAuth 回调请求（亚马逊回调你的接口）"""
    code: str = Field(..., description="授权码")
    selling_partner_id: Optional[str] = Field(None, description="Seller ID")
    state: Optional[str] = Field(None, description="回传的 state 参数")
    spapi_oauth_code: Optional[str] = Field(None, description="SP-API OAuth code（新版）")


# ====== 同步控制 Schema =====#

class SyncTriggerRequest(BaseModel):
    """手动触发同步请求"""
    store_id: str
    sync_types: List[str] = Field(
        default=["sales", "ads", "listings", "inventory"],
        description="要同步的数据类型列表",
    )
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class SyncStatusResponse(BaseModel):
    """同步状态响应"""
    store_id: str
    store_name: str
    credential_status: str
    last_sync_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = None
    sync_types: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="各数据类型的同步状态: {sales: {last_sync, status, record_count}, ...}",
    )

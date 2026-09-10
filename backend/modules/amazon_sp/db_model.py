"""
Amazon SP-API 数据持久化模型

覆盖完整亚马逊对接数据链路：
1. OAuth 凭证管理（token 存储/刷新/轮换）
2. 授权审计日志（bind / refresh / revoke / expire 全链路可追溯）
3. 销售数据（订单报表解析入库，支持 Agent 查询）
4. 广告数据（SP/SB/SD 三种广告类型，多粒度指标）
5. Listing 快照（ASIN 级别产品信息）
6. 报表任务（异步报表创建→轮询→下载的全生命周期）

设计原则：
- 所有表以 store_id 外键关联 stores_store 表（多租户隔离）
- 时间序列数据按 date + store_id + 维度建唯一索引，防重复写入
- 凭证表 token 字段加密存储（应用层加密，DB 层不存明文）
- 广告数据按 report_type + granularity 支持多维度聚合查询
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Boolean, DateTime, Text, Float, Integer,
    BigInteger, Index, UniqueConstraint, ForeignKey, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


# ============================================================
# 1. Amazon OAuth 凭证表
# ============================================================
class AmazonCredential(Base):
    """
    亚马逊 SP-API OAuth 凭证

    每个店铺（StoreRecord）对应一条凭证记录。
    存储 LWA access_token / refresh_token 以及 SP-API 相关配置。
    refresh_token 是长期有效的（除非卖家撤销），access_token 约 1 小时过期。
    """
    __tablename__ = "amazon_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), unique=True, nullable=False,
    )

    # --- LWA (Login with Amazon) Token ---
    # 注意：生产环境这些字段应在应用层加密后存入，DB 不存明文
    access_token: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    refresh_token: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )

    # --- 卖家身份信息 ---
    seller_id: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    marketplace_participant_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True,
    )

    # --- AWS SP-API 配置 ---
    aws_region: Mapped[str] = mapped_column(
        String(32), default="us-east-1",
    )
    api_endpoint: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True,
    )

    # --- 状态 ---
    credential_status: Mapped[str] = mapped_column(
        String(16), default="pending",
    )
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
    )
    refresh_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    error_count: Mapped[int] = mapped_column(
        Integer, default=0,
    )

    # --- 时间戳 ---
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    # 关系
    # store = relationship("StoreRecord", backref="amazon_credential")

    __table_args__ = (
        Index("ix_amazon_creds_store_id", "store_id"),
        Index("ix_amazon_creds_status", "credential_status"),
    )


# ============================================================
# 2. 授权审计日志
# ============================================================
class AmazonAuthLog(Base):
    """
    Amazon OAuth 操作日志

    记录所有授权相关操作：绑定、刷新、撤销、过期、错误。
    用于排查问题和安全审计。
    """
    __tablename__ = "amazon_auth_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    detail: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True,
    )
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_amazon_auth_logs_store_id", "store_id"),
        Index("ix_amazon_auth_logs_action", "action"),
        Index("ix_amazon_auth_logs_created", "created_at"),
    )


# ============================================================
# 3. 每日销售数据
# ============================================================
class DailySales(Base):
    """
    每日销售汇总

    来源：SP-API Reports → GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL
    解析后的结构化数据，按 ASIN × 日期 粒度聚合。
    Agent（运营复盘师/利润计算器）读取此表生成报告。
    """
    __tablename__ = "amazon_daily_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # --- 商品标识 ---
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # --- 销量 ---
    units_ordered: Mapped[int] = mapped_column(Integer, default=0)
    units_refunded: Mapped[int] = mapped_column(Integer, default=0)
    units_shipped: Mapped[int] = mapped_column(Integer, default=0)

    # --- 金额（分为本币和 USD 两套，方便跨站点对比）---
    ordered_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0)
    net_revenue: Mapped[float] = mapped_column(Float, default=0.0)
    ordered_revenue_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_revenue_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 费用估算（由利润引擎后续填充）---
    estimated_fees: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_fba_fee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_ad_spend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 辅助字段 ---
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    bsr_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    buybox_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 同一店铺 + 同一日期 + 同一 ASIN 唯一（防重复导入）
        UniqueConstraint("store_id", "date", "asin", name="uq_daily_sales_store_date_asin"),
        Index("ix_daily_sales_store_date", "store_id", "date"),
        Index("ix_daily_sales_asin", "asin"),
        Index("ix_daily_sales_date", "date"),
    )


# ============================================================
# 4. 广告指标数据
# ============================================================
class AdMetric(Base):
    """
    广告性能指标

    来源：SP-API Advertising API（SP/SB/SD 三种报表类型）
    支持 campaign / ad_group / keyword / product_ad / target 多个粒度。
    Agent（广告分析师/运营复盘师）读取此表生成 ACoS/ROAS 分析。
    """
    __tablename__ = "amazon_ad_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # --- 报表类型与粒度 ---
    report_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    granularity: Mapped[str] = mapped_column(
        String(16), default="daily",
    )

    # --- 广告层级标识（从粗到细）---
    campaign_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    campaign_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    ad_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ad_group_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # --- 目标类型（keyword / target / product_ad 三选一）---
    targeting_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    keyword_text: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    target_expression: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    asin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # --- 核心指标 ---
    impressions: Mapped[int] = mapped_column(BigInteger, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    cpc: Mapped[float] = mapped_column(Float, default=0.0)
    spend: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    # --- 转化指标 ---
    orders: Mapped[int] = mapped_column(Integer, default=0)
    units_sold: Mapped[int] = mapped_column(Integer, default=0)
    sales: Mapped[float] = mapped_column(Float, default=0.0)
    cvr: Mapped[float] = mapped_column(Float, default=0.0)

    # --- 效率指标（计算字段，入库时预计算加速查询）---
    acos: Mapped[float] = mapped_column(Float, default=0.0)
    roas: Mapped[float] = mapped_column(Float, default=0.0)
    cpa: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 其他 ---
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 防重复：同店+同日+同类型+同campaign+同目标
        UniqueConstraint(
            "store_id", "date", "report_type", "campaign_id", "keyword_text", "target_id", "asin",
            name="uq_ad_metric_unique",
        ),
        Index("ix_ad_metrics_store_date", "store_id", "date"),
        Index("ix_ad_metrics_campaign", "store_id", "campaign_id"),
        Index("ix_ad_metrics_asin", "store_id", "asin"),
        Index("ix_ad_metrics_report_type", "store_id", "report_type"),
    )


# ============================================================
# 5. Listing 快照
# ============================================================
class ListingSnapshot(Base):
    """
    Listing 信息快照

    来源：SP-API Listings API / GET_LISTINGS_ALL_ITEM_DATA_REPORT
    定期抓取 ASIN 级别的产品信息，用于竞品对比和 Listing 优化分析。
    支持历史版本对比（每次同步生成新快照）。
    """
    __tablename__ = "amazon_listing_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # --- 基本信息 ---
    title: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    product_type: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    condition_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    item_package_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    number_of_items: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- 价格 ---
    standard_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buybox_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # --- 库存 ---
    fulfillment_channel: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    available_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- 排名 & 评分 ---
    bsr_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parent_asin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    main_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # --- 快照元数据 ---
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    data_source: Mapped[str] = mapped_column(
        String(32), default="listing_api",
    )
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_listing_snapshot_store_asin", "store_id", "asin"),
        Index("ix_listing_snapshot_date", "snapshot_date"),
        Index("ix_listing_snapshot_sku", "store_id", "sku"),
    )


# ============================================================
# 6. 报表任务（异步任务追踪）
# ============================================================
class ReportTask(Base):
    """
    SP-API 报表异步任务

    SP-API 的数据获取是异步的：
    1. POST /reports 创建任务 → 获得 reportId
    2. GET /reports/{id} 轮询状态
    3. 状态变为 DONE 后，GET /documents/{documentId} 下载结果

    此表记录完整的任务生命周期，用于：
    - 防止重复创建相同报表
    - 追踪任务状态和失败原因
    - 支持断点续传（任务创建后服务重启，仍可继续轮询）
    """
    __tablename__ = "amazon_report_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )

    # --- 任务定义 ---
    report_type: Mapped[str] = mapped_column(
        String(128), nullable=False,
    )
    data_start_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    data_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # --- SP-API 返回 ---
    report_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    document_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # --- 状态机 ---
    status: Mapped[str] = mapped_column(
        String(32), default="created",
    )
    processing_status: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )
    result_location: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )

    # --- 执行信息 ---
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- 时间线 ---
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 防重复：同店+同类型+同时间段不重复创建
        UniqueConstraint(
            "store_id", "report_type", "data_start_time", "data_end_time",
            name="uq_report_task_unique",
        ),
        Index("ix_report_task_store_status", "store_id", "status"),
        Index("ix_report_task_report_id", "report_id"),
    )


# ============================================================
# 7. 库存健康数据（FBA）
# ============================================================
class InventoryHealth(Base):
    """
    FBA 库存健康数据

    来源：SP-API FBA Inventory API / GET_FBA_INVENTORY_AGED_DATA
    用于库存健康度检查 Agent 和补货建议。
    """
    __tablename__ = "amazon_inventory_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fn_sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # --- 库存数量 ---
    fulfillable_quantity: Mapped[int] = mapped_column(Integer, default=0)
    inbound_working_quantity: Mapped[int] = mapped_column(Integer, default=0)
    inbound_shipped_quantity: Mapped[int] = mapped_column(Integer, default=0)
    total_quantity: Mapped[int] = mapped_column(Integer, default=0)

    # --- 库龄分析（滞销风险）---
    days_supply: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_30_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_61_90_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_91_180_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_181_270_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_271_365_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    aged_365_plus_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- 风险标记 ---
    is_stagnant: Mapped[bool] = mapped_column(Boolean, default=False)
    has_stockout_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    health_status: Mapped[str] = mapped_column(
        String(16), default="healthy",
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("store_id", "snapshot_date", "asin", name="uq_inventory_health_unique"),
        Index("ix_inv_health_store_date", "store_id", "snapshot_date"),
        Index("ix_inv_health_stagnant", "store_id", "is_stagnant"),
        Index("ix_inv_health_stockout", "store_id", "has_stockout_risk"),
    )


# ============================================================
# 8. 竞品快照 [新增]
# ============================================================
class CompetitorSnapshot(Base):
    """
    竞品监控快照

    定期抓取竞品 ASIN 的价格、BSR、Review 等关键指标，
    用于运营复盘中的竞品对比分析和价格战预警。
    通过 competes_with_asin 关联到自研产品，支持「我们 vs 竞品」视角分析。
    """
    __tablename__ = "amazon_competitor_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("stores_store.id", ondelete="CASCADE"), nullable=False,
    )
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # --- 竞品身份 ---
    competitor_asin: Mapped[str] = mapped_column(String(16), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # --- 关联关系：这个竞品在盯哪个自研产品 ---
    competes_with_asin: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
        comment="关联的自研产品 ASIN",
    )

    # --- 价格情报 ---
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_vs_own: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="与自研产品的价差（正=竞品更贵，负=竞品更便宜）",
    )
    price_change: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
        comment="PRICE_DROP / PRICE_HIKE / STABLE / NORMAL_FLUCT",
    )
    has_buybox: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    buybox_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 排名 & 口碑 ---
    bsr_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- 其他 ---
    fulfillment: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    main_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "store_id", "snapshot_date", "competitor_asin",
            name="uq_competitor_snapshot_unique",
        ),
        Index("ix_comp_snap_store_date", "store_id", "snapshot_date"),
        Index("ix_comp_snap_competes", "store_id", "competes_with_asin"),
        Index("ix_comp_snap_brand", "brand"),
    )

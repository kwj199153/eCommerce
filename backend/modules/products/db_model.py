"""
产品库持久化 ORM 模型（SPU + SKU 分表）

为 /api/v1 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API，无需内存缓存回灌）。
嵌套结构（bullets/history/数组字段）统一用 JSON 列存储。

模型分层（SPU/SKU 标准电商模型）：
- SPU（Standard Product Unit，主产品）：无 ASIN、不可售，聚合公共属性
  （标题/品牌/分类/图片/卖点/关键词/描述），承载公共文案模板 spu_common。
- SKU（Stock Keeping Unit，具体规格）：独立 ASIN、价格、库存、BSR/评分，
  一条 SKU 通过 spu_id 外键归属一个 SPU；Listing 文案默认继承 SPU，可独立覆盖。

字段命名（已从旧「变体」模型全量改名）：
- variation_parent → spu_id
- is_parent        → （由 SPU 表自身表达，不再需要标记）
- variation_value  → spec_value
- variation_theme  → spu_theme
- parent_content   → spu_common
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Text, Integer, Float, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SpuRecord(Base):
    """SPU 主产品表（/api/v1/spus 数据源）"""
    __tablename__ = "spus"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # spu-xxx
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32), default="other")
    sub_category: Mapped[str] = mapped_column(String(64), default="")

    # 规格主题（原变体主题）：Color / Size / Style / Package / Color-Size
    spu_theme: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # 关键词 / 卖点 / 描述
    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selling_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 图片
    main_image: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 公共基础文案（SPU 共享底稿，SKU 继承后可单独改，支持批量同步）
    # 结构：{ brand, category, keywords: [], selling_points: str, bullets: [{title,content}], a_plus: any }
    spu_common: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 元数据
    shop_id: Mapped[str] = mapped_column(String(64), default="")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # 所属分组 id 列表

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class SkuRecord(Base):
    """SKU 具体规格表（/api/v1/skus 数据源）"""
    __tablename__ = "skus"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sku-xxx
    spu_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("spus.id", ondelete="CASCADE"), index=True
    )  # 归属主产品

    # 规格与标识
    spec_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 规格值（如「红色」「M」）
    asin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sku_code: Mapped[str] = mapped_column(String(64), default="")  # 内部 SKU 编码

    # 价格成本（SKU 独有）
    price: Mapped[float] = mapped_column(Float, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    site: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 库存物流（SKU 独有）
    fba_stock: Mapped[int] = mapped_column(Integer, default=0)
    fbm_stock: Mapped[int] = mapped_column(Integer, default=0)
    fulfillment_type: Mapped[str] = mapped_column(String(8), default="FBA")

    # 运营指标（SKU 独有）
    bsr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    daily_sales_avg: Mapped[float] = mapped_column(Float, default=0)
    roi: Mapped[float] = mapped_column(Float, default=0)
    margin: Mapped[float] = mapped_column(Float, default=0)

    # Listing 状态与 AI 生成内容（默认继承 SPU，可独立覆盖）
    listing_status: Mapped[str] = mapped_column(String(16), default="draft")
    generated_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_bullets: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    generated_a_plus: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    seo_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    generated_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    listing_version: Mapped[int] = mapped_column(Integer, default=1)
    listing_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 增强信息
    has_a_plus: Mapped[bool] = mapped_column(Boolean, default=False)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    rating_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 元数据
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class ProductGroupRecord(Base):
    """产品库分组表"""
    __tablename__ = "product_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # group-xxx
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#1890ff")
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

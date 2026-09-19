"""
候选选品库（草稿池）持久化 ORM 模型

为 /api/v1/candidates 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API，无需内存缓存回灌）。
嵌套结构（keywords/competitor_asins/monitor_data/数组字段）统一用 JSON 列存储。

轻量字段：只保留蓝海挖掘产出的核心选品指标 + 评审状态机，
供选品分析师产出、竞品监控员跟踪、运营评审通过后迁移到产品/Listing 库。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class CandidateRecord(Base):
    """候选选品库表（/api/v1/candidates 数据源）"""
    __tablename__ = "candidates"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_candidates_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # cand-xxx
    asin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32), default="other")
    sub_category: Mapped[str] = mapped_column(String(64), default="")

    # 价格站点
    price: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    site: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 市场数据
    estimated_monthly_sales: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0)
    bsr: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bsr_category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    listed_date: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 蓝海评分核心指标
    roi_estimated: Mapped[float] = mapped_column(Float, default=0)
    margin: Mapped[float] = mapped_column(Float, default=0)
    blue_ocean_score: Mapped[int] = mapped_column(Integer, default=0)
    overall_listing_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 关键词 / 竞品 / 卖点
    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    competitor_asins: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    selling_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 图片
    main_image: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 来源信息
    source: Mapped[str] = mapped_column(String(32), default="blue_ocean")  # blue_ocean / manual / competitor

    # ====== 评审状态机 ======
    # pending 待评审 / under_review 评审中 / approved 已通过 / rejected 已淘汰
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 竞品监控员回填的数据变化快照（价格/评论/BSR/评分趋势等）
    monitor_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_monitored_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 元数据
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # 所属分组 id 列表

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class CandidateGroupRecord(Base):
    """候选选品库分组表"""
    __tablename__ = "candidate_groups"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_candidate_groups_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # cgroup-xxx
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#1890ff")
    # 归属店铺（多租户隔离）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True, server_default='')
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'candidates.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.candidates.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store

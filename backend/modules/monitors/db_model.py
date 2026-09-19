"""
竞品监控池（MonitorPool）持久化 ORM 模型

为 /api/v1/monitors 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API，不再有内存缓存回灌）。

与 candidates 表的两点差异，都是按访问模式定的：

1. **7 维时序用 JSON 列整体存取**（price/bsr/review/variation/listing）
   监控面板的用法是「取整条记录 → 画曲线 / 列事件」，不存在「按时间点查某一列」的需求。
   拆成 5 张时序表只会带来 5 次 JOIN 和一堆无用的迁移成本，JSON 更贴合真实访问模式。

2. **时序数据在入池时由后端生成一次并落库**（见 `snapshot.py`）
   落库前它是前端确定性伪随机生成的（刷新重算）；落库后数据固定，
   刷新不再跳动，且将来接真实抓取**只需替换生成器**——表结构与前端契约都不动。

主键形如 `mon-{asin}-{shop}`：ASIN 在「同一店铺内」唯一，跨店铺可以重复监控同一个 ASIN，
所以唯一性必须带租户维度（`uq_monitor_shop_asin`），主键也把 shop 编进去。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, JSON, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class MonitorRecord(Base):
    """竞品监控池表（/api/v1/monitors 数据源）"""
    __tablename__ = "monitors"
    __table_args__ = (
        # 同一店铺内同一 ASIN 只允许一条监控记录（重复开启监控走 upsert 合并，不新增行）
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_monitors_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "asin", name="uq_monitor_shop_asin"),
    )

    # id = mon-{asin}-{shop}；shop 为空（演示模式/无租户上下文）时用 demo 占位
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    asin: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 租户隔离维度（空串 = 无租户上下文）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # ====== 商品档案 ======
    title: Mapped[str] = mapped_column(String(500), default="")
    brand: Mapped[str] = mapped_column(String(128), default="")
    main_image: Mapped[str] = mapped_column(Text, default="")
    marketplace: Mapped[str] = mapped_column(String(16), default="us")
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    # ====== 最新快照（派生，面板读取这里的当刻值）======
    latest_price: Mapped[float] = mapped_column(Float, default=0)
    price_change_7d: Mapped[float] = mapped_column(Float, default=0)   # %（负=降价）
    latest_bsr: Mapped[int] = mapped_column(Integer, default=0)
    bsr_category: Mapped[str] = mapped_column(String(128), default="")
    bsr_change_7d: Mapped[int] = mapped_column(Integer, default=0)     # 差值（负数=排名上升）
    rating: Mapped[float] = mapped_column(Float, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    reviews_added_7d: Mapped[int] = mapped_column(Integer, default=0)
    # in_stock / low_stock / out_of_stock
    stock_status: Mapped[str] = mapped_column(String(16), default="in_stock")
    # 按近期销量估剩余可售（缺货时为 null，表示无从估算）
    estimated_units_remaining: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    est_monthly_sales: Mapped[int] = mapped_column(Integer, default=0)

    # ====== 7 维时序（JSON 整体存取）======
    price_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    bsr_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    review_events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    variations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    listing_changes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ====== 分组归属 + 溯源 ======
    group_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # manual 监控页手填 / candidate 候选库开启监控 / monitor_page 监控页回流新建
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    source_candidate_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 项目定向归属：{type: product|candidate, asin, title}。
    # 有值 = 属某自有产品/候选项目的对标竞品（定向监控）；null = 游离监控（蓝海随手盯）。
    # 面板的「全部/有归属/游离」三段筛选依赖它，但筛选在前端做，故整体存 JSON 即可。
    owned_by: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    added_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class MonitorGroupRecord(Base):
    """竞品监控池分组表（/api/v1/monitor-groups 数据源）

    字段名沿用前端 `MonitorGroup` 的驼峰（createdAt/updatedAt），与 candidate_groups 一致——
    这两张表都是「原样吐给前端」的轻量配置表，不做下划线转换。
    """
    __tablename__ = "monitor_groups"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_monitor_groups_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # mgrp-xxx
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # product 对标产品 / store 对标店铺 / brand 对标品牌 / custom 自定义
    kind: Mapped[str] = mapped_column(String(16), default="custom")
    color: Mapped[str] = mapped_column(String(16), default="#1890ff")
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'monitors.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.monitors.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store

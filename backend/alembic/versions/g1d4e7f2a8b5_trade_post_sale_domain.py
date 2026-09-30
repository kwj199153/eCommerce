"""trade 域：订单 / 明细 / 物流 / 买家评论 / 归因 / 处置 / 补偿规则 / SKU 健康分

Revision ID: g1d4e7f2a8b5
Revises: f8c3d1a7b2e5
Create Date: 2026-09-27 18:00:00.000000

==============================================================================
为什么一次建 8 张表
==============================================================================
老板的原话是：「买家差评数据源；订单 + 物流数据源等相关数据源都建立数据库表，
我们要定义自己的数据模型，后续再通过适配层接入相关数据。」

这 8 张表是一个**闭环**，少一张整个闭环当场断：

    orders ──< order_items       这笔订单买了什么（SKU/ASIN）
      │
      └────── shipments          实际怎么送的（晚了几天？这就是物流归因的证据）
                                       ▲
    customer_reviews ──> review_attributions   这条差评为什么发生（证据指向上面两行）
                    └──> review_dispositions   赔了什么（引用 compensation_rules）
    compensation_rules                           什么情况赔多少（可配置）
    sku_health_scores             把上面的归因聚合成「这个 SKU 现在健康吗」

少任何一张，那条演示叙事里就有一个环节「说得出来、指不到行」。

==============================================================================
★ 幂等守卫（本仓**必须**，不是可选项）
==============================================================================
`init_db()` 在 development 下对 `Base.metadata` 跑 `create_all`，而它与 Alembic
共用同一份 Base.metadata ⇒ 只要带 `--reload` 的应用在开发库上先启动过，这 8 张表
就已经存在了；此后 `alembic upgrade head` 的 `CREATE TABLE` 会抛 `DuplicateTable`
—— 而那恰恰是「本该顺利」的场景（同族先例见 `e7b2c9d4a1f8_review_reports_library.py`、
`b8d4e2f6c3a5_memory_tables.py`）。

★ 因此：表、索引、唯一约束**各自独立探测**。
  「表在」推不出「索引齐」，也推不出「唯一约束在」——`create_all` 从不动已有的表，
  而手工建过表、或更早一次半成品 create_all 都可能留下缺约束的库。

==============================================================================
★ 外键（`test_schema_parity.py` 的核心不变量）
==============================================================================
8 张表**全部**带 `shop_id`，且外键名必须逐字是 `fk_<table>_shop_id_stores_store`
—— 那条不变量从 `pg_constraint` 按名字前缀查，凡有 `shop_id` 列却查不到外键的表
会直接判红（症状不是报错，而是「删店铺时不再被拦，业务行留成孤儿」）。
`order_items` / `shipments` 另有一条指向 `orders.id` 的 CASCADE 外键：删订单连带
删明细与物流轨迹（它们是订单的一部分，孤立存在毫无意义）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1d4e7f2a8b5'
down_revision: Union[str, Sequence[str], None] = 'f8c3d1a7b2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ====== 列构造小工具 ======
def _S(n: str, length: int, nullable: bool = False):
    return sa.Column(n, sa.String(length=length), nullable=nullable)


def _T(n: str, nullable: bool = False):
    return sa.Column(n, sa.Text(), nullable=nullable)


def _I(n: str, nullable: bool = False):
    return sa.Column(n, sa.Integer(), nullable=nullable)


def _F(n: str, nullable: bool = False):
    return sa.Column(n, sa.Float(), nullable=nullable)


def _B(n: str, nullable: bool = False):
    return sa.Column(n, sa.Boolean(), nullable=nullable)


def _J(n: str):
    return sa.Column(n, sa.JSON(), nullable=True)


def _pk(n: str, length: int):
    return sa.Column(n, sa.String(length=length), nullable=False)


_SHOP_FK = lambda table: sa.ForeignKeyConstraint(  # noqa: E731
    ['shop_id'], ['stores_store.id'],
    name=f'fk_{table}_shop_id_stores_store', ondelete='RESTRICT',
)


# ====== 表规格（★ 顺序有意义：orders 必须先于引用它的两张子表）======
#
# 每项的 `columns` 与 `modules/trade/db_model.py` **逐列对应**（含 nullable）——
# 写错一处 `alembic check` 就会报 drift。
_SPEC: dict[str, dict] = {
    "orders": {
        "columns": [
            _pk("id", 128),
            _S("shop_id", 64),
            _S("platform", 32), _S("marketplace", 16), _S("external_order_id", 64),
            _S("buyer_id", 64), _S("buyer_name", 64),
            _S("order_status", 32), _S("fulfillment_channel", 16),
            _S("ship_country", 16), _S("ship_state", 64), _S("ship_city", 64),
            _S("currency", 8), _F("order_total"),
            _S("purchase_at", 64),
            _S("promised_at", 64, True), _S("shipped_at", 64, True), _S("delivered_at", 64, True),
            _I("transit_days", True), _I("delay_days", True),
            _S("source", 32), _S("fetched_at", 64), _J("raw"),
            _S("created_at", 64), _S("updated_at", 64),
        ],
        "fks": [_SHOP_FK("orders")],
        "uniques": [("uq_orders_scope", ["shop_id", "platform", "external_order_id"])],
        "indexes": [
            "shop_id", "platform", "external_order_id", "order_status",
            "purchase_at", "transit_days", "delay_days",
        ],
    },
    "order_items": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("order_id", 128), _S("external_order_item_id", 64),
            _S("sku", 64), _S("asin", 32),
            _S("item_title", 500), _T("image"),
            _I("quantity"), _S("currency", 8), _F("unit_price"), _F("item_total"),
            _J("raw"),
        ],
        "fks": [
            _SHOP_FK("order_items"),
            sa.ForeignKeyConstraint(
                ['order_id'], ['orders.id'],
                name='fk_order_items_order_id_orders', ondelete='CASCADE',
            ),
        ],
        "uniques": [("uq_order_items_scope", ["order_id", "external_order_item_id"])],
        "indexes": ["shop_id", "order_id", "sku", "asin"],
    },
    "shipments": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("order_id", 128), _S("external_order_id", 64), _S("platform", 32),
            _S("carrier", 64), _S("tracking_no", 64), _S("ship_status", 32),
            _S("shipped_at", 64, True), _S("promised_at", 64, True), _S("delivered_at", 64, True),
            _I("transit_days", True), _I("delay_days", True), _B("is_delivered"),
            _S("last_event_at", 64), _S("last_location", 160), _T("last_event_text"),
            _J("events"),
            _S("source", 32), _S("fetched_at", 64),
            _S("created_at", 64), _S("updated_at", 64),
        ],
        "fks": [
            _SHOP_FK("shipments"),
            sa.ForeignKeyConstraint(
                ['order_id'], ['orders.id'],
                name='fk_shipments_order_id_orders', ondelete='CASCADE',
            ),
        ],
        "uniques": [("uq_shipments_scope", ["shop_id", "order_id"])],
        "indexes": [
            "shop_id", "order_id", "external_order_id", "tracking_no",
            "ship_status", "transit_days", "delay_days",
        ],
    },
    "customer_reviews": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("platform", 32), _S("external_review_id", 64), _S("marketplace", 16),
            _S("order_id", 128, True),
            _S("sku", 64), _S("asin", 32), _S("product_title", 500),
            _I("rating"), _S("title", 300), _T("body"),
            _S("language", 8), _S("review_at", 64),
            _B("verified_purchase"), _I("helpful_votes"), _J("images"),
            _S("buyer_name", 64), _S("status", 16),
            _S("source", 32), _S("fetched_at", 64), _J("raw"),
            _S("created_at", 64), _S("updated_at", 64),
        ],
        "fks": [_SHOP_FK("customer_reviews")],
        "uniques": [("uq_customer_reviews_scope", ["shop_id", "platform", "external_review_id"])],
        "indexes": [
            "shop_id", "external_review_id", "order_id", "sku", "asin",
            "rating", "review_at", "status",
        ],
    },
    "review_attributions": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("review_id", 160), _S("order_id", 128, True), _S("sku", 64), _I("rating"),
            _S("primary_cause", 32), _J("causes"), _F("confidence"), _J("evidence"),
            _S("method", 16), _S("rule_version", 32), _S("attributed_at", 64),
        ],
        "fks": [_SHOP_FK("review_attributions")],
        "uniques": [("uq_review_attributions_review", ["review_id"])],
        "indexes": ["shop_id", "review_id", "sku", "primary_cause"],
    },
    "review_dispositions": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("review_id", 160), _S("ticket_id", 64, True),
            _J("channels"), _J("compensation"), _S("coupon_code", 64),
            _T("reply_draft_en"), _T("reply_draft_zh"),
            _S("status", 16), _S("approved_by", 64), _S("issued_at", 64), _T("notes"),
            _S("created_at", 64), _S("updated_at", 64),
        ],
        "fks": [_SHOP_FK("review_dispositions")],
        "uniques": [("uq_review_dispositions_review", ["review_id"])],
        "indexes": ["shop_id", "review_id", "status"],
    },
    "compensation_rules": {
        "columns": [
            _pk("id", 128),
            _S("shop_id", 64),
            _S("code", 64), _S("name", 160),
            _S("cause", 32), _I("priority"),
            _J("conditions"), _J("action"),
            _F("budget_cap"), _B("enabled"), _T("notes"),
            _S("created_at", 64), _S("updated_at", 64),
        ],
        "fks": [_SHOP_FK("compensation_rules")],
        "uniques": [("uq_compensation_rules_scope", ["shop_id", "code"])],
        "indexes": ["shop_id", "cause", "priority"],
    },
    "sku_health_scores": {
        "columns": [
            _pk("id", 160),
            _S("shop_id", 64),
            _S("sku", 64), _S("asin", 32), _S("product_title", 500),
            _I("period_days"), _S("period_end", 32),
            _I("review_count"), _I("negative_count"), _F("negative_rate"), _F("avg_rating"),
            _I("delayed_orders"),
            _J("cause_counts"), _J("dimensions"),
            _F("health_score"), _F("previous_score"), _F("delta"), _S("top_cause", 32),
            _S("method", 16), _S("computed_at", 64),
        ],
        "fks": [_SHOP_FK("sku_health_scores")],
        "uniques": [("uq_sku_health_scope", ["shop_id", "sku", "period_days", "period_end"])],
        "indexes": ["shop_id", "sku", "asin", "health_score"],
    },
}

#: 升级顺序（拓扑序：orders 在最前）
_ORDER = [
    "orders", "order_items", "shipments", "customer_reviews",
    "review_attributions", "review_dispositions",
    "compensation_rules", "sku_health_scores",
]


def _insp():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _insp().get_table_names()


def _has_index(name: str, table: str) -> bool:
    if not _has_table(table):
        return False
    return any(ix.get('name') == name for ix in _insp().get_indexes(table))


def _has_unique(name: str, table: str) -> bool:
    if not _has_table(table):
        return False
    return any(u.get('name') == name for u in _insp().get_unique_constraints(table))


def upgrade() -> None:
    """Upgrade schema."""
    for table in _ORDER:
        spec = _SPEC[table]
        existed = _has_table(table)
        if not existed:
            op.create_table(
                table,
                *spec["columns"],
                *spec["fks"],
                *[
                    sa.UniqueConstraint(*cols, name=name)
                    for name, cols in spec["uniques"]
                ],
                sa.PrimaryKeyConstraint('id'),
            )
        else:
            print(
                f"[{revision}] {table} 已存在（开发期 create_all 抢先建表），"
                "跳过 create_table"
            )
            # ★ 表已存在时，唯一约束不会随 create_table 一起来 —— 必须单独补。
            #   它们是 upsert 的幂等键，缺了会让「重复同步一次」变成「重复行」。
            for name, cols in spec["uniques"]:
                if not _has_unique(name, table):
                    op.create_unique_constraint(name, table, cols)

        # ★ 索引独立探测（见模块 docstring）：表存在 ≠ 索引齐全。
        #   名字逐字与 ORM `index=True` 的自动命名一致（`alembic check` 比的是真名字）。
        for col in spec["indexes"]:
            name = f'ix_{table}_{col}'
            if not _has_index(name, table):
                op.create_index(op.f(name), table, [col], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    ★ 逆序删：order_items / shipments 有指向 orders.id 的 CASCADE 外键，
      但它们是 RESTRICT 之外的独立表，直接 drop_table 时 PostgreSQL 允许
      （CASCADE 语义是删父连带删子，父子先删谁都不会被拦）；
      这里仍按**逆拓扑序**删，保证回退在加了 FK 的任何版本上都干净。
    ★ 索引与唯一约束显式回收：手工建过表的开发库也能原地回退（与 upgrade 对称）。
    """
    for table in reversed(_ORDER):
        spec = _SPEC[table]
        if not _has_table(table):
            continue
        for col in spec["indexes"]:
            name = f'ix_{table}_{col}'
            if _has_index(name, table):
                op.drop_index(op.f(name), table_name=table)
        op.drop_table(table)

"""新建 daily_briefings 表：每日经营简报（第 371 轮）

Revision ID: m9f6a3c7d1e8
Revises: l8d5e2a9c3f6
Create Date: 2026-10-15 15:00:00.000000

==============================================================================
★ 为什么需要这张表（不能"每天现算"）
==============================================================================
简报的内容是从 `monitors` 的**当刻快照**派生的（`price_change_7d` /
`stock_status` / `reviews_added_7d` / `bsr_change_7d` / `listing_changes`）。
若不落库、改成"打开铃铛时现算"，会得到三个都不可接受的结果：

  ① **「已读」无处安放** —— 徽标要能清零，就必须有"这一份我看过了"的持久记录；
  ② **历史不可回看** —— 现算只能答"现在有什么变化"，答不了"上周三早上说的是什么"；
  ③ **口径漂移不可见** —— 阈值改了之后，用户没法对比"昨天为什么没提醒我"。

⇒ 每天由 beat 生成一份，落库；列表与徽标都读这张表。

==============================================================================
★ 租户维度：只有 shop_id（与 monitors 同源）
==============================================================================
`X-Shop-ID → store_id` 是**唯一**的数据分区维度
（`core/tenant/scoping.py::SHOP_SCOPE_ATTR`）；Account 那一层管的是
「你能看见哪些店」，不是分区维度 ⇒ 本表**不带** `account_id`。
外键同样挂 `stores_store`：`monitors` 已有这条约束，且第 371 轮实测它里面的
`shop_id` **全是真实店铺 id**（无空串）—— 沿用同款约束，
这样「简报指向一个不存在的店」在写入时就被挡住，而不是变成一条查不到归属的孤儿行。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（与 j6c4b9e1f3a5 / i5b3a8d0e2c4 同一个坑）
==============================================================================
`DailyBriefingRecord` 随 `modules.monitors.db_model` 一起进 `wiring.MODEL_MODULES`
⇒ development 启动时 `create_all` 就把表建出来了，此后 `alembic upgrade head`
再 `CREATE TABLE` 会抛 `DuplicateTable`。⇒ `_has_table` 守卫。

==============================================================================
★ 索引与约束（与 ORM 的 `__table_args__` / `index=True` **逐条一致**）
==============================================================================
  · `PK(id)`                                —— 主键 `brief-{date}-{shop}`
  · `UQ(shop_id, brief_date)`               —— 同店同日只有一份（重跑走覆盖）
  · `FK(shop_id → stores_store.id) RESTRICT`—— 删店铺不连带删简报
  · `IX(brief_date)`                        —— 列表默认按日期倒序翻页
  · `IX(shop_id)`                           —— 徽标计数 / 按店过滤

★ 为什么 `items` 用 JSON 而不是拆条目子表：用法是「取整份 → 渲染一列」，
  不存在「按条目类型查某一列」的需求（与 `monitors` 的 7 维时序同判据）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm9f6a3c7d1e8'
down_revision: Union[str, Sequence[str], None] = 'l8d5e2a9c3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'daily_briefings'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(length=128), nullable=False),
            sa.Column('brief_date', sa.String(length=10), nullable=False),
            sa.Column('shop_id', sa.String(length=64), nullable=False),
            sa.Column('items', sa.JSON(), nullable=True),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('item_count', sa.Integer(), nullable=False),
            sa.Column('read_at', sa.String(length=64), nullable=True),
            sa.Column('generated_at', sa.String(length=64), nullable=False),
            sa.Column('created_at', sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ['shop_id'],
                ['stores_store.id'],
                name='fk_daily_briefings_shop_id_stores_store',
                ondelete='RESTRICT',
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('shop_id', 'brief_date', name='uq_briefing_shop_date'),
        )
        op.create_index(
            op.f('ix_daily_briefings_brief_date'), _TABLE, ['brief_date'], unique=False
        )
        op.create_index(
            op.f('ix_daily_briefings_shop_id'), _TABLE, ['shop_id'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table(_TABLE):
        op.drop_index(op.f('ix_daily_briefings_shop_id'), table_name=_TABLE)
        op.drop_index(op.f('ix_daily_briefings_brief_date'), table_name=_TABLE)
        op.drop_table(_TABLE)

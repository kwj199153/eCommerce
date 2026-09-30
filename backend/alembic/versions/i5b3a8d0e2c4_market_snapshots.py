"""新建 market_snapshots 表：选品市场洞察快照（第 305 轮 · 蓝海挖掘大盘云图）

Revision ID: i5b3a8d0e2c4
Revises: h4f2a7c9d1b3
Create Date: 2026-09-29 06:00:00.000000

==============================================================================
★ 纯新增表，外键指向已有表 stores_store
==============================================================================
本表是「选品前市场洞察」的数据落点：站点 × 类目 × 日期 的快照行，六大维度
（品类分布 / 价格带 / 竞争密度 / 搜索热度 / 卖家分布 / 趋势）打平成数值列。

外键目标 `stores_store` 由基线 `0d44a915bbb8` 建，远早于本 revision ⇒ 顺序正确。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（与 b4e8f2c6a1d7 同一个坑）
==============================================================================
`register_all_models()` 里包含 `MarketSnapshotRecord` ⇒ development 启动时
`create_all` 就把表建出来了，此后 `alembic upgrade head` 再 `CREATE TABLE`
会抛 `DuplicateTable`。⇒ `_has_table` 守卫。

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 删索引再删表。没有别的表引用 `market_snapshots`。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i5b3a8d0e2c4'
down_revision: Union[str, Sequence[str], None] = 'h4f2a7c9d1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'market_snapshots'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('site', sa.String(length=64), nullable=False),
            sa.Column('category_path', sa.String(length=256), nullable=False),
            sa.Column('category_name', sa.String(length=128), nullable=False),
            sa.Column('listing_count', sa.Integer(), nullable=False),
            sa.Column('price_min', sa.Float(), nullable=False),
            sa.Column('price_max', sa.Float(), nullable=False),
            sa.Column('price_median', sa.Float(), nullable=False),
            sa.Column('seller_count', sa.Integer(), nullable=False),
            sa.Column('search_volume', sa.Integer(), nullable=False),
            sa.Column('new_seller_count', sa.Integer(), nullable=False),
            sa.Column('search_growth', sa.Float(), nullable=False),
            sa.Column('price_trend', sa.String(length=16), nullable=False),
            sa.Column('blue_ocean_score', sa.Integer(), nullable=False),
            sa.Column('snapshot_date', sa.String(length=16), nullable=False),
            sa.Column('shop_id', sa.String(length=64), nullable=False),
            sa.Column('is_demo', sa.Boolean(), nullable=False),
            sa.Column('source', sa.String(length=32), nullable=False),
            sa.Column('created_at', sa.String(length=64), nullable=False),
            sa.Column('updated_at', sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ['shop_id'], ['stores_store.id'],
                name='fk_market_snapshots_shop_id_stores_store', ondelete='RESTRICT',
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_market_snapshots_site'), _TABLE, ['site'], unique=False)
        op.create_index(op.f('ix_market_snapshots_category_path'), _TABLE, ['category_path'], unique=False)
        op.create_index(op.f('ix_market_snapshots_snapshot_date'), _TABLE, ['snapshot_date'], unique=False)
        op.create_index(op.f('ix_market_snapshots_shop_id'), _TABLE, ['shop_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table(_TABLE):
        op.drop_index(op.f('ix_market_snapshots_shop_id'), table_name=_TABLE)
        op.drop_index(op.f('ix_market_snapshots_snapshot_date'), table_name=_TABLE)
        op.drop_index(op.f('ix_market_snapshots_category_path'), table_name=_TABLE)
        op.drop_index(op.f('ix_market_snapshots_site'), table_name=_TABLE)
        op.drop_table(_TABLE)

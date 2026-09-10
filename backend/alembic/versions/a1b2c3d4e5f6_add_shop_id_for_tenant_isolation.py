"""add shop_id for tenant isolation

为多租户数据层隔离新增归属字段：
- assets 表：新增 shop_id（原本无归属字段）
- asset_groups / candidate_groups / product_groups 表：新增 shop_id
- spus / candidates 表：已有 shop_id，仅补索引

Revision ID: a1b2c3d4e5f6
Revises: 731546794d12
Create Date: 2026-09-10 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '731546794d12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 新增归属字段（默认空串，index 加速隔离查询）
    op.add_column('assets', sa.Column('shop_id', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('asset_groups', sa.Column('shop_id', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('candidate_groups', sa.Column('shop_id', sa.String(length=64), nullable=False, server_default=''))
    op.add_column('product_groups', sa.Column('shop_id', sa.String(length=64), nullable=False, server_default=''))

    # spus / candidates 已有 shop_id，补索引
    op.create_index('ix_spus_shop_id', 'spus', ['shop_id'])
    op.create_index('ix_candidates_shop_id', 'candidates', ['shop_id'])
    op.create_index('ix_assets_shop_id', 'assets', ['shop_id'])
    op.create_index('ix_asset_groups_shop_id', 'asset_groups', ['shop_id'])
    op.create_index('ix_candidate_groups_shop_id', 'candidate_groups', ['shop_id'])
    op.create_index('ix_product_groups_shop_id', 'product_groups', ['shop_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_product_groups_shop_id', table_name='product_groups')
    op.drop_index('ix_candidate_groups_shop_id', table_name='candidate_groups')
    op.drop_index('ix_asset_groups_shop_id', table_name='asset_groups')
    op.drop_index('ix_assets_shop_id', table_name='assets')
    op.drop_index('ix_candidates_shop_id', table_name='candidates')
    op.drop_index('ix_spus_shop_id', table_name='spus')

    op.drop_column('product_groups', 'shop_id')
    op.drop_column('candidate_groups', 'shop_id')
    op.drop_column('asset_groups', 'shop_id')
    op.drop_column('assets', 'shop_id')

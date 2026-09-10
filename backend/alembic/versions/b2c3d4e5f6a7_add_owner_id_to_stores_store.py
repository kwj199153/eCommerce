"""add owner_id to stores_store

打通用户→店铺归属（数据隔离最后一环）：
- stores_store 新增 owner_id（指向 users.id，ondelete SET NULL）
- 存量店铺 owner_id 为 NULL（由回填脚本统一处理）

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'stores_store',
        sa.Column('owner_id', sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        'fk_stores_store_owner_id_users',
        'stores_store',
        'users',
        ['owner_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_stores_store_owner_id', 'stores_store', ['owner_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_stores_store_owner_id', table_name='stores_store')
    op.drop_constraint('fk_stores_store_owner_id_users', 'stores_store', type_='foreignkey')
    op.drop_column('stores_store', 'owner_id')

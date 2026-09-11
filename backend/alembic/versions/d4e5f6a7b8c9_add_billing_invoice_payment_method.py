"""add billing: cancel_at_period_end, invoices, payment_methods

恢复「订阅 & 计费」闭环所需的数据表与字段：
- subscriptions 新增 cancel_at_period_end（周期结束后取消标记）
- invoices（账单/发票）——历史遗留表，若已存在则跳过
- payment_methods（支付方式）——历史遗留表，若已存在则跳过

说明：invoices / payment_methods 表在历史版本中已建过（模型映射后来被删，
但表仍留在 DB），故本迁移对这两个表做「存在即跳过」的幂等处理，
只新增真正缺失的 cancel_at_period_end 列。

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-11 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    """判断表是否已存在（幂等迁移用）"""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return name in insp.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = insp.get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    """Upgrade schema."""
    # 1. subscriptions 加取消标记（幂等）
    if not _column_exists('subscriptions', 'cancel_at_period_end'):
        op.add_column(
            'subscriptions',
            sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        )

    # 2. invoices 表（历史遗留，存在则跳过）
    if not _table_exists('invoices'):
        op.create_table(
            'invoices',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('number', sa.String(length=64), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
            sa.Column('currency', sa.String(length=8), nullable=False, server_default='CNY'),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('description', sa.String(length=255), nullable=True),
            sa.Column('issued_at', sa.DateTime(), nullable=True),
            sa.Column('paid_at', sa.DateTime(), nullable=True),
            sa.Column('pdf_url', sa.String(length=512), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('number'),
        )
        op.create_index('ix_invoices_user_id', 'invoices', ['user_id'])

    # 3. payment_methods 表（历史遗留，存在则跳过）
    if not _table_exists('payment_methods'):
        op.create_table(
            'payment_methods',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('type', sa.String(length=20), nullable=False),
            sa.Column('brand', sa.String(length=32), nullable=False, server_default=''),
            sa.Column('last4', sa.String(length=4), nullable=False, server_default=''),
            sa.Column('exp_month', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('exp_year', sa.Integer(), nullable=False, server_default='2026'),
            sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_payment_methods_user_id', 'payment_methods', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # 仅回退本迁移新增的列；表为历史遗留，不回退 drop（避免误删历史数据）
    if _column_exists('subscriptions', 'cancel_at_period_end'):
        op.drop_column('subscriptions', 'cancel_at_period_end')

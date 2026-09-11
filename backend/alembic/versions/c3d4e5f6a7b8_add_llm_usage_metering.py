"""add llm usage metering to subscriptions

打通「LLM 消耗 → 计费」闭环：
- subscriptions 新增 llm_tokens_used（累计 token 数）
- subscriptions 新增 llm_cost_used（累计成本，元）
- 由 core/billing/llm_meter.py 在每次 Agent 对话结束时累积写入

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-10 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'subscriptions',
        sa.Column('llm_tokens_used', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'subscriptions',
        sa.Column('llm_cost_used', sa.Float(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('subscriptions', 'llm_cost_used')
    op.drop_column('subscriptions', 'llm_tokens_used')

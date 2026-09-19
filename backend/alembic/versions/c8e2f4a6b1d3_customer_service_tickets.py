"""customer service: 新增工单表 cs_tickets（第 143 轮 A4）

Revision ID: c8e2f4a6b1d3
Revises: b7e3f1a9c2d4
Create Date: 2026-09-18 16:10:00.000000

==============================================================================
为什么建这张表
==============================================================================
`CustomerServiceService.create_ticket` 此前**只造对象不落库**：
响应写「工单 XXX 创建成功！」，但那个工单号**指向不了任何记录** ——
刷新即消失，事后无处可查。这是「伪成功」的典型形态。

同时 `create_ticket_endpoint` 连 `X-Shop-ID` 都不取（本文件所在批次的 A4 已修），
所以即便当时有表，也落不下租户维度。

==============================================================================
表结构取舍
==============================================================================
· `shop_id` 带 `fk_cs_tickets_shop_id_stores_store`（ON DELETE RESTRICT）：
  与 monitors / candidates 等 16 张业务表同口径 —— 删店铺是低频高风险动作，
  宁可提示先清理，不连带删业务数据。
  ★ 这条外键**必须在这里建**：`test_schema_parity.py` 的核心不变量是
    「凡有 shop_id 列的表都必须有指向 stores_store 的外键」，
    而它从 information_schema / pg_constraint 读**真实库** ⇒ 迁移漏了就会红。

· 时间字段用 String(64) 存 ISO 串（与 monitors / aigc_jobs 一致），
  避免引入 naive/aware 时区议题 —— 本表只做「原样吐给前端」。

· attachments / tags / auto_replies 用 JSON 整体存取（访问模式是取整条工单）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e2f4a6b1d3'
down_revision: Union[str, Sequence[str], None] = 'b7e3f1a9c2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'cs_tickets',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('shop_id', sa.String(length=64), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('priority', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('customer_id', sa.String(length=64), nullable=False),
        sa.Column('order_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.String(length=64), nullable=False),
        sa.Column('updated_at', sa.String(length=64), nullable=False),
        sa.Column('sla_deadline', sa.String(length=64), nullable=True),
        sa.Column('estimated_response_time', sa.String(length=16), nullable=False),
        sa.Column('auto_replies', sa.JSON(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('attachments', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ['shop_id'], ['stores_store.id'],
            name='fk_cs_tickets_shop_id_stores_store', ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cs_tickets_shop_id'), 'cs_tickets', ['shop_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    ★ 直接 drop_table：表是本次新加的，里面只可能有本批次之后产生的工单。
      不写"先把工单导出再删"—— 那是运维动作，不该藏在迁移里。
    """
    op.drop_index(op.f('ix_cs_tickets_shop_id'), table_name='cs_tickets')
    op.drop_table('cs_tickets')

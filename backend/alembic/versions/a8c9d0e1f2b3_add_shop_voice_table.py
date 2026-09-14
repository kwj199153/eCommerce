"""add shop_voice table (voice clone add-on module)

语音克隆附加模块的独立表：一个店铺一条音色记录（MVP：单店铺单音色）。

★ 本迁移**只新建 shop_voice 一张表**，不 ALTER 任何既有表 —— 这是「可插拔」的数据层要求。

Revision ID: a8c9d0e1f2b3
Revises: 9c3a5b7d2e4f
Create Date: 2026-09-14 03:10:00.000000

幂等（CREATE TABLE IF NOT EXISTS）：开发环境可能已通过 init_db 的 create_all 建过表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8c9d0e1f2b3'
down_revision: Union[str, Sequence[str], None] = '9c3a5b7d2e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shop_voice (
            id VARCHAR(64) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            voice_id VARCHAR(128),
            target_model VARCHAR(64) NOT NULL DEFAULT '',
            voice_name VARCHAR(128) NOT NULL DEFAULT '',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            error_msg TEXT NOT NULL DEFAULT '',
            sample_url TEXT NOT NULL DEFAULT '',
            sample_name VARCHAR(255) NOT NULL DEFAULT '',
            sample_size INTEGER NOT NULL DEFAULT 0,
            sample_duration INTEGER NOT NULL DEFAULT 0,
            authorized_at VARCHAR(64) NOT NULL DEFAULT '',
            authorized_by VARCHAR(36) NOT NULL DEFAULT '',
            agreement_snapshot TEXT NOT NULL DEFAULT '',
            preview_text TEXT NOT NULL DEFAULT '',
            "createdAt" VARCHAR(64),
            "updatedAt" VARCHAR(64)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_shop_voice_shop_id ON shop_voice (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_shop_voice_status ON shop_voice (status)")
    # 一个店铺一条记录（MVP 单店铺单音色）—— 唯一索引把这条业务约束落在库上
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_shop_voice_shop ON shop_voice (shop_id)")


def downgrade() -> None:
    op.drop_table('shop_voice')

"""add monitor pool tables

竞品监控池持久化：monitors（每个被监控 ASIN 的 7 维档案）+ monitor_groups（自建分组）。

Revision ID: f7b8c9d0e1f2
Revises: e6a7b8c9d0e1
Create Date: 2026-09-12 19:40:00.000000

注意：本迁移为幂等（CREATE TABLE IF NOT EXISTS），因为开发环境可能已通过
init_db 的 create_all 建过表。时序字段（price_history 等）用 JSON 整体存取，
理由见 modules/monitors/db_model.py 的模块注释。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'e6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monitors (
            id VARCHAR(128) PRIMARY KEY,
            asin VARCHAR(32) NOT NULL,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            title VARCHAR(500) NOT NULL DEFAULT '',
            brand VARCHAR(128) NOT NULL DEFAULT '',
            main_image TEXT NOT NULL DEFAULT '',
            marketplace VARCHAR(16) NOT NULL DEFAULT 'us',
            currency VARCHAR(8) NOT NULL DEFAULT 'USD',
            latest_price DOUBLE PRECISION NOT NULL DEFAULT 0,
            price_change_7d DOUBLE PRECISION NOT NULL DEFAULT 0,
            latest_bsr INTEGER NOT NULL DEFAULT 0,
            bsr_category VARCHAR(128) NOT NULL DEFAULT '',
            bsr_change_7d INTEGER NOT NULL DEFAULT 0,
            rating DOUBLE PRECISION NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            reviews_added_7d INTEGER NOT NULL DEFAULT 0,
            stock_status VARCHAR(16) NOT NULL DEFAULT 'in_stock',
            estimated_units_remaining INTEGER,
            est_monthly_sales INTEGER NOT NULL DEFAULT 0,
            price_history JSON,
            bsr_history JSON,
            review_events JSON,
            variations JSON,
            listing_changes JSON,
            group_ids JSON,
            origin VARCHAR(16) NOT NULL DEFAULT 'manual',
            source_candidate_id VARCHAR(64),
            owned_by JSON,
            added_at VARCHAR(64),
            created_at VARCHAR(64),
            updated_at VARCHAR(64)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS monitor_groups (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            kind VARCHAR(16) NOT NULL DEFAULT 'custom',
            color VARCHAR(16) NOT NULL DEFAULT '#1890ff',
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            "createdAt" VARCHAR(64),
            "updatedAt" VARCHAR(64)
        )
        """
    )
    # 索引（IF NOT EXISTS 语义：用 DO 块规避重复创建报错）
    op.execute("CREATE INDEX IF NOT EXISTS ix_monitors_asin ON monitors (asin)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_monitors_shop_id ON monitors (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_monitor_groups_shop_id ON monitor_groups (shop_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_monitor_shop_asin ON monitors (shop_id, asin)"
    )


def downgrade() -> None:
    op.drop_table('monitor_groups')
    op.drop_table('monitors')

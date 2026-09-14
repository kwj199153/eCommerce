"""add platform rules tables

平台规则库持久化：platform_rules（规则本体）+ platform_rule_docs（来源文档素材）。

Revision ID: 8e2f4a6c9b1d
Revises: f7b8c9d0e1f2
Create Date: 2026-09-12 20:40:00.000000

注意：本迁移为幂等（CREATE TABLE IF NOT EXISTS），因为开发环境可能已通过
init_db 的 create_all 建过表。`status` 只存用户设定的原值（auto/active/…），
按日期解析 status 是前端展示期计算，不进库；文档正文整篇存 Text，
理由见 modules/platform_rules/db_model.py 的模块注释。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e2f4a6c9b1d'
down_revision: Union[str, Sequence[str], None] = 'f7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_rules (
            id VARCHAR(128) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            platform VARCHAR(32) NOT NULL DEFAULT 'amazon',
            category VARCHAR(32) NOT NULL DEFAULT 'policy',
            title VARCHAR(500) NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            effective_date VARCHAR(32) NOT NULL DEFAULT '',
            expiry_date VARCHAR(32),
            status VARCHAR(16) NOT NULL DEFAULT 'auto',
            tags JSON,
            source TEXT NOT NULL DEFAULT '',
            source_doc_id VARCHAR(128),
            created_at VARCHAR(64),
            updated_at VARCHAR(64)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_rule_docs (
            id VARCHAR(128) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            platform VARCHAR(32) NOT NULL DEFAULT 'amazon',
            filename VARCHAR(500) NOT NULL DEFAULT '',
            file_type VARCHAR(16) NOT NULL DEFAULT 'other',
            size INTEGER NOT NULL DEFAULT 0,
            uploaded_at VARCHAR(64),
            description VARCHAR(500) NOT NULL DEFAULT '',
            content TEXT
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rules_shop_id ON platform_rules (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rules_platform ON platform_rules (platform)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rules_category ON platform_rules (category)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rules_source_doc_id ON platform_rules (source_doc_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rule_docs_shop_id ON platform_rule_docs (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_rule_docs_platform ON platform_rule_docs (platform)")


def downgrade() -> None:
    op.drop_table('platform_rule_docs')
    op.drop_table('platform_rules')

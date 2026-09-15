"""add knowledge base tables

业务话术库持久化：knowledge_bases（容器）+ knowledge_faqs（话术）+ knowledge_docs（文档素材）。

Revision ID: 9c3a5b7d2e4f
Revises: 8e2f4a6c9b1d
Create Date: 2026-09-12 23:10:00.000000

注意：本迁移为幂等（CREATE TABLE IF NOT EXISTS），因为开发环境可能已通过
init_db 的 create_all 建过表。`faq_count` / `doc_count` **不是列** ——
计数是派生数据，读取时实时 group by 统计（理由见 modules/knowledge_base/db_model.py）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c3a5b7d2e4f'
down_revision: Union[str, Sequence[str], None] = '8e2f4a6c9b1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id VARCHAR(160) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            name VARCHAR(200) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            icon VARCHAR(16) NOT NULL DEFAULT '📚',
            type VARCHAR(16) NOT NULL DEFAULT 'custom',
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at VARCHAR(64),
            updated_at VARCHAR(64)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_faqs (
            id VARCHAR(160) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            kb_id VARCHAR(160) NOT NULL DEFAULT '',
            question TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            category VARCHAR(32) NOT NULL DEFAULT 'other',
            keywords JSON,
            priority VARCHAR(16) NOT NULL DEFAULT 'medium',
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            usage_count INTEGER NOT NULL DEFAULT 0,
            created_at VARCHAR(64),
            updated_at VARCHAR(64)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_docs (
            id VARCHAR(160) PRIMARY KEY,
            shop_id VARCHAR(64) NOT NULL DEFAULT '',
            kb_id VARCHAR(160) NOT NULL DEFAULT '',
            filename VARCHAR(500) NOT NULL DEFAULT '',
            file_type VARCHAR(16) NOT NULL DEFAULT 'other',
            size INTEGER NOT NULL DEFAULT 0,
            uploaded_at VARCHAR(64),
            description TEXT NOT NULL DEFAULT '',
            content TEXT
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_bases_shop_id ON knowledge_bases (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_faqs_shop_id ON knowledge_faqs (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_faqs_kb_id ON knowledge_faqs (kb_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_faqs_category ON knowledge_faqs (category)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_faqs_status ON knowledge_faqs (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_docs_shop_id ON knowledge_docs (shop_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_docs_kb_id ON knowledge_docs (kb_id)")


def downgrade() -> None:
    op.drop_table('knowledge_docs')
    op.drop_table('knowledge_faqs')
    op.drop_table('knowledge_bases')

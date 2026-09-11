"""add conversation tables

决策层 B（跨会话记忆）：会话 + 消息持久化表。

Revision ID: e6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-09-11 22:20:00.000000

注意：本迁移为幂等（CREATE TABLE IF NOT EXISTS），因为开发环境可能已通过
init_db 的 create_all 建过表；checkpoint_* 表由 LangGraph 运行时管理，不在本迁移内。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(64) PRIMARY KEY,
            owner_id VARCHAR(36),
            shop_id VARCHAR(64),
            agent_id VARCHAR(32) NOT NULL DEFAULT 'secretary',
            title VARCHAR(200) NOT NULL DEFAULT '新对话',
            created_at TIMESTAMP NOT NULL DEFAULT now(),
            updated_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id VARCHAR(64) PRIMARY KEY,
            conversation_id VARCHAR(64) NOT NULL,
            seq INTEGER NOT NULL,
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    # 索引（IF NOT EXISTS 语义：用 DO 块规避重复创建报错）
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_owner_id ON conversations (owner_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_shop_id ON conversations (shop_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_messages_conversation_id
        ON conversation_messages (conversation_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conv_msg_conversation_seq
        ON conversation_messages (conversation_id, seq)
        """
    )


def downgrade() -> None:
    op.drop_table('conversation_messages')
    op.drop_table('conversations')

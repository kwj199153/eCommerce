"""reconcile: 删掉历史遗留的重复会话索引

背景（2026-09-15 squash 迁移基线时的发现）：
  `conversations` 上同时存在两套**功能完全相同**的索引：
    - `ix_conversation_owner_id` / `ix_conversation_shop_id`
      —— 来自手写迁移 e6a7b8c9d0e1 的裸 SQL（单数 conversation）
    - `ix_conversations_owner_id` / `ix_conversations_shop_id`
      —— 由 ORM 的 `index=True` 自动命名（复数 conversations，项目标准命名）
  两套列完全相同，纯冗余（每次写入要维护两份）。

  基线 0d44a915bbb8 是**从 ORM metadata 生成**的，因此只含标准命名那一套。
  本迁移把历史库上旧命名的重复索引清掉，使「历史库」与「基线库」逐项一致
  —— 否则两者会永远差 2 个索引，只能靠 stamp 掩盖。

幂等：`IF EXISTS`；对「由基线建出的全新库」是 no-op（那些索引本就不存在）。

Revision ID: a506249ae3e3
Revises: 0d44a915bbb8
Create Date: 2026-09-15 16:17:06.407180
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a506249ae3e3'
down_revision: Union[str, Sequence[str], None] = '0d44a915bbb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (索引名, 表, 列)
_LEGACY_REDUNDANT = (
    ("ix_conversation_owner_id", "conversations", "owner_id"),
    ("ix_conversation_shop_id", "conversations", "shop_id"),
)


def upgrade() -> None:
    """删掉旧命名的重复索引（新库上为 no-op）。"""
    for name, _table, _col in _LEGACY_REDUNDANT:
        op.execute(f"DROP INDEX IF EXISTS {name}")


def downgrade() -> None:
    """恢复旧命名索引（注意：这会把冗余重新引入，仅供回滚用）。"""
    for name, table, col in _LEGACY_REDUNDANT:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})")

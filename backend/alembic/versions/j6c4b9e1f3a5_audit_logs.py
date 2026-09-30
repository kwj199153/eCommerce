"""新建 audit_logs 表：通用审计日志（第 327 轮 · P0-5）

Revision ID: j6c4b9e1f3a5
Revises: i5b3a8d0e2c4
Create Date: 2026-09-30 12:00:00.000000

==============================================================================
★ 纯新增表，**零外键**
==============================================================================
本表刻意不建任何外键（见 `core/audit/models.py` 文件头的论证）：审计记录必须
比它所记录的主体**活得更久** —— 用户被删、店铺被删之后，「当时是谁干的」
这类问题才最需要回答。挂 CASCADE 会静默抹掉痕迹，挂 SET NULL 会丢掉归属。

⇒ 这是本仓**唯一**一张有 `actor_id` 列却**不指向 `users`** 的表，是设计而非遗漏。
   它也因此不参与 `tests/test_schema_parity.py` 的外键不变量（那些不变量的
   前提是「列名宣告了归属关系」，本表的 `actor_id` 只记录**历史事实**）。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（与 b4e8f2c6a1d7 / i5b3a8d0e2c4 同一个坑）
==============================================================================
`register_all_models()` 里包含 `AuditLog` ⇒ development 启动时 `create_all`
就把表建出来了，此后 `alembic upgrade head` 再 `CREATE TABLE` 会抛
`DuplicateTable`。⇒ `_has_table` 守卫。

==============================================================================
★ 索引（与 ORM 的 `__table_args__` **逐条一致**，`alembic check` 据此比对）
==============================================================================
三个复合/单列索引，分别服务三种主查询形态（时间翻页 / 按人 / 按动作）。
★ 刻意没有 `actor_id` / `action` 的单列索引：复合索引的最左前缀已覆盖，
  多建纯属写放大（理由同步写在 ORM 那一侧）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j6c4b9e1f3a5'
down_revision: Union[str, Sequence[str], None] = 'i5b3a8d0e2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'audit_logs'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('actor_id', sa.String(length=36), nullable=True),
            sa.Column('actor_email', sa.String(length=255), nullable=True),
            sa.Column('action', sa.String(length=64), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('target_type', sa.String(length=32), nullable=True),
            sa.Column('target_id', sa.String(length=64), nullable=True),
            sa.Column('summary', sa.String(length=512), nullable=False),
            sa.Column('detail', sa.JSON(), nullable=True),
            sa.Column('ip', sa.String(length=64), nullable=True),
            sa.Column('user_agent', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_audit_logs_created_at'), _TABLE, ['created_at'], unique=False
        )
        op.create_index(
            op.f('ix_audit_logs_actor_created'), _TABLE,
            ['actor_id', 'created_at'], unique=False,
        )
        op.create_index(
            op.f('ix_audit_logs_action_created'), _TABLE,
            ['action', 'created_at'], unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table(_TABLE):
        op.drop_index(op.f('ix_audit_logs_action_created'), table_name=_TABLE)
        op.drop_index(op.f('ix_audit_logs_actor_created'), table_name=_TABLE)
        op.drop_index(op.f('ix_audit_logs_created_at'), table_name=_TABLE)
        op.drop_table(_TABLE)

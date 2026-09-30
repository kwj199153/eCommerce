"""新建 skill_favorites 表：技能收藏（第 194 轮）

Revision ID: b4e8f2c6a1d7
Revises: a3c7e1b5d9f2
Create Date: 2026-09-18 13:25:00.000000

==============================================================================
★ 纯新增表，但外键指向两张**已有表**（users / skills）
==============================================================================
新建表本身最坏是"建多了"（见 `e8c2f5a7b3d9` 的论证），但它带两个外键，
所以有两个额外注意点：

  1. 外键目标必须已在库里 —— `users`（由 `d1e2f3a4b5c6` 建）与
     `skills`（由 `e8c2f5a7b3d9` 建）都在本 revision 之前 ⇒ 顺序天然正确；
  2. `ondelete='CASCADE'` 两侧都用 —— 收藏行没有独立价值，见
     `modules/skills/db_model.py::SkillFavoriteRecord` 的论证。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（与 e8c2f5a7b3d9 同一个坑）
==============================================================================
`register_all_models()` 里已包含 `SkillFavoriteRecord` ⇒ development 启动时
`create_all` 就把表建出来了，此后 `alembic upgrade head` 再 `CREATE TABLE`
会抛 `DuplicateTable: relation "skill_favorites" already exists`。
⇒ `_has_table` 守卫。

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 先删索引再删表（PG 会随表删索引，但显式 drop 让 downgrade
在"索引被人手工删过"的半坏状态下也能跑通），无需担心子表 —— 没有别的表
引用 `skill_favorites`。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4e8f2c6a1d7'
down_revision: Union[str, Sequence[str], None] = 'a3c7e1b5d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'skill_favorites'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.String(length=36), nullable=False),
            sa.Column('skill_id', sa.String(length=64), nullable=False),
            # ★ nullable=False 必须与 ORM 的 `Mapped[datetime]`（非 Optional）一致。
            #   曾写成 nullable=True ⇒ `alembic check` 报 modify_nullable：
            #   迁移建出的库比 ORM 宽松，且与 create_all 建出的库（NOT NULL）**不一致**。
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ['user_id'], ['users.id'],
                name='fk_skill_favorites_user_id_users', ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['skill_id'], ['skills.id'],
                name='fk_skill_favorites_skill_id_skills', ondelete='CASCADE',
            ),
            # 幂等切换的依据：同一人对同一技能只能有一条收藏
            sa.UniqueConstraint('user_id', 'skill_id', name='uq_skill_favorites_user_skill'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_skill_favorites_user_id'), _TABLE, ['user_id'], unique=False
        )
        op.create_index(
            op.f('ix_skill_favorites_skill_id'), _TABLE, ['skill_id'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_table(_TABLE):
        op.drop_index(op.f('ix_skill_favorites_skill_id'), table_name=_TABLE)
        op.drop_index(op.f('ix_skill_favorites_user_id'), table_name=_TABLE)
        op.drop_table(_TABLE)

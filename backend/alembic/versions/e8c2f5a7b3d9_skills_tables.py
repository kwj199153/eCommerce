"""skills / skill_revisions 建表：技能仓库（第 181 轮 · 批 B）

Revision ID: e8c2f5a7b3d9
Revises: d4a7b2e8c1f6
Create Date: 2026-09-20 15:40:00.000000

==============================================================================
★ 这次是**纯新增**，不动任何既有表
==============================================================================
两张新表（`skills` / `skill_revisions`），零 `ALTER`、零 `DROP`。

这一点值得写下来：它与 `d4a7b2e8c1f6`（给已有表加列）是两种风险等级。
新增表最坏情况是"建多了"，删掉即可；改既有表则要面对「已有行怎么补值」
「代码与库不同步时哪一侧是真的」。所以本次的 `downgrade()` 可以放心地直接
`drop_table` —— 没有别的表引用它们（只有 `skill_revisions.skill_id`
指向 `skills.id`，且是 CASCADE）。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（开发期的真实形态）
==============================================================================
`core/database.py::init_db()` 在 `config.environment == "development"` 时
对 `Base.metadata` 跑一次 `create_all`。而 `register_all_models()` 里已经
包含了本次这两个新模型 ⇒ **第一次启动就把表建出来了**。

此后 `alembic upgrade head` 再 `CREATE TABLE` 会抛
`DuplicateTable: relation "skills" already exists` ——
而那恰恰是"本该顺利"的场景（第 177 轮实测踩过：库里"半新"的状态最容易发生）。

⇒ 用 `_has_table` 守卫，与 `d4a7b2e8c1f6` 的 `_has_column` 同款。

==============================================================================
★ 反向迁移
==============================================================================
`drop_table` 顺序必须**先子后父**：`skill_revisions.skill_id` 有外键指向
`skills.id`，先删父表会被 PG 以外键依赖拒绝（除非 CASCADE，但那会掩盖顺序问题）。
「概念删了不能留库不读」—— 两张表一起退掉，不会出现"表还在、代码不用"的残渣。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8c2f5a7b3d9'
down_revision: Union[str, Sequence[str], None] = 'd4a7b2e8c1f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILLS = 'skills'
_REVISIONS = 'skill_revisions'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_SKILLS):
        op.create_table(
            _SKILLS,
            sa.Column('id', sa.String(length=64), nullable=False),
            # 技能标识：全局唯一（见 modules/skills/db_model.py 的论证）
            sa.Column('name', sa.String(length=64), nullable=False),
            sa.Column('title', sa.String(length=128), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            # 第二级披露的内容（按需加载）
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('tools', sa.JSON(), nullable=True),
            sa.Column('version', sa.String(length=32), nullable=True),
            sa.Column('visibility', sa.String(length=16), nullable=True),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('enabled_agents', sa.JSON(), nullable=True),
            # 归属三件套（与 stores_store 逐字段同形）
            sa.Column('owner_id', sa.String(length=36), nullable=True),
            sa.Column('account_id', sa.String(length=36), nullable=True),
            sa.Column('is_demo', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ['owner_id'], ['users.id'],
                name='fk_skills_owner_id_users', ondelete='SET NULL',
            ),
            sa.ForeignKeyConstraint(
                ['account_id'], ['accounts.id'],
                name='fk_skills_account_id_accounts', ondelete='SET NULL',
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_skills_name'), _SKILLS, ['name'], unique=True)
        op.create_index(op.f('ix_skills_owner_id'), _SKILLS, ['owner_id'], unique=False)
        op.create_index(op.f('ix_skills_account_id'), _SKILLS, ['account_id'], unique=False)

    if not _has_table(_REVISIONS):
        op.create_table(
            _REVISIONS,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('skill_id', sa.String(length=64), nullable=False),
            sa.Column('version', sa.String(length=32), nullable=True),
            # 变更后的正文快照（不可变）
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('note', sa.String(length=255), nullable=True),
            sa.Column('action', sa.String(length=16), nullable=True),
            sa.Column('changed_by', sa.String(length=36), nullable=True),
            sa.Column('changed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ['skill_id'], ['skills.id'],
                name='fk_skill_revisions_skill_id_skills', ondelete='CASCADE',
            ),
            sa.ForeignKeyConstraint(
                ['changed_by'], ['users.id'],
                name='fk_skill_revisions_changed_by_users', ondelete='SET NULL',
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_skill_revisions_skill_id'), _REVISIONS, ['skill_id'], unique=False
        )
        op.create_index(
            op.f('ix_skill_revisions_changed_by'), _REVISIONS, ['changed_by'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    # 先子后父（外键依赖）
    if _has_table(_REVISIONS):
        op.drop_index(op.f('ix_skill_revisions_changed_by'), table_name=_REVISIONS)
        op.drop_index(op.f('ix_skill_revisions_skill_id'), table_name=_REVISIONS)
        op.drop_table(_REVISIONS)
    if _has_table(_SKILLS):
        op.drop_index(op.f('ix_skills_account_id'), table_name=_SKILLS)
        op.drop_index(op.f('ix_skills_owner_id'), table_name=_SKILLS)
        op.drop_index(op.f('ix_skills_name'), table_name=_SKILLS)
        op.drop_table(_SKILLS)

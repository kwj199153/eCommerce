"""新建 prompt_versions 表：提示词覆写层（第 351 轮 · P0-7 B 档）

Revision ID: l8d5e2a9c3f6
Revises: k7e2c4f1b849
Create Date: 2026-10-01 12:40:00.000000

==============================================================================
★ 纯新增表，零 ALTER / 零 DROP / 零外键
==============================================================================
只建一张 `prompt_versions`。它与 `e8c2f5a7b3d9`（skills 两张表）同风险档：
新表最坏情况是"建多了"，删掉即可。**没有外键**也是刻意的 —— 覆写是
平台级配置（不属于任何租户），唯一可空的人字段 `created_by` 故意不建外键：
操作者账号被删不该让一条现役提示词配置跟着消失。
⇒ `downgrade()` 直接 `drop_table` 即可，无需考虑引用方。

==============================================================================
★ 幂等：`create_all()` 会抢先建表（与 e8c2f5a7b3d9 / b4e8f2c6a1d7 同一个坑）
==============================================================================
`register_all_models()` 里已包含 `PromptVersion`（见 `wiring.MODEL_MODULES`）
⇒ development 启动时 `create_all` 就把表建出来了，此后
`alembic upgrade head` 再 `CREATE TABLE` 会抛
`DuplicateTable: relation "prompt_versions" already exists`。
★ 本仓实测过的正是这种"半新"状态（第 177 轮踩过）⇒ `_has_table` 守卫。

==============================================================================
★ 列属性必须与 ORM **逐列刚性对齐**（不是风格问题）
==============================================================================
本仓吃过一次亏（`k7e2c4f1b849` 的文件头）：`e8c2f5a7b3d9` 把一批列写成
`nullable=True`，而 ORM 侧是非 Optional ⇒「迁移建出的库」比
「`create_all` 建出的库」宽松，`alembic check` 在全新库上报 12 条
`modify_nullable`。对应关系是刚性的：

    `Mapped[X]`            ⇒ `nullable=False`
    `Mapped[Optional[X]]`  ⇒ `nullable=True`

对照 `modules/prompt_versions/db_model.py`：
    id / name / content / version / fingerprint / base_fingerprint /
    enabled / created_at / updated_at        ⇒ NOT NULL
    note / created_by                        ⇒ NULL

★ 索引与唯一约束：`name` 在 ORM 是 `unique=True, index=True` ⇒ SQLAlchemy
  生成的是**具名唯一索引** `ix_prompt_versions_name`（不是无名的
  `UNIQUE` 约束）。这里必须照抄成 `create_index(..., unique=True)`
  —— 写成 `sa.UniqueConstraint('name')` 会让两条建表路径产出**不同名字**
  的约束（PG 给无名约束起 `prompt_versions_name_key`），`alembic check`
  在全新库上会报一条本可避免的偏差。

★ 没有 `server_default`：ORM 侧的 `default=` 全是 **Python 侧**默认值
  （`version="1"` / `enabled=True` / `datetime.utcnow`）⇒ 建表 DDL 里
  不该出现 `DEFAULT`。加了反而会让两条路径不一致（create_all 不加）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l8d5e2a9c3f6'
down_revision: Union[str, Sequence[str], None] = 'k7e2c4f1b849'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'prompt_versions'


def _has_table(table: str) -> bool:
    """表是否已在库里（理由见文件头「幂等」一节）。"""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('version', sa.String(length=16), nullable=False),
            sa.Column('fingerprint', sa.String(length=16), nullable=False),
            sa.Column('base_fingerprint', sa.String(length=16), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_by', sa.String(length=64), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        # ★ unique 索引（不是 UniqueConstraint）—— 与 ORM 的
        #   `unique=True, index=True` 对齐，理由见文件头。
        op.create_index(
            op.f('ix_prompt_versions_name'), _TABLE, ['name'], unique=True
        )
        op.create_index(
            op.f('ix_prompt_versions_enabled'), _TABLE, ['enabled'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema.

    ★ 先删索引再删表：PG 会随表删索引，但显式 drop 让 downgrade 在
      "索引被人手工删过"的半坏状态下也能跑通。
      没有别的表引用 `prompt_versions`（零外键）⇒ 无需先动子表。
    """
    if _has_table(_TABLE):
        op.drop_index(op.f('ix_prompt_versions_enabled'), table_name=_TABLE)
        op.drop_index(op.f('ix_prompt_versions_name'), table_name=_TABLE)
        op.drop_table(_TABLE)

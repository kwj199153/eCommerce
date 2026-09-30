"""skills 加 tags 列：自定义标签（第 194 轮 · 技能仓库筛选/分组）

Revision ID: a3c7e1b5d9f2
Revises: f1906a3c8e5b
Create Date: 2026-09-18 13:20:00.000000

==============================================================================
★ 与 f1906a3c8e5b（加 icon）同款：给**已有表**加列
==============================================================================
`tags` 是**用户自由命名**的标记（「选品」「广告」「差评」「合规」），
已有行补 NULL 即可 —— `NULL` 与 `[]` 在业务层同义（都是"没有标签"），
两者的差别只在于「这条技能从没被贴过标签」与「被贴过又被清空」，
而当前没有任何判定依赖这个差别 ⇒ 不回填、不加 `server_default`。

★ 为什么是 JSON 列而不是关联表：见 `modules/skills/db_model.py` 中
  `tags` 字段上方的论证（判据 = 访问模式：标签无独立生命周期、随技能整体读写）。

==============================================================================
★ 幂等：`create_all()` 在全新库上会抢先带上这一列
==============================================================================
`init_db()` 在 development 下对 `Base.metadata` 跑 `create_all`，而
`SkillRecord` 已声明 `tags` ⇒ 全新库启动时表就自带该列，此后
`alembic upgrade head` 再 `ADD COLUMN` 会抛
`DuplicateColumn: column "tags" of relation "skills" already exists`。
⇒ `_has_column` 守卫，与 `f1906a3c8e5b` / `d4a7b2e8c1f6` 同款。

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 真的 `drop_column` —— 「概念删了不能留库不读」：
留着一个没有代码读写的 JSON 列，下次看 schema 的人会以为它在用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c7e1b5d9f2'
down_revision: Union[str, Sequence[str], None] = 'f1906a3c8e5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'skills'
_COLUMN = 'tags'


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    """列是否已在库里（理由见文件头「幂等」一节）。

    ★ 先判表存在再取列：`get_columns()` 对不存在的表会抛，
      而"表不存在"是完全合法的输入（空库先跑 upgrade 的场景）。
    """
    if not _has_table(table):
        return False
    return column in {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)

"""skills 加 icon 列：技能图标（emoji）（第 188 轮）

Revision ID: f1906a3c8e5b
Revises: e8c2f5a7b3d9
Create Date: 2026-09-20 21:30:00.000000

==============================================================================
★ 这次是「给**已有表**加列」—— 与 e8c2f5a7b3d9（纯新增表）是两种风险等级
==============================================================================
新表最坏是"建多了"；加列则要面对「已有行怎么补值」。
本例的答案很干净：`icon` 是**装饰性元数据**，已有行补 `''`（空串）即可 ——
不需要回填任何业务值，也不会因为空值在别处报错（前端按 `icon || 兜底` 渲染）。

★ 默认值写在**代码**（`db_model.SkillRecord.icon` 的 `default=""`）而不是
  数据库的 `server_default`：本仓的写入路径全部经 ORM，从未有裸 SQL 插入
  （唯一例外是 seed 与探针，它们也走 ORM）。加 `server_default` 会多一份
  "默认值"的真源，将来改口径必漏一处。

==============================================================================
★ 幂等：`create_all()` 在**全新库**上会抢先带上这一列
==============================================================================
`core/database.py::init_db()` 在 `environment == "development"` 时对
`Base.metadata` 跑 `create_all`，而 `SkillRecord` 已经声明了 `icon`
⇒ 全新库启动时 `skills` 表**自带** `icon` 列，
此后 `alembic upgrade head` 再 `ADD COLUMN` 会抛
`DuplicateColumn: column "icon" of relation "skills" already exists`。

⇒ 用 `_has_column` 守卫，与 `d4a7b2e8c1f6`（stores 加 is_demo）同款。
  这是本仓"迁移必须幂等"那条铁律的第 N 次应用 —— 它抓的是**开发期**的真实形态，
  而不是"CI 里从零跑一遍"能暴露的问题。

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 真的 `drop_column`。
「概念删了不能留库不读」—— 若只删代码不删列，那个列会变成一个
**没有任何代码读写的字段**，下一次有人看 schema 会以为它在用。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1906a3c8e5b'
down_revision: Union[str, Sequence[str], None] = 'e8c2f5a7b3d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'skills'
_COLUMN = 'icon'


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
            sa.Column(_COLUMN, sa.String(length=16), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)

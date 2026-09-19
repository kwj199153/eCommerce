"""memory: memory_entries 补 `ordinal` 列（第 149 轮批 C2）

Revision ID: c9e5f3a7d4b6
Revises: b8d4e2f6c3a5
Create Date: 2026-09-18 14:05:00.000000

==============================================================================
★ 为什么必须补这一列：**顺序是用户内容的一部分**
==============================================================================
上一版（`b8d4e2f6c3a5`）建 `memory_entries` 时没有位置字段，当时的想法是
"条目是一个集合，顺序由分节决定"。写服务层时发现这个想法站不住：

  1. `render_markdown()` 只重排**分节**的顺序（`ordered_sections`：具名分节按
     规范顺序，自定义标题按首次出现顺序），**组内顺序原样保留** ——
     也就是说组内顺序的唯一来源就是"读出来时列表的顺序"。
  2. 而读出来时的顺序若由 `created_at, id` 决定，则保存一次之后
     所有新行的 `created_at` 几乎相同、`id` 是随机 hex ⇒ 组内顺序**变成随机的**。
  3. 用户体验：在编辑器里把「关注重点」的 1/2/3/4 排好 → 保存 → 再看，
     顺序变了。这不是"少了一个 feature"，而是**系统在乱动用户的内容**，
     且下一次保存会把它再打乱一次。
     （假页面里的样例内容恰好就是编号 1~4 的列表 —— 这种内容最怕被重排。）

⇒ 位置必须落库。用 `ordinal`（该 owner 内从 0 起的连续整数），
  由服务层在整批替换时按提交顺序写入。

==============================================================================
★ 为什么是"新增一列"的独立迁移，而不是回头改上一个迁移
==============================================================================
上一版迁移已经在本机跑过（`alembic_version = b8d4e2f6c3a5`），
且有开发期的 `create_all` 已经建出了这三张表的库存在。回头去改
`b8d4e2f6c3a5` 会造成「库里已记录该版本、但实际结构比该版本少一列」的
**半新状态** —— 此后 `alembic upgrade head` 直接 no-op，而 ORM 期待 `ordinal`，
症状是"迁移说成功、查询说没有那一列"。
⇒ 只改已发布的迁移是不行的，必须**往前开一个新 revision**。

==============================================================================
★ `server_default` 只在这一步存在
==============================================================================
`ADD COLUMN ... NOT NULL` 在已有数据的表上必须给默认值（否则 PG 无法为
既有行补值）。但补完就把它**摘掉**：留着的话 `ordinal` 的默认值就有了
两个真源（SQL 一份、ORM 的 Python 侧一份），而这正是上一版迁移的
docstring 明确反对的形态。摘掉之后，"默认值"重新只剩 ORM 一处。

★ 反向迁移只 `drop_column`，不动别的列、不删表：这一列是"加出来的"，
  回退就该只把它退掉。**概念删了不能留库不读** —— 列没了，
  服务层的 `ordinal` 就真的没有来源了，不会出现"库里有、代码不用"的残渣。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e5f3a7d4b6'
down_revision: Union[str, Sequence[str], None] = 'b8d4e2f6c3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENTRIES = 'memory_entries'
_COLUMN = 'ordinal'


def _has_column(table: str, column: str) -> bool:
    """表与列是否都已在库里。

    ★ 与上一版同一个理由：开发期 `create_all` 用**同一份** `Base.metadata`
      建表，新库启动过一次之后就带上 `ordinal` 了；此后 `alembic upgrade head`
      再 `ADD COLUMN` 会抛 `DuplicateColumn` —— 而那恰恰是"本该顺利"的场景。
      同时判表在不在：全新空库上先跑 `upgrade` 时它还没有。
    """
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column(_ENTRIES, _COLUMN):
        op.add_column(
            _ENTRIES,
            # server_default 只为"给既有行补一个值"而存在，下一步就摘掉。
            sa.Column(_COLUMN, sa.Integer(), nullable=False, server_default='0'),
        )
        op.alter_column(_ENTRIES, _COLUMN, server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column(_ENTRIES, _COLUMN):
        op.drop_column(_ENTRIES, _COLUMN)

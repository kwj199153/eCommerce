"""退役「自定义标签」概念：drop skills.tags（第 195 轮）

Revision ID: c5f9a3e7b2d8
Revises: b4e8f2c6a1d7
Create Date: 2026-09-21 02:30:00.000000

==============================================================================
★ 为什么要删（不是「改需求」，是「这个概念被数据证伪」）
==============================================================================
第 194 轮按老板要求的「方案 B：自定义标签」加了 `skills.tags` 列 + 顶部
「按标签筛选」下拉 + 卡片上的 `#标签` chips。

第 195 轮老板给了截图并说：「筛选过滤按钮两行改一行……**删除标签相关内容**」。

复核后确认这不是"改主意"，而是该功能**从未成立**：

  · 全仓**没有任何录入入口** —— 新建/编辑表单里没有 tags 输入框；
    `stores/skills.ts` 的 `create()` / `update()` 虽然会把 payload 原样透传，
    但 UI 从不填这个字段；
  · ⇒ 库里的 `tags` 永远是 `NULL`/空 ⇒ **顶部筛选器永远筛出 0 条**；
  · ⇒ 一个「筛不出东西的筛选项」占着工具栏一行，是纯粹的负资产。

本仓判据（`refuted-concept-removal`）：**概念被证伪就整体退役** ——
列 / API 出参 / UI 标签 / 筛选器 / 测试一起清除，而不是留着半套。
留着半套的代价是双份：用户以为能筛（其实不能），下一个人以为它是活的（其实不是）。

==============================================================================
★ 幂等
==============================================================================
`create_all()` 从不删列 ⇒ 开发库里这一列一直会在（它与 ORM 已不一致，
但 `create_all` 不管）。所以 `upgrade()` 必须**探测存在性**，
否则 `DROP COLUMN` 在已被手工删过的库上会抛 `UndefinedColumn`。

==============================================================================
★ 反向迁移（`downgrade`）
==============================================================================
可以**把列加回来**，但**加不回数据** —— 列一删，值就没了。
这与 `a3c7e1b5d9f2`（当初加这一列）的 `upgrade` 同形，
保证「降级再升级」在两条路径上都能往返（`tests/test_schema_parity.py`
与空库往返实测都依赖这一点）。

★ 迁移前已在探针里确认过：库里该列**全为 NULL**（无真实用户数据可丢）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f9a3e7b2d8'
down_revision: Union[str, Sequence[str], None] = 'b4e8f2c6a1d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'skills'
_COLUMN = 'tags'


def _has_column(table: str, column: str) -> bool:
    """列是否还在（理由见文件头「幂等」一节）。"""
    cols = {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
    return column in cols


def upgrade() -> None:
    """Upgrade schema."""
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
    else:
        print(f'[{revision}] {_TABLE}.{_COLUMN} 已不存在，跳过 drop_column')


def downgrade() -> None:
    """Downgrade schema（恢复列，但**不恢复数据** —— 值已随列删除）。"""
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))

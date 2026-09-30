"""skills 加 as_shortcut 列：是否在对话页显示为快捷卡片（第 248 轮）

Revision ID: d6a1b3c8e4f7
Revises: c5f9a3e7b2d8
Create Date: 2026-09-24 12:30:00.000000

==============================================================================
★ 为什么加这一列（老板原话）
==============================================================================
「我看了【复盘结论写法】是被周报月报**引用**的，那么这个【复盘结论写法】是否不应该
出现在快捷卡片栏，是直接在 skill 仓库中取消【启用】该技能吗？还是需要增加额外按钮」

复核后的结论：**没有"零改动的正确解法"**。
`enabled` / `enabled_agents` 一组值被**三处**消费，且共用同一套过滤条件：
    · 技能目录注入（第一级披露）`modules/skills/provider.py::build_catalog_for`
    · 正文加载（第二级披露）    `modules/skills/service.py::read_skill_for_agent`
    · 前端快捷卡片             `frontend/src/stores/skills.ts::skillsOfAgent`

⇒ 取消【启用】能让卡片消失，但**同时**让周报 / 广告效果复盘 / 行动计划正文里
  那三处「表达结构沿用「复盘结论写法」」变成**悬空引用**，
  且 `_load_skill` 会把「没有找到名为 … 的技能（它可能未启用、不存在、或不属于当前账号）」
  交给模型 —— 结构定义**整体丢失**。
而在前端加一份隐藏名单 = 第二份实现（本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到）。

⇒ 拆出本列，只承担「要不要给它一张卡片」。

==============================================================================
★ 加列的三个具体决定
==============================================================================
① **`nullable=False` + 临时 `server_default`**：
   本表**已有行**（演示账号 22 条 + 用户自建）。`ADD COLUMN … NOT NULL`
   在非空表上必须能给出旧行的值，所以先带 `server_default=true` 做**回填**。
   ⇒ 这与 `f1906a3c8e5b`（加 `icon`）刻意不同：那一列可空、旧行补 `NULL` 无害；
     本列是布尔判定位，"旧行取到 NULL"会让 `bool(None) is False` ⇒ 卡片全没了。

② **回填完立刻 `alter_column(server_default=None)`**：
   本仓既有口径是「默认值写在**代码**（ORM 的 `default=`），不写数据库」——
   理由是 `server_default` 会让"默认值"多一份真源，将来改口径必漏一处。
   带默认值加列是**一次性回填手段**，用完即撤，最终 DDL 与 `create_all` 建出来的
   完全一致（否则"已有库"与"全新库"两张 schema 会静默分叉）。
   ★ `alembic check` 默认不比较 server_default，所以撤销与不撤销它都不报；
     正因如此**必须由人写对**，不能靠门禁兜。

③ **默认 True = 保持现行为**：21 条技能一行不改；只有被判定为「规矩型」的
   `weekly-review-narrative` 在 `seed.DEMO_SKILLS` 里显式标 `as_shortcut: False`。

==============================================================================
★ 幂等（本仓铁律：迁移必须幂等）
==============================================================================
`core/database.py::init_db()` 在 development 下对 `Base.metadata` 跑 `create_all`，
而 `SkillRecord` 已声明本列 ⇒ **全新库**启动时 `skills` 表自带到它，
此后 `alembic upgrade head` 再 `ADD COLUMN` 会抛 `DuplicateColumn`。
⇒ 用 `_has_column` 守卫，与 `d4a7b2e8c1f6` / `f1906a3c8e5b` 同款。

★ 注意两条路径的**列形态不同**：`create_all` 建的列没有 `server_default`
  （ORM 的 `default=True` 是 Python 侧默认，不进 DDL）。守卫命中时列已存在，
  我们**不能**再补 `server_default`（那是给旧行回填用的，而这一路径上没有旧行）——
  直接跳过即可，两个环境的终态一致。

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 真的 `drop_column`。「概念删了不能留库不读」：只删代码不删列，
那个列会变成**没有任何代码读写的字段**，下一个人看 schema 会以为它在用。
（代价：卡片开关的用户设置会丢 —— 它可由 seed 对账重建，不是不可再生数据。）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6a1b3c8e4f7'
down_revision: Union[str, Sequence[str], None] = 'c5f9a3e7b2d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'skills'
_COLUMN = 'as_shortcut'


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
    if _has_column(_TABLE, _COLUMN):
        # 全新库路径：`create_all()` 已按 ORM 建好这一列（无 server_default）。
        # ⇒ 跳过即可，**不要**再补 server_default，否则两个环境的 DDL 会分叉。
        print(f'[{revision}] {_TABLE}.{_COLUMN} 已存在（create_all 建过），跳过 add_column')
        return

    # ① 带 server_default 加列 ⇒ 已有行的值一次性回填为 true（= 保持现行为）。
    #    ★ `comment` 必须与 ORM 的 `mapped_column(..., comment=...)` **逐字一致**：
    #      `alembic check` 会比对列注释，漏了就是一条 `modify_comment` 偏差
    #      （本轮实测：漏写后 check 报 FAILED，补上才归零）。
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="在 Agent 对话页显示为快捷卡片（第 248 轮）",
        ),
    )
    # ② 回填完毕，撤掉数据库侧默认值 —— 默认值的唯一真源是 ORM 的 `default=True`。
    #    ★ 带上 `existing_*`：让离线（`--sql`）渲染也能写出正确的 ALTER 语句，
    #      且避免 alembic 顺手把列注释一起改写掉。
    op.alter_column(
        _TABLE,
        _COLUMN,
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=False,
        existing_comment="在 Agent 对话页显示为快捷卡片（第 248 轮）",
    )


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
    else:
        print(f'[{revision}] {_TABLE}.{_COLUMN} 已不存在，跳过 drop_column')

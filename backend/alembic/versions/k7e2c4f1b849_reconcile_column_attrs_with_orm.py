"""reconcile: 让「纯迁移建出的库」与 ORM 完全一致（16 处列属性）

Revision ID: k7e2c4f1b849
Revises: j6c4b9e1f3a5
Create Date: 2026-09-30 13:45:00.000000

==============================================================================
★ 这条迁移修的**不是新缺陷**，而是一类「早已存在、且一直在让 CI 变红」的偏差
==============================================================================
起因：`alembic check` 在本轮之前报 **2 条**（只在**开发库**上看得见的那种）。
但把同一命令放到**纯 `alembic upgrade head` 建出的全新库**上跑，它报 **14 条**。
两者相加（去重）就是本迁移要收敛的 **16 处**。

★ 为什么两个库差这么多 —— 这正是本仓 `ci.yml` 注释里那句
  「『本地全绿』推不出『CI 全绿』」的又一次实例化：

    · **开发库**的 `skills` / `skill_revisions` / `market_snapshots` 表，
      当年是被 `core/database.py::init_db()` 的 `create_all()` **按 ORM 建出来的**
      ⇒ 那些列的 `nullable` / `comment` 一开始就是 ORM 的样子，
      手写迁移里的错误声明被 `_has_column` / `_has_table` 守卫**跳过**了；
    · **CI 的库**是全新空容器，只跑 `alembic upgrade head`
      ⇒ 同一批表由**手写迁移**建出 ⇒ 它们声明错什么，库里就是什么。

⇒ 两个口径**都要修**，缺一个就有半边永远是红的。

==============================================================================
★ 16 处的完整清单与**根因迁移**
==============================================================================
【A】开发库可见的 2 处（`compare_metadata` 三元组，逐字抄自实测输出）

    [('modify_nullable', None, 'skills', 'icon',
      {'existing_type': VARCHAR(length=16), 'existing_server_default': False,
       'existing_comment': None}, True, False)]

    [('modify_comment', None, 'stores_store', 'is_demo',
      {'existing_nullable': False, 'existing_type': BOOLEAN(),
       'existing_server_default': False},
      None, '演示店铺：仅对「无身份」的演示请求可见（第 175 轮）')]

    根因：`f1906a3c8e5b`（skills 加 icon，第 188 轮）声明 `nullable=True`；
          `d4a7b2e8c1f6`（stores_store 加 is_demo，第 175 轮）加列时漏了 `comment=`。

【B】只在**全新库**上出现的 14 处

    12 条 `modify_nullable`（existing=True → new=False），根因全是
    `e8c2f5a7b3d9`（skills / skill_revisions 建表，第 181 轮）把一批列
    声明成了 `nullable=True`，而 ORM 侧全是非 `Optional` 的 `Mapped[...]`：

        skills            title / description / content / version / visibility
                          created_at / updated_at
        skill_revisions   version / content / note / action / changed_at

     2 条 `modify_comment`（`is_demo` 建表时漏了列注释）：
        skills            is_demo  ← `e8c2f5a7b3d9`（第 181 轮）
        market_snapshots  is_demo  ← `i5b3a8d0e2c4`（第 305 轮）

★ 共同成因**只有一个**：**每条迁移只写了 schema 的一半**。
  `ADD COLUMN ... NULL` / `CREATE TABLE (c X)` 在任何库上都合法
  ⇒ 「能不能建」永远不会报错；只有「和 ORM 一不一致」会被 `alembic check` 看见。
  同一个坑已经在 `d6a1b3c8e4f7`（skills.as_shortcut）踩过一次并留了注释警告
  —— 本迁移是把剩下的全部补齐。

★ 这条债记在案上很久了（`.workbuddy/memory/DETAILS/技能与意图路由.md` 第 149 行：
  「`alembic check` 有两条既有偏差（**本轮未动，越界**）」）。
  "越界"当时是对的 —— 但代价是 `ci.yml` 的「迁移链完整性自检 ③」
  （`set -e` + `python -m alembic check`）从那天起就没绿过。
  一条常年红的门禁等于没有门禁：没人会去看一个总是失败的东西。

==============================================================================
★ 方向：以 **ORM 为真源**，改库（不是改 ORM）
==============================================================================
`alembic check` 的语义就是「库有没有落后于 ORM」。16 处**全是库侧缺属性**
（可空性太松 / 缺列注释）⇒ 一律**收紧库**。

★ 反向（改 ORM 去迁就库）是错的：
  · 把这 12 列改成 `Mapped[Optional[...]]`，等于宣称「技能可以没有标题、
    没有正文，版本修订可以没有时间」—— 而它们在 ORM 侧每一列都带
    Python `default`（`""` / `"1.0.0"` / `"account"` / `"update"` /
    `datetime.utcnow`）⇒ 这是**声明式的"必有值"**，不是"可以不填"；
  · 把三个 `is_demo` 的 `comment=` 删掉，等于用「删文档」消除「文档不同步」。

==============================================================================
★ 回填策略：**只回填「加列必然产生」的 NULL，不编造历史**
==============================================================================
只有一处需要回填 —— `skills.icon`：

  `f1906a3c8e5b` 是在**已有数据**的表上加列，且 `nullable=True`、无
  `server_default` ⇒ PG **必然**把当时所有既有行的 `icon` 填成 NULL。
  回填值选 `''` 而非别的：它**就是**该列的空语义（`db_model.py` 写明
  「空串 = 没生成 / 用户没填」，兜底渲染归前端）。

其余 15 处**刻意不回填**，理由不是偷懒而是**语义**：

  · 那 12 列是**随建表一起**创建的（不是 `ADD COLUMN`）⇒ 不存在"被 PG 填成
    NULL"的必然性；经 ORM 的任何写入都会带上 Python default。库里若真有 NULL，
    那是**经裸 SQL 写入的数据异常**，需要人来判定该补什么值；
  · 三个时间戳列（`skills.created_at/updated_at`、`skill_revisions.changed_at`）
    和 `skill_revisions.action` 尤其如此 —— 拿 `now()` 或 `'update'` 去填，
    等于**编造"这行是何时/怎么来的"**。本仓判据「禁静默退化」「假数据不许
    冒充实测」的反面正是这个：宁可让 `SET NOT NULL` **当场报错并指出是哪一列**，
    也不要写一个看起来体面的谎言。

★ 实测（2026-09-30，`.workbuddy/probes/r330_fresh_diff.json`）：
  开发库这 15 列 `attnotnull` 全为 `true`、NULL 计数**全为 0**
  （行数 21 / 23 / 44）；全新库 0 行。⇒ 不回填在任何可达路径上都不会触发。

==============================================================================
★ 幂等性
==============================================================================
  · `UPDATE ... WHERE icon IS NULL` —— 二次执行为 0 行；
  · `ALTER COLUMN ... SET NOT NULL` —— 对已是 NOT NULL 的列是 no-op（不抛）；
  · `COMMENT ON COLUMN ... IS '...'` —— 覆盖写。

⇒ 在「由 `create_all()` 建出的全新开发库」上（那里 ORM metadata 直接建出
  NOT NULL + 注释），本迁移是**彻底的 no-op** —— 因此**刻意不加**
  `_has_column` 守卫：那种守卫是给 `add_column` 用的，这里没有 `add_column`，
  也不需要"跳过"语义（真跳过就等于把偏差留在库里）。

==============================================================================
★ 为什么不去改那三条**根因**迁移
==============================================================================
`e8c2f5a7b3d9` / `i5b3a8d0e2c4` / `d4a7b2e8c1f6` 都已经在真实库上跑过，
且都带 `_has_table` / `_has_column` 守卫 ⇒ 改它们**不会**改变任何已存在的库，
只会让"迁移文件"与"库的实际来历"对不上。而本迁移无论如何都必须存在
（要修已存在的库）⇒ 改历史是纯粹的额外风险、零额外收益。
（同款判断见 `a506249ae3e3_reconcile_drop_redundant_legacy_.py`：它同样只做
 "把历史库对齐到基线"，没有回头改历史迁移。）

==============================================================================
★ 反向迁移
==============================================================================
`downgrade()` 把 16 处**退回偏差态**（注释清空、可空性放开）。
它存在的意义不是"我们想回去"，而是：**一条不能回退的迁移无法被验证**
—— 回退后 `alembic check` 必须**重新报出那 16 条**。这是本迁移唯一可用的
"反向注入"，也是它「真的改了这些属性」的证据。

★ 一处**刻意的口径分歧**，必须写清：`downgrade()` 把可空性退回
  `e8c2f5a7b3d9` 当年**声明的**形态（`nullable=True`）—— 那是**迁移链的定义**。
  对「当年由 `create_all` 建表」的库（如本机开发库），它自己的过去其实是
  NOT NULL ⇒ 回退后该库会与自己的历史不同。这不是回退写错了，而是
  「链上定义」与「历史偶然」本来就有分歧 —— 迁移只能回退到链上的前一个状态。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k7e2c4f1b849'
down_revision: Union[str, Sequence[str], None] = 'j6c4b9e1f3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILLS = 'skills'
_ICON = 'icon'
_ICON_TYPE = sa.String(length=16)

# ====== 【A】开发库可见的 2 处 ======
# ★ `comment` 必须与 ORM 的 `mapped_column(..., comment=...)` **逐字一致**
#   （差一个字符，`alembic check` 就会再报一条 `modify_comment`）。
#   同款警告见 `d6a1b3c8e4f7_skills_add_as_shortcut.py`。
_STORES = 'stores_store'
_STORES_IS_DEMO_COMMENT = "演示店铺：仅对「无身份」的演示请求可见（第 175 轮）"

# ====== 【B】只在全新库上出现的 14 处 ======
# (表, 列) —— 建表时被声明成 nullable=True，ORM 侧为非 Optional ⇒ 收紧为 NOT NULL。
# ★ 不写 `existing_type`：PG 的 `SET NOT NULL` 不需要它，而**手写类型**会多出
#   一份与 ORM 并列的真源（类型若变，两处必漂）。缺类型时的渲染正确性由本迁移
#   的往返实测（探针 r330_ci_roundtrip.py）兜住。
_TIGHTEN_NOT_NULL = (
    (_SKILLS, 'title'),
    (_SKILLS, 'description'),
    (_SKILLS, 'content'),
    (_SKILLS, 'version'),
    (_SKILLS, 'visibility'),
    (_SKILLS, 'created_at'),
    (_SKILLS, 'updated_at'),
    ('skill_revisions', 'version'),
    ('skill_revisions', 'content'),
    ('skill_revisions', 'note'),
    ('skill_revisions', 'action'),
    ('skill_revisions', 'changed_at'),
)

# (表, 列, 类型, 注释) —— 建表时漏了列注释。
_MARKET = 'market_snapshots'
_ADD_COMMENTS = (
    (_SKILLS, 'is_demo', sa.Boolean(), "演示技能：仅对「无身份」的演示请求可见（第 181 轮）"),
    (_MARKET, 'is_demo', sa.Boolean(), "演示 mock 标记：读层据此显式标注 degraded（第 305 轮）"),
)


def upgrade() -> None:
    """Upgrade schema."""
    # ① skills.icon：先回填（唯一有"必然 NULL"的一处，理由见文件头），再收紧。
    op.execute(f"UPDATE {_SKILLS} SET {_ICON} = '' WHERE {_ICON} IS NULL")
    op.alter_column(
        _SKILLS,
        _ICON,
        existing_type=_ICON_TYPE,
        nullable=False,
    )

    # ② 12 列收紧为 NOT NULL（不回填，理由见文件头「回填策略」）。
    for table, column in _TIGHTEN_NOT_NULL:
        op.alter_column(table, column, nullable=False)

    # ③ 补 3 处列注释（含 A 组里的 stores_store.is_demo）。
    #    ★ 带上 `existing_nullable`：让离线（`--sql`）渲染也能写出正确的
    #      ALTER 语句，且避免 alembic 顺手把可空性一起改写掉。
    op.alter_column(
        _STORES,
        'is_demo',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        comment=_STORES_IS_DEMO_COMMENT,
    )
    for table, column, type_, text in _ADD_COMMENTS:
        op.alter_column(
            table,
            column,
            existing_type=type_,
            existing_nullable=False,
            comment=text,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # ① 清掉 3 处列注释（`comment=None` 才是"删"，默认的 `False` 是"不动"）。
    #    `existing_comment` 传当前值：只为离线渲染的正确性。
    for table, column, type_, text in _ADD_COMMENTS:
        op.alter_column(
            table,
            column,
            existing_type=type_,
            existing_nullable=False,
            comment=None,
            existing_comment=text,
        )
    op.alter_column(
        _STORES,
        'is_demo',
        existing_type=sa.Boolean(),
        existing_nullable=False,
        comment=None,
        existing_comment=_STORES_IS_DEMO_COMMENT,
    )

    # ② 12 列放回可空（= 恢复 `e8c2f5a7b3d9` 当年声明的形态）。
    for table, column in _TIGHTEN_NOT_NULL:
        op.alter_column(table, column, nullable=True)

    # ③ skills.icon 放回可空（= 恢复 `f1906a3c8e5b` 当年的形态）。
    op.alter_column(
        _SKILLS,
        _ICON,
        existing_type=_ICON_TYPE,
        nullable=True,
    )

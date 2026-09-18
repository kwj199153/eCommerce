"""accounts: 新增 kind 列（personal / team），回填每个 owner 名下最早的账户为 personal

Revision ID: e6b1a4c7d9f2
Revises: c4d9e2f1a6b3
Create Date: 2026-09-17 01:40:00.000000

==============================================================================
内容（B 档，2026-09-17）
==============================================================================
1. `accounts` 加 `kind` 列（String(16)，NOT NULL，server_default='team'）
2. **数据回填**：每个 `owner_user_id` 名下**最早**的账户置 `kind='personal'`，
   其余保持 `team`

★★★ 为什么回填口径必须与旧代码**完全等价**
「个人账户」在改造前是靠 `ensure_personal_account()` 里
「取 `owner_user_id` 名下最早的那个账户」来**指代**的。
本次改造把它显式化成 `kind` 列 —— 但**存量数据的可见行为不能变**，
否则这次改造就从"给概念起个名字"变成"顺手改了一次归属"。

所以回填规则与旧判据逐字对应：`owner_user_id` 分组、按 `(created_at, id)` 全序取首个。
⇒ 迁移前后，任何一次 `ensure_personal_account()` 调用都会返回**同一个**账户。

★ 顺序不能反：先 `add_column`（带 server_default 填 'team'）再回填。
  反过来（先回填后加列）会失败 —— 目标列还不存在。

==============================================================================
★ 后续变更（第 110 轮）—— 本迁移建出来的列已被删除
==============================================================================
本迁移回填的「personal = 每个 owner 最早的账户」这条口径，被实测**证伪**：
老板的容器「跨境1」被回填成 `personal`，而里面**坐着另一名成员李航**。

⇒ 「个人账户 / 团队账户」不是两种容器，而是**一个实体 + 成员数状态**。
   `kind` 列已由迁移 `b7e3f1a9c2d4` 删除，`AccountKind` 枚举已删。

  本迁移文件**保留为历史记录**（迁移链不可改写），不再代表当前 schema。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b1a4c7d9f2'
down_revision: Union[str, Sequence[str], None] = 'c4d9e2f1a6b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ====== 回填 SQL ======
#
# ★ `DISTINCT ON (owner_user_id) ... ORDER BY owner_user_id, created_at, id`
#   是 PostgreSQL 的"每组取第一行"，**正是**旧判据 `order_by(created_at, id).first()`
#   的 SQL 表达。两处用同一套 tie-breaker（(created_at, id) 全序），
#   保证"最早的"在 Python 侧与 SQL 侧是同一个定义 —— 否则边界上会漂移
#   （同一 created_at 的两行在两边排出不同顺序）。
#
# ★ 幂等：重复执行结果相同（UPDATE 到同一个集合）。
#   这类迁移偶会被人工重跑（中途失败后续跑），非幂等会静默改变归属。
#
# ★ 用 `IS DISTINCT FROM` 而不是 `<>`：`kind` 是 NOT NULL，两者等价；
#   但写成 IS DISTINCT FROM 后，即便将来改成可空也不会静默漏行。
_BACKFILL_PERSONAL = """
UPDATE accounts a
SET kind = 'personal'
FROM (
    SELECT DISTINCT ON (owner_user_id) id
    FROM accounts
    ORDER BY owner_user_id, created_at, id
) pick
WHERE a.id = pick.id
  AND a.kind IS DISTINCT FROM 'personal'
"""


def upgrade() -> None:
    """Upgrade schema."""
    # ① 先加列：server_default='team' 让存量行立刻有确定值（NOT NULL 才建得上）
    op.add_column(
        "accounts",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="team",
        ),
    )
    # ② 再回填：每个 owner 最早的账户 → personal（与旧判据等价）
    op.execute(_BACKFILL_PERSONAL)


def downgrade() -> None:
    """Downgrade schema.

    ★ 只删列，不做"把 personal 转回 team"之类的数据动作 ——
      `kind` 删除后，"个人账户"的语义重新退回给
      `ensure_personal_account()` 的"取最早"隐式规则，
      而回填正是按同一条规则算出来的 ⇒ 无需逆操作。
      （制造一次无意义的全表 UPDATE 只会增加 downgrade 的风险面。）
    """
    op.drop_column("accounts", "kind")

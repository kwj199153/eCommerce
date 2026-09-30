"""stores_store 补 `is_demo` 列：给演示模式一个**可隔离**的数据落点（第 175 轮）

Revision ID: d4a7b2e8c1f6
Revises: c9e5f3a7d4b6
Create Date: 2026-09-20 06:00:00.000000

==============================================================================
★ 为什么必须补这一列：演示模式**看得见数据**与**看不见真实店铺**不可兼得
==============================================================================
老板反馈：「演示模式下 UI 上看不到店铺、选品、素材、产品、业务话术、平台规则」。

实测（`.workbuddy/probes/p174_api.py`，10 个端点横打）根因只有一个：

    `core/auth/accounts.py::filter_accessible_stores`
        if user is None:
            return []          # ← 演示身份（无凭据 / demo-token）永远看不到店铺

这一行本身是**对的**——它来自安全修复 `4612abb`（改前是 `return list(stores)`，
即**匿名能拿走全库真实店铺**）。所以不能把它改回去，那会让演示档重新裸奔。

但「演示档下用户身无凭据」是**产品设定**，不是异常：
  · 前端 `demo-token` 不是身份（`isDemoToken()` 明确判定），`user 恒为 None`；
  · 于是 `/stores` 恒返回空 → 前端 `shopStore.shops` 恒为 `[]`
    → `current_shop_id` 永远写不进 localStorage → 所有业务请求不带 `X-Shop-ID`
    → 后端 `get_current_shop_id` 拿不到租户 ⇒ **每个面板都是空的**。

⇒ 缺的不是"放宽过滤"，而是**一个能且只能被演示身份看到的店铺**。
  这一列就是那个开关：`is_demo = true` 的店铺**只**对「无身份」的演示请求可见。

==============================================================================
★ 归属怎么填：演示店铺**刻意无主**（account_id / owner_id 均为 NULL）
==============================================================================
不能挂在任何真实账户下 —— 那会让该账户的成员（或"可见账户集合"命中的任何人）
在正常登录时看到演示店铺。判定链实测：

    `_matches(account_id=None, owner_id=None, visible=<真实用户集合>, user=<真实用户>)`
      → 走「无账户归属」兜底分支 → `bool(None) and ...` → **False** ⇒ 隔离成立

同时演示身份**不查 account**（走 `is_demo` 短路），所以无主不影响可用性。

★ 为什么不新建「演示账户 + 演示用户」：
  那要 seed 一个用户（密码 hash、email 唯一约束、订阅行…），而它的**唯一用途**
  是"让归属列非空"—— 收益为零、状态却多三层。老板要的是"C 档（演示登录改真实
  账号）"时才需要真用户，那时再建不迟。

==============================================================================
★ `server_default` 只在这一步存在
==============================================================================
`ADD COLUMN ... NOT NULL` 在已有数据的表上必须给默认值（否则 PG 无法为既有行补值）。
补完立刻摘掉：留着会让"默认值"有两个真源（SQL 一份、ORM 的 Python 侧一份），
这正是上一版迁移（`c9e5f3a7d4b6`）docstring 明确反对的形态。

★ 反向迁移只 `drop_column`：这一列是"加出来的"，回退就该只把它退掉。
  列没了，`StoreRecord.is_demo` 就真的没有来源了 —— 不会出现"库里有、代码不用"的残渣。

★ 幂等：与 `c9e5f3a7d4b6` 同款 `_has_column` 守卫。开发期 `create_all()` 用同一份
  `Base.metadata` 建表，新库启动过一次就带上这一列了；此后 `upgrade head` 再
  `ADD COLUMN` 会抛 `DuplicateColumn` —— 而那恰恰是"本该顺利"的场景。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a7b2e8c1f6'
down_revision: Union[str, Sequence[str], None] = 'c9e5f3a7d4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STORES = 'stores_store'
_COLUMN = 'is_demo'


def _has_column(table: str, column: str) -> bool:
    """表与列是否都已在库里（理由见文件头「幂等」一节）。"""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_column(_STORES, _COLUMN):
        op.add_column(
            _STORES,
            # server_default 只为"给既有行补 false"而存在，下一步就摘掉。
            sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column(_STORES, _COLUMN, server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    if _has_column(_STORES, _COLUMN):
        op.drop_column(_STORES, _COLUMN)

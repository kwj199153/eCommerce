"""accounts: 删除 kind 列（第 110 轮：容器只有一种，"私有"是成员数的状态）

Revision ID: b7e3f1a9c2d4
Revises: e6b1a4c7d9f2
Create Date: 2026-09-17 12:30:00.000000

==============================================================================
为什么删（第 110 轮）
==============================================================================
迁移 `e6b1a4c7d9f2` 加了 `kind`（personal / team），本意是把「个人账户」
这个**没有名字的概念**显式化。但它显式化的是一个**站不住的概念**：

    「私有」不是一种**容器类型**，而是**成员数的一个取值** ——
    成员数 = 1 时观感上是私有，> 1 就是共享。
    「一个人也可以是一人团」。

实测（开发库）直接证伪：老板的容器「跨境1」被回填成 `personal`，
而里面**坐着另一名成员李航** —— 标签与数据互相矛盾。

⇒ 容器只有**一种**。`AccountKind` 枚举、`accounts.kind` 列、以及前端
  所有「个人 / 团队」标签全部删除。

★ 为什么必须**删列**，而不是"留着不读"：
  本项目已把「字段只写不读」记为缺陷 —— 承诺与实现脱节的同类形态。
  一个不再被任何代码读的列，偏差可以无限期躺着而无人发现。
  要么它有真实用途，要么它不存在（`tests/test_default_account.py` 有 AST 门禁钉住）。

==============================================================================
「默认落点」这条规则保留，但不再靠 kind
==============================================================================
原来 `ensure_personal_account()` 靠 `kind == 'personal'` 找默认落点；
现在 `ensure_default_account()` 改为「该用户名下**最早创建**的容器
（`created_at, id` 全序）」，一个都没有则新建（名字 `{用户名} 的团队`）。

★ 行为差异（必须知道）：对"先建容器 A、后建容器 B"的用户，
  旧实现可能落 B（若 B 是回填出来的 personal），新实现恒落 A。
  新规则是**显式**的产品规则（"默认落到你最早的容器"），不再有
  "用插入顺序冒充某个概念"的问题；而前端建店时会**显式**传当前选中的
  容器 ⇒ 实际使用中很少走到这条兜底。

★ 名字变更：自动创建的容器由「{名} 的账户」改为「**{名} 的团队**」
  （`core/auth/accounts.py::_default_account_name`）。存量容器名字**不动**。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3f1a9c2d4'
down_revision: Union[str, Sequence[str], None] = 'e6b1a4c7d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ★ 只用 drop_column：不做"先把 personal 转成 team"之类的数据动作 ——
    #   列马上就不存在了，先 UPDATE 一遍纯属增加风险面。
    op.drop_column("accounts", "kind")


def downgrade() -> None:
    """Downgrade schema.

    ★ 还原列的**结构**，但不还原**语义**（不回填 personal）：
      回填口径是"每个 owner 最早的账户"，而当下 `ensure_default_account()`
      的判据已经是"取最早"，两者一致 ⇒ 补一次全表 UPDATE 得不到额外信息。
    """
    op.add_column(
        "accounts",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="team",
        ),
    )

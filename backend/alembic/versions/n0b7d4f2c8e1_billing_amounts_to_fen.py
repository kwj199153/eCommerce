"""计费金额单位：元（float）→ 分（int）

Revision ID: n0b7d4f2c8e1
Revises: m9f6a3c7d1e8
Create Date: 2026-10-17 15:20:00.000000

==============================================================================
★ 为什么改（不是一个"风格偏好"）
==============================================================================
改前两列都是 `double precision`（元）：
    · `invoices.amount`            —— 真正收的钱
    · `subscription_plans.price_monthly` —— 真正扣的价

浮点在金额上会以两种方式出事，两种都**不会报错**：

  ① **折算漂移**。年付价是「月付 × 10」，只要月付是小数（例如促销价 299.9），
     折算就会出现 `2999.0000000000005` 这类值。它经过 `round(,2)` 后
     看起来"恰好对"，但每一步都在赌"这个数恰好没漂"。
  ② **比对不精确**。支付宝回调给的是元字符串 `"2990.00"`，本地存的是 float，
     于是"金额是否一致"只能写成 `abs(a-b) < 0.01` 这种**带容差**的判断。
     容差意味着「少收一分钱」也算对账通过 —— 而一分钱正是最容易被批量利用的量。

存整数分之后：
  · 折算全在整数域（`price_monthly_fen * 10`），永不出漂；
  · 与网关的比对变成 `int == int`，**零容差**（`payments.amount_matches`）；
  · 与支付宝的元字符串只在一处换算（`pricing.fen_to_yuan_text` / `yuan_to_fen`）。

★ 参照 eEducation 项目：那边账单列就是 `amount_fen: int`，回调按整数分逐分比对。

==============================================================================
★ 为什么 `subscriptions.llm_cost_used` **不**跟着改（刻意的例外）
==============================================================================
它是**内部成本计量**，不是收款金额：单次 LLM 调用常见 0.0003 元（= 0.03 分），
存整数分会被四舍五入成 0，计量直接归零。留着 float + 6 位小数。

==============================================================================
★ 幂等守卫（与 m9f6a3c7d1e8 / i5b3a8d0e2c4 同一个坑）
==============================================================================
`create_all()` 用**当前**模型建表 ⇒ 全新库上这两列**本来就是**
`price_monthly_fen` / `amount_fen`（int）。此后 `alembic upgrade head`
再按"改名列 + 改类型"跑一遍就会抛 `UndefinedColumn` / `DatatypeMismatch`。
⇒ 每一步都先看实况再动手（列在不在、类型是不是浮点），已就位就跳过。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n0b7d4f2c8e1'
down_revision: Union[str, Sequence[str], None] = 'm9f6a3c7d1e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> dict:
    """表 → {列名: 列信息}。表不存在时返回空 dict（全新库上 create_all 可能还没跑）。"""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return {}
    return {c['name']: c for c in insp.get_columns(table)}


def _is_integer(col: dict) -> bool:
    return isinstance(col.get('type'), sa.Integer)


def _to_fen(table: str, old: str, new: str) -> None:
    """`old`(元 float) → `new`(分 int)，含存量数据 ×100。

    ★ 顺序不能反：先改名（值还是元）→ 再**用 USING 连同值一起**改成整数。
      若先改类型再改名，`round(x*100)` 会跑在一列已经变成整数（值仍是元）的
      数据上 —— 300 元会变成 300 分（差 100 倍），而且改完一切看起来正常。
    """
    cols = _columns(table)

    # ① 改名列（只在旧列存在、新列不存在时）
    if old in cols and new not in cols:
        op.alter_column(table, old, new_column_name=new)
        cols = _columns(table)

    # ② 类型 + 数据换算（只在还是浮点时）
    if new in cols and not _is_integer(cols[new]):
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {new} '
            f'TYPE integer USING round({new} * 100)::int'
        )
        op.execute(f'UPDATE {table} SET {new} = 0 WHERE {new} IS NULL')
        op.alter_column(
            table,
            new,
            existing_type=sa.Integer(),
            existing_nullable=cols[new].get('nullable', True),
            nullable=False,
            server_default='0',
        )


def upgrade() -> None:
    """Upgrade schema."""
    _to_fen('invoices', 'amount', 'amount_fen')
    _to_fen('subscription_plans', 'price_monthly', 'price_monthly_fen')


def downgrade() -> None:
    """Downgrade schema：分 → 元（float），并把列名改回去。"""
    for table, new, old in (
        ('invoices', 'amount_fen', 'amount'),
        ('subscription_plans', 'price_monthly_fen', 'price_monthly'),
    ):
        cols = _columns(table)
        if new in cols and _is_integer(cols[new]):
            op.execute(
                f'ALTER TABLE {table} ALTER COLUMN {new} '
                f'TYPE double precision USING {new} / 100.0'
            )
        if new in cols and old not in cols:
            op.alter_column(table, new, new_column_name=old)

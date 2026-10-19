"""账单退款登记：invoices 补 refunded_at / refund_reason / refund_operator_id

Revision ID: o1c8e5a3d9f2
Revises: n0b7d4f2c8e1
Create Date: 2026-10-19 22:40:00.000000

==============================================================================
★ 为什么加这三列（第 385 轮 · 第三方商用审查 P0-4）
==============================================================================
`Invoice.status` 的注释从第一天起就列着 `refunded`，但全仓**没有任何写入
路径** —— 实测 `grep -rn "refund" backend/modules/billing/*.py` 只命中
注释与两处"矛盾状态不许静默开权限"的判断：

    models.py:136        # paid / pending / failed / refunded / expired
    payment_router.py:189   账单状态与"支付成功"自相矛盾（如已 refunded）……
    payments.py:305          failed / refunded 等状态收到"支付成功"……

⇒ 结果是「客户要退款」这件事在系统里**无法表达**：运营只能改 SQL，
  而对账、客服、发票三条线都看不到痕迹。审查报告把它列为 P0：
  「退款：只有枚举值，全仓无写入路径」。

三列各回答一个问题（运营最常问的三件事）：
    refunded_at        什么时候退的   → 对账/发票期间归属
    refund_reason      为什么退的     → 客服复盘、纠纷举证
    refund_operator_id 谁批的         → 审计（不建外键：操作人删号不该带走账单）

★ 为什么**不**加 `refund_amount_fen`
--------------------------------------
本轮语义是**整单退款**（一次账单 = 一次资金退还），金额恒等于 `amount_fen`。
部分退款/多次退款是另一层模型（需要退款明细表 + 累加校验），在还没有真实
商户号、无法验证 `alipay.trade.refund` 报文之前先不猜 —— 猜出来的模型
比缺一个字段更难改。

★ 幂等守卫（与 n0b7d4f2c8e1 / m9f6a3c7d1e8 同一个坑）
------------------------------------------------------
全新库上 `create_all()` 用**当前**模型建表 ⇒ 这三列本来就在。此后
`alembic upgrade head` 再跑一遍"加列"会抛 `DuplicateColumn`。
⇒ 每一步先看实况（`inspect().get_columns`），已就位就跳过。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "o1c8e5a3d9f2"
down_revision: Union[str, Sequence[str], None] = "n0b7d4f2c8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "invoices"

_COLUMNS = (
    ("refunded_at", sa.DateTime(), True),
    ("refund_reason", sa.String(length=255), True),
    ("refund_operator_id", sa.String(length=36), True),
)


def _existing() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    """Upgrade schema."""
    present = _existing()
    if not present:
        # 表都还没有（全新库且 create_all 未跑）—— 无事可做，交给后续建表
        return
    for name, type_, nullable in _COLUMNS:
        if name in present:
            continue
        op.add_column(_TABLE, sa.Column(name, type_, nullable=nullable))


def downgrade() -> None:
    """Downgrade schema."""
    present = _existing()
    for name, _type, _nullable in reversed(_COLUMNS):
        if name in present:
            op.drop_column(_TABLE, name)

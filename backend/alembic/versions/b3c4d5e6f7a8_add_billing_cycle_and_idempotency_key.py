"""add subscriptions.billing_cycle and invoices.idempotency_key

P1-4 支付链路修复（2026-09-15）配套的表结构变更。

背景（实测）：
  1) subscriptions 表原先**不记录计费周期**。周期只活在
     billing_router.change_plan 的局部变量里，订阅行上查不到。
     后果：无法区分「用户点了两次升级（重复提交）」和「用户到期续费」——
     唯一能反推的线索是 current_period_end 减 current_period_start 的天数
     （monthly≈30 / yearly≈365），这在试用期、促销期上必然判错。
     实测证据：连续两次 POST /billing/subscribe，账单从 1 张涨到 4 张。

  2) invoices 表**没有幂等键**。服务端业务守卫能拦住顺序重复提交，但拦不住
     并发双击（两个请求都读到「尚未订阅」就各建一张单）。唯一约束是最后一道闸，
     它不依赖任何应用层判断，且真实网关也需要这个键做服务端去重
     （Stripe Idempotency-Key / 支付宝·微信 out_trade_no）。

★ 幂等说明：两处变更都先探测存在性，重复执行不会报错。
  这与本项目既有的 d4e5f6a7b8c9 迁移保持同一风格，原因是生产库可能
  已被手工改过或迁移历史与代码库不一致（历史遗留表就是这么来的）。

Revision ID: b3c4d5e6f7a8
Revises: a8c9d0e1f2b3
Create Date: 2026-09-15 13:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a8c9d0e1f2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(table: str, index: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(i["name"] == index for i in insp.get_indexes(table))


def upgrade() -> None:
    """Upgrade schema."""
    # 1. subscriptions.billing_cycle —— 计费周期落库
    if _table_exists('subscriptions') and not _column_exists('subscriptions', 'billing_cycle'):
        op.add_column(
            'subscriptions',
            sa.Column(
                'billing_cycle',
                sa.String(length=10),
                nullable=False,
                server_default='monthly',
            ),
        )
        # ★ 存量行回填：全部按 monthly 处理。
        #   为什么不尝试从周期天数反推？因为反推规则本身不可靠
        #   （试用期/促销期天数不是 30/365），而 billing_cycle 的用途是
        #   「判断是否同一周期的重复提交」，判错方向是「多扣一次钱」。
        #   保守取 monthly 会让既有年付用户在下一次同套餐提交时被判定为
        #   「非同周期」→ 最多多扣一次（可退），比漏判方向安全。
        #   若已知存量年付用户，请在迁移后执行
        #   `UPDATE subscriptions SET billing_cycle='yearly'
        #    WHERE current_period_end - current_period_start > INTERVAL '300 days';`
        op.execute("UPDATE subscriptions SET billing_cycle = 'monthly' WHERE billing_cycle IS NULL")

    # 2. invoices.idempotency_key —— 账单幂等键（唯一约束兜底并发双击）
    if _table_exists('invoices') and not _column_exists('invoices', 'idempotency_key'):
        op.add_column(
            'invoices',
            sa.Column('idempotency_key', sa.String(length=128), nullable=True),
        )

    # 唯一索引与 index=True 在 SQLAlchemy 里同时声明时会生成两个索引，
    # 这里只建唯一索引即可覆盖等值查询，避免冗余。
    if _table_exists('invoices') and not _index_exists('invoices', 'ix_invoices_idempotency_key'):
        op.create_index(
            'ix_invoices_idempotency_key',
            'invoices',
            ['idempotency_key'],
            unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    if _table_exists('invoices') and _index_exists('invoices', 'ix_invoices_idempotency_key'):
        op.drop_index('ix_invoices_idempotency_key', table_name='invoices')
    if _table_exists('invoices') and _column_exists('invoices', 'idempotency_key'):
        op.drop_column('invoices', 'idempotency_key')
    if _table_exists('subscriptions') and _column_exists('subscriptions', 'billing_cycle'):
        op.drop_column('subscriptions', 'billing_cycle')

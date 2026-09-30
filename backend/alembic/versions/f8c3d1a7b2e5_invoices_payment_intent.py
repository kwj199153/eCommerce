"""invoices 补「支付意图」五列：让异步支付确认能闭环（P0/P1 支付宝扫码支付）

Revision ID: f8c3d1a7b2e5
Revises: e7b2c9d4a1f8
Create Date: 2026-09-25 10:00:00.000000

==============================================================================
★ 这一版补的是什么：账单从「收据」升级为「支付意图」
==============================================================================
接入支付宝扫码支付之前，`change_plan` 是**同步**的：
    扣款（mock 瞬时成功） → 同一次请求内改订阅 → 落一张 paid 账单。
账单因此只需要回答「收了多少钱」——「这笔钱对应什么」没必要记，
因为答案体现在同一事务里已经改好的 `subscriptions` 行上。

真实支付把这个前提推翻了。支付宝当面付的流程是：
    ① 服务端 `alipay.trade.precreate` → 拿到二维码，此时**一分钱没收到**；
    ② 用户扫码付款；
    ③ 支付宝异步回调 `notify_url`（可能几十秒后，也可能重试多次）。

⇒ 第 ③ 步发生在一个**全新的 HTTP 请求**里，手上只有
  `out_trade_no`（我们给支付宝的商户订单号）。要回答「这个人买的是哪个套餐、
  买了几个月」，唯一的落点就是账单行。这就是 `plan_id` / `billing_cycle`
  两列存在的全部理由 —— 它们不是把 subscriptions 的字段抄了一份，
  而是把「**这笔钱买的是什么**」这条信息钉在**钱**上（钱与意图必须同源，
  否则 webhook 到达时只能靠猜）。

==============================================================================
★ 为什么 `transaction_id` 必须有唯一约束（不能只靠应用层判重）
==============================================================================
支付宝的异步通知是 **at-least-once**：只要它没收到 HTTP 200 + 响应体
`success`，就会按自己的节奏重复投递同一个 `notify_id`。
所以「同一个订单被处理两次」不是异常路径，而是**设计内**的正常现象。

应用层的判重天生是「读-判断-写」（读 `status`，若是 pending 才改写）：
两个并发回调会**都**读到 pending，然后各自激活一次订阅 ——
表现是「续费周期被推进两次，用户白拿一个月」，且日志里两条都写着成功。
`invoices.transaction_id` 的唯一约束不是兜底，而是这条幂等性的**主闸**：
它让第二次落库在 DB 层直接失败，不依赖任何应用层时序。

★ 可为 NULL（历史账单、人工补录不走网关），PG 允许多个 NULL，与
  `idempotency_key` 同款处理。

==============================================================================
★ 为什么 `pay_url` 必须落库，而不是只在响应体里回给前端
==============================================================================
二维码内容（`qr_code`）如果只存在于 `/billing/subscribe` 的响应里，
用户「下单 → 还没扫 → 刷新页面」就永久丢失它，只能重新下单。
后果不是"体验差一点"，而是**对账时多出一张没人认领的 pending 单**——
它和"真实漏单"在数据上完全同形。

⇒ 落库之后，前端 `GET /billing/payment/pending` 就能把二维码原样重建，
刷新不再是破坏性操作。

==============================================================================
★ 幂等（本仓迁移的硬要求，不是可选项）
==============================================================================
开发期 `main.py` 的 lifespan 会 `create_all()` 抢先按**新** ORM 建出新列，
随后 `alembic upgrade head` 再 `ADD COLUMN` 会抛 `DuplicateColumn` ——
而那恰恰是"本该顺利"的场景。故每一列都过 `_has_column` 守卫，
每个索引都过 `_has_index` 守卫。坑的完整形态见
`alembic/versions/d4a7b2e8c1f6_stores_add_is_demo.py` 文件头「幂等」一节。

★ 反向迁移连同索引一起退掉：列没了索引就是孤儿（PG 会自动删，但显式写出来
  才能让 `downgrade` 与 `upgrade` 严格互逆，也才过得了「迁移往返」自检）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8c3d1a7b2e5'
down_revision: Union[str, Sequence[str], None] = 'e7b2c9d4a1f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'invoices'

#: 列名 -> 列定义（顺序即 DDL 顺序，保持与 models.py 中声明顺序一致）
#:
#: ★ `plan_id` 的 FK **内联**在列定义里，与本仓 autogenerate 的默认形态不同
#:   （autogenerate 会拆成 add_column + create_foreign_key(None, ...)）。
#:   这里内联的收益是：PG 会把约束名生成为 `invoices_plan_id_fkey` ——
#:   与 `create_foreign_key(None, ...)` 的产物**同名**，而少一条 DDL 语句，
#:   少一处"列建了、约束没建"的中间态。ORM 侧该 FK 也是内联声明的
#:   （`mapped_column(Integer, ForeignKey("subscription_plans.id"))`），
#:   两侧形态一致 ⇒ `compare_metadata` 才不会报出无意义的偏差。
_COLUMNS: dict[str, sa.Column] = {
    'plan_id': sa.Column(
        'plan_id',
        sa.Integer(),
        sa.ForeignKey('subscription_plans.id'),
        nullable=True,
    ),
    'billing_cycle': sa.Column('billing_cycle', sa.String(length=10), nullable=True),
    'transaction_id': sa.Column('transaction_id', sa.String(length=64), nullable=True),
    'payment_channel': sa.Column('payment_channel', sa.String(length=20), nullable=True),
    'pay_url': sa.Column('pay_url', sa.String(length=512), nullable=True),
}

#: 需要建的索引：(索引名, [列], 是否唯一)
_INDEXES: list[tuple[str, list[str], bool]] = [
    ('ix_invoices_transaction_id', ['transaction_id'], True),
]


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    insp = _inspector()
    if table not in insp.get_table_names():
        return False
    return column in {c['name'] for c in insp.get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    insp = _inspector()
    if table not in insp.get_table_names():
        return False
    return index in {i['name'] for i in insp.get_indexes(table)}


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        # 空库由基线迁移建表；走到这里说明基线还没跑，交给它去建（含这些列）。
        return

    for name, column in _COLUMNS.items():
        if not _has_column(_TABLE, name):
            op.add_column(_TABLE, column)

    for index_name, cols, unique in _INDEXES:
        if not _has_index(_TABLE, index_name):
            op.create_index(op.f(index_name), _TABLE, cols, unique=unique)


def downgrade() -> None:
    """Downgrade schema."""
    if not _has_table(_TABLE):
        return

    for index_name, _cols, _unique in _INDEXES:
        if _has_index(_TABLE, index_name):
            op.drop_index(op.f(index_name), table_name=_TABLE)

    for name in reversed(list(_COLUMNS)):
        if _has_column(_TABLE, name):
            op.drop_column(_TABLE, name)

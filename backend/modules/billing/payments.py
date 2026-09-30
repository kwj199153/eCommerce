"""待支付订单与「钱 → 权限」结算 —— 异步支付的全部共享逻辑（唯一实现）

==============================================================================
★ 这个模块存在的理由：真实支付把「一次请求」拆成了「两个请求」
==============================================================================
mock 支付下，`change_plan` 一个函数从头做到尾：
    锁定 → 扣款 → 改订阅 → 落账单 → 提交
所有状态都活在那一个事务里，没有第二个入口，也就不需要"共享"。

真实支付（支付宝当面付）不是这样：
    请求 A（用户点升级）  → 建 pending 账单 + 生成二维码
    请求 B（支付宝回调）  → 改账单为 paid + 开通订阅     ← 全新的 HTTP 请求
    请求 C（定时对账）    → 补偿请求 B 丢掉的单         ← 又一条路径

请求 B 和请求 C 做的是**同一件事**（把一笔已到账的钱兑现成套餐权限）。
若各写一遍，必然出现「webhook 走通了但补偿路径没有」这种半边实现 ——
而它平时完全测不出来（毕竟 webhook 几乎不丢），只在丢单的那一天暴露，
并且表现出来的症状是"钱收了、套餐没开"，最难排查的一类。

⇒ 本模块把这套逻辑收成唯一实现，三条路径都调它。

==============================================================================
★ 四条不变量（改本文件前先读这一段）
==============================================================================

① **只有 `settle_invoice()` 能把钱变成权限。**
   其它任何地方都不许写 `subscription.status = "active"` 并声称"用户付过了"。
   判据：改动后若存在第二条"开通套餐"的路径，本模块就白建了。

② **幂等靠行锁 + 状态判定，不靠调用方的时序。**
   支付宝会重复投递同一个通知；对账任务也可能和回调撞在同一秒。
   `settle_invoice()` 先 `SELECT ... FOR UPDATE` 再加 `populate_existing`
   （★ 两者缺一不可，理由与 `change_plan` 完全同源，见
   tests/test_billing_payment.py::test_concurrent_duplicate_submission_creates_single_invoice），
   然后判 `status == "paid"` 直接返回。第二次调用不会推进第二次周期。

③ **`expired` 的账单收到钱照样认账。**
   我们的 TTL 与支付宝的 `timeout_express` 取同一个值，理论上不会出现
   "我们判过期了、支付宝还认"的窗口。但「理论上不会」不是不变量：
   定时回收任务可能因为时钟漂移、部署重启前的旧代码、人工改库而提前执行。
   真出现时，钱**确实到了**，拒收的代价是用户付了钱没权益 ——
   比多开一个周期严重得多。⇒ 认账，并打一条 warning 留痕。

④ **金额必须核对。**
   `total_amount` 与账单金额不符时**不开通**，只落 failed + 告警。
   不核金额的话，一个 0.01 元的通知就能开通 2990 元的年付套餐。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.timefmt import utc_iso
from modules.billing.models import Invoice, Subscription, SubscriptionPlan
from modules.billing.pricing import normalize_cycle, period_end
from platforms.payment.gateway import PENDING_PAYMENT_TTL_MINUTES

_log = get_logger("billing.payments")

#: 「已支付」之外，还能被结算的账单状态。
#: ★ 见不变量 ③：`expired` 也在内 —— 钱到了就认。
_SETTLEABLE_STATUSES = frozenset({"pending", "expired"})


# ============================================================================
# 待支付订单
# ============================================================================

def pending_expires_at(invoice: Invoice) -> Optional[datetime]:
    """这张待支付单什么时候失效（= 下单时间 + TTL）。

    ★ 口径与支付宝侧的 `timeout_express` 取同一个常量
      （`PENDING_PAYMENT_TTL_MINUTES`），见该常量的注释。
    """
    issued = getattr(invoice, "issued_at", None)
    if issued is None:
        return None
    return issued + timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES)


async def find_reusable_pending(
    db: AsyncSession,
    user_id: str,
    plan_id: int,
    billing_cycle: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[Invoice]:
    """找一张**可以直接复用**的待支付账单（同人 + 同套餐 + 同周期 + 未过期）。

    ★ 为什么必须有这一步（漏了它会出什么错）：
      两段式之后，`change_plan` 不再改动订阅行（用户没付钱，凭什么动他的权益）。
      于是「同一个用户连点两次升级」时，两次读到的订阅状态**完全相同**
      —— `is_duplicate_submission` 自然判不出来，`subscription_state_fingerprint`
      算出的幂等键也完全相同 ⇒ 第二次会撞 `invoices.idempotency_key` 唯一约束，
      给用户返回一个莫名其妙的 409「检测到重复提交」。

      但那并不是"重复提交"，而是**上一次的下单还没付款**。正确语义是
      「把同一张二维码再给他看一次」。这个函数就是那个语义的落点。

    ★ 复用而不是新建，还有一个资金安全上的理由：
      每次新建都会向支付宝 `precreate` 一张新订单、生成一张新二维码。
      两张活码同时有效时，用户可能扫第一张付了钱，又在别的页面扫第二张 ——
      付两次。复用把「同一意图同一张码」这条不变量维持住。
    """
    moment = now or datetime.utcnow()
    earliest = moment - timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES)

    result = await db.execute(
        select(Invoice)
        .where(
            Invoice.user_id == user_id,
            Invoice.status == "pending",
            Invoice.plan_id == plan_id,
            Invoice.billing_cycle == normalize_cycle(billing_cycle),
            Invoice.issued_at >= earliest,
        )
        .order_by(Invoice.issued_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def supersede_other_pending(
    db: AsyncSession,
    user_id: str,
    keep_invoice_id: str,
    *,
    now: Optional[datetime] = None,
) -> int:
    """把同一用户**其它**还没付的待支付单标记为 `expired`，返回被顶掉的数量。

    ★ 为什么"顶掉"而不是"删掉"：
      账单是资金凭证，任何情况下都不该被 DELETE —— 删掉之后，
      "用户曾经下过一单但没付"这件事就从数据里消失了。
      而对账时恰恰需要它：支付宝侧的订单数与我们的账单数对不上时，
      一行 `expired` 就能解释差额；没有这一行，那笔差额就成了悬案。

    ★ 已在支付宝侧生成的订单我们**不去撤销**（没调 trade.cancel）：
      万一用户扫的是旧码，钱还是会到账。要接住这种情况，
      靠的是 `settle_invoice()` 对 `expired` 状态照常认账（不变量 ③），
      而不是靠"保证用户不会扫旧码"（那不是我们能保证的）。
    """
    moment = now or datetime.utcnow()
    result = await db.execute(
        update(Invoice)
        .where(
            Invoice.user_id == user_id,
            Invoice.status == "pending",
            Invoice.id != keep_invoice_id,
        )
        .values(status="expired")
        # ★ `synchronize_session=False`：批量 UPDATE 不走 ORM 的 per-object 同步。
        #   默认的 'auto' 会尝试在 session 内"求值"这个条件，而条件里含
        #   `id != :keep` 这类无法在 Python 侧求值的表达式 ⇒ 退化成 'fetch'
        #   并额外发一条 SELECT。这里本来就不需要同步（调用方不依赖 session 内
        #   的旧状态），显式关掉更确定。
        .execution_options(synchronize_session=False)
    )
    count = int(result.rowcount or 0)
    if count:
        _log.info(
            "顶掉旧的待支付单 user={} 保留={} 数量={} at={}",
            user_id, keep_invoice_id, count, moment.isoformat(),
        )
    return count


async def expire_stale_pending(
    db: AsyncSession, *, now: Optional[datetime] = None, limit: int = 500
) -> int:
    """把超时未支付的待支付单批量标记为 `expired`（定时任务调用）。

    ★ 为什么需要一个定时任务，而不是"用到时再判"：
      判"过期"是读时判定，但**数据本身会一直停在 pending**。
      结果是 billing 页面上永远挂着一张"待支付"，而它对应的支付宝订单
      早就超时关闭了 —— 用户点进去扫一张死码，扫不出来，也不知道为什么。

    ★ 为什么带 `limit`：一次任务扫全表在数据量上来后会变成慢查询，
      把整个 beat 槽位占住。分批 + 每轮由调度器再触发，代价可控。
    """
    moment = now or datetime.utcnow()
    cutoff = moment - timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES)

    subq = (
        select(Invoice.id)
        .where(Invoice.status == "pending", Invoice.issued_at < cutoff)
        .limit(limit)
        .scalar_subquery()
    )
    result = await db.execute(
        update(Invoice)
        .where(Invoice.id.in_(subq))
        .values(status="expired")
        .execution_options(synchronize_session=False)
    )
    count = int(result.rowcount or 0)
    if count:
        _log.info("回收超时未支付账单 {} 张（cutoff={}）", count, cutoff.isoformat())
    return count


# ============================================================================
# 金额核对
# ============================================================================

def amount_matches(invoice: Invoice, amount_yuan: Optional[float]) -> bool:
    """通知/查询拿到的金额是否与账单一致（容忍 1 分钱以内的浮点误差）。

    ★ `None`（金额字段缺失或解析失败）一律判为**不匹配**：
      支付通知里没有金额，本身就是报文异常，不该被"宽松处理"。
    """
    if amount_yuan is None:
        return False
    return abs(round(float(invoice.amount or 0), 2) - round(float(amount_yuan), 2)) < 0.01


# ============================================================================
# 结算：把「已到账的钱」兑现成「套餐权限」（唯一实现）
# ============================================================================

@dataclass
class SettleOutcome:
    """`settle_invoice()` 的结果（供调用方决定回什么、记什么）。"""

    ok: bool
    #: 这张账单在本次调用**之前**就已经是 paid（重复通知 / 补偿与回调撞车）
    already_paid: bool = False
    #: 是否真的改动了订阅（False 通常意味着 plan_id 缺失）
    activated: bool = False
    subscription: Optional[Subscription] = None
    #: 人话原因（日志与响应都用它，避免调用方各自拼文案）
    reason: str = ""


async def settle_invoice(
    db: AsyncSession,
    invoice_id: str,
    *,
    paid_at: Optional[datetime] = None,
    trade_no: str = "",
) -> SettleOutcome:
    """**唯一**的「账单转已支付 + 据此开通订阅」实现。

    Args:
        db: 会话（本函数自己提交，见下方「事务边界」）。
        invoice_id: 账单主键（调用方已按 `transaction_id` 查到了它）。
        paid_at: 到账时间；缺省取当前 UTC 时间。
        trade_no: 支付宝交易号，仅用于日志留痕（对账靠 `out_trade_no` 反查即可）。

    Returns:
        `SettleOutcome`。**不抛业务异常** —— 调用方（webhook / 定时任务）
        需要的是"能不能回 success"，而不是把异常漏给支付宝看。

    ★ 事务边界：本函数内部 `commit()`。
      因为"标记已付"与"开通订阅"必须**同时**生效：只落前者 = 用户付了钱没权益；
      只落后者 = 权益没有资金凭证支撑（对账时光秃秃多出一个付费用户）。
      把 commit 交给调用方，就等于允许它忘掉、或者只提交一半。

    ★ 幂等：先 `FOR UPDATE` 锁住账单行。第二个并发调用会阻塞，
      拿到锁后 `populate_existing` 保证它读到的是**新**状态 ⇒ 直接走 already_paid。
      少任何一个（锁 / 重新装载），第二次调用都会读到 pending 并再开通一次。
    """
    moment = paid_at or datetime.utcnow()

    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        # ★★ 行锁 + 强制重载，缺一不可（理由同 change_plan，见模块 docstring 不变量 ②）
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        _log.error("结算失败：账单不存在 id={}", invoice_id)
        return SettleOutcome(ok=False, reason="invoice_not_found")

    if invoice.status == "paid":
        # 重复通知 / 补偿与回调撞车 —— 正常路径，不是异常。
        # ★ 用 `commit()` 而不是 `rollback()` 来释放行锁：
        #   rollback 会把 session 内所有对象 expire，调用方随后读
        #   `invoice.status` 就会触发隐式懒加载 —— 在纯 async 上下文里
        #   直接抛 `MissingGreenlet`（本仓已踩过两次的坑）。
        #   commit 同样释放锁，而 session 是 `expire_on_commit=False`（core/database.py），
        #   对象保持可用。零改动的 commit 不会写任何数据。
        await db.commit()
        return SettleOutcome(ok=True, already_paid=True, reason="already_paid")

    if invoice.status not in _SETTLEABLE_STATUSES:
        # failed / refunded 等状态收到"支付成功"：数据自相矛盾，不能静默开权限。
        await db.commit()
        _log.error(
            "结算拒绝：账单状态与支付成功矛盾 id={} status={} trade_no={}",
            invoice.id, invoice.status, trade_no,
        )
        return SettleOutcome(ok=False, reason=f"status_conflict:{invoice.status}")

    was_expired = invoice.status == "expired"

    # ---- ① 账单转已支付（资金凭证先落地，与权限写入同一事务）----
    invoice.status = "paid"
    invoice.paid_at = moment

    # ---- ② 按账单上的「支付意图」开通/续期订阅 ----
    if invoice.plan_id is None or invoice.user_id is None:
        # 没有支付意图的账单（人工补录 / 早期数据）无法推出该开什么套餐。
        # ★ 提交"已支付"但不激活，并留 error 日志：
        #   吞掉不提交会让钱和凭证一起丢；静默激活又不知道该激活什么。
        await db.commit()
        _log.error(
            "账单已支付但缺少支付意图（plan_id/user_id），无法自动开通 id={} "
            "user={} trade_no={} —— 需要人工处理",
            invoice.id, invoice.user_id, trade_no,
        )
        return SettleOutcome(ok=True, reason="settled_without_plan")

    cycle = normalize_cycle(invoice.billing_cycle)
    plan = (
        await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == int(invoice.plan_id))
        )
    ).scalar_one_or_none()
    if plan is None:
        await db.commit()
        _log.error(
            "账单引用的套餐不存在（plan_id={}）⇒ 无法开通 id={}",
            invoice.plan_id, invoice.id,
        )
        return SettleOutcome(ok=True, reason="plan_not_found")

    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == invoice.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sub = sub_result.scalar_one_or_none()

    if sub is None:
        sub = Subscription(
            id=str(uuid.uuid4()),
            user_id=invoice.user_id,
            plan_id=plan.id,
            status="active",
            billing_cycle=cycle,
            cancel_at_period_end=False,
            current_period_start=moment,
            current_period_end=period_end(moment, cycle),
        )
        db.add(sub)
    else:
        sub.plan_id = plan.id
        sub.status = "active"
        sub.billing_cycle = cycle
        # 付了钱就是要继续用 ⇒ 清掉"周期末取消"的意图。
        # ★ 与 change_plan 同一口径：用户重新付费即视为撤销取消。
        sub.cancel_at_period_end = False
        sub.current_period_start = moment
        sub.current_period_end = period_end(moment, cycle)
        sub.updated_at = moment

    await db.commit()
    await db.refresh(sub)

    if was_expired:
        # 不变量 ③：我们判过期了但钱还是到了（旧码被扫 / 回收任务提前跑）。
        # 认账，但必须留痕 —— 这是"我们的 TTL 与支付宝不一致"的唯一征兆。
        _log.warning(
            "账单已过期但仍收到款项 ⇒ 照常开通（请检查 TTL 与支付宝 timeout_express 是否一致）"
            " id={} user={} plan={} cycle={} trade_no={}",
            invoice.id, invoice.user_id, plan.name, cycle, trade_no,
        )

    _log.info(
        "结算完成 id={} user={} plan={} cycle={} amount={} out_trade_no={} trade_no={}",
        invoice.id, invoice.user_id, plan.name, cycle, invoice.amount,
        invoice.transaction_id, trade_no,
    )
    return SettleOutcome(ok=True, activated=True, subscription=sub, reason="activated")


# ============================================================================
# 序列化（下单响应与待支付查询共用，避免两处各拼一份字段）
# ============================================================================

def pending_payment_payload(invoice: Invoice) -> dict[str, Any]:
    """一张待支付账单 → 前端契约（`/billing/subscribe` 与 `/billing/payment/pending` 共用）。

    ★ 为什么要共用：这两个接口返回的是**同一件事**（有一张待你付款的单）。
      各拼一份的结果是「下单时看到的字段」与「刷新后恢复的字段」不一样，
      前端得写两套解析 —— 而两套里必然有一套没人测。
    """
    expires = pending_expires_at(invoice)
    return {
        "invoice_id": invoice.id,
        "number": invoice.number,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "plan_id": str(invoice.plan_id) if invoice.plan_id is not None else None,
        "billing_cycle": invoice.billing_cycle,
        "payment_channel": invoice.payment_channel,
        # 二维码**原值**（形如 https://qr.alipay.com/xxx）。
        # 前端不直接用它渲染（那是后端出 SVG 的活），但排障时要有：
        # 用户说"扫不出来"时，第一件事就是把这段贴进支付宝核对。
        "qr_code_url": invoice.pay_url or "",
        # ★ 走 utc_iso（core/timefmt.py）而不是裸 isoformat()：
        #   后者输出无偏移的字符串，UTC+8 的浏览器会把它按本地时区解析 ⇒
        #   `expires_at` 的 30 分钟倒计时一打开就显示"已过期"。
        "created_at": utc_iso(invoice.issued_at),
        "expires_at": utc_iso(expires),
    }


__all__ = [
    "SettleOutcome",
    "amount_matches",
    "expire_stale_pending",
    "find_reusable_pending",
    "pending_expires_at",
    "pending_payment_payload",
    "settle_invoice",
    "supersede_other_pending",
]

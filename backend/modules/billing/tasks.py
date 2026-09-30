"""计费的定时任务：待支付回收 / 订阅到期清算 / 支付对账（P1，2026-09-25）

这三个任务对应真实支付上线后**必然会缺**的三件事。
它们与 `modules/memory/tasks.py` 的结构刻意保持一致（同样的会话桥、
同样的"任务名集中定义"、同样的指标写入点），因为那套形态已经在本仓
踩过一遍坑并收敛过了。读者如果只看一个文件就能懂另一个。

==============================================================================
★ 三个任务分别在防什么
==============================================================================

① `expire_pending_invoices`（每 5 分钟）
   防「僵尸待支付单」：用户下单后没付、关掉页面走人。
   不做这个任务时，那张单会**永远停在 pending** ——
   账单页上一直挂着"待支付"，用户点进去扫一张早就死掉的码，扫不出来、
   也没有任何解释。数据上它还占着"未结清"的名额，把对账的注意力引向不存在的问题。

② `sweep_expired_subscriptions`（每天凌晨）
   防「权益状态与时间脱钩」：`current_period_end` 已经过去，而
   `status` 还写着 `active`。
   ★ 注意：**访问控制不依赖这个任务**（`pricing.is_period_active` 按时间判，
     已经天然拒绝过期订阅）。所以它修的不是漏洞，而是**可读性**：
     不做的话，用户看到的订阅卡片写着"生效中"、日期却在一个月前，
     客服只能靠人工算日期来回答"我到底还能不能用"。
   做的话，`cancel_at_period_end=True` 的单转 `cancelled`、
   其余转 `expired` —— 与用户在界面上的预期一致。

③ `reconcile_alipay_orders`（每天凌晨）
   防「漏单」与「幽灵单」，两个方向都要查：
     · 我们以为没付、支付宝说付了  → **补开通**（webhook 丢了）；
     · 我们以为付了、支付宝说没付  → **告警**（有人伪造了通知？我们的库被改了？）。
   ★ 真实支付必须有对账。没有对账的支付集成等于没集成 ——
     漏单/重复单只能靠用户投诉发现，而用户往往不会投诉，他只是下次不续费了。

==============================================================================
★★ 跨 event loop 的连接池陷阱（照抄 aigc_media 的解法，理由见其模块 docstring）
==============================================================================
Celery worker 是**同步**进程，任务体要 `asyncio.run(coro)`，而每次
`asyncio.run` 都新建一个 event loop；asyncpg 的连接绑定在创建它的 loop 上。
复用模块级全局 engine（`core.database.engine`）时**第一次成功、第二次必挂**
（`Future attached to a different loop`），且只在跑第二个任务时才暴露。

⇒ 本模块每次执行都**新建 engine（NullPool）+ 结束时 dispose**。
  （`modules/memory/tasks.py` 选了另一条路 —— 每线程常驻 loop；
   它那么选是因为它的 DB 访问散在多个 service 里、无法注入外部 session。
   本模块的 DB 访问自包含，用 aigc 那套更简单。）

★ 不要在本文件连 `task_success` / `task_failure` 信号：
  `modules/aigc_media/tasks.py` 已经**全局**连了（没有 sender 过滤），
  重复连接会让每个任务被计两次。Celery 的信号是全局的、不按模块隔离。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# ★ 只 import 本模块真正**用得到**的常量。
#   调度节奏（间隔 / 时刻）的消费方是 `core/redis.py::beat_schedule`，
#   不在这里 —— 在那里 import 会把"任务体"与"调度表"耦合起来，
#   而本仓的判据是「谁需要谁读」：调度表读节奏，任务体读窗口。
from core.config import BILLING_RECONCILE_LOOKBACK_DAYS, config
from core.logger import get_logger
from core.observability.metrics import CELERY_TASK_RESULTS
from core.redis import celery_app

logger = get_logger("billing.tasks")

# ============================================================================
# 任务注册名（集中定义一次）
# ============================================================================
#
# ★ 这三个名字同时出现在三个地方：本文件的任务装饰器、
#   `core/redis.py::beat_schedule` 的字面量、以及指标标签。
#   写错任何一个的表现都是**安静地不跑**（beat 往一个没人注册的名字投递），
#   所以由 `tests/test_billing_schedule.py` 把两边钉成相等，
#   而不是靠注释提醒 —— 注释不会失败。
TASK_EXPIRE_PENDING = "billing.expire_pending_invoices"
TASK_SWEEP_SUBSCRIPTIONS = "billing.sweep_expired_subscriptions"
TASK_RECONCILE = "billing.reconcile_alipay_orders"


# ============================================================================
# 会话桥（worker 侧）
# ============================================================================

def _new_session_factory():
    """为本次任务新建一套连接设施（关掉 pre_ping：NullPool 下它没有意义）。"""
    engine = create_async_engine(config.database_url, poolclass=NullPool, echo=False)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _execute_with_session(fn):
    """在**全新的** engine/loop 里执行 `fn(session)`，结束后释放连接。"""
    engine, factory = _new_session_factory()
    try:
        async with factory() as db:
            return await fn(db)
    finally:
        await engine.dispose()


# ============================================================================
# ① 回收超时未支付的账单
# ============================================================================

async def _expire_pending(db) -> dict[str, Any]:
    from modules.billing.payments import expire_stale_pending

    count = await expire_stale_pending(db, now=datetime.utcnow())
    await db.commit()
    return {"expired": count}


@celery_app.task(bind=True, name=TASK_EXPIRE_PENDING)
def expire_pending_invoices(self) -> dict[str, Any]:
    """把超过 TTL 仍未支付的待支付账单标记为 expired。"""
    try:
        summary = _run(_expire_pending)
        CELERY_TASK_RESULTS.inc(task=TASK_EXPIRE_PENDING, status="ok")
        if summary["expired"]:
            logger.info("[billing.tasks] 回收超时未支付账单 {} 张", summary["expired"])
        return summary
    except Exception:
        logger.exception("[billing.tasks] 回收待支付账单失败")
        CELERY_TASK_RESULTS.inc(task=TASK_EXPIRE_PENDING, status="infra_failure")
        raise


# ============================================================================
# ② 订阅到期清算
# ============================================================================

async def _sweep_subscriptions(db, now: Optional[datetime] = None) -> dict[str, Any]:
    """把周期已过的 active 订阅收口：待取消 → cancelled，其余 → expired。

    ★ 覆盖率的判据不能只看 `current_period_end < now`，还必须看 `status`：
      只按时间筛会反复命中同一批已经处理过的行（它们是 cancelled/expired 了，
      但 end 依然在过去），每次任务都"处理"一遍、指标虚高、日志刷屏。
      ⇒ 条件是 `status == "active" AND current_period_end < now`，
        处理完 status 就变了，天然只命中一次。
    """
    from modules.billing.models import Subscription

    moment = now or datetime.utcnow()

    rows = (
        await db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end < moment,
            )
        )
    ).scalars().all()

    cancelled = 0
    expired = 0
    for sub in rows:
        if sub.cancel_at_period_end:
            sub.status = "cancelled"
            cancelled += 1
        else:
            sub.status = "expired"
            expired += 1
        sub.updated_at = moment

    await db.commit()
    return {"scanned": len(rows), "cancelled": cancelled, "expired": expired}


@celery_app.task(bind=True, name=TASK_SWEEP_SUBSCRIPTIONS)
def sweep_expired_subscriptions(self) -> dict[str, Any]:
    """每天的订阅到期清算。"""
    try:
        summary = _run(_sweep_subscriptions)
        CELERY_TASK_RESULTS.inc(task=TASK_SWEEP_SUBSCRIPTIONS, status="ok")
        if summary["scanned"]:
            logger.info(
                "[billing.tasks] 订阅到期清算：共 {} 条，转 cancelled={} expired={}",
                summary["scanned"], summary["cancelled"], summary["expired"],
            )
        return summary
    except Exception:
        logger.exception("[billing.tasks] 订阅到期清算失败")
        CELERY_TASK_RESULTS.inc(task=TASK_SWEEP_SUBSCRIPTIONS, status="infra_failure")
        raise


# ============================================================================
# ③ 支付对账
# ============================================================================

async def _reconcile(db, *, lookback_days: Optional[int] = None) -> dict[str, Any]:
    """与支付宝逐笔核对近期订单。

    只处理 `payment_channel == "alipay"` 且**有** `transaction_id` 的账单：
    没有商户订单号就没法向支付宝反查（mock 账单号形如 `mock-xxx`，
    拿去查只会拿到 ACQ.TRADE_NOT_EXIST，白白刷一堆假告警）。
    """
    from modules.billing.models import Invoice
    from modules.billing.payments import amount_matches, settle_invoice
    from platforms.payment.alipay import AlipayGateway

    days = int(lookback_days or BILLING_RECONCILE_LOOKBACK_DAYS)
    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        await db.execute(
            select(Invoice).where(
                Invoice.payment_channel == "alipay",
                Invoice.transaction_id.is_not(None),
                Invoice.issued_at >= since,
                Invoice.status.in_(("pending", "expired", "paid")),
            )
        )
    ).scalars().all()

    gateway = AlipayGateway()
    compensated = 0     # 我们以为没付、支付宝说付了 → 补开通
    mismatched = 0      # 我们以为付了、支付宝说没付 → 告警
    errors = 0

    for invoice in rows:
        try:
            result = await gateway.query_trade(invoice.transaction_id)
        except Exception:  # noqa: BLE001 —— 单笔查询失败不该拖垮整批
            errors += 1
            logger.exception(
                "[billing.tasks] 对账查询失败 invoice={} out_trade_no={}",
                invoice.number, invoice.transaction_id,
            )
            continue

        code = str(result.get("code") or "")
        status_text = str(result.get("trade_status") or "")

        # 支付宝侧查不到这笔单：对 `paid` 的账单是严重异常（我们凭什么认定收过钱？），
        # 对 pending/expired 则是正常的"用户没付"。两者必须分开报。
        if code != "10000":
            if invoice.status == "paid":
                mismatched += 1
                logger.critical(
                    "[billing.tasks] 对账异常：本地已标记已支付，支付宝查不到该订单"
                    " invoice={} out_trade_no={} code={} sub_msg={}",
                    invoice.number, invoice.transaction_id, code, result.get("sub_msg"),
                )
            continue

        if status_text in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            if invoice.status in ("pending", "expired"):
                if not amount_matches(invoice, _yuan(result.get("total_amount"))):
                    mismatched += 1
                    logger.critical(
                        "[billing.tasks] 对账异常：金额不符，拒绝补开通 invoice={} "
                        "账单={} 支付宝={}",
                        invoice.number, invoice.amount, result.get("total_amount"),
                    )
                    continue
                # ★ 这正是对账存在的意义：webhook 丢了，钱在支付宝侧已经收妥，
                #   只有主动查询才能发现。走的是与 webhook **同一个**结算实现。
                outcome = await settle_invoice(
                    db,
                    invoice.id,
                    trade_no=str(result.get("trade_no") or ""),
                )
                if outcome.ok and outcome.activated:
                    compensated += 1
                    logger.warning(
                        "[billing.tasks] 对账补开通（webhook 曾丢失） invoice={} user={}",
                        invoice.number, invoice.user_id,
                    )
        elif invoice.status == "paid":
            # 我们标了已支付，支付宝说交易已关闭/不在成功态 —— 幽灵单，必须人看。
            mismatched += 1
            logger.critical(
                "[billing.tasks] 对账异常：本地已标记已支付，支付宝状态={} invoice={} "
                "out_trade_no={}（疑似伪造通知或退款未同步，需人工核对）",
                status_text, invoice.number, invoice.transaction_id,
            )

    return {
        "checked": len(rows),
        "compensated": compensated,
        "mismatched": mismatched,
        "errors": errors,
    }


def _yuan(raw: Any) -> Optional[float]:
    """支付宝的金额是字符串；解析失败返回 None（由 amount_matches 判为不符）。"""
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


@celery_app.task(bind=True, name=TASK_RECONCILE)
def reconcile_alipay_orders(self, lookback_days: Optional[int] = None) -> dict[str, Any]:
    """每日支付对账（补漏单 + 揪幽灵单）。"""
    # ★ 非支付宝网关时**跳过并说明原因**，而不是硬跑一遍：
    #   硬跑会向支付宝查一批 `mock-xxx` 的单号，全量返回 TRADE_NOT_EXIST，
    #   然后每条 paid 账单都被判成"幽灵单" ⇒ 一夜之间刷出成百条 CRITICAL 告警，
    #   而真相只是"这个环境用 mock 支付"。
    #   ★ 注意返回里带 `ran=False`：**跳过必须可观测**，不能和"跑完了、没问题"
    #     长得一样（那正是本仓反复收敛的"静默退化"形态）。
    gw = (config.payment_gateway or "").strip().lower()
    if gw != "alipay":
        logger.info("[billing.tasks] 跳过支付对账：当前网关为 {}（非 alipay）", gw)
        CELERY_TASK_RESULTS.inc(task=TASK_RECONCILE, status="skipped")
        return {"ran": False, "reason": "not_alipay", "gateway": gw}

    try:
        summary = _run(lambda db: _reconcile(db, lookback_days=lookback_days))
        CELERY_TASK_RESULTS.inc(task=TASK_RECONCILE, status="ok")
        logger.info(
            "[billing.tasks] 支付对账完成：核对={} 补开通={} 异常={} 查询失败={}",
            summary["checked"], summary["compensated"],
            summary["mismatched"], summary["errors"],
        )
        return {"ran": True, **summary}
    except Exception:
        logger.exception("[billing.tasks] 支付对账失败")
        CELERY_TASK_RESULTS.inc(task=TASK_RECONCILE, status="infra_failure")
        raise


# ============================================================================
# 同步桥（放在最后：上面的任务体读起来更像业务，不必先看桥）
# ============================================================================

def _run(coro_factory) -> dict[str, Any]:
    """把 `async def fn(db)` 桥到 Celery 的同步上下文里。

    ★ 这里用 `asyncio.run` 是**安全**的，前提是每次执行都新建 engine：
      `asyncio.run` 每次建一个新的 event loop 并在结束时关闭它；
      asyncpg 的连接绑定在创建它的 loop 上，所以复用全局 engine 时
      "第二次执行必挂"。本模块每次 `_execute_with_session` 都新建
      engine（NullPool）+ dispose ⇒ loop 与连接同生同死，不存在错配。
      （这也解释了为什么 `modules/memory/tasks.py` 不能照抄这一句：
        它的 DB 访问走应用级 `get_async_session()`，无法每次都换 engine。）
    """
    import asyncio

    return asyncio.run(_execute_with_session(coro_factory))


__all__ = [
    "TASK_EXPIRE_PENDING",
    "TASK_RECONCILE",
    "TASK_SWEEP_SUBSCRIPTIONS",
    "expire_pending_invoices",
    "reconcile_alipay_orders",
    "sweep_expired_subscriptions",
]

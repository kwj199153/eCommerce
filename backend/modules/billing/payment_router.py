"""支付宝回调 + 待支付查询端点（P0，2026-09-25）

这个文件的每一行都围绕一件事：**真实支付的第二段（收钱）发生在这里**。

==============================================================================
★ 免鉴权 ≠ 免验签（本文件最重要的一条，也是最容易写错的一条）
==============================================================================
`/billing/webhook/alipay` 由**支付宝服务器**调用 —— 它没有、也不可能有我们的
Bearer Token。所以这条路由必须挂在鉴权之外（main.py 里不加 BUSINESS_AUTH）。

但这**不**意味着它没有门。它有两道别的门，而且比 Bearer Token 更关键：

  ① **验签**（`AlipayGateway.verify_notify`）：用支付宝公钥验 RSA2 签名。
     没有这一步，任何人 `curl -d "out_trade_no=...&trade_status=TRADE_SUCCESS"`
     就能白拿一份年付套餐。这是支付集成里最经典的漏洞。
  ② **金额核对**（`payments.amount_matches`）：验签只证明"消息来自支付宝"，
     不证明"金额和我们账单一致"。不核金额，一张 0.01 元的真通知
     就能开通 2990 元的套餐。

⇒ 判据：**免鉴权不免验签**。两者是正交的门，不能互相顶替。

==============================================================================
★ 响应约定：只有 "success" 才让支付宝停止重投
==============================================================================
支付宝的异步通知是 at-least-once：响应体不是恰好 `success` 时，
它按 4m / 10m / 10m / ... 的节奏反复投递（最长约 24 小时）。
所以这里的每个分支都要**明确表态**，不能"反正返回 200 就行"：

  · 处理成功（含"已经处理过"）  → 200 + "success"   停投
  · 验签失败 / 找不到账单 / 金额不符 → 非 success     继续投（给我们修正窗口）

★ 为什么"找不到账单"要让它继续投：这通常意味着我们的库正处在
  迁移/恢复/回滚的中间态。让它重投，等环境恢复后这笔钱就自动补上了。
  直接回 success 的话，那笔钱在支付宝侧已结清、在我们侧没有任何记录，
  只能等用户投诉。

==============================================================================
★ 为什么这里也要"锁 + 重载"
==============================================================================
webhook 与「日对账补偿任务」会同时处理同一笔账单（webhook 丢失的假设不成立时
两者必然撞车）。真正的幂等实现在 `payments.settle_invoice()` 里（行锁 + 重载），
本文件只负责把"要不要叫它"决定清楚。见该函数的 docstring。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import require_acting_user
from core.database import get_db
from core.identity.models import User
from core.logger import get_logger
from core.timefmt import utc_iso
from modules.billing.models import Invoice
from modules.billing.payments import (
    amount_matches,
    pending_payment_payload,
    settle_invoice,
)
from modules.billing.qr import qr_svg_data_uri
from platforms.payment.alipay import AlipayGateway

router = APIRouter(prefix="/billing", tags=["计费-支付"])

_log = get_logger("billing.webhook")

#: 支付宝要求"已收到"时返回的字面量。**不能**加空格、不能是 JSON。
_ACK = "success"
_NACK = "failure"


# ============================================================================
# ① 支付宝异步通知（本文件的重点）
# ============================================================================

@router.post(
    "/webhook/alipay",
    # ★ 明确声明响应类型：`PlainTextResponse` 而不是默认的 JSON。
    #   若返回 JSON，body 会带上引号（`"success"`），支付宝不认，
    #   于是它会把每一条通知都重投 24 小时 —— 而我们的日志里全是"处理成功"。
    response_class=PlainTextResponse,
    include_in_schema=True,
)
async def alipay_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """接收支付宝支付结果通知（**免鉴权，但强制验签**）。"""
    # 支付宝用 `application/x-www-form-urlencoded` 发送；`request.form()`
    # 同时兼容 query string（部分沙箱/调试工具会拼在 URL 上）。
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    if not params:
        _log.warning("支付宝回调没有表单参数 ⇒ 拒收")
        return PlainTextResponse(_NACK, status_code=status.HTTP_400_BAD_REQUEST)

    # ★ 直接实例化 AlipayGateway 而不是走 `get_gateway()`：
    #   这条路径**永远**是支付宝（URL 就是 alipay），
    #   不该受 `config.payment_gateway` 影响。若走工厂，运维把网关临时切回 mock
    #   就会导致真实回调**再也验不了签**（而我们可能还想收着余下的款）。
    gateway = AlipayGateway()

    try:
        verified = gateway.verify_notify(params)
    except Exception as exc:  # noqa: BLE001 —— 缺密钥/报文异常统一按"无法验签"处理
        # ★ 这里**不能**返回 success：那等于在"无法判断真伪"时默认相信对方。
        _log.error(
            "支付宝回调无法验签（配置或报文异常）⇒ 拒收并让支付宝重投：{}", exc
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    if not verified:
        _log.error(
            "支付宝回调研签失败 ⇒ 拒收（可能是伪造请求）out_trade_no={} trade_status={}",
            params.get("out_trade_no"), params.get("trade_status"),
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_400_BAD_REQUEST)

    notify = gateway.parse_notify(params)

    if not gateway.app_id_matches(notify):
        _log.error(
            "支付宝回调的 app_id 与本应用不一致 ⇒ 拒收（回调地址配串了？）"
            " 收到={} 本应用={} out_trade_no={}",
            notify.app_id, "(已配置)", notify.out_trade_no,
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_400_BAD_REQUEST)

    if not notify.out_trade_no:
        _log.error("支付宝回调缺少 out_trade_no ⇒ 无法定位账单")
        return PlainTextResponse(_NACK, status_code=status.HTTP_400_BAD_REQUEST)

    invoice = (
        await db.execute(
            select(Invoice).where(Invoice.transaction_id == notify.out_trade_no)
        )
    ).scalar_one_or_none()

    if invoice is None:
        # 见文件头：让它继续重投（可能只是我们的库在恢复中）。
        _log.error(
            "支付宝回调对应的账单不存在 out_trade_no={} trade_no={} trade_status={}"
            "（若持续出现，请核对是否把生产回调打到了非生产库）",
            notify.out_trade_no, notify.trade_no, notify.trade_status,
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_404_NOT_FOUND)

    # ---- 未付款状态：明确表态，不做任何开通 ----
    if not notify.is_paid:
        if notify.is_closed:
            # 超时未付 / 交易关闭。把他标成 expired（若还停在 pending），
            # 让列表页不再显示"待支付"。
            if invoice.status == "pending":
                invoice.status = "expired"
                await db.commit()
            _log.info(
                "支付宝通知交易已关闭 out_trade_no={} status={}",
                notify.out_trade_no, notify.trade_status,
            )
            return PlainTextResponse(_ACK)
        # WAIT_BUYER_PAY 等中间态：确认收到，但什么都不做（后续还会有通知）。
        _log.info(
            "支付宝通知中间态 out_trade_no={} status={}",
            notify.out_trade_no, notify.trade_status,
        )
        return PlainTextResponse(_ACK)

    # ---- 金额核对（见文件头门 ②）----
    if not amount_matches(invoice, notify.amount_yuan):
        # ★ 不激活、不回 success：这是一笔"钱与单不匹配"的异常，必须留给人看见。
        _log.critical(
            "支付宝回调金额与账单不符 ⇒ 拒绝开通（需人工核对）"
            " invoice={} 账单金额={} 通知金额={} out_trade_no={} trade_no={}",
            invoice.number, invoice.amount, notify.total_amount,
            notify.out_trade_no, notify.trade_no,
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_400_BAD_REQUEST)

    outcome = await settle_invoice(
        db,
        invoice.id,
        paid_at=notify.paid_at_utc or datetime.utcnow(),
        trade_no=notify.trade_no,
    )

    if not outcome.ok:
        # 账单状态与"支付成功"自相矛盾（如已 refunded）。不回 success，
        # 让它重投并保持在告警里 —— 静默吞掉等于让用户的钱凭空消失。
        _log.error(
            "支付宝回调结算失败 invoice={} reason={} out_trade_no={}",
            invoice.number, outcome.reason, notify.out_trade_no,
        )
        return PlainTextResponse(_NACK, status_code=status.HTTP_409_CONFLICT)

    _log.info(
        "支付宝回调处理完成 invoice={} user={} already_paid={} activated={} trade_no={}",
        invoice.number, invoice.user_id, outcome.already_paid, outcome.activated,
        notify.trade_no,
    )
    # ★ 重复通知也回 success：语义是"这条消息我处理过了"，不是"我刚开通了"。
    return PlainTextResponse(_ACK)


# ============================================================================
# ② 待支付订单查询（供前端刷新页面后恢复二维码）
# ============================================================================

@router.get("/payment/pending")
async def get_pending_payment(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户是否有未支付的订单（返回最近的一张，没有则 null）。

    ★ 为什么需要它（而不是"下单响应当作唯一来源"）：
      用户下单后**刷新页面**是常态。没有这个接口，那张二维码就随响应体一起
      消失了，用户只能重新下单 —— 多出一张废单，且他很可能只在支付宝侧
      付了其中一张，于是"付了钱没到账"的投诉就来了。

    ★ 这里刻意只查 `pending`：已过期的单不该再引导用户去扫（码已经死了）。
      过期的单由 `/billing/payment/{invoice_id}` 按 id 查得到（供倒计时结束时展示）。

    ★ 为什么不复用 `payments.find_reusable_pending`（它看起来很像）：
      那个函数的语义是「**同套餐同周期**的可复用单」—— 因为它的调用方
      (`change_plan`) 正要判断"这次的套餐是否已有一张待付单"。
      而本接口要的是「**这个人任意一张**待支付单」（页面刷新后要显示的是
      "你有一笔待付款"，不关心它买的是什么）。
      ⇒ 两个不同的判定，就不该挤进同一个实现：为了迁就一方而把另一方的
        语义撑变形（给 plan_id 传哨兵值之类），是"复用"掩盖"语义不同"的典型。
        这里用一条独立、直白的查询。
    """
    result = await db.execute(
        select(Invoice)
        .where(Invoice.user_id == current_user.id, Invoice.status == "pending")
        .order_by(Invoice.issued_at.desc())
        .limit(1)
    )
    pending = result.scalar_one_or_none()
    return {
        "payment": pending_payment_payload(pending) if pending is not None else None
    }


# ============================================================================
# ③ 二维码图片（独立的 <img> 数据源）
# ============================================================================

@router.get("/payment/qr/{invoice_id}")
async def get_payment_qr(
    invoice_id: str,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """返回该账单二维码的 SVG data URI。

    ★ 为什么单独一个端点、而不是把 data URI 塞进下单响应：
      ① 轮询接口（`/payment/{id}`）每 3 秒一次。二维码 SVG 约 7KB、
         base64 后 ~9.4KB —— 塞进每次轮询等于每秒 3KB 的无谓流量，
         且浏览器无法缓存（响应体变了）；
      ② 独立成 `GET` 之后，`<img>` 的数据可以被前端缓存一次、复用整场支付。

    ★ 为什么是 JSON 而不是直接返回 `image/svg+xml`：
      前端用 axios 请求（**要带 Authorization 头**），返回 blob 再转
      objectURL 会多一步、且要处理 blob 生命周期；返回 JSON 里的 data URI
      可以直接绑给 `<img src>`，前端零样板代码。缺点是体积大 4/3，
      但这是一次性请求，可接受。
    """
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            # ★ 归属校验与"不存在"合并成同一分支（同一个 404 文案）：
            #   区分两者会让攻击者能枚举出"哪些 invoice_id 存在"。
            Invoice.user_id == current_user.id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="账单不存在")

    if not invoice.pay_url:
        raise HTTPException(status_code=404, detail="该账单没有二维码")

    if invoice.status == "paid":
        # ★ 已支付的单**不再**返回二维码：让用户重新扫一张已付的码，
        #   最好的结果是白扫，最坏的结果是重复付款。
        raise HTTPException(status_code=409, detail="该账单已完成支付")

    return {"qr_svg": qr_svg_data_uri(invoice.pay_url)}


# ============================================================================
# ④ 单笔支付状态（前端轮询）
# ============================================================================

@router.get("/payment/{invoice_id}")
async def get_payment_status(
    invoice_id: str,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """轮询一张账单的支付状态（前端据此决定关闭弹窗 / 提示超时）。"""
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.user_id == current_user.id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="账单不存在")

    payload = pending_payment_payload(invoice)
    payload["paid_at"] = utc_iso(invoice.paid_at)
    return {"payment": payload}


__all__ = ["router"]

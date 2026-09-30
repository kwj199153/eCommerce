"""
计费与用量 API 路由

提供用量查询、套餐信息、订阅管理、账单与支付方式等接口。

契约说明：本路由的响应字段与前端 `frontend/src/api/billing.ts` 严格对齐。
  - 套餐 `id` 输出为字符串（`str(plan.id)`），前端按字符串比较做「当前套餐」高亮
  - 套餐补全 `price_yearly`（后端无该列，按「年付 = 月付 × 10」折算）、
    `limits` 嵌套对象、`features` 字符串数组（后端存 JSON 字符串，此处解析）
  - 订阅补全 `billing_cycle`、`cancel_at_period_end`、`usage.ai_gen_*`（AIGC 复用 API 额度口径）

★ P1-4（2026-09-15）价目口径收敛
  「年付价」公式原先在本文件出现**两次**（`_serialize_plan` 用于展示、
  `change_plan` 用于真实扣款），两处各自硬编码 `* 10`。
  现已全部改为调用 `modules.billing.pricing`——展示与收款共用同一个函数，
  杜绝「页面写一个价、结算扣另一个价」。改价格只改 pricing.py。
"""

import json
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.timefmt import utc_iso

from core.database import get_db
from core.auth.dependencies import get_admin_user, require_acting_user
# ★ 演示身份判定唯一真源（core/auth/demo_identity.py）。见 change_plan 的分流说明。
from core.auth.demo_identity import is_demo_request
from core.metering.usage_tracker import UsageTracker, init_default_plans
from platforms.payment.gateway import (
    ChargeIntent,
    GatewayConfigError,
    get_gateway,
)
from modules.billing.pricing import (
    build_idempotency_key,
    is_duplicate_submission,
    normalize_cycle,
    period_end,
    plan_amount,
    subscription_state_fingerprint,
    yearly_price,
)
from modules.billing.payments import (
    find_reusable_pending,
    pending_payment_payload,
    supersede_other_pending,
)
from core.identity.models import User
from modules.billing.models import Subscription, SubscriptionPlan, Invoice, PaymentMethod


router = APIRouter(prefix="/billing", tags=["计费与用量"])

_log = get_logger("billing")


# ====== 网关 DTO -> ORM 的转换 ======

def _invoice_from_draft(
    draft,
    *,
    plan_id: Optional[int] = None,
    billing_cycle: Optional[str] = None,
) -> Invoice:
    """把支付网关返回的账单草案（纯数据 InvoiceDraft）转成 ORM 实体。

    ★ 为什么转换点在这个层，而不是让网关直接返回 Invoice：
      `platforms/payment/` 是**外部适配层**，只依赖 DTO。若它 import 业务 ORM
      实体（历史上确实如此：适配层曾直接 import 计费业务模块的 Invoice /
      SubscriptionPlan），适配层就反向耦合了业务模型 —— 独立部署 webhook
      服务、或换一家网关时，会被业务模型一起拖走。
      转换点全项目只有这一处，改动收敛在这里。

    ★ `plan_id` / `billing_cycle` 为什么是**关键字参数**而不是 InvoiceDraft 的字段：
      这两列回答的是「这笔钱买的是什么」—— 是**业务事实**，
      只有计费层知道（网关收到的只是一个 `plan_name` 字符串）。
      把它们塞进 InvoiceDraft，等于让适配层"认识"套餐主键，
      而那正是上一条要避免的耦合方向。
      ⇒ 网关填它知道的（渠道 / 订单号 / 二维码），计费层补它知道的（套餐 / 周期），
        唯一汇合点就是本函数。
    """
    return Invoice(
        id=draft.id or str(uuid.uuid4()),
        user_id=draft.user_id,
        number=draft.number,
        amount=draft.amount,
        currency=draft.currency,
        status=draft.status,
        description=draft.description,
        issued_at=draft.issued_at or datetime.utcnow(),
        paid_at=draft.paid_at,
        pdf_url=draft.pdf_url,
        idempotency_key=draft.idempotency_key,
        # ---- 下列字段回应"这笔钱买的是什么 / 走的哪个通道 / 码在哪" ----
        plan_id=plan_id,
        billing_cycle=normalize_cycle(billing_cycle) if billing_cycle else None,
        transaction_id=draft.transaction_id or None,
        payment_channel=draft.payment_channel or None,
        pay_url=draft.pay_url or None,
    )


# ====== 请求体 schema ======

class SubscribeRequest(BaseModel):
    plan_id: str
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


class AddPaymentMethodRequest(BaseModel):
    type: Literal["card", "alipay", "wechat"] = "card"
    brand: str = "visa"
    last4: str = "4242"
    exp_month: int = 12
    exp_year: int = 2027


class PaymentMethodActionRequest(BaseModel):
    action: Literal["set_default", "detach"]


# ====== 序列化 helper（前后端契约对齐） ======

def _serialize_plan(plan: SubscriptionPlan) -> dict:
    """套餐 → 前端 SubscriptionPlan 契约"""
    try:
        features = json.loads(plan.features) if plan.features else []
    except (json.JSONDecodeError, TypeError):
        features = []

    # ★ 后端无 price_yearly 列，按统一价目口径折算。
    #   ★★ 与 change_plan 的扣款金额共用 `yearly_price()`——这是「展示价 == 收款价」
    #   的硬保证。此处**不允许**再写一遍 `* 10`（改价时必须两处同改 = 迟早出事）。
    price_yearly = yearly_price(plan.price_monthly)

    return {
        "id": str(plan.id),
        "name": plan.name,
        "display_name": plan.display_name,
        "price_monthly": plan.price_monthly,
        "price_yearly": price_yearly,
        "features": features,
        "limits": {
            "api_calls_per_month": plan.api_calls_limit,
            "agent_chats_per_month": plan.agent_chat_limit,
            "shops_limit": plan.max_shops,
            "team_members": plan.max_users,
            # AIGC 生成次数无独立列，复用 API 额度口径（与 UsageTracker.AIGC_GENERATION 一致）
            "ai_generations": plan.api_calls_limit,
        },
        # 推荐位：pro 套餐标记为「推荐」
        "recommended": plan.name == "pro",
    }


def _serialize_subscription(sub: Subscription) -> dict:
    """订阅 → 前端 Subscription 契约"""
    plan = sub.plan
    return {
        "id": sub.id,
        "status": sub.status,
        # 计费周期（P1-4 新增落库字段）。旧数据由迁移填 'monthly'，
        # 故这里兜底 None 以免老行序列化出 null 让前端类型不符。
        "billing_cycle": normalize_cycle(getattr(sub, "billing_cycle", None)),
        "plan": _serialize_plan(plan),
        "usage": {
            "api_calls_used": sub.api_calls_used,
            "api_calls_limit": plan.api_calls_limit,
            "agent_chats_used": sub.agent_chats_used,
            "agent_chat_limit": plan.agent_chat_limit,
            # AIGC 用量无独立列，按 API 用量口径呈现
            "ai_gen_used": sub.api_calls_used,
            "ai_gen_limit": plan.api_calls_limit,
        },
        # ★ 一律走 core/timefmt.py::utc_iso —— 裸 isoformat() 输出无偏移字符串，
        #   浏览器按本地时区解析，UTC+8 下周期起止日期在午夜附近会显示成前一天。
        "period": {
            "start": utc_iso(sub.current_period_start),
            "end": utc_iso(sub.current_period_end),
        },
        "cancel_at_period_end": sub.cancel_at_period_end,
        "created_at": utc_iso(sub.created_at),
    }


async def _get_subscription_or_404(db: AsyncSession, user_id: str) -> Subscription:
    """取用户订阅，不存在则 404"""
    result = await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="尚未订阅任何套餐",
        )
    return sub


# ====== 用量 & 套餐（只读） ======

@router.get("/usage")
async def get_usage(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的使用量信息"""
    usage_info = await UsageTracker.get_usage_info(db, current_user.id)
    return usage_info


@router.get("/plans")
async def list_plans(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有可用的订阅套餐列表（前端套餐对比卡片）

    说明：套餐列表属于公开信息（用户登录前即可查看定价），不挂鉴权依赖。
    """
    result = await db.execute(
        select(SubscriptionPlan).order_by(SubscriptionPlan.price_monthly)
    )
    plans = result.scalars().all()
    return {"plans": [_serialize_plan(p) for p in plans]}


@router.get("/subscription")
async def get_current_subscription(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的订阅详情（含当前套餐、到期时间、用量）"""
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return {"subscription": None}
    return {"subscription": _serialize_subscription(subscription)}


# ====== 订阅管理（写操作） ======

@router.post("/subscribe")
async def change_plan(
    body: SubscribeRequest,
    request: Request,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """
    升级 / 切换 / 续费套餐

    请求体：{ "plan_id": str, "billing_cycle": "monthly" | "yearly" }

    plan_id 为套餐表主键的字符串形式（与 /plans 返回的 id 一致）。

    ==========================================================================
    ★★ 两种支付形态（P0/P1，2026-09-25 支付宝接入后）
    ==========================================================================

      **同步**（mock / 演示身份）—— 与接入支付宝前完全一致：
        扣款成功即开通，落一张 paid 账单，响应 `charged=True`。

      **异步**（支付宝当面付）—— 两段式：
        ① 本端点：调 `alipay.trade.precreate` 拿二维码 → 落一张 `pending`
           账单 → **不动订阅**（用户还没付钱，凭什么动他的权益）→
           响应 `charged=False, requires_confirmation=True, payment={...}`；
        ② 用户扫码付款 → 支付宝回调 `POST /billing/webhook/alipay` →
           `modules/billing/payments.py::settle_invoice()` 才把账单改 paid、
           把订阅改成 active。

      ★ 为什么异步必须两段：`charge()` 返回 success 只代表"二维码生成成功"。
        沿用同步那套（先开权限、后收钱）就是**用户没付钱就拿到套餐** ——
        而且它在测试环境完全看不出来（因为测试环境走 mock，是同步的）。

      ★★ 「演示用户保持现状」是怎么实现的（老板的硬要求）：
        **两级配合**，缺任何一级都会变成死代码 —— 这正是本轮踩到的坑：

          ① **路由级**：本模块全部端点用 `require_acting_user`
             （`core/auth/dependencies.py`）而不是 `get_current_user`。
             ★ 这一级是**前置**的：`get_current_user` **不认** `demo-` 哨兵，
               演示请求在鉴权层就被 401 —— 那么下面 ② 的分支**永远走不到**。
               写成 `Depends(get_current_user)` 时，② 是一段看着很对、
               注释很全、但一行都不会执行的死代码（门禁再强也测不到它）。
          ② **业务级**：`is_demo_request(request)` 为真 ⇒ **强制**取
             `MockGateway` ⇒ 同步扣款成功 ⇒ 订阅立刻 active，整条链路
             与接入支付宝前逐字节一致（**无需扫码**）。

        这一条不影响真实用户：`is_demo_request` 判定的是「凭据形态
        （`demo-` 前缀 + Bearer）+ `config.demo_mode`」，而真实用户带的是 JWT，
        判定恒为 False；测试用例也带真 JWT ⇒ 现有支付用例天然不受影响。

        判据：演示身份与真实用户走的是**同一个端点里的两条分支**，
        而不是两套代码 —— 后者必然漂移，且漂移的那一边没人测。

        ★ 反向断言（同样必须成立，否则「认演示」会变成「谁都能白拿套餐」）：
          `demo_mode=False`（生产）下哨兵与任意伪造串同等待遇 ⇒ 401；
          `auth_required=True` 下取更严的一侧 ⇒ 401；
          演示账号找不到 / 是平台超管 / 已停用 ⇒ 三重守卫降级 ⇒ 401。
          三条守卫都在 `resolve_demo_user` 里，本模块一行都不复制。

    返回：{ subscription, client_secret, charged, requires_confirmation?, payment? }
      - charged=True   本次真的走了扣款（同步形态）
      - charged=False  未扣款。**三种原因必须分清**（前端据此显示不同文案）：
          · already_subscribed=True  → 同套餐同周期重复提交，权益已满足
          · requires_confirmation    → 已下单待支付，请看 payment.qr_code_url
          · skipped_reason           → 金额为 0（免费套餐）等，无需支付
      ★ 前端不得把「HTTP 200」等同于「已收款」，必须看 charged。

    ★ P1-4 收敛的三处「钱」行为（口径统一 / 重复提交不重复扣款 / 先扣款后改订阅）
      不变量由 tests/test_billing_payment.py 守护，改动前先跑那一组。
      ★ 判据：让不可回滚的那一步（收钱）尽可能晚、尽可能靠后，
        把可回滚的 DB 写入放在它后面。

    ★ 本函数体内的实现细节注释已全部外迁到测试的 docstring
      （理由：注释只有被测试锁住才不会腐化；本文件的读者关心契约，
        测试的读者关心坑。实测证据见
        .workbuddy/probes/project-audit-20260915/09-支付链路-实测证据.txt）：
        · 行锁 + populate_existing   → test_concurrent_duplicate_submission_creates_single_invoice
        · rollback 前落标量 / 只吞幂等键冲突
                                     → test_first_purchase_race_returns_409_not_500
                                       test_other_integrity_errors_are_not_swallowed
    """
    plan_id = body.plan_id
    billing_cycle = normalize_cycle(body.billing_cycle)

    if not plan_id:
        raise HTTPException(status_code=400, detail="缺少 plan_id")

    # plan_id 为字符串形式的整数主键
    try:
        pid = int(plan_id)
    except (ValueError, TypeError):
        # 兼容可能的 name 字符串（free/pro/enterprise）
        result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == plan_id))
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在")
    else:
        result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == pid))
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail="套餐不存在")

    # 取订阅（可能不存在）。
    # ★★ `with_for_update()` 与 `.execution_options(populate_existing=True)` 缺一不可
    #   （少任一个 = 门禁从未生效）。坑与实测数据见：
    #   tests/test_billing_payment.py::test_concurrent_duplicate_submission_creates_single_invoice
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sub = result.scalar_one_or_none()

    now = datetime.utcnow()

    # ★ 落成标量：rollback 之后还要用的值，必须在 rollback 之前取出。
    #   tests/test_billing_payment.py::test_first_purchase_race_returns_409_not_500
    _user_id = current_user.id
    _plan_id = plan.id

    # ---- 守卫：同套餐同周期重复提交 → 不扣款、不开票 ----
    if is_duplicate_submission(sub, plan.id, billing_cycle):
        # ★ 真实网关下要**先看一眼有没有待支付单**：用户上次下单没付、
        #   这一次又点同一套餐时，`is_duplicate_submission` 只在
        #   "已经生效的订阅"命中，而下单未付的情况订阅根本没变
        #   ⇒ 这里能走到，说明确实是重复提交（不是待支付），直接返回。
        return {
            "subscription": _serialize_subscription(sub),
            "client_secret": "",
            "charged": False,
            "already_subscribed": True,
            "message": "当前已在所选套餐的有效周期内，未重复扣款",
        }

    # ======================================================================
    # ★★ 演示身份分流（老板硬要求：演示用户无需扫码，保持现状）
    # ======================================================================
    # `is_demo_request` 是「这次请求是不是以演示身份行事」的唯一真源
    # （core/auth/demo_identity.py），它只看**凭据形态 + config.demo_mode**，
    # 不解析身份。真实用户带 JWT ⇒ 恒 False ⇒ 走真实网关。
    demo = is_demo_request(request)
    if demo:
        gateway = get_gateway("mock")
        _log.info("演示身份走模拟支付直通 user={} plan={}", _user_id, _plan_id)
    else:
        gateway = get_gateway()
        # ---- 两段式第 0 步：能复用上一张未支付的二维码吗？ ----
        # ★ 见 payments.find_reusable_pending 的论证：两段式之后订阅行不变，
        #   所以"连点两次"在订阅状态上完全同形，只能靠"有没有待支付单"来分辨。
        reusable = await find_reusable_pending(
            db, current_user.id, plan.id, billing_cycle, now=now
        )
        if reusable is not None:
            return {
                "subscription": _serialize_subscription(sub) if sub else None,
                "client_secret": "",
                "charged": False,
                "requires_confirmation": True,
                "already_pending": True,
                "payment": pending_payment_payload(reusable),
                "message": "已有一笔待支付的订单，请继续扫码完成支付（未重复下单）",
            }

    # ---- 先扣款（不可回滚的一步），成功后再改订阅 ----
    amount = plan_amount(plan, billing_cycle)
    # 幂等键基底 = 「本次变更的起点状态」，见 pricing.subscription_state_fingerprint
    idem_key = build_idempotency_key(
        current_user.id, plan.id, billing_cycle, subscription_state_fingerprint(sub)
    )
    try:
        charge = await gateway.charge(ChargeIntent(
            user_id=current_user.id,
            amount=amount,
            currency="CNY",
            description=f"{plan.display_name}{'年付' if billing_cycle == 'yearly' else '月付'}",
            billing_cycle=billing_cycle,
            plan_name=plan.name,
            idempotency_key=idem_key,
        ))
    except NotImplementedError as exc:
        # 配置里写了一个「已知但未接入」的真实网关（stripe/wechat/...）。
        # ★ 为什么是 501 而非 500、且绝不降级成 mock 成功：
        #   tests/test_billing_payment.py::test_unimplemented_gateway_returns_501
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except GatewayConfigError as exc:
        # ★ 已接入的真实网关但这个部署**没配钥匙**（缺 app_id / 私钥 / 回调地址）。
        #   503 而不是 501：代码在、依赖没就绪，运维照 503 的语义去修配置；
        #   501 会把人引到"这个功能还没开发"的错误方向。
        #   ★ 同样绝不降级成 mock 成功 —— 那正是"用户白拿套餐"的形态。
        await db.rollback()
        _log.error("支付网关配置不完整，拒绝下单：{}", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"支付通道未就绪：{exc}",
        ) from exc

    if not charge.success:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=charge.error or "支付失败，请重试",
        )

    # ======================================================================
    # ★★ 异步支付（支付宝当面付）：只落 pending 账单，**不开通**任何权益
    # ======================================================================
    if charge.requires_confirmation:
        invoice = _invoice_from_draft(
            charge.invoice, plan_id=plan.id, billing_cycle=billing_cycle
        )
        db.add(invoice)
        # 顶掉同一用户此前其它还没付的待支付单（保留刚生成的这张）。
        # ★ 让"同一时刻只有一张有效二维码"，降低用户扫两次付两次的概率；
        #   被顶掉的那些若钱还是到了，settle_invoice 会照常认账（见 payments.py 不变量 ③）。
        await supersede_other_pending(db, current_user.id, keep_invoice_id=invoice.id, now=now)

        try:
            await db.commit()
        except IntegrityError as exc:
            # 与同步形态同一道兜底闸（并发首购时唯一约束拦下其中一个）。
            # 只吞幂等键冲突，其余完整性错误原样抛 —— 见
            # tests/test_billing_payment.py::test_other_integrity_errors_are_not_swallowed
            if "idempotency_key" not in str(getattr(exc, "orig", exc)):
                raise
            await db.rollback()
            _log.warning(
                "待支付账单幂等键冲突（并发下单），按重复提交拒绝 user={} plan={} cycle={} key={}",
                _user_id, _plan_id, billing_cycle, idem_key,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="检测到重复下单，请刷新后查看待支付订单",
            ) from exc

        await db.refresh(invoice)
        return {
            # 订阅**没有**被改动 —— 用户当前仍在原有套餐上（付了钱才升级）。
            # 从未订阅过的用户在支付完成前就是 None（前端需容忍 null）。
            "subscription": _serialize_subscription(sub) if sub else None,
            "client_secret": "",
            "charged": False,
            "requires_confirmation": True,
            "payment": pending_payment_payload(invoice),
            "message": "请使用支付宝扫描二维码完成支付，支付成功后套餐将自动生效",
        }

    # ---- 扣款成功（同步形态）：写订阅状态 + 落账单 ----
    if sub is None:
        # 首次订阅：新建
        sub = Subscription(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            plan_id=plan.id,
            status="active",
            billing_cycle=billing_cycle,
            cancel_at_period_end=False,
            current_period_start=now,
            current_period_end=period_end(now, billing_cycle),
        )
        db.add(sub)
    else:
        # 切套餐 / 续费：更新 plan、周期、清除取消标记
        sub.plan_id = plan.id
        sub.status = "active"
        sub.billing_cycle = billing_cycle
        sub.cancel_at_period_end = False
        sub.current_period_start = now
        sub.current_period_end = period_end(now, billing_cycle)

    sub.updated_at = now

    # 落账单（零元时网关返回 invoice=None，此处自然跳过）
    # 网关给的是**纯数据草案**，由本层转成 ORM 实体后落库（见 _invoice_from_draft）。
    if charge.invoice is not None:
        db.add(_invoice_from_draft(
            charge.invoice, plan_id=plan.id, billing_cycle=billing_cycle
        ))

    try:
        await db.commit()
    except IntegrityError as exc:
        # ★ 兜底闸：只在「同一用户此前没有任何订阅」（无行可锁）的竞态下生效，
        #   由 invoices.idempotency_key 唯一约束拦下其中一个。两道闸的分工、
        #   以及「为什么不能既 rollback 又读库」见：
        #   tests/test_billing_payment.py::test_first_purchase_race_returns_409_not_500
        #   ⚠️ 只吞幂等键冲突，其他完整性错误必须原样抛出：
        #   tests/test_billing_payment.py::test_other_integrity_errors_are_not_swallowed
        if "idempotency_key" not in str(getattr(exc, "orig", exc)):
            raise
        await db.rollback()
        # ★ 只能用回滚前取好的标量（_user_id / _plan_id），不能读 ORM 属性；
        #   日志占位必须用 loguru 的 `{}`（`%s` 不报错，但会丢参数）。
        #   tests/test_billing_payment.py::test_first_purchase_race_returns_409_not_500
        _log.warning(
            "账单幂等键冲突，按重复提交拒绝 user={} plan={} cycle={} key={}",
            _user_id, _plan_id, billing_cycle, idem_key,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="检测到重复提交，请刷新后查看当前订阅状态",
        ) from exc

    await db.refresh(sub)

    return {
        "subscription": _serialize_subscription(sub),
        # 前端 changePlan 返回里含 client_secret（Stripe 支付意图）。
        # mock 下无真实 secret，返回网关透传值（空串占位）。
        "client_secret": charge.client_secret,
        "charged": charge.invoice is not None,
        "requires_confirmation": False,
        "skipped_reason": charge.skipped_reason,
    }


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """取消订阅（周期结束后生效）"""
    sub = await _get_subscription_or_404(db, current_user.id)

    if sub.status != "active":
        raise HTTPException(status_code=400, detail="当前订阅非活跃状态，无需取消")

    if sub.cancel_at_period_end:
        raise HTTPException(status_code=400, detail="订阅已处于「待取消」状态")

    sub.cancel_at_period_end = True
    sub.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sub)

    return {"subscription": _serialize_subscription(sub)}


@router.post("/resume")
async def resume_subscription(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """恢复已发起取消的订阅"""
    sub = await _get_subscription_or_404(db, current_user.id)

    if not sub.cancel_at_period_end:
        raise HTTPException(status_code=400, detail="当前订阅未处于「待取消」状态")

    sub.cancel_at_period_end = False
    sub.status = "active"
    sub.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sub)

    return {"subscription": _serialize_subscription(sub)}


# ====== 账单（发票） ======

@router.get("/invoices")
async def list_invoices(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """获取账单历史（分页）"""
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    result = await db.execute(
        select(Invoice)
        .where(Invoice.user_id == current_user.id)
        .order_by(Invoice.issued_at.desc())
    )
    all_invoices = result.scalars().all()

    total = len(all_invoices)
    start = (page - 1) * page_size
    items = all_invoices[start:start + page_size]

    return {
        "invoices": [
            {
                "id": inv.id,
                "number": inv.number,
                "amount": inv.amount,
                "currency": inv.currency,
                "status": inv.status,
                "description": inv.description,
                "issued_at": utc_iso(inv.issued_at),
                "paid_at": utc_iso(inv.paid_at),
                "pdf_url": inv.pdf_url,
            }
            for inv in items
        ],
        "total": total,
        "page": page,
    }


# ====== 支付方式 ======

def _serialize_payment_method(pm: PaymentMethod) -> dict:
    return {
        "id": pm.id,
        "type": pm.type,
        "brand": pm.brand,
        "last4": pm.last4,
        "exp_month": pm.exp_month,
        "exp_year": pm.exp_year,
        "is_default": pm.is_default,
    }


@router.get("/payment-methods")
async def list_payment_methods(
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """获取支付方式列表"""
    result = await db.execute(
        select(PaymentMethod)
        .where(PaymentMethod.user_id == current_user.id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
    )
    pms = result.scalars().all()
    return {"payment_methods": [_serialize_payment_method(pm) for pm in pms]}


@router.post("/payment-methods")
async def add_payment_method(
    body: AddPaymentMethodRequest,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """
    添加支付方式

    请求体：{ "payment_method_id": str } 或 { "type", "brand", "last4", ... }

    说明：真实场景跳转 Stripe 返回 payment_method_id，再回填卡信息。
    此处为模拟闭环：接受前端传的卡信息直接落库。
    """
    # 已有支付方式数（用于判断是否首个默认）
    result = await db.execute(
        select(PaymentMethod).where(PaymentMethod.user_id == current_user.id)
    )
    existing = result.scalars().all()

    pm_type = body.type
    brand = body.brand
    last4 = body.last4
    exp_month = body.exp_month or 12
    exp_year = body.exp_year or 2027

    pm = PaymentMethod(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        type=pm_type,
        brand=brand,
        last4=str(last4)[-4:],
        exp_month=exp_month,
        exp_year=exp_year,
        is_default=(len(existing) == 0),  # 首个自动设为默认
    )
    db.add(pm)
    await db.commit()
    await db.refresh(pm)

    return _serialize_payment_method(pm)


@router.put("/payment-methods/{method_id}")
async def update_payment_method(
    method_id: str,
    body: PaymentMethodActionRequest,
    current_user: User = Depends(require_acting_user),
    db: AsyncSession = Depends(get_db),
):
    """
    支付方式操作

    请求体：{ "action": "set_default" | "detach" }
      - set_default：设为默认（取消其他默认）
      - detach：删除
    """
    result = await db.execute(
        select(PaymentMethod).where(
            PaymentMethod.id == method_id,
            PaymentMethod.user_id == current_user.id,
        )
    )
    pm = result.scalar_one_or_none()
    if not pm:
        raise HTTPException(status_code=404, detail="支付方式不存在")

    action = body.action

    if action == "set_default":
        # 取消其他默认
        all_result = await db.execute(
            select(PaymentMethod).where(PaymentMethod.user_id == current_user.id)
        )
        for p in all_result.scalars().all():
            p.is_default = (p.id == method_id)
        await db.commit()
        return {"message": "已设为默认支付方式"}

    if action == "detach":
        # 若删除的是默认，把下一个设为默认
        was_default = pm.is_default
        await db.delete(pm)
        await db.commit()
        if was_default:
            next_result = await db.execute(
                select(PaymentMethod)
                .where(PaymentMethod.user_id == current_user.id)
                .order_by(PaymentMethod.created_at.desc())
            )
            next_pm = next_result.scalars().first()
            if next_pm:
                next_pm.is_default = True
                await db.commit()
        return {"message": "支付方式已删除"}

    raise HTTPException(status_code=400, detail="未知操作，支持 set_default / detach")


# ====== 内部管理接口（仅管理员） ======

@router.post("/init-plans")
async def initialize_plans(
    admin_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    初始化默认套餐数据（仅首次部署时调用）

    ⚠️ 管理员接口：仅 admin 角色可调用，防止任意用户重置套餐数据。
    """
    await init_default_plans(db)
    return {"message": "套餐数据初始化完成"}

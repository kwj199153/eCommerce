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
  现已全部改为调用 `core.billing.pricing`——展示与收款共用同一个函数，
  杜绝「页面写一个价、结算扣另一个价」。改价格只改 pricing.py。
"""

import json
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger

from core.database import get_db
from core.auth.dependencies import get_current_user, get_admin_user
from core.billing.usage_tracker import UsageTracker, init_default_plans
from core.billing.payment_gateway import get_gateway, ChargeIntent
from core.billing.pricing import (
    build_idempotency_key,
    is_duplicate_submission,
    normalize_cycle,
    period_end,
    plan_amount,
    subscription_state_fingerprint,
    yearly_price,
)
from modules.user_subscription.models import (
    User,
    Subscription,
    SubscriptionPlan,
    Invoice,
    PaymentMethod,
)


router = APIRouter(prefix="/billing", tags=["计费与用量"])

_log = get_logger("billing")


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
        "period": {
            "start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        },
        "cancel_at_period_end": sub.cancel_at_period_end,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    升级 / 切换 / 续费套餐

    请求体：{ "plan_id": str, "billing_cycle": "monthly" | "yearly" }

    plan_id 为套餐表主键的字符串形式（与 /plans 返回的 id 一致）。

    支付流程：面向 `PaymentGateway` 协议编程（见 core/billing/payment_gateway.py），
    扣款由当前配置的网关完成（默认 mock 模拟支付成功）。
    接入 Stripe / 支付宝 / 微信时改 config.payment_gateway 即可，无需改动此端点。

    返回：{ subscription, client_secret, charged, already_subscribed? }
      - charged=True  本次真的走了扣款
      - charged=False 未扣款（命中「同套餐同周期重复提交」或金额为 0）
      ★ 前端不得把「HTTP 200」等同于「已收款」，必须看 charged。

    ★ P1-4 修复的三处行为（实测证据见
      .workbuddy/probes/project-audit-20260915/09-支付链路-实测证据.txt）

      1) 金额口径：原先内联 `price_monthly * 10`，与 _serialize_plan 各写一遍。
         现统一走 core.billing.pricing.plan_amount()。

      2) 重复提交不重复扣款：原先无论当前是什么套餐，只要调用就重新扣款 ——
         实测连点两次「升级」得到 2 张账单（真实网关下 = 扣两次钱）。
         现在同套餐 + 同计费周期 + 仍在有效期内 ⇒ 直接返回现状、不扣款、不开票。
         续费（周期已过期）不受影响，因为 is_period_active() 会返回 False。

      3) 顺序：原先「先改订阅 → 再扣款」。虽然失败时不 commit 也回滚得掉，
         但一旦接真实网关（扣款成功后再写 DB 失败），就会出现「钱收了、
         订阅没生效」。现在改为「先扣款 → 成功后再改订阅」——钱动了才有状态变更。
         ★ 判据：让不可回滚的那一步（收钱）尽可能晚、尽可能靠后，
           把可回滚的 DB 写入放在它后面。
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
    #
    # ★★ `with_for_update()` 是并发重复扣款的第一道闸（P1-4）：
    #   它把「同一用户的订阅变更」串行化——第二个并发请求会**阻塞**到
    #   第一个提交完，然后读到已更新的订阅状态，被下面的
    #   `is_duplicate_submission()` 判定为重复提交而直接返回，
    #   既不会重复扣款，也不需要在异常分支里重建 session 状态。
    #
    #   ★ 为什么需要它：业务守卫是「读-判断-写」模式，天生有竞态窗口；
    #     只靠应用层判断 + 事后唯一约束，会在「无订阅可锁」时不成立。
    #     行锁把竞态窗口直接关掉，唯一约束退化为兜底。
    #
    #   ⚠️ 锁只覆盖**当前用户自己那一行**，且事务内还包含一次网关调用
    #   （mock 瞬时完成；接真实网关若是同步 HTTP，需评估持锁时长，
    #   必要时改为「先建 pending 账单 → 释放锁 → 收 webhook」的两段式，
    #   见 core/billing/payment_gateway.py 顶部接入清单第 5 条）。
    # ★★ `.execution_options(populate_existing=True)` 不能省（P1-5 收尾修复 2026-09-15）
    #
    #   行锁只在**数据库**层面把并发请求串行化；但 SQLAlchemy 的 identity map 会把
    #   「本 session 里已经加载过的那份 Subscription」原样返回，**不使用锁后重读到
    #   的新值覆盖已加载属性**（除非显式 populate_existing）。
    #   而 `User.subscription` 是 `lazy="selectin"`（models.py:62）——
    #   即 `get_current_user` 查 User 时，已经把这条订阅行连同**旧值**装进了
    #   identity map。于是「串行化之后后到的请求会读到新状态」这条设计前提不成立。
    #
    #   实测（4 并发双击同一套餐）：
    #     · 语句确实阻塞串行了（阶梯等待 71 / 266 / 468 / 671ms，见
    #       .workbuddy/probes/project-audit-20260915/script-lock_probe.py）
    #     · 但 4 个请求全部读到加锁前的旧状态 ⇒ 算出**同一个**幂等键
    #       ⇒ 3 个撞 `invoices.idempotency_key` 唯一约束
    #       ⇒ 走到下面的 IntegrityError 分支（本该 200 + charged=False）
    #   ⇒ 判据：**门禁语句存在 ≠ 门禁在生效**。加锁查询必须同时要求 ORM 重新装载，
    #     否则锁保护的是数据库行，业务读到的仍是内存里的旧对象。
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sub = result.scalar_one_or_none()

    now = datetime.utcnow()

    # ★ 先把「日志/异常要用」的标量取出来（P1-5 收尾修复 2026-09-15）。
    #   理由见下面 IntegrityError 分支：`await db.rollback()` 会 expire 本 session
    #   内所有 ORM 对象，之后任何属性读取都会触发隐式懒加载，而纯 async 上下文里
    #   没有 greenlet ⇒ `MissingGreenlet: greenlet_spawn has not been called`。
    #   ★ 判据：凡是「rollback 之后还要用」的值，必须在 rollback 之前落成标量。
    _user_id = current_user.id
    _plan_id = plan.id

    # ---- 守卫：同套餐同周期重复提交 → 不扣款、不开票 ----
    if is_duplicate_submission(sub, plan.id, billing_cycle):
        return {
            "subscription": _serialize_subscription(sub),
            "client_secret": "",
            "charged": False,
            "already_subscribed": True,
            "message": "当前已在所选套餐的有效周期内，未重复扣款",
        }

    # ---- 先扣款（不可回滚的一步），成功后再改订阅 ----
    amount = plan_amount(plan, billing_cycle)
    # 幂等键基底 = 「本次变更的起点状态」，见 pricing.subscription_state_fingerprint
    idem_key = build_idempotency_key(
        current_user.id, plan.id, billing_cycle, subscription_state_fingerprint(sub)
    )
    gateway = get_gateway()
    try:
        charge = await gateway.charge(ChargeIntent(
            user_id=current_user.id,
            amount=amount,
            currency="CNY",
            description=f"{plan.display_name}{'年付' if billing_cycle == 'yearly' else '月付'}",
            billing_cycle=billing_cycle,
            plan=plan,
            idempotency_key=idem_key,
        ))
    except NotImplementedError as exc:
        # 配置里写了一个「已知但未接入」的真实网关（stripe/alipay/wechat）。
        # ★ 用 501 而不是 500：500 会被当成服务端 bug 去翻栈，
        #   501 直说「这个能力还没实现」，并把整改指引带在 detail 里。
        #   也**不能**降级成 mock 支付成功 —— 那是「用户白拿套餐」。
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc

    if not charge.success:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=charge.error or "支付失败，请重试",
        )

    # ---- 扣款成功：写订阅状态 + 落账单 ----
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
    if charge.invoice is not None:
        db.add(charge.invoice)

    try:
        await db.commit()
    except IntegrityError as exc:
        # ★ 兜底闸：只有「同一用户此前没有任何订阅」时才会走到这里。
        #   那时没有行可锁，两个并发请求都可能判定「不是重复提交」并各建一张单，
        #   于是 invoices.idempotency_key 的唯一约束兜住其中一个。
        #
        #   ⚠️ 只吞「idempotency_key 冲突」，其他完整性错误（外键、number 撞车）
        #   必须原样抛出，否则会把真 bug 伪装成「重复提交」静默吞掉。
        if "idempotency_key" not in str(getattr(exc, "orig", exc)):
            raise
        # ★★ 回滚后**立刻结束请求**，不再对这个 session 做任何 DB 操作。
        #   实测踩坑：回滚后继续 `db.execute(...)` 会在连接池 checkout 的
        #   pre-ping 阶段抛 `MissingGreenlet: greenlet_spawn has not been called`
        #   —— 顶层 greenlet 上下文已经随异常一起退出，而 pre-ping 是同步路径
        #   里的 `await_only`。同一个 `except IntegrityError` 分支里既回滚又读库，
        #   在 async SQLAlchemy 上是走不通的组合。
        #   所以这里不重建状态，直接 409 让前端刷新（此时前一个请求已提交成功，
        #   刷新后看到的订阅状态是正确的）。
        await db.rollback()
        # ★ 这里只能用**回滚前取好的标量**（_user_id / _plan_id），不能读 ORM 属性：
        #   rollback() 已经把 session 内所有对象 expire，此时读 `current_user.id`
        #   触发隐式懒加载 → 纯 async 上下文没有 greenlet ⇒ 抛
        #   `MissingGreenlet: greenlet_spawn has not been called`，
        #   本该 409「重复提交」的响应会变成 500 + 一串 SQLAlchemy 堆栈。
        #   ★ 另外 loguru 用 `{}` 占位：写成 `%s` 不报错，但会把字面量 `%s`
        #   打进日志并**丢掉全部参数**（本行原先就是错的）。
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
        "skipped_reason": charge.skipped_reason,
    }


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
                "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
                "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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

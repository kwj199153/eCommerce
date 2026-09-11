"""
计费与用量 API 路由

提供用量查询、套餐信息、订阅管理、账单与支付方式等接口。

契约说明：本路由的响应字段与前端 `frontend/src/api/billing.ts` 严格对齐。
  - 套餐 `id` 输出为字符串（`str(plan.id)`），前端按字符串比较做「当前套餐」高亮
  - 套餐补全 `price_yearly`（后端无该列，按「年付 = 月付 × 10」近似）、
    `limits` 嵌套对象、`features` 字符串数组（后端存 JSON 字符串，此处解析）
  - 订阅补全 `cancel_at_period_end`、`usage.ai_gen_*`（AIGC 复用 API 额度口径）
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth.dependencies import get_current_user, get_admin_user, require_auth_if_enabled
from core.billing.usage_tracker import UsageTracker, init_default_plans
from core.billing.payment_gateway import get_gateway, ChargeIntent
from modules.user_subscription.models import (
    User,
    Subscription,
    SubscriptionPlan,
    Invoice,
    PaymentMethod,
)


router = APIRouter(prefix="/billing", tags=["计费与用量"])


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

    # 后端无 price_yearly 列，按「年付 ≈ 月付 × 10」近似（与「年付省 17%」体验一致）
    price_yearly = round(plan.price_monthly * 10, 2)

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
    """
    plan_id = body.plan_id
    billing_cycle = body.billing_cycle
    if billing_cycle not in ("monthly", "yearly"):
        billing_cycle = "monthly"

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

    # 取或建订阅
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    sub = result.scalar_one_or_none()

    now = datetime.utcnow()
    if sub is None:
        # 首次订阅：新建
        sub = Subscription(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            plan_id=plan.id,
            status="active",
            cancel_at_period_end=False,
            current_period_start=now,
            current_period_end=None,  # 简化：不设到期（免费/试用）——年付设一年
        )
        db.add(sub)
    else:
        # 切套餐：更新 plan、重置周期、清除取消标记
        sub.plan_id = plan.id
        sub.status = "active"
        sub.cancel_at_period_end = False
        sub.current_period_start = now
        sub.current_period_end = None

    if billing_cycle == "yearly":
        sub.current_period_end = now + timedelta(days=365)
    else:
        sub.current_period_end = now + timedelta(days=30)

    sub.updated_at = now

    # 通过支付网关扣款（默认 mock 模拟成功；真实网关替换配置即可）
    amount = round(plan.price_monthly * 10, 2) if billing_cycle == "yearly" else plan.price_monthly
    gateway = get_gateway()
    result = await gateway.charge(ChargeIntent(
        user_id=current_user.id,
        amount=amount,
        currency="CNY",
        description=f"{plan.display_name}{'年付' if billing_cycle == 'yearly' else '月付'}",
        billing_cycle=billing_cycle,
        plan=plan,
    ))

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=result.error or "支付失败，请重试",
        )

    # 支付成功：落账单
    if result.invoice is not None:
        db.add(result.invoice)

    await db.commit()
    await db.refresh(sub)

    return {
        "subscription": _serialize_subscription(sub),
        # 前端 changePlan 返回里含 client_secret（Stripe 支付意图）。
        # mock 下无真实 secret，返回网关透传值（空串占位）。
        "client_secret": result.client_secret,
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

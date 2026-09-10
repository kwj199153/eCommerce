"""
计费与用量 API 路由

提供用量查询、套餐信息、配额检查等接口。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.auth.dependencies import get_current_user, get_admin_user
from core.billing.usage_tracker import UsageTracker, init_default_plans
from modules.user_subscription.models import User


router = APIRouter(prefix="/billing", tags=["计费与用量"])


@router.get("/usage")
async def get_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的使用量信息

    返回 API 调用次数、Agent 对话次数等使用情况。
    """
    usage_info = await UsageTracker.get_usage_info(db, current_user.id)
    return usage_info


@router.get("/plans")
async def list_plans(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有可用的订阅套餐列表

    用于前端展示套餐选择页面。

    说明：套餐列表属于公开信息（用户在登录/注册前即可查看定价），
    故不挂鉴权依赖。若后续套餐含敏感信息（如渠道折扣），再收紧。
    """
    from sqlalchemy import select
    from modules.user_subscription.models import SubscriptionPlan

    result = await db.execute(
        select(SubscriptionPlan).order_by(SubscriptionPlan.price_monthly)
    )
    plans = result.scalars().all()

    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "price_monthly": p.price_monthly,
                "api_calls_limit": p.api_calls_limit,
                "agent_chat_limit": p.agent_chat_limit,
                "max_shops": p.max_shops,
                "max_users": p.max_users,
                "features": p.features,
            }
            for p in plans
        ]
    }


@router.get("/subscription")
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的订阅详情

    包括当前套餐、到期时间、使用量等信息。
    """
    from sqlalchemy import select
    from modules.user_subscription.models import Subscription

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        return {"subscription": None}

    plan = subscription.plan
    return {
        "subscription": {
            "id": subscription.id,
            "status": subscription.status,
            "plan": {
                "id": plan.id,
                "name": plan.name,
                "display_name": plan.display_name,
                "price_monthly": plan.price_monthly,
            },
            "period": {
                "start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
                "end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            },
            "usage": {
                "api_calls_used": subscription.api_calls_used,
                "api_calls_remaining": max(0, plan.api_calls_limit - subscription.api_calls_used),
                "agent_chats_used": subscription.agent_chats_used,
                "agent_chats_remaining": max(0, plan.agent_chat_limit - subscription.agent_chats_used),
            },
        }
    }


# ====== 内部管理接口（仅管理员）=====

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

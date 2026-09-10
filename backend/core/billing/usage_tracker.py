"""
计费系统模块

提供 API 调用追踪、用量统计、限流、套餐检查等功能。
支持免费版/专业版/企业版的差异化限制。
"""

from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from core.database import get_db
from core.config import config
from modules.user_subscription.models import User, Subscription


# ====== 用量类型 ======

class UsageType:
    """用量类型常量"""
    API_CALL = "api_call"  # API 调用
    AGENT_CHAT = "agent_chat"  # Agent 对话
    AIGC_GENERATION = "aigc_generation"  # AIGC 生成（图片/视频）
    DATA_EXPORT = "data_export"  # 数据导出


# ====== 用量追踪器 ======

class UsageTracker:
    """
    用量追踪器

    追踪用户的各项资源使用情况，用于计费和限流。
    """

    @staticmethod
    async def record_usage(
        db: AsyncSession,
        user_id: str,
        usage_type: str,
        amount: int = 1,
    ) -> bool:
        """
        记录一次使用量

        Args:
            user_id: 用户 ID
            usage_type: 用量类型 (UsageType.*)
            amount: 使用数量（默认 1）

        Returns:
            True 记录成功，False 失败（如超出限额）
        """
        # 1. 查询用户订阅
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.is_active:
            return False

        # 2. 更新对应的使用量字段
        if usage_type == UsageType.API_CALL:
            new_used = subscription.api_calls_used + amount
            if new_used > subscription.plan.api_calls_limit:
                return False  # 超出限制
            subscription.api_calls_used = new_used

        elif usage_type == UsageType.AGENT_CHAT:
            new_used = subscription.agent_chats_used + amount
            if new_used > subscription.plan.agent_chat_limit:
                return False
            subscription.agent_chats_used = new_used

        elif usage_type == UsageType.AIGC_GENERATION:
            # AIGC 使用 API 调用额度
            new_used = subscription.api_calls_used + (amount * 10)  # AIGC 权重更高
            if new_used > subscription.plan.api_calls_limit:
                return False
            subscription.api_calls_used = new_used

        elif usage_type == UsageType.DATA_EXPORT:
            new_used = subscription.api_calls_used + (amount * 5)  # 导出权重中等
            if new_used > subscription.plan.api_calls_limit:
                return False
            subscription.api_calls_used = new_used

        else:
            return False

        subscription.updated_at = datetime.utcnow()
        await db.commit()

        return True

    @staticmethod
    async def get_usage_info(
        db: AsyncSession,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        获取用户当前用量信息

        Returns:
            包含已用量、剩余量、限制等信息的字典
        """
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription:
            return {
                "plan": None,
                "usage": {},
                "limits": {},
            }

        plan = subscription.plan

        return {
            "plan": {
                "name": plan.name,
                "display_name": plan.display_name,
                "price_monthly": plan.price_monthly,
            },
            "usage": {
                "api_calls": {
                    "used": subscription.api_calls_used,
                    "remaining": max(0, plan.api_calls_limit - subscription.api_calls_used),
                    "limit": plan.api_calls_limit,
                    "percentage": round(subscription.api_calls_used / plan.api_calls_limit * 100, 1) if plan.api_calls_limit > 0 else 0,
                },
                "agent_chats": {
                    "used": subscription.agent_chats_used,
                    "remaining": max(0, plan.agent_chat_limit - subscription.agent_chats_used),
                    "limit": plan.agent_chat_limit,
                    "percentage": round(subscription.agent_chats_used / plan.agent_chat_limit * 100, 1) if plan.agent_chat_limit > 0 else 0,
                },
            },
            "period": {
                "start": subscription.current_period_start.isoformat() if subscription.current_period_start else None,
                "end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            },
            "status": subscription.status,
        }

    @staticmethod
    async def check_quota(
        db: AsyncSession,
        user_id: str,
        usage_type: str,
        amount: int = 1,
    ) -> tuple[bool, str]:
        """
        检查用户是否有足够的配额

        Returns:
            (是否允许, 原因说明)
        """
        result = await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.is_active:
            return False, "订阅无效或已过期"

        plan = subscription.plan

        if usage_type == UsageType.API_CALL:
            if subscription.api_calls_used + amount > plan.api_calls_limit:
                remaining = max(0, plan.api_calls_limit - subscription.api_calls_used)
                return False, f"API 调用次数不足，剩余 {remaining} 次"

        elif usage_type == UsageType.AGENT_CHAT:
            if subscription.agent_chats_used + amount > plan.agent_chat_limit:
                remaining = max(0, plan.agent_chat_limit - subscription.agent_chats_used)
                return False, f"Agent 对话次数不足，剩余 {remaining} 次"

        return True, ""


# ====== FastAPI 依赖注入 ======

async def check_api_quota(
    request: Request,
    current_user: User = Depends(get_db),  # TODO: 替换为真实依赖
    db: AsyncSession = Depends(get_db),
):
    """
    API 配额检查依赖

    在需要消耗 API 额度的接口中使用：
        @router.get("/some-api")
        async def some_api(
            _=Depends(check_api_quota),
            ...
        ):
            ...
    """
    allowed, reason = await UsageTracker.check_quota(
        db=db,
        user_id=current_user.id,
        usage_type=UsageType.API_CALL,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=reason or "API 调用次数已达上限",
            headers={
                "X-RateLimit-Limit": "60",
                "X-RateLimit-Remaining": "0",
                "Retry-After": "86400",  # 下次重置时间（秒）
            },
        )

    # 记录使用量
    await UsageTracker.record_usage(db, current_user.id, UsageType.API_CALL)


async def check_agent_chat_quota(
    current_user: User = Depends(get_db),  # TODO: 替换为真实依赖
    db: AsyncSession = Depends(get_db),
):
    """
    Agent 对话配额检查依赖

    用于 Agent 对话接口的限流。
    """
    allowed, reason = await UsageTracker.check_quota(
        db=db,
        user_id=current_user.id,
        usage_type=UsageType.AGENT_CHAT,
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=reason or "Agent 对话次数已达上限",
        )

    # 记录使用量
    await UsageTracker.record_usage(db, current_user.id, UsageType.AGENT_CHAT)


# ====== 初始化默认套餐数据 ======

async def init_default_plans(db: AsyncSession):
    """
    初始化默认的订阅套餐数据

    应在首次部署时调用，插入 free / pro / enterprise 三种套餐。
    """
    from modules.user_subscription.models import SubscriptionPlan

    # 检查是否已有数据
    result = await db.execute(select(SubscriptionPlan).limit(1))
    existing = result.scalar_one_or_none()

    if existing:
        return  # 已初始化过

    # 插入默认套餐
    plans = [
        SubscriptionPlan(
            id=1,
            name="free",
            display_name="免费版",
            price_monthly=0,
            api_calls_limit=100,
            agent_chat_limit=50,
            max_shops=3,
            max_users=1,
            features='["基础选品分析", "Listing生成(3个/月)", "社区支持"]',
        ),
        SubscriptionPlan(
            id=2,
            name="pro",
            display_name="专业版",
            price_monthly=299,
            api_calls_limit=5000,
            agent_chat_limit=500,
            max_shops=10,
            max_users=5,
            features='["全功能选品分析", "竞品监控", "无限Listing生成", "广告分析", "AIGC素材(50张/月)", "优先支持"]',
        ),
        SubscriptionPlan(
            id=3,
            name="enterprise",
            display_name="企业版",
            price_monthly=999,
            api_calls_limit=50000,
            agent_chat_limit=5000,
            max_shops=50,
            max_users=20,
            features='["全部Pro功能", "多租户管理", "自定义Agent", "私有化部署", "专属客户成功经理", "SLA保障"]',
        ),
    ]

    for plan in plans:
        db.add(plan)

    await db.commit()
    print("✅ 默认订阅套餐初始化完成")

"""
店秘书「订阅查询工具」

为什么独立一个文件：
  secretary 的工具集里有 navigation_tools.open_drawer(settings)，当用户问
  「我订阅了什么套餐」时，LLM 在没有订阅查询能力时退而求其次选了它——但
  settings drawer 里根本没有订阅信息（订阅在独立 /subscription 路由页）。
  本文件给 secretary 注入「查订阅」能力，让 LLM 能直接答套餐内容，从根本上
  避免错误跳转。

设计要点：
  - 绕开 HTTP（避免演示模式 401），直接调 ORM service 层
  - 演示环境下取「当前唯一用户」的订阅作为代表（不绑具体 user_id）
  - 返回结构化 dict，让 LLM 用自然语言回复套餐详情
"""

from langchain_core.tools import StructuredTool

from core.database import get_db
from modules.user_subscription.models import Subscription, SubscriptionPlan
from sqlalchemy import select


async def _get_my_subscription_impl() -> dict:
    """查询当前用户的订阅套餐详情（演示模式：返回数据库中第一条订阅记录）。

    Returns:
        {
            "found": bool,
            "plan_name": str,        # e.g. "pro"
            "plan_display_name": str, # e.g. "Pro · 专业版"
            "status": str,           # active / trialing / cancelled ...
            "price_monthly": float,
            "period_start": str,     # ISO datetime
            "period_end": str | None,
            "cancel_at_period_end": bool,
            "features": list[str],   # 套餐特性摘要
            "api_calls_limit": int,
            "agent_chat_limit": int,
            "max_shops": int,
            "remaining_api_calls": int,
            "remaining_agent_chats": int,
        }
    """
    import json

    async for db in get_db():
        # 演示模式：取第一条订阅（实际生产应按当前用户过滤）
        # plan 已配 lazy="selectin"，无需显式 eager load
        stmt = (
            select(Subscription)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        sub = result.scalar_one_or_none()

        if sub is None or sub.plan is None:
            return {
                "found": False,
                "message": "当前账号尚未订阅任何套餐，可在设置 → 订阅管理中查看可选套餐。",
            }

        plan: SubscriptionPlan = sub.plan
        # features 是 Optional[str]（JSON 字符串），统一定义为 list[str]
        features: list[str] = []
        if plan.features:
            try:
                features = json.loads(plan.features)
            except (json.JSONDecodeError, TypeError):
                features = [str(plan.features)]

        return {
            "found": True,
            "plan_name": plan.name,
            "plan_display_name": plan.display_name,
            "status": sub.status,
            "price_monthly": float(plan.price_monthly or 0),
            "period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "cancel_at_period_end": bool(sub.cancel_at_period_end),
            "features": features,
            "api_calls_limit": plan.api_calls_limit,
            "agent_chat_limit": plan.agent_chat_limit,
            "max_shops": plan.max_shops,
            "remaining_api_calls": max(0, plan.api_calls_limit - sub.api_calls_used),
            "remaining_agent_chats": max(0, plan.agent_chat_limit - sub.agent_chats_used),
        }


get_my_subscription = StructuredTool.from_function(
    func=_get_my_subscription_impl,
    coroutine=_get_my_subscription_impl,
    name="get_my_subscription",
    description=(
        "查询当前账号的订阅套餐详情（套餐名、状态、价格、当前周期、特性列表）。"
        "用户问「我订阅了什么套餐 / 我的订阅 / 账单 / 续费日期」时**优先调用此工具**回答，"
        "**不要**用 open_drawer(settings) 应付——设置抽屉里没有订阅信息。"
    ),
)


subscription_tools = [get_my_subscription]
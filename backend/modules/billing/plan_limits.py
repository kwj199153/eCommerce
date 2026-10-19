"""套餐档位闸 —— `max_shops` / `max_users` 的**唯一**拦截实现（第 385 轮）。

==============================================================================
★ 缺陷形态（第三方商用审查 P0-5，本轮实测确认）
==============================================================================
`subscription_plans` 表里三个档位的 `max_shops` / `max_users` 是 3/1、10/5、50/20，
但全仓只有**两处读它们，且都是展示**：

    modules/billing/router.py:159-160      "shops_limit": plan.max_shops
    modules/secretary/subscription_tools.py:112   "max_shops": plan.max_shops

⇒ 免费版能建 50 家店、能加 20 个人；企业版（¥999/月）与免费版在
   「能开多少店、能加多少人」上**完全一样**。差的 ¥999 买到的只有调用次数，
   **升级理由不足**。

对比：`api_calls` / `agent_chat` 是真上闸的（`main.py:502 API_QUOTA`，
22 处消费）。所以这不是"没做配额"，是**做了一半**。

==============================================================================
★ 三条设计决定（都不是随手定的）
==============================================================================
① **按「账户所有者」的订阅判档**，不按操作者。
   套餐是"这个团队买了什么"；团队里一个 member 建店用的是团队的额度，
   而不是他自己的。凭据链：`Account.owner_user_id -> Subscription(user_id) -> Plan`。

② **没有生效订阅 ⇒ 按免费版上限**（不是放行）。
   「取不到就放行」会把闸变成摆设（本仓铁律：取不到禁静默退化）。
   但也不能硬拒 —— 注册流程会建默认订阅，缺行属数据异常，按最严格档位处理
   最安全。数值与 `init_default_plans()` 的 free 档**有测试对账**，防两处漂移。

③ **不加行锁，接受一个有界的 TOCTOU 窗口**（试过加锁，会自死锁）。
   `create_store` 的持久化走的是**另一个** session（`_upsert_store_db`），
   它与本模块的 `db` 事务争同一行 `accounts` 的锁 ⇒ 外键检查阻塞 ⇒
   同一请求内自死锁（实测：`test_stores.py` 整组挂死）。
   ⇒ 保留裸 SELECT：两个并发建店可能双双通过，超出上限**最多 = 并发数**，
     下一次请求读到真实行数就会拒绝。彻底解法是收编那个跨 session 写，
     属独立改造。详见 `_account_owner()` 的 docstring。

==============================================================================
★ 接入点（新增拦截必须同时改这两处，否则只挡住一半）
==============================================================================
    modules/stores/router.py :: create_store        —— 建店（max_shops）
    core/auth/accounts_router.py :: invite_member   —— 加成员（max_users）

★ 演示身份（`demo-token` 且 `DEMO_MODE=true`）**不受档位限制**：演示账号名下
  本来就有 4 家店，按免费版 3 家算会让"再建一家看看"直接撞墙，而演示场景
  要的正是"随便试"。判据复用唯一真源 `core.auth.demo_identity.is_demo_request`
  —— 与 API 配额豁免同一口径，不另写一份。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PlanLimits:
    plan_name: str
    plan_display: str
    max_shops: int
    max_users: int


#: 没有任何生效订阅时的兜底：按**免费版**上限（fail-closed）。
#: ★ 数值必须与 `init_default_plans()` 的 free 档一致 ——
#:   `tests/test_plan_limits.py::test_free_fallback_matches_seeded_plan` 对账。
FREE_FALLBACK = PlanLimits(plan_name="free", plan_display="免费版", max_shops=3, max_users=1)

#: 可拦截的维度
METRIC_SHOPS = "max_shops"
METRIC_USERS = "max_users"

_METRIC_LABEL = {
    METRIC_SHOPS: "店铺",
    METRIC_USERS: "团队成员",
}


async def get_plan_limits(db: AsyncSession, user_id: str) -> PlanLimits:
    """取该用户**生效订阅**的档位上限；没有订阅 / 已失效 ⇒ `FREE_FALLBACK`。"""
    # ★ 延迟导入：`billing` 是 KERNEL 层，本模块也在 KERNEL 层，顶层 import
    #   本来合法；但 `modules.billing.models` 会拉进整个 ORM 域，而本模块被
    #   `core/auth/accounts_router.py` 在函数内调用 —— 保持同一种延迟形态，
    #   避免"从 core 一侧 import 本模块"时意外建立 import 期边。
    from modules.billing.models import Subscription

    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    ).scalar_one_or_none()
    if sub is None or not sub.is_active:
        return FREE_FALLBACK

    plan = sub.plan
    if plan is None:  # 外键保护下不该发生，但缺 plan 时按最严格档位处理
        return FREE_FALLBACK

    return PlanLimits(
        plan_name=plan.name,
        plan_display=plan.display_name or plan.name,
        max_shops=int(plan.max_shops),
        max_users=int(plan.max_users),
    )


async def count_account_shops(db: AsyncSession, account_id: str) -> int:
    from core.stores.models import StoreRecord

    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(StoreRecord)
                .where(StoreRecord.account_id == account_id)
            )
        ).scalar_one()
    )


async def count_account_seats(db: AsyncSession, account_id: str) -> int:
    """已占席位 = 1（所有者）+ 成员数。

    ★ 为什么把 owner 算进去：`max_users=1` 的产品含义是"免费版只有你自己"。
      只数 `account_members` 的话免费版会变成"1 个 owner + 1 个成员"= 2 席位，
      与定价页说的"1 人"对不上。
    """
    from core.identity.account_models import AccountMember

    members = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AccountMember)
                .where(AccountMember.account_id == account_id)
            )
        ).scalar_one()
    )
    return members + 1


async def _account_owner(db: AsyncSession, account_id: str) -> Optional[str]:
    """取账户所有者（不存在 ⇒ None）。

    ★★★ 为什么这里**不**用 `with_for_update()`（试过，会自死锁）
    ------------------------------------------------------------------
    加上行锁后 `test_stores.py` 直接挂死。根因不是本模块，是既有的**双 session**
    写入路径：`create_store` 的 `_upsert_store_db()` 用的是**另一个** session
    （`async_session_factory`），它插 `stores_store` 时 PG 要对被引用的
    `accounts` 行加 `FOR KEY SHARE` 做外键检查 ——
    而我方 `db` 事务正持有同一行的 `FOR UPDATE` ⇒ 外键检查阻塞，
    而 `db` 事务要等本次请求走完才结束 ⇒ **同一请求内自死锁**。

    ⇒ 代价是留下一个**已知的 TOCTOU 窗口**：两个并发建店都读到「已有 2 家
      （上限 3）」⇒ 都通过 ⇒ 最终 4 家。后果是**有界的**（超限幅度 = 并发数，
      下一次请求读真实行数就会拒绝），不是"永久失控"。
      ★ 彻底解法是把 `_upsert_store_db` 收进同一 session（历史遗留的跨 session
        写），那是一次独立的改造，不该顺手塞进档位闸里。
    """
    from core.identity.account_models import Account

    return (
        await db.execute(select(Account.owner_user_id).where(Account.id == account_id))
    ).scalar_one_or_none()


def plan_limit_error(
    *, metric: str, limit: PlanLimits, current: int, account_id: str
) -> HTTPException:
    """402 Payment Required —— 结构化 detail，前端据此显示升级引导。"""
    label = _METRIC_LABEL.get(metric, "资源")
    max_value = getattr(limit, metric)
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "PLAN_LIMIT_EXCEEDED",
            "metric": metric,
            "current": current,
            "limit": max_value,
            "plan": limit.plan_name,
            "plan_display": limit.plan_display,
            "account_id": account_id,
            "upgrade_url": "/settings/subscription",
            "message": (
                f"当前套餐（{limit.plan_display}）最多 {max_value} 个{label}，"
                f"已用 {current} 个。升级套餐后可继续添加。"
            ),
        },
    )


async def enforce_account_limit(db: AsyncSession, *, account_id: str, metric: str) -> PlanLimits:
    """检查并（通过时）不消耗额度 —— 额度由真实行数推导，不另记计数器。

    Returns:
        当前档位（调用方一般不需要，测试与日志用）。

    Raises:
        HTTPException 402 —— 已达上限。
    """
    owner_user_id = await _account_owner(db, account_id)
    if owner_user_id is None:
        # 账户不存在：交给调用方原本的 404 路径，这里不抢它的语义
        return FREE_FALLBACK

    limit = await get_plan_limits(db, owner_user_id)
    max_value = int(getattr(limit, metric))

    current = (
        await count_account_shops(db, account_id)
        if metric == METRIC_SHOPS
        else await count_account_seats(db, account_id)
    )

    # ★ `>=` 而不是 `>`：本次动作**将要**新增一条，已用 == 上限时应当拒绝。
    if current >= max_value:
        raise plan_limit_error(
            metric=metric, limit=limit, current=current, account_id=account_id
        )
    return limit


__all__ = [
    "FREE_FALLBACK",
    "METRIC_SHOPS",
    "METRIC_USERS",
    "PlanLimits",
    "count_account_seats",
    "count_account_shops",
    "enforce_account_limit",
    "get_plan_limits",
    "plan_limit_error",
]

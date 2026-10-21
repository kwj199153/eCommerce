"""429 的**两种业务原因**必须可区分（第 387 轮 · 网站管理员 P1-1）

==============================================================================
为什么这条需求不是"文案美化"
==============================================================================
改造前，后端有四处在 429，其中两处说"额度"：

| 位置 | 订阅失效时说的话 | 额度用尽时说的话 |
|---|---|---|
| `check_quota`（前置检查） | 「订阅无效或已过期」 | 「API 调用次数不足，剩余 N 次」 |
| `record_usage`（原子扣减） | **「API 调用次数已达上限」** ← 洗白 | 同一句 |

第二行才是要害：`record_usage` 返回 `False` 有**四种**成因（无订阅 / 订阅失效 /
超限 / 计量类型未知），全被压成同一个布尔值 ⇒ 调用方只能编一句话。
于是「订阅过期」在界面上长得和「额度用完」一模一样：

  · 用户去充值/升级 —— 没用（订阅失效时升档也进不去）；
  · 运维去查用量曲线 —— 没有异常（用量可能才 3 次）；
  · 支持同学按"提额度"处理 —— 越处理越离谱。

⇒ 本轮的判据：**两种原因的 `code` 必须不同，且给客户端的"下一步"必须不同**。
   如果哪天有人把它们又合成一句，本文件必须红。

★ 口径：断言落在 `detail.code` / `detail.action` / `Retry-After` 上，
  不落在中文文案上 —— 文案会改，语义不该改。
"""

from sqlalchemy import select


async def _sub_of(user_id: str):
    """取出该用例用户的订阅行（夹具已保证存在）。"""
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        return (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one()


async def _set_sub(user_id: str, **fields):
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one()
        for k, v in fields.items():
            setattr(sub, k, v)
        await db.commit()


# ============================================================================
# 1. 额度用尽 ⇒ QUOTA_EXCEEDED（升级 / 等重置**有用**）
# ============================================================================

async def test_exhausted_quota_is_quota_exceeded(
    client, auth_on, user, auth_headers, fake_llm
):
    sub = await _sub_of(user["user_id"])
    limit = sub.plan.agent_chat_limit
    await _set_sub(user["user_id"], agent_chats_used=limit)

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 429, f"应 429，实际 {r.status_code} {r.text[:300]}"

    detail = r.json().get("detail")
    assert isinstance(detail, dict), (
        "detail 必须是结构化对象（字符串无法承载 code，客户端只能猜）："
        f"{detail!r}"
    )
    assert detail.get("code") == "QUOTA_EXCEEDED", detail
    assert detail.get("action") == "upgrade_plan", detail
    # 数量必须真实带出，否则前端只能写"额度不足"这种没有信息量的话
    assert detail.get("limit") == limit, detail
    assert detail.get("used") == limit, detail
    assert detail.get("remaining") == 0, detail
    # 额度会在下个周期重置 ⇒ 给 Retry-After 是对的
    # ★ httpx 的 header 名是小写的；用 `.get()`（大小写不敏感）而不是集合比对
    assert r.headers.get("Retry-After") is not None, dict(r.headers)


# ============================================================================
# 2. 订阅失效 ⇒ SUBSCRIPTION_INACTIVE（与用量**无关**，重试/等待都没用）
# ============================================================================

async def test_inactive_subscription_is_not_reported_as_quota(
    client, auth_on, user, auth_headers, fake_llm
):
    # ★ 关键夹具设计：把用量**留得很低**（3 次），只让订阅失效。
    #   如果实现把两种情况混为一谈，这个用例会以"额度用完"的形式通过
    #   所有"是不是 429"的断言 —— 所以下面必须断言 code 与 message。
    await _set_sub(user["user_id"], status="expired", agent_chats_used=3)

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 429, f"应 429，实际 {r.status_code} {r.text[:300]}"

    detail = r.json().get("detail")
    assert isinstance(detail, dict), f"detail 必须是结构化对象：{detail!r}"
    assert detail.get("code") == "SUBSCRIPTION_INACTIVE", (
        "订阅失效被报成了别的 code ⇒ 界面会显示「额度用完」，"
        f"而归因方向完全相反：{detail}"
    )
    assert detail.get("action") == "renew_subscription", detail
    # 文案必须显式说明「与调用次数无关」——否则用户第一反应永远是"我才调了几次"
    assert "与调用次数无关" in (detail.get("message") or ""), detail
    # ★ 订阅失效**不该**给 Retry-After：那等于暗示"等一会儿就好"
    assert r.headers.get("Retry-After") is None, (
        "订阅失效给了 Retry-After ⇒ 客户端会按提示退避重试，"
        f"而重试永远不可能成功：{dict(r.headers)}"
    )


# ============================================================================
# 3. 原子扣减这一环也必须带原因（改造前它**恒**说"已达上限"）
# ============================================================================

async def test_record_usage_ex_reports_inactive_not_limit(user):
    """`record_usage` 返回 False 的四种成因，这里锁住最关键的一种。"""
    from core.database import get_async_session
    from core.metering.usage_tracker import (
        QUOTA_CODE_SUBSCRIPTION_INACTIVE,
        UsageTracker,
        UsageType,
    )

    await _set_sub(user["user_id"], status="expired", agent_chats_used=0)

    async with get_async_session() as db:
        denial = await UsageTracker.record_usage_ex(
            db, user["user_id"], UsageType.AGENT_CHAT
        )
    assert denial is not None, "订阅已失效，扣减不该成功"
    assert denial.code == QUOTA_CODE_SUBSCRIPTION_INACTIVE, (
        f"原子扣减把「订阅失效」报成了 {denial.code} —— "
        "这正是本轮要修的那一处洗白"
    )


async def test_record_usage_ex_reports_limit_with_numbers(user):
    from core.database import get_async_session
    from core.metering.usage_tracker import (
        QUOTA_CODE_EXCEEDED,
        UsageTracker,
        UsageType,
    )

    sub = await _sub_of(user["user_id"])
    await _set_sub(user["user_id"], status="active", agent_chats_used=sub.plan.agent_chat_limit)

    async with get_async_session() as db:
        denial = await UsageTracker.record_usage_ex(db, user["user_id"], UsageType.AGENT_CHAT)
    assert denial is not None
    assert denial.code == QUOTA_CODE_EXCEEDED
    assert denial.limit == sub.plan.agent_chat_limit
    assert denial.remaining == 0


async def test_unknown_usage_type_is_not_blamed_on_user(user):
    """计量类型未知是**服务端 bug**，不能回 429 让用户以为是自己用超了。"""
    from core.database import get_async_session
    from core.metering.usage_tracker import (
        QUOTA_CODE_USAGE_UNKNOWN,
        UsageTracker,
    )

    await _set_sub(user["user_id"], status="active")
    async with get_async_session() as db:
        denial = await UsageTracker.record_usage_ex(db, user["user_id"], "not_a_real_type")
    assert denial is not None
    assert denial.code == QUOTA_CODE_USAGE_UNKNOWN, (
        f"未知计量类型被报成了 {denial.code}（会被当成用户超额：429）"
    )


# ============================================================================
# 4. 兼容壳不许改变语义（历史调用点用的是 bool）
# ============================================================================

async def test_bool_shells_keep_their_contract(user):
    from core.database import get_async_session
    from core.metering.usage_tracker import UsageTracker, UsageType

    # 订阅失效 ⇒ check_quota 允许吗？不允许；原因里必须能看出是订阅问题
    await _set_sub(user["user_id"], status="expired", agent_chats_used=0)
    async with get_async_session() as db:
        allowed, reason = await UsageTracker.check_quota(
            db, user["user_id"], UsageType.AGENT_CHAT
        )
    assert allowed is False
    assert "订阅" in reason, f"原因说明丢了关键信息：{reason!r}"

    # 恢复订阅后必须放行（否则兼容壳把所有人都拦了也能"通过"上一条）
    await _set_sub(user["user_id"], status="active", agent_chats_used=0)
    async with get_async_session() as db:
        allowed, reason = await UsageTracker.check_quota(
            db, user["user_id"], UsageType.AGENT_CHAT
        )
        assert allowed is True, f"恢复订阅后仍被拦：{reason!r}"
        assert await UsageTracker.record_usage(
            db, user["user_id"], UsageType.AGENT_CHAT
        ) is True

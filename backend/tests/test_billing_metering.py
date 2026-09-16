"""
计费 / LLM 成本计量回归测试

覆盖：
1. LLM 计量器按请求累积 token / 成本
2. Agent 对话计入 agent_chats_used
3. LLM 真实消耗落库到 subscriptions.llm_tokens_used / llm_cost_used
4. 超额时返回 429
5. /billing/usage 能查到 LLM 消耗
6. 并发下用量累加必须**原子**（不许丢更新），见文件末尾 P1-6 小节
"""

import asyncio

import pytest
from sqlalchemy import select

from core.metering.llm_meter import reset_meter, snapshot, record_llm_usage


# ====== 计量器纯逻辑 ======

def test_meter_accumulates():
    reset_meter()
    record_llm_usage(input_tokens=100, output_tokens=200, cost=0.01, model="qwen-max")
    record_llm_usage(input_tokens=50, output_tokens=50, cost=0.002, model="qwen-plus")

    s = snapshot()
    assert s.calls == 2
    assert s.input_tokens == 150
    assert s.output_tokens == 250
    assert s.total_tokens == 400
    assert abs(s.cost - 0.012) < 1e-9
    assert s.models == {"qwen-max": 1, "qwen-plus": 1}


def test_meter_noop_without_reset():
    """未开启计量时静默忽略，不报错"""
    from core.metering import llm_meter

    token = llm_meter._meter_var.set(None)
    try:
        record_llm_usage(input_tokens=10, output_tokens=10, cost=1.0)
        assert snapshot().calls == 0
    finally:
        llm_meter._meter_var.reset(token)


# ====== 端到端：计次 + 落库 ======

async def test_agent_chat_counted_and_llm_cost_persisted(
    client, auth_on, user, auth_headers, fake_llm
):
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        before = (sub.agent_chats_used, sub.llm_tokens_used, sub.llm_cost_used)

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        assert sub.agent_chats_used == before[0] + 1, "对话次数未计量"
        assert sub.llm_tokens_used > before[1], "LLM token 未落库"
        assert sub.llm_cost_used > before[2], "LLM 成本未落库"

    # 账单接口应能看到 LLM 消耗
    ru = await client.get("/api/v1/billing/usage", headers=auth_headers)
    assert ru.status_code == 200, ru.text
    usage = ru.json().get("data", ru.json()).get("usage", {})
    assert usage["llm"]["total_tokens"] > 0
    assert usage["llm"]["cost"] > 0


async def test_quota_exceeded_returns_429(client, auth_on, user, auth_headers, fake_llm):
    """把已用次数顶到上限后，应返回 429"""
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        sub.agent_chats_used = sub.plan.agent_chat_limit  # 顶满
        await db.commit()

    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 429, f"应 429，实际 {r.status_code} {r.text[:200]}"


async def test_failed_request_not_charged(client, auth_on, user, auth_headers):
    """请求体非法导致 422 时不应计费"""
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        before = sub.agent_chats_used

    r = await client.post("/api/v1/listing/chat", json={"bad": "payload"}, headers=auth_headers)
    assert r.status_code == 422

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        assert sub.agent_chats_used == before, "失败请求不应计入额度"


async def test_demo_mode_does_not_charge(client, auth_off):
    """演示模式下不计量"""
    r = await client.post("/api/v1/listing/chat", json={"message": "生成标题"})
    assert r.status_code == 200


async def test_stream_endpoint_counted_after_response(
    client, auth_on, user, auth_headers, fake_llm
):
    """
    SSE 流式端点同样应计数。

    结算挂在 BackgroundTasks 上：ASGI 响应（含流式 body）发送完成后才执行，
    因此断言时后台任务已完成。
    """
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        before = sub.agent_chats_used

    r = await client.post(
        "/api/v1/listing/chat/stream",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers.get("content-type", "")
    assert "done" in r.text, "流式响应应正常结束"

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user["user_id"])
        )).scalar_one()
        assert sub.agent_chats_used == before + 1, "流式端点未计数"


# ====== 并发安全：用量累加必须原子（★ P1-6 / 2026-09-16）======
#
# 背景：record_usage / record_llm_consumption 都是「读-改-写」。
#   修复前实测：8 并发各 +1，最终只累加到 2（丢 6 次）；
#   LLM token 同理，8 并发各 +10 只记到 20（丢 60）。
#   ⇒ 后果是配额可被小幅突破、平台少记 LLM 消耗（少收钱）。
#
# 修复：查询加 `.with_for_update()` + `.execution_options(populate_existing=True)`。
#   两者**缺一不可**，反向注入实测（.workbuddy/probes/project-audit-20260915/
#   r77d-reverse.txt）：
#     · 只去掉 populate_existing（保留行锁）→ 本用例红（丢 6/8）
#     · 只去掉 with_for_update（保留 populate_existing）→ 本用例红（丢 6/8）
#
# ★★ 用例设计的关键（两次假绿换来的，改这里前务必读完）：
#   必须复刻真实请求路径 —— `check_api_quota` 先经 `get_current_user` 取 User，
#   而 `User.subscription` 是 `lazy="selectin"`（models.py:62）⇒ 订阅行在此时
#   就进了本 session 的 identity map，record_usage 随后用**同一个 session**查订阅。
#   复刻时两个细节缺一不可：
#     ① 消费 Result（`.scalar_one()`）—— 不消费则 ORM 根本不构造对象；
#     ② **保留强引用**（赋值给变量）—— identity map 存的是**弱引用**，
#        不赋值时对象会被 GC，map 又空了。
#   两者任缺其一，identity map 都是空的 ⇒ 用例退化成「本 session 首次加载订阅」
#   ⇒ 锁后必然读到新值 ⇒ 去掉 populate_existing 也照样绿（**假绿**）。
#   实测依据：r77e-forupdate-semantics.txt / r77g-identity.txt。

_N_CONCURRENT = 8


async def _usage_snapshot(user_id: str) -> tuple:
    """读取 (api_calls_used, llm_tokens_used, llm_cost_used)"""
    from core.database import get_async_session
    from modules.billing.models import Subscription

    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )).scalar_one()
        return (sub.api_calls_used, sub.llm_tokens_used, float(sub.llm_cost_used))


async def _warm(db, user_id: str):
    """加载 User（复刻 `get_current_user`），使订阅行进 identity map。"""
    from core.identity.models import User

    _user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    assert _user.subscription is not None, "前提不成立：User 未加载出订阅"
    return _user


async def _deduct_with_warm_map(db, user_id: str, *, tokens: int = 0, cost: float = 0.0):
    """
    在「identity map 已装订阅行」的前提下执行一次扣减 —— 与真实请求同形。

    ★★★ 为什么把「加载 User」与「扣减」封进同一个函数（三次假绿换来的）：
      SQLAlchemy 的 identity map 存的是**弱引用**。下面任何一种写法都会让
      identity map 变空，于是扣减退化为「本 session 首次加载订阅」，
      锁后必然读到新值 —— **去掉 populate_existing 也照样绿（假绿）**：
        · `await db.execute(select(User)...)`            # 连 Result 都没消费
        · `(await db.execute(...)).scalar_one()`         # 消费了但没赋值
        · `await _warm(db, uid)`                         # helper 返回了但调用方丢弃
      实测三连（.workbuddy/probes/project-audit-20260915/）：
        ① r77g-identity.txt   identity map 长度 = 0（前两种写法）
        ② r77d-reverse.txt    探针 C 组持有引用 → 去掉 populate_existing 时**红**
        ③ r77i-gate-reverse.txt 正式用例调用方丢弃引用 → 去掉时**假绿**
      所以这里不让调用方接触引用：`_user` 在本函数栈帧内存活到扣减结束。
    """
    from core.metering.usage_tracker import UsageTracker, UsageType

    _user = await _warm(db, user_id)          # noqa: F841 —— 强引用必须存活到扣减结束
    if tokens or cost:
        return await UsageTracker.record_llm_consumption(
            db, user_id, tokens=tokens, cost=cost)
    return await UsageTracker.record_usage(db, user_id, UsageType.API_CALL)


async def test_record_usage_concurrent_accumulation_is_exact(user):
    """8 并发各记 1 次 API 调用 ⇒ api_calls_used 必须精确 +8。"""
    from core.database import get_async_session

    uid = user["user_id"]
    before_api, _, _ = await _usage_snapshot(uid)

    async def one():
        async with get_async_session() as db:
            return await _deduct_with_warm_map(db, uid)

    results = await asyncio.gather(*[one() for _ in range(_N_CONCURRENT)])
    assert all(results), f"并发记数出现失败：{results}"

    after_api, _, _ = await _usage_snapshot(uid)
    gained = after_api - before_api
    assert gained == _N_CONCURRENT, (
        f"{_N_CONCURRENT} 并发只累加了 {gained} 次（丢更新 {_N_CONCURRENT - gained} 次）"
        " —— 检查 record_usage 是否**同时**具备 with_for_update 与 populate_existing"
    )


async def test_record_llm_consumption_concurrent_accumulation_is_exact(user):
    """8 并发各记 10 token / ¥0.01 ⇒ token 精确 +80、成本 +0.08。"""
    from core.database import get_async_session

    uid = user["user_id"]
    _, before_tok, before_cost = await _usage_snapshot(uid)
    per_tokens, per_cost = 10, 0.01

    async def one():
        async with get_async_session() as db:
            return await _deduct_with_warm_map(
                db, uid, tokens=per_tokens, cost=per_cost)

    results = await asyncio.gather(*[one() for _ in range(_N_CONCURRENT)])
    assert all(results), f"并发记 LLM 消耗出现失败：{results}"

    _, after_tok, after_cost = await _usage_snapshot(uid)
    assert after_tok - before_tok == per_tokens * _N_CONCURRENT, (
        f"token 只累加 {after_tok - before_tok}，期望 {per_tokens * _N_CONCURRENT}"
        " —— record_llm_consumption 同样需要行锁 + populate_existing"
    )
    assert abs((after_cost - before_cost) - per_cost * _N_CONCURRENT) < 1e-9, (
        f"成本只累加 {after_cost - before_cost:.6f}，期望 {per_cost * _N_CONCURRENT:.2f}"
    )


async def test_api_quota_rejects_when_atomic_deduct_fails(
    user, auth_on, monkeypatch
):
    """
    前置检查通过、但原子扣减失败时，必须 429（★ P1-6：配额门禁的最后一环）。

    `check_quota` 与 `record_usage` 之间天然存在竞态窗口 —— 并发下两个请求
    都可能通过前置检查。真正决定「这一笔算不算得进去」的是 record_usage 的
    **原子扣减**。原写法 `await UsageTracker.record_usage(...)` 丢弃了返回值
    ⇒ 超限请求被**放行且不计数**（形式上挂了三层依赖，实际仍可越过限额）。

    本用例把这个窗口显式造出来：额度打满 + 前置检查打桩成「恒放行」，
    于是扣减必然失败。若实现回读返回值 ⇒ 429；若忽略 ⇒ 不会抛错。
    """
    from fastapi import HTTPException
    from starlette.requests import Request

    from core.metering import usage_tracker as ut
    from core.database import get_async_session
    from modules.billing.models import Subscription

    uid = user["user_id"]

    # 额度打满：后续任何一次扣减都必然失败
    async with get_async_session() as db:
        sub = (await db.execute(
            select(Subscription).where(Subscription.user_id == uid)
        )).scalar_one()
        sub.api_calls_used = sub.plan.api_calls_limit
        await db.commit()

    async def _always_allow(db, user_id, usage_type, amount=1):
        return True, ""

    monkeypatch.setattr(ut.UsageTracker, "check_quota", _always_allow)

    req = Request({
        "type": "http", "method": "GET", "path": "/probe",
        "headers": [(b"authorization", ("Bearer " + user["token"]).encode())],
    })

    async with get_async_session() as db:
        with pytest.raises(HTTPException) as ei:
            await ut.check_api_quota(request=req, db=db)
    assert ei.value.status_code == 429, (
        f"原子扣减失败时应 429，实际 {ei.value.status_code} —— "
        "record_usage 的返回值被丢弃了"
    )


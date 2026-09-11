"""
计费 / LLM 成本计量回归测试

覆盖：
1. LLM 计量器按请求累积 token / 成本
2. Agent 对话计入 agent_chats_used
3. LLM 真实消耗落库到 subscriptions.llm_tokens_used / llm_cost_used
4. 超额时返回 429
5. /billing/usage 能查到 LLM 消耗
"""

import pytest
from sqlalchemy import select

from core.billing.llm_meter import reset_meter, snapshot, record_llm_usage


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
    from core.billing import llm_meter

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
    from modules.user_subscription.models import Subscription

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
    from modules.user_subscription.models import Subscription

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
    from modules.user_subscription.models import Subscription

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
    from modules.user_subscription.models import Subscription

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

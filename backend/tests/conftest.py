"""
pytest 公共夹具

约定：
- 所有测试针对真实本地 PostgreSQL（tests 会创建并清理自己的临时用户）
- 需要鉴权的用例用 `auth_on` 夹具打开生产模式开关
- 不发起真实 LLM 请求：涉及 LLM 的用例统一 monkeypatch 客户端
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from core.config import config


# ====== 鉴权开关 ======

@pytest.fixture
def auth_on():
    """打开生产模式鉴权（要求 Bearer Token）"""
    prev = config.auth_required
    config.auth_required = True
    yield
    config.auth_required = prev


@pytest.fixture
def auth_off():
    """演示模式（匿名放行）"""
    prev = config.auth_required
    config.auth_required = False
    yield
    config.auth_required = prev


# ====== HTTP 客户端 ======

@pytest_asyncio.fixture
async def client():
    """基于 ASGI 的内存 HTTP 客户端（不经过网络）"""
    from main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ====== 临时用户（含订阅） ======

@pytest_asyncio.fixture
async def user(client):
    """
    注册一个临时用户并返回其凭据。

    /register 会自动创建默认订阅，因此返回对象里带 subscription 信息。
    测试结束后删除该用户及其订阅。
    """
    email = f"pytest-{uuid.uuid4().hex[:10]}@example.com"
    password = "pytest123456"

    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "pytest user"},
    )
    assert r.status_code in (200, 201), f"注册失败: {r.status_code} {r.text}"

    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, f"登录失败: {lr.status_code} {lr.text}"
    token = lr.json()["access_token"]

    # 查 user_id / subscription_id 供 DB 断言与清理
    from sqlalchemy import select, text
    from core.database import get_async_session
    from modules.user_subscription.models import User, Subscription

    async with get_async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == u.id))
        ).scalar_one_or_none()
        payload = {
            "email": email,
            "password": password,
            "token": token,
            "user_id": u.id,
            "subscription_id": sub.id if sub else None,
        }

    yield payload

    async with get_async_session() as db:
        await db.execute(
            text("DELETE FROM invoices WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(
            text("DELETE FROM payment_methods WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(
            text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": payload["user_id"]})
        await db.commit()


@pytest.fixture
def auth_headers(user):
    """带 Bearer Token 的请求头"""
    return {"Authorization": f"Bearer {user['token']}"}


# ====== LLM 打桩 ======

@pytest.fixture
def fake_llm(monkeypatch):
    """
    把 DashScopeLLM 的 chat / chat_stream 换成固定桩，避免真实调用与花费。

    仍会走 `_update_stats` / 计量钩子，因此能覆盖「LLM 消耗 → 计费」链路。
    """
    from ai_infra.llm import dashscope_client as dc

    def _make_response(input_tokens=120, output_tokens=80, cost=0.0036):
        return dc.LLMResponse(
            content="这是一段模拟的 LLM 回答。",
            model="qwen-max",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost,
            latency_ms=5,
            finish_reason="stop",
            raw_response={},
        )

    async def fake_chat(self, messages, system_prompt=None, **kwargs):
        resp = _make_response()
        self._update_stats(resp)
        return resp

    async def fake_chat_stream(self, messages, system_prompt=None, **kwargs):
        for chunk in ["这是", "一段", "模拟的", "流式回答。"]:
            yield chunk
        dc.record_llm_usage(input_tokens=120, output_tokens=80, cost=0.0036, model="qwen-max")

    monkeypatch.setattr(dc.DashScopeLLM, "chat", fake_chat)
    monkeypatch.setattr(dc.DashScopeLLM, "chat_stream", fake_chat_stream)
    return {"response": _make_response}

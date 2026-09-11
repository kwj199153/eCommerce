"""
鉴权 & 多租户隔离回归测试

覆盖此前几轮修复的闭环：
1. 业务接口在演示模式放行、生产模式要求 Bearer Token
2. 租户上下文（ContextVar）并发隔离
3. 店铺归属校验（跨用户访问 403）
4. 租户中间件已注册
"""

import asyncio

import pytest


# ====== 鉴权开关 ======

async def test_health_is_open(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_business_endpoint_401_without_token(client, auth_on):
    r = await client.post("/api/v1/listing/chat", json={"message": "优化标题"})
    assert r.status_code == 401, r.text


async def test_business_endpoint_ok_with_token(client, auth_on, user, auth_headers):
    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


async def test_demo_mode_allows_anonymous(client, auth_off):
    r = await client.post("/api/v1/listing/chat", json={"message": "生成标题"})
    assert r.status_code == 200, r.text


# ====== 租户上下文隔离（不依赖 DB） ======

async def test_tenant_context_concurrent_isolation():
    """并发 Task 各写各的租户，互不污染"""
    from core.tenant.middleware import tenant_context, get_tenant_context

    async def worker(name: str, delay: float) -> str:
        get_tenant_context().set_shop_id(name)
        await asyncio.sleep(delay)
        return get_tenant_context().shop_id

    results = await asyncio.gather(worker("store_A", 0.05), worker("store_B", 0.01))
    assert results == ["store_A", "store_B"]


async def test_tenant_context_write_does_not_leak_to_parent():
    """子 Task 写入不污染父上下文（替换式写入）"""
    from core.tenant.middleware import tenant_context, get_tenant_context

    tenant_context.set_shop_id("PARENT")
    try:
        async def worker():
            get_tenant_context().set_shop_id("CHILD")
            await asyncio.sleep(0)

        await asyncio.create_task(worker())
        assert tenant_context.shop_id == "PARENT"
    finally:
        tenant_context.clear()


def test_tenant_context_is_readonly_value_object():
    """TenantContext 是只读值对象，禁止原地赋值"""
    from core.tenant.middleware import TenantContext

    ctx = TenantContext(shop_id="s1")
    assert ctx.shop_id == "s1"
    with pytest.raises(AttributeError):
        ctx.shop_id = "s2"


def test_tenant_middleware_registered():
    """TenantMiddleware 必须真正挂在 app 上（历史 bug：定义了但没注册）"""
    from main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "TenantMiddleware" in names


# ====== 店铺归属校验 ======

async def test_shop_ownership_enforced(client, auth_on):
    """
    用户 B 不能访问用户 A 的店铺（403）；admin 除外。

    构造：A 建店铺 → B 用 X-Shop-ID 访问 → 应 403
    """
    import uuid
    from sqlalchemy import select, text
    from core.database import get_async_session
    from modules.user_subscription.models import User
    from modules.user_subscription.router import hash_password

    pwd = "owner123456"
    email_a = f"pytest-owner-a-{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"pytest-owner-b-{uuid.uuid4().hex[:8]}@example.com"
    shop_id = f"pytest-shop-{uuid.uuid4().hex[:8]}"

    async with get_async_session() as db:
        a = User(id=str(uuid.uuid4()), email=email_a, hashed_password=hash_password(pwd),
                 name="owner A", is_active=True)
        b = User(id=str(uuid.uuid4()), email=email_b, hashed_password=hash_password(pwd),
                 name="owner B", is_active=True)
        db.add_all([a, b])
        await db.flush()
        await db.execute(
            text(
                # 注意：PG 的 shopplatform 枚举存的是成员名（AMAZON_US），
                # 不是 ShopPlatform 枚举值（amazon_us）——SAEnum 默认按 .name 落库。
                "INSERT INTO shops (id, name, owner_id, platform, is_active, is_connected, "
                "sync_status, created_at, updated_at) "
                "VALUES (:id, :name, :owner, 'AMAZON_US', true, false, 'idle', now(), now())"
            ),
            {"id": shop_id, "name": "PYTEST SHOP", "owner": a.id},
        )
        await db.commit()
        a_id, b_id = a.id, b.id

    async def _login(email):
        r = await client.post("/api/v1/auth/login", data={"username": email, "password": pwd},
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    try:
        token_b = await _login(email_b)
        token_a = await _login(email_a)

        # B 访问 A 的店铺 -> 403
        r_b = await client.get(f"/api/v1/shops/{shop_id}",
                               headers={"Authorization": f"Bearer {token_b}", "X-Shop-ID": shop_id})
        assert r_b.status_code == 403, f"应拒绝跨用户访问, 实际 {r_b.status_code} {r_b.text[:200]}"

        # A 自己访问 -> 非 403
        r_a = await client.get(f"/api/v1/shops/{shop_id}",
                               headers={"Authorization": f"Bearer {token_a}", "X-Shop-ID": shop_id})
        assert r_a.status_code != 403, r_a.text[:200]
    finally:
        async with get_async_session() as db:
            await db.execute(text("DELETE FROM shops WHERE id = :i"), {"i": shop_id})
            await db.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": a_id, "b": b_id})
            await db.commit()

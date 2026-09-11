"""
订阅 & 计费端点回归测试

覆盖（后端新补的 6 个端点 + 契约对齐）：
1. GET  /billing/plans        → 套餐列表（含 price_yearly / limits / features 数组）
2. GET  /billing/subscription → 订阅详情（含 cancel_at_period_end / usage）
3. POST /billing/subscribe    → 切换套餐（生成账单）
4. POST /billing/cancel       → 取消订阅（周期结束生效）
5. POST /billing/resume       → 恢复订阅
6. GET  /billing/invoices     → 账单历史
7. GET/POST/PUT /billing/payment-methods → 支付方式增删改

鉴权约定：billing 端点用 get_current_user（强用户绑定），
需 `auth_on` 打开生产模式 + 有效 token。
"""

import pytest


# ====== 套餐 & 订阅（只读） ======

async def test_plans_contract_aligned(client, auth_on):
    """套餐列表字段应符合前端 SubscriptionPlan 契约"""
    r = await client.get("/api/v1/billing/plans")
    assert r.status_code == 200, r.text

    plans = r.json()["plans"]
    assert len(plans) >= 3, "至少应有 free/pro/enterprise 三个套餐"

    for p in plans:
        assert isinstance(p["id"], str), "套餐 id 应为字符串"
        assert "price_yearly" in p, "缺 price_yearly"
        assert "limits" in p and isinstance(p["limits"], dict), "limits 应为嵌套对象"
        assert "features" in p and isinstance(p["features"], list), "features 应为数组"
        # limits 内部字段
        limits = p["limits"]
        assert "api_calls_per_month" in limits
        assert "agent_chats_per_month" in limits
        assert "shops_limit" in limits
        assert "team_members" in limits
        assert "ai_generations" in limits


async def test_subscription_contract_aligned(client, auth_on, user, auth_headers):
    """订阅详情应含 cancel_at_period_end / usage / plan.id 字符串"""
    r = await client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert r.status_code == 200, r.text

    sub = r.json()["subscription"]
    assert sub is not None, "注册用户应有默认订阅"
    assert "cancel_at_period_end" in sub
    assert sub["cancel_at_period_end"] is False
    assert "usage" in sub and isinstance(sub["usage"], dict)
    assert isinstance(sub["plan"]["id"], str)
    assert "period" in sub


# ====== 切换套餐 ======

async def test_subscribe_changes_plan_and_creates_invoice(
    client, auth_on, user, auth_headers
):
    """切换到 pro 套餐应成功，并生成一条 paid 账单"""
    from sqlalchemy import select
    from core.database import get_async_session
    from modules.user_subscription.models import SubscriptionPlan, Invoice

    # 找到 pro 套餐 id
    async with get_async_session() as db:
        pro = (
            await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.name == "pro")
            )
        ).scalar_one()
        pro_id = str(pro.id)

    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": pro_id, "billing_cycle": "yearly"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscription"]["plan"]["name"] == "pro"
    assert "client_secret" in body

    # 应生成一条账单
    async with get_async_session() as db:
        invs = (
            await db.execute(
                select(Invoice).where(Invoice.user_id == user["user_id"])
            )
        ).scalars().all()
        assert len(invs) == 1, "切换套餐应生成一条账单"
        assert invs[0].status == "paid"
        assert invs[0].amount == pro.price_monthly * 10, "年付金额应为月付×10"


async def test_subscribe_unknown_plan_404(client, auth_on, user, auth_headers):
    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "999999", "billing_cycle": "monthly"},
        headers=auth_headers,
    )
    assert r.status_code == 404


# ====== 取消 / 恢复 ======

async def test_cancel_and_resume_flow(client, auth_on, user, auth_headers):
    """取消 → 标记 cancel_at_period_end；恢复 → 清除标记"""
    r = await client.post("/api/v1/billing/cancel", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["subscription"]["cancel_at_period_end"] is True

    # 再次取消应 400（已取消）
    r2 = await client.post("/api/v1/billing/cancel", headers=auth_headers)
    assert r2.status_code == 400

    # 恢复
    r3 = await client.post("/api/v1/billing/resume", headers=auth_headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["subscription"]["cancel_at_period_end"] is False


# ====== 账单历史 ======

async def test_invoices_empty_by_default(client, auth_on, user, auth_headers):
    r = await client.get("/api/v1/billing/invoices", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["invoices"] == []
    assert r.json()["total"] == 0


# ====== 支付方式 ======

async def test_payment_method_crud(client, auth_on, user, auth_headers):
    """添加 → 首个自动默认 → 设默认 → 删除"""
    # 添加（首个自动设默认）
    r = await client.post(
        "/api/v1/billing/payment-methods",
        json={"type": "card", "brand": "visa", "last4": "4242"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    pm1 = r.json()
    assert pm1["is_default"] is True
    assert pm1["last4"] == "4242"

    # 添加第二个（非默认）
    r2 = await client.post(
        "/api/v1/billing/payment-methods",
        json={"type": "card", "brand": "mastercard", "last4": "8888"},
        headers=auth_headers,
    )
    assert r2.status_code == 200, r2.text
    pm2 = r2.json()
    assert pm2["is_default"] is False

    # 设第二个为默认
    r3 = await client.put(
        f"/api/v1/billing/payment-methods/{pm2['id']}",
        json={"action": "set_default"},
        headers=auth_headers,
    )
    assert r3.status_code == 200

    # 列表验证默认已切换
    r4 = await client.get("/api/v1/billing/payment-methods", headers=auth_headers)
    pms = r4.json()["payment_methods"]
    assert len(pms) == 2
    default = [p for p in pms if p["is_default"]]
    assert len(default) == 1
    assert default[0]["id"] == pm2["id"]

    # 删除第二个（默认），第一个应自动补位为默认
    r5 = await client.put(
        f"/api/v1/billing/payment-methods/{pm2['id']}",
        json={"action": "detach"},
        headers=auth_headers,
    )
    assert r5.status_code == 200

    r6 = await client.get("/api/v1/billing/payment-methods", headers=auth_headers)
    pms_after = r6.json()["payment_methods"]
    assert len(pms_after) == 1
    assert pms_after[0]["is_default"] is True


async def test_payment_method_not_found(client, auth_on, user, auth_headers):
    r = await client.put(
        "/api/v1/billing/payment-methods/nonexistent",
        json={"action": "detach"},
        headers=auth_headers,
    )
    assert r.status_code == 404


# ====== 鉴权：未认证应 401 ======

async def test_billing_requires_auth(client, auth_on):
    """生产模式下无 token 访问计费接口应 401"""
    r = await client.get("/api/v1/billing/subscription")
    assert r.status_code == 401

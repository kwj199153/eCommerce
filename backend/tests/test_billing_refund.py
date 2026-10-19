"""退款登记闭环（r385 · 商用审查 P0-4）。

==============================================================================
★ 缺陷形态
==============================================================================
`Invoice.status` 的注释里一直列着 `refunded`，全仓却**没有任何写入路径**
（`grep -rn refund backend/modules/billing/*.py` 只命中注释与两处"矛盾状态
不许静默开权限"的判断）⇒ 客户要退款时，系统里无法表达这件事，运营只能改 SQL。

本轮补的最小闭环（**登记**，不是打款）：
    POST /api/v1/billing/invoices/{id}/refund   （平台超管）
    → `payments.refund_invoice()`               （唯一写入路径）

★ 为什么"不打款"：本项目没有支付宝商户号，`alipay.trade.refund` 的真实报文
  无法验证。写一条没人验证过的**资金调用**比不写更危险 —— 它会让人以为
  "点了就退了"。⇒ 语义明确为：先在支付宝后台退款，再回系统登记。

==============================================================================
★ 本文件锁五件事
==============================================================================
  1. 已支付账单能退，且**三列 + 状态**都真的落库；
  2. 退款同时**撤销订阅**（钱退了权限还留着是最常见的漏账）；
  3. 重复提交走 `already_refunded`，**不二次撤销**订阅；
  4. 未到账（pending/failed/expired）状态**退不了**（钱根本没到）；
  5. 端点挂**平台超管**门禁（AST 判据：防"以后被改成任何人都能退钱"）。
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from core.database import async_session_factory
from core.identity.models import User
from modules.billing.models import Invoice, Subscription
from modules.billing.payments import refund_invoice

BACKEND = Path(__file__).resolve().parents[1]


async def _uid_of(email: str) -> str:
    async with async_session_factory() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _make_invoice(user_id: str, status: str = "paid") -> str:
    inv_id = str(uuid.uuid4())
    async with async_session_factory() as db:
        db.add(
            Invoice(
                id=inv_id,
                user_id=user_id,
                number=f"INV-T{uuid.uuid4().hex[:10].upper()}",
                amount_fen=29900,
                status=status,
                description="[pytest] 退款用例",
                paid_at=datetime.utcnow() if status == "paid" else None,
            )
        )
        await db.commit()
    return inv_id


async def _read_invoice(inv_id: str) -> dict:
    async with async_session_factory() as db:
        inv = (
            await db.execute(select(Invoice).where(Invoice.id == inv_id))
        ).scalar_one()
        return {
            "status": inv.status,
            "refunded_at": inv.refunded_at,
            "refund_reason": inv.refund_reason,
            "refund_operator_id": inv.refund_operator_id,
        }


async def _sub_status(user_id: str) -> str:
    async with async_session_factory() as db:
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == user_id))
        ).scalar_one_or_none()
        return "" if sub is None else sub.status


async def _promote_to_admin(email: str) -> None:
    """把该用户改成平台超管（`is_platform_admin` 的唯一判据是 role == 'admin'）。"""
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await db.commit()


# ---------------------------------------------------------------------------
# 领域层（直接调唯一入口）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_refund_paid_invoice_writes_three_columns(user):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "paid")

    async with async_session_factory() as db:
        out = await refund_invoice(
            db, inv_id, operator_id="admin-001", reason="客户申请：误购"
        )
    assert out.ok and not out.already_refunded
    assert out.subscription_revoked is True, "退款必须同时撤销订阅（钱退了权限还在 = 漏账）"

    row = await _read_invoice(inv_id)
    assert row["status"] == "refunded"
    assert row["refunded_at"] is not None
    assert row["refund_reason"] == "客户申请：误购"
    assert row["refund_operator_id"] == "admin-001"
    assert await _sub_status(uid) == "cancelled"


@pytest.mark.asyncio
async def test_refund_is_idempotent(user):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "paid")

    async with async_session_factory() as db:
        first = await refund_invoice(db, inv_id, operator_id="admin-001", reason="x")
    assert first.ok and not first.already_refunded

    # 第二次：账单已经是 refunded ⇒ 正常返回 already_refunded，不报错
    async with async_session_factory() as db:
        second = await refund_invoice(db, inv_id, operator_id="admin-002", reason="y")
    assert second.ok and second.already_refunded
    # ★ 关键：第二次**不**再撤销订阅 —— 否则用户后来新买的套餐会被误撤
    assert second.subscription_revoked is False

    row = await _read_invoice(inv_id)
    # 第二次不该覆盖第一次的审计信息
    assert row["refund_operator_id"] == "admin-001"
    assert row["refund_reason"] == "x"


@pytest.mark.asyncio
async def test_refund_rejects_unpaid_invoice(user):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "pending")

    async with async_session_factory() as db:
        out = await refund_invoice(db, inv_id, operator_id="admin-001", reason="x")

    assert not out.ok
    assert out.reason == "status_conflict:pending"
    assert (await _read_invoice(inv_id))["status"] == "pending"


@pytest.mark.asyncio
async def test_refund_missing_invoice(user):
    async with async_session_factory() as db:
        out = await refund_invoice(db, "no-such-invoice", operator_id="admin-001")
    assert not out.ok and out.reason == "invoice_not_found"


@pytest.mark.asyncio
async def test_refund_without_revoke_keeps_subscription(user):
    """`revoke_subscription=False` 是给"退款但保留服务"的例外场景留的口子。"""
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "paid")

    async with async_session_factory() as db:
        out = await refund_invoice(
            db, inv_id, operator_id="admin-001", reason="保留服务", revoke_subscription=False
        )
    assert out.ok and out.subscription_revoked is False
    assert (await _read_invoice(inv_id))["status"] == "refunded"
    assert await _sub_status(uid) == "active"


# ---------------------------------------------------------------------------
# 端点层
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_endpoint_rejects_non_admin(client, user, auth_headers):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "paid")

    r = await client.post(
        f"/api/v1/billing/invoices/{inv_id}/refund",
        json={"reason": "自己点退款"},
        headers=auth_headers,
    )
    assert r.status_code == 403, r.text[:300]
    assert (await _read_invoice(inv_id))["status"] == "paid"


@pytest.mark.asyncio
async def test_endpoint_refunds_as_admin(client, user, auth_headers):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "paid")
    await _promote_to_admin(user["email"])

    r = await client.post(
        f"/api/v1/billing/invoices/{inv_id}/refund",
        json={"reason": "风控要求退款"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body["success"] is True
    assert body["already_refunded"] is False
    # ★ 响应里必须写清"不发起真实退款"，否则运营会以为钱已经退了
    assert "支付宝" in body["note"]

    row = await _read_invoice(inv_id)
    assert row["status"] == "refunded"
    assert row["refund_reason"] == "风控要求退款"


@pytest.mark.asyncio
async def test_endpoint_conflict_returns_409(client, user, auth_headers):
    uid = await _uid_of(user["email"])
    inv_id = await _make_invoice(uid, "failed")
    await _promote_to_admin(user["email"])

    r = await client.post(
        f"/api/v1/billing/invoices/{inv_id}/refund",
        json={"reason": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text[:300]
    assert r.json()["detail"]["code"] == "INVOICE_NOT_REFUNDABLE"


@pytest.mark.asyncio
async def test_endpoint_missing_returns_404(client, user, auth_headers):
    await _promote_to_admin(user["email"])
    r = await client.post(
        "/api/v1/billing/invoices/not-exist/refund",
        json={"reason": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text[:300]


# ---------------------------------------------------------------------------
# 门禁判据（AST）：退款端点必须挂平台超管
# ---------------------------------------------------------------------------
def _depends_names(fn: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
            for a in node.args:
                if isinstance(a, ast.Name):
                    names.add(a.id)
    return names


def test_refund_endpoint_requires_admin():
    """防「以后被人改成普通用户也能退钱」—— 那是一条资金动作的越权。"""
    tree = ast.parse((BACKEND / "modules" / "billing" / "router.py").read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
            and n.name == "refund_invoice_endpoint"
        ),
        None,
    )
    assert fn is not None, "找不到 refund_invoice_endpoint（改名了？判据需同步）"
    assert "get_admin_user" in _depends_names(fn), "退款端点没有平台超管门禁"


def test_only_two_status_writers():
    """`invoices.status` 的写入点必须只有 settle / refund 两处（收敛原则）。

    ★ 为什么钉这个：状态写入一散开，就必然出现"某条路径漏了校验"。
      实测改前全仓只有 `settle_invoice` 一处写 `paid`。
    """
    src = (BACKEND / "modules" / "billing" / "payments.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and tgt.attr == "status"
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id in ("invoice", "inv")
                    ):
                        writers.add(fn.name)
    assert writers <= {"settle_invoice", "refund_invoice"}, f"出现了第三个账单状态写入点：{writers}"
    assert "refund_invoice" in writers, "退款入口没有写 status，判据失效"

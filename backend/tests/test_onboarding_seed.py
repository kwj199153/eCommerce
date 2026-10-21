"""注册即播种 / 「加载示例数据」契约（第 387 轮 · 网站管理员 P0-2 + P0-3）

==============================================================================
这一组钉的是什么
==============================================================================
1. **装配真的生效**：注册端点返回 `onboarding[0].created=True`，而且新店能在
   `GET /api/v1/stores` 里**马上**看见。
   为什么这条必须走真实 HTTP：钩子是「core 定义机制 + 组合根注入」，
   `bootstrap_new_user` 自己测得再绿，只要 `main.py` 少一行登记，
   功能就是**不存在**，而且注册照常 201 —— 这是本仓反复出现的
   「装配漏一行 = 功能静默消失」。

2. **作用域**：`load_sample_data` 传给每个 seed 的 `only_for_shop_ids`
   必须**正好是**点名的那家店。判错的后果不是报错，而是「把示例数据灌进
   别人的店」—— 界面看起来一切正常。

3. **诚实标注**：返回值必须带 `is_sample=True` + `label`，且 `label` 里
   出现「示例」。少了它，前端只能显示「加载成功」，示例数据就以真实数据
   的样子出现在公开站上。

4. **404 与 200 分开**：店不存在时不能回「加载成功」（假成功）。

★ 这里**不真灌数据**：`_seeders` 被打桩成只记录入参的假函数。
  真灌一遍会在共享库里留下 16 张表的孤儿行（`tests/` 直连生产库），
  而「seed 本身写得对不对」由各 seed 自己的 `test_seed_shop_ids.py` 等覆盖。
  本文件要证的是**编排层**（作用域 / 标注 / 装配），两件事不该混在一个用例里。
"""

import uuid

import pytest
from sqlalchemy import select, text

import modules.onboarding.service as svc
from core.database import get_async_session
from core.identity.models import User


# ====== 辅助（与 test_account_store_hierarchy 同源）======

async def _register(client, tag: str) -> dict:
    email = f"pytest-onb-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    password = "pytest123456"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": tag},
    )
    assert r.status_code in (200, 201), f"注册失败 {r.status_code} {r.text[:300]}"
    body = r.json()

    async with get_async_session() as db:
        uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one()

    return {
        "email": email,
        "user_id": uid,
        "token": body["access_token"],
        "body": body,
    }


def _drop_from_memory(store_id: str) -> None:
    from modules.stores.router import _store_db

    _store_db.pop(store_id, None)


async def _purge_user(user_id: str, *store_ids: str) -> None:
    """清掉用户及其计费/成员/店铺痕迹（`/auth/register` 会顺手建订阅与店铺）。"""
    async with get_async_session() as db:
        await db.execute(text("DELETE FROM account_members WHERE user_id = :u"), {"u": user_id})
        await db.execute(text(
            "DELETE FROM account_members WHERE account_id IN "
            "(SELECT id FROM accounts WHERE owner_user_id = :u)"), {"u": user_id})
        await db.execute(text("DELETE FROM stores_store WHERE owner_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM accounts WHERE owner_user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM invoices WHERE user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM payment_methods WHERE user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await db.commit()
    for sid in store_ids:
        _drop_from_memory(sid)


def _stub_seeders(calls: list):
    """把 `_seeders()` 换成只记录入参的假函数（不写库）。"""

    def make(key: str, wrote: int):
        async def fake(*, only_for_shop_ids=()):
            calls.append((key, list(only_for_shop_ids)))
            return wrote

        return (key, f"{key} 标签", fake)

    return [make("products", 3), make("trade", 0)]


# ============================================================================
# 1. 装配：注册 ⇒ 真的多了一家店，且立刻可见
# ============================================================================

async def test_register_bootstraps_a_store_visible_immediately(client, auth_on):
    u = await _register(client, "boot")
    store_id = None
    try:
        hooks = u["body"].get("onboarding") or []
        assert hooks, (
            "注册响应里没有 onboarding 结果 ⇒ 钩子**没有被装配**"
            "（检查 main.py 的 register_post_register_hook 那一行）"
        )
        assert hooks[0]["ok"] is True, f"钩子执行失败：{hooks[0]}"
        assert hooks[0]["created"] is True, (
            f"新账号应当建一家示例店，实际：{hooks[0]}（"
            "若 reason=account_already_has_stores，说明这个邮箱名下已有店）"
        )
        store_id = hooks[0]["store_id"]
        assert store_id and store_id.startswith("store_"), hooks[0]

        # ★ 必须经接口确认，而不是只信返回值：
        #   建店有**两处**写入（PG + 内存 `_store_db`）。只写 PG 时接口列表是空的，
        #   而返回值照样是 True —— 用户要等到进程重启才看见那家店。
        r = await client.get(
            "/api/v1/stores", headers={"Authorization": f"Bearer {u['token']}"}
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        # ★ 响应形状是 `{stores, total}`（`StoreListResponse`）。这里刻意**不**写
        #   `or data or items` 之类的兜底：猜键名会让「列表为空」和「键名写错」
        #   长得一样，而前者才是真缺陷。
        assert "stores" in body, f"店铺列表响应形状变了：{list(body)[:8]}"
        items = body["stores"]
        ids = [s.get("id") for s in items]
        assert store_id in ids, f"新店没出现在店铺列表里：{ids}"

        matched = [s for s in items if s.get("id") == store_id][0]
        assert "示例" in (matched.get("name") or ""), (
            f"店名必须自证是示例店（否则等于在首屏埋一个谎）：{matched.get('name')!r}"
        )
        # 新店没有真实凭据：不能显示成"已连接"
        assert matched.get("has_credentials") is False
    finally:
        if u.get("user_id"):
            await _purge_user(u["user_id"], *( [store_id] if store_id else [] ))


async def test_bootstrap_is_idempotent(client, auth_on):
    u = await _register(client, "idem")
    store_id = None
    try:
        async with get_async_session() as db:
            user = (await db.execute(select(User).where(User.id == u["user_id"]))).scalar_one()
            # 第二次调用：账户里已经有店 ⇒ 不该再建
            again = await svc.bootstrap_new_user(db, user)

        assert again["created"] is False
        assert again["reason"] == "account_already_has_stores", again
    finally:
        if u.get("user_id"):
            await _purge_user(u["user_id"])


# ============================================================================
# 2. 作用域：示例数据只能灌给**点名的那一家店**
# ============================================================================

async def test_seeders_receive_exactly_the_named_shop(monkeypatch):
    calls: list = []
    monkeypatch.setattr(svc, "_seeders", lambda: _stub_seeders(calls))
    monkeypatch.setattr(svc, "_shop_exists", _async_true)

    data = await svc.load_sample_data("store_deadbeef")

    assert data["shop_id"] == "store_deadbeef"
    assert [c[1] for c in calls] == [["store_deadbeef"], ["store_deadbeef"]], (
        f"传给 seed 的 only_for_shop_ids 不是点名店铺：{calls}"
    )


async def _async_true(_shop_id: str) -> bool:
    return True


async def test_sample_result_is_labeled_as_sample(monkeypatch):
    monkeypatch.setattr(svc, "_seeders", lambda: _stub_seeders([]))
    monkeypatch.setattr(svc, "_shop_exists", _async_true)

    data = await svc.load_sample_data("store_x")

    assert data["is_sample"] is True, "缺 is_sample ⇒ 前端无从标注"
    assert "示例" in data["label"], f"label 必须自证是示例：{data['label']!r}"
    assert data["total"] == 3, data  # 3 + 0
    assert data["nothing_new"] is False


async def test_nothing_new_is_reported_honestly(monkeypatch):
    """全部返回 0 ⇒ 如实说「没有新增」，不粉饰成「加载成功」。"""
    def only_zero():
        async def fake(*, only_for_shop_ids=()):
            return 0

        return [("products", "产品库", fake)]

    monkeypatch.setattr(svc, "_seeders", only_zero)
    monkeypatch.setattr(svc, "_shop_exists", _async_true)

    data = await svc.load_sample_data("store_x")
    assert data["total"] == 0
    assert data["nothing_new"] is True


# ============================================================================
# 3. 404 与 200 必须分开
# ============================================================================

async def test_unknown_shop_raises():
    with pytest.raises(svc.SampleTargetMissing) as ei:
        await svc.load_sample_data("store_does_not_exist_387")
    assert ei.value.shop_id == "store_does_not_exist_387"


async def test_endpoint_404_for_missing_shop(client, auth_on):
    u = await _register(client, "404")
    try:
        r = await client.post(
            "/api/v1/onboarding/sample-data",
            headers={
                "Authorization": f"Bearer {u['token']}",
                "X-Shop-ID": "store_does_not_exist_387",
            },
        )
        # 归属校验先拦（不属于你 ⇒ 403），再才轮到 404。
        # 两者都**不是 200** —— 这才是本用例要的判据：不许假成功。
        assert r.status_code in (403, 404), (
            f"不存在的店铺回了 {r.status_code}（200 就是假成功）：{r.text[:300]}"
        )
    finally:
        await _purge_user(u["user_id"])


async def test_endpoint_requires_shop_header(client, auth_on):
    u = await _register(client, "nohdr")
    try:
        r = await client.post(
            "/api/v1/onboarding/sample-data",
            headers={"Authorization": f"Bearer {u['token']}"},
        )
        assert r.status_code == 400, (
            f"写端点缺 X-Shop-ID 应 400（可行动提示），实际 {r.status_code}：{r.text[:200]}"
        )
    finally:
        await _purge_user(u["user_id"])


async def test_endpoint_happy_path_is_labeled(client, auth_on, monkeypatch):
    u = await _register(client, "ok")
    store_id = None
    try:
        store_id = (u["body"].get("onboarding") or [{}])[0].get("store_id")
        assert store_id, u["body"]

        calls: list = []
        monkeypatch.setattr(svc, "_seeders", lambda: _stub_seeders(calls))

        r = await client.post(
            "/api/v1/onboarding/sample-data",
            headers={
                "Authorization": f"Bearer {u['token']}",
                "X-Shop-ID": store_id,
            },
        )
        assert r.status_code == 200, r.text[:300]
        payload = r.json()
        data = payload.get("data") or payload
        assert data.get("is_sample") is True, payload
        assert "示例" in (data.get("label") or ""), payload
        assert [c[1] for c in calls] == [[store_id], [store_id]], calls
    finally:
        if u.get("user_id"):
            await _purge_user(u["user_id"], *([store_id] if store_id else []))

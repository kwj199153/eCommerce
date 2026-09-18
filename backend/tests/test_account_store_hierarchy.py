"""
account → store 层级守护（P1-c 收拢的可执行判据，2026-09-16）

★★★ 这一层解决的是什么
改造前本项目有**两套店铺实体**，ID 空间不同且互不同步（完整说明见
`core/identity/account_models.py` 与迁移 `f2a7c1d4e5b8`）：

    | 侧 | 表 | ID 形态 | 谁在读 |
    |----|----|---------|--------|
    | 账户侧 | `shops` | UUID | 只有 core/identity/shop_router.py 的 7 个端点 |
    | 业务侧 | `stores_store` | `store_xxx` | 15 个业务模块的 get_current_shop_id* |

实测那 7 个端点**生产 0 调用点**，且用它建出来的店在业务侧**根本不可用**
⇒ 那条路只会安静地生产一批废店。收拢后层级唯一：

    User ──(owner_user_id)──> Account ──(account_id)──> StoreRecord
                                 │
                                 └──(account_members)──> User   ← 成员共享账户下的店铺

本文件锁定四件事：

  1. **账户侧实体不再存在** —— `shops` 表 / `Shop` / `ShopPlatform` /
     `shop_router.py` / `/api/v1/shops*` 都不得复活（第 1 条用例）。
  2. **经接口建的店必然挂在一个账户上** —— `account_id IS NOT NULL`
     且该账户的 owner 就是建店人（第 2 条用例）。
  3. **归属判定的四条分支**（纯函数穷尽，第 3 条）——
     其中「`frozenset()`（什么都看不到）≠ `None`（不设限）」是**无声越权**的分界。
  4. **团队共享真的生效**（第 4/5 条）：账户成员能进账户下的店铺、角色矩阵
     卡住写操作、成员被移除后访问立刻失效。

★ 「无账户归属的店铺」这条过渡期兜底**故意保留**并单独被测（第 3 条 ④ 段）：
  存量店铺与测试用的合成店铺靠它存活。回填彻底完成后，应把该分支与
  对应断言一起删 —— 而不是让它们悄悄消失。
"""

import uuid


# ====== 辅助 ======

async def _register(client, tag: str) -> dict:
    """注册一个新用户并登录，返回 {email, password, token, user_id}。"""
    email = f"pytest-hier-{tag}-{uuid.uuid4().hex[:8]}@example.com"
    password = "pytest123456"

    r = await client.post("/api/v1/auth/register",
                          json={"email": email, "password": password, "name": tag})
    assert r.status_code in (200, 201), f"注册失败 {r.status_code} {r.text[:300]}"

    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, f"登录失败 {lr.status_code} {lr.text[:300]}"

    from sqlalchemy import select
    from core.database import get_async_session
    from core.identity.models import User

    async with get_async_session() as db:
        uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one()

    return {"email": email, "password": password,
            "token": lr.json()["access_token"], "user_id": uid}


async def _drop_store(client, token: str, store_id: str) -> None:
    """经接口删店（同时清内存缓存与 PG）；接口失败则回退裸 SQL + 清内存。"""
    r = await client.delete(f"/api/v1/stores/{store_id}",
                            headers={"Authorization": f"Bearer {token}"})
    if r.status_code not in (200, 204, 404):
        from sqlalchemy import text
        from core.database import async_session_factory
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM stores_store WHERE id = :i"), {"i": store_id})
            await db.commit()
    _drop_from_memory(store_id)


def _drop_from_memory(store_id: str) -> None:
    """内存读缓存 `_store_db` 是模块级 dict，跨用例存活 ⇒ 必须显式清。"""
    from modules.stores.router import _store_db
    _store_db.pop(store_id, None)


async def _purge_user(user_id: str) -> None:
    """清掉用户及其计费/成员痕迹（`/auth/register` 会顺手建一条订阅）。"""
    from sqlalchemy import text
    from core.database import get_async_session

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


# ====== 1. 账户侧实体不得复活 ======

async def test_legacy_shops_entity_is_gone():
    """
    `shops` 表 / `Shop` / `ShopPlatform` / `shop_router.py` / `/api/v1/shops*`
    必须**全部**不存在。

    ★ 为什么必须逐项点名，而不是只看"删掉了路由"：
      这套实体整体删除是一次**架构收拢**（两套 ID 空间合成一套）。
      只要表或模型还在，就会有人重新挂一个端点上去 —— 那批端点建出来的店
      在业务侧不可用，会**安静地生产废店**（不报错、不告警）。
      所以这四者要一起消失，且要一起被守卫。
    """
    import os
    import core.identity.models as ident

    # ① ORM 模型
    assert not hasattr(ident, "Shop"), "core.identity.models.Shop 又回来了"
    assert not hasattr(ident, "ShopPlatform"), "core.identity.models.ShopPlatform 又回来了"

    # ② 路由模块文件
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert not os.path.exists(os.path.join(backend, "core", "identity", "shop_router.py")), \
        "core/identity/shop_router.py 又回来了"

    # ③ 表（结构事实）
    from sqlalchemy import text
    from core.database import async_session_factory

    async with async_session_factory() as db:
        has_table = (await db.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='shops'"
        ))).scalar()
        has_type = (await db.execute(text(
            "SELECT 1 FROM pg_type WHERE typname='shopplatform'"
        ))).scalar()
    assert not has_table, (
        "shops 表又存在了（迁移 f2a7c1d4e5b8 已删除它）。"
        "账户侧实体与业务侧 stores_store 是两套 ID 空间，并存会让人接错。"
    )
    assert not has_type, "shopplatform 枚举类型又存在了"

    # ④ 路由表
    #    ★ 直接 import main.app（与 test_auth_and_tenant.py 的做法一致），
    #      不依赖 httpx 客户端的内部属性（那是实现细节，版本升级会变）。
    from fastapi.routing import APIRoute
    from main import app as fastapi_app
    paths = {r.path for r in fastapi_app.routes if isinstance(r, APIRoute)}
    leaked = sorted(p for p in paths if p == "/api/v1/shops" or p.startswith("/api/v1/shops/"))
    assert not leaked, f"/api/v1/shops* 路由又挂上了：{leaked}"


# ====== 2. 经接口建的店必然挂在一个账户上 ======

async def test_store_created_via_api_is_linked_to_owner_account(
    client, auth_on, user, auth_headers
):
    """
    `POST /api/v1/stores` 建出来的店：`account_id` 非空、`owner_id` 是本人、
    且该账户里有一条 **owner** 成员记录。

    ★ 三条一起断言的理由：
      - 只有 `account_id` 非空，团队共享才对它生效（否则只能靠 owner_id 兜底）；
      - `owner_id` 仍要写，它是**审计事实**（谁建的），只是不再参与授权；
      - owner 成员记录必须存在，否则 `resolve_account_role()` 返回 None，
        `account.manage` 无人持有 ⇒ 该账户在界面上"无人可管理"。
    """
    r = await client.post("/api/v1/stores",
                          json={"name": "[pytest] 层级用例", "platform": "amazon_us"},
                          headers=auth_headers)
    assert r.status_code == 201, f"{r.status_code} {r.text[:300]}"
    store_id = r.json()["id"]

    try:
        from sqlalchemy import text
        from core.database import async_session_factory

        async with async_session_factory() as db:
            row = (await db.execute(text(
                "SELECT owner_id, account_id FROM stores_store WHERE id = :i"
            ), {"i": store_id})).one()
            owner_id, account_id = row[0], row[1]

            assert account_id, (
                "建店没有挂账户（account_id 为空）—— 团队共享对该店永久失效，"
                "而界面上看不出任何异常"
            )
            assert owner_id == user["user_id"], "owner_id 应记录建店人（审计事实）"

            acct_owner = (await db.execute(text(
                "SELECT owner_user_id FROM accounts WHERE id = :a"
            ), {"a": account_id})).scalar()
            assert acct_owner == user["user_id"], "账户的 owner 必须是建店人"

            role = (await db.execute(text(
                "SELECT role FROM account_members "
                "WHERE account_id = :a AND user_id = :u AND status = 'active'"
            ), {"a": account_id, "u": user["user_id"]})).scalar()
            assert role == "owner", (
                f"账户里没有 owner 成员记录（拿到 {role!r}）⇒ account.manage 无人持有，"
                f"该账户将没有任何人能管理"
            )

        # ② 幂等：再建一个店，必须复用同一个账户（不是每建一个店开一个账户）
        r2 = await client.post("/api/v1/stores",
                               json={"name": "[pytest] 层级用例2", "platform": "amazon_us"},
                               headers=auth_headers)
        assert r2.status_code == 201, r2.text[:300]
        store2 = r2.json()["id"]
        try:
            async with async_session_factory() as db:
                acct2 = (await db.execute(text(
                    "SELECT account_id FROM stores_store WHERE id = :i"
                ), {"i": store2})).scalar()
            assert acct2 == account_id, (
                f"同一用户的两家店挂到了不同账户（{account_id} vs {acct2}）—— "
                f"`ensure_default_account()` 不幂等会造出重复容器，而重复容器**不报错**"
            )
        finally:
            await _drop_store(client, user["token"], store2)
    finally:
        await _drop_store(client, user["token"], store_id)


# ====== 3. 归属判定内核：四条分支穷尽 ======

def test_ownership_kernel_branches():
    """
    `core.auth.accounts._matches` 的**全部分支**（纯函数，不碰 IO）。

    ★ 为什么要直接测这个私有内核：它是归属判定的唯一算术，四个分支对应四种
      语义，混起来就是越权。走 HTTP 只能覆盖到一部分 —— 「平台超管」与
      「演示模式」都在更外层短路了，从端点根本打不到这两个分支。

    ★★ 最要命的一条：`frozenset()`（什么都看不到）与 `None`（不设限）必须
      是两个不同的值。写成 `if not visible: return True` 的"顺手简化"
      ⇒ 新注册用户（可见集合为空）立刻能看**全部**账户的店铺，且不报错。
    """
    from types import SimpleNamespace
    from core.auth.accounts import _matches

    user = SimpleNamespace(id="u-1", role="user")
    other = SimpleNamespace(id="u-2", role="user")

    # ① 演示模式（无身份）⇒ 本内核返回 True，但★ 列表入口已不再走到这里
    #    （`filter_accessible_stores` 现在 `user is None` 直接返回空列表）；
    #    走到这里的是**单店**路径，见 accounts.py 里的 P1-5 说明。
    assert _matches("acct-x", "u-9", frozenset(), None) is True

    # ② 平台超管：visible is None 表示「不设限」
    assert _matches("acct-x", "u-9", None, user) is True
    assert _matches("acct-x", "u-9", frozenset(), user) is False, (
        "空集被当成了「不设限」—— 这就是无声越权。frozenset() 是「什么都看不到」，"
        "None 才是「全部」"
    )

    # ③ 有账户归属 ⇒ 只看 account_id 在不在可见集合里
    assert _matches("acct-x", "u-9", frozenset({"acct-x"}), user) is True
    assert _matches("acct-x", "u-9", frozenset({"acct-y"}), user) is False
    assert _matches("acct-x", "u-1", frozenset(), user) is False, (
        "店铺有账户归属时，owner_id 不得成为后门（账号被移出团队后，"
        "仅凭「我是创建者」不该还能进）"
    )

    # ④ 过渡期兜底：无账户归属 ⇒ 回退到创建者判定
    #    （存量店铺与合成测试店铺靠这条活着；回填完成后连同本段一起删）
    assert _matches(None, "u-1", frozenset(), user) is True
    assert _matches(None, "u-2", frozenset(), user) is False
    assert _matches(None, None, frozenset(), user) is False, "无主店铺对非超管一律拒绝"


async def test_filter_accessible_stores_no_identity_means_no_data():
    """
    ★★★ 守卫：没有身份 ⇒ 没有数据（2026-09-17）。

    直接测批量筛法的**两个短路分支**，不碰 IO：
      · `user is None`（匿名 / 演示哨兵）⇒ **空列表**（改前是"不过滤 ⇒ 全库"）
      · `visible is None`（平台超管）    ⇒ **全量**（这条是对的，不能一起收）

    ★ 为什么用"会爆炸的 db"当入参：两条分支都应在**查库之前**短路。若哪天有人把
      `get_visible_account_ids()` 提到前面、或把 `user is None` 写成"查完再判"，
      本用例会用一条明确的 AssertionError 报出"该分支不应查库" ——
      而不是悄悄多出一次全表查询。

    ★★ 两条分支**不可混淆**：都写 `return list(stores)` 就是"匿名 = 超管"
      （全库对任何人不设限地敞开）；都写 `return []` 则超管也看不到东西。
      本用例同时断言两者，任何一个被改坏都会红。

    反向注入：把 `filter_accessible_stores` 里的 `return []` 改回
    `return list(stores)`，第一条断言必须转红。
    """
    from types import SimpleNamespace

    from core.auth.accounts import PLATFORM_ADMIN_ROLE, filter_accessible_stores

    class _ExplodingSession:
        """任何 IO 都抛 —— 用来证明这两条分支都是**零 DB 往返**。"""

        async def execute(self, *a, **kw):
            raise AssertionError(
                "该分支不应查库（应在 get_visible_account_ids 之前短路）"
            )

    db = _ExplodingSession()
    stores = [
        SimpleNamespace(id="s-1", account_id="acct-1", owner_id="u-1"),
        SimpleNamespace(id="s-2", account_id="acct-2", owner_id="u-2"),
    ]

    assert await filter_accessible_stores(db, None, stores) == [], (
        "★★★ 匿名拿到了店铺 —— 「没有身份 ⇒ 没有数据」的守卫失效了。"
        "改前这里是 `return list(stores)`（不过滤）⇒ 演示档下全库裸奔。"
    )

    admin = SimpleNamespace(id="u-admin", role=PLATFORM_ADMIN_ROLE)
    assert await filter_accessible_stores(db, admin, stores) == stores, (
        "平台超管看不到了 —— 把 `visible is None`（不设限）与空集（什么都看不到）"
        "混为一谈了。这两者在 `_matches` 里是两条不同的分支，不能一起收。"
    )


# ====== 4. 团队共享：成员能进、能写，但删不了店 ======

async def test_account_member_shares_account_stores(client, auth_on, user, auth_headers):
    """
    账户成员能访问该账户下的店铺（这是本次收拢**唯一的功能目标**）。

    链路：A 建店 → A 把自己的账户分享给 B（`POST /accounts/{id}/members`）
          → B 能读、能改名（member 有 store.write）
          → 但 B 删不掉店（store.delete 只给 owner/admin）—— 角色矩阵真的在管。
    收到移除后 B 立刻失去访问（软删 `status=removed` 即时生效）。
    """
    b = await _register(client, "member")
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = await client.post("/api/v1/stores",
                          json={"name": "[pytest] 共享店", "platform": "amazon_us"},
                          headers=auth_headers)
    assert r.status_code == 201, r.text[:300]
    store_id = r.json()["id"]

    try:
        me = await client.get("/api/v1/accounts/me", headers=auth_headers)
        assert me.status_code == 200, me.text[:300]
        account_id = me.json()["account"]["id"]

        # 邀请前：B 是陌生人 ⇒ 403
        pre = await client.get(f"/api/v1/stores/{store_id}", headers=b_headers)
        assert pre.status_code == 403, (
            f"非成员竟然能读该店：{pre.status_code} {pre.text[:200]}"
        )

        # 邀请
        inv = await client.post(
            f"/api/v1/accounts/{account_id}/members",
            json={"email": b["email"], "role": "member"},
            headers=auth_headers,
        )
        assert inv.status_code == 201, f"{inv.status_code} {inv.text[:300]}"
        member_id = inv.json()["member"]["id"]

        # 邀请后：能读
        got = await client.get(f"/api/v1/stores/{store_id}", headers=b_headers)
        assert got.status_code == 200, (
            f"账户成员读不到本账户的店：{got.status_code} {got.text[:200]}"
        )

        # member 有 store.write ⇒ 能改名
        upd = await client.put(f"/api/v1/stores/{store_id}",
                               json={"name": "[pytest] 共享店(成员改名)"}, headers=b_headers)
        assert upd.status_code == 200, f"member 改名被拒：{upd.status_code} {upd.text[:200]}"

        # member **没有** store.delete ⇒ 删店 403
        dele = await client.delete(f"/api/v1/stores/{store_id}", headers=b_headers)
        assert dele.status_code == 403, (
            f"member 竟然能删店（store.delete 应只给 owner/admin）："
            f"{dele.status_code} {dele.text[:200]}"
        )

        # 移除成员 ⇒ 立刻失去访问（软删 status=removed，判定只看 ACTIVE）
        rem = await client.delete(
            f"/api/v1/accounts/{account_id}/members/{member_id}", headers=auth_headers
        )
        assert rem.status_code == 200, f"{rem.status_code} {rem.text[:300]}"

        post = await client.get(f"/api/v1/stores/{store_id}", headers=b_headers)
        assert post.status_code == 403, (
            f"成员被移除后仍能访问：{post.status_code} —— "
            f"`get_visible_account_ids` 必须只认 status=ACTIVE"
        )
    finally:
        await _drop_store(client, user["token"], store_id)
        await _purge_user(b["user_id"])


# ====== 5. viewer 是只读的（角色矩阵最容易被当装饰的一档）======

async def test_viewer_role_is_read_only(client, auth_on, user, auth_headers):
    """
    `AccountRole.VIEWER` 的定义是「可看，任何写操作 403」。

    ★ 这条存在的理由：角色矩阵最容易变成**装饰** —— 业务端点若只做归属判定
      不查能力表，viewer 照样能改名/删店/连接平台，而矩阵贴在文档里看起来很完整。
      本用例逐个打四个写操作，就是为了让矩阵**真的有牙齿**。
    """
    v = await _register(client, "viewer")
    v_headers = {"Authorization": f"Bearer {v['token']}"}

    r = await client.post("/api/v1/stores",
                          json={"name": "[pytest] viewer 只读店", "platform": "amazon_us"},
                          headers=auth_headers)
    assert r.status_code == 201, r.text[:300]
    store_id = r.json()["id"]

    try:
        me = await client.get("/api/v1/accounts/me", headers=auth_headers)
        account_id = me.json()["account"]["id"]

        inv = await client.post(
            f"/api/v1/accounts/{account_id}/members",
            json={"email": v["email"], "role": "viewer"},
            headers=auth_headers,
        )
        assert inv.status_code == 201, f"{inv.status_code} {inv.text[:300]}"

        # 读 ⇒ 放行
        got = await client.get(f"/api/v1/stores/{store_id}", headers=v_headers)
        assert got.status_code == 200, f"viewer 读不到：{got.status_code} {got.text[:200]}"

        # 四个写 ⇒ 全 403
        upd = await client.put(f"/api/v1/stores/{store_id}",
                               json={"name": "[pytest] viewer 试图改名"}, headers=v_headers)
        assert upd.status_code == 403, f"viewer 竟然能改名：{upd.status_code}"

        dele = await client.delete(f"/api/v1/stores/{store_id}", headers=v_headers)
        assert dele.status_code == 403, f"viewer 竟然能删店：{dele.status_code}"

        con = await client.post(f"/api/v1/stores/{store_id}/connect",
                                json={}, headers=v_headers)
        assert con.status_code == 403, f"viewer 竟然能连接平台：{con.status_code}"

        dis = await client.post(f"/api/v1/stores/{store_id}/disconnect",
                                headers=v_headers)
        assert dis.status_code == 403, f"viewer 竟然能断开连接：{dis.status_code}"

        # 反向保护：owner 未被误伤
        own = await client.put(f"/api/v1/stores/{store_id}",
                               json={"name": "[pytest] owner 改名"}, headers=auth_headers)
        assert own.status_code == 200, f"owner 改名被误伤：{own.status_code} {own.text[:200]}"
    finally:
        await _drop_store(client, user["token"], store_id)
        await _purge_user(v["user_id"])

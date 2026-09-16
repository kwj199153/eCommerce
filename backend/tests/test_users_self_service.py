"""用户自助管理端点的行为锁定（★ 第 100 轮新增 2026-09-16，第 101 轮修订）

覆盖补出来的六条端点（对应此前 `Settings.vue` 那 7 个 404 的 `/users/*` 调用）：

| 端点 | 前端调用点 |
|---|---|
| `PUT  /users/profile`       | 保存个人资料 |
| `POST /users/avatar`        | 上传头像 |
| `GET  /users/api-keys`      | 密钥列表 |
| `POST /users/api-keys`      | 创建密钥 |
| `DELETE /users/api-keys/{id}` | 删除密钥 |
| `PUT  /users/notifications` | 保存通知偏好 |

==============================================================================
★ 本文件同时是**越权防线**的守卫，不只是功能测试
==============================================================================
所有资源都按 `current_user.id` 过滤，操作他人资源一律 **404**
（不是 403 —— 403 等于确认"这个 id 存在、只是不属于你"，
那是资源枚举的信标。本项目统一口径：越权 404）。

★ 四条最容易写漏、也最容易在重构中被改坏的断言：
  ① 资料更新**不接受** `role` / `is_active`（否则就是自助提权接口）；
  ② API 密钥库里**只有哈希**（明文只在创建响应里出现一次）；
  ③ 头像按**魔数**校验（改名成 .png 的非图片必须被拒）；
  ④ 通知偏好里显式关掉的 `false` 必须**原样存下来**
     （若实现用了 `x or 默认值`，用户会发现"这个开关永远关不掉"）。

==============================================================================
★★ 第 101 轮修订：全部用例改用 `make_user`（独享用户），不再共用 `auth_headers`
==============================================================================
修订前的两条用例（密钥列表 / 撤销后列表）用的是共享 `auth_headers`，
却断言 `total == 1` / `total == 0`；而同一文件里的
`test_create_api_key_returns_plaintext_once` 等也在给**同一个**共享用户建密钥
⇒ 计数断言实际取决于执行顺序：全量跑绿、加 `-k` 单跑就红。

★ 判据：**凡是"按 user_id 聚合之后断言绝对数量 / 绝对默认值"的用例，
  必须使用独享用户**；共享夹具只适合"相对断言"（改前 vs 改后）。
  同理，原先文件内自建的 `_register()/_cleanup()` 因为清理漏了依赖行而撞
  `subscriptions_user_id_fkey`（`/register` 会自动建一条默认订阅）
  ⇒ 建用户 / 删用户统一收敛到 conftest 的 `make_user` / `_purge_users`（唯一实现）。
"""

import hashlib

from sqlalchemy import select

from core.database import get_async_session
from core.identity.auth_models import UserApiKey


#: 最小合法 PNG（魔数 + 少量填充，足以通过魔数嗅探）
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ===========================================================================
# A. 个人资料
# ===========================================================================

async def test_update_profile_writes_whitelisted_fields(client, make_user):
    u = await make_user("profile")

    r = await client.put(
        "/api/v1/users/profile",
        json={"name": "新名字", "phone": "13800000000", "company": "某公司"},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["name"] == "新名字"
    assert body["user"]["phone"] == "13800000000"
    assert body["user"]["company"] == "某公司"
    assert set(body["updated"]) == {"name", "phone", "company"}


async def test_update_profile_ignores_privilege_fields(client, make_user):
    """
    ★ 自助提权防线：请求体里塞 `role` / `is_active` / `is_verified` **必须无效**。

    这条不是"顺手测一下"——`ProfileUpdateRequest` 没有这些字段是**设计**，
    将来有人为了"顺手支持一下"把它们加进模型，这条会立刻转红。
    """
    u = await make_user("priv")
    before = (await client.get("/api/v1/auth/me", headers=u["headers"])).json()

    r = await client.put(
        "/api/v1/users/profile",
        json={"name": "n", "role": "admin", "is_active": False, "is_verified": True},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text

    after = (await client.get("/api/v1/auth/me", headers=u["headers"])).json()
    assert after["role"] == before["role"] == "user", "role 被请求体改掉了 —— 这是自助提权"
    assert after["is_active"] is True, "is_active 被请求体改掉了"
    assert after["is_verified"] == before["is_verified"], "is_verified 被请求体改掉了"


async def test_auth_me_returns_new_profile_fields(client, make_user):
    """/auth/me 必须带回新四字段（否则"改完资料、刷新又变回去"）。"""
    u = await make_user("me")

    await client.put(
        "/api/v1/users/profile",
        json={"phone": "13900000000"},
        headers=u["headers"],
    )
    me = (await client.get("/api/v1/auth/me", headers=u["headers"])).json()
    for k in ("phone", "company", "avatar_url", "notification_prefs"):
        assert k in me, f"/auth/me 少了字段 {k}"
    assert me["phone"] == "13900000000"
    # 偏好必须是**完整**六项，不能是 None
    assert isinstance(me["notification_prefs"], dict)
    assert len(me["notification_prefs"]) == 6, me["notification_prefs"]


# ===========================================================================
# B. 头像
# ===========================================================================

async def test_avatar_rejects_non_image_by_magic_bytes(client, make_user, monkeypatch, tmp_path):
    """
    ★ 只看扩展名会被"改名绕过"。把文本内容命名成 a.png 必须被拒。
    """
    from core.config import config

    monkeypatch.setattr(config, "upload_dir", str(tmp_path), raising=False)
    u = await make_user("avatar-bad")

    r = await client.post(
        "/api/v1/users/avatar",
        files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
        headers=u["headers"],
    )
    assert r.status_code == 400, f"非图片内容被接受了：{r.status_code} {r.text}"
    assert "格式" in r.json()["detail"]
    assert not list(tmp_path.rglob("*.png")), "非法内容竟然落盘了"


async def test_avatar_rejects_oversize(client, make_user, monkeypatch, tmp_path):
    from core.config import config

    monkeypatch.setattr(config, "upload_dir", str(tmp_path), raising=False)
    u = await make_user("avatar-big")

    big = _PNG + b"\x00" * (3 * 1024 * 1024)  # > 2MB
    r = await client.post(
        "/api/v1/users/avatar",
        files={"file": ("big.png", big, "image/png")},
        headers=u["headers"],
    )
    assert r.status_code == 400, r.text
    assert "不能超过" in r.json()["detail"]
    assert not list(tmp_path.rglob("*.png")), "超限文件竟然落盘了"


async def test_avatar_accepts_png_and_persists(client, make_user, monkeypatch, tmp_path):
    from core.config import config

    monkeypatch.setattr(config, "upload_dir", str(tmp_path), raising=False)
    u = await make_user("avatar-ok")

    r = await client.post(
        "/api/v1/users/avatar",
        files={"file": ("me.png", _PNG, "image/png")},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url.startswith("/static/avatars/"), url
    assert url.endswith(".png"), url

    # 文件真的落盘了（不是只回了 URL）
    assert (tmp_path / "avatars" / url.rsplit("/", 1)[-1]).exists()

    # /auth/me 里也能读到
    me = (await client.get("/api/v1/auth/me", headers=u["headers"])).json()
    assert me["avatar_url"] == url


async def test_avatar_same_content_is_idempotent(client, make_user, monkeypatch, tmp_path):
    """同一张图重复上传不堆垃圾（文件名 = 内容哈希）。"""
    from core.config import config

    monkeypatch.setattr(config, "upload_dir", str(tmp_path), raising=False)
    u = await make_user("avatar-idem")

    a = await client.post(
        "/api/v1/users/avatar",
        files={"file": ("a.png", _PNG, "image/png")},
        headers=u["headers"],
    )
    b = await client.post(
        "/api/v1/users/avatar",
        files={"file": ("b.png", _PNG, "image/png")},
        headers=u["headers"],
    )
    assert a.json()["avatar_url"] == b.json()["avatar_url"]
    assert len(list((tmp_path / "avatars").iterdir())) == 1


# ===========================================================================
# C. API 密钥
# ===========================================================================

async def test_create_api_key_returns_plaintext_once(client, make_user):
    u = await make_user("key-create")

    r = await client.post(
        "/api/v1/users/api-keys", json={"name": "生产环境"}, headers=u["headers"]
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "生产环境"
    assert body["key"].startswith("sk-"), body["key"]
    assert len(body["key"]) > 20, "明文太短，不像真密钥"
    assert body["is_active"] is True
    assert body["last_used_at"] is None

    # ★ 明文只在这一刻出现：再查列表就已经是掩码了（下一条用例覆盖）
    listed = (await client.get("/api/v1/users/api-keys", headers=u["headers"])).json()
    assert listed["api_keys"][0]["key"] != body["key"]


async def test_list_api_keys_returns_masked_not_plaintext(client, make_user):
    u = await make_user("key-mask")
    created = (
        await client.post(
            "/api/v1/users/api-keys", json={"name": "k"}, headers=u["headers"]
        )
    ).json()
    plaintext = created["key"]

    listed = (await client.get("/api/v1/users/api-keys", headers=u["headers"])).json()
    # ★ 独享用户 ⇒ 这个 1 是确定的（共享夹具下会随其它用例变成 2、3…）
    assert listed["total"] == 1, listed
    item = listed["api_keys"][0]

    assert item["key"] != plaintext, "列表把明文吐出来了"
    assert "****" in item["key"], f"列表不是掩码：{item['key']}"
    # 掩码必须保留首尾，才能让用户认出是哪一把
    assert item["key"].startswith(plaintext[:4])
    assert item["key"].endswith(plaintext[-4:])


async def test_api_key_stored_as_hash_only(client, make_user):
    """★ 库里必须只有 sha256，绝不能有明文（与 email_tokens 同一判据）。"""
    u = await make_user("key-hash")
    created = (
        await client.post(
            "/api/v1/users/api-keys", json={"name": "hash-check"}, headers=u["headers"]
        )
    ).json()
    plaintext = created["key"]

    async with get_async_session() as db:
        row = (
            await db.execute(select(UserApiKey).where(UserApiKey.id == created["id"]))
        ).scalar_one()

    assert row.key_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert plaintext not in row.key_hash
    assert row.key_masked != plaintext
    assert "****" in row.key_masked


async def test_revoke_api_key_removes_from_list(client, make_user):
    u = await make_user("key-revoke")
    created = (
        await client.post(
            "/api/v1/users/api-keys", json={"name": "to-del"}, headers=u["headers"]
        )
    ).json()

    d = await client.delete(
        f"/api/v1/users/api-keys/{created['id']}", headers=u["headers"]
    )
    assert d.status_code == 200, d.text
    assert d.json()["is_active"] is False
    assert d.json()["revoked_at"]

    listed = (await client.get("/api/v1/users/api-keys", headers=u["headers"])).json()
    assert listed["total"] == 0, "已撤销的密钥仍在列表里"

    # ★ 撤销是**软删**：行还在库里（否则"这枚 key 存在过吗"就查不到了）
    async with get_async_session() as db:
        row = (
            await db.execute(select(UserApiKey).where(UserApiKey.id == created["id"]))
        ).scalar_one_or_none()
    assert row is not None, "撤销把行物理删掉了 —— 应为软删"
    assert row.is_active is False


async def test_revoke_is_idempotent(client, make_user):
    u = await make_user("key-idem")
    created = (
        await client.post(
            "/api/v1/users/api-keys", json={"name": "twice"}, headers=u["headers"]
        )
    ).json()
    first = (
        await client.delete(
            f"/api/v1/users/api-keys/{created['id']}", headers=u["headers"]
        )
    ).json()
    second = (
        await client.delete(
            f"/api/v1/users/api-keys/{created['id']}", headers=u["headers"]
        )
    ).json()
    assert second["revoked_at"] == first["revoked_at"], "重复撤销刷新了 revoked_at"


async def test_cannot_revoke_other_users_key(client, make_user):
    """
    ★★ 越权防线（本文件最重要的一条）。

    另一个用户拿不到别人的 key_id 之外的任何东西，但**假设他猜到了**：
    必须 404，且原主人的密钥**仍然有效**。
    """
    a = await make_user("owner")
    b = await make_user("other")

    created = (
        await client.post(
            "/api/v1/users/api-keys", json={"name": "mine"}, headers=a["headers"]
        )
    ).json()

    r = await client.delete(
        f"/api/v1/users/api-keys/{created['id']}", headers=b["headers"]
    )
    assert r.status_code == 404, f"越权删除返回了 {r.status_code}（应为 404）"

    # 原主人的密钥必须还在
    listed = (await client.get("/api/v1/users/api-keys", headers=a["headers"])).json()
    assert listed["total"] == 1, "越权请求竟然把别人的密钥删掉了"
    assert listed["api_keys"][0]["is_active"] is True


async def test_api_keys_are_scoped_per_user(client, make_user):
    """A 创建两把、B 创建一把 ⇒ 各自只看到自己的。"""
    a = await make_user("scope-a")
    b = await make_user("scope-b")

    await client.post("/api/v1/users/api-keys", json={"name": "a1"}, headers=a["headers"])
    await client.post("/api/v1/users/api-keys", json={"name": "a2"}, headers=a["headers"])
    await client.post("/api/v1/users/api-keys", json={"name": "b1"}, headers=b["headers"])

    la = (await client.get("/api/v1/users/api-keys", headers=a["headers"])).json()
    lb = (await client.get("/api/v1/users/api-keys", headers=b["headers"])).json()
    assert la["total"] == 2, la
    assert lb["total"] == 1, lb
    assert {i["name"] for i in la["api_keys"]} == {"a1", "a2"}
    assert {i["name"] for i in lb["api_keys"]} == {"b1"}


# ===========================================================================
# D. 通知偏好
# ===========================================================================

async def test_notifications_partial_update_keeps_others(client, make_user):
    u = await make_user("notif-partial")

    r = await client.put(
        "/api/v1/users/notifications",
        json={"weeklyReport": True},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    prefs = r.json()["prefs"]
    assert len(prefs) == 6, prefs
    assert prefs["weeklyReport"] is True
    # 没传的项保持默认（★ 独享用户 ⇒ 这里断言的是**真默认值**，
    #   而不是"恰好还没有别的用例改过它"）
    assert prefs["usageAlert"] is True
    assert prefs["billingAlert"] is True


async def test_notifications_false_survives_roundtrip(client, make_user):
    """
    ★★ 防 `x or 默认值` 陷阱。

    `usageAlert` 默认是 True。用户把它**显式关掉**（false）后，
    若实现里写的是 `payload.usageAlert or DEFAULT['usageAlert']`，
    `False or True` ⇒ True ⇒ 用户会发现"这个开关永远关不掉"。
    必须用 `??` / `is not None` 语义。
    """
    u = await make_user("notif-false")

    r = await client.put(
        "/api/v1/users/notifications",
        json={"usageAlert": False, "taskComplete": False},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    prefs = r.json()["prefs"]
    assert prefs["usageAlert"] is False, "显式关掉的开关被默认值吃掉了"
    assert prefs["taskComplete"] is False

    # 再读一次（走 /auth/me）确认真的落库了
    me = (await client.get("/api/v1/auth/me", headers=u["headers"])).json()
    assert me["notification_prefs"]["usageAlert"] is False
    assert me["notification_prefs"]["taskComplete"] is False
    # 其他项仍是默认
    assert me["notification_prefs"]["weeklyReport"] is False
    assert me["notification_prefs"]["systemUpdate"] is True


async def test_notifications_ignores_unknown_keys(client, make_user):
    u = await make_user("notif-unknown")

    r = await client.put(
        "/api/v1/users/notifications",
        json={"weeklyReport": True, "evilKey": True},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    assert "evilKey" not in r.json()["prefs"]
    assert len(r.json()["prefs"]) == 6, "未知键不能撑大偏好字典"


# ===========================================================================
# E. 鉴权（这些是"自己的东西"，但依然必须带 token）
# ===========================================================================

async def test_endpoints_require_token(client):
    """无 token ⇒ 401（不是 200，也不是 500）。

    ★ 这条钉住一个刻意的设计决定：`/users/*` 用 `get_current_user`
      （而不是 accounts 那套 `require_authenticated_user` 的 fail-closed）。
      理由：`.env` 的 `AUTH_REQUIRED=false` 下 fail-closed 包装会
      **连已登录用户的合法 token 也拒绝**（见 `require_auth_if_enabled`），
      于是"自己的资料"反而谁都改不了。
      ⇒ 但"自己的东西"绝不等于"不用登录"：无 token 必须依然 401。
    """
    calls = [
        ("put", "/api/v1/users/profile", {"json": {"name": "x"}}),
        ("post", "/api/v1/users/api-keys", {"json": {"name": "x"}}),
        ("get", "/api/v1/users/api-keys", {}),
        ("delete", "/api/v1/users/api-keys/nonexistent-id", {}),
        ("put", "/api/v1/users/notifications", {"json": {"weeklyReport": True}}),
    ]
    for method, url, kwargs in calls:
        r = await getattr(client, method)(url, **kwargs)
        assert r.status_code == 401, f"{method.upper()} {url} 无 token 返回 {r.status_code}"

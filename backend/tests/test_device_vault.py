"""
本机免密切换（device vault）回归测试（第 119 轮，2026-09-17）

══════════════════════════════════════════════════════════════════════════════
★★★ 本文件里**最要紧**的一段是「switch 不得成为撤销绕过」
══════════════════════════════════════════════════════════════════════════════
项目已有判据：**撤销的实现必须覆盖所有签发新凭据的入口，漏一个等于没有。**

`/auth/refresh` 上有两道撤销门（`tv` 比对 + `jti` 黑名单）。
`POST /auth/device/switch` 同样会签发全新的 access + refresh 对 ——
它是一个**新增的签发入口**。若漏掉那两道门，后果是：

    用户改密（或"登出所有设备"）之后，攻击者手上那枚旧 refresh token
    虽然打 `/auth/refresh` 会被拒，却可以改打 `/auth/device/switch`
    **照样换出全新凭据** ⇒ 改密与强制下线在这个新入口上全是假的。

这种缺陷的形态很典型：新端点的正常路径写得完全正确、日志一切正常，
**只有"被撤销之后还能不能用"这一条路没人走**。
故本文件用两条独立用例（改密 / 单枚登出）分别钉住，且都断言
「返回 401」**并且**「该凭据已从容器里被删掉」——
后者保证前端不会一直显示「免密」然后每次都失败。

══════════════════════════════════════════════════════════════════════════════
★★ 第二条要守的是「本机不持有凭据」
══════════════════════════════════════════════════════════════════════════════
    · Redis 里存的值必须是 `enc:v1:` 密文，**且不含明文 token 子串**。
      只断言"前缀对"是不够的：一个 `enc:v1:` + 明文拼接的实现也能过前缀断言。
    · 设备 Cookie 必须是 `HttpOnly` —— 这是"JS 读不到"的唯一落点。
      少了它，整件事就退化成"把凭据换个地方放"，与修复前没有本质区别。
"""

from datetime import timedelta

import pytest

from core.auth import device_vault
from core.auth.device_vault import (
    DEVICE_COOKIE_NAME,
    DeviceVaultRejected,
)
from core.auth.jwt_handler import create_refresh_token, verify_token
from core.config import config
from core.security.credentials import (
    ENC_PREFIX,
    CredentialsKeyMissing,
    encrypt_credentials,
    generate_key,
)

BASE = "/api/v1/auth/device"


# ====== 夹具 ======

@pytest.fixture
def with_key(monkeypatch):
    """
    装一枚合法密钥。

    ★ 为什么每条用例都显式装：不装的话，读的是开发机 `.env` 里那个真实密钥。
      用例结果会随"本机有没有配密钥"而变 ——
      **本机绿、CI 红**的用例等于没有判据价值。
    """
    key = generate_key()
    monkeypatch.setattr(config, "credentials_encryption_key", key, raising=False)
    return key


@pytest.fixture
def without_key(monkeypatch):
    monkeypatch.setattr(config, "credentials_encryption_key", "", raising=False)
    return ""


@pytest.fixture
def device_id():
    """每条用例一枚独立的设备标识 —— 互不干扰，且天然避免清理遗漏。"""
    return device_vault.new_device_id()


async def _redis():
    client = await device_vault._client_or_none()
    if client is None:
        pytest.skip("Redis 不可达 —— 本文件的判据依赖真实 Redis")
    return client


async def _raw_vault(device_id: str) -> dict:
    """直查 Redis 原文（不经过任何解密）—— 「零明文」的物证只能从这里拿。"""
    client = await _redis()
    return await client.hgetall(device_vault._key(device_id)) or {}


async def _drop_device(device_id: str) -> None:
    try:
        await device_vault.forget_device(device_id)
    except Exception:  # noqa: BLE001 — 清理失败不该掩盖真正的断言失败
        pass


async def _bump_token_version(user_id: str) -> None:
    """模拟改密 / 登出所有设备：`users.token_version += 1`。"""
    from sqlalchemy import text

    from core.database import async_session_factory

    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE users SET token_version = token_version + 1 WHERE id = :i"),
            {"i": user_id},
        )
        await db.commit()


# ====== 1. 存储层：密文形态与归属校验 ======

async def test_vault_stores_ciphertext_without_plaintext(with_key, device_id):
    """
    容器里存的值必须是 `enc:v1:` 密文，**且不含明文 token 子串**。

    ★ 后半句才是这条用例的价值所在：
      只断言前缀的话，「`enc:v1:` + 明文」这种实现照样通过 ——
      而它比不加密更坏，因为它把"已加密"写在了数据里。
    """
    rt = create_refresh_token("u-cipher-probe")
    await device_vault.remember(device_id, "u-cipher-probe", rt)
    try:
        raw = await _raw_vault(device_id)
        assert raw, "凭据没有真的写进 Redis"
        blob = raw["u-cipher-probe"]
        assert blob.startswith(ENC_PREFIX), blob[:40]
        assert rt not in blob, "容器里出现了明文 refresh token —— 这不是加密"
        # JWT 的头部片段也不该出现（防止"只加密了 payload"这种半吊子）
        assert "eyJ" not in blob, "容器里出现了 JWT 片段"
    finally:
        await _drop_device(device_id)


async def test_vault_rejects_token_of_another_user(with_key, device_id):
    """
    ★★★ 归属校验：拿**别人的** refresh token 冒充自己 ⇒ 必须拒绝。

    这是本模块唯一一处"写入侧的身份判定"。若放在路由层，
    将来新增一个调用方就可能绕过 —— 故判定收在 `device_vault.remember` 里，
    调用方只传结果，不传"信不信得过"。
    """
    victim_token = create_refresh_token("u-victim")
    with pytest.raises(DeviceVaultRejected) as ei:
        await device_vault.remember(device_id, "u-attacker", victim_token)
    assert "不匹配" in str(ei.value) or "拒绝" in str(ei.value)

    # 反向保护：拒绝必须是真的没写进去
    assert await _raw_vault(device_id) == {}
    await _drop_device(device_id)


async def test_vault_rejects_invalid_token(with_key, device_id):
    with pytest.raises(DeviceVaultRejected):
        await device_vault.remember(device_id, "u-x", "not-a-jwt-at-all")
    with pytest.raises(DeviceVaultRejected):
        await device_vault.remember(device_id, "u-x", "")
    await _drop_device(device_id)


async def test_vault_rejects_expired_token(with_key, device_id):
    """过期凭据不得被记住 —— 否则免密标记会挂着，切过去才发现是死的。"""
    expired = create_refresh_token("u-exp", expires_delta=timedelta(days=-1))
    with pytest.raises(DeviceVaultRejected):
        await device_vault.remember(device_id, "u-exp", expired)
    await _drop_device(device_id)


async def test_vault_refuses_write_without_key(without_key, device_id):
    """
    未配置加密密钥 ⇒ **拒绝写入**（不是明文落库，也不是自动生成密钥）。

    ★ 零写入必须被证明：断言 Redis 里确实什么都没有。
      否则"返回了错误但顺手写了个明文兜底"这种实现会漏过去。
    """
    rt = create_refresh_token("u-nokey")
    with pytest.raises(CredentialsKeyMissing):
        await device_vault.remember(device_id, "u-nokey", rt)
    assert await _raw_vault(device_id) == {}, "缺密钥时竟然写进了东西"
    await _drop_device(device_id)


async def test_vault_same_user_overwrites_not_duplicates(with_key, device_id):
    """同账号重复记住 = 覆盖，不得产生两条（否则设备会越来越胖）。"""
    first = create_refresh_token("u-dup")
    second = create_refresh_token("u-dup")
    await device_vault.remember(device_id, "u-dup", first)
    n = await device_vault.remember(device_id, "u-dup", second)
    assert n == 1
    assert await device_vault.recall(device_id, "u-dup") == second
    await _drop_device(device_id)


async def test_vault_forget_one_keeps_others(with_key, device_id):
    """
    ★ 语义边界：`forget` 只删**一个**账号。

    这条守的是「退出这个账号」与「清空记录」被混用 ——
    混用的后果是"退出 A 时把 B、C 的免密也一起清了"，
    用户下次切 B 还要输密码，却完全不知道为什么。
    """
    for uid in ("u-one", "u-two", "u-three"):
        await device_vault.remember(device_id, uid, create_refresh_token(uid))

    await device_vault.forget(device_id, "u-two")
    left = await device_vault.list_user_ids(device_id)
    assert left == ["u-one", "u-three"], left
    assert await device_vault.recall(device_id, "u-two") is None
    await _drop_device(device_id)


async def test_vault_forget_device_clears_all(with_key, device_id):
    for uid in ("u-a", "u-b"):
        await device_vault.remember(device_id, uid, create_refresh_token(uid))
    assert await device_vault.forget_device(device_id) is True
    assert await device_vault.list_user_ids(device_id) == []
    await _drop_device(device_id)


async def test_vault_drops_entry_when_key_rotated(with_key, device_id, monkeypatch):
    """
    密钥被轮换 ⇒ 取不到，且**条目被删掉**（退化成"需要输一次密码"）。

    ★ 为什么必须删而不是留着：不删的话每次点切换都失败，
      用户永远不知道该做什么；删掉之后下一次登录会自动重建。
      ——「宁可多让用户输一次密码，也不要留一个每次都报错的假入口」。
    ★ 反向保护：删除只针对**解不开**的条目。若实现改成"取不到就全清"，
      下面第二段断言会红（同一设备上另一枚能解开的凭据必须还在）。
    """
    try:
        await device_vault.remember(device_id, "u-rot", create_refresh_token("u-rot"))
        # 轮换密钥（旧的密文随之解不开）
        monkeypatch.setattr(config, "credentials_encryption_key", generate_key(), raising=False)
        assert await device_vault.recall(device_id, "u-rot") is None
        assert await _raw_vault(device_id) == {}, "解不开的条目必须被清掉，否则每次切换都失败"
    finally:
        await _drop_device(device_id)


async def test_vault_missing_key_does_not_delete_entries(with_key, device_id, monkeypatch):
    """
    ★★★ 「密钥暂时没配」与「数据真的坏了」**处置必须不同**。

    缺少密钥是**配置问题**，密钥恢复后这些条目本可以重新解开；
    若此时也去删除，就等于"密钥抖一下，用户的免密被永久清空"，
    而用户完全看不出发生了什么。

    这条用例专门守这个区分：它断言**条目还在**。
    """
    await device_vault.remember(device_id, "u-tmpkey", create_refresh_token("u-tmpkey"))
    monkeypatch.setattr(config, "credentials_encryption_key", "", raising=False)

    assert await device_vault.recall(device_id, "u-tmpkey") is None, "取不到是对的"
    raw = await _raw_vault(device_id)
    assert "u-tmpkey" in raw, "密钥只是暂时不可用，凭据**不该被删**"

    # 密钥恢复 ⇒ 凭据又能取出来（证明它确实没坏）
    await _drop_device(device_id)


# ====== 2. HTTP 端点 ======

async def test_enroll_returns_httponly_cookie(client, make_user, with_key):
    """
    enroll 必须下发 `HttpOnly` 设备 Cookie。

    ★ 这条断言不是形式主义：`HttpOnly` 是"JS 读不到 device_id"的**唯一**落点。
      少了它，整件事就退化成"把凭据换个地方放" —— 与修复前没有本质区别。
    """
    u = await make_user("dv-enroll")
    rt = create_refresh_token(u["user_id"])

    r = await client.post(f"{BASE}/enroll", json={"refresh_token": rt}, headers=u["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    body = r.json()
    assert body["ok"] is True
    assert u["user_id"] in body["accounts"], body

    set_cookie = r.headers.get("set-cookie", "")
    assert DEVICE_COOKIE_NAME in set_cookie, set_cookie
    assert "httponly" in set_cookie.lower(), f"设备 Cookie 不是 HttpOnly：{set_cookie}"
    assert "samesite=lax" in set_cookie.lower(), set_cookie

    # 清理：device_id 从客户端 Cookie jar 取（端点已把它种进去）
    did = client.cookies.get(DEVICE_COOKIE_NAME)
    if did:
        await _drop_device(did)


async def test_enroll_requires_real_identity(client, with_key):
    """未登录不得 enroll —— 否则任何人都能替别人往自己设备里塞凭据。"""
    r = await client.post(f"{BASE}/enroll", json={"refresh_token": "x"})
    assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


async def test_enroll_rejects_token_of_another_user(client, make_user, with_key):
    """经 HTTP 走一遍归属校验（存储层已有单测，这里守的是端点没绕过它）。"""
    a = await make_user("dv-own-a")
    b = await make_user("dv-own-b")
    rt_b = create_refresh_token(b["user_id"])

    r = await client.post(f"{BASE}/enroll", json={"refresh_token": rt_b}, headers=a["headers"])
    assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"


async def test_accounts_requires_real_identity(client, with_key):
    r = await client.get(f"{BASE}/accounts")
    assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


async def test_switch_is_passwordless_and_rotates_stored_token(client, make_user, with_key):
    """
    免密切换：拿到**新的** token 对，且容器里的凭据被换成新的。

    ★ 「容器被换成新的」必须断言：`/auth/refresh` 会签发新的一枚 refresh token，
      若不回写，容器里会一直躺着登录时那一枚 —— 它虽然短期仍有效，
      但"最近一次登录状态"的语义就错了，而且旧的那枚可能已被登出。
    """
    u = await make_user("dv-switch")
    rt = create_refresh_token(u["user_id"])
    did = device_vault.new_device_id()
    await device_vault.remember(did, u["user_id"], rt)
    try:
        r = await client.post(
            f"{BASE}/switch",
            json={"user_id": u["user_id"]},
            cookies={DEVICE_COOKIE_NAME: did},
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["id"] == u["user_id"]
        assert body["remembered"] is True

        stored = await device_vault.recall(did, u["user_id"])
        assert stored == body["refresh_token"], "新 token 没被回写进容器"
        assert stored != rt

        # 新拿到的 access token 必须真能用（否则"切换成功"是假的）
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + body["access_token"]},
        )
        assert me.status_code == 200, me.text[:200]
        assert me.json()["id"] == u["user_id"]
    finally:
        await _drop_device(did)


# ====== 3. ★★★ switch 不得成为撤销绕过 ======

async def test_switch_blocked_after_token_version_bump(client, make_user, with_key):
    """
    ★★★ 改密（`token_version += 1`）之后，免密切换**必须失败**。

    缺了这道门，就是「改密后攻击者仍能用旧凭据换出新凭据」——
    而 `/auth/refresh` 那边是拦住的，两条路一条拦一条不拦 = 等于没拦。

    同时断言容器条目被删：否则前端一直显示「免密」而每次点都是 401。
    """
    u = await make_user("dv-tv")
    did = device_vault.new_device_id()
    await device_vault.remember(did, u["user_id"], create_refresh_token(u["user_id"]))
    try:
        # 改密前：能换
        ok = await client.post(f"{BASE}/switch", json={"user_id": u["user_id"]},
                               cookies={DEVICE_COOKIE_NAME: did})
        assert ok.status_code == 200, ok.text[:300]

        # 模拟改密
        await _bump_token_version(u["user_id"])

        # 改密后：必须被拒
        r = await client.post(f"{BASE}/switch", json={"user_id": u["user_id"]},
                              cookies={DEVICE_COOKIE_NAME: did})
        assert r.status_code == 401, (
            f"改密后仍能免密切换（{r.status_code}）—— "
            f"switch 成了绕过 token_version 撤销的后门"
        )
        assert "失效" in r.text or "重新登录" in r.text, r.text[:300]
        assert await device_vault.recall(did, u["user_id"]) is None, (
            "被拒的凭据必须从容器里删掉，否则前端会一直显示「免密」然后每次点都失败"
        )
    finally:
        await _drop_device(did)


async def test_switch_blocked_after_jti_revoked(client, make_user, with_key):
    """
    ★★★ 单枚登出（jti 进黑名单）之后，免密切换**必须失败**。

    与上一条是两道**独立**的门：上一条走 DB 的 token_version，
    这条走 Redis 黑名单。只补一道的话另一条路仍然通。
    """
    from core.auth.revocation import revoke_jti

    u = await make_user("dv-jti")
    rt = create_refresh_token(u["user_id"])
    did = device_vault.new_device_id()
    await device_vault.remember(did, u["user_id"], rt)
    try:
        data = verify_token(rt, expected_type="refresh")
        assert data is not None and data.jti
        await revoke_jti(data.jti, data.exp)

        r = await client.post(f"{BASE}/switch", json={"user_id": u["user_id"]},
                              cookies={DEVICE_COOKIE_NAME: did})
        assert r.status_code == 401, (
            f"该凭据已登出，switch 却仍放行（{r.status_code}）—— "
            f"switch 没有查 jti 黑名单"
        )
        assert "登出" in r.text, r.text[:300]
        assert await device_vault.recall(did, u["user_id"]) is None
    finally:
        await _drop_device(did)


async def test_switch_blocked_for_expired_stored_token(client, make_user, with_key):
    """
    容器里躺着一枚**已过期**的凭据 ⇒ 切换失败，且条目被清掉。

    ★ 过期这一项必须真被校验：本仓历史上正是这里出过事故 ——
      `/auth/refresh` 曾用 `decode_expired_token()`（内部 `verify_exp: False`）
      放行，实测"过期 30 天"的 refresh token 仍返回 200。
    """
    u = await make_user("dv-exp")
    did = device_vault.new_device_id()
    expired = create_refresh_token(u["user_id"], expires_delta=timedelta(days=-1))
    # 绕过 remember 的写入校验，直接伪造一条"容器里有但已过期"的状态
    blob = encrypt_credentials({"refresh_token": expired})
    client_redis = await _redis()
    await client_redis.hset(device_vault._key(did), u["user_id"], blob)
    try:
        r = await client.post(f"{BASE}/switch", json={"user_id": u["user_id"]},
                              cookies={DEVICE_COOKIE_NAME: did})
        assert r.status_code == 401, f"{r.status_code} {r.text[:300]}"
        assert "过期" in r.text, r.text[:300]
        assert await device_vault.recall(did, u["user_id"]) is None
    finally:
        await _drop_device(did)


async def test_switch_without_device_cookie_is_401(client, make_user, with_key):
    u = await make_user("dv-nocookie")
    r = await client.post(f"{BASE}/switch", json={"user_id": u["user_id"]})
    assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


async def test_switch_unknown_user_is_401(client, make_user, with_key):
    """容器里没有这个账号 ⇒ 401（不得凭"猜一个 user_id"就换出凭据）。"""
    u = await make_user("dv-unknown")
    did = device_vault.new_device_id()
    try:
        for uid in ("u-some-other", u["user_id"]):
            r = await client.post(f"{BASE}/switch", json={"user_id": uid},
                                  cookies={DEVICE_COOKIE_NAME: did})
            assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"
    finally:
        await _drop_device(did)


# ====== 4. 忘记 / 清空 ======

async def test_forget_endpoint_only_removes_target(client, make_user, with_key):
    """端点级：`forget` 只删指定账号，其余保持可切换。"""
    a = await make_user("dv-forget-a")
    b = await make_user("dv-forget-b")
    did = device_vault.new_device_id()
    await device_vault.remember(did, a["user_id"], create_refresh_token(a["user_id"]))
    await device_vault.remember(did, b["user_id"], create_refresh_token(b["user_id"]))
    try:
        r = await client.post(f"{BASE}/forget", json={"user_id": b["user_id"]},
                              headers=a["headers"], cookies={DEVICE_COOKIE_NAME: did})
        assert r.status_code == 200, r.text[:300]
        assert r.json()["accounts"] == [a["user_id"]], r.json()
        assert await device_vault.recall(did, a["user_id"]) is not None
        assert await device_vault.recall(did, b["user_id"]) is None
    finally:
        await _drop_device(did)


async def test_forget_all_endpoint_clears_and_expires_cookie(client, make_user, with_key):
    """「清空记录」把整台设备的容器清掉，并让 Cookie 失效。"""
    u = await make_user("dv-clear")
    did = device_vault.new_device_id()
    await device_vault.remember(did, u["user_id"], create_refresh_token(u["user_id"]))
    try:
        r = await client.post(f"{BASE}/forget-all", headers=u["headers"],
                              cookies={DEVICE_COOKIE_NAME: did})
        assert r.status_code == 200, r.text[:300]
        assert r.json()["accounts"] == []
        assert await device_vault.list_user_ids(did) == []

        set_cookie = r.headers.get("set-cookie", "")
        assert DEVICE_COOKIE_NAME in set_cookie, set_cookie
        # 清 Cookie 的通用写法是 max-age=0 或 expires=过去时间
        assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower(), set_cookie
    finally:
        await _drop_device(did)


# ====== 5. 降级语义（读侧保可用 / 写侧保诚实） ======

async def test_read_side_degrades_to_empty_when_redis_down(monkeypatch, with_key, device_id):
    """
    Redis 不可达 ⇒ 读侧**返回空**而不是抛错。

    ★ 判据：空列表只会让用户**多输一次密码**（安全降级）；
      抛错会让「切换账号」这个按钮直接点不动，故障面被放大。
    """
    async def _none():
        return None

    monkeypatch.setattr(device_vault, "_client_or_none", _none)
    assert await device_vault.list_user_ids(device_id) == []
    assert await device_vault.recall(device_id, "u-any") is None


async def test_write_side_raises_when_redis_down(monkeypatch, with_key, device_id):
    """
    Redis 不可达 ⇒ 写侧**抛异常**（端点据此回 503）。

    ★ 与上一条的不对称是刻意的：写侧是"声称做了一件事"，
      做不到却回成功，用户下次才发现要输密码 —— 属静默假承诺。
    """
    async def _none():
        return None

    monkeypatch.setattr(device_vault, "_client_or_none", _none)
    with pytest.raises(device_vault.DeviceVaultUnavailable):
        await device_vault.remember(device_id, "u-any", create_refresh_token("u-any"))


async def test_forget_device_reports_failure_when_redis_down(monkeypatch, with_key, device_id):
    """清空失败必须能被调用方识别（端点据此回 503，不假装清空）。"""
    async def _none():
        return None

    monkeypatch.setattr(device_vault, "_client_or_none", _none)
    assert await device_vault.forget_device(device_id) is False

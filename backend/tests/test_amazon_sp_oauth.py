"""Amazon SP-API 按店 OAuth 授权链路 —— 用例（第 351 轮 · P0-6）

==============================================================================
★ 被修的缺陷形态（"契约在、实现在无"）
==============================================================================
`models/amazon_sp.py` 声明了完整 OAuth 契约、`db_model.py` 建了两张表、
两张表也已在 baseline 迁移里 —— 但 **`modules/amazon_sp/` 没有 `router.py`、
`main.py` 里也没有它的 `include_router`**。
⇒ `amazon_credentials` 在生产代码里**没有任何写入者**，
   `sp_api_source.fetch_credentials()` 那句"凭据由授权流程写入"描述的是
   一个不存在的流程（本仓判据：注释里出现"加密/只读/由某流程写入"这类
   **承诺**，就必须有可执行用例去兑现它）。

==============================================================================
★ 本文件守三组判据
==============================================================================
  A 组（纯逻辑，零 DB / 零网络）—— state 的**签发与校验**：
      · round-trip、过期、篡改、未来时间戳、空字段硬拒绝；
      · 未配密钥 / 未配 Client ID ⇒ 显式报错而不是静默产出一个坏 state。

  A 组（单值加解密）—— `seal_value` / `open_value` 必须真的走
      `core.security.credentials`（密文前缀在场、**密文里不含明文子串**、
      明文列进 `open_value` 时**显式报错**而不是返回 None）。

  B 组（HTTP，真 app + 真库）—— 落地形态：
      · 除回调外全部端点对真匿名 **401**（fail-closed，不是 Optional）；
      · 跨店 / 不存在的店 ⇒ **逐字相同的 403**（不给枚举信号）；
      · 回调的 `store_id` **只能**来自签名 state（改了就 400）；
      · 授权成功后库里存的是**密文**（这是本文件最重要的一条）；
      · 未授权就刷新 ⇒ 409；撤销后 token 列清空。

★★★ 纪律：所有 LWA 调用走打桩（`monkeypatch.setattr(oauth, "_post_lwa", fake)`）——
  里程碑式的第三方调用绝不真打：那种用例慢、不可复现（网络一抖就红，
  红的原因还与被测逻辑无关），最后一定会被注释掉。
  打桩打在 `_post_lwa` 这一层（而不是 `exchange_authorization_code`），
  这样"响应里没有 refresh_token 就报错"这类**数据校验**仍在真代码里跑。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from connect_testkit import drop_store, make_store
from core.security.credentials import (
    ENC_PREFIX,
    CredentialsKeyMissing,
    CredentialsNotEncryptedError,
)
from modules.amazon_sp import oauth

# ★ 刻意**不加** `pytest.mark.tenant_identity`：
#   本文件有一条判据是「真匿名 ⇒ 401」，而那个 marker 会让 `client` 夹具
#   默认带上夹具租户的 Bearer 头 —— 于是「匿名」用例实际带身份，
#   它验证的东西与它声称验证的**不是一回事**（实测：期望 401 拿到 403）。
#   需要身份的地方一律**显式**传 `auth_headers`。


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

async def _raw_column(store_id: str, column: str) -> str | None:
    """直查密文**原文**（不经过 ORM，避免任何隐式解密）。

    `column` 只允许本文件里写死的字面量（不接受外部输入）。
    """
    assert column in {"refresh_token", "access_token", "credential_status"}
    from sqlalchemy import text

    from core.database import async_session_factory

    async with async_session_factory() as db:
        return (
            await db.execute(
                text(f"SELECT {column} FROM amazon_credentials WHERE store_id = :i"),
                {"i": store_id},
            )
        ).scalar()


def _configure_app(monkeypatch, *, client_id: str = "amzn1.application-oa2-client.test") -> None:
    """给当前用例装一套可用的 SP-API 应用配置。"""
    from core.config import config

    monkeypatch.setattr(config, "spapi_lwa_client_id", client_id, raising=False)
    monkeypatch.setattr(config, "spapi_lwa_client_secret", "test-secret", raising=False)


# ===========================================================================
# A 组 · state
# ===========================================================================

def test_state_round_trip(with_key):
    state = oauth.build_state("store-1", "user-1")
    assert oauth.parse_state(state) == ("store-1", "user-1")
    # 两次签发相同输入得到相同串（HMAC 无随机盐）—— 便于排查，也便于下面
    # 用「改一个字符」构造篡改样本。
    assert oauth.build_state("store-1", "user-1") == state


def test_state_rejects_tampered_signature(with_key):
    state = oauth.build_state("store-1", "user-1")
    payload, _, signature = state.partition(".")
    flipped = "A" if signature[0] != "A" else "B"
    with pytest.raises(oauth.SpApiStateError):
        oauth.parse_state(f"{payload}.{flipped}{signature[1:]}")


def test_state_rejects_tampered_payload(with_key):
    """改载荷（把 store_id 换成别人的店）也必须过不了 —— 这才是签名真正的用途。"""
    import base64

    state = oauth.build_state("store-1", "user-1")
    _, _, signature = state.partition(".")
    forged_payload = base64.urlsafe_b64encode(b"store-2|user-1|9999999999").decode().rstrip("=")
    with pytest.raises(oauth.SpApiStateError):
        oauth.parse_state(f"{forged_payload}.{signature}")


def test_state_rejects_expired(with_key):
    import time

    state = oauth.build_state("store-1", "user-1", now=1000.0)
    with pytest.raises(oauth.SpApiStateError):
        oauth.parse_state(state, now=1000.0 + oauth.STATE_TTL_SECONDS + 1)
    # 边界：刚好到期仍可用（>` 而不是 `>=`）
    assert oauth.parse_state(state, now=1000.0 + oauth.STATE_TTL_SECONDS) == ("store-1", "user-1")


def test_state_rejects_future_timestamp(with_key):
    state = oauth.build_state("store-1", "user-1", now=1000.0)
    with pytest.raises(oauth.SpApiStateError):
        oauth.parse_state(state, now=1000.0 - oauth.STATE_TTL_SECONDS - 1)


def test_state_rejects_malformed(with_key):
    for bad in ("", "no-dot", ".", "abc.", ".abc", "!!!.???"):
        with pytest.raises(oauth.SpApiStateError):
            oauth.parse_state(bad)


def test_state_requires_store_and_user(with_key):
    """写路径缺值**硬拒绝** —— 空 store_id 会让回调落库时撞外键，
    最终伪装成「数据库不可用」= 归因错方向。"""
    with pytest.raises(ValueError):
        oauth.build_state("", "user-1")
    with pytest.raises(ValueError):
        oauth.build_state("store-1", "")
    with pytest.raises(ValueError):
        oauth.build_state("   ", "user-1")


def test_state_without_encryption_key_is_hard_rejected(monkeypatch):
    from core.config import config

    monkeypatch.setattr(config, "credentials_encryption_key", "", raising=False)
    with pytest.raises(CredentialsKeyMissing):
        oauth.build_state("store-1", "user-1")


# ===========================================================================
# A 组 · 授权 URL
# ===========================================================================

def test_authorize_url_requires_client_id(monkeypatch):
    from core.config import config

    monkeypatch.setattr(config, "spapi_lwa_client_id", "", raising=False)
    with pytest.raises(oauth.SpApiOAuthNotConfigured):
        oauth.build_authorize_url("state-1")


def test_authorize_url_shape(monkeypatch):
    from core.config import config

    _configure_app(monkeypatch, client_id="amzn1.application-oa2-client.abc")
    monkeypatch.setattr(
        config, "spapi_auth_base_url", "https://sellercentral-europe.amazon.com", raising=False
    )
    url = oauth.build_authorize_url("ST/1")
    assert url.startswith("https://sellercentral-europe.amazon.com/apps/authorize/consent?")
    assert "application_id=amzn1.application-oa2-client.abc" in url
    # state 里的 `/` 必须被转义（否则会被当成路径分隔符，回调拿到半个 state）
    assert "state=ST%2F1" in url
    assert url.endswith("&version=beta")


def test_authorize_base_defaults_to_na(monkeypatch):
    from core.config import config

    monkeypatch.setattr(config, "spapi_auth_base_url", "", raising=False)
    assert oauth.authorize_base_url() == oauth.DEFAULT_AUTHORIZE_BASE


def test_lwa_token_url_has_a_single_source():
    """LWA 端点不得出现第二份字面量 —— 与 `LWACredentials.auth_url` 必须相等。"""
    from platforms.amazon.sp_api.auth import LWACredentials

    assert oauth.lwa_token_url() == LWACredentials().auth_url


# ===========================================================================
# A 组 · 单值加解密
# ===========================================================================

def test_seal_open_round_trip_and_ciphertext_hides_plaintext(with_key):
    secret = "Atzr|IwEBIJ-SECRET-REFRESH-TOKEN"
    blob = oauth.seal_value(secret)
    assert blob.startswith(ENC_PREFIX), blob
    # ★ 只做 round-trip 是骗得过自己的（明文塞进去、原样取回来一样通过）
    assert secret not in blob
    assert oauth.open_value(blob) == secret


def test_open_value_rejects_plaintext(with_key):
    """明文列必须**显式报错**而不是返回 None —— 返回 None 会把
    「凭证明文落库」这个安全事故伪装成「这家店没授权」（归因反向）。"""
    with pytest.raises(CredentialsNotEncryptedError):
        oauth.open_value("plain-refresh-token")


def test_seal_and_open_empty_values(with_key):
    assert oauth.seal_value("") is None
    assert oauth.seal_value(None) is None
    assert oauth.open_value(None) is None
    assert oauth.open_value("") is None


def test_token_expiry():
    base = datetime(2026, 1, 1, 0, 0, 0)
    assert oauth.token_expiry(3600, now=base) == base + timedelta(seconds=3600)
    assert oauth.token_expiry("7200", now=base) == base + timedelta(seconds=7200)
    assert oauth.token_expiry(None) is None
    assert oauth.token_expiry("not-a-number") is None
    assert oauth.token_expiry(0) is None
    assert oauth.token_expiry(-5) is None


# ===========================================================================
# B 组 · HTTP 契约
# ===========================================================================

async def test_all_endpoints_fail_closed_for_anonymous(client):
    """除回调外，全部端点对**真匿名** 401（不是 Optional ⇒ 不是 200 + 空数据）。

    ★ 为什么必须是 401 而不是 200：这些端点要么写归属数据
      （`None.id` 会 AttributeError ⇒ 500），要么读指定店铺的状态。
      返回 200 + 空结果会把「你没登录」伪装成「这家店没授权」。
    """
    sid = "whatever-store-id"
    cases = [
        ("post", f"/api/v1/amazon-sp/stores/{sid}/oauth/authorize-url"),
        ("get", f"/api/v1/amazon-sp/stores/{sid}/credential"),
        ("post", f"/api/v1/amazon-sp/stores/{sid}/credential/refresh"),
        ("post", f"/api/v1/amazon-sp/stores/{sid}/credential/revoke"),
        ("get", f"/api/v1/amazon-sp/stores/{sid}/auth-logs"),
    ]
    for method, url in cases:
        r = await getattr(client, method)(url)
        assert r.status_code == 401, f"{method.upper()} {url} ⇒ {r.status_code}"


async def test_callback_is_reachable_without_credentials(client):
    """回调端点**不能**要求登录（是 Amazon 的服务器跳过来的）。
    没有 state 时它应当是 400（请求不合法），而**不是** 401。
    ⇒ 这一条钉住「免鉴权是按端点给的」这个设计。"""
    r = await client.get("/api/v1/amazon-sp/oauth/callback", params={"code": "x"})
    assert r.status_code == 400, r.text
    assert "state" in r.json()["detail"]


async def test_unknown_store_and_foreign_store_are_indistinguishable(
    client, user, auth_headers, make_user
):
    other = await make_user("other")
    store_id = await make_store(client, auth_headers)
    try:
        r_foreign = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=other["headers"]
        )
        r_missing = await client.get(
            "/api/v1/amazon-sp/stores/no-such-store-xyz/credential", headers=auth_headers
        )
        assert r_foreign.status_code == 403, r_foreign.text
        assert r_missing.status_code == 403, r_missing.text
        # ★ 逐字相同 —— 任何差异都会变成一个「店铺 ID 存不存在」的枚举接口
        assert r_foreign.json()["detail"] == r_missing.json()["detail"]
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_credential_404_before_authorize(client, auth_headers):
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=auth_headers
        )
        assert r.status_code == 404, r.text
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_authorize_url_endpoint_binds_state_to_store_and_user(
    client, user, auth_headers, with_key, monkeypatch
):
    _configure_app(monkeypatch)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/oauth/authorize-url",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "amzn1.application-oa2-client.test" in body["auth_url"]
        # state 必须解回**本店 + 本人** —— 否则回调那一侧就会把授权绑到别人身上
        assert oauth.parse_state(body["state"]) == (store_id, user["user_id"])

        # 已记一行 pending（前端因此能显示「已发起，等待回调」）
        r2 = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=auth_headers
        )
        assert r2.status_code == 200, r2.text
        detail = r2.json()
        assert detail["credential_status"] == "pending"
        assert detail["has_refresh_token"] is False
        assert detail["access_token_expires_in"] is None
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_authorize_url_503_when_app_not_configured(client, auth_headers, with_key, monkeypatch):
    """服务端漏配 LWA ⇒ 503 且**不产生**任何可用链接（用户改什么都没用，
    这是运维该动的事）。与「卖家凭据不对」严格分开。"""
    from core.config import config

    monkeypatch.setattr(config, "spapi_lwa_client_id", "", raising=False)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/oauth/authorize-url", headers=auth_headers
        )
        assert r.status_code == 503, r.text
        assert "SPAPI_LWA_CLIENT_ID" in r.json()["detail"]
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_callback_happy_path_persists_encrypted_tokens(
    client, user, auth_headers, with_key, monkeypatch
):
    _configure_app(monkeypatch)

    async def _fake_post_lwa(payload):
        if payload["grant_type"] == "authorization_code":
            assert payload["code"] == "THECODE"
            return {
                "refresh_token": "Atzr|SECRET-REFRESH",
                "access_token": "Atza|SECRET-ACCESS",
                "expires_in": 3600,
                "token_type": "bearer",
            }
        raise AssertionError(f"本用例不该发起 {payload['grant_type']}")

    monkeypatch.setattr(oauth, "_post_lwa", _fake_post_lwa)

    store_id = await make_store(client, auth_headers)
    try:
        state = oauth.build_state(store_id, user["user_id"])
        r = await client.get(
            "/api/v1/amazon-sp/oauth/callback",
            params={"state": state, "spapi_oauth_code": "THECODE", "selling_partner_id": "A1SELLER"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["credential_status"] == "active"
        assert body["seller_id"] == "A1SELLER"
        assert body["id"] > 0, "flush 之后应当拿到真实的凭据行编号"

        # ★★★ 本文件最重要的一条：库里存的是**密文**，且密文里不含明文
        raw_rt = await _raw_column(store_id, "refresh_token")
        raw_at = await _raw_column(store_id, "access_token")
        assert raw_rt and raw_rt.startswith(ENC_PREFIX), raw_rt
        assert raw_at and raw_at.startswith(ENC_PREFIX), raw_at
        assert "SECRET-REFRESH" not in raw_rt
        assert "SECRET-ACCESS" not in raw_at

        # 详情端点只暴露「有没有」，不暴露值
        r2 = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=auth_headers
        )
        detail = r2.json()
        assert detail["has_refresh_token"] is True
        assert detail["credential_status"] == "active"
        assert "SECRET" not in r2.text
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_callback_rejects_forged_or_expired_state(
    client, user, auth_headers, with_key, monkeypatch
):
    _configure_app(monkeypatch)
    store_id = await make_store(client, auth_headers)
    try:
        # 篡改签名
        state = oauth.build_state(store_id, user["user_id"])
        payload, _, sig = state.partition(".")
        r = await client.get(
            "/api/v1/amazon-sp/oauth/callback",
            params={"state": f"{payload}.{'A' * len(sig)}", "code": "THECODE"},
        )
        assert r.status_code == 400, r.text

        # 过期的 state
        import time

        old = oauth.build_state(store_id, user["user_id"], now=time.time() - oauth.STATE_TTL_SECONDS - 10)
        r2 = await client.get(
            "/api/v1/amazon-sp/oauth/callback", params={"state": old, "code": "THECODE"}
        )
        assert r2.status_code == 400, r2.text
        # ⇒ 没有任何凭据行被创建
        assert await _raw_column(store_id, "refresh_token") is None
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_callback_records_seller_denial(client, user, auth_headers, with_key, monkeypatch):
    """卖家在同意页点「拒绝」⇒ 400 + 审计留痕，且**不产生**授权记录。"""
    _configure_app(monkeypatch)
    store_id = await make_store(client, auth_headers)
    try:
        state = oauth.build_state(store_id, user["user_id"])
        r = await client.get(
            "/api/v1/amazon-sp/oauth/callback",
            params={"state": state, "error": "access_denied", "error_description": "卖家拒绝"},
        )
        assert r.status_code == 400, r.text

        logs = (
            await client.get(
                f"/api/v1/amazon-sp/stores/{store_id}/auth-logs", headers=auth_headers
            )
        ).json()
        assert any(item["success"] is False for item in logs), logs
        assert await _raw_column(store_id, "credential_status") is None
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_refresh_requires_existing_grant(client, auth_headers):
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/credential/refresh", headers=auth_headers
        )
        assert r.status_code == 409, r.text
        assert "尚未完成授权" in r.json()["detail"]
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_refresh_replaces_access_token(
    client, user, auth_headers, with_key, monkeypatch
):
    _configure_app(monkeypatch)
    calls: list[str] = []

    async def _fake_post_lwa(payload):
        calls.append(payload["grant_type"])
        if payload["grant_type"] == "authorization_code":
            return {"refresh_token": "Atzr|RT", "access_token": "Atza|OLD", "expires_in": 3600}
        assert payload["refresh_token"] == "Atzr|RT", "刷新必须用库里解出来的 refresh_token"
        return {"access_token": "Atza|NEW", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_lwa", _fake_post_lwa)

    store_id = await make_store(client, auth_headers)
    try:
        state = oauth.build_state(store_id, user["user_id"])
        assert (
            await client.get(
                "/api/v1/amazon-sp/oauth/callback",
                params={"state": state, "code": "C"},
            )
        ).status_code == 200

        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/credential/refresh", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["credential_status"] == "active"
        assert calls == ["authorization_code", "refresh_token"]

        raw_at = await _raw_column(store_id, "access_token")
        assert raw_at and raw_at.startswith(ENC_PREFIX)
        assert "Atza|NEW" not in raw_at
        # refresh_token **不变**（刷新不轮换长期凭据）
        from modules.amazon_sp.oauth import open_value

        assert open_value(await _raw_column(store_id, "refresh_token")) == "Atzr|RT"
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_refresh_failure_is_recorded_not_swallowed(
    client, user, auth_headers, with_key, monkeypatch
):
    """刷新失败必须**留下痕迹**（error_count / refresh_error）——
    这是运维判断「卖家是不是撤销了授权」的唯一依据。"""
    _configure_app(monkeypatch)

    async def _fake_post_lwa(payload):
        if payload["grant_type"] == "authorization_code":
            return {"refresh_token": "Atzr|RT", "access_token": "Atza|OLD", "expires_in": 3600}
        raise oauth.SpApiOAuthError("LWA 令牌交换失败：HTTP 400", code="HTTP_400")

    monkeypatch.setattr(oauth, "_post_lwa", _fake_post_lwa)

    store_id = await make_store(client, auth_headers)
    try:
        st = oauth.build_state(store_id, user["user_id"])
        assert (
            await client.get(
                "/api/v1/amazon-sp/oauth/callback", params={"state": st, "code": "C"}
            )
        ).status_code == 200

        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/credential/refresh", headers=auth_headers
        )
        assert r.status_code == 502, r.text

        detail = (
            await client.get(
                f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=auth_headers
            )
        ).json()
        assert detail["error_count"] == 1
        assert detail["refresh_error"], "失败原因必须被记下来"

        logs = (
            await client.get(
                f"/api/v1/amazon-sp/stores/{store_id}/auth-logs", headers=auth_headers
            )
        ).json()
        assert any(i["action"] == "refreshed" and i["success"] is False for i in logs)
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_revoke_clears_tokens_and_marks_revoked(
    client, user, auth_headers, with_key, monkeypatch
):
    _configure_app(monkeypatch)

    async def _fake_post_lwa(payload):
        return {"refresh_token": "Atzr|RT", "access_token": "Atza|AT", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_lwa", _fake_post_lwa)

    store_id = await make_store(client, auth_headers)
    try:
        state = oauth.build_state(store_id, user["user_id"])
        assert (
            await client.get(
                "/api/v1/amazon-sp/oauth/callback", params={"state": state, "code": "C"}
            )
        ).status_code == 200

        r = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/credential/revoke", headers=auth_headers
        )
        assert r.status_code == 204, r.text

        assert await _raw_column(store_id, "refresh_token") is None
        assert await _raw_column(store_id, "access_token") is None
        assert await _raw_column(store_id, "credential_status") == "revoked"

        detail = (
            await client.get(
                f"/api/v1/amazon-sp/stores/{store_id}/credential", headers=auth_headers
            )
        ).json()
        assert detail["has_refresh_token"] is False

        # 撤销之后刷新应当重新变回 409（不能用一个已被清空的凭据去刷）
        r2 = await client.post(
            f"/api/v1/amazon-sp/stores/{store_id}/credential/refresh", headers=auth_headers
        )
        assert r2.status_code == 409, r2.text
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_auth_logs_are_scoped_to_store(client, user, auth_headers, make_user):
    """审计日志按店过滤 + 跨店 403 —— 不得让 A 店看到 B 店的授权历史。"""
    other = await make_user("other")
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/auth-logs", headers=other["headers"]
        )
        assert r.status_code == 403, r.text

        r2 = await client.get(
            f"/api/v1/amazon-sp/stores/{store_id}/auth-logs", headers=auth_headers
        )
        assert r2.status_code == 200
        assert isinstance(r2.json(), list)
    finally:
        await drop_store(client, auth_headers, store_id)

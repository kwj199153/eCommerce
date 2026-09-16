"""
店铺平台凭证「静态加密」回归测试（P1-a 修复，2026-09-16）

★★★ 被修的缺陷形态
    模型注释写着：`api_credentials ... # 加密的 JSON 凭证`
    写入处却是：  `shop.api_credentials = json.dumps(credentials)`
    全项目 `encrypt` / `Fernet` / `decrypt` 命中 **0 处**。

    ⇒ **注释在撒谎，而且不会报错**。该字段只写不读，永远没人去解密，
      于是「文档承诺 vs 实现事实」的偏差可以一直躺着，等到真要读凭证那天
      才以「线上凭证明文裸奔」的形式爆出来。

★★ 本文件的两条设计原则（都不是可选的）

  1. **只做 round-trip 是不够的。**
     把明文塞进去、再原样取回来，round-trip 一样通过 —— 一个恒等函数也能过。
     所以必须额外断言「密文里不含明文子串」。这条才是真正区分
     「真加密」与「假装加密」的判据。

  2. **未配置密钥必须「拒绝写入」，而不是明文落库或自动生成密钥。**
     - 明文落库 = 缺陷原样保留；
     - 自动生成密钥 = 密钥随进程消失 ⇒ 密文永久解不开（数据变砖），
       而界面上一片正常、日志毫无动静 —— **比明文更坏**；
     - 显式拒绝 = 立刻可见、原因可读、修法明确。
     故本文件同时覆盖「无密钥 ⇒ 503 且**零写入**」与「密钥格式非法 ⇒ 同样拒绝」。
"""

import uuid

import pytest

from core.config import config
from core.security.credentials import (
    ENC_PREFIX,
    CredentialsDecryptError,
    CredentialsKeyMissing,
    CredentialsNotEncryptedError,
    decrypt_credentials,
    encrypt_credentials,
    generate_key,
    is_encrypted,
)


# 用一个特征鲜明的值，便于断言「它没出现在密文里」
SECRET = {
    "seller_id": "A1B2C3D4E5F6G7",
    "client_secret": "AKIA-SUPER-SECRET-12345",
    "refresh_token": "Atzr|IwEBIF-not-a-real-token",
}


@pytest.fixture
def with_key(monkeypatch):
    """装一个合法 Fernet 密钥（function 级，不污染其他用例）"""
    key = generate_key()
    monkeypatch.setattr(config, "credentials_encryption_key", key, raising=False)
    return key


@pytest.fixture
def without_key(monkeypatch):
    """显式清空密钥 —— 环境里就算配了也不影响本用例"""
    monkeypatch.setattr(config, "credentials_encryption_key", "", raising=False)
    return ""


# ====== 1. 加解密本身 ======

def test_round_trip_and_ciphertext_hides_plaintext(with_key):
    """
    加密→解密能拿回原值，**且密文里不含任何明文子串**。

    ★ 后半句是这条用例的真正价值：它把「恒等函数伪装成加密」排除掉了。
    """
    cipher = encrypt_credentials(SECRET)

    assert is_encrypted(cipher), "密文必须带 enc:v1: 前缀（用来区分历史明文）"
    assert cipher.startswith(ENC_PREFIX)

    # 关键断言：明文没有以任何形式出现在密文里
    flat = cipher
    for k, v in SECRET.items():
        assert v not in flat, f"密文里出现了明文值 {v!r} —— 这不是加密"
    assert "seller_id" not in flat, "连字段名都不该出现在密文里"

    assert decrypt_credentials(cipher) == SECRET


def test_same_plaintext_encrypts_differently_each_time(with_key):
    """
    同一份凭证两次加密结果必须不同（Fernet 内置随机 IV）。
    ★ 若两次相同，说明没有随机化 —— ECB 式的确定性密文可被比对攻击。
    """
    a = encrypt_credentials(SECRET)
    b = encrypt_credentials(SECRET)
    assert a != b
    assert decrypt_credentials(a) == decrypt_credentials(b) == SECRET


def test_decrypt_none_and_empty_returns_none():
    """空值返回 None（「没配凭证」是合法状态，不是错误）"""
    assert decrypt_credentials(None) is None
    assert decrypt_credentials("") is None


def test_encrypt_requires_dict(with_key):
    with pytest.raises(TypeError):
        encrypt_credentials("seller_id=A1B2")  # type: ignore[arg-type]


# ====== 2. 缺密钥 / 密钥非法 ⇒ 拒绝（绝不退回明文） ======

def test_encrypt_without_key_refuses(without_key):
    """
    无密钥时**拒绝写入**，且失败原因必须点名是哪个配置项。

    ★ 只断言「抛异常」不够：文案里不出现配置项名，运维只会看到
      「服务器内部错误」而不知道去哪修（归因错方向）。
    """
    with pytest.raises(CredentialsKeyMissing) as ei:
        encrypt_credentials(SECRET)
    msg = str(ei.value)
    assert "SHOP_CREDENTIALS_ENCRYPTION_KEY" in msg, msg
    # 必须明说「不会明文落库」，否则调用方可能自己补一个 json.dumps 兜底
    assert "明文" in msg, msg


def test_encrypt_with_invalid_key_format_refuses(monkeypatch):
    """密钥写错（不是合法 Fernet key）同样拒绝，且明确指出格式要求。"""
    monkeypatch.setattr(config, "credentials_encryption_key", "not-a-valid-fernet-key",
                        raising=False)
    with pytest.raises(CredentialsKeyMissing) as ei:
        encrypt_credentials(SECRET)
    assert "Fernet" in str(ei.value)


# ====== 3. 读取路径的两种失败必须显式（不能静默返回 None） ======

def test_decrypt_rejects_legacy_plaintext(with_key):
    """
    库里存的是历史明文 ⇒ **显式报错**，而不是返回 None。

    ★ 为什么不能返回 None：调用方会把「这家店没配凭证」和
      「凭证是明文、有泄露风险」混成同一件事 —— 把数据安全问题
      误判成功能未配置，归因方向完全错。
    """
    with pytest.raises(CredentialsNotEncryptedError) as ei:
        decrypt_credentials('{"seller_id": "A1B2C3"}')
    assert "明文" in str(ei.value)


def test_decrypt_with_rotated_key_fails_loudly(monkeypatch):
    """换了密钥 ⇒ 解密失败必须显式（否则会静默以为「没配凭证」）"""
    monkeypatch.setattr(config, "credentials_encryption_key", generate_key(), raising=False)
    cipher = encrypt_credentials(SECRET)

    monkeypatch.setattr(config, "credentials_encryption_key", generate_key(), raising=False)
    with pytest.raises(CredentialsDecryptError) as ei:
        decrypt_credentials(cipher)
    assert "密钥" in str(ei.value)


# ====== 4. 端点级：写入口真的守住了（含「零写入」证据） ======
#
# ★ 为什么必须有这一段：上面的单测只证明「函数是对的」，
#   证明不了「生产写路径真的调了它」。修复前的实现也能通过上面所有单测。
#
# ★★★ P1-c 改造（2026-09-16）：本段原先打的是**账户侧**
#   `POST /api/v1/shops/{uuid}/connect`（`shops` 表）。该端点已随账户侧实体
#   整体删除 —— 实测生产 0 调用点，且用它建出来的店在业务侧根本不可用。
#   现在改打**业务侧** `POST /api/v1/stores/{store_xxx}/connect`，
#   也就是前端真正在用的那条路径
#   （前端 `connectPlatform()` → `post('/stores/${id}/connect')`）。
#
#   ★ 契约对齐：请求体是**扁平的 credentials**（`json=SECRET`），
#     不是 `{"credentials": {...}}` —— 后者与前端契约不符，会让这组用例
#     测的是一个不存在的调用形状。
#
#   ★ 建店走**真实接口**：`_get_store()` 读的是内存缓存 `_store_db`，
#     只往 PG 插行是打不到端点的（会 404 而不是走到凭证逻辑）。

async def _make_store(client, headers) -> str:
    """经真实接口建店（同时进内存缓存与 PG，与生产路径一致）。"""
    r = await client.post(
        "/api/v1/stores",
        json={"name": f"[p1a] credential probe {uuid.uuid4().hex[:8]}",
              "platform": "amazon_us"},
        headers=headers,
    )
    assert r.status_code == 201, f"建店失败 {r.status_code} {r.text[:300]}"
    return r.json()["id"]


async def _drop_store(client, headers, store_id: str) -> None:
    """经真实接口删店（同时清内存缓存与 PG）；失败则回退裸 SQL + 清内存。"""
    r = await client.delete(f"/api/v1/stores/{store_id}", headers=headers)
    if r.status_code not in (200, 204, 404):
        from sqlalchemy import text
        from core.database import async_session_factory

        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM stores_store WHERE id = :i"), {"i": store_id})
            await db.commit()
    from modules.stores.router import _store_db
    _store_db.pop(store_id, None)


async def _read_api_credentials(store_id: str):
    """直查数据库原文（不经过 ORM，避免任何隐式解密）"""
    from sqlalchemy import text
    from core.database import async_session_factory

    async with async_session_factory() as db:
        return (await db.execute(
            text("SELECT api_credentials FROM stores_store WHERE id = :i"), {"i": store_id}
        )).scalar()


async def test_connect_without_key_returns_503_and_writes_nothing(
    client, user, auth_headers, without_key
):
    """
    未配置密钥时连接平台 ⇒ **503 + 可读原因**，且数据库里一个字节都没写。

    ★ 判据分两半，缺一不可：
      ① 失败原因指向真因（出现「SHOP_CREDENTIALS_ENCRYPTION_KEY」）；
      ② `api_credentials` 仍为 NULL —— 证明「拒绝」真的生效了，
         而不是「返回了 503 但顺手把明文写进去了」。
    """
    store_id = await _make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/stores/{store_id}/connect",
            json=SECRET,
            headers=auth_headers,
        )
        assert r.status_code == 503, f"{r.status_code} {r.text[:300]}"
        assert "SHOP_CREDENTIALS_ENCRYPTION_KEY" in r.text, r.text[:300]

        # ② 零写入证据
        assert await _read_api_credentials(store_id) is None
    finally:
        await _drop_store(client, auth_headers, store_id)


async def test_connect_with_key_stores_ciphertext_and_is_decryptable(
    client, user, auth_headers, with_key
):
    """
    配好密钥后：接口 200，库里是 `enc:v1:` 密文、不含明文，且能解回原值。

    ★ 反向保护：防止「为了让 503 用例变绿，干脆把写入整段删掉」。
    """
    store_id = await _make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/stores/{store_id}/connect",
            json=SECRET,
            headers=auth_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        stored = await _read_api_credentials(store_id)
        assert stored, "凭证必须真的落库了"
        assert stored.startswith(ENC_PREFIX), stored[:40]
        for v in SECRET.values():
            assert v not in stored, f"库里出现了明文 {v!r}"
        assert decrypt_credentials(stored) == SECRET
    finally:
        await _drop_store(client, auth_headers, store_id)


async def test_plain_update_does_not_wipe_credentials(client, user, auth_headers, with_key):
    """
    普通「改个店铺名」**不得**把凭证密文清掉。

    ★ 这条守的是一个零报错的静默破坏：`_upsert_store_db()` 与
      `_save_store_credentials()` 是**两个**写路径。若有人"顺手统一"，
      让前者同步 `api_credentials`，那么每次改名/改状态/连接都会把密文
      写成 NULL（pydantic `Store` 里**没有**该字段，所以同步过去的永远是 None）
      ⇒ 现象是「改个店铺名，平台连接悄悄掉线」，日志毫无提示。
    """
    store_id = await _make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=SECRET, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        before = await _read_api_credentials(store_id)
        assert before and before.startswith(ENC_PREFIX)

        u = await client.put(f"/api/v1/stores/{store_id}",
                             json={"name": f"[p1a] 改名 {uuid.uuid4().hex[:6]}"},
                             headers=auth_headers)
        assert u.status_code == 200, u.text[:300]

        after = await _read_api_credentials(store_id)
        assert after == before, (
            "普通更新把凭证密文改了/清了 —— `_upsert_store_db()` 不得同步 "
            "`api_credentials`（pydantic Store 里没有该字段，同步过去只会是 NULL）"
        )
    finally:
        await _drop_store(client, auth_headers, store_id)


async def test_disconnect_actually_clears_ciphertext(client, user, auth_headers, with_key):
    """
    断开连接必须**真的把密文清掉**，而不只是翻一个标志位。

    ★ 只翻标志而留着密文 = 「用户以为撤销了授权，密文还在库里」。
      授权撤销要落在数据上，否则它只是一个 UI 上的安慰剂。
    """
    store_id = await _make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=SECRET, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        assert await _read_api_credentials(store_id) is not None

        d = await client.post(f"/api/v1/stores/{store_id}/disconnect", headers=auth_headers)
        assert d.status_code == 200, d.text[:300]

        assert await _read_api_credentials(store_id) is None, (
            "断开连接后密文仍在库里 —— 用户以为撤销了授权，实际没有"
        )
        # 响应体不得回带任何凭证字段
        assert "AKIA-SUPER-SECRET-12345" not in d.text
    finally:
        await _drop_store(client, auth_headers, store_id)

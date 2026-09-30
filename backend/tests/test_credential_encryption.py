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
# 第 318 轮：端点现在会真去平台验一次 ⇒ 这些用例必须声明「验证结果是什么」。
from modules.stores.connect import VerifyStatus

# 第 318 轮：三个共用辅助上移到 `tests/connect_testkit.py`（两个文件共用，
# 避免同一能力两份实现 —— 见该模块 docstring）。
from connect_testkit import drop_store, make_store, read_raw_credentials


# 一组特征鲜明的**假**凭据，便于断言「它们没出现在密文里」。
#
# ★★★ 第 318 轮（2026-09-29）：键名必须与 `AmazonConnector.fields()` **对齐**。
#   连接端点现在会先用**真实 schema** 做白名单收敛（`normalize`：未声明的键直接丢）
#   与必填复核（`require`：缺必填 ⇒ 400，且发生在联网之前）。
#   改造前这份 payload 是 `seller_id / client_secret / refresh_token` ——
#   `seller_id` 根本不在 schema 里（LWA 用的是 `client_id`），且缺 3 个必填，
#   于是整组端点用例会以「缺少必填字段」红，而**红的原因看着像端点坏了**。
#
#   `test_secret_payload_matches_amazon_schema` 把这条对齐关系本身钉成判据：
#   字段改名时它会直接指名道姓，而不是留下一堆误导性的失败。
SECRET = {
    "client_id": "amzn1.application-oa2-client.FAKE-0000",
    "client_secret": "AKIA-SUPER-SECRET-12345",
    "refresh_token": "Atzr|IwEBIF-not-a-real-token",
    "aws_access_key": "AKIA-FAKE-ACCESS-KEY",
    "aws_secret_key": "FAKE-AWS-SECRET-VALUE",
}


# ★ `with_key` 已上移到 `tests/conftest.py`（本文件与 `test_store_connect.py`
#   共用）。留两份就是「同一能力两份实现」：改一处漏一处时，
#   其中一个文件会**静默地**不再覆盖「配了密钥」的情形。


@pytest.fixture
def without_key(monkeypatch):
    """显式清空密钥 —— 环境里就算配了也不影响本用例"""
    monkeypatch.setattr(config, "credentials_encryption_key", "", raising=False)
    return ""


# ====== 0. 测试载荷与真实 schema 的对齐（★ 第 318 轮新增） ======

def test_secret_payload_matches_amazon_schema():
    """本文件的 `SECRET` 必须与亚马逊连接器声明的字段**完全对齐**。

    ★ 为什么这条要单独成例：连接端点会先用**真 schema** 做白名单收敛
      （未声明的键直接丢）与必填复核（缺必填 ⇒ 400）。
      一旦 `AmazonConnector.fields()` 改了字段名而这里没跟上，
      下游用例会以「缺少必填字段」红 —— 而那个报错**看起来像端点坏了**，
      排查方向完全错。把这条对齐关系本身钉成判据，红的时候就会直接指名道姓。
    """
    from modules.stores.connect.registry import get_connector

    connector = get_connector("amazon_us")
    declared = {f.key for f in connector.fields()}
    required = {f.key for f in connector.required_fields()}

    unknown = set(SECRET) - declared
    assert not unknown, (
        f"SECRET 里有连接器未声明的字段：{sorted(unknown)} —— "
        "它们会被 normalize() 白名单丢弃，下游用例会静默测不到这些值"
    )
    missing = required - set(SECRET)
    assert not missing, (
        f"SECRET 缺必填字段：{sorted(missing)} —— 端点会在 require() 处 400，"
        "下游用例全部变红且原因看着像端点坏了"
    )


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


async def test_connect_without_key_returns_503_and_writes_nothing(
    client, user, auth_headers, without_key, stub_connector
):
    """
    未配置密钥时连接平台 ⇒ **503 + 可读原因**，且数据库里一个字节都没写。

    ★ 判据分两半，缺一不可：
      ① 失败原因指向真因（出现「SHOP_CREDENTIALS_ENCRYPTION_KEY」）；
      ② `api_credentials` 仍为 NULL —— 证明「拒绝」真的生效了，
         而不是「返回了 503 但顺手把明文写进去了」。

    ★★★ 第 318 轮补的第三半（**顺序**判据）：密钥检查必须在**联网之前**。
      这里把桩装成「验证会通过」，于是能证明：即使凭据本身没问题，
      缺密钥仍然以 503 收场，**且桩的 `verify()` 一次都没被调用**
      （末行 `stub.seen is None`）。
      若密钥检查被挪到落库那一刻（即验证之后），本用例就会变成
      「先拿真凭据去打平台、再报 503」—— 而那次真打出去的调用一旦回
      「凭据无效」，真因（服务端漏配密钥）就被完全掩盖了。
    """
    stub = stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/stores/{store_id}/connect",
            json=SECRET,
            headers=auth_headers,
        )
        assert r.status_code == 503, f"{r.status_code} {r.text[:300]}"
        assert "SHOP_CREDENTIALS_ENCRYPTION_KEY" in r.text, r.text[:300]

        # ② 零写入证据
        assert await read_raw_credentials(store_id) is None
        # ③ 顺序证据：密钥检查拦在联网之前 ⇒ 桩的 verify 根本没被调用
        assert stub.seen is None, (
            "密钥检查没有拦在联网之前：凭据已被送去平台验证 —— "
            "这会在凭据恰好不对时把「服务端漏配密钥」这个真因掩盖掉"
        )
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_connect_with_key_stores_ciphertext_and_is_decryptable(
    client, user, auth_headers, with_key, stub_connector
):
    """
    配好密钥后：接口 200，库里是 `enc:v1:` 密文、不含明文，且能解回原值。

    ★ 反向保护：防止「为了让 503 用例变绿，干脆把写入整段删掉」。

    ★★★ 第 318 轮：这里必须装配桩把验证装成「通过」。
      改造前不需要桩（端点压根不验证）；现在「200」这个结果
      **以验证通过为前提** —— 不装桩的话，本用例会真的拿一组假凭据去打
      Amazon，最终以 400（凭据被拒绝 ⇒ 不落库）收场。
      桩在这里同时是「本用例可离线跑」的保证。
    """
    stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(
            f"/api/v1/stores/{store_id}/connect",
            json=SECRET,
            headers=auth_headers,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        stored = await read_raw_credentials(store_id)
        assert stored, "凭证必须真的落库了"
        assert stored.startswith(ENC_PREFIX), stored[:40]
        for v in SECRET.values():
            assert v not in stored, f"库里出现了明文 {v!r}"
        assert decrypt_credentials(stored) == SECRET
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_plain_update_does_not_wipe_credentials(
    client, user, auth_headers, with_key, stub_connector
):
    """
    普通「改个店铺名」**不得**把凭证密文清掉。

    ★ 这条守的是一个零报错的静默破坏：`_upsert_store_db()` 与
      `_save_store_credentials()` 是**两个**写路径。若有人"顺手统一"，
      让前者同步 `api_credentials`，那么每次改名/改状态/连接都会把密文
      写成 NULL（pydantic `Store` 里**没有**该字段，所以同步过去的永远是 None）
      ⇒ 现象是「改个店铺名，平台连接悄悄掉线」，日志毫无提示。

    ★ 第 318 轮：前置的「先连上」现在以**验证通过**为前提，故装配桩。
    """
    stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=SECRET, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        before = await read_raw_credentials(store_id)
        assert before and before.startswith(ENC_PREFIX)

        u = await client.put(f"/api/v1/stores/{store_id}",
                             json={"name": f"[p1a] 改名 {uuid.uuid4().hex[:6]}"},
                             headers=auth_headers)
        assert u.status_code == 200, u.text[:300]

        after = await read_raw_credentials(store_id)
        assert after == before, (
            "普通更新把凭证密文改了/清了 —— `_upsert_store_db()` 不得同步 "
            "`api_credentials`（pydantic Store 里没有该字段，同步过去只会是 NULL）"
        )
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_disconnect_actually_clears_ciphertext(
    client, user, auth_headers, with_key, stub_connector
):
    """
    断开连接必须**真的把密文清掉**，而不只是翻一个标志位。

    ★ 只翻标志而留着密文 = 「用户以为撤销了授权，密文还在库里」。
      授权撤销要落在数据上，否则它只是一个 UI 上的安慰剂。

    ★ 第 318 轮：前置的「先连上」现在以**验证通过**为前提，故装配桩。
    """
    stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=SECRET, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        assert await read_raw_credentials(store_id) is not None

        d = await client.post(f"/api/v1/stores/{store_id}/disconnect", headers=auth_headers)
        assert d.status_code == 200, d.text[:300]

        assert await read_raw_credentials(store_id) is None, (
            "断开连接后密文仍在库里 —— 用户以为撤销了授权，实际没有"
        )
        # 响应体不得回带任何凭证字段
        assert "AKIA-SUPER-SECRET-12345" not in d.text
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 5. ★ 「配置项名」本身必须真的生效（第 119 轮补） ======
#
# ★★★ 这一段守的是一个「文档与实现各说各话」的缺陷，**上面全部用例都拦不住**：
#
#   本文件 test_encrypt_without_key_refuses 断言「报错文案里出现
#   SHOP_CREDENTIALS_ENCRYPTION_KEY」—— 它保证的是**文档提到了这个名字**，
#   而没有任何一条用例验证 **这个名字真的能配置系统**。
#
#   实测（第 119 轮，对照实验：同一套 .env、同一段代码，只改环境变量名）：
#       SHOP_CREDENTIALS_ENCRYPTION_KEY → config 读到 0 字符
#       CREDENTIALS_ENCRYPTION_KEY      → config 读到 44 字符
#   根因：`Settings.model_config` 里既没有 `env_prefix`、字段也没有 alias
#   ⇒ pydantic-settings 按**字段名大写**去找环境变量。于是 `.env.example`、
#   `credentials.py` 的报错文案、字段注释一律写的那个名字**完全无效**，
#   而失败信息还在指引用户去配同一个没用的名字 —— 照做，依然失败，无处可查。
#
#   ★ 为什么长期没被发现：本文件所有用例都用 `monkeypatch.setattr(config, ...)`
#     **直接改属性**，绕过了环境变量这条真实路径。
#     判据：**绕过真实入口的测试，测的是夹具不是产品。**
#
#   修法见 `core/config.py::credentials_encryption_key` 的 `AliasChoices`。

@pytest.mark.parametrize(
    "env_name",
    [
        "SHOP_CREDENTIALS_ENCRYPTION_KEY",   # 文档 / .env.example / 报错文案承诺的名字
        "CREDENTIALS_ENCRYPTION_KEY",        # 修复前**唯一真正生效**的名字（可能已有部署在用）
    ],
)
def test_env_var_name_actually_configures_encryption(env_name, monkeypatch):
    """
    这两名字都必须真能配置到 —— 「文档提到它」不算证据，「读得到」才算。

    ★ 用 `_env_file=None` 隔离掉开发机 `.env` 里的真实密钥：
      否则 `.env` 里那个值会掩盖"环境变量没被读到"这个事实，
      用例会在**本机绿、CI 红**（或反过来），失去判据价值。
    """
    from core.config import Settings

    key = generate_key()
    # 先把两个候选名都清掉，避免互相干扰（Windows 环境变量大小写不敏感，
    # 故只用两个全大写名，不再额外测字段名本身）
    for name in ("SHOP_CREDENTIALS_ENCRYPTION_KEY", "CREDENTIALS_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env_name, key)

    s = Settings(_env_file=None)
    assert s.credentials_encryption_key == key, (
        f"环境变量 {env_name} 没有生效 —— 文档承诺的名字必须真能配置系统，"
        f"否则用户照文档配置后只会看到「未配置密钥」，而报错文案还在指引他配同一个名字"
    )


def test_settings_keyword_construction_still_works():
    """
    关键字构造这条路不能被 `validation_alias` 打断。

    ★ 回归护栏：加了 alias 之后，若忘了把字段名本身也列进 `AliasChoices`，
      `Settings(credentials_encryption_key=...)` 会静默变回默认空串 ——
      而**没有任何报错**，只是密钥"莫名其妙不生效"。
    """
    from core.config import Settings

    key = generate_key()
    assert Settings(_env_file=None, credentials_encryption_key=key).credentials_encryption_key == key


def test_missing_key_error_message_names_a_working_config_item(without_key):
    """
    报错文案点名的配置项，必须**真的是能生效的那个**。

    ★ 与 test_encrypt_without_key_refuses 的区别（那一条不够）：
      那条只断言"文案里出现了某个名字"；若代码读的名字与文案写的名字不是一个，
      它照样通过。本用例把两件事**绑在一起**验证：
         文案点名的名字 → 照着配 → config 真的读到 → 加密真的可用。
      这才是「承诺与实现一致」的完整判据。
    """
    from core.config import Settings

    with pytest.raises(CredentialsKeyMissing) as ei:
        encrypt_credentials(SECRET)
    msg = str(ei.value)

    # 从文案里抠出被点名的配置项（形如 XXX_ENCRYPTION_KEY）
    import re

    named = re.findall(r"\b([A-Z][A-Z0-9_]*_ENCRYPTION_KEY)\b", msg)
    assert named, f"报错文案没有点名任何配置项：{msg[:200]}"

    key = generate_key()
    for name in named:
        probe_env = {name: key}
        # 只留文案点名的那个名字
        for other in ("SHOP_CREDENTIALS_ENCRYPTION_KEY", "CREDENTIALS_ENCRYPTION_KEY"):
            probe_env.setdefault(other, "")
        monkeypatch = pytest.MonkeyPatch()
        try:
            for other in ("SHOP_CREDENTIALS_ENCRYPTION_KEY", "CREDENTIALS_ENCRYPTION_KEY"):
                monkeypatch.delenv(other, raising=False)
            monkeypatch.setenv(name, key)
            s = Settings(_env_file=None)
            assert s.credentials_encryption_key == key, (
                f"报错文案叫用户去配 {name}，但配了**读不到** —— "
                f"用户会陷入「照着报错改，还是同一句报错」的死循环"
            )
        finally:
            monkeypatch.undo()

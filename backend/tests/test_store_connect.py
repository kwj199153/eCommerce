"""`POST /stores/{id}/connect` 的新契约（第 318 轮）：**先真验证、通过才落库**。

★★★ 被修的缺陷形态（三层叠加，机制见 `modules/stores/connect/base.py` 顶部）

  ① 账号设置的店铺管理里**没有连接入口**，「未连接」是终态；
  ② 后端列表**不返回 `is_connected`** —— `Store.is_connected` 是普通
     `@property`，pydantic v2 **不会**把它序列化进 `model_dump()`
     ⇒ 前端读 `item.is_connected` 恒为 `undefined` ⇒ 连上了也永远显示「未连接」；
  ③ `POST /{id}/connect` 收下凭据后**直接丢弃**、无条件置「已连接」
     ⇒ 「已连接」是个**空承诺**：库里没有任何凭据。

  本文件主要守第 ③ 层，并给第 ② 层留一条回归判据。

★★★ 纪律：**所有联网路径都走注入的桩**（`stub_connector`，见 `tests/conftest.py`）。
  用例里绝不真打第三方接口 —— 那种用例慢、不可复现（网络一抖就红，
  且红的原因与被测逻辑无关），最后一定会被注释掉。
  唯一例外是 `tiktok`：它的连接器**刻意没有** `verify()`，
  基类默认返回 `UNSUPPORTED`，因此**不联网**即可覆盖「已配置（未验证）」这条结局。
"""

import pytest

from connect_testkit import drop_store, make_store, read_raw_credentials
from core.security.credentials import ENC_PREFIX, decrypt_credentials
from modules.stores.connect import VerifyStatus

pytestmark = pytest.mark.tenant_identity


# Amazon 的必填字段集（与 `AmazonConnector.fields()` 对齐）
AMAZON_CREDS = {
    "client_id": "amzn1.application-oa2-client.FAKE-0000",
    "client_secret": "AKIA-SUPER-SECRET-12345",
    "refresh_token": "Atzr|IwEBIF-not-a-real-token",
    "aws_access_key": "AKIA-FAKE-ACCESS-KEY",
    "aws_secret_key": "FAKE-AWS-SECRET-VALUE",
}

# TikTok：`verify_supported=False`（fail-closed），凭据只保存、不标记已验证
TIKTOK_CREDS = {
    "app_key": "tt-app-key",
    "app_secret": "tt-app-secret",
    "access_token": "tt-access-token",
}

# 一个绝不该出现在**响应体**里的特征串（连接器刷新出来的新令牌）
REFRESHED_TOKEN = "REFRESHED-TOKEN-MUST-NOT-LEAK-0001"


# ====== 一、表单规格下发 ======

async def test_connect_schema_lists_all_platforms(client, user, auth_headers):
    """`GET /stores/connect/schema` 必须下发**全部**平台的字段规格。

    ★ 这是「不要每个平台写一套」的验收点：前端只吃 `PlatformSchema`，
      不认平台名 ⇒ 这里的平台数必须与「添加店铺」的平台清单一致，
      否则会出现「能建店但配不了」的店。
    """
    r = await client.get("/api/v1/stores/connect/schema", headers=auth_headers)
    assert r.status_code == 200, r.text

    schemas = r.json()["schemas"]
    platforms = {s["platform"] for s in schemas}
    assert platforms == {"amazon", "shopee", "shopify", "tiktok"}, platforms

    for s in schemas:
        assert s["display_name"], f"{s['platform']} 没有展示名"
        assert s["fields"], f"{s['platform']} 字段为空 ⇒ 表单是空的"

    # 未接入自动校验的平台必须**自报** verify_supported=False（fail-closed）
    by_p = {s["platform"]: s for s in schemas}
    assert by_p["tiktok"]["verify_supported"] is False
    assert by_p["amazon"]["verify_supported"] is True


async def test_store_connect_schema_masks_secrets(
    client, user, auth_headers, with_key, stub_connector
):
    """单店回显：非敏感字段回原值，**敏感字段一律掩码，且全响应不含明文**。

    ★ 两半判据缺一不可：
      ① 敏感字段是掩码（`•` 打头）—— 证明「不回明文」这条设计生效；
      ② 整个响应文本里**搜不到任何明文值** —— 证明掩码不是"只在 values 里做了"，
         而在别处（如某段 detail / echo）漏了出去。
    """
    stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]

        r = await client.get(f"/api/v1/stores/{store_id}/connect/schema",
                             headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        body = r.json()

        assert body["is_connected"] is True
        assert body["any_configured"] is True
        # 非敏感字段回原值（用户重开弹窗时知道自己配过什么）
        assert body["values"]["client_id"] == AMAZON_CREDS["client_id"]

        # ★ 「哪些字段敏感」由**后端的声明**决定，不在测试里硬编码 ——
        #   声明改了（某字段从 text 变 password）这里自动跟上。
        sensitive_keys = {f["key"] for f in body["spec"]["fields"] if f["secret"]}
        # 扫描面自检：若一个敏感字段都没取到，下面的循环会**空跑通过**
        assert sensitive_keys, "规格里没有任何 secret 字段 —— 判据会空跑"

        # ① 敏感字段一律掩码
        for key in sensitive_keys:
            assert body["values"][key] == "••••••", (key, body["values"].get(key))
            assert body["configured"][key] is True

        # ② 敏感明文不得出现在响应的**任何位置**。
        #   ⚠️ 判据只针对敏感字段：`client_id` 等刻意是非敏感的公开标识符，
        #      回显它们正是设计意图 —— 把它们也纳入「不得出现」是**过宽的判据**，
        #      必然红（与「排除规则过宽 ⇒ 静默归零」是同一类错，只是方向相反）。
        for key in sensitive_keys & set(AMAZON_CREDS):
            assert AMAZON_CREDS[key] not in r.text, f"回显里漏出了敏感明文：{key}"
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 二、连接：成功路径 ======

async def test_connect_verified_sets_connected_and_persists(
    client, user, auth_headers, with_key, stub_connector
):
    """验证通过 ⇒ 落库（密文）+ 置 `connected` + 列表/详情都能读到 `is_connected`。

    ★ 第 ② 层回归就在最后两条断言：`is_connected` 必须**出现在 JSON 里**
      （普通 `@property` 不进 `model_dump()`，前端读到的会是 `undefined`）。
    """
    stub = stub_connector("amazon_us", VerifyStatus.OK, message="连接成功")
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["connection_status"] == "connected"
        assert body["is_connected"] is True
        assert body["has_credentials"] is True
        assert body["verify"]["status"] == "ok"
        assert body["verify"]["ok"] is True

        # 桩真的收到了收敛后的值（白名单 + 去空白后的形态）
        assert stub.seen == AMAZON_CREDS

        # 落库的是**密文**，且能解回原值
        stored = await read_raw_credentials(store_id)
        assert stored and stored.startswith(ENC_PREFIX)
        assert decrypt_credentials(stored) == AMAZON_CREDS

        # ★ is_connected 必须进 JSON（详情 + 列表两处，前端两处都在读）
        detail = (await client.get(f"/api/v1/stores/{store_id}",
                                   headers=auth_headers)).json()
        assert detail["is_connected"] is True

        listed = (await client.get("/api/v1/stores", headers=auth_headers)).json()
        row = next((s for s in listed["stores"] if s["id"] == store_id), None)
        assert row is not None, "列表里找不到刚建好的店（归属过滤出问题了）"
        assert "is_connected" in row, "列表响应里没有 is_connected —— 前端会读成 undefined"
        assert row["is_connected"] is True
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 三、连接：**失败不落库、不置位** ======

async def test_connect_invalid_credentials_saves_nothing(
    client, user, auth_headers, with_key, stub_connector
):
    """凭据被平台**明确拒绝** ⇒ 400，且**一个字节都不落库、状态一动不动**。

    ★★★ 这是本轮最重要的一条不变量的前半：
      若「无效凭据也照存」，用户会看到一个「已配置」的界面，
      而每次取数都失败 —— 错误被推迟到真正用数据的那一刻才爆出来，
      且现场已经离「填错凭据」很远了。

    ★ 三条断言缺一不可：400 / 库为 NULL / 状态未变。
      只断言 400 的话，「返回 400 但顺手把凭据存了」照样绿。
    """
    stub_connector("amazon_us", VerifyStatus.INVALID, message="Amazon 拒绝了这组凭据")
    store_id = await make_store(client, auth_headers)
    try:
        before = (await client.get(f"/api/v1/stores/{store_id}",
                                   headers=auth_headers)).json()

        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 400, r.text[:300]
        assert "拒绝" in r.text

        assert await read_raw_credentials(store_id) is None, (
            "凭据被平台拒绝却仍然落库了 —— 会制造「看起来配好了、实际取不到数」的假象"
        )
        after = (await client.get(f"/api/v1/stores/{store_id}",
                                  headers=auth_headers)).json()
        assert after["connection_status"] == before["connection_status"] == "disconnected"
        assert after["has_credentials"] is False
        assert after["is_connected"] is False
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_connect_invalid_response_carries_checks(
    client, user, auth_headers, with_key, stub_connector
):
    """失败响应必须带**逐步骤明细**（用户靠它决定去改哪个字段）。"""
    from modules.stores.connect import VerifyCheck

    stub = stub_connector("amazon_us", VerifyStatus.INVALID, message="签名错误")
    # 给桩补一条 checks，模拟真实连接器的「第一步失败」形态
    stub._result.checks.append(VerifyCheck(name="LWA 令牌交换", ok=False, message="401"))

    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 400, r.text[:300]
        detail = r.json()["detail"]
        assert detail["status"] == "invalid"
        assert detail["message"] == "签名错误"
        assert detail["checks"] and detail["checks"][0]["name"] == "LWA 令牌交换"
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 四、连接：**落库但不标记已验证** 的两条结局 ======

async def test_connect_unreachable_saves_but_not_verified(
    client, user, auth_headers, with_key, stub_connector
):
    """平台不可达 ⇒ 200、凭据落库，但**不标记已验证**。

    ★ 为什么不能判成「凭据无效」：超时 / DNS / 5xx 时**凭据好坏未知**。
      网络抖一下就把用户的正确凭据判成错的，用户会去反复改一个本来没错的东西
      （同「三态压两态＝静默洗白」）。
    """
    stub_connector("amazon_us", VerifyStatus.UNREACHABLE, message="无法连接 Amazon 令牌服务")
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["verify"]["status"] == "unreachable"
        assert body["verify"]["ok"] is False
        # 凭据确实保存了（用户不必重填），但**不得**标记为已连接
        assert body["has_credentials"] is True
        assert body["connection_status"] == "disconnected"
        assert body["is_connected"] is False

        stored = await read_raw_credentials(store_id)
        assert stored and stored.startswith(ENC_PREFIX)
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_connect_unsupported_platform_saves_but_not_verified(
    client, user, auth_headers, with_key
):
    """TikTok（未接入自动校验）⇒ 200、凭据落库，但**不标记已验证**。

    ★ 这条**不需要桩**：`TikTokConnector` 刻意没有 `verify()`，
      基类默认返回 `UNSUPPORTED`，因此本用例在线性链路上跑通
      「fail-closed 一直传到界面」的完整证据链（且不联网）。

    ★ 若失败会怎样：把「未验证」显示成「已连接」，用户以为通了，
      真去拉数据才发现 —— 这是本轮要消灭的承诺型缺陷的另一个版本。
    """
    store_id = await make_store(client, auth_headers, platform="tiktok")
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=TIKTOK_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["verify"]["status"] == "unsupported"
        assert body["verify"]["ok"] is False
        assert body["has_credentials"] is True
        assert body["connection_status"] == "disconnected"
        assert body["is_connected"] is False

        stored = await read_raw_credentials(store_id)
        assert stored and stored.startswith(ENC_PREFIX)
        assert decrypt_credentials(stored) == TIKTOK_CREDS
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 五、刷新值：**落库但绝不回显** ======

async def test_refreshed_token_is_persisted_but_never_returned(
    client, user, auth_headers, with_key, stub_connector
):
    """连接器换到的新令牌：**必须**落库，**绝不**出现在响应里。

    ★ 这两半是一体的：
      - 不落库 ⇒ Shopee 每次都拿旧 token 去换，4 小时后就调不通；
      - 回显 ⇒ 把刚拿到的凭据明文发给浏览器（并留在前端 store / 日志 / 缓存里），
        且**不会有任何报错** —— 功能照常工作，泄露是静默的。
      所以响应模型刻意用 `VerifyReport`（没有 `refreshed` 字段），
      而不是 `VerifyResult`。
    """
    stub_connector("amazon_us", VerifyStatus.OK, message="ok",
                   refreshed={"refresh_token": REFRESHED_TOKEN})
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]

        # ① 绝不回显
        assert REFRESHED_TOKEN not in r.text, "响应体里带出了刷新出来的新令牌明文"
        assert "refreshed" not in r.json()["verify"]

        # ② 必须落库（用连接器产出的值覆盖同名入参）
        stored = await read_raw_credentials(store_id)
        assert decrypt_credentials(stored)["refresh_token"] == REFRESHED_TOKEN
    finally:
        await drop_store(client, auth_headers, store_id)


# ====== 六、脏数据 / 断开的边界 ======

async def test_connect_unregistered_platform_returns_400(
    client, user, auth_headers, with_key
):
    """店铺平台不属于任何已登记平台 ⇒ 400（而不是 500，也不是假装成功）。

    ★ 构造方式：建一家正常店，然后**只改内存里**的 `platform`。
      这模拟的正是真实场景 —— 历史脏数据 / 新平台上线但没登记
      （`create_store` 有平台校验，建不出这种店，但库里可能已经有）。
    """
    from modules.stores.router import _store_db

    store_id = await make_store(client, auth_headers)
    try:
        _store_db[store_id].platform = "mystery_xx"

        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 400, r.text[:300]
        assert "未注册的平台" in r.text
    finally:
        await drop_store(client, auth_headers, store_id)


async def test_disconnect_clears_credentials_and_state(
    client, user, auth_headers, with_key, stub_connector
):
    """断开必须同时清**数据**与**状态**（授权撤销要落在数据上）。

    ★ 只翻标志而留着密文 = 「用户以为撤销了授权，密文还在库里」。
    """
    stub_connector("amazon_us", VerifyStatus.OK)
    store_id = await make_store(client, auth_headers)
    try:
        r = await client.post(f"/api/v1/stores/{store_id}/connect",
                              json=AMAZON_CREDS, headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        assert (await read_raw_credentials(store_id)) is not None

        d = await client.post(f"/api/v1/stores/{store_id}/disconnect",
                              headers=auth_headers)
        assert d.status_code == 200, d.text[:300]

        assert await read_raw_credentials(store_id) is None, "断开后密文仍在库里"
        detail = (await client.get(f"/api/v1/stores/{store_id}",
                                   headers=auth_headers)).json()
        assert detail["connection_status"] == "disconnected"
        assert detail["is_connected"] is False
        assert detail["has_credentials"] is False
    finally:
        await drop_store(client, auth_headers, store_id)

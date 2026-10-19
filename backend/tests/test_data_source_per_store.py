"""按店取数的**验收判据**（第 386 轮 · 商用审查 P0-1）。

三条判据，全部可执行、且**只可能因为「按店」成立而变绿**：

  判据 1  两店两 seller 取同一日期范围，订单号集合**交集为空**。
  判据 2  把 `.env` 里的 `SPAPI_REFRESH_TOKEN` 清空，两店仍能各自取数
          （证明凭据只来自 DB，不是那把全局钥匙）。
  判据 3  未授权店铺抛 `StoreNotConnected`，且**一行数据都不产出**。

★ 为什么桩要读 `config.lwa.refresh_token` 而不是读一个测试自己设的变量：
  这正是判据的关键。如果实现退回「全局单例」，两家店拿到的 config 是同一份
  ⇒ 桩返回同一批订单 ⇒ 判据 1 立刻变红。桩**不能**从外部给它想要的答案。

★ 与 `test_store_credentials.py` 的分工：那个文件管「选哪把钥匙」，
  本文件管「钥匙真的插进去了、且两店不串」。
"""

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from core.database import async_session_factory
from core.security.credentials import encrypt_credentials
from core.stores.models import StoreRecord
from modules.amazon_sp import StoreNotConnected, open_data_source
from platforms.amazon.sp_api.client import SPAPIClient
from platforms.amazon.sp_api.orders import OrdersAPI

from sqlalchemy import update


# ============================================================================
# 夹具
# ============================================================================
@pytest.fixture
def app_creds(monkeypatch):
    """应用级凭据（LWA 应用身份 + AWS 签名密钥）。见 test_store_credentials 同名夹具。"""
    from core.config import config

    monkeypatch.setattr(config, "spapi_lwa_client_id", "amzn1.application-oa2-client.test", raising=False)
    monkeypatch.setattr(config, "spapi_lwa_client_secret", "test-lwa-secret", raising=False)
    monkeypatch.setattr(config, "spapi_aws_access_key", "AKIATESTAPPLEVEL000", raising=False)
    monkeypatch.setattr(config, "spapi_aws_secret_key", "test-aws-secret", raising=False)
    monkeypatch.setattr(config, "spapi_aws_region", "us-east-1", raising=False)
    monkeypatch.setattr(config, "spapi_use_sandbox", True, raising=False)
    return config


@pytest.fixture
async def make_shop(ensure_shop):
    """造一家店铺并配好表单凭据 + 站点。"""
    created = []

    async def _make(*, refresh_token: str, region: str = "US") -> str:
        sid = await ensure_shop(f"store_r386ds_{uuid.uuid4().hex[:10]}")
        created.append(sid)
        blob = encrypt_credentials({
            "client_id": "amzn1.application-oa2-client.test",
            "client_secret": "test-lwa-secret",
            "refresh_token": refresh_token,
            "aws_access_key": "AKIATESTFORM000000",
            "aws_secret_key": "form-secret",
            "region": "us-east-1",
            "use_sandbox": "true",
        })
        async with async_session_factory() as db:
            await db.execute(
                update(StoreRecord)
                .where(StoreRecord.id == sid)
                .values(api_credentials=blob, region_code=region)
            )
            await db.commit()
        return sid

    return _make


@pytest.fixture
async def bare_shop(ensure_shop):
    """一家**没有任何凭据**的店铺（真实客户刚建店的状态）。"""
    sid = await ensure_shop(f"store_r386bare_{uuid.uuid4().hex[:10]}")
    async with async_session_factory() as db:
        await db.execute(
            update(StoreRecord).where(StoreRecord.id == sid).values(region_code="US")
        )
        await db.commit()
    return sid


def _order(order_id: str) -> SimpleNamespace:
    """SP-API `Order` 的最小可用替身（`fetch_daily_sales` 只读这两个字段）。"""
    return SimpleNamespace(amazon_order_id=order_id, purchase_date=datetime_now())


def datetime_now():
    from datetime import datetime

    return datetime.now()


@pytest.fixture
def stub_spapi(monkeypatch):
    """按**该店 config 里的 refresh_token** 决定返回哪一批订单。

    ★ 这就是本文件的全部魔法：桩的输入是「数据源实例真实持有的配置」。
      实现若没有把该店的凭据注进去，这里读到的就是别家的值（或 None），
      判据 1 会立刻红 —— 不需要额外断言。
    """
    seen_tokens = []

    async def fake_orders(self, days_back=7, statuses=None, max_orders=200):
        token = self.client.auth.config.lwa.refresh_token
        seen_tokens.append(token)
        seller = (token or "UNKNOWN").split("|")[-1]
        return [_order(f"ORDER-{seller}-{i}") for i in range(1, 4)]

    async def fake_items(self, order_id, next_token=None):
        return [{
            "asin": f"ASIN-{order_id}",
            "seller_sku": f"SKU-{order_id}",
            "quantity_ordered": 1,
            "price_money": {"amount": "10.00", "currency_code": "USD"},
            "product_info": {"Title": "stub item"},
        }]

    monkeypatch.setattr(OrdersAPI, "get_orders_by_date_range", fake_orders)
    monkeypatch.setattr(SPAPIClient, "get_order_items", fake_items)
    return seen_tokens


# ============================================================================
# 判据 1：两店不相交
# ============================================================================
async def test_two_stores_do_not_share_orders(make_shop, with_key, app_creds, stub_spapi):
    """两家店、两个 seller、同一日期范围 ⇒ 订单号集合**交集为空**。

    ★ 改造前的实际行为：`fetch_daily_sales` 收了 `store_id` 却全程不用，
      两份结果的行内容**完全相同**（只有 `store_id` 标签不同）。
      这条用例在那时必然是红的，而且红得毫无歧义。
    """
    shop_a = await make_shop(refresh_token="Atzr|seller-a", region="US")
    shop_b = await make_shop(refresh_token="Atzr|seller-b", region="JP")

    src_a = await open_data_source(shop_a)
    src_b = await open_data_source(shop_b)

    d_to = date.today()
    d_from = d_to - timedelta(days=6)

    rows_a = src_a.fetch_daily_sales(shop_a, d_from, d_to)
    rows_b = src_b.fetch_daily_sales(shop_b, d_from, d_to)

    assert rows_a and rows_b, "桩没生效：两边都不该是空的"
    asins_a = {r["asin"] for r in rows_a}
    asins_b = {r["asin"] for r in rows_b}

    assert not (asins_a & asins_b), (
        f"两家店取到了同一批数据：交集={sorted(asins_a & asins_b)[:3]}。"
        "这说明数据源没有按店注入凭据（改造前的形态）。"
    )
    # 反向确认：两边的数据都**真的属于各自的 seller**
    assert all("seller-a" in a for a in asins_a)
    assert all("seller-b" in a for a in asins_b)
    # 每一行都带自己的 store_id（另一个串店观测面）
    assert {r["store_id"] for r in rows_a} == {shop_a}
    assert {r["store_id"] for r in rows_b} == {shop_b}


# ============================================================================
# 判据 2：不依赖 .env 里的 refresh_token
# ============================================================================
async def test_env_refresh_token_not_needed(make_shop, with_key, app_creds, monkeypatch, stub_spapi):
    """清空 `SPAPI_REFRESH_TOKEN` 后，两店仍能各自取数。

    ★ 这条判据挡的是「DB 里配了、其实还是用 .env 那把钥匙」这种**假绿**：
      只要实现里还留着全局单例，清空 .env 后必然取数失败。

    ★ 注意这里**不清 AWS 密钥**：AWS SigV4 是**应用级**凭据（我们自己的 IAM
      用户），不是卖家级。改造方案初稿写「把 SPAPI_AWS_* 也删掉」是错的 ——
      删了连签名都做不了，属于「判据本身写错」。凭据按店的部分只有
      LWA refresh_token / client_id / client_secret。
    """
    from core.config import config

    monkeypatch.setattr(config, "spapi_refresh_token", "", raising=False)

    shop_a = await make_shop(refresh_token="Atzr|seller-a")
    src = await open_data_source(shop_a)

    assert src._client.auth.config.lwa.refresh_token == "Atzr|seller-a"

    d_to = date.today()
    rows = src.fetch_daily_sales(shop_a, d_to - timedelta(days=2), d_to)
    assert rows, "清空 .env 的 refresh_token 后取数失败 —— 说明还在依赖全局钥匙"


# ============================================================================
# 判据 3：未授权硬失败，且不产行
# ============================================================================
async def test_unauthorized_store_raises_and_yields_no_rows(bare_shop, with_key, app_creds, stub_spapi):
    """没有凭据的店 ⇒ 抛 `StoreNotConnected`，**一行都不产出**。

    ★ 为什么断言「也没有调用到底层 API」：如果实现是「先拿 mock 顶上」，
      桩的 `seen_tokens` 会多出一条 `None` —— 那就是「向平台发了一次请求
      但用的是空凭据」，在这之前它更可能返回的是编造数据。
    """
    with pytest.raises(StoreNotConnected) as ei:
        await open_data_source(bare_shop)

    assert ei.value.reason == "no_credentials"
    assert stub_spapi == [], "未授权的店不该走到任何一次平台调用"


async def test_unauthorized_store_does_not_fall_back_to_mock(
    bare_shop, with_key, app_creds, monkeypatch
):
    """即便 DEMO_MODE 开着，**非演示店**也不许落 mock。

    ★ 这是「无凭据 ⇒ mock」那条老路留下的最大风险：演示档下打开系统，
      看什么都正常，于是没人会发现「其实一家店都没授权」。
      判据钉在**店铺类型**上（is_demo），不是钉在环境变量上 ——
      两个条件都满足才落 mock（见 `open_data_source` 注释）。
    """
    from core.config import config as settings

    monkeypatch.setattr(settings, "demo_mode", True, raising=False)

    with pytest.raises(StoreNotConnected):
        await open_data_source(bare_shop)


# ============================================================================
# 判据 4：配置真的注进去了（挡「注入了空值」）
# ============================================================================
async def test_credential_reaches_client_auth(make_shop, with_key, app_creds):
    """`_client.auth.config.lwa.refresh_token` == 该店密文的解密值。

    ★ 这条挡的正是改造前那个形态：`self._auth = get_spapi_auth()` 看起来
      「注入了凭据」，实际 `client.auth` 是**另一个**实例、而且配置是空的。
      只断言「取数成功」是发现不了的（mock 会兜住）。
    """
    token = "Atzr|injected-" + uuid.uuid4().hex[:6]
    shop = await make_shop(refresh_token=token)

    src = await open_data_source(shop)

    assert src._client.auth is not None
    assert src._client.auth.config.lwa.refresh_token == token
    assert src._client.auth.config.aws.access_key == "AKIATESTFORM000000"
    # 实例自己也得知道自己属于哪家店（`_assert_store` 的依据）
    assert src._credential.store_id == shop


async def test_source_rejects_other_store_id(make_shop, with_key, app_creds, stub_spapi):
    """拿 A 店的实例去查 B 店 ⇒ 立刻 ValueError。

    ★ 这类错误不会自己暴露：它只会**返回别人的数据**。
      一次字符串比较换掉一整类「传错变量」事故。
    """
    shop_a = await make_shop(refresh_token="Atzr|seller-a")
    shop_b = await make_shop(refresh_token="Atzr|seller-b")
    src_a = await open_data_source(shop_a)

    with pytest.raises(ValueError):
        src_a.fetch_daily_sales(shop_b, date.today(), date.today())

    # ★ 断言「一次平台调用都没发生」：守卫若写成了「先取数再校验」，
    #   这里会多出一条记录 —— 而那种形态已经在拿别人的数据了。
    assert stub_spapi == [], "归属校验必须在发起任何平台调用之前"


async def test_marketplace_follows_store(make_shop, with_key, app_creds):
    """站点跟着店铺走（日本店的客户端默认站点必须是 JP）。

    ★ 改造前所有店都是 US：日本站的订单会带着 US 的 `marketplaceIds` 去查，
      返回 **0 条且不报错**。
    """
    from platforms.amazon.sp_api.models import Marketplace

    shop_jp = await make_shop(refresh_token="Atzr|seller-jp", region="JP")
    src = await open_data_source(shop_jp)

    assert src._marketplace is Marketplace.JP
    assert src._client.default_marketplace == Marketplace.JP.value

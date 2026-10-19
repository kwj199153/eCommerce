"""
数据源层回归测试

覆盖：
1. `is_available()` 只回答「本进程有没有资格调 SP-API」（应用级），不再看卖家级 refresh_token
2. SpApiDataSource 完整实现 AmazonDataSource 抽象接口
3. 真实 SP-API 返回结构 → 表结构的字段映射（用桩客户端，不联网）
4. 归属守卫：拿 A 店的实例去查 B 店，必须在进入网络层**之前**报错

★ 第 386 轮改造后，本文件的构造方式整体变了，原因逐条写在这里：

  - 旧工厂 `get_data_source(prefer=...)` 已**删除** —— 它没有 `store_id` 参数，
    问的是「这个进程有没有凭据」，于是所有店共用同一把钥匙、没凭据就静默喂 mock。
    新的唯一入口是 `open_data_source(store_id)`，端到端行为在
    `test_data_source_per_store.py`（真库 + 桩网络）里覆盖，本文件不重复。

  - `SpApiDataSource()` **不再支持无参构造**：必须注入 `StoreCredential`。
    所以这里手工造一份「假的真凭据」—— 不是 `unittest.mock`，而是真的
    `StoreCredential` 实例。理由：单测要测的是「拿到凭据之后字段怎么映射」，
    用 MagicMock 会把 `credential.config.aws.region` 这类属性链变成
    任意返回值的 Mock，于是「配置有没有被真的读到」这件事测不出来。

  - `store_id` 由 `int` 变成 `str`（`stores_store.id` 就是字符串）。
    所有取数调用都传 `SID`，因为 `_assert_store()` 会拦住「传了个别的店」。
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from modules.amazon_sp.data_sources import (
    AmazonDataSource,
    MockAmazonDataSource,
    SpApiDataSource,
    StoreCredential,
)
from platforms.amazon.sp_api.auth import AWSCredentials, LWACredentials, SPAPIConfig
from platforms.amazon.sp_api.models import Marketplace

#: 本文件里所有店铺 id 都用它。取数方法会把它和实例的归属比一次，
#: 随便写个 "1" 会被 `_assert_store()` 当场拦下（那是特性，不是障碍）。
SID = "store_test"


def _credential(store_id: str = SID, marketplace=Marketplace.US) -> StoreCredential:
    """造一份**结构真实**的按店凭据（不读库、不联网）。"""
    return StoreCredential(
        store_id=store_id,
        source="form",
        seller_id="A1SELLER001",
        marketplace=marketplace,
        config=SPAPIConfig(
            lwa=LWACredentials(
                client_id="amzn1.application-oa2-client.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                client_secret="secret-of-the-app",
                refresh_token="Atzr|form-refresh-token-of-this-store",
            ),
            aws=AWSCredentials(
                access_key="AKIAAAAAAAAAAAAAAAAA",
                secret_key="secret",
                region="us-east-1",
            ),
            use_sandbox=False,
        ),
        note="单测手工构造",
    )


# ====== 可用性：只判应用级 ======

def test_is_available_ignores_seller_level_refresh_token(monkeypatch):
    """`SPAPI_REFRESH_TOKEN` 是**卖家级**凭据，不该参与「应用能不能用」的判定。

    ★ 改造前它算在里面，造成两个方向都错：
      · 一家店都没授权 ⇒ 判 False ⇒ 工厂回退 mock ⇒ 真实客户看到编造数据；
      · `.env` 里留着一个 token ⇒ 判 True ⇒ 所有店铺拿同一把钥匙取数。
    """
    from core.config import config as settings

    monkeypatch.setattr(settings, "spapi_lwa_client_id", "amzn1.application-oa2-client.bbbb", raising=False)
    monkeypatch.setattr(settings, "spapi_lwa_client_secret", "app-secret", raising=False)
    monkeypatch.setattr(settings, "spapi_aws_access_key", "AKIABBBBBBBBBBBBBBBB", raising=False)
    monkeypatch.setattr(settings, "spapi_aws_secret_key", "aws-secret", raising=False)

    # 卖家级 token 无论是空、是值，都不该改变结论
    for token in ("", "Atzr|some-seller-token"):
        monkeypatch.setattr(settings, "spapi_refresh_token", token, raising=False)
        ok, reason = SpApiDataSource.is_available()
        assert ok is True, f"应用级齐全时应可用（token={token!r}）：{reason}"


def test_is_available_reports_missing_app_level(monkeypatch):
    """缺应用级凭据（或仍是占位符）必须判不可用，并**点名**缺哪个环境变量。"""
    from core.config import config as settings

    monkeypatch.setattr(settings, "spapi_lwa_client_id", "your-lwa-client-id", raising=False)
    monkeypatch.setattr(settings, "spapi_lwa_client_secret", "app-secret", raising=False)
    monkeypatch.setattr(settings, "spapi_aws_access_key", "AKIABBBBBBBBBBBBBBBB", raising=False)
    monkeypatch.setattr(settings, "spapi_aws_secret_key", "aws-secret", raising=False)

    ok, reason = SpApiDataSource.is_available()
    assert ok is False
    assert "SPAPI_LWA_CLIENT_ID" in reason, reason


def test_placeholder_detection():
    assert SpApiDataSource._is_placeholder("your-lwa-client-id") is True
    assert SpApiDataSource._is_placeholder("") is True
    assert SpApiDataSource._is_placeholder("   ") is True
    assert SpApiDataSource._is_placeholder("changeme") is True
    assert SpApiDataSource._is_placeholder("amzn1.application-oa2-client.abc") is False


def test_no_arg_construction_is_rejected():
    """无参构造必须当场 `TypeError`。

    ★ 旧签名 `(config=None, marketplace=None)` + `config or SPAPIConfig()` 造出
      空配置传给 client，而 `SPAPIClient` 的判据是 `X if config else Y` ——
      空 dataclass 是**真值** ⇒ 永远走「自建空配置」，带凭据的实例从未被调用。
      因此这里的默认值不是「图省事」，是那条死路的入口。
    """
    with pytest.raises(TypeError):
        SpApiDataSource()  # type: ignore[call-arg]


def test_spapi_implements_full_interface():
    assert issubclass(SpApiDataSource, AmazonDataSource)
    # 抽象方法未全部实现时，实例化会抛 TypeError
    src = SpApiDataSource(_credential())
    for method in (
        "fetch_credentials", "fetch_daily_sales", "fetch_ad_metrics",
        "fetch_listings", "fetch_inventory", "fetch_competitors", "fetch_report_tasks",
    ):
        assert callable(getattr(src, method)), method
        assert getattr(src, method).__doc__, f"{method} 缺少 docstring"


# ====== 归属守卫 ======

def test_source_rejects_other_store_id(monkeypatch):
    """拿 A 店的实例查 B 店 → 报错，且**一次网络调用都不发生**。

    ★ 为什么断言「没发生网络调用」而不是只断言抛错：第一版守卫只写在
      `fetch_credentials()` 里，6 个 `fetch_*` 一个都没加。当时这条用例
      **真的发出了请求**（拿到 401）才被发现 —— 只断言「抛错」的话，
      `requests`/`httpx` 抛的网络异常会让它假绿。
    """
    src = SpApiDataSource(_credential("store_aaa"))

    calls: list[str] = []

    async def boom(*a, **kw):  # pragma: no cover - 走到这里就是漏了守卫
        calls.append("called")
        raise AssertionError("归属守卫失效：拿 A 店的凭据去查 B 店，仍然进了网络层")

    src._client = SimpleNamespace(
        get_order_items=boom,
        get_inventory_summaries=boom,
        get_item_by_asin=boom,
        get_item_offers=boom,
    )
    src._orders = SimpleNamespace(get_orders_by_date_range=boom, track_order=boom)
    src._advertising = SimpleNamespace(get_campaigns=boom)
    src._products = SimpleNamespace(get_competitor_listings=boom)

    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_daily_sales("store_bbb", date(2026, 9, 1), date(2026, 9, 10))
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_inventory("store_bbb")
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_ad_metrics("store_bbb", date(2026, 9, 1), date(2026, 9, 10))
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_listings("store_bbb", date(2026, 9, 1), date(2026, 9, 10), asins=["B0X"])
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_competitors("store_bbb", date(2026, 9, 1), date(2026, 9, 10), asins=["B0X"])
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_report_tasks("store_bbb", date(2026, 9, 1), date(2026, 9, 10))
    with pytest.raises(ValueError, match="归属不符"):
        src.fetch_credentials("store_bbb")

    assert calls == [], "归属守卫没有在进入网络层之前生效"


def test_empty_store_id_is_normalized_to_own():
    """空 `store_id` 归一成本店 id，而不是「随便哪家」。"""
    src = SpApiDataSource(_credential())
    assert src.fetch_report_tasks("", date(2026, 9, 1), date(2026, 9, 10)) == []
    assert src._assert_store("") == SID


# ====== 字段映射（桩客户端） ======

@pytest.fixture
def stubbed_source():
    """造一个把网络层全部替换为桩的 SpApiDataSource"""
    src = SpApiDataSource(_credential())

    async def fake_get_orders_by_date_range(days_back=7, statuses=None, max_orders=200):
        return [
            SimpleNamespace(
                amazon_order_id="111-0000001-0000001",
                purchase_date=datetime(2026, 9, 5, 10, 0),
                order_status="Shipped",
            ),
            SimpleNamespace(
                amazon_order_id="111-0000002-0000002",
                purchase_date=datetime(2026, 9, 5, 15, 30),
                order_status="Shipped",
            ),
        ]

    async def fake_get_order_items(order_id, next_token=None):
        return [{
            "asin": "B0TEST0001",
            "seller_sku": "SKU-1",
            "quantity_ordered": 2,
            "quantity_shipped": 2,
            "price_money": {"amount": 19.99, "currency_code": "USD"},
            "product_info": {"Title": "Test Widget"},
        }]

    async def fake_get_inventory_summaries(*a, **kw):
        return [SimpleNamespace(
            asin="B0TEST0001", seller_sku="SKU-1",
            fulfillable_quantity=120, inbound_working_quantity=10,
            inbound_shipped_quantity=5, inbound_receiving_quantity=5,
            total_quantity=140,
        )]

    async def fake_get_campaigns(**kw):
        return [{
            "campaignId": "C1", "name": "SP-Auto", "type": "sponsoredProducts",
            "impressions": 1000, "clicks": 20, "cost": 15.0, "sales": 100.0,
            "purchases": 5, "targetingType": "AUTO", "currency": "USD",
        }]

    async def fake_get_competitor_listings(asin):
        return {
            "competitor_asin": asin, "title": "Rival Widget", "brand": "Rival",
            "price": 21.5, "price_vs_own": 1.51, "bsr_rank": 1234,
            "review_count": 500, "rating": 4.4, "has_buybox": True,
            "buybox_price": 21.5, "price_change": "STABLE", "fulfillment": "FBA",
        }

    async def fake_get_item_by_asin(asin):
        return SimpleNamespace(asin=asin, title="My Widget", brand="MyBrand",
                               product_type="WIDGET")

    async def fake_get_item_offers(asin, **kw):
        price = SimpleNamespace(amount=19.99, currency_code="USD")
        offer = SimpleNamespace(is_buy_box_winner=True,
                                buying_price=SimpleNamespace(price=price))
        return SimpleNamespace(asin=asin, offers=[offer])

    src._orders = SimpleNamespace(get_orders_by_date_range=fake_get_orders_by_date_range)
    src._advertising = SimpleNamespace(get_campaigns=fake_get_campaigns)
    src._products = SimpleNamespace(get_competitor_listings=fake_get_competitor_listings)
    src._client = SimpleNamespace(
        get_order_items=fake_get_order_items,
        get_inventory_summaries=fake_get_inventory_summaries,
        get_item_by_asin=fake_get_item_by_asin,
        get_item_offers=fake_get_item_offers,
    )
    return src


async def test_daily_sales_mapping(stubbed_source):
    rows = stubbed_source.fetch_daily_sales(
        SID, date(2026, 9, 1), date(2026, 9, 10),
    )
    assert rows, "应聚合出至少一条记录"
    row = rows[0]
    for key in ("store_id", "date", "asin", "sku", "units_ordered",
                "ordered_revenue", "net_revenue", "currency"):
        assert key in row, f"缺少字段 {key}"

    assert row["store_id"] == SID
    assert row["asin"] == "B0TEST0001"
    assert row["sku"] == "SKU-1"
    assert row["units_ordered"] == 4          # 2 单 × 2 件
    assert row["ordered_revenue"] == pytest.approx(79.96, abs=0.01)
    assert row["order_count"] == 2
    assert row["date"] == "2026-09-05"
    # 退款需结算报告，不得臆造
    assert row["units_refunded"] == 0
    assert row["refund_amount"] == 0.0


async def test_daily_sales_filters_by_asin(stubbed_source):
    rows = stubbed_source.fetch_daily_sales(
        SID, date(2026, 9, 1), date(2026, 9, 10), asins=["B0OTHER"],
    )
    assert rows == []


async def test_inventory_mapping(stubbed_source):
    rows = stubbed_source.fetch_inventory(SID, snapshot_date=date(2026, 9, 10))
    assert len(rows) == 1
    row = rows[0]
    assert row["asin"] == "B0TEST0001"
    assert row["fulfillable_quantity"] == 120
    assert row["inbound_quantity"] == 20      # 10 + 5 + 5
    assert row["total_quantity"] == 140
    # 库龄分段需报表，不得编造
    assert row["aged_0_90_days"] == 0
    assert row["health_status"] == "UNKNOWN"


async def test_ad_metrics_mapping(stubbed_source):
    rows = stubbed_source.fetch_ad_metrics(SID, date(2026, 9, 1), date(2026, 9, 10))
    assert len(rows) == 1
    row = rows[0]
    assert row["campaign_name"] == "SP-Auto"
    assert row["report_type"] == "sp"
    assert row["impressions"] == 1000
    assert row["clicks"] == 20
    assert row["ctr"] == pytest.approx(2.0, abs=0.01)
    assert row["cpc"] == pytest.approx(0.75, abs=0.01)
    assert row["acos"] == pytest.approx(15.0, abs=0.01)
    assert row["roas"] == pytest.approx(6.67, abs=0.01)


async def test_listings_mapping(stubbed_source):
    rows = stubbed_source.fetch_listings(SID, date(2026, 9, 1), date(2026, 9, 10),
                                         asins=["B0TEST0001"])
    assert len(rows) == 1
    row = rows[0]
    assert row["asin"] == "B0TEST0001"
    assert row["title"] == "My Widget"
    assert row["brand"] == "MyBrand"
    assert row["buybox_price"] == pytest.approx(19.99, abs=0.01)
    # BSR / 评论数 SP-API 不提供 → None，不编造
    assert row["bsr_rank"] is None
    assert row["review_count"] is None


async def test_listings_requires_asins(stubbed_source):
    assert stubbed_source.fetch_listings(SID, date(2026, 9, 1), date(2026, 9, 10)) == []


async def test_competitors_mapping(stubbed_source):
    rows = stubbed_source.fetch_competitors(SID, date(2026, 9, 1), date(2026, 9, 10),
                                            asins=["B0RIVAL001"])
    assert len(rows) == 1
    row = rows[0]
    assert row["competitor_asin"] == "B0RIVAL001"
    assert row["brand"] == "Rival"
    assert row["price"] == pytest.approx(21.5)
    assert row["price_change"] == "STABLE"


def test_report_tasks_returns_empty_by_design(stubbed_source):
    """SP-API 无「报表任务列表」接口，任务历史属于本地调度记录"""
    assert stubbed_source.fetch_report_tasks(SID, date(2026, 9, 1), date(2026, 9, 10)) == []


def test_credentials_snapshot_never_leaks_tokens(stubbed_source):
    """`fetch_credentials()` 返回的是**真读过的凭据指纹**，且不含任何 token。

    ★ 改造前它返回 `refresh_token="***"` 这类打码值：看着像「有值但被打码」，
      实际调用方拿它做不了任何事，还会让人以为凭据真的被读到了。
      `***` 与「字段不存在」在语义上不是一回事 —— 后者才诚实。
    """
    rows = stubbed_source.fetch_credentials(SID)
    assert len(rows) == 1
    snap = rows[0]
    assert snap["store_id"] == SID
    assert snap["source"] == "form"
    assert snap["seller_id"] == "A1SELLER001"
    assert snap["marketplace_id"] == Marketplace.US.value
    assert snap["has_access_token"] is False

    text = repr(snap)
    for forbidden in ("refresh_token", "access_token=", "Atzr|", "secret"):
        assert forbidden not in text, f"凭据快照泄漏了 {forbidden!r}：{text}"


# ====== 显式 mock 仍然可用（脚本 / 演示灌数） ======

def test_mock_source_still_constructible():
    """`prefer="mock"` 路径（脚本 / 种子）不经过凭据链，必须一直可用。"""
    src = MockAmazonDataSource(seed=42)
    assert isinstance(src, AmazonDataSource)
    rows = src.fetch_daily_sales(SID, date(2026, 9, 1), date(2026, 9, 10))
    assert rows, "演示数据不应为空"

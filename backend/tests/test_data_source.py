"""
数据源层回归测试

覆盖：
1. 工厂在凭据缺失/占位符时回退 Mock，强制 sp_api 时抛错
2. SpApiDataSource 完整实现 AmazonDataSource 抽象接口
3. 真实 SP-API 返回结构 → 表结构的字段映射（用桩客户端，不联网）
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from modules.amazon_sp.data_sources import (
    AmazonDataSource,
    MockAmazonDataSource,
    SpApiDataSource,
    get_data_source,
)


# ====== 工厂选择 ======

def test_factory_falls_back_to_mock_when_credentials_are_placeholders():
    """当前 .env 是占位符 → auto 必须回退 Mock，不能误用真实源"""
    ok, reason = SpApiDataSource.is_available()
    assert ok is False
    assert "凭据" in reason

    src = get_data_source()
    assert isinstance(src, MockAmazonDataSource)


def test_factory_force_sp_api_raises_without_credentials():
    if SpApiDataSource.is_available()[0]:
        pytest.skip("当前环境已配置真实 SP-API 凭据")
    with pytest.raises(RuntimeError):
        get_data_source("sp_api")


def test_placeholder_detection():
    assert SpApiDataSource._is_placeholder("your-lwa-client-id") is True
    assert SpApiDataSource._is_placeholder("") is True
    assert SpApiDataSource._is_placeholder("   ") is True
    assert SpApiDataSource._is_placeholder("changeme") is True
    assert SpApiDataSource._is_placeholder("amzn1.application-oa2-client.abc") is False


def test_spapi_implements_full_interface():
    assert issubclass(SpApiDataSource, AmazonDataSource)
    # 抽象方法未全部实现时，实例化会抛 TypeError
    src = SpApiDataSource()
    for method in (
        "fetch_credentials", "fetch_daily_sales", "fetch_ad_metrics",
        "fetch_listings", "fetch_inventory", "fetch_competitors", "fetch_report_tasks",
    ):
        assert callable(getattr(src, method)), method
        assert getattr(src, method).__doc__, f"{method} 缺少 docstring"


# ====== 字段映射（桩客户端） ======

@pytest.fixture
def stubbed_source():
    """造一个把网络层全部替换为桩的 SpApiDataSource"""
    src = SpApiDataSource()

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
        1, date(2026, 9, 1), date(2026, 9, 10),
    )
    assert rows, "应聚合出至少一条记录"
    row = rows[0]
    for key in ("store_id", "date", "asin", "sku", "units_ordered",
                "ordered_revenue", "net_revenue", "currency"):
        assert key in row, f"缺少字段 {key}"

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
        1, date(2026, 9, 1), date(2026, 9, 10), asins=["B0OTHER"],
    )
    assert rows == []


async def test_inventory_mapping(stubbed_source):
    rows = stubbed_source.fetch_inventory(1, snapshot_date=date(2026, 9, 10))
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
    rows = stubbed_source.fetch_ad_metrics(1, date(2026, 9, 1), date(2026, 9, 10))
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
    rows = stubbed_source.fetch_listings(1, date(2026, 9, 1), date(2026, 9, 10),
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
    assert stubbed_source.fetch_listings(1, date(2026, 9, 1), date(2026, 9, 10)) == []


async def test_competitors_mapping(stubbed_source):
    rows = stubbed_source.fetch_competitors(1, date(2026, 9, 1), date(2026, 9, 10),
                                            asins=["B0RIVAL001"])
    assert len(rows) == 1
    row = rows[0]
    assert row["competitor_asin"] == "B0RIVAL001"
    assert row["brand"] == "Rival"
    assert row["price"] == pytest.approx(21.5)
    assert row["price_change"] == "STABLE"


def test_report_tasks_returns_empty_by_design(stubbed_source):
    """SP-API 无「报表任务列表」接口，任务历史属于本地调度记录"""
    assert stubbed_source.fetch_report_tasks(1, date(2026, 9, 1), date(2026, 9, 10)) == []


def test_credentials_masked(stubbed_source):
    creds = stubbed_source.fetch_credentials(7)
    assert creds[0]["store_id"] == 7
    assert creds[0]["refresh_token"] == "***"
    assert creds[0]["access_token"] is None

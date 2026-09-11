"""
Amazon SP-API 真实数据源

把 platforms/amazon/sp_api 下已实现的真实 SP-API 客户端接入
AmazonDataSource 抽象接口，使上层业务（Agent / 报表脚本）从「模拟数据」
切换到「真实亚马逊数据」时只需改一行工厂调用。

架构说明：
    AmazonDataSource (base.py, 同步接口)
      ├── MockAmazonDataSource   —— 演示/开发用，无需凭据
      └── SpApiDataSource        —— 本文件，真实 SP-API

    由于 base 接口是同步的，而 SP-API 客户端是异步的，本类通过 `_run()`
    做「同步 → 异步」桥接：
      - 在普通同步上下文（如 ingest 脚本）中：直接用事件循环 run
      - 在已运行的事件循环中（如 FastAPI 请求内）：放到独立线程跑，避免嵌套

凭据来源（.env / Settings）：
    SPAPI_LWA_CLIENT_ID / SPAPI_LWA_CLIENT_SECRET / SPAPI_REFRESH_TOKEN
    SPAPI_AWS_ACCESS_KEY / SPAPI_AWS_SECRET_KEY / SPAPI_AWS_REGION
    SPAPI_USE_SANDBOX

未配置凭据时 is_available() 返回 False，工厂自动回退到 Mock。

字段映射约定：
    - 真实 API 能直接提供的字段 → 如实填充
    - 需要「结算报告 / 报表解析」才能得到的派生字段（净收入、预估利润、
      退货数等）→ 填 0 / None，并在 docstring 标注来源，绝不编造
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional

from modules.amazon_sp.data_sources.base import AmazonDataSource

logger = logging.getLogger(__name__)


def _money(amount_obj) -> tuple[float, str]:
    """从 MoneyType / dict 中取 (金额, 币种)"""
    if amount_obj is None:
        return 0.0, "USD"
    if isinstance(amount_obj, dict):
        return float(amount_obj.get("amount", 0) or 0), amount_obj.get("currency_code", "USD")
    return float(getattr(amount_obj, "amount", 0) or 0), getattr(amount_obj, "currency_code", "USD")


class SpApiDataSource(AmazonDataSource):
    """基于 Amazon SP-API 的真实数据源"""

    #: 单次拉取的最大订单数（防止全量扫描把配额打满）
    DEFAULT_MAX_ORDERS = 200

    def __init__(
        self,
        config=None,
        marketplace=None,
        max_orders: int = DEFAULT_MAX_ORDERS,
    ):
        from platforms.amazon.sp_api.auth import SPAPIConfig, get_spapi_auth
        from platforms.amazon.sp_api.client import SPAPIClient
        from platforms.amazon.sp_api.models import Marketplace, OrderStatus  # noqa: F401
        from platforms.amazon.sp_api.advertising import AdvertisingAPI
        from platforms.amazon.sp_api.orders import OrdersAPI
        from platforms.amazon.sp_api.products import ProductsAPI
        from platforms.amazon.sp_api.reports import ReportsAPI

        self._config = config or SPAPIConfig()
        self._marketplace = marketplace or Marketplace.US
        self.max_orders = max_orders

        self._client = SPAPIClient(self._config, default_marketplace=self._marketplace)
        self._orders = OrdersAPI(self._client)
        self._products = ProductsAPI(self._client)
        self._reports = ReportsAPI(self._client)
        self._advertising = AdvertisingAPI(self._client)

        self._auth = get_spapi_auth()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ---------- 同步 / 异步桥接 ----------

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def _run(self, coro):
        """
        在同步接口中执行协程。

        - 无运行中的事件循环 → 复用本实例的常驻 loop
        - 已在事件循环内（FastAPI 请求等）→ 丢到独立线程执行，避免嵌套报错
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._get_loop().run_until_complete(coro)

        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(coro)).result()

    # ---------- 可用性 ----------

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        """
        判断配置值是否是占位符/示例值。

        .env 模板里常见 `your-lwa-client-id`、`xxx`、`changeme` 这类占位，
        它们「非空但不值钱」，必须视为未配置，否则数据源工厂会误判为
        可用并切到真实源，导致线上全部请求 401。
        """
        if not value:
            return True
        v = str(value).strip().lower()
        if not v:
            # 纯空白（"   "）同样视为未配置
            return True
        return (
            v.startswith("your-")
            or v.startswith("your_")
            or v in {"xxx", "xxxx", "changeme", "change-me", "todo", "none", "null"}
            or v.startswith("your ")
        )

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        """
        检查是否具备调用真实 SP-API 的条件。

        不仅检查「是否为空」，还排除占位符（your-xxx / changeme 等）。

        Returns:
            (是否可用, 原因说明)
        """
        try:
            from core.config import config as settings
        except Exception as e:  # pragma: no cover
            return False, f"无法加载配置: {e}"

        required = [
            ("SPAPI_LWA_CLIENT_ID", "spapi_lwa_client_id"),
            ("SPAPI_LWA_CLIENT_SECRET", "spapi_lwa_client_secret"),
            ("SPAPI_REFRESH_TOKEN", "spapi_refresh_token"),
            ("SPAPI_AWS_ACCESS_KEY", "spapi_aws_access_key"),
            ("SPAPI_AWS_SECRET_KEY", "spapi_aws_secret_key"),
        ]

        missing = [
            env_name for env_name, attr in required
            if cls._is_placeholder(getattr(settings, attr, ""))
        ]

        if missing:
            return False, "缺少 SP-API 凭据（或仍为占位符）: " + ", ".join(missing)
        return True, "SP-API 凭据已配置"

    def get_source_info(self) -> dict:
        ok, reason = self.is_available()
        return {
            "source_type": "sp_api",
            "name": "SpApiDataSource",
            "description": "Amazon Selling Partner API 真实数据源",
            "marketplace": getattr(self._marketplace, "value", str(self._marketplace)),
            "sandbox": bool(getattr(self._config, "use_sandbox", False)),
            "credentials_ready": ok,
            "credentials_note": reason,
        }

    def health_check(self) -> dict:
        ok, reason = self.is_available()
        if not ok:
            return {"status": "error", "message": reason}
        try:
            start = datetime.now()
            alive = self._run(self._client.health_check())
            latency = (datetime.now() - start).total_seconds() * 1000
            return {
                "status": "ok" if alive else "degraded",
                "message": "SP-API 连通" if alive else "SP-API 无响应",
                "latency_ms": round(latency, 1),
            }
        except Exception as e:
            return {"status": "error", "message": f"SP-API 健康检查失败: {e}"}

    # ---------- 数据拉取接口 ----------

    def fetch_credentials(self, store_id: int) -> list[dict]:
        """
        返回当前配置的号店 OAuth 凭据记录。

        真实场景凭据由 SP-API 授权流程写入 amazon_credentials 表；
        此处从 Settings 组装一条只读记录，**不对 access_token 落明文**。
        """
        from core.config import config as settings

        now = datetime.now()
        return [{
            "store_id": store_id,
            "seller_id": getattr(settings, "spapi_lwa_client_id", ""),
            "region": getattr(settings, "spapi_aws_region", "us-east-1"),
            "marketplace_id": getattr(self._marketplace, "value", "US"),
            "access_token": None,  # 运行时由 SPAPIClientAuth 动态获取并缓存
            "refresh_token": "***",  # 不落明文
            "token_expires_at": None,
            "credential_status": "ACTIVE",
            "last_refreshed_at": now,
            "auth_scopes": ["sellingpartnerapi::migration"],
            "created_at": now,
            "updated_at": now,
        }]

    def fetch_daily_sales(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        拉取每日销售数据。

        数据来源：Orders API（get_orders_by_date_range + get_order_items）
        按 (日期, ASIN, SKU) 聚合。

        注意：
          - units_refunded / refund_amount 需结算报告（Settlement Report）才能准确，
            此处填 0，不臆造。
          - net_revenue 仅减去退款，未扣佣金/FBA 费（那属于利润测算模块的职责）。
          - estimated_* 字段留空，由 core/profit_engine.py 按费率计算。
        """
        days_back = max(1, (date_to - date_from).days + 1)
        orders = self._run(self._orders.get_orders_by_date_range(
            days_back=days_back, max_orders=self.max_orders,
        ))

        agg: dict[tuple, dict] = {}

        for order in orders:
            purchase = getattr(order, "purchase_date", None)
            if not purchase:
                continue
            order_date = purchase.date() if isinstance(purchase, datetime) else purchase
            if order_date < date_from or order_date > date_to:
                continue

            order_id = getattr(order, "amazon_order_id", "") or ""
            try:
                items = self._run(self._client.get_order_items(order_id))
            except Exception as e:
                logger.warning("SP-API 拉取订单项失败 order=%s: %s", order_id, e)
                continue

            for raw in items:
                item = self._as_item(raw)
                asin = item.get("asin") or ""
                sku = item.get("seller_sku") or ""
                if asins and asin not in asins:
                    continue

                qty = int(item.get("quantity_ordered") or 0)
                amount, currency = _money(item.get("price_money"))
                key = (order_date, asin, sku)
                row = agg.setdefault(key, {
                    "store_id": store_id,
                    "date": order_date.isoformat(),
                    "asin": asin,
                    "sku": sku,
                    "product_name": (item.get("product_info") or {}).get("Title"),
                    "units_ordered": 0,
                    "units_shipped": 0,
                    "units_refunded": 0,
                    "ordered_revenue": 0.0,
                    "refund_amount": 0.0,
                    "net_revenue": 0.0,
                    "estimated_fees": None,
                    "estimated_fba_fee": None,
                    "estimated_ad_spend": None,
                    "estimated_profit": None,
                    "currency": currency,
                    "order_count": 0,
                    "created_at": datetime.now(),
                })
                row["units_ordered"] += qty
                row["units_shipped"] += int(item.get("quantity_shipped") or 0)
                # price_money 是**单价**，营收须乘以件数，否则 qty>1 时被低估
                row["ordered_revenue"] = round(row["ordered_revenue"] + amount * qty, 2)
                row["order_count"] += 1

        for row in agg.values():
            row["net_revenue"] = round(row["ordered_revenue"] - row["refund_amount"], 2)

        return list(agg.values())

    def fetch_ad_metrics(
        self, store_id: int, date_from: date, date_to: date,
        report_types: Optional[list[str]] = None,
        campaign_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        拉取广告指标。

        数据来源：Advertising 封装（get_campaigns + get_search_term_report）
        注意：SP-API 本身不含广告数据，广告来自 Amazon Ads API，本封装已对接；
        无法拿到按天拆分的花费时，按活动汇总写入 date_to 当天，并在
        docstring 中明示（不做随机插值）。
        """
        try:
            campaigns = self._run(self._advertising.get_campaigns(
                start_date=date_from.isoformat(), end_date=date_to.isoformat(),
            ))
        except Exception as e:
            logger.warning("SP-API 拉取广告活动失败: %s", e)
            return []

        if campaign_names:
            campaigns = [c for c in campaigns if c.get("name") in campaign_names]

        records = []
        for camp in campaigns:
            camp_type = (camp.get("type") or "sponsoredProducts")
            report_type = {"sponsoredProducts": "sp", "sponsoredBrands": "sb",
                           "sponsoredDisplay": "sd"}.get(camp_type, "sp")
            if report_types and report_type not in report_types:
                continue

            impressions = int(camp.get("impressions") or 0)
            clicks = int(camp.get("clicks") or 0)
            spend = float(camp.get("cost") or camp.get("spend") or 0)
            sales = float(camp.get("sales") or 0)
            orders = int(camp.get("purchases") or camp.get("orders") or 0)

            records.append({
                "store_id": store_id,
                "date": date_to.isoformat(),
                "report_type": report_type,
                "campaign_id": str(camp.get("campaignId") or camp.get("id") or ""),
                "campaign_name": camp.get("name") or "",
                "ad_group_id": str(camp.get("adGroupId") or ""),
                "ad_group_name": camp.get("adGroupName") or "",
                "keyword_text": "",
                "target_id": "",
                "target_type": camp.get("targetingType") or "AUTO",
                "asin": camp.get("asin") or "",
                "impressions": impressions,
                "clicks": clicks,
                "ctr": round(clicks / impressions * 100, 2) if impressions else 0.0,
                "cpc": round(spend / clicks, 2) if clicks else 0.0,
                "spend": spend,
                "orders": orders,
                "sales": sales,
                "acos": round(spend / sales * 100, 2) if sales else 100.0,
                "roas": round(sales / spend, 2) if spend else 0.0,
                "currency": camp.get("currency") or "USD",
                "created_at": datetime.now(),
            })

        return records

    def fetch_listings(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        拉取 Listing 快照。

        数据来源：Catalog Items API（商品基本信息） + Product Pricing API
        （BuyBox 价格、报价数）。
        说明：BSR（b) 排名）来自 Sales Rank，Catalog API 不返回时填 None；
        评论数/评分需 Reviews 数据，SP-API 不提供，留 None。
        """
        if not asins:
            logger.warning("SpApiDataSource.fetch_listings 需要显式传入 asins（Catalog 不支持全量枚举）")
            return []

        records = []
        today = date_to.isoformat()

        for asin in asins:
            try:
                item = self._run(self._client.get_item_by_asin(asin))
            except Exception as e:
                logger.warning("SP-API 拉取商品失败 asin=%s: %s", asin, e)
                continue

            price = None
            buybox_price = None
            try:
                pricing = self._run(self._client.get_item_offers(asin))
                offers = getattr(pricing, "offers", []) or []
                winner = next((o for o in offers if getattr(o, "is_buy_box_winner", False)), None)
                if winner is not None:
                    buybox_price, _ = _money(getattr(getattr(winner, "buying_price", None), "price", None))
                if offers:
                    price, _ = _money(getattr(getattr(offers[0], "buying_price", None), "price", None))
            except Exception as e:
                logger.warning("SP-API 拉取报价失败 asin=%s: %s", asin, e)

            brand = getattr(item, "brand", None) or ""
            records.append({
                "store_id": store_id,
                "snapshot_date": today,
                "asin": asin,
                "title": getattr(item, "title", None) or "",
                "brand": brand,
                "category": getattr(item, "product_type", None) or "",
                "standard_price": price,
                "buybox_price": buybox_price,
                "bsr_rank": None,          # Catalog API 不返回 BSR，需 Sales Rank 单独获取
                "fulfillment_channel": None,
                "review_count": None,      # SP-API 不提供评论数
                "rating": None,            # SP-API 不提供评分
                "created_at": datetime.now(),
            })

        return records

    def fetch_inventory(
        self, store_id: int, snapshot_date: Optional[date] = None,
    ) -> list[dict]:
        """
        拉取 FBA 库存健康。

        数据来源：FBA Inventory API（summaries）。
        库龄分段（aged_*）需 GET_FBA_INVENTORY_AGED_DATA 报表，此处留 0。
        """
        d = snapshot_date or date.today()
        summaries = self._run(self._client.get_inventory_summaries())

        records = []
        for s in summaries:
            fulfillable = int(getattr(s, "fulfillable_quantity", 0) or 0)
            inbound = int(getattr(s, "inbound_working_quantity", 0) or 0) + \
                int(getattr(s, "inbound_shipped_quantity", 0) or 0) + \
                int(getattr(s, "inbound_receiving_quantity", 0) or 0)
            total = int(getattr(s, "total_quantity", fulfillable + inbound) or (fulfillable + inbound))

            records.append({
                "store_id": store_id,
                "snapshot_date": d.isoformat(),
                "asin": getattr(s, "asin", "") or "",
                "sku": getattr(s, "seller_sku", "") or "",
                "fulfillable_quantity": fulfillable,
                "inbound_quantity": inbound,
                "total_quantity": total,
                # 日均销量需销售数据推算，此处留空由上层计算
                "days_supply": None,
                "aged_0_90_days": 0,
                "aged_91_180_days": 0,
                "aged_181_270_days": 0,
                "aged_271_365_days": 0,
                "aged_365_plus_days": 0,
                "is_stagnant": False,
                "health_status": "UNKNOWN",
                "created_at": datetime.now(),
            })

        return records

    def fetch_competitors(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        拉取竞品快照。

        数据来源：Products API 封装（get_competitor_listings / track_prices）。
        需先用 Catalog 搜索或手工维护竞品 ASIN 列表。
        """
        if not asins:
            logger.warning("SpApiDataSource.fetch_competitors 需要显式传入竞品 asins")
            return []

        records = []
        today = date_to.isoformat()

        for asin in asins:
            try:
                detail = self._run(self._products.get_competitor_listings(asin))
            except Exception as e:
                logger.warning("SP-API 拉取竞品失败 asin=%s: %s", asin, e)
                continue

            if not detail:
                continue

            price = detail.get("price")
            records.append({
                "store_id": store_id,
                "snapshot_date": today,
                "competitor_asin": asin,
                "competes_with_asin": detail.get("competes_with") or "",
                "brand": detail.get("brand") or "",
                "title": detail.get("title") or "",
                "price": price,
                "price_vs_own": detail.get("price_vs_own"),
                "bsr_rank": detail.get("bsr_rank"),
                "review_count": detail.get("review_count"),
                "rating": detail.get("rating"),
                "has_buybox": detail.get("has_buybox"),
                "buybox_price": detail.get("buybox_price"),
                "price_change": detail.get("price_change"),
                "fulfillment": detail.get("fulfillment"),
                "created_at": datetime.now(),
            })

        return records

    def fetch_report_tasks(
        self, store_id: int, date_from: date, date_to: date,
    ) -> list[dict]:
        """
        拉取报表任务记录。

        说明：SP-API 的 Reports API 只提供「按 reportId 查询单个报表」，
        没有「列出历史任务」的接口。历史任务应由本地表
        amazon_report_tasks 自行记录（每次 create_report 后落库）。
        因此真实数据源此处返回空列表——不是缺失，而是语义如此：
        任务历史属于「我们自己的调度记录」，不属于平台数据。

        若需要单次报表状态，请直接用 ReportsAPI.get_report(report_id)。
        """
        logger.info(
            "fetch_report_tasks: SP-API 无「报表任务列表」接口，任务历史应取自本地表"
        )
        return []

    # ---------- 内部工具 ----------

    @staticmethod
    def _as_item(raw) -> dict:
        """把 get_order_items 返回的 dict / OrderItem 统一成 dict"""
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "model_dump"):
            return raw.model_dump()
        return dict(raw) if raw else {}

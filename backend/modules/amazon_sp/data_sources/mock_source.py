"""
Amazon SP-API Mock 数据源实现
==============================

实现 AmazonDataSource 基类接口，生成符合真实业务逻辑的模拟数据。
用于开发/测试阶段，让 Agent 在没有真实亚马逊 API 时也能跑完整流程。

切换到真实数据源时，只需替换为 SpApiDataSource，上层代码零改动。

数据特点：
- 3C数码 + 家居小家电跨境卖家（TechHome Pro, US Marketplace）
- 5 个自研 ASIN + 3-5 个竞品 ASIN
- 数据间逻辑一致（ACoS = spend/sales×100 等）
- 季节性波动（Q4 旺季系数）
- 包含「有问题」的 Campaign 和库存（供运营复盘分析用）

使用方式:
    from modules.amazon_sp.data_sources.mock_source import MockAmazonDataSource

    source = MockAmazonDataSource()
    sales = source.fetch_daily_sales(store_id=1, date_from=d1, date_to=d2)
    metrics = source.fetch_ad_metrics(store_id=1, date_from=d1, date_to=d2)
"""

import random
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from .base import AmazonDataSource


# ============================================================
# 卖家配置（可按需修改为从配置文件/数据库读取）
# ============================================================

SELLER_CONFIG = {
    "store_id": 1,
    "seller_id": "A1B2C3D4E5F6G7",
    "store_name": "TechHome Pro",
    "marketplace_id": "ATVPDKIKX0DER",  # US
    "region": "us",
    "currency": "USD",
}

# 自研产品线
OWN_PRODUCTS = [
    {"asin": "B0CF9X1K2M4", "sku": "THP-SMARTPLUG-10A",
     "title": "Smart Plug Mini Wi-Fi Enabled Outlet Compatible with Alexa and Google Home, 10A",
     "brand": "TechHome", "category": "Electronics > Smart Plugs",
     "standard_price": Decimal("12.99"), "fulfillment_channel": "FBA",
     "daily_units_range": (25, 80)},   # 爆款
    {"asin": "B0DL7N3P5Q8", "sku": "THP-USBC-HUB-7IN1",
     "title": "USB C Hub 7-in-1 Multiport Adapter with 4K HDMI Ethernet 100W PD USB 3.0 for MacBook",
     "brand": "TechHome", "category": "Computers > USB Hubs",
     "standard_price": Decimal("29.99"), "fulfillment_channel": "FBA",
     "daily_units_range": (8, 30)},
    {"asin": "B0EM8R4T6U2", "sku": "THP-LED-DESKLAMP",
     "title": "LED Desk Lamp with Wireless Charger Eye-Caring Table Lamp 5 Color Modes 10 Brightness Levels",
     "brand": "TechHome", "category": "Home Office > Desk Lamps",
     "standard_price": Decimal("34.99"), "fulfillment_channel": "FBA",
     "daily_units_range": (5, 18)},
    {"asin": "B0FN9S2V5W7", "sku": "THP-BT-SPEAKER-WTR",
     "title": "Portable Bluetooth Speaker IPX7 Waterproof 20W Loud Stereo Sound Outdoor Speaker with Bass+",
     "brand": "TechHome", "category": "Electronics > Portable Speakers",
     "standard_price": Decimal("24.99"), "fulfillment_channel": "FBA",
     "daily_units_range": (10, 35)},
    {"asin": "B0GH3T6Y8I1", "sku": "THP-KITCHEN-SCALE",
     "title": "Digital Kitchen Scale Food Scale 0.1g/11lb Precision LCD Display Tare Function Stainless Steel",
     "brand": "TechHome", "category": "Kitchen > Scales",
     "standard_price": Decimal("15.99"), "fulfillment_channel": "FBM",  # 自发货
     "daily_units_range": (3, 12)},
]

# 竞品 ASIN（每个自研产品对应 1-2 个竞品）
COMPETITOR_PRODUCTS = [
    # Smart Plug 竞品
    {"asin": "B08N5KWB9H", "brand": "TP-Link", "title": "Kasa Smart Plug Classic 15A, Smart Home Wi-Fi Outlet Works with Alexa & Google Home",
     "competes_with": "B0CF9X1K2M4", "price_advantage": -0.80},  # 比我们便宜 $0.80
    {"asin": "B08XLYPQJZ", "brand": "Amazon Basics", "title": "Amazon Basics Smart Plug with Alexa Voice Activation, 1-Pack",
     "competes_with": "B0CF9X1K2M4", "price_advantage": -2.00},
    # USB Hub 竞品
    {"asin": "B09VKR9Z3L", "brand": "Anker", "title": "Anker 332 USB-C Hub (5-in-1), with 4K HDMI Display, USB-C Data Port",
     "competes_with": "B0DL7N3P5Q8", "price_advantage": 5.00},  # 比我们贵 $5
    {"asin": "B08NL7RJ8W", "brand": "Satechi", "title": "Satechi USB-C Multiport Adapter with 4K HDMI (60Hz)",
     "competes_with": "B0DL7N3P5Q8", "price_advantage": 15.00},  # 高端竞品
    # Desk Lamp 竞品
    {"asin": "B07Q9MJKBV", "brand": "TaoTronics", "title": "TaoTronics LED Desk Lamp, Eye-Caring Table Lamps, 5 Color Modes",
     "competes_with": "B0EM8R4T6U2", "price_advantage": 3.00},
    # BT Speaker 竞品
    {"asin": "B08CWTG95V", "brand": "JBL", "title": "JBL Clip 4: Portable Speaker with Bluetooth, Built-in Carabiner, IP67 Waterproof",
     "competes_with": "B0FN9S2V5W7", "price_advantage": 10.00},
]

# 广告活动
CAMPAIGNS = [
    {"name": "SP-Manual-SmartPlug", "type": "sponsoredProducts", "targeting_type": "manual",
     "budget": Decimal("30.00"), "asins": ["B0CF9X1K2M4"]},
    {"name": "SP-Auto-Electronics", "type": "sponsoredProducts", "targeting_type": "auto",
     "budget": Decimal("50.00"), "asins": ["B0CF9X1K2M4", "B0DL7N3P5Q8", "B0FN9S2V5W7"]},
    {"name": "SP-Manual-USBHub", "type": "sponsoredProducts", "targeting_type": "manual",
     "budget": Decimal("40.00"), "asins": ["B0DL7N3P5Q8"]},
    {"name": "SP-Manual-DeskLamp", "type": "sponsoredProducts", "targeting_type": "manual",
     "budget": Decimal("25.00"), "asins": ["B0EM8R4T6U2"]},
    {"name": "SB-Brand-TechHome", "type": "sponsoredBrands", "targeting_type": "auto",
     "budget": Decimal("60.00"), "asins": ["B0CF9X1K2M4", "B0DL7N3P5Q8", "B0EM8R4T6U2", "B0FN9S2V5W7"]},
    {"name": "SD-Display-Retargeting", "type": "sponsoredDisplay", "targeting_type": "audience",
     "budget": Decimal("20.00"), "asins": ["B0CF9X1K2M4", "B0DL7N3P5Q8"]},
]

# 手动广告关键词 + benchmark
KEYWORDS = {
    "SP-Manual-SmartPlug": [
        ("smart plug", 135000, Decimal("0.85"), "High"),
        ("wifi outlet", 22000, Decimal("0.72"), "Medium"),
        ("alexa smart plug", 33000, Decimal("0.95"), "High"),
        ("smart socket wifi", 8500, Decimal("0.55"), "Low"),
        ("mini smart plug", 18000, Decimal("0.68"), "Medium"),
        ("google home plug", 12000, Decimal("0.62"), "Medium"),
        ("smart outlet timer", 6500, Decimal("0.48"), "Low"),
        ("usb c smart plug", 4000, Decimal("0.42"), "Low"),
        ("energy monitoring plug", 5500, Decimal("0.51"), "Low"),
        ("smart plug no hub needed", 9000, Decimal("0.65"), "Medium"),
    ],
    "SP-Manual-USBHub": [
        ("usb c hub", 165000, Decimal("0.78"), "High"),
        ("usb c adapter macbook", 45000, Decimal("0.92"), "High"),
        ("macbook pro usb hub", 38000, Decimal("1.05"), "High"),
        ("usb c multiport adapter", 28000, Decimal("0.75"), "Medium"),
        ("usb c hub hdmi ethernet", 15000, Decimal("0.82"), "Medium"),
        ("thunderbolt hub", 22000, Decimal("1.15"), "High"),
        ("usb c docking station", 35000, Decimal("1.08"), "High"),
        ("macbook air accessories", 25000, Decimal("0.65"), "Medium"),
        ("usb hub type c", 19000, Decimal("0.58"), "Medium"),
        ("7 in 1 usb c hub", 12000, Decimal("0.70"), "Medium"),
    ],
    "SP-Manual-DeskLamp": [
        ("led desk lamp", 95000, Decimal("0.55"), "High"),
        ("desk lamp with wireless charger", 18000, Decimal("0.62"), "Medium"),
        ("eye caring desk lamp", 12000, Decimal("0.48"), "Medium"),
        ("led table lamp dimmable", 14000, Decimal("0.52"), "Medium"),
        ("office desk lamp", 30000, Decimal("0.45"), "Medium"),
        ("desk lamp usb charging", 8000, Decimal("0.42"), "Low"),
        ("modern desk lamp", 22000, Decimal("0.50"), "Medium"),
        ("led desk light", 16000, Decimal("0.47"), "Medium"),
        ("study lamp led", 10000, Decimal("0.44"), "Low"),
        ("desk lamp touch control", 11000, Decimal("0.46"), "Low"),
    ],
}


class MockAmazonDataSource(AmazonDataSource):
    """
    Mock 数据源 —— 实现所有 AmazonDataSource 接口方法。

    设计原则：
    - 所有数据生成逻辑封装在此类中
    - 上层调用方只看到标准化的 dict 列表
    - 随机种子可固定（方便测试复现）
    """

    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self._config = SELLER_CONFIG
        self._products = OWN_PRODUCTS
        self._competitors = COMPETITOR_PRODUCTS
        self._campaigns = CAMPAIGNS

    # ---- 工具方法 ----

    def _seasonal_factor(self, d: date) -> float:
        """季节性系数：Q4 旺季上涨"""
        month = d.month
        if month >= 10:
            base = 1.0 + (month - 9) * 0.3
            if month == 12 and d.day >= 15:
                base *= 1.2
            return base + self._rng.uniform(-0.1, 0.1)
        elif month >= 6:
            return 0.85 + self._rng.uniform(-0.1, 0.15)
        else:
            return 1.0 + self._rng.uniform(-0.15, 0.2)

    def _weekend_boost(self, d: date) -> float:
        if d.weekday() >= 5:
            return self._rng.uniform(1.1, 1.25)
        return self._rng.uniform(0.88, 1.02)

    def _product_by_asin(self, asin: str) -> Optional[dict]:
        for p in self._products:
            if p["asin"] == asin:
                return p
        return None

    # ---- 接口实现 ----

    def get_source_info(self) -> dict:
        return {
            "source_type": "mock",
            "name": "MockAmazonDataSource",
            "description": "模拟数据源，生成符合亚马逊业务逻辑的测试数据",
            "product_count": len(self._products),
            "competitor_count": len(self._competitors),
            "campaign_count": len(self._campaigns),
        }

    def health_check(self) -> dict:
        return {"status": "ok", "message": "Mock data source always healthy", "latency_ms": 1}

    def fetch_credentials(self, store_id: int) -> list[dict]:
        """返回一条模拟的 OAuth 凭证"""
        now = datetime.now()
        return [{
            "store_id": store_id,
            "seller_id": self._config["seller_id"],
            "region": self._config["region"],
            "marketplace_id": self._config["marketplace_id"],
            "access_token": "Atza|mock-access-token-" + "".join(
                self._rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=256)),
            "refresh_token": "Aztr|mock-refresh-token-" + "".join(
                self._rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=320)),
            "token_expires_at": now + timedelta(hours=0, minutes=55),
            "credential_status": "ACTIVE",
            "last_refreshed_at": now - timedelta(minutes=5),
            "auth_scopes": ["sellingpartnerapi::migration", "sellingpartnerapi::notifications"],
            "created_at": now - timedelta(days=30),
            "updated_at": now - timedelta(minutes=5),
        }]

    def fetch_daily_sales(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """生成每日销售数据"""
        records = []
        dates = self._date_range(date_from, date_to)
        products = [p for p in self._products if not asins or p["asin"] in asins]

        for product in products:
            lo, hi = product["daily_units_range"]
            price = product["standard_price"]

            for d in dates:
                sf = self._seasonal_factor(d)
                wf = self._weekend_boost(d)
                units = int(self._rng.randint(lo, hi) * sf * wf)
                if units == 0:
                    continue

                refund_rate = self._rng.uniform(0.05, 0.12)
                units_refunded = max(0, int(units * refund_rate * self._rng.uniform(0.3, 1.0)))
                price_float = float(price) * self._rng.uniform(0.95, 1.05)
                ordered_revenue = round(units * price_float, 2)
                refund_amount = round(units_refunded * price_float * self._rng.uniform(0.8, 1.0), 2)

                commission_rate = self._rng.uniform(0.14, 0.16)
                fba_fee = Decimal(str(self._rng.uniform(3.0, 7.0))) if product["fulfillment_channel"] == "FBA" else Decimal("0")
                net_revenue = round(ordered_revenue - refund_amount - (ordered_revenue * commission_rate) - float(fba_fee) * units, 2)

                cost_rate = self._rng.uniform(0.35, 0.55)
                estimated_profit = round(net_revenue * (1 - cost_rate), 2)

                records.append({
                    "store_id": store_id, "date": d.isoformat(),
                    "asin": product["asin"], "sku": product["sku"],
                    "units_ordered": units, "ordered_revenue": ordered_revenue,
                    "units_refunded": units_refunded, "refund_amount": refund_amount,
                    "net_revenue": net_revenue, "estimated_profit": estimated_profit,
                    "currency": self._config["currency"], "created_at": datetime.now(),
                })

        return records

    def fetch_ad_metrics(
        self, store_id: int, date_from: date, date_to: date,
        report_types: Optional[list[str]] = None,
        campaign_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """生成广告指标数据"""
        records = []
        dates = self._date_range(date_from, date_to)
        rt_map = {"sponsoredProducts": "sp", "sponsoredBrands": "sb", "sponsoredDisplay": "sd"}

        campaigns = self._campaigns
        if campaign_names:
            campaigns = [c for c in campaigns if c["name"] in campaign_names]

        for camp in campaigns:
            camp_type = camp["type"]
            report_type = rt_map.get(camp_type, "sp")
            if report_types and report_type not in report_types:
                continue

            kw_list = KEYWORDS.get(camp["name"], [])
            target_asins = camp["asins"]

            for d in dates:
                sf = self._seasonal_factor(d)

                if camp_type == "sponsoredProducts" and kw_list:
                    for kw, sv, cpc, competition in kw_list:
                        impressions = int(sv * self._rng.uniform(0.03, 0.15) * sf)
                        if impressions < 5:
                            continue
                        ctr = self._rng.uniform(0.003, 0.012)
                        clicks = max(1, int(impressions * ctr))
                        spend = round(clicks * float(cpc) * self._rng.uniform(0.8, 1.3), 2)
                        cvr = self._rng.uniform(0.08, 0.22)
                        orders = max(0, int(clicks * cvr))
                        aov = self._rng.uniform(12.0, 32.0)
                        sales = round(orders * aov, 2)

                        records.append(self._make_ad_row(
                            store_id, d, report_type, camp, kw,
                            impressions, clicks, spend, orders, sales,
                            target_type="MANUAL", target_id=f"KW-{hash(kw) % 100000:05d}",
                            keyword_id=f"KW-{hash(kw) % 100000:05d}",
                            asin=self._rng.choice(target_asins),
                        ))
                else:
                    impressions = int(self._rng.randint(500, 5000) * sf)
                    if impressions < 10:
                        continue
                    ctr = self._rng.uniform(0.002, 0.007)
                    clicks = max(1, int(impressions * ctr))
                    cpc = self._rng.uniform(0.4, 1.2)
                    spend = round(min(clicks * cpc, float(camp["budget"])), 2)
                    cvr = self._rng.uniform(0.06, 0.16)
                    orders = max(0, int(clicks * cvr))
                    aov = self._rng.uniform(14.0, 28.0)
                    sales = round(orders * aov, 2)

                    target_type = "AUTO" if camp_type == "sponsoredProducts" else (
                        "AUDIENCE" if camp_type == "sponsoredDisplay" else "CATEGORY")

                    records.append(self._make_ad_row(
                        store_id, d, report_type, camp, "",
                        impressions, clicks, spend, orders, sales,
                        target_type=target_type,
                        target_id=f"TGT-{hash(camp['name']) % 100000:05d}",
                        keyword_id="", asin=self._rng.choice(target_asins),
                    ))

        return records

    def fetch_listings(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """生成 Listing 快照（每 3 天一个点）"""
        records = []
        dates = self._date_range(date_from, date_to)
        snapshot_dates = [d for i, d in enumerate(dates) if i % 3 == 0]
        products = [p for p in self._products if not asins or p["asin"] in asins]

        bsr_ranges = {
            "B0CF9X1K2M4": (500, 3000), "B0DL7N3P5Q8": (800, 5000),
            "B0EM8R4T6U2": (1200, 8000), "B0FN9S2V5W7": (600, 4000),
            "B0GH3T6Y8I1": (2000, 15000),
        }

        for product in products:
            bsr_lo, bsr_hi = bsr_ranges.get(product["asin"], (1000, 10000))
            for d in snapshot_dates:
                sf = self._seasonal_factor(d)
                base_bsr = self._rng.randint(bsr_lo, bsr_hi)
                bsr_rank = max(int(base_bsr / sf), 100)
                price = float(product["standard_price"]) * self._rng.uniform(0.92, 1.08)
                has_buybox = self._rng.random() > 0.05

                records.append({
                    "store_id": store_id, "snapshot_date": d.isoformat(),
                    "asin": product["asin"], "title": product["title"],
                    "brand": product["brand"], "category": product["category"],
                    "standard_price": round(price, 2),
                    "buybox_price": round(price * self._rng.uniform(0.98, 1.02), 2) if has_buybox else None,
                    "bsr_rank": bsr_rank,
                    "fulfillment_channel": product["fulfillment_channel"],
                    "review_count": self._rng.randint(120, 3500),
                    "rating": round(self._rng.uniform(4.0, 4.8), 1),
                    "created_at": datetime.now(),
                })

        return records

    def fetch_inventory(
        self, store_id: int, snapshot_date: Optional[date] = None,
    ) -> list[dict]:
        """生成库存健康数据"""
        d = snapshot_date or date.today()
        inv_configs = [
            {"asin": "B0CF9X1K2M4", "sku": "THP-SMARTPLUG-10A", "fulfillable": (500, 2000), "inbound": (0, 300), "daily_avg": (15, 40)},
            {"asin": "B0DL7N3P5Q8", "sku": "THP-USBC-HUB-7IN1", "fulfillable": (200, 600), "inbound": (0, 200), "daily_avg": (5, 20)},
            {"asin": "B0EM8R4T6U2", "sku": "THP-LED-DESKLAMP", "fulfillable": (150, 400), "inbound": (0, 150), "daily_avg": (3, 12)},
            {"asin": "B0FN9S2V5W7", "sku": "THP-BT-SPEAKER-WTR", "fulfillable": (300, 800), "inbound": (50, 250), "daily_avg": (8, 30)},
            {"asin": "B0GH3T6Y8I1", "sku": "THP-KITCHEN-SCALE", "fulfillable": (80, 300), "inbound": (0, 100), "daily_avg": (2, 8)},
        ]

        records = []
        for cfg in inv_configs:
            fulfillable = self._rng.randint(*cfg["fulfillable"])
            inbound = self._rng.randint(*cfg["inbound"])
            total = fulfillable + inbound
            daily_avg = self._rng.uniform(*cfg["daily_avg"])
            days_supply = round(fulfillable / daily_avg, 1) if daily_avg > 0 else 999

            aged_0_90 = int(fulfillable * self._rng.uniform(0.70, 0.90))
            aged_91_180 = int(fulfillable * self._rng.uniform(0.08, 0.18))
            aged_181_270 = int(fulfillable * self._rng.uniform(0.02, 0.08))
            aged_271_365 = int(fulfillable * self._rng.uniform(0.01, 0.04))
            aged_365_plus = max(0, fulfillable - aged_0_90 - aged_91_180 - aged_181_270 - aged_271_365)

            if days_supply < 14:
                health_status = "CRITICAL"
            elif days_supply < 30:
                health_status = "WARNING"
            elif days_supply > 180:
                health_status = "STAGNANT"
            else:
                health_status = "HEALTHY"

            records.append({
                "store_id": store_id, "snapshot_date": d.isoformat(),
                "asin": cfg["asin"], "sku": cfg["sku"],
                "fulfillable_quantity": fulfillable, "inbound_quantity": inbound,
                "total_quantity": total, "days_supply": days_supply,
                "aged_0_90_days": aged_0_90, "aged_91_180_days": aged_91_180,
                "aged_181_270_days": aged_181_270, "aged_271_365_days": aged_271_365,
                "aged_365_plus_days": aged_365_plus,
                "is_stagnant": health_status == "STAGNANT",
                "health_status": health_status, "created_at": datetime.now(),
            })
        return records

    def fetch_competitors(
        self, store_id: int, date_from: date, date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        生成竞品快照数据 [新增]

        每个竞品 ASIN 的快照包含：
        - 价格（与自研产品对比，体现价格优势/劣势）
        - BSR 排名（对比市场份额变化趋势）
        - Review 数量和评分（对比产品口碑）
        - BuyBox 状态
        - 价格变动记录（追踪竞品是否在打价格战）
        """
        records = []
        dates = self._date_range(date_from, date_to)
        # 竞品快照频率：每 2 天一个点（比自研产品更频繁——需要盯紧竞品）
        snapshot_dates = [d for i, d in enumerate(dates) if i % 2 == 0]

        competitors = self._competitors
        if asins:
            # 按「竞品对应的自研 ASIN」或「竞品自身 ASIN」过滤
            competitors = [c for c in competitors
                          if c["asin"] in asins or (c.get("competes_with") and c["competes_with"] in asins)]

        for comp in competitors:
            own_product = self._product_by_asin(comp["competes_with"])
            own_price = float(own_product["standard_price"]) if own_product else 20.0
            price_adv = comp.get("price_advantage", 0)

            bsr_base_lo, bsr_base_hi = {
                "TP-Link": (300, 2000), "Amazon Basics": (100, 800),
                "Anker": (400, 3000), "Satechi": (2000, 10000),
                "TaoTronics": (800, 5000), "JBL": (200, 1500),
            }.get(comp["brand"], (500, 5000))

            prev_price = None
            for d in snapshot_dates:
                sf = self._seasonal_factor(d)

                # 竞品价格 = 自研价格 + 优势偏移 + 随机波动
                comp_price = round(own_price + price_adv + self._rng.uniform(-1.5, 1.5), 2)

                # 价格变动标记
                price_change = None
                if prev_price is not None:
                    diff = comp_price - prev_price
                    if diff < -1.0:
                        price_change = "PRICE_DROP"       # 降价（可能发起价格战）
                    elif diff > 1.0:
                        price_change = "PRICE_HIKE"       # 涨价
                    elif abs(diff) < 0.01:
                        price_change = "STABLE"           # 价格稳定
                    else:
                        price_change = "NORMAL_FLUCT"     # 正常浮动

                prev_price = comp_price

                # BSR：竞品品牌影响力不同，BSR 范围也不同
                bsr = max(int(self._rng.randint(bsr_base_lo, bsr_base_hi) / sf), 50)

                # Review 数据：大品牌 review 更多
                if comp["brand"] in ("Amazon Basics", "Anker", "TP-Link", "JBL"):
                    rev_range = (2000, 50000)
                    rating_range = (4.2, 4.7)
                else:
                    rev_range = (200, 5000)
                    rating_range = (3.8, 4.6)

                records.append({
                    "store_id": store_id,
                    "snapshot_date": d.isoformat(),
                    "competitor_asin": comp["asin"],
                    "competes_with_asin": comp["competes_with"],  # 关联的自研 ASIN
                    "brand": comp["brand"],
                    "title": comp["title"],
                    "price": comp_price,
                    "price_vs_own": round(comp_price - own_price, 2),  # 与自研产品的价差（正=竞品更贵）
                    "bsr_rank": bsr,
                    "review_count": self._rng.randint(*rev_range),
                    "rating": round(self._rng.uniform(*rating_range), 1),
                    "has_buybox": self._rng.random() > 0.1,  # 大品牌 90% 有 BuyBox
                    "buybox_price": round(comp_price * self._rng.uniform(0.98, 1.02), 2),
                    "price_change": price_change,
                    "fulfillment": "FBA" if comp["brand"] != "Satechi" else "FBM",
                    "created_at": datetime.now(),
                })

        return records

    def fetch_report_tasks(
        self, store_id: int, date_from: date, date_to: date,
    ) -> list[dict]:
        """生成报表任务历史"""
        records = []
        dates = self._date_range(date_from, date_to)
        recent_dates = dates[-7:] if len(dates) > 7 else dates

        report_types = [
            ("GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL", "daily_sales"),
            ("SP_CAMPAIGN_PERFORMANCE_REPORT", "ad_metrics_sp"),
            ("SB_CAMPAIGN_PERFORMANCE_REPORT", "ad_metrics_sb"),
            ("SD_CAMPAIGN_PERFORMANCE_REPORT", "ad_metrics_sd"),
            ("GET_LISTINGS_ALL_ITEM_DATA", "listing_snapshot"),
            ("GET_FBA_INVENTORY_AGED_DATA", "inventory_health"),
        ]

        for d in recent_dates:
            for rpt_type, data_type in report_types:
                status = self._rng.choices(
                    ["COMPLETED", "COMPLETED", "COMPLETED", "FAILED", "CANCELLED"],
                    weights=[70, 5, 5, 10, 10],
                )[0]
                processing = "DONE" if status == "COMPLETED" else (
                    "FATAL" if status == "FAILED" else "CANCELLED")

                started_at = datetime.combine(d, datetime.min.time()) + timedelta(
                    hours=self._rng.randint(2, 6))
                completed_at = started_at + timedelta(
                    minutes=self._rng.randint(5, 45)) if status == "COMPLETED" else None

                records.append({
                    "store_id": store_id, "report_type": rpt_type,
                    "data_type": data_type, "date_start": d.isoformat(),
                    "date_end": d.isoformat(), "status": status,
                    "processing_status": processing,
                    "report_id": f"RPT-{self._rng.randint(10000000, 99999999)}" if status != "CANCELLED" else None,
                    "document_id": f"DOC-{self._rng.randint(10000000, 99999999)}" if status == "COMPLETED" else None,
                    "retry_count": 0 if status == "COMPLETED" else self._rng.randint(1, 3),
                    "error_message": None if status != "FAILED" else "Rate exceeded. Please retry later.",
                    "started_at": started_at, "completed_at": completed_at,
                    "created_at": datetime.now(),
                })
        return records

    # ---- 内部工具方法 ----

    @staticmethod
    def _date_range(date_from: date, date_to: date) -> list[date]:
        """生成日期列表"""
        delta = (date_to - date_from).days
        return [date_from + timedelta(days=i) for i in range(max(delta, 0) + 1)]

    @staticmethod
    def _make_ad_row(
        store_id, d, report_type, camp, keyword_text,
        impressions, clicks, spend, orders, sales,
        **kwargs,
    ) -> dict:
        """构造一条广告指标记录"""
        actual_ctr = round((clicks / impressions * 100), 2) if impressions > 0 else 0
        actual_cpc = round((spend / clicks), 2) if clicks > 0 else 0
        acos = round((spend / sales * 100), 2) if sales > 0 else 100.0
        roas = round((sales / spend), 2) if spend > 0 else 0

        return {
            "store_id": store_id, "date": d.isoformat(),
            "report_type": report_type,
            "campaign_name": camp["name"],
            "campaign_id": f"CAMP-{hash(camp['name']) % 100000:05d}",
            "ad_group_name": kwargs.get("ad_group_name", f"AG-{camp['name'][:10]}"),
            "ad_group_id": kwargs.get("ad_group_id", f"AG-{hash(camp['name']) % 100000:05d}"),
            "keyword_text": keyword_text,
            "keyword_id": kwargs.get("keyword_id", ""),
            "target_id": kwargs.get("target_id", ""),
            "target_type": kwargs.get("target_type", ""),
            "asin": kwargs.get("asin", ""),
            "impressions": impressions, "clicks": clicks,
            "ctr": actual_ctr, "cpc": actual_cpc,
            "spend": spend, "orders": orders, "sales": sales,
            "acos": acos, "roas": roas,
            "currency": "USD", "created_at": datetime.now(),
        }

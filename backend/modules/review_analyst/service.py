"""运营复盘师 - 业务逻辑层

数据源**一律经工厂** `amazon_sp.data_sources.get_data_source()` 获取：
  - 已配置 SP-API 凭据 → SpApiDataSource（真实数据）
  - 未配置           → MockAmazonDataSource（演示数据，工厂会打 warning）

★ 禁止在本模块 import 具体数据源实现（`mock_source` / `sp_api_source`）。
  曾经这里是 `_source = MockAmazonDataSource(seed=42)` 的**模块级单例** ——
  后果是「配好真实凭据」对复盘功能完全无效，永远跑假数据，且没有任何报错。
  该形态由 `tests/test_import_boundaries.py` 钉住（反向注入验证过）。

聚合 8 张表数据产出六大复盘能力。

设计原则：
- service 只做「取数 + 聚合计算」，不引入 LLM（复盘是确定性数据汇总）。
- 返回结构统一为 dict，供 tools.py 序列化 / router 包装。
"""

import logging
from datetime import date, timedelta
from typing import Optional

from modules.amazon_sp.data_sources import get_data_source

from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest, AdReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
)

logger = logging.getLogger(__name__)

# ★ 数据源**按请求**经工厂获取（不是模块级单例）。
#
#   seed=42 只在「工厂回退到 Mock」时生效，作用是让 Mock 数据可复现。
#   旧形态（模块级单例）其实**做不到可复现**：`MockAmazonDataSource.__init__`
#   里是 `self._rng = random.Random(seed)`，单例会让 RNG 状态跨请求累积 ——
#   同一个请求第 N 次调用拿到的数据与第 1 次不同。
#
#   改为一请求一实例后：Mock 档每次都从同一起点生成（真的可复现），
#   真实档则按当前配置走 SpApiDataSource。两种档的判定都在工厂里。
def _source():
    return get_data_source(prefer="auto", seed=42)


def _date_range(days: int):
    """返回 (date_from, date_to)，复盘最近 days 天（含今天）。"""
    today = date.today()
    return today - timedelta(days=days - 1), today


def _sum_sales(sales: list[dict]) -> dict:
    """汇总销售记录：订单数 / 销售额 / 退款 / 净收入 / 预估利润。"""
    units = sum(r.get("units_ordered", 0) for r in sales)
    revenue = sum(r.get("ordered_revenue", 0) for r in sales)
    refunds = sum(r.get("refund_amount", 0) for r in sales)
    net = sum(r.get("net_revenue", 0) for r in sales)
    profit = sum(r.get("estimated_profit", 0) for r in sales)
    return {
        "units": units, "revenue": round(revenue, 2),
        "refunds": round(refunds, 2), "net_revenue": round(net, 2),
        "estimated_profit": round(profit, 2),
    }


def _sum_ad(ads: list[dict]) -> dict:
    """汇总广告记录：曝光 / 点击 / 花费 / 订单 / 销售额 / ACoS / ROAS。"""
    imp = sum(r.get("impressions", 0) for r in ads)
    clicks = sum(r.get("clicks", 0) for r in ads)
    spend = sum(r.get("spend", 0) for r in ads)
    orders = sum(r.get("orders", 0) for r in ads)
    sales = sum(r.get("sales", 0) for r in ads)
    acos = round(spend / sales * 100, 2) if sales else 100.0
    roas = round(sales / spend, 2) if spend else 0.0
    return {
        "impressions": imp, "clicks": clicks, "spend": round(spend, 2),
        "orders": orders, "sales": round(sales, 2),
        "acos": acos, "roas": roas,
        "ctr": round(clicks / imp * 100, 2) if imp else 0,
    }


# ==================== 六大复盘能力 ====================

async def weekly_report(request: WeeklyReportRequest) -> dict:
    """经营概览（周报）：销售 + 广告 + 库存 + 客诉汇总。"""
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(request.store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(request.store_id, d_from, d_to)
    inventory = source.fetch_inventory(request.store_id)

    s = _sum_sales(sales)
    a = _sum_ad(ads)
    stock_risk = [i for i in inventory if i["health_status"] in ("CRITICAL", "STAGNANT")]

    data = {
        "report_type": "weekly_report",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"近 {request.days} 天 GMV ${s['revenue']:,.0f}、订单 {s['units']}、ACoS {a['acos']}%、净利约 ${s['estimated_profit']:,.0f}",
        "metrics": [
            {"label": "GMV", "value": s["revenue"], "unit": "USD", "status": "normal"},
            {"label": "订单数", "value": s["units"], "unit": "单"},
            {"label": "净收入", "value": s["net_revenue"], "unit": "USD"},
            {"label": "预估利润", "value": s["estimated_profit"], "unit": "USD", "status": "good"},
            {"label": "ACoS", "value": a["acos"], "unit": "%", "status": "warning" if a["acos"] > 30 else "normal"},
            {"label": "ROAS", "value": a["roas"], "unit": "", "status": "good" if a["roas"] > 3 else "normal"},
        ],
        "details": {
            "sales": s, "ad": a,
            "refund_rate": round(s["refunds"] / s["revenue"] * 100, 2) if s["revenue"] else 0,
            "stock_risk_count": len(stock_risk),
        },
        "insights": [],
        "actions": [],
    }
    return data


async def monthly_review(request: MonthlyReviewRequest) -> dict:
    """月度复盘：GMV/ACoS/转化/退货趋势对比。"""
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(request.store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(request.store_id, d_from, d_to)

    s = _sum_sales(sales)
    a = _sum_ad(ads)

    # 按 ASIN 拆 SKU 贡献
    by_asin: dict[str, dict] = {}
    for r in sales:
        asin = r["asin"]
        b = by_asin.setdefault(asin, {"asin": asin, "units": 0, "revenue": 0.0, "profit": 0.0})
        b["units"] += r.get("units_ordered", 0)
        b["revenue"] += r.get("ordered_revenue", 0)
        b["profit"] += r.get("estimated_profit", 0)
    sku_rank = sorted(by_asin.values(), key=lambda x: x["revenue"], reverse=True)
    for b in sku_rank:
        b["revenue"] = round(b["revenue"], 2)
        b["profit"] = round(b["profit"], 2)

    data = {
        "report_type": "monthly_review",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"近 {request.days} 天月 GMV ${s['revenue']:,.0f}、净利 ${s['estimated_profit']:,.0f}（净利率 {s['estimated_profit']/s['revenue']*100:.1f}%）",
        "metrics": [
            {"label": "月 GMV", "value": s["revenue"], "unit": "USD"},
            {"label": "净利润", "value": s["estimated_profit"], "unit": "USD", "status": "good"},
            {"label": "净利率", "value": round(s["estimated_profit"] / s["revenue"] * 100, 2) if s["revenue"] else 0, "unit": "%"},
            {"label": "退货率", "value": round(s["refunds"] / s["revenue"] * 100, 2) if s["revenue"] else 0, "unit": "%"},
            {"label": "广告占比", "value": round(a["spend"] / s["revenue"] * 100, 2) if s["revenue"] else 0, "unit": "%"},
        ],
        "details": {"sales": s, "ad": a, "sku_rank": sku_rank},
        "insights": [],
        "actions": [],
    }
    return data


async def ad_review(request: AdReviewRequest) -> dict:
    """广告归因：ROAS/ACoS/CPC/CTR 多维分析，campaign 评级。"""
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    ads = source.fetch_ad_metrics(request.store_id, d_from, d_to)

    a = _sum_ad(ads)

    # 按 campaign 聚合评级
    by_campaign: dict[str, dict] = {}
    for r in ads:
        name = r["campaign_name"]
        b = by_campaign.setdefault(name, {"campaign": name, "spend": 0.0, "sales": 0.0, "orders": 0, "clicks": 0, "impressions": 0})
        b["spend"] += r.get("spend", 0)
        b["sales"] += r.get("sales", 0)
        b["orders"] += r.get("orders", 0)
        b["clicks"] += r.get("clicks", 0)
        b["impressions"] += r.get("impressions", 0)

    campaigns = []
    for b in by_campaign.values():
        acos = round(b["spend"] / b["sales"] * 100, 2) if b["sales"] else 100.0
        roas = round(b["sales"] / b["spend"], 2) if b["spend"] else 0.0
        cpc = round(b["spend"] / b["clicks"], 2) if b["clicks"] else 0.0
        ctr = round(b["clicks"] / b["impressions"] * 100, 2) if b["impressions"] else 0.0
        if acos <= 25:
            grade = "S"
        elif acos <= 32:
            grade = "B"
        else:
            grade = "C"
        campaigns.append({
            "campaign": b["campaign"], "spend": round(b["spend"], 2),
            "sales": round(b["sales"], 2), "acos": acos, "roas": roas,
            "cpc": cpc, "ctr": ctr, "grade": grade,
        })
    campaigns.sort(key=lambda x: x["spend"], reverse=True)

    data = {
        "report_type": "ad_review",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"广告花费 ${a['spend']:,.0f}、ACoS {a['acos']}%、ROAS {a['roas']}，{sum(1 for c in campaigns if c['grade']=='C')} 个 campaign 待优化",
        "metrics": [
            {"label": "广告花费", "value": a["spend"], "unit": "USD"},
            {"label": "广告销售额", "value": a["sales"], "unit": "USD"},
            {"label": "ACoS", "value": a["acos"], "unit": "%", "status": "warning" if a["acos"] > 30 else "normal"},
            {"label": "ROAS", "value": a["roas"], "unit": ""},
            {"label": "CPC", "value": round(a["spend"] / a["clicks"], 2) if a["clicks"] else 0, "unit": "USD"},
            {"label": "CTR", "value": a["ctr"], "unit": "%"},
        ],
        "details": {"ad": a, "campaigns": campaigns},
        "insights": [],
        "actions": [],
    }
    return data


async def product_performance(request: ProductPerformanceRequest) -> dict:
    """商品表现：SKU 级销量/利润/周转排名，识别爆款与滞销。"""
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(request.store_id, d_from, d_to, asins=request.asins)
    listings = source.fetch_listings(request.store_id, d_from, d_to, asins=request.asins)
    inventory = source.fetch_inventory(request.store_id)

    # 最新 listing 快照（评分/BSR）
    latest_listing: dict[str, dict] = {}
    for r in listings:
        asin = r["asin"]
        cur = latest_listing.get(asin)
        if cur is None or r["snapshot_date"] > cur["snapshot_date"]:
            latest_listing[asin] = r
    inv_map = {i["asin"]: i for i in inventory}

    by_asin: dict[str, dict] = {}
    for r in sales:
        asin = r["asin"]
        b = by_asin.setdefault(asin, {"asin": asin, "units": 0, "revenue": 0.0, "profit": 0.0})
        b["units"] += r.get("units_ordered", 0)
        b["revenue"] += r.get("ordered_revenue", 0)
        b["profit"] += r.get("estimated_profit", 0)

    products = []
    for asin, b in by_asin.items():
        lst = latest_listing.get(asin, {})
        inv = inv_map.get(asin, {})
        products.append({
            "asin": asin,
            "units": b["units"],
            "revenue": round(b["revenue"], 2),
            "profit": round(b["profit"], 2),
            "rating": lst.get("rating"),
            "bsr_rank": lst.get("bsr_rank"),
            "days_supply": inv.get("days_supply"),
            "health_status": inv.get("health_status", "UNKNOWN"),
        })
    products.sort(key=lambda x: x["revenue"], reverse=True)

    data = {
        "report_type": "product_performance",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"共 {len(products)} 个 SKU，爆款 {products[0]['asin'] if products else '无'} 贡献最高",
        "metrics": [
            {"label": "SKU 数", "value": len(products), "unit": "个"},
            {"label": "总销量", "value": sum(p["units"] for p in products), "unit": "件"},
        ],
        "details": {"products": products},
        "insights": [],
        "actions": [],
    }
    return data


async def inventory_health(request: InventoryHealthRequest) -> dict:
    """库存健康：滞销预警 / 断货风险 / 补货建议。"""
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    inventory = source.fetch_inventory(request.store_id)

    status_map = {"HEALTHY": 0, "WARNING": 0, "CRITICAL": 0, "STAGNANT": 0}
    items = []
    for i in inventory:
        status_map[i["health_status"]] = status_map.get(i["health_status"], 0) + 1
        items.append({
            "asin": i["asin"], "sku": i["sku"],
            "fulfillable": i["fulfillable_quantity"],
            "inbound": i["inbound_quantity"],
            "days_supply": i["days_supply"],
            "health_status": i["health_status"],
        })
    items.sort(key=lambda x: x["days_supply"])

    data = {
        "report_type": "inventory_health",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"健康 {status_map['HEALTHY']} / 预警 {status_map['WARNING']} / 断货 {status_map['CRITICAL']} / 滞销 {status_map['STAGNANT']}",
        "metrics": [
            {"label": "健康", "value": status_map["HEALTHY"], "unit": "个", "status": "good"},
            {"label": "预警", "value": status_map["WARNING"], "unit": "个", "status": "warning"},
            {"label": "断货", "value": status_map["CRITICAL"], "unit": "个", "status": "critical"},
            {"label": "滞销", "value": status_map["STAGNANT"], "unit": "个", "status": "critical"},
        ],
        "details": {"items": items},
        "insights": [],
        "actions": [],
    }
    return data


async def profit_audit(request: ProfitAuditRequest) -> dict:
    """利润审计：销售额 - 佣金 - FBA - 广告 - 退货 - 仓储 = 净利润。"""
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(request.store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(request.store_id, d_from, d_to)

    s = _sum_sales(sales)
    a = _sum_ad(ads)

    commission = round(s["revenue"] * 0.15, 2)  # 平台佣金约 15%
    # 成本结构（采购/广告/退货已含在 estimated_profit 的口径里，这里做结构拆解展示）
    data = {
        "report_type": "profit_audit",
        "period_days": request.days,
        "store_id": request.store_id,
        "summary": f"净利润 ${s['estimated_profit']:,.0f}，净利率 {s['estimated_profit']/s['revenue']*100:.1f}%（销售额 ${s['revenue']:,.0f}）",
        "metrics": [
            {"label": "销售额", "value": s["revenue"], "unit": "USD"},
            {"label": "平台佣金(估)", "value": commission, "unit": "USD"},
            {"label": "广告花费", "value": a["spend"], "unit": "USD"},
            {"label": "退款", "value": s["refunds"], "unit": "USD"},
            {"label": "净利润", "value": s["estimated_profit"], "unit": "USD", "status": "good"},
            {"label": "净利率", "value": round(s["estimated_profit"] / s["revenue"] * 100, 2) if s["revenue"] else 0, "unit": "%"},
        ],
        "details": {"sales": s, "ad": a, "commission": commission},
        "insights": [],
        "actions": [],
    }
    return data


# ==================== Service 类（统一入口）====================

class ReviewAnalystService:
    """运营复盘师服务（统一命名空间，与其他模块风格对齐）"""

    weekly_report = staticmethod(weekly_report)
    monthly_review = staticmethod(monthly_review)
    ad_review = staticmethod(ad_review)
    product_performance = staticmethod(product_performance)
    inventory_health = staticmethod(inventory_health)
    profit_audit = staticmethod(profit_audit)

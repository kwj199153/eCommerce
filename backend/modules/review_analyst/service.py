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
import time
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import select

from core.database import async_session_factory
from core.library_query import count_library, query_library
from core.tenant.middleware import MissingShopContext, require_shop_context
from core.tenant.scoping import scoped
from modules.amazon_sp import get_data_source

from .db_model import REVIEW_REPORT_TYPES, ReviewReportRecord
from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest, AdReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
)
from .spec import REVIEW_SPEC

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


# ★★★ 归属校验的唯一真源是 `core.tenant.middleware.require_shop_context`
#   （第 143 轮 A4 收拢）。为什么这里还留一个同名薄包装：
#     ① 调用点写成 `_require_store(store_id)` 更短，且 6 个能力里都要写一行；
#     ② 本模块的**拒绝文案**与写路径不同（这里是"复盘取数必须按店铺维度"，
#        写路径是"写操作必须携带 X-Shop-ID"）—— 文案按站点定制，判定逻辑共享。
#   ⚠️ 不要在这里重新实现 `if not store_id` —— 那就是第二份实现，必然漂移
#      （见 `require_shop_context` 的 docstring）。
def _require_store(store_id: "str | None") -> str:
    """校验并归一化店铺 ID；无效即抛 `MissingShopContext`。

    为什么 service 层还要再拦一道（router 的 strict 守卫已经会 400）：

      ① **直接调用方不只 router**：`tools.py` 的 6 个工具、以及任何测试/脚本都能
         直接调 service。少了这道，`store_id=""` 会一路传到数据源。
      ② 数据源**不会**因此返回空 —— 实测（探针 `r142_a4_source_probe.py`）：
         `MockAmazonDataSource` 对 `store_test` / 未知店铺 / 空串 / `None` /
         整数 1 **返回完全相同的 35 行销售数据**（它只把 store_id 打进行里做标签，
         不按它过滤）。也就是说缺店铺**不会**得到「空列表」，而会得到一份
         **看起来完全正常、却不知属于谁**的报告 —— 归因错误，比报错更糟。

    ⇒ 所以这里 fail-closed：拿不到有效店铺就**拒绝出报告**，绝不用
      「GMV $0」之类的全 0 兜底（那正是本仓「降级路径禁用全 0 兜底」那条铁律）。
    """
    return require_shop_context(
        store_id,
        detail="缺少店铺上下文：复盘取数必须按店铺维度。"
               "请先在界面左上角选择一个店铺再重试。",
    )


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

async def weekly_report(request: WeeklyReportRequest, store_id: str) -> dict:
    """经营概览（周报）：销售 + 广告 + 库存 + 客诉汇总。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(store_id, d_from, d_to)
    inventory = source.fetch_inventory(store_id)

    s = _sum_sales(sales)
    a = _sum_ad(ads)
    stock_risk = [i for i in inventory if i["health_status"] in ("CRITICAL", "STAGNANT")]

    data = {
        "report_type": "weekly_report",
        "period_days": request.days,
        "store_id": store_id,
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


async def monthly_review(request: MonthlyReviewRequest, store_id: str) -> dict:
    """月度复盘：GMV/ACoS/转化/退货趋势对比。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(store_id, d_from, d_to)

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
        "store_id": store_id,
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


async def ad_review(request: AdReviewRequest, store_id: str) -> dict:
    """广告归因：ROAS/ACoS/CPC/CTR 多维分析，campaign 评级。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    ads = source.fetch_ad_metrics(store_id, d_from, d_to)

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
        "store_id": store_id,
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


async def product_performance(request: ProductPerformanceRequest, store_id: str) -> dict:
    """商品表现：SKU 级销量/利润/周转排名，识别爆款与滞销。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(store_id, d_from, d_to, asins=request.asins)
    listings = source.fetch_listings(store_id, d_from, d_to, asins=request.asins)
    inventory = source.fetch_inventory(store_id)

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
        "store_id": store_id,
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


async def inventory_health(request: InventoryHealthRequest, store_id: str) -> dict:
    """库存健康：滞销预警 / 断货风险 / 补货建议。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    inventory = source.fetch_inventory(store_id)

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
        "store_id": store_id,
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


async def profit_audit(request: ProfitAuditRequest, store_id: str) -> dict:
    """利润审计：销售额 - 佣金 - FBA - 广告 - 退货 - 仓储 = 净利润。"""
    # ★ A4：归属只能服务端注入（router 的 strict 守卫）——
    #   本行是「拿不到有效店铺就不出报告」的第二道闸（见 _require_store）。
    store_id = _require_store(store_id)
    d_from, d_to = _date_range(request.days)
    source = _source()  # 本次请求的数据源（经工厂；见模块 docstring）
    sales = source.fetch_daily_sales(store_id, d_from, d_to)
    ads = source.fetch_ad_metrics(store_id, d_from, d_to)

    s = _sum_sales(sales)
    a = _sum_ad(ads)

    commission = round(s["revenue"] * 0.15, 2)  # 平台佣金约 15%
    # 成本结构（采购/广告/退货已含在 estimated_profit 的口径里，这里做结构拆解展示）
    data = {
        "report_type": "profit_audit",
        "period_days": request.days,
        "store_id": store_id,
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


# ==================== 复盘库（归档 / 列表 / 详情）====================
#
# ★ 与上面 6 项能力的区别：
#     那 6 项是**计算**（每次按数据源现算，不落库）；
#     本节是**存储**（存老板确认过的那一份 + 读历史）。
#   两者的归属口径完全一致（都走 `_require_store`）⇒ 共用同一个守卫，
#   不另写一份 —— 本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。
#
# ★ 为什么这一节住在 service 而不是 router：
#   读口有**两个**消费者 —— REST（前端复盘库页面）与 Agent 工具
#   （`tools.list_reviews`，让下一期复盘能读到上期做对比）。
#   查询/投影写在 router 里，工具那条路就得再实现一遍同样的查询。

#: 单份快照的序列化上限（字符）。请求体里的 `data` 由前端回传，属**外部输入**。
#: ★ 不设上限的后果不是安全问题而是可用性问题：一份几 MB 的 JSON 会被原样写进
#:   `review_reports.data`，之后每次列表查询都要把它读出来（列表虽然不回传 data，
#:   但 SQL 仍然要取列），把「复盘库」变成一个拖慢整页的东西。
#:   取 512KB —— 实测一份 35 行 SKU 明细的报告约 10~20KB，留了 25 倍余量。
MAX_SNAPSHOT_CHARS = 512 * 1024


class ReviewLibraryError(ValueError):
    """复盘库**写口**校验失败（请求形状/取值问题 ⇒ HTTP 422，不是 500）。

    ★ 为什么要专属异常：router 要把它映射成 422、service 的直接调用方
      （测试/脚本）要能区分「我传错了」与「服务端坏了」。用一句裸 `ValueError`
      会让两者混在同一个 except 里（本仓「失败必须能归因」）。
    """


def _new_id(prefix: str) -> str:
    """生成主键 `{prefix}-{毫秒时间戳}-{6位随机}`。

    ★ 带随机后缀是必要的：同一毫秒内连点两次归档会造出两条，"只靠时间戳"会主键冲突。
      同族实现见 `modules.platform_rules/service.py::_new_id`（本仓既有形态）。
    """
    return f"{prefix}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def _today_iso() -> str:
    """周期末日（`YYYY-MM-DD`，UTC）。

    ★ 由**服务端**取，不读请求体：它是幂等键的一部分（见 `db_model` 的说明），
      客户端可控就等于客户端能决定「覆盖哪一条」。
    """
    return datetime.utcnow().strftime("%Y-%m-%d")


def report_to_dict(r: ReviewReportRecord, include_data: bool = False) -> dict:
    """ORM → dict。

    ★ `include_data=False` 是**默认**：列表与工具出参都不回快照
      （一份报告的 `details` 可挂 35 行 SKU 明细；列表 20 条就是几百 KB）。
      只有「详情」这一个入口需要快照 —— 那时调用方显式传 True。
      这与 `platform_rules.doc_to_dict(include_content=False)` 同一取舍。
    """
    out = {
        "id": r.id,
        "report_type": r.report_type,
        "period_days": r.period_days,
        "period_end": r.period_end,
        "summary": r.summary or "",
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }
    if include_data:
        out["data"] = r.data or {}
    return out


def validate_save_payload(payload: dict) -> None:
    """写口校验（**唯一实现**）：不合规直接抛 `ReviewLibraryError`。

    校验三件事，都是"不接受就会静默存错"的：
      ① `report_type` 必须在 `REVIEW_REPORT_TYPES` 里 —— 否则库里会出现一个
         没有任何读口能筛到、也没人能翻译成中文的类型（前端 `ReviewReportCard`
         的 `TITLES` 查不到就退化成「运营复盘」，看起来像正常数据）；
      ② `period_days` 必须是 1~90 的整数 —— 与 `ReviewRequest.days`
         （`Field(7, ge=1, le=90)`）**同一值域**，否则会出现「算不出来但存得进去」；
      ③ 快照必须是 dict 且序列化后不超 `MAX_SNAPSHOT_CHARS`。
    """
    report_type = str(payload.get("report_type") or "").strip()
    if report_type not in REVIEW_REPORT_TYPES:
        raise ReviewLibraryError(
            "report_type 不合法："
            f"{report_type or '（空）'}；可选：{' / '.join(REVIEW_REPORT_TYPES)}"
        )

    try:
        period_days = int(payload.get("period_days"))
    except (TypeError, ValueError):
        raise ReviewLibraryError("period_days 必须是 1~90 的整数")
    if not (1 <= period_days <= 90):
        raise ReviewLibraryError(f"period_days 必须在 1~90 之间，收到 {period_days}")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReviewLibraryError("data 必须是复盘结果的对象（后端 ReviewReport 的结构）")

    import json  # 只在本函数用到；放模块顶层会与 `_dump` 系列混淆（tools 里另有一个）

    size = len(json.dumps(data, ensure_ascii=False, default=str))
    if size > MAX_SNAPSHOT_CHARS:
        raise ReviewLibraryError(
            f"复盘快照过大（{size} > {MAX_SNAPSHOT_CHARS} 字符），拒绝写入"
        )


async def save_report(payload: dict, shop_id: Optional[str] = None) -> dict:
    """把一份**老板确认过的**复盘结果归档进复盘库（幂等 upsert）。

    Returns:
        `{"created": bool, "item": {...}}` —— `created=False` 表示覆盖了
        同一 (类型, 周期长度, 周期末日) 的既有记录（当天重复归档）。
        ★ 把 created 显式回给前端：**「新增了一条」与「覆盖了今天那条」对老板是
          两件事**，用同一句「已归档」会让他以为库里堆了两份。

    Raises:
        MissingShopContext: 没有有效店铺归属 ⇒ 硬拒绝（不落 `shop_id=""` 的孤儿行）。
        ReviewLibraryError: 请求形状/取值不合法（router 映射成 422）。
    """
    shop = _require_store(shop_id)
    validate_save_payload(payload)

    report_type = str(payload["report_type"]).strip()
    period_days = int(payload["period_days"])
    period_end = _today_iso()
    now = datetime.utcnow().isoformat()

    # ★★ 服务端覆盖三处 —— 这是**唯一的写入点**（同族先例：`ReviewRequest`
    #   干脆没有 `store_id` 字段）。快照由前端回传 ⇒ 它里面的 `store_id`
    #   可以被改成别家；覆盖之后，请求体在结构上不可能影响归属。
    #   `report_type` / `period_days` 也一并覆盖成**服务端已校验**的值，
    #   保证「数据里的自述」与「列上的键」永远一致（否则筛出来的和看到的不符）。
    snapshot = {
        **(payload["data"]),
        "report_type": report_type,
        "period_days": period_days,
        "store_id": shop,
    }
    summary = str(snapshot.get("summary") or "")

    async with async_session_factory() as session:
        # ★ 幂等：同 (店铺, 类型, 周期长度, 周期末日) 只允许一行
        #   ⇒ 先按这四维找，找到就更新，找不到才插。
        #   （DB 上还有 `uq_review_reports_scope` 兜底：并发双写会被数据库拒。）
        q = scoped(select(ReviewReportRecord), ReviewReportRecord, shop).where(
            ReviewReportRecord.report_type == report_type,
            ReviewReportRecord.period_days == period_days,
            ReviewReportRecord.period_end == period_end,
        )
        existing = (await session.execute(q)).scalar_one_or_none()
        if existing is not None:
            existing.data = snapshot
            existing.summary = summary
            existing.updated_at = now
            await session.commit()
            await session.refresh(existing)
            return {"created": False, "item": report_to_dict(existing)}

        record = ReviewReportRecord(
            id=_new_id("rpt"),
            shop_id=shop,
            report_type=report_type,
            period_days=period_days,
            period_end=period_end,
            summary=summary,
            data=snapshot,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return {"created": True, "item": report_to_dict(record)}


async def list_saved_reports(
    shop_id: Optional[str],
    *,
    order_by: Optional[str] = None,
    report_type: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[dict]:
    """列出该店铺已归档的复盘（**不含** `data` 快照）。

    ★ 查询收口到 `core.library_query`（`REVIEW_SPEC`）—— 排序白名单 / 过滤值域 /
      limit 归一只有一份实现，REST 与 Agent 工具共用本函数。

    ★ 空 `shop_id` 一律返回空列表（内核对 `shop_id` 为空直接短路返回 `[]`）——
      与其余 6 个库一致：没有租户上下文时无法判断归属，返回全库就是跨租户串数据。

    ★ `order_by` / `report_type` 传了值域外的值 ⇒ 内核抛 `LibraryQueryError`。
      **故意不让它静默退化成默认排序**：那会让「按创建时间排」与「你参数写错了」
      在调用方看来长得一样（第 216 轮实测过的归因错方向）。
    """
    rows = await query_library(
        REVIEW_SPEC,
        shop_id,
        order_by=order_by,
        filters={"report_type": report_type},
        limit=limit,
    )
    # ★ 这里把 `data` 一并读了（内核不做投影，见其 docstring）但**不回传** ——
    #   复盘库是低频库（一个月几条），为省这点 IO 另写一套投影查询不值得；
    #   真正要防的是「把十几 KB 的 JSON 塞进模型上下文」，那由本函数的出参保证。
    return [report_to_dict(row[0]) for row in rows]


async def count_saved_reports(
    shop_id: Optional[str],
    *,
    report_type: Optional[str] = None,
) -> int:
    """复盘库**真实**条数（与 `list_saved_reports` 同口径，两者都走内核）。

    ★ 不能用 `len(items)` 代替：`items` 受 limit 截断 ⇒ 老板问「归档了几份」
      拿到的是被截断的数（第 216 轮 ① 的形态）。
    """
    return await count_library(REVIEW_SPEC, shop_id, filters={"report_type": report_type})


async def get_saved_report(
    report_id: str, shop_id: Optional[str] = None
) -> Optional[dict]:
    """按主键取一份已归档的复盘（**含** `data` 快照）。

    ★ 归属过滤与「记录不存在」必须压成同一个返回值 `None`：
      调用方（router）据此回**同一句 404 文案**。否则「这个 id 不属于你」
      与「这个 id 不存在」可区分 ⇒ 可以拿它逐位枚举别人的报告 id。
      （同族判据见 `modules/conversation` 的会话归属收口。）
    """
    async with async_session_factory() as session:
        q = scoped(select(ReviewReportRecord), ReviewReportRecord, shop_id).where(
            ReviewReportRecord.id == report_id
        )
        record = (await session.execute(q)).scalar_one_or_none()
        if record is None:
            return None
        return report_to_dict(record, include_data=True)


# ==================== Service 类（统一入口）====================

class ReviewAnalystService:
    """运营复盘师服务（统一命名空间，与其他模块风格对齐）"""

    weekly_report = staticmethod(weekly_report)
    monthly_review = staticmethod(monthly_review)
    ad_review = staticmethod(ad_review)
    product_performance = staticmethod(product_performance)
    inventory_health = staticmethod(inventory_health)
    profit_audit = staticmethod(profit_audit)
    # 复盘库（归档 / 列表 / 详情）—— 工具层 `tools.py` 走类调用，
    # 与上面 6 项保持同一入口形态（否则调用方要在「类」与「模块函数」之间切换）。
    save_report = staticmethod(save_report)
    list_saved_reports = staticmethod(list_saved_reports)
    count_saved_reports = staticmethod(count_saved_reports)
    get_saved_report = staticmethod(get_saved_report)

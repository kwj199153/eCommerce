"""
运营复盘师模块 → 主 Agent 工具注册表

把 ReviewAnalystService 的六大复盘能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 product_research/tools.py 一致）：
- 只包「语义明确」的 6 个复盘能力（周报 / 月报 / 广告归因 / 商品表现 / 库存健康 /
  利润审计），不包粗粒度 chat 入口。
- 参数扁平化，工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰数据源本体。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool

from .service import ReviewAnalystService
from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest, AdReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
)

_service = ReviewAnalystService()


def _dump(resp) -> str:
    """统一序列化。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


async def _weekly_report_tool(store_id: int = 1, days: int = 7) -> str:
    """经营概览（周报）：汇总销售、广告、库存、退款数据，生成结构化周报。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 7）。
    """
    req = WeeklyReportRequest(store_id=store_id, days=days)
    resp = await _service.weekly_report(req)
    return _dump(resp)


async def _monthly_review_tool(store_id: int = 1, days: int = 30) -> str:
    """月度复盘：GMV/ACoS/转化率/退货率趋势对比 + SKU 贡献排名。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 30）。
    """
    req = MonthlyReviewRequest(store_id=store_id, days=days)
    resp = await _service.monthly_review(req)
    return _dump(resp)


async def _ad_review_tool(store_id: int = 1, days: int = 7) -> str:
    """广告归因分析：ROAS/ACoS/CPC/CTR 多维度回顾 + campaign 评级。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 7）。
    """
    req = AdReviewRequest(store_id=store_id, days=days)
    resp = await _service.ad_review(req)
    return _dump(resp)


async def _product_performance_tool(
    store_id: int = 1,
    days: int = 7,
    asins: Optional[list[str]] = None,
) -> str:
    """商品表现分析：SKU 级销量/利润/评分/BSR/周转排名，识别爆款与滞销品。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 7）。
        asins: 指定 ASIN 列表（可选，为空分析全部）。
    """
    req = ProductPerformanceRequest(store_id=store_id, days=days, asins=asins)
    resp = await _service.product_performance(req)
    return _dump(resp)


async def _inventory_health_tool(store_id: int = 1, days: int = 7) -> str:
    """库存健康分析：滞销预警/断货风险/周转天数/补货建议。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 7，仅用于标注）。
    """
    req = InventoryHealthRequest(store_id=store_id, days=days)
    resp = await _service.inventory_health(req)
    return _dump(resp)


async def _profit_audit_tool(store_id: int = 1, days: int = 30) -> str:
    """利润审计：销售额 - 佣金 - 广告 - 退货等全链路核算净利润与净利率。

    Args:
        store_id: 店铺 ID（默认 1）。
        days: 复盘周期天数（默认 30）。
    """
    req = ProfitAuditRequest(store_id=store_id, days=days)
    resp = await _service.profit_audit(req)
    return _dump(resp)


# ====== 工具注册表 ======

review_analyst_tools = [
    StructuredTool.from_function(
        coroutine=_weekly_report_tool,
        name="weekly_report",
        description=(
            "经营概览周报：汇总销售、广告、库存、退款数据，生成结构化周报。"
            "当老板要看本周经营情况/周报/经营大盘/业绩概览时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_monthly_review_tool,
        name="monthly_review",
        description=(
            "月度复盘：GMV/ACoS/转化率/退货率趋势对比 + SKU 贡献排名。"
            "当老板要看月度数据/月报/月度总结/月度复盘时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_ad_review_tool,
        name="ad_review",
        description=(
            "广告归因分析：ROAS/ACoS/CPC/CTR 多维度回顾 + campaign 评级。"
            "当老板要看广告效果/广告复盘/广告数据/ACoS 归因时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_product_performance_tool,
        name="product_performance",
        description=(
            "商品表现分析：SKU 级销量/利润/评分/BSR/周转排名，识别爆款与滞销品。"
            "当老板要看商品表现/SKU 排名/哪个品卖得好/滞销时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_inventory_health_tool,
        name="inventory_health",
        description=(
            "库存健康分析：滞销预警/断货风险/周转天数/补货建议。"
            "当老板要看库存/断货风险/滞销/补货建议时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_profit_audit_tool,
        name="profit_audit",
        description=(
            "利润审计：销售额 - 佣金 - 广告 - 退货全链路核算净利润与净利率。"
            "当老板要看利润/净利润/赚了多少/成本结构时使用。"
        ),
    ),
]

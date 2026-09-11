"""
选品分析模块 → 主 Agent 工具注册表

把 ProductResearchService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 listing_tools.py 一致）：
- 只包「语义明确」的细粒度方法（蓝海挖掘 / 利润计算 / 痛点分析 / 竞品对比），
  **不包** `chat` / `stream_chat` 这类粗粒度入口（交给 agent 内部 _classify_intent
  关键词表再判断一次，会与主 Agent 的 LLM 判断冲突）。
- 参数用扁平字段（照 listing 范式），工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool

from .service import ProductResearchService
from .schemas import (
    BlueOceanRequest,
    ProfitAnalysisRequest,
    PainPointRequest,
    CompetitorCompareRequest,
)

# 单例 service（与 router 同源）
_service = ProductResearchService()


def _dump(resp) -> str:
    """统一序列化：dict 直接 dump，Pydantic 走 model_dump。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


async def _analyze_blue_ocean_tool(
    marketplace: str = "amazon_us",
    category: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    max_reviews: int = 100,
    min_monthly_sales: int = 100,
    min_roi: float = 20,
    exclude_seasonal: bool = False,
    exclude_brand_dominant: bool = False,
) -> str:
    """蓝海品类挖掘：按低竞争 + 有需求 + 有利润的标准筛选候选商品。

    Args:
        marketplace: 目标站点，如 amazon_us / shopee_my（默认 amazon_us）。
        category: 类目关键词，如 home_kitchen / sports_outdoors / beauty_personal_care。
        price_min: 最低售价（USD，可选）。
        price_max: 最高售价（USD，可选）。
        max_reviews: 评论数上限（控制低竞争，默认 100）。
        min_monthly_sales: 最小月销量（保证需求，默认 100）。
        min_roi: 最低目标 ROI（%，默认 20）。
        exclude_seasonal: 是否排除季节性商品（默认否）。
        exclude_brand_dominant: 是否排除品牌垄断商品（默认否）。
    """
    req = BlueOceanRequest(
        marketplace=marketplace,
        category=[category] if category else None,
        price_min=price_min,
        price_max=price_max,
        max_reviews=max_reviews,
        min_monthly_sales=min_monthly_sales,
        min_roi=min_roi,
        exclude_seasonal=exclude_seasonal,
        exclude_brand_dominant=exclude_brand_dominant,
    )
    resp = await _service.analyze_blue_ocean(req)
    return _dump(resp)


async def _analyze_profit_tool(
    selling_price: float,
    cost_price: float,
    product_name: str = "",
    asin: Optional[str] = None,
    weight_lbs: float = 1.5,
    dimensions: str = "10x7x5",
    category: str = "",
    ad_acos_pct: float = 15.0,
) -> str:
    """利润分析：按售价、成本、FBA 费用、广告费计算净利润 / ROI / 盈亏平衡点。

    Args:
        selling_price: 售价（USD，必填）。
        cost_price: 采购成本（USD，必填）。
        product_name: 产品名称（可选）。
        asin: 产品 ASIN（可选，有则查询真实数据）。
        weight_lbs: 重量（磅，默认 1.5）。
        dimensions: 尺寸（长x宽x高 英寸，默认 10x7x5）。
        category: 类目（影响佣金比例）。
        ad_acos_pct: 预期广告 ACOS（%，默认 15）。
    """
    req = ProfitAnalysisRequest(
        selling_price=selling_price,
        cost_price=cost_price,
        product_name=product_name,
        asin=asin,
        weight_lbs=weight_lbs,
        dimensions=dimensions,
        category=category,
        ad_acos_pct=ad_acos_pct,
    )
    resp = await _service.analyze_profit(req)
    return _dump(resp)


async def _analyze_pain_points_tool(
    asin: str,
    analyze_positive: bool = False,
) -> str:
    """痛点分析：分析某产品 ASIN 的用户评论，提炼痛点与改进方向。

    Args:
        asin: 产品 ASIN（必填）。
        analyze_positive: 是否同时分析好评（默认否，只分析差评痛点）。
    """
    req = PainPointRequest(asin=asin, analyze_positive=analyze_positive)
    resp = await _service.analyze_pain_points(req)
    return _dump(resp)


async def _compare_competitors_tool(
    asins: list[str],
    include_reviews: bool = True,
) -> str:
    """竞品对比：对比多个竞品 ASIN 的 Listing 质量、价格、优劣势。

    Args:
        asins: 竞品 ASIN 列表（2-5 个，必填）。
        include_reviews: 是否包含评论分析（默认 True）。
    """
    req = CompetitorCompareRequest(asins=asins, include_reviews=include_reviews)
    resp = await _service.compare_competitors(req)
    return _dump(resp)


# ====== 工具注册表 ======

product_research_tools = [
    StructuredTool.from_function(
        coroutine=_analyze_blue_ocean_tool,
        name="analyze_blue_ocean",
        description=(
            "蓝海品类挖掘：按低竞争 + 有需求 + 有利润的标准筛选候选商品，返回蓝海评分排序列表。"
            "当用户想找蓝海机会/选品/挖掘蓝海品类/看有没有竞争小又赚钱的品类时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_profit_tool,
        name="analyze_profit",
        description=(
            "利润分析：按售价、成本、FBA 费用、广告费计算净利润/ROI/盈亏平衡点。"
            "当用户想算利润/算 ROI/看这个产品赚不赚钱/算成本时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_pain_points_tool,
        name="analyze_pain_points",
        description=(
            "痛点分析：分析某产品 ASIN 的用户评论，提炼痛点与改进方向。"
            "当用户想分析用户痛点/看差评/找产品改进点时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_compare_competitors_tool,
        name="compare_competitors",
        description=(
            "竞品对比：对比多个竞品 ASIN 的 Listing 质量、价格、优劣势，给出参考建议。"
            "当用户想对比竞品/分析竞争对手/看竞品优劣势时使用。"
        ),
    ),
]

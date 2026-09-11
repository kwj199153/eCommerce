"""
竞品情报监控模块 → 主 Agent 工具注册表

把 CompetitorIntelService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 product_research/tools.py 一致）：
- 只包「语义明确」的 8 个细粒度能力（监控 / 批量追踪 / 市场份额 / 定价 / 评论 /
  入侵者检测 / Buy Box / 对比），**不包** `general_analysis` / `stream_chat` 这类
  粗粒度入口（交给 agent 内部 _classify_intent 关键词表再判断一次，会与主 Agent
  的 LLM 判断冲突）。
- 参数用扁平字段（照 listing 范式），工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool

from .service import CompetitorIntelService
from .schemas import (
    CompetitorMonitorRequest,
    BatchTrackRequest,
    MarketShareRequest,
    PricingAnalysisRequest,
    ReviewAnalysisRequest,
    IntruderDetectionRequest,
    BuyBoxAnalysisRequest,
    CompetitorCompareRequest,
)

# 单例 service（与 router 同源）
_service = CompetitorIntelService()


def _dump(resp) -> str:
    """统一序列化：dict 直接 dump，Pydantic 走 model_dump。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


async def _monitor_competitor_tool(
    asin: Optional[str] = None,
    days: int = 30,
) -> str:
    """竞品 Listing 监控：追踪竞品的价格、排名、评论数、库存状态变化。

    Args:
        asin: 竞品 ASIN（可选，为空返回所有竞品监控概览）。
        days: 分析时间范围（7-90 天，默认 30）。
    """
    req = CompetitorMonitorRequest(asin=asin, days=days)
    resp = await _service.monitor_competitor(req)
    return _dump(resp)


async def _track_batch_asins_tool(
    asins: list[str],
    include_history: bool = True,
) -> str:
    """ASIN 批量追踪：批量对比多个竞品的关键指标（价格/BSR/评论/评分/综合得分）。

    Args:
        asins: ASIN 列表（1-20 个，必填）。
        include_history: 是否包含历史趋势数据（默认 True）。
    """
    req = BatchTrackRequest(asins=asins, include_history=include_history)
    resp = await _service.track_batch_asins(req)
    return _dump(resp)


async def _analyze_market_share_tool(
    category: str,
    estimate_method: str = "bsr_based",
) -> str:
    """市场份额分析：基于 BSR 排名估算各品牌市场份额和竞争格局。

    Args:
        category: 产品类目（必填，如 Headphones / Home Kitchen）。
        estimate_method: 估算方法（bsr_based / revenue_based，默认 bsr_based）。
    """
    req = MarketShareRequest(category=category, estimate_method=estimate_method)
    resp = await _service.analyze_market_share(req)
    return _dump(resp)


async def _analyze_pricing_strategy_tool(
    asin: Optional[str] = None,
    compare_asins: Optional[list[str]] = None,
    analysis_depth: str = "standard",
) -> str:
    """定价策略分析：分析竞品的定价模式、促销节奏、价格弹性。

    Args:
        asin: 目标 ASIN（可选，为空分析所有竞品）。
        compare_asins: 对比 ASIN 列表（可选）。
        analysis_depth: 分析深度（basic / standard / deep，默认 standard）。
    """
    req = PricingAnalysisRequest(
        asin=asin,
        compare_asins=compare_asins,
        analysis_depth=analysis_depth,
    )
    resp = await _service.analyze_pricing_strategy(req)
    return _dump(resp)


async def _analyze_competitor_reviews_tool(
    asin: str,
    aspects: Optional[list[str]] = None,
    sample_size: int = 100,
) -> str:
    """竞品评论深度分析：挖掘竞品评论中的优劣势、用户痛点、差异化机会。

    Args:
        asin: 目标竞品 ASIN（必填）。
        aspects: 关注维度列表（可选，为空全维度分析）。
        sample_size: 评论采样数（10-1000，默认 100）。
    """
    req = ReviewAnalysisRequest(asin=asin, aspects=aspects, sample_size=sample_size)
    resp = await _service.analyze_competitor_reviews(req)
    return _dump(resp)


async def _detect_intruders_tool(
    category: str,
    lookback_days: int = 30,
    min_reviews_threshold: int = 50,
) -> str:
    """入侵者检测：发现近期进入市场的新卖家/新产品，评估威胁等级。

    Args:
        category: 监控类目（必填）。
        lookback_days: 回溯天数（7-90，默认 30）。
        min_reviews_threshold: 新卖家最低评论阈值（默认 50）。
    """
    req = IntruderDetectionRequest(
        category=category,
        lookback_days=lookback_days,
        min_reviews_threshold=min_reviews_threshold,
    )
    resp = await _service.detect_intruders(req)
    return _dump(resp)


async def _analyze_buy_box_tool(
    asin: Optional[str] = None,
    marketplace: str = "US",
) -> str:
    """Buy Box 竞争分析：分析 Buy Box 竞争格局、价格竞争力、赢取建议。

    Args:
        asin: 目标 ASIN（可选，为空分析所有竞品）。
        marketplace: 站点（US / UK / DE / JP，默认 US）。
    """
    req = BuyBoxAnalysisRequest(asin=asin, marketplace=marketplace)
    resp = await _service.analyze_buy_box(req)
    return _dump(resp)


async def _compare_competitors_tool(
    asins: list[str],
    dimensions: Optional[list[str]] = None,
) -> str:
    """多维度竞品对比：从价格、评分、评论、BSR、性价比等维度全面对比。

    Args:
        asins: 要对比的 ASIN 列表（2-10 个，必填）。
        dimensions: 对比维度（price/rating/reviews/bsr/value，默认全部）。
    """
    req = CompetitorCompareRequest(
        asins=asins,
        dimensions=dimensions or ["price", "rating", "reviews", "bsr", "value"],
    )
    resp = await _service.compare_competitors(req)
    return _dump(resp)


# ====== 工具注册表 ======

competitor_intel_tools = [
    StructuredTool.from_function(
        coroutine=_monitor_competitor_tool,
        name="monitor_competitor",
        description=(
            "竞品 Listing 监控：追踪竞品的价格、排名、评论数、库存状态变化。"
            "当用户想监控竞品/看竞品价格排名变化/跟踪某个 ASIN 时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_track_batch_asins_tool,
        name="track_batch_asins",
        description=(
            "ASIN 批量追踪：批量对比多个竞品的关键指标（价格/BSR/评论/评分/综合得分）。"
            "当用户想批量对比多个竞品/追踪一批 ASIN 时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_market_share_tool,
        name="analyze_market_share",
        description=(
            "市场份额分析：基于 BSR 排名估算各品牌市场份额和竞争格局（CR4/HHI）。"
            "当用户想看市场份额/市场格局/类目竞争集中度时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_pricing_strategy_tool,
        name="analyze_pricing_strategy",
        description=(
            "定价策略分析：分析竞品的定价模式、促销节奏、价格弹性，给出调价建议。"
            "当用户想分析竞品定价/看价格策略/促销节奏时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_competitor_reviews_tool,
        name="analyze_competitor_reviews",
        description=(
            "竞品评论深度分析：挖掘竞品评论中的优劣势、用户痛点、差异化机会。"
            "当用户想分析竞品评论/看竞品口碑/找差异化机会时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_detect_intruders_tool,
        name="detect_intruders",
        description=(
            "入侵者检测：发现近期进入市场的新卖家/新产品，评估威胁等级并给出应对策略。"
            "当用户想看新进入的竞争者/入侵者/新卖家威胁时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_buy_box_tool,
        name="analyze_buy_box",
        description=(
            "Buy Box 竞争分析：分析 Buy Box 竞争格局、价格竞争力、赢取建议。"
            "当用户想分析 Buy Box/购物车竞争/价格竞争力时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_compare_competitors_tool,
        name="compare_competitors",
        description=(
            "多维度竞品对比：从价格、评分、评论、BSR、性价比等维度全面对比多个竞品。"
            "当用户想对比竞品/对比多个 ASIN 优劣势时使用。"
        ),
    ),
]

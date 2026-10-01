"""
竞品情报监控模块 → 主 Agent 工具注册表

把 CompetitorIntelService 的细粒度能力包装成 langchain 工具，供竞品监控员
（`CompetitorIntelligenceAgent._build_router()`，第 198 轮从范式 B 迁到范式 A）
通过 bind_tools 自主选择调用。

★ 第 207 轮退役 5 条工具（老板裁决）：`monitor_competitor` / `track_batch_asins` /
  `analyze_market_share` / `detect_intruders` / `analyze_buy_box`。
  **只退役工具包装，不动实现** —— `agent_competitor.py` 的 8 个能力方法与
  `router.py` 的 8 个端点**全部保留**，`/competitor/analyze` 的关键词路由照旧可达。
  退役的唯一后果：**模型自主选工具**时少这 5 个选项。
  （`detect_intruders` 是空壳 —— 唯一 return 是 `status="unsupported"` ⇒ 零能力损失。）

设计要点（与 product_research/tools.py 一致）：
- 只包「语义明确」的 3 个细粒度能力（定价 / 评论 / 多维度对比），**不包**
  `general_analysis` / `stream_chat` 这类粗粒度入口（交给 agent 内部
  _classify_intent 关键词表再判断一次，会与主 Agent 的 LLM 判断冲突）。
- 参数用扁平字段（照 listing 范式），工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

from typing import Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.serialization import dump_result as _dump
from ai_infra.tools.side_effects import READ_ONLY_METADATA

from .service import CompetitorIntelService
from .schemas import (
    PricingAnalysisRequest,
    ReviewAnalysisRequest,
    CompetitorCompareRequest,
)

# 单例 service（与 router 同源）
_service = CompetitorIntelService()


def _shop_id() -> Optional[str]:
    """工具可见的店铺归属（★★★ **服务端上下文注入，不是 LLM 入参**）。

    ★ 第 198 轮修复：竞品工具改造前**一个都没传 `store_id`** ⇒
      `CompetitorIntelService` 收到 `None` ⇒ `_ensure_source()` 直接判
      `no_data`（理由「未绑定店铺上下文（请求缺少 X-Shop-ID）」）
      ⇒ 工具**永远拿不到数据**。
      这个缺陷此前完全不可见，正因为注册表悬空、没有任何 Agent 装配它们
      —— 「接上工具」这一步才把它暴露出来（先接线、再谈效果的意义所在）。

    ★ 为什么不把 `store_id` 做成工具形参：归属由模型生成就等于把租户边界
      交给模型（同族判据：归属只能服务端注入）。
    """
    from .agent_competitor import _current_shop_id

    return _current_shop_id.get()


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
    resp = await _service.analyze_pricing_strategy(req, store_id=_shop_id())
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
    resp = await _service.analyze_competitor_reviews(req, store_id=_shop_id())
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
    resp = await _service.compare_competitors(req, store_id=_shop_id())
    return _dump(resp)


# ====== 工具注册表 ======

competitor_intel_tools = [
    StructuredTool.from_function(
        coroutine=_analyze_pricing_strategy_tool,
        name="analyze_pricing_strategy",
        description=(
            "定价策略分析：分析竞品的定价模式、促销节奏、价格弹性，给出调价建议。"
            "当用户想分析竞品定价/看价格策略/促销节奏时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_analyze_competitor_reviews_tool,
        name="analyze_competitor_reviews",
        description=(
            "竞品评论深度分析：挖掘竞品评论中的优劣势、用户痛点、差异化机会。"
            "当用户想分析竞品评论/看竞品口碑/找差异化机会时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_compare_competitors_tool,
        name="compare_competitors",
        description=(
            "多维度竞品对比：从价格、评分、评论、BSR、性价比等维度全面对比多个竞品。"
            "当用户想对比竞品/对比多个 ASIN 优劣势时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
]

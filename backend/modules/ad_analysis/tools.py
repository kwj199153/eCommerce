"""
广告分析模块 → 主 Agent 工具注册表

把 AdAnalysisService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 listing_tools.py 一致）：
- 只包「语义明确」的细粒度方法（诊断 / 搜索词 / 出价 / 竞品 / 预算 / 异常检测），
  **不包** `chat` / `stream_chat` 粗粒度入口。
- 说明：本模块 service 层 6 个方法虽底层仍走 `agent.invoke`（内部 `_classify_intent`
  会再分一次类），但每个方法都构造了**明确的固定 query**（如「请对广告账户进行
  全面诊断」），因此二次分类结果恒正确、不会与主 Agent 判断冲突——故工具层直接
  包 service 方法即可，无需照 listing 新增直调。
- 参数用扁平字段，工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool

from .service import AdAnalysisService
from .schemas import (
    AdDiagnosisRequest,
    SearchTermAnalysisRequest,
    BidOptimizationRequest,
    CompetitorAnalysisRequest,
    BudgetOptimizationRequest,
    AnomalyDetectionRequest,
)

_service = AdAnalysisService()


def _dump(resp) -> str:
    """统一序列化：dict 直接 dump，Pydantic 走 model_dump。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


async def _diagnose_tool(
    time_range: str = "30d",
    include_benchmark: bool = True,
) -> str:
    """广告账户健康诊断：多维度评估表现，生成评级与问题清单。

    Args:
        time_range: 时间范围（7d/30d/90d，默认 30d）。
        include_benchmark: 是否包含行业基准对比（默认是）。
    """
    req = AdDiagnosisRequest(time_range=time_range, include_benchmark=include_benchmark)
    resp = await _service.diagnose(req)
    return _dump(resp)


async def _analyze_search_terms_tool(
    time_range: str = "30d",
    sort_by: str = "spend",
    min_spend: float = 5.0,
    min_clicks: int = 5,
) -> str:
    """搜索词效果分析：识别高效/低效/浪费词，挖掘新机会词。

    Args:
        time_range: 时间范围（默认 30d）。
        sort_by: 排序字段 spend/sales/acos/ctr（默认 spend）。
        min_spend: 最小花费过滤（默认 5）。
        min_clicks: 最小点击过滤（默认 5）。
    """
    req = SearchTermAnalysisRequest(
        time_range=time_range, sort_by=sort_by, min_spend=min_spend, min_clicks=min_clicks
    )
    resp = await _service.analyze_search_terms(req)
    return _dump(resp)


async def _optimize_bids_tool(
    strategy: str = "balanced",
    target_acos: Optional[float] = None,
    keywords: Optional[list[str]] = None,
) -> str:
    """出价优化建议：按策略给出关键词/广告组的智能出价建议。

    Args:
        strategy: 策略 aggressive/conservative/balanced（默认 balanced）。
        target_acos: 目标 ACoS（%，可选）。
        keywords: 指定关键词（可选，空则自动分析）。
    """
    req = BidOptimizationRequest(strategy=strategy, target_acos=target_acos, keywords=keywords)
    resp = await _service.optimize_bids(req)
    return _dump(resp)


async def _analyze_competitors_tool(
    competitor_asins: Optional[list[str]] = None,
    auto_detect: bool = True,
    time_range: str = "30d",
) -> str:
    """竞品广告分析：分析竞争对手广告策略、展示份额、关键词重叠。

    Args:
        competitor_asins: 竞品 ASIN 列表（可选，空则自动检测）。
        auto_detect: 是否自动检测竞品（默认是）。
        time_range: 时间范围（默认 30d）。
    """
    req = CompetitorAnalysisRequest(
        competitor_asins=competitor_asins, auto_detect=auto_detect, time_range=time_range
    )
    resp = await _service.analyze_competitors(req)
    return _dump(resp)


async def _optimize_budget_tool(
    total_daily_budget: Optional[float] = None,
    target_roas: Optional[float] = None,
    seasonality_factor: str = "normal",
) -> str:
    """预算分配优化：多 Campaign 智能分配预算，提升整体 ROI。

    Args:
        total_daily_budget: 总日预算（USD，可选，空则基于当前）。
        target_roas: 目标 RoAS（可选）。
        seasonality_factor: 季节性 low/normal/high/peak（默认 normal）。
    """
    req = BudgetOptimizationRequest(
        total_daily_budget=total_daily_budget,
        target_roas=target_roas,
        seasonality_factor=seasonality_factor,
    )
    resp = await _service.optimize_budget(req)
    return _dump(resp)


async def _detect_anomalies_tool(
    check_period: str = "7d",
    sensitivity: str = "medium",
) -> str:
    """广告异常检测：自动检测花费突增、转化骤降等异常。

    Args:
        check_period: 检测周期 1d/7d/14d/30d（默认 7d）。
        sensitivity: 灵敏度 low/medium/high（默认 medium）。
    """
    req = AnomalyDetectionRequest(check_period=check_period, sensitivity=sensitivity)
    resp = await _service.detect_anomalies(req)
    return _dump(resp)


# ====== 工具注册表 ======

ad_analysis_tools = [
    StructuredTool.from_function(
        coroutine=_diagnose_tool,
        name="diagnose_ad_account",
        description=(
            "广告账户健康诊断：多维度评估广告表现，生成评级与问题清单。"
            "当用户想诊断广告/体检/看广告健康/广告表现怎么样时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_search_terms_tool,
        name="analyze_search_terms",
        description=(
            "搜索词效果分析：识别高效/低效/浪费词，挖掘新机会词。"
            "当用户想看搜索词报告/哪些词表现好/词报告时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_optimize_bids_tool,
        name="optimize_bids",
        description=(
            "出价优化建议：按策略给出关键词/广告组的智能出价建议。"
            "当用户想优化出价/调价/给出价建议/控制 ACOS 时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_competitors_tool,
        name="analyze_ad_competitors",
        description=(
            "竞品广告分析：分析竞争对手广告策略、展示份额、关键词重叠。"
            "当用户想分析竞品广告/对手投放/展示份额时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_optimize_budget_tool,
        name="optimize_budget",
        description=(
            "预算分配优化：多 Campaign 智能分配预算，提升整体 ROI。"
            "当用户想优化预算/分配预算/调拨预算/提升 ROI 时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_detect_anomalies_tool,
        name="detect_ad_anomalies",
        description=(
            "广告异常检测：自动检测花费突增、转化骤降等异常。"
            "当用户想查异常/看有没有突然变化/检测波动时使用。"
        ),
    ),
]

"""
竞品情报监控 - API 路由
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from core.billing.usage_tracker import meter_agent_chat
from typing import Optional, List

from ai_infra.sse import sse_event_stream

from .schemas import (
    CompetitorMonitorRequest, BatchTrackRequest, MarketShareRequest,
    PricingAnalysisRequest, ReviewAnalysisRequest, IntruderDetectionRequest,
    BuyBoxAnalysisRequest, CompetitorCompareRequest, CompetitorAnalysisResponse,
)
from . import service
from .service import CompetitorIntelService

router = APIRouter(prefix="/competitor", tags=["竞品情报监控"])


# ==================== 竞品监控 ====================

@router.post("/monitor", response_model=CompetitorAnalysisResponse, summary="竞品 Listing 监控")
async def monitor_competitor(request: CompetitorMonitorRequest):
    """
    监控竞品 Listing 的关键指标变化

    - **asin**: 指定ASIN则返回单品深度分析，为空返回所有竞品概览
    - **days**: 分析时间范围（7-90天）

    返回：价格变化、排名趋势、库存状态、警报信息
    """
    try:
        result = await service.monitor_competitor(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"监控分析失败: {str(e)}")


@router.get("/monitor/dashboard", response_model=CompetitorAnalysisResponse, summary="监控仪表盘")
async def get_monitor_dashboard():
    """获取所有竞品的监控仪表盘数据（无需参数）"""
    request = CompetitorMonitorRequest()
    return await service.monitor_competitor(request)


# ==================== 批量追踪 ====================

@router.post("/track/batch", response_model=CompetitorAnalysisResponse, summary="ASIN 批量追踪")
async def track_batch_asins(request: BatchTrackRequest):
    """
    批量追踪多个 ASIN 的关键指标

    - **asins**: ASIN列表（1-20个）
    - **include_history**: 是否包含历史趋势数据

    返回：各竞品对比矩阵、综合得分排名
    """
    try:
        result = await service.track_batch_asins(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量追踪失败: {str(e)}")


# ==================== 市场份额分析 ====================

@router.post("/market-share", response_model=CompetitorAnalysisResponse, summary="市场份额分析")
async def analyze_market_share(request: MarketShareRequest):
    """
    分析目标类目的市场竞争格局

    - **category**: 产品类目
    - **estimate_method**: 估算方法（bsr_based / revenue_based）

    返回：各品牌市场份额、CR4集中度、HHI指数、市场洞察
    """
    try:
        result = await service.analyze_market_share(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"市场份额分析失败: {str(e)}")


@router.get("/market-share/{category}", response_model=CompetitorAnalysisResponse, summary="按类目查市场份额")
async def get_market_share_by_category(
    category: str,
):
    """快捷接口：按类目获取市场份额分析"""
    request = MarketShareRequest(category=category)
    return await service.analyze_market_share(request)


# ==================== 定价策略分析 ====================

@router.post("/pricing/analyze", response_model=CompetitorAnalysisResponse, summary="定价策略分析")
async def analyze_pricing_strategy(request: PricingAnalysisRequest):
    """
    分析竞品的定价策略和模式

    - **asin**: 目标ASIN（可选，为空分析所有）
    - **analysis_depth**: 分析深度（basic / standard / deep）

    返回：策略类型、促销频率、价格弹性、调价建议
    """
    try:
        result = await service.analyze_pricing_strategy(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"定价策略分析失败: {str(e)}")


# ==================== 评论深度分析 ====================

@router.post("/reviews/analyze", response_model=CompetitorAnalysisResponse, summary="竞品评论分析")
async def analyze_competitor_reviews(request: ReviewAnalysisRequest):
    """
    深度分析竞品评论，挖掘优劣势和机会

    - **asin**: 目标竞品ASIN
    - **aspects**: 关注维度列表（可选）
    - **sample_size**: 采样评论数

    返回：评论洞察、SWOT分析、可行动情报
    """
    try:
        result = await service.analyze_competitor_reviews(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评论分析失败: {str(e)}")


@router.get("/reviews/{asin}", response_model=CompetitorAnalysisResponse, summary="快捷评论分析")
async def get_review_analysis(asin: str):
    """快捷接口：分析指定ASIN的评论"""
    request = ReviewAnalysisRequest(asin=asin.upper())
    return await service.analyze_competitor_reviews(request)


# ==================== 入侵者检测 ====================

@router.post("/intruders/detect", response_model=CompetitorAnalysisResponse, summary="入侵者检测")
async def detect_intruders(request: IntruderDetectionRequest):
    """
    检测新进入市场的竞争者

    - **category**: 监控类目
    - **lookback_days**: 回溯天数
    - **min_reviews_threshold**: 新卖家最低评论阈值

    返回：新竞争者列表、威胁等级、应对策略建议
    """
    try:
        result = await service.detect_intruders(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"入侵者检测失败: {str(e)}")


@router.get("/intruders/{category}", response_model=CompetitorAnalysisResponse, summary="快捷入侵者检测")
async def detect_intruders_by_category(
    category: str,
):
    """快捷接口：检测指定类目的新进入者"""
    request = IntruderDetectionRequest(category=category)
    return await service.detect_intruders(request)


# ==================== Buy Box 分析 ====================

@router.post("/buy-box/analyze", response_model=CompetitorAnalysisResponse, summary="Buy Box 竞争分析")
async def analyze_buy_box(request: BuyBoxAnalysisRequest):
    """
    分析 Buy Box 竞争格局

    - **asin**: 目标ASIN（可选）
    - **marketplace**: 站点（US / UK / DE / JP）

    返回：Buy Box 赢家、价格竞争力、赢取建议
    """
    try:
        result = await service.analyze_buy_box(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Buy Box 分析失败: {str(e)}")


# ==================== 竞品对比 ====================

@router.post("/compare", response_model=CompetitorAnalysisResponse, summary="多维度竞品对比")
async def compare_competitors(request: CompetitorCompareRequest):
    """
    多维度全面对比多个竞品

    - **asins**: 要对比的ASIN列表（2-10个）
    - **dimensions**: 对比维度（price/rating/reviews/bsr/value）

    返回：各维度对比、性价比得分、总体排名、差异化分析
    """
    try:
        if len(request.asins) < 2:
            raise HTTPException(status_code=400, detail="至少需要2个ASIN进行对比")

        result = await service.compare_competitors(request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"竞品对比失败: {str(e)}")


# ==================== 通用入口 ====================

@router.post("/analyze", response_model=CompetitorAnalysisResponse, summary="通用分析入口")
async def general_analysis(
    query: str = Query(..., description="自然语言查询"),
    context: Optional[dict] = None,
):
    """
    自然语言分析入口

    自动识别用户意图并路由到对应的分析能力：
    - "监控 B08ABC1234" → 单品监控
    - "耳机市场份额" → 市场格局分析
    - "新进入的竞争者" → 入侵者检测
    - "对比这几个ASIN" → 多维对比
    """
    try:
        result = await service.general_analysis(query=query, context=context)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


@router.post("/chat/stream", summary="竞品情报对话（SSE 流式）")
async def chat_stream(
    query: str = Query(..., description="自然语言查询"),
    _meter=Depends(meter_agent_chat),
):
    """竞品情报对话，SSE 流式返回（打字机效果）。"""
    import json as _json

    async def _wrapped():
        try:
            async for event in sse_event_stream(CompetitorIntelService.stream_chat(query)):
                yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")

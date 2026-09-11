"""
广告分析模块 - API 路由 (Router)

提供广告分析相关的 RESTful API 端点
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from core.billing.usage_tracker import meter_agent_chat
from typing import Optional, List

from ai_infra.sse import sse_event_stream

from .schemas import (
    AdDiagnosisRequest,
    SearchTermAnalysisRequest,
    BidOptimizationRequest,
    CompetitorAnalysisRequest,
    BudgetOptimizationRequest,
    AnomalyDetectionRequest,
    AdChatRequest,
    ApiResponse,
    ErrorResponse,
)
from .service import AdAnalysisService

router = APIRouter(prefix="/ad-analysis", tags=["广告分析"])


@router.post("/diagnose", summary="广告账户健康诊断")
async def diagnose(request: AdDiagnosisRequest):
    """
    对广告账户进行全面健康诊断

    - 多维度指标评估（ACoS/RoAS/CTR/CVR/CPC）
    - 各 Campaign 健康评分
    - 问题识别与优先级排序
    - 可执行的优化建议
    - A-F 综合评级
    """
    try:
        result = await AdAnalysisService.diagnose(request)
        return ApiResponse(success=True, message="诊断完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search-terms", summary="搜索词效果分析")
async def analyze_search_terms(request: SearchTermAnalysisRequest):
    """
    分析搜索词表现，识别机会与问题

    - 高效词识别（ACoS < 20%，持续投入）
    - 低效词识别（需优化出价或匹配方式）
    - 浪费词识别（有花费无销售，建议否定）
    - 新机会词挖掘（有初步转化潜力）
    """
    try:
        result = await AdAnalysisService.analyze_search_terms(request)
        return ApiResponse(success=True, message="分析完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bid-optimize", summary="出价优化建议")
async def optimize_bids(request: BidOptimizationRequest):
    """
    生成智能出价优化建议

    - 支持三种策略：激进型/保守型/平衡型
    - 每个关键词的当前出价 vs 建议出价
    - 调整理由和预期影响
    - 优先级排序（high/medium/low）
    - 整体预算影响预估
    """
    try:
        result = await AdAnalysisService.optimize_bids(request)
        return ApiResponse(success=True, message="出价建议生成完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/competitors", summary="竞品广告分析")
async def analyze_competitors(request: CompetitorAnalysisRequest):
    """
    分析竞争对手的广告策略

    - 展示份额 (Share of Voice) 对比
    - 关键词重叠分析
    - 竞品出价策略推测
    - 可执行的市场洞察
    """
    try:
        result = await AdAnalysisService.analyze_competitors(request)
        return ApiResponse(success=True, message="竞品分析完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/budget", summary="预算分配优化")
async def optimize_budget(request: BudgetOptimizationRequest):
    """
    优化多 Campaign 预算分配

    - 基于历史 ROI 的智能分配
    - 各 Campaign 建议预算及理由
    - 预期改善效果量化
    - 风险评估与实施建议
    """
    try:
        result = await AdAnalysisService.optimize_budget(request)
        return ApiResponse(success=True, message="预算方案生成完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomalies", summary="广告异常检测")
async def detect_anomalies(request: AnomalyDetectionRequest):
    """
    检测广告数据异常情况

    - 花费突增预警
    - 转化率骤降检测
    - 展示量异常识别
    - CTR 异常波动告警
    - 可能原因分析与建议操作
    """
    try:
        result = await AdAnalysisService.detect_anomalies(request)
        return ApiResponse(success=True, message="异常检测完成", data=result.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", summary="自然语言对话")
async def chat(
    request: AdChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """
    广告分析师对话入口（推荐使用）

    支持自然语言提问，自动路由到对应的分析功能：
    - "帮我做一下广告体检" → 诊断
    - "看看搜索词报告" → 搜索词分析
    - "给我一些出价建议" → 出价优化
    - "分析竞品" → 竞品监控
    - "优化预算" → 预算分配
    - "有没有异常" → 异常检测
    """
    try:
        result = await AdAnalysisService.chat(request)
        return ApiResponse(
            success=True,
            message="OK",
            data={
                "reply": result.reply,
                "data": result.data,
                "display_type": result.display_type,
                "suggestions": result.suggestions,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream", summary="自然语言对话（SSE 流式）")
async def chat_stream(
    request: AdChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """广告分析师对话，SSE 流式返回（打字机效果）。"""
    import json as _json

    async def _wrapped():
        try:
            async for event in sse_event_stream(AdAnalysisService.stream_chat(request.message)):
                yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


@router.get("/capabilities", summary="查询 Agent 能力")
async def get_capabilities():
    """获取广告分析师的能力说明"""
    capabilities = await AdAnalysisService.get_capabilities()
    return ApiResponse(success=True, data=capabilities)


# ====== 快捷端点（简化参数）=====

@router.get("/quick/diagnose", summary="快速诊断（GET）")
async def quick_diagnose(
    time_range: str = Query(default="30d", description="时间范围"),
):
    """快捷诊断接口，无需 POST 完整请求体"""
    request = AdDiagnosisRequest(time_range=time_range)
    return await diagnose(request)


@router.get("/quick/anomalies", summary="快速异常检测（GET）")
async def quick_anomalies(
    period: str = Query(default="7d", description="检测周期"),
):
    """快捷异常检测"""
    request = AnomalyDetectionRequest(check_period=period)
    return await detect_anomalies(request)

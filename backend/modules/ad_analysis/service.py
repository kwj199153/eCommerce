"""
广告分析模块 - 业务逻辑层 (Service)

封装广告分析的核心业务逻辑，供 Router 调用
"""

from typing import List, Optional, Any, Dict
import logging

from .agent_ad import AdAnalysisAgent
from .schemas import (
    AdDiagnosisRequest,
    SearchTermAnalysisRequest,
    BidOptimizationRequest,
    CompetitorAnalysisRequest,
    BudgetOptimizationRequest,
    AnomalyDetectionRequest,
    AdChatRequest,
    DiagnosisResponse,
    SearchTermResponse,
    BidStrategyResponse,
    CompetitorResponse,
    BudgetOptimizationResponse,
    AnomalyResponse,
    ChatResponse,
)

logger = logging.getLogger(__name__)

# 全局 Agent 实例（单例）
_agent_instance: Optional[AdAnalysisAgent] = None


def get_agent() -> AdAnalysisAgent:
    """获取 Agent 单例"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = AdAnalysisAgent()
        logger.info("AdAnalysisAgent 初始化完成")
    return _agent_instance


class NoDataError(Exception):
    """取不到数据（未绑定店铺 / 数据源无记录）。

    ★ 为什么不直接抛 HTTPException：「没数据」在语义上不是服务端故障，
      路由层要把它转成 `success=False` + 显式原因的业务响应，
      而不是 500 —— 否则前端只能看到「服务器错误」，真实缺口被掩盖。
    """

    def __init__(self, status: str, reason, payload: dict):
        super().__init__(reason or status)
        self.status = status or "no_data"
        self.reason = reason or "数据源未返回可用数据"
        self.payload = payload or {}


def _guard(response, data: dict) -> None:
    """空状态**原样透传**，不进 Response 模型。

    `_no_data()` 只给 `data_status/data_reason`，而各 Response 类字段多为
    **必填** ⇒ `XResponse(**data)` 会抛 ValidationError ⇒ router 转 500。
    """
    if not response.success or response.data_status != "ok":
        raise NoDataError(response.data_status, response.data_reason, data)


class AdAnalysisService:
    """广告分析服务"""

    @staticmethod
    async def diagnose(request: AdDiagnosisRequest, store_id: Optional[str] = None) -> DiagnosisResponse:
        """
        广告账户健康诊断

        Args:
            request: 诊断请求参数

        Returns:
            诊断报告
        """
        agent = get_agent()
        query = f"请对广告账户进行全面诊断，时间范围 {request.time_range}"

        context = {
            "store_id": store_id,
            "time_range": request.time_range,
            "campaign_ids": request.campaign_ids,
            "include_benchmark": request.include_benchmark,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return DiagnosisResponse(**data)

    @staticmethod
    async def analyze_search_terms(request: SearchTermAnalysisRequest, store_id: Optional[str] = None) -> SearchTermResponse:
        """
        搜索词效果分析

        Args:
            request: 分析请求参数

        Returns:
            搜索词报告
        """
        agent = get_agent()
        query = f"分析搜索词表现，按 {request.sort_by} 排序"

        context = {
            "store_id": store_id,
            "time_range": request.time_range,
            "campaign_type": request.campaign_type,
            "min_spend": request.min_spend,
            "min_clicks": request.min_clicks,
            "sort_by": request.sort_by,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return SearchTermResponse(**data)

    @staticmethod
    async def optimize_bids(request: BidOptimizationRequest, store_id: Optional[str] = None) -> BidStrategyResponse:
        """
        出价优化建议

        Args:
            request: 优化请求参数

        Returns:
            出价建议报告
        """
        agent = get_agent()
        strategy_map = {
            "aggressive": "激进型（追求曝光和市场份额）",
            "conservative": "保守型（控制成本优先）",
            "balanced": "平衡型（兼顾效率与增长）",
        }
        query = f"给出价建议，策略：{strategy_map.get(request.strategy, '平衡')}"

        if request.target_acos:
            query += f"，目标 ACoS {request.target_acos}%"

        context = {
            "store_id": store_id,
            "strategy": request.strategy,
            "keywords": request.keywords,
            "max_budget_change": request.max_budget_change,
            "target_acos": request.target_acos,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return BidStrategyResponse(**data)

    @staticmethod
    async def analyze_competitors(request: CompetitorAnalysisRequest, store_id: Optional[str] = None) -> CompetitorResponse:
        """
        竞品广告分析

        Args:
            request: 分析请求参数

        Returns:
            竞品报告
        """
        agent = get_agent()

        asin_str = ", ".join(request.competitor_asins) if request.competitor_asins else "自动检测"
        query = f"分析竞品广告策略，目标 ASIN：{asin_str}"

        context = {
            "store_id": store_id,
            "competitor_asins": request.competitor_asins,
            "auto_detect": request.auto_detect,
            "include_keywords": request.include_keywords,
            "time_range": request.time_range,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return CompetitorResponse(**data)

    @staticmethod
    async def optimize_budget(request: BudgetOptimizationRequest, store_id: Optional[str] = None) -> BudgetOptimizationResponse:
        """
        预算分配优化

        Args:
            request: 优化请求参数

        Returns:
            预算分配方案
        """
        agent = get_agent()

        seasonality_map = {
            "low": "淡季（减少投放）",
            "normal": "正常季节",
            "high": "旺季前（逐步加码）",
            "peak": "旺季（全力投放）",
        }

        query = f"优化预算分配，{seasonality_map.get(request.seasonality_factor, '正常季节')}"

        if request.target_roas:
            query += f"，目标 RoAS {request.target_roas}x"
        if request.total_daily_budget:
            query += f"，总日预算 ${request.total_daily_budget}"

        context = {
            "store_id": store_id,
            "total_daily_budget": request.total_daily_budget,
            "target_roas": request.target_roas,
            "min_campaign_budget": request.min_campaign_budget,
            "seasonality_factor": request.seasonality_factor,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return BudgetOptimizationResponse(**data)

    @staticmethod
    async def detect_anomalies(request: AnomalyDetectionRequest, store_id: Optional[str] = None) -> AnomalyResponse:
        """
        广告异常检测

        Args:
            request: 检测请求参数

        Returns:
            异常检测报告
        """
        agent = get_agent()
        sensitivity_map = {
            "low": "低灵敏度（仅报严重异常）",
            "medium": "中灵敏度（推荐）",
            "high": "高灵敏度（捕捉所有波动）",
        }

        query = f"检测广告数据异常，{sensitivity_map.get(request.sensitivity, '中灵敏度')}"

        context = {
            "store_id": store_id,
            "check_period": request.check_period,
            "sensitivity": request.sensitivity,
            "alert_thresholds": request.alert_thresholds,
            "notify": request.notify,
        }

        response = await agent.invoke(query, context)
        data = response.data or {}

        _guard(response, data)
        return AnomalyResponse(**data)

    @staticmethod
    async def chat(request: AdChatRequest, store_id: Optional[str] = None) -> ChatResponse:
        """
        自然语言对话（主入口）

        Args:
            request: 对话请求

        Returns:
            对话响应
        """
        agent = get_agent()

        response = await agent.invoke(
            query=request.message,
            context={"context_id": request.context_id, "store_id": store_id}
        )

        # 生成后续建议
        suggestions = [
            "帮我做一下广告体检",
            "看看搜索词报告",
            "给我一些出价建议",
            "分析一下竞品广告",
            "优化一下预算分配",
            "最近有没有异常",
        ]

        return ChatResponse(
            reply=response.content,
            data=response.data,
            display_type=response.display_type,
            suggestions=suggestions[:3] if response.display_type == "text" else None,
        )

    @staticmethod
    async def stream_chat(message: str, store_id: Optional[str] = None):
        """流式对话入口（返回逐 token 异步迭代器）"""
        agent = get_agent()
        async for chunk in agent.stream_chat(message, {"store_id": store_id}):
            yield chunk

    @staticmethod
    async def get_capabilities() -> Dict[str, Any]:
        return {
            "agent_name": "广告分析师",
            "agent_id": "ad-analysis",
            "version": "1.0.0",
            "status": "active",
            "description": "Amazon PPC 广告全链路分析与优化专家",
            "capabilities": [
                {
                    "id": "diagnosis",
                    "name": "广告健康诊断",
                    "description": "多维度评估账户/Campaign 表现，生成 A-F 评级报告",
                    "endpoint": "/api/v1/ad-analysis/diagnose",
                    "input_fields": ["time_range", "campaign_ids"],
                },
                {
                    "id": "search_terms",
                    "name": "搜索词分析",
                    "description": "识别高效/低效/浪费词，挖掘新机会词",
                    "endpoint": "/api/v1/ad-analysis/search-terms",
                    "input_fields": ["time_range", "campaign_type", "min_spend"],
                },
                {
                    "id": "bid_optimize",
                    "name": "出价优化",
                    "description": "数据驱动的智能出价建议，支持多种策略模式",
                    "endpoint": "/api/v1/ad-analysis/bid-optimize",
                    "input_fields": ["strategy", "keywords", "target_acos"],
                },
                {
                    "id": "competitor",
                    "name": "竞品监控",
                    "description": "分析竞争对手广告策略、展示份额、关键词重叠",
                    "endpoint": "/api/v1/ad-analysis/competitors",
                    "input_fields": ["competitor_asins", "auto_detect"],
                },
                {
                    "id": "budget",
                    "name": "预算优化",
                    "description": "多Campaign 智能预算分配，提升整体 ROI",
                    "endpoint": "/api/v1/ad-analysis/budget",
                    "input_fields": ["total_daily_budget", "target_roas"],
                },
                {
                    "id": "anomaly",
                    "name": "异常检测",
                    "description": "自动检测花费突增、转化骤降等异常情况",
                    "endpoint": "/api/v1/ad-analysis/anomalies",
                    "input_fields": ["check_period", "sensitivity"],
                },
            ],
            "supported_platforms": ["amazon"],
            "data_freshness": "T-1（前一天数据）",
        }

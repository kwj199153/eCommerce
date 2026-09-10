"""
竞品情报监控 - 业务逻辑层
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from .agent_competitor import CompetitorIntelligenceAgent
from .schemas import (
    CompetitorMonitorRequest, BatchTrackRequest, MarketShareRequest,
    PricingAnalysisRequest, ReviewAnalysisRequest, IntruderDetectionRequest,
    BuyBoxAnalysisRequest, CompetitorCompareRequest,
    CompetitorAnalysisResponse,
)

logger = logging.getLogger(__name__)

# 全局 Agent 实例
_agent_instance: Optional[CompetitorIntelligenceAgent] = None


def _get_agent() -> CompetitorIntelligenceAgent:
    """获取或创建 Agent 实例（单例）"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CompetitorIntelligenceAgent()
    return _agent_instance


# ==================== 核心服务方法 ====================

async def monitor_competitor(request: CompetitorMonitorRequest) -> Dict[str, Any]:
    """
    竞品 Listing 监控

    用途：追踪竞品的价格、排名、评论数、库存状态变化
    """
    agent = _get_agent()
    context = {"asin": request.asin}

    result = await agent.monitor_competitor(
        query=f"监控竞品 {request.asin or '全部'}",
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"成功获取 {result.get('total_competitors', 0)} 个竞品的监控数据",
        "timestamp": datetime.now().isoformat(),
    }


async def track_batch_asins(request: BatchTrackRequest) -> Dict[str, Any]:
    """
    ASIN 批量追踪

    用途：批量对比多个竞品的关键指标
    """
    agent = _get_agent()
    context = {"asins": request.asins}

    result = await agent.track_batch_asins(
        query=f"批量追踪 {', '.join(request.asins[:5])}{'...' if len(request.asins) > 5 else ''}",
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"成功追踪 {result.get('tracked_count', 0)} 个竞品",
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_market_share(request: MarketShareRequest) -> Dict[str, Any]:
    """
    市场份额分析

    用途：基于 BSR 排名估算各品牌市场份额和竞争格局
    """
    agent = _get_agent()
    context = {"category": request.category}

    result = await agent.analyze_market_share(
        query=f"分析 {request.category} 类目的市场份额",
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"完成 {request.category} 类目市场格局分析",
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_pricing_strategy(request: PricingAnalysisRequest) -> Dict[str, Any]:
    """
    定价策略分析

    用途：分析竞品的定价模式、促销节奏、价格弹性
    """
    agent = _get_agent()
    query = f"分析定价策略"
    if request.asin:
        query += f" {request.asin}"
    if request.compare_asins:
        query += f" 对比 {', '.join(request.compare_asins[:3])}"

    context = {
        "asin": request.asin,
        "compare_asins": request.compare_asins,
    }

    result = await agent.analyze_pricing_strategy(
        query=query,
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"完成 {result.get('analyzed_count', 0)} 个产品的定价策略分析",
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_competitor_reviews(request: ReviewAnalysisRequest) -> Dict[str, Any]:
    """
    竞品评论深度分析

    用途：挖掘竞品评论中的优劣势、用户痛点、差异化机会
    """
    agent = _get_agent()

    aspects_str = ", ".join(request.aspects) if request.aspects else "全维度"
    context = {"asin": request.asin, "aspects": request.aspects}

    result = await agent.analyze_competitor_reviews(
        query=f"分析 {request.asin} 的评论（关注{aspects_str}）",
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"完成 {result.get('analyzed_products', 0)} 个产品的评论深度分析",
        "timestamp": datetime.now().isoformat(),
    }


async def detect_intruders(request: IntruderDetectionRequest) -> Dict[str, Any]:
    """
    入侵者检测（新竞争者识别）

    用途：发现近期进入市场的新卖家/新产品，评估威胁等级
    """
    agent = _get_agent()
    context = {"category": request.category}

    result = await agent.detect_intruders(
        query=f"检测 {request.category} 类目的新进入者",
        context=context,
    )

    threat_summary = result.get("threat_summary", {})
    new_count = sum(threat_summary.values())

    return {
        "success": True,
        "data": result,
        "message": f"检测到 {new_count} 个新进入市场的竞争者",
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_buy_box(request: BuyBoxAnalysisRequest) -> Dict[str, Any]:
    """
    Buy Box 竞争分析

    用途：分析 Buy Box 竞争格局、价格竞争力、赢取建议
    """
    agent = _get_agent()
    query = f"分析 Buy Box 竞争"
    if request.asin:
        query += f" {request.asin}"

    context = {"asin": request.asin, "marketplace": request.marketplace}

    result = await agent.analyze_buy_box(
        query=query,
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"完成 {result.get('analyzed_count', 0)} 个产品的 Buy Box 分析",
        "timestamp": datetime.now().isoformat(),
    }


async def compare_competitors(request: CompetitorCompareRequest) -> Dict[str, Any]:
    """
    多维度竞品对比

    用途：从价格、评分、评论、BSR、性价比等多维度全面对比
    """
    agent = _get_agent()
    context = {"asins": request.asins, "dimensions": request.dimensions}

    result = await agent.compare_competitors(
        query=f"对比竞品 {', '.join(request.asins[:4])}",
        context=context,
    )

    return {
        "success": True,
        "data": result,
        "message": f"完成 {result.get('compared_count', 0)} 个竞品的多维度对比",
        "timestamp": datetime.now().isoformat(),
    }


async def general_analysis(query: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    通用分析入口（自然语言查询）

    用途：处理用户的自然语言请求，自动路由到对应能力
    """
    agent = _get_agent()

    result = await agent.analyze(query=query, context=context)

    return {
        "success": True,
        "data": result,
        "message": "分析完成",
        "timestamp": datetime.now().isoformat(),
    }

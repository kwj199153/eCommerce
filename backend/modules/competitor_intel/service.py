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


def _ok(result: Any) -> bool:
    """按结果判定 success。

    ★ 改造前 9 个服务方法把 `"success": True` **硬编码**：即使返回
      `{"error": ...}`（对比不足 2 个竞品）或 `data_status=no_data`（没绑定店铺）
      也报「成功」—— 前端只判 success 就判不出任何失败（伪成功）。
    """
    if not isinstance(result, dict):
        return True
    if result.get("error"):
        return False
    return result.get("data_status") not in ("no_data", "unsupported")


def _message(result: Dict[str, Any], ok: str) -> str:
    """按 payload 决定信封里的 message（**唯一实现**）。

    ★ 为什么不能写「`result.get("message") or <固定成功文案>`」（2026-09-18 实测）：
      固定成功文案在**另一种形态**与**失败**下都会撒谎 ——
        · `/monitor` 传单个 ASIN → 返回完整单品分析，文案却写「成功获取 0 个竞品」；
        · `/monitor` 传未知 ASIN → `success=false`（`data.error` 已说明原因），
          文案仍写「成功获取 …」。
      前端的 toast 与运维日志都会把「失败」读成「成功了但没数据」——归因错方向。

    规则（顺序即优先级）：
      ① 结果自带 `message`（显式空状态 / 能力不支持）→ 原样采用；
      ② 结果带 `error`（如「未找到竞品 ASIN」）→ 直接说 error，不再包装成成功；
      ③ 否则用调用方给的 `ok` 文案。
    """
    if result.get("message"):
        return str(result["message"])
    if result.get("error"):
        return str(result["error"])
    return ok


def _get_agent() -> CompetitorIntelligenceAgent:
    """获取或创建 Agent 实例（单例）"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = CompetitorIntelligenceAgent()
    return _agent_instance


# ==================== 核心服务方法 ====================

async def monitor_competitor(request: CompetitorMonitorRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    竞品 Listing 监控

    用途：追踪竞品的价格、排名、评论数、库存状态变化
    """
    agent = _get_agent()
    context = {"store_id": store_id, "asin": request.asin}

    result = await agent._monitor_competitor(
        query=f"监控竞品 {request.asin or '全部'}",
        context=context,
    )

    # ★ ok 文案必须随 payload 形态走：单品监控没有 total_competitors，
    #   固定文案会写出「成功获取 0 个竞品」，与同一响应体里的 product 自相矛盾。
    if result.get("total_competitors") is not None:
        _ok_text = f"成功获取 {result['total_competitors']} 个竞品的监控数据"
    else:
        _asin = (result.get("product") or {}).get("asin")
        _ok_text = f"已完成 {_asin} 的单品深度监控" if _asin else "监控完成"

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, _ok_text),
        "timestamp": datetime.now().isoformat(),
    }


async def track_batch_asins(request: BatchTrackRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    ASIN 批量追踪

    用途：批量对比多个竞品的关键指标
    """
    agent = _get_agent()
    context = {"store_id": store_id, "asins": request.asins}

    result = await agent._track_batch_asins(
        query=f"批量追踪 {', '.join(request.asins[:5])}{'...' if len(request.asins) > 5 else ''}",
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"成功追踪 {result.get('tracked_count', 0)} 个竞品"),
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_market_share(request: MarketShareRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    市场份额分析

    用途：基于 BSR 排名估算各品牌市场份额和竞争格局
    """
    agent = _get_agent()
    context = {"category": request.category, "store_id": store_id}

    result = await agent._analyze_market_share(
        query=f"分析 {request.category} 类目的市场份额",
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"完成 {request.category} 类目市场格局分析"),
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_pricing_strategy(request: PricingAnalysisRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
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
        "store_id": store_id,
        "asin": request.asin,
        "compare_asins": request.compare_asins,
    }

    result = await agent._analyze_pricing_strategy(
        query=query,
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"完成 {result.get('analyzed_count', 0)} 个产品的定价策略分析"),
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_competitor_reviews(request: ReviewAnalysisRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    竞品评论深度分析

    用途：挖掘竞品评论中的优劣势、用户痛点、差异化机会
    """
    agent = _get_agent()

    aspects_str = ", ".join(request.aspects) if request.aspects else "全维度"
    context = {"store_id": store_id, "asin": request.asin, "aspects": request.aspects}

    result = await agent._analyze_competitor_reviews(
        query=f"分析 {request.asin} 的评论（关注{aspects_str}）",
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"完成 {result.get('analyzed_products', 0)} 个产品的评论深度分析"),
        "timestamp": datetime.now().isoformat(),
    }


async def detect_intruders(request: IntruderDetectionRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    入侵者检测（新竞争者识别）

    用途：发现近期进入市场的新卖家/新产品，评估威胁等级
    """
    agent = _get_agent()
    context = {"category": request.category, "store_id": store_id}

    result = await agent._detect_intruders(
        query=f"检测 {request.category} 类目的新进入者",
        context=context,
    )

    threat_summary = result.get("threat_summary", {})
    new_count = sum(threat_summary.values())

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"检测到 {new_count} 个新进入市场的竞争者"),
        "timestamp": datetime.now().isoformat(),
    }


async def analyze_buy_box(request: BuyBoxAnalysisRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Buy Box 竞争分析

    用途：分析 Buy Box 竞争格局、价格竞争力、赢取建议
    """
    agent = _get_agent()
    query = f"分析 Buy Box 竞争"
    if request.asin:
        query += f" {request.asin}"

    context = {"store_id": store_id, "asin": request.asin, "marketplace": request.marketplace}

    result = await agent._analyze_buy_box(
        query=query,
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"完成 {result.get('analyzed_count', 0)} 个产品的 Buy Box 分析"),
        "timestamp": datetime.now().isoformat(),
    }


async def compare_competitors(request: CompetitorCompareRequest, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    多维度竞品对比

    用途：从价格、评分、评论、BSR、性价比等多维度全面对比
    """
    agent = _get_agent()
    context = {"store_id": store_id, "asins": request.asins, "dimensions": request.dimensions}

    result = await agent._compare_competitors(
        query=f"对比竞品 {', '.join(request.asins[:4])}",
        context=context,
    )

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, f"完成 {result.get('compared_count', 0)} 个竞品的多维度对比"),
        "timestamp": datetime.now().isoformat(),
    }


async def general_analysis(query: str, context: Optional[Dict] = None,
                           store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    通用分析入口（自然语言查询）

    用途：处理用户的自然语言请求，自动路由到对应能力
    """
    agent = _get_agent()

    ctx = dict(context or {})
    ctx["store_id"] = store_id
    result = await agent.analyze(query=query, context=ctx)

    return {
        "success": _ok(result),
        "data": result,
        "message": _message(result, "分析完成"),
        "timestamp": datetime.now().isoformat(),
    }


async def stream_chat(message: str, store_id: Optional[str] = None):
    """流式对话入口（返回逐 token 异步迭代器）"""
    agent = _get_agent()
    async for chunk in agent.stream_chat(message, {"store_id": store_id}):
        yield chunk


# ==================== Service 类（统一入口）====================

class CompetitorIntelService:
    """竞品情报监控服务（统一命名空间，便于与其他模块风格对齐）"""

    monitor_competitor = staticmethod(monitor_competitor)
    track_batch_asins = staticmethod(track_batch_asins)
    analyze_market_share = staticmethod(analyze_market_share)
    analyze_pricing_strategy = staticmethod(analyze_pricing_strategy)
    analyze_competitor_reviews = staticmethod(analyze_competitor_reviews)
    detect_intruders = staticmethod(detect_intruders)
    analyze_buy_box = staticmethod(analyze_buy_box)
    compare_competitors = staticmethod(compare_competitors)
    general_analysis = staticmethod(general_analysis)
    stream_chat = staticmethod(stream_chat)

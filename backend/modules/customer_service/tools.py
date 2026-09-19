"""
智能客服模块 → 主 Agent 工具注册表

把 CustomerServiceService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 listing_tools.py 一致）：
- 只包「语义明确」的细粒度方法（FAQ 搜索 / 创建工单 / 情感分析 / 对话摘要），
  **不包** `chat` / `stream_chat` / `track_order` 这类走 `agent.invoke` 粗粒度入口
  （内部会再跑 _classify_intent，与主 Agent 判断冲突）。
- 参数用扁平字段，工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool

from .service import CustomerServiceService
from .schemas import (
    FAQSearchRequest,
    TicketCreateRequest,
    SentimentAnalysisRequest,
)

_service = CustomerServiceService()


def _dump(resp) -> str:
    """统一序列化：dict 直接 dump，Pydantic 走 model_dump。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


async def _search_faq_tool(
    query: str,
    limit: int = 5,
) -> str:
    """搜索客服知识库（FAQ），返回匹配的问题与答案。

    Args:
        query: 搜索关键词（必填）。
        limit: 返回数量上限（默认 5）。
    """
    req = FAQSearchRequest(query=query, limit=limit)
    resp = await _service.search_faq(req)
    return _dump(resp)


async def _create_ticket_tool(
    store_id: str,
    subject: str,
    description: str,
    category: str = "general",
    order_id: Optional[str] = None,
    priority: Optional[str] = None,
    customer_id: str = "",
) -> str:
    """创建客服工单（**落库**到 cs_tickets），返回工单号与预计响应时间。

    Args:
        store_id: 店铺 ID（**由系统注入**，LLM 不得自行指定）——工单必须有租户维度，
            否则 `cs_tickets.shop_id` 的外键会把写入拒掉。
        subject: 工单标题（必填，至少 2 字）。
        description: 问题描述（必填，至少 10 字）。
        category: 分类：售后/物流/质量/投诉/咨询/支付/订单（默认 general）。
        order_id: 关联订单号（可选）。
        priority: 优先级：low/medium/high/urgent（可选）。
        customer_id: 客户 ID（可选）。
    """
    req = TicketCreateRequest(
        subject=subject,
        description=description,
        category=category,
        order_id=order_id,
        priority=priority,
        customer_id=customer_id,
    )
    resp = await _service.create_ticket(req, store_id)
    return _dump(resp)


async def _analyze_sentiment_tool(text: str) -> str:
    """分析一段文本的情感倾向（正面/负面/中性），返回情感标签与置信度。

    Args:
        text: 待分析文本（必填）。
    """
    req = SentimentAnalysisRequest(text=text)
    resp = await _service.analyze_sentiment(req)
    return _dump(resp)


async def _get_conversation_summary_tool(conversation_id: str) -> str:
    """获取某段客服对话的摘要（用于复盘或交接）。

    Args:
        conversation_id: 会话 ID（必填）。
    """
    resp = await _service.get_conversation_summary(conversation_id)
    if resp is None:
        return json.dumps({"found": False, "message": "未找到该会话的摘要"}, ensure_ascii=False)
    return _dump(resp)


# ====== 工具注册表 ======

customer_service_tools = [
    StructuredTool.from_function(
        coroutine=_search_faq_tool,
        name="search_faq",
        description=(
            "搜索客服知识库（FAQ），返回匹配的问题与标准答案。"
            "当用户想查常见问题/找话术/搜知识库答案时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_create_ticket_tool,
        name="create_ticket",
        description=(
            "创建客服工单，返回工单号与预计响应时间。"
            "当用户想创建工单/记录客户问题/建单时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_sentiment_tool,
        name="analyze_sentiment",
        description=(
            "分析文本情感倾向（正面/负面/中性），返回情感标签与置信度。"
            "当用户想分析评论情感/看客户情绪/判断是好评还是差评时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_get_conversation_summary_tool,
        name="get_conversation_summary",
        description=(
            "获取某段客服对话的摘要。"
            "当用户想总结对话/看会话摘要/复盘客服时使用。"
        ),
    ),
]

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
from ai_infra.tools.side_effects import READ_ONLY_METADATA, SIDE_EFFECT_METADATA

from .service import CustomerServiceService
from .schemas import (
    FAQSearchRequest,
    TicketCreateRequest,
    SentimentAnalysisRequest,
)
# ★ 第 283 轮：客服从此**有订单 / 物流 / 差评可取**。
#   此前本模块 4 个工具全是「话术 + 建单」，而 `cs-refund-playbook` 技能
#   的第 0 步却写着「按证据判断责任归属，引用订单/物流证据」——
#   要求存在、取数手段不存在，于是那条要求只能靠模型即兴发挥。
#   现在把 trade 域的 5 个工具挂进来，要求才第一次有可能被满足。
from modules.trade import trade_tools

_service = CustomerServiceService()


def _shop_id():
    """从请求级 ContextVar 取当前店铺（归属只能由服务端注入）。

    ★ 第 204 轮修复：`create_ticket` 改造前把 `store_id` 当**工具形参**，等于让
      LLM 自报租户 —— 而它的 docstring 却写着「由系统注入，LLM 不得自行指定」，
      是典型的**注释承诺型假门禁**。现在改从 agent 的 ContextVar 取，写入点是
      `CustomerServiceAgent._route_via_tools()`。

    ★ 取不到（None）时**不兜底**：service 的 `require_shop_context` 会抛
      `MissingShopContext` ⇒ 拒绝写入（fail-closed），而不是写一条没有租户的行。

    ★ 延迟导入：`tools` 被 agent 的 `_build_router()` 导入，模块级反向 import
      会形成 `agent → tools → agent` 环。
    """
    from .agent_cs import _current_shop_id
    return _current_shop_id.get()


# 把**本模块**的店铺上下文注入给 trade 工具层：归属只有一个来源，
# trade 工具不接受 shop_id 形参（见 modules/trade/tools.py 文件头）。
from modules.trade import set_shop_id_resolver  # noqa: E402

set_shop_id_resolver(_shop_id)


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

    ★ 第 326 轮修复：改前调用 `search_faq(req)` **漏传 `store_id`** ——
      service 层按店铺隔离话术，缺了它 `faq_source` 直接抛 `PermissionError`，
      而工具层不捕获 ⇒ 本工具虽挂在客服 Agent 上（`agent_cs.py` 的
      `tools=customer_service_tools`），但**每次调用都失败**。
      同文件 `create_ticket` 用的是 `_shop_id()`（第 204 轮范式），
      FAQ 这条属**纯遗漏**，不是有意差异。

    Args:
        query: 搜索关键词（必填）。
        limit: 返回数量上限（默认 5）。
    """
    req = FAQSearchRequest(query=query, limit=limit)
    # 归属只从请求级 ContextVar 取 —— 与 create_ticket 同口径
    resp = await _service.search_faq(req, _shop_id())
    return _dump(resp)


async def _create_ticket_tool(
    subject: str,
    description: str,
    category: str = "general",
    order_id: Optional[str] = None,
    priority: Optional[str] = None,
    customer_id: str = "",
) -> str:
    """创建客服工单（**落库**到 cs_tickets），返回工单号与预计响应时间。

    ★ 第 204 轮：`store_id` 已从工具形参**删除**。原实现把它写成普通形参，
      而 docstring 写着「由系统注入，LLM 不得自行指定」—— 注释承诺、实现没做，
      等于把租户边界交给模型。现在归属经 `_shop_id()` 从请求级 ContextVar 取。

    Args:
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
    resp = await _service.create_ticket(req, _shop_id())
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
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_create_ticket_tool,
        name="create_ticket",
        description=(
            "创建客服工单，返回工单号与预计响应时间。"
            "当用户想创建工单/记录客户问题/建单时使用。"
        ),
        metadata=SIDE_EFFECT_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_analyze_sentiment_tool,
        name="analyze_sentiment",
        description=(
            "分析文本情感倾向（正面/负面/中性），返回情感标签与置信度。"
            "当用户想分析评论情感/看客户情绪/判断是好评还是差评时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_get_conversation_summary_tool,
        name="get_conversation_summary",
        description=(
            "获取某段客服对话的摘要。"
            "当用户想总结对话/看会话摘要/复盘客服时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    # ====== trade 域工具（订单 / 物流 / 差评）—— 见文件头说明 ======
    *trade_tools,
]

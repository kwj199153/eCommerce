"""共享内核：模块级常量 / 数据模型 / 归属 ContextVar / 订单状态标签。

本层不 import 包内其它子模块（唯一叶子），六个 mixin 都从它取。

本文件由 `modules/customer_service/agent_cs.py` 拆分而来（第 356 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_agent_cs.py (第 356 轮)

import asyncio
import json
import re
from contextvars import ContextVar
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from core.logger import get_logger

# ★ 历史缺陷（已修）：3 处 logger.warning 曾在 except 里引用**未定义**的
#   `logger`，其中 `stream_chat failed` 那条最严重 —— 流式失败后本该回退到
#   `self.invoke(query)` 再答一次，NameError 会让回退根本不执行。
#   现已在下一行定义模块级 logger，修复即闭合。
#   ⚠️ 插值口径：本 logger 来自 loguru（`get_logger`），按 `str.format` 插值 ——
#      只能写 f-string / `{}`。写 `%s` **不报错**，参数被静默丢弃、
#      日志原样打出 "%s"（实测：`logger.warning("a=%s", 1)` → `a=%s`）。
#      标准库 `logging.getLogger(__name__)` 才用 `%s`。
logger = get_logger("customer_service.agent")

#: 请求级店铺归属（第 204 轮）。
#:
#: ★★★ `create_ticket` 必须带租户维度（`cs_tickets.shop_id` 有外键），而工具入参
#:   由 LLM 生成 —— 归属只能由**服务端**注入。改造前 `_create_ticket_tool` 把它
#:   写成普通形参，docstring 却写着「由系统注入，LLM 不得自行指定」：
#:   **注释承诺型假门禁**，模型照填不误。
#:
#: ★ 唯一写入点 = `_route_via_tools()`（工具环路的唯一入口），且必须在工具被调用
#:   之前 —— 否则第一次 `create_ticket` 会带着 `store_id=None` 落库，
#:   被 service 的 `require_shop_context` 拒掉（fail-closed，不会写脏行）。
_current_shop_id: ContextVar[Optional[str]] = ContextVar(
    "customer_service_current_shop_id", default=None
)


from pydantic import BaseModel, Field

# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.customer_service import prompts as _prompts  # noqa: F401


from ai_infra.sse import StreamDigest, progress


# 结构化意图 → 阶段进度文案（stream_chat 在耗时处理前发给前端，避免空转）
_INTENT_PROGRESS = {
    "order_tracking": "正在查询订单状态…",
    "ticket_create": "正在创建工单…",
    "escalation": "正在转接人工并整理上下文…",
}


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型


# ---- FAQ 相关 ----

class FAQItem(BaseModel):
    """FAQ 条目"""
    id: str
    question: str
    answer: str
    category: str  # 物流/退换货/支付/账户/产品/其他
    keywords: List[str] = []
    priority: int = 0  # 显示优先级
    views: int = 0  # 浏览次数（表内无对应列，恒 0；不拿 usage_count 冒充实测）
    helpful_count: int = 0  # 有用反馈数
    usage_count: int = 0  # 被客服命中次数（来自 knowledge_faqs.usage_count）


class FAQMatchResult(BaseModel):
    """FAQ 匹配结果"""
    query: str
    matches: List[FAQItem]
    best_match: Optional[FAQItem] = None
    confidence: float = 0.0  # 匹配置信度 0-1
    suggested_questions: List[str] = []  # 相关问题建议


# ---- 工单相关 ----

class TicketInfo(BaseModel):
    """工单信息"""
    ticket_id: str
    subject: str
    description: str
    category: str  # 售后/物流/质量/投诉/咨询
    priority: str  # low/medium/high/urgent
    status: str  # open/in_progress/resolved/closed
    customer_id: str = ""
    order_id: Optional[str] = None
    created_at: str
    assigned_to: str = ""
    sla_deadline: Optional[str] = None
    tags: List[str] = []


class TicketCreateResult(BaseModel):
    """工单创建结果"""
    success: bool
    ticket: Optional[TicketInfo] = None
    estimated_response_time: str = ""
    auto_replies: List[str] = []  # 自动回复建议


# ---- 对话上下文 ----

class ConversationTurn(BaseModel):
    """对话轮次"""
    role: str  # user/assistant/system
    content: str
    timestamp: str
    intent: Optional[str] = None
    sentiment: Optional[str] = None  # positive/neutral/negative/angry
    entities: Dict[str, str] = {}  # 提取的实体（订单号、ASIN等）


class ConversationContext(BaseModel):
    """对话上下文"""
    conversation_id: str
    turns: List[ConversationTurn] = []
    customer_info: Dict[str, str] = {}  # 客户信息缓存
    current_topic: str = ""  # 当前话题
    resolved_topics: List[str] = []  # 已解决问题
    escalation_triggered: bool = False  # 是否触发升级
    turn_count: int = 0


# ---- 情感分析结果 ----

class SentimentAnalysis(BaseModel):
    """情感分析"""
    sentiment: str  # positive/neutral/negative/angry
    confidence: float  # 0-1
    intensity: float  # 0-1 情感强度
    key_emotions: List[str] = []  # 关键情绪词
    should_escalate: bool = False  # 是否需要升级人工
    escalate_reason: str = ""


# ====== 话术从哪里来 ======
#
# ★ 第 286 轮：客服话术的**唯一真源**是 `knowledge_faqs` 表，经
#   `modules/customer_service/faq_source.load_faq_items(shop_id)` 按店铺读取。
#
#   此前这里是一份 12 条的内存常量 `MOCK_FAQ_DB`：改不动、不落库、重启即回原样；
#   而运营在【资料库 → 业务话术库】里维护的那批真数据**从来没被检索到**
#   （审查见 docs/cs-data-source-audit-r285.md 第 2.3 节：名字叫
#   `search_knowledge_base`，检索源却是内存 12 条）。
#
#   那 12 条内容已逐字迁到 `cs_faq_seed.json`，由 `faq_source.seed_cs_faqs()`
#   灌进表 —— 数据还在，只是从「锁在源码里」变成「摆在库里、可编辑、可删」。
#
# ★ 本文件**不再**有任何内存话术常量。取不到就是取不到，如实报错，
#   绝不静默回退到一份假数据（本仓对静默降级的一贯立场）。



#: 订单状态 → 中文标签（**客服回复**用）
#:
#: ★ 为什么这张表放在客服这一层，而不是 trade 域：trade 的 `order_status` 是
#:   **平台无关**的英文码（将来接 Shopee / 独立站也沿用同一套码），把它翻成
#:   消费者能看懂的话是「展示层」的事 —— 放进 trade 就等于让数据模型去承担
#:   某一处 UI 的措辞。同理，`CAUSE_LABELS`（归因中文名）也住在 trade，因为
#:   那是业务口径；而「已签收」这种说法只服务客服话术。
_ORDER_STATUS_LABELS: dict = {
    "pending": "待处理",
    "unshipped": "未发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "cancelled": "已取消",
}

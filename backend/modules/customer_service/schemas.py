"""
智能客服模块 - 数据模型 (Schemas)

定义请求/响应的数据结构
"""

from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, Field

# ★ 「本次请求的作用对象」的形状定义在机制层（`ai_infra/context_target.py`）。
#   第 298 轮起四条链路（选品 / Listing / AIGC / 客服）共用同一个形状 ——
#   各写一份的下场是「少一个字段」的那一份不报任何错，只是静默拿不到对象。
from ai_infra.context_target import ContextTargetPayload


# ====== 请求模型 ======

class ChatRequest(BaseModel):
    """客服对话请求"""
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    conversation_id: Optional[str] = Field(None, description="会话 ID（多轮对话）")
    context: Optional[Dict[str, Any]] = Field(None, description="附加上下文")
    customer_id: Optional[str] = Field(None, description="客户 ID")

    # ★ 点名通道（第 188 轮）：用户点名本次对话要用的技能名（可选）。
    #   留空 ⇒ 只注入技能目录，仍由模型自己判断用哪条（渐进披露的原路径）。
    #   ★ 归属校验不在这里：技能名由服务端在 `read_skill_text` 里按
    #     身份 + 启用 + 对本 Agent 启用 三重过滤，请求体只负责**传递名字**。
    skill: Optional[str] = Field(default=None, description="本次对话指定使用的技能名（可选）")

    # ★ 本次请求的「作用对象」（第 298 轮）。与 `skill` 是**一对**：
    #   `skill` 说「这次用哪条技能」，它说「这次冲着哪个对象来的」。
    #   本 Agent 的差评应对链路此前只能靠 `get_customer_review_context(review_id)`
    #   拿对象，而 `review_id` 只能从**用户消息文本或会话历史**里来 ——
    #   用户已经在台账里点开了某条差评、进对话只说「帮我处理这条」时，
    #   模型只能从历史里挑一条顶上（第 250 轮那个洞在客服线上的同一形状）。
    #   ★ 传 `null` 与**不传**含义不同（明确没有 vs 客户端未参与），
    #     判别由 `model_fields_set` 承担，本字段故意不给默认值。
    #   ★ 本 Agent **只注入、不拒答**（与选品不同）：FAQ 检索 / 情感分析 /
    #     订单追踪类技能本来就不针对具体差评，挂 fail-closed 会把一次正常
    #     提问变成一句拒答（误伤）。
    context_target: Optional[ContextTargetPayload] = Field(
        default=None, description="本次请求的作用对象（三态：字段不出现 / null / {...}）"
    )


class FAQSearchRequest(BaseModel):
    """FAQ 搜索请求"""
    query: str = Field(..., min_length=1, description="搜索关键词")
    limit: int = Field(5, ge=1, le=20, description="返回数量上限")
    category: Optional[str] = Field(None, description="限定类别")


class TicketCreateRequest(BaseModel):
    """创建工单请求"""
    subject: str = Field(..., min_length=2, max_length=200, description="工单标题")
    description: str = Field(..., min_length=10, max_length=5000, description="问题描述")
    category: str = Field("general", description="分类：售后/物流/质量/投诉/咨询/支付/订单")
    order_id: Optional[str] = Field(None, description="关联订单号")
    priority: Optional[str] = Field(None, description="优先级：low/medium/high/urgent")
    customer_id: str = Field("", description="客户 ID")
    attachments: List[str] = Field(default_factory=list, description="附件 URL 列表")


class OrderTrackRequest(BaseModel):
    """订单追踪请求"""
    order_id: Optional[str] = Field(None, description="订单号")
    email: Optional[str] = Field(None, description="下单邮箱")
    phone_last4: Optional[str] = Field(None, description="手机后四位")


class SentimentAnalysisRequest(BaseModel):
    """情感分析请求"""
    text: str = Field(..., min_length=1, description="待分析文本")


# ====== 响应模型 ======

class ChatResponse(BaseModel):
    """客服对话响应"""
    reply: str  # 回复内容
    conversation_id: str  # 会话 ID
    intent: str  # 识别的意图
    sentiment: Optional[Dict[str, Any]] = None  # 情感分析结果
    data: Optional[Any] = None  # 结构化数据（FAQ 匹配、订单信息等）
    display_type: str = "text"  # 展示类型
    suggested_actions: List[str] = Field(default_factory=list)  # 建议操作
    should_escalate: bool = False  # 是否需要升级人工


class FAQSearchResponse(BaseModel):
    """FAQ 搜索响应"""
    query: str
    results: List[Dict[str, Any]]
    total: int
    best_match: Optional[Dict[str, Any]] = None


class TicketResponse(BaseModel):
    """工单响应"""
    success: bool
    ticket: Optional[Dict[str, Any]] = None
    estimated_response_time: str = ""
    auto_replies: List[str] = Field(default_factory=list)
    message: str = ""


class OrderTrackResponse(BaseModel):
    """订单追踪响应"""
    found: bool
    order: Optional[Dict[str, Any]] = None
    message: str = ""


class SentimentResponse(BaseModel):
    """情感分析响应"""
    sentiment: str  # positive/neutral/negative/angry
    confidence: float  # 0-1
    intensity: float  # 0-1
    key_emotions: List[str] = []
    should_escalate: bool = False
    escalate_reason: str = ""


class ConversationSummaryResponse(BaseModel):
    """对话摘要响应"""
    conversation_id: str
    turn_count: int
    current_topic: str
    resolved_topics: List[str] = []
    escalation_triggered: bool = False


# ====== 包装模型 ======

class ApiResponse(BaseModel):
    """通用成功响应"""
    success: bool = True
    data: Any
    message: str = "操作成功"


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error: str
    detail: Optional[str] = None
    code: int = 400


# ====== 能力描述 ======

class CapabilityResponse(BaseModel):
    """Agent 能力描述"""
    name: str
    role: str
    capabilities: List[Dict[str, str]]
    faq_count: int
    categories: List[str]

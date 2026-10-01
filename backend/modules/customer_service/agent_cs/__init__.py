"""
智能客服 Agent (Customer Service Agent - RAG + LLM)

跨境电商 AI 客服专家，基于 RAG 架构实现知识库问答。
已集成 DashScope Qwen LLM + SKLearnVectorStore 混合检索。

功能模块：
1. FAQ 智能匹配 - RAG 向量检索 + 关键词混合 + LLM 生成自然回复
2. 多轮对话上下文 - 订单追踪、退换货、物流查询
3. 工单自动分类 - 问题类型识别 + 优先级判断
4. 情感分析 - 客户情绪检测 + 升级转人工决策
5. 常见问题自动回复 - 高频问题模板匹配
6. 知识库管理 - FAQ 导入/更新/搜索

架构升级：
- Phase 5: 纯关键词匹配模拟响应
- Phase 8: 接入真实 LLM (DashScope Qwen) + RAG 混合检索引擎
"""
# @generated-by: split_agent_cs.py (第 356 轮)

# ============================================================
# ★ 本包是 `modules.customer_service.agent_cs` 的**对外唯一契约面**。
#   拆分前它是一个 1992 行的单文件；拆分后按子域分成 6 个 mixin + 1 个共享内核，
#   但**对外名字集合一字未变**：
#     · `modules/customer_service/__init__.py`：`from .agent_cs import CustomerServiceAgent`
#     · `service.py`：`from .agent_cs import CustomerServiceAgent, AgentResponse`
#     · `tools.py`：`from .agent_cs import _current_shop_id`
#       （re-export 复制的是**同一个 ContextVar 对象**，工具层注入仍生效）
#   六个 mixin 只提供方法，`BaseAgent` 仍是**最后一个直接基类** ——
#   `MixinCore.__init__` 的 `super().__init__()` 与拆分前逐字同义。
# ============================================================

from ._base import (
    logger,
    _current_shop_id,
    _INTENT_PROGRESS,
    AgentResponse,
    FAQItem,
    FAQMatchResult,
    TicketInfo,
    TicketCreateResult,
    ConversationTurn,
    ConversationContext,
    SentimentAnalysis,
    _ORDER_STATUS_LABELS,
)
from .core import MixinCore
from .faq import MixinFaq
from .orders import MixinOrders
from .aftersale import MixinAftersale
from .tickets import MixinTickets
from .conversation import MixinConversation

from ai_infra.base_agent import BaseAgent


# ====== 智能客服 Agent 主类 ======

class CustomerServiceAgent(
    MixinCore,
    MixinFaq,
    MixinOrders,
    MixinAftersale,
    MixinTickets,
    MixinConversation,
    BaseAgent,
):
    """
    跨境电商 AI 智能客服 Agent

    基于 RAG 架构的知识库问答系统，
    支持多轮对话、情感分析、工单管理。

    升级特性：
    - ✅ DashScope Qwen LLM 真实调用
    - ✅ SKLearnVectorStore + TF-IDF 混合检索
    - ✅ 自动降级（LLM 不可用时使用模拟响应）
    """


#: 拆分前后**逐个对账**用的名字清单（校验脚本读它）。
__all__ = [
    "CustomerServiceAgent",
    "logger",
    "_current_shop_id",
    "_INTENT_PROGRESS",
    "AgentResponse",
    "FAQItem",
    "FAQMatchResult",
    "TicketInfo",
    "TicketCreateResult",
    "ConversationTurn",
    "ConversationContext",
    "SentimentAnalysis",
    "_ORDER_STATUS_LABELS",
]

"""
会话持久化 ORM 模型（决策层 B：跨会话记忆）

为店秘书（主 Agent）提供跨会话对话记忆。前端刷新 / 换设备后，
凭 sessionId 从 DB 恢复历史消息，让 LLM 感知跨会话上下文。

设计：
- conversation 表：一次连续对话（一个 sessionId）
- conversation_message 表：该会话的消息明细（按序追加）
- 与 LangGraph checkpoint（决策层 C）互补：checkpoint 存图的中间状态
  （工具调用链），本表存面向用户的可读消息历史（渲染 + 注入 LLM）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Text, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ConversationRecord(Base):
    """会话表（一个 sessionId = 一次连续对话）"""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # session_xxx / uuid
    # 归属：用户 + 店铺（沿用 stores_store 的 owner_id 语义）
    owner_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    shop_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # 当前对话的 Agent（如 secretary / product-research），用于按 Agent 过滤
    agent_id: Mapped[str] = mapped_column(String(32), default="secretary")
    title: Mapped[str] = mapped_column(String(200), default="新对话")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConversationMessageRecord(Base):
    """会话消息表（按序追加，role: user / assistant）"""
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conv_msg_conversation_seq", "conversation_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # msg_xxx / uuid
    conversation_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 会话内序号
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

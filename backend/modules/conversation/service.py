"""会话持久化服务层（决策层 B）"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, update

from core.database import get_async_session

from .db_model import ConversationRecord, ConversationMessageRecord


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


async def create_conversation(
    agent_id: str = "secretary",
    owner_id: Optional[str] = None,
    shop_id: Optional[str] = None,
    title: str = "新对话",
) -> str:
    """新建会话，返回 sessionId。"""
    conv_id = _new_id("session")
    async with get_async_session() as session:
        session.add(ConversationRecord(
            id=conv_id,
            agent_id=agent_id,
            owner_id=owner_id,
            shop_id=shop_id,
            title=title,
        ))
    return conv_id


async def append_message(conversation_id: str, role: str, content: str) -> None:
    """追加一条消息（自动递增 seq）。"""
    async with get_async_session() as session:
        # 计算下一个 seq
        max_seq = await session.execute(
            select(func.coalesce(func.max(ConversationMessageRecord.seq), 0))
            .where(ConversationMessageRecord.conversation_id == conversation_id)
        )
        next_seq = int(max_seq.scalar()) + 1
        session.add(ConversationMessageRecord(
            id=_new_id("msg"),
            conversation_id=conversation_id,
            seq=next_seq,
            role=role,
            content=content,
        ))
        # 更新会话的 updated_at
        await session.execute(
            update(ConversationRecord)
            .where(ConversationRecord.id == conversation_id)
            .values(updated_at=datetime.utcnow())
        )


async def get_history(
    conversation_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取会话历史（最近的 limit 条，按 seq 升序返回）。"""
    async with get_async_session() as session:
        rows = await session.execute(
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.conversation_id == conversation_id)
            .order_by(ConversationMessageRecord.seq.desc())
            .limit(limit)
        )
        msgs = rows.scalars().all()
    # 反转为时间升序
    msgs = list(reversed(msgs))
    return [{"role": m.role, "content": m.content} for m in msgs]


async def conversation_exists(conversation_id: str) -> bool:
    """会话是否存在。"""
    async with get_async_session() as session:
        row = await session.execute(
            select(ConversationRecord.id).where(ConversationRecord.id == conversation_id)
        )
        return row.scalar_one_or_none() is not None

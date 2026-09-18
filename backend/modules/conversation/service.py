"""会话持久化服务层（决策层 B）

★ P0-1（2026-09-18）：**本模块所有对外函数都强制带 `user`**。

修复前的形态是「谁拿到 session_id，谁就能读写这个会话」——
    get_history(conversation_id, limit)           # 只问"存在吗"，不问"是你的吗"
    append_message(conversation_id, role, ...)    # 同上
而业务通道有**两条**，且两条都真可被利用：
    1. `modules/conversation/router.py` 的三个端点（当时无任何鉴权依赖）；
    2. `POST /api/v1/orchestrator/chat` —— 客户端给的 `session_id` 被直接拿来
       读历史、注入 LLM，然后把本轮两条消息**写回**。这条前端在用。

实测（生产模式 `auth_required=True`，B 持自己的有效 token、传 A 的 session_id）：
    GET  .../history  → 200 + A 的完整对话内容
    POST .../messages → 200，且 A 侧会话真的多出两条消息（污染）
    POST /orchestrator/chat → 同上，且 A 的历史被当作上下文喂给了 LLM

⇒ 现在的形状：归属判定只有一处（`get_owned_conversation`），其余函数都从它进；
  且 `user` 是**首参必填** —— 签名本身就是门禁，忘了判权写不出可运行的调用点。
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, func, update

from core.auth.accounts import can_access_conversation
from core.database import get_async_session
from core.identity.models import User

from .db_model import ConversationRecord, ConversationMessageRecord


#: 会话「不存在」与「不属于当前用户」的统一文案。
#:
#: ★ 两种情况**必须**同一句话：分开写等于告诉攻击者"这个 session_id 是真实的，
#:   只是不归你" ⇒ 可以拿来枚举有效 ID。与 `accounts.ensure_can_access_store`
#:   统一 403（而非 404）是同一条理由。
#: ★ 也**不回显**调用方传入的 ID —— 那是把用户输入原样反射进响应与日志。
NO_SESSION_DETAIL = "会话不存在或无权访问"


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


async def create_conversation(
    *,
    agent_id: str = "secretary",
    owner_id: Optional[str],
    shop_id: Optional[str] = None,
    title: str = "新对话",
) -> str:
    """
    新建会话，返回 sessionId。

    ★ `owner_id` 刻意**没有默认值**，且因 `*` 而成为**关键字参数**：
      新写一个调用点忘了传，得到的是 `TypeError`（在任何测试里都会炸），
      而不是静默落一条**无主会话** —— 后者对任何人都不可访问，用户看到的
      只是"刷新后对话丢了"，没有任何报错指向真正的原因。

    ★ 归属**只能由服务端注入**：路由从 `current_user` 取，店秘书从同一个
      `current_user` 取。它**不在任何请求体里** —— 修复前
      `ConversationCreateRequest.owner_id` 是客户端自报字段，
      实测能把自己的会话挂到别人名下（落库 `owner_id=<受害者的 id>`）。
    """
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


# ====== 归属判定（唯一入口）======

async def get_owned_conversation(
    user: Optional[User],
    conversation_id: str,
) -> Optional[ConversationRecord]:
    """
    取**属于当前用户**的会话；不存在 **或** 无权时一律返回 `None`。

    ★ 这是本模块**唯一**的归属判定入口 —— 其余函数全部从它进。

    ★ 返回 `None` 而不抛异常：店秘书需要"没有可用会话就新建"的降级行为，
      而它不该、也不需要区分"没建过"与"不归你"（对用户是同一件事）。

    ★ 无主会话（`owner_id IS NULL`）对**任何有身份的人**都返回 `None`
      ⇒ fail-closed。判据见 `core.auth.accounts.can_access_conversation`。
    """
    async with get_async_session() as session:
        row = await session.execute(
            select(ConversationRecord).where(ConversationRecord.id == conversation_id)
        )
        conv = row.scalar_one_or_none()

    if conv is None:
        return None
    if not can_access_conversation(user, conv):
        return None
    return conv


async def require_owned_conversation(
    user: Optional[User],
    conversation_id: str,
) -> ConversationRecord:
    """同 `get_owned_conversation`，但不可访问时抛 **404**（HTTP 端点用）。"""
    conv = await get_owned_conversation(user, conversation_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NO_SESSION_DETAIL,
        )
    return conv


# ====== 消息读写 ======

async def _load_history(conversation_id: str, limit: int = 20) -> list[dict]:
    """
    直读消息（**不判归属**）。

    ★ 私有，且刻意不导出：只有**已经持有已授权会话**的调用方才准用
      （`history_of` / `get_history`）。新增调用点请走带 `user` 的公开函数。
    """
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


async def history_of(conv: ConversationRecord, limit: int = 20) -> list[dict]:
    """
    读取**已授权**会话的消息。

    ★ 调用方必须已经通过 `get_owned_conversation` 拿到 `conv`。
      为什么要这个"不再判一次"的变体：店秘书在**同一次请求里**既要判归属
      （决定复用还是新建 session_id）又要读历史；用 `get_history(user, id)`
      会把归属查询做两遍，且两次之间存在"会话刚被删"的竞态 ——
      第二次会抛 404，而那条 404 在一个已经判过权的路径上是纯粹的噪声。
      传 record 进来就没有这个窗口：判定与读取锚定在**同一个**快照上。
    """
    return await _load_history(conv.id, limit=limit)


async def get_history(
    user: Optional[User],
    conversation_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取会话历史（最近的 limit 条，按 seq 升序返回）。★ 先判权，再读。"""
    await require_owned_conversation(user, conversation_id)
    return await _load_history(conversation_id, limit=limit)


async def append_message(
    user: Optional[User],
    conversation_id: str,
    role: str,
    content: str,
) -> None:
    """追加一条消息（自动递增 seq）。★ 先判权，再写。"""
    await require_owned_conversation(user, conversation_id)

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

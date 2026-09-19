"""Agent 会话级状态的持久层（第 145 轮批 C1）。

分工
----
  · `ai_infra/session_state.py` —— 与存储无关的容器机制（脏追踪 + 有界缓存），
    它不认识数据库；
  · **本模块** —— 「把那个容器落到 PG / 从 PG 读回来」；
  · 业务 Agent —— 入口调 `hydrate_state()`、出口调 `persist_state()`。

与同包另外两个存储的分工见 `db_model.AgentSessionStateRecord` 的 docstring。

三条被刻意选定的方向（都是"两类代价不对称，选安全那一侧"）
----------------------------------------------------------
1. **落盘失败绝不让本轮回复失败**。落盘发生在「回答已经生成完」的出口 ——
   在那里抛异常等于把一次成功的回答换成 500：用户丢的是**回答**，
   而不是状态。所以这里吞掉异常并记 warning，且**不**清脏标记（下次还会重试）。
2. **读取失败同理**：读不到就当作「这个会话还没有状态」，退回空容器。
   把一次可用的对话变成错误页，代价远大于"少记一轮槽位"。
3. **脏容器不被库里的旧值覆盖** —— 见 `hydrate_state()`。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ai_infra.session_state import SessionState
from core.database import get_async_session

from .db_model import AgentSessionStateRecord

logger = logging.getLogger(__name__)

#: upsert 的冲突目标（与 `db_model` 里的 UniqueConstraint 同名）。
#: ★ 写成常量而不是在两处各写一遍字符串字面量：改名时漏一处不会报错，
#:   只会在**第一次落盘**时抛「没有匹配的约束」，而那时离改名已经很久了。
_UPSERT_CONSTRAINT = "uq_agent_session_state_thread_key"


def _json_safe(value: Any) -> Any:
    """把值收敛成**一定能被 JSON 序列化**的形态（不认识的类型 → `str`）。

    ★ 为什么必须有：`payload` 直接进 `JSON` 列。若某个字段是 datetime /
      numpy 标量 / 自定义对象，序列化会**在落盘时抛** —— 而落盘在出口，
      那里抛异常等于把一次成功的回答换成 500。
    ★ 用 `default=str` 降级而不是拒绝：这些值的用途是「下一轮回读给模型看」
      与「供指代解析匹配」，字符串化之后语义仍然可用。
    ★ 返回值走一遍 `loads` 是**故意的**：只 `dumps` 的话，numpy 标量等方式下
      仍然是非原生类型，最后仍可能在真正写库时炸；往返一次就拿到了纯
      JSON 类型（dict / list / str / int / float / bool / None）。
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


async def load_states(
    *, owner_id: Optional[str], thread_id: Optional[str]
) -> dict:
    """读该会话的全部状态键（`state_key -> payload`）。"""
    if not (owner_id and thread_id):
        return {}
    async with get_async_session() as session:
        rows = await session.execute(
            select(
                AgentSessionStateRecord.state_key,
                AgentSessionStateRecord.payload,
            ).where(
                AgentSessionStateRecord.thread_id == thread_id,
                # ★★ 归属是**查询条件**的一部分，不是返回值里的一件装饰品。
                #    只按 thread_id 查等于「谁拿到会话键谁就能读」——
                #    而 thread_id 里本来就含有 user_id，把它同时当过滤条件，
                #    两道口径就都守住了。
                AgentSessionStateRecord.owner_id == owner_id,
            )
        )
        return {key: payload for key, payload in rows.all()}


async def save_states(
    *,
    owner_id: Optional[str],
    thread_id: Optional[str],
    session_id: Optional[str],
    writes: Mapping[str, Any],
    deletes: Iterable[str] = (),
) -> None:
    """增量落盘：`writes` 逐键 upsert，`deletes` 逐键删除。"""
    if not (owner_id and thread_id):
        return
    writes = dict(writes or {})
    deletes = tuple(deletes or ())
    if not writes and not deletes:
        return

    async with get_async_session() as session:
        for key, value in writes.items():
            stmt = pg_insert(AgentSessionStateRecord).values(
                id=f"sst_{uuid.uuid4().hex[:16]}",
                owner_id=owner_id,
                thread_id=thread_id,
                session_id=session_id or "",
                state_key=key,
                payload=_json_safe(value),
            )
            stmt = stmt.on_conflict_do_update(
                constraint=_UPSERT_CONSTRAINT,
                set_={
                    "payload": stmt.excluded.payload,
                    "session_id": stmt.excluded.session_id,
                    "updated_at": datetime.utcnow(),
                },
            )
            await session.execute(stmt)

        if deletes:
            await session.execute(
                delete(AgentSessionStateRecord).where(
                    AgentSessionStateRecord.thread_id == thread_id,
                    AgentSessionStateRecord.owner_id == owner_id,
                    AgentSessionStateRecord.state_key.in_(list(deletes)),
                )
            )


async def hydrate_state(
    state: SessionState,
    *,
    owner_id: Optional[str],
    thread_id: Optional[str],
) -> bool:
    """从 PG 读回该会话状态；返回是否真的读了。

    ★ **脏容器不被覆盖**：若这个容器里还有没落盘的改动（同一进程内并发的两次
      请求、或上一次落盘失败），库里的值一定**不比内存新**。此时覆盖等于丢掉
      用户刚补上的槽位。方向选「保留内存」—— 内存最差也只是"比库新一点"，
      而覆盖是确定性的数据丢失。
    """
    if not (owner_id and thread_id):
        return False
    if state.is_dirty:
        logger.warning(
            "会话状态容器仍有未落盘的改动，跳过 hydrate（保留内存态）：scope=%s",
            state.scope_id,
        )
        return False
    try:
        data = await load_states(owner_id=owner_id, thread_id=thread_id)
    except Exception as e:  # noqa: BLE001 —— 见模块 docstring 第 2 条
        logger.warning("会话状态读取失败，本轮按空状态继续：%s", e)
        return False
    state.reset(data)
    return True


async def persist_state(
    state: SessionState,
    *,
    owner_id: Optional[str],
    thread_id: Optional[str],
    session_id: Optional[str] = None,
) -> bool:
    """把容器里**未落盘的改动**写回 PG；返回是否写成功（无改动也算成功）。"""
    if not (owner_id and thread_id):
        return False
    writes = state.pending_writes()
    deletes = tuple(state.deleted_keys)
    if not writes and not deletes:
        return True

    try:
        await save_states(
            owner_id=owner_id,
            thread_id=thread_id,
            session_id=session_id,
            writes=writes,
            deletes=deletes,
        )
    except Exception as e:  # noqa: BLE001 —— 见模块 docstring 第 1 条
        logger.warning("会话状态落盘失败（本轮回复不受影响，下次会重试）：%s", e)
        return False

    # ★ 只清**本次真的写过**的那些键：`await` 期间可能有新改动进来，
    #   无差别清空会让那笔新改动永远不会被写出去（且不报错）。
    state.mark_persisted(keys=list(writes.keys()), deleted=deletes)
    return True

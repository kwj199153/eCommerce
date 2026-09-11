"""
LangGraph Checkpoint 生命周期管理

决策层 C：为店秘书（主 Agent）提供跨轮次 / 跨会话的对话记忆持久化。

技术要点：
- AsyncPostgresSaver 硬依赖 psycopg3，故使用独立的 `checkpoint_database_url`
  （postgresql:// 格式），与业务层 asyncpg 引擎（postgresql+asyncpg://）分离，
  二者连同一 PG 实例但走不同驱动。
- checkpointer 必须在 `compile(checkpointer=...)` 时绑定到图，不能随 ainvoke 的
  config 传入（LangGraph 语义），因此这里只负责「建表 + 提供单例实例」。
- thread_id = 会话 sessionId，业务层把 sessionId 传给 graph 的 configurable。

使用方式：
    from core.checkpoint import get_checkpointer, setup_checkpoint

    await setup_checkpoint()          # lifespan 启动时调用，建 checkpoint 表
    cp = get_checkpointer()           # 获取单例，传给 BaseAgent 构造
"""

import logging
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from core.config import config

logger = logging.getLogger(__name__)

# 单例 checkpointer（进程内共享）
_checkpointer: Optional[AsyncPostgresSaver] = None


async def setup_checkpoint() -> AsyncPostgresSaver:
    """
    初始化 checkpointer：创建 checkpoint 表并返回单例。

    幂等：`setup()` 内部使用 CREATE TABLE IF NOT EXISTS，可重复调用。
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    # AsyncPostgresSaver 接受 AsyncConnectionPool（pipe=None 时），
    # 用连接池管理多请求并发，比单连接直连更稳。
    # 关键：kwargs={'autocommit': True} —— setup() 迁移含 CREATE INDEX CONCURRENTLY，
    # 必须在 autocommit 连接下执行，否则报 ActiveSqlTransaction。
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=config.checkpoint_database_url,
        min_size=1,
        max_size=config.database_pool_size,
        kwargs={"autocommit": True},
    )
    await pool.open()
    _checkpointer = AsyncPostgresSaver(pool)
    await _checkpointer.setup()
    logger.info("✅ LangGraph Checkpoint 表已就绪（psycopg3）")
    return _checkpointer


def get_checkpointer() -> Optional[AsyncPostgresSaver]:
    """获取 checkpointer 单例（未初始化则返回 None）。"""
    return _checkpointer


async def close_checkpoint() -> None:
    """关闭 checkpointer 连接池。"""
    global _checkpointer
    if _checkpointer is not None:
        conn = _checkpointer.conn
        if isinstance(conn, AsyncConnectionPool):
            await conn.close()
        elif hasattr(conn, "close"):
            await conn.close()
        _checkpointer = None

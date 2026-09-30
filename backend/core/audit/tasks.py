"""审计保留期清理的 **Celery 接线**（第 328 轮）。

核（**删哪些行**）住在 `core/audit/retention.py`；本文件只做三件机制性的事：

  ① 注册任务名 —— beat 按**名字**投递，见 `core/redis.py::beat_schedule`；
  ② 提供这一次执行的事务边界（开会话 + commit）；
  ③ 把结局写进**日志与指标** —— 定时任务的失效默认是静默的，必须有两个出口。

==============================================================================
★★ 为什么任务体不用 `asyncio.run()`
==============================================================================
Celery worker 是**同步**进程，任务体要跑协程。而 `asyncio.run()` 每次都
**新建并关闭**一个 event loop，asyncpg 的连接绑定在创建它的那个 loop 上
⇒ 若复用应用级连接池，**第一次成功、第二次必挂**
（`Task got Future attached to a different loop`），
而单次验证会**全绿放行** —— 这是本仓记过多次的"假绿"形态。

⇒ 与 `modules/memory/tasks.py` / `modules/trade/tasks.py` 同款：**每线程常驻
  loop**（`_thread_loop`）。于是可以安全复用 `core.database.async_session_factory`，
  不必像 `modules/aigc_media/tasks.py` 那样每次新建 engine（NullPool）。

★★ 异常**不吞**
  让它冒到 Celery：任务被标 FAILURE 并留下 traceback（同时先记一条指标，
  见下）。若改成"捕获后返回删除 0 行"，「这次失败了」与「这次没有过期行」
  在结果里长得**一模一样** —— 那正是"假成功"。同款判据见
  `modules/trade/tasks.py::sync_shop`。

★ 为什么**不**把 `purge_expired` re-export 到 `core/audit/__init__.py`：
  那个包被 `core/database.py::register_all_models()` 在 import 期导入。
  在这里 re-export 会把 `celery` 变成「任何一次 `import core.audit`」的硬依赖
  —— 连只想要 ORM 实体的注册表也要付出这个代价。
  同款理由见 `core/audit/__init__.py` 里「刻意不导出 router」那一段。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict

from core.config import config
from core.database import async_session_factory
from core.logger import get_logger
from core.observability.metrics import AUDIT_PURGE_DELETED, AUDIT_PURGE_RUNS
from core.redis import celery_app

from .retention import purge_expired

logger = get_logger("audit.tasks")

#: 任务注册名。★ 集中定义一次：它同时出现在
#:   · 本文件的 `@celery_app.task(name=...)`
#:   · `core/redis.py::beat_schedule` 里的**字面量**（core 不得 import modules）
#: 写错时 beat 会往一个没人注册的名字投递 —— 现象是「审计表只增不减，
#: 且日志里一条都没有」。⇒ 由 `tests/test_audit_retention_gate.py` 把两边
#: **钉成相等**（不是靠注释提醒）。
TASK_PURGE_EXPIRED = "audit.purge_expired"


# ============================================================
# 每线程常驻 event loop（理由见模块 docstring）
# ============================================================

_LOOP_LOCAL = threading.local()


def _thread_loop() -> asyncio.AbstractEventLoop:
    """本线程的常驻 loop（不存在就建，建好就不再关）。"""
    loop = getattr(_LOOP_LOCAL, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        # 一并设为"当前 loop"：部分库（httpx / anyio）在协程外会走 get_event_loop()。
        asyncio.set_event_loop(loop)
        _LOOP_LOCAL.loop = loop
    return loop


def _run_sync(coro) -> Any:
    return _thread_loop().run_until_complete(coro)


async def _purge_once() -> int:
    """开一个会话 → 删一批 → **提交**，返回删除行数。

    ★ commit 放在这里而不是核里：`purge_expired` 保持「只删不提交」，
      才能被测试塞进自己的事务里回滚（同 `modules/trade/tasks.py` 的分工）。
    """
    async with async_session_factory() as session:
        deleted = await purge_expired(session)
        await session.commit()
    return deleted


# ============================================================
# Celery 任务
# ============================================================

@celery_app.task(bind=True, name=TASK_PURGE_EXPIRED)
def purge_expired_audit_logs(self) -> Dict[str, Any]:
    """beat 入口：清掉 `created_at` 超过保留期的审计行。

    返回值只作**排查线索**，不作为状态源（状态看日志与指标）。
    """
    started = time.perf_counter()
    try:
        deleted = _run_sync(_purge_once())
    except Exception:  # noqa: BLE001 —— 记完指标再原样抛出，绝不吞
        # ★ 先记指标再抛：Celery 的 FAILURE 只活在 worker 日志/结果后端里
        #   （结果 1 小时后过期，见 core/redis.py 的 result_expires）；
        #   指标才能被 Prometheus 抓成**长期**告警。
        AUDIT_PURGE_RUNS.inc(status="failed")
        logger.exception("审计保留期清理失败")
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    AUDIT_PURGE_RUNS.inc(status="ok")
    if deleted:
        # ★ 行数单独一个计数器：`runs{status}` 只答「跑没跑成」，
        #   答不了「回收了多少」—— 而后者是判断保留期**真的在生效**的唯一量化口径
        #   （长期恒为 0 ⇒ 保留期设得过大，或这张表压根没在增长）。
        AUDIT_PURGE_DELETED.inc(deleted)
    logger.info(
        "审计保留期清理完成：删除 {} 行（保留 {} 天），耗时 {}ms",
        deleted,
        config.audit_retention_days,
        elapsed_ms,
    )
    return {"ok": True, "deleted": deleted, "elapsed_ms": elapsed_ms}

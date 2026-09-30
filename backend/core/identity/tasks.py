"""身份域保留期清理的 **Celery 接线**（第 331 轮）。

把两处**零调用点**的清理函数接上调度：

    · `core/identity/login_guard.py::purge_old_attempts`     （`login_attempts` 表）
    · `core/identity/email_tokens.py::purge_spent_tokens`    （`email_tokens` 表）

本文件只做四件机制性的事（内核在两处 purge 与 `identity/retention.py` 里）：

  ① 注册任务名 —— beat 按**名字**投递，见 `core/redis.py::beat_schedule`；
  ② 提供这一次执行的事务边界（开会话 + 一次 commit）；
  ③ 把结局写进**日志与指标** —— 定时任务的失效默认是静默的，必须有两个出口；
  ④ 让"两张表的清理"共用**一个事务**（理由见下）。

==============================================================================
★★ 为什么这两个函数此前是死代码（本轮修的到底是什么）
==============================================================================
它们写好了、幂等、也有行为测试，但**生产代码里零调用点**（只有测试调）。
于是两张表的实际行为是**只增不减**：

  · `login_attempts` —— 每次登录写一行，且失败尝试可被脚本刷。
    实测本机开发库 14 天累积 **3169** 行（2026-09-16 → 2026-09-30）。
  · `email_tokens` —— 每点一次「重发验证邮件」多一行。

★ 这类缺陷的形状是「**每个零件都是好的，缺的只是没有任何东西会去调用它**」——
  所以验收判据不能只是"函数写得对"，必须钉住**真的接上了调度**
  （见 `tests/test_identity_retention_gate.py`）。同款形态在本仓已登记多次，
  最近一次就是 `core/audit/` 的保留期清理（第 328 轮）。

==============================================================================
★★ 为什么两张表共用**一个任务**（而不是两条 beat 条目）
==============================================================================
  · 它们的失效形态完全相同（beat 没起 / 任务名写错 / 任务体空壳），
    分成两条只多一份"两处写法不一致"的故障面；
  · 更重要的是**事务**：两个清理核都刻意「只删、不 commit」
    （那样测试能回滚）。若各开一个会话各自 commit，就会出现
    「登录审计删了、token 没删，而任务报成功」—— 一半成功比全失败更难发现。
    放进**同一个会话**后，`commit` 是唯一的落地点：要么两张表都清完，要么都不清。
  · 代价是"删了多少"混在一个返回值里 ⇒ 用**带 `table` 标签的指标**拆开
    （见 `core/observability/metrics.py::IDENTITY_PURGE_DELETED`），
    信息没丢，而"谁在涨"仍然问得出来。

==============================================================================
★★ 为什么任务体不用 `asyncio.run()`
==============================================================================
Celery worker 是**同步**进程，任务体要跑协程。而 `asyncio.run()` 每次都
**新建并关闭**一个 event loop，asyncpg 的连接绑定在创建它的那个 loop 上
⇒ 若复用应用级连接池，**第一次成功、第二次必挂**
（`Task got Future attached to a different loop`），
而单次验证会**全绿放行** —— 这是本仓记过多次的"假绿"形态。

⇒ 与 `core/audit/tasks.py` / `modules/memory/tasks.py` / `modules/trade/tasks.py`
  同款：**每线程常驻 loop**（`_thread_loop`）。于是可以安全复用
  `core.database.async_session_factory`，不必每次新建 engine（NullPool）。

★★ 异常**不吞**：让它冒到 Celery（任务被标 FAILURE 并留 traceback，
同时先记一条指标）。若改成"捕获后返回删除 0 行"，
「这次失败了」与「这次没有过期行」在结果里长得**一模一样** —— 那正是"假成功"。
同款判据见 `core/audit/tasks.py::purge_expired_audit_logs`。

★ 为什么**不**把本模块 re-export 到 `core/identity/__init__.py`：
  那会把 `celery` 变成「任何一次 `import core.identity`」的硬依赖 ——
  连只想拿 ORM 实体的地方也要付出这个代价（同 `core/audit/tasks.py` 的理由）。

★ 本模块的 import 期边（登记在 `tests/test_core_internal_layering.py`）：
  `identity -> {logger, observability, redis}`。它们与 `identity -> database`
  同族 —— 是「清理」这个能力的**定义性依赖**（记日志 + 记指标 + 注册任务），
  不是"顺手拿一下"。★ `redis` 与 `identity` 之间**不构成环**：
  `core/redis.py` 不 import `core.identity`（它只 import config）⇒ 单向边。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict

from core.config import config
from core.database import async_session_factory
from core.identity.auth_models import EmailToken, LoginAttempt
from core.identity.email_tokens import purge_spent_tokens
from core.identity.login_guard import purge_old_attempts
from core.logger import get_logger
from core.observability.metrics import IDENTITY_PURGE_DELETED, IDENTITY_PURGE_RUNS
from core.redis import celery_app

logger = get_logger("identity.tasks")

#: 任务注册名。★ 集中定义一次：它同时出现在
#:   · 本文件的 `@celery_app.task(name=...)`
#:   · `core/redis.py::beat_schedule` 里的**字面量**（core 不得 import modules）
#: 写错时 beat 会往一个没人注册的名字投递 —— 现象是「两张表只增不减，
#: 且日志里一条都没有」（"没人消费"本身不是错误 ⇒ 什么都不发生）。
#: ⇒ 由 `tests/test_identity_retention_gate.py` 把两边**钉成相等**（不是靠注释提醒）。
TASK_PURGE_EXPIRED = "identity.purge_expired"


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


async def _purge_once() -> Dict[str, int]:
    """开**一个**会话 → 清两张表 → **提交一次**，返回各表删除行数。

    ★ 顺序无关紧要（两张表互不引用），但**事务必须共用一个**：
      commit 放在这里而不是核里 —— 两个核都保持"只删不提交"，
      才能被测试塞进自己的事务里回滚（同 `core/audit/retention.py` 的分工）。
    """
    async with async_session_factory() as session:
        login_deleted = await purge_old_attempts(session)
        token_deleted = await purge_spent_tokens(session)
        await session.commit()
    return {"login_attempts": login_deleted, "email_tokens": token_deleted}


# ============================================================
# Celery 任务
# ============================================================

@celery_app.task(bind=True, name=TASK_PURGE_EXPIRED)
def purge_expired_identity_rows(self) -> Dict[str, Any]:
    """beat 入口：清掉两张身份表里超过保留期的行。

    返回值只作**排查线索**，不作为状态源（状态看日志与指标）。
    """
    started = time.perf_counter()
    try:
        deleted = _run_sync(_purge_once())
    except Exception:  # noqa: BLE001 —— 记完指标再原样抛出，绝不吞
        # ★ 先记指标再抛：Celery 的 FAILURE 只活在 worker 日志/结果后端里
        #   （结果 1 小时后过期，见 core/redis.py 的 result_expires）；
        #   指标才能被 Prometheus 抓成**长期**告警。
        IDENTITY_PURGE_RUNS.inc(status="failed")
        logger.exception("身份域保留期清理失败")
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    IDENTITY_PURGE_RUNS.inc(status="ok")
    # ★ 行数单独一个计数器、且**带 table 标签**：`runs{status}` 只答"跑没跑成"，
    #   答不了"回收了多少"，更答不了"是哪张表在涨"——而后者才是判断
    #   "保留期配错了 / 这个功能压根没在用"的唯一量化口径。
    #   ★ 标签值取自 `Model.__tablename__`（表名的唯一真源），不手写字面量：
    #     改名时指标不会静默失配。
    for model, rows in ((LoginAttempt, deleted["login_attempts"]), (EmailToken, deleted["email_tokens"])):
        if rows:
            IDENTITY_PURGE_DELETED.inc(rows, table=model.__tablename__)
    logger.info(
        "身份域保留期清理完成：login_attempts 删 {} 行（保留 {} 天）/ "
        "email_tokens 删 {} 行（保留 {} 天），耗时 {}ms",
        deleted["login_attempts"],
        config.login_attempt_retention_days,
        deleted["email_tokens"],
        config.email_token_retention_days,
        elapsed_ms,
    )
    return {"ok": True, "deleted": deleted, "elapsed_ms": elapsed_ms}

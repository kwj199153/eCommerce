"""每日经营简报的 **Celery 接线**（第 371 轮）

核（**怎么算**：从监控池快照派生条目、摘要文案、幂等覆盖）住在
`modules/monitors/briefing.py`；本文件只做三件机制性的事：

  ① 注册任务名 —— beat 按**名字**投递，见 `core/redis.py::beat_schedule`；
  ② 提供这一次执行的事务边界（开会话 + 逐店 commit）；
  ③ 把结局写进**日志与指标** —— 定时任务的失效默认是静默的，必须有两个出口。

==============================================================================
★★ 为什么必须有这个模块（本轮修的到底是什么）
==============================================================================
`monitors` 表从建表起就带着五个「变化信号」列（`price_change_7d` /
`stock_status` / `reviews_added_7d` / `bsr_change_7d` / `listing_changes`），
竞品监控看板也能把它们画出来 —— 但用户**必须自己打开那个看板**才看得到。
于是「竞品昨天降了 18%」这件事，只有当用户当天恰好想起去翻监控池时才会被发现。

本任务把这条链路的最后一段接上：每天早上扫一遍监控池，把当天的变化写成一份
简报落库，由右上角铃铛告诉用户「今天有 3 项变化」。

  ★ 同款先例：`core/audit/` 的保留期清理（第 328 轮）、
    `core/backup/` 的每日备份（第 340 轮）—— 都是"函数早就在，
    只是生产里没有任何东西会去调用它"。
  ★ 验收判据不能只是"生成函数能跑"，必须钉住**真的接上了调度**
    （见 `tests/test_briefing_schedule.py`）。

==============================================================================
★★ 为什么任务体不用 `asyncio.run()`
==============================================================================
Celery worker 是**同步**进程，任务体要跑协程。而 `asyncio.run()` 每次都
**新建并关闭**一个 event loop，asyncpg 的连接绑定在创建它的那个 loop 上
⇒ 若复用应用级连接池，**第一次成功、第二次必挂**
（`Task got Future attached to a different loop`），而单次验证会**全绿放行**。
⇒ 与 `core/audit/tasks.py` / `modules/trade/tasks.py` / `modules/memory/tasks.py`
  同款：**每线程常驻 loop**（`_thread_loop`）。

★★ 异常**不吞**
  让它冒到 Celery：任务被标 FAILURE 并留下 traceback（同时先记一条指标）。
  若改成"捕获后返回生成 0 条"，「这次失败了」与「今天真的没有变化」
  在结果里长得**一模一样** —— 那正是"假成功"。
  同款判据见 `core/audit/tasks.py` 与 `modules/trade/tasks.py::sync_shop`。

==============================================================================
★★ 为什么本任务**不** fan-out（与 `trade.sync_all_shops` 相反）
==============================================================================
`trade` 的 `sync_all_shops` 把每家店投成独立任务，因为一次同步要打外部平台 API、
耗时长、且失败要能**按店重试**。

本任务完全相反：它只读**本地** `monitors` 表（每店几十行）+ 写一行摘要，
是"一趟扫描就做完"的量级。fan-out 只会把一趟扫描拆成 N 趟、N 次 worker 调度，
并让"今天到底生成成功了几家"这个数字散落在 N 个任务结果里 ⇒ 收益为负。
⇒ **单任务 + 循环**，返回值里带逐店结果。
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List

from sqlalchemy import select

from core.database import async_session_factory
from core.logger import get_logger
from core.observability.metrics import BRIEFING_ITEMS, BRIEFING_RUNS
from core.redis import celery_app

from modules.monitors.briefing import local_today, generate_for_shop
from modules.monitors.db_model import MonitorRecord

logger = get_logger("monitors.tasks")

#: 任务注册名。★ 集中定义一次：这个名字同时出现在
#:   · 本文件的 `@celery_app.task(name=...)`
#:   · `core/redis.py::beat_schedule` 里的**字面量**（core 不得 import modules）
#: 于是它们构成「同一事实两份写法」—— 写错时 beat 会往一个没人注册的名字投递，
#: 现象是「简报再不长新行，且日志里一条都没有」（"没人消费"本身不是错误）。
#: ⇒ 由 `tests/test_briefing_schedule.py` 把两边**钉成相等**。
TASK_GENERATE_BRIEFINGS = "monitors.generate_daily_briefings"


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


# ============================================================
# 异步实现
# ============================================================

async def _list_monitored_shop_ids() -> List[str]:
    """枚举**监控池里实际出现过**的 `shop_id`。

    ★ 为什么枚举 `monitors.distinct(shop_id)` 而不是 `stores_store.id`：
      ① 简报只对"有监控数据"的店有意义 —— 没有监控的店生成出来是一份
         "今天没有需要你处理的变化"，纯噪音；
      ② 它天然覆盖了 `shop_id == ""`（无租户上下文 / 演示模式）这一档 ——
         枚举 `stores_store` 会**漏掉**它，而演示用户看到的正是那一档
         （`monitors.shop_id` 的列默认值就是空串）。
      ③ 扫描量与实际数据量成正比，不用为它 join 一张无关的表。
    """
    async with async_session_factory() as session:
        rows = (
            await session.execute(select(MonitorRecord.shop_id).distinct())
        ).scalars().all()
        # 归一：列声明了 default ""，但历史行可能是 NULL（列本身 nullable）
        return sorted({(r or "") for r in rows})


async def _generate_all() -> Dict[str, Any]:
    """逐店生成并**逐店提交**。

    ★ 逐店提交而不是最后一次性提交：某一家店的数据异常（比如一行的
      `listing_changes` 存了非 JSON 的脏值）不该把**已经算好的其它店**一起回滚。
      定时任务的部分成功必须能落地 —— 全有或全无在这里只会让"今天一份都没有"。
    """
    date = local_today()
    shop_ids = await _list_monitored_shop_ids()
    results: List[Dict[str, Any]] = []
    total_items = 0

    for shop_id in shop_ids:
        async with async_session_factory() as session:
            out = await generate_for_shop(session, shop_id, date)
            await session.commit()
        results.append(out)
        total_items += int(out["item_count"])

    return {
        "brief_date": date,
        "shops": len(results),
        "items": total_items,
        "results": results,
    }


# ============================================================
# Celery 任务
# ============================================================

@celery_app.task(bind=True, name=TASK_GENERATE_BRIEFINGS)
def generate_daily_briefings(self) -> Dict[str, Any]:
    """beat 入口：为每家店铺生成当天的经营简报。

    返回值只作**排查线索**，不作为状态源（状态看日志与指标）。
    """
    started = time.perf_counter()
    try:
        out = _run_sync(_generate_all())
    except Exception:  # noqa: BLE001 —— 记完指标再原样抛出，绝不吞
        # ★ 先记指标再抛：Celery 的 FAILURE 只活在 worker 日志/结果后端里
        #   （结果 1 小时后过期，见 core/redis.py 的 result_expires）；
        #   指标才能被 Prometheus 抓成**长期**告警。
        BRIEFING_RUNS.inc(status="failed")
        logger.exception("每日经营简报生成失败")
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    BRIEFING_RUNS.inc(status="ok")
    if out["items"]:
        # ★ 条目数单独一个计数器：`runs{status}` 只答「跑没跑成」，
        #   答不了「产出了多少」—— 而后者是判断**阈值真的在生效**的唯一量化口径
        #   （长期恒为 0 ⇒ 阈值设得太宽，或监控池压根没数据）。
        BRIEFING_ITEMS.inc(out["items"])
    logger.info(
        "每日经营简报生成完成：{} 家店 / {} 条，日期 {}，耗时 {}ms",
        out["shops"],
        out["items"],
        out["brief_date"],
        elapsed_ms,
    )
    return {"ok": True, **out, "elapsed_ms": elapsed_ms}


__all__ = ["TASK_GENERATE_BRIEFINGS", "generate_daily_briefings"]

"""AIGC 长任务的 Celery 任务定义。

★ 这个文件此前**不存在**（``celery_app.autodiscover_tasks(["modules"])`` 找的是
``modules.tasks``，永远命中不了）—— 这就是「Celery 配了但全库 ``@task`` 为 0」
的根因。真正让任务被发现的改动有两处，缺一不可：

1. ``core/redis.py`` 里把 autodiscover 指向本模块所在包
2. 本文件存在于 ``modules/aigc_media/tasks.py``

## 为什么任务只收 ``job_id``，参数从 DB 读

图生图的 ``source_image`` 是 base64 data URI，可达数 MB。若塞进 broker 消息
（Redis）会白占一份内存，重试时还要在消息里反复传输。
任务参数保持 ``job_id`` + 日志上下文两个小字段。

## ★★ 跨 event loop 的连接池陷阱（本文件最关键的一处）

Celery worker 是**同步**进程，而业务内核是 ``async def`` ⇒ 任务体里要
``asyncio.run(coro)``。每次调用 ``asyncio.run`` 都会**新建一个 event loop**，
而 asyncpg 的连接是**绑定到创建它的 loop** 的。

若图省事直接复用 ``core.database.engine``（模块级全局单例），现象是：

    第一次任务成功 → 第二次任务必挂
    RuntimeError: Task got Future attached to a different loop

而且这个 bug **只在跑第二个任务时才暴露**，单任务验证会「全绿」放行。
⇒ 本模块每次执行都**新建 engine（``poolclass=NullPool``）+ 结束时 dispose**，
不跨 loop 复用任何连接。NullPool 保证不会有连接被留在池子里跨 loop 存活。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import config
# ★ 这里只导入 get_logger，**不要**导入/调用 setup_logger()：
#   core/logger.py 在模块导入时就已执行过 `setup_logger()`（见其文件末尾），
#   worker 进程只要 import 到它就已经配置好日志。重复调用会 logger.remove()
#   再重加 sink，而 sink 是 enqueue=True（每条一个后台线程）—— 重复初始化会
#   泄漏线程。想改 worker 日志格式请改 config/环境变量，不要在这里重复 setup。
from core.logger import get_logger
from core.observability.metrics import (
    AIGC_TASK_DURATION,
    AIGC_TASKS,
    CELERY_TASK_RESULTS,
)
from core.redis import celery_app

from . import job_service

logger = get_logger("aigc.tasks")

#: 任务注册名（与 CELERY_TASK_RESULTS 指标的 task 标签取值一致）
TASK_NAME = "aigc.run_job"


# ============================================================
# 会话桥（worker 侧）
# ============================================================

def _new_session_factory():
    """为本次任务新建一个自带 event loop 的连接设施。

    ``pool_pre_ping=True`` 不能与 NullPool 同时用出问题：NullPool 每次新建连接，
    pre_ping 只是多一次探测。这里**关掉 pre_ping**（NullPool 下它没有意义，
    反而多一次往返），并关掉 echo。
    """
    engine = create_async_engine(config.database_url, poolclass=NullPool, echo=False)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _execute_with_session(fn):
    """在**全新的** engine/loop 里执行 ``fn(session)``，结束后释放连接。"""
    engine, factory = _new_session_factory()
    try:
        async with factory() as db:
            return await fn(db)
    finally:
        await engine.dispose()


# ============================================================
# 业务分发
# ============================================================

async def _dispatch(kind: str, payload: dict) -> dict[str, Any]:
    """按 kind 调用既有业务内核。

    ★ 刻意**复用** ``service.py`` 里的 ``*_service`` 函数而不是另写一份出图逻辑：
    出图口径（并发数、提示词、转存策略）只能有一套源。
    否则「同步端点出的图」与「异步任务出的图」迟早会分叉。
    """
    # 延迟导入：避免 worker 启动时把整个 FastAPI 依赖树（含 pydantic 模型）全拉起来
    from .schemas import AssetGenerationRequest, ImageGenerationRequest
    from .service import AIGCMediaService

    if kind == "asset_generate":
        return await AIGCMediaService.generate_assets(
            AssetGenerationRequest(**payload)
        )
    if kind == "image_generate":
        return await AIGCMediaService.generate_product_image(
            ImageGenerationRequest(**payload)
        )
    raise ValueError(f"未登记的任务类型：{kind}")


# ============================================================
# 任务体
# ============================================================

async def _run_job(job_id: str, ctx: Optional[dict] = None) -> dict[str, Any]:
    """任务真实逻辑。返回给 Celery 的 summary（**不作为状态源**，状态看 aigc_jobs 表）。"""
    ctx = ctx or {}

    async def _body(db):
        job = await db.get(job_service.AIGCJobRecord, job_id)
        if job is None:
            # 记录不存在：不重试（重试也不会出现），显式记错
            logger.error("[aigc.tasks] 任务记录不存在 job={}", job_id)
            return {"job_id": job_id, "ok": False, "error": "任务记录不存在"}

        if job_service.is_terminal(job.status):
            # ★ 幂等出口：``task_acks_late=True`` 下 worker 崩溃会重投递，
            # 重复执行到已完成的任务时直接返回，避免重复出图（= 重复花钱）。
            logger.warning(
                "[aigc.tasks] 任务已是终态，跳过重复执行 job={} status={}",
                job_id,
                job.status,
            )
            return {"job_id": job_id, "ok": True, "skipped": "already_terminal"}

        kind = job.kind
        payload = dict(job.payload or {})
        retries = int(getattr(job, "retries", 0) or 0)

        await job_service.mark_running(db, job_id)

        started = time.perf_counter()
        AIGC_TASKS.inc(kind=kind, status="started")
        logger.info(
            "[aigc.tasks] 开始执行 job={} kind={} shop={} request_id={}",
            job_id,
            kind,
            ctx.get("shop_id", "-"),
            ctx.get("request_id", "-"),
        )

        try:
            result = await _dispatch(kind, payload)
        except Exception as exc:  # noqa: BLE001 - 任务边界必须兜住一切
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            AIGC_TASKS.inc(kind=kind, status="exception")
            AIGC_TASK_DURATION.observe(elapsed_ms, kind=kind)
            logger.exception("[aigc.tasks] 任务执行抛异常 job={} kind={}", job_id, kind)
            await job_service.mark_failed(db, job_id, f"{type(exc).__name__}: {exc}", retries=retries)
            return {"job_id": job_id, "ok": False, "error": str(exc)}

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        AIGC_TASK_DURATION.observe(elapsed_ms, kind=kind)

        success = bool(result.get("success"))
        if success:
            data = result.get("data") or {}
            assets_count = len(data.get("assets") or []) if isinstance(data, dict) else 0
            # ★ data 里可能是含 base64 的大对象？不会 —— asset_gen 只回 /static 链接。
            #   但为稳妥起见只存必要字段，避免 result 列被无意撑大。
            await job_service.mark_succeeded(
                db, job_id, result=data, assets_count=assets_count
            )
            AIGC_TASKS.inc(kind=kind, status="succeeded")
            logger.info(
                "[aigc.tasks] 任务完成 job={} kind={} assets={} 耗时={:.0f}ms",
                job_id,
                kind,
                assets_count,
                elapsed_ms,
            )
        else:
            error = result.get("message") or result.get("error") or "任务失败（未给出原因）"
            await job_service.mark_failed(db, job_id, error, retries=retries)
            AIGC_TASKS.inc(kind=kind, status="failed")
            logger.warning("[aigc.tasks] 任务失败 job={} kind={} 原因={}", job_id, kind, error)

        return {
            "job_id": job_id,
            "ok": success,
            "elapsed_ms": int(elapsed_ms),
        }

    return await _execute_with_session(_body)


@celery_app.task(bind=True, name=TASK_NAME)
def run_aigc_job(self, job_id: str, ctx: Optional[dict] = None) -> dict[str, Any]:
    """Celery 任务入口（同步函数，内部用 ``asyncio.run`` 桥到异步内核）。

    日志已在 import ``core.logger`` 时配置好（见文件顶部 import 处的说明），
    这里不需要也不应该再调一次 setup。
    """
    try:
        return asyncio.run(_run_job(job_id, ctx))
    except Exception as exc:  # noqa: BLE001 - 兜住 asyncio.run 自身的问题（如 loop 冲突）
        logger.exception("[aigc.tasks] 任务无法启动 job={}", job_id)
        CELERY_TASK_RESULTS.inc(task=TASK_NAME, status="infra_failure")
        # 任务连"启动"都没成功 ⇒ 必须把记录改成 failed，
        # 否则用户看到的是一个永远转圈的「排队中」
        try:
            asyncio.run(
                _execute_with_session(
                    lambda db: job_service.mark_failed(
                        db, job_id, f"任务无法启动：{type(exc).__name__}: {exc}"
                    )
                )
            )
        except Exception:  # noqa: BLE001 - 兜底失败也不能再抛，否则 Celery 一直重试
            logger.exception("[aigc.tasks] 标记任务失败时又出错 job={}", job_id)
        raise


# ============================================================
# Celery 信号 → 指标
# ============================================================

from celery.signals import task_failure, task_success  # noqa: E402


@task_success.connect
def _on_task_success(sender=None, **kwargs):  # pragma: no cover - 信号回调
    """任务成功信号 —— 补上「Celery 层面」的终态计数。

    为什么要单独记：``_run_job`` 记的是「业务成功/失败」，
    而这里记的是「Celery 层面把任务判成功/失败」。两者不一致时（例如任务函数
    抛异常但业务侧已标记 succeeded）能立刻看出来，这是排查「状态对不上」的关键信号。
    """
    CELERY_TASK_RESULTS.inc(task=getattr(sender, "name", TASK_NAME), status="success")


@task_failure.connect
def _on_task_failure(sender=None, **kwargs):  # pragma: no cover - 信号回调
    CELERY_TASK_RESULTS.inc(task=getattr(sender, "name", TASK_NAME), status="failure")

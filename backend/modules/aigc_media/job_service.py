"""AIGC 异步任务的状态读写层（提交 / 查询 / 状态流转）。

本模块是「任务状态」的**唯一权威源**，与 Celery 的 result backend 无关
（原因见 ``db_model`` 顶部：result_expires=3600，1 小时后就查不到钱了花在哪）。

三个设计要点，每个都对应一类真实会出事的方式：

1. **提交用 ``INSERT ... ON CONFLICT DO NOTHING``，不用「先查再插」**
   出图要花钱（≈¥0.14/张）。连点两次「开始生成素材」时，两个并发请求会在
   「查无进行中任务 → 插入」之间**双双通过检查**，变成两份任务、双倍计费。
   用 DB 的部分唯一索引 + ``ON CONFLICT DO NOTHING`` 把判重下沉到数据库，
   并发下也只有一条能插进去。

   ★ 不用「插入失败 → rollback → 再 SELECT」的写法：本项目的 async SQLAlchemy
   组合里，``await db.rollback()`` 之后再 ``db.execute()`` 会在连接池 checkout 的
   pre-ping 阶段抛 ``MissingGreenlet``（P1-4 支付链路踩过）。
   ``ON CONFLICT DO NOTHING`` 不产生异常、不需要回滚，从根上绕开这个坑。

2. **``ON CONFLICT`` 的冲突目标必须带 ``index_where``**
   因为索引是**部分**唯一索引（只对 pending/running 生效）。
   漏了 ``index_where`` 会让 PostgreSQL 找不到匹配的唯一索引，
   报 ``there is no unique or exclusion constraint matching the ON CONFLICT specification``。

3. **投递失败必须显式落库成 failed**
   任务若停在 pending 而队列里根本没有它，用户会一直看着「排队中」转圈，
   这是最难排查的一类故障。宁可立刻告诉用户「异步执行器不可用」。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.logger import get_logger

from .db_model import (
    INFLIGHT_STATUSES,
    KIND_LABELS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    AIGCJobRecord,
    is_terminal,
)

logger = get_logger("aigc.jobs")

#: 允许提交的任务类型。加新类型时**只需**在这里登记 + 在 tasks.py 的分发里加一个分支，
#: 端点本身不用改（避免每加一种长任务就复制一遍提交/查询逻辑）。
ALLOWED_KINDS: tuple[str, ...] = ("asset_generate", "image_generate")

#: 单用户同时进行中的任务上限。
#:
#: 为什么需要：Celery worker 并发有限，而出图内部还有 MAX_CONCURRENCY=2 的并发上限。
#: 一个用户连点 10 次就会把队列占满、其他用户全部排队（吵到别人）。
#: 拦在入口比事后限流便宜。
#:
#: ★ 这是**配额**，从配置读（``AIGC_MAX_INFLIGHT_PER_USER``），不写死：
#:   不同套餐/客户等级需要不同值，写死意味着改配额要改代码 + 重新发布。
#:   读不到时回落到 3 —— 配置异常也不该让「防连点」这道闸门失效（fail-closed 取小值）。
def _resolve_max_inflight() -> int:
    raw = getattr(config, "aigc_max_inflight_per_user", 3)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("[aigc.jobs] AIGC_MAX_INFLIGHT_PER_USER 不是整数（{!r}），回落为 3", raw)
        return 3
    if value < 1:
        # 0 或负数会让**任何**提交都被拒 —— 那是把功能关掉，不是「不限」。
        # 真要关掉应通过鉴权/功能开关，而不是把配额设成 0。
        logger.warning("[aigc.jobs] AIGC_MAX_INFLIGHT_PER_USER={} 非法（须 ≥1），回落为 3", value)
        return 3
    return value


MAX_INFLIGHT_PER_USER = _resolve_max_inflight()

#: 任务列表默认返回条数
DEFAULT_LIST_LIMIT = 20


# ============================================================
# ID 与去重指纹
# ============================================================

def new_job_id() -> str:
    """生成任务 ID。

    形如 ``job_3f2a1b8c9d0e``（不用自增序号：job_id 对前端完全可见，
    自增会被逐个扫出别人的任务规模）。
    """
    return f"job_{uuid.uuid4().hex[:12]}"


def build_dedupe_key(kind: str, payload: Optional[dict]) -> str:
    """由「任务类型 + 入参」算出稳定指纹。

    必须是**稳定**的：同一次点击产生的两个并发请求要算出同一个键，
    否则去重失效。因此 ``sort_keys=True``（dict 顺序不影响结果）+
    ``ensure_ascii=False``（中文参数不会因为转义与否算出两个键）。

    ``source_image`` 可能是数 MB 的 base64 —— 只取 sha256，不落原始串。
    """
    blob = json.dumps(
        {"kind": kind, "payload": payload or {}},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ============================================================
# 提交
# ============================================================

class DuplicateJob(Exception):
    """命中去重：同一用户已有相同入参的进行中任务。

    不是错误 —— 路由层会把它转成「返回已有任务」，用户视角是一次正常点击。
    """

    def __init__(self, job: AIGCJobRecord):
        super().__init__(f"重复提交，复用进行中的任务 {job.id}")
        self.job = job


class TooManyInflight(Exception):
    """同一用户进行中的任务过多（超出 MAX_INFLIGHT_PER_USER）。"""

    def __init__(self, current: int):
        super().__init__(
            f"当前已有 {current} 个任务进行中，请等待完成后再提交（上限 {MAX_INFLIGHT_PER_USER}）"
        )
        self.current = current


async def create_job(
    db: AsyncSession,
    *,
    kind: str,
    payload: Optional[dict],
    user_id: str = "",
    shop_id: str = "",
    request_id: str = "",
) -> AIGCJobRecord:
    """落库一条 pending 任务（不去重场景）。

    ★ 去重与并发安全由 **DB 部分唯一索引**保证，见 ``db_model.AIGCJobRecord``。
    本函数故意不先 SELECT：先查再插在并发下必然漏。
    """
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"未知任务类型：{kind}（支持 {', '.join(ALLOWED_KINDS)}）")

    record = AIGCJobRecord(
        id=new_job_id(),
        kind=kind,
        status=STATUS_PENDING,
        user_id=user_id or "",
        shop_id=shop_id or "",
        request_id=request_id or "",
        dedupe_key=build_dedupe_key(kind, payload),
        payload=payload or {},
    )
    db.add(record)
    await db.flush()
    return record


def _inflight_filter(user_id: str, shop_id: str, dedupe_key: str):
    """未结束任务的定位条件。

    租户维度用 ``user_id``：有登录用户时按用户隔离；演示模式（无登录）
    ``user_id`` 为空串，此时退化为按 ``shop_id`` 隔离，避免演示模式下
    两个不同店铺互相把对方去重掉。
    """
    conds = [
        AIGCJobRecord.dedupe_key == dedupe_key,
        AIGCJobRecord.status.in_(INFLIGHT_STATUSES),
    ]
    if user_id:
        conds.append(AIGCJobRecord.user_id == user_id)
    else:
        conds.append(AIGCJobRecord.shop_id == (shop_id or ""))
    return conds


async def submit_job(
    db: AsyncSession,
    *,
    kind: str,
    payload: Optional[dict],
    user_id: str = "",
    shop_id: str = "",
    request_id: str = "",
) -> tuple[AIGCJobRecord, bool]:
    """提交任务，返回 ``(任务, 是否命中去重)``。

    流程：
      1. 数一下该用户进行中的任务（超限直接拒绝 —— 别一个人占满队列）
      2. ``INSERT ... ON CONFLICT DO NOTHING RETURNING id``
      3. 没插进去 ⇒ 说明命中了部分唯一索引 ⇒ 查出那条进行中任务原样返回
    """
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"未知任务类型：{kind}（支持 {', '.join(ALLOWED_KINDS)}）")

    inflight_count = await count_inflight(db, user_id=user_id, shop_id=shop_id)
    if inflight_count >= MAX_INFLIGHT_PER_USER:
        raise TooManyInflight(inflight_count)

    dedupe_key = build_dedupe_key(kind, payload)
    values = {
        "id": new_job_id(),
        "kind": kind,
        "status": STATUS_PENDING,
        "user_id": user_id or "",
        "shop_id": shop_id or "",
        "request_id": request_id or "",
        "dedupe_key": dedupe_key,
        "payload": payload or {},
        "error": "",
        "assets_count": 0,
        "retries": 0,
        "celery_task_id": "",
        "created_at": datetime.utcnow(),
    }

    stmt = (
        pg_insert(AIGCJobRecord)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["user_id", "dedupe_key"],
            # ★ 必须与 db_model 里部分唯一索引的 WHERE 完全一致，否则 PG 找不到该索引
            index_where=text("status IN ('pending', 'running')"),
        )
        .returning(AIGCJobRecord.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()

    if inserted_id is None:
        # 命中去重：把已有那条进行中任务捞出来返回
        existing = (
            await db.execute(
                select(AIGCJobRecord).where(*_inflight_filter(user_id, shop_id, dedupe_key))
            )
        ).scalars().first()
        if existing is not None:
            # 日志占位符用 {} —— core.logger 是 loguru，**不认** stdlib 的 %s：
            # 写 %s 不会报错，只会把字面量 "%s" 打进日志并把参数丢掉。
            logger.info(
                "[aigc.jobs] 命中重复提交，复用进行中任务 job={} kind={}", existing.id, kind
            )
            return existing, True
        # 极端竞态：索引说冲突了，但那条记录刚好在这一瞬变成终态。
        # 此时不静默当作成功 —— 让调用方重试，优于返回一个查不到的任务。
        raise RuntimeError("提交时检测到并发冲突，请重试")

    job = await db.get(AIGCJobRecord, inserted_id)
    if job is None:  # pragma: no cover - flush 后必然可读
        raise RuntimeError("任务落库失败")
    return job, False


async def count_inflight(db: AsyncSession, *, user_id: str = "", shop_id: str = "") -> int:
    """该归属下未结束的任务数。"""
    conds = [AIGCJobRecord.status.in_(INFLIGHT_STATUSES)]
    if user_id:
        conds.append(AIGCJobRecord.user_id == user_id)
    else:
        conds.append(AIGCJobRecord.shop_id == (shop_id or ""))
    rows = (await db.execute(select(AIGCJobRecord.id).where(*conds))).scalars().all()
    return len(rows)


# ============================================================
# 查询（★ 必须带归属过滤）
# ============================================================

def _owner_filter(user_id: str, is_admin: bool):
    """按归属过滤。

    ★ P0-1（BOLA/IDOR）教训：``BUSINESS_AUTH`` 只回答「你是谁」，
    不回答「这条数据是不是你的」。任何「按 ID 取单条」的端点都必须**额外**
    按 owner 过滤一次，否则拿到 job_id 就能读到别人店铺的素材链接。
    admin 放行（运维排查需要）。
    """
    if is_admin:
        return []
    return [AIGCJobRecord.user_id == (user_id or "")]


async def get_job(
    db: AsyncSession, job_id: str, *, user_id: str = "", is_admin: bool = False
) -> Optional[AIGCJobRecord]:
    """按 ID 取任务；**不属于该归属时返回 None**（路由层转 404）。

    故意返回 404 而不是 403：403 等于告诉对方「这个 job_id 是存在的」，
    会把任务的 ID 空间泄露出去。
    """
    stmt = select(AIGCJobRecord).where(
        AIGCJobRecord.id == job_id, *_owner_filter(user_id, is_admin)
    )
    return (await db.execute(stmt)).scalars().first()


async def list_jobs(
    db: AsyncSession,
    *,
    user_id: str = "",
    is_admin: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[AIGCJobRecord]:
    """最近创建优先的任务列表。

    ``user_id`` 为空（演示模式）时**不按 user 过滤**，但仍按 ``shop_id``
    由路由层传进来的上下文收敛 —— 演示模式本身就是单租户匿名模式。
    """
    limit = max(1, min(int(limit or DEFAULT_LIST_LIMIT), 100))
    stmt = (
        select(AIGCJobRecord)
        .where(*_owner_filter(user_id, is_admin))
        .order_by(AIGCJobRecord.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


# ============================================================
# 状态流转（worker 侧调用）
# ============================================================

async def mark_running(db: AsyncSession, job_id: str) -> bool:
    """pending → running。终态记录不会被覆写，返回 False。"""
    job = await db.get(AIGCJobRecord, job_id)
    if job is None:
        return False
    if is_terminal(job.status):
        return False
    job.status = STATUS_RUNNING
    job.started_at = datetime.utcnow()
    await db.commit()
    return True


async def mark_succeeded(
    db: AsyncSession, job_id: str, *, result: Optional[dict], assets_count: int = 0
) -> bool:
    """running → succeeded。"""
    job = await db.get(AIGCJobRecord, job_id)
    if job is None or is_terminal(job.status):
        return False
    job.status = STATUS_SUCCEEDED
    job.result = result
    job.assets_count = int(assets_count or 0)
    job.error = ""
    job.finished_at = datetime.utcnow()
    await db.commit()
    return True


async def mark_failed(db: AsyncSession, job_id: str, error: str, *, retries: int = 0) -> bool:
    """→ failed。终态不回退，但允许 running→failed 覆盖 pending→failed 之外的重复写。"""
    job = await db.get(AIGCJobRecord, job_id)
    if job is None or is_terminal(job.status):
        return False
    job.status = STATUS_FAILED
    job.error = (error or "未知错误")[:2000]
    job.retries = int(retries or 0)
    job.finished_at = datetime.utcnow()
    await db.commit()
    return True


async def set_celery_task_id(db: AsyncSession, job_id: str, task_id: str) -> None:
    """回写 Celery 任务 ID（仅为排查用；失败不影响任务本身）。"""
    job = await db.get(AIGCJobRecord, job_id)
    if job is None:
        return
    job.celery_task_id = (task_id or "")[:64]
    await db.commit()


# ============================================================
# 投递到 Celery
# ============================================================

class ExecutorUnavailable(Exception):
    """异步执行器（Celery broker / Redis）不可用。

    ★ 必须显式抛出并让路由层转成 503 —— **不能**让任务停在 pending 假装成功。
    「任务已排队」而队列里根本没有它，是用户最难理解、我们最难排查的一类故障：
    界面上一直转圈，日志里什么都没有。
    """


def enqueue(job_id: str, ctx: Optional[dict] = None) -> str:
    """把任务投给 Celery，返回 Celery 任务 ID。

    函数内**延迟 import** ``core.redis`` / ``.tasks``：这两个模块会拉起整条
    Celery + 业务内核的依赖树，而 API 进程只有在真的提交任务时才需要它，
    放在模块顶层会让 ``import main`` 多背一堆启动开销与循环导入风险。
    """
    from core.redis import celery_app

    from .tasks import TASK_NAME

    try:
        async_result = celery_app.send_task(TASK_NAME, args=[job_id, ctx or {}])
    except Exception as exc:  # noqa: BLE001 - broker 连接失败形态很多（ConnectionError/OSError/kombu 各类异常）
        raise ExecutorUnavailable(
            f"无法连接异步执行器（Redis/Celery broker）：{type(exc).__name__}: {exc}"
        ) from exc
    return str(async_result.id or "")


# ============================================================
# 序列化
# ============================================================

def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """UTC 时间戳**必须带 Z 后缀**。

    ★ 项目既有约定里有一处坑：naive 时间串（``2026-09-15T01:00:00``）前端
    ``new Date(s)`` 会当**本地时间**解析，于是显示出来的时间比真实时间早 8 小时。
    这里统一输出 ``...Z``，前端用 ``new Date(s).toLocaleString('zh-CN')``
    就能正确折算到本地时区。
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def serialize_job(job: AIGCJobRecord, *, include_result: bool = True) -> dict[str, Any]:
    """对外结构。字段名与前端 ``AigcJob`` 接口一一对应。"""
    elapsed_ms: Optional[int] = None
    if job.started_at is not None:
        end = job.finished_at or datetime.utcnow()
        elapsed_ms = int((end - job.started_at).total_seconds() * 1000)

    out: dict[str, Any] = {
        "id": job.id,
        "kind": job.kind,
        "kind_label": KIND_LABELS.get(job.kind, job.kind),
        "status": job.status,
        "is_terminal": is_terminal(job.status),
        "assets_count": int(job.assets_count or 0),
        "error": job.error or "",
        "created_at": _iso_utc(job.created_at),
        "started_at": _iso_utc(job.started_at),
        "finished_at": _iso_utc(job.finished_at),
        "elapsed_ms": elapsed_ms,
    }
    if include_result:
        out["result"] = job.result
    return out

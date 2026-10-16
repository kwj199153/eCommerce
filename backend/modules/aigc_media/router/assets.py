"""AIGC 媒体生成 - 出图端点（同步一条 + 异步一条）与异步任务三件套。

从 `router.py` 逐字搬来（第 363 轮拆包）。

★ 同步与异步**不是两份实现**：两者共用 `asset_gen.generate_assets` 这个执行内核，
  差别只在**投递方式**（调用方能否承受长连接）。原文那段「为什么需要异步」的
  推导留在文件里，改动前先读它 —— 它是「钱花了、结果丢了」那个缺陷的记录。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import require_auth_if_enabled
from core.database import get_db
from core.identity.models import User
from core.observability.context import current_request_id
from core.tenant.middleware import get_current_shop_id

from .. import job_service
from ..service import AIGCMediaService
from ..schemas import (
    AgentResponse,
    AigcJobSubmitRequest,
    AssetGenerationRequest,
    ImageGenerationRequest,
)

router = APIRouter()

# ============================================================
# 静态素材批量生成（面板驱动）
# ============================================================

@router.post(
    "/asset/generate",
    response_model=AgentResponse,
    summary="静态素材批量生成（同步）",
    description=(
        "面板驱动：按素材类型（SPU 主图/白底副图/场景图/生活方式图/信息图解图/广告主图）"
        "并发出图，返回可长期访问的 /static 图片地址。\n"
        "- 与 /image/generate 的区别：那条是对话驱动、可先追问缺参；这条不做缺参拦截。\n"
        "- 任一类型失败不影响其余，失败原因逐项回传；**全部失败才返回 503**。\n"
        "- 当前为文生图（源图需公网可访问地址才能图生图，图床尚未接入）。\n"
        "\n"
        "⚠️ **本端点会同步阻塞整个出图过程**（最坏 720s：8 张 / 并发 2 × 单张超时 180s）。\n"
        "前端生产路径请改用异步端点 `POST /aigc/jobs`（kind=asset_generate），"
        "本端点保留给「能承受长连接」的调用方（脚本、调试、以及没有 worker 的环境）。\n"
        "两者共用同一个执行内核，出图口径不会分叉。"
    ),
)
async def generate_assets(
    request: AssetGenerationRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """静态素材批量生成（面板驱动，不追问缺参）。"""
    result = await AIGCMediaService.generate_assets(request)
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result.get("message", "素材生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="asset_generate",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 异步任务端点（长任务不阻塞 HTTP）
# ------------------------------------------------------------
# 为什么需要这一组：出图原本整段同步阻塞在 HTTP 请求里。
# 实测参数（代码常量）：单张 15-25s、内部并发 2（3 并发会被服务端 429）、
# 单次最多 8 张、`wait_for_images` 单张超时 180s
# ⇒ 最坏 8/2 × 180s = 720s。
# 而前端 axios 超时是 300s ⇒ **720 > 300**：极端情况下用户看到「超时失败」，
# 但后端仍在出图、DashScope 已按张计费（≈¥0.14/张）—— **钱花了，结果丢了**。
#
# 改成异步后：
#   - HTTP 连接只占一次提交（毫秒级），不再被长任务长期占用（uvicorn worker 得以释放）
#   - 即使前端轮询中断，任务仍在 worker 上跑完并落库，刷新后能查到
#   - 任务状态落 `aigc_jobs` 表（不依赖 Celery result backend，后者 1 小时就过期）
#
# ★ 与同步端点的分工（避免「同一件事两条路各写一遍」）：
#   两者**共用** `asset_gen.generate_assets` 这个执行内核，只是投递方式不同：
#     - `/aigc/asset/generate`（同步）：调用方能承受长连接时使用（脚本 / 调试 / 无 worker 环境）
#     - `/aigc/jobs`（异步）：**前端生产路径**
#   所以「执行口径」只有一套源，「投递方式」按调用方能力分两种。
# ============================================================

#: kind → 入参校验模型。★ 异步端点不是「把 dict 直接塞进队列」：
#: 这里复用同步端点同一套 Pydantic 模型，校验强度完全一致。
_JOB_PARAM_SCHEMAS = {
    "asset_generate": AssetGenerationRequest,
    "image_generate": ImageGenerationRequest,
}


def _job_owner(current_user: Optional[User]) -> tuple[str, bool]:
    """从当前用户推出 (user_id, is_admin)。

    认证开关关闭时（演示模式）current_user 为 None ⇒ user_id 为空串，
    此时任务按 shop_id 收敛（见 job_service._inflight_filter 的说明）。
    """
    if current_user is None:
        return "", False
    return current_user.id, current_user.role.value == "admin"


@router.post(
    "/jobs",
    status_code=202,
    summary="提交 AIGC 长任务（异步）",
    description=(
        "提交后立即返回 202 + job_id，出图在 Celery worker 上执行。\n"
        "- 用 `GET /aigc/jobs/{job_id}` 轮询状态，状态落 `aigc_jobs` 表（不依赖 Celery result backend）。\n"
        "- **同一入参的进行中任务会被去重**：连点两次不会重复出图（出图按张计费，重复提交=重复花钱），"
        "命中时返回同一条任务并带 `deduplicated=true`。\n"
        "- 单用户进行中任务上限 3 条，超出返回 429。\n"
        "- 异步执行器（Redis/Celery）不可用时返回 503 并把任务显式标成 failed —— "
        "**不会**留下一个永远停在 pending 的假排队任务。"
    ),
)
async def submit_aigc_job(
    request: AigcJobSubmitRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    """提交一个 AIGC 长任务，立即返回 job_id。"""
    schema = _JOB_PARAM_SCHEMAS.get(request.kind)
    if schema is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"未知任务类型：{request.kind}；"
                f"当前支持 {', '.join(sorted(_JOB_PARAM_SCHEMAS))}"
            ),
        )

    try:
        params = schema.model_validate(request.params).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"任务入参不合法：{exc.errors()[:3]}",
        ) from exc

    user_id, is_admin = _job_owner(current_user)

    try:
        job, deduplicated = await job_service.submit_job(
            db,
            kind=request.kind,
            payload=params,
            user_id=user_id,
            shop_id=shop_id or "",
            request_id=current_request_id(),
        )
    except job_service.TooManyInflight as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    # ★ 必须先提交再投递：worker 拿到 job_id 后要回库读 payload，
    #   若先投递后提交，worker 可能读到一个尚未可见的行。
    await db.commit()

    if deduplicated:
        return {
            "success": True,
            "job": job_service.serialize_job(job),
            "deduplicated": True,
            "message": "已存在相同参数的进行中任务，本次未重复提交（不重复计费）",
        }

    # 投递到 Celery
    ctx = {
        "request_id": current_request_id(),
        "shop_id": shop_id or "",
        "user_id": user_id,
    }
    try:
        task_id = job_service.enqueue(job.id, ctx)
    except job_service.ExecutorUnavailable as exc:
        # ★ 显式失败：把刚建的 pending 任务标成 failed 再报 503。
        #   绝不能只报错不改状态 —— 用户会看到列表里多出一条永远「排队中」的任务。
        await job_service.mark_failed(db, job.id, str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                f"异步执行器不可用，任务未被执行：{exc}。"
                "请确认 Redis 与 Celery worker 已启动（docker compose up -d redis worker）"
            ),
        ) from exc

    if task_id:
        await job_service.set_celery_task_id(db, job.id, task_id)

    return {
        "success": True,
        "job": job_service.serialize_job(job),
        "deduplicated": False,
        "message": "任务已提交，请轮询 /api/v1/aigc/jobs/{job_id} 获取进度",
    }


@router.get(
    "/jobs/{job_id}",
    summary="查询 AIGC 任务状态",
    description=(
        "读取任务的权威状态（`aigc_jobs` 表）。\n"
        "- **按归属过滤**：只能查自己提交的任务，别人的 job_id 一律返回 404"
        "（返回 404 而非 403，避免泄露 job_id 是否存在）；admin 可查全部。\n"
        "- `status`：pending → running → succeeded / failed；`is_terminal=true` 表示已结束，不用再轮询。\n"
        "- 时间戳为 **UTC 且带 Z 后缀**，前端请用 `new Date(s).toLocaleString('zh-CN')` 折算本地时区。"
    ),
)
async def get_aigc_job(
    job_id: str,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """按 ID 查询任务状态（只能查自己的）。"""
    user_id, is_admin = _job_owner(current_user)
    job = await job_service.get_job(db, job_id, user_id=user_id, is_admin=is_admin)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "job": job_service.serialize_job(job)}


@router.get(
    "/jobs",
    summary="我的 AIGC 任务列表",
    description=(
        "最近创建优先，默认 20 条（上限 100）。\n"
        "用途：前端轮询中断（刷新页面 / 关掉标签页）后仍能找回自己刚提交的任务 —— "
        "这是异步化相对同步阻塞最直接的收益：**任务不会因为前端断线而消失**。"
    ),
)
async def list_aigc_jobs(
    limit: int = Query(default=job_service.DEFAULT_LIST_LIMIT, ge=1, le=100),
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的任务（不含 result 大字段，列表页用）。"""
    user_id, is_admin = _job_owner(current_user)
    jobs = await job_service.list_jobs(db, user_id=user_id, is_admin=is_admin, limit=limit)
    return {
        "success": True,
        "jobs": [job_service.serialize_job(j, include_result=False) for j in jobs],
        "total": len(jobs),
    }

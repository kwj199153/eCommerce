"""审计读口 —— 仅**平台管理员**可读（P0-5b）。

==============================================================================
★ 为什么读口要单独一层权限，而不是复用业务鉴权
==============================================================================
审计表的内容是**跨账户、跨租户**的全局视图：

    「过去 7 天有哪些账户的成员被改过」
    「谁删了店铺」

这类查询天然无法用「按 shop / account 过滤」来限制 —— 它的价值就在于
**横向看全部**。所以能读它的必须是一个**全局角色**，而不是某个账户的
owner / admin。本仓的全局角色就是**平台超管**（`users.role == admin`），
判定真源是 `core/auth/accounts.py::is_platform_admin()`。

⇒ 因此本文件所有端点一律挂 `Depends(get_admin_user)`：
      · 匿名 / 无效 token ⇒ **401**（由 `get_current_user` 抛出）；
      · 已登录但非平台超管 ⇒ **403**。
   ★ 401 与 403 必须分开：把两者压成同一个码会让前端无法区分
     「该去登录」与「登录了也没用」，而这是两种截然不同的处置。

==============================================================================
★ 只读：本文件不提供任何写端点
==============================================================================
审计是 append-only 的证据（见 `models.py` 文件头）。**没有**「改审计」
「删审计」的端点，且这是刻意设计而非尚未实现 —— 能改的记录不能证明任何事。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit.actions import ACTIONS
from core.audit.models import AuditLog
from core.auth.dependencies import get_admin_user
from core.database import get_db
from core.identity.models import User
from core.timefmt import utc_iso

router = APIRouter(prefix="/audit", tags=["audit"])


def _parse_dt(raw: Optional[str], field: str) -> Optional[datetime]:
    """把 ISO 8601 字符串解析成 naive-UTC `datetime`（本仓时间列口径）。

    ★ 非法输入**显式 400**，绝不静默忽略：静默忽略会让调用方以为"筛选生效了"，
      拿到的是全量结果却当成筛选结果 —— 那是一种很难发现的错误结论。
    """
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    # 允许前端直接传 `Date.toISOString()` 的结尾 `Z`
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} 不是合法的 ISO 8601 时间：{raw!r}",
        ) from exc
    # 本仓时间列是 naive-UTC ⇒ 带偏移的输入归一化到 UTC 再去掉 tzinfo
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_dict(row: AuditLog) -> dict:
    """行 → JSON。时间一律走 `utc_iso`（本仓唯一序列化口径）。"""
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_email": row.actor_email,
        "action": row.action,
        "status": row.status,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "summary": row.summary,
        "detail": row.detail,
        "ip": row.ip,
        "user_agent": row.user_agent,
        "created_at": utc_iso(row.created_at),
    }


@router.get("/logs")
async def list_audit_logs(
    action: Optional[str] = Query(None, description="动作精确匹配，如 store.delete"),
    actor_id: Optional[str] = Query(None, description="执行者用户 id"),
    target_type: Optional[str] = Query(None, description="目标类型，如 store / member"),
    target_id: Optional[str] = Query(None, description="目标 id"),
    status_: Optional[str] = Query(None, alias="status", description="结果：success / failure"),
    since: Optional[str] = Query(None, description="起始时间（ISO 8601，含）"),
    until: Optional[str] = Query(None, description="结束时间（ISO 8601，含）"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按时间倒序分页查询审计日志（平台超管专属）。"""
    conds = []
    if action:
        conds.append(AuditLog.action == action)
    if actor_id:
        conds.append(AuditLog.actor_id == actor_id)
    if target_type:
        conds.append(AuditLog.target_type == target_type)
    if target_id:
        conds.append(AuditLog.target_id == target_id)
    if status_:
        conds.append(AuditLog.status == status_)
    since_dt = _parse_dt(since, "since")
    until_dt = _parse_dt(until, "until")
    if since_dt is not None:
        conds.append(AuditLog.created_at >= since_dt)
    if until_dt is not None:
        conds.append(AuditLog.created_at <= until_dt)

    total = (
        await db.execute(select(func.count()).select_from(AuditLog).where(*conds))
    ).scalar_one()

    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(*conds)
                # ★ 排序必须带 tiebreaker `id`：同一秒内可能写入多条
                #   （批量操作），只按 created_at 排序会让翻页时
                #   **行在页间跳动**（同一条出现两次 / 有的行漏掉）。
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return {
        "items": [_to_dict(r) for r in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/actions")
async def list_audit_actions(
    _admin: User = Depends(get_admin_user),
) -> dict:
    """动作目录（读口与前端筛选下拉的**唯一真源**）。

    返回 `core/audit/actions.py::ACTIONS` 的投影 —— 前端据此渲染筛选框。
    ★ 刻意不在这里再列一份清单：两份必然在某次新增动作后不同步，
      而表现是「新动作记进了库、筛选框里却选不到」，排查时极难想到。
    """
    items = [
        {"action": action, "label": label, "target_type": target_type}
        for action, label, target_type in ACTIONS
    ]
    return {"items": items, "total": len(items)}

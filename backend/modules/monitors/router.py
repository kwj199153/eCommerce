"""
竞品监控池 API

数据源：PostgreSQL（monitors / monitor_groups 表），唯一权威源。

端点：
GET    /api/v1/monitors                     - 监控池列表
GET    /api/v1/monitors/{monitor_id}        - 单条详情
POST   /api/v1/monitors                     - 入池（按 shop+asin 判重，已存在则合并）
PUT    /api/v1/monitors/{monitor_id}        - 更新
DELETE /api/v1/monitors/{monitor_id}        - 移出监控池
POST   /api/v1/monitors/batch-delete        - 批量移出
POST   /api/v1/monitors/batch-upsert        - 批量入池（候选库 / 对标竞品批量开启监控）
POST   /api/v1/monitors/assign-group        - 批量归入分组
POST   /api/v1/monitors/unassign-group      - 批量移出分组
GET    /api/v1/monitor-groups               - 分组列表
POST   /api/v1/monitor-groups               - 新建分组
PUT    /api/v1/monitor-groups/{group_id}    - 更新分组
DELETE /api/v1/monitor-groups/{group_id}    - 删除分组
GET    /api/v1/briefings                    - 每日经营简报列表（含未读数）
POST   /api/v1/briefings/{briefing_id}/read - 标记一条简报已读

租户隔离：全部走 `get_current_shop_id`（X-Shop-ID 头）。
列表在无租户上下文时返回空 —— 与 candidates / products / assets 一致。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy import select, delete

from core.database import async_session_factory
from core.tenant.middleware import get_current_shop_id
from core.tenant.scoping import scoped
from modules.monitors.briefing import (
    count_unread as count_unread_svc,
    list_briefings as list_briefings_svc,
    mark_read as mark_read_svc,
)
from modules.monitors.db_model import MonitorRecord, MonitorGroupRecord
from modules.monitors.service import (
    upsert_monitor,
    record_to_dict,
    group_to_dict,
    apply_fields,
    normalize_asin,
    list_monitors as list_monitors_svc,
)

router = APIRouter(prefix="/api/v1", tags=["竞品监控池"])


# ====== 每日经营简报（第 371 轮）======
#
# ★ 这两个端点**只读**（列表 + 标记已读）。"生成"没有 REST 入口 ——
#   它由 beat 每天早上触发（`modules/monitors/tasks.py`）。
#   手动补跑走 `celery call monitors.generate_daily_briefings`，
#   这是刻意不给按钮的：生成是**全店**动作（一次扫所有监控池），
#   放进 REST 就意味着任何人都能让整个平台重新算一遍。

@router.get("/briefings")
async def list_daily_briefings(
    shop_id: Optional[str] = Depends(get_current_shop_id),
    limit: int = 30,
):
    """简报列表（日期倒序）+ **未读数**。

    ★ 未读数与列表放**同一个响应**而不是两个端点：铃铛每次轮询两个数都要，
      拆成两条会让「徽标说 3 条、点开只有 2 条」成为可能
      （两次请求之间恰好又生成了一份）。同款判据见 `trade` 的列表接口。
    """
    items = await list_briefings_svc(shop_id, limit)
    return {
        "items": items,
        "total": len(items),
        "unread": await count_unread_svc(shop_id),
    }


@router.post("/briefings/{briefing_id}/read")
async def mark_daily_briefing_read(
    briefing_id: str,
    shop_id: Optional[str] = Depends(get_current_shop_id),
):
    """把一条简报标为已读（**幂等**：重复调用不改首次的 `read_at`）。

    ★ 拿不到时回 **404**，不静默成功：静默成功会让前端把徽标清掉，
      而服务端仍是未读 ⇒ 刷新一下又冒出来，用户看到的是
      「点了没反应、还越来越多」。
    ★ 归属条件进**查询**（`mark_read_svc` 内部），不在 Python 里比：
      否则「不存在」与「不属于你」会走出不同路径，那个差异就是一个
      可枚举他人 briefing_id 的存在性探测器。
    """
    row = await mark_read_svc(briefing_id, shop_id)
    if row is None:
        raise HTTPException(status_code=404, detail="简报不存在")
    return row


# ====== 监控池 CRUD ======

@router.get("/monitors")
async def list_monitors(shop_id: Optional[str] = Depends(get_current_shop_id)):
    """监控池列表（按店铺过滤；新增的排在前面）。

    ★ 第 218 轮（P1）：查询收口到 `monitors/service.list_monitors`
      （内部走 `core.library_query` 内核）—— 改前是本 handler 体里的**内联实现**。
    ★ **出参零变化**：仍是 `{"items": [...], "total": N}`；
      默认排序仍是 `created_at` 倒序（逐字不变）。
    """
    rows = await list_monitors_svc(shop_id)
    return {"items": [record_to_dict(r) for r in rows], "total": len(rows)}


@router.get("/monitors/{monitor_id}")
async def get_monitor(monitor_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(MonitorRecord).where(MonitorRecord.id == monitor_id)
        # 无条件挂店铺作用域：缺 X-Shop-ID 时 shop_id=None ⇒ col IS NULL ⇒ 0 行，
        # 走 404（安全失败方向），而非跨租户读。
        q = scoped(q, MonitorRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="监控记录不存在")
    return record_to_dict(r)


@router.post("/monitors", status_code=201)
async def create_monitor_endpoint(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    入池（唯一写入口）。同店铺同 ASIN 已存在则**合并**而非新增。

    合并语义是必须的：候选库开启监控 / 蓝海随手盯 / 监控页手填三条路径会打
    同一个 ASIN，各自 insert 会让池里出现重复行，面板按 ASIN 聚合时数字翻倍。
    """
    if not normalize_asin(payload.get("asin")):
        raise HTTPException(status_code=422, detail="ASIN 不能为空")
    return await upsert_monitor(payload, shop_id=shop_id)


@router.put("/monitors/{monitor_id}")
async def update_monitor(monitor_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(MonitorRecord).where(MonitorRecord.id == monitor_id)
        q = scoped(q, MonitorRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="监控记录不存在")

        apply_fields(r, payload)
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return record_to_dict(r)


@router.delete("/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(MonitorRecord).where(MonitorRecord.id == monitor_id)
        q = scoped(q, MonitorRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="监控记录不存在")
        await session.delete(r)
        await session.commit()
    return {"message": "已移出监控池", "id": monitor_id}


@router.post("/monitors/batch-delete")
async def batch_delete_monitors(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """批量移出监控池。payload = { asins: [...] }"""
    asins = [normalize_asin(a) for a in (payload.get("asins") or []) if a]
    if not asins:
        return {"deleted": 0, "asins": []}
    async with async_session_factory() as session:
        result = await session.execute(
            scoped(delete(MonitorRecord), MonitorRecord, shop_id or '')
            .where(MonitorRecord.asin.in_(asins))
        )
        await session.commit()
    return {"deleted": result.rowcount or 0, "asins": asins}


@router.post("/monitors/batch-upsert")
async def batch_upsert_monitors(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    批量入池。payload = { items: [{asin, title, ...}, ...] }

    返回 added / existing 计数（前端 toast 文案要用）。
    逐条 upsert 而非 bulk insert：需要走同一套判重与合并逻辑。
    """
    items = payload.get("items") or []
    added, existing = 0, 0
    out = []
    for item in items:
        if not isinstance(item, dict) or not normalize_asin(item.get("asin")):
            continue
        asin = normalize_asin(item["asin"])
        already = await _monitor_exists_session(asin, shop_id)
        record = await upsert_monitor(item, shop_id=shop_id)
        if already:
            existing += 1
        else:
            added += 1
        out.append(record)
    return {"added": added, "existing": existing, "items": out}


async def _monitor_exists_session(asin: str, shop_id: Optional[str]) -> bool:
    if not shop_id:
        return False
    async with async_session_factory() as session:
        row = (await session.execute(
            scoped(select(MonitorRecord.id), MonitorRecord, shop_id)
            .where(MonitorRecord.asin == asin)
            .limit(1)
        )).scalar_one_or_none()
    return row is not None


@router.post("/monitors/assign-group")
async def assign_monitors_to_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """批量把 ASIN 归入某分组（追加）。payload = { asins: [...], group_id }"""
    return await _mutate_groups(payload, shop_id, attach=True)


@router.post("/monitors/unassign-group")
async def unassign_monitors_from_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """批量把 ASIN 移出某分组。payload = { asins: [...], group_id }"""
    return await _mutate_groups(payload, shop_id, attach=False)


async def _mutate_groups(payload: dict, shop_id: Optional[str], attach: bool) -> dict:
    asins = [normalize_asin(a) for a in (payload.get("asins") or []) if a]
    group_id = payload.get("group_id")
    if not asins or not group_id:
        return {"updated": 0}
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(MonitorRecord), MonitorRecord, shop_id or '')
            .where(MonitorRecord.asin.in_(asins))
        )).scalars().all()
        for r in rows:
            current = list(r.group_ids or [])
            if attach:
                if group_id not in current:
                    current.append(group_id)
            else:
                current = [g for g in current if g != group_id]
            r.group_ids = current
            r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
    return {"updated": len(rows)}


# ====== 分组 CRUD ======

@router.get("/monitor-groups")
async def list_monitor_groups(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"groups": []}
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(MonitorGroupRecord), MonitorGroupRecord, shop_id)
            .order_by(MonitorGroupRecord.createdAt.asc())
        )).scalars().all()
    return {"groups": [group_to_dict(g) for g in rows]}


@router.post("/monitor-groups", status_code=201)
async def create_monitor_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    g = MonitorGroupRecord(
        id=payload.get("id") or f"mgrp-{int(datetime.utcnow().timestamp() * 1000)}",
        name=(payload.get("name") or "").strip() or "未命名分组",
        kind=payload.get("kind") or "custom",
        color=payload.get("color") or "#1890ff",
        shop_id=shop_id or "",
        createdAt=now,
        updatedAt=now,
    )
    async with async_session_factory() as session:
        session.add(g)
        await session.commit()
        await session.refresh(g)
    return group_to_dict(g)


@router.put("/monitor-groups/{group_id}")
async def update_monitor_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(MonitorGroupRecord).where(MonitorGroupRecord.id == group_id)
        q = scoped(q, MonitorGroupRecord, shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        if "name" in payload and payload["name"]:
            g.name = payload["name"].strip()
        if "kind" in payload and payload["kind"]:
            g.kind = payload["kind"]
        if "color" in payload and payload["color"]:
            g.color = payload["color"]
        g.updatedAt = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(g)
    return group_to_dict(g)


@router.delete("/monitor-groups/{group_id}")
async def delete_monitor_group(group_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    删除分组。**组内 ASIN 不删**，只把它们从该分组摘掉（回落到「未分组」）。
    这是产品约定：删分组是整理动作，不是删除资产。
    """
    async with async_session_factory() as session:
        q = select(MonitorGroupRecord).where(MonitorGroupRecord.id == group_id)
        q = scoped(q, MonitorGroupRecord, shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)

        # 把该分组从所有记录的 group_ids 里摘掉
        rows = (await session.execute(
            scoped(select(MonitorRecord), MonitorRecord, shop_id or '')
        )).scalars().all()
        detached = 0
        for r in rows:
            current = list(r.group_ids or [])
            if group_id in current:
                r.group_ids = [x for x in current if x != group_id]
                r.updated_at = datetime.utcnow().isoformat()
                detached += 1
        await session.commit()
    return {"message": "分组已删除", "id": group_id, "detached": detached}

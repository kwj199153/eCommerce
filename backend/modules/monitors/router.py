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

租户隔离：全部走 `get_current_shop_id`（X-Shop-ID 头）。
列表在无租户上下文时返回空 —— 与 candidates / products / assets 一致。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy import select, delete

from core.database import async_session_factory
from core.tenant.middleware import get_current_shop_id
from modules.monitors.db_model import MonitorRecord, MonitorGroupRecord
from modules.monitors.service import (
    upsert_monitor,
    record_to_dict,
    group_to_dict,
    apply_fields,
    normalize_asin,
)

router = APIRouter(prefix="/api/v1", tags=["竞品监控池"])


# ====== 监控池 CRUD ======

@router.get("/monitors")
async def list_monitors(shop_id: Optional[str] = Depends(get_current_shop_id)):
    """监控池列表（按店铺过滤；新增的排在前面）"""
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(MonitorRecord)
            .where(MonitorRecord.shop_id == shop_id)
            .order_by(MonitorRecord.created_at.desc())
        )).scalars().all()
    items = [record_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/monitors/{monitor_id}")
async def get_monitor(monitor_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(MonitorRecord).where(MonitorRecord.id == monitor_id)
        if shop_id:
            q = q.where(MonitorRecord.shop_id == shop_id)
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
        if shop_id:
            q = q.where(MonitorRecord.shop_id == shop_id)
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
        if shop_id:
            q = q.where(MonitorRecord.shop_id == shop_id)
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
            delete(MonitorRecord)
            .where(MonitorRecord.shop_id == (shop_id or ""))
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
            select(MonitorRecord.id)
            .where(MonitorRecord.shop_id == shop_id)
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
            select(MonitorRecord)
            .where(MonitorRecord.shop_id == (shop_id or ""))
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
            select(MonitorGroupRecord)
            .where(MonitorGroupRecord.shop_id == shop_id)
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
        if shop_id:
            q = q.where(MonitorGroupRecord.shop_id == shop_id)
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
        if shop_id:
            q = q.where(MonitorGroupRecord.shop_id == shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)

        # 把该分组从所有记录的 group_ids 里摘掉
        rows = (await session.execute(
            select(MonitorRecord).where(MonitorRecord.shop_id == (shop_id or ""))
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

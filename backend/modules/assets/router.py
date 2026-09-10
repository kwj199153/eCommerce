"""
素材库管理 API

提供营销素材（图片/视频）的 CRUD、分组管理。
数据源：PostgreSQL（assets / asset_groups 表），唯一权威源。

端点：
GET    /api/v1/assets              - 素材列表
GET    /api/v1/assets/{id}         - 素材详情
POST   /api/v1/assets              - 新增素材（AIGC 归档 / 手动添加共用）
PUT    /api/v1/assets/{id}         - 更新素材
DELETE /api/v1/assets/{id}         - 删除素材
POST   /api/v1/assets/batch-delete - 批量删除
GET    /api/v1/asset-groups        - 分组列表
POST   /api/v1/asset-groups        - 新建分组
PUT    /api/v1/asset-groups/{id}   - 更新分组（重命名/改色）
DELETE /api/v1/asset-groups/{id}   - 删除分组
POST   /api/v1/asset-groups/{id}/move - 分组上移/下移
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime

from sqlalchemy import select
from core.database import async_session_factory
from core.tenant.middleware import get_current_shop_id
from modules.assets.db_model import AssetRecord, AssetGroupRecord

router = APIRouter(prefix="/api/v1", tags=["素材库"])


# ====== 转换工具 ======

def _record_to_dict(r: AssetRecord) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "kind": r.kind,
        "category": r.category,
        "url": r.url,
        "videoUrl": r.videoUrl,
        "thumbnail": r.thumbnail,
        "productId": r.productId,
        "productName": r.productName,
        "asin": r.asin,
        "prompt": r.prompt,
        "source": r.source,
        "width": r.width,
        "height": r.height,
        "tags": r.tags or [],
        "groups": r.groups or [],
        "notes": r.notes,
        "createdAt": r.createdAt,
        "updatedAt": r.updatedAt,
    }


def _group_to_dict(g: AssetGroupRecord) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "color": g.color,
        "createdAt": g.createdAt,
        "updatedAt": g.updatedAt,
    }


# ====== 素材 CRUD ======

@router.get("/assets")
async def list_assets(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(AssetRecord).where(AssetRecord.shop_id == shop_id)
        )).scalars().all()
    items = [_record_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(AssetRecord).where(AssetRecord.id == asset_id)
        if shop_id:
            q = q.where(AssetRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _record_to_dict(r)


@router.post("/assets", status_code=201)
async def create_asset(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    aid = payload.get("id") or f"asset-{int(datetime.utcnow().timestamp() * 1000)}"
    record = AssetRecord(
        id=aid,
        name=payload.get("name") or "未命名素材",
        kind=payload.get("kind") or "image",
        category=payload.get("category") or "other",
        url=payload.get("url") or "",
        videoUrl=payload.get("videoUrl"),
        thumbnail=payload.get("thumbnail"),
        productId=payload.get("productId"),
        productName=payload.get("productName"),
        asin=payload.get("asin"),
        prompt=payload.get("prompt"),
        source=payload.get("source") or "manual",
        width=payload.get("width"),
        height=payload.get("height"),
        tags=payload.get("tags") or [],
        groups=payload.get("groups") or [],
        notes=payload.get("notes") or "",
        shop_id=shop_id or payload.get("shop_id") or "",
        createdAt=payload.get("createdAt") or now,
        updatedAt=now,
    )
    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return _record_to_dict(record)


@router.put("/assets/{asset_id}")
async def update_asset(asset_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(AssetRecord).where(AssetRecord.id == asset_id)
        if shop_id:
            q = q.where(AssetRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="素材不存在")
        for field in [
            "name", "kind", "category", "url", "videoUrl", "thumbnail",
            "productId", "productName", "asin", "prompt", "source",
            "width", "height", "tags", "groups", "notes",
        ]:
            if field in payload:
                setattr(r, field, payload[field])
        r.updatedAt = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _record_to_dict(r)


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(AssetRecord).where(AssetRecord.id == asset_id)
        if shop_id:
            q = q.where(AssetRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="素材不存在")
        await session.delete(r)
        await session.commit()
    return {"message": "素材已删除", "asset_id": asset_id}


@router.post("/assets/batch-delete")
async def batch_delete_assets(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ids = payload.get("ids") or []
    async with async_session_factory() as session:
        for aid in ids:
            q = select(AssetRecord).where(AssetRecord.id == aid)
            if shop_id:
                q = q.where(AssetRecord.shop_id == shop_id)
            r = (await session.execute(q)).scalar_one_or_none()
            if r:
                await session.delete(r)
        await session.commit()
    return {"message": f"已删除 {len(ids)} 个素材", "deleted": len(ids)}


# ====== 分组 CRUD ======

@router.get("/asset-groups")
async def list_groups(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"groups": []}
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(AssetGroupRecord).where(AssetGroupRecord.shop_id == shop_id)
        )).scalars().all()
    return {"groups": [_group_to_dict(g) for g in rows]}


@router.post("/asset-groups", status_code=201)
async def create_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    gid = payload.get("id") or f"asset-group-{int(datetime.utcnow().timestamp() * 1000)}"
    record = AssetGroupRecord(
        id=gid,
        name=payload.get("name") or "新分组",
        color=payload.get("color") or "#1890ff",
        shop_id=shop_id or payload.get("shop_id") or "",
        createdAt=now,
        updatedAt=now,
    )
    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return _group_to_dict(record)


@router.put("/asset-groups/{group_id}")
async def update_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(AssetGroupRecord).where(AssetGroupRecord.id == group_id)
        if shop_id:
            q = q.where(AssetGroupRecord.shop_id == shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        if "name" in payload:
            g.name = payload["name"]
        if "color" in payload:
            g.color = payload["color"]
        g.updatedAt = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(g)
        return _group_to_dict(g)


@router.delete("/asset-groups/{group_id}")
async def delete_group(group_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(AssetGroupRecord).where(AssetGroupRecord.id == group_id)
        if shop_id:
            q = q.where(AssetGroupRecord.shop_id == shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)
        aq = select(AssetRecord)
        if shop_id:
            aq = aq.where(AssetRecord.shop_id == shop_id)
        assets = (await session.execute(aq)).scalars().all()
        for a in assets:
            if a.groups and group_id in a.groups:
                a.groups = [x for x in a.groups if x != group_id]
        await session.commit()
    return {"message": "分组已删除", "group_id": group_id}


@router.post("/asset-groups/{group_id}/move")
async def move_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    direction = payload.get("direction") or "down"
    async with async_session_factory() as session:
        q = select(AssetGroupRecord)
        if shop_id:
            q = q.where(AssetGroupRecord.shop_id == shop_id)
        rows = (await session.execute(
            q.order_by(AssetGroupRecord.createdAt)
        )).scalars().all()
        idx = next((i for i, g in enumerate(rows) if g.id == group_id), -1)
        if idx == -1:
            raise HTTPException(status_code=404, detail="分组不存在")
        target = idx - 1 if direction == "up" else idx + 1
        if target < 0 or target >= len(rows):
            return {"message": "已在边界"}
        rows[idx], rows[target] = rows[target], rows[idx]
        t = datetime.utcnow().timestamp()
        for i, g in enumerate(rows):
            g.updatedAt = datetime.utcfromtimestamp(t + i).isoformat()
        await session.commit()
    return {"message": "排序已更新"}

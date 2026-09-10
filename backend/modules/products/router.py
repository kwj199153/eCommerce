"""
产品库管理 API（SPU + SKU 分表）

提供 SPU（主产品）/ SKU（具体规格）的 CRUD、分组管理、批量导入。
数据源：PostgreSQL（spus / skus / product_groups 表），唯一权威源。

端点：
GET    /api/v1/spus                 - SPU 列表
GET    /api/v1/spus/{id}            - SPU 详情
POST   /api/v1/spus                 - 新增 SPU（可同时带 skus）
PUT    /api/v1/spus/{id}            - 更新 SPU
DELETE /api/v1/spus/{id}            - 删除 SPU（级联删除其 SKU）

GET    /api/v1/skus                 - SKU 列表（可 ?spu_id= 过滤）
GET    /api/v1/skus/{id}            - SKU 详情
POST   /api/v1/skus                 - 新增 SKU
PUT    /api/v1/skus/{id}            - 更新 SKU
DELETE /api/v1/skus/{id}            - 删除 SKU
PATCH  /api/v1/skus/{id}/listing    - 写回 SKU 的 Listing 内容

GET    /api/v1/products             - 聚合列表（SPU 树 + SKU 平铺，兼容前端旧消费方）
GET    /api/v1/products/{id}        - 聚合详情（SPU 带 skus children）

POST   /api/v1/products/batch-delete - 批量删除（兼容）

分组端点（product-groups）保持不变。
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select
from core.database import async_session_factory
from core.tenant.middleware import get_current_shop_id
from modules.products.db_model import SpuRecord, SkuRecord, ProductGroupRecord

router = APIRouter(prefix="/api/v1", tags=["产品库"])


# ====== 转换工具 ======

def _spu_to_dict(r: SpuRecord) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "brand": r.brand,
        "category": r.category,
        "sub_category": r.sub_category,
        "spu_theme": r.spu_theme,
        "keywords": r.keywords or [],
        "selling_points": r.selling_points,
        "description": r.description,
        "main_image": r.main_image,
        "images": r.images or [],
        "spu_common": r.spu_common,
        "shop_id": r.shop_id,
        "tags": r.tags or [],
        "notes": r.notes,
        "status": r.status,
        "groups": r.groups or [],
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def _sku_to_dict(r: SkuRecord) -> dict:
    return {
        "id": r.id,
        "spu_id": r.spu_id,
        "spec_value": r.spec_value,
        "asin": r.asin,
        "sku_code": r.sku_code,
        "price": r.price,
        "cost": r.cost,
        "currency": r.currency,
        "site": r.site,
        "fba_stock": r.fba_stock,
        "fbm_stock": r.fbm_stock,
        "fulfillment_type": r.fulfillment_type,
        "bsr": r.bsr,
        "rating": r.rating,
        "review_count": r.review_count,
        "daily_sales_avg": r.daily_sales_avg,
        "roi": r.roi,
        "margin": r.margin,
        "listing_status": r.listing_status,
        "generated_title": r.generated_title,
        "generated_bullets": r.generated_bullets or [],
        "generated_a_plus": r.generated_a_plus,
        "seo_score": r.seo_score,
        "generated_at": r.generated_at,
        "listing_version": r.listing_version,
        "listing_history": r.listing_history or [],
        "has_a_plus": r.has_a_plus,
        "has_video": r.has_video,
        "rating_breakdown": r.rating_breakdown,
        "tags": r.tags or [],
        "notes": r.notes,
        "status": r.status,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def _group_to_dict(g: ProductGroupRecord) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "color": g.color,
        "createdAt": g.createdAt,
        "updatedAt": g.updatedAt,
    }


# ====== SPU CRUD ======

@router.get("/spus")
async def list_spus(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(SpuRecord).where(SpuRecord.shop_id == shop_id)
        )).scalars().all()
    items = [_spu_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/spus/{spu_id}")
async def get_spu(spu_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SpuRecord).where(SpuRecord.id == spu_id)
        if shop_id:
            q = q.where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="SPU 不存在")
    return _spu_to_dict(r)


@router.post("/spus", status_code=201)
async def create_spu(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    spu_id = payload.get("id") or f"spu-{int(datetime.utcnow().timestamp() * 1000)}"
    record = SpuRecord(
        id=spu_id,
        title=payload.get("title") or "未命名主产品",
        brand=payload.get("brand") or "",
        category=payload.get("category") or "other",
        sub_category=payload.get("sub_category") or "",
        spu_theme=payload.get("spu_theme"),
        keywords=payload.get("keywords") or [],
        selling_points=payload.get("selling_points"),
        description=payload.get("description"),
        main_image=payload.get("main_image") or "",
        images=payload.get("images") or [],
        spu_common=payload.get("spu_common"),
        shop_id=shop_id or payload.get("shop_id") or "",
        tags=payload.get("tags") or [],
        notes=payload.get("notes") or "",
        status=payload.get("status") or "active",
        groups=payload.get("groups") or [],
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )
    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return _spu_to_dict(record)


@router.put("/spus/{spu_id}")
async def update_spu(spu_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SpuRecord).where(SpuRecord.id == spu_id)
        if shop_id:
            q = q.where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="SPU 不存在")

        for field in [
            "title", "brand", "category", "sub_category", "spu_theme",
            "keywords", "selling_points", "description",
            "main_image", "images", "spu_common",
            "tags", "notes", "status", "groups",
        ]:
            if field in payload:
                setattr(r, field, payload[field])
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _spu_to_dict(r)


@router.delete("/spus/{spu_id}")
async def delete_spu(spu_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SpuRecord).where(SpuRecord.id == spu_id)
        if shop_id:
            q = q.where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="SPU 不存在")
        # 级联删除其下 SKU
        skus = (await session.execute(
            select(SkuRecord).where(SkuRecord.spu_id == spu_id)
        )).scalars().all()
        for s in skus:
            await session.delete(s)
        await session.delete(r)
        await session.commit()
    return {"message": "SPU 及其 SKU 已删除", "spu_id": spu_id}


# ====== SKU CRUD ======

@router.get("/skus")
async def list_skus(spu_id: Optional[str] = Query(None), shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        # SKU 通过 spu_id 归属 SPU，join 过滤 shop_id
        q = select(SkuRecord).join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(
            SpuRecord.shop_id == shop_id
        )
        if spu_id:
            q = q.where(SkuRecord.spu_id == spu_id)
        rows = (await session.execute(q)).scalars().all()
    items = [_sku_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/skus/{sku_id}")
async def get_sku(sku_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SkuRecord).where(SkuRecord.id == sku_id)
        if shop_id:
            q = q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="SKU 不存在")
    return _sku_to_dict(r)


@router.post("/skus", status_code=201)
async def create_sku(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    sku_id = payload.get("id") or f"sku-{int(datetime.utcnow().timestamp() * 1000)}"
    # 校验 SPU 归属（防止跨店铺写入 SKU）
    spu_id = payload.get("spu_id") or ""
    if shop_id and spu_id:
        async with async_session_factory() as session:
            spu = (await session.execute(
                select(SpuRecord).where(SpuRecord.id == spu_id, SpuRecord.shop_id == shop_id)
            )).scalar_one_or_none()
            if not spu:
                raise HTTPException(status_code=404, detail="所属 SPU 不存在或不属于当前店铺")
    record = SkuRecord(
        id=sku_id,
        spu_id=spu_id,
        spec_value=payload.get("spec_value"),
        asin=payload.get("asin") or "",
        sku_code=payload.get("sku_code") or f"SKU-{sku_id}",
        price=payload.get("price") or 0,
        cost=payload.get("cost") or 0,
        currency=payload.get("currency") or "USD",
        site=payload.get("site"),
        fba_stock=payload.get("fba_stock") or 0,
        fbm_stock=payload.get("fbm_stock") or 0,
        fulfillment_type=payload.get("fulfillment_type") or "FBA",
        bsr=payload.get("bsr"),
        rating=payload.get("rating") or 0,
        review_count=payload.get("review_count") or 0,
        daily_sales_avg=payload.get("daily_sales_avg") or 0,
        roi=payload.get("roi") or 0,
        margin=payload.get("margin") or 0,
        listing_status=payload.get("listing_status") or "draft",
        generated_title=payload.get("generated_title"),
        generated_bullets=payload.get("generated_bullets") or [],
        generated_a_plus=payload.get("generated_a_plus"),
        seo_score=payload.get("seo_score"),
        generated_at=payload.get("generated_at"),
        listing_version=payload.get("listing_version") or 1,
        listing_history=payload.get("listing_history") or [],
        has_a_plus=payload.get("has_a_plus") or False,
        has_video=payload.get("has_video") or False,
        rating_breakdown=payload.get("rating_breakdown"),
        tags=payload.get("tags") or [],
        notes=payload.get("notes") or "",
        status=payload.get("status") or "active",
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )
    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return _sku_to_dict(record)


@router.put("/skus/{sku_id}")
async def update_sku(sku_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SkuRecord).where(SkuRecord.id == sku_id)
        if shop_id:
            q = q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="SKU 不存在")

        for field in [
            "spu_id", "spec_value", "asin", "sku_code",
            "price", "cost", "currency", "site",
            "fba_stock", "fbm_stock", "fulfillment_type",
            "bsr", "rating", "review_count", "daily_sales_avg", "roi", "margin",
            "listing_status",
            "generated_title", "generated_bullets", "generated_a_plus",
            "seo_score", "generated_at", "listing_version", "listing_history",
            "has_a_plus", "has_video", "rating_breakdown",
            "tags", "notes", "status",
        ]:
            if field in payload:
                setattr(r, field, payload[field])
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _sku_to_dict(r)


@router.delete("/skus/{sku_id}")
async def delete_sku(sku_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(SkuRecord).where(SkuRecord.id == sku_id)
        if shop_id:
            q = q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="SKU 不存在")
        await session.delete(r)
        await session.commit()
    return {"message": "SKU 已删除", "sku_id": sku_id}


@router.patch("/skus/{sku_id}/listing")
async def update_sku_listing(sku_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """Listing 优化工具写回：增量更新 SKU 标题/五点/A+/SEO，维护历史版本"""
    async with async_session_factory() as session:
        q = select(SkuRecord).where(SkuRecord.id == sku_id)
        if shop_id:
            q = q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="SKU 不存在")

        current_version = r.listing_version or 0
        history = list(r.listing_history or [])

        if r.generated_title:
            history.insert(0, {
                "version": current_version,
                "title": r.generated_title,
                "bullets": r.generated_bullets or [],
                "updated_at": r.generated_at or datetime.utcnow().isoformat(),
            })
            if len(history) > 3:
                history = history[:3]

        if "generated_title" in payload:
            r.generated_title = payload["generated_title"]
        if "generated_bullets" in payload:
            r.generated_bullets = payload["generated_bullets"]
        if "generated_a_plus" in payload:
            r.generated_a_plus = payload["generated_a_plus"]
        if "seo_score" in payload:
            r.seo_score = payload["seo_score"]
        if "generated_at" in payload:
            r.generated_at = payload["generated_at"]

        r.listing_version = (payload.get("version", current_version)) + 1
        r.listing_history = history
        if r.generated_title and r.listing_status == "draft":
            r.listing_status = "ready"
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _sku_to_dict(r)


# ====== 聚合端点（兼容旧 /products 消费方） ======

@router.get("/products")
async def list_products_aggregated(shop_id: Optional[str] = Depends(get_current_shop_id)):
    """返回 SPU 树（带 skus children）+ 独立 SKU 平铺，兼容前端旧消费方。"""
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        spus = (await session.execute(
            select(SpuRecord).where(SpuRecord.shop_id == shop_id)
        )).scalars().all()
        skus = (await session.execute(
            select(SkuRecord).join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        )).scalars().all()
    sku_map = {}
    for s in skus:
        sku_map.setdefault(s.spu_id, []).append(s)

    items: List[dict] = []
    for spu in spus:
        d = _spu_to_dict(spu)
        d["is_spu"] = True
        d["skus"] = [_sku_to_dict(s) for s in sku_map.get(spu.id, [])]
        items.append(d)
    return {"items": items, "total": len(items)}


@router.get("/products/{product_id}")
async def get_product_aggregated(product_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """按 id 查 SPU 或 SKU，返回带类型标记的聚合详情。"""
    async with async_session_factory() as session:
        spu_q = select(SpuRecord).where(SpuRecord.id == product_id)
        if shop_id:
            spu_q = spu_q.where(SpuRecord.shop_id == shop_id)
        spu = (await session.execute(spu_q)).scalar_one_or_none()
        if spu:
            d = _spu_to_dict(spu)
            d["is_spu"] = True
            skus = (await session.execute(
                select(SkuRecord).where(SkuRecord.spu_id == product_id)
            )).scalars().all()
            d["skus"] = [_sku_to_dict(s) for s in skus]
            return d
        sku_q = select(SkuRecord).where(SkuRecord.id == product_id)
        if shop_id:
            sku_q = sku_q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
        sku = (await session.execute(sku_q)).scalar_one_or_none()
        if sku:
            d = _sku_to_dict(sku)
            d["is_spu"] = False
            return d
    raise HTTPException(status_code=404, detail="产品不存在")


@router.post("/products/batch-delete")
async def batch_delete_products(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ids = payload.get("ids") or []
    async with async_session_factory() as session:
        for pid in ids:
            spu_q = select(SpuRecord).where(SpuRecord.id == pid)
            if shop_id:
                spu_q = spu_q.where(SpuRecord.shop_id == shop_id)
            spu = (await session.execute(spu_q)).scalar_one_or_none()
            if spu:
                skus = (await session.execute(
                    select(SkuRecord).where(SkuRecord.spu_id == pid)
                )).scalars().all()
                for s in skus:
                    await session.delete(s)
                await session.delete(spu)
                continue
            sku_q = select(SkuRecord).where(SkuRecord.id == pid)
            if shop_id:
                sku_q = sku_q.join(SpuRecord, SkuRecord.spu_id == SpuRecord.id).where(SpuRecord.shop_id == shop_id)
            sku = (await session.execute(sku_q)).scalar_one_or_none()
            if sku:
                await session.delete(sku)
        await session.commit()
    return {"message": f"已删除 {len(ids)} 个产品", "deleted": len(ids)}


# ====== 分组 CRUD ======

@router.get("/product-groups")
async def list_groups(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"groups": []}
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(ProductGroupRecord).where(ProductGroupRecord.shop_id == shop_id)
        )).scalars().all()
    return {"groups": [_group_to_dict(g) for g in rows]}


@router.post("/product-groups", status_code=201)
async def create_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    gid = payload.get("id") or f"group-{int(datetime.utcnow().timestamp() * 1000)}"
    record = ProductGroupRecord(
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


@router.put("/product-groups/{group_id}")
async def update_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(ProductGroupRecord).where(ProductGroupRecord.id == group_id)
        if shop_id:
            q = q.where(ProductGroupRecord.shop_id == shop_id)
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


@router.delete("/product-groups/{group_id}")
async def delete_group(group_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(ProductGroupRecord).where(ProductGroupRecord.id == group_id)
        if shop_id:
            q = q.where(ProductGroupRecord.shop_id == shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)
        # 从当前店铺的 SPU 的 groups 里移除该分组 id
        spu_q = select(SpuRecord)
        if shop_id:
            spu_q = spu_q.where(SpuRecord.shop_id == shop_id)
        spus = (await session.execute(spu_q)).scalars().all()
        for p in spus:
            if p.groups and group_id in p.groups:
                p.groups = [x for x in p.groups if x != group_id]
        await session.commit()
    return {"message": "分组已删除", "group_id": group_id}


@router.post("/product-groups/{group_id}/move")
async def move_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """分组上移/下移。direction: 'up' | 'down'"""
    direction = payload.get("direction") or "down"
    async with async_session_factory() as session:
        q = select(ProductGroupRecord)
        if shop_id:
            q = q.where(ProductGroupRecord.shop_id == shop_id)
        rows = (await session.execute(
            q.order_by(ProductGroupRecord.createdAt)
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

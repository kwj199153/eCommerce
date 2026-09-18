"""
候选选品库管理 API

提供候选选品（草稿池）的 CRUD、分组管理、评审状态流转、评审通过迁移到产品库。
数据源：PostgreSQL（candidates / candidate_groups 表），唯一权威源。

端点：
GET    /api/v1/candidates                    - 候选列表
GET    /api/v1/candidates/{id}               - 候选详情
POST   /api/v1/candidates                    - 新增候选（选品分析师产出）
PUT    /api/v1/candidates/{id}               - 更新候选
PATCH  /api/v1/candidates/{id}/review        - 评审状态流转（pending/under_review/rejected 等）
POST   /api/v1/candidates/{id}/approve       - 评审通过：复制到自有产品库(草稿)，候选保留为已通过基线
POST   /api/v1/candidates/{id}/monitor       - 竞品监控员回填数据快照
DELETE /api/v1/candidates/{id}               - 删除候选
POST   /api/v1/candidates/batch-delete       - 批量删除
GET    /api/v1/candidate-groups              - 分组列表
POST   /api/v1/candidate-groups              - 新建分组
PUT    /api/v1/candidate-groups/{id}         - 更新分组
DELETE /api/v1/candidate-groups/{id}         - 删除分组
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime

from sqlalchemy import select
from core.database import async_session_factory
from core.tenant.middleware import get_current_shop_id
from core.tenant.scoping import scoped
from modules.candidates.db_model import CandidateRecord, CandidateGroupRecord
from modules.candidates.service import create_candidate, record_to_dict as _record_to_dict
from modules.products.db_model import SpuRecord

router = APIRouter(prefix="/api/v1", tags=["候选选品库"])


# ====== 转换工具 ======
# 注：`_record_to_dict` 已下沉到 modules/candidates/service.py，
# 供 REST 路由与选品 Agent 的 save_candidate 工具共用（此处以别名导入）。


def _group_to_dict(g: CandidateGroupRecord) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "color": g.color,
        "createdAt": g.createdAt,
        "updatedAt": g.updatedAt,
    }


# ====== 候选 CRUD ======

@router.get("/candidates")
async def list_candidates(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"items": [], "total": 0}
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(CandidateRecord), CandidateRecord, shop_id)
            .order_by(CandidateRecord.updated_at.desc())
        )).scalars().all()
    items = [_record_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="候选不存在")
    return _record_to_dict(r)


@router.post("/candidates", status_code=201)
async def create_candidate_endpoint(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """新增候选（选品分析师产出）。写逻辑在 modules/candidates/service.create_candidate。"""
    return await create_candidate(payload, shop_id=shop_id)


@router.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="候选不存在")

        for field in [
            "asin", "sku", "title", "brand", "category", "sub_category",
            "price", "currency", "site",
            "estimated_monthly_sales", "review_count", "rating",
            "bsr", "bsr_category", "listed_date",
            "roi_estimated", "margin", "blue_ocean_score", "overall_listing_score",
            "keywords", "competitor_asins", "selling_points",
            "main_image", "images", "source",
            "review_status", "review_notes", "reviewed_at", "reviewed_by",
            "monitor_data", "last_monitored_at",
            "tags", "notes", "groups",
        ]:
            if field in payload:
                setattr(r, field, payload[field])
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _record_to_dict(r)


@router.patch("/candidates/{candidate_id}/review")
async def review_candidate(candidate_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """评审状态流转：payload = { review_status, review_notes?, reviewed_by? }"""
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="候选不存在")

        status = payload.get("review_status")
        if status and status in ("pending", "under_review", "approved", "rejected"):
            r.review_status = status
        if "review_notes" in payload:
            r.review_notes = payload["review_notes"]
        if "reviewed_by" in payload:
            r.reviewed_by = payload["reviewed_by"]
        r.reviewed_at = datetime.utcnow().isoformat()
        r.updated_at = r.reviewed_at
        await session.commit()
        await session.refresh(r)
        return _record_to_dict(r)


@router.post("/candidates/{candidate_id}/monitor")
async def monitor_candidate(candidate_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """竞品监控员回填数据快照：payload = { monitor_data, last_monitored_at? }"""
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="候选不存在")
        r.monitor_data = payload.get("monitor_data", r.monitor_data)
        r.last_monitored_at = payload.get("last_monitored_at") or datetime.utcnow().isoformat()
        r.updated_at = datetime.utcnow().isoformat()
        await session.commit()
        await session.refresh(r)
        return _record_to_dict(r)


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(candidate_id: str, payload: dict = None, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """
    评审通过：复制到自有产品库（status='draft' 待完善 Listing）作为上架物料档案，
    候选本身保留并标记 approved，作为不可覆盖的原始评估基线。原子事务。
    """
    payload = payload or {}
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="候选不存在")

        # 从候选推导 ROI
        roi = r.roi_estimated or 20

        now = datetime.utcnow().isoformat()
        spu_id = payload.get("product_id") or f"spu-{int(datetime.utcnow().timestamp() * 1000)}"
        # 选品阶段评估的是整个主产品（SPU）：审核通过后入库为「SPU 草稿」，
        # 不预建 SKU，运营后续在产品库内补 SKU。SPU 无 ASIN、不可售。
        product = SpuRecord(
            id=spu_id,
            title=r.title,
            brand=r.brand,
            category=r.category,
            sub_category=r.sub_category,
            spu_theme=None,
            keywords=r.keywords or [],
            selling_points=r.selling_points,
            description=None,
            main_image=r.main_image,
            images=r.images or [],
            spu_common={
                "brand": r.brand,
                "category": r.category,
                "keywords": r.keywords or [],
                "selling_points": r.selling_points or "",
                "bullets": [],
                "a_plus": None,
            },
            shop_id=r.shop_id,
            tags=(r.tags or []) + ["蓝海挖掘", f"评分:{r.blue_ocean_score}", "SPU主产品"],
            notes=f"来源：候选选品库评审通过（SPU 主产品）| 蓝海评分：{r.blue_ocean_score} | 预估月销：{r.estimated_monthly_sales} | ROI：{roi}% | 请在产品库补充 SKU",
            status="draft",
            groups=r.groups or [],
            created_at=now,
            updated_at=now,
        )
        session.add(product)
        # 评审通过：保留候选作为「原始评估基线」存档（不再删除），标记 approved，
        # 与自有产品库的上架档案形成双库并存：选品库=评估基线，产品库=上架物料基线
        r.review_status = "approved"
        r.reviewed_at = now
        r.updated_at = now
        await session.commit()

    # SPU → dict 的唯一真源在 products/router.py（公开符号，勿再取私有名）
    from modules.products.router import spu_to_dict
    return {
        "message": "评审通过，已复制到自有产品库，候选保留为已通过评估基线",
        "candidate_id": candidate_id,
        "product": spu_to_dict(product),
    }


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
        if shop_id:
            q = scoped(q, CandidateRecord, shop_id)
        r = (await session.execute(q)).scalar_one_or_none()
        if not r:
            raise HTTPException(status_code=404, detail="候选不存在")
        await session.delete(r)
        await session.commit()
    return {"message": "候选已删除", "candidate_id": candidate_id}


@router.post("/candidates/batch-delete")
async def batch_delete_candidates(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    ids = payload.get("ids") or []
    async with async_session_factory() as session:
        for cid in ids:
            q = select(CandidateRecord).where(CandidateRecord.id == cid)
            if shop_id:
                q = scoped(q, CandidateRecord, shop_id)
            r = (await session.execute(q)).scalar_one_or_none()
            if r:
                await session.delete(r)
        await session.commit()
    return {"message": f"已删除 {len(ids)} 个候选", "deleted": len(ids)}


# ====== 分组 CRUD ======

@router.get("/candidate-groups")
async def list_groups(shop_id: Optional[str] = Depends(get_current_shop_id)):
    if not shop_id:
        return {"groups": []}
    async with async_session_factory() as session:
        rows = (await session.execute(
            scoped(select(CandidateGroupRecord), CandidateGroupRecord, shop_id)
        )).scalars().all()
    return {"groups": [_group_to_dict(g) for g in rows]}


@router.post("/candidate-groups", status_code=201)
async def create_group(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    now = datetime.utcnow().isoformat()
    gid = payload.get("id") or f"cgroup-{int(datetime.utcnow().timestamp() * 1000)}"
    record = CandidateGroupRecord(
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


@router.put("/candidate-groups/{group_id}")
async def update_group(group_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateGroupRecord).where(CandidateGroupRecord.id == group_id)
        if shop_id:
            q = scoped(q, CandidateGroupRecord, shop_id)
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


@router.delete("/candidate-groups/{group_id}")
async def delete_group(group_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateGroupRecord).where(CandidateGroupRecord.id == group_id)
        if shop_id:
            q = scoped(q, CandidateGroupRecord, shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)
        # 从当前店铺候选的 groups 里移除该分组 id
        cq = select(CandidateRecord)
        if shop_id:
            cq = scoped(cq, CandidateRecord, shop_id)
        candidates = (await session.execute(cq)).scalars().all()
        for c in candidates:
            if c.groups and group_id in c.groups:
                c.groups = [x for x in c.groups if x != group_id]
        await session.commit()
    return {"message": "分组已删除", "group_id": group_id}

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
from modules.candidates.service import (
    CandidateQueryError,
    approve_candidate as _approve_candidate,
    count_candidates as _count_candidates,
    create_candidate,
    get_candidate as _get_candidate,
    list_candidates as _list_candidates,
    record_to_dict as _record_to_dict,
    review_candidate as _review_candidate,
)

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
async def list_candidates(
    shop_id: Optional[str] = Depends(get_current_shop_id),
    order_by: Optional[str] = None,
    limit: Optional[int] = None,
    review_status: Optional[str] = None,
):
    """候选列表（`?order_by=&limit=&review_status=`）。

    ★ 第 205 轮：查询落到 `service.list_candidates`（**唯一实现**）。
      跨 Agent 共用的 `list_candidates` 工具走同一个函数
      —— 此前这里是全仓唯一一份「读候选库」的查询，而工具没有落脚点，
      各自实现就会变成「同一判定两份实现 ⇒ 至少一份永远测不到」。

    ★ 第 216 轮两处修正：
      1. **`total` 改真实总数**（`service.count_candidates`，去重后 + 过滤后）。
         改前是 `len(items)` = **`LIMIT` 之后**的长度 ——
         不传 `limit` 时恰好相等所以看不出问题，一旦带 `limit` 就撒谎
         （本库 11 条时 `limit=1` 报 `total=1`）。前端不传参，行为不变。
      2. **暴露排序**（`order_by`）。改前排序硬编码 `updated_at` 倒序，
         而 `limit` 兼表分页与 Top-N ⇒ 「销量前 3」拿到的是「最近更新的 3 条」
         （**截断口径 ≠ 排序口径**，实测真前 3 从未进入候选集）。
      ★ 非法 `order_by` / `review_status` → **400 + 可读原因**，
        不再静默退化成默认排序或空列表
        （空列表会把「真的没有」与「你传错了」压成同一个结果）。
      ★ 三个参数都不传时响应与改前一致，只多一层「按 ASIN 去重」。
    """
    try:
        items = await _list_candidates(
            shop_id, limit=limit, review_status=review_status, order_by=order_by
        )
        total = await _count_candidates(shop_id, review_status=review_status)
    except CandidateQueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"items": items, "total": total}


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """候选详情。

    ★ 第 205 轮：查询落到 `service.get_candidate`（**唯一实现**）。
      Agent 的 `get_candidate` 工具走同一个函数 —— 此前本 handler 是全仓
      唯一一份「按 id 读候选」的实现，工具没有落脚点
      （第 204 轮盘点出的「老板点名：获取选品」缺口）。
    """
    item = await _get_candidate(candidate_id, shop_id)
    if item is None:
        raise HTTPException(status_code=404, detail="候选不存在")
    return item


@router.post("/candidates", status_code=201)
async def create_candidate_endpoint(payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """新增候选（选品分析师产出）。写逻辑在 modules/candidates/service.create_candidate。"""
    return await create_candidate(payload, shop_id=shop_id)


@router.put("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
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
    """评审状态流转：payload = { review_status, review_notes?, reviewed_by? }

    ★ 第 205 轮：流转逻辑下沉到 `service.review_candidate`（**唯一实现**），
      Agent 的 `review_candidate` 工具共用同一条路径。
      ★ 只把 payload 里**真正出现过的键**透传下去（`**{}` 展开）——
        这样「键不在 payload 里」=「不动该字段」，与改前的 `"k" in payload`
        语义**逐字一致**；直接传 `payload.get(k)` 会把「改成 None」和
        「不动」混成一件事（静默改契约）。
    """
    item = await _review_candidate(
        candidate_id,
        shop_id,
        **{
            k: payload[k]
            for k in ("review_status", "review_notes", "reviewed_by")
            if k in payload
        },
    )
    if item is None:
        raise HTTPException(status_code=404, detail="候选不存在")
    return item


@router.post("/candidates/{candidate_id}/monitor")
async def monitor_candidate(candidate_id: str, payload: dict, shop_id: Optional[str] = Depends(get_current_shop_id)):
    """竞品监控员回填数据快照：payload = { monitor_data, last_monitored_at? }"""
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
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
    """评审通过：候选 -> 自有产品库（**唯一通道**）。

    ★ 第 205 轮：整段逻辑下沉到 `service.approve_candidate`（**唯一实现**），
      Agent 的 `approve_candidate` 工具共用同一条路径 —— 此前本 handler 是
      全仓唯一实现，Agent 够不着 ⇒ 选品闭环在 Agent 侧断掉
      （第 204 轮老板点名：「入产品库」缺工具）。
    ★ 语义**一字未改**：仍建 `status='draft'` 的 SPU 草稿（不预建 SKU）、
      候选保留并标记 approved、同一事务原子提交。
    """
    payload = payload or {}
    result = await _approve_candidate(
        candidate_id, shop_id, product_id=payload.get("product_id")
    )
    if result is None:
        raise HTTPException(status_code=404, detail="候选不存在")
    return result


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(candidate_id: str, shop_id: Optional[str] = Depends(get_current_shop_id)):
    async with async_session_factory() as session:
        q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
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
        q = scoped(q, CandidateGroupRecord, shop_id)
        g = (await session.execute(q)).scalar_one_or_none()
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        await session.delete(g)
        # 从当前店铺候选的 groups 里移除该分组 id
        cq = select(CandidateRecord)
        cq = scoped(cq, CandidateRecord, shop_id)
        candidates = (await session.execute(cq)).scalars().all()
        for c in candidates:
            if c.groups and group_id in c.groups:
                c.groups = [x for x in c.groups if x != group_id]
        await session.commit()
    return {"message": "分组已删除", "group_id": group_id}

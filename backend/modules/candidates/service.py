"""
候选选品库 - 业务逻辑层

把候选的**写入口**从 router 抽出，供两处复用：
  1. REST 路由：`POST /api/v1/candidates`
  2. 选品 Agent 的 `save_candidate` 工具（对话里「把这个品加进选品库」）

设计动因：原先唯一写入口是 REST 路由，Agent 想入库只能「HTTP 调自己」，
于是「保存到选品库」长期只是前端卡片上的一个按钮，**对话完全够不到**。
把写逻辑下沉到 service 后，路由与 Agent 工具共用同一条路径与同一套默认值。
"""

from datetime import datetime
from typing import Optional

from core.database import async_session_factory
from core.tenant.scoping import scoped
from modules.candidates.db_model import CandidateRecord


# ====== 字段契约（与前端选品库面板严格对齐）======
#
# 面板是「手动录入候选选品」弹窗 + 蓝海结果卡的「保存到选品库」：
#   - 必填：ASIN、标题（弹窗上的 required 标记）
#   - 可选：售价 / 预估月销 / 蓝海评分 / ROI / 备注 —— 不填就用默认值
#   - 蓝海链路唯一要人操作的「选分组」是可选项，不选也能入库
#
# 对话入库是同一套流程的「免填版」：
#   - 必填缺失 → **多轮追问补齐**（缺什么问什么）
#   - 可选缺失 → **后台按默认值自动补**，不为可选字段打扰老板
# 所以必填清单必须单点定义在这里，别再让前后端各记一份。

CANDIDATE_REQUIRED_FIELDS = ("asin", "title")

# 字段中文名：追问文案给老板看，别把 `asin` 这种字段名直接甩出去
CANDIDATE_FIELD_LABELS = {
    "asin": "ASIN",
    "title": "商品标题",
    "price": "售价(USD)",
    "estimated_monthly_sales": "预估月销",
    "blue_ocean_score": "蓝海评分",
    "roi_estimated": "ROI 估算(%)",
    "notes": "备注",
}


def missing_required_fields(payload: dict) -> list:
    """
    返回 payload 里缺失的必填字段（对齐面板 required）。

    可选字段一律不算缺 —— 面板对可选字段就是「不填走默认值」，
    对话入库同样由 `build_candidate_record` 补默认值，不该为此打扰用户。
    """
    missing = []
    for field in CANDIDATE_REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def describe_missing_fields(missing: list) -> str:
    """缺失字段 → 中文提示（如「ASIN、商品标题」）"""
    return "、".join(CANDIDATE_FIELD_LABELS.get(f, f) for f in missing)


def record_to_dict(r: CandidateRecord) -> dict:
    """ORM → dict（字段名与前端 CandidateItem 对齐）"""
    return {
        "id": r.id,
        "asin": r.asin,
        "sku": r.sku,
        "title": r.title,
        "brand": r.brand,
        "category": r.category,
        "sub_category": r.sub_category,
        "price": r.price,
        "currency": r.currency,
        "site": r.site,
        "estimated_monthly_sales": r.estimated_monthly_sales,
        "review_count": r.review_count,
        "rating": r.rating,
        "bsr": r.bsr,
        "bsr_category": r.bsr_category,
        "listed_date": r.listed_date,
        "roi_estimated": r.roi_estimated,
        "margin": r.margin,
        "blue_ocean_score": r.blue_ocean_score,
        "overall_listing_score": r.overall_listing_score,
        "keywords": r.keywords or [],
        "competitor_asins": r.competitor_asins or [],
        "selling_points": r.selling_points,
        "main_image": r.main_image,
        "images": r.images or [],
        "source": r.source,
        "review_status": r.review_status,
        "review_notes": r.review_notes,
        "reviewed_at": r.reviewed_at,
        "reviewed_by": r.reviewed_by,
        "monitor_data": r.monitor_data,
        "last_monitored_at": r.last_monitored_at,
        "shop_id": r.shop_id,
        "tags": r.tags or [],
        "notes": r.notes,
        "groups": r.groups or [],
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def build_candidate_record(payload: dict, shop_id: Optional[str] = None) -> CandidateRecord:
    """
    由 payload 构造 CandidateRecord（不落库）。

    payload 字段**全部可选**，缺省值在此集中收敛，避免出现
    「路由填一套默认值、Agent 工具填另一套」的语义分裂。
    """
    now = datetime.utcnow().isoformat()
    cid = payload.get("id") or f"cand-{int(datetime.utcnow().timestamp() * 1000)}"

    return CandidateRecord(
        id=cid,
        asin=payload.get("asin") or "",
        sku=payload.get("sku") or f"SKU-CAND-{cid}",
        title=payload.get("title") or "未命名候选",
        brand=payload.get("brand") or "",
        category=payload.get("category") or "other",
        sub_category=payload.get("sub_category") or "",
        price=payload.get("price") or 0,
        currency=payload.get("currency") or "USD",
        site=payload.get("site"),
        estimated_monthly_sales=payload.get("estimated_monthly_sales") or 0,
        review_count=payload.get("review_count") or 0,
        rating=payload.get("rating") or 0,
        bsr=payload.get("bsr"),
        bsr_category=payload.get("bsr_category"),
        listed_date=payload.get("listed_date"),
        roi_estimated=payload.get("roi_estimated") or 0,
        margin=payload.get("margin") or 0,
        blue_ocean_score=payload.get("blue_ocean_score") or 0,
        overall_listing_score=payload.get("overall_listing_score"),
        keywords=payload.get("keywords") or [],
        competitor_asins=payload.get("competitor_asins") or [],
        selling_points=payload.get("selling_points"),
        main_image=payload.get("main_image") or "",
        images=payload.get("images") or [],
        source=payload.get("source") or "blue_ocean",
        review_status=payload.get("review_status") or "pending",
        review_notes=payload.get("review_notes") or "",
        reviewed_at=payload.get("reviewed_at"),
        reviewed_by=payload.get("reviewed_by"),
        monitor_data=payload.get("monitor_data"),
        last_monitored_at=payload.get("last_monitored_at"),
        shop_id=shop_id or payload.get("shop_id") or "",
        tags=payload.get("tags") or [],
        notes=payload.get("notes") or "",
        groups=payload.get("groups") or [],
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )


async def candidate_exists(asin: str, shop_id: Optional[str]) -> bool:
    """
    该店铺下是否已有同 ASIN 的候选。

    用途：对话里重复说「把这个品加进选品库」时避免累积重复行
    （同一商品存 3 遍，评审时无法分辨哪条是最新评估）。

    注意：`shop_id` 为空时一律返回 False（不做跨店铺判重）——
    没有租户上下文时无从判断归属，宁可写入也不要误判为「已存在」而丢数据。
    """
    if not asin or not shop_id:
        return False
    from sqlalchemy import select

    async with async_session_factory() as session:
        row = (await session.execute(
            scoped(select(CandidateRecord.id), CandidateRecord, shop_id)
            .where(CandidateRecord.asin == asin)
            .limit(1)
        )).scalar_one_or_none()
    return row is not None


async def create_candidate(payload: dict, shop_id: Optional[str] = None) -> dict:
    """
    新增候选（**唯一写入口**）。

    Returns:
        落库后的候选 dict（字段名与前端 CandidateItem 对齐）。
    """
    record = build_candidate_record(payload, shop_id=shop_id)

    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)

    return record_to_dict(record)

"""
竞品监控池 - 业务逻辑层

把**写入口**从 router 抽出，与 `modules/candidates/service.py` 同构：
REST 路由与（将来的）Agent 工具共用同一套默认值与判重规则，避免两处各写一遍。

时序数据在「入池」这一刻由 `snapshot.build_time_series` 生成一次并落库，
此后固定不变 —— 这是本次改造的核心收益（原先前端每次进页面重算，刷新就变）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from core.database import async_session_factory
from core.library_query import count_library, query_library
from core.tenant.scoping import scoped
from modules.monitors.db_model import MonitorRecord
from modules.monitors.spec import MONITOR_SPEC
from modules.monitors.snapshot import build_time_series, derive_baseline


# ====== 字段契约（与前端 MonitorPoolRecord 严格对齐）======

# 判据：入池的**最小充分信息**就是 ASIN —— 其余字段（标题/价格/BSR/时序）
# 都能由 snapshot 按 ASIN 确定性推导出来，没必要为它们打断用户。
MONITOR_REQUIRED_FIELDS = ("asin",)

MONITOR_FIELD_LABELS = {
    "asin": "ASIN",
    "title": "商品标题",
    "latest_price": "当前售价(USD)",
}

# 允许从 payload 直接写入的字段白名单（禁止 setattr 任意属性）
_UPDATABLE_FIELDS = (
    "title", "brand", "main_image", "marketplace", "currency",
    "latest_price", "price_change_7d", "latest_bsr", "bsr_category", "bsr_change_7d",
    "rating", "review_count", "reviews_added_7d", "stock_status",
    "estimated_units_remaining", "est_monthly_sales",
    "price_history", "bsr_history", "review_events", "variations", "listing_changes",
    "group_ids", "origin", "source_candidate_id", "owned_by",
)


def normalize_asin(raw) -> str:
    """ASIN 归一：去空白 + 转大写（真实 ASIN 恒为大写 B0 开头）"""
    return (raw or "").strip().upper()


def missing_required_fields(payload: dict) -> list:
    """返回缺失的必填字段（对齐面板 required）"""
    missing = []
    for field in MONITOR_REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def describe_missing_fields(missing: list) -> str:
    """缺失字段 → 中文提示（别把 `asin` 这种字段名甩给用户）"""
    return "、".join(MONITOR_FIELD_LABELS.get(f, f) for f in missing)


def make_monitor_id(asin: str, shop_id: Optional[str]) -> str:
    """主键 `mon-{asin}-{shop}`：ASIN 仅在同店铺内唯一，主键必须带租户维度"""
    return f"mon-{asin}-{shop_id or 'demo'}"


# ====== ORM → dict ======

async def list_monitors(
    shop_id: Optional[str],
    *,
    order_by: Optional[str] = None,
    stock_status: Optional[str] = None,
    marketplace: Optional[str] = None,
    limit: Optional[int] = None,
):
    """监控池列表（**唯一实现**）—— REST 与 Agent 工具共用。

    ★ 第 218 轮（P1）：改前「读监控池」只有 `monitors/router.py::list_monitors`
      一处**内联实现**（handler 体里直接拼 `select`），Agent 侧够不着、也无从复用。
      现在收口到这里，由本函数调 `core.library_query` 内核。

    ★ 默认排序 = 改前 REST 的 `order_by(MonitorRecord.created_at.desc())`，
      逐字不变（前端文案「新增的排在前面」）。
    """
    rows = await query_library(
        MONITOR_SPEC,
        shop_id,
        order_by=order_by,
        filters={"stock_status": stock_status, "marketplace": marketplace},
        limit=limit,
    )
    return [row[0] for row in rows]


async def count_monitors(
    shop_id: Optional[str],
    *,
    stock_status: Optional[str] = None,
    marketplace: Optional[str] = None,
) -> int:
    """监控池**真实**条数（与 `list_monitors` 同口径，两者都走内核）。"""
    return await count_library(
        MONITOR_SPEC,
        shop_id,
        filters={"stock_status": stock_status, "marketplace": marketplace},
    )


def record_to_dict(r: MonitorRecord) -> dict:
    """ORM → dict（字段名与前端 MonitorPoolRecord 一一对齐）"""
    return {
        "id": r.id,
        "asin": r.asin,
        "title": r.title,
        "brand": r.brand,
        "main_image": r.main_image,
        "marketplace": r.marketplace,
        "currency": r.currency,
        "latest_price": r.latest_price,
        "price_change_7d": r.price_change_7d,
        "latest_bsr": r.latest_bsr,
        "bsr_category": r.bsr_category,
        "bsr_change_7d": r.bsr_change_7d,
        "rating": r.rating,
        "review_count": r.review_count,
        "reviews_added_7d": r.reviews_added_7d,
        "stock_status": r.stock_status,
        "estimated_units_remaining": r.estimated_units_remaining,
        "est_monthly_sales": r.est_monthly_sales,
        # JSON 列在库里是 NULL，前端期望恒为数组 —— 这里统一兜底，别让前端判空
        "price_history": r.price_history or [],
        "bsr_history": r.bsr_history or [],
        "review_events": r.review_events or [],
        "variations": r.variations or [],
        "listing_changes": r.listing_changes or [],
        "group_ids": r.group_ids or [],
        "origin": r.origin,
        "source_candidate_id": r.source_candidate_id,
        "owned_by": r.owned_by,
        "added_at": r.added_at,
    }


def group_to_dict(g) -> dict:
    """分组 ORM → dict（对齐前端 MonitorGroup，字段为驼峰）"""
    return {
        "id": g.id,
        "name": g.name,
        "kind": g.kind,
        "color": g.color,
        "createdAt": g.createdAt,
    }


# ====== 构造 ======

def build_monitor_record(payload: dict, shop_id: Optional[str] = None) -> MonitorRecord:
    """
    由 payload 构造 MonitorRecord（不落库）。

    payload 字段**全部可选（除 asin）**，缺省值在此集中收敛。
    时序数据：payload 显式带了就用（如真实抓取回填），否则按 ASIN 生成 30 天基线。
    """
    asin = normalize_asin(payload.get("asin"))
    now = datetime.utcnow().isoformat()
    baseline = derive_baseline(asin, payload)
    ts = build_time_series(
        asin=asin,
        base_price=baseline["base_price"],
        base_bsr=baseline["base_bsr"],
        month_sales=int(payload.get("est_monthly_sales") or 0),
        idx=0,
    )

    def _prefer(key: str, fallback):
        """payload 显式给的值优先；注意 0 / 0.0 是有效值，不能用 `or` 判空"""
        v = payload.get(key)
        return fallback if v is None else v

    def _prefer_list(key: str, fallback: list) -> list:
        v = payload.get(key)
        return v if v else fallback

    return MonitorRecord(
        id=payload.get("id") or make_monitor_id(asin, shop_id),
        asin=asin,
        shop_id=shop_id or payload.get("shop_id") or "",
        title=payload.get("title") or asin,
        brand=payload.get("brand") or "",
        main_image=payload.get("main_image") or "",
        marketplace=payload.get("marketplace") or "us",
        currency=payload.get("currency") or "USD",
        latest_price=_prefer("latest_price", ts["latest_price"]),
        price_change_7d=_prefer("price_change_7d", ts["price_change_7d"]),
        latest_bsr=_prefer("latest_bsr", ts["latest_bsr"]),
        bsr_category=payload.get("bsr_category") or "",
        bsr_change_7d=_prefer("bsr_change_7d", ts["bsr_change_7d"]),
        rating=payload.get("rating") or 0,
        review_count=payload.get("review_count") or 0,
        reviews_added_7d=_prefer("reviews_added_7d", ts["reviews_added_7d"]),
        stock_status=payload.get("stock_status") or ts["stock_status"],
        estimated_units_remaining=_prefer(
            "estimated_units_remaining", ts["estimated_units_remaining"]
        ),
        est_monthly_sales=payload.get("est_monthly_sales") or 0,
        price_history=_prefer_list("price_history", ts["price_history"]),
        bsr_history=_prefer_list("bsr_history", ts["bsr_history"]),
        review_events=_prefer_list("review_events", ts["review_events"]),
        variations=_prefer_list("variations", ts["variations"]),
        listing_changes=_prefer_list("listing_changes", ts["listing_changes"]),
        group_ids=payload.get("group_ids") or [],
        origin=payload.get("origin") or "manual",
        source_candidate_id=payload.get("source_candidate_id"),
        owned_by=payload.get("owned_by"),
        added_at=payload.get("added_at") or now,
        created_at=now,
        updated_at=now,
    )


def apply_fields(record: MonitorRecord, payload: dict) -> None:
    """把 payload 里出现且非 None 的白名单字段合并进已有记录"""
    for field in _UPDATABLE_FIELDS:
        if field in payload and payload[field] is not None:
            setattr(record, field, payload[field])


# ====== 查询 / 写入 ======

async def monitor_exists(asin: str, shop_id: Optional[str]) -> bool:
    """
    该店铺下是否已监控此 ASIN。

    与 candidates 一致：`shop_id` 为空时一律返回 False ——
    没有租户上下文时无从判断归属，宁可写入也不要误判为「已存在」而丢数据。
    """
    if not asin or not shop_id:
        return False
    async with async_session_factory() as session:
        row = (await session.execute(
            scoped(select(MonitorRecord.id), MonitorRecord, shop_id)
            .where(MonitorRecord.asin == asin)
            .limit(1)
        )).scalar_one_or_none()
    return row is not None


# ★ 第 283 轮删除：这里原有一个 `get_monitor_by_id`（条件式 `if shop_id:` 版）。
#   它**零调用点**（`modules/monitors/router.py::get_monitor` 自己写了无条件版），
#   也不在 `__all__` 里 —— 同一判定有两份实现，被门禁守住的那份是无条件的，
#   这份没人测的实现留着只有一种作用：将来被人用起来时把越权原样复活。
async def upsert_monitor(payload: dict, shop_id: Optional[str] = None) -> dict:
    """
    入池：**唯一写入口**。同店铺同 ASIN 已存在则合并字段（不新增行）。

    合并语义很重要 —— 「候选库开启监控」「蓝海随手盯」「监控页手填」三条入池
    路径会打同一个 ASIN，若各自 insert 就会在池里出现重复行，
    面板按 ASIN 聚合时数字翻倍。
    """
    asin = normalize_asin(payload.get("asin"))
    async with async_session_factory() as session:
        q = select(MonitorRecord).where(MonitorRecord.asin == asin)
        q = scoped(q, MonitorRecord, shop_id or '')
        existing = (await session.execute(q)).scalar_one_or_none()

        if existing is not None:
            apply_fields(existing, payload)
            existing.updated_at = datetime.utcnow().isoformat()
            await session.commit()
            await session.refresh(existing)
            return record_to_dict(existing)

        record = build_monitor_record(payload, shop_id=shop_id)
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record_to_dict(record)

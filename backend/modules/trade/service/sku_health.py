"""SKU 健康分：纯函数打分 `score_from_parts` + 落库 `compute_sku_health`。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.tenant.scoping import scope_condition
from datetime import datetime, timedelta
from modules.trade.db_model import ATTRIBUTION_CAUSES, CustomerReviewRecord, OrderItemRecord, OrderRecord, ReviewAttributionRecord, SkuHealthScoreRecord
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ._base import (parse_iso)



# ============================================================ SKU 健康分

#: v1 权重 —— 写死在一处，便于「换口径」变成一次可审阅的改动
_HEALTH_WEIGHTS: dict[str, float] = {
    "rating": 0.45,
    "logistics": 0.30,
    "packaging": 0.25,
}


#: 迟到订单占比达到多少 ⇒ 该维度 0 分
_LOGISTICS_TOLERANCE = 0.30


#: 包装破损归因次数达到多少 ⇒ 该维度 0 分
_PACKAGING_TOLERANCE = 5




def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))




def score_from_parts(
    *,
    avg_rating: float,
    delayed_orders: int,
    total_orders: int,
    packaging_failures: int,
) -> tuple[float, dict]:
    """由三个可量化输入算出 0~100 的健康分与各维度分。

    ★ 公式刻意**简单可读**：科研级模型不值钱，**能被反驳**才值钱。
      维度分（dimensions）随分数一起存，便于事后问「为什么它掉到 62」。
    """
    rating_dim = _clamp((avg_rating or 0) / 5.0 * 100.0)
    delayed_rate = (delayed_orders / total_orders) if total_orders else 0.0
    logistics_dim = _clamp(100.0 * (1.0 - delayed_rate / _LOGISTICS_TOLERANCE))
    packaging_dim = _clamp(100.0 * (1.0 - packaging_failures / _PACKAGING_TOLERANCE))

    total = (
        rating_dim * _HEALTH_WEIGHTS["rating"]
        + logistics_dim * _HEALTH_WEIGHTS["logistics"]
        + packaging_dim * _HEALTH_WEIGHTS["packaging"]
    )
    dimensions = {
        "rating": round(rating_dim, 1),
        "logistics": round(logistics_dim, 1),
        "packaging": round(packaging_dim, 1),
    }
    return round(total, 1), dimensions




async def compute_sku_health(
    session: AsyncSession,
    shop_id: str,
    sku: str,
    *,
    period_days: int = 30,
    period_end: Optional[str] = None,
) -> Optional[SkuHealthScoreRecord]:
    """为一个 SKU 计算**一期**健康分并 upsert 进 `sku_health_scores`。

    ★ `previous_score` / `delta` 都**真去读上一期**：演示里那句「健康分 -0.7」
      只有在库里真的存在上一期时才成立 —— 第一期一律 period_end=当前、
      previous=0、delta=0，不许编一个下降幅度出来好看。
    """
    end_dt = parse_iso(period_end) or datetime.utcnow()
    start_dt = end_dt - timedelta(days=int(period_days))
    end_key = end_dt.date().isoformat()
    start_key = start_dt.date().isoformat()

    reviews = (await session.execute(
        select(CustomerReviewRecord).where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            CustomerReviewRecord.sku == sku,
            CustomerReviewRecord.review_at >= start_key,
            CustomerReviewRecord.review_at <= end_key,
        ))
    )).scalars().all()

    review_count = len(reviews)
    negative_count = sum(1 for r in reviews if r.rating <= 3)
    avg_rating = round(sum(r.rating for r in reviews) / review_count, 2) if review_count else 0.0

    # 归因维度计数 —— ★ 必须与上面的评价集合**同窗**，否则「本期 top cause」
    #   会把窗口外的历史归因也算进来（口径不一致：分子窗口宽、分母窗口窄）。
    #   `ReviewAttributionRecord` 自己没有日期，故 join 回评价按 review_at 过滤。
    attrs = (await session.execute(
        select(ReviewAttributionRecord)
        .join(CustomerReviewRecord,
              CustomerReviewRecord.id == ReviewAttributionRecord.review_id)
        .where(and_(
            scope_condition(ReviewAttributionRecord, shop_id),
            ReviewAttributionRecord.sku == sku,
            CustomerReviewRecord.review_at >= start_key,
            CustomerReviewRecord.review_at <= end_key,
        ))
    )).scalars().all()
    cause_counts: dict[str, int] = {c: 0 for c in ATTRIBUTION_CAUSES}
    for a in attrs:
        for c in (a.causes or [a.primary_cause]):
            if c in cause_counts:
                cause_counts[c] += 1

    # 迟到订单数：本周期内该 SKU 涉及订单里 delay_days > 0 的笔数
    total_orders, delayed_orders = await _count_orders_for_sku(
        session, shop_id, sku, start_key, end_key,
    )

    health_score, dimensions = score_from_parts(
        avg_rating=avg_rating,
        delayed_orders=delayed_orders,
        total_orders=total_orders,
        packaging_failures=cause_counts.get("packaging_failure", 0),
    )

    top_cause = max(
        (c for c in ATTRIBUTION_CAUSES if c != "unknown"),
        key=lambda c: cause_counts.get(c, 0),
    )
    if cause_counts.get(top_cause, 0) == 0:
        top_cause = "unknown"

    previous = await _previous_score(session, shop_id, sku, period_days, end_key)
    delta = round(health_score - previous, 2) if previous else 0.0

    row_id = f"hlt-{sku}-{end_key}"
    row = (await session.execute(
        select(SkuHealthScoreRecord).where(SkuHealthScoreRecord.id == row_id)
    )).scalar_one_or_none()
    if row is None:
        row = SkuHealthScoreRecord(id=row_id)
        session.add(row)
    product_title = reviews[0].product_title if reviews else ""

    row.shop_id = shop_id
    row.sku = sku
    row.asin = reviews[0].asin if reviews else ""
    row.product_title = product_title
    row.period_days = period_days
    row.period_end = end_key
    row.review_count = review_count
    row.negative_count = negative_count
    row.negative_rate = round(negative_count / review_count, 3) if review_count else 0.0
    row.avg_rating = avg_rating
    row.delayed_orders = delayed_orders
    row.cause_counts = {k: v for k, v in cause_counts.items() if v}
    row.dimensions = dimensions
    row.previous_score = previous
    row.health_score = health_score
    row.delta = delta
    row.top_cause = top_cause
    row.method = "rule"
    row.computed_at = datetime.utcnow().isoformat()
    await session.flush()
    return row




async def _count_orders_for_sku(
    session: AsyncSession, shop_id: str, sku: str, start_key: str, end_key: str,
) -> tuple[int, int]:
    """(该 SKU 涉及订单数, 其中迟到笔数)。「涉及」= 订单明细里有这个 SKU。"""
    rows = (await session.execute(
        select(OrderRecord.id, OrderRecord.delay_days)
        .join(OrderItemRecord, OrderItemRecord.order_id == OrderRecord.id)
        .where(and_(
            scope_condition(OrderRecord, shop_id),
            OrderItemRecord.sku == sku,
            OrderRecord.purchase_at >= start_key,
            OrderRecord.purchase_at <= end_key,
        ))
    )).all()
    ids = {r[0] for r in rows}
    delayed = len({r[0] for r in rows if (r[1] or 0) > 0})
    return len(ids), delayed




async def _previous_score(
    session: AsyncSession, shop_id: str, sku: str, period_days: int, end_key: str,
) -> float:
    """上一期（同 SKU、同周期长度、更早的 period_end）的分数。没有 ⇒ 0.0。"""
    prev = (await session.execute(
        select(SkuHealthScoreRecord.health_score)
        .where(and_(
            scope_condition(SkuHealthScoreRecord, shop_id),
            SkuHealthScoreRecord.sku == sku,
            SkuHealthScoreRecord.period_days == period_days,
            SkuHealthScoreRecord.period_end < end_key,
        ))
        .order_by(SkuHealthScoreRecord.period_end.desc())
        .limit(1)
    )).scalar_one_or_none()
    return float(prev or 0.0)




# ============================================================ 个案 / 系统性：唯一判定口径
#
# ★ 为什么判定必须住在**后端**（第 294 轮）
#   「这条差评是个案、还是要捅到根因」此前只有 Agent 工具通道算得出来，
#   HTTP 面没有出口 ⇒ 差评工作台面板**结构上给不出**这一步：用户在面板里
#   走完「生成草稿 → 批准 → 发放」全程，也看不到「是不是系统性问题」。
#   搬进端点之后，**前端一律不得自己推算** `verdict` —— 本仓铁律：
#   同一可见性两份实现且不一致 ⇒ 前端不得推算后端判据。
#   组合规则本身就是判据，放前端等于把判据交给不得推算的那一侧。
#
# ★ 判定阈值与结论标签定义在**上面**（`count_repeat_issues` 之前）：
#   它们是「重复问题」判定的唯一真源，`count_repeat_issues` 与本文件的
#   判定函数**共用同一组常量**。一份判定两个数（函数里写 3、常量里写 5）
#   在本仓是明令禁止的，而它不会报错，只会让两条通道结论不同。


async def get_sku_health_score(
    session: AsyncSession, shop_id: str, sku: str,
) -> dict:
    """取某 SKU **最近一期**买家反馈健康分 —— **唯一真源**（工具与端点共用）。

    ★ 为什么从 `tools._get_sku_health_score_tool` 搬到这里：HTTP 端点
      （`GET /api/v1/trade/skus/{sku}/health`）也要这个数。在 router 或 tools 里
      再写一遍那条查询就是**同一判定两份实现** ⇒ 至少一份永远测不到（本仓铁律）。
      工具层自此只做「取会话 + 调本函数 + 序列化」。

    ★ 取不到时返回 `found=False`，**不返回一堆 0**：0 分与「没算过」在界面上
      必须分开播报，否则「这个 SKU 健康分为 0」会伪装成实测结论。
    """
    row = (await session.execute(
        select(SkuHealthScoreRecord)
        .where(scope_condition(SkuHealthScoreRecord, shop_id),
               SkuHealthScoreRecord.sku == sku)
        .order_by(SkuHealthScoreRecord.period_end.desc())
        .limit(1)
    )).scalars().first()
    if row is None:
        return {"found": False, "sku": sku,
                "error": "该 SKU 还没算过健康分（需先有一期归因数据）"}
    return {
        "found": True,
        "sku": row.sku, "asin": row.asin, "product_title": row.product_title,
        "period_days": row.period_days, "period_end": row.period_end,
        "health_score": row.health_score, "previous_score": row.previous_score,
        "delta": row.delta, "top_cause": row.top_cause,
        "dimensions": row.dimensions, "cause_counts": row.cause_counts,
        "review_count": row.review_count, "negative_rate": row.negative_rate,
        "avg_rating": row.avg_rating, "delayed_orders": row.delayed_orders,
    }

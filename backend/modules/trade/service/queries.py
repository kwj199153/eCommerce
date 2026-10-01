"""订单/物流/差评的查询与序列化（含 SPU 软关联与孤儿差评出口）。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.tenant.scoping import scope_condition
from datetime import datetime, timedelta
from modules.products import SkuRecord, SpuRecord
from modules.trade.db_model import CustomerReviewRecord, OrderItemRecord, OrderRecord, ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ._base import (_attribution_to_dict, _disposition_to_dict, _item_to_dict, _order_to_dict, _review_to_dict, _shipment_to_dict)



# ============================================================ 查询：一笔订单的完整上下文

async def get_order_context(
    session: AsyncSession, shop_id: str, order_id_or_external: str,
) -> dict:
    """取「一笔订单 + 明细 + 物流 + 关联差评」的完整上下文。

    ★ 这是「信息整合」这个卖点在**数据层**的落点：演示里那句
      「订单 Found + 物流轨迹 + 买家差评」必须来自一次查询，而不是三次各自猜测。
    """
    row = (await session.execute(
        select(OrderRecord).where(and_(
            scope_condition(OrderRecord, shop_id),
            (OrderRecord.external_order_id == order_id_or_external)
            | (OrderRecord.id == order_id_or_external),
        ))
    )).scalars().first()
    if row is None:
        return {"found": False, "order_id": order_id_or_external,
                "error": "本店铺下查不到这笔订单（订单号不存在或不属于当前店铺）"}

    items = (await session.execute(
        select(OrderItemRecord).where(OrderItemRecord.order_id == row.id)
    )).scalars().all()
    shipment = (await session.execute(
        select(ShipmentRecord).where(ShipmentRecord.order_id == row.id)
    )).scalars().first()
    reviews = (await session.execute(
        select(CustomerReviewRecord).where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            CustomerReviewRecord.order_id == row.id,
        ))
    )).scalars().all()

    return {
        "found": True,
        "order": _order_to_dict(row),
        "items": [_item_to_dict(i) for i in items],
        "shipment": _shipment_to_dict(shipment) if shipment else None,
        "reviews": [_review_to_dict(r) for r in reviews],
        # ★ 谁给的这行数据必须带上 —— 演示数据与真实数据在界面上不该长得一样
        "data_source": row.source,
    }




async def get_review_context(
    session: AsyncSession, shop_id: str, review_id: str,
) -> dict:
    """取「一条差评 + 关联订单/物流 + 归因 + 处置」—— 差评处置的原料。"""
    review = (await session.execute(
        select(CustomerReviewRecord).where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            (CustomerReviewRecord.id == review_id)
            | (CustomerReviewRecord.external_review_id == review_id),
        ))
    )).scalars().first()
    if review is None:
        return {"found": False, "review_id": review_id,
                "error": "本店铺下查不到这条评价（不存在或不属于当前店铺）"}

    order = shipment = None
    if review.order_id:
        order = (await session.execute(
            select(OrderRecord).where(OrderRecord.id == review.order_id)
        )).scalars().first()
        if order is not None:
            shipment = (await session.execute(
                select(ShipmentRecord).where(ShipmentRecord.order_id == order.id)
            )).scalars().first()

    attribution = (await session.execute(
        select(ReviewAttributionRecord).where(
            ReviewAttributionRecord.review_id == review.id)
    )).scalars().first()
    disposition = (await session.execute(
        select(ReviewDispositionRecord).where(
            ReviewDispositionRecord.review_id == review.id)
    )).scalars().first()

    return {
        "found": True,
        "review": _review_to_dict(review),
        "order": _order_to_dict(order) if order else None,
        "shipment": _shipment_to_dict(shipment) if shipment else None,
        "attribution": _attribution_to_dict(attribution) if attribution else None,
        "disposition": _disposition_to_dict(disposition) if disposition else None,
        "data_source": review.source,
    }




def _recent_negative_condition(shop_id: str, max_rating: int, days: int):
    """「本店近期的中差评」这个过滤条件 —— **唯一**口径。

    ★ list 与 count 共用它：UI 的「共 N 条」必须和列表源自同一判定，
      否则改一处忘一处 ⇒ 列表显示 20 条而总数说 0（或反过来）。
    """
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    return and_(
        scope_condition(CustomerReviewRecord, shop_id),
        CustomerReviewRecord.rating <= max_rating,
        CustomerReviewRecord.review_at >= since,
    )




async def list_recent_negative_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, limit: int = 20,
    days: int = 30, offset: int = 0,
) -> list[dict]:
    """列出本店铺近期的中差评（默认 ≤3 星、30 天内）。

    ★ `limit` 会截断 —— 界面要显示「共 N 条」请用 `count_recent_negative_reviews`，
      不要用 `len(items)`（那给出的是被截断后的数）。
    """
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(_recent_negative_condition(shop_id, max_rating, days))
        .order_by(CustomerReviewRecord.review_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
    )).scalars().all()
    return [_review_to_dict(r) for r in rows]




async def count_recent_negative_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, days: int = 30,
) -> int:
    """本店近期的中差评**真实条数**（不受 `list_...` 的 limit 截断）。"""
    return int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord)
        .where(_recent_negative_condition(shop_id, max_rating, days))
    )).scalar_one())




# ============================================================ 产品 ↔ 差评 关联
#
# ★ 为什么这套关联是「软」的（改这里之前请先读 `db_model.py` 的注释）
# ------------------------------------------------------------
# `customer_reviews.asin` / `.sku` **没有外键**指向 `skus` —— 它们是**平台侧
# 标识符**，不能因为本地产品库少一行就让差评插不进来（差评落库早于产品登记
# 是常态）。没有外键兜 ⇒ join 可能一行都匹配不上，而「匹配不上」有两种
# 语义完全不同的"空"：
#
#   A. 这个产品确实没有差评             —— 正常结论，可以显示「暂无差评」
#   B. 差评和产品**没能对上**（数据缺口）—— 显示「暂无差评」等于把缺口
#                                          伪装成「产品没问题」
#
# 这两种不能混成同一个空列表。下面两个函数把 `empty_state` 显式返回，
# 由界面分别播报（本仓：失败 / 缺口必须能归因）。
#
# ★ 为什么必须用 `distinct` 去重
# ------------------------------------------------------------
# 真库实测（探针 `scripts/probe_review_product_join.py`，输出落盘
# `out-probe-join.txt`）：同一个 ASIN 会挂在**多个 SKU、且分属多个 SPU** ——
# `('B0CXXXX009', 4, 4)` 表示 1 个 ASIN → 4 行 SKU → 4 个不同 SPU。
# 不去重 ⇒ SPU↔差评不是树形而是多对多：同一批差评被 4 个产品各认领一次，
# `count(*)` 虚增 4 倍，分页还会漏行（同一行在不同产品里占位不同）。


def _review_match_condition():
    """差评 ↔ SKU 的匹配条件 —— **唯一**口径，SPU 主查询与孤儿查询共用一份。

    ASIN 优先（平台内全局唯一）；ASIN 缺失时退回 `sku_code`。

    ★ 两侧都必须判非空：两边都是空串时 `"" == ""` 会让**所有**空 ASIN 的差评
      命中**所有**空 ASIN 的 SKU —— 那是把「没有登记」读成了「全店通用」。
      这类错误不报错，只会表现为「数量不对」，很难被发现。
    """
    return or_(
        and_(
            CustomerReviewRecord.asin != "",
            SkuRecord.asin != "",
            SkuRecord.asin == CustomerReviewRecord.asin,
        ),
        and_(
            CustomerReviewRecord.sku != "",
            SkuRecord.sku_code != "",
            SkuRecord.sku_code == CustomerReviewRecord.sku,
        ),
    )




def _rating_condition(max_rating: Optional[int]):
    """「算不算差评」的过滤条件。

    ★ `rating` 为 NULL 一律**算进来**：星都没拿到就说「不是差评」，
      那是把「未知」当成「好评」（本仓对静默退化一贯 fail-closed）。
    """
    if max_rating is None:
        return None
    return or_(
        CustomerReviewRecord.rating.is_(None),
        CustomerReviewRecord.rating <= max_rating,
    )




def _match_kind_of(review: CustomerReviewRecord, asins: set, codes: set) -> str:
    """这条差评是靠什么对上产品的 —— 界面要显示「命中 SKU / ASIN」。

    ★ 这里不用再查一次库：`asins` / `codes` 已经是本 SPU 名下 SKU 的解集，
      与 SQL 的 join 条件同源 ⇒ 不会漂移。再查一遍就是同一判定两份实现。
    """
    if (review.asin or "") and review.asin in asins:
        return "asin"
    if (review.sku or "") and review.sku in codes:
        return "sku_code"
    return "unknown"




async def list_reviews_for_spu(
    session: AsyncSession, shop_id: str, spu_id: str, *,
    max_rating: Optional[int] = None, limit: int = 50, offset: int = 0,
) -> dict:
    """列出「属于某个 SPU」的差评 —— SPU 只当**聚合壳**，真正的键在 SKU 上。

    ★ 为什么挂在 SPU 上是合理的，但**只能当壳**
      ------------------------------------------
      SPU「无 ASIN、不可售」（见 `modules/products/db_model.py` 文件头注释），
      而差评带的是 ASIN ⇒ 物理上只能 `spus.id → skus.spu_id → skus.asin`
      解出这个 SPU 名下的 ASIN 集合，再去匹配 `customer_reviews.asin`。
      界面侧同样成立：产品详情抽屉里 SPU 已经带了 SKU 子表，用户的心智是
      「看这个产品怎么样」，不是「看某个规格怎么样」。

    ★ 店铺作用域两处都要收窄（少一处就是跨租户读）
      ------------------------------------------
      `skus` 表**没有** `shop_id`，产品线只能经 `spus.shop_id` 定归属；
      差评自己另有一份 `shop_id`。两条都挂 ⇒ 否则「别家店的 SKU 与我店差评
      同名 ASIN」会把别家的评价拉进本店的产品详情。

    返回体里的 `empty_state`（**两种空态必须分开播报**）：
      - `"not_found"`         SPU 不存在 / 不属于本店（与「存在但没差评」是两件事）
      - `"no_sku"`            SPU 下还没登记 SKU
      - `"no_asin_binding"`   SKU 登记了但 ASIN / sku_code 全空 ⇒ **数据缺口**
      - `"no_reviews"`        关联得上，确实没有符合条件的评价 ⇒ **正常结论**
      - `None`                有数据
    """
    spu = (await session.execute(
        select(SpuRecord).where(and_(
            scope_condition(SpuRecord, shop_id),
            SpuRecord.id == spu_id,
        ))
    )).scalars().first()
    if spu is None:
        return {"found": False, "spu_id": spu_id, "reviews": [], "total": 0,
                "empty_state": "not_found", "asin_count": 0, "sku_count": 0}

    sku_rows = (await session.execute(
        select(SkuRecord.id, SkuRecord.asin, SkuRecord.sku_code,
               SkuRecord.spec_value)
        .where(SkuRecord.spu_id == spu_id)
    )).all()
    asins = {r.asin for r in sku_rows if (r.asin or "")}
    codes = {r.sku_code for r in sku_rows if (r.sku_code or "")}
    head = {
        "found": True, "spu_id": spu_id, "spu_title": spu.title,
        "reviews": [], "total": 0,
        "asin_count": len(asins), "sku_count": len(sku_rows),
        "asins": sorted(asins),
    }
    if not sku_rows:
        return {**head, "empty_state": "no_sku"}
    if not asins and not codes:
        # ★ 这里**不能**返回 "no_reviews"：SKU 都登记了却没有 ASIN，
        #   差评再怎么存在也 join 不上 —— 那是缺口，不是清白。
        return {**head, "empty_state": "no_asin_binding"}

    id_stmt = (
        select(CustomerReviewRecord.id)
        .join(SkuRecord, _review_match_condition())
        .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
        .where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            scope_condition(SpuRecord, shop_id),
            SpuRecord.id == spu_id,
        ))
        .distinct()
    )
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        id_stmt = id_stmt.where(rating_cond)

    # ★ 两趟而不是一条 DISTINCT + ORDER BY：PostgreSQL 要求 ORDER BY 的表达式
    #   出现在 SELECT DISTINCT 的列表里，直接在 id 上排序会被拒。
    #   先把 id 解成集合（去重发生在 SQL 侧），再按 id 取行做排序 / 分页。
    #   差评是本店的有限集合（远小于 SKU 量级），两次往返可接受。
    ids = list((await session.execute(id_stmt)).scalars().all())
    if not ids:
        return {**head, "empty_state": "no_reviews"}

    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(CustomerReviewRecord.id.in_(ids))
        .order_by(desc(CustomerReviewRecord.review_at))
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )).scalars().all()

    return {
        **head,
        "total": len(ids),
        "limit": limit, "offset": offset,
        "reviews": [
            _review_to_dict(r, match_kind=_match_kind_of(r, asins, codes))
            for r in rows
        ],
        "empty_state": None,
    }




async def count_orphan_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: Optional[int] = None,
) -> int:
    """统计本店「SKU 关联不上」的差评条数 —— 给两条路径共用的一个数。

    ★ 单独成函数而不是 `len(list_orphan_reviews(...))`：产品详情 tab 在
      「数据缺口」空态里要显示「本店还有 N 条差评没关联上产品」，
      为一个数拉 50 行明细没必要，且列表有分页上限 ⇒ 会数错。
    """
    conds = [scope_condition(CustomerReviewRecord, shop_id),
             _not_bound_to_sku(shop_id)]
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        conds.append(rating_cond)
    return int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord).where(*conds)
    )).scalar_one())




async def list_orphan_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: Optional[int] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    """本店铺下「SKU 关联不上」的那批差评 —— P1 兜底列表。

    定义：既没有本店任何 SPU 名下 SKU 的 `asin` 等于它的 `asin`，
          也没有任何 SKU 的 `sku_code` 等于它的 `sku`。

    ★ 为什么必须单列
      ---------------
      软关联没有外键兜 ⇒ 关联不上的差评**不会出现在任何产品的差评 tab 里**，
      它们只是静默消失。而差评恰是最需要被看见的那批数据：界面上那句
      「这个产品 0 条差评」必须能被人验证到底是「真的没有」还是「没对上」。
      没有这张列表，「0 条」永远无法被证伪。
    """
    conds = [scope_condition(CustomerReviewRecord, shop_id),
             _not_bound_to_sku(shop_id)]
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        conds.append(rating_cond)

    total = int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord).where(*conds)
    )).scalar_one())
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(*conds)
        .order_by(desc(CustomerReviewRecord.review_at))
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )).scalars().all()

    return {
        "items": [_review_to_dict(r) for r in rows],
        "total": total, "limit": limit, "offset": offset,
        "empty_state": None if total else "no_orphans",
    }




def _not_bound_to_sku(shop_id: str):
    """「这条差评在本店产品库里没有任何 SKU 能认领它」—— 孤儿判定的唯一口径。

    ★ `correlate(CustomerReviewRecord)` 是必须的：不加相关，exists 子查询
      里的 `CustomerReviewRecord` 会被当成笛卡尔积展开，条件退化成
      「本店是否存在任意一条 SKU 能对上任意差评」⇒ 要么全孤儿要么全不孤儿。
      这类错误不报错，只表现为「要么 0 要么全表」。

    ★ `SpuRecord` 上的店铺条件不能省：`skus` 没有 `shop_id`，产品的归属
      只能经 `spus.shop_id` 这条链。省掉它 ⇒ 别家店的 SKU 也能认领本店差评，
      孤儿数被系统性低估（看起来"关联质量很好"）。
    """
    return ~(
        select(SkuRecord.id)
        .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
        .where(scope_condition(SpuRecord, shop_id))
        .where(_review_match_condition())
        .correlate(CustomerReviewRecord)
    ).exists()

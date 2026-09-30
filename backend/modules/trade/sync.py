"""
交易履约域 —— **落库同步**（本模块唯一写入路径）
================================================

★★ 为什么必须有一个 `sync.py`
-------------------------------
此前本模块只有一条写入路径：`seed.py::_ensure_order()`（演示数据预置）。
等「订单落库同步」要接数据源时，最省事的做法是在同步任务里再写一遍
「取数 → 建行 → 算派生态 → 判归因」，于是世上就有了**两条写入路径**：

    seed 自己写一遍，同步任务再写一遍。

它们各自算 `transit_days` / `delay_days` / `primary_cause`，
两边都跑得通、都不报错 —— 差别只体现在「同一笔订单在 seed 里迟了 7 天、
在同步里迟了 6 天」这种没人会去对的数字上。这是本项目反复踩的
「同一判定两份实现」坑，故收成一条：**seed 与定时同步都走本文件的
`upsert_*`，各自只负责回答「载荷从哪来」。**

★★ 本文件不实现任何计算
------------------------
只做「落库」一件事：
  · 派生态一律 `service.compute_transit_and_delay`
  · 归因一律 `service.attribute_review`
本文件里**不允许**出现日期相减或关键词匹配 —— 出现就是第二份口径。

★★ 行 id 为什么带 `shop_id`
----------------------------
幂等键是 `(shop_id, platform, external_order_id)`，**允许两家店铺各有一行
同号订单**（不同店铺的订单号本来就可能撞）。若主键 id 不含 shop_id，
第二家店灌同一份数据会撞主键，或者更糟 —— 静默覆盖第一家的行。
=> 主键 id 必须与幂等键同构。

★ 历史包袱：本仓早期灌的演示数据 id 是 `ord-amazon-<external_id>`
  （**不含** shop_id）。故下面所有 upsert 都**先按业务键查**，查到就用老行，
  查不到才按新规则建 —— 否则重跑一遍 seed 会凭空多出一倍数据。
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from core.logger import get_logger
from core.tenant.scoping import scope_condition
from . import service as trade_service
from .db_model import (
    CustomerReviewRecord, OrderItemRecord, OrderRecord, ReviewAttributionRecord,
    ShipmentRecord, SOURCE_PLATFORM_API,
)

_log = get_logger("modules.trade.sync")

#: 归因方式之一：人工指定。★ 规则重算**不许**覆盖人工判定。
MANUAL_METHOD = "manual"


class SourceNotSupported(RuntimeError):
    """数据源明确声明自己**不支持**这个域。

    ★ 与「这次拉到 0 条」是两件事，代价也完全不同：
        不支持 => 永远拉不到，得换接入路径（卖家后台导出 / 第三方数据服务）；
        0 条   => 这次没有，下次可能就有。
      把它们混成一个 `[]`，现象是「同步任务天天成功、订单表永远是空的」，
      而排查方向会被引到「是不是调度没跑」而不是「数据源根本没这能力」。
    """


# ============================================================
# 行 id（★ 唯一真源：seed 与同步任务共用）
# ============================================================

def order_row_id(platform: str, shop_id: str, external_order_id: str) -> str:
    return f"ord-{platform}-{shop_id}-{external_order_id}"


def item_row_id(order_id: str, idx: int) -> str:
    return f"{order_id}-itm-{idx}"


def shipment_row_id(order_id: str) -> str:
    return f"shp-{order_id}"


def review_row_id(platform: str, shop_id: str, external_review_id: str) -> str:
    return f"crev-{platform}-{shop_id}-{external_review_id}"


def attribution_row_id(review_id: str) -> str:
    return f"attr-{review_id}"


# ============================================================
# 落库：订单（orders + order_items + shipments 一起）
# ============================================================

async def upsert_order(
    session,
    shop_id: str,
    payload: Dict[str, Any],
    *,
    source: str = SOURCE_PLATFORM_API,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """把一笔**平台侧订单载荷**落库。

    Args:
        payload: 形状见 `AmazonDataSource.fetch_orders` 的契约。
            ★ 载荷里**不带**派生态（transit_days / delay_days）—— 这里算。
        source: 这条数据是谁给的（`SOURCE_*`）。★ 由数据源自己声明可不可信，
            落到 `orders.source`，上层据此决定是否标注「以下基于演示数据」。
        fetched_at: 拉取时刻（可注入，测试才能钉住）。

    Returns:
        {"order": OrderRecord, "items": [...], "shipment": ShipmentRecord|None,
         "inserted": bool}
        ★ `inserted` 由调用方用来报「本次新增几条」—— 没有它，
          「重跑一遍又多了 4 笔」这种事发现不了。
    """
    platform = payload.get("platform") or "amazon"
    external = payload["external_order_id"]
    now_iso = fetched_at or datetime.utcnow().isoformat()
    inserted = False

    # ★ 先按业务键查（兼容不含 shop_id 的老 id），查不到才按新规则建
    row = (await session.execute(
        select(OrderRecord).where(
            scope_condition(OrderRecord, shop_id),
            OrderRecord.platform == platform,
            OrderRecord.external_order_id == external,
        )
    )).scalar_one_or_none()
    if row is None:
        row = OrderRecord(id=order_row_id(platform, shop_id, external))
        session.add(row)
        inserted = True

    shipped_at = payload.get("shipped_at")
    promised_at = payload.get("promised_at")
    delivered_at = payload.get("delivered_at")
    # ★ 派生态唯一口径 —— 这里不许出现日期相减
    transit_days, delay_days = trade_service.compute_transit_and_delay(
        shipped_at, promised_at, delivered_at,
    )

    row.shop_id = shop_id
    row.platform = platform
    row.marketplace = payload.get("marketplace") or "US"
    row.external_order_id = external
    row.buyer_id = payload.get("buyer_id") or ""
    row.buyer_name = payload.get("buyer_name") or ""
    row.order_status = payload.get("order_status") or "pending"
    row.fulfillment_channel = payload.get("fulfillment_channel") or "FBA"
    row.ship_country = payload.get("ship_country") or ""
    row.ship_state = payload.get("ship_state") or ""
    row.ship_city = payload.get("ship_city") or ""
    row.currency = payload.get("currency") or "USD"
    row.order_total = float(payload.get("order_total") or 0)
    row.purchase_at = payload.get("purchase_at") or ""
    row.promised_at = promised_at
    row.shipped_at = shipped_at
    row.delivered_at = delivered_at
    row.transit_days = transit_days
    row.delay_days = delay_days
    row.source = source
    row.fetched_at = now_iso
    row.raw = payload.get("raw")
    await session.flush()

    # ---- 明细 ----
    items: List[OrderItemRecord] = []
    for idx, it in enumerate(payload.get("items") or []):
        iid = item_row_id(row.id, idx)
        item = (await session.execute(
            select(OrderItemRecord).where(OrderItemRecord.id == iid)
        )).scalar_one_or_none()
        if item is None:
            item = OrderItemRecord(id=iid)
            session.add(item)
        item.shop_id = shop_id
        item.order_id = row.id
        item.external_order_item_id = (
            it.get("external_order_item_id") or f"{external}-{idx + 1}")
        item.sku = it.get("sku") or ""
        item.asin = it.get("asin") or ""
        item.item_title = it.get("item_title") or ""
        item.image = it.get("image") or ""
        item.quantity = int(it.get("quantity") or 1)
        item.currency = it.get("currency") or row.currency
        item.unit_price = float(it.get("unit_price") or 0)
        item.item_total = float(
            it.get("item_total") or (item.unit_price * item.quantity))
        item.raw = it.get("raw")
        items.append(item)
    await session.flush()

    # ---- 物流 ----
    shp_payload = payload.get("shipment") or {}
    shipment = None
    if shp_payload:
        sid = shipment_row_id(row.id)
        shipment = (await session.execute(
            select(ShipmentRecord).where(ShipmentRecord.id == sid)
        )).scalar_one_or_none()
        if shipment is None:
            shipment = ShipmentRecord(id=sid)
            session.add(shipment)
        # ★ 优先用 shipment 段自己的时间戳：承运商揽收/签收时刻与订单头上的
        #   发货时间**不是同一个事实**（FBA 尤甚），退回只是兜底。
        s_shipped = shp_payload.get("shipped_at") or shipped_at
        s_promised = shp_payload.get("promised_at") or promised_at
        s_delivered = shp_payload.get("delivered_at") or delivered_at
        s_transit, s_delay = trade_service.compute_transit_and_delay(
            s_shipped, s_promised, s_delivered,
        )
        events = list(shp_payload.get("events") or [])
        last = events[-1] if events else None

        shipment.shop_id = shop_id
        shipment.order_id = row.id
        shipment.external_order_id = external
        shipment.platform = platform
        shipment.carrier = shp_payload.get("carrier") or ""
        shipment.tracking_no = shp_payload.get("tracking_no") or ""
        shipment.ship_status = shp_payload.get("ship_status") or "unknown"
        shipment.shipped_at = s_shipped
        shipment.promised_at = s_promised
        shipment.delivered_at = s_delivered
        shipment.transit_days = s_transit
        shipment.delay_days = s_delay
        shipment.is_delivered = bool(s_delivered)
        shipment.events = events
        # ★ 末条事件优先从 events 尾元素推（整条轨迹自洽），载荷没给才用显式字段
        shipment.last_event_at = (
            (last or {}).get("at") or shp_payload.get("last_event_at") or "")
        shipment.last_location = (
            (last or {}).get("location") or shp_payload.get("last_location") or "")
        shipment.last_event_text = (
            (last or {}).get("description") or shp_payload.get("last_event_text") or "")
        shipment.source = source
        shipment.fetched_at = now_iso
        await session.flush()

    return {"order": row, "items": items, "shipment": shipment,
            "inserted": inserted}


# ============================================================
# 落库：评论（**并自动归因打标**）
# ============================================================

async def _attribute(session, shop_id: str, review_row: CustomerReviewRecord):
    """给一条评论算归因并落 `review_attributions`。

    ★ 已有归因且 `method == manual` 时**原样返回不覆盖**：
      人工判定优先于规则重算，否则运营好不容易改对的结论会被下次同步冲掉。
    ★ 归因是**派生态**，可以反复重算；「已核准 / 已执行的补偿」不是（那在
      `review_dispositions`，本函数从不碰它）。
    """
    order = shipment = None
    if review_row.order_id:
        order = (await session.execute(
            select(OrderRecord).where(OrderRecord.id == review_row.order_id)
        )).scalar_one_or_none()
        shipment = (await session.execute(
            select(ShipmentRecord).where(
                scope_condition(ShipmentRecord, shop_id),
                ShipmentRecord.order_id == review_row.order_id,
            )
        )).scalar_one_or_none()

    attr_id = attribution_row_id(review_row.id)
    attr = (await session.execute(
        select(ReviewAttributionRecord).where(ReviewAttributionRecord.id == attr_id)
    )).scalar_one_or_none()
    if attr is None:
        attr = ReviewAttributionRecord(id=attr_id)
        session.add(attr)
    elif attr.method == MANUAL_METHOD:
        return attr

    result = trade_service.attribute_review(review_row, order, shipment)
    attr.shop_id = shop_id
    attr.review_id = review_row.id
    attr.order_id = review_row.order_id
    attr.sku = review_row.sku
    attr.rating = review_row.rating
    attr.primary_cause = result["primary_cause"]
    attr.causes = result["causes"]
    attr.confidence = result["confidence"]
    attr.evidence = result["evidence"]
    attr.method = result["method"]
    attr.rule_version = result["rule_version"]
    await session.flush()
    return attr


async def upsert_review(
    session,
    shop_id: str,
    payload: Dict[str, Any],
    *,
    source: str = SOURCE_PLATFORM_API,
    fetched_at: Optional[str] = None,
    auto_attribute: bool = True,
) -> Dict[str, Any]:
    """把一条**平台侧评论载荷**落库，并**自动归因打标**。

    ★ `auto_attribute` 默认开：本仓的约定是「差评落库即归因」。
      否则工具层读到的是 `status=new` 的裸评论，「这条差评为什么发生」
      又变成让 LLM 现场发挥 —— 同一条差评两次问出两个原因，且无从对账。

    Returns:
        {"review": CustomerReviewRecord, "attribution": ...|None, "inserted": bool}
    """
    platform = payload.get("platform") or "amazon"
    external = payload["external_review_id"]
    now_iso = fetched_at or datetime.utcnow().isoformat()
    inserted = False

    row = (await session.execute(
        select(CustomerReviewRecord).where(
            scope_condition(CustomerReviewRecord, shop_id),
            CustomerReviewRecord.platform == platform,
            CustomerReviewRecord.external_review_id == external,
        )
    )).scalar_one_or_none()
    if row is None:
        row = CustomerReviewRecord(id=review_row_id(platform, shop_id, external))
        session.add(row)
        inserted = True

    # ---- 关联自家订单：★ 关联不到就留空，不报错 ----
    #   平台侧订单号未必能在自家 orders 里找到（评论常来自另一条通道），
    #   「关联不上」是**常态**而不是错误。
    order_id = None
    ref = payload.get("order_ref")
    if ref:
        order_id = (await session.execute(
            select(OrderRecord.id).where(
                scope_condition(OrderRecord, shop_id),
                OrderRecord.platform == platform,
                OrderRecord.external_order_id == ref,
            )
        )).scalar_one_or_none()

    row.shop_id = shop_id
    row.platform = platform
    row.external_review_id = external
    row.marketplace = payload.get("marketplace") or "US"
    row.order_id = order_id
    row.sku = payload.get("sku") or ""
    row.asin = payload.get("asin") or ""
    row.product_title = payload.get("product_title") or ""
    row.rating = int(payload.get("rating") or 0)
    row.title = payload.get("title") or ""
    row.body = payload.get("body") or ""
    row.language = payload.get("language") or "en"
    row.review_at = payload.get("review_at") or ""
    row.verified_purchase = bool(payload.get("verified_purchase"))
    row.helpful_votes = int(payload.get("helpful_votes") or 0)
    row.images = payload.get("images") or []
    row.buyer_name = payload.get("buyer_name") or ""
    row.source = source
    row.fetched_at = now_iso
    row.raw = payload.get("raw")
    await session.flush()

    attribution = None
    if auto_attribute:
        attribution = await _attribute(session, shop_id, row)
        # ★ 落库即已归因 —— 少了这句，工具层读到的永远是新评论
        if row.status == "new":
            row.status = "triaged"
        await session.flush()

    return {"review": row, "attribution": attribution, "inserted": inserted}


# ============================================================
# 同步：从数据源落库
# ============================================================

async def sync_orders_from_source(
    session,
    shop_id: str,
    source: Any,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """拉订单并落库。

    Raises:
        SourceNotSupported: 数据源声明不支持订单域。
            ★ **不允许**当成「拉到 0 条」静默收工，理由见该异常类。

    Returns:
        {"inserted": int, "updated": int, "total": int, "source": str}
    """
    batch = source.fetch_orders(
        shop_id, date_from=date_from, date_to=date_to, limit=limit)
    if not batch.get("supported"):
        raise SourceNotSupported(
            f"{type(source).__name__} 不支持订单拉取："
            f"{batch.get('reason') or '数据源未说明原因'}"
        )

    tag = batch.get("source") or SOURCE_PLATFORM_API
    inserted = updated = 0
    for payload in batch.get("orders") or []:
        res = await upsert_order(session, shop_id, payload,
                                 source=tag, fetched_at=fetched_at)
        if res["inserted"]:
            inserted += 1
        else:
            updated += 1
    _log.info("trade 订单同步 shop={} 新增={} 更新={} source={}",
              shop_id, inserted, updated, tag)
    return {"inserted": inserted, "updated": updated,
            "total": inserted + updated, "source": tag}


async def sync_reviews_from_source(
    session,
    shop_id: str,
    source: Any,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """拉买家评论并落库（含自动归因打标）。

    Raises:
        SourceNotSupported: 数据源声明不支持评论域。
            ★ SP-API 没有 Reviews API（已对第三方关闭）⇒「不支持」是常态，
              必须如实抛出来，绝不能回一批编造的差评去喂归因与健康分。
    """
    batch = source.fetch_customer_reviews(
        shop_id, date_from=date_from, date_to=date_to, limit=limit)
    if not batch.get("supported"):
        raise SourceNotSupported(
            f"{type(source).__name__} 不支持评论拉取："
            f"{batch.get('reason') or '数据源未说明原因'}"
        )

    tag = batch.get("source") or SOURCE_PLATFORM_API
    inserted = updated = 0
    for payload in batch.get("reviews") or []:
        res = await upsert_review(session, shop_id, payload,
                                  source=tag, fetched_at=fetched_at)
        if res["inserted"]:
            inserted += 1
        else:
            updated += 1
    _log.info("trade 评论同步 shop={} 新增={} 更新={} source={}",
              shop_id, inserted, updated, tag)
    return {"inserted": inserted, "updated": updated,
            "total": inserted + updated, "source": tag}


async def sync_trade(
    session,
    shop_id: str,
    source: Any,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 200,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """订单 + 评论一起同步。

    ★ 为什么两者的失败处理**不同**：
        订单不支持 => 整个同步没意义 ⇒ 直接抛（往上冒泡，任务会红）；
        评论不支持 => **常态**（SP-API 根本没有 Reviews API），
          不该让「差评通道没接」把已经拉到的订单一起拖垮 ⇒ 记进 `errors`。
      ★ 不吞异常：评论侧失败一定出现在 `errors` 里，调用方能看见。

    Returns:
        {"orders": {...}, "reviews": {...}, "errors": [str, ...]}
    """
    now_iso = (now or datetime.utcnow()).isoformat()
    errors: List[str] = []

    orders = await sync_orders_from_source(
        session, shop_id, source, date_from=date_from, date_to=date_to,
        limit=limit, fetched_at=now_iso,
    )
    try:
        reviews = await sync_reviews_from_source(
            session, shop_id, source, date_from=date_from, date_to=date_to,
            limit=limit, fetched_at=now_iso,
        )
    except SourceNotSupported as exc:
        reviews = {"inserted": 0, "updated": 0, "total": 0, "source": ""}
        errors.append(str(exc))
        _log.warning("trade 评论同步跳过 shop={}：{}", shop_id, exc)

    return {"orders": orders, "reviews": reviews, "errors": errors}

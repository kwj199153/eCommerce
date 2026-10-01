"""差评归因：证据优先于关键词，拿不到证据报 `unknown`（第 1 条硬口径）。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from datetime import datetime
from modules.trade.db_model import ATTRIBUTION_CAUSES, CustomerReviewRecord, OrderRecord, ReviewAttributionRecord, ShipmentRecord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ._base import (AttributionError, AttributionNotFound, _attribution_to_dict, _load_review_scoped)



# ============================================================ 归因规则

#: 文本关键词（**兜底通道**：只在拿不到订单/物流证据时使用）
_KEYWORD_RULES: dict[str, tuple[str, ...]] = {
    "logistics_delay": (
        "too long", "slow", "late", "forever", "12 days", "took weeks",
        "still waiting", "delayed", "shipping took", "arrived late",
        "太慢", "很慢", "迟迟", "等了",
    ),
    "packaging_failure": (
        "crushed", "dented", "damaged box", "packaging was", "smashed",
        "box was", "bubble wrap", "not padded", "arrived broken box",
        "压坏", "包装破损", "箱子压", "挤压",
    ),
    "product_defect": (
        "stopped working", "doesn't work", "does not work", "defective",
        "broke", "broken", "leaks", "leaking", "malfunction",
        "坏了", "不能用", "漏水", "故障",
    ),
    "description_mismatch": (
        "not as described", "different color", "not what i ordered", "misleading",
        "smaller than", "not the same as", "false advertising",
        "不符", "描述不符", "色差", "不一样",
    ),
    "service_attitude": (
        "no response", "rude", "ignored", "never replied", "unhelpful",
        "没人回", "态度",
    ),
    "price_value": (
        "overpriced", "not worth", "too expensive", "cheaper elsewhere",
        "不值", "太贵",
    ),
}



#: ★ 归因优先级：证据通道先算，这里的顺序只用于「多因命中时谁是 primary」
_CAUSE_PRIORITY: tuple[str, ...] = (
    "product_defect",        # 最硬的事实：东西坏了，无论如何都得先处理
    "packaging_failure",     # 运输环节责任
    "logistics_delay",
    "description_mismatch",
    "service_attitude",
    "price_value",
)




def _hit_keywords(body: str, keywords: tuple[str, ...]) -> bool:
    low = (body or "").lower()
    return any(k.lower() in low for k in keywords)




def collect_evidence(
    order: Optional[OrderRecord],
    shipment: Optional[ShipmentRecord],
) -> list[dict]:
    """从订单/物流行里抽出**可引用的事实**作为归因证据。

    ★ 每条证据都带 `ref`（订单号 / 运单号）——「真的查了证据」与
      「只是在叙述里提到证据」的区别就在有没有 ref。
    """
    ev: list[dict] = []
    if order is not None:
        if order.delay_days is not None and order.delay_days > 0:
            ev.append({
                "kind": "order", "ref": order.external_order_id or order.id,
                "fact": f"承诺 {order.promised_at} 送达，实际 {order.delivered_at}"
                        f"（迟到 {order.delay_days} 天）",
            })
        if order.transit_days is not None:
            ev.append({
                "kind": "order", "ref": order.external_order_id or order.id,
                "fact": f"在途 {order.transit_days} 天（发货 {order.shipped_at}）",
            })
    if shipment is not None:
        if shipment.tracking_no:
            ev.append({
                "kind": "shipment", "ref": shipment.tracking_no,
                "fact": f"承运商 {shipment.carrier} / 轨迹终态 {shipment.ship_status}"
                        f"（最后事件 {shipment.last_event_at} @ {shipment.last_location}）",
            })
        if shipment.delay_days is not None and shipment.delay_days > 0:
            ev.append({
                "kind": "shipment", "ref": shipment.tracking_no or shipment.id,
                "fact": f"物流迟到 {shipment.delay_days} 天",
            })
    return ev




def attribute_review(
    review: CustomerReviewRecord,
    order: Optional[OrderRecord] = None,
    shipment: Optional[ShipmentRecord] = None,
) -> dict:
    """给一条买家评论做归因 —— **规则实现，不调用 LLM**。

    Returns:
        {"primary_cause": str, "causes": list[str], "confidence": float,
         "evidence": list[dict], "method": "rule", "rule_version": "v1"}

    ★ 两条通道，优先级从高到低：
      ① **证据通道**（有订单/物流事实）：delay_days > 0 且文本提到等待类词 ⇒ 物流延迟；
         轨迹里有 exception/破损类事件 ⇒ 包装破损。
      ② **关键词兜底**：拿不到订单/物流时才用；命中多个按 `_CAUSE_PRIORITY` 排序。
      都没命中 ⇒ `unknown`（这是**正常结果**，不许兜成别的）。
    """
    causes: list[str] = []
    reason: list[str] = []
    body = f"{review.title or ''} {review.body or ''}"

    delay_days = order.delay_days if order is not None else (
        shipment.delay_days if shipment is not None else None
    )
    transit_days = order.transit_days if order is not None else (
        shipment.transit_days if shipment is not None else None
    )

    # ---- ① 证据通道 ----
    evidence_driven = False
    if delay_days is not None and delay_days > 0 and _hit_keywords(
        body, _KEYWORD_RULES["logistics_delay"]
    ):
        causes.append("logistics_delay")
        reason.append(f"证据：迟到 {delay_days} 天，且文本提到等待类表述")
        evidence_driven = True

    if shipment is not None:
        trace_text = " ".join(
            f"{e.get('status','')} {e.get('description','')}"
            for e in (shipment.events or [])
        )
        if _hit_keywords(trace_text, _KEYWORD_RULES["packaging_failure"]) or _hit_keywords(
            body, _KEYWORD_RULES["packaging_failure"]
        ):
            if shipment.ship_status in ("exception", "damaged") or _hit_keywords(
                trace_text, _KEYWORD_RULES["packaging_failure"]
            ):
                causes.append("packaging_failure")
                reason.append(
                    f"证据：物流终态 {shipment.ship_status}"
                    f"（运单 {shipment.tracking_no}）"
                )
                evidence_driven = True

    # ---- ② 关键词兜底（仅在无证据结论时）----
    if not evidence_driven:
        for cause, words in _KEYWORD_RULES.items():
            if cause in causes:
                continue
            if _hit_keywords(body, words):
                causes.append(cause)
                reason.append(f"文本命中「{cause}」关键词")

    if not causes:
        return {
            "primary_cause": "unknown",
            "causes": [],
            "confidence": 0.0,
            "evidence": collect_evidence(order, shipment),
            "reason": "证据通道无迟到事实，关键词也不命中 —— 判不出来，不猜",
            "method": "rule",
            "rule_version": "v1",
        }

    ordered = sorted(causes, key=lambda c: _CAUSE_PRIORITY.index(c)
                     if c in _CAUSE_PRIORITY else len(_CAUSE_PRIORITY))
    confidence = 0.9 if evidence_driven else 0.5
    return {
        "primary_cause": ordered[0],
        "causes": ordered,
        "confidence": confidence,
        "evidence": collect_evidence(order, shipment),
        "reason": "；".join(reason),
        "method": "rule",
        "rule_version": "v1",
    }




#: 人工**可以**选的成因（不含 `unknown` —— 见 `set_review_attribution` 的注释）
ATTRIBUTABLE_CAUSES: tuple[str, ...] = tuple(c for c in ATTRIBUTION_CAUSES if c != "unknown")




async def set_review_attribution(
    session: AsyncSession,
    shop_id: str,
    review_id: str,
    *,
    primary_cause: str,
    causes: Optional[list] = None,
    evidence: Optional[list] = None,
    notes: str = "",
    actor: str = "",
) -> dict:
    """给一条差评**手工**指定归因（upsert，落 `method="manual"`）。

    ★ `primary_cause` 必须在 `ATTRIBUTION_CAUSES` 值域内，且**不接受 `unknown`**：
      「判不出来」是自动判定的**结果**，不是可选项。让人手工选 unknown 等于
      提供一个「什么也没做但看起来做了」的动作 —— 那正是这 8 条差评的现状。

    ★ 已有归因**可以**被手工覆盖（人工 > 自动），但 `causes` / `evidence`
      留空时**沿用**自动判定留下的那些，不把它们清空成「没证据」。

    ★ `confidence` 一律写 1.0：人工判定不表达「把握有多大」，
      写了 0.5 会让「自动判的」和「人判的」在同一列里没法区分。
    """
    # ★ 延迟导入：`sync.py` 顶部 `from . import service as trade_service`，
    #   这里若在模块顶部 import sync 就是循环导入。id 真源仍在 sync，不另抄一份。
    # ★ 第 355 轮拆包：本文件原为 `modules.trade.service`（**模块**）时，
    #   这里写 `from .sync import ...` 指的是 `modules.trade.sync`。
    #   拆成包之后 `.` 变成了 `modules.trade.service` ⇒ 必须**升一级**写 `..sync`，
    #   否则运行期才炸 `No module named 'modules.trade.service.sync'`。
    from ..sync import MANUAL_METHOD, attribution_row_id

    cause = (primary_cause or "").strip()
    if cause not in ATTRIBUTION_CAUSES:
        raise AttributionError(
            f"归因取值不在值域内：{primary_cause!r}；可选：{' / '.join(ATTRIBUTABLE_CAUSES)}")
    if cause == "unknown":
        raise AttributionError(
            "「未判定」是自动归因判不出来的**结果**，不能手工指定 —— "
            "请选一个具体成因；确实判不出来就先别标（它本来就不会进处置链）。")

    review = await _load_review_scoped(session, shop_id, review_id)
    if review is None:
        raise AttributionNotFound(
            f"本店铺下查不到这条评价（不存在或不属于当前店铺）：{review_id}")

    row_id = attribution_row_id(review.id)
    row = (await session.execute(
        select(ReviewAttributionRecord).where(ReviewAttributionRecord.id == row_id)
    )).scalar_one_or_none()
    created = row is None
    if created:
        row = ReviewAttributionRecord(id=row_id)
        session.add(row)

    now = datetime.utcnow().isoformat()
    row.shop_id = shop_id
    row.review_id = review.id
    row.order_id = review.order_id
    row.sku = review.sku
    row.rating = review.rating
    row.primary_cause = cause
    row.causes = list(causes) if causes else (list(row.causes or []) + [cause])
    row.confidence = 1.0
    row.evidence = list(evidence) if evidence is not None else (list(row.evidence or []))
    row.method = MANUAL_METHOD
    row.rule_version = "manual"
    row.attributed_at = now
    if (notes or "").strip():
        row.evidence = list(row.evidence or []) + [
            {"kind": "manual", "ref": actor or "未知操作人", "fact": notes.strip()}]
    await session.flush()
    await session.commit()
    return {"created": created, "review_id": review.id,
            "attribution": _attribution_to_dict(row)}

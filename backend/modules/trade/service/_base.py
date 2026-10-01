"""共享内核：异常类型、时间工具、ORM→dict 序列化、按店铺加载。

本层不依赖包内其它子模块（唯一叶子），其余子模块都从它取。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.logger import get_logger
from core.tenant.scoping import scope_condition
from datetime import datetime
from modules.trade.db_model import CAUSE_LABELS, CustomerReviewRecord, OrderItemRecord, OrderRecord, ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord, SOURCE_MOCK_SEED
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional


_log = get_logger("modules.trade.service")




class MissingShopContext(Exception):
    """缺少租户上下文 —— 按 fail-closed 抛错，不写没有归属的行。"""




class MissingSiblingForReview(Exception):
    """差评拿不到可归因的订单/物流证据 —— 由调用方决定是否降级为 unknown。"""




class CompensationOverBudget(Exception):
    """规则命中的金额超过 hard cap —— 显式拒绝，不做静默截断。"""




# ============================================================ 时间工具

def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """把 ISO 串解析成 datetime；拿不到返回 None（**不抛**，本模块的时间都是可选事实）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("T", " "))
    except (ValueError, AttributeError):
        return None




def days_between(start: Optional[str], end: Optional[str]) -> Optional[int]:
    """两个 ISO 串相差的**整天数**（向上取整）；任一侧缺失 ⇒ None（事实不足，不猜）。"""
    a, b = parse_iso(start), parse_iso(end)
    if a is None or b is None:
        return None
    delta = b - a
    return delta.days + (1 if delta.seconds else 0)




def compute_transit_and_delay(
    shipped_at: Optional[str],
    promised_at: Optional[str],
    delivered_at: Optional[str],
) -> tuple[Optional[int], Optional[int]]:
    """(运输天数, 迟到天数) —— **唯一计算口径**。

    delay_days > 0 ⇒ 迟到；== 0 ⇒ 刚好；< 0 ⇒ 提前。
    缺 `delivered_at`（还没送到）⇒ 两者都 None：**没有结论**，而不是 0。
    ★ 返回 None 与返回 0 的意义完全不同，调用方不许用 `or 0` 抹平。
    """
    if not delivered_at:
        return None, None
    return days_between(shipped_at, delivered_at), days_between(promised_at, delivered_at)




# ============================================================ 归因：人工补标（第 304 轮后半）
#
# ★ 为什么要有这个入口（真库实测）：风险识别命中 12 条中差评，处置台账却只有 5 条。
#   不是数据不互通 —— 风险识别**不要求有归因**，而处置链只扫
#   `primary_cause != "unknown"` 的那批。12 条里 **8 条是 unknown** ⇒ 处置链压根扫不到。
#   自动归因判不出来就停在 unknown，而**没有任何入口**能把它推进一步，
#   于是「报了 12 条、只能处置 5 条」看起来像 bug。
# ★ 落 `method="manual"`：`sync._attribute` 对 manual 行**原样返回不覆盖** ——
#   否则下一次自动同步就把人工判定冲回 unknown 了（本仓：人工 > 自动）。

class AttributionError(Exception):
    """归因取值不合法 —— 调用方映射成 **4xx**。"""




class AttributionNotFound(Exception):
    """评价不存在**或**不属于本店 —— 两者同一句（可区分即可枚举）。"""




# ============================================================ 补偿规则
#
# ★ 为什么补 CRUD（第 304 轮后半）：`compensation_rules` 一直是
#   「有表、有种子、有匹配逻辑、**没有端点也没有界面**」。后果是失败提示让人
#   「到补偿规则里配一条」，而那个面板根本不存在 —— 负指令：把人引向死路。
#   只改文案不补入口，等于承认「这一类差评永远给不出方案」。

class RuleError(Exception):
    """规则取值不合法 —— 4xx。"""




class RuleNotFound(Exception):
    """规则不存在**或**不属于本店 —— 两者同一句（防枚举）。"""




class RuleConflict(Exception):
    """同店同 code 已存在 —— 4xx（唯一约束兜底，这里给可读文案）。"""




class DispositionError(Exception):
    """处置的状态/取值不合法 —— 调用方映射成 **4xx**（不是 5xx）。"""




class DispositionNotFound(Exception):
    """处置不存在**或**不属于当前店铺 —— 两者**同一句**。

    ★ 刻意不分两种文案：可区分就等于能拿 id 逐位枚举别家店铺的差评。
    """




async def _load_review_scoped(
    session: AsyncSession, shop_id: str, review_id: str,
) -> Optional[CustomerReviewRecord]:
    """按 `id` 或 `external_review_id` 取本店评价 —— 归属过滤是硬条件。"""
    return (await session.execute(
        select(CustomerReviewRecord).where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            (CustomerReviewRecord.id == review_id)
            | (CustomerReviewRecord.external_review_id == review_id),
        ))
    )).scalars().first()




# ============================================================ 序列化

def _order_to_dict(r: OrderRecord) -> dict:
    return {
        "id": r.id, "external_order_id": r.external_order_id, "platform": r.platform,
        "order_status": r.order_status, "buyer_name": r.buyer_name,
        "purchase_at": r.purchase_at, "promised_at": r.promised_at,
        "shipped_at": r.shipped_at, "delivered_at": r.delivered_at,
        "transit_days": r.transit_days, "delay_days": r.delay_days,
        "order_total": r.order_total, "currency": r.currency,
        "fulfillment_channel": r.fulfillment_channel,
        "ship_country": r.ship_country, "ship_state": r.ship_state,
        "source": r.source,
    }




def _item_to_dict(r: OrderItemRecord) -> dict:
    return {
        "sku": r.sku, "asin": r.asin, "title": r.item_title,
        "quantity": r.quantity, "unit_price": r.unit_price,
        "item_total": r.item_total, "currency": r.currency,
    }




def _shipment_to_dict(r: ShipmentRecord) -> dict:
    return {
        "id": r.id, "carrier": r.carrier, "tracking_no": r.tracking_no,
        "ship_status": r.ship_status, "shipped_at": r.shipped_at,
        "promised_at": r.promised_at, "delivered_at": r.delivered_at,
        "transit_days": r.transit_days, "delay_days": r.delay_days,
        "last_event_at": r.last_event_at, "last_location": r.last_location,
        "last_event_text": r.last_event_text, "events": r.events or [],
        "source": r.source,
    }



def _review_to_dict(
    r: CustomerReviewRecord, *, match_kind: Optional[str] = None,
    matched_sku_id: Optional[str] = None,
) -> dict:
    """评价的**唯一**序列化口径。

    ★ `match_kind` / `matched_sku_id` 回答「这条差评靠什么对上了产品」
      （界面要显示「命中 ASIN / SKU 码」）。不为此另起一个 `_review_card_dict`
      —— 那会让同一映射出现第二份实现，改一处漏一处。
    """
    return {
        "id": r.id, "external_review_id": r.external_review_id,
        "order_id": r.order_id, "sku": r.sku, "asin": r.asin,
        "product_title": r.product_title, "rating": r.rating,
        "title": r.title, "body": r.body, "language": r.language,
        "review_at": r.review_at, "verified_purchase": r.verified_purchase,
        "buyer_name": r.buyer_name, "status": r.status, "source": r.source,
        "matched_sku_id": matched_sku_id, "match_kind": match_kind,
    }




def _attribution_to_dict(r: ReviewAttributionRecord) -> dict:
    return {
        "primary_cause": r.primary_cause,
        "primary_cause_label": CAUSE_LABELS.get(r.primary_cause, r.primary_cause),
        "causes": r.causes or [], "confidence": r.confidence,
        "evidence": r.evidence or [], "method": r.method,
        "rule_version": r.rule_version, "attributed_at": r.attributed_at,
    }




def _disposition_to_dict(
    r: ReviewDispositionRecord, review: Optional[CustomerReviewRecord] = None,
) -> dict:
    """处置的**唯一**序列化口径（service / router / 工具 / 前端共用这一份）。

    ★ `review` 可选：列表页与详情抽屉要显示「这是哪条差评」，但不能为此
      再写一个 `_disposition_card_dict` —— 那就成了同一映射两份实现。
    """
    return {
        "id": r.id, "review_id": r.review_id, "status": r.status,
        "channels": r.channels or [],
        "compensation": r.compensation or {}, "coupon_code": r.coupon_code,
        "ticket_id": r.ticket_id, "issued_at": r.issued_at,
        # ★ 平台执行回执（第 304 轮）：`executed_at` 为空 = 平台上**还没**执行完，
        #   与「`issued_at` 有值（本地已核准）」是两件事 —— 界面不许把两者画成
        #   同一个状态，否则「已发放」又会变成一次语义欺诈。
        "execution_mode": r.execution_mode, "platform_ref": r.platform_ref,
        "executed_by": r.executed_by, "executed_at": r.executed_at,
        "receipt_note": r.receipt_note,
        "reply_draft_en": r.reply_draft_en, "reply_draft_zh": r.reply_draft_zh,
        "approved_by": r.approved_by, "notes": r.notes,
        "created_at": r.created_at, "updated_at": r.updated_at,
        "review": _review_to_dict(review) if review is not None else None,
    }




#: 给上层（工具 / 前端）用的统一判据：当前这批数据是不是 mock
def is_mock_source(source: Optional[str]) -> bool:
    return source == SOURCE_MOCK_SEED

"""
交易履约 + 买家反馈域 —— 服务层（唯一计算口径）

====================================================
★ 为什么要有一个 service 而不是「工具里现算」
====================================================
「是不是迟了」「赔多少」「这个 SKU 健康吗」这三个判断，本模块**只在这里算一次**。
工具层 / 路由层 / seed 全部调用本文件的函数。

理由不是洁癖。让同一判断散落在 Agent 提示词、工具函数、seed 脚本三处，
后果已经在 `cs-refund-playbook` 那类技能身上发生过一次：
技能正文要求「引用订单/物流证据判断责任归属」，而没有任何地方能产出那个证据
=> 要求变成口号。判断若不能被某个函数断言，它就只是文案。

====================================================
★ 三条硬口径（改动前请三思）
====================================================
1. **归因的证据优先于关键词。**
   先看数据仓库里到底有没有「这单迟了 5 天」这种**事实**；有证据就按证据归类，
   只有在拿不到订单/物流时才退回文本关键词。反过来会让「按关键词猜」盖过
   「按事实判」—— 那是把 LLM 的读后感当证据。

2. **拿不到就报 'unknown'，不许猜。**
   本仓对「静默退化」一贯 fail-closed；`unknown` 是**合法结果**，也必须能被断言
   （见 `ATTRIBUTION_CAUSES` 里的注释）。

3. **补偿金额超 `budget_cap` 必须显式报错，不许悄悄按上限赔。**
   悄悄截断会让「规则说赔 8 块」与「实际赔了 5 块」都不报错地并存，
   审计时无从发现。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import String, and_, desc, func, literal, or_, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import get_logger
from core.tenant.scoping import scope_condition
from modules.products import SkuRecord, SpuRecord
# ★ 风险话术识别（第 299 轮 P0/P1）：本模块**只读**消费它的判定能力。
#   注意方向：`risk_scan` 不 import `service`（叶子模块），因此这里没有循环。
from modules.trade import risk_scan
from modules.trade.db_model import (
    ATTRIBUTION_CAUSES, CAUSE_LABELS,
    CompensationRuleRecord, CustomerReviewRecord, OrderItemRecord, OrderRecord,
    ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord,
    SkuHealthScoreRecord, SOURCE_MOCK_SEED,
)

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
    from .sync import MANUAL_METHOD, attribution_row_id

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


#: `_conditions_match` **只认**这三个键。配了别的键会**静默失效**（永不判到），
#: 比报错更糟 —— 用户以为自己加了限制，其实规则变成了一条无条件规则。
CONDITION_KEYS: tuple[str, ...] = ("max_rating", "min_delay_days", "verified_purchase")

#: `action.type` 值域 —— 决定 `_channels_from_action` 推导出哪些通道
ACTION_TYPES: tuple[str, ...] = ("coupon", "refund", "none")


def _rule_to_dict(r: CompensationRuleRecord) -> dict:
    """规则的**唯一**序列化口径（list / create / update / 前端共用这一份）。"""
    return {
        "id": r.id, "code": r.code, "name": r.name,
        "cause": r.cause, "cause_label": CAUSE_LABELS.get(r.cause, r.cause),
        "priority": r.priority, "conditions": r.conditions or {},
        "action": r.action or {}, "budget_cap": r.budget_cap or 0,
        "enabled": bool(r.enabled), "notes": r.notes or "",
        "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _rule_row_id(shop_id: str, code: str) -> str:
    """与 `seed.py::_ensure_rules` 同构（`crule-<shop>-<code>`）—— 不另起一套。"""
    return f"crule-{shop_id}-{code}"


def _normalize_code(code: str) -> str:
    """code 规范化：小写 + 去空白。

    ★ 为什么不接受任意字符：code 会进主键 id，空格 / 大写会让
      「补的规则」与「匹配时查的 code」在不同入口长得不一样。
    """
    c = (code or "").strip().lower()
    if not c:
        raise RuleError("规则 code 不能为空")
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in c):
        raise RuleError(
            f"规则 code 只允许小写字母 / 数字 / 连字符 / 下划线：{code!r}")
    return c


def _validate_rule_shape(*, cause, conditions, action, priority, budget_cap) -> None:
    """形状校验集中在一处 —— create 与 update 共用（同一判定两份实现 ⇒ 必有一份测不到）。"""
    if cause not in ATTRIBUTABLE_CAUSES:
        raise RuleError(
            f"规则针对的归因不在值域内：{cause!r}；可选：{' / '.join(ATTRIBUTABLE_CAUSES)}"
            "（unknown 没有规则可配：判不出成因的差评本来就不走补偿链）")
    for k in (conditions or {}):
        if k not in CONDITION_KEYS:
            raise RuleError(
                f"未知条件键 {k!r}；只认 {' / '.join(CONDITION_KEYS)} —— "
                "写别的键不会报错，只会**永远判不到**（静默失效比报错更糟）")
    act = dict(action or {})
    kind = (act.get("type") or "none").lower()
    if kind not in ACTION_TYPES:
        raise RuleError(f"未知补偿方式 {act.get('type')!r}；可选：{' / '.join(ACTION_TYPES)}")
    if "amount" in act and act.get("amount") is not None:
        try:
            amt = float(act["amount"])
        except (TypeError, ValueError):
            raise RuleError(f"金额不是数字：{act['amount']!r}")
        if amt < 0:
            raise RuleError(f"金额不能为负：{amt}")
    try:
        prio = int(priority)
    except (TypeError, ValueError):
        raise RuleError(f"优先级不是整数：{priority!r}")
    if prio < 0:
        raise RuleError(f"优先级不能为负：{prio}")
    try:
        cap = float(budget_cap or 0)
    except (TypeError, ValueError):
        raise RuleError(f"单笔上限不是数字：{budget_cap!r}")
    if cap < 0:
        raise RuleError(f"单笔上限不能为负：{cap}")


async def list_compensation_rules(
    session: AsyncSession, shop_id: str, *, include_disabled: bool = True,
) -> list[dict]:
    """本店全部补偿规则（按 cause → priority 排序）。

    ★ `include_disabled` 默认 True：配置界面要能看见**停用**的规则，
      否则「我明明配过」会变成一条谁也找不到的记录。
    """
    q = select(CompensationRuleRecord).where(
        scope_condition(CompensationRuleRecord, shop_id))
    if not include_disabled:
        q = q.where(CompensationRuleRecord.enabled.is_(True))
    rows = (await session.execute(q.order_by(
        CompensationRuleRecord.cause.asc(),
        CompensationRuleRecord.priority.asc(),
        CompensationRuleRecord.id.asc(),
    ))).scalars().all()
    return [_rule_to_dict(r) for r in rows]


async def create_compensation_rule(
    session: AsyncSession,
    shop_id: str,
    *,
    code: str,
    name: str,
    cause: str,
    priority: int = 100,
    conditions: Optional[dict] = None,
    action: Optional[dict] = None,
    budget_cap: float = 0,
    enabled: bool = True,
    notes: str = "",
) -> dict:
    """新建一条补偿规则。

    ★ 形状校验走 `_validate_rule_shape`（与 update 同一份），不在这里另写一遍。
    ★ 同店同 code ⇒ `RuleConflict`（不是静默覆盖：覆盖会让「我配的 8 块」
      变成「别人配的 30 块」而没人知道）。
    """
    c = _normalize_code(code)
    _validate_rule_shape(cause=cause, conditions=conditions, action=action,
                         priority=priority, budget_cap=budget_cap)
    row_id = _rule_row_id(shop_id, c)
    exists = (await session.execute(
        select(CompensationRuleRecord).where(CompensationRuleRecord.id == row_id)
    )).scalar_one_or_none()
    if exists is not None:
        raise RuleConflict(
            f"本店已经有 code 为 {c!r} 的规则（{exists.name}）—— "
            "同名规则请改用它，或换一个 code（不允许静默覆盖）")

    now = datetime.utcnow().isoformat()
    row = CompensationRuleRecord(id=row_id)
    row.shop_id = shop_id
    row.code = c
    row.name = (name or "").strip() or c
    row.cause = cause
    row.priority = int(priority)
    row.conditions = dict(conditions or {})
    row.action = dict(action or {})
    row.budget_cap = float(budget_cap or 0)
    row.enabled = bool(enabled)
    row.notes = notes or ""
    row.created_at = now
    row.updated_at = now
    session.add(row)
    await session.flush()
    await session.commit()
    return _rule_to_dict(row)


async def update_compensation_rule(
    session: AsyncSession,
    shop_id: str,
    rule_id: str,
    *,
    name: Optional[str] = None,
    cause: Optional[str] = None,
    priority: Optional[int] = None,
    conditions: Optional[dict] = None,
    action: Optional[dict] = None,
    budget_cap: Optional[float] = None,
    enabled: Optional[bool] = None,
    notes: Optional[str] = None,
) -> dict:
    """部分更新一条规则（**只改传进来的字段**）。

    ★ `code` **不可改**：它是主键 id 的一部分，改 code 等于换一行，
      而旧 code 已经被处置记录里的 `rule_code` 引用着（改了就对不上账）。
      要换 code 就删了重建 —— 让这一步显式发生，而不是悄悄变成「新增一行」。
    ★ 合并后的整体仍要过一遍 `_validate_rule_shape`：
      只校验「本次传的字段」会漏掉「新条件 + 旧金额」这种组合。
    """
    row = await _load_rule_scoped(session, shop_id, rule_id)
    merged_cause = cause if cause is not None else row.cause
    merged_cond = conditions if conditions is not None else (row.conditions or {})
    merged_action = action if action is not None else (row.action or {})
    merged_prio = priority if priority is not None else row.priority
    merged_cap = budget_cap if budget_cap is not None else (row.budget_cap or 0)
    _validate_rule_shape(cause=merged_cause, conditions=merged_cond, action=merged_action,
                         priority=merged_prio, budget_cap=merged_cap)

    if name is not None:
        row.name = name.strip() or row.code
    if cause is not None:
        row.cause = cause
    if priority is not None:
        row.priority = int(priority)
    if conditions is not None:
        row.conditions = dict(conditions)
    if action is not None:
        row.action = dict(action)
    if budget_cap is not None:
        row.budget_cap = float(budget_cap)
    if enabled is not None:
        row.enabled = bool(enabled)
    if notes is not None:
        row.notes = notes
    row.updated_at = datetime.utcnow().isoformat()
    await session.flush()
    await session.commit()
    return _rule_to_dict(row)


async def delete_compensation_rule(session: AsyncSession, shop_id: str, rule_id: str) -> dict:
    """删除一条规则。

    ★ 硬删（不是软删）：处置记录里存的是**展开后的方案快照**（`compensation`），
      删规则不会让已生成的处置变成孤儿。而「停用」（`enabled=False`）是
      另一件事 —— 界面上默认给停用，删除要二次确认。
    """
    row = await _load_rule_scoped(session, shop_id, rule_id)
    code = row.code
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "id": row.id, "code": code}


async def _load_rule_scoped(
    session: AsyncSession, shop_id: str, rule_id: str,
) -> CompensationRuleRecord:
    """按 id 取规则并校验归属（跨域读写的唯一入口）。"""
    if not (shop_id or "").strip():
        raise MissingShopContext("缺少店铺上下文，无法定位规则")
    row = (await session.execute(
        select(CompensationRuleRecord)
        .where(scope_condition(CompensationRuleRecord, shop_id))
        .where(CompensationRuleRecord.id == rule_id)
    )).scalar_one_or_none()
    if row is None:
        raise RuleNotFound(f"本店铺下查不到这条规则（不存在或不属于当前店铺）：{rule_id}")
    return row


async def list_enabled_rules_for_cause(
    session: AsyncSession, shop_id: str, cause: str,
) -> list[CompensationRuleRecord]:
    """某个 cause 下**启用**的规则（按 priority 升序）—— 条件是否满足**不**在这里判。

    ★ 为什么要单独抽出来（第 304 轮实测）：`match_compensation_rule` 返回 `None`
      有**两种**成因，而它们对用户下一步动作**完全不同**：
        ① 该 cause 一条启用规则都没有    ⇒ 要**新增**规则；
        ② 有规则，但这条差评不满足其条件 ⇒ 新增规则**解决不了**，要看事实 / 改条件。
      此前二者共用一句「没有针对「X」的启用规则」——对 ② 是**假陈述**：
      实测 `logistics_delay` 明明有一条启用规则（`logistics-delay-minor`，
      条件 `min_delay_days=3`），界面却报「没有启用规则」，
      把人引向「再配一条」这个**永远无效**的动作。
    ★ 候选集只此一份实现：诊断分支与匹配分支必须看**同一个**集合，
      否则「有规则但条件不符」会被误判成「没规则」。
    """
    return (await session.execute(
        select(CompensationRuleRecord)
        .where(and_(
            scope_condition(CompensationRuleRecord, shop_id),
            CompensationRuleRecord.cause == cause,
            CompensationRuleRecord.enabled.is_(True),
        ))
        .order_by(CompensationRuleRecord.priority.asc(),
                  CompensationRuleRecord.id.asc())
    )).scalars().all()


async def match_compensation_rule(
    session: AsyncSession,
    shop_id: str,
    cause: str,
    *,
    rating: Optional[int] = None,
    delay_days: Optional[int] = None,
    verified_purchase: Optional[bool] = None,
) -> Optional[CompensationRuleRecord]:
    """按 cause + 条件匹配**优先级最高**的一条可用规则。

    ★ 多条规则命中同一个 cause 是**合法**的（同因不同伤：迟到 3 天 vs 迟到 10 天）；
      取谁由 `priority`（小者优先）决定 —— 不给 LLM 留「挑一个顺眼的」空间。
    """
    for rule in await list_enabled_rules_for_cause(session, shop_id, cause):
        if _conditions_match(rule.conditions or {}, rating, delay_days, verified_purchase):
            return rule
    return None


def _conditions_match(
    conditions: dict,
    rating: Optional[int],
    delay_days: Optional[int],
    verified_purchase: Optional[bool],
) -> bool:
    """条件逐条判。★ 条件里写了某条但**取不到对应事实** ⇒ 判不通过（fail-closed），
    不允许「没数据就当满足」。
    """
    if "max_rating" in conditions and rating is not None:
        if rating > int(conditions["max_rating"]):
            return False
    if "min_delay_days" in conditions:
        if delay_days is None or delay_days < int(conditions["min_delay_days"]):
            return False
    if "verified_purchase" in conditions:
        want = bool(conditions["verified_purchase"])
        if verified_purchase is None or verified_purchase is not want:
            return False
    return True


def apply_compensation_rule(rule: CompensationRuleRecord) -> dict:
    """把规则的 `action` 展开成**可执行**的处置方案。

    ★ 超 `budget_cap` ⇒ 抛 `CompensationOverBudget`（显式拒绝），
      不做「悄悄按上限赔」的静默降级 —— 那是把权限问题伪装成成功。
    """
    action = dict(rule.action or {})
    amount = float(action.get("amount") or 0)
    cap = float(rule.budget_cap or 0)
    # ★ `budget_cap <= 0` 的语义是「未设上限」而不是「上限 0 元」 —— 见 db_model 注释。
    #   写成 `cap > 0 and amount > cap` 才不会把「没设上限」误判成「一分钱都不能赔」。
    if cap > 0 and amount > cap:
        raise CompensationOverBudget(
            f"规则 {rule.code}（{rule.name}）命中金额 {amount} 超过单笔上限 {cap}，"
            f"已拒绝执行 —— 请调整规则限额或改派其他规则"
        )
    return {
        "channels": _channels_from_action(action),
        "compensation": action,
        "rule_code": rule.code,
        "rule_name": rule.name,
        "budget_cap": cap,
    }


def _channels_from_action(action: dict) -> list[str]:
    ch = ["reply"]
    kind = (action.get("type") or "").lower()
    if kind == "coupon":
        ch.append("coupon")
    elif kind == "refund":
        ch.append("refund")
    if action.get("reship"):
        ch.append("reship")
    return ch


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


# ============================================================ 风险话术扫描（第 299 轮 P1）
#
# ★ 为什么这段住在 service 而不是 router：
#   「按风险排序」与「deep 但无凭据 ⇒ degraded + 未定论」都是**判定**，不是接线。
#   写进 router ⇒ Agent 工具 / 脚本 / 端点各写一份，其中至少一份永远测不到
#   （本仓铁律：同一判定两份实现）。P0 的 `risk_scan` 只回答「一条文本是什么」，
#   这里回答「一批差评怎么排序、什么时候算**没扫成**」。
# ★ 零写操作：只读 `customer_reviews`；不碰 `review_dispositions`、不发券、不退款。

#: 浅层扫描（规则通道，零模型成本）单次上限。
RISK_SCAN_MAX_LIMIT = 50
#: 深度扫描（LLM）单次上限。
#: ★ 第 300 轮起语义通道是**批量**的（一次调用判 ≤`risk_scan.RISK_SCAN_BATCH_CHUNK`
#:   条），不再是「每条一次调用」；上限仍然保留 —— 它限的是**输入规模**
#:   （越长越容易输出截断，而截断会让整包判 unknown），
#:   而且「一个 GET 就能烧掉几百次配额」这件事并没有消失。
RISK_SCAN_MAX_LIMIT_DEEP = 20

#: 排序权重：风险在前、未定论居中、干净在后。
#: ★ 「未定论」必须排在「干净」**前面**：前者要人补判，后者不用。
#:   两者同级排序 ⇒「算法不敢定」淹没在长尾里，fail-closed 就白写了。
_RISK_DECISION_RANK = {
    risk_scan.DECISION_RISK: 0,
    risk_scan.DECISION_UNKNOWN: 1,
    risk_scan.DECISION_CLEAN: 2,
}


def _llm_configured() -> bool:
    """LLM 凭据是否已配置 —— **唯一判据**，与 `main._probe_llm` 同口径。

    ★ 此处**不发网络请求**：它回答的是「语义通道能不能开」，不是「模型此刻可用」。
      后者属于运行期事实，要用运行期手段观测，不能靠一次配置读取冒充。
    """
    from core.config import config as app_config
    return bool((app_config.dashscope_api_key or "").strip())


def _review_risk_text(item: dict) -> str:
    """把一条评价拼成待扫描文本（title + body）。

    ★ 两段都空 ⇒ 返回空串，由调用方判 `unknown`
      ——「没正文可判」与「判了没风险」是两件事，不可合并（本仓三态铁律）。
    """
    parts = (str(item.get("title") or "").strip(), str(item.get("body") or "").strip())
    return "\n".join(p for p in parts if p)


def _risk_block_from_scan(res: risk_scan.ScanResult) -> dict:
    """`ScanResult` → 上屏用的 dict —— **唯一**投影口径（端点 / 工具 / 前端共用）。"""
    return {
        "decision": res.decision,
        "level": res.top_level,
        "level_label": risk_scan.LEVEL_LABELS.get(res.top_level, res.top_level),
        "suggested_action": risk_scan.SUGGESTED_ACTION.get(res.top_level, ""),
        "is_risk": res.is_risk,
        "categories": res.categories,
        "risk_categories": res.risk_categories,
        "hits": [h.as_dict() for h in res.hits],
        "channel": res.channel,
        "note": res.note,
    }


def _unscannable_block(reason: str) -> dict:
    """扫不成时**诚实**的结果：判 `unknown`，绝不写成「无风险」。"""
    res = risk_scan.ScanResult(
        hits=[risk_scan.RiskHit(
            category=risk_scan.CAT_EMOTION, level=risk_scan.LEVEL_UNKNOWN,
            evidence=[], channel="llm", note=reason,
        )],
        channel="llm", decision=risk_scan.DECISION_UNKNOWN, note=reason,
    )
    return _risk_block_from_scan(res)


async def scan_reviews_risk(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, days: int = 30,
    limit: int = 20, offset: int = 0, deep: bool = False,
) -> dict:
    """对本店近期中差评逐条跑**风险话术识别**，按「风险 → 未定论 → 干净」排序返回。

    ★★ 分层（第 300 轮）：浅层是**默认**，语义永远是**按需**的
    ----------------------------------------------------------
      ① 规则通道**全量先跑**：零成本（实测 0.15 ms/条），且由它决定「谁不用送语义」。
      ② `rule.risk_categories` 非空的条目**不再送语义**。这不是「省了什么」——
         `fuse()` 在命中四类时**提前 return**、压根不读 LLM 的 decision，
         所以「不送」是**无操作**。
         ★ 短路条件必须是 `risk_categories`（四类），**不能**是 `categories`：
           后者把「只命中 r5（高情绪）」的条目一起短路掉，而那时 `fuse()`
           **要**读 LLM 的结论（规则判 clean、LLM 可能报 risk）⇒ 实测 3 格
           decision 劣化（2 格漏报 + 1 格把 unknown 洗成 clean）。
           同构错案见第 246 轮「关键词短路抢在技能注入之前 return」。
      ③ 其余条目**打包成一次批量语义调用**，按序号回填；缺项 / 解析失败一律
         fail-closed 到 `unknown`，绝不猜 `clean`。
      ⇒ 实测：20 条从 43.4 s（逐条串行）降到约 2 s。

    ★★ 三件事必须一起做（少一件这个视图就是错的）
    ------------------------------------------------
    1. **排序在后端**。前端拿到什么顺序就按什么顺序渲染，**不得**自己按
       `risk.decision` 重排 —— 那是「同一判定两份实现」，改了后端忘前端时
       界面会与报告不一致，且谁都不报错。
    2. **deep 但无凭据 ≠ 无风险**。语义通道被请求却没有 LLM 凭据时，
       `degraded=True` 且**每条判 `unknown`**。悄悄退回「只跑规则」会让
       「这次没扫」伪装成「这家店很干净」—— 本仓最忌讳的一类静默退化。
       （规则通道**真命中**的条目仍照实报 `risk`：那是真信号，不是降级。）
    3. **排序作用在本页内**（`limit`/`offset` 之后）。跨页置顶要求全量扫描再分页，
       批量语义下成本同样随条数上升 ⇒ P1 不引入，接口语义如实写在端点文档里。

    返回 `items`（每条 = `_review_to_dict` 的原字段 + `risk` 块）以及
    `total`（真实条数，不受 limit 截断）/ `scanned` / `risk_count` /
    `unknown_count` / `clean_count` / `deep` / `llm_used` / `degraded`，
    再附 `category_labels` / `level_labels`（中文名真源，前端不得自写一份）。

    ★ 分层的**可观测读数**：`semantic_sent`（送进语义通道的条数）/
      `semantic_skipped`（被规则预筛跳过、因而没花钱的条数）/ `llm_calls`
      （实际发了几次批量请求）。三个数不报 ⇒ 老板没法判断「省下来的钱花在哪」，
      而 `llm_used=True` + `llm_calls=0` 这种组合也就无从解释。
    """
    cap = RISK_SCAN_MAX_LIMIT_DEEP if deep else RISK_SCAN_MAX_LIMIT
    eff_limit = max(1, min(int(limit), cap))
    rows = await list_recent_negative_reviews(
        session, shop_id, max_rating=max_rating, days=days,
        limit=eff_limit, offset=offset,
    )
    total = await count_recent_negative_reviews(
        session, shop_id, max_rating=max_rating, days=days,
    )

    # ★ fail-closed 的判定点：**在调用 LLM 之前**问「语义通道开得起来吗」。
    #   放在调用之后（靠 catch 异常）会把「没凭据」与「模型抽风」混成一类。
    degraded = bool(deep) and not _llm_configured()
    llm_used = bool(deep) and not degraded
    llm = None
    if llm_used:
        from ai_infra.llm import get_llm
        # ★ `max_tokens` 不在这里传：`get_llm()` 按模型名缓存单例，建实例之后再传
        #   参数是无效的；批量通道把 `max_tokens` 作为 per-call 参数传给
        #   `structured_chat`（见 `risk_scan._scan_llm_batch_chunk`）。
        llm = get_llm(model="qwen-plus", temperature=0.0)
    if degraded:
        _log.warning(
            "风险扫描：请求 deep 但未配置 LLM 凭据 shop=%s ⇒ 显式降级为未定论", shop_id,
        )

    # ---- 阶段 1：浅层（规则）通道**全量**先跑 ----
    #   ★ 三个出口（degraded / 语义 / 浅层）都要它 ⇒ 只算一次。
    #     各写一份就是「同一判定三份实现」，改了这边忘那边时谁都不报错。
    #   ★ 空正文 ⇒ `None`（不是「判成 clean」）：三态不可压成两态。
    texts = [_review_risk_text(r) for r in rows]
    rules = [risk_scan.scan_text(t, channel="rule") if t else None for t in texts]

    # ---- 阶段 2：只把「浅层没判出四类风险」的送进语义通道，且一次打包 ----
    pending = (
        [i for i, r in enumerate(rules) if r is not None and not r.risk_categories]
        if llm_used else []
    )
    llm_results: dict[int, risk_scan.ScanResult] = {}
    if pending:
        got = await risk_scan.scan_llm_batch([texts[i] for i in pending], llm=llm)
        # ★ 用 `zip` 按下标回填：`scan_llm_batch` 的契约就是「等长同序」，
        #   缺项已经在它内部 fail-closed 成了 unknown ⇒ 这里不会少一条。
        llm_results = dict(zip(pending, got))

    # ---- 阶段 3：逐条投影 ----
    items: list[dict] = []
    for i, row in enumerate(rows):
        rule = rules[i]
        if rule is None:
            block = _unscannable_block("该条评价无正文可判（标题与正文均为空）")
        elif degraded:
            # 降级下仍跑规则通道：真命中的（威胁 / 索赔 / 投诉）照实报，
            # 不能因为「语义通道缺勤」把真信号一起埋掉。
            if rule.is_risk:
                block = _risk_block_from_scan(rule)
                block["note"] = f"{block['note']}｜语义通道不可用，仅规则命中".strip("｜")
            else:
                block = _unscannable_block(
                    "语义通道不可用（未配置 LLM 凭据）—— 本条未定论，需人工判"
                )
        elif i in llm_results:
            # ★ `fuse([rule, llm])` 与旧的 `fuse([naive, rule, llm])` 等价：
            #   `naive` 通道被 `fuse()` 的拒绝名单挡在外面（反面基线，不进并集）。
            block = _risk_block_from_scan(risk_scan.fuse([rule, llm_results[i]]))
        elif llm_used:
            # 规则通道已判出四类 ⇒ 语义不重复判。
            # ★ 通道如实写 `rule`：这里**没有**发生融合，写 `fuse` 是假话。
            rule.note = "规则通道已判定四类风险，语义通道未重复判定（分层短路）"
            block = _risk_block_from_scan(rule)
        else:
            block = _risk_block_from_scan(rule)
        item = dict(row)
        item["risk"] = block
        items.append(item)

    # ★ 两段排序（Python 的 sort 稳定）：先按时间新→旧定组内序，再按定论分组，
    #   组内保持刚排好的时间序。合成单 key 也行，但 `review_at` 是字符串日期，
    #   取不了负号，两段更直白也不易写错。
    items.sort(key=lambda x: str(x.get("review_at") or ""), reverse=True)
    items.sort(key=lambda x: _RISK_DECISION_RANK.get(
        str((x.get("risk") or {}).get("decision") or ""), 9))

    def _count(decision: str) -> int:
        return sum(
            1 for x in items
            if str((x.get("risk") or {}).get("decision") or "") == decision
        )

    return {
        "items": items,
        "total": total,
        "scanned": len(items),
        "risk_count": _count(risk_scan.DECISION_RISK),
        "unknown_count": _count(risk_scan.DECISION_UNKNOWN),
        "clean_count": _count(risk_scan.DECISION_CLEAN),
        "deep": bool(deep),
        "llm_used": llm_used,
        "degraded": degraded,
        # ★ 「本页被**单次上限**截断」—— 只有上限真的成了约束、且后面确实
        #   还有没扫到的条目，才算截断。
        #   不能用 `eff_limit < limit`：面板固定传 limit=100（deep 上限 20），
        #   那样即使库里只有 3 条也会亮出「已达单次上限」，界面变成
        #   「本页扫描 3 / 共 3 条（已达单次上限）」—— 是一句**假话**。
        "capped": eff_limit == cap and (offset + len(items)) < total,
        # ★ 分层的可观测读数（见 docstring）：省了多少条、实际发了几次调用。
        #   `semantic_skipped` 只在语义通道真开启时才有意义 —— 浅层压根没打算
        #   调语义，那时报「跳过 N 条」会让老板以为省了钱（其实那条路一分不花）。
        "semantic_sent": len(pending),
        "semantic_skipped": (
            sum(1 for r in rules if r is not None and r.risk_categories)
            if llm_used else 0
        ),
        "llm_calls": risk_scan.batch_chunk_count(len(pending)),
        "categories": list(risk_scan.RISK_CATEGORIES),
        "category_labels": dict(risk_scan.CATEGORY_LABELS),
        "level_labels": dict(risk_scan.LEVEL_LABELS),
        "max_rating": max_rating,
        "days": days,
        "limit": eff_limit,
        "offset": offset,
    }


# ============================================================ 「重复问题」的阈值与结论标签
#
# ★★ 为什么这组常量必须在 `count_repeat_issues` **之前**（第 294 轮修）
#   阈值此前有**两份**：`count_repeat_issues` 里写死 `>= 3`，判定端点那边又有一个
#   同名常量。反向注入（把常量改成 5）**没能打红**判定用例 —— 因为真判据走的是
#   函数里那个硬编码 3。两个数并存、都不报错，只有「两条通道结论不同」这一个症状。
#   现在唯一的定义在这里，函数与判定端点都引用它。

#: 同一归因在窗口内出现多少次算「重复问题」。
#: ★ 与 `cs-negative-review-triage` 技能正文写的「≥3 次」**必须是同一个数**：
#:   技能写 3、代码写 5 ⇒ 两条通道结论不同，而用户只会看到其中一个。
#:   `tests/test_trade_systemic_check.py` 有一条判据钉这个同步关系。
REPEAT_ISSUE_THRESHOLD = 3

#: 单期「中差评占比」到这个水位算趋势性问题（与健康分环比同为**趋势**判据）。
#: 为什么不是「健康分绝对值低」：绝对值依赖 `score_from_parts` 的量纲，
#: 而这里要回答的是「有没有在变坏」—— 环比与占比才是同量纲可比的那部分。
SYSTEMIC_NEGATIVE_RATE = 0.3

#: 判定结论的中文名 —— **唯一真源**。前端从端点拿 `verdict_label`，不自己写一份
#: （两边各写一份 ⇒ 改了这边忘那边，出现「后端说 repeat、界面写个案」）。
VERDICT_LABELS: dict[str, str] = {
    "isolated": "个案",
    "repeat": "重复问题",
    "systemic": "系统性风险",
    "unknown": "判不出（缺归因）",
}


async def count_repeat_issues(
    session: AsyncSession, shop_id: str, sku: str, cause: str,
) -> dict:
    """统计同一 SKU 上某个归因的**历史重复次数** —— 「这是不是重复问题」的判据。

    ★ 演示里那句「同类问题近 7 天上升 40%」能不能成立，取决于这里能不能真的数出来。
      数不出来 ⇒ 就是文案；数得出来 ⇒ 才可能变成风险提示。

    ★★ `causes` 是 JSON 列，而 SQLAlchemy 对 **JSON**（不是 JSONB）列不支持
       `.contains([...])` 数组包含：它会退化成 `LIKE` ⇒ 运行期抛
       `operator does not exist: json ~~ text`。
       ⇒ 这里显式 cast 成 JSONB 再用 Postgres 的 `@>` 包含算子。
       （本仓已是 PG-only：`test_schema_parity.py` 直接查 `pg_constraint`。）
    """
    if cause not in ATTRIBUTION_CAUSES:
        # 未知归因码 ⇒ 不猜，直接返回「数不出来」（与 service 的 fail-closed 一致）
        return {"sku": sku, "cause": cause, "cause_label": CAUSE_LABELS.get(cause, cause),
                "historical_count": 0, "is_repeat_issue": False,
                "error": f"未知归因码 {cause}，合法取值见 ATTRIBUTION_CAUSES"}

    # ★ 必须以 **String** 传入再 cast：若把参数声明成 JSONB，驱动会把这个
    #   Python str 序列化成一个 JSON **字符串**（`"[...]"`）而不是数组，
    #   包含判定就恒为 false —— 且不报错，只能靠"数出来是 0"发现。
    needle = sa_cast(literal(f'["{cause}"]', type_=String), JSONB)
    total = (await session.execute(
        select(func.count()).select_from(ReviewAttributionRecord).where(and_(
            scope_condition(ReviewAttributionRecord, shop_id),
            ReviewAttributionRecord.sku == sku,
            sa_cast(ReviewAttributionRecord.causes, JSONB).op("@>")(needle),
        ))
    )).scalar_one()
    return {"sku": sku, "cause": cause, "cause_label": CAUSE_LABELS.get(cause, cause),
            "historical_count": int(total),
            "is_repeat_issue": int(total) >= REPEAT_ISSUE_THRESHOLD}


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


async def analyze_review_systemic(
    session: AsyncSession, shop_id: str, review_id: str,
) -> dict:
    """一条差评「是个案还是系统性问题」—— **后端唯一口径**。

    判据（逐条可断言；`tests/test_trade_systemic_check.py` 四个分支各钉一条）：

      1. 查不到这条差评 / 没有归因 / 归因为 `unknown`
                                    ⇒ `verdict="unknown"`（先跑归因，不猜）
      2. 同 SKU 同因历史次数 >= `REPEAT_ISSUE_THRESHOLD`
                                    ⇒ `verdict="repeat"`
      3. 在第 2 条之上，**再叠加趋势**：健康分环比为负、或中差评占比
         >= `SYSTEMIC_NEGATIVE_RATE`
                                    ⇒ `verdict="systemic"`
      4. 其余                        ⇒ `verdict="isolated"`

    ★ 为什么不是「把两个真值都返回、让前端组合」：组合规则**就是**判据本身。
      前端只做一件事 —— 把 `verdict_label` 与 `reason` 显示出来。

    ★ `recommend_escalate` 一并由本函数给出：UI 的「采纳升级」按钮只认这个字段，
      不自己写 `verdict in (...)`（那是把同一判定搬回前端）。
    """
    ctx = await get_review_context(session, shop_id, review_id)
    if not ctx.get("found"):
        return {"ready": False, "review_id": review_id, "verdict": "unknown",
                "verdict_label": VERDICT_LABELS["unknown"],
                "recommend_escalate": False, "health": None,
                "reason": ctx.get("error") or "查不到这条评价"}

    review = ctx.get("review") or {}
    sku = review.get("sku") or ""
    cause = ((ctx.get("attribution") or {}).get("primary_cause")) or ""
    if not cause or cause == "unknown":
        return {"ready": False, "review_id": review.get("id") or review_id,
                "sku": sku, "primary_cause": cause,
                "verdict": "unknown", "verdict_label": VERDICT_LABELS["unknown"],
                "recommend_escalate": False, "health": None,
                "reason": "这条评价还没有可用的归因 —— 判不出个案还是系统性；"
                          "请先跑归因（没有归因时硬判=猜）"}

    rep = await count_repeat_issues(session, shop_id, sku, cause)
    health = await get_sku_health_score(session, shop_id, sku)
    count = rep.get("historical_count")
    is_repeat = bool(rep.get("is_repeat_issue"))

    if health.get("found"):
        delta = health.get("delta")
        negative_rate = health.get("negative_rate")
    else:
        delta = negative_rate = None
    trending_down = delta is not None and float(delta) < 0
    high_negative = (negative_rate is not None
                     and float(negative_rate) >= SYSTEMIC_NEGATIVE_RATE)

    if is_repeat and (trending_down or high_negative):
        verdict = "systemic"
    elif is_repeat:
        verdict = "repeat"
    else:
        verdict = "isolated"

    if verdict == "systemic":
        # ★ 文案必须**点名真正命中的那一支**（第 294 轮真机读数抓出来的）：
        #   环比为正、只是占比偏高时，写「趋势向下」就是字面为真、暗示为假 ——
        #   用户会照着它去查一个并不存在的下降。
        triggers = []
        if trending_down:
            triggers.append(f"健康分环比 {delta}（下降）")
        if high_negative:
            triggers.append(
                f"中差评占比 {negative_rate}（≥{SYSTEMIC_NEGATIVE_RATE}）")
        reason = (f"同因历史 {count} 次（阈值 >={REPEAT_ISSUE_THRESHOLD}），"
                  f"且{'、'.join(triggers)}"
                  f" —— 病灶不在这一单，建议升级到根因环节")
    elif verdict == "repeat":
        reason = (f"同因历史 {count} 次（阈值 >={REPEAT_ISSUE_THRESHOLD}）"
                  f" —— 建议升级，不要只回一条道歉就归档")
    else:
        reason = (f"同因历史 {count} 次（阈值 >={REPEAT_ISSUE_THRESHOLD}），"
                  f"SKU 无下行趋势 —— 按单条工单处置即可，不必升级")

    return {
        "ready": True, "review_id": review.get("id") or review_id, "sku": sku,
        "primary_cause": cause,
        "primary_cause_label": CAUSE_LABELS.get(cause, cause),
        "historical_count": count,
        "is_repeat_issue": is_repeat,
        "threshold": REPEAT_ISSUE_THRESHOLD,
        "health": health,
        "trending_down": trending_down,
        "high_negative_rate": high_negative,
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[verdict],
        "recommend_escalate": verdict in ("repeat", "systemic"),
        "reason": reason,
    }





# ============================================================ 处置：差评「后来做了什么」的唯一出口
#
# ★ 为什么这一段必须存在（第 287 轮 P0-2）
#   `review_dispositions` 此前是**三无表**：
#     · 全库 0 行 —— 全仓没有一处 `ReviewDispositionRecord(...)` 构造（**没有写入路径**）；
#     · 后端无端点 —— `modules/trade` 此前连 `router.py` 都没有；
#     · 前端零消费 —— `frontend/src` 里 grep `disposition` 零命中。
#   于是「处置」只活在 `plan_compensation` 那句「建议不发券」里：
#   有状态机（proposed→approved→issued）、有双语回复、有补偿金额的模型，
#   却没有任何一条数据能证明它被用过 —— 这是典型的「承诺型资产」。
#
# ★ 出口的形状：三步，人的判断卡在中间
#     proposed（草稿，可反复改） --人批准--> approved --人发放--> issued
#   为什么「发放」不能由 Agent 直接做：发券/退款是**不可逆的外部动作**，
#   本仓既有口径（`tools._plan_compensation_tool` 的 docstring）就是
#   「只把规则摆出来让人判断」。这里把它落成状态机：
#   **Agent 只能写到 proposed**；approved / issued 两步在 HTTP 端点上由人点。
#
# ★ 「已 approved / 已 issued 的处置不允许被草稿覆盖」是硬约束：
#   否则重跑一次归因就会把「券码已经生成了」这条事实改回「待定」，
#   账实不符且无从追责 —— 与 `db_model` 里「处置是已发生的事实」同源。
#
# ★ 为什么这些写入函数 `commit()` 而不是只 `flush()`：
#   它们是**顶层写入入口**（router / 工具 / 脚本各自开一个会话就调一次），
#   不像 `compute_sku_health` 那样被包在更大的事务里。只 flush 不 commit 时，
#   会话一关就回滚 —— 实测真库 `backfill` 报 `created=3`，换个会话查却是 0 行，
#   而调用方拿到的是「成功」。这是把「什么都没发生」伪装成成功。
#
# ★ 草稿为什么是**规则生成**而不是 LLM 现场写：
#   LLM 写出来的回复每次都不一样，测试无法断言、审计无法对账。
#   这里按「归因 + 命中规则 + 补偿金额」确定性地合成，LLM 若想润色，
#   改的是 `reply_draft_*` 字段的内容，而**不改它为什么这么写**。

#: 处置状态
#:
#: ★ `issued` **不再是终态**（第 304 轮改口径）：它只表示「本地已核准 —— 券码
#:   已生成、给买家的回复可以对外」，**平台侧还没动**。真正的终态是 `executed`
#:   （平台上执行完并登记了回执）。
#: ★ 为什么必须把这两个语义拆开：`issue_disposition` **零出站调用**（本模块没有
#:   任何 HTTP 客户端，平台适配层全是 `fetch_*`）。让 `issued` 一人同时承担
#:   「已核准」+「已发放」⇒ 界面上的「已发放 · 退回部分或全部货款」没有任何
#:   数据支撑 —— 那是**语义欺诈**，不是文案瑕疵。
DISPOSITION_STATUSES: tuple[str, ...] = (
    "proposed", "approved", "issued", "executed", "rejected",
)

#: 允许的转移（键 = 当前状态，值 = 可去的全部状态）
#:
#: ★ `issued: ("executed",)` 是 `issued` 的唯一出口（第 304 轮新增）：核准之后
#:   只能「登记回执」，不能退回 `proposed` / `approved`，也不能再 `reject` ——
#:   券码已经生成并写进了给买家的回复，把历史改没只会让台账与对话对不上账。
DISPOSITION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("proposed", "approved", "rejected"),
    "approved": ("issued", "rejected"),
    "issued": ("executed",),
    "executed": (),
    "rejected": ("proposed",),
}

#: 处置通道（`reply` 恒在：不回复买家本身就是一种处置缺失）
DISPOSITION_CHANNELS: tuple[str, ...] = ("reply", "coupon", "refund", "reship", "escalate")

#: 平台执行回执的方式
#:
#: ★ 今天**只有 `manual`**：人去平台后台把券 / 退款 / 补发做完，再回来登记。
#:   这不是保守 —— 本模块没有任何出站 HTTP 客户端，系统**没有能力**自动执行。
#:   现在就开放 `api` 等于允许「填个 mode 冒充系统已调用平台」，那是把回执
#:   做成另一种自我声明（本仓：声明承诺型假门禁是负资产）。
#:   ⇒ 将来真接通平台写接口，再把它加进值域，且必须**同时**有出站客户端 + 门禁。
DISPOSITION_EXECUTION_MODES: tuple[str, ...] = ("manual",)


class DispositionError(Exception):
    """处置的状态/取值不合法 —— 调用方映射成 **4xx**（不是 5xx）。"""


class DispositionNotFound(Exception):
    """处置不存在**或**不属于当前店铺 —— 两者**同一句**。

    ★ 刻意不分两种文案：可区分就等于能拿 id 逐位枚举别家店铺的差评。
    """


#: 归因 → 中英文回复「认错句」（只讲事实与责任，补偿句由 `_render_reply_drafts` 追加）
_REPLY_CAUSE_ZH: dict[str, str] = {
    "logistics_delay": "很抱歉，这笔订单比承诺时间晚到了 {delay}，是我们履约没做好。",
    "packaging_failure": "很抱歉，您收到的包裹外箱/内衬受损，是我们打包防护不到位。",
    "product_defect": "很抱歉，您收到的商品存在质量问题，这不符合我们对品质的要求。",
    "description_mismatch": "很抱歉，实物与页面描述不一致，是我们的信息不准确。",
    "service_attitude": "很抱歉，我们的沟通响应让您不满意，这是我们的服务问题。",
    "price_value": "感谢您的反馈，关于价格与价值的感受我们已记录并会同步给相关团队。",
    "unknown": "很抱歉给您带来了不好的购物体验。",
}

_REPLY_CAUSE_EN: dict[str, str] = {
    "logistics_delay": "We're sorry your order arrived {delay} later than promised - that's on us.",
    "packaging_failure": "We're sorry the package arrived damaged - our packing wasn't good enough.",
    "product_defect": "We're sorry the item is defective - that's not the quality we stand for.",
    "description_mismatch": "We're sorry the item didn't match the listing - our information was inaccurate.",
    "service_attitude": "We're sorry our responses fell short - that's a service failure on our side.",
    "price_value": "Thanks for the feedback on price and value - we've logged it for the team.",
    "unknown": "We're sorry you had a bad experience.",
}


def _render_reply_drafts(
    cause: str,
    *,
    delay_days: Optional[int] = None,
    compensation: Optional[dict] = None,
    coupon_code: str = "",
    issued: bool = False,
) -> tuple[str, str]:
    """按归因 + 补偿方案合成 (中文, 英文) 回复草稿 —— **确定性**，同样输入必得同样输出。

    ★ `delay_days` 取不到时**不许编数字**：只说「晚到了一段时间」。
      这是本仓「拿不到就报未知，不许猜」在文案上的同一条口径。

    ★ `issued` 决定**时态**，这不是文字洁癖（第 292 轮 P0）：
        · `issued=False`（草稿阶段，处置状态还是 `proposed`「待批准」）⇒
          **不许写成既成事实**。原实现一律写 `We've issued a USD 8 coupon
          for you`（现在完成时 = 已经发了），而这一步只是「拟好给客服看」。
          客服照这段发出去、随后批准被驳回，对买家的承诺就落空了
          ⇒ 草稿阶段一律用「拟 / 正在办理」的口径。
        · `issued=True`（`issue_disposition` 真的发放了）⇒ 才可以用完成时 + 券码。

    ★ `coupon_code` 只在 `issued=True` 时才是「可对外的凭据」；草稿阶段把它写进去
      等于提前把券号许出去 ⇒ 同一条分支里由 `issued` 一起把关。
    """
    comp = dict(compensation or {})
    kind = (comp.get("type") or "").lower()
    amount = float(comp.get("amount") or 0)
    currency = comp.get("currency") or "USD"
    reship = bool(comp.get("reship"))

    zh_delay = f"{delay_days} 天" if delay_days else "一段时间"
    en_delay = f"{delay_days} day(s)" if delay_days else "later than expected"

    zh = _REPLY_CAUSE_ZH.get(cause, _REPLY_CAUSE_ZH["unknown"]).replace("{delay}", zh_delay)
    # ★ 英文用**部件表**再拼：一句一句 `+=` 会拼出 "…on us.We've issued…"
    #   （中文不需要空格，英文缺空格），而这类瑕疵只在肉眼读回时才发现。
    en_parts = [_REPLY_CAUSE_EN.get(cause, _REPLY_CAUSE_EN["unknown"]).replace("{delay}", en_delay)]

    if kind == "coupon" and amount > 0:
        code = f"（券码 {coupon_code}）" if coupon_code else ""
        en_code = f" (code {coupon_code})" if coupon_code else ""
        if issued:
            zh += f"我们已为您发放 {currency} {amount:g} 的补偿券{code}。"
            en_parts.append(
                f"We've issued a {currency} {amount:g} coupon for you{en_code}.")
        else:
            # ★ 未发放 ⇒ 只能是「正在办理」，不许写成既成事实（第 292 轮 P0）
            zh += (f"我们正在为您申请 {currency} {amount:g} 的补偿券{code}，"
                   f"发放后会立即告知您。")
            en_parts.append(
                f"We're arranging a {currency} {amount:g} coupon for you{en_code}"
                " - it will be confirmed once issued.")
    elif kind == "refund" and amount > 0:
        if issued:
            zh += f"我们已为您办理 {currency} {amount:g} 的退款。"
            en_parts.append(f"We've processed a {currency} {amount:g} refund for you.")
        else:
            zh += f"我们将为您办理 {currency} {amount:g} 的退款。"
            en_parts.append(f"We'll process a {currency} {amount:g} refund for you.")
    if reship:
        zh += "如需补发，请回复本消息确认收货地址，我们立即安排。"
        en_parts.append("If you'd like a replacement, reply to confirm your address "
                        "and we'll ship it right away.")

    zh += "如您有其他希望的解决方式，也可以直接告诉我们。"
    en_parts.append("If you'd prefer another resolution, just let us know.")
    return zh, " ".join(en_parts)


def _disposition_row_id(review_id: str) -> str:
    """处置行 id —— 与 `db_model` 注释里的 `disp-<review_id>` 形态一致。"""
    return f"disp-{review_id}"


def _mint_coupon_code(review_id: str) -> str:
    """生成券码。**确定性**（同一评价同一天必得同一个码），便于对账与断言。"""
    tail = "".join(ch for ch in review_id if ch.isalnum())[-6:].upper() or "000000"
    return f"CP-{tail}-{datetime.utcnow().strftime('%y%m%d')}"


def _assert_transition(current: str, target: str) -> None:
    allowed = DISPOSITION_TRANSITIONS.get(current, ())
    if target not in allowed:
        readable = " / ".join(allowed) if allowed else "（终态，不可再变）"
        raise DispositionError(
            f"不允许的状态转移：{current} → {target}（{current} 只能到 {readable}）"
        )


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


async def _load_disposition_row(
    session: AsyncSession, shop_id: str, review_id: str,
) -> ReviewDispositionRecord:
    review = await _load_review_scoped(session, shop_id, review_id)
    if review is None:
        raise DispositionNotFound(
            f"本店铺下查不到这条评价（不存在或不属于当前店铺）：{review_id}")
    row = (await session.execute(
        select(ReviewDispositionRecord)
        .where(ReviewDispositionRecord.id == _disposition_row_id(review.id))
    )).scalar_one_or_none()
    if row is None:
        raise DispositionNotFound(f"这条评价还没有处置记录，请先生成草稿：{review_id}")
    return row


async def build_disposition_draft(
    session: AsyncSession, shop_id: str, review_id: str,
) -> dict:
    """合成一份**待批准**的处置建议（**不落库**、不发券、不退款）。

    返回 `{"ready": True, channels, compensation, reply_draft_zh/en, ...}` 或
    `{"ready": False, reason, ...}`。

    ★ 三种「给不出建议」必须分开报（与客服 FAQ 那轮同源）：
        · 评价不存在/不属于本店 ⇒ `reason`
        · 没归因或归因是 unknown   ⇒ `reason`（先跑归因）
        · 有归因但没启用规则 / 超预算 ⇒ `reason` + `rule_code` / `over_budget`
      一律**不返回空方案**：空方案会被上层当成「不用赔」。
    """
    ctx = await get_review_context(session, shop_id, review_id)
    if not ctx.get("found"):
        return {"ready": False, "review_id": review_id,
                "reason": ctx.get("error") or "查不到这条评价"}

    attribution = ctx.get("attribution") or {}
    cause = attribution.get("primary_cause") or ""
    if not cause or cause == "unknown":
        return {"ready": False, "review_id": review_id, "primary_cause": cause,
                "reason_code": "no_attribution",
                "reason": "这条评价还没有可用的归因（unknown 或缺失）—— 请先跑归因，"
                          "没有归因就匹配不了补偿规则"}

    review = ctx["review"]
    shipment = ctx.get("shipment") or {}
    rule = await match_compensation_rule(
        session, shop_id, cause,
        rating=review.get("rating"),
        delay_days=shipment.get("delay_days"),
        verified_purchase=review.get("verified_purchase"),
    )
    if rule is None:
        # ★ 两种成因必须**分开报**（第 304 轮实测修正）：把「压根没规则」与
        #   「有规则但这条不满足条件」说成同一句 ⇒ 后者会拿到一条**假建议**
        #   （去配一条已经存在的规则），而真正该做的是看事实或改条件。
        label = CAUSE_LABELS.get(cause, cause)
        candidates = await list_enabled_rules_for_cause(session, shop_id, cause)
        if candidates:
            codes = " / ".join(r.code for r in candidates)
            return {"ready": False, "review_id": review_id, "primary_cause": cause,
                    "primary_cause_label": label,
                    "reason_code": "rule_conditions_unmet",
                    "rule_codes": [r.code for r in candidates],
                    "reason": f"「{label}」已有 {len(candidates)} 条启用规则（{codes}），"
                              f"但这条差评不满足它的条件 —— 不是「没配规则」，"
                              f"再配一条也命中不了"}
        return {"ready": False, "review_id": review_id, "primary_cause": cause,
                "primary_cause_label": label, "reason_code": "no_rule",
                "reason": f"「{label}」这一类还没有任何补偿规则 ⇒ 给不出补偿方案"}

    try:
        plan = apply_compensation_rule(rule)
    except CompensationOverBudget as e:
        # ★ 超限显式报出来，不悄悄按上限赔（本模块第三条硬口径）
        return {"ready": False, "review_id": review_id, "primary_cause": cause,
                "reason_code": "over_budget",
                "rule_code": rule.code, "over_budget": True, "reason": str(e)}

    zh, en = _render_reply_drafts(
        cause, delay_days=shipment.get("delay_days"),
        compensation=plan["compensation"],
    )
    return {
        # ★ `review` 是 `get_review_context` 出来的 **dict**（不是 ORM 行）——
        #   写 `review.id` 会在「有归因也有规则」这条唯一能走到这里的路径上
        #   `AttributeError`，而其余三条早退分支都碰不到 ⇒ 属于测不到的角落。
        "ready": True, "review_id": review["id"],
        "primary_cause": cause, "primary_cause_label": CAUSE_LABELS.get(cause, cause),
        "channels": plan["channels"], "compensation": plan["compensation"],
        "rule_code": plan["rule_code"], "rule_name": plan["rule_name"],
        "reply_draft_zh": zh, "reply_draft_en": en,
        "is_mock_data": is_mock_source(ctx.get("data_source")),
    }


async def propose_disposition(
    session: AsyncSession,
    shop_id: str,
    review_id: str,
    *,
    channels: Optional[list] = None,
    compensation: Optional[dict] = None,
    coupon_code: str = "",
    reply_draft_en: str = "",
    reply_draft_zh: str = "",
    ticket_id: Optional[str] = None,
    notes: str = "",
) -> dict:
    """写入 / 更新一条 `proposed` 处置（**唯一写入路径**：工具 / 端点 / 脚本都走这里）。

    ★ 调用方没给草稿字段时，用 `build_disposition_draft` 现算一份填上
      （`draft_filled=True`）—— 「先有写入路径」与「表里真的有行」是两件事，
      不自动填的话补完出口表还是 0 行。

    ★ `approved` / `issued` / `executed` 的行**拒绝被覆盖**（抛 `DispositionError`）：
      券码已经生成就是既成事实，重跑归因不该改写它。
    """
    review = await _load_review_scoped(session, shop_id, review_id)
    if review is None:
        raise DispositionNotFound(
            f"本店铺下查不到这条评价（不存在或不属于当前店铺）：{review_id}")

    row_id = _disposition_row_id(review.id)
    row = (await session.execute(
        select(ReviewDispositionRecord).where(ReviewDispositionRecord.id == row_id)
    )).scalar_one_or_none()

    if row is not None and row.status in ("approved", "issued", "executed"):
        raise DispositionError(
            f"这条评价的处置已经是 {row.status} —— 已批准/已核准/已执行的记录不允许被草稿覆盖"
            f"（券码已经生成就是既成事实，重跑归因改不了它）"
        )

    draft_filled = False
    if channels is None or compensation is None or not (reply_draft_en or reply_draft_zh):
        d = await build_disposition_draft(session, shop_id, review.id)
        if not d.get("ready"):
            raise DispositionError(f"无法生成处置草稿：{d.get('reason')}")
        if channels is None:
            channels = d["channels"]
        if compensation is None:
            compensation = d["compensation"]
        if not reply_draft_zh:
            reply_draft_zh = d["reply_draft_zh"]
        if not reply_draft_en:
            reply_draft_en = d["reply_draft_en"]
        draft_filled = True

    created = row is None
    if created:
        row = ReviewDispositionRecord(id=row_id)
        session.add(row)

    row.shop_id = shop_id
    row.review_id = review.id
    if ticket_id is not None:
        row.ticket_id = ticket_id
    row.channels = [c for c in (channels or []) if c in DISPOSITION_CHANNELS] or ["reply"]
    row.compensation = compensation or {}
    row.coupon_code = coupon_code or row.coupon_code
    row.reply_draft_zh = reply_draft_zh
    row.reply_draft_en = reply_draft_en
    row.status = "proposed"
    if notes:
        row.notes = notes
    row.updated_at = datetime.utcnow().isoformat()
    await session.flush()
    await session.commit()

    out = _disposition_to_dict(row)
    out["created"] = created
    out["draft_filled"] = draft_filled
    return out


async def approve_disposition(
    session: AsyncSession, shop_id: str, review_id: str, *,
    approver: str = "", notes: str = "",
) -> dict:
    """人批准草稿（proposed → approved）。

    ★ `approver` 必填：处置是可追责动作，「谁批的」不能为空，
      否则事后问「这张券为什么发出去」无从查起。
    """
    row = await _load_disposition_row(session, shop_id, review_id)
    _assert_transition(row.status, "approved")
    if not (approver or "").strip():
        raise DispositionError("批准人不能为空 —— 处置是可追责动作，必须知道是谁批的")
    row.status = "approved"
    row.approved_by = approver.strip()
    if notes:
        row.notes = ((row.notes or "") + "\n" + notes).strip()
    row.updated_at = datetime.utcnow().isoformat()
    await session.flush()
    await session.commit()
    return _disposition_to_dict(row)


async def reject_disposition(
    session: AsyncSession, shop_id: str, review_id: str, *,
    approver: str = "", notes: str = "",
) -> dict:
    """驳回（proposed / approved → rejected）。

    ★ `approved` 也能驳回：批准之后发现补偿金额写错了，就必须有退路；
      但 `issued` / `executed` 不能 —— 券码已经生成并写进了回复，
      只能另开一笔，不能把历史改没。
    """
    row = await _load_disposition_row(session, shop_id, review_id)
    _assert_transition(row.status, "rejected")
    row.status = "rejected"
    if approver:
        row.approved_by = approver
    row.notes = ((row.notes or "") + "\n" + (notes or "已驳回")).strip()
    row.updated_at = datetime.utcnow().isoformat()
    await session.flush()
    await session.commit()
    return _disposition_to_dict(row)


async def _issue_draft_inputs(
    session: AsyncSession, shop_id: str, row: ReviewDispositionRecord,
) -> tuple[str, Optional[int]]:
    """重渲染草稿所需的 `(归因, 迟到天数)` —— 与 `build_disposition_draft` **同一取数口径**。

    ★ 为什么必须回查、而不是从别处凑：`_render_reply_drafts` 是**确定性**模板，
      要判「草稿有没有被人改过」就得拿**完全相同的输入**再算一遍。输入少一项
      （比如把 `delay_days` 写成 `None`）⇒ 现算结果必然不同 ⇒ 每一份草稿都被
      误判成「人工改过」⇒ 券码又进不了回复（假绿，且看不出是这里错的）。
    """
    ctx = await get_review_context(session, shop_id, row.review_id)
    if not ctx.get("found"):
        return "", None
    cause = (ctx.get("attribution") or {}).get("primary_cause") or ""
    delay_days = (ctx.get("shipment") or {}).get("delay_days")
    return cause, delay_days


async def _rerender_reply_drafts_on_issue(
    session: AsyncSession, shop_id: str, row: ReviewDispositionRecord,
) -> bool:
    """发放时把券码 + 完成时态写进回复草稿。返回**是否真的改写了**。

    ★ 只在「草稿还是机器生成的那一版」时改写：
        · 与**草稿阶段**的现算结果逐字相同（或本来就是空的）⇒ 没人动过 ⇒ 安全重写；
        · 不一致 ⇒ 人工改过措辞 ⇒ **保留人的话**，一行都不覆盖。
      判据不新增 DB 列 —— 「草稿被编辑过」这件事不落库，只有确定性模板能当参照物。

    ★ 为什么人工改过就宁可让券码缺席：券码是**不可逆**的既成事实，而措辞是
      客服按买家语境写的。两者冲突时不能悄悄二选一 —— 调用方会把「没重写」
      记进 `notes` 让人看见（本仓：失败路径必须能归因）。
    """
    cause, delay_days = await _issue_draft_inputs(session, shop_id, row)
    if not cause:
        return False
    comp = dict(row.compensation or {})
    cur_zh = row.reply_draft_zh or ""
    cur_en = row.reply_draft_en or ""
    base_zh, base_en = _render_reply_drafts(
        cause, delay_days=delay_days, compensation=comp,
        coupon_code="", issued=False,
    )
    if (cur_zh or cur_en) and (cur_zh != base_zh or cur_en != base_en):
        return False
    new_zh, new_en = _render_reply_drafts(
        cause, delay_days=delay_days, compensation=comp,
        coupon_code=row.coupon_code or "", issued=True,
    )
    row.reply_draft_zh = new_zh
    row.reply_draft_en = new_en
    return True


async def issue_disposition(
    session: AsyncSession, shop_id: str, review_id: str, *, actor: str = "",
) -> dict:
    """发放（approved → issued）—— **不可逆**，只有这一步会生成券码。

    ★ 前置必须是 approved：未经人批准就发券，等于把 HITL 架空。
    ★ `actor` 必填，同 `approve_disposition` 的理由。
    ★ 券码生成之后**必须回头重写回复草稿**（第 292 轮 P0）：原实现只改了
      `row.coupon_code` 就收工，草稿还是草稿阶段那一版 ⇒ **券发了，而给买家的
      那段话里永远没有券码**（`_render_reply_drafts` 的 `coupon_code` 成了一个
      死参数：唯一调用点不传它）。现在由 `_rerender_reply_drafts_on_issue` 补上，
      人工改过的草稿不覆盖。
    """
    row = await _load_disposition_row(session, shop_id, review_id)
    _assert_transition(row.status, "issued")
    if not (actor or "").strip():
        raise DispositionError("发放人不能为空 —— 发券/退款是不可逆动作，必须知道是谁发的")
    if not row.coupon_code and "coupon" in (row.channels or []):
        row.coupon_code = _mint_coupon_code(row.review_id)
    rewritten = await _rerender_reply_drafts_on_issue(session, shop_id, row)
    if not rewritten and (row.compensation or {}):
        # ★ 没重写就得**说出来**：否则「券码没进回复」在界面上无迹可寻，
        #   客服会以为草稿已经带码了。
        row.notes = (
            (row.notes or "").strip()
            + "\n发放时未自动重写回复草稿（草稿已被人工修改）：券码 "
            + (row.coupon_code or "—")
            + " 需人工补进给买家的回复。"
        ).strip()
    row.status = "issued"
    row.issued_at = datetime.utcnow().isoformat()
    row.updated_at = row.issued_at
    await session.flush()
    await session.commit()
    return _disposition_to_dict(row)


async def record_execution_receipt(
    session: AsyncSession, shop_id: str, review_id: str, *,
    execution_mode: str = "manual", platform_ref: str = "",
    executed_by: str = "", receipt_note: str = "",
) -> dict:
    """登记「平台上真的执行完了」的回执（`issued` → `executed`）—— **终态**。

    ★ 为什么必须有这一步（第 304 轮 P0·A 档）：取证确认 `issue_disposition`
      只是**本地核准**（生成券码 + 把券码写进回复草稿），**零出站调用** ——
      `modules/trade/*.py` 里 `httpx` / `requests` / `aiohttp` / `urllib` 命中 0 次，
      SP-API 与 Shopee 适配层清一色只读的 `fetch_*`。于是库里此前**没有任何字段**
      能回答「平台上做没做」⇒ 界面写「已发放 · 退回部分或全部货款」是
      **字面为真、暗示为假**。这一步把「谁、什么时候、凭什么凭证、在平台上做完了」
      落成**可审计的一行**，而不是继续让 `issued` 一个人承担两种语义。

    ★ `executed_by` 必填（与 `approver` / `actor` 同一条口径，服务端注入）：
      把「平台上已经赔了 8 块钱」这句话记进台账，必须知道是谁记的。

    ★ `execution_mode` 只接受 `manual`：今天不存在「系统自动执行」这回事，
      收窄值域是为了**不让回执变成另一种自我声明**。

    ★ `platform_ref` 为什么**允许空**：人工在平台后台做退款，未必拿得到单一
      凭证号（有的平台只给 case id，有的什么都不给）。空 = 「做了但没凭证」，
      与「没做」的界线是**这一行存不存在**，不是这个字段填没填。
    """
    row = await _load_disposition_row(session, shop_id, review_id)
    _assert_transition(row.status, "executed")
    mode = (execution_mode or "").strip()
    if mode not in DISPOSITION_EXECUTION_MODES:
        raise DispositionError(
            f"未知执行方式 {execution_mode!r}，合法取值："
            f"{' / '.join(DISPOSITION_EXECUTION_MODES)}"
            "（当前只支持 manual：本系统不调用平台接口，由人工执行后回来登记）"
        )
    if not (executed_by or "").strip():
        raise DispositionError(
            "登记人不能为空 —— 「平台上已经执行」是可追责断言，必须知道是谁登记的")

    now = datetime.utcnow().isoformat()
    row.status = "executed"
    row.execution_mode = mode
    row.platform_ref = (platform_ref or "").strip()
    row.executed_by = executed_by.strip()
    row.executed_at = now
    if (receipt_note or "").strip():
        row.receipt_note = receipt_note.strip()
    row.updated_at = now
    await session.flush()
    await session.commit()
    return _disposition_to_dict(row)


async def get_disposition(
    session: AsyncSession, shop_id: str, review_id: str,
) -> Optional[dict]:
    """取一条处置（含所属评价摘要）。没有 ⇒ None（**不是**抛错，读口没有就是没有）。"""
    review = await _load_review_scoped(session, shop_id, review_id)
    if review is None:
        return None
    row = (await session.execute(
        select(ReviewDispositionRecord)
        .where(ReviewDispositionRecord.id == _disposition_row_id(review.id))
    )).scalar_one_or_none()
    if row is None:
        return None
    return _disposition_to_dict(row, review=review)


async def list_dispositions(
    session: AsyncSession, shop_id: str, *, status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """列出本店铺的处置（新 → 旧），带所属评价摘要（列表页要显示「哪条差评」）。

    ★ `status` 非法 ⇒ **抛错**而不是静默忽略：与「按创建时间排」和
      「你参数写错了」必须可区分同一条口径（本仓 `LibraryQueryError` 同族）。
    """
    if status and status not in DISPOSITION_STATUSES:
        raise DispositionError(
            f"未知处置状态 {status}，合法取值：{' / '.join(DISPOSITION_STATUSES)}")

    q = (
        select(ReviewDispositionRecord, CustomerReviewRecord)
        .join(CustomerReviewRecord,
              CustomerReviewRecord.id == ReviewDispositionRecord.review_id)
        .where(scope_condition(ReviewDispositionRecord, shop_id))
        .order_by(ReviewDispositionRecord.updated_at.desc())
        .limit(int(limit))
    )
    if status:
        q = q.where(ReviewDispositionRecord.status == status)
    rows = (await session.execute(q)).all()
    return [_disposition_to_dict(d, review=r) for d, r in rows]


async def count_dispositions(
    session: AsyncSession, shop_id: str, *, status: Optional[str] = None,
) -> int:
    """真实条数（**不受 limit 截断**，与列表同口径）—— 列表页要显示「共 N 条」。"""
    q = select(func.count()).select_from(ReviewDispositionRecord).where(
        scope_condition(ReviewDispositionRecord, shop_id))
    if status:
        q = q.where(ReviewDispositionRecord.status == status)
    return int((await session.execute(q)).scalar_one())


async def backfill_dispositions(
    session: AsyncSession, shop_id: str, *, limit: int = 50,
) -> dict:
    """给「有归因但还没有处置」的中差评批量生成 `proposed` 草稿。

    ★ 为什么必须有这一条：补好写入路径之后，表里**仍然可能是 0 行**
      （历史差评从未被处置过）。没有它，「补出口」就只是补了一根空管道 ——
      端点能调、前端能画，但一格数据都没有。

    ★ 幂等：已有处置（**任何状态**）一律跳过，不覆盖。
    """
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .join(ReviewAttributionRecord,
              ReviewAttributionRecord.review_id == CustomerReviewRecord.id)
        .where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            CustomerReviewRecord.rating <= 3,
            ReviewAttributionRecord.primary_cause != "unknown",
        ))
        .order_by(CustomerReviewRecord.review_at.desc())
        .limit(int(limit))
    )).scalars().all()

    created, skipped, failed = 0, 0, []
    for r in rows:
        existing = (await session.execute(
            select(ReviewDispositionRecord)
            .where(ReviewDispositionRecord.id == _disposition_row_id(r.id))
        )).scalar_one_or_none()
        if existing is not None:
            skipped += 1
            continue
        try:
            await propose_disposition(session, shop_id, r.id)
            created += 1
        except DispositionError as e:
            failed.append({"review_id": r.id, "reason": str(e)})
    # ★ `propose_disposition` 每次都 commit；这里再 commit 一次是为了覆盖
    #   「一条都没建」（created=0）时也要干净收尾的情形。
    await session.commit()
    return {"scanned": len(rows), "created": created, "skipped": skipped,
            "failed": failed}


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

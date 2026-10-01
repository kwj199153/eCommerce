"""补偿规则：CRUD、按因由匹配、超预算显式拒绝（第 3 条硬口径）。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.tenant.scoping import scope_condition
from datetime import datetime
from modules.trade.db_model import CAUSE_LABELS, CompensationRuleRecord
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ._base import (CompensationOverBudget, MissingShopContext, RuleConflict, RuleError, RuleNotFound)
from .attribution import (ATTRIBUTABLE_CAUSES)



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

"""处置单据：草拟 → 生成 → 审批/驳回 → 签发 → 执行回执（状态机唯一实现）。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.tenant.scoping import scope_condition
from datetime import datetime
from modules.trade.db_model import CAUSE_LABELS, CustomerReviewRecord, ReviewAttributionRecord, ReviewDispositionRecord
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ._base import (CompensationOverBudget, DispositionError, DispositionNotFound, _disposition_to_dict, _load_review_scoped, is_mock_source)
from .queries import (get_review_context)
from .rules import (apply_compensation_rule, list_enabled_rules_for_cause, match_compensation_rule)






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

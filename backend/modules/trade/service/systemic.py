"""系统性归因：重复问题计数 + 结论判定。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from core.tenant.scoping import scope_condition
from modules.trade.db_model import ATTRIBUTION_CAUSES, CAUSE_LABELS, ReviewAttributionRecord
from sqlalchemy import String, and_, func, literal, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from .queries import (get_review_context)
from .sku_health import (get_sku_health_score)



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

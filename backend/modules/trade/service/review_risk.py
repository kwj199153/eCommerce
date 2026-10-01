"""风险话术识别的**只读**视图（消费 `modules.trade.risk_scan` 的判定）。

本文件由 `modules/trade/service.py` 拆分而来（第 355 轮），代码**逐行搬运**、未改写逻辑。
"""
# @generated-by: split_trade_service.py (第 355 轮)

from __future__ import annotations

from modules.trade import risk_scan
from sqlalchemy.ext.asyncio import AsyncSession

from ._base import (_log)
from .queries import (count_recent_negative_reviews, list_recent_negative_reviews)



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

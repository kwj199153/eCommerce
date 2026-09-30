# -*- coding: utf-8 -*-
"""r299 · P0 效果评测：三通道对照（**只读**）

跑法（必须在 backend/ 下）：
    python scripts/probe_r299_risk_eval.py

三个集：
  开发集 scripts/data/r299_risk_eval_set.json        —— 规则在此收敛（**有调参泄漏**）
  holdout scripts/data/r299_risk_eval_holdout.json   —— 规则冻结后新写（测「换措辞」鲁棒性）
  库内真数据 customer_reviews                        —— 真数据上会输出什么

★ 为什么要分「开发集 / holdout」：本仓既有判据 —— **没被反向注入验证过的门禁 =
  没有门禁**。同理，**在同一批样本上边看误报边调规则，得到的满分不说明任何问题**。
  首轮实测正是如此：规则通道在开发集上冲到 100%/100%，换一批措辞后掉到 8%/100%。

★ 只读：不写库、不改表。
产出：backend/out-probe-r299-risk-eval.txt（UTF-8，LF）
"""

import os
import sys
import json
import asyncio
import collections

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text  # noqa: E402
from core.database import async_session_factory, register_all_models  # noqa: E402
from modules.trade.risk_scan import (  # noqa: E402
    CATEGORY_LABELS, DECISION_UNKNOWN, RISK_CATEGORIES,
    fuse, scan_llm, scan_naive, scan_rules,
)

DEV_SET = os.path.join(BACKEND, "scripts", "data", "r299_risk_eval_set.json")
HOLDOUT = os.path.join(BACKEND, "scripts", "data", "r299_risk_eval_holdout.json")
OUT = os.path.join(BACKEND, "out-probe-r299-risk-eval.txt")

CHANNELS = [
    ("naive", "朴素关键词"),
    ("rule", "结构化规则"),
    ("llm", "LLM 语义"),
    ("fused", "融合"),
]

_lines: list[str] = []


def p(s: str = "") -> None:
    _lines.append(str(s))
    print(s)


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * prec * rec / (prec + rec)) if (prec == prec and rec == rec and (prec + rec)) else float("nan")
    return prec, rec, f1


def fmt(v: float) -> str:
    return "   n/a" if v != v else f"{v:6.1%}"


# ============================================================ 单集评测

async def evaluate(path: str, tag: str, sem: asyncio.Semaphore):
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    items = spec["items"]

    async def judge(it: dict) -> dict:
        blob = it["text"]
        naive = scan_naive(blob)
        rule = scan_rules(blob)
        async with sem:
            llm_res = await scan_llm(blob)
        fused = fuse([naive, rule, llm_res])
        return {"item": it, "naive": naive, "rule": rule, "llm": llm_res, "fused": fused}

    records = sorted(await asyncio.gather(*[judge(it) for it in items]),
                     key=lambda r: r["item"]["id"])

    summary: dict[str, dict] = {}
    for key, _label in CHANNELS:
        tp = fp = fn = tn = unk = 0
        per_cat = {c: {"tp": 0, "fp": 0, "fn": 0} for c in RISK_CATEGORIES}
        for r in records:
            gold = r["item"]["label"]
            gold_risk = gold in RISK_CATEGORIES
            res = r[key]
            pred = res.is_risk
            # ★「未定论」= 该条**没有定论**（LLM 拿不准 / 调用失败 / 解析失败）。
            #   LLM 明确判「无风险」是 clean，不是 unknown —— 两者方向相反。
            if res.decision == DECISION_UNKNOWN:
                unk += 1
            tp += int(gold_risk and pred)
            fp += int(not gold_risk and pred)
            fn += int(gold_risk and not pred)
            tn += int(not gold_risk and not pred)
            for c in RISK_CATEGORIES:
                g, pr_ = (gold == c), (c in res.categories)
                if g and pr_:
                    per_cat[c]["tp"] += 1
                elif not g and pr_:
                    per_cat[c]["fp"] += 1
                elif g and not pr_:
                    per_cat[c]["fn"] += 1
        prec, rec, f1 = prf(tp, fp, fn)
        summary[key] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "prec": prec,
                        "rec": rec, "f1": f1, "unk": unk, "per_cat": per_cat}

    return {"tag": tag, "path": path, "spec": spec, "items": items,
            "records": records, "summary": summary}


def print_summary(ev, show_detail: bool) -> None:
    items, records, summary = ev["items"], ev["records"], ev["summary"]
    p("=" * 84)
    p(f"[{ev['tag']}]  {os.path.basename(ev['path'])}")
    p("=" * 84)
    gold_pos = [it for it in items if it["label"] in RISK_CATEGORIES]
    p(f"样本数 = {len(items)}   正类(四类) = {len(gold_pos)}   负类(含 r5/none) = {len(items) - len(gold_pos)}")
    p("")
    p(f"    {'通道':<12} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}   {'精确率':>7} {'召回率':>7} {'F1':>7}  {'未定论':>6}")
    for key, label in CHANNELS:
        s = summary[key]
        p(f"    {label:<12} {s['tp']:>4} {s['fp']:>4} {s['fn']:>4} {s['tn']:>4}   "
          f"{fmt(s['prec'])} {fmt(s['rec'])} {fmt(s['f1'])}  {s['unk']:>6}")
    p("")

    p("    分类别（融合通道）")
    p(f"       {'类别':<14} {'TP':>3} {'FP':>3} {'FN':>3}   {'精确率':>7} {'召回率':>7}")
    for c in RISK_CATEGORIES:
        d = summary["fused"]["per_cat"][c]
        pr, rc, _ = prf(d["tp"], d["fp"], d["fn"])
        p(f"       {CATEGORY_LABELS[c]:<14} {d['tp']:>3} {d['fp']:>3} {d['fn']:>3}   {fmt(pr)} {fmt(rc)}")
    p("")

    # 误报 / 漏报（逐通道）
    for key, label in CHANNELS:
        fps = [(r["item"], r[key]) for r in records
               if r["item"]["label"] not in RISK_CATEGORIES and r[key].is_risk]
        fns = [(r["item"], r[key]) for r in records
               if r["item"]["label"] in RISK_CATEGORIES and not r[key].is_risk]
        p(f"    -- {label}：误报 {len(fps)} 条 / 漏报 {len(fns)} 条 --")
        if show_detail:
            for it, res in fps:
                evd = [e for h in res.hits for e in h.evidence][:1]
                p(f"       ✗误报 {it['id']} 判成 {res.risk_categories} level={res.top_level}")
                p(f"          原文：{it['text']}")
                p(f"          证据：{evd}")
            for it, res in fns:
                p(f"       ✗漏报 {it['id']} gold={it['label']}  原文：{it['text']}")
        else:
            if fps:
                p(f"      误报 id：{[it['id'] for it, _ in fps]}")
            if fns:
                p(f"      漏报 id：{[it['id'] for it, _ in fns]}")
        p("")

    if show_detail:
        p("    逐条明细")
        for r in records:
            it = r["item"]
            p(f"      {it['id']:<5} gold={it['label']:<5} {it['text'][:70]}")
            for key, label in CHANNELS:
                res = r[key]
                flag = ""
                if key == "fused" and (it["label"] in RISK_CATEGORIES) != res.is_risk:
                    flag = "  <<< 不一致"
                p(f"            {label:<10} → [{','.join(res.categories) or '-'}] {res.top_level} / {res.decision}{flag}")
        p("")


# ============================================================ 主流程

async def main() -> None:
    register_all_models()
    sem = asyncio.Semaphore(4)

    p("=" * 84)
    p("r299 · P0 效果评测：买家评论风险话术识别（三通道对照）")
    p("=" * 84)
    p("★ 指标口径：二分类「属于四类风险话术？(r1~r4)」。r5（高情绪无威胁）与 none 都算**负类**。")
    p("★ 做法：**先把样本写出来，再写规则**；开发集用于收敛规则，holdout 用于暴露过拟合。")
    p("")

    p("跑开发集…")
    dev = await evaluate(DEV_SET, "开发集（规则在此收敛 ⇒ 有调参泄漏）", sem)
    p("跑 holdout…")
    hold = await evaluate(HOLDOUT, "holdout（规则冻结后新写 ⇒ 测换措辞）", sem)
    p("")

    print_summary(dev, show_detail=False)
    print_summary(hold, show_detail=True)

    # 对比表
    p("=" * 84)
    p("[对比] 同一套代码，两个集")
    p("=" * 84)
    p(f"    {'通道':<12} {'开发集 P':>9} {'开发集 R':>9} {'holdout P':>10} {'holdout R':>10}   {'R 落差':>8}")
    for key, label in CHANNELS:
        a, b = dev["summary"][key], hold["summary"][key]
        drop = (b["rec"] - a["rec"]) if (a["rec"] == a["rec"] and b["rec"] == b["rec"]) else float("nan")
        p(f"    {label:<12} {fmt(a['prec'])} {fmt(a['rec'])} {fmt(b['prec']):>10} {fmt(b['rec']):>10}   "
          f"{'   n/a' if drop != drop else f'{drop:+8.1%}'}")
    p("")
    p("★ 读法：规则通道的召回在 holdout 上暴跌 ⇒ 它的开发集满分来自**调参**，不是能力。")
    p("")

    # 库内真数据
    p("=" * 84)
    p("[库内真数据] customer_reviews 实跑（只读）")
    p("=" * 84)
    async with async_session_factory() as s:
        rows = (await s.execute(text(
            "SELECT id, rating, status, title, body FROM customer_reviews ORDER BY id"
        ))).all()
    p(f"库内共 {len(rows)} 条（全部 source=mock_seed，单店单 SKU）。")
    p("")

    async def judge_row(rw):
        rid, rating, status, title, body = rw
        blob = f"{title or ''}\n{body or ''}"
        naive = scan_naive(blob)
        rule = scan_rules(blob)
        async with sem:
            llm_res = await scan_llm(blob)
        return (rid, rating, status, title, naive, rule, llm_res, fuse([naive, rule, llm_res]))

    for rid, rating, status, title, naive, rule, llm_res, fused in \
            await asyncio.gather(*[judge_row(rw) for rw in rows]):
        p(f"--- {rid}  rating={rating} status={status}  「{title}」")
        for key, res in (("朴素", naive), ("规则", rule), ("LLM", llm_res), ("融合", fused)):
            p(f"    {key:<4} → [{','.join(res.categories) or '-'}] level={res.top_level}")
            for h in res.hits:
                if h.evidence:
                    p(f"           {CATEGORY_LABELS.get(h.category, h.category)} 证据: {h.evidence[0][:88]}")
        p("")
    p("★ 结论：真数据 4 条全为「物流/包装」主题，**四类风险零样本** ⇒ P0 在真数据上")
    p("  得到的是「零命中」，它证明的是**数据里没有**，而不是「算法没用」。")
    p("")

    _flush()


def _flush() -> None:
    with open(OUT, "wb") as f:
        f.write(("\n".join(_lines) + "\n").encode("utf-8"))
    print(f"\n[written] {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

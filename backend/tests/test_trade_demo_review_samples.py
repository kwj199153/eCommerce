# -*- coding: utf-8 -*-
"""第 299 轮 P1：演示差评样本（`demo_script.DEMO_REVIEW_SAMPLES`）的判据。

====================================================================
★ 这批数据为什么需要门禁
====================================================================
演示样本是「差评风险识别」视图**唯一**的真实正样本来源。样本一旦漂移
（offset 落到 30 天窗口外、措辞改到规则命令不中、金标与正文不符），
演示会**静默变空**：界面不报错，只是没有红色可看；而评测仍会给出一个
漂亮的（但基于 0 条正样本的）分数。**能被静默弄坏的东西必须上判据。**

★ 六条不变量（每条对应一个用例，互不重叠）
--------------------------------------------------------------------
  1. 条数账：`rating<=3` 且落在 `days=30` 窗口内的评论 = 20 条（正 12 / 负 8）。
     窗口口径与 `service._recent_negative_condition` **同源**（字符串比较）。
  2. `offset` 在样本批次内唯一。
  3. 全部 `offset` 落在窗口内 —— 窗外 = 演示时压根不出现。
  4. `gold` 取值封闭（`r1`~`r5` | `none`），且 `demo_review_gold()` 覆盖全部 payload。
  5. 正类样本**只靠规则通道**就能命中其 gold 类别
     —— 这是「未配置 LLM 凭据的降级态下演示不塌」的可断言化。
  6. 负类样本规则通道**不得**报出任何四类风险；标 `r5` 的必须真命中 `r5`。
  7. 措辞与评测集（开发集 + holdout）无逐字重复 —— 防「用训练集考自己」。

★ 为什么不连库：本仓 `tests/` 连的是**共享生产库**，连库用例「全量红 /
  单跑绿」不可复现。本文件判的是**剧本源码规格**（数据从哪来），
  与「库里现在有几行」无关 —— 后者是 seed 幂等的判据，在别处。
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from modules.trade import demo_script, risk_scan
from modules.trade.service import _review_risk_text

BACKEND = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND / "scripts" / "data"

RISK_CATS = tuple(risk_scan.RISK_CATEGORIES)
ALL_LABELS = set(risk_scan.CATEGORY_LABELS) | {"none"}
WINDOW_DAYS = 30

#: ★ 固定基准时间：判据必须可复现，不许跟「今天」漂。
NOW = datetime(2026, 1, 15, 12, 0, 0)


# ============================================================ 取数工具

def _payloads() -> list[dict]:
    return demo_script.build_demo_review_payloads(now=NOW)


def _in_window(payloads: list[dict]) -> list[dict]:
    """复刻 `service._recent_negative_condition` 的窗口口径（**字符串比较**）。

    ★ 为什么照抄而不 import 那个条件构造器：那是 SQLAlchemy 表达式，
      要 `session` 才能求值。口径本身（`review_at >= (now - days).date()`）
      照抄在这里，并用下面的「边界用例」把两者钉在一起。
    """
    since = (NOW - timedelta(days=WINDOW_DAYS)).date().isoformat()
    return [p for p in payloads
            if int(p["rating"]) <= 3 and str(p.get("review_at") or "") >= since]


def _specs() -> list[dict]:
    out = [rv for s in demo_script.DEMO_ORDER_SPECS for rv in s.get("reviews", [])]
    out += list(demo_script.DEMO_REVIEW_SAMPLES)
    return out


def _rule_scan(spec: dict) -> risk_scan.ScanResult:
    text = _review_risk_text({"title": spec["title"], "body": spec["body"]})
    return risk_scan.scan_text(text, channel="rule")


def _eval_texts() -> set[str]:
    texts: set[str] = set()
    for name in ("r299_risk_eval_set.json", "r299_risk_eval_holdout.json"):
        data = json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))
        for it in data["items"]:
            texts.add(" ".join(str(it["text"]).split()).lower())
    return texts


# ============================================================ 1 条数账

def test_window_population_is_20_with_12_positive_and_8_negative():
    """窗口内差评恰 20 条，且正 12 / 负 8（口径：正类 ⟺ 命中 RISK_CATEGORIES）。"""
    gold = demo_script.demo_review_gold()
    win = _in_window(_payloads())
    assert len(win) == 20, (
        f"窗口内差评应为 20 条，实测 {len(win)} 条："
        f"{sorted(int(p['rating']) for p in win)}"
    )
    labels = Counter(gold[p["external_review_id"]] for p in win)
    pos = sum(n for lb, n in labels.items() if lb in RISK_CATS)
    neg = sum(n for lb, n in labels.items() if lb in ("r5", "none"))
    assert (pos, neg) == (12, 8), f"正/负样本数应为 (12, 8)，实测 ({pos}, {neg})"
    # 四类风险各自至少 3 条 —— 演示要能同时展示四种话术，缺一类就是残的
    for cat in RISK_CATS:
        assert labels[cat] >= 3, f"{cat} 正样本 {labels[cat]} 条，少于 3 条"
    assert labels["r5"] >= 1 and labels["none"] >= 1, (
        "负类必须同时覆盖 r5（高情绪）与 none（干净）—— 两者被合并成本类就"
        "读不出「算法把情绪当风险」这种误报"
    )


# ============================================================ 2/3 offset

def test_sample_offsets_are_unique():
    offs = [s["offset"] for s in demo_script.DEMO_REVIEW_SAMPLES]
    dup = [o for o, n in Counter(offs).items() if n > 1]
    assert not dup, f"样本 offset 重复：{dup}（同一批样本不该撞同一天）"


def test_novel_sample_offsets_inside_window():
    """新增样本必须落在 30 天窗口内 —— 窗外 = 演示时它压根不出现。

    ★ 与用例 1 冗余但**不重复**：用例 1 只说「总数不对了」，本用例说得出
      **是哪一条、偏了多少天**。诊断粒度不同，两条都要留
      （脚本化调试时，前者只能告诉你「少了 2 条」）。

    ★ 剧本里既有的 R1DEMO0002/0003（offset 40/33）**故意留在窗外**：
      它们是「历史同因差评」，为 `count_repeat_issues` 的 ≥3 条阈值服务，
      不是演示窗口内的样本。本用例只约束**新增样本**，不约束它们。
    """
    novel = [
        (s["external_review_id"], s["offset"]) for s in demo_script.DEMO_REVIEW_SAMPLES
        if int(s["offset"]) > WINDOW_DAYS
    ]
    assert not novel, f"新增样本落到窗口外：{novel}"


# ============================================================ 4 gold

def test_gold_values_closed_set_and_covers_every_payload():
    gold = demo_script.demo_review_gold()
    ids = {p["external_review_id"] for p in _payloads()}
    assert set(gold) == ids, (
        f"金标未覆盖全部 payload：缺 {sorted(ids - set(gold))} / "
        f"多 {sorted(set(gold) - ids)}"
    )
    bad = {k: v for k, v in gold.items() if v not in ALL_LABELS}
    assert not bad, f"金标取值超出封闭集合 {sorted(ALL_LABELS)}：{bad}"


# ============================================================ 5 正类

def test_positive_samples_hit_their_gold_category_with_rules_alone():
    """正类样本必须**只靠规则通道**命中其 gold 类别。

    ★ 为什么这条是载重的：演示不能依赖「本机恰好配了 LLM key」。
      规则通道是零成本兜底，它命不中 ⇒ 降级态下这批样本全判负类，
      演示直接塌，而报告只会说「本次是降级运行」。
    """
    missed = []
    for s in demo_script.DEMO_REVIEW_SAMPLES:
        if s["gold"] not in RISK_CATS:
            continue
        got = set(_rule_scan(s).risk_categories)
        if s["gold"] not in got:
            missed.append((s["external_review_id"], s["gold"], sorted(got)))
    assert not missed, f"规则通道漏报（id, gold, 实际命中）：{missed}"


# ============================================================ 6 负类

def test_negative_samples_are_never_flagged_by_rules():
    """负类样本不得报出四类风险；标 `r5` 的必须真命中 `r5`。

    ★ 两个方向都要判：只判「不许报风险」会漏掉「标了 r5 其实毫无情绪」这种
      标注错误；只判 r5 又会漏掉把普通差评误报成风险。
    """
    false_pos = []
    fake_r5 = []
    for s in demo_script.DEMO_REVIEW_SAMPLES:
        if s["gold"] in RISK_CATS:
            continue
        res = _rule_scan(s)
        if res.risk_categories:
            false_pos.append((s["external_review_id"], sorted(res.risk_categories)))
        if s["gold"] == "r5" and risk_scan.CAT_EMOTION not in res.categories:
            fake_r5.append(s["external_review_id"])
    assert not false_pos, f"负类样本被误报为风险：{false_pos}"
    assert not fake_r5, f"标 r5 但规则通道没判出高情绪：{fake_r5}"


# ============================================================ 7 去重

def test_wording_not_copied_from_eval_sets():
    """样本措辞不得与评测集逐字重复 —— 逐字重复 = 用训练集考自己。"""
    eval_texts = _eval_texts()
    assert eval_texts, "评测集读取为空 —— 路径或结构变了，本判据会恒真（假绿）"
    dup = []
    for s in _specs():
        text = " ".join(f"{s['title']} {s['body']}".split()).lower()
        if text in eval_texts:
            dup.append(s["external_review_id"])
    assert not dup, f"与评测集逐字重复：{dup}"


# ============================================================ 哨兵

def test_gate_self_check():
    """门禁自身的前提哨兵：读集非空、且样本总数对得上。

    ★ 本仓铁律：门禁的**读集**变了必须看出来。用 `build_demo_review_payloads`
      的条数与规格条数对账 —— 若某天有人加了第二种样本来源而没接进 payload，
      这里会先红，而不是等到演示现场才发现「样本没进库」。
    """
    assert len(demo_script.DEMO_REVIEW_SAMPLES) >= 19, (
        "样本数跌破下限 —— 要么被误删，要么来源被拆到别处（读集变了）。"
        "若确为有意精简，请同步下调本下限并说明新的条数账"
    )
    specs = _specs()
    payloads = _payloads()
    assert len(payloads) == len(specs), (
        f"payload {len(payloads)} 条 ≠ 规格 {len(specs)} 条："
        "有规格没被展开成载荷，或反过来"
    )
    assert len(payloads) == len({p["external_review_id"] for p in payloads}), \
        "external_review_id 重复（幂等键撞车）"

# -*- coding: utf-8 -*-
"""第 302 轮：风险样本 / 提示词的**语域一致性**判据。

====================================================================
★ 这批判据要钉死的那次事故
====================================================================
第 299~301 轮把 r299 评测集做到了 P/R/F1 = 1.00，看上去很美。回头一查语域才发现：

  * 12 条正类是**对话体** —— 对卖家喊话：「Either you replace the unit this week
    or …」/「Refund the order in full …」；
  * 8 条负类是**评论体** —— 第三人称体验陈述：「the blue is much darker than the
    listing image」。

**正负类按形式特征（是不是在对卖家说话）完美可分** ⇒ 满分是自证：模型只要学会
「看见第二人称祈使句就判风险」就能拿 1.00，一个字的语义都没学。

⇒ 本文件的判据只回答一个问题：**还能不能只靠「形式」把正负类分开**。

====================================================================
★ 六个判据
--------------------------------------------------------------------
  1. 每条评测样本**必须**声明 `register == "review"`（防后来者把私信体混进来）
  2. 两套提示词（单条 / 批量）**语域段在位**：都有「已公开发布」与「旁白」两句锚点，
     且**不含**已判定自相矛盾的旧定义（这条差评本身就是那条差评，不可能是筹码）
  3. 两套提示词的分类学 r1~r5 **逐字同步** —— 只改一边 = 两条通道给出不同答案且没人报错
  4. 会话体标记**不可分离**：正负类里都既有「含标记」也有「不含标记」的样本
  5. 会话体标记占比差不得过大（阈值见 `_MAX_GAP`，按实测留了余量）
  6. 前提哨兵：读集非空、正负类都非空（否则占比是 0/0，判据恒真）

★ 为什么 **只** 判「会话体标记」而不是所有语言特征
--------------------------------------------------------------------
`FIRST_PERSON`（I / my）在正类里天然更高 —— 「我会去找平台」本来就要用第一人称，
那是**语义内容**不是语域。真正的语域代理是「这条文本在不在对着卖家说话」：
第二人称、祈使句开句、点名卖家。判这个词表之外的东西 ⇒ 会把正常的语义信号
当成缺陷去修（第 302 轮我犯过一次：为拉平人称把正类改成生硬的第三人称）。

★ 阈值从哪来（不手写期望值）
--------------------------------------------------------------------
落成时的实测（脚本 `.workbuddy/probes/r302_risk_scope/probe_r302_register_stats.py`）：

    代理            dev(21/27)     holdout(12/12)   demo(12/7)
    second_person    33.3/25.9      25.0/25.0       33.3/42.9
    seller_noun      14.3/ 7.4      25.0/ 8.3       16.7/ 0.0
    imperative_open   0.0/ 0.0       8.3/ 0.0        0.0/ 0.0

`_MAX_GAP = 0.35` 对最大实测差 25.0pp 留了 10pp 余量；`_MIN_BOTH_SIDES = 2`
要求「四个象限」不是靠 1 条样本撑起来的。**照抄实测值当阈值 = 恒绿**，
这里刻意留余量；改写完脚本重跑一次即可知道有没有跌破。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from modules.trade import demo_script, prompts

BACKEND = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND / "scripts" / "data"
EVAL_FILES = ("r299_risk_eval_set.json", "r299_risk_eval_holdout.json")

#: 正类 ⟺ 命中 r1~r4（与提示词口径同源）；r5 与 none 同属负类。
POS_LABELS = ("r1", "r2", "r3", "r4")
NEG_LABELS = ("r5", "none")

#: ★ 会话体代理 —— 「这条文本在不在对着卖家说话」。词表是**业务判断**，写在测试里
#:   是为了让存取数的旁路读同一份；改词表必须同步改上面的实测注释。
REGISTER_PROXIES = {
    "second_person": re.compile(r"\b(you|your|you're|yours|yourself)\b", re.I),
    "seller_noun": re.compile(r"\b(seller|vendor|store|shop|dispatch|support team)\b", re.I),
    "imperative_open": re.compile(
        r"^\s*(refund|replace|send|reply|respond|ship|contact|sort|fix|cancel)\b", re.I),
}

#: 正负类占比差上限（绝对百分点）
_MAX_GAP = 0.35
#: 「两侧都有」的检查只在代理**有信息量**时才做：语料整体命中率低于这个值的代理
#:   压根分不动类（例如几乎没人用祈使句开句），强求两侧齐全只会逼人往样本里塞哨兵词。
_MIN_SALIENCE = 0.25

#: ★★ 第 302 轮已判定自相矛盾的旧定义碎片：不允许再出现在提示词里。
#:   理由：这批文本**本身就是那条已经发出的差评**，「威胁要去发差评」不成立。
_FORBIDDEN_IN_PROMPTS = (
    "以公开差评为筹码",
    "威胁差评",
    "Either you replace",
)
#: 语域段的两句锚点 —— 缺一句就是只改了一边，或改文案时把关键约束删了。
#:   ★ 两边措辞不同怕 hack：「single」写「不是买家私信」、「batch」写「不是私信」，
#:     所以锚点取的是**两边共有**的子串，不要往回收成某一边的整句。
_REQUIRED_IN_PROMPTS = (
    "已公开发布",
    "私信",
    "第三人称陈述",
)


# ============================================================ 取数

def _eval_items(name: str) -> list[dict]:
    data = json.loads((EVAL_DIR / name).read_text(encoding="utf-8"))
    return list(data["items"])


def _eval_specs() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for name in EVAL_FILES:
        for it in _eval_items(name):
            out.append((name, it))
    return out


def _demo_items() -> list[tuple[str, dict]]:
    """演示样本套进评测的口径里 —— 让「同一个判据」同时管住两处数据。"""
    out = []
    for s in demo_script.DEMO_REVIEW_SAMPLES:
        out.append((f"demo:{s['external_review_id']}", {
            "id": s["external_review_id"],
            "label": s["gold"],
            "register": "review",  # ★ 演示样本统一按评论体记；语域由判据 4/5 守
            "text": f"{s['title']} {s['body']}",
        }))
    return out


def _groups(items):
    pos = [it for _, it in items if it["label"] in POS_LABELS]
    neg = [it for _, it in items if it["label"] in NEG_LABELS]
    other = [it for _, it in items if it["label"] not in POS_LABELS + NEG_LABELS]
    assert not other, f"标签落入封闭集合之外：{[it['id'] for it in other]}"
    return pos, neg


def _prompt_bodies() -> dict[str, str]:
    return {
        "single": prompts.RISK_SCAN_LLM_SYSTEM_PROMPT,
        "batch": prompts.RISK_SCAN_BATCH_SYSTEM_PROMPT,
    }


def _register_paragraph(body: str) -> list[str]:
    """抽出 `★ 输入是 …` 那段语域说明直到空行 —— 两套提示词的这段必须逐字相同。"""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("★ 输入是"):
            out = []
            for nx in lines[i:]:
                if not nx.strip():
                    break
                out.append(nx)
            assert len(out) >= 3, f"语域段只有 {len(out)} 行 —— 说明被删成一句话了"
            return out
    raise AssertionError("没找到 `★ 输入是` 语域段 —— 提示词结构变了，本判据失去抓手")


def _taxonomy_block(body: str) -> list[str]:
    """抽出 `- r1 …` 起到 `- r5 …` 块（含续行）—— 两套提示词的这段必须逐字相同。"""
    lines = body.splitlines()
    start = None
    end = None
    for i, ln in enumerate(lines):
        if ln.startswith("- r1 ") and start is None:
            start = i
        if ln.startswith("- r5 ") and start is not None:
            end = i
            break
    assert start is not None and end is not None, (
        "没找到 r1~r5 定义块 —— 分类学写法变了，本判据失去抓手")
    return lines[start:end + 1]


# ============================================================ 6 前提哨兵

def test_gate_read_sets_are_non_empty_and_both_classes_present():
    """哨兵：读集非空 + 正负类都非空 —— 否则所有占比都是 0/0，判据恒真（假绿）。"""
    specs = _eval_specs() + _demo_items()
    assert len(specs) >= 72 + 19, (
        f"读集条数 {len(specs)} 低于下限（72 评测 + 19 演示）："
        "数据源被搬走了或被删了，后面 5 条判据会全部假绿"
    )
    for name in EVAL_FILES:
        items = [(name, it) for it in _eval_items(name)]
        pos, neg = _groups(items)
        assert pos and neg, f"{name} 正负类有一边为空：{len(pos)}/{len(neg)}"
    pos, neg = _groups(_demo_items())
    assert pos and neg, f"DEMO 正负类有一边为空：{len(pos)}/{len(neg)}"
    assert REGISTER_PROXIES, "代理词表为空 —— 判据会恒真"


# ============================================================ 1 语域声明

def test_every_eval_item_declares_review_register():
    """每条评测样本必须显式声明 `register == "review"`。

    ★ 为什么要求「显式」而不是「默认就是」：默认 = 语域这件事没人负责。
      第 302 轮的事故正是因为没人声明过语域 —— 对话体样本混进来时没人觉得不对。
    """
    bad = []
    for name, it in _eval_specs():
        if it.get("register") != "review":
            bad.append(f"{name}:{it.get('id')} register={it.get('register')!r}")
    assert not bad, (
        f"{len(bad)} 条样本缺语域声明（或声明不是 review）：\n  " + "\n  ".join(bad)
    )


# ============================================================ 2 提示词语域段

@pytest.mark.parametrize("which", ["single", "batch"])
def test_prompts_declare_review_register_and_drop_contradictory_r1(which):
    """两套提示词语域段必须在位，且**不含**已判定自相矛盾的旧 r1 定义。"""
    body = _prompt_bodies()[which]
    for anchor in _REQUIRED_IN_PROMPTS:
        assert anchor in body, (
            f"{which} 提示词缺语域锚点 {anchor!r}："
            "只在一边写明语域 = 另一条通道把评论当私信判"
        )
    # ★ 同一个 running gag：两边都 AssertionError 时打印变乱，所以这一段不用 assert-only
    for dead in _FORBIDDEN_IN_PROMPTS:
        if dead in body:
            raise AssertionError(
                f"{which} 提示词里又出现了第 302 轮已判定自相矛盾的措辞 {dead!r}："
                "这条差评本身就是那条已公开的差评，它不可能同时是「还没发的筹码」"
            )


def test_both_prompts_carry_the_same_register_paragraph():
    """两套提示词的**语域说明段**必须逐字相同。

    ★ 与判据 2 的分工：2 只保证「两边都有」，这里保证「两边说的一样的」。
      措辞不同 = 两条通道对「输入是什么」的理解不同，且不会报错。
    """
    bodies = _prompt_bodies()
    assert _register_paragraph(bodies["single"]) == _register_paragraph(bodies["batch"]), (
        "两套提示词的语域段不一致：\n"
        + "\n".join(f"  single| {a}\n  batch | {b}"
                    for a, b in zip(_register_paragraph(bodies["single"]),
                                    _register_paragraph(bodies["batch"])) if a != b)
    )


# ============================================================ 3 两套同步

def test_single_and_batch_prompts_share_one_taxonomy():
    """单条版与批量版的 r1~r5 定义必须**逐字相同**。

    ★ 为什么这条不是洁癖：两条通道共用一套**语义**，但正文写在两处。
      历史上它们各自演化（批量版为了压缩输出删了 reason 规则）却没人发现 ——
      因为「口径漂移」不报错，只是两条通道给出不同答案。
    """
    bodies = _prompt_bodies()
    single = _taxonomy_block(bodies["single"])
    batch = _taxonomy_block(bodies["batch"])
    assert single == batch, (
        "两套提示词的 r1~r5 定义不一致：\n"
        + "\n".join(f"  single| {a}\n  batch | {b}"
                    for a, b in zip(single, batch) if a != b)
    )
    # 陷阱规则也要同源 —— 第 300 轮两条提示词同时补过反例，就是怕一边补一边没补
    trap = "已经解决"
    assert bodies["single"].count(trap) == bodies["batch"].count(trap), (
        f"「{trap}」这条反例在两套提示词里出现次数不同："
        f"{bodies['single'].count(trap)} vs {bodies['batch'].count(trap)} —— 一边记住一边忘了"
    )


# ============================================================ 4/5 不可分离

@pytest.mark.parametrize("scope", ["dev", "holdout", "demo"])
def test_register_proxy_does_not_separate_positives_from_negatives(scope):
    """会话体代理**不得**把正负类分开（判据 4：四象限都有人；判据 5：占比差有限）。

    ★ 这就是第 302 轮那次事故的直接判据：当年正类 100% 第二人称祈使、
      负类 0% ⇒ 「看一眼是不是在喊话」就能拿满分，评测失去意义。

    ★ 为什么合并成一条用例：分开写会重复造两遍 `_groups` 取数；但**失败信息**
      区分得开（「那一侧是空的」 vs 「差了 X 个百分点」），诊断粒度保住了。
    """
    owner = {
        "dev": "r299_risk_eval_set.json",
        "holdout": "r299_risk_eval_holdout.json",
    }.get(scope)
    items = [(o, it) for o, it in _eval_specs() if o == owner] if owner else _demo_items()
    pos, neg = _groups(items)
    corpus = [it for _, it in items]

    hollow, gaps = [], []
    for name, rx in REGISTER_PROXIES.items():
        def hits(group):  # 闭包用 rx 会有 late binding 问题 ⇒ 直接内联取值
            return [it for it in group if rx.search(it["text"])]

        salience = len(hits(corpus)) / len(corpus)
        ph, nh = hits(pos), hits(neg)
        # 判据 4：代理有信息量（语料整体命中率够高）时，两边都得见过它、也都得见过它没有
        #         —— 一侧抽干 = 这条特征自带标签
        if salience >= _MIN_SALIENCE and (not ph or len(ph) == len(pos)
                                          or not nh or len(nh) == len(neg)):
            hollow.append(
                f"{name}（语料命中率 {salience:.0%}）：正 {len(ph)}/{len(pos)} · "
                f"负 {len(nh)}/{len(neg)} ⇒ 一侧被抽干，只看它就能判正负"
            )
        # 判据 5：梯度（100%/0% 这种极端情况也会被这条抓住，差值是 1.0）
        gap = abs(len(ph) / len(pos) - len(nh) / len(neg))
        gaps.append((name, gap, salience))

    assert not hollow, (
        f"[{scope}] 会话体标记能在某一侧被抽干 ⇒ 只靠它能判正负：\n  "
        + "\n  ".join(hollow)
    )
    detail = " · ".join(f"{n} {g:.0%}" for n, g, _ in gaps)
    worst_name, worst, worst_sal = max(gaps, key=lambda t: t[1])
    assert worst <= _MAX_GAP, (
        f"[{scope}] 会话体标记占比差过大（{detail}）："
        f"{worst_name} 差 {worst:.0%} > 阈值 {_MAX_GAP:.0%}（语料命中率 {worst_sal:.0%}）"
        " —— 形式特征又开始携带标签了"
    )

# -*- coding: utf-8 -*-
"""第 299 轮 P1b：`modules/trade/risk_scan.py`（P0 的判定内核）的自有判据。

====================================================================
★ 为什么需要这个文件（以及它是怎么被发现的）
====================================================================
P0 交付时这个 642 行的判定内核**没有任何 pytest 覆盖** —— 它的正确性只由一次
离线评测脚本（`scripts/probe_r299_risk_eval.py`）的读数背书。于是「正类口径」
在实现里写成了「有任何等级已知的 hit」，而模块自己的文档写的是「命中四类
风险话术」，两者只在 `r5`（高情绪）上分叉，因此**一直没人发现**：

    GET /api/v1/trade/reviews/risk?deep=true  在 3 条**全负样本**的库上
    报出 risk_count=2，而那两条 is_risk=False / risk_categories=[]。

也就是说 `decision == "risk"` 与 `is_risk == False` 可以同时成立。
P1 把它接到界面上时，这个分叉立刻变成用户可见的自相矛盾：
**「红皮 + 置顶 + 没有风险标签」**，而「风险 2」把普通情绪差评算进了风险计数。

⇒ 教训：判定内核不能只靠「离线评测的读数」背书。评测脚本会过时、会没人重跑，
   而门禁会一直在。本文件的判据全部直接问**评测报告里写下的口径**。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from modules.trade import risk_scan as rs

BACKEND = Path(__file__).resolve().parents[1]
SRC = (BACKEND / "modules" / "trade" / "risk_scan.py").read_text(encoding="utf-8")

# ============================================================ 样本
#
# ★ 每一条都**实测过**命中（不是「大概会命中」）。判据的 needle 必须先证明
#   在实现里真的存在，否则 `.includes()` 恒假、取反后恒真 = 空跑。
#   实测读数（第 299 轮）：
#     threat → r1/high      claim → r2+r4/high    atoz → r3/high
#     case   → r4/high      emotion → r5/low（无四类）   neutral → 无命中
#     five   → 规则无命中，但**朴朴素通道误报 r4**（这正是融合拒绝名单的存在理由）

T_THREAT = "I will leave a 1-star review and tell everyone about this, or I'll take this further."
T_CLAIM = "I want a full refund or I will dispute this with my credit card company."
T_ATOZ = "I am going to file an A-to-Z claim if you do not respond."
T_CASE = "I already reported this seller to Amazon support and filed a complaint."
T_EMOTION = "This is garbage and a complete waste of money. Never again."
T_NEUTRAL = "The box arrived with a small dent on the corner."
T_FIVE_STAR = "Exactly as described, arrived early, no complaints at all"

FOUR_RISK_SAMPLES = [
    (T_THREAT, rs.CAT_THREAT),
    (T_CLAIM, rs.CAT_CLAIM),
    (T_ATOZ, rs.CAT_ATOZ),
    (T_CASE, rs.CAT_CASE),
]

ALL_SAMPLES = [T_THREAT, T_CLAIM, T_ATOZ, T_CASE, T_EMOTION, T_NEUTRAL, T_FIVE_STAR]


# ============================================================ 1. 规则通道的四类

@pytest.mark.parametrize("text,cat", FOUR_RISK_SAMPLES)
def test_rules_hit_the_four_risk_categories(text, cat):
    """四类风险话术各自能命中，且带上原文证据、等级为 high。"""
    res = rs.scan_rules(text)
    assert cat in res.risk_categories, f"{cat} 没命中：{res.categories}"
    assert res.decision == rs.DECISION_RISK
    assert res.is_risk is True
    assert res.top_level == rs.LEVEL_HIGH
    assert any(h.evidence for h in res.hits), "命中必须带原文证据（否则老板没法拿去原文里搜）"


def test_plain_negative_review_is_clean():
    """普通差评（到货有磕碰）不是风险话术，也不是「不敢定」。"""
    res = rs.scan_rules(T_NEUTRAL)
    assert res.hits == []
    assert res.decision == rs.DECISION_CLEAN
    assert res.is_risk is False


# ============================================================ 2. ★ r5 不是风险话术

def test_high_emotion_alone_is_not_a_risk_verdict():
    """★ 回归靶点：`r5`（高情绪）是候选池辅助档，**不是风险话术**。

    ★ 反向注入：把 `_decide` 的正类判据改回「有任何等级已知的 hit」
      （或把 `fuse` 的守卫改回 `merged.hits`）⇒ 本用例转红。
      这正是 P0 交付时的形态：高情绪被算成 risk。
    """
    res = rs.scan_rules(T_EMOTION)
    assert res.categories == [rs.CAT_EMOTION], f"样本失效：{res.categories}"
    assert res.risk_categories == []
    assert res.is_risk is False
    assert res.decision != rs.DECISION_RISK, "「高情绪」被算成了风险话术"


def test_a_plain_dent_is_not_emotion_either():
    """r5 的**反面**对照：连情绪都没有的普通差评不得被打上 r5。"""
    assert rs.scan_rules(T_NEUTRAL).categories == []


#: 混合样本（实测：命中 r1，且 `_EMOTION` 也真的匹配 —— 证据在样本本身，不在注释里）
T_MIXED = "This is garbage. I will leave a 1-star review for everyone, or I will sue you."


def test_emotion_is_not_reported_when_a_real_risk_category_already_hit():
    """★ r5 是候选池档，**不得**与四类混在同一个数字里（`scan_rules` 里的守卫）。

    ★ 反向注入：把 `if not res.risk_categories:` 改成 `if True:` ⇒ 本用例转红。
      守卫的必要性由样本自身给出：先断言 `_EMOTION` 在这条文本上确实命中，
      否则「没混进来」可能只是因为压根没匹配上（假绿）。
    """
    assert rs._EMOTION.search(T_MIXED), "样本失效：这条文本根本没触发情绪词"
    res = rs.scan_rules(T_MIXED)
    assert res.risk_categories == [rs.CAT_THREAT], f"r1 没命中：{res.categories}"
    assert res.categories == [rs.CAT_THREAT], f"r5 混进了风险样本：{res.categories}"


def test_decide_respects_an_explicit_decision():
    """`_decide` 只**兜底**填 decision，不覆盖各通道已显式给出的结论。"""
    res = rs.ScanResult(
        hits=[rs.RiskHit(category=rs.CAT_THREAT, level=rs.LEVEL_HIGH)],
        channel="llm", decision=rs.DECISION_UNKNOWN,
    )
    assert rs._decide(res).decision == rs.DECISION_UNKNOWN


# ============================================================ 3. ★ 唯一正类口径

@pytest.mark.parametrize("text", ALL_SAMPLES)
def test_decision_risk_is_equivalent_to_is_risk(text):
    """★★ 唯一正类口径：`decision == risk` ⟺ 命中 `RISK_CATEGORIES`。

    ★ 为什么这条是本文件的核心：`decision` 是**界面排序与计数**的口径，
      `is_risk` 是**评测与标签**的口径。两者一旦分叉，界面上就会出现
      「红皮置顶但无风险标签」，而「风险 N」把普通情绪差评算进去。
      分叉不会有任何报错 —— 只会让读数静默失真。
    """
    for res in (rs.scan_rules(text), rs.scan_naive(text)):
        assert (res.decision == rs.DECISION_RISK) == bool(res.risk_categories), (
            f"decision={res.decision} 但 risk_categories={res.risk_categories}"
        )


# ============================================================ 4. 融合

def _llm_result(decision: str, *, level: str | None = None, cats=()) -> rs.ScanResult:
    """造一个「LLM 通道」的结果（显式给 decision，模拟 `scan_llm` 的两条出口）。"""
    hits = [
        rs.RiskHit(category=c, level=level or rs.LEVEL_UNKNOWN,
                   evidence=[], channel="llm", note="stub")
        for c in cats
    ]
    return rs.ScanResult(hits=hits, channel="llm", decision=decision)


def test_fuse_rejects_the_naive_channel():
    """★★ 朴素通道是**反面基线**，必须被融合拒绝（拒绝名单，不是靠调用方自觉）。

    ★ 反向注入：把 `fuse` 里的 `r.channel != "naive"` 去掉 ⇒ 本用例转红。
      守卫的必要性由**样本自身**给出：先断言朴素通道在这条五星好评上真的误报，
      断言不成立就说明样本失效（fail loud，而不是静默失去覆盖）。
    """
    naive = rs.scan_naive(T_FIVE_STAR)
    assert naive.is_risk is True, (
        "样本失效：朴素通道在五星好评上没有误报，这条用例就不再证明任何事"
    )
    fused = rs.fuse([
        naive,
        rs.scan_rules(T_FIVE_STAR),
        _llm_result(rs.DECISION_CLEAN),
    ])
    assert fused.risk_categories == []
    assert fused.decision == rs.DECISION_CLEAN
    assert all(h.channel != "naive" for h in fused.hits)


def test_fuse_marks_risk_when_a_channel_hits_a_real_category():
    """只要有一支命中四类 ⇒ 融合就是 risk；r5 只作为证据跟在后面。"""
    fused = rs.fuse([rs.scan_rules(T_EMOTION), rs.scan_rules(T_THREAT)])
    assert fused.decision == rs.DECISION_RISK
    assert fused.is_risk is True
    assert set(fused.risk_categories) == {rs.CAT_THREAT}
    assert set(fused.categories) == {rs.CAT_THREAT, rs.CAT_EMOTION}


def test_fuse_keeps_doubt_when_only_emotion_hit():
    """★ 规则说「高情绪」+ LLM 说「拿不准」⇒ **未定论**。

    两个方向都要挡住：
      - 不能判 `risk`（r5 不是风险话术）；
      - 不能被 r5 的命中存在**洗成 clean**（那就把「拿不准」静默变白了）。

    ★ 反向注入：把 `fuse` 的守卫从 `merged.risk_categories` 改回
      `merged.hits` ⇒ 本用例转红（短路发生在 `_decide` 之前）。
    """
    rule = rs.scan_rules(T_EMOTION)
    assert rule.categories == [rs.CAT_EMOTION]
    llm = _llm_result(rs.DECISION_UNKNOWN, cats=(rs.CAT_EMOTION,))
    fused = rs.fuse([rule, llm])
    assert fused.categories == [rs.CAT_EMOTION], "r5 证据不该丢"
    assert fused.decision == rs.DECISION_UNKNOWN
    assert fused.is_risk is False


def test_fuse_is_clean_when_rules_say_emotion_and_llm_says_no_risk():
    """规则说「高情绪」+ LLM **明确**判无风险 ⇒ clean（r5 本身不构成定论）。"""
    fused = rs.fuse([rs.scan_rules(T_EMOTION), _llm_result(rs.DECISION_CLEAN)])
    assert fused.decision == rs.DECISION_CLEAN
    assert fused.is_risk is False
    assert fused.categories == [rs.CAT_EMOTION]


# ============================================================ 5. LLM 通道的两条出口

class _StubLLM:
    def __init__(self, payload=None, exc: Exception | None = None):
        self.payload, self.exc = payload, exc

    async def structured_chat(self, **kw):  # noqa: ANN003
        if self.exc is not None:
            raise self.exc
        return self.payload


async def test_llm_call_failure_is_unknown_not_clean():
    """调用失败 ⇒ 未定论。★ 失败绝不能被写成「判了没风险」。"""
    res = await rs.scan_llm(T_NEUTRAL, llm=_StubLLM(exc=RuntimeError("boom")))
    assert res.decision == rs.DECISION_UNKNOWN
    assert res.is_risk is False


async def test_llm_unparseable_output_is_unknown_not_clean():
    """输出无法解析成判定体 ⇒ 未定论（不猜）。"""
    res = await rs.scan_llm(T_NEUTRAL, llm=_StubLLM(payload="not-a-dict"))
    assert res.decision == rs.DECISION_UNKNOWN
    assert res.is_risk is False


async def test_llm_empty_categories_with_a_known_level_is_clean():
    """空判定 + 已知等级 = LLM **明确**判无风险 ⇒ clean。"""
    res = await rs.scan_llm(
        T_NEUTRAL, llm=_StubLLM({"categories": [], "level": "low", "reason": "no risk"}))
    assert res.decision == rs.DECISION_CLEAN
    assert res.hits == []


async def test_llm_empty_categories_with_unknown_level_is_unknown():
    """空判定 + unknown 等级 = 算法不敢定 ⇒ 未定论。与上一条方向相反，不可合并。"""
    res = await rs.scan_llm(
        T_NEUTRAL, llm=_StubLLM({"categories": [], "level": "unknown", "reason": "?"}))
    assert res.decision == rs.DECISION_UNKNOWN
    assert res.is_risk is False


async def test_llm_r5_only_is_not_a_risk_verdict():
    """LLM 也只报了 r5 ⇒ 不是风险话术（与规则通道同口径）。"""
    res = await rs.scan_llm(
        T_EMOTION, llm=_StubLLM({"categories": ["r5"], "level": "low", "reason": "angry only"}))
    assert res.categories == [rs.CAT_EMOTION]
    assert res.decision != rs.DECISION_RISK
    assert res.is_risk is False


# ============================================================ 6. 形态门禁
#
# ★ 为什么用 AST 而不是「源码字符串包含」：docstring 里就写着
#   `risk_categories` 和 `h.level != LEVEL_UNKNOWN` 这两个词
#   （本文件的模块注释与 `_decide` 的说明里都有），字符串判据会被自己的注释骗过
#   ⇒ 假绿。形态判据必须走 AST。

def _func(name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"risk_scan.py 里找不到函数 {name}")


def test_decide_keys_the_risk_verdict_on_risk_categories():
    """`_decide` 的正类判据必须是 `risk_categories`（唯一真源）。"""
    fn = _func("_decide")
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "risk_categories" in attrs, (
        "_decide 不再以 risk_categories 当正类判据 ⇒ 高情绪会被算成风险"
    )


def test_decide_does_not_use_hit_presence_as_the_risk_predicate():
    """`_decide` 里不得再出现 `h.level != LEVEL_UNKNOWN` 这类**存在性**判据。"""
    fn = _func("_decide")
    neq = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Compare) and any(isinstance(o, ast.NotEq) for o in n.ops)
    ]
    assert not neq, "「有等级已知的 hit 就算 risk」回来了 ⇒ r5 会重新被算成风险"


def test_fuse_guards_its_decide_call_with_risk_categories():
    """`fuse` 里的 `_decide` 调用必须落在「命中四类」的分支里。

    ★ 这一条钉的是**短路位置**：守卫若写成 `merged.hits`（r5 也在 hits 里），
      则 `_decide` 修得再对也没用 —— 分支早就进去了。
    """
    fn = _func("fuse")
    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_decide"
    ]
    assert calls, "fuse 里不再调用 _decide"
    guarded = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        names = {x.attr for x in ast.walk(node.test) if isinstance(x, ast.Attribute)}
        if "risk_categories" not in names:
            continue
        for c in ast.walk(node):
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_decide":
                guarded.add(id(c))
    assert all(id(c) in guarded for c in calls), (
        "fuse 里的 _decide 调用没有被「命中四类」守卫圈住（r5 会短路成 risk）"
    )


# ============================================================ 7. ★ 批量协议（第 300 轮 · C）
#
# 为什么这批判据必须存在：批量通道是**生产路径**（deep 就走它），而它是**另一套
# 输出协议**（压缩映射）。压缩意味着信息更少 ⇒ 「少了的那部分会不会悄悄改变结论」
# 就是它唯一需要被钉住的地方。三条：
#   ① 三态（clean / unknown / risk）在压缩协议里**仍然可分**；
#   ② 缺项与解析失败一律 fail-closed 到 unknown（绝不猜 clean）；
#   ③ 与逐条版**同口径** —— 等价判定必须得到同一个 decision。

class _BatchStubLLM:
    """批量通道的最小 LLM 桩（`structured_chat` 回预设对象，并记录每次入参）。"""

    def __init__(self, payload=None, exc: Exception | None = None):
        self.payload, self.exc, self.calls = payload, exc, []

    async def structured_chat(self, **kw):  # noqa: ANN003
        self.calls.append(kw)
        if self.exc is not None:
            raise self.exc
        return self.payload


async def test_batch_returns_one_result_per_input_in_order():
    """★ 契约：等长同序。调用方直接 `zip(inputs, out)` 回填，不必自己处理缺项。"""
    llm = _BatchStubLLM({"1": "r1:high|" + T_THREAT[:40], "2": "", "3": "?"})
    out = await rs.scan_llm_batch([T_THREAT, T_NEUTRAL, T_EMOTION], llm=llm)
    assert [r.decision for r in out] == [
        rs.DECISION_RISK, rs.DECISION_CLEAN, rs.DECISION_UNKNOWN,
    ]
    assert out[0].categories == [rs.CAT_THREAT]
    assert out[1].hits == [], "「无风险」应当是空 hits（与逐条版同形）"
    assert len(llm.calls) == 1, "3 条（≤ 一包）必须只发一次请求"


async def test_batch_passes_max_tokens_per_call():
    """★ `max_tokens` 必须**逐次**传。

    `get_llm()` 按模型名缓存单例 ⇒ 建实例那次之后再传参数是**无效的**；
    批量输出随条数增长，截断 ⇒ JSON 解析失败 ⇒ 整包判 unknown。
    """
    llm = _BatchStubLLM({"1": ""})
    await rs.scan_llm_batch([T_NEUTRAL], llm=llm)
    assert llm.calls[0].get("max_tokens") == rs._batch_max_tokens(1)
    assert llm.calls[0].get("output_format") == "json"


async def test_batch_three_states_stay_distinguishable():
    """★★ 压缩协议**不许**把三态压成两态。

    ★ 只回「序号 → 类别码」时，`""`（无风险）与「拿不准」**都是空串** ——
      合并就等于把「算法不敢定」静默洗白成「判了干净」。本仓最忌讳的一类静默退化。
      所以协议里必须有一个显式的 `?`（见 `prompts.RISK_SCAN_BATCH_SYSTEM_PROMPT`）。
    """
    llm = _BatchStubLLM({"1": "", "2": "?"})
    out = await rs.scan_llm_batch([T_NEUTRAL, T_NEUTRAL], llm=llm)
    assert out[0].decision == rs.DECISION_CLEAN
    assert out[1].decision == rs.DECISION_UNKNOWN, "「拿不准」被压成了「干净」"
    assert out[0].decision != out[1].decision, "三态被压成了两态"


async def test_batch_missing_item_is_unknown_not_clean():
    """★ 批量输出缺一条 ⇒ `unknown`（**不是** `clean`）：不知道它是漏了还是没风险。"""
    out = await rs.scan_llm_batch([T_NEUTRAL, T_EMOTION], llm=_BatchStubLLM({"1": ""}))
    assert out[0].decision == rs.DECISION_CLEAN
    assert out[1].decision == rs.DECISION_UNKNOWN, "缺项被当成了「无风险」"
    assert "缺" in out[1].hits[0].note, "缺项的原因没写进 note"


async def test_batch_unparseable_output_is_unknown_for_every_item():
    """整包读不出来 ⇒ 每一条都是 `unknown`，一条都不许猜成 `clean`。"""
    out = await rs.scan_llm_batch([T_NEUTRAL, T_EMOTION], llm=_BatchStubLLM("not-a-dict"))
    assert [r.decision for r in out] == [rs.DECISION_UNKNOWN] * 2
    assert all(r.is_risk is False for r in out)


async def test_batch_llm_failure_is_unknown_not_clean():
    """调用失败 ⇒ 未定论。★ 失败绝不能被写成「判了没风险」。"""
    out = await rs.scan_llm_batch([T_NEUTRAL], llm=_BatchStubLLM(exc=RuntimeError("boom")))
    assert out[0].decision == rs.DECISION_UNKNOWN
    assert "失败" in out[0].hits[0].note


async def test_batch_accepts_the_shapes_models_actually_return():
    """模型不按协议回时也得读懂：包裹 / 列表 / **逐条版对象**。

    ★ 只认一种形态，就会把「格式不合我意」记成「模型判不出来」—— 归因方向错。
    """
    for payload in (
        {"items": {"1": "r1:high"}},
        [{"n": 1, "value": "r1:high"}],
        [{"n": 1, "categories": ["r1"], "level": "high", "evidence": {"r1": T_THREAT}}],
    ):
        out = await rs.scan_llm_batch([T_THREAT], llm=_BatchStubLLM(payload))
        assert out[0].decision == rs.DECISION_RISK, f"形态没认出来：{payload}"
        assert out[0].categories == [rs.CAT_THREAT]


async def test_batch_evidence_must_be_grounded():
    """★ 证据必须能回到原文 —— 与逐条版同一条铁律（防 LLM 编证据）。"""
    out = await rs.scan_llm_batch(
        [T_THREAT], llm=_BatchStubLLM({"1": "r1:high|完全不在原文里的一句"}))
    ev = out[0].hits[0].evidence[0]
    assert ev.startswith("<未落地"), f"没落地的证据被原样收下了：{ev}"


async def test_batch_missing_level_falls_back_and_says_so():
    """协议里等级缺了 ⇒ 按类别默认，且**把兜底写进 note**（不静默改口径）。"""
    out = await rs.scan_llm_batch([T_CLAIM], llm=_BatchStubLLM({"1": "r2|" + T_CLAIM[:30]}))
    assert out[0].hits[0].level == rs._DEFAULT_LEVEL_BY_CATEGORY[rs.CAT_CLAIM]
    assert "等级缺失" in out[0].note, "兜底这件事没写进 note ⇒ 口径被静默改写"


async def test_batch_and_single_agree_on_equivalent_payloads():
    """★★ 两条协议**同口径**：等价判定必须得到同一个 decision。

    ★ 为什么必须钉住：批量是生产路径、逐条是基准。两者对同一判定给出不同结论时，
      报告里的数字取决于「你走了哪条路」，而且不会有任何报错。
    """
    pairs = [
        ({"categories": [], "level": "low"}, "", rs.DECISION_CLEAN),
        ({"categories": [], "level": "unknown"}, "?", rs.DECISION_UNKNOWN),
        ({"categories": [rs.CAT_CLAIM], "level": "high"},
         f"{rs.CAT_CLAIM}:high|" + T_CLAIM[:30], rs.DECISION_RISK),
        ({"categories": [rs.CAT_EMOTION], "level": "low"},
         f"{rs.CAT_EMOTION}:low", rs.DECISION_CLEAN),
    ]
    for single_payload, batch_value, want in pairs:
        one = await rs.scan_llm(T_CLAIM, llm=_StubLLM(single_payload))
        many = await rs.scan_llm_batch([T_CLAIM], llm=_BatchStubLLM({"1": batch_value}))
        assert one.decision == many[0].decision == want, (
            f"两条协议不一致：单条 {one.decision} / 批量 {many[0].decision}（期望 {want}）"
        )


async def test_batch_chunking_keeps_order_and_length_across_chunks():
    """拆包**不许**打乱顺序或丢条目：`n` 条 → `ceil(n/CHUNK)` 包 → 等长同序拼回。

    ★ 让每一包回**不同**的值：如果拼装按「完成先后」而不是按包序拼，结果位置就会
      错位 —— 而「全都是 clean」时顺序错了也看不出来（本条前身就是这么写成空跑的）。
    ★ 反向注入：把拼装改成 `for chunk in reversed(done)` ⇒ 本用例转红。
    """
    C = rs.RISK_SCAN_BATCH_CHUNK
    n = C + 3
    texts = [f"t{i}" for i in range(n)]
    llm = _BatchStubLLM()

    async def _structured_chat(**kw):  # noqa: ANN003
        llm.calls.append(kw)
        got = json.loads(kw["user_message"])
        # 满包（第 1 包）⇒ 无风险；不满的那包（第 2 包）⇒ 拿不准
        return {str(it["n"]): ("?" if len(got) < C else "") for it in got}

    llm.structured_chat = _structured_chat  # type: ignore[assignment]
    out = await rs.scan_llm_batch(texts, llm=llm)

    assert len(out) == n == len(texts)
    assert [r.decision for r in out] == (
        [rs.DECISION_CLEAN] * C + [rs.DECISION_UNKNOWN] * 3
    ), "拆包拼回的顺序错了（或丢了条目）"
    assert len(llm.calls) == rs.batch_chunk_count(n) == 2


def test_batch_chunk_count_is_the_only_packing_math():
    """包数计算只有一处实现（`batch_chunk_count`），且 0 条 = 0 次。"""
    C = rs.RISK_SCAN_BATCH_CHUNK
    assert rs.batch_chunk_count(0) == 0
    assert [rs.batch_chunk_count(k) for k in (1, C, C + 1, 2 * C, 2 * C + 1)] == [1, 1, 2, 2, 3]


def test_every_category_has_a_default_level():
    """★ 等级兜底表必须覆盖**全部**类别码，否则缺等级时那条会掉进 `unknown`。"""
    assert set(rs._DEFAULT_LEVEL_BY_CATEGORY) == set(rs.CATEGORY_LABELS)
    assert all(v in rs._LEVEL_ORDER for v in rs._DEFAULT_LEVEL_BY_CATEGORY.values())


def test_scan_full_is_gone():
    """★ `scan_full` 已退役：它是「第二份语义入口」，本仓铁律是收唯一真源。

    ★ 反向注入：把 `scan_full` 加回来 ⇒ 本用例转红（并且 `service` 侧那条
      「不得逐条调语义」的判据也会红）。
    """
    assert not hasattr(rs, "scan_full"), "scan_full 又回来了（逐条语义的第二份入口）"
    assert hasattr(rs, "scan_llm_batch"), "批量语义通道不见了"

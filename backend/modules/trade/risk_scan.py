# -*- coding: utf-8 -*-
"""买家评论风险话术识别（第 299 轮 · P0 试做）
====================================================

★ P0 边界：**只做判定，不做任何写操作**。不建表、不改表、不发消息、不执行补偿。
  产出物是「这条评论疑似属于哪类风险 + 等级 + 证据片段」，供人复核。

★ 为什么叫 `risk_scan` 而不是 `risk_alert`：
  「alert（预警）」隐含「已经通知出去了」——本模块**没有通知能力**。
  等 P1 把结果接到界面上，或 P2 接通平台通道，才配得上 alert 这个名字。

★ 三通道（互相并列取证，**不是短路关系**）
----------------------------------------------------
    naive  —— 朴素关键词：任一风险词命中即报。**故意保留**，用作反面基线：
              它就是「用关键词做风控」这条路真实的样子，误报率写在评测报告里。
    rule   —— 结构化窄口径：要求「筹码/诉求」+「施压/条件结构」同时出现。
              精确率高、召回低，可作为零成本兜底。
    llm    —— 语义判定：处理「词不在但语义在」以及 §陷阱样本。

★ 一条设计铁律：**判定必须带证据片段**
  给不出原文片段的判定等于一句读后感（本仓既有判据）。因此 `RiskHit.evidence`
  是必填，且必须来自原文（由 `_slice_evidence` 保证是原文子串）。

★ fail-closed：拿不准 ⇒ `level="unknown"` 且 categories 为空，**不得**静默当作
  「无风险」。评测脚本据 `unknown` 数单独报一列。

★ 为什么语义通道有「逐条」与「批量」两条实现（第 300 轮）
--------------------------------------------------------
  `scan_llm`（逐条）是**参照实现**：一次判一条，给出完整的 level 与证据，
  被离线评测脚本与「批量 ↔ 逐条一致性」门禁当作基准。
  `scan_llm_batch`（批量）是**生产路径**：一次判 ≤10 条，只付一次固定开销，
  输出协议是压缩的（见 `prompts.RISK_SCAN_BATCH_SYSTEM_PROMPT`）。
  两者并存而不是二选一，理由有三：
    ① 「批量判得对不对」需要一个**独立来源**的答案，否则两边一起错也看不出来；
    ② 批量版的输出协议与逐条版**不是同一个东西**，它不是一个布尔参数；
    ③ 删掉逐条版，评测脚本就得自己再抄一份判据 —— 那才是真正的两份实现。
  ★ 共享的是**判据**（`prompts.py` 里那套 r1~r5 口径），不是输出协议。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ★ 正文住 `prompts.py`（门禁要求，见该文件头部）：这里只留名字。
from .prompts import RISK_SCAN_BATCH_SYSTEM_PROMPT, RISK_SCAN_LLM_SYSTEM_PROMPT

# ============================================================ 常量

CAT_THREAT = "r1"          # 加码要挟（以尚未发生的升级为筹码）
CAT_CLAIM = "r2"           # 索赔 / 要钱
CAT_ATOZ = "r3"           # A-to-Z 索赔前兆
CAT_CASE = "r4"           # 开 case / 投诉平台
CAT_EMOTION = "r5"         # 高情绪差评（辅助档，不算「风险话术」）

CATEGORY_LABELS = {
    CAT_THREAT: "加码要挟",
    CAT_CLAIM: "索赔要钱",
    CAT_ATOZ: "A-to-Z 前兆",
    CAT_CASE: "开 case 投诉",
    CAT_EMOTION: "高情绪差评",
}

# ★ 真正的「四类风险」—— r5 不在内（它是候选池，不是风险话术）
RISK_CATEGORIES = (CAT_THREAT, CAT_CLAIM, CAT_ATOZ, CAT_CASE)

LEVEL_HIGH = "high"
LEVEL_MEDIUM = "medium"
LEVEL_LOW = "low"
LEVEL_UNKNOWN = "unknown"

# ★ 等级的**中文名唯一真源**（与 `CATEGORY_LABELS` 同一范式）。
#   为什么不能让前端自己写一份 map：两端各写一份 ⇒ 改了这边忘那边，
#   界面显示「高风险」而后端 `/reviews/risk` 说的是 `high`，对不上账时
#   谁也说不清是哪边错了。前端一律从端点拿 `level_labels`。
LEVEL_LABELS = {
    LEVEL_HIGH: "高危",
    LEVEL_MEDIUM: "中危",
    LEVEL_LOW: "低危",
    LEVEL_UNKNOWN: "未定论",
}

# ★ 一条样本的**最终定论**（与 hits 是两个维度）：
#   hits 说的是「判成了什么类别」，decision 说的是「这条到底有没有定论」。
#   ★ 必须分开：把「LLM 明确判无风险」也记成 `unknown` 会让统计里
#     「未定论」这一列变成「无风险」的同义词 —— 两个含义相反的结论混成一个数，
#     报告里就再也读不出「算法到底有多少条不敢下结论」。第 299 轮实测踩过。
DECISION_RISK = "risk"
DECISION_CLEAN = "clean"
DECISION_UNKNOWN = "unknown"

_LEVEL_ORDER = {LEVEL_LOW: 1, LEVEL_MEDIUM: 2, LEVEL_HIGH: 3}

# 建议动作（★ 等级与动作分列：等级=文本判成什么，动作=人该做什么）
SUGGESTED_ACTION = {
    LEVEL_HIGH: "立即人工介入：优先处置，走 review_dispositions 的 proposed",
    LEVEL_MEDIUM: "24h 内人工确认",
    LEVEL_LOW: "进候选池，批量看",
    LEVEL_UNKNOWN: "人工判（算法未定论）",
}


@dataclass
class RiskHit:
    category: str
    level: str
    evidence: list[str] = field(default_factory=list)
    channel: str = ""          # naive | rule | llm
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "label": CATEGORY_LABELS.get(self.category, self.category),
            "level": self.level,
            "evidence": list(self.evidence),
            "channel": self.channel,
            "note": self.note,
        }


@dataclass
class ScanResult:
    hits: list[RiskHit] = field(default_factory=list)
    channel: str = ""
    # risk | clean | unknown —— 见 DECISION_* 常量。由 `_decide()` 兜底填。
    decision: str = ""
    note: str = ""

    @property
    def categories(self) -> list[str]:
        seen: list[str] = []
        for h in self.hits:
            if h.category not in seen:
                seen.append(h.category)
        return seen

    @property
    def risk_categories(self) -> list[str]:
        return [c for c in self.categories if c in RISK_CATEGORIES]

    @property
    def top_level(self) -> str:
        best = LEVEL_LOW
        for h in self.hits:
            if _LEVEL_ORDER.get(h.level, 0) > _LEVEL_ORDER.get(best, 0):
                best = h.level
        return best if self.hits else LEVEL_LOW

    @property
    def is_risk(self) -> bool:
        """是否判成「四类风险话术」之一（评测的正类口径）。"""
        return bool(self.risk_categories)


# ============================================================ 定论兜底

def _decide(res: ScanResult) -> ScanResult:
    """按 hits 兜底填 decision（各通道可显式设过，显式优先）。

    ★ 三态不可压成两态：`unknown`（算法不敢定）与 `clean`（算法明确判无风险）
      是**相反**的结论 —— 前者要人补判，后者不用。合并会让报告失真。

    ★★ 正类口径**只有一份**：risk ⟺ 命中 `RISK_CATEGORIES`（四类风险话术）。
      不能用「有任何等级已知的 hit」当判据 —— `r5`（高情绪）也是「等级已知的
      hit」，但它按定义**不是风险话术**（见 `CAT_EMOTION` 注释与
      `scan_rules` 的「只在没有四类风险时才报」，以及首轮评测里
      「r5 与 none 同为负类」的口径）。用 hit 的存在性当判据会让
      `decision == "risk"` 与 `is_risk == False` 同时成立：
      界面据此画出「红皮 + 无风险标签」的自相矛盾，
      并且「风险 N」计数把普通情绪差评也算进去。
      —— 第 299 轮实测：3 条全负样本的库里报出 risk=2，就是这样来的。
    """
    if res.decision:
        return res
    if res.risk_categories:
        res.decision = DECISION_RISK
    elif any(h.level == LEVEL_UNKNOWN for h in res.hits):
        res.decision = DECISION_UNKNOWN
    else:
        res.decision = DECISION_CLEAN
    return res


# ============================================================ 证据切片

def _slice_evidence(text: str, pattern: re.Pattern, span: int = 60) -> list[str]:
    """把命中位置扩成一个**原文子串**（前后各 span 字符，按词边界收敛）。

    ★ 必须是原文子串（`m.group(0)` 加上下文），不得拼接/改写 —— 否则老板
      拿证据去原文里搜不到，等于伪造证据。
    """
    out: list[str] = []
    for m in pattern.finditer(text):
        a = max(0, m.start() - span)
        b = min(len(text), m.end() + span)
        # ★ 按词边界收敛：否则会从单词中间切开（实测出现过证据以 `t it back for...`
        #   开头 —— 老板拿这条去原文里搜，搜不到，等于证据不可用）。
        if a > 0:
            sp = text.find(" ", a)
            if sp != -1 and sp < m.start():
                a = sp + 1
        if b < len(text):
            sp = text.rfind(" ", m.end(), b)
            if sp != -1:
                b = sp
        frag = " ".join(text[a:b].split())
        if frag and frag not in out:
            out.append(frag)
        if len(out) >= 3:
            break
    return out


# ============================================================ 通道 1：朴素关键词
# ★ 故意写得「像大多数人第一版会写的那样」：一个词表，命中即报。
#   它的误报率就是本评测要回答的第一个问题。

_NAIVE_VOCAB: dict[str, list[str]] = {
    CAT_THREAT: [
        r"review", r"rating", r"star", r"feedback", r"social media", r"facebook",
        r"twitter", r"instagram", r"reddit", r"public", r"lawyer", r"attorney",
        r"lawsuit", r"sue", r"legal",
    ],
    CAT_CLAIM: [
        r"refund", r"reimburs", r"money back", r"compensat", r"damages",
        r"replacement", r"return", r"dispute", r"charge ?back", r"coupon",
    ],
    CAT_ATOZ: [
        r"a[-\s]?to[-\s]?z", r"guarantee", r"protection", r"claim",
    ],
    CAT_CASE: [
        r"case", r"complain", r"report", r"escalat", r"ombudsman",
        r"seller performance", r"grievance",
    ],
}

_NAIVE_COMPILED = {
    cat: re.compile("|".join(f"(?:{p})" for p in pats), re.IGNORECASE)
    for cat, pats in _NAIVE_VOCAB.items()
}


def scan_naive(text: str) -> ScanResult:
    res = ScanResult(channel="naive")
    for cat, pat in _NAIVE_COMPILED.items():
        if pat.search(text):
            res.hits.append(RiskHit(
                category=cat, level=LEVEL_HIGH,
                evidence=_slice_evidence(text, pat), channel="naive",
                note="朴素关键词命中（未判语义）",
            ))
    return _decide(res)


# ============================================================ 通道 2：结构化规则
# ★ 口径：筹码/诉求 必须与 施压/条件结构 同时出现。
#   这就把「谢谢你痛快退款」这类叙述排除掉了 —— 它们有诉求词但无施压结构。

# 筹码：以「公开评价 / 曝光 / 法务」为要挟手段
_R1_PROP = re.compile(
    r"(?:\b(?:1|one)[-\s]?star\b"
    r"|\b(?:bad|negative|poor|honest|scathing)\s+(?:review|feedback|rating)\b"
    r"|\b(?:leave|write|post|make|put)\s+(?:a\s+|an\s+)?(?:\w+\s+){0,2}(?:review|feedback|post)\b"
    r"|\b(?:tell|warn|inform)\s+(?:everyone|everybody|people|others|the\s+world|buyers?)\b"
    r"|\b(?:make|makes|making)\s+sure\s+(?:every|all|each)\b"
    r"|\bgo(?:ing)?\s+public\b"
    r"|\bshare\s+my\s+(?:experience|story|thoughts|opinion)\b"
    r"|\b(?:social\s+media|facebook|twitter|instagram|tiktok|reddit|youtube|x\.com)\b"
    r"|\bmy\s+(?:next\s+)?post\s+about\b"
    r"|\b(?:sue|lawyer|attorney|solicitor|lawsuit|legal\s+action|small\s+claims)\b"
    r"|\b(?:shop|buy|order)\s+elsewhere\b"
    r"|\b(?:will\s+)?(?:not|n'?t)\s+(?:buy|shop|order)\s+(?:from\s+)?(?:you|again)\b"
    r"|\bstay\s+quiet\b)",
    re.IGNORECASE,
)

# 诉求：要钱 / 要物（R2 的「筹码」）
# ★ `damages?` → `damages`：单数 damage 在评论里是**描述**（"no damage" / "the
#   damage from shipping"），复数 damages 才是法律/赔偿术语。首轮评测集抓出过
#   这条误报（N03/N18）。
_R2_PROP = re.compile(
    r"(?:\brefund\w*\b|\breimburs\w*\b|\bmoney\s+back\b|\bcompensat\w*\b"
    r"|\brecompense\b|\bcharge\s?back\b|\bdamages\b"
    r"|\b(?:want|expect|asking for|demand|need)\s+(?:the\s+|a\s+|my\s+)?"
    r"(?:\w+\s+){0,2}(?:back|refund|reimbursement|compensation|recompense)\b"
    r"|\bfull\s+(?:reimbursement|refund)\b|\bcost\s+of\b)",
    re.IGNORECASE,
)

# ★ 要求式（现在时主动索取）—— 与「叙述式」相对的判别点。
#   本仓教训：判「写了什么」不难，判「想干什么」才难。这一组词是「想干什么」的
#   **最小可算代理**：`I want/expect/demand/asking for + 财物` 是索取；
#   `refund showed up` / `they offered` 是叙述。
#   ★ 语态启发式，必然脆 —— 它是规则通道精确率与召回率同时上不去的根因，
#     写进评测报告，正是「为什么需要 LLM 通道」的实证。
_R2_DEMAND = re.compile(
    r"(?:\bi\s+(?:want|expect|demand|need|request)\b"
    r"|\bi'?m\s+(?:asking|looking|requesting)\s+for\b"
    r"|\b(?:send|give|refund)\s+me\b"
    r"|\basking\s+for\b)",
    re.IGNORECASE,
)

# ★ 叙述式（过去时/被动/第三方已处理）—— 用于剔除「谢谢你痛快退款」这类。
_R2_NARRATIVE = re.compile(
    r"(?:\b(?:refund|return|replacement|compensation)\s+"
    r"(?:showed\s+up|went\s+through|came\s+through|arrived|was\s+processed)\b"
    r"|\b(?:they|seller|support|amazon|the\s+company)\s+"
    r"(?:offered|gave|issued|processed|refunded|sorted|replaced|sent)\b"
    r"|\bno\s+(?:hard\s+)?feelings\b|\bworks?\s+fine\b|\bwould\s+order\s+again\b"
    r"|\bno\s+damage\b|\bno\s+questions\s+asked\b"
    r"|\bbefore\s+it\s+ever\s+got\s+to\b)",
    re.IGNORECASE,
)

# 未来意图 / 已被逼到墙角（R3/R4 的推进标记）
_INTENT = re.compile(
    r"(?:\btomorrow\b|\bnext\s+(?:step|week|time)\b|\bno\s+option\b"
    r"|\bgoing\s+to\b|\babout\s+to\b|\bi'?ll\b|\bi\s+will\b|\bwill\s+be\b"
    r"|\balready\s+\w+ed\b|\bjust\s+\w+ed\b)",
    re.IGNORECASE,
)

# 投诉受理方（R4 的靶子）—— 用于「已在进行中但没写动作词」的形态
_R4_TARGET = re.compile(
    r"(?:seller\s+performance|seller\s+violation\w*|\bombudsman\b"
    r"|consumer\s+(?:protection|rights)|trading\s+standards|regulator\w*"
    r"|credit\s+card\s+company|amazon\s+support|platform\s+support)",
    re.IGNORECASE,
)

# 平台担保索赔（R3 的筹码）
_R3_PROP = re.compile(
    r"(?:\ba[-\s]?to[-\s]?z\b"
    r"|\b(?:buyer|purchase)\s+protection\b"
    r"|\bprotection\s+polic(?:y|ies)\b"
    r"|\b(?:amazon|platform|marketplace)\s+guarantee\b"
    r"|\bclaim\s+(?:form|against)\b"
    r"|\breverse\s+the\s+charge\b"
    r"|\breclaim\s+the\s+payment\b"
    r"|\bstep\s+in\s+and\s+\w+)",
    re.IGNORECASE,
)

# 投诉/举报（R4 的筹码）：动作 + 受理方
_R4_PROP = re.compile(
    r"(?:(?:rais\w+|report\w*|flag\w+|fil\w+|lodg\w+|escalat\w+|complain\w*|grievance)"
    r"[^.!?]{0,60}?"
    r"(?:seller\s+performance|seller\s+violation\w*|amazon|the\s+platform|platform\s+support"
    r"|\bombudsman\b|authorit\w*|credit\s+card\s+company|consumer\s+(?:protection|rights)"
    r"|trading\s+standards|regulator\w*|support\s+team|violation\w*))",
    re.IGNORECASE,
)

# 施压 / 条件结构
_PRESSURE = re.compile(
    r"(?:\bor\s+(?:i|we|else|my)\b"
    r"|\bif\s+(?:you|nothing|i|it|this|the|no\s?one)\b"
    r"|\bunless\b"
    r"|\botherwise\b"
    r"|\b(?:last|final|one)\s+chance\b"
    r"|\b(?:take|taking)\s+this\s+further\b"
    r"|\bafter\s+that\b"
    r"|\bexpect\s+to\s+see\b"
    r"|\bgood\s+luck\s+with\b"
    r"|\b(?:i'?ll|i\s+will|we'?ll|we\s+will|i'?m\s+going\s+to|going\s+to)\s+"
    r"(?:\w+\s+){0,3}(?:report|flag|file|raise|share|post|leave|write|sue|take|claim|let|open|go)\b"
    r"|\b(?:already|just)\s+(?:printed|reported|filed|screenshotted)\b"
    r"|\b\d+\s*(?:hours?|days?)\b[^.!?]{0,30}\b(?:or|after)\b"
    r"|\bwon'?t\s+stay\s+quiet\b"
    r"|\bleft\s+me\s+no\s+option\b"
    r"|\b(?:anything|nothing)\s+(?:less|else)\b)",
    re.IGNORECASE,
)

# 高情绪（R5）
_EMOTION = re.compile(
    r"(?:\bfurious\b|\bdisgust\w*\b|\bgarbage\b|\bwaste\s+of\s+money\b|\bnever\s+again\b"
    r"|\bdo\s+not\s+buy\b|\bridiculous\b|\bappall\w*\b|\bunacceptable\b|\bscam\w*\b"
    r"|\buseless\b|\bregret\b|\bfalling\s+apart\b|\bcheapest\b|\bterrible\b)",
    re.IGNORECASE,
)
_SHOUT = re.compile(r"\b[A-Z]{3,}\b")


def scan_rules(text: str) -> ScanResult:
    """结构化窄口径。

    ★ 四类的门槛**不一样**，这是刻意的（首轮实现在这里出过错：给四类套了同一个
      「筹码 + 施压」门槛，结果 R2 的叙述式全被放过、R4 的「已投诉在办」全漏）：

        R1 加码要挟 : 筹码 + 施压        —— 没有施压就只是抱怨评价
        R2 索赔要钱 : 诉求 + (施压 → high | 要求式且非叙述 → medium)
        R3 A-to-Z   : 筹码 + (施压 或 推进意图)
        R4 开 case  : 动作+靶子，**或** 靶子+推进意图   —— 「已经投诉了」本身就是事实
    """
    res = ScanResult(channel="rule")
    pressured = bool(_PRESSURE.search(text))
    intent = bool(_INTENT.search(text))

    # ---- R1 加码要挟 ----
    if _R1_PROP.search(text) and pressured:
        res.hits.append(RiskHit(
            category=CAT_THREAT, level=LEVEL_HIGH,
            evidence=_slice_evidence(text, _R1_PROP) + _slice_evidence(text, _PRESSURE, 40),
            channel="rule", note="升级筹码 + 施压结构",
        ))

    # ---- R2 索赔要钱 ----
    if _R2_PROP.search(text):
        if pressured:
            res.hits.append(RiskHit(
                category=CAT_CLAIM, level=LEVEL_HIGH,
                evidence=_slice_evidence(text, _R2_PROP) + _slice_evidence(text, _PRESSURE, 40),
                channel="rule", note="索赔诉求 + 施压结构",
            ))
        elif _R2_DEMAND.search(text) and not _R2_NARRATIVE.search(text):
            res.hits.append(RiskHit(
                category=CAT_CLAIM, level=LEVEL_MEDIUM,
                evidence=_slice_evidence(text, _R2_PROP),
                channel="rule", note="明确索取（无最后通牒）",
            ))

    # ---- R3 A-to-Z 前兆 ----
    if _R3_PROP.search(text) and (pressured or intent):
        res.hits.append(RiskHit(
            category=CAT_ATOZ, level=LEVEL_HIGH,
            evidence=_slice_evidence(text, _R3_PROP),
            channel="rule", note="平台担保索赔筹码 + 推进意图",
        ))

    # ---- R4 开 case / 投诉平台 ----
    if _R4_PROP.search(text) or (_R4_TARGET.search(text) and (intent or pressured)):
        res.hits.append(RiskHit(
            category=CAT_CASE, level=LEVEL_HIGH,
            evidence=(_slice_evidence(text, _R4_PROP) or _slice_evidence(text, _R4_TARGET)),
            channel="rule", note="投诉动作/靶子已出现（含已在进行中）",
        ))

    # R5 只在没有四类风险时才报（避免与风险话术混在一个数字里）
    if not res.risk_categories:
        shouts = set(_SHOUT.findall(text))
        # 排除常见正常大写（品牌/单位），只保留 ≥2 个全大写词才算喊话
        if _EMOTION.search(text) or len(shouts) >= 2:
            res.hits.append(RiskHit(
                category=CAT_EMOTION, level=LEVEL_LOW,
                evidence=_slice_evidence(text, _EMOTION) or sorted(shouts)[:3],
                channel="rule", note="高情绪但无升级/索赔结构",
            ))
    return _decide(res)


# ============================================================ 通道 3：LLM 语义判定




def _extract_llm_payload(data: object) -> Optional[dict]:
    """从 LLM 返回里取出判定体。

    ★ 兼容三种形态：裸 dict、`{"result": {...}}` 包裹、`[{...}]` 单元素列表。
      上一版只认裸 dict ⇒ 模型偶尔包一层就整条判成 unknown（假 unknown）。
    """
    if isinstance(data, dict):
        if "categories" in data or "level" in data:
            return data
        for key in ("result", "data", "output", "answer"):
            inner = data.get(key)
            if isinstance(inner, dict) and ("categories" in inner or "level" in inner):
                return inner
        return None
    if isinstance(data, list):
        for item in data:
            got = _extract_llm_payload(item)
            if got is not None:
                return got
    return None


async def scan_llm(text: str, llm=None) -> ScanResult:  # noqa: ANN001
    """LLM 语义判定。

    ★ 解析失败 ⇒ 返回空 hits（level 视作 unknown），**不猜**。
    """
    if llm is None:
        from ai_infra.llm import get_llm
        llm = get_llm(model="qwen-plus", temperature=0.0, max_tokens=600)

    res = ScanResult(channel="llm")
    try:
        data = await llm.structured_chat(
            user_message=f"买家评论：\n{text}\n",
            system_prompt=RISK_SCAN_LLM_SYSTEM_PROMPT,
            output_format="json",
        )
    except Exception as e:  # noqa: BLE001
        res.hits.append(RiskHit(category=CAT_EMOTION, level=LEVEL_UNKNOWN,
                                evidence=[], channel="llm",
                                note=f"LLM 调用失败: {type(e).__name__}"))
        return _decide(res)

    payload = _extract_llm_payload(data)
    if payload is None:
        res.hits.append(RiskHit(category=CAT_EMOTION, level=LEVEL_UNKNOWN,
                                evidence=[], channel="llm",
                                note="LLM 输出无法解析为判定体"))
        return _decide(res)

    cats = payload.get("categories") or []
    level = str(payload.get("level") or "").strip().lower() or LEVEL_UNKNOWN
    if level not in _LEVEL_ORDER and level != LEVEL_UNKNOWN:
        level = LEVEL_UNKNOWN
    ev = payload.get("evidence") or {}
    reason = str(payload.get("reason") or "").strip()[:200]

    if not cats:
        # ★ 空判定分两种，**方向相反**，绝不能合并：
        #   level=unknown → 算法不敢定（要人补判）
        #   level=其它    → LLM 明确判无风险（clean，不用人管）
        if level == LEVEL_UNKNOWN:
            res.note = reason or "LLM 拿不准"
            res.hits.append(RiskHit(category=CAT_EMOTION, level=LEVEL_UNKNOWN,
                                    evidence=[], channel="llm", note=res.note))
            return _decide(res)
        res.decision = DECISION_CLEAN
        res.note = reason or "LLM 判无风险"
        return res

    for c in cats:
        c = str(c).strip().lower()
        if c not in CATEGORY_LABELS:
            continue
        # 证据必须能回到原文（★ 防「LLM 编证据」）
        raw_ev = ev.get(c) or ""
        ev_list = [str(raw_ev)] if str(raw_ev).strip() else []
        if ev_list and not _is_grounded(ev_list[0], text):
            ev_list = [f"<未落地|原文中找不到该片段> {ev_list[0][:80]}"]
        res.hits.append(RiskHit(category=c, level=level, evidence=ev_list,
                                channel="llm", note=reason))
    return _decide(res)


def _is_grounded(fragment: str, text: str) -> bool:
    """证据是否真出自原文。★ 宽松匹配：忽略空白与大小写差异。"""
    def norm(s: str) -> str:
        return re.sub(r"[\s\u2018\u2019\u201c\u201d'\"]+", "", s).lower()
    frag = norm(fragment)
    if not frag:
        return False
    if frag in norm(text):
        return True
    # LLM 常截取中间一段并省略首尾 —— 用较长子串再试一次
    if len(frag) >= 20:
        head = frag[: max(12, len(frag) // 2)]
        if head in norm(text):
            return True
    return False


# ============================================================ 通道 3b：批量语义判定
#
# ★ 为什么需要它（第 300 轮）：老板的实测质疑是「仅 20 条评论就要风险识别非常久」。
#   逐条版 20 条 = 20 次模型调用，实测 43.4 s。瓶颈是**每次调用的固定开销**，
#   不是判定本身 —— 打包成一次调用之后，同样的判定只付一个固定开销。
#
# ★ 输出协议为什么是压缩的：实测瓶颈在**输出 token 量**（19 条约 2.5k）。
#   只回「序号 → 类别码:等级|证据」把输出压到约 0.2k，20.9 s → 6.1 s。
#
# ★ 为什么不是「回一个 JSON 数组、每条一个对象」：那样每条都要重复一遍键名
#   （id/categories/level/evidence/reason），输出量随条数**超线性**增长，
#   而这个函数存在的全部理由就是压住这部分成本。

#: 一次批量调用最多打包多少条。
#: ★ 有上限不是为省钱，是为**失败半径**：一条超长评论撑爆输出 ⇒ 整包 JSON 解析
#:   失败 ⇒ 整包判 unknown。拆包让「坏一条」最多影响一包。
#: ★ 也不宜太小：每包都要付一次固定开销，包太碎就把批量带来的收益还回去了。
RISK_SCAN_BATCH_CHUNK = 10

#: 一包输出 token 的下限 / 上限。
#: ★ 上限必须有：`max_tokens` 直接决定最坏耗时与成本，不能无界跟着条数涨。
_BATCH_MAX_TOKENS_FLOOR = 400
_BATCH_MAX_TOKENS_CEIL = 4000

#: 批量协议里「拿不准」的写法（与「无风险 = 空串」方向**相反**，不可合并）。
_BATCH_UNKNOWN_MARKS = ("?", "？")

#: 类别码 → 默认等级。★ 只在模型**没给等级**时兜底，且兜底这件事会写进 note。
#:   r2 兜到 medium 而不是 high 是**故意**的：拿不到等级时宁可报低不报高 ——
#:   报高会让低优先级的条目抢占人工注意力；报低不会漏（它已经在风险清单里）。
_DEFAULT_LEVEL_BY_CATEGORY = {
    CAT_THREAT: LEVEL_HIGH,
    CAT_CLAIM: LEVEL_MEDIUM,
    CAT_ATOZ: LEVEL_HIGH,
    CAT_CASE: LEVEL_HIGH,
    CAT_EMOTION: LEVEL_LOW,
}


def batch_chunk_count(n: int) -> int:
    """批量语义判定会发几次请求（0 条 ⇒ 0 次）。"""
    n = max(0, int(n))
    return 0 if n == 0 else (n + RISK_SCAN_BATCH_CHUNK - 1) // RISK_SCAN_BATCH_CHUNK


def _batch_max_tokens(n: int) -> int:
    """一包 n 条的输出上限。

    ★ 逐条版 600 就够（回一条）；批量版要回 n 条 ⇒ 必须随 n 放大，
      否则输出被截断、JSON 解析失败、整包判 unknown（第 300 轮实测踩过）。
    """
    return max(_BATCH_MAX_TOKENS_FLOOR, min(_BATCH_MAX_TOKENS_CEIL, 80 * n + 260))


def _batch_clean(note: str = "批量语义判定：无风险") -> ScanResult:
    """模型**明确**判无风险 ⇒ `clean`（不需要人补判）。"""
    return ScanResult(channel="llm", decision=DECISION_CLEAN, note=note)


def _batch_unknown(note: str) -> ScanResult:
    """模型拿不准 / 输出读不出来 ⇒ `unknown`（**不是** `clean`）。

    ★ `note` 两处都写（块级 + 命中项级）：前端在命中项没有证据时显示 `h.note`，
      只写一处会让「拿不准的原因」在某些渲染分支里消失 —— 与逐条版
      `scan_llm` 的 unknown 出口保持一致。
    """
    res = ScanResult(channel="llm", note=note)
    res.hits.append(RiskHit(category=CAT_EMOTION, level=LEVEL_UNKNOWN,
                            evidence=[], channel="llm", note=note))
    return _decide(res)


def _parse_batch_value(value: object, text: str) -> ScanResult:
    """把批量输出里的**一个值**解析成 `ScanResult`。

    值的三种形态（协议见 `RISK_SCAN_BATCH_SYSTEM_PROMPT`）：

        `""`                 ⇒ clean（模型明确判无风险）
        `"?"`                ⇒ unknown（模型拿不准 —— 与 clean 方向**相反**）
        `"r2:high|原文片段"`  ⇒ 命中；`|` 后面是必须能回到原文的证据

    ★ 三态不可压两态：只回「序号 → 类别码」时 `""` 与 `"?"` 都是空串，合并
      就等于把「算法不敢定」静默洗白成「判了干净」——本仓最忌讳的一类静默退化。
    """
    raw = str("" if value is None else value).strip()
    if raw == "":
        return _batch_clean()
    head, _, raw_ev = raw.partition("|")
    head = head.strip()
    if head in _BATCH_UNKNOWN_MARKS:
        return _batch_unknown("批量语义判定：拿不准")
    if not head:
        # 有证据片段却没有类别码 ⇒ 与空串同解（模型没报出任何类别）。
        return _batch_clean()

    ev_list: list[str] = []
    frag = raw_ev.strip()
    if frag:
        # 证据必须能回到原文（★ 防「LLM 编证据」，与逐条版同一条铁律）
        ev_list = ([frag] if _is_grounded(frag, text)
                   else [f"<未落地|原文中找不到该片段> {frag[:80]}"])

    res = ScanResult(channel="llm")
    missing_level: list[str] = []
    for token in head.split(","):
        cat, _, lv = token.strip().lower().partition(":")
        cat, lv = cat.strip(), lv.strip()
        if cat not in CATEGORY_LABELS or any(h.category == cat for h in res.hits):
            continue
        if lv not in _LEVEL_ORDER:
            # ★ 等级缺失/非法 ⇒ 按类别默认，并把这件事写进 note（不静默改写口径）
            lv = _DEFAULT_LEVEL_BY_CATEGORY.get(cat, LEVEL_UNKNOWN)
            missing_level.append(cat)
        res.hits.append(RiskHit(category=cat, level=lv, evidence=list(ev_list),
                                channel="llm", note="批量语义判定命中"))
    if not res.hits:
        return _batch_unknown(f"批量输出的值无法解析（{raw[:60]}）")
    res.note = "批量语义判定命中 " + ",".join(h.category for h in res.hits)
    if missing_level:
        res.note += f"｜等级缺失按类别默认：{','.join(sorted(set(missing_level)))}"
    return _decide(res)


def _value_from_verbose_item(it: dict) -> Optional[str]:
    """把「逐条版那种对象」压成批量协议的值。

    ★ 为什么值得兼容：模型见过逐条版提示词就会回 `{"categories": [...]}`。
      不兼容的话整包判 unknown —— 那会把「格式不合我意」伪装成「模型判不出来」，
      归因方向从「协议没对齐」错成「模型不可用」。
    """
    cats = it.get("categories")
    if not isinstance(cats, list):
        return None
    lv = str(it.get("level") or "").strip().lower()
    if not cats:
        return _BATCH_UNKNOWN_MARKS[0] if lv == LEVEL_UNKNOWN else ""
    codes = [
        f"{str(c).strip().lower()}:{lv}" if lv else str(c).strip().lower()
        for c in cats
    ]
    frag = ""
    ev = it.get("evidence")
    if isinstance(ev, dict):
        for c in cats:
            frag = str(ev.get(str(c)) or "").strip()
            if frag:
                break
    elif isinstance(ev, list) and ev:
        frag = str(ev[0]).strip()
    body = ",".join(codes)
    return f"{body}|{frag}" if frag else body


def _batch_mapping_from_list(items: list) -> dict:
    """把 `[{"n": 1, "value": ...}]` 形态的返回转成「序号 → 值」。"""
    out: dict = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        n = it.get("n", it.get("index", it.get("id")))
        if n is None:
            continue
        val = it.get("value", it.get("result"))
        if val is None:
            val = _value_from_verbose_item(it)
        if val is None:
            continue
        out[str(n).strip()] = val
    return out


def _extract_batch_mapping(data: object) -> Optional[dict]:
    """从批量输出里取出「序号 → 值」的映射。

    ★ 兼容四种形态（模型不总是按要求回）：裸映射 / `{"items": {...}}` 包裹 /
      列表（`n` + `value`）/ 列表（逐条版对象）。
      只认一种就会把「格式不同」记成「判不出来」，归因方向错。
    """
    if isinstance(data, dict):
        if data.get("__llm_parse_failed__"):
            return None
        for key in ("items", "results", "data", "output"):
            inner = data.get(key)
            if isinstance(inner, dict) and inner:
                return {str(k).strip(): v for k, v in inner.items()}
            if isinstance(inner, list) and inner:
                got = _batch_mapping_from_list(inner)
                if got:
                    return got
        # 裸映射：键里至少得有一个序号（否则是逐条版对象，不是批量输出）
        if any(str(k).strip().isdigit() for k in data):
            return {str(k).strip(): v for k, v in data.items()}
        return None
    if isinstance(data, list):
        return _batch_mapping_from_list(data) or None
    return None


async def _scan_llm_batch_chunk(part: list[str], llm) -> list[ScanResult]:  # noqa: ANN001
    """判一包。★ **不抛异常**：失败整包判 unknown，不让一颗坏掉整批。"""
    payload = json.dumps(
        [{"n": i + 1, "text": t} for i, t in enumerate(part)], ensure_ascii=False,
    )
    try:
        data = await llm.structured_chat(
            user_message=payload,
            system_prompt=RISK_SCAN_BATCH_SYSTEM_PROMPT,
            output_format="json",
            # ★ max_tokens 必须**逐次**传：`get_llm()` 按模型名缓存单例，
            #   建实例之后再传参数是无效的（第 300 轮实测踩过）。
            max_tokens=_batch_max_tokens(len(part)),
        )
    except Exception as e:  # noqa: BLE001
        return [_batch_unknown(f"LLM 调用失败: {type(e).__name__}") for _ in part]

    mapping = _extract_batch_mapping(data)
    if mapping is None:
        return [_batch_unknown("批量输出无法解析成「序号 → 判定」的映射") for _ in part]

    out: list[ScanResult] = []
    for i, text in enumerate(part):
        key = str(i + 1)
        if key not in mapping:
            # ★ 缺项**不是 clean**：模型漏回一条，我们不知道它是漏了还是判无风险。
            out.append(_batch_unknown("批量输出缺这一条 ⇒ 不猜（fail-closed）"))
        else:
            out.append(_parse_batch_value(mapping[key], text))
    return out


async def scan_llm_batch(texts: Iterable[str], llm=None) -> list[ScanResult]:  # noqa: ANN001
    """一次判 N 条 —— 生产路径的语义通道。

    ★ 契约：**返回与输入等长、同序**的 `list[ScanResult]`，**任何**情况下都不少一条
      （缺项由内部 fail-closed 成 `unknown`）。调用方可以直接 `zip(inputs, out)`
      回填，不必自己处理缺项 —— 否则「缺项怎么办」会在调用方长出第二份实现。

    ★ 与 `scan_llm` 的关系：判据同源（同一套 r1~r5 口径），输出协议不同。
      实测 20 条：43.4 s（逐条串行）→ 约 2 s（浅层过滤 + 本节）。

    ★ 为什么并发发包：串行发就把「拆包换失败半径」的代价变成「多付几倍固定开销」，
      而那正是这一轮要消掉的东西。并发面上限由 `RISK_SCAN_BATCH_CHUNK` 与调用方
      的条数上限共同决定（deep 上限 20 ⇒ 最多 2 包）。
    """
    items = [str(t or "") for t in texts]
    if not items:
        return []
    if llm is None:
        from ai_infra.llm import get_llm
        llm = get_llm(model="qwen-plus", temperature=0.0)
    parts = [
        items[i:i + RISK_SCAN_BATCH_CHUNK]
        for i in range(0, len(items), RISK_SCAN_BATCH_CHUNK)
    ]
    # ★ 不用 `return_exceptions=True`：`_scan_llm_batch_chunk` 自己吞掉所有
    #   `Exception`，所以这里如果还有异常冒出来，只可能是 `CancelledError` ——
    #   那必须**继续往上抛**（吞掉取消 = 请求已经断了、模型还在跑、还要计费）。
    done = await asyncio.gather(*(_scan_llm_batch_chunk(p, llm) for p in parts))
    out: list[ScanResult] = []
    for chunk in done:
        out.extend(chunk)
    return out


# ============================================================ 融合

def fuse(results: Iterable[ScanResult]) -> ScanResult:
    """并列取证融合：并集；同类别冲突时取**等级高者**，两侧证据都留。

    ★ 为什么不是「规则优先、LLM 兜底」：本仓踩过「关键词短路早于语义」的坑
      （点名技能永不生效）。这里两条通道互相独立，规则命中**不阻止** LLM 判定。

    ★★ 为什么 `naive` 通道**被排除**在融合之外（拒绝列表，不是靠调用方自觉）：
      融合是并集 ⇒ **一条坏通道会污染好通道**。第 299 轮实测：库里那条 5 星好评
      「Exactly as described, arrived early, no complaints at all」被朴素关键词
      判成「开 case 投诉 / high」—— 并集之后 LLM 的正确判断被盖掉，最终报警里
      混进一条五星好评。朴素通道的定位就是**反面基线**（用来说明「关键词风控」
      为什么不可行），它不是可用通道，绝不能进并集。
    """
    results = [r for r in results if r.channel != "naive"]
    merged = ScanResult(channel="fuse")
    by_cat: dict[str, RiskHit] = {}
    for r in results:
        for h in r.hits:
            if h.level == LEVEL_UNKNOWN:
                continue
            prev = by_cat.get(h.category)
            if prev is None:
                by_cat[h.category] = RiskHit(
                    category=h.category, level=h.level,
                    evidence=list(h.evidence), channel="fuse",
                    note=f"[{h.channel}] {h.note}".strip(),
                )
                continue
            prev.evidence = list(dict.fromkeys(prev.evidence + h.evidence))
            if _LEVEL_ORDER.get(h.level, 0) > _LEVEL_ORDER.get(prev.level, 0):
                prev.level = h.level
                prev.note = (f"[{h.channel}] {h.note}（覆盖较低等级判定）").strip()
            else:
                prev.note = f"{prev.note} | [{h.channel}] {h.note}".strip()
    # 保持稳定顺序：四类在前（按定义顺序），r5 最后
    for cat in RISK_CATEGORIES + (CAT_EMOTION,):
        if cat in by_cat:
            merged.hits.append(by_cat[cat])
    # ★★ 守卫必须是 `risk_categories`，不能是 `merged.hits`：
    #   `fuse` 只丢掉 level=unknown 的 hit，**r5 会留下来** —— 用 hits 非空
    #   当守卫就等于「只要有人喊过一声就判 risk」，r5-only 的评价会被钉成
    #   risk（`_decide` 修好也救不回来，因为短路发生在调用之前）。
    if merged.risk_categories:
        return _decide(merged)
    # ★ 无**四类**命中时（含只命中 r5 的情形），定论要看各支的原始结论：
    #   只要有一支「不敢定」，融合结果就是 unknown（而不是 clean）——
    #   否则「拿不准」会被融合静默洗白。
    #   注意这里读的是**各支自己的 decision**（`results` 已剔除 naive 通道），
    #   所以「规则说高情绪 + LLM 说拿不准」⇒ unknown，
    #   而「规则说高情绪 + LLM 明确判无风险」⇒ clean。r5 本身不构成定论。
    merged.decision = (DECISION_UNKNOWN
                       if any(r.decision == DECISION_UNKNOWN for r in results)
                       else DECISION_CLEAN)
    return merged


# ============================================================ 门面

def scan_text(text: str, channel: str = "rule") -> ScanResult:
    """同步门面：只用规则/朴素通道（供离线盘点与前端即时用，零成本）。"""
    if channel == "naive":
        return scan_naive(text)
    return scan_rules(text)


# ============================================================ 已退役：`scan_full`
#
# ★ 第 300 轮删掉的原入口。它做的事（naive + rule + **逐条** LLM + fuse）在
#   `service.scan_reviews_risk` 的 deep 分支里已被**分层替换**：
#   规则命中四类的条目不再送语义，其余打包成一次批量调用。
#   ⇒ 留着它就是一个没人调用的「第二份语义入口」，而本仓铁律是收唯一真源：
#     两份实现里至少有一份永远测不到。
#
# ★ 需要「一条文本的完整三通道判定」时请**显式组合**，不要再造一个门面：
#
#     fused = fuse([scan_naive(t), scan_rules(t), await scan_llm(t, llm=llm)])
#

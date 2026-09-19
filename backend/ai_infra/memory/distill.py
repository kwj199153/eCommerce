"""长期记忆的**蒸馏规则**（第 149 轮 C2-1）。

三件事，全部是纯函数：

  1. `converge()` —— **收拢**：归一化 → 去重 → 分节配额 → 全局上限。
     每晚跑一次，也在用户提交后立刻跑一次。
  2. `validate_entries()` —— 提交前校验，把问题**报给用户**（HTTP 400），
     而不是静默砍掉一段。
  3. `extract_candidates()` —— 从对话里抽候选事实。LLM 通过**注入**进来
     （`llm_call` 参数），本模块不 import 任何 LLM SDK
     ⇒ 可测、可替换、可在没有网络的环境里跑门禁。

★★ 「蒸馏」在这里是**两档**，不要混为一谈
-----------------------------------------
· `converge` 是**确定性**的：同样的输入必然产出同样的输出，没有任何模型参与。
  它负责的是「重复的合并、超量的裁掉」—— 这是**账本**层面的整理。

· `extract_candidates` 是**概率性**的：它从对话里猜「哪些话值得长期记住」。
  它可能猜错、可能什么都猜不出来 —— 所以它的产物一律标 `source=distill`
  （权重最低），在未来被挤掉时**最先牺牲**（见 `limits.SOURCE_WEIGHTS`）。

分档的意义在于**失败时的表现不同**：
  · `converge` 失败是 bug（它没有外部依赖，失败只可能是代码错）；
  · `extract_candidates` 失败是**常态**（模型返回不可解析、没有 API key、
    对话里确实没有新东西）。

★ 后者因此绝不能"失败就返回空列表"：空列表的表达力与"今晚确实没什么新东西"
  完全重合，调用方**无法区分失败与无事可做** —— 那就是"假成功"的温床，
  也正是 r141 点名要修的那个毛病（页面承诺「每晚自动整理」，实际什么都没发生）。
  ⇒ 抽不出来就抛 `DistillError`，由调用方记一条**显式失败**的学习记录。
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import replace
from typing import Awaitable, Callable, List, Optional, Sequence

from .entry import (
    MemoryEntry,
    dedup_key,
    group_by_section,
    match_section,
    normalize_text,
    truncate_text,
)
from .limits import (
    ALL_SECTIONS,
    DEFAULT_SECTION_QUOTA,
    MAX_CANDIDATES_PER_RUN,
    MAX_DISTILL_MESSAGES,
    MAX_DISTILL_TRANSCRIPT_CHARS,
    MAX_ENTRY_CHARS,
    MAX_ENTRIES,
    MAX_LOG_CHARS,
    MAX_LOG_SAMPLE_CHARS,
    MAX_LOG_SAMPLE_ITEMS,
    MIN_DISTILL_LINE_CHARS,
    SECTION_OTHER,
    SECTION_QUOTA,
    SOURCE_DISTILL,
    TRUNCATION_MARK,
    ordered_sections,
)

logger = logging.getLogger(__name__)


class DistillError(RuntimeError):
    """蒸馏（抽取）失败。

    ★ 刻意用异常而不是"返回空列表"——理由见模块 docstring 最后一段。
    """


# ============================================================================
# 第一档：确定性收拢
# ============================================================================


def converge(
    entries: Sequence[MemoryEntry],
    *,
    max_entries: int = MAX_ENTRIES,
    quota: Optional[dict] = None,
) -> List[MemoryEntry]:
    """把一组条目收敛成规范形态。

    六步（顺序即依赖关系，不能调换）：
      1. 归一化内容 + 丢弃空条目；
      2. 按 `dedup_key` 去重，同 key 保留**权重最高**的来源；
      3. 单条超长**截断**；
      4. 分节**配额**裁剪（按权重，不按时间）；
      5. 全局**条数**上限裁剪（分节轮转，保证小分节不被挤光）；
      6. 按「分节规范顺序 + 组内原始顺序」输出。

    ★★ 幂等：`converge(converge(x)) == converge(x)`（逐字段相等）。

    这不是"顺便成立"的性质，而是每晚任务的**前提**：任务会因为
    `task_acks_late=True` 被重投递，也可能被手动点两次"立即整理"。
    若第二次跑还会继续删东西，用户看到的就是"我点一次它少几条"——
    而他无法判断哪一次的结果才是对的。
    保证幂等的两个关键：
      · 第 3 步截断是**收敛**的（截过的再截不变）；
      · 第 4/5 步的排序键只依赖**组内相对顺序**，不依赖绝对下标 ——
        所以"再跑一次"必然选出同一集合。

    ★ 第 3 步为什么必须排在配额之前：否则一条 10 万字的条目会先占掉一格
      配额，再被截成 500 字 —— 白挤掉一条本来能留下来的正常条目。

    ★ 第 5 步为什么是**轮转**而不是"取权重最高的 N 条"：后者在极端情况下
      会把整个「关注重点」分节删空（只要「运营偏好」那边全是手写条目），
      而用户看到的是"我明明写过的关注重点整块没了"。轮转保证
      **每个分节至少保住它在重要性排序里的头部**。
    """
    caps = dict(SECTION_QUOTA if quota is None else quota)

    # --- 1) 归一化 + 丢弃空条目 ---
    cleaned: List[MemoryEntry] = []
    for raw in entries or ():
        e = MemoryEntry.from_dict(raw)
        content = normalize_text(e.content)
        if not content:
            continue
        cleaned.append(replace(e, content=content))

    # --- 2) 去重 ---
    merged: dict = {}
    order: List[str] = []
    for e in cleaned:
        k = e.key
        prev = merged.get(k)
        if prev is None:
            merged[k] = e
            order.append(k)
        elif e.weight > prev.weight:
            # 保留**首次出现的位置**（顺序稳定），但把来源换成权重更高的那个：
            # 同一条事实既有用户手写、又有 AI 归纳 ⇒ 按"用户写的"算，
            # 于是它在第 4/5 步不会被当成低价值条目牺牲掉。
            merged[k] = replace(prev, source=e.source)
    uniq = [merged[k] for k in order]

    # --- 3) 单条超长截断 ---
    # ★ 这里**静默截断**（区别于 `validate_entries` 的"报错给用户"）：
    #   converge 是自动整理的一环，超长只可能来自历史遗留数据或模型输出，
    #   两者都不可能"停下来问用户一句"。而用户能在界面上看到结果。
    sized = [
        (
            replace(e, content=truncate_text(e.content, MAX_ENTRY_CHARS))
            if len(e.content) > MAX_ENTRY_CHARS
            else e
        )
        for e in uniq
    ]

    # --- 4) 分节配额 ---
    grouped: dict = {}
    for idx, e in enumerate(sized):
        grouped.setdefault(e.section, []).append((idx, e))

    def _rank(pair):
        idx, e = pair
        # 权重高的优先；同权重时"较新的"优先。
        # ★ idx 越大 = 越靠后 = 越新 —— 这条约定由**调用方**保证
        #   （`service` 按 `updated_at` 升序读出来传进来）。
        return (-e.weight, -idx)

    capped: dict = {}
    for section, pairs in grouped.items():
        cap = caps.get(section, DEFAULT_SECTION_QUOTA)
        capped[section] = sorted(pairs, key=_rank)[: max(0, int(cap))]

    # --- 5) 全局上限：分节轮转 ---
    section_order = ordered_sections(capped.keys())
    chosen: list = []
    round_no = 0
    while len(chosen) < max(0, int(max_entries)):
        progressed = False
        for section in section_order:
            bucket = capped[section]
            if round_no < len(bucket):
                chosen.append(bucket[round_no])
                progressed = True
                if len(chosen) >= max_entries:
                    break
        if not progressed:
            break
        round_no += 1

    # --- 6) 稳定输出：分节规范顺序 + 组内原始顺序 ---
    ranks = {
        s: i for i, s in enumerate(ordered_sections([p[1].section for p in chosen]))
    }
    chosen.sort(key=lambda p: (ranks.get(p[1].section, len(ranks)), p[0]))
    return [p[1] for p in chosen]


def validate_entries(
    entries: Sequence[MemoryEntry],
    *,
    max_entries: int = MAX_ENTRIES,
    quota: Optional[dict] = None,
) -> List[str]:
    """提交前校验，返回**人话问题清单**（空列表 = 通过）。

    ★ 为什么要有它，而不是直接 `converge` 一下了事：
      `converge` 会**静默**去掉重复、截断超长、裁掉超量。这三件事对
      "系统自动整理"是对的，对"用户点保存"是**错的** ——
      用户手写的东西被悄悄改掉是不可接受的。所以写入路径先过这里：
      有问题就 400 并把问题原样回给他，让他自己决定删哪条。

    ★ 刻意**不**把"重复条目"算作问题：重复是**可以自动合并**的
      （`converge` 处理，合并后内容不变），报错只会让用户做一件
      系统完全能自己做的事。
    """
    caps = dict(SECTION_QUOTA if quota is None else quota)
    problems: List[str] = []
    items = [MemoryEntry.from_dict(x) for x in (entries or ())]

    if len(items) > max_entries:
        problems.append(
            f"记忆条目共 {len(items)} 条，超过上限 {max_entries} 条，请先删除或合并"
        )

    counts: Counter = Counter()
    for i, e in enumerate(items, 1):
        content = normalize_text(e.content)
        if not content:
            problems.append(f"第 {i} 条内容为空")
            continue
        if len(content) > MAX_ENTRY_CHARS:
            problems.append(
                f"第 {i} 条 {len(content)} 字，超过单条上限 {MAX_ENTRY_CHARS} 字："
                f"{truncate_text(content, 24)}"
            )
        counts[e.section] += 1

    for section, n in counts.items():
        cap = caps.get(section, DEFAULT_SECTION_QUOTA)
        if n > cap:
            problems.append(f"「{section}」共 {n} 条，超过该分节上限 {cap} 条")

    return problems


def diff_summary(
    before: Sequence[MemoryEntry],
    after: Sequence[MemoryEntry],
    *,
    sample: int = MAX_LOG_SAMPLE_ITEMS,
) -> dict:
    """比较整理前后的条目集合，产出可直接进时间线的摘要。

    ★ 数的是**去重后**的条数（`before` / `after` 都是集合大小）：
      否则"整理前 65 条（其中 5 条重复）→ 整理后 60 条"会被读成
      "删了 5 条"，而实际上一条内容都没丢。
    """
    b = {MemoryEntry.from_dict(x).key: MemoryEntry.from_dict(x) for x in (before or ())}
    a = {MemoryEntry.from_dict(x).key: MemoryEntry.from_dict(x) for x in (after or ())}
    added = [a[k] for k in a if k not in b]
    removed = [b[k] for k in b if k not in a]
    return {
        "before": len(b),
        "after": len(a),
        "added": len(added),
        "removed": len(removed),
        "kept": len(a) - len(added),
        "added_samples": [
            truncate_text(e.content, MAX_LOG_SAMPLE_CHARS) for e in added[:sample]
        ],
        "removed_samples": [
            truncate_text(e.content, MAX_LOG_SAMPLE_CHARS) for e in removed[:sample]
        ],
    }


def format_log_content(summary: dict, *, action: str = "自动整理") -> str:
    """把 `diff_summary` 的结果写成人话（进学习时间线）。

    ★ 无论有没有变化都返回一句话（"本次没有变化"），**不返回空串**：
      时间线的价值一部分就在于"昨晚它跑过了"。一条空记录看不出
      "跑过但没事"与"压根没跑"的区别。
    """
    before = int(summary.get("before") or 0)
    after = int(summary.get("after") or 0)
    added = int(summary.get("added") or 0)
    removed = int(summary.get("removed") or 0)

    if not added and not removed:
        body = f"共 {after} 条，本次没有变化"
    else:
        bits = []
        if added:
            bits.append(f"新增 {added} 条")
        if removed:
            bits.append(f"移除 {removed} 条")
        body = f"{before} → {after} 条（{'、'.join(bits)}）"
        samples = list(summary.get("added_samples") or []) + list(
            summary.get("removed_samples") or []
        )
        if samples:
            body += "：" + " / ".join(samples)

    return truncate_text(f"{action}：{body}", MAX_LOG_CHARS)


# ============================================================================
# 第二档：概率性抽取（LLM 注入）
# ============================================================================

# ★★ 本层**不持有提示词** —— `instructions` 由调用方传入、且必填。
#
#   这是分层裁决，不是「还没写」：提示词就是**业务语义本身**。它决定
#   「什么值得记住」（哪些是偏好、哪些是一次性任务、拿什么当例子），
#   而这些判断随产品走。把它放在 ai_infra 里会让
#   `tests/test_infra_layering.py::test_ai_infra_string_literals_have_no_business_content`
#   失守 —— 第 151 轮实测咬中过：提示词里的
#   「竞品价格 / 某个 ASIN 的参数 / 某天的销量 / 广告 ACOS」。
#
#   ⇒ 本模块只管**机制**：转录渲染、prompt 拼装、JSON 抠取、去重、上限。
#     提示词住 `modules/memory/prompts.py`。
#   ⇒ 那是**唯一真源**：本层**不得**再有一个「通用默认提示词」。留一个默认值
#     等于同一件事有两份写法 —— 「通用版」与「业务版」必然漂移，而漂移的表现是
#     「换了个产品，整理出来的记忆开始不像这个产品该记的东西」，不报错。
#
#   ★ 于是签名从「可选」变成「**必填、无默认值**」：这样「忘了传」是
#     `TypeError`（在跑之前就炸），而不是「悄悄用了一个中性但更差的提示词」。
#     这与本仓「签名即门禁」的既有裁决同源。

def _render_messages(messages: Sequence) -> str:
    """把对话消息渲染成有界的转录文本。

    三重界定（缺一不可）：
      · 条数 ≤ `MAX_DISTILL_MESSAGES`（超量时**保留最近的**）；
      · 总字符 ≤ `MAX_DISTILL_TRANSCRIPT_CHARS`；
      · 单条过长时**截断后仍收进来**（见下）。

    夜间任务面对的是"某个用户一整天甚至一个月的对话"，不设界的话
    提示词长度完全由用户行为决定 —— 那是**用户可控的成本**。

    ★★ 两处最容易写错的细节，都在这里踩过（均有反向注入用例钉住）：

    1. **条数超限保留"最近"的，不是最早的**。夜里整理面向"他最近在想什么"，
       `MAX_DISTILL_MESSAGES` 之外的部分本来也只会让提示词更长更糊。

    2. **单条就超预算时不能 `break`，要截断后收进来**。
       写成 `break` 的后果极其隐蔽：对话里只要有一条长消息
       （AI 的长回答动辄几千字），`lines` 就是空的 ⇒ 转录是空串 ⇒
       `build_extract_prompt` 返回空串 ⇒ 抽取直接返回 `[]` ⇒
       调用方记一条"本次无变化"。
       整晚的整理**什么都没做**，而所有日志看起来都很正常 ——
       这正是本项目反复出现的那类"门禁在、功能没了"的静默失效。
       ⇒ 只要还剩 `MIN_DISTILL_LINE_CHARS` 的位置，就截断收进来。
    """
    items = list(messages or ())
    if len(items) > MAX_DISTILL_MESSAGES:
        items = items[-MAX_DISTILL_MESSAGES:]

    lines: List[str] = []
    used = 0
    for raw in items:
        if isinstance(raw, dict):
            role = str(raw.get("role") or "user")
            content = raw.get("content")
        else:
            role = getattr(raw, "role", None) or "user"
            content = getattr(raw, "content", None)
            if content is None and isinstance(raw, (list, tuple)) and len(raw) == 2:
                role, content = str(raw[0]), raw[1]
        text = normalize_text(str(content or ""))
        if not text:
            continue
        line = f"[{role}] {text}"
        room = MAX_DISTILL_TRANSCRIPT_CHARS - used
        if len(line) + 1 <= room:
            lines.append(line)
            used += len(line) + 1
            continue
        if room >= MIN_DISTILL_LINE_CHARS:
            lines.append(truncate_text(line, room - 1))
            used = MAX_DISTILL_TRANSCRIPT_CHARS
        break
    return "\n".join(lines)


def build_extract_prompt(
    messages: Sequence,
    *,
    instructions: str,
    existing: Optional[Sequence[MemoryEntry]] = None,
) -> str:
    """组装抽取提示词。

    `instructions` 由调用方传入（见本文件上方「本层不持有提示词」）——
    必填、**不设默认值**：给默认值就等于本层也有一份提示词。
    没有可用对话时返回**空串**（调用方据此跳过）。
    """
    transcript = _render_messages(messages)
    if not transcript:
        return ""

    parts = [instructions]
    if existing:
        known = "\n".join(f"- {normalize_text(e.content)}" for e in existing if normalize_text(e.content))
        if known:
            parts.append(f"【已有记忆】（不要重复提取）\n{known}")
    parts.append(f"【对话片段】\n{transcript}")
    return "\n\n".join(parts)


def _extract_json_array(text: str) -> Optional[str]:
    """从模型输出里抠出 JSON 数组（容忍前后有解释文字或代码围栏）。

    ★ 用"第一个 `[` 到最后一个 `]`"而不是正则匹配：模型的输出里
      可能同时出现方括号（例如提示词要求的分节名列表被它复述了一遍），
      取最外层一对是最稳的。
    """
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def parse_candidates(
    raw: str,
    *,
    max_candidates: int = MAX_CANDIDATES_PER_RUN,
) -> List[MemoryEntry]:
    """解析模型输出为候选条目。**解析失败抛 `DistillError`**（不返回空列表）。"""
    blob = _extract_json_array(str(raw or ""))
    if blob is None:
        raise DistillError(
            f"模型输出里找不到 JSON 数组，原始输出：{truncate_text(str(raw or ''), 200)}"
        )
    try:
        data = json.loads(blob)
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都是同一件事：输出不合规
        raise DistillError(
            f"模型输出的 JSON 无法解析（{type(exc).__name__}: {exc}），"
            f"原文：{truncate_text(blob, 200)}"
        ) from exc
    if not isinstance(data, list):
        raise DistillError(f"模型输出的 JSON 顶层不是数组，而是 {type(data).__name__}")

    out: List[MemoryEntry] = []
    seen: set = set()
    for item in data:
        e = MemoryEntry.from_dict(item)
        content = normalize_text(e.content)
        if not content:
            continue
        section = match_section(e.section)
        if section not in ALL_SECTIONS:
            # ★ 模型偶尔会自创分节（"客户画像"、"其他偏好"这类）。
            #   放它进来，界面上就会长出一个用户从没见过的分组，
            #   而且它会**每次都不一样**（模型每次自创的措辞不同）⇒
            #   分节列表不断膨胀、每个野分节各占一份配额。
            #   ⇒ 一律收敛到「其他」（那是显式为"归不了类"准备的位置）。
            section = SECTION_OTHER
        key = dedup_key(content)
        if key in seen:
            continue
        seen.add(key)
        out.append(MemoryEntry(content=content, section=section, source=SOURCE_DISTILL))
        if len(out) >= max_candidates:
            break
    return out


async def extract_candidates(
    messages: Sequence,
    *,
    llm_call: Callable[[str], Awaitable[str]],
    instructions: str,
    existing: Optional[Sequence[MemoryEntry]] = None,
    max_candidates: int = MAX_CANDIDATES_PER_RUN,
) -> List[MemoryEntry]:
    """从对话里抽候选事实。

    `llm_call` 是**注入**的：一个 `(prompt) -> awaitable[str]` 的可调用对象。

    ★ 为什么不让本模块自己 `get_llm()`：那会把"机制"和"某个具体厂商的
      客户端"绑死 —— 于是跑门禁必须先有 API key，而没有 key 的环境
      只能`skip`，最终这个模块的核心逻辑**永远没被验证过**。
      注入之后，测试里传一个固定返回的假函数即可，且能精确构造
      "模型返回不合规"这类真实故障。
    """
    prompt = build_extract_prompt(messages, instructions=instructions, existing=existing)
    if not prompt:
        return []
    raw = await llm_call(prompt)
    return parse_candidates(raw, max_candidates=max_candidates)


__all__ = [
    "DistillError",
    "build_extract_prompt",
    "converge",
    "diff_summary",
    "extract_candidates",
    "format_log_content",
    "parse_candidates",
    "validate_entries",
]

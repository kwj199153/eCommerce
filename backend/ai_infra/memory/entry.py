"""长期记忆的**数据形态层**：条目对象 + markdown 读写 + prompt 注入块。

三个纯函数家族，全部零 IO：
  · **归一化/去重键** —— `normalize_text()` / `dedup_key()`
  · **markdown 读写** —— `parse_markdown()` / `render_markdown()`
  · **注入块渲染** —— `render_prompt_block()`

★ 为什么 markdown 是**唯一对外形态**
-------------------------------------
前端 `MemoryEvolution.vue` 的用户体验是「一整块可编辑文本」（像 Obsidian 的
一个笔记页），不是"一条条卡片的表单"。若把存储形态做成条目列表、却在 API 上
只暴露 JSON 数组，前端就得自己拼/拆 markdown —— **第二个解析实现**，
而两份实现迟早对不上（榜单上第 138 轮的 `X-Shop-ID` 就是同一个病）。
⇒ 约定：**markdown 是 I/O 形态，条目列表是内部形态**，转换只在本模块发生。

★★ `dedup_key` 的能力边界（不要把它的作用说大）
-----------------------------------------------
它做的是「**规范化后的精确匹配**」，不是语义去重：

    它能吃掉（归一化后同一串）：
        "- **语言**：中文交流"      ↦ 语言中文交流
        "语言: 中文交流"            ↦ 语言中文交流
        "语言 ： 中文交流。"        ↦ 语言中文交流
    它**吃不动**（归一化后不是同一串）：
        "偏好中文交流"  vs  "语言：中文交流"     ← 同一件事，两种说法

后者需要模型参与（见 `distill.extract_candidates`），而模型是**概率性**的：
把"去重"这个**确定性**职责交给它，等于让一个会猜错的组件去守一条必须
恒真的不变量。所以两件事分开做，各归各的失败模式。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Sequence

from .limits import (
    ALL_SECTIONS,
    MAX_ENTRY_CHARS,
    MAX_PROMPT_CHARS,
    SECTION_ALIASES,
    SECTION_OTHER,
    SOURCE_MANUAL,
    TRUNCATION_MARK,
    ordered_sections,
    source_weight,
)

# ============================================================================
# 归一化
# ============================================================================

#: markdown 标题行：`# 标题` / `## 标题 ##`
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s*(.*?)\s*#*\s*$")

#: 行首的列表符号：`- ` / `* ` / `+ ` / `• ` / `1. ` / `1) ` / `1、` / `(1)` / `（1）`
#:
#: ★ 刻意**只剥一层**（`count=1`）：一条条目里出现第二个 `-` 通常是内容本身
#:   （"改前 - 改后"这种写法），继续剥会把内容吃掉。
_BULLET_RE = re.compile(
    r"^\s*(?:"
    r"[-*+\u2022\u00b7\u25cf\u25cb\u25aa]"
    r"|\d{1,3}\s*[.)\u3001]"
    r"|\d{1,3}\s*\uff09"
    r"|\uff08\d{1,3}\uff09"
    r")\s*"
)

#: 引用符号 `> `
_QUOTE_RE = re.compile(r"^\s*>\s?")

#: 成对的强调标记。
#:
#: ★★ 只处理**成对**的 `**粗体**` / `__粗体__` / `` `代码` ``。
#:   绝不无差别删 `*` 与 `_`：本项目的记忆内容里真实存在
#:   `X-Shop-ID`（下划线是标识符的一部分）与 `ACOS*ROI`（星号是乘号）。
#:   无差别替换会把它们改成 `X-Shop-ID` 之外的东西 —— 而那是一条
#:   **静默的内容损坏**：删完之后再保存，用户原文就永久变了。
_EMPH_PATTERNS = (
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"__(.+?)__"),
    re.compile(r"`(.+?)`"),
)


def normalize_text(text: str) -> str:
    """把一条条目的**内容**收敛成规范形态。

    做四件事（顺序有意义）：
      1. 统一换行、全角空格 → 半角空格；
      2. 剥掉行首列表符号与引用符号；
      3. 去掉成对的强调标记（保留文字）；
      4. 空白压缩、去首尾。

    ★★ 归一化只做**结构**层面的事，绝不改**内容**。

      句末的 `。；;，,` 属于用户原文，**不在这里删**。
      「同一条事实写不写句号算不算两条」这个问题由 `dedup_key()` 回答 ——
      它在折叠时会去掉**所有**标点与空白。

      这样分工的好处：用户存进来的字原样还在，而去重依然能吃掉
      `语言：中文交流` 与 `语言: 中文交流。` 这类差异。
      反过来说，若在这里删标点，用户第一次保存就会发现自己写的句号全没了，
      而他**无法判断这是"系统整理"还是"内容丢了"** ——
      这正是"静默改写用户数据"最难看的一种形态。
    """
    t = str(text or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    t = _QUOTE_RE.sub("", t)
    t = _BULLET_RE.sub("", t, count=1)
    for pat in _EMPH_PATTERNS:
        t = pat.sub(r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fold_for_key(text: str) -> str:
    """把文本折成"只剩实义字符"的形态，用于去重键。

    比 `normalize_text` 更狠：NFKC（全角→半角、异体归一）+ casefold +
    去掉**所有**空白与标点。于是 `语言：中文交流` 与 `语言: 中文交流`
    折成同一串。

    ★ 为什么折得这么狠也不怕误合并：中文 + 英文字母数字的实义序列本来就
      没什么歧义余地。真正会被误合并的是"实义词相同但语序不同"的句子
      （"ACOS 25% 以内" vs "25% 以内 ACOS"），而那种情况连人也要想一想 ——
      它本来就不该由一条字符串规则来裁决。
    """
    t = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        ch for ch in t if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )


def dedup_key(text: str) -> str:
    """条目的稳定去重键（规范化 → 折叠 → sha1 前 16 位）。

    ★ 取 sha1 前 16 位而不是整串：键要进数据库唯一约束，越短索引越省。
      16 hex = 64 bit，在"单个用户的长期记忆"这个量级（上限 60 条）上，
      碰撞概率低到不必讨论；即便真撞了，后果是**两条被并成一条**，
      而不是数据错乱 —— 代价可接受。
    """
    return hashlib.sha1(_fold_for_key(normalize_text(text)).encode("utf-8")).hexdigest()[:16]


def truncate_text(text: str, limit: int) -> str:
    """按字符数截断，超长时补 `TRUNCATION_MARK`。"""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARK):
        return TRUNCATION_MARK[:limit]
    return text[: limit - len(TRUNCATION_MARK)].rstrip() + TRUNCATION_MARK


# ============================================================================
# 条目对象
# ============================================================================


@dataclass(frozen=True)
class MemoryEntry:
    """一条长期记忆。

    ★ `frozen=True` + `replace()` 而不是可变对象 `entry.section = x`：
      裁剪/去重/合并会大量派生新列表，可变对象让"谁改了它"变成
      跨函数的隐式副作用 —— 而本模块的所有函数都承诺**不改入参**。

    ★ `weight` 与 `key` 都是**派生属性**（由 `source` / `content` 算出），
      不是字段。存成字段就意味着"可以存一个与来源不一致的权重"，
      而那种不一致没有任何东西能发现。
    """

    content: str
    section: str = SECTION_OTHER
    source: str = SOURCE_MANUAL
    #: 数据库主键（机制层不认识它，原样透传）。
    id: Optional[str] = None
    #: 落库时的时间字符串（原样透传，只在展示时用）。
    updated_at: Optional[str] = None

    @property
    def key(self) -> str:
        """去重键（见 `dedup_key`）。"""
        return dedup_key(self.content)

    @property
    def weight(self) -> int:
        """重要性权重（见 `limits.source_weight`）。"""
        return source_weight(self.source)

    def as_dict(self) -> dict:
        """转成可直接 JSON 化的 dict（含派生字段，方便前端/日志直接用）。"""
        return {
            "id": self.id,
            "content": self.content,
            "section": self.section,
            "source": self.source,
            "key": self.key,
            "weight": self.weight,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw) -> "MemoryEntry":
        """从 dict / 字符串宽容地构造。

        ★ 宽容是**必要**的：调用方既可能是数据库行、也可能是模型返回的
          JSON、还可能是前端截图出来的旧结构。任何一种形状导致
          `KeyError` 都会让整次整理失败，而失败原因会显示成
          "记忆整理失败" —— 用户根本无从下手。
        """
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            return cls(content=raw)
        if not isinstance(raw, dict):
            return cls(content=str(raw or ""))
        content = raw.get("content")
        if content is None:
            content = raw.get("text") or raw.get("value") or ""
        return cls(
            content=str(content),
            section=str(raw.get("section") or SECTION_OTHER),
            source=str(raw.get("source") or SOURCE_MANUAL),
            id=raw.get("id"),
            updated_at=raw.get("updated_at"),
        )


# ============================================================================
# markdown 读写
# ============================================================================


def match_section(title: str) -> str:
    """把 markdown 标题映射成规范分节名。

    ★ 认不出来的标题**原样保留**（不丢结构、不塞进"其他"）：
      用户导入的文档如果有自己的一套标题，把它压成"其他"等于
      一次静默的结构破坏 —— 而且他下次打开会以为记忆被搞乱了。
    """
    raw = str(title or "").strip()
    if not raw:
        return SECTION_OTHER
    folded = _fold_for_key(raw)
    for alias, section in SECTION_ALIASES.items():
        if _fold_for_key(alias) == folded:
            return section
    return raw


def parse_markdown(
    text: str,
    *,
    source: str = SOURCE_MANUAL,
    default_section: str = SECTION_OTHER,
) -> List[MemoryEntry]:
    """把 markdown 文本拆成条目列表。

    规则（对两种真实写法都成立）：
      · `# 标题` 切换当前分节；
      · **列表行**各自成一条（`- ` / `1. ` / `（1）` …）；
      · **连续的非列表行**合成一条（"段落型"分节，例如「工作背景」原文
        就是两大段散文，而不是清单）；
      · 空行结束当前条目。

    ★ 刻意**不做**条数/长度裁剪：本函数的职责只是"形状"，上限由
      `distill.converge()` / `service` 的校验负责。若这里顺手裁掉，
      「用户导入 200 条」会变成"导入成功但只剩 60 条"——
      而他没有任何途径知道被丢了 140 条。
    """
    entries: List[MemoryEntry] = []
    section = default_section
    buf: List[str] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        joined = normalize_text(" ".join(buf))
        if joined:
            entries.append(MemoryEntry(content=joined, section=section, source=source))
        buf = []

    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in body.split("\n"):
        line = raw_line.rstrip()
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            section = match_section(heading.group(2))
            continue
        if not line.strip():
            flush()
            continue
        if _BULLET_RE.match(line):
            flush()
            buf.append(line)
            flush()
            continue
        buf.append(line)
    flush()
    return entries


def group_by_section(entries: Sequence[MemoryEntry]) -> dict:
    """按分节分组，**保持组内原始顺序**（dict 保序）。"""
    groups: dict = {}
    for e in entries or ():
        groups.setdefault(e.section, []).append(e)
    return groups


def render_markdown(entries: Sequence[MemoryEntry]) -> str:
    """条目列表 → markdown（`parse_markdown` 的逆）。

    ★ 返回值对空列表是**空串**，不是一段占位文案。
      前端需要展示的是"空状态"（`a-empty`），而占位文案一旦进了文本
      就会被 `parse_markdown` 读成**一条真实的记忆**，
      从此每次整理都要为它费一次去重、占一格配额。
    """
    items = [e for e in (entries or ()) if normalize_text(e.content)]
    if not items:
        return ""
    groups = group_by_section(items)
    lines: List[str] = []
    for section in ordered_sections(groups.keys()):
        lines.append(f"# {section}")
        lines.append("")
        for e in groups[section]:
            lines.append(f"- {e.content}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


#: 注入 system prompt 的块首说明。
PROMPT_HEADER = (
    "【长期记忆】以下是用户自己维护的画像与偏好，请据此调整回答的语气、"
    "格式与默认假设；不要复述本段，也不要把没写在这里的事当成他的偏好。"
)


def render_prompt_block(
    entries: Sequence[MemoryEntry],
    *,
    max_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """条目列表 → 注入 system prompt 的紧凑块（**硬上限** `max_chars`）。

    ★ 截断只发生在**整行边界**上：宁可少给两条，也不切半条。
      半条记忆在 prompt 里不是"信息少一点"，而是"给出了错误信息" ——
      例如「ACOS 控制在」后半截丢掉「25% 以内算健康，新品期容忍 40%以内」，
      模型会照着前半句自己编一个数字，而编出来的数字看起来完全正常。
    """
    items = [e for e in (entries or ()) if normalize_text(e.content)]
    if not items:
        return ""
    lines: List[str] = [PROMPT_HEADER]
    groups = group_by_section(items)
    for section in ordered_sections(groups.keys()):
        lines.append(f"[{section}]")
        for e in groups[section]:
            lines.append(f"- {e.content}")

    total = len(items)
    #: 给"已省略"提示预留的位置。
    reserve = 48
    kept: List[str] = []
    used = 0
    shown = 0
    for ln in lines:
        if used + len(ln) + 1 > max_chars - reserve:
            break
        kept.append(ln)
        used += len(ln) + 1
        if ln.startswith("- "):
            shown += 1

    if shown >= total and len(kept) == len(lines):
        return "\n".join(kept)

    # 去掉尾部「只有分节标题、一条条目都没进」的悬空头
    while len(kept) > 1 and kept[-1].startswith("[") and kept[-1].endswith("]"):
        kept.pop()
    if shown <= 0:
        # 连一条都放不下（max_chars 被人为调得极小）。**显式说明**而不是
        # 返回空串冒充"没有记忆"—— 后者会让排查方向整个跑偏。
        return f"【长期记忆】共 {total} 条，因注入上限（{max_chars} 字）过小而未能注入。"
    kept.append(f"（记忆过长，本次只注入前 {shown}/{total} 条）")
    return "\n".join(kept)


__all__ = [
    "MemoryEntry",
    "PROMPT_HEADER",
    "dedup_key",
    "group_by_section",
    "match_section",
    "normalize_text",
    "parse_markdown",
    "render_markdown",
    "render_prompt_block",
    "truncate_text",
]

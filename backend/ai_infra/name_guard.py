# -*- coding: utf-8 -*-
"""名字守卫 —— 「模型把**不该出现的名字**说出口」的通用去污染件（第 400 轮 · P2）

==============================================================================
★ 从哪来
==============================================================================
这份逻辑原先只活在 `modules/secretary/shop_context.py`（店铺名版），是为一个具体
事故写的（第 242 轮实测，不是推断）：

    system 里明明摆着「当前工作店铺：亚马逊1」，模型**仍然**写
    「当前店铺（虾皮1）」—— α 探针三组措辞全 BAD，β 的阳性对照证明事实段
    确实被读了。真因是：历史里那条**句式完整的错误自称**是一份现成的"示范"；
    γ 的 H 组更狠 —— 就算删掉自称片段，模型还会从**别处**（切店确认那条）
    把旧店名捞回来；只有 I 组（历史里完全不存在旧店名）才改口。
    ⇒ 污染源是**历史里任何位置的旧名字**，不是某一句话。

这个能力与"店铺"没有本质关系：**任何"当前只能有一个"的实体**（当前店铺、
当前 Agent、当前账号）切走之后，历史里的旧名字都是同一个形状的污染源。
⇒ 本轮把它上提成通用件，机构 3 个函数：

    order_names          名单规整（去短名 / 去重保序 / **长名优先**）
    strip_names          从一段文本里抹掉这些名字（可带业务侧的"整段删"正则）
    scrub_ai_messages    只改**模型自己说过的话**、返回新列表、不改原消息
    detect               只报"出现了哪些"（不改文本，给日志/诊断用）
    pick_foreign         从"全部可见"里挑出**除当前之外**的那些

==============================================================================
★ 三条不能动的判断（照搬时会丢，所以写在这儿）
==============================================================================

1. **不要碰 `HumanMessage`。** 老板原话里的旧名字是**正当引用**
   （「虾皮1 有多少产品」是历史事实），抹掉会破坏多轮语境。
   模型的"自称"才是把旧名字当成**当前**实体的那个污染源。

2. **返回新列表、不改原消息。** `state` / checkpoint 里的历史保持原样、可审计；
   本模块只作用在"这一轮发给模型的那一份"（同 `_sanitize_tool_call_pairing` 的立场）。
   ★ 名单为空时返回**同一个对象**：没绑实体 / 只有一家时零开销，
     也保证"没有实体时提示词与历史一个字都不许变"这条既有判据继续成立。

3. **短名字不参与抹除。** 单字名（如「1」）会把历史里所有 `1` 都抹掉 ——
   那是**大范围误伤**，比留下一处旧名字更糟。宁可不抹（`MIN_STRIPPABLE_NAME_LEN`）。

★ 为什么可以粗暴地做字符串处理：抹的对象是**权威名单里的名字**，不是自然语言
  理解。不需要分词、不需要猜"哪句在说它"—— 名单里有、文本里出现，就抹。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Pattern, Sequence, Tuple

from langchain_core.messages import AIMessage

__all__ = [
    "MIN_STRIPPABLE_NAME_LEN",
    "detect",
    "order_names",
    "pick_foreign",
    "scrub_ai_messages",
    "strip_names",
]

#: 短于该长度的名字一律不参与去污染。
#:
#: ★ 这是一个**产品判断**，不是实现细节：单字名（电商里的「1」号店）会让
#:   `text.replace("1", "")` 把整段历史里所有数字 1 都吃掉 ——
#:   为了消灭一处旧名字而制造出一段乱码，比不抹更糟。
MIN_STRIPPABLE_NAME_LEN = 2


def order_names(names: Optional[Iterable[Any]]) -> List[str]:
    """规整名单：去空白、丢短名、**去重但保序**、最后按长度**降序**。

    ★ 为什么最后要按长度降序：`虾皮1` 是 `虾皮10` 的**前缀**，
      先替换短名会把 `虾皮10` 剁成 `0`。
      （同族坑见 `shop_tools._switch_shop` 的「全字匹配优先」注释：
       那是"匹配"，这里是"替换"，坑是同一个。）
    ★ 为什么"去重但保序"而不是 `set`：`set` 的迭代顺序不稳定，
      同一份输入两次运行可能抹出不同结果 —— 那会让"这次回复为什么变了"
      变得不可复现。
    """
    out: List[str] = []
    for raw in names or ():
        name = str(raw or "").strip()
        if len(name) < MIN_STRIPPABLE_NAME_LEN:
            continue
        if name not in out:
            out.append(name)
    return sorted(out, key=len, reverse=True)


def strip_names(
    text: str,
    foreign_names: Optional[Iterable[Any]],
    *,
    whole_segment_patterns: Sequence[Pattern[str]] = (),
) -> str:
    """抹掉一段文本里的这些名字（纯函数、零 IO）。

    Args:
        text: 待处理文本。
        foreign_names: **不该出现**的名字（调用方给；不是"全部合法名字"）。
        whole_segment_patterns: 业务侧的"整段删除"正则，**在删名字之前**依次应用。
            店铺版传的是「自称当前店铺」的两条形态（`当前店铺（X）` /
            `当前店铺：X`）—— 那两句是要**整片段删掉**的污染槽位，
            不能只把里面的名字扣掉（替换词会被照抄，β 探针 E 组已证）。

    ★ 顺序不可换，理由分三层：
      ① 先删「自称」整段 —— 它本身是污染槽位；而且先删它，才不会把括号里的
         名字替换成一个半截空壳；
      ② 再删**含这些名字的整段引号内容**（`「…虾皮1 (Shopee MY)…」`）——
         实测：只删名字本体时，同段残留的平台后缀 `(Shopee MY)` 会孤零零留下，
         而模型**能从它反推出平台、再反推回那个名字**；
         用「整段删除」而不是"替换成一句话"：β 探针 E 组已证，放进去什么词，
         模型就可能把那个词回显出来；
      ③ 最后删残余的名字本体（此时已是长名优先）。
    """
    t = text or ""
    for pat in whole_segment_patterns:
        t = pat.sub("", t)

    ordered = order_names(foreign_names)
    if not ordered:
        return t

    # ★ 交替式里**长名在前**：正则交替是"最左优先"，短名在前会先吃掉前缀。
    alt = "|".join(re.escape(n) for n in ordered)
    t = re.sub(r"「[^」]*(?:" + alt + r")[^」]*」", "", t)
    for name in ordered:
        t = t.replace(name, "")
    return t


def scrub_ai_messages(
    messages: list,
    foreign_names: Optional[Iterable[Any]],
    *,
    strip=None,
) -> list:
    """把**发给模型的那份历史副本**里的外来名字抹掉（返回新列表）。

    Args:
        strip: 抹除实现，默认 `strip_names`。业务侧可传自己的包装
            （店铺版要额外带两条"整段删除"正则 —— 那两条是中文店名专用，
            不能塞进本模块）。

    ★ 只动 `AIMessage`（理由见模块 docstring 判断 1）。
    ★ 只在不为空名单时才建新列表；名单为空 ⇒ **原样返回同一个对象**。
    ★ 用 `model_copy(update=...)` 而不是直接改 `m.content`：原消息对象可能
      同时被 state / checkpoint 持有，原地改会让"可审计的历史"跟着变。
    """
    if not order_names(foreign_names):
        return messages
    fn = strip or strip_names
    out: list = []
    for m in messages:
        if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content:
            cleaned = fn(m.content, foreign_names)
            if cleaned != m.content:
                m = m.model_copy(update={"content": cleaned})
        out.append(m)
    return out


def detect(text: str, foreign_names: Optional[Iterable[Any]]) -> Tuple[str, ...]:
    """报出「这段文本里出现了哪些外来名字」（**不改文本**）。

    ★ 存在的理由：去污染是**静默**的 —— 抹完之后模型答案看起来完全正常，
      没人知道刚才发生过一次改写。排查"模型为什么改了说法"时，
      第一个要回答的就是"上一轮到底抹掉了什么"。日志里打它。
    ★ 返回顺序同 `order_names`（长名在前），便于与抹除结果对照。
    """
    t = text or ""
    return tuple(n for n in order_names(foreign_names) if n in t)


def pick_foreign(
    all_names: Iterable[Any], current: Optional[str]
) -> Tuple[str, ...]:
    """从「全部可见名字」里挑出**除当前之外**的那些（纯函数，便于门禁）。

    · 排除当前实体（按 identity）—— 它出现在历史里是对的，不该抹；
    · 去空白、跳过空名与短名（见 `MIN_STRIPPABLE_NAME_LEN`）；
    · **去重但保序**（保序是为了让日志与用例可比）。

    ★ 为什么"按 identity 排除"而不是"按名字排除"：同名不同体（两家都叫「1 号店」）
      时按名字排除会把另一家的名字保留下来 —— 那正是要抹的那一个。
    """
    cur = str(current or "").strip()
    out: List[str] = []
    for item in all_names or ():
        ident, name = _ident_and_name(item)
        if cur and ident and str(ident).strip() == cur:
            continue
        n = str(name or "").strip()
        if len(n) < MIN_STRIPPABLE_NAME_LEN:
            continue
        if n not in out:
            out.append(n)
    return tuple(out)


def _ident_and_name(item: Any) -> Tuple[Optional[str], Optional[str]]:
    """从"字典 / 二元组 / 裸字符串"三种形态里取 `(identity, name)`。

    ★ 兼容三种是因为调用方给的是**可见实体列表**（本仓店铺是 dict），
      而单测与将来的其它实体给的是元组或裸串 —— 让调用方各自适配会变成
      三份实现，这里收一处。
    """
    if isinstance(item, dict):
        return (
            item.get("id") or item.get("store_id") or item.get("key"),
            item.get("name") or item.get("title") or item.get("label"),
        )
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return str(item[0]) if item[0] is not None else None, str(item[1]) if item[1] is not None else None
    if isinstance(item, str):
        return None, item
    return None, None

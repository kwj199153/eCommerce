# -*- coding: utf-8 -*-
"""`ai_infra/name_guard.py` 的门禁（第 400 轮 · P2）。

## 这一层守的是"静默改写"

去污染是**静默**的：抹完之后模型答案看起来完全正常，没人知道刚才发生过一次
改写。所以失效也全是静默的：

① **抹多了** —— `text.replace("1", "")` 把整段历史里所有数字 1 都吃掉；
② **抹少了** —— 只删名字本体，残留 `(Shopee MY)` 让模型反推出旧名；
③ **抹错对象** —— 连 `HumanMessage`（老板原话）一起抹，多轮语境被破坏；
④ **原地改历史** —— state / checkpoint 里那份也跟着变，"可审计的历史"没了。

## 反向注入

`r400u_inject_guards.py`：
  · 把"长名优先"改成"短名优先" ⇒ 判据 2 红（`虾皮10` 被剁成 `0`）
  · 把 `MIN_STRIPPABLE_NAME_LEN` 改成 1 ⇒ 判据 1 红（单字名误伤）
  · 把"只动 AIMessage"放开成"所有消息" ⇒ 判据 3 红
  · 把 `model_copy` 换成原地赋值 ⇒ 判据 4 红
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from ai_infra.name_guard import (
    MIN_STRIPPABLE_NAME_LEN,
    detect,
    order_names,
    pick_foreign,
    scrub_ai_messages,
    strip_names,
)
from modules.secretary.shop_context import strip_foreign_shop_names


# ============================================================
# 1. 短名不参与（抹多了比抹少了更糟）
# ============================================================


def test_short_names_are_never_stripped():
    """★ 单字名会把历史里所有同字都吃掉 —— 为了抹一处旧名制造一段乱码。"""
    assert MIN_STRIPPABLE_NAME_LEN >= 2
    names = order_names(["1", "虾皮1", "", "  ", None])
    assert names == ["虾皮1"], names
    text = "2024 年 1 月，1 号店卖了 100 件"
    assert strip_names(text, ["1"]) == text, "单字名被抹了 —— 整段数字都会烂掉"


def test_order_names_dedupes_keeps_longest_first():
    names = order_names(["虾皮1", "虾皮10", "虾皮1", "亚马逊1"])
    assert names[0] == "虾皮10", f"长名必须排最前：{names}"
    assert names.count("虾皮1") == 1
    assert set(names) == {"虾皮1", "虾皮10", "亚马逊1"}


# ============================================================
# 2. 抹除：长名前缀 / 整段引号
# ============================================================


def test_longer_name_is_stripped_before_its_prefix():
    """★ `虾皮1` 是 `虾皮10` 的前缀 —— 短名先替换会把 `虾皮10` 剁成一个孤零零的 `0`。

    ★ 注意这条判据的**前提**：`虾皮10` 必须在名单里。名单由调用方给
      （`pick_foreign(可见店铺)`），两家长得像本来就是调用方的事实；
      本函数能做的是"名单里有的，按长的先删"，它没法替调用方发明一个没给的
      长名字 —— 那属于"输入不全"，不是本层的职责。
      实测口径：短名优先时结果是 `' 和 0 都在'`（`0` 是残留），长名优先是 `' 和  都在'`。
    """
    out = strip_names("虾皮1 和 虾皮10 都在", ["虾皮1", "虾皮10"])
    assert "0" not in out, f"实际 {out!r}（长名没先删，`虾皮10` 被剁出了残留的 0）"
    assert "虾皮" not in out


def test_quoted_segment_with_platform_suffix_is_removed_whole():
    """★ 只删名字本体时，残留的平台后缀会让模型反推出旧名。"""
    out = strip_names("现在是「虾皮1 (Shopee MY)」在跑", ["虾皮1"])
    assert "Shopee" not in out and "虾皮" not in out, out


def test_shop_adapter_still_removes_self_report_segments():
    """店铺适配层必须把「自称当前店铺」整段删掉（不只是删名字）。

    ★ 第 400 轮 P2 把这层逻辑上提成通用件之后，这条是**回归证明**：
      业务侧的两条正则必须仍被传进去（`whole_segment_patterns`），
      否则后半句「当前店铺：」会孤零零留下，模型照样顺着它编店名。
    """
    for text in ("当前店铺（虾皮1）：今天是晴天", "当前店铺：虾皮1\n销量还行"):
        out = strip_foreign_shop_names(text, ["虾皮1"])
        assert "当前店铺" not in out, f"{text!r} → {out!r}（自称片段没删干净）"
        assert "虾皮1" not in out


# ============================================================
# 3. 只动模型自己说过的话
# ============================================================


def test_human_messages_are_never_touched():
    """老板原话里的旧名字是**正当引用**（历史事实），抹掉会破坏多轮语境。"""
    msgs = [
        HumanMessage(content="虾皮1 有多少产品"),
        AIMessage(content="虾皮1 目前有 12 个产品"),
    ]
    out = scrub_ai_messages(msgs, ["虾皮1"])
    assert out[0].content == "虾皮1 有多少产品", "HumanMessage 被改了"
    assert "虾皮1" not in out[1].content


def test_empty_foreign_names_returns_same_object():
    """没绑实体 / 只有一家店时零开销 —— 且必须是**同一个对象**，
    否则"没有实体时历史一个字都不许变"这条既有判据会被新对象悄悄破坏。"""
    msgs = [AIMessage(content="虾皮1 有多少产品")]
    assert scrub_ai_messages(msgs, []) is msgs
    assert scrub_ai_messages(msgs, None) is msgs
    assert scrub_ai_messages(msgs, ["1"]) is msgs   # 只有短名 ⇒ 等于空名单


# ============================================================
# 4. 不改原消息（历史可审计）
# ============================================================


def test_original_messages_are_not_mutated():
    original = AIMessage(content="当前店铺（虾皮1）今天卖了 3 件")
    out = scrub_ai_messages([original], ["虾皮1"])
    assert "虾皮1" in original.content, "原消息被原地改了 —— checkpoint 里那份历史也跟着变"
    assert out[0] is not original
    assert "虾皮1" not in out[0].content


def test_only_changed_messages_are_copied():
    """没被改动的消息保持同一个对象（省拷贝，也让"哪些被改了"可数）。"""
    clean = AIMessage(content="今天卖了 3 件")
    dirty = AIMessage(content="虾皮1 卖了 3 件")
    out = scrub_ai_messages([clean, dirty], ["虾皮1"])
    assert out[0] is clean
    assert out[1] is not dirty


# ============================================================
# 5. 检测（不改文本，给日志用）
# ============================================================


def test_detect_reports_without_changing():
    text = "虾皮1 和 亚马逊1 都在跑"
    got = detect(text, ["虾皮1", "亚马逊1", "虾皮10"])
    assert set(got) == {"虾皮1", "亚马逊1"}
    assert text == "虾皮1 和 亚马逊1 都在跑", "detect 不该改文本"
    assert detect("干净文本", ["虾皮1"]) == ()


# ============================================================
# 6. 挑"除当前之外"
# ============================================================


def test_pick_foreign_excludes_by_identity_not_by_name():
    """★ 同名不同体时按名字排除会把**另一家**的名字留下来 —— 那正是要抹的那个。"""
    shops = [
        {"id": "s1", "name": "1 号店"},
        {"id": "s2", "name": "1 号店"},
        {"id": "s3", "name": "虾皮1"},
    ]
    got = pick_foreign(shops, "s1")
    # s2 与 s1 同名但不同体 ⇒ 保留（它的名字出现在历史里就是污染）
    assert got == ("1 号店", "虾皮1"), got


def test_pick_foreign_accepts_tuples_and_strings():
    assert pick_foreign([("s1", "甲店"), ("s2", "乙店")], "s1") == ("乙店",)
    assert pick_foreign(["甲店", "乙店"], None) == ("甲店", "乙店")


def test_pick_foreign_drops_short_and_dedupes():
    shops = [{"id": "s2", "name": "1"}, {"id": "s3", "name": "甲店"}, {"id": "s4", "name": "甲店"}]
    assert pick_foreign(shops, "s1") == ("甲店",)

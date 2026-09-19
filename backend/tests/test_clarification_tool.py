"""澄清工具门禁（第 145 轮 · 批 B3）。

## 背景

改造前，「参数不够就问一句」**只存在于提示词里**：

    # modules/secretary/agent.py 的 SECRETARY_SYSTEM_PROMPT 第 6 条
    关键信息不足（≥2 个核心参数缺失）时，调 handoff_to_agent 交接给专职 Agent 追问

那是**规则**，不是**能力**：模型不遵守时没有任何信号 —— 它不报错，只会
「硬凑一个默认值」或「默默换个人」。而且 `handoff_to_agent` 是**交接**
（切走前端 Agent），不是**提问**：即便走通了也是「换个人来问」。

批 B3 把提问做成**真工具**（`ai_infra/tools/clarification.py`）。
本文件钉住它作为工具的**存在性、结构、豁免声明与优先关系**。

## 反向注入

* 把 `make_clarification_tool()` 从注册表里删掉 ⇒ 第 1 条红；
* 把它的 `metadata` 改成 `SIDE_EFFECT_METADATA` ⇒ 第 3 条红（提问不该被审批拦住）；
* 把它的位置挪到 `handoff_to_agent` **之后** ⇒ 第 4 条红；
* 把 `agent.py` 里「先问后交」那段删掉 ⇒ 第 5 条红。
"""

from __future__ import annotations

import json
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _nav_tools():
    from modules.secretary.navigation_tools import navigation_tools

    return navigation_tools


def _tool_names() -> list[str]:
    return [t.name for t in _nav_tools()]


# ============================================================
# 1. 工具必须真的被装配
# ============================================================


def test_clarification_tool_is_registered():
    """`ask_clarification` 必须在 secretary 的工具注册表里。

    ★ 为什么这一条是「第一门禁」：批 B3 之前这个能力**根本没有工具**。
      只要它没被装配，LLM 就不可能调用它 —— 后面所有关于结构与语义的断言
      都会变成「对一个没人能用的对象做检查」。
    """
    names = _tool_names()
    assert "ask_clarification" in names, (
        f"secretary 注册表里没有 ask_clarification（当前 {names}）—— "
        "「提问」又退回成一条没人执行的提示词规则了"
    )


def test_clarification_tool_name_is_unique_globally():
    """工具名不得与别处重名（跨注册表唯一是既有铁律，这里只做局部对照）。"""
    from tests.test_tool_registry_guard import REGISTRY_FILES  # noqa: F401

    assert _tool_names().count("ask_clarification") == 1


# ============================================================
# 2. 返回体结构（前端消费契约）
# ============================================================


async def test_ask_clarification_returns_structured_request():
    """返回体必须是**结构化**的，且字段齐全 —— 前端要据此渲染提问卡。"""
    from ai_infra.tools.clarification import (
        CLARIFICATION_STATUS,
        CLARIFICATION_TYPE,
        ask_clarification,
    )

    raw = await ask_clarification(
        question="做这张主图时你想突出什么卖点？",
        options=["防水", "轻便", "续航"],
        missing_fields=["卖点"],
    )
    data = json.loads(raw)
    assert data["type"] == CLARIFICATION_TYPE == "clarification_request"
    assert data["status"] == CLARIFICATION_STATUS == "awaiting_user_input"
    assert data["action"] == "ask_user"
    assert data["question"] == "做这张主图时你想突出什么卖点？"
    assert data["options"] == ["防水", "轻便", "续航"]
    assert data["missing_fields"] == ["卖点"]


async def test_ask_clarification_tolerates_missing_optionals():
    """只给 question 也要能工作（options / missing_fields 是可选增强）。"""
    from ai_infra.tools.clarification import ask_clarification

    data = json.loads(await ask_clarification(question="你指的是哪个店铺？"))
    assert data["options"] == []
    assert data["missing_fields"] == []
    assert data["status"] == "awaiting_user_input"


async def test_ask_clarification_rejects_blank_question():
    """空问题必须**显式拒绝**，而不是产出一张没有内容的卡片。

    ★ 为什么这条重要：空问题会让前端渲染出一张空卡 —— 用户侧表现为
      「AI 卡住了」，而真相是 LLM 调用参数错误。**归因错误的失败比报错更糟**：
      用户会去查网络、查登录，而问题其实在参数。
    """
    from ai_infra.tools.clarification import ask_clarification

    for blank in ("", "   ", "\n\t "):
        data = json.loads(await ask_clarification(question=blank))
        assert data.get("status") == "error", f"{blank!r} 竟然被当成了合法提问"
        assert "question" in data.get("error", ""), "拒绝理由要点明缺的是 question"


# ============================================================
# 3. 它必须是「只读」：提问不该被审批闸门拦住
# ============================================================


def test_clarification_tool_is_declared_read_only():
    """`ask_clarification` 必须声明为只读（免审批）。

    ★ 为什么：它**不产生任何副作用** —— 只是把一个问题结构化地返回给编排层。
      若它被判为需审批，就会出现荒谬的交互：「要不要问老板一个问题？」
      → 老板必须先点「批准」才能被问到问题。
    """
    from ai_infra.tools.side_effects import declared_side_effects, has_side_effects

    t = next(t for t in _nav_tools() if t.name == "ask_clarification")
    assert declared_side_effects(t) is False, "未显式声明为只读"
    assert has_side_effects(t) is False, "提问被算成了副作用 —— 会被审批闸门拦住"


def test_clarification_tool_not_in_gated_set():
    """它不得出现在「需审批工具集合」里（与上面的声明互为对照）。"""
    from ai_infra.tools.side_effects import derive_hitl_tools

    assert "ask_clarification" not in derive_hitl_tools(_nav_tools())


# ============================================================
# 4. 优先关系：先「问」后「交接」
# ============================================================


def test_clarification_precedes_handoff_in_registry():
    """注册表顺序上，`ask_clarification` 必须排在 `handoff_to_agent` **之前**。

    ★ 为什么顺序是有意义的：工具排列对 LLM 有弱提示作用（先看到的更倾向于先选），
      而两者的正确优先关系是「能在当前会话问清楚，就不要把对话交接走」——
      交接会切走前端 Agent、丢掉当前上下文，是**更重**的动作。
      顺序与提示词规则一致，才是同一件事的两种表达；不一致就是互相矛盾。
    """
    names = _tool_names()
    assert "ask_clarification" in names and "handoff_to_agent" in names
    assert names.index("ask_clarification") < names.index("handoff_to_agent"), (
        "顺序反了 —— 会把 LLM 往「先交接走」的方向推"
    )


def test_system_prompt_states_ask_before_handoff():
    """提示词里必须有「先问后交」的显式规则（顺序约束不能只靠注册表排列）。

    ★ 为什么要检查源码文本而不是行为：提示词的效果无法在单测里断言（那需要真跑
      LLM），但「规则还在不在」是可判定的 —— 而它被删掉时**不会报任何错**，
      只会让行为悄悄退化。这类「静默退化」正是文本级门禁存在的理由。
    """
    src = (BACKEND / "modules" / "secretary" / "agent.py").read_text(encoding="utf-8")
    assert "ask_clarification" in src, "提示词里没提 ask_clarification —— 工具存在但模型不知道何时用"
    assert "handoff_to_agent" in src
    assert "先问后交" in src, "『先问后交』这条规则被删了或改了措辞（改了就把本断言一起改）"

    # ★ 真正的判据在**规则 6 那一段内部**：ask_clarification 的提及必须早于
    #   handoff_to_agent。全文件级的 index 比较没有意义（路由工具清单那段在前，
    #   顺序恰好相反）—— 本文件初版就写了 `或 True` 的恒真断言，等于没查。
    seg_start = src.index("6. 【重要】")
    seg_end = src.index("7. ", seg_start)
    rule6 = src[seg_start:seg_end]
    assert "ask_clarification" in rule6 and "handoff_to_agent" in rule6, (
        "规则 6 必须同时提到两个工具，否则「先问后交」的先后关系无从表达"
    )
    assert rule6.index("ask_clarification") < rule6.index("handoff_to_agent"), (
        "规则 6 里的顺序反了 —— 提示词会把模型往「先交接走」的方向推"
    )

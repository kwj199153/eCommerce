"""上下文窗口门禁（第 147 轮 · 批 C4）。

对应 r141《Agent 能力缺口评审》批 C 的 C4：
    「在 `_llm_call_node` 前加裁剪/摘要钩子：按 token 预算裁历史 +
      折叠旧工具结果为摘要」

★ 本文件钉住的**安全属性**（不是实现细节）：

    P1 裁剪**不是**结构清洗的别名：`_sanitize_tool_call_pairing` 剔孤儿发生在
       批 C4 之前，它**不减少一个字节** —— 长会话照样撞窗口。两者必须同时存在。
    P2 四条不变量：
       I1 当前轮永不裁   I2 保底 `keep_recent_turns` 轮
       I3 `tool_call_id` 配对完整   I4 消息相对顺序不变（只删、只换内容，不重排）
    P3 「没裁到位」必须**显式**（`TrimReport.over_budget`）——
       静默假装成功会把失败推迟到对端，而那时看不出是这里没做到。
    P4 token 估算有**唯一真源**：`dashscope_client.estimate_tokens`。
       私有名 `DashScopeLLM._estimate_tokens` 只允许是**一行转发**
       （它被 `test_llm_client.py` 钉住，既不能删，也不能变成第二份实现）。
    P5 接线顺序：`trim_history` 必须在 `ainvoke` **之前**（裁完再发）。
    P6 裁剪只作用于 `clean_messages`（不含 system prompt）——
       裁掉 system prompt 等于把 Agent 的人设删了。
    P7 折叠**只针对非当前轮**：用户刚拿到的工具结果，模型正要基于它回答。
    P8 业务侧的上下文档位必须是**具名常量**（`CONTEXT_*`），且与
       `budget=BUDGET_*` **同档**。两者管不同维度（预算=「跑多久」、
       上下文=「这一次发出去多大」），同档只为让「为什么是这个数」一处说得清。

★ 反面（误报）也钉住：短会话**不得**被裁（`report.changed` 为假），
  否则每轮白折一次、日志噪音，而且模型看到的是被摘要过的「原始结果」。

反向注入对照（每条都应打穿本文件的某一条 —— 已实测，见第 147 轮记录）：
    · 删 `trim_history` 调用                             → D 组转红
    · 把 `trim_history(clean_messages, …)` 换成原始历史    → C 组转红
    · 去掉 spans[-1] 的当前轮保护                          → A 组 I1 转红
    · `while len(remaining) > keep` 改成 `>=`             → A 组 I2 转红
    · 折叠时新建 ToolMessage 而不带 `tool_call_id`         → A 组 I3 转红
    · `over_budget` 写死 `False`                          → A 组 P3 转红
    · 从最旧删起改成**删中间的轮**                        → A 组 I4 转红
      （★ 这条要求 I4 的键**每轮唯一**；拿类名序列当键时它红 0 条）
    · 私有 `_estimate_tokens` 里重写一份算式               → B 组 P4 转红
    · 业务侧手搓 `ContextPolicy(...)` 或写死 `max_input_tokens=`
                                                      → F 组转红
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

BACKEND = pathlib.Path(__file__).resolve().parents[1]
CONTEXT_PY = BACKEND / "ai_infra" / "context.py"
BASE_AGENT_PY = BACKEND / "ai_infra" / "base_agent.py"
DS_PY = BACKEND / "ai_infra" / "llm" / "dashscope_client.py"
MODULES = BACKEND / "modules"

from ai_infra.base_agent import BaseAgent  # noqa: E402
from ai_infra.context import (  # noqa: E402
    CONTEXT_INTERACTIVE,
    CONTEXT_ROUTER,
    CONTEXT_STANDARD,
    DEFAULT_CONTEXT_POLICY,
    ContextPolicy,
    TrimReport,
    trim_history,
)


# ==================================================================== 工具
def _turn(call_id: str, tool_name: str, payload: str, answer: str = "ok") -> list:
    """一轮工具调用：AIMessage(tool_calls) + ToolMessage + AIMessage(收尾)。"""
    return [
        AIMessage(content="", tool_calls=[{"name": tool_name, "args": {}, "id": call_id}]),
        ToolMessage(content=payload, tool_call_id=call_id, name=tool_name),
        AIMessage(content=answer),
    ]


def _history(n_turns: int, payload_chars: int = 40) -> list:
    """构造 n 轮历史，每轮 = HumanMessage + `_turn(...)`。"""
    msgs: list = [HumanMessage(content="第 1 轮问题")]
    for i in range(n_turns):
        if i:
            msgs.append(HumanMessage(content="第 %d 轮问题" % (i + 1)))
        msgs += _turn("c%d" % i, "tool_%d" % i, "x" * payload_chars)
    return msgs


def _keys(messages) -> list:
    """每条消息的**命脉键**：类名 + 一个**跨折叠存活**、且**每轮唯一**的标识。

    ★ 为什么不能用「类名序列」——第 147 轮 RI-06 第二轮实测出来的：
      `_history()` 造出的类名序列是 `HAIA`（Human/AI/Tool/AI）的**周期串**，
      而「删掉任意整数个**整轮**」得到的串**仍然等于**原串的某个连续切片
      ⇒ 只比类名的判据对「删中间的轮」**天然免疫**。这是周期序列的固有盲区，
      不是实现写错了（两条「重排」注入 + 一条「删中间」注入打在它身上红 0 条，
      就是这件事在报警：一条打不穿的判据不是门禁，是装饰）。
      ⇒ 换成**每轮都不同**的键之后，删中间轮才会把序列断成两截。

    ★ `ToolMessage` 取 `tool_call_id` 而不是 `content`：折叠只换 `content`
      （id 原样带走），若拿 content 当键，**正确的折叠**会被误判成
      「不再是切片」（假 BAD —— 与「基线与现测须同口径」同族）。
    """
    keys = []
    for m in messages:
        cls = m.__class__.__name__
        tool_calls = getattr(m, "tool_calls", None) or []
        if cls == "ToolMessage":
            keys.append((cls, getattr(m, "tool_call_id", "")))
        elif tool_calls:
            keys.append((cls, tuple(tc.get("id") for tc in tool_calls)))
        else:
            keys.append((cls, str(getattr(m, "content", ""))))
    return keys


def _assert_pairing_ok(messages) -> None:
    """I3：不存在「有 ToolMessage 而没有任何 AIMessage 声明它的 id」。"""
    declared = set()
    for m in messages:
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc.get("id"):
                declared.add(tc["id"])
    for m in messages:
        if isinstance(m, ToolMessage):
            assert m.tool_call_id in declared, (
                "裁剪后出现孤儿 ToolMessage(id=%r) —— 会被对端 400 拒绝"
                % m.tool_call_id
            )


def _assert_contiguous_slice(kept, original) -> None:
    """I4：保留消息的类别序列必须是原序列的一个**连续切片**。

    ★ 为什么不是「子序列」——第 147 轮 RI-06 实测出来的：
      裁轮永远从当前 `out` 的开头删起 ⇒ `out[:start]` **恒为空**（删首轮时
      `start == 0`；删之后续轮时，前面的删除已把 `remaining` 的起点前移到 0）
      ⇒ 「重排」在这个实现里**结构上不可能发生** ⇒ 子序列判据**无法被任何注入
      打穿**（两条重排注入实测均红 0 条）。一条打不穿的判据不是门禁，是装饰。
    ⇒ 升级为「连续切片」：它同时能抓住「删中间的轮」（那会让类别序列断成两截，
      子序列判据看不出来、连续切片判据看得出来）。

    ★★ 但「连续切片」**还不够**（RI-06 第二轮实测）：键必须是**每轮唯一**的。
      首版拿**类名序列**当键，而 `HAIA` 是周期串 ⇒ 删掉任意整数个整轮后，
      序列**仍然像**一个连续切片 ⇒ 注入打在它身上红 0 条。
      ⇒ 升级为 `_keys()` 的**命脉键**（每轮唯一 + 跨折叠存活）之后才真能红。
    """
    okeys, kkeys = _keys(original), _keys(kept)
    if not kkeys:
        return
    for s in range(0, len(okeys) - len(kkeys) + 1):
        if okeys[s:s + len(kkeys)] == kkeys:
            return
    raise AssertionError(
        "保留的消息不是原序列的连续切片（重排，或删了中间的轮，而非从最旧删起）"
    )


def _run_node(agent: BaseAgent, state: dict, ai: AIMessage):
    """驱动 `_llm_call_node` 一次，返回 (节点返回值, 实际发给 LLM 的 messages)。"""
    captured: dict = {}

    with patch.object(agent, "_llm_with_tools") as m:
        async def _capture(messages, *a, **kw):
            captured["messages"] = messages
            return ai

        m.return_value.ainvoke = _capture
        result = asyncio.run(agent._llm_call_node(state))
    return result, captured["messages"]


# ================================================== A 组 · 机制（context 模块）
def test_policy_rejects_non_positive_thresholds():
    """fail-fast：非正阈值 ⇒ 构造即拒绝。

    非正会退化成两种假象：fail-open（永不裁）或静默的能力删除（一上来就裁空）。
    在构造点拒绝，错误暴露在写代码的人面前。
    """
    for field in ("max_input_tokens", "keep_recent_turns",
                  "fold_tool_result_chars", "fold_head_chars"):
        with pytest.raises(ValueError):
            ContextPolicy(**{field: 0})
        with pytest.raises(ValueError):
            ContextPolicy(**{field: -1})
        # bool 要单独挡：`True <= 0` 是 False，会从数值校验里溜过去
        with pytest.raises(ValueError):
            ContextPolicy(**{field: True})


def test_policy_rejects_empty_label_and_useless_fold():
    with pytest.raises(ValueError):
        ContextPolicy(label="")
    # 头部 >= 阈值 ⇒ 折叠后不比原文短，等于没折（不会报错，只会白做一遍）
    with pytest.raises(ValueError):
        ContextPolicy(fold_tool_result_chars=200, fold_head_chars=200)
    with pytest.raises(ValueError):
        ContextPolicy(fold_tool_result_chars=200, fold_head_chars=500)


def test_default_policy_is_standard_and_named_tiers_exist():
    assert DEFAULT_CONTEXT_POLICY is CONTEXT_STANDARD
    labels = {CONTEXT_STANDARD.label, CONTEXT_INTERACTIVE.label, CONTEXT_ROUTER.label}
    assert labels == {"standard", "interactive", "router"}
    assert CONTEXT_INTERACTIVE.max_input_tokens > CONTEXT_STANDARD.max_input_tokens > \
        CONTEXT_ROUTER.max_input_tokens


def test_empty_history_is_noop():
    msgs: list = []
    out, rep = trim_history(msgs, CONTEXT_STANDARD)
    assert out == [] and rep.turns_total == 0 and not rep.changed


def test_no_human_message_is_treated_as_one_turn_and_not_trimmed():
    """一条 HumanMessage 都没有 ⇒ 整块视为一轮，不裁（裁了就是全删）。

    ★ 为什么不是「按别的界切轮」：切不出界时宁可多留 —— 丢用户内容比超长更糟。
    """
    msgs = _turn("a", "t", "y" * 5000)          # 只有 AI/Tool，没有 Human
    out, rep = trim_history(msgs, ContextPolicy(max_input_tokens=10, keep_recent_turns=1,
                                                fold_tool_result_chars=100, fold_head_chars=20))
    assert out == msgs, "无 Human 的历史不得被裁"
    assert rep.turns_total == 1
    # 唯一保底轮 = 它自己；虽然没有 Human，仍要显式声明没裁到预算内
    assert rep.over_budget is True


# ------------------------------------------------- I2 保底
def test_keeps_at_least_keep_recent_turns():
    policy = ContextPolicy(max_input_tokens=200, keep_recent_turns=3,
                           fold_tool_result_chars=200, fold_head_chars=60)
    msgs = _history(8, payload_chars=2000)
    out, rep = trim_history(msgs, policy)
    assert rep.turns_kept >= policy.keep_recent_turns, (
        "保底轮数被突破 ⇒ 一次裁剪就把上下文炸成空"
    )
    assert rep.turns_kept == policy.keep_recent_turns
    assert rep.turns_dropped == rep.turns_total - rep.turns_kept
    # 保留的必须是**最近**的若干轮（最后一条消息仍在）
    assert out[-1].content == "ok"
    assert _keys(out) == _keys(msgs)[len(msgs) - len(out):], (
        "保留的不是尾部连续段 —— 说明删的是最近的轮而不是最旧的轮"
    )


# ------------------------------------------------- I1 当前轮永不裁
def test_current_turn_is_never_trimmed_even_when_over_budget():
    """当前轮极长时，宁可超预算（`over_budget=True`）也不删它。

    删掉它 = 把用户这次问的话删了 ⇒ 模型答非所问，而没有任何报错。
    """
    policy = ContextPolicy(max_input_tokens=50, keep_recent_turns=1,
                           fold_tool_result_chars=200, fold_head_chars=60)
    msgs = _history(4, payload_chars=3000)
    out, rep = trim_history(msgs, policy)
    last_human = [m for m in msgs if isinstance(m, HumanMessage)][-1]
    assert last_human in out, "当前轮的 HumanMessage 被裁掉了"
    assert out[-1] is msgs[-1], "最后一条消息（本轮产出）被换掉或被删了"
    assert rep.over_budget is True, "已超预算却没显式声明 —— 这就是静默假装成功"


# ------------------------------------------------- I3 配对完整
def test_folding_preserves_tool_call_id():
    """折叠只换 `content`，`tool_call_id` 必须原样带走。"""
    policy = ContextPolicy(max_input_tokens=10_000, keep_recent_turns=4,
                           fold_tool_result_chars=100, fold_head_chars=30)
    msgs = _history(3, payload_chars=500)
    out, rep = trim_history(msgs, policy)
    assert rep.folded_tool_results >= 1
    _assert_pairing_ok(out)
    for m in out:
        if isinstance(m, ToolMessage):
            assert m.tool_call_id, "折叠后 tool_call_id 丢了"


def test_trimming_never_breaks_pairing():
    policy = ContextPolicy(max_input_tokens=200, keep_recent_turns=2,
                           fold_tool_result_chars=200, fold_head_chars=60)
    out, rep = trim_history(_history(8, payload_chars=2000), policy)
    _assert_pairing_ok(out)
    assert rep.turns_dropped > 0, "本用例的前提是发生了裁轮"


# ------------------------------------------------- I4 顺序不变
def test_order_is_preserved_and_result_is_contiguous():
    """I4：保留部分必须是原序列的连续切片（不是「删中间的轮」也不是重排）。"""
    policy = ContextPolicy(max_input_tokens=200, keep_recent_turns=2,
                           fold_tool_result_chars=200, fold_head_chars=60)
    msgs = _history(8, payload_chars=2000)
    out, _ = trim_history(msgs, policy)
    _assert_contiguous_slice(out, msgs)


# ------------------------------------------------- P7 折叠只针对非当前轮
def test_only_old_tool_results_are_folded():
    policy = ContextPolicy(max_input_tokens=10_000, keep_recent_turns=4,
                           fold_tool_result_chars=100, fold_head_chars=30)
    msgs = _history(3, payload_chars=500)
    out, rep = trim_history(msgs, policy)
    current_tools = [m for m in out if isinstance(m, ToolMessage)][-1]
    assert len(current_tools.content) == 500, (
        "当前轮的工具结果被折叠了 —— 模型正要基于它回答，摘要会丢信息"
    )
    assert rep.folded_tool_results == 2, "只有前两轮（非当前轮）该被折叠"


def test_folded_text_is_self_describing():
    """折叠文案必须自述「被折叠了 + 原始体积」—— 否则模型以为自己有全量信息。"""
    policy = ContextPolicy(max_input_tokens=10_000, keep_recent_turns=4,
                           fold_tool_result_chars=100, fold_head_chars=30)
    out, _ = trim_history(_history(2, payload_chars=400), policy)
    folded = [m for m in out if isinstance(m, ToolMessage) and "[已折叠]" in str(m.content)]
    assert folded, "没有任何工具结果被折叠"
    text = str(folded[0].content)
    assert "400" in text, "折叠文案未回带原始字符数（模型无从判断丢了多少）"


# ------------------------------------------------- P3 显式声明
def test_changed_flag_is_false_for_short_history():
    """反面：短会话不得被裁，也不得报「变了」。"""
    msgs = _history(2, payload_chars=30)
    out, rep = trim_history(msgs, CONTEXT_STANDARD)
    assert rep.changed is False
    assert rep.over_budget is False
    assert out == msgs


def test_report_as_dict_has_stable_keys():
    _, rep = trim_history(_history(2), CONTEXT_STANDARD)
    d = rep.as_dict()
    assert set(d) == {
        "turns_total", "turns_kept", "turns_dropped", "folded_tool_results",
        "tokens_before", "tokens_after", "over_budget", "label",
    }
    assert isinstance(rep, TrimReport)


# ------------------------------------------------- 纯函数性质
def test_is_pure_does_not_mutate_input_and_is_deterministic():
    policy = ContextPolicy(max_input_tokens=200, keep_recent_turns=2,
                           fold_tool_result_chars=200, fold_head_chars=60)
    msgs = _history(8, payload_chars=2000)
    snapshot = [(m.__class__.__name__, str(m.content)) for m in msgs]
    out1, rep1 = trim_history(msgs, policy)
    out2, rep2 = trim_history(msgs, policy)
    assert [(m.__class__.__name__, str(m.content)) for m in msgs] == snapshot, "入参被改动了"
    assert [str(m.content) for m in out1] == [str(m.content) for m in out2], "不确定"
    assert rep1 == rep2


def test_multimodal_content_does_not_crash():
    """content 是 list（多模态）时不能炸 —— 也不能用 `len(str(content))` 当口径。"""
    msgs = [
        HumanMessage(content="看图"),
        AIMessage(content="",
                  tool_calls=[{"name": "t", "args": {}, "id": "m1"}]),
        ToolMessage(content=[{"type": "text", "text": "结" * 300}],
                    tool_call_id="m1", name="t"),
        AIMessage(content="done"),
    ]
    policy = ContextPolicy(max_input_tokens=100_000, keep_recent_turns=4,
                           fold_tool_result_chars=100, fold_head_chars=30)
    out, rep = trim_history(msgs, policy)
    assert rep.folded_tool_results == 0, "当前轮不该折叠"
    assert out == msgs


# ============================================== B 组 · token 估算唯一真源
def test_estimate_tokens_has_single_public_source():
    """P4：公开入口可取、私有名与它同结果（不是两份实现）。"""
    from ai_infra.llm import estimate_tokens as via_facade
    from ai_infra.llm.dashscope_client import DashScopeLLM, estimate_tokens

    assert via_facade is estimate_tokens, "门面导出的不是同一个函数对象"
    for n in (0, 1, 3, 150, 1500):
        assert DashScopeLLM._estimate_tokens(n) == estimate_tokens(n), (
            "私有包装与真源结果不一致 ⇒ 又出现了第二份口径"
        )


def test_token_estimate_formula_appears_exactly_once():
    """AST 判据：`int(x / 1.5)` 这个算式全文件只允许出现一次。

    ★ 为什么不用「源码字符串包含」：注释与 docstring 里也会写出这个式子，
      字符串匹配会被它们骗过（假绿）。只数**表达式节点**。
    """
    tree = ast.parse(DS_PY.read_text(encoding="utf-8"))
    hits = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.BinOp) or not isinstance(n.op, ast.Div):
            continue
        right = n.right
        if isinstance(right, ast.Constant) and right.value == 1.5:
            hits.append(n.lineno)
    assert len(hits) == 1, (
        "字符→token 的算式出现了 %d 次（行 %s）—— 只允许在模块级 estimate_tokens 里"
        % (len(hits), hits)
    )


def test_context_module_uses_the_shared_estimator():
    """`ai_infra/context.py` 必须**引用**真源，而不是自己算。"""
    tree = ast.parse(CONTEXT_PY.read_text(encoding="utf-8"))
    imports = {
        a.name
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    }
    assert "estimate_tokens" in imports, "context.py 没有从 dashscope_client 引入真源"
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            r = n.right
            assert not (isinstance(r, ast.Constant) and r.value == 1.5), (
                "context.py 里自己写了一份 token 算式 —— 复用真源，别抄"
            )


# ================================================== C 组 · 接线形态（AST）
def _func(tree: ast.AST, cls: str, name: str):
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == name:
                    return m
    raise AssertionError("未找到 %s.%s" % (cls, name))


def test_trim_history_is_called_before_llm_invoke():
    """P5：先裁再发。晚一行都等于没裁（发的还是全量）。"""
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func(tree, "BaseAgent", "_llm_call_node")
    trim_line = invoke_line = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "trim_history":
                trim_line = n.lineno
            if isinstance(f, ast.Attribute) and f.attr == "ainvoke":
                invoke_line = n.lineno
    assert trim_line is not None, "_llm_call_node 里没有调用 trim_history（C4 没接线）"
    assert invoke_line is not None, "未找到 ainvoke 调用点"
    assert trim_line < invoke_line, (
        "trim_history 在 ainvoke 之后（trim=%s, invoke=%s）—— 裁了但发的是裁之前的"
        % (trim_line, invoke_line)
    )


def test_trim_history_targets_clean_messages_not_raw_history():
    """P6：裁的是 `clean_messages`（已剔孤儿、且不含 system prompt）。

    ★ 若裁原始历史：① 会把孤儿消息的清洗白做（裁完又回来）；
      ② 若有人顺手把 system prompt 也放进被裁对象，Agent 的人设就没了。
    """
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func(tree, "BaseAgent", "_llm_call_node")
    targets = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id == "trim_history":
            assert n.args, "trim_history 没有位置实参"
            a0 = n.args[0]
            assert isinstance(a0, ast.Name), "第一个实参不是变量名：%s" % type(a0).__name__
            targets.append(a0.id)
    assert targets == ["clean_messages"], "trim_history 的输入是 %s" % targets


def test_budget_state_carries_context_report():
    """裁剪结论必须落到调用方读得到的地方（否则模型像「失忆」时无从解释）。"""
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func(tree, "BaseAgent", "_llm_call_node")
    keys = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    assert "context" in keys, "budget_state 里没有 context 键"
    assert {"spent_tokens", "iterations"} <= keys, "原有键被动了（C5 的契约）"


def test_init_accepts_context_policy_and_defaults_to_shared_tier():
    """P4/P5：口径由构造点声明，缺省落到共享档位（不是各写一个数字）。"""
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func(tree, "BaseAgent", "__init__")
    args = {a.arg: a for a in list(fn.args.args) + list(fn.args.kwonlyargs)}
    assert "context_policy" in args, "__init__ 没有 context_policy 形参"
    for a in fn.args.args + fn.args.kwonlyargs:
        if a.arg == "context_policy":
            assert isinstance(a.annotation, ast.Name) and a.annotation.id == "Optional" or \
                isinstance(a.annotation, ast.Subscript), \
                "context_policy 的类型注解不是 Optional[...]"
    assert "ContextPolicy" in BASE_AGENT_PY.read_text(encoding="utf-8")
    # 缺省必须落到共享档位
    src = BASE_AGENT_PY.read_text(encoding="utf-8")
    assert "DEFAULT_CONTEXT_POLICY" in src, "缺省没有引用共享档位"


def test_context_policy_is_an_instance_attribute():
    """必须是 `self.` 属性：局部变量会让「业务侧声明的档位」静默失效。"""
    src = BASE_AGENT_PY.read_text(encoding="utf-8")
    assert "self.context_policy = (" in src
    a = BaseAgent(agent_name="ctx-attr-probe")
    assert a.context_policy is DEFAULT_CONTEXT_POLICY
    b = BaseAgent(agent_name="ctx-attr-probe-r", context_policy=CONTEXT_ROUTER)
    assert b.context_policy is CONTEXT_ROUTER
    assert a.context_policy is DEFAULT_CONTEXT_POLICY, "构造被串味了"


# ================================================== D 组 · 端到端行为
def test_long_history_is_actually_shrunk_before_sending():
    """接通后的可观测效果：发给 LLM 的消息真的变少，且关键消息都在。"""
    agent = BaseAgent(
        agent_name="ctx-e2e", system_prompt="你是助手",
        context_policy=ContextPolicy(max_input_tokens=200, keep_recent_turns=2,
                                     fold_tool_result_chars=200, fold_head_chars=60),
    )
    msgs = _history(8, payload_chars=2000)
    result, sent = _run_node(agent, {"messages": msgs}, AIMessage(content="ok"))

    assert isinstance(sent[0], SystemMessage), "system prompt 必须仍在第 0 位（P6）"
    assert sent[0].content == "你是助手"
    body = sent[1:]
    assert len(body) < len(msgs), "发给 LLM 的消息没有变少 —— 裁剪没生效"
    assert body[-1] is msgs[-1], "本轮最后一条消息被换掉或被删了"
    last_human = [m for m in msgs if isinstance(m, HumanMessage)][-1]
    assert last_human in body, "当前轮的 HumanMessage 丢了"
    _assert_pairing_ok(body)

    report = result["budget"]["context"]
    assert report["turns_dropped"] > 0
    assert report["turns_kept"] >= 2
    assert report["label"] == "standard"
    # tokens 是**估算**，但必须真的下降
    assert report["tokens_after"] < report["tokens_before"]


def test_short_history_passes_through_untouched():
    """反面：短会话不被裁，`context` 仍是显式结论（changed=False）。"""
    agent = BaseAgent(agent_name="ctx-short", system_prompt="s")
    msgs = _history(2, payload_chars=20)
    result, sent = _run_node(agent, {"messages": msgs}, AIMessage(content="ok"))
    assert sent[1:] == msgs, "短会话的历史被改动了"
    report = result["budget"]["context"]
    assert report["turns_dropped"] == 0 and report["folded_tool_results"] == 0
    assert report["over_budget"] is False


def test_trimmed_history_still_has_no_orphan_after_sanitize():
    """裁剪 + 结构清洗两者叠加后，仍不得产生孤儿（否则对端 400）。"""
    agent = BaseAgent(
        agent_name="ctx-orphan", system_prompt="s",
        context_policy=ContextPolicy(max_input_tokens=200, keep_recent_turns=2,
                                     fold_tool_result_chars=200, fold_head_chars=60),
    )
    msgs = _history(8, payload_chars=2000)
    # 故意塞一条孤儿 ToolMessage：清洗该剔掉它，裁剪也不得把它留下
    msgs.append(ToolMessage(content="orphan", tool_call_id="__nope__", name="z"))
    _, sent = _run_node(agent, {"messages": msgs}, AIMessage(content="ok"))
    _assert_pairing_ok(sent[1:])


def test_over_budget_is_surfaced_not_swallowed(caplog=None):
    """P3：裁不到预算内 ⇒ 必须有 WARNING（可告警），且**不抛异常**。

    ★ 不抛的理由：此刻消息里装的是用户这次问的东西，丢掉它比超长更糟。
      但必须留下痕迹，否则下一次失败看起来像对端的问题。
    """
    agent = BaseAgent(
        agent_name="ctx-over", system_prompt="s",
        context_policy=ContextPolicy(max_input_tokens=50, keep_recent_turns=1,
                                     fold_tool_result_chars=100, fold_head_chars=20),
    )
    msgs = _history(3, payload_chars=3000)
    with patch("ai_infra.base_agent.logger") as lg:
        result, _sent = _run_node(agent, {"messages": msgs}, AIMessage(content="ok"))
    assert result["budget"]["context"]["over_budget"] is True
    assert lg.warning.called, "超预算被静默吞掉了（没有 WARNING）"
    assert any("未回到预算内" in str(c) for c in lg.warning.call_args_list), \
        "WARNING 文案没说明是「这里没做到」"


# ================================================== E 组 · 分层
def _load_layering_gate():
    """按路径加载 layering 门禁 —— **复用它的扫描函数**，不另写一份判据。

    ★ `tests/` 没有 `__init__.py`，不能写 `from tests.xxx import ...`；
      按路径 importlib 加载是本仓已有的做法（见 `test_memory_hygiene.py`）。
      ★ 「同一指标两份实现 ⇒ 至少一份永远测不到」：分层判据只允许有一处。
    """
    import importlib.util

    p = BACKEND / "tests" / "test_infra_layering.py"
    spec = importlib.util.spec_from_file_location("layering_gate_probe", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_context_module_respects_infra_layering():
    """新模块不得引入业务依赖（复用 layering 门禁的扫描函数，不另写一份）。"""
    gate = _load_layering_gate()
    scan_reverse_imports = gate.scan_reverse_imports
    scan_business_strings = gate.scan_business_strings

    src = CONTEXT_PY.read_text(encoding="utf-8")
    assert scan_reverse_imports(src) == [], "ai_infra/context.py 反向 import 了业务模块"
    hits = scan_business_strings(src)
    assert not hits, "ai_infra/context.py 的字符串字面量里出现业务内容: %s" % hits


# ================================================== F 组 · 业务侧档位（形态门禁）
def _module_files() -> list[pathlib.Path]:
    return sorted(p for p in MODULES.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize(
    "rel,expect",
    [
        ("secretary/agent.py", "CONTEXT_INTERACTIVE"),
        ("listing_generator/agent_listing.py", "CONTEXT_ROUTER"),
        ("product_research/agent_product_research.py", "CONTEXT_ROUTER"),
    ],
)
def test_business_agents_use_the_matching_context_tier(rel, expect):
    """C4 的三个落点必须仍是**具名档位**（与 C5 的 `budget=BUDGET_*` 同档）。

    ★ 为什么值得单独立一条：档位接线是「加一行就完事」的改动，
      被改回裸数字或换错档**不会有任何症状** —— 只会让长会话在真实流量下
      悄悄撞窗口（失败点在对端，本地只剩一句 HTTP 400）。形态门禁是这里
      唯一能让它「当场红」的东西（同族判据：「配置存在」≠「门禁生效」）。
    """
    tree = ast.parse((MODULES / rel).read_text(encoding="utf-8"))
    names = {
        kw.value.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg == "context_policy" and isinstance(kw.value, ast.Name)
    }
    assert expect in names, (
        f"{rel} 未使用 {expect}（实际 context_policy= 取到 {sorted(names)}）"
    )


def test_business_modules_do_not_hardcode_context_thresholds():
    """业务侧不得出现 `max_input_tokens=` / `keep_recent_turns=` 裸数字。

    与 C5 的 `test_business_modules_do_not_hardcode_max_iterations` 对称：
    新增 Agent 时若顺手写 `max_input_tokens=8000`，这条会红 —— 逼着作者
    去选一个**具名档位**（或先给档位表加一档），让「为什么是这个数」有地方可写。

    ★ 只扫 `modules/`（业务侧）。`ai_infra/context.py` 里的
      `ContextPolicy(...)` 是**真源本身**，不算违规。
    """
    bad = []
    for f in _module_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg in ("max_input_tokens", "keep_recent_turns"):
                        bad.append(f"{f.relative_to(BACKEND)}:{n.lineno}")
    assert not bad, (
        f"业务侧出现上下文阈值硬编码: {bad} —— 请改用 ai_infra.context 的"
        f"具名档位（CONTEXT_ROUTER / CONTEXT_INTERACTIVE / CONTEXT_STANDARD）"
    )


def test_context_module_is_the_only_place_defining_tiers():
    """`ContextPolicy(...)` 的**定义点**只能出现在 `ai_infra/context.py`。

    防「某处又手搓一个策略对象」—— 那会让「唯一真源」变成口号。
    （业务侧只允许**引用**具名常量，不允许自己构造。）

    ★ 与 `test_budget_module_is_the_only_place_defining_tiers` 同一判据、
      不同对象：**「档案式」门禁要成组**，只钉住其中一个等于没钉
      （上一轮就是靠「按依赖名 grep 修越权必漏」吃过这个亏）。
    """
    offenders = []
    for f in [*_module_files(), BASE_AGENT_PY]:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "ContextPolicy"
            ):
                offenders.append(f"{f.relative_to(BACKEND)}:{n.lineno}")
    assert not offenders, (
        f"业务/基类侧自行构造了上下文策略: {offenders} —— "
        f"请引用 ai_infra.context 的具名档位"
    )


def test_context_file_shape_is_stable():
    """上下文真源文件本身的行尾不得漂（`ai_infra` 全仓 LF-only）。"""
    assert CONTEXT_PY.exists(), "ai_infra/context.py 不见了 —— 上下文真源被删"
    assert CONTEXT_PY.read_bytes().count(b"\r\n") == 0, (
        "ai_infra 全仓 LF-only 口径被破坏"
    )

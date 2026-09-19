"""运行预算门禁（第 145 轮 · 批 C5）。

对应 r141《Agent 能力缺口评审》批 C 的 C5：
    「`max_iterations` 三处硬编码 → 统一预算（迭代 / token / 墙钟），超限显式报错」

★ 本文件钉住的**安全属性**（不是实现细节）：

    P1 预算有**唯一真源**：`ai_infra/budget.py` 的 `AgentBudget`。
       业务侧只允许选**具名档位**，不允许再写裸数字。
    P2 预算有**三个维度**且**每个维度都真的会被判**（不是三个字段摆着好看）。
    P3 超限必须**显式**：`state["budget"]["truncated"]`（调用方读得到）
       + `_respond_node` 的 status 非 completed + 日志 ERROR。
       ★ 反面：此前只有一条 WARNING，图返回的 state 与「模型自己答完了」
       一模一样 —— 这是「静默」，不是「报错」。
    P4 墙钟在**入口层**抛 `BudgetExceeded`（该层没有部分结果可保）。
    P5 截断时的**善后不能丢**：清空 tool_calls（否则 orphan 被 400 拒）。
       ★ 这条同时被 `test_secretary_agent.py::test_max_iterations_strips_orphan_tool_calls`
       钉住 —— 两处判据不同、不是重复：那条防「清空被删」，本条防
       「清空了但没人知道」。

★ 反面（误报）也钉住了：模型**恰好在最后一轮正常答完**时不得标 truncated。
  否则「到顶」与「被截断」混为一谈，用户每次长会话都看到一句假警告。

反向注入对照（每条都能打穿本文件的某一条）：
    · 删 `check_budget` 的 tokens 分支           → A 组 token 用例转红
    · 删 `budget_state.update({...truncated})`    → B 组标记用例转红
    · 把 `_respond_node` 的 status 写死 completed → B 组终态用例转红
    · 去掉 `run_session` 的 `asyncio.timeout`     → C 组墙钟用例转红
    · 业务侧改回 `max_iterations=4`               → D 组形态门禁转红
    · `AgentBudget.__post_init__` 校验删掉        → A 组非法值用例转红
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BUDGET_PY = BACKEND / "ai_infra" / "budget.py"
BASE_AGENT_PY = BACKEND / "ai_infra" / "base_agent.py"
MODULES = BACKEND / "modules"

from ai_infra.base_agent import BaseAgent  # noqa: E402
from ai_infra.budget import (  # noqa: E402
    _BUDGET_FIELDS,  # noqa: PLC2701  (自检常量，供门禁直接引用)
    BUDGET_INTERACTIVE,
    BUDGET_ROUTER,
    DEFAULT_BUDGET,
    DIMENSIONS,
    AgentBudget,
    BudgetExceeded,
    BudgetVerdict,
    check_budget,
)


# ==================================================================== 工具
def _run_node(agent: BaseAgent, state: dict, ai: AIMessage) -> dict:
    """驱动 `_llm_call_node` 一次，LLM 返回给定的 AIMessage（不起真模型）。"""
    with patch.object(agent, "_llm_with_tools") as m:
        m.return_value.ainvoke = AsyncMock(return_value=ai)
        return asyncio.run(agent._llm_call_node(state))


def _orphan_ai(content: str = "try tool", usage: dict | None = None) -> AIMessage:
    """一个「想调工具」的 AIMessage（带可选 usage_metadata）。

    ★ `usage` 必须是**显式形参**，不能写成 `**usage` 再展开 —— 那样
      `_orphan_ai(usage_metadata={...})` 会拼出
      `usage_metadata={"usage_metadata": {...}}`，pydantic 立刻报缺 input_tokens
      （症状看起来像「LangChain 版本不兼容」，实际是自己的 kwarg 嵌套了一层）。
    """
    kw = {"usage_metadata": usage} if usage else {}
    return AIMessage(
        content=content,
        tool_calls=[{"name": "x", "args": {}, "id": "1"}],
        **kw,
    )


# ================================================== A 组 · 机制（budget 模块）
def test_budget_dimensions_match_dataclass_fields():
    """三维度名必须与 `AgentBudget` 的 `max_*` 字段**一一对应**。

    不对应的后果是**静默不生效**：`check_budget` 里 `getattr(budget, "max_x")`
    抛 AttributeError，而调用点通常吞异常 ⇒ 「新预算从不触发」且没有任何报错。
    """
    assert DIMENSIONS == ("iterations", "tokens", "seconds"), (
        f"维度名/顺序变了：{DIMENSIONS} —— 判定顺序是公开契约，改了要同步断言"
    )
    assert _BUDGET_FIELDS == {"max_" + d for d in DIMENSIONS}, (
        f"维度与字段不一致：{sorted(_BUDGET_FIELDS)}"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_iterations", 0),
        ("max_iterations", -1),
        ("max_tokens", 0),
        ("max_seconds", 0.0),
        ("max_iterations", True),  # bool 会被数值比较放过
        ("max_tokens", False),
    ],
)
def test_budget_rejects_non_positive_values(field, value):
    """非正预算必须 fail-fast —— 两种兜底都是假象。

    当「没有限制」= fail-open；当「立刻超限」= 静默删能力（症状与模型不听话重合）。
    """
    with pytest.raises(ValueError):
        AgentBudget(**{field: value})


def test_budget_rejects_empty_label():
    with pytest.raises(ValueError):
        AgentBudget(label="")


@pytest.mark.parametrize(
    "used,dimension",
    [
        ({"iterations": 4}, "iterations"),
        ({"tokens": 100}, "tokens"),
        ({"seconds": 10.0}, "seconds"),
    ],
)
def test_check_budget_flags_each_dimension_independently(used, dimension):
    """★ 每个维度都要**真的会被判**（不是三个字段摆着好看）。"""
    b = AgentBudget(max_iterations=4, max_tokens=100, max_seconds=10.0, label="unit")
    v = check_budget(used, b)
    assert v is not None and v.dimension == dimension, f"{used} 未被判超限：{v}"
    assert v.limit == getattr(b, "max_" + dimension)


def test_check_budget_returns_none_when_within():
    b = AgentBudget(max_iterations=4, max_tokens=100, max_seconds=10.0, label="unit")
    assert check_budget({}, b) is None
    assert check_budget({"iterations": 3, "tokens": 99, "seconds": 9.9}, b) is None
    # 缺省的维度视为「未消耗」，不得被当成 0 以外的值参与判定
    assert check_budget({"tokens": 1}, b) is None


def test_check_budget_uses_fixed_priority_order():
    """多维同时超限时必须报**固定**的那一个 —— 否则断言无法稳定。"""
    b = AgentBudget(max_iterations=4, max_tokens=100, max_seconds=10.0, label="unit")
    v = check_budget({"iterations": 9, "tokens": 999, "seconds": 99.0}, b)
    assert v.dimension == "iterations", "判定顺序漂了（DIMENSIONS 的顺序即优先级）"


def test_budget_is_frozen_and_derivation_isolated():
    """frozen + 派生不改原对象 —— 预算会被并发会话共享，可变即串账。"""
    b = AgentBudget(max_iterations=4, max_tokens=100, max_seconds=10.0, label="unit")
    d = b.with_max_iterations(2)
    assert (d.max_iterations, d.max_tokens, d.max_seconds, d.label) == (2, 100, 10.0, "unit")
    assert b.max_iterations == 4, "派生时被就地修改"
    with pytest.raises(Exception):
        b.max_iterations = 7  # type: ignore[misc]


def test_budget_exceeded_carries_verdict():
    v = BudgetVerdict(dimension="seconds", used=10.0, limit=10.0, label="unit")
    exc = BudgetExceeded(v)
    assert exc.verdict is v
    assert "seconds" in str(exc) and "unit" in str(exc)
    assert isinstance(exc, RuntimeError), "应为 RuntimeError 子类，便于既有 except 接住"


def test_tier_semantics_are_ordered():
    """档位语义：路由子层 < 多轮对话 < 默认。★ 这是「档位有名有实」的判据。"""
    assert BUDGET_ROUTER.label == "router"
    assert BUDGET_INTERACTIVE.label == "interactive"
    assert DEFAULT_BUDGET.label == "standard"
    assert (
        BUDGET_ROUTER.max_iterations
        < BUDGET_INTERACTIVE.max_iterations
        < DEFAULT_BUDGET.max_iterations
    ), "档位之间的迭代上限失去了区分度 —— 具名档位退化成三个一样的数"


# ==================================================== B 组 · 节点行为
def test_llm_call_node_truncation_is_marked_and_content_kept():
    """★ 超限时：既清 orphan tool_calls（善后），又留下**读得到的**截断标记。

    两条缺一不可：
      · 只清不标记 ⇒ 静默（用户以为答完了）
      · 只标记不清 ⇒ 下一轮 orphan tool_calls 被 DashScope 400
    """
    agent = BaseAgent(agent_name="gate", max_iterations=2)
    state = {
        "messages": [
            HumanMessage(content="q"),
            AIMessage(content="r1"),
            AIMessage(content="r2"),
        ]
    }
    out = _run_node(agent, state, _orphan_ai())

    ai_out = out["messages"][0]
    assert ai_out.tool_calls == [], f"orphan tool_calls 未清理: {ai_out.tool_calls}"
    assert ai_out.content == "try tool", "content 被误删（用户会看到空回答）"

    budget = out.get("budget") or {}
    assert budget.get("truncated") == "iterations", f"截断未显式标记: {budget}"
    assert budget.get("limit") == 2 and budget.get("used") == 3, f"结论缺 limit/used: {budget}"
    assert budget.get("message"), "结论缺少可直接转发给用户的文案"


def test_llm_call_node_token_truncation_is_marked():
    """token 维度必须独立生效 —— 否则「三维预算」只有一维是真的。"""
    agent = BaseAgent(agent_name="gate", budget=AgentBudget(max_tokens=5, label="tiny"))
    out = _run_node(
        agent,
        {"messages": [HumanMessage(content="q")]},
        _orphan_ai(usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}),
    )
    budget = out.get("budget") or {}
    assert budget.get("truncated") == "tokens", f"token 超限未标记: {budget}"
    assert budget.get("spent_tokens") == 30, f"耗用未累计: {budget}"
    assert out["messages"][0].tool_calls == [], "token 超限同样要清 orphan tool_calls"


def test_llm_call_node_does_not_flag_normal_finish():
    """★ 反面判据：计数到顶但模型**自己收尾**（无 tool_calls）⇒ 不得标 truncated。

    否则「到顶」与「被截断」混为一谈，长会话会持续刷假警告。
    """
    agent = BaseAgent(agent_name="gate", max_iterations=2)
    state = {
        "messages": [
            HumanMessage(content="q"),
            AIMessage(content="r1"),
            AIMessage(content="r2"),
        ]
    }
    out = _run_node(agent, state, AIMessage(content="done"))
    assert "truncated" not in (out.get("budget") or {}), (
        f"正常收尾被误判为截断: {out.get('budget')}"
    )
    # 未超限时也要保留 tool_calls（别把正常工具调用误清）
    ok = _run_node(
        BaseAgent(agent_name="gate2", max_iterations=10),
        {"messages": [HumanMessage(content="q")]},
        _orphan_ai(),
    )
    assert ok["messages"][0].tool_calls != [], "未超限却清空了 tool_calls —— 工具循环被打断"


def test_carried_tokens_reset_each_turn():
    """★ token 耗用按**轮**归零 —— `state["budget"]` 会随 checkpointer 跨轮持久化，
    不归零的话预算被历史越攒越多，健康会话聊到第 N 轮会突然被判超限。
    """
    st = {"budget": {"spent_tokens": 777}}
    assert BaseAgent._carried_tokens(st, iterations_done=0) == 0, "跨轮继承了上一轮的耗用"
    assert BaseAgent._carried_tokens(st, iterations_done=1) == 777, "本轮内未累计"
    assert BaseAgent._carried_tokens({}, iterations_done=3) == 0, "缺 budget 键时应为 0"


def test_respond_node_reports_budget_truncation():
    """终态结论必须区分「答完了」与「被预算截断」。"""
    agent = BaseAgent(agent_name="gate")
    out = asyncio.run(
        agent._respond_node(
            {
                "messages": [AIMessage(content="半截回答")],
                "budget": {"truncated": "iterations", "limit": 4, "used": 4, "message": "已达上限"},
            }
        )
    )
    sr = out["structured_response"]
    assert sr["status"] == "budget_truncated", f"截断被报成成功: {sr['status']}"
    assert sr["budget"]["truncated"] == "iterations"
    assert sr["budget"]["reason"], "缺少原因文案"
    assert sr["message"] == "半截回答", "截断时的已产出内容被丢弃"


def test_respond_node_keeps_completed_when_no_truncation():
    agent = BaseAgent(agent_name="gate")
    out = asyncio.run(agent._respond_node({"messages": [AIMessage(content="ok")]}))
    assert out["structured_response"]["status"] == "completed"
    assert "budget" not in out["structured_response"], "正常完成时不应夹带预算结论"


# ==================================================== C 组 · 入口层墙钟
class _SlowGraph:
    async def ainvoke(self, state, config=None):
        await asyncio.sleep(3)


class _SlowStream:
    async def astream_events(self, state, config=None, version="v2"):
        await asyncio.sleep(3)
        yield {"event": "never"}


class _FastGraph:
    async def ainvoke(self, state, config=None):
        return {"messages": [], "ok": True}


def test_run_session_enforces_wall_clock():
    """★ 墙钟预算必须**真的**在入口层生效（超时即失败，不静默返回半截）。"""
    agent = BaseAgent(agent_name="gate", budget=AgentBudget(max_seconds=0.05, label="tiny"))
    agent.graph_for_session = lambda *a, **k: (_SlowGraph(), {})  # type: ignore[assignment]
    with pytest.raises(BudgetExceeded) as ei:
        asyncio.run(agent.run_session({"messages": []}))
    assert ei.value.verdict.dimension == "seconds"
    assert ei.value.verdict.label == "tiny", "档位不可追溯 ⇒ 日志里查不出是哪档超的"


def test_stream_session_enforces_wall_clock():
    agent = BaseAgent(agent_name="gate", budget=AgentBudget(max_seconds=0.05, label="tiny"))
    agent.graph_for_session = lambda *a, **k: (_SlowStream(), {})  # type: ignore[assignment]

    async def _drain():
        async for _ev in agent.stream_session({"messages": []}):
            pass

    with pytest.raises(BudgetExceeded) as ei:
        asyncio.run(_drain())
    assert ei.value.verdict.dimension == "seconds"


def test_entry_does_not_break_normal_fast_path():
    """正常（未超时）路径不得被墙钟误伤。"""
    agent = BaseAgent(agent_name="gate", budget=AgentBudget(max_seconds=5.0, label="ok"))
    agent.graph_for_session = lambda *a, **k: (_FastGraph(), {})  # type: ignore[assignment]
    got = asyncio.run(agent.run_session({"messages": []}))
    assert got.get("ok") is True


# ==================================================== D 组 · 形态门禁
def _module_files() -> list[pathlib.Path]:
    return sorted(p for p in MODULES.rglob("*.py") if "__pycache__" not in p.parts)


def test_max_iterations_is_derived_not_assigned():
    """`max_iterations` 必须是**派生视图**（读 `self.budget`），不得自立门户。

    ★ 反面：既留形参又留实例属性 = 两份真源，「档位说 4、属性说 10」时
    没人说得清哪个生效。

    ★ 本用例的**两段判据缺一不可**（第二段是自查时补上的盲区）：
      ① 形态：它是 property、且没有 `self.max_iterations = ...` 赋值。
         —— 只靠这段会漏掉「property 名存实亡」：`return 10` 也能通过。
      ② 行为：换档位/换形参必须给出**不同**的结果。
         反向注入 `return 10` ⇒ ① 仍绿、② 转红 ⇒ 证明②不是冗余。
    """
    assert isinstance(BaseAgent.__dict__.get("max_iterations"), property), (
        "max_iterations 不再是 property —— 预算的真源可能被架空"
    )
    # ② 行为判据：真的读预算（而不是返回常量）
    assert BaseAgent(budget=BUDGET_ROUTER).max_iterations == BUDGET_ROUTER.max_iterations
    assert BaseAgent(max_iterations=3).max_iterations == 3
    assert BaseAgent().max_iterations == DEFAULT_BUDGET.max_iterations

    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    assigns = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and t.attr == "max_iterations":
                    assigns.append(n.lineno)
    assert not assigns, f"base_agent.py 又出现对 self.max_iterations 的赋值（行 {assigns}）"


def test_business_modules_do_not_hardcode_max_iterations():
    """★★★ 核心门禁：业务侧不得再出现 `max_iterations=` 裸数字。

    对应 r141 的「三处硬编码 → 统一预算」。新增一个 Agent 时若顺手写
    `max_iterations=5`，这条会红 —— 逼着作者去选一个**具名档位**
    （或先给档位表加一档），从而让「为什么是这个数」有地方可写。

    ★ 只扫 `modules/`（业务侧）。`ai_infra/budget.py` 里的
    `AgentBudget(max_iterations=4, ...)` 是**真源本身**，不算违规。
    """
    bad = []
    for f in _module_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg == "max_iterations":
                        bad.append(f"{f.relative_to(BACKEND)}:{n.lineno}")
    assert not bad, (
        f"业务侧出现 max_iterations 硬编码: {bad} —— 请改用 ai_infra.budget 的具名档位"
        f"（BUDGET_ROUTER / BUDGET_INTERACTIVE / BUDGET_STANDARD）"
    )


@pytest.mark.parametrize(
    "rel,expect",
    [
        ("secretary/agent.py", "BUDGET_INTERACTIVE"),
        ("listing_generator/agent_listing.py", "BUDGET_ROUTER"),
        ("product_research/agent_product_research.py", "BUDGET_ROUTER"),
    ],
)
def test_agent_workloads_use_the_matching_tier(rel, expect):
    """三处改造的落点必须仍然是**具名档位**（而非被改回数字或换错档）。"""
    src = (MODULES / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {
        kw.value.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg == "budget" and isinstance(kw.value, ast.Name)
    }
    assert expect in names, f"{rel} 未使用 {expect}（实际 budget= 取到 {sorted(names)}）"


def test_budget_module_is_the_only_place_defining_tiers():
    """`AgentBudget(...)` 的**定义点**只能出现在 `ai_infra/budget.py`。

    防「某处又手搓一个预算对象」—— 那会让「唯一真源」变成口号。
    （业务侧只允许**引用**具名常量，不允许自己构造。）
    """
    offenders = []
    for f in [*_module_files(), BASE_AGENT_PY]:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "AgentBudget"
            ):
                offenders.append(f"{f.relative_to(BACKEND)}:{n.lineno}")
    assert not offenders, (
        f"业务/基类侧自行构造了预算对象: {offenders} —— 请引用 ai_infra.budget 的具名档位"
    )


def test_budget_file_shape_is_stable():
    """预算真源文件本身的行尾/位置不得漂（它是被引用方，路径即契约）。"""
    assert BUDGET_PY.exists(), "ai_infra/budget.py 不见了 —— 预算真源被删"
    blob = BUDGET_PY.read_bytes()
    assert blob.count(b"\r\n") == 0, "ai_infra 全仓 LF-only 口径被破坏"

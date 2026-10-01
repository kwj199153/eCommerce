# -*- coding: utf-8 -*-
"""「上一轮是不是追问」判定 + review_analyst 让路 的门禁（第 250 轮 · 遗留项 A）。

## 这个文件补的是什么

实测复现（第 249 轮，老板亲测）：

    老板：帮我做个行动计划
    系统：你想基于哪一期？（周报 / 月报 / 广告 / 商品表现 …）   ← 工具环路的 LLM 在**追问**
    老板：基于月报
    系统：<直接吐出一份月报卡>                                   ← 行动计划从未产出

根因是**结构性**的，不是某一处写漏：追问的问句与答案用的是**同一批词**
（问「周报还是月报」，答案里必然含「月报」）⇒ 任何**纯关键词**判定都躲不开。
唯一的出路是让判定带上**会话级状态**：「上一轮是不是在追问」。

## 本文件钉住的五件事

1. `test_pure_judgment_*` —— 纯判定 `BaseAgent.previous_turn_was_clarification`
   的语义：**有回复但零工具 = 追问；调过工具 = 在干活**。
2. `test_judgment_has_a_single_implementation` —— 形态（AST，不是字符串包含）：
   全仓「上一轮是不是追问」的实现**只有一份**，住在 `ai_infra/base_agent.py`。
3. `test_read_shell_is_read_only` —— ★ 只读性：薄壳只许 `aget_state`，
   绝不许 `ainvoke` / `astream` / `astream_events` / `run_session` / `stream_session`。
   （它在「决定走哪条路」时被调用；顺手推一次图 = 把老板这轮问题先跑一遍再跑一遍。）
4. `test_review_analyst_defers_on_clarification` + 四条行为用例 ——
   命中关键词时，上一轮是追问 ⇒ **让路给工具环路**；工具环路没接住 ⇒
   **退回原直连**（「不许比改造前更差」）。
5. `test_wired_agents_ratchet` —— 棘轮：今天只有 `review_analyst` 接了线。
   ★ 横向铺开到第 2 家时必须**同步改这个集合** —— 否则新接的家等于门禁真空区
   （本仓第 166 轮 `#726` 的原话：只补 agent 不进名单，就是新开一处真空区）。

## 反向注入

改坏了必须转红，否则本文件是在空跑 —— 见
`scripts/probe_250_clarification_answer.py`（注入 + 声明红集比对）。
"""
from __future__ import annotations

import ast
import pathlib
import warnings

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: ★ `tests` 在跳过名单里：本门的范围是**生产件** —— 本文件自己会定义
#: `_StubRouter.last_turn_was_clarification`（假替身，名字必须与真实接口一致），
#: 若不跳过就会被自己的替身判成「第二份实现」。同 `tests/test_intent_single_source.py`。
SCAN_SKIP_DIRS = {
    "tests", ".venv", "__pycache__", "node_modules", ".git", "logs", "data",
    ".pytest_cache", "_attic", ".mypy_cache", "htmlcov",
}

JUDGMENT = "previous_turn_was_clarification"
SHELL = "last_turn_was_clarification"

#: 判定 + 薄壳的**唯一**住所
HOME_REL = "ai_infra/base_agent.py"

#: ★ 棘轮：已接线「上一轮是追问 ⇒ 让路」的业务 Agent（今天恰好 1 家）。
#:   横向铺开时同步加这里 —— 漏加 = 新家没门禁。
WIRED_AGENTS = {"modules/review_analyst/agent.py"}

REVIEW_REL = "modules/review_analyst/agent.py"


# ============================================================
# 扫描器（纯函数，接受源码串 ⇒ 真实判据与自检共用同一份实现）
# ============================================================


def _parse(src: str):
    """`ast.parse` 并压掉 `SyntaxWarning`。

    ★ 为什么要压：本仓 `alembic/versions/b8d4e2f6c3a5_memory_tables.py` 里有非法
      转义序列（**既有问题**，非本轮引入），`ast.parse` 会往 stderr 吐
      `SyntaxWarning`。它不影响判定，但会让门禁输出带噪 —— 噪声会让真红被忽略。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(src)


def defs_named(src: str, name: str):
    """源码里所有名为 `name` 的函数/方法定义行号。

    ★ 走 AST 而**不是** `"def name" in src`：docstring 里提一句就会骗过字符串判据，
      那是本仓咬过的「假绿」形态。
    """
    tree = _parse(src)
    return sorted(
        n.lineno for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


def attr_calls(src: str, attr: str):
    """源码里所有 `*.attr(...)` 形态的**调用点**（返回 unparse 后的表达式）。

    ★ 属性**读取**（`x = o.f`）不算调用 —— 否则「声明」会被误判成「使用」。
    """
    tree = _parse(src)
    return sorted(
        ast.unparse(n.func) for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == attr
    )


def _find_fn(src: str, fn_name: str):
    tree = _parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            return n
    return None


def call_counts_inside(src: str, fn_name: str):
    """`fn_name` 函数体内每个被调表达式的**出现次数**；找不到函数返回 None。"""
    fn = _find_fn(src, fn_name)
    if fn is None:
        return None
    out: dict = {}
    for c in ast.walk(fn):
        if isinstance(c, ast.Call):
            k = ast.unparse(c.func)
            out[k] = out.get(k, 0) + 1
    return out


def _iter_py():
    for path in sorted(BACKEND.rglob("*.py")):
        rel_parts = path.relative_to(BACKEND).parts
        if any(p in SCAN_SKIP_DIRS or p.startswith(".pytest-tmp") for p in rel_parts):
            continue
        yield path.relative_to(BACKEND).as_posix(), path


def _read(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8", errors="replace")


def _defs_safe(src: str, name: str):
    try:
        return defs_named(src, name)
    except SyntaxError:
        return []


def _attr_calls_safe(src: str, attr: str):
    try:
        return attr_calls(src, attr)
    except SyntaxError:
        return []


# ============================================================
# 1. 纯判定的语义
# ============================================================


def test_pure_judgment_no_previous_turn_means_false():
    """没有「上一轮」（首轮 / 空历史）⇒ 不是追问。"""
    assert BaseAgent.previous_turn_was_clarification([]) is False
    assert BaseAgent.previous_turn_was_clarification(None) is False
    one_turn = [HumanMessage(content="帮我做个行动计划")]
    assert BaseAgent.previous_turn_was_clarification(one_turn) is False


def test_pure_judgment_reply_without_tools_is_clarification():
    """★ 核心场景：上一轮**有回复、零工具** ⇒ 它在问话。"""
    messages = [
        HumanMessage(content="帮我做个行动计划"),
        AIMessage(content="你想基于哪一期？周报还是月报？"),
        HumanMessage(content="基于月报"),
    ]
    assert BaseAgent.previous_turn_was_clarification(messages) is True


def test_pure_judgment_tool_call_means_not_clarification():
    """★ 反面：只要上一轮调过工具，它就是在干活（哪怕最后补了句说明）。"""
    messages = [
        HumanMessage(content="本周周报"),
        AIMessage(
            content="",
            tool_calls=[{"name": "weekly_report", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"summary": "本期 GMV 环比 +12.3%"}', tool_call_id="c1"),
        AIMessage(content="本期 GMV 环比 +12.3%，广告 ACoS 偏高。"),
        HumanMessage(content="那月报呢"),
    ]
    assert BaseAgent.previous_turn_was_clarification(messages) is False


def test_pure_judgment_tool_result_alone_is_not_clarification():
    """只有工具往返、没有最终文字 ⇒ 也不是追问（它在干活，只是没多说一句）。"""
    messages = [
        HumanMessage(content="q"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}]),
        ToolMessage(content="{}", tool_call_id="c1"),
        HumanMessage(content="再问"),
    ]
    assert BaseAgent.previous_turn_was_clarification(messages) is False


def test_pure_judgment_only_the_immediately_previous_turn_counts():
    """★ 只看**紧邻**的上一轮：更早那轮的追问不该一直生效。"""
    messages = [
        HumanMessage(content="q1"),
        AIMessage(content="你指的是哪一期？"),                       # 更早的追问
        HumanMessage(content="月报"),
        AIMessage(content="", tool_calls=[{"name": "monthly_review", "args": {}, "id": "c9"}]),
        ToolMessage(content="{}", tool_call_id="c9"),
        HumanMessage(content="那库存呢"),                            # 上一轮在干活
    ]
    assert BaseAgent.previous_turn_was_clarification(messages) is False


def test_pure_judgment_empty_ai_content_is_not_a_reply():
    """`AIMessage` 存在但内容为空 ⇒ 不算「有回复」（工具调用轮常见形态）。"""
    messages = [
        HumanMessage(content="q"),
        AIMessage(content=""),
        HumanMessage(content="再问"),
    ]
    assert BaseAgent.previous_turn_was_clarification(messages) is False


def test_pure_judgment_does_not_hard_depend_on_langchain_types():
    """★ 判定按**类名**兜底（同 `tool_activity_in_turn` 的口径）。

    为什么：这一层要能用「没装 langchain 的裸消息对象」验；且与同族的
    `tool_activity_in_turn` / `_iterations_in_current_turn` 保持同一套识别方式
    （三份口径若不一致，多轮会话里会指向不同的两段 —— 而不会报错）。
    """

    class HumanMessage:  # noqa: N801  (故意同名，验类名兜底)
        def __init__(self, content):
            self.content = content

    class AIMessage:  # noqa: N801
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    duck = [
        HumanMessage("帮我做个行动计划"),
        AIMessage("你想基于哪一期？"),
        HumanMessage("基于月报"),
    ]
    assert BaseAgent.previous_turn_was_clarification(duck) is True


# ============================================================
# 2. 判定只有一份实现（AST 形态，非字符串包含）
# ============================================================


def test_judgment_has_a_single_implementation():
    """★ 全仓「上一轮是不是追问」的判定**只有一份**，住在 `ai_infra/base_agent.py`。"""
    found = {}
    for rel, path in _iter_py():
        lines = _defs_safe(path.read_text(encoding="utf-8", errors="replace"), JUDGMENT)
        if lines:
            found[rel] = lines
    assert list(found) == [HOME_REL], (
        f"「上一轮是不是追问」的实现出现在 {list(found)} —— "
        f"应只有一份（{HOME_REL}）。多份实现 ⇒ 至少一份永远测不到。"
    )
    assert len(found[HOME_REL]) == 1, f"{HOME_REL} 里定义了多次：{found[HOME_REL]}"


def test_read_shell_has_a_single_definition():
    """薄壳同样只有一份（否则调用方各自读 state，口径会漂）。"""
    found = sorted(
        rel for rel, path in _iter_py()
        if _defs_safe(path.read_text(encoding="utf-8", errors="replace"), SHELL)
    )
    assert found == [HOME_REL], f"{SHELL} 定义在 {found}，应只有 {HOME_REL}"


# ============================================================
# 3. ★ 只读性：薄壳绝不许推进图
# ============================================================


def test_read_shell_is_read_only():
    """★ 薄壳只许 `aget_state`；`ainvoke` / `astream*` / `run_session` 一律禁止。

    理由：它在「决定这一轮走哪条路」时被调用。若它顺手推一次图，等于把老板这一轮
    的问题**先执行一遍**再执行一遍 —— 两次写的是同一个 thread。范式同
    `modules/secretary/agent.py` 的 `current_plan()`
    （`test_secretary_plan_read.py` 钉着「只 `aget_state`、不 `ainvoke`」）。
    """
    counts = call_counts_inside(_read(HOME_REL), SHELL)
    assert counts is not None, f"{HOME_REL} 里找不到 {SHELL}"
    assert counts.get("graph.aget_state") == 1, (
        f"{SHELL} 里 `graph.aget_state` 出现 {counts.get('graph.aget_state')} 次"
        f"（应为 1）—— 读不到上一轮时判定恒 False（静默失效）"
    )
    forbidden = {
        "graph.ainvoke", "graph.astream", "graph.astream_events",
        "self.run_session", "self.stream_session",
        "run_session", "stream_session",
    }
    bad = sorted(k for k in counts if k in forbidden)
    assert not bad, f"{SHELL} 里出现了推进图/会话的调用 {bad} —— 只读口不得有副作用"
    assert counts.get("self.previous_turn_was_clarification") == 1, (
        f"{SHELL} 没有复用唯一判定 ⇒ 出现了第二份实现"
    )


def test_read_shell_refuses_without_session_or_identity():
    """★ 无会话 / 无身份必须**早退**为 False。

    为什么不能靠「先算 thread_id 再读」顶过去：本仓 `thread_id` 由
    `ns:user:session` 拼成，**空段会被跳过**（见 `resolve_thread_id`）。若把空
    session / 空 user 放行，拼出来的键会退化成 `ns:session` 甚至裸 `session` ——
    那读到的可能是**别人的上一轮**。早退 = 在拿到键之前就把这条路断掉。
    """
    fn = _find_fn(_read(HOME_REL), SHELL)
    assert fn is not None, f"找不到 {SHELL}"
    guards = [
        (ast.unparse(n.test), [ast.unparse(b) for b in n.body])
        for n in ast.walk(fn) if isinstance(n, ast.If)
    ]
    hit = [g for g in guards
           if "session_id" in g[0] and "user_id" in g[0] and g[1] == ["return False"]]
    assert hit, (
        f"{SHELL} 没有「缺 session_id / user_id ⇒ 直接 return False」的早退守卫；"
        f"现有分支：{guards}"
    )


async def test_read_shell_is_false_without_a_checkpointer():
    """运行期：**没绑 checkpointer** 的实例（如主 Agent 实例）读出来必须 False，且不抛。

    这正是 `review_analyst` 主实例的处境 —— 会话状态寄存在路由子层上。此判据钉住
    「问错实例时不会炸、只是恒 False」（静默失效方向，见 §4 的第二条形态判据）。
    """
    agent = BaseAgent(agent_name="probe-250-clarification-shell")
    assert agent.checkpointer is None, "该实例本应没绑 checkpointer，夹具前提不成立"
    assert await agent.last_turn_was_clarification("s1", "u1") is False
    assert await agent.last_turn_was_clarification(None, None) is False


# ============================================================
# 4. review_analyst 接线（形态）
# ============================================================


def test_review_analyst_defers_on_clarification():
    """形态判据：命中关键词时有「先问上一轮」这一步，且保留退回直连的兜底。"""
    src = _read(REVIEW_REL)
    counts = call_counts_inside(src, "invoke")
    assert counts is not None, "review_analyst 没有 invoke"

    asked = counts.get("router.last_turn_was_clarification", 0)
    assert asked == 1, (
        f"invoke 问「上一轮是不是追问」{asked} 次（应为 1）⇒ 遗留项 A 未接线或重复读"
    )

    # ★ 「不许比改造前更差」：`self._run_one` 至少两处 —— 短路点 + 追问兜底点。
    n_run_one = counts.get("self._run_one", 0)
    assert n_run_one >= 2, (
        f"invoke 里 `self._run_one` 只有 {n_run_one} 处 ⇒ "
        "追问让路后没有「工具环路没接住就退回直连」的兜底，会退化"
    )
    assert counts.get("self._route_via_tools", 0) >= 1, "让路的去处（工具环路）不在 invoke 里"

    # ★ 让路必须**有条件**：读不到就不让路（不能无条件让路 ⇒ 每次都多一次 LLM 往返）
    tree = _parse(src)
    guards = [
        ast.unparse(n.test) for n in ast.walk(tree)
        if isinstance(n, ast.If) and "defer_to_tools" in ast.unparse(n.test)
    ]
    assert guards, "没有以 `defer_to_tools` 为条件的分支 ⇒ 让路是无条件的"


def test_review_analyst_asks_the_instance_that_actually_runs_the_graph():
    """★ 必须问**跑图的那个实例**（`router`），不是 `self`。

    本仓的 `review_analyst` 把会话状态寄存在一个**组合出来的路由子层**上
    （`_build_router()` 里 new 的 `BaseAgent`），主实例自己没绑 checkpointer ⇒
    对它调恒得 False。**形态上**钉住接收者，否则「问了但问错对象」会静默失效。
    """
    counts = call_counts_inside(_read(REVIEW_REL), "invoke")
    assert "router.last_turn_was_clarification" in counts
    assert "self.last_turn_was_clarification" not in counts, (
        "主实例没绑 checkpointer ⇒ 对它读恒得 False（静默失效：看着接了线、其实从不生效）"
    )


# ============================================================
# 4b. review_analyst 接线（行为：四条真实路径）
# ============================================================


class _StubRouter:
    """假路由子层：只回答「上一轮是不是追问」。"""

    def __init__(self, was_clarification: bool):
        self._was = was_clarification
        self.asked = 0

    async def last_turn_was_clarification(self, session_id, user_id=None) -> bool:
        self.asked += 1
        return self._was


def _direct_result():
    import modules.review_analyst.agent as ra
    from modules.review_analyst.schemas import ReviewChatResult

    return ReviewChatResult(
        reply="直连结果",
        display_type=ra.REVIEW_REPORT_DISPLAY_TYPE,
        data={"summary": "直连结果"},
    )


def _routed_result():
    import modules.review_analyst.agent as ra
    from modules.review_analyst.schemas import ReviewChatResult

    return ReviewChatResult(
        reply="按你的行动计划来",
        display_type=ra.REVIEW_REPORT_DISPLAY_TYPE,
        data={"summary": "计划"},
    )


async def _drive(monkeypatch, *, was_clarification, route_result, session_id="s1", user_id="u1"):
    """把 invoke 的三条出口打桩，回放「命中关键词」这一条路。"""
    import modules.review_analyst.agent as ra

    agent = ra.ReviewAnalystAgent()
    router = _StubRouter(was_clarification)
    calls: list = []

    monkeypatch.setattr(agent, "_get_router", lambda: router)

    async def _fake_run_one(intent, context=None):
        calls.append(f"run_one:{intent}")
        return _direct_result()

    async def _fake_route(query, context=None, session_id=None, user_id=None):
        calls.append("route")
        return route_result

    monkeypatch.setattr(agent, "_run_one", _fake_run_one)
    monkeypatch.setattr(agent, "_route_via_tools", _fake_route)

    res = await agent.invoke(
        "基于月报", session_id=session_id, user_id=user_id, shop_id="store_probe_250"
    )
    return res, calls, router


async def test_keyword_hit_still_short_circuits_normally(monkeypatch):
    """★ 未命中「上一轮是追问」⇒ 行为与改造前**逐字等价**：直接命中直连。"""
    res, calls, router = await _drive(
        monkeypatch, was_clarification=False, route_result=_routed_result()
    )
    assert calls == ["run_one:monthly_review"], (
        f"上一轮不是追问却走了别的路：{calls} —— 关键词短路的性能优势被无条件牺牲"
    )
    assert res.reply == "直连结果"
    assert router.asked == 1


async def test_answer_to_clarification_defers_to_tools(monkeypatch):
    """★★ 核心修复：上一轮是追问 ⇒ 答案**让路给工具环路**（它带着问句，判得准）。"""
    res, calls, router = await _drive(
        monkeypatch, was_clarification=True, route_result=_routed_result()
    )
    assert calls == ["route"], f"上一轮是追问却仍然短路成月报卡：{calls} —— 遗留项 A 没修好"
    assert res.reply == "按你的行动计划来"


async def test_answer_to_clarification_falls_back_when_tools_miss(monkeypatch):
    """★ 「不许比改造前更差」：工具环路没接住 ⇒ **退回原关键词直连**。"""
    res, calls, router = await _drive(monkeypatch, was_clarification=True, route_result=None)
    assert calls == ["route", "run_one:monthly_review"], (
        f"工具环路没接住时没有退回直连：{calls} —— 老板的答案会变成一句引导语"
    )
    assert res.reply == "直连结果"


async def test_no_session_never_defers(monkeypatch):
    """★ 无会话 ⇒ 读不到 ⇒ **不让路**（拿不到证据就不引入新行为）。"""
    res, calls, router = await _drive(
        monkeypatch,
        was_clarification=True,
        route_result=_routed_result(),
        session_id=None,
        user_id=None,
    )
    assert calls == ["run_one:monthly_review"], (
        f"没有会话却让了路：{calls} —— 读数来源不明，行为不可解释"
    )
    assert router.asked == 0, "没有会话却去读了 state"


async def test_no_identity_never_defers(monkeypatch):
    """★ 有会话但**无身份** ⇒ 同样读不到（thread_id 缺一段）⇒ 不让路。"""
    _res, calls, router = await _drive(
        monkeypatch,
        was_clarification=True,
        route_result=_routed_result(),
        session_id="s1",
        user_id=None,
    )
    assert calls == ["run_one:monthly_review"], f"无身份却让了路：{calls}"
    assert router.asked == 0


# ============================================================
# 5. 棘轮：今天只接了 review_analyst 一家
# ============================================================


def test_wired_agents_ratchet():
    """★ 已接线的 Agent 集合必须与 `WIRED_AGENTS` 一致。

    横向铺开（第 2、3 家）时**必须同步改这里** —— 漏改就是新开一处门禁真空区
    （本仓第 166 轮 `#726` 的原话）。双向比较：
      · 只声明不接线 ⇒ 门禁虚设（左差集）；
      · 接了线却不声明 ⇒ 新家没被覆盖（右差集）。
    """
    actual = set()
    for rel, path in _iter_py():
        src = path.read_text(encoding="utf-8", errors="replace")
        if _attr_calls_safe(src, SHELL):
            actual.add(rel)
    assert actual == WIRED_AGENTS, (
        f"接线集合与声明不一致：实际 {sorted(actual)}，声明 {sorted(WIRED_AGENTS)}。"
        f"横向铺开时同步更新 WIRED_AGENTS。"
    )


# ============================================================
# 6. 门禁非空跑自检
# ============================================================


def test_gate_is_not_vacuous():
    """★ 反向注入：每条扫描器对「违规样本」都必须报，对「干净样本」不得误报。"""
    # ① 定义扫描：docstring 里提到名字**不算**定义（防字符串判据的假绿）
    fake = f'"""说明：见 {JUDGMENT}()。"""\nx = 1\n'
    assert defs_named(fake, JUDGMENT) == [], "docstring 被误判成函数定义"
    # ② 该样本确实含那个串 —— 证明 ① 不是空跑
    assert JUDGMENT in fake, "样本本身没含该串，① 没有证明力"

    # ③ 定义扫描：真定义必须报（含 async）
    assert defs_named(f"async def {JUDGMENT}(messages):\n    return False\n", JUDGMENT) == [1]

    # ④ 只读性扫描：`ainvoke` 必须被看见
    bad_shell = (
        f"async def {SHELL}(self, s, u=None):\n"
        "    graph, cfg = self.graph_for_session(s, u)\n"
        "    return await graph.ainvoke({}, config=cfg)\n"
    )
    bad_counts = call_counts_inside(bad_shell, SHELL)
    assert "graph.ainvoke" in bad_counts, "只读性扫描漏掉 ainvoke"
    assert "graph.aget_state" not in bad_counts

    ok_shell = (
        f"async def {SHELL}(self, s, u=None):\n"
        "    graph, cfg = self.graph_for_session(s, u)\n"
        "    snap = await graph.aget_state(cfg)\n"
        "    return self.previous_turn_was_clarification(snap.values)\n"
    )
    ok_counts = call_counts_inside(ok_shell, SHELL)
    assert ok_counts["graph.aget_state"] == 1 and "graph.ainvoke" not in ok_counts

    # ⑤ 调用点扫描：`*.attr(...)` 形态才叫调用（属性读取不算）
    assert attr_calls("x = o.f(1)\n", "f") == ["o.f"], "调用点扫描漏报"
    assert attr_calls("x = o.f\n", "f") == [], "属性读取被误判成调用"

    # ⑥ 次数统计：同一调用出现两次必须数成 2（防「只认存在、不认条数」）
    assert call_counts_inside("def g():\n    a.b()\n    a.b()\n", "g")["a.b"] == 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))

"""自主规划器门禁（第 148 轮 · 批 C3）。

对应 r141《Agent 能力缺口评审》批 C 的 C3：
    「新增 `plan_tasks` / `update_task` 工具（todo 外置落库），子任务状态可在 UI 展示」
以及 §三 的验收口径：
    「todo 清单**外置**为状态，跨上下文压缩存活；提供『先规划后执行』的模式」

★ 本文件钉住的**安全属性**（不是实现细节）：

    P1 计划**不在消息序列里**。`state["todos"]` 与 `messages` 是两条独立载体 ——
       这是「跨上下文压缩存活」的**唯一**机制（第 147 轮批 C4 的裁剪只作用于
       `messages`）。若哪天有人把计划改回塞进 messages，D/F 组会红。
    P2 计划**必须每轮重新注入** system prompt（`_system_prompt_with_plan`），
       否则它在 state 里、模型却看不见 —— 表现为「模型明明有计划却重新规划一遍」。
    P3 两个工具返回 `Command` 时**必须**同时回 `ToolMessage`。实测：缺了它
       LangGraph 的 ToolNode 直接抛
       `ValueError: Expected to have a matching ToolMessage in Command.update`
       —— 因为「每个 tool_call 都要有 ToolMessage 回应」是 OpenAI 兼容 API 的硬约束。
    P4 规划工具是**只写本地 state**（`LOCAL_STATE_METADATA`）⇒ 免 HITL 审批。
       但它**不是自由通道**：声明 local_state 的工具名必须在受控集合
       `LOCAL_STATE_TOOL_NAMES` 里（独立第二判据，防「给真写库工具挂 local_state
       以躲开审批」）。
    P5 术语无第二份真源：`TASK_STATUSES` / `TaskStatus`(Literal) / `STATUS_MARKS`
       三者取值集合必须逐字相等；`PLANNER_TOOL_NAMES` 与 `planner_tools` 实际名字、
       与 `side_effects.LOCAL_STATE_TOOL_NAMES` 三处必须对账。
    P6 业务侧的 `plan` 必须是**真消费者**：`structured_response.plan` 在全仓
       生产代码里 0 个消费者（r141 §2.5 记为「死输出」）⇒ 计划改从
       `route()` 的返回值 / `OrchestratorResponse.plan` 透出。

★ 反面（误报）也钉住：**关闭规划时一行注入都不能有** —— `_system_prompt_with_plan`
  必须原样返回业务 prompt（否则「默认关」这个开关是假的）。

反向注入对照（每条都应打穿本文件的某一条 —— 实测见第 148 轮记录）：
    · `plan_tasks` 只返回 `Command(update={"todos": …})`（去掉 ToolMessage） → D/F 组转红
    · 把 `update_task` 的 metadata 从 LOCAL_STATE 改成 READ_ONLY           → C 组转红
    · 把 `update_shop_config` 之类真写库工具挂上 LOCAL_STATE_METADATA      → C 组转红
    · 往 `LOCAL_STATE_TOOL_NAMES` 里塞第三个名字                          → B 组转红
    · `TaskStatus` 里删掉一个取值（与 TASK_STATUSES 不再相等）             → B 组转红
    · `_system_prompt_with_plan` 在关闭时也注入 GUIDE                      → F 组转红
    · 计划改成写进 messages（不再进 state）                               → E/F 组转红
    · `route()` 不再读 `TODOS_STATE_KEY`（计划不落盘/不透出）              → G 组转红
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import typing
from typing import Annotated
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import InjectedState, ToolNode
from langgraph.types import Command

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PLAN_PY = BACKEND / "ai_infra" / "plan.py"
BASE_AGENT_PY = BACKEND / "ai_infra" / "base_agent.py"
SIDE_EFFECTS_PY = BACKEND / "ai_infra" / "tools" / "side_effects.py"
MODULES = BACKEND / "modules"

from ai_infra.base_agent import AgentState, BaseAgent  # noqa: E402
from ai_infra.plan import (  # noqa: E402
    MAX_TODO_CHARS,
    MAX_TODO_ITEMS,
    PLANNER_TOOL_NAMES,
    PLANNING_GUIDE,
    STATUS_MARKS,
    TASK_STATUSES,
    TODOS_STATE_KEY,
    TodoItem,
    TaskStatus,
    apply_status,
    build_plan,
    normalize_todos,
    plan_summary,
    planner_tools,
    render_plan_block,
)
from ai_infra.tools.side_effects import (  # noqa: E402
    LOCAL_STATE_METADATA,
    LOCAL_STATE_TOOL_NAMES,
    READ_ONLY_METADATA,
    declared_local_state,
    derive_hitl_tools,
    is_declared,
    local_state_violations,
    write_verb_violations,
)


def _by_name(name: str):
    return next(t for t in planner_tools if t.name == name)


# ================================================== A 组 · 机制（纯函数）
def test_tool_set_matches_declared_names():
    """`planner_tools` 的实际名字与 `PLANNER_TOOL_NAMES` 必须逐字一致（P5）。"""
    assert tuple(t.name for t in planner_tools) == tuple(PLANNER_TOOL_NAMES)


def test_build_plan_drops_blanks_and_renumbers_ids():
    """空串被丢弃、id 按顺序重排 `t1..tN`、状态全 pending。

    ★ id 是**定位键**（`update_task` 按它找对象）。不重排的话，模型按
      「第 2 条」理解、实现按「数组下标」理解，两边一漂移就改错条目 ——
      而且不报错。
    """
    plan = build_plan(["第一步", "   ", "", "第二步"])
    assert [t.id for t in plan] == ["t1", "t2"]
    assert [t.content for t in plan] == ["第一步", "第二步"]
    assert all(t.status == "pending" for t in plan)
    assert all(t.note == "" for t in plan)


def test_build_plan_caps_items_and_truncates_content():
    """超量/超长的裁剪是**有界**的（常量有名字，不散落魔数）。"""
    plan = build_plan([f"任务{i}" for i in range(MAX_TODO_ITEMS + 5)])
    assert len(plan) == MAX_TODO_ITEMS
    long_item = build_plan(["x" * (MAX_TODO_CHARS + 50)])[0]
    assert len(long_item.content) == MAX_TODO_CHARS


def test_build_plan_is_full_replacement_by_construction():
    """`build_plan` 只吃「新清单」，不读旧计划 ⇒ 重规划不会把计划翻倍。

    ★ 追加语义的病：模型每次重规划都翻倍，而它**看不出来** —— 渲染块只显示
      前 `MAX_TODO_ITEMS` 条，多出来的静默消失（同族：「无上界」）。
    """
    import inspect

    sig = inspect.signature(build_plan)
    assert list(sig.parameters) == ["items"], "build_plan 不应接受旧计划入参（会诱导追加语义）"


def test_apply_status_updates_one_and_returns_new_list():
    plan = build_plan(["甲", "乙", "丙"])
    updated, msg = apply_status(plan, "t2", "in_progress", "正在做")
    assert [t.status for t in updated] == ["pending", "in_progress", "pending"]
    assert updated[1].note == "正在做"
    assert [t.status for t in plan] == ["pending"] * 3, "原列表不得被就地修改"
    assert "t2" in msg and "in_progress" in msg and "进度" in msg


def test_apply_status_unknown_id_changes_nothing_and_says_so():
    """未知 id ⇒ 一个字段都不改，且**明说没找到**并列出当前编号。

    ★ 静默失败会让模型以为改成功了，下一条消息继续基于错误的世界观推理 ——
      这是「失败路径必须回写状态」在工具层的版本。
    """
    plan = build_plan(["甲", "乙"])
    same, msg = apply_status(plan, "t9", "completed")
    assert [t.status for t in same] == ["pending", "pending"]
    assert "没有子任务" in msg and "t1" in msg and "t2" in msg


def test_apply_status_rejects_illegal_status_and_lists_legal_ones():
    plan = build_plan(["甲"])
    same, msg = apply_status(plan, "t1", "finished")
    assert same[0].status == "pending"
    for s in TASK_STATUSES:
        assert s in msg, f"拒绝文案里应列出合法取值 {s}"


def test_apply_status_on_empty_plan_points_at_plan_tasks():
    same, msg = apply_status([], "t1", "completed")
    assert same == []
    assert "plan_tasks" in msg, "空计划时要明确告诉模型先建计划"


def test_normalize_todos_self_heals_dirty_input():
    """任意来路的值都收敛成合法列表（读时自愈，不抛异常）。

    ★ 脏数据在渲染或变更时抛异常的代价是**整轮对话崩掉**；自愈方向与
      `_sanitize_tool_call_pairing` 一致：丢坏数据、保住这一轮。
    ★ 丢弃面是「真的丢掉」：`None` / 数字 / 纯空白 → 无一幸免。
      （写这条断言时我一开始以为 `42` 会被 `str()` 成 `"42"` 保留 —— 实测不是，
        只有 `str` 类型才走裸字符串分支。）
    """
    assert normalize_todos(None) == []
    out = normalize_todos([None, 42, "  ", "有效文本", {"content": "好的"}])
    assert [t.content for t in out] == ["有效文本", "好的"], f"实际 {[t.content for t in out]}"
    bad_status = normalize_todos([{"content": "x", "status": "??"}])[0]
    assert bad_status.status == "pending", "状态不认识 ⇒ 退回 pending（内容是有效的）"
    assert normalize_todos({"content": "单个 dict"})[0].content == "单个 dict"


def test_normalize_todos_dedups_and_fills_ids():
    """id 重复或缺失 ⇒ 重排成 `t1..tN`（`update_task` 靠 id 定位，重复会改错对象）。"""
    out = normalize_todos([{"id": "t1", "content": "a"}, {"id": "t1", "content": "b"}])
    assert [t.id for t in out] == ["t1", "t2"]
    out2 = normalize_todos([{"content": "a"}, {"content": "b"}])
    assert [t.id for t in out2] == ["t1", "t2"]


def test_normalize_todos_bounds_quantity():
    out = normalize_todos([{"content": f"c{i}"} for i in range(MAX_TODO_ITEMS + 10)])
    assert len(out) == MAX_TODO_ITEMS


def test_render_plan_block_shape_and_empty_case():
    assert render_plan_block([]) == "", "空计划渲染空串（由调用方决定拼不拼）"
    assert render_plan_block(None) == ""
    plan = build_plan(["甲", "乙"])
    plan, _ = apply_status(plan, "t1", "completed", "做完了")
    text = render_plan_block(plan)
    assert "【当前计划】" in text and "1/2" in text
    assert "[x] t1 甲 —— 做完了" in text
    assert "[ ] t2 乙" in text
    for s in TASK_STATUSES:
        assert s in STATUS_MARKS, f"状态 {s} 缺渲染符号"


def test_plan_summary_counts_and_keeps_every_item():
    plan = build_plan(["甲", "乙", "丙"])
    plan, _ = apply_status(plan, "t1", "completed")
    plan, _ = apply_status(plan, "t2", "blocked", "缺素材")
    summary = plan_summary(plan)
    assert summary["total"] == 3 and summary["completed"] == 1
    assert summary["by_status"]["blocked"] == 1
    assert [i["content"] for i in summary["items"]] == ["甲", "乙", "丙"], "摘要不得丢项"
    assert summary["items"][1]["note"] == "缺素材"


def test_todo_item_is_frozen_and_json_shaped():
    item = TodoItem(id="t1", content="x")
    with pytest.raises(Exception):
        item.content = "y"  # type: ignore[misc]
    d = item.as_dict()
    assert set(d) == {"id", "content", "status", "note"}
    assert json.loads(json.dumps(d, ensure_ascii=False)) == d, "as_dict 必须是 JSON 原生类型"


# ================================================== B 组 · 术语唯一真源（P5）
def test_status_literal_matches_tuple():
    """工具签名里的 `Literal` 副本必须与 `TASK_STATUSES` 集合相等。

    ★ 两份取值必然漂移：加了 `cancelled` 却只改一处 ⇒ 模型能填但引擎不认
      （或反之），症状是「偶尔报『不是合法取值』」。
    """
    assert set(typing.get_args(TaskStatus)) == set(TASK_STATUSES)


def test_status_marks_cover_exactly_the_statuses():
    assert set(STATUS_MARKS) == set(TASK_STATUSES)


def test_local_state_set_matches_planner_tools():
    """`side_effects.LOCAL_STATE_TOOL_NAMES` 与 `plan.PLANNER_TOOL_NAMES` 双向对账。

    ★ 这两个集合分住两个模块（`side_effects` 是策略真源、`plan` 是工具定义处），
      但它们是**同一件事的两侧**。任一侧单独改名 ⇒ 那条策略判据会指向一个
      不存在的工具（静默失效）。这条把它们钉成同一个集合。
    """
    assert set(LOCAL_STATE_TOOL_NAMES) == set(PLANNER_TOOL_NAMES)
    assert {t.name for t in planner_tools} == set(PLANNER_TOOL_NAMES)


def test_plan_module_has_no_third_status_table():
    """状态取值的字面量在 `plan.py` 里只允许**两处**：定义 + Literal 副本。

    ★ 判据走 AST 而不是 `unparse` 后的字符串 —— 形态判据用字符串包含会骗人
      （docstring / 注释 / 引号形态都会干扰）。
    ★ 这两处是什么：`TASK_STATUSES = (...)` 的定义，与
      `TaskStatus = Literal[...]` 的取值副本（工具签名要用它，且两者相等由
      `test_status_literal_matches_tuple` 保证）。出现**第三处**才是病：
      比如有人加一个 `ALL_STATUSES = (...)`，两份取值从此可以各改各的。
    """
    tree = ast.parse(PLAN_PY.read_text(encoding="utf-8"))
    sites = []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Tuple, ast.List)) and len(n.elts) == len(TASK_STATUSES):
            vals = [e.value for e in n.elts if isinstance(e, ast.Constant)]
            if len(vals) == len(TASK_STATUSES) and set(vals) == set(TASK_STATUSES):
                sites.append(n.lineno)
    assert len(sites) == 2, (
        f"状态字面量出现 {len(sites)} 处（行 {sites}），期望 2 处"
        "（TASK_STATUSES 定义 + TaskStatus 的 Literal 副本）"
    )


# ================================================== C 组 · 副作用第三档（P4）
def test_planner_tools_declare_local_state():
    for t in planner_tools:
        assert is_declared(t), f"{t.name} 未显式声明副作用（必须表态，不能靠默认）"
        assert declared_local_state(t), f"{t.name} 应声明只写本地 state"
        assert t.metadata == LOCAL_STATE_METADATA


def test_planner_tools_are_never_gated_by_hitl():
    """规划工具**不进审批名单** —— 每一步计划都要用户点「批准」是把规划器变成噪音。"""
    assert derive_hitl_tools(planner_tools) == []


def _fake_tool(name: str, md: dict) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: "x", name=name, description="d", metadata=md)


def test_write_verb_violations_still_catches_readonly_write_names():
    """写动词名 + **纯只读**声明 ⇒ 仍被咬（第三档没有放宽既有判据）。"""
    bad = _fake_tool("update_shop_config", READ_ONLY_METADATA)
    assert write_verb_violations([bad]) == ["update_shop_config"]
    assert write_verb_violations(planner_tools) == [], "本地状态声明应被放行"


def test_local_state_violations_catches_out_of_control_plane_declarations():
    """★ 独立第二判据：借 local_state 躲审批（不在受控集合）⇒ 必被咬。

    这条是第三档的**安全边界**。没有它，任何人给真写库工具挂上
    `LOCAL_STATE_METADATA` 就能既躲开审批、又不触发任何既有判据。
    """
    sneaky = _fake_tool("delete_ledger_row", LOCAL_STATE_METADATA)
    assert write_verb_violations([sneaky]) == [], "它确实能躲过写动词判据（所以要第二条）"
    assert local_state_violations([sneaky]) == ["delete_ledger_row"]
    assert local_state_violations(planner_tools) == []


def test_business_tools_never_declare_local_state():
    """反向哨兵：业务注册表里的工具**一个都不许**声明 local_state。

    ★ 若哪天有人为了免审批给某个业务工具挂上它，这条会红 ——
      而不是等到「审批闸门某天不响了」才被发现。
    ★ 工具清单**复用** `test_hitl_policy._all_tools()`（那里是注册表的真源），
      不在这里另维护一份名单 —— 两份名单必然漂移，而漂移的那份会静默放行。
    """
    import importlib.util

    p = BACKEND / "tests" / "test_hitl_policy.py"
    spec = importlib.util.spec_from_file_location("hitl_policy_probe_for_plan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tools = mod._all_tools()
    assert tools, "业务工具清单为空 ⇒ 本判据失去目标（`all(...)` 会真空通过）"
    assert local_state_violations(tools) == [], (
        "业务工具借 local_state 躲开了审批：" + str(local_state_violations(tools))
    )


# ================================================== D 组 · 工具返回值形态（P3）
def _tool_func(name: str):
    tree = ast.parse(PLAN_PY.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == f"_{name}":
            return n
    raise AssertionError(f"plan.py 里找不到工具函数 _{name}")


@pytest.mark.parametrize("name", ["plan_tasks", "update_task"])
def test_plan_tools_return_tool_message_in_command(name):
    """每个规划工具的每个 `Command(update=…)` 都必须带 `messages=[ToolMessage(...)]`（P3）。

    ★ 实测：缺了它 ToolNode 抛
      `ValueError: Expected to have a matching ToolMessage in Command.update`，
      整轮挂掉。这是 OpenAI 兼容 API 的硬约束在不同层级的体现。
      ★ 写成 AST 判据而不是「跑一遍看会不会炸」：`_plan_tasks` 有一条
      **提前返回**的分支（空清单），只跑常规路径覆盖不到它。
    """
    fn = _tool_func(name)
    builds = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Command"]
    # 名字可能以 `Command` 直接调用（本模块的写法）
    if not builds:
        builds = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Command"]
    assert builds, f"{name} 里没有 Command(...) 调用"
    for call in builds:
        kw = {k.arg for k in call.keywords}
        assert "update" in kw, f"{name} 的 Command 缺 update"
        update = next(k.value for k in call.keywords if k.arg == "update")
        keys = {k.value for k in update.keys if isinstance(k, ast.Constant)}
        assert "messages" in keys, f"{name} 的 Command.update 缺 messages（会造成 orphan tool_call）"
        body_src = ast.unparse(update)
        assert "ToolMessage(" in body_src, f"{name} 的 update['messages'] 里不是 ToolMessage"
        assert "tool_call_id=tool_call_id" in body_src, f"{name} 的 ToolMessage 必须回带 tool_call_id"


@pytest.mark.parametrize("name", ["plan_tasks", "update_task"])
def test_plan_tools_take_injected_state_and_call_id(name):
    fn = _tool_func(name)
    anns = {}
    for a in list(fn.args.args) + list(fn.args.kwonlyargs):
        anns[a.arg] = ast.unparse(a.annotation) if a.annotation else ""
    assert "InjectedState" in anns.get("state", ""), f"{name} 缺少 InjectedState（读不到当前计划）"
    assert "InjectedToolCallId" in anns.get("tool_call_id", ""), f"{name} 缺少 InjectedToolCallId"


@pytest.mark.parametrize("name", ["plan_tasks", "update_task"])
def test_injected_params_are_not_sent_to_the_model(name):
    """★ 判据必须查「真正发给模型的那一层」（`tool_call_schema`），不是 `args_schema`。

    实测：`args_schema` **含** `state` / `tool_call_id` —— 那是正常的
    （ToolNode 正是靠它认出该注入什么）；过滤发生在 `tool_call_schema`，
    而 `bind_tools` 用的就是后者。查错层会得到**假 BAD**（同族：只查
    docstring 不查字符串、只比类名不比内容）。
    """
    from langchain_core.utils.function_calling import convert_to_openai_tool

    tool = _by_name(name)
    sent = set((tool.tool_call_schema.model_json_schema().get("properties") or {}))
    assert not ({"state", "tool_call_id"} & sent), f"发给模型的 schema 泄漏了注入参数：{sent}"
    params = convert_to_openai_tool(tool)["function"]["parameters"]
    assert not ({"state", "tool_call_id"} & set(params.get("properties") or {}))
    assert set(params.get("required") or []) <= {"tasks", "task_id", "status"}, (
        f"{name} 的必填项异常：{params.get('required')}"
    )


def test_update_task_status_enum_is_locked_by_literal():
    """`status` 在模型侧是 **enum** ⇒ 只能从合法取值里选（天然防幻觉）。"""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    params = convert_to_openai_tool(_by_name("update_task"))["function"]["parameters"]
    assert set(params["properties"]["status"]["enum"]) == set(TASK_STATUSES)


# ================================================== E 组 · 基类接线形态
def _func_of(tree: ast.AST, cls: str, name: str):
    for c in ast.walk(tree):
        if isinstance(c, ast.ClassDef) and c.name == cls:
            for f in c.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == name:
                    return f
    raise AssertionError(f"找不到 {cls}.{name}")


def test_agent_state_has_todos_key_separate_from_messages():
    """`AgentState.todos` 存在，且**不是** messages（P1 的结构面）。"""
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    cls = next(c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "AgentState")
    fields = {s.target.id for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    assert TODOS_STATE_KEY in fields, f"AgentState 缺 {TODOS_STATE_KEY} 键（实际 {sorted(fields)}）"
    assert AgentState.__annotations__.get(TODOS_STATE_KEY) is not None


def test_enable_planning_defaults_to_false():
    """类属性存在、默认 **False** —— 「先规划后执行」是可选模式。"""
    assert BaseAgent.ENABLE_PLANNING is False
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    cls = next(c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "BaseAgent")
    val = None
    for s in cls.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.target.id == "ENABLE_PLANNING":
            val = s.value.value
    assert val is False, f"ENABLE_PLANNING 的类属性默认值应为 False，实际 {val!r}"


def test_init_accepts_enable_planning_and_coerces_to_bool():
    """构造参数存在、且**解析成 bool**（不留 `None` 三态）。"""
    import inspect

    sig = inspect.signature(BaseAgent.__init__)
    assert "enable_planning" in sig.parameters
    assert sig.parameters["enable_planning"].default is None, "哨兵应是 None（未指定）"
    assert BaseAgent(agent_name="x").enable_planning is False
    assert BaseAgent(agent_name="x", enable_planning=True).enable_planning is True

    class Sub(BaseAgent):
        ENABLE_PLANNING = True

    assert Sub(agent_name="s").enable_planning is True
    assert Sub(agent_name="s", enable_planning=False).enable_planning is False
    assert isinstance(Sub(agent_name="s").enable_planning, bool)


def test_system_prompt_with_plan_is_used_before_invoke():
    """`_llm_call_node` 必须先经 `_system_prompt_with_plan`，再 `ainvoke`（P2）。

    ★ 判据走 AST：找出所有 `SystemMessage(...)` 调用，检查它的 content 实参
      **就是** `self._system_prompt_with_plan(state)`。这比「源码里有没有某个
      字符串」稳健 —— 后者会被注释与死代码骗过，且在 `unparse` 后引号/空格形态
      一变就假红。
    """
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func_of(tree, "BaseAgent", "_llm_call_node")

    sm_calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("SystemMessage")
    ]
    assert sm_calls, "_llm_call_node 里没有构造 SystemMessage"
    for call in sm_calls:
        expr = call.args[0] if call.args else next(
            (k.value for k in call.keywords if k.arg == "content"), None
        )
        assert expr is not None, "SystemMessage 没有 content 实参"
        assert "_system_prompt_with_plan" in ast.unparse(expr), (
            f"SystemMessage 的 content 不是带计划的 prompt：{ast.unparse(expr)}"
        )

    # 顺序：拼接 prompt（第一个 SystemMessage）必须早于 ainvoke
    first_sm = min(n.lineno for n in sm_calls)
    invoke_lines = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Call) and "ainvoke" in ast.unparse(n.func)
    ]
    assert invoke_lines and first_sm < min(invoke_lines), "必须先拼 prompt 再发请求"


def test_respond_node_surfaces_plan_only_when_present():
    """`_respond_node` 只在「开启且有计划」时才带 `plan` 键（P6）。

    ★ 判据全部走 **AST**：`ast.unparse` 会把 `structured["plan"]` 反解析成
      **单引号** `structured['plan']`，拿双引号字符串去断言会得到**假 BAD**
      （实测踩过）。形态判据一律用语法节点，不用源码字符串 —— 这是本仓
      反复出现的同一族坑。
    """
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func_of(tree, "BaseAgent", "_respond_node")

    def _is_plan_assign(node) -> bool:
        if not isinstance(node, ast.Assign):
            return False
        for t in node.targets:
            if (
                isinstance(t, ast.Subscript)
                and isinstance(t.value, ast.Name)
                and t.value.id == "structured"
                and isinstance(t.slice, ast.Constant)
                and t.slice.value == "plan"
            ):
                return True
        return False

    assign_nodes = [n for n in ast.walk(fn) if _is_plan_assign(n)]
    assert assign_nodes, "没有找到 structured['plan'] = ... 赋值"
    assert "plan_summary(" in ast.unparse(assign_nodes[0].value), "计划摘要必须来自 plan_summary"

    guarded = False
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and "self.enable_planning" in ast.unparse(n.test):
            if any(_is_plan_assign(s) for s in ast.walk(n)):
                guarded = True
    assert guarded, "plan 赋值必须被 `if self.enable_planning` 守卫"

    on = BaseAgent(agent_name="r", enable_planning=True)
    with_plan = {"messages": [HumanMessage(content="q"), AIMessage(content="a")],
                 "todos": [{"id": "t1", "content": "x", "status": "completed"}], "budget": {}}
    assert "plan" in asyncio.run(on._respond_node(with_plan))["structured_response"]
    no_plan = {"messages": [HumanMessage(content="q"), AIMessage(content="a")], "todos": [], "budget": {}}
    assert "plan" not in asyncio.run(on._respond_node(no_plan))["structured_response"]
    off = BaseAgent(agent_name="r2", enable_planning=False, system_prompt="p")
    assert "plan" not in asyncio.run(off._respond_node(with_plan))["structured_response"]


# ================================================== F 组 · 端到端行为
def test_tools_are_assembled_only_when_enabled():
    """开启 ⇒ 恰好多两个工具；关闭 ⇒ 一个都不多（P4 的装配面）。"""
    off = BaseAgent(agent_name="off")
    on = BaseAgent(agent_name="on", enable_planning=True)
    assert not ({"plan_tasks", "update_task"} & {t.name for t in off.tools})
    assert {"plan_tasks", "update_task"} <= {t.name for t in on.tools}
    assert {t.name for t in on.tools} - {t.name for t in off.tools} == set(PLANNER_TOOL_NAMES)
    assert not (set(PLANNER_TOOL_NAMES) & on.hitl_tool_names), "规划工具不该进审批名单"


def test_business_tools_and_planner_tools_coexist():
    biz = _fake_tool("search_faq", READ_ONLY_METADATA)
    agent = BaseAgent(agent_name="both", tools=[biz], enable_planning=True)
    assert {t.name for t in agent.tools} == {"search_faq", "plan_tasks", "update_task"}


def _graph_with(script: list[tuple[str, dict]], tools: list):
    """建一张最小 ReAct 图：假模型按脚本发 tool_calls，ToolNode 执行。"""

    class Spy:
        def __init__(self):
            self.i = 0

        def __call__(self, state):
            if self.i >= len(script):
                return {"messages": [AIMessage(content="完成")]}
            n, a = script[self.i]
            self.i += 1
            return {"messages": [AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"c{self.i}", "type": "tool_call"}])]}

    class St(MessagesState):
        todos: list

    wf = StateGraph(St)
    wf.add_node("llm", Spy())
    wf.add_node("tool_node", ToolNode(tools))
    wf.add_edge(START, "llm")
    wf.add_conditional_edges(
        "llm",
        lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else "end",
        {"tools": "tool_node", "end": END},
    )
    wf.add_edge("tool_node", "llm")
    return wf.compile()


def test_end_to_end_plan_then_update_states():
    """真图跑一遍：`plan_tasks` → 两条 `update_task` ⇒ state 与消息都正确。"""
    g = _graph_with(
        [
            ("plan_tasks", {"tasks": ["拆解需求", "查数据", "出结论"]}),
            ("update_task", {"task_id": "t1", "status": "completed", "note": "已明确"}),
            ("update_task", {"task_id": "t2", "status": "in_progress"}),
        ],
        planner_tools,
    )
    out = g.invoke({"messages": [HumanMessage(content="做个分析")], "todos": []})
    todos = out["todos"]
    assert [t["status"] for t in todos] == ["completed", "in_progress", "pending"]
    assert todos[0]["note"] == "已明确"
    tms = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tms) == 3, "每个 tool_call 都要有 ToolMessage 回应（否则下一轮 400）"
    assert any("当前计划" in str(m.content) for m in tms), "工具回执里应带上计划渲染"
    assert len({m.tool_call_id for m in tms}) == 3


def test_missing_tool_message_actually_raises():
    """证明 D 组判据**必要**：工具只返回 todos、不回 ToolMessage ⇒ 框架直接抛。

    ★ 这是「门禁存在的理由」的真实复现 —— 不是假想的约束。
    ★ 注解依赖（`Annotated` / `InjectedState` / `InjectedToolCallId` / `Command`）
      必须在**模块顶层** import：本文件开了 `from __future__ import annotations`
      ⇒ 所有注解都是**字符串**、延迟到运行期才解析；`@tool` 用
      `typing.get_type_hints` 在**模块全局命名空间**里求值 ⇒ 函数内 import 的
      名字找不到，报 `NameError`。**返回注解同样会被解析**（`-> Command`），
      所以它也得在顶层 —— 这一点连踩三次才反应过来。
    """
    from langgraph.types import Command  # noqa: F401  （运行时用；注解见顶层 import）

    @tool
    def bad(state: Annotated[dict, InjectedState], *, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
        """故意不回 ToolMessage。"""
        return Command(update={"todos": [{"id": "t1", "content": "x", "status": "pending"}]})

    class St(MessagesState):
        todos: list

    wf = StateGraph(St)
    wf.add_node("llm", lambda s: {"messages": [AIMessage(content="", tool_calls=[{"name": "bad", "args": {}, "id": "c1", "type": "tool_call"}])]})
    wf.add_node("tool_node", ToolNode([bad]))
    wf.add_edge(START, "llm")
    wf.add_edge("llm", "tool_node")
    wf.add_edge("tool_node", END)
    with pytest.raises(ValueError, match="matching ToolMessage"):
        wf.compile().invoke({"messages": [HumanMessage(content="x")], "todos": []})


def test_system_prompt_with_plan_three_shapes():
    """三形态：关 ⇒ 原样；开无计划 ⇒ prompt+GUIDE；开有计划 ⇒ 再加渲染块。"""
    biz = "你是助手。"
    off = BaseAgent(agent_name="a", system_prompt=biz, enable_planning=False)
    assert off._system_prompt_with_plan({"todos": [{"id": "t1", "content": "x"}]}) == biz, (
        "关闭规划时一行注入都不能有（否则「默认关」是假的）"
    )
    on = BaseAgent(agent_name="b", system_prompt=biz, enable_planning=True)
    no_plan = on._system_prompt_with_plan({})
    assert biz in no_plan and PLANNING_GUIDE in no_plan
    assert "【当前计划】" not in no_plan, "无计划时不该有渲染块标题"
    with_plan = on._system_prompt_with_plan({"todos": [{"id": "t1", "content": "甲", "status": "completed"}]})
    assert "【当前计划】" in with_plan and "[x] t1 甲" in with_plan


def test_plan_survives_history_trimming():
    """★★ 核心不变量：历史被**折叠 + 删轮**之后，计划仍完整出现在 system prompt 里。

    ★ 为什么要三件套（Human/AI/Tool）都放大：只放大工具结果的话，折叠一步就把
      token 拉回预算内、**删轮根本不触发** —— 那样这条用例证明不了「删掉整轮也
      不影响计划」。三件套都大 ⇒ 两个阶段都真实发生。
    """
    from ai_infra.context import CONTEXT_ROUTER, trim_history

    msgs = []
    for i in range(8):
        msgs.append(HumanMessage(content="问题" * 3000))
        msgs.append(AIMessage(content="回答" * 3000, tool_calls=[{"name": "x", "args": {}, "id": f"c{i}", "type": "tool_call"}]))
        msgs.append(ToolMessage(content="数据" * 3000, tool_call_id=f"c{i}"))
    todos = [
        {"id": "t1", "content": "拆解需求", "status": "completed", "note": "已明确"},
        {"id": "t2", "content": "查数据", "status": "in_progress"},
    ]
    trimmed, report = trim_history(msgs, CONTEXT_ROUTER)

    # 对照组：裁剪**真的发生了**（否则这条用例是空跑）
    assert report.folded_tool_results > 0, "折叠阶段没生效 ⇒ 用例失去意义"
    assert report.turns_dropped > 0 and len(trimmed) < len(msgs), "删轮阶段没生效 ⇒ 用例失去意义"
    assert report.tokens_after < report.tokens_before

    agent = BaseAgent(agent_name="c", system_prompt="你是助手。", enable_planning=True)
    prompt = agent._system_prompt_with_plan({"todos": todos})
    assert "[x] t1 拆解需求 —— 已明确" in prompt, "裁剪后计划丢了"
    assert "[>] t2 查数据" in prompt
    # 计划与消息是两条独立载体：裁剪后的消息里**没有**计划（它不在那儿）
    joined = "\n".join(str(getattr(m, "content", "") or "") for m in trimmed)
    assert "拆解需求" not in joined


def test_short_history_is_not_touched_by_planner():
    """反面：短会话里规划器不得引入任何裁剪行为（它只注入，不动历史）。"""
    from ai_infra.context import CONTEXT_ROUTER, trim_history

    msgs = [HumanMessage(content="一句话"), AIMessage(content="答")]
    _, report = trim_history(msgs, CONTEXT_ROUTER)
    assert report.changed is False


# ================================================== G 组 · 业务侧（P6）
def test_secretary_enables_planning_as_class_attribute():
    """店秘书以**类属性**开启（不是散落在 `tools=` 里手写工具）。"""
    tree = ast.parse((MODULES / "secretary" / "agent.py").read_text(encoding="utf-8"))
    cls = next(c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "SecretaryAgent")
    found = None
    for s in cls.body:
        if isinstance(s, ast.Assign) and any(getattr(t, "id", "") == "ENABLE_PLANNING" for t in s.targets):
            found = s.value.value
    assert found is True, f"SecretaryAgent.ENABLE_PLANNING 应为 True，实际 {found!r}"


def test_secretary_route_reads_plan_from_graph_state():
    """`route()` 从**图状态**读计划（P1：计划不在 messages 里，只能从 state 取）。"""
    src = (MODULES / "secretary" / "agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        f for f in ast.walk(tree)
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == "route"
    )
    body = ast.unparse(fn)
    assert "TODOS_STATE_KEY" in body, "route() 没从 state 读计划"
    assert "state.get(" in body
    assert "plan_summary" in body


def test_orchestrator_response_exposes_plan_and_is_wired():
    """`OrchestratorResponse.plan` 不只是声明 —— 端点必须真的把它填上。

    ★ 「声明了字段但没人填」= 恒为 None 的死字段，与 r141 记的
      `structured_response` 死输出同族。所以两处一起钉。
    """
    src = (MODULES / "secretary" / "router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(c for c in ast.walk(tree) if isinstance(c, ast.ClassDef) and c.name == "OrchestratorResponse")
    fields = {s.target.id for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    assert "plan" in fields, f"OrchestratorResponse 缺 plan 字段（实际 {sorted(fields)}）"
    assert 'plan=result.get("plan")' in src, "端点没有回传 plan ⇒ 字段永远是 None（死字段）"


def test_plan_is_not_written_into_message_history():
    """P1 的语法面反向哨兵：计划**不得**被写进 messages。

    ★ 若哪天有人图省事把计划塞进一条 SystemMessage（看着更简单），
      它就会随 `trim_history` 一起被裁 —— 而这条路径上没有任何报错。
    ★ 判据用 `ast.Name`（**代码里的标识符**）而不是 `unparse` 后的字符串：
      后者的 docstring 正文里就有「messages」一词，会造成**假 BAD**
      （实测踩过）。「判据禁源码字符串包含，形态判据一律走 AST」这条
      在 docstring 场景下尤其致命 —— 解释问题的文字本身会触发判据。
    """
    tree = ast.parse(BASE_AGENT_PY.read_text(encoding="utf-8"))
    fn = _func_of(tree, "BaseAgent", "_system_prompt_with_plan")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "messages" not in names, "_system_prompt_with_plan 不该碰 messages（它只产字符串）"
    called = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert not any("SystemMessage" in c for c in called), "不得在这里构造 SystemMessage"


# ================================================== H 组 · 分层
def _load_layering_gate():
    """按路径加载 layering 门禁 —— 复用它的扫描函数，不另写一份判据。

    ★ `tests/` 没有 `__init__.py`，不能写 `from tests.xxx import ...`。
      「同一指标两份实现 ⇒ 至少一份永远测不到」：分层判据只允许有一处。
    """
    import importlib.util

    p = BACKEND / "tests" / "test_infra_layering.py"
    spec = importlib.util.spec_from_file_location("layering_gate_probe_plan", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plan_module_respects_infra_layering():
    gate = _load_layering_gate()
    src = PLAN_PY.read_text(encoding="utf-8")
    assert gate.scan_reverse_imports(src) == [], "ai_infra/plan.py 反向 import 了业务模块"
    hits = gate.scan_business_strings(src)
    assert not hits, f"ai_infra/plan.py 的字符串字面量里出现业务内容: {hits}"


def test_plan_module_reaches_no_database():
    """机制层不做任何 IO：不得出现 DB / session / 存储相关 import。"""
    tree = ast.parse(PLAN_PY.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    forbidden = {"sqlalchemy", "core", "modules", "alembic"}
    assert not (mods & forbidden), f"plan.py 引入了存储/上层依赖：{sorted(mods & forbidden)}"

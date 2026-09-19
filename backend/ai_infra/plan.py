"""自主规划器 —— 子任务清单的机制层（第 148 轮 · 批 C3）。

问题形态
--------
本仓的图是**固定三节点 ReAct**（`llm_call → tool_node → llm_call → … → respond`），
`max_iterations` 一满就硬截断（第 145 轮批 C5 已让它留下可读的超限结论）。它缺的是
**「先规划后执行」**：模型边想边做，走到第 N 步被截断时，调用方看不到
「本来还要做什么」；而计划若写在 assistant 消息里，第 147 轮批 C4 加的
历史裁剪会把它当**旧历史**裁掉 —— 裁完计划就"忘了"。

本模块把计划**从消息里拿出来**，变成图状态里的一个结构化列表：

    state["todos"] : list[dict]        # 元素形状见 `TodoItem`

于是它与消息历史**寿命不同**：裁剪只作用于 `messages`（`ai_infra/context.py`），
`todos` 不在其中 ⇒ **裁多少轮都不影响计划**。这正是 r141 那句
「todo 清单**外置**为状态」的字面含义。

分工
----
  · **本模块** —— 数据形状 + 纯函数变更 + 两个 LLM 可调用工具 + 给模型看的渲染；
  · `BaseAgent` —— 装配（`enable_planning` 时把工具加进 `self.tools`）与注入
    （每轮把当前计划渲染进 system prompt，见 `_system_prompt_with_plan`）；
  · 业务 Agent —— 决定用不用（类属性 `ENABLE_PLANNING`）。

★ 计划存在**图状态**里，随 checkpointer 落 PG —— 不新开一张表。
  理由：todos 是一个**结构化状态**（有序、需整体替换），checkpointer 的整份
  state 快照正是它的自然容器；而 `modules/conversation` 的 `agent_session_state`
  表是「一 (thread_id, state_key) 一行」的**离散键**存储（见其 db_model 的
  docstring）。两者持久性相同（都是 PG）、分工不同，把 todos 塞进离散键表
  只会多出一处需要同步口径的地方。

★ 本模块不做任何 IO、不认识数据库、不含任何业务词（`ai_infra` 分层门禁
  `tests/test_infra_layering.py` 的标识符与字符串两个扫描面都会检查）。

两个工具为什么**不**需要人工审批
--------------------------------
`update_task` 的名字带写动词 `update_`，按 `ai_infra/tools/side_effects.py` 的
`WRITE_VERB_PREFIXES` 会被当成「写操作」—— 那条规则是对的（名字是廉价但强的
信号），但它针对的是**外部副作用**（写库 / 发消息 / 花钱）。本模块的工具改的是
**Agent 自己的图状态**：不落外部数据、不产生不可逆动作、下一次 `plan_tasks`
就能整体覆盖。让每一步规划都停下来等用户点「批准」，会把规划器变成噪音源。

因此副作用策略新增第三档 `LOCAL_STATE_METADATA`（只写本地 state）：
  · 它**免审批**，但与只读声明**不是一回事**（`declared_local_state()` 可区分）；
  · 它**不能随便用** —— 声明 local_state 的工具名必须在受控集合
    `LOCAL_STATE_TOOL_NAMES` 里，否则 `local_state_violations()` 报违规。
    于是「把某个真写库工具声明成 local_state 以躲开审批」这条路被堵住：
    受控集合是硬编码的，加名字必须同步改门禁，而门禁会与真实工具名对账。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Iterable, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from ai_infra.tools.side_effects import LOCAL_STATE_METADATA

# ============================================================
# 口径常量
# ============================================================

#: 图状态里装计划的键名（`AgentState.todos`）。
TODOS_STATE_KEY = "todos"

#: 子任务状态取值 —— **唯一真源**。
#: ⚠️ 工具签名里的 `TaskStatus` 是它的 `Literal` 副本，两者必须逐字相等；
#:   由 `tests/test_agent_plan.py::test_status_literal_matches_tuple` 对账。
TASK_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed", "blocked")

#: 状态在渲染块里的符号（给人看，也给模型看）。
STATUS_MARKS: dict = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "blocked": "[!]",
}

#: 单份计划最多几项。★ 不是「技术上装不下」，而是**计划的用途是让人一眼看懂**：
#: 超过这个数量，模型自己也跟不住，UI 上也展不开。超出的部分会被丢弃，
#: 但**不是在工具里静默丢** —— 见 `build_plan()` 的返回值与工具回执文案。
MAX_TODO_ITEMS: int = 20

#: 单项文本长度上限（防止模型把整段回答塞进一条 todo）。
MAX_TODO_CHARS: int = 200

#: 状态的 `Literal` 副本（工具签名用 —— LLM 只能在合法取值里选，天然防幻觉）。
TaskStatus = Literal["pending", "in_progress", "completed", "blocked"]

#: 恒定的规划指令 —— 每当 `enable_planning` 的 Agent 拼 system prompt 时附上。
#: ★ 为什么放在 infra 而不放各业务 Agent：它是**机制的使用说明**（「什么时候该
#:   先规划」「完成一步要立刻回报」），不是业务知识。写在 infra 里，所有开启
#:   规划的 Agent 行为一致；改写一处即可整体调优。
#: ★ 内容里**不得出现业务词**（分层门禁会查非 docstring 字符串）。
PLANNING_GUIDE = (
    "【任务规划】面对需要多步才能完成的任务，先用 `plan_tasks` 把任务拆成有序的"
    "子任务清单，再逐步执行；每完成一步、或某一步被卡住，立刻用 `update_task` "
    "回报该步的状态（不要攒到全部做完才一次性回报）。已经给出的计划会一直显示在"
    "下面的「当前计划」区块里，且**不会因为对话变长而丢失** —— 所以请以那个区块为"
    "准，不要在回复里重新抄一遍完整计划。"
)


# ============================================================
# 数据形状
# ============================================================


@dataclass(frozen=True)
class TodoItem:
    """一条子任务。

    frozen：状态变更是**产生新列表**（`apply_status()` 返回新 list），而不是原地改。
    这样「这一轮的计划」在返回给调用方后就不可变，前端拿到的快照不会被后续
    请求改掉。
    """

    id: str
    content: str
    status: str = "pending"
    note: str = ""

    def as_dict(self) -> dict:
        """转成进 state / 进 JSON 的形态（**只含 JSON 原生类型**）。"""
        return {
            "id": self.id,
            "content": self.content,
            "status": self.status,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["TodoItem"]:
        """从 state / JSON 里的 dict 还原；形态不对返回 `None`（由调用方决定丢弃）。"""
        if isinstance(raw, TodoItem):
            return raw
        if not isinstance(raw, dict):
            return None
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        status = raw.get("status")
        if status not in TASK_STATUSES:
            # 状态不认识 ⇒ 退回 pending，而不是丢弃整条：内容是有效的，
            # 丢内容比丢一个状态字更可惜（同族判据见 `_sanitize_tool_call_pairing`）。
            status = "pending"
        note = raw.get("note")
        return cls(
            id=str(raw.get("id") or ""),
            content=content.strip()[:MAX_TODO_CHARS],
            status=status,
            note=(note if isinstance(note, str) else "")[:MAX_TODO_CHARS],
        )


def normalize_todos(raw: Any) -> list:
    """把**任意来路**的值收敛成合法 `TodoItem` 列表（读时自愈）。

    来路有三条：图状态（可能被旧版本写成别的形状）、工具调用、调用方直接塞的
    dict。任一条都可能带脏数据，而脏数据在渲染或变更时抛异常的代价是
    **整轮对话崩掉** —— 这里统一吸收。

    ★ 自愈方向与 `_sanitize_tool_call_pairing` 同一条：坏数据**丢弃**（保住这一轮），
      而不是让整轮失败。丢弃数量由调用方决定是否记日志（本函数不吞例外，
      只做形状收敛，因此可以放心在纯计算路径上调用）。
    """
    if raw is None:
        return []
    if isinstance(raw, (TodoItem, dict, str)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []

    out: list = []
    for item in raw:
        if isinstance(item, str):
            # 裸字符串 ⇒ 当作只有内容的条目（兼容调用方直接传 ["a","b"]）
            text = item.strip()[:MAX_TODO_CHARS]
            if text:
                out.append(TodoItem(id=f"t{len(out) + 1}", content=text))
            continue
        parsed = TodoItem.from_dict(item)
        if parsed is not None:
            out.append(parsed)
        if len(out) >= MAX_TODO_ITEMS:
            break

    # 补齐/修正 id：id 是**定位键**，重复或缺失都会让 `update_task` 改错对象。
    fixed: list = []
    seen: set = set()
    for i, item in enumerate(out, start=1):
        want = f"t{i}"
        if not item.id or item.id in seen:
            item = TodoItem(id=want, content=item.content, status=item.status, note=item.note)
        seen.add(item.id)
        fixed.append(item)
    return fixed


def build_plan(items: Iterable) -> list:
    """从一串任务描述建一份**全新**计划（id 按顺序重排 `t1..tN`，状态全 pending）。

    ★ 整体替换而非追加：`plan_tasks` 的语义是「这是我现在要做的计划」。
      追加语义下，模型每次重规划都会把计划翻倍，而它**看不出来** ——
      因为渲染块只显示前 N 条（`MAX_TODO_ITEMS`），多出来的部分静默消失。
    """
    out: list = []
    for raw in items or []:
        text = str(raw).strip()[:MAX_TODO_CHARS]
        if not text:
            continue
        out.append(TodoItem(id=f"t{len(out) + 1}", content=text))
        if len(out) >= MAX_TODO_ITEMS:
            break
    return out


def apply_status(
    todos: Iterable, task_id: str, status: str, note: str = ""
) -> tuple:
    """把某条子任务改成新状态；返回 `(新列表, 给模型看的一句话结论)`。

    ★ **失败时返回原列表**（形状归一化除外）—— 不匹配任何 id 时**什么都不改**，
      并由结论文案明确说出「没找到」以及「当前有哪些 id」。静默失败会让模型
      以为改成功了，下一条消息继续基于错误的世界观推理。
    ★ 结论文案是**工具返回值的一部分**（进 ToolMessage），所以它是给模型读的，
      不是给人读的日志 —— 措辞要能直接纠正模型的下一步。
    """
    current = normalize_todos(todos)

    if status not in TASK_STATUSES:
        return current, (
            f"❌ 状态 {status!r} 不是合法取值，本次未做任何改动。"
            f"合法取值：{'、'.join(TASK_STATUSES)}"
        )

    ids = [t.id for t in current]
    if not current:
        return current, "❌ 当前还没有计划，无法更新子任务。请先用 `plan_tasks` 建立计划。"
    if task_id not in ids:
        return current, (
            f"❌ 计划里没有子任务 {task_id!r}，本次未做任何改动。"
            f"当前子任务编号：{'、'.join(ids)}"
        )

    note = (note or "").strip()[:MAX_TODO_CHARS]
    updated: list = []
    for t in current:
        if t.id == task_id:
            updated.append(TodoItem(id=t.id, content=t.content, status=status, note=note))
        else:
            updated.append(t)

    done = sum(1 for t in updated if t.status == "completed")
    return updated, (
        f"✅ {task_id} 已标记为 {status}"
        + (f"（说明：{note}）" if note else "")
        + f"。进度 {done}/{len(updated)}。"
    )


# ============================================================
# 渲染（给模型看 / 给前端看）
# ============================================================


def render_plan_block(todos: Iterable) -> str:
    """把计划渲染成一段文本（空计划 ⇒ 空串，由调用方决定要不要拼）。

    ★ 每轮**现算**、不缓存：它的输入是图状态，而图状态是唯一真源。
      缓存一份渲染结果等于多一份可能过期的副本。
    """
    items = normalize_todos(todos)
    if not items:
        return ""
    done = sum(1 for t in items if t.status == "completed")
    lines = [f"【当前计划】{done}/{len(items)} 已完成"]
    for t in items:
        mark = STATUS_MARKS.get(t.status, "[ ]")
        line = f"  {mark} {t.id} {t.content}"
        if t.note:
            line += f" —— {t.note}"
        lines.append(line)
    return "\n".join(lines)


def plan_summary(todos: Iterable) -> dict:
    """计划的机器可读摘要（给 `structured_response` / 前端用）。"""
    items = normalize_todos(todos)
    by_status = {s: 0 for s in TASK_STATUSES}
    for t in items:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    return {
        "total": len(items),
        "completed": by_status.get("completed", 0),
        "by_status": by_status,
        "items": [t.as_dict() for t in items],
    }


# ============================================================
# 两个 LLM 可调用工具
# ============================================================
#
# ★ 两个工具都**必须**在 `Command.update` 里带上 `ToolMessage`：
#   实测（第 148 轮探针）只返回 `{"todos": ...}` 时，ToolNode 会抛
#       ValueError: Expected to have a matching ToolMessage in Command.update
#   因为「LLM 发起的每个 tool_call 都必须有一条 ToolMessage 回应」是
#   OpenAI 兼容 API 的硬约束，缺了它下一轮恢复历史会被 400 拒绝。
#   门禁 `test_plan_tools_return_tool_message_in_command` 用 AST 钉住这一点。


def _plan_tasks(
    tasks: list,
    *,
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """登记一份新的子任务清单（**整体替换**旧计划）。

    Args:
        tasks: 有序的子任务描述列表（第 1 项就是第 1 步）。
    """
    todos = build_plan(tasks)
    previous = normalize_todos(state.get(TODOS_STATE_KEY)) if isinstance(state, dict) else []

    if not todos:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="❌ 没有可登记的子任务（清单为空或全为空白），本次未做任何改动。",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    if len(list(tasks or [])) > MAX_TODO_ITEMS:
        # ★ 截断必须**说出来**：静默丢掉第 21 项以后的内容，模型会以为计划已完整。
        head = f"（清单超过 {MAX_TODO_ITEMS} 项，只登记了前 {MAX_TODO_ITEMS} 项）"
    else:
        head = ""
    replaced = f"原计划 {len(previous)} 项已被整体替换。" if previous else ""

    return Command(
        update={
            TODOS_STATE_KEY: [t.as_dict() for t in todos],
            "messages": [
                ToolMessage(
                    content=(
                        f"✅ 已登记 {len(todos)} 步子任务。{replaced}{head}\n"
                        f"{render_plan_block(todos)}"
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


def _update_task(
    task_id: str,
    status: TaskStatus,
    note: str = "",
    *,
    tool_call_id: Annotated[str, InjectedToolCallId],
    state: Annotated[dict, InjectedState],
) -> Command:
    """更新**某一步**子任务的状态。

    Args:
        task_id: 子任务编号（计划里形如 `t1` / `t2`）。
        status: 该步的新状态。
        note: 可选的一句话说明（完成结论 / 卡住的原因）。
    """
    current = normalize_todos(state.get(TODOS_STATE_KEY)) if isinstance(state, dict) else []
    new_todos, message = apply_status(current, task_id, status, note)

    return Command(
        update={
            TODOS_STATE_KEY: [t.as_dict() for t in new_todos],
            "messages": [ToolMessage(content=message, tool_call_id=tool_call_id)],
        }
    )


PLANNER_TOOL_NAMES: tuple = ("plan_tasks", "update_task")

planner_tools: list = [
    StructuredTool.from_function(
        func=_plan_tasks,
        name="plan_tasks",
        description=(
            "登记一份新的子任务清单（整体替换旧计划）。面对需要多步才能完成的任务时，"
            "先用它把任务拆成有序的子任务。登记后计划会一直可见，不会因为对话变长而丢失。"
            "参数 tasks 是有序的任务描述列表；调用本工具**只登记计划，不执行任务**。"
        ),
        metadata=LOCAL_STATE_METADATA,
    ),
    StructuredTool.from_function(
        func=_update_task,
        name="update_task",
        description=(
            "更新某一步子任务的状态（pending 待办 / in_progress 进行中 / completed 已完成 / "
            "blocked 被卡住）。每完成一步就立刻回报，不要攒到最后一次性提交。"
            "参数 task_id 是计划里的编号（如 t1）；note 可写一句完成结论或卡住的原因。"
        ),
        metadata=LOCAL_STATE_METADATA,
    ),
]


__all__ = [
    "TODOS_STATE_KEY",
    "TASK_STATUSES",
    "STATUS_MARKS",
    "MAX_TODO_ITEMS",
    "MAX_TODO_CHARS",
    "TaskStatus",
    "PLANNING_GUIDE",
    "PLANNER_TOOL_NAMES",
    "planner_tools",
    "TodoItem",
    "normalize_todos",
    "build_plan",
    "apply_status",
    "render_plan_block",
    "plan_summary",
]

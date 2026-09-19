"""工具副作用声明机制 —— HITL 审批策略的唯一真源（第 145 轮 · 批 B1）。

## 为什么要有这个模块

在本模块之前，「哪个工具要人工审批」由业务侧的一句手写名单决定：

    _APPROVAL_GATED_INTENTS = frozenset({"save_candidate"})

那是**审批白名单** —— 默认「不审批」。漏写的后果是**漏审批**：新增一个写库
工具，没人记得去改这个 frozenset，它就永远不会被审批；而且**不报错、测试全绿**。
（这是第 141 轮评审「设计不合理清单 #3」：「安全属性靠人记得去改一个 frozenset」。）

本模块把方向**反转**为**只读豁免**：

| | 旧形态 | 新形态 |
|---|---|---|
| 判据来源 | 业务侧手写「写者名单」 | 工具**自己**声明的 `metadata` |
| 默认（未声明） | 不审批 | **审批** |
| 漏写后果 | 漏审批（不安全、不可见） | 多审批（安全、用户立刻察觉） |

判据函数 `has_side_effects()` 的默认分支返回 **True**（fail-closed）：
**未显式声明为只读的工具，一律视为有副作用、一律获得审批包装。**

## 三档判定（优先级从高到低）

1. `tool.metadata["side_effects"] is False` ⇒ 只读，免审批；
2. `tool.metadata["side_effects"] is True` ⇒ 有副作用 ⇒ 审批；
3. **没有** `side_effects` 键 ⇒ **有副作用** ⇒ 审批（fail-closed 兜底）。

## 第三档：「只写本地 state」（第 148 轮 · 批 C3）

上面两档漏掉了一类工具：**只改本 Agent 自己的图状态**、不碰外部世界的工具
（自主规划器的 `plan_tasks` / `update_task` —— 见 `ai_infra/plan.py`）。

它既**不是只读**（确实在改东西），也**不该要审批**（改的是自己的计划清单，
不可逆性为零、下一次规划就能整体覆盖；让用户为每一步计划点「批准」是把
规划器变成噪音源）。二选一都会写错，因此显式开出第三档：

    LOCAL_STATE_METADATA = {"side_effects": False, "writes_local_state": True}

★ 它与「只读」**不是一回事** —— `declared_local_state()` 可区分，门禁据此把
  「写动词名 + 本地状态声明」与「写动词名 + 纯只读声明」分开处置。

★ 但第三档**不是自由通道**：声明 local_state 的工具名必须在受控集合
  `LOCAL_STATE_TOOL_NAMES` 里，否则 `local_state_violations()` 报违规。
  于是「把某个真写库工具声明成 local_state 以躲开审批」走不通 ——
  受控集合硬编码在 infra 侧，加名字必须同步改门禁，而门禁会与真实工具名对账。

## 怎么用（业务侧工具定义处）

    from ai_infra.tools.side_effects import READ_ONLY_METADATA, SIDE_EFFECT_METADATA

    StructuredTool.from_function(
        coroutine=_search_faq_tool,          # 只读：查 FAQ
        name="search_faq",
        description="...",
        metadata=READ_ONLY_METADATA,         # ← 显式声明「本工具无外部副作用」
    )

    StructuredTool.from_function(
        coroutine=_create_ticket_tool,       # 写 PG：cs_tickets
        name="create_ticket",
        description="...",
        metadata=SIDE_EFFECT_METADATA,       # ← 显式声明「本工具有外部副作用」
    )

## 分层约束（★ 本模块的硬边界）

本模块**不得出现任何业务工具名**。`ai_infra` 是基础设施层，它的字符串门禁
`tests/test_infra_layering.py::test_ai_infra_string_literals_have_no_business_content`
会当场拦下业务词（`listing` / `asin` / `客服` / `选品` …）。

★ 这不是假想的约束 —— **本模块的第一版就是这么被拦下的**：那一版把 52 个只读
  工具名硬编码成了 `READ_ONLY_TOOLS = frozenset({...})`，跑测试时该门禁立刻变红。
  这是**门禁按设计工作**，不是误报；改法是「业务名留在业务侧、机制留在 infra 侧」。
  留此记录，防止下次又有人（或我自己）想着「在 infra 里放一份方便复用的名单」。

## 门禁在哪里

* `tests/test_hitl_policy.py` —— 声明完整性、写动词不得被豁免、推导结果正确；
* `tests/test_hitl_wiring.py` —— 装配点真实形态（审批名单、checkpointer 同现）；
* 反向注入：把某工具的声明从 `SIDE_EFFECT` 改成 `READ_ONLY` ⇒ 必红（见留底）。
"""

from __future__ import annotations

from typing import Any, Iterable

#: 工具 `metadata` 里声明副作用的键名。
SIDE_EFFECT_METADATA_KEY = "side_effects"

#: `local_state` 声明的键名（与 `SIDE_EFFECT_METADATA_KEY` 并列，互不替代）。
LOCAL_STATE_METADATA_KEY = "writes_local_state"

#: 声明「**只读**、无外部副作用」——免人工审批。
#: ⚠️ 只在「该工具什么状态都不改、也不产生不可逆外部动作」时才用它。
#: 若它会改 **Agent 自己的图状态**，用 `LOCAL_STATE_METADATA`（下一行），
#: 不要用本常量 —— 两者的语义不同，判据也不同（见模块 docstring 第三档）。
READ_ONLY_METADATA: dict = {SIDE_EFFECT_METADATA_KEY: False}

#: 声明「只写**本 Agent 自己的图状态**，无外部副作用」——免人工审批。
#: ⚠️ 只有 `LOCAL_STATE_TOOL_NAMES` 里的工具名才允许用它（否则门禁红）。
LOCAL_STATE_METADATA: dict = {
    SIDE_EFFECT_METADATA_KEY: False,
    LOCAL_STATE_METADATA_KEY: True,
}

#: **唯一**被允许声明 `LOCAL_STATE_METADATA` 的工具名（受控集合）。
#:
#: ★ 这两个名字的真源在 `ai_infra/plan.py`（`PLANNER_TOOL_NAMES` + `planner_tools`），
#:   这里是一份**镜像**；`tests/test_agent_plan.py` 会做双向对账
#:   （集合逐字相等），任一侧单独改名都会红。
#: ★ 为什么不 import `plan.py` 拿真源：那会形成 tools → plan 的依赖，
#:   而 plan 反过来要 import 本模块的 `LOCAL_STATE_METADATA` ⇒ 循环 import。
#:   用「硬编码 + 门禁对账」代替 import，是这里唯一不引入环的写法。
LOCAL_STATE_TOOL_NAMES: frozenset = frozenset({"plan_tasks", "update_task"})

#: 声明「**有**外部副作用」——须人工审批。
#: 与「不写 metadata」等价（fail-closed），但显式写出可自文档化、也可被门禁枚举。
SIDE_EFFECT_METADATA: dict = {SIDE_EFFECT_METADATA_KEY: True}

#: 「写动词」前缀 —— 工具名以这些词开头 ⇒ **绝不允许**被声明为只读。
#:
#: ★ 这是门禁的**独立第二判据**：即使有人（或反向注入）手工把某个写库工具的
#:   `metadata` 改成 `READ_ONLY_METADATA`，这条也会立刻变红。
#: ★ 为什么用「名字」而不是「追调用链」：写库入口往往跳 3–4 跳
#:   （tool → agent._save_xxx → _write_xxx → 门面 create_xxx），静态追链既脆弱
#:   又会漏判 —— 实测只跳 1 跳时，全仓 54 个工具里只抓到 1 个写库工具，
#:   漏掉了另一个真写库的。名字判据是**廉价的强信号**，与运行时用例
#:   （真数 `create_candidate` 调用次数那一类）形成「静态 + 运行时」双证据。
WRITE_VERB_PREFIXES: tuple[str, ...] = (
    "create_",
    "save_",
    "update_",
    "delete_",
    "insert_",
    "upsert_",
    "persist_",
    "write_",
    "publish_",
    "send_",
    "submit_",
    "remove_",
)


# ============================================================
# 判据
# ============================================================


def declared_side_effects(tool: Any) -> "bool | None":
    """读工具**自带**的显式声明。返回 `True` / `False` / `None`（未声明）。"""
    md = getattr(tool, "metadata", None)
    if isinstance(md, dict) and SIDE_EFFECT_METADATA_KEY in md:
        return bool(md[SIDE_EFFECT_METADATA_KEY])
    return None


def is_declared(tool: Any) -> bool:
    """该工具是否**显式**声明过副作用（供门禁要求「全部工具都必须表态」）。"""
    return declared_side_effects(tool) is not None


def has_side_effects(tool: Any) -> bool:
    """该工具是否需要人工审批（= 是否有外部副作用）。

    ★ **fail-closed**：三档判定的兜底是 `True`。
      未声明为只读的工具一律按「有副作用」处理 —— 于是「新增写库工具但忘了
      声明」的后果是**多一次审批**（安全方向、且用户立刻察觉），
      而不是**静默不审批**（危险方向、且无人察觉）。
    """
    declared = declared_side_effects(tool)
    if declared is not None:
        return declared
    return True


def derive_hitl_tools(tools: Iterable[Any]) -> list[str]:
    """从工具集合推导出**应当**获得审批包装的工具名（唯一实现）。

    ★ 这是 `BaseAgent._wrap_hitl_tools()` 的输入。它取代了原来散在业务侧的
      手写 `hitl_tools=["save_candidate"]` ——「策略」从此只有一处，
      Agent 侧不再需要（也不应该有能力）自己声明哪个工具要审批。
    """
    return sorted(t.name for t in tools if has_side_effects(t))


def declared_local_state(tool: Any) -> bool:
    """该工具是否显式声明「只写本地 state」（第三档）。"""
    md = getattr(tool, "metadata", None)
    if isinstance(md, dict):
        return bool(md.get(LOCAL_STATE_METADATA_KEY))
    return False


def write_verb_violations(tools: Iterable[Any]) -> list[str]:
    """返回「名字像写操作、却被声明为只读」的工具名（应为空）。

    独立于 `has_side_effects()` 的第二判据 —— 即使声明被写坏也能咬住。

    ★ 第 148 轮收紧：判据里的「只读」现在**排除**了声明为 `local_state` 的工具。
      排除是有意的，且**没有放宽**任何东西 ——
      原来的表达式 `declared_side_effects(t) is False` 把两类工具混在一起：
        · 真·只读（`READ_ONLY_METADATA`）—— 名字却像写操作 ⇒ 应当违规；
        · 只写本地 state（`LOCAL_STATE_METADATA`）—— 名字像写操作 ⇒ 本来就该写，
          违规才怪。
      现在两者分开，后者交给 `local_state_violations()` 用**受控集合**兜底。
      两条判据合起来，想借 local_state 绕过审批必须同时闯过两关。
    """
    bad = []
    for t in tools:
        name = getattr(t, "name", "") or ""
        if (
            name.startswith(WRITE_VERB_PREFIXES)
            and declared_side_effects(t) is False
            and not declared_local_state(t)
        ):
            bad.append(name)
    return sorted(bad)


def local_state_violations(tools: Iterable[Any]) -> list[str]:
    """返回「声明了 local_state、却不在受控集合里」的工具名（应为空）。

    ★ 为什么需要这条独立判据：`LOCAL_STATE_METADATA` 会把 `side_effects` 一并
      写成 `False`，于是它对 `write_verb_violations()` 是**免疫**的。
      也就是说，只要有人给一个真写库的工具挂上 `LOCAL_STATE_METADATA`，
      它就能既躲开审批、又不触发任何既有判据 —— 这正是本仓最警惕的那类
      「静默失效」。本条把那个缺口堵上：受控集合之外的 local_state 声明一律违规。
    """
    bad = []
    for t in tools:
        name = getattr(t, "name", "") or ""
        if declared_local_state(t) and name not in LOCAL_STATE_TOOL_NAMES:
            bad.append(name)
    return sorted(bad)


__all__ = [
    "SIDE_EFFECT_METADATA_KEY",
    "LOCAL_STATE_METADATA_KEY",
    "READ_ONLY_METADATA",
    "SIDE_EFFECT_METADATA",
    "LOCAL_STATE_METADATA",
    "LOCAL_STATE_TOOL_NAMES",
    "WRITE_VERB_PREFIXES",
    "declared_side_effects",
    "is_declared",
    "has_side_effects",
    "declared_local_state",
    "derive_hitl_tools",
    "write_verb_violations",
    "local_state_violations",
]

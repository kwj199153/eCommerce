# -*- coding: utf-8 -*-
"""图递归兜底 —— LangGraph「超步」上限的**唯一口径**（第 400 轮 · P2）

==============================================================================
★ 这个模块解决两件事
==============================================================================

1. **递归上限过去是"隐形的"**：全仓 `recursion_limit` **零命中** ⇒ 用的是
   LangGraph 的默认值 25。于是同一件"最多转几圈"的事有**两套不相干的数字**：

   | 谁在管 | 单位 | 在哪 |
   |---|---|---|
   | `AgentBudget.max_iterations`（默认 10，店秘书 6） | **模型轮次** | `_should_continue()` |
   | LangGraph 默认 `recursion_limit = 25` | **超步**（模型节点 + 工具节点各 1） | 图执行器 |

   两者单位不同、量级相近，谁也不看谁。后果分两种：
     · `2 × max_iterations + 松弛 > 25` ⇒ 图会**先**撞上 `GraphRecursionError`，
       而 `_should_continue` 那条"到点就收尾、正常回话"的路径**永远走不到**；
       用户拿到的是一个英文异常而不是一句人话。
     · 反过来（上限远大于轮次）⇒ 兜底形同虚设，真跑飞了要等很久才爆。
   ⇒ 本模块把上限**从 `max_iterations` 推出来**，让两套数字变成一套。

2. **超限时抛给调用方的是原始异常**（本仓此前就是这样）：`GraphRecursionError`
   继承 `RecursionError` → `RuntimeError` → `Exception`，于是它会被各种
   `except Exception` 顺手接住，日志里看到的是一行 `recursion limit reached`，
   既没有 Agent 名、也没有"我该做什么"。SSE 那条链会把它当成普通失败转发。
   ⇒ 本模块把它翻译成 `AgentRecursionExceeded`：**带兜底话术的领域异常**。

==============================================================================
★ 为什么抛异常，而不是返回一段"兜底 state"
==============================================================================
`run_session()` 的契约是「返回**原始** state」。给它合成一条 assistant 消息
塞进 `messages` 看起来更友好，但那条消息会被调用方**当成本轮真实产出**继续
落库 / 下发 —— 于是数据库里多出一条"模型说过、其实模型没说"的话。
那正是本仓反复钉的那类形态：**看起来有数据，其实是假的**。

⇒ 超限是**这次调用失败**，不是"这次调用的结果是这句话"。
  兜底话术挂在异常的 `str()` 上（SSE / 日志都直接读它），
  调用方想换文案可以 `except AgentRecursionExceeded as e: e.friendly`。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from langgraph.errors import GraphRecursionError

from core.logger import get_logger

__all__ = [
    "AgentRecursionExceeded",
    "RECURSION_LIMIT_MARGIN",
    "apply_limit",
    "is_recursion_error",
    "recursion_limit_for",
]

logger = get_logger("ai_infra.recursion_guard")

#: 超步上限相对 `2 × max_iterations` 的**额外松弛**。
#:
#: ★ 为什么留 8：一轮完整交互除了「模型 + 工具」两个超步，还可能多出
#:   规划器（`plan_tasks` / `update_task`）、HITL 包装、以及子图进出。
#:   留得太紧 ⇒ 正常的多步任务被误判成"跑飞"（用户看到兜底话术，而其实再走
#:   一步就答完了）；留得太松 ⇒ 真跑飞时要等很久。8 是"多 4 轮额外往返"的量级，
#:   与 `AgentBudget.max_iterations` 的默认粒度（10）同一数量级。
RECURSION_LIMIT_MARGIN = 8


def recursion_limit_for(max_iterations: int) -> int:
    """按**模型轮次**预算推出图递归上限（超步数）。

    ★ 比例 2 的依据：一次 ReAct 迭代在图里至少占 2 个超步
      （`agent` 节点 + `tools` 节点）。没有工具调用的那一轮只占 1 个，
      所以 2 是**上界估计**、配松弛一起用是安全的。

    ★ 入参非法（<=0 / 非 int）时按下限 1 处理并 **warn**：上限算成 0 会让
      LangGraph 第二次超步就报错，而那个错误长得像"图坏了"，归因会跑偏。
    """
    try:
        n = int(max_iterations)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        logger.warning(
            f"⚠️ recursion_limit_for 收到非法的 max_iterations={max_iterations!r}，按 1 处理"
            "（上限算成 0 会让第二次超步就报错，且看起来像图配置错误）"
        )
        n = 1
    return 2 * n + RECURSION_LIMIT_MARGIN


def apply_limit(
    config: Mapping[str, Any], max_iterations: int
) -> Dict[str, Any]:
    """把 `recursion_limit` 写进一份**新的** config（不改调用方那份）。

    ★ 为什么不原地改：`graph_for_session()` 返回的 `cfg` 会被多个入口共用，
      原地写会让"这一次调用的上限"渗透到下一次（本仓踩过同族：`_forward_headers`
      不清会带上一轮的 `authorization`）。
    ★ `configurable` 子字典也要复制：只浅拷外层会与调用方共享同一个
      `configurable`，写 `thread_id` 之类时同样互相污染。
    """
    out: Dict[str, Any] = dict(config or {})
    inner = out.get("configurable")
    if isinstance(inner, Mapping):
        out["configurable"] = dict(inner)
    out["recursion_limit"] = recursion_limit_for(max_iterations)
    return out


def is_recursion_error(exc: BaseException) -> bool:
    """是不是"图跑超步数了"。

    ★ 必须按**类型**判而不是按文案判：`GraphRecursionError` 继承
      `RecursionError`，而 `RecursionError` 在别的语境下也会出现
      （真的递归溢出）。按文案判会把这三种混成一个 —— 本仓的判据纪律：
      判后端行为只看客观事实，别拿错误文案当类型。
    """
    return isinstance(exc, GraphRecursionError)


class AgentRecursionExceeded(RuntimeError):
    """图跑到超步上限 —— 带**人话兜底**的领域异常。

    属性：
        agent_name 哪个 Agent（6 个 Agent 共用一个入口时，日志里必须能分开）
        limit      本轮的 `recursion_limit`
        friendly   给用户看的那句话（`str(e)` 同此）

    ★ 继承 `RuntimeError` 而不是新造 `Exception` 分支：既有代码里
      `except RuntimeError` 的地方（若有）能接住它，不至于变成"谁都不认"的类型。
    """

    def __init__(self, agent_name: str, limit: int) -> None:
        self.agent_name = agent_name or "agent"
        self.limit = int(limit)
        self.friendly = (
            f"这轮任务太绕了，我在「{self.agent_name}」里连续尝试了 "
            f"{self.limit} 个步骤还没收敛，先停下来免得白烧额度。\n"
            "建议：把问题拆小一点再问（比如先只做其中一步），"
            "或者告诉我更具体的范围 / 条件，我就能一次走完。"
        )
        super().__init__(self.friendly)

    def __str__(self) -> str:  # pragma: no cover - 直通，仅明确意图
        return self.friendly


def raise_exceeded(agent_name: str, limit: Optional[int], exc: BaseException) -> None:
    """统一出口：打一条**带上下文**的 error 日志，再抛领域异常。

    ★ 日志里必须同时出现 Agent 名与上限：只打 `recursion limit reached`
      的话，6 个 Agent 共用同一张日志流时根本分不出是谁跑飞了。
    """
    _limit = int(limit or 0)
    logger.error(
        f"🛑 [{agent_name}] 图递归超限（recursion_limit={_limit}）—— "
        f"原始异常 {type(exc).__name__}: {str(exc)[:200]}"
    )
    raise AgentRecursionExceeded(agent_name, _limit) from exc

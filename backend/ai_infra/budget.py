"""
Agent 运行预算 —— 迭代 / token / 墙钟三维上限的**唯一真源**。

为什么要单独一个模块（第 145 轮 · 批 C5）：

1. `max_iterations` 此前是**业务 Agent 各写一个整数字面量**的构造参数
   （6 / 4 / 4，基类兜底 10）。数字本身没有名字、没有依据、也没有取值校验 ——
   写 0 或写负数的症状是「第一个节点就判超限」，表现为「模型再也不调用工具」，
   与「模型不听话」几乎无法区分。

2. 它**只有一个维度**。一次 LLM 调用烧掉几万 token、或者一次工具调用挂住
   几分钟，迭代计数器都不会动 —— 「预算」这个词在此前名不副实。

本模块只提供**机制**：预算的数据形状、判定函数、通用档位、超限异常。
「哪个 Agent 用哪一档」由业务侧声明 —— `ai_infra` 不认识任何业务 Agent 名
（分层门禁 `tests/test_infra_layering.py` 的字符串扫描会拦）。

★ 关于那三个阈值的**成色**（不要误读）：

    `max_iterations` 是**行为口径**（它决定 Agent 最多走几轮，改动会直接改变
    功能，且三处取值都有历史依据，见各业务侧的档位选择）。

    `max_tokens` / `max_seconds` 目前是**防失控护栏**，不是节流阀 —— 它们的
    量级是「正常工作绝不会碰到，只有跑飞了才会碰到」。★ 它们**未经实测标定**：
    要把它们下调成真正的节流，先量出该档位真实耗用的 P95，再按 P95 的倍数定，
    不要凭感觉改小（改小了症状是「本来能答完的会话被截断」，且只在长会话复现）。
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Optional

#: 预算的三个维度。顺序即**判定顺序**（先迭代、后 token、再墙钟）。
#: ★ 顺序固定是有意的：同一组耗用值必须永远给出同一个结论 ——
#:   否则「同时超限两个维度时报哪一个」就成了随机量，断言无法稳定。
DIMENSIONS: tuple[str, ...] = ("iterations", "tokens", "seconds")


@dataclass(frozen=True)
class AgentBudget:
    """一次会话（一轮图执行）允许消耗的资源上限。

    frozen：预算在运行期不可变。它会被多个并发会话共享（Agent 实例是进程内
    单例），可变预算等于把一个请求的耗用记账到另一个请求上。
    """

    max_iterations: int = 10
    max_tokens: int = 300_000
    max_seconds: float = 600.0
    label: str = "standard"

    def __post_init__(self) -> None:
        # fail-fast：预算必须为正。
        # ★ 为什么不在判定里兜底：把非正数当「没有限制」是 fail-open；
        #   把非正数当「立刻超限」是静默的能力删除（症状与模型不听话重合）。
        #   两种都不能要 —— 在构造点直接拒绝，错误暴露在写代码的人面前。
        #   `bool` 要单独挡：`True <= 0` 是 False，会从数值校验里溜过去。
        for name in ("max_iterations", "max_tokens", "max_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(
                    f"AgentBudget.{name} 必须为正数（当前 {value!r}）——"
                    f"非正预算会退化成「一进入就超限」或「永不超限」两种假象"
                )
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("AgentBudget.label 必须是非空字符串（用于日志与档位断言）")

    def with_max_iterations(self, n: int) -> "AgentBudget":
        """派生一个只改写迭代上限的预算。

        ★ 存在的唯一理由：兼容既有的 `max_iterations=` 形参
          （`BaseAgent.__init__` 与 `test_max_iterations_strips_orphan_tool_calls`）。
          它**不构成第二份真源** —— 返回的是一个新 `AgentBudget`，
          此后一切判定仍只读 `self.budget`；不存在「形参一份、预算一份」。
        """
        return replace(self, max_iterations=n)


#: 通用档位（**不含任何业务 Agent 名**）。业务侧按「这类 Agent 的工作方式」选档：
#:   · `BUDGET_ROUTER`      —— 单次决策 + 一串工具调用，用完即答（子层路由）
#:   · `BUDGET_INTERACTIVE` —— 多轮对话，边问边查（面向用户的主 Agent）
#:   · `BUDGET_STANDARD`    —— 默认档（`DEFAULT_BUDGET`）
BUDGET_ROUTER = AgentBudget(
    max_iterations=4, max_tokens=120_000, max_seconds=240.0, label="router"
)
BUDGET_INTERACTIVE = AgentBudget(
    max_iterations=6, max_tokens=200_000, max_seconds=420.0, label="interactive"
)
BUDGET_STANDARD = AgentBudget()
DEFAULT_BUDGET = BUDGET_STANDARD


@dataclass(frozen=True)
class BudgetVerdict:
    """一次预算判定的结论（`None` 表示未超限，故用 `Optional[BudgetVerdict]` 承载）。"""

    dimension: str
    used: float
    limit: float
    label: str

    @property
    def message(self) -> str:
        return (
            f"已达运行预算上限（{self.dimension}：已用 {self.used:g} / 上限 {self.limit:g}，"
            f"档位 {self.label}）"
        )


def check_budget(used: dict, budget: AgentBudget) -> Optional[BudgetVerdict]:
    """按 `DIMENSIONS` 顺序检查，返回**首个**超限维度；全部未超限 ⇒ `None`。

    `used` 里**只放被检查的维度** —— 缺省的维度视为「未消耗」。这样同一个函数
    同时服务两个判定点，而它们的可见信息本来就不同：
      · 图节点内：看得到 `iterations` / `tokens`（墙钟起点在入口层，节点看不到）
      · 入口层　：看得到 `seconds`
    """
    for dimension in DIMENSIONS:
        if dimension not in used:
            continue
        limit = getattr(budget, "max_" + dimension)
        if used[dimension] >= limit:
            return BudgetVerdict(
                dimension=dimension,
                used=used[dimension],
                limit=limit,
                label=budget.label,
            )
    return None


class BudgetExceeded(RuntimeError):
    """墙钟预算耗尽 —— 由**入口层**抛出（`run_session` / `stream_session`）。

    ★ 为什么只有入口层抛、图节点内不抛：
      · 入口层：一次调用超时 ⇒ 这次调用就是失败了，没有「部分结果」可保 ⇒ 抛，
        让调用方明确处理。
      · 图节点内（`_llm_call_node`）：此刻图里已经有**跑出来的消息与工具结果**。
        在那里抛异常会把它们全部丢掉，用户从「拿到半截结果 + 明确告知被截断」
        退化成「什么都没有」。所以节点内只做 **截断 + 标记**，由终态节点
        （`_respond_node`）把它写成显式结论。
      两者不是「一处做了另一处没做」，而是**同一个预算在两个层次上的两种正确反应**。
    """

    def __init__(self, verdict: BudgetVerdict) -> None:
        super().__init__(verdict.message)
        self.verdict = verdict


# ---------------------------------------------------------------- import 期自检
#
# `DIMENSIONS` 与 `AgentBudget` 的 `max_*` 字段必须一一对应。否则「加了一个维度」
# 会变成静默不生效：`check_budget` 里的 `getattr` 抛 AttributeError，而调用点
# 通常吞异常 ⇒ 症状是「新预算从不触发」，没有任何报错。
# ★ 用 raise 而不是 assert：`python -O` 会剥掉 assert，门禁不能靠它。
_BUDGET_FIELDS = {f.name for f in fields(AgentBudget) if f.name.startswith("max_")}
_EXPECTED_FIELDS = {"max_" + d for d in DIMENSIONS}
if _BUDGET_FIELDS != _EXPECTED_FIELDS:
    raise RuntimeError(
        f"预算维度与字段不一致：DIMENSIONS={DIMENSIONS} 需要 {sorted(_EXPECTED_FIELDS)}，"
        f"而 AgentBudget 实际有 {sorted(_BUDGET_FIELDS)}"
    )

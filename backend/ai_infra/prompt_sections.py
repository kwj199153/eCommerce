"""system prompt 的**外部段落**注册表 —— 机制层（第 152 轮 · 批 C2 读口）。

问题形态
--------
`BaseAgent` 每轮 LLM 调用都会拼一份 system prompt：业务 Agent 自己写的提示词
（子类 `system_prompt`），加上开启规划时的规划说明与当前计划。但还有第三类内容，
它**不属于任何业务 Agent，而属于这个人** —— 跨会话积累下来的长期偏好与背景。
它必须出现在**每一次** LLM 调用里；只在某一轮出现等于没记住。

本模块提供的是**注册表**，不是内容：

    register_prompt_section(name, provider)   # 业务层调用（import 时执行）
    collect_prompt_sections(ctx)              # BaseAgent 调用（每轮执行）

「谁提供」这一问的答案住在基础设施层；「内容长什么样」（读哪张表、怎么渲染、
拿什么当例子）全在业务模块。这一刀与 `ai_infra.llm` 的
`register_prompt_template` 同源，判据也一样：**机制可以住在 infra，
语料一旦住进来就是 L3 那类泄漏**（本仓真实发生过，见
`tests/test_infra_layering.py` 开头那张表）。

三条判据
--------
① **本层的注册表默认必须为空** —— 一个段落都不自带（AST 断言在
   `tests/test_infra_layering.py::test_prompt_section_registry_is_empty_by_default`）。
② **重名注册必须当场报错**，不能静默覆盖：两个模块都想叫同一个名字时，
   后注册的那个会让先注册的**悄悄消失**，而两边都不报错 ——
   表现是「A 的内容不再注入了」，没有任何一处日志或测试会红。
③ **单个 provider 失败不得拖垮整轮对话**。注入块是**增益**，不是门禁：
   失败 ⇒ 这一段本次不注入，但其余段落照常注入、这一轮照常发给模型。

★ ③ 为什么**不算**「静默失败」
-----------------------------
本项目的铁律是「失败必须与没做可分」。这里满足：
  · 每个失败都有一条带**段落名与异常类型**的 WARNING；
  · `collect_prompt_sections()` 把 `failed` 一并**返回给调用方**，
    `BaseAgent` 据此再记一条带 agent 名的日志 ——
    「注入了几段 / 失败了几段」在日志里是可读的差异。

反过来若在这里抛异常，代价是**整轮对话挂掉**：让增益的故障去否决主流程，
是更差的选择。所以这里的选择是「降级 + 可观测」，不是「静默吞掉」。
（同族判据：降级路径禁用「全 0」兜底 —— 兜底值必须能被识别。）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptContext:
    """一次 LLM 调用可用的**身份**（不含任何业务维度）。

    ★ 只有两个字段，且都来自**服务端**：
      · `agent_name` —— 哪个 Agent 在说话（provider 可据此决定注不注入）；
      · `user_id` —— 为谁说话；空 = 匿名。

    ★ 刻意**不带**店铺 / 平台 / 商品这类维度。长期记忆的归属是**用户级**
      （业务侧拍板结论），而往这里加业务维度等于让基础设施层开始认识业务概念
      —— 那正是 L4 那类泄漏（`AgentState.metadata` 曾硬编码 `tenant_id` /
      `shop_id` 四个键，只写不读）。将来真需要更细的归属，正确的做法是
      provider 自己去读它的上下文，而不是把这个 dataclass 变成业务字段的垃圾桶。
    """

    agent_name: str = ""
    user_id: Optional[str] = None


#: 段落提供者：给一个身份，返回一段可拼进 system prompt 的文本。
#: 返回空串 = 本次不注入（**不是**错误，是常态：新用户还没有记忆）。
PromptSectionProvider = Callable[[PromptContext], Awaitable[str]]

#: 注册表（模块级）。★ 定义处必须为空 —— 由 AST 门禁钉住（判据 ①）。
#: dict 在 Python 3.7+ **保序**，所以注册顺序 = 注入顺序，不需要另一个序号字段。
_SECTIONS: dict = {}


def register_prompt_section(name: str, provider: PromptSectionProvider) -> None:
    """登记一个段落提供者。

    ★ 重名**直接拒绝**（判据 ②）：静默覆盖会让先注册者的内容消失，
      且调用方完全看不出来。报错把「两个模块撞名」变成一个当场可见的冲突。
    """
    key = str(name or "").strip()
    if not key:
        raise ValueError("段落名不能为空 —— 空名会让出错时无法指出是哪一段")
    if not callable(provider):
        raise TypeError(f"段落 {key!r} 的提供者不可调用：{provider!r}")
    if key in _SECTIONS:
        raise ValueError(
            f"段落名 {key!r} 已被注册（{_SECTIONS[key]!r}）—— 重名会静默覆盖先注册的，"
            f"所以这里直接拒绝。请换一个名字，或把两处归到同一个提供者。"
        )
    _SECTIONS[key] = provider
    logger.debug("prompt section registered: %s", key)


def registered_sections() -> tuple:
    """已登记的段落名（**有序**，顺序 = 注入顺序）。

    ★ 返回元组而不是那个 dict：调用方拿到 dict 就能绕过 `register_*` 往里塞东西，
      于是判据 ②（重名拒绝）形同虚设。
    """
    return tuple(_SECTIONS)


@dataclass(frozen=True)
class CollectedSections:
    """一次收集的结果：成功注入了哪几段、哪几段失败了。

    ★ 刻意**不实现 `__bool__`**：`if sections:` 会在「一段都没注入但有一段失败」
      时判为假 —— 那正是最需要被看见的情形。调用方请显式用 `.text` 或 `.failed`。
    """

    blocks: tuple = ()
    failed: tuple = ()

    @property
    def text(self) -> str:
        """拼好的注入文本（空 ⇒ 调用方不应往 system prompt 里加任何东西）。"""
        return "\n\n".join(self.blocks)


async def collect_prompt_sections(
    ctx: PromptContext, *, registry: Optional[Mapping] = None
) -> CollectedSections:
    """收集所有段落（逐个 await，**逐个隔离失败**）。

    ★ `registry` 只为可测性存在：不传就用模块级注册表。测试要验证「失败隔离」
      时不必去动全局那个 dict（动了全局就会污染同进程的其它用例 ——
      ContextVar 与模块级全局在本仓都真实咬过人）。

    ★ 每次现算、不缓存。缓存一份渲染结果等于多一份可能过期的副本 ——
      而记忆会在会话进行中被工具改写，正是最不该缓存的那类数据。
      （同族判据见 `ai_infra.plan.render_plan_block`：每轮现算，真源只在状态里。）
    """
    reg = _SECTIONS if registry is None else registry
    blocks: list = []
    failed: list = []

    for name, provider in list(reg.items()):
        try:
            text = await provider(ctx)
        except Exception as exc:  # noqa: BLE001 —— 判据 ③：逐段隔离，见模块 docstring
            failed.append(name)
            logger.warning(
                "prompt section %r failed and was skipped this turn: %s: %s",
                name,
                type(exc).__name__,
                exc,
            )
            continue
        # 非字符串 / 只有空白 ⇒ 视为「本次不注入」。不报错：provider 用空串
        # 表达「这个人现在没有可注入的内容」是正常语义（判据 ③ 的边界）。
        if isinstance(text, str) and text.strip():
            blocks.append(text.strip())

    return CollectedSections(blocks=tuple(blocks), failed=tuple(failed))


__all__ = [
    "PromptContext",
    "PromptSectionProvider",
    "CollectedSections",
    "register_prompt_section",
    "registered_sections",
    "collect_prompt_sections",
]

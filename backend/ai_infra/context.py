"""
Agent 上下文窗口管理 —— 历史裁剪 + 旧工具结果折叠的**唯一真源**（第 147 轮 · 批 C4）。

## 为什么需要它

`_llm_call_node` 此前把 checkpointer 恢复的**全部历史**原样发给 LLM，只做了一件事：
`_sanitize_tool_call_pairing` 的**结构性**清洗（剔除孤儿 tool_call / ToolMessage）。
那是「让请求不被打回」的修复，**不减少一个字节**。

于是多轮会话的输入 token 单调增长：

  · `AgentBudget.max_tokens` 管的是「本轮**累计**耗用」，超了才截断 —— 它是**终局**；
  · 它管不住「**这一次**请求的输入有多大」。等到服务端以「上下文超长」拒绝时，
    失败点在对端，本地只剩一句 HTTP 400，而且**整条会话从此不可用**
    （每次恢复历史都会再次超长）。

## 本模块只提供机制

  · `ContextPolicy`   —— 裁剪档位的数据形状（阈值 + 保底轮数），不含任何 Agent 名
  · `trim_history()`  —— 纯函数：吃 messages，吐 (新 messages, `TrimReport`)

`ai_infra` 不认识任何业务 Agent / 工具名（`tests/test_infra_layering.py` 的字符串扫描会拦），
所以工具名一律**从消息对象上取**（`ToolMessage.name`），不写死。

## 两级动作（先折叠、后裁轮）

1. **折叠旧工具结果**：非当前轮的 `ToolMessage`，内容超长就换成
   `[已折叠]` 前缀 + 头部摘要 + 原始字符数。★ 折叠后的 ToolMessage
   **保留原 `tool_call_id`** ⇒ 配对不断（断了会被对端打回）。
2. **裁掉最旧的历史轮**：仍超预算时，从**最旧**开始**整轮**删除
   （轮 = 一条 `HumanMessage` 到下一个 `HumanMessage` 之前）。整轮删保证
   `AIMessage(tool_calls)` 与它的 `ToolMessage` 同进同出。

## 四条不变量（`tests/test_agent_context_trim.py` 逐条钉住）

  I1 最后一段（当前轮）**永不裁剪** —— 裁掉它等于把用户这次问的话删了
  I2 保底保留 `keep_recent_turns` 轮 —— 否则一次裁剪就把上下文炸成空
  I3 `tool_call_id` 配对在裁剪后仍然完整（不存在「有 ToolMessage 而没声明它的 AIMessage」）
  I4 消息**相对顺序**不变（只做删除与内容替换，不重排）

## 与 `AgentBudget` 的分工（两者都不是对方的兜底）

  · 预算   = 「跑多久 / 一共花多少」 ⇒ 超限是**终局**（截断 + 标记）
  · 上下文 = 「这一次发出去多大」   ⇒ 裁剪是**常态**（让会话继续跑下去）

★ 「没裁到位」必须显式声明：`TrimReport.over_budget` 为真表示
  保底轮数用尽后**仍超预算**。这时不能假装成功 —— 静默假装「已经裁好了」
  会把失败推迟到对端，且看不出是这里没做到（同族判据：降级路径禁用「全 0」兜底）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from ai_infra.llm.dashscope_client import estimate_tokens

__all__ = [
    "ContextPolicy",
    "TrimReport",
    "CONTEXT_STANDARD",
    "CONTEXT_INTERACTIVE",
    "CONTEXT_ROUTER",
    "DEFAULT_CONTEXT_POLICY",
    "trim_history",
]


@dataclass(frozen=True)
class ContextPolicy:
    """一次请求允许携带的**历史**上限（system prompt 不计入）。

    frozen：策略会被多个并发会话共享（Agent 实例是进程内单例），
    可变策略等于把一次请求的裁剪口径泄漏给另一次。

    阈值的**成色**（别误读，与 `AgentBudget` 的注释同族）：
      `max_input_tokens` 是**估算值**（见 `estimate_tokens`），用于裁剪决策，
      不是计费口径。它是「单次请求的历史预算」，与模型窗口之间刻意留了
      一个数量级的余量 —— 只要它远小于窗口，裁剪就永远不会把请求推到
      「超窗口」那一侧。
    """

    max_input_tokens: int = 24_000
    keep_recent_turns: int = 4
    fold_tool_result_chars: int = 600
    fold_head_chars: int = 240
    label: str = "standard"

    def __post_init__(self) -> None:
        # fail-fast，与 `AgentBudget.__post_init__` 同一判据：
        # 非正阈值会退化成两种假象 —— fail-open（永不裁剪）或静默的能力删除
        # （一上来就裁空）。两种都不能要，在构造点拒绝，错误暴露在写代码的人面前。
        # `bool` 要单独挡：`True <= 0` 是 False，会从数值校验里溜过去。
        for name in ("max_input_tokens", "keep_recent_turns",
                     "fold_tool_result_chars", "fold_head_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"ContextPolicy.{name} 必须为正整数（当前 {value!r}）——"
                    f"非正阈值会退化成「永不裁剪」或「一次裁空」两种假象"
                )
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("ContextPolicy.label 必须是非空字符串（用于日志与档位断言）")
        if self.fold_head_chars >= self.fold_tool_result_chars:
            # 头部比阈值还长 ⇒ 「折叠」后不比原文短，等于没折。
            # 这种配置不会报错，只会让每轮都白做一次字符串拼接。
            raise ValueError(
                f"fold_head_chars({self.fold_head_chars}) 必须小于 "
                f"fold_tool_result_chars({self.fold_tool_result_chars})，否则折叠不减少体积"
            )


#: 通用档位（**不含任何业务 Agent 名**）。业务侧按「这类 Agent 的工作方式」选档：
#:   · `CONTEXT_ROUTER`      —— 单次决策 + 一串工具调用，用完即答（子层路由）
#:   · `CONTEXT_INTERACTIVE` —— 多轮对话，边问边查（面向用户的主 Agent）
#:   · `CONTEXT_STANDARD`    —— 默认档（`DEFAULT_CONTEXT_POLICY`）
CONTEXT_STANDARD = ContextPolicy()
CONTEXT_INTERACTIVE = ContextPolicy(
    max_input_tokens=48_000, keep_recent_turns=8, label="interactive"
)
CONTEXT_ROUTER = ContextPolicy(
    max_input_tokens=12_000, keep_recent_turns=2, label="router"
)
DEFAULT_CONTEXT_POLICY = CONTEXT_STANDARD


@dataclass(frozen=True)
class TrimReport:
    """一次裁剪的结论（供日志与 `state["budget"]["context"]` 下游读取）。"""

    turns_total: int
    turns_kept: int
    turns_dropped: int
    folded_tool_results: int
    tokens_before: int
    tokens_after: int
    over_budget: bool
    label: str = "standard"

    @property
    def changed(self) -> bool:
        """本次是否真的动了消息（用于决定要不要打日志）。"""
        return bool(self.turns_dropped or self.folded_tool_results)

    def as_dict(self) -> dict:
        return {
            "turns_total": self.turns_total,
            "turns_kept": self.turns_kept,
            "turns_dropped": self.turns_dropped,
            "folded_tool_results": self.folded_tool_results,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "over_budget": self.over_budget,
            "label": self.label,
        }


_FOLD_PREFIX = "[已折叠]"
_FOLD_NOTE = "（完整结果已从本次上下文移除）"


def _text_of(msg: Any) -> str:
    """取消息的可算文本；非字符串内容（多模态部件）按 JSON 串近似。

    ★ 为什么要兜底而不是直接 `str(content)`：多模态消息的 content 是
      `list[dict]`，`str()` 出来是 Python repr —— 长度口径与真实文本差很远，
      会直接把预算算歪。JSON 串至少是确定性的。
    """
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        return str(content)


def _messages_tokens(messages: Sequence[Any]) -> int:
    """一组消息的估算 token 总量（逐条估算后求和，与计费口径无关）。"""
    return sum(estimate_tokens(len(_text_of(m))) for m in messages)


def _is_human(msg: Any) -> bool:
    """按**类名**判断，不在本层引入对具体消息库的 import 依赖。

    本模块是纯机制：测试可以喂轻量假对象，`_lan` 侧换实现也不影响它。
    """
    return msg.__class__.__name__ == "HumanMessage"


def _is_tool(msg: Any) -> bool:
    return msg.__class__.__name__ == "ToolMessage"


def _turn_spans(messages: Sequence[Any]) -> list[tuple[int, int]]:
    """按 `HumanMessage` 切「轮」，返回 `[(start, end), ...]`（end 不含）。

    ★ 第一轮的开头固定取 0：若历史以非 HumanMessage 起头（异常历史），
      把那段并入**第一轮**而不是让它独立成轮 —— 独立成轮的话它会被当作
      「最旧的轮」优先删掉，而它可能恰好是本轮的前置。宁可多留一段，
      也不要把无法判断归属的内容先删掉（同族判据：拿不到权威清单时保留旧值）。
    """
    if not messages:
        return []
    starts = [i for i, m in enumerate(messages) if _is_human(m)]
    if not starts:
        # 一条 HumanMessage 都没有 ⇒ 整块视为一轮，不裁（裁了就是全删）
        return [(0, len(messages))]
    spans: list[tuple[int, int]] = []
    for k, s in enumerate(starts):
        begin = 0 if k == 0 else s
        end = starts[k + 1] if k + 1 < len(starts) else len(messages)
        spans.append((begin, end))
    return spans


def _fold_one(msg: Any, policy: ContextPolicy) -> Any:
    """把一条超长 `ToolMessage` 的内容换成摘要；未超长或无法复制则原样返回。"""
    text = _text_of(msg)
    if len(text) <= policy.fold_tool_result_chars:
        return msg
    tool_name = getattr(msg, "name", None) or "?"
    head = text[: policy.fold_head_chars]
    folded = (
        f"{_FOLD_PREFIX} 工具 {tool_name} 返回 {len(text)} 字符，"
        f"摘要（前 {policy.fold_head_chars} 字符）：{head}…{_FOLD_NOTE}"
    )
    # ★ 用 model_copy 而不是新建对象：`tool_call_id` 与附加字段必须原样带走 ——
    #   丢了 tool_call_id 就会被对端判成孤儿消息，整条会话 400。
    if hasattr(msg, "model_copy"):
        return msg.model_copy(update={"content": folded})
    # 无法复制（轻量假对象）⇒ 不动它。宁可少折一条，也不要造出残缺消息。
    return msg


def trim_history(
    messages: Sequence[Any], policy: ContextPolicy
) -> tuple[list, TrimReport]:
    """按策略裁剪历史，返回 `(新消息列表, TrimReport)`。

    纯函数：不修改入参、不读全局、不发网络请求。同一输入 + 同一策略 ⇒ 同一输出
    （裁剪是**确定性**的，这样断言才稳定）。
    """
    msgs = list(messages)
    tokens_before = _messages_tokens(msgs)
    spans = _turn_spans(msgs)
    if not spans:
        return msgs, TrimReport(0, 0, 0, 0, 0, 0, False, policy.label)

    # ---- 阶段 1：折叠「非当前轮」的超长工具结果 ----
    # 当前轮（最后一段）不折叠：用户刚拿到的工具结果，模型正要基于它回答。
    current_start = spans[-1][0]
    out = list(msgs)
    folded = 0
    for i in range(0, current_start):
        if not _is_tool(out[i]):
            continue
        new_msg = _fold_one(out[i], policy)
        if new_msg is not out[i]:
            out[i] = new_msg
            folded += 1

    # ---- 阶段 2：仍超预算 ⇒ 从最旧开始整轮删 ----
    dropped = 0
    remaining = list(spans)
    while len(remaining) > policy.keep_recent_turns:
        if _messages_tokens(out) <= policy.max_input_tokens:
            break
        start, end = remaining[0]
        out = out[:start] + out[end:]
        remaining = remaining[1:]
        dropped += 1
        # 删掉 (end - start) 条消息 ⇒ 后续 span 的位置整体前移
        shift = end - start
        remaining = [(a - shift, b - shift) for a, b in remaining]

    tokens_after = _messages_tokens(out)
    return out, TrimReport(
        turns_total=len(spans),
        turns_kept=len(remaining),
        turns_dropped=dropped,
        folded_tool_results=folded,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        over_budget=tokens_after > policy.max_input_tokens,
        label=policy.label,
    )

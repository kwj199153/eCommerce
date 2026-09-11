"""
LLM 用量计量器（请求级）

背景：
    计费系统（core/billing/usage_tracker.py）原本只统计「API 调用次数」和
    「Agent 对话次数」，LLM 真实 token / 成本只活在 DashScopeLLM 的内存
    stats 里，从未落库 —— 导致 LLM 消耗与计费完全脱钩。

作用：
    在请求级 ContextVar 中累积本次请求内所有 LLM 调用的 token 与成本，
    由计费依赖（meter_agent_chat）在请求结束时一次性写入 subscriptions 表。

用法（LLM 客户端侧）：
    from core.billing.llm_meter import record_llm_usage
    record_llm_usage(input_tokens=..., output_tokens=..., cost=..., model="qwen-max")

用法（计费依赖侧）：
    reset_meter()          # 请求开始，开一个干净的计量器
    ...
    snap = snapshot()      # 请求结束，取快照落库
"""

import contextvars
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class LLMUsageMeter:
    """单次请求内的 LLM 用量累加器"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    models: Dict[str, int] = field(default_factory=dict)  # model -> 调用次数

    def add(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        model: Optional[str] = None,
    ) -> None:
        self.calls += 1
        self.input_tokens += max(0, int(input_tokens or 0))
        self.output_tokens += max(0, int(output_tokens or 0))
        self.total_tokens += max(0, int(input_tokens or 0)) + max(0, int(output_tokens or 0))
        self.cost += float(cost or 0.0)
        if model:
            self.models[model] = self.models.get(model, 0) + 1

    @property
    def is_empty(self) -> bool:
        return self.calls == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost": round(self.cost, 6),
            "models": dict(self.models),
        }


_meter_var: contextvars.ContextVar[Optional[LLMUsageMeter]] = contextvars.ContextVar(
    "llm_usage_meter", default=None
)


def reset_meter() -> LLMUsageMeter:
    """为当前请求开一个干净的计量器（请求开始时调用）"""
    meter = LLMUsageMeter()
    _meter_var.set(meter)
    return meter


def get_meter() -> Optional[LLMUsageMeter]:
    """获取当前请求的计量器（可能为 None，表示未开启计量）"""
    return _meter_var.get()


def record_llm_usage(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    model: Optional[str] = None,
) -> None:
    """
    记录一次 LLM 调用（由 LLM 客户端在每次调用后调用）。

    若当前请求未开启计量（get_meter() 为 None），则静默忽略——
    保证 LLM 客户端无需关心调用方是否在计量。
    """
    meter = _meter_var.get()
    if meter is None:
        return
    meter.add(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        model=model,
    )


def snapshot() -> LLMUsageMeter:
    """取当前请求计量器快照（请求结束时调用；无计量器时返回空对象）"""
    meter = _meter_var.get()
    return meter if meter is not None else LLMUsageMeter()

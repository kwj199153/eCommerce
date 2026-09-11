"""
LLM 客户端内部逻辑回归测试

覆盖：
1. 成本计算（按模型定价）
2. 无 usage 时的 token 估算
3. 每次调用都会写入请求级计量器（LLM 消耗 → 计费 的接点）
4. 降级：未开启计量器时不报错
"""

import pytest

from ai_infra.llm.dashscope_client import DashScopeLLM, LLMConfig, LLMResponse
from core.billing.llm_meter import reset_meter, snapshot


def test_compute_cost_uses_model_pricing():
    pricing = LLMConfig.PRICING.get("qwen-max")
    assert pricing, "qwen-max 应有定价配置"

    cost = DashScopeLLM._compute_cost("qwen-max", 1000, 1000)
    expected = pricing["input"] + pricing["output"]
    assert cost == pytest.approx(expected, abs=1e-9)


def test_compute_cost_unknown_model_uses_default():
    cost = DashScopeLLM._compute_cost("unknown-model", 1000, 1000)
    assert cost == pytest.approx(0.01 + 0.03, abs=1e-9)


def test_estimate_tokens():
    assert DashScopeLLM._estimate_tokens(0) == 0
    assert DashScopeLLM._estimate_tokens(150) == 100
    assert DashScopeLLM._estimate_tokens(1) >= 1


def test_update_stats_writes_to_meter():
    """LLM 调用后，计量器应收到 token / 成本"""
    reset_meter()
    client = DashScopeLLM.__new__(DashScopeLLM)      # 跳过 __init__（不需要网络）
    client._stats = type("S", (), {"total_calls": 0, "total_tokens": 0,
                                   "total_cost": 0.0, "errors": 0})()

    resp = LLMResponse(content="x", model="qwen-max", input_tokens=100,
                       output_tokens=200, total_tokens=300, cost=0.005,
                       latency_ms=1, finish_reason="stop", raw_response={})
    client._update_stats(resp)

    s = snapshot()
    assert s.calls == 1
    assert s.total_tokens == 300
    assert abs(s.cost - 0.005) < 1e-9
    assert client._stats.total_calls == 1


def test_update_stats_safe_without_meter():
    """未开启计量器时，_update_stats 不应报错"""
    from core.billing import llm_meter

    token = llm_meter._meter_var.set(None)
    try:
        client = DashScopeLLM.__new__(DashScopeLLM)
        client._stats = type("S", (), {"total_calls": 0, "total_tokens": 0,
                                       "total_cost": 0.0, "errors": 0})()
        resp = LLMResponse(content="x", model="qwen-max", input_tokens=1,
                           output_tokens=1, total_tokens=2, cost=0.001,
                           latency_ms=1, finish_reason="stop", raw_response={})
        client._update_stats(resp)
        assert client._stats.total_calls == 1
    finally:
        llm_meter._meter_var.reset(token)

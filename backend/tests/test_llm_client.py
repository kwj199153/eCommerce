"""
LLM 客户端内部逻辑回归测试

覆盖：
1. 成本计算（按模型定价）
2. 无 usage 时的 token 估算
3. 每次调用都会写入请求级计量器（LLM 消耗 → 计费 的接点）
4. 降级：未开启计量器时不报错
5. 流式解析：usage-only chunk 的 choices 是空数组时不能越界

⚠️ 本文件直接构造 `DashScopeLLM` 并替换 `_client` 为假 http 客户端，
**测的就是真实的 chat/chat_stream 实现本身**，因此必须放行 conftest 的
`_no_real_llm` 总闸（否则方法会被替换成桩，测不到解析逻辑）。
放行是安全的：下面的 `_FakeHttpClient` 已经接管了全部网络交互。
"""

import pytest

from ai_infra.llm.dashscope_client import DashScopeLLM, LLMConfig, LLMResponse
from core.billing.llm_meter import reset_meter, snapshot

# 本文件全程用假 http 客户端，不需要真实出网，但要真实的解析实现
pytestmark = pytest.mark.allow_real_llm


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


# ====== 流式解析：usage-only chunk 的 choices 是空数组 ======

class _FakeStreamResponse:
    """只实现 chat_stream 用到的 aiter_lines"""

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _FakeHttpClient:
    """顶替 httpx.AsyncClient，把预设的 SSE 行喂给解析逻辑"""

    is_closed = False

    def __init__(self, lines):
        self._lines = lines

    def stream(self, *args, **kwargs):
        return _FakeStreamCtx(_FakeStreamResponse(self._lines))


async def test_chat_stream_tolerates_usage_only_chunk():
    """
    开了 `stream_options.include_usage` 后，**最后一个 chunk 的 choices 是空数组**
    （只带 usage）。旧解析写的是 `chunk.get("choices", [{}])[0]` —— `.get(key, default)`
    的默认值只在 key **缺失**时生效，key 存在但值为 `[]` → `[][0]` 越界。

    实测后果：正文已全部流完，最后解析 usage chunk 时抛 IndexError，被上层
    `llm_stream` 的 except 接住 → 在完整回答末尾甩一句
    `[错误: list index out of range]`（老板就是这么看到的）。
    真实抓包：8 个 chunk 中恰有 1 个 `{"choices": [], "usage": {...}}`。
    """
    lines = [
        'data: {"choices":[{"delta":{"content":"便携迷你"}}]}',
        'data: {"choices":[{"delta":{"content":"加湿器"}}]}',
        # ← 真实抓包形态：choices 空数组 + 只带 usage
        'data: {"choices":[],"usage":{"prompt_tokens":14,"completion_tokens":7}}',
        "data: [DONE]",
    ]
    llm = DashScopeLLM()
    llm._client = _FakeHttpClient(lines)

    chunks = [c async for c in llm.chat_stream("hi")]

    assert "".join(chunks) == "便携迷你加湿器", "usage chunk 不该吞掉任何正文"
    assert not any("[错误" in c for c in chunks)
    assert not any("IndexError" in c for c in chunks)


async def test_chat_stream_survives_missing_choices_key():
    """`choices` 整个缺失（部分兼容端点）同样不能越界"""
    lines = [
        'data: {"choices":[{"delta":{"content":"OK"}}]}',
        'data: {"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        "data: [DONE]",
    ]
    llm = DashScopeLLM()
    llm._client = _FakeHttpClient(lines)

    chunks = [c async for c in llm.chat_stream("hi")]

    assert "".join(chunks) == "OK"

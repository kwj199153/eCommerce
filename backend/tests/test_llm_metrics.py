"""
LLM 指标写入点门禁（P0-1，2026-09-16）

★ 修复前的事实（第 94 轮横切审计实测）
    `LLM_CALLS` / `LLM_TOKENS` 在 `core/observability/metrics.py` 定义、
    在 `observability/__init__.py` 导出、在 `_REGISTRY` 注册，
    而**全仓 0 个 `.inc()`**。连 `main.py::_probe_llm` 的 docstring 都写着
    「模型是否可用由 llm_calls_total{status="error"} 反映」——
    那个序列永远不会存在。**文档引用了一个根本不存在的数据源。**

    本文件所以要断言的不是"指标对象存在"，而是**"真的被写了"**。四条路径：

        1. 非流成功 —— `chat()` → `_update_stats()`
        2. 非流失败 —— `chat()` 的 except 分支
        3. 流成功   —— `chat_stream()` 收尾
        4. 流失败   —— `chat_stream()` 的 except 分支

    外加两条口径约束：
        5. token 为 0 时**不建序列** —— 让"这条路径漏了埋点"表现为
           "时间序列不存在"，而不是"值恒为 0"。后者会被当成"真的没消耗"，
           静默的 0 比缺失更难发现。
        6. 写入点**全仓唯一** —— 否则各处各写一套标签口径，指标又变成噪音。

⚠️ 本文件测的是真实的 `chat` / `chat_stream` 实现，因此必须放行 conftest 的
`_no_real_llm` 总闸；网络交互由下面的本地假 http 客户端接管，**不真的出网**。
"""

import pathlib
import re

import httpx
import pytest

from ai_infra.llm import dashscope_client as dsc
from ai_infra.llm.dashscope_client import DashScopeLLM, LLMResponse, UsageStats
from core.observability.metrics import render_prometheus, reset_all

pytestmark = pytest.mark.allow_real_llm

_MODEL = "qwen-max"
_BACKEND = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_metrics():
    """指标是进程级全局状态 —— 每条用例前后都清干净，避免互相污染。"""
    reset_all()
    yield
    reset_all()


@pytest.fixture
def fast_retry(monkeypatch):
    """流式失败用例把重试压到 1 次，否则要真等 1s + 2s 退避。"""
    from core.resilience import RetryPolicy

    monkeypatch.setattr(dsc, "_RETRY_POLICY", RetryPolicy(attempts=1, base_delay=0.0))


def _bare_client() -> DashScopeLLM:
    """跳过 `__init__`（不碰网络 / 配置），只装配 chat / chat_stream 用到的属性。"""
    c = DashScopeLLM.__new__(DashScopeLLM)
    c.model = _MODEL
    c.temperature = 0.7
    c.max_tokens = 1024
    c.top_p = 0.9
    c._client = None
    c._stats = UsageStats()
    return c


def _series(name: str, **labels):
    """从 Prometheus 文本里取一条序列的值；**序列不存在则返回 None**。

    返回 None 与返回 0.0 是两件不同的事，本文件多处断言依赖这个区别。
    """
    text = render_prometheus()
    for m in re.finditer(rf"^{re.escape(name)}\{{([^}}]*)\}}\s+([0-9.eE+-]+)", text, re.M):
        got = dict(re.findall(r'([A-Za-z_]\w*)="((?:[^"\\]|\\.)*)"', m.group(1)))
        if got == {k: str(v) for k, v in labels.items()}:
            return float(m.group(2))
    return None


# ====== 1 / 2. 非流式 ======


async def test_chat_success_writes_calls_and_tokens(monkeypatch):
    """★ 走**完整的 chat()**（不是只调 _update_stats），确认成功路径真的打了指标。"""
    c = _bare_client()

    async def fake_call(url, payload):
        return {
            "model": _MODEL,
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
        }

    monkeypatch.setattr(c, "_call_with_retry", fake_call)
    out = await c.chat("你好")

    assert out.content == "hi"
    assert _series("llm_calls_total", model=_MODEL, status="success") == 1.0
    assert _series("llm_tokens_total", model=_MODEL, direction="input") == 12.0
    assert _series("llm_tokens_total", model=_MODEL, direction="output") == 34.0


async def test_chat_failure_writes_error_series(monkeypatch):
    """★★ 失败必须也计数。

    修复前 `status="error"` 这条序列根本不存在 ⇒ **"LLM 失败率"这个唯一有用的
    告警信号无从计算**；`main.py::_probe_llm` 的 docstring 却指着它。
    """
    c = _bare_client()

    async def boom(url, payload):
        raise httpx.ConnectError("dead")

    monkeypatch.setattr(c, "_call_with_retry", boom)
    with pytest.raises(httpx.ConnectError):
        await c.chat("hi")

    assert _series("llm_calls_total", model=_MODEL, status="error") == 1.0
    # 失败时没有 usage ⇒ 不该凭空写出 token 序列
    assert _series("llm_tokens_total", model=_MODEL, direction="input") is None


def test_update_stats_writes_success_series():
    """`_update_stats` 是非流成功的**唯一出口** —— 记本地 stats 与记全局指标必须成对。"""
    c = _bare_client()
    resp = LLMResponse(
        content="x", model=_MODEL, input_tokens=100, output_tokens=200,
        total_tokens=300, cost=0.005, latency_ms=1,
        finish_reason="stop", raw_response={},
    )
    c._update_stats(resp)

    assert _series("llm_calls_total", model=_MODEL, status="success") == 1.0
    assert _series("llm_tokens_total", model=_MODEL, direction="input") == 100.0
    assert _series("llm_tokens_total", model=_MODEL, direction="output") == 200.0


# ====== 3 / 4. 流式 ======


class _FakeStreamResponse:
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
    """顶替 httpx.AsyncClient：把预设 SSE 行喂给 chat_stream 的解析逻辑。"""

    is_closed = False

    def __init__(self, lines):
        self._lines = lines

    def stream(self, *args, **kwargs):
        return _FakeStreamCtx(_FakeStreamResponse(self._lines))

    async def aclose(self):
        return None


async def test_chat_stream_success_writes_calls_and_tokens():
    c = _bare_client()
    c._client = _FakeHttpClient([
        'data: {"choices":[{"delta":{"content":"你"}}]}',
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        # 最后一个 chunk 的 choices 是空数组、只带 usage（开启 include_usage 后会这样）
        'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}',
        "data: [DONE]",
    ])

    got = []
    async for chunk in c.chat_stream("hi"):
        got.append(chunk)

    assert got == ["你", "好"]
    assert _series("llm_calls_total", model=_MODEL, status="success") == 1.0
    assert _series("llm_tokens_total", model=_MODEL, direction="input") == 5.0
    assert _series("llm_tokens_total", model=_MODEL, direction="output") == 7.0


async def test_chat_stream_open_failure_writes_error_series(fast_retry):
    """★ 流式失败也要计数（修复前 chat_stream 连重试都没有，更别说指标）。"""
    c = _bare_client()

    class _BoomClient:
        is_closed = False

        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("open dead")

        async def aclose(self):
            return None

    c._client = _BoomClient()

    with pytest.raises(httpx.ConnectError):
        async for _ in c.chat_stream("hi"):
            pass  # pragma: no cover

    assert _series("llm_calls_total", model=_MODEL, status="error") == 1.0


# ====== 5. 口径：token 为 0 不建序列 ======


def test_zero_tokens_creates_no_series():
    """★ "漏埋点"应表现为**序列不存在**，而不是"值恒为 0"。

    后者会被当成"这次调用真的没消耗"，前者查 /metrics 一眼就能看出来 ——
    静默的 0 比缺失更难发现。
    """
    from ai_infra.llm.dashscope_client import _emit_llm_metrics

    _emit_llm_metrics("qwen-plus", "success")  # 不传 token

    assert _series("llm_calls_total", model="qwen-plus", status="success") == 1.0
    assert _series("llm_tokens_total", model="qwen-plus", direction="input") is None
    assert _series("llm_tokens_total", model="qwen-plus", direction="output") is None


def test_model_none_is_labelled_unknown():
    """model 缺失时标签落到 `unknown`，而不是产生一条空标签序列。"""
    from ai_infra.llm.dashscope_client import _emit_llm_metrics

    _emit_llm_metrics(None, "error")
    assert _series("llm_calls_total", model="unknown", status="error") == 1.0


# ====== 6. 写入点全仓唯一 ======


def test_metric_writes_have_exactly_one_implementation():
    """★ LLM 指标的 `.inc()` 只能出现在 LLM 客户端（所有 Agent 的单出口）。

    这条是 P0-1 的**机械保障**：要求是"一处覆盖所有 Agent"，那就必须真的只有一处。
    一旦有人在某个 Agent 里再 `LLM_CALLS.inc(...)`，标签口径立刻分叉。
    """
    allowed = {"ai_infra/llm/dashscope_client.py"}
    hits = set()
    for p in _BACKEND.rglob("*.py"):
        rel = p.relative_to(_BACKEND).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/")) or "__pycache__" in rel:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "LLM_CALLS.inc(" in text or "LLM_TOKENS.inc(" in text:
            hits.add(rel)

    assert hits == allowed, (
        f"LLM 指标写入点发生变化：\n"
        f"  新增 = {sorted(hits - allowed)}\n"
        f"  消失 = {sorted(allowed - hits)}\n"
        "指标必须在 LLM 客户端统一写，否则标签口径会分叉。"
    )

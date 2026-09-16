"""
弹性原语（core/resilience.py）回归测试

★ 为什么必须有这个文件
    修复前本项目有 **3 套互不共享**的自研重试实现（第 96 轮 AST 复扫的**实数** ——
    第 94 轮审计报的 6 套里，`payment/gateway.py` 与 `core/redis.py` 两条是误报，
    详见 `core/resilience.py` 模块 docstring），而且**同一个文件里策略都不一致**：
    `ai_infra/llm/dashscope_client.py::chat()` 走 `_call_with_retry`（429 指数退避 +
    5xx 重试），而**同一个文件的 `chat_stream()` 完全没有重试** —— 流式接口遇到一次
    连接抖动就直接失败，非流式却会自己恢复。

    收敛到 `core/resilience.py` 之后，本文件负责钉住三件**重构中最容易丢掉**的事：
      1. 什么错该重试、什么错不该重试（把确定性 4xx 也重试 = 白烧配额）；
      2. **`asyncio.CancelledError` 永不重试**（否则"取消"会被吞掉）；
      3. **流式只重试"建立连接"那一步**（正文一旦开始流出去就绝不能重试）。

    第 3 条最重要，也最没有任何编译期/类型期保障：它写错了不会报错，
    只会让用户在自己的聊天窗口里看到**同一段正文出现两次**。
"""

import ast
import asyncio
from pathlib import Path

import httpx
import pytest

from core.resilience import (
    DEFAULT_POLICY,
    RetryPolicy,
    call_with_retry,
    retrying_stream,
    with_retry,
)

# 零等待策略：用例里不真睡，否则每条白等 1s/2s/4s
FAST = RetryPolicy(attempts=3, base_delay=0.0)
SILENT = {"on_retry": lambda *a: None}  # 静音"即将重试"告警


def _http_error(status: int, headers=None) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://fake")
    resp = httpx.Response(status, headers=headers or {}, request=req)
    return httpx.HTTPStatusError(f"{status}", request=req, response=resp)


# ====== 1. 分类：什么该重试 ======

@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses(status):
    assert RetryPolicy().classify(_http_error(status))[0] is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_deterministic_4xx_is_not_retried(status):
    """4xx（除 429）是确定性失败：重试不会有不同结果，只会白烧配额与调用次数。"""
    assert RetryPolicy().classify(_http_error(status))[0] is False


def test_transport_error_is_retryable():
    assert RetryPolicy().classify(httpx.ConnectError("x"))[0] is True
    assert RetryPolicy().classify(httpx.ReadTimeout("x"))[0] is True


def test_unknown_exception_is_not_retryable():
    assert RetryPolicy().classify(ValueError("x"))[0] is False


class _BizError(RuntimeError):
    """模拟「失败时抛自己的业务异常」的 provider（如万相出图）。"""


def test_retry_if_hook_enables_custom_retryable():
    """★ `retry_if` 是给「错误不是 httpx 异常」的 provider 留的钩子。

    没有它，这类调用方（万相的错误是 `Throttling.RateQuota` 这种业务码，
    抛出来的是 `ImageGenError`）就只能再**自己抄一遍重试循环** ——
    而那正是本模块要消灭的东西。
    """
    pol = RetryPolicy(retry_if=lambda exc: "throttling" in str(exc).lower())
    assert pol.classify(_BizError("Throttling.RateQuota"))[0] is True
    assert pol.classify(_BizError("InvalidParameter: size"))[0] is False


def test_retry_if_does_not_override_deterministic_4xx():
    """★ 顺序约束：钩子只在 httpx 判定**之后**兜底。

    一个"一律返回可重试"的钩子**不能**把确定性 4xx 变成可重试 ——
    否则 400（请求体不合法）会被重试，白烧配额。
    """
    pol = RetryPolicy(retry_if=lambda exc: True)
    assert pol.classify(_http_error(400))[0] is False, "retry_if 越权把确定性 4xx 变成可重试了"
    assert pol.classify(_BizError("x"))[0] is True   # 非 httpx 的才归它管


def test_retry_after_header_is_honored():
    """服务端说了算 —— `Retry-After` 比任何本地退避表都准。"""
    assert RetryPolicy().classify(_http_error(429, {"Retry-After": "7"}))[1] == 7.0


def test_retry_after_http_date_falls_back():
    """HTTP-date 形态不解析（见模块 docstring），回落到退避表。"""
    got = RetryPolicy().classify(
        _http_error(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    assert got[0] is True and got[1] is None


# ====== 2. 退避算得对 ======

def test_backoff_schedule_and_cap():
    pol = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=30.0)
    assert [pol.delay_for(a) for a in (1, 2, 3)] == [1.0, 2.0, 4.0]
    # 服务端给的 hint 也要过封顶（否则一个错误/恶意的头能让请求睡到天荒地老）
    assert pol.delay_for(1, hint=99999.0) == 30.0
    assert pol.delay_for(1, hint=0.0) == 0.0
    # 退避表本身也封顶
    assert pol.delay_for(10) == 30.0


def test_default_policy_attempts_means_total_attempts():
    """★ 口径：attempts = **总尝试次数**，不是"重试次数"（后者会变成 4 次调用）。"""
    assert DEFAULT_POLICY.attempts == 3


# ====== 3. call_with_retry ======

async def test_succeeds_after_transient_failures():
    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("flaky")
        return "ok"

    assert await call_with_retry(_flaky, policy=FAST, what="t", **SILENT) == "ok"
    assert calls["n"] == 3


async def test_exhausted_raises_last_original_exception():
    """耗尽后抛**原始异常**（保留 traceback），而不是包一层无信息的 RuntimeError。"""
    calls = {"n": 0}

    async def _dead():
        calls["n"] += 1
        raise httpx.ReadTimeout("dead")

    with pytest.raises(httpx.ReadTimeout):
        await call_with_retry(_dead, policy=FAST, what="t", **SILENT)
    assert calls["n"] == 3


async def test_deterministic_error_tried_once():
    calls = {"n": 0}

    async def _bad():
        calls["n"] += 1
        raise ValueError("deterministic")

    with pytest.raises(ValueError):
        await call_with_retry(_bad, policy=FAST, what="t", **SILENT)
    assert calls["n"] == 1


async def test_cancelled_error_is_never_retried():
    """★★ 取消不是失败：重试它等于让已取消的操作继续跑，并把取消吞掉。"""
    calls = {"n": 0}

    async def _cancel():
        calls["n"] += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await call_with_retry(_cancel, policy=FAST, what="t", **SILENT)
    assert calls["n"] == 1, "CancelledError 被重试了"


async def test_wrap_produces_custom_exception():
    async def _dead():
        raise httpx.ConnectError("dead")

    with pytest.raises(RuntimeError, match=r"LLM call failed after 3 retries: dead"):
        await call_with_retry(
            _dead, policy=FAST, what="t", **SILENT,
            wrap=lambda n, exc: RuntimeError(f"LLM call failed after {n} retries: {exc}"),
        )


async def test_zero_attempts_is_rejected_loudly():
    with pytest.raises(ValueError):
        await call_with_retry(lambda: asyncio.sleep(0), policy=RetryPolicy(attempts=0))


# ====== 4. retrying_stream（本文件最重要的一组） ======

class _CM:
    """可控的 async 上下文管理器：第 fail_times 次 __aenter__ 抛错"""

    def __init__(self, fail_times: int = 0, value: str = "RESP"):
        self.fail_times = fail_times
        self.value = value
        self.enters = 0

    async def __aenter__(self):
        self.enters += 1
        if self.enters <= self.fail_times:
            raise httpx.ConnectError("open fail")
        return self.value

    async def __aexit__(self, *exc_info):
        return False


async def test_stream_retries_connection_establishment():
    """★ 修复前 dashscope_client.chat_stream 完全没有重试，这一条就是那个缺口。"""
    cms = []

    def _open():
        # ★ 只让**第一次**连接失败：重试时 open_stream() 会被重新调用、
        #   每次新建一个 _CM；若固定 fail_times=1，则每个新 cm 都会再失败
        #   一次 ⇒ 永远重试不上（测试自己构造错了，不是生产代码的问题）。
        cm = _CM(fail_times=1 if not cms else 0)
        cms.append(cm)
        return cm

    seen = []
    async with retrying_stream(_open, policy=FAST, what="s", **SILENT) as resp:
        seen.append(resp)

    assert seen == ["RESP"]
    assert len(cms) == 2 and cms[-1].enters == 1, "应重建一次连接后成功"


async def test_stream_open_failure_exhausts_loudly():
    attempts = {"n": 0}

    def _open():
        attempts["n"] += 1
        return _CM(fail_times=99)

    with pytest.raises(httpx.ConnectError):
        async with retrying_stream(_open, policy=FAST, what="s", **SILENT):
            pass  # pragma: no cover
    assert attempts["n"] == 3


async def test_stream_does_not_retry_after_first_chunk():
    """
    ★★★ 本文件最重要的一条断言。

    正文已经开始流出去之后再失败**绝不能重试** —— 否则会把用户已经看到的
    内容再发一遍。这个错误没有任何编译期/类型期保障，写错了只会表现为
    "用户看到重复正文"（比一次干脆的失败难排查得多）。
    """
    opens = {"n": 0}
    yielded = []

    class _Lines:
        async def aiter_lines(self):
            yield "前半"
            raise httpx.ReadTimeout("mid-stream")

    class _StreamCM:
        async def __aenter__(self):
            return _Lines()

        async def __aexit__(self, *exc_info):
            return False

    def _open():
        opens["n"] += 1
        return _StreamCM()

    with pytest.raises(httpx.ReadTimeout):
        async with retrying_stream(_open, policy=FAST, what="s", **SILENT) as resp:
            async for line in resp.aiter_lines():
                yielded.append(line)

    assert yielded == ["前半"]
    assert opens["n"] == 1, "★ 流中断后重连了 —— 用户会收到重复正文"


# ====== 5. with_retry 装饰器 ======

async def test_decorator_retries():
    calls = {"n": 0}

    @with_retry(FAST, what="deco")
    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("x")
        return "ok"

    assert await _flaky() == "ok"
    assert calls["n"] == 2


def test_decorator_rejects_async_generator():
    """
    ★ 必须**显式报错**，不能静默降级：包一层 async generator 会把它从
    "逐块产出"变成"一次性返回生成器对象"，流式契约被静默破坏。
    """
    with pytest.raises(TypeError, match="async generator"):

        @with_retry(FAST)
        async def _gen():
            yield 1


def test_decorator_rejects_sync_function():
    """同步重试会阻塞事件循环 —— 只做异步，并且要说清楚。"""
    with pytest.raises(TypeError, match="async"):

        @with_retry(FAST)
        def _sync():
            return 1


# ====== 6. 全仓唯一实现门禁（防"第 7 套重试"） ======

_BACKEND = Path(__file__).resolve().parents[1]          # → backend/
_SCAN_SKIP_PARTS = {
    ".venv", "venv", "__pycache__", "node_modules", ".git",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "logs", "data",
}
#: 唯一允许出现"重试循环"的文件 —— 就是收敛目标本身
_RETRY_LOOP_ALLOWED = {"core/resilience.py"}


def _dotted(node) -> str:
    """把 ast 调用节点还原成 ``a.b.c`` 形状。"""
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _retry_loop_lines(path: Path) -> list:
    """返回该文件里"重试循环"的行号（AST 判定，不靠 grep 猜）。

    判据：``for``/``while`` 体内有 ``try``，且某个 ``except`` 处理块的语句里
    调用了 ``sleep``。
    ★ 为什么"handler 里有 sleep"这一条就够：逐项降级（遍历一批数据、单条失败
      就 ``continue``）**不需要 sleep**；只有"失败了要等一会儿再试"才需要 ——
      那正是重试的形态。第 96 轮全仓实测：本判据在 256 个 .py 上零误判。
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for sub in node.body:
            if not isinstance(sub, ast.Try):
                continue
            for handler in sub.handlers:
                block = ast.Module(body=list(handler.body), type_ignores=[])
                if any(
                    isinstance(s, ast.Call) and _dotted(s.func).endswith("sleep")
                    for s in ast.walk(block)
                ):
                    hits.append(node.lineno)
    return sorted(set(hits))


def test_no_retry_loop_outside_resilience():
    """★★★ 全仓唯一重试实现：`core/resilience.py` 之外不该再出现重试循环。

    为什么是**形态门禁**而不是维护一份"共有 N 套"的名单：
      第 94 轮按名枚举，结果**漏了** 2 份客户端 IP 拷贝（实际 4 份）、
      又**多报**了 2 套重试（payment/gateway.py 零重试、core/redis.py 是
      Celery 框架配置）。名单会腐烂，代码形态不会。
    """
    offenders = {}
    for path in _BACKEND.rglob("*.py"):
        if any(part in _SCAN_SKIP_PARTS for part in path.parts):
            continue
        rel = path.relative_to(_BACKEND).as_posix()
        if rel in _RETRY_LOOP_ALLOWED:
            continue
        lines = _retry_loop_lines(path)
        if lines:
            offenders[rel] = lines

    assert not offenders, (
        "发现 core/resilience.py 之外的重试循环 —— 请改用 call_with_retry() / "
        f"retrying_stream() / with_retry()：{offenders}"
    )

"""
重试收敛回归测试 —— 两处「曾经自己抄一套」的调用方

★ 为什么单独一个文件
    `modules/aigc_media/image_client.py` 与 `platforms/amazon/sp_api/auth.py`
    各自有一套**内联重试循环**（第 96 轮收敛到 `core/resilience.py`）。
    这两个文件在收敛前**一条测试都没有** —— 它们的行为是"没人钉住的"。

    所以本文件的任务不是"验证新代码"，而是：
      1. 把**收敛前的行为逐条钉死**，证明收敛是"搬逻辑"而不是"改策略"；
      2. 单独钉住三条**有意修掉的缺陷**（用 `★ 修复前…` 标注），
         防止将来有人"为了统一"把它们改回去。

★ 两类的失败语义**完全不同**，别混：
      · image_client：失败**降级**（返回 ``(prompt, None, 原因)``），从不抛错；
      · sp_api/auth ：失败**抛错**（包装成 ``SPAPIAuthError``）。
    这正是 `core/resilience.py` 约束 2 —— 本模块只提供重试原语，
    不替调用方决定降级语义。
"""

import asyncio

import httpx
import pytest

from modules.aigc_media.image_client import ImageGenError, _gather_many
from platforms.amazon.sp_api.auth import SPAPIAuthError

# ====== 公共夹具 ======


@pytest.fixture
def no_sleep(monkeypatch):
    """把 `asyncio.sleep` 换成记账版 —— 否则每条用例要真等 2/5/10 秒。"""
    slept = []

    async def _fake(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake)
    return slept


# ====== A. 万相出图：失败**降级**，不抛 ======


def _img_runner(script):
    """构造 runner：按调用序号取 script 里的条目，并记录调用次数。

    条目形态：``"ok:<url>"`` → 返回 ``[url]``；``"err:<msg>"`` → 抛 `ImageGenError`。
    最后一条会被重复（模拟"一直失败"）。
    """
    calls = {"n": 0}

    async def _run(_prompt):
        i = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        item = script[i]
        if item.startswith("ok:"):
            return [item[3:]]
        raise ImageGenError(item[4:])

    return _run, calls


async def test_wanx_success_passes_through():
    runner, calls = _img_runner(["ok:http://img/1.png"])
    assert await _gather_many(["猫"], runner, concurrency=1) == [("猫", "http://img/1.png", None)]
    assert calls["n"] == 1


async def test_wanx_retryable_message_is_retried_then_degraded(no_sleep):
    """★ 万相的失败是**业务文案**（429 / Throttling / 超时）而不是 httpx 异常 ——
    这正是 `RetryPolicy.retry_if` 钩子存在的理由。"""
    runner, calls = _img_runner(["err:429 Throttling.RateQuota"])
    got = await _gather_many(["猫"], runner, concurrency=1)

    assert calls["n"] == 4, "应为 1 次初始 + 3 次重试"
    # ★ 降级而不是抛 —— 逐项降级是长任务能跑完的前提
    assert got == [("猫", None, "429 Throttling.RateQuota")]
    # ★ 与原固定表 RETRY_BACKOFF_SECONDS **逐项等价**（不是"差不多"）
    assert no_sleep == [2.0, 5.0, 10.0]


async def test_wanx_non_retryable_message_degrades_immediately():
    """参数错误重试无意义 —— 只调用一次。"""
    runner, calls = _img_runner(["err:InvalidParameter: size is not in the correct format"])
    got = await _gather_many(["猫"], runner, concurrency=1)
    assert calls["n"] == 1
    assert got[0][1] is None and got[0][2].startswith("InvalidParameter")


async def test_wanx_retries_then_succeeds():
    """重试后成功要返回 URL —— 收敛不能把"抖动后恢复"变成失败。"""
    runner, calls = _img_runner(["err:429 rate limit", "ok:http://img/9.png"])
    assert await _gather_many(["猫"], runner, concurrency=1) == [("猫", "http://img/9.png", None)]
    assert calls["n"] == 2


async def test_wanx_one_failure_does_not_kill_the_batch():
    """逐项降级：一张挂掉不影响其余（长任务里最怕一张图挂掉就全灭）。"""
    runner, _calls = _img_runner(
        ["ok:http://img/1.png", "err:InvalidParameter: bad", "ok:http://img/3.png"]
    )
    got = await _gather_many(["a", "b", "c"], runner, concurrency=1)

    assert [g[0] for g in got] == ["a", "b", "c"], "顺序必须与入参一致"
    assert [bool(g[1]) for g in got] == [True, False, True]
    assert got[1][2] == "InvalidParameter: bad"


def test_wanx_policy_backoff_matches_original_table():
    """★ 策略参数逐项等价 —— 收敛不该顺手改退避次数或退避表。"""
    from modules.aigc_media.image_client import _RETRY_POLICY

    assert _RETRY_POLICY.attempts == 4, "原 range(MAX_RETRIES + 1) = 4 次总尝试"
    assert [_RETRY_POLICY.delay_for(a) for a in (1, 2, 3)] == [2.0, 5.0, 10.0]


# ====== B. SP-API：失败**抛错**（包装成 SPAPIAuthError） ======


@pytest.fixture
def spapi(monkeypatch):
    """真实的 SPAPIClientAuth，只把签名步骤打桩（聚焦重试，不牵扯 AWS 签名/凭证）。"""
    from platforms.amazon.sp_api.auth import SPAPIClientAuth, SPAPIConfig

    client = SPAPIClientAuth(config=SPAPIConfig())

    async def _fake_sign(**_kwargs):
        return {"Authorization": "AWS4-FAKE"}

    monkeypatch.setattr(client, "sign_request", _fake_sign)
    return client


def _install(client, monkeypatch, statuses, headers=None):
    """按 `statuses` 逐次返回状态码（最后一项重复），并记录调用次数。"""
    calls = {"n": 0}

    def _handler(request):
        i = min(calls["n"], len(statuses) - 1)
        calls["n"] += 1
        code = statuses[i]
        if code >= 400:
            return httpx.Response(code, headers=headers or {}, request=request)
        return httpx.Response(code, json={"ok": True}, request=request)

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(type(client), "http_client", property(lambda _self: mock))
    return calls


async def test_spapi_success_passes_through(spapi, monkeypatch, no_sleep):
    calls = _install(spapi, monkeypatch, [200])
    assert await spapi.make_authenticated_request("GET", "/orders") == {"ok": True}
    assert calls["n"] == 1 and no_sleep == []


async def test_spapi_deterministic_4xx_is_not_retried(spapi, monkeypatch, no_sleep):
    """★ 修复前 `except httpx.HTTPStatusError` **不看状态码** ⇒ 400/401/404 也重试 3 次。"""
    calls = _install(spapi, monkeypatch, [400])
    with pytest.raises(SPAPIAuthError) as ei:
        await spapi.make_authenticated_request("GET", "/orders")

    assert calls["n"] == 1, "确定性 400 被重试了 —— 白烧配额"
    assert ei.value.code == "HTTP_400"
    assert no_sleep == []


async def test_spapi_5xx_retried_then_wrapped_with_status(spapi, monkeypatch, no_sleep):
    calls = _install(spapi, monkeypatch, [500])
    with pytest.raises(SPAPIAuthError) as ei:
        await spapi.make_authenticated_request("GET", "/orders")

    assert calls["n"] == 3
    assert ei.value.code == "HTTP_500"
    assert no_sleep == [1.0, 2.0], "退避应与修复前逐项等价（1s → 2s）"


async def test_spapi_retries_then_succeeds(spapi, monkeypatch, no_sleep):
    calls = _install(spapi, monkeypatch, [503, 503, 200])
    assert await spapi.make_authenticated_request("GET", "/orders") == {"ok": True}
    assert calls["n"] == 3 and no_sleep == [1.0, 2.0]


async def test_spapi_429_honors_retry_after(spapi, monkeypatch, no_sleep):
    """服务端说了算：429 带 `Retry-After` 时按它等。"""
    calls = _install(spapi, monkeypatch, [429], headers={"Retry-After": "7"})
    with pytest.raises(SPAPIAuthError):
        await spapi.make_authenticated_request("GET", "/orders")

    assert calls["n"] == 3
    assert no_sleep == [7.0, 7.0], "Retry-After 没被遵守"


async def test_spapi_429_retry_after_is_capped(spapi, monkeypatch, no_sleep):
    """★ 修复前 `Retry-After` **完全不封顶** —— 服务端/中间人回 99999 就真的睡 27 小时。"""
    _install(spapi, monkeypatch, [429], headers={"Retry-After": "99999"})
    with pytest.raises(SPAPIAuthError):
        await spapi.make_authenticated_request("GET", "/orders")

    assert no_sleep == [60.0, 60.0], f"Retry-After 未封顶：{no_sleep}"


async def test_spapi_429_exhausted_reports_real_status(spapi, monkeypatch, no_sleep):
    """★ 修复前 429 耗尽会落到 `raise SPAPIAuthError("未知错误：超出最大重试次数")`
    —— **状态码丢了**，看到这条日志的人只能靠猜。"""
    _install(spapi, monkeypatch, [429], headers={"Retry-After": "1"})
    with pytest.raises(SPAPIAuthError) as ei:
        await spapi.make_authenticated_request("GET", "/orders")

    assert ei.value.code == "HTTP_429", "真实状态码没带出来"
    assert "429" in str(ei.value)
    assert "未知错误" not in str(ei.value)


def test_spapi_policy_backoff_matches_original():
    """★ 策略参数逐项等价 + 封顶存在。"""
    from platforms.amazon.sp_api.auth import _RETRY_POLICY

    assert _RETRY_POLICY.attempts == 3
    assert [_RETRY_POLICY.delay_for(a) for a in (1, 2)] == [1.0, 2.0]
    assert _RETRY_POLICY.delay_for(1, hint=99999.0) == 60.0

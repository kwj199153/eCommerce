"""
HTTP 中间件回归测试

覆盖：
1. RateLimitMiddleware：固定窗口计数、超额 429、放行路径、限流响应头
2. RequestLogMiddleware：请求 ID 生成/透传、耗时头、request.state 注入
3. 两个中间件均已注册到主 app

限流测试使用**独立的 app 实例**（显式 enabled=True / limit=N），
不依赖主 app 的配置 —— 测试环境通过 backend/conftest.py 关闭了主 app 的限流。

★ 并且显式传 `redis_backend=False`（强制进程内计数）。
  原因：`_MemoryCounter` 是实例级的，而 `_RedisCounter` 的 key 只含「IP + 时间窗口」，
  是**跨实例共享**的 —— 若让这 6 个用例走 Redis，它们会共用同一份计数而互相污染
  （修复 Redis 的 localhost/IPv6 问题后实测：limit=5 的用例首次请求 remaining 变成 1，
   limit=3 的用例直接 429）。这些用例要测的是**限流算法**，不该依赖外部共享状态。
  Redis 路径由 `test_rate_limit_switches_to_redis_backend_when_reachable` 单独覆盖 ——
  否则这条分支永远没有守护：修复前它因连不上 Redis 而从未被执行，
  用例却因为内存计数照常通过，把问题完全掩盖了。
"""

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from core.middleware import RateLimitMiddleware, RequestLogMiddleware


# ====== 被测的玩具应用 ======

def _make_inner_app() -> FastAPI:
    inner = FastAPI()

    @inner.get("/ping")
    async def ping():
        return {"ok": True}

    @inner.get("/health")
    async def health():
        return {"status": "ok"}

    @inner.get("/sse")
    async def sse():
        async def gen():
            yield "event: delta\ndata: {}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    @inner.get("/with-id")
    async def with_id(request: Request):
        return {"request_id": getattr(request.state, "request_id", None)}

    return inner


def _client(asgi_app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=asgi_app), base_url="http://testserver"
    )


# ====== 注册情况 ======

def test_middlewares_registered_on_main_app():
    from main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "RateLimitMiddleware" in names, names
    assert "RequestLogMiddleware" in names, names
    assert "TenantMiddleware" in names, names


# ====== 限流 ======

async def test_rate_limit_blocks_over_limit():
    """limit=2：前 2 次放行，第 3 次 429"""
    app = RateLimitMiddleware(
        _make_inner_app(), limit=2, window_seconds=60, enabled=True, exempt_paths=set(),
        redis_backend=False,
    )
    async with _client(app) as c:
        r1 = await c.get("/ping")
        r2 = await c.get("/ping")
        r3 = await c.get("/ping")

    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r3.status_code == 429, r3.text
    body = r3.json()
    assert body["error"] == "Too Many Requests"
    assert "Retry-After" in r3.headers


async def test_rate_limit_headers_present():
    app = RateLimitMiddleware(
        _make_inner_app(), limit=5, window_seconds=60, enabled=True, exempt_paths=set(),
        redis_backend=False,
    )
    async with _client(app) as c:
        r = await c.get("/ping")

    assert r.status_code == 200
    assert r.headers["X-RateLimit-Limit"] == "5"
    assert r.headers["X-RateLimit-Remaining"] == "4"
    assert int(r.headers["X-RateLimit-Reset"]) >= 1


async def test_rate_limit_exempt_path_not_counted():
    """放行路径不消耗额度：limit=1 时反复打 /health 仍应全 200"""
    app = RateLimitMiddleware(
        _make_inner_app(), limit=1, window_seconds=60, enabled=True,
        exempt_paths={"/health"},
        redis_backend=False,
    )
    async with _client(app) as c:
        codes = [(await c.get("/health")).status_code for _ in range(4)]

    assert codes == [200, 200, 200, 200]


async def test_rate_limit_disabled_passes_through():
    app = RateLimitMiddleware(
        _make_inner_app(), limit=1, window_seconds=60, enabled=False,
        redis_backend=False,
    )
    async with _client(app) as c:
        codes = [(await c.get("/ping")).status_code for _ in range(5)]

    assert codes == [200] * 5


async def test_rate_limit_headers_survive_streaming_response():
    """SSE 流式响应也必须带上限流头（BaseHTTPMiddleware 的已知坑点）"""
    app = RateLimitMiddleware(
        _make_inner_app(), limit=3, window_seconds=60, enabled=True, exempt_paths=set(),
        redis_backend=False,
    )
    async with _client(app) as c:
        r = await c.get("/sse")

    assert r.status_code == 200
    assert r.headers["X-RateLimit-Remaining"] == "2"
    assert "text/event-stream" in r.headers.get("content-type", "")


async def test_rate_limit_separates_clients_by_forwarded_for():
    """不同客户端 IP 各自计数，互不影响"""
    app = RateLimitMiddleware(
        _make_inner_app(), limit=1, window_seconds=60, enabled=True, exempt_paths=set(),
        redis_backend=False,
    )
    async with _client(app) as c:
        a1 = await c.get("/ping", headers={"X-Forwarded-For": "1.1.1.1"})
        b1 = await c.get("/ping", headers={"X-Forwarded-For": "2.2.2.2"})
        a2 = await c.get("/ping", headers={"X-Forwarded-For": "1.1.1.1"})

    assert a1.status_code == 200
    assert b1.status_code == 200, "不同 IP 不应被连带限流"
    assert a2.status_code == 429


async def test_rate_limit_switches_to_redis_backend_when_reachable():
    """
    Redis 可达时**必须真的**切到跨进程共享计数。

    为什么值得单独立一条：
      修复前 `redis_url = redis://localhost:6379/0`，Windows 下客户端先试 IPv6 的 ::1，
      在 `socket_connect_timeout=1` 处主动放弃且**不回退 IPv4** ⇒ 这个分支从未被执行过。
      而上面那 6 个用例在内存计数下照样全绿，把"Redis 后端形同不存在"完全掩盖了 ——
      只有专门断言"后端类型"，才能守住这条路径。
    """
    from core.config import config
    from core.middleware.rate_limit import _RedisCounter

    if not (config.redis_url or "").strip():
        pytest.skip("未配置 Redis")

    app = RateLimitMiddleware(
        _make_inner_app(), limit=5, window_seconds=60, enabled=True,
        exempt_paths=set(), redis_backend=True,
    )
    async with _client(app) as c:
        # 用独立的 X-Forwarded-For，避免与其它用例的计数器相撞
        r = await c.get("/ping", headers={"X-Forwarded-For": "rl-redis-probe"})

    assert r.status_code == 200, r.text
    assert isinstance(app._counter, _RedisCounter), (
        "Redis 可达却没有切换后端 —— 检查 redis_url 是否写成了 localhost"
        "（Windows 上会先试 ::1、超时后不回退 IPv4）"
    )
    # 收尾：释放本用例新建的客户端，避免连接泄漏
    try:
        await app._counter._client.aclose()
    except Exception:  # noqa: BLE001
        pass


# ====== 请求日志 ======

async def test_request_log_injects_id_and_timing_headers():
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r = await c.get("/ping")

    assert r.status_code == 200
    assert r.headers.get("X-Request-ID"), "缺少 X-Request-ID"
    assert float(r.headers["X-Process-Time-Ms"]) >= 0


async def test_request_log_echoes_incoming_request_id():
    """调用方传入的 X-Request-ID 必须原样透传（便于跟网关/前端日志串联）"""
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r = await c.get("/ping", headers={"X-Request-ID": "trace-abc-123"})

    assert r.headers["X-Request-ID"] == "trace-abc-123"


async def test_request_log_exposes_id_on_request_state():
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r = await c.get("/with-id", headers={"X-Request-ID": "trace-xyz"})

    assert r.json()["request_id"] == "trace-xyz"


async def test_request_log_disabled_adds_no_headers():
    app = RequestLogMiddleware(_make_inner_app(), enabled=False)
    async with _client(app) as c:
        r = await c.get("/ping")

    assert "X-Request-ID" not in r.headers

"""
请求限流中间件（按客户端标识的固定窗口计数）

定位划分（重要）：
  - 本中间件负责「速率」——防刷、防爬，例如 60 次/分钟；
  - 套餐维度的「总量」额度由 core/metering 计费体系负责（api_calls_limit / agent_chat_limit）。
  两者互补，不要重复实现。

存储策略：
  - 默认：进程内内存计数（单进程 uvicorn 足够）
  - 若配置了可达的 Redis，自动切换为 Redis 计数（多 worker / 多副本共享同一个计数器）
  - Redis 不可用时自动降级为内存计数，且只告警一次，绝不因限流组件故障而拒绝服务
  - 可用 `redis_backend=False` 强制走内存计数（Redis 计数是**跨实例共享**的，
    同一进程里存在多个中间件实例时会互相吃额度；只测限流算法时用这个开关隔离）

⚠️ 关于 Redis 地址写法（实测踩过，别再犯）：
  `redis_url` 请写 `127.0.0.1` 而不是 `localhost`。Windows 上 `localhost` 会先解析到
  IPv6 的 ::1；若 Redis 只监听 IPv4，连 ::1 会被拒绝且系统要等约 2 秒才返回失败，
  而这里的 `socket_connect_timeout=1` 会在 1 秒处主动放弃、**不会回退 IPv4**
  ⇒ 本中间件永远走内存计数，"Redis 后端"形同不存在，而告警日志看起来只是"Redis 不可用"。

⚠️ 关于客户端 IP：
  实现已收敛到 `core/middleware/client_ip.py`（**唯一真源**）——
  原先本文件与 request_log 各抄了一份同样的逻辑，两份各自演进时，
  访问日志记的 IP 与限流计数用的 key 会指向不同来源，排查「为什么这个 IP
  被限流了」时会得到互相矛盾的证据。
  反向代理（Nginx）后所有请求的 request.client.host 都是代理 IP，
  因此优先取 X-Forwarded-For 的第一跳。前提是**前置代理可信**；
  若服务直接暴露公网且未经过代理，该头部可由客户端伪造 —— 部署时请确保
  代理层会覆盖（而不是追加）该头部。
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import config
from core.middleware.client_ip import client_ip

logger = logging.getLogger(__name__)

# 放行路径：健康检查、指标采集与文档不应消耗限流额度
#   ★ /metrics 必须放行：Prometheus 默认 15s 抓一次，若计入限流额度，
#     单靠监控采集就能把用户的每分钟请求额度吃掉（limit=60/min 时占 25%）。
DEFAULT_EXEMPT_PATHS = frozenset({
    "/health",
    "/metrics",
    "/favicon.ico",
    "/docs",
    "/redoc",
    "/openapi.json",
})


# ====== 计数器后端 ======

class _MemoryCounter:
    """进程内固定窗口计数器（key 已带窗口号，天然按窗口隔离）"""

    def __init__(self) -> None:
        self._hits: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def incr(self, key: str, window: int) -> int:
        async with self._lock:
            count = self._hits.get(key, 0) + 1
            self._hits[key] = count

            # 顺手清理已过期窗口，避免长期运行内存增长
            # key 形如 ratelimit:{bucket}:{client}，第二段才是窗口号
            if len(self._hits) > 20_000:
                current_bucket = int(time.time() // window)
                self._hits = {
                    k: v for k, v in self._hits.items()
                    if k.split(":", 2)[1].isdigit()
                    and int(k.split(":", 2)[1]) >= current_bucket
                }
            return count


class _RedisCounter:
    """Redis 固定窗口计数器（多进程 / 多副本共享）"""

    def __init__(self, client) -> None:
        self._client = client

    async def incr(self, key: str, window: int) -> int:
        count = await self._client.incr(key)
        if count == 1:
            # 首个请求设定过期时间，窗口过后自动清理
            await self._client.expire(key, window)
        return int(count)


# ====== 中间件 ======

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    按客户端 IP 的固定窗口限流。

    命中上限时返回 429，并带标准限流响应头：
        X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset / Retry-After
    """

    def __init__(
        self,
        app,
        limit: Optional[int] = None,
        window_seconds: int = 60,
        enabled: Optional[bool] = None,
        exempt_paths: Optional[set[str]] = None,
        redis_backend: Optional[bool] = None,
    ) -> None:
        super().__init__(app)
        self.limit = int(limit if limit is not None else config.rate_limit_requests_per_minute)
        self.window = max(1, int(window_seconds))
        self.enabled = config.rate_limit_enabled if enabled is None else bool(enabled)
        self.exempt_paths = (
            frozenset(exempt_paths) if exempt_paths is not None else DEFAULT_EXEMPT_PATHS
        )
        self._counter: object = _MemoryCounter()
        self._backend_resolved = False
        # 后端选择：None = 自动探测（默认，生产行为）；
        #           False = 强制进程内计数；True = 强制 Redis。
        #
        # ★ 为什么需要这个开关（不是为测试开的后门）：
        #   `_MemoryCounter` 是**实例级**的，而 `_RedisCounter` 的 key 只含
        #   「IP + 时间窗口」，是**跨实例/跨进程共享**的。于是同一个进程里
        #   若有多个中间件实例（测试里的玩具 app、将来的子应用），它们会
        #   共用同一份计数而互相污染 —— 一个实例的流量会吃掉另一个实例的额度。
        #   生产只有唯一实例、且多副本共享计数正是设计意图，所以默认仍是自动探测；
        #   需要"只测限流算法、不要外部共享状态"的场景可显式传 False。
        self._redis_backend = redis_backend

    # ---- 内部工具 ----

    async def _resolve_backend(self) -> None:
        """首次请求时决定用 Redis 还是内存（只尝试一次）"""
        self._backend_resolved = True
        if self._redis_backend is False:
            # 显式要求进程内计数 → 不碰 Redis
            return
        redis_url = (getattr(config, "redis_url", "") or "").strip()
        if not redis_url:
            return
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
            )
            await client.ping()
            self._counter = _RedisCounter(client)
            logger.info("限流计数使用 Redis：%s", redis_url)
        except Exception as exc:  # noqa: BLE001 — 限流后端故障不得影响服务
            logger.warning("Redis 不可用，限流降级为进程内计数：%s", exc)

    def _headers(self, limit: int, remaining: int, reset_in: int) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_in),
        }

    # ---- 主流程 ----

    async def dispatch(self, request: Request, call_next):
        if (
            not self.enabled
            or request.method == "OPTIONS"
            or request.url.path in self.exempt_paths
        ):
            return await call_next(request)

        if not self._backend_resolved:
            await self._resolve_backend()

        now = time.time()
        bucket = int(now // self.window)
        reset_in = max(1, int(self.window - (now % self.window)))

        # 占位符由本用途决定：限流 key 需要一个稳定可拼的 token（见 client_ip docstring）
        key = f"ratelimit:{bucket}:{client_ip(request) or 'unknown'}"
        try:
            count = await self._counter.incr(key, self.window)
        except Exception as exc:  # noqa: BLE001 — 计数失败则放行（fail-open）
            logger.warning("限流计数失败，本次请求放行：%s", exc)
            return await call_next(request)

        remaining = max(0, self.limit - count)

        if count > self.limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Too Many Requests",
                    "detail": f"请求过于频繁，请 {reset_in} 秒后重试（上限 {self.limit} 次/{self.window}s）",
                },
                headers={
                    **self._headers(self.limit, 0, reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        response = await call_next(request)
        response.headers.update(self._headers(self.limit, remaining, reset_in))
        return response

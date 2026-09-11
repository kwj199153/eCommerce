"""
请求限流中间件（按客户端标识的固定窗口计数）

定位划分（重要）：
  - 本中间件负责「速率」——防刷、防爬，例如 60 次/分钟；
  - 套餐维度的「总量」额度由 core/billing 计费体系负责（api_calls_limit / agent_chat_limit）。
  两者互补，不要重复实现。

存储策略：
  - 默认：进程内内存计数（单进程 uvicorn 足够）
  - 若配置了可达的 Redis，自动切换为 Redis 计数（多 worker / 多副本共享同一个计数器）
  - Redis 不可用时自动降级为内存计数，且只告警一次，绝不因限流组件故障而拒绝服务

⚠️ 关于客户端 IP：
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

logger = logging.getLogger(__name__)

# 放行路径：健康检查与文档不应消耗限流额度
DEFAULT_EXEMPT_PATHS = frozenset({
    "/health",
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

    # ---- 内部工具 ----

    @staticmethod
    def _client_key(request: Request) -> str:
        """取客户端标识：优先 X-Forwarded-For 首跳，回落 request.client"""
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        client = request.client
        return client.host if client else "unknown"

    async def _resolve_backend(self) -> None:
        """首次请求时决定用 Redis 还是内存（只尝试一次）"""
        self._backend_resolved = True
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

        key = f"ratelimit:{bucket}:{self._client_key(request)}"
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

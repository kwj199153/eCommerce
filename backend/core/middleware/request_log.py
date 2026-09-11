"""
请求日志中间件

为每个请求生成 / 透传 X-Request-ID，记录一行结构化访问日志，并回写：
    X-Request-ID        请求追踪 ID（便于串联前后端与网关日志）
    X-Process-Time-Ms   服务端处理耗时（毫秒）

日志级别按状态码区分：5xx → error，4xx → warning，其余 → info；
超过 slow_request_ms 的请求额外打一条 warning，方便排查慢接口。

⚠️ 关于流式接口（SSE）：
   出于性能考虑，耗时统计的是「响应头就绪」时间（TTFB），
   而不是整个流式 body 传输完成的时间 —— 对 SSE 而言后者可能长达数十秒，
   把它算进接口耗时会让日志失去参考价值。
"""

import time
import uuid
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import config
from core.logger import get_logger

_log = get_logger("http")

# 健康检查等噪音路径降到 debug，避免刷屏
QUIET_PATHS = frozenset({"/health", "/favicon.ico"})


class RequestLogMiddleware(BaseHTTPMiddleware):
    """统一访问日志 + 请求 ID 分发"""

    def __init__(
        self,
        app,
        enabled: Optional[bool] = None,
        slow_request_ms: int = 3000,
    ) -> None:
        super().__init__(app)
        self.enabled = config.request_log_enabled if enabled is None else bool(enabled)
        self.slow_request_ms = int(slow_request_ms)

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        client = request.client
        return client.host if client else "-"

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        request_id = (request.headers.get("X-Request-ID") or "").strip() or uuid.uuid4().hex[:16]
        # 挂到 request.state：业务代码 / 异常处理器里可直接取到同一个 ID
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            cost_ms = (time.perf_counter() - started) * 1000
            _log.bind(request_id=request_id).exception(
                "{method} {path} -> 未捕获异常 ({cost:.1f}ms) client={client}",
                method=request.method, path=request.url.path,
                cost=cost_ms, client=self._client_ip(request),
            )
            raise

        cost_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{cost_ms:.1f}"

        # 租户中间件不做 request.state 写入，这里直接从同源头/参数取店铺
        shop_id = request.headers.get("X-Shop-ID") or request.query_params.get("shop_id") or "-"
        path = request.url.path
        status_code = response.status_code
        log = _log.bind(request_id=request_id)
        message = "{method} {path} -> {status} ({cost:.1f}ms) client={client} shop={shop}"
        fields = dict(
            method=request.method, path=path, status=status_code,
            cost=cost_ms, client=self._client_ip(request), shop=shop_id,
        )

        if path in QUIET_PATHS:
            log.debug(message, **fields)
        elif status_code >= 500:
            log.error(message, **fields)
        elif status_code >= 400:
            log.warning(message, **fields)
        else:
            log.info(message, **fields)
            if cost_ms >= self.slow_request_ms:
                log.warning(
                    "慢请求 {method} {path} 耗时 {cost:.1f}ms（阈值 {slow}ms）",
                    method=request.method, path=path,
                    cost=cost_ms, slow=self.slow_request_ms,
                )

        return response

"""
请求日志中间件

为每个请求生成 / 透传 X-Request-ID，记录一行结构化访问日志，并回写：
    X-Request-ID        请求追踪 ID（便于串联前后端与网关日志）
    X-Process-Time-Ms   服务端处理耗时（毫秒）

日志级别按状态码区分：5xx → error，4xx → warning，其余 → info；
超过 slow_request_ms 的请求额外打一条 warning，方便排查慢接口。

★ 2026-09-15 增强（可观测性 P1-8）：
    1. **写入请求上下文**：把 request_id / shop_id 放进 ContextVar，
       于是**业务代码打的所有日志自动带上 request_id**（由 core/logger.py 的
       patcher 注入）—— 修复前只有这一行访问日志有 ID，业务日志没有，
       线上排障无法把「一个请求里的若干条日志」串起来。
    2. **记录 HTTP 指标**：计数 + 耗时直方图 + 在途请求数，经 /metrics 暴露。
       路径经 normalize_path() 归一化，防止 UUID 撑爆时间序列基数。
    3. **务必在 finally 清上下文**：keep-alive 连接下同一个 asyncio 任务会
       复用于后续请求，不清会把上一个请求的 ID 带到下一个请求里。

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
from core.observability.context import clear_request_context, set_request_context
from core.observability.metrics import (
    HTTP_DURATION,
    HTTP_IN_FLIGHT,
    HTTP_REQUESTS,
    normalize_path,
)

_log = get_logger("http")

# 健康检查 / 指标采集等噪音路径降到 debug，避免刷屏
QUIET_PATHS = frozenset({"/health", "/metrics", "/favicon.ico"})


class RequestLogMiddleware(BaseHTTPMiddleware):
    """统一访问日志 + 请求 ID 分发 + HTTP 指标"""

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

        # ★ 写入 ContextVar —— 必须在 call_next 之前，
        #   下游 app 作为独立 task 启动时会继承此刻的上下文快照。
        shop_id = request.headers.get("X-Shop-ID") or request.query_params.get("shop_id") or "-"
        set_request_context(request_id=request_id, shop_id=shop_id)

        path = request.url.path
        method = request.method
        route_label = normalize_path(path)  # 低基数标签

        HTTP_IN_FLIGHT.inc()
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                cost_ms = (time.perf_counter() - started) * 1000
                _log.bind(request_id=request_id, shop_id=shop_id).exception(
                    "{method} {path} -> 未捕获异常 ({cost:.1f}ms) client={client}",
                    method=method, path=path,
                    cost=cost_ms, client=self._client_ip(request),
                )
                HTTP_REQUESTS.inc(method=method, path=route_label, status="500")
                HTTP_DURATION.observe(cost_ms, method=method, path=route_label)
                raise

            cost_ms = (time.perf_counter() - started) * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = f"{cost_ms:.1f}"

            status_code = response.status_code

            # --- 指标 ---
            HTTP_REQUESTS.inc(method=method, path=route_label, status=str(status_code))
            HTTP_DURATION.observe(cost_ms, method=method, path=route_label)

            # --- 访问日志 ---
            log = _log.bind(request_id=request_id, shop_id=shop_id)
            message = "{method} {path} -> {status} ({cost:.1f}ms) client={client} shop={shop}"
            fields = dict(
                method=method, path=path, status=status_code,
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
                        method=method, path=path,
                        cost=cost_ms, slow=self.slow_request_ms,
                    )

            return response
        finally:
            HTTP_IN_FLIGHT.dec()
            # ★ 必须清 —— keep-alive 下同一任务会复用于后续请求
            clear_request_context()

"""
可观测性工具箱（observability）

三个能力，各自一个模块，互不依赖：

| 模块        | 解决什么                                        | 出口              |
|-------------|-------------------------------------------------|-------------------|
| context.py  | 业务日志不带 request_id ⇒ 无法串联一次请求        | loguru patcher    |
| metrics.py  | 无任何指标 ⇒ 不知道线上 QPS/错误率/慢在哪          | GET /metrics      |
| sentry.py   | 生产 5xx 只能等人反馈                             | Sentry（可选）     |

使用约定：
    - **中间件**（core/middleware/request_log.py）负责：写上下文 → 记 HTTP 指标 → 清上下文
    - **业务代码**只需 `from core.observability.metrics import LLM_CALLS` 后 inc()，
      日志里自动带上 request_id（无需改任何 logger 调用）
    - **不要**在业务代码里 set/clear 上下文（生命周期归中间件管）
"""

from core.observability.context import (
    EMPTY,
    clear_request_context,
    current_request_id,
    current_shop_id,
    current_user_id,
    set_request_context,
    snapshot,
)
from core.observability.metrics import (
    AIGC_TASK_DURATION,
    AIGC_TASKS,
    CELERY_TASK_RESULTS,
    DEPENDENCY_UP,
    HTTP_DURATION,
    HTTP_IN_FLIGHT,
    HTTP_REQUESTS,
    LLM_CALLS,
    LLM_TOKENS,
    QUOTA_REJECTIONS,
    normalize_path,
    render_prometheus,
)

__all__ = [
    "EMPTY",
    "set_request_context",
    "clear_request_context",
    "current_request_id",
    "current_shop_id",
    "current_user_id",
    "snapshot",
    "normalize_path",
    "render_prometheus",
    "HTTP_REQUESTS",
    "HTTP_DURATION",
    "HTTP_IN_FLIGHT",
    "LLM_CALLS",
    "LLM_TOKENS",
    "AIGC_TASKS",
    "AIGC_TASK_DURATION",
    "QUOTA_REJECTIONS",
    "CELERY_TASK_RESULTS",
    "DEPENDENCY_UP",
]

"""
请求级上下文（observability/context.py）

背景：
    `core/middleware/request_log.py` 早就为每个请求生成了 request_id，但它
    **只出现在那一行访问日志里** —— 业务代码里 `logger.info(...)` 打出来的日志
    完全不带 request_id。结果是：线上一个请求报错，你只能看到一行访问日志和
    零散的业务日志，无法用同一个 ID 把它们串起来。

    本模块用 ContextVar 承载「当前请求的标识」，配合 `core/logger.py` 里的
    loguru patcher，让**任意模块、任意层级**的日志自动带上 request_id / shop_id。

为什么用 ContextVar 而不是 middleware 手动传参：
    - 异步场景下 threading.local 会串请求；ContextVar 是 asyncio 官方方案
      （每个 task 有独立副本，不会互相污染）。
    - 零侵入：业务函数不需要多接一个 request_id 参数。

⚠️ 三个必须注意的点：
    1. ContextVar 只在**同一个 asyncio task 内**可见。`asyncio.create_task()`
       起的子任务会继承一份拷贝（值能读到，但父任务后续的 set 子任务看不到）；
       Celery 任务、线程池里的代码**读不到** —— 所以入队时必须把 request_id
       作为显式参数带上（见 modules/aigc_media/tasks.py 的做法）。
    2. 中间件必须在 finally 里 clear()，否则复用连接的 keep-alive 请求
       会把上一个请求的 ID 带进来（本项由 request_log 中间件保证）。
    3. 值是字符串，空串代表「无请求上下文」（如启动期、定时任务）。
"""

import contextvars
from typing import Optional

# ====== 上下文变量 ======
# 默认空串（而非 None）：让 patcher 里的判断保持简单，日志渲染时统一兜底成 "-"
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
_shop_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "shop_id", default=""
)
_user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default=""
)

# 日志里代表「空」的占位符
EMPTY = "-"


# ====== 写入 ======

def set_request_context(
    *,
    request_id: Optional[str] = None,
    shop_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    设置当前上下文的标识。

    只覆盖传了值的字段 —— 允许中间件先设 request_id，鉴权依赖随后只补 user_id，
    不会把前者冲掉。
    """
    if request_id is not None:
        _request_id_var.set(request_id)
    if shop_id is not None:
        _shop_id_var.set(shop_id)
    if user_id is not None:
        _user_id_var.set(user_id)


def clear_request_context() -> None:
    """清空上下文（中间件 finally 里必须调用）"""
    _request_id_var.set("")
    _shop_id_var.set("")
    _user_id_var.set("")


# ====== 读取 ======

def current_request_id() -> str:
    """当前请求 ID；无上下文返回空串"""
    return _request_id_var.get()


def current_shop_id() -> str:
    """当前店铺 ID；无上下文返回空串"""
    return _shop_id_var.get()


def current_user_id() -> str:
    """当前用户 ID；无上下文返回空串"""
    return _user_id_var.get()


def snapshot() -> dict:
    """
    当前上下文的快照，用于：
      - 日志 patcher 注入
      - 把 request_id 显式传给 Celery 任务 / 线程池（见模块 docstring ⚠️1）
    """
    return {
        "request_id": _request_id_var.get() or EMPTY,
        "shop_id": _shop_id_var.get() or EMPTY,
        "user_id": _user_id_var.get() or EMPTY,
    }

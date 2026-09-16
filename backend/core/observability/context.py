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

★ P0-2（2026-09-16）修复：本模块此前只有 request_id / shop_id **真的被写入**。
    `_user_id_var` 定义了、`current_user_id()` 导出了，却**全项目 0 处写入** ——
    任何按用户打标签的日志/审计拿到的都是空串；`account_id` / `client_ip`
    当时根本不存在。现在五个字段各自有**明确且唯一**的写入点：

        字段        写入点
        --------    ------------------------------------------------------
        request_id  请求日志中间件（每请求生成 / 透传 X-Request-ID）
        client_ip   请求日志中间件（与限流共用 core/middleware/client_ip.py）
        shop_id     请求日志中间件（原始头值，仅供日志展示，**不是**授权依据）
        user_id     鉴权依赖 core/auth/dependencies.get_current_user
        account_id  core/tenant/middleware._resolve_current_shop_id

    ★ 为什么 account_id **不**在鉴权依赖里写：一个用户可属于多个账户
      （个人账户 + 被邀请的团队账户），"本次请求属于哪个账户"只有解析出
      具体店铺之后才知道。在鉴权阶段写一个猜测值 = 把错误归属扩散到
      全部日志与审计里。

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
# ★ P0-2：account_id = 「租户」在本项目的实际语义（P1-c 收拢后 == accounts.id）
_account_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "account_id", default=""
)
# ★ P0-2：请求来源 IP（取法见 core/middleware/client_ip.py，中间件层唯一实现）
_client_ip_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "client_ip", default=""
)

# 日志里代表「空」的占位符
EMPTY = "-"


# ====== 写入 ======

def set_request_context(
    *,
    request_id: Optional[str] = None,
    shop_id: Optional[str] = None,
    user_id: Optional[str] = None,
    account_id: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> None:
    """
    设置当前上下文的标识（统一 Context 的**唯一**写入口）。

    只覆盖传了值的字段（`None` = "本次不改这一项"）—— 这是一条**故意**的契约：
    中间件先设 request_id / client_ip，鉴权依赖随后只补 user_id，
    店铺解析处再补 account_id，多次写入互不冲掉。

    ⚠️ `None` 与空串在此语义不同：`None` = 跳过不写；`""` = 显式写空。
      要清空整个上下文请用 `clear_request_context()`，不要用空串绕契约。
    """
    if request_id is not None:
        _request_id_var.set(request_id)
    if shop_id is not None:
        _shop_id_var.set(shop_id)
    if user_id is not None:
        _user_id_var.set(user_id)
    if account_id is not None:
        _account_id_var.set(account_id)
    if client_ip is not None:
        _client_ip_var.set(client_ip)


def clear_request_context() -> None:
    """清空上下文（中间件 finally 里必须调用）"""
    _request_id_var.set("")
    _shop_id_var.set("")
    _user_id_var.set("")
    _account_id_var.set("")
    _client_ip_var.set("")


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


def current_account_id() -> str:
    """当前账户 ID（== 本项目的租户语义）；无上下文返回空串"""
    return _account_id_var.get()


def current_client_ip() -> str:
    """当前请求来源 IP；无上下文返回空串"""
    return _client_ip_var.get()


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
        "account_id": _account_id_var.get() or EMPTY,
        "client_ip": _client_ip_var.get() or EMPTY,
    }


#: 统一 Context 的字段全集（★ P0-2）—— 供门禁测试对账用。
#: 新增字段时**必须**同步四处：写入（set_request_context）、读取（current_*）、
#: snapshot()、logger patcher。漏一处就是"字段恒为空"的静默失效 ——
#: 本轮修的正是这种形态（user_id 定义了、导出了、0 处写入）。
CONTEXT_FIELDS = ("request_id", "user_id", "account_id", "shop_id", "client_ip")

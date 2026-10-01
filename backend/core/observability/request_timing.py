"""
请求级**分段计时**（DB / LLM 毫秒）

与 `core/observability/context.py` 的分工：
    · context.py 管**字符串标识**（request_id / shop_id …），出口是日志 patcher；
    · 本模块管**单调累加的毫秒数**，出口是响应头 X-DB-Time-Ms / X-LLM-Time-Ms。
两者都用 ContextVar，但类型与消费方不同，故分文件 —— 不把浮点计时塞进
context.py 那张「字段 → 写入点」契约表（那张表登记的是**日志字段**）。

★ 为什么必须是「一个 ContextVar 承载一个**可变对象**」，而不是直接累加 ContextVar
  （第 351 轮 L3-3 实测，探针 `.workbuddy/probes/r351/l3_3_task_boundary.py`）：

    中间件的真实拓扑是

        RequestLogMiddleware.dispatch  ── call_next ──►  下游 app（**独立 task**）

    asyncio / anyio 的 Task 在创建时 `copy_context()` ⇒ 子任务里的 `ContextVar.set()`
    只改自己那份**拷贝**，父任务**读不到**。实测：

        子任务里 val_var.set(999)           ⇒ 中间件读回 0     （方案 A 失败）
        子任务里 box.n = 777（改对象字段）   ⇒ 中间件读回 777   （方案 B 成功）

    context 被拷贝时**共享同一个对象引用** ⇒「先 set 一个新对象，之后只改它的字段」
    就能把下游累加的值带回中间件。本模块是方案 B 的唯一实现。

★ 边界（防误用）：
    · 只有**一个** ContextVar 承载计时对象，且**只在中间件里 set**；
      业务代码一律用 `add_db_ms()` / `add_llm_ms()` 就地累加，**不要**自己 set。
    · 无请求上下文时 `current_timing()` 返回 `None`（不是零值对象）：定时任务 /
      启动期 / 脚本里直接调函数**不得**静默累加到某个全局对象上 ——
      那样会把定时任务的耗时算进上一个 HTTP 请求里。
"""

import contextvars
import dataclasses
from typing import Optional


@dataclasses.dataclass
class RequestTiming:
    """一次请求内的分段耗时（毫秒）。**字段就地累加，不替换对象**。

    ★ 为什么用 dataclass 而不是 dict：字段名有类型检查兜底 ——
      把 `timing.db_ms` 敲成 `timing.dbms` 会立刻被 mypy 抓住，而 dict 只会静默多一个键。
    """

    db_ms: float = 0.0
    llm_ms: float = 0.0


_timing_var: contextvars.ContextVar[Optional[RequestTiming]] = contextvars.ContextVar(
    "request_timing", default=None
)


def start_timing() -> RequestTiming:
    """开一次分段计时（**中间件在 `call_next` 之前**调用）。

    返回新建的计时对象；之后的 `add_db_ms` / `add_llm_ms` 都改它这一个对象。
    """
    timing = RequestTiming()
    _timing_var.set(timing)
    return timing


def current_timing() -> Optional[RequestTiming]:
    """当前请求的计时对象；无请求上下文返回 `None`。"""
    return _timing_var.get()


def _bump(field: str, ms: float) -> None:
    timing = _timing_var.get()
    if timing is None:
        # 无请求上下文（定时任务 / 脚本）⇒ 静默不累加。这是**有意**的：
        # 编一个全局计时对象只会让「这次请求等了多久」变成假数据。
        return
    setattr(timing, field, getattr(timing, field) + ms)


def add_db_ms(ms: float) -> None:
    """累加一次 SQL 执行耗时（由 `core/database.py` 的引擎事件回调调用）。"""
    _bump("db_ms", ms)


def add_llm_ms(ms: float) -> None:
    """累加一次 LLM 调用耗时（由 `ai_infra/llm/dashscope_client.py` 调用）。"""
    _bump("llm_ms", ms)


def clear_timing() -> None:
    """清空（中间件 finally 里调用，与 `clear_request_context()` 同处）。"""
    _timing_var.set(None)

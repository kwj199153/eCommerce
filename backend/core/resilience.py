"""
统一弹性原语（retry / backoff）—— 全项目**唯一**的重试实现

★★★ 为什么必须有这个模块（第 94 轮「横切关注点三层安放」审计的结论）
    收敛前实测：全项目有 **3 套互不共享** 的自研重试实现 ——

        ai_infra/llm/dashscope_client.py::_call_with_retry           （第 95 轮收敛）
        modules/aigc_media/image_client.py::_gather_many._one         （第 96 轮收敛）
        platforms/amazon/sp_api/auth.py::make_authenticated_request   （第 96 轮收敛）

    ⚠️ 第 94 轮审计的原始清单还列了 `core/redis.py` 与 `platforms/payment/gateway.py`，
       第 96 轮用 **AST 全仓重扫**（门禁见 `tests/test_resilience.py::test_no_retry_loop_outside_resilience`）
       证实这两条是**误报**，它们不是自研重试：
         · `payment/gateway.py` 一条重试循环都没有，而且这是**刻意的** ——
           注释明写「否则网络重试 / 双击会真的扣两次钱」（幂等键才是它的正确防线）。
         · `core/redis.py` 只有 `broker_connection_retry_on_startup=True`，
           那是 **Celery 框架自己的配置项**，收敛它等于砍掉 worker 的启动鲁棒性。
       ⇒ 教训：**审计数字必须能被复算**。按名枚举调用点既会漏（第 94 轮漏了 2 份
         客户端 IP 拷贝），也会多（这里多了 2 条）。所以门禁改为对**代码形态**做
         AST 扫描，而不是维护一份"共有 N 套"的名单 —— 名单会腐烂，形态不会。

    代价不只是"抄了几遍"。同一份**策略知识**没有落点，于是同一个文件里都能不一致：
    `dashscope_client.chat()` 走 `_call_with_retry`（429 指数退避 + 5xx 重试），
    而**同一个文件的 `chat_stream()` 完全没有重试** —— 流式接口遇到一次连接抖动
    就直接失败，非流式却会自己恢复。也没有任何一处能回答
    「什么错该重试 / 重试几次 / 等多久」这三个问题。

★★ 定位与边界（照第 94 轮确立的三层分工）
    · 本模块是**核心实现**，不是钩子。四个导出即覆盖全部用法：
          RetryPolicy / call_with_retry / retrying_stream / with_retry
    · 它**无状态**，可以当模块级单例直接用，不需要 DI 托管 ——
      中间件层（`BaseHTTPMiddleware.dispatch`）**不在 FastAPI 的依赖图里**，
      拿不到 `Depends`；把无状态的策略对象做成"必须注入"只会逼出一层层包装壳。
      DI 只在路由层用（注入 Service / DB / 第三方客户端），重试不在此列。
    · `with_retry` 是**装饰器形态**，供 Service / Agent 内部方法使用 ——
      HTTP 与 Celery 后台任务都生效（后台任务不走中间件、不走路由 DI）。
      装饰器只是薄壳，逻辑全在 `call_with_retry`。

★★★ 三条必须遵守的约束（不照做会写出更糟的东西）
    1. **不重试已被消费的流**。`retrying_stream` 只重试「建立连接 / 拿到响应头」
       这一步；一旦 `yield` 出去就**永不重试** —— 否则会把自己已经发给用户的正文
       再发一遍。用户看到重复内容，比一次干脆的失败难排查得多。
    2. **不要为了"统一"把有意的降级改成抛错**。限流 fail-open（rate_limit.py）、
       单枚撤销 fail-open（auth/revocation.py）、Sentry「没配就跳过」
       （observability/sentry.py）都是刻意设计。本模块只提供重试原语，
       不替调用方决定降级语义。
       ★ 同类极端形态：**支付扣款路径连重试都不该有**（`payment/gateway.py`
         刻意零重试，靠幂等键防重复扣款）。"把重试统一进来"不等于"每处都要
         用上重试" —— 有时候**没有重试**才是正确实现。
    3. **`asyncio.CancelledError` 永不重试**。它是协作式取消的信号（客户端断开、
       上层超时取消），重试等于让已取消的操作继续跑，并且会把取消吞掉。

⚠️ 一个容易漏的点：`Retry-After` 只解析「秒数」形态
    HTTP 允许 `Retry-After` 是秒数或 HTTP-date（RFC 9110）。这里只认秒数，
    HTTP-date 形态回落到退避表 —— 解析日期要引入 tz-aware 时间计算，
    而绝大多数网关（含 DashScope / Nginx）用的都是秒数。
"""

import asyncio
import functools
import inspect
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    Optional,
    Tuple,
    TypeVar,
)

import httpx

from core.logger import get_logger

_log = get_logger(__name__)

T = TypeVar("T")

#: `on_retry(what, attempt, attempts, delay, exc)` —— 每次「决定重试」时回调一次
OnRetry = Callable[[str, int, int, float, BaseException], None]


# ====== 策略 ======

@dataclass(frozen=True)
class RetryPolicy:
    """
    重试策略（不可变值对象 —— 可以放心地做模块级单例、跨请求共享）。

    Attributes:
        attempts: **总尝试次数**（不是"重试次数"）。`attempts=3` = 最多跑 3 次。
                  ★ 这个口径必须写死，否则调用方按"重试 3 次"理解就会变成 4 次。
        base_delay: 第一次失败后的等待秒数。
        multiplier: 退避倍数（指数退避）。
        max_delay: 单次等待上限（防止 attempts 大时退避到几分钟）。
        jitter: 抖动比例 0~1。多客户端同时被限流时，固定退避会让它们
                在同一时刻齐刷刷重试（thundering herd）。默认 0 = 不抖。
        retry_statuses: 可重试的 HTTP 状态码。429 是限流、5xx 是服务端临时故障；
                其余 4xx（401/403/404/422…）都是**确定性失败**，重试只是浪费配额。
        retry_if: 自定义可重试判定，给「失败时抛的不是 httpx 异常」的 provider 用。
                ★ 为什么需要它：有些 API（如万相出图）的失败是**业务错误码**
                  （`Throttling.RateQuota` 之类），只能从错误码/文案里读出
                  "该不该重试"。没有这个钩子，这类调用方就只能再自己抄一遍
                  循环 —— 而那正是本模块要消灭的东西。
                ★ 只在 httpx 判定**之后**兜底调用：`HTTPStatusError` /
                  `TransportError` / `TimeoutError` 的结论优先级更高，
                  一个确定性 4xx 不会被这个钩子"救回来"。
    """

    attempts: int = 3
    base_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.0
    retry_statuses: Tuple[int, ...] = (429, 500, 502, 503, 504)
    #: 见 docstring。默认为 None = 只看 httpx 异常类型
    retry_if: Optional[Callable[[BaseException], bool]] = None

    def delay_for(self, attempt: int, hint: Optional[float] = None) -> float:
        """
        第 `attempt` 次失败后该等多久（attempt 从 1 开始）。

        `hint` = 服务端明确要求的等待秒数（`Retry-After`）。服务端说了算 ——
        它比任何本地退避表都准，但仍然要过 `max_delay` 封顶，
        避免一个恶意/错误的头部让请求睡到天荒地老。
        """
        if hint is not None:
            return min(max(0.0, float(hint)), self.max_delay)

        raw = self.base_delay * (self.multiplier ** max(0, attempt - 1))
        if self.jitter:
            raw *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return min(max(0.0, raw), self.max_delay)

    def classify(self, exc: BaseException) -> Tuple[bool, Optional[float]]:
        """
        判定一个异常该不该重试。

        Returns:
            `(是否可重试, 服务端建议的等待秒数或 None)`

        ★ 判"确定性失败"优先于"网络抖动"：4xx 里除了 429 都不重试。
          重试一个 400（请求体不合法）不会有任何不同结果，只会把配额和
          调用次数指标一起浪费掉。
        """
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in self.retry_statuses:
                return True, _retry_after_seconds(exc.response)
            return False, None

        # 连接失败 / 读写超时 / DNS 失败 / TLS 握手失败 —— 都是临时性的
        if isinstance(exc, httpx.TransportError):
            return True, None

        # 裸 asyncio 超时（未被 httpx 包装的场景，如 wait_for 上游）
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True, None

        # ★ 最后兜底：调用方自定义判定（业务错误码 / 异常文案）。
        #   放最后是有意的 —— httpx 那几条结论优先，确定性 4xx 不在这里被"救回来"。
        if self.retry_if is not None and self.retry_if(exc):
            return True, None

        return False, None


#: 默认策略：3 次尝试、1s 起指数退避、上限 30s
DEFAULT_POLICY = RetryPolicy()


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """解析 `Retry-After` 的**秒数**形态；HTTP-date 形态返回 None（见模块 docstring）。"""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# ====== 核心：一次性调用的重试 ======

async def call_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy = DEFAULT_POLICY,
    what: str = "operation",
    on_retry: Optional[OnRetry] = None,
    wrap: Optional[Callable[[int, BaseException], BaseException]] = None,
) -> T:
    """
    执行 `fn()`，失败时按 `policy` 重试。**所有重试逻辑的唯一实现**。

    Args:
        fn: 无参可等待工厂 —— 传 `lambda: do(x)` 而不是 `do(x)`。
            ★ 必须是工厂：协程对象只能 await 一次，把已经创建好的协程传进来，
              第二次重试会撞 `cannot reuse already awaited coroutine`。
        policy: 重试策略。
        what: 人类可读的操作名，进日志（如 `"LLM chat (qwen-max)"`）。
        on_retry: 每次决定重试时的回调；不传则打一条 warning。
                  传 `lambda *a: None` 可静音（测试里常用）。
        wrap: 重试耗尽后用来包装最终异常的工厂 `(attempts, last_error) -> exc`。
              不传则原样抛出最后一次的异常（保留原始 traceback，通常更好）。

    Raises:
        最后一次尝试的异常（或 `wrap` 产出的异常）。
    """
    if policy.attempts < 1:
        raise ValueError(f"RetryPolicy.attempts 必须 >= 1（收到 {policy.attempts}）")

    last_exc: Optional[BaseException] = None

    for attempt in range(1, policy.attempts + 1):
        try:
            return await fn()
        except asyncio.CancelledError:
            # ★ 约束 3：取消不是失败，绝不重试
            raise
        except BaseException as exc:  # noqa: BLE001 —— 由 policy.classify 决定去留
            last_exc = exc
            retryable, hint = policy.classify(exc)
            if not retryable or attempt >= policy.attempts:
                break

            delay = policy.delay_for(attempt, hint)
            _notify(on_retry, what, attempt, policy.attempts, delay, exc)
            await asyncio.sleep(delay)

    assert last_exc is not None  # 循环只在 except 分支里 break
    if wrap is not None:
        raise wrap(policy.attempts, last_exc) from last_exc
    raise last_exc


# ====== 核心：流式的重试（只重试"建立连接"） ======

@asynccontextmanager
async def retrying_stream(
    open_stream: Callable[[], AsyncContextManager[T]],
    *,
    policy: RetryPolicy = DEFAULT_POLICY,
    what: str = "stream",
    on_retry: Optional[OnRetry] = None,
):
    """
    建立流式连接，失败时按 `policy` 重试 —— **只重试建立连接这一步**。

    Args:
        open_stream: **同步**可调用，返回一个 **async 上下文管理器**。
                     `httpx.AsyncClient.stream(...)` 正好是这个形状
                     （`async with client.stream(...) as r:`）。
                     ⚠️ 不要传"已经 await 好的对象"，也不要传 async 函数。

    Yields:
        `open_stream()` 返回的上下文管理器 `__aenter__` 的结果（如 `httpx.Response`）。

    ★★★ 为什么只重试"建立连接"（本模块最重要的语义约束）
        HTTP 流的正文是**边收边转发**的。一旦第一个 chunk 已经 `yield` 给上层
        （在 SSE 场景里已经写进响应体发给浏览器了），重连就意味着把读者已经
        看到的内容**再发一遍** —— 用户看到重复正文，而这比一次干脆的失败
        难排查得多。所以：`__aenter__` 期间失败 → 可重试；进入 `yield` 之后
        的任何异常 → 原样向上抛，由调用方决定（重试整条请求是**产品决策**，
        不是传输层能替用户做的）。
    """
    if policy.attempts < 1:
        raise ValueError(f"RetryPolicy.attempts 必须 >= 1（收到 {policy.attempts}）")

    cm: Optional[AsyncContextManager[T]] = None
    response: Optional[T] = None
    last_exc: Optional[BaseException] = None

    for attempt in range(1, policy.attempts + 1):
        try:
            candidate = open_stream()
            response = await candidate.__aenter__()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            retryable, hint = policy.classify(exc)
            if not retryable or attempt >= policy.attempts:
                raise

            delay = policy.delay_for(attempt, hint)
            _notify(on_retry, what, attempt, policy.attempts, delay, exc)
            await asyncio.sleep(delay)
        else:
            cm = candidate
            break

    if cm is None:  # 防御分支：正常路径要么 break 要么 raise
        raise last_exc if last_exc is not None else RuntimeError(f"{what}: 未能建立连接")

    try:
        yield response
    finally:
        # 显式关闭（`__aenter__` 已经手动调用过，不能再 `async with cm` 二次进入）
        await cm.__aexit__(None, None, None)


# ====== 装饰器形态（Service / Agent / 后台任务） ======

def with_retry(policy: RetryPolicy = DEFAULT_POLICY, *, what: Optional[str] = None):
    """
    给 Service / Agent 的 **异步方法**挂上重试。

        @with_retry(RetryPolicy(attempts=3, base_delay=0.5))
        async def call_dashscope(self, prompt): ...

    ★ 为什么需要它：后台任务（Celery）与 Agent 内部调用**不走 HTTP 中间件、
      也不走路由 DI**，横切能力只能靠装饰器触达。装饰器本身不含逻辑，
      只是 `call_with_retry` 的薄壳（这正是第 94 轮确立的分工）。

    ⚠️ 两道防错（都会**显式报错**，不做静默降级）：
        1. `async def f(): yield ...`（async generator）**不能**用它 ——
           包装后函数会从"逐块产出"变成"一次性返回异步生成器对象"，
           流式契约被静默破坏。请改用 `retrying_stream()`。
        2. 同步函数也不支持 —— 用同步重试会阻塞事件循环，本模块只做异步。
           同步场景请显式写循环，或先把它改成 async。
    """

    def decorator(fn):
        name = what or getattr(fn, "__qualname__", repr(fn))

        if inspect.isasyncgenfunction(fn):
            raise TypeError(
                f"{name} 是 async generator，不能用 with_retry 包装："
                "包装后会把它变成一次性返回（流式契约被静默破坏）。"
                "流式请用 retrying_stream()，只对『建立连接』那一步重试。"
            )
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"{name} 不是 async 函数。本模块只提供异步重试 —— "
                "同步重试会阻塞事件循环；请先把函数改成 async。"
            )

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await call_with_retry(
                lambda: fn(*args, **kwargs),
                policy=policy,
                what=name,
            )

        # 打上标记，便于静态检查/AST 门禁识别"这个函数已被重试覆盖"
        wrapper.__retry_policy__ = policy  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ====== 内部 ======

def _notify(
    on_retry: Optional[OnRetry],
    what: str,
    attempt: int,
    attempts: int,
    delay: float,
    exc: BaseException,
) -> None:
    """统一的"即将重试"通知（默认打 warning，可被调用方替换）。"""
    if on_retry is not None:
        on_retry(what, attempt, attempts, delay, exc)
        return
    _log.warning(
        "{} 第 {}/{} 次失败（{}: {}），{:.2f}s 后重试",
        what,
        attempt,
        attempts,
        type(exc).__name__,
        exc,
        delay,
    )

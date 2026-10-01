# -*- coding: utf-8 -*-
"""请求级**分段**计时（L3-3，第 351 轮）—— 三道守卫

覆盖：
  1. `core/observability/request_timing.py` 的模块语义（对象身份 / 无上下文不累加）；
  2. ★ **跨任务边界**：中间件（父 task）必须能读到下游路由（独立 task）累加的值；
  3. 引擎事件真的接上了（`event.contains` 反查 + 在真 SQLite 引擎上跑真 SQL）。

★ 为什么第 2 条是本项的核心（不是"顺手测一下"）：
    中间件的 `call_next` 会**另起一个 asyncio task**（starlette `BaseHTTPMiddleware`
    的 anyio task group），而 Task 在创建时 `copy_context()` ⇒ 子任务里的
    `ContextVar.set()` 只改自己那份**拷贝**，父任务读不到。

    实测（`.workbuddy/probes/r351/l3_3_task_boundary.py`）：
        子任务 set 999       ⇒ 中间件读回 0     （直接累加 ContextVar：失败）
        子任务改对象字段 777  ⇒ 中间件读回 777   （可变容器：成功）

    所以实现必须是「一个 ContextVar 承载一个**可变对象**」。
    反向注入见 `.workbuddy/probes/r351/revinject_timing_snapshot.py`：
    把实现换成「快照式读 ContextVar」⇒ 本文件第 2 组用例必红。

★ 为什么 DB 用例用**同步** sqlite 内存引擎：
    `event.listens_for` 挂的就是 `sync_engine`，事件链路与生产一致
    （async 引擎只是在外面套了一层 greenlet）。backend venv 未装 `aiosqlite`，
    故不用 `sqlite+aiosqlite` —— 不为了写测试去污染依赖清单。
"""

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text

from core.database import INSTALLED_TIMING_LISTENERS, engine, install_db_timing
from core.middleware import RequestLogMiddleware
from core.observability.request_timing import (
    add_db_ms,
    add_llm_ms,
    clear_timing,
    current_timing,
    start_timing,
)


# ====== 玩具应用：路由在**下游独立 task** 里累加 ======

def _make_inner_app() -> FastAPI:
    inner = FastAPI()

    @inner.get("/ping")
    async def ping():
        return {"ok": True}

    @inner.get("/segmented")
    async def segmented():
        # ★ 模拟 DB / LLM 层：它们在下游 task 里就地累加（不 set，不换对象）
        add_db_ms(12.5)
        add_llm_ms(7.5)
        return {"ok": True}

    return inner


def _client(asgi_app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=asgi_app), base_url="http://testserver"
    )


def _ms(header_value: str) -> float:
    return float(header_value)


# ====== 1. 模块语义 ======

def test_start_returns_same_object_that_current_reads():
    clear_timing()
    try:
        t = start_timing()
        assert current_timing() is t, (
            "start 返回的不是 current 读到的那个对象 ⇒ 下游累加会丢"
        )
        add_db_ms(1.5)
        add_llm_ms(2.5)
        assert t.db_ms == pytest.approx(1.5)
        assert t.llm_ms == pytest.approx(2.5)
    finally:
        clear_timing()


def test_no_request_context_does_not_accumulate():
    """无请求上下文（定时任务 / 启动期 / 脚本）时不得静默累加。

    `current_timing()` 必须是 `None` —— 不是某个全局零值对象；
    否则定时任务的耗时会被算进上一个 HTTP 请求里。
    """
    clear_timing()
    assert current_timing() is None
    add_db_ms(9.0)   # 必须**不炸**，也不得写进任何全局对象
    add_llm_ms(9.0)
    assert current_timing() is None


def test_clear_resets_current():
    start_timing()
    add_db_ms(3.0)
    clear_timing()
    assert current_timing() is None, "clear 之后仍拿得到计时对象 ⇒ keep-alive 会串味"


# ====== 2. ★ 跨任务边界传播 ======

async def test_segmented_headers_reach_middleware_across_tasks():
    """下游 task 累加的分段耗时，必须出现在响应头里。

    ★ 本项的真正风险点：若实现改成「子任务里 set 自己的 ContextVar」，
      父任务（中间件）读不到 ⇒ 两个头都是 0.0，本用例必红。
    """
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r = await c.get("/segmented")

    assert r.status_code == 200
    assert _ms(r.headers["X-DB-Time-Ms"]) == pytest.approx(12.5, abs=0.06), (
        "DB 分段没有跨任务边界回传 —— 多半是把「可变容器」换成了「快照式读 ContextVar」"
    )
    assert _ms(r.headers["X-LLM-Time-Ms"]) == pytest.approx(7.5, abs=0.06), (
        "LLM 分段没有跨任务边界回传"
    )
    # 与既有口径共存：总耗时头仍在（既有 4 条契约不许被本次改造破坏）
    assert _ms(r.headers["X-Process-Time-Ms"]) >= 0


async def test_segmented_headers_default_to_zero_when_no_work():
    """路由里没干活 ⇒ 两个分段头必须存在且为 0.0（不是缺失、不是空串）。"""
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r = await c.get("/ping")

    assert _ms(r.headers["X-DB-Time-Ms"]) == 0.0
    assert _ms(r.headers["X-LLM-Time-Ms"]) == 0.0


async def test_timing_cleared_between_requests():
    """keep-alive 复用同一 task ⇒ 上一次请求的累加值不得漏进下一次。"""
    app = RequestLogMiddleware(_make_inner_app(), enabled=True)
    async with _client(app) as c:
        r1 = await c.get("/segmented")
        r2 = await c.get("/ping")

    assert _ms(r1.headers["X-DB-Time-Ms"]) == pytest.approx(12.5, abs=0.06)
    assert _ms(r2.headers["X-DB-Time-Ms"]) == 0.0, (
        "上一次请求的分段耗时漏进了下一次 —— finally 里没清计时对象"
    )


async def test_disabled_middleware_adds_no_segmented_headers():
    app = RequestLogMiddleware(_make_inner_app(), enabled=False)
    async with _client(app) as c:
        r = await c.get("/segmented")

    assert "X-DB-Time-Ms" not in r.headers
    assert "X-LLM-Time-Ms" not in r.headers


# ====== 3. 引擎事件接线 ======

def test_global_engine_has_db_timing_listener_installed():
    """模块级引擎必须真的装了 cursor 事件。

    ★ 用 `sqlalchemy.event.contains` **问库本身**（本仓铁律：禁自算复刻 ——
      自己维护一个 `_installed = True` 标记只能在"有人忘了改"时假绿）。
    """
    assert INSTALLED_TIMING_LISTENERS, (
        "core/database.py 没有安装任何 DB 计时监听器 ⇒ X-DB-Time-Ms 恒为 0"
    )
    matched = [
        (before, after)
        for target, before, after in INSTALLED_TIMING_LISTENERS
        if target is engine.sync_engine
    ]
    assert matched, "登记表里没有模块级引擎 ⇒ 生产路径上的 SQL 不会被计时"
    before, after = matched[-1]
    assert event.contains(engine.sync_engine, "before_cursor_execute", before)
    assert event.contains(engine.sync_engine, "after_cursor_execute", after)


def test_db_timing_counts_real_sql_on_a_real_engine():
    """在**真** SQLite 引擎上跑**真** SQL，断言 `db_ms` 被真的累加。

    这条把「装了个摆设」与「真的计时」分开：只断言 `event.contains` 的话，
    回调体写错（比如忘了 add_db_ms）也照样绿。
    """
    probe_engine = create_engine("sqlite:///:memory:")
    registry_before = len(INSTALLED_TIMING_LISTENERS)
    try:
        install_db_timing(probe_engine)
        assert len(INSTALLED_TIMING_LISTENERS) == registry_before + 1, (
            "install_db_timing 没有登记新引擎（幂等守卫判断错了？）"
        )
        t = start_timing()
        try:
            with probe_engine.begin() as conn:
                conn.execute(text("select 1"))
            assert t.db_ms > 0, "真 SQL 跑过了 db_ms 仍是 0 ⇒ 事件回调没接上"
        finally:
            clear_timing()
    finally:
        # 收尾：本用例只为验证机制，不该在全局登记表里留下临时引擎
        del INSTALLED_TIMING_LISTENERS[registry_before:]
        probe_engine.dispose()


def test_install_db_timing_is_idempotent_per_engine():
    """同一引擎重复安装 ⇒ 不重复登记（否则每次调用都多一份回调，耗时被算两遍）。"""
    probe_engine = create_engine("sqlite:///:memory:")
    registry_before = len(INSTALLED_TIMING_LISTENERS)
    try:
        install_db_timing(probe_engine)
        install_db_timing(probe_engine)
        assert len(INSTALLED_TIMING_LISTENERS) == registry_before + 1, (
            "同一引擎被登记了两次 ⇒ SQL 耗时会重复累加"
        )
    finally:
        del INSTALLED_TIMING_LISTENERS[registry_before:]
        probe_engine.dispose()

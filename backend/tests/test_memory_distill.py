# -*- coding: utf-8 -*-
"""长期记忆「每晚自动整理」的门禁（第 151 轮，批 C2-4）。

★ 本文件钉的是什么
r141 §2.4 判 `MemoryEvolution.vue` 是**假页面**，依据不是「没有表」，而是
**界面上承诺了「每晚自动整理更新」，而后端零实现**。C2-4 补上了机制 / 三张表 /
服务层 / HTTP 面 / **调度器**。而「调度器」这件事有个特殊性质：

    它坏了**不报错**。

    · 任务名两处写法不一致（`core/redis.py` 是字面量）⇒ beat 往一个没人注册的
      名字投递 ⇒ 现象是「整晚没跑」，日志干净、指标全零；
    · `asyncio.run` 复用应用级连接池 ⇒ **第一次任务成功**，第二次才抛
      `attached to a different loop` ⇒ 单任务验证会全绿放行；
    · 另建一个任务模块顺手连 `task_success` 信号 ⇒ 每个任务被计两次，指标翻倍；
    · 候选非空却一个都没投出去（Broker 不可达）⇒ 报「调度完成、投递 0 个」。

所以这里钉的不是「函数能跑」，而是**它们不会安静地坏掉**。这四条里有三条是
形态判据（AST / 真实 dependant 树），因为「跑一次看看」恰好是抓不到它们的方式。

★ 为什么这些判据要进 pytest，而不只留在探针
探针在 `.workbuddy/probes/`（被 .gitignore，CI 上不存在），是一次性的。
而上面每一坑都属于「下一个人改一行就会重新踩」的类型 —— 尤其那个字面量任务名。
探针负责**端到端真跑**（真库 / 真闸门 / 真落库），本文件负责**长期守着形态**。
两者不是重复：探针抓「实现错了」，本文件抓「下轮改回去了」。

★ 反向注入
每条断言都在 docstring 里写明「怎么改会变红」，并已逐条实测。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
TASKS_PY = BACKEND / "modules" / "memory" / "tasks.py"
CONV_SERVICE_PY = BACKEND / "modules" / "conversation" / "service.py"
COMPOSE = REPO / "docker-compose.yml"
BEAT_ENTRY = BACKEND / "beat.py"

#: 记忆路由的端点（方法, 路径）。★ 只列**已存在**的，多列一个会让门禁自己变红。
MEMORY_CRUD = (
    ("/api/v1/memory", "GET"),
    ("/api/v1/memory", "PUT"),
    ("/api/v1/memory/profile", "PUT"),
    ("/api/v1/memory/reset", "POST"),
    ("/api/v1/memory/logs", "GET"),
)
MEMORY_DISTILL = ("/api/v1/memory/distill", "POST")
MEMORY_ROUTER_PY = BACKEND / "modules" / "memory" / "router.py"

#: 本模块唯一的 fail-closed 身份门：(函数名, `__module__`)。
#: ★ 这个名字有**三个消费者**，改名必须同时改，否则静默失真：
#:     1. `modules/memory/router.py`（定义处 —— 它**必须**是真 `async def`）；
#:     2. 本文件的依赖树断言 + `_assert_identity_gate`（判定处）；
#:     3. `scripts/auth_coverage_report.py` 的 `AUTH_DEPENDENCY_NAMES`（体检处）。
#:   第 153 轮实测过漏改的第 3 处的后果：写成 `partial(...)` 时它**没有 __name__**，
#:   体检报告把本模块报成「memory 6 端点 / 已鉴权 0 / 0% <-- 无鉴权」，
#:   与事实**完全相反**（它本是 fail-closed 的）。
MEMORY_GATE_NAME = "_REQUIRE_USER"
MEMORY_GATE_MODULE = "modules.memory.router"


# ============================================================ 工具
def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _as_set(v) -> set:
    """celery 的 crontab 把 hour/minute 存成 **set**（实测 `{3}`），不是标量。"""
    if v is None:
        return set()
    if isinstance(v, (set, frozenset, list, tuple)):
        return set(v)
    return {v}


def _route_of(app, path: str, method: str):
    """真实路由对象（路径 + 方法都要对上）。"""
    for r in app.routes:
        if getattr(r, "path", "") == path and method in (getattr(r, "methods", ()) or ()):
            return r
    return None


def _walk_deps(dependant):
    """dependant 子树深度不限地逐个 yield。"""
    stack = [dependant]
    while stack:
        d = stack.pop()
        yield d
        stack.extend(getattr(d, "dependencies", []) or [])


def _dep_calls(app, path: str, method: str) -> list:
    """真实 dependant 树里所有依赖的 **call 对象**（不是名字）。

    ★★★ 判定一律走 call 对象，**不走名字** —— 第 153 轮实测事故。
    「名字里含 `require_authenticated_user`」这条判据在两个方向上
    **都**不可靠，而且两个方向都**真的发生过**：

      · 依赖被 `functools.partial` 包住时没有 `__name__`，而
        `str(partial)` **恰好含** `require_authenticated_user`
        ⇒ 断言**恒真**：判得出「挂没挂」，判不出「挂上去能不能用」。
        实测后果：FastAPI 不 await 它 ⇒ 注入**协程对象** ⇒ 6 个端点 100% 500。
      · 把 wrapper 起名 `_REQUIRE_USER` 之后，`str()` 里不再含那个子串
        ⇒ **同一条断言恒假**：红得毫无道理，且会诱使人把断言删掉。

    结论：**名字只配出现在报错信息里，不配当判据。**
    """
    target = _route_of(app, path, method)
    if target is None:
        return []
    return [d.call for d in _walk_deps(target.dependant) if d.call is not None]


def _dep_names(calls) -> list:
    """依赖的可读名 —— **只用于报错信息**。"""
    return [getattr(c, "__name__", str(c)) for c in calls]


def _has_dep(calls, name: str) -> bool:
    """依赖里是否有 `__name__` **精确等于** `name` 的那个（**不是子串**）。

    子串匹配会让 `check_api_quota` 这类反向断言（「CRUD 上不许有配额」）
    被一个恰含该串的无关依赖**打穿** ⇒ 恒真 = 死门禁。
    """
    return any(getattr(c, "__name__", None) == name for c in calls)


def _fastapi_awaitable(call) -> bool:
    """FastAPI 自己会不会 await 它 —— 这是「能不能用」的**唯一真源**。

    注意它**不是** `asyncio.iscoroutinefunction`：后者是直觉会信的那个，
    但 FastAPI 从没问过它（它问的是 `fastapi/dependencies/utils.py`
    里那个三分支版本）。两者分歧处就是事故。
    """
    from fastapi.dependencies.utils import is_coroutine_callable

    return bool(is_coroutine_callable(call))


def _assert_identity_gate(calls, label: str) -> None:
    """★★★ 断言这组依赖里挂着**本模块那个** fail-closed 身份门，且真能 await。

    三重判据缺一不可：

      1. **在场**：依赖里必须有一个 `__name__ == MEMORY_GATE_NAME` 的 call。
         用**精确**匹配 —— 子串会在「被 partial 包住」与「改过名」
         两头给出相反的假结论（第 153 轮两个方向都实测过）。
      2. **形态**：它必须是**真能 await** 的 async callable ——
         `asyncio.iscoroutinefunction` 与 FastAPI 自己的 `is_coroutine_callable` **都**为真。
         `partial(async_fn, ...)` 让前者 True、后者 False ⇒ 不 await ⇒ 500。
      3. **来源**：`__module__` 必须在本模块。
         全应用可能有同形态的 wrapper（`core/auth/accounts_router.py`
         的 `_current_user` 就是），只按名字找会**认错人** —— 挂的是别人的门，照样过。

    ★ 为什么不能只查子依赖里有没有 `require_authenticated_user`：
      上面那个 wrapper 把判定写在**函数体内**，不是用 `Depends(...)` 挂上去的
      —— 所以它**不会**出现在 dependant 树里。它的真实性由
      `test_identity_gate_is_a_real_async_wrapper_not_a_partial`（AST）钉住。
      两条合起来才是完整的：「端点挂了它」+ 「它是真的」。
    """
    names = _dep_names(calls)
    ctx = "%s 依赖=%s" % (label, names)

    named = [c for c in calls if getattr(c, "__name__", None) == MEMORY_GATE_NAME]
    assert named, (
        "%s 没有声明 fail-closed 身份门（%s）—— 长期记忆按**人**归属，"
        "匿名会话没有可归属的对象，必须 fail-closed。%s"
        "（★ 注意不能改挂路由级 BUSINESS_AUTH：它是 optional-auth，"
        "允许匿名取到 None。）" % (label, MEMORY_GATE_NAME, ctx)
    )
    gate = named[0]

    assert asyncio.iscoroutinefunction(gate) and _fastapi_awaitable(gate), (
        "%s 的身份门**形态错误**："
        "`asyncio.iscoroutinefunction=%s` 而 FastAPI 的 `is_coroutine_callable=%s`。"
        " 两者不一致 ⇒ FastAPI **不会 await** 它，把协程对象当身份注入 handler"
        " ⇒ 端点 500（不是 401，所以看起来像“数据库挂了”）。"
        " 常见成因：`functools.partial(async_fn, ...)`。%s"
        % (label, asyncio.iscoroutinefunction(gate), _fastapi_awaitable(gate), ctx)
    )
    assert getattr(gate, "__module__", "") == MEMORY_GATE_MODULE, (
        "%s 挂的身份门来自 `%s`，不是本模块的 `%s`"
        "—— 同名不同源，挂的是别人的门。%s"
        % (label, getattr(gate, "__module__", "?"), MEMORY_GATE_MODULE, ctx)
    )


def _leaked_owner_params(app, path: str, method: str) -> list:
    """端点（含全部子依赖）上任何位置叫 owner_id 的入参。"""
    target = _route_of(app, path, method)
    if target is None:
        return []
    leaked: list = []
    for d in _walk_deps(target.dependant):
        for group in (d.query_params, d.body_params, d.header_params,
                      d.path_params, d.cookie_params):
            leaked.extend(p.name for p in group if p.name == "owner_id")
    return leaked


# ============================================================ 调度器
def test_beat_task_name_is_registered():
    """★★★ 调度器投递的名字，必须在 worker 侧真的注册过。

    `core/redis.py` 里那个任务是**字面量** —— 这是刻意的：`core` 不得 import
    `modules`（见 `test_core_layering.py`）。于是它与
    `tasks.TASK_DISTILL_ALL` 构成「同一事实两份写法」。

    不一致时的现象是**整晚没跑**：beat 照常投递、worker 照常运行、
    没有任何异常 —— 只有一个没人认识的队列消息，而队列不会因为
    "没人消费"报错。指标里 `CELERY_TASK_RESULTS` 连一行都不会多。

    ★ 同一个坑还有第二个入口：`autodiscover_tasks([...])` 的列表漏了
      `modules.memory` 时，任务定义在、beat 在投、**worker 根本没注册**，
      症状与上面一模一样。所以两条都要断言。

    反向注入已验：core 的字面量改成 "memory.distill_all" ⇒ 第一段变红；
    autodiscover 列表去掉 "modules.memory" ⇒ 第二段变红。
    """
    from core.redis import celery_app
    from modules.memory import tasks as T

    celery_app.finalize()
    entry = (celery_app.conf.beat_schedule or {}).get("memory-nightly-distill")
    assert entry is not None, (
        "beat_schedule 里没有 memory-nightly-distill —— 「每晚自动整理」退回零实现，"
        "正是 r141 判 MemoryEvolution.vue 是假页面的那条依据"
    )
    assert entry.get("task") == T.TASK_DISTILL_ALL, (
        "两处任务名不一致：调度投递 %r，而 tasks.py 注册的是 %r —— "
        "现象是「整晚没跑」，不报错" % (entry.get("task"), T.TASK_DISTILL_ALL)
    )
    assert entry["task"] in celery_app.tasks, (
        "%r 没有被 autodiscover 注册 —— 检查 core/redis.py 的 "
        "autodiscover_tasks 是否漏了 modules.memory" % entry["task"]
    )
    assert T.TASK_DISTILL_OWNER in celery_app.tasks, (
        "fan-out 的落点任务没被注册 ⇒ 每晚投递出去的任务全都无人消费"
    )


def test_beat_schedule_is_crontab_pinned_to_limits():
    """★★ 调度用 crontab（不是 timedelta），且小时/分钟取自 `limits`。

    ★ 为什么必须是 crontab：crontab 每次按**当前时间**重算下次触发点，
      不依赖调度文件里的 `last_run_at`。用 `timedelta` 时，schedule 文件一旦
      丢失（容器重建、卷没挂上、路径不可写），就再也算不出「该什么时候跑」
      ⇒ 漏掉一整天，而日志里只有一句「等待下一次运行」。

    ★ 为什么小时数不能手写在这个文件里：它同时被三处消费 ——
      `claim_distill_run` 的冷却窗口、`DISTILL_LOOKBACK_HOURS` 的回溯窗口、
      以及这里的调度时刻。写死后只改一处时，三者关系被破坏，
      症状是「有时两天才整理一次」，且不报错。

    反向注入已验：把 crontab 换成 timedelta(hours=24) ⇒ 第一段变红；
    把 hour 写死成 4 ⇒ 第二段变红。
    """
    from celery.schedules import crontab

    from ai_infra.memory import limits as L
    from core.redis import celery_app

    celery_app.finalize()
    sch = celery_app.conf.beat_schedule["memory-nightly-distill"]["schedule"]
    assert isinstance(sch, crontab), (
        "调度不是 crontab 而是 %s —— schedule 文件丢失后会漏掉一整天"
        % type(sch).__name__
    )
    assert _as_set(sch.hour) == {L.DISTILL_HOUR}, (
        "调度小时 %r 与 limits.DISTILL_HOUR=%r 不一致（两份写法）"
        % (_as_set(sch.hour), L.DISTILL_HOUR)
    )
    assert _as_set(sch.minute) == {L.DISTILL_MINUTE}, (
        "调度分钟 %r 与 limits.DISTILL_MINUTE=%r 不一致"
        % (_as_set(sch.minute), L.DISTILL_MINUTE)
    )


def test_rhythm_invariants_hold():
    """★★★ 三条节奏常量关系必须同时成立：

        COOLDOWN_HOURS  <  PERIOD_HOURS  <  LOOKBACK_HOURS

    · 冷却必须**严格小于**周期：两者相等时，beat 的触发抖动会让「距上次多久」
      恰好落在边界上 ⇒ 随机二选一 ⇒ 用户看到的是「有时两天才整理一次」，
      而且换个时间跑又正常，无从复现。
    · 回溯窗口必须**大于**周期：否则两轮之间存在对话缺口，落在缺口里的对话
      永远不被整理 —— 它不报错，只是从此不在记忆里。

    ★ 这不是「测试实现」，而是「测试设计口径」：改任一常量都必须重新满足它。
      本文件因此不 import 具体数值，只断言关系（改数值不该让门禁变红）。

    反向注入已验：把 COOLDOWN 改成与 PERIOD 相等（24）⇒ 本条变红。
    """
    from ai_infra.memory import limits as L

    assert L.DISTILL_COOLDOWN_HOURS < L.DISTILL_PERIOD_HOURS, (
        "冷却(%s) 未严格小于周期(%s) —— beat 抖动会让边界随机二选一"
        % (L.DISTILL_COOLDOWN_HOURS, L.DISTILL_PERIOD_HOURS)
    )
    assert L.DISTILL_LOOKBACK_HOURS > L.DISTILL_PERIOD_HOURS, (
        "回溯窗口(%s) 未大于周期(%s) —— 两轮之间的对话会落进缺口，永远不被整理"
        % (L.DISTILL_LOOKBACK_HOURS, L.DISTILL_PERIOD_HOURS)
    )
    assert L.DISTILL_MANUAL_GAP_SECONDS > 0, "手动整理的最小间隔必须是正数（防连点）"
    assert L.DISTILL_BATCH_LIMIT > 0, "批次上限必须是正数（否则活跃用户一个都不处理）"
    assert 0 <= L.DISTILL_HOUR <= 23 and 0 <= L.DISTILL_MINUTE <= 59


def test_beat_entry_starts_beat_not_worker():
    """★ `beat.py` 必须以 `celery_app.start(argv=["beat", ...])` 启动。

    另一种写法 `celery_app.worker_main([...])` 会在 argv 里找**字面量** "worker"，
    传 "beat" 直接 `ValueError` —— 容器启动即退出，而 compose 的
    `restart: unless-stopped` 会让它反复重启，日志里是一句 Celery 内部的
    argv 报错：「入口写错了」这一点不直观。

    ★ 另外钉住 schedule 文件的落点：它必须能被 compose 持久化
      （`logs:/app/logs`）。落在临时目录也不算错（crontab 会按当前时间重算），
      但会让「下次几点跑」在每次重启后消失，运维看不出来。

    ★ 判据走 AST：`beat.py` 的注释里**提到了** `worker_main`（正是在解释为什么
      不用它），按源码字符串包含来判会假红 —— 本条第一次跑就是这么红的，
      与 `test_identity_endpoint_auth.py` 里那条同源。

    反向注入已验：把 `celery_app.start(argv=["beat", ...])` 换成
    `celery_app.worker_main(["beat", ...])` ⇒ 本条变红。
    """
    tree = _tree(BEAT_ENTRY)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

    bad = [
        n.lineno
        for n in calls
        if getattr(n.func, "attr", None) == "worker_main"
        or (isinstance(n.func, ast.Name) and n.func.id == "worker_main")
    ]
    assert not bad, (
        "beat.py 第 %s 行调用了 worker_main —— 它会在 argv 里找字面量 \"worker\"，"
        "传 \"beat\" 直接 ValueError（容器启动即退出，compose 反复重启）" % bad
    )

    argvs = []
    for n in calls:
        if getattr(n.func, "attr", None) != "start":
            continue
        for kw in n.keywords:
            if kw.arg == "argv" and isinstance(kw.value, (ast.List, ast.Tuple)):
                argvs.append([e.value for e in kw.value.elts if isinstance(e, ast.Constant)])
    assert argvs, "beat.py 没有 celery_app.start(argv=[...]) 调用"
    assert any(items and items[0] == "beat" for items in argvs), (
        "celery_app.start 的 argv 首项不是 \"beat\"：%s" % argvs
    )


# ============================================================ worker 侧形态
def test_tasks_use_persistent_loop_not_asyncio_run():
    """★★★ `tasks.py` 不得出现 `asyncio.run`（跨 event loop 的连接池陷阱）。

    Celery 是同步进程，任务体要桥到协程。但 `asyncio.run` **每次都新建并关闭**
    一个 loop，而 asyncpg 的连接绑定在创建它的那个 loop 上。既然长期记忆的
    全部 DB 访问都在 `modules/memory/service.py` / `modules/conversation/service.py`
    （走应用级 `get_async_session()`，即模块级 engine），第二次任务必挂：

        RuntimeError: Task got Future attached to a different loop

    ★ 最阴的地方：**第一次任务成功**。只跑一次的自测会全绿放行 ——
      这正是 `modules/aigc_media/tasks.py` 记下的实测结论。
    ⇒ 判据只能是形态（有没有 `asyncio.run`），不能是「跑一次看看」。
    ⇒ 替代实现是每线程一个**常驻** loop：`_thread_loop()` 建好不关，
      `threads` 池复用线程 ⇒ 同线程的后续任务复用同一 loop。

    反向注入已验：把 `_run_sync` 的实现换成 `asyncio.run(coro)` ⇒ 本条变红。
    """
    tree = _tree(TASKS_PY)
    bad = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "run"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "asyncio"
    ]
    assert not bad, (
        "tasks.py 第 %s 行用了 asyncio.run —— 每次新建并关闭 loop ⇒ "
        "第二次任务抛 'attached to a different loop'（而第一次会成功）" % bad
    )
    names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"_thread_loop", "_run_sync"} <= names, (
        "缺少每线程常驻 loop 的替代实现（_thread_loop / _run_sync）"
    )


def test_tasks_do_not_reuse_llm_singleton():
    """★★ 整理任务**每次新建并关闭** LLM 客户端，不用 `get_llm()` 单例。

    单例内部持一个 `httpx.AsyncClient`，而 AsyncClient 的连接同样绑定在
    「它第一次被使用的那个 loop / 线程」上。跨线程复用它行为未定义 ——
    而 worker 用的正是 `threads` 池，任务会落在不同线程上。

    ★ 判据走 AST（「有没有**调用**」），不是源码字符串包含：
      `tasks.py` 的 docstring 里就写着 `get_llm()` 这个名字（解释为什么不用它），
      按字符串判会**假红**。

    反向注入已验：把 `DashScopeLLM(...)` 换成 `get_llm()` ⇒ 本条变红。
    """
    tree = _tree(TASKS_PY)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    singleton = [
        n.lineno
        for n in calls
        if (isinstance(n.func, ast.Name) and n.func.id == "get_llm")
        or (isinstance(n.func, ast.Attribute) and n.func.attr == "get_llm")
    ]
    assert not singleton, "tasks.py 第 %s 行调用了 get_llm() 单例（跨线程复用 AsyncClient）" % singleton
    assert any(
        isinstance(n.func, ast.Name) and n.func.id == "DashScopeLLM" for n in calls
    ), "没找到「每次新建 LLM 客户端」的实现（DashScopeLLM(...)）"
    assert "await llm.close()" in TASKS_PY.read_text(encoding="utf-8"), (
        "LLM 客户端没有被关闭 ⇒ 每晚每人漏一个连接"
    )


def test_global_celery_signals_are_connected_at_most_once():
    """★★★ `task_success` / `task_failure` 是**全局**信号，全仓最多连一处。

    `modules/aigc_media/tasks.py` 已经连了这两个信号，且**没有 `sender=` 过滤**
    ⇒ 所有任务都从它走。新任务模块再连一次，每个任务就被**计两次**：
    指标翻倍、且没有任何报错。

    这个坑只在「第二个任务模块出现时」才暴露 —— 也就是本模块出现的时候。

    ★ 扫描面是 `modules/` + `core/`（**不含 `tests/`**）：本文件自己的 docstring
      就写着这两个装饰器名，扫进来会自己撞自己。

    反向注入已验：在 `modules/memory/tasks.py` 里加一个
    `@task_success.connect` 装饰的函数 ⇒ 本条变红。
    """
    hits: dict = {}
    for root_name in ("modules", "core"):
        base = BACKEND / root_name
        for py in sorted(base.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            if "@task_success.connect" in text or "@task_failure.connect" in text:
                hits[str(py.relative_to(BACKEND))] = True

    assert len(hits) <= 1, (
        "有 %d 个文件连了全局 celery 信号：%s —— 全局信号不按模块隔离，"
        "第二个连接会让每个任务被计两次" % (len(hits), sorted(hits))
    )
    assert "modules/memory/tasks.py" not in hits, (
        "memory/tasks.py 连了 task_success/task_failure —— 与 aigc_media 的全局连接"
        "叠加 ⇒ 每个任务计两次"
    )


# ============================================================ HTTP 面
def test_distill_endpoint_declares_quota_but_crud_does_not():
    """★★★ 配额只挂在 `POST /memory/distill` 上，CRUD 端点一个都不挂。

    两个方向都必须钉，而且**必须走真实 app 的 dependant 树**：

      · 正向：distill 是会调模型的端点 ⇒ 要计费。
      · 反向：CRUD 挂了配额 ⇒ 配额用完的用户**连自己的记忆都改不了**
        （他会看到一个「记忆」页面，但保存永远失败，且失败原因与记忆无关）。
      · 反向：全靠**子串**判断。鉴权/配额依赖常被 `functools.partial` 包一层，
        没有 `__name__`；精确匹配会让「distill 有配额」假红、
        让「CRUD 没有配额」**恒真**（= 一条永远绿的假门禁）。

    ★ 为什么不 grep 源码：「配置存在 ≠ 门禁生效」。挂载方式（路由级
      `dependencies=[...]` / 端点自己 `Depends(...)` / `main.py` 的条件挂载）
      有五种写法，其中两种历史上实测过是**根本没挂上**的。只有运行时
      dependant 树是那唯一真源。

    反向注入已验：给 `/api/v1/memory` 的 GET 加上 `Depends(check_api_quota)`
    ⇒ 反向断言变红；删掉 distill 上的 quota ⇒ 正向断言变红。
    """
    from main import app

    label = "%s %s" % (MEMORY_DISTILL[1], MEMORY_DISTILL[0])
    calls = _dep_calls(app, *MEMORY_DISTILL)
    assert calls, "没找到 %s" % label
    _assert_identity_gate(calls, label)
    assert _has_dep(calls, "check_api_quota"), (
        "distill 端点没有声明配额 —— 它会真的调一次模型，必须计费。"
        " 依赖=%s" % _dep_names(calls)
    )

    for path, method in MEMORY_CRUD:
        label = "%s %s" % (method, path)
        calls = _dep_calls(app, path, method)
        assert calls, "没找到 %s 路由" % label
        _assert_identity_gate(calls, label)
        assert not _has_dep(calls, "check_api_quota"), (
            "%s 挂了配额 —— 配额用完的用户会连自己的记忆都读不了/改不了。"
            " 依赖=%s" % (label, _dep_names(calls))
        )


def test_memory_endpoints_take_owner_only_from_identity():
    """★★★ 记忆端点**不接受**客户端的 `owner_id` 参数。

    归属只能由服务端从登录态注入。若某个端点允许从 request 里带 `owner_id`
    （query / body / header / path / cookie 任一种），传别人的 id 就能读写别人的记忆 ——
    而 pydantic 默认会**忽略**多余字段，所以「照发不报错」不等于「字段没被采纳」。

    ★ 必须扫全部五种入参通道：只看 body 会漏掉 `?owner_id=` 这种最省事的越权。
      （榜单上 `X-Shop-ID` 那一条就是同类：同名 header 两套 ID 空间。）

    反向注入已验：给 distill 端点加一个 `owner_id: str = Query("")` ⇒ 本条变红。
    """
    from main import app

    for path, method in (MEMORY_DISTILL,) + MEMORY_CRUD:
        leaked = _leaked_owner_params(app, path, method)
        assert not leaked, (
            "%s %s 存在 owner_id 入参 %s —— 归属只能来自登录态，"
            "从请求里取 = 可读别人的记忆" % (method, path, leaked)
        )


# ============================================================ 扇出与守卫
async def test_dispatch_fanout_and_silent_failure_guard(monkeypatch):
    """★★★ beat → `distill_all_owners` → `_dispatch_all`：最容易「静默成功」的一段。

    两种必须分开的形态：

      · **投递数 ≠ 成功数**。返回 `dispatched` 而不是「成功数」，是因为
        「队列里堆了 100 个任务没人消费」与「100 个人都整理完了」必须可区分 ——
        合成一个数字后两者一模一样。
      · **候选非空、却一个都没投出去 ⇒ 必须显式失败**。
        报「调度完成、投递 0 个」是最糟的形态：调度器看起来正常、时间线一条
        记录都没有、而真实原因是 Broker 不可达。

    ★ 为什么 fan-out 而不是一个任务里 for 循环所有人：`task_time_limit` 下
      整批会被硬杀在超时上，而被杀掉的是**整批** —— 前面整理好的白做，
      后面一个都没轮到。

    ★ 本测试不需要真库：`active_owner_ids` 换成桩，因为这里要钉的是**分支**。
      「真库 + 真闸门 + 真落库」由探针 C 段覆盖。

    反向注入已验：删掉 `if owners and not dispatched: raise` ⇒ 第二段变红；
    把 `dispatched.append(oid)` 改成只在成功时计数 ⇒ 第一段变红。
    """
    from modules.memory import tasks as T

    seen: list = []

    class _FanOut:
        def delay(self, oid):
            seen.append(oid)

    class _Dead:
        def delay(self, oid):
            raise RuntimeError("probe: broker unreachable")

    async def _owners(*, since=None, limit=0):
        return ["u-a", "u-b"]

    monkeypatch.setattr(T, "active_owner_ids", _owners)

    monkeypatch.setattr(T, "distill_owner", _FanOut())
    out = await T._dispatch_all(None)
    assert seen == ["u-a", "u-b"], "fan-out 没覆盖到每个活跃用户：%s" % seen
    assert out["owners"] == 2 and out["dispatched"] == 2, "计数口径不对：%s" % out
    assert out["dispatch_failed"] == 0

    monkeypatch.setattr(T, "distill_owner", _Dead())
    with pytest.raises(RuntimeError):
        await T._dispatch_all(None)


def test_active_owner_ids_judgement_field_is_refreshed_by_real_writes():
    """★★★ `active_owner_ids` 的判据字段（`conversations.updated_at`）
    必须仍被真实写入路径刷新。

    夜间整理的读口按 `conversations.updated_at` 挑人。这个字段一旦不再被
    `append_message` 刷新，读口返回的就是陈旧结果 —— 症状是
    **夜间整理静默漏掉今天说过话的人**：不报错、指标全绿（只是
    `status="no_messages"` 变多，而那本身就表示「跑了、没事」，看起来正常）。

    ★ 判据必须走 AST（有没有对 `ConversationRecord` 的 `.values(updated_at=...)`
      更新），不能靠 `updated_at in src` 这种字符串包含：那个字段在注释、
      docstring、读口里都出现过，字符串判据会被文字骗过。

    反向注入已验：删掉 `append_message` 里那段 `update(ConversationRecord)
    .values(updated_at=datetime.utcnow())` ⇒ 本条变红。
    """
    tree = _tree(CONV_SERVICE_PY)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "append_message"
        ),
        None,
    )
    assert fn is not None, "conversation/service.py 里没有 append_message"

    refresh = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "values"
        and any(k.arg == "updated_at" for k in n.keywords)
        and "ConversationRecord" in ast.dump(n)
    ]
    assert refresh, (
        "append_message 不再刷新 conversations.updated_at —— "
        "active_owner_ids（夜间整理的读口）会返回陈旧结果，静默漏掉最近说过话的人"
    )


# ============================================================ 部署形态
def test_beat_runs_as_its_own_service_not_embedded_in_worker():
    """★★ beat 必须是**独立**进程，不由 worker 内嵌（`-B`）。

    两条具体理由，都不是风格问题：

      · 本项目的 worker 用 `--pool=threads`，且与 `/metrics` **共进程**
        （指标注册表是进程内的，prefork 下计数会落进子进程、`/metrics` 永远 0）。
        把调度器塞进去，它每次唤醒都要抢 GIL，而同一进程里正跑着 LLM 任务。
      · 调度器需要**独占**一个 schedule 文件（记录 `last_run_at`）。
        与任务执行共进程时会互抢，报 `PermissionError` 或**静默不触发** ——
        现象是「整晚没跑」，是最难排查的一类。

    ★ 还有一条只能靠"单副本"表达的约束：两个 beat 会各触发一次，
      同一晚的整理被投递两遍。冷却窗口是第二道保险，但部署上从一开始就只跑一个。

    ★ 文件缺失时 skip 而不是 fail：compose 在**仓库根**，而 backend 镜像的
      构建上下文是 `./backend` ⇒ 在镜像内跑测试时它不在。这是「不需要 =
      显式跳过」，不是「漏配 = 起不来」。

    反向注入已验：把 beat 服务从 compose 删掉、给 worker 的 command 加 `-B`
    ⇒ 本条变红。
    """
    if not COMPOSE.is_file():
        pytest.skip("仓库根的 docker-compose.yml 不在本环境（backend 镜像内跑测试时如此）")

    raw = COMPOSE.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = raw.split("\n")

    def _service_block(name: str) -> list:
        """取某个顶层服务（2 空格缩进的 key）到下一个顶层 key 之间的**非注释**行。

        ★ 必须跳过注释行、且注释不结束当前块：worker 与 beat 之间那段
          解释「为什么不加 -B」的注释就在两者中间 —— 把它算进 worker 块，
          断言会被一句**说明性文字**触发（正是本项目「注释承诺型假门禁」的镜像：
          这次是注释让真门禁假红）。
        """
        out: list = []
        inside = False
        for ln in lines:
            if not ln.strip():
                continue
            if ln.strip().startswith("#"):
                continue
            if not ln.startswith(" "):
                inside = False           # 顶层 key（services: / volumes: …）⇒ 结束
            elif not ln.startswith("   ") and ln.rstrip().endswith(":"):
                inside = ln.strip() == name + ":"
            if inside:
                out.append(ln)
        return out

    beat = _service_block("beat")
    worker = _service_block("worker")

    assert beat, "docker-compose.yml 里没有 beat 服务 —— 「每晚自动整理」没有进程去调度"
    assert any("beat.py" in ln for ln in beat), (
        "beat 服务没有跑 beat.py（command 应形如 [\"python\", \"beat.py\"]）"
    )
    assert any("-B" in ln for ln in worker) is False, (
        "worker 的 command 里出现了 -B（内嵌调度器）—— 会抢 GIL 且与任务执行互抢 "
        "schedule 文件，表现为静默不触发"
    )
    assert any("/app/logs" in ln for ln in beat), (
        "beat 没有挂载 logs 卷 —— schedule 文件会随容器重建消失"
    )


# ============================================================ 提示词分层（第 151 轮）
#: 机制层目录（不得持有提示词）。★ 用**目录**而不是列文件：新增文件自动受管。
AI_INFRA_MEMORY = BACKEND / "ai_infra" / "memory"
#: 提示词真源（业务层）。第 151 轮从 `ai_infra/memory/distill.py` 搬来。
MEMORY_PROMPTS = BACKEND / "modules" / "memory" / "prompts.py"


def test_llm_prompt_lives_in_business_layer_not_mechanism():
    """★★★ 抽取提示词的**唯一真源**在业务层；机制层只收一个**必填**参数。

    ★ 为什么这条要单独钉（`test_infra_layering` 已经在扫业务词了）：
      那道门禁管的是「字符串里有没有业务词」，本门禁管的是**分层归属**。
      两者能各自被绕过：
        · 只扫业务词 ⇒ 机制层放一个**中性**默认提示词能过（例如
          「把用户的事实整理成 JSON」）⇒ 于是「通用版」与「业务版」两份写法
          开始漂移；漂移的表现是「换了个产品，整理出来的记忆开始不像这个产品
          该记的东西」，不报错；
        · 只钉分层 ⇒ 提示词搬回机制层、而扫词那条被顺手放宽时没人拦。
      ⇒ 两条都要。

    ★ 为什么「必填」也是判据：给 `instructions` 一个默认值，等于机制层
      **也**有一份提示词。而「忘了传」的后果会从 `TypeError`（跑之前就炸）
      退化成「悄悄用了一个更差的提示词」。

    ★ 判据只认**代码级引用**（Name / Assign 目标 / import alias），不数串：
      本仓栽过四次「docstring 或注释里提了那个名字，把断言骗过去」。反过来，
      在这里扫字符串还会造成**假红** —— 一段解释分层理由的 docstring 里
      逐字提到这个名字，就被判违规。

    反向注入已验：① 在 `ai_infra/memory/distill.py` 里写
    `EXTRACT_INSTRUCTIONS = "把用户事实整理成 JSON"`；
    ② 给 `build_extract_prompt` 的 `instructions` 加 `= ""`；
    ③ 在 `ai_infra/memory/__init__.py` 里重新 re-export ⇒ 三种都变红。
    """
    # (a) 机制层不得出现这个**名字**（哪怕内容是中性的）
    offenders = []
    for p in sorted(AI_INFRA_MEMORY.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id == "EXTRACT_INSTRUCTIONS":
                offenders.append("%s:%d NAME" % (p.relative_to(BACKEND), n.lineno))
            elif isinstance(n, ast.alias) and n.name == "EXTRACT_INSTRUCTIONS":
                offenders.append("%s:%d IMPORT" % (p.relative_to(BACKEND), n.lineno))
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == "EXTRACT_INSTRUCTIONS":
                        offenders.append("%s:%d ASSIGN" % (p.relative_to(BACKEND), n.lineno))
    assert not offenders, (
        "抽取提示词的真源出现在机制层: %s —— 提示词就是业务语义本身"
        "（它决定「什么值得记住」、拿什么当例子），应住 modules/memory/prompts.py；"
        "机制层不得再有第二个真源" % offenders
    )

    # (b) 真源确实在业务层
    assert MEMORY_PROMPTS.is_file(), (
        "modules/memory/prompts.py 不存在：提示词没有落点（机制层又被掏空就没人管了）"
    )
    assert "EXTRACT_INSTRUCTIONS" in MEMORY_PROMPTS.read_text(encoding="utf-8"), (
        "modules/memory/prompts.py 里没有 EXTRACT_INSTRUCTIONS"
    )

    # (c) 机制层两个入口都**必填** instructions
    tree = _tree(AI_INFRA_MEMORY / "distill.py")
    checked = []
    for n in tree.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if n.name not in ("build_extract_prompt", "extract_candidates"):
            continue
        checked.append(n.name)
        pos = n.args.posonlyargs + n.args.args
        pos_names = [a.arg for a in pos]
        if "instructions" in pos_names:
            # 位置参数：默认值从右往左对齐 ⇒ 有默认值当且仅当
            #   len(defaults) >= len(pos) - idx
            idx = pos_names.index("instructions")
            no_default = len(n.args.defaults) < len(pos) - idx
        else:
            kw_names = [a.arg for a in n.args.kwonlyargs]
            assert "instructions" in kw_names, (
                "%s 没有 instructions 参数 —— 提示词从哪来？" % n.name
            )
            no_default = n.args.kw_defaults[kw_names.index("instructions")] is None
        assert no_default, (
            "%s.instructions 带了默认值 —— 等于机制层也有一份提示词；"
            "「忘了传」会从 TypeError（跑之前就炸）退化成"
            "「悄悄用了个更差的提示词」（不报错）" % n.name
        )
    assert sorted(checked) == ["build_extract_prompt", "extract_candidates"], (
        "预期两个入口都收 instructions，实际匹配到 %s" % checked
    )


def test_distill_task_passes_the_business_prompt():
    """★★ 夜间任务必须把**业务层那份**提示词显式传进去。

    ★ 为什么这不是「实现细节」：`instructions` 是必填的，所以忘传会 `TypeError`；
      但抽取那一步被 `except Exception` 兜住 ⇒ 它会变成一条 `distill_failed`
      记录。也就是说**接线断了的表现是「每晚整理都失败」**，而不是启动即崩：
      界面上看到「整理失败」，要定位到「少传了一个参数」得翻日志。

    ★ 判据走 AST 取**关键字实参**，不数串（同上：本仓已四次被 docstring 骗过）。

    反向注入已验：把 `instructions=EXTRACT_INSTRUCTIONS` 改成
    `instructions="整理一下"` ⇒ 本条变红。
    """
    tree = _tree(TASKS_PY)
    passed = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "extract_candidates":
            for kw in n.keywords:
                if kw.arg == "instructions":
                    passed.append(kw.value)
    assert passed, (
        "tasks.py 没有给 extract_candidates 传 instructions —— 抽取拿不到业务提示词"
    )
    for v in passed:
        assert isinstance(v, ast.Name) and v.id == "EXTRACT_INSTRUCTIONS", (
            "tasks.py 传的不是业务层那份提示词（实参 AST = %s）" % ast.dump(v)[:90]
        )
    froms = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.module
        and n.module.split(".")[-1] == "prompts"
        and any(a.name == "EXTRACT_INSTRUCTIONS" for a in n.names)
    ]
    assert froms, (
        "tasks.py 没有 `from ...prompts import EXTRACT_INSTRUCTIONS` —— "
        "提示词必须来自业务层那唯一真源，不许就地再写一份"
    )


# ============================================================ 身份门的**实现形态**
def test_identity_gate_is_a_real_async_wrapper_not_a_partial():
    """★★★ `_REQUIRE_USER` 必须是「真 `async def` + 真的转交唯一实现」。

    第 153 轮的墓碑。它曾写成：

        _REQUIRE_USER = functools.partial(require_authenticated_user, what="长期记忆")

    于是 FastAPI 的两个判定当场分歧（同一对象、同一进程、实测）：

        asyncio.iscoroutinefunction(partial)  → True     ← 直觉会信的那个
        is_coroutine_callable(partial)        → False    ← FastAPI 真正问的那个

    FastAPI 只问后者 ⇒ **不 await** ⇒ 把**协程对象**当身份注入 handler
    ⇒ `current_user.id` 报 `AttributeError: 'coroutine' object has no attribute 'id'`
    ⇒ 本模块 6 个端点 **100% 500**（不是 401 —— 所以它看起来像“数据库挂了”）。

    ★ 为什么这条判据必须存在，而不只靠依赖树断言
      依赖树断言问「端点挂的那个东西**在不在**」，
      本断言问「那个东西**是不是真的**」。
      两者问的不是一件事：恰好是 `partial` 让前者为真、后者为假。
      而「源码字符串包含 require_authenticated_user」这种写法**不算判据**
      —— docstring 里写一遍就会骗过它（本仓铁律：形态判据一律走 AST）。

    反向注入已验：把它改回 `functools.partial(...)` ⇒ 本条 + 依赖树断言
    + `test_route_dependency_form.py` 三处同时变红。
    """
    tree = _tree(MEMORY_ROUTER_PY)

    # ① 模块级不得把 `_REQUIRE_USER` 赋成表达式（partial / lambda / 别的包装）。
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == MEMORY_GATE_NAME:
                    raise AssertionError(
                        "%s 被赋成了表达式（%s）—— 必须是 `async def`。"
                        " `functools.partial(async_fn, ...)` 会让 FastAPI 的"
                        " is_coroutine_callable 判 False ⇒ 不 await ⇒ 端点 500"
                        % (MEMORY_GATE_NAME, ast.unparse(node.value)[:80])
                    )

    fn = None
    for node in tree.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == MEMORY_GATE_NAME):
            fn = node
            break
    assert fn is not None, (
        "`modules/memory/router.py` 里找不到 `%s` —— 身份门改名了吗？"
        " 改名要同时改三处（定义处 / 本文件的 MEMORY_GATE_NAME /"
        " `scripts/auth_coverage_report.py` 的白名单）" % MEMORY_GATE_NAME
    )
    assert isinstance(fn, ast.AsyncFunctionDef), (
        "`%s` 不是 `async def` —— FastAPI 判「要不要 await」走的是它自己的"
        " is_coroutine_callable，只认真 async 函数/协程方法" % MEMORY_GATE_NAME
    )

    # ② 参数：`request`（裸 Request —— 写 Union 会让整个应用起不来）+ `db`。
    args = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
    assert "request" in args, "`%s` 没有 request 入参 —— 拿不到凭据" % MEMORY_GATE_NAME
    assert "db" in args, "`%s` 没有 db 入参 —— 查不了库" % MEMORY_GATE_NAME

    # ③ 体内必须真的 `await require_authenticated_user(request, db, what=...)`：
    #    判定逻辑只能有一份真源，wrapper 只负责转交。
    forwarded = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value
            if ast.unparse(call.func) == "require_authenticated_user":
                forwarded.append(call)
    assert forwarded, (
        "`%s` 体内没有 `await require_authenticated_user(...)` ——"
        " 它没有转交唯一实现（自己写一份判定 = 第二份实现，必有一份测不到）"
        % MEMORY_GATE_NAME
    )
    assert any(len(c.args) == 2 and any(k.arg == "what" for k in c.keywords)
               for c in forwarded), (
        "`%s` 调 `require_authenticated_user` 的姿势变了：应当把 (request, db) 原样转交、"
        " 并用 `what=` 给出主语（只影响 401 文案）" % MEMORY_GATE_NAME
    )

    # ④ 体内不得出现 `partial`（哪怕不用在依赖上，出现即说明有人在往回走）。
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == "partial":
            raise AssertionError(
                "`%s` 体内出现了 `partial` —— 这正是第 153 轮事故的形态"
                % MEMORY_GATE_NAME
            )

    # ⑤ 每个端点都必须**自己** `Depends(_REQUIRE_USER)`：路由级依赖不向
    #    handler 注入参数，只挂路由级的话 handler 拿不到 current_user。
    uses = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "Depends":
            if node.args and ast.unparse(node.args[0]) == MEMORY_GATE_NAME:
                uses += 1
    expect = len(MEMORY_CRUD) + 1  # 5 个 CRUD + distill
    assert uses == expect, (
        "`Depends(%s)` 出现 %d 次，应为 %d 次（%d 个 CRUD + distill）"
        % (MEMORY_GATE_NAME, uses, expect, len(MEMORY_CRUD))
    )

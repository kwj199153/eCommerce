# -*- coding: utf-8 -*-
"""全应用「路由依赖形态」门禁（第 153 轮）。

★ 本文件钉的是什么
    任何路由的 dependant 树里，**不得**出现「asyncio 认为是协程函数、
    而 FastAPI 不会 await」的依赖。

★ 为什么需要它（真实事故，不是假想）
    `modules/memory/router.py` 曾把 fail-closed 身份门写成

        _REQUIRE_USER = functools.partial(require_authenticated_user, what="长期记忆")

    同一对象、同一进程里的两个判定当场分歧（实测）：

        asyncio.iscoroutinefunction(partial)   → True     ← 直觉会信的那个
        fastapi.is_coroutine_callable(partial) → False    ← FastAPI 真正问的那个

    FastAPI 只问后者（`fastapi/dependencies/utils.py` 里那个三分支版本）⇒ **不 await**
    ⇒ 把**协程对象**当身份注入 handler ⇒ `AttributeError: 'coroutine' object has
    no attribute 'id'` ⇒ memory 6 个端点 **100% 500**（不是 401）。

★ 为什么既有三套验证全绿（各自差一层，缺一不可）
    · `tests/test_memory_distill.py` 的依赖树断言当时用**名字子串**匹配，
      而 `str(partial)` 恰好含 `require_authenticated_user` ⇒ 只判得出「挂没挂」；
    · `r150_probe_c24.py`（115/115）与全部服务层测试**绕过 HTTP** 直接调 service
      ⇒ 缺陷在**依赖注入层**，绕过去就永久看不见；
    · 前端那时还是假页面（r141 判定）⇒ 没有任何真调用会踩到它。

★ 为什么是**形态**判据，而不是名字白名单
    名字白名单（`scripts/auth_coverage_report.py` 的 `AUTH_DEPENDENCY_NAMES`）
    有两个洞，且第一个洞**真的发生过**：
      · `partial` **没有 `__name__`** ⇒ 白名单认不出它 ⇒ 体检报告把 memory
        报成「6 端点 / 已鉴权 0 / 0% <-- 无鉴权」，与事实**完全相反**；
      · 新增模块要人工登记，忘了就静默失真（那份 docstring 自己写着这件事）。
    形态判据与「谁写的、叫什么」无关 —— 新模块一律**自动**被覆盖。

★ ★ 判据**不能**写成「两个判定必须一致」（实测教训）
    `OAuth2PasswordBearer` 这类**可调用对象**在 25 条路由上出现，它是
    `asyncio.iscoroutinefunction=False` 而 `is_coroutine_callable=True`
    —— 与事故**同一种分歧、方向相反**，但它是**正确且必要的**形态
    （`__call__` 是 async 方法，FastAPI 会正常 await）。
    若把判据写成「两者必须相等」，这条门禁会在 25 条正当路由上变红 = **负资产**。
    只有「asyncio 说真、FastAPI 说假」这一侧会炸：**它说异步、它却不 await**。

★ 反向注入已验（两种坏形态各注入一次，都真的变红了）
    A：`_REQUIRE_USER` 改回 `functools.partial(...)` ⇒ 本条变红（并连带打红
       `test_memory_distill.py` 的两条 + `test_memory_contract.py` 的三条，
       后三条报的正是 `AttributeError: 'coroutine' object has no attribute 'id'`
       —— 事故原样复现）；
    C：把 `_REQUIRE_USER` 包一层保留 `__wrapped__` 的包装 ⇒ 本条变红。

★ 为什么**没有**「`Depends(async_fn())` 直接塞协程对象」这条断言
    因为 FastAPI 在**建路由时**就拦住了它：`get_dependant()` 里有
    `if not callable(call): raise TypeError(...)`，而**协程对象不是 callable**。
    实测（第 153 轮反向注入 B）：改成 `Depends(_REQUIRE_USER(request=None, db=None))`
    ⇒ `import main` 直接抛
    `TypeError: <coroutine object _REQUIRE_USER ...> is not a callable object`，
    7 条测试全红 —— 但**全部是导入期炸的**，没有一条来自断言。
    也就是说那是**响的**失败，不属于本门禁的业务（本门禁只管**静默**那一类）。
    给一个响的失败再写一条永远红不了的断言 = 死断言；而本仓铁律是
    「没被反向注入验证过的门禁 = 没有门禁」—— 所以这里只留注释，不留断言。
"""

from __future__ import annotations

import asyncio

#: 防空跑下限。★ 刻意写得很松（实测：路由 229 / 节点 1212 / 树深 2）——
#: 它的用途是抓「app 没 import 起来」或「树没往下递归」这类**全零**读数，
#: 不是抓「有人删了几个路由」。照实测值写，正当重构就会变红 = 负资产。
MIN_ROUTES = 100
MIN_DEPTH = 2


def _walk(dependant, depth=0):
    """dependant 子树深度不限地逐个 yield（连同深度）。"""
    yield dependant, depth
    for child in getattr(dependant, "dependencies", []) or []:
        yield from _walk(child, depth + 1)


def test_no_dependency_that_fastapi_silently_does_not_await():
    """★★★ 全应用不存在「说自己是异步、而 FastAPI 不会 await」的依赖。

    判据是**形态**，与依赖叫什么都无关。两种坏形态分开报，因为成因不同：

      A. `asyncio.iscoroutinefunction(call) and not is_coroutine_callable(call)`
         —— 「两个判定分歧」那一类。典型成因 `functools.partial(async_fn, ...)`：
         `partial` 既非 routine 也非 class ⇒ FastAPI 落到 `call.__call__`，
         而它是同步 C 方法 ⇒ 判不可 await。
      C. `__wrapped__` 指向协程函数，而 call 本身不被判为可 await
         —— `lru_cache` / `functools.wraps` 这类**保留了 `__wrapped__`** 的包装。
         它与 A **同样静默**，但 A 的判据**漏掉它**（`iscoroutinefunction` 不看
         `__wrapped__`），所以必须单独一条 —— 这正是「换一种包装就绕过门禁」
         的那个缺口。

    两种的症状**相同**（FastAPI 不 await ⇒ 注入协程对象 ⇒ handler 里
    `.id` 抛 AttributeError ⇒ 500，看起来像「数据库挂了」），所以只要出现就停。

    ★ 为什么它必须走**运行时** dependant 树，而不是 grep 源码：
      挂载方式至少有五种（路由级 `dependencies=[...]` / 端点自己 `Depends(...)` /
      `main.py` 的条件挂载 / `include_router` 层层传下去 / 类式依赖的 `__call__`），
      其中两种在本仓历史上实测过是**根本没挂上**的。dependant 树是唯一真源。

    ★ 为什么每条都要**防住空跑**：一条「0 命中」的断言，在「app 根本没起来」
      和「真的一处都没有」下长得一模一样。所以先断言扫描规模与递归深度。

    反向注入已验：见本文件模块 docstring 末尾（A / B 各一次）。
    """
    from fastapi.dependencies.utils import is_coroutine_callable

    from main import app

    route_count = 0
    node_count = 0
    max_depth = 0
    form_a = []  # 两个判定分歧：asyncio 说是协程函数、FastAPI 不会 await
    form_c = []  # __wrapped__ 指向协程函数，而 call 本身不被判为可 await

    for route in app.routes:
        top = getattr(route, "dependant", None)
        if top is None:
            continue
        route_count += 1
        path = getattr(route, "path", "?")
        methods = ",".join(sorted(getattr(route, "methods", ()) or ()))
        for node, depth in _walk(top):
            node_count += 1
            if depth > max_depth:
                max_depth = depth
            call = getattr(node, "call", None)
            if call is None:
                continue
            if asyncio.iscoroutinefunction(call) and not is_coroutine_callable(call):
                form_a.append("%s [%s] :: %r" % (path, methods, call))
                continue
            inner = getattr(call, "__wrapped__", None)
            if (inner is not None
                    and asyncio.iscoroutinefunction(inner)
                    and not is_coroutine_callable(call)):
                form_c.append("%s [%s] :: %r  (__wrapped__=%r)"
                              % (path, methods, call, inner))

    # ---- 防空跑：没有这三条，「0 命中」既可能是真干净，也可能是压根没扫到 ----
    assert route_count >= MIN_ROUTES, (
        "只扫到 %d 条带 dependant 的路由（下限 %d）—— app 没起来 / 路由没注册，"
        "本次门禁的「0 命中」不成立" % (route_count, MIN_ROUTES)
    )
    assert max_depth >= MIN_DEPTH, (
        "dependant 树最大深度只有 %d（下限 %d）—— 递归没往下走，"
        "子依赖里的坏形态一个都扫不到" % (max_depth, MIN_DEPTH)
    )
    assert node_count > route_count, (
        "节点数 %d 不大于路由数 %d —— 只走到了顶层 handler，没进子依赖"
        % (node_count, route_count)
    )

    assert not form_a, (
        "有 %d 个依赖是「asyncio 说是协程函数、而 FastAPI 不会 await」—— "
        "FastAPI 判「要不要 await」走的是**它自己**的 `is_coroutine_callable`"
        "（`fastapi/dependencies/utils.py`：`partial` 既非 routine 也非 class ⇒ "
        "落到 `call.__call__`，而它是**同步**的 C 方法包装 ⇒ 判 False）。"
        " 后果不是 401 而是 **500**：handler 拿到的是**协程对象**，"
        "`current_user.id` 抛 `AttributeError: 'coroutine' object has no attribute 'id'`"
        "（看起来像「数据库挂了」）。常见成因：`functools.partial(async_fn, ...)`；"
        " 修法：写成真 `async def` 包装（见 `modules/memory/router.py::_REQUIRE_USER`）。"
        "\n  %s" % (len(form_a), "\n  ".join(form_a))
    )
    assert not form_c, (
        "有 %d 个依赖被「保留了 `__wrapped__` 的包装」包住了：`__wrapped__` 指向一个"
        "协程函数，而 FastAPI **不会 await** 这个 call 本身。"
        " 症状与 form_a 完全相同（注入协程对象 ⇒ 500），但 form_a 的判据漏掉它"
        "（`asyncio.iscoroutinefunction` **不跟随** `__wrapped__`，所以 `lru_cache`、"
        "`functools.wraps` 装饰的 sync 包装都判 False）。"
        " 修法：让交出去的东西**自己**是 `async def`（去掉那层缓存/包装，或把包装写成"
        " async def）；缓存请放在被调用的**内部**，不要包住依赖本身。"
        "\n  %s" % (len(form_c), "\n  ".join(form_c))
    )

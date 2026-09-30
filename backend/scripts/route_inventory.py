"""运行时路由盘点 —— **唯一真源**（第 247 轮）。

==============================================================================
★ 为什么需要这个模块
==============================================================================
FastAPI 0.141 起，`include_router()` **不再把子路由摊平进 `app.routes`**，
而是往里追加一个惰性容器 `fastapi.routing._IncludedRouter`。实测本仓：

    top-level app.routes = 32 = Route 4 + Mount 1 + APIRoute 2 + _IncludedRouter 25

也就是说，一切「`for r in app.routes: r.path`」的写法**读到空且不报错**：
`/api/v1` 开头的业务路由一条都数不到（实测 0 条，而真实有 198 条）。

这类缺陷的症状是**静默变绿**（门禁盘点为空 ⇒ 空集合让 `missing` 断言恒假，
或 `pytest.skip` 把它吞掉），所以它躲过了整轮回归 —— 直到框架升级那一刻集体爆发。
本轮 12 条红里有 8 条是它。

★ 判据（本仓铁律）：**盘点型门禁在盘点数为 0 时必须 `assert` 失败**，
  绝不允许 `pytest.skip` / 空集合把「判据失明」吞成绿。

==============================================================================
★ 设计要点
==============================================================================
1. **不钉库私有名字**：容器识别走**结构**（有 `effective_candidates` / `routes`
   这类子节点访问器的就是容器），不写 `isinstance(x, _IncludedRouter)`。
   这样 0.14x 再换容器形态时，本模块要么继续工作，要么**显式报错**。
2. **遇到不认识的对象必须炸**：这是本模块存在的**全部理由**。旧写法对
   `_IncludedRouter` 的处理是「`getattr(r,"path","")` 取不到 ⇒ 静默当成非路由」
   —— 失明就是这样来的。这里改成收进 `unknown`，`inventory()` 直接抛。
3. **端点判据 = 有 `dependant`**：`starlette.routing.Route` / `Mount` 都没有
   `dependant`；FastAPI 的真实端点（`APIRoute` 及 0.141 的投影
   `_EffectiveRouteContext`）都有。所以 `hasattr(x, "dependant")` 是跨版本成立的
   「这是不是一个端点」判据 —— 比 `isinstance(x, APIRoute)` 稳，后者在 0.141 下
   会把 198 条业务端点**全部漏掉**（本仓 `test_account_store_hierarchy.py` 与
   `scripts/auth_coverage_report.py` 原来就是这种写法）。
4. **子节点取值取「第一个非空列表」**：属性存在但内容为空正是失明的形态，
   不能当成「有容器、没子路由」。

==============================================================================
★ 用法
==============================================================================
    from scripts.route_inventory import (iter_api_routes, find_route, find_routes,
                                         inventory, route_paths, all_paths,
                                         iter_endpoint_signatures, fastapi_awaitable)

    routes = iter_api_routes(app)                       # 全部端点（路径前缀已拼好）
    route  = find_route(app, "/api/v1/orchestrator/plan", "GET")
    assert route is not None, "端点没挂上"
    inv = inventory(app)                                # 带体检信息（失明即抛）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


class RouteInventoryError(RuntimeError):
    """盘点失明 / 遇到无法识别的容器 —— **必须让门禁变红**，不许静默。"""


#: 「容器」的子节点访问器候选名。**顺序即优先级**：先试专用访问器，再退到通用。
#: ★ 为什么 `effective_candidates` 排在 `routes` 前面：0.141 的 `_IncludedRouter`
#:   若同时提供 `routes`（可能为空/为旧视图）与 `effective_candidates`（真源），
#:   按 `routes` 优先就会**再次失明**。
_CHILD_ATTRIBUTES: tuple[str, ...] = (
    "effective_candidates",           # fastapi 0.141 _IncludedRouter（方法）= 真源
    "effective_low_priority_routes",  # 同上（低优先/兜底路由）
    "routes",                         # starlette Router / Mount
)

#: 正常但**不是端点**的叶子类型（框架内置固定路由 / 挂载点）。
#: ★ 按**类型名**而不是 import 的类型对象：starlette 大版本改名时应当退回
#:   `unknown` 分支**报错**，而不是静默把新版内置路由漏掉。
#: ★ 挂载点（Mount）单独成桶：它既是「可路由路径」又是「可能含子路由的容器」，
#:   两者都要记 —— `test_static_mount_is_not_behind_business_auth` 要的就是它。
_MOUNT_TYPE = "Mount"
_KNOWN_LEAF_TYPES = frozenset({
    "Route",       # starlette 固定路由（/health、/metrics、/docs、/openapi.json）
    "WebSocketRoute",
    "Host",
})

#: 递归深度上限（防父子互相引用成环）
_MAX_DEPTH = 12


# ============================================================================
# 一、盘点
# ============================================================================


@dataclass
class RouteInventory:
    """一次盘点的全部读数（同时是**体检报告**，供门禁断言空跑）。"""

    endpoints: list = field(default_factory=list)
    mounts: list = field(default_factory=list)
    leaves: list = field(default_factory=list)
    containers: int = 0
    max_depth: int = 0
    unknown: list = field(default_factory=list)

    @property
    def paths(self) -> set:
        """**端点**路径（不含挂载点 / 内置固定路由）。"""
        return {getattr(r, "path", "") for r in self.endpoints}

    @property
    def all_paths(self) -> set:
        """全部可路由路径（端点 + 挂载点 + 内置固定路由）。"""
        out = set(self.paths)
        for node in (*self.mounts, *self.leaves):
            out.add(getattr(node, "path", ""))
        return out

    def describe(self) -> str:
        from collections import Counter

        kinds = Counter(type(r).__name__ for r in self.endpoints)
        return (
            "端点 %d（%s）· 挂载点 %d · 叶子 %d · 容器 %d · 最大深度 %d · 未知 %d"
            % (
                len(self.endpoints),
                dict(kinds),
                len(self.mounts),
                len(self.leaves),
                self.containers,
                self.max_depth,
                len(self.unknown),
            )
        )


def _children_of(node: Any):
    """取一个路由容器对象的子节点列表；不是容器则返回 None。

    ★ 取「第一个**非空**列表」而不是「第一个存在的属性」：全部为空时返回
      `[]`（确实是容器，只是暂时没子路由），一个都没有才返回 `None`。
    """
    empty_hit = False
    for attr in _CHILD_ATTRIBUTES:
        raw = getattr(node, attr, None)
        if raw is None:
            continue
        try:
            value = raw() if callable(raw) else raw
        except Exception:  # noqa: BLE001 — 探测属性不得把门禁炸成 ImportError/TypeError
            continue
        if isinstance(value, (list, tuple)):
            if value:
                return list(value)
            empty_hit = True
    return [] if empty_hit else None


def _is_endpoint(node: Any) -> bool:
    """是不是一个**真实端点**（而不是容器 / 静态挂载 / 框架内置路由）。

    ★ 用 `dependant` 而不是 `isinstance(APIRoute)`：见模块 docstring 第 3 点。
    """
    return hasattr(node, "dependant") and hasattr(node, "path")


def scan(app: Any) -> RouteInventory:
    """盘点但**不**做空跑断言 —— 供体检/诊断使用。

    门禁请用 `inventory()`（它会在失明时抛错）。
    """
    inv = RouteInventory()
    visited: set[int] = set()

    def walk(node: Any, depth: int) -> None:
        if depth > inv.max_depth:
            inv.max_depth = depth
        if depth > _MAX_DEPTH:
            inv.unknown.append(
                "%r（递归深度超过 %d，疑似容器成环）" % (node, _MAX_DEPTH)
            )
            return

        if _is_endpoint(node):
            inv.endpoints.append(node)
            return

        type_name = type(node).__name__
        is_mount = type_name == _MOUNT_TYPE
        children = _children_of(node)

        if is_mount:
            # 挂载点：既记路径，也往下走（挂的可能是子 app）
            inv.mounts.append(node)
        elif children is not None:
            inv.containers += 1

        if children:
            for child in children:
                key = id(child)
                if key in visited:
                    continue
                visited.add(key)
                walk(child, depth + 1)
            return

        if children is not None or type_name in _KNOWN_LEAF_TYPES:
            if not is_mount:
                inv.leaves.append(node)
            return

        # 走到这里：既不是端点，也不是任何已知形态 —— 必须记账，不许静默跳过。
        inv.unknown.append(repr(node))

    for route in list(getattr(app, "routes", []) or []):
        walk(route, 1)
    return inv


def inventory(app: Any) -> RouteInventory:
    """盘点并保证「没有失明」——门禁的唯一入口。

    抛 `RouteInventoryError` 的两种情况：
      · 端点数为 0 ⇒ 要么 app 没起来，要么写法已失明。两者都不许当成通过。
      · 出现无法识别的对象 ⇒ 上游又换了容器形态，本模块需要同步。
    """
    inv = scan(app)

    if inv.unknown:
        raise RouteInventoryError(
            "路由盘点遇到 %d 个无法识别的对象 —— 说明 app.routes 里出现了本模块"
            "不认识的容器/路由形态，**盘点结果不可信**（不要当成「没有」）。\n"
            "  先确认 FastAPI/Starlette 是否又改了 include_router 的容器形态"
            "（0.141 的 `_IncludedRouter` 就是这么来的），再补进 `_CHILD_ATTRIBUTES`"
            "或 `_KNOWN_LEAF_TYPES`。\n  %s"
            % (len(inv.unknown), "\n  ".join(inv.unknown[:10]))
        )

    if not inv.endpoints:
        raise RouteInventoryError(
            "路由盘点数为 **0** —— app 没 import 起来，或者盘点写法已失明。"
            "★ 盘点型门禁在盘点为 0 时**必须失败**，不许 skip / 空集合通过。"
            "  top-level app.routes=%d，容器=%d，挂载点=%d，叶子=%d"
            % (
                len(getattr(app, "routes", []) or []),
                inv.containers,
                len(inv.mounts),
                len(inv.leaves),
            )
        )
    return inv


# ============================================================================
# 二、消费便捷函数（全部走 inventory，天然带「失明即炸」）
# ============================================================================


def iter_api_routes(app: Any) -> list:
    """全部真实端点（`.path` / `.methods` / `.dependant` 均可用）。"""
    return inventory(app).endpoints


def route_paths(app: Any) -> set:
    """全部**端点**路径集合。"""
    return inventory(app).paths


def all_paths(app: Any) -> set:
    """全部可路由路径（端点 + 挂载点 + 内置固定路由）。"""
    return inventory(app).all_paths


def iter_all_routables(app: Any) -> list:
    """全部**可路由对象**（端点 + 挂载点 + 内置固定路由）。

    ★ 给「挂载点」类断言用（例：`/static` 必须是 Mount 而不是带鉴权的端点）。
      `iter_api_routes()` 只给端点，会把挂载点整段漏掉。
    """
    inv = inventory(app)
    return [*inv.endpoints, *inv.mounts, *inv.leaves]


def find_route(app: Any, path: str, method: str | None = None):
    """按路径（可选方法）找端点；找不到返回 None。"""
    for route in iter_api_routes(app):
        if getattr(route, "path", "") != path:
            continue
        if method is None:
            return route
        if method.upper() in _methods_of(route):
            return route
    return None


def find_routes(app: Any, path: str, method: str | None = None) -> list:
    """按路径（可选方法）找**全部**匹配端点（供「恰好 1 条」类断言使用）。"""
    out = []
    for route in iter_api_routes(app):
        if getattr(route, "path", "") != path:
            continue
        if method is not None and method.upper() not in _methods_of(route):
            continue
        out.append(route)
    return out


def iter_endpoint_signatures(app: Any) -> Iterator[tuple[str, str]]:
    """`(METHOD, path)` 逐条产出（多方法的端点会产出多条）。"""
    for route in iter_api_routes(app):
        path = getattr(route, "path", "")
        for method in sorted(_methods_of(route)):
            yield method, path


def _methods_of(route: Any) -> set:
    return {str(m).upper() for m in (getattr(route, "methods", ()) or ())}


# ============================================================================
# 三、FastAPI「会不会 await 它」的唯一实现
# ============================================================================
#
# ★ 背景（第 153 轮事故，后面有 3 个消费方都用它）：
#     asyncio.iscoroutinefunction(functools.partial(async_fn, ...))  → True
#     而 FastAPI 判「要不要 await」用的**不是**它 → False
#   ⇒ 不 await ⇒ 把协程对象当身份注入 handler ⇒ 端点 500（不是 401，
#     所以看起来像「数据库挂了」）。
#
# ★ 为什么把这件事收成一处实现：
#     原先 3 个消费方各写一遍 `from fastapi.dependencies.utils import
#     is_coroutine_callable`（`scripts/auth_coverage_report.py`、
#     `tests/test_memory_distill.py`、`tests/test_route_dependency_form.py`）。
#     0.141 把它改名成 `_is_coroutine_callable` ⇒ 三处**同时** ImportError。
#     本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到；三份就是三份负资产。
#
# ★ 为什么**不**在本模块里自己实现一遍那个三分支判定：
#     那样本门禁就与 FastAPI 的真实行为**解耦**了 —— FastAPI 改判据时，
#     我们的复刻版会继续按旧规则"正确"地判定，门禁静默失真。
#     这里的立场是：**问库本身**，名字变了就按候选名逐个找；
#     一个都找不到 ⇒ **显式抛错**（绝不退回 asyncio.iscoroutinefunction 那种
#     "看起来在工作"的兜底 —— 那正是事故的成因）。

#: FastAPI 判「要不要 await」的实现名候选（按版本向后兼容；顺序即优先级）。
#:   0.104~0.140: `is_coroutine_callable`
#:   0.141+:      `_is_coroutine_callable`（带 `_CallIdentity` 缓存）
_FASTAPI_AWAIT_PREDICATE_NAMES: tuple[str, ...] = (
    "is_coroutine_callable",
    "_is_coroutine_callable",
)

_await_predicate_cache: list = []  # [fn, name]


def fastapi_await_predicate():
    """返回 `(fn, name)`：FastAPI 真正用来判「要不要 await」的那个函数。"""
    if _await_predicate_cache:
        return _await_predicate_cache[0], _await_predicate_cache[1]

    from fastapi.dependencies import utils as _deps_utils

    for name in _FASTAPI_AWAIT_PREDICATE_NAMES:
        fn = getattr(_deps_utils, name, None)
        if callable(fn):
            _await_predicate_cache[:] = [fn, name]
            return fn, name

    raise RouteInventoryError(
        "FastAPI 判「要不要 await」的实现名一个都没找到（试过 %s）—— "
        "上游又改名/换模块了。★ **不许**退回 `asyncio.iscoroutinefunction` 顶替："
        "两者分歧处正是第 153 轮那次 500 事故的成因，静默顶替会让门禁失真。"
        " 请核对 `fastapi/dependencies/utils.py` 后补进 "
        "`_FASTAPI_AWAIT_PREDICATE_NAMES`。" % (_FASTAPI_AWAIT_PREDICATE_NAMES,)
    )


def fastapi_awaitable(call: Any) -> bool:
    """FastAPI **会不会 await** 这个 call —— 全仓唯一实现。"""
    if call is None:
        return False
    fn, _ = fastapi_await_predicate()
    return bool(fn(call))


if __name__ == "__main__":  # pragma: no cover — 手工体检用
    import os
    import sys

    _BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BACKEND_ROOT not in sys.path:
        sys.path.insert(0, _BACKEND_ROOT)
    os.chdir(_BACKEND_ROOT)

    from main import app as _app  # noqa: E402

    _inv = scan(_app)
    print("=" * 68)
    print("路由盘点体检")
    print("=" * 68)
    print(f"top-level app.routes = {len(_app.routes)}")
    print(f"盘点结果：{_inv.describe()}")
    print(f"await 判据来源：{fastapi_await_predicate()[1]}")
    if _inv.unknown:
        print("★ 未知对象（会让 inventory() 抛错）：")
        for item in _inv.unknown[:20]:
            print("   ", item)
    print("-" * 68)
    _biz = sorted(p for p in _inv.paths if p.startswith("/api/v1"))
    print(f"/api/v1 端点 = {len(_biz)}")
    for p in _biz[:15]:
        print("   ", p)
    print("挂载点:", sorted(getattr(m, "path", "") for m in _inv.mounts))
    print("叶子  :", sorted(getattr(m, "path", "") for m in _inv.leaves))

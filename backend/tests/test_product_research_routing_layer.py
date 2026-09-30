# -*- coding: utf-8 -*-
"""P0-6 「路由与意图层」形态门禁（第四刀）。

## 本刀在四刀里的位置

    agent_models.py            数据结构
    agent_helpers.py           领域纯逻辑（mixin，函数体里无 self）
    agent_analyzers.py         分析编排（显式传参）
    agent_hitl.py              HITL 审批（显式传参）
    agent_routing.py           路由与意图（显式传参）  ← 本刀
    agent_product_research.py  Agent 本体（入口 / 流式 / 会话 / 落库）

## 本刀特有的三个静默失败方向

  · **回流**：`Route(...)` / `first_match` / `BaseAgent` 又出现在主文件里
    ⇒ 「唯一真源」变成两份，且第二份永远测不到；
  · **漏传**：`build_router` 的 7 个装配参数漏一个 ⇒ TypeError（较好）；
    但 `route_via_tools=` / `stream_via_tools=` 漏了会**绕过 monkeypatch**
    （`tests/test_hitl_approval_flow.py` 打在**实例**上的补丁静默失效）；
  · **重导出写成了第二份定义**：`_INTENT_ROUTES = (Route(...), ...)` 抄回来
    ⇒ 表面绿，实际两份表各自漂移。

## 不测什么

不测「主文件还有没有 `_routing`」—— 当然有；也不测 docstring 写得对不对。
只钉**形态**：谁在哪里、依赖怎么传、契约有没有断。
"""
import ast
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "product_research"
MAIN_PY = MODULE_DIR / "agent_product_research.py"
ROUTING_PY = MODULE_DIR / "agent_routing.py"

MAIN_MODULE = "modules.product_research.agent_product_research"
ROUTING_MODULE = "modules.product_research.agent_routing"
ROUTING_ALIAS = "_routing"

#: 路由层的**全部**函数（集合相等判据：增删都必须改这里）
ROUTING_FUNCS = frozenset({
    "build_router",
    "parse_tool_output",
    "route_gated_intent",
    "stream_gated_intent",
    "route_via_tools",
    "classify_intent",
    "is_candidate_query",
    "is_market_insight_query",
    "named_tokens",
})

#: 主类薄壳 → 它必须委托的模块级函数
SHELL_TO_DELEGATE = {
    "_build_router": "build_router",
    "_parse_tool_output": "parse_tool_output",
    "_route_gated_intent": "route_gated_intent",
    "_stream_gated_intent": "stream_gated_intent",
    "_route_via_tools": "route_via_tools",
    "_classify_intent": "classify_intent",
    "_is_candidate_query": "is_candidate_query",
    "_is_market_insight_query": "is_market_insight_query",
    "_named_tokens": "named_tokens",
}

#: 薄壳体里**禁止**出现的名字 —— 出现即说明领域逻辑又被抄回主类了。
#: 只看**函数体的语句**（不含签名与返回标注）：返回标注 `-> AgentResponse`
#: 是契约声明，不是回流（第三刀踩过这个假红）。
FORBIDDEN_IN_SHELL = frozenset({
    "Route", "first_match", "loads", "AIMessage", "ToolMessage",
    "BaseAgent", "AgentResponse", "NO_SHOP_SELECTED_MSG",
    "INTENT_ROUTES", "TOOL_TYPE_MAP", "SAVE_ACTION_WORDS",
})

#: 薄壳必须**作为回调**显式传下去的 `self.` 属性。
#:
#: ★ 为什么必须是 `self.<attr>` 而不是模块函数：`tests/test_hitl_approval_flow.py`
#:   用 `monkeypatch.setattr(agent, "_route_via_tools", …)` 替换**实例**方法；
#:   裸名/模块函数会绕过那次替换，让「测试以为换掉了」变成「其实没生效」。
#:   `router` 也用 `self._router`（**不是** `self._get_router()`）：原实现就是裸属性
#:   访问，且两个调用点都先调过 `_get_router()` 判过 None —— 换掉会顺带改变
#:   「谁负责懒加载」的归属。
SELF_CALLABLES = {
    "_route_gated_intent": {
        "get_router": "_get_router",
        "route_via_tools": "_route_via_tools",
    },
    "_stream_gated_intent": {
        "get_router": "_get_router",
        "stream_via_tools": "_stream_via_tools",
    },
    "_route_via_tools": {
        "router": "_router",
        "detect_pending": "_detect_pending_approval",
        "compose_reply": "_compose_reply",
    },
}

#: `build_router` 的 7 个 keyword-only 形参 —— 薄壳必须**逐个显式传**。
#: 漏传会 TypeError（不静默），但这条判据防的是「给它们加默认值从而变成可选」。
BUILD_ROUTER_KWARGS = frozenset({
    "agent_name", "system_prompt", "tools", "budget",
    "context_policy", "checkpointer", "checkpoint_ns",
})

#: 类体/模块级的**重导出**：名字 → (被指向的路由层名字)
CLASS_REEXPORTS = {
    "_INTENT_ROUTES": "INTENT_ROUTES",
    "_APPROVAL_CHANNEL_DOWN_MSG": "APPROVAL_CHANNEL_DOWN_MSG",
}
MODULE_REEXPORTS = {
    "QUERY_CANDIDATES_INTENT": "QUERY_CANDIDATES_INTENT",
    "MARKET_INSIGHT_INTENT": "MARKET_INSIGHT_INTENT",
}

#: 已随外移**删除**（不重导出）的类常量 —— 主类里再出现就是回流。
REMOVED_CLASS_CONSTS = frozenset({
    "_CANDIDATE_QUERY_DOMAIN", "_CANDIDATE_QUERY_COUNT",
    "_MARKET_INSIGHT_METRICS", "_MARKET_INSIGHT_RANK",
    "_SAVE_ACTION_WORDS", "_TOOL_TYPE_MAP",
})

#: 路由层允许的**非标准库**依赖前缀（其余交给 `sys.stdlib_module_names`）。
#: 精确到子模块：`ai_infra.base_agent`（装配 BaseAgent）与 `ai_infra.intent`
#: （唯一真源）是这一层的本职依赖，但 `ai_infra` 整体并不开放。
ALLOWED_IMPORT_PREFIXES = (
    "core.logger",
    "langchain_core.messages",
    "ai_infra.base_agent",
    "ai_infra.intent",
    "platforms.amazon.client",      # `named_tokens` 惰性 import `tokenize`
)

#: 出现即违规的 import 前缀（与 ALLOWED 不重叠）
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy", "asyncpg", "psycopg", "redis", "httpx", "requests", "aiohttp",
    MAIN_MODULE,                    # 不许反向回流主文件（会成环）
    ROUTING_MODULE,                 # 不许自己 import 自己（冗余）
    "modules.conversation",         # 持久化是**注入的回调**，不是 import
    "modules.product_research.tools",
    "modules.product_research.router",
    "modules.product_research.service",
)

#: 薄壳行数上限（含 docstring）。实测最长的是 `_build_router` 34 行；
#: 留到 40 是给注释余量，同时挡住「逻辑长回来」。
SHELL_MAX_LINES = 40


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_bytes().decode("utf-8"))


def _main_class(tree: ast.Module) -> ast.ClassDef:
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ProductResearchAgent"), None)
    assert cls is not None, "主文件里找不到 ProductResearchAgent"
    return cls


def _methods(cls: ast.ClassDef) -> dict:
    return {n.name: n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _top_funcs(tree: ast.Module) -> dict:
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _import_targets(tree: ast.Module) -> set:
    """本模块 import 的**目标全名**集合（`from a.b import c` 展开出 `a.b.c`）。"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                out.add(f"<relative:{n.level}:{n.module or ''}>")
                continue
            base = n.module or ""
            if base:
                out.add(base)
            for a in n.names:
                out.add(f"{base}.{a.name}" if base else a.name)
    return out


def _is_std_or_allowed(target: str) -> bool:
    if target.startswith("<relative"):
        return True
    if target.split(".")[0] in sys.stdlib_module_names:
        return True
    return any(target.startswith(p) for p in ALLOWED_IMPORT_PREFIXES)


def _referenced_names(node: ast.AST) -> set:
    """节点子树里出现的**标识符与属性名**全集（引用也算，不只调用）。"""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _referenced_in_body(fn: ast.AST) -> set:
    """★ 只看**函数体的语句**，不含签名与返回标注（第三刀的假红教训）。"""
    out: set = set()
    for stmt in fn.body:
        out |= _referenced_names(stmt)
    return out


def _routing_calls(node: ast.AST) -> set:
    """子树里所有 `_routing.<name>(...)` 调用的 `<name>` 集合。"""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == ROUTING_ALIAS):
            out.add(n.func.attr)
    return out


def _routing_kwargs(node: ast.AST) -> set:
    """子树里 `_routing.<fn>(...)` 调用的**关键字实参名**集合。"""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == ROUTING_ALIAS):
            out.update(k.arg for k in n.keywords if k.arg)
    return out


def _routing_kwarg_value(node: ast.AST, kw: str):
    """子树里 `_routing.<fn>(...)` 调用的 `kw=` 实参**表达式节点**。"""
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == ROUTING_ALIAS):
            for k in n.keywords:
                if k.arg == kw:
                    return k.value
    return None


def _is_self_attr(node, attr: str) -> bool:
    return (isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr == attr)


def _assign_in(body: list, name: str):
    """在语句列表里找 `name = <value>`，返回 value 节点（找不到返回 None）。"""
    for n in body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return n.value
    return None


def _called_bare_names(fn: ast.AST) -> set:
    """函数体里**裸名**调用的函数名集合（`first_match(...)` 这种）。"""
    return {n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def routing_tree():
    assert ROUTING_PY.exists(), f"路由层不存在: {ROUTING_PY}"
    return _tree(ROUTING_PY)


@pytest.fixture(scope="module")
def main_tree():
    assert MAIN_PY.exists(), f"主文件不存在: {MAIN_PY}"
    return _tree(MAIN_PY)


@pytest.fixture(scope="module")
def shells(main_tree):
    return _methods(_main_class(main_tree))


# --------------------------------------------------------------------------- #
# A · 路由层自身
# --------------------------------------------------------------------------- #

def test_routing_module_has_exactly_the_nine_functions(routing_tree):
    """集合相等：9 个函数一个不多一个不少（防静默增删）。"""
    got = set(_top_funcs(routing_tree))
    assert got == set(ROUTING_FUNCS), (
        f"多出来的: {sorted(got - ROUTING_FUNCS)}；丢掉的: {sorted(ROUTING_FUNCS - got)}"
    )


def test_no_routing_function_touches_self(routing_tree):
    """★ `self`/`cls` 出现即说明该函数又需要 Agent 实例 ⇒ 显式传参已被破坏。

    这正是本刀**不用 mixin** 的理由：藏进基类会让耦合从「可以数的参数」
    变成「看不见的继承链」，门禁再也数不出这层依赖什么。
    """
    offenders = []
    for nm in ROUTING_FUNCS:
        fn = _top_funcs(routing_tree)[nm]
        if any(isinstance(x, ast.Name) and x.id in ("self", "cls") for x in ast.walk(fn)):
            offenders.append(nm)
    assert not offenders, (
        f"这些路由层函数开始依赖实例/类状态了，必须改成参数显式传入: {offenders}"
    )


def test_routing_layer_imports_are_leaf(routing_tree):
    """路由层只允许依赖日志 / 消息类型 / `ai_infra` 两个本职模块 / 同层数据模型。"""
    targets = _import_targets(routing_tree)
    bad = [t for t in targets if any(t.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES)]
    assert not bad, (
        f"路由层出现了禁止的依赖: {bad} —— "
        f"取数 / 持久化 / 注册表必须作为 callable 由调用方传入，不能 import"
    )
    unexpected = [t for t in targets if not _is_std_or_allowed(t)]
    assert not unexpected, (
        f"路由层新增了未登记的非标准库依赖: {unexpected}；"
        f"若确实需要，请同时更新 ALLOWED_IMPORT_PREFIXES 并说明理由"
    )


# --------------------------------------------------------------------------- #
# B · 主文件薄壳：真的委托了吗
# --------------------------------------------------------------------------- #

def test_main_shells_really_delegate(shells):
    """★ 每个薄壳都必须出现对应 `_routing.<函数>` 调用（缺此条空壳也能过）。"""
    missing = {}
    for shell_name, fn_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        called = _routing_calls(shells[shell_name])
        if fn_name not in called:
            missing[shell_name] = sorted(called) or "（没调用 _routing 任何函数）"
    assert not missing, f"这些薄壳没有委托给路由层: {missing}"


def test_main_shells_have_no_domain_logic(shells):
    """薄壳里不许出现领域原语 —— 出现即说明逻辑又被抄回主类了。"""
    bad = {}
    for shell_name in SHELL_TO_DELEGATE:
        hit = _referenced_in_body(shells[shell_name]) & FORBIDDEN_IN_SHELL
        if hit:
            bad[shell_name] = sorted(hit)
    assert not bad, f"薄壳里出现了领域逻辑（应留在 agent_routing.py）: {bad}"


def test_main_shells_stay_small(shells):
    """薄壳行数上限 —— 挡住「逻辑长回来」。"""
    over = {}
    for shell_name in SHELL_TO_DELEGATE:
        fn = shells[shell_name]
        n = fn.end_lineno - fn.lineno + 1
        if n > SHELL_MAX_LINES:
            over[shell_name] = n
    assert not over, f"薄壳超过 {SHELL_MAX_LINES} 行（逻辑回流了？）: {over}"


def test_build_router_shell_passes_all_seven_params(shells):
    """★ `build_router` 的 7 个 keyword-only 形参必须**逐个显式传**。

    漏传会 TypeError（不静默）；这条防的是「给它们加默认值从而变成可选」——
    那时漏传就退化成「悄悄用了另一个预算档 / 另一个 checkpoint_ns」。
    """
    got = _routing_kwargs(shells["_build_router"])
    missing = BUILD_ROUTER_KWARGS - got
    assert not missing, (
        f"`_build_router` 薄壳漏传了 {sorted(missing)}；"
        f"这些是装配策略，漏传会静默用错档位（实参名: {sorted(got)}）"
    )


# --------------------------------------------------------------------------- #
# C · 依赖**显式**：漏传不报错，只会静默降级 / 绕过 monkeypatch
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("shell_name", sorted(SELF_CALLABLES))
def test_shells_pass_self_callables(shells, shell_name):
    """★ 三个薄壳必须把 `self.<attr>` 作为回调显式传下去。

    `tests/test_hitl_approval_flow.py` 用 `monkeypatch.setattr(agent, "_route_via_tools", …)`
    替换**实例**方法 —— 传 `self.` 属性 ⇒ 查找发生在调用时刻 ⇒ 补丁照常生效。
    裸名/模块函数会绕过它（测试照绿，但测的不是真路径）。
    """
    fn = shells[shell_name]
    wrong = {}
    for kw, attr in SELF_CALLABLES[shell_name].items():
        val = _routing_kwarg_value(fn, kw)
        if val is None:
            wrong[kw] = "（没传）"
        elif not _is_self_attr(val, attr):
            wrong[kw] = ast.unparse(val)
    assert not wrong, (
        f"`{shell_name}` 的回调没走 `self.` 查找: {wrong} —— "
        f"实例级 monkeypatch 会静默失效"
    )


def test_detect_pending_shell_is_not_bypassed(shells):
    """★ `_detect_pending_approval` 本身**留在主类**（monkeypatch 打在实例上）。

    它若被搬走，`tests/test_thinking_trace.py` 的 `monkeypatch.setattr(agent, …)`
    会打到一个不存在的方法上（或打到了但没人用）⇒ 测试静默失真。
    """
    assert "_detect_pending_approval" in shells, "探测薄壳被搬走了（实例级 monkeypatch 会失效）"


# --------------------------------------------------------------------------- #
# D · 重导出必须是**同一对象**，不是第二份定义
# --------------------------------------------------------------------------- #

def test_class_constants_are_reexports_not_redefinitions(main_tree):
    """`_INTENT_ROUTES` / `_APPROVAL_CHANNEL_DOWN_MSG` 必须是 `_routing.<name>` 的别名。

    ★ 抄回来一份 `Route(...)` 表 ⇒ 表面绿，实际两份表各自漂移，且第二份永远测不到。
    """
    cls = _main_class(main_tree)
    bad = {}
    for name, target in CLASS_REEXPORTS.items():
        val = _assign_in(cls.body, name)
        if not (isinstance(val, ast.Attribute)
                and isinstance(val.value, ast.Name)
                and val.value.id == ROUTING_ALIAS
                and val.attr == target):
            bad[name] = ast.unparse(val) if val is not None else "（找不到）"
    assert not bad, (
        f"这些类常量不是重导出（必须是 `{ROUTING_ALIAS}.<name>`）: {bad}"
    )


def test_module_constants_are_reexports_not_redefinitions(main_tree):
    """两个模块级意图标签同理（消费方按本模块路径导入 ⇒ 必须仍是**同一对象**）。"""
    bad = {}
    for name, target in MODULE_REEXPORTS.items():
        val = _assign_in(main_tree.body, name)
        if not (isinstance(val, ast.Attribute)
                and isinstance(val.value, ast.Name)
                and val.value.id == ROUTING_ALIAS
                and val.attr == target):
            bad[name] = ast.unparse(val) if val is not None else "（找不到）"
    assert not bad, f"这些模块级标签不是重导出: {bad}"


# --------------------------------------------------------------------------- #
# E · 主文件不再持有判定体 / 死 import 已清
# --------------------------------------------------------------------------- #

def test_main_no_longer_holds_the_removed_class_constants(main_tree):
    """已外移的类常量必须**整批消失**（它们只被已外移的判定消费）。"""
    cls = _main_class(main_tree)
    present = {t.id for n in cls.body if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    leftover = present & REMOVED_CLASS_CONSTS
    assert not leftover, (
        f"主类里还有已外移的常量: {sorted(leftover)} —— "
        f"留下就是**死常量**（消费方已搬走）"
    )


def test_classify_shell_has_no_bare_first_match_call(shells):
    """★ `_classify_intent` 薄壳里不得有 `first_match` 的**裸名调用**。

    判据走 AST Call 而不是字符串：docstring 里提一句 `first_match` 是引用，
    不是「关键词路由又住回主类了」。
    """
    called = _called_bare_names(shells["_classify_intent"])
    assert "first_match" not in called, (
        "`_classify_intent` 薄壳里出现了 `first_match` 调用 ⇒ 判定体回流了"
    )


def test_main_no_route_primitive(main_tree):
    """★ `Route` 必须只住在路由层 / `ai_infra.intent`。

    它原先由主文件 import 且只有一个消费点（`_INTENT_ROUTES` 表）。表搬走后
    import 是死代码；若它又出现在主文件里，说明关键词路由被抄回去了。
    """
    hits = _referenced_names(main_tree) & {"Route"}
    assert not hits, "主文件又出现了 `Route` —— 关键词路由表回流了（应只在 agent_routing.py）"

    routing_targets = _import_targets(_tree(ROUTING_PY))
    assert any(t.startswith("ai_infra.intent") for t in routing_targets), (
        "路由层没有 import `ai_infra.intent` —— 唯一真源失去了消费方"
    )


def test_main_imports_are_pruned(main_tree):
    """死 import 必须清掉，且 typing 的名单不得再长回来。

    判据走 AST 的 import 节点，不看源码字符串（注释里提一句「已删 json」不算）。
    """
    for n in main_tree.body:
        if isinstance(n, ast.Import):
            names = {a.name for a in n.names}
            assert "json" not in names, (
                "主文件又 import 了 `json` —— 唯一的消费点（`parse_tool_output`）已外移"
            )
        elif isinstance(n, ast.ImportFrom):
            if n.module == "ai_infra.intent":
                raise AssertionError(
                    "主文件不该再 import `ai_infra.intent` —— 判定体已外移到 agent_routing"
                )
            if n.module == "langchain_core.messages":
                got = {a.name for a in n.names}
                assert got <= {"HumanMessage"}, (
                    f"`langchain_core.messages` 的名单长回来了: {sorted(got)}；"
                    f"`AIMessage` / `ToolMessage` 只被已外移的 `route_via_tools` 消费"
                )
            if n.module == "typing":
                got = {a.name for a in n.names}
                assert got <= {"Any", "AsyncIterable", "List", "Optional"}, (
                    f"typing 名单长回来了: {sorted(got)}；`Dict` 全是死引用"
                )


# --------------------------------------------------------------------------- #
# F · 方法名一一对应
# --------------------------------------------------------------------------- #

def test_shell_to_routing_names_match_one_to_one(routing_tree, shells):
    """薄壳 → 路由层函数必须**一一对应**且两边都存在（改名即红）。"""
    routing_names = set(_top_funcs(routing_tree))
    for shell_name, fn_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        assert fn_name in routing_names, f"路由层丢掉了函数 {fn_name}"
    assert len(set(SHELL_TO_DELEGATE.values())) == len(SHELL_TO_DELEGATE), (
        "SHELL_TO_DELEGATE 里有重复的委托目标（两个薄壳指同一个函数？）"
    )


def test_no_routing_calls_outside_the_shells(main_tree):
    """★ 主文件对 `_routing.*` 的调用必须**只**出现在那 9 个薄壳里。

    在别处直接调（例如 `_stream_via_tools` 里自己调 `_routing.route_via_tools`）
    会**绕过薄壳** —— 而薄壳正是 monkeypatch 与形态门禁共同盯着的通道。
    """
    shell_names = set(SHELL_TO_DELEGATE)
    stray = {}
    for name, fn in _methods(_main_class(main_tree)).items():
        called = _routing_calls(fn)
        if called and name not in shell_names:
            stray[name] = sorted(called)
    assert not stray, f"这些方法在 9 个薄壳之外调用了路由层: {stray}"

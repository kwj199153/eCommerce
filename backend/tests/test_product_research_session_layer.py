# -*- coding: utf-8 -*-
"""P0-6 「会话与状态层」形态门禁（第五刀）。

## 本刀与前四刀的关系

第一刀（`agent_helpers.py`）摘走**不碰实例状态**的方法（mixin，零改动）。
第二刀（`agent_analyzers.py`）摘走 4 个 `_analyze_*`，改**显式传参**。
第三刀（`agent_hitl.py`）摘走 HITL 块 5 个函数。
第四刀（`agent_routing.py`）摘走路由与意图块 9 个函数。
本刀同法摘走会话与状态块的 **8 个方法 + 1 个只读 property**（157 行）到
`agent_session.py`，外加 1 个模块级常量 `_DEFAULT_STATE_SCOPE`。

## 与第三/四刀最关键的一处**不对称**（也是本门禁存在的首要理由）

第三、四刀的新模块**禁止** import 主文件（`FORBIDDEN_IMPORT_PREFIXES` 含 `MAIN_MODULE`，
理由是会成环）。本刀**必须**反过来：`agent_session.py` 顶层
`import modules.product_research.agent_product_research as _pr`，因为

    `_current_context_id` / `_current_shop_id` / `_current_user_id` 的**真源**
    与 `_hydrate_session_state` / `_persist_session_state` 两个存储门面
    **有意留在主文件**（生产侧 `tools.py` 与 3 个测试文件按**主文件路径**导入它们）。

于是本门禁把「允许反向 import」写成**放行 + 三条约束**，而不是简单放行：

  1. 反向依赖只能**按模块别名**取，且 `_pr` **只能取属性、不能被调用**（A4/A5）；
  2. 真要用的名字必须能在会话层里看到 `_pr.<name>` 的**属性访问**（A6）——
     防止「写着 import 了，其实一个 ContextVar 都没读」；
  3. 两个存储门面必须是**晚绑定**（函数体内 `_pr._hydrate_session_state`），
     不许 `from ... import _hydrate_session_state`（D3）——
     后者会让 `tests/test_agent_session_state.py::_patch_store()` 的
     `patch.object(主文件模块, "_hydrate_session_state", …)` **静默失效**。

## 其余失败方向

  · **回流**：把 `ContextVar` / `state_key` 逻辑 / `_DEFAULT_STATE_SCOPE` 抄回薄壳 → B2/F1 红；
  · **漏传**：`resolve_thread_id=` / `registry=` 漏一个 → D1/D2 红（漏传**不报错**，
    只会让作用域算错或状态落在另一个容器里）；
  · **改名**：会话层函数被改名 → A1/E1 红（集合相等 + 一一对应）；
  · **掉契约**：`_last_blue_ocean` 丢 `@property`、`_bind_context` 丢 `@staticmethod`
    或形参顺序变了 → C1/C2/C3 红（调用点是类级 / 位置传参）。

## 不测什么

不测「主文件还有没有 `_sess`」—— 当然有；也不测「会话层有没有 docstring」。
只钉**形态**：谁在哪里、依赖怎么传、契约有没有断。
"""
import ast
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "product_research"
MAIN_PY = MODULE_DIR / "agent_product_research.py"
SESSION_PY = MODULE_DIR / "agent_session.py"

MAIN_MODULE = "modules.product_research.agent_product_research"
SESSION_MODULE = "modules.product_research.agent_session"
SESSION_ALIAS = "_sess"

#: 会话层的**全部**函数（集合相等判据：增删都必须改这里）
SESSION_FUNCS = frozenset({
    "state_scope",
    "state_key",
    "session",
    "hydrate_state",
    "flush_state",
    "last_products",
    "last_blue_ocean",
    "bind_context",
    "session_context_block",
})

#: 主类薄壳 → 它必须委托的模块级函数
SHELL_TO_DELEGATE = {
    "_state_scope": "state_scope",
    "_state_key": "state_key",
    "_session": "session",
    "_hydrate_state": "hydrate_state",
    "_flush_state": "flush_state",
    "_last_products": "last_products",
    "_last_blue_ocean": "last_blue_ocean",
    "_bind_context": "bind_context",
    "_session_context_block": "session_context_block",
}

#: 薄壳体里**禁止**出现的名字 —— 出现即说明领域逻辑又被抄回主类了。
#: · 三个 ContextVar      会话上下文的真源（只由 `bind_context` 写、`state_scope` 读）
#: · 两个存储门面          持久化的真源（薄壳经 `_sess` 转发，不直接引用）
#: · `_DEFAULT_STATE_SCOPE` 本刀已搬进会话层；主文件里连定义都没有了
#: · `SessionStateRegistry` 容器机制只在 `__init__` 构造一次
FORBIDDEN_IN_SHELL = frozenset({
    "_current_context_id",
    "_current_shop_id",
    "_current_user_id",
    "_hydrate_session_state",
    "_persist_session_state",
    "_DEFAULT_STATE_SCOPE",
    "SessionStateRegistry",
})

#: 会话层允许的**非标准库**前缀（其余交给 `sys.stdlib_module_names`）。
#: ★ 含 `modules.product_research`（含主文件）—— 本刀**有意**反向依赖，理由见模块 docstring；
#:   该前缀下**只**放行主文件，其余子模块由 `_is_forbidden_import()` 拦掉。
ALLOWED_IMPORT_PREFIXES = ("core.logger", "modules.product_research")

#: 出现即违规的 import 前缀（**不含** MAIN_MODULE：本刀的唯一例外）
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy", "asyncpg", "psycopg", "redis", "httpx", "requests", "aiohttp",
    "modules.conversation",        # 持久化是**注入的门面**（经 `_pr` 转发），不是 import
    "platforms",                   # 本层不取数
    "ai_infra",
    "langchain_core", "langgraph",  # 本层不算路由、不碰图
)

#: 薄壳行数上限（含 docstring 与装饰器行）。实测最长的是 `_bind_context` 11 行；
#: 留到 18 是给注释余量，同时挡住「逻辑长回来」。
SHELL_MAX_LINES = 18

#: 反向依赖：会话层必须读到的 5 个主文件符号（少一个都说明搬漏/写空）
REVERSE_DEPS = frozenset({
    "_current_context_id",
    "_current_shop_id",
    "_current_user_id",
    "_hydrate_session_state",
    "_persist_session_state",
})

#: 必须传 `resolve_thread_id=self.resolve_thread_id`（回调，不传 self）的薄壳
RESOLVE_CALLBACK_SHELLS = {
    "_state_scope": "state_scope",
    "_state_key": "state_key",
    "_session": "session",
    "_hydrate_state": "hydrate_state",
    "_flush_state": "flush_state",
    "_last_products": "last_products",
    "_last_blue_ocean": "last_blue_ocean",
    "_session_context_block": "session_context_block",
}

#: 必须传 `registry=self._session_states`（实例状态，按值传）的薄壳
REGISTRY_SHELLS = {
    "_session": "session",
    "_hydrate_state": "hydrate_state",
    "_flush_state": "flush_state",
    "_last_products": "last_products",
    "_last_blue_ocean": "last_blue_ocean",
    "_session_context_block": "session_context_block",
}

#: 必须仍是 `@property` 的薄壳（消费方写 `agent._last_blue_ocean`，不带括号）
PROPERTY_SHELLS = frozenset({"_last_blue_ocean"})

#: 必须仍是 `@staticmethod` 的薄壳（测试与 `agent_hitl` 按**类 / 位置**调用）
STATIC_SHELLS = frozenset({"_bind_context"})

#: `_bind_context` 形参顺序即契约（调用点按位置传参）
BIND_CONTEXT_PARAMS = ["context_id", "shop_id", "user_id"]


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


def _module_bound_names(tree: ast.Module) -> set:
    """模块级**绑定的名字**全集（def / class / 赋值 / import 别名）。

    ★ 为什么要含 import 别名：两个存储门面是
      `from modules.conversation import hydrate_state as _hydrate_session_state`
      —— 它们不是 `def`，但同样是**模块级属性**；`patch.object(主文件模块, 名, …)`
      要求这个名字存在。只看 `FunctionDef` 会漏判。
    """
    out: set = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(n, ast.AnnAssign):
            if isinstance(n.target, ast.Name):
                out.add(n.target.id)
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                out.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.asname or a.name.split(".")[0])
    return out


def _import_targets(tree: ast.Module) -> set:
    """本模块 import 的**目标全名**集合。

    · `import a.b`          → `{"a.b"}`
    · `from a.b import c`   → `{"a.b", "a.b.c"}`

    ★ 必须展开 `from a.b import c` 的第二项：只看 `ImportFrom.module` 的话
      「到底反向依赖了哪个子模块」看不出来（第二刀被反向注入抓出的漏洞）。
    """
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


def _is_forbidden_import(target: str) -> bool:
    """`modules.product_research.*` 里**只**放行主文件（本刀唯一例外）。"""
    if target == "modules.product_research":
        return False                        # `from a.b import c` 会产出父包名
    if target.startswith("modules.product_research."):
        return not target.startswith(MAIN_MODULE)
    return any(target.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES)


def _is_std_or_allowed(target: str) -> bool:
    if target.startswith("<relative"):
        return True
    if target.split(".")[0] in sys.stdlib_module_names:
        return True
    return any(target.startswith(p) for p in ALLOWED_IMPORT_PREFIXES)


def _referenced_names(node: ast.AST) -> set:
    """节点子树里出现的**标识符与属性名**全集。

    ★ 不用「只看 `ast.Call`」的口径：「逻辑回流」未必长成调用 ——
      `_ = _DEFAULT_STATE_SCOPE` 这类**引用**同样是回流。
    """
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _referenced_in_body(fn: ast.AST) -> set:
    """★ 只看**函数体的语句**，不含签名与返回标注。

    与 `_referenced_names(fn)` 的区别是必须的：薄壳签名里就有
    `context_id` / `shop_id` / `user_id` 这些形参名，那是**契约声明**不是回流。
    第一版把整棵 `FunctionDef` 丢进去会命中签名 ⇒ 假红。
    """
    out: set = set()
    for stmt in fn.body:
        out |= _referenced_names(stmt)
    return out


def _alias_attr_names(tree: ast.Module, alias: str) -> set:
    """全部 `alias.<attr>` 形式的**属性名**集合（`_pr._current_user_id` → `_current_user_id`）。"""
    out = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name)
                and n.value.id == alias):
            out.add(n.attr)
    return out


def _sess_calls(node: ast.AST) -> set:
    """子树里所有 `_sess.<name>(...)` 调用的 `<name>` 集合。"""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == SESSION_ALIAS):
            out.add(n.func.attr)
    return out


def _call_of(node: ast.AST, attr: str) -> ast.Call | None:
    """子树里第一个 `X.<attr>(...)` 调用节点（找不到返回 None）。"""
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr):
            return n
    return None


def _kwargs_of(node: ast.AST, attr: str) -> set:
    """子树里 `X.<attr>(...)` 调用的**关键字实参名**集合。"""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr):
            out.update(k.arg for k in n.keywords if k.arg)
    return out


def _kwarg_value(node: ast.AST, attr: str, kw: str):
    """子树里 `X.<attr>(...)` 调用的 `kw=` 实参**表达式节点**（找不到返回 None）。"""
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr):
            for k in n.keywords:
                if k.arg == kw:
                    return k.value
    return None


def _self_attr(node) -> str | None:
    """`self.<attr>` → `<attr>`；否则 None。"""
    if (isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"):
        return node.attr
    return None


def _has_decorator(fn: ast.AST, name: str) -> bool:
    return any(isinstance(d, ast.Name) and d.id == name for d in fn.decorator_list)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def session_tree():
    assert SESSION_PY.exists(), f"会话层不存在: {SESSION_PY}"
    return _tree(SESSION_PY)


@pytest.fixture(scope="module")
def main_tree():
    assert MAIN_PY.exists(), f"主文件不存在: {MAIN_PY}"
    return _tree(MAIN_PY)


@pytest.fixture(scope="module")
def shells(main_tree):
    return _methods(_main_class(main_tree))


# --------------------------------------------------------------------------- #
# A · 会话层自身
# --------------------------------------------------------------------------- #

def test_session_module_has_exactly_the_nine_functions(session_tree):
    """集合相等：9 个函数一个不多一个不少（防静默增删）。"""
    got = set(_top_funcs(session_tree))
    assert got == set(SESSION_FUNCS), (
        f"多出来的: {sorted(got - SESSION_FUNCS)}；丢掉的: {sorted(SESSION_FUNCS - got)}"
    )


def test_no_session_function_touches_self(session_tree):
    """★ `self`/`cls` 出现即说明该函数又需要 Agent 实例 ⇒ 显式传参已被破坏。"""
    offenders = []
    for nm in SESSION_FUNCS:
        fn = _top_funcs(session_tree)[nm]
        if any(isinstance(x, ast.Name) and x.id in ("self", "cls") for x in ast.walk(fn)):
            offenders.append(nm)
    assert not offenders, (
        f"这些会话函数开始依赖实例/类状态了，必须改成参数显式传入: {offenders}"
    )


def test_session_layer_imports_are_leaf(session_tree):
    """会话层只允许依赖日志、标准库与**主文件**（反向依赖，见模块 docstring）。

    ★ 与第三/四刀相反：本层**允许** `modules.product_research.agent_product_research`，
      但该前缀下别的子模块（tools / router / agent_hitl / agent_routing / 自己）
      一律禁止 —— 本层是**同层**，不许横向依赖兄弟层。
    """
    targets = _import_targets(session_tree)
    bad = [t for t in targets if _is_forbidden_import(t)]
    assert not bad, (
        f"会话层出现了禁止的依赖: {bad} —— "
        f"本层唯一允许的 modules.product_research.* 是主文件（取 ContextVar/门面）；"
        f"持久化/取数必须由调用方传入"
    )

    unexpected = [t for t in targets if not _is_std_or_allowed(t)]
    assert not unexpected, (
        f"会话层新增了未登记的非标准库依赖: {unexpected}；"
        f"若确实需要，请同时更新 ALLOWED_IMPORT_PREFIXES 并说明理由"
    )


def test_reverse_dep_is_a_module_alias(session_tree):
    """★ 反向依赖必须**按模块别名**绑定，且别名是 `_pr` 且**恰好一次**。

    别名而非 `from ... import <符号>`：后者在 import 时**冻结**符号，
    `patch.object(主文件模块, …)` 再也改不动它（见 D3）。
    """
    hits = [a.asname
            for n in session_tree.body if isinstance(n, ast.ImportFrom)
            and n.module == "modules.product_research"
            for a in n.names if a.name == "agent_product_research"]
    assert hits == ["_pr"], (
        f"`from modules.product_research import agent_product_research as _pr` "
        f"必须恰好一次且别名为 _pr；实际 asname={hits}"
    )


def test_session_module_never_calls_the_main_module(session_tree):
    """★ `_pr` 只能是**模块句柄**：绝不能被当函数调用。

    `_pr` 是主文件模块对象；`_pr(...)` 必然 TypeError。写成这样说明
    作者误以为它是某个可调用对象 —— 且这个错只在运行期某个分支才炸。
    """
    called = [n.lineno for n in ast.walk(session_tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == "_pr"]
    assert not called, f"会话层把 `_pr` 当函数调用了（行号 {called}）"


def test_session_module_reads_state_from_main(session_tree):
    """★ 会话层必须真的读到主文件那 5 个符号（否则「搬空」也能过 A1/A4）。

    少任何一个是**静默**的：`bind_context` 少写一个 ContextVar ⇒ 状态落到别的
    作用域；`hydrate/flush` 少读门面 ⇒ 持久化整条链断在会话层。
    """
    used = _alias_attr_names(session_tree, "_pr")
    missing = REVERSE_DEPS - used
    assert not missing, (
        f"会话层没有通过 `_pr.` 读到这些主文件符号: {sorted(missing)} —— "
        f"它们是有意留在主文件的真源，必须经 `_pr.` 晚绑定引用"
    )


# --------------------------------------------------------------------------- #
# B · 主文件薄壳：真的委托了吗
# --------------------------------------------------------------------------- #

def test_main_shells_really_delegate(shells):
    """★ 每个薄壳都必须出现对应 `_sess.<函数>` 调用（缺此条空壳也能过）。"""
    missing = {}
    for shell_name, sess_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        called = _sess_calls(shells[shell_name])
        if sess_name not in called:
            missing[shell_name] = sorted(called) or "（没调用 _sess 任何函数）"
    assert not missing, f"这些薄壳没有委托给会话层: {missing}"


def test_main_shells_have_no_domain_logic(shells):
    """薄壳里不许出现领域原语（ContextVar / 存储门面 / 默认作用域常量）。"""
    bad = {}
    for shell_name in SHELL_TO_DELEGATE:
        hit = _referenced_in_body(shells[shell_name]) & FORBIDDEN_IN_SHELL
        if hit:
            bad[shell_name] = sorted(hit)
    assert not bad, f"薄壳里出现了领域逻辑（应留在 agent_session.py）: {bad}"


def test_main_shells_stay_small(shells):
    """薄壳行数上限 —— 挡住「逻辑长回来」。"""
    over = {}
    for shell_name in SHELL_TO_DELEGATE:
        fn = shells[shell_name]
        n = fn.end_lineno - fn.lineno + 1
        if n > SHELL_MAX_LINES:
            over[shell_name] = n
    assert not over, f"薄壳超过 {SHELL_MAX_LINES} 行（逻辑回流了？）: {over}"


def test_no_session_calls_outside_the_shells(main_tree):
    """★ 主文件对 `_sess.*` 的调用必须**只**出现在那 9 个薄壳里。

    在别处直接调（例如某个 `_analyze_*` 里自己调 `_sess.last_products`）
    会**绕过薄壳** —— 而薄壳正是 monkeypatch 与形态门禁共同盯着的通道。
    """
    shell_names = set(SHELL_TO_DELEGATE)
    stray = {}
    for name, fn in _methods(_main_class(main_tree)).items():
        called = _sess_calls(fn)
        if called and name not in shell_names:
            stray[name] = sorted(called)
    assert not stray, f"这些方法在 9 个薄壳之外调用了会话层: {stray}"


# --------------------------------------------------------------------------- #
# C · 静态契约（property / staticmethod / 位置传参）
# --------------------------------------------------------------------------- #

def test_last_blue_ocean_shell_keeps_property(shells):
    """★ `_last_blue_ocean` 必须仍是 `@property`。

    消费方（`tests/test_product_research_candidate_flow.py` 15 处、
    `agent_hitl` 等）写的是 `agent._last_blue_ocean["products"]` —— 不带括号。
    去掉 `@property` 后拿到的是**绑定方法**，`["products"]` 直接 TypeError。
    """
    bad = [nm for nm in PROPERTY_SHELLS
           if nm in shells and not _has_decorator(shells[nm], "property")]
    assert not bad, f"这些薄壳丢了 `@property`（消费方按属性取，会 TypeError）: {bad}"


def test_bind_context_shell_keeps_staticmethod(shells):
    """★ `_bind_context` 必须仍是 `@staticmethod`。

    `agent_hitl.resume_approval` 与两个入口都按**类 / 位置**调用它；
    去掉 staticmethod ⇒ 收到未绑定 `self` ⇒ 参数整体错位（Shop 变成 context_id）。
    """
    bad = [nm for nm in STATIC_SHELLS
           if nm in shells and not _has_decorator(shells[nm], "staticmethod")]
    assert not bad, f"这些薄壳丢了 `@staticmethod`（类级/位置调用会错位）: {bad}"


def test_bind_context_param_order_is_contract(shells):
    """★ `_bind_context` 形参顺序即契约，且调用点必须**按位置**传。

    形参顺序决定了「`shop_id` 到底绑到哪个 ContextVar」。一旦改成关键字或换序，
    最可能的后果是把**原始请求头**写进 `_current_shop_id` —— 那正是
    `_current_shop_id` 注释里记的那次跨租户写入事故。
    """
    fn = shells["_bind_context"]
    got = [a.arg for a in fn.args.args]
    assert got == BIND_CONTEXT_PARAMS, (
        f"`_bind_context` 形参顺序变了: {got}（必须 {BIND_CONTEXT_PARAMS}）"
    )
    assert _kwargs_of(fn, "bind_context") == set(), (
        "`_bind_context` 薄壳改成关键字传参了 —— 位置契约失效"
    )
    call = _call_of(fn, "bind_context")
    assert call is not None, "`_bind_context` 薄壳没调用 `_sess.bind_context`"
    argv = [ast.unparse(a) for a in call.args]
    assert argv == BIND_CONTEXT_PARAMS, (
        f"`_sess.bind_context(...)` 的实参顺序/个数变了: {argv}"
    )


# --------------------------------------------------------------------------- #
# D · 依赖**显式**：漏传不报错，只会静默算错
# --------------------------------------------------------------------------- #

def test_shells_pass_resolve_thread_id_as_self_callback(shells):
    """★ 8 个薄壳必须传 `resolve_thread_id=self.resolve_thread_id`。

    ★ 为什么必须是 `self.` 查找而不是模块函数：`resolve_thread_id` 来自
      `BaseAgent`，测试可能打在**实例**上；且本层只允许**一处**算作用域键
      （`tests/test_agent_session_state.py` 的「唯一调用点」门禁）。
      漏传 ⇒ TypeError（较好）；传错对象 ⇒ 作用域漂移，「历史还在、槽位没了」。
    """
    bad = {}
    for shell_name, sess_name in RESOLVE_CALLBACK_SHELLS.items():
        val = _kwarg_value(shells[shell_name], sess_name, "resolve_thread_id")
        if val is None:
            bad[shell_name] = "未传 resolve_thread_id="
            continue
        attr = _self_attr(val)
        if attr != "resolve_thread_id":
            bad[shell_name] = f"传的不是 self.resolve_thread_id（{ast.unparse(val)}）"
    assert not bad, f"这些薄壳的 resolve_thread_id 传法不对: {bad}"


def test_shells_pass_registry_as_instance_value(shells):
    """★ 6 个薄壳必须传 `registry=self._session_states`（**按值**传实例状态）。

    漏传 / 传新建的注册表 ⇒ 每次调用一份新容器 ⇒ **状态直接蒸发**
    （既不报错也不落库，表现为「刚补的槽位下一轮又不见了」）。
    """
    bad = {}
    for shell_name, sess_name in REGISTRY_SHELLS.items():
        val = _kwarg_value(shells[shell_name], sess_name, "registry")
        if val is None:
            bad[shell_name] = "未传 registry="
            continue
        attr = _self_attr(val)
        if attr != "_session_states":
            bad[shell_name] = f"传的不是 self._session_states（{ast.unparse(val)}）"
    assert not bad, f"这些薄壳的 registry 传法不对: {bad}"


def test_store_facade_patch_channel_is_late_bound(session_tree):
    """★★ 存储门面必须是**晚绑定**：函数体内 `_pr._hydrate_session_state`。

    `tests/test_agent_session_state.py::_patch_store()` 用
    `patch.object(主文件模块, "_hydrate_session_state", 桩)` 打桩。
    若会话层写成 `from modules.product_research.agent_product_research import
    _hydrate_session_state`，那个名字在 import 时就**冻结**了 —— 补丁静默失效，
    测试照绿，但**测的不是真路径**（本刀最容易埋的坑，故单列一条）。
    """
    frozen = [a.asname or a.name
              for n in ast.walk(session_tree) if isinstance(n, ast.ImportFrom)
              for a in n.names if a.name in ("_hydrate_session_state", "_persist_session_state")]
    assert not frozen, (
        f"会话层直接 import 了存储门面 {frozen} —— 必须改成 `_pr.` 晚绑定，"
        f"否则 `_patch_store()` 的补丁静默失效"
    )

    used = _alias_attr_names(session_tree, "_pr")
    for facade in ("_hydrate_session_state", "_persist_session_state"):
        assert facade in used, (
            f"会话层没有晚绑定 `_pr.{facade}` —— 持久化链断了"
        )


# --------------------------------------------------------------------------- #
# E · 两端一一对应
# --------------------------------------------------------------------------- #

def test_shell_to_session_names_match_one_to_one(session_tree, shells):
    """薄壳 → 会话层函数必须**一一对应**且两边都存在（改名即红）。"""
    sess_names = set(_top_funcs(session_tree))
    for shell_name, sess_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        assert sess_name in sess_names, f"会话层丢掉了函数 {sess_name}"
    assert len(set(SHELL_TO_DELEGATE.values())) == len(SHELL_TO_DELEGATE), (
        "SHELL_TO_DELEGATE 里有重复的委托目标（两个薄壳指同一个函数？）"
    )
    assert set(SHELL_TO_DELEGATE.values()) == set(SESSION_FUNCS), (
        "9 个委托目标与 SESSION_FUNCS 不等 —— 有函数只被登记却没被委托，或反之"
    )


# --------------------------------------------------------------------------- #
# F · 常量搬走 / 反向依赖原地不动
# --------------------------------------------------------------------------- #

def test_default_state_scope_moved_out_of_main(session_tree, main_tree):
    """★ `_DEFAULT_STATE_SCOPE` 必须**只**住在会话层，且值仍是 `"_default"`。

    它原先在主文件模块级；本刀随唯一消费方 `state_scope` 一起搬走。
    若主文件里又出现定义 ⇒ 两个真源（改一处漏一处 ⇒ 有会话/无会话两条路径
    撞进同一个容器，只在单会话场景下不显形）。
    """
    main_bound = _module_bound_names(main_tree)
    assert "_DEFAULT_STATE_SCOPE" not in main_bound, (
        "主文件又定义了 `_DEFAULT_STATE_SCOPE` —— 常量搬走失败（两个真源）"
    )

    val = None
    for n in session_tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "_DEFAULT_STATE_SCOPE":
                    val = n.value
    assert val is not None, "会话层没有定义模块级 `_DEFAULT_STATE_SCOPE`"
    assert isinstance(val, ast.Constant) and val.value == "_default", (
        f"`_DEFAULT_STATE_SCOPE` 的值变了: {ast.unparse(val)}"
    )


def test_main_still_owns_contextvars_and_store_facades(main_tree):
    """★ 反向依赖必须**原地不动**：3 个 ContextVar + 2 个存储门面仍在主文件模块级。

    它们有三个外部消费方按**主文件路径**导入（`modules/product_research/tools.py`
    与 3 个测试文件），搬走等于替第三方改契约；且 `_patch_store()` 的
    `patch.object(主文件模块, …)` 也要求这两个名字挂在主文件模块上。
    """
    bound = _module_bound_names(main_tree)
    missing = REVERSE_DEPS - bound
    assert not missing, (
        f"主文件不再绑定这些反向依赖: {sorted(missing)} —— "
        f"它们是 tools.py 与 3 个测试文件按主文件路径导入的真源，不能跟着搬"
    )

# -*- coding: utf-8 -*-
"""P0-6 「HITL 审批层」形态门禁（第三刀）。

## 本刀与前两刀的关系

第一刀（`agent_helpers.py`）摘走**不碰实例状态**的方法，判据是「函数体里没有 `self`」，
于是能用**继承**（mixin）做到调用点零改动。
第二刀（`agent_analyzers.py`）摘走 4 个 `_analyze_*`，改用**显式传参**。
本刀同法摘走 HITL 块的 5 个函数（226 行），并额外钉住一件事：

    **薄壳必须保留 `self.` 查找，且必须把能力作为 callable 显式传进去。**

两条都是「静默失败」，靠人记不住：

  · 薄壳写成 `_hitl.detect_pending_approval(..., get_router=None)` —— 不报错，
    只是永远探不到待审批（审批卡再也不弹，用户以为「系统没让我确认」）；
  · 薄壳绕过 `self._detect_pending_approval` 直接引用模块函数 ——
    `tests/test_thinking_trace.py` 打在**实例**上的 monkeypatch 静默失效。

## 三个失败方向

  · **回流**：把 `Command(resume=...)` / `AgentResponse(...)` 写回壳里 → E 档红；
  · **漏传**：加参数时漏了 `get_router=` / `hydrate_state=` → G/H 档红；
  · **改名**：hitl 层函数被改名 → A/I 档红（集合相等 + 一一对应）。

## 不测什么

不测「主文件还有没有 `_hitl`」—— 当然有；也不测「hitl 层有没有 docstring」。
只钉**形态**：谁在哪里、依赖怎么传、契约有没有断。
"""
import ast
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "product_research"
MAIN_PY = MODULE_DIR / "agent_product_research.py"
HITL_PY = MODULE_DIR / "agent_hitl.py"

MAIN_MODULE = "modules.product_research.agent_product_research"
HITL_MODULE = "modules.product_research.agent_hitl"
HITL_ALIAS = "_hitl"

#: HITL 层的**全部**函数（集合相等判据：增删都必须改这里）
HITL_FUNCS = frozenset({
    "pending_approval_from_interrupt",
    "build_resume_payload",
    "unwrap_hitl_tool_output",
    "detect_pending_approval",
    "resume_approval",
})

#: 主类薄壳 → 它必须委托的模块级函数
SHELL_TO_DELEGATE = {
    "_pending_approval_from_interrupt": "pending_approval_from_interrupt",
    "_build_resume_payload": "build_resume_payload",
    "_unwrap_hitl_tool_output": "unwrap_hitl_tool_output",
    "_detect_pending_approval": "detect_pending_approval",
    "resume_approval": "resume_approval",
}

#: 薄壳体里**禁止**出现的名字 —— 出现即说明领域逻辑又被抄回主类了。
#: · `Command`       resume 的图原语（只在 hitl 层用）
#: · `AgentResponse` 审批响应构造（只在 hitl 层用）
#: · `loads`         解包逻辑（`json.loads`，只在 hitl 层用）
#: · `getattr`       Interrupt 字段探测（只在 hitl 层用）
FORBIDDEN_IN_SHELL = frozenset({"Command", "AgentResponse", "loads", "getattr"})

#: HITL 层允许的**非标准库**前缀（其余交给 `sys.stdlib_module_names`）
ALLOWED_IMPORT_PREFIXES = ("core.logger", "langgraph.types")

#: 出现即违规的 import 前缀
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy", "asyncpg", "psycopg", "redis", "httpx", "requests", "aiohttp",
    MAIN_MODULE,                            # 不许反向回流主文件（会成环）
    HITL_MODULE,                            # 不许自己 import 自己（冗余）
    "modules.conversation",                 # 持久化是**注入的回调**，不是 import
    "modules.product_research.tools",
    "modules.product_research.router",
    "platforms",                            # 本层不取数
    "ai_infra",
    "langchain_core",                       # 只用 langgraph.types.Command
)

#: 薄壳行数上限（含 docstring 与装饰器行）。实测最长的是 `resume_approval` 29 行；
#: 留到 32 是给注释余量，同时挡住「逻辑长回来」。
SHELL_MAX_LINES = 32

#: `resume_approval` 必须显式传下去的 5 个能力（漏传**不会报错**）
RESUME_REQUIRED_CALLABLES = frozenset({
    "get_router", "bind_context", "hydrate_state", "compose_reply", "detect_pending",
})

#: 必须仍是 `@staticmethod` 的三个薄壳 —— 测试按**类**调用它们
STATIC_SHELLS = frozenset({
    "_pending_approval_from_interrupt",
    "_build_resume_payload",
    "_unwrap_hitl_tool_output",
})


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
    """本模块 import 的**目标全名**集合。

    · `import a.b`          → `{"a.b"}`
    · `from a.b import c`   → `{"a.b", "a.b.c"}`
    · `from .x import y`    → `{"<relative:1:x>"}`

    ★ 必须展开 `from a.b import c` 的第二项：只看 `ImportFrom.module` 的话，
      `from modules.product_research import agent_hitl` 只留下包名，
      「反向依赖了哪个子模块」看不出来（该漏洞在第二刀被反向注入 C2 抓出）。
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


def _is_std_or_allowed(target: str) -> bool:
    if target.startswith("<relative"):
        return True
    if target.split(".")[0] in sys.stdlib_module_names:
        return True
    return any(target.startswith(p) for p in ALLOWED_IMPORT_PREFIXES)


def _referenced_names(node: ast.AST) -> set:
    """节点子树里出现的**标识符与属性名**全集。

    ★ 不用「只看 `ast.Call`」的口径：「逻辑回流」未必长成调用 ——
      `_ = Command`、`x = AgentResponse` 这类**引用**同样是回流（第二刀 B1 的教训）。
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

    与 `_referenced_names(fn)` 的区别是必须的，不是风格：薄壳的返回标注是
    `-> AgentResponse`，那是**契约声明**（测试按它取类型），不是「逻辑回流」。
    第一版把整棵 `FunctionDef` 丢进去，于是每个薄壳都命中 `AgentResponse` ⇒ 假红。
    """
    out: set = set()
    for stmt in fn.body:
        out |= _referenced_names(stmt)
    return out


def _hitl_calls(node: ast.AST) -> set:
    """子树里所有 `_hitl.<name>(...)` 调用的 `<name>` 集合。"""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == HITL_ALIAS):
            out.add(n.func.attr)
    return out


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


def _is_static(fn: ast.AST) -> bool:
    return any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in fn.decorator_list)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def hitl_tree():
    assert HITL_PY.exists(), f"HITL 层不存在: {HITL_PY}"
    return _tree(HITL_PY)


@pytest.fixture(scope="module")
def main_tree():
    assert MAIN_PY.exists(), f"主文件不存在: {MAIN_PY}"
    return _tree(MAIN_PY)


@pytest.fixture(scope="module")
def shells(main_tree):
    return _methods(_main_class(main_tree))


# --------------------------------------------------------------------------- #
# A · HITL 层自身
# --------------------------------------------------------------------------- #

def test_hitl_module_has_exactly_the_five_functions(hitl_tree):
    """集合相等：5 个函数一个不多一个不少（防静默增删）。"""
    got = set(_top_funcs(hitl_tree))
    assert got == set(HITL_FUNCS), (
        f"多出来的: {sorted(got - HITL_FUNCS)}；丢掉的: {sorted(HITL_FUNCS - got)}"
    )


def test_no_hitl_function_touches_self(hitl_tree):
    """★ `self`/`cls` 出现即说明该函数又需要 Agent 实例 ⇒ 显式传参已被破坏。"""
    offenders = []
    for nm in HITL_FUNCS:
        fn = _top_funcs(hitl_tree)[nm]
        if any(isinstance(x, ast.Name) and x.id in ("self", "cls") for x in ast.walk(fn)):
            offenders.append(nm)
    assert not offenders, (
        f"这些 HITL 函数开始依赖实例/类状态了，必须改成参数显式传入: {offenders}"
    )


def test_hitl_layer_imports_are_leaf(hitl_tree):
    """HITL 层只允许依赖日志、`langgraph.types`、同层数据模型与标准库。"""
    targets = _import_targets(hitl_tree)
    bad = [t for t in targets if any(t.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES)]
    assert not bad, (
        f"HITL 层出现了禁止的依赖: {bad} —— "
        f"持久化/路由/取数必须作为 callable 由调用方传入，不能 import"
    )

    unexpected = [t for t in targets if not _is_std_or_allowed(t)]
    assert not unexpected, (
        f"HITL 层新增了未登记的非标准库依赖: {unexpected}；"
        f"若确实需要，请同时更新 ALLOWED_IMPORT_PREFIXES 并说明理由"
    )


# --------------------------------------------------------------------------- #
# B/C · 主文件薄壳：真的委托了吗
# --------------------------------------------------------------------------- #

def test_main_shells_really_delegate(shells):
    """★ 每个薄壳都必须出现对应 `_hitl.<函数>` 调用（缺此条空壳也能过）。"""
    missing = {}
    for shell_name, hitl_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        called = _hitl_calls(shells[shell_name])
        if hitl_name not in called:
            missing[shell_name] = sorted(called) or "（没调用 _hitl 任何函数）"
    assert not missing, f"这些薄壳没有委托给 HITL 层: {missing}"


def test_main_shells_have_no_domain_logic(shells):
    """薄壳里不许出现领域原语 —— 出现即说明逻辑又被抄回主类了。"""
    bad = {}
    for shell_name in SHELL_TO_DELEGATE:
        hit = _referenced_in_body(shells[shell_name]) & FORBIDDEN_IN_SHELL
        if hit:
            bad[shell_name] = sorted(hit)
    assert not bad, f"薄壳里出现了领域逻辑（应留在 agent_hitl.py）: {bad}"


def test_main_shells_stay_small(shells):
    """薄壳行数上限 —— 挡住「逻辑长回来」。"""
    over = {}
    for shell_name in SHELL_TO_DELEGATE:
        fn = shells[shell_name]
        n = fn.end_lineno - fn.lineno + 1
        if n > SHELL_MAX_LINES:
            over[shell_name] = n
    assert not over, f"薄壳超过 {SHELL_MAX_LINES} 行（逻辑回流了？）: {over}"


# --------------------------------------------------------------------------- #
# D/E · 静态契约（测试按**类**调用）与 monkeypatch 通道
# --------------------------------------------------------------------------- #

def test_static_shells_keep_staticmethod(shells):
    """★ 三个薄壳必须仍是 `@staticmethod`。

    `tests/test_hitl_approval_flow.py` 有 5 处 `ProductResearchAgent._build_resume_payload(...)`
    这类**类级**调用；去掉 staticmethod ⇒ 收到未绑定 `self` ⇒ TypeError。
    """
    bad = [nm for nm in STATIC_SHELLS
           if nm in shells and not _is_static(shells[nm])]
    assert not bad, f"这些薄壳丢了 `@staticmethod`（类级调用会 TypeError）: {bad}"


def test_shells_use_self_lookup_for_monkeypatch(shells):
    """★ `resume_approval` 薄壳必须传 `detect_pending=self._detect_pending_approval`。

    `tests/test_thinking_trace.py` 用 `monkeypatch.setattr(agent, "_detect_pending_approval", ...)`
    打在**实例**上 —— 补丁替换的就是 `self.` 查找到的那个属性。
    若薄壳直接引用模块函数，补丁静默失效（测试照绿，但测的不是真路径）。
    """
    val = _kwarg_value(shells["resume_approval"], "resume_approval", "detect_pending")
    assert isinstance(val, ast.Attribute), (
        "`detect_pending=` 不是属性访问 ⇒ 实例级 monkeypatch 会失效"
    )
    assert isinstance(val.value, ast.Name) and val.value.id == "self", (
        "`detect_pending=` 必须走 `self.` 查找，否则实例级 monkeypatch 失效"
    )
    assert val.attr == "_detect_pending_approval", (
        f"`detect_pending=` 绑的不是 `_detect_pending_approval`：self.{val.attr}"
    )


# --------------------------------------------------------------------------- #
# F/G · 依赖**显式**：漏传不报错，只会静默降级
# --------------------------------------------------------------------------- #

def test_resume_shell_passes_all_five_callables(shells):
    """★ `resume_approval` 薄壳必须显式传 5 个能力。

    漏 `get_router=` ⇒ 初次调用即 TypeError（较好）；
    漏 `bind_context=` / `hydrate_state=` ⇒ **静默**：续跑时 ContextVar 是空的，
    被中断的工具在另一个作用域里找会话状态（「第 1 个」解析不出来）。
    """
    got = _kwargs_of(shells["resume_approval"], "resume_approval")
    missing = RESUME_REQUIRED_CALLABLES - got
    assert not missing, (
        f"薄壳漏传了 {sorted(missing)}；这些依赖是 callable，漏传不会报错只会静默降级"
    )


def test_detect_shell_passes_get_router(shells):
    """`_detect_pending_approval` 薄壳必须传 `get_router=`（否则恒返回 None）。"""
    got = _kwargs_of(shells["_detect_pending_approval"], "detect_pending_approval")
    assert "get_router" in got, f"探测薄壳没传 get_router（实参名: {sorted(got)}）"


# --------------------------------------------------------------------------- #
# H/I · 两端一一对应 / 主文件不再持有图原语
# --------------------------------------------------------------------------- #

def test_no_hitl_calls_outside_the_shells(main_tree):
    """★ 主文件对 `_hitl.*` 的调用必须**只**出现在那 5 个薄壳里。

    在别处直接调（例如 `_stream_via_tools` 里自己调 `_hitl.detect_pending_approval`）
    会**绕过薄壳** —— 而薄壳正是 monkeypatch 与形态门禁共同盯着的通道：
    测试把补丁打在**实例**上，绕过 `self.` 的调用看不见它。
    """
    shell_names = set(SHELL_TO_DELEGATE)
    stray = {}
    for name, fn in _methods(_main_class(main_tree)).items():
        called = _hitl_calls(fn)
        if called and name not in shell_names:
            stray[name] = sorted(called)
    assert not stray, f"这些方法在 5 个薄壳之外调用了 HITL 层: {stray}"


def test_shell_to_hitl_names_match_one_to_one(hitl_tree, shells):
    """薄壳 → HITL 函数必须**一一对应**且两边都存在（改名即红）。"""
    hitl_names = set(_top_funcs(hitl_tree))
    for shell_name, hitl_name in SHELL_TO_DELEGATE.items():
        assert shell_name in shells, f"主类丢掉了薄壳 {shell_name}"
        assert hitl_name in hitl_names, f"HITL 层丢掉了函数 {hitl_name}"
    assert len(set(SHELL_TO_DELEGATE.values())) == len(SHELL_TO_DELEGATE), (
        "SHELL_TO_DELEGATE 里有重复的委托目标（两个薄壳指同一个函数？）"
    )


def test_main_no_longer_uses_command(main_tree):
    """★ `Command`（图 resume 原语）必须只住在 HITL 层。

    它原先由主文件 import 且**只有一个消费点**（`resume_approval` 里的
    `graph.ainvoke(Command(resume=payload))`）。该消费点搬走后 import 就是死代码；
    若它又出现在主文件里，说明 resume 逻辑被抄回去了。
    """
    hits = _referenced_names(main_tree) & {"Command"}
    assert not hits, "主文件又出现了 `Command` —— resume 逻辑回流了（应只在 agent_hitl.py）"

    hitl_targets = _import_targets(_tree(HITL_PY))
    assert any(t.startswith("langgraph.types") for t in hitl_targets), (
        "HITL 层没有 import langgraph.types —— resume 原语失去了唯一住所"
    )

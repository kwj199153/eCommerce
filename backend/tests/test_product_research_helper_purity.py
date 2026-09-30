# -*- coding: utf-8 -*-
"""P0-6 「领域纯逻辑层」形态门禁。

## 这道门禁守的是什么

第 335 轮把 `agent_product_research.py` 判为 **God Class**（2375 行 / 56 个方法，
跨 272-2646 行；P0-6 原判「1358-2646 是一个 1289 行的单方法」经实测**不成立**，
最大方法只有 131 行）。真正可拆的第一刀是：把那批**不依赖实例状态**的方法
摘成一个叶子模块。

判据不是「文件变小了」，而是**形态**：

    一个方法该不该住纯逻辑层，看它函数体里有没有 `self`。

这条判据有两个失败方向，两边都要钉：

  ① **回流**：有人为了图省事，把 `self.adapter` / `self._session(...)` 写进
     `agent_helpers.py` 里的某个函数 —— 它立刻不再能从"纯函数层"单测，
     也把「类目映射表」重新绑回 Agent 生命周期。→ 本门禁的 `test_no_self_...` 会红。
  ② **复制**：有人抄一份方法定义回主类（以为"就地改更快"），于是同一逻辑
     有了两份实现 —— 正是本仓反复踩的「同一能力两份实现，至少一份永远测不到」。
     → 本门禁的 `test_main_class_no_longer_defines_...` 会红。

## 为什么还要钉 re-export

`tests/test_product_research_blue_ocean.py` 与
`tests/test_product_research_intent_routing.py` 按**原模块路径**导入
`_TRENDING_KEYWORDS` / `_ASIN_RE`。外移后必须继续能从这里取到，
且必须是**同一对象**（重新定义一份常量等于又造了第二份真源）。
"""
import ast
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "product_research"
MAIN_PY = MODULE_DIR / "agent_product_research.py"
HELPERS_PY = MODULE_DIR / "agent_helpers.py"

HELPER_CLASS = "ResearchHelpersMixin"

#: 纯逻辑层的**全部**函数 —— 集合相等判据（增删都必须改这里，改不了偷偷漂移）
PURE_FUNCS = frozenset({
    "_extract_category",
    "_generate_search_keywords",
    "_calculate_opportunity_score",
    "_generate_reason",
    "_estimate_price_range",
    "_estimate_margin",
    "_generate_improvement_suggestions",
    "_extract_product_info",
    "_extract_asin",
    "_extract_multiple_asins",
    "_extract_ordinal",
})

#: 纯逻辑层允许的**唯一**非标准库前缀。
#: `platforms.base` 只是为了 `KeywordData` 的类型标注 —— 它是叶子层，
#: 不 import 任何 adapter / 客户端 / 数据库。
#: （标准库不靠手写名单，直接用 `sys.stdlib_module_names` 判 —— 手写名单
#:   一定会漏，而漏了会把 `re` / `math` 这种正当依赖误报成违规。）
ALLOWED_IMPORT_PREFIXES = ("platforms.base",)

#: 出现即违规的 import 前缀（数据库 / HTTP / Agent 自身 / 业务模块）
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy", "asyncpg", "psycopg", "redis", "httpx", "requests", "aiohttp",
    "modules.product_research.agent_product_research",
    "platforms.amazon", "langchain", "langgraph",
)


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_bytes().decode("utf-8"))


def _funcs(node: ast.AST):
    return [n for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _import_targets(tree: ast.Module) -> set:
    """本模块 import 的**目标全名**集合。

    · `import a.b`          → `{"a.b"}`
    · `from a.b import c`   → `{"a.b", "a.b.c"}`
    · `from .x import y`    → `{"<relative:1:x>"}`

    ★ 为什么必须展开 `from a.b import c` 的第二项：
      `from modules.product_research import agent_analyzers` 的 `ImportFrom.module`
      只有 `modules.product_research` —— 只看 module 名，就看不到「反向依赖了
      哪个子模块」。本判据的旧版（只收 `module`）正是这么漏的。
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


def _relative_imports_of(tree: ast.Module, module_name: str) -> list:
    """本文件里 `from .<module_name> import ...` 的语句（相对 import 无包前缀）。"""
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.level and n.module == module_name]


@pytest.fixture(scope="module")
def helper_tree():
    assert HELPERS_PY.exists(), f"纯逻辑层模块不存在: {HELPERS_PY}"
    return _tree(HELPERS_PY)


# --------------------------------------------------------------------------- #
# A 纯逻辑层自身
# --------------------------------------------------------------------------- #

def test_helper_module_has_exactly_the_pure_functions(helper_tree):
    """集合相等：11 个纯函数一个不多一个不少（防静默增删）。"""
    got = {n.name for n in _funcs(helper_tree)}
    assert got == set(PURE_FUNCS), (
        f"多出来的: {sorted(got - PURE_FUNCS)}；丢掉的: {sorted(PURE_FUNCS - got)}"
    )


def test_no_function_in_helper_layer_touches_self(helper_tree):
    """`self` 出现即说明该函数需要 Agent 实例 ⇒ 它不该住这一层。"""
    offenders = []
    for fn in _funcs(helper_tree):
        if any(isinstance(x, ast.Name) and x.id == "self" for x in ast.walk(fn)):
            offenders.append(fn.name)
    assert not offenders, (
        f"这些函数开始依赖实例状态了，必须搬回主类或显式传参: {offenders}"
    )


def test_only_extract_ordinal_may_use_cls(helper_tree):
    """`cls` 只允许 `_extract_ordinal` 用（读本类 `_CN_NUM` 常量表）。

    若别处也开始用 `cls`，说明纯逻辑层正在拿「类」当全局命名空间 ——
    改成模块级常量更直白。
    """
    users = [fn.name for fn in _funcs(helper_tree)
             if any(isinstance(x, ast.Name) and x.id == "cls" for x in ast.walk(fn))]
    assert users == ["_extract_ordinal"], f"意外的 cls 使用者: {users}"


def test_helper_layer_imports_stay_leaf(helper_tree):
    """纯逻辑层必须保持叶子：不连库、不发请求、不反向 import Agent。

    「是不是标准库」交给 `sys.stdlib_module_names` 判（Python 3.10+），
    不手写标准库名单 —— 手写必漏，而漏掉会把 `re` / `math` 这类正当依赖
    误报成违规，逼出「往白名单里堆词」的坏习惯。
    """
    targets = _import_targets(helper_tree)
    bad = [t for t in targets if any(t.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES)]
    # ★ 相对形式单独判：`from .agent_product_research import X` 的 `ImportFrom.module`
    #   只有 `"agent_product_research"`（丢了包前缀），前缀匹配抓不到它。
    bad += [f"<relative to {n.module}>" for n in
            _relative_imports_of(helper_tree, "agent_product_research")]
    assert not bad, f"纯逻辑层出现了禁止的依赖: {bad}"

    unexpected = [t for t in targets if not _is_std_or_allowed(t)]
    assert not unexpected, (
        f"纯逻辑层新增了未登记的非标准库依赖: {unexpected}；"
        f"若确实需要，请同时更新 ALLOWED_IMPORT_PREFIXES 并说明理由"
    )


# --------------------------------------------------------------------------- #
# B 主文件侧：真外移（而不是复制）
# --------------------------------------------------------------------------- #

def test_main_class_no_longer_defines_pure_functions():
    """★ 反向方向：主类里**不得**再出现这 11 个 `def`。

    若这里红了，几乎总是「复制粘贴回主类」——那会让同一逻辑有两份实现，
    两份中的一份永远测不到。
    """
    tree = _tree(MAIN_PY)
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ProductResearchAgent"), None)
    assert cls is not None, "主文件里找不到 ProductResearchAgent"
    own = {n.name for n in cls.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    dup = own & set(PURE_FUNCS)
    assert not dup, f"这些纯函数又被定义回主类了（应只在 agent_helpers.py 有一份）: {sorted(dup)}"


def test_main_class_inherits_the_helper_mixin():
    """主类必须**继承** mixin —— 这是「调用点零改动」的来源。"""
    tree = _tree(MAIN_PY)
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ProductResearchAgent"), None)
    assert cls is not None
    bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
    assert HELPER_CLASS in bases, (
        f"ProductResearchAgent 的基类里没有 {HELPER_CLASS}（实得 {sorted(bases)}）"
    )


def test_main_module_still_reexports_the_moved_constants():
    """两个常量必须继续能从**原模块路径**取到，且指向 helper 里的同一个对象。

    消费方是测试（`test_product_research_blue_ocean.py` /
    `test_product_research_intent_routing.py`）；重新定义一份常量
    等于造第二个真源，所以还要断言 `is` 同一性。
    """
    tree = _tree(MAIN_PY)
    imported = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "modules.product_research.agent_helpers":
            for a in n.names:
                imported[a.asname or a.name] = a.name
    for name in ("_TRENDING_KEYWORDS", "_ASIN_RE", HELPER_CLASS):
        assert name in imported, (
            f"{name} 没有从 agent_helpers re-export；"
            f"实测已导入: {sorted(imported)}"
        )

    from modules.product_research import agent_helpers as H  # noqa: PLC0415
    from modules.product_research import agent_product_research as M  # noqa: PLC0415
    assert M._ASIN_RE is H._ASIN_RE
    assert M._TRENDING_KEYWORDS is H._TRENDING_KEYWORDS

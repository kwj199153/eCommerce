# -*- coding: utf-8 -*-
"""P0-6 「分析编排层」形态门禁（第二刀）。

## 第一刀与本刀的区别（也是本文件的核心判据）

第一刀（`agent_helpers.py`）摘走的是**不碰实例状态**的方法，判据是「函数体里没有 `self`」，
所以能用**继承**（mixin）做到调用点零改动。

本刀摘走的是 4 个 `_analyze_*` —— 它们**必须**用 adapter 与会话状态。于是选**显式传参**：

    藏进 mixin 基类 ＝ 把耦合从「可以数的参数」变成「看不见的继承链」，
    门禁再也数不出这个类实际依赖什么 —— 那是自欺。

因此本门禁要守的不是「文件变小了」，而是三件可机检的事：

  ① **逻辑真的搬走了**：主类那 4 个方法体里不许再有领域构造与取数调用；
  ② **真的委托了**：方法体里必须出现对应 `analyze_*` 的调用；
  ③ **依赖真的显式**：`blue_ocean` 壳里必须写出 `session=` / `structured_llm=` /
     `system_prompt=` 三个关键字参数 —— 少传一个**不会报错**，只会静默降级
     （少 `session` ⇒ 「把第 1 个加进选品库」解析不出目标；少 `structured_llm`
     ⇒ LLM 增强悄悄消失）。这种「静默降级」正是本仓反复踩的坑，
     所以要用判据钉住，而不是靠人记得。

## 三个失败方向

  · **回流**：有人为了图快，把 `adapter.get_keyword_data(...)` 写回壳里 → A 档红；
  · **复制**：有人把整个方法体抄回主类 → A 档红（构造 + 取数同时出现）；
  · **漏传**：有人加参数时漏了一个 → E 档红。

## 不测什么

不测「主类还有没有 `self.adapter`」—— 它当然有，作为**参数传出去**是正当的。
判据只禁**属性链** `self.adapter.<attr>`（那才是取数）。
"""
import ast
import pathlib
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULE_DIR = BACKEND / "modules" / "product_research"
MAIN_PY = MODULE_DIR / "agent_product_research.py"
ANALYZERS_PY = MODULE_DIR / "agent_analyzers.py"
MODELS_PY = MODULE_DIR / "agent_models.py"

MAIN_MODULE = "modules.product_research.agent_product_research"

#: 分析编排层的**全部**函数（集合相等判据：增删都必须改这里）
ANALYZER_FUNCS = frozenset({
    "analyze_blue_ocean",
    "analyze_profit",
    "analyze_pain_points",
    "analyze_competitors",
})

#: 主类薄壳 → 它必须委托的模块级函数
SHELL_TO_DELEGATE = {
    "_analyze_blue_ocean": "analyze_blue_ocean",
    "_analyze_profit": "analyze_profit",
    "_analyze_pain_points": "analyze_pain_points",
    "_analyze_competitors": "analyze_competitors",
}

#: 薄壳体里**禁止**出现的领域构造 —— 出现即说明逻辑又被抄回主类了
FORBIDDEN_CONSTRUCTORS = frozenset({
    "BlueOceanOpportunity",
    "ProfitAnalysis",
    "PainPointAnalysis",
    "ProductData",
})

#: 分析编排层允许的**唯一**非标准库前缀（其余交给 `sys.stdlib_module_names`）
ALLOWED_IMPORT_PREFIXES = ("platforms.base", "core.logger")

#: 出现即违规的 import 前缀
FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy", "asyncpg", "psycopg", "redis", "httpx", "requests", "aiohttp",
    MAIN_MODULE,                                  # 不许反向回流主文件（会成环）
    "modules.product_research.agent_analyzers",   # 不许自己 import 自己（冗余）
    "langchain", "langgraph",
    "ai_infra.base_agent",                        # 依赖的是「回调」，不是 BaseAgent
)

#: 模型层的**全部**模型（集合相等判据）
MODEL_NAMES = frozenset({
    "AgentResponse", "BlueOceanOpportunity", "ProfitAnalysis",
    "PainPointAnalysis", "ResearchReport",
})

#: 薄壳行数上限（含 docstring 与装饰器行）。实测最长的是 `_analyze_blue_ocean` 13 行；
#: 留到 20 是为了给注释余量，同时挡住「逻辑长回来」。
SHELL_MAX_LINES = 20


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

    ★ 为什么必须展开 `from a.b import c` 的第二项（本门禁第一版就漏在这里）：
      `from modules.product_research import agent_analyzers` 的 `ImportFrom.module`
      只有 `modules.product_research` —— 只看 module 名，「反向依赖了哪个子模块」
      就看不出来。这个漏洞是**反向注入 C2** 抓出来的：注入后门禁没红。
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

    ★ 为什么不用 `_called_names`（只看 `ast.Call`）：
      「把领域模型抄回壳里」未必长成构造调用的样子 —— `_ = ProfitAnalysis`
      这种**引用**同样是逻辑回流。反向注入 B1 证明了只看 Call 会漏。
    """
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _called_names(node: ast.AST) -> set:
    return {n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _kwarg_names(node: ast.AST) -> set:
    """该节点（含其子树）里出现的**关键字实参名**全集。"""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            out.update(k.arg for k in n.keywords if k.arg)
    return out


def _self_attr_chains(node: ast.AST) -> list:
    """`self.adapter.<attr>` 这类**属性链**（取数），不含裸 `self.adapter`。"""
    hits = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Attribute)
                and isinstance(n.value.value, ast.Name)
                and n.value.value.id == "self"):
            hits.append(f"self.{n.value.attr}.{n.attr}")
    return hits


@pytest.fixture(scope="module")
def analyzer_tree():
    assert ANALYZERS_PY.exists(), f"分析编排层不存在: {ANALYZERS_PY}"
    return _tree(ANALYZERS_PY)


@pytest.fixture(scope="module")
def main_tree():
    return _tree(MAIN_PY)


@pytest.fixture(scope="module")
def model_tree():
    assert MODELS_PY.exists(), f"数据结构层不存在: {MODELS_PY}"
    return _tree(MODELS_PY)


# --------------------------------------------------------------------------- #
# A 分析编排层自身
# --------------------------------------------------------------------------- #

def test_analyzer_module_has_exactly_the_analyze_functions(analyzer_tree):
    """集合相等：4 个 `analyze_*` 一个不多一个不少（防静默增删）。"""
    got = set(_top_funcs(analyzer_tree))
    assert got == set(ANALYZER_FUNCS), (
        f"多出来的: {sorted(got - ANALYZER_FUNCS)}；丢掉的: {sorted(ANALYZER_FUNCS - got)}"
    )


def test_no_analyzer_touches_self(analyzer_tree):
    """★ `self` 出现即说明该函数又需要 Agent 实例 ⇒ 显式传参已被破坏。"""
    offenders = []
    for nm in ANALYZER_FUNCS:
        fn = _top_funcs(analyzer_tree)[nm]
        if any(isinstance(x, ast.Name) and x.id in ("self", "cls")
               for x in ast.walk(fn)):
            offenders.append(nm)
    assert not offenders, (
        f"这些分析函数开始依赖实例/类状态了，必须改成参数显式传入: {offenders}"
    )


def test_analyzer_layer_imports_are_leaf(analyzer_tree):
    """分析编排层只允许依赖 adapter 接口、数据类、日志、纯逻辑层与数据层。"""
    targets = _import_targets(analyzer_tree)
    bad = [t for t in targets if any(t.startswith(p) for p in FORBIDDEN_IMPORT_PREFIXES)]
    assert not bad, f"分析编排层出现了禁止的依赖: {bad}"

    unexpected = [t for t in targets if not _is_std_or_allowed(t)]
    assert not unexpected, (
        f"分析编排层新增了未登记的非标准库依赖: {unexpected}；"
        f"若确实需要，请同时更新 ALLOWED_IMPORT_PREFIXES 并说明理由"
    )


def test_analyzer_aliases_are_the_same_objects():
    """★ 纯逻辑层别名必须是**同一对象** —— 否则就是又造了第二份实现。

    `_extract_category = ResearchHelpersMixin._extract_category` 这种别名写法
    让函数体与改前只差一个 `self.` 前缀（可机检），但代价是容易被误写成
    「复制一份函数体」。这条判据就是钉住那个代价。
    """
    from modules.product_research import agent_analyzers as AN  # noqa: PLC0415
    from modules.product_research import agent_helpers as H  # noqa: PLC0415

    for nm in ["_extract_category", "_generate_search_keywords",
               "_calculate_opportunity_score", "_generate_reason",
               "_estimate_price_range", "_estimate_margin",
               "_generate_improvement_suggestions", "_extract_product_info",
               "_extract_asin", "_extract_multiple_asins"]:
        a = getattr(AN, nm)
        b = getattr(H.ResearchHelpersMixin, nm)
        assert a is b, f"AN.{nm} 不是 mixin.{nm} 的同一对象 ⇒ 造了第二份实现"


# --------------------------------------------------------------------------- #
# B 主文件侧：真外移（而不是复制）
# --------------------------------------------------------------------------- #

def test_main_shells_have_no_domain_construction(main_tree):
    """★ 反向方向 A：薄壳里不得再出现领域模型的**任何引用** —— 出现即是「抄回来了」。

    ★ 为什么判「引用」而不是判「构造调用」：`_ = ProfitAnalysis` 这种形态
      同样是逻辑回流。反向注入 B1 证明只看 `ast.Call` 会漏掉它。
    """
    methods = _methods(_main_class(main_tree))
    for shell in SHELL_TO_DELEGATE:
        assert shell in methods, f"主类里没有 {shell}"
        refs = _referenced_names(methods[shell])
        dup = refs & set(FORBIDDEN_CONSTRUCTORS)
        assert not dup, (
            f"{shell} 里引用了领域模型 {sorted(dup)} ⇒ 逻辑被复制回主类了"
            f"（正本在 agent_analyzers.py）"
        )


def test_main_shells_have_no_data_fetching(main_tree):
    """★ 反向方向 B：薄壳里不得再出现 `self.adapter.<attr>` 取数属性链。

    ★ 注意判据只禁**属性链**：裸 `self.adapter` 作为参数传出去是正当的 ——
      本刀要的是「耦合显式」，不是「不许有数据源」。
    """
    methods = _methods(_main_class(main_tree))
    for shell in SHELL_TO_DELEGATE:
        chains = _self_attr_chains(methods[shell])
        assert not chains, (
            f"{shell} 里还在自己取数: {sorted(set(chains))} ⇒ 取数逻辑没搬走"
        )


def test_main_shells_really_delegate(main_tree):
    """★ 反向方向 C：薄壳里必须**真的**调用对应的 `analyze_*`。

    没有这条，「壳里什么都没有」也能过前两条 —— 那就成了空壳。
    """
    methods = _methods(_main_class(main_tree))
    for shell, target in SHELL_TO_DELEGATE.items():
        called = _called_names(methods[shell])
        assert target in called, (
            f"{shell} 没有调用 {target}（实测调用: {sorted(called)}）"
        )


def test_main_shells_stay_small(main_tree):
    """薄壳必须**薄**：行数上限钉住，防逻辑长回来（实测最长 13 行）。"""
    methods = _methods(_main_class(main_tree))
    for shell in SHELL_TO_DELEGATE:
        fn = methods[shell]
        n = (fn.end_lineno or fn.lineno) - fn.lineno + 1
        assert n <= SHELL_MAX_LINES, (
            f"{shell} 有 {n} 行（上限 {SHELL_MAX_LINES}）—— 薄壳不该长回来"
        )


def test_blue_ocean_shell_passes_all_three_dependencies(main_tree):
    """★★ 壳必须把 3 个依赖**全传**给 `analyze_blue_ocean`。

    ★ 为什么单独钉这一条：漏传 `session` ⇒ 结果不进会话缓存 ⇒
      「把第 1 个加进选品库」解析不出目标；漏传 `structured_llm` ⇒
      LLM 增强静默消失。**两者都不会报任何错**。
    """
    fn = _methods(_main_class(main_tree))["_analyze_blue_ocean"]
    kwargs = _kwarg_names(fn)
    for required in ("session", "structured_llm", "system_prompt"):
        assert required in kwargs, (
            f"_analyze_blue_ocean 没把 `{required}=` 传下去（实得 {sorted(kwargs)}）"
        )


# --------------------------------------------------------------------------- #
# C 数据结构层
# --------------------------------------------------------------------------- #

def test_model_module_has_exactly_the_models(model_tree):
    """集合相等：5 个模型一个不多一个不少。"""
    got = {n.name for n in model_tree.body if isinstance(n, ast.ClassDef)}
    assert got == set(MODEL_NAMES), (
        f"多出来的: {sorted(got - MODEL_NAMES)}；丢掉的: {sorted(MODEL_NAMES - got)}"
    )


def test_model_module_does_not_import_upstream(model_tree):
    """数据结构层是**叶子**：不许 import 编排层或主文件（否则成环）。

    ★ 判据比的是**导入目标全名**（见 `_import_targets`）——
      这样 `from modules.product_research import agent_analyzers` 这种
      「只写到包」的形态也能抓到。反向注入 C2 证明单看 `module` 名会漏。
    """
    targets = _import_targets(model_tree)
    bad = sorted(
        t for t in targets
        if t == MAIN_MODULE
        or t.startswith(MAIN_MODULE + ".")
        or t == "modules.product_research.agent_analyzers"
    )
    assert not bad, f"数据结构层反向依赖了上层: {bad}"


def test_main_module_reexports_models_as_same_objects():
    """5 个模型必须能从**主模块路径**取到，且与 `agent_models` 里是同一对象。

    消费方是测试（`tests/test_hitl_approval_flow.py` 导入 `AgentResponse`）——
    重新定义一份等于造第二个真源。
    """
    from modules.product_research import agent_models as MODELS  # noqa: PLC0415
    from modules.product_research import agent_product_research as M  # noqa: PLC0415

    for nm in sorted(MODEL_NAMES):
        assert hasattr(M, nm), f"主模块没有再导出 {nm}"
        assert getattr(M, nm) is getattr(MODELS, nm), (
            f"M.{nm} 与 MODELS.{nm} 不是同一对象 ⇒ 又造了一份定义"
        )

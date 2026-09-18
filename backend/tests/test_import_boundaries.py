"""跨模块 import 的**形态**门禁（P0-1 / P0-2）

★ 判据全走 AST，判「import 语句」而不是「源码里有没有这个字符串」。
  这不是洁癖：`review_analyst/service.py` 的 docstring 里就**写着**
  `MockAmazonDataSource(seed=42)` 和 `mock_source`（用于解释这条规则为什么存在），
  任何字符串式判据都会在那句话上假报。同理，注释里提到某个私有符号名也不算引用。

覆盖两条：

§1 数据源**具体实现**必须经工厂
   本项目的 SP-API 数据源有三件套：抽象 `data_sources/base.py`、
   工厂 `data_sources/__init__.py::get_data_source()`、实现 `mock_source` / `sp_api_source`。
   业务模块直接 import 实现类（或直接实例化）会让「抽象 + 工厂」形同虚设 ——
   实测的历史形态是 `review_analyst` 里 `_source = MockAmazonDataSource(seed=42)`
   的**模块级单例**，后果是配好真实凭据也永远跑假数据，且没有任何报错。

§2 跨包不得 import 下划线私有符号
   `_spu_to_dict` 曾经被 `candidates/router.py` 跨模块 import —— 它事实上是公共 API，
   名字却写着「私有」。改名的重构不会有人想到去更新那个 import。
   ★ 覆盖范围（第 139 轮**反向注入**挖出并修复）：判据按「文件所在目录 = 包」判定，
     因此 `core/` 下**直接**放着的 9 个文件（bootstrap / profit_engine / config …）、
     `modules/__init__.py`、`scripts/*.py`、backend 根文件（main.py / worker.py）
     **全部在网内**。此前判据里的 `len(parts) < 3 → continue` 把后四类整类漏掉 ——
     实测就藏着一处真实违规（`scripts/check_tenant_isolation.py`）。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 通用

EXCLUDE_DIR_PARTS = {"__pycache__", "tests", "alembic", "logs", "uploads"}


def _py_files(*roots: Path):
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if EXCLUDE_DIR_PARTS & set(p.parts):
                continue
            yield p


def _rel(p: Path) -> str:
    return p.relative_to(BACKEND).as_posix()


def _parse(p: Path) -> ast.Module | None:
    src = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def _imported_modules(tree: ast.Module) -> list[tuple[int, str, list[str]]]:
    """产出 [(行号, 被 import 的模块名, 导入的符号名列表)]，只取**绝对** import。"""
    out: list[tuple[int, str, list[str]]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:            # 相对 import ⇒ 同包内部，不算跨包
                continue
            out.append((n.lineno, n.module or "", [a.name for a in n.names]))
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.append((n.lineno, a.name, []))
    return out


# ================================================================ §1
#: 具体实现所在的模块（import 这两个 = 绕开工厂）
SOURCE_IMPL_MODULES = {
    "modules.amazon_sp.data_sources.mock_source",
    "modules.amazon_sp.data_sources.sp_api_source",
}

#: 具体实现类的类名（`from ...data_sources import MockAmazonDataSource` 同样算绕开工厂：
#: 从包里按名字取出具体类，和直接从实现模块取等价）
CONCRETE_SOURCE_CLASSES = {"MockAmazonDataSource", "SpApiDataSource"}

#: 允许直接触碰具体实现的位置（所有者 + 开发脚本 + 测试）
SOURCE_IMPL_OWNER_PREFIXES = (
    "modules/amazon_sp/",       # 实现与工厂的所有者
    "scripts/",                 # 开发/种子数据脚本，刻意产出 mock 数据
    "tests/",                   # 测试可以钉住某个具体数据源
)


def scan_direct_source_imports() -> list[tuple[str, int, str]]:
    """返回 [(文件, 行号, 说明)] —— 绕开工厂直接引用数据源实现的地方。"""
    hits: list[tuple[str, int, str]] = []
    for p in _py_files(BACKEND):
        rel = _rel(p)
        if rel.startswith(SOURCE_IMPL_OWNER_PREFIXES):
            continue
        tree = _parse(p)
        if tree is None:
            continue
        for lineno, module, names in _imported_modules(tree):
            if module in SOURCE_IMPL_MODULES:
                hits.append((rel, lineno, f"直接 import 数据源实现 {module}"))
                continue
            concrete = sorted(CONCRETE_SOURCE_CLASSES & set(names))
            if concrete:
                hits.append(
                    (rel, lineno,
                     f"从 {module or '<相对>'} 取出具体数据源类 {concrete}（应改用 get_data_source）")
                )
    return hits


def test_no_module_bypasses_the_data_source_factory():
    """业务代码不得绕过 `get_data_source()` 直接引用数据源实现。"""
    hits = scan_direct_source_imports()
    assert hits == [], (
        "以下位置绕开了数据源工厂（改用 "
        "`from modules.amazon_sp.data_sources import get_data_source`）：\n"
        + "\n".join(f"  {f}:{ln}  {why}" for f, ln, why in hits)
    )


def test_the_factory_is_the_only_door():
    """自检：工厂本身确实存在且可被导入（否则上一条的「改用工厂」是句空话）。"""
    factory = BACKEND / "modules" / "amazon_sp" / "data_sources" / "__init__.py"
    assert factory.exists(), "数据源工厂文件不见了"
    tree = _parse(factory)
    assert tree is not None
    defines = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "get_data_source" in defines, "工厂里没有 get_data_source"
    exported = set()
    for n in tree.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(n.value, ast.List):
                        exported = {e.value for e in n.value.elts
                                    if isinstance(e, ast.Constant)}
    assert "get_data_source" in exported, "get_data_source 不在 __all__ 里"


# ================================================================ §2


#: 参与跨包判据的顶层命名空间。**源与目标共用同一张表** —— 只覆盖一半会造成
#: 「甲引乙被拦、乙引甲不拦」的单边门禁。`scripts/` 与 backend 根文件不在表里，
#: 但它们仍有包身份（= 所在目录名），因此**它们引任何包树的私有符号都会被拦**。
CODE_NAMESPACES = ("modules", "core", "platforms", "ai_infra")


def source_package(rel: str) -> str:
    """源文件所属的包 = **它所在目录**的 posix 串（`modules/products/router.py` → `modules/products`）。

    ★ 这里曾经写作 `if len(parts) < 3: continue` —— 那是**真实覆盖漏洞**，不是理论洁癖：
      `core/` 下直接放着 9 个文件（`bootstrap.py` / `profit_engine.py` / `config.py` …）、
      `modules/__init__.py` 同理，它们不在任何子包里，恰恰是最想去抓别包私有 helper 的
      横切层；`scripts/` 与 backend 根文件（main.py / worker.py / conftest.py）则**整类**漏掉。
      改成「目录即包」后，实测立刻挖出一处**真实违规**：
      `scripts/check_tenant_isolation.py` 从 `core.tenant.middleware` 取私有
      `_resolve_current_shop_id`（已改为走公开入口）。
    """
    return "/".join(rel.split("/")[:-1])


def target_package(module: str) -> str | None:
    """把 import 的点号名映射到**包目录**（与 `source_package` 同一坐标系）。

    ★ 已知近似：约定「最后一段是模块名」，故 `from a.b import sym` 记作包 `a`
      （`a/b` 本身也可能是包，此时符号来自它的 `a/b/__init__.py`）。
      该近似对当前树零误报，且具体取值已被自检钉住 —— 要改约定必须同时改自检。
    """
    parts = module.split(".")
    if len(parts) < 2 or parts[0] not in CODE_NAMESPACES:
        return None      # 第三方库 / 单段模块名：没有「跨包私有」概念
    return "/".join(parts[:-1])


def is_same_package(src_pkg: str, tgt_pkg: str) -> bool:
    """源是否位于目标包**之内**（含同目录）。

    后半个条件（`src_pkg.startswith(tgt_pkg + "/")`）是必要的：`core/tenant/middleware.py`
    里写 `from core.tenant import _x` 是**读自己包的 `__init__`**，属包内；没有它会把
    包内 `__init__` 再导出判成跨包。

    ★ 反方向（`tgt_pkg` 位于 `src_pkg` 之内，如 `core/bootstrap.py` 取 `core.tenant` 的
      私有符号）**必须判为跨包** —— 那正是本判据要拦的形态，**勿加对称条件**。
    """
    return src_pkg == tgt_pkg or src_pkg.startswith(tgt_pkg + "/")


def scan_cross_package_private_imports() -> list[tuple[str, int, str]]:
    """返回 [(文件, 行号, 说明)] —— 从一个包 import 另一个包的下划线私有符号。"""
    hits: list[tuple[str, int, str]] = []
    for p in _py_files(BACKEND):
        rel = _rel(p)
        src_pkg = source_package(rel)
        tree = _parse(p)
        if tree is None:
            continue
        for lineno, module, names in _imported_modules(tree):
            tgt_pkg = target_package(module)
            if tgt_pkg is None or is_same_package(src_pkg, tgt_pkg):
                continue
            privs = sorted(n for n in names if n.startswith("_") and not n.startswith("__"))
            if privs:
                hits.append((rel, lineno,
                             f"from {module} import {', '.join(privs)}（{tgt_pkg} 的私有符号）"))
    return hits


def test_cross_package_gate_covers_top_level_and_script_files():
    """覆盖面自检：两级文件、`scripts/`、backend 根文件都必须有包身份且被判为「跨包」。

    ★ 这条是**反向注入**挖出来的：注入文件放在 `modules/<file>.py`（两级）时门禁**不响**
      （红 0 条），根因是判据里的 `len(parts) < 3 → continue`。修完必须有断言钉住，
      否则下次「为了少几个误报」很容易把它加回来。
    """
    # 两级文件 / 脚本 / 根文件：所在目录就是包，**不等于**任何子包
    assert source_package("core/bootstrap.py") == "core"
    assert source_package("modules/__init__.py") == "modules"
    assert source_package("scripts/check_tenant_isolation.py") == "scripts"
    assert source_package("main.py") == ""
    # ⇒ 它们取任一族内私有符号都算跨包（这正是被漏掉的那一档）
    for src in ("core", "modules", "scripts", ""):
        for tgt in ("core/tenant", "modules/products"):
            assert not is_same_package(src, tgt), f"{src!r} → {tgt!r} 未被判为跨包"
    # 深层包仍精确（不是「只取前两段」的粗判）
    assert source_package("modules/products/sub/x.py") == "modules/products/sub"
    # 源在目标包**之内** ⇒ 包内（等价于读自己包的 __init__）
    assert is_same_package("modules/products/sub", "modules/products")
    # ★ 反方向（源是目标的父目录）⇒ 跨包 —— 与 core/bootstrap.py 同一条规则：
    #   「上层取下层私有」是违规，「下层取上层 __init__」不是。
    assert not is_same_package("modules/products", "modules/products/sub")
    # 包内 / 包内再导出：不算跨包
    assert is_same_package("core/tenant", "core/tenant")
    assert is_same_package("core/tenant/sub", "core/tenant")
    # ★ 反方向必须判跨包（否则 core/bootstrap.py 取 core.tenant 私有符号会漏）
    assert not is_same_package("core", "core/tenant")
    # 目标侧只解析已知命名空间
    assert target_package("core.tenant.middleware") == "core/tenant"
    assert target_package("modules.products.router") == "modules/products"
    assert target_package("os.path") is None


def test_no_cross_package_private_symbol_imports():
    """跨包不得 import 下划线私有符号（它事实上是公共 API，名字却写在说「别用」）。"""
    hits = scan_cross_package_private_imports()
    assert hits == [], (
        "以下位置跨包引用了私有符号（要么把它提升为公开名，要么把它挪到调用方）：\n"
        + "\n".join(f"  {f}:{ln}  {why}" for f, ln, why in hits)
    )


# ================================================================ 自检（反向注入的常驻版）


def test_import_boundary_gates_are_not_vacuous():
    """门禁自检：每条判据都要能**真的**抓到违规（否则只是恒绿的装饰）。"""
    # §1：直接 import 实现模块
    t = ast.parse("from modules.amazon_sp.data_sources.mock_source import MockAmazonDataSource\n")
    mods = _imported_modules(t)
    assert mods == [(1, "modules.amazon_sp.data_sources.mock_source", ["MockAmazonDataSource"])]
    assert mods[0][1] in SOURCE_IMPL_MODULES

    # §1：从包里按名字取具体类（不写 .mock_source 也算绕开工厂）
    t = ast.parse("from modules.amazon_sp.data_sources import SpApiDataSource\n")
    mods = _imported_modules(t)
    assert "SpApiDataSource" in set(mods[0][2]) & CONCRETE_SOURCE_CLASSES

    # §1：经工厂 import 不算违规
    t = ast.parse("from modules.amazon_sp.data_sources import get_data_source\n")
    mods = _imported_modules(t)
    assert mods[0][1] not in SOURCE_IMPL_MODULES
    assert not (set(mods[0][2]) & CONCRETE_SOURCE_CLASSES)

    # §2：跨包私有符号命名匹配
    t = ast.parse("from modules.products.router import _spu_to_dict\n")
    mods = _imported_modules(t)
    assert mods[0][1] == "modules.products.router"
    assert target_package(mods[0][1]) == "modules/products"
    assert [n for n in mods[0][2] if n.startswith("_")] == ["_spu_to_dict"]

    # §2：公开名不算违规
    t = ast.parse("from modules.products.router import spu_to_dict\n")
    mods = _imported_modules(t)
    assert [n for n in mods[0][2] if n.startswith("_")] == []

    # §2：相对 import 是包内，不算跨包
    t = ast.parse("from .db_model import _helper\n")
    t2 = ast.parse("from .db_model import _helper\n")
    mods = [m for m in _imported_modules(t2)]
    assert mods == [], f"相对 import 不应进入跨包判据，实际得到 {mods}"
    assert t is not None

    # 第三方库的首段不在 CODE_NAMESPACES ⇒ 不计（没有「跨包私有」概念）
    assert target_package("os.path") is None
    assert target_package("collections") is None
    assert target_package("fastapi") is None

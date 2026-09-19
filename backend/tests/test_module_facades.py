"""模块**门面契约**门禁：跨模块引用只允许 `from modules.B import <已声明出口>`。

## 这道门禁要解决的问题

老板的原话是「**物理分层做了，边界从未定义**」。第 139 轮加的
`test_module_layering.py` 给每个模块打了 `KERNEL / SHARED / PLUGIN` 标签 ——
但**标签不是边界**：它只约束「谁可以依赖谁」，不约束**依赖的粒度**。
于是「边界未定义」在代码里留下的真实痕迹是这个形态：

    from modules.candidates.service import create_candidate   # 伸手进包内部

`service` 是 `modules.candidates` 的内部实现文件。消费者依赖它，就等于把
「`candidates` 内部怎么切文件」变成了一份**未声明、未被任何门禁保护的公开契约**：
包内重命名文件、拆模块、合并实现，都会在不违反任何规则的情况下打断别人。

第 140 轮的 T-682（实体归位）+ T-684（补门面）已经把 9 处跨模块引用改成走门面，
本文件把这个结果**钉住**，并把契约写成三条可执行条款。

## 门面契约（本门禁判据）

对于一个模块包 `modules/B`，其它模块 `modules/A`（A != B）引用它时：

1. **只允许** `from modules.B import <name>`；
   `from modules.B.<子模块> import ...` / `import modules.B.<子模块>` /
   `from modules import B` / `import modules.B` **一律违规**。
2. `<name>` 必须在 `modules/B/__init__.py` 的 `__all__` 里。
   —— `__all__` 就是「本包允许被其它模块取用」的名字全集。
   —— 若 `B` 连 `__all__` 都没有，报「无契约面」，而不是默认放行。
3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空：
   允许 `from modules.B import service` 等于把条款 1 变成一句空话）。

## 作用域：只管 `backend/modules/**`，**不管**测试

实测测试侧有 117+ 处深层跨模块 import（含 `_store_db`、`_fee_template_db`、
`_current_shop_id` 这类**私有**名）—— 测试**本来就该**直接摸内部（要造数据、
要断言中间态）。把它们纳入门禁只会逼出一堆只为测试存在的门面，是纯负担。

## 非目标（明确不做的两件事，避免误解为「漏洞」）

- **不要求每个模块包都有门面**。本门禁是**按需施压**：只有当一个包**被别的包
  引用**时，才要求它有契约面。给 19 个包都硬加 `__all__`，在没有消费者时只是装饰。
- **不管 `modules → core.<子包>.<模块>` 的深层取用**（如 `from core.identity.models
  import User`）。理由是 `core` 的子包**不是模块边界**（边界只应存在于可以独立
  演进 / 独立下线的切割面上；`core` 内部是一个一起测试、一起发布的实现域）。
  core 内部耦合由 `test_core_internal_layering.py` 用**登记表**管，见那边的论证。

## ★ 陷阱：门面 re-export 会**复制绑定**，从而击穿 monkeypatch

`modules/candidates/__init__.py` 做 re-export 之后，
`modules.candidates.create_candidate` 与 `modules.candidates.service.create_candidate`
是**两个独立的模块级绑定**。消费方改走门面后，

    monkeypatch.setattr("modules.candidates.service.create_candidate", fake)

**不再被拦截**（消费方读的是门面那份绑定）—— 第 140 轮实测因此红了 9 个用例。

⇒ 打桩的目标必须指向**契约面**：

    monkeypatch.setattr("modules.candidates.create_candidate", fake)

全仓对账后只有 2 处受影响（`tests/test_product_research_candidate_flow.py`）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

#: ---------------------------------------------------------------- 历史遗留登记
#: `__all__` 里含**子模块名**的包（= 契约条款 3 的例外）。
#: 这些包允许 `from modules.B import <子模块>`，即其内部结构未收口。
#: 用**字典相等**断言：新增一个必红，修掉一个不删登记也必红。
#: 第 140 轮实测只有这 2 个，且它们**当前都没有跨模块消费者** —— 属于待收口债务，
#: 不是正在被利用的漏洞。
LEGACY_SUBMODULE_EXPORTS: dict[str, frozenset[str]] = {
    "modules.customer_service": frozenset({"router"}),
    "modules.voice_clone": frozenset({"router", "db_model", "client", "service"}),
}


# ================================================================ 基础工具


def _module_index() -> frozenset[str]:
    """`backend/` 下所有**可导入的点分模块名**（含包名本身）。

    用途：判断 `from X import a` 里的 `a` 到底是「X 的属性」还是「X 的子模块」。
      · `from core.auth import device_vault` —— `device_vault` 是子模块
        （实测存在于 `core/identity/device_router.py:72`）⇒ 这是**取模块对象**，
        与 `from core.auth.device_vault import ...` 等价，不能当条款 2 的普通名字放行。
    不看这个，门禁就只能拦「写法直白」的那一半。
    """
    names: set[str] = set()
    for base in (BACKEND / "core", BACKEND / "modules", BACKEND / "ai_infra"):
        if not base.exists():
            continue
        root_pkg = base.name
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            parts = list(p.relative_to(BACKEND).with_suffix("").parts)
            if parts and parts[-1] == "__init__":
                parts = parts[:-1]
            if parts:
                names.add(".".join(parts))
            for i in range(1, len(parts)):
                names.add(".".join(parts[:i]))
    # 顶层包自身
    for base in (BACKEND / "core", BACKEND / "modules", BACKEND / "ai_infra"):
        if base.exists():
            names.add(base.name)
    return frozenset(names)


def own_package(rel_posix: str) -> str:
    """`modules/products/router.py` -> `modules.products`；`modules/products/__init__.py` 同。"""
    parts = list(Path(rel_posix).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts[:2]) if len(parts) >= 2 else ".".join(parts)


def resolve(cur_pkg: str, level: int, module: str | None) -> str:
    """把 `(level, module)` 解析成绝对点分模块名。

    ★ 相对 import **必须**解析：`modules/product_research/x.py` 里的
      `from ..candidates.service import y` 在源码里看着像"内部相对引用"，
      解析后是 `modules.candidates.service` —— **跨包深层**。
      只看 `node.module.startswith("modules.")` 的实现会整类漏掉它。
    """
    if level == 0:
        return module or ""
    base = cur_pkg.split(".")
    drop = level - 1
    if drop:
        base = base[: len(base) - drop] if drop <= len(base) else []
    if module:
        base = base + module.split(".")
    return ".".join(base)


# ================================================================ 扫描


@dataclass(frozen=True)
class Ref:
    """一条指向 `modules.*` 的引用。"""

    lineno: int
    kind: str               # "shallow" | "deep" | "bare"
    target: str             # 解析后的绝对模块名
    names: tuple[str, ...]  # `from X import a, b` 里的 (a, b)

    def __str__(self) -> str:  # pragma: no cover - 仅用于报错信息
        ns = ", ".join(self.names)
        return f"行 {self.lineno}: [{self.kind}] {self.target} :: {ns}"


def scan_cross_package(
    source: str,
    cur_pkg: str,
    is_module=None,
) -> list[Ref]:
    """产出**跨包**引用（同包内引用一律排除 —— 那是合法的内部组织）。

    kind 的含义：
      · `shallow` —— `from modules.B import <name>`：**唯一合法**形态，
                     接下来要拿 `<name>` 去 `B.__all__` 里核对。
      · `deep`    —— 显式写出子模块路径（`from modules.B.sub import ...`、
                     `import modules.B.sub`）⇒ 直接违规。
      · `bare`    —— 取到**模块/包对象**本身（`import modules.B`、
                     `from modules import B`、`from X import <子模块>`）⇒ 违规，
                     因为拿到对象后可以用属性访问绕开一切声明。

    ★ `is_module` 注入点：让本函数保持**纯函数**（不碰文件系统），
      反向注入自检才能喂假数据而不依赖真实目录。
    """
    if is_module is None:
        is_module = lambda _n: False  # noqa: E731 - 默认关闭子模块识别
    tree = ast.parse(source)
    out: list[Ref] = []

    def is_own(t: str) -> bool:
        return t == cur_pkg or t.startswith(cur_pkg + ".")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            t = resolve(cur_pkg, node.level, node.module)
            if not (t == "modules" or t.startswith("modules.")):
                continue
            alias_names = tuple(a.name for a in node.names)

            # `from modules import B` / 相对等价形态：拿到的是模块对象
            if t == "modules":
                for nm in alias_names:
                    full = "modules." + nm
                    if not is_own(full):
                        out.append(Ref(node.lineno, "bare", full, ()))
                continue
            if is_own(t):
                continue

            # 逐个别名判断：`from X import a` 中 a 若是子模块 ⇒ 同为取模块对象
            if t.count(".") == 1:
                plain: list[str] = []
                for nm in alias_names:
                    if nm != "*" and is_module(f"{t}.{nm}"):
                        out.append(Ref(node.lineno, "bare", f"{t}.{nm}", ()))
                    else:
                        plain.append(nm)
                if plain or not alias_names:
                    out.append(Ref(node.lineno, "shallow", t, tuple(plain)))
            else:
                out.append(Ref(node.lineno, "deep", t, alias_names))

        elif isinstance(node, ast.Import):
            for a in node.names:
                n = a.name
                if not n.startswith("modules") or n == "modules":
                    continue
                if is_own(n):
                    continue
                kind = "bare" if n.count(".") == 1 else "deep"
                out.append(Ref(node.lineno, kind, n, ()))
    return sorted(out, key=lambda r: (r.lineno, r.kind, r.target))


def declared_exports(pkg_dir: Path) -> tuple[bool, list[str]]:
    """读包 `__init__.py` 的 `__all__`：返回 `(是否有 __all__, 名字列表)`。

    ★ 走 AST 字面量，**不 import**（import 会执行包代码，有副作用且慢）。
      `__all__` 是拼接表达式时返回 `(True, [])` —— 门禁会报「非字面量」，
      这比默默放行安全。
    """
    init = pkg_dir / "__init__.py"
    if not init.exists():
        return (False, [])
    try:
        tree = ast.parse(init.read_text(encoding="utf-8"))
    except SyntaxError:
        return (False, [])
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            try:
                return (True, [ast.literal_eval(e) for e in node.value.elts])
            except ValueError:
                return (True, [])
        return (True, [])
    return (False, [])


def submodule_names_of(pkg_dir: Path) -> frozenset[str]:
    """包下**直接子模块 / 子包**的名字（不含 `__init__`）。"""
    names = {
        p.stem
        for p in pkg_dir.glob("*.py")
        if p.name != "__init__.py"
    }
    names |= {
        d.name for d in pkg_dir.iterdir() if d.is_dir() and d.name != "__pycache__"
    }
    return frozenset(names)


def _scan_tree() -> tuple[list[tuple[str, Ref]], dict[str, tuple[bool, list[str]]], dict[str, frozenset[str]]]:
    """扫 `modules/**`，返回 `(引用清单, 各包 __all__, 各包子模块名)`。"""
    refs: list[tuple[str, Ref]] = []
    alls: dict[str, tuple[bool, list[str]]] = {}
    subs: dict[str, frozenset[str]] = {}
    for d in sorted(p for p in MODULES.iterdir() if p.is_dir() and p.name != "__pycache__"):
        alls[f"modules.{d.name}"] = declared_exports(d)
        subs[f"modules.{d.name}"] = submodule_names_of(d)

    is_module = lambda n: n in _MODULE_INDEX  # noqa: E731
    for f in sorted(MODULES.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        rel = f.relative_to(BACKEND).as_posix()
        src = f.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for r in scan_cross_package(src, own_package(rel), is_module):
            refs.append((rel, r))
    return refs, alls, subs


_MODULE_INDEX = _module_index()


# ================================================================ 用例


def test_no_cross_module_deep_or_bare_references():
    """条款 1：跨模块引用不得写出子模块路径，也不得取模块对象。

    这是「边界未定义」最直接的痕迹 —— 一旦允许，包的内部文件结构就成了
    未声明的公开契约。
    """
    refs, _, _ = _scan_tree()
    bad = [(rel, r) for rel, r in refs if r.kind in ("deep", "bare")]
    assert not bad, (
        "以下跨模块引用越过了包门面（应改为 `from modules.B import <name>`，"
        "并在 `modules/B/__init__.py` 的 `__all__` 里声明该名字）：\n"
        + "\n".join(f"  {rel}:{r}" for rel, r in bad)
    )


def test_cross_module_imports_use_declared_exports_only():
    """条款 2：跨模块取的名字必须在目标包的 `__all__` 里；没有 `__all__` 就得先建。

    ★ 这里对「目标包没有 `__all__`」选择**报错而不是放行**：
      放行等于承认「未声明 = 可引用」，那正是本轮要消灭的形态。
    """
    refs, alls, _ = _scan_tree()
    problems: list[str] = []
    for rel, r in refs:
        if r.kind != "shallow":
            continue
        has, exported = alls.get(r.target, (False, []))
        if not has:
            problems.append(
                f"  {rel}:{r.lineno} -> {r.target} —— 该包**没有契约面**"
                f"（`{r.target.replace('.', '/')}/__init__.py` 里没有 `__all__`）；"
                f"请先声明它允许被取用的名字"
            )
            continue
        if not exported:
            problems.append(
                f"  {rel}:{r.lineno} -> {r.target} —— `__all__` 不是字面量列表，"
                f"门禁无法静态校验，请改成字面量"
            )
            continue
        for nm in r.names:
            if nm == "*":
                problems.append(f"  {rel}:{r.lineno} -> {r.target} —— 禁止 `import *`")
            elif nm not in exported:
                problems.append(
                    f"  {rel}:{r.lineno} -> {r.target} :: `{nm}` 不在 `__all__` 里"
                    f"（现有出口：{sorted(exported)}）"
                )
    assert not problems, (
        "以下跨模块引用取了未声明的出口（把名字加进目标包 `__all__`，"
        "或改用已声明的出口）：\n" + "\n".join(problems)
    )


def test_no_package_reexports_a_submodule():
    """条款 3：`__all__` 里不得出现**子模块名** —— 否则条款 1 形同虚设。

    `__all__ = ["service"]` 加 `from .service import service` 之后，
    消费者写 `from modules.B import service` 就合法地拿到了整个内部模块，
    再 `service.anything()` 畅通无阻。

    ★ 断言用**字典相等**：新增违规必红，修好一个但忘了删登记也红。
    ★ 反例来自实测：`core/identity/device_router.py:72` 里的
      `from core.auth import device_vault` 就是「`import` 语句上取到子模块」的
      真实写法 —— 这条形态在仓里**确实会发生**，不是假想。
    """
    found: dict[str, frozenset[str]] = {}
    for d in sorted(p for p in MODULES.iterdir() if p.is_dir() and p.name != "__pycache__"):
        pkg = f"modules.{d.name}"
        has, exported = declared_exports(d)
        if not has:
            continue
        subs = submodule_names_of(d)
        hits = frozenset(n for n in exported if n in subs)
        if hits:
            found[pkg] = hits

    newly = {k: sorted(v) for k, v in found.items() if k not in LEGACY_SUBMODULE_EXPORTS}
    grown = {
        k: sorted(v - LEGACY_SUBMODULE_EXPORTS[k])
        for k, v in found.items()
        if k in LEGACY_SUBMODULE_EXPORTS and v - LEGACY_SUBMODULE_EXPORTS[k]
    }
    stale = sorted(set(LEGACY_SUBMODULE_EXPORTS) - set(found))

    assert not newly, (
        "以下包的 `__all__` 里出现了**子模块名**（等于把包内部结构当出口）：\n"
        + "\n".join(f"  {k} :: {v}" for k, v in sorted(newly.items()))
    )
    assert not grown, (
        "以下历史遗留包又多暴露了子模块（债务只能减、不能加）：\n"
        + "\n".join(f"  {k} :: {v}" for k, v in sorted(grown.items()))
    )
    assert not stale, (
        f"这些包已不再暴露子模块，但登记还在，请删掉：{stale}"
    )


# ================================================================ 自检


def test_reference_scanner_is_not_vacuous():
    """★ 反向注入自检：扫描器必须真的能区分「走门面」与「伸手进内部」。

    没有这一条，条款 1 可能因为判据写错而恒绿 —— 那就是又一个假门禁。
    """
    own = "modules.secretary"
    is_mod = lambda n: n in {"modules.products.db_model"}  # noqa: E731

    def kinds(src: str) -> list[tuple[str, str, tuple[str, ...]]]:
        return [(r.kind, r.target, r.names)
                for r in scan_cross_package(src, own, is_mod)]

    # ① 深层：两种写法都要抓到
    assert kinds("from modules.products.db_model import SpuRecord\n") == [
        ("deep", "modules.products.db_model", ("SpuRecord",))
    ]
    assert kinds("import modules.products.db_model\n") == [
        ("deep", "modules.products.db_model", ())
    ]

    # ② 取模块对象：也要抓到（这是最容易被漏掉的形态）
    assert kinds("import modules.products\n") == [
        ("bare", "modules.products", ())
    ]
    assert kinds("from modules import products\n") == [
        ("bare", "modules.products", ())
    ]
    assert kinds("from modules.products import db_model\n") == [
        ("bare", "modules.products.db_model", ())
    ]

    # ③ 走门面：必须放过，且原样带出待核对的名字
    assert kinds("from modules.products import SpuRecord, spu_to_dict\n") == [
        ("shallow", "modules.products", ("SpuRecord", "spu_to_dict"))
    ]

    # ④ 同包内引用不算跨包（这是包自己的内部组织，合法）
    assert kinds("from modules.secretary.agent import build_agent\n") == []
    assert kinds("from .agent import build_agent\n") == []
    assert kinds("from ..secretary.shop_tools import X\n") == []

    # ⑤ 相对 import 必须被解析成绝对名再判 —— 否则整类漏掉
    own2 = "modules.product_research"
    got = [
        (r.kind, r.target)
        for r in scan_cross_package(
            "from ..candidates.service import create_candidate\n", own2, is_mod
        )
    ]
    assert got == [("deep", "modules.candidates.service")], (
        "相对 import 未解析成绝对名 —— `from ..candidates.service import x` 会漏报"
    )

    # ⑥ 与 `modules` 无关的引用不得误报
    assert kinds("from core.stores import StoreRecord\n") == []
    assert kinds("import os\nfrom pathlib import Path\n") == []

    # ⑦ 多行 import 的后续行缩进非 0 —— 靠缩进判定的实现会把顶层语句误判成函数内
    assert kinds("from modules.products.db_model import (\n    SpuRecord,\n)\n") == [
        ("deep", "modules.products.db_model", ("SpuRecord",))
    ]


def test_tree_scan_is_not_empty():
    """防「目录写错 ⇒ 空集 ⇒ 恒绿」：确认扫描真的看到了包与引用。"""
    refs, alls, subs = _scan_tree()
    assert len(alls) >= 15, f"只发现 {len(alls)} 个 modules 子包，扫描路径可疑"
    assert len(subs) >= 15, "子模块清单为空，扫描路径可疑"

    facades = {k for k, (has, names) in alls.items() if has and names}
    assert len(facades) >= 5, (
        f"只找到 {len(facades)} 个带 `__all__` 的门面包，"
        f"T-684 建的门面可能没落盘：{sorted(facades)}"
    )

    shallow = [r for _, r in refs if r.kind == "shallow"]
    pairs = {(own_package(rel), r.target) for rel, r in refs if r.kind == "shallow"}
    assert len(shallow) >= 8, f"只扫到 {len(shallow)} 条跨模块引用，scan 逻辑可疑"
    assert len(pairs) >= 5, f"只扫到 {len(pairs)} 条跨包边，scan 逻辑可疑"

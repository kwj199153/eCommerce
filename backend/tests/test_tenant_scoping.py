"""店铺作用域过滤的**形态**门禁（P1-3）

背景：`shop_id` 过滤曾经在 **71 处各自手写**，散在 12 个文件里。于是
「哪个列承载店铺作用域」这个决定被重复做了 71 次 —— 将来改口径（例如像
`stores_store` 那样从 owner 级升到 account 级）就得改 71 个地方。

本 file 把「店铺作用域只能有一个实现」钉住：

  S1 真源存在且 API 齐全（`core/tenant/scoping.py`：`scoped` / `scoped_if` / `scope_condition`）
  S2 业务层不得再出现**手写**的 `<Model>.shop_id == ...` 比较
  S3 真源真的被接入（防「阀建了没人用」）
  S4 扫描器自检（确认它抓得到违规，不是恒绿）
  S5 真源里「作用域列叫 shop_id」这个假设有模型层的证据支撑

★ 判据走 AST 而不是字符串匹配：`scoping.py` 自己的 docstring 里就**写着**
  `Model.shop_id == shop_id`（用来解释规则），字符串判据会在那里假报。

★ 不算违规的形态：`shop_id is None` / `is not None` —— 那是**身份守卫**
  （`if shop_id is None: raise ...`），不是作用域过滤，别误伤。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SCOPING_REL = "core/tenant/scoping.py"
SCOPING = BACKEND / SCOPING_REL
TRUE_SOURCE_MODULE = "core.tenant.scoping"

EXCLUDE_DIR_PARTS = {"__pycache__", "tests", "alembic", "logs", "uploads"}


def _rel(p: Path) -> str:
    return p.relative_to(BACKEND).as_posix()


def _business_files():
    """业务实现文件（modules/** 与 core/**，排除测试 / 迁移 / 真源自身）。"""
    for root in (BACKEND / "modules", BACKEND / "core"):
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if EXCLUDE_DIR_PARTS & set(p.parts):
                continue
            rel = _rel(p)
            if rel == SCOPING_REL:
                continue
            yield p, rel


def _parse_src(src: str) -> ast.Module | None:
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def _parse(p: Path) -> ast.Module | None:
    return _parse_src(p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n"))


def scan_handwritten_shop_scope(source: str) -> list[tuple[int, str]]:
    """从源码里扫出手写的店铺作用域比较，返回 [(行号, 表达式)]。

    ★ 只认 `==`（`Eq`）。`is None` / `is not None` 是身份守卫，返回空。
    ★ 要求比较的**一侧是属性** `X.shop_id`：裸名 `shop_id` 不构成作用域过滤
      （那是拿函数参数跟自己比，不可能出现在查询条件里）。
    """
    tree = _parse_src(source)
    if tree is None:
        return []
    out: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Compare):
            continue
        if len(n.ops) != 1 or not isinstance(n.ops[0], ast.Eq):
            continue
        sides = [n.left, *n.comparators]
        if any(isinstance(s, ast.Attribute) and s.attr == "shop_id" for s in sides):
            out.append((n.lineno, ast.unparse(n)))
    return out


# ================================================================ S1


def test_true_source_exists_with_the_documented_api():
    assert SCOPING.exists(), f"店铺作用域真源不见了：{SCOPING_REL}"
    tree = _parse(SCOPING)
    assert tree is not None, "真源无法解析"
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for want in ("scoped", "scoped_if", "scope_condition"):
        assert want in funcs, f"真源缺少 {want}()"
    # 作用域列名必须是唯一真源里的一个常量（不是散在各调用点的字面量）
    consts = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = n.value.value
    assert consts.get("SHOP_SCOPE_ATTR") == "shop_id", (
        "SHOP_SCOPE_ATTR 应等于 'shop_id'（它是「哪个列承载作用域」的唯一真源）"
    )


# ================================================================ S2


def test_no_handwritten_shop_scope_comparisons():
    """业务层不得再手写 `<Model>.shop_id == ...`（一律走真源）。"""
    offenders: list[str] = []
    for p, rel in _business_files():
        for lineno, expr in scan_handwritten_shop_scope(
                p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")):
            offenders.append(f"  {rel}:{lineno}  {expr}")
    assert offenders == [], (
        f"发现 {len(offenders)} 处手写的店铺作用域比较；"
        "改用 core.tenant.scoping 的 scoped() / scoped_if() / scope_condition()：\n"
        + "\n".join(offenders)
    )


def test_identity_guards_are_not_flagged():
    """`is None` / `is not None` 守卫不是作用域过滤，不能被抓成违规。"""
    assert scan_handwritten_shop_scope("if shop_id is None:\n    pass\n") == []
    assert scan_handwritten_shop_scope("if shop_id is not None:\n    pass\n") == []
    # 裸名（非属性）也不该被抓
    assert scan_handwritten_shop_scope("if shop_id == other:\n    pass\n") == []


# ================================================================ S3

#: 接入下限（**棘轮**，不是名单）。
#: 收敛当轮实测 11 个文件接入；此处取 8 作为下限 —— 防止「真源建了却没人用」
#: 或被整体回退。低于下限说明有人把调用点改回了手写形态。
MIN_ADOPTERS = 8


def _adopters() -> list[str]:
    out = []
    for p, rel in _business_files():
        src = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        tree = _parse_src(src)
        if tree is None:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module == TRUE_SOURCE_MODULE:
                out.append(rel)
                break
    return out


def test_true_source_is_actually_adopted():
    adopters = _adopters()
    assert len(adopters) >= MIN_ADOPTERS, (
        f"只有 {len(adopters)} 个业务文件接入 {TRUE_SOURCE_MODULE}，低于下限 {MIN_ADOPTERS}：\n"
        + "\n".join(f"  {a}" for a in adopters)
    )


# ================================================================ S5


def test_shop_scope_column_assumption_has_model_level_evidence():
    """真源假设「作用域列叫 shop_id」。要求模型层确有该列，否则这条假设是空的。"""
    holders: list[str] = []
    for root in (BACKEND / "modules", BACKEND / "core"):
        if not root.exists():
            continue
        for p in sorted(root.rglob("db_model.py")):
            if EXCLUDE_DIR_PARTS & set(p.parts):
                continue
            tree = _parse(p)
            if tree is None:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, ast.ClassDef):
                    continue
                if any(isinstance(st, ast.AnnAssign)
                       and isinstance(st.target, ast.Name)
                       and st.target.id == "shop_id"
                       for st in n.body):
                    holders.append(f"{_rel(p)}::{n.name}")
    assert len(holders) >= 8, (
        f"只有 {len(holders)} 个 ORM 模型带 shop_id 列，与真源假设不符：\n"
        + "\n".join(f"  {h}" for h in holders)
    )


# ================================================================ S4


def test_scoping_gate_is_not_vacuous():
    """扫描器自检：必须能抓到违规形态，且不误伤相邻形态。"""
    # 违规：无条件过滤
    got = scan_handwritten_shop_scope("q = select(M).where(M.shop_id == shop_id)\n")
    assert len(got) == 1 and "shop_id" in got[0][1], got

    # 违规：guard 内
    got = scan_handwritten_shop_scope(
        "if shop_id:\n    q = q.where(M.shop_id == shop_id)\n")
    assert len(got) == 1, got

    # 违规：归一化形态
    got = scan_handwritten_shop_scope("q = q.where(M.shop_id == (shop_id or ''))\n")
    assert len(got) == 1, got

    # 违规：比较写在左边（`shop_id == M.shop_id`）也要抓到
    got = scan_handwritten_shop_scope("sel = select(M).where(shop_id == M.shop_id)\n")
    assert len(got) == 1, got

    # 违规：多行 form
    got = scan_handwritten_shop_scope(
        "rows = await session.execute(\n"
        "    select(M).where(\n"
        "        M.shop_id == shop_id\n"
        "    )\n"
        ")\n")
    assert len(got) == 1, got

    # 合法：真源调用
    assert scan_handwritten_shop_scope("q = scoped(q, M, shop_id)\n") == []
    assert scan_handwritten_shop_scope("q = scoped_if(q, M, shop_id)\n") == []
    assert scan_handwritten_shop_scope("conds.append(scope_condition(M, shop_id))\n") == []

    # 合法：别的列叫 shop_id 也无所谓？——不，这里要说明：其它模型上的 shop_id
    # 列同样属于作用域，所以**任何** `X.shop_id ==` 都算违规。这正是判据的一部分。
    got = scan_handwritten_shop_scope("q = q.where(Other.shop_id == X)\n")
    assert len(got) == 1, got

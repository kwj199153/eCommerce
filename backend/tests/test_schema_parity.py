"""
schema 一致性：**外键只在迁移里，不在 ORM 里** —— 这条缝会静默掉守卫。

本文件守护的不变量
------------------
> 凡是带 `shop_id` 列的表，都必须有一条 `shop_id -> stores_store` 的外键。

不变量是**从库自身结构推导**的，不依赖任何硬编码表名清单：
将来新增一张带 `shop_id` 的表，它会被自动纳入检查；漏建外键会立刻红。

为什么值得单独一个文件
----------------------
这 16 条外键**只由 alembic 迁移建立**，ORM `db_model.py` 里根本没声明
（建库历史上靠 `create_all`，而 `create_all` 只认 ORM）。

⇒ 任何"从零建库"的路径只要走 `create_all`，就会**静默**得到一个没有外键的库。
   后果不是报错，而是「删店铺时不再被拦」——16 张业务表的行留成孤儿，
   接口返回 200，谁也不会发现。

   这就是「门禁存在 ≠ 在执行」在 schema 层的形态：迁移文件躺在仓库里，
   不等于它出现在每一个被使用的库里。

修复经过（本用例曾是 `xfail(strict=False)`，现已转正为**硬门禁**）
----------------------------------------------------------------
原缺口：init 迁移 `5fe72f9a9520` 的 `upgrade()` 是 `pass`（autogenerate 对着
"已被 create_all 建好表"的库跑出来的，diff 为空）⇒ 全新库没有任何一条可用的
供给路径；CI 又只 `create_all` 不跑迁移 ⇒ CI 的库里 16 张带 `shop_id` 的表
**外键 0 条**，而用例只在本地能过 ⇒ 长期以 XPASS 形态存在（披着绿的外衣）。

两条修复均已落地：
  - `be5abf1` squash 迁移成全薪基线 → 空库 `alembic upgrade head` 可跑通
  - `1b3fa59` CI 建库链路补齐：① `alembic upgrade head`
           ② 迁移链自检（单一 head / 往返 / `alembic check`）
           ③ `scripts/bootstrap_db.py` ④ `pytest`

实测证据（2026-09-15，`.workbuddy/probes/project-audit-20260915/r69x-freshdb-fk.txt`）：
  临时全新空库 `alembic upgrade head` -> returncode=0
    （`baseline: full schema (squashed)` -> `a506249ae3e3`）
  有 `shop_id` 列的表 = 16 / 有外键的表 = 16 / `missing = []`

⇒ 故**摘掉 `xfail` 标记**。本用例现在是硬门禁：任何让库丢掉这些外键的改动
  （例如把建库路径换回 `create_all`）都会直接变红。
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import text

from core.database import async_session_factory


_SHOP_ID_TABLES_SQL = """
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN pg_class t ON t.relname = c.table_name
    JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'
    WHERE c.column_name = 'shop_id' AND c.table_schema = 'public'
    ORDER BY 1
"""

_SHOP_ID_FK_TABLES_SQL = """
    SELECT src.relname
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class ref ON ref.oid = con.confrelid
    WHERE con.contype = 'f'
      AND ref.relname = 'stores_store'
      AND con.conname LIKE 'fk_%_shop_id_stores_store'
    ORDER BY 1
"""


async def _schema_sets() -> tuple[set[str], set[str]]:
    async with async_session_factory() as session:
        with_shop_id = set(
            (await session.execute(text(_SHOP_ID_TABLES_SQL))).scalars().all()
        )
        with_fk = set(
            (await session.execute(text(_SHOP_ID_FK_TABLES_SQL))).scalars().all()
        )
    return with_shop_id, with_fk


async def test_every_shop_id_column_has_fk_to_stores():
    """
    ★ 核心不变量：有 `shop_id` 列的表，必须有 `shop_id → stores_store` 外键。

    两侧都从库里读，不硬编码表名 —— 新增表自动纳入。
    """
    with_shop_id, with_fk = await _schema_sets()

    # 先保证断言本身不是"空对空"：连错库时两边都是空集，`==` 会假绿
    assert with_shop_id, "库里找不到任何带 shop_id 的表 —— 检查是否连到了正确的库"

    missing = sorted(with_shop_id - with_fk)
    extra = sorted(with_fk - with_shop_id)

    assert not missing, (
        f"以下表有 shop_id 列但没有指向 stores_store 的外键，"
        f"删除店铺时会产生孤儿数据（且不会报错）：{missing}"
    )
    assert not extra, f"存在指向 stores_store 的外键、但表里没有 shop_id 列：{extra}"


async def test_migration_head_is_single_not_forked():
    """
    alembic 图必须是单 head。

    `DETAILS.md` 里记着这个坑：新增迁移若挂错父节点会产生 `Multiple head`，
    之后任何 `alembic upgrade head` 都直接失败。这条不查数据库，只读迁移文件，
    因此不受"CI 没跑迁移"影响，任何时候都有效。
    """
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(backend), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        pytest.skip(f"无法执行 alembic heads（缺 alembic/psycopg2 依赖）: {proc.stderr[-200:]}")

    heads = [l for l in (proc.stdout or "").splitlines() if l.strip() and "(head)" in l]
    assert len(heads) == 1, (
        "alembic 出现多个 head，upgrade head 会失败。\r\n"
        + "\r\n".join(heads)
    )


# ====== ORM 外键目标表必须全部可解析（★ P1-b 事故后补的硬门禁）======
#
# 事故形态（2026-09-16，P1-b/P1-c 批次，实测）
# -------------------------------------------
# `stores_store.account_id -> accounts.id` 是**字符串**外键，SQLAlchemy 在
# 解析时要在当前 `MetaData` 里按表名找到 `accounts`。而 `accounts` 只由
# `core.database.register_all_models()` 导入 —— 该函数**只被 alembic/env.py
# 与 init_db() 调用**，init_db() 又只在 FastAPI lifespan 里跑。
#
# ⇒ pytest 进程从不跑 lifespan（`httpx.ASGITransport` 不触发 startup）
#   ⇒ 整个套件在 **setup 阶段 100% ERROR**，报错是
#
#       NoReferencedTableError: Foreign key associated with column
#       'stores_store.account_id' could not find table 'accounts'
#
#   注意它抛在 **flush** 时（SQLAlchemy 要对表做拓扑排序），不在 import 时；
#   而且报错指向外键本身，看起来像"外键写错了"。
#
# 为什么这条用例是正确的位置
# --------------------------
# 上面的 `shop_id` 外键检查走的是 **information_schema**（只看库里的结构），
# 所以"ORM 里声明的外键能不能解析"这件事它一个字都答不了。
# 两者互补：一个管"库里的外键在不在"，一个管"ORM 里的外键能不能用"。
#
# 判据不硬编码表名：直接让 SQLAlchemy 解析**全部**外键，目标表缺失即抛。

def test_every_orm_foreign_key_target_is_registered():
    """
    触发全部 ORM 外键的目标表解析；缺任何一张目标表都会立刻红。

    `MetaData.sorted_tables` 会对所有表做拓扑排序 —— 这正是 flush 时抛
    `NoReferencedTableError` 的那段逻辑，因此本用例能在**收集期/运行期早期**
    就复现出"某张表没被任何模块 import"这一类问题，而不是等到某条
    无关的用例 flush 时才炸（那时报错位置与根因隔了十万八千里）。
    """
    from core.database import Base, register_all_models

    register_all_models()
    # 不抛异常即通过
    tables = Base.metadata.sorted_tables
    assert tables, "metadata 里一张表都没有 —— register_all_models() 可能失效了"


def test_stores_account_fk_target_is_present():
    """
    定向钉住本次事故的那条边：`stores_store.account_id -> accounts.id`。

    为什么在通用检查之外还要这一条：通用检查依赖 `register_all_models()`
    把两个模块都导进来 —— 如果哪天有人把 `stores.db_model` 从清单里删掉，
    两条边会一起消失、通用检查反而**依然是绿的**。这条直接断言两边都在，
    且外键指向的表名正确。
    """
    from core.database import Base, register_all_models

    register_all_models()
    assert "accounts" in Base.metadata.tables, "accounts 表未注册到 metadata"
    assert "stores_store" in Base.metadata.tables, "stores_store 表未注册到 metadata"

    targets = {
        fk.target_fullname
        for fk in Base.metadata.tables["stores_store"].foreign_keys
    }
    assert "accounts.id" in targets, (
        f"stores_store 缺少指向 accounts.id 的外键，实际目标 = {sorted(targets)}"
    )


# ====== 每个模型模块必须「外键自洽」（★ 第 140 轮事故后补的硬门禁）======
#
# 事故形态（2026-09-18，第 140 轮「实体归位」，实测）
# ------------------------------------------------
# `StoreRecord` 从 `modules/stores/db_model.py` 搬到 `core/stores/models.py` 后，
# 消费者写法从
#     from modules.stores.db_model import StoreRecord
# 改成
#     from core.stores import StoreRecord
# 于是 pytest 的会话级 autouse 夹具 `_synthetic_test_shops` 在 setup 阶段直接 ERROR：
#
#     NoReferencedTableError: Foreign key associated with column
#     'stores_store.owner_id' could not find table 'users'
#
# 根因是「**意外依赖承重**」：旧写法会先执行**父包** `modules/stores/__init__.py`，
# 它 import 了 router，router import `core.auth.dependencies`，后者又 import
# `core.identity.models` ⇒ `users` 表其实是被这条**与本模块无关**的链路顺带注册的。
# 归位后父包只剩 `models.py`，链路整体断掉，于是暴露真相：`stores_store` 声明的
# 两个外键目标里，`accounts` 有人注册、`users` **没人注册**。
#
# 为什么上面 4 条用例都拦不住
# --------------------------
# 它们全部走 `register_all_models()`（把**所有**模型一起导进来）⇒ 目标表当然都在
# ⇒ 「单模块不自洽」这一类缺陷对它们是**结构性不可见**的。
# 而且它只在「没有别的测试模块先 import 过目标表」时才复现 —— **全量跑绿、
# 定向跑红**。所以必须**按模块隔离**地验。
#
# 判据（纯 AST，不 import、不连库）
# -------------------------------
# 对每个声明了 ORM 外键的模块 M，计算 M 的 **import 期传递闭包**：
#   · 顶层 import / from-import 的目标（**函数内 import 不算** —— 它被推迟到
#     调用期，帮不上 import 期的注册）；
#   · **父包 `__init__.py`** 的导入（Python 真实语义：import X.Y 必先 import X）。
# 然后断言「M 每个外键目标表的**定义模块**」都在闭包内。
# ★ 父包必须算进去 —— 上面那个事故恰恰是父包带来的；这条判据能复现它，
#   正说明判据与真实行为一致（而不是「看起来合理」）。
#
# 实测值（2026-09-18，修复前 → 修复后）
# -----------------------------------
# 全仓 6 个模块声明了 ORM 外键；修复前 **3 个不自洽**，另 1 个是「意外自洽」：
#   core.identity.account_models  缺 users          （accounts.* / account_members.* -> users.id）
#   core.identity.auth_models     缺 users          （email_tokens / login_attempts / user_api_keys -> users.id）
#   modules.amazon_sp.db_model    缺 stores_store   （8 张表 store_id -> stores_store.id）
#   modules.products.db_model     「意外」自洽      （靠门面导出 router 里的纯函数顺带拉起 core.stores）
# 修复后 6/6 自洽，且**真实子进程**（独立解释器逐个 import）与 AST 判据结论完全一致。

_FK_BACKEND = Path(__file__).resolve().parents[1]
_FK_SKIP_DIRS = {"__pycache__", "tests", "alembic", "scripts", ".venv", "venv", "node_modules"}


def _fk_build_index(root: Path) -> dict[str, Path]:
    """点分模块名 -> 文件（`__init__.py` 折叠成包名本身）。"""
    idx: dict[str, Path] = {}
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root)
        if any(part in _FK_SKIP_DIRS for part in rel.parts[:-1]):
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
        idx[".".join(parts)] = f
    return idx


def _fk_read(path: Path) -> str:
    # ★ 行尾归一化：本仓 CRLF / LF 混存，判据一律按 LF 口径。
    #
    # ★★ 第 140 轮修正：本行原本写作 `.replace("\r\n", "\r\n")` —— **字面 no-op**，
    #   注释承诺的归一化从未发生。之所以一直没暴露，是因为下游 `_fk_tablenames` /
    #   `_fk_declared_targets` / `_fk_import_time_candidates` **全是 AST 口径**
    #   （`ast.parse` 不在乎行尾）。但任何**按行锚点**的判据都会静默失配 ——
    #   第 140 轮的探针就当场踩了一次（锚点在 CRLF 文件里命中 0 次）。
    #   ⇒ 现在真的做。别让它再退化成 no-op。
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _fk_resolve(cur_pkg: str, level: int, module: "str | None") -> str:
    """把 (level, module) 解析成绝对点分模块名（相对 import 必须解析）。"""
    if level == 0:
        return module or ""
    base = cur_pkg.split(".") if cur_pkg else []
    drop = level - 1
    if drop:
        base = base[: len(base) - drop] if drop <= len(base) else []
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _fk_import_time_candidates(source: str, modname: str, is_pkg: bool) -> set[str]:
    """该模块在 import 期会拉起的模块名候选集合。

    · 函数内的 import 一律不算（被推迟到调用期，帮不上注册）。
    · `from X import a` 同时产出 `X` 与 `X.a` 两个候选 —— 后者覆盖
      「导入的是子模块」那种形态（实测仓里真有：`from core.auth import device_vault`）。
      非模块的候选在查表时自然落空，不需要额外判定。
    """
    tree = ast.parse(source)
    parents: dict[int, "ast.AST"] = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[id(ch)] = node

    def inside_func(node: "ast.AST") -> bool:
        cur = parents.get(id(node))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            cur = parents.get(id(cur))
        return False

    pkg = modname if is_pkg else modname.rsplit(".", 1)[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if inside_func(node):
            continue
        if isinstance(node, ast.ImportFrom):
            t = _fk_resolve(pkg, node.level, node.module)
            if t:
                out.add(t)
                for a in node.names:
                    out.add(f"{t}.{a.name}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
    return out


def _fk_closure(
    modname: str,
    index: dict[str, Path],
    sources: dict[str, tuple[str, bool]],
) -> frozenset[str]:
    """import 期传递闭包（含父包链 —— Python 会先执行每一层的 `__init__.py`）。"""
    # ★★ 「已访问」标记必须在 pop 之后打，不能在 push 时打。
    #   第一版写成 `if parent not in seen: seen.add(parent); stack.append(parent)`
    #   ⇒ 弹出时永远命中 `m in seen` 直接 continue ⇒ **子节点再也不被展开**，
    #   闭包退化成 1 层（只收直接 import，不传递）。实测后果：`core.stores.models`
    #   被误判成不在闭包内（它得靠展开父包 `core.stores` 才能到达），一次误报 10 个模块。
    #   自检用例 v4 / v8 就是专门盯这个退化形态的。
    seen: set[str] = set()
    stack = [modname]
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        parts = m.split(".")
        for i in range(1, len(parts)):            # 父包链
            parent = ".".join(parts[:i])
            if parent in index:
                stack.append(parent)
        src, is_pkg = sources.get(m, ("", False))
        if not src:
            continue
        for t in _fk_import_time_candidates(src, m, is_pkg):
            if t in index:
                stack.append(t)
    return frozenset(seen)


def _fk_tablenames(source: str) -> set[str]:
    """模块里 `__tablename__ = ...` 声明的表名。"""
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out.add(node.value.value)
    return out


def _fk_declared_targets(source: str) -> set[str]:
    """模块声明的外键**目标表名**（两种写法都认）。

        ForeignKey("users.id")
        ForeignKeyConstraint(["shop_id"], ["stores_store.id"], ...)

    ★ 只看**位置参数**：`name="fk_x"` 这类关键字里也带字符串，扫进去会误报。
    """
    out: set[str] = set()

    def absorb(node: "ast.AST") -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "." in node.value:
            out.add(node.value.split(".")[0])
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for e in node.elts:
                absorb(e)

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
        if name not in ("ForeignKey", "ForeignKeyConstraint"):
            continue
        for arg in node.args:
            absorb(arg)
    return out


def _fk_self_sufficiency(root: Path) -> dict[str, list[str]]:
    """返回 {模块: [缺失的外键目标表说明]}；空字典 = 全部自洽。"""
    index = _fk_build_index(root)
    sources = {m: (_fk_read(p), p.name == "__init__.py") for m, p in index.items()}

    definers: dict[str, set[str]] = {}
    for m, (src, _) in sources.items():
        for tbl in _fk_tablenames(src):
            definers.setdefault(tbl, set()).add(m)

    report: dict[str, list[str]] = {}
    for m, (src, _) in sources.items():
        targets = _fk_declared_targets(src)
        if not targets:
            continue
        closure = _fk_closure(m, index, sources)
        missing: list[str] = []
        for tbl in sorted(targets):
            owners = definers.get(tbl)
            if not owners:
                missing.append(f"{tbl}（仓里没有任何模块声明 __tablename__ = 「{tbl}」）")
            elif not (owners & closure):
                missing.append(f"{tbl}（定义于 {sorted(owners)}，但不在本模块的 import 期闭包内）")
        if missing:
            report[m] = missing
    return report


def test_every_model_module_is_self_sufficient_for_fk_targets():
    """★ 声明外键的模块，必须自己把目标表的定义模块带进 import 期闭包。

    不做这件事的后果**不在**本模块 import 时暴露，而是在**某一次 flush** 时：
    SQLAlchemy 要对表做拓扑排序，缺目标表就抛 `NoReferencedTableError`，
    报错还指向**外键本身**（看起来像「外键写错了」）。见文件顶部的事故记录。
    """
    report = _fk_self_sufficiency(_FK_BACKEND)
    assert not report, (
        "以下模型模块单独 import 时，自己声明的外键目标表**不在** metadata 里 —— "
        "任何一次 flush 都会抛 NoReferencedTableError（且只在「没有别的模块先把它"
        "带进来」时才复现，极难定位）：\r\n"
        + "\r\n".join(
            f"  {m}:\r\n" + "\r\n".join(f"      - {x}" for x in miss)
            for m, miss in sorted(report.items())
        )
        + "\r\n\r\n修法：在该模块**文件末尾**显式 import 定义目标表的模块，"
          "并加 `# noqa: E402,F401`（本仓惯用式，见 `core/stores/models.py` 末尾）。"
    )


def test_self_sufficiency_scan_is_not_vacuous():
    """★ 反向注入自检：判据必须能报出违规样本，也必须放过合法形态。

    三条最容易写错的地方，逐条钉住：
      ① 顶层 import 要算，**函数内 import 不算**；
      ② 相对 import 必须解析成绝对名（含跨层的 `..`）；
      ③ **父包 `__init__.py`** 里的 import 必须算（事故就是父包带来的）。
    """
    import tempfile

    def build(tmp: Path, files: dict[str, str]) -> Path:
        for rel, body in files.items():
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        return tmp

    owner = 'class A:\r\n    __tablename__ = "users"\r\n'
    fk = 'class B:\r\n    __tablename__ = "things"\r\n    col = Column(String, ForeignKey("users.id"))\r\n'

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)

        # ① 缺注册 ⇒ 必须报
        build(tmp / "v1", {"pkg/__init__.py": "", "pkg/a.py": owner, "pkg/b.py": fk})
        rep = _fk_self_sufficiency(tmp / "v1")
        assert "pkg.b" in rep and "users" in rep["pkg.b"][0], (
            f"判据没能报出「独立模块缺 FK 目标表定义模块」这一形态，实际 = {rep}"
        )

        # ② 顶层 import ⇒ 必须放过
        build(tmp / "v2", {
            "pkg/__init__.py": "",
            "pkg/a.py": owner,
            "pkg/b.py": "from pkg.a import A\r\n" + fk,
        })
        assert _fk_self_sufficiency(tmp / "v2") == {}, "顶层 import 未被认作有效注册"

        # ③ 函数内 import ⇒ 必须仍然报（它被推迟到调用期，帮不上 import 期的注册）
        build(tmp / "v3", {
            "pkg/__init__.py": "",
            "pkg/a.py": owner,
            "pkg/b.py": "def f():\r\n    from pkg.a import A\r\n    return A\r\n" + fk,
        })
        assert "pkg.b" in _fk_self_sufficiency(tmp / "v3"), (
            "函数内 import 被误判成 import 期注册 —— 这会让门禁恒绿"
        )

        # ④ 父包 __init__.py 里的 import ⇒ 必须放过（事故正是父包带来的）
        build(tmp / "v4", {
            "pkg/__init__.py": "from pkg.a import A\r\n",
            "pkg/a.py": owner,
            "pkg/b.py": fk,
        })
        assert _fk_self_sufficiency(tmp / "v4") == {}, (
            "父包 __init__.py 的 import 未被算进闭包 —— 判据与 Python 真实语义不符"
        )

        # ⑤ 相对 import ⇒ 必须解析（同包 `.a` 与跨层 `..a`）
        build(tmp / "v5", {
            "pkg/__init__.py": "", "pkg/a.py": owner,
            "pkg/b.py": "from .a import A\r\n" + fk,
        })
        assert _fk_self_sufficiency(tmp / "v5") == {}, "同包相对 import 未被解析"

        build(tmp / "v6", {
            "pkg/__init__.py": "", "pkg/a.py": owner,
            "pkg/sub/__init__.py": "", "pkg/sub/c.py": "from ..a import A\r\n" + fk,
        })
        assert _fk_self_sufficiency(tmp / "v6") == {}, "跨层相对 import（..）未被解析"

        # ⑥ ForeignKeyConstraint([...], [...]) 形态也要被认出（仓里 16 张表用它）
        build(tmp / "v7", {
            "pkg/__init__.py": "",
            "pkg/a.py": owner,
            "pkg/b.py": (
                'class B:\r\n    __tablename__ = "things"\r\n'
                '    __table_args__ = (ForeignKeyConstraint(["x"], ["users.id"], name="fk_b_x"),)\r\n'
            ),
        })
        assert "pkg.b" in _fk_self_sufficiency(tmp / "v7"), "ForeignKeyConstraint 形态漏报"

        # ⑦ 传递链必须**真的传递**（3 层）：b 的父包 import mid，mid 再 import a。
        #    这条专盯「闭包只展开一层」的退化 —— 那种写法在 ①②⑤ 上照样是绿的。
        build(tmp / "v8", {
            "pkg/__init__.py": "from pkg.mid import M\r\n",
            "pkg/mid.py": "from pkg.a import A\r\n",
            "pkg/a.py": owner,
            "pkg/b.py": fk,
        })
        assert _fk_self_sufficiency(tmp / "v8") == {}, (
            "闭包没有真的传递（只展开了直接 import 一层）"
        )


def test_self_sufficiency_holds_in_a_fresh_interpreter():
    """地面真相：**真实子进程**逐个 import 声明外键的模型模块，验证判据没说谎。

    为什么 AST 判据之外还要跑一遍真的：AST 闭包毕竟是一个**模型**，
    只有真实解释器能证明它没跑偏。实测两者结论一致（修复前 3 个不自洽 / 修复后 6/6）。

    ★ 必须用**子进程**而非本进程：本进程在 collection 期早已 import 了一堆东西，
      目标表全都在 metadata 里 ⇒ 任何隔离性问题都看不出来（这正是事故当初
      只在「定向跑某个不碰 DB 的用例文件」时复现的原因）。
    """
    import json
    import subprocess
    import sys as _sys  # 用**当前解释器**跑子进程：保证版本/依赖与本套件一致

    index = _fk_build_index(_FK_BACKEND)
    modules = sorted(m for m, p in index.items() if _fk_declared_targets(_fk_read(p)))
    assert len(modules) >= 4, f"只找到 {len(modules)} 个声明外键的模型模块，扫描可疑：{modules}"

    child = (
        "import json, os, sys\r\n"
        "root, mod = sys.argv[1], sys.argv[2]\r\n"
        "os.chdir(root)\r\n"
        "sys.path.insert(0, root)\r\n"
        "out = {'module': mod}\r\n"
        "try:\r\n"
        "    __import__(mod)\r\n"
        "    from core.database import Base\r\n"
        "    _ = Base.metadata.sorted_tables\r\n"
        "    out['ok'] = True\r\n"
        "except Exception as e:\r\n"
        "    out['ok'] = False\r\n"
        "    out['error'] = type(e).__name__ + ': ' + str(e)\r\n"
        "print('RESULT_JSON:' + json.dumps(out))\r\n"
    )

    def check(mod: str) -> "str | None":
        """在**全新解释器**里只 import 这一个模块，看外键能不能全部解析。"""
        proc = subprocess.run(
            [_sys.executable, "-X", "utf8", "-c", child, str(_FK_BACKEND), mod],
            cwd=str(_FK_BACKEND), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        payload = None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("RESULT_JSON:"):
                payload = json.loads(line[len("RESULT_JSON:"):])
        if payload is None:
            tail = (proc.stderr or "").strip().splitlines()
            return f"  {mod}: 子进程无结果 rc={proc.returncode} {tail[-1] if tail else ''}"
        if not payload.get("ok"):
            return f"  {mod}: {payload.get('error')}"
        return None

    # ★ 并发跑：每个子进程都要冷启解释器 + sqlalchemy + `core.config`（≈2.7s），
    #   串行 10 个约 19s，4 路并发后墙钟 ≈ 最慢那个。子进程之间无共享状态
    #   （各自独立解释器、只 import **不连库**），并发安全；覆盖完全不变。
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, modules))
    bad = [r for r in results if r]
    assert not bad, (
        "以下模型模块在**全新解释器**里单独 import 后，`Base.metadata.sorted_tables` 失败"
        "（= 缺外键目标表定义模块）：\r\n" + "\r\n".join(bad)
    )

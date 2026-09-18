"""`core/` 层的**分层门禁**：反向依赖不得发生在 import 期。

本仓的分层方向是 `modules → core`（业务依赖内核）。反方向 `core → modules`
**不能一刀切禁掉** —— 全仓共 24 处，其中 22 处是「模型注册 / 引导数据 / 粒度
查询」的合理形态，作者已用**函数内导入**在缓解（`register_all_models` 必须列全
模型，否则 alembic autogenerate 静默漏表；`bootstrap` 必须能种引导数据）。

真正危险的是**在模块顶层**反向 import：它在 import 期就把 `core` 与某个业务模块
绑定，形成模块级循环依赖，且是否报错取决于**导入顺序**（"有时能跑"）。
这正是本项目第 135 轮踩过的坑（搬 models 跨界 ⇒ 1:1 relationship 必崩）。

⇒ 本门禁的规则：**`core/` 不得在 import 期 import `modules.*`**
   —— 即反向依赖若不可避免，必须被**函数边界**推迟。
   例外只有一处（见 `EXCEPTIONS`），且必须在源码里显式声明（`# noqa: E402`）。

★ 为什么规则不是「core 不得 import modules」
  那会误伤 `register_all_models()`（`Base.metadata` 必须列全模型）与
  `bootstrap` 的 seed —— 它们是**注册 / 引导**，不是业务耦合。本门禁只钉
  「import 期耦合」这一个可执行、无争议的形态，而不是靠一张"哪个模块算业务"
  的人工名单（名单必然漂移）。

★ 判据要点（为什么这么写）
  ① 走 AST 判「该 import 是否有函数祖先」。**不能用行首缩进判** ——
     多行 import（`from x import (\\n a,\\n)`）的后续行缩进非 0，
     缩进判据会把整条语句误判成"在函数里"（漏报）。
  ② 例外表用**集合相等**断言：多一处、少一处都红 —— 既防"偷偷顶层 import"，
     也防"改了源码但忘了删例外"。
  ③ 自带反向注入自检（`test_layering_gate_is_not_vacuous`）：当场造违规样本喂给
     扫描函数，证明它真会报警（防门禁恒绿 —— 与 `test_infra_layering.py` 同名自检同源）。

★ 与 `test_infra_layering.py` 的分工
  那份管 `ai_infra`：**任何方向**都不许碰业务，且查到标识符与字符串字面量三层。
  本份只管 `core` 的 **import 期反向耦合**，不查标识符 / 字符串 —— `core` 里出现
  `StoreRecord` 是合法的（归属校验要用），且已用函数内导入推迟。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CORE = BACKEND / "core"

# ★ 唯一例外：模型注册。
#   `User.subscription <-> Subscription.user` 是 1:1 双向关系，两侧类必须同处
#   一个 `Base.registry`，否则 `configure_mappers()` 报
#     InvalidRequestError: expression 'Subscription' failed to locate a name
#   该行**只导入模块对象、不访问任何属性**，因此 `modules.billing.models` 处于
#   半初始化状态时也安全，不会循环 import。改成函数内导入会让"只 import
#   `core.identity.models` 的进程"在 mapper 配置阶段直接崩，且**只在特定导入
#   顺序下复现** —— 属于无法用测试稳定覆盖的形态，因此保留为显式例外。
EXCEPTIONS: set[tuple[str, str]] = {
    ("core/identity/models.py", "modules.billing.models"),
}

# 例外行必须在源码里自证"这是刻意的非顶层导入"（而不是靠测试文件里的一句话）。
NOQA_MARKER = "noqa: E402"


def _import_time_nodes(tree: ast.Module):
    """产出**在 import 期就会执行**的 import 节点。

    判据：该 import 的祖先链里**没有函数边界**（FunctionDef / AsyncFunctionDef）。
      · 模块体、模块级 `if`/`try` 体、类体里的 import —— 都会在 import 期执行 ⇒ 算；
      · 函数 / 方法体内的 import —— 被推迟到调用时才执行 ⇒ 不算（这正是允许的形态）。
    """
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        cur = parents.get(id(node))
        inside_func = False
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inside_func = True
                break
            cur = parents.get(id(cur))
        if not inside_func:
            yield node


def scan_import_time_reverse_imports(source: str) -> list[tuple[int, str]]:
    """返回 `[(行号, 模块名)]` —— 在 import 期执行、且指向 `modules.*` 的 import。"""
    tree = ast.parse(source)
    out: list[tuple[int, str]] = []
    for node in _import_time_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "modules" or mod.startswith("modules."):
                out.append((node.lineno, mod))
        else:  # ast.Import
            for alias in node.names:
                if alias.name == "modules" or alias.name.startswith("modules."):
                    out.append((node.lineno, alias.name))
    return sorted(out)


def _scan_all() -> dict[tuple[str, str], int]:
    found: dict[tuple[str, str], int] = {}
    for f in sorted(CORE.rglob("*.py")):
        rel = f.relative_to(BACKEND).as_posix()
        for lineno, mod in scan_import_time_reverse_imports(f.read_text(encoding="utf-8")):
            found[(rel, mod)] = lineno
    return found


# ------------------------------------------------- 1. import 期反向依赖必须为空

def test_core_has_no_import_time_reverse_import():
    """`core/` 不得在 import 期 import `modules.*`（唯一的例外见 `EXCEPTIONS`）。

    反向依赖不是绝对禁止，但**必须被函数边界推迟**：这样 `core` 被 import 时
    不会连带把某个业务模块拉进 import 图，模块级循环依赖也就不可能形成
    （循环只在 import 期才有意义）。
    """
    found = _scan_all()
    unexpected = {k: v for k, v in found.items() if k not in EXCEPTIONS}
    stale = {k for k in EXCEPTIONS if k not in found}
    assert not unexpected, (
        "core/ 出现 import 期反向依赖（应改为函数内导入）：\n"
        + "\n".join(f"  {rel}:{ln} -> {mod}" for (rel, mod), ln in sorted(unexpected.items()))
        + "\n（若确属「无法推迟」的形态，请先回答：它在 import 期真的必须执行吗？"
          "然后把它登记进 EXCEPTIONS 并在源码里加 `# noqa: E402`。）"
    )
    assert not stale, (
        f"EXCEPTIONS 里有已失效的条目（源码已不再顶层 import 它）：{sorted(stale)}"
        " —— 请删掉，否则例外表会越积越松。"
    )


# ------------------------------------ 2. 例外必须在源码里自证（不能只在测试里）

def test_registration_exception_is_declared_out_of_order():
    """例外行必须带 `# noqa: E402`。

    防的是「新加一处顶层反向 import，然后往 `EXCEPTIONS` 里塞一行就完事」——
    要求例外在**源码**也留下痕迹（`E402 = module-import-not-at-top-of-file`），
    而不是只在测试文件的一句注释里。

    ★ 定位 import 行**走 AST，不用字符串筛**：第一版用
      `[l for l in lines if "import" in l and mod in l]`，结果把紧邻的**注释行**
      （`# modules.billing.models 正处于部分初始化状态也安全…`）也当成了 import 行，
      于是报「例外行缺 noqa」—— 假红。注释里出现模块名是常态。
    """
    for rel, mod in sorted(EXCEPTIONS):
        text = (BACKEND / rel).read_text(encoding="utf-8")
        src_lines = text.splitlines()
        stmt_lines: list[int] = []
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom):
                m = node.module or ""
                if m == mod or m.startswith(mod + "."):
                    stmt_lines.append(node.lineno)
            elif isinstance(node, ast.Import):
                if any(a.name == mod or a.name.startswith(mod + ".") for a in node.names):
                    stmt_lines.append(node.lineno)
        assert stmt_lines, f"{rel}: 找不到对 `{mod}` 的 import 语句 —— 例外登记已失效"
        missing = [
            src_lines[n - 1].strip()
            for n in stmt_lines
            if NOQA_MARKER not in src_lines[n - 1]
        ]
        assert not missing, (
            f"{rel}: 例外行缺少 `{NOQA_MARKER}` 声明：{missing}\n"
            "（例外必须在源码里显式标注「这是刻意的非顶层导入」。）"
        )


# ------------------------------------------- 3. 门禁自身有效性自检（防恒绿）

def test_layering_gate_is_not_vacuous():
    """★ 反向注入自检：扫描函数必须能报出违规样本，且放过合法形态。

    没有这一条，「门禁」可能因为判据写错而恒绿 —— 那就是又一个假门禁。
    """
    # ① 模块顶层：两种 import 形态都要报
    assert scan_import_time_reverse_imports("import modules.billing.models\n") == [
        (1, "modules.billing.models")
    ]
    assert scan_import_time_reverse_imports(
        "from modules.stores.db_model import StoreRecord\n"
    ) == [(1, "modules.stores.db_model")]

    # ② 函数内导入必须**不算**（这是本门禁允许的形态）
    assert scan_import_time_reverse_imports(
        "def f():\n    from modules.billing.models import Subscription\n    return Subscription\n"
    ) == []

    # ③ 模块级 if / try 里的导入**算**（import 期会执行）
    assert scan_import_time_reverse_imports(
        "import os\nif os.getenv('X'):\n    import modules.billing.models\n"
    ) == [(3, "modules.billing.models")]

    # ④ 多行 import 的后续行缩进非 0 —— 缩进判据会漏掉，AST 判据必须抓住
    assert scan_import_time_reverse_imports(
        "from modules.x import (\n    a,\n    b,\n)\n"
    ) == [(1, "modules.x")]

    # ⑤ 干净样本不得误报
    assert scan_import_time_reverse_imports("from core.database import Base\n") == []
    assert scan_import_time_reverse_imports(
        "def f():\n    pass\n"
    ) == []


def test_scan_actually_covers_the_core_tree():
    """扫描器必须真的扫到 `core/`（防"目录路径写错 ⇒ 空集 ⇒ 恒绿"）。"""
    files = sorted(CORE.rglob("*.py"))
    assert len(files) >= 20, f"core/ 只扫到 {len(files)} 个 .py —— 路径可能不对"
    assert (CORE / "database.py").exists()
    assert (CORE / "identity" / "models.py").exists()

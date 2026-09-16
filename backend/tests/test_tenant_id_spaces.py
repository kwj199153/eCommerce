"""
店铺实体唯一性守卫（P1-c 收拢后的**源码级**判据，2026-09-16）

==============================================================================
★ 本文件的历史（为什么从"两套 ID 空间"改成"唯一解析者"）
==============================================================================
收拢前本项目有**两个**店铺实体，ID 空间不同、互不同步：

    | 侧 | 表 | ID 形态 | 解析它的依赖 | 谁在读 |
    |----|----|---------|--------------|--------|
    | 账户侧 | `shops` | UUID | `get_tenant_from_header` 家族 | 只有 `core/identity/shop_router.py` |
    | 业务侧 | `stores_store` | `store_xxx` | `get_current_shop_id*` | 15 个业务模块 |

本文件当时钉住的是一条**边界**：「同一个 `X-Shop-ID` 头在两个依赖里含义不同，
别把账户侧依赖挂到业务路由上」。

P1-c 收拢后账户侧实体整体删除（表 / 模型 / 路由 / 中间件设施），
所以那条边界不再是"要注意别越过"，而是**结构上不存在**。本文件随之升级为：

  1. **被删的符号不得复活**（第 1 条）—— 逐个点名，见下。
  2. **`X-Shop-ID` 的读取者只有两个，且都有正当身份**（第 3 条）——
     业务侧解析者、请求日志。任何第三个读者出现都必须显式论证，
     否则它就是一条"未校验的租户身份入口"。
  3. **业务侧解析者只有一个实现**（第 2 条）—— 且它查的是 `stores_store`。
  4. **ORM metadata 里不该再有第二张店铺表**（第 4 条）。

==============================================================================
★ 为什么用 AST 而不是字符串匹配
==============================================================================
本项目已经栽过两次：`core/auth/dependencies.py` 的 docstring 里逐字写着
`require_shop_owner`、`core/tenant/middleware.py` 的 docstring 里逐字引用了
修复前那行 `get_tenant_context().set_shop_id(...)`。
纯文本匹配会把这些**文档**当成**调用**，结果是"代码改对了、测试反而红"。

AST 只反映真实语法结构：docstring 与注释都是字符串/不产生节点，
天然免疫这类伪造。⇒ 本文件的一切扫描都走 AST。
"""

import ast
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]

# ====== 已废除的账户侧符号（代码级引用一律视为违规）======
#
# ★ 这份清单就是"那次架构收拢"的判据快照。往这里加名字 = 承认"又删了一套东西"；
#   从里面减名字 = 承认"这套东西回来了"，两者都必须能说清理由。
GONE_SYMBOLS = {
    # ORM 实体与枚举
    "Shop",
    "ShopPlatform",
    # 中间件的账户侧租户上下文设施
    "TenantContext",
    "_tenant_context_var",
    "_TenantContextProxy",
    "tenant_context",
    "get_tenant_context",
    "_require_owned",
    # 账户侧依赖 / 权限工厂
    "get_tenant_from_header",
    "get_optional_tenant",
    "get_tenant_from_query",
    "require_shop_owner",
}

# 允许"读 `X-Shop-ID` 头"的模块及其理由（第 3 条用例）。
# 只应有两项；任何新增都等于引入一个租户身份入口，需要显式论证。
ALLOWED_HEADER_READERS = {
    # 业务侧**唯一**的解析者 + 只做可观测性的 TenantMiddleware
    "core/tenant/middleware.py",
    # 请求日志：只把该值记进日志行，不做任何归属判定，也不写入任何上下文
    "core/middleware/request_log.py",
}


def _iter_backend_py():
    """遍历后端生产代码（排除 tests/ scripts/ alembic/ logs/ __pycache__）。"""
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", "logs/")):
            continue
        if "__pycache__" in rel:
            continue
        yield rel, p


def _iter_source_py():
    """遍历后端**全部** Python 源（含 tests/），用于"符号不得复活"的扫描。

    ★ 为什么要连 tests 一起扫：`tests/test_credential_encryption.py` 曾经
      `from core.identity.models import Shop, ShopPlatform` —— 只要测试还在
      引用被删的模型，就说明有人会照着测试把模型加回来。
    """
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith(("alembic/", "logs/")):
            continue
        if "__pycache__" in rel:
            continue
        yield rel, p


def _code_names(tree: ast.AST) -> set:
    """
    收集**代码级**出现的标识符。

    ★ 刻意不收集 `ast.Constant`（字符串）：docstring / 注释里提到某个名字，
      那是文档，不是调用。这正是 AST 相对字符串匹配的价值所在。
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[-1])
    return names


# ====== 1. 被删的符号不得复活 ======

def test_deleted_shops_side_symbols_do_not_come_back():
    """
    账户侧那套符号**一个都不得再以代码形式出现**（生产 + 测试全扫）。

    ★ 违规意味着什么：只要 `Shop` 模型还在，就会有人给它挂端点/写查询；
      而那套实体的 ID（UUID）在业务侧查不到 ⇒ 建出来的店**业务侧不可用**，
      且**不报错** —— 就是"安静地生产一批废店"。
    """
    violations = []
    for rel, path in _iter_source_py():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:          # 语法错误应该在别处暴露，这里不重复报
            raise AssertionError(f"{rel} 语法错误: {exc}") from exc
        hit = _code_names(tree) & GONE_SYMBOLS
        if hit:
            violations.append((rel, sorted(hit)))

    assert not violations, (
        "以下文件以**代码**形式引用了已废除的账户侧符号：\n"
        + "\n".join(f"  - {rel}: {syms}" for rel, syms in violations)
        + "\n这些符号随 P1-c 收拢（account → store 层级）整体删除，"
          "它们与业务侧 `stores_store` 是两套 ID 空间，并存会让人接错表。\n"
          "要继续用店铺概念请使用 `stores_store`（`StoreRecord`）"
          "+ `core/auth/accounts.py` 的归属判定；\n"
          "账户概念请使用 `core/identity/account_models.py` 的 Account / AccountMember。\n"
          "（注：docstring / 注释里提到这些名字是允许的 —— 本检查只看 AST。）"
    )


# ====== 2. 业务侧解析者唯一，且查 stores_store ======

def test_business_side_header_is_resolved_against_stores_table():
    """
    `X-Shop-ID` 在业务侧**唯一**由 `_resolve_current_shop_id` 解析，且查 `stores_store`。

    ★ 这条守的是「同名头只有一个解析者」这个不变量。收拢前账户侧读同一个头、
      含义却是 UUID —— 一旦有人再写第三个解析者，这条断言会先红。
    """
    src = (BACKEND / "core/tenant/middleware.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_resolve_current_shop_id"), None)
    assert fn is not None, "业务侧解析函数 _resolve_current_shop_id 不见了"

    body = ast.unparse(fn)
    assert "StoreRecord" in body, "业务侧必须查 stores_store（StoreRecord）"
    assert "TENANT_HEADER" in body, "业务侧解析者应从 TENANT_HEADER 取头"
    assert "can_access_store" in body, (
        "业务侧解析者必须调归属判定真源 `can_access_store()` —— "
        "自己写一份 `owner_id != user.id` 就是第二套口径（P0 事故的形态）"
    )


# ====== 3. 读 `X-Shop-ID` 的模块只有两个，且身份正当 ======

def test_only_sanctioned_modules_read_the_shop_header():
    """
    读 `X-Shop-ID` 头的模块集合必须**恰好**等于 `ALLOWED_HEADER_READERS`。

    ★ 为什么值得一条用例：这个请求头是**租户身份**的唯一载体。
      多一个读者 = 多一个"谁都能写进去/读出来"的入口。
      P0 事故（BOLA 跨租户写入）正是这么发生的：中间件用它写请求级上下文，
      另一个模块直读那个上下文当作写库归属 —— 两处单看都无害。

    ★ 扫描方式：找形如 `<something>.headers.get("X-Shop-ID" | TENANT_HEADER)`
      的真实调用（AST），**不**匹配错误文案里的 "缺少 X-Shop-ID 请求头"。
    """
    readers = set()
    for rel, path in _iter_backend_py():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # 只认 `.headers.get(...)`
            if not (isinstance(func, ast.Attribute) and func.attr == "get"):
                continue
            if not (isinstance(func.value, ast.Attribute)
                    and func.value.attr == "headers"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            is_header_arg = (
                (isinstance(arg, ast.Constant) and arg.value == "X-Shop-ID")
                or (isinstance(arg, ast.Name) and arg.id == "TENANT_HEADER")
            )
            if is_header_arg:
                readers.add(rel)

    assert readers == ALLOWED_HEADER_READERS, (
        "读 `X-Shop-ID` 的模块集合变了：\n"
        f"  实际 = {sorted(readers)}\n"
        f"  允许 = {sorted(ALLOWED_HEADER_READERS)}\n"
        "新增读者 = 新增一条租户身份入口。若确有必要，请显式加入 "
        "ALLOWED_HEADER_READERS 并写明它为什么**不做归属判定、不写任何上下文**。"
    )


# ====== 4. ORM metadata 里不该再有第二张店铺表 ======

def test_only_one_shop_table_in_orm_metadata():
    """
    `Base.metadata` 里店铺表**只有** `stores_store`。

    ★ 这条与"DB 结构里没有 shops 表"是**两件不同的事**：
      DB 那条由 `tests/test_account_store_hierarchy.py` 看运行库；
      这条看的是**代码声明**。有人只加模型不写迁移时，DB 那条查不出来
      （表还没建），metadata 这条会立刻红。
    """
    from core.database import Base, register_all_models

    register_all_models()
    tables = set(Base.metadata.tables)

    assert "stores_store" in tables, "业务侧店铺表 stores_store 不见了"
    assert "shops" not in tables, (
        "Base.metadata 里又出现了 `shops` 表 —— 这是账户侧那套已删除的实体。"
        "它和 stores_store 是两套 ID 空间，并存会让人接错表。"
    )
    # 账户层级本身必须还在（收拢不是"删掉账户概念"）
    for t in ("accounts", "account_members"):
        assert t in tables, f"{t} 不见了 —— account → store 层级是收拢后的唯一形态"

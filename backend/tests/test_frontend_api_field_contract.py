"""
前端 api 层请求体字段名 ⇔ 后端 Pydantic schema 对账门禁（第 200 轮建立）。

为什么有这个文件
----------------
`frontend/src/api/productResearch.ts` 有三个函数把后端 snake_case 字段名写成了
camelCase：`sellingPrice` / `analyzePositive` / `includeReviews`。
请求体是**直接透传**的（`request.post(path, data)`）⇒ 后果分两档：

- `selling_price` 在后端是**必填**（`Field(..., gt=0)`）⇒ 一旦被调用**稳定 422**；
- `analyze_positive` / `include_reviews` 有默认值 ⇒ **静默丢弃**（不报错，语义没了）。

第 200 轮已修。但「修完」≠「不会复发」：**同一个文件**里
`chatWithProductResearcher` 与 `resumeApproval` 的注释早就写着「必须与后端字段逐字一致」，
上面那三个函数照旧写错 —— 说明**注释不构成门禁**。
而 `frontend/scripts/check-hitl-approval.cjs` 的 D 段只覆盖 HITL 那条链
（`context_id` / `decision`），对这三个函数**零覆盖**。

本文件用**显式注册表**（与本仓 `test_tool_registry_guard.py` 的 `REGISTRY_FILES` 同范式）
把「前端函数 `data: {...}` 类型字面量」与「后端 schema 字段集合」锁成一对。

判据
----
A. 前端字段名 ⊆ 后端字段名 —— 否则前端传了后端不认的键 ⇒ 静默丢弃
B. 前端**必填**字段名 ⊆ 后端必填字段 —— 否则必填缺失 ⇒ 稳定 422
C. 前端函数体里真正请求的路径 == 注册表登记的路径 —— 防注册表与代码脱钩、
   也防「注册表把两个函数张冠李戴」。**这条让注册表自己也被门禁管着**，
   否则白名单迟早腐烂成谎话（本仓有先例）。
D. 每条判据都有**防空跑断言**：解析不到字段/路径 ⇒ 直接失败，不静默通过。

怎么加新模块
------------
往 `CONTRACTS` 里追加一行即可。**只加行不改判据**，所以不会有「新写一份实现」的
分叉风险。未登记的模块不在覆盖范围内 —— 这是显式取舍（本仓惯用棘轮而非静默全扫）。

反向注入（已实测能转红）
------------------------
1. 把 `selling_price:` 改回 `sellingPrice:` ⇒ A 红（「后端不认 sellingPrice」），
   同时 B 红（后端必填 `selling_price` 不在前端必填集合里）。
2. 把注册表里某行的 `path` 改掉 ⇒ C 红。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
BACKEND = TESTS_DIR.parent
REPO = BACKEND.parent
FRONTEND_SRC = REPO / "frontend" / "src"

SCHEMA_FILE = BACKEND / "modules" / "product_research" / "schemas.py"

# (前端 api 文件相对 frontend/src 的路径, 函数名, 注册表登记的请求路径, 后端 schema 类名)
CONTRACTS: list[tuple[str, str, str, str]] = [
    ("api/productResearch.ts", "analyzeBlueOcean", "/product-research/blue-ocean", "BlueOceanRequest"),
    ("api/productResearch.ts", "analyzeProfit", "/product-research/profit", "ProfitAnalysisRequest"),
    ("api/productResearch.ts", "analyzePainPoints", "/product-research/pain-points", "PainPointRequest"),
    ("api/productResearch.ts", "compareCompetitors", "/product-research/competitors", "CompetitorCompareRequest"),
    ("api/productResearch.ts", "chatWithProductResearcher", "/product-research/chat", "ChatRequest"),
    ("api/productResearch.ts", "resumeApproval", "/product-research/approval/resume", "ApprovalResumeRequest"),
]

_TS_FUNC = r"export\s+function\s+%s\s*\(\s*data\s*:\s*\{"
_TS_REQUEST = re.compile(
    r"request\s*\.\s*(?:post|get|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*(['\"])([^'\"]+)\1"
)


def _ts_data_literal(src: str, func_name: str) -> tuple[list[str], list[str]]:
    """返回 (全部键, 必填键)。必填 = 类型字面量里没写 `?`。"""
    m = re.search(_TS_FUNC % re.escape(func_name), src)
    assert m, f"未在 api 文件里找到 `export function {func_name}(data: {{`"

    start = m.end() - 1  # 指向 '{'
    depth = 0
    end = None
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end is not None, f"{func_name} 的 data 类型字面量没有闭合大括号"

    all_keys: list[str] = []
    required: list[str] = []
    for line in src[start + 1:end].splitlines():
        s = line.strip()
        # 跳过行内注释（`/** ... */` 与 `// ...`）
        if not s or s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            continue
        mm = re.match(r"([A-Za-z_]\w*)\s*(\?)?\s*:", s)
        if not mm:
            continue
        all_keys.append(mm.group(1))
        if not mm.group(2):
            required.append(mm.group(1))
    return all_keys, required


def _ts_request_path(src: str, func_name: str) -> str:
    m_func = re.search(r"\bfunction\s+%s\b" % re.escape(func_name), src)
    assert m_func, f"未找到函数 {func_name}"
    m = _TS_REQUEST.search(src[m_func.start():])
    assert m, f"{func_name} 函数体里没找到 `request.xxx('路径')`"
    return m.group(2)


_PY_REQUIRED_MARK = object()


def _py_schema_fields() -> dict[str, tuple[set[str], set[str]]]:
    """返回 {类名: (全部字段, 必填字段)}；必填 = `Field(..., ...)` 首参是 Ellipsis。"""
    tree = ast.parse(SCHEMA_FILE.read_text(encoding="utf-8"))
    out: dict[str, tuple[set[str], set[str]]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields: set[str] = set()
        required: set[str] = set()
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            name = stmt.target.id
            fields.add(name)
            v = stmt.value
            if (
                isinstance(v, ast.Call)
                and v.args
                and isinstance(v.args[0], ast.Constant)
                and v.args[0].value is Ellipsis
            ):
                required.add(name)
        out[node.name] = (fields, required)
    return out


def _load_ts(rel_path: str) -> str:
    p = FRONTEND_SRC / rel_path
    assert p.exists(), f"前端 api 文件不存在: {p}"
    return p.read_text(encoding="utf-8")


def test_registry_is_not_empty():
    """防空跑：注册表本身不能是空的（否则下面三条全部静默通过）。"""
    assert CONTRACTS, "CONTRACTS 注册表为空 —— 本门禁整体空跑"
    assert len(CONTRACTS) >= 6, f"注册表条目骤减到 {len(CONTRACTS)} 条，疑似被误删"


def test_frontend_field_names_are_accepted_by_backend():
    """判据 A + B：前端字段名必须被后端接受；前端必填必须在后端也是必填。"""
    schemas = _py_schema_fields()
    assert schemas, f"未能从 {SCHEMA_FILE.name} 解析出任何 schema 类 —— 判据空跑"

    failures: list[str] = []
    checked = 0

    for rel, func, _path, schema_name in CONTRACTS:
        src = _load_ts(rel)
        all_keys, required = _ts_data_literal(src, func)
        assert all_keys, f"{rel}::{func} 的类型字面量里解析不到任何字段 —— 判据空跑"

        assert schema_name in schemas, f"后端 schema 里没有类 {schema_name}"
        py_all, py_required = schemas[schema_name]
        assert py_all, f"后端 {schema_name} 解析不到任何字段 —— 判据空跑"

        checked += 1
        unknown = sorted(set(all_keys) - py_all)
        if unknown:
            failures.append(
                f"[A] {func} → {schema_name}: 前端传了后端不认的字段 {unknown}"
                f"（body 直接透传 ⇒ Pydantic 静默丢弃，不报错）"
            )
        missing_req = sorted(set(required) - py_required)
        if missing_req:
            failures.append(
                f"[B] {func} → {schema_name}: 前端必填 {missing_req} 在后端不是必填"
                f"（后端必填 = {sorted(py_required)}）⇒ 若前端少传/写错名，稳定 422"
            )

    assert checked == len(CONTRACTS), f"只检查了 {checked}/{len(CONTRACTS)} 条契约"
    assert not failures, "前端 api 层字段名与后端 schema 不一致：\n  " + "\n  ".join(failures)


def test_frontend_request_path_matches_registry():
    """判据 C：函数体里真正请求的路径 == 注册表登记的路径（防注册表腐烂/张冠李戴）。"""
    mismatches: list[str] = []
    for rel, func, path, _schema in CONTRACTS:
        src = _load_ts(rel)
        actual = _ts_request_path(src, func)
        if actual != path:
            mismatches.append(f"{func}: 注册表登记 {path!r}，代码里实际是 {actual!r}")
    assert not mismatches, "注册表与前端代码脱钩：\n  " + "\n  ".join(mismatches)

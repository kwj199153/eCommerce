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
    # ★ 第 400 轮 P1-1：**删掉**了 `("api/productResearch.ts", "resumeApproval", …)`。
    #   那条登记守的是一个已在**前端侧**退役的函数：P0-2 把审批续跑改成通用端点
    #   `POST /agents/{agent}/approval/resume` 之后，`productResearch.ts::resumeApproval`
    #   零调用点（没有一行代码再调它），P1-1 把它删了。
    #   后端那条 `/product-research/approval/resume` 仍保留（已发布的前端在用它），
    #   所以这**不是**"端点没了"，只是"前端不再走它"。
    #   ⇒ 覆盖没丢，换了位置：`test_resume_payload_interface_matches_backend`（本文件末尾）
    #     把 `ResumeApprovalPayload` 接口与后端 `ApprovalResumeRequest` 锁成一对，
    #     `frontend/scripts/check-hitl-approval.cjs` 的 D 段守 `context_id` / `decision`
    #     在整条链上逐字一致。
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
    # ★ 第 400 轮：6 → 5。删掉的是 `resumeApproval`（理由见 CONTRACTS 里那段注释：
    #   通用端点改造后前端那个函数零调用点，P1-1 已删）。
    #   ⇒ 阈值跟着降，但**不取消**：这条守的是「有人顺手清空注册表让门禁静默通过」，
    #     降一个数字不影响它守住的东西。新增契约请把它加回去。
    assert len(CONTRACTS) >= 5, f"注册表条目骤减到 {len(CONTRACTS)} 条，疑似被误删"


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


# ============================================================================
# 第 400 轮 P1-1/P1-2 补：审批续跑的载荷契约（换了文件，换了解析形态）
# ============================================================================


def _ts_interface_fields(src: str, interface: str) -> tuple[set[str], set[str]]:
    """从 TS 的 `export interface X { ... }` 取 (全部字段, 必填字段)。

    ★ 为什么不复用 `_ts_data_literal`：那个只认**内联类型字面量**
      （`function f(data: { a: string })`）。通用端点这一版的载荷是**具名 interface**
      （`resumeAgentApproval(agent, payload: ResumeApprovalPayload)`）——
      形态变了，解析器也就得换，但**要守的东西没变**：
      「前端传的键 ⊆ 后端认得键」且「前端必填 ⊆ 后端必填」。
    """
    m = re.search(r"export\s+interface\s+%s\s*\{" % re.escape(interface), src)
    assert m, f"未在 api 文件里找到 `export interface {interface} {{`"
    body = src[m.end():]
    depth = 1
    end = 0
    for i, ch in enumerate(body):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = body[:end]
    keys = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(\??)\s*:", block, re.M)
    assert keys, f"interface {interface} 里没解析出任何字段（形态变了？）"
    return {k for k, _ in keys}, {k for k, q in keys if not q}


def test_resume_payload_interface_matches_backend():
    """★★★ 审批续跑的载荷必须与后端 `ApprovalResumeRequest` 对得上。

    ★ 这条要守的是**静默丢弃**：后端 pydantic 忽略多余字段（不 422、也不采纳），
      所以前端把 `context_id` 写成 `conversationId` 时，请求**成功**、
      审批**没生效**、日志全绿 —— 这是本仓反复出现的形态。

    ★ 为什么单开一条而不是塞进 `CONTRACTS`：那张表是「内联字面量」用的，
      而通用端点这一版的载荷是具名 interface + 两参签名（`agent` 走路径）。
      硬塞进去只会把解析器改成四不像。

    ★ 反向注入：把 `ResumeApprovalPayload` 里的 `context_id` 改名
      （或去掉 `decision`）⇒ 本条必红。
    """
    ts = _load_ts("api/agentApproval.ts")
    fe_all, fe_req = _ts_interface_fields(ts, "ResumeApprovalPayload")

    schema = ast.parse((BACKEND / "modules/hitl/router.py").read_text(encoding="utf-8"))
    be_all: set[str] = set()
    be_req: set[str] = set()
    found = False
    for node in schema.body:
        if isinstance(node, ast.ClassDef) and node.name == "ApprovalResumeRequest":
            found = True
            for stmt in node.body:
                if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                    continue
                be_all.add(stmt.target.id)
                v = stmt.value
                if (
                    isinstance(v, ast.Call)
                    and v.args
                    and isinstance(v.args[0], ast.Constant)
                    and v.args[0].value is Ellipsis
                ):
                    be_req.add(stmt.target.id)
    assert found, "`modules/hitl/router.py` 里找不到 `ApprovalResumeRequest`（改名了？本判据需同步）"
    # ★ 自检：两边解析结果都非空，否则"集合 ⊆ 空集"会恒真
    assert fe_all and be_all, f"解析为空（fe={fe_all} / be={be_all}）—— 本条会假绿"

    assert fe_all <= be_all, (
        f"前端多传了后端不认的键：{sorted(fe_all - be_all)}\n"
        f"⇒ pydantic 会**静默丢弃**它们（不报错），于是参数看起来传了、其实没生效。"
    )
    assert fe_req <= be_req, (
        f"前端标了必填、后端可选（或反之）：{sorted(fe_req - be_req)} —— 必填判定要一致。"
    )
    # ★ 这两个键是整条链的命门：一个定"哪一轮会话"，一个定"批还是不批"
    assert {"context_id", "decision"} <= fe_all, "审批载荷少了 context_id / decision 之一"
    assert {"context_id", "decision"} <= be_req, "后端这两个键必须是必填（缺了就无法定位会话）"


def test_resume_endpoint_is_the_generic_one():
    """★★★ 前端必须打**通用**端点，不许再出现只对一个 Agent 生效的旧路径。

    ★ 第 399 轮的事故形态：客服点「批准」发出的是
      `/product-research/approval/resume`，于是**只有选品那一家能续跑**，
      客服的审批永远没反应 —— 而前端代码"看起来是正确的"（端点确实存在）。
    """
    ts = _load_ts("api/agentApproval.ts")
    m = re.search(r"function\s+resumeAgentApproval\b", ts)
    assert m, "`agentApproval.ts` 里找不到 `resumeAgentApproval`"
    body = ts[m.start():]
    paths = re.findall(r"`([^`]*approval/resume)`", body)
    assert paths, "函数体里没找到 approval/resume 的路径模板"
    template = paths[0]
    assert template.startswith("/agents/"), (
        f"审批续跑的路径模板是 {template!r}，不是通用端点 `/agents/{{agent}}/approval/resume`。"
    )
    assert "encodeURIComponent" in body, (
        "agent 段没做 `encodeURIComponent` —— 含 `/` 或 `?` 的 agent 名会把路径改掉。"
    )

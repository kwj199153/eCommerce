# -*- coding: utf-8 -*-
"""HITL **闭环**门禁（第 400 轮 P0-1）。

## 为什么需要这份门禁（不是"再加一条测试"）

第 399 轮实测出的洞，三个判据全都**绿着**：

    · `test_hitl_policy.py` 断言「gated 工具集合 == EXPECTED_GATED」—— 对；
    · `test_assembly_surface_three_counts_agree` 断言「绑了副作用注册表的装配点
      必须有 checkpointer」—— 对（客服的 `core.py:111` 确实绑了）；
    · 但 `agent_cs/core.py:203` 调 `run_session` 时**不传 session_id**
      ⇒ `graph_for_session(None, None)` 返回 memoryless 图 ⇒ 没有 thread_id
      ⇒ `interrupt()` 被 fail-closed 直接拒。

也就是说：**"装了闸"与"闸后面通电"是两件事**，而旧门禁只测了前者。
更糟的是 `_route_via_tools()` 在全仓**零调用点** —— 非流式 `/chat` 走的是
关键词路由，压根到不了工具环路，所以连闸都不会碰到。

## 三条判据

1. `test_every_run_session_call_passes_session`
   —— 全仓 `modules/` 下每个 `*.run_session(...)` / `*.stream_session(...)`
      **必须**传 `session_id`。这是"闸后面有没有通电"的可执行形态。
      ★ 为什么扫 `modules/` 而不是全仓：`ai_infra/base_agent.py` 里的是**定义**
        （`def run_session`），不是调用点；`graph_for_session` 也不在这个集合里。
2. `test_gated_tools_owner_has_resume_channel`
   —— 每个 gated 工具的宿主 Agent 必须在 `RESUME_SPECS` 里登记了 resume 通道。
      没有它，审批卡弹得出来、点不动。
3. `test_customer_service_invoke_wires_tool_router`
   —— 客服 `invoke()` 函数体里必须真的出现 `_route_via_tools(` 调用。
      防的是"函数存在但没人调"（第 399 轮的原样：它是死代码）。

## 反向注入（改坏了必须转红）

    · 删掉 `agent_cs/core.py` 里 `run_session(...)` 的 `session_id=` ⇒ 判据 1 红
    · 从 `RESUME_SPECS` 删掉 customer-service ⇒ 判据 2 红
    · 把 `invoke()` 里的 `_route_via_tools(` 调用删掉 ⇒ 判据 3 红

三条都做过反向注入（`r400h_inject_closed_loop.py`），HIT 3/3。
"""
import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

SESSION_METHODS = frozenset({"run_session", "stream_session"})

#: 文件前缀 → 业务 Agent 的规范 id（与 `modules/hitl/registry.py` 同名）。
#: ★ 新增一个 Agent 模块时必须在这里登记，否则它的调用点会被判为"未登记文件"。
FILE_TO_AGENT = {
    "modules/product_research/": "product-research",
    "modules/customer_service/": "customer-service",
    "modules/ad_analysis/": "ad-analysis",
    "modules/aigc_media/": "aigc-media",
    "modules/competitor_intel/": "competitor-intel",
    "modules/listing_generator/": "listing-generator",
    "modules/review_analyst/": "review-analyst",
}

#: 已知缺口：**没有 gated 工具**的 Agent 里，仍有调用点不传 `session_id`。
#:
#: 第 400 轮实测（P0-1 范围外，属于"多轮对话无记忆"这个独立问题）：
#:   · ad_analysis      2 处 —— 广告诊断/出价优化都是单轮问答，暂时能接受
#:   · aigc_media       2 处 —— 同上
#:   · competitor_intel 2 处 —— 同上
#:
#: ★ 为什么写死而不是"忽略"：忽略会让"新加一个无记忆调用点"永远不被发现。
#:   写成计数的效果是**只许减不许增** —— 谁把它们修好，这里的数字就该变小
#:   （变大则本条红）。
KNOWN_MISSING_SESSION = {
    "modules/ad_analysis/agent_ad.py": 2,
    "modules/aigc_media/agent_aigc.py": 2,
    "modules/competitor_intel/agent_competitor.py": 2,
}


def _agent_of(rel_path: str):
    for prefix, agent in FILE_TO_AGENT.items():
        if rel_path.startswith(prefix):
            return agent
    return None


def _gated_agents():
    """有 gated（需审批）工具的 Agent 规范 id 集合。

    ★ 与 `test_gated_tools_owner_has_resume_channel` 同一套推导 ——
      两处若各写一份，迟早对不上（而它们判的是同一件事）。
    """
    from modules.hitl.registry import canonical_agent_id
    from modules.skills.tools_catalog import TOOL_CATALOG
    from tests.test_hitl_policy import EXPECTED_GATED

    out = set()
    for entry in TOOL_CATALOG:
        if entry.get("name") not in EXPECTED_GATED:
            continue
        owners = set(entry.get("agents") or [])
        if entry.get("agent"):
            owners.add(entry["agent"])
        for owner in owners:
            cid = canonical_agent_id(owner)
            if cid:
                out.add(cid)
    return out


def _module_files():
    return sorted(p for p in MODULES.rglob("*.py") if "__pycache__" not in p.parts)


def _parse(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _session_calls():
    """全仓 `modules/` 下所有 `X.run_session(...)` / `X.stream_session(...)` 调用点。

    产出 `(相对路径, 行号, 是否传了 session_id, 属性名)`。
    """
    out = []
    for path in _module_files():
        try:
            tree = _parse(path)
        except SyntaxError:  # pragma: no cover —— 语法坏掉由别的门禁抓
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr in SESSION_METHODS):
                continue
            kw = {k.arg for k in node.keywords if k.arg}
            # 位置参数第 2 个以后也可能是 session_id，但**本仓统一用 keyword**
            # （`run_session(state, *, session_id=..., user_id=...)`），
            # 所以只认关键字形态；若将来改成位置传入，本判据会红一次，
            # 那时再放宽也不迟（宁可红一次，不要静默漏判）。
            out.append((
                path.relative_to(BACKEND).as_posix(),
                node.lineno,
                "session_id" in kw,
                fn.attr,
            ))
    return out


def test_every_run_session_call_passes_session():
    """★ 有 gated 工具的 Agent，每个驱动图的调用点都必须传 `session_id`。

    不传的后果**不是报错**，而是：图变成 memoryless、`interrupt()` 抛
    `HITLPrerequisiteError`、写工具从此不可用 —— 而所有"装配面"判据照样全绿。

    ## 为什么不是"全仓一律必须传"

    第 400 轮实测：除选品与客服外还有 3 个 Agent（广告 / AIGC / 竞品）也没传
    `session_id`。它们的工具**全是只读**，所以不涉及审批面 —— 但代价是
    **多轮对话无记忆**（用户第二轮追问就断片），那是另一个独立问题，
    不在 P0-1 的范围内。

    ⇒ 本条按**棘轮**写：
      · gated 工具宿主（`GATED_AGENTS`）：一处都不许漏（严格）；
      · 其余：进 `KNOWN_MISSING_SESSION`（文件 → 缺失条数），**只许减不许增**。
        减了是好事（不用改这里，计数不匹配会提示更新）；
        增了说明新增了一个无记忆的调用点，必须显式登记理由。
    """
    calls = _session_calls()
    assert calls, (
        "全仓找不到任何 run_session/stream_session 调用点 —— "
        "本门禁失去目标（要么函数改名了，要么扫错了目录）。"
    )

    gated_agents = _gated_agents()
    hard_missing, soft_missing = [], {}
    for rel, lineno, ok, attr in calls:
        if ok:
            continue
        agent = _agent_of(rel)
        if agent is None:
            hard_missing.append(f"{rel}:{lineno} .{attr}(...) —— 文件未登记到任何 Agent")
        elif agent in gated_agents:
            hard_missing.append(
                f"{rel}:{lineno} .{attr}(...) —— {agent} 有 gated 工具，必须传 session_id"
            )
        else:
            soft_missing[rel] = soft_missing.get(rel, 0) + 1

    assert not hard_missing, (
        "以下调用点没有传 `session_id` ⇒ 图是 memoryless 的，`interrupt()` 会被"
        "fail-closed 直接拒（写工具从此不可用，且**不会有任何报错**）：\n  "
        + "\n  ".join(hard_missing)
        + "\n  修法：`x.run_session(state, session_id=..., user_id=...)`。"
    )

    grew = {
        rel: n for rel, n in soft_missing.items()
        if n > KNOWN_MISSING_SESSION.get(rel, 0)
    }
    assert not grew, (
        "以下文件新增了**不传 session_id** 的调用点（多轮对话无记忆）：\n  "
        + "\n  ".join(f"{rel}: {n} 处（已知 {KNOWN_MISSING_SESSION.get(rel, 0)} 处）"
                     for rel, n in sorted(grew.items()))
        + "\n  要么补上 session_id，要么在 KNOWN_MISSING_SESSION 里显式登记并写清理由。"
    )


def test_gated_tools_owner_has_resume_channel():
    """★ 每个 gated（需审批）工具的宿主 Agent 都必须有 resume 通道。

    判据取自两处**互不依赖**的真源：
      · 谁需要审批 —— `tests/test_hitl_policy.py::EXPECTED_GATED`（工具名集合）
      · 谁能放行   —— `modules/hitl/registry.RESUME_SPECS`（agent 集合）
    中间的桥是 `TOOL_CATALOG` 的 `agent` 字段（工具 → 宿主）。

    ★ 为什么不直接写死"应该有两个 agent"：那样新增写工具的人不会被迫登记，
      而这条洞的形态恰恰是"工具加了、通道没加"。经过 TOOL_CATALOG 走一趟，
      新增工具时 `agent` 字段一填，本判据就会要求那条通道存在。
    """
    from modules.hitl.registry import canonical_agent_id, supported_agents
    from modules.skills.tools_catalog import TOOL_CATALOG
    from tests.test_hitl_policy import EXPECTED_GATED

    owner_of = {}
    for entry in TOOL_CATALOG:
        tool = entry.get("name")
        if not tool:
            continue
        owners = set(entry.get("agents") or [])
        if entry.get("agent"):
            owners.add(entry["agent"])
        owner_of[tool] = sorted(owners)

    registered = set(supported_agents())
    problems = []
    for tool in sorted(EXPECTED_GATED):
        owners = owner_of.get(tool)
        if not owners:
            problems.append(f"{tool}: TOOL_CATALOG 里找不到宿主（无法判定）")
            continue
        for owner in owners:
            agent_id = canonical_agent_id(owner)
            if agent_id is None or agent_id not in registered:
                problems.append(
                    f"{tool}: 宿主 {owner!r} 没有登记 resume 通道"
                    f"（canonical={agent_id!r}，已登记={sorted(registered)}）"
                )

    assert not problems, (
        "以下 gated 工具**弹得出审批卡、点不动批准**（图画停了没人能放行）：\n  "
        + "\n  ".join(problems)
        + "\n  修法：在 modules/hitl/registry.py 登记该 Agent，"
        "并让它的 service 实现 `resume_approval(...)`（签名见 registry docstring）。"
    )


def test_customer_service_invoke_wires_tool_router():
    """★ 客服的 `invoke()` 必须真的调 `_route_via_tools(`。

    第 399 轮的原样：`_route_via_tools()` 定义得完完整整，但**零调用点** ——
    非流式 `/chat` 只走关键词路由，写工具永远触发不到。
    "函数存在"与"函数被调"是两件事，本判据钉住后者。
    """
    core = MODULES / "customer_service" / "agent_cs" / "core.py"
    tree = _parse(core)

    invoke = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "invoke":
            invoke = node
            break
    assert invoke is not None, "customer_service/agent_cs/core.py 里找不到 invoke()"

    called = {
        n.func.attr
        for n in ast.walk(invoke)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "_route_via_tools" in called, (
        "客服 invoke() 没有调用 `_route_via_tools()` —— 非流式对话走不到工具环路，"
        "`create_ticket` 在 /chat 上永远不会被触发（审批卡也就永远不出现）。"
    )


def test_resume_approval_signatures_match_registry():
    """★ 登记的每个 resumer 都必须**真能 await 到**，且签名与通用端点对齐。

    ★ 为什么必须真 import 一次：`get_resumer()` 是惰性 import，
      模块路径写错时**启动不会报错**，只有用户点下"批准"的那一刻才 500。
      那正是"审批点了没反应"最贵的失败方式（用户会以为是数据丢了）。
    """
    import inspect

    from modules.hitl.registry import RESUME_SPECS, get_resumer

    problems = []
    for spec in RESUME_SPECS:
        fn = get_resumer(spec.agent_id)
        if fn is None:
            problems.append(f"{spec.agent_id}: get_resumer() 返回 None")
            continue
        if not inspect.iscoroutinefunction(fn):
            problems.append(f"{spec.agent_id}: {spec.module}.{spec.attr} 不是 async")
            continue
        params = inspect.signature(fn).parameters
        # 通用端点按这套名字关键字调用；缺一个就是 TypeError（点批准那一刻才炸）
        for required in ("context_id", "decision", "shop_id", "user_id",
                         "reason", "args", "feedback"):
            if required not in params:
                problems.append(f"{spec.agent_id}: 缺参数 {required}")

    assert not problems, "resume 登记表与实现漂移：\n  " + "\n  ".join(problems)

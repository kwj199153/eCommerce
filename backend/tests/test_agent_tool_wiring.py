"""
Agent ↔ 工具注册表接线门禁（第 204 轮建立）。

背景
----
老板问「19 悬空工具接上对应 agent」。接上之后必须有一条门禁**永久钉住**
「注册表要真的交到 LLM 手里」，否则下一轮新增一个 `xxx_tools` 又会悄悄悬空
—— 而 `test_tool_registry_guard.py` 的棘轮只判「不许新增」，判不出
「本来就该接的没接」。

第 202 轮实测的两种「假接线」，本文件各钉一条
--------------------------------------------
1. **注册表悬空**：`ad_analysis_tools` / `aigc_tools` / `customer_service_tools`
   注册了却没有任何 Agent 绑定（全仓 `from .tools import X` 零命中）。
2. **装饰性接线**：只在自己的 `super().__init__()` 里写 `tools=` 是**无效**的
   —— 工具只在 `BaseAgent._llm_with_tools()` 里被 `bind_tools`，而它只被图节点
   `_llm_call_node` 调用；这三家的 `invoke()` / `stream_chat()` 从不驱动那张图。
   正确做法是组合一个 `BaseAgent` 作路由子层（`_build_router()`），
   沿 `competitor_intel`(第 198 轮) / `listing_generator` / `product_research` 的先例。

为什么判据走 AST 而不是 grep：本项目多次踩「源码字符串包含」被判据骗过
（docstring / 注释里出现同名 token 即假绿）。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

# ---- 工具注册表所在文件（与 test_tool_registry_guard.py::REGISTRY_FILES 同源）----
REGISTRY_FILES = [
    "modules/aigc_media/tools.py",
    "modules/ad_analysis/tools.py",
    "modules/customer_service/tools.py",
    "modules/competitor_intel/tools.py",
    "modules/review_analyst/tools.py",
    "modules/listing_generator/tools.py",
    "modules/product_research/tools.py",
    "modules/secretary/navigation_tools.py",
    "modules/secretary/subscription_tools.py",
    "modules/secretary/product_tools.py",
    "modules/secretary/shop_tools.py",
]

# ---- 必须「真的把工具交给 LLM」的 Agent：文件 → 期望装配的容器名 ----
# 新增 Agent 时在此补一行。漏补的后果 = 该 Agent 的工具永远悬空，
# 而本文件不会转红 —— 这是本清单**唯一的**维护义务，写在最显眼处。
WIRED_AGENTS = {
    "modules/ad_analysis/agent_ad.py": "ad_analysis_tools",
    "modules/aigc_media/agent_aigc.py": "aigc_tools",
    "modules/customer_service/agent_cs.py": "customer_service_tools",
    "modules/competitor_intel/agent_competitor.py": "competitor_intel_tools",
    "modules/listing_generator/agent_listing.py": "listing_tools",
    "modules/product_research/agent_product_research.py": "product_research_tools",
    "modules/review_analyst/agent.py": "review_analyst_tools",
}

#: `secretary` 的装配写在 `super().__init__(tools=...)` 里（拼接表达式），
#: 单独列一对，判据同上。
WIRED_SECRETARY = {
    "modules/secretary/agent.py": {"navigation_tools", "subscription_tools",
                                   "product_tools", "shop_tools",
                                   "library_tools"},
}


def _parse(rel: str) -> ast.Module:
    return ast.parse((BACKEND / rel).read_bytes().decode("utf-8", "replace"))


def _module_level_tool_lists(tree: ast.Module) -> list[tuple[str, list[str], int]]:
    """模块级 `xxx_tools = ...` → [(var, [工具名], 行号)]。

    ★ 取值形态**不止 list 字面量**（第 204 轮实测修正）：
      `listing_generator/tools.py` 写的是
      `listing_tools = _fine_grained_tools + _coarse_grained_tools`（`BinOp`），
      工具名要等运行时相加才出现。
      只认 `ast.List` 会让它**整条漏出扫描面** ⇒ 一个 `x_tools = a + b` 形态的
      容器被拔掉装配，本判据**不会有任何反应** —— 正是本仓最警惕的
      「门禁真空区」（判据自己看不见自己该管的对象）。
      ⇒ 形态放宽到 `List` / `BinOp` / `Name`：工具名只在 `List` 时取得到，
        而本判据只用**容器名**，取不到不影响它。
    """
    found = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, (ast.List, ast.BinOp, ast.Name)):
            continue
        is_list = isinstance(node.value, ast.List)
        for tgt in node.targets:
            # ★ 下划线前缀 = **内部拼装零件**，不是注册表。
            #   `_fine_grained_tools` / `_coarse_grained_tools` 只用于相加出
            #   `listing_tools`（那个才真被装配）。把零件当注册表 ⇒ 本判据会报
            #   两条**假红**（第 204 轮实测踩到）。零件是否真被用到，由判据 2
            #   从**真容器**名下核对 —— 少一个零件会让真容器少几个工具，照样露馅。
            if not (
                isinstance(tgt, ast.Name)
                and tgt.id.endswith("_tools")
                and not tgt.id.startswith("_")
            ):
                continue
            names = []
            if is_list:
                for el in node.value.elts:
                    if isinstance(el, ast.Call):
                        for kw in el.keywords:
                            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                                names.append(kw.value.value)
            found.append((tgt.id, names, node.lineno))
    return found


def _names_in(expr: str) -> set[str]:
    """从 `a + b` / `build_x(shop_id)` / `mod.X` 里取出所有 Name。"""
    tree = ast.parse(expr, mode="eval")
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _agent_tools_args(rel: str) -> list[tuple[str, int]]:
    """产出该文件里所有 `tools=` 实参的 (源码, 行号)。

    ★ **纯文件级**：不区分那些实参住在哪个方法里。判据 1 用它（判「容器有没有
      被任何地方引用」）；要判「装配点真的可达」必须用 `_tools_args_in_func`。
    """
    out = []
    for node in ast.walk(_parse(rel)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "tools":
                    out.append((ast.unparse(kw.value), node.lineno))
    return out


def _tools_args_in_func(rel: str, func_name: str) -> list[tuple[str, int]]:
    """**只取指定方法体内**的 `tools=` 实参。

    ★ 为什么要这层切片（第 204 轮反向注入实测）：文件级扫描无法区分
      「装到了 `_build_router`」与「装进了一个没人调用的死方法」——
      把 `_build_router` 改名后，`tools=aigc_tools` 那句话**还在文件里**，
      文件级判据照样绿。而**装配的唯一意义是它会被执行**。
    """
    out: list[tuple[str, int]] = []
    for node in ast.walk(_parse(rel)):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == func_name):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                for kw in sub.keywords:
                    if kw.arg == "tools":
                        out.append((ast.unparse(kw.value), sub.lineno))
    return out


# ============================================================
# 1. 每个模块级工具容器都必须被某个 Agent 装配
# ============================================================

def test_every_tool_registry_is_wired_to_an_agent():
    """`*_tools` 容器不得悬空 —— 要么接给某个 Agent，要么删掉。

    ★ 这是第 204 轮的正题：接手前实测 3 个容器 / 19 个工具悬空
      （`ad_analysis_tools` 6 + `aigc_tools` 9 + `customer_service_tools` 4）。

    ★★ 判据的**射程**（第 204 轮反向注入实测的读数 —— 别高估它）：
       它只问「这个容器名有没有出现在**某个** `tools=` 实参里」，**纯 AST 级**。
       ⇒ 把 `_build_router` 改名、让那个 `tools=` 住进**死方法**，本条
         **不会红**（实测：注入 E 时红的只有判据 3）。
       所以「容器没悬空」≠「工具真的到了模型手上」：
         · 「实参住的方法是不是 `_build_router`」→ **判据 3**；
         · 「`_build_router` 定义与调用点成对」→
           `test_hitl_policy.py::test_assembly_surface_three_counts_agree`。
       三条合起来才等于那句话；单看本条会高估覆盖面。
    """
    declared: dict[str, str] = {}
    for rel in REGISTRY_FILES:
        if not (BACKEND / rel).exists():
            continue
        for var, _names, _ln in _module_level_tool_lists(_parse(rel)):
            declared[var] = rel
    assert declared, "一个模块级 *_tools 容器都没扫到 —— 判据空跑，先查 REGISTRY_FILES"

    wired: set[str] = set()
    for rel in WIRED_AGENTS:
        for expr, _ln in _agent_tools_args(rel):
            wired |= _names_in(expr)
    for rel in WIRED_SECRETARY:
        for expr, _ln in _agent_tools_args(rel):
            wired |= _names_in(expr)

    unwired = sorted(set(declared) - wired)
    assert not unwired, (
        "以下工具容器注册了却没有任何 Agent 绑定（悬空）："
        + ", ".join(f"{v}（{declared[v]}）" for v in unwired)
        + "；要么接给 Agent，要么删掉。"
    )
    assert len(declared) >= 9, f"容器数异常偏少（{len(declared)}），注册表可能没被读全"


# ============================================================
# 2. 显式清单里的每个 Agent 都必须把期望的容器交出去
# ============================================================

def test_wired_agents_pass_expected_registry():
    """`WIRED_AGENTS` 里每个 Agent 的 `tools=` 必须含期望容器名。

    ★ 防的是「接了但接错/接没了」：例如有人把 `tools=ad_analysis_tools` 改成
      别的容器、或整个删掉 —— 棘轮与本文件判据 1 都可能仍然绿
      （容器照样被别处引用），但该 Agent 手里已经没有工具了。
    """
    for rel, expected in WIRED_AGENTS.items():
        args = _agent_tools_args(rel)
        assert args, f"{rel} 里找不到任何 `tools=` 实参 —— 该 Agent 没把工具交给 LLM"
        names: set[str] = set()
        for expr, _ln in args:
            names |= _names_in(expr)
        assert expected in names, (
            f"{rel} 的 tools= 实参里没有 {expected}（实为 {sorted(names)}）"
        )

    for rel, expected in WIRED_SECRETARY.items():
        names: set[str] = set()
        for expr, _ln in _agent_tools_args(rel):
            names |= _names_in(expr)
        missing = expected - names
        assert not missing, f"{rel} 的 tools= 实参缺 {sorted(missing)}"


# ============================================================
# 3. `_build_router` 形态：必须有、且真的把 tools 传给 BaseAgent
# ============================================================

def test_router_sublayer_shape():
    """每个「范式 A」Agent 必须有 `_build_router()`，且 `tools=` 实参**就住在它体内**。

    ★★ 为什么必须限定在 `_build_router` 体内（第 204 轮反向注入实测）：
       旧版用 `_agent_tools_args(rel)` 扫**整个文件**。把 `_build_router` 改名
       （= 拆掉工具路由子层）之后，`tools=aigc_tools` 那句**还在文件里**，
       只是住进了一个**没人调用的方法** ⇒
         · 判据 1（同样文件级、只问"出现过"）**没红**；
         · 若不是本条改了，本条也会**假绿**。
       ⇒ 判据形态必须是「**装配点所在的函数**」，不是「文件里出现过这个字符串」。
         装配的唯一意义是它会被执行。

    ★ 为什么还要断言"不是空列表"：`BaseAgent` 用空工具集照样能构建
      （`ToolNode` 接受空集），`bind_tools` 直接返回原 llm ——
      **装配成功、工具为零**，静默失效。

    ★ 覆盖面：`WIRED_AGENTS` **全表**（7 家走 `_build_router` 的 Agent），
      不再只覆盖第 204 轮改造的 3 家 —— 新增 Agent 时它**自动**进入扫描面。
      实测 7 家全部满足（`probes/out_r204j_scope.txt`），加严不误伤。
    """
    checked = 0
    for rel, expected in WIRED_AGENTS.items():
        tree = _parse(rel)
        has_router = any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_build_router"
            for n in ast.walk(tree)
        )
        assert has_router, (
            f"{rel} 缺 `_build_router()` —— 该 Agent 走的是范式 A，"
            f"没有它就等于工具交不到 LLM 手上"
        )

        args = _tools_args_in_func(rel, "_build_router")
        assert args, (
            f"{rel} 的 `_build_router()` **体内**没有 `tools=` 实参 —— "
            f"实参若住在别的方法里，那个方法很可能没人调用（死方法），"
            f"而文件级扫描看不出这个区别"
        )
        for expr, ln in args:
            body = ast.parse(expr, mode="eval").body
            assert not (isinstance(body, ast.List) and not body.elts), (
                f"{rel}:{ln} 的 `tools=` 是空列表 —— 装配成功但工具为零，属静默失效"
            )
        names: set[str] = set()
        for expr, _ln in args:
            names |= _names_in(expr)
        assert expected in names, (
            f"{rel} 的 `_build_router(tools=...)` 里没有 {expected}"
            f"（实为 {sorted(names)}）—— 该 Agent 手里没有它该有的工具"
        )
        checked += 1

    assert checked >= 7, (
        f"只核对了 {checked} 个 Agent（期望 ≥7）—— `WIRED_AGENTS` 可能被改瘦了；"
        f"清单是判据的扫描面，改瘦它等于静默放弃覆盖"
    )


# ============================================================
# 4. 归属 ContextVar：需要租户维度的模块必须定义 + 只从唯一写入点写
# ============================================================

def test_shop_context_provider_exists():
    """需要租户维度的模块必须有 `_current_shop_id`，且 tools 从它取归属。

    ★ 判据来源（第 204 轮）：`ad_analysis/tools.py` 改造前 6 个工具**一个都没传
      `store_id`** ⇒ service 的 `store_id` 恒为 None ⇒ agent 层取数直接返回空表
      ⇒ 工具永远回「未绑定店铺上下文」。**接上工具却永远没数据。**
    """
    for rel in ("modules/ad_analysis/agent_ad.py",
                "modules/customer_service/agent_cs.py"):
        src = (BACKEND / rel).read_bytes().decode("utf-8", "replace")
        assert "_current_shop_id" in src, (
            f"{rel} 缺 `_current_shop_id` —— 该模块的工具需要租户归属"
        )

    for rel in ("modules/ad_analysis/tools.py",
                "modules/customer_service/tools.py"):
        src = (BACKEND / rel).read_bytes().decode("utf-8", "replace")
        assert "def _shop_id()" in src, (
            f"{rel} 缺 `_shop_id()` —— 工具层取不到归属，会永远返回 no_data"
        )


def test_create_ticket_has_no_store_id_param():
    """`create_ticket` 不得把 `store_id` 做成工具形参。

    ★ 改造前它的 docstring 写着「store_id 由系统注入，LLM 不得自行指定」，
      而实现里它是**普通形参** —— 模型照填不误 ⇒ 租户边界交给 LLM。
      典型「注释承诺型假门禁」，本条把它钉死。
    """
    tree = _parse("modules/customer_service/tools.py")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == "_create_ticket_tool":
            args = [a.arg for a in node.args.args]
            assert "store_id" not in args, (
                "create_ticket 又把 store_id 收回成工具形参了 —— 归属只能服务端注入"
            )
            return
    raise AssertionError("找不到 _create_ticket_tool")

"""HITL 审批策略门禁（第 145 轮 · 批 B1/B2/B5）。

## 这批改动解决了什么

批 B 之前，「哪个工具要人工审批」由业务侧一句手写名单决定：

    _APPROVAL_GATED_INTENTS = frozenset({"save_candidate"})

那是**审批白名单** —— 默认不审批。新增一个写库工具而没人记得改名单 ⇒
**静默漏审批**，且不报错、测试全绿。反向注入也咬不住：把某个工具从名单里
删掉，没有任何用例会红（因为「没被列进去」和「列错了」看起来一样）。

批 B 把方向反转为**只读豁免**（见 `ai_infra/tools/side_effects.py`）：
工具**自己**声明 `metadata={"side_effects": False}` 才免审批，
未声明的一律视为有副作用（fail-closed）。

## 本文件钉住的五件事

1. `test_every_tool_declares_side_effects`
   —— 全仓 54 个工具**全部**显式表态（不允许靠 fail-closed 兜底）。
   这一条是「棘轮」：新增工具必须给出声明，否则红。
2. `test_write_verb_tools_are_never_exempted`
   —— 名字带写动词（`save_` / `create_` / …）的工具**不得**被声明为只读。
   这是**独立第二判据**：即使有人把某个写库工具的声明改坏，本条仍会咬。
3. `test_gated_set_matches_policy_derivation`
   —— 运行时推导出的「需审批工具集合」必须 == `EXPECTED_GATED`。
   声明被改坏（写 → 只读）⇒ 集合变小 ⇒ 红；新增写工具 ⇒ 集合变大 ⇒ 红
   （提醒把新工具纳入审查视野，而不是让它静默获得/失去审批）。
4. `test_agents_compiling_gated_registries_carry_checkpointer`
   —— 凡装配了「含副作用工具」的注册表的 `BaseAgent(...)` 构造点，
   **必须同现 `checkpointer=`** 且非字面量 `None`（`interrupt()` 的前提）。
5. `test_registry_lists_agree_with_tool_registry_guard`
   —— 本文件的注册表清单与 `test_tool_registry_guard.REGISTRY_FILES` 一致，
   防止「新增注册表只登记了一处」。

## 反向注入（改坏了必须转红，否则这些用例是在空跑）

* 把 `save_candidate` 的 `metadata` 从 `SIDE_EFFECT_METADATA` 改成
  `READ_ONLY_METADATA` ⇒ 判据 3 集合变小 ⇒ 红；
* 把它从工具定义里**整个删掉** `metadata=` ⇒ 判据 1 未声明非空 ⇒ 红；
* 删除 `product_research._build_router()` 的 `checkpointer=get_checkpointer()`
  ⇒ 判据 4 红（它在 `test_hitl_wiring.py` 侧也有运行时对照）；
* 把 `create_ticket` 改名成 `make_ticket` 并声明只读 ⇒ 判据 3 红（少一个 gated）。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# ---- 工具注册表清单（变量名 → 模块路径）----
# ⚠️ 与 `test_tool_registry_guard.REGISTRY_FILES` 的一致性由第 5 条判据保证。
REGISTRIES: list[tuple[str, str]] = [
    ("modules.ad_analysis.tools", "ad_analysis_tools"),
    ("modules.aigc_media.tools", "aigc_tools"),
    ("modules.competitor_intel.tools", "competitor_intel_tools"),
    ("modules.customer_service.tools", "customer_service_tools"),
    ("modules.listing_generator.tools", "listing_tools"),
    ("modules.product_research.tools", "product_research_tools"),
    ("modules.review_analyst.tools", "review_analyst_tools"),
    ("modules.secretary.navigation_tools", "navigation_tools"),
    # ⚠️ 这两个是**工厂函数**（`build_xxx(shop_id)`），不是模块级 list —— 名字必须
    #    写函数的真名。写成 "product_tools" 会 AttributeError（本文件初版就这么错过）。
    ("modules.secretary.product_tools", "build_product_tools"),
    ("modules.secretary.shop_tools", "build_shop_tools"),
    ("modules.secretary.subscription_tools", "subscription_tools"),
]

#: 期望「需人工审批」的工具集合 —— **运行时推导**必须与它相等。
#: 这份名单写在测试里是**有意**的：测试层允许知道业务名（`ai_infra` 层不允许）。
#: 它的作用是「把推导结果钉住」——推导是实现的真源，这里是对账的另一侧。
EXPECTED_GATED = {"save_candidate", "create_ticket"}


# ============================================================
# 取注册表工具（运行时真源）
# ============================================================

_CACHE: dict[str, list] = {}


def _tools_of(modpath: str, attr: str) -> list:
    """import 注册表并取工具列表（工厂函数会按其必填参数个数补 None）。"""
    key = f"{modpath}:{attr}"
    if key in _CACHE:
        return _CACHE[key]
    mod = importlib.import_module(modpath)
    obj = getattr(mod, attr)
    if callable(obj) and not isinstance(obj, list):
        sig = inspect.signature(obj)
        n = len(
            [
                p
                for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
        )
        obj = obj(*([None] * n))
    tools = list(obj or [])
    _CACHE[key] = tools
    return tools


def _all_tools() -> list:
    out = []
    for modpath, attr in REGISTRIES:
        out.extend(_tools_of(modpath, attr))
    return out


def _tool_names_by_var() -> dict[str, set[str]]:
    """变量名 → 工具名集合（供 AST 侧解析 `tools=` 实参用）。"""
    return {attr: {t.name for t in _tools_of(modpath, attr)} for modpath, attr in REGISTRIES}


# ============================================================
# 1. 全部工具必须显式声明
# ============================================================


def test_every_tool_declares_side_effects():
    """全仓工具**全部**显式声明 `metadata["side_effects"]`，无一靠默认兜底。

    ★ 为什么要求「显式」而不满足于 fail-closed 的默认值：默认值保护的是
      「忘了声明」的运行期行为（安全方向），但它**不产生任何提示** ——
      一个没声明的写库工具会获得审批（好事），可没人知道它其实该被登记。
      显式声明让「哪些工具被审查过」成为一个可枚举的集合，而不是
      「除了声明过的，其余全靠猜」。
    """
    from ai_infra.tools.side_effects import is_declared

    undeclared = [t.name for t in _all_tools() if not is_declared(t)]
    assert not undeclared, (
        f"以下工具未声明副作用（必须在 from_function 里加 metadata=）：{sorted(undeclared)}"
        " —— 只读用 READ_ONLY_METADATA，有副作用用 SIDE_EFFECT_METADATA"
    )


# ============================================================
# 2. 写动词工具不得被豁免
# ============================================================


def test_write_verb_tools_are_never_exempted():
    """名字带写动词的工具，绝不允许被声明为只读。

    ★ 这是**独立于推导**的第二判据：判据 3 比的是集合，一旦集合本身被改
      （例如把某个写库工具名从 EXPECTED_GATED 也一并删掉），3 会被蒙混过关；
      本条直接看「名字 vs 声明」这一对，改不动两边就无法绕过。
    """
    from ai_infra.tools.side_effects import write_verb_violations

    bad = write_verb_violations(_all_tools())
    assert not bad, (
        f"以下工具名字是写操作、却被声明为只读：{bad} —— "
        "它极可能真的写库（名字是廉价但强的信号），请改回 SIDE_EFFECT_METADATA，"
        "或改名以反映它其实不写。"
    )


# ============================================================
# 3. 推导结果 == 期望集合
# ============================================================


def test_gated_set_matches_policy_derivation():
    """运行时推导出的「需审批工具集合」必须等于 `EXPECTED_GATED`。

    ★ 两个方向都会红，且都是**有用的**红：
      · 集合变小 ⇒ 某个写库工具被改成只读（安全属性被削弱）；
      · 集合变大 ⇒ 新增了写库工具（好事，但必须把它的审批纳入审查：
        checkpointer 是否就位、前端审批卡是否能渲染它、是否有落库测试）。
    """
    from ai_infra.tools.side_effects import derive_hitl_tools

    gated = set(derive_hitl_tools(_all_tools()))
    assert gated == EXPECTED_GATED, (
        f"审批工具集合漂移：实际 {sorted(gated)}，期望 {sorted(EXPECTED_GATED)}。\n"
        "  实际比期望少 ⇒ 有写库工具被误声明为只读（危险）；\n"
        "  实际比期望多 ⇒ 新增了有副作用的工具，请把它纳入审查后更新 EXPECTED_GATED。"
    )


def test_gated_tools_are_relatively_few():
    """反向哨兵：审批集合**不得**膨胀到「几乎所有工具都要审批」。

    ★ 为什么这条必要：判据 3 只保证「集合 == 期望」。若有人图省事，
      把所有工具的声明都删了（fail-closed 会把 54 个全判为需审批），
      再顺手把 EXPECTED_GATED 改成 54 个 —— 判据 3 仍然绿，但 HITL 事实上
      已经不可用（每个只读查询都要老板点一次「批准」）。
      这条给「审批面」设一个上限，防的是**方向正确但程度失控**。
    """
    from ai_infra.tools.side_effects import derive_hitl_tools

    tools = _all_tools()
    gated = derive_hitl_tools(tools)
    assert len(gated) <= 6, (
        f"需审批工具多达 {len(gated)} / {len(tools)} —— 审批面失控，"
        "HITL 会退化成人人点确认的噪音。请检查是不是大量只读工具漏了声明。"
    )


# ============================================================
# 4. 装配了「含副作用注册表」的构造点必须有 checkpointer
# ============================================================


def _module_level_list_vars(tree: ast.Module) -> dict[str, set[str]]:
    """文件内 `xxx = [StructuredTool.from_function(name=...), ...]` → {变量名: 工具名}。"""
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)):
            continue
        names = set()
        for el in node.value.elts:
            if isinstance(el, ast.Call):
                for kw in el.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.add(kw.value.value)
        if not names:
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out[tgt.id] = names
    return out


def _names_in_expr(node: ast.AST) -> set[str]:
    """把 `a + b + c` / `[x, y]` / `a` 这类实参展开成变量名集合。"""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _names_in_expr(node.left) | _names_in_expr(node.right)
    if isinstance(node, ast.List):
        out: set[str] = set()
        for el in node.elts:
            out |= _names_in_expr(el)
        return out
    return set()


def test_agents_compiling_gated_registries_carry_checkpointer():
    """装配了「含副作用工具」的注册表的构造点，必须同现 checkpointer。

    ★ 这条取代了旧判据「凡出现 `hitl_tools=` 关键字就必须给 checkpointer」。
      旧判据在批 B2 之后**失去了目标**：手写名单已被删除，全仓再无
      `hitl_tools=` 构造点，而它的首行 `assert hits` 会因此变红 ——
      那是「门禁的墓志铭」：需求变了，旧断言从资产变成负资产。
      新判据不问关键字，只问**装配内容**：这套注册表里有没有副作用工具？

    ★ 为什么这层耦合必须钉住：`interrupt()` 在**没有 checkpointer 的图上直接抛**
      （而不是「降级为不审批」）。所以「工具挂了审批」与「图绑了 checkpointer」
      是同一个前提，却写在同一个构造调用的不同行上 —— 后来的人删掉其中一行
      不会报错，直到线上某次审批型操作才炸。
    """
    from ai_infra.tools.side_effects import has_side_effects

    gated_registry_vars = {
        attr
        for modpath, attr in REGISTRIES
        if any(has_side_effects(t) for t in _tools_of(modpath, attr))
    }
    assert gated_registry_vars, (
        "没有任何注册表含副作用工具 —— 本门禁失去目标（`all(...)` 会真空通过）"
    )

    # 需要 AST 侧的「变量名 → 工具名」映射：既看注册表模块自身，也看装配点所在
    # 文件里的模块级列表（后者用于 `tools=[...]` 内联写法）。
    by_var = _tool_names_by_var()
    gated_names = {n for v in gated_registry_vars for n in by_var.get(v, set())}

    checked = 0
    violations: list[str] = []
    for p in sorted(BACKEND.rglob("*.py")):
        parts = set(p.parts)
        if "tests" in parts or "__pycache__" in parts or "alembic" in parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), str(p))
        except SyntaxError:  # pragma: no cover
            continue
        local_lists = _module_level_list_vars(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)):
                continue
            fname = ast.unparse(node.func)
            if not fname.endswith("BaseAgent"):
                continue
            kw = {k.arg: k for k in node.keywords if k.arg}
            if "tools" not in kw:
                continue
            refs = _names_in_expr(kw["tools"].value)
            # 展开：变量名可能是本文件里的模块级列表，也可能是注册表变量
            tool_names = set()
            for r in refs:
                tool_names |= by_var.get(r, set()) | local_lists.get(r, set())
            if not (tool_names & gated_names):
                continue  # 这套工具全是只读 ⇒ 不需要 checkpointer
            checked += 1
            rel = p.relative_to(BACKEND)
            if "checkpointer" not in kw:
                violations.append(f"{rel}:{node.lineno} 装配了含副作用工具却没给 checkpointer")
                continue
            val = kw["checkpointer"].value
            if isinstance(val, ast.Constant) and val.value is None:
                violations.append(f"{rel}:{node.lineno} checkpointer 被显式写成 None")

    assert checked > 0, (
        "全仓找不到任何「装配了含副作用工具的 BaseAgent 构造点」—— "
        "本门禁失去目标。若确实移除了 HITL 接线，请一并删除本门禁并说明原因。"
    )
    assert not violations, (
        "以下构造点装配了需审批的工具，却没有可用的 checkpointer —— "
        "`interrupt()` 会在无 checkpointer 的图上直接抛，审批闸门不可用：\n  "
        + "\n  ".join(violations)
    )


# ============================================================
# 5. 与 tool_registry_guard 的注册表清单保持一致
# ============================================================


def test_registry_lists_agree_with_tool_registry_guard():
    """本文件的注册表清单不得与 `test_tool_registry_guard.REGISTRY_FILES` 漂移。

    ★ 为什么要这条：两份清单分别服务「工具名唯一性」与「副作用声明」两个门禁。
      新增一个注册表时只登记一处 ⇒ 另一个门禁**静默放行**它（不在扫描面内），
      而它是绿的 —— 典型的「门禁真空区」。
    """
    from tests.test_tool_registry_guard import REGISTRY_FILES

    mine = {f"{modpath.replace('.', '/')}.py" for modpath, _attr in REGISTRIES}
    theirs = set(REGISTRY_FILES)
    missing = theirs - mine
    extra = mine - theirs
    assert not missing, f"本文件漏登记注册表（tool_registry_guard 有、这里没有）：{sorted(missing)}"
    assert not extra, f"本文件多登记了 tool_registry_guard 没有的注册表：{sorted(extra)}"

"""模块分层门禁：内核 / 共享领域 / 插件 三层 + **插件之间互不 import**（P1-4）

老板的长文给的红线是「内核禁止 import 插件」。第 137 轮已经把
`core → modules` 钉住了（`test_core_layering.py`）。但还剩一个空白：
**`modules/` 内部之间**没有任何约束 —— 实测有 13 条直接 import 边，其中 11 条
发生在**模块顶层**（import 期）。

分清楚这 11 条的性质之后，只有一件事是真的要禁止的：

    插件 → 插件 的**顶层** import

其余 10 条里，7 条是「依赖 `stores`/`billing`」—— 那不是插件互耦，而是
**内核实体被物理放在了 `modules/` 下**（`stores` 是全库唯一带
`tenant_id + account_id + owner_id` 三件套的表，且被 7 个模块依赖）。

★ 第 140 轮更新（本段原先写的是「物理不动」，**已作废**，别照它推理）：
  `StoreRecord` + `SHOP_ORDER_BY` 已**实际搬迁**到 `core/stores/models.py`，
  `modules/stores/` 只剩 HTTP 面 `router.py`（`/api/v1/stores` 原地不动）。
  当时列出的顾虑逐条实测后**都不成立**：`StoreRecord` 零 `relationship()`
  （不碰 1:1 的 Base.registry 地雷）、表名仍是 `stores_store`
  （autogenerate 零 diff）、前端契约不变。详见 `core/stores/models.py` docstring。
  ⇒ 本文件的**清单仍然必要** —— 分层归属是一个**决定**，AST 推不出来。
    但职责已收窄为「`modules/` 之间还能不能横向依赖」；
    「跨模块引用能不能伸手进包内部」改由 `test_module_facades.py` 管。

★ 两个轴，别混（读者最常在此处绕晕）：
  本表的 KERNEL / SHARED / PLUGIN 是**语义分层** —— 「这东西属不属于平台内核」，
  是决策记录；而「实体该住 `core/` 还是 `modules/`」用的是**入度判据** ——
  「被 ≥2 个别的模块 import ⇒ 基础域 ⇒ 该住 core/」。
  同一条入度判据下 `billing` 只有 1 个跨模块消费者 ⇒ 实体留 `modules/`；
  但它**语义上**仍是平台内核 ⇒ 本表继续标 KERNEL。两者不矛盾。

## 为什么这里必须有一张「名单」

别的门禁我都尽量避开名单（用代码形态判）。但**分层归属本身就是一个决定**：
没人能靠 AST 推断出「`billing` 属于内核」——那需要知道它做的是订阅/计费/配额。
所以这张清单不是「人工枚举的脆弱名单」，而是**决策记录**。它安全的三个理由：

  1. 每条都写了理由（下面的注释）；
  2. 断言是**集合相等** —— 模块增删、层级调整都必须改这个文件，改不了偷偷漂移；
  3. 门禁本体（谁 import 谁）走 **AST**，不靠人盯。

## 三层与允许的依赖方向

| 层 | 含义 | 例 |
|---|---|---|
| KERNEL | 平台内核，行业无关，任何垂直 SaaS 都需要 | `core/*`、`stores`、`billing` |
| SHARED | 行业内**跨功能共享**的实体 / 适配器 | `products`、`amazon_sp`、`conversation`、`candidates` |
| PLUGIN | 面向用户的功能模块 | `secretary`、`monitors`、`assets`、… |

允许：`PLUGIN → SHARED/KERNEL`、`SHARED → SHARED/KERNEL`、`KERNEL → KERNEL`
禁止：`PLUGIN → PLUGIN`（顶层）、`SHARED → PLUGIN`（顶层）、`KERNEL → 任何 modules`（顶层）

★ 只管**import 期**（模块顶层）的边。函数内延迟 import 不在本门禁范围 ——
  那类边是注册/引导/粒度查询，钉住它们会让「每加一个 seed 模块就要改测试」。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

KERNEL = "KERNEL"
SHARED = "SHARED"
PLUGIN = "PLUGIN"

_RANK = {KERNEL: 0, SHARED: 1, PLUGIN: 2}

#: ------------------------------------------------------------------ 决策记录
#: 每个 `modules/` 子目录必须在这里被分类（集合相等断言 ⇒ 新模块不能悄悄进来）。
#: 层级与理由**分两张表**，且断言键集合相等 ⇒ 加一个模块必须同时给出层级和理由。
MODULE_LAYERS: dict[str, str] = {
    # ---- KERNEL：平台内核。行业无关，任何垂直 SaaS 都要有。
    "billing": KERNEL,
    "stores": KERNEL,

    # ---- SHARED：行业内的共享领域 / 外部平台适配器。
    "products": SHARED,
    "amazon_sp": SHARED,
    "conversation": SHARED,
    "candidates": SHARED,
    "memory": SHARED,

    # ---- PLUGIN：面向用户的功能模块。插件之间**不得**顶层互相 import。
    "ad_analysis": PLUGIN,
    "aigc_media": PLUGIN,
    "assets": PLUGIN,
    "competitor_intel": PLUGIN,
    "customer_service": PLUGIN,
    "knowledge_base": PLUGIN,
    "listing_generator": PLUGIN,
    "monitors": PLUGIN,
    "platform_rules": PLUGIN,
    "product_research": PLUGIN,
    "review_analyst": PLUGIN,
    "secretary": PLUGIN,
    "voice_clone": PLUGIN,
}

#: 每条分类的**理由**。这是决策记录的一部分 —— 没有理由的分类等于没分类。
MODULE_REASONS: dict[str, str] = {
    "billing":
        "订阅 / 套餐 / 计价 / 额度 —— 长文自己把「租户管理：配额、订阅套餐、计费、额度」列进平台内核",
    "stores":
        "店铺（租户容器）的 **HTTP 契约面**（`/api/v1/stores`）。内核实体 StoreRecord 与"
        "排序真源 SHOP_ORDER_BY 已于第 140 轮归位 `core/stores/`，本包只剩 router；"
        "仍留 KERNEL：它服务的对象是内核实体，不该被插件反向依赖",
    "products":
        "SPU/SKU 商品主数据。被 candidates、secretary 等多个功能引用，是跨功能共享实体",
    "amazon_sp":
        "亚马逊平台数据接入适配器（含 data_sources 抽象 + 工厂）。属「平台适配」而非业务功能",
    "conversation":
        "Agent 会话记忆（跨会话上下文）。被 secretary 消费，是面向 Agent 的基础设施",
    "candidates":
        "候选 / 选品记忆。被 product_research 消费，属跨功能共享的记忆实体",
    "memory":
        "跨会话**长期记忆**（用户画像 / 偏好）。被 secretary 消费以注入 system prompt，"
        "与 conversation 同为面向 Agent 的基础设施；★ 按 owner_id（人）分片、"
        "不是 thread_id（会话）⇒ 这也是它另立一包的原因",
    "ad_analysis": "广告分析视图；只被前端直接调用，无模块间顶层引用 ⇒ 插件",
    "aigc_media": "AIGC 图片 / 视频生成；产出物经 assets 落库，模块间无顶层共享 ⇒ 插件",
    "assets": "素材库；仅被 secretary 的**函数内**工具引用（非顶层），无共享需求 ⇒ 插件",
    "competitor_intel": "竞品情报；自足功能，无其它模块顶层引用 ⇒ 插件",
    "customer_service": "智能客服；自足功能，无其它模块顶层引用 ⇒ 插件",
    "knowledge_base": "知识库；自足功能，无其它模块顶层引用 ⇒ 插件",
    "listing_generator": "Listing 文案生成；自足功能，无其它模块顶层引用 ⇒ 插件",
    "monitors": "监控告警；自足功能，无其它模块顶层引用 ⇒ 插件",
    "platform_rules": "平台规则库；自足功能，无其它模块顶层引用 ⇒ 插件",
    "product_research": "选品研究；引用 candidates 走**函数内**延迟 import（非顶层）⇒ 插件",
    "review_analyst": "运营复盘；经数据源工厂消费 amazon_sp（SHARED），自身不被引用 ⇒ 插件",
    "secretary": "店秘书（主对话 Agent）；顶层依赖 products / stores / billing / conversation，"
                 "全部落在 SHARED / KERNEL ⇒ 插件",
    "voice_clone": "声音复刻；自足功能，无其它模块顶层引用 ⇒ 插件",
}


# ================================================================ 扫描


def _rel(p: Path) -> str:
    return p.relative_to(BACKEND).as_posix()


def _module_of(rel: str) -> str | None:
    """`modules/monitors/router.py` → `monitors`。"""
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "modules":
        return parts[1]
    return None


def _import_time_reverse_edges() -> set[tuple[str, str]]:
    """产出**在 import 期就会执行**的 `modules.A → modules.B` 边（A/B 为模块名，A != B）。"""
    edges: set[tuple[str, str]] = set()
    for p in sorted(MODULES.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = _rel(p)
        src = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        cur = _module_of(rel)
        if cur is None:
            continue

        # 收集函数边界 —— 判「import 是否在函数里」必须看祖先链，
        # 不能用行首缩进：多行 import 的后续行缩进非 0，会把顶层语句误判成函数内。
        funcs = [(n.lineno, n.end_lineno or n.lineno)
                 for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

        def in_func(lineno: int) -> bool:
            return any(a <= lineno <= b for a, b in funcs)

        for n in ast.walk(tree):
            targets: list[tuple[int, str]] = []
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("modules."):
                targets.append((n.lineno, n.module))
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.startswith("modules."):
                        targets.append((n.lineno, a.name))
            for lineno, m in targets:
                to = m.split(".")[1]
                if to != cur and not in_func(lineno):
                    edges.add((cur, to))
    return edges


def _violates(src_layer: str, dst_layer: str) -> bool:
    if _RANK[dst_layer] < _RANK[src_layer]:
        return False                     # 往上依赖（插件→共享/内核）允许
    if _RANK[dst_layer] == _RANK[src_layer]:
        return src_layer == PLUGIN       # 同层：插件之间禁止；内核/共享内部允许
    return True                          # 往下依赖（内核→共享/插件）禁止


# ================================================================ 用例


def test_every_module_is_classified():
    """每个 `modules/` 子目录都必须被分类 —— 新模块不能悄悄溜进来。"""
    actual = {p.name for p in MODULES.iterdir()
              if p.is_dir() and p.name != "__pycache__"}
    declared = set(MODULE_LAYERS)
    missing = sorted(actual - declared)
    stale = sorted(declared - actual)
    assert not missing, (
        "以下模块没有分层归属，请在 MODULE_LAYERS 里声明它是内核 / 共享 / 插件，"
        "并写一句理由（这是决策记录，不是装饰）：\n  " + "\n  ".join(missing)
    )
    assert not stale, (
        "MODULE_LAYERS 里声明了已不存在的模块（改了目录忘了改这里）：\n  "
        + "\n  ".join(stale)
    )


def test_layer_values_are_known():
    bad = {m: lay for m, lay in MODULE_LAYERS.items() if lay not in _RANK}
    assert not bad, f"未知层级取值：{bad}"


def test_every_classification_carries_a_reason():
    """层级表与理由表的键必须一一对应 —— 分类必须带理由，理由必须对应真实模块。"""
    only_layer = sorted(set(MODULE_LAYERS) - set(MODULE_REASONS))
    only_reason = sorted(set(MODULE_REASONS) - set(MODULE_LAYERS))
    assert not only_layer, f"这些模块有层级但没写理由：{only_layer}"
    assert not only_reason, f"这些理由对应不到已声明的模块：{only_reason}"
    thin = [m for m, r in MODULE_REASONS.items() if len(r.strip()) < 12]
    assert not thin, f"这些模块的理由太短（等于没写）：{thin}"


def test_no_plugin_imports_another_plugin_at_import_time():
    """插件之间不得在 **import 期**互相 import（长文红线：插件互相独立）。"""
    reports: list[str] = []
    for src, dst in sorted(_import_time_reverse_edges()):
        ls, ld = MODULE_LAYERS[src], MODULE_LAYERS[dst]
        if _violates(ls, ld):
            reports.append(f"  modules/{src} ({ls}) -> modules/{dst} ({ld})")
    assert reports == [], (
        "以下 import 期依赖跨过了层级边界（插件之间的共享逻辑应下沉到 SHARED/KERNEL 层，"
        "或改成函数内延迟 import）：\n" + "\n".join(reports)
    )


def test_kernel_modules_do_not_depend_on_modules_tree_at_import_time():
    """内核模块（billing / stores）不得在 import 期依赖任何其它 `modules/*`。"""
    reports: list[str] = []
    for src, dst in sorted(_import_time_reverse_edges()):
        if MODULE_LAYERS[src] == KERNEL:
            reports.append(f"  modules/{src} (KERNEL) -> modules/{dst} "
                           f"({MODULE_LAYERS[dst]})")
    assert reports == [], (
        "内核模块反向依赖了 modules/ 树 —— 内核一旦依赖行业代码就无法跨行业复用：\n"
        + "\n".join(reports)
    )


# ================================================================ 自检


def test_rules_are_expressible():
    """规则自检：三层之间的允许/禁止矩阵必须与文档一致。"""
    cases = [
        (PLUGIN, KERNEL, False),      # 插件 → 内核：允许
        (PLUGIN, SHARED, False),      # 插件 → 共享：允许
        (PLUGIN, PLUGIN, True),       # 插件 → 插件：**禁止**
        (SHARED, KERNEL, False),      # 共享 → 内核：允许
        (SHARED, SHARED, False),      # 共享 → 共享：允许
        (SHARED, PLUGIN, True),       # 共享 → 插件：**禁止**（会形成环）
        (KERNEL, KERNEL, False),      # 内核 → 内核：允许
        (KERNEL, SHARED, True),       # 内核 → 共享：**禁止**
        (KERNEL, PLUGIN, True),       # 内核 → 插件：**禁止**（长文红线）
    ]
    for src, dst, want in cases:
        got = _violates(src, dst)
        assert got is want, f"{src} -> {dst} 判定为 {got}，期望 {want}"


def test_edge_scanner_detects_top_level_but_ignores_function_level():
    """边的扫描器必须能区分「顶层」与「函数内」——包括多行 import 形态。"""
    src_top = "from modules.products.db_model import SpuRecord\n"
    src_func = "def f():\n    from modules.products.db_model import SpuRecord\n"
    src_multi = "from modules.products.db_model import (\n    SpuRecord,\n)\n"

    def top_level_targets(source: str) -> list[str]:
        tree = ast.parse(source)
        funcs = [(n.lineno, n.end_lineno or n.lineno) for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        out = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("modules."):
                if not any(a <= n.lineno <= b for a, b in funcs):
                    out.append(n.module.split(".")[1])
        return out

    assert top_level_targets(src_top) == ["products"]
    assert top_level_targets(src_func) == [], "函数内 import 不该被算成 import 期依赖"
    assert top_level_targets(src_multi) == ["products"], (
        "多行 import 的后续行缩进非 0，用行首缩进判定会漏报 —— 必须看 AST 祖先链"
    )


def test_current_tree_really_exercises_the_gate():
    """防「路径写错 ⇒ 空集 ⇒ 恒绿」：确认扫描确实看到了模块与边。"""
    actual = {p.name for p in MODULES.iterdir()
              if p.is_dir() and p.name != "__pycache__"}
    assert len(actual) >= 15, f"只发现 {len(actual)} 个模块，扫描路径可疑"
    edges = _import_time_reverse_edges()
    assert edges, "一条 import 期 modules→modules 边都没扫到，扫描逻辑可疑"

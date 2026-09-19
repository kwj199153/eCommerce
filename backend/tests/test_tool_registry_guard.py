"""
工具注册表门禁（第 143 轮 A3 建立）。

背景
----
老板问：「32 个工具有哪些是什么，确定不是多于无用的历史遗留吗？」
实测（探针 `r143_a3_recon.py`，AST 级「注册表 × 消费点」对账）得到两个结论：

1. **真接线的工具 = 21 个**：`listing_tools`(8) / `product_research_tools`(5) /
   `navigation_tools`(5) / `subscription_tools`(1) / `build_product_tools`(1) /
   `build_shop_tools`(1) —— 它们被某个 Agent 作为 `BaseAgent(tools=...)` 真的绑上了。
2. **悬空（注册了但全仓无消费点）= 32 个**，精确等于老板说的数字：
   `aigc_tools`(8) + `ad_analysis_tools`(6) + `customer_service_tools`(4) +
   `competitor_intel_tools`(8) + `review_analyst_tools`(6)。
   实测证据：这些模块的 Agent 子类 `__init__` 里只有一句 `super().__init__()`，
   工具数恒为 0（运行时日志 `✅ Agent 初始化完成: AIGCMediaAgent | 工具数: 0`）。
   （A3 之后为 33 —— 新增的 `generate_assets` 随悬空的 `aigc_tools` 一起悬空。）

本文件钉住的四件事
------------------
1. **工具名跨注册表全局唯一**（`test_tool_names_globally_unique`）。
   A1 曾出现 `compare_competitors` 在两个注册表里重名 —— 名字重了，LLM 选哪个都
   不可预期。判据走 AST 取 `name=` 字面量，不看注释（本项目踩过「源码字符串
   包含」被 docstring 骗过的坑）。
2. **desc 里互相指路的工具名必须真实存在**
   （`test_desc_cross_references_resolve`）。A3 把 `generate_product_image` 的
   desc 改成指向 `generate_assets` —— 好处是 LLM 能选对，代价是**引入了一条隐式
   依赖**：被指的工具一旦改名/删除，desc 立刻变成新的误导。所以把它钉住。
3. **悬空注册表棘轮**（`test_orphan_registry_ratchet`）。既有 32 个等后续批次处置，
   但**不许再新增**「注册了却没人绑」的注册表。棘轮只许往下走：把某个悬空注册表
   要么绑上、要么删掉 —— 两种都能让本测试继续绿。
4. **能力承诺与实现一致**（`test_capability_claim_matches_implementation`）。
   这是 A3 的正题：`generate_product_image` 的 desc 原写「当用户想做图/生成产品图/
   主图时使用」，而实现返回体里**没有任何图片 URL**，只有提示词 + 一行
   「当前为模拟模式」。desc 承诺 > 实现能力 = 把 LLM 往错路上引。
   现在新的 `generate_assets` 才是真出图（实测 wanx2.1-t2i-turbo 出图 → 转存
   `/static/aigc/*.png`）。本条把「desc 说不产出图片」⇔「实现真的不含 url 键」
   锁成一对，任一侧单方面改动都会红。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

# ---- 工具注册表所在文件（A3 对账出的全集）----
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
    # ★ 第 145 轮 批 B1 补登：这两个注册表此前**不在本名单里**（A3 对账时漏了），
    #   于是本文件的三条判据（工具名唯一 / desc 交叉引用 / 悬空棘轮）对它们
    #   全部**静默放行** —— 看着门禁齐全，实际是一片真空区。
    #   它们形如 `def build_xxx_tools(...) -> list`（工厂函数，不是模块级 list 字面量），
    #   所以 `_module_level_tool_lists()` 看不见它们、棘轮不受影响；
    #   但 `_iter_registry_calls()` 是 AST 扫 `from_function`，一加就能覆盖。
    #   促成这次补登的是 `tests/test_hitl_policy.py` 的
    #   `test_registry_lists_agree_with_tool_registry_guard` —— 两份清单对账后
    #   发现差异，正是它该干的事。
    "modules/secretary/product_tools.py",
    "modules/secretary/shop_tools.py",
]

# ---- 已知悬空注册表（注册了但全仓无消费点）。棘轮：只许减少，不许增加。----
KNOWN_ORPHAN_REGISTRIES = {
    "modules/aigc_media/tools.py::aigc_tools",
    "modules/ad_analysis/tools.py::ad_analysis_tools",
    "modules/customer_service/tools.py::customer_service_tools",
    "modules/competitor_intel/tools.py::competitor_intel_tools",
    "modules/review_analyst/tools.py::review_analyst_tools",
}
ORPHAN_TOOL_BUDGET = 33
# ↑ 32 = A3 对账出的存量（aigc 8 + ad 6 + cs 4 + competitor 8 + review 6）；
#   33 = 存量 + A3 新增的 `generate_assets`。
#   注意这个 +1 本身是个信号：A3 把「真能力」注册进了 `aigc_tools`，而这个注册表
#   正是悬空的 —— 新增的工具随它一起悬空。所以本批次只把"数据源/描述"做真，
#   悬空（绑上 or 删掉）必须由后续批次处置，否则 A3 的效果只停在纸面。

# ---- desc 里允许出现的非工具 snake_case token（有依据的例外）----
# `open_drawer` 是订阅工具 desc 里给 LLM 的**前端动作提示**（抽屉），本仓并无此工具，
# 也不是笔误。若要新增例外，必须在这里写明理由。
#
# ★ 第 145 轮 批 B1 新增两项 —— 它们是 `switch_shop` 的**入参名**（第 145 轮把
#   `modules/secretary/{shop,product}_tools.py` 补登进 REGISTRY_FILES 后，本判据
#   第一次扫到它们）。入参名写在 desc 里是**正确做法**（告诉 LLM 该传什么），
#   不该被当成「引用了不存在的工具名」：
#     · `shop_name`     —— `switch_shop` 的首选入参（店铺全名或片段）；
#     · `platform_nth`  —— `switch_shop` 的平台内序号入参。
DESC_NON_TOOL_TOKENS = {"open_drawer", "shop_name", "platform_nth"}

# 图片 URL 语义的键名（判「实现到底出不出图」用）
IMAGE_URL_KEYS = {"url", "image_url", "imageUrl", "images", "image", "assets"}

# 否定/限定声明词（desc 里声明「我做不到 X」）
DENIAL_WORDS = ("不生成", "不返回", "不出图", "不产出")


# ============================================================
# 通用 AST 工具
# ============================================================

def _parse(rel: str) -> ast.Module:
    return ast.parse((BACKEND / rel).read_text(encoding="utf-8", errors="replace"))


def _all_py() -> list[Path]:
    return [p for p in MODULES.rglob("*.py") if "__pycache__" not in p.parts]


def _iter_registry_calls(tree: ast.Module):
    """产出所有 StructuredTool.from_function(...) 调用节点。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("from_function"):
            yield node


def _registry_name_and_desc(node: ast.Call):
    """抽 (name, coroutine_name, description)。取不到的维度返回 None。"""
    name = coro = desc = None
    for kw in node.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            name = kw.value.value
        elif kw.arg == "coroutine":
            coro = ast.unparse(kw.value)
        elif kw.arg == "description":
            try:
                desc = ast.literal_eval(kw.value)
            except (ValueError, SyntaxError):
                desc = None
    return name, coro, desc


def _tool_names_by_file() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rel in REGISTRY_FILES:
        p = BACKEND / rel
        if not p.exists():
            continue
        names = []
        for call in _iter_registry_calls(_parse(rel)):
            nm, _c, _d = _registry_name_and_desc(call)
            if nm:
                names.append(nm)
        out[rel] = names
    return out


def _module_level_tool_lists(tree: ast.Module) -> list[tuple[str, list[str], int]]:
    """模块级 `xxx_tools = [ ... ]` → [(var, [工具名], 行号)]。只认 list 字面量。"""
    found = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.endswith("_tools"):
                    names = []
                    for el in node.value.elts:
                        nm = None
                        if isinstance(el, ast.Call):
                            for kw in el.keywords:
                                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                                    nm = kw.value.value
                        if nm:
                            names.append(nm)
                    found.append((tgt.id, names, node.lineno))
    return found


# ============================================================
# 1. 工具名跨注册表全局唯一
# ============================================================

def test_tool_names_globally_unique():
    """同一个工具名不得出现在两个注册表里（A1 的 `compare_competitors` 重名事故）。

    为什么必须唯一：LLM 只拿到工具名 → 名字冲突时它无法表达"我要哪一个"，
    选中的是哪个完全取决于 bind_tools 的顺序 —— 不可预期、不可测试。
    """
    by_file = _tool_names_by_file()
    owner: dict[str, list[str]] = {}
    for rel, names in by_file.items():
        for nm in names:
            owner.setdefault(nm, []).append(rel)

    dups = {nm: files for nm, files in owner.items() if len(files) > 1}
    assert not dups, f"工具名跨注册表重复：{dups}"
    # 注册表本身也不许内部重名
    for rel, names in by_file.items():
        assert len(names) == len(set(names)), f"{rel} 内部工具名重复：{names}"
    assert len(owner) >= 50, f"工具名总数异常偏少（{len(owner)}），注册表可能没被读全"


# ============================================================
# 2. desc 交叉引用的工具名必须真实存在
# ============================================================

def test_desc_cross_references_resolve():
    """desc 里提到别的工具名时，那个工具必须真的存在。

    A3 把 `generate_product_image` 的 desc 改成「必须改用 generate_assets」——
    这条指路是给 LLM 看的，一旦被指的工具改名/删除，desc 就从"帮助"变成"新的误导"。
    """
    import re

    snake = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
    by_file = _tool_names_by_file()
    all_names = {nm for names in by_file.values() for nm in names}

    dangling = []
    for rel in REGISTRY_FILES:
        if not (BACKEND / rel).exists():
            continue
        for call in _iter_registry_calls(_parse(rel)):
            nm, _c, desc = _registry_name_and_desc(call)
            if not desc:
                continue
            for tok in set(snake.findall(desc)):
                if tok in all_names or tok in DESC_NON_TOOL_TOKENS:
                    continue
                dangling.append((rel, nm, tok))

    assert not dangling, (
        "desc 引用了不存在的工具名（要么改名后漏改 desc，要么需要登记例外）："
        + str(dangling)
    )


# ============================================================
# 3. 悬空注册表棘轮
# ============================================================

def test_orphan_registry_ratchet():
    """不许再新增「注册了却没人绑」的工具注册表。

    现状：32 个工具悬空（A3 对账），本批次只做"接数据源/注册真能力/改误导 desc"，
    悬空本身的处置（绑上 or 删掉）留待后续批次。
    棘轮语义：**只许减少** ——
      · 把某个悬空注册表绑到 Agent 上 → 它不再悬空 → 集合变小 → 仍绿；
      · 把某个悬空注册表删掉 → 集合变小 → 仍绿；
      · 新写一个没人绑的注册表 → 集合变大 → 红。
    """
    # 引用统计：全仓 AST 里对该名字的 Load 引用，排除 tests/ 与 __pycache__
    refs: dict[str, int] = {}
    for p in _all_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                refs[node.id] = refs.get(node.id, 0) + 1

    orphans = {}
    for rel in REGISTRY_FILES:
        p = BACKEND / rel
        if not p.exists():
            continue
        tree = _parse(rel)
        for var, names, _ln in _module_level_tool_lists(tree):
            # 同文件内的引用（如 listing_tools = _fine_grained_tools + ...）也算消费
            if refs.get(var, 0) > 0:
                continue
            orphans[f"{rel}::{var}"] = names

    new_orphans = set(orphans) - KNOWN_ORPHAN_REGISTRIES
    assert not new_orphans, (
        f"新增悬空注册表（注册了但全仓无消费点）：{sorted(new_orphans)}；"
        "要么把它绑给某个 Agent，要么删掉 —— 不要留下一个没人用的注册表。"
    )

    total = sum(len(v) for v in orphans.values())
    assert total <= ORPHAN_TOOL_BUDGET, (
        f"悬空工具数从 {ORPHAN_TOOL_BUDGET} 涨到 {total}（只许降不许升）"
    )


# ============================================================
# 4. 能力承诺与实现一致（A3 正题）
# ============================================================

def _method_return_dict_keys(rel: str, class_name: str, method: str) -> set[str]:
    """取某类某方法里 `return { ... }` 字面量的键集合（只看字面量，不追变量）。"""
    tree = _parse(rel)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name]:
        for fn in cls.body:
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == method:
                keys: set[str] = set()
                for node in ast.walk(fn):
                    if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                        for k in node.value.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                keys.add(k.value)
                return keys
    raise AssertionError(f"未找到 {rel} 的 {class_name}.{method}")


def _aigc_descs() -> dict[str, tuple[str | None, str | None]]:
    rel = "modules/aigc_media/tools.py"
    out = {}
    for call in _iter_registry_calls(_parse(rel)):
        nm, coro, desc = _registry_name_and_desc(call)
        if nm:
            out[nm] = (desc, coro)
    return out


def test_capability_claim_matches_implementation():
    """desc 的能力承诺必须与实现一致 —— 本条的起因就是 A3 那个"谎"。

    A3 前：`generate_product_image` 的 desc 写「当用户想做图/生成产品图/主图时使用」，
    而实现 (`AIGCMediaAgent.generate_product_image`) 的返回体里**没有任何图片 URL**，
    只有 prompt / 关键词 / 文案，外加一行 note「当前为模拟模式」。
    ⇒ LLM 被 desc 引导去调一个永远拿不到图的工具。**承诺 > 能力 = 误导。**

    现在锁成一对：
      · 事实侧：实现返回体不含任何图片 URL 键；
      · 承诺侧：它的 desc 必须显式声明「不产出图片」并指向真出图工具；
      · 对照侧：真出图工具的 desc **不得**含否定声明，且其 wrapper 真的调用出图服务。
    任一侧被单方面改动（例如有人"顺手"把否定声明删掉，或把实现改成返回假 URL）都会红。
    """
    facts = _method_return_dict_keys(
        "modules/aigc_media/agent_aigc.py", "AIGCMediaAgent", "generate_product_image"
    )
    url_keys = facts & IMAGE_URL_KEYS
    assert not url_keys, (
        f"generate_product_image 的实现里出现了图片 URL 键 {sorted(url_keys)} —— "
        "那它的 desc 就不该再声明「不返回图片文件」，两侧必须同时改。"
    )

    descs = _aigc_descs()
    assert "generate_product_image" in descs, "注册表里找不到 generate_product_image"
    assert "generate_assets" in descs, "注册表里找不到 generate_assets（A3 新增的真出图工具）"

    d_old, c_old = descs["generate_product_image"]
    assert d_old, "generate_product_image 缺 description"
    assert "generate_assets" in d_old, (
        "desc 必须把用户指向真出图工具 generate_assets，否则 LLM 无从选择"
    )
    # ★ 否定声明只判「自述段落」= 交叉引用之前的那一段。为什么必须切开：
    #   generate_assets 的 desc 里写「用 generate_product_image —— 它不出图」，
    #   那个「不出图」说的是**对方**，不是否认自己。朴素 `in desc` 会把这条误判成 FAIL。
    prefix_old = d_old.split("generate_assets")[0]
    assert any(w in prefix_old for w in DENIAL_WORDS), (
        "generate_product_image 的自述段落必须显式声明它不产出图片"
        "（实测其实现确实不含图片 URL），"
        f"当前自述 = {prefix_old!r}"
    )

    d_new, c_new = descs["generate_assets"]
    assert d_new, "generate_assets 缺 description"
    assert "generate_product_image" in d_new, (
        "generate_assets 的 desc 应说明与 generate_product_image 的分工"
    )
    prefix_new = d_new.split("generate_product_image")[0]
    assert not any(w in prefix_new for w in DENIAL_WORDS), (
        "generate_assets 是真出图工具，它的**自述段落**不该含否定声明，"
        f"当前自述 = {prefix_new!r}"
    )

    # 对照侧：wrapper 必须真的把请求交给出图服务（不是空壳）
    tools_tree = _parse("modules/aigc_media/tools.py")
    body = None
    for fn in tools_tree.body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == c_new:
            body = ast.unparse(fn)
    assert body is not None, f"注册表指向的 coroutine {c_new} 在 tools.py 里找不到"
    assert "generate_assets_service" in body, (
        f"{c_new} 必须调用 generate_assets_service，否则 desc 承诺的「真出图」没有落点"
    )


def test_aigc_tool_count_and_schema():
    """A3 后 aigc_tools = 9 个，且每个都带 args_schema（LLM 才能看到字段描述）。"""
    rel = "modules/aigc_media/tools.py"
    names = [nm for nm, _c, _d in
             (_registry_name_and_desc(c) for c in _iter_registry_calls(_parse(rel))) if nm]
    assert len(names) == 9, f"aigc_tools 应为 9 个，实为 {len(names)}: {names}"
    assert "generate_assets" in names

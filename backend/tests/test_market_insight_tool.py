# -*- coding: utf-8 -*-
"""选品大盘读口（`query_market_insight`）门禁（第 325 轮）。

## 动因（老板原话）

    对话截图：「现在哪个品类蓝海分最高」
    回复：「未识别出具体类目，已按全类目高潜方向扫描，发现 8 个蓝海方向」
          + 8 条候选商品 + 「要入库直接说『把第 1 个加进选品库』」
    追问：「他不是有选品大盘吗 为什么会回答不出来这个问题」
    要求：「让 agent 可以读数据库，**解耦前端界面大盘**。用户不可能只问我这一个
          问题蓝海分，也可能其他大盘相关问题。」

## 根因（三层）

  ① 后端**没有读大盘的工具**：`product_research_tools` 里读 `market_snapshots`
     的工具数 = 0 —— 那份数据只有前端面板一条通道
     （`GET /product-research/market-insight/treemap`）；
  ② 问句被**关键词短路**：「品类」在 `blue_ocean` 组里 ⇒ 命中即
     `_process_query` 直接开挖，LLM 与工具全程未参与；
  ③ 「蓝海分」有**三份不同口径**（类目级 `market_snapshots.blue_ocean_score`
     / 关键词级 `_calculate_opportunity_score` / 商品级
     `_calculate_blue_ocean_scores`）⇒ 即便答了也未必是老板问的那一个。

## 修法

  登记一份 `MARKET_SNAPSHOT_SPEC`（**唯一真源**）⇒ 前端端点与 Agent 工具
  **同走** `core.library_query` 内核 ⇒ 面板上的数字与对话里的数字必然一致。

## 本文件钉什么（全部是**结构 / 契约**判据，不依赖数据库）

  A. 工具真的在容器里、且是**只读**声明（否则会被 HITL 审批拦下来）
  B. description 里的排序 / 过滤维度**来自 spec**（逐个核对，不是手抄的）
  C. tool 与 REST 端点**同源**：两处引用**同一个** spec 对象，且都真的用了它
  D. `invalid_argument` 的 `type` 字面量与 `modules/library/tools.py` **逐字一致**
  E. 缺归属时**硬拒绝**（不是回一个空大盘 —— 那会把「没选店铺」伪装成「没数据」）
  F. 与 `analyze_blue_ocean` 的分工写进了 description（否则模型两条都可能选）

★ 真数据路径（库里真有快照时工具返回什么、与面板是否逐字段一致）需要数据库，
  由探针 `probes/r325/r325_b1_treemap_parity.py` 覆盖，**不在 pytest 里**：
  `tests/` 直连共享生产库 ⇒ 全量不可复现（本仓既有判据）。
"""

import ast
import json
import pathlib

from ai_infra.tools.side_effects import has_side_effects
from modules.product_research.spec import MARKET_SNAPSHOT_SPEC
from modules.product_research.tools import product_research_tools

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: 工具与端点两侧的「函数名 → 文件」对（判据 C 用）
_ENDPOINT_SIDE = ("modules/product_research/service.py", "get_market_insight_treemap")
_TOOL_SIDE = ("modules/product_research/tools.py", "_query_market_insight_tool")


def _tool():
    return next((t for t in product_research_tools if t.name == "query_market_insight"), None)


# =====================================================================
# 判据 A
# =====================================================================

def test_tool_is_registered_in_the_agent_container():
    """工具必须在**被 `_build_router()` 真正绑定的那个容器**里。

    ★ 与本仓「可勾选但调不起来」同源：放进别的容器（或只写进目录表）都会
      产生一个模型看不到的工具，而**不报错**。
    """
    t = _tool()
    assert t is not None, (
        "`query_market_insight` 不在 `product_research_tools` 里 —— "
        "Agent 侧又变成「一个读大盘的工具都没有」了"
    )


def test_tool_is_read_only():
    """必须是只读声明：否则 `_wrap_hitl_tools()` 会把它包进人工审批。

    ★ 后果是荒谬的：老板问一句「现在哪个品类蓝海分最高」，界面弹出审批框。
    """
    assert not has_side_effects(_tool()), (
        "大盘读口被声明成有副作用 ⇒ 每次读大盘都要人工审批"
    )


# =====================================================================
# 判据 B
# =====================================================================

def test_description_dimensions_come_from_the_spec():
    """description 必须让模型看得见 spec 里的**每一个**排序 / 过滤维度与值域。

    ★ 这一条是「模型能不能答出『其他大盘相关问题』」的**前提**：白名单只写在
      服务端校验里、没写进 description ⇒ 模型根本不知道按什么排
      （第 216 轮实测过这个形态的代价：合法值只写在 docstring 里 ⇒ 传错值静默
      回空列表，与「真的没有」长得一样）。
    ★ 判据本身取自 **spec 对象**：手抄一份白名单进测试 = 第二份真源。
    """
    d = _tool().description

    missing = [k for k in MARKET_SNAPSHOT_SPEC.sort_keys if k not in d]
    assert not missing, f"description 里缺这些**排序**维度：{missing}"

    missing_f = [k for k in MARKET_SNAPSHOT_SPEC.filter_keys if k not in d]
    assert not missing_f, f"description 里缺这些**过滤**维度：{missing_f}"

    for key in MARKET_SNAPSHOT_SPEC.filter_keys:
        for value in MARKET_SNAPSHOT_SPEC.filters[key].values or ():
            assert value in d, f"过滤维度 {key!r} 的值域 {value!r} 没写进 description"

    assert MARKET_SNAPSHOT_SPEC.default_sort in d, "默认排序没写进 description"


# =====================================================================
# 判据 C
# =====================================================================

def test_tool_and_rest_endpoint_share_one_spec_object():
    """工具与前端端点必须引用**同一个** spec 对象（同一真源）。

    ★ 本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到。运维上最直观的后果是
      「面板上显示 71 分，对话里说 65 分」而没有任何一处报错。
    """
    import modules.product_research.service as svc
    import modules.product_research.tools as tl

    assert svc.MARKET_SNAPSHOT_SPEC is MARKET_SNAPSHOT_SPEC
    assert tl.MARKET_SNAPSHOT_SPEC is MARKET_SNAPSHOT_SPEC, (
        "tools.py 与 service.py 引用的不是同一个 spec 对象 —— 有人复制了一份？"
    )


def test_both_sides_really_use_the_spec_and_do_not_query_by_hand():
    """AST 层再钉一次：两边**真的用了**它，且都没自己写查询。

    ★ 只 import 不使用（放着好看的 `from ... import SPEC`）也能过「同一对象」那条；
      这里按**调用点**核对，并查「手写查询」的标识符（`select` / `scoped` /
      `async_session_factory`）。
    ★ 走 AST 而不是源码字符串：docstring 里写一句「此处不手写查询」就能骗过字符串
      判据 —— 本函数的 docstring 里**确实**写着「改前是手写 select/scoped」。
    """
    problems = []
    for rel, fn_name in (_ENDPOINT_SIDE, _TOOL_SIDE):
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name),
            None,
        )
        assert node is not None, f"找不到 {rel}::{fn_name}"
        used = any(isinstance(n, ast.Name) and n.id == "MARKET_SNAPSHOT_SPEC"
                   for n in ast.walk(node))
        if not used:
            problems.append(f"{rel}::{fn_name} import 了 spec 却没用它")
        idents = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        idents |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        bad = sorted(idents & {"select", "scoped", "async_session_factory"})
        if bad:
            problems.append(f"{rel}::{fn_name} 里出现了手写查询 {bad}")

    assert not problems, (
        "大盘取数没有收在 spec 一份实现上：\n  " + "\n  ".join(problems)
        + "\n⇒ 两边各写一份查询，迟早漂移，而且只有一份会被测到。"
    )


# =====================================================================
# 判据 D
# =====================================================================

def test_invalid_argument_type_matches_the_library_tools():
    """两个工具层的「参数非法」出参 `type` 必须**逐字一致**。

    ★ 模型靠这个字面量决定处置：`invalid_argument` ⇒ **换个值再试一次**；
      若这边写成别的词，模型会把它当成「大盘读不出来」⇒ 老板去查一个不存在的
      故障（归因错方向）。本仓同类真源：`modules/library/tools.py::_invalid`。
    """
    from modules.library.tools import _invalid as _lib_invalid  # noqa: PLC2701
    from modules.product_research.tools import _invalid_argument  # noqa: PLC2701

    mine = json.loads(_invalid_argument("boom"))
    ref = json.loads(_lib_invalid("boom"))
    assert mine["type"] == ref["type"] == "invalid_argument", (
        f"两处「参数非法」的 type 不一致：{mine['type']!r} vs {ref['type']!r}"
    )


# =====================================================================
# 判据 E
# =====================================================================

async def test_missing_shop_is_hard_refused_not_an_empty_market():
    """缺归属（没选店铺）时必须**硬拒绝**，不能回一个空大盘载荷。

    ★ 两者对老板的处置完全不同：前者该去选店铺，后者该去接数据源。
      回一个 `items: []` 会把它们压成同一件事（同族判据：fail-closed 不等于
      「静默返回空」）。
    """
    from modules.product_research.tools import _query_market_insight_tool  # noqa: PLC2701

    out = await _query_market_insight_tool()
    payload = None
    try:
        payload = json.loads(out)
    except (TypeError, ValueError):
        pass
    assert payload is None, f"缺归属时回了一个结构化载荷（应为一句话拒绝）：{out!r}"
    assert "店铺" in out, f"缺归属时没说清原因：{out!r}"


# =====================================================================
# 判据 F
# =====================================================================

def test_description_distinguishes_from_analyze_blue_ocean():
    """description 必须点明与 `analyze_blue_ocean` 的**分工**。

    ★ 两条工具都跟「蓝海」有关，但一条读**类目级大盘**、一条现挖**商品级候选**；
      不写清分工，模型选错工具的后果正是老板那次投诉的形态
      （问「哪个品类蓝海分最高」却拿到 8 个候选商品）。
    """
    d = _tool().description
    assert "analyze_blue_ocean" in d, "没写与 analyze_blue_ocean 的分工"
    assert "类目" in d, "没点明本工具是**类目级**"
    assert "category_path" in d, "没提 category_path"
    # ★ 断言的是「**不支持模糊匹配**」这句**警示**，不是「精确匹配」这个词：
    #   后者在 `_market_filter_hint()` 渲染出的 `category_path（自由文本，精确匹配）`
    #   里也有一份 ⇒ 判据会被**另一处**顶住而恒绿。
    #   （反向注入实测：把警示句删掉、判据仍绿 —— 这一条就是这么改出来的。）
    assert "不支持模糊匹配" in d, (
        "没写清 category_path **不支持模糊匹配** —— 模型会拿「厨房用品」这种关键字来筛，"
        "然后拿到空列表并据此说「没有这类目」"
    )

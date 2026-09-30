# -*- coding: utf-8 -*-
"""候选存量清点意图 + 意图关键词**裸词处置表**门禁（第 223 轮）。
（第 325 轮追加「选品大盘读口」前置判定 —— 与清点同款形态、同款病根。）

## 动因（老板原话）

    截图：老板问「**现在有多少选品了**」
    回复：「未识别出具体类目，已按全类目高潜方向扫描，发现 **8 个蓝海方向**」
          + 8 条候选商品 + 「要入库直接说『把第 1 个加进选品库』」
    追问：「是不是意图识别没做好，还是规划没做好？回答的是错误的」

## 根因（三层，均有实测证据）

  ① **关键词表过宽**：`blue_ocean` 收了**裸「选品」**，而 `save_candidate` 组
     一个裸「选品」都没有（全是「选品库 / 加入选品 / 加进选品」等短语）
     ⇒ 「有多少选品」在第一组零命中、被第二组吞掉。
  ② **短路发生在规划之前**：`_stream_chat_impl` 命中结构化意图即
     `_process_query(...)` + `return` ⇒ **LLM 与 14 个工具全程未参与**。
  ③ **能力其实具备**：`list_candidates` 早在真装配的 14 个工具里（第 216 轮
     起还返回**真实** `total`），`_build_router()` 也是真接线
     ⇒ **不是规划没做好，是规划没被调用**。

## 修法（与老板拍板的档位一致）

  - 「清点」做成**前置信号**（与既有「≥2 个 ASIN ⇒ competitor」同款形态），
    **与门**：候选域对象词 AND 清点诉求词；命中后**不短路**，交工具路由由 LLM
    调 `list_candidates` 作答。
  - 两个入口（`invoke` / `_stream_chat_impl`）**共用一份短路名单**
    `INTENT_SHORTCUTS` —— 改前两条路径各写一份判据，新加标签必然漂移。
  - 裸词体检：63 个关键词逐个过一遍，给每组裸词一个「留 / 收窄 / 删」结论。

## 反向注入

每条判据都实测过「注进去会转红」，记录在文件末尾。**没有反例的断言 = 没有断言**。
"""

import ast
import inspect
import pathlib
import textwrap

import pytest

from modules.product_research import agent_product_research as M
from modules.product_research.agent_product_research import (
    INTENT_SHORTCUTS,
    MARKET_INSIGHT_INTENT,
    PROGRESS_ONLY_INTENTS,
    QUERY_CANDIDATES_INTENT,
    ProductResearchAgent,
)

_AGENT_FILE = (pathlib.Path(__file__).resolve().parents[1]
               / "modules" / "product_research" / "agent_product_research.py")
# ★ 第 338 轮（P0-6 第四刀）：意图判定的**判定体**外移到本文件，
#   主文件只剩薄壳 ⇒ 「顺序」这类判据必须读这里。
_ROUTING_FILE = (pathlib.Path(__file__).resolve().parents[1]
                 / "modules" / "product_research" / "agent_routing.py")

#: 路由表的运行时真值（`{组名: (词, ...)}`）
_ROUTES = {r.label: tuple(r.keywords) for r in ProductResearchAgent._INTENT_ROUTES}


def _agent() -> ProductResearchAgent:
    """只调纯逻辑方法，不构造完整 Agent（不需要 DB / LLM / 事件循环设备）。

    ★ 与 `test_product_research_intent_routing.py::test_adverb_bijiao_is_not_competitor`
      同款做法：`_classify_intent` 是纯字符串逻辑，`__new__` 即可。
    """
    return ProductResearchAgent.__new__(ProductResearchAgent)


# =====================================================================
# ① 裸词处置表（名单式门禁）
# =====================================================================
#
# ★ 为什么必须有一张**登记表**：裸词（<=2 字）是这类缺陷的唯一来源 ——
#   语义最宽、最易误伤，而且**加了不会被任何用例发现**（除非恰好有人写成反例）。
#   名单式门禁的规矩：新增同类对象必须同步登记，否则静默落在扫描面外。
#   ⇒ 两个方向都断：代码里多一个词而表里没有 ⇒ 红；表里有而代码没有 ⇒ 红。
#
# ★ 处置三档的含义：
#   留   —— 该词在本产品语境里**只**指向本组语义（或已被既有门禁钉死）。
#   收窄 —— 该词本身是普通词，但本产品里确实要靠它命中，暂时保留并登记为
#           「已知误伤（受控）」；再出现同类误判时应改成短语。
#   删   —— 该词**不该**由本组命中：它指向别的对象/别的问题，落工具路由
#           （LLM 会判对）比短路答错好。
BARE_WORD_VERDICTS = {
    # ---- save_candidate ----
    "入库": ("save_candidate", "留",
           "本产品语境里唯一义 = 写入选品库；且既有门禁钉死（「这个帮我入库」"
           "「把 B0CGLKP2R1 入库」）"),
    # ---- blue_ocean ----
    "蓝海": ("blue_ocean", "留", "专有词，无歧义"),
    "挖掘": ("blue_ocean", "留", "专有动词，只出现在挖掘诉求里"),
    "品类": ("blue_ocean", "留",
           "本组核心**对象词**（蓝海挖掘就是按品类挖）；既有门禁依赖它"
           "（「帮我选个男装品类的机会」）"),
    "趋势": ("blue_ocean", "留", "市场趋势与蓝海分析绑定"),
    "好卖": ("blue_ocean", "收窄",
           "口语高频，但只出现在「卖」的语境里；已知误伤：与「评论」同现时"
           "（「有什么好卖的评论」）会误判 —— 受控"),
    "好销": ("blue_ocean", "留", "同「好卖」，用词更书书面、歧义更低"),
    "热销": ("blue_ocean", "留", "与「畅销」同族，电商语境专用"),
    "热门": ("blue_ocean", "收窄",
           "「热门」也修饰非商品对象（热门评论/热门问题）；已知误伤受控"),
    "爆款": ("blue_ocean", "留", "电商专有词，只修饰商品/品类"),
    "很火": ("blue_ocean", "留", "副词+火，句式固定"),
    "火爆": ("blue_ocean", "留", "同「很火」，句式固定（什么品类火爆）"),
    "潜力": ("blue_ocean", "留", "「有没有潜力」是选品判断的标准问法"),
    "好做": ("blue_ocean", "留", "「这个品好做吗」= 可进入性判断，属本组"),
    "冷门": ("blue_ocean", "留", "蓝海的口语同义（低竞争）"),
    # ---- profit ----
    "利润": ("profit", "留", "本组对象词，无歧义"),
    "费用": ("profit", "留", "成本侧对象词"),
    "成本": ("profit", "留", "本组对象词（成本核算的标准问法）"),
    "售价": ("profit", "留", "本组对象词（也是排行榜维度之一）"),
    "定价": ("profit", "留", "本组对象词（定价合理性与利润同组）"),
    "赚钱": ("profit", "留", "「这个品赚不赚钱」= 本组"),
    # ---- pain_points ----
    "痛点": ("pain_points", "留", "本组专有对象词"),
    "差评": ("pain_points", "留", "本组专有对象词"),
    "评论": ("pain_points", "收窄",
           "「看看评论」本意就是评论分析（= 本组载体），保留；"
           "已知误伤：「这个评论说的什么」会被短路成痛点分析 —— 受控"),
    "抱怨": ("pain_points", "留", "投诉类语义，指向本组"),
    # ---- competitor ----
    "对比": ("competitor", "留",
           "「对比」在电商语境里就是拿两个商品/Listing 比；"
           "本组另有「比较一下/比较下」等短语，且注释明令禁止收裸「比较」（副词）"),
    "竞品": ("competitor", "留", "本组专有对象词"),
    "vs": ("competitor", "留", "英文对比标记，无歧义"),
}

#: 本轮**删掉**的裸词（`(组, 词)`）。防止它们悄悄回流。
#:
#: ★ 每一条都对应一次真实的答非所问，理由见 `_INTENT_ROUTES` 上方的注释。
BARE_WORD_REMOVED = {
    ("blue_ocean", "选品"): (
        "领域义是**候选选品这个存量对象**（「有多少选品」「列一下我的选品」），"
        "却排在 blue_ocean 里 ⇒ 清点问句被吞、直接开挖（本轮 bug 的病根）"
    ),
    ("blue_ocean", "机会"): (
        "泛名词（「我这个品还有机会吗」）；删掉后真蓝海问句落**工具路由**"
        "仍答对，而留着则同类误判没有任何补救路径"
    ),
    ("pain_points", "问题"): (
        "全表最宽的万能名词（实测「我的店铺有什么问题」→ 痛点分析 ⇒ 反问要 ASIN）；"
        "本组「痛点/差评/不满意/抱怨」四个区分性词已足够"
    ),
}

_ALLOWED_VERDICTS = {"留", "收窄", "删"}


def _bare_words_in_code() -> set:
    return {(grp, kw) for grp, kws in _ROUTES.items() for kw in kws if len(kw) <= 2}


def test_every_bare_word_in_code_is_registered():
    """代码里的每个裸词都必须在处置表里 —— 否则红。

    ★ 这是「新增裸词」的唯一捕获点：加一个「好」或「品」进关键词表，
      没有任何行为用例会发现（要写出恰好被它误伤的反例才行）。
    """
    registered = {(grp, kw) for kw, (grp, _v, _r) in BARE_WORD_VERDICTS.items()}
    unregistered = sorted(_bare_words_in_code() - registered)
    assert not unregistered, (
        "这些裸词（<=2 字）没在处置表里登记：%s\n"
        "⇒ 请逐个判定「留 / 收窄 / 删」并加进 BARE_WORD_VERDICTS（带理由）。"
        % unregistered
    )


def test_every_registered_bare_word_exists_in_code():
    """反向：处置表里的每条都必须在代码里真实存在 —— 防「表里登记了、代码没有」。"""
    registered = {(grp, kw) for kw, (grp, _v, _r) in BARE_WORD_VERDICTS.items()}
    stale = sorted(registered - _bare_words_in_code())
    assert not stale, (
        "处置表里这些词在运行时关键词表里找不到：%s ⇒ 表已过期（词被删/改名了）"
        % stale
    )


def test_removed_bare_words_stay_removed():
    """本轮删掉的三个裸词不得回流 —— 这是老板遇到的那个 bug 的直接防线。"""
    back = []
    for (grp, kw) in BARE_WORD_REMOVED:
        if kw in _ROUTES.get(grp, ()):
            back.append("%s 的裸「%s」" % (grp, kw))
    assert not back, "这些已判定为「删」的裸词又回到了关键词表：%s" % back


def test_verdicts_are_well_formed():
    """处置表自身的完整性：档位合法、理由非空、组名真实存在。"""
    for kw, (grp, verdict, reason) in BARE_WORD_VERDICTS.items():
        assert grp in _ROUTES, f"{kw!r} 登记的组 {grp!r} 不存在"
        assert verdict in _ALLOWED_VERDICTS, f"{kw!r} 的处置 {verdict!r} 非法"
        assert len(reason or "") >= 6, f"{kw!r} 没写理由（处置表的价值就在理由里）"
        assert len(kw) <= 2, f"{kw!r} 不是裸词，不该进这张表"
    for key, reason in BARE_WORD_REMOVED.items():
        assert len(reason or "") >= 6, f"{key} 没写删除理由"


def test_no_keyword_can_never_match():
    """★ 死关键词门禁：任何关键词都不得含大写字母。

    查询串在 `first_match` 里被 `lower()` ⇒ 含大写的关键词**永不命中**。
    改前 `profit` 组的 `"FBA"` / `"ROI"` 就是这种形态 —— 写了词、从不生效
    （典型的**声明承诺型假门禁**）；实测「fba 费用怎么算」判成 general。
    第 223 轮修为小写，并在此立判据防回流。
    """
    dead = [f"{grp}:{kw}" for grp, kws in _ROUTES.items() for kw in kws
            if any(c.isupper() for c in kw)]
    assert not dead, (
        "这些关键词含大写字母，在小写归一后的查询里**永不命中**：%s\n"
        "⇒ 要么改成小写，要么删掉（写了不生效 = 假门禁）" % dead
    )


# =====================================================================
# ② 清点意图：行为判据（真值实测）
# =====================================================================

#: 应当被判成 `query_candidates` 的问句（老板那句 + 同义问法）
INVENTORY_QUERIES = [
    "现在有多少选品了",          # ★ 老板原话
    "有多少个选品",
    "我选品库里有多少条",
    "选品库现在有几条",
    "候选池里有多少个",
    "候选库现在有哪些",
    "列一下我的选品",
    "看看候选库",
    "选品库列表",
    "我的选品都有啥",
]

#: 这些问句含清点词但**不是**清点（域对象词不成立）⇒ 不得被吞
NOT_INVENTORY_QUERIES = [
    "现在有哪些比较火的产品",      # 既有门禁：应 blue_ocean
    "比较火的品类有哪些",          # 既有门禁：应 blue_ocean
    "有什么冷门品类",             # 既有门禁：应 blue_ocean
    "这个品利润多少",             # 含「多少」但不是清点候选
    "这个产品的痛点有哪些",        # 含「有哪些」但对象是痛点
    "把这个加到选品",             # 含域对象词但没有清点诉求 ⇒ 入库
    "把第 1 个加进选品库",         # 同上
    "这个品帮我进入选品库",        # 同上
]


@pytest.mark.parametrize("query", INVENTORY_QUERIES)
async def test_inventory_queries_are_routed_to_query_candidates(query):
    assert await _agent()._classify_intent(query) == QUERY_CANDIDATES_INTENT, (
        f"{query!r} 没被判成清点意图 —— 关键词表又把它吞掉了？"
    )


@pytest.mark.parametrize("query", NOT_INVENTORY_QUERIES)
async def test_inventory_gate_does_not_swallow_other_intents(query):
    """★ 与门的**另一个方向**：只有清点词、或只有域对象词时都不得命中。

    ★ 没有这一条，把 `_is_candidate_query` 写成 `return True` 也能全绿。
    """
    assert await _agent()._classify_intent(query) != QUERY_CANDIDATES_INTENT, (
        f"{query!r} 被清点判定吞掉了 —— 与门退化成单关键词了？"
    )


def test_gate_is_a_conjunction_of_two_doors():
    """`_is_candidate_query` 必须是**与门**：两个方向各给一个反例。"""
    obj = _agent()
    assert obj._is_candidate_query("现在有多少选品了") is True
    # 只有域对象词（没有清点诉求）⇒ False
    assert obj._is_candidate_query("帮我做个选品分析") is False
    # 只有清点诉求（没有域对象词）⇒ False
    assert obj._is_candidate_query("现在有哪些比较火的产品") is False
    assert obj._is_candidate_query("") is False


# =====================================================================
# ②b 选品大盘读口的前置判定（第 325 轮）
# =====================================================================
#
# ★ 老板的原始投诉（第 324 轮截图）：「现在哪个品类蓝海分最高」→ Agent 答
#   「未识别出具体类目，已按全类目高潜方向扫描，发现 8 个蓝海方向」+ 8 条候选
#   商品 + 「要入库直接说『把第 1 个加进选品库』」。**它去挖蓝海了，压根没读大盘。**
#
# ★ 根因与「清点」（第 223 轮）**同款三层**：
#   ① 关键词表过宽：`blue_ocean` 收了裸「品类」⇒ 「品类」命中即短路；
#   ② 短路发生在规划之前：`_process_query` 直接开挖，LLM 与工具全程未参与；
#   ③ 能力其实具备：`market_snapshots` 里就存着类目级蓝海评分（seed 的
#      `msnap-003` Smart Lighting 71 分），只是 Agent 侧**一个工具都没有**
#      （第 325 轮补上 `query_market_insight`）。
#
# ★ 修法（同款）：加一条**前置判定**（与「≥2 个 ASIN ⇒ competitor」「候选清点」
#   同形），命中后**不短路** —— 只把标签交出去，由工具路由的 LLM 调
#   `query_market_insight` 作答。
#
# ★ 与门：**大盘量纲词** AND **排行/清点诉求词**。
#   为什么必须两条同时成立：只按量纲词判，会把「帮我看看这些类目的搜索增长」
#   这类没有诉求的问句也吞掉；只按诉求词判，等于把「有多少」全吞掉。
#   ★ 这两组词**不进** `BARE_WORD_VERDICTS`：它们不是「关键词路由」，而是
#     **与门的一半**，单独一个词永远不会命中（与 `_CANDIDATE_QUERY_*` 同款）。
#
# ★ 代价不对称（这是本判定敢写窄的理由）：它**不是**「识别大盘问句」，
#   只干「不让关键词短路吞掉大盘问句」这一件事。没被它拦下的问句落 `general`
#   ⇒ **仍然**进工具路由 ⇒ LLM 照样能调 `query_market_insight`。
#   ⇒ 漏判 = 与现状相同；误判 = 也只是换个标签（它不在 `INTENT_SHORTCUTS` 里）。

#: 应当被判成 `market_insight` 的问句（老板那句 + 同义问法）
MARKET_INSIGHT_QUERIES = [
    "现在哪个品类蓝海分最高",          # ★ 老板原话（第 324 轮截图）
    "蓝海评分最高的类目是哪个",
    "大盘上搜索量最大的品类有哪些",
    "哪个类目卖家数最少",
    "有哪些价格带高的品类",
    "搜索增长最快的类目是什么",
    "有没有竞争度低的类目",
    "价格趋势是 rising 的类目有哪些",
    "哪些类目的新卖家数最多",
    "哪个类目价格中位数最高",
]

#: 这些问句**不得**被判成 `market_insight` —— 每条都钉着一个既有行为
NOT_MARKET_INSIGHT_QUERIES = [
    "找厨房用品的蓝海机会",   # 既有门禁：挖候选商品（blue_ocean），不是读大盘
    "有什么冷门品类",       # 既有门禁：blue_ocean
    "把这个加进选品库",     # 既有门禁：save_candidate（写库 ⇒ 走 HITL 审批）
    "现在有多少选品了",     # 既有门禁：query_candidates（候选清点）
]


@pytest.mark.parametrize("query", MARKET_INSIGHT_QUERIES)
async def test_market_insight_queries_are_not_stolen_by_keyword_router(query):
    """★ 本轮 bug 的直接防线：这些问句不得再被 `blue_ocean` 吞掉。

    改前实测「现在哪个品类蓝海分最高」判的就是 `blue_ocean`
    （因为「品类」在那一组里）⇒ 关键词层直接 `return` + 开挖。
    """
    assert await _agent()._classify_intent(query) == MARKET_INSIGHT_INTENT, (
        f"{query!r} 没被判成大盘读口 —— 关键词表（「品类」「趋势」「售价」…）"
        f"又把它抢走了？"
    )


@pytest.mark.parametrize("query", NOT_MARKET_INSIGHT_QUERIES)
async def test_market_insight_gate_does_not_swallow_existing_intents(query):
    """★ 与门的**另一个方向**：别把既有行为修坏。

    ★ 没有这一条，把 `_is_market_insight_query` 写成 `return True` 也能全绿。
    """
    assert await _agent()._classify_intent(query) != MARKET_INSIGHT_INTENT, (
        f"{query!r} 被大盘判定吞掉了 —— 与门退化成单量纲词了？"
    )


def test_market_insight_gate_is_a_conjunction_of_two_doors():
    """`_is_market_insight_query` 必须是**与门**：两个方向各给反例。"""
    obj = _agent()
    assert obj._is_market_insight_query("现在哪个品类蓝海分最高") is True
    # 只有量纲词（没有排行 / 清点诉求）⇒ False
    assert obj._is_market_insight_query("帮我看看这些类目的搜索增长") is False
    assert obj._is_market_insight_query("这个类目的价格带怎么样") is False
    # 只有诉求词（没有量纲词）⇒ False
    assert obj._is_market_insight_query("现在有多少选品了") is False
    assert obj._is_market_insight_query("哪些产品比较火") is False
    assert obj._is_market_insight_query("") is False


def test_market_insight_signal_runs_before_the_keyword_router():
    """大盘判定必须排在 `first_match` **之前**（顺序即优先级）。

    ★ 排到后面 = 「现在哪个品类蓝海分最高」里含「品类」⇒ 先被 `blue_ocean`
      吞掉（改前实测结果就是它），此时前置信号退化成「关键词表没命中时的补丁」。
    ★ 只看**顶层语句序**（`fn.body`）：行号会被「求值顺序」这类无害重排误伤，
      而真正要防的是「判定被排在关键词裁决**之后**」。
    """
    # ★ 第 338 轮（P0-6 第四刀）：判定体外移到 `agent_routing.py`。
    #   读集跟着**不变量**走 —— 不变量是「顺序」，不是「住哪个文件」。
    fn = _fn_node("classify_intent", _ROUTING_FILE.read_text(encoding="utf-8"))
    gate_idx = None
    router_idx = None
    for idx, stmt in enumerate(fn.body):
        names = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(stmt) if isinstance(n, ast.Attribute)}
        # ★ 第 338 轮（P0-6 第四刀）：判定体外移后，新模块里的函数名去掉了
        #   下划线前缀（`is_market_insight_query`）⇒ 两种写法都要认（两端同查）。
        hit = any(n in attrs or n in names for n in
                  ("_is_market_insight_query", "is_market_insight_query"))
        if hit and gate_idx is None:
            gate_idx = idx
        if "first_match" in names and router_idx is None:
            router_idx = idx
    assert gate_idx is not None, "`_classify_intent` 没调用 `_is_market_insight_query`"
    assert router_idx is not None, "`_classify_intent` 没调用 `first_match`"
    assert gate_idx < router_idx, (
        "大盘判定排在了关键词裁决之后（语句序 %s vs %s）⇒ 它退化成「关键词表没命中"
        "时的补丁」，而「现在哪个品类蓝海分最高」含「品类」、根本轮不到它"
        % (gate_idx, router_idx)
    )


def test_market_insight_intent_is_progress_only_not_a_shortcut():
    """大盘读口必须**不短路**，且两个入口共用同一份「只给进度文案」名单。

    ★ 进了 `INTENT_SHORTCUTS` ⇒ 又变成「关键词层把答法也钉死」（本轮 bug 病根）。
    ★ 写成 `_INTENT_ROUTES` 的一组 ⇒ 排在 `save_candidate` / `blue_ocean` 之后，
      永远轮不到（「品类」在 `blue_ocean` 组里）。
    ★ `PROGRESS_ONLY_INTENTS` 取代了 `_stream_chat_impl` 里那行散装判断
      （`if intent == QUERY_CANDIDATES_INTENT:`）—— 同一条规则只允许一份表达。
    """
    assert MARKET_INSIGHT_INTENT not in INTENT_SHORTCUTS
    assert MARKET_INSIGHT_INTENT not in _ROUTES
    assert MARKET_INSIGHT_INTENT in PROGRESS_ONLY_INTENTS
    assert QUERY_CANDIDATES_INTENT in PROGRESS_ONLY_INTENTS
    for label in PROGRESS_ONLY_INTENTS:
        assert label not in INTENT_SHORTCUTS, f"{label} 又回到短路名单里了"
        assert isinstance(M._INTENT_PROGRESS.get(label), str), (
            f"{label} 没有进度文案 —— 流式下老板看到的是空白/转圈"
        )
        assert M._INTENT_PROGRESS[label].strip(), f"{label} 的进度文案是空的"

# =====================================================================
# ③ 「不新增第二份读库实现」（形态判据）
# =====================================================================

def _fn_node(name, src=None):
    tree = ast.parse(src if src is not None else _AGENT_FILE.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"找不到函数 {name}")


def _called_names(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.add(n.func.attr)
    return out


_DB_WORDS = ("candidate", "count", "list", "service", "session", "select", "query")


def test_classifier_does_not_read_the_database_itself():
    """清点判定只做**路由**，不许自己查库（否则就是第二份读库实现）。

    ★ 走 AST 不用源码字符串：docstring 里写一句「此处不查库」就能骗过字符串判据。
    """
    # ★ 第 338 轮（P0-6 第四刀）：判定体外移到 `agent_routing.py`。
    #   在**薄壳**上跑本判据会把委托本身当成取数调用（`is_candidate_query`
    #   里含 `candidate`）⇒ 读集必须跟着判定体走。
    #   ★ 薄壳端由 `test_product_research_routing_layer.py` 单独钉
    #     「只许委托、不许出现领域原语」。
    called = {c.lower() for c in
              _called_names(_fn_node("is_candidate_query",
                                     _ROUTING_FILE.read_text(encoding="utf-8")))}
    bad = sorted(c for c in called if any(w in c for w in _DB_WORDS))
    assert not bad, (
        f"`_is_candidate_query` 里出现了疑似取数调用 {bad} —— "
        f"清点必须交工具路由由 `list_candidates`（跨 Agent 共用唯一实现）作答"
    )


def test_tool_layer_does_not_query_the_candidate_table_itself():
    """工具层不得自己写查询 —— 只许调 `modules.candidates` 的 service。

    ★ 「同一判定两份实现 ⇒ 至少一份永远测不到」。本轮给「清点」加的是**路由**，
      不是实现：数据仍只经 `modules/candidates/service.py`（它的 `list_candidates`
      与 `count_candidates` 共用同一个内核 base query）。
    ★ 按「谁真的构造 ORM 查询」定判据，而不是按「有几个同名 def」——
      `modules/candidates/router.py` 里那个同名 `list_candidates` 是 FastAPI
      端点（转 HTTP 信封），不算第二份实现；按名字数会长出一堆假阳性。
    ★ 用 **AST 标识符**而不是源码字符串包含：后者会被注释/docstring 里写一句
      「这里不用 CandidateRecord」骗红，也会被 `select(` 的写法差异漏掉。
    """
    tool_file = (pathlib.Path(__file__).resolve().parents[1]
                 / "modules" / "library" / "tools.py")
    tree = ast.parse(tool_file.read_text(encoding="utf-8"))
    idents = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            idents.add(n.id)
        elif isinstance(n, ast.Attribute):
            idents.add(n.attr)
        elif isinstance(n, ast.alias):
            idents.add((n.name or "").split(".")[-1])
    bad = sorted(idents & {"CandidateRecord", "select", "sqlalchemy"})
    assert not bad, (
        f"工具层 `modules/library/tools.py` 里出现了 {bad} —— "
        f"它应该只调 service，不许自己查库"
    )


# =====================================================================
# ④ 两个入口都不把清点送进 `_process_query`（形态判据）
# =====================================================================

def test_shortcut_list_is_the_single_source_and_excludes_read_and_write():
    """短路名单**唯一**，且清点（只读）与入库（有副作用）都不在其中。

    ★ 入库不在其中：有副作用的意图必须经带 HITL 审批的工具路径
      （`_APPROVAL_GATED_INTENTS`），由关键词表直写 = 零审批直写。
    ★ 清点不在其中：它是**读库问题**，必须交工具路由 —— 进了短路名单就等于
      「关键词层把答法也钉死」，那正是本轮 bug 的病根。
    """
    assert QUERY_CANDIDATES_INTENT not in INTENT_SHORTCUTS, (
        "清点又回到短路名单里了 —— 会重新走进 `_process_query` 直接开挖"
    )
    assert "save_candidate" not in INTENT_SHORTCUTS, (
        "有副作用的入库不得短路（HITL 审批闸门会被绕过）"
    )
    assert QUERY_CANDIDATES_INTENT not in _ROUTES, (
        "清点被写成了 `_INTENT_ROUTES` 的一组 —— 那会排在 save_candidate 之后而"
        "永远轮不到（「选品库里现在有多少条」含「选品库」），必须是前置信号"
    )


_ADDRIFT_SRC = """\
async def f(self, intent):
    if intent != "general":
        return await self._process_query(intent)
"""


def _uses_name(fn_node, name):
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(fn_node))


def test_both_entries_share_one_shortcut_rule():
    """两个**实现体**（`_invoke_impl` / `_stream_chat_impl`）必须**共用**
    `INTENT_SHORTCUTS`。

    ★ 改前两条路径各写一份判据（`_invoke_impl` 是 `intent != "general"`、
      `_stream_chat_impl` 是一份显式元组）；同一规则两种表达 ⇒ 加一个新标签
      必然漂移，漂移后果是「同一句话走流式开挖、走非流式清点」。
    ★ 靶子必须是**实现体**而不是公开入口：`invoke()` / `stream_chat()` 只是
      「绑上下文 → hydrate → 委托 → flush」的薄壳（第 145 轮批 C1 的拆分），
      决策路径一行都不在里面 —— 把判据打在薄壳上等于打在空气里。
    """
    src = _AGENT_FILE.read_text(encoding="utf-8")
    for entry in ("_invoke_impl", "_stream_chat_impl"):
        fn = _fn_node(entry, src)
        assert _uses_name(fn, "INTENT_SHORTCUTS"), (
            f"{entry} 没有引用 `INTENT_SHORTCUTS` —— 又自己写了一份短路判据？"
        )


def test_public_wrappers_hold_no_intent_decision():
    """公开入口（`invoke` / `stream_chat`）里不得有意图判定。

    ★ 上面那条判据的**前提**：决策只在实现体里。若哪天有人把 `_classify_intent`
      搬回薄壳，上面那条会**继续绿**（因为实现体里的那份还在），
      而实际的决策点已经多了一处 —— 这正是「同一判定两份实现」的入口。
    """
    src = _AGENT_FILE.read_text(encoding="utf-8")
    for entry in ("invoke", "stream_chat"):
        fn = _fn_node(entry, src)
        called = _called_names(fn)
        assert "_classify_intent" not in called, (
            f"公开入口 {entry} 里出现了 `_classify_intent` —— 决策不该住在薄壳里"
        )
        assert not _uses_name(fn, "INTENT_SHORTCUTS"), (
            f"公开入口 {entry} 里出现了短路判定 —— 决策只在实现体里"
        )


def test_invoke_no_longer_uses_the_divergent_expression():
    """`_invoke_impl` 里不得再出现 `intent != "general"` 这种与流式不同的表达。"""
    fn = _fn_node("_invoke_impl")
    bad = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Compare):
            continue
        if not isinstance(n.left, ast.Name) or n.left.id != "intent":
            continue
        if any(isinstance(op, ast.NotEq) for op in n.ops):
            bad.append("intent != ...")
    assert not bad, (
        "`_invoke_impl` 又用起了与 `_stream_chat_impl` 不一致的判据：%s "
        "⇒ 两个入口必须共用 `INTENT_SHORTCUTS`" % bad
    )


def test_process_query_has_no_inventory_branch():
    """`_process_query` 的 if/elif 表里**不得**出现清点分支。

    ★ 加了就等于把「怎么答」也钉死在关键词层（「有多少条 / 按评审状态筛 /
      排行榜」三种问法只能答一种）。
    """
    fn = _fn_node("_process_query")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)}
    assert "QUERY_CANDIDATES_INTENT" not in names, (
        "`_process_query` 里出现了清点分支 —— 清点必须交工具路由，不进关键词短路"
    )
    assert QUERY_CANDIDATES_INTENT not in consts, (
        "`_process_query` 里硬编码了 query_candidates —— 同上"
    )


def test_inventory_signal_runs_before_the_keyword_router():
    """清点判定必须排在 `first_match` **之前**（顺序即优先级）。

    ★ 排到后面 = 「选品库里现在有多少条」里含「选品库」⇒ 先被 save_candidate
      吞掉。改前实测这条问句判的正是 save_candidate。
    """
    # ★ 第 338 轮（P0-6 第四刀）：判定体外移，同 `test_market_insight_*` 的理由。
    fn = _fn_node("classify_intent", _ROUTING_FILE.read_text(encoding="utf-8"))
    gate_idx = None
    router_idx = None
    # ★ 只看**顶层语句序**（`fn.body` 的次序），不按 `ast.walk` 的源码行号：
    #   行号会被「求值顺序」这种无害重排（先算 first_match 存变量、再判清点）
    #   误伤，而真正要防的是「清点判定被排在关键词裁决**之后**」
    #   —— 那时它不再是前置信号，而只是一个补在 general 分支上的补丁。
    for idx, stmt in enumerate(fn.body):
        names = {n.id for n in ast.walk(stmt) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(stmt) if isinstance(n, ast.Attribute)}
        # ★ 同上：新模块里的名字是 `is_candidate_query`。
        hit_gate = any(n in attrs or n in names for n in
                       ("_is_candidate_query", "is_candidate_query"))
        if hit_gate and gate_idx is None:
            gate_idx = idx
        if "first_match" in names and router_idx is None:
            router_idx = idx
    assert gate_idx is not None, "`_classify_intent` 没调用 `_is_candidate_query`"
    assert router_idx is not None, "`_classify_intent` 没调用 `first_match`（唯一真源）"
    assert gate_idx < router_idx, (
        "清点判定排在了关键词裁决之后（语句序 %s vs %s）⇒ 它会退化成「关键词表没命中"
        "时的补丁」，而「选品库里现在有多少条」含「选品库」、根本轮不到它"
        % (gate_idx, router_idx)
    )


def test_progress_text_exists_for_inventory():
    """流式入口要给清点一句进度文案，否则老板看到的是空白/转圈。"""
    assert isinstance(M._INTENT_PROGRESS.get(QUERY_CANDIDATES_INTENT), str)
    assert M._INTENT_PROGRESS[QUERY_CANDIDATES_INTENT].strip(), "进度文案是空的"


# =====================================================================
# ⑤ 门禁非空跑自检（把判据本身当被测对象）
# =====================================================================

def test_bare_word_registry_scanner_is_not_vacuous():
    """反向注入：**人为**加一个裸词进表，扫描器必须报出来。

    ★ 没有这一条，`_bare_words_in_code()` 写错（比如返回空集）时上面两条
      注册判据会恒绿。这里直接喂一份「含未登记裸词」的形态。
    """
    fake_routes = {"blue_ocean": ("蓝海", "好")}     # 「好」是未登记裸词
    bare = {(g, k) for g, ks in fake_routes.items() for k in ks if len(k) <= 2}
    registered = {(grp, kw) for kw, (grp, _v, _r) in BARE_WORD_VERDICTS.items()}
    assert bare - registered, "扫描器把未登记的裸词漏掉了"


def test_divergence_scanner_is_not_vacuous():
    """反向注入：`intent != "general"` 这种形态必须被扫出来。"""
    fn = ast.parse(textwrap.dedent(_ADDRIFT_SRC)).body[0]
    hits = [n for n in ast.walk(fn)
            if isinstance(n, ast.Compare)
            and isinstance(n.left, ast.Name) and n.left.id == "intent"
            and any(isinstance(op, ast.NotEq) for op in n.ops)]
    assert hits, "扫描器认不出 `intent != \"general\"` 这种漂移形态"


def test_case_insensitive_keyword_scanner_is_not_vacuous():
    """反向注入：大写关键词必须被扫出来。"""
    fake = {"profit": ("利润", "FBA")}
    dead = [f"{g}:{k}" for g, ks in fake.items() for k in ks if any(c.isupper() for c in k)]
    assert dead == ["profit:FBA"], "扫描器认不出大写关键词"


# ============================================================================
# 反向注入记录（第 223 轮**实测**：17 条注入，17 条都转红）
# ============================================================================
#
# 执行方式：把缺陷注入生产文件 → 跑本文件 → 读 `--junitxml` 明细判红 → 逐字还原
# → 核对 sha256（`223w_revinject.py`；还原一律用内存里的 pristine 字节，
# 绝不 `git checkout`/`git show` —— 本仓工作区有大量未提交改动）。
#
#   RI-1  往 competitor 塞未登记裸词「哪个」        → test_every_bare_word_in_code_is_registered
#   RI-2  删掉「冷门」（表里仍登记）                → test_every_registered_bare_word_exists_in_code
#   RI-3  裸「选品」加回 blue_ocean                 → test_removed_bare_words_stay_removed
#                                                    + test_every_bare_word_in_code_is_registered
#   RI-4  小写 fba/roi 改回大写                     → test_no_keyword_can_never_match
#   RI-5  `_is_candidate_query` 直接 return False   → 清点行为 10 条 + 与门 1 条
#   RI-6  与门退化只看域对象词                      → 不得吞别的意图 + 与门
#   RI-7  与门退化只看清点词                        → 同上
#   RI-8  清点判定里自己调 `list_candidates`        → test_classifier_does_not_read_the_database_itself
#   RI-9  工具层自己 `select(...)` 直查             → test_tool_layer_does_not_query_the_candidate_table_itself
#   RI-10 清点塞回 `INTENT_SHORTCUTS`               → test_shortcut_list_is_the_single_source_...
#   RI-11 清点写成 `_INTENT_ROUTES` 的一组          → 同上（并顺带红「未登记裸词」「不得吞别的意图」）
#   RI-12 `_stream_chat_impl` 换回显式元组          → test_both_entries_share_one_shortcut_rule
#   RI-13 判定复制进公开入口 `stream_chat`          → test_public_wrappers_hold_no_intent_decision
#   RI-14 `_invoke_impl` 换回 `!= "general"`        → test_invoke_no_longer_uses_the_divergent_expression
#   RI-15 清点降级成「关键词表没命中的补丁」        → 语句序判据 + 清点行为
#   RI-16 删掉清点进度文案                          → test_progress_text_exists_for_inventory
#   RI-17 `_process_query` 加清点分支               → test_process_query_has_no_inventory_branch
#
# ★ 一条**修正过的期望**（值得记下来）：
#   RI-3 最初我还期望 `test_inventory_queries_are_routed_to_query_candidates`
#   一起转红，实测**没红** —— 不是门禁空跑，是我对控制流理解错了：裸「选品」
#   回流后那条问句仍被**前置判定**先拦下（它在 `first_match` 之前），
#   行为完全不变。⇒ 这个修法是**纵深防御**，不靠某张词表的巧合。
#   教训与判据（「不是门禁空跑，是期望值写错」）留在此处，供下一轮复用。

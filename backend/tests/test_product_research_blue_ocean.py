"""
选品 Agent 蓝海分析的兜底回归测试

背景（bug）：主 Agent 路由带参跳转到选品 Agent 后，回复
「在「general」领域发现 6 个蓝海机会」——`general` 是内部兜底标识，被直接回显；
且 `general` 的泛化关键词（smart home / organizer…）在关键词库中命中不到，
会走「未匹配 → 随机估算」分支，导致机会分数随机、结论不可信。

覆盖：
1. 未识别出类目时用「全类目高潜关键词」，不再用 general 泛词表（B：数据兜底）
2. 全类目高潜关键词必须都有平台关键词库支撑（防未来漂移又踩随机估算）
3. 面向用户的 summary 绝不回显内部标识，且类目已知时保留原话术（A：话术兜底）
4. 无类目 / 有类目 / 空结果三种情况的文案分支
5. 工具入口 category 留空时不拼出「帮我找类的蓝海机会」这种病句

后续演进（本次）：正文主列表从**关键词**改为**商品**——词没有 ASIN，既存不进
选品库（候选库以 asin 为核心标识）也没法对比；词降级成商品的「来源机会词」标注。
「词 → 商品 → 选品库」的完整链路见 test_product_research_candidate_flow.py。
"""

import json

import pytest

from modules.product_research.agent_product_research import (
    ProductResearchAgent,
    _TRENDING_KEYWORDS,
)

QUERY_NO_CATEGORY = "比较好卖的品类有哪些"


# ====== B：数据兜底 ======

def test_generate_search_keywords_falls_back_to_trending():
    """未识别出类目 → 用全类目高潜关键词，而不是 general 泛词表"""
    keywords = ProductResearchAgent._generate_search_keywords(None)
    assert keywords == list(_TRENDING_KEYWORDS)
    for generic in ("smart home", "organizer", "portable", "wireless"):
        assert generic not in keywords, f"泛化词 {generic} 不该再出现在兜底列表里"


def test_generate_search_keywords_unknown_category_also_falls_back():
    """类目未收录（如 LLM 传了个怪词）也走同一兜底，不抛 KeyError"""
    keywords = ProductResearchAgent._generate_search_keywords("no-such-category")
    assert keywords == list(_TRENDING_KEYWORDS)


def test_generate_search_keywords_keeps_known_category_behavior():
    """已知类目仍然走原模板 + 修饰词扩展（行为不变）"""
    keywords = ProductResearchAgent._generate_search_keywords("kitchen")
    assert "coffee grinder" in keywords
    assert "portable coffee grinder" in keywords, "修饰词扩展逻辑应保留"


def test_generate_search_keywords_no_duplicated_modifier():
    """修饰词扩展不产生「portable portable blender」这类重复词"""
    for category in ("kitchen", "home", "sports", "pet"):
        for kw in ProductResearchAgent._generate_search_keywords(category):
            parts = kw.split()
            assert len(parts) == len(set(parts)), f"{category} 生成重复修饰词: {kw!r}"


@pytest.mark.parametrize("keyword", _TRENDING_KEYWORDS)
def test_trending_keywords_backed_by_adapter_keyword_db(keyword):
    """
    每个全类目高潜关键词都必须在平台关键词库里有真实数据。

    这是本次 bug 的根因防线：库里命中不到的词会被随机估算（搜索量/竞争度/趋势
    全随机），机会分数随之随机，结论不可信。
    """
    from platforms.amazon.client import MOCK_KEYWORDS

    assert keyword in MOCK_KEYWORDS, (
        f"{keyword!r} 不在 MOCK_KEYWORDS 中——会走随机估算分支，请改用有数据支撑的关键词"
    )


# ====== A：话术兜底 ======

async def test_summary_never_leaks_internal_category_token():
    """无类目提问：summary 不得出现 general，且要讲人话"""
    agent = ProductResearchAgent()
    result = await agent._analyze_blue_ocean(QUERY_NO_CATEGORY)

    assert "general" not in result["summary"], result["summary"]
    assert "全类目" in result["summary"] or "未指定" in result["summary"]
    assert result["category"] == "all"
    assert result["type"] == "blue_ocean_analysis"


async def test_summary_keeps_original_phrasing_when_category_known():
    """已知类目：保留「在「xxx」领域发现 N 个蓝海机会」原话术"""
    agent = ProductResearchAgent()
    result = await agent._analyze_blue_ocean("帮我找厨房用品的蓝海机会")

    assert result["category"] == "kitchen"
    assert result["summary"].startswith("在「kitchen」领域发现")


async def test_summary_reports_directions_and_candidates():
    """
    summary 要同时讲清「几个方向」和「几个候选商品」。

    旧版只说「发现 N 个蓝海机会」——但词是中间产物，老板真正能动手的是商品，
    所以汇总数必须落到商品上，且不再出现「（已列出 Top N）」这类空承诺。
    """
    agent = ProductResearchAgent()
    result = await agent._analyze_blue_ocean(QUERY_NO_CATEGORY)

    assert len(result["opportunities"]) <= 5
    assert "已列出" not in result["summary"], result["summary"]
    if result["products"]:
        assert "候选商品" in result["summary"], result["summary"]
    else:
        assert "方向" in result["summary"], result["summary"]


async def test_summary_when_no_opportunity_passes_threshold():
    """零达标机会时给可执行的建议，而不是「发现 0 个蓝海机会」"""
    agent = ProductResearchAgent()

    async def _low_score(keyword):
        from platforms.base import KeywordData
        return KeywordData(
            keyword=keyword,
            search_volume=10,
            competition=0.99,
            suggested_bid=0.5,
            trend_direction="declining",
        )

    agent.adapter.get_keyword_data = _low_score  # type: ignore[method-assign]
    result = await agent._analyze_blue_ocean(QUERY_NO_CATEGORY)

    assert result["opportunities"] == []
    assert "暂未发现" in result["summary"]
    assert "建议" in result["summary"]


# ====== 正文必须「列出有哪些」，而不只是「有几个」 ======

async def test_reply_body_enumerates_every_product():
    """
    复现路径：老板问「现在哪些货卖的比较火」，回复只有一句汇总——说了几个、没说哪些。

    正文必须把 **商品** 逐条列出来（标题 + ASIN）：
    词只有搜索量没有 ASIN，既存不进选品库也没法对比，所以列词等于没答。
    """
    agent = ProductResearchAgent()
    resp = await agent._process_query(QUERY_NO_CATEGORY)

    products = resp.data["products"]
    assert products, "本次没跑出候选商品，用例前提不成立"
    for p in products:
        assert p["title"] in resp.content, f"正文漏了商品 {p['title']!r}"
        assert p["asin"] in resp.content, f"正文漏了 ASIN {p['asin']!r}"

    # 逐条编号 + 不再出现「已列出」这类空承诺
    assert "1. " in resp.content
    assert "已列出" not in resp.content


async def test_reply_body_carries_decision_fields():
    """每条商品至少带上售价/月销/ROI 与来源机会词的市场指标，老板才能判断"""
    agent = ProductResearchAgent()
    resp = await agent._process_query(QUERY_NO_CATEGORY)

    for field in ("售价", "月销", "预估 ROI", "来源机会词", "月搜索", "竞争度"):
        assert field in resp.content, f"正文缺少决策字段 {field!r}"


async def test_reply_body_translates_trend_to_chinese():
    """趋势不得以 rising/stable 这类英文标识示人"""
    agent = ProductResearchAgent()
    resp = await agent._process_query(QUERY_NO_CATEGORY)

    # 注意用「趋势 xxx」整块匹配：裸子串会误伤 "Adjustable Settings" 里的 stable
    for raw in ("rising", "stable", "declining", "falling"):
        assert f"趋势 {raw}" not in resp.content, f"正文泄漏英文趋势标识 {raw!r}"


async def test_reply_body_when_no_opportunity_has_no_dangling_list():
    """零达标机会时不输出空清单，直接给可执行建议"""
    agent = ProductResearchAgent()

    async def _low_score(keyword):
        from platforms.base import KeywordData
        return KeywordData(
            keyword=keyword, search_volume=10, competition=0.99,
            suggested_bid=0.5, trend_direction="declining",
        )

    agent.adapter.get_keyword_data = _low_score  # type: ignore[method-assign]
    resp = await agent._process_query(QUERY_NO_CATEGORY)

    assert "暂未发现" in resp.content
    assert "1. " not in resp.content, "没有机会就不该有编号清单"


async def test_chat_stream_reply_contains_actual_product_names(client, auth_off, fake_llm):
    """端到端：SSE 报文里必须出现具体商品（标题 + ASIN）及来源机会词"""
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": QUERY_NO_CATEGORY},
    )
    assert r.status_code == 200, r.text
    assert "预估 ROI" in r.text, r.text
    # 具体商品（ASIN 是最关键的——没有它就无法入库）
    assert "B0KLMN3456" in r.text, f"报文里没有候选商品 ASIN：{r.text[:400]}"
    # 来源机会词仍在（词没消失，只是降级为商品的来源标注）
    assert any(kw in r.text for kw in _TRENDING_KEYWORDS), (
        f"报文里没有任何来源机会词：{r.text[:400]}"
    )


# ====== 工具入口 ======

async def test_tool_search_blue_ocean_with_empty_category():
    """工具入口 category 留空 → 不拼出「帮我找类的蓝海机会」病句，且走全类目"""
    agent = ProductResearchAgent()
    opportunities = await agent._tool_search_blue_ocean("")
    assert isinstance(opportunities, list)


# ====== 端到端：复现用户看到的那句 ======

async def test_chat_stream_no_category_reply_has_no_internal_token(client, auth_off, fake_llm):
    """
    复现路径：主 Agent 路由带参跳过来，子 Agent 用老板原话直接跑。
    断言 SSE 全量报文里不出现 general，并说明是「全类目」扫描。
    """
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": QUERY_NO_CATEGORY},
    )
    assert r.status_code == 200, r.text
    assert "general" not in r.text, r.text
    assert "全类目" in r.text, r.text


# ====== 结构化载荷随流下发（meta）：中列结论卡的数据来源 ======

def _sse_frames(text: str):
    """把 SSE 报文切成 (event, raw_data) 帧列表，便于断言事件顺序与载荷。"""
    frames = []
    for raw in text.split("\n\n"):
        event, data = "", ""
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event:
            frames.append((event, data))
    return frames


async def test_chat_stream_emits_meta_before_done(client, auth_off, fake_llm):
    """
    对话流必须把结构化结论随流下发（event: meta），且在 done 之前。

    这是「对话结果 → 中列结论卡」的唯一数据来源：没有 meta，前端只能渲染纯文本，
    卡片与「最近结果」都拿不到 opportunities 这类结构化载荷。
    """
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": QUERY_NO_CATEGORY},
    )
    assert r.status_code == 200, r.text

    frames = _sse_frames(r.text)
    events = [ev for ev, _ in frames]
    assert "meta" in events, f"未下发 meta 事件：{events}"

    metas = [json.loads(d) for ev, d in frames if ev == "meta"]
    assert len(metas) == 1, "meta 应只下发一次"

    meta = metas[0]
    assert meta["display_type"] == "blue_ocean_analysis"
    assert meta["data"]["type"] == "blue_ocean_analysis"
    # 商品层（主列表，可入库）与市场层（词及其搜索量/竞争度）都要在
    assert meta["data"]["products"], "meta 必须携带结构化商品列表"
    assert meta["data"]["opportunities"], "meta 必须携带结构化机会（市场层）数据"
    for p in meta["data"]["products"]:
        assert p["asin"], "商品必须带 ASIN——没有 ASIN 就无法写入选品库"
        assert p["source_keyword"], "商品必须带来源机会词（词→商品的溯源）"

    # 顺序：正文 delta → meta → done
    assert events.index("meta") < events.index("done")


async def test_chat_stream_meta_skipped_for_followup(client, auth_off, fake_llm):
    """
    追问类结果（缺 ASIN 的痛点分析）不是结论，不该弹卡——否则每句追问都插一张空卡。
    """
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": "帮我看看用户痛点"},
    )
    assert r.status_code == 200, r.text
    assert "event: meta" not in r.text, r.text


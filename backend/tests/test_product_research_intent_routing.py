"""
选品 Agent 意图路由 / 文案 / ASIN 提取的回归测试

背景（bug）：老板问「现在有哪些比较火的产品」，选品 Agent 却回了
`{"error":"请提供至少 2 个产品 ASIN 进行对比"}` —— 三层叠加：

1. **意图误判（主因）**：`competitor_keywords` 收了裸 "比较"，而中文里 "比较"
   绝大多数是**副词**（比较好卖 / 比较火 / 比较便宜），于是「比较火的产品」
   被判成竞品对比。
2. **错误裸奔**：`_analyze_competitors` 返回 `{"error": ...}` 时没有 `summary`，
   `_process_query` 走 `json.dumps(result)`，把内部结构原样丢给用户。
3. **ASIN 正则失效**：`[Bb]\\d{9}` 要求 B 后 9 位纯数字，而真实 ASIN 是
   `B0` + 8 位字母数字（B0C1234567 第 3 位是字母），所以连「对比 B0C… B0C…」
   都判成「未提供 ASIN」。修好正则后又暴露了 3 个被掩盖的崩溃/空结果分支
   （利润 NoneType、评论 KeyError 'neutral'、竞品 0 结果）。

覆盖：
1. 副词「比较」不得判 competitor；真正的对比意图仍要判 competitor
2. 蓝海口语（热销/热门/爆款/比较火/好做…）归 blue_ocean
3. ASIN 正则：真实 ASIN 能提取，≥2 个直接判 competitor
4. `_compose_reply` 任何分支都不裸吐 JSON
5. profit / pain_points / competitor 的缺参分支给人话而不是裸 JSON 或 500
6. 修 ASIN 正则后暴露的三个分支不再崩
"""

import json

import pytest

from modules.product_research.agent_product_research import (
    ProductResearchAgent,
    _ASIN_RE,
)

# mock 商品库里真实存在的 ASIN（见 platforms/amazon/client.py 的 MOCK_PRODUCTS）
KNOWN_ASIN_A = "B0CGLKP2R1"
KNOWN_ASIN_B = "B0DXYZ1234"
UNKNOWN_ASIN = "B0C1234567"


# ====== 1. 意图误判（本次 bug 主因）======

@pytest.mark.parametrize(
    "query",
    [
        "现在有哪些比较火的产品",
        "现在有哪些比较火的品类",
        "比较火的品类有哪些",
        "比较热销的有哪些",
        "哪个品类比较好卖",
        "比较好做的产品有哪些",
    ],
)
async def test_adverb_bijiao_is_not_competitor(query):
    """「比较」作副词（比较好卖/比较火）时不得判成竞品对比"""
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "blue_ocean", (
        f"{query!r} 被误判——裸 '比较' 又被当成对比关键词了"
    )


@pytest.mark.parametrize(
    "query",
    [
        "对比 B0CGLKP2R1 和 B0DXYZ1234",
        "比较一下这两款",
        "帮我比较两个竞品",
        "这两个哪个更好",
        "A 和 B 选哪个",
    ],
)
async def test_real_comparison_intent_still_competitor(query):
    """真正的对比意图仍要判 competitor（别修过头）"""
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "competitor"


def test_competitor_keywords_do_not_contain_bare_bijiao():
    """防回归：competitor 关键词表里不能再出现裸 "比较" """
    import inspect

    src = inspect.getsource(ProductResearchAgent._classify_intent)
    assert '"比较",' not in src and "'比较'," not in src, (
        "裸 '比较' 已回到 competitor_keywords —— 会导致「比较火的产品」被误判为竞品对比"
    )


# ====== 2. ASIN 正则 ======

@pytest.mark.parametrize(
    "asin",
    ["B0CGLKP2R1", "B0DXYZ1234", "B0C1234567", "B01N4ABCD1"],
)
def test_asin_regex_matches_real_asins(asin):
    """真实 ASIN 是 B0 + 8 位字母数字；旧的 [Bb]\\d{9} 会把含字母的全部漏掉"""
    agent = ProductResearchAgent()
    assert agent._extract_asin(f"分析 {asin} 的利润") == asin


def test_asin_regex_does_not_match_plain_words():
    """不能把普通英文单词误判成 ASIN"""
    agent = ProductResearchAgent()
    assert agent._extract_asin("best sellers 2024 list") is None
    assert agent._extract_multiple_asins("bedrooms 12 kitchen") == []


def test_two_asins_route_to_competitor():
    """≥2 个 ASIN 是竞品对比的强信号"""
    agent = ProductResearchAgent()
    assert agent._extract_multiple_asins(f"对比 {KNOWN_ASIN_A} {KNOWN_ASIN_B}") == [
        KNOWN_ASIN_A,
        KNOWN_ASIN_B,
    ]


# ====== 3. 文案：绝不裸吐 JSON ======

@pytest.mark.parametrize(
    "query",
    [
        "现在有哪些比较火的产品",      # blue_ocean
        f"分析 {UNKNOWN_ASIN} 的利润",  # profit 缺售价
        f"分析 {UNKNOWN_ASIN} 的用户痛点",  # pain_points
        f"对比 {UNKNOWN_ASIN} 和 B0C9999999",  # competitor 数据为空
        "帮我写个标题",                # general 兜底
    ],
)
async def test_reply_is_never_raw_json(query):
    """任何分支的正文都必须是给人看的话，不能是 json.dumps(result)"""
    agent = ProductResearchAgent()
    content = (await agent._process_query(query)).content

    assert not content.lstrip().startswith("{"), f"裸 JSON 又出现了: {content[:80]}"
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        parsed = None
    assert parsed is None or not isinstance(parsed, dict), f"正文是 dict: {content[:80]}"


def test_compose_reply_priority_order():
    """summary > response > error > 兜底"""
    compose = ProductResearchAgent._compose_reply
    assert compose({"summary": "S", "response": "R", "error": "E"}) == "S"
    assert compose({"response": "R", "error": "E"}) == "R"
    assert "E" in compose({"error": "E"})
    assert compose({}) == "分析已完成。"


# ====== 4. 缺参/空结果分支不再崩、不再裸 JSON ======

async def test_profit_without_price_asks_instead_of_crashing():
    """查不到 ASIN 详情又没给售价 → 友好追问（原先直接 AttributeError → 500）"""
    agent = ProductResearchAgent()
    result = await agent._analyze_profit(f"分析 {UNKNOWN_ASIN} 的利润")

    assert "售价" in result["summary"]
    assert result["type"] == "profit_analysis"


async def test_profit_with_explicit_price_still_works():
    """给了售价就照常算（且文案里带关键数字）"""
    agent = ProductResearchAgent()
    result = await agent._analyze_profit(f"分析 {UNKNOWN_ASIN} 的利润，售价 29.99")

    assert "售价 $29.99" in result["summary"]
    assert "ROI" in result["summary"]


async def test_pain_points_3star_reviews_do_not_crash():
    """rating_filter=3 曾触发 MOCK_REVIEWS['neutral'] KeyError"""
    agent = ProductResearchAgent()
    result = await agent._analyze_pain_points(f"分析 {KNOWN_ASIN_A} 的用户痛点")

    assert result["type"] == "pain_point_analysis"
    assert "中差评" in result["summary"]


async def test_competitor_with_unknown_asins_says_so_humanly():
    """竞品数据为空时说明白，而不是「已完成 0 个竞品」"""
    agent = ProductResearchAgent()
    result = await agent._analyze_competitors(f"对比 {UNKNOWN_ASIN} 和 B0C9999999")

    assert result["competitors"] == []
    assert "没返回" in result["summary"]


async def test_competitor_with_known_asins_returns_results():
    """mock 库里存在的 ASIN 能正常出对比结果"""
    agent = ProductResearchAgent()
    result = await agent._analyze_competitors(f"对比 {KNOWN_ASIN_A} 和 {KNOWN_ASIN_B}")

    assert len(result["competitors"]) == 2
    assert KNOWN_ASIN_A in result["summary"]


async def test_pain_points_without_asin_guides_user():
    agent = ProductResearchAgent()
    result = await agent._analyze_pain_points("帮我看看用户痛点")

    assert result["type"] == "pain_point_analysis"
    assert "ASIN" in result["summary"]


async def test_pain_points_summary_lists_top_pains_not_just_one():
    """
    与蓝海同一类缺陷：「说了一个，不说全部」。

    痛点分析原先只报「最集中的痛点是「X」（占 N%）」，问「有哪些痛点」时
    等于没答完——正文要列出 Top 3 及占比。
    """
    agent = ProductResearchAgent()
    result = await agent._analyze_pain_points(f"分析 {KNOWN_ASIN_A} 的用户痛点")

    pains = result["top_pain_points"]
    assert len(pains) >= 2, "用例前提：该 ASIN mock 数据应有多类痛点"
    for pp in pains[:3]:
        assert pp["pain_point"] in result["summary"], f"正文漏了痛点 {pp['pain_point']!r}"


# ====== 5. 端到端：复现用户截图那句话 ======

async def test_chat_stream_unmatched_question_goes_blue_ocean(client, auth_off, fake_llm):
    """复现路径：老板问「有哪些比较火的产品」→ 必须是蓝海结论，不能是竞品报错"""
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": "现在有哪些比较火的产品"},
    )
    assert r.status_code == 200, r.text
    assert "蓝海" in r.text, r.text
    assert "ASIN" not in r.text, r.text
    assert '"error"' not in r.text, r.text


# ====== 6. 同一个 ASIN 在一次输入里重复出现（第 215 轮）======
#
# 事故：老板贴了一条 Amazon 商品链接说「这个选品帮我放入选品库」，选品 Agent 却回
# 「拿到了 ASIN（B09V9TXTKK, B09V9TXTKK, B09V9TXTKK），但平台没返回可对比的竞品数据」。
#
# 根因：Amazon 商品链接里**同一个 ASIN 出现 3 次**（`/dp/<ASIN>`、`pd_rd_i=<ASIN>`、
# `ref_=..._<ASIN>`），而 `_classify_intent` 有一条非关键词**前置信号**：
#
#     if len(self._extract_multiple_asins(query)) >= 2:
#         return "competitor"
#
# 它是按**出现次数**数的 ⇒ 把「1 个商品」读成「3 个商品要对比」；而这条判定排在
# 关键词路由**之前**，所以「选品库」这个关键词永远轮不到。这是确定性缺陷，
# 与模型能力无关（同样的输入 100% 复现）。
#
# 修法：去重收口在 `_extract_multiple_asins`（唯一真源）—— 它的 4 个消费点
# （意图判定 / 竞品对比 / 待补槽位 / 入库目标解析）同时受益。只在 `_classify_intent`
# 里 `len(set(...))` 会留下另外三处按重复计数，属于「同一判定两份实现」。

#: 老板那次贴的真实链接（同一个 ASIN 以三种形态各出现一次）
AMAZON_URL_WITH_REPEATED_ASIN = (
    "https://www.amazon.com/Junk-Food-Clothing-NFL-Francisco/dp/B09V9TXTKK"
    "?pd_rd_w=ogerC&content-id=amzn1.sym.e850b2a8-46e9-483d-bf08-f59ae1aebb11"
    "&pf_rd_p=e850b2a8-46e9-483d-bf08-f59ae1aebb11"
    "&pd_rd_i=B09V9TXTKK&ref_=slls_san-francisco-49ers_collc_deal_d_B09V9TXTKK"
    "&th=1&psc=1"
)


def test_repeated_asin_in_one_url_is_deduped():
    """一个商品链接里同一个 ASIN 出现 3 次 ⇒ 只应提取出 **1 个** ASIN"""
    agent = ProductResearchAgent()
    asins = agent._extract_multiple_asins(AMAZON_URL_WITH_REPEATED_ASIN)
    assert asins == ["B09V9TXTKK"], (
        f"重复的 ASIN 没被去重（得到 {asins}）—— 「>=2 个 ASIN 判竞品」那条前置判定"
        f"会把它读成「给了 3 个 ASIN 要对比」"
    )


async def test_amazon_url_with_repeated_asin_routes_to_save_candidate():
    """★ 本轮主判据：贴链接 + 「放入选品库」必须判 save_candidate，而不是 competitor"""
    agent = ProductResearchAgent()
    query = f"{AMAZON_URL_WITH_REPEATED_ASIN} 这个选品帮我放入选品库"
    intent = await agent._classify_intent(query)
    assert intent == "save_candidate", (
        f"判成了 {intent!r} —— 链接里重复的 ASIN 又抢先触发了 competitor 前置判定"
    )


def test_dedup_keeps_first_occurrence_order():
    """去重不能改顺序（顺序影响「把第 N 个加进去」的指代解析）"""
    agent = ProductResearchAgent()
    out = agent._extract_multiple_asins(
        f"{KNOWN_ASIN_B} 对比 {KNOWN_ASIN_A} 再看 {KNOWN_ASIN_B}")
    assert out == [KNOWN_ASIN_B, KNOWN_ASIN_A]


async def test_two_distinct_asins_still_route_to_competitor():
    """防修过头：两个**不同** ASIN 仍然是竞品对比的强信号"""
    agent = ProductResearchAgent()
    assert await agent._classify_intent(
        f"对比 {KNOWN_ASIN_A} 和 {KNOWN_ASIN_B}") == "competitor"


def test_dedup_is_not_reimplemented_at_the_call_site():
    """形态判据：去重**不得**在 `_classify_intent` 里再实现一遍（唯一真源）。

    ★ 为什么需要这条**独立于行为**的判据：在 `_classify_intent` 里补一句
      `len(set(self._extract_multiple_asins(query))) >= 2`，上面两条行为用例也会
      **全绿** —— 于是"看起来修好了"，而**另外 3 个消费点**（竞品对比 / 待补槽位 /
      入库目标解析）仍按重复计数。那正是
      「同一判定两份实现 ⇒ 至少一份永远测不到」。
      本判据专门抓这个形态：去重只允许住在 `_extract_multiple_asins` 里。
    ★ 走 AST 判 `ast.Call` 的**函数名**，不用源码字符串 —— docstring / 注释里
      写一句「此处不去重」就能骗过字符串判据。
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(ProductResearchAgent._classify_intent))
    dup_calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "set"
    ]
    assert not dup_calls, (
        "`_classify_intent` 里出现了 `set(...)` —— 去重被实现了第二遍。"
        "应当收口在 `_extract_multiple_asins`（唯一真源），否则其余 3 个消费点"
        "仍按重复计数。"
    )

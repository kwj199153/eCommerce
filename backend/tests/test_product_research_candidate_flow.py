"""
选品 Agent 「词 → 商品 → 选品库」链路回归测试

背景（bug）：老板在选品 Agent 对话里说
「exercise mat alignment lines 这个品帮我进入选品库」，
回复却是「未识别出具体类目，已按全类目高潜方向扫描，发现 8 个蓝海机会」——
把蓝海挖掘又跑了一遍。

两层根因：
1. **Agent 侧没有写入口**：`tools.py` 只有 4 个只读分析工具，「保存到选品库」
   只是前端卡片上的按钮（→ `POST /api/v1/candidates`），对话够不到；
   而「选品库」里含「选品」，恰好是 blue_ocean 的关键词 → 误判成挖掘。
2. **对话链的产物没有 ASIN**：`_analyze_blue_ocean` 只产关键词级机会，
   而候选库以 `asin` 为核心标识——就算加了工具，存进去也是空壳。

本文件覆盖三层修复：
A. 商品池统一（platforms/amazon/client.py 为唯一权威源）
B. 词 → 商品匹配（词边界命中，确定性）
C. 对话入库（意图优先级 + 目标解析 + payload 映射 + 判重）
D. 对话类回复的会话语境注入（不注入时 LLM 只会照提示词骨架编通用知识）
E. 入库槽位填充（面板流程的对话免填版：必填多轮追问、可选后台自动补）

其中 C 的目标解析后续又补了「点名商品 / 越界序数 / 判重」三处（见 C-4 段注释）：
只有「ASIN / 序数 / 否则上一轮 Top1」三条路时，用户贴整条商品标题会被错存成 Top1。
"""

import pytest

from modules.product_research.agent_product_research import ProductResearchAgent
from platforms.amazon.client import (
    CATEGORY_KEYS,
    MOCK_PRODUCTS,
    get_mock_products,
    match_products_by_keyword,
    tokenize,
)

QUERY_BLUE_OCEAN = "现在哪些货卖的比较火"
TARGET_KEYWORD = "exercise mat alignment lines"
TARGET_ASIN = "B0KLMN3456"

# 入库是**写业务数据**的动作，必须带一个"已校验归属"的店铺 ID。
# 本文件测的是"目标解析"（要入哪个商品），不是租户归属，所以固定用一个合成店铺即可：
#   - 常量 `store_test` 已登记在 conftest.SYNTHETIC_TEST_SHOP_IDS（外键前提）；
#   - `create_candidate` / `candidate_exists` 在本文件里都被 monkeypatch 拦掉，
#     不会真的落库，也不受真实店铺是否存在影响。
# ★ 为什么必须显式传而不能省略：P0 修复后 `_write_candidates` 缺 shop_id 时
#   **硬拒绝写入**（修复前它直读全局上下文，而那个值来自未校验的请求头）。
#   用例若不声明店铺，就等于在测一条已经不存在的旧契约。
TEST_SHOP = "store_test"


# ====== A. 商品池统一（唯一权威源） ======

def test_pool_covers_every_category_key():
    """统一池必须覆盖全部类目键（修复前 sports/pet/toys 等键对不上 → 永远退回 home_kitchen）"""
    for key in CATEGORY_KEYS:
        assert get_mock_products(key), f"类目 {key!r} 没有商品"


def test_pool_uses_canonical_field_names():
    """
    统一池只允许规范字段名：review_count / estimated_monthly_sales。

    修复前 service 内部池用的是 sales / reviews 别名，两边字段名不通，
    任何「跨池取数」都会 KeyError。
    """
    for p in MOCK_PRODUCTS:
        for field in ("asin", "title", "price", "review_count",
                      "estimated_monthly_sales", "roi", "category_key"):
            assert field in p, f"{p.get('asin')} 缺规范字段 {field!r}"
        assert "sales" not in p and "reviews" not in p, "不该再出现 sales/reviews 别名"


async def test_pool_category_filter_is_effective():
    """类目筛选真的生效——修复前前端下发 sports/pet 都会落空退回 home_kitchen"""
    from modules.product_research.schemas import BlueOceanRequest
    from modules.product_research.service import ProductResearchService

    result = await ProductResearchService().analyze_blue_ocean(
        BlueOceanRequest(category=["pet"])
    )
    assert result["products"], "pet 类目没返回任何商品"
    # 至少命中一个真宠物商品（说明筛选没落空）
    assert any("Pet" in p["category"] for p in result["products"]), (
        [p["category"] for p in result["products"]]
    )


# ====== B. 词 → 商品匹配 ======

def test_tokenize_drops_stopwords_and_short_tokens():
    assert tokenize("Yoga Mat for the Home") == ["yoga", "mat", "home"]


def test_match_products_finds_the_right_product():
    """老板点名的那个词必须落到对应的商品上"""
    hits = match_products_by_keyword(TARGET_KEYWORD, limit=3)
    assert hits, f"{TARGET_KEYWORD!r} 没匹配到任何商品"
    assert hits[0]["asin"] == TARGET_ASIN, hits[0]["title"]


def test_match_products_uses_word_boundary_not_substring():
    """
    ⚠️ 回归防线：子串匹配会让 `mat` 命中 `auto·mat·ic`，
    实测把「Automatic Pet Feeder」错误挂到了 `exercise mat alignment lines` 上。
    """
    hits = match_products_by_keyword(TARGET_KEYWORD, limit=10)
    asins = [h["asin"] for h in hits]
    assert "B0DXYZ1234" not in asins, "词边界失守：Automatic Pet Feeder 被误配"


def test_match_products_returns_empty_when_nothing_matches():
    """无命中必须返回空列表（而不是回退随机商品），调用方据此走降级路径"""
    assert match_products_by_keyword("glorbnak nonsense") == []


async def test_search_products_respects_query():
    """
    修复前 `search_products` 完全忽略 query，无条件 random.sample 返回 5 条随机商品，
    既导致「关键词 → 商品」这条路不存在，也让结果不可复现。
    """
    agent = ProductResearchAgent()
    hits = await agent.adapter.search_products(TARGET_KEYWORD)
    assert hits, "关键词检索无结果"
    assert hits[0].product_id == TARGET_ASIN

    # 确定性：同一 query 多次结果一致（不再随机）
    again = await agent.adapter.search_products(TARGET_KEYWORD)
    assert [p.product_id for p in hits] == [p.product_id for p in again]


# ====== C-1. 意图优先级 ======

@pytest.mark.parametrize("query", [
    "这个品帮我进入选品库",
    "把 exercise mat alignment lines 加入选品库",
    "保存到选品库",
    "加入候选池",
    "把这个商品存入选品库",
])
async def test_save_intent_wins_over_blue_ocean(query):
    """
    「选品库」里含「选品」，而「选品」是 blue_ocean 的关键词 ——
    所以 save 必须**先于** blue_ocean 判定，否则入库请求会被判成挖掘、又跑一遍。
    """
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "save_candidate"


@pytest.mark.parametrize("query", [
    "现在哪些货卖的比较火",
    "有什么冷门品类",
    "帮我选个男装品类的机会",
])
async def test_pure_discovery_still_routes_to_blue_ocean(query):
    """加了 save 关键词不能把正常的选品发现请求抢走"""
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "blue_ocean"


@pytest.mark.parametrize("query", [
    "Portable Mini Humidifier for Bedroom Desk USB Cool Mist帮我入库",
    "这个帮我入库",
    "把 B0CGLKP2R1 入库",
    "加入库",
    "存进选品库",
    "把这个加到选品",
])
async def test_colloquial_save_intent_is_recognized(query):
    """
    实测 bug（老板原话）：说「…USB Cool Mist帮我入库」，旧关键词表只有
    「加入库 / 存进选品」这类书面说法 → 一个都没命中 → 判成 general →
    商品名被**裸丢给 LLM 闲聊**，编出一大段通用市场分析
    （Google Trends「搜索热度较高」/ CE·FCC 认证 / 液体容器物流风险，全是套话），
    而商品池里明明就有这个品（B0HUMI0001），本该一句话入库成功。
    「入库」是电商语境里最高频的说法，必须认。
    """
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "save_candidate"


@pytest.mark.parametrize("query", ["你好呀", "今天几号"])
async def test_chitchat_is_not_mistaken_for_save(query):
    """补了「入库」这类宽词，不能反过来把真正的闲聊也吞成入库"""
    agent = ProductResearchAgent()
    assert await agent._classify_intent(query) == "general"


# ====== C-2. 目标商品解析 ======

def test_extract_ordinal_variants():
    assert ProductResearchAgent._extract_ordinal("把第 1 个加进选品库") == 0
    assert ProductResearchAgent._extract_ordinal("第2款入库") == 1
    assert ProductResearchAgent._extract_ordinal("第三个加入候选池") == 2
    assert ProductResearchAgent._extract_ordinal("top1 入库") == 0
    assert ProductResearchAgent._extract_ordinal("这个品帮我进入选品库") is None


async def _agent_with_last_result():
    """跑一轮蓝海，让 Agent 持有「上一轮结果」（供指代解析）"""
    agent = ProductResearchAgent()
    await agent._analyze_blue_ocean(QUERY_BLUE_OCEAN)
    return agent


@pytest.fixture
def captured_candidates(monkeypatch):
    """拦截 create_candidate，捕获 payload（不落库，避免污染真实数据库）"""
    captured: list[dict] = []

    async def _fake(payload, shop_id=None):
        captured.append({"payload": payload, "shop_id": shop_id})
        return {**payload, "id": f"cand-test-{len(captured)}"}

    monkeypatch.setattr("modules.candidates.service.create_candidate", _fake)
    return captured


async def test_save_without_context_asks_instead_of_writing_empty(captured_candidates):
    """既没跑过蓝海、也没给 ASIN → 必须追问，绝不写一条空壳候选"""
    agent = ProductResearchAgent()
    result = await agent._save_candidate("这个品加进选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert result.get("error")
    assert captured_candidates == [], "不该发生写入"


async def test_save_resolves_pronoun_to_top1(captured_candidates):
    """「这个品」→ 上一轮蓝海结果的 Top 1"""
    agent = await _agent_with_last_result()
    result = await agent._save_candidate("这个品帮我进入选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_saved"
    payload = captured_candidates[0]["payload"]
    assert payload["asin"] == TARGET_ASIN
    assert payload["source"] == "blue_ocean"


async def test_save_carries_market_layer_into_notes_and_keywords(captured_candidates):
    """
    市场层不能丢：词虽然退出了主列表，但要随商品带下去
    （keywords + notes 里留来源机会词，便于回溯成色来源）。
    """
    agent = await _agent_with_last_result()
    await agent._save_candidate("把第 1 个加进选品库", shop_id=TEST_SHOP)

    payload = captured_candidates[0]["payload"]
    assert payload["keywords"], "候选必须记录来源机会词"
    assert "来源机会词" in payload["notes"]
    # 商品层字段也要齐（否则候选库列表页全是空列）
    assert payload["price"] > 0
    assert payload["estimated_monthly_sales"] > 0
    assert payload["roi_estimated"] > 0
    assert payload["blue_ocean_score"] > 0


async def test_save_resolves_explicit_asin(captured_candidates):
    """显式给 ASIN 时不需要上下文，也不该被代词逻辑覆盖"""
    agent = ProductResearchAgent()
    await agent._save_candidate("把 B0CGLKP2R1 加入选品库", shop_id=TEST_SHOP)

    assert captured_candidates[0]["payload"]["asin"] == "B0CGLKP2R1"


async def test_save_resolves_ordinal(captured_candidates):
    """「第 2 个」应取上一轮结果的第 2 条，而不是永远 Top 1"""
    agent = await _agent_with_last_result()
    products = agent._last_blue_ocean["products"]
    assert len(products) >= 2, "用例前提：上一轮结果至少 2 条"

    await agent._save_candidate("把第 2 个加进选品库", shop_id=TEST_SHOP)
    assert captured_candidates[0]["payload"]["asin"] == products[1]["asin"]


# ====== C-4. 点名商品 / 越界序数 / 判重 ======
#
# 实测 bug：老板贴进整条商品标题
# 「Automatic Pet Feeder, Smart Food Dispenser with WiFi App Control for Cats and Dogs」
# 说「帮我加到选品库」，回复却是「已加入选品库：Yoga Mat with Alignment Lines（B0KLMN3456）」
# —— 又存了一遍上一轮蓝海 Top1 的瑜伽垫（累计 3 条重复）。
# 根因：解析只有「ASIN / 序数 / 否则 Top1」三条路，**没有按标题核对商品池这一步**。

NAMED_TITLE = "Automatic Pet Feeder, Smart Food Dispenser with WiFi App Control for Cats and Dogs"
NAMED_ASIN = "B0DXYZ1234"


async def test_save_resolves_product_named_in_query(captured_candidates):
    """查询里点名了商品（整条标题）→ 按标题去商品池核对，而不是落到上一轮 Top1"""
    agent = await _agent_with_last_result()
    assert agent._last_blue_ocean["products"][0]["asin"] == TARGET_ASIN, \
        "用例前提：上一轮 Top1 是瑜伽垫（这样才构成「错存」的复现条件）"

    result = await agent._save_candidate(f"{NAMED_TITLE} 帮我加到选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_saved"
    payload = captured_candidates[0]["payload"]
    assert payload["asin"] == NAMED_ASIN, "必须入库被点名的宠物喂食器"
    assert payload["asin"] != TARGET_ASIN, "不能被上一轮 Top1 覆盖"


async def test_save_asks_when_named_product_not_in_pool(captured_candidates):
    """点名了商品但商品池匹配不到 → 追问，绝不改存上一轮 Top1 来充数"""
    agent = await _agent_with_last_result()
    result = await agent._save_candidate("把 Titanium Space Suit For Hamsters 加进选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert result.get("error")
    assert captured_candidates == [], "匹配不到就不该写任何东西"


async def test_save_rejects_out_of_range_ordinal(captured_candidates):
    """序数越界要追问并告知实际条数，不能静默折回第 1 个"""
    agent = await _agent_with_last_result()
    n = len(agent._last_blue_ocean["products"])
    assert n >= 2, "用例前提：上一轮结果至少 2 条"

    result = await agent._save_candidate(f"把第 {n + 5} 个加进选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert str(n) in result["error"], "应告知上一轮实际条数"
    assert captured_candidates == []


async def test_save_skips_existing_asin(monkeypatch, captured_candidates):
    """同店铺同 ASIN 已在库 → 不重复写入，回「已在选品库中」"""
    async def _always_exists(asin, shop_id=None):
        return True

    monkeypatch.setattr("modules.candidates.service.candidate_exists", _always_exists)

    agent = await _agent_with_last_result()
    result = await agent._save_candidate("这个品帮我进入选品库", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_saved"
    assert result["skipped"], "应走判重分支"
    assert "未重复写入" in result["summary"]
    assert captured_candidates == [], "已存在时不该写库"


# 老板原话的端到端回归（意图 + 目标解析两条链路一起锁）
HUMIDIFIER_QUERY = "Portable Mini Humidifier for Bedroom Desk USB Cool Mist帮我入库"
HUMIDIFIER_ASIN = "B0HUMI0001"


async def test_save_full_title_with_colloquial_verb(captured_candidates):
    """
    贴一整条商品标题 + 「帮我入库」（老板实际那句话）→ 必须入库**这个**商品。

    这句话同时踩了两个坑：
      ① 意图层缺「入库」→ 判成 general，走 LLM 闲聊（编通用市场分析）；
      ② 即便意图对了，目标解析也得靠「按标题核对商品池」命中，
         否则会落到上一轮 Top1 —— 而上一轮 Top1 是瑜伽垫，又存错。
    """
    agent = await _agent_with_last_result()
    assert agent._last_blue_ocean["products"][0]["asin"] == TARGET_ASIN, \
        "用例前提：上一轮 Top1 是瑜伽垫（构成「错存」的复现条件）"

    assert await agent._classify_intent(HUMIDIFIER_QUERY) == "save_candidate"

    result = await agent._save_candidate(HUMIDIFIER_QUERY, shop_id=TEST_SHOP)

    assert result["type"] == "candidate_saved"
    assert captured_candidates[0]["payload"]["asin"] == HUMIDIFIER_ASIN, \
        "必须入库被点名的加湿器"
    assert captured_candidates[0]["payload"]["asin"] != TARGET_ASIN, \
        "不能被上一轮 Top1 覆盖"


async def test_named_tokens_ignore_action_words():
    """英文动作词不算「点名商品」——否则 add this to my candidate library 会被误判为点了名"""
    agent = ProductResearchAgent()
    assert agent._named_tokens("add this to my candidate library") == []
    assert agent._named_tokens("这个品帮我进入选品库") == []
    assert agent._named_tokens("把第 2 个加进选品库") == []
    assert agent._named_tokens(NAMED_TITLE), "真正的商品标题必须留下实词"


# ====== C-3. 入库动作不该出结论卡 ======

async def test_chat_stream_skips_meta_for_save_action(
    client, auth_off, fake_llm, captured_candidates
):
    """
    入库是「动作回执」不是「分析结论」——不能下发 meta，
    否则会污染前端「最近结果」槽（把刚看的商品卡顶掉）。
    """
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": "这个品帮我进入选品库"},
    )
    assert r.status_code == 200, r.text
    assert "event: meta" not in r.text, r.text


# ====== D. 对话类回复的会话语境注入 ======


def test_session_context_block_forbids_fabrication_without_context():
    """
    没跑过蓝海时也要带上输出约束。

    旧实现把 query **裸丢给 LLM**（只有角色提示词），LLM 手里没有真实数据，
    只能照 system prompt 里「数据驱动 / 趋势洞察 / 风险意识」的骨架编通用知识
    —— 实测编出「Google Trends 搜索热度较高」「CE、FCC 认证」「液体容器运输限制」。
    """
    agent = ProductResearchAgent()
    assert agent._last_blue_ocean is None, "用例前提：还没跑过蓝海"

    block = agent._session_context_block()

    assert "严禁编造" in block
    assert "追问" in block, "没说清入哪个时必须让 LLM 反问，而不是假装已完成"
    assert "候选商品" not in block, "没有上一轮结果时不该凭空捏出商品清单"


async def test_session_context_block_surfaces_real_products():
    """跑过蓝海后，LLM 必须能看到真实候选商品（ASIN + 标题 + 售价）"""
    agent = await _agent_with_last_result()
    block = agent._session_context_block()

    first = agent._last_blue_ocean["products"][0]
    assert first["asin"] in block, "真实 ASIN 要摆到 LLM 面前"
    assert (first["title"] or "")[:12] in block
    assert "严禁编造" in block


# ====== E. 入库槽位填充（面板流程的对话版）======
#
# 面板流程（蓝海结果卡 → 勾选 → 选分组 → 保存）里：
#   - 必填：ASIN + 商品标题
#   - 可选：售价/月销/蓝海评分/ROI/备注/**分组**（不选也能入库）
# 对话入库是同一套流程的「免填版」：
#   - 必填缺失 → 多轮追问补齐（有状态，见 pending_save）
#   - 可选缺失 → 后台按默认值自动补，不打扰用户


def test_required_fields_match_panel():
    """必填契约必须与面板「手动录入候选」弹窗的 required 一致"""
    from modules.candidates.service import CANDIDATE_REQUIRED_FIELDS

    assert CANDIDATE_REQUIRED_FIELDS == ("asin", "title")


def test_missing_required_fields_ignores_optional():
    """可选字段缺了**不算缺** —— 面板对可选就是「不填走默认值」，不该因此打扰用户"""
    from modules.candidates.service import describe_missing_fields, missing_required_fields

    assert missing_required_fields({"asin": "B01", "title": "T"}) == []
    assert missing_required_fields({"asin": "", "title": "T"}) == ["asin"]
    assert missing_required_fields({"asin": "B01", "title": "   "}) == ["title"]
    assert missing_required_fields({}) == ["asin", "title"]
    # 只有选项缺 → 不算缺
    assert missing_required_fields({"asin": "B01", "title": "T", "price": None}) == []
    assert describe_missing_fields(["title"]) == "商品标题"


async def test_ask_records_pending_and_is_not_a_failure(captured_candidates):
    """
    目标说不清 → 追问并**记下待补槽位**（这是多轮补齐的前提）。

    追问用 `soft_error` 标记：它是对话的正常一步，文案不该被套上「这次没跑通」。
    """
    agent = ProductResearchAgent()
    result = await agent._save_candidate("帮我入库", context_id="ctx-ask", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert result.get("soft_error") is True
    assert "这次没跑通" not in agent._compose_reply(result)
    assert captured_candidates == [], "追问阶段不该写库"

    pending = agent._session("ctx-ask")["pending_save"]
    assert set(pending["awaiting"]) == {"asin", "title"}


async def test_slot_filling_second_turn_completes_save(captured_candidates):
    """
    多轮补齐：第 1 轮追问 → 第 2 轮用户只回一个 ASIN → 自动补标题并入库。

    修复前追问是**无状态**的：用户回「B0CGLKP2R1」不含入库关键词 → 判成 general 跑偏，
    这条链路根本走不下去。
    """
    agent = ProductResearchAgent()
    ctx = "ctx-fill"

    first = await agent._save_candidate("帮我入库", context_id=ctx, shop_id=TEST_SHOP)
    assert first["type"] == "candidate_save_failed"

    second = await agent._resume_pending_save("B0CGLKP2R1", ctx, shop_id=TEST_SHOP)
    assert second is not None and second["type"] == "candidate_saved"

    payload = captured_candidates[0]["payload"]
    assert payload["asin"] == "B0CGLKP2R1"
    assert payload["title"], "标题要从商品池自动补，不能留空"
    assert agent._session(ctx).get("pending_save") is None, "补齐后必须清 pending"


async def test_slot_filling_accepts_product_name(captured_candidates):
    """第 2 轮用户回的是商品名（不是 ASIN）→ 同样要能补齐"""
    agent = ProductResearchAgent()
    ctx = "ctx-name"
    await agent._save_candidate("帮我入库", context_id=ctx, shop_id=TEST_SHOP)

    result = await agent._resume_pending_save("Yoga Mat with Alignment Lines", ctx, shop_id=TEST_SHOP)

    assert result["type"] == "candidate_saved"
    assert captured_candidates[0]["payload"]["asin"] == TARGET_ASIN


async def test_cancel_clears_pending(captured_candidates):
    """用户说「算了」→ 清 pending，不再追问，也不写库"""
    agent = ProductResearchAgent()
    ctx = "ctx-cancel"
    await agent._save_candidate("帮我入库", context_id=ctx, shop_id=TEST_SHOP)

    result = await agent._resume_pending_save("算了，不弄了", ctx, shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert result.get("soft_error") is True
    assert agent._session(ctx).get("pending_save") is None
    assert captured_candidates == []


async def test_topic_change_releases_pending(captured_candidates):
    """用户在待补期间换了话题（说了别的结构化意图）→ 放弃 pending，交回常规流程"""
    agent = ProductResearchAgent()
    ctx = "ctx-topic"
    await agent._save_candidate("帮我入库", context_id=ctx, shop_id=TEST_SHOP)

    assert await agent._resume_pending_save("帮我挖点蓝海机会", ctx, shop_id=TEST_SHOP) is None
    assert agent._session(ctx).get("pending_save") is None


async def test_unknown_asin_asks_for_title(captured_candidates):
    """
    给了 ASIN 但商品库/蓝海结果里都没有 → 标题就是缺的，追问补齐。

    不能拿 ASIN 当标题硬写一条半成品（面板里标题是必填项）。
    """
    agent = ProductResearchAgent()
    result = await agent._save_candidate("把 B0ZZZZZZZZ 加入选品库", context_id="ctx-unknown", shop_id=TEST_SHOP)

    assert result["type"] == "candidate_save_failed"
    assert result.get("soft_error") is True
    assert result["awaiting"] == ["title"]
    assert captured_candidates == []


async def test_save_payload_aligns_with_panel(captured_candidates):
    """
    payload 对齐面板 `mapToCandidate`：sku 自动生成、tags/notes 自动拼，
    **分组后台兜底**（面板里分组是唯一的人工交互，对话版不该为它打断用户）。
    """
    agent = await _agent_with_last_result()
    await agent._save_candidate("这个品帮我进入选品库", shop_id=TEST_SHOP)

    payload = captured_candidates[0]["payload"]
    assert payload["sku"].startswith("SKU-CAND-")
    assert payload["groups"] == [], "分组后台化：默认不分组"
    assert payload["tags"], "tags 应自动生成"
    assert payload["notes"], "notes 应自动生成"
    assert payload["source"] == "blue_ocean"
    assert payload["currency"] == "USD"


async def test_sessions_are_isolated(captured_candidates):
    """
    会话隔离：service 是**全局单例**，状态若挂在实例上会跨会话串数据 ——
    A 会话挖的蓝海会被 B 会话的「第 1 个入库」取走。
    """
    agent = ProductResearchAgent()

    await agent._save_candidate("帮我入库", context_id="sess-A", shop_id=TEST_SHOP)
    assert agent._session("sess-A").get("pending_save")
    assert agent._session("sess-B").get("pending_save") is None, "B 会话不该看到 A 的待补项"

    await agent._analyze_blue_ocean(QUERY_BLUE_OCEAN, "sess-B")
    assert agent._last_products("sess-B"), "B 会话应有自己的蓝海结果"
    assert agent._last_products("sess-A") == [], "A 会话不该看到 B 的蓝海结果"


def test_legacy_alias_reads_default_session():
    """`_last_blue_ocean` 只读别名指向默认会话（兼容既有用法）"""
    agent = ProductResearchAgent()
    agent._session(None)["last_blue_ocean"] = {"products": [{"asin": "B01"}]}

    assert agent._last_blue_ocean["products"][0]["asin"] == "B01"
    assert agent._last_products("other") == [], "别的会话不该看到默认会话的结果"

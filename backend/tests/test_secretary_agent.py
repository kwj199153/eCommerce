"""
店秘书（主 Agent）工具循环冒烟测试

验证「主 Agent 绑工具」整条链路的机制正确性，**不依赖真实 LLM**：

1. BaseAgent 修复后的 bind_tools 真的生效（LLM 产出 tool_calls 时，
   _should_continue 会走 tool_node，而不是永远 respond）。
2. 工具注册表 4 个工具已正确构建、参数 schema 来自 Pydantic 模型。
3. 「润色标题」这类语义能命中 optimize_listing_title 工具（通过 fake LLM
   直接产出 tool_calls 验证路由链路，而非验证真实模型判断）。

真实 LLM 判断的正确性需连线上环境人工/联调确认，这里只验证机制闭环。
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent
from modules.listing_generator.tools import listing_tools
from modules.aigc_media.tools import aigc_tools
from modules.secretary.agent import SecretaryAgent, SECRETARY_SYSTEM_PROMPT
from modules.secretary.navigation_tools import navigation_tools, _switch_agent, _open_view, _open_account_menu, _handoff_to_agent, _set_theme
from modules.secretary.product_tools import build_product_tools
from modules.secretary.shop_tools import build_shop_tools
from modules.product_research.tools import product_research_tools
from modules.customer_service.tools import customer_service_tools
from modules.ad_analysis.tools import ad_analysis_tools


def test_listing_tools_registry():
    """8 个工具注册正确（4 细粒度 + 4 粗粒度），参数 schema 来自 Pydantic 模型"""
    names = {t.name for t in listing_tools}
    assert names == {
        "optimize_listing_title",
        "generate_bullet_points",
        "generate_product_description",
        "generate_search_terms",
        "generate_complete_listing",
        "optimize_listing",
        "analyze_listing_seo",
        "generate_ab_test_variants",
    }
    # 工具应携带 args_schema（Pydantic），LLM 才能看到字段描述
    for t in listing_tools:
        assert t.args_schema is not None, f"{t.name} 缺少 args_schema"


def test_aigc_tools_registry():
    """9 个 AIGC 工具注册正确，参数 schema 来自 Pydantic 模型"""
    names = {t.name for t in aigc_tools}
    assert names == {
        "generate_product_image",
        "generate_assets",
        "analyze_main_image",
        "generate_a_plus_content",
        "generate_brand_story",
        "translate_content",
        "generate_infographic",
        "check_image_compliance",
        "generate_video_script",
    }
    for t in aigc_tools:
        assert t.args_schema is not None, f"{t.name} 缺少 args_schema"


def test_navigation_tools_marker():
    """导航工具返回结构化 action 标记，供前端 dispatchAppAction 消费"""
    names = {t.name for t in navigation_tools}
    # ★ 第 145 轮 批 B3 加 `ask_clarification`（提问工具）—— 它虽不产导航标记，
    #   但与 `handoff_to_agent` 同属「协调」类，且必须排在它**之前**（先问后交）。
    assert names == {
        "switch_agent",
        "open_view",
        "open_account_menu",
        "handoff_to_agent",
        "set_theme",
        "ask_clarification",
    }

    assert '"switch_agent"' in _switch_agent("product-research")
    assert '"product-research"' in _switch_agent("product-research")

    # 路由带参：老板原话透传进 query，子 Agent 据此自动续跑
    with_query = _switch_agent("product-research", "比较好卖的品类有哪些")
    assert '"query"' in with_query
    assert "比较好卖的品类有哪些" in with_query
    # 纯导航：不带 query，保持旧契约（前端只切页、不续跑）
    assert '"query"' not in _switch_agent("product-research")

    assert '"navigate"' in _open_view("products")
    assert '"products"' in _open_view("products")

    # account_menu 网关：返回账户菜单标记 + target
    menu_out = _open_account_menu("subscription")
    assert '"account_menu"' in menu_out
    assert '"subscription"' in menu_out

    # handoff 工具：返回交接标记 + 意图 + 缺失字段
    handoff_out = _handoff_to_agent("aigc-media", "生成水壶白底图", ["材质", "造型", "视角"])
    assert '"handoff"' in handoff_out
    assert '"aigc-media"' in handoff_out
    assert '生成水壶白底图' in handoff_out
    assert '材质' in handoff_out

    # set_theme 工具：返回主题切换标记 + 目标主题
    theme_out = _set_theme("dark")
    assert '"set_theme"' in theme_out
    assert '"dark"' in theme_out


def test_handoff_carries_the_boss_original_words():
    """★ 第 215 轮：handoff 必须能把老板**原话**一起带过去。

    事故链条：老板贴了一条 Amazon 链接要求入库 → 店秘书走了 handoff → 而 handoff
    的 payload 里只有一句概括（`intent`），**链接本身丢了**；前端又只渲染追问、
    不续跑 ⇒ 老板看到的是一个「读不懂链接、只会反问 asin / title」的假 Agent。

    判据是**行为**：原话进 → payload 里有原话。
    """
    url = "https://www.amazon.com/dp/B09V9TXTKK?pd_rd_i=B09V9TXTKK"
    out = _handoff_to_agent("product-research", "把商品加入选品库", ["asin"], query=url)
    data = json.loads(out)
    assert data["action"] == "handoff"
    assert data["query"] == url, "老板原话没进 payload —— 交接后链接就永久丢了"


def test_handoff_without_query_keeps_the_old_shape():
    """不传 query（或只传空白）时 payload **不带** query 键 —— 纯导航语义，不与空串混淆"""
    data = json.loads(_handoff_to_agent("aigc-media", "生成水壶白底图", ["材质"]))
    assert "query" not in data, "不传 query 时不该凭空多出一个键"

    blank = json.loads(_handoff_to_agent("aigc-media", "生成水壶白底图", ["材质"], query="   "))
    assert "query" not in blank, "空白原话不该被当成有效 query"


def test_product_tools_registry():
    """select_product 工具正确构建，空店铺返回空标记"""
    tools = build_product_tools(shop_id="")
    names = {t.name for t in tools}
    assert names == {"select_product"}


def test_shop_tools_registry():
    """店铺工具正确构建：只读 `list_shops` + 替换语义的 `switch_shop`。

    ★ 第 243 轮（第 240 轮方案 A′）：修前这里断言的是 `== {"switch_shop"}` ——
      它把「店秘书**没有**读店铺的工具」这个**缺陷**钉成了规格（本仓判据
      「门禁是墓志铭」：需求变了，钉住旧形态的断言就从资产变负资产）。
      现在把「读有哪些店铺」与「切店铺」拆成两个工具，本条随之收紧为两者都在。
    """
    tools = build_shop_tools()
    names = {t.name for t in tools}
    assert names == {"list_shops", "switch_shop"}


# ============================================================
# 八、switch_shop 的「切错店」防护（2026-09-14 事故）
# ============================================================
#
# 事故现场：老板说「切換到蝦皮2」→ 后端返回 shop=虾皮1。
# 根因：工具只有 `nth`（全局序号），LLM 只能硬猜全局序号 → 猜成第 3 个（虾皮1）。
# 老板说「第二个虾皮店铺」时，语义是**平台内**第 2 个，工具无法表达 ⇒ 必然错。
#
# 修复：给工具加 `platform` + `platform_nth`，并让 `_list_shops` 标注平台内序号。
# 本段把三类匹配路径钉死，防回归。

@pytest.mark.asyncio
async def test_platform_family_groups_sites():
    """`shopee_my` / `shopee_tw` 必须归到同一家族 `shopee`。

    否则「虾皮」这类平台级说法无法筛出全部虾皮店铺 —— 这是「第二个虾皮店铺」
    能被正确定位的前提。
    """
    from modules.secretary.shop_tools import _platform_family

    assert _platform_family("shopee_my") == "shopee"
    assert _platform_family("shopee_tw") == "shopee"
    assert _platform_family("amazon_us") == "amazon"
    assert _platform_family("amazon_uk") == "amazon"
    assert _platform_family("temu_us") == "temu"
    assert _platform_family("tiktok") == "tiktok"
    # 未知平台原样返回（不吞掉，便于排查）
    assert _platform_family("unknown_x") == "unknown_x"
    # 空值不炸
    assert _platform_family("") == ""
    assert _platform_family(None) == ""


@pytest.mark.asyncio
async def test_list_shops_exposes_platform_index():
    """`_list_shops` 必须同时给出**全局序号**与**平台内序号**。

    为什么两者都要：老板既可能说「第 3 个店铺」（全局），也可能说
    「第二个虾皮店铺」（平台内）。少任何一个，LLM 就只能靠猜。
    """
    from modules.secretary.shop_tools import _list_shops

    shops = await _list_shops()
    if not shops:
        pytest.skip("库中无店铺（需先 seed），跳过")

    # 全局序号必须连续且从 1 开始（与 SHOP_ORDER_BY 的顺序一致）
    assert [s["index"] for s in shops] == list(range(1, len(shops) + 1))
    assert all(s["total"] == len(shops) for s in shops)

    # 平台内序号：按家族分组后各自从 1 连续递增
    seen: dict = {}
    for s in shops:
        fam = s["platform_family"]
        seen[fam] = seen.get(fam, 0) + 1
        assert s["platform_index"] == seen[fam], (
            f"{s['name']} 的平台内序号应为 {seen[fam]}，实为 {s['platform_index']}"
        )
    # platform_total 与分组计数一致
    for s in shops:
        assert s["platform_total"] == seen[s["platform_family"]]


@pytest.mark.asyncio
async def test_switch_shop_by_exact_name_wins():
    """按**完整店铺名**切换必须命中该店（原 bug：说「虾皮2」却切到虾皮1）。

    ⚠️ 覆盖度说明（诚实标注）：本条钉住的是「名称可达性」—— 每个店铺都能
       用它的全名切到。它**不能**区分「全字匹配」与「子串匹配」（当店铺名
       本身就是 `虾皮2` 时两者等价）；真正防住本次事故的是
       `test_switch_shop_by_platform_nth`（「平台内序数」路径）。
       「全字优先」的价值在于 `虾皮1` 不误配 `虾皮10` —— 需库中存在
       同前缀店铺才会显形，属**前向防护**，当前数据下无法构造。
    """
    import json as _json
    from modules.secretary.shop_tools import _list_shops, _switch_shop

    shops = await _list_shops()
    if not shops:
        pytest.skip("库中无店铺（需先 seed），跳过")

    for s in shops:
        res = _json.loads(await _switch_shop(shop_name=s["name"]))
        assert res["shop"] is not None, f"按全名「{s['name']}」切换失败：{res}"
        assert res["shop"]["id"] == s["id"], (
            f"按全名「{s['name']}」切换到了 {res['shop']['name']} —— 名称匹配错位"
        )


@pytest.mark.asyncio
async def test_switch_shop_exact_name_not_substring_of_other(tmp_path):
    """「全字优先」的单元级验证：`虾皮1` 不得被 `虾皮10` 之类的**包含关系**带偏。

    用**构造数据**验证匹配算法的选优顺序（不依赖库里恰好有同前缀店铺）：
    直接调用内部匹配逻辑的等价实现 —— 即「先找全字相等，再退子串」。
    这里用 monkeypatch 把一个假的 `_list_shops` 注入，构造 `虾皮1` / `虾皮10`。
    """
    import json as _json
    import modules.secretary.shop_tools as st

    fake = [
        {"id": "s10", "name": "虾皮10", "platform": "shopee_my",
         "index": 1, "platform_family": "shopee", "platform_index": 1,
         "platform_total": 2, "total": 2},
        {"id": "s1", "name": "虾皮1", "platform": "shopee_my",
         "index": 2, "platform_family": "shopee", "platform_index": 2,
         "platform_total": 2, "total": 2},
    ]

    async def fake_list():
        return fake

    orig = st._list_shops
    st._list_shops = fake_list
    try:
        # 「虾皮1」必须命中 s1（全字），而不是排在前面、子串也能中的「虾皮10」
        res = _json.loads(await st._switch_shop(shop_name="虾皮1"))
        assert res["shop"]["id"] == "s1", (
            f"「虾皮1」被「虾皮10」带偏了 → {res['shop']['name']}"
        )
        # 「虾皮10」也能正确命中自己
        res2 = _json.loads(await st._switch_shop(shop_name="虾皮10"))
        assert res2["shop"]["id"] == "s10"
    finally:
        st._list_shops = orig


@pytest.mark.asyncio
async def test_switch_shop_by_platform_nth():
    """★ 核心回归：「平台内第 N 个」必须能正确定位（「第二个虾皮店铺」场景）。"""
    import json as _json
    from modules.secretary.shop_tools import _list_shops, _switch_shop

    shops = await _list_shops()
    if not shops:
        pytest.skip("库中无店铺（需先 seed），跳过")

    fams = {s["platform_family"] for s in shops}
    for fam in fams:
        fam_shops = [s for s in shops if s["platform_family"] == fam]
        for pos in range(1, len(fam_shops) + 1):
            res = _json.loads(await _switch_shop(platform=fam, platform_nth=pos))
            expect = fam_shops[pos - 1]
            assert res["shop"]["id"] == expect["id"], (
                f"{fam} 平台内第 {pos} 个应为 {expect['name']}，"
                f"实为 {res['shop']['name']}"
            )


@pytest.mark.asyncio
async def test_switch_shop_name_beats_platform_nth():
    """匹配优先级：`shop_name` 必须优先于 `platform_nth`（精确 > 模糊）。"""
    import json as _json
    from modules.secretary.shop_tools import _list_shops, _switch_shop

    shops = await _list_shops()
    shopee = [s for s in shops if s["platform_family"] == "shopee"]
    if len(shopee) < 2:
        pytest.skip("虾皮店铺不足 2 个，无法验证优先级")

    last = shopee[-1]
    # 同时给出「平台内第 1 个」与「全名指到最后一个」——应以全名为准
    res = _json.loads(
        await _switch_shop(shop_name=last["name"], platform="shopee", platform_nth=1)
    )
    assert res["shop"]["id"] == last["id"], "shop_name 未能压过 platform_nth"


@pytest.mark.asyncio
async def test_switch_shop_global_nth_still_works():
    """兜底路径不能坏：只说「第 N 个店铺」时仍按全局序号切换。"""
    import json as _json
    from modules.secretary.shop_tools import _list_shops, _switch_shop

    shops = await _list_shops()
    if not shops:
        pytest.skip("库中无店铺（需先 seed），跳过")

    for s in shops:
        res = _json.loads(await _switch_shop(nth=s["index"]))
        assert res["shop"]["id"] == s["id"], (
            f"全局第 {s['index']} 个应为 {s['name']}，实为 {res['shop']['name']}"
        )

    # 越界序号必须被夹取到边界，而不是抛异常 / 返回 None
    res_over = _json.loads(await _switch_shop(nth=999))
    assert res_over["shop"]["id"] == shops[-1]["id"]
    res_under = _json.loads(await _switch_shop(nth=-5))
    assert res_under["shop"]["id"] == shops[0]["id"]


@pytest.mark.asyncio
async def test_switch_shop_action_matches_frontend_contract():
    """工具返回的 action 结构必须与前端 `switch_shop` 分支期望一致。

    前端消费的是 `{action:'switch_shop', shop:{id,name,platform}}`，
    并只依赖 `shop.id`。这里钉住字段名与类型，防止后端改名后前端静默失效
    （前端无类型可依赖 —— 跨语言边界只能靠契约测试）。
    """
    import json as _json
    from modules.secretary.shop_tools import _list_shops, _switch_shop

    shops = await _list_shops()
    if not shops:
        pytest.skip("库中无店铺（需先 seed），跳过")

    res = _json.loads(await _switch_shop(shop_name=shops[0]["name"]))
    assert res["action"] == "switch_shop"
    assert isinstance(res["shop"], dict)
    for key in ("id", "name", "platform"):
        assert key in res["shop"], f"shop 缺字段 {key}（前端依赖它）"
        assert isinstance(res["shop"][key], str)
    assert res["shop"]["id"] == shops[0]["id"]
    # index / total 是给人看与日志用的辅助信息，不应缺失
    assert res["index"] == shops[0]["index"]
    assert res["total"] == len(shops)



def test_product_research_tools_registry():
    """选品分析 10 个工具正确构建（4 个只读分析 + 3 个写入 + 1 个只读详情
    + 6 个**跨 Agent 共用**）。

    ★ 7 → 10（第 205 轮批 B）：新增候选生命周期的三条原子工具
      `get_candidate` / `review_candidate` / `approve_candidate`。
      它们的实现原先**只内联在 `candidates/router.py` 的 handler 里**，
      Agent 够不着 —— 正是第 204 轮盘点里老板点名的两条缺口
      （「获取选品」与「入产品库」）。其中「入产品库」是候选 → 产品库的
      **唯一通道**，不补上则选品闭环在 Agent 侧断掉。
      ★ `review_candidate` / `approve_candidate` 声明了 `SIDE_EFFECT_METADATA`
      ⇒ 会被 `BaseAgent._wrap_hitl_tools()` **自动**包进人工审批
      （见 `tests/test_hitl_wiring.py`）。

    ★ 5 → 7（第 205 轮批 A）：尾部追加了 `list_candidates` / `list_products`
      —— 它们来自 `modules/library/`（SHARED 层），与店秘书手里的是
      **同一个实现**。收敛动因：`GET /api/v1/candidates` 与 `GET /api/v1/skus`
      此前被不同 Agent 提议成不同名字，而「同一能力两个名字」会让模型在两处
      乱选、测试只覆盖其中一条。共用关系本身由
      `tests/test_tool_catalog.py::test_shared_tool_agents_match_runtime_holders`
      与 `...::test_one_capability_has_exactly_one_implementation` 钉住。
    """
    names = {t.name for t in product_research_tools}
    assert names == {
        "analyze_blue_ocean",
        "analyze_profit",
        "analyze_pain_points",
        "compare_competitor_listings",
        "save_candidate",
        "get_candidate",
        "review_candidate",
        "approve_candidate",
        "query_market_insight",
        "list_candidates",
        "list_products",
        "list_assets",
        "list_monitors",
        "list_faqs",
        "list_platform_rules",
    }


def test_customer_service_tools_registry():
    """智能客服 4 个自有工具 + 6 个 trade 域工具（共 10 个）

    ★ 第 283 轮：客服从「话术 + 建单」升级为「能取订单 / 物流 / 差评证据」，
      5 个 trade 域工具经 `modules/trade` 门面挂进来（接线与理由见
      `modules/customer_service/tools.py` 文件头）。

    ★★ 这 5 个名字**必须写字面量**，不许 `from modules.trade import trade_tools`
      后再 `{t.name for t in trade_tools}` —— 那样期望值由被测对象自己提供，
      「接线掉了」和「接线在」会得到同一个结果 ⇒ 假绿。
    """
    names = {t.name for t in customer_service_tools}
    assert names == {
        # ---- 客服自有 4 个 ----
        "search_faq",
        "create_ticket",
        "analyze_sentiment",
        "get_conversation_summary",
        # ---- trade 域 6 个：订单 / 差评列表 / 差评上下文 / 健康分 / 补偿建议 / 处置草稿 ----
        "fetch_order_tracking",
        "list_customer_reviews",
        "get_customer_review_context",
        "get_sku_health_score",
        "plan_compensation",
        # ★ 第 287 轮 P0-2：`review_dispositions` 唯一的 Agent 侧写入点。
        #   表里全库 0 行的根因就是没有它 —— 有模型有状态机，没人往里写。
        "propose_review_disposition",
    }


def test_ad_analysis_tools_registry():
    """广告分析 4 个工具正确构建（第 316 轮由 6 收敛到 4）"""
    names = {t.name for t in ad_analysis_tools}
    assert names == {
        "diagnose_ad_account",
        "analyze_search_terms",
        "optimize_bids",
        "analyze_ad_competitors",
    }


def test_secretary_agent_binds_tools():
    """店秘书 agent 应持有 19 个工具（16 业务/导航 + 2 规划 + 1 技能加载），业务细粒度工具全部下沉到子 Agent"""
    agent = SecretaryAgent(llm=MagicMock())
    # 8 → 9：第 145 轮 批 B3 把「提问」从提示词规则升级成真工具（`ask_clarification`）
    # 9 → 11：第 148 轮 C3 开启规划器，注入 `plan_tasks` / `update_task`（todo 外置落图状态）
    # 11 → 12：第 181 轮 批 B 技能渐进披露，注入 `load_skill`（技能目录每轮进 system prompt）
    # 12 → 14：第 205 轮 资料库只读工具 `list_candidates` / `list_products`
    #          （跨 Agent 共用，见 `modules/library/`）
    # 14 → 18：第 218 轮 P1 资料库扩到 6 库（+ `list_assets` / `list_monitors` /
    #          `list_faqs` / `list_platform_rules`，同样是跨 Agent 共用）
    # 18 → 19：第 243 轮（第 240 轮方案 A′）`build_shop_tools()` 新增只读 `list_shops`
    #          —— 修前「读有哪些店铺」**没有工具**，只能拿 switch_shop（会真切店）
    #          或 get_my_subscription（套餐上限）凑数。
    names = [t.name for t in agent.tools]
    assert len(names) == 19
    # 只断言数字会在内容漂移时静默退化成假绿：必须锁住「多出来的恰是这两个」
    planner_names = ["plan_tasks", "update_task"]
    assert sorted(set(names) & set(planner_names)) == planner_names
    assert names.count("plan_tasks") == 1 and names.count("update_task") == 1
    assert names.count("load_skill") == 1
    # ★ 第 205 轮：共用工具**各只有一份**（秘书与选品分析师各拿一份实例，
    #   但实现是同一个）—— 秘书这一侧不许出现重复条目。
    assert names.count("list_candidates") == 1 and names.count("list_products") == 1
    # ★ 第 218 轮：新增的 4 个资料库工具同样**各只有一份**。
    assert (
        names.count("list_assets") == 1
        and names.count("list_monitors") == 1
        and names.count("list_faqs") == 1
        and names.count("list_platform_rules") == 1
    )
    # ★ 第 243 轮：**读**（list_shops）与**写/切**（switch_shop）必须是两个工具，
    #   且各只有一份 —— 少了 list_shops，「问有几家店」就只能靠会切店的工具回答。
    assert names.count("list_shops") == 1 and names.count("switch_shop") == 1
    assert agent.enable_planning is True
    assert agent.system_prompt == SECRETARY_SYSTEM_PROMPT


def test_bind_tools_routes_to_tool_node():
    """
    核心机制验证：修好 bind_tools 后，LLM 产出 tool_calls 会路由到 tool_node。

    用 fake LLM 模拟「第一次返回 tool_calls、第二次返回纯文本」，
    验证 _should_continue 的判断逻辑与 BaseAgent 的工具循环不退化。
    """
    agent = BaseAgent(
        agent_name="test",
        system_prompt="sys",
        tools=listing_tools,
        llm=MagicMock(),
    )

    # 有 tool_calls → 应继续走 tool_node
    state_with_call = {
        "messages": [
            HumanMessage(content="帮我润色下标题"),
            AIMessage(
                content="",
                tool_calls=[{"name": "optimize_listing_title",
                             "args": {"current_title": "old title"},
                             "id": "1"}],
            ),
        ]
    }
    assert agent._should_continue(state_with_call) == "tool_node"

    # 无 tool_calls → 应 respond
    state_plain = {
        "messages": [
            HumanMessage(content="你好"),
            AIMessage(content="你好，有什么可以帮你？"),
        ]
    }
    assert agent._should_continue(state_plain) == "respond"


def test_respond_node_handles_tool_message():
    """修复后：_respond_node 遇到 ToolMessage 不再 NameError"""
    import asyncio

    agent = BaseAgent(
        agent_name="test",
        system_prompt="sys",
        tools=listing_tools,
        llm=MagicMock(),
    )
    state = {
        "messages": [
            HumanMessage(content="hi"),
            ToolMessage(content="优化结果 JSON", tool_call_id="1"),
        ]
    }
    result = asyncio.run(agent._respond_node(state))
    assert result["structured_response"]["status"] == "completed"
    assert "优化结果 JSON" in result["structured_response"]["message"]


def test_max_iterations_strips_orphan_tool_calls():
    """回归测试：max_iterations 触发的 AIMessage 不应留下 orphan tool_calls

    否则下次 invoke 时 checkpointer 恢复历史会因「tool_calls 必须有 ToolMessage
    配对」被 LLM API 400 拒绝（截图报错复现）。
    """
    import asyncio
    from unittest.mock import patch

    agent = BaseAgent(
        agent_name="test",
        system_prompt="sys",
        tools=listing_tools,
        llm=MagicMock(),
        max_iterations=2,
    )

    # 已达到 max_iterations（state 里 2 条 AIMessage）
    state = {
        "messages": [
            HumanMessage(content="q"),
            AIMessage(content="r1", tool_calls=[]),
            AIMessage(content="r2", tool_calls=[]),
        ]
    }

    # 模拟 LLM 返回带 tool_calls 的 AIMessage（orphan 场景）
    orphan_ai = AIMessage(
        content="try tool",
        tool_calls=[{"name": "x", "args": {}, "id": "1"}],
    )
    with patch.object(agent, "_llm_with_tools") as mock_lwt:
        mock_lwt.return_value.ainvoke = AsyncMock(return_value=orphan_ai)
        result = asyncio.run(agent._llm_call_node(state))

    # 关键断言：tool_calls 必须被清空
    out_ai = result["messages"][0]
    assert out_ai.tool_calls == [], f"orphan tool_calls 未清理: {out_ai.tool_calls}"
    # content 必须保留（用户能看到响应）
    assert out_ai.content == "try tool"


def test_listing_agent_deep_router_lazy():
    """深层分层路由：ListingGeneratorAgent 懒加载工具化路由层，LLM 可用时构建成功"""
    from modules.listing_generator.agent_listing import ListingGeneratorAgent

    agent = ListingGeneratorAgent()
    # 未触发 invoke 前 router 为空（懒加载，避免循环导入）
    assert agent._router is None
    # 触发懒加载后应构建出 BaseAgent 路由层：8 个业务工具
    # + 1 个恒带的技能按需加载工具（第 181 轮批 B）⇒ 共 9
    router = agent._get_router()
    if router is not None:
        assert len(router.tools) == 9
        names = {t.name for t in router.tools}
        assert "generate_complete_listing" in names
        assert "optimize_listing_title" in names
        assert "analyze_listing_seo" in names
        assert "generate_ab_test_variants" in names


def test_product_research_agent_deep_router_lazy():
    """深层分层路由：ProductResearchAgent 懒加载工具化路由层，10 业务工具 + 1 技能加载"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    agent = ProductResearchAgent()
    assert agent._router is None
    router = agent._get_router()
    if router is not None:
        # 14 个业务工具 + 1 个恒带的技能按需加载工具（第 181 轮批 B）⇒ 共 15
        # ★ 10 → 14（第 218 轮 P1）：资料库从 2 库扩到 6 库。
        # ★ 7 → 10（第 205 轮批 B）：候选生命周期三条 `get_candidate` /
        #   `review_candidate` / `approve_candidate`（解释见上一条用例）。
        assert len(router.tools) == 16
        names = {t.name for t in router.tools}
        assert names == {
            "analyze_blue_ocean",
            "analyze_profit",
            "analyze_pain_points",
            "compare_competitor_listings",
            "save_candidate",
            "get_candidate",
            "review_candidate",
            "approve_candidate",
            "query_market_insight",
            "list_candidates",
            "list_products",
            "list_assets",
            "list_monitors",
            "list_faqs",
            "list_platform_rules",
            "load_skill",
        }


def test_iterations_count_only_current_turn():
    """回归测试：迭代计数必须只数「本轮」，不能被跨轮历史累积误判。

    背景（线上 bug）：checkpointer 恢复的 messages 是跨轮完整历史。旧实现用
    「AIMessage 总数」判断是否达 max_iterations，多轮会话累积几条 AIMessage 后
    每轮都被判超限——`_llm_call_node` 强制清空 tool_calls、`_should_continue`
    直接 respond——LLM 再也无法调用任何工具，前端一直收到「处理完成」、actions 为空。
    """
    # 构造 4 轮完整历史（每轮 1 条 AIMessage，共 4 条）
    history = []
    for r in range(4):
        history += [
            HumanMessage(content=f"q{r}"),
            AIMessage(content=f"a{r}"),
        ]
    # 本轮刚输入，尚未产生任何 AIMessage
    history.append(HumanMessage(content="本轮"))

    assert BaseAgent._iterations_in_current_turn(history) == 0, "跨轮历史被误计入本轮迭代"

    # 本轮产生 1 次 AI 输出后 → 应为 1
    history.append(AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "n1"}]))
    assert BaseAgent._iterations_in_current_turn(history) == 1

    # 再累计 1 次 → 应为 2（此时跨轮历史已有 5 条 AIMessage，但本轮仍是 2）
    history.append(ToolMessage(content="{}", tool_call_id="n1"))
    history.append(AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "n2"}]))
    assert BaseAgent._iterations_in_current_turn(history) == 2


def test_sanitize_tool_call_pairing_removes_orphans():
    """回归测试：读时清洗 orphan tool_calls / 孤立 ToolMessage。

    线上 400：checkpointer 历史里存在「AIMessage 带 tool_calls 但无配对 ToolMessage」
    的孤儿消息时，DashScope 会拒绝整个会话（
    `An assistant message with "tool_calls" must be followed by tool messages...`），
    导致前端降级到 mock 兜底、用户看到「没听懂」。
    """
    msgs = [
        HumanMessage(content="hi"),
        # 配对正常
        AIMessage(content="", tool_calls=[{"name": "ok", "args": {}, "id": "c1"}]),
        ToolMessage(content="{}", tool_call_id="c1"),
        # orphan：有 tool_calls 但无 ToolMessage 响应
        AIMessage(content="keep me", tool_calls=[{"name": "bad", "args": {}, "id": "c2"}]),
        # 孤立：ToolMessage 没有对应的 AIMessage 声明
        ToolMessage(content="{}", tool_call_id="c9"),
    ]
    cleaned, dropped = BaseAgent._sanitize_tool_call_pairing(msgs)

    assert dropped == 2, f"应清洗 2 条（1 orphan tool_calls + 1 孤立 ToolMessage），实为 {dropped}"

    # 配对正常的一对必须保留
    pairs = [(m.tool_call_id, m) for m in cleaned if isinstance(m, ToolMessage)]
    assert len(pairs) == 1 and pairs[0][0] == "c1"

    # orphan AIMessage 的 tool_calls 被清空，但正文保留
    ai_with_text = [m for m in cleaned if isinstance(m, AIMessage) and m.content == "keep me"]
    assert len(ai_with_text) == 1
    assert ai_with_text[0].tool_calls == []

    # 清洗后的序列里不存在「声明了却没有响应」的 tool_call_id
    declared = {tc.get("id") for m in cleaned if isinstance(m, AIMessage) for tc in (m.tool_calls or [])}
    responded = {m.tool_call_id for m in cleaned if isinstance(m, ToolMessage)}
    assert declared == responded, f"仍有未配对: declared={declared} responded={responded}"

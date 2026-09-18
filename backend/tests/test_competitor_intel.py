"""
/api/v1/competitor 端点测试（13 个非流式端点 + 1 个 SSE）

为什么这个文件重要
------------------
竞品情报模块后端**功能最全**（14 个路由、8 项分析能力），但此前**零端点测试**。
更值得注意的现状（已实测核对）：

* 前端分析结果是**本地 mock 生成**的 —— `src/mock/competitorIntel.ts`（484 行），
  被 `composables/useChatOrchestrator.ts` / `stores/competitorPool.ts` 直接 import；
* 而 `src/api/competitorIntelligence.ts` 里封装这 13 个端点的函数
  **没有任何组件 / store 引用**（`grep -rn competitorIntelligence src` 除自身外为空）。

也就是说后端这 13 个端点当前**零前端消费者**。端点测试的价值就在于此：
在联调之前把契约（信封、字段名、边界校验、快捷口是否与 POST 同构）钉死。

本文件钉住 2026-09-12 修复的两个真 bug
-------------------------------------
**Bug 1｜`/analyze` 的「单品监控」失效（ASIN 被丢弃）**

    `_monitor_competitor` 内联写 `self._extract_asin(query) or context.get("asin")
    if context else None`。Python 里 `or` 优先级高于条件表达式，实际解析为
    `(extract or context.get("asin")) if context else None` —— `context is None`
    时**整条短路成 None**。《竞品监控》只是「提取到了也白提取」。
    而 `/analyze`（通用入口）恰恰不传 context，于是路由文档承诺的
    「"监控 B08ABC1234" → 单品监控」实际返回的是**全量仪表盘**
    （`data.type == "monitor_dashboard"`），用户永远拿不到单品深度分析。

    注意同一文件另外三处（pricing / reviews / buy_box）**括号是对的**，
    只有 monitor 漏了 —— 所以「看起来一样的代码」不等于「行为一样」。

**Bug 2｜ASIN 大小写不一致（静默 0 结果）**

    竞品库 `_competitor_db` 以**大写** ASIN 为键，`_extract_asin` 提取时
    `.upper()`，`GET /reviews/{asin}` 也主动 `.upper()`；但**POST body / context
    传入的 ASIN 原样使用**。于是同一个 ASIN：小写走 GET 正常，走 POST 得到
    「未找到竞品 ASIN: b08abc1234」+「成功获取 0 个竞品的监控数据」——
    ASIN 是从亚马逊 URL 里复制来的，大小写完全取决于用户怎么粘。

**修法**：新增 `_resolve_asin` / `_resolve_asins`，把「query → context → 大写」
收敛为唯一入口，6 处解析点（monitor / track_batch / pricing / reviews /
buy_box / compare）全部改为调用它。Bug 1 与 Bug 2 是同一个根因的两个症状。

本文件同时标注了 4 个**已知问题**（用 `xfail` 或注释形式），均**未修改代码**，
见文件末尾「已知问题」小节。

不测什么
--------
* 不打真实 LLM：模块级 autouse 夹具 `no_llm` 关掉 `ENABLE_LLM`。
  实测未打桩时 `/monitor` 3.5s、`/compare` 9.9s（真实 DashScope 调用），
  不打桩会让整个测试套件既慢又花钱。
* 不测数值：市场份额、价格波动带 `random` 噪声，每次调用都不同，
  只断言结构、取值范围与不变量（如份额归一化到 100）。
"""

import inspect
import re

import pytest

KNOWN_ASIN = "B08ABC1234"          # 见 agent_competitor._initialize_mock_data
KNOWN_ASIN_2 = "B08DEF5678"
UNKNOWN_ASIN = "B0ZZZZZZZZ"        # 10 位且符合 [A-Z0-9]{10}，但不在竞品库

# ====== 夹具 ======


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """
    关闭竞品 Agent 的 LLM 增强（autouse：本模块任何用例都不许打真实 LLM）。

    `_llm_insights` 在 `ENABLE_LLM` 为假时直接返回 None，各能力降级到规则引擎，
    输出变为确定性的；不打桩则 monitor/compare 每次真实调用 3.5~10 秒。
    """
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent

    monkeypatch.setattr(CompetitorIntelligenceAgent, "ENABLE_LLM", False)


# ====== 一、路由清单与快捷接口不互相遮蔽 ======

EXPECTED_ROUTES = {
    ("POST", "/api/v1/competitor/monitor"),
    ("GET", "/api/v1/competitor/monitor/dashboard"),
    ("POST", "/api/v1/competitor/track/batch"),
    ("POST", "/api/v1/competitor/market-share"),
    ("GET", "/api/v1/competitor/market-share/{category}"),
    ("POST", "/api/v1/competitor/pricing/analyze"),
    ("POST", "/api/v1/competitor/reviews/analyze"),
    ("GET", "/api/v1/competitor/reviews/{asin}"),
    ("POST", "/api/v1/competitor/intruders/detect"),
    ("GET", "/api/v1/competitor/intruders/{category}"),
    ("POST", "/api/v1/competitor/buy-box/analyze"),
    ("POST", "/api/v1/competitor/compare"),
    ("POST", "/api/v1/competitor/analyze"),
    ("POST", "/api/v1/competitor/chat/stream"),
}


def test_route_inventory():
    """13 个非流式端点 + 1 个 SSE 端点必须全部注册（少一个前端就静默 404）"""
    from main import app

    registered = set()
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v1/competitor"):
            for m in getattr(r, "methods", None) or []:
                registered.add((m, path))

    missing = EXPECTED_ROUTES - registered
    assert not missing, f"缺失路由: {sorted(missing)}"


async def test_quick_get_does_not_shadow_post_sibling(client, auth_off):
    """
    快捷 GET 与 POST 同前缀共存，互不遮蔽。

    背景：`stores` 模块曾因 `GET /{store_id}` 注册在 `GET /fee-templates` 之前，
    单段静态路径被当成路径参数 → 恒 404。这里 `GET /market-share/{category}`
    与 `POST /market-share` 同前缀，靠 **HTTP 方法**区分而非注册顺序，
    因此必须验证两者都活着（防止未来有人把 GET 改成无方法约束的 catch-all）。
    """
    post = await client.post("/api/v1/competitor/market-share", json={"category": "Headphones"})
    get = await client.get("/api/v1/competitor/market-share/Headphones")
    assert post.status_code == 200, post.text
    assert get.status_code == 200, get.text
    assert post.json()["data"]["type"] == get.json()["data"]["type"] == "market_share"


# ====== 二、竞品监控 ======


async def test_monitor_no_asin_returns_dashboard(client, auth_off):
    """不传 ASIN → 全量监控仪表盘"""
    r = await client.post("/api/v1/competitor/monitor", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["type"] == "monitor_dashboard"
    assert data["total_competitors"] > 0
    comp = data["competitors"][0]
    for key in ("asin", "brand", "current_price", "price_change_7d", "current_bsr", "alerts"):
        assert key in comp, f"监控条目缺字段 {key}"
    # 未启用 LLM 时摘要是结构化 dict（启用后会被 LLM 文本替换）
    assert isinstance(data["summary"], dict)
    assert "key_events" in data["summary"]


async def test_monitor_dashboard_get_matches_post(client, auth_off):
    """GET /monitor/dashboard 是无参快捷口，结构必须与 POST /monitor 空参一致"""
    post = (await client.post("/api/v1/competitor/monitor", json={})).json()["data"]
    get = (await client.get("/api/v1/competitor/monitor/dashboard")).json()["data"]
    assert get["type"] == post["type"] == "monitor_dashboard"
    assert get["total_competitors"] == post["total_competitors"]


async def test_monitor_single_asin_deep_analysis(client, auth_off):
    """传已知 ASIN → 单品深度分析（价格/排名趋势 + 三项分析）"""
    r = await client.post("/api/v1/competitor/monitor", json={"asin": KNOWN_ASIN})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "single_monitor"
    assert data["product"]["asin"] == KNOWN_ASIN
    assert len(data["price_trend"]) > 0
    assert len(data["ranking_trend"]) > 0
    assert set(data["analysis"]) == {"price_stability", "ranking_momentum", "stock_pattern"}


async def test_monitor_lowercase_asin_is_accepted(client, auth_off):
    """Bug 2 回归：ASIN 小写（从 URL 复制）不得被判「未找到」"""
    r = await client.post("/api/v1/competitor/monitor", json={"asin": KNOWN_ASIN.lower()})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "single_monitor", f"小写 ASIN 被当成未找到: {data}"
    assert data["product"]["asin"] == KNOWN_ASIN


async def test_monitor_days_boundary(client, auth_off):
    """days 约束 7~90，越界由 Pydantic 拦成 422"""
    assert (await client.post("/api/v1/competitor/monitor", json={"days": 3})).status_code == 422
    assert (await client.post("/api/v1/competitor/monitor", json={"days": 120})).status_code == 422
    assert (await client.post("/api/v1/competitor/monitor", json={"days": 7})).status_code == 200
    assert (await client.post("/api/v1/competitor/monitor", json={"days": 90})).status_code == 200


async def test_monitor_summary_replaced_by_llm(client, auth_off, monkeypatch):
    """LLM 可用时，规则摘要被 LLM 文本替换（验证集成接线，不打真实模型）"""
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent

    async def fake_insights(self, context, max_tokens=800):
        return "LLM 综合结论：SoundMax Pro 正在降价抢量"

    monkeypatch.setattr(CompetitorIntelligenceAgent, "_llm_insights", fake_insights)
    data = (await client.post("/api/v1/competitor/monitor", json={})).json()["data"]
    assert data["summary"] == "LLM 综合结论：SoundMax Pro 正在降价抢量"


# ====== 三、ASIN 批量追踪 ======


async def test_track_batch_known_asins(client, auth_off):
    r = await client.post(
        "/api/v1/competitor/track/batch", json={"asins": [KNOWN_ASIN, KNOWN_ASIN_2]}
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "batch_track"
    assert data["tracked_count"] == 2
    # 得分降序
    scores = [c["score"] for c in data["competitors"]]
    assert scores == sorted(scores, reverse=True)
    assert set(data["comparison_matrix"]) >= {"price", "rating", "reviews", "bsr", "score"}


async def test_track_batch_lowercase_asins(client, auth_off):
    """Bug 2 回归：小写 ASIN 列表也要认得"""
    data = (
        await client.post("/api/v1/competitor/track/batch", json={"asins": [KNOWN_ASIN.lower()]})
    ).json()["data"]
    assert data["tracked_count"] == 1
    assert data["competitors"][0]["asin"] == KNOWN_ASIN


async def test_track_batch_unknown_asin_is_skipped_not_faked(client, auth_off):
    """未知 ASIN 只被跳过，不得伪造成数据（空状态优于虚构默认）"""
    data = (
        await client.post(
            "/api/v1/competitor/track/batch", json={"asins": [KNOWN_ASIN, UNKNOWN_ASIN]}
        )
    ).json()["data"]
    assert data["tracked_count"] == 1
    assert all(c["asin"] == KNOWN_ASIN for c in data["competitors"])


@pytest.mark.parametrize("asins", [[], ["A" * 10] * 21])
async def test_track_batch_length_limits(client, auth_off, asins):
    """asins 长度约束 1~20"""
    r = await client.post("/api/v1/competitor/track/batch", json={"asins": asins})
    assert r.status_code == 422


# ====== 四、市场份额分析 ======


async def test_market_share_post(client, auth_off):
    r = await client.post("/api/v1/competitor/market-share", json={"category": "Headphones"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "market_share"
    assert data["category"] == "Headphones"
    assert data["total_market_estimate"] > 0
    assert data["competitors"]
    item = data["competitors"][0]
    assert item["trend"] in ("rising", "stable", "declining")
    # 份额已归一化到 100
    assert abs(sum(c["estimated_market_share"] for c in data["competitors"]) - 100) < 1
    # 降序排列
    shares = [c["estimated_market_share"] for c in data["competitors"]]
    assert shares == sorted(shares, reverse=True)
    assert set(data["concentration_ratio"]) == {"CR4", "HHI", "market_type"}
    assert data["insights"]


async def test_market_share_get_shortcut(client, auth_off):
    """快捷口按类目查询，与 POST 结构一致"""
    r = await client.get("/api/v1/competitor/market-share/Headphones")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["type"] == "market_share"


async def test_market_share_missing_category_422(client, auth_off):
    assert (await client.post("/api/v1/competitor/market-share", json={})).status_code == 422


# ====== 五、定价策略分析 ======


async def test_pricing_analyze_all(client, auth_off):
    """不传 ASIN → 分析全部竞品"""
    r = await client.post("/api/v1/competitor/pricing/analyze", json={})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "pricing_strategy"
    assert data["analyzed_count"] == 5
    s = data["strategies"][0]
    assert s["strategy_type"] in ("premium", "economy", "competitive", "dynamic")
    assert s["promo_frequency"] in ("high", "medium", "low")
    assert s["recommendations"]
    assert "positions" in data["market_positioning_map"]


async def test_pricing_analyze_lowercase_asin(client, auth_off):
    """Bug 2 回归：小写 ASIN 也要命中（此前 analyzed_count 静默为 0）"""
    data = (
        await client.post("/api/v1/competitor/pricing/analyze", json={"asin": KNOWN_ASIN.lower()})
    ).json()["data"]
    assert data["analyzed_count"] == 1
    assert data["strategies"][0]["strategy_type"] in ("premium", "economy", "competitive", "dynamic")


# ====== 六、竞品评论深度分析 ======


async def test_reviews_analyze_by_body(client, auth_off):
    r = await client.post("/api/v1/competitor/reviews/analyze", json={"asin": KNOWN_ASIN})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "review_analysis"
    assert data["analyzed_products"] == 1
    a = data["analyses"][0]
    assert a["asin"] == KNOWN_ASIN
    assert set(a["swot"]) == {"strengths", "weaknesses", "opportunities", "threats"}
    assert a["insights"] and a["actionable_intelligence"]


async def test_reviews_analyze_lowercase_asin(client, auth_off):
    """Bug 2 回归：POST body 小写 ASIN 此前静默返回 0 个产品"""
    data = (
        await client.post("/api/v1/competitor/reviews/analyze", json={"asin": KNOWN_ASIN.lower()})
    ).json()["data"]
    assert data["analyzed_products"] == 1


async def test_reviews_get_shortcut_uppercases(client, auth_off):
    """快捷口自带 .upper()（这条一直是好的，钉住它别退化）"""
    r = await client.get(f"/api/v1/competitor/reviews/{KNOWN_ASIN.lower()}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["analyses"][0]["asin"] == KNOWN_ASIN


async def test_reviews_validation(client, auth_off):
    """asin 必填；sample_size 约束 10~1000"""
    assert (await client.post("/api/v1/competitor/reviews/analyze", json={})).status_code == 422
    for size in (5, 1001):
        r = await client.post(
            "/api/v1/competitor/reviews/analyze",
            json={"asin": KNOWN_ASIN, "sample_size": size},
        )
        assert r.status_code == 422, f"sample_size={size} 应被拒"


# ====== 七、入侵者检测 ======


async def test_intruders_detect(client, auth_off):
    r = await client.post("/api/v1/competitor/intruders/detect", json={"category": "Headphones"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "intruder_detection"
    assert data["new_competitors"]
    assert set(data["threat_summary"]) == {"high_threat", "medium_threat", "low_threat"}
    # 威胁分级与应对策略一一对应
    assert len(data["response_strategies"]) == len(data["new_competitors"])
    assert all(s["priority"] in ("P0", "P1", "P2") for s in data["response_strategies"])


async def test_intruders_get_shortcut(client, auth_off):
    r = await client.get("/api/v1/competitor/intruders/Headphones")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["type"] == "intruder_detection"


async def test_intruders_lookback_days_boundary(client, auth_off):
    assert (
        await client.post(
            "/api/v1/competitor/intruders/detect", json={"category": "x", "lookback_days": 3}
        )
    ).status_code == 422


# ====== 八、Buy Box 竞争分析 ======


async def test_buy_box_analyze(client, auth_off):
    r = await client.post("/api/v1/competitor/buy-box/analyze", json={})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "buy_box_analysis"
    assert data["analyzed_count"] == 5
    assert data["best_practices"]
    bb = data["analyses"][0]["buy_box_analysis"]
    for key in ("current_winner", "winning_price", "all_sellers", "buy_box_percentage",
                "price_to_win", "featured_offer_reason"):
        assert key in bb, f"Buy Box 缺字段 {key}"
    assert bb["all_sellers"] and all("seller_name" in s for s in bb["all_sellers"])
    score = data["analyses"][0]["competitiveness_score"]
    assert 0 <= score <= 100


async def test_buy_box_lowercase_asin(client, auth_off):
    """Bug 2 回归"""
    data = (
        await client.post("/api/v1/competitor/buy-box/analyze", json={"asin": KNOWN_ASIN.lower()})
    ).json()["data"]
    assert data["analyzed_count"] == 1


# ====== 九、多维度竞品对比 ======


async def test_compare_two_asins(client, auth_off):
    r = await client.post(
        "/api/v1/competitor/compare",
        json={"asins": [KNOWN_ASIN, KNOWN_ASIN_2]},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "competitor_comparison"
    assert data["compared_count"] == 2
    comparison = data["comparison"]
    for key in ("price_comparison", "rating_comparison", "review_count_comparison",
                "bsr_comparison", "value_score", "overall_ranking",
                "differentiation_analysis", "recommendations"):
        assert key in comparison, f"对比结果缺维度 {key}"
    assert comparison["price_comparison"]["best"]  # 价格最优者非空


async def test_compare_single_asin_rejected_by_schema_not_router(client, auth_off):
    """
    单个 ASIN → **422（Pydantic）**，不是 400。

    `CompetitorCompareRequest.asins` 已声明 `min_length=2`，请求校验阶段就退回 422，
    因此路由里的 `if len(request.asins) < 2: raise HTTPException(400, "至少需要2个ASIN进行对比")`
    是**不可达分支**（死代码）。钉住 422 这个真实契约，避免有人误以为 400 会触发。
    若将来要给用户中文友好提示，要么放开 schema 的 min_length，要么在前端拦。
    """
    r = await client.post("/api/v1/competitor/compare", json={"asins": [KNOWN_ASIN]})
    assert r.status_code == 422, r.text


async def test_compare_too_many_asins(client, auth_off):
    r = await client.post("/api/v1/competitor/compare", json={"asins": ["A" * 10] * 11})
    assert r.status_code == 422


# ====== 十、通用入口（自然语言） ======


@pytest.mark.parametrize(
    "query,expected_type,expected_intent",
    [
        ("耳机市场份额", "market_share", "market_share"),
        ("新进入的竞争者", "intruder_detection", "intruder"),
        ("分析评论", "review_analysis", "reviews"),
        ("定价策略", "pricing_strategy", "pricing"),
        ("Buy Box", "buy_box_analysis", "buy_box"),
        (f"对比 {KNOWN_ASIN} {KNOWN_ASIN_2}", "competitor_comparison", "compare"),
    ],
)
async def test_analyze_intent_routing(client, auth_off, query, expected_type, expected_intent):
    """自然语言入口的意图路由（真实意图落在 data.intent）"""
    r = await client.post("/api/v1/competitor/analyze", params={"query": query}, json={})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == expected_type
    assert data["intent"] == expected_intent


async def test_analyze_monitor_query_returns_single_monitor(client, auth_off):
    """
    Bug 1 回归（本文件最重要的一条）。

    路由文档承诺「"监控 B08ABC1234" → 单品监控」。修复前 `_monitor_competitor`
    因 `or`/条件表达式优先级把已提取到的 ASIN 丢弃（`/analyze` 不传 context），
    实际返回全量仪表盘 `monitor_dashboard`。
    """
    r = await client.post(
        "/api/v1/competitor/analyze", params={"query": f"监控 {KNOWN_ASIN}"}, json={}
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["intent"] == "monitor"
    assert data["type"] == "single_monitor", "ASIN 又被丢了：单品监控退化成全量仪表盘"
    assert data["product"]["asin"] == KNOWN_ASIN


async def test_analyze_query_required(client, auth_off):
    """query 是必填查询参数，缺了 422（不能静默返回空结果）"""
    assert (await client.post("/api/v1/competitor/analyze")).status_code == 422


# ====== 十一、鉴权闸门 ======


def test_routes_under_business_auth_gate():
    """
    竞品路由必须挂在 `BUSINESS_AUTH` 下（源码断言）。

    不能用 `auth_on` 夹具断言 401 —— `BUSINESS_AUTH` 是 `import main` 时求值一次的
    启动期快照，运行期改 `config.auth_required` 对它无效。

    ★ 第 106 轮更新：该常量已改为**无条件挂载**（请求期读 config）⇒
      `auth_on` 现在能断言 401 了；此处保留源码断言，只为防「新增模块漏挂闸门」。
    """
    import main

    flat = re.sub(r"\s+", " ", inspect.getsource(main))
    assert "competitor_intel_router, prefix=\"/api/v1\", dependencies=BUSINESS_AUTH" in flat


# ====== 已知问题（未改代码，标注出来供决策） ======
#
# 1) 未找到 ASIN 时信封自相矛盾：`/monitor` 未知 ASIN 返回
#    200 + `success: true` + `data.error` + message「成功获取 0 个竞品的监控数据」；
#    `/reviews/analyze` 未知 ASIN 则静默返回 `analyzed_products: 0`。
#    `stores` 模块对同类情形返回 404，两处语义不一致 → 见 xfail 用例。
# 2) `/compare` 的 400 分支不可达（见 test_compare_single_asin_rejected_by_schema_not_router）。
# 3) 顶层 `intent` 字段恒为 ""（真实意图只在 `data.intent`），
#    `CompetitorAnalysisResponse.intent` 从未被填充 → 见 xfail 用例。
# 4) `_classify_intent` 永不返回 "general"，导致
#    a. `handlers.get(intent, self._general_analysis)` 的兜底分支不可达；
#    b. `stream_chat` 里 `if intent != "general"` 恒为真 → **LLM 流式分支是死代码**，
#       `/chat/stream` 实际只把结构化结果包了一层 SSE（其他 Agent 是真流式）。
#    → 见 test_classify_intent_never_returns_general。


@pytest.mark.xfail(reason="已知问题：未知 ASIN 仍返回 success=true + data.error（信封自相矛盾）")
async def test_monitor_unknown_asin_should_not_claim_success(client, auth_off):
    """期望：未知 ASIN 不该谎报成功（应 404，或至少 success=false）"""
    body = (await client.post("/api/v1/competitor/monitor", json={"asin": UNKNOWN_ASIN})).json()
    assert body["success"] is False or "error" not in body.get("data", {})


@pytest.mark.xfail(reason="已知问题：顶层 intent 字段从未被填充，恒为空串")
async def test_top_level_intent_is_populated(client, auth_off):
    """期望：`CompetitorAnalysisResponse.intent` 应带出真实意图，而不是恒 """""
    body = (
        await client.post("/api/v1/competitor/analyze", params={"query": "耳机市场份额"}, json={})
    ).json()
    assert body["intent"] == "market_share"


def test_classify_intent_never_returns_general():
    """
    钉住「无 general 意图」这个事实（它让 stream_chat 的 LLM 分支成为死代码）。

    这不是期望行为的断言，而是防止有人误以为 `/chat/stream` 会走 LLM 流式。
    """
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent

    agent = CompetitorIntelligenceAgent()
    for q in ["你好", "随便问问天气", "今天有什么新闻", "帮我看看"]:
        assert agent._classify_intent(q) != "general"

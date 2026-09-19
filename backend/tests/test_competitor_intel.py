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

第 142 轮（2026-09-18）**重基**：本文件的期望值全部来自实测
--------------------------------------------
背景：批 A（A1 去重 / A2 接数据源 / A3 注册真能力）把竞品模块的**取数点**从
「`random` 现编 5 个耳机竞品」换成了 `amazon_sp.get_data_source()`。原测试里
写死的 `B08ABC1234` / `B08DEF5678` 正是被删掉的那批假竞品，与真实集合**零交集**，
于是 30+ 条断言整体失效。

重基原则（本仓铁律）：**期望值不手写**。先用探针把 14 个端点按测试同等条件
（`no_llm` + `X-Shop-ID`）真打一遍，再拿真实 payload 反推断言 ——
留底在 `.workbuddy/probes/r142_ci_truth/`（`dump.txt` / `brief.txt` / `days.txt`）。

地面真相（`MockAmazonDataSource.fetch_competitors("store_test", 30d)`）：

    6 个 ASIN × 15 个快照（每 2 天一点）= 90 行

    B08N5KWB9H  TP-Link        Kasa Smart Plug        $10.83  BSR 678
    B08XLYPQJZ  Amazon Basics  Smart Plug             $11.89  BSR 226
    B09VKR9Z3L  Anker          332 USB-C Hub          $34.12  BSR 2198
    B08NL7RJ8W  Satechi        USB-C Multiport        $44.78  BSR 12227
    B07Q9MJKBV  TaoTronics     LED Desk Lamp          $38.80  BSR 1132（无 Buy Box）
    B08CWTG95V  JBL            Clip 4                 $34.80  BSR 1622

**每条请求都要带 `X-Shop-ID`**（第 142 轮 A2-3 起本模块 router 挂了 strict 守卫）：
`get_current_shop_id` 对**写方法**缺头直接 400（空值守卫，与"你是谁"无关）；
GET 快捷口缺头不报错，但 `_ensure_source` 拿不到 store_id ⇒ 返回**显式空状态**
（`data_status="no_data"`、`success=false`）。两种都钉在下文。

本文件历史上钉住的真 bug（仍然有效，别退化）
------------------------------------------
**Bug 1｜`/analyze` 的「单品监控」失效（ASIN 被丢弃）**

    `_monitor_competitor` 内联写 `self._extract_asin(query) or context.get("asin")
    if context else None`。Python 里 `or` 优先级高于条件表达式，实际解析为
    `(extract or context.get("asin")) if context else None` —— `context is None`
    时**整条短路成 None**。《竞品监控》只是「提取到了也白提取」。
    而 `/analyze`（通用入口）恰恰不传 context，于是路由文档承诺的
    「"监控 B08N5KWB9H" → 单品监控」实际返回的是**全量仪表盘**。

    注意同一文件另外三处（pricing / reviews / buy_box）**括号是对的**，
    只有 monitor 漏了 —— 所以「看起来一样的代码」不等于「行为一样」。

**Bug 2｜ASIN 大小写不一致（静默 0 结果）**

    竞品库以**大写** ASIN 为键，`_extract_asin` 提取时 `.upper()`，
    `GET /reviews/{asin}` 也主动 `.upper()`；但**POST body / context 传入的 ASIN
    原样使用**。于是同一个 ASIN：小写走 GET 正常，走 POST 得到
    「未找到竞品 ASIN」+「成功获取 0 个竞品的监控数据」——
    ASIN 是从亚马逊 URL 里复制来的，大小写完全取决于用户怎么粘。

**修法**：新增 `_resolve_asin` / `_resolve_asins`，把「query → context → 大写」
收敛为唯一入口，6 处解析点全部改为调用它。Bug 1 与 Bug 2 是同一个根因的两个症状。

不测什么
--------
* 不打真实 LLM：模块级 autouse 夹具 `no_llm` 关掉 `ENABLE_LLM`。
  不打桩时 `/monitor` 3.5s、`/compare` 9.9s（真实 DashScope 调用），
  不打桩会让整个测试套件既慢又花钱。
* 不测具体数值：市场份额/定价只断言结构、取值范围与不变量（如份额归一化到 100）。
  唯一写死的数值是 `COMPETITOR_COUNT`，它来自上面的实测表。
"""

import inspect
import re

import pytest

# ====== 常量（全部来自实测，见文件头「地面真相」）======

SHOP = "store_test"
HEADERS = {"X-Shop-ID": SHOP}      # 写方法缺它 ⇒ 400；GET 缺它 ⇒ 显式空状态

KNOWN_ASIN = "B08N5KWB9H"          # TP-Link Kasa Smart Plug，$10.83 / ⭐4.5
KNOWN_ASIN_2 = "B08XLYPQJZ"        # Amazon Basics，$11.89 / ⭐4.3（BSR 最低 = 226）
KNOWN_ASIN_NO_BUYBOX = "B07Q9MJKBV"  # TaoTronics：has_buybox=false，用于钉「不编造赢家」
KNOWN_ASINS = {
    "B07Q9MJKBV", "B08CWTG95V", "B08N5KWB9H",
    "B08NL7RJ8W", "B08XLYPQJZ", "B09VKR9Z3L",
}
UNKNOWN_ASIN = "B0ZZZZZZZZ"        # 10 位且符合 [A-Z0-9]{10}，但不在竞品库

COMPETITOR_COUNT = 6               # = len(KNOWN_ASINS)，数据源换数据时须同步更新
SNAPSHOTS_PER_ASIN_30D = 15        # 每 2 天一个点 → 30 天 15 个

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


def _asins_of(payload: dict) -> set:
    """从仪表盘 payload 抽出 ASIN 集合"""
    return {c["asin"] for c in payload["competitors"]}


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
    post = await client.post("/api/v1/competitor/market-share",
                             json={"category": "Headphones"}, headers=HEADERS)
    get = await client.get("/api/v1/competitor/market-share/Headphones", headers=HEADERS)
    assert post.status_code == 200, post.text
    assert get.status_code == 200, get.text
    assert post.json()["data"]["type"] == get.json()["data"]["type"] == "market_share"


# ====== 二、店铺上下文闸门（第 142 轮 A2-3 起）======


async def test_write_endpoints_require_shop_header(client, auth_off):
    """
    写方法缺 `X-Shop-ID` ⇒ 400（不是 200 空结果、也不是 500）。

    为什么必须是 400 而不是「返回空数据」：竞品数据的**分区键就是 store_id**，
    没有它连"该看哪个店铺"都无从谈起。返回 200 + 空列表会被读成
    「AI 变笨了/这家店没竞品」，而正确归因是「你还没选店铺」——
    空值守卫放在请求形状这一层，`get_current_shop_id` 的 docstring 有完整理由。
    """
    r = await client.post("/api/v1/competitor/monitor", json={})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "店铺" in detail, f"400 原因应当是可行动的（提示选店铺），实际: {detail}"


async def test_read_endpoints_without_shop_return_explicit_empty_state(client, auth_off):
    """
    GET 快捷口缺头 ⇒ 200 + **显式空状态**（`no_data` / success=false），不是静默空结果。

    这一条钉的是「拿不到权威清单 ≠ 清单为空」：若返回
    `competitors: []` + `success: true`，前端会把「未选店铺」渲染成
    「该店铺确实没有竞品」——归因错方向，且用户永远不会去选店铺。
    """
    for url in (
        "/api/v1/competitor/monitor/dashboard",
        "/api/v1/competitor/market-share/Headphones",
        f"/api/v1/competitor/reviews/{KNOWN_ASIN}",
    ):
        body = (await client.get(url)).json()
        assert body["success"] is False, f"{url} 未选店铺却报成功: {body}"
        assert body["data"]["data_status"] == "no_data", f"{url}: {body}"
        assert "X-Shop-ID" in body["data"]["data_reason"], f"{url}: {body}"
        assert body["message"] == body["data"]["message"], (
            f"{url} 外层 message 与内层不一致（外层会丢掉真实原因）: {body}")


# ====== 三、竞品监控 ======


async def test_monitor_no_asin_returns_dashboard(client, auth_off):
    """不传 ASIN → 全量监控仪表盘"""
    r = await client.post("/api/v1/competitor/monitor", json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert data["type"] == "monitor_dashboard"
    assert data["total_competitors"] == len(data["competitors"]) > 0
    comp = data["competitors"][0]
    for key in ("asin", "brand", "current_price", "price_change_7d", "current_bsr", "alerts"):
        assert key in comp, f"监控条目缺字段 {key}"
    # 未启用 LLM 时摘要是结构化 dict（启用后会被 LLM 文本替换）
    assert isinstance(data["summary"], dict)
    assert "key_events" in data["summary"]


async def test_monitor_dashboard_covers_the_real_competitor_set(client, auth_off):
    """
    数据源里真实存在的 6 个竞品**全部**出现在仪表盘里。

    这是「数据源 → API」这条链路的正向证据：换数据源时最容易被忽略的失败模式是
    「接口还活着、字段也都在，但竞品集合悄悄变成了别的（或空）」——
    只断言 `total_competitors > 0` 抓不到，必须钉住具体成员。
    """
    data = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    assert _asins_of(data) == KNOWN_ASINS
    assert data["total_competitors"] == COMPETITOR_COUNT


async def test_monitor_dashboard_get_matches_post(client, auth_off):
    """GET /monitor/dashboard 是无参快捷口，结构必须与 POST /monitor 空参一致"""
    post = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    get = (await client.get("/api/v1/competitor/monitor/dashboard",
                            headers=HEADERS)).json()["data"]
    assert get["type"] == post["type"] == "monitor_dashboard"
    assert get["total_competitors"] == post["total_competitors"]
    assert _asins_of(get) == _asins_of(post)


async def test_monitor_single_asin_deep_analysis(client, auth_off):
    """传已知 ASIN → 单品深度分析（价格/排名趋势 + 三项分析）"""
    r = await client.post("/api/v1/competitor/monitor",
                          json={"asin": KNOWN_ASIN}, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    data = body["data"]
    assert data["type"] == "single_monitor"
    assert data["product"]["asin"] == KNOWN_ASIN
    assert len(data["price_trend"]) > 0
    assert len(data["ranking_trend"]) > 0
    assert set(data["analysis"]) == {"price_stability", "ranking_momentum", "stock_pattern"}
    # ★ 单品形态下 message 必须描述单品，不能说「成功获取 0 个竞品」
    #   （第 142 轮修：原先 3 条路径共用一句固定文案，与 payload 自相矛盾）
    assert KNOWN_ASIN in body["message"] or "单品" in body["message"], body["message"]


async def test_monitor_single_asin_does_not_fabricate_missing_fields(client, auth_off):
    """
    数据源没有的字段**留空**，不编造。

    竞品快照（`fetch_competitors`）不含类目与主图，改造前这里由
    `_initialize_mock_data()` 现编。契约：宁可空字符串，也不要一个看起来
    很合理但没人能追溯来源的类目名。
    """
    data = (await client.post("/api/v1/competitor/monitor",
                              json={"asin": KNOWN_ASIN}, headers=HEADERS)).json()["data"]
    product = data["product"]
    assert product["category"] == ""
    assert product["image_url"] == ""
    # 有真实值的字段必须来自数据源（价格/BSR/评分都 > 0）
    assert product["price"] > 0
    assert product["bsr_rank"] > 0
    assert product["rating"] > 0


async def test_monitor_lowercase_asin_is_accepted(client, auth_off):
    """Bug 2 回归：ASIN 小写（从 URL 复制）不得被判「未找到」"""
    r = await client.post("/api/v1/competitor/monitor",
                          json={"asin": KNOWN_ASIN.lower()}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "single_monitor", f"小写 ASIN 被当成未找到: {data}"
    assert data["product"]["asin"] == KNOWN_ASIN


async def test_monitor_unknown_asin_is_not_faked(client, auth_off):
    """
    未知 ASIN：`success=false` + `data.error`，且**不返回任何 product**。

    ★ 第 142 轮由 `xfail` 转正：改造前这条是「已知问题」——未知 ASIN 返回
      `200 + success: true + data.error`，信封自相矛盾（`success` 说成功、
      `data.error` 说没找到、`message` 又说「成功获取 0 个竞品」三个声音）。
      现在 `_ok()` 与 `_message()` 都以 `data.error` 为准，三者一致。
    """
    body = (await client.post("/api/v1/competitor/monitor",
                              json={"asin": UNKNOWN_ASIN}, headers=HEADERS)).json()
    assert body["success"] is False, f"未知 ASIN 不该谎报成功: {body}"
    assert UNKNOWN_ASIN in body["data"]["error"]
    assert "product" not in body["data"], "找不到就明说，不得返回伪造的 product"
    assert body["message"] == body["data"]["error"], (
        "message 与 data.error 必须同一个声音，否则 toast 会显示「成功」")


async def test_monitor_days_boundary(client, auth_off):
    """days 约束 7~90，越界由 Pydantic 拦成 422"""
    assert (await client.post("/api/v1/competitor/monitor",
                              json={"days": 3}, headers=HEADERS)).status_code == 422
    assert (await client.post("/api/v1/competitor/monitor",
                              json={"days": 120}, headers=HEADERS)).status_code == 422
    assert (await client.post("/api/v1/competitor/monitor",
                              json={"days": 7}, headers=HEADERS)).status_code == 200
    assert (await client.post("/api/v1/competitor/monitor",
                              json={"days": 90}, headers=HEADERS)).status_code == 200


async def test_monitor_summary_replaced_by_llm(client, auth_off, monkeypatch):
    """LLM 可用时，规则摘要被 LLM 文本替换（验证集成接线，不打真实模型）"""
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent

    async def fake_insights(self, context, max_tokens=800):
        return "LLM 综合结论：Kasa Smart Plug 正在降价抢量"

    monkeypatch.setattr(CompetitorIntelligenceAgent, "_llm_insights", fake_insights)
    data = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    assert data["summary"] == "LLM 综合结论：Kasa Smart Plug 正在降价抢量"


# ====== 四、ASIN 批量追踪 ======


async def test_track_batch_known_asins(client, auth_off):
    r = await client.post("/api/v1/competitor/track/batch",
                          json={"asins": [KNOWN_ASIN, KNOWN_ASIN_2]}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "batch_track"
    assert data["tracked_count"] == 2
    # 得分降序
    scores = [c["score"] for c in data["competitors"]]
    assert scores == sorted(scores, reverse=True)
    assert set(data["comparison_matrix"]) >= {"price", "rating", "reviews", "bsr", "score"}
    # 每个竞品的历史窗口都取到了（30d → 15 个快照 ⇒ 最低价/最高价/最佳排名都成立）
    for c in data["competitors"]:
        assert c["price_30d_low"] <= c["price"] <= c["price_30d_high"]
        assert c["bsr_30d_best"] <= c["bsr"]


async def test_track_batch_lowercase_asins(client, auth_off):
    """Bug 2 回归：小写 ASIN 列表也要认得"""
    data = (
        await client.post("/api/v1/competitor/track/batch",
                          json={"asins": [KNOWN_ASIN.lower()]}, headers=HEADERS)
    ).json()["data"]
    assert data["tracked_count"] == 1
    assert data["competitors"][0]["asin"] == KNOWN_ASIN


async def test_track_batch_unknown_asin_is_skipped_not_faked(client, auth_off):
    """未知 ASIN 只被跳过，不得伪造成数据（空状态优于虚构默认）"""
    data = (
        await client.post("/api/v1/competitor/track/batch",
                          json={"asins": [KNOWN_ASIN, UNKNOWN_ASIN]}, headers=HEADERS)
    ).json()["data"]
    assert data["tracked_count"] == 1
    assert all(c["asin"] == KNOWN_ASIN for c in data["competitors"])


@pytest.mark.parametrize("asins", [[], ["A" * 10] * 21])
async def test_track_batch_length_limits(client, auth_off, asins):
    """asins 长度约束 1~20"""
    r = await client.post("/api/v1/competitor/track/batch",
                          json={"asins": asins}, headers=HEADERS)
    assert r.status_code == 422


# ====== 五、市场份额分析 ======


async def test_market_share_post(client, auth_off):
    r = await client.post("/api/v1/competitor/market-share",
                          json={"category": "Headphones"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "market_share"
    assert data["category"] == "Headphones"
    assert data["total_market_estimate"] > 0
    assert len(data["competitors"]) == COMPETITOR_COUNT
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
    r = await client.get("/api/v1/competitor/market-share/Headphones", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["type"] == "market_share"


async def test_market_share_missing_category_422(client, auth_off):
    r = await client.post("/api/v1/competitor/market-share", json={}, headers=HEADERS)
    assert r.status_code == 422


# ====== 六、定价策略分析 ======


async def test_pricing_analyze_all(client, auth_off):
    """不传 ASIN → 分析全部竞品"""
    r = await client.post("/api/v1/competitor/pricing/analyze", json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "pricing_strategy"
    assert data["analyzed_count"] == len(data["strategies"]) == COMPETITOR_COUNT
    s = data["strategies"][0]
    assert s["strategy_type"] in ("premium", "economy", "competitive", "dynamic")
    assert s["promo_frequency"] in ("high", "medium", "low")
    assert s["recommendations"]
    assert "positions" in data["market_positioning_map"]
    # ★ 价格弹性需要「价格 → 销量」配对，而竞品快照不含销量 ⇒ 数据源没给的一律 0，
    #   不得用随机数伪装成"算出来的弹性"（改造前是 random.uniform(-1.5, -2.5)）。
    assert all(x["price_elasticity"] == 0.0 for x in data["strategies"])


async def test_pricing_analyze_lowercase_asin(client, auth_off):
    """Bug 2 回归：小写 ASIN 也要命中（此前 analyzed_count 静默为 0）"""
    data = (
        await client.post("/api/v1/competitor/pricing/analyze",
                          json={"asin": KNOWN_ASIN.lower()}, headers=HEADERS)
    ).json()["data"]
    assert data["analyzed_count"] == 1
    assert data["strategies"][0]["strategy_type"] in ("premium", "economy", "competitive", "dynamic")


# ====== 七、竞品评论深度分析 ======


async def test_reviews_analyze_by_body(client, auth_off):
    r = await client.post("/api/v1/competitor/reviews/analyze",
                          json={"asin": KNOWN_ASIN}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "review_analysis"
    assert data["analyzed_products"] == 1
    a = data["analyses"][0]
    assert a["asin"] == KNOWN_ASIN
    assert set(a["swot"]) == {"strengths", "weaknesses", "opportunities", "threats"}
    assert a["insights"]


async def test_reviews_degrades_honestly_without_review_text(client, auth_off):
    """
    数据源不含评论正文 ⇒ 必须**显式降级**，而不是编出主题与原文引用。

    契约三件套：
      ① `data_status == "partial"` —— 明确说这是残缺结果；
      ② `data_reason` 说清缺什么（评论正文）与后果（主题级洞察/引用不可得）；
      ③ `actionable_intelligence == []` 且每条 insight 的 `example_quotes == []`
         —— 宁可空着，也不放一段没人能追溯的"用户原话"。
    """
    data = (await client.post("/api/v1/competitor/reviews/analyze",
                              json={"asin": KNOWN_ASIN}, headers=HEADERS)).json()["data"]
    assert data["data_status"] == "partial"
    assert "评论正文" in data["data_reason"]
    a = data["analyses"][0]
    assert a["actionable_intelligence"] == []
    assert all(i["example_quotes"] == [] for i in a["insights"])


async def test_reviews_analyze_lowercase_asin(client, auth_off):
    """Bug 2 回归：POST body 小写 ASIN 此前静默返回 0 个产品"""
    data = (
        await client.post("/api/v1/competitor/reviews/analyze",
                          json={"asin": KNOWN_ASIN.lower()}, headers=HEADERS)
    ).json()["data"]
    assert data["analyzed_products"] == 1


async def test_reviews_get_shortcut_uppercases(client, auth_off):
    """快捷口自带 .upper()（这条一直是好的，钉住它别退化）"""
    r = await client.get(f"/api/v1/competitor/reviews/{KNOWN_ASIN.lower()}", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["analyses"][0]["asin"] == KNOWN_ASIN


async def test_reviews_validation(client, auth_off):
    """asin 必填；sample_size 约束 10~1000"""
    assert (await client.post("/api/v1/competitor/reviews/analyze",
                             json={}, headers=HEADERS)).status_code == 422
    for size in (5, 1001):
        r = await client.post("/api/v1/competitor/reviews/analyze",
                              json={"asin": KNOWN_ASIN, "sample_size": size}, headers=HEADERS)
        assert r.status_code == 422, f"sample_size={size} 应被拒"


# ====== 八、入侵者检测（当前**显式不可用**，第 142 轮起）======


async def test_intruders_detect_is_explicitly_unsupported(client, auth_off):
    """
    入侵者检测：200 + `data_status="unsupported"` + `success=false`，**不返回名单**。

    ★ 改造前这里返回 3 个硬编码的假新进入者（B0NEW001/002/003，
      「7 天内获得 200+ 评论」之类的理由全是编的）。
      竞品快照数据源**没有「新进入者」这个维度** —— 它给的是「当前竞品集合的
      快照序列」，回答不了「谁是最近才出现的」。要恢复此能力得接
      ① 商品上架时间 或 ② 类目新品榜。

    因此本能力的契约是：**明说不可用**，而不是返回一份看起来煞有介事的名单。
    这条用例的价值在于：谁想把这句 `unsupported` 换回假数据，就必须先删掉它。
    """
    r = await client.post("/api/v1/competitor/intruders/detect",
                          json={"category": "Headphones"}, headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    data = body["data"]
    assert data["type"] == "unsupported"
    assert data["data_status"] == "unsupported"
    assert "数据源" in data["data_reason"]
    assert body["success"] is False
    for key in ("new_competitors", "threat_summary", "response_strategies"):
        assert key not in data, f"不可用的能力不得返回 {key}（伪数据入口）"


async def test_intruders_get_shortcut_is_also_unsupported(client, auth_off):
    """快捷口与 POST 同源同判据（不能一个有守卫、一个漏）"""
    body = (await client.get("/api/v1/competitor/intruders/Headphones", headers=HEADERS)).json()
    assert body["data"]["data_status"] == "unsupported"
    assert body["success"] is False


async def test_intruders_lookback_days_boundary(client, auth_off):
    assert (
        await client.post("/api/v1/competitor/intruders/detect",
                          json={"category": "x", "lookback_days": 3}, headers=HEADERS)
    ).status_code == 422


# ====== 九、Buy Box 竞争分析 ======


async def test_buy_box_analyze(client, auth_off):
    r = await client.post("/api/v1/competitor/buy-box/analyze", json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "buy_box_analysis"
    assert data["analyzed_count"] == len(data["analyses"]) == COMPETITOR_COUNT
    assert data["best_practices"]
    bb = data["analyses"][0]["buy_box_analysis"]
    for key in ("current_winner", "winning_price", "all_sellers", "buy_box_percentage",
                "price_to_win", "featured_offer_reason"):
        assert key in bb, f"Buy Box 缺字段 {key}"
    score = data["analyses"][0]["competitiveness_score"]
    assert 0 <= score <= 100


async def test_buy_box_does_not_invent_winner_or_seller_list(client, auth_off):
    """
    数据源只有「Buy Box 归属 + 价格」两项 ⇒ 卖家清单与占有率不得编造；
    `has_buybox=false` 的商品（TaoTronics）赢家必须是 `None`，不能硬塞一个品牌。

    这是本能力最容易踩的坑：给每个竞品都填一个 `current_winner`（用自己的品牌名）
    看起来毫无破绽，但它把「没有 Buy Box」这个**真实的商业事实**抹掉了。
    """
    data = (await client.post("/api/v1/competitor/buy-box/analyze",
                              json={}, headers=HEADERS)).json()["data"]
    assert data["data_status"] == "partial"
    assert "卖家清单" in data["data_reason"]

    by_asin = {a["asin"]: a for a in data["analyses"]}
    # 全部卖家清单为空（数据源不给）
    assert all(a["buy_box_analysis"]["all_sellers"] == [] for a in data["analyses"])
    # 没有 Buy Box 的那个：赢家为 None、占有率为 0，且其分数显著低于有 Buy Box 的
    no_bb = by_asin[KNOWN_ASIN_NO_BUYBOX]["buy_box_analysis"]
    assert no_bb["current_winner"] is None
    assert no_bb["buy_box_percentage"] == 0.0
    assert (by_asin[KNOWN_ASIN_NO_BUYBOX]["competitiveness_score"]
            < by_asin[KNOWN_ASIN]["competitiveness_score"])


async def test_buy_box_lowercase_asin(client, auth_off):
    """Bug 2 回归"""
    data = (
        await client.post("/api/v1/competitor/buy-box/analyze",
                          json={"asin": KNOWN_ASIN.lower()}, headers=HEADERS)
    ).json()["data"]
    assert data["analyzed_count"] == 1


# ====== 十、多维度竞品对比 ======


async def test_compare_two_asins(client, auth_off):
    r = await client.post("/api/v1/competitor/compare",
                          json={"asins": [KNOWN_ASIN, KNOWN_ASIN_2]}, headers=HEADERS)
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


async def test_compare_ranking_is_internally_consistent(client, auth_off):
    """
    排名与各维度最优者必须自洽（防止维度口径各算各的）。

    钉住的不变量：
      · `overall_ranking` 的 rank 从 1 连续编号，且与分数降序一致；
      · `price_comparison.best` 就是价格最低的那个品牌（不是随便哪个）。
    """
    data = (await client.post("/api/v1/competitor/compare",
                              json={"asins": [KNOWN_ASIN, KNOWN_ASIN_2]},
                              headers=HEADERS)).json()["data"]
    comparison = data["comparison"]

    ranks = [x["rank"] for x in comparison["overall_ranking"]]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [x["overall_score"] for x in comparison["overall_ranking"]]
    assert scores == sorted(scores, reverse=True)

    prices = comparison["price_comparison"]["values"]
    cheapest = min(prices, key=lambda v: v["value"])
    assert comparison["price_comparison"]["best"] == cheapest["brand"]


async def test_compare_single_asin_rejected_by_schema_not_router(client, auth_off):
    """
    单个 ASIN → **422（Pydantic）**，不是 400。

    `CompetitorCompareRequest.asins` 已声明 `min_length=2`，请求校验阶段就退回 422，
    因此路由里的 `if len(request.asins) < 2: raise HTTPException(400, "至少需要2个ASIN进行对比")`
    是**不可达分支**（死代码）。钉住 422 这个真实契约，避免有人误以为 400 会触发。
    若将来要给用户中文友好提示，要么放开 schema 的 min_length，要么在前端拦。
    """
    r = await client.post("/api/v1/competitor/compare",
                          json={"asins": [KNOWN_ASIN]}, headers=HEADERS)
    assert r.status_code == 422, r.text


async def test_compare_too_many_asins(client, auth_off):
    r = await client.post("/api/v1/competitor/compare",
                          json={"asins": ["A" * 10] * 11}, headers=HEADERS)
    assert r.status_code == 422


# ====== 十一、通用入口（自然语言） ======


@pytest.mark.parametrize(
    "query,expected_type,expected_intent",
    [
        ("耳机市场份额", "market_share", "market_share"),
        ("分析评论", "review_analysis", "reviews"),
        ("定价策略", "pricing_strategy", "pricing"),
        ("Buy Box", "buy_box_analysis", "buy_box"),
        (f"对比 {KNOWN_ASIN} {KNOWN_ASIN_2}", "competitor_comparison", "compare"),
    ],
)
async def test_analyze_intent_routing(client, auth_off, query, expected_type, expected_intent):
    """自然语言入口的意图路由（真实意图落在 data.intent）"""
    r = await client.post("/api/v1/competitor/analyze",
                          params={"query": query}, json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == expected_type
    assert data["intent"] == expected_intent


async def test_analyze_intruder_query_routes_to_unsupported(client, auth_off):
    """
    「新进入的竞争者」→ 意图路由**是对的**（`intruder`），能力本身不可用。

    这两个断言要分开看，否则会得出错误结论：意图路由没问题（`intent == "intruder"`），
    不可用的是数据源维度（`type == "unsupported"`）。混在一条用例里会让人以为
    「路由坏了」而去改 `_classify_intent` —— 改错地方。
    """
    data = (await client.post("/api/v1/competitor/analyze",
                              params={"query": "新进入的竞争者"},
                              json={}, headers=HEADERS)).json()["data"]
    assert data["intent"] == "intruder"
    assert data["type"] == "unsupported"


async def test_analyze_monitor_query_returns_single_monitor(client, auth_off):
    """
    Bug 1 回归（本文件最重要的一条）。

    路由文档承诺「"监控 B08N5KWB9H" → 单品监控」。修复前 `_monitor_competitor`
    因 `or`/条件表达式优先级把已提取到的 ASIN 丢弃（`/analyze` 不传 context），
    实际返回全量仪表盘 `monitor_dashboard`。
    """
    r = await client.post("/api/v1/competitor/analyze",
                          params={"query": f"监控 {KNOWN_ASIN}"}, json={}, headers=HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["intent"] == "monitor"
    assert data["type"] == "single_monitor", "ASIN 又被丢了：单品监控退化成全量仪表盘"
    assert data["product"]["asin"] == KNOWN_ASIN


async def test_analyze_query_required(client, auth_off):
    """query 是必填查询参数，缺了 422（不能静默返回空结果）"""
    assert (await client.post("/api/v1/competitor/analyze",
                             headers=HEADERS)).status_code == 422


# ====== 十二、鉴权闸门 ======


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
# 1) `/compare` 的 400 分支不可达（见 test_compare_single_asin_rejected_by_schema_not_router）。
# 2) 顶层 `intent` 字段恒为 ""（真实意图只在 `data.intent`），
#    `CompetitorAnalysisResponse.intent` 从未被填充 → 见 xfail 用例。
# 3) `_classify_intent` 永不返回 "general"，导致
#    a. `handlers.get(intent, self._general_analysis)` 的兜底分支不可达；
#    b. `stream_chat` 里 `if intent != "general"` 恒为真 → **LLM 流式分支是死代码**，
#       `/chat/stream` 实际只把结构化结果包了一层 SSE（其他 Agent 是真流式）。
#    → 见 test_classify_intent_never_returns_general。
# 4) ★ `/monitor` 的 `days` 参数**从未到达数据层**（2026-09-18 实测，留底
#    `.workbuddy/probes/r142_ci_truth/days.txt`）：
#       days=7  / 30 / 90 → price_trend 长度、price_change_7d 完全相同（均 14 / -7.9）
#    根因：`service.monitor_competitor` 组 context 时没带 `days`，
#    `_ensure_source` 于是恒取 `f"{ctx.get('days') or 30}d"` = "30d"。
#    而数据源本身**是尊重区间**的（实测 7d→24 行/4 个日期、30d→90 行/15 个、
#    90d→270 行/45 个）⇒ 参数确实被吞在中间层。
#    为什么这次不顺手接通：接通后会暴露出第二个问题 —— `_calculate_price_change(asin, 7)`
#    在快照不足 7 个点时 `return 0.0`，于是 7 天窗口会显示「价格变动 0%」，
#    那又是一个「静默 0 = 假数据」的坑。改它等于重新定义该指标口径，
#    属于产品决策，留给老板拍板。
#
# 已修（第 142 轮，保留记录以免有人改回去）：
# 5) 未知 ASIN 的信封自相矛盾（success=true + data.error + message「成功」）
#    → 现为 success=false，三者同一个声音（见 test_monitor_unknown_asin_is_not_faked）。
# 6) 单品监控的 message 说「成功获取 0 个竞品」而 payload 里有完整 product
#    → 现按 payload 形态给文案（见 test_monitor_single_asin_deep_analysis）。


@pytest.mark.xfail(reason="已知问题：顶层 intent 字段从未被填充，恒为空串")
async def test_top_level_intent_is_populated(client, auth_off):
    """期望：`CompetitorAnalysisResponse.intent` 应带出真实意图，而不是恒 """""
    body = (
        await client.post("/api/v1/competitor/analyze",
                          params={"query": "耳机市场份额"}, json={}, headers=HEADERS)
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

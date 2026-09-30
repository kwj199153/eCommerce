"""
/api/v1/competitor 端点测试（13 个非流式端点 + 1 个 SSE）

为什么这个文件重要
------------------
竞品情报模块后端**功能最全**（14 个路由、8 项分析能力），但此前**零端点测试**。
端点测试的价值在于：在联调之前把契约（信封、字段名、边界校验、快捷口是否与 POST 同构）
钉死。

第 172 轮（2026-09-20）**重基：取数真源从 mock 数据源改为数据库表**
------------------------------------------------------------------
老板指令原文：「mock数据可以删，但是要搬到数据库中，你说的真源应该就是数据库中的数据吧。
（因为现在真实的数据获取不到的，只能说保留接口以后可以接真实api获取数据）」

改了什么（两处，都实测过）：
  1. **落库**：新增 `modules/amazon_sp/seed.py`，把 `monitors`（用户真正在盯的竞品池）
     展开成 `amazon_competitor_snapshots` 的**逐日行**，挂在 `core.bootstrap`
     的 ⑤b 步（紧随监控池之后）。
  2. **取数**：两个消费方的 `_load_competitor_rows()` 都改为读表。
     查询本体上收到 `modules/amazon_sp/snapshot_repo.load_competitor_snapshots()`
     （表的所有者），经门面出口。→ 无 SP-API 凭据时**不再回退 mock**，
     这就是本文件夹具存在的理由。

  ★ 收尾时又发现**第二份**实现：`ad_analysis/agent_ad.py::_load_competitor_rows()`
    同样在走 `get_data_source()`（无凭据即 `MockAmazonDataSource` 现编
    TP-Link / Anker / JBL），服务「竞品广告分析」。上一版门禁**只扫一个模块**
    ⇒ 全绿却漏了它。现在两处共用唯一入口，门禁也升级为**全仓**扫描
    （`test_competitor_snapshot_has_exactly_one_door`）。
    教训：**单模块 scoped 的门禁只能证明「这一份是对的」，不能证明「只有这一份」。**

★ 为什么测试必须自己造数据（`_competitor_pool` 夹具）
  改造前，测试只要带一个 `X-Shop-ID` 就有数据 —— 因为 mock 数据源**不看店铺**，
  现场随机生成 6 个竞品。现在真源是表，测试店铺（`store_test`）名下没有监控池
  ⇒ 全部能力落在 `no_data`。夹具负责把"用户添加竞品"这一步显式做出来。

  这不是测试的负担，而是**契约变严格了**：数据从哪来变成了可追溯的事实，
  而不是"问一句就有"。同一原因也让下面的断言从"数字对不对"变成
  "集合与不变量对不对" —— 因为数值现在由 `build_time_series()` 确定性生成，
  再写死一遍只是把同一份实现抄两份。

★ 两类断言的分工（不要混）
  · **无池店铺**（`test_no_pool_shop_never_falls_back_to_mock`）：
    钉「不许凭空造数据」。这是本轮改造的**唯一硬证据** ——
    只要 mock 回退还在，这条必红。
  · **有池店铺**：钉「真实池子的成员与结构」。数值只断言不变量（低 ≤ 现价 ≤ 高 等）。

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
* 不测具体数值：集合、长度、不变量（份额归一化 / 排名自洽 / 低≤现价≤高）。
"""

import inspect
import re

import pytest
import pytest_asyncio
pytestmark = pytest.mark.tenant_identity


# ====== 常量（全部来自实测，见文件头「地面真相」）======

SHOP = "store_test"
HEADERS = {"X-Shop-ID": SHOP}      # 写方法缺它 ⇒ 400；GET 缺它 ⇒ 显式空状态

#: 监控池里的竞品（`modules/monitors/seed.py::SEED_SPECS` 的 ASIN）。
KNOWN_ASIN = "B0MONBRD01"          # Voltage 100W GaN 快充 —— 类目头部品牌
KNOWN_ASIN_2 = "B0MONPRO01"        # ZestPro 便携咖啡机 —— 核心对标爆款（BSR 最优）
KNOWN_ASINS = {
    "B0MONBRD01", "B0MONBRD02", "B0MONPRO01",
    "B0MONPRO02", "B0MONPRO03", "B0MONSTO01",
}
UNKNOWN_ASIN = "B0ZZZZZZZZ"        # 10 位且符合 [A-Z0-9]{10}，但不在监控池

COMPETITOR_COUNT = len(KNOWN_ASINS)   # 6 —— 与 SEED_SPECS 同长，不手写

#: 「有店铺行、但没有监控池」的合成店铺：`store_x` 已在 conftest 的
#: `SYNTHETIC_TEST_SHOP_IDS` 里注册，可安全用作 `X-Shop-ID`。
#:
#: ★ 第 177 轮换值：原来是 `store_no_pool_x`，一个**库里不存在**的 id。
#:   它能用只是因为当时的演示档（`user is None`）会在归属校验前整体放行，
#:   而"不存在"与"不属于你"在那条路径上都只表现为同一件事。
#:   演示档旁路收掉、且 `shop_id -> stores_store` 外键早已存在之后，
#:   本常量必须是一个**真实存在、且归属夹具租户**的行 —— 否则用例会先撞
#:   归属 403 / 外键违例，而不是它真正要验证的「没有监控池时不许回退 mock」。
SHOP_NO_POOL = "store_x"

#: 第 172 轮改造前，数据源是 `MockAmazonDataSource`，它有自己的 6 个竞品。
#: 这组品牌名现在是**反例清单**：任何一条出现在响应里，都说明 mock 回退复活了。
MOCK_WORLD_BRANDS = {
    "TP-Link", "Amazon Basics", "Anker", "Satechi", "TaoTronics", "JBL",
}

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


@pytest_asyncio.fixture(autouse=True)
async def _competitor_pool():
    """给 `SHOP` 建出「监控池 + 已展开的竞品快照」，用例结束即清。

    ★ 为什么是 autouse：绝大多数的用例都要求"这个店铺有竞品"，
      漏掉一次就会得到一个看起来像"分析坏了"的 `no_data`。
      默认有数据、要空数据的用例显式自证（见 `test_no_pool_shop_...`）。

    ★ 为什么每次重新生成而不是复用既有行：`build_seed_record()` 内部的
      `build_time_series()` 以**运行当日**为基准生成最近 30 天时序。
      若复用旧行，测试会在 seed 满 30 天后因数据滑出查询窗口而**集体变红**，
      且红得毫无线索（数据"在库里"却查不到）。
    """
    from sqlalchemy import text

    from core.database import async_session_factory
    from modules.amazon_sp.db_model import CompetitorSnapshot
    from modules.amazon_sp.seed import build_snapshot_rows
    from modules.monitors.db_model import MonitorRecord
    from modules.monitors.seed import SEED_SPECS, build_seed_record

    async def _purge(session):
        await session.execute(text(
            "DELETE FROM amazon_competitor_snapshots WHERE store_id = :s"), {"s": SHOP})
        await session.execute(text(
            "DELETE FROM monitors WHERE shop_id = :s"), {"s": SHOP})

    async with async_session_factory() as session:
        await _purge(session)
        records = [build_seed_record(SHOP, spec, i) for i, spec in enumerate(SEED_SPECS)]
        session.add_all(records)
        # 展开成逐日快照 —— 与 `seed_competitor_snapshots_if_empty()` 同一函数，
        # 差别只是绕过"全表非空即跳过"的全局幂等（那会让第二个店铺永远灌不进去）。
        for monitor in records:
            for row in build_snapshot_rows(monitor):
                session.add(row)
        await session.commit()

    yield

    async with async_session_factory() as session:
        await _purge(session)
        await session.commit()


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
    """13 个非流式端点 + 1 个 SSE 端点必须全部注册（少一个前端就静默 404）

    ★ 第 247 轮：取路由改走 `scripts.route_inventory`（唯一真源）。
      FastAPI 0.141 起 `include_router()` 不再把子路由摊平进 `app.routes`，
      而是追加惰性容器 `_IncludedRouter` ⇒ 原先的 `for r in app.routes`
      在这里只数到 7 条框架内置路径，`/api/v1/competitor*` **一条都数不到**。
      本条还算幸运：`missing` 是集合差，盘点为空时它会等于整个 EXPECTED_ROUTES
      ⇒ 直接报红（归因还算清楚）。真正危险的是那些「盘点为空 ⇒ 断言恒真」的
      写法（见 `scripts/auth_coverage_report.py` 的历史形态）。
      真源在盘点为 0 时**抛错**，这类失明不可能再被静默吞掉。
    """
    from main import app
    from scripts.route_inventory import iter_endpoint_signatures

    registered = {
        (m, path)
        for m, path in iter_endpoint_signatures(app)
        if path.startswith("/api/v1/competitor")
    }

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


# ====== 二、店铺上下文闸门 ======


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


# ====== 三、★ 本轮核心：无监控池的店铺不得回退 mock ======


async def test_no_pool_shop_never_falls_back_to_mock(client, auth_off):
    """
    ★ 第 172 轮改造的**唯一硬证据**：监控池为空的店铺必须得到显式空状态。

    改造前这条必红 —— 取数走 `get_data_source(prefer="auto")`，没有 SP-API
    凭据时静默回退到 `MockAmazonDataSource`，于是**任何**店铺 id 都能拿到
    6 个随机竞品（TP-Link / Anker / JBL…）。用户看到的"竞品"与自己在监控池里
    盯的对象毫无关系，而且同一问题问两次答案不同。

    现在的契约三层：
      ① 竞品数 = 0（没有就是没有）；
      ② 响应里**一个 mock 世界品牌都不许有** —— 只断言 ① 不够，
         因为将来若有人把 6 条 mock 过滤成 3 条，① 依然会过；
      ③ 文案要**可行动**：告诉用户去哪儿加竞品，而不是"暂无数据"。
    """
    body = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers={"X-Shop-ID": SHOP_NO_POOL})).json()
    data = body["data"]

    assert body["success"] is False, f"没有监控池却报成功: {body}"
    assert data["data_status"] == "no_data", data
    assert not data.get("competitors"), f"空池子却返回了竞品: {data.get('competitors')}"

    blob = str(body)
    leaked = sorted(b for b in MOCK_WORLD_BRANDS if b in blob)
    assert not leaked, f"mock 世界的竞品又出现了（回退复活）: {leaked}"

    assert "监控池" in data["data_reason"], (
        f"空状态文案要说清「去哪儿加竞品」，实际: {data['data_reason']}")


async def test_the_pool_is_the_only_truth_source(client, auth_off):
    """
    同一时刻两个店铺必须各自看到**自己的**池子（真源按 store_id 分区）。

    这是"真源 = 数据库"的第二个面：改造前 mock 数据源不看 store_id，
    两个店铺返回**同一个**随机集合 —— 数据隔离在展示层就已失效。
    """
    a = (await client.post("/api/v1/competitor/monitor",
                           json={}, headers=HEADERS)).json()["data"]
    b = (await client.post("/api/v1/competitor/monitor",
                           json={}, headers={"X-Shop-ID": SHOP_NO_POOL})).json()["data"]

    assert _asins_of(a) == KNOWN_ASINS, "有池店铺必须看到池子里的 6 个"
    assert not b.get("competitors"), "无池店铺必须看不到任何竞品"


# ====== 四、竞品监控 ======


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
    监控池里真实存在的 6 个竞品**全部**出现在仪表盘里。

    这是「监控池 → 快照表 → API」这条链路的正向证据：换数据源时最容易被忽略的
    失败模式是「接口还活着、字段也都在，但竞品集合悄悄变成了别的（或空）」——
    只断言 `total_competitors > 0` 抓不到，必须钉住具体成员。
    """
    data = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    assert _asins_of(data) == KNOWN_ASINS
    assert data["total_competitors"] == COMPETITOR_COUNT


async def test_monitor_all_values_trace_back_to_the_pool(client, auth_off):
    """
    数值必须**可追溯到池子**，不能是随机数。

    池子里每个竞品都有 `est_monthly_sales` 与 `latest_bsr`；仪表盘给出的
    BSR 必须落在「围绕基准漂移」的合理带内（生成器是 `base_bsr ± 25%` 再叠加
    正弦项，留 2 倍余量），且价格 > 0。若有人改回现场随机，量级会立刻漂出这个带。
    """
    from modules.monitors.seed import SEED_SPECS

    base_bsr = {s["asin"]: s["base_bsr"] for s in SEED_SPECS}
    data = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    for c in data["competitors"]:
        assert c["current_price"] > 0, c
        assert 0 < c["current_bsr"] <= base_bsr[c["asin"]] * 2, (
            f"{c['asin']} 的 BSR 漂出池子基准 {base_bsr[c['asin']]} 的 2 倍: {c['current_bsr']}")


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
    assert KNOWN_ASIN in body["message"] or "单品" in body["message"], body["message"]


async def test_monitor_single_asin_does_not_fabricate_missing_fields(client, auth_off):
    """
    快照表没有的字段**留空**，不编造。

    竞品快照不含类目与主图 URL（`main_image_url` 在表里有，但
    `_build_from_rows` 刻意不把它当 `image_url` 用 —— 那是本店铺素材库的字段口径），
    改造前这里由 `_initialize_mock_data()` 现编。契约：宁可空字符串，
    也不要一个看起来很合理但没人能追溯来源的类目名。
    """
    data = (await client.post("/api/v1/competitor/monitor",
                              json={"asin": KNOWN_ASIN}, headers=HEADERS)).json()["data"]
    product = data["product"]
    assert product["category"] == ""
    assert product["image_url"] == ""
    # 有真实值的字段必须来自池子（价格/BSR/评分都 > 0）
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
      `200 + success: true + data.error`，信封自相矛盾。
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
        return "LLM 综合结论：Voltage 正在降价抢量"

    monkeypatch.setattr(CompetitorIntelligenceAgent, "_llm_insights", fake_insights)
    data = (await client.post("/api/v1/competitor/monitor",
                              json={}, headers=HEADERS)).json()["data"]
    assert data["summary"] == "LLM 综合结论：Voltage 正在降价抢量"


# ====== 五、ASIN 批量追踪 ======


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
    # 每个竞品的历史窗口都取到了 ⇒ 最低价/最高价/最佳排名自洽
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


# ====== 六、市场份额分析 ======


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


# ====== 七、定价策略分析 ======


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


# ====== 八、竞品评论深度分析 ======


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
    快照表不含评论正文 ⇒ 必须**显式降级**，而不是编出主题与原文引用。

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


# ====== 九、入侵者检测（当前**显式不可用**）======


async def test_intruders_detect_is_explicitly_unsupported(client, auth_off):
    """
    入侵者检测：200 + `data_status="unsupported"` + `success=false`，**不返回名单**。

    ★ 改造前这里返回 3 个硬编码的假新进入者（B0NEW001/002/003，
      「7 天内获得 200+ 评论」之类的理由全是编的）。
      竞品快照**没有「新进入者」这个维度** —— 它给的是「当前竞品集合的
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


# ====== 十、Buy Box 竞争分析 ======


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
    ★ 第 172 轮语义升级。

    改造前这条钉的是「TaoTronics 那一个没有 Buy Box」。现在**全部**竞品都没有 ——
    因为 `monitors` 表根本没有 Buy Box 维度，落库时该列刻意留 NULL
    （见 `modules/amazon_sp/seed.py` 的「刻意留空」一节）。

    于是判据从「某个商品无 Buy Box」升级为「**整个维度缺失时全部诚实降级**」：

      · `current_winner` 必须**全是 None** —— 给每个竞品都填自家品牌名
        看起来毫无破绽，但它把「我们没有这个数据」这个真实事实抹掉了；
      · `all_sellers` 全为空（数据源不给卖家清单）；
      · `data_status == "partial"` + 文案点明缺"卖家清单"。

    将来接真实 SP-API 抓取后，这条会**自然变红**（赢家不再是 None）——
    那时请把它改成"赢家必须来自抓取结果"，而不是删掉。
    """
    data = (await client.post("/api/v1/competitor/buy-box/analyze",
                              json={}, headers=HEADERS)).json()["data"]
    assert data["data_status"] == "partial"
    assert "卖家清单" in data["data_reason"]

    assert all(a["buy_box_analysis"]["all_sellers"] == [] for a in data["analyses"])
    winners = {a["buy_box_analysis"]["current_winner"] for a in data["analyses"]}
    assert winners == {None}, f"表里没有 Buy Box 维度，赢家必须全为 None，实际: {winners}"
    assert all(a["buy_box_analysis"]["buy_box_percentage"] == 0.0 for a in data["analyses"])


async def test_buy_box_lowercase_asin(client, auth_off):
    """Bug 2 回归"""
    data = (
        await client.post("/api/v1/competitor/buy-box/analyze",
                          json={"asin": KNOWN_ASIN.lower()}, headers=HEADERS)
    ).json()["data"]
    assert data["analyzed_count"] == 1


# ====== 十一、多维度竞品对比 ======


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
    因此路由里的 `if len(request.asins) < 2: raise HTTPException(400, ...)`
    是**不可达分支**（死代码）。钉住 422 这个真实契约，避免有人误以为 400 会触发。
    """
    r = await client.post("/api/v1/competitor/compare",
                          json={"asins": [KNOWN_ASIN]}, headers=HEADERS)
    assert r.status_code == 422, r.text


async def test_compare_too_many_asins(client, auth_off):
    r = await client.post("/api/v1/competitor/compare",
                          json={"asins": ["A" * 10] * 11}, headers=HEADERS)
    assert r.status_code == 422


# ====== 十二、通用入口（自然语言） ======


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

    路由文档承诺「"监控 <ASIN>" → 单品监控」。修复前 `_monitor_competitor`
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


# ====== 十三、鉴权闸门 ======


def test_routes_under_business_auth_gate():
    """
    竞品路由必须挂在 `BUSINESS_AUTH` 下（源码断言）。

    不能用 `auth_on` 夹具断言 401 —— `BUSINESS_AUTH` 是 `import main` 时求值一次的
    启动期快照；第 106 轮起该常量已改为**无条件挂载**（请求期读 config）。
    此处保留源码断言，只为防「新增模块漏挂闸门」。
    """
    import main

    flat = re.sub(r"\s+", " ", inspect.getsource(main))
    assert "competitor_intel_router, prefix=\"/api/v1\", dependencies=BUSINESS_AUTH" in flat


# ====== 十四、取数层**唯一入口**（全仓源码级门禁，第 172 轮） ======


def _has_store_id_filter(tree) -> bool:
    """入口里是否存在「某个对象的 `.store_id` 参与比较」的形态（租户过滤没被删）。

    ★ 为什么用 AST 而不是字符串包含：本仓铁律 —— docstring 里写一句
      `WHERE store_id = ...` 就能骗过字符串判据。这里要的是**语法树里真的有一次
      拿 `.store_id` 去比较**（`.store_id == str(store_id)` 落在 ast.Compare 上）。
    """
    import ast

    for n in ast.walk(tree):
        if not isinstance(n, ast.Compare):
            continue
        sides = [n.left, *n.comparators]
        if any(isinstance(s, ast.Attribute) and s.attr == "store_id" for s in sides):
            return True
    return False


def test_competitor_snapshot_has_exactly_one_door():
    """★ 第 172 轮门禁（升级版）：竞品快照的取数必须走**全仓唯一入口**。

    这条替代了同轮早先那版 `test_load_competitor_rows_reads_the_database_not_the_factory`
    —— 那版**只扫一个模块**（`competitor_intel.agent_competitor`），于是
    `ad_analysis/agent_ad.py` 里那**第二份**同职责实现（`get_data_source()` →
    无凭据即 `MockAmazonDataSource` → 现编 6 个 TP-Link / Anker / JBL）
    在门禁全程绿的情况下继续服务「竞品广告分析」。

    ⇒ 教训写进门禁：**单模块 scoped 的门禁只能证明「这一份是对的」，
      不能证明「只有这一份」。** 所以本门禁扫全仓 `modules/**`。

    四件事一起钉：
      ① 除表的所有者（`modules/amazon_sp/`）外，任何模块**不得**出现
         `fetch_competitors` / `MockAmazonDataSource` 这两个名字（AST 层面）；
      ② 两个消费方都必须 `from modules.amazon_sp import load_competitor_snapshots`；
      ③ 入口本体（`amazon_sp/snapshot_repo.py`）必须真的查表、且**带租户过滤**；
      ④ `_load_competitor_rows` 这个名字在全仓只允许出现在两个消费方，
         冒第三处就是又开了一份实现。

    ★ 判据一律走 AST：本仓铁律 —— docstring 里的历史说明（本模块里正好写着
      `fetch_competitors()` / `get_data_source(prefer="auto")`）会骗过任何
      「源码字符串包含」型判据，既假红也假绿。
    """
    import ast
    from pathlib import Path

    from modules.ad_analysis import agent_ad as mod_ad
    from modules.competitor_intel import agent_competitor as mod_ci

    backend = Path(__file__).resolve().parents[1]
    modules = backend / "modules"

    consumers = {
        "modules/competitor_intel/agent_competitor.py": "competitor_intel",
        "modules/ad_analysis/agent_ad.py": "ad_analysis",
    }
    OWNER_PREFIX = "modules/amazon_sp/"      # 表 + 数据源实现的所有者，豁免
    REPO_FILE = "modules/amazon_sp/snapshot_repo.py"

    def names_of(tree) -> set:
        out = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        out |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        # ★ import 引入的名字是 ast.alias，不是 ast.Name —— 不单独收会漏掉
        #   「只 import 没调用」的形态（这条是上轮反向注入逼出来的）。
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                out |= {a.name for a in node.names}
            elif isinstance(node, ast.Import):
                out |= {a.name.rsplit(".", 1)[-1] for a in node.names}
        return out

    banned_hits: list = []
    loader_defs: list = []
    entry_import: dict = {rel: False for rel in consumers}
    repo_tree = None
    scanned = 0

    for p in sorted(modules.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(backend).as_posix()
        tree = ast.parse(p.read_bytes().decode("utf-8").replace("\r\n", "\n"))
        scanned += 1

        if rel == REPO_FILE:
            repo_tree = tree

        # ① 全仓（除所有者）不得再出现「经工厂取竞品」的名字
        if not rel.startswith(OWNER_PREFIX):
            nm = names_of(tree)
            for banned in ("fetch_competitors", "MockAmazonDataSource"):
                if banned in nm:
                    banned_hits.append(f"{rel}: {banned}")

        # ④ 谁还定义着 _load_competitor_rows
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "_load_competitor_rows"):
                loader_defs.append(f"{rel}:{node.lineno}")

        # ② 消费方是否走了唯一入口
        if rel in entry_import:
            for node in ast.walk(tree):
                if (isinstance(node, ast.ImportFrom)
                        and node.module == "modules.amazon_sp"
                        and any(a.name == "load_competitor_snapshots" for a in node.names)):
                    entry_import[rel] = True

    assert scanned >= 40, f"只扫到 {scanned} 个 modules 文件，扫描路径可疑"
    assert repo_tree is not None, f"{REPO_FILE} 不存在 —— 取数入口被挪走了？"

    assert not banned_hits, (
        "以下位置又出现了「经数据源工厂取竞品」的实现 —— 无 SP-API 凭据时会静默"
        "回退 Mock 并现编竞品，与监控池的真源零交集。请改为调用 "
        "`from modules.amazon_sp import load_competitor_snapshots`：\n"
        + "\n".join(f"  {h}" for h in banned_hits))

    missing = sorted(r for r, ok in entry_import.items() if not ok)
    assert not missing, (
        "以下消费方没有走唯一入口 `modules.amazon_sp.load_competitor_snapshots`：\n"
        + "\n".join(f"  {m}" for m in missing))

    repo_names = names_of(repo_tree)
    assert "CompetitorSnapshot" in repo_names, "取数入口没有查竞品快照表"
    assert "select" in repo_names, "取数入口没有用 select 查表"
    assert _has_store_id_filter(repo_tree), (
        "取数入口没有按 `.store_id` 过滤 —— 那是**跨租户泄漏**，不是内部实现细节")

    defs_files = sorted({d.split(":")[0] for d in loader_defs})
    assert defs_files == sorted(consumers), (
        f"`_load_competitor_rows` 的定义出现在 {defs_files}；"
        f"只允许两个消费方各一份（{sorted(consumers)}）—— 多一处就是又开了一份实现")

    assert inspect.iscoroutinefunction(mod_ci._load_competitor_rows), (
        "competitor_intel 取数层必须是 async —— 改回同步说明它又没在查库")
    assert inspect.iscoroutinefunction(mod_ad._load_competitor_rows), (
        "ad_analysis 取数层必须是 async —— 改回同步说明它又没在查库")

    # 自检：确认扫描真的看到了东西（防「目录写错 ⇒ 空集 ⇒ 恒绿」）
    assert loader_defs, "一条 _load_competitor_rows 定义都没扫到，扫描逻辑可疑"


def test_ad_analysis_collapses_daily_rows_to_one_per_competitor():
    """★ 探针挖出的真缺陷：`ad_analysis` 必须把**逐日行**收敛成「每 ASIN 一行」。

    症状：6 个竞品的池子 → `_analyze_competitors` 返回 **126 条**（同一 ASIN 每天
    一条），ΣSOV = 42 而不是 ~100 —— 份额分母被撑大 21 倍。

    根因：`amazon_competitor_snapshots` 是逐日行，而
    `_competitor_data_from_rows()` 按**每一行**生成一个 `CompetitorAdData`。
    改造前 mock 的 `fetch_competitors()` 同样返回时序（每 2 天一个点），
    所以旧实现也产出 ~90 条 —— 这是**改造前就存在**的缺陷，本次改造只是把
    行数从「每 2 天」变成「每天」，把它放大了。

    为什么是纯函数用例（不需要库）：收敛逻辑是纯函数，行为可直接钉住；
    端到端那条另有探针（`.workbuddy/probes/p172_ad.py`）跑真库验证。
    """
    from modules.ad_analysis.agent_ad import _latest_row_per_asin

    def row(asin, day, bsr):
        return {"competitor_asin": asin, "snapshot_date": day, "bsr_rank": bsr,
                "review_count": 100, "rating": 4.5}

    rows = []
    for asin in ("B0MONBRD01", "B0MONPRO01", "B0MONPRO02"):
        for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
            rows.append(row(asin, day, 100))
    # 故意打乱顺序，并给一个没有日期 / 没有 ASIN 的脏行
    rows = list(reversed(rows)) + [{"competitor_asin": "", "snapshot_date": day}]

    out = _latest_row_per_asin(rows)
    assert len(out) == 3, f"应收敛成 3 个竞品（每 ASIN 一行），实际 {len(out)}"
    assert {r["competitor_asin"] for r in out} == {"B0MONBRD01", "B0MONPRO01", "B0MONPRO02"}
    assert all(r["snapshot_date"] == "2026-09-03" for r in out), "必须取最新一行"
    assert all(r["bsr_rank"] == 100 for r in out)

    # 空输入 / 全脏行不得炸
    assert _latest_row_per_asin([]) == []
    assert _latest_row_per_asin([{"competitor_asin": None}]) == []


def test_ad_analysis_loads_competitors_through_the_deduping_exit():
    """形态门禁：`ad_analysis` 的取数出口必须经过收敛，而不是把时序直接返回。

    ★ 走 AST 而不是字符串包含：本仓铁律 —— docstring 里写一句
      `_latest_row_per_asin(rows)` 就能骗过字符串判据。
      这里要的是 `_load_competitor_rows` 函数体里**真的有一次调用**。
    """
    import ast

    from modules.ad_analysis import agent_ad as mod_ad

    tree = ast.parse(inspect.getsource(mod_ad))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "_load_competitor_rows"), None)
    assert fn is not None, "ad_analysis 的 _load_competitor_rows 不见了"
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_latest_row_per_asin" in called, (
        "取数出口没有收敛逐日行 ⇒ 同一竞品会被重复 N 次、份额分母被撑大")
    assert "load_competitor_snapshots" in called, "取数出口没有走唯一入口"


def test_seed_expands_monitors_without_randomness():
    """
    种子数据必须**零随机**：同一份监控池展开两次结果必须逐字节相同。

    `monitors` 的时序本身是确定性伪随机（FNV-1a，ASIN 作种子），
    展开成快照行的过程更不许引入 `random` —— 否则"同一店铺两次请求
    看到的竞品历史不同"这个被修掉的毛病会以另一种形式复活。
    """
    import random as _random

    from modules.amazon_sp import seed as seed_mod
    from modules.monitors.seed import SEED_SPECS, build_seed_record

    assert "import random" not in inspect.getsource(seed_mod), "种子模块引入了 random"

    monitor = build_seed_record(SHOP, SEED_SPECS[0], 0)
    a = seed_mod.build_snapshot_rows(monitor)
    b = seed_mod.build_snapshot_rows(monitor)
    assert len(a) == len(b) > 0
    for x, y in zip(a, b):
        assert (x.snapshot_date, x.price, x.bsr_rank, x.review_count, x.rating,
                x.price_change) == (
                y.snapshot_date, y.price, y.bsr_rank, y.review_count, y.rating,
                y.price_change)
    # 展开方不能碰全局随机状态
    _random.seed(0)
    first = _random.random()
    seed_mod.build_snapshot_rows(monitor)
    _random.seed(0)
    assert _random.random() == first, "展开过程移动了全局随机状态 ⇒ 里面有 random"


def test_seed_leaves_unavailable_dimensions_null():
    """
    快照表里 `monitors` 没提供的维度必须留 NULL，不许用别处数据凑。

    三列刻意留空：`has_buybox` / `buybox_price` / `fulfillment`
    （外加 `price_vs_own`，它需要"自研产品价格"，也不在这条数据通路上）。
    为什么值得一条独立用例：这三项都是可以被用户拿去决策的商业事实，
    塞一个"看起来合理"的值比留空危险得多。
    """
    from modules.amazon_sp.seed import build_snapshot_rows
    from modules.monitors.seed import SEED_SPECS, build_seed_record

    rows = build_snapshot_rows(build_seed_record(SHOP, SEED_SPECS[0], 0))
    assert rows, "展开结果为空"
    for r in rows:
        assert r.has_buybox is None
        assert r.buybox_price is None
        assert r.fulfillment is None
        assert r.price_vs_own is None
    # 有真值的列必须真的填了
    assert rows[0].competitor_asin == SEED_SPECS[0]["asin"]
    assert rows[0].brand == SEED_SPECS[0]["brand"]
    assert rows[0].main_image_url == SEED_SPECS[0]["image"]


def test_seed_backcast_lands_exactly_on_the_pool_values():
    """
    回推算法必须**逐日闭环**，不能只对终点。

    ★ 这条判据是被反向注入逼出来的。第一版只断言"最后一天 == 池子当前值"，
      注入「回推窗口漏掉一天增量」后**门禁不红** —— 因为 `i` 取到最后一天时，
      `events[i+1:]` 本来就是空切片，终点恒等于当前值。
      终点对 ≠ 过程对。所以现在钉三件事：

      ① 终点闭合：最后一天的 review_count / rating 精确等于 `monitors` 的当前值；
      ② 逐日闭环：任意相邻两天的评论差 == 那一天 `review_events` 的 `added`
         （口径断言，不是把实现抄一遍）；
      ③ 单调不减：评论数不会被"撤回"。
    """
    from modules.amazon_sp.seed import build_snapshot_rows
    from modules.monitors.seed import SEED_SPECS, build_seed_record

    for idx, spec in enumerate(SEED_SPECS):
        monitor = build_seed_record(SHOP, spec, idx)
        rows = build_snapshot_rows(monitor)
        assert rows, f"{spec['asin']} 展开结果为空"

        # ① 终点闭合
        assert rows[-1].review_count == monitor.review_count, (
            f"{spec['asin']} 评论数回推未闭合: {rows[-1].review_count} != {monitor.review_count}")
        assert abs(rows[-1].rating - monitor.rating) < 0.051, (
            f"{spec['asin']} 评分回推未闭合: {rows[-1].rating} != {monitor.rating}")

        # ② 逐日增量必须等于当天事件（漏一天/多一天都会在这里露出来）
        added_by_date = {
            str(e.get("date")): int(e.get("added") or 0)
            for e in (monitor.review_events or [])
        }
        for prev, cur in zip(rows, rows[1:]):
            day = cur.snapshot_date.date().isoformat()
            delta = cur.review_count - prev.review_count
            assert delta == added_by_date.get(day, 0), (
                f"{spec['asin']} {day} 评论增量 {delta} != 事件里的 "
                f"{added_by_date.get(day, 0)} —— 回推窗口错位")

        # ③ 单调不减
        counts = [r.review_count for r in rows]
        assert counts == sorted(counts), f"{spec['asin']} 评论数出现回退: {counts}"


# ====== 已知问题（未改代码，标注出来供决策） ======
#
# 1) `/compare` 的 400 分支不可达（见 test_compare_single_asin_rejected_by_schema_not_router）。
# 2) 顶层 `intent` 字段恒为 ""（真实意图只在 `data.intent`）。
# 3) `_classify_intent` 永不返回 "general"，导致
#    a. `handlers.get(intent, self._general_analysis)` 的兜底分支不可达；
#    b. `stream_chat` 里 `if intent != "general"` 恒为真 → **LLM 流式分支是死代码**，
#       `/chat/stream` 实际只把结构化结果包了一层 SSE（其他 Agent 是真流式）。
# 4) ★ `/monitor` 的 `days` 参数**从未到达数据层**：
#       days=7 / 30 / 90 → price_trend 长度与 price_change_7d 完全相同。
#    根因：`service.monitor_competitor` 组 context 时没带 `days`，
#    `_ensure_source` 于是恒取 `f"{ctx.get('days') or 30}d"` = "30d"。
#    ★ 第 172 轮更新：取数改读库后，`days` 会直接决定 SQL 的时间窗口，
#      但**接通它需要先解决第二个问题** —— `_calculate_price_change(asin, 7)`
#      在窗口内不足 8 个快照点时 `return 0.0`，于是 7 天窗口会显示
#      「价格变动 0%」，又是一个「静默 0 = 假数据」的坑。
#      故本轮**只换真源、不动 days 口径**，保留给产品决策。
# 5) ★ 种子数据的时效性：`monitors` 的 30 天时序以「seed 运行当日」为基准生成，
#    因此 seed 满 30 天后查询窗口会完全滑出、各端点变 `no_data`。
#    这是**演示数据**的固有性质（测试夹具每次重新生成，故测试不受影响）；
#    接入真实 SP-API 每日抓取后不再存在。

# 已修（第 142 轮，保留记录以免有人改回去）：
# 6) 未知 ASIN 的信封自相矛盾（success=true + data.error + message「成功」）
# 7) 单品监控的 message 说「成功获取 0 个竞品」而 payload 里有完整 product


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
    钉住「无 general 意图」这个事实（回退分支里的 `general` 一段不可达）。

    ★ 第 198 轮**更正表述**：改造前这里写的理由是「它让 stream_chat 的 LLM
      分支成为死代码」。现在对话通道改为**先走工具环路**
      （`_route_via_tools`，LLM 用 bind_tools 自己选那 3 个竞品工具），只有
      环路不可用（`ENABLE_LLM=False` / 无 KEY / 建图失败）时才回退到本关键词
      路由。也就是说 `stream_chat` 的 **LLM 流式分支依然不可达** —— 它被工具
      环路**取代**，而不是被修通。断言本身不变（它钉的是一条事实），
      变的是它解释的是哪条路径。
    """
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent

    agent = CompetitorIntelligenceAgent()
    for q in ["你好", "随便问问天气", "今天有什么新闻", "帮我看看"]:
        assert agent._classify_intent(q) != "general"


# ============================================================================
# 第 198 轮：competitor_intel 从「范式 B（关键词路由、零工具）」
#             迁到「范式 A（`_build_router()` + LLM 自主 bind_tools）」
# ============================================================================


def test_agent_builds_a_tool_router_with_its_tools(monkeypatch):
    """★ 接线钉子：`_build_router()` 必须真的把它当前那 3 个工具装上。

    ★ 为什么必须断言「模型手里真有工具」，而不是「代码里写了 tools=」：
      工具只在 `BaseAgent._llm_with_tools()` 里被 `bind_tools`，而它只被图节点
      `_llm_call_node` 调用。本 Agent 的 `analyze()` 从不驱动那张图 ⇒
      只给 `super().__init__()` 加 `tools=` 是**装饰性接线**：
      注册表不再「悬空」、门禁变绿，而模型手里依旧没有工具 —— 比不接更糟，
      因为它把缺口藏起来了。

    ★★★ 第 198 轮实测：本用例初版**必红**，而且红得毫无信息量
      （`assert None is not None`）。根因**不在产品代码**，在本文件的 autouse
      夹具 `no_llm` —— 它为了让本模块全部用例确定性降级，把
      `CompetitorIntelligenceAgent.ENABLE_LLM` 统一摁成 `False`；
      而 `_build_router()` 的第一行正是 `if not self.ENABLE_LLM: return None`。
      ⇒ 这里必须**显式重新打开**，并断言「真的开了」。

      ★ 一般教训：**模块级 autouse 夹具关掉的能力开关，在同模块里新增
        「验证该能力已接好」的用例时必须显式重开** —— 否则新用例一出生就是红的，
        而且报错指向产品代码（`_build_router()` 返回 None），归因方向完全错。
    """
    from modules.competitor_intel.agent_competitor import CompetitorIntelligenceAgent
    from modules.competitor_intel.tools import competitor_intel_tools

    monkeypatch.setattr(CompetitorIntelligenceAgent, "ENABLE_LLM", True)
    assert CompetitorIntelligenceAgent.ENABLE_LLM is True, (
        "`no_llm` 夹具在用例体之后又摁了一次 —— 下面的断言会退化成空跑"
    )

    router = CompetitorIntelligenceAgent()._build_router()
    assert router is not None, (
        "路由子层没建起来。ENABLE_LLM 已在本用例内显式打开 ⇒ 这不是"
        "「环境关了 LLM」，而是 `_build_router()` 的装配真的抛了异常"
        "（异常被吞成日志，按关键词 `router build failed` 去捞）。"
    )

    business = {t.name for t in competitor_intel_tools}
    # ★ 第 207 轮：8 → 3（退役 5 条 —— 见 `modules/competitor_intel/tools.py`
    #   文件头的退役说明；只退役工具包装，能力方法与端点全部保留）。
    assert business == {
        "analyze_pricing_strategy",
        "analyze_competitor_reviews",
        "compare_competitors",
    }, f"注册表本身漂了：{sorted(business)}"

    names = {t.name for t in router.tools}
    assert business <= names, f"路由子层漏装工具：{sorted(business - names)}"
    # ★ 子层恒带一个技能按需加载工具（`load_skill`）⇒ 只允许它多出来。
    #   口径同 `test_secretary_agent.py`（那里断言 `len(router.tools) == 9`）。
    assert names - business == {"load_skill"}, (
        f"子层多出了非预期工具：{sorted(names - business)}"
    )

    assert router.checkpoint_namespace == "competitor_intel", (
        "会话命名空间与别的 Agent 混了 —— 同一 thread_id 会跨 Agent 串味"
        "（BaseAgent 上的真名是 `checkpoint_namespace`，不是构造参数名）"
    )
    assert router.agent_name.endswith("_router"), (
        "子层名不带 `_router` ⇒ `agents.business_agent_name()` 的归一失配 "
        "⇒ 技能目录/正文在该通道上静默不注入"
    )


class _ServiceRecorder:
    """把 service 换成记录器：只关心**归属有没有被传下去**，不真跑业务。"""

    def __init__(self):
        self.seen: list = []

    def __getattr__(self, name):
        async def _call(req, store_id=None):
            self.seen.append((name, store_id))
            return {"type": "probe", "success": True}

        return _call


async def test_all_competitor_tools_carry_shop_attribution(monkeypatch):
    """★★★ 3 个工具都必须把 ContextVar 里的店铺归属透传给 service。

    ★ 这条钉的是一个**从未暴露过的潜伏缺陷**（第 198 轮接线时才现形）：
      竞品工具改造前**一个都没传 `store_id`** ⇒ `CompetitorIntelService`
      收到 `None` ⇒ `_ensure_source()` 直接判 `no_data`（理由「未绑定店铺上下文
      （请求缺少 X-Shop-ID）」）⇒ 工具**永远拿不到数据**。
      缺陷此前不可见的原因正是「注册表悬空、没有任何 Agent 装配它们」
      —— 「先接线、再谈效果」这一步才把它照出来。

    ★ 归属只走 ContextVar（**服务端注入**），不是工具形参：
      做成形参等于让模型决定租户边界（同族判据：归属只能服务端注入）。
    """
    import modules.competitor_intel.tools as T
    from modules.competitor_intel.agent_competitor import _current_shop_id

    rec = _ServiceRecorder()
    monkeypatch.setattr(T, "_service", rec)

    # ★ 第 207 轮：8 → 3（退役 5 条）。这是**行为面**的清单，
    #   必须跟着注册表走 —— 否则它引用的函数已不存在，用例直接 AttributeError。
    cases = [
        (T._analyze_pricing_strategy_tool, {}),
        (T._analyze_competitor_reviews_tool, {"asin": "B0TEST0001"}),
        (T._compare_competitors_tool, {"asins": ["B0TEST0001", "B0TEST0002"]}),
    ]
    token = _current_shop_id.set("shop-probe-A")
    try:
        for fn, kwargs in cases:
            await fn(**kwargs)
    finally:
        _current_shop_id.reset(token)

    assert len(rec.seen) == 3, f"3 个工具应各调一次 service，实得 {len(rec.seen)}"
    missing = [name for name, sid in rec.seen if sid != "shop-probe-A"]
    assert not missing, (
        f"这些工具没把归属传下去：{missing}\n"
        f"⇒ service 收到 None 会直接判 no_data，工具永远拿不到数据，"
        f"而且理由是「请求缺少 X-Shop-ID」（把排查引向一个不存在的问题）。"
    )


async def test_competitor_tools_fail_closed_without_shop(monkeypatch):
    """反向面：没有店铺上下文时**照传 None**，不许兜一个默认店铺。

    ★ 与上一条成对（「修 bug 不许修过头」）：补归属很容易顺手写成
      「没有就编一个默认店铺」—— 那会把竞品数据读到**不属于任何人的店铺**上，
      比读不到危险得多。
    """
    import modules.competitor_intel.tools as T
    from modules.competitor_intel.agent_competitor import _current_shop_id

    rec = _ServiceRecorder()
    monkeypatch.setattr(T, "_service", rec)

    token = _current_shop_id.set(None)
    try:
        await T._analyze_pricing_strategy_tool()
    finally:
        _current_shop_id.reset(token)

    assert rec.seen == [("analyze_pricing_strategy", None)], (
        f"无店铺时不该伪造归属：{rec.seen}"
    )


def test_every_service_call_in_tools_passes_store_id():
    """★ 形态判据：`tools.py` 里**每一处** `_service.xxx(...)` 都必须带 `store_id=`。

    ★ 为什么上面那条行为判据不够：它只覆盖**今天这 3 个**。将来往注册表里加
      第 4 个工具而忘了传归属 —— 它同样「永远拿不到数据」，
      而行为判据看不见它（它遍历的是写死的那 3 个函数）。
    """
    import ast as _ast
    import pathlib as _pathlib

    rel = _pathlib.Path(__file__).resolve().parents[1] / "modules/competitor_intel/tools.py"
    tree = _ast.parse(rel.read_text(encoding="utf-8"))
    total, with_shop = 0, 0
    for n in _ast.walk(tree):
        if not isinstance(n, _ast.Call):
            continue
        fn = n.func
        if not (isinstance(fn, _ast.Attribute) and isinstance(fn.value, _ast.Name)
                and fn.value.id == "_service"):
            continue
        total += 1
        if any(kw.arg == "store_id" for kw in n.keywords):
            with_shop += 1

    assert total == 3, f"tools.py 里对 _service 的调用应有 3 处，实得 {total}"
    assert total == with_shop, (
        f"{total - with_shop} 处 `_service.xxx(...)` 没有传 `store_id` —— "
        f"那类工具会永远返回 no_data，理由还是「请求缺少 X-Shop-ID」（归因错误）"
    )


# ====== 十二、装载缓存不变量（第 210 轮）======
#
# 为什么单列一节：本 Agent 由 `service._get_agent()` 持有，是**进程内单例**
#   （`service.py:59`）⇒ 任何被「记住」的结论都作用于**整个进程**，不是这一次请求。
# 两条不变量各对应一次实测事故（证据：`.workbuddy/probes/210_ab_verdict.txt`）：
#   · **负结果被永久记住** ⇒ 用户照空状态提示补了竞品池，再问**照样**「暂无数据」；
#   · **缓存 key 比它的数据活得久** ⇒ 回到旧店铺会命中「key 相等、却对着空 dict」
#     的短路，返回 False 且理由还是**另一个店铺**的
#     （实测把本文件从 62 绿打成 33 红）。


async def test_empty_load_is_not_cached_forever(monkeypatch):
    """空结果**不进缓存**：用户按提示补了竞品池之后，下一次调用必须重新取数。"""
    from modules.competitor_intel import agent_competitor as ac

    calls = {"n": 0}

    async def fake_load(store_id, time_range="30d", asins=None):
        calls["n"] += 1
        return []

    monkeypatch.setattr(ac, "_load_competitor_rows", fake_load)
    agent = ac.CompetitorIntelligenceAgent()
    ctx = {"store_id": "probe-round-210"}

    assert await agent._ensure_source(ctx) is False
    assert agent._loaded_key is None, "空结果被写进了装载缓存 —— 整个进程都会看不到数据"
    assert await agent._ensure_source(ctx) is False
    assert calls["n"] == 2, (
        f"第二次调用没有真正取数（取数次数 {calls['n']}）—— "
        "用户照空状态提示补了竞品池，也会得到同一句「暂无数据」"
    )


async def test_cache_key_never_outlives_its_payload(monkeypatch):
    """★ 回归门禁：`_loaded_key` 与装载出来的数据必须**同生共死**。"""
    from modules.competitor_intel import agent_competitor as ac

    async def fake_load(store_id, time_range="30d", asins=None):
        return [] if store_id == "EMPTY" else [{"competitor_asin": "B0PROBE000"}]

    monkeypatch.setattr(ac, "_load_competitor_rows", fake_load)
    agent = ac.CompetitorIntelligenceAgent()
    # 装载本体需要完整行结构；本用例只关心**缓存不变量** ⇒ 用替身顶掉
    monkeypatch.setattr(
        agent, "_build_from_rows",
        lambda rows: agent._competitor_db.update({"B0PROBE000": {"asin": "B0PROBE000"}}),
    )

    assert await agent._ensure_source({"store_id": "HAS"}) is True
    assert agent._loaded_key == ("HAS", "30d")

    # 换一家**空**店铺：dict 被清空
    assert await agent._ensure_source({"store_id": "EMPTY"}) is False
    assert agent._loaded_key is None, (
        "缓存 key 比它的数据活得久 —— 回到 HAS 会命中「key 相等、却对着空 dict」"
        "的短路并返回 False，而 _data_reason 还是 EMPTY 的（用户看到别人的店铺名）"
    )

    # 回到 HAS 必须**重新取数**并成功
    assert await agent._ensure_source({"store_id": "HAS"}) is True

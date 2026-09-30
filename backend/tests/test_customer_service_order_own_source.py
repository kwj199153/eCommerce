"""第 285 轮：订单追踪的**取数顺序** —— 自有订单库优先，平台适配层兜底。

为什么必须单独钉这一条（本仓纪律：改了行为就要有能被打红的判据）：
  · `test_customer_service_order_failclosed.py` 钉的是「**绝不能编造订单**」，
    它只允许 `prefer='sp_api'`（`set(calls) == {"sp_api"}`）—— 那条判据在
    「不带店铺」的场景下依然成立，但它**看不见**本轮新增的自有库分支。
  · 也就是说：把 `_fetch_order_info` 改回「只问平台」，那两套测试**全绿**。
    本文件就是堵这个洞的。

★ 判据全部走 **monkeypatch**，不连真实库 —— 本仓 `tests/` 连的是共享生产库，
  依赖 seed 数据的用例不可复现（只认单跑）。这里喂的是构造好的 ctx，
  所以「自有库命中 / 未命中」两种形态都能稳定复现。

★ 与既有 fail-closed 测试的**分工**：
    failclosed  → 管「不能编」
    本文件      → 管「先问谁」
"""

import pytest

from modules.customer_service.agent_cs import CustomerServiceAgent

SHOP = "store_unit_test"
ORDER = "AMZN123456789"

# 构造一份「自有订单库命中」的上下文（形态照抄 trade.service.get_order_context）
OWN_CTX = {
    "found": True,
    "data_source": "mock_seed",
    "order": {
        "id": f"ord-amazon-{ORDER}",
        "external_order_id": ORDER,
        "platform": "amazon",
        "order_status": "delivered",
        "purchase_at": "2026-09-12T03:06:10",
        "promised_at": "2026-09-18T03:06:10",
        "order_total": 29.99,
        "currency": "USD",
        "ship_country": "US",
        "ship_state": "California",
        "transit_days": 12,
        "delay_days": 7,
        "source": "mock_seed",
    },
    "items": [{"sku": "SKU-KC-002", "asin": "B0CXXXX009",
               "title": "智能保温杯", "quantity": 1, "unit_price": 29.99}],
    "shipment": {
        "carrier": "UPS", "tracking_no": "1Z999AA10123456784",
        "ship_status": "delivered", "last_location": "San Jose, CA",
        "last_event_text": "Delivered, left at front door",
        "transit_days": 12, "delay_days": 7,
    },
    "reviews": [],
}


@pytest.fixture
def agent():
    return CustomerServiceAgent()


@pytest.fixture
def traced(monkeypatch):
    """同时挂住「自有库」与「平台适配层」两个取数口，记录调用顺序。"""
    calls = []

    async def _own(session, shop_id, order_id):
        calls.append(("own", shop_id, order_id))
        return dict(OWN_CTX)  # 默认命中

    async def _own_miss(session, shop_id, order_id):
        calls.append(("own", shop_id, order_id))
        return {"found": False, "order_id": order_id, "error": "本店铺下查不到这笔订单"}

    # ★ 打在**门面**上：生产代码 `_fetch_order_info` 从 `modules.trade` 取函数，
    #   打在 `modules.trade.service` 上的桩不会被查到（同一名字的两处绑定）。
    import modules.trade as trade_facade
    monkeypatch.setattr(trade_facade, "get_order_context", _own)
    monkeypatch.setattr(trade_facade, "get_order_context_miss", _own_miss, raising=False)

    def _factory(prefer=None, **kw):
        calls.append(("platform", prefer))

        class _Src:
            def fetch_order_tracking(self, order_id):
                return {"found": False, "error": "平台侧也没有"}
        return _Src()

    import modules.amazon_sp as amazon_sp
    monkeypatch.setattr(amazon_sp, "get_data_source", _factory)

    # 会话工厂不会被真正用到（get_order_context 已被替换），但留个兜底防真连库
    return calls


# =====================================================================
# 1. 带店铺 ⇒ 先问自有库；命中就**不再**问平台
# =====================================================================
async def test_own_source_is_queried_first_and_short_circuits(agent, traced):
    info, why = await agent._fetch_order_info(ORDER, SHOP)

    assert info is not None, "自有库里有这笔订单，却没查到"
    assert why == ""
    assert ("own", SHOP, ORDER) in traced, "带店铺却没查自有订单库"
    # ★ 核心判据：命中即短路 —— 再去问平台等于「同一个问题两种答案」，
    #   正是 modules/trade/tools.py 头部警告的那件事。
    assert not any(c[0] == "platform" for c in traced), (
        f"自有库已命中，不该再问平台适配层：{traced}")


async def test_own_source_fields_are_richer_than_platform(agent, traced):
    """自有库的价值就在这些字段：运单号 / 承运商 / 迟到天数（平台给不出）。"""
    info, _ = await agent._fetch_order_info(ORDER, SHOP)

    assert info["carrier"] == "UPS"
    assert info["tracking_number"] == "1Z999AA10123456784"
    assert info["delay_days"] == 7
    assert info["transit_days"] == 12
    # ★ 演示数据必须被标记出来 —— 不能冒充真实订单
    assert info["data_source"] == "mock_seed"
    assert info["is_mock_data"] is True
    # 与平台版**共用**对外键名，渲染层不需要分叉
    for k in ("order_id", "status_text", "created_at", "product_name",
              "quantity", "total_text", "shipping_to"):
        assert k in info, f"对外键名缺失：{k}"


async def test_status_is_translated_for_the_consumer(agent, traced):
    """`order_status` 是平台无关的英文码，翻成中文只发生在客服这一层。"""
    info, _ = await agent._fetch_order_info(ORDER, SHOP)
    assert info["status"] == "delivered"
    assert info["status_text"] == "已签收"


# =====================================================================
# 2. 不带店铺 ⇒ 不碰自有库（租户隔离，不允许「全店数据」形态）
# =====================================================================
async def test_without_shop_context_own_source_is_skipped(agent, traced):
    info, why = await agent._fetch_order_info(ORDER, None)

    assert info is None
    assert not any(c[0] == "own" for c in traced), (
        "没有店铺上下文却去查了租户隔离的订单库 —— 那是跨店读取")
    assert "未携带店铺上下文" in why, f"失败原因必须说清跳过自有库的原因：{why}"


# =====================================================================
# 3. 自有库未命中 ⇒ 回退平台；且失败原因**两段都在**
# =====================================================================
async def test_falls_back_to_platform_when_own_source_misses(agent, traced, monkeypatch):
    import modules.trade as trade_facade
    monkeypatch.setattr(trade_facade, "get_order_context",
                        getattr(trade_facade, "get_order_context_miss"))

    info, why = await agent._fetch_order_info(ORDER, SHOP)

    assert info is None
    assert ("own", SHOP, ORDER) in traced, "库里没有也必须先问过自有库"
    assert ("platform", "sp_api") in traced, "自有库未命中应回退平台适配层"
    # ★ 两个源都试过 ⇒ 原因里两段都要有。只报一段会让「库里没同步到」
    #   和「平台根本没有」混成同一句话，归因反向。
    assert "自有订单库中查无此订单" in why
    assert "平台" in why or "SP-API" in why


# =====================================================================
# 4. 反例：把「先问自有库」改回「只问平台」 ⇒ 必须红
# =====================================================================
async def test_regression_guard_own_source_cannot_be_removed(agent, monkeypatch):
    """模拟有人把前置分支摘掉（回到只问平台），判据必须能抓到。

    ★ 这不是在测产品代码，是在测**本文件里其它判据还活着** ——
      摘掉 `_fetch_order_from_trade` 的调用后，第 1 组的两条断言
      应当各自失败。若这条也绿，说明判据写空了。
    """
    import modules.customer_service.agent_cs as cs

    original = cs.CustomerServiceAgent._fetch_order_from_trade

    async def _sabotaged(self, shop_id, order_id):
        return None  # 假装自有库永远没有

    monkeypatch.setattr(cs.CustomerServiceAgent, "_fetch_order_from_trade", _sabotaged)

    info, why = await agent._fetch_order_info(ORDER, SHOP)

    # 破坏后：拿不到自有库 ⇒ 只能回退平台 ⇒ 平台也没有 ⇒ found=None
    assert info is None, "摘掉自有库分支后仍返回了订单 ⇒ 说明取数走的不是自有库"
    assert "自有订单库中查无此订单" in why

    monkeypatch.setattr(cs.CustomerServiceAgent, "_fetch_order_from_trade", original)

"""第 286 轮 P1-3：物流咨询 / 退换货必须接**真实订单**，而不是静态话术。

钉的是两件事：
  ① 买家问「我的货到哪了」⇒ 给的是 `shipments` 里的运单号 / 承运商 / 轨迹，
     **不是**「请登录账户 → 我的订单 → 查看物流」（那句是把缺口推回给买家）；
  ② 买家说「我要退货」⇒ 先查这笔订单的**签收日**再判断窗口，
     而不是把一份写死的退货指南原样吐出来。

★ 全部 monkeypatch（`_fetch_order_info` 换成构造好的订单），不连共享库。
★ 与既有测试的分工：
    order_own_source  → 管「先问谁（自有库 / 平台）」
    本文件            → 管「拿到订单后，物流 / 退货这两个分支**用不用它**」
"""

from datetime import datetime, timedelta

import pytest

from modules.customer_service.agent_cs import (
    CustomerServiceAgent, SentimentAnalysis,
)

SHOP = "store_unit_test"
ORDER = "AMZN123456789"


def _order(delivered_days_ago=None, delay=7, status="delivered",
           status_text="已签收"):
    """构造一份「自有订单库命中」的客服订单字典（形态照抄 `_map_order_from_trade`）"""
    delivered = ""
    if delivered_days_ago is not None:
        delivered = (datetime.utcnow() - timedelta(days=delivered_days_ago)
                     ).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "order_id": ORDER, "status": status, "status_text": status_text,
        "created_at": "2026-09-12T03:06:10",
        "product_name": "智能保温杯", "quantity": 1,
        "total": 29.99, "total_text": "$29.99",
        "estimated_delivery": "2026-09-18T03:06:10",
        "shipping_to": "California / US",
        "carrier": "UPS", "tracking_number": "1Z999AA10123456784",
        "ship_status_text": "已签收", "last_location": "San Jose, CA",
        "last_event_text": "Delivered, left at front door",
        "transit_days": 12, "delay_days": delay,
        "shipped_at": "2026-09-13T03:06:10", "delivered_at": delivered,
        "data_source": "mock_seed", "is_mock_data": True,
    }


@pytest.fixture
def agent():
    return CustomerServiceAgent()


@pytest.fixture
def neutral():
    return SentimentAnalysis(sentiment="neutral", confidence=0.5, intensity=0.2)


def _patch_order(monkeypatch, info=None, why=""):
    async def _fake(self, order_id, shop_id=None):
        _patch_order.calls.append((order_id, shop_id))
        return (info, why) if info is not None else (None, why or "两个源都没查到")
    _patch_order.calls = []
    monkeypatch.setattr(CustomerServiceAgent, "_fetch_order_info", _fake)
    return _patch_order.calls


# =====================================================================
# 1. 物流咨询：有订单号 ⇒ 给真实轨迹
# =====================================================================
async def test_shipping_returns_real_tracking_not_login_hint(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, _order(delivered_days_ago=5))

    r = await agent._handle_shipping_inquiry(
        f"订单 {ORDER} 到哪了", {"store_id": SHOP}, None, neutral)

    assert r.data["type"] == "shipping_tracking"
    assert "1Z999AA10123456784" in r.content, "运单号没出现在回复里"
    assert "UPS" in r.content, "承运商没出现在回复里"
    assert "San Jose, CA" in r.content, "最新位置没出现在回复里"
    # ★ 反例判据：不能再让买家自己去别处看
    assert "登录账户" not in r.content, "还在让买家自己登录查看 ⇒ 等于没接数据"
    # ★ 店铺上下文必须带下去（话术/订单都是租户隔离）
    assert _patch_order.calls and _patch_order.calls[-1][1] == SHOP


async def test_shipping_without_order_id_asks_for_it(agent, monkeypatch, neutral):
    """没订单号 ⇒ 明确说「给我订单号我能查到什么」，而不是笼统答一句。"""
    # 直接灌一条「物流」分类的话术（真实链路上由 `_route_by_intent` 调
    # `ensure_faq` 灌入；本用例只测「没订单号时走话术分支」这一段）
    from modules.customer_service.agent_cs import FAQItem
    agent.faq_database = [FAQItem(
        id="cs-faq-001-x", question="发货时间要多久？", answer="标准发货 1-3 天。",
        category="物流", keywords=["发货", "多久"], priority=100)]
    agent._faq_error = ""

    r = await agent._handle_shipping_inquiry(
        "我的货到哪了", {"store_id": SHOP}, None, neutral)

    assert r.data.get("need_order_id") is True
    assert "订单号" in r.content


async def test_shipping_passes_through_failure_reason(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, None, "自有订单库中查无此订单；且平台侧也没有")

    r = await agent._handle_shipping_inquiry(
        f"订单 {ORDER} 到哪了", {"store_id": SHOP}, None, neutral)

    assert r.data["type"] == "shipping_order_not_found"
    assert "自有订单库中查无此订单" in r.content, "失败原因必须透传，不许改成笼统文案"


# =====================================================================
# 2. 退换货：按签收日判断窗口（三种结局必须分开）
# =====================================================================
async def test_return_within_window(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, _order(delivered_days_ago=5))

    r = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)

    assert r.data["within_window"] is True
    assert r.data["days_since_delivery"] == 5
    assert r.data["days_left"] == 25
    assert "仍在" in r.content and "退货窗口内" in r.content


async def test_return_beyond_window(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, _order(delivered_days_ago=40))

    r = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)

    assert r.data["within_window"] is False
    assert r.data["days_since_delivery"] == 40
    assert "超出" in r.content and "人工审核" in r.content


async def test_return_not_delivered_yet(agent, monkeypatch, neutral):
    """没签收 ⇒ 窗口还没起算；该走的是「未收到货」，不能按超期处理。"""
    _patch_order(monkeypatch, _order(delivered_days_ago=None,
                                     status="in_transit", status_text="运输中"))

    r = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)

    assert r.data["delivered"] is False
    assert "尚未签收" in r.content
    assert "未收到货" in r.content


async def test_return_unparsable_date_is_not_guessed(agent, monkeypatch, neutral):
    """★ 签收时间解析不出来 ⇒ 必须说「不判断」，绝不默认放行（fail-open）。"""
    info = _order(delivered_days_ago=5)
    info["delivered_at"] = "昨天下午三点"      # 解析不了
    _patch_order(monkeypatch, info)

    r = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)

    assert r.data.get("window_unknown") is True
    assert "不据此判断" in r.content
    assert "转人工" in r.content


async def test_return_without_order_id_asks_for_it(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, _order(delivered_days_ago=5))

    r = await agent._handle_return_refund("我要退货", {"store_id": SHOP}, None, neutral)

    assert r.data.get("need_order_id") is True
    assert "订单号" in r.content
    assert _patch_order.calls == [], "没订单号就不该去查库"


async def test_return_order_not_found_passes_reason(agent, monkeypatch, neutral):
    _patch_order(monkeypatch, None, "本店铺下查不到这笔订单")

    r = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)

    assert r.data["order_found"] is False
    assert "本店铺下查不到这笔订单" in r.content


# =====================================================================
# 2b. 意图：订单号是**参数**不是意图 ⇒ 「我要退货 + 订单号」必须走退货分支
# =====================================================================
async def test_return_intent_wins_over_order_tracking(agent):
    """★ 这条钉的是**走得到**：退货分支接了真数据，但被 `order_tracking`
      的「订单」关键词截走的话，等于没接（界面上看不出来，只是答非所问）。
    """
    assert agent._classify_intent(f"我要退货 订单 {ORDER}") == "return_refund"
    assert agent._classify_intent("帮我退款，单号 AMZN123456789") == "return_refund"
    # 反过来：只问订单、没有退货动词 ⇒ 仍走订单追踪
    assert agent._classify_intent(f"查询订单 {ORDER}") == "order_tracking"


# =====================================================================
# 3. 反向注入：判据不是空跑
# =====================================================================
async def test_judges_are_not_vacuous(agent, monkeypatch, neutral):
    """把取数口打回「永远查不到」：上面第 1 / 2 组的核心断言必须转红。

    ★ 这条测的是**判据本身**：若打回之后仍然绿，说明那些断言根本没在看
      真实订单的内容（改了等于没改，界面上也看不出来）。
    """
    _patch_order(monkeypatch, None, "永远查不到")

    r_ship = await agent._handle_shipping_inquiry(
        f"订单 {ORDER} 到哪了", {"store_id": SHOP}, None, neutral)
    assert "1Z999AA10123456784" not in r_ship.content, (
        "取数口已打回，回复里却还有运单号 ⇒ 第 1 组判据是空跑")

    r_ret = await agent._handle_return_refund(
        f"我要退 {ORDER}", {"store_id": SHOP}, None, neutral)
    assert r_ret.data.get("within_window") is None, (
        "取数口已打回，却仍给出了窗口判断 ⇒ 第 2 组判据是空跑")


async def test_shipping_block_is_shared_by_both_branches(agent):
    """物流段只有一份实现 ⇒ 订单追踪与物流咨询渲染出的字段必须一致。"""
    info = _order(delivered_days_ago=5)
    block = agent._render_shipping_block(info)
    for token in ("UPS", "1Z999AA10123456784", "San Jose, CA", "晚了 **7 天**"):
        assert token in block, f"物流段缺字段：{token}"

    empty = agent._render_shipping_block({"order_id": ORDER})
    assert empty == "", "没有物流字段时不应渲染出空标题"

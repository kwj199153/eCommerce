"""
订单查询 fail-closed 门禁（第 164 轮 #727 建立）。

背景 —— 修复前的形态：**编造订单号的闭环**
------------------------------------------
两个独立的编造点，串起来形成闭环：

1. `CustomerServiceService.track_order`：没有 `order_id` 时用
   `hash(email) % 10000` **现编**一个 `ORD-YYYYMMDDxxxxxxxx` 去查。
   那个号在平台侧不可能存在 —— 它唯一的「作用」是让「查不到」看起来像
   「查过了、没找到」。
2. `CustomerServiceAgent._mock_order_info`：8 处 `random.*` 生成
   状态（delivered/shipped/processing）、商品名（4 个英文商品）、
   数量、金额、**运单号 `1Z…` 与承运商**。

两点相乘的后果不是「数据难看」，而是**用户只给一个邮箱就会收到
`found=True` + 一张随机生成的订单表**（状态、商品、金额、运单号俱全）。
顺带：真实订单路径 `OrdersAPI.track_order` 从来没跑通过 —— 它读
`address["state_or_region"]`，而 `get_order_detail()` 构字典用的键名是
`state` ⇒ 任何带收货地址的订单都抛 `KeyError`，被 `except` 吞成
`found: False`。于是「真路径恒失败、假路径恒成功」。

本文件钉住的六件事
------------------
1. **拿不到真源 ⇒ 诚实说拿不到**，且回复里**零编造内容**
   （`test_without_credentials_reply_contains_no_fabricated_content`）。
2. **禁止 mock 回退**：不可用时只能试 `prefer="sp_api"`，
   绝不出现 `auto` / `mock`（否则又回到「静默假数据」）。
3. **映射层不补平台没给的字段**：`tracking_number` / `carrier`
   两个键**必须不存在**（平台不给就是不给）。
4. **没有订单号就不发起查询**（`agent.invoke` 一次都不许被调用）
   —— 这是「不假装查过」的正面判据。
5. **真路径真的能跑通**：`OrdersAPI.track_order` 带收货地址的订单必须
   `found=True`（反向注入：把 `state` 改回 `state_or_region` ⇒ 本用例变红）。
6. `agent_cs.py` 的 `random.*` 调用点**不得增长**（本地棘轮；
   全仓棘轮见 `tests/test_no_random_in_production.py`）。
"""

import ast
from pathlib import Path

import pytest

from pkg_source import source_files  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

#: 修复前 mock 会编出来的东西 —— 失败回复里出现任何一个都算回归
FABRICATED_MARKERS = [
    "1Z",                      # 运单号前缀
    "UPS", "FedEx", "USPS", "Amazon Logistics",   # 承运商池
    "Portable Coffee Grinder Pro", "Wireless Bluetooth Earbuds",
    "Smart Home Security Camera", "Stainless Steel Water Bottle",
    "$",                       # 金额
]

#: 修复前「编造订单号」的形态残留
FABRICATED_ID_MARKER = "ORD-"

ORDER_ID = "112-1234567-8901234"


def _patch_factory(monkeypatch, behavior):
    """把**门面**上的 `get_data_source` 换掉，并记录每次调用的 `prefer` 值。

    ★ 打桩必须打在 `modules.amazon_sp`（门面）上，不能打
      `modules.amazon_sp.data_sources`：生产代码按门禁 G-1 只从门面取名字，
      打在子模块上的桩**永远不被查到**（见 `test_facade_monkeypatch_targets.py`）。
    """
    calls: list[str] = []

    def fake(prefer="auto", **kwargs):
        calls.append(prefer)
        return behavior(prefer, **kwargs)

    import modules.amazon_sp as facade

    monkeypatch.setattr(facade, "get_data_source", fake)
    return calls


# ---------------------------------------------------------------- ① 诚实回复
async def test_without_credentials_reply_contains_no_fabricated_content(monkeypatch):
    """无凭据环境：回复必须说明真因，且**一个编造字段都不许出现**。"""

    def unavailable(prefer, **kwargs):
        raise RuntimeError("SP-API 数据源不可用: 缺少 SP-API 凭据（或仍为占位符）")

    _patch_factory(monkeypatch, unavailable)

    from modules.customer_service.agent_cs import CustomerServiceAgent

    resp = await CustomerServiceAgent()._handle_order_tracking(
        query=f"帮我查询订单 {ORDER_ID}", context=None, conv=None, sentiment=None,
    )

    assert resp.data is not None
    assert resp.data.get("type") == "order_not_found", (
        f"拿不到真源时必须走「查不到」分支，实际 type={resp.data.get('type')!r}"
    )
    assert resp.data.get("reason"), "必须把真实原因带出来（调用方要用它回话）"

    hits = [m for m in FABRICATED_MARKERS if m in resp.content]
    assert hits == [], f"失败回复里出现了编造内容 {hits}：\n{resp.content}"
    assert "未能查到" in resp.content


# ---------------------------------------------------------------- ② 禁 mock 回退
async def test_never_falls_back_to_the_mock_source(monkeypatch):
    """不可用时只能试 `sp_api`；出现 `auto` / `mock` 就是静默假数据回来了。"""

    def unavailable(prefer, **kwargs):
        raise RuntimeError("凭据缺失")

    calls = _patch_factory(monkeypatch, unavailable)

    from modules.customer_service.agent_cs import CustomerServiceAgent

    await CustomerServiceAgent()._handle_order_tracking(
        query=f"查询订单 {ORDER_ID}", context=None, conv=None, sentiment=None,
    )

    assert calls, "根本不查数据源 = 「编一份」没被修掉，而是被藏起来了"
    assert set(calls) == {"sp_api"}, f"订单查询只允许 prefer='sp_api'，实际 {calls}"


# ---------------------------------------------------------------- ③ 不补字段
async def test_mapping_does_not_invent_platform_missing_fields():
    """映射层只做改名/取首项，**不补**平台不返回的运单号与承运商。"""
    from modules.customer_service.agent_cs import CustomerServiceAgent

    raw = {
        "found": True,
        "current_status": {"code": "Shipped", "label": "已发货"},
        "purchase_date": "2026-09-01 10:20:30+00:00",
        "item_count": 3,
        "items": [
            {"title": "Portable Coffee Grinder Pro", "quantity": 2, "price": 12.34},
            {"title": "Wireless Bluetooth Earbuds", "quantity": 1, "price": 30.0},
        ],
        "order_total": {"amount": 54.68, "currency": "USD"},
        "shipping_to": "Seattle, WA",
        "estimated_delivery": "2026-09-04 ~ 2026-09-06",
    }
    info = CustomerServiceAgent._map_order_info(ORDER_ID, raw)

    assert "tracking_number" not in info, "Orders 接口不返回运单号，映射层不得凭空造一个"
    assert "carrier" not in info, "Orders 接口不返回承运商"
    assert info["status_text"] == "已发货"
    assert info["total_text"] == "$54.68"
    assert info["quantity"] == 3
    assert info["product_name"].startswith("Portable Coffee Grinder Pro")
    assert info["shipping_to"] == "Seattle, WA"

    # 边界：空明细 / 无金额 ⇒ 用占位符，不许退化成 $0.00
    empty = CustomerServiceAgent._map_order_info("X", {"found": True, "items": [], "order_total": {}})
    assert empty["product_name"] == "—" and empty["total_text"] == "—"
    assert empty["total"] is None, "没查到的金额必须是 None，不能是 0（0 会被渲染成 $0.00）"


# ---------------------------------------------------------------- ④ 不假装查
async def test_service_does_not_query_at_all_without_an_order_id(monkeypatch):
    """只给邮箱/手机号时：既不编订单号，也**不发起查询**。"""
    from modules.customer_service.agent_cs import CustomerServiceAgent
    from modules.customer_service.schemas import OrderTrackRequest
    from modules.customer_service.service import CustomerServiceService

    called: list[str] = []

    async def spy_invoke(self, query=None, context=None, **kwargs):
        called.append(str(query))
        raise AssertionError("没有订单号时不该发起任何查询")

    monkeypatch.setattr(CustomerServiceAgent, "invoke", spy_invoke)

    out = await CustomerServiceService.track_order(
        OrderTrackRequest(order_id=None, email="buyer@example.com", phone_last4=None)
    )

    assert called == [], f"未应发起查询，实际 {called}"
    assert out.found is False, "没有订单号却 found=True ⇒ 又回到「编造订单」"
    assert FABRICATED_ID_MARKER not in (out.message or ""), (
        f"文案里仍出现编造订单号的痕迹 {FABRICATED_ID_MARKER!r}：{out.message}"
    )
    assert "订单号" in (out.message or "")
    assert out.order is None


# ---------------------------------------------------------------- ⑤ 真路径可跑
async def test_real_track_order_path_survives_a_shipping_address():
    """`OrdersAPI.track_order` 带收货地址的订单必须 found=True。

    反向注入：把 `_format_shipping_to` 换回 `detail['shipping_address']['state_or_region']`
    ⇒ KeyError 被 except 吞掉 ⇒ found 变 False ⇒ 本用例变红。
    """
    from platforms.amazon.sp_api.orders import OrdersAPI

    api = OrdersAPI(client=None)  # type: ignore[arg-type]  # 本用例只走 detail 映射

    async def fake_detail(order_id: str):
        return {
            "order_id": order_id,
            "purchase_date": "2026-09-01 10:20:30+00:00",
            "order_status": "Shipped",
            "fulfillment_channel": "Amazon",
            "order_total": {"amount": 54.68, "currency": "USD"},
            "shipping_address": {
                "name": "Jane Doe", "city": "Seattle", "state": "WA",
                "postal_code": "98101", "country": "US",
            },
            "buyer_email": "buyer@example.com",
            "is_prime": True,
            "items": [{
                "asin": "B0TEST00001", "sku": "SKU-1", "title": "Portable Coffee Grinder Pro",
                "quantity": 2, "price": 12.34, "status": "Shipped",
            }],
            "total_items": 2,
        }

    api.get_order_detail = fake_detail  # type: ignore[method-assign]

    result = await api.track_order(ORDER_ID)

    assert result["found"] is True, f"真路径又被打回 not-found：{result.get('error')!r}"
    assert result["shipping_to"] == "Seattle, WA"
    assert result["current_status"]["label"] == "已发货"
    # ★ 客服侧要靠这两个字段回话（商品名 / 金额），必须带出来
    assert result["items"][0]["title"] == "Portable Coffee Grinder Pro"
    assert result["order_total"]["amount"] == 54.68


async def test_real_track_order_path_without_shipping_address_is_na():
    """无收货地址的订单不能崩，收货地降级为 N/A。"""
    from platforms.amazon.sp_api.orders import OrdersAPI

    api = OrdersAPI(client=None)  # type: ignore[arg-type]

    async def fake_detail(order_id: str):
        return {
            "order_id": order_id, "purchase_date": None, "order_status": "Pending",
            "fulfillment_channel": None, "order_total": {"amount": 0, "currency": "USD"},
            "shipping_address": None, "buyer_email": None, "is_prime": False,
            "items": [], "total_items": 0,
        }

    api.get_order_detail = fake_detail  # type: ignore[method-assign]

    result = await api.track_order(ORDER_ID)
    assert result["found"] is True
    assert result["shipping_to"] == "N/A"
    assert result["estimated_delivery"] is None


# ---------------------------------------------------------------- ⑥ 本地棘轮
def _random_call_count(path: Path) -> int:
    tree = ast.parse(path.read_bytes().decode("utf-8", errors="replace"))
    return sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "random"
    )


def test_order_tracking_module_keeps_random_out_of_the_data_path():
    """`agent_cs` **模块**的 `random.*` 调用点不得增长（本地棘轮）。

    ★ 口径必须走 AST：`raw.count("random.")` 会被注释与 docstring 骗到
      （本仓就有解释这条规则的注释写着 `random.uniform`）。
    ★ 判据窗口 = **整个 agent_cs 模块**（单文件 `agent_cs.py`，或拆包后的
      `agent_cs/` 整包），读取点收口在 `tests/pkg_source.py`。
      ★ 为什么不是「某一个文件」：拆包时方法是**逐行搬运**，合计值不变
      —— 所以这条棘轮在拆包前后**都**有效；反之若写死单文件路径，
      拆包后要么崩、要么静默只扫到包里一个文件而**放走其余的随机调用**。
    ★ 全仓棘轮与白名单见 `tests/test_no_random_in_production.py`。
    """
    files = source_files("modules/customer_service/agent_cs.py")
    assert files, "没读到 agent_cs 的任何源码文件 —— 棘轮会恒真，拒绝放行"
    count = sum(_random_call_count(p) for p in files)
    assert count <= 3, (
        f"agent_cs 的 random 调用点涨到 {count}（基线 3）—— "
        "订单数据路径必须零随机；新增的随机只允许出现在「同义文案挑选」这类位置。"
    )

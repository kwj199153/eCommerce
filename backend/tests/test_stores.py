"""
/api/v1/stores 端点测试（13 个端点）

为什么这个文件重要
------------------
`/api/v1/stores` 是前端「店铺群」的数据源，同时是**利润计算引擎的上下文入口**：
后端通过 `X-Store-ID` 请求头把 Store 上下文注入利润引擎，Agent 完全不感知 Store 模型。
此前这 13 个端点**零测试**。

本文件钉住一个 2026-09-12 修复的真实 bug
----------------------------------------
`GET /{store_id}` 曾注册在 `GET /fee-templates` / `GET /discount-templates` **之前**。
FastAPI 按注册顺序匹配路由，于是这两个**单段静态路径**被当成 store_id
（`store_id="fee-templates"`）→ 恒 404「店铺不存在: fee-templates」。
而前端 `api/stores.ts:165/172` 一直在调用它们 —— 即这两个接口**一直是坏的**。

修法：把「费率模板 / 折扣规则」两个静态路径段整体前移到 `/{store_id}` 之前。
`test_static_routes_registered_before_store_id` 用源码断言把顺序钉死，
防止后续新增端点时再踩同一个坑。

不测什么
--------
`connect` 端点只做「标记已连接」的状态变更（源码留 TODO：「实际验证凭证有效性」），
不发起任何外部请求，因此无需 mock SP-API。
"""

import inspect
import re
import uuid

import pytest_asyncio
from sqlalchemy import delete

from modules.stores.db_model import StoreRecord
from modules.stores.router import _fee_template_db, _store_db


# ====== 夹具 ======

@pytest_asyncio.fixture
async def created_ids():
    """
    记录用例创建的店铺 id，结束后同时清掉「内存读缓存」与「PG 权威存储」。

    两者都要清：stores 是双写设计（写内存 + 写 PG），只清一边会让下个用例
    读到上个案子的残影，或让开发库里堆测试垃圾。
    """
    ids: list[str] = []
    yield ids

    if not ids:
        return
    from core.database import async_session_factory

    async with async_session_factory() as session:
        for sid in ids:
            _store_db.pop(sid, None)
            await session.execute(delete(StoreRecord).where(StoreRecord.id == sid))
        await session.commit()


async def _create_store(client, ids: list[str], headers: dict | None = None, **overrides):
    """
    建一个店铺并登记 id（供 teardown 清理）。

    ★ `headers` 只在需要**按身份过滤**的用例里传：列表端点已收紧为
      「没有身份 ⇒ 没有数据」（见 `test_auth_optional_semantics.py`），
      匿名建出来的店 `owner_id` 为空 ⇒ 带身份读列表本就不该看见它。
    """
    payload = {"name": f"pytest-{uuid.uuid4().hex[:6]}", "platform": "amazon_us", **overrides}
    r = await client.post("/api/v1/stores", json=payload, headers=headers or {})
    assert r.status_code == 201, r.text
    ids.append(r.json()["id"])
    return r.json()


# ====== 一、路由注册顺序（bug 回归） ======

def test_static_routes_registered_before_store_id():
    """
    源码级回归：静态路径必须注册在 `/{store_id}` 之前。

    这是 FastAPI 的硬约束 —— 路由按注册顺序匹配，`/{store_id}` 会吞掉任何
    单段静态路径。改这个顺序会让前端两个接口静默 404，因此用源码断言锁死。
    """
    from modules.stores import router as router_module

    src = inspect.getsource(router_module)
    param_pos = src.index('@router.get("/{store_id}"')
    assert src.index('@router.get("/fee-templates"') < param_pos
    assert src.index('@router.get("/discount-templates"') < param_pos


async def test_fee_templates_reachable(client, auth_off):
    """`/fee-templates` 必须返回模板列表，而不是「店铺不存在」"""
    r = await client.get("/api/v1/stores/fee-templates")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and data
    assert any(t["id"] == "fee_amazon_us" for t in data)
    assert all(t["platform_type"] in ("amazon", "shopee") for t in data)


async def test_fee_templates_platform_filter(client, auth_off):
    r = await client.get("/api/v1/stores/fee-templates", params={"platform_type": "shopee"})
    assert r.status_code == 200
    assert r.json() and all(t["platform_type"] == "shopee" for t in r.json())


async def test_discount_templates_reachable(client, auth_off):
    """`/discount-templates` 同样不能被 `/{store_id}` 吃掉"""
    r = await client.get("/api/v1/stores/discount-templates")
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list) and data
    assert any(t["id"] == "default" for t in data)


async def test_supported_markets(client, auth_off):
    r = await client.get("/api/v1/stores/profit/supported-markets")
    assert r.status_code == 200
    data = r.json()
    assert "amazon" in data and "shopee" in data
    assert data["amazon"] and all("currency" in m for m in data["amazon"])


# ====== 二、费率模板详情 ======

async def test_fee_template_detail(client, auth_off):
    r = await client.get("/api/v1/stores/profit/fee-template/amazon_us")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform_key"] == "amazon_us"
    assert data["platform_type"] == "amazon"
    assert data["currency"] == "USD"
    assert isinstance(data["config"], dict) and data["config"]


async def test_fee_template_unknown_key_400(client, auth_off):
    r = await client.get("/api/v1/stores/profit/fee-template/nope_key")
    assert r.status_code == 400
    assert "nope_key" in r.json()["detail"]


async def test_create_fee_template(client, auth_off):
    """自定义模板：is_default 必须为 False（不能冒充系统默认）"""
    r = await client.post(
        "/api/v1/stores/fee-templates",
        json={"name": "pytest 自定义模板", "platform_type": "amazon", "referral_fee_pct": 12.5},
    )
    assert r.status_code == 201, r.text
    t = r.json()
    try:
        assert t["is_default"] is False
        assert t["name"] == "pytest 自定义模板"
        assert t["referral_fee_pct"] == 12.5
        assert t["id"].startswith("fee_custom_")
    finally:
        _fee_template_db.pop(t["id"], None)


# ====== 三、店铺 CRUD ======

async def test_create_store_derives_currency_and_region(client, auth_off, created_ids):
    """
    只给 name + platform，currency / region_code 应自动推断。

    回归 2026-09-12 修的 bug：`StoreCreate.currency` 曾默认 "USD"（非空），
    使 create_store 里的 `data.currency or 推断值` 永远短路 → 推断形同虚设，
    建 Shopee 店铺拿到 USD。Settings.vue 建店铺正是走「不传 currency」这条路。
    """
    store = await _create_store(client, created_ids, platform="shopee_my")
    assert store["currency"] == "MYR"
    assert store["region_code"] == "MY"
    # 默认值收敛
    assert store["status"] == "active"
    assert store["connection_status"] == "disconnected"
    assert store["has_credentials"] is False


async def test_create_store_explicit_currency_wins(client, auth_off, created_ids):
    """显式传 currency 时必须用传入值，不能被推断覆盖"""
    store = await _create_store(client, created_ids, platform="shopee_my", currency="SGD")
    assert store["currency"] == "SGD"


async def test_create_store_id_format(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    assert re.fullmatch(r"store_[0-9a-f]{8}", store["id"]), store["id"]


async def test_create_store_missing_name_422(client, auth_off):
    r = await client.post("/api/v1/stores", json={"platform": "amazon_us"})
    assert r.status_code == 422


async def test_list_stores_contains_created(client, auth_off, created_ids, make_user):
    """
    ★ 2026-09-17：改为**带身份**建店 + 带身份读列表。

    改前它匿名建、匿名读，靠的是「列表端点对无身份请求不过滤」——
    那正是 `filter_accessible_stores` 的 fail-open，现已收紧为
    「没有身份 ⇒ 没有数据」。这是**用例语义随之修正**，不是放宽断言。
    """
    me = await make_user("stores-list")
    store = await _create_store(client, created_ids, headers=me["headers"])
    r = await client.get("/api/v1/stores", headers=me["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["stores"])
    assert body["stores"], "带身份读列表不该为空（否则下一条断言会真空通过）"
    assert any(s["id"] == store["id"] for s in body["stores"])


async def test_list_stores_platform_filter(client, auth_off, created_ids, make_user):
    """
    ★ 同 `test_list_stores_contains_created`：必须带身份。

    ★★ 另修一处**真空通过**：`all(...)` 对空列表**恒真** ⇒ 过滤逻辑整段
      坏掉也一路绿。加一条非空前置，让「过滤没生效」能被抓住。
    """
    me = await make_user("stores-filter")
    await _create_store(
        client, created_ids, headers=me["headers"], platform="amazon_us"
    )
    r = await client.get(
        "/api/v1/stores", params={"platform": "amazon_us"}, headers=me["headers"]
    )
    assert r.status_code == 200
    stores = r.json()["stores"]
    assert stores, "列表为空 ⇒ `all(...)` 会真空通过，本用例失去意义"
    assert all(s["platform"] == "amazon_us" for s in stores)


async def test_get_store_detail(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    r = await client.get(f"/api/v1/stores/{store['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == store["id"]
    # 详情比列表多出两个摘要字段
    assert "fee_template_summary" in body
    assert "discount_template_summary" in body


async def test_get_unknown_store_404(client, auth_off):
    r = await client.get("/api/v1/stores/store_ffffffff")
    assert r.status_code == 404
    assert "store_ffffffff" in r.json()["detail"]


async def test_update_store(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    new_name = f"pytest-updated-{uuid.uuid4().hex[:6]}"
    r = await client.put(
        f"/api/v1/stores/{store['id']}",
        json={"name": new_name, "status": "inactive"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == new_name
    assert body["status"] == "inactive"
    # 未提交的字段不被清空
    assert body["platform"] == store["platform"]


async def test_update_unknown_store_404(client, auth_off):
    r = await client.put("/api/v1/stores/store_ffffffff", json={"name": "x"})
    assert r.status_code == 404


async def test_delete_store_then_404(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    r = await client.delete(f"/api/v1/stores/{store['id']}")
    assert r.status_code == 200
    assert r.json()["store_id"] == store["id"]
    assert (await client.get(f"/api/v1/stores/{store['id']}")).status_code == 404


async def test_delete_unknown_store_404(client, auth_off):
    assert (await client.delete("/api/v1/stores/store_ffffffff")).status_code == 404


# ====== 四、平台连接状态机 ======

async def test_connect_then_disconnect(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    sid = store["id"]

    r = await client.post(f"/api/v1/stores/{sid}/connect")
    assert r.status_code == 200, r.text
    assert r.json()["connection_status"] == "connected"
    detail = (await client.get(f"/api/v1/stores/{sid}")).json()
    assert detail["connection_status"] == "connected"
    assert detail["has_credentials"] is True

    r = await client.post(f"/api/v1/stores/{sid}/disconnect")
    assert r.status_code == 200
    detail = (await client.get(f"/api/v1/stores/{sid}")).json()
    assert detail["connection_status"] == "disconnected"
    assert detail["has_credentials"] is False


async def test_connect_unknown_store_404(client, auth_off):
    assert (await client.post("/api/v1/stores/store_ffffffff/connect")).status_code == 404


# ====== 五、利润计算（Agent 上下文注入入口） ======

async def test_profit_calculate_ok(client, auth_off, created_ids):
    store = await _create_store(client, created_ids, platform="amazon_us")
    r = await client.post(
        "/api/v1/stores/profit/calculate",
        json={"product_cost": 10.0, "listing_price": 29.99},
        headers={"X-Store-ID": store["id"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 平台由店铺上下文注入，不由请求体传入
    assert body["platform"] == "amazon"


async def test_profit_calculate_missing_header_422(client, auth_off):
    """`X-Store-ID` 是必填头：缺了必须 422，不能静默用一个默认店铺算"""
    r = await client.post(
        "/api/v1/stores/profit/calculate",
        json={"product_cost": 10.0, "listing_price": 29.99},
    )
    assert r.status_code == 422


async def test_profit_calculate_unknown_store_404(client, auth_off):
    r = await client.post(
        "/api/v1/stores/profit/calculate",
        json={"product_cost": 10.0, "listing_price": 29.99},
        headers={"X-Store-ID": "store_ffffffff"},
    )
    assert r.status_code == 404


async def test_profit_calculate_rejects_nonpositive_cost(client, auth_off, created_ids):
    store = await _create_store(client, created_ids)
    r = await client.post(
        "/api/v1/stores/profit/calculate",
        json={"product_cost": 0, "listing_price": 29.99},
        headers={"X-Store-ID": store["id"]},
    )
    assert r.status_code == 422


# ====== 六、鉴权闸门 ======

def test_routes_under_business_auth_gate():
    """
    断言 `stores_router` 挂上了 `BUSINESS_AUTH`。

    注意不能用 `auth_on` 夹具断言 401 —— `BUSINESS_AUTH` 是 `import main` 时
    求值一次的**启动期快照**，运行期改 `config.auth_required` 对它无效。
    因此只能做源码断言。

    ★ 第 106 轮更新：该常量已改为**无条件挂载**，依赖在**请求期**读
      `config.auth_required` ⇒ 上面那句话不再成立，`auth_on` 现在**可以**
      断言 401（端点级 401 见 `test_auth_optional_semantics.py`）。
      本用例保留源码断言，锁的是「这份 router 被纳入闸门」，防新增模块漏挂。
    """
    import main

    flat = re.sub(r"\s+", " ", inspect.getsource(main))
    assert "stores_router, dependencies=BUSINESS_AUTH" in flat, "stores 路由未挂鉴权闸门"
# ====== 七、店铺「序号」排序口径一致性（2026-09-14 修复） ======
#
# 为什么必须有这组测试
# --------------------
# 老板说「切到第 2 个店铺」时，**序号是两条链路各自数出来的**：
#   - LLM 侧：`secretary/shop_tools._list_shops()` 查 PG
#   - 界面侧：`GET /api/v1/stores` → 原本是 `list(_store_db.values())`（内存 dict 顺序）
# 两边顺序不一致 ⇒ AI 按 A 顺序数、界面按 B 顺序显示 ⇒ **静默切错店**（不报错，最难发现）。
#
# 修复前的三处不一致：
#   1. `load_stores_into_memory()` 的 `select(StoreRecord)` **无 order_by** → dict 插入顺序未定义
#   2. `list_stores()` 直接用 `list(_store_db.values())` → 继承上面那个未定义顺序
#   3. `_list_shops()` 用 `ORDER BY created_at, id` → 与上面两者无关
#
# 修法：真源 `SHOP_ORDER_BY` 落在 `stores/db_model.py`，三处消费。
# 本组测试钉住「真源唯一 + 两条链路对齐」，防止有人改回隐式顺序。


def test_shop_order_by_is_single_source_of_truth():
    """
    排序真源必须是 `db_model.SHOP_ORDER_BY`，且被三处消费。

    用源码断言（而非行为断言）：行为断言在「三处各写一遍但恰好一致」时会假绿，
    而本 bug 的本质就是**多份口径**，必须钉住「只有一份」。
    """
    from modules.stores import db_model, router as router_module

    assert hasattr(db_model, "SHOP_ORDER_BY"), "排序真源 SHOP_ORDER_BY 不存在"
    assert db_model.SHOP_ORDER_BY == ("created_at", "id")

    rsrc = inspect.getsource(router_module)
    # ① 回灌必须排
    assert "order_by(" in rsrc and "SHOP_ORDER_BY" in rsrc, \
        "load_stores_into_memory / list_stores 未使用排序真源"
    # ② list_stores 必须显式 sorted（不依赖 dict 插入顺序）
    assert "sorted(_store_db.values()" in rsrc, \
        "list_stores 仍依赖 dict 插入顺序（应为显式 sorted）"

    from modules.secretary import shop_tools
    ssrc = inspect.getsource(shop_tools)
    assert "SHOP_ORDER_BY" in ssrc, "_list_shops 未复用排序真源（自己写了一份 order_by）"
    # 反向：不允许再出现写死的 order_by(...created_at..., ...id...)
    assert "order_by(StoreRecord.created_at, StoreRecord.id)" not in ssrc, \
        "_list_shops 里仍有写死的 order_by —— 应改为 SHOP_ORDER_BY"


async def test_stores_order_matches_shop_tools_order(
    client, auth_off, created_ids, make_user
):
    """
    ★ 核心回归：`/api/v1/stores` 的顺序 == `_list_shops()` 的顺序。

    这两个序列是同一个「第 N 个店铺」的两种读法，必须逐项相等。
    """
    from modules.secretary.shop_tools import _list_shops

    # ★ 带身份建 / 带身份读：无身份的列表已收紧为空集，用它比对顺序会**真空通过**
    #   （空列表的 positions 必然等于 sorted(positions)）。
    me = await make_user("stores-order")
    # 建 3 个店铺，故意用「乱序」的创建顺序（名字带前缀不参与排序）
    for _ in range(3):
        await _create_store(client, created_ids, headers=me["headers"])

    r = await client.get("/api/v1/stores", headers=me["headers"])
    assert r.status_code == 200, r.text
    api_ids = [s["id"] for s in r.json()["stores"]]
    assert len(api_ids) == 3, (
        f"期望恰好 3 家店，实得 {api_ids} —— 空/少则下面的顺序断言真空通过"
    )

    tool_shops = await _list_shops()
    tool_ids = [s["id"] for s in tool_shops]

    # 两边可能因 owner 过滤差异而子集不同（api 会按当前用户过滤），
    # 所以断言「api_ids 是 tool_ids 的子序列」且**相对顺序一致**。
    assert set(api_ids) <= set(tool_ids), "api 返回了 tool 不认识的店铺"
    positions = [tool_ids.index(i) for i in api_ids]
    assert positions == sorted(positions), (
        "两边顺序不一致！\n  api  = %s\n  tool = %s" % (api_ids, tool_ids)
    )


async def test_load_stores_into_memory_is_ordered():
    """
    回灌后内存 dict 的顺序必须已经是真源顺序（不依赖后续 sorted 兜底）。

    这是「双重保险」的第一层：即使哪天有人从 `list_stores` 里去掉 sorted，
    回灌顺序本身也是对的。
    """
    from modules.stores.router import load_stores_into_memory, _store_db
    from modules.stores.db_model import SHOP_ORDER_BY

    await load_stores_into_memory()
    stores = list(_store_db.values())
    key = [tuple(getattr(s, k) for k in SHOP_ORDER_BY) for s in stores]
    assert key == sorted(key), "回灌后的 dict 顺序不是 SHOP_ORDER_BY 顺序"


def test_tie_breaker_makes_order_deterministic():
    """
    `created_at` 相同时，`id` 必须能定序（否则顺序随入参漂移 = 不稳定排序）。

    反证：只用 created_at 时，同一批数据因入参顺序不同会给出两种结果。
    """
    from datetime import datetime
    from types import SimpleNamespace
    from modules.stores.db_model import SHOP_ORDER_BY

    T = datetime(2026, 9, 14, 10, 0, 0)
    shops = [
        SimpleNamespace(id="store_zzz", created_at=T),
        SimpleNamespace(id="store_aaa", created_at=T),
        SimpleNamespace(id="store_mmm", created_at=T),
    ]
    key = lambda s: tuple(getattr(s, k) for k in SHOP_ORDER_BY)  # noqa: E731

    a = [s.id for s in sorted(shops, key=key)]
    b = [s.id for s in sorted(list(reversed(shops)), key=key)]
    assert a == b == ["store_aaa", "store_mmm", "store_zzz"], \
        "tie-breaker 失效：相同 created_at 下顺序随入参变化"

    # 反证：去掉 id 会不稳定
    only_ts = lambda s: s.created_at  # noqa: E731
    a2 = [s.id for s in sorted(shops, key=only_ts)]
    b2 = [s.id for s in sorted(list(reversed(shops)), key=only_ts)]
    assert a2 != b2, "反证失败：只用 created_at 竟然也稳定？（说明测试构造有误）"

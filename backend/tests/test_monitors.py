"""
竞品监控池（monitors）测试

分三层覆盖：
  1. **时序生成器**（snapshot）—— 确定性是核心契约：刷新不跳动全靠「同一 ASIN
     永远生成同一份序列」，这条一破，持久化就白做了。
  2. **字段契约**（record_to_dict）—— 前端 `MonitorPoolRecord` 的字段一个都不能少，
     JSON 列必须兜底成数组（前端直接 `.length` / `.slice()`）。
  3. **端点行为** —— 租户过滤 / upsert 合并 / 分组 CRUD / 批量操作。

所有用例针对真实本地 PostgreSQL，用**测试专属 shop_id** 隔离，结束清理自己写入的行
（不碰其他店铺的数据）。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from core.database import async_session_factory
from modules.monitors.db_model import MonitorRecord, MonitorGroupRecord
from modules.monitors.service import (
    build_monitor_record,
    make_monitor_id,
    missing_required_fields,
    normalize_asin,
    record_to_dict,
)
from modules.monitors.snapshot import build_time_series, derive_baseline


# ====== 夹具 ======

@pytest_asyncio.fixture
async def shop_headers(ensure_shop):
    """只属于本次测试的店铺 id；用例跑完清掉该店铺的全部监控数据"""
    # ensure_shop：自造 shop_id 必须在 stores_store 里真实存在（迁移 d5e6f7a8b9c0 的外键）
    sid = await ensure_shop(f"store_pytest_{uuid.uuid4().hex[:8]}")
    yield {"X-Shop-ID": sid}
    async with async_session_factory() as session:
        await session.execute(delete(MonitorRecord).where(MonitorRecord.shop_id == sid))
        await session.execute(delete(MonitorGroupRecord).where(MonitorGroupRecord.shop_id == sid))
        await session.commit()


@pytest_asyncio.fixture
async def two_shop_headers(ensure_shop):
    """两个互不相干的店铺（验证租户隔离）"""
    a = await ensure_shop(f"store_pytest_a_{uuid.uuid4().hex[:6]}")
    b = await ensure_shop(f"store_pytest_b_{uuid.uuid4().hex[:6]}")
    yield ({"X-Shop-ID": a}, {"X-Shop-ID": b})
    async with async_session_factory() as session:
        for sid in (a, b):
            await session.execute(delete(MonitorRecord).where(MonitorRecord.shop_id == sid))
            await session.execute(delete(MonitorGroupRecord).where(MonitorGroupRecord.shop_id == sid))
        await session.commit()


# ====== 1. 时序生成器 ======

def test_snapshot_is_deterministic():
    """同一 ASIN 两次生成必须完全一致 —— 这是「刷新不跳动」的唯一保证"""
    a = build_time_series("B0DETERM01", 39.99, 1200, 3000, idx=0)
    b = build_time_series("B0DETERM01", 39.99, 1200, 3000, idx=0)
    assert a == b


def test_snapshot_differs_across_asins():
    """不同 ASIN 应得到不同的历史曲线（否则 6 条演示数据会长得一模一样）"""
    a = build_time_series("B0AAA00001", 39.99, 1200, 3000, idx=0)
    b = build_time_series("B0BBB00002", 39.99, 1200, 3000, idx=0)
    assert a["price_history"] != b["price_history"]
    assert a["bsr_history"] != b["bsr_history"]


def test_snapshot_series_lengths():
    ts = build_time_series("B0LENGTH001", 29.99, 800, 1500)
    assert len(ts["price_history"]) == 30
    assert len(ts["bsr_history"]) == 30
    assert len(ts["review_events"]) == 30
    assert 1 <= len(ts["variations"]) <= 4
    assert 1 <= len(ts["listing_changes"]) <= 3


def test_snapshot_derived_fields_consistent():
    """派生快照必须与序列自洽（否则卡片数字与曲线对不上）"""
    ts = build_time_series("B0DERIVE001", 49.99, 2000, 4000)
    assert ts["latest_price"] == ts["price_history"][-1]["price"]
    assert ts["latest_bsr"] == ts["bsr_history"][-1]["bsr"]
    assert ts["reviews_added_7d"] == sum(e["added"] for e in ts["review_events"][-7:])


def test_snapshot_stock_status_all_states_reachable():
    """
    回归：原前端写法 `roll > 0.82 ? low : roll > 0.92 ? out : in` 里
    `out_of_stock` **永远不可达**（第一个条件先命中），缺货预警面板从来没亮过。
    修复后三态都必须出得来。
    """
    statuses = {build_time_series(f"B0STATE{i:04d}", 30.0, 1000)["stock_status"] for i in range(100)}
    assert statuses == {"in_stock", "low_stock", "out_of_stock"}


def test_snapshot_out_of_stock_has_no_remaining_units():
    """缺货时剩余可售必须为 None（无从估算，不能编一个数字）"""
    for i in range(200):
        ts = build_time_series(f"B0UNIT{i:04d}", 30.0, 1000)
        if ts["stock_status"] == "out_of_stock":
            assert ts["estimated_units_remaining"] is None
            return
    pytest.fail("200 个样本里没有出现缺货态，生成器有问题")


def test_derive_baseline_is_deterministic_and_respects_payload():
    a = derive_baseline("B0BASE0001", {})
    b = derive_baseline("B0BASE0001", {})
    assert a == b
    assert a["base_price"] > 0 and a["base_bsr"] > 0
    # payload 给了就用，不再推导
    given = derive_baseline("B0BASE0001", {"latest_price": 88.8, "latest_bsr": 77})
    assert given == {"base_price": 88.8, "base_bsr": 77}


# ====== 2. 字段契约 ======

# 前端 MonitorPoolRecord 的字段清单（少一个前端就渲染出 undefined）
FRONTEND_REQUIRED_KEYS = {
    "id", "asin", "title", "brand", "main_image", "marketplace", "currency",
    "latest_price", "price_change_7d", "latest_bsr", "bsr_category", "bsr_change_7d",
    "rating", "review_count", "reviews_added_7d", "stock_status",
    "estimated_units_remaining", "est_monthly_sales",
    "price_history", "bsr_history", "review_events", "variations", "listing_changes",
    "group_ids", "added_at", "origin", "source_candidate_id", "owned_by",
}


def test_record_to_dict_covers_frontend_contract():
    payload = {"asin": "B0CONTRACT1", "title": "Test Product", "brand": "ACME"}
    record = build_monitor_record(payload, shop_id="store_x")
    d = record_to_dict(record)
    assert FRONTEND_REQUIRED_KEYS <= set(d.keys()), \
        f"缺字段: {FRONTEND_REQUIRED_KEYS - set(d.keys())}"
    assert d["asin"] == "B0CONTRACT1"
    assert d["brand"] == "ACME"


def test_record_to_dict_json_columns_default_to_list():
    """JSON 列在库里可为 NULL，前端期望恒为数组"""
    record = build_monitor_record({"asin": "B0EMPTY0001"}, shop_id="store_x")
    record.price_history = None
    record.bsr_history = None
    record.review_events = None
    record.variations = None
    record.listing_changes = None
    record.group_ids = None
    d = record_to_dict(record)
    for key in ("price_history", "bsr_history", "review_events",
                "variations", "listing_changes", "group_ids"):
        assert d[key] == [], f"{key} 未兜底成 []"


def test_normalize_asin():
    assert normalize_asin("  b0abc12345 ") == "B0ABC12345"
    assert normalize_asin(None) == ""
    assert normalize_asin("") == ""


def test_make_monitor_id_carries_tenant():
    """主键必须带租户维度：同一 ASIN 可以被不同店铺各自监控"""
    a = make_monitor_id("B0SAME0001", "store_a")
    b = make_monitor_id("B0SAME0001", "store_b")
    assert a != b
    assert a == "mon-B0SAME0001-store_a"


def test_missing_required_fields():
    assert missing_required_fields({}) == ["asin"]
    assert missing_required_fields({"asin": "   "}) == ["asin"]
    assert missing_required_fields({"asin": "B0OK000001"}) == []


def test_build_minimal_payload_still_produces_full_record():
    """只给 ASIN 也要能产出一条有意义的记录（弹窗就一个输入框）"""
    record = build_monitor_record({"asin": "B0MINIMAL1"}, shop_id="store_x")
    assert record.title == "B0MINIMAL1"          # 标题兜底成 ASIN
    assert record.latest_price > 0                # 价格按 ASIN 推导
    assert record.latest_bsr > 0
    assert len(record.price_history) == 30        # 时序照常生成
    assert record.group_ids == []
    assert record.origin == "manual"


def test_build_prefers_payload_over_generated():
    record = build_monitor_record(
        {"asin": "B0PREFER001", "title": "Given Title", "latest_price": 12.5, "latest_bsr": 345},
        shop_id="store_x",
    )
    assert record.title == "Given Title"
    assert record.latest_price == 12.5
    assert record.latest_bsr == 345


def test_zero_is_a_valid_value_not_a_fallback_trigger():
    """
    `payload.get(k) or fallback` 会把 0 当成缺失 —— 价格变化 0% 是有效值，
    被 fallback 覆盖就会出现「明明没变却显示 3%」。
    """
    record = build_monitor_record(
        {"asin": "B0ZERO00001", "price_change_7d": 0, "bsr_change_7d": 0},
        shop_id="store_x",
    )
    assert record.price_change_7d == 0
    assert record.bsr_change_7d == 0


# ====== 3. 端点 ======

async def test_list_returns_empty_without_shop_header(client, auth_off):
    """无租户上下文 → 返回空（与 candidates / products / assets 一致）"""
    r = await client.get("/api/v1/monitors")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}


async def test_create_then_list(client, auth_off, shop_headers):
    r = await client.post(
        "/api/v1/monitors",
        json={"asin": "b0create001", "title": "Created Product", "brand": "ACME"},
        headers=shop_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["asin"] == "B0CREATE001"        # ASIN 归一为大写
    assert created["title"] == "Created Product"
    assert len(created["price_history"]) == 30

    lst = await client.get("/api/v1/monitors", headers=shop_headers)
    assert lst.status_code == 200
    body = lst.json()
    assert body["total"] == 1
    assert body["items"][0]["asin"] == "B0CREATE001"


async def test_upsert_merges_same_asin(client, auth_off, shop_headers):
    """同店铺同 ASIN 二次入池必须合并，不能出现重复行"""
    first = await client.post(
        "/api/v1/monitors", json={"asin": "B0MERGE0001", "title": "First"}, headers=shop_headers
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/monitors",
        json={"asin": "B0MERGE0001", "brand": "Filled Later"},
        headers=shop_headers,
    )
    assert second.status_code == 201
    # 合并语义：新字段补上，旧字段保留
    assert second.json()["title"] == "First"
    assert second.json()["brand"] == "Filled Later"

    lst = await client.get("/api/v1/monitors", headers=shop_headers)
    assert lst.json()["total"] == 1


async def test_same_asin_in_two_shops_is_isolated(client, auth_off, two_shop_headers):
    """两个店铺监控同一个 ASIN，互不干扰"""
    ha, hb = two_shop_headers
    await client.post("/api/v1/monitors", json={"asin": "B0SHARED001", "title": "A 家的"}, headers=ha)
    await client.post("/api/v1/monitors", json={"asin": "B0SHARED001", "title": "B 家的"}, headers=hb)

    la = (await client.get("/api/v1/monitors", headers=ha)).json()
    lb = (await client.get("/api/v1/monitors", headers=hb)).json()
    assert la["total"] == 1 and lb["total"] == 1
    assert la["items"][0]["title"] == "A 家的"
    assert lb["items"][0]["title"] == "B 家的"


async def test_create_without_asin_is_rejected(client, auth_off, shop_headers):
    r = await client.post("/api/v1/monitors", json={"title": "no asin"}, headers=shop_headers)
    assert r.status_code == 422


async def test_get_unknown_id_404(client, auth_off, shop_headers):
    r = await client.get("/api/v1/monitors/mon-NOPE-shop_x", headers=shop_headers)
    assert r.status_code == 404


async def test_update_monitor(client, auth_off, shop_headers):
    created = (await client.post(
        "/api/v1/monitors", json={"asin": "B0UPDATE001", "title": "Old"}, headers=shop_headers
    )).json()
    r = await client.put(
        f"/api/v1/monitors/{created['id']}",
        json={"title": "New", "rating": 4.8},
        headers=shop_headers,
    )
    assert r.status_code == 200
    assert r.json()["title"] == "New"
    assert r.json()["rating"] == 4.8


async def test_delete_monitor(client, auth_off, shop_headers):
    created = (await client.post(
        "/api/v1/monitors", json={"asin": "B0DELETE001"}, headers=shop_headers
    )).json()
    r = await client.delete(f"/api/v1/monitors/{created['id']}", headers=shop_headers)
    assert r.status_code == 200
    lst = (await client.get("/api/v1/monitors", headers=shop_headers)).json()
    assert lst["total"] == 0


async def test_batch_delete(client, auth_off, shop_headers):
    for asin in ("B0BATCH0001", "B0BATCH0002", "B0BATCH0003"):
        await client.post("/api/v1/monitors", json={"asin": asin}, headers=shop_headers)
    r = await client.post(
        "/api/v1/monitors/batch-delete",
        json={"asins": ["B0BATCH0001", "B0BATCH0002"]},
        headers=shop_headers,
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == 2
    lst = (await client.get("/api/v1/monitors", headers=shop_headers)).json()
    assert lst["total"] == 1
    assert lst["items"][0]["asin"] == "B0BATCH0003"


async def test_batch_upsert_reports_added_and_existing(client, auth_off, shop_headers):
    """批量入池要能区分「新增」与「已在池」，前端 toast 文案依赖它"""
    await client.post("/api/v1/monitors", json={"asin": "B0EXIST0001"}, headers=shop_headers)
    r = await client.post(
        "/api/v1/monitors/batch-upsert",
        json={"items": [
            {"asin": "B0EXIST0001", "title": "已有"},
            {"asin": "B0NEWNEW001", "title": "新增一"},
            {"asin": "B0NEWNEW002", "title": "新增二"},
        ]},
        headers=shop_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 2
    assert body["existing"] == 1
    assert len(body["items"]) == 3


async def test_group_crud_and_assignment(client, auth_off, shop_headers):
    g = (await client.post(
        "/api/v1/monitor-groups",
        json={"name": "Q4 重点盯防", "kind": "custom", "color": "#722ed1"},
        headers=shop_headers,
    )).json()
    assert g["name"] == "Q4 重点盯防"
    assert g["kind"] == "custom"

    listed = (await client.get("/api/v1/monitor-groups", headers=shop_headers)).json()
    assert len(listed["groups"]) == 1

    # 改名
    r = await client.put(
        f"/api/v1/monitor-groups/{g['id']}", json={"name": "Q4 盯防"}, headers=shop_headers
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Q4 盯防"

    # 归入分组
    await client.post("/api/v1/monitors", json={"asin": "B0GROUP0001"}, headers=shop_headers)
    r = await client.post(
        "/api/v1/monitors/assign-group",
        json={"asins": ["B0GROUP0001"], "group_id": g["id"]},
        headers=shop_headers,
    )
    assert r.json()["updated"] == 1
    item = (await client.get("/api/v1/monitors", headers=shop_headers)).json()["items"][0]
    assert item["group_ids"] == [g["id"]]

    # 移出分组
    r = await client.post(
        "/api/v1/monitors/unassign-group",
        json={"asins": ["B0GROUP0001"], "group_id": g["id"]},
        headers=shop_headers,
    )
    assert r.json()["updated"] == 1
    item = (await client.get("/api/v1/monitors", headers=shop_headers)).json()["items"][0]
    assert item["group_ids"] == []


async def test_delete_group_keeps_records(client, auth_off, shop_headers):
    """删分组是整理动作，不能连带删掉监控记录"""
    g = (await client.post(
        "/api/v1/monitor-groups", json={"name": "临时分组"}, headers=shop_headers
    )).json()
    await client.post("/api/v1/monitors", json={"asin": "B0KEEP00001"}, headers=shop_headers)
    await client.post(
        "/api/v1/monitors/assign-group",
        json={"asins": ["B0KEEP00001"], "group_id": g["id"]},
        headers=shop_headers,
    )

    r = await client.delete(f"/api/v1/monitor-groups/{g['id']}", headers=shop_headers)
    assert r.status_code == 200
    assert r.json()["detached"] == 1

    lst = (await client.get("/api/v1/monitors", headers=shop_headers)).json()
    assert lst["total"] == 1                       # 记录还在
    assert lst["items"][0]["group_ids"] == []      # 只是脱钩了
    assert (await client.get("/api/v1/monitor-groups", headers=shop_headers)).json()["groups"] == []


async def test_groups_are_shop_scoped(client, auth_off, two_shop_headers):
    """分组也要按店铺隔离，不能串"""
    ha, hb = two_shop_headers
    await client.post("/api/v1/monitor-groups", json={"name": "A 的分组"}, headers=ha)
    assert len((await client.get("/api/v1/monitor-groups", headers=ha)).json()["groups"]) == 1
    assert (await client.get("/api/v1/monitor-groups", headers=hb)).json()["groups"] == []


async def test_demo_mode_allows_anonymous_access(client, auth_off, shop_headers):
    """演示模式（默认）下业务端点放行 —— 与其余业务模块行为一致"""
    r = await client.get("/api/v1/monitors", headers=shop_headers)
    assert r.status_code == 200


def test_monitors_routes_under_business_auth_gate():
    """
    monitors 与 candidates / products / assets 一致，走 `main.BUSINESS_AUTH` 统一闸门。

    **这个常量是「启动期快照」，不是运行期开关**：
        BUSINESS_AUTH = [Depends(require_auth_if_enabled)] if config.auth_required else []

    它在 `import main` 时求值一次，所以：
      · 演示模式启动 → 空列表，业务端点全部放行；此后运行期把 config.auth_required
        改成 True **也不会生效**，必须重启进程（这是「条件挂载」的设计代价，
        换来的是「路由上有依赖 == 请求真会被拦」，鉴权覆盖报告不失真）。
      · 生产模式启动（AUTH_REQUIRED=true）→ 挂上依赖，未带 token 返回 401。

    因此这里**不能**用 `auth_on` 夹具去断言 401（改的是运行期 config，对已经被
    求值成空列表的 BUSINESS_AUTH 无效）。本用例改为锁住「monitors 确实被纳入
    该闸门」，防止以后新增模块时漏挂。
    """
    import inspect
    import main

    paths = {r.path for r in main.app.routes if "monitor" in getattr(r, "path", "")}
    assert "/api/v1/monitors" in paths
    assert "/api/v1/monitors/{monitor_id}" in paths
    assert "/api/v1/monitor-groups" in paths

    flat = " ".join(inspect.getsource(main).split())
    assert "monitors_router, dependencies=BUSINESS_AUTH" in flat, \
        "monitors 路由未挂在 BUSINESS_AUTH 闸门下（生产模式将不受鉴权保护）"


def test_business_auth_empty_in_demo_mode_by_design():
    """演示模式下 BUSINESS_AUTH 为空列表 —— 明确记录这个设计，避免误判为漏挂"""
    import main
    from core.config import config

    if not config.auth_required:
        assert main.BUSINESS_AUTH == []
    else:
        assert len(main.BUSINESS_AUTH) == 1


# ====== 4. seed ======

async def test_seed_uses_real_shop_ids_not_hardcoded():
    """
    回归（历史背景）：candidates/seed.py 与 products/seed.py 曾把 shop_id 写死成
    "shop-1"（已于 2026-09-12 修复，见 tests/test_seed_shop_ids.py），而真实租户
    id 是 `store_xxxxxxxx`，导致那批种子数据任何请求都查不到。

    这里断言 monitors 的 seed 产出的 shop_id 必须来自 stores 表，
    **不包含**任何硬编码字面量。
    """
    from sqlalchemy import select as sa_select
    from modules.stores.db_model import StoreRecord

    async with async_session_factory() as session:
        real_shop_ids = set((await session.execute(sa_select(StoreRecord.id))).scalars().all())
        seeded_shop_ids = set((await session.execute(
            sa_select(MonitorRecord.shop_id).distinct()
        )).scalars().all())

    # 允许监控池暂时为空（测试库刚建时），但只要有数据，shop_id 必须在真实店铺集合里
    if seeded_shop_ids:
        assert seeded_shop_ids <= real_shop_ids, (
            f"seed 用了不存在的 shop_id: {seeded_shop_ids - real_shop_ids}"
        )
    assert "shop-1" not in seeded_shop_ids

"""交易履约域「落库同步」的**行为**门禁（第 283 轮）

==============================================================================
★ 与 `test_trade_schedule.py` 的分工
==============================================================================
`test_trade_schedule.py` 守的是「**接上了没有**」（beat 条目 / autodiscover /
任务体调没调对）；本文件守的是「**同步本身做得对不对**」——
接上了但算错，照样是坏的，而且**不报错**。

==============================================================================
★ 为什么全程单事务 + rollback
==============================================================================
本仓 `tests/` 直连**共享库**。若这些用例真的提交，跑一次就往里灌一批
`platform='amazon_test_sync'` 的订单，第二次跑的幂等断言随即被自己污染
（第二次变成 UPDATE 而不是 INSERT，看着像"幂等通过了"其实是数据脏了）。
⇒ 每个用例开一个事务、断言完**回滚**，库保持原样，用例可重复跑。

==============================================================================
★ 为什么用例写成 `async def`，而不是 `asyncio.run(...)` 包一层
==============================================================================
`pytest.ini` 里是 `asyncio_mode = auto`，loop 由 pytest-asyncio 统一管。
若自己 `asyncio.run()`：它**每次新建并关闭**一个 loop，而 asyncpg 的连接
绑定在「创建它的那个 loop」上 ⇒ 第二个用例拿到「属于一个已死 loop」的连接，
报 `RuntimeError: Event loop is closed`；而在用例里自建常驻 loop 也不行 ——
conftest 里的 async fixture 走的是 pytest-asyncio 那个 loop，两侧连接打架
（实测报 `got Future attached to a different loop`，且只在 teardown 期炸）。
⇒ **一个进程一个 loop，交给框架**。这与 `modules/memory/tasks.py` 为 Celery
侧记下的结论是同一个坑的三种形态。

==============================================================================
★ 反向注入清单（每条都必须让本文件**至少一条**转红）
==============================================================================
 1. `sync.py::upsert_order` 里把 `compute_transit_and_delay(...)` 换成
    自己算的日期差 ⇒ `test_delay_days_matches_service_rule` 转红；
 2. `sync_orders_from_source` 里去掉 `if not batch.get("supported")` 判据
    ⇒ `test_unsupported_source_raises` 转红（静默当成 0 条）；
 3. `upsert_review` 里去掉 `auto_attribute` 的自动归因
    ⇒ `test_new_review_is_auto_attributed` 转红；
 4. `_attribute` 里去掉 `method == MANUAL_METHOD` 的短路
    ⇒ `test_manual_attribution_survives_resync` 转红。
"""

from datetime import datetime

import pytest
from sqlalchemy import select

#: ★ 专用 platform：与真实数据（'amazon'）隔开，避免用例把演示数据改掉，
#:   也让「这次 INSERT 的是用例自己的行」可以被数清楚。
PROBE_PLATFORM = "amazon_test_sync"

NOW = datetime(2026, 3, 1, 12, 0, 0)


# ============================================================================
# 载荷：一条「迟到 + 包装破损」的订单（与演示剧本同一形态）
# ============================================================================

def _order_payload(external="T-ORD-0001"):
    return {
        "external_order_id": external,
        "platform": PROBE_PLATFORM,
        "marketplace": "US",
        "buyer_id": "", "buyer_name": "T***t",
        "order_status": "delivered", "fulfillment_channel": "FBA",
        "ship_country": "US", "ship_state": "California", "ship_city": "San Jose",
        "currency": "USD", "order_total": 29.99,
        # 发货 02-15 → 送达 02-27 = 在途 12 天；承诺 02-20 → 送达 = 迟 7 天
        "purchase_at": "2026-02-14T12:00:00",
        "shipped_at": "2026-02-15T12:00:00",
        "promised_at": "2026-02-20T12:00:00",
        "delivered_at": "2026-02-27T12:00:00",
        "items": [{
            "external_order_item_id": f"{external}-1",
            "sku": "T-SKU-001", "asin": "B0TEST0001",
            "item_title": "Test Mug", "image": "",
            "quantity": 1, "currency": "USD",
            "unit_price": 29.99, "item_total": 29.99,
        }],
        "shipment": {
            "carrier": "UPS", "tracking_no": "1ZTEST0001",
            "ship_status": "delivered",
            "shipped_at": "2026-02-15T12:00:00",
            "promised_at": "2026-02-20T12:00:00",
            "delivered_at": "2026-02-27T12:00:00",
            "events": [
                {"at": "2026-02-25T12:00:00", "status": "EXCEPTION",
                 "location": "Ontario, CA",
                 "description": "Package crushed in transit"},
                {"at": "2026-02-27T12:00:00", "status": "DELIVERED",
                 "location": "San Jose, CA", "description": "Delivered"},
            ],
        },
        "raw": {"script": "unit-test"},
    }


def _review_payload(order_ref="T-ORD-0001", external="T-REV-0001", rating=1):
    return {
        "external_review_id": external,
        "platform": PROBE_PLATFORM,
        "marketplace": "US",
        "order_ref": order_ref,
        "sku": "T-SKU-001", "asin": "B0TEST0001",
        "product_title": "Test Mug",
        "rating": rating,
        "title": "Twelve days and the box was destroyed",
        "body": (
            "Took 12 days to arrive even though the listing promised 5. "
            "When it finally showed up the outer box was crushed."
        ),
        "language": "en",
        "review_at": "2026-02-27T12:00:00",
        "verified_purchase": True,
        "helpful_votes": 12,
        "images": [],
        "buyer_name": "T***t",
        "raw": {"script": "unit-test"},
    }


async def _first_shop_id(session):
    from core.stores import StoreRecord
    return (await session.execute(
        select(StoreRecord.id).order_by(StoreRecord.id).limit(1)
    )).scalar_one_or_none()


# ============================================================================
# 不需要 DB 的用例（纯契约）
# ============================================================================

async def test_unsupported_source_raises():
    """数据源说「不支持」时必须**抛**，不能当成「这次拉到 0 条」。

    ★ 为什么这条最重要：「不支持」与「0 条」混在一起时，同步任务会天天
      「成功」而订单表永远是空的，且**没有任何报错** —— 排查方向会被
      引到「是不是调度没跑」（而调度其实是好的）。

    ★ 反向注入：把 `sync.py` 里 `if not batch.get("supported"): raise ...`
      这一段删掉 ⇒ 本条转红（函数会安静地返回 inserted=0）。
    """
    from modules.trade import (
        SourceNotSupported, sync_orders_from_source, sync_reviews_from_source,
    )

    class _NoOrders:
        def fetch_orders(self, shop_id, date_from=None, date_to=None, limit=200):
            return {"supported": False, "source": "", "orders": [],
                    "reason": "该数据源不提供订单数据"}

        def fetch_customer_reviews(self, shop_id, date_from=None, date_to=None, limit=200):
            return {"supported": False, "source": "", "reviews": [],
                    "reason": "该数据源不提供评论数据"}

    # ★ session 传 None 是刻意的：不支持时**根本不该碰数据库**，
    #   这条用例因此不依赖库里有数据，永远可跑。
    with pytest.raises(SourceNotSupported):
        await sync_orders_from_source(None, "store_any", _NoOrders())
    with pytest.raises(SourceNotSupported):
        await sync_reviews_from_source(None, "store_any", _NoOrders())


async def test_supported_but_zero_rows_is_not_an_error():
    """「支持，但这次一条都没有」必须**正常返回 0**，不能抛。

    ★ 与上面那条是一对：两条一起才把「不支持」与「0 条」真正分开。
      只留一条时，「0 条」的语义会被 raise 吞掉（或反过来）。
    """
    from modules.trade import sync_orders_from_source

    class _Empty:
        def fetch_orders(self, shop_id, date_from=None, date_to=None, limit=200):
            return {"supported": True, "source": "platform_api",
                    "orders": [], "reason": ""}

    out = await sync_orders_from_source(None, "store_any", _Empty())
    assert out["total"] == 0 and out["inserted"] == 0


# ============================================================================
# 需要 DB 的用例（单事务 + rollback）
# ============================================================================

async def test_upsert_order_is_idempotent():
    """同一份载荷跑两次：第一次 INSERT，第二次 UPDATE（inserted=0）。

    ★ 反向注入：把 `upsert_order` 里「先按业务键查」的那段删掉、
      改成无条件 `session.add(...)` ⇒ 第二次会撞主键或产生重复行，本条转红。
    """
    from core.database import async_session_factory
    from modules.trade import SOURCE_MOCK_SEED, upsert_order
    from modules.trade.db_model import OrderItemRecord, ShipmentRecord

    async with async_session_factory() as session:
        shop_id = await _first_shop_id(session)
        if shop_id is None:
            pytest.skip("库里没有任何店铺 —— 写入路径的前置数据缺失")
        payload = _order_payload()

        r1 = await upsert_order(session, shop_id, payload,
                                source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())
        r2 = await upsert_order(session, shop_id, payload,
                                source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())

        assert r1["inserted"] is True, "首次落库必须是 INSERT"
        assert r2["inserted"] is False, (
            "第二次必须是 UPDATE（inserted=False）—— 否则同一个订单号"
            "每同步一次就多一行，订单表会被重复数据淹掉"
        )
        assert r1["order"].id == r2["order"].id, "两次应命中同一行"

        # 明细与物流各只有一行（幂等键生效，不是「插了又插」）
        n_items = len((await session.execute(
            select(OrderItemRecord.id).where(
                OrderItemRecord.order_id == r1["order"].id))).scalars().all())
        n_shp = len((await session.execute(
            select(ShipmentRecord.id).where(
                ShipmentRecord.order_id == r1["order"].id))).scalars().all())
        assert n_items == 1 and n_shp == 1, (
            f"重跑后明细/物流必须仍各 1 行，实际 {n_items}/{n_shp}")
        await session.rollback()


async def test_delay_days_matches_service_rule():
    """落库行的 `transit_days` / `delay_days` 必须等于 service 算出来的值。

    ★★ 这条守的是「写入方不许自己算派生态」：
       若 `upsert_order` 里自己写了一段日期相减，只要它恰好算对，
       别的用例一条都不会红 —— 而口径已经分成两份了。
       ⇒ 这里**用 service 的结果当期望值**，自算的实现一旦与之分叉就转红。

    ★ 反向注入：把 `upsert_order` 里的 `compute_transit_and_delay(...)` 换成
      `(13, 7)` 之类自算结果 ⇒ 本条转红。
    """
    from core.database import async_session_factory
    from modules.trade import (
        SOURCE_MOCK_SEED, compute_transit_and_delay, upsert_order,
    )

    async with async_session_factory() as session:
        shop_id = await _first_shop_id(session)
        if shop_id is None:
            pytest.skip("库里没有任何店铺")
        payload = _order_payload("T-ORD-0002")
        res = await upsert_order(session, shop_id, payload,
                                 source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())
        row, shp = res["order"], res["shipment"]

        want_t, want_d = compute_transit_and_delay(
            payload["shipped_at"], payload["promised_at"], payload["delivered_at"])
        assert (row.transit_days, row.delay_days) == (want_t, want_d), (
            f"订单上的派生态 {(row.transit_days, row.delay_days)} 与 service "
            f"口径 {(want_t, want_d)} 不一致 —— 写入方自己算了一套")
        assert (shp.transit_days, shp.delay_days) == (want_t, want_d)
        assert (want_t, want_d) == (12, 7), "本载荷：在途 12 天 / 迟到 7 天"

        # ★★ 还没送到 ⇒ 派生态必须是 **None**，不是 0。
        #    为什么这条单独断言：只测「送达的情形」时，任何自算实现只要把
        #    天数算对就全绿 —— 而 `or 0` 这种抹平写法恰恰只在**未送达**时
        #    露出马脚（把「在途未签收」谎报成「准时送达」）。
        #    ★ 反向注入实测：把 service 调用换成写死 (12, 7)，上面的断言仍然绿，
        #      只有加了这一段之后才会红 —— 这条断言才是这条用例的价值所在。
        p2 = _order_payload("T-ORD-0002B")
        p2["delivered_at"] = None
        p2["shipment"] = dict(p2["shipment"], delivered_at=None)
        r2 = await upsert_order(session, shop_id, p2,
                                source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())
        assert r2["order"].transit_days is None, (
            "未送达时 transit_days 必须是 None（没有结论），不是 0")
        assert r2["order"].delay_days is None, (
            "未送达时 delay_days 必须是 None —— 写成 0 等于谎报「准时送达」")
        await session.rollback()


async def test_new_review_is_auto_attributed():
    """新落库的差评必须**自动**写归因并把 status 推到 `triaged`。

    ★ 为什么要有这条：没有自动归因时，工具层读到的是 `status='new'` 的裸评论，
      「这条差评为什么发生」就变成让 LLM 现场发挥 —— 同一条差评两次问出
      两个原因，而且无从对账。

    ★ 反向注入：把 `upsert_review` 的 `auto_attribute` 默认改成 False
      （或删掉那段）⇒ 本条转红。
    """
    from core.database import async_session_factory
    from modules.trade import SOURCE_MOCK_SEED, upsert_order, upsert_review
    from modules.trade.db_model import ReviewAttributionRecord

    async with async_session_factory() as session:
        shop_id = await _first_shop_id(session)
        if shop_id is None:
            pytest.skip("库里没有任何店铺")
        await upsert_order(session, shop_id, _order_payload("T-ORD-0003"),
                           source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())
        res = await upsert_review(
            session, shop_id,
            _review_payload(order_ref="T-ORD-0003", external="T-REV-0003"),
            source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())

        row = res["review"]
        assert res["inserted"] is True
        assert row.status == "triaged", (
            f"落库即归因 ⇒ status 应为 triaged，实际 {row.status!r}")
        # ★ order_ref 能对上自家订单时必须关联上
        assert row.order_id, "order_ref 能对上时必须关联到自家 orders.id"

        attr = (await session.execute(
            select(ReviewAttributionRecord).where(
                ReviewAttributionRecord.review_id == row.id)
        )).scalar_one_or_none()
        assert attr is not None, "必须自动写一条归因"
        assert attr.primary_cause in (
            "packaging_failure", "logistics_delay"), attr.primary_cause
        # ★ 证据必须能指到具体的订单号 / 运单号
        refs = " ".join(e.get("ref", "") for e in (attr.evidence or []))
        assert "T-ORD-0003" in refs or "1ZTEST0001" in refs, (
            f"归因证据必须引用订单号或运单号，实际：{attr.evidence}")
        await session.rollback()


async def test_manual_attribution_survives_resync():
    """人工指定的归因 **不许** 被下一次同步的规则重算覆盖。

    ★ 为什么值得一条用例：运营好不容易把一条误判改成正确归因，
      下一轮同步（每 6 小时一次）就把它冲回去了 —— 而且没有任何提示，
      表现为「我明明改过了，怎么又变回去了」。

    ★ 反向注入：删掉 `_attribute` 里 `elif attr.method == MANUAL_METHOD:
      return attr` 这一段 ⇒ 本条转红。
    """
    from core.database import async_session_factory
    from modules.trade import (
        MANUAL_METHOD, SOURCE_MOCK_SEED, review_row_id, upsert_review,
    )
    from modules.trade.db_model import ReviewAttributionRecord

    async with async_session_factory() as session:
        shop_id = await _first_shop_id(session)
        if shop_id is None:
            pytest.skip("库里没有任何店铺")
        payload = _review_payload(order_ref="T-ORD-NOPE", external="T-REV-0004")
        await upsert_review(session, shop_id, payload,
                            source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())

        # ★ 定位用**行 id 工厂**算出来的精确值，不用 like：
        #   like 会连带命中别家店/别条评论，scalar_one() 随即抛错，
        #   而那个错看起来像「归因没写」—— 排查方向完全反了。
        rid = review_row_id(PROBE_PLATFORM, shop_id, payload["external_review_id"])
        attr = (await session.execute(
            select(ReviewAttributionRecord).where(
                ReviewAttributionRecord.review_id == rid)
        )).scalar_one()
        attr.method = MANUAL_METHOD
        attr.primary_cause = "service_attitude"
        await session.flush()

        # 再同步一次（同一条评论）
        await upsert_review(session, shop_id, payload,
                            source=SOURCE_MOCK_SEED, fetched_at=NOW.isoformat())
        await session.flush()

        again = (await session.execute(
            select(ReviewAttributionRecord).where(
                ReviewAttributionRecord.review_id == rid)
        )).scalar_one()
        assert again.primary_cause == "service_attitude", (
            f"人工判定被规则重算覆盖了：{again.primary_cause}")
        assert again.method == MANUAL_METHOD
        await session.rollback()

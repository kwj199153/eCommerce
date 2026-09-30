"""选品市场洞察快照种子数据（第 305 轮 · 蓝海挖掘大盘云图）

==============================================================================
★ 演示 mock 只给演示账号：不脏真实账号
==============================================================================
老板的原话：「我需要的数据库中的 mock 数据都是给演示账号用的，这样才不会脏数据」。

本 seed 走 `only_for_shop_ids` 通道（复用 `modules/stores/demo.py::demo_store_ids()`），
**只给演示账号名下的店铺**灌市场洞察快照，真实账号名下店铺一行都不会写
⇒ 真实账号永远空态（fail-closed），直到将来接入第三方类目数据。

==============================================================================
★ 数据是「快照」，不是「实时市场」
==============================================================================
六维度（品类分布 / 价格带 / 竞争密度 / 搜索热度 / 卖家分布 / 趋势）打平成
数值列，站点 × 类目 × 日期 一行。演示数据带 `is_demo=True` + `source='mock_seed'`，
读层据此在响应里如实标注 `degraded: true`，不与真实同步混淆。

==============================================================================
★ 类目体系与蓝海挖掘 cascader 对齐（r309）
==============================================================================
category_path 一级 slug 必须与前端 BlueOceanConfig 的 cascader 一级一致
（home_kitchen / electronics / sports / beauty / toys / pet），否则「大盘 →
跳蓝海挖掘」预填会对不上类目。旧演示库的 sports_outdoors / home_living 已
改写并入；beauty / toys / pet 补齐快照让六个一级全有行情数据。

==============================================================================
★ 幂等：规格表 + 按「(shop_id, site, category_path, snapshot_date)」判空
==============================================================================
与 `modules/candidates/seed.py` 同款：id 追加店铺后缀防主键冲突；已有的快照
不覆盖。传 `only_for_shop_ids` 跳过全表守卫、按店铺判空。
"""

from typing import Sequence

from sqlalchemy import select

from core.database import async_session_factory
from core.stores import StoreRecord
from core.tenant.scoping import scope_condition
from modules.product_research.db_model import MarketSnapshotRecord

# 六维度演示快照：站点 × 类目 × 日期，覆盖亚马逊 / 虾皮典型选品场景。
# 蓝海评分由六维度综合（高搜索热度 + 低竞争密度 + 高增长 ⇒ 高分）。
SEED_MARKET_SNAPSHOTS = [
    # ===== Amazon US =====
    {
        "id": "msnap-000",
        "site": "amazon_us",
        "category_path": "home_kitchen/kitchen_dining/coffee",
        "category_name": "Coffee Machines",
        "listing_count": 48200,
        "price_min": 19.99,
        "price_max": 299.99,
        "price_median": 89.99,
        "seller_count": 3100,
        "search_volume": 1850000,
        "new_seller_count": 420,
        "search_growth": 18.5,
        "price_trend": "stable",
        "blue_ocean_score": 62,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-001",
        "site": "amazon_us",
        "category_path": "home_kitchen/kitchen_dining/coffee",
        "category_name": "Coffee Machines",
        "listing_count": 47500,
        "price_min": 19.99,
        "price_max": 289.99,
        "price_median": 87.50,
        "seller_count": 3050,
        "search_volume": 1720000,
        "new_seller_count": 398,
        "search_growth": 14.2,
        "price_trend": "stable",
        "blue_ocean_score": 60,
        "snapshot_date": "2026-08-29",
    },
    {
        "id": "msnap-002",
        "site": "amazon_us",
        "category_path": "electronics/accessories/stand",
        "category_name": "Phone Stands",
        "listing_count": 120000,
        "price_min": 7.99,
        "price_max": 59.99,
        "price_median": 18.99,
        "seller_count": 8200,
        "search_volume": 980000,
        "new_seller_count": 1500,
        "search_growth": 6.3,
        "price_trend": "falling",
        "blue_ocean_score": 38,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-003",
        "site": "amazon_us",
        "category_path": "home_kitchen/home_decor/lighting",
        "category_name": "Smart Lighting",
        "listing_count": 65000,
        "price_min": 12.99,
        "price_max": 199.99,
        "price_median": 34.99,
        "seller_count": 4100,
        "search_volume": 1240000,
        "new_seller_count": 680,
        "search_growth": 24.7,
        "price_trend": "rising",
        "blue_ocean_score": 71,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-004",
        "site": "amazon_us",
        "category_path": "sports/fitness/water_bottles",
        "category_name": "Water Bottles",
        "listing_count": 210000,
        "price_min": 5.99,
        "price_max": 45.99,
        "price_median": 14.99,
        "seller_count": 12500,
        "search_volume": 1560000,
        "new_seller_count": 2400,
        "search_growth": 3.1,
        "price_trend": "falling",
        "blue_ocean_score": 22,
        "snapshot_date": "2026-09-29",
    },
    # ===== Amazon UK =====
    {
        "id": "msnap-005",
        "site": "amazon_uk",
        "category_path": "home_kitchen/kitchen_dining/coffee",
        "category_name": "Coffee Machines",
        "listing_count": 21000,
        "price_min": 15.99,
        "price_max": 249.99,
        "price_median": 74.99,
        "seller_count": 1600,
        "search_volume": 620000,
        "new_seller_count": 210,
        "search_growth": 12.8,
        "price_trend": "stable",
        "blue_ocean_score": 58,
        "snapshot_date": "2026-09-29",
    },
    # ===== Shopee SG =====
    {
        "id": "msnap-006",
        "site": "shopee_sg",
        "category_path": "home_kitchen/storage/kitchen_storage",
        "category_name": "Kitchen Storage",
        "listing_count": 88000,
        "price_min": 3.50,
        "price_max": 39.99,
        "price_median": 12.90,
        "seller_count": 6900,
        "search_volume": 450000,
        "new_seller_count": 1900,
        "search_growth": 9.6,
        "price_trend": "rising",
        "blue_ocean_score": 49,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-007",
        "site": "shopee_sg",
        "category_path": "home_kitchen/storage/kitchen_storage",
        "category_name": "Kitchen Storage",
        "listing_count": 86000,
        "price_min": 3.50,
        "price_max": 38.99,
        "price_median": 12.50,
        "seller_count": 6800,
        "search_volume": 410000,
        "new_seller_count": 1750,
        "search_growth": 7.4,
        "price_trend": "rising",
        "blue_ocean_score": 47,
        "snapshot_date": "2026-08-29",
    },
    # ===== Amazon US（r309 补齐 beauty / toys / pet，六个一级类目全有行情） =====
    {
        "id": "msnap-008",
        "site": "amazon_us",
        "category_path": "beauty/skincare/serum",
        "category_name": "Face Serums",
        "listing_count": 78000,
        "price_min": 8.99,
        "price_max": 79.99,
        "price_median": 24.99,
        "seller_count": 5200,
        "search_volume": 890000,
        "new_seller_count": 950,
        "search_growth": 21.3,
        "price_trend": "rising",
        "blue_ocean_score": 66,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-009",
        "site": "amazon_us",
        "category_path": "toys/educational/stem_kits",
        "category_name": "STEM Kits",
        "listing_count": 34000,
        "price_min": 15.99,
        "price_max": 129.99,
        "price_median": 42.50,
        "seller_count": 2400,
        "search_volume": 520000,
        "new_seller_count": 410,
        "search_growth": 15.8,
        "price_trend": "rising",
        "blue_ocean_score": 55,
        "snapshot_date": "2026-09-29",
    },
    {
        "id": "msnap-010",
        "site": "amazon_us",
        "category_path": "pet/dog_supplies/chew_toys",
        "category_name": "Dog Chew Toys",
        "listing_count": 156000,
        "price_min": 4.99,
        "price_max": 39.99,
        "price_median": 11.99,
        "seller_count": 9800,
        "search_volume": 1120000,
        "new_seller_count": 2100,
        "search_growth": 1.9,
        "price_trend": "falling",
        "blue_ocean_score": 41,
        "snapshot_date": "2026-09-29",
    },
]


async def seed_market_snapshots_if_empty(
    *, only_for_shop_ids: Sequence[str] = (),
) -> int:
    """
    给**演示账号名下店铺**灌市场洞察快照（幂等）。

    Args:
        only_for_shop_ids: 只给点名店铺补灌；**不传则默认只灌演示店铺**
            （与其余 seed 的「不传=全店」不同：市场洞察 mock 只该进演示店）。

    Returns:
        实际写入条数。

    ★ 为什么「不传=只灌演示店」而不是「不传=全店」：
      市场洞察 mock 是**演示专用**数据，真实账号名下店铺绝不该被它污染
      （老板：mock 只给演示账号用，这样才不会脏数据）。所以默认目标就是
      演示店铺，`only_for_shop_ids` 只是额外把点名店铺也纳入（幂等，已有的不动）。

    ★ 幂等键：(shop_id, site, category_path, snapshot_date) 判空 ——
      同一类目同一天的快照只灌一次；id 追加店铺后缀防主键冲突。
    """
    from modules.stores import demo_store_ids  # 走门面（`modules/stores/__init__` 已进 `__all__`）

    async with async_session_factory() as session:
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        # 目标店铺 = 演示店铺 ∪ 点名店铺（都必须是真实存在的店）
        demo_ids = await demo_store_ids()
        targets = set(demo_ids)
        if only_for_shop_ids:
            known = set(shop_ids)
            targets.update(s for s in only_for_shop_ids if s in known)

        if not targets:
            return 0

        total = 0
        for shop_id in sorted(targets):
            for data in SEED_MARKET_SNAPSHOTS:
                existing = (
                    await session.execute(
                        select(MarketSnapshotRecord.id).where(
                            scope_condition(MarketSnapshotRecord, shop_id),
                            MarketSnapshotRecord.site == data["site"],
                            MarketSnapshotRecord.category_path == data["category_path"],
                            MarketSnapshotRecord.snapshot_date == data["snapshot_date"],
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue

                session.add(
                    MarketSnapshotRecord(
                        id=f"{data['id']}-{shop_id}",
                        site=data["site"],
                        category_path=data["category_path"],
                        category_name=data["category_name"],
                        listing_count=data["listing_count"],
                        price_min=data["price_min"],
                        price_max=data["price_max"],
                        price_median=data["price_median"],
                        seller_count=data["seller_count"],
                        search_volume=data["search_volume"],
                        new_seller_count=data["new_seller_count"],
                        search_growth=data["search_growth"],
                        price_trend=data["price_trend"],
                        blue_ocean_score=data["blue_ocean_score"],
                        snapshot_date=data["snapshot_date"],
                        shop_id=shop_id,
                        is_demo=True,
                        source="mock_seed",
                    )
                )
                total += 1

        await session.commit()

    return total

"""
竞品监控池 - 种子数据预置

启动时若 `monitors` 表为空，预置一批演示数据，让 7 个面板一打开就有内容可看。
与 products / assets / candidates 的 `seed_xxx_if_empty()` 惯例一致，在 main.py
的 lifespan 里调用。

**与既有 seed 的关键差异：这里不硬编码 shop_id。**

既有 candidates/seed.py 把 `shop_id` 写成 `"shop-1"`，而真实租户 id 是
`X-Shop-ID` 头传进来的 `store_xxxxxxxx`（store_ 前缀 + 8 位 hex）——
两者格式对不上，导致那批种子数据**任何请求都查不到**（列表端点按 shop_id 过滤），
属于「灌了但等于没灌」。

本模块改为：**先查 `stores_store` 取真实店铺 id，再为每个店铺各灌一份**。
好处有二：
  1. 切到任意店铺都能看到演示数据，演示体验完整；
  2. 数据库里没有店铺时直接跳过 —— 没有租户上下文，灌了也看不到，
     不如不灌（避免又造一批死数据）。

分组**不预置**：前端的产品设定是「分组由用户自建，无预设」，seed 记录的
`group_ids` 一律留空、落进默认的「未分组」视图，不改变该设定。
"""

from datetime import datetime
from typing import Dict, List

from sqlalchemy import select, func

from core.database import async_session_factory
from modules.monitors.db_model import MonitorRecord
from modules.monitors.snapshot import build_time_series
from core.stores import StoreRecord


# 演示竞品档案（6 条覆盖 4 种监控动机：对标爆款/低价走量/对标店铺/对标品牌/新品观察）
SEED_SPECS: List[Dict] = [
    {
        "asin": "B0MONPRO01", "brand": "ZestPro",
        "title": "Portable Espresso Maker 20 Bar Electric for Travel",
        "image": "/mock/products/B0CXXXX001.png",
        "base_price": 69.99, "base_bsr": 842, "rating": 4.3,
        "review_count": 3120, "month_sales": 3600,
        "note": "核心对标爆款，主图/五点每周更新一次",
    },
    {
        "asin": "B0MONPRO02", "brand": "BrewMate",
        "title": "Manual Espresso Machine Portable Mini Coffee Press",
        "image": "/mock/products/B0CXXXX002.png",
        "base_price": 34.99, "base_bsr": 1805, "rating": 3.9,
        "review_count": 958, "month_sales": 1200,
        "note": "低价走量款，近两周连续降价抢排名",
    },
    {
        "asin": "B0MONSTO01", "brand": "CafeNow",
        "title": "CafeNow Cold Brew Maker 2L with Reusable Filter",
        "image": "/mock/products/B0CXXXX003.png",
        "base_price": 45.5, "base_bsr": 2660, "rating": 4.1,
        "review_count": 5241, "month_sales": 2100,
        "note": "同一店铺多链接，重点跟踪店铺整体上新节奏",
    },
    {
        "asin": "B0MONBRD01", "brand": "Voltage",
        "title": "Voltage 100W Fast Charger USB C GaN Wall Charger",
        "image": "/mock/products/B0CXXXX004.png",
        "base_price": 29.99, "base_bsr": 421, "rating": 4.6,
        "review_count": 18732, "month_sales": 15000,
        "note": "类目头部品牌，监视其促销节奏与变体扩张",
    },
    {
        "asin": "B0MONBRD02", "brand": "Voltage",
        "title": "Voltage 3-in-1 Magnetic Wireless Charging Stand",
        "image": "/mock/products/B0CXXXX005.png",
        "base_price": 49.99, "base_bsr": 980, "rating": 4.5,
        "review_count": 6404, "month_sales": 6800,
        "note": "同品牌衍生款，注意是否复制爆款打法",
    },
    {
        "asin": "B0MONPRO03", "brand": "AeroHeat",
        "title": "Smart Portable Heater with Thermostat & Remote",
        "image": "/mock/products/B0CXXXX006.png",
        "base_price": 55.0, "base_bsr": 3200, "rating": 3.7,
        "review_count": 402, "month_sales": 640,
        "note": "新进入者，评分偏低，观察差评是否限制起量",
    },
]


def build_seed_record(shop_id: str, spec: Dict, idx: int) -> MonitorRecord:
    """由规格构造一条带完整 30 天时序的演示记录"""
    ts = build_time_series(
        asin=spec["asin"],
        base_price=spec["base_price"],
        base_bsr=spec["base_bsr"],
        month_sales=spec["month_sales"],
        idx=idx,
    )
    return MonitorRecord(
        id=f"mon-{spec['asin']}-{shop_id or 'demo'}",
        asin=spec["asin"],
        shop_id=shop_id,
        title=spec["title"],
        brand=spec["brand"],
        main_image=spec["image"],
        marketplace="us",
        currency="USD",
        latest_price=ts["latest_price"],
        price_change_7d=ts["price_change_7d"],
        latest_bsr=ts["latest_bsr"],
        # 与前端既有实现保持一致：这一列存的是「监控动机备注」而非类目名
        bsr_category=spec["note"],
        bsr_change_7d=ts["bsr_change_7d"],
        rating=spec["rating"],
        review_count=spec["review_count"],
        reviews_added_7d=ts["reviews_added_7d"],
        stock_status=ts["stock_status"],
        estimated_units_remaining=ts["estimated_units_remaining"],
        est_monthly_sales=spec["month_sales"],
        price_history=ts["price_history"],
        bsr_history=ts["bsr_history"],
        review_events=ts["review_events"],
        variations=ts["variations"],
        listing_changes=ts["listing_changes"],
        group_ids=[],
        origin="manual",
        added_at="2026-09-01T00:00:00Z",
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )


async def seed_monitors_if_empty() -> int:
    """
    首次启动时，若 monitors 表为空，**为每个已存在的店铺**预置演示数据。

    Returns:
        实际写入的条数（表非空、或无店铺可归属时返回 0）。
    """
    async with async_session_factory() as session:
        existing = (await session.execute(
            select(func.count()).select_from(MonitorRecord)
        )).scalar_one()
        if existing > 0:
            return 0

        # 取真实店铺 id；一个都没有则跳过（无租户上下文，灌了也查不到）
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        total = 0
        for shop_id in shop_ids:
            for idx, spec in enumerate(SEED_SPECS):
                session.add(build_seed_record(shop_id, spec, idx))
                total += 1
        await session.commit()

    return total

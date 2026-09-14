"""
候选选品库种子数据

首次启动（candidates 表为空）时，预置几条候选选品供演示，
展示「待评审 / 评审中 / 已淘汰」等评审状态机。

数据为演示 mock，后续接入真实选品分析师产出后替换。

**shop_id 不硬编码**：早期版本把 `shop_id` 写成 `"shop-1"`，而真实租户 id 是
`X-Shop-ID` 头传进来的 `store_xxxxxxxx`（store_ 前缀 + 8 位 hex）——两者格式
对不上，列表端点按 shop_id 过滤后**一条都查不到**，等于「灌了但没灌」。
现改为启动时先查 `stores_store` 取真实店铺 id，再为每个店铺各灌一份；
库里没有店铺则直接跳过（没有租户上下文，灌了也看不到）。

注意本表是 **id 单主键**（无 `(shop_id, asin)` 唯一约束），多店铺灌入必须给
记录 id 追加店铺后缀，否则第二个店铺会主键冲突。
"""

from sqlalchemy import select, func
from core.database import async_session_factory
from modules.candidates.db_model import CandidateRecord
from modules.stores.db_model import StoreRecord

SEED_CANDIDATES = [
    {
        "id": "cand-000",
        "asin": "B0CAND0001",
        "sku": "SKU-CAND-000",
        "title": "Sunset Projection Alarm Clock with Sunrise Simulation & White Noise",
        "brand": "SunRise",
        "category": "home",
        "sub_category": "智能家居",
        "price": 32.99,
        "currency": "USD",
        "site": "Amazon US",
        "estimated_monthly_sales": 4200,
        "review_count": 856,
        "rating": 4.4,
        "bsr": 2345,
        "bsr_category": "Home & Kitchen > Alarm Clocks",
        "listed_date": "2025-11-20",
        "roi_estimated": 142,
        "margin": 58,
        "blue_ocean_score": 86,
        "overall_listing_score": 71,
        "keywords": ["sunrise alarm clock", "wake up light", "white noise machine", "projection clock"],
        "competitor_asins": ["B0COMP0001", "B0COMP0002", "B0COMP0003"],
        "selling_points": "日出模拟自然唤醒 | 白噪音助眠 | 星空投影 | 无线充电",
        "main_image": "https://picsum.photos/seed/B0CAND0001/600/600",
        "images": ["https://picsum.photos/seed/B0CAND0001-a/600/600"],
        "source": "blue_ocean",
        "review_status": "pending",
        "review_notes": "",
        "reviewed_at": None,
        "reviewed_by": None,
        "monitor_data": None,
        "last_monitored_at": None,
        "tags": ["蓝海挖掘", "评分:86", "ROI:142%"],
        "notes": "高潜力蓝海，竞争度低，建议优先评审",
        "groups": [],
        "created_at": "2026-09-05T09:00:00Z",
    },
    {
        "id": "cand-001",
        "asin": "B0CAND0002",
        "sku": "SKU-CAND-001",
        "title": "Magnetic Phone Stand Foldable Aluminum Desktop Holder Adjustable",
        "brand": "MagHold",
        "category": "electronics",
        "sub_category": "手机配件",
        "price": 18.99,
        "currency": "USD",
        "site": "Amazon US",
        "estimated_monthly_sales": 6800,
        "review_count": 2134,
        "rating": 4.6,
        "bsr": 1234,
        "bsr_category": "Electronics > Cell Phone Stands",
        "listed_date": "2025-08-15",
        "roi_estimated": 185,
        "margin": 64,
        "blue_ocean_score": 74,
        "overall_listing_score": 78,
        "keywords": ["phone stand", "magnetic phone holder", "desk phone stand", "foldable stand"],
        "competitor_asins": ["B0COMP0010", "B0COMP0011"],
        "selling_points": "磁吸稳固 | 可折叠便携 | 多角度调节 | 铝合金材质",
        "main_image": "https://picsum.photos/seed/B0CAND0002/600/600",
        "images": ["https://picsum.photos/seed/B0CAND0002-a/600/600"],
        "source": "blue_ocean",
        "review_status": "under_review",
        "review_notes": "竞品监控中，观察价格波动",
        "reviewed_at": "2026-09-05T14:00:00Z",
        "reviewed_by": "运营",
        "monitor_data": {
            "price_trend": "stable",
            "last_price": 18.99,
            "competitor_count": 12,
            "review_growth": "fast",
        },
        "last_monitored_at": "2026-09-05T14:00:00Z",
        "tags": ["蓝海挖掘", "评审中"],
        "notes": "磁吸配件赛道，需关注专利风险",
        "groups": [],
        "created_at": "2026-09-04T10:00:00Z",
    },
    {
        "id": "cand-002",
        "asin": "B0CAND0003",
        "sku": "SKU-CAND-002",
        "title": "Silicone Collapsible Travel Cup Folding Water Bottle Leakproof",
        "brand": "FoldCup",
        "category": "sports",
        "sub_category": "户外水具",
        "price": 14.99,
        "currency": "USD",
        "site": "Amazon US",
        "estimated_monthly_sales": 2900,
        "review_count": 642,
        "rating": 4.1,
        "bsr": 5678,
        "bsr_category": "Sports & Outdoors > Water Bottles",
        "listed_date": "2025-06-10",
        "roi_estimated": 96,
        "margin": 49,
        "blue_ocean_score": 52,
        "overall_listing_score": 58,
        "keywords": ["collapsible cup", "folding water bottle", "travel cup", "silicone bottle"],
        "competitor_asins": ["B0COMP0020", "B0COMP0021", "B0COMP0022", "B0COMP0023"],
        "selling_points": "折叠收纳 | 硅胶食品级 | 防漏设计 | 轻量便携",
        "main_image": "https://picsum.photos/seed/B0CAND0003/600/600",
        "images": [],
        "source": "blue_ocean",
        "review_status": "rejected",
        "review_notes": "竞争已趋饱和，毛利偏低，暂缓",
        "reviewed_at": "2026-09-03T16:00:00Z",
        "reviewed_by": "运营",
        "monitor_data": None,
        "last_monitored_at": None,
        "tags": ["蓝海挖掘", "已淘汰"],
        "notes": "竞品过多，蓝海评分偏低",
        "groups": [],
        "created_at": "2026-09-02T11:00:00Z",
    },
]


async def seed_candidates_if_empty() -> int:
    """
    首次启动时，若 candidates 表为空，**为每个已存在的店铺**预置种子数据。

    Returns:
        实际写入的条数（表非空、或无店铺可归属时返回 0）。
    """
    async with async_session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(CandidateRecord))).scalar_one()
        if count > 0:
            return 0

        # 取真实店铺 id；一个都没有则跳过（无租户上下文，灌了也查不到）
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            return 0

        total = 0
        for shop_id in shop_ids:
            for data in SEED_CANDIDATES:
                record = CandidateRecord(
                    id=f"{data['id']}-{shop_id}",
                    asin=data["asin"],
                    sku=data["sku"],
                    title=data["title"],
                    brand=data["brand"],
                    category=data["category"],
                    sub_category=data["sub_category"],
                    price=data["price"],
                    currency=data["currency"],
                    site=data["site"],
                    estimated_monthly_sales=data["estimated_monthly_sales"],
                    review_count=data["review_count"],
                    rating=data["rating"],
                    bsr=data["bsr"],
                    bsr_category=data["bsr_category"],
                    listed_date=data["listed_date"],
                    roi_estimated=data["roi_estimated"],
                    margin=data["margin"],
                    blue_ocean_score=data["blue_ocean_score"],
                    overall_listing_score=data["overall_listing_score"],
                    keywords=data["keywords"],
                    competitor_asins=data["competitor_asins"],
                    selling_points=data["selling_points"],
                    main_image=data["main_image"],
                    images=data["images"],
                    source=data["source"],
                    review_status=data["review_status"],
                    review_notes=data["review_notes"],
                    reviewed_at=data["reviewed_at"],
                    reviewed_by=data["reviewed_by"],
                    monitor_data=data["monitor_data"],
                    last_monitored_at=data["last_monitored_at"],
                    shop_id=shop_id,
                    tags=data["tags"],
                    notes=data["notes"],
                    groups=data["groups"],
                    created_at=data["created_at"],
                    updated_at=data["created_at"],
                )
                session.add(record)
                total += 1
        await session.commit()

    return total

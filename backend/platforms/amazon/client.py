"""
Amazon 平台适配器

Phase 2 MVP 使用模拟数据演示完整流程。
后续升级：接入 Amazon SP-API 获取真实数据。

功能：
- 产品搜索（模拟）
- 关键词数据（模拟）
- FBA 费用计算（真实算法）
- 评论数据（模拟）
- BSR 排名（模拟）
"""

import random
from typing import List, Optional
from datetime import datetime, timedelta

from platforms.base import (
    PlatformAdapter,
    PlatformType,
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
    CompetitorAnalysis,
)


# ====== 模拟数据池 ======

# 类目分组键 —— 与前端 BlueOceanConfig 的类目选项严格一致
# （修复记录：原先 service 内部另有一套 sports_outdoors / pet_supplies / toys_games
#  等 key，与前端下发的 sports / pet / toys 对不上 → category_pool.get() 永远落空
#  → 选任何类目都退回 home_kitchen。此处以「前端契约」为准统一。）
CATEGORY_KEYS = ("home_kitchen", "electronics", "sports", "beauty", "toys", "pet")

# 统一商品池（唯一权威源）
#
# 修复记录：此前 mock 商品分裂在三处且 ASIN 命名空间互不相通 ——
#   ① 本文件的 MOCK_PRODUCTS（5 条）           ← 选品 Agent 走这里
#   ② service._generate_mock_blue_ocean_products（~18 条 B0CXXXX 型）← REST 蓝海端点走这里
#   ③ 前端 mock/data.ts getBlueOceanCandidates（8 条）              ← 右栏工具卡走这里
# ①② 已在此合并为一处；③ 见前端 toolExecutors 的「后端优先」改造。
#
# 字段说明（规范名，勿再引入 sales/reviews 等同义别名）：
#   review_count / estimated_monthly_sales 为规范名；roi 为该商品的预估 ROI（%）。
MOCK_PRODUCTS = [
    {
        "asin": "B0CGLKP2R1",
        "title": "Portable Coffee Grinder, Electric Burr Coffee Bean Grinder with Adjustable Settings",
        "price": 29.99,
        "rating": 4.3,
        "review_count": 2847,
        "category": "Home & Kitchen > Kitchen & Dining > Coffee, Tea & Espresso",
        "category_key": "home_kitchen",
        "brand": "BurrMaster",
        "image_url": "https://m.media-amazon.com/images/I/71example.jpg",
        "estimated_monthly_sales": 4500,
        "bsr_rank": 1234,
        "roi": 32.5,
    },
    {
        "asin": "B0DXYZ1234",
        "title": "Automatic Pet Feeder, Smart Food Dispenser with WiFi App Control for Cats and Dogs",
        "price": 49.99,
        "rating": 4.1,
        "review_count": 1523,
        "category": "Pet Supplies > Dog Supplies > Automatic Feeders",
        "category_key": "pet",
        "brand": "PetTech Pro",
        "image_url": "https://m.media-amazon.com/images/I/72example.jpg",
        "estimated_monthly_sales": 3200,
        "bsr_rank": 567,
        "roi": 28.4,
    },
    {
        "asin": "B0FABC5678",
        "title": "Desktop Organizer Set, Mesh Office Supplies Storage with Drawer and Pen Holder",
        "price": 18.99,
        "rating": 4.5,
        "review_count": 8934,
        "category": "Office Products > Desk Accessories & Workspace Organizers",
        "category_key": "home_kitchen",
        "brand": "DeskPro",
        "image_url": "https://m.media-amazon.com/images/I/73example.jpg",
        "estimated_monthly_sales": 8900,
        "bsr_rank": 234,
        "roi": 24.1,
    },
    {
        "asin": "B0GHIJ9012",
        "title": "LED Grow Lights for Indoor Plants, Full Spectrum Plant Growing Lamp with Timer",
        "price": 35.99,
        "rating": 4.2,
        "review_count": 2156,
        "category": "Lawn & Garden > Plant Growing Equipment > Grow Lights",
        "category_key": "home_kitchen",
        "brand": "GrowSmart",
        "image_url": "https://m.media-amazon.com/images/I/74example.jpg",
        "estimated_monthly_sales": 2800,
        "bsr_rank": 890,
        "roi": 30.8,
    },
    {
        "asin": "B0KLMN3456",
        "title": "Yoga Mat with Alignment Lines, Non-Slip Exercise Mat for Yoga, Pilates & Fitness",
        "price": 25.99,
        "rating": 4.6,
        "review_count": 12453,
        "category": "Sports & Fitness > Yoga > Mats",
        "category_key": "sports",
        "brand": "FlexFit",
        "image_url": "https://m.media-amazon.com/images/I/75example.jpg",
        "estimated_monthly_sales": 12000,
        "bsr_rank": 89,
        "roi": 21.7,
    },
    {
        "asin": "B0HUMI0001",
        "title": "Portable Mini Humidifier for Bedroom Desk USB Cool Mist",
        "price": 24.99,
        "rating": 4.4,
        "review_count": 45,
        "category": "Home & Kitchen > Heating, Cooling & Air Quality > Humidifiers",
        "category_key": "home_kitchen",
        "brand": "MistGo",
        "image_url": "https://m.media-amazon.com/images/I/76example.jpg",
        "estimated_monthly_sales": 1200,
        "bsr_rank": 3120,
        "roi": 35.2,
    },
    {
        "asin": "B0KUTN0002",
        "title": "Silicone Kitchen Utensil Set 43 Pcs Non-Stick Cooking Tools",
        "price": 29.99,
        "rating": 4.5,
        "review_count": 78,
        "category": "Home & Kitchen > Kitchen & Dining > Kitchen Utensils & Gadgets",
        "category_key": "home_kitchen",
        "brand": "ChefLine",
        "image_url": "https://m.media-amazon.com/images/I/77example.jpg",
        "estimated_monthly_sales": 890,
        "bsr_rank": 4560,
        "roi": 28.5,
    },
    {
        "asin": "B0CUTB0003",
        "title": "Bamboo Cutting Board with Juice Groove Kitchen Chopping",
        "price": 22.99,
        "rating": 4.3,
        "review_count": 56,
        "category": "Home & Kitchen > Kitchen & Dining > Cutting Boards",
        "category_key": "home_kitchen",
        "brand": "BambooWay",
        "image_url": "https://m.media-amazon.com/images/I/78example.jpg",
        "estimated_monthly_sales": 750,
        "bsr_rank": 5230,
        "roi": 38.4,
    },
    {
        "asin": "B0CANO0004",
        "title": "Electric Can Opener Smooth Edge Automatic",
        "price": 19.99,
        "rating": 4.2,
        "review_count": 34,
        "category": "Home & Kitchen > Kitchen & Dining > Can Openers",
        "category_key": "home_kitchen",
        "brand": "OpenEasy",
        "image_url": "https://m.media-amazon.com/images/I/79example.jpg",
        "estimated_monthly_sales": 650,
        "bsr_rank": 6710,
        "roi": 42.1,
    },
    {
        "asin": "B0GLSF0005",
        "title": "Glass Food Storage Containers Airtight Lids Meal Prep",
        "price": 27.99,
        "rating": 4.6,
        "review_count": 92,
        "category": "Home & Kitchen > Kitchen & Dining > Food Storage",
        "category_key": "home_kitchen",
        "brand": "FreshKeep",
        "image_url": "https://m.media-amazon.com/images/I/80example.jpg",
        "estimated_monthly_sales": 1100,
        "bsr_rank": 3890,
        "roi": 31.2,
    },
    {
        "asin": "B0RSBD0006",
        "title": "Resistance Bands Set Exercise Workout Bands Fitness",
        "price": 15.99,
        "rating": 4.4,
        "review_count": 234,
        "category": "Sports & Outdoors > Fitness > Strength Training",
        "category_key": "sports",
        "brand": "FitLoop",
        "image_url": "https://m.media-amazon.com/images/I/81example.jpg",
        "estimated_monthly_sales": 3200,
        "bsr_rank": 1120,
        "roi": 18.6,
    },
    {
        "asin": "B0JMPR0007",
        "title": "Jump Rope Adjustable Speed Skipping Rope Fitness",
        "price": 9.99,
        "rating": 4.3,
        "review_count": 167,
        "category": "Sports & Outdoors > Fitness > Cardio Training",
        "category_key": "sports",
        "brand": "SpeedRope",
        "image_url": "https://m.media-amazon.com/images/I/82example.jpg",
        "estimated_monthly_sales": 2800,
        "bsr_rank": 1450,
        "roi": 25.3,
    },
    {
        "asin": "B0PSHB0008",
        "title": "Push Up Board Multi-function Foldable Home Gym",
        "price": 24.99,
        "rating": 4.2,
        "review_count": 42,
        "category": "Sports & Outdoors > Fitness > Strength Training",
        "category_key": "sports",
        "brand": "HomeGymX",
        "image_url": "https://m.media-amazon.com/images/I/83example.jpg",
        "estimated_monthly_sales": 560,
        "bsr_rank": 7120,
        "roi": 36.8,
    },
    {
        "asin": "B0ACRO0009",
        "title": "Acrylic Organizer Makeup Storage Drawer Cosmetic Box",
        "price": 19.99,
        "rating": 4.5,
        "review_count": 89,
        "category": "Beauty & Personal Care > Tools & Accessories > Makeup Organizers",
        "category_key": "beauty",
        "brand": "ClearVanity",
        "image_url": "https://m.media-amazon.com/images/I/84example.jpg",
        "estimated_monthly_sales": 1800,
        "bsr_rank": 2760,
        "roi": 31.8,
    },
    {
        "asin": "B0VANL0010",
        "title": "LED Vanity Mirror Lights Strip Makeup Mirror",
        "price": 16.99,
        "rating": 4.1,
        "review_count": 123,
        "category": "Beauty & Personal Care > Tools & Accessories > Mirror Lights",
        "category_key": "beauty",
        "brand": "GlowLine",
        "image_url": "https://m.media-amazon.com/images/I/85example.jpg",
        "estimated_monthly_sales": 1400,
        "bsr_rank": 4180,
        "roi": 26.4,
    },
    {
        "asin": "B0JADE0011",
        "title": "Jade Roller Gua Sha Facial Beauty Tools Set",
        "price": 14.99,
        "rating": 4.4,
        "review_count": 198,
        "category": "Beauty & Personal Care > Skin Care > Facial Tools",
        "category_key": "beauty",
        "brand": "PureStone",
        "image_url": "https://m.media-amazon.com/images/I/86example.jpg",
        "estimated_monthly_sales": 2100,
        "bsr_rank": 2140,
        "roi": 22.1,
    },
    {
        "asin": "B0WCHG0012",
        "title": "Wireless Charging Pad Fast Charger Stand for Phone",
        "price": 18.99,
        "rating": 4.2,
        "review_count": 198,
        "category": "Electronics > Accessories & Supplies > Chargers & Adapters",
        "category_key": "electronics",
        "brand": "VoltPad",
        "image_url": "https://m.media-amazon.com/images/I/87example.jpg",
        "estimated_monthly_sales": 1450,
        "bsr_rank": 3020,
        "roi": 19.2,
    },
    {
        "asin": "B0EARB0013",
        "title": "Wireless Earbuds Bluetooth 5.3 Noise Cancelling in Ear Headphones",
        "price": 39.99,
        "rating": 4.3,
        "review_count": 32,
        "category": "Electronics > Headphones & Earbuds > Earbud Headphones",
        "category_key": "electronics",
        "brand": "SoundPod",
        "image_url": "https://m.media-amazon.com/images/I/88example.jpg",
        "estimated_monthly_sales": 650,
        "bsr_rank": 6840,
        "roi": 42.1,
    },
    {
        "asin": "B0USBC0014",
        "title": "USB C Hub Multiport Adapter Type C Docking Station",
        "price": 29.99,
        "rating": 4.4,
        "review_count": 145,
        "category": "Electronics > Computers & Accessories > Hubs",
        "category_key": "electronics",
        "brand": "PortX",
        "image_url": "https://m.media-amazon.com/images/I/89example.jpg",
        "estimated_monthly_sales": 890,
        "bsr_rank": 4870,
        "roi": 21.5,
    },
    {
        "asin": "B0PGRM0015",
        "title": "Pet Grooming Brush Deshedding Tool for Dogs Cats",
        "price": 12.99,
        "rating": 4.5,
        "review_count": 156,
        "category": "Pet Supplies > Grooming > Brushes",
        "category_key": "pet",
        "brand": "FurAway",
        "image_url": "https://m.media-amazon.com/images/I/90example.jpg",
        "estimated_monthly_sales": 1900,
        "bsr_rank": 1980,
        "roi": 24.6,
    },
    {
        "asin": "B0DPUZ0016",
        "title": "Dog Puzzle Toys Interactive Treat Dispenser Slow Feeder",
        "price": 17.99,
        "rating": 4.2,
        "review_count": 67,
        "category": "Pet Supplies > Dog Supplies > Toys",
        "category_key": "pet",
        "brand": "PawPuzzle",
        "image_url": "https://m.media-amazon.com/images/I/91example.jpg",
        "estimated_monthly_sales": 720,
        "bsr_rank": 5340,
        "roi": 33.2,
    },
    {
        "asin": "B0BLKS0017",
        "title": "Building Blocks STEM Educational Toy Kids Ages 4-8",
        "price": 21.99,
        "rating": 4.6,
        "review_count": 38,
        "category": "Toys & Games > Learning & Education > Building Toys",
        "category_key": "toys",
        "brand": "BrickLab",
        "image_url": "https://m.media-amazon.com/images/I/92example.jpg",
        "estimated_monthly_sales": 480,
        "bsr_rank": 6910,
        "roi": 39.5,
    },
    {
        "asin": "B0FDGT0018",
        "title": "Fidget Toys Pack Sensory Tools Stress Relief Adults Kids",
        "price": 11.99,
        "rating": 4.1,
        "review_count": 289,
        "category": "Toys & Games > Novelty & Gag Toys > Fidget Toys",
        "category_key": "toys",
        "brand": "CalmKit",
        "image_url": "https://m.media-amazon.com/images/I/93example.jpg",
        "estimated_monthly_sales": 3500,
        "bsr_rank": 860,
        "roi": 17.8,
    },
]


def get_mock_products(category_key: Optional[str] = None) -> List[dict]:
    """
    读取统一 Mock 商品池（唯一权威源）。

    所有需要「商品实体」的调用方（选品 Agent 的蓝海挖掘、REST 蓝海端点、
    关键词 → 商品匹配）都必须经由此函数取数，禁止再各自维护一份内联商品表。

    Args:
        category_key: 可选类目键（见 CATEGORY_KEYS）。None 或未收录 → 返回全池。

    Returns:
        商品 dict 列表（深拷贝，调用方可安全修改）。
    """
    pool = MOCK_PRODUCTS
    if category_key and category_key in CATEGORY_KEYS:
        pool = [p for p in pool if p.get("category_key") == category_key] or MOCK_PRODUCTS
    return [dict(p) for p in pool]


# 检索用停用词：无区分度，命中它们只会制造假相关
_SEARCH_STOPWORDS = {
    "for", "with", "and", "the", "of", "to", "in", "on", "an", "by",
    "set", "pack", "pcs", "pc", "piece", "pieces", "inch", "inches",
    "new", "best", "good", "top",
}


def tokenize(text: str) -> List[str]:
    """
    把查询/标题切成用于 token 命中的词（小写、去停用词、长度 > 2）。

    用于「关键词 → 商品」的标题匹配：这是 mock 阶段商品检索的唯一判据。
    """
    import re as _re

    raw = _re.split(r"[^0-9a-zA-Z]+", (text or "").lower())
    return [t for t in raw if len(t) > 2 and t not in _SEARCH_STOPWORDS]


def match_products_by_keyword(keyword: str, limit: int = 5) -> List[dict]:
    """
    关键词 → 商品 的确定性匹配（供选品 Agent 把「词机会」落到「具体货」）。

    匹配规则：把关键词切成 token，在商品的 title/brand/category 上做**词边界**
    命中打分——按命中数降序、同分按预估月销降序取 Top N。

    ⚠️ 必须是词边界而不是子串：子串匹配会让 `mat` 命中 `auto·mat·ic`，
    实测把「Automatic Pet Feeder」错误挂到了 `exercise mat alignment lines` 上。

    与 `search_products` 的区别：本函数返回**原始 dict**（含 roi/category_key），
    供后端内部做进一步加工；`search_products` 返回 `ProductData` 模型，供工具/LLM 消费。

    Returns:
        命中的商品 dict 列表；无命中返回空列表（**不**回退随机/全池，
        调用方需据此走「该方向暂无匹配商品」的降级路径）。
    """
    tokens = tokenize(keyword)
    if not tokens:
        return []

    hits = []
    for p in MOCK_PRODUCTS:
        haystack = set(tokenize(f"{p['title']} {p.get('brand', '')} {p.get('category', '')}"))
        # 词形变化：query 的 cat/mat 应命中标题里的 cats/mats
        score = sum(
            1 for t in tokens
            if t in haystack or f"{t}s" in haystack or f"{t}es" in haystack
        )
        if score:
            hits.append((score, p["estimated_monthly_sales"], p))

    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [dict(h[2]) for h in hits[:limit]]

MOCK_KEYWORDS = {
    "coffee grinder": {"volume": 45000, "competition": 0.65, "trend": "rising"},
    "portable coffee maker": {"volume": 22000, "competition": 0.45, "trend": "rising"},
    "electric burr grinder": {"volume": 18000, "competition": 0.55, "trend": "stable"},
    "pet feeder automatic": {"volume": 35000, "competition": 0.58, "trend": "stable"},
    "smart pet feeder wifi": {"volume": 12000, "competition": 0.35, "trend": "rising"},
    "cat food dispenser": {"volume": 28000, "competition": 0.52, "trend": "stable"},
    "desk organizer mesh": {"volume": 52000, "competition": 0.72, "trend": "stable"},
    "office supplies storage": {"volume": 38000, "competition": 0.68, "trend": "declining"},
    "desktop accessories set": {"volume": 15000, "competition": 0.42, "trend": "rising"},
    "led grow lights indoor": {"volume": 62000, "competition": 0.75, "trend": "rising"},
    "plant growing lamp full spectrum": {"volume": 18000, "competition": 0.48, "trend": "rising"},
    "yoga mat non slip": {"volume": 95000, "competition": 0.82, "trend": "stable"},
    "exercise mat alignment lines": {"volume": 8000, "competition": 0.25, "trend": "rising"},
}

MOCK_REVIEWS = {
    "positive": [
        ("Great product!", "I've been using this for a month now and it works perfectly. Highly recommend!", 5),
        ("Exactly what I needed", "Good quality, fast shipping, and it does exactly what it's supposed to do.", 5),
        ("Better than expected", "The build quality is surprisingly good for the price. Very happy with my purchase.", 5),
        ("Works great", "No issues so far. Easy to use and clean.", 4),
        ("Good value", "Worth every penny. Would buy again.", 4),
    ],
    "negative": [
        ("Stopped working after 2 weeks", "It was great at first but then just died on me. Very disappointed.", 1),
        ("Poor quality control", "Mine arrived with scratches and the button feels loose. QC needs improvement.", 2),
        ("Battery doesn't last", "The battery life is nowhere near what they claim. Maybe 2 hours max.", 2),
        ("App connection issues", "Keeps disconnecting from my phone. Had to restart multiple times.", 2),
        ("Missing features", "Description says it has X feature but I can't find it anywhere in the app.", 3),
    ],
    # 3 星「中性」评：rating_filter=3 会走到这里（原先缺失该档 → KeyError: 'neutral'）
    "neutral": [
        ("Decent, but quality feels average", "It works, though the quality of the plastic is not great. Setup was a bit slow.", 3),
        ("Battery is just okay", "The battery barely lasts a day and the connection drops sometimes.", 3),
        ("Mixed experience", "Good design but the app is confusing and it can stop working randomly.", 3),
        ("Average for the price", "Does what it says. Nothing special, and it feels expensive for what you get.", 3),
    ],
}


class AmazonAdapter(PlatformAdapter):
    """
    Amazon 平台适配器

    Phase 2: 使用模拟数据 + 真实 FBA 费用算法
    Phase 3+: 接入 SP-API 替换为真实数据
    """

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.AMAZON

    async def search_products(
        self,
        query: str,
        page: int = 1,
        category: Optional[str] = None,
    ) -> List[ProductData]:
        """
        搜索产品（模拟数据）

        修复记录：原实现**完全忽略 `query`**，无条件 `random.sample` 返回 5 条随机商品。
        后果有两个：①「关键词 → 商品」这条路根本不存在（同一个词每次结果不同且与词无关），
        ② `_tool_search_products` 沦为假接口。

        现改为按 title/brand/category 做 token 命中打分：
          - 有命中：按命中数降序、同分按预估月销降序；
          - 无命中：按预估月销降序（**确定性**，可复现，不再随机）。

        实际实现在 Phase 3+ 会调用 Amazon Product Advertising API 或爬虫 + 数据库缓存。
        """
        await self._simulate_delay(0.3)

        page_size = 5
        ranked = match_products_by_keyword(query, limit=10 ** 6)
        if not ranked:
            # 无命中回退：按预估月销降序（确定性，保证同一 query 结果稳定）
            ranked = sorted(
                get_mock_products(category),
                key=lambda x: x["estimated_monthly_sales"],
                reverse=True,
            )
            if category:
                ranked = [p for p in ranked if p.get("category_key") == category]

        start = max(page - 1, 0) * page_size
        selected = ranked[start:start + page_size]

        return [
            ProductData(
                product_id=p["asin"],
                title=p["title"],
                price=p["price"],
                rating=p["rating"],
                review_count=p["review_count"],
                category=p["category"],
                brand=p["brand"],
                image_url=p["image_url"],
                estimated_monthly_sales=p["estimated_monthly_sales"],
                bsr_rank=p["bsr_rank"],
                platform=self.platform_type,
                url=f"https://www.amazon.com/dp/{p['asin']}",
            )
            for p in selected
        ]

    async def match_products(self, keyword: str, limit: int = 5) -> List[dict]:
        """
        关键词 → 具体商品（覆写基类默认实现）。

        直接用统一 Mock 池做 token 命中，好处是能带上 `roi` / `category_key`
        / `brand` / 原始 `category` 路径等派生字段——基类默认实现走
        `search_products` 会退化成 `ProductData`，丢掉这些字段。
        """
        await self._simulate_delay(0.15)
        return match_products_by_keyword(keyword, limit=limit)

    async def get_product_detail(self, product_id: str) -> Optional[ProductData]:
        """获取产品详情（模拟）"""
        await self._simulate_delay(0.2)

        for p in MOCK_PRODUCTS:
            if p["asin"] == product_id.upper():
                return ProductData(
                    product_id=p["asin"],
                    title=p["title"],
                    price=p["price"],
                    rating=p["rating"],
                    review_count=p["review_count"],
                    category=p["category"],
                    brand=p["brand"],
                    image_url=p["image_url"],
                    estimated_monthly_sales=p["estimated_monthly_sales"],
                    bsr_rank=p["bsr_rank"],
                    platform=self.platform_type,
                    url=f"https://www.amazon.com/dp/{p['asin']}",
                )

        return None

    async def get_keyword_data(self, keyword: str) -> KeywordData:
        """
        获取关键词数据（模拟）

        返回基于训练数据的合理估算值
        """
        await self._simulate_delay(0.15)

        keyword_lower = keyword.lower().strip()

        # 尝试从模拟数据库匹配
        if keyword_lower in MOCK_KEYWORDS:
            data = MOCK_KEYWORDS[keyword_lower]
            base_volume = data["volume"]
            competition = data["competition"]
            trend = data["trend"]
        else:
            # 未匹配的关键词生成合理随机值
            base_volume = random.randint(5000, 80000)
            competition = round(random.uniform(0.2, 0.85), 2)
            trend = random.choice(["rising", "stable", "declining"])

        # 添加波动
        volume = int(base_volume * random.uniform(0.9, 1.1))

        return KeywordData(
            keyword=keyword,
            search_volume=volume,
            competition=competition,
            suggested_bid=round(random.uniform(0.5, 3.5), 2),
            trend_direction=trend,
            organic_products_count=random.randint(10, 100),
            sponsored_products_count=random.randint(3, 15),
        )

    def calculate_fees(
        self,
        price: float,
        category: str = "",
        weight_lbs: float = 1.0,
        dimensions_inch: tuple = (10, 7, 5),
    ) -> FeeStructure:
        """
        计算 Amazon FBA 费用（真实算法！）

        基于 2024 年 Amazon US FBA 费率表：
        - 佣金：大部分类目 8-15%
        - FBA 配送费：按尺寸段和重量计算
        - 仓储费：月度仓储费（非旺季/旺季不同）
        """
        length, width, height = dimensions_inch

        # ====== 1. 佣金计算 ======
        if any(kw in category.lower() for kw in ["consumer electronics", "computer", "camera"]):
            referral_fee_pct = 8.0  # 电子类目较低
        elif any(kw in category.lower() for kw in ["clothing", "shoes", "jewelry", "watch"]):
            referral_fee_pct = 15.0  # 服装珠宝较高
        elif any(kw in category.lower() for kw in ["beauty", "health", "grocery"]):
            referral_fee_pct = 8.0 or 15.0  # 视具体子类目
        else:
            referral_fee_pct = 15.0  # 大部分类目默认 15%

        referral_fee = price * (referral_fee_pct / 100)

        # ====== 2. FBA 配送费计算 ======
        # 判断尺寸等级
        dimensional_weight_lbs = (length * width * height) / 139
        billable_weight = max(weight_lbs, dimensional_weight_lbs)

        # 小件标准 / 大件标准 / 大件 oversize
        is_small_standard = (length <= 15 and width <= 12 and height <= 0.75 and weight_lbs <= 1)
        girth = length + 2 * (width + height)
        is_oversize = (length > 25 or width > 20 or height > 20 or girth > 60)

        if is_small_standard:
            fba_fulfillment_fee = 3.22  # 小件标准尺寸
        elif is_oversize:
            # 大件费用更高
            fba_fulfillment_fee = 31.42 + (billable_weight - 5) * 0.38 if weight_lbs > 5 else 31.42
        else:
            # 标准尺寸
            if weight_lbs <= 1:
                fba_fulfillment_fee = 3.22
            elif weight_lbs <= 2:
                fba_fulfillment_fee = 4.59
            elif weight_lbs <= 3:
                fba_fulfillment_fee = 5.23
            else:
                fba_fulfillment_fee = 5.23 + (weight_lbs - 3) * 0.28

        # ====== 3. 月仓储费 ======
        volume_cubic_feet = (length * width * height) / 1728
        storage_fee_monthly = volume_cubic_feet * 0.87  # 标准尺寸非旺季费率

        # ====== 4. 结算费（媒体类目）======
        closing_fee = None
        if any(kw in category.lower() for kw in ["book", "dvd", "music", "video game", "software"]):
            closing_fee = 1.80

        # ====== 总计 ======
        total_fees = referral_fee + fba_fulfillment_fee + storage_fee_monthly + (closing_fee or 0)
        fee_percentage = (total_fees / price) * 100 if price > 0 else 0

        return FeeStructure(
            referral_fee_pct=referral_fee_pct,
            fba_fulfillment_fee=round(fba_fulfillment_fee, 2),
            storage_fee_monthly=round(storage_fee_monthly, 2),
            closing_fee=closing_fee,
            total_fees=round(total_fees, 2),
            fee_percentage=round(fee_percentage, 2),
        )

    async def get_reviews(
        self,
        product_id: str,
        page: int = 1,
        rating_filter: Optional[int] = None,
    ) -> List[ReviewData]:
        """获取评论（模拟）"""
        await self._simulate_delay(0.2)

        reviews = []

        # 决定正负评论比例
        positive_ratio = 0.7  # 70% 好评
        num_reviews = 10  # 每页返回10条

        for i in range(num_reviews):
            # 根据筛选条件决定情感
            if rating_filter:
                if rating_filter >= 4:
                    sentiment = "positive"
                    rating = rating_filter
                elif rating_filter <= 2:
                    sentiment = "negative"
                    rating = rating_filter
                else:
                    sentiment = "neutral"
                    rating = rating_filter
            else:
                sentiment = "positive" if random.random() < positive_ratio else "negative"
                rating = random.choices([5, 4, 3, 2, 1], weights=[45, 30, 10, 10, 5])[0]

            # 从模板中选取或生成
            pool = MOCK_REVIEWS[sentiment]
            template = random.choice(pool)
            title, content, _ = template

            reviews.append(
                ReviewData(
                    review_id=f"R{product_id}{i:04d}",
                    rating=rating,
                    title=title,
                    content=content,
                    author=f"Amazon Customer {random.randint(10000, 99999)}",
                    date=(datetime.now() - timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d"),
                    verified_purchase=random.random() > 0.2,
                    helpful_votes=random.randint(0, 50),
                    sentiment=sentiment,
                    # 3 星（neutral）同样含抱怨信息，痛点分析会把 1~3 星一起统计
                    pain_points=(
                        self._extract_pain_points(content)
                        if sentiment in ("negative", "neutral")
                        else []
                    ),
                )
            )

        return reviews

    async def get_bsr_rank(self, product_id: str) -> Optional[int]:
        """获取 BSR 排名（模拟）"""
        await self._simulate_delay(0.1)

        for p in MOCK_PRODUCTS:
            if p["asin"] == product_id.upper():
                return p["bsr_rank"]

        return random.randint(100, 50000)

    async def analyze_competitors(self, product_ids: List[str]) -> List[CompetitorAnalysis]:
        """竞品分析（增强版）"""
        results = []
        for pid in product_ids:
            product = await self.get_product_detail(pid)
            if not product:
                continue

            reviews = await self.get_reviews(pid)

            # 提取痛点
            negative_reviews = [r for r in reviews if r.sentiment == "negative"]
            pain_points = []
            for r in negative_reviews:
                pain_points.extend(r.pain_points)

            # 统计高频痛点
            pain_point_counts = {}
            for pp in pain_points:
                pain_point_counts[pp] = pain_point_counts.get(pp, 0) + 1
            top_pain_points = sorted(pain_point_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            # 分析优势劣势
            strengths = []
            weaknesses = [f"{pp} ({count}条提及)" for pp, count in top_pain_points]

            if product.rating >= 4.5:
                strengths.append(f"高评分 ({product.rating}⭐)")
            if product.review_count > 1000:
                strengths.append(f"大量评论 ({product.review_count}条)")
            if product.estimated_monthly_sales > 5000:
                strengths.append(f"高月销 ({product.estimated_monthly_sales}件)")

            listing_score = self._calculate_listing_score(product, reviews)

            # 定价策略判断
            avg_price = sum(p["price"] for p in MOCK_PRODUCTS) / len(MOCK_PRODUCTS)
            if product.price > avg_price * 1.3:
                price_positioning = "premium"
            elif product.price < avg_price * 0.7:
                price_positioning = "budget"
            else:
                price_positioning = "competitive"

            results.append(
                CompetitorAnalysis(
                    product=product,
                    strengths=strengths,
                    weaknesses=weaknesses,
                    listing_quality_score=listing_score,
                    price_positioning=price_positioning,
                )
            )

        return results

    # ====== 内部工具方法 ======

    @staticmethod
    async def _simulate_delay(seconds: float):
        """模拟网络延迟"""
        import asyncio
        await asyncio.sleep(seconds)

    @staticmethod
    def _extract_pain_points(text: str) -> List[str]:
        """从评论文本中提取痛点（简单规则匹配）"""
        pain_keywords = {
            "battery": "电池续航不足",
            "connection": "连接不稳定",
            "quality": "质量问题",
            "broke": "容易损坏",
            "stop": "停止工作",
            "app": "APP问题",
            "expensive": "性价比低",
            "missing": "缺少功能",
            "difficult": "使用困难",
            "slow": "速度慢",
        }

        found = []
        text_lower = text.lower()
        for keyword, pain_point in pain_keywords.items():
            if keyword in text_lower:
                found.append(pain_point)

        return list(set(found))  # 去重

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

MOCK_PRODUCTS = [
    {
        "asin": "B0CGLKP2R1",
        "title": "Portable Coffee Grinder, Electric Burr Coffee Bean Grinder with Adjustable Settings",
        "price": 29.99,
        "rating": 4.3,
        "review_count": 2847,
        "category": "Home & Kitchen > Kitchen & Dining > Coffee, Tea & Espresso",
        "brand": "BurrMaster",
        "image_url": "https://m.media-amazon.com/images/I/71example.jpg",
        "estimated_monthly_sales": 4500,
        "bsr_rank": 1234,
    },
    {
        "asin": "B0DXYZ1234",
        "title": "Automatic Pet Feeder, Smart Food Dispenser with WiFi App Control for Cats and Dogs",
        "price": 49.99,
        "rating": 4.1,
        "review_count": 1523,
        "category": "Pet Supplies > Dog Supplies > Automatic Feeders",
        "brand": "PetTech Pro",
        "image_url": "https://m.media-amazon.com/images/I/72example.jpg",
        "estimated_monthly_sales": 3200,
        "bsr_rank": 567,
    },
    {
        "asin": "B0FABC5678",
        "title": "Desktop Organizer Set, Mesh Office Supplies Storage with Drawer and Pen Holder",
        "price": 18.99,
        "rating": 4.5,
        "review_count": 8934,
        "category": "Office Products > Desk Accessories & Workspace Organizers",
        "brand": "DeskPro",
        "image_url": "https://m.media-amazon.com/images/I/73example.jpg",
        "estimated_monthly_sales": 8900,
        "bsr_rank": 234,
    },
    {
        "asin": "B0GHIJ9012",
        "title": "LED Grow Lights for Indoor Plants, Full Spectrum Plant Growing Lamp with Timer",
        "price": 35.99,
        "rating": 4.2,
        "review_count": 2156,
        "category": "Lawn & Garden > Plant Growing Equipment > Grow Lights",
        "brand": "GrowSmart",
        "image_url": "https://m.media-amazon.com/images/I/74example.jpg",
        "estimated_monthly_sales": 2800,
        "bsr_rank": 890,
    },
    {
        "asin": "B0KLMN3456",
        "title": "Yoga Mat with Alignment Lines, Non-Slip Exercise Mat for Yoga, Pilates & Fitness",
        "price": 25.99,
        "rating": 4.6,
        "review_count": 12453,
        "category": "Sports & Fitness > Yoga > Mats",
        "brand": "FlexFit",
        "image_url": "https://m.media-amazon.com/images/I/75example.jpg",
        "estimated_monthly_sales": 12000,
        "bsr_rank": 89,
    },
]

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

        实际实现会调用：
        - Amazon Product Advertising API
        - 或爬虫 + 数据库缓存
        """
        # 模拟搜索延迟
        await self._simulate_delay(0.3)

        # 随机返回部分产品（模拟搜索结果）
        results = []
        sample_size = min(len(MOCK_PRODUCTS), 5)  # 每页最多5个
        selected = random.sample(MOCK_PRODUCTS, sample_size)

        for p in selected:
            # 添加随机波动模拟不同搜索结果
            price_variation = p["price"] * random.uniform(-0.05, 0.05)
            results.append(
                ProductData(
                    product_id=p["asin"],
                    title=p["title"],
                    price=round(p["price"] + price_variation, 2),
                    rating=p["rating"] + random.uniform(-0.1, 0.1),
                    review_count=int(p["review_count"] * random.uniform(0.95, 1.05)),
                    category=p["category"],
                    brand=p["brand"],
                    image_url=p["image_url"],
                    estimated_monthly_sales=int(p["estimated_monthly_sales"] * random.uniform(0.9, 1.1)),
                    bsr_rank=int(p["bsr_rank"] * random.uniform(0.9, 1.1)),
                    platform=self.platform_type,
                    url=f"https://www.amazon.com/dp/{p['asin']}",
                )
            )

        return results

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
                    pain_points=self._extract_pain_points(content) if sentiment == "negative" else [],
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

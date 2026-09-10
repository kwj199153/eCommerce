"""
平台适配层 - 统一接口定义

所有平台适配器（Amazon/TikTok/Shopify）必须实现此接口。
选品 Agent 通过此抽象层调用不同平台的数据，实现平台无关的业务逻辑。

设计原则：
- 面向接口编程，业务层不依赖具体平台
- 工厂模式自动路由，支持运行时切换平台
- 数据结构统一，屏蔽平台差异
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# ====== 数据模型（跨平台通用）======

class PlatformType(str, Enum):
    """支持的电商平台"""
    AMAZON = "amazon"
    SHOPEE = "shopee"
    TIKTOK = "tiktok"
    SHOPIFY = "shopify"


class ProductData(BaseModel):
    """
    通用产品数据结构

    不同平台的特有字段映射到统一结构：
    - Amazon: ASIN → product_id, BSR → rank
    - TikTok: product_id → product_id
    - Shopify: handle → product_id
    """
    product_id: str = Field(..., description="产品ID（ASIN/product_id/handle）")
    title: str = Field(..., description="产品标题")
    price: float = Field(..., description="价格（USD）")
    currency: str = Field(default="USD", description="货币单位")
    rating: float = Field(default=0.0, description="评分（0-5）")
    review_count: int = Field(default=0, description="评论数量")
    category: str = Field(default="", description="类目路径")
    brand: Optional[str] = Field(None, description="品牌名")
    image_url: Optional[str] = Field(None, description="主图URL")

    # 销售数据
    estimated_monthly_sales: Optional[int] = Field(None, description="预估月销量")
    bsr_rank: Optional[int] = Field(None, description="Best Seller Rank（Amazon专用，其他平台可为None）")

    # 平台元数据
    platform: PlatformType = Field(..., description="数据来源平台")
    url: Optional[str] = Field(None, description="产品详情页URL")

    class Config:
        use_enum_values = True


class KeywordData(BaseModel):
    """关键词数据"""
    keyword: str = Field(..., description="关键词文本")
    search_volume: int = Field(default=0, description="月搜索量")
    competition: float = Field(default=0.0, description="竞争指数（0-1，越高越竞争激烈）")
    suggested_bid: Optional[float] = Field(None, description="建议竞价（USD）")
    trend_direction: str = Field(default="stable", description="趋势方向：rising/stable/declining")

    # 相关指标
    organic_products_count: int = Field(default=0, description="自然搜索结果数")
    sponsored_products_count: int = Field(default=0, description="广告结果数")


class FeeStructure(BaseModel):
    """平台费用结构"""
    referral_fee_pct: float = Field(..., description="佣金比例（%）")
    fba_fulfillment_fee: float = Field(default=0.0, description="FBA配送费（USD）")
    storage_fee_monthly: float = Field(default=0.0, description="月仓储费（USD/立方英尺）")
    closing_fee: Optional[float] = Field(None, description="结算费（仅媒体类目）")

    # 计算结果
    total_fees: float = Field(default=0.0, description="总费用（USD）")
    fee_percentage: float = Field(default=0.0, description="费用占售价比例（%）")


class ReviewData(BaseModel):
    """评论数据"""
    review_id: str
    rating: int = Field(..., ge=1, le=5)
    title: Optional[str] = None
    content: str = Field(..., description="评论内容")
    author: Optional[str] = None
    date: Optional[str] = None
    verified_purchase: bool = Field(default=False)
    helpful_votes: int = Field(default=0)

    # AI 分析结果
    sentiment: Optional[str] = Field(None, description="情感倾向：positive/negative/neutral")
    pain_points: List[str] = Field(default=[], description="提取的痛点")


class CompetitorAnalysis(BaseModel):
    """竞品分析结果"""
    product: ProductData
    strengths: List[str] = Field(default=[], description="优势列表")
    weaknesses: List[str] = Field(default=[], description="劣势列表")
    listing_quality_score: float = Field(default=0.0, ge=0, le=100, description="Listing质量评分")
    price_positioning: str = Field(default="", description="定价策略：premium/budget/competitive")


# ====== 抽象接口 ======

class PlatformAdapter(ABC):
    """
    所有平台适配器的基类（抽象接口）

    设计来源：
    - 策略模式：不同平台有不同实现
    - 工厂方法：通过 get_platform_adapter() 自动实例化
    - 单一职责：每个适配器只负责一个平台的数据获取
    """

    @property
    @abstractmethod
    def platform_type(self) -> PlatformType:
        """返回平台类型"""
        pass

    @abstractmethod
    async def search_products(
        self,
        query: str,
        page: int = 1,
        category: Optional[str] = None,
    ) -> List[ProductData]:
        """
        搜索产品

        Args:
            query: 搜索关键词
            page: 页码（从1开始）
            category: 类目筛选（可选）

        Returns:
            产品列表
        """
        pass

    @abstractmethod
    async def get_product_detail(self, product_id: str) -> Optional[ProductData]:
        """
        获取产品详情

        Args:
            product_id: 产品ID（ASIN等）

        Returns:
            产品详情，不存在返回 None
        """
        pass

    @abstractmethod
    async def get_keyword_data(self, keyword: str) -> KeywordData:
        """
        获取关键词数据

        Args:
            keyword: 关键词

        Returns:
            关键词数据（搜索量、竞争度等）
        """
        pass

    @abstractmethod
    def calculate_fees(
        self,
        price: float,
        category: str = "",
        weight_lbs: float = 1.0,
        dimensions_inch: tuple = (10, 7, 5),
    ) -> FeeStructure:
        """
        计算平台费用

        Args:
            price: 售价
            category: 类目（影响佣金比例）
            weight_lbs: 重量（磅）
            dimensions_inch: 尺寸（长宽高，英寸）

        Returns:
            费用明细
        """
        pass

    @abstractmethod
    async def get_reviews(
        self,
        product_id: str,
        page: int = 1,
        rating_filter: Optional[int] = None,
    ) -> List[ReviewData]:
        """
        获取产品评论

        Args:
            product_id: 产品ID
            page: 页码
            rating_filter: 星级筛选（1-5），不传则全部

        Returns:
            评论列表
        """
        pass

    @abstractmethod
    async def get_bsr_rank(self, product_id: str) -> Optional[int]:
        """
        获取 Best Seller Rank

        Args:
            product_id: 产品ID

        Returns:
            BSR排名，无数据返回 None
        """
        pass

    async def analyze_competitors(
        self,
        product_ids: List[str],
    ) -> List[CompetitorAnalysis]:
        """
        批量分析竞品（默认实现，可覆写）

        Args:
            product_ids: 产品ID列表

        Returns:
            竞品分析结果列表
        """
        results = []
        for pid in product_ids:
            product = await self.get_product_detail(pid)
            if product:
                reviews = await self.get_reviews(pid)
                results.append(
                    CompetitorAnalysis(
                        product=product,
                        listing_quality_score=self._calculate_listing_score(product, reviews),
                    )
                )
        return results

    def _calculate_listing_score(
        self,
        product: ProductData,
        reviews: List[ReviewData],
    ) -> float:
        """计算 Listing 质量评分（内部方法）"""
        score = 50.0  # 基础分

        # 标题质量（长度适中加分）
        if 80 <= len(product.title) <= 200:
            score += 15
        elif len(product.title) > 50:
            score += 10

        # 图片（有图加分）
        if product.image_url:
            score += 10

        # 评论（数量和评分）
        if product.review_count > 100:
            score += 10
        elif product.review_count > 20:
            score += 5

        if product.rating >= 4.5:
            score += 15
        elif product.rating >= 4.0:
            score += 10

        return min(score, 100.0)


# ====== 工厂方法 ======

def get_platform_adapter(platform: str | PlatformType) -> PlatformAdapter:
    """
    工厂方法：根据平台名称返回对应的适配器实例

    使用方式：
        adapter = get_platform_adapter("amazon")
        products = await adapter.search_products("coffee maker")

    Args:
        platform: 平台名称或枚举值

    Returns:
        平台适配器实例

    Raises:
        ValueError: 不支持的平台
    """
    if isinstance(platform, str):
        platform = PlatformType(platform.lower())

    # 延迟导入，避免循环依赖
    if platform == PlatformType.AMAZON:
        from platforms.amazon.client import AmazonAdapter
        return AmazonAdapter()
    elif platform == PlatformType.SHOPEE:
        # Shopee 适配器（Phase 10 骨架，后续实现完整 API 对接）
        from platforms.shopee.client import ShopeeAdapter
        return ShopeeAdapter()
    elif platform == PlatformType.TIKTOK:
        from platforms.tiktok.client import TikTokAdapter
        return TikTokAdapter()
    elif platform == PlatformType.SHOPIFY:
        from platforms.shopify.client import ShopifyAdapter
        return ShopifyAdapter()
    else:
        raise ValueError(f"不支持的平台类型: {platform}。可选值: {[p.value for p in PlatformType]}")

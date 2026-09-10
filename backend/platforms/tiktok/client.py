"""
TikTok Shop 平台适配器（骨架预留）

Phase 5+ 实现完整功能。
当前仅提供占位实现，确保工厂方法可正常调用。
"""

from typing import List, Optional

from platforms.base import (
    PlatformAdapter,
    PlatformType,
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
)


class TikTokAdapter(PlatformAdapter):
    """
    TikTok Shop 平台适配器（待实现）

    TODO Phase 5:
    - 对接 TikTok Shop Open API
    - 实现 search_products / get_product_detail 等方法
    - 处理 TikTok 特有数据结构
    """

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.TIKTOK

    async def search_products(self, query: str, page: int = 1, category: Optional[str] = None) -> List[ProductData]:
        raise NotImplementedError("TikTok 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_product_detail(self, product_id: str) -> Optional[ProductData]:
        raise NotImplementedError("TikTok 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_keyword_data(self, keyword: str) -> KeywordData:
        raise NotImplementedError("TikTok 适配器尚未实现，请在 Phase 5+ 开发")

    def calculate_fees(self, price: float, category: str = "", **kwargs) -> FeeStructure:
        # TikTok 费率结构不同（佣金约 5% + 支付手续费）
        return FeeStructure(
            referral_fee_pct=5.0,
            fba_fulfillment_fee=0.0,  # TikTok 无 FBA
            storage_fee_monthly=0.0,
            total_fees=price * 0.05 + 0.30,  # 5% 佣金 + $0.30 支付费
            fee_percentage=5.0 + (0.30 / price * 100 if price > 0 else 0),
        )

    async def get_reviews(self, product_id: str, page: int = 1, rating_filter: Optional[int] = None) -> List[ReviewData]:
        raise NotImplementedError("TikTok 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_bsr_rank(self, product_id: str) -> Optional[int]:
        # TikTok 使用 "热销排名" 而非 BSR
        return None

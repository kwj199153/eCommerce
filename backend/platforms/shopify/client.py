"""
Shopify 独立站平台适配器（骨架预留）

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


class ShopifyAdapter(PlatformAdapter):
    """
    Shopify 独立站平台适配器（待实现）

    TODO Phase 5:
    - 对接 Shopify Admin API / Storefront API
    - 实现 search_products / get_product_detail 等方法
    - 处理独立站特有数据结构
    """

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.SHOPIFY

    async def search_products(self, query: str, page: int = 1, category: Optional[str] = None) -> List[ProductData]:
        raise NotImplementedError("Shopify 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_product_detail(self, product_id: str) -> Optional[ProductData]:
        raise NotImplementedError("Shopify 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_keyword_data(self, keyword: str) -> KeywordData:
        # Shopify 无内置关键词工具，需接入第三方（如 Google Trends）
        raise NotImplementedError("Shopify 适配器尚未实现，请在 Phase 5+ 开发")

    def calculate_fees(self, price: float, category: str = "", **kwargs) -> FeeStructure:
        # Shopify 费用：月租费 + 交易手续费 (2-2.9% + $0.30)
        transaction_fee_pct = 2.9  # 基础费率
        return FeeStructure(
            referral_fee_pct=transaction_fee_pct,
            fba_fulfillment_fee=0.0,
            storage_fee_monthly=0.0,
            total_fees=price * (transaction_fee_pct / 100) + 0.30,
            fee_percentage=transaction_fee_pct + (0.30 / price * 100 if price > 0 else 0),
        )

    async def get_reviews(self, product_id: str, page: int = 1, rating_filter: Optional[int] = None) -> List[ReviewData]:
        # Shopify 使用第三方评论应用（如 YotPo、Judge.me）
        raise NotImplementedError("Shopify 适配器尚未实现，请在 Phase 5+ 开发")

    async def get_bsr_rank(self, product_id: str) -> Optional[int]:
        # 独立站无 BSR 概念
        return None

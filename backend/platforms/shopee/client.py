"""
Shopee 平台适配器 (Phase 10 骨架)

当前为骨架实现，后续对接 Shopee Open Platform API。
费率计算已通过 profit_engine.py 的 ShopeeFeeConfig 支持。
"""

from typing import List, Optional
from platforms.base import (
    PlatformType, PlatformAdapter, ProductData, KeywordData,
    FeeStructure, ReviewData, CompetitorAnalysis
)


class ShopeeAdapter(PlatformAdapter):
    """
    Shopee 平台适配器

    Phase 10: 骨架实现，费率计算通过 profit_engine.py 完成
    后续: 对接 Shopee Open Platform API (https://open.shopee.com/)
    """

    @property
    def platform_type(self) -> PlatformType:
        return PlatformType.SHOPEE

    async def search_products(
        self,
        query: str,
        page: int = 1,
        category: Optional[str] = None,
    ) -> List[ProductData]:
        # TODO: 对接 Shopee Search Item API
        # GET https://open.shopee.com/api/v2/product/search_item
        return []

    async def get_product_detail(self, product_id: str) -> Optional[ProductData]:
        # TODO: 对接 Shopee Get Item Detail API
        # GET https://open.shopee.com/api/v2/product/get_item_detail
        return None

    async def get_keyword_data(self, keyword: str) -> KeywordData:
        # TODO: Shopee 无官方关键词 API，可通过第三方数据服务获取
        return KeywordData(
            keyword=keyword,
            search_volume=0,
            competition=0.0,
        )

    def calculate_fees(
        self,
        price: float,
        category: str = "",
        weight_lbs: float = 1.0,
        dimensions_inch: tuple = (10, 7, 5),
    ) -> FeeStructure:
        """
        计算 Shopee 费用

        注意：此方法保留接口兼容性，实际费用计算建议使用 core/profit_engine.py
        的通用引擎，支持更完整的 Shopee 费用结构（商业增长费、基础设施费等）。
        """
        from core.profit_engine import ShopeeFeeConfig, get_fee_template

        # 使用默认 Shopee MY 费率（后续可从店铺上下文动态加载）
        cfg: ShopeeFeeConfig = get_fee_template("shopee_my")

        commission = price * cfg.commission_pct / 100
        growth = price * cfg.growth_fee_pct / 100
        vat = price * cfg.vat_rate / 100
        withdrawal = price * cfg.withdrawal_fee_rate / 100

        total = commission + cfg.transaction_fee + growth + cfg.infrastructure_fee + vat + withdrawal + cfg.logistics_cost

        return FeeStructure(
            referral_fee_pct=commission,  # 复用字段存储佣金
            fba_fulfillment_fee=cfg.transaction_fee,  # 复用字段存储交易费
            storage_fee_monthly=growth,  # 复用字段存储增长费
            closing_fee=cfg.infrastructure_fee,  # 复用字段存储基础设施费
            total_fees=round(total, 2),
            fee_percentage=round(total / price * 100, 2) if price > 0 else 0,
        )

    async def get_reviews(
        self,
        product_id: str,
        page: int = 1,
        rating_filter: Optional[int] = None,
    ) -> List[ReviewData]:
        # TODO: 对接 Shopee Get Comment List API
        return []

    async def get_bsr_rank(self, product_id: str) -> Optional[int]:
        # Shopee 无 BSR 概念，返回 None
        return None

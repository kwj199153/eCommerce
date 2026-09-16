"""
平台适配层

提供统一的电商平台数据访问接口，屏蔽不同平台的差异。

使用方式：
    from platforms import get_platform_adapter, PlatformType

    # 获取 Amazon 适配器
    adapter = get_platform_adapter("amazon")
    products = await adapter.search_products("coffee maker")

    # 获取 TikTok 适配器（Phase 5+ 可用）
    tiktok_adapter = get_platform_adapter(PlatformType.TIKTOK)

支持的平台：
    - Amazon (Phase 2: 完整实现)
    - TikTok Shop (Phase 5+: 骨架预留)
    - Shopify (Phase 5+: 骨架预留)
"""

# 注：支付网关（platforms/payment/）与下面这些电商平台适配器同属本层 ——
#     它们都是「对接外部系统、对内提供统一接口」的适配器。
#     为避免符号名混淆（get_gateway vs get_platform_adapter），此处不聚合
#     导出，请直接从 platforms.payment 导入。
from platforms.base import (
    PlatformAdapter,
    PlatformType,
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
    CompetitorAnalysis,
    get_platform_adapter,
)

__all__ = [
    "PlatformAdapter",
    "PlatformType",
    "ProductData",
    "KeywordData",
    "FeeStructure",
    "ReviewData",
    "CompetitorAnalysis",
    "get_platform_adapter",
]

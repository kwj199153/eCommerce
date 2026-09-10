"""
Amazon SP-API 模块导出

提供统一的导入入口：
- from platforms.amazon.sp_api import SPAPIClient, get_spapi_client
- from platforms.amazon.sp_api.models import *
- from platforms.amazon.sp_api.auth import SPAPIClientAuth
"""

from .auth import (
    SPAPIClientAuth,
    SPAPIConfig,
    LWACredentials,
    AWSCredentials,
    AccessToken,
    SPAPIAuthError,
    get_spapi_auth,
    close_spapi_auth,
)

from .models import (
    # 通用
    Marketplace,
    FulfillmentChannel,
    OrderStatus,
    # Products API
    ItemByASIN,
    Offer,
    PricingItem,
    InventorySummary,
    MoneyType,
    # Orders API
    Order,
    OrderItem,
    Address,
    # Reports API
    Report,
    ReportDocument,
    ReportProcessingStatus,
    # Advertising API
    Campaign,
    CampaignType,
    CampaignState,
    AdGroup,
    Keyword,
    AdPerformanceMetrics,
    SearchTermReportRow,
    ProductAd,
    # 竞品分析
    CompetitorListing,
    BuyBoxData,
    PriceHistoryPoint,
)

from .client import (
    SPAPIClient,
    get_spapi_client,
    close_spapi_client,
)

__all__ = [
    # Auth
    "SPAPIClientAuth",
    "SPAPIConfig",
    "LWACredentials",
    "AWSCredentials",
    "AccessToken",
    "SPAPIAuthError",
    "get_spapi_auth",
    "close_spapi_auth",
    # Models
    "Marketplace",
    "FulfillmentChannel",
    "OrderStatus",
    "ItemByASIN",
    "Offer",
    "PricingItem",
    "InventorySummary",
    "MoneyType",
    "Order",
    "OrderItem",
    "Address",
    "Report",
    "ReportDocument",
    "ReportProcessingStatus",
    "Campaign",
    "CampaignType",
    "CampaignState",
    "AdGroup",
    "Keyword",
    "AdPerformanceMetrics",
    "SearchTermReportRow",
    "ProductAd",
    "CompetitorListing",
    "BuyBoxData",
    "PriceHistoryPoint",
    # Client
    "SPAPIClient",
    "get_spapi_client",
    "close_spapi_client",
]

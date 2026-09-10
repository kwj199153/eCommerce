"""数据模型"""
from models.store import (
    Store, StoreCreate, StoreUpdate, StoreWithCredentials,
    StoreListResponse, StoreDetailResponse,
    FeeTemplate, FeeTemplateCreate, DiscountTemplate,
    ProfitCalculationContext,
    StoreStatus, ConnectionStatus, SyncStatus,
)
from models.amazon_sp import (
    # 枚举
    CredentialStatus, ReportTaskStatus, AdReportType, InventoryHealthStatus,
    # OAuth
    AmazonCredentialCreate, AmazonCredentialResponse, AmazonCredentialDetail,
    AuthUrlResponse, OAuthCallbackRequest,
    # 日志
    AuthLogResponse,
    # 销售
    DailySalesResponse, DailySalesSummary,
    # 广告
    AdMetricResponse, AdMetricsSummary,
    # Listing
    ListingSnapshotResponse,
    # 报表任务
    ReportTaskCreate, ReportTaskResponse,
    # 库存
    InventoryHealthResponse, InventoryHealthSummary,
    # 同步控制
    SyncTriggerRequest, SyncStatusResponse,
)

__all__ = [
    # Store 模块
    "Store", "StoreCreate", "StoreUpdate", "StoreWithCredentials",
    "StoreListResponse", "StoreDetailResponse",
    "FeeTemplate", "FeeTemplateCreate", "DiscountTemplate",
    "ProfitCalculationContext",
    "StoreStatus", "ConnectionStatus", "SyncStatus",
    # Amazon SP-API 模块
    "CredentialStatus", "ReportTaskStatus", "AdReportType", "InventoryHealthStatus",
    "AmazonCredentialCreate", "AmazonCredentialResponse", "AmazonCredentialDetail",
    "AuthUrlResponse", "OAuthCallbackRequest",
    "AuthLogResponse",
    "DailySalesResponse", "DailySalesSummary",
    "AdMetricResponse", "AdMetricsSummary",
    "ListingSnapshotResponse",
    "ReportTaskCreate", "ReportTaskResponse",
    "InventoryHealthResponse", "InventoryHealthSummary",
    "SyncTriggerRequest", "SyncStatusResponse",
]

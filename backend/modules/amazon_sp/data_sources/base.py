"""
Amazon SP-API 数据源抽象层 — 基类

设计原则：
- 所有数据源（Mock / SP-API Real / CSV Import）实现同一接口
- 上层 Agent/Service 只依赖此接口，不关心数据从哪来
- 换数据源 = 改一行配置，零改动上层逻辑

接口约定：
  fetch_credentials()      → List[AmazonCredentialDict]
  fetch_daily_sales(...)   → List[DailySalesDict]
  fetch_ad_metrics(...)    → List[AdMetricDict]
  fetch_listings(...)      → List[ListingSnapshotDict]
  fetch_inventory(...)     → List[InventoryHealthDict]
  fetch_competitors(...)   → List[CompetitorSnapshotDict]   [新增]
  fetch_report_tasks(...)  → List[ReportTaskDict]
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional


class AmazonDataSource(ABC):
    """亚马逊数据源基类 —— 所有数据源必须实现此接口"""

    @abstractmethod
    def fetch_credentials(self, store_id: int) -> list[dict]:
        """获取店铺的 OAuth 凭证"""
        ...

    @abstractmethod
    def fetch_daily_sales(
        self,
        store_id: int,
        date_from: date,
        date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取每日销售数据
        返回字段与 amazon_daily_sales 表结构一致
        """
        ...

    @abstractmethod
    def fetch_ad_metrics(
        self,
        store_id: int,
        date_from: date,
        date_to: date,
        report_types: Optional[list[str]] = None,
        campaign_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取广告指标数据
        返回字段与 amazon_ad_metrics 表结构一致
        支持 sp / sb / sd 三种 report_type
        """
        ...

    @abstractmethod
    def fetch_listings(
        self,
        store_id: int,
        date_from: date,
        date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取 Listing 快照
        返回字段与 amazon_listing_snapshots 表结构一致
        """
        ...

    @abstractmethod
    def fetch_inventory(
        self,
        store_id: int,
        snapshot_date: Optional[date] = None,
    ) -> list[dict]:
        """
        获取库存健康数据
        返回字段与 amazon_inventory_health 表结构一致
        snapshot_date=None 表示最新
        """
        ...

    @abstractmethod
    def fetch_competitors(
        self,
        store_id: int,
        date_from: date,
        date_to: date,
        asins: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取竞品快照数据 [新增]
        返回字段与 amazon_competitor_snapshots 表结构一致
        """
        ...

    @abstractmethod
    def fetch_report_tasks(
        self,
        store_id: int,
        date_from: date,
        date_to: date,
    ) -> list[dict]:
        """
        获取报表任务记录
        返回字段与 amazon_report_tasks 表结构一致
        """
        ...

    # ---- 可选钩子：数据源健康检查 ----

    def health_check(self) -> dict:
        """
        检查数据源是否可用
        返回: {"status": "ok"|"degraded"|"error", "message": "...", "latency_ms": ...}
        """
        return {"status": "ok", "message": "Base class - no check implemented"}

    def get_source_info(self) -> dict:
        """返回数据源元信息（名称、类型、最后更新时间等）"""
        return {
            "source_type": "base",
            "name": "Abstract Base",
            "description": "数据源基类，不应直接使用",
        }

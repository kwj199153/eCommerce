"""
Amazon SP-API Reports API 封装

提供报告创建、获取、解析的高级操作方法。
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import base64
import gzip

from .client import SPAPIClient
from .models import (
    Report,
    ReportDocument,
    ReportProcessingStatus,
)

logger = logging.getLogger(__name__)


class ReportsAPI:
    """
    Reports API 高级封装

    提供面向业务的方法：
    - 业务报告（销售、库存、流量）
    - 广告报告（搜索词、关键词、商品）
    - 报告自动轮询与解析
    """

    # 常用报告类型
    REPORT_TYPES = {
        # ====== 业务报告 ======
        "sales_business": "GET_SALES_AND_TRAFFIC_REPORT",
        "inventory_ledger": "GET_LEDGER_DETAIL_VIEW_DATA",
        "storage_volume": "GET_FBA_STORAGE_VOLUME_INVENTORY_DATA",
        "inventory_health": "GET_FBA_INVENTORY_HEALTH_DATA",
        "inventory_planned": "GET_FBA_INVENTORY_PLANNED_FEEDBACK",
        "all_listings": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
        "open_listings": "GET_FLAT_FILE_OPEN_LISTINGS_DATA",

        # ====== 广告报告 (SP) ======
        "sp_campaign": "SP_CAMPAIGN_REPORT",
        "sp_adgroup": "SP_AD_GROUP_REPORT",
        "sp_keyword": "SP_KEYWORDS_REPORT",
        "sp_product_ads": "SP_PRODUCT_ADS_REPORT",
        "sp_search_term": "SP_SEARCH_TERM_REPORT",
        "sp_targeted_keyword": "SP_TARGETED_KEYWORD_REPORT",
        "sp_asin": "SP_ASIN_REPORT",

        # ====== 广告报告 (SB) ======
        "sb_campaign": "SB_CAMPAIGN_REPORT",
        "sb_adgroup": "SB_AD_GROUP_REPORT",
        "sb_keyword": "SB_KEYWORDS_REPORT",
        "sb_targeted_keyword": "SB_TARGETED_KEYWORD_REPORT",
        "sb_product_ads": "SB_PRODUCT_ADS_REPORT",
        "sb_search_term": "SB_SEARCH_TERM_REPORT",

        # ====== 广告报告 (SD) ======
        "sd_campaign": "SD_CAMPAIGN_REPORT",
        "sd_adgroup": "SD_AD_GROUP_REPORT",
        "sd_product_ads": "SD_PRODUCT_ADS_REPORT",
        "sd_targeted_keyword": "SD_TARGETED_KEYWORD_REPORT",
        "sd_search_term": "SD_SEARCH_TERM_REPORT",
    }

    def __init__(self, client: SPAPIClient):
        self.client = client

    # ====== 便捷报告方法 ======

    async def get_sales_traffic_report(
        self,
        days_back: int = 7,
        aggregation: str = "DAILY",  # DAILY/WEEKLY/MONTHLY
    ) -> List[Dict[str, Any]]:
        """
        获取销售和流量报告

        这是最常用的业务报告，包含：
        - 销售额、订单数、平均售价
        - 页面浏览量、转化率、会话数
        - 按父 ASIN 或 SKU 聚合
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        report_type = self.REPORT_TYPES["sales_business"]

        report = await self.client.create_report(
            report_type=report_type,
            data_start_time=start_date,
            data_end_time=end_date,
            report_options={
                "aggregationByDate": aggregation,
            },
        )

        try:
            doc = await self.client.wait_for_report(report.report_id)
            return self._parse_json_report(doc.data)
        except Exception as e:
            logger.error(f"销售流量报告失败: {e}")
            return []

    async def get_inventory_health_report(self) -> List[Dict[str, Any]]:
        """获取 FBA 库存健康度报告"""
        report = await self.client.create_report(
            report_type=self.REPORT_TYPES["inventory_health"],
        )

        try:
            doc = await self.client.wait_for_report(report.report_id)
            return self._parse_tsv_to_dicts(doc.data)
        except Exception as e:
            logger.error(f"库存健康报告失败: {e}")
            return []

    async def get_storage_volume_report(self) -> List[Dict[str, Any]]:
        """获取 FBA 库存体积报告"""
        report = await self.client.create_report(
            report_type=self.REPORT_TYPES["storage_volume"],
        )

        try:
            doc = await self.client.wait_for_report(report.report_id)
            return self._parse_tsv_to_dicts(doc.data)
        except Exception as e:
            logger.error(f"库存体积报告失败: {e}")
            return []

    # ====== 广告报告便捷方法 ======

    async def get_sp_search_term_report(
        self,
        days_back: int = 30,
        segment: str = "query",
    ) -> List[Dict[str, Any]]:
        """
        获取 SP 搜索词报告

        Args:
            days_back: 数据天数
            segment: 分段类型 (query/keyword/target)
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        report = await self.client.create_report(
            report_type=self.REPORT_TYPES["sp_search_term"],
            data_start_time=start_date,
            data_end_time=end_date,
            report_options={"segment": segment},
        )

        try:
            doc = await self.client.wait_for_report(report.report_id, max_wait_seconds=600)
            return self._parse_tsv_to_dicts(doc.data)
        except Exception as e:
            logger.error(f"搜索词报告失败: {e}")
            return []

    async def get_sp_keyword_report(
        self,
        days_back: int = 30,
    ) -> List[Dict[str, Any]]:
        """获取 SP 关键词报告"""
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        report = await self.client.create_report(
            report_type=self.REPORT_TYPES["sp_keyword"],
            data_start_time=start_date,
            data_end_time=end_date,
        )

        try:
            doc = await self.client.wait_for_report(report.report_id, max_wait_seconds=600)
            return self._parse_tsv_to_dicts(doc.data)
        except Exception as e:
            logger.error(f"关键词报告失败: {e}")
            return []

    async def get_ad_performance_summary(
        self,
        days_back: int = 7,
    ) -> Dict[str, Any]:
        """
        获取广告表现汇总

        整合多个广告报告数据，生成汇总视图。
        """
        search_terms = await self.get_sp_search_term_report(days_back=days_back)

        if not search_terms:
            return {
                "period_days": days_back,
                "total_impressions": 0,
                "total_clicks": 0,
                "total_cost": 0.0,
                "total_sales": 0.0,
                "acos": 0.0,
                "roas": 0.0,
                "ctr": 0.0,
                "cvr": 0.0,
                "top_search_terms": [],
            }

        total_impressions = sum(int(st.get("impressions", 0)) for st in search_terms)
        total_clicks = sum(int(st.get("clicks", 0)) for st in search_terms)
        total_cost = sum(float(st.get("cost", 0)) for st in search_terms)
        total_sales = sum(float(st.get("attributedSales14d", 0)) for st in search_terms)

        # 排序 Top 搜索词
        sorted_by_cost = sorted(search_terms, key=lambda x: float(x.get("cost", 0)), reverse=True)[:10]

        return {
            "period_days": days_back,
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_cost": round(total_cost, 2),
            "total_sales": round(total_sales, 2),
            "acos": round(total_cost / total_sales * 100, 2) if total_sales > 0 else 0,
            "roas": round(total_sales / total_cost, 2) if total_cost > 0 else 0,
            "ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0,
            "cvr": round(sum(float(st.get("attributedConversions14d", 0)) for st in search_terms) / total_clicks * 100, 2) if total_clicks > 0 else 0,
            "top_search_terms": [
                {
                    "term": st.get("searchTerm", ""),
                    "impressions": int(st.get("impressions", 0)),
                    "clicks": int(st.get("clicks", 0)),
                    "cost": round(float(st.get("cost", 0)), 2),
                    "sales": round(float(st.get("attributedSales14d", 0)), 2),
                    "acos": round(float(st.get("cost", 0)) / max(float(st.get("attributedSales14d", 0)), 0.01) * 100, 2),
                }
                for st in sorted_by_cost
            ],
        }

    # ====== 报告解析工具 ======

    @staticmethod
    def _decode_document(data: Optional[str]) -> Optional[str]:
        """解码报告文档（Base64 + GZIP）"""
        if not data:
            return None

        try:
            decoded = base64.b64decode(data)
            decompressed = gzip.decompress(decoded).decode("utf-8")
            return decompressed
        except Exception as e:
            logger.error(f"文档解码失败: {e}")
            return None

    @staticmethod
    def _parse_tsv_to_dicts(data: Optional[str]) -> List[Dict[str, Any]]:
        """将 TSV 格式报告解析为字典列表"""
        content = ReportsAPI._decode_document(data)
        if not content:
            return []

        lines = content.strip().split("\n")
        if len(lines) < 2:
            return []

        headers = [h.strip().lower() for h in lines[0].split("\t")]
        rows = []

        for line in lines[1:]:
            values = line.split("\t")
            row_dict = {}
            for i, header in enumerate(headers):
                if i < len(values):
                    row_dict[header] = values[i].strip()
            rows.append(row_dict)

        return rows

    @staticmethod
    def _parse_json_report(data: Optional[str]) -> List[Dict[str, Any]]:
        """解析 JSON 格式报告"""
        import json

        content = ReportsAPI._decode_document(data)
        if not content:
            return []

        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                return [parsed]
            return []
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            return []

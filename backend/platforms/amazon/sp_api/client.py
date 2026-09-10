"""
Amazon SP-API 核心客户端

统一的 HTTP 请求层，封装所有 API 调用的公共逻辑：
- 认证头自动添加
- 错误处理与重试
- 响应解析
- 限流处理
- 日志记录
"""

import json
import logging
from typing import Optional, Dict, Any, List, TypeVar, Generic

from .auth import SPAPIClientAuth, get_spapi_auth, SPAPIConfig
from .models import (
    Marketplace,
    ItemByASIN,
    PricingItem,
    InventorySummary,
    Order,
    Report,
    ReportDocument,
    Campaign,
    AdPerformanceMetrics,
    SearchTermReportRow,
    CompetitorListing,
    BuyBoxData,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SPAPIClient:
    """
    Amazon SP-API 客户端

    提供所有 SP-API 操作的统一入口。
    """

    # API 版本常量
    API_VERSIONS = {
        "products": "2022-05-01",
        "orders": "v0",
        "reports": "2021-06-30",
        "catalog_items": "2020-12-01",
        "listings": "2021-08-01",
        "pricing": "2022-05-01",
        "inventory": "2024-03-06",
        "fba_inbound": "2024-03-20",
        "notifications": "v1",
    }

    def __init__(
        self,
        config: Optional[SPAPIConfig] = None,
        default_marketplace: Marketplace = Marketplace.US,
    ):
        """
        初始化 SP-API 客户端

        Args:
            config: SP-API 配置（为空则从 settings 加载）
            default_marketplace: 默认市场（美国）
        """
        self.auth = SPAPIClientAuth(config) if config else get_spapi_auth()
        self.default_marketplace = default_marketplace.value

    # ====== 通用请求方法 ======

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        marketplace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """发送认证后的 SP-API 请求"""

        # 添加市场 ID 参数
        request_params = dict(params or {})
        if marketplace_id or (not marketplace_id and method == "GET"):
            request_params["marketplaceIds"] = marketplace_id or self.default_marketplace

        logger.debug(f"SP-API {method} {endpoint}")

        result = await self.auth.make_authenticated_request(
            method=method,
            endpoint=endpoint,
            params=request_params,
            json_data=json_data,
        )

        return result

    async def _get(self, endpoint: str, **kwargs) -> Dict[str, Any]:
        return await self._request("GET", endpoint, **kwargs)

    async def _post(self, endpoint: str, json_data: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        return await self._request("POST", endpoint, json_data=json_data, **kwargs)

    # ====== Products API ======

    async def get_item_by_asin(
        self,
        asin: str,
        marketplace_id: Optional[str] = None,
        included_data: Optional[List[str]] = None,
    ) -> ItemByASIN:
        """
        通过 ASIN 获取商品详情

        Args:
            asin: 商品 ASIN
            marketplace_id: 市场 ID
            included_data: 需要包含的额外数据类型
                - attributes, dimensions, identifiers, images, productTypes, relationships, salesRanks, summaries

        Returns:
            商品详情对象
        """
        endpoint = f"/products/{self.API_VERSIONS['products']}/items/{asin}"
        params = {}

        if included_data:
            params["includedData"] = ",".join(included_data)
        else:
            # 默认获取常用数据
            params["includedData"] = "attributes,summaries,images,identifiers"

        response = await self._get(endpoint, params=params, marketplace_id=marketplace_id)

        item_data = response.get("item", response.get("Items", [{}])[0] if "Items" in response else {})
        return ItemByASIN(**item_data) if isinstance(item_data, dict) else ItemByASIN(asin=asin)

    async def get_item_offers(
        self,
        asin: str,
        condition: str = "New",
        customer_type: str = "Consumer",
        marketplace_id: Optional[str] = None,
    ) -> PricingItem:
        """
        获取商品报价信息

        Args:
            asin: 商品 ASIN
            condition: 成色 (New/Used)
            customer_type: 客户类型 (B2B/Consumer)
            marketplace_id: 市场 ID

        Returns:
            定价项（含多个报价）
        """
        endpoint = f"/products/pricing/{self.API_VERSIONS['pricing']}/items/{asin}/offers"
        params = {
            "condition": condition,
            "CustomerType": customer_type,
        }

        response = await self._get(endpoint, params=params, marketplace_id=marketplace_id)

        payload = response.get("payload", response)
        offers_raw = payload.get("Offers", [])

        pricing_item = PricingItem(asin=asin, marketplace_id=marketplace_id or self.default_marketplace)
        for offer_raw in offers_raw:
            try:
                offer = Offer(**offer_raw)
                pricing_item.offers.append(offer)
            except Exception as e:
                logger.warning(f"解析报价失败: {e}")

        return pricing_item

    async def get_batch_item_offers(
        self,
        asins: List[str],
        condition: str = "New",
        marketplace_id: Optional[str] = None,
    ) -> List[PricingItem]:
        """批量获取多个商品的报价"""
        results = []
        for asin in asins[:20]:  # SP-API 单次最多 20 个
            try:
                pricing = await self.get_item_offers(asin, condition=condition, marketplace_id=marketplace_id)
                results.append(pricing)
            except Exception as e:
                logger.warning(f"获取 {asin} 报价失败: {e}")
        return results

    async def get_inventory_summaries(
        self,
        marketplace_id: Optional[str] = None,
        granularity_type: str = "Marketplace",
        granularity_id: Optional[str] = None,
        next_token: Optional[str] = None,
    ) -> List[InventorySummary]:
        """
        获取库存摘要

        Args:
            granularity_type: 粒度类型 (Marketplace/SellerSKU)
            granularity_id: 粒度 ID
            next_token: 分页令牌
        """
        endpoint = f"/fba/inventory/{self.API_VERSIONS['inventory']}/summaries"
        params = {
            "granularityType": granularity_type,
            "granularityId": granularity_id or self.default_marketplace,
        }
        if next_token:
            params["nextToken"] = next_token

        response = await self._get(endpoint, params=params, marketplace_id=marketplace_id)

        summaries_raw = response.get("payload", {}).get("inventorySummaries", [])
        return [InventorySummary(**s) for s in summaries_raw]

    async def search_catalog_items(
        self,
        keywords: List[str],
        marketplace_id: Optional[str] = None,
        page_size: int = 20,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        搜索目录商品

        Args:
            keywords: 关键词列表
            page_size: 每页数量
            page_token: 分页令牌
        """
        endpoint = f"/catalog/{self.API_VERSIONS['catalog_items']}/items"
        params = {
            "keywords": ",".join(keywords),
            "pageSize": min(page_size, 20),
        }
        if page_token:
            params["pageToken"] = page_token

        response = await self._get(endpoint, params=params, marketplace_id=marketplace_id)
        return response.get("payload", response)

    # ====== Orders API ======

    async def get_orders(
        self,
        created_after: str,
        created_before: Optional[str] = None,
        last_updated_after: Optional[str] = None,
        order_statuses: Optional[List[str]] = None,
        fulfillment_channels: Optional[List[str]] = None,
        max_results_per_page: int = 50,
        next_token: Optional[str] = None,
        marketplace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取订单列表

        Args:
            created_after: 创建时间起始 (ISO 8601)
            created_before: 创建时间结束
            last_updated_after: 最后更新时间起始
            order_statuses: 订单状态过滤
            max_results_per_page: 每页最大数量
            next_token: 分页令牌
        """
        endpoint = f"/orders/{self.API_VERSIONS['orders']}/orders"
        params = {
            "CreatedAfter": created_after,
            "MaxResultsPerPage": max_results_per_page,
        }

        if created_before:
            params["CreatedBefore"] = created_before
        if last_updated_after:
            params["LastUpdatedAfter"] = last_updated_after
        if order_statuses:
            params["OrderStatuses"] = ",".join(order_statuses)
        if fulfillment_channels:
            params["FulfillmentChannels"] = ",".join(fulfillment_channels)
        if next_token:
            params["NextToken"] = next_token

        return await self._get(endpoint, params=params, marketplace_id=marketplace_id)

    async def get_order(self, order_id: str) -> Order:
        """
        获取订单详情

        Args:
            order_id: Amazon 订单号
        """
        endpoint = f"/orders/{self.API_VERSIONS['orders']}/orders/{order_id}"
        response = await self._get(endpoint)

        payload = response.get("payload", response)
        return Order(**payload)

    async def get_order_items(
        self,
        order_id: str,
        next_token: Optional[str] = None,
    ) -> List[Any]:
        """
        获取订单商品项

        Args:
            order_id: Amazon 订单号
            next_token: 分页令牌
        """
        endpoint = f"/orders/{self.API_VERSIONS['orders']}/orderItems/{order_id}"
        params = {}
        if next_token:
            params["NextToken"] = next_token

        response = await self._get(endpoint, params=params)
        payload = response.get("payload", {})
        return payload.get("OrderItems", [])

    # ====== Reports API ======

    async def create_report(
        self,
        report_type: str,
        data_start_time: Optional[str] = None,
        data_end_time: Optional[str] = None,
        marketplace_ids: Optional[List[str]] = None,
        report_options: Optional[Dict[str, str]] = None,
    ) -> Report:
        """
        创建报告任务

        Args:
            report_type: 报告类型（如 GET_FLAT_FILE_OPEN_LISTINGS_DATA）
            data_start_time: 数据起始时间
            data_end_time: 数据结束时间
            marketplace_ids: 市场列表
            report_options: 报告选项
        """
        endpoint = f"/reports/{self.API_VERSIONS['reports']}/reports"

        body = {
            "reportType": report_type,
            "marketplaceIds": marketplace_ids or [self.default_marketplace],
        }
        if data_start_time:
            body["dataStartTime"] = data_start_time
        if data_end_time:
            body["dataEndTime"] = data_end_time
        if report_options:
            body["reportOptions"] = report_options

        response = await self._post(endpoint, json_data=body)
        payload = response.get("payload", response)
        return Report(**payload)

    async def get_report(self, report_id: str) -> Report:
        """获取报告状态"""
        endpoint = f"/reports/{self.API_VERSIONS['reports']}/reports/{report_id}"
        response = await self._get(endpoint)
        payload = response.get("payload", response)
        return Report(**payload)

    async def get_report_document(self, document_id: str) -> ReportDocument:
        """获取报告文档内容"""
        endpoint = f"/reports/{self.API_VERSIONS['reports']}/documents/{document_id}"
        response = await self._get(endpoint)
        payload = response.get("payload", response)
        return ReportDocument(**payload)

    async def wait_for_report(
        self,
        report_id: str,
        max_wait_seconds: int = 300,
        poll_interval: int = 10,
    ) -> ReportDocument:
        """
        等待报告生成完成并返回文档

        Args:
            report_id: 报告 ID
            max_wait_seconds: 最大等待秒数
            poll_interval: 轮询间隔秒数
        """
        import asyncio

        elapsed = 0
        while elapsed < max_wait_seconds:
            report = await self.get_report(report_id)

            if report.processing_status == "DONE":
                if report.report_document_id:
                    return await self.get_report_document(report.report_document_id)
                raise ValueError("报告已完成但无文档 ID")

            elif report.processing_status in ("CANCELLED", "FATAL"):
                raise ValueError(f"报告生成失败: {report.processing_status}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"报告生成超时 ({max_wait_seconds}s)")

    # ====== Advertising API (通过 SP-API 代理) ======

    async def get_ad_campaigns(
        self,
        campaign_type: str = "sponsoredProducts",
        state_filter: Optional[str] = None,
        query: Optional[str] = None,
        start_index: int = 0,
        count: int = 100,
    ) -> List[Campaign]:
        """
        获取广告活动列表

        注意：Advertising API 需要额外的 OAuth scope 和配置
        这里使用 SP-API 的受限代理方式调用
        """
        endpoint = f"/advertising/campaigns"
        params = {
            "campaignType": campaign_type,
            "startIndex": start_index,
            "count": count,
        }
        if state_filter:
            params["stateFilter"] = state_filter
        if query:
            params["query"] = query

        try:
            response = await self._get(endpoint, params=params)
            campaigns_raw = response.get("campaigns", [])
            return [Campaign(**c) for c in campaigns_raw]
        except Exception as e:
            logger.warning(f"获取广告活动失败（可能未开通权限）: {e}")
            return []

    async def get_search_term_report(
        self,
        report_record_type: str = "searchTerm",
        metrics: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ad_product: str = "sp",
    ) -> List[SearchTermReportRow]:
        """
        获取搜索词报告

        Args:
            report_record_type: 报告类型
            metrics: 指标列表
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)
            ad_product: 广告产品 (sp/sb/sd)
        """
        from datetime import datetime, timedelta

        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

        if not metrics:
            metrics = [
                "impressions", "clicks", "cost",
                "attributedConversions14d", "attributedSales14d",
                "attributedUnitsOrdered14d",
            ]

        # 使用 Reports API 获取广告报告
        report = await self.create_report(
            report_type=f"SP_{report_record_type.upper()}_REPORT",
            data_start_time=start_date,
            data_end_time=end_date,
            report_options={"segment": "query"},
        )

        try:
            doc = await self.wait_for_report(report.report_id)
            # 解析报告内容
            rows = self._parse_tsv_report(doc.data, SearchTermReportRow)
            return rows
        except Exception as e:
            logger.error(f"搜索词报告获取失败: {e}")
            return []

    # ====== 辅助方法 ======

    @staticmethod
    def _parse_tsv_report(data: Optional[str], model_class: type) -> List[Any]:
        """解析 TSV 格式报告"""
        if not data:
            return []

        import base64
        import gzip
        import io

        try:
            # 解码 Base64 并解压 GZIP
            decoded = base64.b64decode(data)
            decompressed = gzip.decompress(decoded).decode("utf-8")

            lines = decompressed.strip().split("\n")
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

                try:
                    row = model_class(**row_dict)
                    rows.append(row)
                except Exception:
                    continue

            return rows

        except Exception as e:
            logger.error(f"报告解析失败: {e}")
            return []

    async def health_check(self) -> bool:
        """健康检查：验证认证是否正常"""
        try:
            token = await self.auth.get_access_token()
            return bool(token and not token.startswith("Error"))
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False

    async def close(self) -> None:
        """关闭客户端连接"""
        await self.auth.close()


# ====== 便捷工厂函数 ======

_client_instance: Optional[SPAPIClient] = None


def get_spapi_client(marketplace: Marketplace = Marketplace.US) -> SPAPIClient:
    """获取全局 SP-API 客户端实例"""
    global _client_instance
    if _client_instance is None:
        _client_instance = SPAPIClient(default_marketplace=marketplace)
    return _client_instance


async def close_spapi_client() -> None:
    """关闭全局 SP-API 客户端"""
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None

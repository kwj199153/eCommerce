"""
Amazon SP-API Orders API 封装

提供订单管理相关的高级操作方法。
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from .client import SPAPIClient
from .models import (
    Order,
    OrderItem,
    OrderStatus,
    FulfillmentChannel,
)

logger = logging.getLogger(__name__)


class OrdersAPI:
    """
    Orders API 高级封装

    提供面向业务的方法：
    - 订单查询与追踪
    - 订单商品详情
    - 订单状态统计
    """

    def __init__(self, client: SPAPIClient):
        self.client = client

    # ====== 订单查询 ======

    async def get_orders_by_date_range(
        self,
        days_back: int = 7,
        statuses: Optional[List[str]] = None,
        max_orders: int = 200,
    ) -> List[Order]:
        """
        按日期范围获取订单

        Args:
            days_back: 往前多少天
            statuses: 订单状态过滤
            max_orders: 最大返回数量
        """
        created_after = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

        all_orders = []
        next_token = None

        while len(all_orders) < max_orders:
            response = await self.client.get_orders(
                created_after=created_after,
                order_statuses=statuses,
                max_results_per_page=min(50, max_orders - len(all_orders)),
                next_token=next_token,
            )

            payload = response.get("payload", response)
            orders_raw = payload.get("Orders", [])

            for o in orders_raw:
                try:
                    order = Order(**o)
                    all_orders.append(order)
                except Exception as e:
                    logger.warning(f"解析订单失败: {e}")

            next_token = payload.get("NextToken")
            if not next_token:
                break

        return all_orders[:max_orders]

    async def get_order_detail(self, order_id: str) -> Dict[str, Any]:
        """获取完整订单详情（含商品项）"""
        order = await self.client.get_order(order_id)
        items = await self.client.get_order_items(order_id)

        return {
            "order_id": order.amazon_order_id,
            "purchase_date": str(order.purchase_date) if order.purchase_date else None,
            "order_status": order.order_status.value if isinstance(order.order_status, OrderStatus) else order.order_status,
            "fulfillment_channel": order.fulfillment_channel.value if isinstance(order.fulfillment_channel, FulfillmentChannel) else order.fulfillment_channel,
            "order_total": {
                "amount": order.order_total.amount if order.order_total else 0,
                "currency": order.order_total.currency_code if order.order_total else "USD",
            },
            "shipping_address": {
                "name": order.shipping_address.name if order.shipping_address else None,
                "city": order.shipping_address.city if order.shipping_address else None,
                "state": order.shipping_address.state_or_region if order.shipping_address else None,
                "postal_code": order.shipping_address.postal_code if order.shipping_address else None,
                "country": order.shipping_address.country_code if order.shipping_address else None,
            } if order.shipping_address else None,
            "buyer_email": (order.buyer_info.buyer_email if order.buyer_info else None),
            "is_prime": order.is_prime,
            "items": [
                {
                    "asin": item.asin,
                    "sku": item.seller_sku,
                    "title": item.product_name,
                    "quantity": item.quantity_ordered,
                    "price": item.price_money.amount if item.price_money else 0,
                    "status": item.order_item_status,
                }
                for item in items
            ],
            "total_items": sum(i.quantity_ordered for i in items),
        }

    async def track_order(self, order_id: str) -> Dict[str, Any]:
        """
        追踪订单状态（用于客服场景）

        返回格式化的订单追踪信息。
        """
        try:
            detail = await self.get_order_detail(order_id)

            # 构建状态时间线
            status_timeline = []
            current_status = detail["order_status"]

            # 状态映射
            status_map = {
                "Pending": {"label": "待处理", "icon": "⏳", "description": "订单已创建，等待确认"},
                "Unshipped": {"label": "未发货", "icon": "📦", "description": "订单已确认，准备发货"},
                "PartiallyShipped": {"label": "部分发货", "icon": "🚚", "description": "部分商品已发货"},
                "Shipped": {"label": "已发货", "icon": "✈️", "description": "商品已发出，运输中"},
                "DeliveredToCarrier": {"label": "已交付承运商", "icon": "🏭", "description": "已交给物流公司"},
                "Canceled": {"label": "已取消", "icon": "❌", "description": "订单已取消"},
            }

            status_info = status_map.get(current_status, {"label": current_status, "icon": "❓", "description": ""})

            return {
                "found": True,
                "order_id": order_id,
                "current_status": {
                    "code": current_status,
                    **status_info,
                },
                "purchase_date": detail["purchase_date"],
                "item_count": detail["total_items"],
                "items_summary": [
                    f"{i['quantity']}x {i['title'] or i['asin']} (${i['price']:.2f})"
                    for i in detail["items"][:5]
                ],
                "shipping_to": (
                    f"{detail['shipping_address']['city']}, "
                    f"{detail['shipping_address']['state_or_region']}"
                    if detail.get("shipping_address") else "N/A"
                ),
                "is_prime": detail["is_prime"],
                "estimated_delivery": self._estimate_delivery(current_status, detail["purchase_date"]),
            }

        except Exception as e:
            logger.error(f"追踪订单 {order_id} 失败: {e}")
            return {
                "found": False,
                "order_id": order_id,
                "error": str(e),
            }

    # ====== 订单统计 ======

    async def get_order_statistics(
        self,
        days_back: int = 30,
    ) -> Dict[str, Any]:
        """获取订单统计数据"""
        orders = await self.get_orders_by_date_range(days_back=days_back, max_orders=1000)

        total_revenue = 0.0
        total_items = 0
        status_counts: Dict[str, int] = {}
        channel_counts: Dict[str, int] = {}
        prime_count = 0

        for order in orders:
            # 状态统计
            status = order.order_status.value if isinstance(order.order_status, OrderStatus) else str(order.order_status)
            status_counts[status] = status_counts.get(status, 0) + 1

            # 渠道统计
            channel = order.fulfillment_channel.value if isinstance(order.fulfillment_channel, FulfillmentChannel) else str(order.fulfillment_channel)
            channel_counts[channel] = channel_counts.get(channel, 0) + 1

            # Prime 统计
            if order.is_prime:
                prime_count += 1

            # 收入和数量
            if order.order_total:
                total_revenue += order.order_total.amount
            total_items += order.number_of_items_shipped + order.number_of_items_unshipped

        return {
            "period_days": days_back,
            "total_orders": len(orders),
            "total_revenue": round(total_revenue, 2),
            "total_items": total_items,
            "average_order_value": round(total_revenue / len(orders), 2) if orders else 0,
            "prime_rate": round(prime_count / len(orders) * 100, 1) if orders else 0,
            "status_breakdown": status_counts,
            "channel_breakdown": channel_counts,
            "daily_average_orders": round(len(orders) / days_back, 1),
        }

    # ====== 内部工具方法 ======

    @staticmethod
    def _estimate_delivery(status: str, purchase_date: Optional[str]) -> Optional[str]:
        """估算送达日期"""
        if not purchase_date or status in ("Pending", "Canceled"):
            return None

        try:
            purchased = datetime.fromisoformat(purchase_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

        delivery_estimates = {
            "Unshipped": (3, 7),  # 3-7 天
            "PartiallyShipped": (2, 5),
            "Shipped": (1, 3),
            "DeliveredToCarrier": (1, 3),
        }

        min_days, max_days = delivery_estimates.get(status, (0, 0))
        earliest = purchased + timedelta(days=min_days)
        latest = purchased + timedelta(days=max_days)

        return f"{earliest.strftime('%Y-%m-%d')} ~ {latest.strftime('%Y-%m-%d')}"

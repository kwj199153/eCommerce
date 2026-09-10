"""
Amazon SP-API Products API 封装

提供商品、报价、库存相关的高级操作方法。
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from .client import SPAPIClient
from .models import (
    ItemByASIN,
    PricingItem,
    InventorySummary,
    Offer,
    CompetitorListing,
    BuyBoxData,
    MoneyType,
)

logger = logging.getLogger(__name__)


class ProductsAPI:
    """
    Products API 高级封装

    提供面向业务的方法：
    - 商品详情获取
    - 竞品价格监控
    - 库存管理
    - Buy Box 分析
    """

    def __init__(self, client: SPAPIClient):
        self.client = client

    # ====== 商品信息 ======

    async def get_product_detail(self, asin: str) -> Dict[str, Any]:
        """获取完整商品详情（含报价和摘要）"""
        try:
            item = await self.client.get_item_by_asin(asin)
            pricing = await self.client.get_item_offers(asin)

            return {
                "asin": asin,
                "title": item.title,
                "brand": item.brand,
                "product_type": item.product_type,
                "attributes": item.attributes,
                "identifiers": item.identifiers,
                "pricing": {
                    "offers": [
                        {
                            "seller_id": o.seller_id,
                            "price": o.buying_price.price.amount if o.buying_price and o.buying_price.price else None,
                            "currency": o.buying_price.price.currency_code if o.buying_price and o.buying_price.price else None,
                            "condition": o.condition,
                            "is_buy_box_winner": o.is_buy_box_winner,
                            "is_fba": o.is_fulfilled_by_amazon,
                            "delivery_prime": o.delivery_info.is_prime if o.delivery_info else False,
                        }
                        for o in pricing.offers
                    ],
                    "total_offers": len(pricing.offers),
                    "buy_box_price": self._extract_buy_box_price(pricing.offers),
                    "lowest_price": self._extract_lowest_price(pricing.offers),
                },
            }
        except Exception as e:
            logger.error(f"获取商品 {asin} 详情失败: {e}")
            raise

    # ====== 竞品分析 ======

    async def get_competitor_listings(
        self,
        asins: List[str],
        include_pricing: bool = True,
    ) -> List[CompetitorListing]:
        """批量获取竞品 Listing 信息"""
        results = []

        for asin in asins:
            try:
                listing = CompetitorListing(asin=asin)

                # 获取基本信息
                item = await self.client.get_item_by_asin(asin)
                listing.title = item.title or ""
                listing.brand = item.brand
                listing.category = item.product_type

                # 获取报价
                if include_pricing:
                    pricing = await self.client.get_item_offers(asin)
                    listing.offer_count = len(pricing.offers)

                    buy_box_offer = next((o for o in pricing.offers if o.is_buy_box_winner), None)
                    if buy_box_offer and buy_box_offer.buying_price and buy_box_offer.buying_price.price:
                        listing.buy_box_price = buy_box_offer.buying_price.price.amount
                        listing.buy_box_seller_id = buy_box_offer.seller_id
                        listing.is_fba = buy_box_offer.is_fulfilled_by_amazon

                    lowest_offer = min(
                        [o for o in pricing.offers if o.buying_price and o.buying_price.price],
                        key=lambda o: o.buying_price.price.amount,
                        default=None,
                    )
                    if lowest_offer:
                        listing.price = lowest_offer.buying_price.price.amount

                listing.last_updated = datetime.now()
                results.append(listing)

            except Exception as e:
                logger.warning(f"获取竞品 {asin} 失败: {e}")
                continue

        return results

    # ====== 价格追踪 ======

    async def track_prices(
        self,
        asins: List[str],
    ) -> List[Dict[str, Any]]:
        """追踪多个 ASIN 的当前价格"""
        price_data = []

        for asin in asins:
            try:
                pricing = await self.client.get_item_offers(asin)

                offers_info = []
                for offer in pricing.offers[:10]:  # 只取前10个报价
                    offer_info = {
                        "seller_id": offer.seller_id,
                        "price": offer.buying_price.price.amount if offer.buying_price and offer.buying_price.price else None,
                        "condition": offer.condition,
                        "is_fba": offer.is_fulfilled_by_amazon,
                        "is_buy_box": offer.is_buy_box_winner,
                    }
                    offers_info.append(offer_info)

                price_data.append({
                    "asin": asin,
                    "timestamp": datetime.now().isoformat(),
                    "offers": offers_info,
                    "buy_box_price": self._extract_buy_box_price(pricing.offers),
                    "lowest_price": self._extract_lowest_price(pricing.offers),
                    "offer_count": len(pricing.offers),
                })

            except Exception as e:
                logger.warning(f"追踪 {asin} 价格失败: {e}")

        return price_data

    # ====== Buy Box 分析 ======

    async def analyze_buy_box(
        self,
        asin: str,
    ) -> BuyBoxData:
        """分析指定商品的 Buy Box 情况"""
        data = BuyBoxData(asin=asin)

        try:
            pricing = await self.client.get_item_offers(asin)
            data.total_offers = len(pricing.offers)

            fba_offers = [o for o in pricing.offers if o.is_fulfilled_by_amazon]
            fbm_offers = [o for o in pricing.offers if not o.is_fulfilled_by_amazon]
            data.fba_offers = len(fba_offers)
            data.fbm_offers = len(fbm_offers)

            # Buy Box 赢家
            winner = next((o for o in pricing.offers if o.is_buy_box_winner), None)
            if winner:
                data.winner_seller_id = winner.seller_id
                data.winner_condition = winner.condition
                data.winner_fulfillment = "FBA" if winner.is_fulfilled_by_amazon else "FBM"
                if winner.buying_price and winner.buying_price.price:
                    data.winner_price = winner.buying_price.price.amount

            # 最低 FBA/FBM 价格
            fba_prices = [
                o.buying_price.price.amount
                for o in fba_offers
                if o.buying_price and o.buying_price.price
            ]
            fbm_prices = [
                o.buying_price.price.amount
                for o in fbm_offers
                if o.buying_price and o.buying_price.price
            ]

            data.lowest_fba_price = min(fba_prices) if fba_prices else None
            data.lowest_fbm_price = min(fbm_prices) if fbm_prices else None

        except Exception as e:
            logger.error(f"Buy Box 分析失败 ({asin}): {e}")

        return data

    # ====== 库存查询 ======

    async def get_inventory_summary(
        self,
        seller_skus: Optional[List[str]] = None,
    ) -> List[InventorySummary]:
        """获取库存摘要（可按 SKU 过滤）"""
        summaries = await self.client.get_inventory_summaries()

        if seller_skus:
            summaries = [s for s in summaries if s.seller_sku in (seller_skus or [])]

        return summaries

    # ====== 目录搜索 ======

    async def search_products(
        self,
        keywords: List[str],
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """通过关键词搜索目录商品"""
        response = await self.client.search_catalog_items(
            keywords=keywords,
            page_size=page_size,
        )

        items_raw = response.get("Items", response.get("items", []))
        results = []

        for item in items_raw:
            asin = item.get("asin", "")
            summary = item.get("summary", {})

            results.append({
                "asin": asin,
                "title": item.get("itemName", ""),
                "brand": summary.get("brand", ""),
                "product_type": item.get("productType", ""),
                "image_url": (item.get("images") or [{}])[0].get("link", "") if item.get("images") else "",
                "rating": summary.get("starsRating"),
                "review_count": summary.get("reviewCount", 0),
            })

        return results

    # ====== 内部工具方法 ======

    @staticmethod
    def _extract_buy_box_price(offers: List[Offer]) -> Optional[float]:
        """从报价列表中提取 Buy Box 价格"""
        buy_box = next((o for o in offers if o.is_buy_box_winner), None)
        if buy_box and buy_box.buying_price and buy_box.buying_price.price:
            return buy_box.buying_price.price.amount
        return None

    @staticmethod
    def _extract_lowest_price(offers: List[Offer]) -> Optional[float]:
        """从报价列表中提取最低价格"""
        valid_prices = [
            o.buying_price.price.amount
            for o in offers
            if o.buying_price and o.buying_price.price
        ]
        return min(valid_prices) if valid_prices else None

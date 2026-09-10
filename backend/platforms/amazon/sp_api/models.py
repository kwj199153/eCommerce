"""
Amazon SP-API 数据模型

定义所有 SP-API 接口的请求/响应数据结构。

参考：
- Products API: https://developer-docs.amazon.com/sp-api/reference/products-api-v2022-05-01.html
- Orders API: https://developer-docs.amazon.com/sp-api/reference/orders-api-v0.html
- Reports API: https://developer-docs.amazon.com/sp-api/reference/reports-api-2021-06-30.html
- Advertising API: https://advertising.amazon.com/API/docs/en-us
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


# ====== 通用模型 ======

class Marketplace(str, Enum):
    """Amazon 市场枚举"""
    US = "ATVPDKIKX0DER"  # 美国
    CA = "A2EUQ1WTGCTBG2"  # 加拿大
    MX = "A1AM78C64UM0Y8"  # 墨西哥
    UK = "A1F83G8C2ARO7P"  # 英国
    DE = "A1PA6795UKMFR9"  # 德国
    FR = "A13V1IB3VIYZZH"  # 法国
    IT = "APJ6JRA9NG5V4"  # 意大利
    ES = "A1RKKUPIHCS9HS"  # 西班牙
    JP = "A1VC38T7YXB528"  # 日本
    AU = "A39IBJ37TRP1C6"  # 澳大利亚


class FulfillmentChannel(str, Enum):
    """履约渠道"""
    AMAZON = "Amazon"
    MERCHANT = "Merchant"


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "Pending"
    UNshipped = "Unshipped"
    PARTIALLY_SHIPPED = "PartiallyShipped"
    SHIPPED = "Shipped"
    CANCELED = "Canceled"
    DELIVERED_TO_CARRIER = "DeliveredToCarrier"


# ====== Products API 模型 ======

class ItemByASIN(BaseModel):
    """通过 ASIN 获取的商品信息"""
    asin: str
    title: Optional[str] = None
    product_type: Optional[str] = None
    brand: Optional[str] = None
    manufacturer: Optional[str] = None
    part_number: Optional[str] = None
    model_number: Optional[str] = None
    item_package_quantity: Optional[int] = None
    number_of_items: Optional[int] = None
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)
    identifiers: Optional[Dict[str, Any]] = Field(default_factory=dict)


class OfferCustomerType(str, Enum):
    """报价客户类型"""
    B2B = "B2B"
    B2C = "B2C"


class OfferCondition(str, Enum):
    """商品成色"""
    NEW = "New"
    USED = "Used"


class MoneyType(BaseModel):
    """金额类型"""
    amount: float = 0.0
    currency_code: str = "USD"


class Points(BaseModel):
    """积分信息"""
    points_number: int = 0
    monetary_value: Optional[MoneyType] = None


class OfferBuyingPrice(BaseModel):
    """购买价格"""
    price: Optional[MoneyType] = None
    discount: Optional[MoneyType] = None
    points: Optional[Points] = None


class OfferShippingPrice(BaseModel):
    """运费价格"""
    price: Optional[MoneyType] = None
    discount: Optional[MoneyType] = None
    availability_type: Optional[str] = None  # FAST_AND_FREE, etc.


class OfferDeliveryInfo(BaseModel):
    """配送信息"""
    earliest_delivery_date: Optional[datetime] = None
    latest_delivery_date: Optional[datetime] = None
    is_eligible_for_super_saver_shipping: bool = False
    is_prime: bool = False
    is_eligible_for_free_shipping: bool = False


class SellerFeedbackRating(BaseModel):
    """卖家反馈评分"""
    seller_positive_feedback_rating: float = 0.0
    feedback_count: int = 0


class SubConditionType(str, Enum):
    """子成色类型"""
    NEW = "New"
    LIKE_NEW = "LikeNew"
    VERY_GOOD = "VeryGood"
    GOOD = "Good"
    ACCEPTABLE = "Acceptable"


class Offer(BaseModel):
    """商品报价"""
    asin: str = ""
    seller_id: str = ""
    condition: str = "New"
    sub_condition: Optional[str] = None
    buying_price: Optional[OfferBuyingPrice] = None
    shipping_price: Optional[OfferShippingPrice] = None
    delivery_info: Optional[OfferDeliveryInfo] = None
    is_buy_box_winner: bool = False
    is_featured_merchant: bool = False
    is_fulfilled_by_amazon: bool = False
    listing_status: str = "Active"
    seller_feedback_rating: Optional[SellerFeedbackRating] = None
    shipping_time: Optional[Dict[str, Any]] = None
    shipment_availability_type: Optional[str] = None


class PricingItem(BaseModel):
    """定价项（包含多个报价）"""
    asin: str = ""
    marketplace_id: str = ""
    offers: List[Offer] = Field(default_factory=list)


class InventorySummary(BaseModel):
    """库存摘要"""
    asin: str = ""
    fn_sku: str = ""
    seller_sku: str = ""
    condition: str = "NewItem"
    inventory_details: Optional[Dict[str, Any]] = None
    supply_quantity: int = 0
    quantity_on_order: int = 0
    received_quantity: int = 0
    inbound_shipped_quantity: int = 0
    inbound_receiving_quantity: int = 0
    inbound_working_quantity: int = 0
    inbound_queued_quantity: int = 0
    fc_processing_quantity: int = 0
    total_quantity: int = 0


# ====== Orders API 模型 ======

class Address(BaseModel):
    """地址"""
    name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    address_line3: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    district: Optional[str] = None
    state_or_region: Optional[str] = None
    postal_code: Optional[str] = None
    country_code: Optional[str] = None
    phone: Optional[str] = None


class OrderItemBuyerInfo(BaseModel):
    """买家信息"""
    buyer_email: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_tax_info: Optional[Dict[str, Any]] = None


class PaymentExecutionDetailItem(BaseModel):
    """支付详情"""
    payment_method: Optional[str] = None
    payment_execution_detail: Optional[List[Dict[str, Any]]] = None


class OrderItem(BaseModel):
    """订单商品项"""
    order_item_id: str = ""
    asin: str = ""
    seller_sku: str = ""
    order_item_status: Optional[str] = None
    quantity_ordered: int = 0
    quantity_shipped: int = 0
    product_info: Optional[Dict[str, Any]] = None
    price_money: Optional[MoneyType] = None
    item_tax: Optional[MoneyType] = None
    shipping_money: Optional[MoneyType] = None
    shipping_tax: Optional[MoneyType] = None
    gift_wrap_price: Optional[MoneyType] = None
    gift_wrap_tax: Optional[MoneyType] = None
    item_promotion_discount: Optional[MoneyType] = None
    ship_promotion_discount: Optional[MoneyType] = None
    promotion_ids: List[str] = Field(default_factory=list)
    cod_fee: Optional[MoneyType] = None
    cod_fee_discount: Optional[MoneyType] = None
    is_gift: bool = False
    condition_note: Optional[str] = None
    condition_subtype_id: Optional[str] = None
    condition_type: Optional[str] = None
    scheduled_delivery_start_date: Optional[datetime] = None
    scheduled_delivery_end_date: Optional[datetime] = None
    price_designation: Optional[str] = None
    buyer_info: Optional[OrderItemBuyerInfo] = None
    tax_collection: Optional[Dict[str, Any]] = None
    product_name: Optional[str] = None
    serial_number_required: bool = False
    deazon_reselling: bool = False
    is_transparent_box: bool = False
    ioss_number: Optional[str] = None
    store_chain_store_id: Optional[str] = None
    store_chain_store_name: Optional[str] = None


class Order(BaseModel):
    """订单"""
    amazon_order_id: str = ""
    purchase_date: Optional[datetime] = None
    last_update_date: Optional[datetime] = None
    order_status: OrderStatus = OrderStatus.PENDING
    fulfillment_channel: FulfillmentChannel = FulfillmentChannel.MERCHANT
    sales_channel: str = "Amazon.com"
    order_channel: Optional[str] = None
    ship_service_level: Optional[str] = None
    order_total: Optional[MoneyType] = None
    number_of_items_shipped: int = 0
    number_of_items_unshipped: int = 0
    payment_method: Optional[str] = None
    payment_execution_detail: Optional[List[PaymentExecutionDetailItem]] = None
    is_business_order: bool = False
    is_premium_order: bool = False
    is_prime: bool = False
    is_global_express_enabled: bool = False
    promised_delivery_due_date: Optional[datetime] = None
    earliest_delivery_date: Optional[datetime] = None
    latest_delivery_date: Optional[datetime] = None
    earliest_ship_date: Optional[datetime] = None
    latest_ship_date: Optional[datetime] = None
    delivery_timeline: Optional[Dict[str, Any]] = None
    is_access_point_delivery: bool = False
    hasautomated_shipping_settings: bool = False
    easy_ship_shipments: Optional[List[Dict[str, Any]]] = None
    electronic_invoice_status: Optional[str] = None
    is_ibee: bool = False
    buyer_info: Optional[OrderItemBuyerInfo] = None
    automations_replacements: Optional[Dict[str, Any]] = None
    fulfillment_instruction: Optional[str] = None
    shipping_address: Optional[Address] = None
    billing_address: Optional[Address] = None
    order_items: List[OrderItem] = Field(default_factory=list)


# ====== Reports API 模型 ======

class ReportProcessingStatus(str, Enum):
    """报告处理状态"""
    CANCELLED = "CANCELLED"
    DONE = "DONE"
    FATAL = "FATAL"
    IN_PROGRESS = "IN_PROGRESS"
    IN_QUEUE = "IN_QUEUE"


class Report(BaseModel):
    """报告"""
    report_id: str = ""
    report_type: str = ""
    data_start_time: Optional[datetime] = None
    data_end_time: Optional[datetime] = None
    created_time: Optional[datetime] = None
    processing_status: ReportProcessingStatus = ReportProcessingStatus.IN_QUEUE
    processing_start_time: Optional[datetime] = None
    processing_end_time: Optional[datetime] = None
    report_document_id: Optional[str] = None
    marketplace_ids: List[str] = Field(default_factory=list)


class ReportDocument(BaseModel):
    """报告文档"""
    report_document_id: str = ""
    url: Optional[str] = None
    compression_algorithm: Optional[str] = None  # GZIP
    data: Optional[str] = None  # Base64 编码内容


# ====== Advertising API 模型 ======

class CampaignType(str, Enum):
    """广告活动类型"""
    SPONSORED_PRODUCTS = "sponsoredProducts"
    SPONSORED_BRANDS = "sponsoredBrands"
    SPONSOED_DISPLAY = "sponsoredDisplay"
    DSP = "dsp"


class CampaignState(str, Enum):
    """广告活动状态"""
    ENABLED = "enabled"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CampaignBudgetType(str, Enum):
    """预算类型"""
    DAILY = "daily"


class Budget(BaseModel):
    """预算"""
    budget_type: CampaignBudgetType = CampaignBudgetType.DAILY
    budget: Optional[float] = Field(None, alias="budget")  # 避免与字段名冲突
    currency_code: str = "USD"

    class Config:
        populate_by_name = True


class BiddingStrategy(BaseModel):
    """出价策略"""
    strategy: str = ""  # legacyForSales, fixed, dynamic - etc.
    adjustments: Optional[List[Dict[str, Any]]] = None


class AdGroup(BaseModel):
    """广告组"""
    ad_group_id: str = ""
    name: str = ""
    campaign_id: str = ""
    default_bid: Optional[float] = None
    state: CampaignState = CampaignState.ENABLED
    serving_status: Optional[str] = None


class KeywordText(str, Enum):
    """关键词匹配类型"""
    BROAD = "broad"
    PHRASE = "phrase"
    EXACT = "exact"


class Keyword(BaseModel):
    """关键词"""
    keyword_id: str = ""
    ad_group_id: str = ""
    campaign_id: str = ""
    keyword_text: str = ""
    match_type: KeywordText = KeywordText.PHRASE
    state: CampaignState = CampaignState.ENABLED
    bid: Optional[float] = None
    serving_status: Optional[str] = None


class Campaign(BaseModel):
    """广告活动"""
    campaign_id: str = ""
    name: str = ""
    advertiser_id: str = ""
    state: CampaignState = CampaignState.ENABLED
    daily_budget: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    targeting_type: Optional[str] = None
    bidding_strategy: Optional[BiddingStrategy] = None
    portfolio_id: Optional[str] = None
    campaign_type: CampaignType = CampaignType.SPONSORED_PRODUCTS
    serving_status: Optional[str] = None
    creation_date: Optional[str] = None
    last_updated_date: Optional[str] = None


class AdPerformanceMetrics(BaseModel):
    """广告表现指标"""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    attributed_conversions_1d: int = 0
    attributed_conversions_7d: int = 0
    attributed_conversions_14d: int = 0
    attributed_conversions_30d: int = 0
    attributed_units_ordered_1d: int = 0
    attributed_sales_1d: float = 0.0
    attributed_sales_7d: float = 0.0
    attributed_sales_14d: float = 0.0
    attributed_sales_30d: float = 0.0

    @property
    def ctr(self) -> float:
        """点击率"""
        return (self.clicks / self.impressions * 100) if self.impressions > 0 else 0.0

    @property
    def cpc(self) -> float:
        """平均点击成本"""
        return (self.cost / self.clicks) if self.clicks > 0 else 0.0

    @property
    def acos(self) -> float:
        """广告销售成本比"""
        return (self.cost / self.attributed_sales_1d * 100) if self.attributed_sales_1d > 0 else 0.0

    @property
    def roas(self) -> float:
        """广告支出回报率"""
        return (self.attributed_sales_1d / self.cost) if self.cost > 0 else 0.0

    @property
    def cvr(self) -> float:
        """转化率"""
        return (self.attributed_conversions_1d / self.clicks * 100) if self.clicks > 0 else 0.0


class SearchTermReportRow(BaseModel):
    """搜索词报告行"""
    search_term: str = ""
    campaign_name: str = ""
    ad_group_name: str = ""
    keyword_text: Optional[str] = None
    matched_keyword_text: Optional[str] = None
    match_type: Optional[str] = None
    customer_search_term_id: Optional[str] = None
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    attributed_conversions_14d: int = 0
    attributed_units_ordered_14d: int = 0
    attributed_sales_14d: float = 0.0
    date: Optional[str] = None

    @property
    def ctr(self) -> float:
        return (self.clicks / self.impressions * 100) if self.impressions > 0 else 0.0

    @property
    def acos(self) -> float:
        return (self.cost / self.attributed_sales_14d * 100) if self.attributed_sales_14d > 0 else 0.0

    @property
    def cpc(self) -> float:
        return (self.cost / self.clicks) if self.clicks > 0 else 0.0


class ProductAd(BaseModel):
    """产品广告"""
    ad_id: str = ""
    campaign_id: str = ""
    ad_group_id: str = ""
    asin: str = ""
    sku: str = ""
    state: CampaignState = CampaignState.ENABLED
    serving_status: Optional[str] = None


# ====== 竞品分析专用模型 ======

class CompetitorListing(BaseModel):
    """竞品 Listing 信息"""
    asin: str = ""
    title: str = ""
    brand: Optional[str] = None
    price: Optional[float] = None
    rating: Optional[float] = None
    review_count: int = 0
    bsr_rank: Optional[int] = None
    category: Optional[str] = None
    image_url: Optional[str] = None
    buy_box_price: Optional[float] = None
    buy_box_seller_id: Optional[str] = None
    is_fba: Optional[bool] = None
    offer_count: int = 0
    last_updated: Optional[datetime] = None


class PriceHistoryPoint(BaseModel):
    """价格历史数据点"""
    date: str = ""
    price: float = 0.0
    currency: str = "USD"
    is_buy_box: bool = False
    is_deal: bool = False
    is_prime_exclusive: bool = False


class BuyBoxData(BaseModel):
    """Buy Box 数据"""
    asin: str = ""
    winner_seller_id: Optional[str] = None
    winner_price: Optional[float] = None
    winner_condition: Optional[str] = None
    winner_fulfillment: Optional[str] = None
    total_offers: int = 0
    fba_offers: int = 0
    fbm_offers: int = 0
    lowest_fba_price: Optional[float] = None
    lowest_fbm_price: Optional[float] = None
    our_offer_in_buy_box: bool = False
    our_competitiveness_score: Optional[float] = None

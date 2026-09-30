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
  fetch_order_tracking()   → OrderTrackingDict（单订单，客服场景）  [新增]
  fetch_orders(...)        → OrderBatchDict（批量订单+明细+物流，落库用）  [新增]
  fetch_customer_reviews(...) → ReviewBatchDict（批量买家评论，落库用）  [新增]
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

    # ---- 可选钩子：单订单查询（客服场景）----

    def fetch_order_tracking(self, order_id: str) -> dict:
        """
        按订单号查询**单个**订单的追踪信息（客服场景）。

        ★ 非抽象钩子，默认实现是 fail-closed 的：没有接入真实订单源的
          数据源如实回「查不到」，而不是回一条随机生成的假订单 ——
          后者等于把编造内容直接告诉终端消费者（本项目真实发生过）。

        Returns:
            {"found": True, "order_id": ..., "current_status": {...}, ...}
            或 {"found": False, "order_id": ..., "error": <原因>}
        """
        return {
            "found": False,
            "order_id": order_id,
            "error": (
                f"{type(self).__name__} 未实现单订单查询"
                "（该数据源不提供订单追踪，禁止编造订单内容）"
            ),
        }

    # ---- 可选钩子：订单域批量拉取（供 modules/trade/sync.py 落库）----

    def fetch_orders(
        self,
        shop_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 200,
    ) -> dict:
        """
        批量拉取订单（含明细 + 物流）——「订单落库同步」的上游。

        ★★ 注意第一个参数与其余 `fetch_*` 不同：那些是 `store_id: int`
           （历史包袱：amazon_sp 老接口按数字店铺 id 取数），而这里是
           `shop_id: str`。订单域落的是**本仓自有模型**，租户键就是
           `shop_id` 字符串（`store_xxxxxxxx`）。照抄 int 会让调用方
           被迫把一个字符串塞进 int 位，类型错配**不会报错** —— 这正是
           本项目反复吃的亏，所以宁可显式不一致，也不要静默错配。
        ★★ 为什么返回 dict 而不是 list：**「不支持」与「拉到 0 条」必须可分**。
           返回 list 时两者都长得像 `[]`，同步任务会把「这个数据源根本没有
           订单能力」误读成「这家店今天没有单」，然后静默收工 ——
           现象是「订单表一直是空的」且**没有任何报错**，排查方向会完全跑偏
           （会去查是不是调度没跑，而不是查数据源根本不支持）。
           这是本项目对**静默降级**的一贯立场。

        Returns:
            {"supported": True,  "source": <SOURCE_*>, "orders": [ {...}, ... ]}
            {"supported": False, "source": "", "orders": [], "reason": <为什么不支持>}

        ★ `source` 由数据源**自己声明**自己可不可信：Mock 声明 `mock_seed`，
          真实 SP-API 声明 `platform_api`。换接入路径不改上层。

        单个 order 载荷字段与 orders / order_items / shipments 三张表对齐：
            {external_order_id, platform, marketplace, buyer_id, buyer_name,
             order_status, fulfillment_channel, ship_country, ship_state,
             ship_city, currency, order_total, purchase_at, promised_at,
             shipped_at, delivered_at,
             items: [{external_order_item_id, sku, asin, item_title, image,
                      quantity, currency, unit_price, item_total}],
             shipment: {carrier, tracking_no, ship_status, shipped_at, promised_at,
                        delivered_at, last_event_at, last_location,
                        last_event_text, events: [{at, status, location, description}]},
             raw: {...}}
        ★ 派生态（transit_days / delay_days）**不在**载荷里 —— 由落库方调
          `trade.service.compute_transit_and_delay` 算，适配层不许自己算。
        """
        return {
            "supported": False,
            "source": "",
            "orders": [],
            "reason": (
                f"{type(self).__name__} 未实现订单批量拉取"
                "（该数据源不提供订单数据，禁止编造订单内容）"
            ),
        }

    def fetch_customer_reviews(
        self,
        shop_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 200,
    ) -> dict:
        """
        批量拉取买家评论 / 差评 ——「差评落库同步」的上游。

        ★★ 注意第一个参数与其余 `fetch_*` 不同：那些是 `store_id: int`
           （历史包袱：amazon_sp 老接口按数字店铺 id 取数），而这里是
           `shop_id: str`。订单域落的是**本仓自有模型**，租户键就是
           `shop_id` 字符串（`store_xxxxxxxx`）。照抄 int 会让调用方
           被迫把一个字符串塞进 int 位，类型错配**不会报错** —— 这正是
           本项目反复吃的亏，所以宁可显式不一致，也不要静默错配。
        ★ 与 `fetch_orders` 同样的 fail-closed 形态，而且**更该如此**：
          SP-API 没有 Reviews API（已对第三方关闭），所以「不支持」是**常态**
          而不是异常。数据源必须能如实说出这句话，而不是回一批凭空生成的
          差评 —— 那等于拿编造的差评去喂归因与 SKU 健康分，
          「包装破损上升 40%」会变成一个**看上去完全可信的假结论**。

        Returns:
            {"supported": True,  "source": <SOURCE_*>, "reviews": [ {...}, ... ]}
            {"supported": False, "source": "", "reviews": [], "reason": ...}

        单个 review 载荷字段与 customer_reviews 表对齐：
            {external_review_id, platform, marketplace, order_ref, sku, asin,
             product_title, rating, title, body, language, review_at,
             verified_purchase, helpful_votes, images, buyer_name, raw}
        ★ `order_ref` 是**平台侧订单号**（不是自家 orders.id）—— 能否关联上
          由落库方查表决定，关联不到就留空（评论未必能反查到订单）。
        """
        return {
            "supported": False,
            "source": "",
            "reviews": [],
            "reason": (
                f"{type(self).__name__} 未实现买家评论拉取"
                "（该数据源不提供评论数据，禁止编造买家反馈）"
            ),
        }

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

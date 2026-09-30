"""
交易履约 + 买家反馈域 —— **平台无关**的自有数据模型
====================================================

★★★ 先读这一段：为什么叫 `trade` 而不是 `reviews`
---------------------------------------------------
本仓 `review*` 是一块**已被占用的命名空间**，而且语义完全不同：

    modules/review_analyst/          运营复盘 Agent（周报/月报/广告归因/利润审计）
    modules/review_analyst/db_model  表 review_reports  = 归档的复盘报告
    review_analyst/tools.py          工具 list_reviews  = 列复盘库归档

它们都不是「买家差评」。本模块的 8 张表才是。

=> 所以本模块叫 `trade`（交易履约 + 买家反馈），买家评论表叫 `customer_reviews`
   （不叫 `reviews`），对应工具叫 `list_customer_reviews`。
   命名坑踩过一次就够了 —— 详见 `docs/round-283-review-scenario-gap.md`。

====================================================
★ 为什么是「自己的数据模型」而不是照抄某个平台的字段
====================================================
上层要回答的是「这笔订单是不是迟了」「这条差评是不是包装问题」，
这些问题**与平台无关**。照抄某个平台会立刻遇到三个事实：

  · SP-API 的 Orders API **不返回**运单号与承运商（那属 Shipping API，
    见 `amazon_sp/data_sources/sp_api_source.py:529` 处的说明）；
  · SP-API **没有** Reviews API（已对第三方关闭）；
  · Shopee / Temu 的分期送货、COD 等概念亚马逊根本没有。

照抄 => 每接一个平台就改一次上层。本模型因此只保留**跨平台都存在的最小事实**：

    订单买了什么、什么时候买的、承诺什么时候到、实际什么时候到、
    买家给了几分、说了什么、我们判成什么原因、赔了多少。

平台私有字段一律塞 `raw` JSON（**只存档，不参与查询**）；
平台差异交给适配层（`amazon_sp/data_sources/*`），上层不感知。

====================================================
★ 两条写入语义共用一张表 —— `source` + `fetched_at` 为此存在
====================================================
差评的接入路径尚未拍板（卖家后台导出 CSV / 第三方数据服务 / 平台推送），
而不同路径的语义**不同**：

    · 增量同步：按 `external_*` 幂等 upsert，能更新、能反映删除；
    · 全量快照：整批覆盖某一区间，缺了的不代表消失（可能只是没导出）。

本模型对两者**都成立**，差异由 `source` + `fetched_at` 承载：
每行数据「是谁给的、什么时候拉的」永远可查，适配层据此决定 upsert 还是重建。
=> **换接入路径不用改表**，这是本模型现在最值钱的一个性质。

====================================================
★ 派生态（transit_days / delay_days / negative_rate）为什么落成**列**
====================================================
「12 天才收到」「近 7 天上升 40%」这类判断，若让上层在**调用现场**
拿两个字符串算日期差，就等于让 LLM 做算术 —— 它算错的概率不是零，
而且**错了看不出来**（「late 12 days」与「late 13 days」都像真的）。

=> 由**写入方**在落库时用同一份规则算好、落列：
    transit_days = delivered_at - shipped_at
    delay_days   = delivered_at - promised_at（> 0 即迟到）
唯一真源 = 那两个时间戳本身；列只是它们的派生物，不独立编辑。

====================================================
租户与一致性（沿用本仓既有范式）
====================================================
· **每张表都有 `shop_id`**，并带 `fk_<table>_shop_id_stores_store`
  （`ondelete=RESTRICT`）—— `tests/test_schema_parity.py` 的核心不变量
  按这个名字查 `pg_constraint`：有 `shop_id` 列的表必须有指向 `stores_store` 的外键。
· 时间字段用 `String(64)` 存 ISO 串（与 cs_tickets / monitors / review_reports 一致），
  避开 naive/aware 时区议题。
· 嵌套结构用 `JSON` 列整体存取。
· 幂等键走 `UniqueConstraint`：重复拉取是 UPDATE 而不是 INSERT。
· **故意不**给 `sku` / `asin` 建外键指向 `skus` 表：订单号 / 运单号 / 评论 id
  是**平台侧标识符**，其存在的意义就是「与平台对得上」，
  不能因为本地产品库少了一行就让整笔订单插不进来。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


# ====== 归因码表（**唯一真源**：UI 下拉 / 规则匹配 / 统计口径全读它）======
#
# ★★ 为什么必须先定死一张码表，而不是让 LLM 自由发挥：
#    「物流太慢」可以被表述成 logistics_delay / shipping_delay / slow_delivery /
#    delivery_delay / late_shipping ... 同一个现实五个名字 =>
#    统计「包装破损上升多少」时五个数对不上账，而这件事**不会报错**，
#    只会让结论不可信。
ATTRIBUTION_CAUSES: tuple[str, ...] = (
    "logistics_delay",       # 物流延迟：到货晚于承诺
    "packaging_failure",     # 包装破损：到货时外箱/内衬受损
    "product_defect",        # 商品缺陷：功能失效、做工问题
    "description_mismatch",  # 描述不符：实物与 Listing 描述不一致
    "service_attitude",      # 服务态度：沟通响应类问题
    "price_value",           # 价格价值投诉
    "unknown",               # ★ 判不出来就判出来 —— 不许猜
)

CAUSE_LABELS: dict[str, str] = {
    "logistics_delay": "物流延迟",
    "packaging_failure": "包装破损",
    "product_defect": "商品缺陷",
    "description_mismatch": "描述不符",
    "service_attitude": "服务态度",
    "price_value": "价格价值",
    "unknown": "未判定",
}

#: 数据源标记之一 —— 「这条数据是本仓 seed 造的演示数据」。
#   ★ 有它，上层才能在回答里**如实标注**当前跑的是演示数据；
#     没它，「看来可以作业了」与「这只是 mock」在界面上长得一模一样。
SOURCE_MOCK_SEED = "mock_seed"
SOURCE_CSV_IMPORT = "csv_import"
SOURCE_PLATFORM_API = "platform_api"


def _now() -> str:
    return datetime.utcnow().isoformat()


# ============================================================ 1. 订单

class OrderRecord(Base):
    """买家订单主表（orders）—— 一笔订单一行，平台无关。

    ★ 幂等键 `(shop_id, platform, external_order_id)`：
      同一家店同一平台的同一笔订单只能有一行。重复拉取 => UPDATE 而不是 INSERT，
      否则「同步任务多跑一次」就会换来一堆无法解释的重复订单。
    """

    __tablename__ = "orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_orders_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "platform", "external_order_id", name="uq_orders_scope"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # ord-<platform>-<external_id>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # 平台标识（amazon / shopee / temu / csv_import ...）—— 多平台共存的关键
    platform: Mapped[str] = mapped_column(String(32), default="amazon", index=True)
    marketplace: Mapped[str] = mapped_column(String(16), default="US")
    external_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # 买家（★ 只存最小必要 + 脱敏展示名；不存邮箱/电话/完整收货地址 —— PII）
    buyer_id: Mapped[str] = mapped_column(String(64), default="")
    buyer_name: Mapped[str] = mapped_column(String(64), default="")

    # 状态与履约
    order_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    fulfillment_channel: Mapped[str] = mapped_column(String(16), default="FBA")

    # 收货地只到国家/州/市一级（不要具体门牌）
    ship_country: Mapped[str] = mapped_column(String(16), default="")
    ship_state: Mapped[str] = mapped_column(String(64), default="")
    ship_city: Mapped[str] = mapped_column(String(64), default="")

    currency: Mapped[str] = mapped_column(String(8), default="USD")
    order_total: Mapped[float] = mapped_column(Float, default=0)

    # ---- 时间轴（原始事实）----
    purchase_at: Mapped[str] = mapped_column(String(64), default="", index=True)
    promised_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    shipped_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivered_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ---- 派生态（写入时算好，见文件头）----
    transit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    delay_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    source: Mapped[str] = mapped_column(String(32), default=SOURCE_PLATFORM_API)
    fetched_at: Mapped[str] = mapped_column(String(64), default="")
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 2. 订单明细

class OrderItemRecord(Base):
    """订单明细（order_items）—— 一笔订单买了哪几个 SKU。"""

    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_order_items_shop_id_stores_store",
        ),
        UniqueConstraint("order_id", "external_order_item_id", name="uq_order_items_scope"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # itm-<order_id>-<idx>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    # 指向自家 orders —— 与平台订单号规则解耦
    order_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("orders.id", ondelete="CASCADE", name="fk_order_items_order_id_orders"),
        default="", index=True,
    )
    external_order_item_id: Mapped[str] = mapped_column(String(64), default="")

    # ★ 平台侧标识，故意不用外键指向 skus（见文件头）
    sku: Mapped[str] = mapped_column(String(64), default="", index=True)
    asin: Mapped[str] = mapped_column(String(32), default="", index=True)
    item_title: Mapped[str] = mapped_column(String(500), default="")
    image: Mapped[str] = mapped_column(Text, default="")

    quantity: Mapped[int] = mapped_column(Integer, default=1)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    item_total: Mapped[float] = mapped_column(Float, default=0)

    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


# ============================================================ 3. 物流轨迹

class ShipmentRecord(Base):
    """物流轨迹（shipments）—— 一笔订单一条物流记录 + events 时间线。

    ★ `transit_days` / `delay_days` 是**写入时**算好的：
      「是不是迟了」必须是能进 WHERE 条件的数字，不能交给调用方现场算。
    ★ `events` 是整条扫描轨迹（JSON），访问模式是「取整条」。
    """

    __tablename__ = "shipments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_shipments_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "order_id", name="uq_shipments_scope"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # shp-<order_id>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    order_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("orders.id", ondelete="CASCADE", name="fk_shipments_order_id_orders"),
        default="", index=True,
    )
    external_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    platform: Mapped[str] = mapped_column(String(32), default="amazon")

    carrier: Mapped[str] = mapped_column(String(64), default="")
    tracking_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    ship_status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)

    shipped_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    promised_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivered_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ---- 派生态 ----
    transit_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    delay_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    is_delivered: Mapped[bool] = mapped_column(Boolean, default=False)

    last_event_at: Mapped[str] = mapped_column(String(64), default="")
    last_location: Mapped[str] = mapped_column(String(160), default="")
    last_event_text: Mapped[str] = mapped_column(Text, default="")

    # [{at, status, location, description}] —— 整条轨迹原样存档
    events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    source: Mapped[str] = mapped_column(String(32), default=SOURCE_PLATFORM_API)
    fetched_at: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 4. 买家评论

class CustomerReviewRecord(Base):
    """买家评论 / 差评（customer_reviews）。

    ★★ 表名为什么不是 `reviews`：见文件头 —— `review_reports` 是复盘归档，
      叫 `reviews` 会让人以为差评已经有了（**命名陷阱**，本项目真实发生过）。

    ★ 幂等键 `(shop_id, platform, external_review_id)`：
      同一份 CSV 导入两次不应产生两行。
    """

    __tablename__ = "customer_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_customer_reviews_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "platform", "external_review_id", name="uq_customer_reviews_scope"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # crev-<platform>-<external_id>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    platform: Mapped[str] = mapped_column(String(32), default="amazon")
    external_review_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    marketplace: Mapped[str] = mapped_column(String(16), default="US")

    # 关联自家订单（可为 None —— 评论未必能反查到订单）
    order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    sku: Mapped[str] = mapped_column(String(64), default="", index=True)
    asin: Mapped[str] = mapped_column(String(32), default="", index=True)
    product_title: Mapped[str] = mapped_column(String(500), default="")

    rating: Mapped[int] = mapped_column(Integer, default=0, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    review_at: Mapped[str] = mapped_column(String(64), default="", index=True)

    verified_purchase: Mapped[bool] = mapped_column(Boolean, default=False)
    helpful_votes: Mapped[int] = mapped_column(Integer, default=0)
    images: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # ★ 买家名一律存脱敏后的形态（平台原名不落库）
    buyer_name: Mapped[str] = mapped_column(String(64), default="")

    # new -> triaged（已归因）-> replied（已回复）/ closed（已结案）
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)

    source: Mapped[str] = mapped_column(String(32), default=SOURCE_PLATFORM_API)
    fetched_at: Mapped[str] = mapped_column(String(64), default="")
    raw: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 5. 归因打标

class ReviewAttributionRecord(Base):
    """差评归因（review_attributions）—— 这条差评**为什么**发生。

    ★ `causes` 是多值（一条差评常常同时是「迟到 + 压坏」），`primary_cause`
      是排序后的第一责任因 —— 「改进包装能降多少投诉」这类统计按 primary 算。
    ★ `evidence` 必须能指到**具体的一行证据**（订单号 / 运单 / 承诺日期）；
      没有证据的归因等于一句读后感。记忆里 `cs-refund-playbook` 要求
      「引用订单/物流证据」却拿不到任何取数工具，缺的就是这一类表。
    """

    __tablename__ = "review_attributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_review_attributions_shop_id_stores_store",
        ),
        UniqueConstraint("review_id", name="uq_review_attributions_review"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # attr-<review_id>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    review_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sku: Mapped[str] = mapped_column(String(64), default="", index=True)
    rating: Mapped[int] = mapped_column(Integer, default=0)

    primary_cause: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    causes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)

    # [{kind: order|shipment|review, ref: <id>, fact: <一句话>}]
    evidence: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # rule（规则命中）/ llm（模型判断）/ manual（人工指定）
    method: Mapped[str] = mapped_column(String(16), default="rule")
    rule_version: Mapped[str] = mapped_column(String(32), default="v1")
    attributed_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 6. 处置与补偿

class ReviewDispositionRecord(Base):
    """差评处置（review_dispositions）—— 归因之后**做了什么**。

    ★ 为什么与归因分表：归因可以反复重算（换个规则再来一遍），
      处置是**已经发生的事实**（券码已生成 / 平台回执已登记）。混一张表
      会让「重算归因」误伤「已核准 / 已执行记录」。
    ★ `status`：proposed -> approved -> issued -> executed。HITL 审批卡消费的是
      approved 这一步；未 approved 的处置**不允许**出现在发给买家的回复里。
        · `issued`  ＝ **本地核准**（券码已生成、给买家的回复可以对外）
                      ⇒ **平台侧还没动**；
        · `executed` ＝ 平台上真的执行完了，且有回执（见下方五列）。
    """

    __tablename__ = "review_dispositions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_review_dispositions_shop_id_stores_store",
        ),
        UniqueConstraint("review_id", name="uq_review_dispositions_review"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # disp-<review_id>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    review_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 处置通道（可多选）：reply / coupon / reship / refund / escalate
    channels: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # {"amount": 8.0, "currency": "USD", "percent": null, "reship": true}
    compensation: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    coupon_code: Mapped[str] = mapped_column(String(64), default="")

    reply_draft_en: Mapped[str] = mapped_column(Text, default="")
    reply_draft_zh: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    issued_at: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    # ---- 平台执行回执（第 304 轮 P0·A 档） ----
    #
    # ★ 为什么要有这五列：`issue_disposition` 只做**本地核准**（生成券码、把券码
    #   写进回复草稿），它**不调用任何平台接口** —— 本模块零出站 HTTP，SP-API /
    #   Shopee 适配层清一色是只读的 `fetch_*`。于是「已发放」在本地只等于
    #   「已核准 · 待平台执行」，而库里此前**没有任何字段**能回答「平台上做没做」
    #   ⇒ 界面写「已发放 / 退回部分或全部货款」是**字面为真、暗示为假**。
    #
    # ★ 五列一律空串起步：`""` 的语义是「还没登记」，**不是**「平台已执行」。
    #   用 0 / false / "-" 当默认值 ⇒ 空回执会伪装成已回执（本仓：失败必须能归因）。
    execution_mode: Mapped[str] = mapped_column(String(16), default="")
    platform_ref: Mapped[str] = mapped_column(String(128), default="")
    executed_by: Mapped[str] = mapped_column(String(64), default="")
    executed_at: Mapped[str] = mapped_column(String(64), default="")
    receipt_note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 7. 补偿规则

class CompensationRuleRecord(Base):
    """补偿规则（compensation_rules）—— 什么情况赔多少，**可配置**。

    ★ 为什么要有这张表：此前「不超授权」「酌情补偿」这类话在数据层**没有落地物**，
      Agent 每次现场发挥 => 同样的情况可能拿到两种答复，且无从审计。
      落成规则后，「为什么赔 8 块」能指到**具体一行**。
    ★ `budget_cap` 是硬上限：命中规则但金额超限 => **显式报错**，
      不做「悄悄按上限赔」的静默降级（本仓对静默降级的一贯立场）。
    """

    __tablename__ = "compensation_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_compensation_rules_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "code", name="uq_compensation_rules_scope"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # crule-<shop>-<code>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    code: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(160), default="")

    # 命中哪个归因 cause（一个 cause 可有多条规则，按 priority 取第一条）
    cause: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)

    # {"max_rating":2, "min_delay_days":3, "verified_purchase":true}
    conditions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {"type":"coupon","amount":8.0,"currency":"USD","reship":true,"refund_percent":null}
    action: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 单笔硬上限（<= 0 表示未设置上限 —— 判据见 service.apply_compensation_rule）
    budget_cap: Mapped[float] = mapped_column(Float, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


# ============================================================ 8. SKU 健康分

class SkuHealthScoreRecord(Base):
    """SKU 健康分（sku_health_scores）—— 站在**买家反馈**维度的健康度。

    ★ 与 `ad_analysis` 里广告活动的 `health_score` 是两个东西：那是「广告花钱效率」，
      这是「这个 SKU 买家怎么说」。同名不同义最容易引发误并，故表名写全。
    ★ `health_score` / `dimensions` / `delta` 都是**算本期时一次性写定**的，
      查询面只做「取最近一期」 —— 不让上层在不同场合现算同一个分数。
    """

    __tablename__ = "sku_health_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"], ["stores_store.id"], ondelete="RESTRICT",
            name="fk_sku_health_scores_shop_id_stores_store",
        ),
        UniqueConstraint("shop_id", "sku", "period_days", "period_end", name="uq_sku_health_scope"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)  # hlt-<sku>-<period_end>
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    sku: Mapped[str] = mapped_column(String(64), default="", index=True)
    asin: Mapped[str] = mapped_column(String(32), default="", index=True)
    product_title: Mapped[str] = mapped_column(String(500), default="")

    period_days: Mapped[int] = mapped_column(Integer, default=30)
    # ★ 周期**末日**必须进幂等键：只看 period_days，第 2 期会把第 1 期覆盖掉
    #   （`review_reports` 的 `uq_review_reports_scope` 踩过同一个坑）。
    period_end: Mapped[str] = mapped_column(String(32), default="")

    review_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_rate: Mapped[float] = mapped_column(Float, default=0)
    avg_rating: Mapped[float] = mapped_column(Float, default=0)
    delayed_orders: Mapped[int] = mapped_column(Integer, default=0)

    # {"logistics_delay": n, "packaging_failure": n, ...} —— 各归因维度计数
    cause_counts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # {"rating": 82, "logistics": 45, "packaging": 60} —— 各维度 0~100 分
    dimensions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    health_score: Mapped[float] = mapped_column(Float, default=0, index=True)
    previous_score: Mapped[float] = mapped_column(Float, default=0)
    delta: Mapped[float] = mapped_column(Float, default=0)
    top_cause: Mapped[str] = mapped_column(String(32), default="unknown")

    method: Mapped[str] = mapped_column(String(16), default="rule")
    computed_at: Mapped[str] = mapped_column(String(64), default=_now)


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# `shop_id` 指向 `stores_store.id`，`order_id` 指向 `orders.id`。
# 后者在本文件里定义，天然自洽；**前者不是** —— 若不在 import 期把
# `stores_store` 带进 metadata，症状不是 import 报错，而是某一次 flush 的
# 拓扑排序里抛 NoReferencedTableError，且报错指向外键本身（像「外键写错了」）。
#   同类修复见 core/stores/models.py、modules/customer_service/db_model.py 末尾；
#   门禁见 tests/test_schema_parity.py。
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store

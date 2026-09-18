"""
店铺数据模型 (Phase 10)

支持多平台（Amazon / Shopee）的店铺管理：
- Store: 店铺基本信息 + 平台关联
- FeeTemplate: 费率模板配置
- DiscountTemplate: 折扣规则模板

设计原则：
- 一个 Tenant 可以有多个 Store
- 每个 Store 绑定一个 PlatformType 和 FeeTemplate
- 数据按店铺隔离存储
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ====== 枚举 ======

class StoreStatus(str, Enum):
    """店铺状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class ConnectionStatus(str, Enum):
    """API 连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    EXPIRED = "expired"  # Token 过期
    ERROR = "error"      # 连接错误


class SyncStatus(str, Enum):
    """数据同步状态"""
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"


# ====== 核心模型 ======

class Store(BaseModel):
    """
    店铺模型

    每个店铺代表一个电商平台的实际店铺（如 Amazon US Store、Shopee Malaysia）。
    通过 fee_template_id 关联到费率模板，实现动态利润计算。
    """
    id: str = Field(..., description="店铺唯一标识")
    tenant_id: str = Field(..., description="所属租户 ID")
    owner_id: Optional[str] = Field(
        None,
        description="店铺创建者用户 ID（users.id）—— 审计/展示用，**不再**参与授权判定",
    )
    # ★★★ P1-c（2026-09-16）：账户归属 —— 归属判定的**唯一**依据。
    #
    #   收拢前用的是 `owner_id`（「一店一人」模型）⇒ 团队共享
    #   （同一家店两个人都要能进）根本表达不出来。
    #   account_id 指向 `accounts.id`：多人通过 account_members 共享
    #   同一账户名下的全部店铺。判定实现见 core/auth/accounts.py。
    #
    #   ★ 2026-09-17（A 档）：`StoreCreate` 现可**显式指定** `account_id`
    #      （把店建到自己名下的团队账户，而不是默认的个人账户）。
    #      这不是"客户端随便填"：建店端点会对目标账户做 `store.write` 能力门，
    #      填一个自己无权的账户会 403，而不是静默挂上去。
    #      改造前完全没有这个入口 ⇒ 用户建的第二家店只能落回个人账户，
    #      「新建账户」因此是个没有闭环的空壳。
    account_id: Optional[str] = Field(
        None, description="所属账户 ID（accounts.id）—— 归属判定真源"
    )

    # 基本信息
    name: str = Field(..., description="店铺名称")
    platform: str = Field(..., description="平台类型: amazon_us, amazon_uk, shopee_my, shopee_tw 等")
    marketplace_id: Optional[str] = Field(None, description="市场/站点 ID")
    region_code: str = Field(default="", description="地区代码: US, MY, TW 等")
    currency: str = Field(default="USD", description="默认货币")

    # 费率关联
    fee_template_id: Optional[str] = Field(None, description="关联的费率模板 ID")
    discount_template_id: str = Field(default="default", description="折扣规则模板 ID")

    # 状态
    status: StoreStatus = Field(default=StoreStatus.ACTIVE)
    connection_status: ConnectionStatus = Field(default=ConnectionStatus.DISCONNECTED)

    # 同步信息
    sync_status: SyncStatus = Field(default=SyncStatus.IDLE)
    last_sync_at: Optional[datetime] = Field(None, description="最后同步时间")

    # 凭证信息（不返回给前端明文）
    has_credentials: bool = Field(default=False, description="是否已配置 API 凭证")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
        from_attributes = True

    @property
    def platform_family(self) -> str:
        """返回平台家族: amazon | shopee | tiktok | shopify"""
        if self.platform.startswith("amazon"):
            return "amazon"
        elif self.platform.startswith("shopee"):
            return "shopee"
        elif self.platform.startswith("tiktok"):
            return "tiktok"
        elif self.platform.startswith("shopify"):
            return "shopify"
        return "unknown"

    @property
    def is_active(self) -> bool:
        return self.status == StoreStatus.ACTIVE

    @property
    def is_connected(self) -> bool:
        return self.connection_status == ConnectionStatus.CONNECTED


class StoreCreate(BaseModel):
    """创建店铺请求"""
    name: str = Field(..., min_length=1, max_length=100)
    platform: str = Field(..., description="如: amazon_us, shopee_my")
    marketplace_id: Optional[str] = None
    # 两个「可自动推断」字段的默认值都必须是 falsy：
    # create_store 用的是 `data.X or 推断值`，非空默认值会让 `or` 永远短路。
    # region_code 默认 "" 一直是对的；currency 曾误设默认 "USD"，
    # 导致 `get_currency_for_marketplace()` 形同虚设（2026-09-12 修）。
    region_code: str = ""
    currency: Optional[str] = Field(None, description="默认币种，不传则按 platform 推断（shopee_my → MYR）")
    fee_template_id: Optional[str] = None
    discount_template_id: str = "default"

    # ★ 2026-09-17（A 档）：把店建到**指定的**容器下（团队协作）。
    #   不传（默认 None）→ 建到自己的**默认容器**（`ensure_default_account`），
    #   即改造前的唯一行为。
    #   ★ 传了就必须过目标容器的 `store.write` 能力门（见 create_store）——
    #     否则任何登录用户都能把店挂进别人的团队。
    account_id: Optional[str] = Field(
        None, description="目标容器 ID（accounts.id）；不传=建到自己的默认容器"
    )


class StoreUpdate(BaseModel):
    """更新店铺请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[StoreStatus] = None
    fee_template_id: Optional[str] = None
    discount_template_id: Optional[str] = None


class StoreTransfer(BaseModel):
    """店铺转移请求：把店铺改挂到另一个账户（团队）下。

    ★ 为什么不做成 `StoreUpdate.account_id`：
      改名 / 改状态 / 改费率随时可做，而**改归属**是权限敏感动作 ——
      它同时需要「对原账户有写权限」与「对目标账户有写权限」两道门。
      混进通用更新里，能力门很容易退化成只查其一，而"少查的那一道"
      **不会有任何报错**，只会安静地放行一种越权。
      独立端点让两道门各自有明确的位置（见 `transfer_store`）。
    """

    account_id: str = Field(..., description="目标账户 ID（accounts.id）")


class StoreWithCredentials(Store):
    """包含凭证信息的店铺模型（仅内部使用）"""
    credentials: Optional[Dict[str, Any]] = Field(None, description="API 凭证（加密存储）")


# ====== 费率模板模型 ======

class FeeTemplate(BaseModel):
    """费率模板（可自定义覆盖默认值）"""
    id: str = Field(..., description="模板 ID")
    name: str = Field(..., description="模板名称")
    platform_type: str = Field(..., description="amazon | shopee")
    is_default: bool = Field(default=False, description="是否为系统默认模板")

    # Amazon 费率字段
    referral_fee_pct: Optional[float] = Field(None)
    fba_fulfillment_fee: Optional[float] = Field(None)
    storage_fee_monthly: Optional[float] = Field(None)
    closing_fee: Optional[float] = Field(None)
    vat_rate: Optional[float] = Field(None)
    size_tier: Optional[str] = Field(None)

    # Shopee 费率字段
    commission_pct: Optional[float] = Field(None)
    transaction_fee: Optional[float] = Field(None)
    growth_fee_pct: Optional[float] = Field(None)
    infrastructure_fee: Optional[float] = Field(None)
    shopee_vat_rate: Optional[float] = Field(None, alias="vat_rate")  # 避免与 Amazon 的冲突
    withdrawal_fee_rate: Optional[float] = Field(None)
    logistics_cost: Optional[float] = Field(None)

    created_by: Optional[str] = Field(None, description="创建者 ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FeeTemplateCreate(BaseModel):
    """创建费率模板请求"""
    name: str
    platform_type: str  # amazon | shopee
    is_default: bool = False
    # 所有费用字段可选，None 表示使用系统默认值
    referral_fee_pct: Optional[float] = None
    commission_pct: Optional[float] = None
    transaction_fee: Optional[float] = None
    growth_fee_pct: Optional[float] = None
    infrastructure_fee: Optional[float] = None
    vat_rate: Optional[float] = None
    withdrawal_fee_rate: Optional[float] = None
    logistics_cost: Optional[float] = None
    fba_fulfillment_fee: Optional[float] = None
    storage_fee_monthly: Optional[float] = None


class DiscountTemplate(BaseModel):
    """折扣规则模板"""
    id: str
    name: str
    coupon_discount_pct: float = 10.0
    flash_sale_discount_pct: float = 45.0
    bundle_discount_pct: float = 0.0
    description: str = ""


# ====== 响应模型 ======

class StoreListResponse(BaseModel):
    """店铺列表响应"""
    stores: List[Store]
    total: int


class StoreDetailResponse(Store):
    """店铺详情响应（含关联的费率模板摘要）"""
    fee_template_summary: Optional[Dict[str, Any]] = Field(None, description="当前使用的费率模板摘要")
    discount_template_summary: Optional[Dict[str, Any]] = Field(None, description="当前使用的折扣规则摘要")


class ProfitCalculationContext(BaseModel):
    """利润计算的上下文（由后端中间件构建）"""
    store_id: str
    platform: str           # "amazon" or "shopee"
    currency: str
    region_code: str
    fee_config: Dict[str, Any]   # 序列化后的费率配置
    discount_config: Dict[str, Any]  # 序列化后的折扣配置

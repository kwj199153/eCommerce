"""
用户与订阅数据模型

定义 User、SubscriptionPlan、Shop 等核心业务实体。
使用 SQLAlchemy 2.0 异步 ORM。
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Boolean, DateTime, Text, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

# 统一到 core.database.Base（alembic autogenerate 才会看到所有表）
from core.database import Base


# ====== 枚举类型 ======

class UserRole(str, enum.Enum):
    """用户角色"""
    ADMIN = "admin"
    USER = "user"


class PlanType(str, enum.Enum):
    """套餐类型"""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ShopPlatform(str, enum.Enum):
    """店铺平台"""
    AMAZON_US = "amazon_us"
    AMAZON_UK = "amazon_uk"
    TIKTOK = "tiktok"
    SHOPIFY = "shopify"


# ====== 用户模型 ======

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # 邮箱验证

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    shops: Mapped[List["Shop"]] = relationship("Shop", back_populates="owner", lazy="selectin")
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="user", uselist=False, lazy="selectin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


# ====== 套餐计划 ======

class SubscriptionPlan(Base):
    """订阅套餐表（静态数据）"""
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # free / pro / enterprise
    display_name: Mapped[str] = mapped_column(String(100))  # 免费版 / 专业版 / 企业版
    price_monthly: Mapped[float] = mapped_column(default=0)  # 月费（元）
    api_calls_limit: Mapped[int] = mapped_column(default=100)  # API 调用限制/月
    agent_chat_limit: Mapped[int] = mapped_column(default=50)  # Agent 对话次数/月
    max_shops: Mapped[int] = mapped_column(default=3)  # 最大店铺数
    max_users: Mapped[int] = mapped_column(default=1)  # 最大用户数
    features: Mapped[Optional[str]] = mapped_column(Text)  # JSON 格式的功能列表

    def __repr__(self) -> str:
        return f"<SubscriptionPlan(name={self.name}, display_name={self.display_name})>"


# ====== 用户订阅 ======

class Subscription(Base):
    """用户订阅记录表"""
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("subscription_plans.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="active")  # active / cancelled / expired / past_due
    current_period_start: Mapped[datetime] = mapped_column(DateTime)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 用量追踪
    api_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    agent_chats_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    plan: Mapped["SubscriptionPlan"] = relationship("SubscriptionPlan")

    @property
    def is_active(self) -> bool:
        return self.status == "active" and (
            self.current_period_end is None or self.current_period_end > datetime.utcnow()
        )

    @property
    def remaining_api_calls(self) -> int:
        return max(0, self.plan.api_calls_limit - self.api_calls_used)

    @property
    def remaining_agent_chats(self) -> int:
        return max(0, self.plan.agent_chat_limit - self.agent_chats_used)

    def __repr__(self) -> str:
        return f"<Subscription(user_id={self.user_id}, plan_id={self.plan_id}, status={self.status})>"


# ====== 店铺（租户）=====

class Shop(Base):
    """店铺表（多租户核心）"""
    __tablename__ = "shops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[ShopPlatform] = mapped_column(SAEnum(ShopPlatform), nullable=False)

    # 平台凭证（加密存储）
    seller_id: Mapped[Optional[str]] = mapped_column(String(255))  # Amazon Seller ID
    marketplace_id: Mapped[Optional[str]] = mapped_column(String(20))  # 如 ATVPDKIKX0DER
    api_credentials: Mapped[Optional[str]] = mapped_column(Text)  # 加密的 JSON 凭证

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否已连接平台 API

    # 同步状态
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="idle")  # idle / syncing / error

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    owner: Mapped["User"] = relationship("User", back_populates="shops")

    def __repr__(self) -> str:
        return f"<Shop(id={self.id}, name={self.name}, platform={self.platform})>"

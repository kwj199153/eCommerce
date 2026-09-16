"""
订阅与计费领域模型

★ 为什么住在 modules/billing 而不是 core：
    Subscription / Invoice 只被计费域自身消费（billing 路由 + secretary 的
    订阅工具），属于**业务域实体**；而 User 是全系统基础实体，
    已移到 core/identity/models.py。两者原先混在同一个 models.py 里，
    导致「基础域」和「业务域」无法分层。

    本模块的 relationship 通过**类名字符串**引用 core/identity 的 User
    （SQLAlchemy 延迟解析），不 import 对端类，保持依赖方向单向。
"""

from datetime import datetime
from typing import Optional

import enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 统一到 core.database.Base（alembic autogenerate 才会看到所有表）
from core.database import Base


# ====== 套餐类型枚举 ======

class PlanType(str, enum.Enum):
    """套餐类型"""
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


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

    status: Mapped[str] = mapped_column(String(20), default="active")  # active / cancelled / expired / past_due / trialing
    # 是否「周期结束后取消」（cancel_at_period_end）：true 表示用户已发起取消，
    # 但当前周期内仍可用，到期后自动转为 cancelled。
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    # ★ P1-4 补充（2026-09-15）：计费周期必须落库。
    #   修复前周期只存在于 change_plan 的局部变量里，订阅行上查不到，
    #   于是「用户点了两次升级」无法判断第二次是不是同一周期的重复提交，
    #   只能按金额/天数反推（monthly≈30 天、yearly≈365 天）——这种推断在
    #   促销周期、试用期上必然出错。落库后 is_duplicate_submission() 才能
    #   精确判等，做到「同套餐同周期重复提交不重复扣款」。
    billing_cycle: Mapped[str] = mapped_column(String(10), default="monthly", server_default="monthly")
    current_period_start: Mapped[datetime] = mapped_column(DateTime)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 用量追踪
    api_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    agent_chats_used: Mapped[int] = mapped_column(Integer, default=0)

    # LLM 消耗计量（由 core/metering/llm_meter.py 按调用累积落库）
    llm_tokens_used: Mapped[int] = mapped_column(Integer, default=0, server_default='0')          # 累计 token 数
    llm_cost_used: Mapped[float] = mapped_column(Float, default=0.0, server_default='0')          # 累计成本（元）

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="subscription")
    # plan 必须是 eager load：计费逻辑（check_quota/record_usage）在异步上下文
    # 中访问 subscription.plan.xxx，若为默认懒加载会抛 MissingGreenlet。
    plan: Mapped["SubscriptionPlan"] = relationship("SubscriptionPlan", lazy="selectin")

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


# ====== 账单（发票）======

class Invoice(Base):
    """账单表（订阅付费记录）"""
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 账单号 INV-xxxx
    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)  # 金额（元，正=收款，负=退款）
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # paid / pending / failed / refunded
    description: Mapped[Optional[str]] = mapped_column(String(255))  # 描述（如「专业版年付」）
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # ★ P1-4 补充（2026-09-15）：账单幂等键 + 唯一约束。
    #   实测（09-支付链路-实测证据.txt 第 [8] 段）：连续两次 POST /billing/subscribe
    #   会产生 2 张账单；接真实网关后 = 真的扣两次钱。
    #   服务端业务守卫（modules.billing.pricing.is_duplicate_submission）能拦住
    #   绝大多数情况，但**拦不住并发双击**——两个请求都读到「尚未订阅」就会
    #   各建一张单。唯一约束是最后一道闸，它不依赖任何应用层判断。
    #   可为 NULL（历史数据、人工补录账单不走订阅链路），PG 允许多个 NULL。
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Invoice(number={self.number}, amount={self.amount}, status={self.status})>"


# ====== 支付方式 ======

class PaymentMethod(Base):
    """支付方式表（信用卡/支付宝/微信）"""
    __tablename__ = "payment_methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # card / alipay / wechat
    brand: Mapped[str] = mapped_column(String(32), default="")  # visa / mastercard / unionpay ...
    last4: Mapped[str] = mapped_column(String(4), default="")  # 卡号后四位
    exp_month: Mapped[int] = mapped_column(Integer, default=1)
    exp_year: Mapped[int] = mapped_column(Integer, default=2026)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<PaymentMethod(type={self.type}, brand={self.brand}, last4={self.last4})>"

# ====== 跨模块模型注册（非业务依赖）======
# 见 core/identity/models.py 末尾同名段落。Subscription.user 引用 User，
# 两侧必须同处一个 Base.registry；此处只做注册，不访问对端属性。
import core.identity.models as _identity_models  # noqa: E402,F401

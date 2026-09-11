"""
支付网关抽象层

背景：
    billing_router.change_plan 原本把「模拟支付成功」硬编码在端点内——
    直接生成一张 paid 账单 + 更新订阅，真实支付无法插拔。

    本模块定义统一支付网关协议与工厂，让计费端点只面向协议编程，
    接入 Stripe / 支付宝 / 微信时新增一个 Gateway 实现并改一行配置即可，
    无需改动 change_plan 的计费流程。

设计：
    - `PaymentGateway`：Protocol，声明 charge() 接口与返回结构
    - `MockGateway`：默认实现，模拟「支付成功」闭环（保留原 _make_invoice 逻辑）
    - `ChargeResult` / `ChargeIntent`：网关与调用方之间的统一数据结构
    - `get_gateway()`：按 config.payment_gateway 返回对应实现（工厂）

用法：
    from core.billing.payment_gateway import get_gateway

    gateway = get_gateway()
    result = await gateway.charge(
        user_id=..., plan=..., billing_cycle="yearly",
        amount=..., currency="CNY", description="专业版年付",
    )
    if result.success:
        db.add(result.invoice)          # 落账单
    else:
        raise HTTPException(402, result.error)

    前端若需拉起第三方支付（如 Stripe PaymentIntent），可透传 result.client_secret。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from core.config import config
from modules.user_subscription.models import Invoice, SubscriptionPlan


# ====== 统一数据结构 ======

@dataclass
class ChargeIntent:
    """一次扣款请求的输入参数（网关无关）"""

    user_id: str
    amount: float                       # 金额（元）
    currency: str = "CNY"
    description: str = ""
    billing_cycle: str = "monthly"      # monthly / yearly
    plan: Optional[SubscriptionPlan] = None   # 关联套餐（生成账单描述用）


@dataclass
class ChargeResult:
    """一次扣款的结果（网关无关）"""

    success: bool
    invoice: Optional[Invoice] = None           # 成功时返回待落库账单
    client_secret: str = ""                     # 第三方支付意图（Stripe 等）；mock 为空串
    transaction_id: str = ""                    # 网关侧交易号
    error: str = ""                             # 失败原因


# ====== 网关协议 ======

@runtime_checkable
class PaymentGateway(Protocol):
    """支付网关协议：计费端点只面向此接口编程"""

    name: str

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        """发起一次扣款，返回统一结果"""
        ...


# ====== Mock 实现 ======

class MockGateway:
    """
    模拟支付网关（默认）

    始终返回「支付成功」，生成一张 paid 账单。
    用于本地开发 / 演示环境；接入真实网关前，生产环境应禁用此实现。
    """

    name = "mock"

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        now = datetime.utcnow()
        invoice = Invoice(
            id=str(uuid.uuid4()),
            user_id=intent.user_id,
            number=f"INV-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
            amount=round(intent.amount, 2),
            currency=intent.currency or "CNY",
            status="paid",
            description=intent.description or "",
            issued_at=now,
            paid_at=now,
            pdf_url=None,
        )
        return ChargeResult(
            success=True,
            invoice=invoice,
            client_secret="",
            transaction_id=f"mock-{uuid.uuid4().hex}",
            error="",
        )


# ====== 网关注册表 & 工厂 ======

# 已实现网关注册表：name -> 工厂函数
# 接入真实网关时在此登记，并新增对应配置项分支。
_GATEWAYS: dict = {
    "mock": MockGateway,
}


def get_gateway(name: Optional[str] = None) -> PaymentGateway:
    """
    返回当前配置的支付网关实例。

    Args:
        name: 网关名；缺省读取 config.payment_gateway

    Raises:
        ValueError: 配置了未登记的网关
    """
    gw_name = (name or config.payment_gateway or "mock").strip().lower()
    cls = _GATEWAYS.get(gw_name)
    if cls is None:
        raise ValueError(
            f"未登记的支付网关 '{gw_name}'，可用：{', '.join(_GATEWAYS.keys())}"
        )
    return cls()

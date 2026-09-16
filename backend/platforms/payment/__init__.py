"""
支付网关适配器

与 platforms/ 下其它适配器同构：都是「对接外部系统、对内提供统一接口 + 工厂」。
业务侧（modules/billing）只面向 PaymentGateway 协议编程，
接入 Stripe / 支付宝 / 微信时新增一个实现并改一行配置即可。

★ 本层**不依赖任何业务 ORM 模型**：入参 ChargeIntent、出参 ChargeResult /
  InvoiceDraft 全是纯数据。落库是调用方的事。

用法：
    from platforms.payment import get_gateway, ChargeIntent, ChargeResult

    gateway = get_gateway()
    result = await gateway.charge(ChargeIntent(user_id=..., amount=...))
"""

from platforms.payment.gateway import (
    ChargeIntent,
    ChargeResult,
    InvoiceDraft,
    MockGateway,
    PaymentGateway,
    UnimplementedGateway,
    get_gateway,
)

__all__ = [
    "PaymentGateway",
    "MockGateway",
    "UnimplementedGateway",
    "ChargeIntent",
    "ChargeResult",
    "InvoiceDraft",
    "get_gateway",
]

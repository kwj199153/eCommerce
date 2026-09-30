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
    PENDING_PAYMENT_TTL_MINUTES,
    SETTLEMENT_ASYNC,
    SETTLEMENT_IMMEDIATE,
    ChargeIntent,
    ChargeResult,
    GatewayConfigError,
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
    "GatewayConfigError",
    "SETTLEMENT_ASYNC",
    "SETTLEMENT_IMMEDIATE",
    "PENDING_PAYMENT_TTL_MINUTES",
    "get_gateway",
]

# ★ `AlipayGateway` / `AlipaySignatureError` **刻意不在这里导出**：
#   它们住在 `platforms/payment/alipay.py`，且该模块 import 本包的 gateway 模块。
#   在这里顶层再 import 一次，等于把那条懒加载打开的环重新接上
#   （见 gateway.py::_load_alipay_gateway 的论证）。
#   需要它们的调用方请直接 `from platforms.payment.alipay import ...`，
#   那条路径本身就会先执行本文件、再加载 alipay，顺序是确定的。

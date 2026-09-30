"""
支付网关抽象层

背景：
    modules/billing/router.py::change_plan 原本把「模拟支付成功」硬编码在端点内——
    直接生成一张 paid 账单 + 更新订阅，真实支付无法插拔。

    本模块定义统一支付网关协议与工厂，让计费端点只面向协议编程，
    接入 Stripe / 支付宝 / 微信时新增一个 Gateway 实现并改一行配置即可，
    无需改动 change_plan 的计费流程。

设计：
    - `PaymentGateway`：Protocol，声明 charge() 接口与返回结构
    - `MockGateway`：默认实现，模拟「支付成功」闭环
    - `ChargeResult` / `ChargeIntent`：网关与调用方之间的统一数据结构
    - `get_gateway()`：按 config.payment_gateway 返回对应实现（工厂）

用法：
    from platforms.payment.gateway import get_gateway

    gateway = get_gateway()
    result = await gateway.charge(ChargeIntent(
        user_id=..., amount=..., currency="CNY", description="专业版年付",
        plan_name="pro", billing_cycle="yearly", idempotency_key="sub:...",
    ))
    if not result.success:
        raise HTTPException(402, result.error)
    if result.invoice is not None:
        # result.invoice 是纯数据 InvoiceDraft，不是 ORM 实体。
        # 落库由调用方决定（见 modules/billing/router.py::_invoice_from_draft）。
        db.add(_invoice_from_draft(result.invoice))   # 零元不开票，见 MockGateway

    前端若需拉起第三方支付（如 Stripe PaymentIntent），可透传 result.client_secret。

★ Mock 与生产的边界（P1-4）
    MockGateway.charge() 的语义是「**无条件**返回支付成功」——没有收单方、
    没有回调、没有对账。它只能出现在开发和演示环境。
    生产环境若仍是 mock，用户在页面上点一下「升级到专业版」就直接变成
    付费用户，平台一分钱收不到。
    为此 `core.config.Settings._enforce_production_safety()` 增加了一条硬校验：
        environment == "production" 且 payment_gateway == "mock" → 拒绝启动。
    ★ 判据：伪造成功的支付 ≠ 支付。「默认安全」意味着默认值必须朝
      「收不到钱就报错」而不是「收不到钱也放行」的方向倒。


===============================================================================
真实网关接入清单（第 1~3 家按此清单接入）
===============================================================================

现状（2026-09-25 更新）：`_GATEWAYS` 登记了 **mock** 与 **alipay**。
支付宝已按下面 6 步完整接入（见 `platforms/payment/alipay.py`）；
stripe / wechat / wechatpay / paypal 仍是占位名 —— 把 PAYMENT_GATEWAY
配成这些名字，`get_gateway()` 会返回 UnimplementedGateway，
在**真正收钱那一步**显式失败并列出整改路径。这是有意的：
静默回落 mock 会让「配了真实网关」和「没配」看起来一样，是最危险的失败模式。

要把下一家网关接上，按下面 6 步做（以 Stripe 为例）：

1) 加依赖
   requirements.txt: `stripe>=11.0`（支付宝用 `alipay-sdk-python`，
   微信支付用 `wechatpayv3`）。★ 不要写成本地 mock 包，CI 里要能装上。

2) 加配置（core/config.py）
   payment_gateway: str                     # 已存在，只需能填 "stripe"
   payment_stripe_secret_key: str = ""      # sk_live_... / sk_test_...
   payment_stripe_webhook_secret: str = ""  # whsec_...（验签用）
   payment_return_url: str = ""             # 支付完成后跳回前端
   ★ 同时在 `_enforce_production_safety()` 里加一条：
     「生产 + gateway==stripe + secret_key 为空 → 拒绝启动」，
     否则会带着空 key 上线，表现为「所有支付都 500」，且日志里是一堆
     authentication_error，排查方向容易被带偏到「用户支付方式有问题」。

3) 实现 Gateway
   class StripeGateway:
       name = "stripe"

       async def charge(self, intent: ChargeIntent) -> ChargeResult:
           # ★ 三件必须做的事：
           #   a. 透传幂等键 → stripe.PaymentIntent.create(..., idempotency_key=intent.idempotency_key)
           #      否则网络重试 / 双击会真的扣两次钱。
           #   b. 金额单位换算：Stripe 用「分」（int），intent.amount 是「元」（float）。
           #      必须 round(amount * 100) 并断言 > 0，浮点直接 int() 会少一分。
           #   c. 不要在这里返回 status="paid" 的账单！
           #      这一步只创建了 PaymentIntent，钱还没到账。
           #      正确做法：建一张 status="pending" 的 Invoice 落库，
           #      真正的 paid 由 webhook 回调改写（见第 4 步）。
           #      ★ 判据：网关返回 success=True 的语义是「受理成功」，
           #        不等于「收款成功」。把两者混为一谈 = 用户没付钱就拿到套餐。

4) webhook 回调（★ 这是真实支付能闭环的关键，mock 完全不需要）
   新增 `modules/billing/webhook_router.py`：
       POST /api/v1/billing/webhook/stripe
           - 用 payment_stripe_webhook_secret 验签（不验签 = 任何人可伪造到账通知）
           - 幂等：按 event.id 去重（Stripe 会重复投递同一个事件）
           - 命中 payment_intent.succeeded → 把 Invoice.status 置 paid、
             paid_at 置当前时间、写入 transaction_id
           - 命中 payment_intent.payment_failed → Invoice.status 置 failed，
             并**不要**给用户开套餐权限
   注册到 main.py 时注意：该路由**必须免鉴权**（调用方是 Stripe 服务器，
   没有我们的 Bearer Token），但必须**强制验签**。免鉴权不免验签，
   这是两个正交的门。
   ★ 同时该路径要加入限流中间件的 exempt 列表，否则 Stripe 重试会被 429。

5) 订阅状态机对齐
   真实支付是异步确认，所以「先开权限、后收到钱」的窗口必须消除：
     当前 change_plan 的顺序是「改订阅 → 扣款 → commit」，
     接真实网关后要改成「建 pending 账单 → commit → 收 webhook → 改订阅为 active」。
   对应地 Subscription.status 需要用到 `past_due` / `trialing`
   （模型已预留这两个取值，无需改表结构）。
   ★ 顺带注意：change_plan 的行锁覆盖「当前用户自己那一行」，事务内还包含
     一次网关调用。mock 是瞬时完成；接真实网关若走**同步 HTTP**，
     持锁时长 ≈ 网关 P99 延迟，同一用户的高频请求会排队等待。
     这也是要改两段式的原因之一（建 pending 账单 → commit 释放锁 → 收 webhook）。

6) 对账
   真实网关必须有日对账任务：拉取昨日结算流水，与 invoices 表按
   transaction_id 比对，差额落告警。没有对账的支付集成等于没集成——
   漏单/重复单只能靠用户投诉发现。

===============================================================================
三项支付网关的差异速查（接入时对着改）
===============================================================================
| 项目       | Stripe              | 支付宝（当面付/APP） | 微信支付 v3        |
|-----------|---------------------|---------------------|-------------------|
| 认证      | Secret Key (Bearer) | RSA2 应用私钥签名    | 商户私钥 + 平台证书 |
| 金额单位  | 分（int）           | 元（str，两位小数）  | 分（int）          |
| 幂等机制  | Idempotency-Key 头  | out_trade_no        | out_trade_no       |
| 回调验签  | whsec_ 签名头       | 支付宝公钥验签       | 平台证书 + AES 解密 |
| 异步确认  | PaymentIntent 事件  | notify_url 异步通知  | notify_url 异步通知 |
| 退款      | Refund API          | alipay.trade.refund | 退款 API（需证书）  |

★ 三者共同点：**都必须有服务端回调 + 验签 + 幂等**。
  任何「前端拿到支付成功就开权限」的实现都是不安全的，
  因为前端的那句话是可以被伪造的。
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from core.config import KNOWN_UNIMPLEMENTED_GATEWAYS, config

# ★ 适配层只依赖 DTO，**不** import 任何业务 ORM 模型。
#   历史问题：本模块曾 `from modules.user_subscription.models import Invoice,
#   SubscriptionPlan`，于是「外部适配层」反向依赖了业务实体 ——
#   要独立部署 webhook 服务 / 换网关时，会被业务模型一起拖走。
#   现在账单以纯数据 InvoiceDraft 返回，由调用方（modules/billing）负责落库。


# ====== 统一数据结构 ======

@dataclass
class ChargeIntent:
    """一次扣款请求的输入参数（网关无关）"""

    user_id: str
    amount: float                       # 金额（元）
    currency: str = "CNY"
    description: str = ""
    billing_cycle: str = "monthly"      # monthly / yearly
    # 关联套餐的**标识**（如 "pro"）。刻意只放字符串而不是 ORM 实体：
    # 适配层不该认识业务模型；给人看的描述文案由调用方拼进 description。
    plan_name: str = ""
    # 幂等键：同一业务动作重试必须带同一个值。
    # ★ 真实网关靠它做服务端去重（Stripe 透传、支付宝/微信作 out_trade_no）；
    #   mock 下只落到 Invoice.idempotency_key 上，由 DB 唯一约束兜底。
    idempotency_key: str = ""


@dataclass
class InvoiceDraft:
    """账单草案（纯数据，**不含** ORM 实体）

    ★ 为什么需要这一层：
      网关属于**外部适配层**，只该产出与框架无关的数据；是否落库、按哪个
      业务模型落库，是调用方（modules/billing）的决定。网关若直接 new 一个
      ORM Invoice，就等于替业务层做了持久化决策，适配层也无法脱离业务模型复用。
      调用方转换见 modules/billing/router.py::_invoice_from_draft()。

    ★ 字段分工（加字段前先想清楚它属于哪一侧，别混）：

      · **网关侧事实**（谁来收款、网关给了什么号、二维码是什么）
        → 由网关填：`payment_channel` / `transaction_id` / `pay_url` / `status`。
        这些值**只有网关知道**，调用方无从推算。

      · **业务侧事实**（这笔钱买的是哪个套餐、几个月）
        → 由调用方填：见 `_invoice_from_draft(..., plan_id=, billing_cycle=)`。
        网关刻意不认识这两个字段 —— `ChargeIntent.plan_name` 只给了个字符串，
        真正的套餐主键是业务概念，让适配层认识它就把适配层绑死在计费域上了。
    """

    user_id: str
    number: str                                  # 账单号 INV-xxxx
    amount: float
    currency: str = "CNY"
    status: str = "paid"                        # paid / pending / failed / refunded / expired
    description: str = ""
    issued_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    pdf_url: Optional[str] = None
    idempotency_key: Optional[str] = None
    id: str = ""                                # 网关预生成的账单 UUID
    # ---- 以下三列为真实支付（异步确认）新增，见 platforms/payment/alipay.py ----
    transaction_id: str = ""                    # 网关侧商户订单号（支付宝 out_trade_no）
    payment_channel: str = ""                   # 实际收款渠道：mock / alipay / ...
    pay_url: str = ""                           # 二维码内容（待用户扫码的地址）


@dataclass
class ChargeResult:
    """一次扣款的结果（网关无关）

    ★★ 区分两个经常被混为一谈的字段（这是本层最容易出人命的地方）：

      `success=True` 的语义是「**这笔单被受理了**」，不是「钱到账了」。
      在同步网关（mock）下两者等价，在异步网关（支付宝当面付）下**不等价**：
      precreate 返回 200 只代表二维码生成了，用户还没扫。

      ⇒ 因此多出一个 `requires_confirmation`：它为 True 时，调用方**必须**
        走两段式（建 pending 账单 → 用户扫码 → webhook 到达才激活订阅）。
        把 success 直接当"已收款"就是「用户没付钱就拿到套餐」，
        也正是本文件顶部接入清单第 3 步用一整段警告的那个坑。
    """

    success: bool
    invoice: Optional[InvoiceDraft] = None      # 成功时返回待落库的账单**草案**；零元或纯授权返回 None
    client_secret: str = ""                     # 第三方支付意图（Stripe 等）；mock 为空串
    transaction_id: str = ""                    # 网关侧交易号
    error: str = ""                             # 失败原因
    # 未产生账单的原因（如「零元无需开票」），便于调用方区分
    # 「扣款成功但没账单」和「压根没扣款」。
    skipped_reason: str = ""
    # ---- 异步真实支付（P0，2026-09-25）新增 ----
    #: 是否为「先受理、后确认」的异步支付。True ⇒ 调用方必须保留 pending 状态，
    #: 等 webhook 到达才开通服务。mock 恒为 False。
    requires_confirmation: bool = False
    #: 待用户扫码/跳转的地址（支付宝 qr_code 原值）。仅 requires_confirmation 时有意义。
    qr_code_url: str = ""


# ====== 结算模式 ======

#: 同步结算：`charge()` 返回时钱已经收到了（mock）。调用方可以在**同一个事务**里
#: 直接把订阅改成 active。
SETTLEMENT_IMMEDIATE = "immediate"

#: 异步结算：`charge()` 返回时只是"受理成功"，真正的到账由 webhook 确认
#: （支付宝当面付 / 微信 Native）。调用方**必须**两段式。
SETTLEMENT_ASYNC = "async"


#: 一笔「待支付」订单的有效窗口（分钟）。**唯一定义处**。
#
# 两个消费方都从这里取，不允许各写一个数字：
#   · `platforms/payment/alipay.py`  → 下单时的 `timeout_express`（支付宝侧超时）；
#   · `modules/billing`（下单复用判定 / 定时回收）→ 判定"这张 pending 单还能不能续用"。
#
# ★ 两侧必须一致，且**业务侧不得短于网关侧**：
#   若我们提前把订单判为过期、又让用户扫了那张还活着的码，
#   就会出现「用户付了钱，我们库里那张单已经是 expired」——
#   钱到了、权限没开，是最难排查的一类事故（支付宝侧一切正常）。
#   取相等值 + 「expired 的单收到回调照样认账」（见 payment_router）双保险。
PENDING_PAYMENT_TTL_MINUTES = 30


# ====== 错误类型 ======

class GatewayConfigError(RuntimeError):
    """真实网关的接入配置不完整（缺凭证 / 缺回调地址）。

    ★ 为什么要与 `NotImplementedError` 分开：
      两者的**整改动作完全不同**，混成一个类型会让运维照着错误的清单去修。
        · NotImplementedError → 「这个网关的代码还没写」→ 开发者的事；
        · GatewayConfigError   → 「代码写了，但这个部署没配钥匙」→ 运维的事。
      调用方的映射也不同：前者 501（Not Implemented），后者 503（Service
      Unavailable，语义是"服务依赖没就绪"）。

    ★ 而且它绝对不能靠"静默返回 success=False"来表达：那样这张单会被记成
      「一次正常的支付失败」进了业务表，而真实原因是环境没配好 ——
      用户看到的是"支付失败请重试"，重试一万次也一样。
    """


# ====== 网关协议 ======

@runtime_checkable
class PaymentGateway(Protocol):
    """支付网关协议：计费端点只面向此接口编程"""

    name: str

    #: 结算模式（见上面的 SETTLEMENT_* 常量）。
    #: ★ 必须由**网关自己声明**，不能让调用方按网关门牌号 if/else 猜 ——
    #:   那样每接一家新网关都要回去改计费端点，正是本模块要消除的耦合。
    settlement_mode: str

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        """发起一次扣款，返回统一结果"""
        ...


# ====== Mock 实现 ======

class MockGateway:
    """
    模拟支付网关（仅限开发 / 演示环境）

    ★ 语义要点（容易踩）：
      `charge()` 是「无条件支付成功」——它不碰任何真实收单方。
      因此生产环境用它 = 用户白拿付费套餐。生产护栏见模块 docstring。

      零元（免费套餐、全额优惠券）时**不开票**并返回 invoice=None：
      修复前 MockGateway 无条件建 Invoice，导致「切到免费版」会凭空多出
      一张 ¥0.00 的 status="paid" 账单（实测证据：
      `09-支付链路-实测证据.txt` 第 [7] 段）。零元账单会污染
      /billing/invoices 列表，也让「本月实收」这类统计失去意义。
      ★ 判据：没有资金流动就不该有资金凭证。
    """

    name = "mock"
    #: 模拟网关是**同步**的：`charge()` 返回时"钱已经收到了"，
    #: 所以调用方可以在同一个事务里直接把订阅改成 active（当前的既有行为）。
    settlement_mode = SETTLEMENT_IMMEDIATE

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        amount = round(float(intent.amount or 0), 2)

        if amount <= 0:
            return ChargeResult(
                success=True,
                invoice=None,
                client_secret="",
                transaction_id="",
                error="",
                skipped_reason="金额为 0，无需支付与开票",
            )

        now = datetime.utcnow()
        invoice = InvoiceDraft(
            id=str(uuid.uuid4()),
            user_id=intent.user_id,
            number=f"INV-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
            amount=amount,
            currency=intent.currency or "CNY",
            status="paid",
            description=intent.description or "",
            issued_at=now,
            paid_at=now,
            pdf_url=None,
            idempotency_key=intent.idempotency_key or None,
            # ★ 渠道落成 "mock" 而不是空串：账单表里必须一眼看得出
            #   「这笔钱是模拟收的」。演示环境的账单混进真实账单列表时，
            #   唯一的区分依据就是这一列 —— 对账时靠人工回看日志是来不及的。
            payment_channel=self.name,
            transaction_id=f"mock-{uuid.uuid4().hex}",
        )
        return ChargeResult(
            success=True,
            invoice=invoice,
            client_secret="",
            transaction_id=invoice.transaction_id,
            error="",
            # mock 恒为同步：不产生"待确认"状态，调用方走原来那条路。
            requires_confirmation=False,
            qr_code_url="",
        )


# ====== 未接入的真实网关（占位） ======

class UnimplementedGateway:
    """
    「配置里写了一个尚未接入的真实网关」时的显式占位。

    为什么要有这个类，而不是让 get_gateway() 直接抛错：
      - 抛错会让**应用启动期**失败，看起来像代码 bug；
      - 静默回落 MockGateway 则是最危险的失败模式——配置里明明写着
        `PAYMENT_GATEWAY=stripe`，实际却在用模拟支付，日志里还有正常的
        「支付成功」，直到财务发现没收到钱。
      所以这里选择第三条路：**启动正常，但每次真正收钱时显式失败并说清原因**。
      ★ 判据：能在启动期拦住就拦住；拦不住时，也要在「产生后果的那一步」
        大声失败，绝不静默降级。

    实现方式：`charge()` 抛 `NotImplementedError`（不是返回 success=False），
    让调用方无法把这笔单当成「一次正常的支付失败」记录进业务表。
    """

    name = "unimplemented"
    #: 取值本身无意义（`charge()` 必抛），但协议要求有 —— 且**不能**随便填
    #: `immediate` 之外的值：假如将来有人在调用 `charge()` 之前读它做分支，
    #: 填 "async" 会让调用方走进"建 pending 账单等回调"那条路，
    #: 而这条路永远不会有人回调 ⇒ 用户钱没付、订阅挂着 pending 烂尾。
    #: 填 immediate 时，调用方必然走到 `charge()`，然后**当场炸在**这里。
    settlement_mode = SETTLEMENT_IMMEDIATE

    def __init__(self, requested: str) -> None:
        self.requested = requested

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        raise NotImplementedError(
            f"支付网关 '{self.requested}' 尚未接入实现。"
            f"请按 platforms/payment/gateway.py 顶部「真实网关接入清单」"
            f"完成 6 步接入后，再把 PAYMENT_GATEWAY 改为 '{self.requested}'。"
        )


# ====== 网关注册表 & 工厂 ======

def _load_alipay_gateway():
    """懒加载支付宝网关。

    ★ 为什么是函数而不是直接写类名：`platforms/payment/alipay.py` 需要
      `from platforms.payment.gateway import ChargeIntent, GatewayConfigError, ...`
      —— 名字定义在**本模块**里。若本模块在顶层 `import alipay`，
      两个模块就形成 import 环：谁先被导入，另一方拿到的都是**半初始化**的
      模块对象，报 `ImportError: cannot import name ...`（而且报错时机取决于
      谁先被 import，测试单跑绿、全量跑红那类最难查的问题）。
      懒加载把环打开：正常路径下 `get_gateway("alipay")` 第一次调用时才 import。
    """
    from platforms.payment.alipay import AlipayGateway

    return AlipayGateway()


# 已实现网关注册表：name -> 工厂（类或返回实例的可调用对象）
# 接入真实网关时在此登记，并新增对应配置项分支（见顶部接入清单第 2、3 步）。
_GATEWAYS: dict = {
    "mock": MockGateway,
    "alipay": _load_alipay_gateway,
}

# 已知但尚未实现的真实网关名。命中时**不报配置错误**，
# 而是进入 UnimplementedGateway，在真正收钱那一步显式失败。
# ★ 复用 core.config 里的同名单：避免「哪些网关算未接入」出现两份清单。
#   （生产环境护栏也读那份，两处判定必须一致。）
_KNOWN_UNIMPLEMENTED = KNOWN_UNIMPLEMENTED_GATEWAYS


def get_gateway(name: Optional[str] = None) -> PaymentGateway:
    """
    返回当前配置的支付网关实例。

    Args:
        name: 网关名；缺省读取 config.payment_gateway

    Returns:
        PaymentGateway 实现。若配置的是「已知但未接入」的真实网关，
        返回 UnimplementedGateway（charge 时才报错，见其 docstring）。

    Raises:
        ValueError: 配置了完全不认识的网关名（拼写错误等）
    """
    gw_name = (name or config.payment_gateway or "mock").strip().lower()

    cls = _GATEWAYS.get(gw_name)
    if cls is not None:
        return cls()

    if gw_name in _KNOWN_UNIMPLEMENTED:
        return UnimplementedGateway(gw_name)

    raise ValueError(
        f"未登记的支付网关 '{gw_name}'，可用：{', '.join(_GATEWAYS.keys())}"
    )

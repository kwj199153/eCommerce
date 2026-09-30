"""支付宝当面付（扫码支付）网关实现 —— 项目内**第一个**真实支付网关

==============================================================================
★ 它解决的是什么问题（先看这一节，否则下面的每个"多余"细节都会看不懂）
==============================================================================
接入前整条订阅链路是 `MockGateway`：用户点「选择此套餐」→ 后端
**无条件**返回支付成功 → 订阅变 active + 落一张 paid 账单。平台一分钱收不到。

本模块把「收钱」这一步真正交给支付宝。核心差别只有一个词：**异步**。

    mock：  charge() 返回 ⇒ 钱已收到 ⇒ 可以立刻开权限
    支付宝：charge() 返回 ⇒ **只是生成了一张二维码** ⇒ 一分钱没收到
            用户扫码付款后才由支付宝回调 `notify_url` 告诉我们

⇒ 因此 `charge()` 返回的是 `requires_confirmation=True` + 一张 status="pending"
  的账单草案，而**不是** paid 账单。把这两件事混起来就是
  「用户没付钱就拿到套餐」——本文件所有"多看一步"的地方都是在守这条线。

==============================================================================
★ 签名：为什么不用 alipay-sdk-python
==============================================================================
支付宝请求签名只要 RSA2（SHA256withRSA），而 `cryptography` 已经因为
`python-jose[cryptography]` 装在环境里。自己实现 sign/verify 约 60 行，
省掉一个 SDK 及其全部传递依赖 —— 而且**少一个黑盒**：出问题时能直接
读到这里每一行在做什么，而不是去翻 SDK 源码。

★ 密钥形态必须宽容（这是易用性，不是"兼容性洁癖"）：
  支付宝开放平台的密钥工具给人复制的通常是**纯 base64**（没有 PEM 头尾），
  而 `.env` 是单行文件、真换行会被截断。所以 `_load_*` 同时接受：
    · 带 PEM 头尾的多行串（本地 yaml / 密钥文件直接粘贴）
    · 单行串里用字面量 `\\n` 转义换行（`.env` 标准做法）
    · 纯 base64（自动补头尾）
  私钥还要同时试 PKCS#8 与 PKCS#1 —— 两种格式在支付宝文档里都出现过，
  而它们的 PEM 头不同（`PRIVATE KEY` / `RSA PRIVATE KEY`），
  只支持一种就等于让一半用户拿到"密钥格式错误"。

==============================================================================
★★★ 三个"必须做"（漏了任何一个都是资金事故）
==============================================================================

① **必须透传幂等键**：`out_trade_no` 由 `intent.idempotency_key` 确定性派生
   （见 `out_trade_no_for`）。理由：网络超时时客户端会重发同一个业务动作，
   若每次都生成新单号，支付宝侧就是**两笔真实订单**，用户可能付两次钱。
   派生式单号让"同一次业务意图"永远映射到同一个支付宝订单，
   支付宝自己会去重；而 `InvoiceDraft.transaction_id` 的唯一约束在我们这一侧
   再加一道闸（两道闸的分工见 modules/billing/models.py 的 Invoice 注释）。

② **金额必须转换且校验**：支付宝用「元（两位小数字符串）」，`intent.amount`
   是 float。必须 `f"{amount:.2f}"` —— 直接 `str(amount)` 会送出 `"2990.0"`
   甚至 `"2.99e+03"`，前者支付宝能容忍、后者直接报参数错误。
   并断言 `amount > 0`：零元单走不到这里（调用方已短路），但**真走到就是 bug**，
   与其把一张 ¥0.00 的待支付单丢给支付宝，不如当场炸掉。

③ **必须验签，且响应也要验**：
   · 回调（notify）验签：用**支付宝公钥**验。不验签 = 任何人 POST 一个表单
     就能白拿套餐（这是最经典、最容易被漏的一步）。
   · **响应**也要验签：`openapi.alipay.com` 的响应带 `sign`，
     内容是响应节点的原始 JSON 子串。不验的话，一个被污染的网络路径
     可以把 `qr_code` 换成攻击者自己的收款码 —— 用户扫了、钱进了别人的账，
     而我们这边一切日志正常。
     ★ 提取用的是 `json.JSONDecoder.raw_decode`（返回消费到的结束下标），
       而不是"解析成 dict 再 dumps 回去"——后者会把空白/键序改掉，
       签名必然对不上。这一条是响应验签能不能成立的关键。

==============================================================================
★ 关于 `httpx` 重试：用 core/resilience.py，不自己写循环
==============================================================================
重试逻辑在本仓有唯一实现（`core/resilience.call_with_retry`）。
这里只做两件配置：
  · 重试对 `precreate` 是**安全**的（单号确定性派生 ⇒ 天然幂等）；
  · 支付宝的业务错误（HTTP 200 + `code != 10000`）**不重试** ——
    它不是异常，`call_with_retry` 本来就看不见它，这里显式地把
    「业务失败」翻译成 `ChargeResult(success=False)`，而不是抛异常去骗重试。
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from core.config import config
from core.logger import get_logger
from core.resilience import RetryPolicy, call_with_retry
from platforms.payment.gateway import (
    PENDING_PAYMENT_TTL_MINUTES,
    SETTLEMENT_ASYNC,
    ChargeIntent,
    ChargeResult,
    GatewayConfigError,
    InvoiceDraft,
)

_log = get_logger("payment.alipay")

#: 支付宝成功码
_ALIPAY_SUCCESS_CODE = "10000"

#: 表示「钱真的到手了」的交易状态。
#: ★ TRADE_FINISHED 也要收 —— 它是交易结束后（不可退款）的终态，
#:   把只认 TRADE_SUCCESS 的写法放到这里，会在"用户付款后隔了一段时间
#:   我们才收到通知"的场景下漏单（通知里的状态已经是 FINISHED）。
_PAID_TRADE_STATUSES = frozenset({"TRADE_SUCCESS", "TRADE_FINISHED"})

#: 交易已关闭（超时未付 / 用户取消）—— 明确失败。
_CLOSED_TRADE_STATUSES = frozenset({"TRADE_CLOSED"})

#: 请求超时（秒）。★ 比 `llm_timeout_seconds` 短：支付接口是**用户在场等待**的
#: 场景，长超时对体验无益；且 precreate 幂等，超时后重试是安全的。
_REQUEST_TIMEOUT = 15.0

#: precreate / query 的重试策略。
#: ★ 比默认策略更保守（attempts=2）：调用发生在**持有订阅行锁**的事务里
#:   （见 modules/billing/router.py 的持锁时长说明），
#:   重试 3 次 × 指数退避最坏要 3 秒以上，会把同一用户的下一次请求一起拖住。
#:   一次重试足以覆盖绝大多数瞬时抖动。
_PAY_RETRY_POLICY = RetryPolicy(attempts=2, base_delay=0.5, multiplier=2.0, max_delay=2.0)

#: 上海时区固定偏移。★ 刻意不用 ZoneInfo("Asia/Shanghai")：
#:   它需要系统 tzdata（Windows 上默认没有，Alpine 镜像也常常没装），
#:   缺失时 `ZoneInfoNotFoundError` 会让**每一笔支付都失败**。
#:   而中国自 1991 年起不再使用夏令时，UTC+8 是恒定的 ⇒ 固定偏移
#:   既确定又不引入任何运行时依赖。判据：能算准的常量，不要换成一个
#:   "可能会缺文件"的运行时查询。
_CST = timezone(timedelta(hours=8))


class AlipaySignatureError(GatewayConfigError):
    """支付宝报文验签失败。

    ★ 单独一个类型（继承 `GatewayConfigError` 但可精确捕获）的理由：
      「密钥配错了」和「报文被篡改/伪造」的整改动作完全不同 ——
      前者去核对开放平台的公钥，后者是安全事件。
      混成一个 400 会让第二种情况被当成"配置问题"翻半天。
    """


# ============================================================================
# 密钥加载
# ============================================================================

def _unwrap_key_text(raw: str) -> str:
    """把 `.env` 里的单行密钥还原成多行 PEM 文本。

    ★ 只替换**字面量** `\\n`（反斜杠 + n），不碰真正的换行 ——
      `.env` 读取器已经把真换行交给了我们（多行值的场景）。
    """
    return (raw or "").strip().replace("\\n", "\n").strip()


def _pem(body: str, label: str) -> str:
    """把纯 base64 包成 PEM（每 64 字符换行，RFC 7468）。"""
    compact = "".join(body.split())
    lines = [compact[i:i + 64] for i in range(0, len(compact), 64)]
    return f"-----BEGIN {label}-----\n" + "\n".join(lines) + f"\n-----END {label}-----\n"


def _load_private_key(raw: str) -> "rsa.RSAPrivateKey":
    """加载应用私钥（PKCS#8 / PKCS#1 都收）。

    Raises:
        GatewayConfigError: 未配置、或两种格式都解析不了。
    """
    text = _unwrap_key_text(raw)
    if not text:
        raise GatewayConfigError(
            "缺少支付宝应用私钥（PAYMENT_ALIPAY_APP_PRIVATE_KEY）⇒ 无法对请求签名，"
            "所有支付调用都会被支付宝拒绝（sign check fail）"
        )

    candidates: list[str] = []
    if "BEGIN" in text:
        candidates.append(text)
    else:
        # 先试 PKCS#8（支付宝文档推荐），再试 PKCS#1（部分密钥工具导出的形态）。
        candidates.append(_pem(text, "PRIVATE KEY"))
        candidates.append(_pem(text, "RSA PRIVATE KEY"))

    last_error: Optional[Exception] = None
    for pem_text in candidates:
        try:
            key = serialization.load_pem_private_key(
                pem_text.encode("utf-8"), password=None
            )
        except Exception as exc:  # noqa: BLE001 —— 逐个候选试，最后一个再报
            last_error = exc
            continue
        if not isinstance(key, rsa.RSAPrivateKey):
            raise GatewayConfigError(
                "支付宝应用私钥不是 RSA 私钥（当前类型 "
                f"{type(key).__name__}）。RSA2 签名只能用 RSA 私钥"
            )
        return key

    raise GatewayConfigError(
        "支付宝应用私钥解析失败：既不是有效的 PEM，也不是可识别的 PKCS#8 / PKCS#1 "
        f"base64。请从开放平台密钥工具重新复制（原因：{last_error}）"
    )


def _load_public_key(raw: str) -> "rsa.RSAPublicKey":
    """加载**支付宝公钥**（用于回调验签）。

    Raises:
        GatewayConfigError: 未配置或解析失败。
    """
    text = _unwrap_key_text(raw)
    if not text:
        raise GatewayConfigError(
            "缺少支付宝公钥（PAYMENT_ALIPAY_PUBLIC_KEY）⇒ 无法验签回调，"
            "而**不验签的回调等于让任何人免费开通套餐**，因此宁可拒收"
        )

    candidates: list[str] = []
    if "BEGIN" in text:
        candidates.append(text)
    else:
        candidates.append(_pem(text, "PUBLIC KEY"))
        candidates.append(_pem(text, "RSA PUBLIC KEY"))

    last_error: Optional[Exception] = None
    for pem_text in candidates:
        try:
            key = serialization.load_pem_public_key(pem_text.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        if not isinstance(key, rsa.RSAPublicKey):
            raise GatewayConfigError(
                "支付宝公钥不是 RSA 公钥（当前类型 "
                f"{type(key).__name__}）"
            )
        return key

    raise GatewayConfigError(
        "支付宝公钥解析失败。★ 最容易踩的坑是**复制成了应用公钥**（而这是支付宝"
        f"公钥），两者格式相同、验签必失败。请到开放平台「支付宝公钥」一栏重新复制"
        f"（原因：{last_error}）"
    )


# ============================================================================
# 签名 / 验签（RSA2 = SHA256withRSA）
# ============================================================================

def sign_content(params: Mapping[str, Any]) -> str:
    """待签名字符串：剔除 `sign` 与空值，按 key 升序，`k=v` 用 `&` 连接。

    ★ 「剔除空值」与「剔除 sign」是支付宝签名规则里唯一两处例外，
      其余任何"顺手优化"（如 URL 编码、去空格）都会让签名对不上。
      值**不做** URL 编码 —— 编码只发生在最终发送时。
    """
    items = [
        (k, str(v))
        for k, v in params.items()
        if k != "sign" and v is not None and str(v) != ""
    ]
    items.sort(key=lambda kv: kv[0])
    return "&".join(f"{k}={v}" for k, v in items)


def rsa2_sign(content: str, private_key: "rsa.RSAPrivateKey") -> str:
    """SHA256withRSA 签名 → base64。"""
    signature = private_key.sign(
        content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def rsa2_verify(content: str, signature_b64: str, public_key: "rsa.RSAPublicKey") -> bool:
    """校验 SHA256withRSA 签名。任何异常都返回 False（由调用方决定怎么报）。"""
    try:
        public_key.verify(
            base64.b64decode(signature_b64),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception:  # noqa: BLE001 —— InvalidSignature / 长度不符 / base64 坏
        return False
    return True


def extract_response_node(raw_body: str, node: str) -> str:
    """从响应原文里取出某个节点**逐字原样**的 JSON 子串（响应验签的内容）。

    ★★ 为什么不能「json.loads 之后再 json.dumps」：
      支付宝签的是**它实际发出的那段字节**。重新序列化会改变键序、空白、
      数字格式（2990.00 → 2990.0）⇒ 内容变了 ⇒ 签名必然对不上。
      唯一的正确做法是拿到原始子串，`raw_decode` 正是为此存在的
      （它返回消费到的结束下标，等于免费给了我们子串的边界）。

    Raises:
        AlipaySignatureError: 报文结构不是预期的形状（无法定位节点）。
    """
    key = f'"{node}"'
    idx = raw_body.find(key)
    if idx < 0:
        raise AlipaySignatureError(f"支付宝响应里找不到节点 {node}，无法验签")
    colon = raw_body.find(":", idx + len(key))
    if colon < 0:
        raise AlipaySignatureError(f"支付宝响应的 {node} 节点结构异常，无法验签")

    # ★★ 必须**自己**跳过 `:` 与值之间的空白（2026-09-25 实测踩到）：
    #   `JSONDecoder.raw_decode(s, idx)` 要求 `s[idx]` **就是**值的第一个字符，
    #   它不会替你跳过前置空白（跳过空白是 `decode()` 的职责，不是 `raw_decode` 的）。
    #   而支付宝的响应是 `{"node": {…}}` 这种带空格的排版 ⇒ 直接传 `colon+1`
    #   会抛 `JSONDecodeError: Expecting value`，表现是**每一笔支付都验签失败**，
    #   且错误信息看起来像"支付宝返回了坏 JSON"，归因完全反向。
    #   ⇒ 这里显式定位值的起点，同时也就拿到了子串的**精确左边界**
    #     （不需要再 `.strip()`，避免把"值内部的前导空白"误伤）。
    start = colon + 1
    while start < len(raw_body) and raw_body[start] in " \t\r\n":
        start += 1
    if start >= len(raw_body):
        raise AlipaySignatureError(f"支付宝响应的 {node} 节点后没有值，无法验签")

    try:
        _obj, end = json.JSONDecoder().raw_decode(raw_body, start)
    except ValueError as exc:
        raise AlipaySignatureError(
            f"支付宝响应的 {node} 节点不是合法 JSON，无法验签：{exc}"
        ) from exc

    return raw_body[start:end]


# ============================================================================
# 订单号派生
# ============================================================================

def out_trade_no_for(idempotency_key: str) -> str:
    """由业务幂等键**确定性**派生支付宝商户订单号。

    约束（支付宝侧）：只允许字母/数字/下划线，长度 <= 64。

    ★ 为什么必须确定性（而不是每次随机）：
      `ChargeIntent.idempotency_key` 的语义是「同一次业务动作重试带同一个值」。
      若这里换成 `uuid4()`，客户端超时重发就会在支付宝侧变成**两笔订单** ——
      用户可能扫两次、付两次。派生式单号把"同一意图 ⇒ 同一订单"这条
      不变量从业务层一直贯通到支付宝，让网关侧也能去重。

    ★ 为什么用 sha256 而不是直接拼接原键：
      原键形如 `sub:{uuid}:{plan_id}:{cycle}:{plan_id}|active|monthly|2026...`，
      含 `:` 与 `|` —— 支付宝会直接拒绝这种单号。
    """
    digest = hashlib.sha256((idempotency_key or "").encode("utf-8")).hexdigest()
    return f"SUB{digest[:28].upper()}"


# ============================================================================
# 回调解析
# ============================================================================

@dataclass(frozen=True)
class NotifyResult:
    """一次已验签通过的支付宝异步通知（字段名对齐支付宝，语义我们重述）。"""

    out_trade_no: str          # = 我们账单上的 transaction_id
    trade_no: str              # 支付宝交易号（对账/客服查询用）
    trade_status: str
    total_amount: str          # 支付宝给的金额字符串（"2990.00"）
    app_id: str = ""
    notify_id: str = ""
    gmt_payment: str = ""

    @property
    def is_paid(self) -> bool:
        """钱是否**真的**到账（唯一判据）。"""
        return self.trade_status in _PAID_TRADE_STATUSES

    @property
    def is_closed(self) -> bool:
        return self.trade_status in _CLOSED_TRADE_STATUSES

    @property
    def amount_yuan(self) -> Optional[float]:
        """金额转 float；解析失败返回 None（**不**兜底成 0：
        0 会让"金额对不上"的校验静默通过，而那正是要拦的情况）。"""
        try:
            return round(float(self.total_amount), 2)
        except (TypeError, ValueError):
            return None

    @property
    def paid_at_utc(self) -> Optional[datetime]:
        """`gmt_payment` → 库口径的 naive UTC 时间。

        ★ 为什么必须显式换算而不是直接 `datetime.strptime`：
          支付宝的时间是**东八区**（`gmt_payment` = "2026-09-25 10:01:00" 表示北京时间），
          而本库全部按 `datetime.utcnow()` 存 naive UTC（见 models 的 default）。
          直接存进去，账单的 `paid_at` 会比真实时间早 8 小时 ——
          对账时按日聚合，「昨晚 23:00 付的款」会被算进**前一天**，
          表现为「日流水对不上，但逐笔都对得上」，极难定位。

        ★ 解析失败返回 None（不抛异常）：调用方会退回 `datetime.utcnow()`。
          一条时间字段格式异常的报文不该让整笔支付失败 —— 钱是真的到了。
        """
        raw = (self.gmt_payment or "").strip()
        if not raw:
            return None
        try:
            naive_cst = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return naive_cst.replace(tzinfo=_CST).astimezone(timezone.utc).replace(tzinfo=None)


# ============================================================================
# 网关实现
# ============================================================================

class AlipayGateway:
    """支付宝当面付（precreate）网关。

    流程：
        charge()            → alipay.trade.precreate → 二维码 + pending 账单草案
        verify_notify()     → 回调验签（支付宝公钥）
        parse_notify()      → 回调字段解析
        query_trade()       → alipay.trade.query（对账 / 漏回调补偿）
    """

    name = "alipay"

    #: ★ 异步结算：调用方必须走两段式，绝不能在本方法返回时就开通服务。
    settlement_mode = SETTLEMENT_ASYNC

    # ---------------------------------------------------------------- 配置

    @staticmethod
    def _require_app_id() -> str:
        app_id = (config.payment_alipay_app_id or "").strip()
        if not app_id:
            raise GatewayConfigError(
                "缺少支付宝应用 APPID（PAYMENT_ALIPAY_APP_ID）"
            )
        return app_id

    @staticmethod
    def _require_notify_url() -> str:
        url = config.resolve_payment_notify_url()
        if not url:
            raise GatewayConfigError(
                "缺少支付回调地址：请设 PUBLIC_BASE_URL（推荐）或 PAYMENT_NOTIFY_URL。"
                "★ 没有回调地址时支付宝无法通知我们到账，"
                "用户付了钱订阅也不会激活"
            )
        if not url.lower().startswith(("http://", "https://")):
            raise GatewayConfigError(
                f"支付回调地址不是绝对 URL（当前 '{url}'）"
            )
        return url

    @staticmethod
    def _endpoint() -> str:
        return (config.payment_alipay_gateway or "").strip() or (
            "https://openapi.alipay.com/gateway.do"
        )

    # ------------------------------------------------------------ 请求组装

    def _build_params(self, method: str, biz_content: dict) -> dict:
        """组装一个已签名的公共请求参数集。"""
        params: dict[str, Any] = {
            "app_id": self._require_app_id(),
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            # 支付宝要求 yyyy-MM-dd HH:mm:ss，且以**东八区**为准
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            # ★ biz_content 必须是 JSON 字符串。`ensure_ascii=False` 让中文
            #   商品名以 UTF-8 原文参与签名（charset=utf-8 与之配套）；
            #   separators 去空格同样是"减少签名内容的不确定性"。
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = rsa2_sign(sign_content(params), _load_private_key(
            config.payment_alipay_app_private_key
        ))
        return params

    async def _call(self, method: str, biz_content: dict, *, node: str) -> dict:
        """发起一次网关调用，验签后返回响应节点（dict）。

        Raises:
            GatewayConfigError: 配置缺失 / 验签失败。
            httpx.HTTPError: 网络层失败（已按策略重试）。
        """
        params = self._build_params(method, biz_content)
        endpoint = self._endpoint()

        async def _post() -> httpx.Response:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.post(endpoint, data=params)
                resp.raise_for_status()
                return resp

        try:
            resp = await call_with_retry(
                _post, policy=_PAY_RETRY_POLICY, what=f"alipay {method}"
            )
        except httpx.HTTPStatusError as exc:
            # 网关返回了非 2xx（通常是 5xx 或 WAF 拦截）。转成业务可读的失败，
            # 而不是让 500 冒到用户面前 —— 用户看不懂，运维也定位不到。
            raise GatewayConfigError(
                f"支付宝网关返回 HTTP {exc.response.status_code}，"
                f"请检查网关地址配置（当前 {endpoint}）"
            ) from exc

        raw = resp.text
        payload = resp.json()

        # ★ 先验签，再信任里面的任何字段。顺序反了 = 验签形同虚设。
        signature = payload.get("sign")
        if not signature:
            raise AlipaySignatureError(
                f"支付宝响应缺少 sign 字段（{node}）。"
                f"★ 这通常意味着网关地址被指向了一个**非支付宝**的服务"
                f"（当前 {endpoint}）"
            )
        node_text = extract_response_node(raw, node)
        if not rsa2_verify(node_text, signature, _load_public_key(
            config.payment_alipay_public_key
        )):
            raise AlipaySignatureError(
                f"支付宝响应验签失败（{node}）。请核对 PAYMENT_ALIPAY_PUBLIC_KEY "
                f"是否为开放平台「支付宝公钥」一栏（而不是应用公钥）"
            )

        result = payload.get(node)
        if not isinstance(result, dict):
            raise GatewayConfigError(
                f"支付宝响应缺少 {node} 节点，实际顶层键：{sorted(payload.keys())}"
            )
        return result

    # ------------------------------------------------------------ charge

    async def charge(self, intent: ChargeIntent) -> ChargeResult:
        """发起「生成收款二维码」，**不**代表已收款。

        Returns:
            成功时 `success=True` + `requires_confirmation=True` +
            一张 `status="pending"` 的账单草案（含 qr_code 与商户订单号）。

        Raises:
            GatewayConfigError: 配置不完整或验签失败（调用方应转 503，
                且**绝不能**降级成"支付成功"）。
        """
        amount = round(float(intent.amount or 0), 2)
        if amount <= 0:
            # ★ 走到这里说明调用方的短路逻辑出了问题（零元单应当在那里就被拦下）。
            #   报错而不是返回一张 ¥0.00 的待支付单：后者会让用户在支付宝上
            #   扫到一个零元订单，且它在我们库里占着一个 pending 状态。
            raise GatewayConfigError(
                f"支付宝不接受非正数金额（收到 {amount}）：零元单应在调用网关之前短路"
            )

        out_trade_no = out_trade_no_for(intent.idempotency_key)
        notify_url = self._require_notify_url()

        biz = {
            "out_trade_no": out_trade_no,
            # ★ 两位小数字符串。见模块 docstring 第 ② 条。
            "total_amount": f"{amount:.2f}",
            "subject": (intent.description or "订阅套餐")[:256],
            "timeout_express": f"{PENDING_PAYMENT_TTL_MINUTES}m",
            # 回调地址必须在**请求参数**里给（每次下单都可以不同），
            # 而不是只依赖开放平台的应用配置 —— 后者在多环境（沙箱/生产）
            # 共用同一个 app_id 时会互相串。
            "notify_url": notify_url,
        }
        if intent.billing_cycle:
            biz["passback_params"] = intent.billing_cycle

        result = await self._call(
            "alipay.trade.precreate", biz, node="alipay_trade_precreate_response"
        )

        code = str(result.get("code") or "")
        if code != _ALIPAY_SUCCESS_CODE:
            sub_code = result.get("sub_code") or ""
            sub_msg = result.get("sub_msg") or result.get("msg") or "未知原因"
            _log.warning(
                "支付宝 precreate 失败 code={} sub_code={} msg={} out_trade_no={}",
                code, sub_code, sub_msg, out_trade_no,
            )
            # ★ 业务失败 → success=False（**不是**抛异常）。
            #   抛异常会被 call_with_retry 之外的上层当成"基础设施故障"，
            #   而这里其实是一个确定性的业务结论（参数错、商户状态异常）。
            return ChargeResult(
                success=False,
                error=f"支付宝下单失败：{sub_msg}（{sub_code or code}）",
            )

        qr_code = str(result.get("qr_code") or "")
        if not qr_code:
            # 有 code=10000 却没有 qr_code ⇒ 报文不符合约定。宁可失败也不要
            # 返回一张没有二维码的"待支付单"（用户会看到一片空白且无解释）。
            return ChargeResult(
                success=False,
                error="支付宝返回成功但缺少 qr_code，无法生成收款二维码",
            )

        now = datetime.utcnow()
        invoice = InvoiceDraft(
            user_id=intent.user_id,
            number=f"INV-{now.strftime('%Y%m%d%H%M%S')}-{out_trade_no[-4:]}",
            amount=amount,
            currency=intent.currency or "CNY",
            # ★★ status 是 **pending**，不是 paid。这一行是整个两段式的地基：
            #    它让「账单存在」与「钱到账」彻底解耦，webhook 才有东西可改。
            status="pending",
            description=intent.description or "",
            issued_at=now,
            paid_at=None,
            idempotency_key=intent.idempotency_key or None,
            transaction_id=out_trade_no,
            payment_channel=self.name,
            pay_url=qr_code,
        )
        return ChargeResult(
            success=True,
            invoice=invoice,
            client_secret="",
            transaction_id=out_trade_no,
            requires_confirmation=True,
            qr_code_url=qr_code,
        )

    # ------------------------------------------------------------ query

    async def query_trade(self, out_trade_no: str) -> dict:
        """查询一笔订单在支付宝侧的真实状态（对账 / 补偿漏掉的回调）。

        ★ 这个方法是「日对账」任务的基础设施，**不是**可选项：
          真实支付必须有对账，因为 webhook 会丢（网络、我们的服务在重启、
          部署窗口期）。没有它，漏掉的单只能等用户投诉。
        """
        result = await self._call(
            "alipay.trade.query",
            {"out_trade_no": out_trade_no},
            node="alipay_trade_query_response",
        )
        return result

    # ------------------------------------------------------------ notify

    def verify_notify(self, params: Mapping[str, str]) -> bool:
        """校验回调表单的签名。

        Raises:
            GatewayConfigError: 未配置公钥（**不是**返回 False —— 返回 False
                会被上层当成"伪造请求"，而真相是"这个部署没配钥匙"，
                归因方向完全相反）。
        """
        signature = (params.get("sign") or "").strip()
        if not signature:
            _log.warning("支付宝回调缺少 sign 字段 ⇒ 拒收")
            return False
        content = sign_content(params)
        return rsa2_verify(content, signature, _load_public_key(
            config.payment_alipay_public_key
        ))

    def parse_notify(self, params: Mapping[str, str]) -> NotifyResult:
        """把回调表单解析成 `NotifyResult`（**不**做验签，调用方必须先验签）。"""
        return NotifyResult(
            out_trade_no=str(params.get("out_trade_no") or ""),
            trade_no=str(params.get("trade_no") or ""),
            trade_status=str(params.get("trade_status") or ""),
            total_amount=str(params.get("total_amount") or ""),
            app_id=str(params.get("app_id") or ""),
            notify_id=str(params.get("notify_id") or ""),
            gmt_payment=str(params.get("gmt_payment") or ""),
        )

    def app_id_matches(self, notify: NotifyResult) -> bool:
        """回调里的 app_id 是否就是我们自己（防跨应用重放）。

        签名已经保证了报文来自「持有该公钥对应私钥的一方」= 支付宝，
        但它不区分**哪个应用**。若同一个开发者账号下有多个应用、
        而我们把回调地址配到了错误的那个，签名依然通过、订单号却对不上。
        显式对一下 app_id，能让这类配置错误变成一条明确的日志。
        """
        mine = (config.payment_alipay_app_id or "").strip()
        if not mine:
            return True   # 未配置时不做判定（护栏已在生产环境拦住）
        return notify.app_id == mine


__all__ = [
    "AlipayGateway",
    "AlipaySignatureError",
    "NotifyResult",
    "extract_response_node",
    "out_trade_no_for",
    "rsa2_sign",
    "rsa2_verify",
    "sign_content",
]

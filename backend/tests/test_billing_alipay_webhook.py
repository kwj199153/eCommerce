"""支付宝 webhook + 二维码端点门禁（P0，2026-09-25）

==============================================================================
★★★ 这条门禁守的是「钱能不能被伪造出来」
==============================================================================
`POST /billing/webhook/alipay` 是**免鉴权**的 —— 支付宝服务器没有我们的
Bearer Token。免鉴权在这里是**必须**的，但它把整条链路的信任边界搬到了
两个业务判定上（`payment_router.py` 文件头那两道门）：

    ① **验签**   —— 用支付宝公钥验 RSA2。少了它，任何人
       `curl -d "out_trade_no=SUBxxx&trade_status=TRADE_SUCCESS"` 就能白拿年付。
    ② **金额核对** —— 验签只证明「消息来自支付宝」，不证明「金额与账单一致」。
       少了它，一笔 0.01 元的真通知能开通 2990 元的套餐。

⇒ 本文件的用例全部**从 HTTP 打进来**（不直接调 `settle_invoice`），
  因为要守的正是这条**带签名**的入口。

==============================================================================
★★ 为什么用真 RSA 密钥对签名（而不是给 `verify_notify` 打桩）
==============================================================================
给 `verify_notify` 打桩 = 把两道门里最陡的那道换成“永远通过”，
于是「签名算错」「参数被篡改」「公钥配错」这三类真实故障**一条都测不出来**
（而它们恰恰是支付集成里最常见的三个坑）。
这里用 `cryptography` 现场生成一对 2048 位密钥、按支付宝的规则签名
（`platforms/payment/alipay.py::sign_content` 是与生产同一份实现），
于是：**篡改任一字段 = 签名必然对不上** —— 门是真的在被考验。

==============================================================================
★ 反向注入清单（每条都必须让本文件**至少一条**转红）
==============================================================================
 1. `payment_router.alipay_notify` 删掉 `if not verified: return _NACK`
    ⇒ `test_bad_signature_is_rejected` 转红（伪造通知会被当成真通知）。
 2. 删掉 `if not amount_matches(...): return _NACK`
    ⇒ `test_amount_mismatch_is_rejected` 转红（0.01 元开通 2990 元套餐）。
 3. `settle_invoice` 的 `.with_for_update()` 或 `.execution_options(populate_existing=True)`
    去掉任一个 ⇒ `test_replayed_notify_does_not_extend_period_twice` 转红
    （重复通知把订阅周期又推进一次 = 用户白得一个周期）。
 4. `qr` 端点把归属校验去掉（只按 invoice_id 查）⇒
    `test_foreign_invoice_is_indistinguishable_from_missing` 转红。
 5. `PAYMENT_NOTIFY_PATH` 从 `core/middleware/rate_limit.py::DEFAULT_EXEMPT_PATHS`
    移除 ⇒ 支付宝重投会被 429（见 `tests/test_billing_payment.py` 附近的
    路由挂载断言与之配套）。
 6. `payments.pending_payment_payload` 的两行改回裸 `.isoformat()`
    ⇒ `test_polling_endpoint_timestamps_are_unambiguous` /
      `test_pending_endpoint_timestamps_are_unambiguous` 转红
    （无偏移 ⇒ 浏览器按本地时区解析 ⇒ 倒计时一打开就显示"已过期"）。
"""

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import text

from core.database import async_session_factory
from platforms.payment.alipay import sign_content
from platforms.payment.gateway import PENDING_PAYMENT_TTL_MINUTES

#: 本用例自造的「应用 APPID」与「支付宝公钥」所对应的私钥。
#: ★ 私钥只活在内存里（每次跑用例现生成），与任何真实商户无关。
APP_ID = "2021000000000000"

_KEYS: dict = {}


def _keys() -> tuple[
    "rsa.RSAPrivateKey", "rsa.RSAPublicKey", str, str
]:
    """生成（并缓存）一对 RSA 密钥；返回 (私钥, 公钥, 私钥PEM, 公钥PEM)。

    ★ 模块内缓存而不是每个用例各生成一次：2048 位密钥生成约 50~200ms，
      本文件有十来条用例，每次重生成会让这一组门禁慢到没人愿意跑。
    """
    if not _KEYS:
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = priv.public_key()
        _KEYS["priv"] = priv
        _KEYS["pub"] = pub
        _KEYS["priv_pem"] = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        _KEYS["pub_pem"] = pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
    return _KEYS["priv"], _KEYS["pub"], _KEYS["priv_pem"], _KEYS["pub_pem"]


def _configure(monkeypatch, *, app_id: str = APP_ID, public_key: str = None):
    """把支付宝配置打进 `config`（公钥 = 上面那对密钥里的公钥）。"""
    if public_key is None:
        public_key = _keys()[3]
    monkeypatch.setattr(
        "core.config.config.payment_alipay_app_id", app_id, raising=True
    )
    monkeypatch.setattr(
        "core.config.config.payment_alipay_public_key", public_key, raising=True
    )


def _signed_form(**params) -> dict:
    """按支付宝规则签名，返回可以直接当表单提交的 dict。

    ★ 签名对象是 `sign_content(params)`（生产同一实现），
      所以「改一个字段而签名不跟着改」必然验签失败 —— 这正是要考的。
    """
    priv = _keys()[0]
    payload = {k: str(v) for k, v in params.items() if v is not None}
    # ★★ `sign_type` 必须在**签名之前**就放进 payload（实测踩到）：
    #   支付宝的待签串只剔除 `sign` 一个字段（`sign_content` 与生产同实现），
    #   `sign_type` 是**参与签名**的。先签后加 ⇒ 签名与提交内容不一致 ⇒ 全部 400。
    #   真实回调里 `sign_type` 本来就带在表单上，所以"先放再签"才是真实形态。
    payload["sign_type"] = "RSA2"
    content = sign_content(payload)
    sig = priv.sign(
        content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    payload["sign"] = base64.b64encode(sig).decode("ascii")
    return payload


async def _post_notify(client, params: dict):
    """投递一条回调（**不带任何 Authorization 头** —— 支付宝也不会带）。"""
    return await client.post(
        "/api/v1/billing/webhook/alipay",
        data=params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


# ============================================================================
# 夹具：一张 pending 账单
# ============================================================================

async def _make_pending_invoice(
    user_id: str,
    *,
    amount: float = 2990.0,
    plan_id: int = 2,
    cycle: str = "yearly",
    trade_no: str = None,
) -> dict:
    """直接落一张 pending 账单（模拟「下单拿到二维码、用户还没付」那一刻）。

    ★ 直接写库而不是走 `/billing/subscribe`：本文件要考的是**第二段**
      （收钱），用真实支付宝下单需要商户号与公网回调地址，测试环境给不了。
      直接落 pending 账单 = 精确构造「webhook 到达时库里的样子」。
    """
    trade_no = trade_no or ("SUB" + uuid.uuid4().hex[:28].upper())
    invoice_id = str(uuid.uuid4())
    now = datetime.utcnow()
    async with async_session_factory() as db:
        await db.execute(
            text(
                "INSERT INTO invoices (id, user_id, number, amount, currency, status,"
                " description, issued_at, plan_id, billing_cycle, transaction_id,"
                " payment_channel, pay_url, created_at)"
                " VALUES (:id, :u, :num, :amt, 'CNY', 'pending', :desc, :ts, :pid,"
                " :cyc, :tid, 'alipay', :pay, :ts)"
            ),
            {
                "id": invoice_id,
                "u": user_id,
                "num": "INV-" + uuid.uuid4().hex[:10].upper(),
                "amt": amount,
                "desc": "专业版年付",
                "ts": now,
                "pid": plan_id,
                "cyc": cycle,
                "tid": trade_no,
                "pay": "https://qr.alipay.com/" + uuid.uuid4().hex[:20],
            },
        )
        await db.commit()
    return {"id": invoice_id, "trade_no": trade_no}


async def _invoice_row(invoice_id: str) -> dict:
    async with async_session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT status, paid_at, amount, payment_channel, plan_id"
                    " FROM invoices WHERE id = :i"
                ),
                {"i": invoice_id},
            )
        ).mappings().first()
    return dict(row) if row else {}


async def _subscription_of(user_id: str) -> dict:
    async with async_session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT status, plan_id, billing_cycle, current_period_end,"
                    " api_calls_used FROM subscriptions WHERE user_id = :u"
                ),
                {"u": user_id},
            )
        ).mappings().first()
    return dict(row) if row else {}


def _paid_notify(trade_no: str, *, amount: str = "2990.00", **extra) -> dict:
    base = dict(
        out_trade_no=trade_no,
        trade_no="2026092522001" + uuid.uuid4().hex[:10],
        trade_status="TRADE_SUCCESS",
        total_amount=amount,
        app_id=APP_ID,
        notify_id="nid-" + uuid.uuid4().hex[:12],
        gmt_payment="2026-09-25 18:30:00",
        seller_id="2088000000000000",
    )
    base.update(extra)
    return base


# ============================================================================
# 1. 正向：真通知 ⇒ 账单转 paid + 订阅真的被开通
# ============================================================================

async def test_valid_notify_settles_invoice_and_activates_subscription(
    client, make_user, monkeypatch
):
    """一条**签名正确、金额一致**的通知必须：回 success、账单转 paid、订阅生效。

    ★ 这条同时证明「webhook 免鉴权」是**可用**的：请求里没有任何
      Authorization 头（支付宝也不会有），却必须处理成功。
    """
    _configure(monkeypatch)
    owner = await make_user("aliwebhook")
    inv = await _make_pending_invoice(owner["user_id"])

    before = await _subscription_of(owner["user_id"])
    assert before.get("plan_id") != 2, (
        f"前置不成立：注册后本应是 free 套餐，实际 plan_id={before.get('plan_id')}"
    )

    r = await _post_notify(client, _signed_form(**_paid_notify(inv["trade_no"])))
    assert r.status_code == 200, f"期望 200，实际 {r.status_code} {r.text}"
    assert r.text.strip() == "success", (
        f"★ 支付宝只认**逐字** success（不能带引号、不能加空格）—— "
        f"响应体是 {r.text!r} 时它会把这条通知重投 24 小时，"
        f"而我们日志里全是“处理成功”。"
    )

    row = await _invoice_row(inv["id"])
    assert row["status"] == "paid", f"账单没有转 paid：{row}"
    assert row["paid_at"] is not None, "paid_at 必须落库（对账按日聚合要用它）"
    assert row["payment_channel"] == "alipay"

    after = await _subscription_of(owner["user_id"])
    assert after.get("plan_id") == 2, (
        f"★ 钱到了却没开通套餐（plan_id={after.get('plan_id')}）—— "
        f"用户会付了钱什么都拿不到。"
    )
    assert after.get("billing_cycle") == "yearly"
    assert after.get("current_period_end") is not None, "必须写入到期时间（调度靠它清算）"


async def test_paid_at_uses_beijing_time_converted_to_utc(client, make_user, monkeypatch):
    """`gmt_payment` 是**东八区**，落库必须是 naive UTC（差 8 小时会让对账错一天）。

    ★ 为什么值得单列：这个错**不会**让任何流程失败 —— 账单照样 paid、
      订阅照样生效，只有“按日聚合的流水”对不上，而逐笔看又都对。
      ⇒ 归因极难，必须靠用例钉住。
    """
    _configure(monkeypatch)
    owner = await make_user("alitimeshift")
    inv = await _make_pending_invoice(owner["user_id"])

    ts = "2026-09-25 18:30:00"        # 北京时间
    r = await _post_notify(
        client, _signed_form(**_paid_notify(inv["trade_no"], gmt_payment=ts))
    )
    assert r.text.strip() == "success", r.text

    row = await _invoice_row(inv["id"])
    assert row["paid_at"] is not None
    # 18:30 CST == 10:30 UTC（同一天）；若直接 strptime 落库则是 18:30 UTC（差 8 小时）
    assert row["paid_at"].hour == 10 and row["paid_at"].minute == 30, (
        f"★ paid_at 看起来是原生北京时间而不是 UTC：{row['paid_at']}。"
        f"支付宝的 gmt_payment 是东八区，直接落库会让对账按日聚合错一天。"
    )


# ============================================================================
# 2. 幂等：同一条通知投两次，权益只推进一次
# ============================================================================

async def test_replayed_notify_does_not_extend_period_twice(
    client, make_user, monkeypatch
):
    """★★★ 支付宝是 **at-least-once**：同一条通知会被重复投递。

    ★ 两次都必须回 `success`（语义是「这条消息我处理过了」），
      但订阅周期只能被推进**一次** —— 否则用户白得一个周期，
      而这件事在界面上完全看不出来（订阅是 active，日期更靠后而已）。

    ★ 反向注入：去掉 `settle_invoice` 里的
      `.with_for_update()` 或 `.execution_options(populate_existing=True)`
      ⇒ 本条转红（第二次调用读到旧状态，再开通一次）。
    """
    _configure(monkeypatch)
    owner = await make_user("aliidem")
    inv = await _make_pending_invoice(owner["user_id"])
    params = _signed_form(**_paid_notify(inv["trade_no"]))

    r1 = await _post_notify(client, params)
    assert r1.text.strip() == "success", r1.text
    first = await _subscription_of(owner["user_id"])
    first_paid_at = (await _invoice_row(inv["id"]))["paid_at"]

    # 同一条报文原样重投（支付宝就是这么干的）
    r2 = await _post_notify(client, params)
    assert r2.status_code == 200 and r2.text.strip() == "success", (
        f"★ 重复通知必须回 success（否则支付宝会一直重投 24 小时）："
        f"{r2.status_code} {r2.text!r}"
    )

    second = await _subscription_of(owner["user_id"])
    assert second["current_period_end"] == first["current_period_end"], (
        f"★★ 重复通知把订阅周期又推进了一次：{first['current_period_end']} → "
        f"{second['current_period_end']} —— 用户白得一个周期，且界面上看不出来。"
    )
    assert (await _invoice_row(inv["id"]))["paid_at"] == first_paid_at, (
        "重复通知改写了 paid_at —— 对账时会看到同一笔钱两个到账时间。"
    )

    async with async_session_factory() as db:
        n = (
            await db.execute(
                text("SELECT count(*) FROM invoices WHERE user_id = :u"),
                {"u": owner["user_id"]},
            )
        ).scalar_one()
    assert n == 1, f"重复通知产生了额外账单：{n} 张"


# ============================================================================
# 3. 门①：验签（伪造通知）
# ============================================================================

async def test_bad_signature_is_rejected(client, make_user, monkeypatch):
    """签名不对（= 伪造通知）必须回非 success，且**不碰任何数据**。

    ★ 这是支付集成里最经典的漏洞：没有验签，任何人 curl 一下就白拿年付。

    ★ 反向注入：删掉 `if not verified: return _NACK` ⇒ 本条转红。
    """
    _configure(monkeypatch)
    owner = await make_user("aliforge")
    inv = await _make_pending_invoice(owner["user_id"])
    before = await _subscription_of(owner["user_id"])

    params = _signed_form(**_paid_notify(inv["trade_no"]))
    # ★★ 篡改的字段必须是「**没有第二道门看它**」的那个（反向注入实测踩到）：
    #
    #   第一版这里改的是 `total_amount`，结果把验签门整段删掉之后本用例**仍然绿** ——
    #   因为金额门会接着拦住它（400），断言 `!= success` 照样成立。
    #   于是这条用例实际考的是金额门，而不是它声称的验签门（**假绿**：
    #   一条守卫被另一条守卫顶住，看起来"验签被验证过了"，其实没有）。
    #
    #   `seller_id` 是真实回调里存在、而本模块**任何其他地方都不读**的字段：
    #   改了它 ⇒ 只有验签会报错。验签一旦失效，这条报文就是一笔"合法"的付款。
    params["seller_id"] = "2088" + uuid.uuid4().hex[:12]

    r = await _post_notify(client, params)
    assert r.text.strip() != "success", (
        f"★★★ 篡改过的报文被当成真通知处理了（{r.status_code} {r.text!r}）—— "
        f"任何人只要知道回调地址就能免费开通任意套餐。"
    )
    assert r.status_code == 400, f"验签失败应得 400（客户端错误），实际 {r.status_code}"

    assert (await _invoice_row(inv["id"]))["status"] == "pending", (
        "★ 验签失败却改了账单状态 —— 攻击者可以用伪造通知污染对账数据。"
    )
    assert await _subscription_of(owner["user_id"]) == before, "验签失败却改了订阅"


async def test_signature_from_a_foreign_private_key_is_rejected(
    client, make_user, monkeypatch
):
    """用**别人的私钥**签的通知必须被拒（模拟“攻击者自带密钥对”）。

    ★ 与上一条的区别：上一条是“签名与报文不匹配”，这条是“签名与报文
      完全自洽，只是不是支付宝的公钥签的”。少了公钥校验的实现会放行它。
    """
    _configure(monkeypatch)
    owner = await make_user("aliforeign")
    inv = await _make_pending_invoice(owner["user_id"])

    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = {k: str(v) for k, v in _paid_notify(inv["trade_no"]).items()}
    payload["sign_type"] = "RSA2"          # 参与签名，必须在签名前放入
    sig = attacker.sign(
        sign_content(payload).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    payload["sign"] = base64.b64encode(sig).decode("ascii")

    r = await _post_notify(client, payload)
    assert r.text.strip() != "success", (
        f"★ 用陌生私钥签的通知被放行了（{r.status_code}）—— 说明验签用的不是"
        f"支付宝公钥，或者根本没验。"
    )
    assert (await _invoice_row(inv["id"]))["status"] == "pending"


async def test_missing_public_key_is_503_not_false(client, make_user, monkeypatch):
    """没配公钥时必须回 **503**（可重试），而不是 400 / success。

    ★ 这条钉的是**归因方向**：
        · 回 400 ⇒ 被当成“伪造请求”，我们会去查攻击，而真相是“这个部署没配钥匙”；
        · 回 success ⇒ 在“无法判断真伪”时默认相信对方（最坏的一档）；
        · 回 503 ⇒ 语义正确：“我暂时处理不了，请重投” —— 配好钥匙后这笔钱自动补上。
      `verify_notify` 抛 `GatewayConfigError` 而不是返回 False，正是为此。
    """
    _configure(monkeypatch, public_key="")     # 故意不配公钥
    owner = await make_user("alinokey")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await _post_notify(client, _signed_form(**_paid_notify(inv["trade_no"])))
    assert r.status_code == 503, (
        f"缺公钥时应回 503（让支付宝重投），实际 {r.status_code} {r.text!r}"
    )
    assert r.text.strip() != "success", "无法验签时绝不能回 success"
    assert (await _invoice_row(inv["id"]))["status"] == "pending"


# ============================================================================
# 4. 门②：金额核对
# ============================================================================

async def test_amount_mismatch_is_rejected(client, make_user, monkeypatch):
    """签名正确但**金额与账单不符** ⇒ 拒收（且不激活）。

    ★ 为什么必须在验签之外**单独**核金额：验签只证明“消息来自支付宝”，
      不证明“金额和我们账单一致”。一笔 0.01 元的**真实**付款（用户自己
      或者攻击者用小额订单）如果被用来核销 2990 元的账单，就是平台亏钱。

    ★ 反向注入：删掉 `if not amount_matches(...)` 分支 ⇒ 本条转红。
    """
    _configure(monkeypatch)
    owner = await make_user("aliamount")
    inv = await _make_pending_invoice(owner["user_id"], amount=2990.0)

    r = await _post_notify(
        client, _signed_form(**_paid_notify(inv["trade_no"], amount="0.01"))
    )
    assert r.text.strip() != "success", (
        f"★ 金额不符的通知被当成有效付款处理了（{r.status_code} {r.text!r}）—— "
        f"0.01 元开通 2990 元的套餐，平台直接亏钱。"
    )
    assert r.status_code == 400, f"金额不符应得 400，实际 {r.status_code}"
    assert (await _invoice_row(inv["id"]))["status"] == "pending"
    sub = await _subscription_of(owner["user_id"])
    assert sub.get("plan_id") != 2, "金额不符却激活了套餐"


async def test_missing_amount_is_rejected(client, make_user, monkeypatch):
    """通知里没有金额 ⇒ 判为不符（**不**宽松放行）。

    ★ `amount_matches` 对 `None` 一律返回 False 而不是“跳过校验”：
      缺少金额字段本身就是报文异常，宽松处理等于给了一条绕过门②的路。
    """
    _configure(monkeypatch)
    owner = await make_user("alinoamount")
    inv = await _make_pending_invoice(owner["user_id"])
    params = _paid_notify(inv["trade_no"])
    params.pop("total_amount")
    # ★ 注意：这里必须**包含** total_amount 才能验签成功，
    #   所以改为签名之后再删 —— 否则测的是门①而不是门②。
    signed = _signed_form(**params)
    signed.pop("total_amount", None)

    r = await _post_notify(client, signed)
    assert r.text.strip() != "success", (
        f"缺金额的通知被放行了（{r.status_code} {r.text!r}）"
    )


# ============================================================================
# 5. app_id 核对（防跨应用回调）
# ============================================================================

async def test_foreign_app_id_is_rejected(client, make_user, monkeypatch):
    """回调里的 app_id 与本应用不一致 ⇒ 拒收（回调地址配串了的明确信号）。"""
    _configure(monkeypatch)
    owner = await make_user("aliappid")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await _post_notify(
        client,
        _signed_form(**_paid_notify(inv["trade_no"], app_id="2021999999999999")),
    )
    assert r.status_code == 400, (
        f"app_id 不匹配应得 400，实际 {r.status_code} {r.text!r}"
    )
    assert (await _invoice_row(inv["id"]))["status"] == "pending"


# ============================================================================
# 6. 非「已付款」状态：明确表态，不做开通
# ============================================================================

async def test_closed_trade_marks_invoice_expired(client, make_user, monkeypatch):
    """`TRADE_CLOSED`（超时未付 / 交易关闭）⇒ 账单标 expired，**不回退**订阅。

    ★ 为什么标 expired 而不是删掉：账单是资金凭证，删了之后对账时
      这笔“曾经下过单”的历史就没了；而 UI 需要知道“这张单不用再付了”。
    """
    _configure(monkeypatch)
    owner = await make_user("alicosed")
    inv = await _make_pending_invoice(owner["user_id"])
    before = await _subscription_of(owner["user_id"])

    r = await _post_notify(
        client,
        _signed_form(
            **_paid_notify(
                inv["trade_no"], trade_status="TRADE_CLOSED", total_amount="2990.00"
            )
        ),
    )
    assert r.text.strip() == "success", (
        f"交易已关闭是**终态**，应回 success 让它别再重投：{r.status_code} {r.text!r}"
    )
    assert (await _invoice_row(inv["id"]))["status"] == "expired", (
        "交易已关闭却没有把 pending 账单收口 —— 列表页会一直显示“待支付”"
    )
    assert await _subscription_of(owner["user_id"]) == before, "关闭的交易不得改动订阅"


async def test_intermediate_status_does_nothing(client, make_user, monkeypatch):
    """`WAIT_BUYER_PAY` 等中间态：回 success，但账单仍是 pending、订阅不动。

    ★ 中间态**必须**回 success（否则支付宝会为重投一个“还没付钱”的状态
      反复打扰我们），但绝不能顺手开通 —— 钱还没到。
    """
    _configure(monkeypatch)
    owner = await make_user("aliwait")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await _post_notify(
        client,
        _signed_form(
            **_paid_notify(inv["trade_no"], trade_status="WAIT_BUYER_PAY")
        ),
    )
    assert r.text.strip() == "success", r.text
    assert (await _invoice_row(inv["id"]))["status"] == "pending", (
        "★ 中间态被当成了已付款 —— 钱还没到就开权限（两段式白做了）。"
    )
    sub = await _subscription_of(owner["user_id"])
    assert sub.get("plan_id") != 2, "中间态开通了套餐"


# ============================================================================
# 7. 未知订单：**继续重投**（给我们修正窗口）
# ============================================================================

async def test_unknown_order_is_nacked_so_alipay_keeps_retrying(
    client, make_user, monkeypatch
):
    """账单不存在 ⇒ 回非 success（404），让支付宝重投。

    ★ 这条判据容易被写成“找不到就回 success 免得它烦我们” —— 那是错的：
      找不到通常意味着我们的库正处在迁移 / 恢复 / 回滚的中间态。
      回 success 之后这笔钱在支付宝侧已结清、在我们侧没有记录，
      只能等用户投诉；回 404 则等环境恢复后自动补上。
    """
    _configure(monkeypatch)
    await make_user("aliunknown")   # 有个真人，但通知里的订单号不属于任何账单

    r = await _post_notify(
        client,
        _signed_form(**_paid_notify("SUB" + uuid.uuid4().hex[:28].upper())),
    )
    assert r.status_code == 404, f"未知订单应得 404，实际 {r.status_code}"
    assert r.text.strip() != "success", (
        "★ 找不到账单却回了 success —— 这笔钱从此在两侧都无人认领，"
        "只能等用户投诉。"
    )


# ============================================================================
# 8. 二维码 / 待支付端点（含归属校验）
# ============================================================================

async def test_qr_endpoint_renders_svg_data_uri(client, make_user, monkeypatch):
    """`GET /billing/payment/qr/{id}` 必须返回可直接塞进 `<img src>` 的数据 URI。

    ★ 判据不只是 200：前端拿它直接渲染，格式不对就是
      “图片裂了”，而接口本身是成功的（假成功）。
    """
    _configure(monkeypatch)
    owner = await make_user("aliqr")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await client.get(
        f"/api/v1/billing/payment/qr/{inv['id']}", headers=owner["headers"]
    )
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    uri = r.json()["qr_svg"]
    assert uri.startswith("data:image/svg+xml;base64,"), (
        f"不是可直接渲染的 SVG data URI：{uri[:60]!r}"
    )
    assert len(uri) > 500, f"data URI 太短（{len(uri)}），可能二维码没生成出来"


async def test_foreign_invoice_is_indistinguishable_from_missing(
    client, make_user, monkeypatch
):
    """别人的账单与不存在的账单必须**同一响应**（含逐字相同的文案）。

    ★ 为什么这条是安全判据而不是“体验优化”：
      若“不属于你”回 403 而“不存在”回 404，那么任何登录用户都可以
      拿 invoice_id 逐个试 —— 403 告诉你“这个 id 真实存在”，
      于是可以枚举全平台的账单（数量、金额、下单时间都能借此推断）。
      ⇒ 两个分支必须合并成同一个 404。

    ★ 反向注入：qr 端点把归属校验去掉（只按 invoice_id 查）
      ⇒ 第一条断言转红（拿到别人的二维码 = 可以让别人替你“付错单”）。
    """
    _configure(monkeypatch)
    a = await make_user("alia")
    b = await make_user("alib")
    inv = await _make_pending_invoice(a["user_id"])

    mine = await client.get(
        f"/api/v1/billing/payment/{inv['id']}", headers=a["headers"]
    )
    assert mine.status_code == 200, f"本人查自己的账单应 200：{mine.status_code}"

    foreign = await client.get(
        f"/api/v1/billing/payment/{inv['id']}", headers=b["headers"]
    )
    missing_id = str(uuid.uuid4())
    missing = await client.get(
        f"/api/v1/billing/payment/{missing_id}", headers=b["headers"]
    )

    assert foreign.status_code == 404, (
        f"★ 别人的账单返回了 {foreign.status_code} —— "
        f"这等于告诉调用方“这个 id 真实存在”，可用来枚举全平台账单。"
    )
    assert missing.status_code == 404
    assert foreign.json() == missing.json(), (
        f"★ 「别人的账单」与「不存在的账单」响应体不同：\n"
        f"  别人的：{foreign.json()}\n  不存在的：{missing.json()}\n"
        f"  两个分叉必须合并成同一个 404（含逐字相同的文案）。"
    )

    # 二维码端点同一口径
    qr_foreign = await client.get(
        f"/api/v1/billing/payment/qr/{inv['id']}", headers=b["headers"]
    )
    assert qr_foreign.status_code == 404, (
        f"★ 拿到了别人的收款二维码（{qr_foreign.status_code}）—— "
        f"二维码是**收款凭据**，泄露它等于让别人替这笔单付款。"
    )


# ============================================================================
# 9. 时间口径：进 JSON 的时间必须带时区偏移（**覆盖整个 billing 模块**）
# ============================================================================
#
# ★ 为什么守在这里：**支付倒计时读的就是 `expires_at`**，它由
#   `modules/billing/payments.py::pending_payment_payload` 产出。
#   若那里用裸 `.isoformat()`（naive-UTC ⇒ 输出无偏移），浏览器 `new Date()`
#   会按**本地时区**解析 ⇒ UTC+8 下整体偏 8 小时 ⇒ 30 分钟的倒计时
#   **一打开就显示"已过期"**。
#   而金额、状态、账单号全都是对的 —— 没有任何一条业务断言会顺带把它测出来。
#
# ★ 纯函数判据在 `tests/test_timefmt.py`；本节守的是**响应体真的带上偏移了**。

def _assert_aware(s: str, label: str) -> datetime:
    """断言 `s` 是一条**无歧义**的 RFC3339 字符串，并返回解析结果。"""
    assert s, f"{label} 是空的"
    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None, (
        f"★ {label} 没有时区偏移（{s!r}）⇒ 浏览器 new Date() 会按**本地时区**解析，"
        f"UTC+8 下整体偏 8 小时。支付倒计时会一打开就显示「已过期」。"
        f"根因：用了裸 .isoformat()，应改走 core.timefmt.utc_iso。"
    )
    assert dt.utcoffset() == timedelta(0), f"{label} 不是 UTC：{s!r}"
    return dt


async def test_polling_endpoint_timestamps_are_unambiguous(client, make_user, monkeypatch):
    """轮询端点（倒计时的**唯一**数据源）的时间戳必须带偏移、剩余时间也必须合理。"""
    _configure(monkeypatch)
    owner = await make_user("alitz1")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await client.get(
        f"/api/v1/billing/payment/{inv['id']}", headers=owner["headers"]
    )
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    pay = r.json()["payment"]

    _assert_aware(pay["created_at"], "payment.created_at")
    expires = _assert_aware(pay["expires_at"], "payment.expires_at")

    # ★ 只判"带没带偏移"还不够 —— 还要判「由它算出的倒计时是正数且不超过 TTL」。
    #   这一条把两个都会让用户看到"刚打开就过期"的二维码的原因一起钉住：
    #   ① 时区序列化错；② 我们的 TTL 与支付宝侧 `timeout_express` 分叉了。
    remaining = expires - datetime.now(timezone.utc)
    assert timedelta(0) < remaining <= timedelta(minutes=PENDING_PAYMENT_TTL_MINUTES), (
        f"★ 由 expires_at 算出的剩余时间不合理：{remaining}"
        f"（TTL={PENDING_PAYMENT_TTL_MINUTES} 分钟）—— 要么时区错了，要么 TTL 分叉了"
    )


async def test_pending_endpoint_timestamps_are_unambiguous(client, make_user, monkeypatch):
    """「刷新页面后恢复二维码」那条路径（`/payment/pending`）必须同一口径。"""
    _configure(monkeypatch)
    owner = await make_user("alitz2")
    await _make_pending_invoice(owner["user_id"])

    r = await client.get("/api/v1/billing/payment/pending", headers=owner["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    pay = r.json()["payment"]
    assert pay is not None, "刚落的 pending 账单没被查出来 —— 后面的断言会变成空跑"
    _assert_aware(pay["created_at"], "pending.created_at")
    _assert_aware(pay["expires_at"], "pending.expires_at")


async def test_paid_invoice_timestamps_are_unambiguous(client, make_user, monkeypatch):
    """`paid_at` 只在支付完成后才出现 —— 也必须带偏移（前端要显示付款时间）。

    ★ 这条**必须**真的走一遍 webhook：`paid_at` 在未支付时是 `None`，
      只测 pending 路径永远碰不到它（"两条路径只测一条"的典型漏法）。
    """
    _configure(monkeypatch)
    owner = await make_user("alitz3")
    inv = await _make_pending_invoice(owner["user_id"])

    r = await _post_notify(client, _signed_form(**_paid_notify(inv["trade_no"])))
    assert r.status_code == 200 and r.text == "success", f"{r.status_code} {r.text}"

    got = await client.get(
        f"/api/v1/billing/payment/{inv['id']}", headers=owner["headers"]
    )
    assert got.status_code == 200, f"{got.status_code} {got.text}"
    pay = got.json()["payment"]
    assert pay["status"] == "paid", f"回调没把账单结算成 paid：{pay['status']}"

    paid_at = _assert_aware(pay["paid_at"], "payment.paid_at")
    # ★ 断言用**确定值**而不是"大约等于现在"：
    #   `_paid_notify` 的 `gmt_payment` 固定是 `2026-09-25 18:30:00`（东八区），
    #   换算成 UTC 就是 10:30:00。写死这个确定时刻，"时区算错/丢偏移"
    #   会被精确定位；而"跟现在差得不大"这种模糊判据在有真实时钟的机器上
    #   既可能放过 8 小时偏差，也可能因固定日期而恒红（本用例第一版就踩了这个）。
    assert paid_at == datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc), (
        f"★ paid_at 是 {paid_at}，不等于 gmt_payment（18:30 东八区）换算出的 "
        f"2026-09-25T10:30:00+00:00 —— 要么序列化丢了时区偏移，要么东八区→UTC 算错了"
    )


async def _subscribe(client, headers, plan_id: str = "2", cycle: str = "yearly"):
    """走真实下单端点 —— **带** Authorization 头（与 `_post_notify` 恰好相反）。

    ★ 与 `tests/test_billing_payment.py` 里同名辅助的区别：那个用 pytest 夹具
      的 `auth_headers`；这里保持本文件"夹具自足"的风格，签名一致以便对照。
    """
    return await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": plan_id, "billing_cycle": cycle},
        headers=headers,
    )


async def test_subscription_and_invoice_timestamps_are_unambiguous(
    client, auth_on, user, auth_headers
):
    """订阅与账单列表的时间戳同样必须带偏移。

    ★ 本节虽然住在「支付宝」这个文件里，但覆盖的是 `modules/billing/` 的
      **全部** 8 个时间输出点（`subscription.period.*` / `created_at` /
      `invoices.*.issued_at|paid_at`）。放在这里的原因很实际：待支付账单的
      夹具在本文件，**复用夹具优于复制夹具** —— 复制的夹具会随真实表结构
      漂移，而漂移的那一份没人跑。
    """
    r = await _subscribe(client, auth_headers, "2", "yearly")
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.json().get("charged") is True, (
        "前置不成立：本用例要在**同步形态**下看时间序列化（演示/ mock 直通）"
    )

    got = await client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert got.status_code == 200, f"{got.status_code} {got.text}"
    sub = got.json()["subscription"]

    _assert_aware(sub["created_at"], "subscription.created_at")
    start = _assert_aware(sub["period"]["start"], "subscription.period.start")
    end = _assert_aware(sub["period"]["end"], "subscription.period.end")
    span = end - start
    assert timedelta(days=360) < span < timedelta(days=370), (
        f"★ 年付周期跨度是 {span}，不像一年 —— 时间戳的**时刻**被算错了"
        f"（不只是格式问题）。裸 isoformat() 不会造成这个，但时区误算会。"
    )

    inv = await client.get("/api/v1/billing/invoices", headers=auth_headers)
    assert inv.status_code == 200, f"{inv.status_code} {inv.text}"
    rows = inv.json()["invoices"]
    assert rows, "订阅成功却没写出账单 —— 后面的断言会变成空跑"
    row = rows[0]
    assert row["status"] == "paid", f"刚扣完款账单不是 paid：{row['status']}"
    _assert_aware(row["issued_at"], "invoice.issued_at")
    _assert_aware(row["paid_at"], "invoice.paid_at")


def test_aware_check_is_not_vacuous():
    """**自检**：`_assert_aware` 对无偏移的字符串必须报警。

    ★ 为什么必须有这条：本节前面几条判据的**全部力度**都压在 `_assert_aware`
      上。若这个辅助函数写成"看不出来就放过"（比如误写成 `if s and ...`、
      或把 `tzinfo is None` 判反），那么无论生产代码怎么退化，前几条都恒绿 ——
      门禁变成装饰。
      这条用**当场构造的违规样本**喂给它，证明它真会报警。
    """
    naive = datetime(2026, 9, 25, 12, 0).isoformat()
    assert "+" not in naive and "Z" not in naive, (
        f"自检前提不成立：{naive!r} 自带偏移，这条自检会退化为空跑"
    )
    with pytest.raises(AssertionError, match="没有时区偏移"):
        _assert_aware(naive, "selfcheck")

    # 正向对照：带偏移的必须**通过**（否则辅助函数成了"恒报警"，本节恒红）
    ok = _assert_aware("2026-09-25T12:00:00+00:00", "selfcheck")
    assert ok.utcoffset() == timedelta(0)

    # `None` / 空串要报"是空的"，不能静默通过
    with pytest.raises(AssertionError, match="是空的"):
        _assert_aware(None, "selfcheck")

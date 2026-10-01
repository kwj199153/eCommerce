r"""Amazon SP-API 按店 OAuth 授权链路 —— 纯逻辑层（第 351 轮 · P0-6）

==============================================================================
★ 为什么必须有这个模块（缺陷形态：契约与表都在，就是没有实现）
==============================================================================
`models/amazon_sp.py` 早就**声明**了完整契约：
    `CredentialStatus` / `AuthUrlResponse` / `OAuthCallbackRequest` /
    `AmazonCredentialCreate` / `AmazonCredentialResponse` /
    `AmazonCredentialDetail` / `AuthLogResponse`
`modules/amazon_sp/db_model.py` 也建好了两张表：
    `amazon_credentials`（LWA token + 卖家身份 + 刷新状态）
    `amazon_auth_logs`（授权全链路审计）
两张表**已在 baseline 迁移里**（`0d44a915bbb8` 第 222 / 264 行）。

但全仓 `grep -rn "amazon_credentials\|AmazonCredential\|AmazonAuthLog"` 的
命中**只有**：迁移文件、ORM 定义、Pydantic 定义、一个 mock 数据生成脚本 ——
**没有任何 router / service / 工具消费它们**。
⇒ 表是死的，契约是「声明承诺」，卖家永远无法在界面上完成一次授权，
   `sp_api_source.fetch_credentials()` 里那句注释（「真实场景凭据由 SP-API
   授权流程写入 amazon_credentials 表」）描述的是一个**不存在的流程**。

==============================================================================
★ 授权链路（Amazon SP-API 官方四步）
==============================================================================
  1. **我方生成授权 URL**，把卖家送到 Seller Central 的同意页：
         {auth_base}/apps/authorize/consent?application_id=<LWA client_id>
                                        &state=<签名串>&version=beta
     ★ `application_id` **就是** LWA Client ID（形如
       `amzn1.application-oa2-client.xxxx`），不是另一个值 —— 所以本模块
       不新增配置项，直接复用 `config.spapi_lwa_client_id`。
  2. 卖家点「授权」⇒ Amazon 带着 `spapi_oauth_code` 回调我们的 redirect_uri，
     并在 query 里**原样回传**第 1 步放进去的 `state`。
  3. 我方用该 code 去 LWA 端点换 `refresh_token`（长期有效，除非卖家撤销）。
  4. 每次调用 SP-API 前用 refresh_token 换 1 小时有效的 access_token。

  ★ 第 4 步在 `platforms/amazon/sp_api/auth.py::SPAPIClientAuth` 里**已有实现**，
    但那份实现**只从进程 settings 读一个全局 refresh_token**
    （`config.spapi_refresh_token`）——语义是「全进程只能连一个卖家」。
    本模块不重写签名/刷新算法，只补两个它没有的东西：
      · `grant_type=authorization_code`（首次换 refresh_token，auth.py 没有）；
      · **按店**取 refresh_token（从 `amazon_credentials` 表，而不是全局 settings）。

==============================================================================
★ 为什么 state 必须签名（而不是一个随机串）
==============================================================================
    回调请求**不带 Authorization 头** —— 它是 Amazon 的服务器发起的浏览器
    跳转，没有任何属于我方的凭据。所以这一步的「认证」只能落在 state 上。

    若 state 只是随机串、且由服务端存着（session / Redis），仍然缺少
    **完整性**：攻击者可以拿自己的 cookie 发起授权、拿到自己的 state，
    再把回调 URL 改一改骗受害者点开 ⇒ 受害者点的是自己的账号，但授权码
    被绑到攻击者那一侧（授权 CSRF / 账号绑架）。

    这里改用 **HMAC-SHA256 签名 + 时间戳**，让 state 自证：
      · 能验真伪（签名对不上 ⇒ 400）；
      · 能验时效（签发超过 `STATE_TTL_SECONDS` ⇒ 400）；
      · 能验绑定（解出的 store_id / user_id 就是当初签发时的那两个）；
      · **不依赖服务端会话** ⇒ 多实例部署天然可用。

==============================================================================
★ 密钥来源：复用 `config.credentials_encryption_key`
==============================================================================
    本项目唯一的服务端密钥就是它（Fernet key，`core/security/credentials.py`
    的唯一真源）。而 OAuth 落库时**本来就必须**有它 —— 没有这个 key，
    `encrypt_credentials()` 会拒绝写入（该模块的既有判据：宁可拒绝写入，
    也不明文落库）。所以这里不为签名单开一个配置项：多一个 secret 就多一个
    忘记轮换的地方，而它保护的东西与凭据加密是同一个信任域。

==============================================================================
★ 单值加解密：`seal_value` / `open_value`
==============================================================================
    `core/security/credentials.py` 的入口是 **dict 级**（`encrypt_credentials`
    收 dict、`decrypt_credentials` 返 dict），而 `amazon_credentials` 表的
    `refresh_token` / `access_token` 两列是**单值 Text**。
    这里把单值包成 `{"v": <value>}` 再走同一个入口 —— 而不是绕开它直接用
    Fernet：那样会多出一份「读写密文」的实现，而本仓判据是
    「同一能力两份实现 ⇒ 至少一份永远测不到」。包一层 dict 的代价可以忽略，
    换来的是：前缀校验（`enc:v1:`）、缺密钥拒绝、明文检测**全部只有一份**。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional, Tuple
from urllib.parse import quote

import httpx

from core.security.credentials import (
    CredentialsKeyMissing,
    CredentialsNotEncryptedError,
    decrypt_credentials,
    encrypt_credentials,
    is_encrypted,
)


# ============================================================
# 常量
# ============================================================

#: 授权同意页的默认基址（北美站）。
#: ★ 欧洲 / 远东站的域名不同 ⇒ 用 `SPAPI_AUTH_BASE_URL` 覆盖，
#:   而**不在本模块写第二份站点清单**（站点清单的真源是
#:   `platforms/amazon/sp_api/models.py` 的 marketplace 表）。
DEFAULT_AUTHORIZE_BASE = "https://sellercentral.amazon.com"

#: state 的有效期（秒）。10 分钟足够卖家在同意页上完成操作，
#: 又不至于让一个被抓到的 state 长期可用。
STATE_TTL_SECONDS = 600

#: 单次 LWA 调用超时（秒）。
LWA_TIMEOUT_SECONDS = 15.0


# ============================================================
# 异常
# ============================================================

class SpApiOAuthNotConfigured(RuntimeError):
    """SP-API 应用凭据未配置 ⇒ 无法发起授权（**配置问题**，映射 503）。

    与「卖家凭据不对」严格区分：前者是服务端漏配（用户改什么参数都没用，
    运维该去补 .env），后者是用户该去检查卖家中心。混成一个错误会让
    用户反复修改一个本来没错的东西，而真因被完全掩盖 ——
    这与 `core/security/credentials.py::ensure_key_available` 的既有判据同源。
    """


class SpApiOAuthError(RuntimeError):
    """与 Amazon LWA 端点交互失败（网络 / 4xx / 5xx / 响应缺字段）。"""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Any = None,
    ) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


class SpApiStateError(ValueError):
    """state 非法 / 被篡改 / 已过期 / 与店铺不匹配 ⇒ 拒绝回调（映射 400）。

    ★ 故意**不区分**「签名错」与「过期」：给攻击者一个可以二分探测的
      错误面没有收益（合法用户两种情况下要做的事完全一样：重新发起授权）。
    """


# ============================================================
# 配置读取（延迟导入：避免在 import 期就把 config 拉起来）
# ============================================================

def _settings():
    """延迟取全局配置 —— 让测试可以 monkeypatch 后再调用。"""
    from core.config import config
    return config


def lwa_token_url() -> str:
    """LWA 令牌端点。

    ★ 唯一真源是 `LWACredentials.auth_url` 的默认值 —— 这里**绝不**另写一份
      字面量。与 `modules/stores/connect/platforms/amazon.py::_lwa_auth_url()`
      同判据：同一个 URL 写两份，改一份就会有一处静默失效。
    """
    from platforms.amazon.sp_api.auth import LWACredentials
    return LWACredentials().auth_url


def _lwa_credentials() -> Tuple[str, str]:
    """返回 (client_id, client_secret)。"""
    cfg = _settings()
    return (
        (getattr(cfg, "spapi_lwa_client_id", "") or "").strip(),
        (getattr(cfg, "spapi_lwa_client_secret", "") or "").strip(),
    )


def authorize_base_url() -> str:
    """授权同意页的基址（`SPAPI_AUTH_BASE_URL`，缺省北美站）。"""
    cfg = _settings()
    base = (getattr(cfg, "spapi_auth_base_url", "") or "").strip()
    return (base or DEFAULT_AUTHORIZE_BASE).rstrip("/")


# ============================================================
# state：签名 / 校验
# ============================================================

def _signing_key() -> bytes:
    """签名密钥 = `SHOP_CREDENTIALS_ENCRYPTION_KEY`（理由见模块头）。"""
    raw = (getattr(_settings(), "credentials_encryption_key", "") or "").strip()
    if not raw:
        raise CredentialsKeyMissing(
            "未配置 SHOP_CREDENTIALS_ENCRYPTION_KEY，无法签发 OAuth state"
            "（该密钥同时用于加密落库的 refresh_token，缺它则整条授权链路不可用）"
        )
    return raw.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str) -> str:
    digest = hmac.new(
        _signing_key(), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return _b64e(digest[:16])


def build_state(store_id: str, user_id: str, *, now: Optional[float] = None) -> str:
    """签发 state：`base64(payload).base64(hmac)`。

    Raises:
        ValueError: store_id / user_id 为空 —— **硬拒绝**，不签一个无主的 state。
            本仓判据：写路径缺值必须硬拒绝（空 store_id 会让回调落库时
            撞外键，最终伪装成「数据库不可用」= 归因错方向）。
        CredentialsKeyMissing: 未配置签名密钥。
    """
    sid = (store_id or "").strip()
    uid = (user_id or "").strip()
    if not sid:
        raise ValueError("签发 state 需要非空 store_id")
    if not uid:
        raise ValueError("签发 state 需要非空 user_id")

    issued = int(now if now is not None else time.time())
    payload = f"{sid}|{uid}|{issued}"
    return f"{_b64e(payload.encode('utf-8'))}.{_signature(payload)}"


def parse_state(state: str, *, now: Optional[float] = None) -> Tuple[str, str]:
    """验签并解出 `(store_id, user_id)`。

    Raises:
        SpApiStateError: 格式错 / 签名错 / 已过期 / 字段为空。
    """
    raw = (state or "").strip()
    if not raw or "." not in raw:
        raise SpApiStateError("state 缺失或格式不合法")

    encoded, _, signature = raw.partition(".")
    if not encoded or not signature:
        raise SpApiStateError("state 缺失或格式不合法")

    try:
        payload = _b64d(encoded).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 —— 任何解码失败都归为「state 非法」
        raise SpApiStateError("state 无法解码") from exc

    expected = _signature(payload)
    # ★ 用 `compare_digest` 而不是 `==`：后者在首个不同字节就返回，
    #   时间差可以被用来逐字节爆破签名（本仓安全面的一贯要求）。
    if not hmac.compare_digest(expected, signature):
        raise SpApiStateError("state 签名不匹配（可能被篡改或来自其它环境）")

    parts = payload.split("|")
    if len(parts) != 3:
        raise SpApiStateError("state 载荷字段数不对")

    store_id, user_id, issued_raw = parts
    if not store_id or not user_id:
        raise SpApiStateError("state 载荷缺少店铺或用户标识")

    try:
        issued = int(issued_raw)
    except ValueError as exc:
        raise SpApiStateError("state 载荷的时间戳不合法") from exc

    reference = now if now is not None else time.time()
    if reference - issued > STATE_TTL_SECONDS:
        raise SpApiStateError("state 已过期，请重新发起授权")
    if issued - reference > STATE_TTL_SECONDS:
        # 未来时间戳 ⇒ 时钟异常或人为构造；同样拒绝（不给「时间旅行」留口子）。
        raise SpApiStateError("state 时间戳不在允许区间内")

    return store_id, user_id


def build_authorize_url(state: str) -> str:
    """拼出卖家同意页的跳转 URL。

    Raises:
        SpApiOAuthNotConfigured: 未配置 LWA Client ID（= application_id）。
    """
    client_id, _ = _lwa_credentials()
    if not client_id:
        raise SpApiOAuthNotConfigured(
            "未配置 SPAPI_LWA_CLIENT_ID，无法生成 Amazon 授权链接。"
            "请在卖家中心「开发应用」创建应用后，把 LWA Client ID 写入 .env。"
        )
    return (
        f"{authorize_base_url()}/apps/authorize/consent"
        f"?application_id={quote(client_id, safe='')}"
        f"&state={quote(state, safe='')}"
        f"&version=beta"
    )


# ============================================================
# LWA 令牌交换
# ============================================================

async def _post_lwa(payload: Dict[str, str]) -> Dict[str, Any]:
    """POST 到 LWA 令牌端点，返回解析后的 JSON。"""
    try:
        async with httpx.AsyncClient(timeout=LWA_TIMEOUT_SECONDS) as client:
            response = await client.post(
                lwa_token_url(),
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.text
        except Exception:  # noqa: BLE001 —— 取不到 body 不影响错误归类
            body = ""
        raise SpApiOAuthError(
            f"LWA 令牌交换失败：HTTP {exc.response.status_code}",
            code=f"HTTP_{exc.response.status_code}",
            details=body[:500],
        ) from exc
    except httpx.HTTPError as exc:
        raise SpApiOAuthError(f"LWA 令牌交换异常：{exc}") from exc


async def exchange_authorization_code(code: str) -> Dict[str, Any]:
    """用回调拿到的 `spapi_oauth_code` 换长期 `refresh_token`。

    ★ 这是 `SPAPIClientAuth` **没有**的那一步（它只会用已有的 refresh_token
      换 access_token）。授权码是**一次性**的：换过一次再换会被 Amazon 拒绝。

    Returns:
        LWA 响应 dict，至少含 `refresh_token`；通常还有 `access_token` /
        `expires_in` / `token_type`。
    """
    plain = (code or "").strip()
    if not plain:
        raise SpApiStateError("授权码为空")

    client_id, client_secret = _lwa_credentials()
    if not (client_id and client_secret):
        raise SpApiOAuthNotConfigured(
            "未配置 SPAPI_LWA_CLIENT_ID / SPAPI_LWA_CLIENT_SECRET，无法用授权码换取令牌。"
        )

    data = await _post_lwa(
        {
            "grant_type": "authorization_code",
            "code": plain,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    if not data.get("refresh_token"):
        raise SpApiOAuthError(
            "LWA 响应里没有 refresh_token（授权码可能已被使用过或已过期）",
            code="REFRESH_TOKEN_MISSING",
            details=data,
        )
    return data


async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """用长期 refresh_token 换 1 小时有效的 access_token。"""
    plain = (refresh_token or "").strip()
    if not plain:
        raise SpApiStateError("refresh_token 为空")

    client_id, client_secret = _lwa_credentials()
    if not (client_id and client_secret):
        raise SpApiOAuthNotConfigured(
            "未配置 SPAPI_LWA_CLIENT_ID / SPAPI_LWA_CLIENT_SECRET，无法刷新令牌。"
        )

    data = await _post_lwa(
        {
            "grant_type": "refresh_token",
            "refresh_token": plain,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    if not data.get("access_token"):
        raise SpApiOAuthError(
            "LWA 响应里没有 access_token（refresh_token 可能已被卖家撤销）",
            code="ACCESS_TOKEN_MISSING",
            details=data,
        )
    return data


# ============================================================
# 单值加解密（包一层 dict 走凭据模块的唯一入口）
# ============================================================

#: `encrypt_credentials` 要求 dict —— 单值统一放在这个键下。
_VALUE_KEY = "v"


def seal_value(value: Optional[str]) -> Optional[str]:
    """把单个敏感值加密成可入库字符串。空值原样返回 `None`。"""
    raw = (value or "").strip()
    if not raw:
        return None
    return encrypt_credentials({_VALUE_KEY: raw})


def open_value(blob: Optional[str]) -> Optional[str]:
    """把库里存的密文解回单个字符串。空值返回 `None`。

    Raises:
        CredentialsNotEncryptedError: 列里存的是明文 —— **显式报错而不是返回 None**
            （返回 None 会把「凭证明文落库」这个安全事故伪装成「这家店没授权」）。
    """
    if not blob:
        return None
    if not is_encrypted(blob):
        raise CredentialsNotEncryptedError(
            "amazon_credentials 的 token 列里存的是明文，不是 core.security.credentials "
            "写下的密文。请先确认写入路径，再用一次性脚本加密回填。"
        )
    data = decrypt_credentials(blob) or {}
    value = data.get(_VALUE_KEY)
    return value if isinstance(value, str) and value else None


# ============================================================
# 时间工具
# ============================================================

def token_expiry(expires_in: Any, *, now: Optional[datetime] = None) -> Optional[datetime]:
    """把 LWA 的 `expires_in`（秒）换算成绝对到期时刻。

    ★ 落库用 **UTC naive**（`db_model` 的既有列全是 naive `DateTime`），
      这样与 `last_refresh_at` / `created_at` 的口径一致 —— 混用 aware/naive
      会让「剩余秒数」这类计算在跨时区时静默算错。
    """
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    base = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return base + timedelta(seconds=seconds)


# ============================================================
# 错误映射（router 共用一处，避免每个端点抄一遍 try/except）
# ============================================================

@contextmanager
def mapped_errors() -> Iterator[None]:
    """把本模块的异常翻译成 HTTP 状态码。

    ★ 503 / 502 / 400 三档刻意分开：
        · **503** = 服务端没配好（运维该动，用户改什么都没用）；
        · **502** = 上游 Amazon 拒绝或不可达（用户该检查凭据 / 稍后重试）；
        · **400** = 请求本身不合法（state 缺失 / 被篡改 / 过期）。
      混成一个 500 会让三类完全不同的处置意见变成同一句「服务器错误」。
    """
    from fastapi import HTTPException  # 局部导入：本模块的非 HTTP 部分（含测试）不依赖 fastapi

    try:
        yield
    except SpApiStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SpApiOAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CredentialsKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SpApiOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = [
    "DEFAULT_AUTHORIZE_BASE",
    "LWA_TIMEOUT_SECONDS",
    "STATE_TTL_SECONDS",
    "SpApiOAuthError",
    "SpApiOAuthNotConfigured",
    "SpApiStateError",
    "authorize_base_url",
    "build_authorize_url",
    "build_state",
    "exchange_authorization_code",
    "lwa_token_url",
    "mapped_errors",
    "open_value",
    "parse_state",
    "refresh_access_token",
    "seal_value",
    "token_expiry",
]

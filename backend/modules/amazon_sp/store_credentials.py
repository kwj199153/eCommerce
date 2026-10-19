"""按店凭据读取口 —— 「这家店该用哪把钥匙」的**唯一**判定处。

==============================================================================
★ 为什么必须有这个文件（第 386 轮）
==============================================================================
改造前，取数链是这样的（`sp_api_source.py` 构造函数）：

    self._config = config or SPAPIConfig()        # 空配置
    self._client = SPAPIClient(self._config)      # client 拿空配置自建 auth
    self._auth   = get_spapi_auth()               # 带环境的那个，赋值后再没被用过

`SPAPIClient` 的判断是 `SPAPIClientAuth(config) if config else get_spapi_auth()`，
而空的 `SPAPIConfig()` 是**真值**（dataclass 无 `__bool__`）⇒ 永远走「自建」，
那个真正带凭据的实例从未被调用。⇒ 第一次 `get_access_token()` 就抛
`REFRESH_TOKEN_MISSING`。**这条路径从来没有产出过一条真实数据**，一直被 mock
回退挡着，所以没人发现。

⇒ 本模块的职责不是「加多店支持」，而是**把 凭据 → 配置 → 客户端 这条链接上**，
   多店只是「按 store_id 查一行」的自然结果。

==============================================================================
★ 两类凭据必须分清楚（混在一起正是当初混乱的根源）
==============================================================================
| 东西 | 归属 | 存在哪 | 是否按店 |
|---|---|---|---|
| LWA `refresh_token` / `client_id` / `client_secret` | **卖家级**（授权来的） | OAuth 行 或 表单密文 | ✅ 按店 |
| AWS `access_key` / `secret_key` | **应用级**（我们自己的 IAM 用户） | `.env` / Settings | ❌ 全店共用 |

所以 OAuth 通道读不到 AWS 密钥是**正常的**，不是缺字段 —— 它本来就不该按店。
改造前把两者混成「SPAPI_* 一组环境变量」，才出现「所有店共用一把钥匙」。

==============================================================================
★ 取舍：为什么这里不缓存、不重试、不吞异常
==============================================================================
- **不缓存**：凭据是「哪家店能用」的判据，而判据一旦被缓存，撤销授权/换 token
  之后就会继续用旧的。token 本身的缓存放在 `SPAPIClientAuth`（它有失效时间，
  且 DB 里的 `access_token` 就是跨 worker 的那份缓存）。
- **不重试**：LWA 刷新失败的原因（401 / 卖家撤销 / 网络）必须原样上抛，
  由调用方决定是报 409 还是 502。这里重试会把「凭据失效」伪装成「偶发故障」。
- **不吞异常**：解密失败**显式上抛**。若静默当作「这家店没配过」，用户会重填一份
  新凭据，覆盖掉可能还能救回来的密文 —— 那是不可逆的数据损失。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import select

from core.database import async_session_factory
from core.security.credentials import decrypt_credentials

if TYPE_CHECKING:  # pragma: no cover
    from platforms.amazon.sp_api.auth import SPAPIConfig
    from platforms.amazon.sp_api.models import Marketplace

logger = logging.getLogger(__name__)

#: 复用的 access_token 至少还要剩这么久才直接用；否则宁可在本次调用里刷新。
#: 5 分钟与 `AccessToken.is_expired` 的提前量一致 —— 两处必须同口径，
#: 否则会出现「这里判有效、auth 那边判过期」的来回抖动。
TOKEN_REUSE_MARGIN = timedelta(minutes=5)

#: OAuth 行连续失败到这个次数就不再参与选择（`router.py` 的刷新失败会 +1）。
#: 为什么按 `error_count` 而不是直接排除所有非 active 行：授权刚完成但还没
#: 刷新过 token 的行是 `pending`，它其实可用 —— 真正说明「不可用」的是
#: 「刷新过且连续失败」。
MAX_OAUTH_ERROR_COUNT = 3

#: 表单凭据的字段名（与 `modules/stores/connect/platforms/amazon.py::fields()` 同源）。
FORM_FIELD_CLIENT_ID = "client_id"
FORM_FIELD_CLIENT_SECRET = "client_secret"
FORM_FIELD_REFRESH_TOKEN = "refresh_token"
FORM_FIELD_AWS_KEY = "aws_access_key"
FORM_FIELD_AWS_SECRET = "aws_secret_key"
FORM_FIELD_REGION = "region"
FORM_FIELD_SANDBOX = "use_sandbox"


# ============================================================================
# 异常：三种「拿不到钥匙」必须可区分
# ============================================================================
class StoreCredentialError(Exception):
    """凭据读取失败的基类。"""


class StoreNotConnected(StoreCredentialError):
    """该店铺没有可用的平台授权。

    ★ 这是**正常业务状态**，不是故障：客户建了店但还没走授权流程。
      调用方必须把它翻译成「该店铺未授权」的空态（HTTP 409 +
      `code=STORE_NOT_CONNECTED`），**绝不能**退化成 mock 数据或空列表：
      - 退化 mock ⇒ 给真实客户假数字，他会照着假数字补货（本仓铁律）；
      - 退化空列表 ⇒ 「有授权但没数据」与「压根没授权」变成同一句话，
        客户会以为同步出了问题，去查调度而不是去授权。
    """

    code = "STORE_NOT_CONNECTED"

    def __init__(
        self,
        store_id: str,
        detail: str = "",
        *,
        reason: str = "",
        store_is_demo: bool = False,
    ) -> None:
        self.store_id = store_id
        self.detail = detail
        self.reason = reason or "not_connected"
        #: 这家店是不是演示店 —— 由 `load_store_credential` 填。
        #: ★ 只给 `open_data_source` 判「演示档落 mock」用；**不是**「可以退回 mock」
        #:   的意思：还要 DEMO_MODE 也为真，两个条件缺一不可（见该函数注释）。
        self.store_is_demo = store_is_demo
        super().__init__(f"店铺 {store_id or '(空)'} 未授权：{detail}" if detail else
                         f"店铺 {store_id or '(空)'} 未授权")

    def to_payload(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "store_id": self.store_id,
            "reason": self.reason,
            "message": self.detail or "该店铺尚未完成平台授权",
        }


class UnsupportedMarketplace(StoreCredentialError):
    """市场不属于 `Marketplace` 枚举里的 10 个站点（SG / BR / IN / AE 等）。

    ★ 为什么宁可抛错也不默认 US：默认 US 会让「新加坡站的订单」被当成美国站
      去查，结果是**空数据且不报错** —— 现象是「这家店怎么没订单」，
      排查方向会完全跑偏（会去查授权、查同步，而不会想到站点映射错了）。
    """

    code = "UNSUPPORTED_MARKETPLACE"

    def __init__(self, store_id: str, raw: str = "") -> None:
        self.store_id = store_id
        self.raw = raw
        super().__init__(
            f"店铺 {store_id} 的站点 {raw or '(未知)'} 不在支持列表内"
            f"（当前仅支持 Marketplace 枚举里的 10 个站点）"
        )


# ============================================================================
# 返回值
# ============================================================================
@dataclass(frozen=True)
class StoreCredential:
    """一家店铺的完整取数能力（配置已组装好，数据源直接拿去用）。

    ★ `config` 里**已经**包含了该类凭据对应的 LWA 与 AWS 值 ——
      数据源不许再去读 `settings`，否则「按店」这件事会在第二处被绕过。
    """

    store_id: str
    #: "oauth" | "form" —— 诊断用，「这家店的数据到底是按哪条通道取的」必须可答
    source: str
    seller_id: str
    marketplace: "Marketplace"
    config: "SPAPIConfig"
    #: 库里存的 access_token（若还在有效期内）；None 表示本次调用需要刷新
    access_token: Optional[str] = None
    access_token_expires_at: Optional[datetime] = None
    #: 人类可读的来源说明（进日志与 `/amazon-sp/status`，不进前端业务接口）
    note: str = ""

    def snapshot(self) -> Dict[str, Any]:
        """**不含任何密文**的凭据元数据（供 `fetch_credentials()` 与状态端点）。

        ★ 这里刻意不返回 refresh_token 的任何形态（连 `"***"` 都不返回）：
          改造前那个 `fetch_credentials()` 返回 `"***"` 占位符，看起来像
          「有值但被打码」，实际调用方拿它做不了任何事，还容易让人以为
          凭据真的被读到了。**要么给真值（在服务端内部），要么就不给这个字段。**
        """
        return {
            "store_id": self.store_id,
            "source": self.source,
            "seller_id": self.seller_id,
            "marketplace_id": getattr(self.marketplace, "value", ""),
            "marketplace_name": getattr(self.marketplace, "name", ""),
            "region": getattr(getattr(self.config, "aws", None), "region", ""),
            "sandbox": bool(getattr(self.config, "use_sandbox", False)),
            "has_access_token": bool(self.access_token),
            "access_token_expires_at": (
                self.access_token_expires_at.isoformat() if self.access_token_expires_at else None
            ),
            "note": self.note,
        }


# ============================================================================
# 主入口
# ============================================================================
async def load_store_credential(
    store_id: str,
    *,
    prefer: str = "auto",
) -> StoreCredential:
    """解析出这家店该用的凭据（唯一读取口）。

    Args:
        store_id: `stores_store.id`（字符串，形如 `store_xxxx`）。
        prefer:
            - "auto"（默认）：**OAuth 优先 → 表单兜底**（决策①A）
            - "oauth"：只认 OAuth 行，没有就抛 `StoreNotConnected`
            - "form"：只认表单密文，没有就抛 `StoreNotConnected`

    Raises:
        StoreNotConnected: 店铺不存在 / 两条通道都没有可用凭据。
        UnsupportedMarketplace: 站点推不出来或不在枚举内。
        CredentialsKeyMissing / CredentialsNotEncryptedError / CredentialsDecryptError:
            凭据层故障 —— **原样上抛**，不许降级成「没配过」。
    """
    from core.stores.models import StoreRecord
    from modules.amazon_sp.db_model import AmazonCredential

    sid = (store_id or "").strip()
    if not sid:
        raise StoreNotConnected("", "缺少 store_id（按店取数不允许全局凭据）", reason="empty_store_id")

    async with async_session_factory() as db:
        store = (
            await db.execute(select(StoreRecord).where(StoreRecord.id == sid))
        ).scalar_one_or_none()
        if store is None:
            # 店铺不存在与「店铺存在但没授权」都用同一个异常：调用方对外的响应
            # 文案一致（「该店铺未授权」），不给「这家店存在吗」的枚举面。
            raise StoreNotConnected(sid, "店铺不存在或已删除", reason="store_not_found")

        oauth_row = (
            await db.execute(
                select(AmazonCredential).where(AmazonCredential.store_id == sid)
            )
        ).scalar_one_or_none()

        form_creds = _read_form_credentials(store)
        oauth_creds = _read_oauth_credentials(oauth_row)

    try:
        chosen_source = _choose_source(
            sid, oauth_creds=oauth_creds, form_creds=form_creds, prefer=prefer
        )
    except StoreNotConnected as exc:
        # ★ 把「是不是演示店」带到异常上：`open_data_source` 要用它判
        #   「演示档落 mock」还是「真实客户硬失败」。多查一次 DB 不值当，
        #   而把 is_demo 做成模块级缓存又会在建店后失效 —— 挂在异常上最省。
        exc.store_is_demo = bool(getattr(store, "is_demo", False))
        raise

    creds = oauth_creds if chosen_source == "oauth" else form_creds
    assert creds is not None  # `_choose_source` 已保证

    # 两条通道都命中且 refresh_token 不同 ⇒ 记一条 warning，**不静默选一个**
    if oauth_creds and form_creds:
        if oauth_creds["refresh_token"] != form_creds["refresh_token"]:
            logger.warning(
                "店铺 %s 同时存在 OAuth 与表单两套授权且 refresh_token 不一致；"
                "本次按 prefer=%s 取 %s（OAuth 行 updated=%s / 表单 updated=%s）。"
                "两套并存时请择一保留，否则「用的是哪把钥匙」无法复核。",
                sid, prefer, chosen_source,
                oauth_creds.get("updated_at"), form_creds.get("updated_at"),
            )

    marketplace = _resolve_marketplace(
        sid,
        participant_id=(oauth_row.marketplace_participant_id if oauth_row else None),
        store_marketplace_id=getattr(store, "marketplace_id", None),
        store_region_code=getattr(store, "region_code", None),
    )

    config = _build_config(sid, creds, source=chosen_source)

    access_token, expires_at = _reusable_access_token(oauth_row if chosen_source == "oauth" else None)

    return StoreCredential(
        store_id=sid,
        source=chosen_source,
        seller_id=str(creds.get("seller_id") or ""),
        marketplace=marketplace,
        config=config,
        access_token=access_token,
        access_token_expires_at=expires_at,
        note=creds.get("note", ""),
    )


# ============================================================================
# 两条通道的读取（各自只做「把行/密文变成 dict」，不做优先级判断）
# ============================================================================
def _read_form_credentials(store) -> Optional[Dict[str, Any]]:
    """表单通道：`stores_store.api_credentials` 的 Fernet 密文 → dict。

    ★ 解密失败**上抛**（不返回 None）：见模块 docstring 最后一条。
    ★ 缺字段（老版本连接时只存了部分字段）按「这条通道不可用」处理并记 warning，
      因为拿一份残缺配置去取数只会在 LWA 那一步 400，晚失败不如早失败。
    """
    blob = getattr(store, "api_credentials", None)
    if not blob:
        return None

    data = decrypt_credentials(blob) or {}
    missing = [
        name
        for name, key in (
            ("LWA Client ID", FORM_FIELD_CLIENT_ID),
            ("LWA Client Secret", FORM_FIELD_CLIENT_SECRET),
            ("Refresh Token", FORM_FIELD_REFRESH_TOKEN),
        )
        if not str(data.get(key) or "").strip()
    ]
    if missing:
        logger.warning(
            "店铺 %s 的表单凭据缺少必需字段(%s)，该通道不参与选择；"
            "请重新连接并补全后重试",
            getattr(store, "id", "?"), "、".join(missing),
        )
        return None

    return {
        "client_id": str(data.get(FORM_FIELD_CLIENT_ID) or "").strip(),
        "client_secret": str(data.get(FORM_FIELD_CLIENT_SECRET) or "").strip(),
        "refresh_token": str(data.get(FORM_FIELD_REFRESH_TOKEN) or "").strip(),
        # ★ AWS 是应用级凭据，表单里留空是合法的（走 .env 的应用级值）
        "aws_access_key": str(data.get(FORM_FIELD_AWS_KEY) or "").strip() or None,
        "aws_secret_key": str(data.get(FORM_FIELD_AWS_SECRET) or "").strip() or None,
        "region": str(data.get(FORM_FIELD_REGION) or "").strip() or None,
        "use_sandbox": _as_bool(data.get(FORM_FIELD_SANDBOX)),
        "seller_id": str(data.get("seller_id") or "").strip(),
        "updated_at": getattr(store, "updated_at", None),
        "note": "表单直填",
    }


def _read_oauth_credentials(row) -> Optional[Dict[str, Any]]:
    """OAuth 通道：`amazon_credentials` 行 → dict（token 用 `oauth.open_value` 解密）。

    ★ 可用性门槛（决策①A 的附加硬规则），三条缺一不可：
      1. `credential_status == "active"`
      2. `last_refresh_at` 非空 —— 授权回调写了行但**从没成功换过 token** 的行
         不算数（那种行连 refresh_token 是否被卖家撤销都还不知道）
      3. `error_count < MAX_OAUTH_ERROR_COUNT`
    这三条不是「保守」，是**唯一能表达「卖家撤销了授权」的地方** ——
    表单通道完全看不出这件事，会一直拿死 token 撞 401。
    """
    if row is None:
        return None

    from modules.amazon_sp.oauth import open_value

    status = str(getattr(row, "credential_status", "") or "").lower()
    error_count = int(getattr(row, "error_count", 0) or 0)
    if status != "active":
        return None
    if getattr(row, "last_refresh_at", None) is None:
        return None
    if error_count >= MAX_OAUTH_ERROR_COUNT:
        logger.warning(
            "店铺 %s 的 OAuth 行连续失败 %s 次，本轮不参与选择（请重新授权）",
            getattr(row, "store_id", "?"), error_count,
        )
        return None

    refresh_token = open_value(getattr(row, "refresh_token", None))
    if not refresh_token:
        return None

    from core.config import config as settings

    return {
        "client_id": str(getattr(settings, "spapi_lwa_client_id", "") or "").strip(),
        "client_secret": str(getattr(settings, "spapi_lwa_client_secret", "") or "").strip(),
        "refresh_token": refresh_token,
        # ★ AWS 是应用级的：OAuth 行里没有这个字段，从 Settings 取是**正确**的。
        "aws_access_key": None,
        "aws_secret_key": None,
        "region": str(getattr(row, "aws_region", "") or "").strip() or None,
        "use_sandbox": None,  # 由 Settings 决定
        "seller_id": str(getattr(row, "seller_id", "") or "").strip(),
        "updated_at": getattr(row, "updated_at", None),
        "note": "OAuth 授权",
    }


def _choose_source(
    store_id: str,
    *,
    oauth_creds: Optional[Dict[str, Any]],
    form_creds: Optional[Dict[str, Any]],
    prefer: str,
) -> str:
    """决策①：OAuth 优先 → 表单兜底。**优先级只在这一处判**。"""
    if prefer == "oauth":
        if oauth_creds:
            return "oauth"
        raise StoreNotConnected(store_id, "该店铺没有可用的 OAuth 授权", reason="oauth_missing")

    if prefer == "form":
        if form_creds:
            return "form"
        raise StoreNotConnected(store_id, "该店铺没有填写表单凭据", reason="form_missing")

    if prefer != "auto":
        raise ValueError(f"未知的 prefer={prefer!r}（只接受 auto / oauth / form）")

    if oauth_creds:
        return "oauth"
    if form_creds:
        return "form"

    raise StoreNotConnected(
        store_id,
        "该店铺尚未完成 Amazon 授权（请在「店铺设置 → 连接平台」里填写凭据或走 OAuth 授权）",
        reason="no_credentials",
    )


# ============================================================================
# 市场解析（决策：宁可抛错，绝不默认 US）
# ============================================================================
def _resolve_marketplace(
    store_id: str,
    *,
    participant_id: Optional[str],
    store_marketplace_id: Optional[str],
    store_region_code: Optional[str],
) -> "Marketplace":
    """按「participant_id → 店铺 marketplace_id → region_code」的顺序解析站点。

    这条顺序的依据是**精确度**：participant_id 是 SP-API 自己给的，一字不差；
    `marketplace_id` 是用户填的（可能填成 `amazon.com` 这类域名）；
    `region_code` 是店铺创建时顺手写的，最不可信（实测存量里出现过 `AMAZON`
    这种不是国家码的值）。
    """
    from platforms.amazon.sp_api.models import Marketplace

    # ★★ participant_id **是权威值**：它由 SP-API 自己给出，一字不差。
    #   它一旦存在却解析不出来，说明该站点不在支持范围内 —— 此时**不许**
    #   退回 `region_code` 去猜。猜出来的值更不可信，且会让「新加坡站被当成
    #   美国站查、返回 0 条且不报错」重新出现（那正是本函数要防的形态）。
    pid = str(participant_id or "").strip()
    if pid:
        try:
            return Marketplace(pid)
        except ValueError:
            raise UnsupportedMarketplace(store_id, raw=pid) from None

    for raw in (store_marketplace_id,):
        code = str(raw or "").strip()
        if not code:
            continue
        try:
            return Marketplace(code)
        except ValueError:
            # 也可能是 "US" / "us" 这种短码（用户手填的）
            try:
                return Marketplace[code.upper()]
            except KeyError:
                logger.debug("店铺 %s 的市场值 %r 不是 participant_id，继续往下推", store_id, raw)

    region = str(store_region_code or "").strip().upper()
    if region:
        try:
            return Marketplace[region]
        except KeyError:
            pass

    raise UnsupportedMarketplace(
        store_id,
        raw=participant_id or store_marketplace_id or store_region_code or "",
    )


# ============================================================================
# 组装 config（LWA 按店 + AWS 按应用）
# ============================================================================
def _build_config(store_id: str, creds: Dict[str, Any], *, source: str) -> "SPAPIConfig":
    """把两份凭据拼成一份 `SPAPIConfig`。

    ★ **应用级缺 AWS 密钥时抛错，不静默留空**：留空的结果是每个请求都被 SP-API
      以 403 拒绝，而错误信息里只有一句「SignatureDoesNotMatch」——
      排查会从「哪家店授权坏了」一路查到「AWS 密钥是不是没配」，
      方向完全错。宁可现在说明白。
    """
    from core.config import config as settings
    from platforms.amazon.sp_api.auth import AWSCredentials, LWACredentials, SPAPIConfig

    def _app_level(attr: str) -> str:
        return str(getattr(settings, attr, "") or "").strip()

    lwa = LWACredentials(
        client_id=creds.get("client_id") or _app_level("spapi_lwa_client_id"),
        client_secret=creds.get("client_secret") or _app_level("spapi_lwa_client_secret"),
        refresh_token=creds.get("refresh_token") or "",
    )
    if not lwa.client_id or not lwa.client_secret:
        raise StoreNotConnected(
            store_id,
            f"缺少 LWA 应用凭据（client_id / client_secret），无法为 {source} 通道组装客户端",
            reason="app_credentials_missing",
        )
    if not lwa.refresh_token:
        raise StoreNotConnected(store_id, "refresh_token 为空", reason="refresh_token_missing")

    aws = AWSCredentials(
        access_key=creds.get("aws_access_key") or _app_level("spapi_aws_access_key"),
        secret_key=creds.get("aws_secret_key") or _app_level("spapi_aws_secret_key"),
        region=creds.get("region") or _app_level("spapi_aws_region") or "us-east-1",
    )
    if not aws.access_key or not aws.secret_key:
        raise StoreNotConnected(
            store_id,
            "缺少 AWS 签名密钥（SPAPI_AWS_ACCESS_KEY / SPAPI_AWS_SECRET_KEY）——"
            "这是**应用级**凭据，不随店铺授权变化，需要运维配置",
            reason="aws_credentials_missing",
        )

    use_sandbox = creds.get("use_sandbox")
    if use_sandbox is None:
        use_sandbox = bool(getattr(settings, "spapi_use_sandbox", False))

    return SPAPIConfig(lwa=lwa, aws=aws, use_sandbox=bool(use_sandbox))


def _reusable_access_token(row) -> tuple[Optional[str], Optional[datetime]]:
    """DB 里的 `access_token` 还能用就直接用（决策③：DB 当缓存）。

    ★ 只读**这一条通道**的行：表单通道没有存 access_token 的地方，
      它的 token 一律由 auth 现场刷新 —— 这不是缺陷，是「表单通道只管
      refresh_token」的既定分工。
    ★ 剩余有效期不足 `TOKEN_REUSE_MARGIN` 就当作不可用（返回 None），
      交给 auth 去刷新 —— 这样「快过期的 token」不会在请求中途失效。
    """
    if row is None:
        return None, None

    from modules.amazon_sp.oauth import open_value

    expires_at = getattr(row, "token_expires_at", None)
    if expires_at is None:
        return None, None
    try:
        token = open_value(getattr(row, "access_token", None))
    except Exception as e:  # noqa: BLE001 - 解密失败不该阻断取数（refresh 仍可用）
        logger.warning("店铺 %s 的 access_token 解密失败，改为现场刷新: %s",
                       getattr(row, "store_id", "?"), e)
        return None, None
    if not token:
        return None, None
    if expires_at - datetime.utcnow() <= TOKEN_REUSE_MARGIN:
        return None, expires_at
    return token, expires_at


def _as_bool(value: Any) -> Optional[bool]:
    """表单里 `use_sandbox` 是字符串（"true"/"false"），转成三态。

    ★ 返回 None 表示「表单没填」，不是 False —— 后者会静默覆盖 Settings 里的
      沙箱开关，渠道一多就会出现「表单没填 = 强制生产」这种谁也不想要的结果。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    return text in {"1", "true", "yes", "on"}


__all__ = [
    "StoreCredential",
    "StoreCredentialError",
    "StoreNotConnected",
    "UnsupportedMarketplace",
    "load_store_credential",
    "TOKEN_REUSE_MARGIN",
    "MAX_OAUTH_ERROR_COUNT",
]

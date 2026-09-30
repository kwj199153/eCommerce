"""Amazon SP-API 连接器：字段规格 + 真实验证。

★★★ 验证为什么是**两步**（而不是只换一次 token）

    第一步 LWA token 交换只能证明 `client_id / client_secret / refresh_token`
    三个值是对的 —— 而 AWS 那两个密钥是**纯本地签名材料**，Amazon 在
    你真正发请求之前根本看不到它们。只做第一步的后果是：
    用户填错 AWS Secret Key，界面照样显示「已连接」，直到某次真取数才炸。
    （这正是「连接成功但调不通」的翻版。）

    所以第二步用换到的 token 去调 `/sellers/v1/marketplaceParticipations`：
    这个端点是 Amazon 官方推荐的「验证你的接入是否配好」的探针 ——
    只读、权限要求最低、失败原因可直接归因到「凭据错」或「App 未授权」。

★ 为什么**不**用 `SPAPIClient.health_check()`
    它内部 `except Exception: return False` —— 把 401 和 ConnectTimeout
    揉成同一个 False，正好毁掉「拒绝 vs 不可达」的区分（见 http.py 顶部）。
    这里改走 `SPAPIClientAuth.make_authenticated_request()`（公开方法，
    自带 LWA 刷新 + AWS SigV4 签名 + `SPAPIAuthError` 错误面）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from modules.stores.connect.base import (
    CredentialField,
    PlatformConnector,
    VerifyCheck,
    VerifyResult,
    VerifyStatus,
)
from modules.stores.connect.http import DEFAULT_TIMEOUT, HttpOutcome, request


def _lwa_auth_url() -> str:
    """LWA 端点地址。

    ★ **唯一真源**是 `LWACredentials` 的默认值 —— 这里绝不另写一份字面量：
      写两份的话，Amazon 换端点时只会改一处，另一处会静默地打到旧地址。
      这与「同一判定两份实现 ⇒ 至少一份永远测不到」是同一条判据。

    ★ 函数内导入的理由：本包位于 `modules/stores/`，而 `platforms.amazon.sp_api.auth`
      会拉起 `core.config` 等一串依赖。顶层导入会让「只想读一下表单 schema」的
      调用方（前端一进页面就调 `/connect/schema`）把整条 Amazon 依赖链拖起来。
    """
    from platforms.amazon.sp_api.auth import LWACredentials
    return LWACredentials().auth_url


class AmazonConnector(PlatformConnector):
    platform = "amazon"
    display_name = "亚马逊（Amazon SP-API）"
    docs_url = "https://developer-docs.amazon.com/sp-api/docs/registering-your-application"

    notes: List[str] = [
        "LWA 三个值在卖家中心「开发应用」里创建应用后获得；Refresh Token 需先完成一次授权。",
        "AWS 两个密钥来自 IAM 里给 SP-API 建的用户，只有首次创建时能看到 Secret。",
        "沙箱环境仅覆盖部分接口，验证沙箱请把环境切到「沙箱」。",
    ]

    def fields(self) -> List[CredentialField]:
        return [
            CredentialField.text(
                "client_id", "LWA Client ID",
                placeholder="amzn1.application-oa2-client.xxxx",
                help="卖家中心 → 开发应用 → 你的应用 → LWA 凭证",
            ),
            CredentialField.password("client_secret", "LWA Client Secret"),
            CredentialField.password(
                "refresh_token", "Refresh Token",
                placeholder="Atzr|xxxx",
                help="完成一次卖家授权后获得；长期有效，不会过期",
            ),
            CredentialField.password(
                "aws_access_key", "AWS Access Key ID",
                placeholder="AKIAxxxx",
                help="IAM 用户凭证，用于请求签名",
            ),
            CredentialField.password("aws_secret_key", "AWS Secret Access Key"),
            CredentialField.text(
                "region", "AWS 区域", required=False, default="us-east-1",
                help="北美 us-east-1 / 欧洲 eu-west-1 / 远东 ap-northeast-1",
            ),
            CredentialField.select(
                "use_sandbox", "运行环境", required=False, default="false",
                options=[
                    {"value": "false", "label": "生产（真实数据）"},
                    {"value": "true", "label": "沙箱（测试数据）"},
                ],
            ),
        ]

    async def verify(self, values: Dict[str, Any]) -> VerifyResult:
        checks: List[VerifyCheck] = []

        # ---------- 第一步：LWA token 交换 ----------
        lwa_outcome = await self._exchange_lwa_token(values)
        if lwa_outcome.error_kind or not lwa_outcome.ok:
            checks.append(VerifyCheck(name="LWA 令牌交换", ok=False, message=lwa_outcome.error_text))
            return self._failure_from_lwa(lwa_outcome, checks)

        token_data = lwa_outcome.body if isinstance(lwa_outcome.body, dict) else {}
        if not token_data.get("access_token"):
            checks.append(VerifyCheck(
                name="LWA 令牌交换", ok=False,
                message="Amazon 未返回 access_token",
            ))
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message="LWA 凭据被 Amazon 拒绝：响应里没有 access_token。请核对 Client ID / Secret / Refresh Token。",
                checks=checks,
                detail={"response": _redact(token_data)},
            )

        checks.append(VerifyCheck(name="LWA 令牌交换", ok=True, message="LWA 凭据有效"))

        # ---------- 第二步：SP-API 只读探针（验 AWS 签名 + App 授权）----------
        probe = await self._probe_spapi(values)
        checks.append(VerifyCheck(name="SP-API 只读探针", ok=probe["ok"], message=probe["message"]))
        if not probe["ok"]:
            return VerifyResult(
                status=probe["status"],
                message=probe["message"],
                checks=checks,
                detail=probe.get("detail", {}),
            )

        return VerifyResult(
            status=VerifyStatus.OK,
            message="连接成功：LWA 凭据与 AWS 签名均已通过 Amazon 校验",
            checks=checks,
            detail=probe.get("detail", {}),
        )

    # ---------- 内部：两步的各自实现（都用共享 HTTP 层）----------

    @staticmethod
    async def _exchange_lwa_token(values: Dict[str, Any]) -> HttpOutcome:
        """第一步：用 refresh_token 换 access_token。

        ★ URL 取自 `_lwa_auth_url()`（唯一真源），不另写字面量。
        """
        return await request(
            "POST",
            _lwa_auth_url(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": values["refresh_token"],
                "client_id": values["client_id"],
                "client_secret": values["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=DEFAULT_TIMEOUT,
        )

    @staticmethod
    def _failure_from_lwa(outcome: HttpOutcome, checks: List[VerifyCheck]) -> VerifyResult:
        """把第一步的失败**分流**成「被拒绝」或「不可达」。"""
        if outcome.is_transport_error:
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message=(
                    f"无法连接 Amazon 令牌服务（{outcome.error_text}）。"
                    "凭据好坏**未知** —— 请检查网络/代理后重试。"
                ),
                checks=checks,
            )

        # 有 HTTP 状态码：4xx 是凭据问题，5xx 是 Amazon 侧问题
        if outcome.status and 400 <= outcome.status < 500:
            desc = ""
            body = outcome.body
            if isinstance(body, dict):
                desc = str(body.get("error_description") or body.get("error") or "")
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message=(
                    "Amazon 拒绝了这组 LWA 凭据"
                    f"（HTTP {outcome.status}{'：' + desc if desc else ''}）。"
                    "请核对 Client ID / Client Secret / Refresh Token 是否属于同一个应用。"
                ),
                checks=checks,
                detail={"status": outcome.status},
            )

        return VerifyResult(
            status=VerifyStatus.UNREACHABLE,
            message=(
                f"Amazon 令牌服务返回 HTTP {outcome.status}（平台侧故障）。"
                "凭据好坏**未知**，请稍后重试。"
            ),
            checks=checks,
            detail={"status": outcome.status},
        )

    @staticmethod
    async def _probe_spapi(values: Dict[str, Any]) -> Dict[str, Any]:
        """第二步：带 AWS 签名调一次只读端点。"""
        from platforms.amazon.sp_api.auth import (
            AWSCredentials,
            SPAPIAuthError,
            SPAPIClientAuth,
            SPAPIConfig,
        )

        cfg = SPAPIConfig(
            lwa=LWACredentials(
                client_id=values["client_id"],
                client_secret=values["client_secret"],
                refresh_token=values["refresh_token"],
            ),
            aws=AWSCredentials(
                access_key=values["aws_access_key"],
                secret_key=values["aws_secret_key"],
                region=values.get("region") or "us-east-1",
            ),
            use_sandbox=str(values.get("use_sandbox", "false")).lower() == "true",
        )
        auth = SPAPIClientAuth(cfg)
        try:
            data = await auth.make_authenticated_request(
                method="GET", endpoint="/sellers/v1/marketplaceParticipations"
            )
        except SPAPIAuthError as exc:
            return AmazonConnector._classify_probe_error(exc)
        except Exception as exc:  # noqa: BLE001 —— 未预期异常按不可达处理，不影响凭据判定
            return {
                "ok": False,
                "status": VerifyStatus.UNREACHABLE,
                "message": f"SP-API 探针异常（{type(exc).__name__}）：{exc}",
            }
        finally:
            try:
                await auth.close()
            except Exception:  # noqa: BLE001
                pass

        return {
            "ok": True,
            "status": VerifyStatus.OK,
            "message": "SP-API 只读探针通过（AWS 签名有效、App 已被卖家授权）",
            "detail": {"marketplaces": _extract_marketplaces(data)},
        }

    @staticmethod
    def _classify_probe_error(exc: Exception) -> Dict[str, Any]:
        """把 `SPAPIAuthError` 分流。

        ★ 判据是 `code` 的 `HTTP_<status>` 前缀 —— 这是 `_wrap_spapi_error()`
          写进去的约定（auth.py 里 `code=f"HTTP_{...}"`）。
          拿不到状态码的（传输层）一律按不可达处理，**不冤枉凭据**。
        """
        code = str(getattr(exc, "code", "") or "")
        text = str(exc)
        if code.startswith("HTTP_"):
            try:
                status = int(code.split("_", 1)[1])
            except (IndexError, ValueError):
                status = 0
            if 400 <= status < 500:
                return {
                    "ok": False,
                    "status": VerifyStatus.INVALID,
                    "message": (
                        f"SP-API 拒绝了这个请求（HTTP {status}）：{text}。"
                        "常见原因：AWS 密钥不属于同一账号/未授予 SP-API 角色，"
                        "或该应用尚未被卖家授权。"
                    ),
                    "detail": {"status": status},
                }
        return {
            "ok": False,
            "status": VerifyStatus.UNREACHABLE,
            "message": f"SP-API 探针未能完成（{code or 'ERR'}）：{text}。凭据好坏未知，请稍后重试。",
        }


def _extract_marketplaces(data: Any) -> List[Dict[str, str]]:
    """从探针响应里挑出可展示的站点信息（拿不到就返回空，不编造）。"""
    out: List[Dict[str, str]] = []
    if not isinstance(data, dict):
        return out
    for item in (data.get("payload") or [])[:5]:
        if not isinstance(item, dict):
            continue
        mp = item.get("marketplace") or {}
        if not isinstance(mp, dict):
            continue
        out.append({
            "id": str(mp.get("id", "")),
            "name": str(mp.get("name", "")),
            "country": str(mp.get("countryCode", "")),
        })
    return out


def _redact(data: Dict[str, Any]) -> Dict[str, Any]:
    """平台错误响应里可能带敏感值 —— 回显前统一抹掉 token 类字段。"""
    out = {}
    for k, v in (data or {}).items():
        if k in ("access_token", "refresh_token"):
            out[k] = "••••••"
        else:
            out[k] = v
    return out

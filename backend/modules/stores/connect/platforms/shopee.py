"""Shopee Open Platform 连接器：字段规格 + 真实验证。

★★★ 签名规范（**查证自官方文档，不是凭记忆**）
    https://open.shopee.com/developer-guide/16 与 /developer-guide/20

    `sign` = HMAC-SHA256(base_string, key=partner_key) 的**小写 hex**。
    base_string 按 API 类型有三种拼法，**顺序写错只会得到「签名错误」**：

        Public API（授权、换 token、刷新 token）:
            partner_id + api_path + timestamp
        Shop API（店铺维度，绝大多数业务接口）:
            partner_id + api_path + timestamp + access_token + shop_id
        Merchant API（主账号维度）:
            partner_id + api_path + timestamp + access_token + merchant_id

    `api_path` **只含路径**（如 `/api/v2/shop/get_shop_info`），不带 host、不带 query。
    `timestamp` 是**秒**（不是毫秒）。

★ Host（生产 / 沙箱两套）
    生产 https://partner.shopeemobile.com
    沙箱 https://partner.test-stable.shopeemobile.com
    两套的 partner_id 是**分开申请**的，混用只会得到「签名错误」。

★★★ 为什么要处理 refresh_token 这条支路

    Shopee 的 `access_token` **只有 4 小时**有效期，而 `refresh_token` 有 30 天。
    只收 access_token 的话，「连接成功」在 4 小时后就自动变成假的，
    而用户完全不知道为什么（界面上还显示着「已连接」）。

    所以本连接器允许两种输入，并通过 `VerifyResult.refreshed` 把新换到的
    token 回传落库 —— 用户只填一次 refresh_token，之后每次验证都会自动续期。
    这也是「验证」这个动作顺带承担的一个真实职责，而不是纯只读检查。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from modules.stores.connect.base import (
    CredentialField,
    CredentialsIncomplete,
    PlatformConnector,
    VerifyCheck,
    VerifyResult,
    VerifyStatus,
)
from modules.stores.connect.http import HttpOutcome, brief_error, request
from modules.stores.connect.signing import hmac_sha256_hex

#: 生产 / 沙箱两套 host。★ 混用 partner_id 与 host 只会得到「签名错误」。
HOSTS: Dict[str, str] = {
    "production": "https://partner.shopeemobile.com",
    "sandbox": "https://partner.test-stable.shopeemobile.com",
}

PATH_TOKEN_GET = "/api/v2/auth/access_token/get"
PATH_SHOP_INFO = "/api/v2/shop/get_shop_info"

#: Shopee 的 error code 分两类。**分错的代价**：
#: 把不可达判成 `invalid`，用户会去反复改一个本来没错的密钥。
_INVALID_ERRORS = {
    "error_auth", "error_sign", "error_param", "error_param_invalid",
    "error_permission", "error_not_found", "error_shop_not_found",
    "error_partner_not_found", "error_token_invalid", "error_token_expired",
    "error_invalid_access_token", "error_refresh_token_invalid",
}


class ShopeeConnector(PlatformConnector):
    platform = "shopee"
    display_name = "虾皮（Shopee Open Platform）"
    docs_url = "https://open.shopee.com/developer-guide/20"

    notes: List[str] = [
        "partner_id / partner_key 在 Shopee 开放平台控制台的「App 详情页」里。",
        "access_token 仅 4 小时有效，refresh_token 30 天。只填 refresh_token 即可："
        "系统会在验证时自动换取新的 access_token 并保存。",
        "生产与沙箱的 partner_id 是分开申请的，请与环境保持一致。",
    ]

    def fields(self) -> List[CredentialField]:
        return [
            CredentialField.text(
                "partner_id", "Partner ID", placeholder="2001887",
                help="控制台 App 详情页；纯数字",
            ),
            CredentialField.password("partner_key", "Partner Key"),
            CredentialField.text(
                "shop_id", "Shop ID", placeholder="14701711",
                help="卖家授权后返回的店铺 ID；纯数字",
            ),
            CredentialField.password(
                "refresh_token", "Refresh Token", required=False,
                help="有效期 30 天。填了它就能自动续期，推荐",
            ),
            CredentialField.password(
                "access_token", "Access Token", required=False,
                help="仅 4 小时有效。与 Refresh Token **至少填一个**",
            ),
            CredentialField.select(
                "environment", "运行环境", required=False, default="production",
                options=[
                    {"value": "production", "label": "生产"},
                    {"value": "sandbox", "label": "沙箱"},
                ],
            ),
        ]

    async def verify(self, values: Dict[str, Any]) -> VerifyResult:
        checks: List[VerifyCheck] = []
        refreshed: Dict[str, str] = {}

        partner_id = values["partner_id"]
        partner_key = values["partner_key"]
        shop_id = values["shop_id"]
        access_token = values.get("access_token") or ""
        refresh_token = values.get("refresh_token") or ""
        host = HOSTS.get(values.get("environment") or "production", HOSTS["production"])

        if not access_token and not refresh_token:
            # ★ 跨字段规则，`required` 表达不了 ⇒ 在这里显式拒绝。
            #   绝不能放过：没有 token 就必然验不过，而报错会落在
            #   「get_shop_info 签名错误」上，把用户引向完全错误的方向。
            raise CredentialsIncomplete(
                ["access_token", "refresh_token"],
                ["Access Token 或 Refresh Token（至少填一个）"],
            )

        for key, label in (("partner_id", "Partner ID"), ("shop_id", "Shop ID")):
            if not str(values.get(key, "")).strip().lstrip("-").isdigit():
                raise CredentialsIncomplete(
                    [key], [f"{label}（必须是纯数字）"]
                )

        # ---------- 第一步（可选）：用 refresh_token 换 access_token ----------
        if not access_token:
            exchange = await self._exchange_access_token(
                host, partner_id, partner_key, shop_id, refresh_token
            )
            checks.append(VerifyCheck(
                name="令牌续期", ok=exchange["ok"], message=exchange["message"]
            ))
            if not exchange["ok"]:
                return VerifyResult(
                    status=exchange["status"],
                    message=exchange["message"],
                    checks=checks,
                )
            access_token = exchange["access_token"]
            refreshed["access_token"] = access_token
            if exchange.get("refresh_token"):
                # Shopee 每次刷新都会下发新的 refresh_token，必须一起存回去，
                # 否则用旧的那个再刷会失败（旧值已作废）。
                refreshed["refresh_token"] = exchange["refresh_token"]

        # ---------- 第二步：调 Shop API 拿店铺信息（证明签名与店铺都对）----------
        ts = _now_ts()
        base_string = f"{partner_id}{PATH_SHOP_INFO}{ts}{access_token}{shop_id}"
        outcome = await request(
            "GET",
            f"{host}{PATH_SHOP_INFO}",
            params={
                "partner_id": partner_id,
                "shop_id": shop_id,
                "timestamp": ts,
                "access_token": access_token,
                "sign": hmac_sha256_hex(partner_key, base_string),
            },
        )

        payload = _payload(outcome.body)
        err = _error_code(outcome.body)

        # 失败判据只有一条：**传输层出错**（error_kind，含 4xx/5xx）**或**
        # **业务错误码非空**。后者是 Shopee 特有的形态 —— HTTP 200 也可能是失败，
        # 只看 status_code 会把「签名错误」读成「连接成功」。
        if outcome.error_kind or err:
            checks.append(VerifyCheck(
                name="店铺信息探针", ok=False, message=brief_error(outcome) or err
            ))
            return self._classify(outcome, err, checks)

        if not payload:
            checks.append(VerifyCheck(
                name="店铺信息探针", ok=False, message="响应为空",
            ))
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message="Shopee 返回了空响应，无法确认连接。请稍后重试。",
                checks=checks,
            )

        checks.append(VerifyCheck(
            name="店铺信息探针", ok=True,
            message=f"已读到店铺「{payload.get('shop_name') or '未命名'}」",
        ))
        return VerifyResult(
            status=VerifyStatus.OK,
            message="连接成功：Shopee 签名校验通过，并已读到店铺信息",
            checks=checks,
            detail={
                "shop_name": str(payload.get("shop_name") or ""),
                "region": str(payload.get("region") or ""),
                "shop_status": str(payload.get("status") or ""),
                "auth_expire_time": payload.get("expire_time"),
                "is_cross_border": payload.get("is_cb"),
            },
            refreshed=refreshed,
        )

    # ---------- 内部 ----------

    @staticmethod
    async def _exchange_access_token(
        host: str, partner_id: str, partner_key: str, shop_id: str, refresh_token: str
    ) -> Dict[str, Any]:
        """Public API 换 token：base_string = partner_id + path + timestamp。"""
        ts = _now_ts()
        base_string = f"{partner_id}{PATH_TOKEN_GET}{ts}"
        outcome = await request(
            "POST",
            f"{host}{PATH_TOKEN_GET}",
            params={
                "partner_id": partner_id,
                "timestamp": ts,
                "sign": hmac_sha256_hex(partner_key, base_string),
            },
            json_body={
                "partner_id": int(partner_id),
                "shop_id": int(shop_id),
                "refresh_token": refresh_token,
            },
        )
        payload = _payload(outcome.body) or {}
        err = _error_code(outcome.body)

        if outcome.is_transport_error:
            return {
                "ok": False, "status": VerifyStatus.UNREACHABLE,
                "message": f"无法连接 Shopee（{outcome.error_text}）。凭据好坏未知，请检查网络后重试。",
            }
        if err or not outcome.ok or not payload.get("access_token"):
            if outcome.status and outcome.status >= 500:
                return {
                    "ok": False, "status": VerifyStatus.UNREACHABLE,
                    "message": f"Shopee 令牌服务故障（HTTP {outcome.status}），请稍后重试。",
                }
            return {
                "ok": False, "status": VerifyStatus.INVALID,
                "message": (
                    "Shopee 拒绝了 refresh_token"
                    f"（{err or brief_error(outcome)}）：请确认它未过期、且与本 Partner ID / Shop ID 匹配。"
                ),
            }
        return {
            "ok": True, "status": VerifyStatus.OK,
            "message": "已用 Refresh Token 换到新的 Access Token",
            "access_token": str(payload["access_token"]),
            "refresh_token": str(payload.get("refresh_token") or ""),
        }

    @staticmethod
    def _classify(
        outcome: HttpOutcome, err: str, checks: List[VerifyCheck]
    ) -> VerifyResult:
        """把失败分流成「被拒绝」与「不可达」。

        ★ 分流依据有三层，从最可靠往下：
          1. 传输层错误 ⇒ 必然不可达（凭据没被平台看过）
          2. HTTP 5xx ⇒ 平台故障 ⇒ 不可达
          3. Shopee 业务错误码 ⇒ 白名单里的按「被拒绝」，其余按「不可达」
             （拿不准的一律按不可达 —— 宁可让用户重试，也不要冤枉正确的凭据）
        """
        if outcome.is_transport_error:
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message=f"无法连接 Shopee（{outcome.error_text}）。凭据好坏**未知**，请检查网络/代理后重试。",
                checks=checks,
            )
        if outcome.status and outcome.status >= 500:
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message=f"Shopee 返回 HTTP {outcome.status}（平台侧故障）。凭据好坏**未知**，请稍后重试。",
                checks=checks,
                detail={"status": outcome.status},
            )
        if err and err in _INVALID_ERRORS:
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message=(
                    f"Shopee 拒绝了这组凭据（{err}）。"
                    "请逐项核对 Partner ID / Partner Key / Shop ID / Access Token 是否同属一个 App 与店铺。"
                ),
                checks=checks,
                detail={"error": err},
            )
        if outcome.status and 400 <= outcome.status < 500:
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message=f"Shopee 拒绝了请求（HTTP {outcome.status}）。请核对凭据与运行环境是否匹配。",
                checks=checks,
                detail={"status": outcome.status, "error": err},
            )
        return VerifyResult(
            status=VerifyStatus.UNREACHABLE,
            message=(
                f"Shopee 返回了无法归因的响应（{err or brief_error(outcome)}）。"
                "凭据好坏未知，请稍后重试。"
            ),
            checks=checks,
            detail={"error": err, "text": outcome.raw_text},
        )


def _now_ts() -> int:
    """Shopee 要求**秒**级时间戳（毫秒会被判签名错误）。"""
    return int(time.time())


def _payload(body: Any) -> Optional[Dict[str, Any]]:
    """取业务负载。

    ★ 容错两种形态：Shopee v2 通常把数据包在 `response` 里，但
      token 类接口与部分老接口把字段放在顶层。写死一种会在另一种上读空，
      而「读空」的表现是「店铺名显示不出来」而不是报错，很难被发现。
    """
    if not isinstance(body, dict):
        return None
    inner = body.get("response")
    if isinstance(inner, dict):
        return inner
    return body


def _error_code(body: Any) -> str:
    """取 Shopee 的业务错误码（成功时为空串）。

    官方说明："When the API call is successful, the error code returned is empty."
    """
    if not isinstance(body, dict):
        return ""
    return str(body.get("error") or "").strip()

"""Shopify 连接器：字段规格 + 真实验证。

★ 验证机制与 Amazon/Shopee **形状相同、实现不同**：
  Shopify 用自定义请求头 `X-Shopify-Access-Token`（无签名算法），
  所以这里既不需要 `signing.py`、也不需要多步取 token ——
  一次带头的 GET 就能同时证明「域名对」「token 对」「权限够」。

  这正是「一层适配」的体现：差异只是「带什么头、看哪个字段」，
  HTTP 出口与三态分流完全复用。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from modules.stores.connect.base import (
    CredentialField,
    PlatformConnector,
    VerifyCheck,
    VerifyResult,
    VerifyStatus,
)
from modules.stores.connect.http import brief_error, request

#: Admin API 版本。★ 写死一个**受支持**的版本号即可 ——
#: 留空或不填会让 Shopify 回落到「已弃用」的默认版本，行为随平台变动。
DEFAULT_API_VERSION = "2024-10"


class ShopifyConnector(PlatformConnector):
    platform = "shopify"
    display_name = "Shopify"
    docs_url = "https://shopify.dev/docs/apps/auth/admin-app-access-tokens"

    notes: List[str] = [
        "在 Shopify 后台「设置 → 应用和销售渠道 → 开发应用」里创建应用并安装，即可拿到 Admin API 访问令牌。",
        "店铺域名形如 your-store.myshopify.com（可连同 https:// 一起粘贴，系统会自动清理）。",
    ]

    def fields(self) -> List[CredentialField]:
        return [
            CredentialField.text(
                "shop_domain", "店铺域名",
                placeholder="your-store.myshopify.com",
                help="Shopify 后台的 .myshopify.com 域名（不是自定义域名）",
            ),
            CredentialField.password(
                "admin_access_token", "Admin API 访问令牌",
                placeholder="shpat_xxxx",
                help="安装自定义应用后生成，形如 shpat_ 开头",
            ),
            CredentialField.text(
                "api_version", "API 版本", required=False, default=DEFAULT_API_VERSION,
                help="留空则用默认版本",
            ),
        ]

    async def verify(self, values: Dict[str, Any]) -> VerifyResult:
        checks: List[VerifyCheck] = []
        domain = _normalize_domain(values["shop_domain"])
        version = (values.get("api_version") or DEFAULT_API_VERSION).strip()

        if not domain:
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message="店铺域名不合法：应形如 your-store.myshopify.com。",
                checks=checks,
            )

        outcome = await request(
            "GET",
            f"https://{domain}/admin/api/{version}/shop.json",
            headers={
                "X-Shopify-Access-Token": values["admin_access_token"],
                "Accept": "application/json",
            },
        )
        shop = (outcome.body or {}).get("shop") if isinstance(outcome.body, dict) else None

        if outcome.is_transport_error:
            checks.append(VerifyCheck(name="店铺信息探针", ok=False, message=outcome.error_text))
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message=(
                    f"无法连接 Shopify（{outcome.error_text}）。"
                    "凭据好坏**未知** —— 请检查域名拼写、网络或代理后重试。"
                ),
                checks=checks,
            )

        if isinstance(shop, dict) and outcome.ok:
            checks.append(VerifyCheck(
                name="店铺信息探针", ok=True,
                message=f"已读到店铺「{shop.get('name') or domain}」",
            ))
            return VerifyResult(
                status=VerifyStatus.OK,
                message="连接成功：Shopify 已接受该访问令牌",
                checks=checks,
                detail={
                    "shop_name": str(shop.get("name") or ""),
                    "domain": str(shop.get("domain") or domain),
                    "country": str(shop.get("country_code") or ""),
                    "currency": str(shop.get("currency") or ""),
                },
            )

        checks.append(VerifyCheck(
            name="店铺信息探针", ok=False, message=brief_error(outcome)
        ))
        if outcome.status in (401, 403):
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message=(
                    "Shopify 拒绝了该访问令牌（HTTP "
                    f"{outcome.status}）：令牌无效、已被撤销，或缺少读取店铺信息的权限。"
                ),
                checks=checks,
                detail={"status": outcome.status},
            )
        if outcome.status == 404:
            return VerifyResult(
                status=VerifyStatus.INVALID,
                message=(
                    f"找不到店铺 {domain}（HTTP 404）："
                    "请确认填的是 .myshopify.com 域名，且 API 版本号受支持。"
                ),
                checks=checks,
                detail={"status": 404},
            )
        if outcome.status and outcome.status >= 500:
            return VerifyResult(
                status=VerifyStatus.UNREACHABLE,
                message=f"Shopify 返回 HTTP {outcome.status}（平台侧故障），请稍后重试。",
                checks=checks,
                detail={"status": outcome.status},
            )
        return VerifyResult(
            status=VerifyStatus.UNREACHABLE,
            message=(
                f"Shopify 返回了无法归因的响应（{brief_error(outcome)}）。"
                "凭据好坏未知，请稍后重试。"
            ),
            checks=checks,
            detail={"text": outcome.raw_text},
        )


def _normalize_domain(raw: str) -> str:
    """把用户粘贴的各种形态收敛成裸域名。

    老板从浏览器地址栏复制时，常带上 `https://`、结尾的 `/`、
    甚至 `/admin` 路径 —— 这些值肉眼看着都对，直接拼进 URL 会得到
    一个 404，用户会以为是 token 错了（归因错方向）。
    """
    s = (raw or "").strip()
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE)
    s = s.split("/", 1)[0]
    s = s.split("?", 1)[0].strip().lower()
    return s

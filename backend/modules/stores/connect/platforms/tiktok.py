"""TikTok Shop 连接器：**仅字段规格，未接入自动校验**。

★★★ 为什么这里刻意不写 `verify()`

  本轮的验证适配器只覆盖 Amazon / Shopee / Shopify 三家（都已查到官方规范
  并实现）。TikTok Shop 的鉴权参数名与签名规则**尚未在本项目核对过**，
  而凭记忆写参数名是这条链路上最贵的一种错：字段名对不上时平台只会回
  「签名错误 / 参数错误」，用户会以为是自己复制错了。

  ⇒ 按基类默认实现走 `UNSUPPORTED`（fail-closed）：凭据**会加密保存**、
  但**不会**被标记为「已验证」。界面上必须显示为「已配置（未验证）」，
  与「已连接（已验证）」显式区分。

  ★ 这是**有意为之的空缺**，不是漏做：宁可让界面说「我们还没验过」，
    也不要让用户以为它验过了。
"""

from __future__ import annotations

from typing import List

from modules.stores.connect.base import CredentialField, PlatformConnector


class TikTokConnector(PlatformConnector):
    platform = "tiktok"
    display_name = "TikTok Shop"
    docs_url = "https://partner.tiktokshop.com/doc"

    notes: List[str] = [
        "⚠️ 本平台尚未接入自动校验：凭据会加密保存，但不会标记为「已验证」。",
        "字段名称与签名规则待按 TikTok Shop 官方文档复核后再接入验证。",
    ]

    def fields(self) -> List[CredentialField]:
        return [
            CredentialField.text(
                "app_key", "应用 Key",
                help="TikTok Shop 合作伙伴中心的应用标识",
            ),
            CredentialField.password("app_secret", "应用 Secret"),
            CredentialField.password(
                "access_token", "访问令牌",
                help="店铺授权后获得",
            ),
            CredentialField.text(
                "shop_id", "店铺 ID", required=False,
                help="TikTok Shop 的店铺标识（如控制台显示为 shop_cipher，请一并填入）",
            ),
        ]

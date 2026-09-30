"""平台签名算法（共享一份）。

★ 收在这里的理由与 `http.py` 相同：签名是**跨平台可复用**的纯函数，
  一旦散进各平台连接器，就会出现「Shopee 一份 HMAC、TikTok 又抄一份」
  的局面，而这类实现的 bug 表现为「平台回一句签名错误」，
  不给出到底哪一位拼错了 —— 抄错的那一份极难被发现。

目前只有 HMAC-SHA256（Shopee / TikTok 共用）。Amazon 走的是 AWS SigV4，
其实现已存在于 `platforms/amazon/sp_api/auth.py::sign_request()`，
**不在这里重写**（避免出现第二份签名实现）。
"""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(secret: str, base_string: str) -> str:
    """HMAC-SHA256 的十六进制小写摘要。

    ★ 两个细节都是平台硬要求，写错就只得到「签名错误」：
      - 密钥先于消息编码：`hmac.new(key, msg, ...)`（顺序反了不会报错，只会不匹配）
      - 输出**小写 hex**：Shopee 文档明确 "hexadecimal all-lowercase"
    """
    return hmac.new(
        secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

"""二维码渲染：把支付宝 `qr_code` 字符串变成可放进 `<img src>` 的 SVG。

==============================================================================
★ 为什么二维码在**后端**生成，而不是前端引一个 npm 包
==============================================================================
支付宝 `alipay.trade.precreate` 返回的是**一段字符串**（形如
`https://qr.alipay.com/bavh4wjlxf12tper3a`），不是图片。要把它呈现给用户，
必须自己做 QR 编码（Reed-Solomon 纠错 + 掩码选优，200+ 行）。

三个选择里我们选了第二个：

  ① 前端引二维码库（`qrcode` npm）
     多一个前端依赖；且**前端拿得到明文二维码内容** —— 虽然它本来就要显示，
     但把"生成"和"展示"放在同一侧，将来换成"服务端托管收款码"时无处可改。

  ② 后端生成 SVG（**本模块**）
     前端只 `<img src="data:image/svg+xml;base64,...">`，零新增前端依赖；
     生成逻辑与支付链路同侧，出问题时不需要跨前后端对时。

  ③ 用公网二维码 API（如 api.qrserver.com）
     ★ 直接排除：那等于把**用户的收款码地址**发给第三方。
       支付相关数据不出自家边界，这条不需要权衡。

==============================================================================
★ 为什么是 SVG 而不是 PNG
==============================================================================
`qrcode` 的 PNG 输出需要 `pillow`（一个 C 扩展）。SVG 输出路径是纯 Python
（`qrcode.image.svg` 只用 `xml.etree`）⇒ 少一个重量级运行期依赖；
且 SVG 是矢量的，二维码在任意显示尺寸下都不会出现"像素抖动导致扫不出来"。

★ 尺寸：默认 `box_size=10, border=4`（支付宝要求静区 ≥ 4 模块）。
  SVG 自带 `viewBox`，前端按 CSS 宽高任意缩放都不失真。
"""

from __future__ import annotations

import base64
import io

from core.logger import get_logger

_log = get_logger("billing.qr")

#: data URI 前缀。★ 用 base64 而不是 URL-encode：SVG 里有 `#`、`&`、引号，
#: URL-encode 形态在部分浏览器与 vue 模版绑定下会被截断（`#` 之后当成 fragment）。
_DATA_URI_PREFIX = "data:image/svg+xml;base64,"


def qr_svg_data_uri(data: str) -> str:
    """把内容编码为 SVG 二维码，返回可直接绑给 `<img src>` 的 data URI。

    Args:
        data: 二维码承载的字符串（支付宝的 `qr_code`）。

    Returns:
        `data:image/svg+xml;base64,...`；**入参为空时返回空串**。

    ★ 空入参返回空串而不是抛异常：调用方是"渲染账单上的二维码"，
      而历史账单 / mock 账单的 `pay_url` 本来就是空的。
      为一张没有二维码的账单抛异常，会让整个列表接口 500 ——
      一个展示问题上升成可用性问题。**由前端决定"没有二维码"怎么显示**。
    """
    text = (data or "").strip()
    if not text:
        return ""

    # 延迟 import：`qrcode` 只在真正要出图时才加载。这样"支付链路"与
    # "二维码渲染"在依赖上是解耦的 —— 没装 qrcode 的部署仍能正常收款下单
    # （订单已落库、pay_url 已存），只是这个接口会报错，而不是整个应用起不来。
    import qrcode
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.QRCode(
        version=None,             # 自动选版本（内容短时用小版本，码点更大更好扫）
        error_correction=qrcode.constants.ERROR_CORRECT_M,   # 约 15% 纠错，扫码屏显的常规档
        box_size=10,
        border=4,                 # 静区：支付宝要求 >= 4 模块，少了会扫不出来
        image_factory=SvgPathImage,
    )
    qr.add_data(text)
    qr.make(fit=True)

    buf = io.BytesIO()
    qr.make_image().save(buf)
    return _DATA_URI_PREFIX + base64.b64encode(buf.getvalue()).decode("ascii")


__all__ = ["qr_svg_data_uri"]

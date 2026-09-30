"""平台验证的**唯一 HTTP 出口**。

★★★ 为什么必须收成一份

  「每个平台写一套」最典型的形态不是复制整段业务逻辑，而是**每处各写一个
  `httpx.AsyncClient(...)`**：于是超时值、异常分类、日志、代理行为各平台
  互不相同，改一处永远改不全。

  收口之后，各平台连接器只声明「打到哪个 URL、带什么参数、什么算成功」，
  网络层的行为（超时 / 重试边界 / 异常翻译）只有这一份。

★★★ 本模块的核心契约：**永不抛异常**

  所有网络异常都在这里被翻译成 `HttpOutcome.error_kind`。调用方拿到的
  永远是一个可判定的结果对象 —— 因为「把拒绝与不可达分开」这件事
  （见 `base.VerifyStatus`）必须先有 `error_kind` 才做得出来。

  若这里放任异常往上冒，调用方就只剩 `try/except Exception` 一条路，
  而那恰好会把 `401` 与 `ConnectTimeout` 揉成同一个 `False` ——
  也就是「网络抖一下，用户的正确凭据被判成无效」。

★★★ 为什么用 `follow_redirects=True` 之外还要看 `status_code`

  这里**不做** `raise_for_status()`：HTTP 4xx/5xx 是**业务信息**（凭据被拒），
  不是本层的异常。抛出去再由上层 `except` 捕获，就又丢掉了 status_code。
  统一放进 `status` 字段，判定权交给连接器。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


#: 默认超时（秒）。验证是**交互式**操作（用户点了「测试连接」在等），
#: 不能像后台任务那样默认 30s —— 用户等不到结果会以为界面卡死。
DEFAULT_TIMEOUT = 10.0


@dataclass
class HttpOutcome:
    """一次 HTTP 调用的结果。

    `error_kind` 的取值（调用方据此判 `INVALID` 还是 `UNREACHABLE`）：
      - `""`            成功（2xx 且响应体解析通过）
      - `"timeout"`     超时 ⇒ 不可达
      - `"unreachable"` DNS / 连接被拒 / TLS 失败 ⇒ 不可达
      - `"http"`        收到 4xx/5xx 响应 ⇒ **要看 status 才能定性**
      - `"decode"`      响应体不是合法 JSON ⇒ 平台侧异常，按不可达处理
    """
    ok: bool
    status: Optional[int] = None
    body: Any = None
    error_kind: str = ""
    error_text: str = ""
    requested_url: str = ""
    #: 原始响应文本（截断）。放在这里而不是只留 body，是为了让「返回了非 JSON
    #: 的 HTML 错误页」这类情况仍然可读 —— 那正是线上最常见的怪响应。
    raw_text: str = ""

    @property
    def is_transport_error(self) -> bool:
        """是不是「根本没拿到有效响应」（网络层问题）。"""
        return self.error_kind in ("timeout", "unreachable", "decode")


def _truncate(text: str, limit: int = 400) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _friendly_transport_error(exc: Exception) -> tuple[str, str]:
    """把 httpx 的传输异常翻译成 (error_kind, 中文可读文案)。"""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", f"请求超时（{DEFAULT_TIMEOUT:g}s 内未收到响应）"
    if isinstance(exc, httpx.ConnectError):
        return "unreachable", f"无法建立连接：{exc}"
    return "unreachable", f"网络错误：{type(exc).__name__}: {exc}"


async def request(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HttpOutcome:
    """发一次请求，**永不抛异常**。

    Args:
        params:    query 参数
        data:      form-urlencoded 表单体（Amazon LWA 用这种）
        json_body: JSON 请求体（Shopee 用这种）
        headers:   额外请求头

    Returns:
        `HttpOutcome`。判定成功与否请用 `outcome.ok`；
        要区分「被拒绝」与「不可达」请看 `error_kind` / `status`。
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method.upper(),
                url,
                params=params,
                data=data,
                json=json_body,
                headers=headers,
            )
    except Exception as exc:  # noqa: BLE001 —— 本层的契约就是「全部翻译成结果」
        kind, text = _friendly_transport_error(exc)
        logger.warning("平台验证请求失败 (%s %s): %s", method, url, text)
        return HttpOutcome(
            ok=False, error_kind=kind, error_text=text, requested_url=url
        )

    raw = ""
    parsed: Any = None
    decode_failed = False
    if resp.content:
        try:
            raw = resp.text
        except Exception:  # noqa: BLE001
            raw = ""
        try:
            parsed = resp.json()
        except ValueError:
            # 不是 JSON。**不能直接判失败** —— 有些平台的错误页是 HTML，
            # 而状态码仍能说明问题（401 就是 401）。交给调用方按 status 判。
            parsed = None
            decode_failed = True

    if resp.status_code >= 400:
        # 4xx/5xx：这是**业务信息**（凭据被拒 / 店铺不存在 / 平台故障），
        # 不是本层的异常。必须把 status 原样带出去。
        return HttpOutcome(
            ok=False,
            status=resp.status_code,
            body=parsed,
            error_kind="http",
            error_text=f"HTTP {resp.status_code}",
            requested_url=url,
            raw_text=_truncate(raw),
        )

    if parsed is None and decode_failed:
        return HttpOutcome(
            ok=False,
            status=resp.status_code,
            body=None,
            error_kind="decode",
            error_text="响应不是合法 JSON（可能是平台错误页或代理拦截）",
            requested_url=url,
            raw_text=_truncate(raw),
        )

    return HttpOutcome(
        ok=True,
        status=resp.status_code,
        body=parsed,
        requested_url=url,
        raw_text=_truncate(raw),
    )


def brief_error(outcome: HttpOutcome) -> str:
    """把结果压成一句可直接上屏的话（用于 VerifyResult.message）。"""
    if outcome.error_kind == "http":
        return f"平台返回 HTTP {outcome.status}"
    if outcome.error_text:
        return outcome.error_text
    return "未知错误"

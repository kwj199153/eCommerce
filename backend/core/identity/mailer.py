"""
邮件通道（P1-b，2026-09-16）

本模块**只负责把一封信发出去**，不负责「发什么」（那是 email_tokens.py 的事）。
三档实现，由 `config.email_provider` 选择。

==============================================================================
★ 为什么是「三档」而不是「配了就发、没配就不发」
==============================================================================
最后那种写法是最典型的「假门禁」：没配邮件服务时接口照样 200，
用户以为验证邮件已发出、实际什么都没发生；忘记密码更是彻底断链
（永远收不到重置链接，也永远查不出为什么）。

三档的判据是**每一档的行为都可预测，且不产生"假成功"**：

    console   —— 开发/测试。信不真发，写日志 + 落进内存 outbox。
                 测试据此断言「信确实被发了」，**永不依赖外网**，
                 也不会因为没配 SMTP 而静默跳过用例。
                 生产护栏禁止这一档（否则就是"界面说已发送、实际没人收到"）。
    aliyun_dm —— 真发。缺任一必填项 ⇒ 生产启动期直接拒绝（config.py 护栏）。
    disabled  —— 显式关闭。发送时抛 `MailDisabled` ⇒ 接口回 503 + 可读原因。

==============================================================================
★ 为什么自实现阿里云签名，而不是装 aliyun SDK
==============================================================================
DirectMail 的 `SingleSendMail` 是标准的阿里云 RPC 风格签名（HMAC-SHA1），
用标准库 `hmac`/`hashlib`/`urllib` + 项目已有的 `httpx` 即可，约 60 行。
少一个依赖 = 少一类「SDK 升级后签名算法变了、发信静默失败」的故障面。

签名算法（阿里云 RPC v1.0）：
    ① 参数按 key 升序排列
    ② 每个 k/v 做 RFC3986 percent-encode（`~` 不编码、空格 → %20、`*` → %2A）
    ③ CanonicalizedQueryString = "k1=v1&k2=v2&..."
    ④ StringToSign = "POST&%2F&" + percentEncode(CanonicalizedQueryString)
    ⑤ Signature = Base64(HMAC-SHA1(AccessKeySecret + "&", StringToSign))
"""

import base64
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from urllib.parse import quote

from core.config import config

logger = logging.getLogger(__name__)


# ====== 消息 ======

@dataclass
class MailMessage:
    """一封待发的邮件"""
    to: str
    subject: str
    html_body: str
    text_body: str = ""


# ====== 异常 ======

class MailDisabled(RuntimeError):
    """邮件通道被显式关闭（EMAIL_PROVIDER=disabled）—— 端点据此回 503"""


class MailSendFailed(RuntimeError):
    """发送失败（网络/鉴权/配额）—— **必须让调用方知道**，不能静默吞掉"""


# ====== 实现 ======

class ConsoleMailer:
    """
    开发/测试用：不真发，写日志 + 落进内存 outbox。

    ★ outbox 是**类属性**（不是实例属性）：`get_mailer()` 可能返回不同实例，
      而用例要能稳定读到"刚才发了什么"。放在类上可以跨实例读。
    ★ 为什么必须留 outbox 而不只是打日志：
      打日志只能靠人眼翻，用例无法断言；outbox 让「验证邮件真的发出去了」
      变成一条**可执行判据** —— 也正是这一点，让测试不必真的连 SMTP。
    """
    outbox: List[MailMessage] = []

    async def send(self, msg: MailMessage) -> None:
        ConsoleMailer.outbox.append(msg)
        logger.info(
            "[console-mailer] 收件人=%s 主题=%s（未真正外发；EMAIL_PROVIDER=console）",
            msg.to, msg.subject,
        )


class DisabledMailer:
    """显式关闭：发送即失败，且原因可读（供端点翻译成 503）"""

    async def send(self, msg: MailMessage) -> None:  # noqa: ARG002
        raise MailDisabled(
            "邮件服务未启用（EMAIL_PROVIDER=disabled）："
            "无法发送验证/重置邮件。请联系管理员配置 EMAIL_PROVIDER=aliyun_dm"
        )


def _percent_encode(value: str) -> str:
    """
    阿里云要求的 RFC3986 编码。

    `urllib.parse.quote(s, safe="")` 的行为正好符合：
      `~` 属"永不编码"字符集（Python 3.7+），空格 → %20，`*` → %2A。
    这里再做一次防御性替换，避免不同 Python 版本的行为差异。

    ★ 关于 `.replace("+", "%20")` —— 别把它理解成"加号要变成空格"：
      阿里云官方示例（Java）写的是 `URLEncoder.encode(...).replace("+","%20")`，
      那一步之所以必要，是因为 **URLEncoder 把空格编成 `+`**。
      本实现用 `quote`，空格**本来就是 %20**、字面 `+` 是 `%2B`
      ⇒ 这句 replace 在这里恒为无操作，属于"对齐官方示例"的冗余保险。
      判据由 `tests/test_auth_security_p1b.py::test_percent_encode_follows_rfc3986`
      钉住：字面加号必须留在 `%2B`。
      唯一要小心的是**别改用 `urllib.parse.quote_plus`** —— 那才会把空格
      编成 `+`，此时这句 replace 就从"冗余"变成"必需"，而两种实现会
      产出不同的规范串（签名随之变化）。
    """
    return quote(str(value), safe="").replace("*", "%2A").replace("+", "%20")


class AliyunDirectMailMailer:
    """阿里云邮件推送（DirectMail）SingleSendMail"""

    API_VERSION = "2015-11-23"
    ACTION = "SingleSendMail"

    async def send(self, msg: MailMessage) -> None:
        params = {
            "Action": self.ACTION,
            "Format": "JSON",
            "Version": self.API_VERSION,
            "AccessKeyId": config.aliyun_dm_access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": uuid.uuid4().hex,
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RegionId": config.aliyun_dm_region,
            # DirectMail 专有参数
            "AccountName": config.aliyun_dm_account_name,
            "ReplyToAddress": "false",
            "AddressType": "1",
            "ToAddress": msg.to,
            "Subject": msg.subject,
            "HtmlBody": msg.html_body or msg.text_body,
        }
        if config.aliyun_dm_from_alias:
            params["FromAlias"] = config.aliyun_dm_from_alias

        params["Signature"] = self._sign(params)

        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(config.aliyun_dm_endpoint, data=params)
        except Exception as exc:  # noqa: BLE001
            raise MailSendFailed(f"调用阿里云邮件推送失败（网络层）：{exc}") from exc

        if resp.status_code != 200:
            raise MailSendFailed(
                f"阿里云邮件推送返回 HTTP {resp.status_code}：{resp.text[:300]}"
            )
        # 业务错误码也走 200，必须解析 body 才知道成没成 ——
        # 只看 status_code 会把「发信被拒」当成「发送成功」。
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            raise MailSendFailed(f"阿里云邮件推送返回非 JSON：{resp.text[:300]}")

        if payload.get("Code"):
            raise MailSendFailed(
                f"阿里云邮件推送拒绝发送：Code={payload.get('Code')} "
                f"Message={payload.get('Message')}"
            )

    @staticmethod
    def _sign(params: dict) -> str:
        """按阿里云 RPC v1.0 规则算签名（见模块 docstring 的 ①~⑤）"""
        # ① 升序；② 编码
        items = sorted((k, _percent_encode(v)) for k, v in params.items() if v is not None)
        canonical = "&".join(f"{k}={v}" for k, v in items)
        string_to_sign = "POST&%2F&" + _percent_encode(canonical)
        digest = hmac.new(
            (config.aliyun_dm_access_key_secret + "&").encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode("ascii")


# ====== 工厂 ======

_MailerCache = {"provider": None, "mailer": None}


def get_mailer():
    """
    按 `config.email_provider` 返回邮件实现（缓存；provider 变了会自动换）。

    ★ 缓存 key 里带 provider：测试里会 monkeypatch `config.email_provider`
      来切档（console ↔ disabled），若只按"第一次调用的结果"缓存，
      切换后拿到的还是旧的 —— 用例会开始互相污染，且原因极难查。
    """
    provider = (config.email_provider or "").strip().lower()
    if _MailerCache["provider"] == provider and _MailerCache["mailer"] is not None:
        return _MailerCache["mailer"]

    if provider == "aliyun_dm":
        mailer = AliyunDirectMailMailer()
    elif provider == "disabled":
        mailer = DisabledMailer()
    else:
        # 未知值兜底走 console：生产护栏已禁止 console，此处只影响开发/测试
        mailer = ConsoleMailer()

    _MailerCache["provider"] = provider
    _MailerCache["mailer"] = mailer
    return mailer


def clear_outbox() -> None:
    """清空 console outbox（测试用例之间隔离用）"""
    ConsoleMailer.outbox.clear()

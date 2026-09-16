"""
邮箱验证 / 密码重置的一次性 token 服务（P1-b，2026-09-16）

==============================================================================
★ 三个必须由实现（而不是由注释）保证的性质
==============================================================================
① **只存哈希**：库里存的是 sha256(raw)。拖库 / 备份泄露 / 只读副本读到该表时，
   攻击者拿不到可直接使用的凭据。
   （对照：明文存 token 等于把「能收这封信」直接变成「能改这个账号的密码」。）

② **一次性**：消费判据全部压进**一条** UPDATE ... RETURNING，靠 PostgreSQL
   的行锁保证并发第二条影响 0 行。写成「先查后改」就是 TOCTOU ——
   用户双击邮件链接、或邮件客户端/安全网关**预抓取**链接，都会并发消费。
   对外不区分「无效 / 过期 / 已用过」，统一一句话术（避免帮攻击者做区分）。

③ **用途绑定**：purpose 参与消费判据。否则「能收验证信」就等于「能改密码」，
   而这两件事的可信度并不相同（邮箱可能只是临时加的转发规则）。

==============================================================================
★ 重发为什么必须同时作废旧 token
==============================================================================
用户点「重新发送验证邮件」时，旧链接仍在有效期内。若不作废，就有多份
同时在野的有效凭据（谁收到过旧邮件谁就还能用）。
⇒ 签发新 token 时把同 purpose 的未消费 token 全部标记为已用。
   **这一步必须显式做**，否则用户点旧邮件里的链接会莫名失败却查不出原因
   （这里选择"作废旧链接"而不是"允许多份并存"，因为前者是可解释的）。
"""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.identity.auth_models import EmailToken, EmailTokenPurpose
from core.identity.mailer import (
    MailDisabled,
    MailMessage,
    MailSendFailed,
    get_mailer,
)

logger = logging.getLogger(__name__)

# token 明文长度：32 字节 = 256 bit 熵，urlsafe 编码后 43 字符。
# ★ 必须用 secrets 而不是 random：random 是 Mersenne Twister，**可预测**，
#   观察到若干个输出就能推出后续输出 —— 对重置密码的凭据是致命的。
_TOKEN_BYTES = 32


def hash_token(raw: str) -> str:
    """sha256(raw) 的十六进制表示；库里只存这个"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _ttl_for(purpose: str) -> timedelta:
    """
    有效期按用途分档。

    ★ 为什么重置密码（30 分钟）比验证邮箱（24 小时）短得多：
      两者的"最坏后果"不对称 —— 验证链接泄露只是"帮别人确认一个邮箱"，
      重置链接泄露是**账号沦陷**。有效期越短，泄露窗口越小，
      而用户为了重置密码本来就在电脑前等着，30 分钟完全够用。
    """
    if purpose == EmailTokenPurpose.RESET_PASSWORD.value:
        return timedelta(minutes=int(config.email_reset_token_ttl_minutes))
    return timedelta(hours=int(config.email_verify_token_ttl_hours))


def _purpose_value(purpose) -> str:
    return purpose.value if hasattr(purpose, "value") else str(purpose)


async def issue_token(
    db: AsyncSession,
    user_id: str,
    purpose,
    requested_ip: Optional[str] = None,
) -> str:
    """
    签发一枚一次性 token，返回**明文**（只此一次；库里只有哈希）。

    ⚠️ 调用方负责 commit（本函数只 add + flush 前的作废 UPDATE）。
       让调用方掌握事务边界，便于把「作废旧 token + 落新 token + 记录审计」
       放进同一个事务，不会出现"旧的废了、新的没落上"的中间态。
    """
    p = _purpose_value(purpose)
    now = datetime.utcnow()

    # ① 作废同用途的未消费 token（见模块 docstring）
    await db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == p,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    # ② 落新 token（只存哈希）
    raw = _new_raw_token()
    db.add(
        EmailToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            purpose=p,
            token_hash=hash_token(raw),
            expires_at=now + _ttl_for(p),
            requested_ip=requested_ip,
        )
    )
    await db.flush()
    return raw


async def consume_token(db: AsyncSession, raw: str, purpose) -> Optional[str]:
    """
    原子消费一枚 token，成功返回 user_id，失败返回 None。

    ★ 判定全部压在一条 UPDATE 上（见模块 docstring 的 ②）：
        - token_hash 匹配
        - purpose 匹配
        - used_at IS NULL（没用过）
        - expires_at > now（没过期）
      影响行数为 0 即视为无效，**不区分**具体是哪一项不满足。

    ⚠️ 调用方负责 commit。消费与"重置密码 / 置 is_verified"必须在**同一事务**里，
       否则会出现"token 消费了但密码没改成"这种用户无法重试的死局。
    """
    if not raw:
        return None
    p = _purpose_value(purpose)
    now = datetime.utcnow()

    row = (
        await db.execute(
            text(
                """
                UPDATE email_tokens
                   SET used_at = :now
                 WHERE token_hash = :h
                   AND purpose = :p
                   AND used_at IS NULL
                   AND expires_at > :now
                RETURNING user_id
                """
            ),
            {"h": hash_token(raw), "p": p, "now": now},
        )
    ).first()
    return row[0] if row else None


# ====== 邮件内容 ======

def _link(path: str, raw: str) -> str:
    """
    把 token 拼成用户可点的链接。

    ★ 未配 `PUBLIC_SITE_URL` 时**不编造一个 localhost 链接** ——
      那会让用户在邮件里看到一个点了没用的地址，还以为是服务坏了。
      此时返回空串，由调用方在正文里改成"请把下面这串代码填进 App"。
      （生产护栏要求 EMAIL_VERIFICATION_REQUIRED=true 时 PUBLIC_SITE_URL 非空。）
    """
    base = (config.public_site_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}{path}?token={raw}"


def _render(title: str, intro: str, link: str, raw: str, footnote: str) -> str:
    """渲染邮件 HTML。链接为空时退化成"请复制这串代码"。"""
    action_block = (
        f'<p><a href="{link}" style="background:#2f6fed;color:#fff;'
        f'padding:10px 18px;border-radius:6px;text-decoration:none">{title}</a></p>'
        f'<p style="color:#888;font-size:12px">若按钮无法点击，请复制下面的地址到浏览器：<br>{link}</p>'
        if link
        else '<p>请在应用内粘贴下面这串代码完成操作：</p>'
        f'<p style="font-family:monospace;background:#f4f4f4;padding:10px;'
        f'word-break:break-all">{raw}</p>'
    )
    return f"""<div style="font-family:sans-serif;line-height:1.7;max-width:560px">
  <h2 style="margin:0 0 12px">{intro}</h2>
  {action_block}
  <p style="color:#666;font-size:13px">{footnote}</p>
  <hr style="border:none;border-top:1px solid #eee">
  <p style="color:#aaa;font-size:12px">{config.app_name}</p>
</div>"""


async def send_verify_email(to_email: str, raw: str) -> None:
    """发送邮箱验证邮件（失败会抛 MailDisabled / MailSendFailed，调用方须处理）"""
    link = _link("/verify-email", raw)
    hours = int(config.email_verify_token_ttl_hours)
    html = _render(
        "验证邮箱",
        f"请验证你的邮箱：{to_email}",
        link,
        raw,
        f"链接 {hours} 小时内有效。若你并未注册 {config.app_name}，忽略本邮件即可。",
    )
    await get_mailer().send(
        MailMessage(
            to=to_email,
            subject=f"【{config.app_name}】请验证你的邮箱",
            html_body=html,
            text_body=f"请打开以下链接验证邮箱（{hours} 小时内有效）：{link or raw}",
        )
    )


async def send_reset_email(to_email: str, raw: str) -> None:
    """发送密码重置邮件"""
    link = _link("/reset-password", raw)
    minutes = int(config.email_reset_token_ttl_minutes)
    html = _render(
        "重置密码",
        "重置你的密码",
        link,
        raw,
        f"链接 {minutes} 分钟内有效，且只能用一次。"
        f"若你并未申请重置密码，请忽略本邮件 —— 你的密码不会被改动。",
    )
    await get_mailer().send(
        MailMessage(
            to=to_email,
            subject=f"【{config.app_name}】重置密码",
            html_body=html,
            text_body=f"请打开以下链接重置密码（{minutes} 分钟内有效）：{link or raw}",
        )
    )


# ====== 清理 ======

async def purge_spent_tokens(db: AsyncSession, older_than_days: int = 7) -> int:
    """
    清掉已消费/已过期超过 N 天的 token 行。

    为什么需要：每点一次「重发验证邮件」就多一行，长期不清理会稳定增长
    （它没有任何业务价值了：used_at 非空或已过期 ⇒ 永远不会再被消费）。
    """
    cutoff = datetime.utcnow() - timedelta(days=max(1, older_than_days))
    res = await db.execute(
        text(
            "DELETE FROM email_tokens"
            " WHERE (used_at IS NOT NULL OR expires_at < :now) AND created_at < :cutoff"
        ),
        {"now": datetime.utcnow(), "cutoff": cutoff},
    )
    return res.rowcount or 0

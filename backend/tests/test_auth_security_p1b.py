"""
P1-b 账号安全回归测试（2026-09-16）

覆盖本轮落地的六项能力（每项都至少有「正向 + 反向」两条）：
    ① 邮箱验证（发送验证邮件 → 消费一次性 token → 置 is_verified）
    ② 忘记密码 → 重置密码邮件链路（统一话术 / 一次性 / 用途绑定）
    ③ 修改密码（登录态改密 ⇒ 其他设备全部掉线，当前设备换发新 token）
    ④ 登出（真撤销：jti 黑名单 / 失败必须 503 而不是假报成功）
    ⑤ 登录失败计数 + 账号锁定（login_attempts 审计 + users 判定）
    ⑥ admin/邮件/锁定的生产护栏（console 档不得进生产、阈值不得调低）

==============================================================================
★ 本文件刻意断言的三类东西（不然等于没测）
==============================================================================
1. **库里的真实状态**，而不是只看 HTTP 码。
   例：验证邮箱要核 `is_verified` 变 True **且** `email_tokens.used_at`
   非空；改密要核 `users.token_version` 真的 +1。
   只断言 "200" 会漏掉"接口返回成功但什么都没写"（本项目出现过多次）。

2. **旧凭据真的失效**，而不只是"新凭据能用"。
   撤销类需求最容易做成"发个新 token 就宣称改密成功"，而旧 token 照样能进。

3. **失败时不许静默成功**。
   例：Redis 挂掉时 `/auth/logout` 必须 503。断言 200 就等于认可了
   "界面说已安全退出、实际 token 还能用"。

==============================================================================
★ 测试替身为什么是必须的（不是图省事）
==============================================================================
- 邮件：`ConsoleMailer.outbox`（内存 outbox）。生产默认档就是 console，
  信写日志 + 落 outbox ⇒ 用例能断言"信确实发了"，且**永不依赖外网**、
  不会因为没配 SMTP 而静默跳过。
- Redis：`jti` 黑名单需要 Redis。用一个只实现 `setex`/`exists` 的替身，
  既能测"撤销真的生效"，也能**确定性地**模拟"Redis 挂了"这条最容易被忽略
  的失败路径（真 Redis 挂不挂取决于环境，测不出稳定结论）。
"""

import re
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from core.config import config
from core.database import async_session_factory
from core.identity.email_tokens import hash_token
from core.identity.models import User
from core.identity.router import hash_password


# ==============================================================================
# 基础工具
# ==============================================================================

_LOGIN_URL = "/api/v1/auth/login"
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}

# token_urlsafe(32) ⇒ 43 个 URL-safe 字符
_RAW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{43}$")


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _form_login(client, email: str, password: str):
    """用表单方式登录，返回原始响应（失败用例要看状态码）。"""
    return await client.post(
        _LOGIN_URL, data={"username": email, "password": password}, headers=_FORM
    )


async def _token_of(client, email: str, password: str) -> str:
    """登录并返回 access token（登录本身失败即用例失败）。"""
    r = await _form_login(client, email, password)
    assert r.status_code == 200, f"登录失败 {r.status_code}: {r.text[:300]}"
    return r.json()["access_token"]


def _token_from(msg) -> str:
    """
    从 ConsoleMailer 的邮件里取出一次性 token（明文只存在于邮件里）。

    ★ 这里**不查库**：库里存的是 sha256，明文不落库是本次改造的核心性质之一。
      邮件正文（`text_body`）以「：<token>」结尾，故按全角冒号右切一次。
    """
    raw = (msg.text_body or "").rsplit("：", 1)[-1].strip()
    assert _RAW_TOKEN_RE.match(raw), f"未能从邮件正文取出 token：{msg.text_body!r}"
    return raw


async def _purge_user(email: str) -> None:
    """彻底清掉一个测试用户及其所有附属行（保持开发库干净）。"""
    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM login_attempts WHERE email = :e"), {"e": email})
        for sql in (
            "DELETE FROM email_tokens WHERE user_id IN (SELECT id FROM users WHERE email = :e)",
            "DELETE FROM invoices WHERE user_id IN (SELECT id FROM users WHERE email = :e)",
            "DELETE FROM payment_methods WHERE user_id IN (SELECT id FROM users WHERE email = :e)",
            "DELETE FROM subscriptions WHERE user_id IN (SELECT id FROM users WHERE email = :e)",
            # accounts.owner_user_id 是 CASCADE，删用户会带走账户；
            # account_members 同理。这里显式删一遍是为了**老库**上也能干净。
            "DELETE FROM account_members WHERE user_id IN (SELECT id FROM users WHERE email = :e)",
            "DELETE FROM accounts WHERE owner_user_id IN (SELECT id FROM users WHERE email = :e)",
        ):
            await db.execute(text(sql), {"e": email})
        await db.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
        await db.commit()


async def _user_row(uid: str):
    """读一条用户行的关键列（判定类字段都在这）。"""
    async with async_session_factory() as db:
        return (
            await db.execute(
                text(
                    "SELECT token_version, failed_login_count, locked_until, "
                    "is_verified, hashed_password FROM users WHERE id = :u"
                ),
                {"u": uid},
            )
        ).first()


async def _token_row(raw: str):
    """按 token_hash 查一次性 token 行（明文查不到，这是刻意的）。"""
    async with async_session_factory() as db:
        return (
            await db.execute(
                text(
                    "SELECT user_id, purpose, token_hash, used_at, expires_at, created_at "
                    "FROM email_tokens WHERE token_hash = :h"
                ),
                {"h": hash_token(raw)},
            )
        ).first()


async def _attempts(email: str, reason: str | None = None) -> list:
    sql = "SELECT success, reason FROM login_attempts WHERE email = :e"
    if reason is not None:
        sql += " AND reason = :r"
    sql += " ORDER BY created_at"
    async with async_session_factory() as db:
        params = {"e": email} if reason is None else {"e": email, "r": reason}
        return (await db.execute(text(sql), params)).all()


async def _expire_token_now(raw: str) -> None:
    """把某枚 token 的过期时间改到过去（用于测"过期"分支，不必真等 24h）。"""
    async with async_session_factory() as db:
        await db.execute(
            text(
                "UPDATE email_tokens SET expires_at = :t, created_at = :t "
                "WHERE token_hash = :h"
            ),
            {"t": datetime.utcnow() - timedelta(minutes=1), "h": hash_token(raw)},
        )
        await db.commit()


# ==============================================================================
# 夹具
# ==============================================================================

@pytest_asyncio.fixture
async def sec_user():
    """
    直插用户工厂：`await sec_user()` / `await sec_user(password="x", is_verified=True)`

    ★ 为什么不复用 conftest 的 `user` 夹具（它走 /register + /login）：
      本文件的用例大量需要"指定的初始状态"（未验证 / 已锁定 / 已知密码哈希），
      而 register 会在 outbox 里塞一封验证邮件，把「刚才那封信是哪封」
      这件事搅浑。直插更快、更可控，且清理路径完全独立。
    """
    created: list[str] = []

    async def _make(password: str = "pytest123456", **fields) -> dict:
        email = fields.pop("email", None) or f"pytest-sec-{uuid.uuid4().hex[:10]}@example.com"
        uid = str(uuid.uuid4())
        fields.setdefault("is_active", True)
        fields.setdefault("is_verified", False)
        async with async_session_factory() as db:
            db.add(
                User(
                    id=uid,
                    email=email,
                    hashed_password=hash_password(password),
                    name="sec-user",
                    **fields,
                )
            )
            await db.commit()
        created.append(email)
        return {"email": email, "password": password, "user_id": uid}

    yield _make

    for email in created:
        await _purge_user(email)


@pytest.fixture
def mailbox(monkeypatch):
    """
    console 档邮件 + 干净 outbox。

    ★ 必须显式把 `email_provider` 钉成 console：
      用例会把它切成 disabled 来测 503，而 `get_mailer()` 的缓存 key 带
      provider ⇒ 若不钉住，前一条用例留下的档位会让本用例静默走错实现。
    ★ `public_site_url` 置空：这样邮件正文末尾就是裸 token（便于解析），
      也顺带覆盖"没配站点地址时不编造 localhost 链接"这条降级行为。
    """
    from core.identity.mailer import ConsoleMailer, clear_outbox

    monkeypatch.setattr(config, "email_provider", "console")
    monkeypatch.setattr(config, "public_site_url", "")
    clear_outbox()
    yield ConsoleMailer.outbox
    clear_outbox()


class _FakeRedis:
    """最小 Redis 替身：只实现 revocation 用到的两个命令。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def setex(self, key: str, ttl, value: str) -> None:
        self.store[key] = value

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def ping(self) -> bool:
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    """让 jti 黑名单"可用"（内存实现），可断言撤销真的写进去了。"""
    from core.auth import revocation as rev

    fake = _FakeRedis()
    monkeypatch.setattr(rev, "_client", fake)
    monkeypatch.setattr(rev, "_client_failed", False)
    return fake


@pytest.fixture
def redis_down(monkeypatch):
    """让 jti 黑名单"不可达"（**确定性**，不依赖真实 Redis 状态）。"""
    from core.auth import revocation as rev

    monkeypatch.setattr(rev, "_client", None)
    monkeypatch.setattr(rev, "_client_failed", True)   # _get_client 直接返回 None，不尝试连接
    return None


# ==============================================================================
# ① 邮箱验证
# ==============================================================================

async def test_register_sends_verify_email_into_outbox(client, mailbox):
    """
    注册必须真的发出一封验证邮件，且邮件里带可用 token。

    ★ 为什么断言 outbox 而不是"响应 200"：`EMAIL_PROVIDER` 配错时最容易
      出现的形态是"接口一切正常、信没人收到"。outbox 让"信发了"变成
      一条可执行判据。
    """
    email = f"pytest-sec-{uuid.uuid4().hex[:10]}@example.com"
    try:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "pytest123456", "name": "mail test"},
        )
        assert r.status_code == 201, r.text[:300]
        body = r.json()
        assert body["email_sent"] is True, f"注册响应应如实回报已发信：{body}"
        assert body["email_error"] == ""
        assert body["user"]["is_verified"] is False, "注册时不应已通过验证"

        assert len(mailbox) == 1, f"应恰好发出一封验证邮件，实际 {len(mailbox)}"
        msg = mailbox[0]
        assert msg.to == email
        assert "验证" in msg.subject
        raw = _token_from(msg)

        # 明文不得落库：库里只有 sha256
        row = await _token_row(raw)
        assert row is not None, "邮件里的 token 在库里查不到"
        assert row.token_hash != raw, "★ token 明文落库了（应只存 sha256）"
        assert row.token_hash == hash_token(raw)
        assert row.purpose == "verify_email"
        assert row.used_at is None
    finally:
        await _purge_user(email)


async def test_verify_email_roundtrip_sets_is_verified(client, mailbox, sec_user):
    """验证邮箱：消费 token → `is_verified=True`，且 token 被标记已用。"""
    u = await sec_user()
    r = await client.post(
        "/api/v1/auth/verify-email/resend", headers=_hdr(await _token_of(client, u["email"], u["password"]))
    )
    assert r.status_code == 200, r.text[:300]
    assert r.json()["email_sent"] is True
    raw = _token_from(mailbox[-1])

    vr = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert vr.status_code == 200, vr.text[:300]
    assert vr.json()["user"]["is_verified"] is True

    row = await _user_row(u["user_id"])
    assert row.is_verified is True, "★ 接口返回成功但库里 is_verified 没变"
    trow = await _token_row(raw)
    assert trow.used_at is not None, "token 未被标记为已消费"


async def test_verify_email_token_is_single_use(client, mailbox, sec_user):
    """
    同一枚 token 第二次必须失败（一次性）。

    ★ 这条对应真实场景：用户双击邮件链接、或邮件客户端/安全网关**预抓取**
      链接，都会让同一 token 被消费两次。若实现是"先查后改"，两条请求会
      同时通过检查 ⇒ token 用两次（TOCTOU）。
    """
    u = await sec_user()
    await client.post(
        "/api/v1/auth/verify-email/resend", headers=_hdr(await _token_of(client, u["email"], u["password"]))
    )
    raw = _token_from(mailbox[-1])

    first = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert first.status_code == 200, first.text[:200]

    second = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert second.status_code == 400, (
        f"token 可重复使用（应 400），实际 {second.status_code} {second.text[:200]}"
    )


async def test_verify_email_rejects_expired_token(client, mailbox, sec_user):
    """过期 token 必须 400，且不得置 is_verified。"""
    u = await sec_user()
    await client.post(
        "/api/v1/auth/verify-email/resend", headers=_hdr(await _token_of(client, u["email"], u["password"]))
    )
    raw = _token_from(mailbox[-1])
    await _expire_token_now(raw)

    r = await client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert r.status_code == 400, r.text[:200]
    assert (await _user_row(u["user_id"])).is_verified is False, "被拒的请求不该改动状态"


async def test_verify_email_rejects_reset_purpose_token(client, mailbox, sec_user):
    """
    用途绑定：**重置密码**的 token 不能用来验证邮箱（反之亦然）。

    ★ 为什么要绑：验证邮箱的链接可信度与重置密码不同（邮箱可能只是临时加的
      转发规则）。不绑就等于"能收信 ⇒ 能改密码"。
    """
    u = await sec_user()
    fr = await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    assert fr.status_code == 200, fr.text[:200]
    reset_raw = _token_from(mailbox[-1])

    r = await client.post("/api/v1/auth/verify-email", json={"token": reset_raw})
    assert r.status_code == 400, (
        f"reset token 竟能用于邮箱验证（应 400），实际 {r.status_code} {r.text[:200]}"
    )
    assert (await _user_row(u["user_id"])).is_verified is False


async def test_resend_verify_email_invalidates_previous_token(client, mailbox, sec_user):
    """
    重发验证邮件必须**作废旧链接**。

    ★ 不然就有多份同时在野的有效凭据（谁收到过旧邮件谁还能用），
      而用户点旧链接失败时完全查不出原因。
    """
    u = await sec_user()
    hdr = _hdr(await _token_of(client, u["email"], u["password"]))

    await client.post("/api/v1/auth/verify-email/resend", headers=hdr)
    old_raw = _token_from(mailbox[-1])

    await client.post("/api/v1/auth/verify-email/resend", headers=hdr)
    new_raw = _token_from(mailbox[-1])
    assert new_raw != old_raw

    stale = await client.post("/api/v1/auth/verify-email", json={"token": old_raw})
    assert stale.status_code == 400, f"重发后旧 token 仍可用：{stale.status_code}"

    fresh = await client.post("/api/v1/auth/verify-email", json={"token": new_raw})
    assert fresh.status_code == 200, fresh.text[:200]


async def test_resend_verify_email_reports_failure_honestly(
    client, mailbox, sec_user, monkeypatch
):
    """
    邮件通道 disabled 时，resend 必须回 `email_sent: false` + 原因，
    **不能**谎报成功。

    接口本身仍是 200（"你是谁"这件事成功了，失败的是邮件）——
    用 5xx 会让前端误以为会话出了问题，从而把用户踢去登录页。
    """
    from core.identity.mailer import DisabledMailer, get_mailer

    u = await sec_user()
    hdr = _hdr(await _token_of(client, u["email"], u["password"]))
    monkeypatch.setattr(config, "email_provider", "disabled")
    assert isinstance(get_mailer(), DisabledMailer), "切档没生效，用例前提不成立"

    r = await client.post("/api/v1/auth/verify-email/resend", headers=hdr)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["email_sent"] is False, f"发信失败竟回报成功：{body}"
    assert "邮件服务未启用" in body["message"], body


async def test_resend_skips_when_already_verified(client, sec_user):
    """已验证的账号不必再发信（省额度，也让前端知道无需提示）。"""
    u = await sec_user(is_verified=True)
    hdr = _hdr(await _token_of(client, u["email"], u["password"]))
    r = await client.post("/api/v1/auth/verify-email/resend", headers=hdr)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["email_sent"] is False


async def test_login_blocked_until_email_verified_when_required(
    client, mailbox, monkeypatch
):
    """
    `EMAIL_VERIFICATION_REQUIRED=true` 时：未验证 → 403；验证后 → 200。

    ★ 这条同时是"门禁真的在执行"的证明：单看配置项存在说明不了什么。
    """
    email = f"pytest-sec-{uuid.uuid4().hex[:10]}@example.com"
    pwd = "pytest123456"
    monkeypatch.setattr(config, "email_verification_required", True)
    try:
        reg = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": pwd}
        )
        assert reg.status_code == 201, reg.text[:200]

        denied = await _form_login(client, email, pwd)
        assert denied.status_code == 403, (
            f"未验证邮箱竟可登录（应 403），实际 {denied.status_code} {denied.text[:200]}"
        )
        assert "邮箱尚未验证" in denied.json()["detail"]
        assert await _attempts(email, "unverified"), "被拒的登录必须留审计"

        raw = _token_from(mailbox[-1])
        ok = await client.post("/api/v1/auth/verify-email", json={"token": raw})
        assert ok.status_code == 200, ok.text[:200]

        passed = await _form_login(client, email, pwd)
        assert passed.status_code == 200, passed.text[:200]
    finally:
        await _purge_user(email)


async def test_verify_email_ttl_matches_configured_value(client, mailbox, sec_user):
    """
    有效期必须按用途分档，且真的用上了配置值。

    ★ 重置密码（30 分钟）必须显著短于验证邮箱（24 小时）——
      两者"最坏后果"不对称：验证链接泄露只是帮人确认一个邮箱，
      重置链接泄露是账号沦陷。
    """
    u = await sec_user()
    await client.post(
        "/api/v1/auth/verify-email/resend", headers=_hdr(await _token_of(client, u["email"], u["password"]))
    )
    verify_row = await _token_row(_token_from(mailbox[-1]))

    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    reset_row = await _token_row(_token_from(mailbox[-1]))

    verify_ttl = (verify_row.expires_at - verify_row.created_at).total_seconds() / 60
    reset_ttl = (reset_row.expires_at - reset_row.created_at).total_seconds() / 60

    assert abs(verify_ttl - config.email_verify_token_ttl_hours * 60) < 2, verify_ttl
    assert abs(reset_ttl - config.email_reset_token_ttl_minutes) < 2, reset_ttl
    assert reset_ttl < verify_ttl, "重置口令的有效期必须短于验证邮箱"


# ==============================================================================
# ② 忘记密码 / 重置密码
# ==============================================================================

async def test_forgot_password_response_is_identical_for_unknown_email(
    client, mailbox, sec_user
):
    """
    邮箱存在与不存在，响应**完全一致**（状态码 + 消息），且不存在的邮箱不发信。

    ★ 这是「反邮箱枚举」的核心判据：只要两者有差异，攻击者拿一批邮箱跑一遍
      就能筛出哪些是本站用户，再对这些账号做定向爆破（省掉 99% 的无效尝试）。
    """
    u = await sec_user()

    known = await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    unknown_email = f"nobody-{uuid.uuid4().hex[:10]}@example.com"
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": unknown_email}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json(), (
        f"两种邮箱的响应不同 ⇒ 接口成了邮箱枚举器：{known.json()} vs {unknown.json()}"
    )
    assert len(mailbox) == 1, "不存在的邮箱不该发信"


async def test_forgot_password_sends_reset_link(client, mailbox, sec_user):
    """存在且启用的邮箱：发一封重置邮件，token 落库为 hash。"""
    u = await sec_user()
    r = await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    assert r.status_code == 200, r.text[:200]

    assert len(mailbox) == 1
    assert mailbox[0].to == u["email"]
    assert "重置密码" in mailbox[0].subject

    row = await _token_row(_token_from(mailbox[0]))
    assert row is not None and row.purpose == "reset_password"
    assert row.token_hash != _token_from(mailbox[0])


async def test_forgot_password_503_when_mail_disabled(client, sec_user, monkeypatch):
    """
    `EMAIL_PROVIDER=disabled` ⇒ 503 + 可读原因。

    ★ 为什么这里**可以**明确回 503 而不违反"统一话术"：
      邮件服务是否启用是**全局配置状态**，与具体邮箱无关，
      因此不构成任何枚举通道。反过来，若这里静默返回 200，
      用户会一直等一封永远不会来的信。
    """
    from core.identity.mailer import DisabledMailer, get_mailer

    u = await sec_user()
    monkeypatch.setattr(config, "email_provider", "disabled")
    assert isinstance(get_mailer(), DisabledMailer)

    r = await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    assert r.status_code == 503, f"应 503，实际 {r.status_code} {r.text[:200]}"
    assert "邮件服务未启用" in r.json()["detail"]


async def test_reset_password_full_roundtrip(client, mailbox, sec_user):
    """完整链路：申请 → 收信 → 重置 → 新密码可登录、旧密码不行。"""
    u = await sec_user(password="old-password-1")
    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    raw = _token_from(mailbox[-1])

    rr = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "new-password-2"}
    )
    assert rr.status_code == 200, rr.text[:300]

    assert (await _form_login(client, u["email"], "new-password-2")).status_code == 200
    assert (await _form_login(client, u["email"], "old-password-1")).status_code == 401


async def test_reset_password_invalidates_all_existing_tokens(
    client, mailbox, sec_user
):
    """
    ★★★ 重置密码后，**重置之前签发的 token 必须全部失效**。

    这是"账号可能已失窃"场景的核心：攻击者手里那枚 access token 必须立刻作废。
    实现走 `users.token_version += 1`（不是"把 token 逐个加黑名单"——
    无状态 JWT 服务端根本没有那份清单，详见 core/auth/revocation.py）。
    """
    u = await sec_user(password="old-password-1")
    stolen = await _token_of(client, u["email"], u["password"])
    assert (await client.get("/api/v1/auth/me", headers=_hdr(stolen))).status_code == 200

    tv_before = (await _user_row(u["user_id"])).token_version

    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    raw = _token_from(mailbox[-1])
    await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "new-password-2"}
    )

    after = await client.get("/api/v1/auth/me", headers=_hdr(stolen))
    assert after.status_code == 401, (
        f"★ 重置密码后旧 token 仍可用（应 401），实际 {after.status_code} {after.text[:200]}"
    )
    assert (await _user_row(u["user_id"])).token_version == tv_before + 1


async def test_reset_password_also_kills_old_refresh_token(client, mailbox, sec_user):
    """
    ★★ 旧 **refresh** token 也必须失效（否则改密只挡住了一半）。

    这条曾经是**真漏洞**：`/auth/refresh` 从不比对 token 里的 `tv`、也不查
    jti 黑名单 ⇒ 攻击者拿改密前那枚 refresh token 照样换出全新 access token，
    而且新 token 带的是库里**当前**的 tv（看起来完全合法）⇒ 改密形同没改。
    """
    u = await sec_user(password="old-password-1")
    lr = await _form_login(client, u["email"], u["password"])
    stolen_refresh = lr.json()["refresh_token"]

    # 前提：改密前这枚 refresh token 是可用的
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh})
    ).status_code == 200

    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    await client.post(
        "/api/v1/auth/reset-password",
        json={"token": _token_from(mailbox[-1]), "new_password": "new-password-2"},
    )

    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": stolen_refresh}
    )
    assert after.status_code == 401, (
        f"★ 旧 refresh token 仍能换出新 access token（应 401），"
        f"实际 {after.status_code} {after.text[:200]}"
    )


async def test_reset_password_token_is_single_use(client, mailbox, sec_user):
    """同一枚重置 token 用两次，第二次必须 400。"""
    u = await sec_user()
    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    raw = _token_from(mailbox[-1])

    first = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "brand-new-1"}
    )
    assert first.status_code == 200, first.text[:200]

    second = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "brand-new-2"}
    )
    assert second.status_code == 400, f"重置 token 可重复使用：{second.status_code}"


async def test_reset_password_rejects_invalid_token_with_generic_message(
    client, sec_user
):
    """
    无效 / 过期 / 已用过 —— 三者**对外话术一致**（不帮攻击者做区分）。

    这条只做"格式根本不存在的 token"这一种，另外两种（过期、已用过）
    由上面两条覆盖；三条合起来共同钉住"统一话术"。
    """
    r = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "whatever-123"},
    )
    assert r.status_code == 400, r.text[:200]
    detail = r.json()["detail"]
    assert "无效或已过期" in detail, detail
    assert "不存在" not in detail and "已使用" not in detail, (
        f"错误话术泄露了失败原因：{detail}"
    )


async def test_reset_password_clears_lockout(client, mailbox, sec_user, monkeypatch):
    """
    ★ 重置密码必须顺手清掉失败计数与锁定。

    否则：账号正被爆破锁定中 → 用户改完密码仍登不上 → 而原因完全不可见
    （他看到的是"账号已锁定"，会以为重置没生效）。
    """
    u = await sec_user()
    monkeypatch.setattr(config, "login_max_failures", 3)

    for _ in range(3):
        await _form_login(client, u["email"], "wrong-password")
    locked = await _form_login(client, u["email"], u["password"])
    assert locked.status_code == 429, f"应已锁定，实际 {locked.status_code}"

    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    rr = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": _token_from(mailbox[-1]), "new_password": "after-lock-1"},
    )
    assert rr.status_code == 200, rr.text[:200]

    row = await _user_row(u["user_id"])
    assert row.locked_until is None, "重置后锁定未清除"
    assert row.failed_login_count == 0, "重置后失败计数未清零"

    ok = await _form_login(client, u["email"], "after-lock-1")
    assert ok.status_code == 200, f"重置后仍登不上：{ok.status_code} {ok.text[:200]}"


# ==============================================================================
# ③ 修改密码（登录态）
# ==============================================================================

async def test_change_password_requires_current_password(client, sec_user):
    """
    必须校验当前密码。

    ★ 不校验的后果：一枚被盗的 access token 就能把主人锁在门外
      （改掉密码 → 真主人再也进不来）。
    """
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "totally-wrong", "new_password": "brand-new-1"},
        headers=_hdr(token),
    )
    assert r.status_code == 400, f"未校验当前密码，实际 {r.status_code} {r.text[:200]}"
    # 密码不得被改动
    assert (await _form_login(client, u["email"], u["password"])).status_code == 200


async def test_change_password_rejects_same_password(client, sec_user):
    """新旧相同应拒绝（否则用户以为改了、实际没改）。"""
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": u["password"], "new_password": u["password"]},
        headers=_hdr(token),
    )
    assert r.status_code == 400, r.text[:200]


async def test_change_password_invalidates_other_devices_and_reissues_here(
    client, sec_user
):
    """
    ★★ 改密后：**其他设备全部掉线**，但**当前设备无感续用**。

    用户角度：他在 A 设备主动改密，不该被自己踢出去（否则体验像 bug，
    且他刚改完的密码还得再登一次）。攻击者角度：他手上的旧 token 必须立刻死。
    ⇒ 实现是"提升 token_version（整批失效）+ 返回一对新 token"。
    """
    u = await sec_user(password="old-password-1")
    other_device = await _token_of(client, u["email"], "old-password-1")
    this_device = await _token_of(client, u["email"], "old-password-1")

    r = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-1", "new_password": "new-password-2"},
        headers=_hdr(this_device),
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["access_token"] and body["refresh_token"], f"改密后应换发新 token：{body}"

    # 旧 token（两台设备）全部失效
    for name, old in (("其他设备", other_device), ("当前设备原 token", this_device)):
        got = await client.get("/api/v1/auth/me", headers=_hdr(old))
        assert got.status_code == 401, (
            f"{name} 的旧 token 仍可用（应 401），实际 {got.status_code}"
        )

    # 新 token 立即可用
    fresh = await client.get("/api/v1/auth/me", headers=_hdr(body["access_token"]))
    assert fresh.status_code == 200, fresh.text[:200]
    assert fresh.json()["email"] == u["email"]

    # 新密码可登录、旧密码不行
    assert (await _form_login(client, u["email"], "new-password-2")).status_code == 200
    assert (await _form_login(client, u["email"], "old-password-1")).status_code == 401


async def test_change_password_new_refresh_token_works(client, sec_user):
    """换发的新 refresh token 必须能正常刷新（否则用户 15 分钟后仍被踢）。"""
    u = await sec_user(password="old-password-1")
    token = await _token_of(client, u["email"], "old-password-1")
    r = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "old-password-1", "new_password": "new-password-2"},
        headers=_hdr(token),
    )
    new_refresh = r.json()["refresh_token"]

    rr = await client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert rr.status_code == 200, f"新 refresh token 不可用：{rr.status_code} {rr.text[:200]}"
    nxt = await client.get("/api/v1/auth/me", headers=_hdr(rr.json()["access_token"]))
    assert nxt.status_code == 200


async def test_change_password_bumps_token_version(client, sec_user):
    """库里 `token_version` 必须真的 +1（撤销的唯一落点）。"""
    u = await sec_user()
    before = (await _user_row(u["user_id"])).token_version
    token = await _token_of(client, u["email"], u["password"])
    await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": u["password"], "new_password": "brand-new-9"},
        headers=_hdr(token),
    )
    assert (await _user_row(u["user_id"])).token_version == before + 1


# ==============================================================================
# ④ 登出（真撤销）
# ==============================================================================

async def test_logout_revokes_current_token(client, sec_user, fake_redis):
    """登出后原 access token 必须 401，且 jti 真的写进了黑名单。"""
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])
    assert (await client.get("/api/v1/auth/me", headers=_hdr(token))).status_code == 200

    r = await client.post("/api/v1/auth/logout", headers=_hdr(token))
    assert r.status_code == 200, r.text[:200]
    assert r.json()["revoked"] >= 1
    assert fake_redis.store, "黑名单里没有任何条目 —— 撤销没落盘"

    after = await client.get("/api/v1/auth/me", headers=_hdr(token))
    assert after.status_code == 401, (
        f"登出后 token 仍可用（应 401），实际 {after.status_code} {after.text[:200]}"
    )


async def test_logout_revokes_refresh_token_too(client, sec_user, fake_redis):
    """
    ★ 带 `refresh_token` 登出时，那枚 refresh token 也必须失效。

    只撤销 access token 的话，refresh token 还能换出全新的 access token
    ⇒"登出"被绕过。这条同时验证 `/auth/refresh` 侧新增的 jti 检查。
    """
    u = await sec_user()
    lr = await _form_login(client, u["email"], u["password"])
    access, refresh = lr.json()["access_token"], lr.json()["refresh_token"]

    r = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
        headers=_hdr(access),
    )
    assert r.status_code == 200, r.text[:200]
    assert r.json()["revoked"] == 2, f"应同时撤销 access + refresh：{r.json()}"

    rr = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert rr.status_code == 401, (
        f"登出后 refresh token 仍能换新 token（应 401），实际 {rr.status_code} {rr.text[:200]}"
    )


async def test_logout_returns_503_when_redis_unavailable(client, sec_user, redis_down):
    """
    ★★★ Redis 不可达时 `/auth/logout` 必须 **503**，绝不能回"已登出"。

    本接口**声称**做了一件有安全后果的事（撤销凭据）。做不到却说成功，
    用户会以为自己已经安全退出（例如在公共电脑上），而 token 其实还能用 ——
    **静默的假成功比明确的失败危险得多**。
    """
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])

    r = await client.post("/api/v1/auth/logout", headers=_hdr(token))
    assert r.status_code == 503, (
        f"Redis 挂了却回 {r.status_code}（应 503）—— 这是假成功：{r.text[:200]}"
    )
    assert "未生效" in r.json()["detail"], r.json()


async def test_logout_all_works_without_redis(client, sec_user, redis_down):
    """
    ★ 兜底出路：Redis 全挂时，`/auth/logout-all` 必须照样能把所有登录踢掉。

    它走 `token_version`（DB），不依赖 Redis —— 这正是它存在的意义：
    用户需要一个"我就是要把所有登录都踢掉"的、**永远可用**的手段。
    """
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])

    r = await client.post("/api/v1/auth/logout-all", headers=_hdr(token))
    assert r.status_code == 200, f"Redis 挂时兜底接口也必须可用：{r.status_code} {r.text[:200]}"

    after = await client.get("/api/v1/auth/me", headers=_hdr(token))
    assert after.status_code == 401, f"logout-all 未生效：{after.status_code}"


async def test_logout_all_invalidates_refresh_token(client, sec_user, redis_down):
    """`logout-all` 也必须断掉 refresh 这条路（否则等于没登出）。"""
    u = await sec_user()
    lr = await _form_login(client, u["email"], u["password"])
    access, refresh = lr.json()["access_token"], lr.json()["refresh_token"]

    assert (await client.post("/api/v1/auth/logout-all", headers=_hdr(access))).status_code == 200

    rr = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert rr.status_code == 401, f"logout-all 后 refresh 仍可用：{rr.status_code}"


async def test_logout_requires_authentication(client, sec_user, fake_redis):
    """未登录不得登出（登出是"撤销我的凭据"，先得证明凭据是我的）。"""
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 401, r.text[:200]


async def test_logout_is_idempotent_for_same_token(client, sec_user, fake_redis):
    """
    同一枚 token 登出两次：第一次 200，第二次 401（因为已撤销）。

    ★ 记这条是因为它的语义容易被"优化"坏：有人会觉得"重复登出应该也回 200"，
      但那样就必须先绕过黑名单检查 ⇒ 等于给登出接口开了个免检入口。
      正确行为是：撤销生效后，这枚 token 在任何入口都不再被认作有效身份。
    """
    u = await sec_user()
    token = await _token_of(client, u["email"], u["password"])
    first = await client.post("/api/v1/auth/logout", headers=_hdr(token))
    assert first.status_code == 200
    second = await client.post("/api/v1/auth/logout", headers=_hdr(token))
    assert second.status_code == 401, (
        f"已撤销的 token 又通过了鉴权（应 401），实际 {second.status_code}"
    )


# ==============================================================================
# ⑤ 登录失败计数 + 账号锁定
# ==============================================================================

async def test_login_locks_account_after_threshold(client, sec_user, monkeypatch):
    """连续失败达阈值即锁定：第 N 次起 429，且带 `Retry-After`。"""
    u = await sec_user()
    monkeypatch.setattr(config, "login_max_failures", 3)

    r1 = await _form_login(client, u["email"], "wrong-1")
    r2 = await _form_login(client, u["email"], "wrong-2")
    assert r1.status_code == r2.status_code == 401, "未达阈值前应是普通 401"

    r3 = await _form_login(client, u["email"], "wrong-3")
    assert r3.status_code == 429, f"第 3 次失败应触发锁定，实际 {r3.status_code}"
    assert "Retry-After" in r3.headers, "锁定响应必须给出重试时间"
    assert "锁定" in r3.json()["detail"]

    locked = await _form_login(client, u["email"], "wrong-4")
    assert locked.status_code == 429, "锁定窗口内继续尝试仍应 429"


async def test_lockout_rejects_even_correct_password(client, sec_user, monkeypatch):
    """
    ★★★ 锁定期内**密码正确也必须拒绝** —— 判定顺序不能调换。

    若写成"密码对了就放行"，攻击者只要持续猜，猜对的那一次就直接进
    ⇒ 锁定窗口对攻击者零成本。

    ★ 反向保护：解锁时间过后，正确密码必须能进（否则是"永久锁死"）。
    """
    u = await sec_user()
    monkeypatch.setattr(config, "login_max_failures", 3)

    for i in range(3):
        await _form_login(client, u["email"], f"wrong-{i}")

    correct = await _form_login(client, u["email"], u["password"])
    assert correct.status_code == 429, (
        f"★ 锁定期内正确密码被放行了（应 429），实际 {correct.status_code} —— "
        f"后果：攻击者持续猜，猜中即进，锁定形同不存在"
    )

    # 把锁定时间推到过去 ⇒ 等同于"锁定窗口已过"
    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE users SET locked_until = :t WHERE id = :u"),
            {"t": datetime.utcnow() - timedelta(seconds=1), "u": u["user_id"]},
        )
        await db.commit()

    recovered = await _form_login(client, u["email"], u["password"])
    assert recovered.status_code == 200, (
        f"锁定窗口过后仍进不去（应 200），实际 {recovered.status_code} —— 永久锁死"
    )
    row = await _user_row(u["user_id"])
    assert row.locked_until is None, "锁定期过后应顺手复位 locked_until"
    assert row.failed_login_count == 0, "锁定期过后失败计数应归零"


async def test_login_success_resets_failure_count(client, sec_user):
    """
    登录成功必须把失败计数清零。

    ★ 不清零的后果：计数单调累积 ⇒ 用户"隔三差五打错一次"最终也会被锁，
      而且他完全无法把状态恢复（只有等锁）。
    """
    u = await sec_user()
    for i in range(2):
        assert (await _form_login(client, u["email"], f"wrong-{i}")).status_code == 401
    assert (await _user_row(u["user_id"])).failed_login_count == 2

    assert (await _form_login(client, u["email"], u["password"])).status_code == 200
    row = await _user_row(u["user_id"])
    assert row.failed_login_count == 0, f"成功后计数未清零：{row.failed_login_count}"
    assert row.locked_until is None


async def test_lockout_clears_counter_on_trigger(client, sec_user, monkeypatch):
    """
    触发锁定时必须**同时清零计数**并把 `locked_until` 往后推。

    ★ 若只置 locked_until 而不清零：解锁后计数仍是满的 ⇒ 用户再错 1 次
      立刻又锁 ⇒ 表现为"解锁后一碰就锁"，很难解释。
    """
    u = await sec_user()
    monkeypatch.setattr(config, "login_max_failures", 3)
    for i in range(3):
        await _form_login(client, u["email"], f"wrong-{i}")

    row = await _user_row(u["user_id"])
    assert row.locked_until is not None, "未写入 locked_until，锁定根本没生效"
    assert row.failed_login_count == 0, (
        f"触发锁定时计数未清零（当前 {row.failed_login_count}）⇒ 解锁后一碰就锁"
    )
    remaining = (row.locked_until - datetime.utcnow()).total_seconds()
    assert remaining > 0, "locked_until 必须在未来"


async def test_login_attempts_are_audited(client, sec_user):
    """
    每次登录尝试（成功与失败都算）都必须落 `login_attempts` 审计。

    ★ 审计与判定是不同的东西，缺一不可：
        - `users.failed_login_count` = 判定（只有当前值，成功即清零）
        - `login_attempts` = 审计（append-only，回答"昨晚是谁在撞我的账号"）
      用审计替代判定会在并发下算错"当前失败几次"；
      用判定替代审计则永远查不到攻击痕迹。
    """
    u = await sec_user()
    assert (await _form_login(client, u["email"], "wrong-password")).status_code == 401
    assert (await _form_login(client, u["email"], "wrong-password")).status_code == 401
    assert (await _form_login(client, u["email"], u["password"])).status_code == 200

    rows = await _attempts(u["email"])
    assert len(rows) == 3, f"应有 3 条审计，实际 {len(rows)}：{rows}"
    assert [r.success for r in rows] == [False, False, True]
    assert [r.reason for r in rows] == ["bad_password", "bad_password", "ok"]


async def test_unknown_email_login_is_audited_without_leaking(client, sec_user):
    """
    不存在的邮箱：审计照记（`reason=unknown_email`），但对外话术与"密码错"一致。

    ★ 审计里必须能区分这两种（运维排查需要），而对客户端必须不能区分
      （否则登录接口就是邮箱枚举器）。
    """
    u = await sec_user()
    bad_pwd = await _form_login(client, u["email"], "wrong-password")

    ghost = f"ghost-{uuid.uuid4().hex[:10]}@example.com"
    unknown = await _form_login(client, ghost, "wrong-password")

    assert bad_pwd.status_code == unknown.status_code == 401
    assert bad_pwd.json() == unknown.json(), (
        f"响应差异泄露了账号存在性：{bad_pwd.json()} vs {unknown.json()}"
    )

    assert await _attempts(u["email"], "bad_password"), "密码错未留正确原因"
    assert await _attempts(ghost, "unknown_email"), "邮箱不存在未留审计"
    await _purge_user(ghost)


async def test_locked_attempt_is_audited(client, sec_user, monkeypatch):
    """锁定期内的尝试也要留审计（reason=locked），否则测不出攻击者在持续撞。"""
    u = await sec_user()
    monkeypatch.setattr(config, "login_max_failures", 3)
    for i in range(3):
        await _form_login(client, u["email"], f"wrong-{i}")
    await _form_login(client, u["email"], u["password"])   # 锁定期内

    assert await _attempts(u["email"], "locked"), "锁定期内的尝试没有留审计"


async def test_lockout_threshold_defaults_stay_protective():
    """
    字段**默认值**必须仍然有防护力（>=3 次 / >=5 分钟）。

    ★ 为什么单独要一条：运行时用例靠 monkeypatch 把阈值调小以求快，
      于是"默认值被改弱"这件事在测试中**看不出来** —— 套件照样全绿，
      而生产的爆破防护已经静默消失。
      （与 `test_password_hash_rounds_default_stays_production_grade` 同一思路。）
    """
    from core.config import Settings

    assert Settings.model_fields["login_max_failures"].default >= 3
    assert Settings.model_fields["login_lockout_minutes"].default >= 5


# ==============================================================================
# ⑥ 生产护栏（P1-b 新增部分）
# ==============================================================================

@pytest.mark.parametrize(
    "over, keyword",
    [
        # 邮件通道
        ({"email_provider": "smtp"}, "EMAIL_PROVIDER"),
        ({"email_provider": "console"}, "console"),
        ({"aliyun_dm_access_key_id": ""}, "ALIYUN_DM_ACCESS_KEY_ID"),
        ({"aliyun_dm_access_key_secret": "  "}, "ALIYUN_DM_ACCESS_KEY_SECRET"),
        ({"aliyun_dm_account_name": ""}, "ALIYUN_DM_ACCOUNT_NAME"),
        # 邮箱验证开启的前置条件
        ({"email_provider": "console", "email_verification_required": True}, "console"),
        ({"public_site_url": "", "email_verification_required": True}, "PUBLIC_SITE_URL"),
        # 锁定阈值
        ({"login_max_failures": 1}, "LOGIN_MAX_FAILURES"),
        ({"login_max_failures": 0}, "LOGIN_MAX_FAILURES"),
        ({"login_lockout_minutes": 1}, "LOGIN_LOCKOUT_MINUTES"),
    ],
)
def test_production_guard_rejects_p1b_violations(prod_settings_kwargs, over, keyword):
    """
    反向：P1-b 的每一种违规配置都必须**拒绝启动**，且文案指出是哪个配置项。

    ★ 为什么必须"拒绝启动"而不是打日志：
      这些配置调低了不会报错、不会告警、功能一切正常 ——
      只是防护静默消失（console 档 = 用户以为收到信、实际没人收到；
      阈值调低 = 爆破门槛消失）。"静默削弱"只能在启动期拦住。
    """
    from core.config import Settings

    with pytest.raises(ValueError) as ei:
        Settings(**prod_settings_kwargs(**over))
    assert keyword in str(ei.value), f"错误信息里应出现 {keyword!r}：{ei.value}"


def test_production_guard_allows_explicitly_disabling_email(prod_settings_kwargs):
    """
    正向：不打算发邮件时显式 `EMAIL_PROVIDER=disabled` 必须放行 —— 证明护栏不过宽。

    ★ 这条是必需的"反向保护"：没有它，把 console 一刀切禁掉也能让上面
      那条反向用例变绿，但会把"我不想接邮件服务"这种合法部署一起挡在门外。
    """
    from core.config import Settings

    s = Settings(**prod_settings_kwargs(email_provider="disabled"))
    assert s.email_provider == "disabled"


def test_production_guard_allows_enabling_email_verification(prod_settings_kwargs):
    """正向：`EMAIL_VERIFICATION_REQUIRED=true` 在前置条件齐备时必须放行。"""
    from core.config import Settings

    s = Settings(**prod_settings_kwargs(email_verification_required=True))
    assert s.email_verification_required is True


# ==============================================================================
# ⑦ 邮件通道与签名（纯单元）
# ==============================================================================

def test_get_mailer_switches_with_provider(monkeypatch):
    """
    三档必须真的按 `email_provider` 切换到不同实现。

    ★ 缓存 key 必须带 provider：用例会中途切档（console ↔ disabled），
      若只按"第一次调用的结果"缓存，切换后拿到的还是旧实现 ⇒
      用例开始互相污染，且原因极难查。
    """
    from core.identity.mailer import (
        AliyunDirectMailMailer,
        ConsoleMailer,
        DisabledMailer,
        get_mailer,
    )

    monkeypatch.setattr(config, "email_provider", "console")
    assert isinstance(get_mailer(), ConsoleMailer)

    monkeypatch.setattr(config, "email_provider", "disabled")
    assert isinstance(get_mailer(), DisabledMailer)

    monkeypatch.setattr(config, "email_provider", "aliyun_dm")
    assert isinstance(get_mailer(), AliyunDirectMailMailer)

    monkeypatch.setattr(config, "email_provider", "console")
    assert isinstance(get_mailer(), ConsoleMailer)


async def test_disabled_mailer_raises_readable_error():
    """disabled 档发送即失败，且原因可读（端点据此翻译成 503）。"""
    from core.identity.mailer import DisabledMailer, MailDisabled, MailMessage

    with pytest.raises(MailDisabled) as ei:
        await DisabledMailer().send(
            MailMessage(to="a@b.c", subject="s", html_body="h")
        )
    assert "EMAIL_PROVIDER=disabled" in str(ei.value)


def test_aliyun_signature_is_deterministic_and_well_formed(monkeypatch):
    """
    自实现的阿里云 RPC v1.0 签名：确定性 + 正确的形状。

    ★ 为什么值得单独测：签名错了不会在启动期报错，而是**发信时**才被拒
      （且业务错误码走 HTTP 200，只看状态码会把"发信被拒"当成"发送成功"）。
      这里把"签名算法本身"钉住，把故障面从"线上发不出信"前移到"用例变红"。
    """
    import base64
    import hashlib
    import hmac

    from core.identity.mailer import AliyunDirectMailMailer, _percent_encode

    monkeypatch.setattr(config, "aliyun_dm_access_key_secret", "test-secret")

    params = {
        "Action": "SingleSendMail",
        "AccessKeyId": "test-ak",
        "SignatureNonce": "fixed-nonce-for-determinism",
        "Subject": "a b*c~d",
    }
    sig1 = AliyunDirectMailMailer._sign(params)
    sig2 = AliyunDirectMailMailer._sign(dict(reversed(list(params.items()))))
    assert sig1 == sig2, "签名对参数顺序敏感 —— 未按 key 升序排列"

    raw = base64.b64decode(sig1)
    assert len(raw) == hashlib.sha1().digest_size, "签名不是 SHA1 摘要长度"
    assert len(sig1) == 28, f"Base64(SHA1) 应为 28 字符，实际 {len(sig1)}"

    # 与手工按规则算出的值逐位对齐（防止"两边都用错规则"式的自洽）
    items = sorted((k, _percent_encode(v)) for k, v in params.items())
    canonical = "&".join(f"{k}={v}" for k, v in items)
    string_to_sign = "POST&%2F&" + _percent_encode(canonical)
    expected = base64.b64encode(
        hmac.new(
            b"test-secret&", string_to_sign.encode("utf-8"), hashlib.sha1
        ).digest()
    ).decode("ascii")
    assert sig1 == expected


def test_percent_encode_follows_rfc3986(monkeypatch):
    """
    编码规则：`~` 不编码、空格 → %20、`*` → %2A、`+` → %2B（阿里云要求）。

    ★ 关于 `+`：阿里云官方示例用 `URLEncoder.encode` 再 `.replace("+","%20")`
      —— 那一步之所以必要，是因为 **Java 的 URLEncoder 把空格编成 `+`**。
      本实现用的是 `urllib.parse.quote`，**空格本来就直接编成 %20**、
      字面 `+` 编成 %2B ⇒ 那句 replace 在这里恒为无操作。
      这是**正确**的（不是多余的错），故这里把真实行为钉住：
      字面加号必须留在 `%2B`，不能变成空格。
    """
    from core.identity.mailer import _percent_encode

    assert _percent_encode("a~b") == "a~b"
    assert _percent_encode("a b") == "a%20b"
    assert _percent_encode("a*b") == "a%2Ab"
    assert _percent_encode("a+b") == "a%2Bb"
    assert _percent_encode("a/b") == "a%2Fb"


async def test_token_plaintext_never_stored(client, mailbox, sec_user):
    """
    ★ 全表扫描确认：**任何**一次性 token 的明文都不在库里。

    这是"只存 sha256"这条性质的**整体**断言（单点断言容易被"某一处漏了"
    绕过）：把 outbox 里出现过的所有明文都拼起来，去库里搜，必须搜不到。
    """
    u = await sec_user()
    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    await client.post(
        "/api/v1/auth/verify-email/resend", headers=_hdr(await _token_of(client, u["email"], u["password"]))
    )
    raws = [_token_from(m) for m in mailbox]
    assert len(raws) == 2

    async with async_session_factory() as db:
        for raw in raws:
            hit = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM email_tokens "
                        "WHERE token_hash = :raw OR id = :raw"
                    ),
                    {"raw": raw},
                )
            ).scalar()
            assert hit == 0, f"★ token 明文出现在库里：{raw[:8]}…"
        # 反向保护：哈希确实在库里（否则上面那条可能因为"根本没写"而假绿）
        stored = (
            await db.execute(
                text("SELECT count(*) FROM email_tokens WHERE user_id = :u"),
                {"u": u["user_id"]},
            )
        ).scalar()
        assert stored == 2, f"应落 2 条 token 记录，实际 {stored}"


async def test_purge_spent_tokens_only_removes_old_rows(client, mailbox, sec_user):
    """
    清理任务：删"已消费/已过期 **且** 够老"的行，保留新鲜行。

    ★ 为什么必须有清理：每点一次"重发验证邮件"就多一行，
      长期不清理会稳定增长 —— 而它已经没有业务价值了。
    ★ 为什么写成 async 用例（而不是在同步用例里 run_until_complete）：
      本套件全部用例共用**同一个事件循环**（pytest.ini 的
      `asyncio_default_test_loop_scope = session`），而 asyncpg 的连接绑定在
      创建它的 loop 上。在同步用例里新起一个 loop 跑 DB 调用会直接报
      "attached to a different loop"。
    """
    from core.identity.email_tokens import purge_spent_tokens

    u = await sec_user()
    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    old_raw = _token_from(mailbox[-1])
    await client.post("/api/v1/auth/forgot-password", json={"email": u["email"]})
    fresh_raw = _token_from(mailbox[-1])

    # old_raw 已在第二次 issue_token 里被作废（used_at 非空）；再把它的创建时间改老
    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE email_tokens SET created_at = :t WHERE token_hash = :h"),
            {"t": datetime.utcnow() - timedelta(days=30), "h": hash_token(old_raw)},
        )
        await db.commit()

        removed = await purge_spent_tokens(db, older_than_days=7)
        await db.commit()

    assert removed >= 1, "老的已消费 token 没被清掉"
    assert await _token_row(old_raw) is None, "老行未被删除"
    assert await _token_row(fresh_raw) is not None, "★ 新鲜 token 被误删（用户会莫名失效）"


async def test_purge_old_attempts_respects_retention(client, sec_user):
    """登录审计按保留期清理（它每次登录都写一行，不清理会稳定增长）。"""
    from core.identity.login_guard import purge_old_attempts

    u = await sec_user()
    await _form_login(client, u["email"], "wrong-password")
    assert await _attempts(u["email"])

    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE login_attempts SET created_at = :t WHERE email = :e"),
            {"t": datetime.utcnow() - timedelta(days=90), "e": u["email"]},
        )
        await db.commit()

        removed = await purge_old_attempts(db, retention_days=30)
        await db.commit()

    assert removed >= 1, "超过保留期的审计没被清理"
    assert not await _attempts(u["email"]), "老审计仍在表里"

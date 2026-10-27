"""r400 · 演示账号登录别名（`DEMO_LOGIN_ALIAS`）回归测试

需求出处：运维待办《eCommerce 演示账号支持用户名登录（admin）》(2026-10-27)。
两站演示账号统一成 `admin` + 同一口令，但 **`users.email` 与
`DEMO_ACCOUNT_EMAIL` 一个字节都不许改** —— 因为 `is_demo_account()` 是
按 email 判身份的，改了它演示号的写保护（改密/删店/转移三条 403）整条失效。

本文件钉住的正是这条边界：**别名只改"输入侧的识别"，不改身份。**

==============================================================================
★ 为什么每条用例都要带反向（不然等于没测）
==============================================================================
1. 「`admin` 能登录」单独看是**恒真**的断言 —— 任何 401 都能被解释成"口令不对"。
   所以每条都配一个对照分支：`reason=unknown_email`（查无此人）vs
   `reason=bad_password`（查到了、口令不对）。**能把这两个分开**，
   才说明"认不认得出 admin"被真正观测到了。
2. 审计断言只认**本次用例产生的行**（唯一 `User-Agent` 标记）。
   第一版探针按 `email=... ORDER BY created_at DESC LIMIT 1` 取，
   结果上一次跑留下的行被当成本次结果 ⇒ 把别名关掉做反向注入时照样全绿。
3. `alias=""` 必须回到"完全不生效"（fail-closed），且这条**永久留在测试里** ——
   它是回滚路径本身，坏了就等于"删掉 .env 那一行也回不去"。

★ 为什么用临时用户而不是真演示号：
  真演示号的口令不在仓里（也不该在）。本文件把 `config.demo_account_email`
  临时指到一个 `make_user` 造的临时用户上 —— 别名映射的目标变成了它，
  「admin + 正确口令 → 200」这条链路就能被**确定性地**测到，
  不需要任何外部口令，也不会碰真实演示数据。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from core.config import config
from core.database import async_session_factory

LOGIN = "/api/v1/auth/login"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}

ALIAS = "admin"


async def _login(client, identifier: str, password: str, marker: str):
    """带着唯一 UA 标记登录，方便事后只查"本次用例"造出来的审计行。"""
    return await client.post(
        LOGIN,
        data={"username": identifier, "password": password},
        headers={**FORM, "User-Agent": marker},
    )


async def _last_attempt(marker: str) -> tuple[str, str, int]:
    """本次用例产生的**最新一条**审计行：(reason, email, 条数)。"""
    async with async_session_factory() as db:
        rows = (await db.execute(text(
            "SELECT reason, email FROM login_attempts "
            "WHERE user_agent = :m ORDER BY created_at DESC"
        ), {"m": marker})).all()
    if not rows:
        return ("<none>", "<none>", 0)
    return (rows[0][0], rows[0][1], len(rows))


@pytest_asyncio.fixture
async def alias_env(monkeypatch, make_user):
    """把「演示账号」临时指到一个新建用户上，并打开别名。

    产出的 `marker` 用作本次用例的审计标记；teardown 只删这些行
    （`make_user` 负责删 users，但 `login_attempts.user_id` 是 SET NULL，
    行会留下 —— 审计不该被静默改写，但"测试自己造的探测行"要收干净）。
    """
    marker = f"r400-test-{uuid.uuid4().hex[:10]}"
    demo = await make_user("alias-demo")
    monkeypatch.setattr(config, "demo_account_email", demo["email"])
    monkeypatch.setattr(config, "demo_login_alias", ALIAS)
    yield {"demo": demo, "marker": marker}
    async with async_session_factory() as db:
        await db.execute(
            text("DELETE FROM login_attempts WHERE user_agent = :m"), {"m": marker}
        )
        await db.commit()


@pytest.mark.asyncio
async def test_alias_logs_in_and_yields_token(client, alias_env):
    """判据 1：`admin` + 正确口令 → 200 + access_token，且身份是那位主人。"""
    demo, marker = alias_env["demo"], alias_env["marker"]

    r = await _login(client, ALIAS, demo["password"], marker)
    assert r.status_code == 200, f"别名登录失败: {r.status_code} {r.text}"
    body = r.json()
    assert body.get("access_token"), "200 却没发 token"

    # 拿到 token 之后必须是**那位主人**，不是字符串 "admin"
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == demo["email"], (
        f"别名登录后身份错位：{me.json().get('email')} != {demo['email']}"
    )


@pytest.mark.asyncio
async def test_real_email_still_works(client, alias_env):
    """判据 2：别名不能顶掉原登录名 —— 真 email + 同一口令仍然 200。"""
    demo, marker = alias_env["demo"], alias_env["marker"]

    r = await _login(client, demo["email"], demo["password"], marker)
    assert r.status_code == 200, f"原 email 登录被打断: {r.status_code} {r.text}"


@pytest.mark.asyncio
async def test_unknown_identifier_is_still_unknown(client, alias_env):
    """对照组：一个跟别名无关的字符串仍必须 `unknown_email`。

    没有这条，"admin 认得出"也可能只是"任何字符串都被当成有效标识符"。
    """
    marker = alias_env["marker"]
    r = await _login(client, f"nobody-{uuid.uuid4().hex[:8]}@example.invalid", "whatever", marker)
    assert r.status_code == 401
    reason, _, _ = await _last_attempt(marker)
    assert reason == "unknown_email", f"预期 unknown_email，实际 {reason}"


@pytest.mark.asyncio
async def test_alias_empty_means_disabled(client, alias_env, monkeypatch):
    """反向用例（永久钉住回滚路径）：`DEMO_LOGIN_ALIAS` 置空 ⇒ 别名完全不生效。

    这条是"删掉 .env 那一行就能回滚"这句话的可执行版本。
    """
    marker = alias_env["marker"]
    monkeypatch.setattr(config, "demo_login_alias", "")

    r = await _login(client, ALIAS, alias_env["demo"]["password"], marker)
    assert r.status_code == 401, f"别名关掉后居然登录成功: {r.status_code}"
    reason, logged_email, n = await _last_attempt(marker)
    assert n == 1, f"本次用例应有 1 条审计行，实际 {n}"
    assert reason == "unknown_email", f"别名关掉后仍被认出（reason={reason}）"
    # ★ 括号是一个**独立**的事实：关掉后连"记成谁"都回到输入原样
    assert logged_email == ALIAS


@pytest.mark.asyncio
async def test_audit_records_real_email(client, alias_env):
    """判据 6：审计记真 email，不记 `admin`（否则登录历史断成两个人）。"""
    demo, marker = alias_env["demo"], alias_env["marker"]

    r = await _login(client, ALIAS, demo["password"], marker)
    assert r.status_code == 200

    reason, logged_email, n = await _last_attempt(marker)
    assert n == 1
    assert reason == "ok", f"成功登录的 reason 应为 ok，实际 {reason}"
    assert logged_email == demo["email"], f"审计记成了 {logged_email}"


@pytest.mark.asyncio
async def test_alias_is_case_and_space_insensitive(client, alias_env):
    """别名对大小写与首尾空白不敏感（用户在手机上输入不会讲究这些）。

    ★ 与"别名不是任意身份入口"配套：映射目标恒为 `config.demo_account_email`，
      输入只决定"要不要走这个分支"，不决定"走进去之后是谁" ——
      所以这里断言身份**逐字等于** demo 用户的 email。
    """
    demo, marker = alias_env["demo"], alias_env["marker"]

    for typed in ("Admin", "  ADMIN  ", "aDmIn"):
        r = await _login(client, typed, demo["password"], marker)
        assert r.status_code == 200, f"{typed!r} 登录失败: {r.status_code} {r.text}"
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {r.json()['access_token']}"},
        )
        assert me.json()["email"] == demo["email"], (
            f"{typed!r} 登进了 {me.json().get('email')} —— 映射目标必须恒为 demo_account_email"
        )

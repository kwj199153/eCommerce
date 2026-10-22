"""演示账号写保护（第 391 轮）

==============================================================================
★ 为什么要这一层：演示账号是**唯一会被陌生人登录**的账号
==============================================================================
面试/简历场景下，演示账号的 email + 口令是**公开**的（否则面试官进不来）。
公开口令的副作用是：
  · `POST /auth/change-password` 只要求"当前密码正确" ⇒ 公开口令 = 公开修改权
    ⇒ 一个人手滑改掉，下一位访客（以及现场演示的你）**全部登不进**，
      且那个 email 是 `@example.com`，收不到重置邮件 —— 没有救济通道；
  · `DELETE /stores/{id}` 是物理删除，删掉一家演示店铺 = 演示永久少一块。

⇒ 两条按**身份**（`user.email == config.demo_account_email`）拦截，
  与 `DEMO_MODE` 哨兵无关 —— 线上哨兵本来就是关的，账号本身却还在。

==============================================================================
★★★ 判据的两侧都要钉住
==============================================================================
只测"演示账号被拦"是不够的：把守卫写成 `if True:` 也能过。
⇒ 必须同时测"**真实账号不受影响**"（本文件的 `test_real_user_*`）。
   这与本仓既有教训同构：单向判据只能证明"拦住了"，不能证明"没拦错人"。
"""

import pytest
from fastapi import HTTPException

from core.auth.demo_identity import is_demo_account
from core.config import config
from core.identity.router import hash_password
from core.identity.security_router import ChangePasswordRequest, change_password
from core.identity.models import User
from modules.stores.router import delete_store, transfer_store
from models.store import StoreTransfer

DEMO_EMAIL = "tenant-test-a@example.com"


@pytest.fixture()
def demo_email_on(monkeypatch):
    """把「谁是演示账号」指向夹具邮箱（这个值在线上由 .env 决定）。"""
    monkeypatch.setattr(config, "demo_account_email", DEMO_EMAIL, raising=False)
    return DEMO_EMAIL


def _user(email: str, password: str = "RealPass123") -> User:
    """构造一个内存里的 User（不落库 —— 这些用例只走守卫，不碰数据库）。"""
    return User(
        id="u-test",
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )


# ============================================================================
# 1. 身份判定本身
# ============================================================================

def test_is_demo_account_matches_configured_email(demo_email_on):
    assert is_demo_account(_user(demo_email_on)) is True


def test_is_demo_account_ignores_case_and_spaces(demo_email_on):
    """`.env` 是手写的 ⇒ `Demo@… ` 与 `demo@…` 必须是同一个人。"""
    assert is_demo_account(_user("  TENANT-TEST-A@Example.COM ")) is True


def test_is_demo_account_is_false_for_other_users(demo_email_on):
    assert is_demo_account(_user("someone-else@example.com")) is False


def test_is_demo_account_is_false_when_unconfigured(demo_email_on, monkeypatch):
    """配置为空 ⇒ 没有演示账号。

    ★ 方向是刻意的：本函数只用来**加限制**，判错只能"漏保护"，
      绝不能"误伤" —— 一个配置项没填就全站不能改密码，比不保护严重得多。
    """
    monkeypatch.setattr(config, "demo_account_email", "", raising=False)
    assert is_demo_account(_user(demo_email_on)) is False


def test_is_demo_account_handles_none():
    assert is_demo_account(None) is False


# ============================================================================
# 2. 改密码：演示账号 403，真实账号照常走
# ============================================================================

def _payload(old: str = "x", new: str = "y") -> ChangePasswordRequest:
    return ChangePasswordRequest(current_password=old, new_password=new)


@pytest.mark.asyncio
async def test_demo_account_cannot_change_password(demo_email_on):
    user = _user(demo_email_on)
    with pytest.raises(HTTPException) as exc:
        # db 传 None：守卫在函数第一行，任何数据库访问都在它之后。
        # 若哪天有人把守卫挪到后面，这里会因为 AttributeError 而不是 403 变红。
        await change_password(_payload("RealPass123", "NewPass456"), current_user=user, db=None)
    assert exc.value.status_code == 403
    assert "演示账号" in exc.value.detail


@pytest.mark.asyncio
async def test_real_user_still_reaches_password_check(demo_email_on):
    """真实账号必须**穿过**守卫，落到原有的密码校验（这里故意给错密码）。

    ★ 断言"不是 403"而不是"等于 400"之外的任何东西：
      本用例要证的是「守卫没拦错人」，密码校验的具体文案是别的用例的事。
    """
    user = _user("real-user@example.com")
    with pytest.raises(HTTPException) as exc:
        await change_password(_payload("wrong-password", "NewPass456"), current_user=user, db=None)
    assert exc.value.status_code == 400
    assert "演示账号" not in exc.value.detail


# ============================================================================
# 3. 删店：演示账号 403（且在取店之前），真实账号仍走既有 404/403 语义
# ============================================================================

@pytest.mark.asyncio
async def test_demo_account_cannot_delete_store(demo_email_on):
    user = _user(demo_email_on)
    with pytest.raises(HTTPException) as exc:
        # 故意用一个**不存在**的 store_id：策略判定在取店之前，
        # 所以演示账号拿到的必须是 403 而不是 404（否则就成了存在性探针）。
        await delete_store("store_does_not_exist", request=None, db=None, current_user=user)
    assert exc.value.status_code == 403
    assert "演示账号" in exc.value.detail


@pytest.mark.asyncio
async def test_real_user_delete_store_keeps_404_semantics(demo_email_on):
    """真实账号删不存在的店 ⇒ 仍然是原来的 404（守卫没有改变既有语义）。"""
    user = _user("real-user@example.com")
    with pytest.raises(HTTPException) as exc:
        await delete_store("store_does_not_exist", request=None, db=None, current_user=user)
    assert exc.value.status_code == 404


# ============================================================================
# 4. 转移店铺：演示账号 403（这条比删店更隐蔽，见下方说明）
# ============================================================================

@pytest.mark.asyncio
async def test_demo_account_cannot_transfer_store(demo_email_on):
    """演示账号不能把店铺转走。

    ★ 为什么这条必须单独立一个用例：转移**不删任何数据**，看起来无害。
      但 `ensure_demo_stores()` 按 `store.account_id == 演示账户 id` 双向收敛，
      店一旦转走，下一次启动就被打回 `is_demo=False` ⇒ 演示身份看不到它，
      而库里数据完好、接口全部 200 —— 现象是"演示账号莫名少了店铺"。
    """
    user = _user(demo_email_on)
    with pytest.raises(HTTPException) as exc:
        await transfer_store(
            "store_does_not_exist",
            data=StoreTransfer(account_id="acct-target"),
            request=None,
            db=None,
            current_user=user,
        )
    assert exc.value.status_code == 403
    assert "演示账号" in exc.value.detail

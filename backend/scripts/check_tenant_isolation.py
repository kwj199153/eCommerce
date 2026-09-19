"""
多租户隔离回归自检（业务侧）

验证 `core/tenant/middleware.py` 公开入口的归属校验是否真正生效
（`get_current_shop_id` / `get_current_shop_id_optional`）：
  - 用户 A 的 token 拿用户 B 的店铺 ID 当 X-Shop-ID -> 403
  - 店铺所有者 B 自己访问                          -> 放行（返回该 shop_id）
  - 平台超管跨账户访问                             -> 放行（设计如此）
  - 无 token / 伪造 token                          -> 401
  - 无 X-Shop-ID 头：读方法 -> None（端点回空列表）；写方法 -> 400
  - 演示模式（AUTH_REQUIRED=false）                -> 全部放行（不破坏本地演示）

★★★ P1-c 改造（2026-09-16）：本脚本原先打的是**账户侧**
    `get_tenant_from_header` / `require_shop_owner`（查 `shops` 表 / UUID）。
    那套符号已随账户侧实体整体删除。现在改打**业务侧**唯一解析者，
    并且用**真实的 account → store 层级**造数据（而不是手插一行 shops）：
    店铺必须挂在一个账户上、账户必须有 owner 成员行 —— 否则测的不是生产形态。
    判定实现见 `core/auth/accounts.py`。

★★★ 2026-09-18：本脚本改走**公开依赖入口**（`get_current_shop_id` /
    `get_current_shop_id_optional`），不再直接 import `_resolve_current_shop_id`。
    两条理由：
      ① 生产代码走的本来就是那两个公开依赖，直接打私有实现 = **少测一层**；
      ② 跨包 import 下划线私有符号等于对内部签名**静默上锁** —— `middleware.py`
         改名或加参数时这里会失联，而 `scripts/` 不在任何 CI 的 import 图上。
    该形态由 `tests/test_import_boundaries.py::test_no_cross_package_private_symbol_imports`
    钉住（本处是它挖出的**唯一**真实违规）。
    行为等价性有实测：改造前后本脚本均 `10/10 通过`、逐条 PASS 文案一致。

运行方式（必须在生产模式下才会拦截）：
    cd backend
    AUTH_REQUIRED=true python scripts/check_tenant_isolation.py

退出码：0 = 全部通过；1 = 有用例失败
"""

import asyncio
import os
import sys
import uuid

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from sqlalchemy import select  # noqa: E402

from core.auth.accounts import ensure_owner_member, ensure_default_account  # noqa: E402
from core.auth.jwt_handler import create_token_pair  # noqa: E402
from core.config import config  # noqa: E402
from core.database import get_async_session  # noqa: E402
from core.identity.models import User, UserRole  # noqa: E402
from core.identity.router import hash_password  # noqa: E402
from core.tenant.middleware import (  # noqa: E402
    TENANT_HEADER,
    get_current_shop_id,
    get_current_shop_id_optional,
)
from core.stores import StoreRecord  # noqa: E402


def make_request(shop_id: str = None, token: str = None, method: str = "GET") -> Request:
    """构造一个最小可用的 ASGI Request，用于直接调用依赖函数"""
    headers = []
    if shop_id is not None:
        headers.append((TENANT_HEADER.lower().encode(), str(shop_id).encode()))
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))

    scope = {
        "type": "http",
        "method": method,
        "path": "/test",
        "headers": headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("127.0.0.1", 8001),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


async def ensure_user(session, email: str, role: str = "user") -> User:
    """确保测试用户存在，返回该用户"""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password("test123456"),
        name=email.split("@")[0],
        role=UserRole.ADMIN if role == "admin" else UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def ensure_store(session, owner: User, name: str) -> StoreRecord:
    """
    确保测试店铺存在（**按生产形态造**：个人账户 + owner 成员行 + 挂账户的店）。

    ★ 为什么不手插一行 `stores_store` 了事：那样 `account_id` 为空，
      归属判定会走**过渡期兜底分支**（按 owner_id 判），
      于是本脚本验证的是"过渡期行为"，而不是收拢后的真实口径
      —— 口径不同、结论可能完全相反，这种自检等于没做。
    """
    result = await session.execute(select(StoreRecord).where(StoreRecord.name == name))
    store = result.scalars().first()
    if store:
        return store

    account = await ensure_default_account(session, owner)
    await ensure_owner_member(session, account, owner)
    await session.flush()

    store = StoreRecord(
        id=f"store_{uuid.uuid4().hex[:8]}",
        name=name,
        platform="amazon_us",
        tenant_id="default_tenant",
        owner_id=owner.id,
        account_id=account.id,
    )
    session.add(store)
    await session.commit()
    await session.refresh(store)
    return store


async def expect(coro_func, expected, label: str, results: list, *, expect_value=None):
    """
    执行一个依赖调用并断言结果。

    `expected` 为 int 时按 HTTP 状态码断言（200 表示放行）；
    为 None 时断言"无异常返回的原始值 == expect_value"（读方法缺头的情形）。
    """
    try:
        result = await coro_func()
        actual = 200
        detail = f"放行 -> {result!r}"
    except HTTPException as exc:
        actual = exc.status_code
        result = None
        detail = str(exc.detail)

    if expected is None:
        ok = actual == 200 and result == expect_value
        shown = f"期望返回 {expect_value!r}"
    else:
        ok = actual == expected
        shown = f"期望 {expected}"

    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: {shown} / 实际 {actual}  ({detail})")
    return result


async def main() -> int:
    print("=" * 70)
    print("多租户隔离回归自检（业务侧 · account → store 层级）")
    print("=" * 70)
    print(f"AUTH_REQUIRED = {config.auth_required}")
    print(f"判定实现      = core/auth/accounts.py::can_access_store")
    if not config.auth_required:
        print()
        print("提示：当前为演示模式，归属校验按设计放行。")
        print("      要验证拦截行为，请用 AUTH_REQUIRED=true 运行本脚本。")

    results = []
    created_store_ids = []

    async with get_async_session() as session:
        user_a = await ensure_user(session, "tenant-test-a@example.com")
        user_b = await ensure_user(session, "tenant-test-b@example.com")
        admin = await ensure_user(session, "tenant-test-admin@example.com", role="admin")
        store_b = await ensure_store(session, user_b, "TenantB-Store")
        created_store_ids.append(store_b.id)

        token_a = create_token_pair(user_a.id, user_a.email, user_a.role.value).access_token
        token_b = create_token_pair(user_b.id, user_b.email, user_b.role.value).access_token
        token_admin = create_token_pair(admin.id, admin.email, admin.role.value).access_token

        print()
        print(f"店铺 [{store_b.name}] ({store_b.id}) 归属于账户 {store_b.account_id}")
        print(f"  账户所有者 = {user_b.email}；测试破坏者 = {user_a.email}")
        print()

        if config.auth_required:
            print("用例：")
            # 1. A 带着自己的合法 token 用 B 的店铺 ID -> 403
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_a), session),
                403, "用户A token 冒充 用户B 的店铺", results,
            )
            # 2. 所有者 B 访问自己的店铺 -> 放行
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_b), session),
                200, "所有者B 访问自己的店铺", results,
            )
            # 3. 平台超管跨账户 -> 放行
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_admin), session),
                200, "平台超管 跨账户访问", results,
            )
            # 4. 无 token -> 401
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, None), session),
                401, "无 token 访问", results,
            )
            # 5. 伪造 token -> 401
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, "fake.token.value"), session),
                401, "伪造 token 访问", results,
            )
            # 6. 不存在的店铺 ID -> 403（**不是 404**：不泄露存在性）
            await expect(
                lambda: get_current_shop_id(
                    make_request("store_ffffffff", token_b), session),
                403, "不存在的店铺 ID（应为 403 而非 404）", results,
            )
            # 7. 缺 X-Shop-ID + 写方法 -> 400（空值守卫）
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, token_b, method="POST"), session),
                400, "写方法缺 X-Shop-ID", results,
            )
            # 8. 缺 X-Shop-ID + 读方法 -> 返回 None（端点回空列表）
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, token_b, method="GET"), session),
                None, "读方法缺 X-Shop-ID（应返回 None）", results, expect_value=None,
            )
            # 9. 纯空白头 + 写方法 -> 400（不能被当成合法店铺 ID）
            await expect(
                lambda: get_current_shop_id(
                    make_request("   ", token_b, method="POST"), session),
                400, "写方法 + 纯空白 X-Shop-ID", results,
            )
            # 10. get_current_shop_id_optional（对话/导航入口）缺头 -> 返回 None，不 400
            await expect(
                lambda: get_current_shop_id_optional(
                    make_request(None, token_b, method="POST"), session),
                None, "对话入口缺头（不应 400）", results, expect_value=None,
            )
        else:
            print("用例：")
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, None), session),
                200, "演示模式：无 token 也放行（保证演示可用）", results,
            )
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, None, method="POST"), session),
                400, "演示模式：写方法缺头仍 400（空值守卫与身份无关）", results,
            )

        # ---- 清理：只删本脚本造出来的店（保留用户，便于复跑）----
        for sid in created_store_ids:
            await session.execute(
                StoreRecord.__table__.delete().where(StoreRecord.id == sid)
            )
        await session.commit()

    print()
    passed = sum(1 for r in results if r)
    print(f"结果: {passed}/{len(results)} 通过")
    print("=" * 70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""
多租户隔离回归测试

验证 core/tenant/middleware.py 的归属校验是否真正生效：
  - 用户 A 的 token 访问用户 B 的店铺 -> 403
  - 店铺所有者本人访问                -> 放行
  - 管理员越权访问                    -> 放行（设计如此）
  - 无 token                          -> 401
  - 演示模式（AUTH_REQUIRED=false）   -> 全部放行（不应破坏本地演示）

运行方式（必须在生产模式下才会拦截）：
    cd backend
    AUTH_REQUIRED=true python scripts/check_tenant_isolation.py

退出码：0 = 全部通过；1 = 有用例失败
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from sqlalchemy import select  # noqa: E402

from core.config import config  # noqa: E402
from core.database import get_async_session  # noqa: E402
from core.auth.jwt_handler import create_token_pair  # noqa: E402
from core.tenant.middleware import (  # noqa: E402
    get_tenant_from_header,
    require_shop_owner,
    TENANT_HEADER,
    tenant_context,
)
from modules.user_subscription.models import User, UserRole, Shop  # noqa: E402
from modules.user_subscription.router import hash_password  # noqa: E402


def make_request(shop_id: str = None, token: str = None) -> Request:
    """构造一个最小可用的 ASGI Request，用于直接调用依赖函数"""
    headers = []
    if shop_id:
        headers.append((TENANT_HEADER.lower().encode(), shop_id.encode()))
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))

    scope = {
        "type": "http",
        "method": "GET",
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


async def ensure_shop(session, owner: User, name: str) -> Shop:
    """确保测试店铺存在，返回该店铺"""
    result = await session.execute(select(Shop).where(Shop.name == name))
    shop = result.scalar_one_or_none()
    if shop:
        return shop

    shop = Shop(
        id=str(uuid.uuid4()),
        owner_id=owner.id,
        name=name,
        platform="amazon_us",
        is_active=True,
    )
    session.add(shop)
    await session.commit()
    await session.refresh(shop)
    return shop


async def expect_http(coro_func, expected_status: int, label: str, results: list):
    """执行一个依赖调用，断言抛出的 HTTPException 状态码"""
    try:
        result = await coro_func()
        actual = 200
        detail = "放行"
    except HTTPException as exc:
        actual = exc.status_code
        result = None
        detail = str(exc.detail)

    ok = actual == expected_status
    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: 期望 {expected_status} / 实际 {actual}  ({detail})")
    return result


async def main() -> int:
    print("=" * 68)
    print("多租户隔离回归测试")
    print("=" * 68)
    print(f"AUTH_REQUIRED = {config.auth_required}")
    if not config.auth_required:
        print()
        print("提示：当前为演示模式，归属校验按设计放行。")
        print("      要验证拦截行为，请用 AUTH_REQUIRED=true 运行本脚本。")

    results = []

    async with get_async_session() as session:
        user_a = await ensure_user(session, "tenant-test-a@example.com")
        user_b = await ensure_user(session, "tenant-test-b@example.com")
        admin = await ensure_user(session, "tenant-test-admin@example.com", role="admin")
        shop_b = await ensure_shop(session, user_b, "TenantB-Shop")

        token_a = create_token_pair(user_a.id, user_a.email, user_a.role.value).access_token
        token_b = create_token_pair(user_b.id, user_b.email, user_b.role.value).access_token
        token_admin = create_token_pair(admin.id, admin.email, admin.role.value).access_token

        # require_shop_owner 是同步工厂，返回 async checker（此处直接注入 shop）
        owner_checker = require_shop_owner()
        tenant_context.clear()

        print()
        print(f"店铺 [{shop_b.name}] 归属于用户 B ({user_b.email})")
        print()

        if config.auth_required:
            print("用例：")
            # 1. 用户 A 带着自己的合法 token 访问 B 的店铺 -> 403
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, token_a), session),
                403,
                "用户A token 访问 用户B 店铺",
                results,
            )
            # 2. 店铺所有者 B 访问自己的店铺 -> 放行
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, token_b), session),
                200,
                "所有者B 访问自己的店铺",
                results,
            )
            # 3. 管理员越权访问 -> 放行
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, token_admin), session),
                200,
                "管理员 跨租户访问",
                results,
            )
            # 4. 无 token -> 401
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, None), session),
                401,
                "无 token 访问",
                results,
            )
            # 5. 伪造 token -> 401
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, "fake.token.value"), session),
                401,
                "伪造 token 访问",
                results,
            )
            # 6. require_shop_owner 同样拦截（A 访问 B 的店铺）
            await expect_http(
                lambda: owner_checker(make_request(shop_b.id, token_a), session, shop_b),
                403,
                "require_shop_owner 拦截 A",
                results,
            )
            # 7. require_shop_owner 放行所有者
            await expect_http(
                lambda: owner_checker(make_request(shop_b.id, token_b), session, shop_b),
                200,
                "require_shop_owner 放行 B",
                results,
            )
            # 8. 缺少 X-Shop-ID 头 -> 400
            await expect_http(
                lambda: get_tenant_from_header(make_request(None, token_b), session),
                400,
                "缺少 X-Shop-ID 头",
                results,
            )
        else:
            print("用例：")
            await expect_http(
                lambda: get_tenant_from_header(make_request(shop_b.id, None), session),
                200,
                "演示模式：无 token 也放行（保证演示可用）",
                results,
            )

    print()
    passed = sum(1 for r in results if r)
    print(f"结果: {passed}/{len(results)} 通过")
    print("=" * 68)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

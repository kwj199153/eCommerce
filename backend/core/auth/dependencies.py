"""
认证依赖注入

提供 FastAPI 依赖项：get_current_user, get_optional_user 等。
用于保护需要认证的 API 端点。
"""

from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.database import get_db
from core.auth.jwt_handler import verify_token, TokenData
from modules.user_subscription.models import User


# OAuth2 密码模式（自动从请求头提取 Bearer Token）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    获取当前登录用户（必须认证）

    用法：
        @router.get("/protected")
        async def protected_route(current_user: User = Depends(get_current_user)):
            return {"user_id": current_user.id}

    Raises:
        HTTPException 401: Token 无效或过期
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. 验证 Token
    token_data: Optional[TokenData] = verify_token(token, expected_type="access")
    if not token_data or not token_data.user_id:
        raise credentials_exception

    # 2. 查找用户
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise credentials_exception

    # 3. 检查用户状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    return user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    获取当前用户（可选认证）

    如果提供了有效 Token 则返回用户，否则返回 None。
    用于既支持匿名又支持登录用户的接口。
    """
    if not token:
        return None

    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    获取管理员用户（必须是 admin 角色）

    Raises:
        HTTPException 403: 非管理员
    """
    if current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


def require_permissions(*required_roles: str):
    """
    权限检查装饰器工厂

    用法：
        @router.get("/admin-only")
        async def admin_only(user: User = Depends(require_permissions("admin"))):
            return {"data": "sensitive info"}
    """
    async def permission_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role.value not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要以下权限之一: {', '.join(required_roles)}",
            )
        return current_user
    return permission_checker


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    获取当前活跃用户（必须认证且账号正常）

    与 get_current_user 相同，但额外检查 is_active 状态。
    用于需要确保用户账号正常的场景。
    """
    return current_user


async def require_auth_if_enabled(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    受开关控制的鉴权依赖（用于路由级批量挂载）

    行为：
      - config.auth_required = False（演示模式，默认）：直接放行，返回 None
      - config.auth_required = True（生产模式）：
          * 缺少 / 格式错误的 Authorization 头 -> 401
          * Token 无效、过期或用户不存在  -> 401
          * 用户被禁用                    -> 403
          * 校验通过                      -> 返回 User 对象

    用途：在 main.py 里以 router 级别挂载，一处覆盖整个模块的所有端点，
         例如 app.include_router(xxx_router, dependencies=[Depends(require_auth_if_enabled)])

    注意：此依赖只做「认证」（你是谁），不做「授权」（你能不能动这条数据）。
         数据级归属校验需配合 require_shop_owner / 业务层 tenant 过滤。
    """
    if not config.auth_required:
        return None

    auth_header = request.headers.get("Authorization") or ""
    scheme, _, raw_token = auth_header.partition(" ")
    token = raw_token.strip()

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭据，请在 Authorization 头中提供 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await get_current_user(token=token, db=db)

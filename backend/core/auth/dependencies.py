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
from core.identity.models import User
# ★ P0-2（2026-09-16）：把"你是谁 / 你从哪来"写进请求上下文，
#   供日志、审计、指标统一读取（此前 user_id 恒为空串，见 context.py docstring）。
from core.middleware.client_ip import client_ip
from core.observability.context import set_request_context


# OAuth2 密码模式（自动从请求头提取 Bearer Token）
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    获取当前登录用户（必须认证）

    ★ P0-2（2026-09-16）：校验全部通过后，把 `user_id`（+ 兜底 `client_ip`）
      写进请求上下文。**这是 `current_user_id()` 全项目唯一的写入点。**

      修复前：`set_request_context` 全仓只有一个调用点（请求日志中间件），
      且它不传 user_id ⇒ `observability/context.py` 里的 `_user_id_var`
      是**装饰品**，任何"按用户聚合"的日志 / 审计 / 指标都只能拿到空串。

    ⚠️ 写入位置必须在**全部校验之后**（不是函数开头）：
      被撤销的 token、被禁用的账号都不该在上下文里留下"是谁" ——
      否则一条 401/403 的日志看起来会像"这个用户成功访问过某接口"。

    ★★★ `request: Request` **必须写裸类型**，不能写 `Optional[Request]`
        （实测踩过，见 `_probe` 记录）：FastAPI 判定"这个参数是不是框架特判的
        Request 注入项"用的是
            lenient_issubclass(type_annotation, Request)   # dependencies/utils.py:320
        它拿的是**原始注解**；`Optional[Request]` 是 Union，`lenient_issubclass`
        对它返回 False ⇒ 该参数被当成 Pydantic 字段去解析 ⇒ 路由注册期直接抛
            FastAPIError: Invalid args for response field!
        后果不是"少一个字段"，而是 **import main 失败、整个应用起不来**。
        所以本文件三个依赖都用裸 `Request`。

    ⚠️ `request` 为必填（无默认值）：本函数有内部调用方
      （`get_optional_user` / `require_auth_if_enabled`），它们都持有 Request
      并显式传入。若将来出现拿不到 Request 的调用方，请**不要**改回
      `Optional[Request]`（见上一条），而是改用 `Request` 之外的显式传参。

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

    # 2.5 凭据版本比对（★ P1-b 2026-09-16）—— 整批撤销的**唯一**落点
    #
    #   改密 / 重置密码 / 「登出所有设备」都会把 users.token_version +1；
    #   本步比对即让全部旧 token 失效。
    #   为什么放在 is_active 之前：版本不匹配的凭据根本不该被当作"有效身份"
    #   继续往下走，先判它可以让错误语义更准确。
    from core.auth.revocation import token_version_matches

    if not token_version_matches(token_data.token_version, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭据已失效（密码已变更或已登出所有设备），请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 检查用户状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 4. 单枚撤销（jti 黑名单，Redis；★ fail-open，理由见 core/auth/revocation.py）
    from core.auth.revocation import is_jti_revoked

    if await is_jti_revoked(token_data.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该登录凭据已登出",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ★ P0-2：全部校验通过 —— 此刻这个请求"确实属于 user.id"，写进上下文。
    set_request_context(user_id=user.id)
    if request is not None:
        # 中间件通常已经写过 client_ip；这里是"直接调用本函数"路径的兜底
        # （`None` 会被 set_request_context 跳过，不会把已有值清掉）。
        set_request_context(client_ip=client_ip(request))

    return user


async def get_optional_user(
    request: Request,
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
        return await get_current_user(request=request, token=token, db=db)
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
    ★ P1-c（2026-09-16）更正：这里此前写「需配合 require_shop_owner」——
      那是**账户侧**（shops 表 / UUID）的权限工厂（★ C4 已随账户侧收拢
      整体删除，`core/tenant/middleware.py` 里也不再有该符号），
      而业务数据全部按
      业务侧 `stores_store.id`（store_xxx）分区。照那句话去做会把两套
      ID 空间接错（业务路由去查错表）。业务侧的正确做法是挂
      `core.tenant.middleware.get_current_shop_id*`，由它做归属校验
      （403 语义）并返回已校验的 ID。
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

    return await get_current_user(request=request, token=token, db=db)

async def require_authenticated_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    *,
    what: str = "该功能",
) -> User:
    """
    **强制身份**（fail-closed）：拿不到有效身份一律 401，绝不静默放行。

    ★ 与 `require_auth_if_enabled` 的分工：
      - 后者服务于「业务数据按店铺分区」的路由级批量挂载（`BUSINESS_AUTH`），
        它把 `config.auth_required` 当**整块功能的总开关**：关掉时返回 None，
        语义是"演示模式，业务数据不设限"；
      - 本函数服务于**身份与授权数据**（账户、成员、自助资料管理）——
        这类东西说不清"你是谁"就不该能读，更不该能改。

    ★★★ 2026-09-16 修正：本函数**不再受 `config.auth_required` 影响**。

      旧实现直接复用 `require_auth_if_enabled`，而后者在
      `auth_required=False` 时**第一步就 `return None`（连 token 都不解析）**
      ⇒ 本地演示模式（`AUTH_REQUIRED=false`，正是本地 `.env` 的默认值）下，
      **哪怕带着一枚完全合法的 JWT 也一律 401**。造成的实际后果不是
      "演示模式不开放该功能"，而是：

        * 「团队成员」页在本地**永久打不开**（无论是否已登录）；
        * 401 文案让用户"先去登录"——**登录了结果一样是 401**，
          等于把人指向一个解决不了问题的方向；
        * 前端 `request.ts` 又对 demo-token 的 401 静默处理 ⇒
          连"失败"这个事实都没能落到任何登录入口上。

      「演示模式不开放」的正确表达是「**没有真身份就不放行**」，
      而不是「**有真身份也不放行**」。所以本函数只判定一件事：
      这枚 Bearer token 是不是有效的、且属于一个真实存在的用户。

    ★ 为什么把判定收成一份（第 100 轮）：
      这条 fail-closed 判定原本在 `core/auth/accounts_router.py::_current_user`
      里写了一遍；补 `core/identity/users_router.py` 时又需要一模一样的一遍。
      ⇒ 按项目判据「同一判定出现两份实现 ⇒ 至少有一份永远测不到」，
        收敛到这里，调用方只传**主语**（`what`），判定逻辑唯一。

    ★ `what` 只影响文案，不影响行为：要说清"是哪个功能需要登录"，
      否则用户不知道自己在哪一步被拦住。

    Raises:
        HTTPException 401: 缺少 / 格式错误的 Bearer 头，或 token 无效、
                           已过期、已撤销、对应用户不存在。
    """
    auth_header = request.headers.get("Authorization") or ""
    scheme, _, raw_token = auth_header.partition(" ")
    token = raw_token.strip()

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{what}需要登录，请先登录后再操作。",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 有 token 就按**真身份**校验：无效 / 过期 / 已撤销 / 用户不存在
    # 会各自抛出准确原因（比统一回一句"请登录"更有诊断价值，
    # 也让前端能据 "认证/Token" 关键字触发一次 token 刷新）。
    return await get_current_user(request=request, token=token, db=db)

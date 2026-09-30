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

# ★ 前端演示哨兵串的前缀 —— 定义已**下移**到 `core/auth/demo_identity.py`
#   （第 182 轮）。理由：它和「解析成谁」是同一件事的两半，分开放会让将来
#   改哨兵串的人只改到一半。这里 re-export 一次，保持既有调用点不变。
from core.auth.demo_identity import (  # noqa: E402
    DEMO_SENTINEL_PREFIX,
    is_demo_credential,
    is_demo_request,
    resolve_demo_user,
)


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
    # ★ 第 327 轮收口：改用平台超管的**唯一真源** `is_platform_admin()`
    #   （core/auth/accounts.py）。此前这里硬编码 `role.value != "admin"`，
    #   与真源构成**两份实现** —— 两者各自演进时，「谁能读审计 / 谁能看计费」
    #   这类判定会悄悄分叉，而分叉只表现为某个入口偶尔放行或拒绝，没有报错。
    #   ★ 函数内 import：accounts 顶层会拉 core.identity.* 的包初始化，
    #     而 identity 侧又依赖 auth，顶层互相 import 会把初始化顺序变成隐式约束。
    from core.auth.accounts import is_platform_admin

    if not is_platform_admin(current_user):
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
    受开关控制的鉴权依赖（用于路由级批量挂载）—— **optional auth（可选用户）**

    ★★★ 2026-09-17 语义修正（起因：老板反馈「真实登录后仍看到别人的 4 个店铺」）

      旧实现是「`auth_required=False` ⇒ 第一步 `return None`，**连 Authorization
      头都不解析**」。它把两件不同的事搓成了一件，后果不是"演示模式不设限"，
      而是**连真实登录用户的身份也拿不到**：

        · `accounts.filter_accessible_stores(db, None, stores)` 走
          `user is None → return list(stores)` ⇒ **任何登录用户看到全库店铺**；
          （★ 2026-09-17：该函数已收紧为 `user is None → []`；第 175～177 轮
            进一步改为「无身份 ⇒ 只给演示店铺」，此处描述的是**当时**的形态。）
        · `accounts.can_access_store` / `_matches` 的 `user is None → True`
          ⇒ 伪造 `X-Shop-ID` 就能读写任意店铺的业务数据（演示模式下 BOLA 原样回归）。
          （★ 第 177 轮：该分支已收紧为「只放行演示店铺」—— 单店路径与列表路径
            现已同一处判定；此处描述的是**当时**的形态。）

      正确形态是 **optional auth**（有凭据就解析，没有才看开关），三档行为：

        ① 有 `Authorization: Bearer <token>`
             · token 是演示哨兵（`demo-` 前缀）且 `config.demo_mode=True`
               → **解析成演示账号主人**（★ 第 182 轮起是真 `User`，不再是 `None`）
             · 否则 → **强制解析真身份**（`get_current_user`）：
                 无效 / 过期 / 已撤销 / 用户不存在 → 401；用户被禁用 → 403
             ★ 这一档是本次修复的核心：带真 token 就必须拿到真身份，
               否则下游所有「user is None → 放行」的归属分支会整体失效。

        ② 无 `Authorization` 头（真正的匿名访问）
             · `config.auth_required=False` → 返回 None（本地匿名联调，行为不变）
             · `config.auth_required=True`  → 401

    ★ 为什么演示哨兵要 `demo_mode` 单独把关（而不是直接认字符串）：
      `demo-token` 就明文写在前端源码里（frontend/src/config/demoMode.ts），
      任何会读代码的人都能带上它。所以它是「本地演示开关」，不是「身份」——
      生产必须为 false（由 `config._enforce_production_safety` 硬拦）。

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
    auth_header = request.headers.get("Authorization") or ""
    scheme, _, raw_token = auth_header.partition(" ")
    token = raw_token.strip()
    has_bearer = scheme.lower() == "bearer" and bool(token)

    # ① 演示哨兵：**只在 demo_mode 打开时承认**，且解析成**演示账号主人**。
    #    生产（demo_mode=False）下它和任意伪造串一样，落到 ② 被 401 拒绝。
    #
    # ★★★ 第 182 轮：这里返回的**不再是 `None`**，而是真 `User` 行。
    #    需求原文「演示模式也当作一个真实的账号，只是无需账号密码。也有全套功能」。
    #    返真主角之后，`ensure_default_account` / `filter_accessible_skills` /
    #    `can_access_skill` 全部**一行不改**就能工作 —— 演示模式因此拿到与真实
    #    账号同等的读写能力，而不是一份"只读体验版"。
    #
    #    ⚠️ 「具体是谁」**不在这一层决定**（这里只认得那枚哨兵串）。
    #    它是 `config.demo_account_email` 决定的 —— 见 `demo_identity.py` 的长论证：
    #    前端源码公开，让客户端传 user_id 等于任何人改一行就能冒充任意身份。
    # ★ 第 220 轮：这条判定收口到 `demo_identity.is_demo_request`（唯一真源）——
    #   此前本文件里手写了两份（另一处在 `get_acting_user`），且两份不一致。
    if is_demo_request(request):
        if config.auth_required:
            # demo_mode 与 auth_required 同时为真属配置矛盾（生产护栏已拒绝启动），
            # 这里按更严格的一侧生效：不承认这个身份。
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="演示身份不可用：当前环境要求真实登录。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        demo_user = await resolve_demo_user(db, allow_demo=True)
        if demo_user is not None:
            # 与 `get_current_user` 同口径：**守卫全过之后**才写上下文。
            # ★ 演示身份既然是一个真身份，日志/审计就该记下"是谁做的" ——
            #   这正是第 181 轮那些"无身份 ⇒ 删了也查不出是谁"问题的解法。
            set_request_context(user_id=demo_user.id)
            set_request_context(client_ip=client_ip(request))
        return demo_user

    # ② 带了自称为 Bearer 的凭据 ⇒ 一律按**真身份**强制校验。
    #    ★★★ 本次修复的核心：修复前这一步被 `if not config.auth_required: return None`
    #    挡在前面，导致真实登录用户也拿不到身份 ⇒ 归属过滤整体失效
    #    （老板看到的"4 个店铺"就是这么漏出来的）。
    if has_bearer:
        return await get_current_user(request=request, token=token, db=db)

    # ③ 完全没带凭据（真匿名）⇒ 由 auth_required 决定放不放行。
    if not config.auth_required:
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少认证凭据，请在 Authorization 头中提供 Bearer Token",
        headers={"WWW-Authenticate": "Bearer"},
    )

async def require_authenticated_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    *,
    what: str = "该功能",
) -> User:
    """
    **强制身份**（fail-closed）：拿不到有效身份一律 401，绝不静默放行。

    ★ 与 `require_auth_if_enabled` 的分工（★ 2026-09-17 更新：两者语义已对齐）：
      - 后者服务于「业务数据按店铺分区」的路由级批量挂载（`BUSINESS_AUTH`）：
        它现在是 **optional auth** —— 带了真 token 就**必须**解析出身份
        （这条对多租户隔离是必需的，见其 docstring 的修复记录）；只有
        **完全不带凭据**时才可能返回 None（`config.auth_required=False` 的匿名放行）。
      - 本函数服务于**身份与授权数据**（账户、成员、自助资料管理）——
        这类东西说不清"你是谁"就不该能读，更不该能改，故**不接受任何匿名**。

      ⚠️ 两者唯一的差别是「demo 哨兵算不算身份」：`require_auth_if_enabled` 在
        `config.demo_mode=True` 下承认 `demo-token` 为**匿名演示**（仍拿不到归属），
        而本函数**永远不认** —— 身份数据编不出一份可降级的"你的团队成员"。

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


async def get_acting_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """解析「本次请求**究竟以谁的身份**在做事」（第 182 轮）。

    ★★★ 与 `require_auth_if_enabled` 的关系：**语义不同，不能互相替代**。

      `require_auth_if_enabled` 把演示哨兵解析成演示账号主人 —— 对**业务数据**
      （店铺、技能这类有归属的资源）这是对的：演示模式要能真的读写演示账号的数据。

      但对**身份与授权数据**（账户、成员、自助资料）不行：那里 `require_authenticated_user`
      明确写着「演示哨兵**永远不算身份**」—— 因为「我的团队成员」这种东西
      编不出一份可降级的"演示版"。两者是**刻意的不同**，不是不一致。

    ★ 那这个函数是干什么的？
      给「**既要演示身份可读、又要演示身份可写**」的资源用 —— 当前唯一调用方是
      `modules/skills/router.py`（技能仓库）。

      技能在本轮需求里是「演示账号也有全套功能」的直接对象：老板要求
      「演示模式也当作一个真实的账号 …… 也有全套功能，目前无法编辑 skill」。
      所以它的读口与写口**都必须**认得演示身份，而演示身份此前只会被解析成
      `None` —— 于是服务层的 `create_skill(user is None) ⇒ PermissionError`
      把写口整体封死（那正是老板截图里"按钮全灰"的后端一半）。

      第 182 轮之后 `require_auth_if_enabled` 自己就会返回真主角，
      本函数因此在**当前**实现下与它等价 —— 那为什么还要单独一个？

        ① 它把意图写进签名：「这个端点要的是**行动者**，不是匿名访客」。
           将来若有人把 `require_auth_if_enabled` 改回返回 `None`（或给它加
           "演示只读"档），技能写口会**静默失效**且没有一处报错 —— 那正是
           第 181 轮踩过的形态。独立函数让这种改动至少**显式**地影响本入口。
        ② 它把演示解析与「真 token ⇒ 必须解析」两件事**并列写出来**，
           而 `require_auth_if_enabled` 的 ① 档里这两件事是交织的。

    ★ 降级是安全的：守卫不通过（`demo_mode=False` / 找不到账号 / 账号是超管 /
      账号被停用）⇒ 拿到的就是 `None` ⇒ 服务层照旧 403。
      **投影到更窄的权限，永远不投影到更宽的权限。**
    """
    # ★ 第 220 轮：判定收口到 `demo_identity.is_demo_request`（唯一真源）。
    #   ★ 这是**收紧**：旧写法少了 `scheme == "bearer"` 那一半，于是
    #     `Authorization: Demo demo-token` 这类非 Bearer 头在此处会被认成演示
    #     身份，而在 `require_auth_if_enabled` 那里不会 —— 收口后两处一致。
    if is_demo_request(request):
        if config.auth_required:
            # 与 `require_auth_if_enabled` 的 ① 档同一处置：配置矛盾时取更严的一侧。
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="演示身份不可用：当前环境要求真实登录。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        demo_user = await resolve_demo_user(db, allow_demo=True)
        if demo_user is not None:
            set_request_context(user_id=demo_user.id)
            set_request_context(client_ip=client_ip(request))
            return demo_user
        # 守卫没过 ⇒ 落到下面的「真身份 / 匿名」两条路（**不在这里返回 None**：
        # 万一调用方传的是"demo- 前缀但其实是真 token"的串，
        # 仍应走完整的真身份校验，而不是被一句断言直接判成匿名）。
        # ★ 边界说明：`is_demo_credential` 只看前缀，理论上一枚以 "demo-" 开头的
        #   真 token 会走到这里而 demo 解析返回 None。此时 `get_current_user`
        #   的验签会给出准确结论（真 token 通过、伪造串 401）—— 这正是期望行为。

    # 非演示凭据（或演示守卫未过）：完全交回既有的 optional-auth 语义，不复制口径。
    return await require_auth_if_enabled(request=request, db=db)


async def require_acting_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """**行动者**（fail-closed）：认演示身份，但**真匿名一律 401**。

    ==========================================================================
    ★★ 为什么需要它：`get_acting_user` 的返回类型是 `Optional[User]`
    ==========================================================================

      `get_acting_user` 在「完全不带凭据 + `config.auth_required=False`」
      这一档会返回 `None`（本地匿名联调档，是**刻意**的）。
      纯读口可以接受它（`None` = 匿名访客，按最窄可见性投影）；
      但凡是服务端要**以某个人的名义落一行数据**的端点（计费就是典型：
      `Invoice.user_id`、`Subscription.user_id` 都是非空外键），
      `None` 不是"少给一点权限"，而是下一步 `current_user.id` 直接
      `AttributeError` ⇒ 500。

      ★ 500 是最坏的结局：它既不是"你没登录"（用户该去登录）也不是
        "你没权限"（用户该换账号），而是一条**归因反向**的信号 ——
        用户看到"服务器错误"，运维去翻栈找 bug，真因只是没带 token。

    ---- 与相邻三个依赖的定位（四格全是刻意分开的，不是一个函数的四种退化）----

        · `get_current_user`            带凭据必验真身份；演示哨兵 ⇒ 401（不认）
          `require_authenticated_user`  = 上一条的 fail-closed 形态（拒绝一切匿名），
                                         **永远不认**演示哨兵
          `get_acting_user`             认演示哨兵；**接受** `None`
          `require_acting_user`         认演示哨兵；**拒绝** `None`  ← 本函数

      ⇒ `require_acting_user` 与 `require_authenticated_user` 的差别**只有一格**：
        「演示哨兵算不算身份」。前者算（演示身份是一个真 `User`，
        有 `Account` 容器，写进去的归属有地方落），后者不算
        （「我的团队成员」编不出一份可降级的"演示版"）。

      ⇒ 它与 `get_current_user` 的差别也**只有一格**：「演示哨兵算不算身份」。
        同形先例：`modules/skills/router.py` 第 182 轮把技能写口
        从 `require_auth_if_enabled` 换成 `get_acting_user` 时，
        走的就是这条判据（老板原文：「演示模式也当作一个真实的账号……
        也有全套功能」）。

    ==========================================================================
    ★★ 为什么是 401 而不是 403
    ==========================================================================
      本函数取代的位置此前是 `get_current_user`，它在"无凭据"时给 **401**。
      401（"你是谁都没说清"）与 403（"我知道你是谁，但你不能动这个"）会
      触发前端**完全不同**的动作：401 去登录、403 提示换账号。
      把 401 改成 403 会让"没登录"变成一句**用户无法自行解决**的提示，
      而 `request.ts` 也不会再触发登录跳转。路径依赖保持原样 = 401。

    ★ 本函数**不**自己复制判定：`is_demo_request` / `resolve_demo_user` /
      三重守卫全部在 `get_acting_user` 里，这里只做"投影到更窄"的那一步
      （`None` ⇒ 401）。本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。

    Raises:
        HTTPException 401: 无凭据（真匿名），或 `demo_mode & auth_required`
                           同时为真（配置矛盾，取更严的一侧），或演示
                           解析的三重守卫未过。
    """
    user = await get_acting_user(request=request, db=db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证凭据，请在 Authorization 头中提供 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

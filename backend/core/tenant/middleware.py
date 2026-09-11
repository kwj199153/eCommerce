"""
多租户中间件

实现租户识别、数据隔离等核心逻辑。
支持从 Header 或 Token 中提取 tenant_id（shop_id）。
"""

import contextvars
from typing import Optional
from fastapi import Request, HTTPException, status, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from core.database import get_db
from core.auth.dependencies import require_auth_if_enabled
from modules.user_subscription.models import Shop


# ====== 常量 ======

# 请求头中的租户标识
TENANT_HEADER = "X-Shop-ID"

# 查询参数中的租户标识
TENANT_QUERY_PARAM = "shop_id"


# ====== 租户上下文 ======

class TenantContext:
    """
    租户上下文（请求级「值对象」）

    只读：仅暴露 shop / shop_id / is_set 属性，不提供原地修改方法。
    所有写入统一走 `tenant_context.xxx` 代理（替换式更新 ContextVar），
    避免出现「两个实例各改各的」这类语义分裂。
    """

    __slots__ = ("_shop", "_shop_id")

    def __init__(self, shop: Optional[Shop] = None, shop_id: Optional[str] = None):
        object.__setattr__(self, "_shop", shop)
        object.__setattr__(
            self, "_shop_id",
            shop_id if shop_id is not None else (shop.id if shop else None),
        )

    def __setattr__(self, key, value):
        raise AttributeError("TenantContext 是只读值对象，请通过 tenant_context 代理写入")

    @property
    def shop(self) -> Optional[Shop]:
        """当前店铺对象"""
        return self._shop

    @property
    def shop_id(self) -> Optional[str]:
        """当前店铺 ID"""
        return self._shop_id

    @property
    def is_set(self) -> bool:
        """是否已设置租户"""
        return self._shop_id is not None


# ====== 请求级租户上下文（ContextVar 隔离）======
#
# 修复记录：原先这里是模块级单例 `tenant_context = TenantContext()`，
# 所有请求共享同一个可变对象。异步并发下（同一 worker 内多个请求交错
# 执行）会导致 A 请求读到 B 请求的 shop，属于跨请求数据串扰。
#
# 现改为 ContextVar + 「替换式写入」：
#   1. 每个请求（asyncio Task）持有自己的上下文副本，天然隔离；
#   2. 写入时构造新实例并 set 进 ContextVar，而不是原地改字段——
#      这样即便某个 Task 继承了父级 Context 里的旧实例，写入也不会
#      污染父级或兄弟 Task。
_tenant_context_var: contextvars.ContextVar[Optional[TenantContext]] = contextvars.ContextVar(
    "tenant_context", default=None
)


def _read_context() -> TenantContext:
    """读取当前请求的上下文实例（懒创建，内部使用）"""
    ctx = _tenant_context_var.get()
    if ctx is None:
        ctx = TenantContext()
        _tenant_context_var.set(ctx)
    return ctx


def _update_context(**changes) -> TenantContext:
    """
    以「替换」语义更新当前请求上下文，返回新实例。

    不在旧实例上原地改字段，而是构造新实例并 set 进当前 Context。
    """
    cur = _tenant_context_var.get()
    cur_shop = cur._shop if cur else None
    cur_shop_id = cur._shop_id if cur else None

    new_shop = changes.get("shop", cur_shop)
    new_shop_id = changes.get("shop_id", cur_shop_id)
    if "shop" in changes and changes["shop"] is not None and "shop_id" not in changes:
        new_shop_id = changes["shop"].id

    new_ctx = TenantContext(shop=new_shop, shop_id=new_shop_id)
    _tenant_context_var.set(new_ctx)
    return new_ctx


class _TenantContextProxy:
    """
    租户上下文代理（对外唯一入口）

    - 读：`tenant_context.shop_id` / `.shop` / `.is_set` 转发到当前请求实例
    - 写：`set_shop` / `set_shop_id` / `clear` 走「替换式」更新，保证 Task 隔离

    保留此代理是为了让既有的 `tenant_context.set_shop(...)` 等调用点无需修改。
    """

    __slots__ = ()

    def set_shop(self, shop: Shop) -> TenantContext:
        return _update_context(shop=shop, shop_id=shop.id)

    def set_shop_id(self, shop_id: str) -> TenantContext:
        return _update_context(shop_id=shop_id)

    def clear(self) -> TenantContext:
        return _update_context(shop=None, shop_id=None)

    @property
    def shop(self) -> Optional[Shop]:
        return _read_context().shop

    @property
    def shop_id(self) -> Optional[str]:
        return _read_context().shop_id

    @property
    def is_set(self) -> bool:
        return _read_context().is_set


# 请求级租户上下文入口（所有读写都落在当前请求的 ContextVar 上）
tenant_context = _TenantContextProxy()


def get_tenant_context() -> _TenantContextProxy:
    """
    获取当前请求的租户上下文入口。

    返回代理而非裸实例，确保调用方拿到的永远是安全（替换式）语义。
    """
    return tenant_context


# ====== 依赖注入函数 ======

async def get_tenant_from_header(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Shop:
    """
    从请求头获取当前租户（店铺）

    用法：
        @router.get("/products")
        async def list_products(shop: Shop = Depends(get_tenant_from_header)):
            # shop 就是当前选中的店铺
            return {"shop_name": shop.name}

    归属校验：当 config.auth_required 为 True 时，会强制校验当前登录用户
    是目标店铺的所有者（admin 角色可跨租户访问），否则 401/403。
    """
    # 1. 从请求头提取 shop_id
    shop_id = request.headers.get(TENANT_HEADER)

    if not shop_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"缺少请求头: {TENANT_HEADER}",
        )

    # 2. 查询店铺
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"店铺不存在: {shop_id}",
        )

    if not shop.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该店铺已被禁用",
        )

    # 2.5 归属校验（仅在启用鉴权时强制；演示模式放行）
    #     修复前：只要知道 shop_id 即可读写任意店铺数据
    current_user = await require_auth_if_enabled(request, db)
    if current_user is not None:
        if current_user.role.value != "admin" and shop.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问该店铺",
            )

    # 3. 设置到上下文
    tenant_context.set_shop(shop)

    return shop


async def get_optional_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[Shop]:
    """
    获取可选的租户（不强制要求）

    如果提供了 shop_id 则返回店铺，否则返回 None。
    用于支持全局操作或店铺级操作的接口。
    """
    shop_id = (
        request.headers.get(TENANT_HEADER)
        or request.query_params.get(TENANT_QUERY_PARAM)
    )

    if not shop_id:
        return None

    try:
        return await get_tenant_from_header(request, db)
    except HTTPException:
        return None


async def get_tenant_from_query(
    shop_id: Optional[str] = Query(None, description="店铺 ID"),
    db: AsyncSession = Depends(get_db),
) -> Optional[Shop]:
    """
    从查询参数获取租户

    用于 GET 请求中通过 ?shop_id=xxx 指定店铺的场景。
    """
    if not shop_id:
        return None

    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if shop and shop.is_active:
        tenant_context.set_shop(shop)
        return shop

    return None


# ====== 轻量店铺 ID 依赖（数据层隔离用） ======

async def get_current_shop_id(request: Request) -> Optional[str]:
    """
    从请求头提取当前选中店铺 ID（stores_store.id，格式 store_xxx）。

    与 get_tenant_from_header 的区别：
    - 前者查 shops 表（user_subscription，UUID），用于订阅/归属校验；
    - 本依赖直接返回 header 里的 store_xxx 字符串，用于业务数据（spus/
      candidates/assets）的 shop_id 过滤，不做表校验（stores_store 目前
      无 owner 概念，归属由后续 tenant_id 补全）。

    用法：
        @router.get("/products")
        async def list_products(shop_id: Optional[str] = Depends(get_current_shop_id)):
            if shop_id:
                q = q.where(Record.shop_id == shop_id)
            else:
                return {"items": [], "total": 0}  # 未选店铺返回空
    """
    return request.headers.get(TENANT_HEADER)


# ====== 权限检查 ======

def require_shop_owner():
    """
    验证当前用户是店铺的所有者

    用法：
        @router.delete("/shops/{shop_id}")
        async def delete_shop(
            shop: Shop = Depends(require_shop_owner()),
        ):
            ...
    """
    async def checker(
        request: Request,
        db: AsyncSession = Depends(get_db),
        shop: Shop = Depends(get_tenant_from_header),
    ) -> Shop:
        # 归属校验逻辑复用统一鉴权依赖（admin 越权放行、演示模式返回 None）
        current_user = await require_auth_if_enabled(request, db)

        if current_user is None:
            # 演示模式：不强制归属校验，避免影响本地演示
            return shop

        if current_user.role.value != "admin" and shop.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权操作此店铺",
            )

        return shop
    return checker


# ====== FastAPI 中间件 ======

class TenantMiddleware(BaseHTTPMiddleware):
    """
    多租户中间件

    自动从请求头/查询参数提取租户信息并设置到当前请求的上下文。
    如果不需要强制要求租户，可以使用此中间件自动处理。

    注册方式（main.py）：
        app.add_middleware(TenantMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        # 尝试提取租户信息（不强制）
        shop_id = (
            request.headers.get(TENANT_HEADER)
            or request.query_params.get(TENANT_QUERY_PARAM)
        )

        if shop_id:
            get_tenant_context().set_shop_id(shop_id)

        # 同时挂到 request.state：外层中间件（请求日志）与异常处理器可直接读取
        request.state.shop_id = shop_id

        # 执行请求（ContextVar 在请求 Task 结束时随副本一起失效）
        response = await call_next(request)
        return response

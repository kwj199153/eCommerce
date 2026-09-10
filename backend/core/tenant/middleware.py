"""
多租户中间件

实现租户识别、数据隔离等核心逻辑。
支持从 Header 或 Token 中提取 tenant_id（shop_id）。
"""

from typing import Optional
from fastapi import Request, HTTPException, status, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from modules.user_subscription.models import Shop


# ====== 常量 ======

# 请求头中的租户标识
TENANT_HEADER = "X-Shop-ID"

# 查询参数中的租户标识
TENANT_QUERY_PARAM = "shop_id"


# ====== 租户上下文 ======

class TenantContext:
    """
    租户上下文（请求级别单例）

    在一次请求中存储当前租户信息，供后续业务逻辑使用。
    """

    def __init__(self):
        self._shop: Optional[Shop] = None
        self._shop_id: Optional[str] = None

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

    def set_shop(self, shop: Shop):
        """设置当前店铺"""
        self._shop = shop
        self._shop_id = shop.id

    def set_shop_id(self, shop_id: str):
        """仅设置店铺 ID（不加载完整对象）"""
        self._shop_id = shop_id

    def clear(self):
        """清除租户信息（请求结束后调用）"""
        self._shop = None
        self._shop_id = None


# 全局租户上下文实例（每个请求会重置）
tenant_context = TenantContext()


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
        current_user = None,  # TODO: 从 get_current_user 注入
        shop: Shop = Depends(get_tenant_from_header),
    ) -> Shop:
        if current_user and shop.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权操作此店铺",
            )
        return shop
    return checker


# ====== FastAPI 中间件 ======

class TenantMiddleware:
    """
    多租户中间件（可选）

    自动从请求头/查询参数提取租户信息并设置到上下文。
    如果不需要强制要求租户，可以使用此中间件自动处理。
    """

    async def __call__(self, request: Request, call_next):
        # 尝试提取租户信息（不强制）
        shop_id = (
            request.headers.get(TENANT_HEADER)
            or request.query_params.get(TENANT_QUERY_PARAM)
        )

        if shop_id:
            tenant_context.set_shop_id(shop_id)

        # 执行请求
        response = await call_next(request)

        # 清理上下文
        tenant_context.clear()

        return response

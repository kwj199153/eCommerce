"""
店铺管理 API 路由

提供店铺的 CRUD 操作、平台连接状态查询等接口。
"""

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.auth.dependencies import get_current_user
from core.tenant.middleware import tenant_context
from modules.user_subscription.models import (
    User,
    Shop,
    ShopPlatform,
)


router = APIRouter(prefix="/shops", tags=["店铺管理"])


# ====== Schema ======

class ShopCreateRequest:
    """创建店铺请求"""
    def __init__(self, name: str, platform: str):
        self.name = name
        self.platform = platform


class ShopUpdateRequest:
    """更新店铺请求"""
    def __init__(self, name: str = None, is_active: bool = None):
        self.name = name
        self.is_active = is_active


class ShopResponse:
    """店铺响应"""
    def __init__(self, shop: Shop):
        self.id = shop.id
        self.name = shop.name
        self.platform = shop.platform.value if shop.platform else None
        self.is_active = shop.is_active
        self.is_connected = shop.is_connected
        self.marketplace_id = shop.marketplace_id
        self.last_sync_at = shop.last_sync_at.isoformat() if shop.last_sync_at else None
        self.sync_status = shop.sync_status
        self.created_at = shop.created_at.isoformat() if shop.created_at else None


# ====== 辅助函数 ======

def shop_to_dict(shop: Shop) -> dict:
    """将 Shop 对象转换为字典"""
    return {
        "id": shop.id,
        "name": shop.name,
        "platform": shop.platform.value if shop.platform else None,
        "is_active": shop.is_active,
        "is_connected": shop.is_connected,
        "marketplace_id": shop.marketplace_id,
        "last_sync_at": shop.last_sync_at.isoformat() if shop.last_sync_at else None,
        "sync_status": shop.sync_status,
        "created_at": shop.created_at.isoformat() if shop.created_at else None,
    }


async def check_shop_ownership(user: User, shop_id: str, db: AsyncSession) -> Shop:
    """
    检查用户是否拥有该店铺，并返回店铺对象

    Raises:
        HTTPException 404: 店铺不存在
        HTTPException 403: 无权操作此店铺
    """
    result = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="店铺不存在",
        )

    if shop.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此店铺",
        )

    return shop


# ====== API 端点 ======

@router.get("", response_model=dict)
async def list_shops(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的所有店铺列表

    返回店铺基本信息（不含敏感凭证）
    """
    result = await db.execute(
        select(Shop)
        .where(Shop.owner_id == current_user.id)
        .order_by(Shop.created_at.desc())
    )
    shops = result.scalars().all()

    return {
        "shops": [shop_to_dict(s) for s in shops],
        "total": len(shops),
    }


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_shop(
    name: str,
    platform: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建新店铺

    - **name**: 店铺名称
    - **platform**: 平台类型 (amazon_us / amazon_uk / tiktok / shopify)
    """
    # 1. 验证平台类型
    try:
        platform_enum = ShopPlatform(platform.lower())
    except ValueError:
        valid_platforms = [p.value for p in ShopPlatform]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的平台类型。可选值: {', '.join(valid_platforms)}",
        )

    # 2. 检查店铺数量限制（基于订阅套餐）
    # TODO: 从用户的 subscription 获取 max_shops 限制
    # current_shops_count = ...

    # 3. 创建店铺
    new_shop = Shop(
        id=str(uuid.uuid4()),
        owner_id=current_user.id,
        name=name.strip(),
        platform=platform_enum,
        is_active=True,
        is_connected=False,
        sync_status="idle",
    )

    db.add(new_shop)
    await db.commit()
    await db.refresh(new_shop)

    return {
        "message": "店铺创建成功",
        "shop": shop_to_dict(new_shop),
    }


@router.get("/{shop_id}", response_model=dict)
async def get_shop_detail(
    shop_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取店铺详情

    包含连接状态、同步状态等信息。
    """
    shop = await check_shop_ownership(current_user, shop_id, db)

    return {"shop": shop_to_dict(shop)}


@router.put("/{shop_id}", response_model=dict)
async def update_shop(
    shop_id: str,
    name: str = None,
    is_active: bool = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    更新店铺信息

    可更新：名称、启用/禁用状态
    """
    shop = await check_shop_ownership(current_user, shop_id, db)

    # 更新字段
    if name is not None:
        shop.name = name.strip()
    if is_active is not None:
        shop.is_active = is_active

    shop.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(shop)

    return {
        "message": "店铺信息已更新",
        "shop": shop_to_dict(shop),
    }


@router.delete("/{shop_id}", response_model=dict)
async def delete_shop(
    shop_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除店铺（软删除或硬删除）

    ⚠️ 此操作不可逆！会删除店铺关联的所有数据。
    """
    shop = await check_shop_ownership(current_user, shop_id, db)

    # TODO: 考虑软删除（设置 deleted_at）而非硬删除
    await db.delete(shop)
    await db.commit()

    return {"message": "店铺已删除"}


@router.post("/{shop_id}/connect", response_model=dict)
async def connect_shop_platform(
    shop_id: str,
    credentials: dict = None,  # 平台凭证（加密存储）
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    连接平台 API（如 Amazon SP-API）

    - **credentials**: 平台认证凭据（具体格式取决于平台）
    """
    import json

    shop = await check_shop_ownership(current_user, shop_id, db)

    # TODO: 实现各平台的 OAuth2 授权流程
    # 这里仅模拟连接成功

    if credentials:
        # 生产环境应加密存储
        shop.api_credentials = json.dumps(credentials)

    shop.is_connected = True
    shop.sync_status = "idle"
    shop.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(shop)

    return {
        "message": f"{shop.platform.value} 平台连接成功",
        "shop": shop_to_dict(shop),
    }


@router.post("/{shop_id}/disconnect", response_model=dict)
async def disconnect_shop_platform(
    shop_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    断开平台 API 连接
    """
    shop = await check_shop_ownership(current_user, shop_id, db)

    shop.is_connected = False
    shop.api_credentials = None
    shop.sync_status = "disconnected"
    shop.updated_at = datetime.utcnow()
    await db.commit()

    return {
        "message": "平台连接已断开",
        "shop": shop_to_dict(shop),
    }

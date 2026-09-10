"""
认证 API 路由

提供用户注册、登录、Token 刷新等接口。
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db
from core.auth.jwt_handler import (
    create_token_pair,
    verify_token,
    decode_expired_token,
    TokenPair,
)
from modules.user_subscription.models import User, UserRole


router = APIRouter(prefix="/auth", tags=["认证"])


# ====== 请求/响应 Schema ======

class UserRegisterRequest:
    """注册请求"""
    def __init__(self, email: str, password: str, name: str = None):
        self.email = email
        self.password = password
        self.name = name


class UserLoginResponse:
    """登录响应"""
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str,
        user: dict,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.user = user


class RefreshTokenRequest:
    """刷新 Token 请求"""
    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token


class UserInfoResponse:
    """用户信息响应"""
    def __init__(self, user: dict):
        self.user = user


# ====== 辅助函数 ======

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """根据邮箱查询用户"""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """根据 ID 查询用户"""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def hash_password(password: str) -> str:
    """密码哈希（使用 bcrypt）"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(plain_password, hashed_password)


def user_to_dict(user: User) -> dict:
    """将 User 对象转换为字典（不包含敏感信息）"""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value if user.role else "user",
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


# ====== API 端点 ======

@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(
    email: str,
    password: str,
    name: str = None,
    db: AsyncSession = Depends(get_db),
):
    """
    用户注册

    - **email**: 邮箱地址（唯一）
    - **password**: 密码（至少 6 位）
    - **name**: 用户名（可选）
    """
    # 1. 检查邮箱是否已存在
    existing_user = await get_user_by_email(db, email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册",
        )

    # 2. 验证密码强度
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度不能少于 6 位",
        )

    # 3. 创建用户
    import uuid
    new_user = User(
        id=str(uuid.uuid4()),
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        name=name or email.split("@")[0],
        role=UserRole.USER,
        is_active=True,
        is_verified=False,  # 需要后续邮件验证
    )

    db.add(new_user)

    # 4. 创建默认订阅（免费版）
    from modules.user_subscription.models import Subscription
    default_subscription = Subscription(
        id=str(uuid.uuid4()),
        user_id=new_user.id,
        plan_id=1,  # free plan id
        status="active",
        current_period_start=datetime.utcnow(),
    )
    db.add(default_subscription)

    await db.commit()
    await db.refresh(new_user)

    # 5. 生成 Token
    tokens = create_token_pair(
        user_id=new_user.id,
        email=new_user.email,
        role=new_user.role.value,
    )

    return {
        "message": "注册成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
        "user": user_to_dict(new_user),
    }


@router.post("/login", response_model=dict)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    用户登录（OAuth2 Password 模式）

    - **username**: 邮箱地址
    - **password**: 密码
    """
    # 1. 查找用户
    user = await get_user_by_email(db, form_data.username.lower())
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 验证密码
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. 检查账号状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )

    # 4. 更新最后登录时间
    user.last_login_at = datetime.utcnow()
    await db.commit()

    # 5. 生成 Token
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    return {
        "message": "登录成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@router.post("/refresh", response_model=dict)
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    刷新 Access Token

    - **refresh_token**: Refresh Token
    """
    # 1. 解码 refresh token（允许过期但格式正确）
    payload = decode_expired_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Refresh Token",
        )

    # 2. 提取用户 ID 并查找用户
    user_id = payload.get("sub")
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    # 3. 生成新的 Token 对
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    return {
        "message": "Token 刷新成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: User = Depends(get_db),  # TODO: 替换为真实的依赖注入
):
    """
    获取当前登录用户信息

    需要 Bearer Token 认证
    """
    # TODO: 实现真实的当前用户依赖注入
    return {"detail": "TODO: 实现 /auth/me 接口"}


@router.post("/logout")
async def logout():
    """
    用户登出（客户端清除 Token 即可）

    后端可扩展：将 Token 加入黑名单（Redis）
    """
    return {"message": "登出成功"}

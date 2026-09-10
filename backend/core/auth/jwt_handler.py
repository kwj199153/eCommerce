"""
JWT 认证工具

提供 Token 签发、验证、刷新等功能。
使用 python-jose 库实现。
"""

from datetime import datetime, timedelta
from typing import Optional, Any
from jose import JWTError, jwt
from core.config import config


# ====== Token 类型 ======

class TokenData:
    """Token 解码后的数据"""
    def __init__(
        self,
        user_id: str = None,
        email: str = None,
        role: str = "user",
        exp: datetime = None,
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.exp = exp


class TokenPair:
    """Token 对（Access + Refresh）"""
    def __init__(self, access_token: str, refresh_token: str, token_type: str = "bearer"):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type


# ====== Token 操作 ======

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 Access Token

    Args:
        data: 要编码的数据（通常包含 sub, email, role）
        expires_delta: 过期时间，默认使用配置值
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.jwt_access_token_expire_minutes)

    to_encode.update({
        "exp": expire,
        "type": "access",  # Token 类型标识
    })

    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )
    return encoded_jwt


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 Refresh Token（用于刷新 Access Token）

    Args:
        user_id: 用户 ID
        expires_delta: 过期时间，默认 7 天
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=config.jwt_refresh_token_expire_days)

    to_encode = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh",  # 标识为 refresh token
    }

    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )
    return encoded_jwt


def create_token_pair(user_id: str, email: str, role: str = "user") -> TokenPair:
    """
    创建完整的 Token 对（Access + Refresh）

    Args:
        user_id: 用户 ID
        email: 用户邮箱
        role: 用户角色

    Returns:
        TokenPair 包含 access_token 和 refresh_token
    """
    # Access Token payload
    access_payload = {
        "sub": user_id,
        "email": email,
        "role": role,
    }
    access_token = create_access_token(access_payload)
    refresh_token = create_refresh_token(user_id)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
    )


def verify_token(token: str, expected_type: str = "access") -> Optional[TokenData]:
    """
    验证并解码 Token

    Args:
        token: JWT 字符串
        expected_type: 期望的 token 类型 (access/refresh)

    Returns:
        TokenData 解码成功返回数据，失败返回 None
    """
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=[config.jwt_algorithm],
        )

        # 检查 token 类型
        token_type = payload.get("type")
        if token_type != expected_type:
            return None

        # 提取数据
        user_id = payload.get("sub")
        email = payload.get("email")
        role = payload.get("role", "user")
        exp = payload.get("exp")

        if exp:
            # 转换为 datetime
            exp_datetime = datetime.fromtimestamp(exp)
        else:
            exp_datetime = None

        return TokenData(
            user_id=user_id,
            email=email,
            role=role,
            exp=exp_datetime,
        )
    except JWTError:
        return None


def decode_expired_token(token: str) -> Optional[dict]:
    """
    解码可能已过期的 Token（用于刷新流程）

    即使 Token 过期也能提取 payload，用于判断是否允许刷新。

    Returns:
        dict 解码后的 payload，或 None（如果格式错误）
    """
    try:
        # 允许过期但格式正确的 token
        payload = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=[config.jwt_algorithm],
            options={"verify_exp": False},  # 不验证过期时间
        )
        return payload
    except JWTError:
        return None

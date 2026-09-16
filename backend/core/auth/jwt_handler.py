"""
JWT 认证工具

提供 Token 签发、验证、刷新等功能。
使用 python-jose 库实现。
"""

import uuid
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
        jti: str = None,
        token_version: Optional[int] = None,
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.exp = exp
        # ★ jti = 这一枚 token 的唯一编号（P1-b）。「登出当前这一台设备」
        #   靠把它写进 Redis 黑名单实现 —— 没有 jti 就无法单独撤销某一枚
        #   （只能靠 token_version 整批失效，那会把所有设备一起踢下线）。
        self.jti = jti
        # ★ token_version = 签发时的用户凭据版本（P1-b）。校验时与库里
        #   `users.token_version` 比对 ⇒ 改密/重置密码后全部旧 token 失效。
        #   这是**整批撤销**，也是「服务端不知道有哪些 token 在飞」这个
        #   无状态前提下的唯一正确实现（详见 core/auth/revocation.py）。
        self.token_version = token_version


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
    token_version: Optional[int] = None,
) -> str:
    """
    创建 Access Token

    Args:
        data: 要编码的数据（通常包含 sub, email, role）
        expires_delta: 过期时间，默认使用配置值
        token_version: 用户当前凭据版本，写进 `tv` 声明
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=config.jwt_access_token_expire_minutes)

    to_encode.update({
        "exp": expire,
        "type": "access",  # Token 类型标识
        # ★ jti：本枚 token 的唯一编号，供「只登出这一台设备」用（P1-b）
        "jti": uuid.uuid4().hex,
    })
    if token_version is not None:
        to_encode["tv"] = int(token_version)

    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )
    return encoded_jwt


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
    token_version: Optional[int] = None,
) -> str:
    """
    创建 Refresh Token（用于刷新 Access Token）

    Args:
        user_id: 用户 ID
        expires_delta: 过期时间，默认 7 天
        token_version: 用户当前凭据版本

    ★ 为什么 refresh token 也必须带 `tv`：
      否则「改密让所有 token 失效」会留下一个绕过的口子 ——
      access token 被拒了，但攻击者手上那枚 refresh token 照样能换出
      全新的 access token ⇒ 改密形同没改。撤销必须是**成套**的。
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=config.jwt_refresh_token_expire_days)

    to_encode = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh",  # 标识为 refresh token
        "jti": uuid.uuid4().hex,
    }
    if token_version is not None:
        to_encode["tv"] = int(token_version)

    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key,
        algorithm=config.jwt_algorithm,
    )
    return encoded_jwt


def create_token_pair(
    user_id: str, email: str, role: str = "user", token_version: Optional[int] = None
) -> TokenPair:
    """
    创建完整的 Token 对（Access + Refresh）

    Args:
        user_id: 用户 ID
        email: 用户邮箱
        role: 用户角色
        token_version: 用户当前凭据版本（改密/重置密码后旧值即失效）

    Returns:
        TokenPair 包含 access_token 和 refresh_token
    """
    # Access Token payload
    access_payload = {
        "sub": user_id,
        "email": email,
        "role": role,
    }
    access_token = create_access_token(access_payload, token_version=token_version)
    refresh_token = create_refresh_token(user_id, token_version=token_version)

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
        jti = payload.get("jti")
        tv = payload.get("tv")
        if tv is not None:
            try:
                tv = int(tv)
            except (TypeError, ValueError):
                tv = None

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
            jti=jti,
            token_version=tv,
        )
    except JWTError:
        return None


def verify_refresh_token(token: str) -> Optional[TokenData]:
    """
    校验 Refresh Token：签名 + 类型 + **过期时间**，三项全过才返回 TokenData。

    ★ 与 `decode_expired_token` 的分工（P0 修复 2026-09-16，别搞反）
        - 本函数 = **授权判定**的唯一入口。
        - `decode_expired_token` = 只负责"给用户一句可读的失败原因"
          （"已过期" vs "无效"），**永远不能**拿它的返回值放行。

    ★ 事故形态（实测）
        `/auth/refresh` 曾直接 `payload = decode_expired_token(...)`，再
        `if not payload or payload.get("type") != "refresh": 401` ——
        看起来是一道完整的门禁，实际因为 `decode_expired_token` 内部写了
        `options={"verify_exp": False}`，**过期这一项从未被检查**。
        实测：造一个"过期 30 天"的 refresh token 打 `/auth/refresh` → **200**，
        换回全新的 access + refresh 对；而 `jwt_refresh_token_expire_days = 7`
        是**装饰性配置**，且每次刷新都续期 ⇒ 等于永久会话。
        探针：`script-r84e_refresh.py`（修复前 200，修复后 401）。
    """
    return verify_token(token, expected_type="refresh")


def decode_expired_token(token: str) -> Optional[dict]:
    """
    解码可能已过期的 Token（**仅用于给出可读的失败原因**）

    即使 Token 过期也能提取 payload —— 它内部关掉了 `exp` 校验，所以返回值
    只说明「签名有效、格式正确」，**不说明「还没过期」**。

    ★ 这是**诊断**工具，不是**授权**工具。授权请用：
        - 通用：`verify_token(token, expected_type=...)`
        - 刷新：`verify_refresh_token(token)`
      错误用法（P0 事故）：`payload = decode_expired_token(t); if payload: 放行`
      —— 等于把 exp 校验整段删掉，而代码表面看不出任何异常。

    Returns:
        dict 解码后的 payload，或 None（如果签名/格式错误）
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

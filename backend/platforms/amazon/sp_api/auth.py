"""
Amazon SP-API 认证模块

实现两种认证机制：
1. LWA (Login with Amazon) OAuth 2.0 - 获取访问令牌
2. AWS Signature V4 - API 请求签名认证

参考文档：
- https://developer-docs.amazon.com/sp-api/docs/authorization-api-use-case-guide
- https://developer-docs.amazon.com/sp-api/reference/sellingpartnerapiauthorizationv1.html

使用流程：
1. 开发者通过 LWA OAuth 获取 Refresh Token（一次性）
2. 使用 Refresh Token 获取 Access Token（有效期 60 分钟）
3. 使用 Access Token + AWS Signature V4 签名调用 SP-API
"""

import hashlib
import hmac
import time
import json
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

import httpx


def _get_settings():
    """延迟导入 settings，避免循环依赖"""
    try:
        from core.config import config as settings
        return settings
    except ImportError:
        # 返回空配置作为兜底
        class _EmptySettings:
            spapi_lwa_client_id = ""
            spapi_lwa_client_secret = ""
            spapi_refresh_token = ""
            spapi_aws_access_key = ""
            spapi_aws_secret_key = ""
            spapi_aws_region = "us-east-1"
            spapi_use_sandbox = True
        return _EmptySettings()


# ====== 配置数据类 ======

@dataclass
class LWACredentials:
    """LWA OAuth 凭证"""
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    # LWA 端点
    auth_url: str = "https://api.amazon.com/auth/o2/token"
    # 作用域
    scope: str = "sellingpartnerapi::migration"


@dataclass
class AWSCredentials:
    """AWS Signature V4 凭证"""
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"
    service: str = "execute-api"


@dataclass
class SPAPIConfig:
    """SP-API 完整配置"""
    lwa: LWACredentials = field(default_factory=LWACredentials)
    aws: AWSCredentials = field(default_factory=AWSCredentials)
    # SP-API 基础 URL
    sandbox_base_url: str = "https://sandbox.sellingpartnerapi-na.amazon.com"
    production_base_url: str = "https://sellingpartnerapi-na.amazon.com"
    # 环境
    use_sandbox: bool = False

    @property
    def base_url(self) -> str:
        return self.sandbox_base_url if self.use_sandbox else self.production_base_url


# ====== Token 管理 ======

@dataclass
class AccessToken:
    """访问令牌"""
    token: str = ""
    token_type: str = "Bearer"
    expires_in: int = 0  # 秒
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """检查是否过期（提前 5 分钟刷新）"""
        if not self.token:
            return True
        elapsed = time.time() - self.created_at
        return elapsed >= (self.expires_in - 300)

    @property
    def authorization_header(self) -> str:
        return f"{self.token_type} {self.token}"


class SPAPIClientAuth:
    """
    SP-API 认证管理器

    负责：
    1. LWA Access Token 获取与自动刷新
    2. AWS Signature V4 请求签名
    3. 凭证配置管理
    """

    def __init__(self, config: Optional[SPAPIConfig] = None):
        self.config = config or self._load_config_from_settings()
        self._access_token: Optional[AccessToken] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    # ====== 配置加载 ======

    @staticmethod
    def _load_config_from_settings() -> SPAPIConfig:
        """从应用设置加载 SP-API 配置"""
        config = SPAPIConfig()
        settings = _get_settings()

        # LWA 凭证
        config.lwa.client_id = getattr(settings, 'spapi_lwa_client_id', '')
        config.lwa.client_secret = getattr(settings, 'spapi_lwa_client_secret', '')
        config.lwa.refresh_token = getattr(settings, 'spapi_refresh_token', '')

        # AWS 凭证
        config.aws.access_key = getattr(settings, 'spapi_aws_access_key', '')
        config.aws.secret_key = getattr(settings, 'spapi_aws_secret_key', '')
        config.aws.region = getattr(settings, 'spapi_aws_region', 'us-east-1')

        # 环境
        config.use_sandbox = getattr(settings, 'spapi_use_sandbox', True)

        return config

    # ====== LWA Token 管理 ======

    async def get_access_token(self) -> str:
        """
        获取有效的 Access Token

        如果当前 token 未过期则直接返回，否则通过 Refresh Token 刷新。
        """
        if self._access_token and not self._access_token.is_expired:
            return self._access_token.authorization_header

        # 刷新 token
        await self._refresh_access_token()

        if not self._access_token or not self._access_token.token:
            raise SPAPIAuthError("无法获取 Access Token，请检查 LWA 凭证配置")

        return self._access_token.authorization_header

    async def _refresh_access_token(self) -> None:
        """通过 Refresh Token 刷新 Access Token"""

        if not self.config.lwa.refresh_token:
            raise SPAPIAuthError(
                "Refresh Token 未配置，请先完成 LWA 授权流程",
                code="REFRESH_TOKEN_MISSING"
            )

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.config.lwa.refresh_token,
            "client_id": self.config.lwa.client_id,
            "client_secret": self.config.lwa.client_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.config.lwa.auth_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                data = response.json()

            self._access_token = AccessToken(
                token=data.get("access_token", ""),
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in", 3600),
                created_at=time.time(),
            )

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.json()
            except Exception:
                error_body = e.response.text

            raise SPAPIAuthError(
                f"LWA Token 刷新失败: {e.response.status_code}",
                code=f"HTTP_{e.response.status_code}",
                details=error_body,
            ) from e
        except Exception as e:
            raise SPAPIAuthError(f"LWA Token 刷新异常: {str(e)}") from e

    def invalidate_token(self) -> None:
        """使当前 Token 失效（用于测试或手动切换）"""
        self._access_token = None

    # ====== AWS Signature V4 ======

    async def sign_request(
        self,
        method: str,
        path: str,
        query_params: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """
        为请求添加 AWS Signature V4 签名头

        Args:
            method: HTTP 方法 (GET/POST/PUT/DELETE)
            path: API 路径（如 /products/pricing/2022-05-01/items）
            query_params: 查询参数字典
            body: 请求体字符串
            headers: 已有的请求头

        Returns:
            包含签名字典的完整请求头
        """

        access_token = await self.get_access_token()

        # 构建完整 URL 和参数
        base_headers = headers or {}

        # 当前时间戳
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        # 规范化 URI
        canonical_uri = path
        if not canonical_uri.startswith("/"):
            canonical_uri = "/" + canonical_uri

        # 规范化查询参数
        if query_params:
            sorted_params = sorted(query_params.items())
            canonical_querystring = "&".join(
                f"{self._uri_encode(k)}={self._uri_encode(v)}"
                for k, v in sorted_params
            )
        else:
            canonical_querystring = ""

        # 计算内容哈希
        payload_hash = hashlib.sha256((body or "").encode("utf-8")).hexdigest()

        # 规范化请求头
        required_headers = {
            "host": self._extract_host(),
            "x-amz-date": amz_date,
            "x-amz-access-token": access_token.replace("Bearer ", ""),
        }

        merged_headers = {**base_headers, **required_headers}
        sorted_header_names = sorted(merged_headers.keys())
        canonical_headers = "\n".join(
            f"{k.lower()}:{merged_headers[k].strip()}" for k in sorted_header_names
        ) + "\n"
        signed_headers = ";".join(k.lower() for k in sorted_header_names)

        # 规范化请求
        canonical_request = "\n".join([
            method.upper(),
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash,
        ])

        # 创建待签字符串
        credential_scope = f"{date_stamp}/{self.config.aws.region}/{self.config.aws.service}/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        # 计算签名
        signing_key = self._get_signature_key(
            self.config.aws.secret_key,
            date_stamp,
            self.config.aws.region,
            self.config.aws.service,
        )
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # 构建最终请求头
        authorization_header = (
            f"AWS4-HMAC-SHA256 "
            f"Credential={self.config.aws.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        final_headers = {
            **merged_headers,
            "Authorization": authorization_header,
            "Content-Type": "application/json",
            "User-Agent": "CrossBorder-AI-SaaS/1.0",
        }

        return final_headers

    # ====== AWS 签名辅助方法 ======

    @staticmethod
    def _get_signature_key(key: str, date_stamp: str, region: str, service: str) -> bytes:
        """生成 AWS Signature V4 派生签名密钥"""
        k_date = hmac.new(f"AWS4{key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
        k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
        k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
        k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
        return k_signing

    @staticmethod
    def _uri_encode(value: str) -> str:
        """URI 编码（符合 RFC 3986）"""
        import urllib.parse
        return urllib.parse.quote(str(value), safe="-_.~")

    def _extract_host(self) -> str:
        """从基础 URL 提取主机名"""
        from urllib.parse import urlparse
        parsed = urlparse(self.config.base_url)
        return parsed.netloc

    # ====== HTTP 客户端 ======

    @property
    def http_client(self) -> httpx.AsyncClient:
        """获取或创建共享的 HTTP 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=60,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._http_client

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    # ====== 便捷方法 ======

    async def make_authenticated_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送经过认证的 SP-API 请求

        这是最高层的封装方法，处理：
        1. Token 自动获取/刷新
        2. AWS 签名
        3. 请求发送
        4. 错误处理
        5. 限流重试
        """
        body = json.dumps(json_data) if json_data else None
        query_params = {k: str(v) for k, v in (params or {}).items()}

        # 获取签名后的请求头
        headers = await self.sign_request(
            method=method,
            path=endpoint,
            query_params=query_params,
            body=body,
        )

        url = f"{self.config.base_url}{endpoint}"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.http_client.request(
                    method=method,
                    url=url,
                    params=query_params,
                    content=body,
                    headers=headers,
                )

                # 处理限流
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "5"))
                    import asyncio
                    await asyncio.sleep(retry_after)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                if attempt == max_retries - 1:
                    raise SPAPIAuthError(
                        f"SP-API 请求失败 [{e.response.status_code}]: {endpoint}",
                        code=f"HTTP_{e.response.status_code}",
                        details=e.response.text[:500],
                    ) from e
                import asyncio
                await asyncio.sleep(1 * (attempt + 1))

            except Exception as e:
                if attempt == max_retries - 1:
                    raise SPAPIAuthError(f"SP-API 请求异常: {str(e)}") from e
                import asyncio
                await asyncio.sleep(1 * (attempt + 1))

        raise SPAPIAuthError("未知错误：超出最大重试次数")


# ====== 异常类 ======

class SPAPIAuthError(Exception):
    """SP-API 认证相关异常"""

    def __init__(
        self,
        message: str,
        code: str = "AUTH_ERROR",
        details: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.code,
            "message": str(self),
            "details": self.details,
        }


# ====== 单例模式 ======

_auth_instance: Optional[SPAPIClientAuth] = None


def get_spapi_auth() -> SPAPIClientAuth:
    """获取全局 SP-API 认证实例（单例）"""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = SPAPIClientAuth()
    return _auth_instance


async def close_spapi_auth() -> None:
    """关闭全局 SP-API 认证实例"""
    global _auth_instance
    if _auth_instance:
        await _auth_instance.close()
        _auth_instance = None

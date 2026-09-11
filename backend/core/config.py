"""
全局配置模块

统一管理所有环境变量和系统配置，供全项目引用。
使用 pydantic-settings 进行类型安全的配置管理。
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用全局配置"""

    # ====== 应用基础 ======
    app_name: str = "跨境电商AI SaaS"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, description="调试模式")
    environment: str = Field(default="development", description="环境: development/staging/production")

    model_config = {
        "extra": "ignore",  # 允许额外字段，避免验证错误
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    # ====== 服务器配置 ======
    api_host: str = Field(default="0.0.0.0", description="API 监听地址")
    api_port: int = Field(default=8000, description="API 端口")
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"], description="CORS 允许的源")

    # ====== 数据库 (PostgreSQL) ======
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ecommerce",
        description="PostgreSQL 异步连接 URL"
    )
    database_pool_size: int = Field(default=10, description="连接池大小")
    database_max_overflow: int = Field(default=20, description="连接池最大溢出数")

    # ====== Redis & Celery ======
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis 连接 URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/1", description="Celery Broker URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/2", description="Celery Result Backend")

    # ====== JWT 认证 ======
    jwt_secret_key: str = Field(default="your-super-secret-key-change-in-production", description="JWT 密钥")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法")
    jwt_access_token_expire_minutes: int = Field(default=60, description="Access Token 过期时间(分钟)")
    jwt_refresh_token_expire_days: int = Field(default=7, description="Refresh Token 过期时间(天)")

    # 业务接口强制鉴权开关
    # False（默认）= 演示模式，业务接口不校验 Token，方便本地演示与联调
    # True          = 生产模式，全部业务接口要求 Bearer Token，未登录返回 401
    auth_required: bool = Field(
        default=False,
        description="是否强制业务接口鉴权（演示模式默认关闭，生产环境必须开启）",
    )

    # ====== LLM (DashScope/Qwen) ======
    dashscope_api_key: str = Field(default="", description="阿里 DashScope API Key")
    llm_default_model: str = Field(default="qwen-max", description="默认 LLM 模型")
    llm_fallback_model: str = Field(default="qwen-plus", description="备用 LLM 模型")
    llm_max_tokens: int = Field(default=4096, description="最大 Token 数")
    llm_temperature: float = Field(default=0.7, description="生成温度")
    llm_timeout_seconds: int = Field(default=120, description="LLM 调用超时(秒)")

    # ====== RAG 配置 ======
    rag_chunk_size: int = Field(default=500, description="文本分块大小")
    rag_chunk_overlap: int = Field(default=50, description="分块重叠大小")
    rag_top_k: int = Field(default=5, description="检索返回数量")

    # ====== 限流 & 计费 ======
    rate_limit_requests_per_minute: int = Field(default=60, description="每分钟请求限制")
    rate_limit_requests_per_day: int = Field(default=1000, description="每日请求限制")
    rate_limit_enabled: bool = Field(
        default=True,
        description="是否启用请求速率限制中间件（测试/压测时可关闭）",
    )
    request_log_enabled: bool = Field(
        default=True,
        description="是否启用请求日志中间件",
    )
    free_tier_monthly_quota: int = Field(default=100, description="免费套餐月度额度")

    # ====== 文件存储 ======
    upload_dir: str = Field(default="./uploads", description="文件上传目录")
    max_upload_size_mb: int = Field(default=10, description="最大上传文件大小(MB)")
    allowed_file_types: list[str] = Field(
        default=["pdf", "csv", "xlsx", "txt", "json", "jpg", "png"],
        description="允许上传的文件类型"
    )

    # ====== Amazon SP-API ======
    spapi_lwa_client_id: str = Field(default="", description="LWA Client ID")
    spapi_lwa_client_secret: str = Field(default="", description="LWA Client Secret")
    spapi_refresh_token: str = Field(default="", description="LWA Refresh Token")
    spapi_aws_access_key: str = Field(default="", description="AWS Access Key ID")
    spapi_aws_secret_key: str = Field(default="", description="AWS Secret Access Key")
    spapi_aws_region: str = Field(default="us-east-1", description="AWS Region (SP-API)")
    spapi_use_sandbox: bool = Field(default=True, description="使用 Sandbox 环境")


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings()


# 全局配置实例（方便直接导入）
config = get_settings()

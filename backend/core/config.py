"""
全局配置模块

统一管理所有环境变量和系统配置，供全项目引用。
使用 pydantic-settings 进行类型安全的配置管理。
"""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


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

    @model_validator(mode="after")
    def _derive_checkpoint_url(self):
        """checkpoint_database_url 缺省时从 database_url 派生（去 +asyncpg 驱动）。"""
        if not self.checkpoint_database_url or "+asyncpg" in self.checkpoint_database_url:
            self.checkpoint_database_url = self.database_url.replace("+asyncpg", "")
        return self

    # ====== 服务器配置 ======
    api_host: str = Field(default="0.0.0.0", description="API 监听地址")
    api_port: int = Field(default=8000, description="API 端口")
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"], description="CORS 允许的源")

    # ====== 数据库 (PostgreSQL) ======
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ecommerce",
        description="PostgreSQL 异步连接 URL"
    )
    # LangGraph Checkpoint 专用连接串（psycopg3 驱动，与业务 asyncpg 分离）
    # AsyncPostgresSaver 硬依赖 psycopg3，故用 postgresql:// 而非 postgresql+asyncpg://
    checkpoint_database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/ecommerce",
        description="LangGraph checkpoint 持久化连接 URL（psycopg3）"
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

    # ====== 支付网关 ======
    payment_gateway: str = Field(
        default="mock",
        description="支付网关实现：mock（模拟支付，默认）/ stripe / alipay / wechat（待接入）",
    )

    # ====== 文件存储 ======
    upload_dir: str = Field(default="./uploads", description="文件上传目录")
    max_upload_size_mb: int = Field(default=10, description="最大上传文件大小(MB)")
    allowed_file_types: list[str] = Field(
        default=["pdf", "csv", "xlsx", "txt", "json", "jpg", "png"],
        description="允许上传的文件类型"
    )
    # 对外可访问的站点根地址（形如 https://api.example.com）。
    # 用途：声音复刻（CosyVoice）只接受「公网可访问的音频 URL」，不接受本地上传流，
    # 所以样本落盘后必须拼成公网地址。留空 = 未配置 → 语音克隆会显式报错并说明原因，
    # **不会**静默退回 localhost（那样服务端根本取不到文件）。
    public_base_url: str = Field(
        default="",
        description="对外可访问的站点根地址，用于生成第三方可回源的资源 URL（如声音复刻样本）",
    )

    # ====== 样本公网镜像（本地开发用，见 docs/voice-sample-mirror.md）======
    # 问题：CosyVoice 只收【公网可访问】的音频 URL，且是【服务端主动来拉】。
    #       本地开发的 localhost 它够不着 ⇒ 不解决就永远跑不通。
    # 方案：样本落盘后【额外推一份】到云端静态目录，public_base_url 指向云端。
    #       判据：本机没公网入口，但云端有 ⇒ 让云端只当"文件柜"，业务逻辑全在本地。
    # ⚠️ 与 PUBLIC_BASE_URL 的分工：
    #       PUBLIC_BASE_URL          = 拼给 DashScope 的地址前缀（指向【云端】）
    #       VOICE_SAMPLE_MIRROR_*    = 怎么把文件【送上去】（ssh/scp 凭据）
    #    ⚠️ 未配置 ssh_host 时，同步静默跳过（本地仍可用，只是克隆会失败——
    #       失败原因由 sample_public_url 的显式报错给出，不在这里制造第二个错误）。
    voice_sample_mirror_ssh_host: str = Field(
        default="",
        description="样本镜像目标主机（形如 root@1.2.3.4）。留空 = 不做镜像同步",
    )
    voice_sample_mirror_ssh_port: int = Field(
        default=22, description="样本镜像 SSH 端口"
    )
    voice_sample_mirror_remote_dir: str = Field(
        default="/www/wwwroot/voice-samples",
        description="样本镜像的远端目录（需与 nginx 站点根目录一致）",
    )
    voice_sample_mirror_ssh_key: str = Field(
        default="",
        description="样本镜像用的 SSH 私钥路径（留空 = 用默认 ssh-agent / ~/.ssh/id_*）",
    )

    # ====== 附加模块总开关 ======
    # 语音克隆（客服音色）属于**附加模块**：装了也不生效，必须显式打开。
    # 关闭时：前端入口直接隐藏 + 后端路由不注册（404 语义）；数据表保留，不做破坏性迁移。
    voice_clone_enabled: bool = Field(
        default=False,
        description="是否启用语音克隆附加模块（默认关闭）",
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

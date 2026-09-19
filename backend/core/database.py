"""
数据库连接管理模块

基于 SQLAlchemy 2.0 + aiosqlite (MVP) / asyncpg (生产) 的异步数据库连接池管理。
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import config


logger = logging.getLogger(__name__)


# ====== 声明式基类 ======
class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# ====== 引擎创建 ======
def create_engine() -> AsyncEngine:
    """创建异步数据库引擎"""
    return create_async_engine(
        config.database_url,
        echo=config.debug,  # 调试模式打印 SQL
        pool_pre_ping=True,  # 连接前健康检查
    )


# 全局引擎实例
engine = create_engine()

# ====== 会话工厂 ======
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后不过期，允许访问属性
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    异步会话上下文管理器

    使用方式：
        async with get_async_session() as session:
            result = await session.execute(query)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db():
    """
    FastAPI 依赖注入用的会话生成器

    使用方式：
        @app.get("/users")
        async def list_users(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 为了兼容性，保留别名
get_db_session = get_db


# ====== 生命周期管理 ======
# ====== ORM 模型注册（唯一真源） ======
def register_all_models() -> None:
    """导入全部 ORM 模型，确保它们被注册到 `Base.metadata`。

    ★★ 为什么必须是唯一真源：
      本清单有**两个消费者** —— `init_db()`（开发期 create_all 兜底）与
      `alembic/env.py`（autogenerate 比对 `target_metadata`）。
      历史上两处各写一份，`env.py` 那份漏了 monitors / platform_rules /
      knowledge_base / voice_clone / aigc_media 共 5 个模块 ⇒ `target_metadata`
      里少 9 张表 ⇒ autogenerate 生成的迁移**静默漏表**（不报错、不告警，
      只在全新库上表现为「表不存在」）。

    ⇒ 新增业务模块时**只改这里**，两处自动同步。
    """
    from core.identity.models import User  # noqa: F401
    # 账户域（★ P1-b/P1-c 2026-09-16）：Account/AccountMember 取代 shops 的架构位置；
    # EmailToken/LoginAttempt 服务邮箱验证、密码重置与登录审计。
    from core.identity.account_models import Account, AccountMember  # noqa: F401
    from core.identity.auth_models import EmailToken, LoginAttempt, UserApiKey  # noqa: F401
    # ★ 第 140 轮：StoreRecord 随实体归位搬到 core/stores/，本行由 modules 组挪到 core 组。
    from core.stores import StoreRecord  # noqa: F401
    from modules.billing.models import SubscriptionPlan, Subscription, Invoice, PaymentMethod  # noqa: F401
    from modules.products.db_model import (  # noqa: F401
        SpuRecord, SkuRecord, ProductGroupRecord,
    )
    from modules.assets.db_model import (  # noqa: F401
        AssetRecord, AssetGroupRecord,
    )
    from modules.candidates.db_model import (  # noqa: F401
        CandidateRecord, CandidateGroupRecord,
    )
    from modules.amazon_sp.db_model import (  # noqa: F401
        AmazonCredential, AmazonAuthLog, DailySales, AdMetric,
        ListingSnapshot, ReportTask, InventoryHealth, CompetitorSnapshot,
    )
    from modules.conversation.db_model import (  # noqa: F401
        AgentSessionStateRecord, ConversationRecord, ConversationMessageRecord,
    )
    from modules.monitors.db_model import MonitorRecord, MonitorGroupRecord  # noqa: F401
    from modules.platform_rules.db_model import (  # noqa: F401
        PlatformRuleRecord, PlatformRuleDocRecord,
    )
    from modules.knowledge_base.db_model import (  # noqa: F401
        KnowledgeBaseRecord, KnowledgeFaqRecord, KnowledgeDocRecord,
    )
    # 附加模块：语音克隆（独立表 shop_voice，不 ALTER 任何既有表）
    # 无条件导入以完成 metadata 注册；是否真正启用由 config.voice_clone_enabled 决定
    from modules.voice_clone.db_model import ShopVoice  # noqa: F401
    # AIGC 异步任务表（aigc_jobs）—— 长任务的状态权威源
    from modules.aigc_media.db_model import AIGCJobRecord  # noqa: F401
    # 客服工单表（cs_tickets）—— 第 143 轮 A4：工单从「只在内存里造一个就返回」
    from modules.customer_service.db_model import TicketRecord  # noqa: F401


async def init_db():
    """初始化数据库（创建表结构）"""
    register_all_models()

    async with engine.begin() as conn:
        # 2026-09-09: 已迁移到 Alembic（backend/alembic）
        # - 首次部署：`alembic upgrade head`
        # - 改 schema 后：`alembic revision --autogenerate -m "..."` 生成迁移 + 确认 diff + `alembic upgrade head`
        # - create_all 仅作「全新空数据库」的兜底（不会给已有表加列！）
        if config.environment == "development":
            # ★ 全部模型共用本模块的 Base ⇒ 一次 create_all 即建出**全部**表。
            #   历史上这里逐个模型调用了一次（20+ 行），每个都是 no-op ——
            #   因为 `X.metadata` 就是 `Base.metadata`，第一次调用已经建完了全部。
            #   合并成一次调用，避免「逐类调用看起来各建一张表」的误导。
            await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ 数据库表创建完成（注意：已迁移到 Alembic，已有表请走 `alembic upgrade head`）")


async def close_db():
    """关闭数据库连接池"""
    await engine.dispose()

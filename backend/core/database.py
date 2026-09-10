"""
数据库连接管理模块

基于 SQLAlchemy 2.0 + aiosqlite (MVP) / asyncpg (生产) 的异步数据库连接池管理。
"""

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
async def init_db():
    """初始化数据库（创建表结构）"""
    # 导入所有模型，确保它们被注册到 metadata 中
    from modules.user_subscription.models import User, SubscriptionPlan, Subscription, Shop
    from modules.stores.db_model import StoreRecord
    from modules.products.db_model import SpuRecord, SkuRecord, ProductGroupRecord
    from modules.assets.db_model import AssetRecord, AssetGroupRecord
    from modules.candidates.db_model import CandidateRecord, CandidateGroupRecord
    from modules.amazon_sp.db_model import (
        AmazonCredential, AmazonAuthLog, DailySales,
        AdMetric, ListingSnapshot, ReportTask, InventoryHealth,
    )

    async with engine.begin() as conn:
        # 2026-09-09: 已迁移到 Alembic（backend/alembic）
        # - 首次部署：`alembic upgrade head`
        # - 改 schema 后：`alembic revision --autogenerate -m "..."` 生成迁移 + 确认 diff + `alembic upgrade head`
        # - create_all 仅作「全新空数据库」的兜底（不会给已有表加列！）
        if config.environment == "development":
            # 以下 fallback 仅在数据库完全为空时生效
            # 已有数据库请走 alembic 升级
            await conn.run_sync(User.metadata.create_all)
            # 以下表挂在 core.database.Base 上，需单独建表
            await conn.run_sync(StoreRecord.metadata.create_all)
            await conn.run_sync(SpuRecord.metadata.create_all)
            await conn.run_sync(SkuRecord.metadata.create_all)
            await conn.run_sync(AssetRecord.metadata.create_all)
            await conn.run_sync(CandidateRecord.metadata.create_all)
            # Amazon SP-API 表
            await conn.run_sync(AmazonCredential.metadata.create_all)
            await conn.run_sync(AmazonAuthLog.metadata.create_all)
            await conn.run_sync(DailySales.metadata.create_all)
            await conn.run_sync(AdMetric.metadata.create_all)
            await conn.run_sync(ListingSnapshot.metadata.create_all)
            await conn.run_sync(ReportTask.metadata.create_all)
            await conn.run_sync(InventoryHealth.metadata.create_all)
            print("✅ 数据库表创建完成（注意：已迁移到 Alembic，已有表请走 `alembic upgrade head`）")


async def close_db():
    """关闭数据库连接池"""
    await engine.dispose()

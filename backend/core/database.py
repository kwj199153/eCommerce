"""
数据库连接管理模块

基于 SQLAlchemy 2.0 + aiosqlite (MVP) / asyncpg (生产) 的异步数据库连接池管理。
"""

import importlib
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Iterable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import config
# ★ L3-3（第 351 轮）：DB 分段耗时出口（响应头 X-DB-Time-Ms）。
#   与 `identity -> observability`（指标出口）同族 —— 内核自己报告自己的开销。
#   这条 import 期边已登记在 tests/test_core_internal_layering.py 的登记表 1。
from core.observability.request_timing import add_db_ms


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


# ====== 请求级 DB 分段计时（L3-3，第 351 轮）======
#: 已安装的监听器 `(sync_engine, before_fn, after_fn)` —— 供门禁用
#: `sqlalchemy.event.contains(...)` 反查「装上了没有」（问库本身，禁自算复刻）。
INSTALLED_TIMING_LISTENERS: list = []


def install_db_timing(sync_engine) -> None:
    """把「SQL 实际执行耗时」累加进请求级分段计时。

    ★ 参数是**同步引擎**（`engine.sync_engine` / 一个 sync `Engine`）：
      `event.listens_for` 只能挂在同步 Connectable 上。

    ★ 为什么挂 cursor 事件，而不是包 `get_db` / `get_async_session`：
      · 事件只在**真的发 SQL** 时触发（一次请求 0 条 SQL ⇒ 0ms），
        而包 get_db 会把「拿到连接但没查询」也算成耗时；
      · SQLAlchemy 的异步引擎通过 greenlet 调 DBAPI，事件回调与调用方
        **共享同一个 Context** ⇒ 这里的 add_db_ms 能改到中间件那个计时对象。
      （greenlet 共享 context 见 `.workbuddy/probes/r351/l3_3_greenlet_ctx.py`；
        跨任务边界必须用可变容器见 `core/observability/request_timing.py`。）

    ★ 对**同一个**引擎幂等：重复调用直接返回。
      不加这道守卫的后果不是报错而是**静默翻倍** —— SQLAlchemy 会把同一个
      `before_cursor_execute` 注册两次，于是每条 SQL 的耗时被累加两遍，
      响应头里的数字看着"像那么回事"，其实全是错的。
    """
    if any(target is sync_engine for target, _b, _a in INSTALLED_TIMING_LISTENERS):
        return

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._l3_3_sql_started = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_l3_3_sql_started", None)
        if started is not None:
            add_db_ms((time.perf_counter() - started) * 1000.0)

    INSTALLED_TIMING_LISTENERS.append(
        (sync_engine, _before_cursor_execute, _after_cursor_execute)
    )


# ★ 装在模块级唯一引擎上：任何经 async_session_factory / get_db 的 SQL 都被计时。
install_db_timing(engine.sync_engine)

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
# ====== ORM 模型注册（机制住 core，清单住 wiring） ======
def register_all_models(model_modules: Iterable[str]) -> None:
    """按**调用方提供的**模块名清单导入全部 ORM 模型模块，完成 `Base.metadata` 注册。

    ★ 为什么参数必填、不给默认值（这是门禁，不是风格偏好）：
      `core` 不认识任何业务模块名 —— 清单住在组合根 `wiring.MODEL_MODULES`
      （见该文件头「为什么要有这一层」）。签名必填 ⇒ 漏传直接 `TypeError`，
      而不是静默注册 0 个模型、让 `create_all` 建出一张空库
      （那是一个**没有任何报错的**故障，只在线上表现为「表不存在」）。

    ★ 机制 vs 清单：
      本函数只做**机制** —— 把一串模块名导进来（import 副作用 = ORM 类注册到
      `Base.registry`），**不关心**它们是谁。清单写死在 `core` 里就会形成
      `core → modules` 反向依赖（第 335 轮 P0-7 已消除该类 28 处）。

    ★ 唯一真源：清单有**两个消费者** —— `init_db()`（开发期 create_all 兜底）
      与 `alembic/env.py`（autogenerate 比对 `target_metadata`）。历史上两处
      各写一份，`env.py` 那份漏了 monitors / platform_rules / knowledge_base /
      voice_clone / aigc_media 共 5 个模块 ⇒ `target_metadata` 里少 9 张表
      ⇒ autogenerate 生成的迁移**静默漏表**。现在两者都读
      `wiring.MODEL_MODULES`，新增业务模块**只改那一处**。
    """
    for name in model_modules:
        importlib.import_module(name)


async def init_db(model_modules: Iterable[str]) -> None:
    """初始化数据库（创建表结构）。

    ★ `model_modules` 必填：理由见 `register_all_models` 的 docstring ——
      漏传必须炸 `TypeError`，而不是静默建空库。
    """
    register_all_models(model_modules)

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

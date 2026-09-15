"""
Alembic 环境配置

- 同步引擎（psycopg2），独立于业务 asyncpg 引擎
- target_metadata 指向业务 ORM 的 Base.metadata，用于 autogenerate
- 通过 python-dotenv 加载 backend/.env 拿到 DATABASE_URL
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# ====== 加载 .env（DATABASE_URL）======
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # 没装 dotenv 也能用 alembic.ini 里的 sqlalchemy.url

# this is the Alembic Config object
config = context.config

# 优先用环境变量 DATABASE_URL（asyncpg → psycopg2 转换）
db_url = os.getenv("DATABASE_URL", "")
if db_url.startswith("postgresql+asyncpg://"):
    db_url = "postgresql+psycopg2://" + db_url[len("postgresql+asyncpg://"):]
elif db_url.startswith("postgresql://"):
    db_url = "postgresql+psycopg2://" + db_url[len("postgresql://"):]
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ====== 业务 ORM MetaData（autogenerate 用）======
# 把项目根加进 path，方便 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import Base, register_all_models  # noqa: E402

# ★★ 模型清单只在 `core.database.register_all_models()` 维护一份，这里绝不重复列举。
#    历史事故：本文件曾自己列了一遍清单，但漏了 monitors / platform_rules /
#    knowledge_base / voice_clone / aigc_media 共 5 个模块 ⇒ `target_metadata`
#    少 9 张表 ⇒ autogenerate 生成的迁移**静默漏表**（不报错），
#    表现为全新库 upgrade 时报「relation xxx does not exist」。
register_all_models()

target_metadata = Base.metadata


# checkpoint_* 表由 LangGraph AsyncPostgresSaver.setup() 运行时创建，
# 不属于业务 ORM，必须排除在 autogenerate 之外，否则会被误判为「待删除表」。
_CHECKPOINT_PREFIXES = ("checkpoint",)


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name.startswith(_CHECKPOINT_PREFIXES):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 列类型变更也能检测
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

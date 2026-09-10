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

from core.database import Base  # noqa: E402

# 导入所有模型，确保它们被注册到 metadata
from modules.user_subscription.models import (  # noqa: E402,F401
    User, SubscriptionPlan, Subscription, Shop,
)
from modules.stores.db_model import StoreRecord  # noqa: E402,F401
from modules.products.db_model import (  # noqa: E402,F401
    SpuRecord, SkuRecord, ProductGroupRecord,
)
from modules.assets.db_model import (  # noqa: E402,F401
    AssetRecord, AssetGroupRecord,
)
from modules.candidates.db_model import (  # noqa: E402,F401
    CandidateRecord, CandidateGroupRecord,
)
from modules.amazon_sp.db_model import (  # noqa: E402,F401
    AmazonCredential, AmazonAuthLog, DailySales,
    AdMetric, ListingSnapshot, ReportTask, InventoryHealth,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

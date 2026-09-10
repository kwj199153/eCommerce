"""
Redis 连接 & Celery 配置模块

提供 Redis 连接管理和 Celery Worker 配置。
"""

import redis.asyncio as aioredis
from celery import Celery

from core.config import config


# ====== Redis 连接 ======
async def get_redis_client() -> aioredis.Redis:
    """获取异步 Redis 客户端"""
    return aioredis.from_url(
        config.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )


# ====== Celery 配置 ======
celery_app = Celery(
    "ecommerce_worker",
    broker=config.celery_broker_url,
    backend=config.celery_result_backend,
)

celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务配置
    task_track_started=True,
    task_time_limit=1800,  # 单任务最大执行时间(30分钟)
    worker_prefetch_multiplier=1,  # 每次只预取1个任务
    # 结果配置
    result_expires=3600,  # 结果保存1小时
    # 重试配置
    task_acks_late=True,  # 任务完成后再确认
    worker_max_tasks_per_child=1000,  # Worker 处理1000个任务后重启
)

# 自动发现任务模块
celery_app.autodiscover_tasks(["modules"])

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
    # ⚠️ 结果只保留 1 小时。**不要把 result backend 当作任务状态源** ——
    #    AIGC 出图产物是长期有效的 /static 链接，任务记录 1 小时后蒸发
    #    会让用户再也查不到自己花钱生成的图。
    #    权威状态源是 aigc_jobs 表（见 modules/aigc_media/db_model.py）。
    result_expires=3600,
    # 重试配置
    task_acks_late=True,  # 任务完成后再确认
    worker_max_tasks_per_child=1000,  # Worker 处理1000个任务后重启
    # 启动期 broker 不可达时持续重试（否则 worker 一启动就退出，
    # 在 compose 里表现为容器反复重启，排查方向容易被带偏）
    broker_connection_retry_on_startup=True,
)

# 队列：任务默认投到 default。worker.py 的 --queues 已包含 default，
# 因此**不需要** task_routes —— 少一层映射就少一类「任务投到没人监听的队列、
# 永远停在 pending」的故障。将来若要给出图单独扩容一批 worker，
# 再把 aigc.* 路由到 ai_tasks 队列（worker.py 已预留该队列名）。
celery_app.conf.task_default_queue = "default"

# 自动发现任务模块
# ★ 这里曾经是 autodiscover_tasks(["modules"]) —— 它找的是 `modules.tasks` 模块，
#   而本项目的任务定义在**子包**里（modules/aigc_media/tasks.py），
#   于是永远命中 0 个任务。现象是：Broker/Worker/compose 全部就绪、
#   `worker.py` 正常打印启动日志，但 `celery inspect registered` 是空的，
#   提交任务永远停在 pending。⇒ 必须指到**子包**。
celery_app.autodiscover_tasks(["modules.aigc_media"])

"""
Redis 连接 & Celery 配置模块

提供 Redis 连接管理和 Celery Worker 配置。
"""

import redis.asyncio as aioredis
from celery import Celery
from celery.schedules import crontab

from ai_infra.memory.limits import DISTILL_HOUR, DISTILL_MINUTE
from core.config import config


# ====== Redis 连接 ======
async def get_redis_client() -> aioredis.Redis:
    """获取异步 Redis 客户端。

    ★ 必须显式给超时：redis-py 默认的 connect 超时可以很长（TCP 层面几十秒），
      Redis 不可达时会把调用方（/health 探针、限流中间件）一起拖住 ——
      探针本身不该比被探测的服务更慢。
    """
    return aioredis.from_url(
        config.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=2,
        socket_timeout=5,
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
celery_app.autodiscover_tasks(["modules.aigc_media", "modules.memory"])

# ====== 定时任务（Celery Beat）======
# ★ 调度表定义在这里而不是 `modules/memory/tasks.py`：`beat_schedule` 是
#   **应用级**配置，beat 进程只读它、不 import 任何任务模块。
#   写在任务模块里的话，beat 就得先 import 业务代码才能知道"该调度什么" ——
#   一个语法错误会让整晚的调度一起消失。
#
# ★ 这里 import 的是一个**叶子常量模块**（`ai_infra/memory/limits.py` 零依赖，
#   不 import 任何 core / modules）⇒ 不构成 `core → ai_infra → core` 的环。
#   `test_core_internal_layering.py` 只登记 `core → core` 的边，本行不在它的网内。
#
# ★ 触发时刻与冷却窗口共用同一份真源（见 limits 的「蒸馏节奏」一节）：
#   两者写在同一个文件里，"改周期"不会漏改冷却。
#
# ★★ 任务名是**字面量**，这是刻意的（core 不得 import modules）——
#   于是它与 `modules/memory/tasks.py::TASK_DISTILL_ALL` 构成了"同一事实两份写法"。
#   写错时 beat 会往一个没人注册的名字投递：现象是"整晚没跑"。
#   ⇒ 由 `tests/test_memory_distill.py` 把两者**钉成相等**（而不是靠注释提醒）。
celery_app.conf.beat_schedule = {
    "memory-nightly-distill": {
        "task": "memory.distill_all_owners",
        # 用 crontab 而不是 timedelta：crontab 每次按**当前时间**重算下次触发点，
        # 不依赖调度文件的 last_run_at ⇒ 调度文件丢失/重建时不会漏掉一整天。
        "schedule": crontab(hour=DISTILL_HOUR, minute=DISTILL_MINUTE),
        # 明确投 default 队列（worker.py 的 --queues 已含它）。
        "options": {"queue": "default"},
    },
}

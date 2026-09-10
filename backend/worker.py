"""
Celery Worker 入口

用于执行异步任务（选品分析、AIGC生成、数据导出等耗时操作）。
"""

from core.redis import celery_app
from core.config import config

if __name__ == "__main__":
    print(f"🔧 启动 Celery Worker: {config.app_name}")
    celery_app.worker_main(
        [
            "--loglevel=info",
            "--queues=default,ai_tasks,data_export",
            "--concurrency=4",
            "-n", "worker1@%h",
        ]
    )

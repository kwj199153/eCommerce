"""Celery Beat 入口 —— 长期记忆的「每晚自动整理」（第 149 轮批 C2-4）。

## 为什么 beat 要独立于 worker

`celery worker -B` 把调度器塞进 worker 进程里，Celery 官方文档明确说它
只适合开发调试。本项目的情况更具体，两条理由各自都能独立成立：

1. **进程职责**。worker 用 `--pool=threads`，任务体与 `/metrics` 共享一个进程
   （原因见 `worker.py` 顶部）。把调度器也塞进来，它就与业务执行抢同一个 GIL；
   而且 worker 重启会把"下一次该几点跑"一起丢掉。
2. **schedule 文件必须独占**。调度器需要一个可写文件记录 `last_run_at`
   （默认 CWD 下的 `celerybeat-schedule`）。与 worker 共进程时，本机跑第二个
   worker 就会互抢这个文件，报 `PermissionError` 或**静默不触发** ——
   后者的现象是"整晚没跑"，属于最难排查的那一类。

⇒ 独立进程（与 `worker.py` 同构：同镜像、不同 command）；
   `docker-compose.yml` 里的 `beat` 服务就是它。

## 为什么 schedule 文件落在 logs/ 下

默认路径是**当前工作目录**下的 `celerybeat-schedule`。容器里 CWD 是 `/app`，
写进去要么污染镜像层、要么在 `git status` 里冒出来。`logs/` 已被
`.gitignore` 覆盖（`logs/`），且 compose 里是一个持久卷 ⇒ 两个问题一起解决。

★ 该文件丢失不会导致"这一天不跑"：crontab 调度每次都按**当前时间**重算下次
  触发点，不像 interval 调度那样依赖 `last_run_at`。
"""

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger
from core.redis import celery_app

logger = get_logger("beat")

#: schedule 文件路径。可用 `CELERYBEAT_SCHEDULE_FILE` 覆盖。
SCHEDULE_FILE = Path(
    os.getenv("CELERYBEAT_SCHEDULE_FILE")
    or str(Path(__file__).resolve().parent / "logs" / "celerybeat-schedule")
)


if __name__ == "__main__":
    # ★ loguru 用 ``{}`` 占位，**不认** stdlib 的 ``%s``（`worker.py` 记过这条）。
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)

    entries = celery_app.conf.beat_schedule or {}
    logger.info("[beat] 启动 Celery Beat，定时任务共 {} 条", len(entries))
    for name in sorted(entries):
        spec = entries[name] or {}
        logger.info(
            "[beat]   {} -> task={} schedule={}",
            name,
            spec.get("task"),
            spec.get("schedule"),
        )
    logger.info("[beat] schedule 文件：{}", SCHEDULE_FILE)

    # ★ 用 `celery_app.start(argv=[...])` 而不是 `worker_main`：beat 不是 worker
    #   子命令（`worker_main` 会在 argv 里找字面量 "worker"，传 "beat" 会直接
    #   抛 ValueError）。`start()` 把 argv 交给 celery 的 CLI 解析。
    celery_app.start(
        argv=["beat", "--loglevel=info", "-s", str(SCHEDULE_FILE)]
    )

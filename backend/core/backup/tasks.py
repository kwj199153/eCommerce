"""数据库每日备份的 **Celery 接线**（第 340 轮 / P0-2）。

核（**怎么备份**：`pg_dump` → 结构校验 → 深度校验 → 原子落盘 → 轮转，
外加 `verify` / `drill` / `restore`）住在 `backend/scripts/backup_db.py`；
本文件只做三件机制性的事：

  ① 注册任务名 —— beat 按**名字**投递，见 `core/redis.py::beat_schedule`；
  ② 把脚本执行成**一次带超时的子进程**，并把退出码翻译成 ok / failed；
  ③ 把结局写进**日志与指标** —— 定时任务的失效默认是静默的，必须有两个出口。

==============================================================================
★★ 为什么「有备份脚本」不等于「有备份」（本轮修的到底是什么）
==============================================================================
`backend/scripts/backup_db.py` 从 P0-2 起就在，写得也对（含校验、演练、轮转），
但在本轮之前**生产里没有任何东西会去调用它** —— 没有 beat 条目、没有任务、
没有 cron。于是 `backups/` 目录只在有人手动跑时才会出现新文件，而"手动跑"
这件事没人会天天记得。这正是本仓记过多次的形态：

    ★ 每个零件都是好的，缺的只是没有任何东西会去调用它。
      同款先例：`core/audit/` 的保留期清理（第 328 轮）、
                `core/identity/` 的两张表清理（第 331 轮）。

⇒ 验收判据不能只是"脚本能跑"，必须钉住**真的接上了调度**
  （见 `tests/test_backup_schedule.py`）。

==============================================================================
★★ 为什么本任务体**不需要** `_thread_loop()`（与 audit / identity 相反）
==============================================================================
audit / identity 的清理任务要**开数据库会话**（asyncpg），而 Celery worker 是
同步进程 ⇒ 必须用每线程常驻 event loop 复用应用级连接池（否则第二次执行报
`Task got Future attached to a different loop`）。

本任务**不碰数据库连接**：它只是 `subprocess.run([python, backup_db.py, ...])`，
真正的库访问发生在**子进程**里（`pg_dump` / `pg_restore` 通过 `docker exec`
在容器内跑）。⇒ 任务体内既没有协程、也没有工作 loop，故**无需** `_thread_loop`，
也**禁止**为它引入 `asyncio.run()` —— 那只会凭空造出一个没人 join 的 loop。

==============================================================================
★★ 为什么用**子进程**调脚本、而不是 import 它的函数
==============================================================================
  · `backup_db.py` 是**命令行脚本**（`scripts/` 不是包、无 `__init__.py`）——
    import 它得先造出 `scripts` 包身份，那是一层与"备份"无关的耦合；
  · 脚本对外**唯一稳定的契约是退出码**（0=成功 / 1=参数与环境错误 /
    2=备份校验失败），正是子进程形态的天然产物；
  · 备份是**重 IO / 长耗时**操作，塞进 worker 主进程只会和别的任务抢 GIL 与
    文件句柄；隔一层进程边界后，超时 / 异常都收敛在子进程里。

★ 退出码必须**翻译成异常**（而不是记个 warning 继续）：脚本的 2 表示
  「备份文件不可用」。若这里把它吞掉，"备份失败"与"备份成功"在任务结果里
  长得一模一样 —— 正是本仓反复记的"假成功"。同款判据见
  `modules/trade/tasks.py::sync_shop`、`core/audit/tasks.py`。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from core.config import config
from core.logger import get_logger
from core.observability.metrics import BACKUP_LAST_BYTES, BACKUP_RUNS
from core.redis import celery_app

logger = get_logger("backup.tasks")

#: 任务注册名。★ 集中定义一次：它同时出现在
#:   · 本文件的 `@celery_app.task(name=...)`
#:   · `core/redis.py::beat_schedule` 里的**字面量**（core 不得 import modules，
#:     同理也不该为了取一个名字而让 beat 去 import 任务模块）
#: 写错时 beat 会往一个没人注册的名字投递 —— 现象是「`backups/` 再不长新文件，
#: 且日志里一条都没有」（"没人消费"本身不是错误 ⇒ 什么都不会发生）。
#: ⇒ 由 `tests/test_backup_schedule.py` 把两边**钉成相等**（不是靠注释提醒）。
TASK_DB_BACKUP = "backup.db_daily"

#: 仓库 `backend/` 目录（本文件在 `core/backup/` 下 ⇒ parents[2]）。
BACKEND = Path(__file__).resolve().parents[2]
#: 备份脚本（核）。零第三方依赖：只用标准库 + docker CLI。
BACKUP_SCRIPT = BACKEND / "scripts" / "backup_db.py"

#: 子进程超时（秒）。★ 必须**严格小于** Celery 的 `task_time_limit`（1800s，
#: 见 `core/redis.py`）：否则超时那一刻先被 Celery 硬杀（任务被标 FAILURE 但
#: **我们的 except 没机会执行**），于是"备份卡死"在指标上表现为"没跑"
#: —— 与 BackupStalled 同形，归因方向被带偏。留 300s 余量。
BACKUP_TIMEOUT_SECONDS = int(os.getenv("DB_BACKUP_TIMEOUT_SECONDS", "1500") or "1500")


def _newest_dump_size(out_dir: Path) -> int:
    """`backups/` 下最新一份 `.dump` 的字节数（找不到 / 读不到返回 0）。"""
    try:
        dumps = sorted(
            out_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return 0
    return dumps[0].stat().st_size if dumps else 0


def _run_backup() -> Dict[str, Any]:
    """跑一次 `backup_db.py backup`；**非 0 退出码一律抛错**。

    返回 `{"file", "bytes"}`（仅作排查线索）。异常**不吞** —— 由调用方记完
    指标后原样抛出，让 Celery 把任务标 FAILURE 并留 traceback。
    """
    if not BACKUP_SCRIPT.is_file():
        # ★ 脚本路径漂移（被移动 / 改名）时，若这里静默返回"成功"，
        #   现象是"每天都跑、每天都成功、就是没有新备份文件"。
        raise FileNotFoundError(f"备份脚本不存在：{BACKUP_SCRIPT}")

    cmd = [
        sys.executable,
        str(BACKUP_SCRIPT),
        "backup",
        "--keep",
        str(config.db_backup_keep),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=BACKUP_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-800:]
        raise RuntimeError(
            f"backup_db.py 退出码={proc.returncode}"
            f"（0=成功 / 1=参数与环境错误 / 2=备份校验失败）。尾部输出：{tail}"
        )

    # 脚本成功时会打印 `RESULT: OK  <绝对路径>`。解析它拿到文件名；
    # 解析不到就退化为"看 backups/ 里最新的那份"（口径与脚本同源）。
    out_dir = BACKEND.parent / "backups"
    picked = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT: OK"):
            picked = line.split("RESULT: OK", 1)[1].strip()
    size = 0
    if picked:
        p = Path(picked)
        size = p.stat().st_size if p.is_file() else 0
    if not size:
        size = _newest_dump_size(out_dir)
    return {"file": Path(picked).name if picked else "", "bytes": size}


@celery_app.task(bind=True, name=TASK_DB_BACKUP)
def db_backup_daily(self) -> Dict[str, Any]:
    """beat 入口：每天跑一次数据库备份（dump + 校验 + 轮转）。

    返回值只作**排查线索**，不作为状态源（状态看日志与指标）。
    """
    started = time.perf_counter()
    try:
        info = _run_backup()
    except Exception:  # noqa: BLE001 —— 记完指标再原样抛出，绝不吞
        # ★ 先记指标再抛：Celery 的 FAILURE 只活在 worker 日志/结果后端里
        #   （结果 1 小时后过期，见 core/redis.py 的 result_expires）；
        #   指标才能被 Prometheus 抓成**长期**告警（BackupFailing / BackupStalled）。
        BACKUP_RUNS.inc(status="failed")
        logger.exception("数据库每日备份失败")
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    BACKUP_RUNS.inc(status="ok")
    if info.get("bytes"):
        # ★ 大小单独一个 gauge：`runs{status}` 只答"跑没跑成"，答不了"备了多少"。
        #   持续偏小 ⇒ dump 被截断 / 库被清空；长期不变 ⇒ 备份没真的重跑过。
        BACKUP_LAST_BYTES.set(info["bytes"])
    logger.info(
        "数据库每日备份完成：{}（{} bytes，保留最近 {} 份），耗时 {}ms",
        info.get("file") or "<未知文件名>",
        info.get("bytes"),
        config.db_backup_keep,
        elapsed_ms,
    )
    return {"ok": True, **info, "elapsed_ms": elapsed_ms}

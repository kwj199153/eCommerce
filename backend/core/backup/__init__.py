"""数据库备份内核域的门面（★ 第 340 轮 / P0-2）。

★ 这个包**没有可导出的公共 API**，所以 `__init__.py` 只有这一段文档。
  取舍与 `core/audit/__init__.py` 逐字同源：

  · 备份的**核**（dump → 结构校验 → 深度校验 → 原子落盘 → 轮转，外加
    `verify` / `drill` / `restore`）住在 `backend/scripts/backup_db.py` ——
    它是一个**零第三方依赖的命令行脚本**（只用标准库 + docker CLI），
    刻意不做成 Python 包：这样 CI / 运维机能直接
    `python scripts/backup_db.py backup` 跑，无需装项目依赖、也无需连库。
  · 本包只承载**调度接线**（`tasks.py`）：把脚本跑成一次带超时的子进程，
    并把结局写进日志与指标。

★ 刻意**不**在 `__init__.py` 里 re-export `tasks`：
  那会把 `celery` 变成「任何一次 `import core.backup`」的硬依赖
  —— 连只想要一个包身份的地方也要付出这个代价（同 `core/audit/__init__.py`
  里「不导出 tasks / router」的理由）。★ 本轮**没有**任何别的代码需要
  import 本包：它只被 `core/redis.py::autodiscover_tasks(["core.backup"])`
  按**包名**发现一次。

★ 本模块的 import 期边：无（纯文档，不 import 任何 core 单元）。
"""

# `core/identity` 的包说明（★ 第 331 轮补；此前是 0 字节空壳）。
#
# ★ 为什么这里**刻意不 re-export** `tasks`（`purge_expired_identity_rows`）：
#   本包被 `wiring.MODEL_MODULES` 在 **import 期**导入
#   （它要 `User` / `EmailToken` / `LoginAttempt` 这些 ORM 实体）。
#   在这里 re-export `core.identity.tasks` 会把 `celery` 变成
#   「任何一次 `import core.identity`」的硬依赖 ——
#   连只想要实体类的注册表也要付出这个代价。
#   ⇒ 已注册的 Celery 任务由 `core/redis.py::autodiscover_tasks(["core.identity"])`
#     在 worker / beat 进程里加载，与业务进程的 import 图无关。
#   同款理由见 `core/audit/__init__.py`（那里还解释了"为什么不导出 router"）。
#
# ★ 也不在里 re-export 业务函数（`purge_old_attempts` / `hash_token` 等）：
#   本仓 core 内部**不建包门面** —— 子包不是模块边界，而是同一个内核的实现分解。
#   理由见 `tests/test_core_internal_layering.py` 文件头
#   「★ 为什么 core 内部不建包门面，而 modules/ 之间要建」。

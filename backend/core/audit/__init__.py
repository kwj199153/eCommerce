"""审计内核域的门面 —— 通用审计日志（P0-5）。

★ 为什么这个包有门面（re-export）
  与 `core/stores/__init__.py` 同一条理由：**包只有 re-export，才能让
  「从包取名字」成为唯一消费方式**。否则消费方只能
  `from core.audit.service import record_audit` —— 那是伸手进包内部，
  而「从包取」与「伸手进包」在 AST 上长得一样，门禁没法禁止越界取内部文件。

★ 公开面（改这里必须同步核对全部消费点）
  - `record_audit`  —— 审计写入的**唯一路径**（自带会话，见 service.py）
  - `AuditLog`      —— `audit_logs` 表 ORM 实体（读口查询用）
  - `ACTIONS`       —— 动作目录 `(动作, 说明, 目标类型)`，读口与前端筛选共用
  - `ACTION_*`      —— 动作名常量（**调用点必须用常量，禁止裸字符串**）
  - `STATUS_*` / `STATUSES` —— 结果枚举
  - `TARGET_*` / `TARGET_TYPES` —— 目标类型枚举

★ 刻意**不导出** `router`：
  读口（`core/audit/router.py`）依赖 FastAPI 依赖注入链（`core.auth.dependencies`）。
  若在这里 re-export 它，任何一次 `import core.audit` —— 包括
  `register_all_models()` 里那一行模型注册 —— 都会顺带把鉴权链拉进 import 期。
  注册表只想要 ORM 实体，不该为此付出「拉起整个鉴权栈」的代价。
  ⇒ 读口由 `main.py` 直接 import（既有范式，见 main.py 里各 router 的挂载）。

★ 同样**不导出** `tasks` / `retention`（第 328 轮）：
  `core/audit/tasks.py` 是 Celery 任务（依赖 `core.redis`，即 celery 本身）。
  若在这里 re-export，`celery` 就会变成「任何一次 `import core.audit`」的硬依赖
  —— 连只想要 ORM 实体的模型注册表也得付出这个代价（与上一条 router 同源）。
  ★ 清理核 `purge_expired` 由任务模块自己 import：它**不是**业务入口 ——
    业务侧只需要**写**审计，不需要（也不应该）删。
"""

from core.audit.actions import (
    ACTION_LOGIN_SUCCESS,
    ACTION_MEMBER_REMOVE,
    ACTION_MEMBER_UPDATE,
    ACTION_STORE_CONNECT,
    ACTION_STORE_DELETE,
    ACTION_STORE_DISCONNECT,
    ACTION_STORE_TRANSFER,
    ACTIONS,
    KNOWN_ACTIONS,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    STATUSES,
    TARGET_ACCOUNT,
    TARGET_MEMBER,
    TARGET_SESSION,
    TARGET_STORE,
    TARGET_TYPES,
    TARGET_USER,
)
from core.audit.models import AuditLog
from core.audit.service import record_audit

__all__ = [
    # 写入与实体
    "AuditLog",
    "record_audit",
    # 动作
    "ACTIONS",
    "KNOWN_ACTIONS",
    "ACTION_LOGIN_SUCCESS",
    "ACTION_STORE_CONNECT",
    "ACTION_STORE_DISCONNECT",
    "ACTION_STORE_TRANSFER",
    "ACTION_STORE_DELETE",
    "ACTION_MEMBER_UPDATE",
    "ACTION_MEMBER_REMOVE",
    # 结果
    "STATUSES",
    "STATUS_SUCCESS",
    "STATUS_FAILURE",
    # 目标类型
    "TARGET_TYPES",
    "TARGET_USER",
    "TARGET_STORE",
    "TARGET_ACCOUNT",
    "TARGET_MEMBER",
    "TARGET_SESSION",
]

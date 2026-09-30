"""
Redis 连接 & Celery 配置模块

提供 Redis 连接管理和 Celery Worker 配置。
"""

import redis.asyncio as aioredis
from celery import Celery
from celery.schedules import crontab

from core.config import (
    BILLING_EXPIRE_PENDING_INTERVAL_MINUTES,
    BILLING_RECONCILE_HOUR,
    BILLING_RECONCILE_MINUTE,
    BILLING_SWEEP_HOUR,
    BILLING_SWEEP_MINUTE,
    MEMORY_DISTILL_HOUR,
    MEMORY_DISTILL_MINUTE,
    config,
)


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
celery_app.autodiscover_tasks([
    "modules.aigc_media",
    "modules.memory",
    # ★ 2026-09-25：计费的三条定时任务（待支付回收 / 订阅到期清算 / 支付对账）。
    #   漏了这一行会怎样：任务装饰器依然会执行（因为 autodiscover 只是"去哪些
    #   包找 tasks 模块"的清单），但只要**没有任何进程 import 过** modules.billing.tasks，
    #   任务就没被注册 —— `celery inspect registered` 里查不到它，
    #   而 beat 会照常按调度表投递 ⇒ 任务永远停在 pending，日志里一条都没有。
    #   ★ 这是"配置写了、实现也在、就是没生效"的典型，靠 beat 的日志看不出来。
    "modules.billing",
    # ★ 第 283 轮：交易履约域的定时同步（订单 / 物流 / 差评落库）。
    #   漏掉这一行的后果与上面 billing 那行**逐字相同**：装饰器没被执行过
    #   ⇒ `celery inspect registered` 里查不到，而 beat 照常按调度表投递
    #   ⇒ 任务永远停在 pending，日志里一条都没有。
    "modules.trade",
    # ★ 第 328 轮：通用审计的**保留期清理**（`core/audit/tasks.py`）。
    #   ★★ 这一条与上面几条**不同**：它指向的是 `core` 下的包，不是 modules。
    #      审计的内核（模型 / 写路径 / 读口 / 清理核）整体住在 `core/audit/`，
    #      清理只是它自己的编排 ⇒ 任务定义跟着内核走，不另开一个
    #      `modules/audit` 空壳域（那个域将不含任何业务代码）。
    #   ★ 漏了这一行的后果与上面逐字相同：装饰器从未被执行过
    #     ⇒ `celery inspect registered` 里查不到它，而 beat 照常按调度表投递
    #     ⇒ 任务永远停在 pending，日志里一条都没有。
    "core.audit",
    # ★ 第 331 轮：身份域的**保留期清理**（`core/identity/tasks.py`）。
    #   它接的是两个**此前零调用点**的清理例程：登录审计 `login_attempts`
    #   （`login_guard.purge_old_attempts`）与邮件一次性 token `email_tokens`
    #   （`email_tokens.purge_spent_tokens`）—— 从前只有测试调它们，
    #   于是两张表在生产里**只增不减**（实测开发库 14 天累积 3169 行登录审计）。
    #   ★ 同样是"指向 core 下的包"：清理例程跟着内核走，
    #     不为此新开一个不含任何业务代码的 `modules/identity` 空壳域。
    #   ★ 漏了这一行的后果与上面逐字相同：装饰器从未被执行过
    #     ⇒ `celery inspect registered` 里查不到它，而 beat 照常按调度表投递
    #     ⇒ 任务永远停在 pending，日志里一条都没有。
    "core.identity",
    # ★ 第 340 轮：数据库**每日备份**（`core/backup/tasks.py`）。
    #   它把此前**零调度**的 `scripts/backup_db.py` 接上 beat ——
    #   在此之前生产里没有 cron / 没有任务，"备份"只在有人手动跑时发生。
    #   ★ 同样是"指向 core 下的包"：备份的核跟着驱动它的脚本走，
    #     不为此新开一个不含业务代码的 `modules/backup` 空壳域。
    #   ★ 漏了这一行的后果与上面逐字相同：装饰器从未被执行过
    #     ⇒ `celery inspect registered` 里查不到它，而 beat 照常按调度表投递
    #     ⇒ 任务永远停在 pending，日志里一条都没有。
    "core.backup",
])

# ====== 定时任务（Celery Beat）======

#: 交易履约同步的节奏（订单 / 物流 / 买家评论落库）。
#: ★ 为什么不进 `core/config`：只有本文件的调度表用它。进 config 会让它看起来
#:   像「一个可以随时翻的业务开关」，而改它的实际代价是「同步窗口变了」——
#:   那是运维事件，不是配置开关。
#: ★ 分钟取 23 而不是 0：与 memory（凌晨 3 点档）/ billing（整点与每 N 分钟）
#:   错峰，避免同一时刻一堆任务抢同一条 `default` 队列。
TRADE_SYNC_INTERVAL_HOURS = 6
TRADE_SYNC_MINUTE = 23

#: 审计保留期清理的触发时刻（★ 第 328 轮）。
#: ★ 小时取 5、分钟取 7，两处都是刻意错峰：
#:   · 分钟 **7** —— `billing-expire-pending` 是 `*/5`（每 5 分钟一次，
#:     即所有 5 的倍数分钟），7 落在它的两条之间，不会被它排队顶住；
#:   · 小时 **5** —— memory 在 3:00、billing 巡检在 3:20、支付对账在 4:30，
#:     5:07 排在对账之后：当天的审计写入已经收敛，
#:     "删多少行"这个数字才不会被当天未落地的写入搅动。
AUDIT_PURGE_HOUR = 5
AUDIT_PURGE_MINUTE = 7

#: 身份域保留期清理的触发时刻（★ 第 331 轮）。
#: ★ 小时同样取 **5**、分钟取 **17**（与审计那条错开 10 分钟）：
#:   · 分钟 **17** —— 同样避开 `billing-expire-pending` 的 `*/5` 边界（5 的倍数），
#:     也不与审计的 7 撞在一起；
#:   · 小时 **5** —— 理由与审计那条**逐字相同**：memory 在 3:00、billing 巡检在
#:     3:20、支付对账在 4:30，5 点档排在这些之后，"删多少行"这个数字才不会被
#:     当天尚未收敛的写入搅动。
#: ★ 为什么不是与审计**同一个**任务/时刻：两张表 + 两张表 = 四张表的清理混在
#:   一个任务里，出问题时"是哪一半挂了"只能靠猜；而分成两条 beat 条目后，
#:   各自的 runs/deleted 指标天然分开，告警也能分别定位。
IDENTITY_PURGE_HOUR = 5
IDENTITY_PURGE_MINUTE = 17

#: 数据库每日备份的触发时刻（★ 第 340 轮 / P0-2）。
#: ★ 小时取 **2**、分钟取 **41**，两处都是刻意错峰：
#:   · 分钟 **41** —— 避开 `billing-expire-pending` 的 `*/5` 边界（5 的倍数）；
#:   · 小时 **2** —— 排在**维护窗口之前**（memory 3:00 / billing 3:20 /
#:     支付对账 4:30 / audit 清理 5:07 / identity 清理 5:17）。
#:     备份要拍的是"前一天收敛后的快照"，所以它应当在这些"删数据"的任务
#:     **之前**跑；排在它们之后会拍到一份被当天清理改过的库，
#:     与"日终快照"的语义不符。
BACKUP_HOUR = 2
BACKUP_MINUTE = 41
# ★ 调度表定义在这里而不是 `modules/memory/tasks.py`：`beat_schedule` 是
#   **应用级**配置，beat 进程只读它、不 import 任何任务模块。
#   写在任务模块里的话，beat 就得先 import 业务代码才能知道"该调度什么" ——
#   一个语法错误会让整晚的调度一起消失。
#
# ★ 2026-09-30（P0-7 分层修复）：触发时刻原先 import 自
#   `ai_infra/memory/limits.py`（一个零依赖叶子模块），已上移到
#   `core/config.py` 的 `MEMORY_DISTILL_HOUR` / `MEMORY_DISTILL_MINUTE`。
#   原因：即便 limits 零依赖、不构成环，`core → ai_infra` 仍与分层方向相反；
#   把"部署侧调度时刻"收到 core/config 后，core 层不再 import ai_infra / modules。
#   ⇒ 触发时刻（core/config）与冷却窗口（ai_infra/memory/limits.py）现分居两处，
#   二者的一致性由 `tests/test_memory_distill.py` 断言（不再靠"同一文件"提醒）。
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
        "schedule": crontab(
            hour=MEMORY_DISTILL_HOUR, minute=MEMORY_DISTILL_MINUTE
        ),
        # 明确投 default 队列（worker.py 的 --queues 已含它）。
        "options": {"queue": "default"},
    },
    # ====== 计费（P1，2026-09-25）======
    #
    # ★★ 任务名是**字面量**，与上面那条 memory 同款理由：core 不得 import modules，
    #   于是它与 `modules/billing/tasks.py::TASK_*` 构成"同一事实两份写法"。
    #   写错时的现象是「beat 往一个没人注册的名字投递 ⇒ 静默不跑」——
    #   由 `tests/test_billing_schedule.py` 把两边钉成相等（不是靠注释提醒）。
    #
    # 三条任务的分工与它们各自防的问题，见 modules/billing/tasks.py 模块 docstring。
    "billing-expire-pending": {
        # 回收超时未支付的账单。★ 用分钟级 crontab：TTL 是 30 分钟，
        # 回收频率远高于 TTL 即可，再密没有收益（TTL 没到就不会命中）。
        "task": "billing.expire_pending_invoices",
        "schedule": crontab(minute=f"*/{BILLING_EXPIRE_PENDING_INTERVAL_MINUTES}"),
        "options": {"queue": "default"},
    },
    "billing-sweep-subscriptions": {
        # 订阅到期清算：把 current_period_end 已过的 active 订阅收口。
        "task": "billing.sweep_expired_subscriptions",
        "schedule": crontab(hour=BILLING_SWEEP_HOUR, minute=BILLING_SWEEP_MINUTE),
        "options": {"queue": "default"},
    },
    "billing-reconcile-alipay": {
        # 支付对账：补漏单（webhook 丢了）+ 揪幽灵单（我们以为收了、支付宝说没有）。
        # ★ 排在到期清算之后，让当天的最终状态收敛（见 config 里该时刻的注释）。
        "task": "billing.reconcile_alipay_orders",
        "schedule": crontab(hour=BILLING_RECONCILE_HOUR, minute=BILLING_RECONCILE_MINUTE),
        "options": {"queue": "default"},
    },
    # ====== 交易履约同步（第 283 轮）======
    #
    # ★★ 任务名是**字面量**，与上面 memory / billing 同款理由：core 不得 import
    #    modules ⇒ 它与 `modules/trade/tasks.py::TASK_SYNC_ALL_SHOPS` 构成
    #    「同一事实两份写法」。写错时 beat 会往一个没人注册的名字投递，
    #    现象是「订单表永远不更新，且没有任何日志」。
    #    ⇒ 由 `tests/test_trade_schedule.py` 把两边**钉成相等**（不是靠注释提醒）。
    #
    # ★ 为什么这里只投递 `sync_all_shops` 而不是逐店各来一条：
    #    店铺是运行期数据（会增减），写死在调度表里就会变成
    #    「新开的店永远不被同步，且没人发现」。⇒ beat 只负责敲一次门，
    #    由任务自己枚举店铺再 fan-out（见 modules/trade/tasks.py）。
    "trade-sync-all-shops": {
        "task": "trade.sync_all_shops",
        "schedule": crontab(
            hour=f"*/{TRADE_SYNC_INTERVAL_HOURS}", minute=TRADE_SYNC_MINUTE),
        "options": {"queue": "default"},
    },
    # ====== 通用审计保留期清理（第 328 轮）======
    #
    # ★★ 任务名是**字面量**，理由同上（core 不得 import modules）：它与
    #    `core/audit/tasks.py::TASK_PURGE_EXPIRED` 构成「同一事实两份写法」。
    #    写错时的现象是「审计表只增不减，且日志里一条都没有」——
    #    （beat 往一个没人注册的名字投递，队列里只是多了一条没人认识的消息，
    #     "没人消费"本身不是错误 ⇒ 什么都不发生。）
    #    ⇒ 由 `tests/test_audit_retention_gate.py` 把两边**钉成相等**。
    #
    # ★ 为什么用 crontab 而不是 timedelta：同 memory 那条理由 ——
    #   crontab 每次按**当前时间**重算下次触发点，不依赖调度文件的 last_run_at，
    #   于是调度文件丢失 / 重建时不会漏掉一整天。
    "audit-purge-expired": {
        "task": "audit.purge_expired",
        "schedule": crontab(hour=AUDIT_PURGE_HOUR, minute=AUDIT_PURGE_MINUTE),
        "options": {"queue": "default"},
    },
    # ====== 身份域保留期清理（第 331 轮）======
    #
    # ★★ 任务名是**字面量**，理由同上（core 不得 import modules）：它与
    #    `core/identity/tasks.py::TASK_PURGE_EXPIRED` 构成「同一事实两份写法」。
    #    写错时的现象是「login_attempts / email_tokens 只增不减，
    #    且日志里一条都没有」——（beat 往一个没人注册的名字投递，
    #    队列里只是多了一条没人认识的消息，"没人消费"本身不是错误
    #    ⇒ 什么都不发生。）
    #    ⇒ 由 `tests/test_identity_retention_gate.py` 把两边**钉成相等**。
    #
    # ★ 为什么这一个任务覆盖**两张表**（而不是拆成两条）：
    #   两个清理核都刻意"只删不 commit"，本任务把它们放进**同一个会话**
    #     ⇒ commit 是唯一落地点，不会出现"删了一半而任务报成功"。
    #   理由与代价的完整版见 `core/identity/tasks.py` 的模块 docstring。
    "identity-purge-expired": {
        "task": "identity.purge_expired",
        "schedule": crontab(hour=IDENTITY_PURGE_HOUR, minute=IDENTITY_PURGE_MINUTE),
        "options": {"queue": "default"},
    },
    # ====== 数据库每日备份（第 340 轮 / P0-2）======
    #
    # ★★ 任务名是**字面量**，理由同上（core 不得 import modules）：它与
    #    `core/backup/tasks.py::TASK_DB_BACKUP` 构成「同一事实两份写法」。
    #    写错时的现象是「`backups/` 再不长新文件，且日志里一条都没有」——
    #    （beat 往一个没人注册的名字投递，队列里只是多了一条没人认识的
    #    消息，"没人消费"本身不是错误 ⇒ 什么都不发生。）
    #    ⇒ 由 `tests/test_backup_schedule.py` 把两边**钉成相等**。
    #
    # ★ 为什么用 crontab 而不是 timedelta：同 memory 那条理由 ——
    #   crontab 每次按**当前时间**重算下次触发点，不依赖调度文件的
    #   last_run_at ⇒ 调度文件丢失 / 重建时不会漏掉一整天。
    #
    # ★ 为什么这条**没有**对应的"清理核"：备份是**只增**的（快照），
    #   它的"保留期"由脚本自己的 `--keep` 轮转处理，不在 beat 里再做一次。
    "db-backup-daily": {
        "task": "backup.db_daily",
        "schedule": crontab(hour=BACKUP_HOUR, minute=BACKUP_MINUTE),
        "options": {"queue": "default"},
    },
}

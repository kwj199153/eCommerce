"""审计日志的**保留期清理核**（`audit_logs`，第 328 轮）。

==============================================================================
★★ 为什么清理**不能**写进 `service.py`（本模块存在的理由）
==============================================================================
`core/audit/models.py` 的文件头把 `audit_logs` 定义为 **append-only**：

    本表只有 INSERT，没有 UPDATE / DELETE。
    保留期清理（若将来需要）必须走**独立的、显式的**归档任务，
    而不是这里的方法。

理由不是洁癖，而是**证据完整性**：一张能被随手 UPDATE / DELETE 的表，
它的每一行都不再能证明任何事（「这条记录没被改过」本身无法自证）。
所以清理必须住在一个**名字里就写着"清理"**的独立模块里 ——
读代码的人一眼能看见"谁能删审计"，而不是在写路径里翻出一个隐藏分支。

⇒ 本模块是**唯一的删除路径**（对应 `service.py` 是唯一的写入路径）。
   `tests/test_audit_retention_gate.py` 钉住「删 `audit_logs` 只出现在这里」。

==============================================================================
★★ 为什么是「定时任务」而不是「写的时候顺手清一把」
==============================================================================
直觉方案：每次 `record_audit()` 时按概率删一批旧行（机会式清理）——
不用任何调度器，听起来更省事。但它把**删除塞进了业务写路径**：

  · `record_audit()` 是**旁路**，契约是"绝不阻断业务、绝不变慢业务"
    （见 `service.py` 文件头）。在里面做一次 DELETE，等于把
    「审计表的体量」变成「业务写操作延迟」的隐式函数 —— 表越大业务越慢，
    而且**没有任何地方会报错**。
  · 清理的失效必须**可被看见**。在定时任务里，跑没跑 / 删了多少
    是一等公民（有日志、有指标、有返回值）；散在写路径里则无从观测。

⇒ 定时任务（`core/audit/tasks.py`）+ beat 调度（`core/redis.py::beat_schedule`）。
  控制流与 `core/identity/login_guard.py::purge_old_attempts` 同源，
   但那个函数**至今零调用点**（只有测试调）—— 所以本轮的验收判据不只是
   「函数写得对」，而是「**真的接上了调度**」，见同名门禁。

==============================================================================
★★ 「保留期」是配置，不是常量
==============================================================================
`config.audit_retention_days`（默认 90 天）。★ 刻意与
`config.login_attempt_retention_days`（30 天）**分开**：两张表的写入速率与
「留多久才有排查价值」完全不同（理由见 `core/config.py` 该字段的注释）。
写死成常量则"想延长审计追溯期"必须改代码 + 重新发版，
而这类需求（合规要求、事故复盘）常常是**当天就要生效**的。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit.models import AuditLog
from core.config import config


#: 保留期的**下限**（天）。★ 它不是可配项，是防呆下限：
#: 配成 0 / 负数时若不钳住，本任务会退化成「每次清空全表」——
#: 一条**不可逆**的数据销毁路径，而「配置写错」不该有这个后果。
#: ★ 钳到 1（而不是钳到 90）是刻意选**错得轻**的那一侧：真要清干净的人会
#:   立刻发现「怎么只删了 1 天前的」（可观测、可回退）；钳到 0 的那一侧
#:   后果是"整表没了"。
MIN_RETENTION_DAYS = 1


def retention_cutoff(
    retention_days: Optional[int] = None, *, now: Optional[datetime] = None
) -> datetime:
    """返回清理的**时间下界**：`created_at` 早于它的行会被删。

    ★ 为什么把这段算法单独抽成一个函数：它是本任务里**唯一会造成不可逆
      后果**的一段逻辑（方向写反 ⇒ 删掉近期证据）。
      抽成纯函数后，门禁可以用**纯算术断言**把它钉死，
      而不必真的对共享库执行一次全局 DELETE —— 那会把历史行真删掉，
      「验证代码的测试」不该有这种副作用。
    """
    days = int(
        retention_days if retention_days is not None else config.audit_retention_days
    )
    base = now if now is not None else datetime.utcnow()
    return base - timedelta(days=max(MIN_RETENTION_DAYS, days))


async def purge_expired(db: AsyncSession, retention_days: Optional[int] = None) -> int:
    """删除 `created_at` 早于保留期的审计行，返回**实际删除的行数**。

    ★ 只**删**、不 commit：事务边界留给调用方。
      `record_audit()` 是自带会话自提交的旁路，本核刻意**相反** ——
      这样测试能把它塞进自己的事务里回滚（同 `modules/trade/sync.py` 的分工）。

    ★ 保留期的下限钳位、以及"为什么钳到 1 天"见 `retention_cutoff`。

    ★ 用 ORM 的 `delete(AuditLog)` 而不是裸 SQL 字符串：表名只有一个真源
      （`AuditLog.__tablename__`），改名时这里不会静默失配
      —— 裸 SQL 写错表名的现象是"删了 0 行"，与"没有过期行"长得一样。
    """
    cutoff = retention_cutoff(retention_days)
    res = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
    return int(res.rowcount or 0)

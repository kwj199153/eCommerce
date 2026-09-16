"""
登录失败计数与账号锁定（P1-b，2026-09-16）

==============================================================================
★ 判定与审计分开（这是本模块最容易做错的地方）
==============================================================================
| 用途 | 载体 | 特点 |
|------|------|------|
| **判定**（锁不锁） | `users.failed_login_count` + `users.locked_until` | 只有当前值，成功即清零 |
| **审计**（谁在撞） | `login_attempts` 表 | append-only，不做判定 |

为什么判定不能只放 Redis：锁定是**安全判定**。Redis 抖一下不能让锁定消失
（那正是"门禁存在 ≠ 在执行"的经典形态）。

为什么审计不能替代判定：审计表是历史流水，"当前失败了几次"要扫全表才能算出来，
而且并发下（5 个请求同时到达）会算错。计数器必须是**单行可原子自增**的。

==============================================================================
★★ 判定顺序：先看锁没锁，再看密码对不对
==============================================================================
若「密码正确就放行」，攻击者只要持续猜，猜对的那一次就直接进 ——
锁定窗口对攻击者零成本。所以必须在**校验密码之前**检查锁定。

⇒ 锁定期内，即使密码完全正确也一律拒绝（429 + 剩余时间）。

==============================================================================
★ 不泄露「邮箱是否存在」
==============================================================================
账号不存在时也照常记录一条审计（`reason=unknown_email`），
对外与"密码错"用**同一句话术**。否则登录接口会变成"邮箱枚举器"：
攻击者拿一批邮箱跑一遍，靠响应差异就能筛出哪些是本站用户，
再对这些账号做定向爆破（省掉 99% 的无效尝试）。
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.identity.auth_models import LoginAttempt
from core.identity.models import User

logger = logging.getLogger(__name__)

# 失败原因码（写进 login_attempts.reason，供排查；**不直接回给客户端**）
REASON_OK = "ok"
REASON_BAD_PASSWORD = "bad_password"
REASON_UNKNOWN_EMAIL = "unknown_email"
REASON_LOCKED = "locked"
REASON_INACTIVE = "inactive"
REASON_UNVERIFIED = "unverified"


def lockout_remaining(user: User, now: Optional[datetime] = None) -> Optional[int]:
    """
    若处于锁定期，返回剩余秒数（>=1）；否则返回 None。

    ★ 用 `locked_until` 与当前时间比较，而不是靠一个"解锁定时任务"：
      定时任务不跑（worker 挂了、容器没起）就会导致**账号永久锁死**，
      而那条路径不会有任何报错。惰性判定（谁登录谁自己看时间）没有这个故障面。
    """
    if user is None or user.locked_until is None:
        return None
    now = now or datetime.utcnow()
    remaining = (user.locked_until - now).total_seconds()
    if remaining <= 0:
        return None
    return max(1, int(remaining))


async def check_lockout(db: AsyncSession, user: User) -> Optional[int]:
    """
    登录前的锁定检查。返回剩余秒数（锁着）或 None（没锁）。

    ★ 顺手处理「锁定期已过」的复位：把 locked_until 清空、计数归零。
      放在这里而不是定时任务里 —— 理由同上（少一条"没人跑就永久锁死"的路径）。
    """
    remaining = lockout_remaining(user)
    if remaining is not None:
        return remaining
    if user.locked_until is not None:
        # 锁定期已过：复位
        user.locked_until = None
        user.failed_login_count = 0
        await db.flush()
    return None


async def record_attempt(
    db: AsyncSession,
    *,
    email: str,
    user: Optional[User],
    success: bool,
    reason: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    记一条审计（append-only）。**不 commit** —— 由调用方与"计数更新"放同一事务，
    避免出现"审计写了但计数没更新"或反过来。
    """
    db.add(
        LoginAttempt(
            id=str(uuid.uuid4()),
            email=(email or "")[:255],
            user_id=user.id if user else None,
            ip=_clip(ip, 64),
            user_agent=_clip(user_agent, 255),
            success=success,
            reason=reason,
        )
    )


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    """截断到列宽（HttpUser-Agent 可以很长，超长会被数据库直接拒绝）"""
    if not value:
        return None
    return value[:limit]


async def register_failure(db: AsyncSession, user: Optional[User]) -> Optional[int]:
    """
    累加失败计数；达到阈值则锁定，返回本次锁定时的 `locked_until`（未锁定返回 None）。

    ★ 达到阈值后**清零计数**并把 `locked_until` 往后推：
      若只置 locked_until 而不清零，解锁后计数仍是满的，
      用户只要再错 1 次就又被锁 —— 表现为"解锁后一碰就锁"，很难解释。
    """
    if user is None:
        # 邮箱不存在：没有可累加的对象，只留审计。
        # （不能按邮箱建影子计数器 —— 那等于给了攻击者一个"随便填邮箱就能
        #   把某个计数打满"的入口，还会让合法的拼错邮箱永远排不上队。）
        return None

    user.failed_login_count = int(user.failed_login_count or 0) + 1
    threshold = max(1, int(config.login_max_failures))
    if user.failed_login_count >= threshold:
        user.locked_until = datetime.utcnow() + timedelta(
            minutes=max(1, int(config.login_lockout_minutes))
        )
        user.failed_login_count = 0
        await db.flush()
        return user.locked_until
    await db.flush()
    return None


async def register_success(db: AsyncSession, user: User) -> None:
    """登录成功：清计数、清锁定、更新最后登录时间"""
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
    await db.flush()


async def purge_old_attempts(db: AsyncSession, retention_days: Optional[int] = None) -> int:
    """
    清理超过保留期的登录审计。

    为什么需要：这是一张**每次登录都写一行**的表，且失败尝试可能被脚本刷。
    不清理会稳定增长（它只在风控排查时才有价值，不需要永久保留）。
    """
    from sqlalchemy import text

    days = int(retention_days or config.login_attempt_retention_days)
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    res = await db.execute(
        text("DELETE FROM login_attempts WHERE created_at < :cutoff"), {"cutoff": cutoff}
    )
    return res.rowcount or 0

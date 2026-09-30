"""身份域两张表的**保留期边界算法**（第 331 轮）。

==============================================================================
★★ 本模块存在的理由：同一个算法此前有**两份实现**
==============================================================================
清理核一共有两个，各自算自己的 `cutoff`：

    · `login_guard.py::purge_old_attempts`   -> `max(1, int(retention_days or ...))`
    · `email_tokens.py::purge_spent_tokens`  -> `max(1, older_than_days)`

两行看着"差不多"，但**有一处实质不同**：左边用 `or`（传 0 会退回配置值），
右边直接用（传 0 会钳成 1）。这类"同一判定两份实现"的形态在本仓已登记过多次，
结论固定：**至少有一份永远测不到**，而漂移方向恰好是「哪一天少钳了一点」。

⇒ 收口成本极低（一个纯函数），收益是**不可逆后果只由一处代码产生**。

==============================================================================
★★ 为什么是「纯函数」，而不是顺手把清理也搬进来
==============================================================================
清理这件事只需要**算出一个时间点**，然后 `DELETE ... WHERE created_at < 那个点`。
整条链里唯一可能造成不可逆后果的就是这个时间点：方向写反 ⇒ 删掉近期证据
（比"一条都不删"危险得多）。把它抽成纯函数之后，门禁可以用**纯算术**钉死它，
不必真的对共享库执行一次全局 DELETE —— 那会把历史行真删掉，
「验证代码的测试」不该有这种副作用（同 `core/audit/retention.py` 的分工）。

删除语句**留在各自的表模块里**（那是该表唯一的删除路径，理由同审计：
`login_guard.py` 是登录审计的写路径、`email_tokens.py` 是 token 的写路径）。

==============================================================================
★★ 「保留期」是配置，不是常量（这是本轮顺手修掉的第二个缺陷）
==============================================================================
`email_tokens` 的保留期此前**写死在函数签名里**（`older_than_days: int = 7`），
而隔壁两张表都是配置。⇒ 现在三个字段各管自己的表：

    · `config.login_attempt_retention_days` = 30（登录审计：每登录一行，留 30 天够）
    · `config.email_token_retention_days`   = 7 （一次性凭据：消费/过期后无用途）
    · `config.audit_retention_days`         = 90（问责证据：与复查周期对齐）

★ 两个 `..._cutoff()` 包装函数**只做一件事**：把"没传就取配置"这一步收进这里。
  这样"默认值真的来自配置"就变成**纯算术断言**（不需要数据库、不需要会话），
  与"默认值退化成硬编码"形成可测的对照 —— 见
  `tests/test_identity_retention_gate.py::test_defaults_come_from_config`。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.config import config

#: 保留期的**下限**（天）。★ 它不是可配项，是防呆下限：
#: 配成 0 / 负数时若不钳住，清理会退化成「每次清空全表」——
#: 一条**不可逆**的数据销毁路径，而「配置写错」不该有这个后果。
#: ★ 钳到 1（而不是钳到 30）是刻意选**错得轻**的那一侧：真要清干净的人会
#:   立刻发现「怎么只删了 1 天前的」（可观测、可回退）；钳到 0 的那一侧
#:   后果是"整表没了"。（与 `core/audit/retention.py` 同一个数字、同一条理由。）
MIN_RETENTION_DAYS = 1


def retention_cutoff(days: int, *, now: Optional[datetime] = None) -> datetime:
    """把「保留 N 天」换算成清理的**时间下界**：`created_at` 早于它的行会被删。

    ★ 唯一的钳位实现（两张表共用）—— 上方 docstring 说明了为什么不能各写一份。

    ★ 语义变更（相对改前）已显式记录：改前 `purge_old_attempts` 的
      `retention_days or 默认值` 会让**显式传 0** 退回配置值（30 天），
      现在 `0` 会被钳成 1 天。两个方向都不可逆，取"与审计同一条规则"以消歧；
      实测全仓**没有任何调用点传 0**（只有测试传 30 / 7）。
    """
    base = now if now is not None else datetime.utcnow()
    return base - timedelta(days=max(MIN_RETENTION_DAYS, int(days)))


def _resolve_days(value: Optional[int], default: int) -> int:
    """`None`（= 调用方没指定）才取配置；显式给的值一律照用（再交给钳位）。"""
    return default if value is None else value


def login_attempt_cutoff(
    retention_days: Optional[int] = None, *, now: Optional[datetime] = None
) -> datetime:
    """`login_attempts` 的清理下界。未指定时取 `config.login_attempt_retention_days`。"""
    return retention_cutoff(
        _resolve_days(retention_days, config.login_attempt_retention_days), now=now
    )


def email_token_cutoff(
    retention_days: Optional[int] = None, *, now: Optional[datetime] = None
) -> datetime:
    """`email_tokens` 的清理下界。未指定时取 `config.email_token_retention_days`。

    ★ 本函数就是「email_tokens 的保留期是配置」这条事实的落地点：
      改前它写死在 `purge_spent_tokens(older_than_days: int = 7)` 里。
    """
    return retention_cutoff(
        _resolve_days(retention_days, config.email_token_retention_days), now=now
    )

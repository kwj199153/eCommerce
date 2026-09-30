"""审计写入的**唯一路径**：`record_audit()`（P0-5）。

==============================================================================
★★ 为什么审计自带会话，而**不**复用请求的事务
==============================================================================
这是本模块最需要论证的一个取舍。直觉写法是把 `AuditLog` 塞进请求的
`AsyncSession`（端点里那个 `db`），然后 `await db.commit()` —— 一行就完事。
但那样会同时丢掉两类最关键的记录：

  (1) **业务失败时，审计也一起被回滚。**
      `store.delete` 因为外键冲突抛 409 → 请求事务 rollback → 「某人尝试删除
      这家店」这条审计**跟着消失**。而"谁试过删"恰恰是安全排查的起点。
      ⇒ 审计的语义是「**发生过的事**」，不是「**成功提交的事**」。
        它必须与业务事务**解耦**，才能记录下业务事务的失败。

  (2) **业务成功但审计想单独失败时，无法表达。**
      反之，若审计写失败需要重试，挂在业务事务里根本没有重试的位置。

⇒ 所以本函数自己开一个短会话（`async_session_factory()`），独立提交。
  调用点**不需要**、也**不应该**把自己的 `db` 传进来。

==============================================================================
★★ 「失败不吞」在这里到底怎么落（与全仓口径的差异，必须说清）
==============================================================================
全仓口径是「失败不得静默」。但审计是一个**旁路**，它有两端：

    · 写失败**不能**让业务操作失败 —— 审计服务抖一下就把全站写操作带崩，
      那是拿「可观测性」换「可用性」，方向错了。所以本函数**不抛异常**。
    · 但写失败**也绝不能静默** —— 否则「审计悄悄停了」这件事本身没人知道，
      而它恰恰是最需要被知道的一种故障（安全能力静默失效）。

⇒ 折中落成三件事同时做：
      ① `logger.error(..., exc_info=True)` —— 日志里留全栈；
      ② `AUDIT_WRITE_ERRORS.inc(action=...)` —— 指标里可见（配告警规则）；
      ③ **返回 `False`** —— 调用方若在意，可以自己判断。
  注意 ①② 都不是"吞"：吞的定义是「失败了但没有任何人/任何地方知道」，
  这里有两处出口，且其中一处（指标）能被 Prometheus 抓成告警。

==============================================================================
★ 为什么 `status` 的非法值**不改写成 success**
==============================================================================
「未知 status ⇒ 归一到 success」是一种**静默洗白**：它会把一次失败的删除
伪装成成功，且事后无法从库里察觉（因为库里存的就是 `success`）。
⇒ 本函数对未知 status **原样落库 + WARNING**。宁可留下一个可疑值让人来看，
   也不要悄悄把它变成一个看起来正确的值。同理由见 `core/audit/models.py`。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import Request

from core.audit.actions import KNOWN_ACTIONS, STATUS_SUCCESS, STATUSES
from core.audit.models import AuditLog
from core.database import async_session_factory
from core.middleware.client_ip import client_ip
from core.observability.context import current_client_ip, current_user_id
from core.observability.metrics import AUDIT_RECORDS, AUDIT_WRITE_ERRORS

logger = logging.getLogger(__name__)


def _text(value: Any, limit: int) -> Optional[str]:
    """转成截断后的字符串；空 / 缺失一律返回 `None`（列可空）。

    ★ 必须截断：`User-Agent` / 来自请求体的 `summary` 都可能超长，
      超长会被数据库**直接拒绝**（不是截断）⇒ 整条审计写失败。
      在这里截断比在数据库报错后重试便宜得多。
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:limit]


async def record_audit(
    *,
    action: str,
    actor: Any = None,
    status: str = STATUS_SUCCESS,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    summary: str = "",
    detail: Optional[dict] = None,
    request: Optional[Request] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> bool:
    """写一条审计。**唯一写入路径**，自带会话、自提交。

    Args:
        action: 动作名。应取 `core/audit/actions.py` 里的常量
            （不在 `KNOWN_ACTIONS` 里只告警、不拒绝，理由见 `actions.py`）。
        actor: 执行者。鸭子类型 —— 只用到 `.id` / `.email`；`None` 表示无身份
            （演示路径 / 匿名），此时 `actor_id` 记为空。
        status: 结果（`STATUS_SUCCESS` / `STATUS_FAILURE`）。未知值原样落库 + 告警。
        target_type / target_id: 被操作对象的类型与 id。
        summary: 一行可独立读懂的摘要（给人看的）。
        detail: 结构化明细。★ **严禁放口令 / token / 完整凭据**。
        request: 传入时会自动补 `ip` 与 `user_agent`（两者若已显式给出则不覆盖）。
        ip / user_agent: 显式覆盖（无 `Request` 的场景，如 Celery 任务）。

    Returns:
        True = 已提交；False = 写失败（已记日志 + 指标，**不抛**）。
    """
    if action not in KNOWN_ACTIONS:
        logger.warning(
            "审计动作 %r 不在已知目录（core/audit/actions.py）—— 仍会落库，"
            "但请补登记：否则读口 /audit/actions 的筛选框里选不到它。",
            action,
        )

    if status not in STATUSES:
        logger.warning(
            "审计 status %r 不在 %s 内 —— 按**原值**落库（绝不静默改成 success，"
            "那会把失败伪装成成功且事后不可察觉）。",
            status,
            STATUSES,
        )

    if request is not None:
        if ip is None:
            ip = client_ip(request)
        if user_agent is None:
            user_agent = request.headers.get("User-Agent")
    if ip is None:
        # ★ 兜底：从请求上下文取来源 IP。写入点是**请求日志中间件**，它在每个
        #   请求上都写（与是否走鉴权无关）⇒ 即便调用点拿不到 `Request`
        #   （没有该参数的端点、Celery 任务），只要在同一 asyncio task 内，
        #   来源就不会丢。无上下文时返回空串 ⇒ 归一成 None（而不是空串）。
        ip = current_client_ip() or None

    # ★ detail 预检：不可序列化时**只丢 detail**，保住核心字段。
    #   为什么不像其他字段那样"写不进去就整体失败"：action / actor / target
    #   才是审计的核心证据，detail 是附加。为了一个附加字段丢掉核心证据，
    #   方向错了。这里降级 + WARNING（可见），核心字段原样入库。
    if detail is not None:
        try:
            json.dumps(detail)
        except (TypeError, ValueError):
            logger.warning(
                "审计 detail 不可 JSON 序列化（action=%s）—— 已丢弃该字段，"
                "核心字段不受影响。请检查调用点是否塞入了非基本类型。",
                action,
            )
            detail = {"_dropped": "detail 不可 JSON 序列化"}

    # ★ actor_id 兜底：调用点没给 actor 时，退回请求上下文里的 user_id。
    #   （演示路径下 current_user 是 None，上下文里也可能是空串 —— 那就如实记空，
    #    绝不拿一个猜测值冒充"是谁做的"。）
    actor_id = _text(getattr(actor, "id", None), 36) or _text(current_user_id(), 36)
    row = AuditLog(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        actor_email=_text(getattr(actor, "email", None), 255),
        action=_text(action, 64) or "",
        status=_text(status, 16) or STATUS_SUCCESS,
        target_type=_text(target_type, 32),
        target_id=_text(target_id, 64),
        summary=_text(summary, 512) or "",
        detail=detail,
        ip=_text(ip, 64),
        user_agent=_text(user_agent, 255),
    )

    try:
        async with async_session_factory() as session:
            session.add(row)
            await session.commit()
    except Exception:  # noqa: BLE001 —— 审计是旁路，任何异常都不得外抛
        AUDIT_WRITE_ERRORS.inc(action=action)
        logger.error(
            "审计写入失败（action=%s, target=%s:%s）—— 业务操作不受影响，"
            "但这条痕迹已丢失，请检查 audit_logs 表与数据库连接。",
            action,
            target_type,
            target_id,
            exc_info=True,
        )
        return False

    AUDIT_RECORDS.inc(action=action, status=row.status)
    return True

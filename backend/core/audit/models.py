"""通用审计日志实体 `AuditLog`（`audit_logs` 表，P0-5）。

==============================================================================
★ 为什么不建到 `users` 的外键（本模型最容易"顺手写错"的一处）
==============================================================================
`actor_id` 看起来就是「用户 id」，很自然会加上
`ForeignKey("users.id", ondelete="SET NULL")` —— 本仓 `login_attempts.user_id`
就是这么写的。但**审计表不能这么写**，理由是一条硬约束：

    审计记录必须**比它所记录的主体活得更久**。

「谁在什么时候删了这家店 / 改了这个成员的角色」这类问题，恰恰是在
**主体已经不存在之后**才最需要回答（账号被注销、店铺被删、成员被移除）。
若挂了外键：
  · `ondelete="CASCADE"` ⇒ 用户一删，他的全部行为痕迹**被静默抹掉**，
    这正好毁灭了审计存在的意义（还给了攻击者一个「删号＝清痕迹」的入口）；
  · `ondelete="SET NULL"` ⇒ 不丢行，但**丢失归属**：审计变成一堆
    「有人干过某事」，而"有人"是谁永远查不到了。

⇒ 所以 `actor_id` / `actor_email` 一律**裸列 + 索引**，不做外键：
  即使 `users` 那一行被物理删除，审计行仍完整保留「当时**是**这个 id / 邮箱
  执行了这次操作」这一**历史事实**。历史事实不需要被当前的外键完整性约束。

代价是「孤儿 actor_id」—— 我们接受它，因为审计表不参与任何 join 判定，
只被「按 actor 查历史」这类查询使用，而这类查询本来就允许主体已不存在。

★ 与 `login_attempts` 的分工（别把两张表混为一谈）
    · `login_attempts`  = **登录专用**审计，字段为登录场景定制
      （`success` + `reason∈{ok,bad_password,...}`），且**每次尝试一条**
      （含失败），服务的是「谁在撞我的账号」。
    · `audit_logs`（本表）= **通用**审计，服务的是「谁对**什么对象**做了什么」，
      覆盖登录成功 + 店铺/成员等业务写操作。字段是动作/目标/结果三段式。
    两者刻意不合并：登录失败率极高（脚本刷），塞进通用表会让后者被噪声淹没。

==============================================================================
★ append-only：本表只有 INSERT，没有 UPDATE / DELETE
==============================================================================
`AuditLog` 的调用方只有 `core/audit/service.py::record_audit()`（唯一写入路径），
它只做 `session.add()`。本模块**不提供**任何 update/delete 辅助函数 ——
一旦有了「改审计」的入口，审计就不再是证据（能被改的记录不能证明任何事）。
保留期清理（第 328 轮已落地）走**独立的、显式的**清理核
（`core/audit/retention.py::purge_expired`）+ 定时任务
（`core/audit/tasks.py`），而不是本模块 / `service.py` 里的方法。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from core.audit.actions import STATUS_SUCCESS
from core.database import Base


class AuditLog(Base):
    """通用审计日志行（append-only，见文件头说明）。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        # 主查询形态一：按时间倒序翻页（读口默认排序）。
        Index("ix_audit_logs_created_at", "created_at"),
        # 主查询形态二：「某个人最近干了什么」—— 安全排查第一问。
        # ★ 刻意**不**再给 `actor_id` 单列加索引：本复合索引的**最左前缀**已经
        #   能服务「WHERE actor_id = ?」，单列索引纯属冗余（只增加写放大与空间，
        #   不提升任何查询）。同理见下一条。
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        # 主查询形态三：「这个动作最近发生过吗」（如 store.delete）。
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID

    # ---- 主体（**不挂外键**，理由见文件头）----
    #: 执行者的用户 id。演示身份 / 匿名路径下可能为 None。
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    #: 执行者邮箱快照。★ 冗余存一份而不是 join `users` 取：
    #:   用户改邮箱或注销后，「当时是谁」仍要答得出来（join 会跟着变）。
    actor_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ---- 动作与结果 ----
    #: 动作名（真源 `core/audit/actions.py`）。
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 结果（success / failure）。
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_SUCCESS
    )

    # ---- 目标 ----
    #: 目标类型（store / member / user / ...）。
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: 目标 id。★ 刻意与 `target_type` 分列、且**不命名为 `shop_id`**：
    #:   本表是通用审计，目标是店铺、成员还是会话都可能；
    #:   而且若叫 `shop_id`，本仓 `test_schema_parity.py` 会强制要求
    #:   「带 shop_id 列的表必须有指向 stores_store 的外键」——
    #:   那与本节开头「审计要活得更久、不做外键」的立场直接冲突。
    #:   用 `target_id` 既表达通用性，也不触发那条（正确的）外键不变量。
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ---- 描述 ----
    #: 一行摘要（**给人和日志看**，如「断开店铺 shop_c3529ab1」）。
    #: ★ 摘要必须能脱离任何上下文独立读懂：审计是要拿去给别人看的。
    summary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    #: 结构化明细（JSON）。不按字段查询 ⇒ 用 JSON 而不是拆列
    #: （同 `modules/memory/db_model.py::detail` 的取舍）。
    #: ★ 严禁写入口令 / token / 完整凭据 —— 审计是**最不该**成为泄露面的一张表。
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # ---- 来源 ----
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<AuditLog(action={self.action!r}, status={self.status!r}, "
            f"target={self.target_type}:{self.target_id}, actor={self.actor_id})>"
        )

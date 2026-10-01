"""提示词覆写层的 ORM（第 351 轮 · P0-7 B 档）

==============================================================================
★ 这张表解决什么
==============================================================================
A 档（第 283 轮）给提示词加了 `version` + `fingerprint`，但正文仍只住在
`.py` 常量里 —— **改一个词就要改代码 + 重新发布**。本表把「当前生效的正文」
从源码解耦：运维可以不动代码就换上一版正文，且每一次都留痕。

==============================================================================
★ 为什么必须有 `base_fingerprint` 这一列（与 `fingerprint` 不是一回事）
==============================================================================
    两者管的是**不同的文本**：
      · `fingerprint`      = 本行**覆写正文**的指纹（= sha256(content)[:12]）；
      · `base_fingerprint` = 写这条覆写时**源码那一版正文**的指纹。

    应用时拿 `base_fingerprint` 与**当前源码**的指纹比对：
      · 相等 ⇒ 源码没动过，覆写可以盖上去；
      · 不等 ⇒ 这条覆写建立在**已不存在的文本**上，直接盖上会把别人刚改好的
        正文**静默回滚**（改动仍在源码里，翻 git 看不出问题）。

    ⇒ 只存一个 `fingerprint` 是**测不出这件事**的：它只能回答「覆写本身变了没」，
      回答不了「覆写还配不配得上当前源码」。这两问的答案在两张文本上。

==============================================================================
★ 作用域：**全局**（本轮刻意不做按租户覆写）
==============================================================================
    提示词注册表 `ai_infra.llm.PROMPT_TEMPLATES` 是**进程级单例**，
    而按租户覆写需要在每次渲染时按请求上下文选一个版本 —— 那要求渲染链路
    携带租户标识，是一次独立的架构动作（会牵动 12 个调用点）。
    ⇒ 本轮只做全局覆写；按租户覆写照实记在交付说明的「未验证项 / 后续」里，
      **不假装它已经支持**。

==============================================================================
★ 与其它表的差异：**没有 `store_id` / `account_id`**
==============================================================================
    这不是漏了归属字段：提示词覆写是**平台级**配置，不属于任何租户
    （见上一节）。它的访问控制挂在「平台超管」上（`core.auth.accounts.is_platform_admin`），
    而不是挂在这一行的归属上。
    ★ 判据：本仓要求「有归属的资源必须按归属过滤」；本表**没有归属**，
      所以那条判据不适用 —— 但因此它的读口必须**更严**（超管），
      否则就是「无归属 + 人人可读」的越权形态。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PromptVersion(Base):
    """一条提示词覆写。

    ★ 列的可空性**必须**与 ORM 注解逐列一致 —— 本仓已经吃过一次亏：
      `e8c2f5a7b3d9`（skills 建表）把一批列写成 `nullable=True` 而 ORM 侧是
      非 Optional，于是「迁移建出的库」比「`create_all` 建出的库」宽松，
      `alembic check` 在全新库上报 12 条 `modify_nullable`
      （详见 `k7e2c4f1b849` 的文件头）。
      这里的对应关系是刚性的：`Mapped[X]` ⇒ NOT NULL，`Mapped[Optional[X]]` ⇒ NULL。
    """

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: 模板键。与 `ai_infra.llm.PROMPT_TEMPLATES` 的 key 一一对应。
    #: ★ unique：一个模板同一时刻只能有一条生效的覆写 —— 允许两行会让
    #:   「生效的是哪一条」取决于查询顺序，那是不可复现的配置。
    #: ★ `index=True` 一并给：`unique=True` 单独用会落成**无名**的
    #:   `UNIQUE` 约束 —— PG 给它起的名字（`prompt_versions_name_key`）
    #:   与迁移脚本里手写的名字对不上，`alembic check` 会报一条既存偏差。
    #:   带 `index=True` 时 SQLAlchemy 生成的是**具名唯一索引**
    #:   `ix_prompt_versions_name`，两条建表路径（`create_all` / 迁移）产出同名
    #:   —— 与 `modules/skills/db_model.py::SkillRecord.name` 同一处理。
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )

    #: 覆写正文
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: 覆写后的语义版本（人写）
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")

    #: 覆写正文的指纹（sha256(content)[:12]）—— 写入时由服务端计算
    fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)

    #: **写这条覆写时**源码那一版的指纹 —— stale 判定的基准（见文件头）
    base_fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)

    #: 是否参与应用。关掉它 = 保留记录但让源码版生效（用于「先停用再观察」）
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: 为什么改（给人看的，例如「线上反馈语气太硬」）
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: 操作者（user_id）。可空：允许由初始化脚本灌入
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_prompt_versions_enabled", "enabled"),
    )


__all__ = ["PromptVersion"]

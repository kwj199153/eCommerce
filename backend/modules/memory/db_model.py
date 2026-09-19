"""长期记忆的 ORM 模型（第 149 轮 批 C2）。

★ 本模块是 r141 §2.4 里**第四处**存储。前三处与它的分工：

    conversations / conversation_messages   面向用户的**可读消息**
    LangGraph checkpointer                  图状态、工具调用链、待审批中断态
    agent_session_state                     Agent 自己的**内部槽位**（指代 / 多轮补齐）
    **本模块（memory_* 三张表）**             **跨会话长期有效的用户画像与偏好**

前三处都是"会话内"的：换个 sessionId 就查不到。本模块是唯一"跨会话"的 ——
它的键是 `owner_id`（人），不是 `thread_id`（会话）。

==============================================================================
★★ 为什么是三张表而不是一张
==============================================================================
三个东西的**生命周期完全不同**，合成一行会互相牵制：

  · `memory_profiles` —— 一个 owner **一行**的**开关 + 蒸馏游标**。
    它必须能独立存在：用户刚打开开关、还没有任何条目时，这一行就已经要有。
    若把它并进条目表，"没有条目"就等于"没有开关"，而"没有开关"的默认值
    是开还是关？—— 这个问题一旦要靠"表里有没有行"来回答，就必然在
    两个地方各推一次，然后不一致。

  · `memory_entries` —— **内容真源**。上限、去重、配额、权重全在这里生效。

  · `memory_logs` —— **学习时间线**。它是**只增不改**的流水，
    而条目是**可被整理覆盖**的状态。两者放一张表里，整理一次就要
    在"既当状态又当历史"的行上做增删改 —— 历史会被整理动作本身污染，
    而时间线恰恰是用来**审查整理动作**的。

==============================================================================
★ 本模块三张表**都没有 `shop_id` 列**
==============================================================================
因此不落入 `test_schema_parity.py` 那条「凡有 `shop_id` 的表必须有指向
`stores_store` 的外键」的不变量 —— 这是**有意的**，不是漏了：
长期记忆按**人**分片，店铺维度不参与它的判据。
同一条取舍见 `conversation/db_model.py::AgentSessionStateRecord`。

★ 也正因为没有外键，本模块**不 import 任何别的 db_model**
（不触发 `test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`）。

==============================================================================
★★ 为什么一个 `index=True` 都没写
==============================================================================
三张表的查询模式**全部**是"先按 `owner_id` 过滤，再按某列排序/定位"：

    memory_entries : WHERE owner_id = ? AND section = ?      （渲染 / 分节统计）
                     WHERE owner_id = ? AND dedup_key = ?    （保存时查重）
    memory_logs    : WHERE owner_id = ? ORDER BY created_at DESC LIMIT n

因此**只需要**两个以 `owner_id` 打头的复合索引：

    ix_memory_entries_owner_section (owner_id, section)
    ix_memory_logs_owner_created    (owner_id, created_at)

★ 再加单列 `index=True` 是**纯写放大、零读收益**：
  单列 `(owner_id)` 索引是上面两个复合索引的**左前缀**，PG 照样能用；
  `memory_entries` 上连 `uq_memory_entries_owner_dedup` 唯一约束建的隐式索引
  也是以 `owner_id` 打头的。多出来的每一个索引都要在每次写入时维护 ——
  而这三张表里 `memory_entries` 是**整批覆盖**写入的（每保存一次全删全插），
  索引越多，这个动作越贵。

（这一条不是洁癖：`index=True` 与显式 `Index(...)` **都会**产生真实索引，
 漏建的话 `alembic autogenerate` 会把它们当成 drift 反复生成。）
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_infra.memory.limits import SOURCE_MANUAL
from core.database import Base


class MemoryProfileRecord(Base):
    """长期记忆的**账户级档案**（一个 `owner_id` 一行）。

    装什么：
      · `enabled` —— 「生成对话记忆」总开关。前端那个 `a-switch` 的真源。
        关掉之后：每晚任务跳过这个人、读口注入空块。
      · `last_distilled_at` —— 「最近一次**发起**整理的时间」。

    ★★ `owner_id` 直接做主键（而不是 `id` + 唯一约束）
    --------------------------------------------------
    这一行天然就是"一个人一行"，用代理主键只会**允许**出现两行 ——
    而"同一个人有两份档案"没有任何东西能发现：读的时候取哪一行？
    取最新的话，旧的 `enabled=false` 就永远不生效（用户关了开关却
    发现记忆还在长）。把不变量交给主键，是唯一不依赖人去守的写法。

    ★ 为什么时间用 naive UTC（`datetime.utcnow`）
    ---------------------------------------------
    与同仓 `conversations` / `agent_session_state` 一致。跨时区的判据
    （"今晚跑过了吗"）**不按日期比**，而是按 **时长**（冷却窗口）——
    见 `modules/memory/tasks.py`。按日期比就必然要选一个时区，
    而"选哪个时区"这个决定会散落在任务、服务、前端三处。
    """

    __tablename__ = "memory_profiles"

    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: 最近一次**发起**整理的时间（成功/失败都写）。
    #: ★ 用途是**幂等闸门**：`task_acks_late=True` 下 worker 崩溃会重投递，
    #:   没有它就会重复调用 LLM（重复花钱）。失败也写 ⇒ 次日仍会重试。
    last_distilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MemoryEntryRecord(Base):
    """长期记忆的**条目**（唯一内容真源）。

    ★★ 为什么存"条目"而不是"一整块 markdown 文本"
    ------------------------------------------------
    前端体验确实是一整块可编辑文本，但存储不能跟着它走：

      · **去重必须有一个稳定的键**。整块文本没有条目边界，去重只能靠
        文本 diff —— 那是"每次保存都重算全部差异"，且两次保存之间
        用户只改了一个错字，diff 也会把整块判成变了。
      · **上限必须有可裁剪的单位**。"整份不超过 N 字"这个约束在
        超限时无法执行：没有任何依据决定该删哪一段。
      · **重要性必须能逐条标注**。`source` 决定"满了先挤掉谁"
        （见 `ai_infra/memory/limits.SOURCE_WEIGHTS`），整块文本装不下它。

    ⇒ markdown 只是 **I/O 形态**，进出的转换全在
      `ai_infra/memory/entry.py::parse_markdown / render_markdown` 一处完成。

    ★★ `dedup_key` 由**应用层**算出后写入，不是 DB 生成列
    ----------------------------------------------------
    值与 `ai_infra/memory/entry.py::dedup_key(content)` 逐字节相同。

    为什么不交给数据库生成：`dedup_key` 的算法是
    「NFKC 归一 → casefold → 去掉所有空白与标点 → sha1 前 16 位」。
    DB 端想算必须先有 `pgcrypto`（扩展依赖，且 sha1 与 Python 的
    `hashlib.sha1` 在编码细节上要额外对齐）；而一旦在 SQL 里重写一遍，
    同一件事就有了**两份实现**，且两份的差异没有任何测试能同时看到
    （应用层测试跑 Python 版本，迁移测试跑 SQL 版本）。
    ⇒ 宁可多一个"必须先算再写"的义务，也不要第二份判据。

    ★ 它与 `owner_id` 组成唯一约束 ⇒ 同一个人在库里不可能存两条等价条目。
      ★ 唯一约束**只按 owner 隔离**：两个人写下一模一样的一句话是完全正常的，
        跨人唯一会把第二个人的保存变成静默失败。
    """

    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "dedup_key", name="uq_memory_entries_owner_dedup"
        ),
        Index("ix_memory_entries_owner_section", "owner_id", "section"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # mem_xxx
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: 该条目在本 owner 记忆里的**位置**（0 起，连续）。
    #:
    #: ★★ 为什么位置要落库：**顺序是用户内容的一部分**。
    #:   `render_markdown()` 只重排**分节**（`ordered_sections`：具名分节按规范
    #:   顺序、自定义标题按首次出现顺序），**组内顺序原样保留** ——
    #:   也就是说组内顺序的唯一来源是"读出来时列表的顺序"。
    #:   若那个顺序由 `created_at, id` 推出来，保存一次之后所有新行的
    #:   `created_at` 几乎相同、`id` 是随机 hex ⇒ 组内顺序**变成随机的**。
    #:   用户把「关注重点」的 1/2/3/4 排好、保存、再看一眼：顺序变了，
    #:   而且下次保存还会再打乱一次。这不是"少个 feature"，
    #:   是**系统在乱动用户的内容**。
    #:
    #: ★ 为什么不给它建索引：`memory_entries` 的条数被 `MAX_ENTRIES`（60）封顶，
    #:   且所有查询都已按 `owner_id` 过滤过。在 ≤60 行上排序的代价可以忽略；
    #:   多一个索引反而让"整批覆盖写入"（每保存一次全删全插）更贵。
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 规范分节名（见 `ai_infra.memory.limits.ALL_SECTIONS`）。
    #: ★ 是**中文用户可见文案**，会渲染成 markdown 的 `# 标题`。
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: `entry.dedup_key(content)` 的结果（32 位 hex 的前 16 位）。
    #: 与 `owner_id` 组成唯一约束。
    dedup_key: Mapped[str] = mapped_column(String(32), nullable=False)
    #: manual / import / distill —— 决定重要性权重（见 limits.SOURCE_WEIGHTS）。
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SOURCE_MANUAL
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MemoryLogRecord(Base):
    """**学习时间线**（每次整理 / 手改 / 导入 / 重置 一条）。

    为什么是独立一张表、且**只增不改**：
      · 它是用来**审查整理动作**的 —— 如果整理动作会改写历史记录，
        那它就无法审查自己（用户看到"昨晚新增 3 条"，而那 3 条是什么
        已经被下一次整理改掉了）。
      · 条目是状态（可被覆盖），日志是流水（不可变）。两种东西的生命周期
        不同，塞一张表里必然要引入"这条是不是历史"的标记位。

    `kind` 取值见 `ai_infra.memory.limits.LOG_KINDS`，落库前必须过
    `limits.is_known_log_kind()` —— 其中 `distill_failed` 是关键的一个：
    抽取失败必须**留痕**，否则界面上的"暂无学习记录"会同时表示
    "没跑"、"跑了没事"、"跑失败了"三件事，而用户无法区分。
    （这正是 r141 认定「假页面」的那条判据。）
    """

    __tablename__ = "memory_logs"
    __table_args__ = (
        Index("ix_memory_logs_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # mlog_xxx
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: distill / distill_failed / manual / import / reset
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: 人话摘要（时间线正文）。上限见 `limits.MAX_LOG_CHARS`。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: 结构化明细（`distill.diff_summary()` 的结果）。访问模式是整体取回，
    #: 不按字段查询 ⇒ 用 JSON 而不是拆列。
    detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

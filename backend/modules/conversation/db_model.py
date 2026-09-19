"""
会话持久化 ORM 模型（决策层 B：跨会话记忆）

为店秘书（主 Agent）提供跨会话对话记忆。前端刷新 / 换设备后，
凭 sessionId 从 DB 恢复历史消息，让 LLM 感知跨会话上下文。

设计：
- conversation 表：一次连续对话（一个 sessionId）
- conversation_message 表：该会话的消息明细（按序追加）
- 与 LangGraph checkpoint（决策层 C）互补：checkpoint 存图的中间状态
  （工具调用链），本表存面向用户的可读消息历史（渲染 + 注入 LLM）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ConversationRecord(Base):
    """会话表（一个 sessionId = 一次连续对话）"""
    __tablename__ = "conversations"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_conversations_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # session_xxx / uuid
    # 归属：用户 + 店铺（沿用 stores_store 的 owner_id 语义）
    owner_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    shop_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # 当前对话的 Agent（如 secretary / product-research），用于按 Agent 过滤
    agent_id: Mapped[str] = mapped_column(String(32), default="secretary")
    title: Mapped[str] = mapped_column(String(200), default="新对话")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConversationMessageRecord(Base):
    """会话消息表（按序追加，role: user / assistant）"""
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conv_msg_conversation_seq", "conversation_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # msg_xxx / uuid
    conversation_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 会话内序号
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentSessionStateRecord(Base):
    """Agent 会话级状态（一个 (thread_id, state_key) 一行）—— 第 145 轮批 C1。

    装什么：Agent 自己那几个「跨轮次要记住」的槽位。以选品分析师为例 ——
    `last_blue_ocean` 支撑「把第 1 个加进选品库」这类**指代解析**，
    `pending_save` 支撑**多轮槽位补齐**（上一轮追问「还差什么」，这一轮的回答
    直接当槽位填）。

    为什么原来是进程内存、现在必须落库
    ----------------------------------
    原实现是挂在 Agent **单例**上的一个 dict
    （`agent_product_research.py` 旧第 281 行 `self._session_state: dict = {}`）。
    三个后果：
      · 进程数 > 1 时跨进程不可见 —— 同一会话的两次请求若落到不同进程，
        第二次就"忘了"第一次留下的槽位；
      · 重启即丢 —— 消息历史在 PG（由 checkpointer 承担），槽位却只在内存里，
        两处寿命不同，表现为「聊天记录还在，但 AI 忘了我在补什么」；
      · **无上界** —— 键是会话 ID，只增不减，长跑进程持续吃内存。

    为什么是「一 (thread_id, state_key) 一行」而不是「一会话一行 JSON」
    ------------------------------------------------------------------
    落盘是**增量**的：一次请求通常只改动一两个键。整行 JSON 的写法要读-改-写
    整个大对象（`last_blue_ocean` 可以到几百 KB），两次并发请求还会互相覆盖；
    逐键一行则各自 upsert、互不干扰，也天然只写变化的那部分。

    ★ `owner_id` 不可为空，且是**查询条件的一部分**：与 `conversations` 同一条
      原则 —— 归属由服务端注入，读的时候当过滤条件。为空即意味着「谁都读得到」
      或「谁都读不到」，两种都不能接受。
    ★ `thread_id` 用的是 `BaseAgent.resolve_thread_id()` 的**同一份口径**
      （见 `agent_product_research.py::_state_scope`）：状态与 checkpoint 描述的
      必须是"同一个会话"，两处各拼一份键迟早漂移，而漂移的表现是
      「历史还在、槽位没了」—— 两边都不报错。

    与另外两个存储的分工（r141 §2.4 的三个存储）
    -------------------------------------------
      · `conversations` / `conversation_messages` —— 面向用户的**可读消息**；
      · LangGraph checkpointer —— 图状态、工具调用链、待审批中断态；
      · 本表 —— Agent 自己的**内部槽位**（指代 / 多轮补齐）。
    """

    __tablename__ = "agent_session_state"
    __table_args__ = (
        # ★ (thread_id, state_key) 唯一 —— 也是落盘时 upsert 的冲突目标。
        UniqueConstraint(
            "thread_id", "state_key", name="uq_agent_session_state_thread_key"
        ),
        Index("ix_agent_session_state_owner_thread", "owner_id", "thread_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sst_xxx
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    #: 与 checkpointer 同口径的会话键（`ns:user_id:session_id`）
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 原始 session_id —— 只为排查/清理时能按人话定位，**不参与判定**
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'conversations.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.conversation.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store

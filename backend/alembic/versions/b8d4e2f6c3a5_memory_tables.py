"""memory: 新增 memory_profiles / memory_entries / memory_logs 三张表（第 149 轮批 C2）

Revision ID: b8d4e2f6c3a5
Revises: a7f3c1e9d2b4
Create Date: 2026-09-18 13:40:00.000000

==============================================================================
为什么建这三张表
==============================================================================
r141 §2.4 实测：`frontend/src/views/MemoryEvolution.vue`（「记忆与进化」页）
是**硬编码假页面** —— 记忆正文是 `ref(\`# 工作背景 ...\`)` 里写死的一段文本、
学习时间线是 7 条硬编码记录、`onSaveMemory` 只写本地 `ref`（**零 API 调用**）。
页面上却承诺"每晚自动整理更新"。

⇒ 本迁移是那句话变成事实的第一步：**先把东西存下来**。
   （写口 / 读口 / 定时器在 `modules/memory/` 与 `modules/memory/tasks.py`。）

★ 这是 r141 §2.4 点名的**第四处**存储，也是唯一"跨会话"的一处：

    conversations / conversation_messages   面向用户的**可读消息**
    LangGraph checkpointer                  图状态、工具链路、待审批中断态
    agent_session_state                     Agent 内部槽位（指代 / 多轮补齐）
    **本迁移的三张表**                        **跨会话长期有效的用户画像与偏好**

前三处的键是 `thread_id`（会话），本处的键是 `owner_id`（人）——
换个会话照样要读到，这正是它不能复用前三处的原因。

==============================================================================
表结构取舍
==============================================================================
· **三张表而不是一张**：档案（开关 + 蒸馏游标，必须能独立存在）·
  条目（内容真源，可被整理覆盖的**状态**）· 日志（只增不改的**流水**，
  用来审查整理动作，不能被整理动作自身污染）。详见 `modules/memory/db_model.py`。

· `memory_profiles.owner_id` **直接做主键**：这一行天然是"一个人一行"，
  用代理主键只会允许出现两行 —— 而"同一个人有两份档案"没有任何东西能发现
  （读的时候取哪一行？取最新的话旧的 `enabled=false` 永远不生效）。

· **一个 `index=True` 都没有**，只建两个以 `owner_id` 打头的复合索引：
      ix_memory_entries_owner_section (owner_id, section)
      ix_memory_logs_owner_created    (owner_id, created_at)
  三张表的查询模式全是"先按 owner 过滤"；单列 `(owner_id)` 索引是这两个的
  **左前缀**（`uq_memory_entries_owner_dedup` 的隐式索引也是），纯写放大。
  ★ 漏建这里的索引会让 `alembic autogenerate` 反复把同一批索引当 drift 生成。

· **刻意不加 `shop_id` 列**：长期记忆按**人**分片，店铺维度不参与它的判据。
  ★ 顺带说明，免得后人误以为漏了外键：`test_schema_parity.py` 的不变量是
    「凡有 `shop_id` 列的表，必须有指向 `stores_store` 的外键」；
    这三张表不带该列，因此不落入那条约束（不是因为忘了建外键）。

· 时间字段用 `DateTime`（与同仓 `conversations` / `agent_session_state` 一致）。
  ★ 跨时区判据（"今晚跑过了吗"）**不按日期比**，而按**时长**：按日期比就
    必然要选一个时区，而"选哪个时区"会散落在任务 / 服务 / 前端三处。

· **不写 `server_default`**（与 `agent_session_state` 一致）：`enabled` 的默认值
  由 ORM 的 Python 侧 `default=True` 承担 —— 单一真源在
  `modules/memory/db_model.py`，SQL 里再写一份就是第二份判据。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d4e2f6c3a5'
down_revision: Union[str, Sequence[str], None] = 'a7f3c1e9d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROFILES = 'memory_profiles'
_ENTRIES = 'memory_entries'
_LOGS = 'memory_logs'


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    # ★ 幂等守卫：开发期 `create_all` 与 Alembic **共用同一份 Base.metadata**，
    #   只要应用在 development 下启动过一次（`init_db()` 会 create_all），
    #   这三张新表就已经存在了。此后再 `alembic upgrade head` 会抛
    #   `DuplicateTable` —— 而那恰恰是"本该顺利"的场景。
    #   逐表判定而不是"任一张在就整体 return"：三张表可能因为中断而只建了一半。
    if not _has_table(_PROFILES):
        op.create_table(
            _PROFILES,
            sa.Column('owner_id', sa.String(length=36), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('last_distilled_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('owner_id'),
        )

    if not _has_table(_ENTRIES):
        op.create_table(
            _ENTRIES,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('owner_id', sa.String(length=36), nullable=False),
            sa.Column('section', sa.String(length=32), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('dedup_key', sa.String(length=32), nullable=False),
            sa.Column('source', sa.String(length=16), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'owner_id', 'dedup_key', name='uq_memory_entries_owner_dedup'
            ),
        )
        op.create_index(
            'ix_memory_entries_owner_section',
            _ENTRIES,
            ['owner_id', 'section'],
            unique=False,
        )

    if not _has_table(_LOGS):
        op.create_table(
            _LOGS,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('owner_id', sa.String(length=36), nullable=False),
            sa.Column('kind', sa.String(length=16), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('detail', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_memory_logs_owner_created',
            _LOGS,
            ['owner_id', 'created_at'],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema.

    ★ 反向迁移**连数据一起删**，且**三张表一起**：这三张表是一个概念的三个面
      （开关 / 内容 / 流水）。只删其中一张会留下"有开关没内容"或
      "有流水没内容"的半套状态，而那种状态没有任何读者、也没有任何代码能修
      —— 见 DETAILS「概念删了不能留库不读」。
    ★ 索引随 `drop_table` 一起消失，不需要单独 drop_index。
    ★ 删除顺序：先明细（entries / logs）后档案（profiles），
      与"先建父后建子"的直觉相反 —— 这里三张表**没有外键**，
      顺序对正确性无影响，按上面这个顺序只为了让 diff 读起来像"倒放"。
    """
    for name in (_ENTRIES, _LOGS, _PROFILES):
        if _has_table(name):
            op.drop_table(name)

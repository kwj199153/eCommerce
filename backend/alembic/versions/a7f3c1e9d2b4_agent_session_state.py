"""session state: 新增 agent_session_state 表（第 145 轮批 C1）

Revision ID: a7f3c1e9d2b4
Revises: c8e2f4a6b1d3
Create Date: 2026-09-19 03:00:00.000000

==============================================================================
为什么建这张表
==============================================================================
选品分析师的「会话级状态」此前挂在 Agent **单例**上的一个普通 dict 里
（`agent_product_research.py` 旧第 281 行 `self._session_state: dict = {}`），装着：

  · `last_blue_ocean` —— 上一轮蓝海结果，供「把第 1 个加进选品库」这类
    **指代解析**；
  · `pending_save`    —— 多轮槽位补齐的待补项（上一轮追问"还差什么"，
    这一轮的回答直接当槽位填）。

三个后果（r141 §2.4 实测）：
  1. **进程数 > 1 时跨进程不可见** —— 同一会话的两次请求若落到不同 worker，
     第二次就"忘了"第一次留下的槽位；
  2. **重启即丢** —— 消息历史在 PG（由 checkpointer 承担），槽位却只在内存里，
     两处寿命不同，表现为「聊天记录还在，但 AI 忘了我在补什么」；
  3. **无上界** —— 键是会话 ID，只增不减。

⇒ 搬到 PG，并且**键与 checkpointer 同口径**（`thread_id` = `ns:user_id:session_id`）。
  若状态用自己的键（例如裸 session_id）、checkpoint 用 thread_id，两者就会各自
  描述"同一个会话"却键不同 —— 那是**两份 ID 空间**，第 138 轮的 `X-Shop-ID`
  事故正是同一形态。

==============================================================================
表结构取舍
==============================================================================
· **一 (thread_id, state_key) 一行**，不是"一会话一行 JSON"：落盘是增量的，
  整行 JSON 要读-改-写整个大对象（`last_blue_ocean` 可以到几百 KB），
  并发两次请求还会互相覆盖；逐键一行则各自 upsert、互不干扰。

· `owner_id` **NOT NULL**，与 `conversations.owner_id` 同一条原则 ——
  归属由服务端注入，读的时候当**查询条件**（见 `state_store.load_states`）。

· **刻意不加 `shop_id` 列**：本表按会话（thread）分片，店铺维度不参与它的判据。
  ★ 顺带说明，免得后人误以为漏了：`test_schema_parity.py` 的不变量是
    「凡有 `shop_id` 列的表，必须有指向 `stores_store` 的外键」；
    本表不带该列，因此不落入那条约束（不是因为忘了建外键）。

· `payload` 用 `JSON`：访问模式是整体取回（下一轮回读给模型 / 供指代匹配），
  不按字段查询。写入前统一走 `state_store._json_safe()` 收敛。

· 时间字段用 `DateTime`（与同包的 `conversations` 一致；cs_tickets / monitors
  那两张表用 String 存 ISO 串，是另一批次的取舍，不强行统一）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3c1e9d2b4'
down_revision: Union[str, Sequence[str], None] = 'c8e2f4a6b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'agent_session_state'


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema."""
    # ★ 幂等守卫：开发期 `create_all` 与 Alembic **共用同一份 Base.metadata**，
    #   只要应用在 development 下启动过一次（`init_db()` 会 create_all），
    #   这张新表就已经存在了。此后再 `alembic upgrade head` 会抛
    #   `DuplicateTable` —— 而那恰恰是"本该顺利"的场景（目标就是让库与 ORM
    #   一致）。同一坑见 DETAILS「迁移必须幂等」。
    if _has_table(_TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('owner_id', sa.String(length=36), nullable=False),
        sa.Column('thread_id', sa.String(length=255), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('state_key', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'thread_id', 'state_key', name='uq_agent_session_state_thread_key'
        ),
    )
    op.create_index(
        'ix_agent_session_state_owner_thread',
        _TABLE,
        ['owner_id', 'thread_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema.

    ★ 反向迁移**连数据一起删**：本表存的是会话内的槽位（"上一轮挖到哪几个品"
      这种），没有跨会话的独立价值，留着也没有读者。概念删了就不该留一张
      没人读的表 —— 见 DETAILS「概念删了不能留库不读」。
    ★ 索引随 `drop_table` 一起消失，不需要单独 drop_index。
    """
    if _has_table(_TABLE):
        op.drop_table(_TABLE)

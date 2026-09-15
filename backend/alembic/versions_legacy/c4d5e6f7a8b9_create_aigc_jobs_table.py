"""create aigc_jobs table (AIGC 长任务异步化)

P1-5 异步任务（2026-09-15）配套的表结构变更。

背景（实测/代码常量推算）：
  AIGC 出图原本整段同步阻塞在 HTTP 请求里。`POST /aigc/asset/generate` 的最坏耗时：
      单张 15-25s，`image_client.MAX_CONCURRENCY = 2`（3 并发会被服务端 429），
      单次最多 `asset_gen.MAX_TOTAL = 8` 张，`wait_for_images` 单张超时 180s
      ⇒ 8 / 2 × 180s = **720s**
  而前端 axios 超时是 **300s**（`aigcMedia.ts` 为这条接口单独放宽过）
      ⇒ 720 > 300：极端情况下用户看到「请求超时」，后端却仍在出图，
        DashScope 已按张计费（≈¥0.14/张）—— **钱花了，结果丢了**。

  改造后任务状态落本表，**不依赖 Celery result backend**
  （后者 `result_expires = 3600`，1 小时就查不到，而 /static 图是长期链接）。

★ 为什么这张表必须自己带 `user_id`：
  按 P0-1（BOLA/IDOR）的教训，「按 ID 取单条」的端点若不额外做归属过滤，
  拿到 job_id 的人就能读到别人店铺的素材链接。归属维度在提交时就写死，
  查询时按它过滤（见 modules/aigc_media/job_service.py 的 `_owner_filter`）。

★★ 两个「静默出错」的坑，本文件都做了处理（反向注入验证时实测暴露）：

  坑 1：**不能用「表已存在就整体 return」做幂等。**
      第一版写成 `if _table_exists(TABLE): return`。后果：若表已被别的路径建出来
      （开发环境 `init_db()` 的 `create_all`、或上一次迁移中途失败），
      本次升级会**整体跳过**，于是 `uq_aigc_jobs_inflight` 这个唯一索引永远不存在
      —— 而去重（并发双击不重复出图 = 不重复计费）完全依赖它，
      并且**不会有任何报错**。
      ⇒ 改为「表与每个索引分别探测、分别创建」。

  坑 2：**建唯一索引前必须先清理重复的 inflight 行。**
      实测：库里若已存在 (user_id, dedupe_key) 相同的多条 pending/running 行，
      `CREATE UNIQUE INDEX` 直接报
        could not create unique index "uq_aigc_jobs_inflight"
      升级中断，且留下「表在、索引不在」的半成品状态（正是坑 1 的触发条件）。
      ⇒ 建索引前先把重复的进行中任务标记为 failed（保留最早一条），
        并保证 (user_id, dedupe_key) 非空（NULL 在唯一索引里互不冲突，
        会让去重静默失效，所以先把 NULL 归零成空串）。

★ 关于 `uq_aigc_jobs_inflight` 这个**部分唯一索引**：
  它只对 status IN ('pending','running') 的行生效，作用是「同一用户 + 同一入参
  只允许有一条进行中的任务」。只覆盖 inflight 是刻意的：若覆盖全部状态，
  用户第二次生成同样的素材会被历史记录永久挡住。

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-15 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'aigc_jobs'
INFLIGHT_UNIQUE_INDEX = 'uq_aigc_jobs_inflight'

#: 单列 / 复合索引（除了唯一那个之外）
PLAIN_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ('ix_aigc_jobs_kind', ['kind']),
    ('ix_aigc_jobs_status', ['status']),
    ('ix_aigc_jobs_user_id', ['user_id']),
    ('ix_aigc_jobs_shop_id', ['shop_id']),
    ('ix_aigc_jobs_dedupe_key', ['dedupe_key']),
    ('ix_aigc_jobs_user_created', ['user_id', 'created_at']),
)


def _table_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in insp.get_table_names()


def _index_exists(table: str, index: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(i["name"] == index for i in insp.get_indexes(table))


def _cleanse_before_unique_index() -> None:
    """建唯一索引前的清场。两步都要做，缺一个都会出问题：

    1. **NULL 归零**：唯一索引里 NULL 与任何值都不相等（连 NULL 与 NULL 都不冲突），
       所以 (NULL, 'k') 可以插任意多条 —— 去重会静默失效。
       本表由业务代码写入时不会产生 NULL（默认空串），但历史行/手工插入可能有。
    2. **重复 inflight 行降级**：同一 (user_id, dedupe_key) 只保留 created_at 最早
       的一条，其余标记为 failed 并写明原因。不清掉的话建索引进直接失败、升级中断。
    """
    op.execute(
        f"""
        UPDATE {TABLE} SET user_id = '' WHERE user_id IS NULL;
        """
    )
    op.execute(
        f"""
        UPDATE {TABLE} SET dedupe_key = '' WHERE dedupe_key IS NULL;
        """
    )
    op.execute(
        f"""
        UPDATE {TABLE}
           SET status = 'failed',
               error = COALESCE(error, '')
                       || '[迁移 c4d5e6f7a8b9] 同参数存在重复的进行中任务，'
                       || '已保留最早一条，本条标记为失败（不影响已产出的素材）',
               finished_at = COALESCE(finished_at, NOW())
         WHERE status IN ('pending', 'running')
           AND id NOT IN (
                SELECT DISTINCT ON (user_id, dedupe_key) id
                  FROM {TABLE}
                 WHERE status IN ('pending', 'running')
                 ORDER BY user_id, dedupe_key, created_at ASC, id ASC
           );
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    # 1) 建表（已存在则跳过 —— 只跳建表，不跳索引，见文件顶部「坑 1」）
    if not _table_exists(TABLE):
        op.create_table(
            TABLE,
            sa.Column('id', sa.String(length=40), primary_key=True),
            sa.Column('kind', sa.String(length=32), nullable=False),
            sa.Column(
                'status', sa.String(length=16), nullable=False, server_default='pending'
            ),
            sa.Column('user_id', sa.String(length=36), nullable=False, server_default=''),
            sa.Column('shop_id', sa.String(length=64), nullable=False, server_default=''),
            sa.Column(
                'request_id', sa.String(length=64), nullable=False, server_default=''
            ),
            sa.Column(
                'dedupe_key', sa.String(length=128), nullable=False, server_default=''
            ),
            sa.Column('payload', sa.JSON(), nullable=True),
            sa.Column('result', sa.JSON(), nullable=True),
            sa.Column('error', sa.Text(), nullable=False, server_default=''),
            sa.Column(
                'celery_task_id', sa.String(length=64), nullable=False, server_default=''
            ),
            sa.Column('assets_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('retries', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
        )

    # 2) 普通索引（逐个探测，避免「表在、索引不在」）
    for name, cols in PLAIN_INDEXES:
        if not _index_exists(TABLE, name):
            op.create_index(name, TABLE, cols)

    # 3) 唯一索引 —— 去重（= 不重复计费）的兜底闸门
    if not _index_exists(TABLE, INFLIGHT_UNIQUE_INDEX):
        _cleanse_before_unique_index()
        op.create_index(
            INFLIGHT_UNIQUE_INDEX,
            TABLE,
            ['user_id', 'dedupe_key'],
            unique=True,
            postgresql_where=sa.text("status IN ('pending', 'running')"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    if not _table_exists(TABLE):
        return
    for name, _cols in PLAIN_INDEXES:
        if _index_exists(TABLE, name):
            op.drop_index(name, table_name=TABLE)
    if _index_exists(TABLE, INFLIGHT_UNIQUE_INDEX):
        op.drop_index(INFLIGHT_UNIQUE_INDEX, table_name=TABLE)
    op.drop_table(TABLE)

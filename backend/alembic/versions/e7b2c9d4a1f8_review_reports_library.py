r"""review library: 新增复盘库表 review_reports（资料库 → 复盘库）

Revision ID: e7b2c9d4a1f8
Revises: d6a1b3c8e4f7
Create Date: 2026-09-25 10:00:00.000000

==============================================================================
为什么建这张表
==============================================================================
老板原话：

    我资料库开一个复盘资料库，当复盘 agent 的结果满意就入库

改前 `review_analyst` 的 6 项能力是**纯计算**（每次按当前数据源现算，
`service.py` 里一行写库都没有）⇒ 结果只活在这一次响应里：
  · 老板看过一眼就没了，想回看只能重跑（而重跑拿到的是**另一批数字**）；
  · 「下一期复盘自动读到上期做对比」在数据层**不可能成立** ——
    没有「上期」可以读。

本表就是那个「上期」的落脚点。写入走**人工确认**（前端「归档到复盘库」按钮），
不在生成时自动落库 —— 自动落库会堆满没人看过的中间结果，
而「哪一份是老板确认过的」这件事会变得不可判定。

==============================================================================
★ 幂等守卫（本仓**必须**，不是可选项）
==============================================================================
`init_db()` 在 development 下对 `Base.metadata` 跑 `create_all`，而它与 Alembic
**共用同一份 Base.metadata** ⇒ 只要带 `--reload` 的应用在开发库上启动过一次
（或任何一次 import 了全部模型的进程跑过 `create_all`），这张新表就已经存在了。
此后 `alembic upgrade head` 的 `CREATE TABLE` 会抛 `DuplicateTable`
—— 而那恰恰是「本该顺利」的场景。

★ 实测（本轮，2026-09-24）：本机的开发库**已经**有 `review_reports`
  （`\d review_reports` 显示列 / 四个 `ix_*` 索引 / `uq_review_reports_scope` /
  `fk_review_reports_shop_id_stores_store` **全部与 ORM 一致**），
  首次 `alembic upgrade head` 就是因此抛了 `DuplicateTable`。
⇒ 若不做存在性探测，这道迁移在**每一个开发库**上都会失败。
  同族先例：`b8d4e2f6c3a5_memory_tables.py`、`a7f3c1e9d2b4_agent_session_state.py`、
  `c4d9e2f1a6b3_users_self_service_profile_and_api_key.py`。

★ 索引**单独探测**、不复用「表已存在」这个结论：`create_all` 从不动已有的表，
  所以「表在」不等于「索引齐」（表可能是更早一次 create_all 只建了一半，
  也可能手工建过）。这也是 c4d9e2f1a6b3 的做法。

==============================================================================
表结构取舍
==============================================================================
· `shop_id` 带 `fk_review_reports_shop_id_stores_store`（ON DELETE RESTRICT）：
  与其余 16 张业务表同口径 —— 删店铺是低频高风险动作，宁可提示先清理，
  不连带删业务数据。
  ★ 这条外键**必须在这里建**：`tests/test_schema_parity.py` 的核心不变量是
    「凡有 shop_id 列的表都必须有指向 stores_store 的外键」，而它从
    information_schema / pg_constraint 读**真实库** ⇒ 迁移漏了就会红
    （症状不是报错，而是「删店铺时不再被拦」）。

· **唯一约束 `uq_review_reports_scope` 建在四维上**：
  `(shop_id, report_type, period_days, period_end)`。
  这是幂等键，也是「上期对比」能成立的前提：
    · 三个维度撑不起「周期」—— days=30 的月报，8 月那份与 9 月那份
      `period_days` 完全相同；键若只到 `period_days`，第二个月归档会
      **覆盖掉**第一个月，库里永远只剩一行。
    · 补 `period_end`（覆盖周期的最后一天）后：当天重复归档 ⇒ 命中同一行 ⇒
      UPDATE（幂等）；隔一期归档 ⇒ 新增一行 ⇒ 可对比。
  `period_end` 由服务端按归档当天写入（它是键的一部分，客户端可控就等于
  客户端能决定「覆盖哪一条」）。

· `data` 用 JSON 整体存取：
  六种报告（weekly_report / monthly_review / ad_review / product_performance /
  inventory_health / profit_audit）的 details 形状**互不相同**
  （campaigns / sku_rank / products / items / sales+ad…），拆列会得到一张
  大半字段恒 NULL 的宽表；而访问模式是「取整份报告」。与 cs_tickets 的
  attachments / monitors 的 7 维时序同取舍。

· `summary` 单列存：列表与 Agent 工具出参都**不回** `data`（一份报告可挂
  35 行 SKU 明细、十几 KB），但不回 data 又必须能显示一句话结论 ⇒
  在**写入期**从同一份快照派生出来存一份（不是第二份真源，也不独立编辑）。

· 时间字段用 String(64) 存 ISO 串（与 cs_tickets / monitors / platform_rules
  一致），避免引入 naive/aware 时区议题 —— 本表只做「原样吐给前端」。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b2c9d4a1f8'
down_revision: Union[str, Sequence[str], None] = 'd6a1b3c8e4f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'review_reports'
_INDEXED_COLUMNS = ('shop_id', 'report_type', 'period_days', 'period_end')


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(name: str, table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not _has_table(table):
        return False
    return any(ix.get('name') == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    """Upgrade schema."""
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(length=128), nullable=False),
            sa.Column('shop_id', sa.String(length=64), nullable=False),
            sa.Column('report_type', sa.String(length=32), nullable=False),
            sa.Column('period_days', sa.Integer(), nullable=False),
            sa.Column('period_end', sa.String(length=32), nullable=False),
            sa.Column('summary', sa.Text(), nullable=False),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.String(length=64), nullable=False),
            sa.Column('updated_at', sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ['shop_id'], ['stores_store.id'],
                name='fk_review_reports_shop_id_stores_store', ondelete='RESTRICT',
            ),
            # ★ 幂等键：同一个「店铺 + 报告类型 + 周期长度 + 周期末日」只允许一行。
            #   与 `modules/review_analyst/db_model.py` 的 __table_args__ 逐字对应
            #   （`alembic check` 会比对；名字也必须一致）。
            sa.UniqueConstraint(
                'shop_id', 'report_type', 'period_days', 'period_end',
                name='uq_review_reports_scope',
            ),
            sa.PrimaryKeyConstraint('id'),
        )
    else:
        print(
            f"[{revision}] {_TABLE} 已存在（开发期 create_all 抢先建表），跳过 create_table"
        )

    # ★ 索引独立探测（见模块 docstring）：表存在 ≠ 索引齐全。
    #   名字逐字与 ORM 的 `index=True` 自动命名一致 —— `alembic check` 比对的是
    #   **实际名字**，差一个字就会被当成 drift 反复生成。
    for col in _INDEXED_COLUMNS:
        name = f'ix_{_TABLE}_{col}'
        if not _has_index(name, _TABLE):
            op.create_index(op.f(name), _TABLE, [col], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    ★ 直接 drop_table：表是本次新加的，里面只可能有本批次之后归档的报告。
      不写「先把报告导出再删」—— 那是运维动作，不该藏在迁移里。
    ★ 索引**显式** drop 而不是依赖 `drop_table` 连带删除：
      与 upgrade 的逐个探测对称 —— 手工建过索引的开发库也能干净回退。
      （`memory_tables` 那种「索引随表消失」的写法在单表场景也成立，
        但这里索引名是本迁移自己声明的，显式回收更可读。）
    """
    for col in _INDEXED_COLUMNS:
        name = f'ix_{_TABLE}_{col}'
        if _has_index(name, _TABLE):
            op.drop_index(op.f(name), table_name=_TABLE)
    if _has_table(_TABLE):
        op.drop_table(_TABLE)

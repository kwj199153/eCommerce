"""为 16 张业务表的 shop_id 建立指向 stores_store 的外键

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-15

======================================================================
为什么需要这个迁移
======================================================================
项目体检发现：全库 15 条外键里，**没有一条**是「业务表 → stores_store」。
而 16 张业务表都有 shop_id 列，也都有 ix_*_shop_id 索引。

后果：删掉一家店铺（stores_store 里的一行）之后，那家店名下的
spus / assets / candidates / monitors / knowledge_* / platform_rules ...
全部变成**孤儿行** —— shop_id 指向一个不存在的店：
  - 任何按 shop_id 过滤的查询都查不到它们（用户看不见，但行还占着库）
  - 若某个 store id 将来被复用，旧数据会串到新店上（跨租户串数据）
数据库层完全没有阻止这件事发生。

======================================================================
★ ON DELETE 语义：用 RESTRICT，不用 CASCADE（有意写清，请勿默默改）
======================================================================
目标只是「不再产生孤儿」。RESTRICT 直接达成这个目标：
      店铺下还有业务数据时，删除被数据库拒绝 —— 删不掉，就不可能产生孤儿。

CASCADE 也能「不产生孤儿」，但它是靠**静默连带删除**达成的：
      一次删店会连带删掉该店全部选品/素材/监控/知识库。
      删店是低频高风险操作，"一次误点删掉一家店的全部数据" 的代价，
      远高于 "删店时被提示先清理数据"。
所以这里选择让删店在数据非空时**失败并给出可操作提示**
（配套改动：stores/router.py 把 IntegrityError 转成 409 + 文案），
而不是替用户决定「连带删光」。

如果将来产品上确实要「删店即删全部数据」，应当：
  1) 明确这是产品决策，改这里的 ondelete 为 CASCADE；
  2) 同时补一个二次确认 + 数据导出，再上线。

======================================================================
★ 为什么不自动清理脏数据
======================================================================
迁移若发现无法归属的 shop_id（空串 / 指向不存在的店），
**故意抛错而不是自动删除或改写** —— "删哪些数据" 是业务决策，应由人来做。
迁移只负责把问题**显式暴露**出来，并附上可直接执行的排查 SQL。

（本机当时有 1 行 candidates.shop_id='' 的测试残留，已备份到
 .workbuddy/backup/db-dirty-20260915/candidates_shop_id_empty.json
 后人工处理，然后本迁移才通过。）

======================================================================
★ 幂等性：逐表探测，不使用「存在就整体 return」
======================================================================
「表已存在就 return」是本节目的已知坑（会造成索引永远建不上且零报错）。
这里对**每一张表、每一个约束**分别探测，重复执行安全。
"""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


# 有 shop_id 列、需要建立外键指向 stores_store 的业务表。
# 顺序无关紧要（不涉及互相依赖），但保持字母序便于比对。
SHOP_SCOPED_TABLES = [
    "aigc_jobs",
    "asset_groups",
    "assets",
    "candidate_groups",
    "candidates",
    "conversations",
    "knowledge_bases",
    "knowledge_docs",
    "knowledge_faqs",
    "monitor_groups",
    "monitors",
    "platform_rule_docs",
    "platform_rules",
    "product_groups",
    "shop_voice",
    "spus",
]


def _fk_name(table: str) -> str:
    # 命名规则与项目其他外键保持一致的可读性（pg 默认名太随机，不便排查）
    return f"fk_{table}_shop_id_stores_store"


def _count(conn, table: str, where: str) -> int:
    return conn.execute(
        sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE {where}')
    ).scalar() or 0


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------------
    # 1) 防御性检查：脏数据必须先由人工处理，迁移不替人做决定
    # ---------------------------------------------------------------
    offenders = []
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    for table in SHOP_SCOPED_TABLES:
        if table not in existing_tables:
            continue
        blanks = _count(conn, table, "shop_id = ''")
        orphans = _count(
            conn, table,
            "shop_id IS NOT NULL AND shop_id <> '' "
            "AND shop_id NOT IN (SELECT id FROM stores_store)",
        )
        if blanks or orphans:
            offenders.append((table, blanks, orphans))

    if offenders:
        detail = "\n".join(
            f'    - {t}: 空串={b} 行, 指向不存在的店={o} 行' for t, b, o in offenders
        )
        raise RuntimeError(
            "存在无法归属到任何店铺的 shop_id 数据，外键无法建立。\n"
            "请先人工处理（删除该行，或修正为正确的 shop_id）后重跑本迁移。\n"
            f"{detail}\n\n"
            "排查 SQL（把 <表名> 换成上面列出的表）：\n"
            '    SELECT id, shop_id FROM "<表名>"\n'
            "    WHERE shop_id = ''\n"
            "       OR shop_id NOT IN (SELECT id FROM stores_store);\n"
        )

    # ---------------------------------------------------------------
    # 2) 逐表建外键（逐表逐约束探测，重复执行安全）
    # ---------------------------------------------------------------
    for table in SHOP_SCOPED_TABLES:
        if table not in existing_tables:
            continue

        name = _fk_name(table)
        already = conn.execute(
            sa.text("SELECT COUNT(*) FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        ).scalar() or 0
        if already:
            continue

        op.create_foreign_key(
            name,
            source_table=table,
            referent_table="stores_store",
            local_cols=["shop_id"],
            remote_cols=["id"],
            # ★ 见文件头：RESTRICT 而非 CASCADE
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """回滚：只删外键，不动任何数据（外键是纯约束，删除它不改变数据）。"""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing_tables = set(insp.get_table_names())

    for table in SHOP_SCOPED_TABLES:
        if table not in existing_tables:
            continue
        name = _fk_name(table)
        already = conn.execute(
            sa.text("SELECT COUNT(*) FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        ).scalar() or 0
        if not already:
            continue
        op.drop_constraint(name, table, type_="foreignkey")

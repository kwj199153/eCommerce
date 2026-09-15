"""
schema 一致性：**外键只在迁移里，不在 ORM 里** —— 这条缝会静默掉守卫。

本文件守护的不变量
------------------
> 凡是带 `shop_id` 列的表，都必须有一条 `shop_id -> stores_store` 的外键。

不变量是**从库自身结构推导**的，不依赖任何硬编码表名清单：
将来新增一张带 `shop_id` 的表，它会被自动纳入检查；漏建外键会立刻红。

为什么值得单独一个文件
----------------------
这 16 条外键**只由 alembic 迁移建立**，ORM `db_model.py` 里根本没声明
（建库历史上靠 `create_all`，而 `create_all` 只认 ORM）。

⇒ 任何"从零建库"的路径只要走 `create_all`，就会**静默**得到一个没有外键的库。
   后果不是报错，而是「删店铺时不再被拦」——16 张业务表的行留成孤儿，
   接口返回 200，谁也不会发现。

   这就是「门禁存在 ≠ 在执行」在 schema 层的形态：迁移文件躺在仓库里，
   不等于它出现在每一个被使用的库里。

修复经过（本用例曾是 `xfail(strict=False)`，现已转正为**硬门禁**）
----------------------------------------------------------------
原缺口：init 迁移 `5fe72f9a9520` 的 `upgrade()` 是 `pass`（autogenerate 对着
"已被 create_all 建好表"的库跑出来的，diff 为空）⇒ 全新库没有任何一条可用的
供给路径；CI 又只 `create_all` 不跑迁移 ⇒ CI 的库里 16 张带 `shop_id` 的表
**外键 0 条**，而用例只在本地能过 ⇒ 长期以 XPASS 形态存在（披着绿的外衣）。

两条修复均已落地：
  - `be5abf1` squash 迁移成全薪基线 → 空库 `alembic upgrade head` 可跑通
  - `1b3fa59` CI 建库链路补齐：① `alembic upgrade head`
           ② 迁移链自检（单一 head / 往返 / `alembic check`）
           ③ `scripts/bootstrap_db.py` ④ `pytest`

实测证据（2026-09-15，`.workbuddy/probes/project-audit-20260915/r69x-freshdb-fk.txt`）：
  临时全新空库 `alembic upgrade head` -> returncode=0
    （`baseline: full schema (squashed)` -> `a506249ae3e3`）
  有 `shop_id` 列的表 = 16 / 有外键的表 = 16 / `missing = []`

⇒ 故**摘掉 `xfail` 标记**。本用例现在是硬门禁：任何让库丢掉这些外键的改动
  （例如把建库路径换回 `create_all`）都会直接变红。
"""

import pytest
from sqlalchemy import text

from core.database import async_session_factory


_SHOP_ID_TABLES_SQL = """
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN pg_class t ON t.relname = c.table_name
    JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'
    WHERE c.column_name = 'shop_id' AND c.table_schema = 'public'
    ORDER BY 1
"""

_SHOP_ID_FK_TABLES_SQL = """
    SELECT src.relname
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class ref ON ref.oid = con.confrelid
    WHERE con.contype = 'f'
      AND ref.relname = 'stores_store'
      AND con.conname LIKE 'fk_%_shop_id_stores_store'
    ORDER BY 1
"""


async def _schema_sets() -> tuple[set[str], set[str]]:
    async with async_session_factory() as session:
        with_shop_id = set(
            (await session.execute(text(_SHOP_ID_TABLES_SQL))).scalars().all()
        )
        with_fk = set(
            (await session.execute(text(_SHOP_ID_FK_TABLES_SQL))).scalars().all()
        )
    return with_shop_id, with_fk


async def test_every_shop_id_column_has_fk_to_stores():
    """
    ★ 核心不变量：有 `shop_id` 列的表，必须有 `shop_id → stores_store` 外键。

    两侧都从库里读，不硬编码表名 —— 新增表自动纳入。
    """
    with_shop_id, with_fk = await _schema_sets()

    # 先保证断言本身不是"空对空"：连错库时两边都是空集，`==` 会假绿
    assert with_shop_id, "库里找不到任何带 shop_id 的表 —— 检查是否连到了正确的库"

    missing = sorted(with_shop_id - with_fk)
    extra = sorted(with_fk - with_shop_id)

    assert not missing, (
        f"以下表有 shop_id 列但没有指向 stores_store 的外键，"
        f"删除店铺时会产生孤儿数据（且不会报错）：{missing}"
    )
    assert not extra, f"存在指向 stores_store 的外键、但表里没有 shop_id 列：{extra}"


async def test_migration_head_is_single_not_forked():
    """
    alembic 图必须是单 head。

    `DETAILS.md` 里记着这个坑：新增迁移若挂错父节点会产生 `Multiple head`，
    之后任何 `alembic upgrade head` 都直接失败。这条不查数据库，只读迁移文件，
    因此不受"CI 没跑迁移"影响，任何时候都有效。
    """
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(backend), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        pytest.skip(f"无法执行 alembic heads（缺 alembic/psycopg2 依赖）: {proc.stderr[-200:]}")

    heads = [l for l in (proc.stdout or "").splitlines() if l.strip() and "(head)" in l]
    assert len(heads) == 1, (
        "alembic 出现多个 head，upgrade head 会失败。\n"
        + "\n".join(heads)
    )

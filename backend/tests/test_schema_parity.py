"""
schema 一致性：**外键只在迁移里，不在 ORM 里** —— 这条缝会静默掉守卫。

本文件守护的不变量
------------------
> 凡是带 `shop_id` 列的表，都必须有一条 `shop_id → stores_store` 的外键。

不变量是**从库自身结构推导**的，不依赖任何硬编码表名清单：
将来新增一张带 `shop_id` 的表，它会被自动纳入检查；漏建外键会立刻红。

为什么值得单独一个文件
----------------------
这 16 条外键**只由 alembic 迁移 `d5e6f7a8b9c0` 建立**，ORM `db_model.py` 里
根本没声明（建库历史上靠 `create_all`，而 `create_all` 只认 ORM）。

⇒ 任何"从零建库"的路径只要走 `create_all`，就会**静默**得到一个没有外键的库。
   后果不是报错，而是「删店铺时不再被拦」——16 张业务表的行留成孤儿，
   接口返回 200，谁也不会发现。

   这就是「门禁存在 ≠ 在执行」在 schema 层的形态：迁移文件躺在仓库里，
   不等于它出现在每一个被使用的库里。

当前状态（2026-09-15 实测，证据脚本见下方）
------------------------------------------
| 环境 | shop_id 列 | 有外键 | 本用例 |
|---|---|---|---|
| 本地开发库 | 16 | 16 | 通过 |
| CI 的库 | 16 | 0 | 失败 |

CI 侧为什么修不了：**CI 跑不了 `alembic upgrade head`**。实测（临时库上执行）：

  1. 空库直接 `upgrade head` →
     `ProgrammingError: relation "products" does not exist`
     （`330c6bbf4c9e` 的 `ALTER TABLE products ADD COLUMN parent_content JSON`）
  2. 先 `create_all` 再 `upgrade head` → 同样死在同一句（create_all 今天建的是
     spus/skus，`products` 已不在 ORM 里）
  3. 生产环境（`ENVIRONMENT=production`）`create_all` 被跳过 → 什么表都没有

  根因：init 迁移 `5fe72f9a9520` 的 `upgrade()` 是 `pass` —— 它是
  autogenerate 对着"已被 create_all 建好表"的库跑出来的，diff 为空。
  ⇒ **全新库没有任何一条可用的供给路径。**

  证据脚本：`.workbuddy/tmp/p6_migration_fresh_db_probe.py`（路径 1、3）、
           `.workbuddy/tmp/p6_devpath_probe.py`（路径 2）

所以本用例暂时标 `xfail(strict=False)`
--------------------------------------
- 本地通过 → 报 XPASS（**不算失败**），提示"这个已知缺口还没修"
- CI 失败 → 报 xfail，不阻塞流水线，但失败信息完整保留在输出里

目的是让缺口**在测试输出里可见**，而不是靠人记得。
迁移链修好后（补一条真正的 baseline 迁移 / 把 init 迁成 squash 基线），
去掉 `xfail` 标记即可变成硬门禁。
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


@pytest.mark.xfail(
    strict=False,
    reason="已知缺口：外键只在 alembic 迁移里，CI 的库由 create_all 建表因此没有外键；"
           "根因是 init 迁移为空（pass）导致全新库无法 upgrade head。见本文件头部说明。",
)
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

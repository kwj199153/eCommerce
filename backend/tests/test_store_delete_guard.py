"""
店铺删除守卫：店铺下还有业务数据时，DELETE 必须 **409**。

为什么这个文件存在
------------------
`DELETE /api/v1/stores/{id}` 是**唯一**一个会牵动 16 张业务表归属的操作。
在此之前它的行为是「只要店铺存在就删掉」——把 spus / assets / candidates /
monitors / knowledge_* / platform_rules 等行全部留成孤儿（shop_id 指向一个
不存在的店）。接口返回 200，用户看到"已删除"，而这些行在法律与统计意义上
都还挂在账上。属于**静默数据损坏**，不是普通 bug。

修复引入两层：
  ① 数据库层：16 条 `fk_<table>_shop_id_stores_store` 外键，ON DELETE RESTRICT
     （见 `alembic/versions/d5e6f7a8b9c0_add_shop_id_foreign_keys.py`）
  ② 应用层：`delete_store` 把 `IntegrityError` 翻译成 409 + 可操作文案，
     并把顺序改成「**先删 PG，成功后再清内存缓存**」

本文件钉住 ②，并顺带钉住顺序（顺序反了会退化成"假成功"）。

环境前提（这条很重要，别忽略）
------------------------------
本文件验证的是**数据库外键**这一机制，前提是库里真有那 16 条外键。
而这些外键**只由 alembic 迁移建立**，ORM（`db_model.py`）里没有声明。
于是存在真实的环境差异：

  - 本地开发库：已 `alembic upgrade head` → 外键在 → 本文件全绿
  - CI 的库：`ENVIRONMENT` 默认 `development` → `core/database.py` 的
    `create_all` 兜底建表 → ORM 没声明外键 → **外键不存在**

因此下面用 `shop_fk_guard` 夹具显式探测外键；缺失时 **skip 并说明原因**，
而不是让用例以「200 != 409」这种极具误导性的方式失败（那会让人去查
`delete_store`，而真正的问题在迁移链上）。

schema 层面的缺口本身记在 `tests/test_schema_parity.py`，两件事分开。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from modules.monitors.db_model import MonitorGroupRecord
from modules.stores.db_model import StoreRecord
from modules.stores.router import _store_db


# ====== 前置探测 ======

async def _monitor_group_fk_present() -> bool:
    """库里是否真有 monitor_groups.shop_id → stores_store 的外键"""
    from core.database import async_session_factory

    async with async_session_factory() as session:
        n = (await session.execute(text(
            """
            SELECT count(*)
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            WHERE con.contype = 'f'
              AND src.relname = 'monitor_groups'
              AND con.conname LIKE 'fk_%_shop_id_stores_store'
            """
        ))).scalar()
    return bool(n)


@pytest_asyncio.fixture
async def shop_fk_guard():
    """
    依赖外键的用例的统一前置。

    缺失时 skip（不是 fail）：这是**环境差异**，不是被测代码的缺陷。
    原因写清楚，让看到 skip 的人能直接定位到根因与证据脚本。
    """
    if not await _monitor_group_fk_present():
        pytest.skip(
            "本库缺少 fk_monitor_groups_shop_id_stores_store（该外键只由 alembic 迁移 "
            "d5e6f7a8b9c0 建立，ORM 未声明）。此环境由 create_all 建表，因此无法验证 "
            "409 守卫。根因与实测证据见 tests/test_schema_parity.py 与 "
            ".workbuddy/tmp/p6_devpath_probe.py"
        )
    yield


# ====== 造数与清理 ======

async def _new_store(client) -> str:
    """建一个店铺，返回 id（与 test_stores.py 同口径，但本文件自带清理）"""
    r = await client.post(
        "/api/v1/stores",
        json={"name": f"pytest-{uuid.uuid4().hex[:6]}", "platform": "amazon_us"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest_asyncio.fixture
async def store_with_group(client):
    """
    店铺 + 该店铺下 1 行 monitor_groups。

    分组**走真实接口**创建（`POST /api/v1/monitor-groups` + `X-Shop-ID` 头），
    而不是直接插 ORM —— 这样前置数据与线上同一路径产生，顺带覆盖该端点。

    teardown 顺序必须是「先删子行，再删店铺」：外键是 RESTRICT，
    反过来删不掉，清理会失败并把垃圾留在库里。
    """
    from core.database import async_session_factory

    store_id = await _new_store(client)
    r = await client.post(
        "/api/v1/monitor-groups",
        json={"name": f"pytest-grp-{uuid.uuid4().hex[:6]}", "kind": "custom"},
        headers={"X-Shop-ID": store_id},
    )
    assert r.status_code == 201, r.text
    group_id = r.json()["id"]

    yield {"store_id": store_id, "group_id": group_id}

    async with async_session_factory() as session:
        await session.execute(
            delete(MonitorGroupRecord).where(MonitorGroupRecord.id == group_id)
        )
        await session.execute(delete(StoreRecord).where(StoreRecord.id == store_id))
        await session.commit()
    _store_db.pop(store_id, None)  # 双清：内存 + PG，避免残留影响下个用例


@pytest_asyncio.fixture
async def clean_store(client):
    """一个没有任何业务数据的店铺（应能被正常删除）"""
    from core.database import async_session_factory

    store_id = await _new_store(client)
    yield store_id

    async with async_session_factory() as session:
        await session.execute(delete(StoreRecord).where(StoreRecord.id == store_id))
        await session.commit()
    _store_db.pop(store_id, None)


# ====== 一、核心：有业务数据 → 409 ======

async def test_delete_store_with_business_data_returns_409(
    client, auth_off, shop_fk_guard, store_with_group
):
    """
    店铺下还有 monitor_groups 行时，DELETE 必须 409。

    修复前的错误形态有两种，都要被这条挡住：
      - 直接 200 删掉（产生孤儿）
      - 500（把数据库约束冲突原样冒出去，用户看不懂也不知道怎么办）
    """
    sid = store_with_group["store_id"]

    r = await client.delete(f"/api/v1/stores/{sid}")

    assert r.status_code == 409, (
        f"期望 409（拒绝删除以免产生孤儿），实际 {r.status_code}: {r.text}"
    )
    detail = r.json()["detail"]
    # 说清"为什么不能删"
    assert "业务数据" in detail
    # 说清"那我该怎么办" —— 没有出路的报错等于没报错
    assert "停用" in detail, f"409 文案缺少可操作指引: {detail}"
    # 指明是哪个店铺（并发/批量操作时这行信息很关键）
    assert sid in detail


async def test_conflict_keeps_store_intact_everywhere(
    client, auth_off, shop_fk_guard, store_with_group
):
    """
    ★ 409 之后店铺必须**三处全部原样保留**：内存缓存、读接口、PG。

    这条直接钉住本次修复的**顺序**：`delete_store` 必须是
    「先删 PG → 失败就抛 → 成功才 pop 内存」。
    若改回「先 `del _store_db[...]` 再删 PG」，冲突时内存已被清掉：
      - `_store_db` 里没有该 id
      - `GET /{id}` 返回 404（走内存读）
      - 而 PG 里数据还在
    ⇒ 用户看到"店铺没了"，刷新/重启服务（会从 PG 回灌）后"又回来了"。
    这类**假成功**比直接报错难排查得多，所以用断言把它焊死。
    """
    from core.database import async_session_factory

    sid = store_with_group["store_id"]

    assert (await client.delete(f"/api/v1/stores/{sid}")).status_code == 409

    # ① 内存缓存未被提前清掉
    assert sid in _store_db, (
        "冲突后内存缓存里已没有该店铺 —— delete_store 的顺序被改回了"
        "「先清内存再删 PG」，会产生假成功"
    )
    # ② 读接口仍可用
    r = await client.get(f"/api/v1/stores/{sid}")
    assert r.status_code == 200, r.text
    # ③ PG 里那行还在（权威存储未被动过）
    async with async_session_factory() as session:
        row = (await session.execute(
            select(StoreRecord).where(StoreRecord.id == sid)
        )).scalar_one_or_none()
    assert row is not None, "409 之后 PG 里的店铺行消失了 —— 说明删除并未被真正回滚"


# ====== 二、无业务数据 → 正常删除（守卫不能误伤） ======

async def test_delete_clean_store_succeeds(client, auth_off, clean_store):
    """
    干净的店铺必须能删掉。

    守卫类改动最常见的副作用是"拦得太狠"：把本来合法的操作也拒了。
    这条是它的反向保险。
    """
    from core.database import async_session_factory

    sid = clean_store

    r = await client.delete(f"/api/v1/stores/{sid}")
    assert r.status_code == 200, r.text
    assert r.json()["store_id"] == sid

    # 双清都生效
    assert sid not in _store_db
    assert (await client.get(f"/api/v1/stores/{sid}")).status_code == 404
    async with async_session_factory() as session:
        row = (await session.execute(
            select(StoreRecord).where(StoreRecord.id == sid)
        )).scalar_one_or_none()
    assert row is None, "接口说删成功了，PG 里却还在 —— 内存与权威存储不一致"


async def test_delete_unknown_store_404(client, auth_off):
    """不存在的店铺仍是 404（不能因为加了守卫就变成 409 或 500）"""
    r = await client.delete("/api/v1/stores/store_ffffffff")
    assert r.status_code == 404
    assert "store_ffffffff" in r.json()["detail"]

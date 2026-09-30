"""店铺平台连接相关的**测试辅助**（第 318 轮抽出）。

★★★ 为什么单独成一个模块

  `test_credential_encryption.py` 与 `test_store_connect.py` 都要
  「经真实接口建店 / 删店 / 直查密文原文」这三件事。
  留两份就是同一能力的两份实现 —— 改一处漏一处时，另一个文件会**静默地**
  用旧口径继续跑（例如建店不再走接口而是直接插 PG 行，
  于是端点 404，而红的原因看着像端点坏了）。

★ 本模块**不是**测试文件（文件名不以 `test_` 开头），pytest 不会收集它。
"""

from __future__ import annotations

import uuid
from typing import Optional


async def make_store(client, headers, platform: str = "amazon_us") -> str:
    """经**真实接口**建店（同时进内存缓存与 PG，与生产路径一致），返回 store_id。

    ★ 为什么必须走接口、而不是直接往 PG 插行：`_get_store()` 读的是**内存缓存**
      `_store_db`，只插 PG 的话打端点会 404 —— 用例会红在一个与被测逻辑
      完全无关的地方。
    """
    r = await client.post(
        "/api/v1/stores",
        json={
            "name": f"[p318] connect probe {uuid.uuid4().hex[:8]}",
            "platform": platform,
        },
        headers=headers,
    )
    assert r.status_code == 201, f"建店失败 {r.status_code} {r.text[:300]}"
    return r.json()["id"]


async def drop_store(client, headers, store_id: str) -> None:
    """经真实接口删店（同时清内存缓存与 PG）；失败则回退裸 SQL + 清内存。"""
    r = await client.delete(f"/api/v1/stores/{store_id}", headers=headers)
    if r.status_code not in (200, 204, 404):
        from sqlalchemy import text

        from core.database import async_session_factory

        async with async_session_factory() as db:
            await db.execute(
                text("DELETE FROM stores_store WHERE id = :i"), {"i": store_id}
            )
            await db.commit()
    from modules.stores.router import _store_db

    _store_db.pop(store_id, None)


async def read_raw_credentials(store_id: str) -> Optional[str]:
    """直查数据库**原文**（不经过 ORM，避免任何隐式解密）。"""
    from sqlalchemy import text

    from core.database import async_session_factory

    async with async_session_factory() as db:
        return (
            await db.execute(
                text("SELECT api_credentials FROM stores_store WHERE id = :i"),
                {"i": store_id},
            )
        ).scalar()

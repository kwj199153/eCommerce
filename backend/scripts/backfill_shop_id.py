"""
存量数据 shop_id 回填脚本

将多租户隔离改造前的存量业务数据（spus/candidates/assets 及各自分组表）
的 shop_id 回填到指定店铺（默认第一个 store_xxx），使选择该店铺后可见。

用法：
    cd backend
    python scripts/backfill_shop_id.py [目标 shop_id]

不传参数时，自动取 stores_store 表里最早创建的一个店铺作为目标店铺；
若 stores_store 为空则回填为 ''（保持原样，不虚构店铺）。
"""

import asyncio
import os
import sys

from sqlalchemy import text

# 把 backend 根目录加入 sys.path，保证 `core` 可导入（脚本从任意目录运行均可）
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from core.database import get_async_session

# 需要回填的表（有 shop_id 字段的业务表 + 分组表）
BACKFILL_TABLES = [
    "spus",
    "candidates",
    "assets",
    "product_groups",
    "candidate_groups",
    "asset_groups",
]


async def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else None

    async with get_async_session() as s:
        # 1. 确定目标店铺
        if target is None:
            r = await s.execute(
                text("SELECT id FROM stores_store ORDER BY created_at ASC LIMIT 1")
            )
            row = r.scalar_one_or_none()
            target = row if row else ""
            if target:
                print(f"未指定目标店铺，自动选择最早创建的店铺: {target}")
            else:
                print("⚠️ stores_store 为空，存量数据 shop_id 将回填为 ''（不虚构店铺）")

        # 2. 逐表回填（仅回填 shop_id 为空串或无效值 'shop-1' 的行）
        total = 0
        for table in BACKFILL_TABLES:
            try:
                # 只回填空串或旧占位值，避免覆盖已有有效归属
                result = await s.execute(
                    text(
                        f"UPDATE {table} SET shop_id = :target "
                        f"WHERE shop_id = '' OR shop_id = 'shop-1'"
                    ),
                    {"target": target},
                )
                total += result.rowcount
                print(f"  {table}: 回填 {result.rowcount} 行")
            except Exception as e:
                print(f"  {table}: 跳过（{str(e)[:60]}）")

        await s.commit()

    print(f"\n✅ 回填完成，共 {total} 行 shop_id -> {target!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

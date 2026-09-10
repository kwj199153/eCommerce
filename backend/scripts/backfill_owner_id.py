"""
存量数据 owner_id 回填脚本

用途：stores_store 新增 owner_id 后，把存量店铺回填到测试用户，
打通「用户 → 店铺」归属，避免生产模式下存量数据全部不可见。

回填策略（本次）：
- 存量 4 个 store_xxx 店铺 + 其下业务数据（spus/candidates/assets）
  统一回填到 tenant-test-a@example.com（测试用户）
- tenant_id 保留（仍为 default_tenant，兼容；真实租户映射由后续 tenant_id 收口统一处理）

用法（reactAgents 环境）：
    cd backend
    python scripts/backfill_owner_id.py
"""
import asyncio
import sys
from pathlib import Path

# 让 scripts/ 能 import 项目包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from core.database import get_async_session

TARGET_EMAIL = "tenant-test-a@example.com"


async def main() -> None:
    async with get_async_session() as db:
        # 1. 找目标用户
        user_row = (
            await db.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": TARGET_EMAIL},
            )
        ).scalar_one_or_none()

        if not user_row:
            print(f"❌ 目标用户不存在: {TARGET_EMAIL}")
            return

        user_id = user_row
        print(f"目标用户: {TARGET_EMAIL} ({user_id})")

        # 2. 回填 stores_store.owner_id（当前为 NULL 的存量店铺）
        stores = (
            await db.execute(
                text("SELECT id FROM stores_store WHERE owner_id IS NULL")
            )
        ).scalars().all()

        if stores:
            await db.execute(
                text("UPDATE stores_store SET owner_id = :uid WHERE owner_id IS NULL"),
                {"uid": user_id},
            )
            print(f"✅ 回填 stores_store.owner_id: {len(stores)} 个店铺 -> {user_id}")

        # 3. 业务数据无需改 shop_id（已指向 store_xxx），但列出确认
        for tbl in ("spus", "candidates", "assets"):
            cnt = (
                await db.execute(
                    text(f"SELECT count(*) FROM {tbl} WHERE shop_id = 'store_c3529ab1'")
                )
            ).scalar_one()
            print(f"    {tbl}: {cnt} 条 (shop_id=store_c3529ab1)")

        await db.commit()
        print("\n回填完成。")


if __name__ == "__main__":
    asyncio.run(main())

"""给「有归因但还没处置」的中差评批量生成 `proposed` 处置（幂等）。

用法::

    python scripts/seed_dispositions.py                 # 给**所有**店铺补灌
    python scripts/seed_dispositions.py --shop <id>     # 只给指定店铺补灌

★ 为什么要有这个脚本（第 287 轮 P0-2）
    `review_dispositions` 这张表此前**全库 0 行**，根因是全仓没有一处
    `ReviewDispositionRecord(...)` 的构造 —— 没有写入路径。
    第 287 轮补了写入路径（`propose_disposition` + REST 端点 + Agent 工具），
    但**补完管道表里仍然可以是 0 行**（历史差评从未被处置过）。
    本脚本就是那个「把管道灌上水」的一步：按已落库的归因 + 补偿规则，
    确定性地合成双语回复草稿与补偿方案，落成待批准状态。

★ 落的是 `proposed`，不是 `issued`：券发出去是不可逆动作，
  批准与发放两步留给**人**（REST 端点 / 前端处置列表）。
  脚本不代劳 —— 否则「脚本一键发券」等于把 HITL 架空。

★ 幂等：已有处置（任何状态）一律跳过，不覆盖。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _all_shop_ids(session):
    from sqlalchemy import select

    from modules.trade.db_model import CustomerReviewRecord

    rows = (await session.execute(
        select(CustomerReviewRecord.shop_id).distinct()
    )).scalars().all()
    return [r for r in rows if r]


async def _main(shop_ids):
    from core.database import async_session_factory
    from modules.trade import service as svc

    async with async_session_factory() as session:
        targets = shop_ids or await _all_shop_ids(session)

    if not targets:
        print("库里没有可灌的店铺（customer_reviews 为空）")
        return

    total = 0
    for shop_id in targets:
        async with async_session_factory() as session:
            out = await svc.backfill_dispositions(session, shop_id)
        total += out["created"]
        print(
            f"  {shop_id}: 扫描 {out['scanned']} 条 / 新建 {out['created']} 条 / "
            f"跳过 {out['skipped']} 条"
            + (f" / 失败 {len(out['failed'])} 条 {out['failed']}"
               if out["failed"] else "")
        )
    print(f"合计新建 {total} 条（状态均为 proposed，等待人工批准）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", action="append", default=[],
                    help="只给指定店铺灌（可重复）")
    args = ap.parse_args()
    asyncio.run(_main(args.shop))

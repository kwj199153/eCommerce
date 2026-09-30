"""把 12 条演示话术灌进 `knowledge_faqs`（幂等）。

用法::

    python scripts/seed_cs_faq.py                 # 给所有店铺补灌（已存在的跳过）
    python scripts/seed_cs_faq.py --shop <id>     # 只给指定店铺补灌

★ 为什么要有这个脚本：`modules/customer_service/cs_faq_seed.json` 里那 12 条
  原本是锁在源码里的内存常量（`agent_cs.MOCK_FAQ_DB`）——改不动、不落库、
  重启即回原样。第 286 轮把它们迁进库：内容一字未改，但从此**可编辑、
  可被资料库页面看到、能被客服检索到**（数据 mock 进库，而不是 mock 在源码里）。

★ 幂等：按 `id = cs-<原id>-<shop_id>` 判存在，已存在即跳过；重跑零副作用。
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _main(shop_ids):
    from modules.customer_service.faq_source import seed_cs_faqs

    result = await seed_cs_faqs(only_for_shop_ids=shop_ids or None)
    if not result:
        print("没有新增任何行（已灌过 / 店铺没有默认知识库 / 库里没有店铺）")
        return
    for shop_id, n in result.items():
        print(f"  {shop_id}: +{n} 条")
    print(f"合计新增 {sum(result.values())} 条")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", action="append", default=[],
                    help="只给指定店铺灌（可重复）")
    args = ap.parse_args()
    asyncio.run(_main(args.shop))

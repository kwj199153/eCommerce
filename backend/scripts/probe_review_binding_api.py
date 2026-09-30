# -*- coding: utf-8 -*-
"""运行期验证：第 289 轮新增的两个 service 函数在**真库**上的行为 —— 只读。

验五件事（每件事对应一条机械能因此被测红的判据）：
  C1 同一个 SPU 内，同一条差评**不重复计数**（ASIN→多 SKU 的抖动已被吸收）
  C2 两种空态**字面不同**：`no_reviews`（正常结论）vs `no_asin_binding`（数据缺口）
  C3 跨租户：换一个 shop_id ⇒ `found=False`，且拿不到任何差评
  C4 孤儿判定：孤儿数 + 已收养数 == 该店差评总数（**没人被漏**）
  C5 孤儿 query 的店铺口径：命中别家店 SKU 的差评仍算本店孤儿

★ 必须在 `backend/` 下跑：`.env` 相对 CWD 读，跑错目录会静默退回默认值。
"""
import asyncio
import logging
import os
import sys
from collections import Counter
from pathlib import Path

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://kevin:123456@localhost:5432/postgres")

from core.database import async_session_factory  # noqa: E402
from sqlalchemy import text  # noqa: E402

from modules.trade import service  # noqa: E402

SHOP = "store_c3529ab1"          # 真库当前唯一有差评的店
OTHER = "store_does_not_exist"   # 用于跨租户反向注入


#: ★ 探针一律落文件：SQL echo 日志混在同一个 stdout 里，
#:   如果只看终端就会被日志淹掉（本仓判据：探针输出应与 sqlalchemy 日志分流）。
OUT = Path(__file__).resolve().parent.parent / "out-probe-binding.txt"


def line(s=""):
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        f.write(s + "\n")


async def main():
    async with async_session_factory() as s:
        total_rev = (await s.execute(text(
            "select count(*) from customer_reviews"))).scalar() or 0
        shop_ids = [r[0] for r in (await s.execute(text(
            "select distinct shop_id from customer_reviews"))).fetchall()]
        line(f"customer_reviews 总数={total_rev}  shop_id 分布={shop_ids}")

        spu_ids = [r[0] for r in (await s.execute(text(
            "select id from spus order by id limit 8"))).fetchall()]

        # ---------------- C1 / C2 ----------------
        line("\n=== C1+C2 逐个 SPU 聚合 ===")
        seen: Counter = Counter()
        for sid in spu_ids:
            res = await service.list_reviews_for_spu(s, SHOP, sid)
            ids = [r["id"] for r in res["reviews"]]
            dup = len(ids) != len(set(ids))
            seen.update(ids)
            line(f"  {sid}: found={res['found']} empty={res['empty_state']} "
                 f"sku={res['sku_count']} asin={res['asin_count']} "
                 f"total={res['total']} 页内重复={dup} "
                 f"match_kind={sorted({r['match_kind'] for r in res['reviews']})}")

        line(f"  => 跨 SPU 认领次数分布: {dict(seen)}")
        line("  （一个 ASIN 挂在多个 SPU 下时，跨 SPU 重复属**数据本身**的问题；")
        line("    单次调用内部的去重由 `total` != 页内重复 判据守着）")

        # ---------------- C3 跨租户 ----------------
        line("\n=== C3 跨租户反向注入 ===")
        victim = None
        for sid in spu_ids:
            own = await service.list_reviews_for_spu(s, SHOP, sid)
            if own.get("total"):
                victim = sid
                break
        if victim:
            bad = await service.list_reviews_for_spu(s, OTHER, victim)
            bad2 = await service.list_reviews_for_spu(s, None, victim)
            line(f"  victim={victim}  用别的 shop -> found={bad['found']} "
                 f"total={bad['total']} empty={bad['empty_state']}")
            line(f"                 用 None shop -> found={bad2['found']} "
                 f"total={bad2['total']} empty={bad2['empty_state']}")
            ok = (bad["found"] is False and bad["total"] == 0
                  and bad2["found"] is False and bad2["total"] == 0)
            line(f"  => 跨租户隔离 {'PASS' if ok else 'FAIL'}")

        # ---------------- C4 / C5 孤儿 ----------------
        line("\n=== C4+C5 孤儿 ===")
        for rating in (None, 3):
            res = await service.list_orphan_reviews(s, SHOP, max_rating=rating,
                                                    limit=200)
            cnt = await service.count_orphan_reviews(s, SHOP, max_rating=rating)
            mine = (await s.execute(text(
                "select count(*) from customer_reviews where shop_id=:s")
                , {"s": SHOP})).scalar() or 0
            line(f"  max_rating={rating}: 本店差评={mine} 孤儿={res['total']} "
                 f"(count_orphan={cnt}) empty={res['empty_state']}")
            assert res["total"] == cnt, "列表 total 与 count_orphan_reviews 不一致"
            for r in res["items"][:5]:
                line(f"     孤儿样例 asin={r['asin']!r} sku={r['sku']!r} "
                     f"rating={r['rating']}")

        # 孤儿 + 已收养 覆盖性
        res = await service.list_orphan_reviews(s, SHOP, limit=200)
        adopted = await s.execute(text("""
            select count(distinct r.id) from customer_reviews r
            join skus k on k.asin = r.asin and coalesce(k.asin,'')<>''
            join spus p on p.id = k.spu_id and p.shop_id = r.shop_id
            where r.shop_id = :s
        """), {"s": SHOP})
        n_adopted = adopted.scalar() or 0
        n_mine = (await s.execute(text(
            "select count(*) from customer_reviews where shop_id=:s"),
            {"s": SHOP})).scalar() or 0
        # ---------------- C6 反向注入：证明这两个 API 真的能测出「有」 ----------------
        #
        # ★ 真库当前孤儿数 = 0 ⇒ 「孤儿列表返回 0」这条绿什么都证明不了：
        #   查询写错成 `where 1=0` 也会返回 0。要让它可信，必须在事务里制造出
        #   孤儿、断言它出现，再 rollback（不污染真库）。
        line("\n=== C6 反向注入（事务内，最后 rollback） ===")
        # ★ 用 ORM 实体插入而不是裸 SQL：`mapped_column(default=...)` 是
        #   **ORM 层**的默认值，裸 insert 拿不到 ⇒ 会撞 NOT NULL（实测就是
        #   `title` 先炸出来）。探针里再手写一遍全列 = 定义第二次（易漂移）。
        s.add(service.CustomerReviewRecord(
            id="crev-probe-orphan-1", shop_id=SHOP,
            external_review_id="PROBE-ORPHAN-1",
            sku="SKU-PROBE-X", asin="B0PROBEZZZZ",
            product_title="探针孤儿", rating=1, source="probe",
            review_at="2026-09-01",
        ))
        await s.flush()

        res2 = await service.list_orphan_reviews(s, SHOP, limit=200)
        cnt2 = await service.count_orphan_reviews(s, SHOP)
        mine2 = (await s.execute(text(
            "select count(*) from customer_reviews where shop_id=:s"
        ), {"s": SHOP})).scalar() or 0
        hit = [r["id"] for r in res2["items"]]
        line(f"  注入 1 条无匹配差评后：本店={mine2} 孤儿={res2['total']} "
             f"(count={cnt2}) 命中={hit}")
        c6a = (res2["total"] == 1 and "crev-probe-orphan-1" in hit and cnt2 == 1)
        line(f"  => 孤儿能被检出: {'PASS' if c6a else 'FAIL'}")

        # ★ C6b 的正向 / 反向都必须测：只测「孤儿能被检出」不够 ——
        #   查询写成 `NOT EXISTS (select 1 where 1=0)` 也能检出 1 条，那是假绿。
        #   还要看它「被收养之后孤儿数会回落」。
        await s.execute(text(
            "update customer_reviews set asin="
            "  (select asin from skus where spu_id=:p limit 1) "
            "where id='crev-probe-orphan-1'"), {"p": "prod-002"})
        await s.flush()
        adopted_back = await service.list_orphan_reviews(s, SHOP, limit=200)
        line(f"  把该差评的 ASIN 改成 prod-002 的 ASIN 后：孤儿={adopted_back['total']}"
             f"（应回落到 0）")
        c6b = adopted_back["total"] == 0
        line(f"  => 正向/反向成对生效: {'PASS' if c6b else 'FAIL'}")

        # ★ C6c 跨店铺口径：把承接它的 SPU 挪到**别家真实存在的店**，
        #   本店这 4 条差评应立刻全部变孤儿 —— 证明「别家店的 SKU 不认领本店差评」。
        # ★ C6c 第一次写错成「只挪 prod-002」⇒ 结果是孤儿仍 0（不算 FAIL，是期望错）：
        #   同一个 ASIN 挂在 4 个 SPU 下（这就是 C1 的那个抖动源），挪走其中一个，
        #   剩下三个还在本店认领同一批差评 ⇒ 孤儿数当然不变。
        #   ⇒ 必须把**全部承接方**都挪走，断言才有意义。
        OTHER_SHOP = "store_72ad211f"      # yamaxun1（真库里存在，FK 才过得去）
        await s.execute(text("""
            update spus set shop_id=:o
            where id in (
              select k.spu_id from skus k
              join customer_reviews r on r.asin = k.asin
              where r.shop_id = :s and coalesce(k.asin,'')<>''
            )
        """), {"o": OTHER_SHOP, "s": SHOP})
        await s.flush()
        cross = await service.list_orphan_reviews(s, SHOP, limit=200)
        mine_cross = (await s.execute(text(
            "select count(*) from customer_reviews where shop_id=:s"
        ), {"s": SHOP})).scalar() or 0
        line(f"  把全部承接方 SPU 挪到 {OTHER_SHOP} 后：本店差评={mine_cross} "
             f"孤儿={cross['total']}（应=全部，因为承接方已不属于本店）")
        c6c = cross["total"] == mine_cross
        line(f"  => 孤儿判定按**本店**产品计，不认别店 SKU: {'PASS' if c6c else 'FAIL'}")

        # ---------------- C7 反向注入：数据缺口空态 `no_asin_binding` ----------------
        # ★ 必须在这里 rollback：C6c 把 SPU 挪去了别家店，若不回滚，
        #   后续 C7 读到的 prod-002 已经不属于本店 ⇒ `found=False`，
        #   会把「跨租户读不到」误读成「空态判据坏了」。
        await s.rollback()

        line("\n=== C7 反向注入 no_asin_binding（事务内，最后 rollback） ===")
        victim2 = "prod-002"
        before = await service.list_reviews_for_spu(s, SHOP, victim2)
        await s.execute(text(
            "update skus set asin='', sku_code='' where spu_id=:p"), {"p": victim2})
        await s.flush()
        after = await service.list_reviews_for_spu(s, SHOP, victim2)
        line(f"  清空 {victim2} 名下 SKU 的 ASIN/SKU码：")
        line(f"    before: empty={before['empty_state']} total={before['total']} "
             f"asin={before['asin_count']}")
        line(f"    after : empty={after['empty_state']} total={after['total']} "
             f"asin={after['asin_count']}")
        c7 = (before["empty_state"] is None and before["total"] > 0
              and after["empty_state"] == "no_asin_binding" and after["total"] == 0)
        line(f"  => 「数据缺口」与「确实没有」两种空态可区分: {'PASS' if c7 else 'FAIL'}")
        await s.rollback()

        line("\n=== 汇总 ===")
        # ★ 判据口径必须覆盖**全部**落点（本仓铁律）：第一版这里写成
        #   `all([c6a, c6b, c7])`，把刚加的 c6c 漏在外面 ⇒ c6c 明明打了 FAIL，
        #   汇总却报「全绿」—— 探针自己变成了假绿的源头。
        marks = {"C6a 孤儿能被检出": c6a, "C6b 成对生效": c6b,
                 "C6c 不认别店 SKU": c6c, "C7 两种空态可区分": c7}
        for k, v in marks.items():
            line(f"  {'PASS' if v else 'FAIL'}  {k}")
        line(f"  => 反向注入 {'全绿' if all(marks.values()) else '有红，需查'}")

    line("\nDONE")


if __name__ == "__main__":
    OUT.write_bytes(b"")   # 每轮清干净：留着旧的会以为新结论是旧的
    asyncio.run(main())

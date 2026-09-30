"""取证：差评(customer_reviews) 与产品库(spus/skus) 的关联可行性 —— 只读。

回答三个问题：
  Q1 差评的 asin / sku 字段实际长什么样、填充率多少
  Q2 差评.asin 能否对上 skus.asin（含店铺作用域过滤）
  Q3 差评.sku 能否对上 skus.sku_code / SKU 的什么字段
"""
import os
from collections import Counter

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://kevin:123456@localhost:5432/postgres")

from sqlalchemy import create_engine, text  # noqa: E402

ENGINE = create_engine("postgresql+psycopg2://kevin:123456@localhost:5432/postgres")


def show(title, rows):
    print(f"\n=== {title} ===")
    if not rows:
        print("  (empty)")
        return
    for r in rows:
        print("  ", tuple(r))


def main():
    with ENGINE.connect() as c:
        n_rev = c.execute(text("select count(*) from customer_reviews")).scalar() or 0
        n_spu = c.execute(text("select count(*) from spus")).scalar() or 0
        n_sku = c.execute(text("select count(*) from skus")).scalar() or 0
        print(f"customer_reviews={n_rev}  spus={n_spu}  skus={n_sku}")
        if n_rev == 0:
            print("!! 差评表 0 行，后续 join 无意义")
            return

        # Q1 填充率
        show("Q1 填充率", c.execute(text("""
            select
              count(*) filter (where coalesce(asin,'')<>'') as has_asin,
              count(*) filter (where coalesce(sku,'')<>'')  as has_sku,
              count(*) filter (where coalesce(asin,'')<>'' and coalesce(sku,'')<>'') as both,
              count(distinct shop_id) as shop_cnt,
              count(*) filter (where rating<=3) as neg_cnt
            from customer_reviews
        """)).fetchall())

        show("Q1 差评里的 shop_id 分布", c.execute(text("""
            select shop_id, count(*) from customer_reviews group by shop_id order by 2 desc limit 10
        """)).fetchall())

        show("Q1 差评 asin 样例", c.execute(text("""
            select asin, sku, rating, left(product_title,28) from customer_reviews limit 8
        """)).fetchall())

        if n_sku == 0:
            print("\n!! skus 表 0 行 ⇒ 无论怎么 join 都是「孤儿」，此时 P0 tab 必然全空")
        else:
            show("Q2 按 ASIN join（不区分店铺）", c.execute(text("""
                select count(*) as reviews_matched,
                       count(distinct r.id) as distinct_reviews
                from customer_reviews r
                join skus s on s.asin = r.asin and coalesce(r.asin,'')<>''
            """)).fetchall())

            # ★ 店铺作用域：skus 无 shop_id，必须经 skus.spu_id -> spus.shop_id
            show("Q2 按 ASIN join + 店铺归属一致", c.execute(text("""
                select count(*) as matched_in_scope
                from customer_reviews r
                join skus s on s.asin = r.asin and coalesce(r.asin,'')<>''
                join spus p on p.id = s.spu_id and p.shop_id = r.shop_id
            """)).fetchall())

            show("Q2 每个 SPU 能挂到几条差评（top）", c.execute(text("""
                select p.id as spu_id, left(p.title,24) as spu_title, count(*) as rev_cnt,
                       count(*) filter (where r.rating<=3) as neg_cnt
                from customer_reviews r
                join skus s on s.asin = r.asin and coalesce(r.asin,'')<>''
                join spus p on p.id = s.spu_id and p.shop_id = r.shop_id
                group by p.id, p.title order by rev_cnt desc limit 10
            """)).fetchall())

            show("Q3 差评.sku vs skus.sku_code 命中", c.execute(text("""
                select count(*) from customer_reviews r
                join skus s on s.sku_code = r.sku and coalesce(r.sku,'')<>'' and coalesce(s.sku_code,'')<>''
            """)).fetchall())

            codes = [r[0] for r in c.execute(text(
                "select distinct coalesce(nullif(sku_code,''),'<empty>') from skus limit 50"
            )).fetchall()]
            rev_skus = [r[0] for r in c.execute(text(
                "select distinct coalesce(nullif(sku,''),'<empty>') from customer_reviews limit 50"
            )).fetchall()]
            rev_asins = [r[0] for r in c.execute(text(
                "select distinct coalesce(nullif(asin,''),'<empty>') from customer_reviews limit 50"
            )).fetchall()]
            print("\n=== Q3 样例 ===")
            print("  skus.sku_code :", codes[:12])
            print("  reviews.sku   :", rev_skus[:12])
            print("  reviews.asin  :", rev_asins[:12])

            show("Q2 一个 ASIN 是否对应多个 SKU（抖动源）", c.execute(text("""
                select asin, count(*) as sku_rows, count(distinct spu_id) as spu_cnt
                from skus where coalesce(asin,'')<>'' group by asin having count(*)>1 limit 10
            """)).fetchall())

        # 孤儿规模
        show("Q_孤儿 匹配不上的差评数", c.execute(text("""
            select count(*) from customer_reviews r
            where coalesce(r.asin,'')<>''
              and not exists (
                select 1 from skus s join spus p on p.id=s.spu_id and p.shop_id=r.shop_id
                where s.asin = r.asin)
        """)).fetchall())


if __name__ == "__main__":
    main()

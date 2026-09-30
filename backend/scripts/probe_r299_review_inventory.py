# -*- coding: utf-8 -*-
"""r299 · P0 盘点：customer_reviews 现有数据（**只读**）

用途：老板批了 P0「买家消息风险预警」，但 P0 的第一步是**看现有数据够不够、
长什么样**。本脚本只做盘点与粗筛，不写库、不改表、不下结论。

★ 必须在 backend/ 下跑：`.env` 相对 CWD，否则静默退回默认值（配置读不到）。
   这里用 os.chdir 兜底，且必须在 import core.config 之前完成。

★ 本脚本**不改任何数据**：只有 SELECT。

产出：backend/out-probe-r299-review-inventory.txt（UTF-8，LF）
"""

import os
import re
import sys
import json
import asyncio
import collections

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text  # noqa: E402
from core.database import async_session_factory, register_all_models  # noqa: E402
from wiring import MODEL_MODULES  # noqa: E402
from core.config import config  # noqa: E402

OUT = os.path.join(BACKEND, "out-probe-r299-review-inventory.txt")

_lines: list[str] = []


def p(s: str = "") -> None:
    _lines.append(str(s))
    print(s)


# ============================================================ 粗筛关键词
# ★ 这只是**数据基础体检**用的粗筛，不是最终判定口径（口径在 #1072 单独设计）。
# ★ 一律用正则 + 词边界：`"case" in body` 会把 "in case" / "case of" 全数命中。
RISK_PATTERNS: dict[str, list[str]] = {
    "威胁差评 / 逼退威胁": [
        r"negative (review|feedback)",
        r"bad (review|feedback)",
        r"\b1[-\s]?star\b",
        r"\bone[-\s]star\b",
        r"leave a (bad |negative )?review",
        r"write a (bad |negative )?review",
        r"post (it |this )?(online|on social)",
        r"social media",
        r"\b(facebook|twitter|instagram|tiktok|reddit)\b",
        r"tell (everyone|everybody|people)",
        r"warn (others|people)",
        r"never (buy|shop|order) (from )?(you|again)",
        # 法务升级（威胁的极端形态）
        r"\b(lawyer|attorney|solicitor)\b",
        r"\blawsuit\b",
        r"\bsue\b",
        r"legal action",
        r"small claims",
        r"\bBBB\b",
        r"consumer (protection|rights)",
        r"trading standards",
    ],
    "索赔 / 要钱": [
        r"\brefund\b",
        r"\breimburs",
        r"money back",
        r"\bcompensat",
        r"charge ?back",
        r"\bdispute\b",
        r"\bdamages\b",
        r"replacement",
        r"\breturn\b",
    ],
    "A-to-Z 前兆": [
        r"a[-\s]?to[-\s]?z",
        r"\batoz\b",
        r"amazon guarantee",
        r"guarantee claim",
    ],
    "开 case / 投诉平台": [
        r"open (a |an )?case",
        r"file (a |an )?case",
        r"amazon case",
        r"(file|make|lodge) a complaint",
        r"complain to (amazon|the platform)",
        r"contact amazon",
        r"report (you|this) to amazon",
        r"seller central",
        r"\bescalat",
        r"report to (the )?authorit",
        r"third[-\s]?party (arbitrat|mediation)",
    ],
}

_COMPILED = {
    k: [re.compile(pat, re.IGNORECASE) for pat in v] for k, v in RISK_PATTERNS.items()
}


def scan(text_blob: str) -> dict[str, list[str]]:
    """返回 {类别: [命中的模式串]}；空 dict 表示零命中。"""
    hits: dict[str, list[str]] = {}
    for cat, pats in _COMPILED.items():
        got = [pt.pattern for pt in pats if pt.search(text_blob)]
        if got:
            hits[cat] = got
    return hits


async def main() -> None:
    register_all_models(MODEL_MODULES)

    p("=" * 78)
    p("r299 · P0 盘点：customer_reviews 现有数据（只读）")
    p("=" * 78)
    p(f"CWD            : {os.getcwd()}")
    p(f"environment    : {config.environment}")
    db = config.database_url
    # 打码口令
    p(f"database_url   : {re.sub(r'//[^:@]+:[^@]+@', '//***:***@', db)}")
    p("")

    async with async_session_factory() as s:
        # ---------- 1. 总量 ----------
        total = (await s.execute(text("SELECT count(*) FROM customer_reviews"))).scalar()
        p(f"[1] customer_reviews 总行数 = {total}")

        # 表是否存在 / 其它相关表
        for t in ("review_dispositions", "review_attributions",
                  "compensation_rules", "sku_health_scores", "orders", "shipments"):
            try:
                n = (await s.execute(text(f"SELECT count(*) FROM {t}"))).scalar()
                p(f"    关联表 {t:22s} = {n}")
            except Exception as e:  # noqa: BLE001
                p(f"    关联表 {t:22s} = <查不到: {type(e).__name__}>")
        p("")

        if not total:
            p("!! 表是空的 —— 没有任何差评数据可扫。P0 需先造/导入数据。")
            _flush()
            return

        # ---------- 2. 分布 ----------
        dims = [
            ("platform", "platform"),
            ("shop_id", "shop_id"),
            ("rating", "rating"),
            ("status", "status"),
            ("source", "source"),
            ("language", "language"),
            ("marketplace", "marketplace"),
        ]
        p("[2] 分布")
        for label, col in dims:
            rows = (await s.execute(text(
                f"SELECT {col} AS k, count(*) AS n FROM customer_reviews "
                f"GROUP BY {col} ORDER BY n DESC NULLS LAST"
            ))).all()
            p(f"    -- {label} --")
            for k, n in rows:
                p(f"       {str(k):<28s} {n}")
        p("")

        # ---------- 3. 正文可用性 ----------
        row = (await s.execute(text(
            "SELECT "
            "  count(*) FILTER (WHERE coalesce(body,'') = '')            AS empty_body, "
            "  count(*) FILTER (WHERE length(coalesce(body,'')) < 40)    AS short_body, "
            "  count(*) FILTER (WHERE coalesce(title,'') <> '')          AS has_title, "
            "  count(*) FILTER (WHERE rating <= 2)                       AS low_rating, "
            "  count(*) FILTER (WHERE rating >= 4)                       AS high_rating, "
            "  count(*) FILTER (WHERE rating = 3)                        AS mid_rating, "
            "  count(*) FILTER (WHERE order_id IS NOT NULL AND order_id <> '') AS has_order, "
            "  count(DISTINCT shop_id)                                   AS shops, "
            "  count(DISTINCT sku)                                       AS skus, "
            "  count(DISTINCT asin)                                      AS asins "
            "FROM customer_reviews"
        ))).one()
        keys = ["empty_body", "short_body", "has_title", "low_rating", "high_rating",
                "mid_rating", "has_order", "shops", "skus", "asins"]
        p("[3] 正文与结构可用性")
        for k, v in zip(keys, row):
            p(f"    {k:<14s} = {v}")
        p("")

        # ---------- 4. 已处置情况 ----------
        try:
            d = (await s.execute(text(
                "SELECT count(*), count(DISTINCT review_id) FROM review_dispositions"
            ))).one()
            p(f"[4] 处置台账：{d[0]} 条，覆盖 {d[1]} 条差评")
            st = (await s.execute(text(
                "SELECT status, count(*) FROM review_dispositions GROUP BY status ORDER BY 2 DESC"
            ))).all()
            for k, n in st:
                p(f"       status={k:<20s} {n}")
        except Exception as e:  # noqa: BLE001
            p(f"[4] 处置台账查询失败: {type(e).__name__}: {e}")
        p("")

        # ---------- 5. 粗筛：风险话术命中 ----------
        rows = (await s.execute(text(
            "SELECT id, shop_id, platform, rating, status, title, body "
            "FROM customer_reviews ORDER BY id"
        ))).all()

        cat_hit = collections.Counter()
        cat_examples: dict[str, list[tuple]] = collections.defaultdict(list)
        detail_rows = []
        for r in rows:
            rid, shop, plat, rating, status, title, body = r
            blob = f"{title or ''}\n{body or ''}"
            hits = scan(blob)
            if hits:
                for c in hits:
                    cat_hit[c] += 1
                    if len(cat_examples[c]) < 5:
                        cat_examples[c].append((rid, rating, (title or "")[:70]))
                detail_rows.append((rid, shop, plat, rating, status, list(hits), title, body))

        p("[5] 风险话术**粗筛**（正则词边界，未做语义判定；数字是命中条数，同一条可命中多类）")
        for c in RISK_PATTERNS:
            p(f"    {c:<22s} {cat_hit.get(c, 0)}")
        p(f"    命中任一类的总条数 = {len(detail_rows)}")
        p("")

        # ---------- 6. 命中明细（全量打印，供人工判准不准）----------
        p("[6] 命中明细（全量）")
        p("-" * 78)
        for i, (rid, shop, plat, rating, status, hits, title, body) in enumerate(detail_rows, 1):
            p(f"--- #{i} {rid}")
            p(f"    shop={shop} platform={plat} rating={rating} status={status}")
            p(f"    命中类别: {hits}")
            p(f"    title: {title}")
            p(f"    body : {body}")
            p("")
        p("-" * 78)
        p("")

        # ---------- 7. 未命中的低星样本（看漏报风险）----------
        low = [r for r in rows if (r[3] or 0) <= 2]
        p(f"[7] 低星(rating<=2)共 {len(low)} 条；其中粗筛零命中的前 8 条（查漏报风险）：")
        shown = 0
        for r in low:
            rid, shop, plat, rating, status, title, body = r
            if scan(f"{title or ''}\n{body or ''}"):
                continue
            p(f"--- {rid} | rating={rating} | {title}")
            p(f"    {body}")
            shown += 1
            if shown >= 8:
                break
        if shown == 0:
            p("    （无：所有低星都命中了至少一类粗筛模式）")
        p("")

    _flush()


def _flush() -> None:
    # ★ Windows 二进制写盘：避免 Path.write_text 把 LF 翻成 CRLF
    with open(OUT, "wb") as f:
        f.write(("\n".join(_lines) + "\n").encode("utf-8"))
    print(f"\n[written] {OUT}")


if __name__ == "__main__":
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""一次性补丁（第 289 轮 P1 前半）：给本店近期差评补 HTTP 出口。

★ 为什么要补：`service.list_recent_negative_reviews` 此前只有一个调用点
  （`modules/trade/tools.py:122`，是 **Agent 工具**）—— 没有端点、前端拿不到。
  这就是本仓反复出现的「三无」形态之一：有函数、没有出口、没人看得见。
  客服工作台（差评列表）正需要它，顺手把口补上。
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SERVICE = BACKEND / "modules" / "trade" / "service.py"
ROUTER = BACKEND / "modules" / "trade" / "router.py"
INIT = BACKEND / "modules" / "trade" / "__init__.py"


def _read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write(p: Path, s: str) -> None:
    p.write_bytes(s.encode("utf-8"))


def sub(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    assert n == 1, f"锚点命中 {n} 次（须为 1）：{label}"
    return src.replace(old, new, 1)


# ---------------- service：抽出条件 + 补 count + 加 offset

svc = _read(SERVICE)

svc = sub(
    svc,
    '''async def list_recent_negative_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, limit: int = 20,
    days: int = 30,
) -> list[dict]:
    """列出本店铺近期的中差评（默认 ≤3 星、30 天内）。"""
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            CustomerReviewRecord.rating <= max_rating,
            CustomerReviewRecord.review_at >= since,
        ))
        .order_by(CustomerReviewRecord.review_at.desc())
        .limit(limit)
    )).scalars().all()
    return [_review_to_dict(r) for r in rows]''',
    '''def _recent_negative_condition(shop_id: str, max_rating: int, days: int):
    """「本店近期的中差评」这个过滤条件 —— **唯一**口径。

    ★ list 与 count 共用它：UI 的「共 N 条」必须和列表源自同一判定，
      否则改一处忘一处 ⇒ 列表显示 20 条而总数说 0（或反过来）。
    """
    since = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
    return and_(
        scope_condition(CustomerReviewRecord, shop_id),
        CustomerReviewRecord.rating <= max_rating,
        CustomerReviewRecord.review_at >= since,
    )


async def list_recent_negative_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, limit: int = 20,
    days: int = 30, offset: int = 0,
) -> list[dict]:
    """列出本店铺近期的中差评（默认 ≤3 星、30 天内）。

    ★ `limit` 会截断 —— 界面要显示「共 N 条」请用 `count_recent_negative_reviews`，
      不要用 `len(items)`（那给出的是被截断后的数）。
    """
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(_recent_negative_condition(shop_id, max_rating, days))
        .order_by(CustomerReviewRecord.review_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
    )).scalars().all()
    return [_review_to_dict(r) for r in rows]


async def count_recent_negative_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: int = 3, days: int = 30,
) -> int:
    """本店近期的中差评**真实条数**（不受 `list_...` 的 limit 截断）。"""
    return int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord)
        .where(_recent_negative_condition(shop_id, max_rating, days))
    )).scalar_one())''',
    "抽出近期差评条件 + 补 count",
)

_write(SERVICE, svc)

# ---------------- router：补端点

rt = _read(ROUTER)

rt = sub(
    rt,
    "@router.get(\"/reviews/by-spu/{spu_id}\", summary=\"某个 SPU 名下的差评\")",
    '''@router.get("/reviews", summary="本店铺近期的中差评（工作台主列表）")
async def list_recent_reviews(
    max_rating: int = 3,
    days: int = 30,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """差评工作台的主列表 —— 「本店最近发生了哪些中差评」。

    ★ 为什么 endpoint 要补：`service.list_recent_negative_reviews` 此前只有
      Agent 工具一个调用点，HTTP 面没有出口 ⇒ 前端工作台拿不到差评清单，
      只能退而用「处置列表」（那只覆盖**已经处置过**的差评，历史差评全是 0
      处置 ⇒ 列表永远空白）。差评以**差评**为主语，处置以**处置**为主语，
      两者不可互相替代。

    - **total**: 真实条数（另行 count，不受 `limit` 截断）。
    - 缺 `X-Shop-ID` ⇒ 400，不返回空列表（本模块一律不提供「跨店汇总」这一档）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        items = await _guard(
            service.list_recent_negative_reviews, "读取近期差评", session, shop,
            max_rating=max_rating, days=days, limit=limit, offset=offset,
        )
        total = await _guard(
            service.count_recent_negative_reviews, "统计近期差评", session, shop,
            max_rating=max_rating, days=days,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/reviews/by-spu/{spu_id}", summary="某个 SPU 名下的差评")''',
    "router 补 /reviews 端点",
)

_write(ROUTER, rt)

# ---------------- __init__：导出 count

ini = _read(INIT)

ini = sub(
    ini,
    "    count_orphan_reviews, get_disposition, get_order_context,",
    "    count_orphan_reviews, count_recent_negative_reviews, get_disposition,\n"
    "    get_order_context,",
    "import 加 count_recent_negative_reviews",
)

ini = sub(
    ini,
    '    "list_reviews_for_spu", "list_orphan_reviews", "count_orphan_reviews",',
    '    "list_reviews_for_spu", "list_orphan_reviews", "count_orphan_reviews",\n'
    '    "count_recent_negative_reviews",',
    "__all__ 加导出",
)

_write(INIT, ini)

print("patched: service.py / router.py / __init__.py (reviews 出口)")

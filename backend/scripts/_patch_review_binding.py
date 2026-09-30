# -*- coding: utf-8 -*-
"""一次性补丁（第 289 轮）：给 trade 加「产品 ↔ 差评」软关联的两个出口。

★ 为什么走脚本而不是多 Edit：同一条消息里多个 Edit 会并发读同一份源，
  后写覆盖先写（本仓判据）。改成一次 str.replace 落盘，幂等键各自独立。
"""
from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SERVICE = BACKEND / "modules" / "trade" / "service.py"
INIT = BACKEND / "modules" / "trade" / "__init__.py"
ROUTER = BACKEND / "modules" / "trade" / "router.py"


def _read(p: Path) -> str:
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _write(p: Path, s: str) -> None:
    # ★ Windows 下 write_text 会把 LF 翻成 CRLF ⇒ 二进制写，行尾自己说了算
    p.write_bytes(s.encode("utf-8"))


def sub(src: str, old: str, new: str, label: str) -> str:
    """替换型判据：判 old 在不在（new 内嵌 old 时才会用错这把尺）。"""
    assert src.count(old) == 1, f"锚点不唯一或不命中：{label} -> hit={src.count(old)}"
    return src.replace(old, new, 1)


# ============================================================ service.py

svc = _read(SERVICE)

svc = sub(
    svc,
    "from sqlalchemy import String, and_, func, literal, select",
    "from sqlalchemy import String, and_, desc, func, literal, or_, select",
    "sqlalchemy import 行",
)

svc = sub(
    svc,
    "from modules.trade.db_model import (",
    "from modules.products import SkuRecord, SpuRecord\n"
    "from modules.trade.db_model import (",
    "products 门面导入",
)

NEW_BLOCK = '''

# ============================================================ 产品 ↔ 差评 关联
#
# ★ 为什么这套关联是「软」的（改这里之前请先读 `db_model.py` 的注释）
# ------------------------------------------------------------
# `customer_reviews.asin` / `.sku` **没有外键**指向 `skus` —— 它们是**平台侧
# 标识符**，不能因为本地产品库少一行就让差评插不进来（差评落库早于产品登记
# 是常态）。没有外键兜 ⇒ join 可能一行都匹配不上，而「匹配不上」有两种
# 语义完全不同的"空"：
#
#   A. 这个产品确实没有差评             —— 正常结论，可以显示「暂无差评」
#   B. 差评和产品**没能对上**（数据缺口）—— 显示「暂无差评」等于把缺口
#                                          伪装成「产品没问题」
#
# 这两种不能混成同一个空列表。下面两个函数把 `empty_state` 显式返回，
# 由界面分别播报（本仓：失败 / 缺口必须能归因）。
#
# ★ 为什么必须用 `distinct` 去重
# ------------------------------------------------------------
# 真库实测（探针 `scripts/probe_review_product_join.py`，输出落盘
# `out-probe-join.txt`）：同一个 ASIN 会挂在**多个 SKU、且分属多个 SPU** ——
# `('B0CXXXX009', 4, 4)` 表示 1 个 ASIN → 4 行 SKU → 4 个不同 SPU。
# 不去重 ⇒ SPU↔差评不是树形而是多对多：同一批差评被 4 个产品各认领一次，
# `count(*)` 虚增 4 倍，分页还会漏行（同一行在不同产品里占位不同）。


def _review_match_condition():
    """差评 ↔ SKU 的匹配条件 —— **唯一**口径，SPU 主查询与孤儿查询共用一份。

    ASIN 优先（平台内全局唯一）；ASIN 缺失时退回 `sku_code`。

    ★ 两侧都必须判非空：两边都是空串时 `"" == ""` 会让**所有**空 ASIN 的差评
      命中**所有**空 ASIN 的 SKU —— 那是把「没有登记」读成了「全店通用」。
      这类错误不报错，只会表现为「数量不对」，很难被发现。
    """
    return or_(
        and_(
            CustomerReviewRecord.asin != "",
            SkuRecord.asin != "",
            SkuRecord.asin == CustomerReviewRecord.asin,
        ),
        and_(
            CustomerReviewRecord.sku != "",
            SkuRecord.sku_code != "",
            SkuRecord.sku_code == CustomerReviewRecord.sku,
        ),
    )


def _rating_condition(max_rating: Optional[int]):
    """「算不算差评」的过滤条件。

    ★ `rating` 为 NULL 一律**算进来**：星都没拿到就说「不是差评」，
      那是把「未知」当成「好评」（本仓对静默退化一贯 fail-closed）。
    """
    if max_rating is None:
        return None
    return or_(
        CustomerReviewRecord.rating.is_(None),
        CustomerReviewRecord.rating <= max_rating,
    )


def _match_kind_of(review: CustomerReviewRecord, asins: set, codes: set) -> str:
    """这条差评是靠什么对上产品的 —— 界面要显示「命中 SKU / ASIN」。

    ★ 这里不用再查一次库：`asins` / `codes` 已经是本 SPU 名下 SKU 的解集，
      与 SQL 的 join 条件同源 ⇒ 不会漂移。再查一遍就是同一判定两份实现。
    """
    if (review.asin or "") and review.asin in asins:
        return "asin"
    if (review.sku or "") and review.sku in codes:
        return "sku_code"
    return "unknown"


async def list_reviews_for_spu(
    session: AsyncSession, shop_id: str, spu_id: str, *,
    max_rating: Optional[int] = None, limit: int = 50, offset: int = 0,
) -> dict:
    """列出「属于某个 SPU」的差评 —— SPU 只当**聚合壳**，真正的键在 SKU 上。

    ★ 为什么挂在 SPU 上是合理的，但**只能当壳**
      ------------------------------------------
      SPU「无 ASIN、不可售」（见 `modules/products/db_model.py` 文件头注释），
      而差评带的是 ASIN ⇒ 物理上只能 `spus.id → skus.spu_id → skus.asin`
      解出这个 SPU 名下的 ASIN 集合，再去匹配 `customer_reviews.asin`。
      界面侧同样成立：产品详情抽屉里 SPU 已经带了 SKU 子表，用户的心智是
      「看这个产品怎么样」，不是「看某个规格怎么样」。

    ★ 店铺作用域两处都要收窄（少一处就是跨租户读）
      ------------------------------------------
      `skus` 表**没有** `shop_id`，产品线只能经 `spus.shop_id` 定归属；
      差评自己另有一份 `shop_id`。两条都挂 ⇒ 否则「别家店的 SKU 与我店差评
      同名 ASIN」会把别家的评价拉进本店的产品详情。

    返回体里的 `empty_state`（**两种空态必须分开播报**）：
      - `"not_found"`         SPU 不存在 / 不属于本店（与「存在但没差评」是两件事）
      - `"no_sku"`            SPU 下还没登记 SKU
      - `"no_asin_binding"`   SKU 登记了但 ASIN / sku_code 全空 ⇒ **数据缺口**
      - `"no_reviews"`        关联得上，确实没有符合条件的评价 ⇒ **正常结论**
      - `None`                有数据
    """
    spu = (await session.execute(
        select(SpuRecord).where(and_(
            scope_condition(SpuRecord, shop_id),
            SpuRecord.id == spu_id,
        ))
    )).scalars().first()
    if spu is None:
        return {"found": False, "spu_id": spu_id, "reviews": [], "total": 0,
                "empty_state": "not_found", "asin_count": 0, "sku_count": 0}

    sku_rows = (await session.execute(
        select(SkuRecord.id, SkuRecord.asin, SkuRecord.sku_code,
               SkuRecord.spec_value)
        .where(SkuRecord.spu_id == spu_id)
    )).all()
    asins = {r.asin for r in sku_rows if (r.asin or "")}
    codes = {r.sku_code for r in sku_rows if (r.sku_code or "")}
    head = {
        "found": True, "spu_id": spu_id, "spu_title": spu.title,
        "reviews": [], "total": 0,
        "asin_count": len(asins), "sku_count": len(sku_rows),
        "asins": sorted(asins),
    }
    if not sku_rows:
        return {**head, "empty_state": "no_sku"}
    if not asins and not codes:
        # ★ 这里**不能**返回 "no_reviews"：SKU 都登记了却没有 ASIN，
        #   差评再怎么存在也 join 不上 —— 那是缺口，不是清白。
        return {**head, "empty_state": "no_asin_binding"}

    id_stmt = (
        select(CustomerReviewRecord.id)
        .join(SkuRecord, _review_match_condition())
        .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
        .where(and_(
            scope_condition(CustomerReviewRecord, shop_id),
            scope_condition(SpuRecord, shop_id),
            SpuRecord.id == spu_id,
        ))
        .distinct()
    )
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        id_stmt = id_stmt.where(rating_cond)

    # ★ 两趟而不是一条 DISTINCT + ORDER BY：PostgreSQL 要求 ORDER BY 的表达式
    #   出现在 SELECT DISTINCT 的列表里，直接在 id 上排序会被拒。
    #   先把 id 解成集合（去重发生在 SQL 侧），再按 id 取行做排序 / 分页。
    #   差评是本店的有限集合（远小于 SKU 量级），两次往返可接受。
    ids = list((await session.execute(id_stmt)).scalars().all())
    if not ids:
        return {**head, "empty_state": "no_reviews"}

    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(CustomerReviewRecord.id.in_(ids))
        .order_by(desc(CustomerReviewRecord.review_at))
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )).scalars().all()

    return {
        **head,
        "total": len(ids),
        "limit": limit, "offset": offset,
        "reviews": [
            _review_to_dict(r, match_kind=_match_kind_of(r, asins, codes))
            for r in rows
        ],
        "empty_state": None,
    }


async def count_orphan_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: Optional[int] = None,
) -> int:
    """统计本店「SKU 关联不上」的差评条数 —— 给两条路径共用的一个数。

    ★ 单独成函数而不是 `len(list_orphan_reviews(...))`：产品详情 tab 在
      「数据缺口」空态里要显示「本店还有 N 条差评没关联上产品」，
      为一个数拉 50 行明细没必要，且列表有分页上限 ⇒ 会数错。
    """
    conds = [scope_condition(CustomerReviewRecord, shop_id),
             _not_bound_to_sku(shop_id)]
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        conds.append(rating_cond)
    return int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord).where(*conds)
    )).scalar_one())


async def list_orphan_reviews(
    session: AsyncSession, shop_id: str, *, max_rating: Optional[int] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    """本店铺下「SKU 关联不上」的那批差评 —— P1 兜底列表。

    定义：既没有本店任何 SPU 名下 SKU 的 `asin` 等于它的 `asin`，
          也没有任何 SKU 的 `sku_code` 等于它的 `sku`。

    ★ 为什么必须单列
      ---------------
      软关联没有外键兜 ⇒ 关联不上的差评**不会出现在任何产品的差评 tab 里**，
      它们只是静默消失。而差评恰是最需要被看见的那批数据：界面上那句
      「这个产品 0 条差评」必须能被人验证到底是「真的没有」还是「没对上」。
      没有这张列表，「0 条」永远无法被证伪。
    """
    conds = [scope_condition(CustomerReviewRecord, shop_id),
             _not_bound_to_sku(shop_id)]
    rating_cond = _rating_condition(max_rating)
    if rating_cond is not None:
        conds.append(rating_cond)

    total = int((await session.execute(
        select(func.count()).select_from(CustomerReviewRecord).where(*conds)
    )).scalar_one())
    rows = (await session.execute(
        select(CustomerReviewRecord)
        .where(*conds)
        .order_by(desc(CustomerReviewRecord.review_at))
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
    )).scalars().all()

    return {
        "items": [_review_to_dict(r) for r in rows],
        "total": total, "limit": limit, "offset": offset,
        "empty_state": None if total else "no_orphans",
    }


def _not_bound_to_sku(shop_id: str):
    """「这条差评在本店产品库里没有任何 SKU 能认领它」—— 孤儿判定的唯一口径。

    ★ `correlate(CustomerReviewRecord)` 是必须的：不加相关，exists 子查询
      里的 `CustomerReviewRecord` 会被当成笛卡尔积展开，条件退化成
      「本店是否存在任意一条 SKU 能对上任意差评」⇒ 要么全孤儿要么全不孤儿。
      这类错误不报错，只表现为「要么 0 要么全表」。

    ★ `SpuRecord` 上的店铺条件不能省：`skus` 没有 `shop_id`，产品的归属
      只能经 `spus.shop_id` 这条链。省掉它 ⇒ 别家店的 SKU 也能认领本店差评，
      孤儿数被系统性低估（看起来"关联质量很好"）。
    """
    return ~(
        select(SkuRecord.id)
        .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
        .where(scope_condition(SpuRecord, shop_id))
        .where(_review_match_condition())
        .correlate(CustomerReviewRecord)
    ).exists()

'''

svc = sub(
    svc,
    "def _review_to_dict(r: CustomerReviewRecord) -> dict:\n    return {",
    NEW_BLOCK.lstrip("\n") + '''def _review_to_dict(
    r: CustomerReviewRecord, *, match_kind: Optional[str] = None,
    matched_sku_id: Optional[str] = None,
) -> dict:
    """评价的**唯一**序列化口径。

    ★ `match_kind` / `matched_sku_id` 回答「这条差评靠什么对上了产品」
      （界面要显示「命中 ASIN / SKU 码」）。不为此另起一个 `_review_card_dict`
      —— 那会让同一映射出现第二份实现，改一处漏一处。
    """
    return {''',
    "_review_to_dict 加可选参数",
)

svc = sub(
    svc,
    '        "buyer_name": r.buyer_name, "status": r.status, "source": r.source,\n    }',
    '        "buyer_name": r.buyer_name, "status": r.status, "source": r.source,\n'
    '        "matched_sku_id": matched_sku_id, "match_kind": match_kind,\n    }',
    "_review_to_dict 追加两键",
)

_write(SERVICE, svc)

# ============================================================ __init__.py

ini = _read(INIT)

ini = sub(
    ini,
    "    get_disposition, get_order_context, get_review_context, is_mock_source,",
    "    count_orphan_reviews, get_disposition, get_order_context,\n"
    "    get_review_context, is_mock_source,",
    "service import 列表（前半）",
)

ini = sub(
    ini,
    "    match_compensation_rule, propose_disposition, reject_disposition,\n    score_from_parts,\n)",
    "    list_orphan_reviews, list_reviews_for_spu,\n"
    "    match_compensation_rule, propose_disposition, reject_disposition,\n"
    "    score_from_parts,\n)",
    "service import 列表（后半）",
)

ini = sub(
    ini,
    '    "get_order_context", "get_review_context", "list_recent_negative_reviews",\n'
    '    "is_mock_source",',
    '    "get_order_context", "get_review_context", "list_recent_negative_reviews",\n'
    '    # ★ 产品 ↔ 差评 软关联（第 289 轮）：差评落在 SKU 上（SPU 只是聚合壳），\n'
    '    #   关联不上产品的那批必须有个兜底出口，否则它们只是静默消失。\n'
    '    "list_reviews_for_spu", "list_orphan_reviews", "count_orphan_reviews",\n'
    '    "is_mock_source",',
    "__all__ 导出",
)

_write(INIT, ini)

# ============================================================ router.py

rt = _read(ROUTER)

NEW_ROUTER = '''# ============================================================ 读：产品 ↔ 差评 关联
#
# ★ 这两个端点是同一个问题的两半：
#     左边 = 「某个产品名下有哪些差评」（产品详情的差评 tab）
#     右边 = 「哪些差评谁都没认领」（孤儿兜底列表）
#   只做一半 ⇒ 另一半静默丢失：软关联没有外键兜，join 不上不会报错，
#   只会变成一个谁也发现不了的 0。

@router.get("/reviews/by-spu/{spu_id}", summary="某个 SPU 名下的差评")
async def list_reviews_by_spu(
    spu_id: str,
    max_rating: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """产品详情「差评 tab」的数据源 —— **SPU 当聚合壳，键在 SKU 上**。

    - **max_rating**: 留空看全部星级，给 `3` 只看中差评（≤3 星，含星级缺失）。
    - **empty_state**: 界面必须按它分别播报 ——
      `no_reviews` 是「确实没有差评」（正常结论）；
      `no_asin_binding` / `no_sku` 是**数据缺口**（SKU 没登记 ASIN，
      差评再存在也关联不上）。把后者显示成「暂无差评」＝把缺口伪装成清白。

    ★ 同一个 ASIN 可能对应多个 SKU / 多个 SPU ⇒ 结果**已去重**，
      同一条差评不会被重复计数（真库实测：`B0CXXXX009` → 4 SKU / 4 SPU）。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.list_reviews_for_spu, "读取产品差评", session, shop, spu_id,
            max_rating=max_rating, limit=limit, offset=offset,
        )


@router.get("/reviews/orphans", summary="关联不上产品的差评（孤儿兜底列表）")
async def list_orphan_reviews(
    max_rating: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """本店境内无法通过 ASIN / SKU 码匹配到**本店**任何产品的差评。

    ★ 「本店」这三个字是口径的一部分：某个 ASIN 命中了**别家店**的 SKU，
      在本店视角里依然是孤儿 —— 直接用无店铺过滤的 join 会让孤儿数系统性
      偏低，看起来像"我们的关联质量很好"。
    """
    shop = _require_shop(store_id)
    async with async_session_factory() as session:
        return await _guard(
            service.list_orphan_reviews, "读取孤儿差评", session, shop,
            max_rating=max_rating, limit=limit, offset=offset,
        )


# ============================================================ 写：审批 / 驳回 / 发放'''

rt = sub(
    rt,
    "# ============================================================ 写：审批 / 驳回 / 发放",
    NEW_ROUTER,
    "router 新增两读端点",
)

_write(ROUTER, rt)

print("patched: service.py / __init__.py / router.py")

"""资料库通用查询 —— 执行内核（唯一实现）。

★ 本文件是「同一能力一份实现」的落点：6 个库的
  排序解析 / 过滤解析 / 去重 / 真实 count 全部走这里。
  任何一库若自己再写一遍 `order_by(...)`，就是本仓判据
  「同一判定两份实现 ⇒ 至少一份永远测不到」——由形态门禁钉住。

★ 为什么 query 与 count **必须共用** `_base_select` / `_dedup_key_expr`：
  第 216 轮实测过一次「列表 9 条、总数 11」的口径分裂
  （`count_all=9, approved=5, pending=5`，5+5=10 > 9）——
  根因正是「过滤放进去重子查询里 ⇒ 先筛后归并」。修法是先归并再筛，
  并把两条路径的 base query 收成同一个函数。计数若另写一份过滤口径，这种事还会再发生。
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select

from core.database import async_session_factory
from core.library_query.spec import LibraryQueryError, LibrarySpec
from core.tenant.scoping import scoped

__all__ = [
    "clamp_limit",
    "query_library",
    "count_library",
    "resolve_sort_clause",
    "resolve_filters",
]

#: 工具层默认返回条数 / 硬上限（模型上下文有限，列表类工具必须封顶）。
#: ★ 放内核而不是各库自己写：6 个库各写一遍就必然出现
#:   「这个库封顶 20、那个库封顶 100」的口径漂移。
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def clamp_limit(limit: Any, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    """把外部传入的 limit 归一到 `[1, maximum]`。

    ★ `None` / 空串 / 非数字都退回 `default`（不是抛错）：limit 的错法
      「值不合理」与「类型不对」对模型的处置完全一样 —— 用默认值继续，
      而把**真正会改变查询语义**的错（order_by / 过滤取值）留给显式报错。
    """
    try:
        n = int(limit) if limit is not None and str(limit).strip() else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, maximum))


def resolve_sort_clause(spec: LibrarySpec, order_by: Optional[str]):
    """把对外排序名解析成 SQLAlchemy 排序表达式；非法值**显式报错**。

    ★ 归一化口径：`None` / 空串 / 纯空白 = **不指定**（用 `spec.default_sort`），
      其余值去首尾空白后必须在白名单里。这是**有意选的边**，不是顺手：
      空串在 URL（`?order_by=`）与 LLM 出参里都是「没填」的自然表达，
      为它报错只会让模型去纠结一个不存在的错误。

    ★ 为什么是白名单而不是把参数直接透给 `order_by`：参数值来自 LLM（工具参数）
      与 URL（查询串）。`getattr(...)` 直接拼进 `order_by` 是一条**注入面**；
      而非法值若退化成默认排序，「按售价排」与「按更新时间排」在模型看来长得一样。
    """
    key = str(order_by).strip() if order_by is not None else ""
    if not key:
        key = spec.default_sort
    if key not in spec.sort_fields:
        raise LibraryQueryError(
            f"[{spec.key}] 不支持的排序维度 {order_by!r}；可选：{' / '.join(spec.sort_keys)}"
        )
    attr, direction = spec.sort_fields[key]
    col = getattr(spec.model, attr)
    return col.asc() if direction == "asc" else col.desc()


def resolve_filters(spec: LibrarySpec, filters: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """校验并归一化过滤参数，返回 `[(模型属性名, 归一化取值), ...]`。

    ★ 返回**属性名**而不是列对象：去重路径下过滤条件必须挂在子查询的列上
      （`sub.c.review_status`），非去重路径挂在模型列上。由调用方决定挂哪，
      但「哪个属性、什么值、值合不合法」这个判定只有这一份实现。
    """
    out: List[Tuple[str, str]] = []
    for name, value in (filters or {}).items():
        fs = spec.filters.get(name)
        if fs is None:
            raise LibraryQueryError(
                f"[{spec.key}] 不支持的过滤维度 {name!r}；"
                f"可选：{' / '.join(spec.filter_keys) or '（该库无过滤维度）'}"
            )
        if value is None:
            continue
        v = str(value).strip()
        if not v:
            # 空过滤值 = 「没填」⇒ 不筛（与排序维度同一口径）
            continue
        if fs.values is not None and v not in fs.values:
            raise LibraryQueryError(
                f"[{spec.key}] 过滤维度 {name!r} 不支持取值 {value!r}；"
                f"可选：{' / '.join(fs.values)}"
            )
        out.append((fs.attr, v))
    return out


def base_select(spec: LibrarySpec, shop_id: Optional[str]):
    """本库的 base query（已 join、已挂店铺作用域）—— query 与 count 共用。

    ★ `scoped()` 无条件挂过滤：`shop_id` 为 None 时 SQL 是 `col IS NULL`
      ⇒ 匹配不到任何行（安全失败方向：宁可查不到，不可查全部）。
      所以本函数**不做** `if shop_id:` 短路 —— 短路会让「忘了传归属」
      静默变成「查全库」，那正是跨租户泄露的形态。
    """
    stmt = select(spec.model, *spec.select_extra) if spec.select_extra else select(spec.model)
    for target, condition in spec.joins:
        stmt = stmt.join(target, condition)
    return scoped(stmt, spec.scope_model, shop_id)


def _dedup_order_clauses(spec: LibrarySpec) -> list:
    clauses = []
    for attr, direction in spec.dedup_order:
        col = getattr(spec.model, attr)
        clauses.append(col.desc() if direction == "desc" else col.asc())
    return clauses


def _deduped_subquery(spec: LibrarySpec, shop_id: Optional[str]):
    """按 `spec.dedup_key` 归并后的行集（带 `rn` 排名列）。

    ★ 去重键由 spec 提供（纯函数）—— 例如候选库是
      `CASE WHEN asin = '' THEN id ELSE asin END`：空 ASIN 是**合法缺省值**
      （面板手填允许不填），若一律按 `asin` 归并，一堆手填候选会塌成一条
      —— **那是丢数据，比重复更糟**。用 `id` 当空值的键 ⇒ 每行独占一个分区 ⇒ 恒被保留。

    ★ 用 `row_number()` 而不是 PG 专属的 `DISTINCT ON`：窗口函数是标准 SQL，
      换库（SQLite 跑单测 / 将来换存储）不至于重写。

    ★ 本函数**不带**任何业务过滤 —— 过滤是调用方的事，且必须在去重**之后**：
      若把过滤塞进来（先筛后归并），同一商品会在「pending」视图里保留 pending
      那条、在「approved」视图里保留 approved 那条 ⇒ 各状态条数之和大于 total。
    """
    ranked = base_select(spec, shop_id).add_columns(
        func.row_number()
        .over(
            partition_by=spec.dedup_key(spec.model),
            order_by=_dedup_order_clauses(spec),
        )
        .label("rn")
    )
    return ranked.subquery()


def _where_model(model: Any, pairs: List[Tuple[str, str]]) -> list:
    """把 `(属性名, 值)` 挂到**模型列**上（非去重路径）。"""
    return [getattr(model, attr) == value for attr, value in pairs]


def _where_columns(columns: Any, pairs: List[Tuple[str, str]]) -> list:
    """把 `(属性名, 值)` 挂到**子查询列**上（去重路径）。

    ★ 去重路径必须用子查询的列：`Model.review_status` 在 `WHERE` 里会指向
      **外层 FROM 的原始表**，而子查询是一个独立派生表 —— 那样过滤的是
      「原始表里状态匹配的行」而不是「归并后保留的那一行」，又回到
      「各状态条数之和 > total」的口径分裂。
    """
    return [columns[attr] == value for attr, value in pairs]


async def query_library(
    spec: LibrarySpec,
    shop_id: Optional[str],
    *,
    order_by: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> List[Any]:
    """按声明式 spec 查询资料库。

    ★ 参数校验**先于任何 DB 往返**：非法值必须报错，而不是回一个空列表
      （「真的没有」与「你传错了」被压成一种，是第 216 轮 ③ 要修的根因）。

    ★ Top-N 由 SQL 保证：`order_by` 与 `limit` **同时**给了，取到的才是
      「某维度的前 N」；只给 limit 拿到的是「默认维度的前 N」。
      改前的实现里 `limit` 一个人干两件事（分页 + Top-N 截断），
      于是「销量前 3」的真前 3 **从未进入候选集**（实测交集为空）。

    Args:
        spec: 库的声明式元数据。
        shop_id: **已校验归属**的店铺 ID。
        order_by: 对外排序名（见 `spec.sort_fields`）；None/空 = 默认排序。
        filters: `{对外过滤名: 取值}`；值域外的值**显式报错**。
        limit: 最多返回多少条（None = 不限）。
    Returns:
        SQLAlchemy `Row` 列表（每行首列是 `spec.model` 实例，其后是 `select_extra`）。
        **不做投影** —— 投影是每库特有的语义（字段不同），由调用方负责。
    Raises:
        LibraryQueryError: 排序维度 / 过滤维度 / 过滤取值不在值域内。
    """
    sort_clause = resolve_sort_clause(spec, order_by)
    pairs = resolve_filters(spec, filters)

    if not shop_id:
        # 无归属 ⇒ 空列表。与 REST 既有契约一致（前端「未选店铺看空列表」）。
        # ★ 调用方要**先**区分「没选店铺」与「店铺确实没数据」再回话 ——
        #   两者对老板的处置完全不同（去选店铺 / 去建数据）。
        return []

    async with async_session_factory() as session:
        if spec.dedup_key is None:
            stmt = base_select(spec, shop_id)
            for cond in _where_model(spec.model, pairs):
                stmt = stmt.where(cond)
            stmt = stmt.order_by(sort_clause, getattr(spec.model, spec.tie_breaker).asc())
            if limit:
                stmt = stmt.limit(int(limit))
            # ★ 第 346 轮：`Result.all()` 的静态类型是 `Sequence[Row[...]]`，
            #   而本函数注解收 `list[Any]`。运行期它本就是列表，`list()` 只是
            #   把契约写实（调用方按列表用：索引 / len / 迭代，行为不变）。
            return list((await session.execute(stmt)).all())

        sub = _deduped_subquery(spec, shop_id)
        stmt = (
            base_select(spec, shop_id)
            .join(sub, getattr(spec.model, "id") == sub.c.id)
            .where(sub.c.rn == 1)
        )
        # ★ 过滤发生在**去重之后** ⇒ 各过滤值下的条数之和 == 总数
        for cond in _where_columns(sub.c, pairs):
            stmt = stmt.where(cond)
        stmt = stmt.order_by(sort_clause, getattr(spec.model, spec.tie_breaker).asc())
        if limit:
            stmt = stmt.limit(int(limit))
        return list((await session.execute(stmt)).all())


async def count_library(
    spec: LibrarySpec,
    shop_id: Optional[str],
    *,
    filters: Optional[Dict[str, Any]] = None,
) -> int:
    """资料库**真实**条数（去重后、过滤后）—— 与 `query_library` **同口径**。

    ★ 为什么必须有它：工具层与 REST 此前普遍把 `total` 写成「返回了几条」
      （= `LIMIT` **之后**的长度）。本库 11 条时 `limit=1` 报 `total=1`
      ⇒ 老板问「评审通过的有几个」拿到的是**被截断的数**。
      小库看不出来，真实数据源几百条立刻失真。
    """
    pairs = resolve_filters(spec, filters)
    if not shop_id:
        return 0

    async with async_session_factory() as session:
        if spec.dedup_key is None:
            stmt = base_select(spec, shop_id)
            for cond in _where_model(spec.model, pairs):
                stmt = stmt.where(cond)
            total = (
                await session.execute(select(func.count()).select_from(stmt.subquery()))
            ).scalar()
        else:
            sub = _deduped_subquery(spec, shop_id)
            stmt = select(func.count()).select_from(sub).where(sub.c.rn == 1)
            for cond in _where_columns(sub.c, pairs):
                stmt = stmt.where(cond)
            total = (await session.execute(stmt)).scalar()
    return int(total or 0)

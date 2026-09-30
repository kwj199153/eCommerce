"""
候选选品库 - 业务逻辑层

把候选的**写入口**从 router 抽出，供两处复用：
  1. REST 路由：`POST /api/v1/candidates`
  2. 选品 Agent 的 `save_candidate` 工具（对话里「把这个品加进选品库」）

设计动因：原先唯一写入口是 REST 路由，Agent 想入库只能「HTTP 调自己」，
于是「保存到选品库」长期只是前端卡片上的一个按钮，**对话完全够不到**。
把写逻辑下沉到 service 后，路由与 Agent 工具共用同一条路径与同一套默认值。

★ 第 216 轮：读口（`list_candidates`）也收口成**通用查询**，动因是老板问
  「换成真正的数据源还通用吗？换问法（售价前 5 / 评审通过）还能查吗」——
  实测暴露三处结构性不通用（`limit` 兼表分页与 Top-N、`total` 是截断后长度、
  过滤值域只写在 docstring 里），逐条修在下方「通用查询的三个真源」段。
"""

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import case, select

from core.database import async_session_factory
from core.library_query import (
    FilterSpec,
    LibraryQueryError,
    LibrarySpec,
    count_library,
    query_library,
)
from core.tenant.scoping import scoped
from modules.candidates.db_model import CandidateRecord


# ====== 字段契约（与前端选品库面板严格对齐）======
#
# 面板是「手动录入候选选品」弹窗 + 蓝海结果卡的「保存到选品库」：
#   - 必填：ASIN、标题（弹窗上的 required 标记）
#   - 可选：售价 / 预估月销 / 蓝海评分 / ROI / 备注 —— 不填就用默认值
#   - 蓝海链路唯一要人操作的「选分组」是可选项，不选也能入库
#
# 对话入库是同一套流程的「免填版」：
#   - 必填缺失 → **多轮追问补齐**（缺什么问什么）
#   - 可选缺失 → **后台按默认值自动补**，不为可选字段打扰老板
# 所以必填清单必须单点定义在这里，别再让前后端各记一份。

CANDIDATE_REQUIRED_FIELDS = ("asin", "title")

# 字段中文名：追问文案给老板看，别把 `asin` 这种字段名直接甩出去
CANDIDATE_FIELD_LABELS = {
    "asin": "ASIN",
    "title": "商品标题",
    "price": "售价(USD)",
    "estimated_monthly_sales": "预估月销",
    "blue_ocean_score": "蓝海评分",
    "roi_estimated": "ROI 估算(%)",
    "notes": "备注",
}


def missing_required_fields(payload: dict) -> list:
    """
    返回 payload 里缺失的必填字段（对齐面板 required）。

    可选字段一律不算缺 —— 面板对可选字段就是「不填走默认值」，
    对话入库同样由 `build_candidate_record` 补默认值，不该为此打扰用户。
    """
    missing = []
    for field in CANDIDATE_REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing


def describe_missing_fields(missing: list) -> str:
    """缺失字段 → 中文提示（如「ASIN、商品标题」）"""
    return "、".join(CANDIDATE_FIELD_LABELS.get(f, f) for f in missing)


def record_to_dict(r: CandidateRecord) -> dict:
    """ORM → dict（字段名与前端 CandidateItem 对齐）"""
    return {
        "id": r.id,
        "asin": r.asin,
        "sku": r.sku,
        "title": r.title,
        "brand": r.brand,
        "category": r.category,
        "sub_category": r.sub_category,
        "price": r.price,
        "currency": r.currency,
        "site": r.site,
        "estimated_monthly_sales": r.estimated_monthly_sales,
        "review_count": r.review_count,
        "rating": r.rating,
        "bsr": r.bsr,
        "bsr_category": r.bsr_category,
        "listed_date": r.listed_date,
        "roi_estimated": r.roi_estimated,
        "margin": r.margin,
        "blue_ocean_score": r.blue_ocean_score,
        "overall_listing_score": r.overall_listing_score,
        "keywords": r.keywords or [],
        "competitor_asins": r.competitor_asins or [],
        "selling_points": r.selling_points,
        "main_image": r.main_image,
        "images": r.images or [],
        "source": r.source,
        "review_status": r.review_status,
        "review_notes": r.review_notes,
        "reviewed_at": r.reviewed_at,
        "reviewed_by": r.reviewed_by,
        "monitor_data": r.monitor_data,
        "last_monitored_at": r.last_monitored_at,
        "shop_id": r.shop_id,
        "tags": r.tags or [],
        "notes": r.notes,
        "groups": r.groups or [],
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def build_candidate_record(payload: dict, shop_id: Optional[str] = None) -> CandidateRecord:
    """
    由 payload 构造 CandidateRecord（不落库）。

    payload 字段**全部可选**，缺省值在此集中收敛，避免出现
    「路由填一套默认值、Agent 工具填另一套」的语义分裂。
    """
    now = datetime.utcnow().isoformat()
    cid = payload.get("id") or f"cand-{int(datetime.utcnow().timestamp() * 1000)}"

    return CandidateRecord(
        id=cid,
        asin=payload.get("asin") or "",
        sku=payload.get("sku") or f"SKU-CAND-{cid}",
        title=payload.get("title") or "未命名候选",
        brand=payload.get("brand") or "",
        category=payload.get("category") or "other",
        sub_category=payload.get("sub_category") or "",
        price=payload.get("price") or 0,
        currency=payload.get("currency") or "USD",
        site=payload.get("site"),
        estimated_monthly_sales=payload.get("estimated_monthly_sales") or 0,
        review_count=payload.get("review_count") or 0,
        rating=payload.get("rating") or 0,
        bsr=payload.get("bsr"),
        bsr_category=payload.get("bsr_category"),
        listed_date=payload.get("listed_date"),
        roi_estimated=payload.get("roi_estimated") or 0,
        margin=payload.get("margin") or 0,
        blue_ocean_score=payload.get("blue_ocean_score") or 0,
        overall_listing_score=payload.get("overall_listing_score"),
        keywords=payload.get("keywords") or [],
        competitor_asins=payload.get("competitor_asins") or [],
        selling_points=payload.get("selling_points"),
        main_image=payload.get("main_image") or "",
        images=payload.get("images") or [],
        source=payload.get("source") or "blue_ocean",
        review_status=payload.get("review_status") or "pending",
        review_notes=payload.get("review_notes") or "",
        reviewed_at=payload.get("reviewed_at"),
        reviewed_by=payload.get("reviewed_by"),
        monitor_data=payload.get("monitor_data"),
        last_monitored_at=payload.get("last_monitored_at"),
        shop_id=shop_id or payload.get("shop_id") or "",
        tags=payload.get("tags") or [],
        notes=payload.get("notes") or "",
        groups=payload.get("groups") or [],
        created_at=payload.get("created_at") or now,
        updated_at=now,
    )


async def find_candidate_by_asin(asin: str, shop_id: Optional[str]) -> Optional[dict]:
    """
    该店铺下同 ASIN 的候选，**取最新一条**（没有则 `None`）。

    用途：判重。改前这个能力叫 `candidate_exists`（只回 bool），
    于是调用方拿到「已存在」之后**无法告诉用户是哪一条**，也无法把那条
    回给模型；现在直接回记录本身，判重与「回执指向哪条」用同一个查询。

    ★ 第 216 轮：它**只被 `create_candidate` 调用**（判重唯一实现收口在那里）。
      改前它是个**孤儿** —— 只在选品 Agent 那一条写路径上被调用，
      而自称「唯一写入口」的 `create_candidate` 内部不判重、
      REST `POST /candidates` 完全无判重 ⇒ 重复数据还在继续长。

    注意：`shop_id` 为空时一律返回 `None`（不做跨店铺判重）——
    没有租户上下文时无从判断归属，宁可写入也不要误判为「已存在」而丢数据。
    """
    if not asin or not shop_id:
        return None
    async with async_session_factory() as session:
        row = (await session.execute(
            scoped(select(CandidateRecord), CandidateRecord, shop_id)
            .where(CandidateRecord.asin == asin)
            .order_by(CandidateRecord.updated_at.desc(), CandidateRecord.id.desc())
            .limit(1)
        )).scalar_one_or_none()
    return record_to_dict(row) if row is not None else None


async def create_candidate(
    payload: dict,
    shop_id: Optional[str] = None,
    on_duplicate: str = "allow",
) -> dict:
    """
    新增候选（**唯一写入口**，判重也在这里 —— 唯一判重实现）。

    Args:
        on_duplicate: 同店铺同 ASIN 已在库时的行为（**必须显式选边**）。
            · `"allow"`（默认）—— 照旧插入。**REST `POST /api/v1/candidates`
              走这一档，响应逐字不变**：面板是人工显式录入，
              重复可能是刻意的，替老板「顺手判重」等于替他做决定。
            · `"skip"` —— 不插入，返回**已存在的那条**并附 `"deduped": True`。
              选品 Agent 的 `save_candidate` 走这一档（对话里重复说
              「把这个品加进选品库」不该累积重复行）。
    Returns:
        落库后的候选 dict（字段名与前端 CandidateItem 对齐）；
        `on_duplicate != "allow"` 时**恒带** `"deduped": bool`
        （恒有该键 ⇒ 消费方不必用「有没这个键」来表达两种语义）。
    Raises:
        CandidateQueryError: `on_duplicate` 不在 `DUPLICATE_POLICIES` 里。

    ★ 第 216 轮：判重**收口到这里**。改前是「一份实现挂错地方」——
      `candidate_exists`（docstring 写着「避免累积重复行」）只在 Agent 那一条
      写路径上被调用，而本函数自称「唯一写入口」内部却不判重、
      REST `POST /candidates` 完全无判重 ⇒ 重复数据还在继续长
      （第 216 轮实测：库里 `B0CXXXX009` 三条、`B0KLMN3456` 三条）。
    """
    if on_duplicate not in DUPLICATE_POLICIES:
        raise CandidateQueryError(
            f"不支持的判重策略 {on_duplicate!r}；可选：{' / '.join(DUPLICATE_POLICIES)}"
        )
    record = build_candidate_record(payload, shop_id=shop_id)

    if on_duplicate == "skip":
        existing = await find_candidate_by_asin(record.asin, shop_id)
        if existing is not None:
            return {**existing, "deduped": True}

    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)

    return {**record_to_dict(record), "deduped": False}


#: 评审状态合法取值（与 `CandidateRecord.review_status` 的注释一致）。
#:
#: ★ 第 216 轮：它同时是**读口过滤**的值域真源 —— `list_candidates` 拿它校验
#:   `review_status`，非法值**显式报错**。改前合法值只写在 docstring 里
#:   （`args_schema` 无 `enum`）⇒ 传「通过」「APPROVED」静默回**空列表**，
#:   「真的没有」与「你传错了」被压成同一个结果（归因错方向）。
REVIEW_STATUSES = ("pending", "under_review", "approved", "rejected")

# ====== 候选库「通用查询」的三个真源（第 216 轮）======
#
# 动因（老板原话）：「换成真正的数据源的数据，也能很好地工作吗？是否具有通用性？
# 换个问法，而不是预估销量前 3，而是售价前 5、评审状态通过的产品等等，
# 对这个数据的查询能否正常」。
#
# 第 216 轮实测（probes/216b_generic_query_probe.py + 216b_contract_probe.py）
# 暴露三处**结构性不通用** —— 小库看不出来，换真数据源立刻爆发：
#
#   ① `limit` 一个人干两件事（分页 + Top-N 截断）。SQL 先按 `updated_at`
#      截断，再让模型自己重排 ⇒ 「销量前 3」的**真前 3 从未进入候选集**
#      （实测手牌 `[009(560), 009(560), 007(750)]` vs 真前 3
#      `[006(3200), 004(2100), 005(1800)]`，**交集为空**）；
#      「售价前 5」同型复现。
#      ⇒ 排序必须由 SQL 保证，`order_by` 必须**显式暴露**给读口。
#   ② `total` 口径 = `LIMIT` **之后**的长度 ⇒ 模型答「评审通过有几个」时
#      给的是被截断的数（本库 11 条时 `list_candidates(limit=1)` 报 `total=1`）。
#   ③ 过滤维度的合法值只写在 docstring 里 ⇒ 传近义词静默回空（见上）。
#
# ⇒ 本段各收口成一个真源：**白名单**（排序）/ **真实总数**（count）/ **显式报错**（值域）。

#: 排序维度白名单 —— **唯一真源**。
#:
#: · key   = **对外契约名**：REST 查询参数 / 工具参数 / 前端 `sortBy` **三名一体**
#:   （前端 `components/KnowledgeBase/CandidateLibrary.vue` 的排序下拉与
#:   `stores/candidateLibrary.ts` 的 `sortBy` 分支必须与它**逐字相同**，
#:   由 `frontend/scripts/check-agent-sort-parity.cjs` 做三方对齐门禁）。
#: · value = `(Mapper 属性名, 缺省方向)`。用**属性名字符串**而不是列对象，
#:   是为了让门禁能「**按属性名相等**」核对它真的存在于 `CandidateRecord`
#:   —— 本仓铁律：判据禁「源码字符串包含」（会被同族更长标识符顶掉）。
#:
#: ★ 为什么是白名单，而不是把参数直接透给 `order_by`：
#:   参数值来自 LLM（工具参数）与 URL（查询串）。`getattr(...)` 直接拼进
#:   `order_by` 是一条**注入面**；而非法值若退化成默认排序，
#:   「按售价排」与「按更新时间排」在模型看来长得一样（归因错方向）。
CANDIDATE_SORT_FIELDS = {
    "updated_at": ("updated_at", "desc"),
    "blue_ocean_score": ("blue_ocean_score", "desc"),
    "roi": ("roi_estimated", "desc"),
    "sales": ("estimated_monthly_sales", "desc"),
    "rating": ("rating", "desc"),
    "price": ("price", "desc"),
}

#: 白名单键序（= 报错文案里的可选值顺序）。
CANDIDATE_SORT_KEYS = tuple(CANDIDATE_SORT_FIELDS)

#: 缺省排序 —— 与前端 `sortBy` 初值、REST 既有契约一致（最新更新在前）。
DEFAULT_SORT_FIELD = "updated_at"

#: `create_candidate` 的判重策略取值（**显式选边**，不给隐式默认行为）。
DUPLICATE_POLICIES = ("allow", "skip")


#: 候选库参数非法异常 —— **内核异常的别名**（同一判定一份实现）。
#:
#: ★ 为什么要有**专属异常**：两个消费者要给出**不同形态**的「人话」，
#:   但判定必须是**同一份实现**——
#:     · REST（`router.py`）→ `HTTPException(400, detail=...)`
#:     · 工具（`library/tools.py`）→ `{"type": "invalid_argument", ...}`，
#:       模型据此**改参数重试**（而不是把它转述成「读取失败」）
#:
#: ★ 第 218 轮：读口搬进 `core/library_query` 后，抛出的就是内核的
#:   `LibraryQueryError`。这里保留专用名，因为既有消费方（REST、工具层、
#:   3 个测试文件）都写 `except CandidateQueryError` / `pytest.raises(...)`。
#:   ★ 必须是**同一个类**，不能是「新建一个派生自它的子类」：
#:     读口抛的是父类实例 ⇒ `pytest.raises(CandidateQueryError)` **抓不住**
#:     ⇒ 那些用例不是变红，而是**异常穿透**（非红非绿，最难查）。
CandidateQueryError = LibraryQueryError


#: 候选库的**声明式元数据**（唯一真源）。
#:
#: ★ 第 218 轮：执行机制（排序白名单 / 过滤值域 / 去重 / limit / 真实 count）
#:   全部上提到 `core.library_query`，本库成为它的**第一个调用方**。
#:   动因是「换成真数据源还通用吗」这一问的后续实测：同样的三处结构性缺陷
#:   在其余 5 个库原样存在 —— 修法是抽执行内核，而不是把本库那套复制 6 份
#:   （复制 6 份等于把上一轮踩过的坑再踩 6 遍）。
#:   本文件现在只剩**投影**（`record_to_dict` 那 40 个字段）与**写入**。
#:
#: ★ 排序白名单仍以 `CANDIDATE_SORT_FIELDS` 字面量形式保留在下方 ——
#:   跨端对齐门禁（`frontend/scripts/check-agent-sort-parity.cjs`）要从这里
#:   正则解析出 `"sales": ("estimated_monthly_sales", "desc")` 形态。
#:   换成「引用 spec.sort_fields」会让那道门禁的锚点失效
#:   （它会 FAIL 而不是静默放行 —— 但没必要让门禁白红一次）。
CANDIDATE_SPEC = LibrarySpec(
    key="candidates",
    label="选品库",
    model=CandidateRecord,
    sort_fields=CANDIDATE_SORT_FIELDS,
    default_sort=DEFAULT_SORT_FIELD,
    filters={"review_status": FilterSpec("review_status", REVIEW_STATUSES)},
    # 去重键 = `CASE WHEN asin = '' THEN id ELSE asin END`：
    # 空 ASIN 是 `build_candidate_record` 的**合法缺省值**（面板手填允许不填），
    # 若一律按 `asin` 归并，一堆手填候选会塌成一条 —— **那是丢数据，比重复更糟**。
    # 用 `id` 当空 ASIN 的键 ⇒ 每一行独占一个分区 ⇒ 恒被保留。
    dedup_key=lambda M: case((M.asin == "", M.id), else_=M.asin),
)


async def list_candidates(
    shop_id: Optional[str],
    limit: Optional[int] = None,
    review_status: Optional[str] = None,
    order_by: Optional[str] = None,
) -> List[dict]:
    """候选列表（**唯一实现**）。

    ★ 第 205 轮收口：此前「读候选库」只有 REST 路由里那一份查询，
      而跨 Agent 共用的 `list_candidates` 工具没有落脚点
      ⇒ 若各自实现，就是「同一判定两份实现 ⇒ 至少一份永远测不到」。
      现在两个消费者共用一个函数：

        1. REST：`modules/candidates/router.py`（`GET /api/v1/candidates`）
        2. 工具：`modules/library/tools.py` 的 `list_candidates`
           （选品分析师与店秘书**共用同一个工具**，见 `SHARED_TOOL_AGENTS`）

    Args:
        shop_id: **已校验归属**的店铺 ID（来自 `get_current_shop_id*`）。
        limit: 最多返回多少条（None = 不限）。
        review_status: 只看某个评审状态（None = 全部）；非法值**报错**。
        order_by: 排序维度（见 `CANDIDATE_SORT_FIELDS`）。
            **None / 空串 / 不传 = `updated_at` 倒序**（与改前契约逐字一致 ⇒
            前端「最新在前」不会静默变样）；非法值**报错**，不静默退化。

    Returns:
        候选 dict 列表（按 `order_by` 倒序，同值以 `id` 兜底保证确定性）。

    Raises:
        CandidateQueryError: `order_by` / `review_status` 不在值域内。

    ★ 第 216 轮两处行为变更（都是**修 bug**，不是加料）：
      1. **Top-N 由 SQL 保证**：加 `order_by` 后「销量前 3」才真的取到前 3。
         改前 `limit=3` 只能表达「拿 3 条『最新更新』的」，模型再自己重排，
         真前 3 从未进入候选集（实测交集为空）。**截断口径 ≠ 排序口径。**
      2. **读口按 ASIN 去重**（老板原话「第二个和第三个实际上是同一个产品」）：
         同店同 ASIN 只留 `updated_at` 最新的那一条。
    """
    # 参数校验**先于任何 DB 往返**：非法值必须报错而不是回一个空列表
    # （空结果的两种语义被压成一种，是第 216 轮 ③ 要修的根因）。
    #
    # ★ 第 218 轮：查询本体搬进 `core.library_query.query_library` —— 排序
    #   白名单 / 过滤值域 / 去重 / limit 全在那**一个内核**里。本函数只剩
    #   **投影**（候选特有的 40 字段 dict）：投影是每库特有的语义（字段不同），
    #   不属于可收敛的机制；而查询若也留在这里，就是「6 个库各写一份执行逻辑」。
    rows = await query_library(
        CANDIDATE_SPEC,
        shop_id,
        order_by=order_by,
        filters={"review_status": review_status},
        limit=limit,
    )
    return [record_to_dict(row[0]) for row in rows]


async def count_candidates(
    shop_id: Optional[str],
    review_status: Optional[str] = None,
) -> int:
    """候选**真实**条数（去重后、过滤后）—— 与 `list_candidates` **同口径**。

    ★ 为什么必须有它：工具层与 REST 此前都把 `total` 写成「返回了几条」
      （= `LIMIT` **之后**的长度）。本库 11 条时 `list_candidates(limit=1)`
      报 `total=1` ⇒ 老板问「评审通过的有几个」拿到的是**被截断的数**。
      小库看不出来，真实数据源几百条立刻失真。
    ★ 与 `list_candidates` **共用内核的同一个 base query**（`base_select` /
      `_deduped_subquery`，见 `core/library_query/executor.py`）：
      计数若另写一份过滤/去重口径，「列表 9 条、总数 11」这种事就会再次发生。

    Args:
        shop_id: **已校验归属**的店铺 ID。
        review_status: 只数某个评审状态（None = 全部）；非法值**报错**。
    Raises:
        CandidateQueryError: `review_status` 不在 `REVIEW_STATUSES` 里。
    """
    # ★ 与 `list_candidates` **同一口径**：两者都走内核，内核内部共用同一个
    #   base query（`library_query.executor.base_select` / `_deduped_subquery`）。
    #   计数若另写一份过滤/去重口径，「列表 9 条、总数 11」这种事就会再次发生
    #   —— 第 216 轮实测过（`count_all=9, approved=5, pending=5`，5+5=10 > 9）。
    return await count_library(
        CANDIDATE_SPEC, shop_id, filters={"review_status": review_status}
    )

# ====== 候选生命周期流转（第 205 轮 · 从 router 下沉）======
#
# ★ 为什么这三条必须下沉：第 204 轮盘点出「原子级工具缺口 20 条」，其中
#   `get_candidate` / `review_candidate` / `approve_candidate` 在
#   `router.py` 里**只有内联实现**（`async_session_factory()` 直接写在 handler
#   体里）。工具层**无法**复用 handler：跨模块 import `router` 会同时踩破两条
#   既有门禁 ——
#     ① 门面包契约（只允许 `from modules.X import <name>`，且 `<name>` ∈ `__all__`）；
#     ② 分层表（`tests/test_module_layering.py` 禁 `PLUGIN → PLUGIN` 顶层 import）。
#   ⇒ 下沉后「REST 路由」与「Agent 工具」共用**同一条**路径与同一套归属过滤，
#   否则就是本仓判据「同一判定两份实现 ⇒ 至少一份永远测不到」。

#: 「没传」哨兵 —— 与 `None` 区分开：`review_notes=None` 是「把它改成空」，
#: `_UNSET` 才是「别动这个字段」。REST 既有语义靠 `"k" in payload` 实现，
#: 用 `None` 当默认值会把这个区别抹掉（静默改动契约）。
_UNSET: Any = object()


async def _load_scoped(session, candidate_id: str, shop_id: Optional[str]):
    """取**归属内**的候选记录；「不存在」与「不属于你」返回同一个 `None`。

    ★ 两者必须同一出口：否则可以拿 id 逐个试探，把「存在但不属于我」与
      「不存在」区分开 ⇒ 可枚举别人的 `candidate_id`。
    """
    q = select(CandidateRecord).where(CandidateRecord.id == candidate_id)
    # ★★★ 无条件挂店铺作用域（第 283 轮 P0 修复 · 读越权）
    #   此前是 `if shop_id:` —— `get_candidate`（GET）缺 `X-Shop-ID` 时
    #   `get_current_shop_id` 返回 None（400 空值守卫**只**拦写方法，
    #   `WRITE_METHODS` = POST/PUT/PATCH/DELETE，**不含 GET**）
    #   ⇒ 店铺条件整个不发 ⇒ 凭 candidate_id 可读**任意租户**的候选详情。
    #   现在 None ⇒ `shop_id IS NULL` ⇒ 0 行 ⇒ None ⇒ 上游 404。
    q = scoped(q, CandidateRecord, shop_id)
    return (await session.execute(q)).scalar_one_or_none()


async def get_candidate(candidate_id: str, shop_id: Optional[str]) -> Optional[dict]:
    """候选详情（**唯一实现**）。

    Args:
        candidate_id: 候选 ID。
        shop_id: **已校验归属**的店铺 ID。★ 它**没有默认值**是有意的
            （本仓判据「签名即门禁」）：调用方必须显式交代归属从哪来，
            禁掉「忘了传 ⇒ 静默不过滤 ⇒ 跨租户读到别人的候选」。
            传 `None` = **查不到任何行**（`shop_id IS NULL` ⇒ 0 行 ⇒ 404），
            不是「不过滤」。★ 第 283 轮修正：原文把「REST 路由缺 X-Shop-ID 时
            沿用既有语义」写成了合法用法，而那条既有语义正是「读到别人的候选」
            —— 一段把缺陷当设计写进契约的注释，是最难被发现的那类漏洞。
            工具层仍然必须传真值（拿不到店铺时**硬拒绝**，
            见 `product_research/tools.py`）。

    Returns:
        候选 dict；不存在 / 不属于本店铺 ⇒ `None`（两者同一出口）。
    """
    async with async_session_factory() as session:
        r = await _load_scoped(session, candidate_id, shop_id)
    return record_to_dict(r) if r is not None else None


async def review_candidate(
    candidate_id: str,
    shop_id: Optional[str],
    review_status: Any = _UNSET,
    review_notes: Any = _UNSET,
    reviewed_by: Any = _UNSET,
) -> Optional[dict]:
    """评审状态流转（**唯一实现**）：淘汰 / 转评审中 / 退回待评审。

    ★ 与 `approve_candidate` 的分工：本条**只改评审标记**，不碰产品库；
      「入产品库」是 `approve_candidate` 的职责（候选 → 产品的**唯一通道**）。
      两条都会写库 ⇒ 工具层都声明 `SIDE_EFFECT_METADATA`，
      由 `BaseAgent._wrap_hitl_tools()` 按 `has_side_effects()` **自动**包审批
      （业务侧没有手写名单可漏）。

    Args:
        review_status: 只接受 `REVIEW_STATUSES` 的取值；非法值**静默忽略**
            （沿用 REST 既有契约：非法状态不改动，而不是报 500）。
        review_notes / reviewed_by: `_UNSET` = 不动该字段。
    Returns:
        流转后的候选 dict；不存在 / 不属于本店铺 ⇒ `None`。
    """
    async with async_session_factory() as session:
        r = await _load_scoped(session, candidate_id, shop_id)
        if r is None:
            return None

        if review_status is not _UNSET and review_status in REVIEW_STATUSES:
            r.review_status = review_status
        if review_notes is not _UNSET:
            r.review_notes = review_notes
        if reviewed_by is not _UNSET:
            r.reviewed_by = reviewed_by
        r.reviewed_at = datetime.utcnow().isoformat()
        r.updated_at = r.reviewed_at
        await session.commit()
        await session.refresh(r)
    return record_to_dict(r)


async def approve_candidate(
    candidate_id: str,
    shop_id: Optional[str],
    product_id: Optional[str] = None,
) -> Optional[dict]:
    """评审通过 = **候选 → 自有产品库的唯一通道**（**唯一实现**）。

    语义（与 REST 端点**逐字一致**，不许在这一步加料）：
      · 在 `products` 库建一条 `status='draft'` 的 **SPU 草稿**（不预建 SKU，
        运营后续在产品库内补 SKU；SPU 无 ASIN、不可售）；
      · 候选**保留**并标记 `approved`，作为**不可覆盖的原始评估基线**；
      · 两步在**同一事务**里（原子）。

    ★ 为什么这是 P0：第 204 轮实测，「入产品库」是老板点名的四条之一，
      而全仓唯一实现就在 REST handler 里 ⇒ Agent 够不着，
      **选品闭环在 Agent 侧直接断掉**（能评估、能入候选库、就是进不了产品库）。
    ★ 为什么跨模块 import 写在**函数内**：`modules.products` 门面会连带拉起
      `products/router.py`（该代价已记在门面 docstring）。放到模块顶层会让
      `import modules.candidates` 顺带装配 FastAPI 组件，也给未来留成环的机会。
      `candidates` 与 `products` 同为 SHARED 层，方向合法（分层表允许 SHARED → SHARED）。

    Args:
        product_id: 指定落库的 SPU id；不传则按时间戳生成。
    Returns:
        `{"message", "candidate_id", "product"}`；不存在 / 不属于本店铺 ⇒ `None`。
    """
    from modules.products import SpuRecord, spu_to_dict

    async with async_session_factory() as session:
        r = await _load_scoped(session, candidate_id, shop_id)
        if r is None:
            return None

        # 从候选推导 ROI（候选没填就用 20 作展示值，与 REST 既有口径一致）
        roi = r.roi_estimated or 20

        now = datetime.utcnow().isoformat()
        spu_id = product_id or f"spu-{int(datetime.utcnow().timestamp() * 1000)}"
        # 选品阶段评估的是整个主产品（SPU）：审核通过后入库为「SPU 草稿」，
        # 不预建 SKU，运营后续在产品库内补 SKU。SPU 无 ASIN、不可售。
        product = SpuRecord(
            id=spu_id,
            title=r.title,
            brand=r.brand,
            category=r.category,
            sub_category=r.sub_category,
            spu_theme=None,
            keywords=r.keywords or [],
            selling_points=r.selling_points,
            description=None,
            main_image=r.main_image,
            images=r.images or [],
            spu_common={
                "brand": r.brand,
                "category": r.category,
                "keywords": r.keywords or [],
                "selling_points": r.selling_points or "",
                "bullets": [],
                "a_plus": None,
            },
            shop_id=r.shop_id,
            tags=(r.tags or []) + ["蓝海挖掘", f"评分:{r.blue_ocean_score}", "SPU主产品"],
            notes=f"来源：候选选品库评审通过（SPU 主产品）| 蓝海评分：{r.blue_ocean_score} | 预估月销：{r.estimated_monthly_sales} | ROI：{roi}% | 请在产品库补充 SKU",
            status="draft",
            groups=r.groups or [],
            created_at=now,
            updated_at=now,
        )
        session.add(product)
        # 评审通过：保留候选作为「原始评估基线」存档（不再删除），标记 approved，
        # 与自有产品库的上架档案形成双库并存：选品库=评估基线，产品库=上架物料基线
        r.review_status = "approved"
        r.reviewed_at = now
        r.updated_at = now
        await session.commit()

        # ★ 在 session 存活期内就把 SPU 转成 dict（第 271 轮 P2-2）：
        #   改前 `spu_to_dict(product)` 在 `async with` 之外调用，product 是已
        #   detach 的 ORM 对象 —— commit 后 session 已 close，若未来 `spu_to_dict`
        #   访问了 lazy-load 字段会抛 `DetachedInstanceError`，且此刻 SPU 已提交、
        #   重试会重复建 SPU（spu_id 由时间戳重算）。
        #   提前转 dict 把「ORM 访问」收进 session 生命周期，杜绝这个窗口。
        product_dict = spu_to_dict(product)

    # SPU → dict 的唯一真源已收进 products 包门面（跨模块一律走门面，勿取内部文件）
    return {
        "message": "评审通过，已复制到自有产品库，候选保留为已通过评估基线",
        "candidate_id": candidate_id,
        "product": product_dict,
    }

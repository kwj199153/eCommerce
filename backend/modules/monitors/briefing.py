"""每日经营简报 —— **生成核**（第 371 轮）

==============================================================================
★ 这个模块补的是链路里**缺失的那一段**
==============================================================================
竞品监控此前是一条「有数据、有界面、但没人主动告诉你」的链路：

    ① 采集    ✅ `monitors` 表有当刻快照与 7 维时序（价格 / BSR / 评论 / 变体 / Listing）
    ② 判定    ✅ `MonitorRecord` 上已有 `price_change_7d` / `stock_status` /
                `reviews_added_7d` / `bsr_change_7d` / `listing_changes` 五个信号字段
    ③ **通知** ❌ 没有任何东西会**在每天早上**把这些变化说给用户听
    ④ 展示    ❌ 右上角铃铛 `:count="0"` 是**硬编码死的**（`Workspace.vue`）

    ⇒ 每个零件都是好的，缺的只是"没有任何东西去调用它"。本模块 + `tasks.py`
      + `core/redis.py` 的 beat 条目 + `daily_briefings` 表把 ③④ 接上。
      ★ 同款先例：`core/audit/` 的保留期清理（第 328 轮）、
        `core/backup/` 的每日备份（第 340 轮）—— 都是"脚本/函数早就在，
        只是生产里没有东西会去调它"。

==============================================================================
★★ 为什么阈值是**模块常量**，而不是 `core/config.py` 里的开关
==============================================================================
  ① 它们与下面的**判定逻辑强耦合**：改 `build_briefing_items` 的分支就要
     同步改阈值，放两个文件里必然漂移。
  ② 它们不是"运维可以在生产上随时翻的开关"——翻了之后**当天**的简报口径就变了，
     而那是一份**已经发出去的东西**（用户早上看过一眼）。语义上属于代码，不属于配置。
  ③ 同款判据见 `core/redis.py` 里 `TRADE_SYNC_INTERVAL_HOURS` 那段注释
     （「为什么不进 core/config：进 config 会让它看起来像一个可以随时翻的业务开关」）。
  ★ 另有一条本仓体量约束：`core/config.py` 已在**源码体量棘轮**的冻结表里
     （`backend/tests/test_source_size_ratchet.py`，值只许降不许升），
     往那儿加行会直接撞门禁。

==============================================================================
★★ 租户语义（照 `monitors` 表，不另发明）
==============================================================================
  · `shop_id` 是**唯一的数据分区维度**（`X-Shop-ID → store_id`，
    `core/tenant/scoping.py::SHOP_SCOPE_ATTR`）。
  · `account_id` / `owner_id` 那一层管的是「你能看见哪些店」，**不是**分区维度
    ⇒ 本表**不带** `account_id` 列，与 `monitors` 保持一致。
  · ★ 已知取舍：`read_at`（已读）**按 (店铺 × 日期) 存**，而不是按人存。
    于是同一账户里两个成员看到的是同一个已读状态。这在当前形态下是对的
    （数据作用域只有一层，"谁读的"没有落点），但**将来要支持多人各自的未读**时，
    需要把它拆成一张 `briefing_reads(briefing_id, user_id)` —— 那时 `read_at` 退役。

==============================================================================
★★ 两条时间口径（刻意不同，别"统一"）
==============================================================================
  · `brief_date` = **本地日历日**（`YYYY-MM-DD`）—— 它回答的是
    「这是**哪一天**的简报」，是用户语义（"今天的简报"），必须跟着挂钟走。
  · `generated_at` / `read_at` = **UTC ISO 串** —— 与仓内其他时间列
    （`MonitorRecord.created_at` 等）同口径，用于排序与审计。
  ★ 如果把它们统一成一种：前者用 UTC 会让"今天的简报"在时区偏移下变成昨天/明天；
    后者用本地会让跨表排序在换时区时错乱。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from core.database import async_session_factory
from core.logger import get_logger

from modules.monitors.db_model import DailyBriefingRecord, MonitorRecord

logger = get_logger("monitors.briefing")

#: 降价告警阈值（百分点）。`price_change_7d` 是近 7 天涨跌幅，**负 = 降价**。
#: ★ 取 -10 而不是 -5：5% 在 3C / 家居类目的日常促销里就是噪音，
#:   天天推「某竞品降 5%」的结果是铃铛变成背景板、真信号被淹掉。
PRICE_DROP_THRESHOLD_PCT = -10.0

#: 榜单跃升阈值（名次差）。`bsr_change_7d` 负 = 排名上升。
#: ★ 100 名是个粗但稳的下界：BSR 在小类目里日间波动本来就有几十名。
BSR_CLIMB_THRESHOLD = -100

#: 新增评论阈值（条，近 7 天）。评论暴增通常先于排名跃升。
REVIEW_SURGE_THRESHOLD = 20

#: Listing 变更的**最小处数**。
#:
#: ★★ 这个门槛的来历是**实测**，不是拍脑袋（第 371 轮首次生成的真实数据）：
#:   在不设门槛时 `listing_changes` 非空的比例极高 —— 4 家店共 48 条条目里
#:   它一家占 23 条（≈48%），把降价与排名跃升挤出了 `MAX_ITEMS` 上限。
#:   根因是原判据「近 7 天有任何变更」太宽：改一张主图、补一个关键词都算。
#:   ≥2 处通常意味着对手在做**整套改版**（主图 + 五点 + 标题一起动），
#:   那才是值得知道的；零散 1 处属于日常运营动作，不该占简报的名额。
#: ★ 为什么是「加门槛」而不是「给类型限流」：限流会让「今天 10 个竞品都断货」只报 4 个 —— 那是**漏报**，
#:   而漏报比刷屏危险得多。加门槛只砍掉噪音，不砍掉任何一类信号。
LISTING_CHANGE_MIN = 2

#: 一条简报最多带几条明细。
#: ★ 上限的存在意义不是省字节，而是**简报要能被一眼读完**：
#:   列 40 条等于没有重点，用户会直接不看。
#: ★ 12 -> 20 同样是**实测调上来的**（第 371 轮首次生成的真实数据）：
#:   当时**每一家店都恰好顶到 12 条**（= 全部被截断），说明上限比真实产量
#:   还小。那不是筛选、是截断 —— 用户永远只看到前 12 条，
#:   而「被砍掉的那几条是什么」无从得知。
MAX_ITEMS = 20

#: 条目类型 → 中文说明（`summary` 里的计数文案用；也是**类型的全集声明**）
ITEM_TYPE_LABELS: Dict[str, str] = {
    "price_drop": "降价",
    "stock_out": "断货",
    "stock_low": "库存告急",
    "review_surge": "评论激增",
    "bsr_climb": "排名跃升",
    "listing_change": "Listing 变更",
}

#: 严重度排序权重（小的排前面）。简报是**倒序醒目**的：高风险必须置顶。
_SEVERITY_RANK = {"high": 0, "medium": 1, "info": 2}

#: 同一严重度内的**类型优先级**（小的排前面）。
#:
#: ★ 为什么不能按 `type` 的字母序：那会让 `bsr_climb` 排在 `price_drop` 前面 ——
#:   而「对手降价 18%」显然比「我们排名升了 100 名」更该先被看到。
#:   字母序是「碰巧有个顺序」，不是「有理由的顺序」，用户读起来会觉得简报没重点。
#: ★ 顺序理由（从「必须今天动」到「知道就好」）：
#:   stock_out（窗口期，慢一天就没了）> price_drop（价格战要跟）
#:   > stock_low（还来得及）> review_surge（趋势信号）
#:   > bsr_climb（结果，不是原因）> listing_change（对手动作，最弱线索）
#: ★ 键集合必须与 `ITEM_TYPE_LABELS` 相等（由 tests 钉住）。
_TYPE_ORDER: Dict[str, int] = {
    "stock_out": 0,
    "price_drop": 1,
    "stock_low": 2,
    "review_surge": 3,
    "bsr_climb": 4,
    "listing_change": 5,
}

#: 类型 → 该类条目的**默认**严重度。
#:
#: ★★ 这是「类型 ↔ 严重度」的**唯一真源**：下面每个分支都从它取值，
#:   只有需要按数据动态升级的才就地覆盖（见 `price_drop` 的清仓那一档）。
#:   在分支里各写一遍字面量 = 同一事实 N 份写法 —— 改一处就静默漂移，
#:   而症状只是「摘要里某一类的排序不对」，没有任何一处会报错。
#: ★ 键集合必须与 `ITEM_TYPE_LABELS` 相等，由 `tests/test_briefing_schedule.py` 钉住。
_TYPE_SEVERITY: Dict[str, str] = {
    "price_drop": "medium",
    "stock_out": "high",
    "stock_low": "medium",
    "review_surge": "medium",
    "bsr_climb": "info",
    "listing_change": "info",
}


def local_today(now: Optional[datetime] = None) -> str:
    """本地日历日（`YYYY-MM-DD`）。★ 口径理由见文件头「两条时间口径」。"""
    return (now or datetime.now()).strftime("%Y-%m-%d")


def briefing_id(brief_date: str, shop_id: Optional[str]) -> str:
    """主键 `brief-{date}-{shop}`。

    ★ 主键必须带租户维度：日期只在**同一店铺内**唯一（同 `monitors` 的
      `mon-{asin}-{shop}` 判据）。
    ★ `shop_id` 为空（演示模式 / 无租户上下文）时用 `demo` 占位 ——
      不能省掉这一段：省掉会让"无租户上下文"和"某个恰好叫 demo 的店"
      撞同一个主键，而**写入方没有任何一处会报错**。
    """
    return f"brief-{brief_date}-{shop_id or 'demo'}"


def build_briefing_items(
    records: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从监控池当刻快照派生简报条目。**纯函数**（不碰数据库）。

    ★ 做成纯函数是刻意的：这是本模块唯一有**业务判定**的地方，
      纯函数才能零成本单测（不需要起库、不需要 Celery）。
      同款取舍见 `frontend/src/utils/hoverTranslate.ts`（零 import 的叶子）。

    `records` 每项的字段口径 = `MonitorRecord` 的列名（不经过任何前端驼峰转换）。
    """
    items: List[Dict[str, Any]] = []

    for r in records:
        asin = str(r.get("asin") or "")
        title = str(r.get("title") or "") or asin
        base = {"asin": asin, "title": title}

        price_chg = _as_float(r.get("price_change_7d"))
        if price_chg is not None and price_chg <= PRICE_DROP_THRESHOLD_PCT:
            items.append(
                {
                    **base,
                    "type": "price_drop",
                    # 降幅 ≥ 25% 通常是清仓 / 打价格战 ⇒ 从默认档**升**到 high
                    "severity": "high"
                    if price_chg <= -25.0
                    else _TYPE_SEVERITY["price_drop"],
                    "metric": f"{price_chg:.1f}%",
                    "text": f"{title} 近 7 天降价 {abs(price_chg):.1f}%"
                    f"（现价 {_as_float(r.get('latest_price')) or 0:.2f}）",
                }
            )

        stock = str(r.get("stock_status") or "")
        if stock == "out_of_stock":
            items.append(
                {
                    **base,
                    "type": "stock_out",
                    # 断货是**窗口期**：它一出现就该立刻动，不是"看看再说"
                    "severity": _TYPE_SEVERITY["stock_out"],
                    "metric": "断货",
                    "text": f"{title} 已断货 —— 这是抢排名的窗口期",
                }
            )
        elif stock == "low_stock":
            items.append(
                {
                    **base,
                    "type": "stock_low",
                    "severity": _TYPE_SEVERITY["stock_low"],
                    "metric": "库存低",
                    "text": f"{title} 库存告急"
                    + (
                        f"（估计可售 {r.get('estimated_units_remaining')} 件）"
                        if r.get("estimated_units_remaining") is not None
                        else ""
                    ),
                }
            )

        reviews_added = _as_int(r.get("reviews_added_7d"))
        if reviews_added is not None and reviews_added >= REVIEW_SURGE_THRESHOLD:
            items.append(
                {
                    **base,
                    "type": "review_surge",
                    "severity": _TYPE_SEVERITY["review_surge"],
                    "metric": f"+{reviews_added}",
                    "text": f"{title} 近 7 天新增 {reviews_added} 条评论（排名通常随后抬升）",
                }
            )

        bsr_chg = _as_int(r.get("bsr_change_7d"))
        if bsr_chg is not None and bsr_chg <= BSR_CLIMB_THRESHOLD:
            items.append(
                {
                    **base,
                    "type": "bsr_climb",
                    "severity": _TYPE_SEVERITY["bsr_climb"],
                    "metric": f"{bsr_chg}",
                    "text": f"{title} 榜单排名上升 {abs(bsr_chg)} 名"
                    f"（当前 BSR {_as_int(r.get('latest_bsr')) or 0}）",
                }
            )

        changes = r.get("listing_changes")
        # ★ 门槛理由见 `LISTING_CHANGE_MIN` 的注释（实测：不设门槛时它一家占 48%）
        if isinstance(changes, list) and len(changes) >= LISTING_CHANGE_MIN:
            items.append(
                {
                    **base,
                    "type": "listing_change",
                    "severity": _TYPE_SEVERITY["listing_change"],
                    "metric": f"{len(changes)} 处",
                    "text": f"{title} 的 Listing 有 {len(changes)} 处变更",
                }
            )

    # 排序：先严重度，再**类型优先级**（理由见 `_TYPE_ORDER`），最后 asin 兜底保证稳定
    items.sort(
        key=lambda it: (
            _SEVERITY_RANK.get(it["severity"], 9),
            _TYPE_ORDER.get(it["type"], 9),
            it["asin"],
        )
    )
    return items[:MAX_ITEMS]


def summarize(items: List[Dict[str, Any]]) -> str:
    """把条目压成一句人话（铃铛抽屉里那行标题）。

    ★ 没有条目时**不返回空串** —— 空串在界面上会退化成「有一条通知但没写是什么」。
      返回一句明确的"今天没有需要你处理的变化"，用户才知道简报**跑过了**。
    """
    if not items:
        return "今天没有需要你处理的变化"
    counts: Dict[str, int] = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    # ★ 排序口径与明细列表**同源**（类型优先级），这样摘要与列表读起来同序：
    #   摘要把「2 个降价」放前面，用户在列表里看到的第 2 条也确实是降价。
    parts = [
        f"{counts[t]} 个{ITEM_TYPE_LABELS.get(t, t)}"
        for t in sorted(counts, key=lambda t: _TYPE_ORDER.get(t, 9))
    ]
    # 总述 + 明细：只给"3 项变化"用户不知道是什么，只给明细又读不出量级
    return f"今天有 {len(items)} 项变化：" + "、".join(parts)


def _as_float(v: Any) -> Optional[float]:
    """宽容取数：`None` / 非数字一律返回 `None`（**不当 0**）。

    ★ 为什么不能 `float(v or 0)`：`0` 是一个**合法观测值**（价格没变），
      把"缺字段"和"确实是 0"压成同一个值，会让"这个信号没采集到"退化成
      "这个信号是 0" —— 后者在简报里表现为"什么都没发生"，而前者本该进告警。
      同款判据见 `modules/monitors/service.py::build_monitor_record`
      （「注意 0 / 0.0 是有效值，不能用 `or` 判空」）。
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> Optional[int]:
    """同 `_as_float`（这里的 `None` 与 `0` 也必须分开）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# 落库（生成 + 读写）
# ============================================================

async def generate_for_shop(
    session,
    shop_id: Optional[str],
    brief_date: Optional[str] = None,
) -> Dict[str, Any]:
    """为一家店生成当天的简报并**落库**（同 `(shop_id, brief_date)` 幂等覆盖）。

    ★ 不提交：任务体是事务边界（同 `core/audit/tasks.py::_purge_once` 与
      `modules/trade/tasks.py` 的分工）。这样才能被测试塞进自己的事务里回滚。

    ★ 幂等语义是**覆盖**而不是"已存在就跳过"：重跑一次（手动补跑 / beat 重试）
      应当反映**当刻**的监控池；若跳过，昨天生成的简报会带着旧数字一直挂在那儿。
    """
    date = brief_date or local_today()

    rows = (
        await session.execute(select(MonitorRecord).where(MonitorRecord.shop_id == (shop_id or "")))
    ).scalars().all()
    # ★ 逐列取出来再交给纯函数：不把 ORM 实体直接透进去，
    #   否则 `build_briefing_items` 就绑死在 SQLAlchemy 上，也就没法纯单测。
    records = [
        {
            "asin": r.asin,
            "title": r.title,
            "latest_price": r.latest_price,
            "price_change_7d": r.price_change_7d,
            "latest_bsr": r.latest_bsr,
            "bsr_change_7d": r.bsr_change_7d,
            "reviews_added_7d": r.reviews_added_7d,
            "stock_status": r.stock_status,
            "estimated_units_remaining": r.estimated_units_remaining,
            "listing_changes": r.listing_changes,
        }
        for r in rows
    ]

    items = build_briefing_items(records)
    summary = summarize(items)
    bid = briefing_id(date, shop_id)
    now = datetime.utcnow().isoformat()

    existing = (
        await session.execute(select(DailyBriefingRecord).where(DailyBriefingRecord.id == bid))
    ).scalar_one_or_none()

    if existing is None:
        session.add(
            DailyBriefingRecord(
                id=bid,
                brief_date=date,
                shop_id=shop_id or "",
                items=items,
                summary=summary,
                item_count=len(items),
                generated_at=now,
                created_at=now,
            )
        )
    else:
        existing.items = items
        existing.summary = summary
        existing.item_count = len(items)
        existing.generated_at = now

    return {"shop_id": shop_id or "", "brief_date": date, "id": bid, "item_count": len(items)}


async def list_briefings(
    shop_id: Optional[str], limit: int = 30
) -> List[Dict[str, Any]]:
    """简报列表（**日期倒序**，最新在前）。"""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(DailyBriefingRecord)
                .where(DailyBriefingRecord.shop_id == (shop_id or ""))
                .order_by(DailyBriefingRecord.brief_date.desc())
                .limit(max(1, min(int(limit or 30), 180)))
            )
        ).scalars().all()
        return [_to_dict(r) for r in rows]


async def count_unread(shop_id: Optional[str]) -> int:
    """未读简报数（铃铛徽标的数据源）。

    ★ 单独一个函数而不是"读列表再 `len([r for r in ...])`"：
      徽标每次轮询都要这个数字，而列表接口会顺带把 `items` JSON 全解出来
      （每份最多 `MAX_ITEMS` 条明细）。两者成本不同，不该共用一条路。
    """
    async with async_session_factory() as session:
        n = (
            await session.execute(
                select(func.count(DailyBriefingRecord.id)).where(
                    DailyBriefingRecord.shop_id == (shop_id or ""),
                    DailyBriefingRecord.read_at.is_(None),
                )
            )
        ).scalar_one()
        return int(n or 0)


async def mark_read(briefing_id_: str, shop_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """把一条简报标为已读。**幂等**（重复调用不改变首次的 `read_at`）。

    ★ 返回 `None` 表示"没找到"——调用方据此回 404，**不**静默成功。
      静默成功会让前端把徽标清掉，而实际上服务端还是未读 ⇒ 刷新后又冒出来。
    """
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(DailyBriefingRecord).where(
                    DailyBriefingRecord.id == briefing_id_,
                    # ★ 归属条件必须进查询（不能先查再在 Python 里比）：
                    #   否则"不存在"与"不属于你"会走出两条不同的路径，
                    #   而两者对调用方的可见差异就是一个**存在性探测器**
                    #   （枚举他人 briefing_id 能看到 404 vs 403 的差别）。
                    DailyBriefingRecord.shop_id == (shop_id or ""),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.read_at is None:
            row.read_at = datetime.utcnow().isoformat()
        await session.commit()
        return _to_dict(row)


def _to_dict(r: DailyBriefingRecord) -> Dict[str, Any]:
    """ORM → dict（字段名与前端 `DailyBriefing` 一一对齐，**保持下划线**）。

    ★ 与本文件其他读口一致：`monitors` 的 `record_to_dict` 也是原样吐下划线，
      转换在前端做（`stores/briefing.ts` 一处）。
    """
    return {
        "id": r.id,
        "brief_date": r.brief_date,
        "shop_id": r.shop_id,
        "items": r.items or [],
        "summary": r.summary or "",
        "item_count": r.item_count or 0,
        "read_at": r.read_at,
        "generated_at": r.generated_at,
    }


__all__ = [
    "PRICE_DROP_THRESHOLD_PCT",
    "BSR_CLIMB_THRESHOLD",
    "REVIEW_SURGE_THRESHOLD",
    "MAX_ITEMS",
    "ITEM_TYPE_LABELS",
    "LISTING_CHANGE_MIN",
    "local_today",
    "briefing_id",
    "build_briefing_items",
    "summarize",
    "generate_for_shop",
    "list_briefings",
    "count_unread",
    "mark_read",
]

"""
竞品快照 - 种子数据预置（由**监控池**展开，不再现算）

==============================================================================
★ 这个模块解决什么问题
==============================================================================
改造前，竞品情报 Agent 的取数链是：

    competitor_intel.agent_competitor._load_competitor_rows()
      → amazon_sp.get_data_source(prefer="auto")
        →（无 SP-API 凭据）MockAmazonDataSource.fetch_competitors()
          → 每次查询**现场随机生成** TP-Link / Anker / JBL 那 6 个竞品

两个后果：
  1. **每次问都不一样**（`random` 现编），前端展示的"竞品快照"无法复盘；
  2. 那 6 个竞品与用户在监控池里**真正盯的对象**（ZestPro / Voltage / CafeNow …）
     是两套完全不同的世界 —— 用户问"我的竞品怎么样"，回答的是别人的竞品。

本模块把「真实监控对象的时序」**落进数据库**，让 Agent 从表里读：

    monitors 表（用户定义"盯谁"，已持久化）
      --(本模块展开)-->  amazon_competitor_snapshots（逐日快照行，Agent 的权威表）
                           ↑
                     competitor_intel 只读这张表

==============================================================================
★ 字段映射：哪些是真值、哪些**刻意留空**
==============================================================================
逐日行由 monitors 的三列 JSON 时序**确定性展开**（无随机、可复现）：

    competitor_asin    ← monitors.asin
    brand / title      ← monitors.brand / monitors.title
    main_image_url     ← monitors.main_image
    snapshot_date      ← price_history[i].date
    price              ← price_history[i].price
    bsr_rank           ← bsr_history[i].bsr
    price_change       ← 相邻两日价格**真算**（阈值口径与数据源一致）
    review_count       ← monitors.review_count 按 review_events 的 added **回推**
    rating             ← monitors.rating 按 review_events 的 rating_delta **回推**
    competes_with_asin ← monitors.owned_by["asin"]（无定向归属则为 NULL）

**以下四列刻意留 NULL，不用任何方式"推断"填充**：

    has_buybox / buybox_price   monitors 里**没有** Buy Box 维度
    fulfillment                 monitors 里**没有**配送方式维度
    price_vs_own                monitors 里**没有**自研产品价格维度

  为什么不留个"看起来合理"的值：这三项都是**可被用户拿去决策的商业事实**
  （"竞品是不是 FBA"、"它还差多少钱能抢到 Buy Box"）。用 `stock_status` 或
  品牌名硬推，产出的是一条**无法追溯来源**的假事实 —— 比空值危险得多。
  它们由将来的 SP-API 抓取填充（表结构不用动），接口保留在列上。

==============================================================================
★ 幂等
==============================================================================
与 products / assets / candidates / monitors 等 seed 同惯例：全表非空即返回 0。
不硬编码 shop_id —— 只按 `monitors` 里**实际存在**的店铺展开（monitors.shop_id
本身有外键指向 stores_store，所以这里不需要再查一次店铺表）。
"""

from typing import Dict, List, Optional, Sequence

from sqlalchemy import select, func

from core.database import async_session_factory
from core.logger import get_logger
from modules.amazon_sp.db_model import CompetitorSnapshot

_log = get_logger("modules.amazon_sp.seed")


#: 价格变动标记的判定阈值 —— 与 `data_sources/mock_source.fetch_competitors()`
#: **完全同口径**（绝对差值，不是百分比）。消费者按这几个字面量分流，
#: 两边判据必须一致，否则同一个词在两条取数路径下含义不同。
_PRICE_MOVE_THRESHOLD = 1.0
_PRICE_STABLE_EPS = 0.01


def _classify_price_change(price: float, prev: Optional[float]) -> Optional[str]:
    """相邻两个快照点的价格变动标记（首个快照点无前值 ⇒ None）。"""
    if prev is None:
        return None
    diff = price - prev
    if diff < -_PRICE_MOVE_THRESHOLD:
        return "PRICE_DROP"
    if diff > _PRICE_MOVE_THRESHOLD:
        return "PRICE_HIKE"
    if abs(diff) < _PRICE_STABLE_EPS:
        return "STABLE"
    return "NORMAL_FLUCT"


def _trailing_backcast(events: List[Dict], current: float, key: str, ndigits: int = 1) -> List[float]:
    """由**当前值** + 逐日增量，回推每一天的历史值。

    时序是「过去 30 天 → 今天」，`current` 是今天的值，`events[i][key]` 是
    第 i 天相对前一天的变化量。于是：

        第 i 天的值 = current - Σ(events[j][key] for j > i)

    这是**数学等价的重述**，不是估算 —— 展开后所有日增量之和恰好还原到 current。
    评论数与评分在 monitors 表里只有「当前值」一列，没有逐日历史；
    而本表是逐日快照，所以必须做这个回推（否则只能编）。
    """
    out: List[float] = []
    for i in range(len(events)):
        delta_after = sum(float(e.get(key) or 0.0) for e in events[i + 1:])
        out.append(round(current - delta_after, ndigits))
    return out


# ★ 形参标注写成**字符串**：`MonitorRecord` 只在
#   `seed_competitor_snapshots_if_empty()` 内延迟 import（见那里的说明），
#   模块顶层没有这个名字 ⇒ 不加引号会在**定义时**求值并 NameError。
def build_snapshot_rows(monitor: "MonitorRecord") -> List[CompetitorSnapshot]:
    """把一条监控记录展开成逐日竞品快照行（纯函数，便于单测）。

    以 `price_history` 为日期主轴（它最完整）；`bsr_history` / `review_events`
    按 date 建索引对齐，缺某一天就跳过该维度的取值（不补 0，因为 0 是**有效值**，
    补 0 会把"没有数据"伪装成"排名第 0 / 新增 0 条评论"）。
    """
    price_history = list(monitor.price_history or [])
    if not price_history:
        return []

    bsr_by_date = {p.get("date"): p.get("bsr") for p in (monitor.bsr_history or [])}
    events = list(monitor.review_events or [])
    review_by_date = {e.get("date"): e for e in events}

    # review_count / rating 的逐日值：按 price_history 的日期序列回推。
    # ★ 回推的输入必须是**同一天序列**上的增量；这里按日期取对应的 event，
    #   没有 event 的日期视为当日增量为 0（`review_events` 本身对无变化日也会出点）。
    ordered_events = [
        review_by_date.get(p.get("date"), {"date": p.get("date"), "added": 0, "rating_delta": 0.0})
        for p in price_history
    ]
    review_counts = _trailing_backcast(ordered_events, float(monitor.review_count or 0), "added", 0)
    ratings = _trailing_backcast(ordered_events, float(monitor.rating or 0), "rating_delta", 1)

    # 定向归属：{type: product|candidate, asin, title}；无归属（游离监控）则为 None
    owned = monitor.owned_by or {}
    competes_with = str(owned.get("asin") or "").upper() or None

    rows: List[CompetitorSnapshot] = []
    prev_price: Optional[float] = None
    for i, point in enumerate(price_history):
        day = str(point.get("date") or "")
        if not day:
            continue
        price = point.get("price")
        if price is None:
            continue
        price = float(price)

        rows.append(CompetitorSnapshot(
            store_id=monitor.shop_id,
            snapshot_date=_parse_day(day),
            competitor_asin=str(monitor.asin or "").upper(),
            brand=monitor.brand or None,
            title=monitor.title or None,
            competes_with_asin=competes_with,
            price=price,
            # ★ 以下三项 monitors 无维度 ⇒ 留空（见模块 docstring「刻意留空」）
            price_vs_own=None,
            has_buybox=None,
            buybox_price=None,
            fulfillment=None,
            price_change=_classify_price_change(price, prev_price),
            bsr_rank=_as_int(bsr_by_date.get(day)),
            review_count=int(review_counts[i]),
            rating=max(1.0, min(5.0, float(ratings[i]))),
            main_image_url=monitor.main_image or None,
        ))
        prev_price = price

    return rows


def _parse_day(day: str):
    """'YYYY-MM-DD' → datetime（DB 列是 DateTime）。

    用 datetime 而不是字符串：asyncpg 对 `timestamp` 列接受 ISO 串，但
    由驱动做隐式转换会让"时区/格式"变成一个**静默**的失败面；
    显式解析失败会当场抛，归因清楚。
    """
    from datetime import datetime

    return datetime.fromisoformat(day)


def _as_int(value) -> Optional[int]:
    """转 int；None 保持 None（不写成 0 —— 0 是有效排名，会伪装成真值）。"""
    return int(value) if value is not None else None


async def seed_competitor_snapshots_if_empty(
    *, only_for_shop_ids: Sequence[str] = ()
) -> int:
    """首次启动时，若竞品快照表为空，按监控池展开一批时序数据。

    Returns:
        实际写入的条数（表非空、或监控池为空时返回 0）。

    ★★★ `only_for_shop_ids`（第 175 轮新增）：**只为点名店铺展开**，绕过全表守卫
    ----------------------------------------------------------------------
    与其余六个 seed 同一个问题：本函数的守卫是「**全表**非空 ⇒ 整个函数不执行」
    ⇒ 任何后建的店铺（演示店铺 `is_demo=true`）一条快照都拿不到。传参时改为
    **按 store 判空**：已有快照的 store 跳过（幂等），只展开点名且为空的 store。
    不传时行为与改造前**逐字一致**。

    ★★ 当前状态（第 176 轮）：**启动流程不再自动调用它**
    ------------------------------------------------------------------
    第 175 轮的演示店铺是「新建一家空店」，必须补灌；第 176 轮改为「**演示账号
    名下那 4 家本来就有数据的店**」，自动补灌只会把 `SEED_*` 常量里的
    `https://picsum.photos/...` **随机图**灌进原本干净的店铺
    （实测：虾皮1/2、亚马逊2 各多出 3~7 行，图片与商品完全无关 —— 正是老板
    抱怨的「图与商品不对应」）。参数保留，供将来「给指定店铺补灌」使用。
    """
    # ★ 延迟 import（必须留在函数体内，别"整理"回顶层）：
    #   `monitors` 是 PLUGIN 层、本包是 SHARED 层，`tests/test_module_layering.py`
    #   禁止 SHARED→PLUGIN 的**import 期**边（共享层反向依赖插件会成环）。
    #   该门禁明确豁免「函数内延迟 import」—— 见其 docstring 第 54 行。
    from modules.monitors import MonitorRecord

    async with async_session_factory() as session:
        if only_for_shop_ids:
            # ---- 只展开点名店铺的监控池（第 175 轮：演示店铺走这条通道）----
            #
            # ★ 判据是**按 store 判空**（distinct store_id），不是全表计数：
            #   全表早已非空，正是它让演示店铺永远拿不到快照。
            already = set((await session.execute(
                select(CompetitorSnapshot.store_id).distinct()
            )).scalars().all())
            targets = [s for s in only_for_shop_ids if s not in already]
            if not targets:
                return 0
            _monitor_stmt = select(MonitorRecord).where(
                MonitorRecord.shop_id.in_(targets)
            )
        else:
            # ---- 默认：全表非空即跳过（与改造前**逐字一致**）----
            existing = (await session.execute(
                select(func.count()).select_from(CompetitorSnapshot)
            )).scalar_one()
            if existing > 0:
                return 0
            _monitor_stmt = select(MonitorRecord)

        monitors = (await session.execute(_monitor_stmt)).scalars().all()
        if not monitors:
            # 监控池为空 ⇒ 没有"用户真正盯的对象"可展开。
            # 这里**不去编一批竞品**填充 —— 那正是本次改造要删掉的东西。
            return 0

        total = 0
        for monitor in monitors:
            if not monitor.shop_id:
                continue          # 无租户归属的行（外键下不应存在），跳过
            for row in build_snapshot_rows(monitor):
                session.add(row)
                total += 1
        await session.commit()

    _log.info("竞品快照种子数据：{} 条监控展开为 {} 行", len(monitors), total)
    return total

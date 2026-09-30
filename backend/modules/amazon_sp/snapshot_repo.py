"""竞品快照读取层 —— `amazon_competitor_snapshots` 的**唯一读取入口**。

==============================================================================
★ 为什么读取层必须收口在「表的所有者」这里（第 172 轮）
==============================================================================
改造前，竞品快照有**两份**读取实现，且都不读表：

    competitor_intel/agent_competitor.py::_load_competitor_rows()
    ad_analysis/agent_ad.py::_load_competitor_rows()
      → 都是 amazon_sp.get_data_source(prefer="auto")
        →（无 SP-API 凭据）MockAmazonDataSource.fetch_competitors()
          → 每次**现场随机**生成 TP-Link / Anker / JBL 那 6 个竞品

第 172 轮把 `competitor_intel` 那份改成直读表，但当时的门禁**只扫这一个模块**，
于是 `ad_analysis` 里那份同名同职责的实现**在门禁全绿的情况下继续服务**
「竞品广告分析」—— 同一个平台上，两个功能回答的是两个不同的竞品世界。

⇒ 教训：**单模块 scoped 的门禁只能证明「这一份是对的」，不能证明「只有这一份」。**
  读取逻辑因此上收到表的所有者（`modules/amazon_sp`），两个消费方共用本函数。
  对应的门禁 `tests/test_competitor_intel.py::test_competitor_snapshot_has_exactly_one_door`
  是**全仓**扫描的。

==============================================================================
★ 租户隔离只在这一处
==============================================================================
`WHERE store_id = ...` 在本文件里是**唯一一份**实现。两个消费方各写 SQL 的时代，
任何一份漏掉这个条件就是跨租户数据泄漏 —— 而漏掉的那份不会有任何测试变红。

==============================================================================
★ 为什么导出的是**函数**而不是 ORM 模型
==============================================================================
`modules/amazon_sp/__init__.py` 的门面契约写着「模型层（`db_model`）不对外」，
本函数就是对它的兑现：消费方拿到的是**行**，不是可以任意拼 SQL 的类。
将来接真实 SP-API 抓取时，只需让抓取任务写同一张表 —— 本函数与两个消费方
一行都不用改，这就是「保留接口」的落点。
"""

from typing import Dict, List, Optional

from core.database import async_session_factory
from core.logger import get_logger
from modules.amazon_sp.db_model import CompetitorSnapshot

_log = get_logger("modules.amazon_sp.snapshot_repo")

#: 默认查询窗口（天）—— 与 Agent 侧 "30d" 的默认口径一致。
DEFAULT_WINDOW_DAYS = 30


def snapshot_to_row(r) -> Dict:
    """ORM 行 → 与 `AmazonDataSource.fetch_competitors()` **逐字段同形**的 dict。

    ★ 这个「同形」是刻意的：下游 `_build_from_rows()`（competitor_intel）与
      `_competitor_data_from_rows()`（ad_analysis）只认字段名，取数层从数据源
      换成数据库后它们**一行都不用改**。少一处改动 = 少一处回归面。
    ★ `snapshot_date` 统一成 'YYYY-MM-DD' 字符串：DB 里是 DateTime，
      直接 str() 会得到 '2026-08-13 00:00:00'，而下游/前端契约是日期串。
    """
    return {
        "store_id": r.store_id,
        "snapshot_date": r.snapshot_date.date().isoformat() if r.snapshot_date else "",
        "competitor_asin": r.competitor_asin,
        "competes_with_asin": r.competes_with_asin,
        "brand": r.brand,
        "title": r.title,
        "price": r.price,
        "price_vs_own": r.price_vs_own,
        "price_change": r.price_change,
        "has_buybox": r.has_buybox,
        "buybox_price": r.buybox_price,
        "bsr_rank": r.bsr_rank,
        "review_count": r.review_count,
        "rating": r.rating,
        "fulfillment": r.fulfillment,
        "main_image_url": r.main_image_url,
    }


async def load_competitor_snapshots(
    store_id: Optional[str],
    days: int = DEFAULT_WINDOW_DAYS,
    asins: Optional[List[str]] = None,
) -> List[Dict]:
    """取某店铺近 `days` 天的竞品快照（逐日行）。

    ★ 拿不到 `store_id`（未选店铺）时**不猜测、不取默认店**，直接返回空列表，
      由调用方给显式空状态。
    ★ `asins` 过滤语义与原数据源一致：命中「竞品自身 ASIN」**或**「它盯的自研
      ASIN」；查不到的 ASIN 就落空 —— 这是事实，不由本层编造补上。
    ★ 取数故障**不得伪装成「无数据」**：这里直接抛出，由调用方区分
      「表里没有」与「读表失败」。
    ★ 无租户归属（`store_id` 为空串）按「拿不到 store_id」处理：返回空，
      绝不用空串去查 —— 空串是历史脏数据的值，撞上会把别人的行当自己的。
    """
    if not store_id:
        return []

    from datetime import date, datetime, timedelta

    from sqlalchemy import func, or_, select

    span = max(1, int(days or DEFAULT_WINDOW_DAYS))
    d_to = date.today()
    d_from = d_to - timedelta(days=span - 1)

    # ★ 租户过滤：全仓唯一一份（见模块 docstring）
    stmt = select(CompetitorSnapshot).where(
        CompetitorSnapshot.store_id == str(store_id),
        CompetitorSnapshot.snapshot_date >= datetime.combine(d_from, datetime.min.time()),
        CompetitorSnapshot.snapshot_date <= datetime.combine(d_to, datetime.max.time()),
    )
    if asins:
        wanted = sorted({str(a).upper() for a in asins})
        stmt = stmt.where(or_(
            func.upper(CompetitorSnapshot.competitor_asin).in_(wanted),
            func.upper(CompetitorSnapshot.competes_with_asin).in_(wanted),
        ))
    stmt = stmt.order_by(CompetitorSnapshot.snapshot_date)

    try:
        async with async_session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
    except Exception as e:  # 取数故障不得伪装成「无数据」
        _log.error("读竞品快照失败 store={}: {}", store_id, e)
        raise

    return [snapshot_to_row(r) for r in rows]

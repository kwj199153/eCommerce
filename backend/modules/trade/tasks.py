"""
交易履约域 —— **定时同步**（Celery 任务，第 283 轮）
====================================================

★★ 为什么必须有这个文件
------------------------
本域此前已经有表（`db_model.py`）、口径（`service.py`）、写入路径
（`sync.py`）与上游（`AmazonDataSource.fetch_orders`）—— 全都正确，
但**没有任何东西会去调用它们**，于是现象是：
「功能都在，订单表永远是那 4 条演示数据」。

这正是 r141 判「假页面」的同一条判据：**承诺了会跑，而后端零实现**。
「订单落库同步」这六个字的落地物就是本文件 + beat 里那条调度。

验收判据（照 `modules/memory/tasks.py` 的三条，本域同样适用）：
  ① `celery_app.conf.beat_schedule` 里真的有条目（beat 能算出下次运行时间）；
  ② worker 注册得到这两个任务名（`celery inspect registered` 查得到）；
  ③ 任务**失败**要看得见 —— 不能让「没跑 / 跑了没事 / 跑失败」
     在界面上长得一模一样。本文件用「逐店结构化结果 + 异常冒泡」满足它。

★ 两个任务、两个粒度（fan-out）
    trade.sync_all_shops —— beat 入口：枚举店铺，逐店投递
    trade.sync_shop      —— 单店同步的落点
  fan-out 的理由与 memory 同源：接上真 SP-API 之后单店拉取可能几十秒，
  放在一个任务里串行 ⇒ 前面慢的店会拖垮后面所有店，
  而且**看不出是谁拖垮的**（超时杀掉的是整批）。

★★ 跨 event loop 的连接池陷阱（与 memory / aigc 同源）
  Celery 是同步进程，任务体要跑协程，而 `asyncio.run()` **每次新建并关闭**
  一个 loop；asyncpg 的连接绑定在创建它的那个 loop 上 ⇒ 第二次任务必挂
  （`Task got Future attached to a different loop`），而单任务验证会全绿。
  ⇒ 用**每线程常驻 loop**。详见 `modules/memory/tasks.py` 的长论证。

★★★ 演示数据源只喂演示店铺
  当前无 SP-API 凭据 ⇒ `get_data_source()` 回退 `MockAmazonDataSource`。
  若不加约束，定时任务会把同一份演示订单灌进**库里每一家店铺** ——
  于是「亚马逊2 / 虾皮1 / BOLA店铺」莫名其妙多出 4 笔亚马逊订单，
  而且它们长得跟真的一样（`source='mock_seed'` 是唯一线索，没人会去看）。
  ⇒ 数据源是 mock 时，只同步 `is_demo=True` 的店铺，其余**根本不枚举**，
     并在返回值里写下这个约束（否则「为什么只有 4 家」无从查起）。
"""

import asyncio
import threading
from typing import Any, Dict, List

from sqlalchemy import select

from core.database import async_session_factory
from core.logger import get_logger
from core.redis import celery_app
from core.stores import StoreRecord
from modules.trade import sync as trade_sync

logger = get_logger("trade.tasks")

#: 任务注册名。★ 集中定义一次：这两个名字同时出现在
#:   · 本文件的 `@celery_app.task(name=...)`
#:   · `core/redis.py::beat_schedule` 里的**字面量**（core 不得 import modules）
#: 于是它们构成「同一事实两份写法」—— 写错时 beat 会往一个没人注册的
#: 名字投递：现象是「订单表永远不更新，日志里一条都没有」。
#: ⇒ 由 `tests/test_trade_schedule.py` 把两边钉成相等（不是靠注释提醒）。
TASK_SYNC_ALL_SHOPS = "trade.sync_all_shops"
TASK_SYNC_SHOP = "trade.sync_shop"


# ============================================================
# 每线程常驻 event loop（见模块 docstring）
# ============================================================

_LOOP_LOCAL = threading.local()


def _thread_loop() -> asyncio.AbstractEventLoop:
    """本线程的常驻 loop（不存在就建，建好就不再关）。

    ★ 刻意不用 `asyncio.run()`：它每次新建并**关闭**一个 loop，
      池里的连接随即变成「属于一个已经死掉的 loop」。
    """
    loop = getattr(_LOOP_LOCAL, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LOOP_LOCAL.loop = loop
    return loop


def _run_sync(coro) -> Any:
    return _thread_loop().run_until_complete(coro)


# ============================================================
# 异步实现
# ============================================================

async def _list_shop_ids(*, demo_only: bool) -> List[str]:
    """要同步哪些店铺。

    ★ `demo_only` 为真时只取演示店铺 —— 理由见模块 docstring 最后一段。
      这不是「先取全部再过滤」，而是**根本不枚举**非演示店铺：
      少一次「差一点就写进去了」的机会，也让返回值里的 shops 数可直接对账。
    """
    async with async_session_factory() as session:
        q = select(StoreRecord.id)
        if demo_only:
            q = q.where(StoreRecord.is_demo.is_(True))
        q = q.order_by(StoreRecord.id)
        return list((await session.execute(q)).scalars().all())


async def _sync_one_shop(shop_id: str) -> Dict[str, Any]:
    """同步一家店（订单 + 评论），并**提交**。

    ★ 为什么在这里 commit 而不是留给调用方：任务体是事务边界，
      让 `sync_trade` 保持「只写不提交」才能被测试塞进自己的事务里回滚。
    """
    # 函数内延迟 import：`data_sources` 工厂会读配置、可能触发较重初始化，
    # 放在模块顶层会让「只是想读一下 TASK_* 常量」的调用也付出这个代价。
    from modules.amazon_sp import get_data_source

    source = get_data_source(prefer="auto")
    async with async_session_factory() as session:
        result = await trade_sync.sync_trade(session, shop_id, source)
        await session.commit()
    return result


# ============================================================
# Celery 任务
# ============================================================

@celery_app.task(bind=True, name=TASK_SYNC_SHOP)
def sync_shop(self, shop_id: str) -> Dict[str, Any]:
    """同步**一家**店铺的订单与买家评论。

    ★ 异常**不吞**：让它冒到 Celery，任务被标 FAILURE 并留下 traceback。
      改成「捕获后返回 ok=False」的话，「这次失败了」与「这次没有新数据」
      在结果里长得一样 —— 那正是 r141 判「假页面」的那条判据。
    """
    try:
        out = _run_sync(_sync_one_shop(shop_id))
        logger.info(
            "trade 同步完成 shop={} 订单 新增{}/更新{} 评论 新增{}/更新{} errors={}",
            shop_id, out["orders"]["inserted"], out["orders"]["updated"],
            out["reviews"]["inserted"], out["reviews"]["updated"], out["errors"],
        )
        return {"shop_id": shop_id, "ok": True, **out}
    except Exception as exc:
        logger.error("trade 同步失败 shop={}: {}", shop_id, exc)
        raise


@celery_app.task(bind=True, name=TASK_SYNC_ALL_SHOPS)
def sync_all_shops(self) -> Dict[str, Any]:
    """beat 入口：枚举店铺并逐店投递 `sync_shop`。

    ★ 自己**不做**同步：fan-out 出去，让每家店成为一个独立的重试单元
      （理由见模块 docstring）。
    ★ 演示数据源只喂演示店铺 —— 否则会把同一份演示订单灌进每一家店。
    """
    from modules.amazon_sp import get_data_source

    source = get_data_source(prefer="auto")
    info = source.get_source_info() or {}
    is_mock = info.get("source_type") == "mock"

    shop_ids = _run_sync(_list_shop_ids(demo_only=is_mock))
    for shop_id in shop_ids:
        sync_shop.delay(shop_id)

    out = {
        "ok": True,
        "source_type": info.get("source_type"),
        "demo_only": is_mock,
        "shops": len(shop_ids),
        "dispatched": len(shop_ids),
    }
    if is_mock:
        logger.warning(
            "trade 同步当前跑在**演示数据源**上，只同步演示店铺；"
            "接上真实平台凭据后会自动覆盖全部店铺"
        )
    logger.info("trade 同步已投递 {}", out)
    return out

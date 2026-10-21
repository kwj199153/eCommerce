"""注册即播种 / 「加载示例数据」（第 387 轮 · 网站管理员 P0-2 + P0-3）

==============================================================================
问题（管理员原话，逐字）
==============================================================================
    「访客自助注册进来是空壳，P0-2 的另一半。跨 20+ 表带外键的数据克隆我不做，
      必须产品级 seed」

实测确实如此：新用户**零店铺** ⇒ 多数业务端点（POST 类）因缺 `X-Shop-ID`
直接 400 ⇒ 首屏不是「没有数据」，而是「什么都点不动」。

==============================================================================
本模块做的两件事（刻意都很小）
==============================================================================
1. `bootstrap_new_user(db, user)` —— 注册后给新账号建**一家**店铺，**不灌数据**。
   为什么只建店不灌：现有 `seed_*` 那套示例数据的图片是 `picsum.photos` 随机图，
   与商品标题毫无关系 —— 正是老板第 176 轮明确否决过的「图文不对应」形态
   （见 `modules/stores/demo.py` 文件头）。自动灌进每个新账号，等于把被否决的
   形态装上公开站。
2. `load_sample_data(shop_id)` —— 用户**主动点**「加载示例数据」时才灌，
   并且返回里带 `is_sample=True` + `label`，让界面必须如实标注。

⇒ 「注册即播种」落在**店铺**这一层，「示例数据」落在**用户点击**这一层。
   这是老板拍板的 A 案（建店 + 按需加载），不是默认值。

==============================================================================
★★ 幂等与「假成功」
==============================================================================
各 seed 都是 `*_if_empty`：该店该表已有数据时返回 0。于是 `total == 0` 有两种
含义 —— 「刚刚灌进去了但全部命中幂等键」与「本来就有数据」。本模块不去猜，
直接如实返回 `nothing_new=True`，由界面说「已存在，未重复写入」。

★ 不做「灌失败回滚成 0 条」的兜底：seed 抛错就让它抛（router 回 500）。
  把它吞掉再返回 `total: 0`，界面会显示「加载成功」而库里什么都没有 ——
  这正是本仓反复出现的「假成功」形态。

==============================================================================
★★ 为什么 seed 走**函数内**延迟 import
==============================================================================
本模块是 PLUGIN，它的 9 个 seed 宿主也全是 PLUGIN/SHARED
（products / assets / candidates / monitors / platform_rules / knowledge_base /
trade / amazon_sp / product_research）。顶层 import 会踩
`test_module_layering.py` 的「PLUGIN → PLUGIN」红线（插件之间不得顶层互引）。
`modules/library` 第 218 轮就是这么处理的，理由同源。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.accounts import ensure_default_account
from core.identity.models import User
from core.stores import StoreRecord

# ★ 走门面（`modules.stores` 是 KERNEL，PLUGIN→KERNEL 顶层合法）。
#   它导出的 `create_store_for_account` 已经把「内存读缓存 + 权威存储」成对写好；
#   绕过它直接 insert 一行 PG 会让新店**要等重启才出现**，且不报错。
from modules.stores import create_store_for_account

logger = logging.getLogger(__name__)

#: 注册时自动建的店名。
#:
#: ★ 名字里必须有「示例」二字：这家店没有真实凭据、没有任何平台数据，
#:   叫「我的亚马逊店」等于在用户第一屏埋一个谎。用户改个名就能当自己的用。
SAMPLE_STORE_NAME = "示例店铺 · 亚马逊美国站"

#: 示例数据的**如实标注**（前端必须显示它，不许只显示「已加载」）。
SAMPLE_DATA_LABEL = "示例数据（mock_seed，非真实平台数据）"


class SampleTargetMissing(LookupError):
    """点名的店铺不存在。

    ★ 与「已存在数据」严格分开：前者要 404（去建店），后者是正常状态。
      合并成一句「加载完成」会让用户以为点错了按钮。
    """

    def __init__(self, shop_id: str) -> None:
        self.shop_id = shop_id
        super().__init__(f"店铺不存在：{shop_id}")


async def _account_store_count(db: AsyncSession, account_id: str) -> int:
    n = await db.scalar(
        select(func.count()).select_from(StoreRecord).where(StoreRecord.account_id == account_id)
    )
    return int(n or 0)


async def bootstrap_new_user(db: AsyncSession, user: User) -> Dict[str, Any]:
    """注册后置钩子：给新账号建一家「示例店铺」（幂等）。

    Returns:
        `{"created": bool, "store_id": str|None, "reason": str, "account_id": str}`

    ★ 幂等判据是「该账户名下**有没有店**」而不是「有没有叫这个名字的店」：
      用户可能已经把示例店改名或删掉，再建一家只会凭空多出第二家。
      账户里有店 ⇒ 说明这位用户不是第一次进来，不该再塞东西给他。

    ★ 为什么不在这里灌示例数据：见文件头第 2 段（图文不对应 + 用户没点过）。
    """
    account = await ensure_default_account(db, user)
    # ★★ 必须**提交**，不能只 flush：`create_store_for_account` 内部的
    #    `_upsert_store_db()` 用的是**另一个** session（async_session_factory），
    #    未提交的 accounts 行对它不可见（PG 默认 READ COMMITTED）⇒
    #    `stores_store.account_id` 外键会因「目标账户不存在」而违例。
    #    （与 `modules/stores/router.py::create_store` 同一处坑，同一条注释。）
    await db.commit()

    existing = await _account_store_count(db, account.id)
    if existing:
        logger.info(
            "注册播种跳过：账号已有 %d 家店 user=%s account=%s", existing, user.id, account.id
        )
        return {
            "created": False,
            "store_id": None,
            "reason": "account_already_has_stores",
            "account_id": account.id,
        }

    store_id = await create_store_for_account(
        owner_id=user.id,
        account_id=account.id,
        name=SAMPLE_STORE_NAME,
    )
    logger.info("注册播种：已建示例店铺 user=%s store=%s", user.id, store_id)
    return {
        "created": True,
        "store_id": store_id,
        "reason": "created_sample_store",
        "account_id": account.id,
    }


def _seeders() -> List[Tuple[str, str, Any]]:
    """按**依赖顺序**返回 (key, 中文名, 函数)。

    ★ 顺序有硬依赖，不是审美：
      · `trade` 的锚定 SKU 从**该店自己的产品库**里挑，产品库为空的店会被
        整店跳过（`modules/trade/seed.py` 文件头）⇒ products 必须在前；
      · `competitor_snapshots` 的输入就是 `monitors` 表，池子为空则一行都不展开。
      这两条与 `wiring.SEED_STEPS` 的顺序一致 —— 这里抄的是**语义**，
      而不是那份元组（那是组合根的启动清单，含 `requires_demo` 等启动期概念）。
    """
    # ★ 全部延迟 import：见文件头最后一段（PLUGIN→PLUGIN 红线）。
    from modules.amazon_sp import seed_competitor_snapshots_if_empty
    from modules.assets import seed_assets_if_empty
    from modules.candidates import seed_candidates_if_empty
    from modules.knowledge_base import seed_knowledge_if_empty
    from modules.monitors import seed_monitors_if_empty
    from modules.platform_rules import seed_platform_rules_if_empty
    from modules.product_research import seed_market_snapshots_if_empty
    from modules.products import seed_products_if_empty
    from modules.trade import seed_trade_if_empty

    return [
        ("products", "产品库", seed_products_if_empty),
        ("assets", "素材库", seed_assets_if_empty),
        ("candidates", "候选选品库", seed_candidates_if_empty),
        ("monitors", "竞品监控池", seed_monitors_if_empty),
        ("competitor_snapshots", "竞品快照", seed_competitor_snapshots_if_empty),
        ("platform_rules", "平台规则库", seed_platform_rules_if_empty),
        ("knowledge_base", "业务话术库", seed_knowledge_if_empty),
        ("trade", "交易履约（订单/物流/差评）", seed_trade_if_empty),
        ("market_snapshots", "市场洞察快照", seed_market_snapshots_if_empty),
    ]


async def _shop_exists(shop_id: str) -> bool:
    from core.database import async_session_factory

    async with async_session_factory() as session:
        found = await session.scalar(select(StoreRecord.id).where(StoreRecord.id == shop_id))
    return found is not None


async def load_sample_data(shop_id: str) -> Dict[str, Any]:
    """给**点名店铺**灌一份示例数据（幂等），并如实标注它是示例。

    Args:
        shop_id: `stores_store.id`（`store_xxx`）。归属校验**不在这里做** ——
            调用方（router）必须已经过 `get_current_shop_id`，那里是 `X-Shop-ID`
            归属判定的唯一真源。本函数只认 id，不认人。

    Raises:
        SampleTargetMissing: 店铺不存在（404 语义，不是"加载成功"）。

    Returns:
        `{shop_id, is_sample, label, counts, total, nothing_new}`
    """
    if not await _shop_exists(shop_id):
        raise SampleTargetMissing(shop_id)

    counts: Dict[str, int] = {}
    for key, label, fn in _seeders():
        wrote = await fn(only_for_shop_ids=[shop_id])
        counts[key] = int(wrote or 0)
        if wrote:
            logger.info("示例数据 %s：%s +%d 条 shop=%s", key, label, wrote, shop_id)

    total = sum(counts.values())
    return {
        "shop_id": shop_id,
        # ★ 三个字段一起返回，是为了让界面**没法**只显示「加载成功」：
        #   `is_sample` 与 `label` 就是「这批数是示例，不是真实平台数据」的凭据。
        "is_sample": True,
        "label": SAMPLE_DATA_LABEL,
        "counts": counts,
        "total": total,
        "nothing_new": total == 0,
    }

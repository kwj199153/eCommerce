"""
交易履约 + 买家反馈域 —— 演示数据预置

====================================================
★ 与既有 seed 的两处不同（都是踩过的坑）
====================================================
1. **`shop_id` 不硬编码。** 早期 candidates/seed.py 把 shop_id 写成 `"shop-1"`，
   而真实租户 id 是 `store_xxxxxxxx` ⇒ 灌了也是「任何请求都查不到」的死数据。
   本模块与 monitors 一致：先查 `stores_store` 取真实店铺，逐店灌一份。

2. **锚定 SKU 取自该店铺自己的产品库**，不用写死的假 SKU。
   演示叙事里的 `KITCH-002-BLUE` 在本仓**不存在**（这是老板演示文案里的名字），
   硬灌进去会得到一笔「订单里有个产品库查不到的 SKU」—— 又是那种
   「说得出来、指不到行」的空转。
   ⇒ 锚定 SKU 按三级优先度挑：偏好 sku_code → 偏好 asin → 该店第一条 SKU。
     演示叙事因此用**库里真实存在的那个 SKU**讲，而不是讲一个虚构编号。

====================================================
★ 为什么历史数据刻意做成「能被数出来的重复问题」
====================================================
演示里有句「同类问题近 7 天上升 40%」。它能不能成立，取决于有没有
**≥3 条历史同因归因**能真的被 `count_repeat_issues()` 数出来。
所以本 seed 给锚定 SKU 灌了 3 条同因（packaging_failure）历史差评 ——
这是让那句话从「文案」变成「事实」的唯一办法。

同理，健康分灌了**两期**（上期 + 本期），否则 `delta` 只能是 0，
那句「更新健康分 -0.7」依旧是一句空话。

====================================================
★★ 本模块**不写库** —— 写入一律走 `sync.py`
====================================================
本文件只负责回答「演示载荷从哪来」（剧本 + 该店产品库的真 SKU），
真正的落库由 `sync.upsert_order` / `sync.upsert_review` 完成；
派生态与归因再由它们转交 `service` 算（唯一口径）。

之所以这么绕，是因为写入路径一旦有两份，就会出现：
    seed 自己算一遍 transit_days / primary_cause，同步任务再算一遍。
两边都跑得通、都不报错，差别只在「同一笔订单在 seed 里迟了 7 天、
在同步里迟了 6 天」这种没人会去对的数字上。收成一条之后，
**改口径只需要改一处**，且 seed 与同步共享同一套幂等键。
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

from sqlalchemy import func, select

from core.database import async_session_factory
from core.logger import get_logger
from core.stores import StoreRecord
from core.tenant.scoping import scope_condition
from modules.products import SpuRecord, SkuRecord
from modules.trade import service as trade_service
from modules.trade import sync as trade_sync
from modules.trade.db_model import (
    CompensationRuleRecord, OrderRecord, SOURCE_MOCK_SEED,
)
from modules.trade.demo_script import (
    build_demo_order_payloads, build_demo_review_payloads,
)

_log = get_logger("modules.trade.seed")

# ============================================================
# 锚定 SKU 的偏好（按现实环境排：先认本仓演示库里真实存在的那个）
# ============================================================
_PREFERRED_SKU_CODES = ("SKU-KC-002", "KITCH-002-BLUE")
_PREFERRED_ASIN = "B0CXXXX009"


# ============================================================
# 默认补偿规则（本仓配置，不是平台数据 ⇒ 留在 seed 里）
# ============================================================
#: ★ 剧本本体已搬到 `demo_script.py`（seed 与 Mock 数据源共用同一份），
#:   这里不再持有它 —— 详见该文件头。

#: 默认补偿规则（**可配置**这件事的落地物 —— 不是 prompt 里的一句「酌情补偿」）
DEFAULT_COMPENSATION_RULES: List[Dict] = [
    {
        "code": "packaging-damage-standard",
        "name": "包装破损 · 标准补偿（优惠券 + 免费重发）",
        "cause": "packaging_failure",
        "priority": 10,
        "conditions": {"max_rating": 3},
        "action": {"type": "coupon", "amount": 8.0, "currency": "USD", "reship": True},
        "budget_cap": 50.0,
        "notes": "责任在己方（破损率高于竞品）时适用；含免费重发一份",
    },
    {
        "code": "logistics-delay-minor",
        "name": "物流延迟 · 3 天以上补偿 $5 券",
        "cause": "logistics_delay",
        "priority": 20,
        "conditions": {"max_rating": 3, "min_delay_days": 3},
        "action": {"type": "coupon", "amount": 5.0, "currency": "USD", "reship": False},
        "budget_cap": 30.0,
        "notes": "只在**证据显示真的迟到**时命中（min_delay_days=3）",
    },
    {
        "code": "product-defect-refund",
        "name": "商品缺陷 · 全额退款",
        "cause": "product_defect",
        "priority": 5,
        "conditions": {"max_rating": 3, "verified_purchase": True},
        "action": {"type": "refund", "amount": 0.0, "currency": "USD",
                   "refund_percent": 100, "reship": False},
        "budget_cap": 200.0,
        "notes": "需已验证购买；金额上限 200 USD，超限由 service 显式拒绝",
    },
]


async def pick_anchor_sku(session, shop_id: str) -> Optional[Dict[str, str]]:
    """挑该店铺的演示锚定 SKU —— 三级优先度，全都没有则 None（跳过该店）。"""
    rows = (await session.execute(
        select(SkuRecord.id, SkuRecord.sku_code, SkuRecord.asin,
               SkuRecord.spec_value, SpuRecord.title)
        .join(SpuRecord, SpuRecord.id == SkuRecord.spu_id)
        .where(scope_condition(SpuRecord, shop_id))
        .order_by(SkuRecord.id.asc())
    )).all()
    if not rows:
        return None
    for prefer in _PREFERRED_SKU_CODES:
        for r in rows:
            if r.sku_code == prefer:
                return {"sku": r.sku_code, "asin": r.asin, "title": r.title}
    for r in rows:
        if r.asin == _PREFERRED_ASIN:
            return {"sku": r.sku_code, "asin": r.asin, "title": r.title}
    r = rows[0]
    return {"sku": r.sku_code or r.asin, "asin": r.asin, "title": r.title}


# ============================================================
# 写入：单店铺
# ============================================================

async def seed_demo_for_shop(
    session, shop_id: str, anchor: Dict[str, str], now: datetime,
) -> int:
    """给**一家**店铺灌一整套演示数据（订单 + 评论），返回**真实新增订单数**。

    ★★ 写入一律走 `sync.upsert_*` —— seed 里不许有第二份写入实现。
       本函数只回答「载荷从哪来」：剧本（唯一真源）+ 该店产品库的真 SKU。

    ★ 返回**真实新增数**而不是「处理了几条」：
      「重跑一遍又多了 4 笔」必须能被这个数字看出来，否则幂等只是嘴上说说。
      （老实现每次都 +1，于是「灌了多少次」永远看不出来。）
    """
    inserted = 0
    now_iso = now.isoformat()

    def _resolver(_spec: Dict) -> Dict[str, str]:
        # 剧本里每笔订单都用该店的锚定 SKU（三级优先度挑出来的那个）
        return anchor

    # ★ 订单必须先落库：评论靠 `order_ref` 反查自家 orders.id 才能关联上
    for payload in build_demo_order_payloads(now=now, sku_resolver=_resolver):
        res = await trade_sync.upsert_order(
            session, shop_id, payload,
            source=SOURCE_MOCK_SEED, fetched_at=now_iso,
        )
        inserted += 1 if res["inserted"] else 0

    # 评论自带归因打标（sync 内部调 service.attribute_review）
    for payload in build_demo_review_payloads(now=now, sku_resolver=_resolver):
        await trade_sync.upsert_review(
            session, shop_id, payload,
            source=SOURCE_MOCK_SEED, fetched_at=now_iso,
        )

    return inserted


async def _ensure_rules(session, shop_id: str, now: datetime) -> int:
    n = 0
    for spec in DEFAULT_COMPENSATION_RULES:
        rule_id = f"crule-{shop_id}-{spec['code']}"
        row = (await session.execute(
            select(CompensationRuleRecord).where(CompensationRuleRecord.id == rule_id)
        )).scalar_one_or_none()
        if row is None:
            row = CompensationRuleRecord(id=rule_id)
            session.add(row)
            n += 1
        row.shop_id = shop_id
        row.code = spec["code"]
        row.name = spec["name"]
        row.cause = spec["cause"]
        row.priority = spec["priority"]
        row.conditions = spec["conditions"]
        row.action = spec["action"]
        row.budget_cap = spec["budget_cap"]
        row.enabled = True
        row.notes = spec["notes"]
        row.updated_at = now.isoformat()
    await session.flush()
    return n


# ============================================================
# 入口
# ============================================================

async def seed_trade_if_empty(
    *,
    only_for_shop_ids: Sequence[str] = (),
    now: Optional[datetime] = None,
) -> int:
    """给每家已有店铺灌一份演示数据（幂等；返回「本次**真实新增**订单条数」）。

    返回值是 0 有两种可能，且都是正常的：
      · 守卫拦下了（表里已经有数据，不重复灌）；
      · 灌了，但每一笔都命中幂等键（UPDATE 而非 INSERT）。
    ★ 要单独验证「写入路径本身幂等」，请直接调公开的 `seed_demo_for_shop`
      —— 它不带守卫，连跑两次第二次必须返回 0。

    ★ 幂等守卫沿用 monitors 的约定：
      · 不传 `only_for_shop_ids` ⇒ **全表非空即跳过**；
      · 传了 ⇒ 只看该店铺有无数据，有则不动、无则灌。
    ★ 无 SKU 的店铺直接跳过：订单要有东西指向，灌一笔「买了个不存在的 SKU」
      的订单等于制造新的死数据。
    """
    now = now or datetime.utcnow()
    async with async_session_factory() as session:
        shop_ids = (await session.execute(select(StoreRecord.id))).scalars().all()
        if not shop_ids:
            _log.warning("trade 演示数据跳过：库里没有任何店铺")
            return 0

        if only_for_shop_ids:
            already = set((await session.execute(
                select(OrderRecord.shop_id).distinct()
            )).scalars().all())
            known = set(shop_ids)
            targets = [s for s in only_for_shop_ids if s in known and s not in already]
        else:
            existing = (await session.execute(
                select(func.count()).select_from(OrderRecord)
            )).scalar_one()
            if existing > 0:
                return 0
            targets = list(shop_ids)

        total = 0
        for shop_id in targets:
            anchor = await pick_anchor_sku(session, shop_id)
            if anchor is None:
                _log.warning("trade 演示数据跳过店铺 {}: 产品库里没有任何 SKU", shop_id)
                continue
            total += await seed_demo_for_shop(session, shop_id, anchor, now)
            await _ensure_rules(session, shop_id, now)
            # ★ 两期健康分：没有上一期就没有 delta，「健康分 -0.7」会是空话
            await trade_service.compute_sku_health(
                session, shop_id, anchor["sku"], period_days=30,
                period_end=(now - timedelta(days=30)).isoformat(),
            )
            await trade_service.compute_sku_health(
                session, shop_id, anchor["sku"], period_days=30,
                period_end=now.isoformat(),
            )
            _log.info("trade 演示数据已预置 shop={} anchor_sku={}", shop_id, anchor["sku"])

        await session.commit()
    return total

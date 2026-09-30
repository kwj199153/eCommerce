"""
交易履约域 —— 演示剧本（**唯一真源**）
======================================

★★ 为什么剧本要单独成文件，而不是住在 `seed.py` 里
---------------------------------------------------
同一批演示数据现在有**两个消费者**：

    modules/trade/seed.py                本仓演示预置（空库起来就有数据可看）
    modules/amazon_sp/data_sources/mock_source.py  适配层的 Mock（假装自己是平台）

剧本若各写一份，两份会各自漂移：seed 说「12 天才收到」、Mock 说「14 天」，
两边都跑得通、都不报错，界面上却会出现**同一笔订单两个答案**。
本项目对「同一事实两份实现」的立场一贯是：迟早出错，而且**出错时不报错**。
=> 剧本抽到这里，两个消费者都 import 它。

★★ 为什么时间是「相对今天的偏移」而不是写死的日期
--------------------------------------------------
写死日期 => 三个月后再跑演示，「近 7 天上升 40%」这句会**静默失效**：
数据全在三个月前，统计窗口里一条都没有，流程照跑、结论照出。
用偏移 => 任何时候跑都是新鲜的。

★★ 载荷里为什么**没有** transit_days / delay_days / primary_cause
------------------------------------------------------------------
这里产出的是**平台侧原始数据**。派生态（多久送到 / 迟了几天）与归因
（为什么差评）由**落库方**调 `modules.trade.service` 算（唯一口径），
适配层不许自己算 —— 否则「适配层算一遍 + 落库又算一遍」，又是两份实现。
"""

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional


# ============================================================
# 剧本本体（相对「今天」的天数偏移）
# ============================================================
#: ★ 主剧本：老板演示文案里那笔订单
#:   下单 15 天前 → 发货 14 天前 → 承诺 9 天前到 → 实际 2 天前到
#:   ⇒ transit_days=12（文案说的「12 天才收到」）· delay_days=7（迟到一周）
DEMO_ORDER_SPECS: List[Dict] = [
    {
        "external_order_id": "AMZN123456789",
        "sku_role": "anchor",
        "quantity": 1,
        "unit_price": 29.99,
        "purchase_offset": 15, "ship_offset": 14, "promise_offset": 9, "deliver_offset": 2,
        "order_status": "delivered",
        "buyer_name": "J***n D.",
        "ship_state": "California", "ship_city": "San Jose",
        "carrier": "UPS",
        "tracking_no": "1Z999AA10123456784",
        "ship_status": "delivered",
        "events": [
            {"offset": 14, "status": "LABEL_CREATED",
             "location": "Shenzhen, CN", "description": "Shipment label created"},
            {"offset": 13, "status": "PICKED_UP",
             "location": "Shenzhen, CN", "description": "Carrier picked up the parcel"},
            {"offset": 6, "status": "IN_TRANSIT",
             "location": "Anchorage, AK", "description": "Arrived at sort facility"},
            {"offset": 3, "status": "EXCEPTION",
             "location": "Ontario, CA",
             "description": "Package crushed in transit, outer box damaged"},
            {"offset": 2, "status": "DELIVERED",
             "location": "San Jose, CA", "description": "Delivered, left at front door"},
        ],
        "reviews": [
            {
                "external_review_id": "R1DEMO0001",
                "gold": "none",  # 金标：无风险话术（见 demo_review_gold）
                "rating": 1,
                "offset": 2,
                "title": "Twelve days and the box was destroyed",
                "body": (
                    "Took 12 days to arrive even though the listing promised 5. "
                    "When it finally showed up the outer box was crushed and the "
                    "unit inside has a dent on the lid. Not happy about paying full "
                    "price for something that looks like it fell off a truck."
                ),
            },
        ],
    },
    # ---- 历史同因差评（≥3 条才能构成「重复问题」）----
    {
        "external_order_id": "AMZN123456001",
        "sku_role": "anchor",
        "quantity": 1,
        "unit_price": 29.99,
        "purchase_offset": 52, "ship_offset": 51, "promise_offset": 46, "deliver_offset": 41,
        "order_status": "delivered",
        "buyer_name": "A***a M.",
        "ship_state": "Texas", "ship_city": "Austin",
        "carrier": "FedEx",
        "tracking_no": "794657112233",
        "ship_status": "delivered",
        "events": [
            {"offset": 51, "status": "PICKED_UP", "location": "Shenzhen, CN", "description": "Departed origin"},
            {"offset": 43, "status": "EXCEPTION", "location": "Memphis, TN",
             "description": "Carton crushed, contents may be damaged"},
            {"offset": 41, "status": "DELIVERED", "location": "Austin, TX", "description": "Delivered"},
        ],
        "reviews": [
            {
                "external_review_id": "R1DEMO0002",
                "gold": "none",  # 金标：无风险话术（见 demo_review_gold）
                "rating": 2,
                "offset": 40,
                "title": "Arrived crushed again",
                "body": (
                    "Slow shipping, and the box was crushed on one corner. "
                    "Replacement foam inside was too thin — same problem I read "
                    "about in other reviews."
                ),
            },
        ],
    },
    {
        "external_order_id": "AMZN123456002",
        "sku_role": "anchor",
        "quantity": 2,
        "unit_price": 29.99,
        "purchase_offset": 45, "ship_offset": 44, "promise_offset": 39, "deliver_offset": 34,
        "order_status": "delivered",
        "buyer_name": "R***h K.",
        "ship_state": "Florida", "ship_city": "Orlando",
        "carrier": "UPS",
        "tracking_no": "1Z999AA10998877665",
        "ship_status": "delivered",
        "events": [
            {"offset": 44, "status": "PICKED_UP", "location": "Shenzhen, CN", "description": "Departed origin"},
            {"offset": 35, "status": "DELIVERED", "location": "Orlando, FL", "description": "Delivered"},
        ],
        "reviews": [
            {
                "external_review_id": "R1DEMO0003",
                "gold": "none",  # 金标：无风险话术（见 demo_review_gold）
                "rating": 2,
                "offset": 33,
                "title": "Packaging is the weak point",
                "body": (
                    "Product itself is fine but the packaging was damaged in "
                    "transit and one unit leaked. Please use bubble wrap."
                ),
            },
        ],
    },
    # ---- 一条好评做对照（没有它，「健康分」只剩负样本，分数会失真）----
    {
        "external_order_id": "AMZN123456003",
        "sku_role": "anchor",
        "quantity": 1,
        "unit_price": 29.99,
        "purchase_offset": 20, "ship_offset": 19, "promise_offset": 14, "deliver_offset": 13,
        "order_status": "delivered",
        "buyer_name": "T***y L.",
        "ship_state": "New York", "ship_city": "Brooklyn",
        "carrier": "UPS",
        "tracking_no": "1Z999AA10554433221",
        "ship_status": "delivered",
        "events": [
            {"offset": 19, "status": "PICKED_UP", "location": "Shenzhen, CN", "description": "Departed origin"},
            {"offset": 13, "status": "DELIVERED", "location": "Brooklyn, NY", "description": "Delivered"},
        ],
        "reviews": [
            {
                "external_review_id": "R1DEMO0004",
                "gold": "none",  # 金标：无风险话术（见 demo_review_gold）
                "rating": 5,
                "offset": 12,
                "title": "Keeps coffee hot all morning",
                "body": "Exactly as described, arrived early, no complaints at all.",
            },
        ],
    },
]


# ============================================================
# 演示差评样本（**独立于订单** —— 评论走的是另一条通道）
# ============================================================
# ★★ 为什么不挂在 `DEMO_ORDER_SPECS[].reviews` 上：
#   本文件开头已经定调 —— SP-API 没有 Reviews API，差评来自卖家后台导出或
#   第三方服务，**与订单不是同一条通道**（`upsert_review` 也明写「关联不到
#   订单是常态，不报错」）。这批样本的用途是「让演示与评测有足够的正负样本」，
#   不是为了再造 19 笔假订单 —— 订单那 4 笔的物流时间线是老板演示文案的载体，
#   不该被样本数量牵着改。
#
# ★★ 这批样本**同时服务两件事**，这也是它们必须住在剧本里的原因：
#   ① 演示：风险识别视图里要有足够的「红 / 橙 / 干净」可看；
#   ② 评测：`gold` 是人工金标，用来算风险识别的 P/R/F1。
#   金标与样本**同源**（都由 `demo_review_gold()` 导出）——
#   分成两处写，改样本忘改标签，报告里的「误报」其实是标错了，且报告不会说。
#
# ★★ 五条硬约束（改样本必须同时满足，前三条第 299 轮 P1 定，后两条第 302 轮加）：
#   1. `offset` 全部落在 `list_recent_negative_reviews(days=30)` 窗口内。
#      窗外 = 演示时这些样本压根不出现 —— 老剧本里 R1DEMO0002/0003 的
#      40/33 天偏移就在窗外，于是「20 条」只看得见 1 条。
#   2. 措辞**不得与** `scripts/data/r299_risk_eval_set.json`（开发集）/
#      `r299_risk_eval_holdout.json` **逐字重复** —— 逐字重复等于用训练集
#      考自己，分数好看但没有任何信息量。
#   3. 四类风险各自的**结构化规则必须真能命中**（`risk_scan` 的 `_R1_PROP`
#      ~`_R4_PROP` 等）。否则在「未配置 LLM 凭据」的降级态下这批样本全判负类，
#      演示直接塌 —— 演示不能依赖「本机恰好配了 key」。
#   4. **语域统一**（第 302 轮）：正负类都写成「买家**已公开发布**的评价旁白」，
#      正类**不许**再写成 BidAsk 式的祈使句（"Either you replace…" / "Refund the
#      order in full…"）—— 那是**会话**语域。旧样本正类全是第二人称祈使句、
#      负类全是第三人称体验陈述 ⇒ 正负类按语域可分离，评测满分是自证。
#      ★ 对应的中间产物就是 r1 的旧定义「以**公开差评**为筹码」：这条差评本身
#        已经发布，拿它当筹码是自相矛盾。现在的筹码必须是**还没发生的升级动作**。
#   5. **人称不再是分界线**（第 302 轮）：负类里要有指着卖家鼻子说话的样本
#      （真实评价里 "Your size chart is off by two inches" 很常见），正类里也要有。
#      只看 brainstorm 的羔判断是否有着路径会走到另一个极端 —— 重写第一版
#      就变成了「负类 7/7 全含 you、正类 1/12」，人称照样能分正负，只换了方向。
#      两条支点刻度像塞前的门禁 `test_trade_review_risk_view.py` 第 8 节盯着。
#
# ★ 条数账（`rating <= 3` 且 30 天内）：
#     正类 12（r1/r2/r3/r4 各 3）+ 本批负类 7（r5×4 + none×3）
#     + 剧本里既有的 R1DEMO0001（none）⇒ 合计 **20 条**，正 12 / 负 8。
# ★ 标签取值是**封闭集合**：r1~r5 与 none。`r5` 与 `none` **同为负类**
#   （正类 ⟺ 命中 `risk_scan.RISK_CATEGORIES`）—— 与评测集同一口径。
DEMO_REVIEW_SAMPLES: List[Dict] = [
    # ---------------- r1 加码要挟：筹码（进一步的升级动作）+ 施压 ----------------
    # ★ 第 302 轮：筹码**不能是这条差评本身**（它已经公开发布了，拿已发生的事当
    #   筹码是自相矛盾）。写的是「还没发生的升级」：公开扩散 / 社媒 / 法务。
    {
        "external_review_id": "R1DEMO0101",
        "gold": "r1", "rating": 1, "offset": 1,
        "buyer_name": "M***a P.",
        "title": "Waiting on the replacement nozzle",
        "body": (
            "Third message about the same leaking lid and nobody from your side "
            "has answered one. "
            "Either the replacement shows up this week or I will share my "
            "experience in every group where this listing has been recommended, "
            "screenshots included."
        ),
    },
    {
        "external_review_id": "R1DEMO0102",
        "gold": "r1", "rating": 1, "offset": 4,
        "buyer_name": "D***l R.",
        "title": "Silence for two weeks now",
        "body": (
            "Two weeks about a cracked seal that emptied into my bag and nobody "
            "answers. If this is still unresolved by the weekend I am taking it "
            "to a solicitor about the damage to my laptop."
        ),
    },
    {
        "external_review_id": "R1DEMO0103",
        "gold": "r1", "rating": 2, "offset": 7,
        "buyer_name": "S***h W.",
        "title": "Pictures ready if nothing changes",
        "body": (
            "Eighteen days waiting for a real answer and three replies that all "
            "said the same thing. Each one pushed me further. Fix it this week, "
            "otherwise my next post about this comes with the photos attached."
        ),
    },
    # ---------------- r2 索赔要钱：诉求（要钱）+ 施压 / 要求式 ----------------
    {
        "external_review_id": "R1DEMO0111",
        "gold": "r2", "rating": 1, "offset": 3,
        "buyer_name": "K***n T.",
        "title": "Gave out on the second use",
        "body": (
            "The pump stopped after two uses and your support has gone quiet. I "
            "want my money back on this one, plus the cost of the locker I had "
            "to replace when it leaked."
        ),
    },
    {
        "external_review_id": "R1DEMO0112",
        "gold": "r2", "rating": 2, "offset": 9,
        "buyer_name": "L***a B.",
        "title": "Two of four arrived in pieces",
        "body": (
            "Two of the four tumblers were shattered when the box turned up. "
            "I am asking for the item price back plus compensation for the gift "
            "wrap I had to buy at the last minute instead."
        ),
    },
    {
        "external_review_id": "R1DEMO0113",
        "gold": "r2", "rating": 1, "offset": 13,
        "buyer_name": "J***y C.",
        "title": "Cracked jar, cut hand",
        "body": (
            "The jar arrived cracked and cut my hand while I was opening it. I "
            "expect the full amount back plus the cost of the dressing and the "
            "clinic visit; the bill is here in front of me."
        ),
    },
    # ---------------- r3 A-to-Z 前兆：平台担保筹码 + 推进意图 ----------------
    {
        "external_review_id": "R1DEMO0121",
        "gold": "r3", "rating": 1, "offset": 6,
        "buyer_name": "P***r N.",
        "title": "Twenty-six days, no movement",
        "body": (
            "Twenty-six days since ordering and not once has your dispatch team "
            "answered. Next step is the marketplace protection policy to get "
            "the payment back if it is still not scanned by Friday."
        ),
    },
    {
        "external_review_id": "R1DEMO0122",
        "gold": "r3", "rating": 1, "offset": 11,
        "buyer_name": "A***w G.",
        "title": "Four weeks, still no parcel",
        "body": (
            "Four weeks and nothing has reached my address. Nothing from "
            "support after four messages, so this is going through the buyer "
            "protection route and the charge will be reversed through them."
        ),
    },
    {
        "external_review_id": "R1DEMO0123",
        "gold": "r3", "rating": 2, "offset": 16,
        "buyer_name": "C***s V.",
        "title": "Tracking frozen eleven days",
        "body": (
            "Tracking has been frozen for eleven days and nobody replies to "
            "messages anymore. Unless something moves today I am opening a "
            "claim against the marketplace purchase protection."
        ),
    },
    # ---------------- r4 开 case / 投诉平台：动作 + 靶子 ----------------
    {
        "external_review_id": "R1DEMO0131",
        "gold": "r4", "rating": 1, "offset": 8,
        "buyer_name": "R***t F.",
        "title": "Three weeks past the promised window",
        "body": (
            "The listing promised two-day shipping; it has been three weeks. "
            "Every screenshot is still on my phone and I have reported it to "
            "Amazon support as a misleading listing."
        ),
    },
    {
        "external_review_id": "R1DEMO0132",
        "gold": "r4", "rating": 2, "offset": 15,
        "buyer_name": "B***e H.",
        "title": "Advertised 20oz, arrived 14oz",
        "body": (
            "Advertised as 20oz and what turned up holds 14oz. Your listing is "
            "misleading, so I have filed a complaint with the platform support "
            "team and flagged it at the same time."
        ),
    },
    {
        "external_review_id": "R1DEMO0133",
        "gold": "r4", "rating": 1, "offset": 20,
        "buyer_name": "T***m S.",
        "title": "No parcel, no reply, three weeks",
        "body": (
            "Three weeks without the parcel and three messages without an "
            "answer. Next step is the consumer protection office here, and my "
            "credit card company after that."
        ),
    },
    # ---------------- r5 高情绪差评：**不是风险话术**，候选池 ----------------
    # ★ 第 302 轮：这几条刻意指着卖家说话。旧负类全是「东西怎么样」的体验陈述，
    #   正类全是对卖家喊话 ⇒ 「有没有对着卖家说话」成了一条免费的分类捷径。
    {
        "external_review_id": "R1DEMO0141",
        "gold": "r5", "rating": 1, "offset": 5,
        "buyer_name": "G***l M.",
        "title": "Absolutely ridiculous for the money",
        "body": (
            "You would think something at this price survives a week. It did "
            "not. Cheapest plastic I have handled and a complete waste of "
            "money, straight in the bin."
        ),
    },
    {
        "external_review_id": "R1DEMO0142",
        "gold": "r5", "rating": 1, "offset": 10,
        "buyer_name": "N***l K.",
        "title": "NEVER AGAIN",
        "body": (
            "Two weeks in and the handle has already come loose. Garbage "
            "finish and I am furious that this passed any quality check at all."
        ),
    },
    {
        "external_review_id": "R1DEMO0143",
        "gold": "r5", "rating": 2, "offset": 18,
        "buyer_name": "F***a O.",
        "title": "Terrible finish, mould lines everywhere",
        "body": (
            "The lid cracked on day three and now the whole thing rattles like "
            "a disposable cup. The mould lines are visible from across the "
            "room and the whole thing feels terrible. What a waste of an order."
        ),
    },
    {
        "external_review_id": "R1DEMO0144",
        "gold": "r5", "rating": 2, "offset": 24,
        "buyer_name": "H***d E.",
        "title": "Appalled by the smell",
        "body": (
            "Appalled. Sharp edges on the rim, a handle that rocks, and it "
            "smelled of solvent straight out of the box. Not worth a quarter "
            "of the asking price."
        ),
    },
    # ---------------- none 干净差评：既无风险话术、也无强情绪 ----------------
    {
        "external_review_id": "R1DEMO0151",
        "gold": "none", "rating": 3, "offset": 14,
        "buyer_name": "V***c A.",
        "title": "Colour is darker than the photos",
        "body": (
            "The tumbler does its job and keeps drinks hot for hours, but the "
            "blue you see in your listing photos is much darker in person. "
            "Worth knowing before you order, not a deal breaker."
        ),
    },
    {
        "external_review_id": "R1DEMO0152",
        "gold": "none", "rating": 2, "offset": 22,
        "buyer_name": "E***n J.",
        "title": "Seal gave up after a month",
        "body": (
            "It held heat beautifully for the first month, then the seal "
            "failed and now it drips a little if I tip it. Everything else "
            "still works, though you do have to keep it upright."
        ),
    },
    {
        "external_review_id": "R1DEMO0153",
        "gold": "none", "rating": 3, "offset": 27,
        "buyer_name": "O***r Z.",
        "title": "Runs small against the size chart",
        "body": (
            "Runs smaller than the size chart suggests - worth ordering one size "
            "up for anyone between sizes. The build itself is fine and it "
            "arrived a day early."
        ),
    },
]


#: 平台侧 SKU 兜底 —— **没有产品库可查时**用什么。
#: ★ 这是卖家在亚马逊后台自己的 SKU 命名，本仓产品库里查不到完全正常：
#:   `db_model.py` 文件头已定调，`sku` 故意不建外键指向 `skus` 表，
#:   理由是「不能因为本地产品库少一行就让整笔订单插不进来」。
DEMO_FALLBACK_SKU = "KITCH-002-BLUE"
DEMO_FALLBACK_ASIN = "B0CXXXX009"
DEMO_FALLBACK_TITLE = "Insulated Coffee Mug 20oz Stainless Steel Travel Tumbler (Blue)"


def _iso(base: datetime, offset_days: Optional[int]) -> Optional[str]:
    """把「N 天前」展开成绝对 ISO 串（None 表示这个时间点还没有发生）。"""
    if offset_days is None:
        return None
    return (base - timedelta(days=offset_days)).isoformat()


def _resolve_anchor(spec: Dict, sku_resolver: Optional[Callable[[Dict], Dict[str, str]]]) -> Dict[str, str]:
    """决定这笔订单/评论落在哪个 SKU 上。

    ★ 有 resolver（seed 传）=> 用**该店铺产品库里真实存在的 SKU**，
       「说得出来」就「指得到行」；没有（Mock 数据源）=> 用平台侧兜底命名。
    """
    if sku_resolver:
        got = sku_resolver(spec)
        if got and got.get("sku"):
            return got
    return {"sku": DEMO_FALLBACK_SKU, "asin": DEMO_FALLBACK_ASIN,
            "title": DEMO_FALLBACK_TITLE}


def build_demo_order_payloads(
    now: Optional[datetime] = None,
    sku_resolver: Optional[Callable[[Dict], Dict[str, str]]] = None,
) -> List[Dict]:
    """把剧本展开成**平台侧订单载荷**（orders + order_items + shipments 三合一）。

    Args:
        now: 基准时间。★ 可注入 —— 测试才能钉住绝对值，而不是「大概这几天」。
        sku_resolver: 见 `_resolve_anchor`。

    Returns:
        载荷列表，字段与 `orders` / `order_items` / `shipments` 三张表对齐。
        ★ **不含**派生态（transit_days / delay_days）—— 由落库方用 service 算。
    """
    base = now or datetime.utcnow()
    out: List[Dict] = []
    for spec in DEMO_ORDER_SPECS:
        anchor = _resolve_anchor(spec, sku_resolver)
        external = spec["external_order_id"]
        qty = int(spec["quantity"])
        unit = float(spec["unit_price"])

        events = [
            {
                "at": _iso(base, e["offset"]) or "",
                "status": e["status"],
                "location": e["location"],
                "description": e["description"],
            }
            for e in spec.get("events", [])
        ]
        last_event = events[-1] if events else None

        out.append({
            # ---- orders ----
            "external_order_id": external,
            "platform": "amazon",
            "marketplace": "US",
            "buyer_id": "",
            "buyer_name": spec["buyer_name"],
            "order_status": spec["order_status"],
            "fulfillment_channel": "FBA",
            "ship_country": "US",
            "ship_state": spec["ship_state"],
            "ship_city": spec["ship_city"],
            "currency": "USD",
            "order_total": round(unit * qty, 2),
            # ---- 时间轴（原始事实，派生态由落库方算）----
            "purchase_at": _iso(base, spec["purchase_offset"]) or "",
            "promised_at": _iso(base, spec["promise_offset"]),
            "shipped_at": _iso(base, spec["ship_offset"]),
            "delivered_at": _iso(base, spec["deliver_offset"]),
            # ---- order_items ----
            "items": [{
                "external_order_item_id": f"{external}-1",
                "sku": anchor["sku"],
                "asin": anchor["asin"],
                "item_title": anchor["title"],
                "image": "",
                "quantity": qty,
                "currency": "USD",
                "unit_price": unit,
                "item_total": round(unit * qty, 2),
            }],
            # ---- shipments ----
            "shipment": {
                "carrier": spec["carrier"],
                "tracking_no": spec["tracking_no"],
                "ship_status": spec["ship_status"],
                "shipped_at": _iso(base, spec["ship_offset"]),
                "promised_at": _iso(base, spec["promise_offset"]),
                "delivered_at": _iso(base, spec["deliver_offset"]),
                "last_event_at": (last_event or {}).get("at", ""),
                "last_location": (last_event or {}).get("location", ""),
                "last_event_text": (last_event or {}).get("description", ""),
                "events": events,
            },
            "raw": {"script": "demo", "spec_offsets": {
                "purchase": spec["purchase_offset"], "ship": spec["ship_offset"],
                "promise": spec["promise_offset"], "deliver": spec["deliver_offset"],
            }},
        })
    return out


def build_demo_review_payloads(
    now: Optional[datetime] = None,
    sku_resolver: Optional[Callable[[Dict], Dict[str, str]]] = None,
) -> List[Dict]:
    """把剧本里的 `reviews` 抽平成**平台侧评论载荷**。

    ★ 为什么与订单**分开**返回：真实世界里评论根本不走订单那条通道 ——
      SP-API 没有 Reviews API（已对第三方关闭），差评只能来自卖家后台导出
      或第三方数据服务。两条通道各自能独立失败，载荷也就必须能独立取。

    ★ `order_ref` 是**平台侧订单号**（不是自家 `orders.id`）：能不能关联上
      由落库方查表决定，关联不到就留空 —— 评论未必能反查到订单。
    """
    base = now or datetime.utcnow()
    out: List[Dict] = []

    def _emit(rv: Dict, anchor: Dict[str, str], order_ref: str, buyer: str) -> None:
        """把一条评论规格展开成平台侧载荷。

        ★ 「挂订单的」与「不挂订单的」共用本函数：字段口径写两份 ⇒
          改一处忘一处，两条通道落库的行长得不一样且都不报错。
        """
        rating = int(rv["rating"])
        out.append({
            "external_review_id": rv["external_review_id"],
            "platform": "amazon",
            "marketplace": "US",
            "order_ref": order_ref,
            "sku": anchor["sku"],
            "asin": anchor["asin"],
            "product_title": anchor["title"],
            "rating": rating,
            "title": rv["title"],
            "body": rv["body"],
            "language": "en",
            "review_at": _iso(base, rv["offset"]) or "",
            # ★ 默认 True（挂订单那批的原行为）；独立样本可显式声明 False
            #   —— 「没有订单却标已验证购买」是自相矛盾的数据形态。
            "verified_purchase": bool(rv.get("verified_purchase", True)),
            # ★ 确定性取值（不用 random）：差评票多、好评票少，
            #   否则同一份剧本两次跑出来的「有用票数」不一样，无法对账。
            "helpful_votes": 12 if rating <= 2 else 3,
            "images": [],
            "buyer_name": buyer,
            "raw": {"script": "demo"},
        })

    for spec in DEMO_ORDER_SPECS:
        anchor = _resolve_anchor(spec, sku_resolver)
        for rv in spec.get("reviews", []):
            _emit(rv, anchor, spec["external_order_id"], spec["buyer_name"])

    # ★ 独立样本：同一份剧本、**另一条通道**。
    #   为何 `order_ref=""`：评论反查不到订单是常态（见本函数文档与
    #   `upsert_review` 的同名约定），不是错误。
    for sample in DEMO_REVIEW_SAMPLES:
        anchor = _resolve_anchor(sample, sku_resolver)
        _emit(sample, anchor, "", str(sample.get("buyer_name") or ""))

    return out


def demo_review_gold() -> Dict[str, str]:
    """演示差评的**金标标签**（`external_review_id -> r1..r5|none`）—— 唯一真源。

    ★ 为什么金标必须与样本**同源**：样本与标签分两处写，改样本忘改标签 ⇒
      评测报告里的「误报」其实是标错了，而报告自己不会说这件事。
    ★ 标签取值是**封闭集合**（`r1`~`r5` 与 `none`），口径与评测集一致：
      **正类 ⟺ 命中 `risk_scan.RISK_CATEGORIES`（四类风险话术）**，
      `r5`（高情绪）与 `none` **同为负类**。
    ★ 样本总体 = **中差评**（`rating <= 3` 且落在 30 天窗口内）。
      好评（如剧本里的 R1DEMO0004）也带标签，但它不在总体内 ——
      调用方按 rating 自行收敛，本函数不替调用方决定口径。
    """
    gold: Dict[str, str] = {}
    for spec in DEMO_ORDER_SPECS:
        for rv in spec.get("reviews", []):
            gold[rv["external_review_id"]] = str(rv.get("gold") or "")
    for sample in DEMO_REVIEW_SAMPLES:
        gold[sample["external_review_id"]] = str(sample.get("gold") or "")
    return gold

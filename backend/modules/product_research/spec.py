"""选品大盘（市场洞察快照）的声明式查询元数据。

★ 为什么大盘需要一个 spec（本轮 · 第 325 轮）
==============================================================================
老板的原话：「他不是有选品大盘吗 为什么会回答不出来这个问题」
          「让 agent 可以读数据库，**解耦前端界面大盘**」

改前这份数据**只有一条消费通道**：前端 `MarketInsightConfig.vue` 通过
`GET /product-research/market-insight/treemap` 拿数据，而那个端点的查询是
`service.get_market_insight_treemap()` 里**手写**的（`select(...)` + `scoped()`
+ 内存 `seen` 集合去重）。Agent 侧**没有任何工具**能读这张表 ⇒
「现在哪个品类蓝海分最高」必然答不出来，只能回落到关键词短路去挖蓝海。

本 spec 把「查什么、按什么排、怎么去重、总共几条」收成**唯一真源**，
两条通道（前端端点 / Agent 工具）都走 `core.library_query` 内核 ⇒
面板上的数字与对话里的数字**必然一致**（本仓铁律：同一判定两份实现 ⇒
至少一份永远测不到）。

★ `dedup_key` 必须是 `(site, category_path)` —— 这是**业务粒度**，不是随手填的
==============================================================================
`market_snapshots` 是**时序表**：同一个 (站点, 类目) 每个 `snapshot_date` 一行
（seed 里有 `2026-08-29` 与 `2026-09-29` 两批）。
内核的默认 `dedup_key=None` = **完全不去重** ⇒ 同一个类目会出现两次、
`total` 虚高、Top-N 被同类目的旧行占掉。
「大盘取最新一天」的口径就是：**同一 (site, category_path) 取最新快照那一行**。

★ 为什么不按 `category_name` 去重：末级类目名会跨站点重名
  （`lighting` 在 amazon_us 与 amazon_uk 各有一条），按名字归并会把两个站点的
  数字塌成一条 —— **那是丢数据，比重复更糟**（同族教训见 `candidates` 的空 ASIN）。

★ `dedup_order` **必须显式给**，且与改前的内存去重口径**逐字对齐**
==============================================================================
内核默认 `dedup_order=("updated_at" desc, "id" desc)`。而本表是**批量 seed**
写进去的 ⇒ 同一批行的 `updated_at` 几乎同值 ⇒ 「保留哪一条」由 `id` 决定，
也就是**不确定**：数字会在 8 月那批与 9 月那批之间随机跳。

改前的内存去重是「`ORDER BY snapshot_date DESC, blue_ocean_score DESC` 之后
**首个命中即保留**」⇒ 保留的行 = 按 `(snapshot_date, blue_ocean_score)` 的
字典序**最大**者。所以 `dedup_order` 必须写成**三键**：

    (("snapshot_date", "desc"), ("blue_ocean_score", "desc"), ("id", "desc"))

★ 中间那个 `blue_ocean_score` 不是凑数，是第 325 轮的探针**逼出来的**：
  只写 `(snapshot_date, id)` 时，「同一天有两条同 (站点, 类目)」（数据异常，
  但内核必须给一个确定的答案）会出现**真实分歧** —— 改前取**分高**那条、
  改后取 **id 大**那条。补上中间键后两边一致；
  `id` 退到第三位，只在前两键都打平时兜底，比改前「取决于 DB 返回顺序」**更**确定。
  判据：`.workbuddy/probes/r325/r325_b3_parity_nodb.py` 第 7 节
  （种子里刻意让 `id` 的降序与分数的降序**相反**，否则这条判据测不出东西）。

★ `default_sort` 与改前 REST 的差异（有意为之，逐条记明）
==============================================================================
改前 treemap 端点的排序是 `snapshot_date desc, blue_ocean_score desc`（内存去重前）。
去重之后，「取最新快照」已经由 `dedup_order` 承担，剩下的排序意图只有一条：
**蓝海机会大的在前** ⇒ `default_sort="blue_ocean_score"`。
⇒ 可观察差异**只有一处**：`nodes` 的**数组顺序**。

★ ★ 这一处顺序差异 **不是**「对界面不可见」—— 本段第一版写错了，留痕
--------------------------------------------------------------------------
第一版我写的理由是「treemap 面积 = 搜索热度、颜色 = 蓝海评分，不消费数组顺序」。
**这个论证只覆盖了云图那一半**。同一个文件 `MarketInsightConfig.vue` 的
`reload()` 里还有一处**读 `nodes.value[0]`**：

    // 默认选中第一个类目，六维度明细有落脚点
    if (nodes.value.length && !selectedKey.value) {
      const first = nodes.value[0]
      selectedKey.value = `${first.site}|${first.category_path}`
    }

⇒ 「默认选中的类目」= 右侧六维度 KPI 明细的落脚点，**就是被数组顺序决定的**。

  · 改前：`nodes[0]` = 最新快照日里蓝海分最高的那条
  · 改后：`nodes[0]` = **蓝海分最高的那条**（`default_sort` 直接保证）

结论：这不是丢行为，是**把默认项换成更有意义的那一个** —— 面板默认落在
「最值得进的类目」上，也正是老板那句「现在哪个品类蓝海分最高」的答案。

★ 但它是**契约**、不是巧合：前端依赖「`nodes` 按 `blue_ocean_score` 降序」，
  该保证的唯一真源就是本 spec 的 `default_sort` ⇒ **改它会同时改掉面板默认选中项**，
  动它时必须回到这里对账。判据：同一份探针断言该序列**非递增**。

端点响应形状（`nodes` / `total_categories` / `degraded` / `source` / `message`）
与 node 的 15 个键**逐字段未动**（由同一份探针拿改前实现逐字段比对）。

★ 过滤维度：内核只做**等值**匹配，没有前缀 / 模糊匹配
==============================================================================
`category_path` 因此登记为**自由文本**（不挂值域）：
  · 路径是开放的（`home_kitchen/kitchen_dining/coffee` 这种，写多少层由数据决定），
    没法枚举成白名单；
  · 但它只能**精确**匹配 —— 「找厨房用品的蓝海机会」这种**类目关键字**问法，
    老板拍板的修法是「**交给 LLM 认**」：工具 description 明确写清「不支持模糊匹配，
    不确定就先不带这个参数把类目列表取回来自己挑」，
    而不是扩内核加一种匹配模式（那是另一份查询实现）。
`site` / `price_trend` 的值域**不是抄来的**，是从
`modules/product_research/seed.py` 的真实取值逐个点出来的：
  · `site`：`amazon_us` / `amazon_uk` / `shopee_sg`
  · `price_trend`：`rising` / `stable` / `falling`
  给了值域 ⇒ 传值域外的值**显式报错**，不再静默回空列表（第 216 轮 ③ 的教训：
  「真的没有」与「你传错了」被压成同一个结果，归因错方向）。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.product_research.db_model import MarketSnapshotRecord

#: 选品大盘的**声明式元数据**（唯一真源）—— REST 端点与 Agent 工具同走它。
MARKET_SNAPSHOT_SPEC = LibrarySpec(
    key="market_snapshots",
    label="选品大盘（市场洞察快照）",
    model=MarketSnapshotRecord,
    # ★ 排序白名单：8 个维度全部对应「面板上真有数据的那几列」——
    #   这样才能做到「一张工具覆盖老板可能问的所有大盘问题」，而不是按问句造工具。
    sort_fields={
        # 蓝海机会：分越高越值得进（面板默认口径）
        "blue_ocean_score": ("blue_ocean_score", "desc"),
        # 搜索热度：需求侧规模
        "search_volume": ("search_volume", "desc"),
        # 搜索增长率：趋势侧
        "search_growth": ("search_growth", "desc"),
        # 价格带中位数：客单价侧
        "price_median": ("price_median", "desc"),
        # ↓ 竞争侧三个维度都是**越小越好** ⇒ 升序（与「越大越好」方向相反）
        "listing_count": ("listing_count", "asc"),
        "seller_count": ("seller_count", "asc"),
        "new_seller_count": ("new_seller_count", "asc"),
        # 快照日期：看「哪批数据」用（正常读大盘不需要按它排）
        "snapshot_date": ("snapshot_date", "desc"),
    },
    default_sort="blue_ocean_score",
    filters={
        "site": FilterSpec("site", ("amazon_us", "amazon_uk", "shopee_sg")),
        "price_trend": FilterSpec("price_trend", ("rising", "stable", "falling")),
        # ★ 自由文本（**精确**匹配，不是模糊）：理由见模块 docstring 末节。
        "category_path": FilterSpec("category_path"),
    },
    # 去重粒度 = 业务粒度：同一 (站点, 类目) 只留最新快照那一行。
    dedup_key=lambda M: (M.site, M.category_path),
    # ★ 必须显式给：内核默认按 `updated_at`，而批量 seed 的 `updated_at` 几乎同值
    #   ⇒ 保留哪一行不确定、数字会随机跳。见模块 docstring。
    # ★ 三键：中间那个 `blue_ocean_score` 让「同一天重复行」也与改前的内存去重一致。
    dedup_order=(
        ("snapshot_date", "desc"),
        ("blue_ocean_score", "desc"),
        ("id", "desc"),
    ),
)

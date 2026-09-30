"""工具目录 —— 「这个技能能配套哪些工具」的**唯一真源**（第 185 轮 · 批 A）

==============================================================================
★ 为什么需要这张表
==============================================================================
第 185 轮老板原话：

    那用户怎么知道有哪些工具呢？目前是让用户自己写工具名

在此之前，技能编辑页的「工具定义」是一个 `mode="tags"` 的**自由文本输入框**：
租户能填任意字符串，而后端 `service._normalize_tools` 只做「去空 / 去重 / 保序」，
**不校验存在性**。更糟的是那个输入框的 placeholder 举例是 `export_report` ——
**这个工具全仓不存在**（占位符在教用户填一个错的）。

⇒ 用户既不知道该填什么，填错了也没有任何反馈，而"填了不生效"是静默的。
本表就是那个「该填什么」的答案，`GET /api/v1/tools` 把它下发给界面。

==============================================================================
★ 与 `agents.py::AGENT_CATALOG` 是**同一套范式**（照抄它，别另发明）
==============================================================================
| | `AGENT_CATALOG`（第 181 轮） | `TOOL_CATALOG`（本轮） |
|---|---|---|
| 解决 | 前端 id ↔ 后端 agent_name 两套 ID | 「哪些工具真的存在且真的绑上了」 |
| 形态 | 手写表 + 门禁钉住 | 手写表 + 门禁钉住 |
| 下发 | `GET /api/v1/agents` | `GET /api/v1/tools` |
| 门禁 | `tests/test_skill_agent_catalog.py` | `tests/test_tool_catalog.py` |

★ 为什么**手写**而不是运行时从装配点取：
  工具自己的 `description` 是写给**模型**看的（「当用户想算利润时使用」这类引导语），
  而本表要的是写给**人**看的（租户在勾选界面上判断"我要不要这个工具"）。
  两者受众不同，自动派生只会得到一个模型腔的句子。
  ⇒ 手写内容 + 门禁钉住**名字集合与副作用判定**，兼顾可读性与防漂移。

==============================================================================
★ 表里放什么、不放什么（判据：装配点）
==============================================================================
**只放「源码里 `BaseAgent(tools=...)` 实参命名的容器」里的工具。**

本轮实测真源（`probes/o185_tools.txt`，运行时取，非 AST 近似）：

    ListingGenerator   modules.listing_generator.tools.listing_tools             8
    ProductResearcher  modules.product_research.tools.product_research_tools     8 + 2（共用）
    review_analyst     modules.review_analyst.tools.review_analyst_tools         5 + 1（复盘库读口）
    secretary          navigation + subscription + build_product_tools() + build_shop_tools()  10 + 2（共用）
    competitor_intel   modules.competitor_intel.tools.competitor_intel_tools     8   ← 第 198 轮接线
    ad_analysis        modules.ad_analysis.tools.ad_analysis_tools               4   ← 第 204 轮接线（第 316 轮 6 → 4）
    AIGC 媒体生成器     modules.aigc_media.tools.aigc_tools                       9   ← 第 204 轮接线
    智能客服            modules.customer_service.tools.customer_service_tools     4   ← 第 204 轮接线
    library            modules.library.tools.build_library_tools()               6   ← 第 218 轮扩到 6 库（跨 Agent 共用）
    ────────────────────────────────────────────────────────────────────────────
    去重合计 = 61（其中 6 个是**跨 Agent 共用**：`list_candidates` / `list_products` /
    `list_assets` / `list_monitors` / `list_faqs` / `list_platform_rules`；
    这 6 个各自挂在 2 家名下 ⇒ 装配点原始计数 = 61 + 6 = 67）。
    ★ 第 243 轮：59 → 60，新增的是店秘书的**只读** `list_shops`（无副作用 ⇒
      上面的「4 个需审批」分子不变，见 `tests/test_tool_catalog.py`）。
    ★ 第 251 轮：60 → 61，新增的是运营复盘师的**只读** `list_reviews`
      （读「资料库 → 复盘库」里已归档的历史复盘；无副作用 ⇒ 分子仍为 4）。
      ★ 它**不是**第 7 项复盘能力：那 6 项是「算」，它是「读」——
        存在理由是让「下一期复盘读到上期做对比」在数据层成立。
    ★ 第 316 轮：广告分析师 6 → **4**（退役 `optimize_budget` /
      `detect_ad_anomalies`）。★ 上面那两行「去重合计 / 原始计数」
      **只是第 251 轮的历史快照**，此后又有多轮增删未回填 ⇒ 以门禁
      `tests/test_tool_catalog.py` 的实测为准：本轮 66 → **64**。
    ★ 第 325 轮：64 → **65**，新增选品分析师的**只读** `query_market_insight`
      （读选品大盘 `market_snapshots`：蓝海评分 / 搜索量 / 搜索增长 / 价格带 /
      卖家数 / 在售 ASIN 数…）。老板「让 agent 可以读数据库，**解耦前端界面大盘**」
      ⇒ 这份数据从「只有前端面板一条通道」变成「面板与对话同走
      `MARKET_SNAPSHOT_SPEC` 这一份声明」。
      只读 ⇒ 上面那个需审批的**分子仍为 5**（由 `tests/test_tool_catalog.py` 钉住）。

★ 为什么必须**运行时**取而不能靠 AST 扫：
  秘书的 `product_tools` / `shop_tools` 是 `build_product_tools(shop_id)` 这类
  **工厂函数动态构造**的 —— AST 只能看到工厂名，看不到它产出哪些工具。
  上一轮探针就是因为只 AST 扫模块属性，漏读了秘书 3 个模块，
  让「真接线工具数」在 25 / 28 之间摆动了两次。留此记录。

★ 第 204 轮接线后，**当时被排除的那 19 个已全数登记**：
  原文这一节讲的是「为什么不放 `ad_analysis` 6 / `aigc_media` 9 /
  `customer_service` 4」—— 那时它们**注册了但没有任何 Agent 绑定**
  （全仓 `from ... import ad_analysis_tools` 零命中），放进来 = 让租户勾一个
  **调不起来**的工具，那比不给勾更糟（他会以为配好了）。
  第 204 轮把这 19 个接到了各自的 `_build_router()`（范式 A）⇒ 收录条件满足，
  本条**随之失效**，全数登记。
  ★ 这 19 个**不是新增的业务能力**，是原本就有、只是没交给 Agent 的能力 ——
    `docs/orphan-tools-19-r203.md` 记了实测：后端落地率 19/19 = 100%，
    tools 的 service 出口 ⊆ router 的 service 出口（差集 0）。
  `_fine_grained_tools` / `_coarse_grained_tools` 不进本表则是**另一回事**：
  它们**有** Agent 绑定（`listing_tools = 两者相加`，挂在 `_build_router()`），
  只是作为**内部构件**本来就不该出现在租户界面。

★ 不放机制型工具（`load_skill`）：那是渐进披露的**机制**，不是业务能力。
  它由 `ai_infra.skills.build_skill_tools()` 恒装在每个 Agent 上，与技能绑定无关。

==============================================================================
★ 副作用档（`effect` 字段）
==============================================================================
取值只有两个（真源是工具自己的 `metadata`，见 `ai_infra/tools/side_effects.py`）：

    "read_only"  —— 免人工审批（`metadata={"side_effects": False}`）
    "approval"   —— 有外部副作用，每次调用弹人工审批（未声明 / 声明 True）

61 个里只有 4 个是 `approval`：`save_candidate`（写选品库）、`review_candidate` /
`approve_candidate`（第 205 轮批 B 接入的候选评审写工具）与 `create_ticket`
（建客服工单）。★ `create_ticket` **本来就有**副作用，第 204 轮随
`customer_service_tools` 接线才第一次出现在可勾选清单里 —— 不是新增了写库工具，
是它终于露面了。
界面必须把它们标出来：租户勾了 = 这个技能每次执行都会弹审批。
★ 沿革（第 207 轮更正）：原文 28 → 第 204 轮接线 19 个后 55 →
批 A 收敛「同端点多名」后「57 里 2 个」→ 批 B 接入候选生命周期三条后
「60 里 4 个」→ 第 207 轮退役竞品 5 条后「55 里 4 个」→
**第 218 轮资料库扩到 6 库后「59 里 4 个」**（+4 条全是只读 ⇒ 分子仍为 4）→
**第 243 轮新增只读 `list_shops` 后「60 里 4 个」**（分子仍为 4）→
**第 251 轮新增只读 `list_reviews`（复盘库读口）后「61 里 4 个」**（分子仍为 4）。
★ 报数必须说清口径：**分母在变，分子（真写库的那 4 个）一直没变**。

★ `effect` 与运行时 `has_side_effects()` 的一致性由门禁双向钉住 ——
  写错方向是：把有副作用的标成只读 ⇒ 用户以为不弹审批（危险方向）。

==============================================================================
★ 谁来消费
==============================================================================
  · `GET /api/v1/tools`                —— 技能编辑页「配套工具」勾选的数据源
  · `service._validate_tools`          —— 写口拒绝未注册的工具名（修掉 `export_report` 类缺陷）
  · `ai_infra.skills.render_skill_body`—— 正文里渲染「本技能配套工具」（**让勾选真的生效**）

==============================================================================
★ 收敛「同端点多名」：一个能力只留一个工具名（第 205 轮）
==============================================================================
第 204 轮的原子工具盘点发现两组「同后端能力、被不同 Agent 提议成不同名字」：

    GET /api/v1/candidates   → `list_candidates`（选品分析师 / 店秘书，同名）
    GET /api/v1/skus         → `list_products`（选品分析师 / 店秘书）
                               `list_skus`（Listing 优化师）   ← 同一件事的第二个名字

按「同一判定两份实现 ⇒ 至少一份永远测不到」这条既有判据，第 205 轮裁决：
**一个能力只留一个工具名，该工具注册给多家 Agent 共用同一份实现。**

落地形态就是下面条目里的 `agents` 字段：

    {"agent": "ProductResearcher", "agents": ["ProductResearcher", "secretary"],
     "name": "list_candidates", …}

  · `agent`  —— 主归属（展示分组的第一顺位，向后兼容）；
  · `agents` —— 归属**全集**，缺省 = `[agent]`。`grouped_catalog()` 会把它
    同时列在每一家的分组里（`tools_for_agent` 按归属集合匹配）。

★ 为什么不是「写两条目录项」：两条 = 两份 `title`/`description`/`effect`，
  必然漂移。一份条目 + 一个归属集合，结构上就不可能有第二个定义。

★ 落选名字去哪了：`REJECTED_TOOL_ALIASES`（本文件下方）。它们被登记为
  **禁名**，门禁 `tests/test_tool_catalog.py::test_rejected_aliases_never_appear`
  会逐名搜「目录 + 全仓运行时工具集」—— 有人重新捡起落选名 ⇒ 红。

★ 谁在保证「声明了共用就真的共用」：
  `tests/test_shared_tool_convergence.py` 两条判据 ——
    ① `..._exactly_as_many_agents_as_declared`：`agents` 必须**逐字等于**
       运行时真值里「手里真有这个工具」的 Agent 集合（双向，多一个少一个都红）；
    ② `..._exactly_one_implementation`：同名工具在不同 Agent 手里，
       底层实现必须是**同一个函数**（按 `(模块, 限定名)` 比对）——
       「两家各写一份同名工具」会直接转红。
"""

from typing import Any, Dict, List, Optional, Tuple

from modules.skills.agents import AGENT_CATALOG

#: 副作用档取值（与 `ai_infra.tools.side_effects` 的判定对应）
EFFECT_READ_ONLY = "read_only"
EFFECT_APPROVAL = "approval"

#: 平台工具目录。**顺序即界面展示顺序**（按 Agent 分组后，组内保持本表顺序）。
#:
#: 字段：
#:   agent       —— 后端 `agent_name`（必须是 `AGENT_CATALOG` 里的值，门禁钉住）
#:   name        —— 工具名（**存进 `skills.tools` 的值**，即模型看到的函数名）
#:   title       —— 展示名（中文短语，界面上一行一个）
#:   description —— 一句话说明（写给**人**看：这个工具解决什么问题）
#:   effect      —— `read_only` / `approval`（见模块 docstring）
#:   agents      —— **可选**：跨 Agent 共用时的归属全集（缺省 = 只有 `agent` 那一个）。
#:                  ★ 第 205 轮引入，理由见模块 docstring「收敛同端点多名」一节：
#:                    同一个能力**只允许一个工具名**，多家 Agent 共用同一份实现。
TOOL_CATALOG: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------
    # Listing 优化师（8）—— modules.listing_generator.tools.listing_tools
    # ------------------------------------------------------------------
    {
        "agent": "ListingGenerator",
        "name": "optimize_listing_title",
        "title": "标题优化",
        "description": "优化 Listing 标题，返回 SEO 改进版、字符数与 SEO 评分。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "generate_bullet_points",
        "title": "五点描述",
        "description": "为产品生成五点描述（卖点）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "generate_product_description",
        "title": "详情描述",
        "description": "为产品生成详情描述，可含 HTML 富文本。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "generate_search_terms",
        "title": "后台搜索词",
        "description": "基于标题生成后台搜索词（Search Terms）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "generate_complete_listing",
        "title": "整套 Listing",
        "description": "从零生成一整套 Listing：标题 + 五点 + 描述 + 关键词 + SEO 评分。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "optimize_listing",
        "title": "整体优化建议",
        "description": "分析现有 Listing 并给出逐项优化建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "analyze_listing_seo",
        "title": "SEO 诊断",
        "description": "对现有 Listing 做 SEO 诊断评分。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ListingGenerator",
        "name": "generate_ab_test_variants",
        "title": "A/B 测试变体",
        "description": "生成多个可用于 A/B 测试的标题变体。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # 选品分析师（9）—— modules.product_research.tools.product_research_tools
    # ------------------------------------------------------------------
    {
        "agent": "ProductResearcher",
        "name": "analyze_blue_ocean",
        "title": "蓝海品类挖掘",
        "description": "按低竞争 + 有需求 + 有利润的标准筛选候选商品，返回蓝海评分排序列表。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "name": "analyze_profit",
        "title": "利润测算",
        "description": "按售价、成本、FBA 费用、广告费计算净利润 / ROI / 盈亏平衡点。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "name": "analyze_pain_points",
        "title": "评论痛点分析",
        "description": "分析某商品 ASIN 的用户评论，提炼痛点与改进方向。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "name": "compare_competitor_listings",
        "title": "竞品 Listing 对比",
        "description": "对比多个竞品 ASIN 的 Listing 质量、价格与优劣势，给出参考建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "name": "save_candidate",
        "title": "加入选品库",
        "description": "把商品加入候选选品库（草稿池，待评审）。⚠️ 写库操作，每次调用需人工审批。",
        "effect": EFFECT_APPROVAL,
    },
    {
        "agent": "ProductResearcher",
        "name": "get_candidate",
        "title": "查看候选详情",
        "description": "查看某个候选选品的完整详情（ASIN/售价/评分/评审状态/备注等）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "name": "review_candidate",
        "title": "评审候选（淘汰/转评审）",
        "description": "给候选选品打评审结论：淘汰 / 转评审中 / 退回待评审。⚠️ 写库操作，每次调用需人工审批。",
        "effect": EFFECT_APPROVAL,
    },
    {
        "agent": "ProductResearcher",
        "name": "approve_candidate",
        "title": "评审通过·推进产品库",
        "description": "评审通过：把候选选品推进自有产品库（建待完善 Listing 的 SPU 草稿）。⚠️ 写库操作，每次调用需人工审批。",
        "effect": EFFECT_APPROVAL,
    },
    {
        "agent": "ProductResearcher",
        "name": "query_market_insight",
        "title": "选品大盘（市场洞察）",
        "description": "读类目级选品大盘：蓝海评分 / 搜索量 / 搜索增长 / 价格带 / 卖家数 / 在售 ASIN 数等，可按维度排行、按站点与价格趋势过滤。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 运营复盘师（6）—— modules.review_analyst.tools.review_analyst_tools
    # ★ 第 251 轮：6 → 7（新增只读 `list_reviews` —— 复盘库读口）。
    # ★ 第 313 轮：7 → 6（退役 `ad_review` —— 老板「运营复盘删除广告数据」，
    #   该工具的**对话路由 / LangChain 工具 / 提示词清单**一起退；
    #   只保留 `/review/ad-review` 端点作历史归档读口，故 `REVIEW_REPORT_TYPES`
    #   里的 `ad_review` 与 `list_reviews` 的 report_type 过滤值都不动）。
    #   前 5 个是「**算**复盘」（每次按数据源现算、不落库），
    #   第 6 个 `list_reviews` 是「**读**复盘库」（读人工确认后归档的历史）。
    #   ★ 为什么不登记进 `modules/library/tools.py` 那组跨 Agent 共用工具：
    #     那 5 个是「读当前店铺的某个资料库」，挂给选品分析师 + 店秘书；
    #     而本工具的存在理由是老板那句「**下一期复盘自动读到上期**做对比」——
    #     消费者是复盘师本人。挂给别人，复盘师就永远读不到自己的历史。
    # ------------------------------------------------------------------
    {
        "agent": "review_analyst",
        "name": "weekly_report",
        "title": "经营周报",
        "description": "汇总销售、广告、库存、退款数据，生成结构化周报。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "review_analyst",
        "name": "monthly_review",
        "title": "月度复盘",
        "description": "GMV / ACoS / 转化率 / 退货率趋势对比，附 SKU 贡献排名。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "review_analyst",
        "name": "product_performance",
        "title": "商品表现分析",
        "description": "SKU 级销量 / 利润 / 评分 / BSR / 周转排名，识别爆款与滞销品。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "review_analyst",
        "name": "inventory_health",
        "title": "库存健康分析",
        "description": "滞销预警 / 断货风险 / 周转天数 / 补货建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "review_analyst",
        "name": "profit_audit",
        "title": "利润审计",
        "description": "销售额 − 佣金 − 广告 − 退货全链路核算净利润与净利率。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "review_analyst",
        "name": "list_reviews",
        "title": "查看复盘库",
        "description": "列出本店复盘库里已归档的历史复盘（含类型、周期、一句话结论），可做本期与上期的对比；不含明细快照。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # 店秘书（10）—— navigation_tools(6) + subscription_tools(1)
    #                + build_product_tools()(1) + build_shop_tools()(2)
    # ★ 第 243 轮（第 240 轮方案 A′）：`build_shop_tools()` 由 1 个扩到 2 个
    #   （`switch_shop` + 只读 `list_shops`）—— 把「读有哪些店铺」与「切店铺」分开。
    #   修前只有替换语义的 `switch_shop` 可用 ⇒ 老板问「有几家店」时，
    #   模型要么拿它凑数（**真的切了店**），要么拿 `get_my_subscription`
    #   答成「最多可绑定 3 家」（那是套餐上限，不是店铺数）。
    #   依据 `docs/round-240-shop-list-no-tool.md`（三层根因 + 三衍生危害）。
    # ------------------------------------------------------------------
    {
        "agent": "secretary",
        "name": "switch_agent",
        "title": "切换 Agent",
        "description": "切换到某个业务 Agent 的对话页。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "open_view",
        "title": "打开资料库",
        "description": "打开资料库 / 看板视图，例如产品库、选品库、竞品库。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "open_account_menu",
        "title": "打开账户菜单",
        "description": "打开账户菜单里的某一项（账户 / 系统类跳转的统一网关）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "set_theme",
        "title": "切换界面主题",
        "description": "切换界面外观主题（浅色 / 深色），直接生效。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "ask_clarification",
        "title": "追问补齐信息",
        "description": "向老板提问以补齐继续执行所必需的信息，本身不执行任何动作。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "handoff_to_agent",
        "title": "转交专家 Agent",
        "description": "把对话交接给某个专业 Agent 接管，由它在自己领域内继续追问与执行。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "list_shops",
        "title": "列出我的店铺",
        "description": "只读列出当前身份可见的全部店铺（含全局/平台内序号），不切换店铺。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "switch_shop",
        "title": "切换店铺",
        "description": "切换当前工作的店铺（数据源）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "select_product",
        "title": "选中工作商品",
        "description": "选中产品库里的第 N 个（默认第一个）商品作为「工作商品」。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "secretary",
        "name": "get_my_subscription",
        "title": "查询我的订阅",
        "description": "查询当前账号的订阅套餐详情：套餐名、状态、价格、当前周期、特性列表。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # 竞品监控员（3）—— modules.competitor_intel.tools.competitor_intel_tools
    # ★ 第 198 轮接线：这一组此前「注册了但没有任何 Agent 绑定」，
    #   已随 `CompetitorIntelligenceAgent._build_router()` 真正装配（范式 A），
    #   故登记入表 —— 否则它们在界面上**永远选不到**。
    # ★ 第 207 轮退役 5 条（老板裁决）：`monitor_competitor` / `track_batch_asins` /
    #   `analyze_market_share` / `detect_intruders` / `analyze_buy_box`。
    #   这 5 条**只退役工具包装**：`agent_competitor.py` 的能力方法与 `router.py`
    #   的端点原样保留，`/competitor/analyze` 的关键词路由照旧可达 ⇒
    #   唯一后果是「模型自主选工具」少这 5 个选项。8 → 3。
    # ------------------------------------------------------------------
    {
        "agent": "competitor_intel",
        "name": "analyze_pricing_strategy",
        "title": "定价策略分析",
        "description": "分析竞品定价模式、促销节奏与价格弹性，并给出调价建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "competitor_intel",
        "name": "analyze_competitor_reviews",
        "title": "竞品评论分析",
        "description": "挖掘竞品评论里的优劣势、用户痛点与差异化机会。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "competitor_intel",
        "name": "compare_competitors",
        "title": "多维度竞品对比",
        "description": "从价格、评分、评论、BSR、性价比等维度全面对比多个竞品。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # 广告分析师（4）—— modules.ad_analysis.tools.ad_analysis_tools
    # ★ 第 316 轮：`optimize_budget`（预算分配优化）与 `detect_ad_anomalies`
    #   （广告异常检测）随老板「广告分析师删除异常检测、广告预算再平衡」
    #   一并退役 —— 工具 / 对话意图 / REST 端点 / 大屏 Tab / 技能同步退，
    #   不留零调用假路径。
    # ★ 第 204 轮接线：这 6 个此前「注册了但没有任何 Agent 绑定」（悬空），
    #   已随 `AdAnalysisAgent._build_router()` 真正装配（范式 A）⇒ 收录条件
    #   满足，登记入表 —— 否则它们在界面上**永远选不到**。
    # ------------------------------------------------------------------
    {
        "agent": "ad_analysis",
        "name": "diagnose_ad_account",
        "title": "广告账户体检",
        "description": "多维度评估广告表现，给出评级与问题清单（含同类基准对比）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ad_analysis",
        "name": "analyze_search_terms",
        "title": "搜索词分析",
        "description": "识别高效词、低效词与浪费词，并挖掘新的机会词。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ad_analysis",
        "name": "optimize_bids",
        "title": "出价优化建议",
        "description": "按策略给出关键词 / 广告组的智能出价建议，可指定目标 ACoS。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ad_analysis",
        "name": "analyze_ad_competitors",
        "title": "竞品广告分析",
        "description": "分析竞争对手的广告策略、展示份额与关键词重叠度。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # AIGC 媒体生成器（9）—— modules.aigc_media.tools.aigc_tools
    # ★ 第 204 轮接线（同上）。
    # ★ `generate_product_image` 与 `generate_assets` 是一组**能力边界对**：
    #   前者只出提示词包（不返回图片文件），后者真出图，两条 description
    #   互相点名 ⇒ **必须成对登记**：拆开登记会让模型把提示词包当图片交付。
    # ------------------------------------------------------------------
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_product_image",
        "title": "出图提示词包",
        "description": "产出出图方案（提示词 / SEO 关键词 / 文案建议 / 风格指南），⚠️ 只出方案，不含图片文件。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_assets",
        "title": "生成图片素材",
        "description": "真正出图：白底图 / 场景图 / 主图 / 信息图 / 广告图，返回图片 URL。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "analyze_main_image",
        "title": "主图质量诊断",
        "description": "给主图打分，并给出 CTR 预测、合规问题与改进建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_a_plus_content",
        "title": "A+ 内容生成",
        "description": "生成 A+（EBC 增强品牌内容）各模块文案。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_brand_story",
        "title": "品牌故事生成",
        "description": "生成品牌定位、使命、卖点、标语与叙事角度。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "translate_content",
        "title": "多语言内容翻译",
        "description": "把文案翻译到目标语言，并保留 SEO 关键词。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_infographic",
        "title": "信息图规格",
        "description": "生成营销信息图的分区、文案、配色与 CTA 规格。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "check_image_compliance",
        "title": "图片合规检查",
        "description": "检查图片是否合规，返回状态、评分与整改建议。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "AIGC 媒体生成器",
        "name": "generate_video_script",
        "title": "短视频脚本",
        "description": "生成短视频脚本：分镜、旁白、字幕、钩子与 CTA。",
        "effect": EFFECT_READ_ONLY,
    },
    # ------------------------------------------------------------------
    # 智能客服（9）—— modules.customer_service.tools.customer_service_tools
    # ★ 第 204 轮接线（同上）。
    # ★ 第 283 轮从 4 扩到 9：新增 trade 域 5 个工具（订单 / 物流 / 差评 /
    #   健康分 / 补偿建议）—— 让「按证据判断责任归属」这条技能要求**有数可取**。
    # ★ `create_ticket` 是本组唯一带副作用的工具（会写 `cs_tickets` 表）
    #   ⇒ `effect` 必须 `approval`。它**本来就有**副作用，此前只是因为注册表
    #     悬空、没露面才没被要求标出来。
    # ------------------------------------------------------------------
    {
        "agent": "智能客服",
        "name": "search_faq",
        "title": "检索客服知识库",
        "description": "搜索客服知识库（FAQ），返回匹配的问题与标准答案。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "create_ticket",
        "title": "创建客服工单",
        "description": "创建客服工单，返回工单号与预计响应时间。⚠️ 写库操作，每次调用需人工审批。",
        "effect": EFFECT_APPROVAL,
    },
    {
        "agent": "智能客服",
        "name": "analyze_sentiment",
        "title": "情感分析",
        "description": "判断文本是正面 / 负面 / 中性，返回情感标签与置信度。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "get_conversation_summary",
        "title": "会话摘要",
        "description": "获取某段客服对话的摘要。",
        "effect": EFFECT_READ_ONLY,
    },
    # ---- 第 283 轮新增：trade 域（订单 / 物流 / 买家评价）----
    {
        "agent": "智能客服",
        "name": "fetch_order_tracking",
        "title": "查询订单与物流",
        "description": "按订单号查订单、商品明细、物流轨迹与关联差评（含迟到天数）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "list_customer_reviews",
        "title": "列出买家评价",
        "description": "列出本店铺近期买家评价（默认中差评），可按 SKU 过滤。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "get_customer_review_context",
        "title": "差评处置上下文",
        "description": "取一条买家评价的原文、关联订单/物流、归因与是否重复问题。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "get_sku_health_score",
        "title": "SKU 健康分",
        "description": "取某 SKU 的买家反馈健康分（含环比 delta 与主要失分项）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "智能客服",
        "name": "plan_compensation",
        "title": "补偿方案建议",
        "description": "按差评归因匹配补偿规则，给出建议方案（不发券不写库）。",
        "effect": EFFECT_READ_ONLY,
    },
    # ---- 第 287 轮新增：差评处置的**写入点**（P0-2 给 review_dispositions 补出口）----
    {
        "agent": "智能客服",
        "name": "propose_review_disposition",
        "title": "生成差评处置草稿",
        "description": "按归因与补偿规则生成一条待批准的差评处置（补偿方案 + 中英双语回复）并落库；发放须由人在处置列表里批准。",
        "effect": EFFECT_APPROVAL,
    },
    # ------------------------------------------------------------------
    # 跨 Agent 共用（6）—— modules.library.tools.build_library_tools()
    # ★ 第 218 轮（P1）从 2 → 6：侧边栏「资料库」组的 6 个库全覆盖
    #   （`candidates / products / assets / competitors / faq / rules`）。
    #   ★ 为什么这 4 个也挂给**同样两家**而不是按库拆到 4 家宿主：归属来源的
    #     注入通道只有选品分析师与店秘书接好了（`resolve=` / `shop_id=`），
    #     其余业务 Agent 整条没有店铺归属通道 —— 挂上去等于「接了调不到」。
    #     判据 G 会把归属集合与运行时真值双向咬住，将来真需要再拆也不会漂。
    # ★ 第 205 轮：这两条是**同一份实现**挂给多家（`agents`）。
    #   `agent`（主归属）取的是**提出该能力、且能真调到它**的那一家；
    #   Listing 优化师**不在**名单里 —— 它的工具路径整条没有店铺归属通道
    #   （全模块 0 处 shop/store/tenant 引用），`list_products` 拿不到租户
    #   就没法读产品库。这是**已知前置**，见
    #   `docs/atomic-tools-per-agent-r205.md`，不是漏登记。
    # ------------------------------------------------------------------
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_candidates",
        "title": "查看选品库",
        "description": "列出当前店铺候选选品库（草稿池）里的候选，可按评审状态筛、也可按销量/售价/评分/蓝海评分/ROI 排序取前几名。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_products",
        "title": "查看产品库",
        "description": "列出当前店铺产品库里的产品（SKU 粒度，含所属 SPU 标题）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_assets",
        "title": "查看素材库",
        "description": "列出当前店铺营销素材库里的图片 / 视频素材，可按类型 / 分类 / 来源筛，可按名称、类型、创建时间排序取前几条。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_monitors",
        "title": "查看竞品监控池",
        "description": "列出当前店铺竞品监控池里正在盯的竞品，可按库存状态 / 站点筛，可按价格、评分、评论数、销量、BSR 排序取前几名（BSR 越小越好）。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_faqs",
        "title": "查看业务话术库",
        "description": "列出当前店铺业务话术库里的客服问答条目（问题 + 标准答案），可按知识库、分类、优先级、状态筛，可按使用次数排序。",
        "effect": EFFECT_READ_ONLY,
    },
    {
        "agent": "ProductResearcher",
        "agents": ["ProductResearcher", "secretary"],
        "name": "list_platform_rules",
        "title": "查看平台规则库",
        "description": "列出当前店铺平台规则库里的规则条目（含平台、分类、生效日期、正文），可按平台、分类、状态筛，默认按生效日期倒序。",
        "effect": EFFECT_READ_ONLY,
    },
]

#: 「纯文本型」Agent —— 名下**没有任何业务工具**，且这是**有意为之**。
#:
#: ★★★ 为什么需要这张白名单（第 198 轮 · 老板点名要的那条门禁）：
#:   此前**没有任何一条判据**回答「某个 Agent 一个工具都没有」这件事。
#:   第 197 轮实测有 4 个：`ad_analysis` / `AIGC 媒体生成器` / `智能客服` /
#:   `competitor_intel`（最后一个已于第 198 轮接线并登记进 `TOOL_CATALOG`）。
#:   缺这条判据的后果：新写一个 Agent 忘了绑工具 ⇒ 它在工具清单里不出现
#:   （`grouped_catalog` 跳过空组，那是对的）、运行期拿不到任何数据，
#:   **且不报错**。
#:
#: 语义（`tests/test_tool_catalog.py::test_every_agent_has_tools_or_is_declared_text_only`）：
#:   `AGENT_CATALOG` 里的每个 Agent，要么在 `TOOL_CATALOG` 里有 ≥1 个工具，
#:   要么在本字典里**显式登记并写明理由**。两者都不满足 ⇒ 红。
#:   反向：已经有工具的 Agent 留在这里 ⇒ 也红（白名单不许腐烂成谎话）。
#:
#: ★ 为什么不是「加一条注释说明」：注释不会在 CI 里转红。
#:
#: ★★★ 第 204 轮起本表为**空表** —— 8 个 Agent 全部名下有工具。
#:   最后 3 个（`ad_analysis` / `AIGC 媒体生成器` / `智能客服`）随各自的
#:   `_build_router()` 接线一并补齐（19 个工具），三条登记理由
#:   「工具集悬空」随之失效 ⇒ 一并删除。
#:
#: ★ 空表是**合格状态**，不是「忘了填」。为此自检断言已从
#:   「白名单必须非空」改为「**表内每一条**理由都要像样」——
#:   因为「非空」在空表合法化之后会变成**负资产**（逼人塞假条目交差）。
#:   真正咬住「有没有 Agent 零工具」的是判据 F 的 ②：
#:   `naked = known - with_tools - declared` 必须为空，且
#:   `len(AGENT_CATALOG) == 8` 把 Agent 总数钉死。
TEXT_ONLY_AGENTS: Dict[str, str] = {}

#: `name` → 目录项
_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOL_CATALOG}


# ============================================================================
# 查询口（界面与校验都只经这几个函数，别直接遍历 TOOL_CATALOG）
# ============================================================================


#: 已裁决的**落选同义名** —— 同一个后端能力只留一个工具名（第 205 轮）。
#:
#: ★ 为什么要有这张表：收敛如果不登记落选者，它会在下一轮被**重新捡起来**
#:   （有人要补 `GET /api/v1/skus` 的工具，顺手取名 `list_skus`）——
#:   那时「一个能力两个名字」又回来了，而没有任何东西会报错。
#:   门禁逐名搜「目录 + 全仓运行时工具集」，出现即红。
#:
#: 键 = 禁用的工具名；值 = 为什么禁用 + 该用什么。
REJECTED_TOOL_ALIASES: Dict[str, str] = {
    "list_skus": (
        "`GET /api/v1/skus` 的另一个提议名（第 204 轮 Listing 优化师提出）。"
        "该能力统一叫 `list_products` —— 界面上的域名叫「产品库」，"
        "秘书既有的 `select_product` 同族；`skus` 是**存储层**的词，不该漏进工具名。"
    ),
    "get_sku": (
        "`GET /api/v1/skus/{id}` 的提议名。该能力**尚未注册**；要补时请叫 "
        "`get_product` —— 与 `list_products` 同族。否则词表会分裂成 "
        "list 用 product、get 用 sku 两套，模型选名字时会漂。"
    ),
}


def entry_agents(entry: Dict[str, Any]) -> Tuple[str, ...]:
    """目录项的**归属 Agent 全集**（缺省 = 只有 `agent` 那一个）。

    ★ 唯一真源是条目自己的 `agents` 字段，本函数不维护第二份名单。
    """
    got = entry.get("agents")
    if not got:
        return (str(entry["agent"]),)
    return tuple(str(a) for a in got)


def shared_tools() -> Dict[str, Tuple[str, ...]]:
    """**跨 Agent 共用**的工具：`{工具名: 归属全集}`（只含归属 > 1 的）。

    ★ 从 `TOOL_CATALOG` **派生**，不另建一张表 —— 两张表迟早漂移。
    """
    out: Dict[str, Tuple[str, ...]] = {}
    for t in TOOL_CATALOG:
        agents = entry_agents(t)
        if len(agents) > 1:
            out[t["name"]] = agents
    return out


def all_tool_names() -> Tuple[str, ...]:
    """全部**合法**工具名（`skills.tools` 只能存这里的值）。"""
    return tuple(t["name"] for t in TOOL_CATALOG)


def is_known_tool(name: str) -> bool:
    """该工具名是否已在平台注册。

    ★ 写口用它做 fail-closed 校验：未知名字一律拒绝（见 `service._validate_tools`）。
      在此之前，`export_report` 这种不存在的名字会被**原样存进库**，
      然后在运行期静默不生效 —— 正是本表要消灭的形态。
    """
    return str(name or "") in _BY_NAME


def tool_entry(name: str) -> Optional[Dict[str, str]]:
    """取某个工具的目录项（未知工具返回 None）。"""
    return _BY_NAME.get(str(name or ""))


def tool_title(name: str) -> str:
    """取展示名；**未知工具原样返回** —— 日志与界面里宁可显示怪名字，
    也不要因为一次改名让整页渲染挂掉（同 `agents.agent_title` 判据）。

    ★ 这条对老数据是必须的：库里可能存在本表登记之前写入的工具名，
      它们必须**能被显示**（否则租户看不见、也就删不掉）。
    """
    item = _BY_NAME.get(str(name or ""))
    return item["title"] if item else str(name or "")


def tools_for_agent(agent_name: str) -> List[Dict[str, str]]:
    """某个 Agent 名下的工具（界面按已勾选的 Agent 收窄候选集时用）。

    ★ 收窄的意义：**避免「绑了调不到」**。工具是按 Agent 装配的，
      一个技能若只挂在 `ListingGenerator` 上，却绑了 `analyze_profit`
      （属于 `ProductResearcher`），模型在那个 Agent 手上根本没有这个工具。
    """
    key = str(agent_name or "")
    return [t for t in TOOL_CATALOG if key in entry_agents(t)]


def grouped_catalog() -> List[Dict]:
    """按 Agent 分组（**顺序与 `AGENT_CATALOG` 一致**，保证界面排列稳定）。

    返回 `[{"agent", "agentTitle", "tools": [目录项…]}, …]`，
    只含「名下至少有一个工具」的 Agent —— 空组会让界面出现一堆空标题。
    """
    out: List[Dict] = []
    for a in AGENT_CATALOG:
        items = tools_for_agent(a["name"])
        if items:
            out.append(
                {
                    "agent": a["name"],
                    "agentTitle": a["title"],
                    "tools": items,
                }
            )
    return out


__all__ = [
    "EFFECT_APPROVAL",
    "EFFECT_READ_ONLY",
    "REJECTED_TOOL_ALIASES",
    "TOOL_CATALOG",
    "TEXT_ONLY_AGENTS",
    "all_tool_names",
    "entry_agents",
    "grouped_catalog",
    "is_known_tool",
    "shared_tools",
    "tool_entry",
    "tool_title",
    "tools_for_agent",
]

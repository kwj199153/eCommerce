# -*- coding: utf-8 -*-
"""工具目录 —— 「这个技能能配套哪些工具」的**唯一真源**（第 185 轮 · 批 A；第 400 轮 P1-2 改派生化）

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
★ 第 400 轮 P1-2：表里**只留文案**，其余全部派生
==============================================================================
改造前每条长这样（5 个字段）：

    {"agent": "ListingGenerator", "name": "optimize_listing_title",
     "title": "标题优化", "description": "…", "effect": EFFECT_READ_ONLY}

其中 `agent` / `effect` 是**冗余**的：门禁早已用运行时真值把它们钉死
（`tests/test_tool_catalog.py` 判据 A / B），也就是说这两个字段
**只可能写错，不可能携带额外信息**。它们的失效方式是安静的：
副作用档从 `READ_ONLY_METADATA` 改成 `SIDE_EFFECT_METADATA` 后表里没跟
⇒ 界面上那个「需审批」标记**在骗人**，而日志全绿。

改造后每条只剩**人文案**：

    "optimize_listing_title": ("标题优化", "优化 Listing 标题，返回 SEO 改进版…"),

`name`（键）/ `agent` / `agents` / `effect` 全部由
`modules/skills/tool_wiring.py` 从**装配点运行时真值**派生：

| 字段 | 派生自 | 失效形态 |
|---|---|---|
| `name` | 工具对象的 `.name` | 结构上不可能漂 |
| `agent` / `agents` | 谁家的 `tools=` 容器里装着它 | 结构上不可能漂 |
| `effect` | `has_side_effects(tool)`（**fail-closed**） | 结构上不可能漂 |

★ 只留下 `title` / `description` 的原因：它们**派生不出来** ——
  工具自己的 `description` 是写给**模型**看的（「当用户想算利润时使用」这类
  引导语），而本表要的是写给**人**看的（租户在勾选界面上判断"我要不要这个"）。
  两者受众不同，自动派生只会得到一个模型腔的句子。

★ 因此「新增一个工具」要做的事从**四处**降到**三处**：
  ① 写实现 ② 放进某个 Agent 的容器 ③ **在本表加一行文案**。
  忘了 ③ 会怎样？不会静默少一个工具 —— `catalog_gaps()["missing_text"]`
  会列出它，门禁转红（见下方 `catalog_gaps()`）。

==============================================================================
★ 表里放什么、不放什么（判据：装配点）
==============================================================================
**只放「源码里 `BaseAgent(tools=...)` 实参命名的容器」里的工具。**
注册了却没有任何 Agent 绑定的工具**一个都不下发** —— 它们勾了也调不起来，
而"让租户勾一个不生效的工具"比"不给他勾"更糟：他会以为配好了。

★ 为什么必须**运行时**取而不能靠 AST 扫：
  秘书的 `product_tools` / `shop_tools` 是 `build_product_tools(shop_id)` 这类
  **工厂函数动态构造**的 —— AST 只能看到工厂名，看不到它产出哪些工具。
  第 183/184 轮两个 AST 探针把同一件事算成了 54 和 25 两个错答案，留此记录。

★ 真值的**射程**与分工（别高估它）：
  本表是**容器级**的 —— 只问「这些容器里有哪些工具名」，**不检查该容器有没有
  被某个 Agent 真的绑上**。后者是 `tests/test_agent_tool_wiring.py` 的职责。
  缺任何一处都会造出「可勾选但调不起来」的工具，且**不报错**。

==============================================================================
★ 跨 Agent 共用（第 205 轮「收敛同端点多名」）
==============================================================================
同一个后端能力**只允许一个工具名**，多家 Agent 共用同一份实现 ——
它们会**同时出现在两家 Agent 的分组里**（`agents` 字段是归属全集，
`agent` 只是主归属 = `ASSEMBLY_POINTS` 里先出现的那一家）。
落选名登记在 `REJECTED_TOOL_ALIASES`，防止下一轮被重新捡起来。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from modules.skills.agents import AGENT_CATALOG

logger = get_logger("skills.tools_catalog")

#: 副作用档取值（与 `ai_infra.tools.side_effects` 的判定对应）
EFFECT_READ_ONLY = "read_only"
EFFECT_APPROVAL = "approval"

#: 目录文案表：`工具名 → (展示名, 一句话说明)`。
#:
#: ★ **顺序即界面展示顺序**（按 Agent 分组后，组内保持本表顺序）。
#: ★ 这是本模块**唯一需要人写**的东西。别在这里写 `agent` / `effect` ——
#:   它们派生得出来，写进来只会多一处能写错的地方。
#: ★ 键必须是装配点里真实存在的工具名：写了但没人装配 ⇒
#:   `catalog_gaps()["orphan_text"]` 会点名（死文案不许留着骗人）。
TOOL_TEXT: Dict[str, Tuple[str, str]] = {
    # ---- Listing 优化师 ----
    "optimize_listing_title": ("标题优化", "优化 Listing 标题，返回 SEO 改进版、字符数与 SEO 评分。"),
    "generate_bullet_points": ("五点描述", "为产品生成五点描述（卖点）。"),
    "generate_product_description": ("详情描述", "为产品生成详情描述，可含 HTML 富文本。"),
    "generate_search_terms": ("后台搜索词", "基于标题生成后台搜索词（Search Terms）。"),
    "generate_complete_listing": ("整套 Listing", "从零生成一整套 Listing：标题 + 五点 + 描述 + 关键词 + SEO 评分。"),
    "optimize_listing": ("整体优化建议", "分析现有 Listing 并给出逐项优化建议。"),
    "analyze_listing_seo": ("SEO 诊断", "对现有 Listing 做 SEO 诊断评分。"),
    "generate_ab_test_variants": ("A/B 测试变体", "生成多个可用于 A/B 测试的标题变体。"),
    # ---- 选品分析师 ----
    "analyze_blue_ocean": ("蓝海品类挖掘", "按低竞争 + 有需求 + 有利润的标准筛选候选商品，返回蓝海评分排序列表。"),
    "analyze_profit": ("利润测算", "按售价、成本、FBA 费用、广告费计算净利润 / ROI / 盈亏平衡点。"),
    "analyze_pain_points": ("评论痛点分析", "分析某商品 ASIN 的用户评论，提炼痛点与改进方向。"),
    "compare_competitor_listings": ("竞品 Listing 对比", "对比多个竞品 ASIN 的 Listing 质量、价格与优劣势，给出参考建议。"),
    "save_candidate": ("加入选品库", "把商品加入候选选品库（草稿池，待评审）。⚠️ 写库操作，每次调用需人工审批。"),
    "get_candidate": ("查看候选详情", "查看某个候选选品的完整详情（ASIN/售价/评分/评审状态/备注等）。"),
    "review_candidate": ("评审候选（淘汰/转评审）", "给候选选品打评审结论：淘汰 / 转评审中 / 退回待评审。⚠️ 写库操作，每次调用需人工审批。"),
    "approve_candidate": ("评审通过·推进产品库", "评审通过：把候选选品推进自有产品库（建待完善 Listing 的 SPU 草稿）。⚠️ 写库操作，每次调用需人工审批。"),
    "query_market_insight": ("选品大盘（市场洞察）", "读类目级选品大盘：蓝海评分 / 搜索量 / 搜索增长 / 价格带 / 卖家数 / 在售 ASIN 数等，可按维度排行、按站点与价格趋势过滤。"),
    # ---- 运营复盘师 ----
    "weekly_report": ("经营周报", "汇总销售、广告、库存、退款数据，生成结构化周报。"),
    "monthly_review": ("月度复盘", "GMV / ACoS / 转化率 / 退货率趋势对比，附 SKU 贡献排名。"),
    "product_performance": ("商品表现分析", "SKU 级销量 / 利润 / 评分 / BSR / 周转排名，识别爆款与滞销品。"),
    "inventory_health": ("库存健康分析", "滞销预警 / 断货风险 / 周转天数 / 补货建议。"),
    "profit_audit": ("利润审计", "销售额 − 佣金 − 广告 − 退货全链路核算净利润与净利率。"),
    "list_reviews": ("查看复盘库", "列出本店复盘库里已归档的历史复盘（含类型、周期、一句话结论），可做本期与上期的对比；不含明细快照。"),
    # ---- 店秘书 ----
    "switch_agent": ("切换 Agent", "切换到某个业务 Agent 的对话页。"),
    "open_view": ("打开资料库", "打开资料库 / 看板视图，例如产品库、选品库、竞品库。"),
    "open_account_menu": ("打开账户菜单", "打开账户菜单里的某一项（账户 / 系统类跳转的统一网关）。"),
    "set_theme": ("切换界面主题", "切换界面外观主题（浅色 / 深色），直接生效。"),
    "ask_clarification": ("追问补齐信息", "向老板提问以补齐继续执行所必需的信息，本身不执行任何动作。"),
    "handoff_to_agent": ("转交专家 Agent", "把对话交接给某个专业 Agent 接管，由它在自己领域内继续追问与执行。"),
    "find_capabilities": ("查找读能力", "在本系统已有的读端点里按关键词检索能力，返回名字与摘要（不含参数）。"),
    "describe_capability": ("查看能力参数", "查看某个读能力的参数清单（名称 / 位置 / 必填 / 说明）。"),
    "read_capability": ("读取数据", "按名字调用一个只读端点取数（GET），不修改任何数据。"),
    "list_shops": ("列出我的店铺", "只读列出当前身份可见的全部店铺（含全局/平台内序号），不切换店铺。"),
    "switch_shop": ("切换店铺", "切换当前工作的店铺（数据源）。"),
    "select_product": ("选中工作商品", "选中产品库里的第 N 个（默认第一个）商品作为「工作商品」。"),
    "get_my_subscription": ("查询我的订阅", "查询当前账号的订阅套餐详情：套餐名、状态、价格、当前周期、特性列表。"),
    # ---- 竞品监控员 ----
    "analyze_pricing_strategy": ("定价策略分析", "分析竞品定价模式、促销节奏与价格弹性，并给出调价建议。"),
    "analyze_competitor_reviews": ("竞品评论分析", "挖掘竞品评论里的优劣势、用户痛点与差异化机会。"),
    "compare_competitors": ("多维度竞品对比", "从价格、评分、评论、BSR、性价比等维度全面对比多个竞品。"),
    # ---- 广告分析师 ----
    "diagnose_ad_account": ("广告账户体检", "多维度评估广告表现，给出评级与问题清单（含同类基准对比）。"),
    "analyze_search_terms": ("搜索词分析", "识别高效词、低效词与浪费词，并挖掘新的机会词。"),
    "optimize_bids": ("出价优化建议", "按策略给出关键词 / 广告组的智能出价建议，可指定目标 ACoS。"),
    "analyze_ad_competitors": ("竞品广告分析", "分析竞争对手的广告策略、展示份额与关键词重叠度。"),
    # ---- AIGC 媒体生成器 ----
    "generate_product_image": ("出图提示词包", "产出出图方案（提示词 / SEO 关键词 / 文案建议 / 风格指南），⚠️ 只出方案，不含图片文件。"),
    "generate_assets": ("生成图片素材", "真正出图：白底图 / 场景图 / 主图 / 信息图 / 广告图，返回图片 URL。"),
    "analyze_main_image": ("主图质量诊断", "给主图打分，并给出 CTR 预测、合规问题与改进建议。"),
    "generate_a_plus_content": ("A+ 内容生成", "生成 A+（EBC 增强品牌内容）各模块文案。"),
    "generate_brand_story": ("品牌故事生成", "生成品牌定位、使命、卖点、标语与叙事角度。"),
    "translate_content": ("多语言内容翻译", "把文案翻译到目标语言，并保留 SEO 关键词。"),
    "generate_infographic": ("信息图规格", "生成营销信息图的分区、文案、配色与 CTA 规格。"),
    "check_image_compliance": ("图片合规检查", "检查图片是否合规，返回状态、评分与整改建议。"),
    "generate_video_script": ("短视频脚本", "生成短视频脚本：分镜、旁白、字幕、钩子与 CTA。"),
    # ---- 智能客服 ----
    "search_faq": ("检索客服知识库", "搜索客服知识库（FAQ），返回匹配的问题与标准答案。"),
    "create_ticket": ("创建客服工单", "创建客服工单，返回工单号与预计响应时间。⚠️ 写库操作，每次调用需人工审批。"),
    "analyze_sentiment": ("情感分析", "判断文本是正面 / 负面 / 中性，返回情感标签与置信度。"),
    "get_conversation_summary": ("会话摘要", "获取某段客服对话的摘要。"),
    "fetch_order_tracking": ("查询订单与物流", "按订单号查订单、商品明细、物流轨迹与关联差评（含迟到天数）。"),
    "list_customer_reviews": ("列出买家评价", "列出本店铺近期买家评价（默认中差评），可按 SKU 过滤。"),
    "get_customer_review_context": ("差评处置上下文", "取一条买家评价的原文、关联订单/物流、归因与是否重复问题。"),
    "get_sku_health_score": ("SKU 健康分", "取某 SKU 的买家反馈健康分（含环比 delta 与主要失分项）。"),
    "plan_compensation": ("补偿方案建议", "按差评归因匹配补偿规则，给出建议方案（不发券不写库）。"),
    "propose_review_disposition": ("生成差评处置草稿", "按归因与补偿规则生成一条待批准的差评处置（补偿方案 + 中英双语回复）并落库；发放须由人在处置列表里批准。"),
    # ---- 跨 Agent 共用（选品分析师 + 店秘书，第 205 轮收敛）----
    "list_candidates": ("查看选品库", "列出当前店铺候选选品库（草稿池）里的候选，可按评审状态筛、也可按销量/售价/评分/蓝海评分/ROI 排序取前几名。"),
    "list_products": ("查看产品库", "列出当前店铺产品库里的产品（SKU 粒度，含所属 SPU 标题）。"),
    "list_assets": ("查看素材库", "列出当前店铺营销素材库里的图片 / 视频素材，可按类型 / 分类 / 来源筛，可按名称、类型、创建时间排序取前几条。"),
    "list_monitors": ("查看竞品监控池", "列出当前店铺竞品监控池里正在盯的竞品，可按库存状态 / 站点筛，可按价格、评分、评论数、销量、BSR 排序取前几名（BSR 越小越好）。"),
    "list_faqs": ("查看业务话术库", "列出当前店铺业务话术库里的客服问答条目（问题 + 标准答案），可按知识库、分类、优先级、状态筛，可按使用次数排序。"),
    "list_platform_rules": ("查看平台规则库", "列出当前店铺平台规则库里的规则条目（含平台、分类、生效日期、正文），可按平台、分类、状态筛，默认按生效日期倒序。"),
}

#: 「纯文本型」Agent —— 名下**没有任何业务工具**，且这是**有意为之**。
#:
#: ★★★ 为什么需要这张白名单（第 198 轮 · 老板点名要的那条门禁）：
#:   此前**没有任何一条判据**回答「某个 Agent 一个工具都没有」这件事。
#:   缺这条判据的后果：新写一个 Agent 忘了绑工具 ⇒ 它在工具清单里不出现
#:   （`grouped_catalog` 跳过空组，那是对的）、运行期拿不到任何数据，**且不报错**。
#:
#: 语义：`AGENT_CATALOG` 里的每个 Agent，要么名下有 ≥1 个工具，
#:   要么在本字典里**显式登记并写明理由**。两者都不满足 ⇒ 红。
#:   反向：已经有工具的 Agent 留在这里 ⇒ 也红（白名单不许腐烂成谎话）。
#:
#: ★ 为什么不是「加一条注释说明」：注释不会在 CI 里转红。
#: ★ 空表是**合格状态**，不是「忘了填」—— 所以自检断言的是
#:   「**表内每一条**理由都要像样」而不是「非空」（否则会逼人塞假条目交差）。
TEXT_ONLY_AGENTS: Dict[str, str] = {}

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


# ============================================================================
# 派生（P1-2）
# ============================================================================

#: 装配点解析失败的原因（**不静默**：门禁断言它为空）。
#:
#: ★ 为什么不让失败直接抛出去：本模块在 `modules/skills/service.py` 的
#:   import 链上（= app 启动必经之路）。一个悬空的装配点不该让整个应用起不来，
#:   但也**不能假装目录是完整的** —— 记在这里 + 打 error，
#:   `catalog_gaps()` 与门禁会把它变成一个可见的缺口。
WIRING_FAILURES: List[str] = []

#: 派生出来的目录（`shipped_catalog()` 幂等填充）。
#:
#: ★★ 为什么**不**在 import 期填充（第 400 轮实测，别省这一步）：
#:   派生的前提是「真的 import 并调用工具工厂」。实测 `import 本模块` 若
#:   连派生一起做，**单模块导入要 4.1 秒**，而且会把 8 个 Agent 的构造一起跑掉
#:   （日志里能看到 `✅ Agent 初始化完成: AIGCMediaAgent`）——
#:   那是把一个「纯数据表」的 import 变成了有副作用的重量级操作：
#:   任何 `import modules.skills` 的脚本（alembic / seed / 单测）都被迫付这笔钱，
#:   而它可能在没有 LLM 配置的环境里跑。
#:   ⇒ 改成**首次真正要用目录时**才算（见 `shipped_catalog()`）。
#:   ⇒ 也**不要**在模块底部调 `_ensure()`，那等于把懒加载改回急加载。
_CATALOG: List[Dict[str, Any]] = []

#: `name` → 目录项
_BY_NAME: Dict[str, Dict[str, Any]] = {}

#: 文案表里写了、但装配点里没人装的名字（死文案）
_ORPHAN_TEXT: List[str] = []

#: 装配点里有、但文案表没写的名字（会从界面消失 —— 最危险的一类缺口）
_MISSING_TEXT: List[str] = []

_BUILT = False


def _build() -> None:
    """派生一次（幂等；由 `shipped_catalog()` 首次调用时触发）。"""
    global _BUILT
    if _BUILT:
        return

    from modules.skills.tool_wiring import WiringError, derive_wiring

    owner: Dict[str, Tuple[str, ...]] = {}
    effect: Dict[str, str] = {}
    try:
        owner, effect, conflicts = derive_wiring()
        for c in conflicts:
            # 同一份实现只有一份 metadata ⇒ 真冲突说明某处漏传了 metadata，
            # 而"后写覆盖"会让「界面说只读、运行期过审批」变得难以归因。
            WIRING_FAILURES.append(f"副作用声明冲突：{c}")
    except WiringError as e:
        WIRING_FAILURES.append(str(e))
    except Exception as e:  # noqa: BLE001 —— 兜底：装配点里任何异常都不该拖垮启动
        WIRING_FAILURES.append(f"{type(e).__name__}: {e}")

    for f in WIRING_FAILURES:
        logger.error(f"❌ 工具目录派生失败（界面会少工具，且不会报错）：{f}")

    built: List[Dict[str, Any]] = []
    for name, (title, description) in TOOL_TEXT.items():
        owners = owner.get(name) or ()
        if not owners:
            # 文案在、装配点里没有 ⇒ 不下发（勾了也调不起来），但**点名**
            _ORPHAN_TEXT.append(name)
            continue
        entry: Dict[str, Any] = {
            "agent": owners[0],
            "name": name,
            "title": title,
            "description": description,
            "effect": effect.get(name, EFFECT_APPROVAL),   # ★ 取不到就按"需审批"（fail-closed）
        }
        if len(owners) > 1:
            entry["agents"] = list(owners)
        built.append(entry)

    # 装配点有、文案表没有 ⇒ 它不会进目录（租户根本选不到），必须报出来
    _MISSING_TEXT.extend(sorted(set(owner) - set(TOOL_TEXT)))

    list.extend(_CATALOG, built)      # ★ 原地填充：`shipped_catalog()` 的返回值始终是同一对象
    _BY_NAME.clear()
    _BY_NAME.update({t["name"]: t for t in built})
    _BUILT = True


def _ensure() -> None:
    _build()


def shipped_catalog() -> List[Dict[str, Any]]:
    """**取目录请用这个函数**（首次调用才派生，之后直接返回同一份）。"""
    _ensure()
    return _CATALOG


def __getattr__(name: str):
    """保留 `TOOL_CATALOG` 这个名字（PEP 562 模块级惰性属性）。

    ★ 为什么用 `__getattr__` 而不是一个模块级空列表：空列表在 import 期就存在，
      `from … import TOOL_CATALOG` 会绑到那个**空对象**上；等到有人 ensure 之后
      它虽然是原地填充的（引用没变），但"读到空表"这个窗口是真实存在的，
      而且它的表现是**静默的空目录**（界面一个工具都没有，日志全绿）。
      惰性属性没有这个窗口：**取到它的时候它一定是填好的**。

    ★ 代价：`from … import TOOL_CATALOG` 的那一刻就会触发派生（约 4 秒 + 一次
      Agent 构造）。所以**生产代码请一律用 `shipped_catalog()`**，
      这个名字只留给了既有的测试与脚本。
    """
    if name == "TOOL_CATALOG":
        return shipped_catalog()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def catalog_gaps() -> Dict[str, List[str]]:
    """目录的两类缺口（都为空才是健康状态）。

    * `missing_text` —— 装配点里有、但没人写文案 ⇒ **界面看不见这个工具**；
    * `orphan_text`  —— 写了文案、但没人装配 ⇒ 死文案（勾了也调不起来）；
    * `wiring_failures` —— 装配点解析失败（模块改了名 / 工厂签名变了）。

    ★ 三者都必须为空，且都**不许**用"静默跳过"处理 ——
      "界面少一个工具"这个症状没有任何一处会报错，只有这里能说清原因。
    """
    _ensure()
    return {
        "missing_text": sorted(_MISSING_TEXT),
        "orphan_text": sorted(_ORPHAN_TEXT),
        "wiring_failures": list(WIRING_FAILURES),
    }


# ============================================================================
# 查询口（界面与校验都只经这几个函数，别直接遍历 TOOL_CATALOG）
# ============================================================================


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

    ★ 从目录**派生**，不另建一张表 —— 两张表迟早漂移。
    """
    out: Dict[str, Tuple[str, ...]] = {}
    for t in shipped_catalog():
        agents = entry_agents(t)
        if len(agents) > 1:
            out[t["name"]] = agents
    return out


def all_tool_names() -> Tuple[str, ...]:
    """全部**合法**工具名（`skills.tools` 只能存这里的值）。"""
    return tuple(t["name"] for t in shipped_catalog())


def is_known_tool(name: str) -> bool:
    """该工具名是否已在平台注册。

    ★ 写口用它做 fail-closed 校验：未知名字一律拒绝（见 `service._validate_tools`）。
      在此之前，`export_report` 这种不存在的名字会被**原样存进库**，
      然后在运行期静默不生效 —— 正是本表要消灭的形态。
    """
    _ensure()
    return str(name or "") in _BY_NAME


def tool_entry(name: str) -> Optional[Dict[str, Any]]:
    """取某个工具的目录项（未知工具返回 None）。"""
    _ensure()
    return _BY_NAME.get(str(name or ""))


def tool_title(name: str) -> str:
    """取展示名；**未知工具原样返回** —— 日志与界面里宁可显示怪名字，
    也不要因为一次改名让整页渲染挂掉（同 `agents.agent_title` 判据）。

    ★ 这条对老数据是必须的：库里可能存在本表登记之前写入的工具名，
      它们必须**能被显示**（否则租户看不见、也就删不掉）。
    """
    _ensure()
    item = _BY_NAME.get(str(name or ""))
    return item["title"] if item else str(name or "")


def tools_for_agent(agent_name: str) -> List[Dict[str, Any]]:
    """某个 Agent 名下的工具（界面按已勾选的 Agent 收窄候选集时用）。

    ★ 收窄的意义：**避免「绑了调不到」**。工具是按 Agent 装配的，
      一个技能若只挂在 `ListingGenerator` 上，却绑了 `analyze_profit`
      （属于 `ProductResearcher`），模型在那个 Agent 手上根本没有这个工具。
    """
    key = str(agent_name or "")
    return [t for t in shipped_catalog() if key in entry_agents(t)]


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


# ★ 故意**不**在这里调 `_ensure()`：那会把懒加载改回急加载
#   （4.1 秒 + 构造 8 个 Agent，理由见 `_CATALOG` 处的注释）。
#   要做到"导入这个模块很便宜"，必须把派生推迟到**第一次真的要目录**。


__all__ = [
    "EFFECT_APPROVAL",
    "EFFECT_READ_ONLY",
    "REJECTED_TOOL_ALIASES",
    "TEXT_ONLY_AGENTS",
    "TOOL_CATALOG",
    "TOOL_TEXT",
    "WIRING_FAILURES",
    "all_tool_names",
    "catalog_gaps",
    "entry_agents",
    "grouped_catalog",
    "is_known_tool",
    "shared_tools",
    "shipped_catalog",
    "tool_entry",
    "tool_title",
    "tools_for_agent",
]

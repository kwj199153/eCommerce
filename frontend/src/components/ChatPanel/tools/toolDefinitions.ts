/**
 * Agent 工具定义
 * 每个 Agent 拥有一组工具卡片，点击后在 ChatPanel 下方展示对应表单
 *
 * 排序（按真实业务流）：
 *   1. 选品分析师 → 2. 竞品监控员 → 3. AIGC媒体生成器
 *   4. Listing 优化师 → 5. 广告分析师 → 6. 智能客服 → 7. 运营复盘师
 */

export interface ToolDefinition {
  id: string
  name: string
  icon: string // emoji or icon name
  description: string
  mode: 'form' | 'chat' | 'page' // form=表单输入, chat=聊天触发, page=独立页面
  status: 'active' | 'coming_soon'
  category?: string // 分组标签
}

// 按 Agent 分组的工具集（业务流排序）
export const AGENT_TOOLS: Record<string, ToolDefinition[]> = {
  // ====== 0. 店秘书（全局入口 · 编排层）======
  // 不挂任何工具卡片：它只做意图调度（切 Agent / 打开资料库），不产出业务结果。
  'secretary': [],

  // ====== 1. 选品分析师 ======
  // 顶部工具栏只保留「产出报表」类 form 工具（蓝海挖掘 / 利润测算 / 选品大盘）。
  // 痛点分析 / 选品避坑 / 竞品对比 移入对话框上方的候选评估 chip 区，由 AI 推理模板针对载入候选输出。
  'product-research': [
    {
      // ★ 第 305 轮新增：选品市场洞察大盘云图（选品前看大盘）。
      //   ★ 第 311 轮：移到第一位 + 设为默认工具（老板拍板「选品大盘设默认、排功能栏第一」）。
      //   工具级双模式（对齐 isReviewDeskTool）：只有选中它才显示顶栏「对话/大屏」切换，
      //   避免给选品分析师的主形态（聊天+蓝海表单）挂一个常驻大屏开关。
      //   数据源：GET /product-research/market-insight/treemap（market_snapshots 表），
      //   演示账号看 mock 快照（degraded=true），真实账号空态 fail-closed。
      id: 'market-insight',
      name: '选品大盘',
      icon: '🗺️',
      description: '品类分布/价格带/竞争密度/搜索热度/卖家分布/趋势六维度大盘',
      mode: 'form',
      status: 'active',
      category: '市场分析',
    },
    {
      id: 'blue-ocean',
      name: '蓝海挖掘',
      icon: '🌊',
      description: '挖掘低竞争高需求品类机会',
      mode: 'form',
      status: 'active',
      category: '市场分析',
    },
    {
      id: 'profit-calc',
      name: '利润测算',
      icon: '💰',
      description: 'FBA费用+ROI+盈亏平衡计算',
      mode: 'form',
      status: 'active',
      category: '财务分析',
    },
  ],

  // ====== 2. 竞品监控员 ======
  // ★★ 第 255 轮：工具卡**全部退役**（老板：「竞品监控员 13 个工具没用到的删」；
  //    按源码复算实为 **12 条** —— 判据一律以源码为准，清单见下）。
  //    退役依据不是"看着没用"，而是**可达性复算** —— `currentSelectedTool` 的
  //    非 null 写入点只有两处：
  //      (a) 顶部工具栏 `handleToolbarToolClick`，而工具栏整块被 `Workspace.vue`
  //          的 `v-if` 对竞品监控员**排除**（该处注释原文：「顶部不展示工具卡片」）；
  //      (b) `resolveDefaultTool(agentId)`，而 `AGENT_DEFAULT_TOOL` 里
  //          **没有** competitor-intel 的登记。
  //    外加 `provide('currentSelectedTool')` 全仓 **0 个** inject 消费者。
  //    ⇒ 这 13 条卡此前是「编译得通、永远点不到」的死代码，且各自还拖着一份
  //      配置面板 / 结果组件 / mock 执行器（本轮一并退役 **13 个文件**：
  //      7 个配置面板 + 6 个结果卡）。
  //
  // ★ 竞品监控员**不是没有界面**：它的右侧常驻视图走的是「未选工具」分支下
  //    `!currentTool && isCompetitorIntel` 的 `IntelBoardConfig`（监控大屏）——
  //    那条路径与工具卡无关，原样保留。
  //
  // ★ 刻意**留空数组**而不是删掉这个 key：`AGENT_TOOLS[agentId] === []`
  //    （"它没有工具卡"）与「这个 key 不存在」是两件事 —— 后者会让工具栏 /
  //    默认工具解析走上另一条分支，那是**静默的行为差异**，不是报错。
  //
  // ★ 防复发：同类"注册了却没有任何入口"的 id 由
  //    `scripts/check-tool-reality.cjs` 的 F1 直接判红（要么接线、要么登记去向）。
  'competitor-intel': [],

  // ====== 3. AIGC 媒体生成器 ======
  'aigc-media': [
    {
      id: 'static-asset-gen',
      name: '静态素材生成',
      icon: '🎨',
      description: '白底三视图、细节图、场景图、分镜首帧图（载入产品自动回填）',
      mode: 'form',
      status: 'active',
      category: '图片生成',
    },
    {
      id: 'video-script-gen',
      name: '短视频带货脚本',
      icon: '🎬',
      description: '基于卖点/痛点自动生成带货脚本与结构化分镜表（支持人工编辑）',
      mode: 'form',
      status: 'active',
      category: '视频脚本',
    },
    {
      id: 'ai-video-generator',
      name: 'AI 短视频生成',
      icon: '🎥',
      description: '基于分镜首帧+运镜指令分段生成短视频镜头（支持素材库选帧）',
      mode: 'form',
      status: 'active',
      category: '视频生成',
    },
  ],

  // ====== 4. Listing 优化师 ======
  // 顶部工具栏 4 个「生成类」form 工具（关键词 / 标题 / 五点 / 长描述）。
  // 点击工具 → 跳转到右侧「文案工作区」对应模块并高亮；SEO 诊断已下线。
  'listing-generator': [
    {
      id: 'keyword-miner',
      name: '关键词',
      icon: '🔑',
      description: '长尾词挖掘与搜索词扩展 · 竞品词源分析',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'title-gen',
      name: '标题',
      icon: '📝',
      description: '多版本标题生成 + 关键词覆盖（仅改标题；五点/长描述请用各自工具）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'bullet-gen',
      name: '五点',
      icon: '✨',
      description: '卖点提炼与五点撰写（仅改五点）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
    {
      id: 'desc-gen',
      name: '长描述',
      icon: '📄',
      description: 'A+ Content 风格产品长描述（仅改长描述模块）',
      mode: 'form',
      status: 'active',
      category: 'Listing优化',
    },
  ],

  // ====== 5. 广告分析师 ======
  'ad-analysis': [
    { id: 'ad-diagnosis', name: '广告诊断', icon: '🩺', description: '广告账户健康检查 A-F评级', mode: 'form', status: 'active', category: '诊断' },
    { id: 'keyword-report', name: '词报告', icon: '📈', description: '搜索词效果分析 高低效词识别', mode: 'form', status: 'active', category: '报告' },
    { id: 'bid-suggest', name: '出价建议', icon: '💡', description: '智能出价策略推荐', mode: 'form', status: 'active', category: '优化' },
    { id: 'competitor-ad', name: '竞品广告', icon: '🎯', description: '竞争对手广告策略 SOV分析', mode: 'form', status: 'active', category: '竞品' },
    // ★ 第 316 轮：`budget-alloc`（预算分配）与 `anomaly-detect`（异常检测）两张卡
    //   已退役（老板「广告分析师删除异常检测、广告预算再平衡」）——
    //   连大屏 Tab / api 层 / 执行器 / 后端工具与端点一起退，不留零调用假路径。
  ],

  // ====== 6. 智能客服 ======
  // ★★ 第 284 轮：**话术检索 / 情感分析 / 创建工单 三张卡退役**（老板盘点后拍板）。
  //
  //    退役依据不是"看着没用"，而是**逐条通道复算** —— 五段全查（目录 status →
  //    配置面板 → 执行器注册表 → 前端 api 调用点 → 后端端点），结论：
  //
  //    · `faq-search`  前端 `searchFAQ` **零调用**、无执行器、无配置面板（落兜底
  //                    「配置面板开发中」）；后端端点虽在，搜索源却是进程内存里的
  //                    `MOCK_FAQ_DB` —— **不读任何知识库**。
  //    · `sentiment`   同上（`analyzeSentiment` 零调用）。★ 它此前挂着 `active`，
  //                    实际三重空壳 —— 与 `reply-draft` 的真实状态完全一样，
  //                    区别只在于**一个假装做了、一个诚实说没做**。
  //                    （括注：`reply-draft` 已于同轮第三段退役，理由见下方 ★★ 段
  //                      —— 当时这条对照只回答了「它算不算伪功能」，没回答
  //                       「它配不配占着这个位」。）
  //    · `ticket-create` 两条通道**一真一假**：对话路径 `createTicket` 真落库
  //                    `cs_tickets`；工具卡路径 `executeTicketCreate` 用
  //                    `Math.random()` 编个单号、**根本不落库**。
  //
  //    ★ 更根本的一层：这三张卡本质是「**把后端 Agent 工具又做了个前端按钮**」。
  //      后端 `modules/customer_service/tools.py` 的 4 个 LangChain 工具
  //      （`search_faq` / `create_ticket` / `analyze_sentiment` /
  //      `get_conversation_summary`）是给 `bind_tools` 用的，由技能正文
  //      （`modules/skills/seed.py` 的锚工具表：`cs-refund-playbook → search_faq`）
  //      在**对话**里被模型自己调用 —— 那才是它们的正确入口，而且走真 LLM。
  //      ⇒ 按钮壳不但多余，还用「点了报错」遮蔽了「其实用对话就能用」这件事。
  //
  // ★★ 第 284 轮第三段追加：`reply-draft` 退役。它连过两轮"coming_soon 是诚实
  //    占位"的豁免，但复核发现它**零依据** —— `src/` 真实定义只此一处；后端
  //    4 个客服工具里没有它；无配置面板 / 无执行器 / 无 api 调用 / 无规格表登记。
  //    而「回复建议」的职责已被两条客服技能正文覆盖（`cs-negative-review-triage`
  //    最后一步就是「回复」），对话里直接说「帮我写个回复」本来就能做。
  //    ⇒ 与上批同一把尺子（职责已被技能覆盖 + 无后端承载）。它的性质**不是
  //      伪功能**（从不假装能用），是**零价值登记** —— 占位也须有规格表依据。
  //
  //    ★ 后端 tool / 技能绑定 / `cs_tickets` 表 / `createTicket` api **一律不动** ——
  //      退的是前端这个壳，不是能力本身。
  //    ★ 防复发：`scripts/check-tool-reality.cjs` 的 F7 钉住「目录里 `active` 的 id
  //      必须能找到承载面板」—— 这正是本轮暴露的盲区（F1 只查反方向）。
  //
  // ★★★ 关于 `order-track` 的取数源 —— 第 292 轮复核：**下面这段旧记录已过期**
  // ---------------------------------------------------------------------------
  //    曾经的缺陷是「工具卡这条链**接错了取数源**」，`_fetch_order_info` 直接走
  //    `get_data_source(prefer="sp_api")` ⇒ 自有 `orders` 表里有数据也查不到。
  //    同一订单号 `AMZN123456789` 实测两条范式结论相反：
  //      · 对话 `stream_chat()` 范式 A（LLM `bind_tools`）→ 查 `orders` 表 ⇒ found=True
  //      · 工具卡 `invoke()`   范式 B（`_classify_intent` 短路）→ 走平台 ⇒ found=False
  //    ⇒ **已修（#1017）**：`_fetch_order_info` 现在**先查自有 `orders` 表**
  //      （`_fetch_order_from_trade` → `_map_order_from_trade`），查不到才走平台
  //      适配层 ⇒ 两条范式同源。**不要再按「它接错了源」去改它。**
  //    ★ 仍然成立的一条：前端 `composables/chat/replies/customerService.ts` 有一道
  //      本地正则短路（`/订单|order|物流|tracking/` 命中即 return）—— 命中时走
  //      `/customer-service/order/track` 结构化端点，**不经 LLM**（这是设计，不是缺陷）。
  //    ★ 渲染口径第 292 轮已统一到 `utils/orderTracking.ts`：工具卡
  //      （`results/OrderTrackResult.vue`）、对话正文、结果摘要三处共用一份字段清单。
  'customer-service': [
    { id: 'order-track', name: '订单追踪', icon: '📦', description: '订单状态与物流查询', mode: 'form', status: 'active', category: '订单' },
    // ★ 第 289 轮新增：差评工作台。为什么它走**功能栏（form 工具）**而不是
    //   对话框上方的快捷卡片：它是**确定性**的 —— 「列差评 / 关联的缺口在哪 /
    //   有没有处置」是查表就能答的问题，不需要 LLM 推理；
    //   而快捷卡片（skill）那一路要点的是「帮我归因、怎么赔、回复怎么说」，
    //   那才是不确定结论。两者的落点也因此不同：form 工具点击后在右栏出面板，
    //   skill chip 是在对话里一轮推理。
    //   ⇒ 注意唯一不属于它的东西：**批准 / 发放**（发券退款不可逆）只走
    //      面板里的人工按钮 + REST，不进任何 Agent 工具。
    { id: 'review-desk', name: '差评台账', icon: '📉', description: '本店差评清单与处置（含关联不上产品的孤儿差评）', mode: 'form', status: 'active', category: '售后' },
  ],

  // ====== 7. 运营复盘师 ======
  'review-analyst': [
    {
      id: 'weekly-report',
      name: '经营概览',
      icon: '📋',
      description: '自动汇总本周销售、广告、库存、客诉数据，生成结构化周报',
      mode: 'form',
      status: 'active',
      category: '周期报告',
    },
    {
      id: 'monthly-review',
      name: '月度数据',
      icon: '📊',
      description: '全维度月度经营分析：GMV/ACOS/转化率/退货率趋势对比',
      mode: 'form',
      status: 'active',
      category: '周期报告',
    },
    {
      id: 'product-performance',
      name: '商品表现',
      icon: '🏆',
      description: 'SKU级表现排名：销量/利润率/周转天数/好评率，识别爆款与滞销品',
      mode: 'form',
      status: 'active',
      category: '商品分析',
    },
    {
      id: 'inventory-health',
      name: '库存健康',
      icon: '📦',
      description: '库存周转分析：滞销预警/断货风险/补货建议/FBA长期仓储费预估',
      mode: 'form',
      status: 'active',
      category: '供应链',
    },
    {
      id: 'profit-audit',
      name: '利润分析',
      icon: '💰',
      description: '全链路利润核算：销售额-平台佣金-FBA-广告-退货-仓储=净利润',
      mode: 'form',
      status: 'active',
      category: '财务分析',
    },
  ],
}

// 获取指定 Agent 的工具列表
export const getAgentTools = (agentId: string): ToolDefinition[] => {
  return AGENT_TOOLS[agentId] || []
}

// 获取工具定义
export const getToolDefinition = (agentId: string, toolId: string): ToolDefinition | undefined => {
  return AGENT_TOOLS[agentId]?.find(t => t.id === toolId)
}

/**
 * 点 Agent 时右栏**默认选中**的工具（唯一真源）。
 *
 * ★ 为什么要有这张表：右栏默认态只有两种 ——「已选中某工具」与「空态」。
 *   空态对多数 Agent 是对的（工具多、用户目的不明确，让用户自己点）；
 *   但对**入口动作唯一**的 Agent，空态等于白让用户多点一步，还容易被当成面板坏了。
 *
 * ★ 为什么值写死 toolId、而不是「取数组第一个」：
 *   取 `AGENT_TOOLS[id][0]` 会让「默认工具」这个**产品决策**被工具数组的顺序决定 ——
 *   哪天有人在列表中间插一个工具，默认选中就静默变了，而且没人看得出来。
 *   写死 id 后顺序随便调；id 拼错由 `resolveDefaultTool` fail-closed 掉（返回 null 走空态）。
 *
 * ★ 登记项必须真实存在：值不是该 Agent 工具表里的 id ⇒ 门禁 `check-agent-scope-lifecycle.cjs`
 *   的 S6 判红（否则就是一条永远不会生效的死登记）。
 */
export const AGENT_DEFAULT_TOOL: Record<string, string> = {
  // 选品分析师：默认「选品大盘」（老板第 311 轮拍板：先看大盘赛道，再蓝海挖掘深挖产品）
  'product-research': 'market-insight',
  // AIGC 媒体生成器：3 个工具里最常用的是静态素材生成（对齐「点 Agent 就能出图」）
  'aigc-media': 'static-asset-gen',
}

/**
 * 解析「点 Agent 时右栏默认选中的工具」。
 *
 * fail-closed：没登记 ⇒ null（保持空态，由 TaskConfigPanel 渲染各 Agent 自己的默认视图）；
 * 登记了但该 Agent 的工具表里查不到 ⇒ 也 null —— **不回落成第一个工具**，
 * 否则 id 写错时用户会看到一个「从没人承诺过」的工具被选中，比空态更难排查。
 */
export const resolveDefaultTool = (agentId: string): ToolDefinition | null => {
  const toolId = AGENT_DEFAULT_TOOL[agentId]
  if (!toolId) return null
  return AGENT_TOOLS[agentId]?.find(t => t.id === toolId) ?? null
}

/** Agent 显示顺序（用于侧边栏/顶部导航排列） */
export const AGENT_ORDER = [
  'secretary',            // 0. 店秘书（全局入口）
  'product-research',     // 1. 选品分析师
  'competitor-intel',     // 2. 竞品监控员
  'aigc-media',           // 3. AIGC 媒体生成器
  'listing-generator',    // 4. Listing 优化师
  'ad-analysis',          // 5. 广告分析师
  'customer-service',     // 6. 智能客服
  'review-analyst',       // 7. 运营复盘师（新增）
]

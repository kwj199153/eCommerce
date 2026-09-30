/**
 * 工具执行器 —— 工具 ID → 执行结果
 *
 * 由 components/ChatPanel/index.vue 拆分而来（S1 低垂果实）。
 *
 * ★ #744（2026-09-18）删除 13 个**无入口**执行器。判据是可达性，不是「有没有配置面板」：
 *   `tool-analysis` 事件是注册表的唯一触发口，而 `AdDashboardConfig` / `ReviewConfig` /
 *   `IntelBoardConfig` 三个统一大面板**声明了 emits 却一次都不 emit**（各自直调 `@/api/*`）
 *   ⇒ 挂在他们下面的 13 个执行器没有任何入口 —— 是「后端已接好、前端被新面板取代」之后
 *   留下的假数据坟墓。删掉是净收益：它们仍在 `mock/` 里等着被重新 import 成第二条假数据路径。
 *   删除清单：ad-diagnosis / keyword-report / competitor-ad / anomaly-detect /
 *   monitor-dashboard / review-spy / weekly-report / monthly-review / ad-review /
 *   product-performance / inventory-health / profit-audit / action-plan。
 *   ★ 保留 bid-suggest —— 它经 `useAgentShortcuts` 的广告快捷 chip 可达。
 *   ★ 第 316 轮：`budget-alloc` 已随老板「广告分析师删除异常检测、广告预算再平衡」
 *     **整条退役** ⇒ 执行器 / `TOOL_DATA_SOURCE` / 注册表三处一并删除
 *     （不再是「保留待接线」的欠账）。
 * 每个执行器签名统一为 `async (params: any) => Promise<any>`，
 * 组件层通过 `toolExecutors` 注册表查表调用，不关心实现来源。
 *
 * ★ P0-2 批 1（2026-09-18）：**高曝光执行器已接真后端**
 *   - `ad-diagnosis`  → POST /ad-analysis/diagnose（**工具卡路径已于 #744 删除**：
 *     该工具由 `AdDashboardConfig` 接管；对话路径在 `composables/chat/replies/adAnalysis.ts`，
 *     直调 `diagnoseAdAccount`，不经过本文件）
 *   - `competitor`    → POST /competitor/compare
 *   - `seo-audit`     → POST /listing/analyze/seo
 *   - `bullet-gen`    → POST /listing/generate/bullets
 *   形状转换统一在 `@/utils/toolResultAdapters`。
 *   ★ 这 4 个**不再产出本地假数据**；后端给不出的字段一律留空，**不编造**。
 *
 * ★ 批 2（2026-09-20）：`order-track` → POST /customer-service/order/track
 *   原实现用 `Math.random()` 编状态 / 商品名 / 金额 / 运单号，**与后端
 *   `modules/customer_service/agent_cs.py::_mock_order_info` 是同一份谎话的
 *   两处实现**（连 carriers 列表都逐字相同）。后端已改 fail-closed 查 SP-API，
 *   这里同步改真调用 —— 否则界面上还剩第二条路径能编出一张假订单。
 *
 * ★ 其余执行器**仍是本地 mock**（本目录的定位所在），由前端门禁
 *   `scripts/check-tool-reality.cjs` 钉住「真调用执行器数量不得回退」。
 *
 * 外部依赖：上述 4 个 @/api 模块。
 *   ★ 第 255 轮（#918）：原先还依赖 `useMonitorPoolStore`（竞品监控那 6 个执行器
 *     读监控池做时序聚合），那 6 个已随 12 个**不可达**工具一并退役 ⇒
 *     本文件不再认识监控池。退役依据见 `toolDefinitions.ts` 的 `competitor-intel`。
 */
import { generateAssets } from '@/api/aigcMedia'
import { generateBullets, analyzeSEO } from '@/api/listingGenerator'
import { compareCompetitors } from '@/api/competitorIntel'
import { trackOrder } from '@/api/customerService'
import {
  adaptBulletGen,
  adaptSeoAudit,
  adaptCompetitorCompare,
} from '@/utils/toolResultAdapters'

// 辅助：时间范围标签
const timeRangeLabel = (tr: string): string => ({ '7d': '近7天', '30d': '近30天', '90d': '近90天' }[tr] || '近30天')

// 获取参数摘要文本
export const getParamSummary = (toolId: string, params: any): string => {
  switch (toolId) {
    case 'blue-ocean':
      return `- 站点：${params.marketplace || 'US'}\n- 类目：${params.category?.join(' > ') || '全部'}\n- 价格：$${params.priceMin || 0} ~ $${params.priceMax || '不限'}\n- 评论上限：${params.maxReviews || '不限'}条\n- 最小月销：${params.minMonthlySales || '不限'}件\n- 最低ROI：${params.minRoi || 0}%`
    case 'pain-points':
      return `- ASIN：${params.asin}\n- 分析深度：${params.depth === 'deep' ? '深度' : '快速'}\n- 评论范围：${params.reviewRange} 条`
    case 'competitor':
      return `- 竞品数：${params.validAsins?.length || params.asins?.filter((a: string) => a)?.length || 0} 个\n- 对比维度：${params.dimensions?.join('、') || '全部'}`
    case 'profit-calc':
      return `- 成本：$${params.costPrice || 0}\n- 售价：$${params.sellingPrice || 0}\n- 模式：${params.mode === 'reverse' ? '逆向定价' : '正向计算'}`
    case 'bid-suggest':
      return `- 策略：${({ aggressive: '激进', balanced: '平衡', conservative: '保守' } as Record<string, string>)[params.strategy] || '平衡'}\n- 目标ACoS：${params.target_acos || 20}%\n- 预算变动上限：±${params.budget_change_limit || 20}%`
    case 'order-track':
      return `- 查询方式：${params.order_id ? `订单号 ${params.order_id}` : params.email ? `邮箱 ${params.email}` : params.phone_last4 ? `手机后四位 ${params.phone_last4}` : '未知'}`
    // ===== Listing 优化师 =====
    case 'keyword-miner':
      return `- 种子词：${params.seed_keywords?.join('、') || '未指定'}\n- 目标数量：${params.target_count || 20} 个\n- 来源：${['种子词扩展', '竞品词', '类目词', '长尾词'].join(' / ')}`
    case 'title-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 语言：${params.language || '英语(美国)'}\n- 风格：${params.style || '专业电商'}`
    case 'bullet-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 卖点数：5 条\n- 风格：${params.style || '利益驱动型'}`
    case 'desc-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 模块：${params.modules?.join('、') || '品牌故事+规格+场景'}\n- 风格：${params.tone || '专业可信'}`
    case 'seo-audit':
      return `- ASIN：${params.asin || '未指定'}\n- 站点：${params.marketplace || 'US'}\n- 深度：${({ basic: '基础', full: '全面' } as Record<string, string>)[params.depth] || '全面'}`
    case 'ab-test':
      return `- 测试变量：标题+主图\n- 流量分配：A(40%) / B(30%) / C(30%)\n- 周期：${params.duration || 14} 天`
    // ===== 选品分析师 =====
    case 'pitfalls':
      return `- 目标产品：${params.asin || params.product_name || '未指定'}\n- 扫描维度：8 项全扫描\n- 严重程度过滤：全部`
    // ===== AIGC 媒体生成器 =====
    case 'static-asset-gen':
      // 不写「模式：图生图」—— 执行前无法断言模式，且后端目前只做文生图
      // （源图是前端 base64、没有图床），结果摘要按真实返回写（见 useChatOrchestrator）
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 素材类型：${(params.imageTypes || []).join('、') || '三视图'}\n- 数量：${params.quantity || 4} 张\n- 参考原图：${params.source_image_name || '未提供'}`
    case 'video-script-gen':
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 平台：${({ tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' } as Record<string, string>)[params.platform] || 'TikTok'}\n- 风格：${params.videoStyle || '痛点解决型'}\n- 分镜数：${params.sceneCount || 5} 个镜头（每镜 ${params.sceneDuration || 5} 秒）\n- 总时长：${params.total_scene_duration || 30}s`
    case 'ai-video-generator':
      const modeLabel = params.mode === 'single-image' ? '🖼️ 单图极速生成' : '🎬 分镜脚本专业模式'
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 生成模式：${modeLabel}\n` +
        (params.mode === 'single-image'
          ? `- 底图：${params.singleImageUrl ? '已选择 ✓' : '未选择'}\n- 产品文案：${params.singleCopyText?.slice(0, 50) || '未填写'}\n- 平台：${params.targetPlatform || 'TikTok'}`
          : `- 镜头数：${params.storyboardScenes?.length || 0} 个\n- 各镜头素材来源：${params.storyboardScenes?.filter((s: any) => s.imageUrl).length || 0}/${params.storyboardScenes?.length || 0} 已就绪\n- 平台：${params.targetPlatform || 'TikTok'}`)
    default:
      return JSON.stringify(params, null, 2)
  }
}

// 执行蓝海挖掘分析
//
// 数据源策略：**后端优先，本地 mock 兜底**。
//
// 修复记录：此前无条件走前端 mock（mock/data.ts:getBlueOceanCandidates），
// 而对话流走的是后端 MOCK_PRODUCTS —— 两边是两批互不相通的商品，
// 「右栏工具卡」与「对话结论卡」因此永远对不上。现在后端可用时两边同源；
// 后端不可用（离线演示）才退回本地 mock。
export const executeBlueOceanAnalysis = async (params: any): Promise<any> => {
  const fromBackend = await tryBackendBlueOcean(params)
  if (fromBackend) return fromBackend

  // ===== 兜底：本地 mock（离线演示）=====
  await new Promise(resolve => setTimeout(resolve, 300))
  const products = await generateMockBlueOceanProducts(params)

  return {
    type: 'blue_ocean',
    params,
    products,
    summary: {
      total_candidates: products.length,
      high_potential: products.filter((p: any) => p.blue_ocean_score >= 65).length,
      medium_potential: products.filter((p: any) => p.blue_ocean_score >= 40 && p.blue_ocean_score < 65).length,
      high_competition: products.filter((p: any) => p.blue_ocean_score < 40).length,
    },
    report: `## 蓝海市场分析报告\n\n（离线演示数据）系统在 **${params.marketplace || 'US'}** 站点发现 **${products.length}** 个候选商品。`,
    source: 'local-mock',
  }
}

/**
 * 尝试从后端获取蓝海结果，并把响应适配成工具卡期望的形状。
 * 后端不可用 / 无结果 → 返回 null，由调用方降级到本地 mock。
 */
const tryBackendBlueOcean = async (params: any): Promise<any | null> => {
  try {
    const { analyzeBlueOcean } = await import('@/api/productResearch')
    const raw: any = await analyzeBlueOcean({
      marketplace: params.marketplace || 'amazon_us',
      category: params.category || [],
      price_min: params.priceMin ?? null,
      price_max: params.priceMax ?? null,
      max_reviews: params.maxReviews ?? 100,
      min_monthly_sales: params.minMonthlySales ?? 100,
      min_roi: params.minRoi ?? 20,
    })
    // 后端统一包一层 ApiResponse：{ success, message, data }
    const res: any = raw?.data ?? raw

    const products = (res?.products || []).map((p: any) => ({
      ...p,
      // 工具卡表格读取的字段名对齐（后端字段已同名，这里只补缺失项）
      main_image: p.main_image || p.image_url || '',
      brand: p.brand || '',
      marketplace: p.marketplace || params.marketplace || 'us',
    }))
    if (!products.length) return null

    return {
      type: 'blue_ocean',
      params,
      products,
      summary: {
        total_candidates: res.total_candidates ?? products.length,
        high_potential: res.premium_count ?? 0,
        medium_potential: res.moderate_count ?? 0,
        high_competition: res.high_competition_count ?? 0,
      },
      report: res.analysis_summary || '',
      source: 'backend',
    }
  } catch (e) {
    console.warn('[蓝海挖掘] 后端不可用，降级本地 mock：', e)
    return null
  }
}

/**
 * 生成 Mock 蓝海产品数据
 * 从 mock/data.ts 的增强蓝海候选（getBlueOceanCandidates）取数，
 * 已含 main_image 及变体数/卖家数/头程/类目/趋势等扩展字段。
 */
const generateMockBlueOceanProducts = async (params: any): Promise<any[]> => {
  const { getBlueOceanCandidates } = await import('@/mock/data')
  const products = getBlueOceanCandidates(8)

  // 追加 params 信息（marketplace/category 透传给上层渲染）
  return products.map(p => ({
    ...p,
    marketplace: params.marketplace || p.marketplace || 'us',
    category: params.category?.join(' > ') || p.category_l2 || p.category_path?.join(' > ') || p.category || 'Home & Kitchen',
  }))
}

// 执行痛点分析（Mock）
export const executePainPointAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))
  const { getMockPainPointAnalysis } = await import('@/mock/data')
  return getMockPainPointAnalysis(params.asin)
}

// 执行竞品对比（Mock）
export const executeCompetitorAnalysis = async (params: any): Promise<any> => {
  // ★ 真调后端。/competitor/compare 硬校验 asins >= 2（<2 直接 400），
  //   这里提前拦下来，给的是**可执行的下一步**而不是一个后端 400 文案。
  const asins: string[] = (params?.validAsins || params?.asins || []).filter((a: any) => !!a)
  if (asins.length < 2) {
    throw new Error('竞品对比至少需要 2 个 ASIN —— 请在右侧补齐后再试')
  }

  const resp: any = await compareCompetitors({ asins, dimensions: params?.dimensions })
  if (resp?.success === false) {
    throw new Error(resp?.message || '竞品对比失败')
  }

  // ★ 后端在「ASIN 一个都解析不到」时返回 HTTP 200 + success:true + data.error（**伪成功**）。
  //   只判 success === false 会把这种失败当成功，界面就会拿空数组渲染出一份
  //   「对比完成」的空报告。实测：{"error":"至少需要2个竞品进行对比"}。
  const bizErr = resp?.data?.error
  if (bizErr) {
    throw new Error(typeof bizErr === 'string' ? bizErr : '竞品对比失败：未解析到任何竞品')
  }

  const adapted = adaptCompetitorCompare(resp, params)
  if (!adapted.competitors.length) {
    throw new Error('竞品对比未解析到任何竞品 —— 请确认这些 ASIN 是否已被系统收录')
  }
  return adapted
}

// 执行利润测算 —— 已下线（09-14）
//
// 这里原本是第二套利润公式：FBA 按售价 12% 凭空估算、头程用 `|| 3.2` 兜底
// （用户填 0 也会被换成 3.2），且只算 4 个成本项，与右栏面板的 13 项口径对不上 ——
// 同一份输入因此出现两个结果。现在利润测算统一走后端
// POST /stores/profit/calculate（费率取自店铺费率模板），入口在 useChatOrchestrator
// 的 resolveProfitResult，不再经过本文件。

// ========== 广告分析 Mock 执行函数 ==========

// 执行出价建议（Mock）
export const executeBidSuggest = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))

  const keywords = [
    { keyword: 'coffee grinder manual', match_type: 'exact', current_bid: 0.85, suggested_bid: 1.08, bid_change_pct: 27, reason: '该词转化率高且 ACoS 优于平均，提高出价可获得更多优质流量', expected_impact: '预计+27% 点击量，ACoS ↓', priority: 'high' },
    { keyword: 'ceramic burr grinder', match_type: 'phrase', current_bid: 0.72, suggested_bid: 0.91, bid_change_pct: 26, reason: '近期该词转化有明显上升趋势，建议抢占更多曝光', expected_impact: '预计+26% 点击量，ACoS ~', priority: 'high' },
    { keyword: 'portable coffee grinder', match_type: 'exact', current_bid: 1.15, suggested_bid: 0.89, bid_change_pct: -23, reason: '该词长期 ACoS 偏高，降低出价以控制成本', expected_impact: '预计-23% 点击量，ACoS ↓', priority: 'high' },
    { keyword: 'hand crank coffee mill', match_type: 'phrase', current_bid: 0.65, suggested_bid: 0.49, bid_change_pct: -25, reason: '点击量大但转化不稳定，先降低出价观察', expected_impact: '预计-25% 点击量，ACoS ↓', priority: 'medium' },
    { keyword: 'best coffee grinder 2024', match_type: 'broad', current_bid: 1.35, suggested_bid: 1.02, bid_change_pct: -24, reason: 'Broad 匹配 CPC 偏高但 ROI 不理想，建议降至合理区间', expected_impact: '预计-24% 点击量，ACoS ↓', priority: 'low' },
  ]

  const budgetImpact = keywords.reduce((sum, k) => sum + k.suggested_bid - k.current_bid, 0)

  return {
    strategy_type: params.strategy || 'balanced',
    total_keywords: keywords.length,
    recommendations: keywords,
    budget_impact: Math.round(budgetImpact * 100) / 100,
    expected_acos_change: -(4 + Math.random() * 4),
    rationale: '基于近30天转化数据、竞争强度、季节性因素综合计算。平衡策略兼顾曝光与效率。',
  }
}
// ========== 客服 Mock 执行函数 ==========

// 执行订单追踪（真后端）
//
// ★ 2026-09-20（批 2）：原实现用 Math.random() 编状态 / 商品名 / 金额 / 运单号，
//   与后端 modules/customer_service/agent_cs.py::_mock_order_info 是**同一份谎话的
//   两处实现**。后端已改 fail-closed 查 SP-API，这里同步改真调用 ——
//   否则界面上还剩第二条路径能编出一张假订单。
//
//   返回形状与后端 OrderTrackResponse 对齐：`{found, order, message}`。
//   查不到时 `order` 是 **null**（不是编一份），消费方必须先判 `found`。
export const executeOrderTrack = async (params: any): Promise<any> => {
  const res: any = await trackOrder({
    order_id: params.order_id || undefined,
    email: params.email || undefined,
    phone_last4: params.phone_last4 || undefined,
  })
  // 后端直返 body（无 {code,data} 信封）；这里兼容两种形状
  const payload = res?.data ?? res ?? {}
  return {
    found: !!payload.found,
    order: payload.order ?? null,
    message: payload.message || '',
  }
}

// ========== Listing 优化师 Mock 执行函数 ==========

// 执行关键词挖掘（Mock）
export const executeKeywordMiner = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  const seedKeywords = params.seed_keywords || ['coffee grinder', 'portable grinder']
  const mockKeywords = [
    { keyword: 'manual coffee grinder ceramic burr', search_volume: 12500, competition: 'medium', suggested_bid: 0.92, relevance: 98, source: 'seed_expand' },
    { keyword: 'portable coffee bean grinder travel', search_volume: 8900, competition: 'low', suggested_bid: 0.75, relevance: 95, source: 'seed_expand' },
    { keyword: 'hand coffee grinder stainless steel', search_volume: 6700, competition: 'low', suggested_bid: 0.68, relevance: 92, source: 'competitor' },
    { keyword: 'electric coffee grinder small', search_volume: 15800, competition: 'high', suggested_bid: 1.25, relevance: 88, source: 'category' },
    { keyword: 'aeropress compatible coffee grinder', search_volume: 3200, competition: 'low', suggested_bid: 0.52, relevance: 85, source: 'long_tail' },
    { keyword: 'cold brew coffee grinder coarse', search_volume: 4500, competition: 'medium', suggested_bid: 0.78, relevance: 82, source: 'long_tail' },
    { keyword: 'best coffee grinder under 30 dollars', search_volume: 9200, competition: 'medium', suggested_bid: 0.88, relevance: 90, source: 'question' },
    { keyword: 'quiet coffee grinder for office', search_volume: 2800, competition: 'low', suggested_bid: 0.45, relevance: 80, source: 'long_tail' },
    { keyword: 'hario mini mill slim plus alternative', search_volume: 1900, competition: 'low', suggested_bid: 0.38, relevance: 75, source: 'competitor' },
    { keyword: 'camping coffee equipment manual', search_volume: 5100, competition: 'low', suggested_bid: 0.58, relevance: 78, source: 'category' },
    { keyword: 'gift for coffee lover dad birthday', search_volume: 3400, competition: 'low', suggested_bid: 0.55, relevance: 72, source: 'question' },
    { keyword: 'coffee mill hand crank adjustable', search_volume: 4100, competition: 'medium', suggested_bid: 0.72, relevance: 86, source: 'seed_expand' },
  ]

  return {
    type: 'keyword_miner',
    params,
    seed_keywords: seedKeywords,
    total_found: mockKeywords.length,
    // 透传来源产品，供结果卡「应用到当前产品」定位
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    keywords: mockKeywords.sort((a, b) => b.relevance - a.relevance),
    summary: `## 关键词挖掘报告\n\n基于 **${seedKeywords.join('、')}** 种子词，共挖掘 **${mockKeywords.length}** 个候选关键词。\n\n### 分布\n- 🔍 高搜索量 (>10K)：${mockKeywords.filter(k => k.search_volume > 10000).length} 个\n- 🎯 低竞争高相关：${mockKeywords.filter(k => k.competition === 'low' && k.relevance >= 85).length} 个\n- 📈 推荐立即投放：${mockKeywords.filter(k => k.relevance >= 90 && k.competition !== 'high').length} 个`,
  }
}

// 执行标题生成（Mock）
export const executeTitleGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 800))

  const productName = params.product_name || 'Portable Coffee Grinder'
  // 根据店铺平台切换返回结构
  const isSimplified = params.is_simplified === true
  const platformMode = params.platform_mode || 'amazon'

  // ===== Temu / Shopee 简化模式：短标题 + 商品详情（无五点/Search Term/A+） =====
  if (isSimplified) {
    const platformLabel = platformMode === 'temu' ? 'Temu' : 'Shopee'
    const shortTitleList = [
      { title: `${productName} 静音USB 卧室便携`, score: 94, char_count: 28, seo_score: 92, notes: '短标题，核心词前置' },
      { title: `${productName} 大容量 低噪 办公室桌面`, score: 91, char_count: 26, seo_score: 90, notes: '突出场景词' },
      { title: `${productName} 两档雾量 自动断电`, score: 88, char_count: 22, seo_score: 87, notes: '突出差异化功能' },
      { title: `${productName} 迷你便携 七彩夜灯`, score: 85, char_count: 20, seo_score: 85, notes: '突出情感/颜值卖点' },
      { title: `${productName} 送礼佳选 母婴可用`, score: 82, char_count: 18, seo_score: 83, notes: '突出人群标签' },
    ]
    return {
      type: 'title_gen',
      params,
      platform_mode: platformMode,
      is_simplified: true,
      // 来源标记：产品库模式 → 走「应用到当前产品 Listing」；手动模式 → 走「保存为草稿」
      _source: params.source === 'product_library' ? 'product' : 'manual',
      product_id: params.product_id,
      product_name: productName,
      short_titles: shortTitleList,
      // 兼容 TitleGenerator.vue 的字段
      recommended_title: shortTitleList[0].title,
      char_count: shortTitleList[0].char_count,
      word_count: shortTitleList[0].title.length,
      variants: shortTitleList.slice(1).map((t: any) => ({ title: t.title, seo_score: t.seo_score })),
      detail_desc: {
        title: `${productName} 商品详情`,
        sections: [
          { heading: '产品亮点', content: `这款${productName}采用 500ml 大容量水箱，整夜加湿无需频繁加水；双雾量模式（持续/间歇）满足不同场景需求，USB 供电搭配静音运行，办公、卧室两相宜。` },
          { heading: '核心卖点', content: '① 顶置注水口，无需拆机加水；② 智能自动断电保护，水位低自动停机；③ 内置七彩夜灯，营造温馨氛围；④ 8 小时定时，安心入睡。' },
          { heading: '适用场景', content: '卧室 / 办公室 / 母婴房 / 宿舍，干燥季节的保湿利器，缓解皮肤干燥、嘴唇起皮。' },
          { heading: '规格参数', content: '容量：500ml · 雾量：双档可调 · 噪音：≤25dB · 供电：5V USB · 尺寸：小巧便携 · 材质：食品级安全材质' },
        ],
      },
      tips: [
        `${platformLabel} 短标题建议 20-40 字符，核心卖点前置`,
        '商品详情用「短段落 + 符号列表」结构，移动端易读',
        '关键词自然植入标题与详情首段，避免堆砌',
        '突出价格优势与使用场景，引导冲动下单',
      ],
    }
  }

  // ===== 亚马逊完整模式：标题 + 五点 + Search Term + A+ =====
  const titleList = [
    { title: `${productName} with Ceramic Burrs, Manual Hand Coffee Bean Grinder Adjustable Coarseness, Portable Compact for Travel Camping Office Home Kitchen`, score: 94, char_count: 148, features: ['Ceramic Burrs', 'Adjustable', 'Portable'], seo_score: 91 },
    { title: `Premium ${productName}, Stainless Steel Manual Coffee Grinder with Conical Burr Mill, Quiet Operation & Easy Clean, Perfect for Aeropress Pour Over French Press`, score: 89, char_count: 152, features: ['Stainless Steel', 'Quiet', 'Easy Clean'], seo_score: 88 },
    { title: `${productName} Professional, Hand Crank Coffee Mill with Precision Engineering, No Battery Needed, Eco-Friendly & Durable Design`, score: 86, char_count: 138, features: ['Professional', 'No Battery', 'Eco-Friendly'], seo_score: 84 },
    { title: `Manual ${productName} Portable Mini, Ceramic Burr Coffee Bean Grinder Fine to Coarse Setting, Travel-Friendly Hand Coffee Mill Small Size`, score: 83, char_count: 140, features: ['Portable Mini', 'Fine to Coarse', 'Travel'], seo_score: 82 },
    { title: `${productName} with Brush & Storage Bag, Ergonomic Hand Coffee Grinder Anti-Slip Base, Dishwasher Safe Parts, Gift Box Included`, score: 80, char_count: 136, features: ['With Accessories', 'Ergonomic', 'Gift Ready'], seo_score: 79 },
  ]
  return {
    type: 'title_gen',
    params,
    platform_mode: platformMode,
    is_simplified: false,
    // 来源标记：产品库模式 → 走「应用到当前产品 Listing」；手动模式 → 走「保存为草稿」
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    product_name: productName,
    titles: titleList,
    // 兼容 TitleGenerator.vue 的字段
    recommended_title: titleList[0].title,
    char_count: titleList[0].char_count,
    word_count: titleList[0].title.split(' ').length,
    variants: titleList.slice(1).map((t: any) => ({ title: t.title, seo_score: t.seo_score })),
    core_keywords: [
      { word: 'Portable Coffee Grinder', search_volume: 45000, competition: 'high', placed_in_title: true },
      { word: 'Manual Coffee Grinder', search_volume: 32000, competition: 'medium', placed_in_title: true },
      { word: 'Ceramic Burr', search_volume: 18000, competition: 'low', placed_in_title: true },
      { word: 'Adjustable Coarseness', search_volume: 12000, competition: 'low', placed_in_title: true },
      { word: 'Travel', search_volume: 28000, competition: 'high', placed_in_title: true },
    ],
    tips: [
      '标题前 80 字符最重要，核心关键词前置',
      '避免全大写或特殊符号（!@#$）',
      '数字用阿拉伯数字（如 "5 Settings" 而非 "Five"）',
      '品牌名 + 核心卖点 + 材质 + 适用场景 + 兼容性',
    ],
  }
}

// 执行五点描述生成（Mock）
export const executeBulletGen = async (params: any): Promise<any> => {
  // ★ 真调后端。入参只有 product_name 是必需的（后端 min_length=2）
  const productName = String(params?.product_name || '').trim()
  if (productName.length < 2) {
    throw new Error('请先填写或载入产品名称（至少 2 个字符）')
  }

  // 右栏面板的 features 是 [{name, detail}]，后端要 string[] ⇒ 在这里合流。
  // 兼容两种入参形态，避免面板改名后静默丢参。
  const rawFeatures = Array.isArray(params?.features) ? params.features : []
  const features = rawFeatures
    .map((f: any) =>
      typeof f === 'string' ? f : [f?.name, f?.detail].filter(Boolean).join(': '),
    )
    .map((s: string) => String(s || '').trim())
    .filter(Boolean)

  const resp: any = await generateBullets({
    product_name: productName,
    features: features.length ? features : undefined,
    tone: params?.style || params?.tone || undefined,
  })
  if (resp?.success === false) {
    throw new Error(resp?.message || '五点描述生成失败')
  }
  const adapted = adaptBulletGen(resp, params)
  // ★ 同上：空信封会让结果卡渲染出「五点描述：0 条」，
  //   与「后端真的生成了 0 条」**不可区分** ⇒ 当场抛错，别让空壳冒充结果。
  if (adapted.bullets.length === 0) {
    throw new Error('五点描述未返回任何内容 —— 请确认产品名称与卖点信息是否完整，或稍后重试')
  }
  return adapted
}

// 执行描述生成（Mock）
export const executeDescGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 800))

  const productName = params.product_name || 'Premium Coffee Grinder'
  return {
    type: 'desc_gen',
    params,
    product_name: productName,
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    description: {
      title: `Discover the Art of Perfect Coffee with ${productName}`,
      sections: [
        { heading: 'Why Choose Our Manual Coffee Grinder?', content: 'In a world of electric everything, there\'s something deeply satisfying about grinding your own beans by hand. Our ceramic burr grinder puts YOU in control — from powder-fine espresso grounds to chunky cold brew bits. The result? Coffee that tastes noticeably fresher, more aromatic, and more YOU.' },
        { heading: 'Ceramic vs Steel: The Clear Winner', content: 'While steel burrs generate heat during grinding (literally cooking your beans and killing flavor), our advanced ceramic burrs remain naturally cool. This means every cup preserves the delicate volatile compounds that give coffee its complex taste profile. Professional baristas know this secret — now you do too.' },
        { heading: 'Engineered for Every Brewing Method', content: 'Whether you\'re an AeroPress enthusiast, a pour-over purist, or a French press fanatic, our 15+ coarseness settings have you covered. The smooth adjustment dial clicks into place with satisfying precision, so you can recreate your perfect grind every single time.' },
        { heading: 'Built for Adventure', content: 'At just 6 ounces and compact enough to slip into any bag, this grinder is your ultimate travel companion. Campsite mornings, office desk breaks, hotel rooms — enjoy freshly ground coffee anywhere. No cords, no batteries, no problem.' },
        { heading: 'Specifications', content: '- Material: Food-grade 304 Stainless Steel + High-Density Ceramic\n- Dimensions: 5.2" x 3.1" x 3.1"\n- Capacity: ~40g coffee beans (4 cups)\n- Weight: 6 oz (170g)\n- Warranty: 5-Year Full Coverage\n- Package Includes: Grinder, Cleaning Brush, Storage Pouch, User Manual' },
      ],
    },
    aplus_tips: [
      'A+ Content 使用品牌故事+场景化图片组合',
      '标准模块：产品对比表 → 使用场景图 → 规格参数 → 品牌故事',
      '图片建议：7张横幅(1460x600) + 7张方图(600x600)',
    ],
  }
}

// 执行 SEO 诊断（Mock）
export const executeSEOAudit = async (params: any): Promise<any> => {
  // ★ 真调后端。★ 关键：后端 /listing/analyze/seo 要的是**完整 Listing 文本**
  //   （title / bullets / description 三件必填），**不是 ASIN** ——
  //   后端没有「按 ASIN 查 Listing」的能力。
  //   文本由右栏面板在提交时从「载入产品」带过来（见 configs/SEOConfig.vue）。
  const title = String(params?.listing_title || '').trim()
  const bullets: string[] = Array.isArray(params?.listing_bullets)
    ? params.listing_bullets.map((b: any) => String(b || '').trim()).filter(Boolean)
    : []
  const description = String(params?.listing_description || '').trim()

  // 缺料就**明确说缺什么**，绝不拿假文案去诊断 —— 那是把本地随机数包装成 AI 结论。
  const missing: string[] = []
  if (!title) missing.push('标题')
  if (!bullets.length) missing.push('五点描述')
  if (!description) missing.push('产品描述')
  if (missing.length) {
    throw new Error(
      `该商品缺少${missing.join(' / ')}，无法做 SEO 诊断。` +
        '请先在顶部「载入产品」选一个已有 Listing 内容的商品，或先用 Listing 工具生成文案。',
    )
  }

  const resp: any = await analyzeSEO({
    title,
    bullets,
    description,
    search_terms: String(params?.listing_search_terms || ''),
    main_keyword: params?.listing_main_keyword || undefined,
    platform: params?.platform_mode || 'amazon',
  })
  if (resp?.success === false) {
    throw new Error(resp?.message || 'SEO 诊断失败')
  }
  const adapted = adaptSeoAudit(resp, params)
  // ★ 同上（#732）：空信封下 adaptSeoAudit 会产出 `overall_score: 0` 的**全 0 兜底**，
  //   且不带 `success/found/degraded` 任何标志 ⇒ 消费方无法与「真的考了 0 分」区分。
  //   （上面那道入参校验只挡得住「没带 Listing 文本」，挡不住「后端回空」。）
  if (!adapted.dimensions.length && !adapted.total_count) {
    throw new Error('SEO 诊断未返回任何结果 —— 请确认后端 /listing/analyze/seo 可用后重试')
  }
  return adapted
}

// 执行 A/B 测试（Mock）
export const executeABTest = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  return {
    type: 'ab_test',
    params,
    test_id: `AB-${Date.now().toString(36).toUpperCase()}`,
    variants: [
      {
        name: 'Control (当前)',
        id: 'A',
        title: 'Portable Coffee Grinder Manual with Ceramic Burrs, Hand Coffee Bean Grinder Adjustable Coarseness',
        main_image: '/mock/control.jpg',
        projected_ctr: 2.8,
        projected_conversion: 9.5,
      },
      {
        name: 'Variant B (新标题)',
        id: 'B',
        title: 'Premium Manual Coffee Grinder - Ceramic Conical Burr, 15 Settings, Portable for Travel & Camping',
        main_image: '/mock/variant_b.jpg',
        projected_ctr: 3.4,
        projected_conversion: 11.2,
        changes: ['标题更简洁，去除冗余词汇', '突出 "Premium" 和 "15 Settings"', '加入 "Camping" 场景词'],
      },
      {
        name: 'Variant C (新主图)',
        id: 'C',
        title: 'Portable Coffee Grinder Manual with Ceramic Burrs, Hand Coffee Bean Grinder Adjustable Coarseness',
        main_image: '/mock/variant_c.jpg',
        projected_ctr: 3.8,
        projected_conversion: 10.8,
        changes: ['保持原标题不变', '更换为手持展示图（人手握持）', '增加尺寸参照物'],
      },
    ],
    test_config: {
      duration_days: 14,
      traffic_split: { A: 40, B: 30, C: 30 },
      confidence_target: 95,
      minimum_sample_size: 500,
      estimated_completion: new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10),
    },
    hypothesis: '假设：更简洁的标题 + 场景化主图可提升 CTR 20%+',
  }
}

// ===== 选品分析师补充 =====

// 执行选品避坑（Mock）— 5大类风险评估
export const executePitfalls = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1200))

  const product = params.product || {}
  const productName = product.title || product.keyword || '目标产品'
  const platform = params.platform_label || '亚马逊'
  const isAmazon = params.is_amazon !== false

  // ====== 5 大类风险数据（四段式：等级 + 说明 + 原因 + 规避方案）======
  const risks = [
    // ----- 1. 知识产权侵权风险 -----
    {
      category: 'ip_infringement',
      category_name: '知识产权侵权风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '存在外观专利冲突风险',
      description: '检测到该类目（手动研磨器/厨房工具）存在 2 个活跃外观专利，产品外形与专利 D897,123 高度相似度 >70%，存在被诉侵权风险。',
      reason: 'USPTO 数据显示同类手持研磨器已有 3+ 项授权外观专利覆盖；头部品牌 Cuisinart / Breville 有主动维权记录，年均投诉 15+ 起。',
      solution: '① 聘请 IP 律师做 FTO（Freedom to Operate）分析报告（$800-1500）；② 外形差异化改款：改变握柄弧度/旋钮位置/材质拼接方式；③ 避开专利保护范围重新设计 ID。',
    },
    {
      category: 'ip_infringement',
      category_name: '知识产权侵权风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '关键词可能触发品牌词拦截',
      description: '核心关键词 "portable coffee grinder" 中包含部分品牌通用化词汇，若在标题中使用可能触发品牌方自动化投诉。',
      reason: 'Amazon Brand Registry 允许品牌方对注册商标词设置自动监控；"coffee grinder" 本身非商标但组合使用时易被误判。',
      solution: '标题中避免直接使用品牌名变体；使用同义词替换（如 hand mill / manual bean grinder）；保留使用证据截图以备申诉。',
    },

    // ----- 2. 平台合规与认证风险 -----
    ...isAmazon ? [{
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '缺少 FCC 认证（如含电动部件）',
      description: '若产品含任何电动/电子元件（即使仅是 LED 指示灯），美国站强制要求 FCC Part 15 认证，否则面临下架 + 销毁风险。',
      reason: 'FCC 对含 >9kHz 振荡电路的设备一律要求认证；亚马逊美国站对电子产品实行「零容忍」政策，无证商品直接下架并冻结资金。',
      solution: '① 确认是否含电子元件 → 如有必须做 FCC SDoC（$2000-5000，周期 2-4 周）；② 纯机械产品可提交免责声明；③ 提前准备测试报告备查。',
    }] : [{
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: `${platform} 平台禁售品类审核`,
      description: `${platform} 对食品接触类材料有特殊资质要求，陶瓷/不锈钢制品需提供食品级检测报告方可上架。`,
      reason: `${platform} 平台对 Kitchen 类目实行类目审核制；新卖家首次上架需提交材质证明；无证商品审核不通过且影响店铺评分。`,
      solution: `① 提前准备 FDA/LFGB 食品接触材料检测报告（$300-800）；② 在 ${platform} Seller Center 提前申请类目白名单；③ 准备产品实拍图+说明书供审核。`,
    }],
    {
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '不属于危险品/禁售品类',
      description: '产品为纯机械/手动操作，不含电池/液体/粉末/磁性物质，不属于平台禁售或需特殊物流申报的品类。',
      reason: 'IATA 危险品清单中手工研磨器不在受限列表；无需 MSDS/UN 编号；常规 FBA 入仓即可。',
      solution: '保持现有包装合规即可；建议在运输标签上标注 "Non-hazardous, Manual Device" 加速入库。',
    },

    // ----- 3. 供应链 & 物流损耗风险 -----
    {
      category: 'supply_chain',
      category_name: '供应链 & 物流损耗风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '陶瓷部件易碎 — 退货破损率预警',
      description: '陶瓷磨芯属于易碎材质，FBA 配送过程破损率预估 6-12%，远高于类目均值 3%。高破损率将导致差评激增和退货成本飙升。',
      reason: '陶瓷莫氏硬度虽高但脆性大；FBA 多次分拣抛掷易产生微裂纹；买家退货二次上架后破损概率翻倍；竞品差评中 "arrived broken" 占比达 18%。',
      solution: '① 包装升级：EVA 内衬 + 独立泡沫卡槽（增加 $0.8-1.2/件 成本）；② 考虑替换为不锈钢/钛合金磨芯（供应链询价对比）；③ 设置破损赔付预算（售价的 3-5%）。',
    },
    {
      category: 'supply_chain',
      category_name: '供应链 & 物流损耗风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '尺寸重量适合 FBA 小件标准',
      description: '预估尺寸 15x10x8cm / 重量 <0.5kg，属于 FBA 小件标准费率区间，头程运费和仓储费用可控。',
      reason: '小件标准 FBA 费率约 $2.41-3.22/件（取决于尺寸档位）；海运头程约 $1.2-1.8/kg；无超大件附加费。',
      solution: '优化包装体积争取落入 Small Standard 尺寸档（≤18x14x8cm 可降费率 $0.5/件）；批量发货降低头程单价。',
    },

    // ----- 4. 市场商业盈利风险 -----
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '头部寡头垄断 — 前 3 名占 72% 份额',
      description: '类目 Top3 链接（Cuisinart / Breville / OXO）合计占据 BSR 前 10 中的 7 席，新品自然排名突破 Top100 需 150+ 评论门槛。',
      reason: '头部链接评论数均 >5000 且持续投放 SB/SD 广告；类目月均新品存活率仅 23%；价格带 $20-40 区间竞争最激烈（红海区）。',
      solution: '① 避开红海价格带 → 定位 $45-65 细分高端市场（手动精品路线）；② 差异化卖点：可调节粗细度 + 陶瓷防氧化（竞品多为不锈钢）；③ 预算 $3000-5000 用于 Vine + SBV 冷启动。',
    },
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '竞品差评高频缺陷：陶瓷掉粉/调节松动',
      description: '分析 Top10 竞品共 2847 条差评，高频原生缺陷 TOP3：① 陶瓷磨芯掉粉污染咖啡（34%）② 粗细度调节钮松动回弹（28%）③ 收纳盖难清洗（19%）。',
      reason: '这些是结构性设计问题而非个别品控问题；说明全行业都未解决此痛点 = **差异化机会点**。',
      solution: '① 产品设计阶段加入「不掉粉」陶瓷烧结工艺要求；② 调节机构改用金属卡扣式替代螺纹式；③ 将以上三点作为 Listing 核心卖点 + A+ 页面重点突出。',
    },
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '毛利空间偏紧 — 推广预算不足',
      description: '按成本 $8 + 头程 $2 + FBA $3.5 + 佣金 15% 测算，定价 $29.99 时毛利仅 $11.99（40%），扣除广告 ACoS 25% 后净利仅 ~$4.5/件。',
      reason: '类目平均 CPC $0.85-$1.35（厨房小家电属高价词）；新品冷启动期 CVR 仅 3-6%；需要至少 50-80 单/月才能跑出足够数据优化广告。',
      solution: '① 目标定价 $39.99-44.99（毛利提升至 48-53%）；② 供应链端压价到 $6.5 以下（MOQ 500+）；③ 预留首 3 个月广告亏损预算 $2000-3000。',
    },

    // ----- 5. 运营推广风险 -----
    {
      category: 'operation_risk',
      category_name: '运营推广风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '变体泛滥 — 同质化变体过多稀释流量',
      description: '类目头部链接普遍采用 5-8 个颜色/尺寸变体策略，若只上单 SKU 会失去变体权重加成和关联流量优势。',
      reason: 'Amazon 变体系统会将父 ASIN 的评论/销量聚合到子链接；单 SKU 新品在搜索结果中视觉占比远低于多变体竞品。',
      solution: '① 上线时至少准备 3 个颜色变体（黑/白/原木色）；② 后续可增加尺寸变体（Standard / Mini / Travel）；③ 变体间保持差异化定位避免内部互搏。',
    },
    {
      category: 'operation_risk',
      category_name: '运营推广风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '测评风控可控 — 该类目非敏感类目',
      description: '手动研磨器类目不属于 Amazon 高危测评监控类目（不像耳机/充电宝/保健品），Vine 计划和早期亲友测评风险较低。',
      reason: 'Amazon 测评风控重点在 3C 电子/健康保健/美妆等刷单重灾区；厨具类目相对宽松；Vine 官方计划完全合规。',
      solution: '① 上线即注册 Vine Voice（$60/ASIN，最多 30 条评论）；② 首月亲友测评控制在 5 单以内并确保真实购买路径；③ 避免任何形式的折扣返现操作。',
    },
  ]

  // 统计各级别数量
  const highCount = risks.filter(r => r.level === 'high').length
  const mediumCount = risks.filter(r => r.level === 'medium').length
  const lowCount = risks.filter(r => r.level === 'low').length

  // 最终开发建议
  let verdict = ''
  if (highCount >= 2) {
    verdict = '❌ **放弃开发** — 存在多项致命风险（IP侵权 + 利润/垄断），建议更换选品方向或大幅改款后再评估'
  } else if (highCount >= 1) {
    verdict = '⚠️ **谨慎推进** — 存在高危风险项，必须在备货前解决（尤其是 IP 专利排查），其余中风险项制定应对预案后可启动'
  } else if (mediumCount >= 3) {
    verdict = '🟡 **有条件推进** — 无致命风险，但中风险项较多，建议逐条制定规避方案并预留额外预算后启动'
  } else {
    verdict = '✅ **推荐开发** — 风险整体可控，低风险为主，正常推进即可'
  }

  return {
    type: 'pitfalls_report',
    params,
    report_title: `《${productName} 选品风险评估报告》`,
    platform,
    is_amazon: isAmazon,
    product_info: {
      name: productName,
      asin: product.asin || '-',
      keywords: product.keywords || product.keyword || [],
      competitor_asins: product.competitor_asins || params.manual_asins || [],
    },
    summary: {
      high_count: highCount,
      medium_count: mediumCount,
      low_count: lowCount,
      total: risks.length,
      verdict,
      risk_score: Math.max(20, 100 - highCount * 20 - mediumCount * 8),
    },
    risks,
    generated_at: new Date().toLocaleString('zh-CN'),
  }
}

// ========== AIGC 媒体生成器 Mock 执行函数 ==========

// 执行静态素材生成 —— **真实出图**（通义万相，走异步任务 /aigc/jobs）
//
// 这里已不是 mock：单张约 15-25s。走「提交任务 → 轮询状态」而不是同步阻塞请求，
// 原因见 api/aigcMedia.ts 里 generateAssets 的注释（同步版最坏 720s，前端超时 300s
// ⇒ 会出现「HTTP 超时但钱已花、结果丢失」）。
//
// 失败时**显式降级并把原因带出去**，绝不用 picsum 之类的随机图凑数 ——
// 拿假图顶上去会让老板以为「生成的就是这个产品」（空状态优于虚构默认）。
export const executeStaticAssetGen = async (params: any): Promise<any> => {
  const productName = params._sourceProduct?.title || params.productName || ''
  const imageTypes: string[] = params.imageTypes?.length ? params.imageTypes : ['spu-main']
  const category = params._sourceProduct?.category || params.category || 'general'
  const extraDescription = [params.extraPrompt, params.sceneDescription, params.infographicPoints, params.selling_points]
    .filter((s: any) => typeof s === 'string' && s.trim())
    .join('；')

  if (!productName) {
    return {
      type: 'static_asset_gen',
      params,
      product_name: '',
      generated_assets: [],
      degraded: true,
      degraded_reason: '未指定产品：请先「载入产品」再生成素材',
    }
  }

  try {
    const waited: any = await generateAssets({
      product_name: productName,
      image_types: imageTypes,
      category,
      extra_description: extraDescription,
      // 前端 quantity（1-12）→ 单类型张数（夹紧 1-4，与后端 asset_gen.MAX_PER_TYPE 对齐）。
      // 6 类型 × 4 张 = 24 上限由后端 MAX_TOTAL=8 轮次裁剪，单类型必出至少 1 张。
      count_per_type: Math.max(1, Math.min(Math.floor(params.quantity) || 1, 4)),
      // 产品原图（base64 data URI）：传了 → 后端走图生图（原图参与生成）；空 → 退回文生图
      source_image: params.source_image || '',
    })

    const job = waited?.job || {}
    const jobId: string = job.id || ''
    // ★ 没有任务编号 ⇒ **提交就没成功**（后端空信封 / 网关截断），这与
    //   「任务已提交、只是等待超时」是**两件事**。旧写法把两者都归到
    //   「任务仍在后台执行（已等待约 4 分钟）」，会让用户去「我的任务」里
    //   找一个**根本不存在的编号**（归因错方向）。
    if (!jobId) {
      return {
        type: 'static_asset_gen',
        params,
        product_name: productName,
        generated_assets: [],
        failed: [],
        degraded: true,
        degraded_reason:
          '出图任务未提交成功（后端未返回任务编号）—— 请确认 AIGC 任务接口可用后重试；' +
          '不要盲目重跑：同一入参会被后端去重，但换参数重跑会真的再出一次图（按张计费）',
        generation_params: { mode: 'text2image', types: imageTypes, total_generated: 0 },
      }
    }
    const throttleNote = waited?.throttled
      ? `（轮询期间被限流 ${waited.throttled} 次，已自动退避，未影响任务）`
      : ''

    // ★ 等待超时 ≠ 失败：任务仍在服务端继续跑，状态已落库。
    //   宁可如实说「还在生成」，也不要谎报失败让老板重跑一次（那就是重复花钱）。
    if (!waited?.settled) {
      return {
        type: 'static_asset_gen',
        params,
        product_name: productName,
        generated_assets: [],
        failed: [],
        degraded: true,
        degraded_reason:
          `任务仍在后台执行（已等待约 4 分钟，尚未完成）${throttleNote}` +
          `。任务不会因关闭页面而丢失，可稍后在「我的任务」里查看结果。`,
        pending_job_id: jobId,
        job_status: job.status || 'running',
        generation_params: { mode: 'text2image', types: imageTypes, total_generated: 0 },
        tips: [
          `任务编号：${jobId}（在任务列表里按此编号可查到结果）`,
          '不要把「仍在生成」当成失败重跑 —— 同一入参的进行中任务会被后端去重，但换参数重跑会真的再出一次图（按张计费）',
        ],
      }
    }

    if (job.status !== 'succeeded') {
      // 后端已明确失败：把原因原样带出（任务记录里也有同一条 reason）
      const reason = job.error || '出图任务失败（后端未给出原因）'
      return {
        type: 'static_asset_gen',
        params,
        product_name: productName,
        generated_assets: [],
        failed: [],
        degraded: true,
        degraded_reason: `素材生成失败：${reason}`,
        pending_job_id: jobId,
        job_status: job.status,
        generation_params: { mode: 'text2image', types: imageTypes, total_generated: 0 },
      }
    }

    const data = job.result || {}
    const generatedAssets = (data.assets || []).map((a: any) => ({
      id: a.id,
      url: a.url,
      type: a.type,
      desc: a.desc,
      prompt_hint: a.prompt,
      created_at: a.created_at,
    }))

    return {
      type: 'static_asset_gen',
      params,
      product_name: productName,
      generated_assets: generatedAssets,
      failed: data.failed || [],
      degraded: Boolean(data.degraded),
      degraded_reason: data.degraded_reason || null,
      notice: data.notice,
      job_id: jobId,
      elapsed_ms: job.elapsed_ms ?? null,
      generation_params: {
        mode: data.mode || 'text2image',
        model: data.model,
        source_image_used: Boolean(data.source_image_used),
        types: imageTypes,
        total_generated: generatedAssets.length,
        // 让老板能看见「这次是真的排队跑了多久」，而不是一个黑盒
        job_elapsed_ms: job.elapsed_ms ?? null,
      },
      tips: [
        '确认满意后，点结果卡片「归档到素材库」手动保存（可选择分组、绑定产品）',
        '白底图符合 Amazon 主图规范（纯白 #FFFFFF 背景，产品占 85% 以上面积）',
        '场景图注意文化中性（避免特定节日/宗教元素）',
        '分镜首帧图可关联到带货脚本的对应镜头',
      ],
    }
  } catch (error: any) {
    // 显式降级：给出可读原因，不用随机图凑数
    const status = error?.response?.status
    const detail =
      error?.response?.data?.detail || error?.message || '后端不可用或出图服务异常'
    const hint =
      status === 503
        ? '（异步执行器未启动：请确认 Redis 与 Celery worker 已运行）'
        : status === 429
          ? '（任务提交过于频繁或轮询过快，请稍后重试）'
          : ''
    return {
      type: 'static_asset_gen',
      params,
      product_name: productName,
      generated_assets: [],
      failed: [],
      degraded: true,
      degraded_reason: `素材生成失败：${detail}${hint}`,
      generation_params: { mode: 'text2image', types: imageTypes, total_generated: 0 },
    }
  }
}

// 执行短视频带货脚本生成（Mock）— 替代 分镜脚本
export const executeVideoScriptGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1000))

  const productName = params._sourceProduct?.title || params.productName || 'Portable Coffee Grinder'
  const platform = params.platform || 'tiktok'
  const videoStyle = params.videoStyle || 'problem-solution'
  const sellingPoints = params.selling_points || '静音研磨、陶瓷磨芯、便携小巧'
  const painPoints = params.painPoints || params.pain_points || '电动噪音大、研磨不均匀、难清洗'

  const platformLabel: Record<string, string> = { tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' }

  // 根据风格生成不同脚本
  const scriptTemplates: Record<string, { summary: string; scenes: any[] }> = {
    'problem-solution': {
      summary: `**痛点驱动型脚本**：前3秒用「电动研磨器吵得邻居敲门」钩住注意力 → 展示本产品静音优势 → 多场景便携证明 → CTA 限时优惠`,
      scenes: [
        { duration: 3, visual: '黑屏+音效"咚咚咚"：模拟邻居敲门声，画面出现"又来了？"', narration: '你的电动研磨器是不是也…', cameraMovement: 'static', shotSize: 'closeup', bgm: 'silence', subtitleStyle: 'bold-bottom', frameRef: '' },
        { duration: 5, visual: '产品 360° 缓慢旋转，手指轻触磨芯，完全无声', narration: '陶瓷磨芯，静音到…（耳语）…听不见', cameraMovement: 'rotate', shotSize: 'medium-shot', bgm: 'asmr', subtitleStyle: 'highlight', frameRef: '' },
        { duration: 5, visual: '分屏左=电动（噪音波形满格），右=本产品（波形平缓）', narration: '零电机噪音，只有咖啡豆碎裂的治愈声', cameraMovement: 'static', shotSize: 'full-shot', bgm: 'asmr', subtitleStyle: 'bold-bottom', frameRef: '' },
        { duration: 5, visual: '快切4场景：厨房→办公室→露营→旅行箱（各2秒）', narration: '家用、办公、户外、旅行…走到哪带到哪', cameraMovement: 'zoom-dolly', shotSize: 'wide-angle', bgm: 'upbeat', subtitleStyle: 'typewriter', frameRef: '' },
        { duration: 4, visual: '手握产品倒入咖啡粉，蒸汽升腾，满足表情', narration: '现磨的香气，真的不一样', cameraMovement: 'push-in-slow', shotSize: 'closeup', bgm: 'lo-fi', subtitleStyle: 'none', frameRef: '' },
        { duration: 3, visual: '产品+价格$24.99+购物车动画+倒计时', narration: '限时8折，链接在左下角，手慢无！', cameraMovement: 'static', shotSize: 'medium-shot', bgm: 'swoosh', subtitleStyle: 'highlight', frameRef: '' },
      ],
    },
    'product-showcase': {
      summary: `**产品展示型脚本**：纯视觉冲击路线，ASMR 研磨音效 + 电影级运镜 + 每帧都是壁纸级别`,
      scenes: [
        { duration: 3, visual: '暗光环境，一束聚光灯打在产品上，缓慢推近', narration: '', cameraMovement: 'push-in-slow', shotSize: 'closeup', bgm: 'cinematic', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '产品拆解动画：外壳→磨芯→粉仓→组装，每步微距', narration: '', cameraMovement: 'rotate', shotSize: 'extreme-closeup', bgm: 'asmr', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '咖啡豆落入→研磨→出粉→冲泡 全流程慢动作', narration: '', cameraMovement: 'ken-burns', shotSize: 'closeup', bgm: 'lo-fi', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '不同产地咖啡豆拼配特写（埃塞俄比亚/哥伦比亚/巴西）', narration: '', cameraMovement: 'pan-left-right', shotSize: 'extreme-closeup', bgm: 'acoustic', subtitleStyle: 'typewriter', frameRef: '' },
        { duration: 4, visual: '成品拉花特写，产品在背景虚化处若隐若现', narration: '', cameraMovement: 'pull-out-reveal', shotSize: 'medium-shot', bgm: 'cinematic', subtitleStyle: 'none', frameRef: '' },
        { duration: 5, visual: 'Logo + 品牌名 + Slogan 渐显', narration: '', cameraMovement: 'static', shotSize: 'full-shot', bgm: 'cinematic', subtitleStyle: 'bold-bottom', frameRef: '' },
      ],
    },
  }

  const template = scriptTemplates[videoStyle] || scriptTemplates['problem-solution']

  // ★ 分镜数 / 单镜时长由侧边栏参数驱动（见 VideoScriptConfig.vue 的「分镜数/单镜时长」）。
  //   此前这里按 videoStyle 直接吐一份硬编码 6 镜模板，用户配的镜头参数**完全没生效** ——
  //   这正是「配置改了结果不变」的根因。现在镜头表由这两个字段算出。
  // 分镜数取整；单镜时长保留 2 位小数 —— 侧边栏的联动会算出 7.5 这类非整数，
  // 用 Math.floor 会把它悄悄截成 7（结果表里的时长和用户配的就对不上了）。
  const r2 = (n: number) => Math.round(n * 100) / 100
  const sceneCount = Math.max(1, Math.round(Number(params.sceneCount) || 5))
  const sceneDuration = Math.max(0.5, r2(Number(params.sceneDuration) || 5))
  // 模板镜头是「内容池」：数量不够就循环复用（同风格续镜），多了就截断
  const pool = template.scenes
  const storyScenes = Array.from({ length: sceneCount }, (_, i) => {
    const base = pool[i % pool.length]
    return {
      ...base,
      duration: sceneDuration,
      visual: i < pool.length ? base.visual : `${base.visual}（同风格续镜）`,
    }
  })
  const totalDuration = r2(storyScenes.reduce((sum, s) => sum + s.duration, 0))

  return {
    type: 'video_script_gen',
    params,
    product_name: productName,
    platform,
    platform_label: platformLabel[platform],
    video_style: videoStyle,
    scene_count: sceneCount,
    scene_duration: sceneDuration,
    total_duration: totalDuration,
    script_summary: template.summary,
    selling_points_used: sellingPoints,
    pain_points_used: painPoints,
    storyboard: storyScenes.map((s, i) => ({
      ...s,
      scene: i + 1,
      time: r2(storyScenes.slice(0, i).reduce((sum, x) => sum + x.duration, 0)),
    })),
    shooting_tips: [
      `${platformLabel[platform]} 竖版 9:16 适配`,
      '前 3 秒必须有视觉或听觉钩子（痛点/悬念/反差）',
      '字幕要大且醒目（占画面 1/3），关键信息用高亮色',
      `共 ${sceneCount} 个镜头、每镜 ${sceneDuration} 秒（可在生成结果的分镜表里逐项改）`,
      '音乐版权：使用无版权素材库或原创 BGM',
    ],
  }
}

// 执行 AI 短视频生成（Mock）— 支持 分镜脚本专业模式 / 单图极速生成
export const executeAIVideoGenerator = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 2000))

  const productName = params._sourceProduct?.title || params.productName || 'Coffee Grinder'
  const mode = params.mode || 'storyboard-pro'     // storyboard-pro | single-image
  const sceneCount = params.storyboardScenes?.length || 1
  const clipCount = mode === 'single-image' ? 1 : sceneCount

  // 单图极速模式：围绕底图自动规划镜头
  const previewFrames = mode === 'single-image'
    ? [
        { timestamp: '00:02', url: params.singleImageUrl || `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_0/480/854`, desc: '底图 → 开场画面' },
        { timestamp: '00:06', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_1/480/854`, desc: '卖点演绎画面' },
        { timestamp: '00:10', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_2/480/854`, desc: '场景氛围画面' },
        { timestamp: '00:14', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_3/480/854`, desc: 'CTA 结尾画面' },
      ]
    : Array.from({ length: Math.min(clipCount, 6) }, (_, i) => ({
        timestamp: `00:${String(i * 4 + 2).padStart(2, '0')}`,
        url: (params.storyboardScenes?.[i]?.imageUrl) || `https://picsum.photos/seed/vframe_${productName.replace(/\s/g, '')}_${i}/480/854`,
        desc: `镜头 ${i + 1}${params.storyboardScenes?.[i]?.desc ? '：' + params.storyboardScenes[i].desc : ' 预览帧'}`,
      }))

  return {
    type: 'ai_video_generator',
    params,
    product_name: productName,
    mode,
    mode_label: mode === 'single-image' ? '单图极速生成' : '分镜脚本专业模式',
    video_url: '/mock/generated_video.mp4',
    thumbnail_url: params.singleImageUrl || `/mock/video_thumb_${Date.now()}.jpg`,
    clip_count: clipCount,
    metadata: {
      duration: (mode === 'single-image' ? 15 : clipCount * 4 + 2),
      resolution: (params.aspectRatio === '16:9') ? '1920x1080 (16:9)' : '1080x1920 (9:16)',
      format: 'MP4 H.264',
      fps: parseInt(params.fps) || 30,
      file_size: `${(clipCount * 3.2).toFixed(1)} MB`,
    },
    preview_frames: previewFrames,
    archived: false,  // 不再自动归档，由用户手动确认
    archive_target: params._sourceProduct ? params._sourceProduct.title : null,
    next_steps: [
      '预览视频，确认内容无误',
      '可选择：添加配音/更换背景音乐/调整节奏',
      '确认后可归档到营销素材库',
      `一键分发到 ${params.targetPlatform === 'tiktok' ? 'TikTok' : params.targetPlatform === 'reels' ? 'Instagram Reels' : '各平台'}`,
    ],
  }
}

/** 工具 ID -> 执行器。分发链由原来的 switch 改为查表（未知 id 返回 undefined）。 */

/**
 * ★ #745：每个已注册工具的**数据来源声明**。
 *
 * 存在理由：`toolExecutors.ts` 里的函数**签名一样、返回形状也一样**，
 * 所以「真调后端」和「本地编一份」在类型系统、单测、界面上**长得一模一样**。
 * 把来源写成代码里的常量之后：
 *   · 非真源的执行结果在对话里**显式标注**（见 `chat/useChatEventBridge.ts`）；
 *   · 门禁 `scripts/check-tool-reality.cjs` 断言 E 可做**双向对账** ——
 *     声明的 `backend` 必须被源码判据认定为真调用，声明 `local-mock` 的必须不是；
 *     且**注册表里的每个 id 都必须在这里登记**（漏登记 = 门禁红）。
 *
 *   backend           真调 `@/api/*`；拿不到数据必须**显式失败**（断言 D 会真跑一遍）
 *   backend-then-mock 先试后端，后端不可用才退回本地演示数据（离线演示）
 *   local-mock        纯本地演示数据
 */
export const TOOL_DATA_SOURCE: Record<string, 'backend' | 'backend-then-mock' | 'local-mock'> = {
  'competitor': 'backend',
  'order-track': 'backend',
  'bullet-gen': 'backend',
  'seo-audit': 'backend',
  'static-asset-gen': 'backend',
  'blue-ocean': 'backend-then-mock',
  'pain-points': 'local-mock',
  'bid-suggest': 'local-mock',
  'keyword-miner': 'local-mock',
  'title-gen': 'local-mock',
  'desc-gen': 'local-mock',
  'ab-test': 'local-mock',
  'pitfalls': 'local-mock',
  'video-script-gen': 'local-mock',
  'ai-video-generator': 'local-mock',
}

export const toolExecutors: Record<string, (params: any) => Promise<any>> = {
  'blue-ocean': executeBlueOceanAnalysis,
  'pain-points': executePainPointAnalysis,
  'competitor': executeCompetitorAnalysis,
  'bid-suggest': executeBidSuggest,
  'order-track': executeOrderTrack,
  'keyword-miner': executeKeywordMiner,
  'title-gen': executeTitleGen,
  'bullet-gen': executeBulletGen,
  'desc-gen': executeDescGen,
  'seo-audit': executeSEOAudit,
  'ab-test': executeABTest,
  'pitfalls': executePitfalls,
  'static-asset-gen': executeStaticAssetGen,
  'video-script-gen': executeVideoScriptGen,
  'ai-video-generator': executeAIVideoGenerator,
}

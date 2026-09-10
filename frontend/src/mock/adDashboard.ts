// ====== 广告分析师·大屏看板 Mock 数据 ======
// 以「手摇咖啡 grinder」产品线为统一业务场景，6 个 Tab 数据互相关联、指标自洽。
// 对接真实 SP-API / Advertising API 后替换为 fetch 接口。

// ──── 类型定义 ────

export interface AdMetric {
  name: string
  value: number
  unit: string
  benchmark: number
  status: 'good' | 'warning' | 'danger'
  change_pct: number
}

export interface AdCampaignRaw {
  campaign_name: string
  type: 'SP' | 'SB' | 'SD'
  status: 'active' | 'paused'
  impressions: number
  clicks: number
  spend: () => number
  sales: () => number
  acos: () => number
  roas: () => number
  ctr: () => number
  cvr: () => number
  cpc: () => number
  orders: () => number
}

/** 展开后的 Campaign 列表（供表格直接使用）—— 与 AdCampaignRaw 分离定义，避免方法/属性类型冲突 */
export interface AdCampaign {
  campaign_name: string
  type: 'SP' | 'SB' | 'SD'
  status: 'active' | 'paused'
  impressions: number
  clicks: number
  spend: number
  sales: number
  acos: number
  roas: number
  ctr: number
  cvr: number
  cpc: number
  orders: number
}

export interface SearchTerm {
  term: string
  impr: number
  clicks: number
  spend: number
  sales: number
  acos: number
  roas: number
  orders: number
  cpc: number
  match_type: 'exact' | 'phrase' | 'broad'
  efficiency: 'high' | 'medium' | 'low' | 'waste'
}

export interface BidSuggestion {
  keyword: string
  match_type: 'exact' | 'phrase' | 'broad'
  current_bid: number
  suggested_bid: number
  bid_change_pct: number
  reason: string
  expected_impact: string
  priority: 'high' | 'medium' | 'low'
}

export interface AdCompetitor {
  competitor_name: string
  asin: string
  share_of_voice: number
  overlap_keywords: number
  avg_position: number
  estimated_spend: number
  top_keywords: string[]
  strengths: string[]
  weaknesses: string[]
}

export interface BudgetAllocation {
  campaign_name: string
  current_budget: number
  suggested_budget: number
  allocation_pct: number
  reason: string
  expected_roas: number
}

export interface Anomaly {
  type: string
  severity: 'high' | 'medium' | 'low'
  campaign: string
  metric: string
  current_value: number
  expected_value: number
  deviation_pct: number
  detected_at: string
  possible_cause: string
  suggested_action: string
}

// ──── ① 账户总览数据 ────

export const AD_OVERALL_SCORE = 89
export const AD_OVERALL_GRADE = 'A'
export const AD_OVERALL_SUMMARY = '账户整体表现优秀，近30天内各项指标基本达标。SP 精准 Campaign 是主力转化引擎，SD 再营销 ROI 突出。'

export const AD_METRICS: AdMetric[] = [
  { name: 'ACoS', value: 21.3, unit: '%', benchmark: 22.0, status: 'good', change_pct: -2.1 },
  { name: 'RoAS', value: 4.7, unit: 'x', benchmark: 4.5, status: 'good', change_pct: 5.4 },
  { name: 'CTR', value: 0.42, unit: '%', benchmark: 0.40, status: 'good', change_pct: 3.2 },
  { name: 'CVR', value: 8.7, unit: '%', benchmark: 9.0, status: 'warning', change_pct: -1.5 },
  { name: 'CPC', value: 0.68, unit: '$', benchmark: 0.75, status: 'good', change_pct: -4.8 },
]

export const AD_CAMPAIGNS_RAW: AdCampaignRaw[] = [
  { campaign_name: '自动广告-广泛', type: 'SP', status: 'active',
    impressions: 125000, clicks: 3750,
    spend: () => 3375, sales: () => 10800, acos: () => 31.25, roas: () => 3.2,
    ctr: () => 3.0, cvr: () => 6.4, cpc: () => 0.9, orders: () => 240 },
  { campaign_name: '手动-精准-核心词', type: 'SP', status: 'active',
    impressions: 45000, clicks: 2250,
    spend: () => 2025, sales: () => 10328, acos: () => 19.6, roas: () => 5.1,
    ctr: () => 5.0, cvr: () => 11.2, cpc: () => 0.9, orders: () => 252 },
  { campaign_name: '手动-短语-长尾词', type: 'SP', status: 'active',
    impressions: 32000, clicks: 960,
    spend: () => 768, sales: () => 2918, acos: () => 26.32, roas: () => 3.8,
    ctr: () => 3.0, cvr: () => 8.5, cpc: () => 0.8, orders: () => 82 },
  { campaign_name: '品牌-SB-品牌词', type: 'SB', status: 'active',
    impressions: 28000, clicks: 812,
    spend: () => 812, sales: () => 3654, acos: () => 22.22, roas: () => 4.5,
    ctr: () => 2.9, cvr: () => 9.2, cpc: () => 1.0, orders: () => 75 },
  { campaign_name: '展示-SD-竞品定向', type: 'SD', status: 'active',
    impressions: 52000, clicks: 780,
    spend: () => 1092, sales: () => 3058, acos: () => 35.71, roas: () => 2.8,
    ctr: () => 1.5, cvr: () => 5.8, cpc: () => 1.4, orders: () => 45 },
  { campaign_name: 'SD-再营销', type: 'SD', status: 'active',
    impressions: 18000, clicks: 1260,
    spend: () => 756, sales: () => 5141, acos: () => 14.71, roas: () => 6.8,
    ctr: () => 7.0, cvr: () => 12.0, cpc: () => 0.6, orders: () => 151 },
]

/** 展开后的 Campaign 列表（供表格直接使用） */
export const AD_CAMPAIGNS: AdCampaign[] = AD_CAMPAIGNS_RAW.map(c => ({
  ...c,
  spend: c.spend(),
  sales: c.sales(),
  acos: Math.round(c.acos() * 10) / 10,
  roas: Math.round(c.roas() * 100) / 100,
  ctr: Math.round(c.ctr() * 100) / 100,
  cvr: Math.round(c.cvr() * 10) / 10,
  cpc: Math.round(c.cpc() * 100) / 100,
  orders: c.orders(),
}))

export const AD_TOP_ISSUES = [
  { type: 'acos_high', title: 'SD 竞品定向 ACoS 偏高', description: '展示广告(SD)竞品定向 Campaign 的 ACoS 达 35.7%，建议优化定向或降低出价', priority: 'high' as const },
  { type: 'cvr_drop', title: '自动广告 CVR 有下滑趋势', description: '广泛匹配 Campaign CVR 从 9.2% 降至 6.4%，可能受新竞品冲击或 Listing 变动影响', priority: 'medium' as const },
  { type: 'negative_missing', title: '否定关键词覆盖不足', description: '搜索词报告中发现 "best coffee grinder under 30" 等大词浪费 $990/月，建议加强否词管理', priority: 'medium' as const },
]

export const AD_RECOMMENDATIONS = [
  '暂停 SD 竞品定向中 ACoS > 50% 的低效投放，转移预算到 SP 精准匹配',
  '对 SB 品牌 Campaign 进行 A/B 测试，选择 CTR 更高的创意素材',
  '本周下载搜索词报告，新增不少于 10 个精确否定词',
  '对 RoAS > 5 的核心词 Campaign 适当提高预算 15%',
  '开启商品投放(PAT)扩展流量来源，降低对单一关键词的依赖',
]

// ──── ② 搜索词数据 ────

export const SEARCH_TERMS: SearchTerm[] = [
  { term: 'portable coffee grinder manual', impr: 12500, clicks: 380, spend: 342.00, sales: 1280.00, acos: 26.7, roas: 3.7, orders: 42, cpc: 0.90, match_type: 'exact', efficiency: 'high' },
  { term: 'ceramic burr coffee grinder', impr: 8900, clicks: 290, spend: 261.00, sales: 956.00, acos: 27.3, roas: 3.7, orders: 34, cpc: 0.90, match_type: 'phrase', efficiency: 'high' },
  { term: 'hand coffee bean grinder travel', impr: 15600, clicks: 520, spend: 468.00, sales: 1872.00, acos: 25.0, roas: 4.0, orders: 62, cpc: 0.90, match_type: 'exact', efficiency: 'high' },
  { term: 'coffee mill hand crank stainless', impr: 4300, clicks: 98, spend: 88.20, sales: 198.00, acos: 44.5, roas: 2.2, orders: 8, cpc: 0.90, match_type: 'broad', efficiency: 'low' },
  { term: 'best coffee grinder under 30', impr: 22000, clicks: 1100, spend: 990.00, sales: 0, acos: 999, roas: 0, orders: 0, cpc: 0.90, match_type: 'broad', efficiency: 'waste' },
  { term: 'aeropress coffee grinder recommendation', impr: 3100, clicks: 78, spend: 70.20, sales: 0, acos: 999, roas: 0, orders: 0, cpc: 0.90, match_type: 'phrase', efficiency: 'waste' },
  { term: 'cold brew coffee grinder coarse', impr: 6700, clicks: 185, spend: 148.00, sales: 444.00, acos: 33.3, roas: 3.0, orders: 15, cpc: 0.80, match_type: 'exact', efficiency: 'medium' },
  { term: 'hario mini mill slim plus', impr: 2900, clicks: 92, spend: 82.80, sales: 265.00, acos: 31.3, roas: 3.2, orders: 10, cpc: 0.90, match_type: 'exact', efficiency: 'low' },
]

export const SEARCH_NEW_OPPORTUNITIES: SearchTerm[] = [
  { term: 'camping coffee equipment compact', impr: 2400, clicks: 68, spend: 54.60, sales: 163.80, acos: 33.3, roas: 3.0, orders: 6, cpc: 0.80, match_type: 'exact', efficiency: 'high' },
  { term: 'gift for coffee lover dad', impr: 1800, clicks: 52, spend: 41.60, sales: 145.60, acos: 28.6, roas: 3.5, orders: 5, cpc: 0.80, match_type: 'phrase', efficiency: 'high' },
]

export const SEARCH_SUGGESTIONS = [
  '立即将 2 个浪费词（$1,060.20/月）添加为精确否定',
  '对 2 个低效词降低出价 20-30%，或改为 phrase/exact 匹配',
  '对 3 个高效词提高预算 15-25%，测试扩大曝光',
  '每周一导出搜索词报告，新增否定词不少于 10 个',
]

// ──── ③ 出价建议数据 ────

export const BID_SUGGESTIONS: BidSuggestion[] = [
  { keyword: 'coffee grinder manual', match_type: 'exact', current_bid: 0.85, suggested_bid: 1.08, bid_change_pct: 27, reason: '该词转化率高且 ACoS 优于平均，提高出价可获得更多优质流量', expected_impact: '预计+27% 点击量，ACoS ↓', priority: 'high' },
  { keyword: 'ceramic burr grinder', match_type: 'phrase', current_bid: 0.72, suggested_bid: 0.91, bid_change_pct: 26, reason: '近期该词转化有明显上升趋势，建议抢占更多曝光', expected_impact: '预计+26% 点击量，ACoS ~', priority: 'high' },
  { keyword: 'portable coffee grinder', match_type: 'exact', current_bid: 1.15, suggested_bid: 0.89, bid_change_pct: -23, reason: '该词长期 ACoS 偏高，降低出价以控制成本', expected_impact: '预计-23% 点击量，ACoS ↓', priority: 'high' },
  { keyword: 'hand crank coffee mill', match_type: 'phrase', current_bid: 0.65, suggested_bid: 0.49, bid_change_pct: -25, reason: '点击量大但转化不稳定，先降低出价观察', expected_impact: '预计-25% 点击量，ACoS ↓', priority: 'medium' },
  { keyword: 'best coffee grinder 2024', match_type: 'broad', current_bid: 1.35, suggested_bid: 1.02, bid_change_pct: -24, reason: 'Broad 匹配 CPC 偏高但 ROI 不理想，建议降至合理区间', expected_impact: '预计-24% 点击量，ACoS ↓', priority: 'low' },
]

export const BID_SUMMARY = {
  total_keywords: 5,
  budget_impact: -0.22,
  expected_acos_change: -6.2,
  rationale: '基于近30天转化数据、竞争强度、季节性因素综合计算。平衡策略兼顾曝光与效率。',
}

// ──── ④ 竞品广告数据 ────

export const AD_COMPETITORS: AdCompetitor[] = [
  { competitor_name: 'BrewMaster Pro', asin: 'B08XXXXXX1', share_of_voice: 24.2, overlap_keywords: 38, avg_position: 2.1, estimated_spend: 520, top_keywords: ['coffee grinder', 'burr mill', 'manual grinder'], strengths: ['高品质陶瓷磨芯', '调节粗细度高'], weaknesses: ['价格偏高', '款式单一'] },
  { competitor_name: 'GrindElite', asin: 'B09XXXXXX2', share_of_voice: 19.8, overlap_keywords: 31, avg_position: 2.8, estimated_spend: 380, top_keywords: ['portable grinder', 'travel coffee'], strengths: ['性价比突出', '评价数量多'], weaknesses: ['质量参差', '退货率略高'] },
  { competitor_name: 'CoffeeCraft', asin: 'B07XXXXXX3', share_of_voice: 14.5, overlap_keywords: 22, avg_position: 3.4, estimated_spend: 260, top_keywords: ['ceramic grinder', 'aeropress'], strengths: ['设计精美', '包装用心'], weaknesses: ['价格虚高', '发货慢'] },
  { competitor_name: 'BaristaBasics', asin: 'B0AXXXXXX4', share_of_voice: 11.2, overlap_keywords: 18, avg_position: 3.9, estimated_spend: 190, top_keywords: ['kitchen gadget', 'coffee tool'], strengths: ['SKU丰富', '物流快'], weaknesses: ['缺乏创新', '同质化严重'] },
]

export const YOUR_SOV = 18.5
export const COMPETITOR_INSIGHTS = [
  '**BrewMaster Pro** 是最大威胁（SOV 24.2%），重点关注其 38 个重叠关键词的广告策略',
  '**GrindElite** SOV 仅 19.8%，可尝试抢夺其展示份额',
  '建议增加品牌防御广告（SBV）预算，保护品牌词展示份额',
  '关注竞品的新品上架节奏，提前布局防御性广告',
]

// ──── ⑤ 预算分配数据 ────

export const BUDGET_ALLOCATIONS: BudgetAllocation[] = [
  { campaign_name: '自动广告-广泛', current_budget: 300, suggested_budget: 285, allocation_pct: 21.2, reason: '流量入口，保持稳定', expected_roas: 3.2 },
  { campaign_name: '手动-精准-核心词', current_budget: 450, suggested_budget: 562, allocation_pct: 41.8, reason: '主力转化，建议加码', expected_roas: 5.1 },
  { campaign_name: '手动-短语-长尾词', current_budget: 250, suggested_budget: 238, allocation_pct: 17.7, reason: '低成本拓量', expected_roas: 3.8 },
  { campaign_name: '品牌-SB-品牌词', current_budget: 180, suggested_budget: 162, allocation_pct: 12.0, reason: '品牌防御，维持现状', expected_roas: 4.5 },
  { campaign_name: '展示-SD-竞品定向', current_budget: 220, suggested_budget: 264, allocation_pct: 19.6, reason: '抢量渠道，适度增加', expected_roas: 2.8 },
  { campaign_name: 'SD-再营销', current_budget: 120, suggested_budget: 216, allocation_pct: 16.1, reason: '高ROI，建议翻倍', expected_roas: 6.8 },
]

export const BUDGET_TOTAL_CURRENT = 1520
export const BUDGET_TOTAL_SUGGESTED = 1727
export const BUDGET_PROJECTED = {
  expected_roas_increase: '+22.5%',
  expected_acos_decrease: '-5.2%',
  efficiency_gain: '+16.8%',
}
export const BUDGET_RISK = '中等风险 — 建议分两周逐步调整，每周监测效果'

// ──── ⑥ 异常检测数据 ────

export const ANOMALIES: Anomaly[] = [
  { type: 'spend_spike', severity: 'high', campaign: '手动-精准-核心词', metric: '日花费', current_value: 280, expected_value: 150, deviation_pct: 86.7, detected_at: new Date(Date.now() - 86400000).toISOString().slice(0, 10), possible_cause: '某关键词出价被意外调高或竞争加剧导致 CPC 飙升', suggested_action: '立即检查出价设置，必要时暂停高价词' },
  { type: 'conversion_drop', severity: 'high', campaign: '自动广告-广泛', metric: '转化率', current_value: 3.2, expected_value: 8.5, deviation_pct: -62.4, detected_at: new Date(Date.now() - 172800000).toISOString().slice(0, 10), possible_cause: 'Listing 被差评拉低转化率，或出现恶意竞争点击', suggested_action: '检查 Listing 评价情况，排查无效点击' },
  { type: 'impression_anomaly', severity: 'medium', campaign: '品牌-SB-品牌词', metric: '展示量', current_value: 8500, expected_value: 25000, deviation_pct: -66.0, detected_at: new Date(Date.now() - 86400000).toISOString().slice(0, 10), possible_cause: '品牌词搜索量季节性下降或预算耗尽提前', suggested_action: '确认预算是否充足，考虑拓展非品牌词' },
  { type: 'ctr_drop', severity: 'medium', campaign: '展示-SD-竞品定向', metric: 'CTR', current_value: 0.12, expected_value: 0.35, deviation_pct: -65.7, detected_at: new Date(Date.now() - 43200000).toISOString().replace('T', ' ').slice(0, 16), possible_cause: '创意素材疲劳或竞品更新了更有吸引力的素材', suggested_action: '轮换 SD 广告创意，A/B 测试新素材' },
]

export const ANOMALY_SUMMARY = '发现 2 个高风险异常需立即关注，还有 2 个中等风险项'
export const ANOMALY_ALERT_COUNT = 2

// ──── ⑦ 趋势数据（近7天/近30天）────

export const AD_DAILY_TREND = {
  labels: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
  spend: [1660, 1720, 1690, 1580, 1740, 2310, 2180],
  sales: [5020, 5380, 5260, 4890, 5430, 8220, 7360],
}

export const AD_TYPE_DISTRIBUTION = {
  labels: ['SP 商品推广', 'SB 品牌推广', 'SD 展示推广'],
  spend: [6168, 812, 1848],
  sales: [14046, 3654, 8199],
}

// ──── 工具函数 ────

export function fmtMoney(v: number): string {
  return Math.round(v).toLocaleString()
}

export function fmtPct(v: number): string {
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'
}

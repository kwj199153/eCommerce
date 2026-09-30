/**
 * 广告分析 API 接口
 *
 * ★ 第 169 轮（#737）接真源时补全类型。此前本模块只有 8 个**零类型**的裸函数，
 *   而 `AdDashboardConfig.vue` 的 6 个 Tab 全部吃 `@/mock/adDashboard`
 *   （27 个硬编码常量）—— 后端 6 个结构化端点早已就绪，前端一个都没调。
 *   本仓铁律的又一现场：「后端有端点 ≠ 前端在用」。
 *   ★ 第 316 轮：Tab 6 → 4、结构化端点 6 → 4（退役「预算分配 / 异常检测」，
 *     老板「广告分析师删除异常检测、广告预算再平衡」）⇒ 上面那两个「6」
 *     是第 169 轮的历史读数，现役以本文件的函数为准。
 *
 * ★ 响应形状（实测钉住，别再猜）
 * ==============================
 * `request.ts` 的响应拦截器返回的是**整个信封**（不是 `res.data.data`）：
 *     { success: boolean, message?: string, data: T | null }
 *
 * 后端 `ad_analysis/router.py` 对四个分析端点做了 **fail-closed**：
 *   取不到数据 ⇒ `success=False` + `message=<可读原因>`
 *   + `data={data_status:'no_data', data_reason:...}`，而且**仍是 HTTP 200**。
 *   ⇒ 调用方**必须判 `success`**，不能只看「请求有没有抛错」。
 *   这正是本仓那条「兜底路径照样返回 200，于是所有真伪判据失效」的现场。
 *
 * ★ 这四个端点**全是 POST**，成功响应都带 `message`（「诊断完成 / 分析完成 / …」）。
 *   第 267 轮之前，拦截器会把非 GET 响应的 `message` 一律弹成成功提示 ⇒
 *   看板按 Tab 拉数据会连着弹绿勾。现在拦截器**不再自动弹成功提示**，无需再传开关。
 *   （下面 4 个函数仍留 `config` 口子 —— 调用方现在要传的是 `silentError`：
 *   本看板自带常驻横幅，不要让同一个失败原因再弹一条 toast。）
 *
 * 归属口径：`X-Shop-ID` 由 `request.ts` 的请求拦截器自动注入，
 * 所以这里**函数体里一律不传 store_id** —— 后端 `store_id` 走
 * `Depends(get_current_shop_id)` 服务端注入，请求体里发它也不会被采纳。
 */

import request from './request'
import type { AxiosRequestConfig } from 'axios'

// ==================== 通用信封 ====================

/**
 * 空状态载荷。
 *
 * ★ 后端取不到数据时 `data` 里放的是这两个字段，**不是**业务字段。
 *   此时**不要读数值字段**：它们不存在，读出来是 `undefined` 而不是 `0`，
 *   静默渲染成 `NaN` / 空白，比直接报错更难查。
 */
export interface AdNoDataPayload {
  data_status?: 'ok' | 'no_data'
  data_reason?: string
}

/** 四个分析端点共用的响应信封 */
export interface AdEnvelope<T> {
  success: boolean
  message?: string
  data?: (T & AdNoDataPayload) | null
}

/** 调用方判断「这份结果是真数据」的唯一判据（两条都要过） */
export function isAdDataOk<T>(res: AdEnvelope<T> | null | undefined): boolean {
  return !!res && res.success === true && res.data?.data_status !== 'no_data'
}

// ==================== ① 账户诊断（POST /ad-analysis/diagnose）====================

/** `schemas.MetricItem` —— 实测 5 条：ACoS / RoAS / CTR / CVR / CPC */
export interface AdMetricItem {
  name: string
  value: number
  /** `'%'` | `'x'` | `'$'` */
  unit: string
  /** 行业基准（后端用 SYSTEM_PROMPT 里的常量，不是实测） */
  benchmark: number
  /** `good` | `warning` | `critical` */
  status: string
  /**
   * 环比变化（%）。
   *
   * ★ 后端目前**一律填 0.0**（`_metrics_from_rows` 只算当期，没有上一期对比口径）。
   *   所以 `0` 的语义是「没有环比数据」而**不是**「与上期持平」——
   *   界面必须据此显示占位符，不能渲染成「▲ 0.0% 环比」那种看着像真数的假持平。
   */
  change_pct: number
}

/** `schemas.CampaignHealthItem` */
export interface AdCampaignItem {
  campaign_name: string
  /** `SP` | `SB` | `SD`（后端由 `report_type.upper()` 得来） */
  campaign_type: string
  status: string
  spend: number
  impressions: number
  clicks: number
  orders: number
  sales: number
  acos: number
  roas: number
  ctr: number
  cvr: number
  cpc: number
  health_score: number
}

/** `agent_ad._identify_issues` 产出的一项 */
export interface AdTopIssue {
  type?: string
  title: string
  description: string
  /** `high` | `medium` | `low` */
  priority?: string
}

/**
 * 按日期的花费/销售序列。
 *
 * ★ 三个键**都可能是 undefined**：后端 `daily_trend` 默认是空 dict，
 *   而且 `SpApiDataSource` 拿不到按天拆分时会把整段活动写在 `date_to` 当天
 *   （其 docstring 已明示「不做随机插值」）⇒ **只有 1 个点是真实情况**。
 *   前端要能渲染单点或直接显示「暂无序列」，**不得插值补点**。
 */
export interface AdDailyTrend {
  labels?: string[]
  spend?: number[]
  sales?: number[]
}

/** `schemas.DiagnosisResponse` */
export interface AdDiagnosisData {
  overall_score: number
  /** `A` | `B` | `C` | `D` | `F` —— ★ 五档，`F` 也是合法值（见 `_score_to_grade`） */
  grade: string
  summary: string
  metrics: AdMetricItem[]
  campaigns: AdCampaignItem[]
  top_issues: AdTopIssue[]
  recommendations: string[]
  daily_trend: AdDailyTrend
}

/** 广告账户健康诊断 */
export function diagnoseAdAccount(
  data: {
    time_range?: string
    campaign_ids?: string[]
    include_benchmark?: boolean
  },
  config?: AxiosRequestConfig
): Promise<AdEnvelope<AdDiagnosisData>> {
  return request.post('/ad-analysis/diagnose', data, config)
}

// ==================== ② 搜索词（POST /ad-analysis/search-terms）====================

/** `schemas.SearchTermItem` */
export interface AdSearchTermItem {
  term: string
  impressions: number
  clicks: number
  ctr: number
  spend: number
  sales: number
  acos: number
  roas: number
  orders: number
  cpc: number
  /** 后端 `_search_terms_from_rows` 目前**一律填 `broad`**（未接匹配类型维度） */
  match_type: string
  /** `high` | `medium` | `low` | `waste` */
  efficiency: string
}

/**
 * `schemas.SearchTermResponse`。
 *
 * ★ 分档用**后端给的四个数组**，不要在组件里再 `filter(efficiency === 'x')`
 *   重算一遍 —— 那是「同一判定两份实现 ⇒ 至少一份永远测不到」。
 *   实测后端的分档口径：`waste`（有花费零出单）/ `high`（ACoS<=20 且有单）
 *   / `low`（ACoS>35）/ 其余 `medium`。
 */
export interface AdSearchTermData {
  period: string
  total_terms: number
  high_performers: AdSearchTermItem[]
  low_performers: AdSearchTermItem[]
  waste_terms: AdSearchTermItem[]
  new_opportunities: AdSearchTermItem[]
  suggestions: string[]
  summary: string
}

/** 搜索词效果分析 */
export function analyzeSearchTerms(
  data: {
    time_range?: string
    campaign_type?: string
    min_spend?: number
    min_clicks?: number
    sort_by?: string
  },
  config?: AxiosRequestConfig
): Promise<AdEnvelope<AdSearchTermData>> {
  return request.post('/ad-analysis/search-terms', data, config)
}

// ==================== ③ 出价优化（POST /ad-analysis/bid-optimize）====================

/** `schemas.BidRecommendationItem` */
export interface AdBidRecommendation {
  keyword: string
  match_type: string
  current_bid: number
  suggested_bid: number
  bid_change_pct: number
  reason: string
  expected_impact: string
  priority: string
}

/** `schemas.BidStrategyResponse` */
export interface AdBidStrategyData {
  strategy_type: string
  total_keywords: number
  recommendations: AdBidRecommendation[]
  /**
   * 预算影响（美元/词）。
   *
   * ★ 后端给的是**未舍入的浮点**（实测 `-1.5999999999999979`）——
   *   渲染前必须 `toFixed(2)`，否则界面上会印出那一长串。
   */
  budget_impact: number
  expected_acos_change: number
  rationale: string
}

/** 出价优化建议 */
export function optimizeBids(
  data: {
    strategy?: string
    keywords?: string[]
    max_budget_change?: number
    target_acos?: number
  },
  config?: AxiosRequestConfig
): Promise<AdEnvelope<AdBidStrategyData>> {
  return request.post('/ad-analysis/bid-optimize', data, config)
}

// ==================== ④ 竞品广告（POST /ad-analysis/competitors）====================

/**
 * `schemas.CompetitorAdItem`。
 *
 * ★ 实测只有三个字段是真数据，其余是**数据源物理上没有的**：
 *   真：`competitor_name` / `asin` / `avg_position`（= BSR 排名，**不是**广告位）
 *       / `strengths`（评分/评论数/BuyBox/价差）
 *   假缺失（后端 `_competitor_data_from_rows` 明示「不编造」）：
 *       `overlap_keywords` = 0、`estimated_spend` = 0、`top_keywords` = []、
 *       `weaknesses` = `["数据不足"]`
 *   ⇒ 界面照实显示，**不要**把 0 渲染成「0 个重叠词」这种像结论的话。
 */
export interface AdCompetitorItem {
  competitor_name: string
  asin: string
  share_of_voice: number
  overlap_keywords: number
  /** ★ 语义是 **BSR 排名**（越小越好），不是广告平均位置 */
  avg_position: number
  estimated_spend: number
  top_keywords: string[]
  strengths: string[]
  weaknesses: string[]
}

/**
 * `schemas.CompetitorResponse`。
 *
 * ★ `competitors` 实测有 **90 条**：后端是**逐快照行**映射，同一个竞品
 *   （同 asin）会按不同 BSR 快照出现多次 ⇒ 界面必须先按 asin 去重再取 Top N，
 *   否则饼图会画出 90 个扇区、表格会拉到几百行。
 */
export interface AdCompetitorData {
  competitors: AdCompetitorItem[]
  /** 实测 0.0 —— 数据源没有展示份额维度，见上 */
  your_share_of_voice: number
  /** `leader` | `challenger` | `nicher` */
  market_position: string
  actionable_insights: string[]
}

/** 竞品广告分析 */
export function analyzeCompetitors(
  data: {
    competitor_asins?: string[]
    auto_detect?: boolean
    include_keywords?: boolean
    time_range?: string
  },
  config?: AxiosRequestConfig
): Promise<AdEnvelope<AdCompetitorData>> {
  return request.post('/ad-analysis/competitors', data, config)
}
// ==================== 对话 / 能力 ====================

/** 广告分析师对话（主入口） */
/**
 * 广告分析师对话（主入口）。
 *
 * ★ `skill` 走 **body**（后端 `AdChatRequest.skill`）—— 字段名不能改：
 *   写成 `skill_name` / `skillName` 会被 pydantic **静默丢弃**，请求照发、200 照回，
 *   只是 system prompt 里没有那段技能正文（本仓「静默失效」的典型形态）。
 */
export function chatWithAdAnalyst(data: {
  message: string
  context_id?: string
  stream?: boolean
  /** 点名的技能名（`skills.name`，不是 id）。后端据此注入该技能正文 */
  skill?: string
}): Promise<any> {
  return request.post('/ad-analysis/chat', data)
}

/** 查询广告分析 Agent 能力 */
export function getAdAnalysisCapabilities(): Promise<any> {
  return request.get('/ad-analysis/capabilities')
}

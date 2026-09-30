/**
 * 运营复盘师 API 接口
 *
 * ★ 第 167 轮（#725）新建。此前本模块的「6 个结构化端点 + 1 个对话端点」
 *   在后端**全部就绪**，而前端**一个都没调** —— 全仓 `grep '/review/` 零命中。
 *   这正是本仓那条铁律的现场：「后端有端点 ≠ 前端在用」。
 *   右栏看板与对话分支一直吃 `@/mock/reviewDashboard`（281 行硬编码假数据）。
 *
 * 归属口径（与本文件无关但必须知道）：
 *   `X-Shop-ID` 由 `api/request.ts` 的**请求拦截器**自动注入，所以这里
 *   **任何函数体里都不传 store_id** —— 后端 `schemas.ReviewRequest` /
 *   `ReviewChatRequest` 物理上没有该字段，发了也会被 pydantic 忽略。
 *   后端 router 用 **strict 守卫**解析该头：缺 / 空 / 纯空白 ⇒ **400**，
 *   不是「静默读 1 号店」。所以调用方必须把 400 当成一种**可解释的业务结论**
 *   （「请先选店铺」），而不是当网络错误重试。
 */

import request from './request'

// ==================== 类型（与后端 schemas.py 逐字对齐）====================

/** 单个指标卡：`schemas.MetricSummary` */
export interface ReviewMetric {
  label: string
  value: number
  unit?: string
  /** 环比变化（%）。后端目前**一律不填**（None）—— 见文件尾「未提供维度」说明。 */
  delta_pct?: number | null
  status?: 'normal' | 'good' | 'warning' | 'critical'
}

/** 复盘报告：`schemas.ReviewReport` */
export interface ReviewReport {
  report_type: string
  period_days: number
  /** 服务端注入的 `stores_store.id`（形态 `store_xxx`），**不是** int */
  store_id: string
  summary: string
  metrics: ReviewMetric[]
  /** 各 report_type 的结构不同，逐个用下面的具名接口收窄 */
  details: Record<string, any>
  insights: string[]
  actions: Array<{ priority?: string; content?: string }>
}

/** 统一包装：`schemas.ReviewResponse` */
export interface ReviewResponse {
  success: boolean
  data: ReviewReport
  message: string
}

/** 一次复盘对话的结果：`schemas.ReviewChatResult` */
export interface ReviewChatResult {
  reply: string
  display_type: string
  data?: Record<string, any> | null
  /** ★ 前端**必须**据此提示：否则「查不到」与「数据就是很差」在界面上不可区分 */
  degraded: boolean
  degraded_reason: string
}

/** 对话响应包装：`schemas.ReviewChatResponse` */
export interface ReviewChatResponse {
  success: boolean
  data?: ReviewChatResult | null
  message: string
}

/** 复盘周期（天）。后端 `Field(7, ge=1, le=90)` —— 超界是 422。 */
export type ReviewDays = number

// ==================== details 的具名形状（按 report_type 收窄）====================

/** 销售汇总：service._sum_sales */
export interface ReviewSalesSum {
  units: number
  revenue: number
  refunds: number
  net_revenue: number
  estimated_profit: number
}

/** 广告汇总：service._sum_ad */
export interface ReviewAdSum {
  impressions: number
  clicks: number
  spend: number
  orders: number
  sales: number
  acos: number
  roas: number
  ctr: number
}

/** 广告 campaign 评级行：service.ad_review */
export interface ReviewCampaign {
  campaign: string
  spend: number
  sales: number
  acos: number
  roas: number
  cpc: number
  ctr: number
  /** S（ACoS≤25）/ B（≤32）/ C（>32） */
  grade: 'S' | 'B' | 'C'
}

/** SKU 贡献行：service.monthly_review 的 sku_rank */
export interface ReviewSkuRank {
  asin: string
  units: number
  revenue: number
  profit: number
}

/** 商品表现行：service.product_performance */
export interface ReviewProductPerf {
  asin: string
  units: number
  revenue: number
  profit: number
  rating: number | null
  bsr_rank: number | null
  days_supply: number | null
  /** HEALTHY / WARNING / CRITICAL / STAGNANT / UNKNOWN */
  health_status: string
}

/** 库存行：service.inventory_health */
export interface ReviewInventoryItem {
  asin: string
  sku: string
  fulfillable: number
  inbound: number
  days_supply: number
  health_status: 'HEALTHY' | 'WARNING' | 'CRITICAL' | 'STAGNANT' | string
}

// ==================== 报告类型的中文名（**唯一真源**）====================

/**
 * `report_type` → 人话标题。
 *
 * ★★ 为什么必须放在这里、而不是各消费点各写一份：
 *   消费点有**两处**（对话里的 `ReviewReportCard`、资料库里的 `ReviewLibrary`），
 *   而键是后端下发的内部标识（`weekly_report` 等）。各写一份的后果是
 *   「同一个类型的报告在两个地方叫两个名字」—— 谁都不会报错。
 *   本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到。
 *
 * ★ 顺序 = 界面上的展示顺序（后端 `REVIEW_REPORT_TYPES` 的元组顺序同源）。
 *   新增类型时**只改这一处**，两处消费点自动跟上。
 */
export const REVIEW_REPORT_TITLES: Record<string, string> = {
  weekly_report: '经营概览（周报）',
  monthly_review: '月度复盘',
  ad_review: '广告归因',
  product_performance: '商品表现',
  inventory_health: '库存健康',
  profit_audit: '利润审计',
}

/** 类型未知时的兜底名。★ 刻意**不**编造一个具体类型的名字（那会把未知说成已知）。 */
export const REVIEW_REPORT_FALLBACK_TITLE = '运营复盘'

/** 某个 report_type 的中文名（未知类型回兜底，不抛错）。 */
export function reviewTitleOf(reportType: unknown): string {
  return REVIEW_REPORT_TITLES[String(reportType || '')] || REVIEW_REPORT_FALLBACK_TITLE
}

/** 筛选项（下拉）用：`{ label, value }`，顺序与 `REVIEW_REPORT_TITLES` 一致。 */
export const REVIEW_REPORT_OPTIONS = Object.entries(REVIEW_REPORT_TITLES).map(
  ([value, label]) => ({ value, label })
)

// ==================== 五大复盘能力 ====================

/** 经营概览（周报） */
export function fetchWeeklyReport(days: ReviewDays = 7): Promise<ReviewResponse> {
  return request.post('/review/weekly-report', { days })
}

/** 月度复盘（看整月传 30） */
export function fetchMonthlyReview(days: ReviewDays = 30): Promise<ReviewResponse> {
  return request.post('/review/monthly-review', { days })
}

/** 商品表现（asins 为空则分析全部） */
export function fetchProductPerformance(
  days: ReviewDays = 7,
  asins?: string[]
): Promise<ReviewResponse> {
  return request.post('/review/product-performance', { days, ...(asins?.length ? { asins } : {}) })
}

/** 库存健康（days 只用于标注周期） */
export function fetchInventoryHealth(days: ReviewDays = 7): Promise<ReviewResponse> {
  return request.post('/review/inventory-health', { days })
}

/** 利润审计 */
export function fetchProfitAudit(days: ReviewDays = 30): Promise<ReviewResponse> {
  return request.post('/review/profit-audit', { days })
}

// ==================== 对话（第 166 轮 · #726 第 2 条补齐后端）====================

/**
 * 运营复盘师对话（工具路由：LLM 自主选 6 个复盘工具之一）。
 *
 * `session_id` 非空时后端把它当 checkpointer 的 `thread_id` ⇒ 同一会话的
 * 第二轮能看见第一轮；为空则**不留记忆**（后端不拿默认值兜底）。
 */
export function chatWithReviewAnalyst(data: {
  query: string
  session_id?: string
  context?: Record<string, any>
  /**
   * 点名的技能名（`skills.name`，不是 id）—— 后端 `ReviewChatRequest.skill`，走 **body**。
   * 字段名不能改：改名会被 pydantic 静默丢弃，技能不注入且不报错。
   */
  skill?: string
}): Promise<ReviewChatResponse> {
  // ★ 不传 store_id：归属只走 X-Shop-ID（见文件头说明）。
  return request.post('/review/chat', data, { silentError: true })
}

/**
 * 5 个复盘工具 id（与前端 `toolDefinitions.ts` 里 review-analyst 的 5 张卡同族）。
 *
 * ★ 第 313 轮：退役 `ad-review`（老板「运营复盘删除广告数据」）。
 *   后端仍保留 `POST /review/ad-review` 端点与 `service.ad_review`（复盘库
 *   `ad_review` 报告类型的历史归档读口），但**前端不再有消费点** ⇒ 这里连同
 *   下面的 fetcher 映射一起去掉，避免留一个零调用的「第二条假路径」。
 */
export type ReviewToolId =
  | 'weekly-report'
  | 'monthly-review'
  | 'product-performance'
  | 'inventory-health'
  | 'profit-audit'

/**
 * 5 个结构化端点的「工具 id → 拉取函数」映射。
 *
 * ★ 与前端 `toolDefinitions.ts` 的 5 个工具 id **1:1 对应**（后端 router 也是
 *   按同一命名族设计的），所以调用方不需要在中间层做名字翻译。
 *
 * ★ 显式标注成统一的 `(days) => Promise<ReviewResponse>`，是为了让调用方
 *   能按**变量**索引它（`REVIEW_FETCHERS[id](days)`）而不触发 TS 的
 *   「联合函数签名」报错 —— `fetchProductPerformance` 多一个可选 `asins`。
 */
export const REVIEW_FETCHERS: Record<
  ReviewToolId,
  (days: number) => Promise<ReviewResponse>
> = {
  'weekly-report': fetchWeeklyReport,
  'monthly-review': fetchMonthlyReview,
  'product-performance': fetchProductPerformance,
  'inventory-health': fetchInventoryHealth,
  'profit-audit': fetchProfitAudit,
}

/**
 * 后端**不提供**的维度清单（第 167 轮实测得出的口径，见 `#725`）。
 *
 * ★ 为什么要把「不给什么」写进代码：旧右栏看板有 8 类图位（逐日销售序列、
 *   30 天逐日 GMV、周对比、7 天广告趋势、流量占比、好词/高花费词、评价变动、
 *   逐 ASIN 采购成本）在真后端**没有任何数据源** —— 它们只存在于那份 mock 里。
 *   把这份清单钉在这里，是为了让「界面上显示不出东西」有**可归因的原因**，
 *   而不是被下一个人误当成 bug 去修。
 *
 * 归宿：要么后端补数据源（独立的后端轮次），要么这些图位永久显示
 * 「后端未提供该维度」。**不要**再用编造的数字填回去。
 */
export const REVIEW_UNAVAILABLE_DIMENSIONS = [
  'daily-sales-series',
  'monthly-daily-revenue',
  'weekly-gmv-compare',
  'ad-trend-7d',
  'traffic-mix',
  'keyword-level-detail',
  'review-changes',
  'per-asin-cost',
] as const

// ==================== 复盘库（资料库 → 复盘库，第 251 轮）====================
//
// ★ 与上面 6 项能力的分工：那 6 项是「**算**」（算完不落库），复盘库是「**存 + 读**」。
//   老板点「归档到复盘库」才走 `POST /review/reports`。
//
// ★★ 归属（`X-Shop-ID`）由 `api/request.ts` 的请求拦截器自动注入 ⇒
//    这里的**任何函数都不传 store_id**。后端写口是 strict 守卫：缺 / 空 /
//    纯空白该头 ⇒ **400**，调用方必须把它当成「请先选店铺」这种**业务结论**去回话，
//    而不是当网络错误重试。
//
// ★★ 后端**不返回**统一信封（`{success, data, message}`），直接回
//    `{created, item}` / `{items, total}` / 详情对象本身 —— 与
//    `platform_rules` 等资料库端点同族。所以这里**没有** `success` 可判，
//    调用方必须**按字段判成功**（见下 `saveReviewReport` 的返回值说明）。

/** 归档/列表出参里的单条复盘（**不含** `data` 快照）。 */
export interface SavedReviewItem {
  id: string
  report_type: string
  period_days: number
  /** 业务周期末日 `YYYY-MM-DD`，**由服务端**写入（幂等键的一部分） */
  period_end: string
  /** 写入期从 `data` 派生的投影（列表不拉整份快照） */
  summary: string
  created_at: string
  updated_at: string
}

/** 详情出参：单条 + 完整快照。`data` 就是当初回传的那份 `ReviewReport`。 */
export interface SavedReviewDetail extends SavedReviewItem {
  data?: ReviewReport
}

/** 列表出参。★ `total` 是**真实条数**（不受 limit 截断）—— 显示「共 N 份」用它。 */
export interface ReviewListResult {
  items: SavedReviewItem[]
  total: number
}

/**
 * 归档出参。
 *
 * ★★ `created` 必须被消费：`true` = 新增了一条；`false` = **覆盖**了同一
 *   (类型, 周期长度, 周期末日) 的既有记录（当天重复归档）。
 *   两者对老板是**两件事**，用同一句「已归档」会让他以为库里堆了两份。
 */
export interface SaveReviewResult {
  created: boolean
  item: SavedReviewItem
}

/** 列表排序维度（后端 `REVIEW_SPEC.sort_fields` 的白名单；写错是 400）。 */
export type ReviewSortKey = 'period_end' | 'created_at' | 'period_days'

/**
 * 归档一份**老板确认过**的复盘到复盘库（幂等 upsert）。
 *
 * @param data 后端刚返回的那份 `ReviewReport` **原样回传** —— 入库的语义是
 *   「留档老板确认的那一份」，让后端重算会拿到另一批数字。
 *   ★ 快照里的 `store_id` 会被服务端**覆盖**成已校验的店铺；`period_end`
 *   取服务端当天 ⇒ 请求体在结构上影响不了归属与幂等键。
 */
export function saveReviewReport(payload: {
  report_type: string
  period_days: number
  data: ReviewReport | Record<string, any>
}): Promise<SaveReviewResult> {
  return request.post('/review/reports', payload)
}

/**
 * 列出当前店铺已归档的复盘（**不含**快照；详情走 `getSavedReport`）。
 *
 * 排序/过滤取值非法时后端回 **400**（不静默退化成默认排序）——
 * 「按创建时间排」与「你参数写错了」必须可区分。
 */
export function listSavedReports(params?: {
  order_by?: ReviewSortKey
  report_type?: string
  limit?: number
}): Promise<ReviewListResult> {
  return request.get('/review/reports', { params })
}

/**
 * 取一份已归档复盘的完整内容（**含** `data` 快照）。
 *
 * ★ 后端把「不存在」与「不属于当前店铺」压成**同一句 404** ⇒ 调用方无法
 *   （也不该）区分「这个 id 是不是别人的」。任何 404 一律按「复盘不存在」回话。
 */
export function getSavedReport(reportId: string): Promise<SavedReviewDetail> {
  return request.get(`/review/reports/${encodeURIComponent(reportId)}`)
}

/**
 * 选品分析 API 接口
 */

import request from './request'

/**
 * 蓝海品类分析
 *
 * 请求体按后端 `BlueOceanRequest` 的字段名（snake_case）组织；
 * 前端表单是 camelCase，调用方负责映射。
 */
export function analyzeBlueOcean(data: {
  marketplace?: string
  category?: string[]
  price_min?: number | null
  price_max?: number | null
  max_reviews?: number
  min_monthly_sales?: number
  min_roi?: number
  exclude_seasonal?: boolean
  exclude_brand_dominant?: boolean
  exclude_high_risk?: boolean
}) {
  return request.post('/product-research/blue-ocean', data)
}

/**
 * SKU 利润计算
 */
export function analyzeProfit(data: {
  asin?: string
  /** 后端 `ProfitAnalysisRequest.product_name` */
  product_name?: string
  /** 后端 `ProfitAnalysisRequest.selling_price` —— **必填**且 `gt=0` */
  selling_price: number
  /** 后端 `ProfitAnalysisRequest.cost_price` —— **必填**且 `ge=0` */
  cost_price: number
  weight_lbs?: number
  dimensions?: string
  category?: string
  ad_acos_pct?: number
}) {
  // ★★ 第 200 轮修复：此前这里写的是 camelCase（productName / sellingPrice /
  //    costPrice / weightLbs / adAcosPct），而后端 `ProfitAnalysisRequest` 是
  //    snake_case ⇒ body 直接透传 ⇒ Pydantic 收不到必填字段 ⇒ **稳定 422**。
  //    更刺眼的是**同一个文件**里 `chatWithProductResearcher` 与 `resumeApproval`
  //    的注释都写着「必须与后端字段逐字一致」—— 规矩写在下面两处，
  //    却漏了上面这三处（契约铁律只对后写的函数生效）。
  //    当前这三个函数在前端**零调用**，所以从未爆出来。
  return request.post('/product-research/profit', data)
}

/**
 * 痛点机会识别
 */
export function analyzePainPoints(data: {
  asin: string
  /** 后端 `PainPointRequest.analyze_positive`（原写作 `analyzePositive`） */
  analyze_positive?: boolean
}) {
  return request.post('/product-research/pain-points', data)
}

/**
 * 竞品对比分析
 */
export function compareCompetitors(data: {
  asins: string[]
  /** 后端 `CompetitorCompareRequest.include_reviews`（原写作 `includeReviews`） */
  include_reviews?: boolean
}) {
  return request.post('/product-research/competitors', data)
}

/**
 * 选品助手对话（主入口）
 */
export function chatWithProductResearcher(data: {
  message: string
  // ⚠️ 必须与后端 ChatRequest 的字段同名（snake_case `context_id`）。
  // 早前写的是 `contextId`，body 直接透传 → Pydantic 收不到 → 会话 ID 永远是 None，
  // 「按会话隔离的待补槽位 / 上一轮蓝海结果」全部退化成全局共享。
  context_id?: string
  stream?: boolean
  // ★ 同一条铁律适用于 `skill`：后端 `ChatRequest.skill`。改名 ⇒ 静默丢弃 ⇒ 技能不注入。
  /** 点名的技能名（`skills.name`，不是 id）。后端据此注入该技能正文 */
  skill?: string
  /**
   * 本次请求的「作用对象」（第 251 轮）。**三态**，后端靠它做前置门禁：
   *   · 字段**不出现** ⇒ 本客户端未参与该机制，不注入任何提示段；
   *   · `null`        ⇒ 本次**明确没有**对象（点名的技能要求对象时会被拒答）；
   *   · `{…}`         ⇒ 本次的对象。
   * ★ 与后端 `ChatRequest.context_target` 同名（改名 ⇒ 被 Pydantic 丢掉 ⇒ 静默无门禁）。
   */
  context_target?: { label: string; title: string; ref: string } | null
}): Promise<any> {
  return request.post('/product-research/chat', data)
}

/**
 * 提交人工审批决策，恢复被 `interrupt()` 挂起的会话（HITL 闭环）。
 *
 * ★ 为什么不能复用 `chatWithProductResearcher()`：
 *   被挂起的图停在 `tool_node` 上等一个 `Command(resume=...)`。
 *   用户在界面上点「批准」**不是在说话** —— 走 `/chat` 只会开一轮全新对话，
 *   那个待审批的操作仍会永久挂着（而且不报任何错）。
 *
 * ★ 字段名必须与后端 `ApprovalResumeRequest` 逐字一致（snake_case）。
 *   写成 camelCase 会被 Pydantic 丢掉 ⇒ 必填缺失 ⇒ 稳定 422。
 * ★ `context_id` 必须是**首轮**那次对话的同一个会话 ID：thread_id 由服务端
 *   按（命名空间, 用户, 会话）重算，所以**不接受**客户端传 thread_id。
 */
export function resumeApproval(data: {
  context_id: string
  decision: 'accept' | 'reject' | 'edit' | 'response'
  /** decision=reject：拒绝原因 */
  reason?: string
  /** decision=edit：改写后的工具入参（须非空） */
  args?: Record<string, any>
  /** decision=response：直接回复内容 */
  feedback?: string
}): Promise<any> {
  return request.post('/product-research/approval/resume', data)
}

/**
 * 查询 Agent 能力说明
 */
export function getProductResearchCapabilities() {
  return request.get('/product-research/capabilities')
}

/**
 * 选品市场洞察大盘云图（第 305 轮 · 蓝海挖掘大盘云图）
 *
 * GET /product-research/market-insight/treemap
 * 返回站点 × 类目 的市场洞察快照，前端 ECharts Treemap 渲染六维度大盘。
 * ★ 真源诚实：演示账号返回 mock 快照且 `degraded=true`，真实账号返回空 + degraded=false。
 */
export function getMarketInsightTreemap(): Promise<any> {
  return request.get('/product-research/market-insight/treemap')
}

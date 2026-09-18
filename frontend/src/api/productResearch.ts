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
  productName?: string
  sellingPrice: number
  costPrice: number
  weightLbs?: number
  dimensions?: string
  category?: string
  adAcosPct?: number
}) {
  return request.post('/product-research/profit', data)
}

/**
 * 痛点机会识别
 */
export function analyzePainPoints(data: {
  asin: string
  analyzePositive?: boolean
}) {
  return request.post('/product-research/pain-points', data)
}

/**
 * 竞品对比分析
 */
export function compareCompetitors(data: {
  asins: string[]
  includeReviews?: boolean
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

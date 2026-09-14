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
 * 查询 Agent 能力说明
 */
export function getProductResearchCapabilities() {
  return request.get('/product-research/capabilities')
}

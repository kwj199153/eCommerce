/**
 * 选品分析 API 接口
 */

import request from './request'

/**
 * 蓝海品类分析
 */
export function analyzeBlueOcean(data: {
  category: string
  keywords?: string[]
  minSearchVolume?: number
  maxCompetition?: number
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
  contextId?: string
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

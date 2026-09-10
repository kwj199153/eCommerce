/**
 * Listing 生成优化 API
 *
 * 与后端 /api/v1/listing/* 端点交互
 */

import request from './request'

/**
 * 生成完整 Listing
 */
export function generateListing(data: {
  product_name: string
  brand?: string
  category?: string
  features?: string[]
  price?: number
  generate_ab_variants?: boolean
}) {
  return request.post('/listing/generate', data)
}

/**
 * 优化现有 Listing
 */
export function optimizeListing(data: {
  current_listing: {
    title: string
    bullets: string[]
    description: string
    search_terms: string
  }
  optimization_focus?: string[]
}) {
  return request.post('/listing/optimize', data)
}

/**
 * 单独优化标题
 */
export function optimizeTitle(data: {
  current_title: string
  product_name?: string
  main_keyword?: string
}) {
  return request.post('/listing/optimize/title', data)
}

/**
 * 生成五点描述
 */
export function generateBullets(data: {
  product_name: string
  features?: string[]
  tone?: string
}) {
  return request.post('/listing/generate/bullets', data)
}

/**
 * 生成产品描述
 */
export function generateDescription(data: {
  product_name: string
  features?: string[]
  include_html?: boolean
  style?: string
}) {
  return request.post('/listing/generate/description', data)
}

/**
 * 生成后台关键词
 */
export function generateKeywords(params: { title: string; category?: string }) {
  return request.post('/listing/generate/keywords', null, { params })
}

/**
 * SEO 分析诊断
 */
export function analyzeSEO(data: {
  title: string
  bullets: string[]
  description: string
  search_terms: string
  main_keyword?: string
}) {
  return request.post('/listing/analyze/seo', data)
}

/**
 * A/B 测试变体
 */
export function generateABTestVariants(data: {
  base_listing: Record<string, any>
  variant_count?: number
}) {
  return request.post('/listing/ab-test', data)
}

/**
 * 自然语言对话
 */
export function chatWithListingAgent(data: {
  message: string
  context?: Record<string, any>
}) {
  return request.post('/listing/chat', data)
}

/**
 * 获取 Agent 能力说明
 */
export function getListingCapabilities() {
  return request.get('/listing/capabilities')
}

/**
 * AIGC 媒体生成模块 API
 * =====================
 * Phase 7: AI 图片生成、主图分析、A+内容、品牌故事、翻译、信息图、合规检查、视频脚本
 */

import request from '../utils/request'

// ============================================================
// 图片生成相关
// ============================================================

/**
 * AI 生成产品图片
 */
export async function generateImage(data: {
  product_name: string
  category: string
  brand?: string
  target_market?: string
  image_type?: string
  style?: string
  color_scheme?: string
  keywords?: string[]
  reference_description?: string
  dimensions?: string
}) {
  return request.post('/aigc/image/generate', data)
}

/**
 * 分析主图质量
 */
export async function analyzeMainImage(data: {
  image_url: string
  product_category?: string
}) {
  return request.post('/aigc/image/analyze', data)
}

// ============================================================
// A+ 内容相关
// ============================================================

/**
 * 生成 A+/EBC 内容
 */
export async function generateAPlusContent(data: {
  product_name: string
  brand: string
  features: string[]
  specifications?: Record<string, string>
  target_audience?: string
}) {
  return request.post('/aigc/content/a-plus', data)
}

// ============================================================
// 品牌故事相关
// ============================================================

/**
 * 生成品牌故事
 */
export async function generateBrandStory(data: {
  brand_name: string
  industry: string
  products: string[]
  values?: string[]
  founding_story?: string
}) {
  return request.post('/aigc/content/brand-story', data)
}

// ============================================================
// 翻译相关
// ============================================================

/**
 * SEO 友好翻译
 */
export async function translateContent(data: {
  content: string
  source_lang?: string
  target_lang: string
  context?: string
  keywords?: string[]
}) {
  return request.post('/aigc/content/translate', data)
}

// ============================================================
// 信息图相关
// ============================================================

/**
 * 生成营销信息图规格
 */
export async function generateInfographic(data: {
  topic: string
  data_points?: Record<string, any>[]
  infographic_type?: string
  brand_colors?: string[]
}) {
  return request.post('/aigc/design/infographic', data)
}

// ============================================================
// 合规检查相关
// ============================================================

/**
 * 检查图片合规性
 */
export async function checkCompliance(data: {
  image_url: string
  platform?: string
  category?: string
}) {
  return request.post('/aigc/compliance/check', data)
}

// ============================================================
// 视频脚本相关
// ============================================================

/**
 * 生成短视频脚本
 */
export async function generateVideoScript(data: {
  product_name: string
  product_category: string
  key_features: string[]
  target_platform?: string
  video_type?: string
  duration_target?: number
}) {
  return request.post('/aigc/video/script', data)
}

// ============================================================
// 工具列表 & 聊天
// ============================================================

/**
 * 获取 AIGC 可用工具列表
 */
export async function getAIGCTools() {
  return request.get('/aigc/tools')
}

/**
 * AIGC 助手聊天（意图识别）
 */
export async function aigcChat(message: string, context?: Record<string, any>) {
  return request.post('/aigc/chat', { message, context })
}

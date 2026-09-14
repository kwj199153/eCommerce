/**
 * AIGC 媒体生成模块 API
 * =====================
 * Phase 7: AI 图片生成、主图分析、A+内容、品牌故事、翻译、信息图、合规检查、视频脚本
 */

import request from './request'

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

/** 划词翻译的返回体（只含译文，无 SEO/文化/多版本字段） */
export interface SelectionTranslation {
  original_text: string
  translation: string
  source_lang: string
  target_lang: string
  /** LLM 不可用时为 true，此时 translation 为空字符串（后端不编造译文） */
  degraded: boolean
}

/**
 * 划词翻译（轻量，面向阅读辅助）
 *
 * 与 translateContent 的分工：那个面向内容生产（长文本、关键词、多版本），
 * 这个面向「选中一段英文想立刻看懂」。
 *
 * silent: 划词是高频操作，不能每次都弹「翻译完成」提示。
 */
export async function translateSelection(data: {
  text: string
  target_lang?: string
  context?: string
}): Promise<{ success: boolean; response: SelectionTranslation; message?: string }> {
  return request.post('/aigc/content/translate-selection', data, { silent: true })
}

/** 提示词增强的返回体（只含改写后的文本） */
export interface PromptEnhancement {
  /** 原始输入，原样回传，便于前端做比对 / 撤销 */
  draft: string
  /** 增强后的提示词 */
  enhanced: string
  /** LLM 不可用时为 true，此时 enhanced 为空字符串（后端不编造提示词） */
  degraded: boolean
}

/**
 * 提示词增强（输入框辅助）
 *
 * 把对话框里的一句口语化需求改写成更可执行的提示词（补齐任务目标 / 约束条件 / 期望的输出形式）。
 * 与 translateSelection 并列，但**改的不是语言，是需求的完备度**。
 *
 * silent: 这是输入框的即时操作，成功与否都靠输入框内容体现，不要弹提示打断输入。
 */
export async function enhancePrompt(data: {
  draft: string
  context?: string
}): Promise<{ success: boolean; response: PromptEnhancement; message?: string }> {
  return request.post('/aigc/prompt/enhance', data, { silent: true })
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


/** 单张生成素材 */
export interface GeneratedAsset {
  id: string
  type: string
  type_label: string
  desc: string
  prompt: string
  url: string
  created_at: string
}

/** 批量出图结果 */
export interface AssetGenerationData {
  mode: string
  model?: string
  assets: GeneratedAsset[]
  failed: { type: string; type_label: string; error: string }[]
  degraded: boolean
  degraded_reason?: string | null
  source_image_used: boolean
  notice?: string
}

/**
 * 静态素材批量出图（面板驱动）。
 *
 * 与 `/aigc/image/generate` 的区别：那条是**对话驱动**、Agent 可先追问缺参；
 * 这条是**面板驱动** —— 表单里点「开始生成素材」就该出图，不做缺参拦截。
 *
 * ⚠️ 出图是**长任务**：单张 15-25s、后端并发上限 3、最多 8 张 → 必须单独放宽超时，
 * 否则会被 axios 实例默认的 30s 掐断（表现成「莫名超时」而看不出原因）。
 */
export async function generateAssets(data: {
  product_name: string
  image_types: string[]
  category?: string
  extra_description?: string
  count_per_type?: number
  size?: string
  /**
   * 产品原图（图生图底图）：公网 URL 或 **base64 data URI**。
   * 万相 base_image_url 原生支持 base64 直传 —— **不需要图床**。
   * 留空则后端退回文生图。
   */
  source_image?: string
}): Promise<{ success: boolean; response: AssetGenerationData; message: string }> {
  return request.post('/aigc/asset/generate', data, { timeout: 300000, silent: true })
}

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
 * 静态素材批量出图 —— **异步任务版（前端唯一路径）**。
 *
 * ⚠️ 为什么不再用同步端点 `/aigc/asset/generate`：
 *   那条会整段阻塞出图过程。实测参数（后端代码常量）：单张 15-25s、内部并发 2
 *   （3 并发会被服务端 429）、单次最多 8 张、单张超时 180s
 *   ⇒ 最坏 8/2 × 180s = **720s**，而 axios 侧为了它不得不把超时放宽到 **300s**。
 *   720 > 300 ⇒ 极端情况下用户看到「请求超时」，但后端仍在出图、
 *   DashScope 已按张计费（≈¥0.14/张）—— **钱花了，结果丢了**。
 *
 * 现在改为：提交 → 立即拿到 job_id → 轮询状态。
 *   - 再也不会有「HTTP 超时但钱已花」的情形：任务状态在服务端持久化，
 *     **前端断线、刷新、关标签页都不会丢**（可在任务列表里找回）。
 *   - 连点两次不会重复出图：同入参的进行中任务由后端去重（重复提交 = 重复花钱）。
 *   - 同步端点仍保留在服务端（`generateAssets` 已从前端移除），
 *     供脚本 / 调试 / 无 worker 环境使用；**执行内核是同一个**，出图口径不会分叉。
 */
export type AigcJobStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface AigcJob {
  id: string
  kind: string
  kind_label: string
  status: AigcJobStatus
  /** true = 已结束（succeeded/failed），不必再轮询 */
  is_terminal: boolean
  assets_count: number
  error: string
  /** UTC 且带 Z 后缀 —— 用 new Date(s).toLocaleString('zh-CN') 折算本地时区 */
  created_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_ms: number | null
  result?: AssetGenerationData | null
}

interface AigcJobSubmitResponse {
  success: boolean
  job: AigcJob
  /** true = 命中去重，返回的是已有的进行中任务（未重复提交、不重复计费） */
  deduplicated: boolean
  message: string
}

/** 提交一个 AIGC 长任务，立即返回（不阻塞出图过程） */
export async function submitAigcJob(
  kind: 'asset_generate' | 'image_generate',
  params: Record<string, unknown>,
): Promise<AigcJobSubmitResponse> {
  return request.post('/aigc/jobs', { kind, params }, { silent: true })
}

/** 查询任务状态 */
export async function getAigcJob(jobId: string): Promise<{ job: AigcJob }> {
  return request.get(`/aigc/jobs/${jobId}`, { silent: true, silentError: true })
}

/** 我的任务列表（前端刷新后能找回刚提交的任务） */
export async function listAigcJobs(limit = 20): Promise<{ jobs: AigcJob[]; total: number }> {
  return request.get(`/aigc/jobs?limit=${limit}`, { silent: true, silentError: true })
}

export interface AigcJobWaitResult {
  job: AigcJob
  /** true = 已等到终态；false = 等待超时，任务仍在后台继续执行（不是失败） */
  settled: boolean
  /** 因 429（限流）而延长等待的次数 —— 排查「为什么等久了」用 */
  throttled: number
}

/**
 * 提交并轮询到终态。
 *
 * ★ 三条与后端限流/健壮性直接相关的设计（都是实测踩出来的）：
 *  1. **轮询间隔 2.5s**：后端限流是 60 次/分钟/IP。0.5s 轮询 = 120 次/分钟，
 *     会直接把状态查询打成 429（实测）。
 *  2. **429 必须当成「继续等」而不是失败**：429 只说明查得太快，
 *     任务本身没出问题。这里对被限流做指数退避（2.5s → 5s → 10s → 上限 15s），
 *     并计入 `throttled`。
 *  3. **等到超时不等于失败**：任务在服务端继续跑，状态落库。
 *     返回 `settled: false` 让调用方给出「仍在后台生成」的提示，
 *     而不是谎报失败（这正是同步端点最糟的地方）。
 */
export async function submitAndWaitAigcJob(
  kind: 'asset_generate' | 'image_generate',
  params: Record<string, unknown>,
  options: { maxWaitMs?: number; pollIntervalMs?: number } = {},
): Promise<AigcJobWaitResult> {
  const maxWaitMs = options.maxWaitMs ?? 240_000
  const baseInterval = options.pollIntervalMs ?? 2_500

  const submitted = await submitAigcJob(kind, params)
  const jobId = submitted.job.id

  const deadline = Date.now() + maxWaitMs
  let interval = baseInterval
  let throttled = 0
  let last: AigcJob = submitted.job

  // 已经是终态（例如命中去重的任务刚好已完成）→ 直接返回
  if (last.is_terminal) return { job: last, settled: true, throttled }

  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, interval))
    try {
      const res = await getAigcJob(jobId)
      last = res.job
      interval = baseInterval // 成功后恢复正常节奏
      if (last.is_terminal) return { job: last, settled: true, throttled }
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 429) {
        throttled += 1
        interval = Math.min(interval * 2, 15_000)
        continue
      }
      // 其他错误（网络抖动 / 404 等）不立即判失败：记一次并继续，
      // 由外层超时兜底 —— 任务可能已经成功，不该因为一次查询失败就报错。
      interval = Math.min(interval * 2, 15_000)
    }
  }

  return { job: last, settled: false, throttled }
}

/**
 * 静态素材批量出图（面板驱动，异步）。
 *
 * 与 `/aigc/image/generate` 的区别：那条是**对话驱动**、Agent 可先追问缺参；
 * 这条是**面板驱动** —— 表单里点「开始生成素材」就该出图，不做缺参拦截。
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
}): Promise<AigcJobWaitResult> {
  return submitAndWaitAigcJob('asset_generate', { ...data }, { maxWaitMs: 240_000 })
}

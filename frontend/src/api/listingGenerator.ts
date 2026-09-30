/**
 * Listing 生成优化 API —— 与后端 `/api/v1/listing/*` 对齐
 *
 * ## 契约来源（全部实测，不是照 schema 猜的）
 *
 * 本文件的所有字段名与可选性，来自第 169 轮对 6 个端点的 **TestClient 真打**：
 * `POST /generate`、`/generate/bullets`、`/generate/description`、`/generate/keywords`、
 * `/optimize/title`、`/analyze/seo`。证据落在
 * `.workbuddy/probes/o169_t738_shape.json`。
 *
 * ## 三条必须先知道的语义（写错就会编数据或误报故障）
 *
 * 1. **信封是 `{success, message, data}`**（后端 `schemas.ApiResponse`）。
 *    但注意：本模块**不像 `ad_analysis` 那样 fail-closed** —— 它出错时
 *    **直接 `HTTPException(500)`**（`detail` 是给用户看的中文原因），
 *    不存在 `success:false` 的 200 响应。所以调用方要按 HTTP 状态判失败。
 *
 * 2. **`/generate/keywords` 回的是 Search Terms（后台搜索词），不是关键词挖掘**：
 *    只有扁平的 `terms: string[]` + `total_bytes`，**没有** search_volume /
 *    competition / relevance。那三个指标只有 `product_research`（关键词挖掘）才有。
 *    ⇒ 不要把 Search Terms 渲染成「带搜索量的关键词表」。
 *
 * 3. **`/generate/keywords` 的参数走 query 不是 body**：后端签名是裸标量
 *    `title: str, category: str = ""`（FastAPI 对非 pydantic 的裸标量形参按 query 解析）。
 *    发 body 会稳定 422。
 *
 * ## 一个实测到的后端故障（别在前端"兜底"掩盖它）
 *
 * `POST /analyze/seo` 在本机实测 **500**，`detail` =
 * 「SEO 分析未产出结构化结果（Agent 路由未返回 seo_score）」。
 * 这是后端 Agent 路由的问题，前端不要用假分数兜底。Listing 面板的 4 个模块
 * 不走这个端点（SEO 走对话编排器那条链）。
 */

import type { AxiosRequestConfig } from 'axios'
import http from './request'

// ====== 信封 ======

export interface ListingEnvelope<T> {
  success: boolean
  message?: string
  data: T
}

// ====== 载荷类型（字段名与后端逐字对齐）======

/** 后端 `agent_listing.ListingTitle` */
export interface ListingTitlePayload {
  /** 完整标题 */
  title: string
  character_count: number
  word_count: number
  main_keyword: string
  /** SEO 评分（0-100） */
  seo_score: number
  optimization_notes: string[]
}

/**
 * 后端 `agent_listing.BulletPoint`
 * 实测 item keys = `['bullet_id','character_count','content','emotion_trigger','title']`
 */
export interface ListingBulletPayload {
  bullet_id?: number
  /** 大写卖点标题 */
  title: string
  content: string
  character_count?: number
  emotion_trigger?: string | null
}

export interface ListingBulletsPayload {
  bullets: ListingBulletPayload[]
  total_characters: number
  /** `/generate` 里实测出现过 33.3（LLM 增强路径）与 `/generate/bullets` 的 100.0 */
  coverage_score?: number
  /** 仅 `/generate/bullets` 回 */
  product_name?: string
  /** 仅 `/generate/bullets` 回 */
  tips?: string[]
}

/**
 * ★ 实测 item 只有两个键：`type` / `content`。
 *
 * `type` 是**语义**枚举（实测 `intro` / `features` / `scenarios`），
 * **不是** A+ 的版式类型（text / image-text / highlights / comparison）。
 * 两者同名不同义，映射在 `stores/listingDraft.ts::normalizeModule` 里做。
 */
export interface ListingDescriptionSection {
  type: string
  content: string
}

/** 后端 `agent_listing.ProductDescription` */
export interface ListingDescriptionPayload {
  plain_text: string
  html_content?: string | null
  word_count: number
  sections: ListingDescriptionSection[]
  call_to_action?: string | null
  /** 仅 `/generate/description` 回 */
  product_name?: string
}

/**
 * 后端 `agent_listing.SearchTerms` —— **后台搜索词**。
 * 实测 `terms` 是 17 个扁平字符串、`total_bytes` = 242（硬上限 250 字节）。
 * ★ 没有 search_volume / competition / relevance。
 */
export interface ListingSearchTermsPayload {
  terms: string[]
  /** 总字节数（需 ≤ 250） */
  total_bytes: number
  is_valid: boolean
  /** 仅 `/generate/keywords` 回 */
  usage_tips?: string[]
  /** 仅 `/generate` 回 */
  optimization_notes?: string[]
}

/** 后端 `agent_listing.SEOScore` */
export interface ListingSeoScorePayload {
  overall_score: number
  title_score: number
  bullet_score: number
  description_score: number
  keywords_score: number
  /** 实测 19 个布尔检查项（key 形如 `title_title_length_ok`） */
  checklist?: Record<string, boolean>
  improvement_areas?: string[]
}

/** 后端 `schemas.CompleteListingResponse`（`POST /generate` 的 `data`） */
export interface CompleteListingPayload {
  product_name: string
  generated_at: string
  platform: string
  title: ListingTitlePayload
  bullet_points: ListingBulletsPayload
  description: ListingDescriptionPayload
  search_terms: ListingSearchTermsPayload
  seo_score: ListingSeoScorePayload
  ab_variants?: unknown[] | null
}

/** 后端 `schemas.TitleOptimizationResponse` */
export interface OptimizedTitlePayload {
  original_title: string
  optimized_title: string
  character_count: number
  seo_score: number
  improvements: string[]
  optimization_notes: string[]
}

/** 后端 `schemas.SEOAnalysisResponse` */
export interface ListingSeoAnalysisPayload {
  overall_score: number
  title_score: number
  bullet_score: number
  description_score: number
  keywords_score: number
  checklist: Record<string, boolean>
  improvement_areas: string[]
  /** A/B/C/D/F */
  grade: string
}

// ====== 请求入参 ======

export interface GenerateListingParams {
  product_name: string
  brand?: string
  category?: string
  features?: string[]
  price?: number
  target_audience?: string
  unique_selling_point?: string
  competitor_asins?: string[]
  generate_ab_variants?: boolean
  language?: string
}

export interface BulletPointsParams {
  product_name: string
  features?: string[]
  /** professional / friendly / luxury */
  tone?: string
  /** 自定义生成指令，存在则完全替换默认 prompt */
  custom_prompt?: string
}

export interface DescriptionParams {
  product_name: string
  features?: string[]
  include_html?: boolean
  /** storytelling / technical / benefit-driven */
  style?: string
  /** 自定义生成指令，存在则完全替换默认 prompt */
  custom_prompt?: string
}

export interface OptimizeTitleParams {
  /** 必填，后端 `min_length=5` */
  current_title: string
  product_name?: string
  main_keyword?: string
  /** 自定义生成指令，存在则完全替换默认 prompt */
  custom_prompt?: string
}

// ====== 端点 ======

/**
 * 生成**完整** Listing（标题 + 五点 + 描述 + 搜索词 + SEO 评分）。
 *
 * 一次往返拿到全部四个模块 —— 「一键生成全部」用这个，不要串四个请求。
 * 注意它比较重（后端内部会跑标题/五点/描述的 LLM 增强），实测数秒级。
 */
export function generateListing(
  data: GenerateListingParams,
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<CompleteListingPayload>> {
  return http.post('/listing/generate', data, config)
}

/**
 * 单独生成五点描述。
 * 实测 `bullets[*]` 带 `title`（大写卖点词）+ `content`，正好是
 * `listingDraft.setBullets` 需要的两字段。
 */
export function generateBullets(
  data: BulletPointsParams,
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<ListingBulletsPayload>> {
  return http.post('/listing/generate/bullets', data, config)
}

/**
 * 单独生成产品长描述（A+ Content 风格）。
 * `sections` 是**语义分段**，映射到 A+ 版式由 store 负责（见类型注释）。
 */
export function generateDescription(
  data: DescriptionParams,
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<ListingDescriptionPayload>> {
  return http.post('/listing/generate/description', data, config)
}

/**
 * 生成后台搜索词（Search Terms）。
 *
 * ★ **参数走 body，不是 query** —— 第 273 轮后端签名从裸标量形参
 *   `title: str, category: str = ""` 改为 Pydantic `KeywordRequest`，
 *   因此这里发 body（含可选 `custom_prompt`），不再是 `params` + body null。
 * ★ 返回的是**扁平词表**，没有搜索量/竞争度/相关度（见文件头第 2 条）。
 */
export function generateKeywords(
  data: { title: string; category?: string; custom_prompt?: string },
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<ListingSearchTermsPayload>> {
  return http.post('/listing/generate/keywords', data, config)
}

/**
 * 优化/重写标题。
 *
 * ★ 语义是「给我一个更好的标题」：后端实现里 `product_name` 优先、
 *   缺失时回退到 `current_title[:50]`。所以第一次生成标题时
 *   传 `current_title` = 现有标题（没有就传产品名）+ `product_name`。
 */
export function optimizeTitle(
  data: OptimizeTitleParams,
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<OptimizedTitlePayload>> {
  return http.post('/listing/optimize/title', data, config)
}

/**
 * SEO 诊断。
 * ⚠️ 本机实测该端点 **500**（后端 Agent 路由未返回 `seo_score`），
 *    不要在调用方用假分数兜底 —— 让它以「分析不可用」如实呈现。
 */
export function analyzeSEO(
  data: {
    title: string
    bullets: string[]
    description: string
    search_terms?: string
    main_keyword?: string
    /** 后端默认 "amazon" */
    platform?: string
  },
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<ListingSeoAnalysisPayload>> {
  return http.post('/listing/analyze/seo', data, config)
}

/** 优化现有 Listing（逐项建议，按优先级排序） */
export function optimizeListing(
  data: {
    current_listing: {
      title: string
      bullets: string[]
      description: string
      search_terms: string
    }
    optimization_focus?: string[]
  },
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<{ suggestions: unknown[]; summary: string; high_priority_count: number }>> {
  return http.post('/listing/optimize', data, config)
}

/** A/B 测试变体 */
export function generateABTestVariants(
  data: { base_listing: Record<string, unknown>; variant_count?: number },
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<{ variants: unknown[]; summary: string; testing_recommendations: string[] }>> {
  return http.post('/listing/ab-test', data, config)
}

/** 自然语言对话（非流式） */
/**
 * Listing 优化师对话。
 *
 * ★ `skill` 走 **body**（后端 `ChatRequest.skill`），字段名不能改 —— 写成
 *   `skill_name` 会被 pydantic 静默丢弃（请求照发、200 照回，只是技能没注入）。
 */
export function chatWithListingAgent(
  data: {
    message: string
    context?: Record<string, unknown>
    skill?: string
    /**
     * 本次请求的「作用对象」（第 257 轮）。**三态**，后端靠它把"这次给哪个品做"
     * 变成结构化事实，而不是让模型从用户消息里猜：
     *   · 字段**不出现** ⇒ 本客户端未参与该机制，不注入任何提示段；
     *   · `null`        ⇒ 本次**明确没有**对象（本 Agent 只注入、不拒答）；
     *   · `{…}`         ⇒ 本次的工作商品。
     * ★ 必须与后端 `ListingChatRequest.context_target` 同名（改名 ⇒ 被 Pydantic
     *   丢掉 ⇒ 静默无对象，而请求本身照样 200 —— 最难归因的一类）。
     */
    context_target?: { label: string; title: string; ref: string } | null
  },
  config?: AxiosRequestConfig
): Promise<ListingEnvelope<{ response: string; data?: unknown; display_type?: string }>> {
  return http.post('/listing/chat', data, config)
}

/** Agent 能力说明（无信封，直接返回对象） */
export function getListingCapabilities(config?: AxiosRequestConfig): Promise<Record<string, unknown>> {
  // ★ axios 实例的 `get<T,R,D,P>(url, config?)` 只有 **2 个**参数；
  //   `get(url, params, config)` 是 `request.ts` 里另一个独立辅助函数的签名（默认导出的是实例）。
  return http.get('/listing/capabilities', config)
}


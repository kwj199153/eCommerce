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
  //    更刺眼的是 `chatWithProductResearcher` 与（当时同在本文件、现已迁到
  //    `api/agentApproval.ts` 的）`resumeApproval`
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
 * 提交人工审批决策 → **已迁走**（第 400 轮 P0-2）。
 *
 * 原来这里有个 `resumeApproval()` 打在 `/product-research/approval/resume` 上，
 * 于是「能点批准」被绑死在选品分析师身上：客服 / trade 域的写工具同样会被
 * `interrupt()` 挂起，却没有任何端点能放行。
 *
 * 现在是 `api/agentApproval.ts::resumeAgentApproval(agent, payload)`，走通用端点
 * `POST /agents/{agent}/approval/resume`。**不要在这里加回来** ——
 * 一份「谁都能点的批准」只要出现第二个入口，两边迟早会漂移，
 * 而漂移的表现是「点了批准 404」，看起来像这个功能没做。
 * （`scripts/check-hitl-approval.cjs` 的 A1 会扫全 src 拦这个端点。）
 */

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

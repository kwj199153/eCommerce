/**
 * 差评处置 API（第 287 轮 P0-2 新建）
 *
 * ★ 为什么需要这个文件：`review_dispositions` 这张表此前是**三无表**
 *   —— 全库 0 行（没有写入路径）、后端无端点（`modules/trade` 连 router 都没有）、
 *   前端零消费（`grep disposition` 在 `frontend/src` 命中 0 次）。
 *   于是「处置」只活在 Agent 的一句「建议不发券」里：有状态机、有双语回复、
 *   有补偿金额的模型，却没有任何一条数据能证明它被用过。
 *
 * 归属口径：`X-Shop-ID` 由 `api/request.ts` 的**请求拦截器**注入，
 *   本文件任何函数体里都不传 store_id（后端请求体物理上没有该字段）。
 *
 * ★★ 三步里**只有第一步属于 Agent**：
 *     propose（生成草稿，Agent 可调）→ approve（人批准）→ issue（人核准，生券码）
 *   前端把后两步做成按钮，是因为发券/退款不可逆 —— 本仓既有口径就是
 *   「只把规则摆出来让人判断」。反过来若让 Agent 自己发券，HITL 就被架空了。
 */

import request from './request'

/**
 * 处置状态（与后端 `service.DISPOSITION_STATUSES` 逐字对齐）
 *
 * ★★ `issued` ≠ `executed`（第 304 轮改口径，别再合并这两个词）
 * ------------------------------------------------------------
 * 取证：`issue_disposition` **零出站调用** —— `modules/trade` 里没有任何 HTTP
 * 客户端，SP-API / Shopee 适配层清一色是只读的 `fetch_*`。所以
 *   · `issued`  ＝ **本地已核准**：券码已生成、给买家的回复可以对外，
 *                 **平台侧还没动**；
 *   · `executed` ＝ 平台上真的执行完了（人工做完回来登记回执）。
 * 把这两个词合成一个 ⇒ 界面写「已发放 · 退回部分或全部货款」时，
 * 库里**没有任何字段**能支撑「钱退回去了」—— 字面为真、暗示为假。
 */
export type DispositionStatus =
  | 'proposed' | 'approved' | 'issued' | 'executed' | 'rejected'

/** 状态中文名 —— 唯一真源，页面与筛选器共用 */
export const DISPOSITION_STATUS_LABELS: Record<DispositionStatus, string> = {
  proposed: '待批准',
  approved: '已批准',
  /** ★ 不许写回「已发放」：那句话暗示平台上已经执行，而本系统根本没调接口 */
  issued: '已核准 · 待平台执行',
  executed: '平台已执行',
  rejected: '已驳回',
}

/**
 * 状态色（与 `theme/bands.ts` 的语义色同一套取值）
 *
 * ★ `issued` 用 `gold` 而不是 `green`：待平台执行还是「在路上」，
 *   绿色会被读成「已经完事了」—— 那正是本轮要治的病。
 */
export const DISPOSITION_STATUS_COLORS: Record<DispositionStatus, string> = {
  proposed: 'orange',
  approved: 'blue',
  issued: 'gold',
  executed: 'green',
  rejected: 'red',
}

/** 所属评价摘要（后端 `_review_to_dict` 的子集，列表页要显示「这是哪条差评」） */
export interface DispositionReview {
  id: string
  /**
   * ★ `asin` 必须在这里：台账列表此前只渲染 `sku`（`SKU-KC-002`），
   *   而老板在差评列表里看到的是 `B0CXXXX009` ⇒ 两边看着像两份数据。
   *   后端 `_review_to_dict` 本来就下发它，只是前端 interface 没接。
   */
  asin: string
  sku: string
  rating: number
  title: string
  body: string
  review_at: string
  buyer_name: string
}

/** 一条处置（后端 `service._disposition_to_dict`） */
export interface Disposition {
  id: string
  review_id: string
  status: DispositionStatus
  channels: string[]
  compensation: Record<string, any>
  coupon_code: string
  ticket_id: string | null
  issued_at: string
  /** ★ 平台执行回执（第 304 轮）：`executed_at` 为空 ⇒ 平台上**还没**执行 */
  execution_mode: string
  platform_ref: string
  executed_by: string
  executed_at: string
  receipt_note: string
  reply_draft_en: string
  reply_draft_zh: string
  approved_by: string
  notes: string
  created_at: string
  updated_at: string
  review: DispositionReview | null
}

/** 草稿建议（**不落库**；`GET /trade/dispositions/{review_id}/draft`） */
export interface DispositionDraft {
  ready: boolean
  review_id?: string
  reason?: string
  primary_cause?: string
  primary_cause_label?: string
  channels?: string[]
  compensation?: Record<string, any>
  rule_code?: string
  rule_name?: string
  reply_draft_zh?: string
  reply_draft_en?: string
  over_budget?: boolean
  is_mock_data?: boolean
}

/** `POST /trade/dispositions` 的请求体（**没有** approver / store_id 字段） */
export interface ProposeDispositionParam {
  review_id: string
  channels?: string[]
  compensation?: Record<string, any>
  coupon_code?: string
  reply_draft_en?: string
  reply_draft_zh?: string
  ticket_id?: string
  notes?: string
}

/**
 * 列出本店铺的处置
 *
 * ★ `total` 是**真实条数**（不受 limit 截断）—— 列表头的「共 N 条」要它；
 *   用 `items.length` 会给出被截断的数。
 */
export async function listDispositions(params?: {
  status?: DispositionStatus
  limit?: number
}): Promise<{ items: Disposition[]; total: number }> {
  return request.get('/trade/dispositions', { params })
}

/** 处置详情（含完整双语草稿）。没有 ⇒ 后端 404。 */
export async function getDisposition(reviewId: string): Promise<Disposition> {
  return request.get(`/trade/dispositions/${encodeURIComponent(reviewId)}`)
}

/** 草稿建议（不落库） */
export async function draftDisposition(reviewId: string): Promise<DispositionDraft> {
  return request.get(`/trade/dispositions/${encodeURIComponent(reviewId)}/draft`)
}

/** 生成 / 更新待批准处置 */
export async function proposeDisposition(
  data: ProposeDispositionParam,
): Promise<Disposition> {
  return request.post('/trade/dispositions', data)
}

/**
 * 批量补生成里「给不出方案」的单条记录。
 *
 * ★ `reason_code` 是**后端**给的成因码。前端**不许**再从 `reason` 文案里正则猜形状：
 *   第 304 轮实测，同一句「没有针对「X」的启用规则」底下藏着两种**动作相反**的情况 ——
 *   真没规则（该去配）vs 有规则但这条不满足条件（配了也命中不了）。
 *   文案猜不出来，只有码能。
 */
export interface BackfillFailure {
  review_id: string
  reason: string
  /** no_rule / rule_conditions_unmet / no_attribution / over_budget；缺省 = 后端未分类 */
  reason_code?: string
  primary_cause?: string
  primary_cause_label?: string
  rule_codes?: string[]
}

/** 批量给「有归因但没处置」的差评补生成草稿（幂等） */
export async function backfillDispositions(
  limit = 50,
): Promise<{
  scanned: number
  created: number
  skipped: number
  failed: BackfillFailure[]
}> {
  return request.post('/trade/dispositions/backfill', null, { params: { limit } })
}

/** 批准（人） */
export async function approveDisposition(reviewId: string): Promise<Disposition> {
  return request.post(
    `/trade/dispositions/${encodeURIComponent(reviewId)}/approve`,
  )
}

/** 驳回（人） */
export async function rejectDisposition(
  reviewId: string,
  notes = '',
): Promise<Disposition> {
  return request.post(`/trade/dispositions/${encodeURIComponent(reviewId)}/reject`, {
    notes,
  })
}

// ==================================================================
// 产品 ↔ 差评 软关联（第 289 轮）
//
// ★ 为什么这套 API 要单独放着讲：差评的 `asin` / `sku` **没有外键**指向
//   产品库（平台侧标识符，不能因为本地少一行就让差评插不进来）。没有外键兜
//   ⇒ join 可能一行都匹配不上，而「匹配不上」有两种完全不同的语义：
//      · 这个产品确实没有差评       —— 正常结论
//      · 差评和产品**没能对上**     —— 数据缺口
//   所以 `empty_state` 必须由界面分别播报，不能统一显示成「暂无差评」
//   —— 那等于把缺口伪装成「产品没问题」。
// ==================================================================

/** 产品的关联差评（后端 `_review_to_dict` + 关联元数据） */
export interface ProductReview {
  id: string
  sku: string
  asin: string
  product_title: string
  rating: number
  title: string
  body: string
  review_at: string
  buyer_name: string
  status: string
  source: string
  /** 这条差评是靠什么对上产品的 —— 界面要显示「命中 ASIN / SKU 码」 */
  match_kind: 'asin' | 'sku_code' | 'unknown' | null
  matched_sku_id: string | null
}

/**
 * 空态种类 —— **界面必须逐种给不同文案**
 * - `no_reviews`：关联得上，确实没有符合条件的评价（正常结论，绿色）
 * - `no_sku` / `no_asin_binding`：**数据缺口**（SKU 没登记 ASIN ⇒ 差评再存在也对不上来）
 * - `not_found`：SPU 不存在 / 不属于本店
 */
export type ProductReviewsEmptyState =
  | 'not_found' | 'no_sku' | 'no_asin_binding' | 'no_reviews' | null

export interface ProductReviewsResult {
  found: boolean
  spu_id: string
  spu_title?: string
  reviews: ProductReview[]
  /** 真实条数（不受 limit 截断） */
  total: number
  asin_count: number
  sku_count: number
  empty_state: ProductReviewsEmptyState
}

export interface OrphanReviewsResult {
  items: ProductReview[]
  total: number
  empty_state: 'no_orphans' | null
}

/**
 * 本店近期的中差评 —— 「差评工作台」的主列表。
 *
 * ★ 这个端点此前是缺的：`service.list_recent_negative_reviews` 只有 Agent 工具
 *   一个调用点，没有 HTTP 出口 ⇒ 前端要拿差评清单只能退而用「处置列表」，
 *   而那只看得见**已经处置过**的差评（历史差评从未被处置过 ⇒ 永远是空列表）。
 *   差评以差评为主语，处置以处置为主语，两者不能互相顶替。
 */
export async function listShopReviews(params?: {
  max_rating?: number
  days?: number
  limit?: number
  offset?: number
}): Promise<{ items: ProductReview[]; total: number; limit: number; offset: number }> {
  return request.get('/trade/reviews', { params })
}

/**
 * 某个 SPU 名下的差评 —— 产品详情「差评 tab」的数据源。
 *
 * ★ SPU 只是**聚合壳**：SPU 无 ASIN、不可售，真正的键在它名下 SKU 的
 *   ASIN 上（`spus.id → skus.spu_id → skus.asin`），且在 ASIN 缺失时退回 SKU 码。
 * ★ 同一个 ASIN 可能挂在多个 SKU 上 ⇒ 结果**已去重**，不会重复计数。
 */
export async function listReviewsBySpu(
  spuId: string,
  params?: { max_rating?: number; limit?: number; offset?: number },
): Promise<ProductReviewsResult> {
  return request.get(`/trade/reviews/by-spu/${encodeURIComponent(spuId)}`, { params })
}

/**
 * 关联不上产品的差评（孤儿兜底列表）。
 *
 * ★ 为什么要这一张表：软关联没有外键兜 ⇒ 关联不上的差评**不会出现在任何
 *   产品的差评 tab 里**，它们只是静默消失。没有它，「这个产品 0 条差评」
 *   这句话永远无法被证伪。
 */
export async function listOrphanReviews(params?: {
  max_rating?: number
  limit?: number
  offset?: number
}): Promise<OrphanReviewsResult> {
  return request.get('/trade/reviews/orphans', { params })
}

/**
 * 核准（人）—— 不可逆，只有这一步生成券码。
 *
 * ★★ 这一步**不调用平台接口**：它只是本地核准（生成券码 + 写进回复草稿）。
 *   平台侧的动作要由人做完之后走 `recordExecutionReceipt` 登记。
 */
export async function issueDisposition(reviewId: string): Promise<Disposition> {
  return request.post(`/trade/dispositions/${encodeURIComponent(reviewId)}/issue`)
}

/**
 * 登记平台执行回执（人）—— `issued` → `executed`，**终态**。
 *
 * ★ 为什么要有它：本系统不调平台写接口（同上），所以「平台上做没做」只能由人
 *   回来登记。没有这一步，`executed` 就没有任何数据来源，界面也就没有资格
 *   说「已执行」。
 *
 * ★ 请求体里**没有** `executed_by`：与 `approver` / `actor` 同一条口径，
 *   登记人由服务端注入 —— 让客户端自报「我执行完了」= 审计字段可伪造。
 */
export interface ExecutionReceiptParam {
  /** 当前只接受 `manual`（人工在平台执行后登记） */
  execution_mode?: string
  /** 平台侧凭证号：退款单号 / 券码 / case id；拿不到就留空 */
  platform_ref?: string
  /** 回执备注：做了什么、在哪做的 */
  receipt_note?: string
}

export async function recordExecutionReceipt(
  reviewId: string,
  data: ExecutionReceiptParam = {},
): Promise<Disposition> {
  return request.post(
    `/trade/dispositions/${encodeURIComponent(reviewId)}/receipt`,
    data,
  )
}


// ============================================================ 个案 / 系统性判定（第 294 轮 B 档）
//
// ★ 为什么这两个接口必须存在：判定与健康分此前**只有 Agent 工具通道**能到达
//   （`count_repeat_issues` 全仓唯一消费点是 `modules/trade/tools.py` 那个工具）
//   ⇒ 差评工作台面板**结构上给不出**「这是个案还是系统性问题」这一步，
//   而且漏得毫无提示。
//
// ★ 判定结论一律取自后端（`verdict` / `verdict_label` / `recommend_escalate`）：
//   组合规则（同因次数 ≥ 阈值，且环比为负或中差评占比偏高 ⇒ 系统性）本身就是
//   判据，复制到界面就是**同一可见性两份实现**（本仓铁律）。

/** SKU 买家反馈健康分 —— **不是**广告分析里广告活动的 health_score */
export interface SkuHealth {
  found: boolean
  sku: string
  asin?: string
  product_title?: string
  period_days?: number
  period_end?: string
  health_score?: number
  previous_score?: number
  delta?: number
  top_cause?: string
  dimensions?: Record<string, number>
  cause_counts?: Record<string, number>
  review_count?: number
  negative_rate?: number
  avg_rating?: number
  delayed_orders?: number
  /** `found=false` 时的原因（该 SKU 还没算过健康分，需先有一期归因数据） */
  error?: string
}

/** 判定结论 —— 取值与后端 `service.VERDICT_LABELS` 的键一一对应 */
export type SystemicVerdict = 'isolated' | 'repeat' | 'systemic' | 'unknown'

export interface SystemicCheck {
  ready: boolean
  review_id: string
  sku?: string
  primary_cause?: string
  primary_cause_label?: string
  historical_count?: number
  is_repeat_issue?: boolean
  /** 阈值 —— 唯一真源在后端 `service.REPEAT_ISSUE_THRESHOLD`，界面**不写死** */
  threshold?: number
  health?: SkuHealth | null
  trending_down?: boolean
  high_negative_rate?: boolean
  verdict: SystemicVerdict
  verdict_label: string
  recommend_escalate: boolean
  reason: string
}

/**
 * 这条差评是个案还是系统性问题 —— **后端唯一判定口径**。
 *
 * `ready=false` ⇒ 看 `reason`（多半是这条差评还没有归因；此时硬判等于猜）。
 */
export async function getReviewSystemicCheck(reviewId: string): Promise<SystemicCheck> {
  return request.get(`/trade/reviews/${encodeURIComponent(reviewId)}/systemic-check`)
}

/** 某 SKU 最近一期买家反馈健康分（`found=false` ⇒ 还没算过，**不等于 0 分**） */
export async function getSkuHealth(sku: string): Promise<SkuHealth> {
  return request.get(`/trade/skus/${encodeURIComponent(sku)}/health`)
}

// ============================================================ 风险话术识别（第 299 轮 P1）
//
// ★ 这个视图存在的理由：后端 P0 已经有「这条差评是不是威胁/索赔/投诉」的判定能力
//   （`modules/trade/risk_scan.py`，四类 + 证据片段），但它此前**只有脚本能到达**
//   —— 没有任何出口，界面也就看不见。能力在而用户摸不到，等于没有。
//
// ★★ 三条口径一律取自后端，前端**不得**自算：
//   1. **顺序**：后端按「风险 → 未定论 → 干净」排好才返回，界面按序渲染即可。
//      在界面再 `sort` 一次 = 同一判定两份实现（改了后端忘前端 ⇒ 两边不一致）。
//   2. **中文名**：类别名 / 等级名走响应里的 `category_labels` / `level_labels`。
//   3. **三态**：`risk` / `clean` / `unknown` 方向不同 —— `unknown` 是「算法不敢定，
//      要人补判」，`clean` 是「明确无风险」。界面**必须分开播报**，不可合并。

/** 风险等级 —— 键与后端 `risk_scan.LEVEL_LABELS` 一一对应 */
export type ReviewRiskLevel = 'high' | 'medium' | 'low' | 'unknown'

/** 定论三态 —— 与后端 `risk_scan.DECISION_RISK / _CLEAN / _UNKNOWN` 对齐 */
export type ReviewRiskDecision = 'risk' | 'clean' | 'unknown'

/**
 * 类别码 —— `r1..r4` 是**四类风险话术**（后端 `RISK_CATEGORIES`）；
 * `r5`（高情绪差评）**不是风险**，只是候选池，别把它当成命中风险。
 */
export type ReviewRiskCategory = 'r1' | 'r2' | 'r3' | 'r4' | 'r5'

/** 一条命中（后端 `risk_scan.RiskHit.as_dict()`）；`evidence` 是**原文片段** */
export interface ReviewRiskHit {
  category: ReviewRiskCategory
  /** 类别中文名 —— 后端下发（`CATEGORY_LABELS`），界面不得自写一份 */
  label: string
  level: ReviewRiskLevel
  evidence: string[]
  /** naive | rule | llm | fuse */
  channel: string
  note: string
}

/** 一条差评的风险块（后端 `service._risk_block_from_scan`） */
export interface ReviewRiskBlock {
  decision: ReviewRiskDecision
  level: ReviewRiskLevel
  /** 等级中文名 —— 后端下发（`LEVEL_LABELS`） */
  level_label: string
  suggested_action: string
  /** 是否命中**四类风险**之一（`r5` 不算，见 `ReviewRiskCategory`） */
  is_risk: boolean
  categories: ReviewRiskCategory[]
  risk_categories: ReviewRiskCategory[]
  hits: ReviewRiskHit[]
  channel: string
  note: string
}

/** 带风险块的差评 = 主列表同形 + `risk` */
export interface ReviewWithRisk extends ProductReview {
  risk: ReviewRiskBlock
}

export interface ReviewRiskScanResult {
  /** ★ 已由后端排序：风险 → 未定论 → 干净；同组内新→旧。界面按序渲染，**不得重排** */
  items: ReviewWithRisk[]
  /** 真实条数（不受 limit 截断） */
  total: number
  scanned: number
  risk_count: number
  unknown_count: number
  clean_count: number
  deep: boolean
  llm_used: boolean
  /**
   * ★ 语义通道被请求却不可用（没配 LLM 凭据）⇒ `true`，且**每条判 `unknown`**。
   * 界面必须如实播报这层降级 —— 显示成「全部清白」就是把一次没扫成的扫描
   * 伪装成一次通过的扫描。
   */
  degraded: boolean
  /**
   * ★ 第 300 轮分层读数：**送进语义通道**的条数（= 规则没判出四类的那些）。
   * 三个读数一起看才能回答「省下来的钱花在哪」。
   */
  semantic_sent: number
  /**
   * ★ 被规则预筛跳过、因而**没花模型钱**的条数。
   * 只在 `llm_used` 为真时有意义（浅层压根不打算调语义，那时后端报 0）。
   */
  semantic_skipped: number
  /** ★ 实际发出的**批量**语义请求次数（0 ⇒ 这次一次都没花） */
  llm_calls: number
  /** 本页被服务端上限截断（`deep` 上限更低）⇒ 与 `scanned < total` 一起解释 */
  capped: boolean
  /** 四类风险的类别码（渲染图例用） */
  categories: ReviewRiskCategory[]
  category_labels: Record<string, string>
  level_labels: Record<string, string>
  max_rating: number
  days: number
  limit: number
  offset: number
}

/**
 * 对近期中差评逐条跑风险话术识别，按「风险 → 未定论 → 干净」排序后返回。
 *
 * ★ **只读**：不写库、不发券、不改处置状态。识别只产线索；处置动作仍旧要人批准。
 * ★ `deep=true` 才走语义通道 —— **默认档是浅层**，语义必须由用户
 *   **显式点击**触发，不要挂在页面自动加载里。所以下面的调用点**显式**写 `deep`，
 *   不依赖后端默认值：默认值一改，成本就从「按了才发生」变成「谁来调都发生」，
 *   而接口文档、压测脚本、未来的 Agent 工具都不会报错。
 *
 * ★★ 后端是**分层**的（第 300 轮），前端不必关心细节，但要知道这三件事
 * ---------------------------------------------------------------
 *   ① 规则通道全量先跑（零成本），并决定「谁不用送语义」；
 *   ② 规则已判出四类的条目**不送语义**（`semantic_skipped` 就是它们的条数）；
 *   ③ 其余条目**打包成一次批量调用**（`llm_calls` 是实际发出的次数）。
 *   ⇒ 实测 20 条：43.4s（第 299 轮的逐条串行）→ 约 2s。
 *
 * ★★ 为什么 deep 仍然单独放宽超时（第 299 轮 P1 的结论，数字按第 300 轮更新）
 * --------------------------------------------------------------------------
 *   `request.ts` 的全局 timeout 是 30s。分层之后深扫的**典型**耗时降到约 2s，
 *   但**尾延迟**不可控 —— 一次批量请求的耗时取决于模型侧抖动，而且
 *   `core/resilience.py` 对它最多还有 3 次重试（`LLM_MAX_RETRIES=3`）。
 *   ⇒ 仍然传 per-call timeout，且必须**明显**大于全局值
 *     （门禁按「≥ 全局值 ×3」判，见 `scripts/check-review-risk-view.cjs` 的 R12）。
 *   ★ 取 180s 而不是「刚好 45s」：留出模型侧抖动与后续条数上调的余量，
 *     但仍是**有界的**（不是 0 = 永不超时，那会让失败永远转不成错误）。
 *   ★ 浅层调用**不动**走全局 30s：它实测 0.03s，放宽它只会把
 *     「后端真的挂了」这件事从 30s 推迟到 180s 才告诉用户。
 */
const RISK_SCAN_DEEP_TIMEOUT_MS = 180_000

export async function scanReviewsRisk(params?: {
  max_rating?: number
  days?: number
  limit?: number
  offset?: number
  deep?: boolean
}): Promise<ReviewRiskScanResult> {
  const config = params?.deep ? { timeout: RISK_SCAN_DEEP_TIMEOUT_MS } : {}
  return request.get('/trade/reviews/risk', { params, ...config })
}

// ============================================================ 补偿规则配置 + 补归因（第 304 轮后半）
//
// ★ 为什么这一块必须补：`compensation_rules` 有表、有 3 条种子、有匹配逻辑
//   （`list_enabled_rules_for_cause` / `match_compensation_rule`），但此前**没有
//   端点也没有界面**。失败提示让人「到补偿规则里配一条」= 指向一个不存在的
//   面板（负指令）。老板在风险 12 条 vs 台账 5 条的对账里撞到的正是这个：
//   12 条里 8 条 `primary_cause = unknown`，自动判定判不出、又无入口推进，
//   于是永远进不了台账。
//
// ★ 两块各解一个缺口：
//   · 补归因 —— 把「判不出来」的差评手工标上具体成因（落 `method=manual`，
//     自动同步不会冲回 unknown）；
//   · 补偿规则 CRUD —— 给「这一类还没有规则」的成因补一条规则。

/** 归因取值（与后端 `ATTRIBUTION_CAUSES` 对齐）；**补归因不接受 `unknown`** */
export type AttributionCause =
  | 'logistics_delay' | 'packaging_failure' | 'product_defect'
  | 'description_mismatch' | 'service_attitude' | 'price_value' | 'unknown'

/** 归因中文名 —— 与后端 `CAUSE_LABELS` 对齐（补归因下拉的 label） */
export const CAUSE_LABELS: Record<AttributionCause, string> = {
  logistics_delay: '物流延迟',
  packaging_failure: '包装破损',
  product_defect: '商品缺陷',
  description_mismatch: '描述不符',
  service_attitude: '服务态度',
  price_value: '价格价值',
  unknown: '未判定',
}

/** 可选的归因（补归因下拉**不含** `unknown`，与后端 `ATTRIBUTABLE_CAUSES` 对齐） */
export const ATTRIBUTABLE_CAUSES: AttributionCause[] = [
  'logistics_delay', 'packaging_failure', 'product_defect',
  'description_mismatch', 'service_attitude', 'price_value',
]

/** 条件键（与后端 `CONDITION_KEYS` 对齐：max_rating / min_delay_days / verified_purchase） */
export type RuleCondition = {
  max_rating?: number
  min_delay_days?: number
  verified_purchase?: boolean
}

/** 补偿方式（与后端 `ACTION_TYPES` 对齐：coupon / refund / none） */
export type RuleAction = {
  type: 'coupon' | 'refund' | 'none'
  amount?: number
  currency?: string
  refund_percent?: number
}

/** 一条补偿规则（后端 `service._rule_to_dict`） */
export interface CompensationRule {
  id: string
  code: string
  name: string
  cause: AttributionCause
  /** 归因中文名 —— 后端下发（`CAUSE_LABELS`），界面**不**写第二份映射 */
  cause_label: string
  priority: number
  conditions: RuleCondition
  action: RuleAction
  budget_cap: number
  enabled: boolean
  notes: string
  created_at: string
  updated_at: string
}

/** `POST /compensation-rules` 请求体（归属由服务端注入，**没有** shop_id） */
export interface CreateRuleParam {
  code: string
  name?: string
  cause: AttributionCause
  priority?: number
  conditions?: RuleCondition
  action?: RuleAction
  budget_cap?: number
  enabled?: boolean
  notes?: string
}

/** `PATCH /compensation-rules/{id}` 请求体 —— 只改传进来的字段，`code` 不可改 */
export interface UpdateRuleParam {
  name?: string
  cause?: AttributionCause
  priority?: number
  conditions?: RuleCondition
  action?: RuleAction
  budget_cap?: number
  enabled?: boolean
  notes?: string
}

/** 手工给一条差评指定归因的请求体（`primary_cause` 不接受 `unknown`） */
export interface SetAttributionParam {
  primary_cause: AttributionCause
  causes?: string[]
  evidence?: any[]
  notes?: string
}

/** 列出本店全部补偿规则（含停用；后端按 cause → priority 排序） */
export async function listCompensationRules(params?: {
  include_disabled?: boolean
}): Promise<CompensationRule[]> {
  return request.get('/trade/compensation-rules', { params })
}

/** 新建一条补偿规则（同店同 code ⇒ 后端 409） */
export async function createCompensationRule(
  data: CreateRuleParam,
): Promise<CompensationRule> {
  return request.post('/trade/compensation-rules', data)
}

/** 部分更新一条补偿规则（含启停；`code` 不可改） */
export async function updateCompensationRule(
  ruleId: string,
  data: UpdateRuleParam,
): Promise<CompensationRule> {
  return request.patch(`/trade/compensation-rules/${encodeURIComponent(ruleId)}`, data)
}

/** 删除一条补偿规则（硬删；想留用走 `enabled=false` 停用） */
export async function deleteCompensationRule(ruleId: string): Promise<void> {
  await request.delete(`/trade/compensation-rules/${encodeURIComponent(ruleId)}`)
}

/** 手工给一条差评指定归因（落 `method=manual`，自动同步不冲回 unknown） */
export async function setReviewAttribution(
  reviewId: string,
  data: SetAttributionParam,
): Promise<Record<string, any>> {
  return request.post(`/trade/reviews/${encodeURIComponent(reviewId)}/attribution`, data)
}

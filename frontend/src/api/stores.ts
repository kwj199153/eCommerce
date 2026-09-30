/**
 * 店铺群 + 利润测算 API
 *
 * Phase 10: 多平台动态利润计算
 */

import { get, post, put, del } from './request'

// ====== 类型定义 ======

export interface FeeBreakdownItem {
  name: string
  amount: number
  is_percentage: boolean
  percentage_value?: number | null
}

export interface ProfitResult {
  platform: string
  currency: string
  listing_price: number
  final_price: number
  fee_breakdown: FeeBreakdownItem[]
  /** 平台与运营费用合计（不含采购/头程/包装） */
  total_fees: number
  /** 全部成本 = 采购 + 头程 + 包装 + total_fees */
  total_cost: number
  gross_profit: number
  net_profit: number
  profit_margin_pct: number
  roi: number
  discount_applied: boolean
  effective_discount_pct: number
  coupon_discount_pct: number
  flash_sale_discount_pct: number
  calculation_mode: string
  formula_summary: string
}

export interface ProfitRequest {
  product_cost: number
  listing_price?: number | null
  target_profit?: number | null
  ad_cost?: number
  quantity?: number
  // ===== 通用成本项（与面板 13 项表单一一对应）=====
  shipping_cost?: number
  packaging_cost?: number
  return_rate_pct?: number
  exchange_loss_pct?: number
  /** null/undefined = 没传，走店铺折扣模板；0 = 显式无折扣 */
  discount_pct?: number | null
  /** 覆盖店铺费率模板；键用面板表单字段名，后端按平台翻译 */
  overrides?: Record<string, number> | null
}

/**
 * 面板表单（语义字段名）→ 后端利润请求。
 *
 * 右栏面板是利润测算的唯一输入口，对话结果卡与右栏预览共用这一份请求、
 * 调同一个接口拿同一份结果 —— 两处绝不各自复算（那正是「一个表单两个结果」的根源）。
 */
export function toProfitRequest(form: Record<string, any>): ProfitRequest {
  const num = (v: any): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  const isReverse = form?.mode === 'reverse'
  return {
    product_cost: num(form?.costPrice),
    // 正向只认售价、逆向只认目标毛利。两个都传的话后端优先走正向，
    // 会把逆向算成「按残留售价的正向利润」（目标售价在逆向下被禁用但仍留着旧值）。
    listing_price: isReverse ? null : (form?.sellingPrice ?? null),
    target_profit: isReverse ? (form?.targetProfit ?? null) : null,
    ad_cost: num(form?.adCost),
    shipping_cost: num(form?.shippingCost),
    packaging_cost: num(form?.packagingCost),
    return_rate_pct: num(form?.returnRatePct),
    exchange_loss_pct: num(form?.exchangeLossPct),
    discount_pct: num(form?.discountPct),
    overrides: {
      referralFeePct: num(form?.referralFeePct),
      fbaFee: num(form?.fbaFee),
      storageFee: num(form?.storageFee),
      vatRate: num(form?.vatRate),
      withdrawalFeePct: num(form?.withdrawalFeePct),
    },
  }
}

export interface Store {
  id: string
  name: string
  platform: string
  currency: string
  region_code: string
  fee_template_id: string | null
  discount_template_id: string
  is_active: boolean
  /**
   * 库里那一组凭据**是否已通过平台校验**。
   *
   * ★★ 第 318 轮：这个字段此前**永远读不到** —— 后端 `Store.is_connected` 是普通
   *    `@property`，而 pydantic v2 不会把普通 property 序列化进 `model_dump()`
   *    ⇒ JSON 里根本没有这个键 ⇒ 前端恒 `undefined` ⇒ 状态标签恒显示「未连接」。
   *    后端已改为 `@computed_field`（见 `models/store.py`）。
   *
   * ⚠️ 它与 `has_credentials` 回答的是**两个不同的问题**，不能互相替代：
   *   - `is_connected`    = 凭据已验证通过（绿灯）
   *   - `has_credentials` = 库里有凭据，但**可能没验过**（网络不通 / 平台未接入校验）
   *   只读前者 ⇒「已配置未验证」被显示成「未连接」，用户以为白填了；
   *   只读后者 ⇒ 没验过的被显示成「已连接」，正是本轮要消灭的**空承诺**。
   *   ⇒ 状态展示请走 `shopConnectState()`（本文件），别在组件里各拼一套。
   */
  is_connected: boolean
  /** 库里是否已存有加密凭据（**不代表**验证通过） */
  has_credentials: boolean
  status: string
  connection_status: string
  /**
   * 所属账户 ID（★ A/B 档 2026-09-17）
   *
   * ★ 归属判定的真源是后端 `account_id`，本字段供前端做
   *   「按当前账户筛选店铺」与"把店转到哪个账户"的展示。
   *   兼容过渡：存量/合成店铺可能为 null（走 owner_id 兜底）。
   */
  account_id?: string | null
}

export interface SupportedMarket {
  key: string
  currency: string
  template_id: string
}

// ====== API 函数 ======

/**
 * 动态利润计算（核心接口）
 *
 * @param data 计算参数
 * @param storeId 当前选中的店铺 ID（通过 Header 传递）
 */
export async function calculateProfit(
  data: ProfitRequest,
  storeId: string,
): Promise<ProfitResult> {
  return post<ProfitResult>('/stores/profit/calculate', data, {
    headers: { 'X-Store-ID': storeId },
  })
}

/**
 * 获取店铺列表
 */
export async function fetchStores(): Promise<{ stores: Store[]; total: number }> {
  return get('/stores')
}

/**
 * 获取店铺详情
 */
export async function fetchStoreDetail(storeId: string): Promise<Store & Record<string, any>> {
  return get(`/stores/${storeId}`)
}

/**
 * 创建店铺
 */
export async function createShop(data: {
  name: string
  platform: string
  currency?: string
  fee_template_id?: string
  description?: string
  /**
   * 目标容器 ID（★ A 档 2026-09-17）。
   * 不传 ⇒ 后端建到你的**默认容器**（判据见后端 `ensure_default_account`）。
   * 传了 ⇒ 必须对该容器有 `store.write`，否则 403。
   * ★ 第 110 轮：原写作"个人账户"，该概念已被证伪（容器只有一种）。
   */
  account_id?: string
}): Promise<Store> {
  return post<Store>('/stores', data)
}

/**
 * 把店铺转移到另一个账户（★ A 档 2026-09-17）
 *
 * ★ 后端要过**两道**门：对原账户有 `store.write` + 对目标账户有 `store.write`。
 *   前端不做镜像判定（那是两套判定的老路），失败时把后端的 403 原样呈现。
 */
export async function transferStore(storeId: string, accountId: string): Promise<Store> {
  return post<Store>(`/stores/${storeId}/transfer`, { account_id: accountId })
}

/**
 * 更新店铺
 */
export async function updateShop(
  shopId: string,
  data: Partial<Pick<Store, 'name' | 'status'>>,
): Promise<Store> {
  return put<Store>(`/stores/${shopId}`, data)
}

/**
 * 删除店铺
 */
export async function deleteShop(shopId: string): Promise<void> {
  return del(`/stores/${shopId}`)
}

// ====== 平台连接（★ 第 318 轮：从「后端有个端点」变成「真的能用」）======
//
// ★★ 这一段的类型全部**由后端下发**驱动：前端不认识 `amazon` / `shopee`，
//    只认识 `PlatformSchema` 这个结构。加平台 = 后端加几条声明，前端零改动。

/** 输入控件类型。★ 刻意只有三种：多一种就多一个前端分支，而「每个平台写一套」正是从分支长出来的 */
export type CredentialFieldType = 'text' | 'password' | 'select'

/** 一个凭据字段的规格 */
export interface CredentialField {
  key: string
  label: string
  type: CredentialFieldType
  required: boolean
  placeholder: string
  help: string
  /** 敏感字段：回显一律掩码，永不回明文 */
  secret: boolean
  options: Array<{ value: string; label: string }>
  default: string
}

/** 一个平台的连接表单规格 */
export interface PlatformSchema {
  platform: string
  display_name: string
  docs_url: string
  fields: CredentialField[]
  notes: string[]
  /** 本平台是否已接入自动校验；false ⇒ 只会存凭据，不会标记「已验证」 */
  verify_supported: boolean
}

/**
 * 验证结论（★ 刻意是四态，不是布尔）。
 *
 * `invalid`（凭据被平台拒绝）与 `unreachable`（超时/DNS/5xx，凭据好坏**未知**）
 * 必须分开 —— 合成一个 false 时，网络抖一下就会把用户正确的凭据判成错的，
 * 用户会去反复改一个本来没错的东西。
 */
export type VerifyStatus = 'ok' | 'invalid' | 'unreachable' | 'unsupported'

export interface VerifyCheck {
  name: string
  ok: boolean
  message: string
}

/**
 * 对外形态的验证报告。
 *
 * ★ 与后端 `VerifyResult` 的区别：这里**没有** `refreshed` ——
 *   那里面装的是刚换到的新令牌明文，绝不能进响应体。
 */
export interface VerifyReport {
  status: VerifyStatus
  message: string
  checks: VerifyCheck[]
  detail: Record<string, any>
  ok: boolean
}

/** `GET /stores/connect/schema`（全平台规格，弹窗打开时取一次） */
export async function fetchConnectSchemas(): Promise<PlatformSchema[]> {
  const r = await get<{ schemas: PlatformSchema[] }>('/stores/connect/schema')
  return r?.schemas ?? []
}

/** 单店连接规格 + **掩码**回显（用户重开弹窗时知道自己配过什么） */
export interface StoreConnectSpec {
  spec: PlatformSchema
  configured: Record<string, boolean>
  /** 非敏感字段的原值 + 敏感字段的 `••••••`，**不含任何明文敏感值** */
  values: Record<string, any>
  any_configured: boolean
  connection_status: string
  is_connected: boolean
  has_credentials: boolean
}

export async function fetchStoreConnectSpec(shopId: string): Promise<StoreConnectSpec> {
  return get(`/stores/${shopId}/connect/schema`)
}

/** 连接结果 */
export interface StoreConnectResult {
  store_id: string
  platform: string
  family: string
  message: string
  verify: VerifyReport
  connection_status: string
  is_connected: boolean
  has_credentials: boolean
}

/**
 * 连接平台：**后端会真去平台验一次**，通过后才置「已连接」。
 *
 * ★ 请求体是**扁平的凭据 dict**（不是 `{credentials: {...}}`）—— 与后端契约一致。
 *
 * ★ 失败的三种形态（前端必须分开处理，别一律弹「连接失败」）：
 *   - `400` + `detail` 是**对象** `{message, status, checks}` ⇒ 凭据被平台拒绝，
 *     展开 `checks` 告诉用户是**哪一步**断了（换 token 还是签名）；
 *   - `400` + `detail` 是**字符串** ⇒ 输入问题（缺必填字段，文案已带中文字段名）；
 *   - `503` ⇒ 服务端未配加密密钥（原因可读，不是用户的问题）。
 */
export async function connectPlatform(
  shopId: string,
  credentials?: Record<string, any>,
): Promise<StoreConnectResult> {
  return post<StoreConnectResult>(`/stores/${shopId}/connect`, credentials)
}

/**
 * 断开平台 API（后端会**真的清除**已存的加密凭据）
 */
export async function disconnectPlatform(shopId: string): Promise<void> {
  return post(`/stores/${shopId}/disconnect`)
}

/** 连接状态的展示档位 */
export type ShopConnectState = 'connected' | 'configured' | 'disconnected'

/**
 * 把「两个布尔」收敛成**一个三态** —— 界面文案的唯一来源。
 *
 * ★ 为什么必须有这个函数（而不是在组件里各写一个三元表达式）：
 *   同一个判定写在两处，改一处漏一处时，两个界面会对同一家店显示不同的状态，
 *   而两边都不会报错。
 *
 * `connected`    已通过平台校验 → 绿灯「已连接」
 * `configured`   有凭据但**未验证**（网络不通 / 平台未接入校验）→ 黄灯「已配置（未验证）」
 * `disconnected` 库里没有凭据 → 灰灯「未连接」
 */
export function shopConnectState(
  shop: Pick<Store, 'is_connected' | 'has_credentials'>,
): ShopConnectState {
  if (shop?.is_connected) return 'connected'
  if (shop?.has_credentials) return 'configured'
  return 'disconnected'
}

/**
 * 获取费率模板详情
 */
export async function fetchFeeTemplate(platformKey: string) {
  return get(`/stores/profit/fee-template/${platformKey}`)
}

/**
 * 获取所有支持的站点
 */
export async function fetchSupportedMarkets(): Promise<{
  amazon: SupportedMarket[]
  shopee: SupportedMarket[]
}> {
  return get('/stores/profit/supported-markets')
}

/**
 * 获取费率模板列表
 */
export async function fetchFeeTemplates(platformType?: string) {
  const params = platformType ? `?platform_type=${platformType}` : ''
  return get(`/stores/fee-templates${params}`)
}

/**
 * 获取折扣规则模板列表
 */
export async function fetchDiscountTemplates() {
  return get('/stores/discount-templates')
}

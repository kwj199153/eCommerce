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
  is_connected: boolean
  status: string
  connection_status: string
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
}): Promise<Store> {
  return post<Store>('/stores', data)
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

/**
 * 连接平台 API
 */
export async function connectPlatform(
  shopId: string,
  credentials?: Record<string, any>,
): Promise<void> {
  return post(`/stores/${shopId}/connect`, credentials)
}

/**
 * 断开平台 API
 */
export async function disconnectPlatform(shopId: string): Promise<void> {
  return post(`/stores/${shopId}/disconnect`)
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

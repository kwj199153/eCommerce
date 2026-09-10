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
  total_fees: number
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

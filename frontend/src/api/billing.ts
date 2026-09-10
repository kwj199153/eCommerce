/**
 * 订阅 & 计费 API
 */

import { get, post, put } from './request'

// ====== 类型定义 ======

export interface SubscriptionPlan {
  id: string
  name: string
  display_name: string
  price_monthly: number
  price_yearly: number
  features: string[]
  limits: {
    api_calls_per_month: number
    agent_chats_per_month: number
    shops_limit: number
    team_members: number
    ai_generations: number
  }
  recommended?: boolean
}

export interface UsageInfo {
  api_calls_used: number
  api_calls_limit: number
  agent_chats_used: number
  agent_chat_limit: number
  ai_gen_used: number
  ai_gen_limit: number
}

export interface Subscription {
  id: string
  status: 'active' | 'past_due' | 'cancelled' | 'trialing' | 'expired'
  plan: SubscriptionPlan
  usage: UsageInfo
  period: {
    start: string
    end: string | null
  }
  cancel_at_period_end: boolean
  created_at: string
}

export interface Invoice {
  id: string
  number: string
  amount: number
  currency: string
  status: 'paid' | 'pending' | 'failed' | 'refunded'
  description: string
  issued_at: string
  paid_at: string | null
  pdf_url: string | null
}

export interface PaymentMethod {
  id: string
  type: 'card' | 'alipay' | 'wechat'
  brand: string
  last4: string
  exp_month: number
  exp_year: number
  is_default: boolean
}

// ====== API 函数 ======

/** 获取当前订阅信息 */
export async function fetchSubscription(): Promise<{ subscription: Subscription }> {
  return get('/billing/subscription')
}

/** 获取所有可用套餐 */
export async function fetchPlans(): Promise<{ plans: SubscriptionPlan[] }> {
  return get('/billing/plans')
}

/** 升级/切换套餐 */
export async function changePlan(planId: string, billingCycle: 'monthly' | 'yearly'): Promise<{
  subscription: Subscription
  client_secret: string  // Stripe payment intent
}> {
  return post('/billing/subscribe', { plan_id: planId, billing_cycle: billingCycle })
}

/** 取消订阅（周期结束后生效） */
export async function cancelSubscription(): Promise<{ subscription: Subscription }> {
  return post('/billing/cancel')
}

/** 恢复已取消的订阅 */
export async function resumeSubscription(): Promise<{ subscription: Subscription }> {
  return post('/billing/resume')
}

/** 获取账单历史 */
export async function fetchInvoices(params?: { page?: number; page_size?: number }): Promise<{
  invoices: Invoice[]
  total: number
  page: number
}> {
  const query = params ? `?page=${params.page || 1}&page_size=${params.page_size || 10}` : ''
  return get(`/billing/invoices${query}`)
}

/** 获取支付方式列表 */
export async function fetchPaymentMethods(): Promise<{ payment_methods: PaymentMethod[] }> {
  return get('/billing/payment-methods')
}

/** 添加支付方式 */
export async function addPaymentMethod(paymentMethodId: string): Promise<PaymentMethod> {
  return post('/billing/payment-methods', { payment_method_id: paymentMethodId })
}

/** 删除支付方式 */
export async function removePaymentMethod(methodId: string): Promise<void> {
  return put(`/billing/payment-methods/${methodId}`, { action: 'detach' })
}

/** 设置默认支付方式 */
export async function setDefaultPaymentMethod(methodId: string): Promise<void> {
  return put(`/billing/payment-methods/${methodId}`, { action: 'set_default' })
}

/** 获取用量统计（支持时间范围） */
export async function fetchUsageStats(params?: { start_date?: string; end_date?: string }): Promise<{
  usage: UsageInfo
  daily_breakdown: Array<{ date: string; api_calls: number; agent_chats: number }>
}> {
  const query = params
    ? `?start_date=${params.start_date}&end_date=${params.end_date}`
    : ''
  return get(`/billing/usage${query}`)
}

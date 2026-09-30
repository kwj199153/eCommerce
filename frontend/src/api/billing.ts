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
  /** 计费周期（后端 subscriptions.billing_cycle，旧数据由迁移填 'monthly'） */
  billing_cycle: 'monthly' | 'yearly'
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

/**
 * 一张**待支付**账单（支付宝当面付两段式的第一段产物）。
 *
 * ★ 字段与后端 `modules/billing/payments.py::pending_payment_payload` **一一对应**
 *   （`/billing/subscribe` 的 `payment` 字段与 `/billing/payment/pending` 共用同一个
 *   构造函数 —— 所以这里只写一份类型，两条路径的解析代码也只有一份）。
 */
export interface PendingPayment {
  invoice_id: string
  number: string
  amount: number
  currency: string
  /** 'pending' | 'paid' | 'expired' | 'failed' | 'refunded' */
  status: string
  plan_id: string | null
  billing_cycle: 'monthly' | 'yearly'
  /** 'alipay' / null（演示身份同步直通，根本没有支付渠道） */
  payment_channel: string | null
  /**
   * 二维码**原值**（形如 `https://qr.alipay.com/xxx`）。
   * ★ 不要直接拿它渲染 —— 出图是后端的活（`/billing/payment/qr/{id}`）。
   *   留着它只是为了排障：用户说"扫不出来"时，把这段贴进支付宝核对。
   */
  qr_code_url: string
  /** RFC3339 **带偏移**（后端走 core/timefmt.utc_iso）—— 可直接 `new Date()` */
  created_at: string | null
  /** 同上。倒计时读的就是它，别自己再算 TTL */
  expires_at: string | null
  /** 仅在已支付的账单上出现（轮询接口会给） */
  paid_at?: string | null
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

/**
 * 升级/切换套餐
 *
 * ★ 返回 HTTP 200 **不等于**已收款，必须看 `charged`：
 *   - charged=true  本次真的走了扣款（**演示身份**恒走这条：无需扫码，点一下即开通）
 *   - charged=false 未扣款。**三种原因必须分清**，否则文案会撒谎：
 *       · already_subscribed=true  同套餐同周期重复提交，权益已满足
 *       · requires_confirmation    **已下单、待用户扫码** ⇒ 必须弹二维码，
 *                                  绝不能提示"已切换套餐"（权益还没给！）
 *       · skipped_reason           金额为 0（免费套餐）等，无需支付
 *
 * ★ 为什么 `subscription` 可能是 null：
 *   两段式的第一段**刻意不动订阅**（用户还没付钱，凭什么动他的权益）。
 *   于是「从未订阅过的用户」在下单后，这里的 subscription 仍是 null。
 *   前端必须容忍 —— 把 null 当成"没有订阅"去渲染，别当异常。
 *
 * ★ `payment.expires_at` 是**带偏移**的 RFC3339（后端 core/timefmt.utc_iso），
 *   可以直接 `new Date()` 做倒计时；不要自己拿 created_at 加一个 TTL 常量
 *   —— 那会造出第二份 TTL 口径，与支付宝侧 `timeout_express` 漂移。
 */
export async function changePlan(planId: string, billingCycle: 'monthly' | 'yearly'): Promise<{
  subscription: Subscription | null
  client_secret: string  // Stripe payment intent
  charged: boolean
  /** 后端的同步形态也会显式回 false，见 router.change_plan 的返回 */
  requires_confirmation?: boolean
  payment?: PendingPayment | null
  already_subscribed?: boolean
  /** 同一套餐同一周期已有一张未支付的单：后端把**原来那张**二维码再给一次 */
  already_pending?: boolean
  skipped_reason?: string
  message?: string
}> {
  // ★ `silentError`：调用点（Subscription.vue::confirmSwitchPlan）有**唯一**的
  //   catch 报告出口。不声明的话，一个 402「支付失败」/ 503「支付通道未就绪」
  //   会"响应拦截器弹一条 + 调用点再弹一条"，用户看到两条一样的红条。
  return post(
    '/billing/subscribe',
    { plan_id: planId, billing_cycle: billingCycle },
    { silentError: true }
  )
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

// ====== 支付宝扫码支付的三个读接口 ======
//
// ★ 为什么是三个而不是"下单响应里全带上"：
//   下单响应只在**下单那一刻**存在。用户刷新页面后它就没了 —— 而刷新是常态。
//   没有这三条，用户只能重新下单（多出一张废单），且他很可能只在支付宝侧
//   付了其中一张 ⇒ "付了钱没到账"的投诉。

/**
 * 当前用户是否有一张未支付的订单（没有则 `payment` 为 `null`）。
 *
 * ★ 页面加载时调它来**恢复二维码**（刷新页面后仍能看到刚才那张码）。
 *   只看 `pending`：已过期的单不该再引导用户去扫（码已经死了）。
 */
export async function fetchPendingPayment(): Promise<{ payment: PendingPayment | null }> {
  return get('/billing/payment/pending')
}

/**
 * 取账单二维码的 SVG data URI（可直接绑给 `<img src>`）。
 *
 * ★ 为什么单独一个请求、而不是塞进轮询响应里：
 *   SVG 约 7KB、base64 后 ~9.4KB。轮询每 3 秒一次 ⇒ 每秒 3KB 的无谓流量，
 *   且响应体每次都在变、浏览器无法缓存。独立成 GET 之后前端**只取一次**。
 *
 * ★ 409 的语义是「这张账单**已经付过了**」—— 不是错误，是"已完成"。
 *   调用方要把它当成"支付成功"处理（刷新订阅并关闭弹窗），
 *   而不是弹一个"二维码加载失败"。见 Subscription.vue::loadPayQr。
 */
export async function fetchPaymentQr(invoiceId: string): Promise<{ qr_svg: string }> {
  // ★ `silentError`：调用点在弹窗里渲染**常驻**错误面（`payQrFailed`），
  //   不声明就会"横幅 + toast"同一个原因报两遍（见 request.ts 的提示归属）。
  return get(`/billing/payment/qr/${invoiceId}`, undefined, { silentError: true })
}

/**
 * 轮询一张账单的支付状态（前端据此关闭弹窗 / 提示超时）。
 *
 * ★ 别人的账单与不存在的账单返回**同一个 404**（后端刻意合并）——
 *   所以这里拿到 404 时，文案只能说"账单不存在"，不能说"这不是你的账单"。
 */
export async function fetchPaymentStatus(invoiceId: string): Promise<{ payment: PendingPayment }> {
  // ★ `silentError`：这是**每 3 秒一次**的轮询。让拦截器弹错会在网络抖动时
  //   刷出一串红条，而调用点自己有更合适的承载面（弹窗里的提示条）。
  return get(`/billing/payment/${invoiceId}`, undefined, { silentError: true })
}

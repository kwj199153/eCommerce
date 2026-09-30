/**
 * 智能客服 API
 */

import request from './request'

// 客服对话请求/响应接口
export interface ChatMessage {
  message: string
  conversation_id?: string
  context?: Record<string, any>
  customer_id?: string
  /**
   * 点名的技能名（`skills.name`，不是 id）—— 后端 `ChatRequest.skill`，走 **body**。
   * 注意这是**本模块唯一的对话端点** `/customer-service/chat` 的请求体；
   * 字段名必须逐字一致，改名会被 pydantic 静默丢弃。
   */
  skill?: string
  /**
   * 本次请求的「作用对象」（第 298 轮）。**三态**，后端靠它把
   * 「这次冲着哪条差评来的」变成结构化事实，而不是让模型从用户消息或
   * **会话历史**里挑一条：
   *   · 字段**不出现** ⇒ 本客户端未参与该机制，不注入任何提示段；
   *   · `null`        ⇒ 本次**明确没有**对象（本 Agent 只注入、不拒答）；
   *   · `{…}`         ⇒ 本次处置的那条差评（`ref` = `review_id`）。
   * ★ 必须与后端 `ChatRequest.context_target` 同名（改名 ⇒ 被 Pydantic
   *   丢掉 ⇒ 静默无对象，而请求本身照样 200 —— 最难归因的一类）。
   * ★ `detail` 不在本注解里：它是机制层的可选补充字段，调用方传
   *   `ContextTargetPayload` 时会被**原样序列化**发出去（TS 的窄形状
   *   只是给静态检查看的，不影响运行时 JSON）。
   */
  context_target?: { label: string; title: string; ref: string } | null
}

export interface ChatResult {
  reply: string
  conversation_id: string
  intent: string
  sentiment?: any
  data?: any
  display_type: string
  suggested_actions: string[]
  should_escalate: boolean
}

// FAQ 搜索
export interface FAQSearchParam {
  query: string
  limit?: number
  category?: string
}

// 工单创建
export interface TicketCreateParam {
  subject: string
  description: string
  category?: string
  order_id?: string
  priority?: string
  customer_id?: string
}

// 订单追踪
export interface OrderTrackParam {
  order_id?: string
  email?: string
  phone_last4?: string
}

/**
 * 客服对话（主入口）
 */
export async function chatWithCustomerService(data: ChatMessage): Promise<ChatResult> {
  return request.post('/customer-service/chat', data)
}

/**
 * 快速回复（简化版）
 */
export async function quickReply(message: string): Promise<any> {
  return request.post('/customer-service/quick-reply', { message })
}

/**
 * 搜索 FAQ 知识库
 */
export async function searchFAQ(data: FAQSearchParam): Promise<any> {
  return request.post('/customer-service/faq/search', data)
}

/**
 * 获取 FAQ 分类列表
 */
export async function getFAQCategories(): Promise<any> {
  return request.get('/customer-service/faq/categories')
}

/**
 * 创建工单
 *
 * ★ `silentError: true`：写库失败时后端回 **HTTP 200 + `success:false` + message**
 *   （`customer_service/service.py` 的 fail-closed，不是 4xx）。而消费点
 *   （`composables/chat/replies/customerService.ts`）已经把 `payload.message`
 *   渲染进对话卡（「🎫 **工单未能创建**」）⇒ 拦截器再弹一次就是同一个原因两处报。
 */
export async function createTicket(data: TicketCreateParam): Promise<any> {
  return request.post('/customer-service/ticket/create', data, { silentError: true })
}

/**
 * 订单追踪
 *
 * ★ 本端点 **fail-closed** —— 查不到时也返回 200，用 `{found:false, message}`
 *   表达业务结论（而不是 4xx）。第 267 轮之前**必须**传 `{ silent: true }`，
 *   否则拦截器会把那条「查不到」的 message 弹成**绿色「成功」提示**
 *   （于是「订单查不到」被渲染成「查询成功」）。
 *   现在拦截器不再自动弹成功提示，这个开关已无用；又因为响应体**没有**
 *   `success` 字段（用的是 `found`），新补的业务失败补判也不会误伤它。
 */
export async function trackOrder(data: OrderTrackParam): Promise<any> {
  return request.post('/customer-service/order/track', data)
}

/**
 * 情感分析
 */
export async function analyzeSentiment(text: string): Promise<any> {
  return request.post('/customer-service/analyze/sentiment', { text })
}

/**
 * 获取对话摘要
 */
export async function getConversationSummary(conversationId: string): Promise<any> {
  return request.get(`/customer-service/conversation/${conversationId}`)
}

/**
 * 获取 Agent 能力描述
 */
export async function getCustomerServiceCapabilities(): Promise<any> {
  return request.get('/customer-service/capabilities')
}

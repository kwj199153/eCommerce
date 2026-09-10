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
 */
export async function createTicket(data: TicketCreateParam): Promise<any> {
  return request.post('/customer-service/ticket/create', data)
}

/**
 * 订单追踪
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

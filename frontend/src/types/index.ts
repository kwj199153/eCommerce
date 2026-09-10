/**
 * 全局 TypeScript 类型定义
 */

// ====== API 响应类型 ======
export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

// ====== 分页响应 ======
export interface PaginatedResponse<T = any> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ====== Agent 相关 ======
export interface AgentInfo {
  id: string
  name: string
  description: string
  icon: string
  status: 'active' | 'inactive'
}

export interface AgentInvokeRequest {
  agent_id: string
  query: string
  context_id?: string
  shop_id?: string
  options?: Record<string, any>
}

export interface AgentInvokeResponse {
  status: 'completed' | 'error' | 'input_required'
  message: string
  data?: any
  token_usage?: TokenUsage
}

// ====== Token 使用量 ======
export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost: number
}

// ====== 店铺相关 ======
export interface ShopInfo {
  id: string
  name: string
  platform: 'amazon' | 'tiktok' | 'shopify'
  region: string
  status: 'active' | 'inactive'
  marketplace_id?: string
  seller_id?: string
  created_at: string
  updated_at: string
}

// ====== 用户相关 ======
export interface UserInfo {
  id: string
  email: string
  name: string
  avatar?: string
  tenant_id: string
  role: 'owner' | 'admin' | 'member'
  status: 'active' | 'disabled'
  created_at: string
}

// ====== 认证相关 ======
export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  expires_in: number
  user: UserInfo
}

// ====== HITL 审批相关 ======
export type HitlResponseType = 'accept' | 'reject' | 'edit' | 'response'

export interface HitlRequest {
  action_request: {
    action: string
    args: Record<string, any>
    require_reason?: boolean
    timeout?: number
  }
  config?: Record<string, any>
  description: string
}

export interface HitlResponse {
  type: HitlResponseType
  args?: Record<string, any>
}

// ====== 文件上传 ======
export interface UploadResponse {
  file_id: string
  file_name: string
  file_url: string
  file_size: number
  file_type: string
  uploaded_at: string
}

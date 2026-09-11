/**
 * 店秘书（主 Agent / 编排层）API 接口
 */

import request from './request'

/** 后端 orchestrator 返回的动作 */
export interface SecretaryAction {
  action: 'switch_agent' | 'navigate' | 'select_product' | 'open_drawer' | 'account_menu' | 'handoff' | 'set_theme' | 'switch_shop'
  agentId?: string
  view?: string
  /** select_product 专属：选中的产品（id 用于前端从 productLibrary 定位完整对象） */
  product?: { id: string; title: string; asin: string; spu_id?: string } | null
  /** open_drawer 专属：drawer 标识（settings | memory） */
  drawer?: 'settings' | 'memory'
  /** account_menu 专属：账户菜单 target（settings | memory | subscription | logout） */
  target?: 'settings' | 'memory' | 'subscription' | 'logout'
  /** handoff 专属：已识别的意图 + 需追问的缺失字段 */
  intent?: string
  missing_fields?: string[]
  /** set_theme 专属：目标主题（light / dark / system） */
  mode?: 'light' | 'dark' | 'system'
  /** switch_shop 专属：目标店铺（id 用于前端 shopStore.setCurrentShop） */
  shop?: { id: string; name: string; platform: string } | null
  index?: number
  total?: number
}

export interface SecretaryResponse {
  reply: string
  /** 有序动作列表（如「先选产品，再切 Agent」），前端按顺序执行 */
  actions: SecretaryAction[]
  /** 向后兼容：= actions 最后一个 */
  action: SecretaryAction | null
  tool_calls: string[]
  /** 会话 ID（后端返回，前端持久化后后续请求带回，实现跨会话记忆） */
  session_id?: string | null
}

export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

/**
 * 店秘书对话（全局入口）
 * 后端主 Agent 识别意图：调业务工具出结果，或返回导航/选择动作。
 * history 传本会话历史消息（不含当前 message），用于多轮上下文连贯。
 * session_id 传会话 ID（跨会话记忆，非空时后端从 DB 读历史 + checkpoint 持久化）。
 */
export function chatWithSecretary(data: {
  message: string
  history?: HistoryMessage[]
  session_id?: string | null
}): Promise<SecretaryResponse> {
  return request.post('/orchestrator/chat', data)
}

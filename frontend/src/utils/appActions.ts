/**
 * 全局动作分发器（AI 原生「对话 → 动作」的统一出口）
 *
 * 背景：
 *   店秘书（全局入口 Agent）识别用户意图后，需要能「切 Agent」或「打开资料库视图」。
 *   这类动作本质是前端 SPA 的状态切换，不需要 MCP / 后端 tool-calling——
 *   复用 Workspace 既有的 CustomEvent（view-navigate）与 agentStore.setCurrentAgent 即可。
 *
 * 设计：
 *   - AppAction：动作的联合类型（当前支持 navigate / switch_agent，后续可扩展 apply_to）
 *   - dispatchAppAction()：唯一执行入口，返回是否成功（供调用方决定回复文案）
 *   - 白名单：target 只在已知视图 / 已知 Agent 内匹配，非法目标直接拒绝（防 LLM 幻觉跳转）
 */

import { useAgentStore } from '@/stores/agent'

/** 资料库 / 内容区视图枚举（与 Workspace.currentView 保持一致） */
export type AppView =
  | 'chat'
  | 'faq'
  | 'candidates'
  | 'products'
  | 'assets'
  | 'rules'
  | 'monitor'

/** 视图中文名（用于回复文案 / 日志） */
export const VIEW_LABELS: Record<AppView, string> = {
  chat: '对话',
  faq: '业务话术库',
  candidates: '选品库',
  products: '产品库',
  assets: '营销素材库',
  rules: '平台规则库',
  monitor: '竞品监控看板',
}

/** 可分发动作 */
export type AppAction =
  /** 切换到资料库 / 内容区视图 */
  | { type: 'navigate'; view: AppView }
  /** 切换到某个业务 Agent（留在对话视图） */
  | { type: 'switch_agent'; agentId: string }

/** 合法视图白名单 */
const VALID_VIEWS = new Set<AppView>([
  'chat', 'faq', 'candidates', 'products', 'assets', 'rules', 'monitor',
])

/**
 * 执行一个动作。
 * @returns 是否执行成功（目标非法时返回 false，调用方据此提示用户）
 */
export function dispatchAppAction(action: AppAction): boolean {
  if (action.type === 'navigate') {
    if (!VALID_VIEWS.has(action.view)) {
      console.warn('[actionDispatcher] 非法视图目标:', action.view)
      return false
    }
    // 复用 Workspace 已有的 view-navigate 监听（handleViewNavigate → handleKnowledgeNavigate）
    window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: action.view } }))
    return true
  }

  if (action.type === 'switch_agent') {
    const agentStore = useAgentStore()
    const agent = agentStore.agentList.find(a => a.id === action.agentId)
    if (!agent) {
      console.warn('[actionDispatcher] 未知 Agent:', action.agentId)
      return false
    }
    // 复用 agentStore 既有切换逻辑（同步 chatStore.setActiveAgent + 触发点击计数）
    agentStore.setCurrentAgent(agent)
    return true
  }

  return false
}

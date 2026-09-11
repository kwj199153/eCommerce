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
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useThemeStore } from '@/stores/theme'

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
  /** 选中产品库里的某个产品作为工作商品（并可顺带切到目标 Agent） */
  | { type: 'select_product'; productId: string; agentId?: string }
  /** 打开前端全局 Drawer（设置 / 记忆与进化） */
  | { type: 'open_drawer'; drawer: 'settings' | 'memory' }
  /** 把对话交接给专业 Agent 接管（子 Agent 追问缺失字段后执行） */
  | { type: 'handoff'; agentId: string; intent: string; missingFields: string[] }
  /** 切换界面外观主题 */
  | { type: 'set_theme'; mode: 'light' | 'dark' | 'system' }
  /** 切换当前店铺（数据源） */
  | { type: 'switch_shop'; shopId: string }

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

  if (action.type === 'select_product') {
    const productLibrary = useProductLibraryStore()
    const product = productLibrary.findRowById(action.productId)
    if (!product) {
      console.warn('[actionDispatcher] 未找到产品:', action.productId)
      return false
    }
    // 复用 Workspace 既有的「产品库 → Agent 载入产品」链路：
    // 派发 product-listing-optimize / product-aigc-launch 事件，
    // Workspace 的 launchProductToAgent 会「载入产品 + 切目标 Agent + 切回对话视图」。
    const target = action.agentId || 'listing-generator'
    const eventName = target === 'aigc-media' ? 'product-aigc-launch' : 'product-listing-optimize'
    window.dispatchEvent(new CustomEvent(eventName, { detail: product }))
    return true
  }

  if (action.type === 'open_drawer') {
    // 复用 Workspace 监听的 drawer CustomEvent
    const eventName = `open-${action.drawer}-drawer`
    window.dispatchEvent(new CustomEvent(eventName))
    return true
  }

  if (action.type === 'handoff') {
    // 交接动作：切到目标 Agent，并把「意图 + 缺失字段」作为待追问上下文
    // 交给子 Agent 的对话区渲染追问。这里只做状态切换，追问由 ChatPanel
    // 根据 pending_handoff 渲染。
    const agentStore = useAgentStore()
    const agent = agentStore.agentList.find(a => a.id === action.agentId)
    if (!agent) {
      console.warn('[actionDispatcher] 未知交接目标 Agent:', action.agentId)
      return false
    }
    // 切到目标 Agent
    agentStore.setCurrentAgent(agent)
    // 派发 handoff 事件，由 ChatPanel / 编排层消费，注入追问上下文
    window.dispatchEvent(new CustomEvent('secretary-handoff', {
      detail: {
        agentId: action.agentId,
        intent: action.intent,
        missingFields: action.missingFields,
      },
    }))
    return true
  }

  if (action.type === 'set_theme') {
    // 切换主题：复用 themeStore.setMode（light / dark / system）
    const themeStore = useThemeStore()
    themeStore.setMode(action.mode)
    return true
  }

  return false
}

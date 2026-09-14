/**
 * 全局动作分发器（AI 原生「对话 → 动作」的统一出口）
 *
 * 背景：
 *   店秘书（全局入口 Agent）识别用户意图后，需要能「切 Agent」或「打开资料库视图」。
 *   这类动作本质是前端 SPA 的状态切换，不需要 MCP / 后端 tool-calling——
 *   复用 Workspace 既有的 CustomEvent（view-navigate）与 agentStore.setCurrentAgent 即可。
 *
 * 设计：
 *   - AppAction：动作的联合类型（8 个：navigate / switch_agent / select_product /
 *     open_drawer / account_menu / handoff / set_theme / switch_shop）
 *     ★★ **加新动作必须同时补下面的 dispatchAppAction 分支** —— if 链没有 never 兜底，
 *        tsc 不会检查穷尽性，漏写只在运行时静默 `return false`（曾导致「AI 说已切换店铺、
 *        界面没换」）。自检：`python frontend/scripts/check_app_actions.py`。
 *   - dispatchAppAction()：唯一执行入口，返回是否成功（供调用方决定回复文案）
 *   - 白名单：target 只在已知视图 / 已知 Agent 内匹配，非法目标直接拒绝（防 LLM 幻觉跳转）
 *
 * ★★ 动作的两类依赖，别混：
 *      · **无前置依赖**（navigate / set_theme / switch_shop）—— 只依赖 store 本身，
 *        必须**永远能成功**；任何「还要求别处先加载好」的写法都是脆弱设计。
 *      · **有前置依赖**（switch_agent / select_product 需要列表里存在目标）——
 *        找不到目标即失败并回报，这是合理的。
 *    反面教材：`switch_shop` 曾要求 `shopStore.shops` 已加载（而该列表当时只在
 *    弹层挂载时才拉），造成「没点开过店铺群 → 切店铺被静默丢弃」。
 */

import { useAgentStore } from '@/stores/agent'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useThemeStore } from '@/stores/theme'
import type { ThemeMode } from '@/theme/presets'
import { useUserStore } from '@/stores/user'
import { useShopStore } from '@/stores/shop'
import router from '@/router'

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
  /** 切换到某个业务 Agent（留在对话视图）；query 为老板原话（路由带参，子 Agent 会自动续跑） */
  | { type: 'switch_agent'; agentId: string; query?: string }
  /** 选中产品库里的某个产品作为工作商品（并可顺带切到目标 Agent） */
  | { type: 'select_product'; productId: string; agentId?: string }
  /** 打开前端全局 Drawer（设置 / 记忆与进化） */
  | { type: 'open_drawer'; drawer: 'settings' | 'memory' }
  /** 打开账户菜单项（设置/记忆/订阅/退出登录）——账户类跳转的统一网关 */
  | { type: 'account_menu'; target: 'settings' | 'memory' | 'subscription' | 'logout' }
  /** 把对话交接给专业 Agent 接管（子 Agent 追问缺失字段后执行） */
  | { type: 'handoff'; agentId: string; intent: string; missingFields: string[] }
  /** 切换界面外观主题（模式与可用预设由 @/theme/presets 定义，「跟随系统」也在其中） */
  | { type: 'set_theme'; mode: ThemeMode }
  /**
   * 切换当前店铺（数据源）
   *
   * ★★ `shopId` 是唯一必填项；`shopName` / `platform` 是后端顺带回的轻量信息，
   *    **只用于「取不到店铺时」的提示文案**，不参与选中逻辑。
   *
   * ⚠️ 血泪教训：早期实现要求「`shopStore.shops` 里已存在该 id」才切，导致
   *    「老板没点开过左上角『店铺群』弹层 → 列表为空 → 切换被静默丢弃」。
   *    现在改为**本动作自主保证数据**（列表空则先拉取），不依赖任何外部前置。
   */
  | { type: 'switch_shop'; shopId: string; shopName?: string; platform?: string }

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
    // 路由带参：老板带着具体诉求来 → 切过去后让子 Agent 自动接着干活。
    // 由编排层（useChatOrchestrator）监听 agent-auto-task 事件，
    // 把原话注入子 Agent 对话区并触发它的响应链路。
    if (action.query && action.query.trim()) {
      window.dispatchEvent(new CustomEvent('agent-auto-task', {
        detail: { agentId: action.agentId, query: action.query.trim() },
      }))
    }
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

  if (action.type === 'account_menu') {
    // 账户菜单网关：settings/memory 复用 drawer 事件；subscription 跳路由；logout 登出
    if (action.target === 'settings') {
      window.dispatchEvent(new CustomEvent('open-settings-drawer'))
      return true
    }
    if (action.target === 'memory') {
      window.dispatchEvent(new CustomEvent('open-memory-drawer'))
      return true
    }
    if (action.target === 'subscription') {
      router.push('/subscription')
      return true
    }
    if (action.target === 'logout') {
      useUserStore().logout()
      router.push('/login')
      return true
    }
    return false
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

  if (action.type === 'switch_shop') {
    // 切换当前店铺（数据源）—— 与侧栏「店铺群」点选同一路径（shopStore.setCurrentShop）。
    //
    // ★★ 这里**不要求 `shopStore.shops` 里已有该对象**：
    //    `setCurrentShop` 只需要 id（它内部就只写 `currentShopId` + localStorage），
    //    而 `currentShop` 是 `shops.find(id)` 的 computed —— 只要列表最终加载了，
    //    界面自然跟上。早先版本强求「先 find 到对象」，于是：
    //      · 未点开过「店铺群」弹层 → shops=[] → find 失败 → 切换被静默丢弃
    //      · AI 回复"已切换"、左上角纹丝不动 ⇒ 用户读作"AI 撒谎"
    //    现在改为：**只校验 id 非空**，数据由 ensureShopsLoaded 补齐。
    const shopStore = useShopStore()
    if (!action.shopId) {
      console.warn('[actionDispatcher] switch_shop 缺少 shopId')
      return false
    }
    shopStore.setCurrentShop(action.shopId)
    // 列表为空（未加载）时补拉一次：让左上角店铺名 / `currentShop` 能算出来。
    // 不 await（本函数是同步契约，调用方靠返回值判成败）；失败也不影响切换本身，
    // 因为 currentShopId 已落 localStorage，下次进入照样生效。
    if (shopStore.shops.length === 0) {
      void shopStore.ensureShopsLoaded()
    }
    return true
  }

  return false
}

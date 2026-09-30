/**
 * ChatPanel 编排层 · **装配壳**（第 169 轮 #664「按域拆编排器」）
 *
 * 本文件曾经是 1,744 行 / 91 KB 的巨型闭包：一个 `useChatOrchestrator()` 里塞了
 * 5 个 store、30 个返回值、4 条动作条、9 条 Agent 回复链路（最大的一块叫
 * `simulateAgentResponse`，516 行）。它的对外契约一直很清晰，问题只在**内部没有接缝**：
 *
 *   · 任何一处改动都要在 1,744 行里找落点；
 *   · 4 个 mock 模块（`toolExecutors` / `competitorIntel` / `secretaryBrain` /
 *     `data`）**全部**从这个文件被消费 ⇒ 想退役任何一个都得先动这里；
 *   · `simulateAgentResponse` 这个名字让「真后端链路」和「本地假数据」混在一起，
 *     读者无法判断某条分支到底打不打后端。
 *
 * 现在这里只做**装配**（按依赖顺序把各域拼起来 + 保持对外 30 个返回键一字不变）：
 *
 * ```text
 * useChatRuntime       滚动 / 加载态与看门狗 / meta 回填 / Markdown / 小工具
 * useVoiceAnnounce     语音播报（监听最后一条 assistant 消息）
 * useAgentShortcuts    Agent 判定 + 技能卡动作条（卡片 = 技能，第 189 轮）
 * useAgentReply        发送链路 + 按域分派的 9 条回复链路（chat/replies/**）
 * useChatEventBridge   window 事件桥：handoff / 路由续跑 / tool-analysis
 * useSecretaryPlan     店秘书子任务计划（会话级状态 + 刷新恢复）
 * ```
 *
 * ★ 跨域回调走**稳定 thunk + 装配期回填**（见 `chat/types.ts` 的 `ChatCtx` 注释）：
 *   三个 handler（`handleSend` / `runAgentReply` / `ensureCandidateLoaded`）两两成环，
 *   thunk 让各域仍能直接解构，同时保证**每个 handler 全仓只有一份实现**。
 *
 * ★ 对外契约：`ChatPanel/index.vue` 解构本函数返回的键（**按名字**，不按位置）。
 *   第 169 轮拆分时是 **30 个键**（与拆分前逐字相同）；第 189 轮**有意**收敛为 **23 个** ——
 *   四组硬编码动作条（竞品 3 / 选品 5 / 复盘 4 / 广告 2）合并为「技能卡动作条」：
 *   退场 13 键、进场 6 键。这是老板批准的**功能变更**，不是契约漂移 ⇒
 *   冻结清单已同步登记在 `scripts/check-chat-domain-split.cjs::RETURN_KEYS`（那道门禁
 *   要求逐项相等，正是为了让这种变更必须显式落到两个地方，而不是悄悄漂移）。
 */
import type { ComputedRef } from 'vue'
import { watch } from 'vue'

import type { ChatCtx, ChatOrchestratorOptions, ContextTargetPayload } from './chat/types'
import { useChatRuntime } from './chat/useChatRuntime'
import { useVoiceAnnounce } from './chat/useVoiceAnnounce'
import { useAgentShortcuts } from './chat/useAgentShortcuts'
import { useAgentReply } from './chat/replies'
import { useChatEventBridge } from './chat/useChatEventBridge'
import { useSecretaryPlan } from './chat/useSecretaryPlan'

export type { ChatOrchestratorOptions } from './chat/types'

/**
 * 装配期回填槽：`get` 是**稳定引用**（各域可安全解构），`set` 由装配壳调用。
 * 未回填就被调用 ⇒ 抛错。装配是同步完成的，用户操作必然在其后
 * ⇒ 这个异常只会在「编排顺序写错」时出现 —— 正是我们想立刻知道的那类 bug。
 */
function slot<T extends (...args: any[]) => any>(name: string): { get: T; set: (fn: T) => void } {
  let impl: T | null = null
  const get = ((...args: any[]) => {
    if (!impl) {
      throw new Error(`[编排层] ${name} 在装配完成前被调用 —— 这是编排顺序 bug，不是运行时故障`)
    }
    return (impl as T)(...args)
  }) as T
  return { get, set: (fn: T) => { impl = fn } }
}

/**
 * **值槽**：`slot()` 的兄弟 —— 转发只读引用（`Ref` / `ComputedRef`）而不是函数。
 *
 * ★ 为什么需要它：`contextTarget` 的唯一产地在 ③ `useAgentShortcuts(ctx)`，
 *   而 `ctx` 必须先于 ③ 构造完（它就是 ③ 的入参）⇒ 成环。
 *   `ensureCandidateLoaded` 用 `slot()` 解的是同一个结；`ComputedRef` 不是函数，
 *   转发不了调用，只能转发 `.value`。装配完成前读 ⇒ 抛错（与 `slot()` 的 get 同口径）。
 */
function valueSlot<T>(name: string): { holder: ComputedRef<T>; set: (r: { value: T }) => void } {
  let impl: { value: T } | null = null
  const holder = {
    get value(): T {
      if (!impl) {
        throw new Error(`[编排层] ${name} 在装配完成前被读取 —— 这是编排顺序 bug，不是运行时故障`)
      }
      return impl.value
    },
  } as unknown as ComputedRef<T>
  return { holder, set: (r) => { impl = r } }
}

export function useChatOrchestrator(opts: ChatOrchestratorOptions) {
  // ① 运行时地基：其余各域都要用到它提供的东西（尤其 setLoading / scrollToBottom）
  const runtime = useChatRuntime(opts)

  const sendSlot = slot<ChatCtx['handleSend']>('handleSend')
  const replySlot = slot<ChatCtx['runAgentReply']>('runAgentReply')
  const candSlot = slot<ChatCtx['ensureCandidateLoaded']>('ensureCandidateLoaded')
  // 第 251 轮：本次请求的「作用对象」——唯一产地在 ③ shortcuts，这里只占位（值槽）
  const targetSlot = valueSlot<ContextTargetPayload | null | undefined>('contextTarget')

  const ctx: ChatCtx = {
    ...opts,
    isLoading: runtime.isLoading,
    // 生成流生命周期（第 241 轮：可取消）
    isStreaming: runtime.isStreaming,
    beginStream: runtime.beginStream,
    endStream: runtime.endStream,
    cancelEpoch: runtime.cancelEpoch,
    isCancelledSince: runtime.isCancelledSince,
    loadingStatus: runtime.loadingStatus,
    currentMode: runtime.currentMode,
    selectedTool: runtime.selectedTool,
    setLoading: runtime.setLoading,
    scrollToBottom: runtime.scrollToBottom,
    handleAgentMeta: runtime.handleAgentMeta,
    handleThinkingStep: runtime.handleThinkingStep,
    pendingSkill: runtime.pendingSkill,
    setPendingSkill: runtime.setPendingSkill,
    peekPendingSkill: runtime.peekPendingSkill,
    clearPendingSkill: runtime.clearPendingSkill,
    handleSend: sendSlot.get,
    runAgentReply: replySlot.get,
    ensureCandidateLoaded: candSlot.get,
    contextTarget: targetSlot.holder,
  }

  // ② 语音播报：自己注册 onUnmounted（清理责任与持有责任同处一地）
  useVoiceAnnounce()

  // ③ 动作条：提供 ensureCandidateLoaded（回复链路要用），自身要用 handleSend（稍后回填）
  const shortcuts = useAgentShortcuts(ctx)
  // ★ 值槽回填（同函数槽）：ctx 里那个 contextTarget 只是转发壳，真正的 computed 在这里接上。
  targetSlot.set(shortcuts.contextTarget)

  // ④ 回复链路：发送链路 + 9 条分派；提供 handleSend / runAgentReply
  const reply = useAgentReply(ctx)
  replySlot.set(reply.runAgentReply)
  sendSlot.set(reply.handleSend)
  candSlot.set(shortcuts.ensureCandidateLoaded)

  // ⑤ 事件桥：依赖 ③④，且必须在这两个槽回填之后
  useChatEventBridge(ctx)

  // ⑥ 店秘书计划：内部自带 `watch(activeAgentId, …, { immediate: true })`
  const plan = useSecretaryPlan()

  const { messages, isLoading, isStreaming, loadingTip, inputPlaceholder, removeToolResult,
          handleNavigateTo, renderMarkdown, scrollToBottom, handleCancel } = runtime
  const { secretaryPlan, loadSecretaryPlan } = plan
  const {
    isCompetitorIntelAgent, isProductResearchAgent, isListingAgent, isReviewAgent, isAdAnalyst,
    // 技能卡动作条（第 189 轮）：卡片 = 技能；上下文条参数由 agentScope* 提供
    skillCards, activeSkillCard, runSkillCard,
    periodOptions, agentScopeText, agentScopeColor, agentScopeLabel,
    // 点名可见 chip（第 250 轮）：本轮生效的技能点名 + 用户撤销入口
    pendingSkillCard, dismissPendingSkill, contextTarget,
    scopeTargetLoaded, clearScopeTarget,
  } = shortcuts
  const { handleKeyPress, handleSend } = reply
  watch(messages, () => scrollToBottom(), { deep: true })

  return {
    // 状态
    messages,
    isLoading,
    // 「生成中」只看活跃流，不看 isLoading —— 首 token 到达后 isLoading 已是 false
    isStreaming,
    loadingTip,
    inputPlaceholder,
    // 店秘书计划（第 155 轮）
    secretaryPlan,
    loadSecretaryPlan,
    // Agent 判定
    isCompetitorIntelAgent,
    isProductResearchAgent,
    isListingAgent,
    isReviewAgent,
    isAdAnalyst,
    // 技能卡动作条（第 189 轮：四组硬编码 chip 统一为「读技能列表」）
    skillCards,
    activeSkillCard,
    runSkillCard,
    periodOptions,
    agentScopeText,
    agentScopeColor,
    agentScopeLabel,
    // 消息/输入
    removeToolResult,
    handleNavigateTo,
    renderMarkdown,
    handleKeyPress,
    handleSend,
    // 「停止生成」（第 241 轮）
    handleCancel,
    // 点名可见 chip（第 250 轮：把"点名还在生效"这件事变可见 + 给撤销入口）
    pendingSkillCard,
    dismissPendingSkill,
    // 作用对象的取消入口（第 298 轮 · 老板 bug2；与上面那条同族，同批转发）
    contextTarget,
    scopeTargetLoaded,
    clearScopeTarget,
  }
}

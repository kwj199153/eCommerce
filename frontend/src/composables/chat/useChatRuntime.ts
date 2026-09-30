/**
 * 对话编排层 · 运行时地基（第 169 轮 #664）
 *
 * 这里放**每个域都要用、且必须先存在**的那几样东西：
 *   · 消息列表 / 加载态 / 阶段文案 / 60s 看门狗（`setLoading`）
 *   · tool|chat 模式与当前选中工具（工具执行事件写、右栏读）
 *   · Markdown 渲染器与输入框占位文案
 *   · 滚动到底部、移除某条工具结果、视图跳转
 *   · SSE meta → 结论卡的回填（`handleAgentMeta`）
 *
 * ★ `setLoading` 的看门狗是**唯一一份**实现（60s 未释放就强制复位并给一条可行动提示）。
 *   拆编排器时最怕的就是把它抄成两份 —— 那样两条链路各管一半计时器，
 *   症状是「偶尔卡在 AI 正在思考…」，而单看任一份实现都是对的。
 *
 * ★ 滚动容器取 `mainContentRef` 优先：`.message-list` 自身不滚动
 *   （见 ChatPanel/index.vue 样式注释）。取错的表现是「新消息不自动滚到底」，
 *   而不是报错 —— 这类静默失效只能靠注释把它钉住。
 */
import { ref, computed, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { useRecentResultStore } from '@/stores/recentResult'
import type { ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import type { ThinkingStep } from '@/api/stream'
import type { ChatOrchestratorOptions } from './types'

export function useChatRuntime(opts: ChatOrchestratorOptions) {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const recentResultStore = useRecentResultStore()

  const { messageListRef, mainContentRef } = opts

  /**
   * 会话结论入库（SSE meta 事件）。
   *
   * 一处分发、两处落点：
   * - chatStore：回填最后一条消息的 displayType/data → 消息流里渲染「结论卡」
   * - recentResultStore：按 agentId 存「最近结果」→ 清空对话后仍可从顶部找回
   *
   * 注意 meta 只是**增强**：正文（content）已自带完整结论清单，
   * 后端未下发 meta 时对话照常可读，只是少了卡片承托。
   */
  function handleAgentMeta(meta: { display_type?: string; data?: any }) {
    if (!meta?.display_type) return
    chatStore.setLastMessageResult(meta.display_type, meta.data)
    recentResultStore.setRecent(agentStore.currentAgent?.id || 'default', {
      displayType: meta.display_type,
      data: meta.data,
      summary: meta.data?.summary || '',
    })
  }

  /**
   * 思考过程的一步（SSE `step` 事件）→ 追加到**当前这条** assistant 消息上。
   *
   * ★ 与 `handleAgentMeta` 是**同一个归属口径**（都用 `activeAgentId` 缺省），
   *   因为两者描述的都是「刚刚在跑的这一轮」。
   * ★ 全仓只此一份写入点：5 条回复链路各自拼 `thinkingSteps` 必然会漏掉几条，
   *   而漏了不报错 —— 界面只是少一段过程，没有红灯也没有异常。
   */
  function handleThinkingStep(step: ThinkingStep) {
    chatStore.appendThinkingStep(step)
  }

  /**
   * 卡片点名的技能（**任务级**通道，第 249 轮起不再一次消费即清）。语义见 `chat/types.ts`。
   *
   * ★ 只有三行，但**位置**有意义：它必须与其他运行时状态（`isLoading` / `currentMode`）
   *   同处 runtime —— 因为装配壳按 `runtime → ctx` 的顺序构建 ctx。放到动作条那一层
   *   就变成「动作条写、回复链路读」的跨域直接依赖（本仓明令禁止的形态）。
   */
  const pendingSkill = ref<string | null>(null)
  const setPendingSkill = (name: string | null) => {
    pendingSkill.value = name || null
  }
  /**
   * 取出点名但**不清空**（第 249 轮语义变更）。
   *
   * ★ 为什么不再「消费即清空」：点名的真实生命周期是**一个任务**，而不是一次请求。
   *   `review-action-plan`（行动计划）这类技能的适用条件本身就要求先确认「基于哪份复盘」
   *   ⇒ 第一轮 Agent 追问、第二轮用户回答。旧语义在第一轮就把点名清掉了，
   *   第二轮退化成关键词短路（"基于月报" 命中 `monthly_review`）⇒ **永远拿不到行动计划**。
   *   完整论证见 `chat/types.ts` 的 `peekPendingSkill` 注释。
   *
   * ★ 那第 189 轮担心的「残留点名粘在后续消息上」怎么办：由「本轮产出了结果就清」
   *   + 「切换 Agent 就清」两条覆盖（见 `replies/index.ts` 的 `turnProducedResult`
   *   与 `useAgentShortcuts` 的 watch）。残留窗口从"永久"收窄到"一次追问之内"。
   */
  const peekPendingSkill = (): string | null => pendingSkill.value
  /**
   * 清空点名。
   *
   * ★ **只有两个调用点**：① 回复分派器确认本轮产出了结果（任务结束）；
   *   ② 切换 Agent（点名是按 Agent 生效的技能名，跨 Agent 必然无意义）。
   *   除这两处外不许调用 —— 多一处就等于把「任务级」又改回「一次性」。
   */
  const clearPendingSkill = (): void => {
    pendingSkill.value = null
  }

  // Markdown 渲染器
  const md = new MarkdownIt()

  // 渲染 Markdown
  const renderMarkdown = (content: string) => md.render(content)

  // ========== 状态管理 ==========

  // 当前模式: tool(工具) / chat(对话)
  const currentMode = ref<'tool' | 'chat'>('chat')

  // 当前选中的工具
  const selectedTool = ref<ToolDefinition | null>(null)

  // 工具执行结果通过消息流展示（displayType: 'tool_result'），无需独立状态

  // 消息列表（Pinia 已解包 computed，直接引用即可保持响应式）
  const messages = computed(() => chatStore.messages)

  // 加载状态
  const isLoading = ref(false)

  // 长任务反馈：阶段进度文案（后端 progress 事件驱动）+ 已用秒数（前端计时）
  // 背景：结构化分析（蓝海/竞品/广告诊断等）后端需 15-25s 才能吐出结果，
  // 期间零输出，只显示「AI 正在思考…」会让用户以为卡死。
  const loadingStatus = ref('')
  const elapsedSec = ref(0)
  let elapsedTimer: ReturnType<typeof setInterval> | null = null
  const startElapsedTimer = () => {
    elapsedSec.value = 0
    if (elapsedTimer) clearInterval(elapsedTimer)
    elapsedTimer = setInterval(() => { elapsedSec.value += 1 }, 1000)
  }
  const stopElapsedTimer = () => {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
  }
  /** 加载提示文案：默认「AI 正在思考...」，有阶段进度则用之；超过 3s 追加已用时长 */
  const loadingTip = computed(() => {
    const base = loadingStatus.value || 'AI 正在思考...'
    return isLoading.value && elapsedSec.value >= 3 ? `${base}（已用 ${elapsedSec.value}s）` : base
  })

  // 看门狗：兜底"AI 正在思考…"卡死
  // 任何路径把 isLoading=true 后若 60s 内未释放（流式网络挂起、同步函数异常吞掉等），
  // 强制置 false 并插入一条错误消息，避免用户面对永久 spinner 无可操作。
  const LOADING_WATCHDOG_MS = 60_000
  let loadingWatchdogTimer: ReturnType<typeof setTimeout> | null = null
  const setLoading = (on: boolean, source: string) => {
    isLoading.value = on
    if (on) {
      startElapsedTimer()
      if (loadingWatchdogTimer) clearTimeout(loadingWatchdogTimer)
      loadingWatchdogTimer = setTimeout(() => {
        if (isLoading.value) {
          isLoading.value = false
          loadingWatchdogTimer = null
          stopElapsedTimer()
          console.warn(`[isLoading 看门狗] 60s 未释放（来源：${source}），强制重置`)
          try {
            chatStore.addMessage({
              role: 'assistant',
              content: '⏱️ **请求超时**：超过 60 秒未收到响应，可能是网络异常或后端服务未启动。\n\n请确认：① 后端 `uvicorn main:app --port 8000` 是否运行；② 网络是否可达。点击重试。',
            })
          } catch { /* 兜底中的兜底 */ }
        }
      }, LOADING_WATCHDOG_MS)
    } else {
      stopElapsedTimer()
      loadingStatus.value = ''
      if (loadingWatchdogTimer) {
        clearTimeout(loadingWatchdogTimer)
        loadingWatchdogTimer = null
      }
    }
  }

  // 输入框提示文字
  const inputPlaceholder = computed(() => {
    if (!agentStore.currentAgent) return '请先在左侧选择一个 Agent...'
    return `向 ${agentStore.currentAgent.name} 提问...`
  })

  // ========== 生成流的生命周期（第 241 轮：可取消）==========
  //
  // ★★ 为什么「能不能取消」**不能**看 `isLoading`：
  //   多条链路在**首个 token 到达时**就 `setLoading(false)` 了（spinner 退场），
  //   可流还在跑 —— 那时按 isLoading 判断会得出「已经结束、不能取消」的错误结论，
  //   而用户正对着十几秒的流发呆。能不能取消只由**有没有活跃的流**决定。
  //
  // ★ `liveStreams` 是**数组**而不是单个控制器：既然 isLoading 在首 token 就变 false，
  //   用户完全可以在上一条流还没结束时再发一条（连续发送 / 店秘书路由续跑）。
  //   只留一个控制器的话，新流会把旧流「孤儿化」—— 旧流的 abort 再也打不到它。
  const liveStreams: AbortController[] = []
  const isStreaming = ref(false)

  /**
   * 取消纪元。语义 = 「用户按过几次停止」。
   *
   * 用法（结构化的 axios 调用**没法真正中断**，只能靠它在回来时自我否决）：
   *   `const e0 = ctx.cancelEpoch.value`                  ← await 之前取快照
   *   `if (ctx.isCancelledSince(e0)) return 'handled'`    ← await 之后判
   */
  const cancelEpoch = ref(0)
  const isCancelledSince = (epoch: number) => cancelEpoch.value !== epoch

  /** 开一次生成流：返回本次流的信号（交给 `streamSSE` 的第 4 个参数）。 */
  const beginStream = (): AbortSignal => {
    const ctrl = new AbortController()
    liveStreams.push(ctrl)
    isStreaming.value = true
    return ctrl.signal
  }

  /** 收一次生成流（正常 / 失败 / 取消都走这里）。幂等，且只摘掉自己那一条。 */
  const endStream = (signal: AbortSignal) => {
    const i = liveStreams.findIndex((c) => c.signal === signal)
    if (i >= 0) liveStreams.splice(i, 1)
    isStreaming.value = liveStreams.length > 0
  }

  /**
   * 中止所有活跃流。
   *
   * ★ 同时推进 `cancelEpoch`：`fetch` 能真正中断，但结构化的 axios 请求不能，
   *   后者只能靠纪元在回来时自我否决 —— 否则点了停止，十几秒后答案又冒出来。
   */
  const cancelStream = () => {
    for (const c of liveStreams) c.abort()
    liveStreams.length = 0
    isStreaming.value = false
    cancelEpoch.value++
  }

  /**
   * 「停止生成」按钮的落点。
   *
   * ★ 为什么还要补一次 `setLoading(false)`：结构化调用（广告诊断 / Listing 生成等）
   *   根本没有流可中止，`isLoading` 是它们唯一的「在跑」信号 —— 不退掉的话
   *   按钮会一直停在停止态。晚到的结果由 `cancelEpoch` 挡下。
   */
  const handleCancel = () => {
    cancelStream()
    setLoading(false, 'user-cancel')
  }

  // 从消息流中移除指定工具结果
  const removeToolResult = (index: number) => {
    chatStore.removeMessage(index)
  }

  // 导航到其他视图（产品库/知识库）
  const handleNavigateTo = (view: string) => {
    window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view } }))
  }

  // 滚动到底部
  // 注意：滚动容器是 .main-content（overflow-y:auto），.message-list 自身不滚动
  // （见 index.vue 样式注释「不再独立滚动，随 main-content 一起滚动」）。
  // 因此必须优先取 mainContentRef —— 取 messageListRef 时 scrollTop 设了也没用，
  // 表现为「新消息不自动滚到底」。
  const scrollToBottom = async () => {
    await nextTick()
    const target = mainContentRef.value || messageListRef.value
    if (target) target.scrollTop = target.scrollHeight
  }

  return {
    messages,
    isLoading,
    isStreaming,
    loadingStatus,
    loadingTip,
    inputPlaceholder,
    currentMode,
    selectedTool,
    setLoading,
    scrollToBottom,
    renderMarkdown,
    removeToolResult,
    handleNavigateTo,
    handleAgentMeta,
    handleThinkingStep,
    pendingSkill,
    setPendingSkill,
    peekPendingSkill,
    clearPendingSkill,
    // 生成流生命周期（第 241 轮：可取消）
    beginStream,
    endStream,
    cancelStream,
    cancelEpoch,
    isCancelledSince,
    handleCancel,
  }
}

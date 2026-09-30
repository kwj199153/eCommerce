/**
 * 对话编排层 · window 事件桥（第 169 轮 #664）
 *
 * 三个事件把「别处的意图」接进对话链路：
 *   · `secretary-handoff`   —— 店秘书交接到子 Agent，渲染「接管 + 逐项追问」
 *   · `agent-auto-task`     —— 店秘书路由带参：把老板原话注入子 Agent 并**自动续跑**
 *   · `tool-analysis`       —— 右栏工具卡/动作条发起执行（三条执行路径：
 *                             竞品推理 / 利润测算同源 / `toolExecutors` 派发）
 *
 * ★ 监听与解除必须成对且**在同一处**：`onMounted` / `onUnmounted` 都写在下面，
 *   拆编排器时最容易出的错是把 `removeEventListener` 留在旧文件里
 *   —— 症状是「离开对话视图后事件还在响应」，且不报错。
 *
 * ★ `tool-analysis` 是**四个 mock 的集中消费点之一**（`@/mock/toolExecutors` 的
 *   `getParamSummary` + `toolExecutors` 映射表）：把「取 executor 并派发」换成
 *   直调 `api/**` 之后，#740（退役 toolExecutors）的条件就齐了。
 */
import { onMounted, onUnmounted } from 'vue'
import { message } from 'ant-design-vue'

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { toolExecutors, getParamSummary, TOOL_DATA_SOURCE } from '@/mock/toolExecutors'
import { renderClarification, extractProductName, isDegenerateIntent } from '@/utils/clarification'
import { resolveProfitResult, saveScriptToStore, syncListingDraft } from './toolResultPost'
import { buildResultSummary } from './resultSummary'
import type { ChatCtx } from './types'

/** AIGC 三个工具：大屏模式下结果只进右栏预览，不进对话流。 */
const AIGC_TOOL_IDS = new Set(['static-asset-gen', 'video-script-gen', 'ai-video-generator'])

/** 选品分析师三个工具：大屏模式下结果同样只进右栏结果窗口，不进对话流（第 312 轮对齐 AIGC 范式）。 */
const PRODUCT_RESEARCH_TOOL_IDS = new Set(['market-insight', 'blue-ocean', 'profit-calc'])

/**
 * ★ #745：非真源工具的「演示数据」提示。
 *
 * 为什么必须放在**参数摘要那条消息**上（而不是结果摘要）：
 *   · 参数摘要在执行**之前**就写进对话，用户读完参数即可知道这份结果的性质；
 *   · 它不是「增强」，走的是同一条 `if (!skipChatStream)` 分支，与 `try/catch` 回退同级，
 *     覆盖率与参数摘要完全一致（结果摘要则可能因没有对应 case 而整体缺失）。
 *
 * 判据只读 `TOOL_DATA_SOURCE`（唯一真源），本文件不认识任何具体工具名 ——
 * 谁接真源了，把声明改成 `backend`，这里自动不再标注。
 */
const demoDataNotice = (toolId: string): string => {
  const source = TOOL_DATA_SOURCE[toolId]
  if (!source || source === 'backend') return ''
  return (source === 'backend-then-mock'
    ? '\n\n> ⚠️ **本工具优先走后端真源；后端不可用时会退回本地演示数据**，退回时结果里会带 `source: local-mock` 标记。'
    : '\n\n> ⚠️ **本工具当前返回本地演示数据**（后端接线未完成），**不是店铺真实数据** —— 请勿据此做经营决策。')
}

export function useChatEventBridge(ctx: ChatCtx) {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()

  const { currentMode, selectedTool, setLoading, scrollToBottom, runAgentReply } = ctx

  /**
   * 摘要消息写进对话流。
   * ★ 摘要是**增强**：`buildResultSummary` 抛错不能影响已经拿到的工具结果，
   *   所以调用处包了独立 try/catch（见下），失败只 `console.warn`。
   */
  const addResultSummaryToChat = (toolId: string, result: any) => {
    chatStore.addMessage({ role: 'assistant', content: buildResultSummary(toolId, result) })
  }

  // ========== 监听右侧面板的分析请求 ==========
  onMounted(() => {
    window.addEventListener('tool-analysis', handleToolAnalysisEvent as unknown as EventListener)
    window.addEventListener('secretary-handoff', handleSecretaryHandoff as unknown as EventListener)
    window.addEventListener('agent-auto-task', handleAgentAutoTask as unknown as EventListener)
  })

  onUnmounted(() => {
    window.removeEventListener('tool-analysis', handleToolAnalysisEvent as unknown as EventListener)
    window.removeEventListener('secretary-handoff', handleSecretaryHandoff as unknown as EventListener)
    window.removeEventListener('agent-auto-task', handleAgentAutoTask as unknown as EventListener)
    // 语音停止已搬进 useVoiceAnnounce 自己的 onUnmounted
    // （第 169 轮 #664：speakTailTimer / voiceTts 由那个模块持有，清理责任跟着走）
  })

  // 处理主 Agent 交接：切到子 Agent 后，渲染「待补齐信息 + 逐项追问」。
  //
  // ★ 第 215 轮订正了这一段的语义：这条路径上的追问**不是子 Agent 生成的** ——
  //   它是前端模板把后端传来的 missing_fields 渲染成问题，而 handoff **只切页、
  //   不触发续跑**（要续跑走 `agent-auto-task` ⇒ handleAgentAutoTask）。
  //   订正前它渲染出的样子与「子 Agent 真的读了你的消息后在反问」**完全一样**，
  //   于是老板以为选品分析师读了他的链接却在要 ASIN（实测事故）。修法两条：
  //     ① 消息开头**标明来源**，并明说「子 Agent 还没开始处理这一轮」；
  //     ② 原话（`query`）**回显到对话区**，链接 / ASIN 这类信息不再凭空消失。
  const handleSecretaryHandoff = (event: CustomEvent) => {
    const { agentId, intent, missingFields, query } = event.detail || {}
    if (!agentId) return

    const targetAgent = agentStore.agentList.find(a => a.id === agentId)
    const agentName = targetAgent?.name || agentId

    // 在目标 Agent 对话区渲染「待补齐 + 追问」消息
    chatStore.setActiveAgent(agentId)

    // ★ intent 可能只是一个工具代号（如 `add`）—— 那时它**不是产品名**。
    //   不挡掉就会渲染出「好的，**add** 这事儿我接住了」（实测）。
    const productName = isDegenerateIntent(intent) ? undefined : extractProductName(intent)
    const { greeting, questions } = renderClarification({
      fields: Array.isArray(missingFields) ? missingFields : [],
      productName,
    })

    // 招呼语 + 追问列表
    const questionLines = questions.map(q => {
      const ex = q.examples?.length ? `\n   比如：${q.examples.slice(0, 3).join(' / ')}` : ''
      return `• **${q.label}**：${q.question}${ex}`
    }).join('\n')

    // ★ 来源标注：先说清「这不是子 Agent 说的」，再列问题。
    const sourceNote =
      `> 📋 **由店秘书转交** —— **${agentName} 还没开始处理这一轮**；` +
      `下面几项是它接手前需要补齐的信息。`

    const takeoverMsg = questionLines
      ? `${sourceNote}\n\n${greeting}\n\n${questionLines}\n\n不想挨个说也行，直接给我一段描述，我来拆。`
      : `${sourceNote}\n\n${greeting}`

    // ★ 原话先落地（在追问之前），老板和子 Agent 后续都看得到它。
    const echo = typeof query === 'string' ? query.trim() : ''
    if (echo) {
      chatStore.addMessage({ role: 'user', content: `（店秘书转达）${echo}` }, agentId)
    }

    chatStore.addMessage({
      role: 'assistant',
      content: takeoverMsg,
    }, agentId)
    scrollToBottom()
  }

  // 处理主 Agent「路由带参」：切到子 Agent 后，把老板原话注入它的对话区并自动续跑。
  // 触发方：dispatchAppAction（switch_agent 带 query）→ agent-auto-task 事件。
  const handleAgentAutoTask = async (event: CustomEvent) => {
    const { agentId, query } = event.detail || {}
    if (!agentId || !query) return

    // 确保对话区路由到目标 Agent（switch_agent 已切过，这里幂等兜底）
    chatStore.setActiveAgent(agentId)

    // 回显老板原话（标注来源，便于追溯），再让子 Agent 接着执行
    chatStore.addMessage({ role: 'user', content: `（店秘书转达）${query}` }, agentId)
    await scrollToBottom()

    setLoading(true, 'agent-auto-task')
    try {
      // 此时 agentStore.currentAgent 已是子 Agent，simulateAgentResponse 会分流到它自己的链路
      await runAgentReply(query)
    } catch (e) {
      console.error('[路由续跑] 子 Agent 执行失败:', e)
      chatStore.addMessage({ role: 'assistant', content: '（子 Agent 执行失败，请稍后重试）' }, agentId)
    } finally {
      setLoading(false, 'agent-auto-task-finally')
      await scrollToBottom()
    }
  }

  // 处理来自右侧面板的分析请求
  const handleToolAnalysisEvent = async (event: CustomEvent) => {
    const { tool, params, mode } = event.detail

    if (!tool) return

    // 大屏模式：结果只在右侧结果窗口显示，不进对话流（避免对话区和大屏结果冗余）。
    // AIGC 与选品分析师三个工具同范式：AIGC 派发 aigc-*，选品派发 product-research-*。
    const skipChatStream = mode === 'data' && (AIGC_TOOL_IDS.has(tool.id) || PRODUCT_RESEARCH_TOOL_IDS.has(tool.id))
    // 结果事件通道按工具族分流：AIGC 走 aigc-*，选品走 product-research-*（右栏各自监听）。
    const isProductResearch = PRODUCT_RESEARCH_TOOL_IDS.has(tool.id)

    // 设置当前工具状态
    selectedTool.value = { ...tool }
    currentMode.value = 'tool'
    // 大屏模式：loading 交给右栏结果窗口展示。
    // 结果不进对话流，若仍在对话区转圈，用户会以为卡在了一个没有输出的地方。
    if (skipChatStream) {
      window.dispatchEvent(new CustomEvent(isProductResearch ? 'product-research-generating' : 'aigc-generating', {
        detail: { toolId: tool.id, generating: true }
      }))
    } else {
      setLoading(true, 'tool-click')
    }

    // ===== 步骤1：添加用户消息（独立 try-catch）=====
    // AIGC 大屏模式：跳过对话流，结果直接展示在右侧预览区
    if (!skipChatStream) {
      try {
        const paramSummary = getParamSummary(tool.id, params || {})
        chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${paramSummary}${demoDataNotice(tool.id)}` })
      } catch (msgError) {
        console.warn('参数摘要生成失败（使用 fallback）:', msgError)
        chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${JSON.stringify(params || {}, null, 2)}${demoDataNotice(tool.id)}` })
      }
    }

    // ===== 步骤2：执行分析（主 try-catch）=====
    try {
      // 利润测算：与右栏面板同源。面板已经调后端算过一份就原样沿用，
      // 绝不在前端用另一套公式复算 —— 「一个表单两个结果」就是这么来的。
      let result: any
      if (tool.id === 'profit-calc') {
        result = await resolveProfitResult(params)
      } else {
        const executor = toolExecutors[tool.id]
        if (!executor) {
          throw new Error(`未知工具: ${tool.id}`)
        }
        result = await executor(params)
      }

      // 视频脚本同步到共享 store（供 AI 短视频生成「分镜脚本专业模式」复用）
      if (tool.id === 'video-script-gen') {
        saveScriptToStore(result)
      }

      // Listing 工具结果同步到「Listing 工作区」草稿（右侧面板可直接接着编辑/保存）
      syncListingDraft(tool.id, params, result)

      // ===== 步骤3：将结果插入对话流（或大屏下直接派发给右栏结果窗口）=====
      if (skipChatStream) {
        // 大屏模式：直接广播给右栏结果窗口，不经对话流（避免对话区与大屏结果冗余）
        window.dispatchEvent(new CustomEvent(isProductResearch ? 'product-research-result-ready' : 'aigc-result-ready', {
          detail: { toolId: tool.id, result }
        }))
      } else {
        chatStore.addMessage({
          role: 'assistant',
          content: '',
          displayType: 'tool_result',
          data: {
            toolId: tool.id,
            toolName: tool.name,
            resultData: result,
          },
        })

        // 摘要消息（独立 try-catch，防止摘要生成错误导致主流程报错）
        try {
          addResultSummaryToChat(tool.id, result)
        } catch (summaryError) {
          console.warn('结果摘要生成失败（不影响主结果）:', summaryError)
        }
      }

    } catch (error: unknown) {
      const err = error as Error
      console.error('=== 工具执行失败详情 ===')
      console.error('工具 ID:', tool?.id)
      console.error('错误类型:', err?.constructor?.name)
      console.error('错误消息:', err?.message)
      console.error('接收到的 params:', JSON.stringify(params || {}))
      console.error('错误堆栈:', err?.stack)
      console.error('========================')
      if (skipChatStream) {
        // 大屏模式：失败提示走顶部 toast，不污染对话流
        message.error(`❌ ${tool.name} 执行失败：${err?.message || '未知错误'}`)
      } else {
        chatStore.addMessage({
          role: 'assistant',
          content: `❌ 分析执行失败，请检查参数后重试。\n\n\`${err?.message || '未知错误'}\``,
        })
      }
    } finally {
      // 大屏模式：收掉结果窗口 loading（setLoading(false) 此时幂等无害，保留兜底）
      if (skipChatStream) {
        window.dispatchEvent(new CustomEvent(isProductResearch ? 'product-research-generating' : 'aigc-generating', {
          detail: { toolId: tool.id, generating: false }
        }))
      }
      setLoading(false, 'tool-click-finally2')
      await scrollToBottom()
    }
  }
}

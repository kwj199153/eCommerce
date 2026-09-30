/**
 * 回复链路 · 广告分析师
 *
 * 两个结构化意图（诊断 / 搜索词）各走自己的端点；都不是才走 SSE 文本对话。
 * ★ 第 316 轮：原第三个「异常检测」分支已随该能力整条退役
 *   （老板「广告分析师删除异常检测、广告预算再平衡」）。
 *
 * ★ 诊断分支刻意复用 `tool_result` 这张**工具结果卡**（`toolId: 'ad-diagnosis'`）：
 *   原先给的是自定义 `displayType: 'ad_diagnosis'`，而结果卡分派只认 `msg.data?.toolId`
 *   ⇒ 那个 displayType **全仓没有任何渲染分支**，metrics/campaigns/top_issues 一直渲染不出来，
 *   用户只看得到一行 summary —— 「接线了但没渲染」比纯 mock 更隐蔽。
 *
 * ★ 第 221 轮（失败路径统一，与 listing / customerService / productResearch 同款）：
 *   ① `onError` 只记录、不写文案（`streamSSE` 抛错前会先调它 ⇒ 会叠成两条矛盾文案）；
 *   ② 流式失败降级到 `/ad-analysis/chat`（`chatWithAdAnalyst` —— 它此前**被 import
 *      却从未被调用**，`noUnusedLocals=false` 所以没人发现「降级链路半截」）；
 *   ③ 都失败 ⇒ 如实上报（HTTP 状态码 + 后端 `detail`）并 `return 'handled'` 就地终止，
 *      不再落回 `fallthrough` 让兜底再补一句「这次没有返回结果」。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { describeChatFailure } from '../chatFailure'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ReplyOutcome } from '../types'

/** 失败文案的业务名（`⚠️ <label>失败…`）。 */
const LABEL = '广告分析请求'

/** 本文件的 store 类型（`useChatStore()` 的返回）。 */
type ChatStore = ReturnType<typeof useChatStore>

/**
 * 非流式降级：**再试一次** `/ad-analysis/chat`；仍失败则如实上报并 `return 'handled'`。
 *
 * ★ 为什么这里能用 `chatWithAdAnalyst`：它就是本文件一直 `import` 却**从未调用**的那个函数
 *   （`tsconfig.json` 的 `noUnusedLocals` 是 false，所以没报错）——
 *   也就是说「流式失败 → 非流式降级」这条链路此前是**半截的**：降级函数备好了，没人接。
 *
 * @param reusePlaceholder 同上：流式那条路有空的占位消息，结构化那条路没有。
 */
async function degradeAdText(
  chatStore: ChatStore,
  userMessage: string,
  skill: string | null,
  transportError: unknown,
  reusePlaceholder: boolean,
): Promise<ReplyOutcome> {
  try {
    const { chatWithAdAnalyst } = await import('@/api/adAnalysis')
    // ★ 后端 `ad_analysis/router.py::chat` 回的是 `ApiResponse(success, message, data)`，
    //   业务字段在**信封的 `data` 里**：`{reply, data, display_type, suggestions}`。
    const env: any = await chatWithAdAnalyst({ message: userMessage, skill: skill ?? undefined })
    const d = env?.data ?? env
    const content = d?.reply || d?.response || d?.summary || '分析完成'
    const displayType = d?.display_type || 'text'
    if (reusePlaceholder) {
      chatStore.appendToLastMessage(content)
      chatStore.setLastMessageResult(displayType, d?.data ?? d)
    } else {
      chatStore.addMessage({ role: 'assistant', content, data: d?.data ?? d, displayType })
    }
    return 'handled'
  } catch (retryError) {
    const text = describeChatFailure(LABEL, retryError, transportError)
    if (reusePlaceholder) chatStore.setLastMessageContent(text)
    else chatStore.addMessage({ role: 'assistant', content: text })
    return 'handled'
  }
}

/**
 * @param skill 点卡的技能名（`skills.name`）。没点卡时为 `null` ⇒ 不带该字段。
 *              只作用于**文本对话**那条链（两个结构化意图端点不接受 skill）。
 */
export async function replyAdAnalysis(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadingStatus, setLoading, handleAgentMeta, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince } = ctx

    // 广告分析师
    if (agentStore.currentAgent?.id === 'ad-analysis') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      try {
        const { diagnoseAdAccount, analyzeSearchTerms } = await import('@/api/adAnalysis')
        const { streamSSE } = await import('@/api/stream')

        // 判断是否是特定功能请求
        const isDiagnosis = /诊断|体检|健康|状况/.test(userMessage)
        const isSearchTerms = /搜索词|词报告|关键词|search term/.test(userMessage)

        let response: any

        if (isDiagnosis) {
          response = await diagnoseAdAccount({ time_range: '30d' })
          response = response.data
        } else if (isSearchTerms) {
          response = await analyzeSearchTerms({})
          response = response.data
        }

        if (response) {
          // ★ 用户在等待期间点了「停止生成」⇒ 结构化请求拦不住，但结果不许再上屏
          if (isCancelledSince(epoch0)) return 'handled'
          // 结构化结果：一次性渲染 + 落右栏
          // ★ P0-2 批 1 修正：原来 isDiagnosis 给的是 `displayType: 'ad_diagnosis'`，
          //   但 ChatPanel 的结果卡分派只认 `msg.data?.toolId` ⇒ 该 displayType
          //   **全仓没有任何渲染分支** ⇒ metrics / campaigns / top_issues 其实一直渲染不出来，
          //   用户只看得到一行 summary（「接线了但没渲染」比纯 mock 更隐蔽）。
          //   现改为与工具卡**共用同一个结果卡**，两个入口同一份真数据。
          chatStore.addMessage({
            role: 'assistant',
            content: response.reply || response.summary || '分析完成',
            data: isDiagnosis
              ? { toolId: 'ad-diagnosis', toolName: '广告诊断', resultData: response }
              : (response.data || response),
            displayType: isDiagnosis ? 'tool_result' : (response.display_type || undefined),
          })
          return 'handled'
        }

        // 纯文本对话：SSE 流式渲染
        // ★ 取消若发生在上面的 await 期间 ⇒ 连占位气泡都别建（建了也没人收）
        if (isCancelledSince(epoch0)) return 'handled'
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        const signal = beginStream()
        try {
          await streamSSE('/ad-analysis/chat/stream', { message: userMessage, skill: skill ?? undefined }, {
            onProgress: (text) => { loadingStatus.value = text },
            onMeta: handleAgentMeta,
            onStep: handleThinkingStep,
            onDelta: (text) => {
              streamed = true
              setLoading(false, 'sse-delta-ad')
              chatStore.appendToLastMessage(text)
            },
            // ★ 只记录、不写文案（第 221 轮）：`streamSSE` 抛错前会先调一次 `onError`，
            //   此处再 append 就会与下方 catch 的说明合成**两条互相矛盾**的失败文案。
            onError: () => {},
          }, { signal })
          return 'handled'
        } catch (streamError) {
          // ★ 用户取消 ≠ 失败：不写失败文案、更不发非流式重试（那会把答案又补回来）
          if (absorbStreamCancel(chatStore, streamed, streamError)) return 'handled'
          // 已输出过部分正文 ⇒ 保留它，既不追加全文、也不追加失败文案（避免重复）
          if (streamed) return 'handled'
          return await degradeAdText(chatStore, userMessage, skill, streamError, true)
        } finally {
          endStream(signal)
        }
      } catch (error) {
        console.error('广告分析 API 失败:', error)
        // 模块加载失败 / 三个结构化意图端点失败 ⇒ 同样走非流式降级；再失败就如实上报。
        // ★ 旧实现在这里只 `console.error` 然后落回 `return 'fallthrough'` ——
        //   用户看到的是兜底那句「⚠️ 广告分析师 这次没有返回结果」，看不到**真实原因**。
        return await degradeAdText(chatStore, userMessage, skill, error, false)
      }
    }
  // 本分支没接住（**当前 Agent 与分支不匹配**）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

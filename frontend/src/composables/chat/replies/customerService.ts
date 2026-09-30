/**
 * 回复链路 · 智能客服
 *
 * 订单追踪与工单创建走结构化出参（**注意：这两个响应都没有 `data` 字段**，
 * 原实现写 `response = response.data` 导致该分支恒不执行 —— 已修，别改回去），
 * 其余走 SSE 文本对话。
 *
 * ★ 第 221 轮（失败路径统一，与 listing / adAnalysis / productResearch 同款）：
 *   ① `onError` 只记录、不写文案（`streamSSE` 抛错前会先调它 ⇒ 会叠成两条矛盾文案）；
 *   ② 流式失败降级到 `/customer-service/chat`（`chatWithCustomerService` —— 它此前
 *      **被 import 却从未被调用**，`noUnusedLocals=false` 所以没人发现「降级链路半截」）；
 *   ③ 都失败 ⇒ 如实上报（HTTP 状态码 + 后端 `detail`）并 `return 'handled'` 就地终止，
 *      不再落回 `fallthrough` 让兜底再补一句「这次没有返回结果」。
 *
 * ★ 第 298 轮：两条**文本对话**路径（SSE + 非流式降级）都要带 `context_target`。
 *   它是「本次处置哪条差评」的结构化事实（与选品 / Listing / AIGC 同一条通道）。
 *   只补一条的后果不是"少个字段"：另一条链路上模型只能从会话历史里挑一条顶上，
 *   而那正是第 250 轮那个洞的形状。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { describeChatFailure } from '../chatFailure'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ContextTargetPayload, ReplyOutcome } from '../types'
import { renderOrderTrackingText } from '@/utils/orderTracking'

/** 失败文案的业务名（`⚠️ <label>失败…`）。 */
const LABEL = '客服请求'

/** 本文件的 store 类型（`useChatStore()` 的返回）。 */
type ChatStore = ReturnType<typeof useChatStore>

/**
 * 非流式降级：**再试一次** `/customer-service/chat`；仍失败则如实上报并 `return 'handled'`。
 *
 * ★ 与广告那条链同款：`chatWithCustomerService` 也是本文件一直 `import` 却**从未调用**的函数
 *   ⇒ 「流式失败 → 非流式降级」此前是半截链路。第 221 轮把它接上。
 *
 * @param reusePlaceholder 同上：流式那条路有空的占位消息，结构化那条路没有 ——
 *   搞反了会**覆盖掉用户刚发的那条提问**。
 */
async function degradeCsText(
  chatStore: ChatStore,
  userMessage: string,
  skill: string | null,
  // ★ 第 298 轮：作用对象必须**显式传进来** —— 本函数是模块级函数、拿不到 ctx。
  contextTarget: ContextTargetPayload | null | undefined,
  transportError: unknown,
  reusePlaceholder: boolean,
): Promise<ReplyOutcome> {
  try {
    const { chatWithCustomerService } = await import('@/api/customerService')
    // ★ 后端 `customer_service/router.py::chat_endpoint` 回的是
    //   `ApiResponse(data={reply, conversation_id, intent, sentiment, display_type, data, ...})`
    //   ⇒ 业务字段在**信封的 `data` 里**（`api/customerService.ts` 上那个 `Promise<ChatResult>`
    //   注解只描述了信封内部的形状，不是拦截器交回来的东西 —— 别照它取 `.reply`）。
    // ★ 第 298 轮：降级路径**同样要带** `context_target` —— 否则
    //   「在台账里选了差评、点了卡但流式失败」时，模型手里没有对象，
    //   只能从会话历史里挑一条（第 250 轮那个洞换个入口复现）。
    //   ★ 原值**原样**透传，别写 `?? undefined` —— 那会把 `null`（明确没有）
    //     压成「字段不出现」（不参与），三态变两态。
    const env: any = await chatWithCustomerService({
      message: userMessage,
      skill: skill ?? undefined,
      context_target: contextTarget,
    })
    const d = env?.data ?? env
    const content = d?.reply || d?.message || '处理完成'
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
 *              只作用于**文本对话**那条链（订单/工单两个结构化端点不接受 skill）。
 */
export async function replyCustomerService(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadingStatus, setLoading, handleAgentMeta, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince } = ctx

    // 智能客服
    if (agentStore.currentAgent?.id === 'customer-service') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      try {
        const { trackOrder, createTicket } = await import('@/api/customerService')
        const { streamSSE } = await import('@/api/stream')

        // 判断是否是订单追踪
        const isOrderTrack = /订单|order|物流|tracking|到哪里/.test(userMessage)
        // 判断是否是工单创建
        const isTicketCreate = /工单|投诉|问题|ticket|创建/.test(userMessage)

        let response: any

        if (isOrderTrack) {
          // ★ 订单号正则必须含 Amazon **真实**格式（112-1234567-8901234）。
          //   旧正则只认本项目自己编的 `ORD-` 格式 ⇒ 用户粘贴真实订单号时
          //   提取不到，order_id 传 undefined，后端再拿邮箱 hash 编一个号去查
          //   （已修，但正则不补上这条链路依然走不通）。
          const orderMatch = userMessage.match(/(\d{3}-\d{7}-\d{7})|(ORD[-–]?\d{8,})|(\d{10,})/i)
          const orderId = orderMatch ? orderMatch[0] : undefined
          const payload: any = await trackOrder({ order_id: orderId })
          // ★ 原实现写的是 `response = response.data`，但
          //   `OrderTrackResponse` 是 `{found, order, message}` —— **没有 data 字段**
          //   ⇒ response 恒为 undefined ⇒ `if (response)` 恒假 ⇒
          //   「结构化结果一次性渲染 + 落右栏」这条分支**从来没走过**（静默落到 SSE）。
          response = {
            reply: renderOrderTrackingText(payload),
            data: payload,
            display_type: 'text',
          }
        } else if (isTicketCreate) {
          // ★ 同一个形状 bug：`TicketResponse` 也没有 `data` 字段
          const payload: any = await createTicket({
            subject: userMessage.slice(0, 50),
            description: userMessage,
            category: 'general',
          })
          const tkt = payload?.ticket
          response = {
            reply: (payload?.success ? '🎫 **工单创建成功**\n\n' : '🎫 **工单未能创建**\n\n') +
              (tkt ? `- 工单号：**${tkt.ticket_id}**\n- 标题：${tkt.subject}\n- 优先级：${tkt.priority || '—'}\n` : '') +
              `\n${payload?.message || ''}`,
            data: payload,
            display_type: 'text',
          }
        }

        if (response) {
          // ★ 用户在等待期间点了「停止生成」⇒ 结构化请求拦不住，但结果不许再上屏
          if (isCancelledSince(epoch0)) return 'handled'
          // 结构化结果（订单/工单）：一次性渲染 + 落右栏
          chatStore.addMessage({
            role: 'assistant',
            content: response.reply || response.message || '处理完成',
            data: response.data || response,
            displayType: response.display_type || 'text',
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
          await streamSSE('/customer-service/chat/stream', {
            message: userMessage,
            skill: skill ?? undefined,
            // ★ 第 298 轮：结构化「作用对象」。差评应对技能第 0 步是
            //   `get_customer_review_context(review_id)`，此前这个 id 只能从
            //   用户消息文本或**会话历史**里来 —— 台账里明明选中了某条，
            //   对话却只能靠模型自己猜（界面还写着「在对话里直接问」）。
            context_target: ctx.contextTarget.value,
          }, {
            onProgress: (text) => { loadingStatus.value = text },
            onMeta: handleAgentMeta,
            onStep: handleThinkingStep,
            onDelta: (text) => {
              streamed = true
              setLoading(false, 'sse-delta-cs')
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
          return await degradeCsText(
            chatStore, userMessage, skill, ctx.contextTarget.value, streamError, true,
          )
        } finally {
          endStream(signal)
        }
      } catch (error) {
        console.error('客服 API 失败:', error)
        // 模块加载失败 / 订单、工单两个结构化端点失败 ⇒ 同样走非流式降级；再失败就如实上报。
        // ★ 旧实现在这里只 `console.error` 然后落回 `return 'fallthrough'` ——
        //   用户看到的是兜底那句「⚠️ 智能客服 这次没有返回结果」，看不到**真实原因**。
        return await degradeCsText(
          chatStore, userMessage, skill, ctx.contextTarget.value, error, false,
        )
      }
    }
  // 本分支没接住（**当前 Agent 与分支不匹配**）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

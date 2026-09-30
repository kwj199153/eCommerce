/**
 * 回复链路 · Listing 优化师
 *
 * 先按关键词判定「是不是要生成整套 Listing」：是 → 走结构化 `/listing/generate`（结果落右栏）；
 * 否则走 `/listing/chat/stream` 打字机渲染。流式失败降级到非流式对话。
 *
 * ★ 第 221 轮（失败路径统一，与 productResearch / adAnalysis / customerService 同款）：
 *   ① `onError` **只记录、不写文案** —— `streamSSE` 在抛错前会先调一次 `onError`，
 *      此处再 append 就会与下方 catch 的说明合成**两条互相矛盾**的失败文案；
 *   ② 流式 + 非流式**都**失败 ⇒ 如实上报真实原因（HTTP 状态码 + 后端 `detail`），
 *      并 `return 'handled'` **就地终止**。旧实现只 `console.error` 然后落回文件末尾的
 *      `return 'fallthrough'`，于是降级链又补一句「⚠️ Listing 优化师 这次没有返回结果」
 *      —— 用户同时看到两条说明（`replies/index.ts` 文件头登记的历史疙瘩，本轮消掉）；
 *   ③ 失败文案的实现收口到 `chatFailure.describeChatFailure`（唯一实现）。
 *
 * ★ 第 257 轮：文本对话那两条路（流式 + 非流式降级）都带上结构化「作用对象」
 *   （`ctx.contextTarget`）。此前本 Agent 的对话链路只能靠后端
 *   `_extract_product_info(query, …)` 从**用户消息文本**里抽品名 ——
 *   用户在顶部【载入产品】选好了商品、然后只说「帮我优化标题」时，模型只能猜。
 *   ★ **两条路都要带**：只带流式那条的话，一次网络抖动就会把
 *     「载入了商品」退化成「猜哪个商品」—— 基础设施故障被转译成业务结论。
 *   ★ AIGC 同批接了这个字段的**产出与上下文条**，但它目前没有对话链路
 *     （见 `replies/fallback.ts` 的说明），所以只有本文件有请求体落点。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { describeChatFailure } from '../chatFailure'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ContextTargetPayload, ReplyOutcome } from '../types'

/** 失败文案的业务名（`⚠️ <label>失败…`）。 */
const LABEL = 'Listing 生成请求'

/** 本文件的 store 类型（`useChatStore()` 的返回）。 */
type ChatStore = ReturnType<typeof useChatStore>

/**
 * 非流式降级：流式失败（或结构化生成失败）后**再试一次** `/listing/chat`；
 * 仍失败则如实上报真实原因，并 `return 'handled'` **就地终止**。
 *
 * @param reusePlaceholder 调用前是否已经 append 过一条**空的 assistant 占位消息**。
 *   · `true`（流式那条路）⇒ 结果 / 失败文案都写在那条占位消息上，不让界面多出一条空消息；
 *   · `false`（结构化那条路，压根没有占位消息）⇒ 必须 `addMessage` ——
 *     否则 `setLastMessageContent` 会**覆盖掉用户刚发的那条提问**，消息区直接错乱。
 * @param target 本次请求的「作用对象」（第 257 轮）。**降级路径同样要带** ——
 *   否则「载入了商品但流式失败」时，后端只能从用户消息文本里抽品名，
 *   一次网络抖动就退化成"猜哪个商品"（归因错方向的翻版）。
 */
async function degradeListingText(
  chatStore: ChatStore,
  userMessage: string,
  skill: string | null,
  target: ContextTargetPayload | null | undefined,
  transportError: unknown,
  reusePlaceholder: boolean,
): Promise<ReplyOutcome> {
  try {
    const { chatWithListingAgent } = await import('@/api/listingGenerator')
    // ★ 本仓口径（`api/request.ts` 的响应拦截器 `return data`）：它返回的是**整个信封**
    //   `{ success, message, data }`，不是 `res.data.data` ⇒ 业务载荷在 `.data`。
    const env: any = await chatWithListingAgent({
      message: userMessage,
      skill: skill ?? undefined,
      // `undefined`（本 Agent 不参与）会被 JSON 丢掉 ⇒ 字段不出现；
      // `null` 则**显式下发**，两者含义不同（见 `ChatCtx.contextTarget`）。
      context_target: target,
    })
    const d = env?.data ?? env
    const content = d?.summary || d?.response || '完成'
    const displayType = d?.display_type || d?.type || 'text'
    if (reusePlaceholder) {
      chatStore.appendToLastMessage(content)
      chatStore.setLastMessageResult(displayType, d)
    } else {
      chatStore.addMessage({ role: 'assistant', content, data: d, displayType })
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
 *              只作用于**文本对话**那条链（`/generate` 结构化端点不接受 skill）。
 */
export async function replyListing(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadingStatus, setLoading, handleAgentMeta, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince, contextTarget } = ctx

    // Listing 优化师
    if (agentStore.currentAgent?.id === 'listing-generator') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      try {
        const { generateListing } = await import('@/api/listingGenerator')
        const { streamSSE } = await import('@/api/stream')
        const isGenerateRequest =
          userMessage.includes('生成') || userMessage.includes('写') ||
          userMessage.includes('创建') || userMessage.toLowerCase().includes('generate')

        // 完整 Listing 生成走结构化接口（结果落右栏）
        if (isGenerateRequest) {
          let response: any = await generateListing({
            product_name: userMessage.replace(/生成|写|创建|listing|Listing/gi, '').trim() || 'New Product',
            generate_ab_variants: false,
          })
          response = response.data
          // ★ 用户在等待期间点了「停止生成」⇒ 结构化请求拦不住，但结果不许再上屏
          if (isCancelledSince(epoch0)) return 'handled'

          chatStore.addMessage({
            role: 'assistant',
            content: response.summary || response.response || '完成',
            data: response,
            displayType: response.type || 'complete_listing',
          })
          return 'handled'
        }

        // 文本类对话：SSE 流式渲染（打字机效果）
        // ★ 取消若发生在上面的 await 期间 ⇒ 连占位气泡都别建（建了也没人收）
        if (isCancelledSince(epoch0)) return 'handled'
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        const signal = beginStream()
        try {
          await streamSSE('/listing/chat/stream', {
            message: userMessage,
            skill: skill ?? undefined,
            // ★ 第 257 轮：结构化「作用对象」。本 Agent 的对话链路此前只能靠
            //   `_extract_product_info(query, …)` 从**用户消息文本**里抽品名 ——
            //   用户在顶部【载入产品】选好了商品、然后只说「帮我优化标题」时，
            //   模型只能猜，而猜错的结论打在别的品上时界面/日志/测试全绿。
            context_target: contextTarget.value,
          }, {
            onProgress: (text) => { loadingStatus.value = text },
            onMeta: handleAgentMeta,
            onStep: handleThinkingStep,
            onDelta: (text) => {
              streamed = true
              setLoading(false, 'sse-delta-listing')  // 首 token 到达即隐藏"思考中"spinner
              chatStore.appendToLastMessage(text)
            },
            // ★ 只记录、不写文案（第 221 轮）：`streamSSE` 在抛错前会先调一次 `onError`，
            //   此处再 append 就会与下方 catch 的说明合成**两条互相矛盾**的失败文案。
            onError: () => {},
          }, { signal })
          return 'handled'
        } catch (streamError) {
          // ★ 用户取消 ≠ 失败：不写失败文案、更不发非流式重试（那会把答案又补回来）
          if (absorbStreamCancel(chatStore, streamed, streamError)) return 'handled'
          // 已输出过部分正文 ⇒ 保留它，既不追加全文、也不追加失败文案（避免重复）
          if (streamed) return 'handled'
          return await degradeListingText(chatStore, userMessage, skill, contextTarget.value, streamError, true)
        } finally {
          endStream(signal)
        }
      } catch (error) {
        console.error('Listing API 失败:', error)
        // 模块加载失败 / 结构化生成失败 ⇒ 同样走非流式降级；再失败就如实上报。
        // ★ **不许**落回文件末尾的 `return 'fallthrough'` —— 那会让兜底再补一条伪成功文案。
        return await degradeListingText(chatStore, userMessage, skill, contextTarget.value, error, false)
      }
    }
  // 本分支没接住（**当前 Agent 与分支不匹配**）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

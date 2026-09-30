/**
 * 回复链路 · 选品分析师（真后端 + SSE 流式）
 *
 * 结构化结果（蓝海/利润等）由后端在 `done` 之前通过 meta 推送；流式失败降级到非流式，
 * 且降级路径**同样要回填 `display_type`/`data`** —— 否则后端那句
 * 「请选择『批准』或『拒绝』」会变成一句没有按钮可点的指令（比不显示更糟）。
 *
 * ★ 第 219 轮（老板报「选品分析师回复成了兜底文案」后重写失败路径）：
 *   旧实现在流式失败时只 `console.error` 然后落回末尾的 `return 'fallthrough'`，
 *   于是降级链又跑了一趟 `replyCandidateSnapshot` → `replyFallback`，用户同时收到
 *   `（对话失败，请重试）` 与 `收到：「…」我是 选品分析师，正在为您分析...` ——
 *   后者是**伪装成成功的失败**（看不出这是失败）。
 *   现在：拿不到结果就**如实说**（带 HTTP 状态码与后端 `detail`），并 `return 'handled'` 就地终止。
 *   同款处理见 `competitorIntel.ts`（竞品分支早前已这么修）与 `review.ts`。
 *
 * ★ 第 221 轮：Listing / 广告 / 客服三条链**同款缺陷已一并修掉**（老板拍板「一并修」），
 *   失败文案的实现同时收口到 `composables/chat/chatFailure.ts`（唯一实现）。
 *   判据从单链扩成四条链 × 五个场景：`scripts/check-chat-failure-path.cjs`。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { describeChatFailure } from '../chatFailure'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ReplyOutcome } from '../types'

/**
 * ★ 第 221 轮：失败文案的**实现**已收口到 `chatFailure.describeChatFailure`（唯一实现）。
 *
 * 为什么不是「就地改一改」：同一段逻辑此前在四条回复链里各写了一份，而**只有本文件
 * 这一份是「如实说」**—— 另外三条（Listing / 广告 / 客服）失败后只 `console.error`
 * 再落回 `return 'fallthrough'`，于是降级链又补一句伪成功文案。
 * 「同一判定两份实现 ⇒ 至少一份永远测不到」是本仓反复踩过的形态。
 *
 * 口径不变（为什么**不写**「（对话失败，请重试）」）：配额耗尽（429）与网络抖动在界面上
 * 完全同形，用户只能反复重试；后端 `detail` 里给的是**可解释的业务结论**，原样透出才有
 * 可操作性 —— 与 `review.ts` 取 `error.response.data.detail` 同口径。
 * 判据见 `scripts/check-chat-failure-path.cjs`。
 */

/**
 * @param skill 点卡的技能名（`skills.name`）。没点卡时为 `null` ⇒ 请求体不带 `skill`，
 *              与第 189 轮之前**逐字相同**。非空时后端把该技能正文注入 system prompt。
 */
export async function replyProductResearch(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadingStatus, setLoading, handleAgentMeta, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince,
          contextTarget } = ctx

    // 选品分析师
    if (agentStore.currentAgent?.id === 'product-research') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      try {
        const { chatWithProductResearcher } = await import('@/api/productResearch')
        const { streamSSE } = await import('@/api/stream')

        // 文本对话：优先 SSE 流式渲染，失败降级到非流式
        // ★ 取消若发生在上面的 await 期间 ⇒ 连占位气泡都别建（建了也没人收）
        if (isCancelledSince(epoch0)) return 'handled'
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        const signal = beginStream()
        // 会话 ID 必须带上：后端「入库待补槽位」「上一轮蓝海结果」都按会话隔离，
        // 不带就退化成全局共享（多会话串数据），而且「追问 → 补充 → 入库」
        // 这种多轮补齐也无从进行。
        const contextId = chatStore.ensureSessionId('product-research')

        try {
          await streamSSE(
            '/product-research/chat/stream',
            {
              message: userMessage,
              context_id: contextId,
              skill: skill ?? undefined,
              // ★ 第 251 轮：结构化「作用对象」。`undefined`（本 Agent 不参与）
              //   会被 JSON 丢掉 ⇒ 字段不出现；`null` 则**显式下发**，
              //   两者含义不同（见 `ChatCtx.contextTarget`）。
              context_target: contextTarget.value,
            },
            {
            onProgress: (text) => { loadingStatus.value = text },
            onMeta: handleAgentMeta,
            onStep: handleThinkingStep,
            onDelta: (text) => {
              streamed = true
              setLoading(false, 'sse-delta-product')
              chatStore.appendToLastMessage(text)
            },
            onDone: (fullText) => {
              // 结构化结果（蓝海/利润等）在 done 事件前通过 meta 推送，此处兜底
              if (!fullText && !streamed) {
                chatStore.appendToLastMessage('（未获取到分析结果）')
              }
            },
            // ★ 这里**只记录、不写文案**：`streamSSE` 在抛错前会先调一次 `onError`，
            //   此处若也 append，就会与下方 catch 的说明合成**两条互相矛盾**的失败文案
            //   —— 第 219 轮老板报的就是这个形态。失败文案统一由下方 catch 写。
            onError: () => {},
            },
            { signal },
          )
          return 'handled'
        } catch (streamError) {
          // ★ 用户取消 ≠ 失败：不写失败文案、更不发非流式重试（那会把答案又补回来）
          if (absorbStreamCancel(chatStore, streamed, streamError)) return 'handled'
          // 已输出过部分正文 ⇒ 不再追加全文，避免重复
          if (streamed) return 'handled'

          // 流式失败（鉴权 401 / 配额 429 / 网络抖动）→ 回退到非流式对话
          try {
            const response = await chatWithProductResearcher({
              message: userMessage,
              context_id: contextId,
              // ★ 降级路径**同样要带**：否则「点了卡但流式失败」时
              //   前置门禁会看到空的上下文而误判为「本次没有对象」，
              //   把一次网络抖动转译成一句「请先载入选品」。
              context_target: contextTarget.value,
              // ★ 降级路径**同样要带 skill**：否则「点了卡但流式失败」时
              //   会退化成「没有技能的普通提问」，而用户看不出这次降级（同一句话、同一界面）。
              skill: skill ?? undefined,
            })
            chatStore.appendToLastMessage(response.reply || '分析完成')
            // ★ 兜底路径**同样要回填结构化结果**（第 131 轮 item2-C）。
            //   只 append 正文的话，流式失败时用户会看到后端那句
            //   「请选择『批准』或『拒绝』」却**没有任何按钮可点** ——
            //   一句无法执行的指令，比不显示更糟。
            //   审批卡与结论卡都只靠 `display_type` + `data` 渲染。
            if (response?.display_type) {
              chatStore.setLastMessageResult(response.display_type, response.data)
            }
            return 'handled'
          } catch (retryError) {
            // 非流式也失败 ⇒ 如实上报**真实原因**，并就地终止。
            // ★ 必须 `handled`：`fallthrough` 会让降级链再补一句
            //   「我是选品分析师，正在为您分析…」的伪成功文案（本轮 bug 的另一半）。
            // ★ 如实上报**真实原因**（HTTP 状态码 + 后端 `detail`），实现见
            //   `chatFailure.describeChatFailure`（唯一实现）。
            chatStore.setLastMessageContent(
              describeChatFailure('选品分析请求', retryError, streamError),
            )
            return 'handled'
          }
        } finally {
          endStream(signal)
        }
      } catch (error) {
        console.error('选品 API 失败:', error)
      }
    }
  // 本分支没接住（**当前 Agent 与分支不匹配**）⇒ 交回分派器走降级链，**不静默吞掉**
  // ★ 第 221 轮：模块加载失败已被同一条降级吃掉（不会走到这里）。
  return 'fallthrough'
}

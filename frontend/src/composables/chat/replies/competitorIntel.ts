/**
 * 回复链路 · 竞品监控员 / 选品候选快照
 *
 * ★ 第 189 轮（#786）：`replyCompetitorIntel` **已从本地 mock 叙述层改走真后端 LLM**
 *   （`POST /competitor/chat/stream`，SSE）。动因是老板第 187 轮那句
 *   「10 张不走 LLM 的卡片改成走 llm，前端调用后端」——
 *   旧实现调 `@/utils/competitorIntel::analyzeCompetitorIntel()`，那是**本地拼出来的
 *   叙述**（读监控池快照 + 模板造句），从头到尾没有模型参与。
 *
 * ★ `replyCandidateSnapshot` **刻意保留**本地实现，且**不是**遗漏：
 *   它是选品链路的**第二跳**（真后端失败后才轮到它），做的是「对已载入的候选做
 *   静态快照评估」—— 那件事本来就不需要 LLM（纯数值 / 规则推导）。
 *   前置不满足（没载入选品）时必须 `fallthrough`，让降级链继续走到通用提示，
 *   而不是「什么都不做」。
 *
 * ★ `@/utils/competitorIntel` 的退役进度（#741 / #752 / **#918 已收口**）：
 *   它原有 3 个入口 —— 两个已退役（`analyzeCompetitorIntel` 随本文件改走真后端
 *   归零调用；作为**动作条 chip** 的那个随第 189 轮卡片改造退役），
 *   剩下 `analyzeCandidateSelection` 被下面的第二跳使用。
 *   ★★ 第 255 轮（#918）：`analyzeCompetitorIntel` 与其数据源 A 子树
 *     （意图识别 / 证据聚合 / `buildReply`）**已整体删除** ——
 *     它唯一的调用点就是竞品监控员那 12 个**不可达**工具卡。
 *     同类「注册了却没有入口」的回归由 `check-tool-reality.cjs` F1 判红。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { absorbStreamCancel } from '../streamCancel'
import type { ChatCtx, ReplyOutcome } from '../types'

/**
 * @param skill 点卡的技能名（`skills.name`）。★ 竞品这条链的 `skill` 走 **URL query**
 *              而不是 body —— 原因见 `api/competitorIntel.ts::_queryWithSkill`。
 */
export async function replyCompetitorIntel(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadingStatus, setLoading, handleAgentMeta, handleThinkingStep,
          beginStream, endStream, cancelEpoch, isCancelledSince } = ctx

    // 竞品监控员：真后端 LLM（SSE 流式）—— 第 189 轮 #786
    if (agentStore.currentAgent?.id === 'competitor-intel') {
      // ★ 取消纪元快照：下面每个 await 之后都要用它判「我这一轮是否已被取消」
      const epoch0 = cancelEpoch.value
      try {
        const { streamCompetitorChat } = await import('@/api/competitorIntel')

        // ★ 取消若发生在上面的 await 期间 ⇒ 连占位气泡都别建（建了也没人收）
        if (isCancelledSince(epoch0)) return 'handled'
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        const signal = beginStream()
        try {
          await streamCompetitorChat(userMessage, skill, {
            onProgress: (text) => { loadingStatus.value = text },
            onMeta: handleAgentMeta,
            onStep: handleThinkingStep,
            onDelta: (text) => {
              streamed = true
              setLoading(false, 'sse-delta-competitor')
              chatStore.appendToLastMessage(text)
            },
            onDone: (fullText) => {
              if (!fullText && !streamed) {
                chatStore.appendToLastMessage('（未获取到分析结果）')
              }
            },
            // 失败文案由下方统一写：`streamSSE` 抛错前会先调 `onError`，
            // 这里再写一次就会得到两条重复说明。
            onError: () => {},
          }, { signal })
        } catch (streamError) {
          // ★ 用户取消 ≠ 失败：不写「未返回内容」那句（那是给真失败用的），直接收口
          if (absorbStreamCancel(chatStore, streamed, streamError)) return 'handled'
          // ★ 必须在此**终止**（`handled`），不能 `fallthrough`、更不能退回本地 mock：
          //   · 穿透到 `replyFallback` 会追加第二条文案 ⇒ 用户看到两条互相矛盾的失败说明
          //     （Listing 分支就是这么留下历史疙瘩的，见 `index.ts` 文件头）；
          //   · 退回本地 mock 会把「后端挂了」渲染成一段**看起来正常的分析** ——
          //     那正是本轮要消灭的东西。
          if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
            chatStore.appendToLastMessage('（竞品分析未返回内容，请稍后重试。）')
          }
          return 'handled'
        } finally {
          endStream(signal)
        }
        return 'handled'
      } catch (error) {
        console.error('竞品监控对话失败:', error)
      }
    }
  // 本分支没接住（前置不满足 / 模块加载失败）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

export async function replyCandidateSnapshot(ctx: ChatCtx, userMessage: string): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const { loadedCandidate, ensureCandidateLoaded } = ctx

    // 选品分析师：若已「载入选品」→ 针对该候选做静态快照可行性；未载入 → 走默认回复引导载入
    if (agentStore.currentAgent?.id === 'product-research' && loadedCandidate.value) {
      try {
        await ensureCandidateLoaded()
        const { analyzeCandidateSelection } = await import('@/utils/competitorIntel')
        const reply = analyzeCandidateSelection([loadedCandidate.value])
        chatStore.addMessage({ role: 'assistant', content: reply })
        return 'handled'
      } catch (error) {
        console.error('选品分析师候选评估失败:', error)
      }
    }
  // 本分支没接住（API 挂了 / 前置不满足）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

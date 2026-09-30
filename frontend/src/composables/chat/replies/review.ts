/**
 * 回复链路 · 运营复盘师（真后端）
 *
 * ★ 第 167 轮 #725 退役 `@/mock/reviewDashboard` 的产物。旧实现是个**纯数据编造器**：
 *   把 `+12.3%` /「目标完成率 92.4%」这些后端从未计算过的数字写死在字符串里，
 *   用户看到的每一句结论都与自己店铺无关。
 *
 * ★ 两条硬约束（都是本仓既有铁律）：
 *   ① **失败路径必须回写界面**（给一句可行动的话），不许静默落到通用兜底
 *      —— 那会渲染成「我在为您分析…」这种**伪装成成功的失败**；
 *   ② **降级不许静默**：后端 `degraded=true` 时把原因一起写进消息，
 *      否则「查不到数据」与「你的数据就是这么差」在界面上完全不可区分。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { useShopStore } from '@/stores/shop'
import type { ChatCtx, ReplyOutcome } from '../types'

/**
 * @param skill 点卡的技能名（`skills.name`）。没点卡时为 `null` ⇒ 不带该字段。
 */
export async function replyReview(
  ctx: ChatCtx,
  userMessage: string,
  skill: string | null = null,
): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const shopStore = useShopStore()

    // 运营复盘师（第 167 轮 #725：退役 `@/mock/reviewDashboard`，改走真后端）
    //
    // ★ 旧实现调 `m.buildReviewReply(intent)` —— 那是个**纯数据编造器**：
    //   它把 `+12.3%` / `+8.1%` / 「环比」/「目标完成率 92.4%」这些**后端从未计算过**
    //   的数字写死在字符串里。用户看到的每一句结论都与自己店铺无关。
    //
    // ★ 新实现的两个硬要求（都是本仓既有铁律，不是本次新发明）：
    //   ① **失败路径必须回写界面状态** —— 拿不到数据时给一句可行动的说明，
    //      而不是 `catch` 之后静默落到下面的「默认模拟响应」（那会渲染出
    //      「收到：… 我是运营复盘师，正在为您分析…」这种**伪装成成功的失败**）。
    //   ② **降级不许静默** —— 后端 `degraded=true` 时把原因一并写进消息；
    //      否则「查不到数据」与「你的数据就是这么差」在界面上完全不可区分。
    if (agentStore.currentAgent?.id === 'review-analyst') {
      // ★ 取消纪元快照：复盘是**非流式**调用（axios 拦不住），只能让它在回来时自我否决
      const epoch0 = ctx.cancelEpoch.value
      try {
        const { chatWithReviewAnalyst } = await import('@/api/review')
        // 会话 ID 必须带：后端拿它当 checkpointer 的 `thread_id`，
        // 同一会话的第二轮才看得见第一轮；不带则后端**不留记忆**（不做默认值兜底）。
        const sessionId = chatStore.ensureSessionId('review-analyst')
        const res = await chatWithReviewAnalyst({
          query: userMessage,
          session_id: sessionId,
          skill: skill ?? undefined,
        })
        // ★ 用户在等待期间点了「停止生成」⇒ 这份结果（含"没返回结果"那句）都不许再上屏
        if (ctx.isCancelledSince(epoch0)) return 'handled'
        const out = res?.data
        if (out?.reply) {
          chatStore.addMessage({
            role: 'assistant',
            content: out.degraded
              ? `${out.reply}\n\n> ⚠️ ${out.degraded_reason || '本次未取到店铺数据，以上结论可能不完整。'}`
              : out.reply,
            data: out.data,
            displayType: out.display_type || 'text',
          })
          return 'handled'
        }
        // 200 但没有结果体：也必须说出来，不许静默兜底成假回复。
        //
        // ★ 不读 `res.message`（第 268 轮 B 档）：信封里的 `message` 是短回执
        //   （「复盘完成」），拼进这句话会变成「未返回结果。复盘完成」。
        //   真正的失败说明在后端 4xx/5xx 的 `detail` 里（走下面的 catch）。
        chatStore.addMessage({
          role: 'assistant',
          content: '⚠️ 复盘服务未返回结果，请稍后重试。',
        })
        return 'handled'
      } catch (error: any) {
        // ★ `error.response.data.detail` 里是后端**可解释的业务结论**：
        //   400 = 没选店铺（X-Shop-ID 缺失，strict 守卫拦下）
        //   403 = 该店铺不属于当前账号
        //   这两类都不是网络故障，原样说出来才有可操作性。
        const status = error?.response?.status
        const detail = error?.response?.data?.detail
        const hint = !shopStore.currentShopId
          ? '请先在界面左上角选择一个店铺。'
          : status === 403
            ? '当前账号无权访问该店铺的数据，请切换店铺后重试。'
            : '请稍后重试。'
        chatStore.addMessage({
          role: 'assistant',
          content: `⚠️ ${detail || '复盘数据暂时取不到。'}\n\n${hint}`,
        })
        return 'handled'
      }
    }
  // 本分支没接住（API 挂了 / 前置不满足）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

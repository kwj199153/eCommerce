/**
 * 回复链路 · 通用兜底（最后一跳）
 *
 * ★ 这一跳是**有意保留**的：`aigc-media` 在分派器（`index.ts`）的冻结分派表里
 *   **本就没有专属分支**，它只有从这里才能拿到一句可行动的话。
 *
 * ★ 但它也是本仓最容易被误读的地方 —— 任何分支只要 `catch` 之后忘了 `return`，
 *   用户就会看到「收到：… 我是 X，正在为您分析…」。第 219 轮之前这里**确实是那么写的**，
 *   于是选品分析师配额耗尽（HTTP 429）时，用户同时收到
 *   `（对话失败，请重试）` 与 `我是 选品分析师，正在为您分析...` 两条互相矛盾的说明。
 *
 * ★ 第 219 轮起的纪律：
 *   ① 本文件**禁止任何「正在进行」的措辞**。一个没能接住请求的分支不可能同时
 *      「正在分析」—— 那正是「伪装成成功的失败」。
 *   ② 真后端分支的失败必须**在各分支内显式终止**（`return 'handled'` + 写明原因）：
 *      见 `productResearch.ts` / `competitorIntel.ts` / `review.ts`。
 *   ③ 本文件只负责「本来就没有专属分支」与「分支穿透」两种到达方式，且**只陈述事实**
 *      （没返回结果 / 对话未接入），不假装在做分析。
 *
 * ★ 末尾仍返回 `'fallthrough'`，**不要**为了「整齐」改成 `'handled'`：
 *   `scripts/check-chat-domain-split.cjs` 的 A7 把本文件登记为 `LAST_RESORT` ——
 *   最后一跳天然不会提前终止，给它补一个「已处理」出口，等于把「什么都没接住」
 *   伪装成「已处理」。
 */

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import type { ChatCtx, ReplyOutcome } from '../types'

export async function replyFallback(ctx: ChatCtx, userMessage: string): Promise<ReplyOutcome> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const agentId = agentStore.currentAgent?.id
  const agentName = agentStore.currentAgent?.name || '当前 Agent'

  // ★ 两种到达方式必须给**不同**文案，否则必有一边说谎：
  //   ① `aigc-media` 没有专属分支 ⇒ 说清「对话未接入、请用工具卡片」；
  //   ② 某分支失败后穿透而来 ⇒ 如实说「没返回结果」，**不得**暗示正在分析。
  const content = agentId === 'aigc-media'
    ? `> 💡 **${agentName}** 的对话能力尚未接入，请使用上方的工具卡片（图片 / 视频 / 文案生成）执行任务。`
    : [
        `⚠️ **${agentName}** 这次没有返回结果。`,
        '',
        `> 你刚才说的是：「${userMessage}」`,
        '',
        agentId === 'competitor-intel'
          ? `> 💡 可点下方「竞品周报 / 异动洞察 / 策略推演」，或稍后重试。`
          : agentId === 'product-research'
            ? `> 💡 先在顶部点击 **【载入选品】** 选定评估对象，再点下方「市场可行性 / 上架建议」，或稍后重试。`
            : `> 💡 可以用上方的工具卡片直接执行，或稍后重试。`,
      ].join('\n')

  // ★ 这里**没有** `await new Promise(r => setTimeout(r, 800))` 那种假延时：
  //   它让「没有答复」看起来像「正在生成」，与本轮要消灭的伪成功是同一类东西。
  chatStore.addMessage({ role: 'assistant', content })
  // 本分支没接住（API 挂了 / 前置不满足）⇒ 交回分派器走降级链，**不静默吞掉**
  return 'fallthrough'
}

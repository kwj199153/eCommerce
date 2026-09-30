/**
 * 对话编排层 · 发送链路与回复分派（第 169 轮 #664）
 *
 * ★ 分派器严格复原**原实现的控制流**：一串按注册顺序排列的
 *   `if (agentId === …) { try { … return } catch { console.error } }`，
 *   其中**未 `return` 的 catch 会把控制流交给下一个 `if`**，最终落到通用兜底。
 *   这是有意的降级链，不是笔误 ⇒ 所以每个分支返回 `ReplyOutcome`
 *   （`'handled'` = 已给答复、终止；`'fallthrough'` = 本分支没接住、继续）。
 *
 * 原顺序与穿透关系（逐条对照原文件 L1119–L1629）：
 *
 *   | 分支 | 原条件 | 失败时 |
 *   |---|---|---|
 *   | 店秘书 | `id === 'secretary'` | 内部已自带本地正则兜底；**两条路径都终止** |
 *   | 选品（真后端+SSE） | `id === 'product-research'` | 内部已终止（第 219 轮）；只有「不匹配」才穿透到第二跳 |
 *   | Listing | `id === 'listing-generator'` | 内部已终止（第 221 轮） |
 *   | 广告 | `id === 'ad-analysis'` | 内部已终止（第 221 轮） |
 *   | 客服 | `id === 'customer-service'` | 内部已终止（第 221 轮） |
 *   | 竞品监控 | `id === 'competitor-intel'` | 穿透 |
 *   | 选品第二跳（静态快照） | `id === 'product-research' && loadedCandidate` | 穿透 |
 *   | 运营复盘 | `id === 'review-analyst'` | 内部已把失败写进对话；**两条路径都终止** |
 *   | 通用兜底 | 其余 | 终止 |
 *
 * ★ 已知历史疙瘩 —— **第 221 轮已消**：
 *   旧形态是「Listing 分支失败时先补一条『流式中断』，再穿透到通用兜底 ⇒ 用户看到两条」。
 *   第 221 轮把四条真后端分支（Listing / 广告 / 客服 / 选品）的失败路径统一成
 *   「`onError` 只记录不写文案 → 非流式重试 → 仍失败则如实上报并 `return 'handled'`」，
 *   文案实现收口到 `composables/chat/chatFailure.ts`（唯一实现）。
 *   ⇒ 四条分支都**不再穿透**；`fallthrough` 只剩两种来源：
 *     ① 当前 Agent 与分支不匹配（正常分派）；② 真后端分支的模块加载失败（会被同一条降级吃掉）。
 *
 * ★ 第 189 轮新增：**技能点名（`skill`）**
 *   动作条上的卡片现在就是技能（第 187 轮「skill 当源」）。点卡 → `setPendingSkill`
 *   → `handleSend` → **本函数开头消费一次** → 作为第 3 参下发给各分支，各分支把它
 *   塞进请求体（竞品例外，走 URL query —— 见 `api/competitorIntel.ts` 的原因注释）。
 *   没点卡时 `skill === null`，各分支行为与改造前**逐字相同**（这是本轮的回归判据）。
 */
import { message } from 'ant-design-vue'

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import type { ChatCtx, ReplyOutcome } from '../types'

import { replySecretary } from './secretary'
import { replyProductResearch } from './productResearch'
import { replyListing } from './listing'
import { replyAdAnalysis } from './adAnalysis'
import { replyCustomerService } from './customerService'
import { replyCompetitorIntel, replyCandidateSnapshot } from './competitorIntel'
import { replyReview } from './review'
import { replyFallback } from './fallback'

/**
 * 按当前 Agent 分派一次回复。
 *
 * ★ 判据用的是 `agentStore.currentAgent?.id`（原样）—— **不是** `chatStore.activeAgentId`。
 *   两者语义不同：前者是「面板上选中的 Agent」，后者是「对话区当前归属」。
 *   原实现在这里就用 currentAgent，保持一致以免改变可见行为。
 */
export async function runAgentReply(ctx: ChatCtx, userMessage: string): Promise<void> {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const agentId = agentStore.currentAgent?.id

  // ★ 技能点名的**唯一读取点**（第 189 轮立 · 第 249 轮改语义）。
  //   链路：动作条点卡 → `ctx.setPendingSkill(name)` → `handleSend` → 这里读。
  //   ★ 第 249 轮起**取出不清空**：点名保持到「任务结束」为止 —— 因为技能可能是多轮的
  //     （「行动计划」要先确认基于哪份复盘）。旧语义在这里就清掉，第二轮的回答会退化成
  //     关键词短路、输出一张完全无关的报表。完整论证见 `chat/types.ts`。
  //   非点卡入口（键盘 Enter / 发送按钮 / 事件桥续跑）拿到 `null`，
  //   此时各分支请求体里 `skill` 为 undefined —— 与改造前**逐字等价**。
  const skill = ctx.peekPendingSkill()

  try {
    await dispatchToAgent(ctx, agentId, userMessage, skill)
  } finally {
    // ★ **任务边界**收口在这一处（不在 6 条回复链路里各写一遍）。
    //   本轮产出了结果 ⇒ 这个任务结束 ⇒ 清点名。
    //   本轮只是追问（display_type='text' 且无 data）⇒ **保留**，下一轮继续带。
    if (skill && turnProducedResult(chatStore, agentId)) ctx.clearPendingSkill()
  }
}

/**
 * 本轮**是否产出了结果** —— 技能点名「任务边界」的唯一判据（第 249 轮）。
 *
 * ★ 与后端**同一口径**：`modules/review_analyst/agent.py` 的 `_route_via_tools` 在
 *   「无工具结果但有最终回复」时返回 `display_type="text"`（注释原文：*模型可能只是在
 *   追问/澄清*）；产出报告时 `display_type` 是报告型且 `data` 非空。
 *   两边必须同时成立 —— 只改一边，这条链会再一次断在中间。
 *
 * ★ 为什么读**消息**、而不是让 6 条回复链路各自上报「我是不是结果型」：
 *   本仓的「同一判定两份实现 ⇒ 至少一份永远测不到」反复咬过人。读界面**已经渲染出来的
 *   事实**只需一份实现，且天然覆盖全部链路（包括将来新增的）。
 *
 * ★ 判据取「非 text 的 displayType」或「有 data」：两者取或 ——
 *   只判 displayType 会漏掉「有结构化数据但没给类型」的链路，
 *   只判 data 会漏掉「有类型但 data 为空对象」的链路。
 *   ★ 取值方向是**保守的**：宁可判定"没产出结果"（多留一轮点名）也不误清 ——
 *     与「拿不到权威清单 ≠ 清单为空」同源：两个方向的代价不对称。
 */
function turnProducedResult(
  chatStore: ReturnType<typeof useChatStore>,
  agentId?: string,
): boolean {
  // ★ 「取不到权威清单 ≠ 清单为空」（本仓既有判据）：读不到消息列表时**按"未产出"处理**
  //   ⇒ 点名多留一轮。取值方向是安全的 —— 多留一轮用户再点一次即可，
  //   而误清是**结构性地拿不到**。两个方向的代价不对称，故选这一侧。
  //   同一条守卫还让门禁/测试里的**桩对象**不会在此抛 TypeError：
  //   桩是为测别的行为而来的，不该因为一条新判据整体崩掉。
  const byAgent: any = (chatStore as any)?.messagesByAgent
  const list = byAgent ? byAgent[agentId || 'default'] : null
  const last = Array.isArray(list) && list.length > 0 ? list[list.length - 1] : null
  if (!last || last.role !== 'assistant') return false
  if (last.data) return true
  return !!last.displayType && last.displayType !== 'text'
}

/** 按 Agent 分派一次回复（`runAgentReply` 的 if 链，逐字保留）。 */
async function dispatchToAgent(
  ctx: ChatCtx,
  agentId: string | undefined,
  userMessage: string,
  skill: string | null,
): Promise<void> {
  if (agentId === 'secretary') {
    await replySecretary(ctx, userMessage)
    return
  }

  if (agentId === 'product-research') {
    // 第一跳：真后端；没接住才轮到第二跳（载入选品的静态快照）
    if ((await replyProductResearch(ctx, userMessage, skill)) === 'handled') return
    if ((await replyCandidateSnapshot(ctx, userMessage)) === 'handled') return
    await replyFallback(ctx, userMessage)
    return
  }

  if (agentId === 'listing-generator') {
    if ((await replyListing(ctx, userMessage, skill)) === 'handled') return
    await replyFallback(ctx, userMessage)
    return
  }

  if (agentId === 'ad-analysis') {
    if ((await replyAdAnalysis(ctx, userMessage, skill)) === 'handled') return
    await replyFallback(ctx, userMessage)
    return
  }

  if (agentId === 'customer-service') {
    if ((await replyCustomerService(ctx, userMessage, skill)) === 'handled') return
    await replyFallback(ctx, userMessage)
    return
  }

  if (agentId === 'competitor-intel') {
    if ((await replyCompetitorIntel(ctx, userMessage, skill)) === 'handled') return
    await replyFallback(ctx, userMessage)
    return
  }

  if (agentId === 'review-analyst') {
    await replyReview(ctx, userMessage, skill)
    return
  }

  await replyFallback(ctx, userMessage)
}

/** 发送链路（键盘 Enter 与「发送」按钮共用）。 */
export function useAgentReply(ctx: ChatCtx) {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()

  const { inputMessage, isLoading, setLoading, scrollToBottom } = ctx

  /** 兼容原名：本文件内 `handleSend` 直接调它，分派逻辑见上面的 `runAgentReply`。 */
  const simulateAgentResponse = (userMessage: string) => runAgentReply(ctx, userMessage)

  // ========== 聊天功能 ==========


  // 键盘事件
  const handleKeyPress = (e: KeyboardEvent) => {
    if (!e.shiftKey && e.key === 'Enter') {
      e.preventDefault()
      handleSend()
    }
  }

  // 发送消息
  const handleSend = async () => {
    const text = inputMessage.value.trim()
    if (!text || isLoading.value) return

    if (!agentStore.currentAgent) {
      message.warning('请先在左侧选择一个 Agent')
      return
    }

    chatStore.addMessage({ role: 'user', content: text })
    inputMessage.value = ''
    setLoading(true, 'send-message')

    try {
      await simulateAgentResponse(text)
    } catch (error) {
      message.error('发送失败，请重试')
    } finally {
      setLoading(false, 'send-finally')
    }
    await scrollToBottom()
  }

  return { handleKeyPress, handleSend, runAgentReply: simulateAgentResponse }
}

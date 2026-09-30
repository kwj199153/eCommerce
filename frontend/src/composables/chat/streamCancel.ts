/**
 * 对话编排层 · 「取消」的收口（第 241 轮：可取消生成）
 *
 * 为什么要有这个模块
 * ================
 * 6 条流式回复链的 `catch` 都要回答同一个问题：**「这一轮是被用户取消的，还是真失败？」**
 * 两者的正确处理**正好相反**：
 *
 *   · 真失败 ⇒ 如实上报（HTTP 状态码 + 后端 detail）→ 非流式重试 → 仍失败就写失败文案；
 *   · 用户取消 ⇒ **什么都不做**。写失败文案是错的（用户自己按的停止，不是故障）；
 *     发起非流式重试更错（会把答案又补回来，看上去像"停止按钮失灵"）。
 *
 * 若把这套判定在 6 条链里各抄一份，必然漏掉一两条 —— 而"取消"是低频手动操作，
 * 漏了在日常点击里很难发现（本仓「同一判定两份实现 ⇒ 至少一份永远测不到」的形态）。
 *
 * ★ 为什么它**不能**塞进 `chatFailure.ts`：
 *   那个模块被门禁钉成**纯函数模块**（不许 import store / api）——
 *   见 `scripts/check-chat-failure-path.cjs::P4`。本函数要动 store（收掉空气泡），
 *   所以只能另起一个模块，而"谁写界面"这一步必须留在**知道有没有占位气泡**的地方。
 */
import { isStreamCancelled } from '@/api/stream'

/**
 * 取消收口所需的最小 store 形状。★ 刻意写成**结构类型**、而不是
 * `ReturnType<typeof useChatStore>` —— 本模块因此不 import 任何 store / pinia，
 * 门禁把它当纯函数模块装载时不必额外打桩（少一个桩 = 少一处会腐烂的接线）。
 */
export interface CancelSink {
  /** 当前对话区归属的 Agent（与 `addMessage` 的落点同一口径） */
  activeAgentId: string
  getMessages: (agentId: string) => Array<{ role: string; content: string }>
  removeMessage: (index: number, agentId?: string) => void
}

/**
 * 收掉「一个字都没吐出来」的 assistant 占位气泡。
 *
 * 判据与 `replies/secretary.ts` 的 `finally` 里那段**完全一致**（同一条口径，
 * 别再造第三种）：最后一条是 assistant 且 `content` 为空 ⇒ 那是刚建好、
 * 还没写入正文的占位气泡。留着它 = 界面上一个空气泡（"回复了个寂寞"）且零报错。
 */
export function dropEmptyAssistantBubble(sink: CancelSink): void {
  const list = sink.getMessages(sink.activeAgentId)
  const last = list[list.length - 1]
  if (last && last.role === 'assistant' && !last.content) {
    sink.removeMessage(list.length - 1)
  }
}

/**
 * 取消收口：**全仓唯一的「这一轮是取消吗」判定入口**。
 *
 * @param sink     取消时要收拾的 store（结构类型，见上）
 * @param streamed 本链是否已经吐过正文。已吐 ⇒ 保留半句（用户看得见自己打断了什么）；
 *                 没吐 ⇒ 收掉空占位气泡。
 * @returns `true` = 确系用户取消 ⇒ **调用方必须 `return 'handled'` 就地终止**：
 *          不得追加失败文案、不得发起非流式重试、不得穿透到通用兜底。
 *          `false` = 不是取消，按原有失败路径继续。
 */
export function absorbStreamCancel(sink: CancelSink, streamed: boolean, err: unknown): boolean {
  if (!isStreamCancelled(err)) return false
  if (!streamed) dropEmptyAssistantBubble(sink)
  return true
}

/**
 * 对话编排层 · 语音播报（第 169 轮 #664 从编排器搬出）
 *
 * 职责单一：监听「当前对话区最后一条 assistant 消息」，把它**渐进**喂给播报队列。
 *
 * ★ 为什么放在编排层而不是每个 Agent 的回复分支里各加一行：
 *   「扩展到其他 Agent」应该是**改白名单**（`stores/voiceTts.ts` 的 `supports`），
 *   而不是回头改 6 个分支。
 *
 * ★ 第 169 轮拆分的两处所有权变更（都不是行为变更）：
 *   ① 原先 `speakTailTimer` / `voiceTts.stop()` 的清理写在编排器的 `onUnmounted` 里，
 *      但操作的是本模块持有的东西 ⇒ 搬回本模块，**清理责任与持有责任同处一地**；
 *   ② `onUnmounted` 在本 composable 内注册 —— 它在 `useChatOrchestrator` 的同步
 *      setup 期间被调用，生命周期钩子仍绑在同一个组件实例上，语义不变。
 */
import { onUnmounted, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useVoiceTtsStore } from '@/stores/voiceTts'

export function useVoiceAnnounce() {
  const chatStore = useChatStore()

  // ===== 语音播报：边生成边念（首期只服务店秘书） =====
  //
  // 为什么放在编排层、而不是去每个 Agent 的回复分支里各加一行：
  // 「扩展到其他 Agent」应该是**改白名单**，而不是回头改 6 个分支。
  // 所以这里统一监听「当前对话区最后一条 assistant 消息」，把它渐进喂给播报队列。
  //
  // ★★ 已废弃的旧做法（P0+P1，2026-09-14）：`SPEAK_SETTLE_MS = 700` 防抖。
  //    它的语义是「每个 delta 都重置计时器」⇒ 等价于「等整段说完，再等 700ms 才
  //    开始合成」⇒ 首声实测 8.7s（正文 7.6s 与合成 5.2s 串起来）。
  //    现在改成**分句流水线**：每个 delta 都把「目前为止的正文」交给 store，
  //    由它调后端 /speak-plan 算出**已定型**的段，边生成边合成、边合成边播 ⇒
  //    首声只等第一段（实测 ~1.1s）。
  //
  // 仍然必须处理的时序问题（都不是理论问题）：
  // 1. **认本轮**：`runKey` = `agentId#timestamp`，变了就是新回复 → store 重置游标。
  //    ★ runKey **不能带正文长度** —— 长度随每个 delta 变，含进去等于每次增量都
  //    开新一轮、从头重念。长度只用于**触发** watch（见下面的 getter）。
  // 2. **交接**：店秘书回复后 ~700ms 会切到子 Agent，对话区随之切换 ——
  //    所以每次都从**当前快照**取正文，不缓存旧引用。
  // 3. **收尾**：正文停止增长后再喂一次 `streaming=false`，让 store 念掉结尾那段
  //    尚未定型的碎片（否则最后半句永远不念）。这个 300ms 只影响**尾巴**，
  //    不影响首声 —— 首声由流式期间**已定型**的段决定。
  const voiceTts = useVoiceTtsStore()
  const SPEAK_TAIL_MS = 300
  let speakTailTimer: ReturnType<typeof setTimeout> | null = null

  /**
   * 取「当前对话区最后一条 assistant 消息」。
   *
   * 用 `chatStore.activeAgentId`（而不是 `agentStore.currentAgent`）判归属：
   * `chatStore.messages` 就是按 activeAgentId 切的，两者必须同源，
   * 否则会拿 A 的回复去套 B 的白名单。
   */
  function lastAssistantSnapshot(): { agentId: string; text: string; runKey: string } | null {
    const list = chatStore.messages
    const last = list[list.length - 1]
    if (!last || last.role !== 'assistant') return null
    const text = (last.content || '').trim()
    if (!text) return null
    const agentId = chatStore.activeAgentId
    return { agentId, text, runKey: `${agentId}#${last.timestamp}` }
  }

  watch(
    () => {
      const snap = lastAssistantSnapshot()
      // ★ 触发源必须含正文长度：`appendToLastMessage` 只改 content，
      //   不含长度的话 watch 在流式期间根本不会触发。
      return snap ? `${snap.runKey}#${snap.text.length}` : ''
    },
    () => {
      const snap = lastAssistantSnapshot()
      if (!snap) return
      // 白名单判定只认 store（唯一真源），这里不重复写 Agent id
      if (!voiceTts.supports(snap.agentId)) return
      if (!voiceTts.enabled) return
      // ★★ 「本轮」闸门：只念**刚刚被提问的那个对话区**的回复。
      //   没有这道闸，下面两种情况会凭空开口：
      //   ① 开屏欢迎语 —— 它也是 assistant 消息，于是每次刷新都念一遍；
      //   ② 切面板回来 —— activeAgentId 一变 watch 就触发，读到的是历史回复，
      //      而此时 runKey 没见过 ⇒ setupRun 重置游标 ⇒ 从头再念一遍。
      //   判据来自 chatStore.lastUserMessage（唯一写入点在 chatStore.addMessage）。
      if (chatStore.lastUserMessage?.agentId !== snap.agentId) return

      // ① 立刻喂：已定型的段马上开始合成 ⇒ 首声不必等正文说完
      voiceTts.feed(snap.text, { runKey: snap.runKey, streaming: true })

      // ② 尾部兜底：正文停 300ms 没再长 ⇒ 认为说完了，把结尾碎片也念掉
      if (speakTailTimer) clearTimeout(speakTailTimer)
      speakTailTimer = setTimeout(() => {
        speakTailTimer = null
        if (!voiceTts.enabled) return
        voiceTts.feed(snap.text, { runKey: snap.runKey, streaming: false })
      }, SPEAK_TAIL_MS)
    }
  )

  // 对话区销毁（离开对话视图）→ 立刻停声，别再触发播报
  onUnmounted(() => {
    if (speakTailTimer) clearTimeout(speakTailTimer)
    voiceTts.stop()
  })
}

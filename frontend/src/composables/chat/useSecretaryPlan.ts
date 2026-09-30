/**
 * 对话编排层 · 店秘书子任务计划（第 169 轮 #664 从编排器搬出）
 *
 * 计划是**会话级状态**（后端存在图状态里、随 checkpointer 落 PG，不随上下文裁剪丢失），
 * 所以前端只在收到 `/orchestrator/chat` 响应时才知道它 —— 一刷新手上就没有「最近一次响应」了。
 * 后端为此提供了只读读口 `GET /orchestrator/plan`（不调 LLM、**不消耗对话次数**）。
 *
 * ★ 判归属用 `chatStore.activeAgentId`（与 `messages` / `PlanChecklist` 同源），
 *   **不是** `agentStore.currentAgent` —— 两者不同源时会出现「面板已经切过去了、
 *   判归属的那个还没变」，读计划就静默不触发。
 *
 * ★ 「读失败 ⇒ 不动 store」：**拿不到权威清单 ≠ 清单为空**，
 *   保留旧值才是安全失败方向（清了会让老板看到计划凭空消失，而后端其实好好的）。
 */
import { computed, watch } from 'vue'
import { useChatStore } from '@/stores/chat'

export function useSecretaryPlan() {
  const chatStore = useChatStore()

  // ===== 店秘书计划（第 155 轮）==============================================
  /**
   * 店秘书的当前子任务计划（会话级状态）。
   * ★ 用 `chatStore.activeAgentId` 判归属、而不是 `agentStore.currentAgent` ——
   *   与 `messages` 同源（见本文件顶部关于两者必须同源的注释）。
   */
  const secretaryPlan = computed(() =>
    chatStore.activeAgentId === 'secretary' ? chatStore.getPlan('secretary') : undefined,
  )

  /**
   * 刷新后恢复计划（第 155 轮）。
   *
   * 为什么需要：计划是**跨轮持续的状态**（后端存在图状态、随 checkpointer 落 PG，
   * 不随上下文裁剪丢失），但前端只在收到 `/orchestrator/chat` 响应时才知道它 ——
   * 老板一刷新，手上就没有'最近一次响应'了。后端为此提供了只读读口
   * `GET /orchestrator/plan`（不调 LLM、**不消耗对话次数**）。
   *
   * ★ 三个「不做」：
   *   · 不是 secretary 对话区 ⇒ 不发请求（计划只有店秘书有）；
   *   · 没有 sessionId ⇒ 不发请求（后端也只会返回 null）；
   *   · **读失败 ⇒ 不动 store** —— 「拿不到权威清单 ≠ 清单为空」，
   *     保留旧值才是安全失败方向（清了会让老板看到计划莫名消失，
   *     而后端那边其实好好的）。
   * ★ 成功时写的是 `null`（明确没有计划）而不是 `undefined`（不知道），
   *   两者在 `setPlan` 里语义不同。
   */
  async function loadSecretaryPlan() {
    if (chatStore.activeAgentId !== 'secretary') return
    const sid = chatStore.getSessionId('secretary')
    if (!sid) return
    try {
      const { fetchCurrentPlan } = await import('@/api/secretary')
      const { plan } = await fetchCurrentPlan(sid)
      chatStore.setPlan('secretary', plan)
    } catch {
      // 静默：读不到计划不是错误态，不该弹 toast 打断老板。
      // （宿主页面无需感知 —— 计划条自己会保持上一次的显示或为空。）
    }
  }

  /**
   * 进入店秘书对话区时拉一次计划。
   *
   * ★ 监听的是 `chatStore.activeAgentId`（与 `secretaryPlan` / `messages` 同源），
   *   **不是** `agentStore.currentAgent` —— 两者不同源时会出现"面板已经切过去了、
   *   判归属的那个还没变"，读计划就会静默不触发。
   * ★ `immediate: true` 是必需的：刷新页面时 `activeAgentId` 往往**已经是**
   *   secretary，只监听后续变化的话这个 watch 永远不触发 —— 恰好漏掉
   *   "刷新后恢复"这个**唯一**的场景。
   */
  watch(
    () => chatStore.activeAgentId,
    () => {
      loadSecretaryPlan()
    },
    { immediate: true },
  )

  return { secretaryPlan, loadSecretaryPlan }
}

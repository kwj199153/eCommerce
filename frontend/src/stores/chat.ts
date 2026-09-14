import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: number
  hitlRequired?: boolean
  hitlToolName?: string
  data?: any
  displayType?: string
}

export const useChatStore = defineStore('chat', () => {
  // 按 Agent ID 分组的消息列表：{ [agentId]: Message[] }
  const messagesByAgent = ref<Record<string, Message[]>>({})

  // 当前激活的 Agent ID（用于 addMessage 路由到正确的对话区）
  const activeAgentId = ref<string>('default')

  // 按 Agent ID 分组的会话 ID（决策层 B：跨会话记忆）
  // 后端返回 session_id 后写入，刷新页面从 localStorage 恢复，实现「刷新不丢对话」
  const sessionIdByAgent = ref<Record<string, string>>({})

  /**
   * ★ 最近一次「往哪个对话区追加了 user 消息」——语音播报的**本轮判据**。
   *
   * 播报只该念「你刚提问后得到的回复」。没有这条判据时，下面两种都会被念出来：
   * ① 开屏欢迎语（它是 assistant 消息、前面没有 user 消息）；
   * ② 切面板回来看到的历史回复（activeAgentId 一变，watch 就触发）。
   *
   * 写入点只有下面 `addMessage` 一处 —— user 消息的落点在全项目有 6 处，
   * 分散去记必然漏一处（漏了就是静默不播报），所以收敛到这里。
   */
  const lastUserMessage = ref<{ agentId: string; at: number } | null>(null)

  // sessionId 持久化 key
  const SESSION_KEY = 'secretary_session_ids'

  // 从 localStorage 恢复 sessionId（初始化时调用）
  const loadSessionIds = () => {
    try {
      const raw = localStorage.getItem(SESSION_KEY)
      if (raw) {
        sessionIdByAgent.value = JSON.parse(raw)
      }
    } catch (e) {
      // 忽略解析错误
    }
  }

  // 持久化 sessionId 到 localStorage
  const _persistSessionIds = () => {
    try {
      localStorage.setItem(SESSION_KEY, JSON.stringify(sessionIdByAgent.value))
    } catch (e) {
      // 忽略写入错误（如隐私模式）
    }
  }

  // 获取指定 Agent 的会话 ID（无则返回 undefined）
  const getSessionId = (agentId: string): string | undefined => {
    return sessionIdByAgent.value[agentId]
  }

  // 设置指定 Agent 的会话 ID（持久化）
  const setSessionId = (agentId: string, sessionId: string) => {
    sessionIdByAgent.value[agentId] = sessionId
    _persistSessionIds()
  }

  // 确保指定 Agent 有会话 ID（没有则生成并持久化后返回）。
  //
  // 用途：子 Agent 的 SSE 请求要带 context_id —— 后端的「入库待补槽位」与
  // 「上一轮蓝海结果」都**按会话隔离**，不带就会退化成全局共享（多会话串数据），
  // 而且「追问 → 用户补充 → 完成入库」这种多轮补齐也无从进行。
  const ensureSessionId = (agentId: string): string => {
    const existing = sessionIdByAgent.value[agentId]
    if (existing) return existing
    const generated = `${agentId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setSessionId(agentId, generated)
    return generated
  }

  // 清除指定 Agent 的会话 ID（新开对话）
  const clearSessionId = (agentId: string) => {
    delete sessionIdByAgent.value[agentId]
    _persistSessionIds()
  }

  // 当前 Agent 的消息列表（供 ChatPanel 绑定）
  const messages = computed(() => {
    return messagesByAgent.value[activeAgentId.value] || []
  })

  // 设置当前 Agent（切换 Agent 时调用，后续 addMessage 都写入该 Agent）
  const setActiveAgent = (agentId: string) => {
    activeAgentId.value = agentId
    if (!messagesByAgent.value[agentId]) {
      messagesByAgent.value[agentId] = []
    }
  }

  // 获取指定 Agent 的消息列表（无则返回空数组）
  const getMessages = (agentId: string): Message[] => {
    return messagesByAgent.value[agentId] || []
  }

  // 添加消息到当前激活的 Agent 对话区
  const addMessage = (msg: Message, agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    if (!messagesByAgent.value[targetId]) {
      messagesByAgent.value[targetId] = []
    }
    const timestamp = Date.now()
    messagesByAgent.value[targetId].push({
      ...msg,
      timestamp,
    })
    // ★ 记「哪个对话区刚被提问」——语音播报靠它区分「本轮回复」与「历史回复」
    if (msg.role === 'user') {
      lastUserMessage.value = { agentId: targetId, at: timestamp }
    }
  }

  // 向指定 Agent 的最后一条消息追加文本（流式渲染）
  const appendToLastMessage = (delta: string, agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    const list = messagesByAgent.value[targetId]
    if (!list || list.length === 0) return
    const last = list[list.length - 1]
    last.content = (last.content || '') + delta
  }

  /**
   * 回填「最后一条消息」的结构化结果（收到 SSE meta 事件时调用）。
   *
   * 有了它，一条对话消息才同时具备两副面孔：
   * - content      → 正文（人话清单，永远可读）
   * - displayType/data → 结论卡数据源（结构化、可渲染成卡片）
   */
  const setLastMessageResult = (displayType: string, data: any, agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    const list = messagesByAgent.value[targetId]
    if (!list || list.length === 0) return
    const last = list[list.length - 1]
    last.displayType = displayType
    last.data = data
  }

  // 从当前 Agent 的消息列表中移除指定索引的消息
  const removeMessage = (index: number, agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    const list = messagesByAgent.value[targetId]
    if (list) {
      list.splice(index, 1)
    }
  }

  // 清空当前 Agent 的会话
  const clearMessages = (agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    messagesByAgent.value[targetId] = []
  }

  // 清空所有 Agent 的会话
  const clearAllMessages = () => {
    messagesByAgent.value = {}
  }

  // 初始化：恢复持久化的 sessionId
  loadSessionIds()

  return {
    messagesByAgent,
    activeAgentId,
    messages,
    sessionIdByAgent,
    lastUserMessage,
    setActiveAgent,
    getMessages,
    getSessionId,
    setSessionId,
    ensureSessionId,
    clearSessionId,
    addMessage,
    appendToLastMessage,
    setLastMessageResult,
    removeMessage,
    clearMessages,
    clearAllMessages,
  }
})

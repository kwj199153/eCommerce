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
    messagesByAgent.value[targetId].push({
      ...msg,
      timestamp: Date.now(),
    })
  }

  // 向指定 Agent 的最后一条消息追加文本（流式渲染）
  const appendToLastMessage = (delta: string, agentId?: string) => {
    const targetId = agentId || activeAgentId.value || 'default'
    const list = messagesByAgent.value[targetId]
    if (!list || list.length === 0) return
    const last = list[list.length - 1]
    last.content = (last.content || '') + delta
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
    setActiveAgent,
    getMessages,
    getSessionId,
    setSessionId,
    clearSessionId,
    addMessage,
    appendToLastMessage,
    removeMessage,
    clearMessages,
    clearAllMessages,
  }
})

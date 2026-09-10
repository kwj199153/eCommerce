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

  return {
    messagesByAgent,
    activeAgentId,
    messages,
    setActiveAgent,
    getMessages,
    addMessage,
    removeMessage,
    clearMessages,
    clearAllMessages,
  }
})

<template>
  <div class="agent-list">
    <div class="section-title">Agent 群</div>
    <a-menu
      mode="inline"
      :selectedKeys="[currentAgentId]"
      @click="handleSelectAgent"
    >
      <a-menu-item
        v-for="agent in agentList"
        :key="agent.id"
        :disabled="agent.status === 'coming_soon'"
      >
        <component :is="agent.icon" />
        <span>{{ agent.name }}</span>
        <a-tag
          v-if="agent.status === 'active'"
          color="green"
          size="small"
          style="margin-left: auto"
        >
          可用
        </a-tag>
        <a-tag
          v-else-if="agent.status === 'coming_soon'"
          color="default"
          size="small"
          style="margin-left: auto"
        >
          即将上线
        </a-tag>
      </a-menu-item>
    </a-menu>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()

// Agent 列表（从 store 获取）
const agentList = computed(() => agentStore.agentList)

// 当前选中的 Agent ID
const currentAgentId = computed(() => agentStore.currentAgent?.id || '')

// 选择 Agent
const handleSelectAgent = ({ key }: { key: string }) => {
  const agent = agentList.value.find(a => a.id === key)
  if (agent && agent.status !== 'coming_soon') {
    agentStore.setCurrentAgent(agent)
  }
}
</script>

<style scoped>
.agent-list {
  padding: 8px 0;
}

.section-title {
  padding: 12px 16px 8px;
  font-size: 13px;
  font-weight: 500;
  color: #8c8c8c;
}

:deep(.ant-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: 2px 8px;
  border-radius: 6px;
}

:deep(.ant-menu-item .anticon) {
  font-size: 16px;
  margin-right: 10px;
}
</style>

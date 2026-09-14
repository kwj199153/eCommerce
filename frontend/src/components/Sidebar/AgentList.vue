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

// Agent 列表（从 store 获取，排除「店秘书」——它已由左上角 Logo「店管家 AI」作为唯一入口）
const agentList = computed(() => agentStore.agentList.filter(a => a.id !== 'secretary'))

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
  padding: var(--space-8) 0;
}

.section-title {
  padding: var(--space-12) var(--space-16) var(--space-8);
  font-size: var(--font-size-13);
  font-weight: 500;
  color: var(--text-tertiary);
}

:deep(.ant-menu-item) {
  height: 40px;
  line-height: 40px;
  margin: var(--space-2) var(--space-8);
  border-radius: var(--radius-6);
}

:deep(.ant-menu-item .anticon) {
  font-size: var(--font-size-16);
  margin-right: var(--space-10);
}
</style>

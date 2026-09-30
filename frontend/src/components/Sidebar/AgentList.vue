<template>
  <div class="agent-list" data-tour="tour-agent-list">
    <div class="sidebar-section-title">Agent 群</div>
    <a-menu
      class="sidebar-nav-menu"
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
/* ★ 第 260 轮：分组标题与菜单项的**行高 / 间距**不再在这里定义 ——
   唯一真源是 `src/styles/sidebar-nav.css`
   （`.sidebar-section-title` 与 `.sidebar-nav-menu`）。
   原先这里的两条 `:deep()` 规则与 KnowledgeBase.vue 里那份**逐字重复**，
   而两份容器的纵向 padding 叠加后，让三个分组标题的上间距实测为 8 / 18 / 2
   —— 看起来就是「三个标题行高度不一致」。
   容器纵向 padding 清零：分组之间的留白改由标题自身的 margin-top 统一决定。
   结构由 scripts/check-sidebar-layout.cjs 钉住，几何由
   scripts/cdp-sidebar-layout-probe.mjs 在真实浏览器里钉住。 */
.agent-list {
  padding: 0;
}
</style>

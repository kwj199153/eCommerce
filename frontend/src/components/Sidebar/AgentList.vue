<template>
  <div
    class="agent-list"
    data-tour="tour-agent-list"
  >
    <div class="sidebar-section-title">
      <span class="section-label">数字员工</span>
      <!-- 能力广场（第 371 轮引入，第 376 轮换位）：
           原来它是菜单里的**最后一项**，紧接着「运营复盘师」—— 结果被读成「第八个员工」，
           而它其实是**陈列面入口**（看每个员工会什么），不是员工本身。
           现在挪到分组标题行的右端：与整个分组平级，语义对；同时菜单少一行 34px。
           `data-tour` 锚点不动（`tour-agent-list` 仍挂在本组件根节点上）。 -->
      <button
        class="section-action"
        type="button"
        title="能力广场 · 看看每个数字员工现在就能做什么"
        aria-label="打开能力广场"
        @click="plazaOpen = true"
      >
        <AppstoreOutlined />
      </button>
    </div>
    <a-menu
      class="sidebar-nav-menu"
      mode="inline"
      :selected-keys="[currentAgentId]"
      @click="handleSelectAgent"
    >
      <a-menu-item
        v-for="agent in agentList"
        :key="agent.id"
        :disabled="agent.status === 'coming_soon'"
        :title="agent.description"
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

    <AbilityPlazaDrawer v-model:open="plazaOpen" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { AppstoreOutlined } from '@ant-design/icons-vue'

import { useAgentStore } from '@/stores/agent'
import AbilityPlazaDrawer from '@/components/AbilityPlaza/AbilityPlazaDrawer.vue'

const agentStore = useAgentStore()

/**
 * 能力广场抽屉的开关（抽屉组件自包含，不往上抛事件）。
 * ★ 第 376 轮：入口从菜单项改成「分组标题行右端的图标按钮」⇒ 不再需要
 *   `ABILITY_PLAZA_KEY` 这类"假员工键"，也不会再被 `handleSelectAgent` 当成员工处理。
 */
const plazaOpen = ref(false)

// Agent 列表（从 store 获取，排除「店秘书」——它已由左上角 Logo「店管管」作为唯一入口）
const agentList = computed(() => agentStore.agentList.filter(a => a.id !== 'secretary'))

// 当前选中的 Agent ID
const currentAgentId = computed(() => agentStore.currentAgent?.id || '')

// 选择 Agent
// ★ 第 376 轮：能力广场的拦截分支已随菜单项一起删除（入口改到分组标题行右端，
//   走 `@click="plazaOpen = true"`，不再经过本函数）。菜单里现在**只有**员工。
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

<template>
  <div
    class="agent-list"
    data-tour="tour-agent-list"
  >
    <div class="sidebar-section-title">
      数字员工
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

      <!-- 能力广场（第 371 轮）：技能**陈列**面。
           与「Skill 仓库」是同一份数据源的相反视角 —— 仓库答「这条技能对不对」，
           广场答「我能用它做什么」。入口刻意放进本菜单（而不是新起一个分组）：
           `check-sidebar-layout.cjs` 的 S6a/S6b 判「恰好 3 处分组标题 / 3 处分节菜单」。
           它的 key 不是任何 agent id，`handleSelectAgent` 里先于查表拦截。 -->
      <a-menu-item
        :key="ABILITY_PLAZA_KEY"
        title="看看每个数字员工现在就能做什么"
      >
        <AppstoreOutlined />
        <span>能力广场</span>
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

/**
 * 「能力广场」入口在菜单里的 key。
 *
 * ★ 必须不可能与任何 agent id 相等（那些都是 kebab-case 业务名），
 *   否则会被下面的 `agentList.find()` 当成一个员工。
 */
const ABILITY_PLAZA_KEY = '__ability-plaza__'

const agentStore = useAgentStore()

/** 能力广场抽屉的开关（抽屉组件自包含，不往上抛事件） */
const plazaOpen = ref(false)

// Agent 列表（从 store 获取，排除「店秘书」——它已由左上角 Logo「店管家 AI」作为唯一入口）
const agentList = computed(() => agentStore.agentList.filter(a => a.id !== 'secretary'))

// 当前选中的 Agent ID
const currentAgentId = computed(() => agentStore.currentAgent?.id || '')

// 选择 Agent
const handleSelectAgent = ({ key }: { key: string }) => {
  // ★ 能力广场是**入口**不是「员工」：先于查表拦截，且**不设高亮**
  //   （`:selected-keys` 仍停在当前员工）—— 否则关掉抽屉后菜单会显示
  //   「选中了能力广场」，而它并不对应任何员工。
  if (key === ABILITY_PLAZA_KEY) {
    plazaOpen.value = true
    return
  }
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

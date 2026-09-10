<template>
  <a-layout
    class="workspace-container"
    :class="{ 'review-data-mode': isReviewDataMode, 'listing-data-mode': isReviewDataMode && isListingAgent }"
  >
    <!-- 左侧边栏 -->
    <a-layout-sider
      :width="260"
      :collapsed="sidebarCollapsed"
      theme="light"
      class="sidebar"
    >
      <!-- Logo 区域 + 店铺群触发器 -->
      <div class="logo-row">
        <div class="logo-brand">
          <h3 v-if="!sidebarCollapsed" class="logo-title">
            店管家 AI
            <span v-if="currentShop" class="logo-shop-name">· {{ currentShop.name }}</span>
          </h3>
          <h3 v-else class="logo-title">店</h3>
        </div>
        <!-- 店铺群小图标（右上角） -->
        <a-popover
          v-model:open="shopPopoverVisible"
          trigger="click"
          placement="bottomRight"
          :overlayStyle="{ width: '340px' }"
        >
          <template #content>
            <ShopPopoverContent @close="shopPopoverVisible = false" />
          </template>
          <button class="shop-trigger-btn" :class="{ active: shopPopoverVisible }">
            <ShopOutlined />
            <span v-if="!sidebarCollapsed" class="shop-trigger-count">{{ shopCount }}</span>
          </button>
        </a-popover>
      </div>

      <!-- Agent 群 -->
      <SidebarAgentList />

      <!-- 资料库 -->
      <SidebarKnowledgeBase @navigate="handleKnowledgeNavigate" />

      <!-- 分隔线 -->
      <a-divider style="margin: 8px 0" />

      <!-- 底部账户菜单 -->
      <SidebarAccountMenu :sidebar-collapsed="sidebarCollapsed" />
    </a-layout-sider>

    <!-- 中间内容区 -->
    <a-layout class="main-content">
      <!-- 顶部栏：折叠 | 工具栏 | 消息/账户 -->
      <a-layout-header class="header">
        <div class="header-left">
          <!-- 折叠按钮 -->
          <a-button
            type="text"
            @click="toggleSidebar"
            class="collapse-btn"
          >
            <MenuUnfoldOutlined v-if="sidebarCollapsed" />
            <MenuFoldOutlined v-else />
          </a-button>

          <!-- 紧凑工具栏（选中 Agent 且在对话视图时显示） -->
          <div v-if="currentAgent && currentView === 'chat'" class="inline-toolbar">
            <span class="toolbar-agent-label">{{ currentAgent.name }}</span>

            <!-- 竞品监控员：顶部不展示工具卡片（看数面板收敛到监控看板；推理走输入框上方 chip） -->
            <!-- 运营复盘师/广告分析师：仅对话模式显示工具按钮（数据模式看宽看板自带 Tab 切换） -->
            <template v-if="!isCompetitorIntelAgent && !(isReviewAgent && reviewMode === 'data') && !(isAdAnalyst && reviewMode === 'data')">
              <a-divider type="vertical" :margin="8" />
              <div class="toolbar-tools">
                <div
                  v-for="tool in currentAgentTools"
                  :key="tool.id"
                  class="toolbar-tool-btn"
                  :title="`${tool.name} — ${tool.description}`"
                  :style="{
                    backgroundColor: currentSelectedTool?.id === tool.id ? '#1890ff' : 'transparent',
                    color: currentSelectedTool?.id === tool.id ? '#fff' : (tool.status === 'coming_soon' ? '#d9d9d9' : '#595959'),
                    opacity: tool.status === 'coming_soon' ? 0.4 : 1,
                    cursor: tool.status === 'coming_soon' ? 'not-allowed' : 'pointer',
                  }"
                  @click="handleToolbarToolClick(tool)"
                >
                  <span class="tb-icon">{{ tool.icon }}</span>
                  <span class="tb-name">{{ tool.name }}</span>
                </div>
              </div>
            </template>
          </div>

          <!-- 载入产品按钮（仅 Listing 优化师 / AIGC 媒体生成器，仅 chat 视图，避免资料库里误显示） -->
          <ProductLoaderButton
            v-if="showProductLoader && currentView === 'chat'"
            :model-value="currentWorkingProduct"
            @select="onWorkspaceProductSelect"
          />

          <!-- 载入选品按钮（仅选品分析师·仅 chat 视图；切到资料库时由 ChatPanel 内 chip 完成评估，不再需要） -->
          <CandidateLoaderButton
            v-else-if="showCandidateLoader && currentView === 'chat'"
            :model-value="currentWorkingCandidate"
            @select="onWorkspaceCandidateSelect"
          />

          <!-- 未选 Agent 提示（仅对话视图） -->
          <span v-else-if="currentView === 'chat'" class="no-agent-hint">选择左侧 Agent 开始</span>
        </div>
        <div class="header-right">
          <!-- 宽看板 Agent（运营复盘师 / Listing 优化师）：双模式切换（对话模式 / 大屏模式[复盘]·文案模式[Listing]） -->
          <div v-if="isWideBoardAgent && currentView === 'chat'" class="mode-switch">
            <button
              class="mode-switch-btn"
              :class="{ active: reviewMode === 'chat' }"
              title="对话模式：中间对话宽，右侧看板窄"
              @click="setReviewMode('chat')"
            >
              <MessageOutlined /> 对话模式
            </button>
            <button
              class="mode-switch-btn"
              :class="{ active: reviewMode === 'data' }"
              title="大屏模式：右侧看板占大部分宽度，对话压缩为窄侧栏"
              @click="setReviewMode('data')"
            >
              <AreaChartOutlined /> {{ isReviewAgent || isAdAnalyst ? '大屏模式' : '文案模式' }}
            </button>
          </div>

          <!-- 通知铃铛 -->
          <a-badge :count="0" dot>
            <BellOutlined style="font-size: 18px; cursor: pointer" />
          </a-badge>
        </div>
      </a-layout-header>

      <!-- 内容区：对话 / 知识库 / 产品库 -->
      <a-layout-content class="chat-area">
        <!-- Agent 对话视图（默认） -->
        <ChatPanel v-if="currentView === 'chat'" />

        <!-- 业务话术库视图 -->
        <FaqKnowledgeBase v-else-if="currentView === 'faq'" />

        <!-- 选品库视图（候选选品草稿池） -->
        <CandidateLibrary v-else-if="currentView === 'candidates'" />

        <!-- 产品/Listing 库视图 -->
        <ProductLibrary v-else-if="currentView === 'products'" />

        <!-- 营销素材库视图 -->
        <AssetLibrary v-else-if="currentView === 'assets'" />

        <!-- 平台规则库视图 -->
        <PlatformRules v-else-if="currentView === 'rules'" />

        <!-- 竞品监控工作台视图（一套监控池 → 多面板） -->
        <CompetitorMonitor v-else-if="currentView === 'monitor'" />
      </a-layout-content>
    </a-layout>

    <!-- 右侧任务配置面板（仅对话视图显示） -->
    <a-layout-sider
      v-if="currentView === 'chat'"
      :width="isWideBoardAgent ? 528 : 340"
      :collapsed="rightPanelCollapsed"
      :collapsed-width="0"
      reverse-direction
      collapsible
      theme="light"
      class="right-panel"
      :trigger="null"
      collapse-renderer
    >
      <TaskConfigPanel
        :key="currentAgent?.id || 'none'"
        :currentTool="currentSelectedTool"
        @startAnalysis="handleToolAnalysis"
        @clearTool="() => { currentSelectedTool = null }"
      />
    </a-layout-sider>

    <!-- 记忆与进化 Drawer（全局，由侧栏菜单触发） -->
    <MemoryEvolution v-model:open="memoryDrawerOpen" />

    <!-- 设置 Drawer（全局，由侧栏菜单触发） -->
    <Settings v-model:open="settingsDrawerOpen" />
  </a-layout>
</template>

<script setup lang="ts">
import { ref, provide, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  BellOutlined,
  ShopOutlined,
  MessageOutlined,
  AreaChartOutlined,
} from '@ant-design/icons-vue'

import SidebarAgentList from '@/components/Sidebar/AgentList.vue'
import SidebarKnowledgeBase from '@/components/Sidebar/KnowledgeBase.vue'
import SidebarAccountMenu from '@/components/Sidebar/AccountMenu.vue'
import ShopPopoverContent from '@/components/Sidebar/ShopPopoverContent.vue'
import ChatPanel from '@/components/ChatPanel/index.vue'
import TaskConfigPanel from '@/components/TaskConfigPanel/index.vue'
import FaqKnowledgeBase from '@/components/KnowledgeBase/FaqKnowledgeBase.vue'
import CandidateLibrary from '@/components/KnowledgeBase/CandidateLibrary.vue'
import ProductLibrary from '@/components/KnowledgeBase/ProductLibrary.vue'
import AssetLibrary from '@/components/KnowledgeBase/AssetLibrary.vue'
import PlatformRules from '@/components/KnowledgeBase/PlatformRules.vue'
import CompetitorMonitor from '@/components/KnowledgeBase/CompetitorMonitor.vue'
import MemoryEvolution from '@/views/MemoryEvolution.vue'
import Settings from '@/views/Settings.vue'
import type { ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import { getAgentTools } from '@/components/ChatPanel/tools/toolDefinitions'

import { useAgentStore } from '@/stores/agent'
import { useShopStore } from '@/stores/shop'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useAssetLibraryStore } from '@/stores/assetLibrary'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import ProductLoaderButton from '@/components/TaskConfigPanel/configs/ProductLoaderButton.vue'
import CandidateLoaderButton from '@/components/TaskConfigPanel/configs/CandidateLoaderButton.vue'

const router = useRouter()
const agentStore = useAgentStore()
const shopStore = useShopStore()
const productLibraryStore = useProductLibraryStore()
const assetLibraryStore = useAssetLibraryStore()
const candidateLibraryStore = useCandidateLibraryStore()

// 侧边栏状态
const sidebarCollapsed = ref(false)
const rightPanelCollapsed = ref(false)
const memoryDrawerOpen = ref(false)
const settingsDrawerOpen = ref(false)

// 店铺群 Popover 状态
const shopPopoverVisible = ref(false)

// 店铺数量
const shopCount = computed(() => shopStore.shopList.length)

// 当前选中店铺（用于标题栏显示）
const currentShop = computed(() => shopStore.currentShop)

// 内容区视图切换：chat（Agent 对话）| faq（业务话术库）| products（产品/Listing 库）| assets（营销素材库）| rules（平台规则库）| monitor（竞品监控工作台）
const currentView = ref<'chat' | 'faq' | 'candidates' | 'products' | 'assets' | 'rules' | 'monitor'>('chat')

// 当前选中的工具（用于右侧配置面板）
const currentSelectedTool = ref<ToolDefinition | null>(null)

// 向子组件提供工具选择状态
provide('currentSelectedTool', currentSelectedTool)
provide('setSelectedTool', (tool: ToolDefinition | null) => {
  currentSelectedTool.value = tool
  // 选中工具时自动展开右侧面板
  if (tool) rightPanelCollapsed.value = false
})

// ====== 当前工作商品（Agent 级共享上下文）======
// 所有 Listing 工具共享同一个已选商品，切换工具不丢失
const currentWorkingProduct = ref<any>(null)
provide('workingProduct', currentWorkingProduct)
provide('setWorkingProduct', (product: any) => {
  currentWorkingProduct.value = product
})
provide('clearWorkingProduct', () => {
  currentWorkingProduct.value = null
})

// ====== 当前工作候选（选品分析师·载入选品，Agent 级共享上下文）======
// 单选一个候选库选品作为评估主角，供【市场可行性 / 上架建议】chip 使用；未载入时为 null
const currentWorkingCandidate = ref<any>(null)
provide('workingCandidate', currentWorkingCandidate)
provide('setWorkingCandidate', (cand: any) => {
  currentWorkingCandidate.value = cand
})
provide('clearWorkingCandidate', () => {
  currentWorkingCandidate.value = null
})
// 提供右侧面板收缩控制
provide('toggleRightPanel', () => {
  rightPanelCollapsed.value = !rightPanelCollapsed.value
})
provide('rightPanelCollapsed', rightPanelCollapsed)

// 当前 Agent（响应式）
const currentAgent = computed(() => agentStore.currentAgent)

// 竞品监控员：顶部工具已改为「监控看板 + 输入框上方 chip + 右侧竞品选择」的统一入口
const isCompetitorIntelAgent = computed(() => currentAgent.value?.id === 'competitor-intel')

// 运营复盘师：右侧面板切换为「纯数据看板」模式，需比普通配置面板更宽以容纳图表
const isReviewAgent = computed(() => currentAgent.value?.id === 'review-analyst')

// Listing 优化师：右侧为「Listing 统一工作区」，同样需要加宽面板容纳多模块编辑
const isListingAgent = computed(() => currentAgent.value?.id === 'listing-generator')

// 广告分析师：右侧为「广告大屏看板」，6 Tab 数据面板
const isAdAnalyst = computed(() => currentAgent.value?.id === 'ad-analysis')

// 需要「宽看板」的 Agent（复盘数据看板 / Listing 统一工作区 / 广告大屏看板）
const isWideBoardAgent = computed(() => isReviewAgent.value || isListingAgent.value || isAdAnalyst.value)

// ====== 宽看板 Agent·双模式布局 ======
// chat = 对话优先（中间对话宽，右侧看板窄）
// data = 面板优先（右侧看板占大部分宽度，对话压缩成窄侧边栏）
const REVIEW_MODE_KEY = 'review-analyst-layout-mode'
const reviewMode = ref<'chat' | 'data'>(
  (localStorage.getItem(REVIEW_MODE_KEY) as 'chat' | 'data') || 'chat'
)
function setReviewMode(mode: 'chat' | 'data') {
  reviewMode.value = mode
  localStorage.setItem(REVIEW_MODE_KEY, mode)
}
// 仅宽看板 Agent + 面板优先模式 + 右侧面板未收起时，才应用宽看板布局
const isReviewDataMode = computed(
  () => isWideBoardAgent.value && reviewMode.value === 'data' && !rightPanelCollapsed.value
)

// 向 ListingBoard / ReviewConfig 提供当前「对话/文案(数据)」模式
provide('reviewMode', reviewMode)

// 当前 Agent 的工具列表（广告分析师：出价建议/预算分配已移至输入框上方 chip，顶部不再重复展示）
const AD_TOOLBAR_EXCLUDE = new Set(['bid-suggest', 'budget-alloc'])
const currentAgentTools = computed(() => {
  const tools = currentAgent.value ? getAgentTools(currentAgent.value.id) : []
  if (currentAgent.value?.id === 'ad-analysis') {
    return tools.filter(t => !AD_TOOLBAR_EXCLUDE.has(t.id))
  }
  return tools
})

// 是否显示「载入产品」按钮（仅 Listing 优化师 / AIGC 媒体生成器）
const showProductLoader = computed(() => {
  const agentId = currentAgent.value?.id
  return agentId === 'listing-generator' || agentId === 'aigc-media'
})

// 是否显示「载入选品」按钮（仅选品分析师）—— 载入选品库中的未上架候选作为评估主角
const showCandidateLoader = computed(() => {
  return currentAgent.value?.id === 'product-research'
})

// 切换左侧边栏
const toggleSidebar = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

// 资料库导航切换
const handleKnowledgeNavigate = (key: string) => {
  currentView.value = key as 'faq' | 'candidates' | 'products' | 'assets' | 'rules' | 'monitor'
  // 切换到资料库视图时，关闭右侧配置面板（工具面板不适用）
  if (key !== 'chat') {
    currentSelectedTool.value = null
    rightPanelCollapsed.value = true
  }
}

// 点击 Agent 时自动切回对话视图 + 清空当前工具选择
// 同时监听 currentAgent 引用变化 + agentClickCounter（处理同一 agent 重复点击场景）
watch([() => agentStore.currentAgent, () => agentStore.agentClickCounter], () => {
  if (agentStore.currentAgent) {
    // 切换 Agent 时必须清空当前工具，否则右侧配置面板会残留旧 Agent 的配置
    currentSelectedTool.value = null
    // 离开选品分析师：清空「载入选品」工作候选，避免携带到其它 Agent
    if (agentStore.currentAgent.id !== 'product-research') {
      currentWorkingCandidate.value = null
    }
    if (currentView.value !== 'chat') {
      currentView.value = 'chat'
      rightPanelCollapsed.value = false
    }
  }
})

// 监听来自 ChatPanel 的导航事件（如：蓝海挖掘结果→跳转产品库）
// 监听来自产品库的 Listing 优化 / AIGC 生成 跳转请求
onMounted(() => {
  window.addEventListener('view-navigate', handleViewNavigate as EventListener)
  window.addEventListener('product-listing-optimize', handleListingOptimize as EventListener)
  window.addEventListener('product-aigc-launch', handleAigcLaunch as EventListener)
  window.addEventListener('monitor-launch-analysis', handleMonitorLaunchAnalysis as EventListener)
  window.addEventListener('open-memory-drawer', () => { memoryDrawerOpen.value = true })
  window.addEventListener('open-settings-drawer', () => { settingsDrawerOpen.value = true })
  // 预加载资料库数据（选品库 + 产品库 + 素材库），确保各消费方组件打开时数据已就绪
  candidateLibraryStore.fetchItems()
  productLibraryStore.fetchItems()
  assetLibraryStore.fetchItems()
})
onUnmounted(() => {
  window.removeEventListener('view-navigate', handleViewNavigate as EventListener)
  window.removeEventListener('product-listing-optimize', handleListingOptimize as EventListener)
  window.removeEventListener('product-aigc-launch', handleAigcLaunch as EventListener)
  window.removeEventListener('monitor-launch-analysis', handleMonitorLaunchAnalysis as EventListener)
})

const handleViewNavigate = (e: Event) => {
  const detail = (e as CustomEvent).detail
  if (detail?.view) {
    handleKnowledgeNavigate(detail.view)
  }
}

/**
 * 通用落地：把某个产品载入工作区，并切换到目标 Agent（仅切 Agent + 载入产品，不自动选工具）
 * 供产品库行的 Listing 优化 / AIGC 媒体生成两个跳转按钮使用。
 * 时序关键：先清工具 → 切对话视图 → 载产品 → 再切 Agent，避免 Vue 响应式批量更新产生中间状态。
 */
const launchProductToAgent = (product: any, agentId: string) => {
  if (!product) return
  // Step 0: 先清除旧选中状态（防止多选 / 残留旧 Agent 工具）
  currentSelectedTool.value = null
  // Step 1: 切到对话视图
  currentView.value = 'chat'
  rightPanelCollapsed.value = false
  // Step 2: 载入全局工作商品
  currentWorkingProduct.value = product
  // Step 3: 若目标 Agent 未选中则切换（Agent 侧 watch 会自动把 view 带回 chat）
  if (currentAgent.value?.id !== agentId) {
    const targetAgent = agentStore.agentList.find((a: any) => a.id === agentId)
    if (targetAgent) agentStore.setCurrentAgent(targetAgent)
  }
}

/**
 * 处理产品库→Listing 优化跳转（跳 Listing 优化师 + 载入产品）
 */
const handleListingOptimize = (e: Event) => {
  launchProductToAgent((e as CustomEvent).detail, 'listing-generator')
}

/**
 * 处理产品库→AIGC 媒体生成跳转（跳 AIGC Agent + 载入产品）
 */
const handleAigcLaunch = (e: Event) => {
  launchProductToAgent((e as CustomEvent).detail, 'aigc-media')
}

/** 清除当前工作商品 */
const clearWorkingProduct = () => {
  currentWorkingProduct.value = null
}

/**
 * 竞品监控看板「发起 AI 分析」跳转：
 * 从监控池视图跳到竞品监控员 Agent 对话页。勾选 ASIN 已在看板页写入 pool.selectedAsins，
 * 这里只负责切 Agent + 切回对话视图 + 展开右侧竞品选择面板，右侧面板会自动读池里已圈选的竞品。
 */
const handleMonitorLaunchAnalysis = () => {
  // Step 0: 清除旧工具选择
  currentSelectedTool.value = null

  // Step 1: 若当前不是竞品监控员，先切换到该 Agent
  if (currentAgent.value?.id !== 'competitor-intel') {
    const targetAgent = agentStore.agentList.find((a: any) => a.id === 'competitor-intel')
    if (targetAgent) agentStore.setCurrentAgent(targetAgent)
  }

  // Step 2: 切回对话视图 + 展开右侧配置面板（下一帧等 Agent/视图就绪）
  currentView.value = 'chat'
  rightPanelCollapsed.value = false
  nextTick(() => { rightPanelCollapsed.value = false })
}

/** 从产品库载入商品（顶部按钮触发） */
const onWorkspaceProductSelect = (product: any) => {
  if (!product) {
    // 清除
    currentWorkingProduct.value = null
    return
  }
  currentWorkingProduct.value = product
  // 如果右侧面板折叠了，展开它
  rightPanelCollapsed.value = false
}

/** 从选品库载入候选（选品分析师顶部按钮触发）：写入当前工作候选供评估 chip 消费 */
const onWorkspaceCandidateSelect = (cand: any) => {
  currentWorkingCandidate.value = cand || null
  // 如果右侧面板折叠了，展开它
  rightPanelCollapsed.value = false
}

// 工具栏点击处理
const handleToolbarToolClick = (tool: ToolDefinition) => {
  if (tool.status === 'coming_soon') return
  // 切换选中状态（再次点击同一工具不取消）
  if (currentSelectedTool.value?.id !== tool.id) {
    currentSelectedTool.value = tool
    rightPanelCollapsed.value = false
  }
}

// 工具按钮样式（用 inline style 彻底排除 CSS 污染导致的伪多选）
const getToolBtnStyle = (tool: ToolDefinition): Record<string, string> => {
  const isActive = currentSelectedTool.value?.id === tool.id
  const isDisabled = tool.status === 'coming_soon'
  return {
    backgroundColor: isActive ? '#1890ff' : 'transparent',
    color: isActive ? '#fff' : isDisabled ? '#d9d9d9' : '#595959',
    fontWeight: isActive ? '500' : '400',
    opacity: isDisabled ? '0.4' : '1',
    cursor: isDisabled ? 'not-allowed' : 'pointer',
  }
}

// 处理工具分析请求（从右侧面板触发）
const handleToolAnalysis = (params: any) => {
  // 通过事件总线或 store 传递给 ChatPanel 执行
  window.dispatchEvent(new CustomEvent('tool-analysis', {
    detail: { tool: currentSelectedTool.value, params }
  }))
}
</script>

<style scoped>
.workspace-container {
  height: 100vh;
}

/* 左侧边栏 */
.sidebar {
  border-right: 1px solid var(--border-base);
  background-color: var(--bg-sidebar);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
}

:deep(.ant-layout-sider-children) {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 100%;
}

.logo-row {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-base);
  padding: 0 12px 0 16px;
  flex-shrink: 0;
}

.logo-brand {
  display: flex;
  align-items: center;
  min-width: 0;
  flex: 1;
}

.logo-row h3 {
  margin: 0;
}

.logo-title {
  color: var(--primary);
  font-size: 16px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.logo-shop-name {
  color: var(--text-tertiary);
  font-size: 13px;
  font-weight: 400;
  margin-left: 4px;
}

/* 店铺群触发按钮（右上角小图标） */
.shop-trigger-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 32px;
  height: 32px;
  border: 1.5px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-elevated);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 15px;
  transition: all 0.2s ease;
  flex-shrink: 0;
  padding: 0;
}

.shop-trigger-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-active-light);
  box-shadow: 0 2px 6px rgba(24, 144, 255, 0.15);
}

.shop-trigger-btn.active {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-active-light);
}

.shop-trigger-count {
  font-size: 11px;
  font-weight: 600;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  padding: 0 4px;
}

/* 主内容区 */
.main-content {
  background-color: var(--bg-elevated);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  min-width: 0;
  /* 双模式切换（对话优先 ↔ 数据分析）平滑过渡 */
  transition: flex-basis 0.25s cubic-bezier(0.645, 0.045, 0.355, 1),
              width 0.25s cubic-bezier(0.645, 0.045, 0.355, 1);
}

.header {
  background-color: var(--bg-toolbar);
  color: var(--text-primary);
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-base);
  height: 48px;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
  z-index: 10;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.collapse-btn {
  font-size: 18px;
  flex-shrink: 0;
  color: var(--text-secondary);
}

/* ===== Header 内嵌紧凑工具栏 ===== */
.inline-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.toolbar-agent-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.toolbar-tools {
  display: flex;
  align-items: center;
  gap: 2px;
  overflow-x: auto;
  overflow-y: hidden;
  flex: 1;
  min-width: 0;

  /* 隐藏滚动条 */
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.toolbar-tools::-webkit-scrollbar {
  display: none;
}

.toolbar-tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 8px;
  border: none;
  border-radius: 6px;
  background-color: transparent;
  white-space: nowrap;
  font-size: 12px;
  line-height: 1;
  flex-shrink: 0;
  color: var(--text-secondary);
  transition: background-color 0.15s ease, color 0.15s ease;
}

.toolbar-tool-btn:hover {
  background-color: var(--bg-active-light);
  color: var(--primary);
}

.tb-icon {
  font-size: 13px;
  line-height: 1;
  flex-shrink: 0;
}

.tb-name {
  font-size: 12px;
  line-height: 1;
}

/* 窄屏工具栏：隐藏按钮文字只显示 icon，避免被滚动隐藏 */
@media (max-width: 1400px) {
  .toolbar-tool-btn .tb-name { display: none; }
  .toolbar-tool-btn { padding: 0 6px; }
}
@media (max-width: 1100px) {
  .toolbar-agent-label { display: none; }
}

.no-agent-hint {
  font-size: 13px;
  color: var(--text-disabled);
  margin-left: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  color: var(--text-secondary);
}

/* ====== 运营复盘师·双模式切换按钮（对话优先 / 数据分析） ====== */
.mode-switch {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-right: 12px;
  padding: 2px;
  background: var(--bg-card-pill);
  border: 1px solid var(--border-base);
  border-radius: 8px;
  flex-shrink: 0;
}

.mode-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  white-space: nowrap;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.mode-switch-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover-light);
}
.mode-switch-btn.active {
  background: var(--primary);
  color: #fff;
  font-weight: 600;
}
.mode-switch-btn.active:hover {
  background: var(--primary-hover);
  color: #fff;
}

/* ====== 数据分析模式：右侧看板占大部分宽度，对话压缩成窄侧边栏 ====== */
.workspace-container.review-data-mode .main-content {
  flex: 0 0 400px !important;
  width: 400px !important;
  min-width: 400px !important;
  max-width: 400px !important;
}
.workspace-container.review-data-mode .right-panel {
  flex: 1 1 auto !important;
  width: auto !important;
  min-width: 0 !important;
  max-width: none !important;
}
/* 窄对话栏下隐藏顶部工具按钮（复盘看板自带 6 个 Tab 可直接切换视图）
   —— 但 Listing 优化师需保留工具栏：点工具 = 跳到工作区对应模块 */
.workspace-container.review-data-mode:not(.listing-data-mode) .inline-toolbar .toolbar-tools,
.workspace-container.review-data-mode:not(.listing-data-mode) .inline-toolbar .ant-divider {
  display: none !important;
}

/* 对话区 */
.chat-area {
  flex: 1;
  overflow: hidden;
  background-color: var(--bg-elevated);
}

/* 右侧任务配置面板 - WorkBuddy 风格平滑收缩 */
.right-panel {
  border-left: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
  color: var(--text-primary);
  transition: all 0.25s cubic-bezier(0.645, 0.045, 0.355, 1) !important;
  overflow: hidden;
}

.right-panel :deep(.ant-layout-sider-children) {
  overflow: hidden;
}

/* 隐藏 ant-design 默认的 trigger（我们用自定义按钮） */
.right-panel :deep(.ant-layout-sider-trigger) {
  display: none !important;
}
</style>

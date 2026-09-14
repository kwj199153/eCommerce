<template>
  <a-layout
    class="workspace-container"
    :class="{
      'review-data-mode': isReviewDataMode,
      'listing-data-mode': isReviewDataMode && isListingAgent,
      'aigc-data-mode': isReviewDataMode && isAigcAgent,
    }"
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
        <div class="logo-brand" :title="!sidebarCollapsed ? '回到店秘书' : ''" @click="goHome">
          <span class="logo-avatar"><RobotOutlined /></span>
          <span v-if="!sidebarCollapsed" class="logo-name">
            <span class="logo-title">店管家 AI</span>
            <span v-if="currentShop" class="logo-shop-name">· {{ currentShop.name }}</span>
          </span>
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
      <SidebarKnowledgeBase ref="knowledgeBaseRef" @navigate="handleKnowledgeNavigate" />

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
            <!-- 运营复盘师/广告分析师/AIGC：仅对话模式显示工具按钮（数据模式看宽看板自带 Tab 切换） -->
            <template v-if="!isSecretaryAgent && !isCompetitorIntelAgent && !(isReviewAgent && reviewMode === 'data') && !(isAdAnalyst && reviewMode === 'data') && !(isAigcAgent && reviewMode === 'data')">
              <a-divider type="vertical" :margin="8" />
              <div class="toolbar-tools">
                <div
                  v-for="tool in currentAgentTools"
                  :key="tool.id"
                  class="toolbar-tool-btn"
                  :title="`${tool.name} — ${tool.description}`"
                  :style="{
                    backgroundColor: currentSelectedTool?.id === tool.id ? SEM.primary : 'transparent',
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

          <!-- 圈选竞品按钮（仅竞品监控员·仅 chat 视图）
               大屏的六个追踪视角都读「监控池已圈选」，所以圈选入口收在顶部按钮里，
               右栏整块让给大屏 —— 对齐「对象驱动型 Agent 统一用载入主角入口」的约定。 -->
          <IntelPickButton
            v-else-if="isCompetitorIntelAgent && currentView === 'chat'"
          />

          <!-- 未选 Agent 提示（仅对话视图且确实未选 Agent） -->
          <span v-else-if="!currentAgent && currentView === 'chat'" class="no-agent-hint">选择左侧 Agent 开始</span>
        </div>
        <div class="header-right">
          <!-- 宽看板场景（复盘 / Listing / 广告 / 竞品监控 / AIGC）：双模式切换（对话模式 / 大屏模式；Listing 为文案模式）
               利润测算**不进**：它是工具级加宽（528），无大屏模式（详见 isWideProfitTool 注释）。 -->
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
              <AreaChartOutlined /> {{ isListingAgent ? '文案模式' : '大屏模式' }}
            </button>
          </div>

          <!-- 通知铃铛 -->
          <a-badge :count="0" dot>
            <BellOutlined style="font-size: 18px; cursor: pointer" />
          </a-badge>

          <!-- 语音播报开关（右上角喇叭）
               是否**显示**由 store 白名单决定（首期只有店秘书）—— 这里只判「功能开关 + 处于对话视图」，
               这样「扩展到其他 Agent」只需改 store 里的白名单一处。 -->
          <VoiceSpeakerButton
            v-if="VOICE_CLONE_ENABLED && currentView === 'chat' && currentAgent"
            :agent-id="currentAgent.id"
          />
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

        <!-- 竞品监控池视图（长期盯盘清单；与产品库内嵌的「对标竞品」区分） -->
        <MonitorPoolLibrary v-else-if="currentView === 'competitors'" />

        <!-- 营销素材库视图 -->
        <AssetLibrary v-else-if="currentView === 'assets'" />

        <!-- 平台规则库视图 -->
        <PlatformRules v-else-if="currentView === 'rules'" />
      </a-layout-content>
    </a-layout>

    <!-- 右侧任务配置面板（仅对话视图显示） -->
    <a-layout-sider
      v-if="currentView === 'chat' && !isSecretaryAgent"
      :width="isWidePanel ? 528 : 340"
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

    <!-- 划词翻译浮层（全局一次，选中英文商品文字即出译文） -->
    <SelectionTranslateLayer />
  </a-layout>
</template>

<script setup lang="ts">
import { SEM } from '@/theme/semantic'
import { ref, provide, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  BellOutlined,
  ShopOutlined,
  MessageOutlined,
  AreaChartOutlined,
  RobotOutlined,
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
import MonitorPoolLibrary from '@/components/KnowledgeBase/MonitorPoolLibrary.vue'
import AssetLibrary from '@/components/KnowledgeBase/AssetLibrary.vue'
import PlatformRules from '@/components/KnowledgeBase/PlatformRules.vue'
import IntelPickButton from '@/components/TaskConfigPanel/configs/IntelPickButton.vue'
import MemoryEvolution from '@/views/MemoryEvolution.vue'
import Settings from '@/views/Settings.vue'
import SelectionTranslateLayer from '@/components/Translate/SelectionTranslateLayer.vue'
import VoiceSpeakerButton from '@/components/common/VoiceSpeakerButton.vue'
import { VOICE_CLONE_ENABLED } from '@/config/featureFlags'
import type { ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import { getAgentTools } from '@/components/ChatPanel/tools/toolDefinitions'

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { useShopStore } from '@/stores/shop'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useAssetLibraryStore } from '@/stores/assetLibrary'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { usePlatformRulesStore } from '@/stores/platformRules'
import { useKnowledgeStore } from '@/stores/knowledge'
import ProductLoaderButton from '@/components/TaskConfigPanel/configs/ProductLoaderButton.vue'
import CandidateLoaderButton from '@/components/TaskConfigPanel/configs/CandidateLoaderButton.vue'

const router = useRouter()
const agentStore = useAgentStore()
const chatStore = useChatStore()
const shopStore = useShopStore()
const productLibraryStore = useProductLibraryStore()
const assetLibraryStore = useAssetLibraryStore()
const candidateLibraryStore = useCandidateLibraryStore()
const monitorPoolStore = useMonitorPoolStore()
const platformRulesStore = usePlatformRulesStore()
const knowledgeStore = useKnowledgeStore()

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

// 内容区视图切换：chat（Agent 对话）| faq（业务话术库）| candidates（选品库）| products（产品/Listing 库）| assets（营销素材库）| rules（平台规则库）
// 竞品监控看板已并入竞品监控员的右侧边栏，不再是独立视图
const currentView = ref<'chat' | 'faq' | 'candidates' | 'products' | 'competitors' | 'assets' | 'rules'>('chat')

/** 侧边栏资料库组件引用：供 CustomEvent 跳转（不经过菜单点击）时同步菜单高亮 */
const knowledgeBaseRef = ref<{ navigateTo: (key: string) => void } | null>(null)

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

// 店秘书（全局入口 · 编排层）：无工具卡片、无右侧配置面板，纯对话 + 自动调度
const isSecretaryAgent = computed(() => currentAgent.value?.id === 'secretary')

// 选品分析师·利润测算：这是**工具级**宽版，不是 Agent 级。
// 同一个 Agent 下还挂着「蓝海挖掘」，它是常规表单、不需要加宽 —— 所以必须用
// 「Agent + 当前选中工具」双重判定，只认 Agent 会把蓝海挖掘一起带宽。
// 利润测算有 13 个字段，340px 下只能纵向堆叠；改成 Excel 风格表格必须加宽。
//
// ⚠️ 它**只借宽度，不接大屏模式**（09-13 老板拍板）：
//    大屏是「吃剩余宽度」（右栏 = 视口 − 260 导航 − 400 对话区），窗口越宽右栏越大；
//    而利润测算的表格把「说明」列设成吃 100% 剩余 → 宽屏下被撑成一片空白
//    （1477px 实测：说明列 1216px，其中 1110px 是纯空白；「计算利润」按钮被推到 1100px 外）。
//    故宽度由 isWidePanel 单独判定，模式切换与大屏布局仍只认 isWideBoardAgent。
const isWideProfitTool = computed(
  () => currentAgent.value?.id === 'product-research' && currentSelectedTool.value?.id === 'profit-calc'
)

// AIGC 媒体生成器（3 工具）：与复盘/Listing/广告/竞品监控一样，接「对话模式 / 大屏模式」。
// 09-13 老板纠偏：AIGC 大屏**参照其他 Agent**，走 Workspace 顶栏 mode-switch（reviewMode 切 chat/data），
//   不要在每个工具配置窗口里自造「对话/大屏」按钮（AIGCMediaWrapper 头部按钮已删除）。
// 第 9 轮进一步细化：AIGC 用 **Agent 级**判定（与具体工具无关），点 AIGC Agent 就该显示顶栏 mode-switch，
// 不用先选「静态素材生成/脚本/视频」。3 个工具共用同一对「对话/大屏」按钮。
// 大屏模式 = 右栏「左右分栏」：左半边是表单（继续可见），右半边是预览窗口（图片网格/分镜卡片/视频播放器）。
const isAigcAgent = computed(() => currentAgent.value?.id === 'aigc-media')

// 需要「宽看板」场景（复盘 / Listing / 广告 / 竞品监控 / AIGC）
// —— 这些都同时拥有「对话模式 / 大屏模式」切换能力（顶栏 mode-switch + 整页看板布局）。
// AIGC 是 Agent 级判定（用 isAigcAgent）—— 点 AIGC Agent 即可见 mode-switch。
const isWideBoardAgent = computed(
  () =>
    isReviewAgent.value ||
    isListingAgent.value ||
    isAdAnalyst.value ||
    isCompetitorIntelAgent.value ||
    isAigcAgent.value
)

// 右栏「加宽」的判定：宽看板 Agent ∪ 宽版工具（利润测算）。
// 与上面 isWideBoardAgent 的唯一区别 —— **只加宽到固定 528，不给大屏模式**。
const isWidePanel = computed(
  () => isWideBoardAgent.value || isWideProfitTool.value
)

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
// 仅宽看板 Agent + 面板优先模式 + 右侧面板未收起时，才应用**整页**看板布局
// （中间对话压缩成窄边栏、右栏吃剩余宽度）。
// AIGC 也在这里：大屏模式下中间对话变窄，右栏预览窗口吃满剩余宽度（与其他看板 Agent 一致）。
const isReviewDataMode = computed(
  () => isWideBoardAgent.value && reviewMode.value === 'data' && !rightPanelCollapsed.value
)

// 向 ListingBoard / ReviewConfig 提供当前「对话/文案(数据)」模式
provide('reviewMode', reviewMode)

// 注：原先还 provide('isWidePanel') 让右栏自己决定「配置 | 预览」是否并排；
// 09-13 取消 AIGC 右栏预览后已无消费方，故移除（右栏宽度只由 :width 的 isWidePanel 决定）。

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

// 点击 Logo 回到店秘书（主入口）
const goHome = () => {
  // 清工具 + 切回对话视图 + 切到店秘书
  currentSelectedTool.value = null
  if (currentAgent.value?.id !== 'secretary') {
    const secretary = agentStore.agentList.find((a: any) => a.id === 'secretary')
    if (secretary) agentStore.setCurrentAgent(secretary)
  }
  if (currentView.value !== 'chat') {
    currentView.value = 'chat'
    rightPanelCollapsed.value = true
  }
}

/**
 * 统一落地：切到竞品监控员并把右栏切进「大屏模式」。
 *
 * 竞品监控看板已从「左侧导航独立视图」并入竞品监控员的右侧边栏，
 * 因此所有旧的 'monitor' 视图入口都要重定向到这里，否则会切到一个
 * 已经没有渲染分支的空白视图（currentView='monitor' 谁都不匹配）。
 */
const openIntelBoard = () => {
  const target = agentStore.agentList.find((a: any) => a.id === 'competitor-intel')
  if (target && agentStore.currentAgent?.id !== 'competitor-intel') {
    agentStore.setCurrentAgent(target)
  }
  currentSelectedTool.value = null
  currentView.value = 'chat'
  rightPanelCollapsed.value = false
  setReviewMode('data')
}

// 资料库导航切换
const handleKnowledgeNavigate = (key: string) => {
  // 旧「竞品监控」入口（蓝海详情抽屉 / 选品库开启监控 / 店秘书导航）统一重定向
  if (key === 'monitor') {
    openIntelBoard()
    return
  }
  currentView.value = key as 'faq' | 'candidates' | 'products' | 'competitors' | 'assets' | 'rules'
  // 同步侧边栏高亮：来自 CustomEvent（如大屏的「在资料库中管理」）的跳转不会经过菜单点击，
  // 不补这一步就会出现「视图已切、菜单没高亮」的错位。
  knowledgeBaseRef.value?.navigateTo(key)
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
    // AIGC 媒体生成器：点 Agent 即默认选中第一个工具「静态素材生成」，
    // 对齐运营复盘师「点 Agent 默认落到第一个数据视图」的体验（无需再手动点工具）。
    if (agentStore.currentAgent.id === 'aigc-media') {
      const firstTool = getAgentTools('aigc-media')[0]
      if (firstTool) {
        currentSelectedTool.value = firstTool
        // 默认选中工具时同步展开右栏，避免工具已选但面板折叠看不到
        rightPanelCollapsed.value = false
      }
    }
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

/**
 * 资料库（选品库 / 产品库 / 素材库 / 监控池 / 平台规则库）统一重新拉取。
 *
 * 它们都按 `X-Shop-ID` 在服务端过滤（平台规则库同样如此），因此必须与当前店铺严格同步：
 * - 切店铺不刷新 → 把旧店铺的数据当成新店铺的展示（跨店铺串数据）；
 * - 首屏不刷新 → 漏掉「选品 Agent 后端 `save_candidate` 写库」的结果
 *   （它只写库，碰不到前端 store）。
 */
const reloadLibraries = () => {
  candidateLibraryStore.resetForShopSwitch()
  candidateLibraryStore.fetchItems()
  productLibraryStore.fetchItems()
  assetLibraryStore.fetchItems()
  // 监控池与选品库同理：切店铺必须先把 UI 圈选/过滤重置，再按新店铺重拉
  monitorPoolStore.resetForShopSwitch()
  monitorPoolStore.fetchItems()
  // 平台规则库也按 X-Shop-ID 过滤，切店铺同样要重置过滤条件 + 重拉
  platformRulesStore.resetForShopSwitch()
  platformRulesStore.fetchItems()
  // 业务话术库同理：知识库容器本身就是按店铺隔离的
  knowledgeStore.resetForShopSwitch()
  knowledgeStore.fetchItems()
}

/**
 * 资料库跟随当前店铺加载。
 *
 * 用 watch 而不是在 onMounted 里裸调 fetchItems，是为了避开竞态：
 * 首屏店铺列表是异步拉的，onMounted 时 `current_shop_id` 可能还没写进
 * localStorage → 请求不带 X-Shop-ID → 后端一律返回空列表，且**再也不重拉**。
 * 这里 shopId 为空就跳过，等店铺 store 自动选中第一个店铺后由本 watch 触发。
 * （「店铺 store 自动选中」由同文件 onMounted 的 `shopStore.ensureShopsLoaded()`
 *   保证 —— 其 setShopList 内含「未选店铺则选中第一个」的兜底。）
 */
watch(
  () => shopStore.currentShopId,
  (shopId) => {
    if (!shopId) return
    reloadLibraries()
  },
  { immediate: true },
)

// 监听来自 ChatPanel 的导航事件（如：蓝海挖掘结果→跳转产品库）
// 监听来自产品库的 Listing 优化 / AIGC 生成 跳转请求
onMounted(() => {
  window.addEventListener('view-navigate', handleViewNavigate as EventListener)
  window.addEventListener('product-listing-optimize', handleListingOptimize as EventListener)
  window.addEventListener('product-aigc-launch', handleAigcLaunch as EventListener)
  window.addEventListener('monitor-launch-analysis', handleMonitorLaunchAnalysis as EventListener)
  window.addEventListener('open-memory-drawer', () => { memoryDrawerOpen.value = true })
  window.addEventListener('open-settings-drawer', () => { settingsDrawerOpen.value = true })

  // ★★ 店铺列表 = 应用级基础数据，必须在主界面挂载时主动拉一次。
  //    曾经它只在「店铺群」弹层挂载时（ShopPopoverContent.onMounted）加载，
  //    导致不点开弹层就 `shops=[]`：左上角店铺名不显示（`currentShop` 算不出）、
  //    AI 说「切换到 X 店」时 `switch_shop` 找不到目标被静默丢弃。
  //    这里是**唯一权威的启动加载点**；弹层内的 refreshShopList 保留（增删后刷新用）。
  //    下面 `watch(currentShopId)` 会在本调用写回 currentShopId 后自动触发资料库加载。
  void shopStore.ensureShopsLoaded()

  // 资料库数据的加载交给上面的 `watch(currentShopId)`（见其注释：避开首屏无店铺头的竞态）

  // 店秘书首屏欢迎语（仅首次进入且该会话无消息时注入）
  if (chatStore.getMessages('secretary').length === 0) {
    chatStore.addMessage({
      role: 'assistant',
      content: [
        '👋 我是**店秘书**，你的全局助手。直接告诉我你想做什么，我帮你一步到位：',
        '',
        '- 「帮我改下这个 listing」→ Listing 优化师',
        '- 「找找蓝海产品」→ 选品分析师',
        '- 「看看竞品动向」→ 竞品监控员',
        '- 「做张商品图 / 视频」→ AIGC 媒体生成器',
        '- 「打开产品库 / 选品库 / 竞品监控看板」→ 直达对应模块',
      ].join('\n'),
    }, 'secretary')
  }
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
    backgroundColor: isActive ? SEM.primary : 'transparent',
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
    detail: { tool: currentSelectedTool.value, params, mode: reviewMode.value }
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
  padding: 0 var(--space-12) 0 var(--space-16);
  flex-shrink: 0;
}

.logo-brand {
  display: flex;
  align-items: center;
  gap: var(--space-10);
  min-width: 0;
  flex: 1;
  cursor: pointer;
  border-radius: var(--radius-6);
  transition: opacity 0.15s ease;
}

.logo-brand:hover {
  opacity: 0.75;
}

.logo-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: var(--radius-10);
  background: var(--primary);
  color: #fff;
  font-size: var(--font-size-20);
}

.logo-name {
  display: inline-flex;
  align-items: baseline;
  min-width: 0;
}

.logo-title {
  color: var(--text-primary);
  font-size: var(--font-size-16);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.logo-shop-name {
  color: var(--text-tertiary);
  font-size: var(--font-size-13);
  font-weight: 400;
  margin-left: var(--space-4);
}

/* 店铺群触发按钮（右上角小图标） */
.shop-trigger-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  width: 32px;
  height: 32px;
  border: 1.5px solid var(--border-strong);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: var(--font-size-15);
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
  font-size: var(--font-size-11);
  font-weight: 600;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  text-align: center;
  background: var(--primary);
  color: #fff;
  border-radius: var(--radius-8);
  padding: 0 var(--space-4);
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
  padding: 0 var(--space-16);
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
  gap: var(--space-8);
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.collapse-btn {
  font-size: var(--font-size-18);
  flex-shrink: 0;
  color: var(--text-secondary);
}

/* ===== Header 内嵌紧凑工具栏 ===== */
.inline-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-left: var(--space-4);
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
}

.toolbar-agent-label {
  font-size: var(--font-size-12);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  flex-shrink: 0;
}

.toolbar-tools {
  display: flex;
  align-items: center;
  gap: var(--space-2);
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
  gap: var(--space-4);
  height: 28px;
  padding: 0 var(--space-8);
  border: none;
  border-radius: var(--radius-6);
  background-color: transparent;
  white-space: nowrap;
  font-size: var(--font-size-12);
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
  font-size: var(--font-size-13);
  line-height: 1;
  flex-shrink: 0;
}

.tb-name {
  font-size: var(--font-size-12);
  line-height: 1;
}

/* 窄屏工具栏：隐藏按钮文字只显示 icon，避免被滚动隐藏 */
@media (max-width: 1400px) {
  .toolbar-tool-btn .tb-name { display: none; }
  .toolbar-tool-btn { padding: 0 var(--space-6); }
}
@media (max-width: 1100px) {
  .toolbar-agent-label { display: none; }
}

.no-agent-hint {
  font-size: var(--font-size-13);
  color: var(--text-disabled);
  margin-left: var(--space-8);
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
  gap: var(--space-2);
  margin-right: var(--space-12);
  padding: var(--space-2);
  background: var(--bg-card-pill);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-8);
  flex-shrink: 0;
}

.mode-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-4);
  height: 26px;
  padding: 0 var(--space-10);
  font-size: var(--font-size-12);
  white-space: nowrap;
  color: var(--text-secondary);
  background: transparent;
  border: none;
  border-radius: var(--radius-6);
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
   —— 但 Listing 优化师需保留工具栏：点工具 = 跳到工作区对应模块
   —— AIGC 也保留：大屏模式下仍需顶部工具栏切换 3 个工具（静态素材/脚本/视频） */
.workspace-container.review-data-mode:not(.listing-data-mode):not(.aigc-data-mode) .inline-toolbar .toolbar-tools,
.workspace-container.review-data-mode:not(.listing-data-mode):not(.aigc-data-mode) .inline-toolbar .ant-divider {
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

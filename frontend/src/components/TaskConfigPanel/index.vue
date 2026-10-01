<template>
  <div class="task-config-panel">
    <!-- 面板头部 -->
    <div class="panel-header">
      <div class="header-left">
        <span class="panel-icon">{{ panelIcon }}</span>
        <span class="panel-title">{{ panelTitle }}</span>
        <!-- 当前工作商品标签（从产品库 ⚡ 过来时显示） -->
        <a-tag
          v-if="workingProduct"
          closable
          color="blue"
          class="working-product-tag"
          @close="clearWorkingProduct"
        >
          📦 {{ workingProduct.title.length > 10 ? workingProduct.title.slice(0, 10) + '…' : workingProduct.title }}
        </a-tag>
      </div>
      <div class="header-actions">
        <a-tooltip :title="collapsed ? '展开面板' : '收起面板'">
          <button
            class="collapse-trigger"
            @click="handleToggle"
          >
            <LeftOutlined v-if="!collapsed" />
            <RightOutlined v-else />
          </button>
        </a-tooltip>
      </div>
    </div>

    <!-- ====== AIGC 大屏模式：顶部工具 Tab 栏（对齐复盘师大屏 rv-tabs） ======
         对话模式由 Workspace 顶部工具栏 6 个工具按钮承担切换；
         大屏模式下顶部工具按钮已隐藏，改由这里的 Tab 栏切换三个工具。
         ★ 显示条件 = Workspace 注入的 `isWideBoardDataMode`（整页大屏布局**真的生效**），
           不是 `reviewMode === 'data'`（那只是"用户偏好"）。两者不一致时会出现
           「中间退回对话模式、右栏却还挂着这排 Tab」的错位 —— 第 313 轮故障。 -->
    <div
      v-if="isAigcAgent && isWideBoardDataMode"
      class="aigc-tool-tabs"
    >
      <button
        v-for="tab in aigcTabs"
        :key="tab.id"
        class="aigc-tool-tab"
        :class="{ active: currentTool?.id === tab.id }"
        @click="setSelectedTool(tab)"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        <span>{{ tab.name }}</span>
      </button>
    </div>

    <!-- ====== 选品分析师大屏模式：顶部工具 Tab 栏（第 312 轮对齐 AIGC 范式）======
         选品分析师是工具级双模式（选中任一选品工具才显示 mode-switch），
         大屏下三个工具（选品大盘 / 蓝海挖掘 / 利润测算）复用同一 Tab 栏切换。
         ★ 显示条件同 AIGC：Workspace 注入的 `isWideBoardDataMode`。
           第 313 轮故障原样：这里曾只认 `reviewMode === 'data'`，而 Workspace 那边
           的整页大屏判据漏了蓝海/利润 ⇒ 点这两个工具时「布局退回对话模式、
           右栏却还挂着这排 Tab」（老板 09-29 截图）。 -->
    <div
      v-if="isProductResearchAgent && isWideBoardDataMode"
      class="aigc-tool-tabs"
    >
      <button
        v-for="tab in productResearchTabs"
        :key="tab.id"
        class="aigc-tool-tab"
        :class="{ active: currentTool?.id === tab.id }"
        @click="setSelectedTool(tab)"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        <span>{{ tab.name }}</span>
      </button>
    </div>

    <!-- 面板内容 -->
    <div class="panel-body">
      <!-- 竞品监控员：右侧常驻「竞品监控大屏」（圈选入口已收到顶部按钮，推理走输入框上方 chip） -->
      <IntelBoardConfig v-if="!currentTool && isCompetitorIntel" />

      <!-- 运营复盘师：未选工具时默认展示「经营概览」数据看板（对话/数据模式一致） -->
      <ReviewConfig
        v-else-if="!currentTool && isReviewAgent"
        :key="'review-default'"
      />

      <!-- Listing 优化师：统一工作区（未选工具时默认展示，落在标题模块） -->
      <ListingBoard
        v-else-if="!currentTool && isListingAgent"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 广告分析师：未选工具时默认展示「账户总览」数据看板（对话/数据模式一致） -->
      <AdDashboardConfig
        v-else-if="!currentTool && isAdAnalyst"
        :key="'ad-default'"
      />

      <!-- 无工具选中（其它 Agent） -->
      <div
        v-else-if="!currentTool"
        class="empty-hint"
      >
        <SettingOutlined style="font-size: var(--font-size-32); color: var(--text-tertiary); margin-bottom: var(--space-12)" />
        <p>选择工具后</p>
        <p>在此配置任务参数</p>
      </div>

      <!-- ====== Listing 优化师：4 个工具统一落到「商品详情页」对应模块 ======
           不要 :key 重建（依赖内部 watch currentToolId 切模块），
           否则 setup 反复执行 → activeModule 永远重置为 'title' 默认值，
           导致右侧永远显示标题模块。 -->
      <ListingBoard
        v-else-if="isListingAgent && LISTING_TOOL_IDS.includes(currentTool.id)"
        :current-tool-id="currentTool.id"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 蓝海挖掘配置 -->
      <BlueOceanConfig
        v-else-if="currentTool.id === 'blue-ocean'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 痛点分析配置 -->
      <PainPointConfig
        v-else-if="currentTool.id === 'pain-points'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 竞品对比配置 -->
      <CompetitorConfig
        v-else-if="currentTool.id === 'competitor'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 选品避坑配置 -->
      <PitfallsConfig
        v-else-if="currentTool.id === 'pitfalls'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 利润测算配置 -->
      <ProfitConfig
        v-else-if="currentTool.id === 'profit-calc'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- ★ 选品市场洞察大盘云图（第 305 轮）：选品分析师功能栏「选品大盘」落点。
           工具级双模式（对话/大屏），面板直调 GET /product-research/market-insight/treemap，
           演示账号看 mock 快照（degraded=true），真实账号空态 fail-closed。 -->
      <MarketInsightConfig v-else-if="currentTool.id === 'market-insight'" />

      <!-- ====== Listing 优化师（按工作流顺序） ====== -->

      <!-- 关键词挖掘配置 -->
      <KeywordMinerConfig
        v-else-if="currentTool.id === 'keyword-miner'"
        :working-product="workingProduct"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 标题生成配置 -->
      <ListingOptimConfig
        v-else-if="currentTool.id === 'title-gen'"
        :working-product="workingProduct"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 五点描述配置 -->
      <BulletConfig
        v-else-if="currentTool.id === 'bullet-gen'"
        :working-product="workingProduct"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 描述生成配置 -->
      <DescConfig
        v-else-if="currentTool.id === 'desc-gen'"
        :working-product="workingProduct"
        @start-analysis="handleStartAnalysis"
      />

      <!-- SEO 诊断配置 -->
      <SEOConfig
        v-else-if="currentTool.id === 'seo-audit'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- A/B 测试配置 -->
      <ABTestConfig
        v-else-if="currentTool.id === 'ab-test'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- ====== 广告分析师：统一大面板，4 个工具共用（:key 强制切换时重建） ====== -->
      <!-- ★ 第 316 轮：`budget-alloc` / `anomaly-detect` 两张卡已退役，白名单同步收窄 -->
      <AdDashboardConfig
        v-else-if="['ad-diagnosis','keyword-report','bid-suggest','competitor-ad'].includes(currentTool.id)"
        :key="'ad-' + currentTool.id"
        :current-tool-id="currentTool.id"
        @start-analysis="handleStartAnalysis"
      />

      <!-- ★ 差评工作台（第 289 轮 P1 / 第 291 轮收敛）：客服 Agent 功能栏
           「差评台账」按钮的落点，内含 近期差评 / 未关联产品 / 处置台账 三视图。
           ★★ 它是 approve / reject / issue 这三个**不可逆人审动作的唯一出口**
           —— 资料库那个同名入口（DispositionLibrary）已在第 291 轮删除。
           再加第二个带这些按钮的面板前，先读 ReviewDeskConfig.vue 头部的说明。 -->
      <ReviewDeskConfig v-else-if="currentTool.id === 'review-desk'" />

      <!-- 订单追踪配置 -->
      <OrderTrackConfig
        v-else-if="currentTool.id === 'order-track'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- ====== AIGC 媒体生成器（3 工具各自独立配置面板） ======
           大屏/对话切换走 Workspace 顶栏 mode-switch（reviewMode），
           三个 config 通过 inject('reviewMode') 自算「是否 data」渲染「预览窗口 / 表单」。
           （config 层自算点与 `hasWideBoard` 的等价性说明，见 Workspace 里
            `isWideBoardDataMode` 的注释 —— 别在这里再展开第二份。） -->
      <StaticAssetConfig
        v-else-if="currentTool.id === 'static-asset-gen'"
        @start-analysis="handleStartAnalysis"
      />
      <VideoScriptConfig
        v-else-if="currentTool.id === 'video-script-gen'"
        @start-analysis="handleStartAnalysis"
      />
      <VideoGeneratorConfig
        v-else-if="currentTool.id === 'ai-video-generator'"
        @start-analysis="handleStartAnalysis"
      />

      <!-- ====== 运营复盘师（统一大面板，5个工具共用，:key 强制切换时重建） ====== -->
      <ReviewConfig
        v-else-if="['weekly-report','monthly-review','product-performance','inventory-health','profit-audit'].includes(currentTool.id)"
        :key="'review-' + currentTool.id"
        :current-tool-id="currentTool.id"
        @start-analysis="handleStartAnalysis"
      />

      <!-- 通用占位（兜底） -->
      <div
        v-else
        class="empty-hint"
      >
        <ToolOutlined style="font-size: var(--font-size-32); color: var(--text-tertiary); margin-bottom: var(--space-12)" />
        <p>{{ currentTool.name }}</p>
        <p class="hint">
          配置面板开发中
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject, provide, computed, ref, type Ref, onMounted, onUnmounted } from 'vue'
import {
  LeftOutlined,
  RightOutlined,
  SettingOutlined,
  ToolOutlined,
} from '@ant-design/icons-vue'
import type { ToolDefinition } from '../ChatPanel/tools/toolDefinitions'
import { getAgentTools } from '../ChatPanel/tools/toolDefinitions'
import { useAgentStore } from '@/stores/agent'
import BlueOceanConfig from './configs/BlueOceanConfig.vue'
import PainPointConfig from './configs/PainPointConfig.vue'
import CompetitorConfig from './configs/CompetitorConfig.vue'
import PitfallsConfig from './configs/PitfallsConfig.vue'
import ProfitConfig from './configs/ProfitConfig.vue'
import BulletConfig from './configs/BulletConfig.vue'
import SEOConfig from './configs/SEOConfig.vue'
import ABTestConfig from './configs/ABTestConfig.vue'
import DescConfig from './configs/DescConfig.vue'
import OrderTrackConfig from './configs/OrderTrackConfig.vue'
import ReviewDeskConfig from './configs/ReviewDeskConfig.vue'
import ListingOptimConfig from './configs/ListingOptimConfig.vue'
import StaticAssetConfig from './configs/StaticAssetConfig.vue'
import VideoScriptConfig from './configs/VideoScriptConfig.vue'
import VideoGeneratorConfig from './configs/VideoGeneratorConfig.vue'
import KeywordMinerConfig from './configs/KeywordMinerConfig.vue'
import ReviewConfig from './configs/ReviewConfig.vue'
import AdDashboardConfig from './configs/AdDashboardConfig.vue'
import ListingBoard from './configs/ListingBoard.vue'
import MarketInsightConfig from './configs/MarketInsightConfig.vue'

// Listing 优化师：这些工具不再各自开配置面板，统一落到商品详情页的对应模块
const LISTING_TOOL_IDS = ['keyword-miner', 'title-gen', 'bullet-gen', 'desc-gen']
import IntelBoardConfig from './configs/IntelBoardConfig.vue'

const props = defineProps<{
  currentTool: ToolDefinition | null
}>()

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const agentStore = useAgentStore()
// 竞品监控员：无工具时右侧默认显示「竞品监控大屏」
const isCompetitorIntel = computed(() => agentStore.currentAgent?.id === 'competitor-intel')
// 运营复盘师：无工具时右侧默认显示「经营概览」数据看板
const isReviewAgent = computed(() => agentStore.currentAgent?.id === 'review-analyst')
// Listing 优化师：右侧常驻「Listing 统一工作区」
const isListingAgent = computed(() => agentStore.currentAgent?.id === 'listing-generator')

// 广告分析师：右侧为「广告大屏看板」，6 Tab 数据面板
const isAdAnalyst = computed(() => agentStore.currentAgent?.id === 'ad-analysis')

// AIGC 媒体生成器：大屏模式顶部提供「工具 Tab 栏」切换三个工具（对齐复盘师大屏 rv-tabs）
const isAigcAgent = computed(() => agentStore.currentAgent?.id === 'aigc-media')

// 选品分析师：大屏模式顶部提供「工具 Tab 栏」切换三个选品工具（第 312 轮对齐 AIGC 范式）
const isProductResearchAgent = computed(() => agentStore.currentAgent?.id === 'product-research')

// 面板图标/标题（拆成 computed 避免模板内嵌套三元过长导致 Vite 解析失败）
const panelIcon = computed(() =>
  props.currentTool?.icon || (isCompetitorIntel.value ? '🎯' : isReviewAgent.value ? '📊' : isListingAgent.value ? '🧩' : isAdAnalyst.value ? '📈' : '⚙️')
)
const panelTitle = computed(() =>
  props.currentTool?.name || (isCompetitorIntel.value ? '竞品监控' : isReviewAgent.value ? '经营概览' : isListingAgent.value ? '商品详情页' : isAdAnalyst.value ? '账户总览' : '任务配置')
)
// 注：这里原先还有一份「Agent 变了且 currentTool 还没清 ⇒ emit('clearTool')」的兜底 watcher，
// 第 252 轮删除。它与 Workspace 切 Agent 的 watch 是**同一判定的第二份实现**，
// 而父组件那边更强：每次切 Agent 都**无条件**先 `currentSelectedTool = null`，
// 再按 `AGENT_DEFAULT_TOOL` 挂默认工具（父 watch 的触发源 ⊇ 子 watch，见 toolDefinitions.ts）。
// 保留它的唯一可观测后果是**子 watcher 后跑、把父刚挂上的默认工具又清掉**，
// 表现为「点 Agent 右栏落回空态」。判定归父组件一处，子组件不再插手。

// 从 Workspace 注入收缩控制（WorkBuddy 风格：外层 Sider 统一管理）
const collapsed = inject<Ref<boolean>>('rightPanelCollapsed')
const toggleRightPanel = inject<() => void>('toggleRightPanel')

// 从 Workspace 注入当前工作商品（Agent 级共享上下文，所有工具可读）
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// 从 Workspace 注入当前「对话/文案(数据)」模式（Listing 工作区据此切换单模块/完整视图）
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)

// ★ 第 313 轮：大屏工具 Tab 栏的显示条件改用 Workspace 注入的
//   「**整页大屏布局是否真的生效**」（= Workspace 的 `isReviewDataMode`）。
//   此前是 `reviewMode.value === 'data'` —— 只看用户偏好，与 Workspace 的判定
//   是**两份实现**。两者不一致时（选品三工具曾漏在 `hasWideBoard` 之外）就出现：
//   中间退回对话模式大小、右栏顶部却还挂着工具 Tab 栏（老板 09-29 截图）。
//   注：`reviewMode` 仍要 inject —— 下面 provide 透传给各 config 用。
const isWideBoardDataMode = inject<Ref<boolean>>('isWideBoardDataMode', ref(false))

// 从 Workspace 注入「设置当前工具」（AIGC 大屏工具 Tab 栏切换工具用）
const setSelectedTool = inject<(tool: ToolDefinition | null) => void>('setSelectedTool', () => {})

// ====== 选品大盘 → 蓝海挖掘 预填通道（第 306 轮）======
// 选品大盘点色块（类目粒度）时，把类目 slug 预填进蓝海挖掘表单，让用户
// 再细化价格/竞争条件去挖产品。这里 provide 一个带时间戳的 payload，
// 蓝海表单 watch 它，命中同一时间戳即消费（避免重复消费 / 丢信号）。
interface BlueOceanPrefill {
  categoryPath: string
  categoryName: string
  site: string
  ts: number
}
const blueOceanPrefill = ref<BlueOceanPrefill | null>(null)
provide('blueOceanPrefill', blueOceanPrefill)
provide('prefillBlueOcean', (payload: { categoryPath: string; categoryName: string; site: string }) => {
  blueOceanPrefill.value = { ...payload, ts: Date.now() }
})

// AIGC 三个工具（大屏 Tab 栏数据源，直接读 toolDefinitions 保证与顶部工具栏一致）
const aigcTabs = computed(() => getAgentTools('aigc-media'))

// 选品分析师三个工具（大屏 Tab 栏数据源，同读 toolDefinitions 保证与顶部工具栏一致）
const productResearchTabs = computed(() => getAgentTools('product-research'))

// 透传给所有子组件（确保孙组件 inject 能稳定获取响应式值）
// 必须提供默认值 ref(null)，防止上游 provide 失败时子组件 inject 崩溃
provide('workingProduct', workingProduct)
provide('reviewMode', reviewMode)

// 切换收起/展开（委托给 Workspace 的 a-layout-sider）
const handleToggle = () => {
  if (toggleRightPanel) toggleRightPanel()
}

// 清除当前工作商品（点击标签 × 时）
const clearWorkingProduct = () => {
  const clearFn = inject<() => void>('clearWorkingProduct')
  if (clearFn) clearFn()
}

// 处理开始分析
const handleStartAnalysis = (params: any) => {
  emit('startAnalysis', params)
}
</script>

<style scoped>
.task-config-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-elevated);
}

/* 面板头部 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-12) var(--space-16);
  border-bottom: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
  min-height: 52px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  overflow: hidden;
  min-width: 0;
}

/* 工作商品标签 */
.working-product-tag {
  flex-shrink: 0;
  font-size: var(--font-size-11);
  max-width: 140px;
  border-radius: var(--radius-10);
}
.working-product-tag :deep(.ant-tag-close-icon) {
  font-size: var(--font-size-10);
  margin-left: var(--space-4);
}

.panel-icon {
  font-size: var(--font-size-18);
  flex-shrink: 0;
}

.panel-title {
  font-size: var(--font-size-14);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  gap: var(--space-4);
  flex-shrink: 0;
}

/* 收缩按钮 - WorkBuddy 风格 */
.collapse-trigger {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: var(--radius-6);
  color: var(--text-tertiary);
  transition: all 0.2s ease;
  font-size: var(--font-size-12);
}

.collapse-trigger:hover {
  background-color: var(--bg-hover-light);
  color: var(--primary);
}

/* 面板内容 */
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-12) var(--space-16);
}

/* ====== AIGC 大屏工具 Tab 栏（对齐复盘师 rv-tabs 样式） ====== */
.aigc-tool-tabs {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-8) var(--space-12);
  border-bottom: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
  flex-shrink: 0;
  overflow-x: auto;
}
.aigc-tool-tab {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-6) var(--space-12);
  border: 1px solid transparent;
  border-radius: var(--radius-6);
  background: transparent;
  cursor: pointer;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  white-space: nowrap;
  transition: all 0.2s;
}
.aigc-tool-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover-light);
}
.aigc-tool-tab.active {
  color: var(--primary);
  background: var(--bg-active-light);
  border-color: var(--primary);
  font-weight: 600;
}
.aigc-tool-tab .tab-icon {
  font-size: var(--font-size-14);
}

/* 空状态提示 */
.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-tertiary);
  text-align: center;
  padding: var(--space-24);
}

.empty-hint p {
  margin: var(--space-4) 0;
  font-size: var(--font-size-13);
}

.empty-hint .hint {
  font-size: var(--font-size-12);
  color: var(--text-disabled);
  margin-top: var(--space-4);
}

</style>

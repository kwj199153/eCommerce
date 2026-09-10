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
          <button class="collapse-trigger" @click="handleToggle">
            <LeftOutlined v-if="!collapsed" />
            <RightOutlined v-else />
          </button>
        </a-tooltip>
      </div>
    </div>

    <!-- 面板内容 -->
    <div class="panel-body">
      <!-- 竞品监控员：右侧常驻「竞品选择」（推理走输入框上方 chip） -->
      <IntelCompetitorPick v-if="!currentTool && isCompetitorIntel" />

      <!-- 运营复盘师：未选工具时默认展示「经营概览」数据看板（对话/数据模式一致） -->
      <ReviewConfig
        v-else-if="!currentTool && isReviewAgent"
        :key="'review-default'"
      />

      <!-- Listing 优化师：统一工作区（未选工具时默认展示，落在标题模块） -->
      <ListingBoard
        v-else-if="!currentTool && isListingAgent"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 广告分析师：未选工具时默认展示「账户总览」数据看板（对话/数据模式一致） -->
      <AdDashboardConfig
        v-else-if="!currentTool && isAdAnalyst"
        :key="'ad-default'"
      />

      <!-- 无工具选中（其它 Agent） -->
      <div v-else-if="!currentTool" class="empty-hint">
        <SettingOutlined style="font-size: 32px; color: var(--text-tertiary); margin-bottom: 12px" />
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
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 蓝海挖掘配置 -->
      <BlueOceanConfig
        v-else-if="currentTool.id === 'blue-ocean'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 痛点分析配置 -->
      <PainPointConfig
        v-else-if="currentTool.id === 'pain-points'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 竞品对比配置 -->
      <CompetitorConfig
        v-else-if="currentTool.id === 'competitor'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 选品避坑配置 -->
      <PitfallsConfig
        v-else-if="currentTool.id === 'pitfalls'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 利润测算配置 -->
      <ProfitConfig
        v-else-if="currentTool.id === 'profit-calc'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- ====== Listing 优化师（按工作流顺序） ====== -->

      <!-- 关键词挖掘配置 -->
      <KeywordMinerConfig
        v-else-if="currentTool.id === 'keyword-miner'"
        :working-product="workingProduct"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 标题生成配置 -->
      <ListingOptimConfig
        v-else-if="currentTool.id === 'title-gen'"
        :working-product="workingProduct"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 五点描述配置 -->
      <BulletConfig
        v-else-if="currentTool.id === 'bullet-gen'"
        :working-product="workingProduct"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 描述生成配置 -->
      <DescConfig
        v-else-if="currentTool.id === 'desc-gen'"
        :working-product="workingProduct"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- SEO 诊断配置 -->
      <SEOConfig
        v-else-if="currentTool.id === 'seo-audit'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- A/B 测试配置 -->
      <ABTestConfig
        v-else-if="currentTool.id === 'ab-test'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- ====== 广告分析师：统一大面板，6 个工具共用（:key 强制切换时重建） ====== -->
      <AdDashboardConfig
        v-else-if="['ad-diagnosis','keyword-report','bid-suggest','competitor-ad','budget-alloc','anomaly-detect'].includes(currentTool.id)"
        :key="'ad-' + currentTool.id"
        :current-tool-id="currentTool.id"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 订单追踪配置 -->
      <OrderTrackConfig
        v-else-if="currentTool.id === 'order-track'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 创建工单配置 -->
      <TicketCreateConfig
        v-else-if="currentTool.id === 'ticket-create'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 竞品监控员：智能推理（读监控池，问答/周报/异动/策略共用） -->
      <IntelAnalysisConfig
        v-else-if="['intel-chat', 'intel-weekly', 'intel-anomaly', 'intel-strategy'].includes(currentTool.id)"
        :key="'intel-' + currentTool.id"
        :current-tool-id="currentTool.id"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 监控仪表盘配置 -->
      <MonitorDashboardConfig
        v-else-if="currentTool.id === 'monitor-dashboard'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 价格追踪配置 -->
      <PriceTrackConfig
        v-else-if="currentTool.id === 'price-track'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 市场份额配置 -->
      <MarketShareConfig
        v-else-if="currentTool.id === 'market-share'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 定价策略配置 -->
      <PricingAnalysisConfig
        v-else-if="currentTool.id === 'pricing-analysis'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 入侵者警报配置 -->
      <IntruderAlertConfig
        v-else-if="currentTool.id === 'intruder-alert'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- Buy Box 分析配置 -->
      <BuyBoxAnalysisConfig
        v-else-if="currentTool.id === 'buy-box-analysis'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 多维对比配置 -->
      <CompareGridConfig
        v-else-if="currentTool.id === 'compare-grid'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- ====== AIGC 媒体生成器 ====== -->

      <!-- 静态素材生成（白底三视图/细节图/场景图/分镜首帧） -->
      <StaticAssetConfig
        v-else-if="currentTool.id === 'static-asset-gen'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 短视频带货脚本 + 分镜表 -->
      <VideoScriptConfig
        v-else-if="currentTool.id === 'video-script-gen'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- AI 短视频生成（基于分镜首帧+运镜指令） -->
      <VideoGeneratorConfig
        v-else-if="currentTool.id === 'ai-video-generator'"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- ====== 运营复盘师（统一大面板，7个工具共用，:key 强制切换时重建） ====== -->
      <ReviewConfig
        v-else-if="['weekly-report','monthly-review','ad-review','product-performance','inventory-health','profit-audit','action-plan'].includes(currentTool.id)"
        :key="'review-' + currentTool.id"
        :current-tool-id="currentTool.id"
        @startAnalysis="handleStartAnalysis"
      />

      <!-- 通用占位（兜底） -->
      <div v-else class="empty-hint">
        <ToolOutlined style="font-size: 32px; color: var(--text-tertiary); margin-bottom: 12px" />
        <p>{{ currentTool.name }}</p>
        <p class="hint">配置面板开发中</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject, provide, computed, ref, type Ref, onMounted, onUnmounted, watch } from 'vue'
import {
  LeftOutlined,
  RightOutlined,
  SettingOutlined,
  ToolOutlined,
} from '@ant-design/icons-vue'
import type { ToolDefinition } from '../ChatPanel/tools/toolDefinitions'
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
import AdDiagnosisConfig from './configs/AdDiagnosisConfig.vue'
import SearchTermReportConfig from './configs/SearchTermReportConfig.vue'
import BidSuggestConfig from './configs/BidSuggestConfig.vue'
import CompetitorAdConfig from './configs/CompetitorAdConfig.vue'
import BudgetAllocConfig from './configs/BudgetAllocConfig.vue'
import OrderTrackConfig from './configs/OrderTrackConfig.vue'
import TicketCreateConfig from './configs/TicketCreateConfig.vue'
import MonitorDashboardConfig from './configs/MonitorDashboardConfig.vue'
import PriceTrackConfig from './configs/PriceTrackConfig.vue'
import MarketShareConfig from './configs/MarketShareConfig.vue'
import PricingAnalysisConfig from './configs/PricingAnalysisConfig.vue'
import IntruderAlertConfig from './configs/IntruderAlertConfig.vue'
import BuyBoxAnalysisConfig from './configs/BuyBoxAnalysisConfig.vue'
import CompareGridConfig from './configs/CompareGridConfig.vue'
import ListingOptimConfig from './configs/ListingOptimConfig.vue'
import StaticAssetConfig from './configs/StaticAssetConfig.vue'
import VideoScriptConfig from './configs/VideoScriptConfig.vue'
import VideoGeneratorConfig from './configs/VideoGeneratorConfig.vue'
import KeywordMinerConfig from './configs/KeywordMinerConfig.vue'
import ReviewConfig from './configs/ReviewConfig.vue'
import AdDashboardConfig from './configs/AdDashboardConfig.vue'
import ListingBoard from './configs/ListingBoard.vue'

// Listing 优化师：这些工具不再各自开配置面板，统一落到商品详情页的对应模块
const LISTING_TOOL_IDS = ['keyword-miner', 'title-gen', 'bullet-gen', 'desc-gen']
import IntelAnalysisConfig from './configs/IntelAnalysisConfig.vue'
import IntelCompetitorPick from './configs/IntelCompetitorPick.vue'

const props = defineProps<{
  currentTool: ToolDefinition | null
}>()

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
  (e: 'clearTool'): void
}>()

// 内核级防护：直接监听 Agent 变化，确保切换时清空工具选择
const agentStore = useAgentStore()
// 竞品监控员：无工具时右侧默认显示「竞品选择」面板
const isCompetitorIntel = computed(() => agentStore.currentAgent?.id === 'competitor-intel')
// 运营复盘师：无工具时右侧默认显示「经营概览」数据看板
const isReviewAgent = computed(() => agentStore.currentAgent?.id === 'review-analyst')
// Listing 优化师：右侧常驻「Listing 统一工作区」
const isListingAgent = computed(() => agentStore.currentAgent?.id === 'listing-generator')

// 广告分析师：右侧为「广告大屏看板」，6 Tab 数据面板
const isAdAnalyst = computed(() => agentStore.currentAgent?.id === 'ad-analysis')

// 面板图标/标题（拆成 computed 避免模板内嵌套三元过长导致 Vite 解析失败）
const panelIcon = computed(() =>
  props.currentTool?.icon || (isCompetitorIntel.value ? '🎯' : isReviewAgent.value ? '📊' : isListingAgent.value ? '🧩' : isAdAnalyst.value ? '📈' : '⚙️')
)
const panelTitle = computed(() =>
  props.currentTool?.name || (isCompetitorIntel.value ? '竞品选择' : isReviewAgent.value ? '经营概览' : isListingAgent.value ? '商品详情页' : isAdAnalyst.value ? '账户总览' : '任务配置')
)
watch(() => agentStore.currentAgent, (newAgent) => {
  if (newAgent && props.currentTool) {
    // Agent 切换了但 currentTool 还残留 → 强制通知父组件清空
    console.log('🛡️ TaskConfigPanel 检测到 Agent 切换，强制清空工具选择')
    emit('clearTool')
  }
})

// 从 Workspace 注入收缩控制（WorkBuddy 风格：外层 Sider 统一管理）
const collapsed = inject<Ref<boolean>>('rightPanelCollapsed')
const toggleRightPanel = inject<() => void>('toggleRightPanel')

// 从 Workspace 注入当前工作商品（Agent 级共享上下文，所有工具可读）
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// 从 Workspace 注入当前「对话/文案(数据)」模式（Listing 工作区据此切换单模块/完整视图）
const reviewMode = inject<Ref<'chat' | 'data'>>('reviewMode', ref('chat') as Ref<'chat' | 'data'>)

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
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
  min-height: 52px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
  min-width: 0;
}

/* 工作商品标签 */
.working-product-tag {
  flex-shrink: 0;
  font-size: 11px;
  max-width: 140px;
  border-radius: 10px;
}
.working-product-tag :deep(.ant-tag-close-icon) {
  font-size: 10px;
  margin-left: 4px;
}

.panel-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  gap: 4px;
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
  border-radius: 6px;
  color: var(--text-tertiary);
  transition: all 0.2s ease;
  font-size: 12px;
}

.collapse-trigger:hover {
  background-color: var(--bg-hover-light);
  color: var(--primary);
}

/* 面板内容 */
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
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
  padding: 24px;
}

.empty-hint p {
  margin: 4px 0;
  font-size: 13px;
}

.empty-hint .hint {
  font-size: 12px;
  color: var(--text-disabled);
  margin-top: 4px;
}
</style>

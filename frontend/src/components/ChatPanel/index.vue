<template>
  <div class="chat-panel">
    <!-- ===== 主内容区域（对话 + 结果共存） ===== -->
    <div class="main-content" ref="mainContentRef">
      <!-- 对话消息区域（始终显示） -->
      <div class="message-list" ref="messageListRef">
          <div v-if="messages.length === 0 && !agentStore.currentAgent" class="empty-state">
            <RobotOutlined style="font-size: 48px; color: var(--text-tertiary); margin-bottom: 16px" />
            <p>选择一个 Agent 开始对话</p>
            <p class="hint">或从顶部工具栏选择功能</p>
          </div>

          <div v-else-if="messages.length === 0 && agentStore.currentAgent" class="empty-state">
            <span style="font-size: 48px">{{ agentStore.currentAgent.icon?.render?.() || '🤖' }}</span>
            <p>{{ agentStore.currentAgent.name }} 已就绪</p>
            <p v-if="isCompetitorIntelAgent" class="hint">在右侧圈选竞品后，点下方「竞品周报 / 异动洞察 / 策略推演」或直接提问</p>
            <p v-else-if="isProductResearchAgent" class="hint">先在顶部「载入选品」选定候选，再点下方「市场可行性 / 上架建议 / 痛点分析 / 选品避坑 / 竞品对比」任一评估</p>
            <p v-else-if="isListingAgent" class="hint">先在顶部「载入产品」选定要优化的商品，再点下方「SEO 诊断」诊断其 Listing 或从顶部工具栏生成文案</p>
            <p v-else class="hint">输入问题或点击顶部工具栏开始分析</p>
          </div>

          <div
            v-for="(msg, index) in messages"
            :key="index"
          >
            <!-- ===== 工具结果消息（内联渲染，支持折叠/展开）===== -->
            <div v-if="msg.displayType === 'tool_result'" class="message-item tool-result-message">
              <a-avatar style="background-color: #52c41a">AI</a-avatar>
              <div class="message-content tool-result-content">
                <!-- 工具结果组件（各自带标题栏+关闭按钮） -->
                <BlueOceanResult
                  v-if="msg.data?.toolId === 'blue-ocean'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                  @navigateTo="handleNavigateTo"
                />
                <!-- 痛点分析 -->
                <PainPointResult
                  v-else-if="msg.data?.toolId === 'pain-points'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 竞品对比 -->
                <CompetitorResult
                  v-else-if="msg.data?.toolId === 'competitor'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 利润测算 -->
                <ProfitResult
                  v-else-if="msg.data?.toolId === 'profit-calc'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 标题生成 -->
                <TitleGenerator
                  v-else-if="msg.data?.toolId === 'title-gen'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                  @navigateTo="handleNavigateTo"
                />
                <!-- 五点描述 -->
                <BulletGenerator
                  v-else-if="msg.data?.toolId === 'bullet-gen'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- SEO 诊断 -->
                <SEODiagnostic
                  v-else-if="msg.data?.toolId === 'seo-audit'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- A/B 测试 -->
                <ABTestGenerator
                  v-else-if="msg.data?.toolId === 'ab-test'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 描述生成 -->
                <DescriptionGenerator
                  v-else-if="msg.data?.toolId === 'desc-gen'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 广告诊断 -->
                <AdDiagnosisResult
                  v-else-if="msg.data?.toolId === 'ad-diagnosis'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 搜索词报告 -->
                <SearchTermResult
                  v-else-if="msg.data?.toolId === 'keyword-report'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 出价建议 -->
                <BidOptimizeResult
                  v-else-if="msg.data?.toolId === 'bid-suggest'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 竞品广告 -->
                <CompetitorAdResult
                  v-else-if="msg.data?.toolId === 'competitor-ad'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 预算分配 -->
                <BudgetAllocResult
                  v-else-if="msg.data?.toolId === 'budget-alloc'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 异常检测 -->
                <AnomalyDetectResult
                  v-else-if="msg.data?.toolId === 'anomaly-detect'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 订单追踪 -->
                <OrderTrackResult
                  v-else-if="msg.data?.toolId === 'order-track'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 工单创建 -->
                <TicketCreateResult
                  v-else-if="msg.data?.toolId === 'ticket-create'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 监控仪表盘 -->
                <MonitorDashboardResult
                  v-else-if="msg.data?.toolId === 'monitor-dashboard'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 价格追踪 -->
                <PriceTrackResult
                  v-else-if="msg.data?.toolId === 'price-track'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 市场份额 -->
                <MarketShareResult
                  v-else-if="msg.data?.toolId === 'market-share'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 定价策略 -->
                <PricingAnalysisResult
                  v-else-if="msg.data?.toolId === 'pricing-analysis'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 评论侦探 -->
                <ReviewSpyResult
                  v-else-if="msg.data?.toolId === 'review-spy'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 入侵者警报 -->
                <IntruderAlertResult
                  v-else-if="msg.data?.toolId === 'intruder-alert'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- Buy Box 分析 -->
                <BuyBoxAnalysisResult
                  v-else-if="msg.data?.toolId === 'buy-box-analysis'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 多维对比 -->
                <CompareGridResult
                  v-else-if="msg.data?.toolId === 'compare-grid'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 关键词挖掘 -->
                <KeywordMinerResult
                  v-else-if="msg.data?.toolId === 'keyword-miner'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 选品避坑 -->
                <PainPointResult
                  v-else-if="msg.data?.toolId === 'pitfalls'"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 静态素材生成 / 短视频脚本 / AI视频 -->
                <AIGCMediaResult
                  v-else-if="['static-asset-gen', 'video-script-gen', 'ai-video-generator'].includes(msg.data?.toolId)"
                  :data="msg.data?.resultData"
                  @close="removeToolResult(index)"
                />
                <!-- 运营复盘师（周报/月度/广告/商品/库存/利润） -->
                <div v-else-if="['weekly-report', 'monthly-review', 'ad-review', 'product-performance', 'inventory-health', 'profit-audit'].includes(msg.data?.toolId)" class="raw-result-fallback">
                  <a-alert type="success" show-icon :message="`${msg.data?.toolName || '复盘'} 报告生成完成`" style="margin-bottom: 8px" />
                  <pre class="result-json-preview">{{ JSON.stringify(msg.data?.resultData, null, 2) }}</pre>
                </div>
                <!-- 兜底 -->
                <div v-else class="raw-result-fallback">
                  <a-alert type="warning" show-icon message="未知工具类型" />
                </div>
              </div>
            </div>

            <!-- ===== 普通文本消息 ===== -->
            <div
              v-else
              :class="['message-item', msg.role]"
            >
            <a-avatar
              :style="{ backgroundColor: msg.role === 'user' ? '#1890ff' : '#52c41a' }"
            >
              {{ msg.role === 'user' ? 'U' : 'AI' }}
            </a-avatar>
            <div class="message-content">
              <div class="message-text" v-html="renderMarkdown(msg.content)"></div>

              <!-- 竞品监控员：推理证据联动卡（数据底座背书 AI 解读） -->
              <CompetitorIntelEvidence
                v-if="msg.displayType === 'competitor_intel_analysis' && msg.data?.per_asin?.length"
                :data="msg.data"
              />

              <!-- HITL 审批卡片 -->
              <div v-if="msg.hitlRequired" class="hitl-card">
                <a-alert
                  type="warning"
                  show-icon
                  message="需要人工审批"
                  :description="`操作：${msg.hitlToolName}`"
                  style="margin-bottom: 12px"
                />
                <a-space>
                  <a-button type="primary" size="small" @click="handleHitlAccept(msg)">批准执行</a-button>
                  <a-button size="small" danger @click="handleHitlReject(msg)">拒绝</a-button>
                </a-space>
              </div>
            </div>
          </div>
          </div>

          <!-- 加载中 -->
          <div v-if="isLoading" class="message-item assistant">
            <a-avatar style="background-color: #52c41a">AI</a-avatar>
            <div class="message-content">
              <a-spin tip="AI 正在思考..." />
            </div>
          </div>
        </div>
    </div>

      <!-- 竞品监控员·统一分析动作条（输入框上方）：
           分析周期下拉 + 快入口 chips，联动右侧竞品选择器 -->
      <div v-if="isCompetitorIntelAgent" class="intel-action-bar">
        <div class="iab-controls">
          <div class="iab-period">
            <span class="iab-period-label">分析周期</span>
            <a-select
              v-model:value="intelDays"
              size="small"
              :options="periodOptions"
              style="width: 96px"
              :disabled="isLoading"
            />
          </div>
          <div class="iab-chips">
            <button
              v-for="c in intelChips"
              :key="c.id"
              class="iab-chip"
              :class="{ active: activeIntelChip === c.id }"
              :disabled="isLoading"
              @click="runIntelChip(c)"
            >
              <span class="iab-chip-icon">{{ c.icon }}</span>
              <span>{{ c.name }}</span>
            </button>
          </div>
        </div>
        <a-tag :color="pool.selectedAsins.length ? 'blue' : 'orange'" class="iab-scope-float">
          {{ pool.selectedAsins.length ? `已圈 ${pool.selectedAsins.length} 个竞品` : '未圈选·将分析全池' }}
        </a-tag>
      </div>

      <!-- 选品分析师·候选评估动作条（输入框上方）：
           评估对象 = 顶部【载入选品】选定的候选（未载入则提示先载入） -->
      <div v-else-if="isProductResearchAgent" class="intel-action-bar">
        <div class="iab-controls">
          <div class="iab-period" style="visibility:hidden">
            <span class="iab-period-label">评估对象</span>
          </div>
          <div class="iab-chips">
            <button
              v-for="c in candidateIntelChips"
              :key="c.id"
              class="iab-chip"
              :class="{ active: activeIntelChip === c.id }"
              :disabled="isLoading"
              @click="runCandidateChip(c)"
            >
              <span class="iab-chip-icon">{{ c.icon }}</span>
              <span>{{ c.name }}</span>
            </button>
          </div>
        </div>
        <a-tag :color="loadedCandidate ? 'geekblue' : 'orange'" class="iab-scope-float">
          {{ loadedCandidate ? `评估 ${loadedCandidate.title?.slice(0, 10)}…` : '未载入选品·请先载入评估对象' }}
        </a-tag>
      </div>

      <!-- Listing 优化师：输入框上方不再有 chip 动作条；
           跳转/生成/保存都通过顶部 4 个工具按钮（关键词/标题/五点/长描述）触发 -->


      <!-- 运营复盘师·统一分析动作条（输入框上方，与其他 Agent 布局一致）：
           快捷 chips：周报 / 月度复盘 / 广告优化 / 行动计划 -->
      <div v-else-if="isReviewAgent" class="intel-action-bar">
        <div class="iab-controls">
          <div class="iab-period" style="visibility:hidden">
            <span class="iab-period-label">复盘范围</span>
          </div>
          <div class="iab-chips">
            <button
              v-for="action in REVIEW_ACTIONS"
              :key="action.key"
              class="iab-chip"
              :class="{ 'rqa-loading': activeReviewAction === action.key }"
              :disabled="isLoading || activeReviewAction !== null"
              :title="action.desc"
              @click="runReviewAction(action)"
            >
              <span class="iab-chip-icon">{{ action.icon }}</span>
              <span>{{ action.name }}</span>
            </button>
          </div>
        </div>
        <a-tag :color="reviewScopeColor" class="iab-scope-float">
          {{ reviewScopeText }}
        </a-tag>
      </div>

      <!-- 广告分析师·快捷操作（输入框上方，出价建议 / 预算分配） -->
      <div v-else-if="isAdAnalyst" class="intel-action-bar">
        <div class="iab-controls">
          <div class="iab-period" style="visibility:hidden">
            <span class="iab-period-label">广告账户</span>
          </div>
          <div class="iab-chips">
            <button
              v-for="action in AD_QUICK_ACTIONS"
              :key="action.key"
              class="iab-chip"
              :class="{ 'rqa-loading': activeAdAction === action.key }"
              :disabled="isLoading || activeAdAction !== null"
              :title="action.desc"
              @click="runAdQuickAction(action)"
            >
              <span class="iab-chip-icon">{{ action.icon }}</span>
              <span>{{ action.name }}</span>
            </button>
          </div>
        </div>
        <a-tag :color="shopStore.currentShop ? 'geekblue' : 'orange'" class="iab-scope-float">
          {{ shopStore.currentShop ? `广告 ${shopStore.currentShop.name}` : '未选店铺·默认全账户' }}
        </a-tag>
      </div>


      <!-- 输入区域（卡片式，冻结在底部） -->
      <div class="input-area">
        <div class="input-card">
          <a-textarea
            v-model:value="inputMessage"
            :placeholder="inputPlaceholder"
            :auto-size="{ minRows: 3, maxRows: 6 }"
            @pressEnter="handleKeyPress"
            class="chat-textarea"
          />
          <div class="input-card-footer">
            <span class="input-hint">Enter 发送 · Shift+Enter 换行</span>
            <a-button
              type="primary"
              size="small"
              :loading="isLoading"
              :disabled="!inputMessage.trim()"
              @click="handleSend"
            >
              <SendOutlined /> 发送
            </a-button>
          </div>
        </div>
      </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted, inject, type Ref } from 'vue'
import { SendOutlined, RobotOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import MarkdownIt from 'markdown-it'

import { useAgentStore } from '@/stores/agent'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import { useChatStore } from '@/stores/chat'
import { useResultStore } from '@/stores/result'
import { useShopStore } from '@/stores/shop'
import { useListingDraftStore } from '@/stores/listingDraft'
import { useProductLibraryStore } from '@/stores/productLibrary'

// 结果展示组件（轻量级，只展示数据）
import BlueOceanResult from './results/BlueOceanResult.vue'
import KeywordMinerResult from './results/KeywordMinerResult.vue'
import PainPointResult from './results/PainPointResult.vue'
import CompetitorResult from './results/CompetitorResult.vue'
import ProfitResult from './results/ProfitResult.vue'
import TitleGenerator from './results/TitleGenerator.vue'
import BulletGenerator from './results/BulletGenerator.vue'
import SEODiagnostic from './results/SEODiagnostic.vue'
import ABTestGenerator from './results/ABTestGenerator.vue'
import DescriptionGenerator from './results/DescriptionGenerator.vue'
import AdDiagnosisResult from './results/AdDiagnosisResult.vue'
import SearchTermResult from './results/SearchTermResult.vue'
import BidOptimizeResult from './results/BidOptimizeResult.vue'
import CompetitorAdResult from './results/CompetitorAdResult.vue'
import BudgetAllocResult from './results/BudgetAllocResult.vue'
import AnomalyDetectResult from './results/AnomalyDetectResult.vue'
import OrderTrackResult from './results/OrderTrackResult.vue'
import TicketCreateResult from './results/TicketCreateResult.vue'
import MonitorDashboardResult from './results/MonitorDashboardResult.vue'
import CompetitorIntelEvidence from './results/CompetitorIntelEvidence.vue'
import PriceTrackResult from './results/PriceTrackResult.vue'
import MarketShareResult from './results/MarketShareResult.vue'
import PricingAnalysisResult from './results/PricingAnalysisResult.vue'
import ReviewSpyResult from './results/ReviewSpyResult.vue'
import IntruderAlertResult from './results/IntruderAlertResult.vue'
import BuyBoxAnalysisResult from './results/BuyBoxAnalysisResult.vue'
import CompareGridResult from './results/CompareGridResult.vue'
import AIGCMediaResult from './results/AIGCMediaResult.vue'
import { ToolDefinition, getAgentTools } from './tools/toolDefinitions'

const agentStore = useAgentStore()
const chatStore = useChatStore()
const pool = useMonitorPoolStore()
const candStore = useCandidateLibraryStore()
const shopStore = useShopStore()
const productLibraryStore = useProductLibraryStore()

// 从 Workspace 注入工具选择方法（快捷 chip 选中工具时同步右侧面板）
const setSelectedTool = inject<(tool: ToolDefinition | null) => void>('setSelectedTool', () => {})

// ===== 竞品监控员·统一动作条状态 =====
const isCompetitorIntelAgent = computed(() => agentStore.currentAgent?.id === 'competitor-intel')
// 选品分析师（候选评估动作条挂点）
const isProductResearchAgent = computed(() => agentStore.currentAgent?.id === 'product-research')
// Listing 优化师（SEO 诊断 chip 动作条挂点）
const isListingAgent = computed(() => agentStore.currentAgent?.id === 'listing-generator')
// 运营复盘师（快捷操作卡片挂点）
const isReviewAgent = computed(() => agentStore.currentAgent?.id === 'review-analyst')
// 广告分析师（出价/预算快捷操作挂点）
const isAdAnalyst = computed(() => agentStore.currentAgent?.id === 'ad-analysis')
const intelDays = ref(30)
const activeIntelChip = ref<string | null>(null)

// ====== 运营复盘师·快捷操作 ======
const activeReviewAction = ref<string | null>(null)

/** 复盘范围（右侧 scope tag，与其他 Agent 动作条一致的店铺上下文） */
const reviewScopeText = computed(() =>
  shopStore.currentShop
    ? `复盘 ${shopStore.currentShop.name}${shopStore.currentShop.platform ? ` · ${shopStore.currentShop.platform}` : ''}`
    : '未选店铺·默认全店数据'
)
const reviewScopeColor = computed(() =>
  shopStore.currentShop ? 'geekblue' : 'orange'
)

const REVIEW_ACTIONS = [
  { key: 'weekly-report', icon: '\u{1F4C4}', name: '周报', desc: '生成本周运营复盘周报：销售+广告+库存+利润汇总' },
  { key: 'monthly-review', icon: '\u{1F4CB}', name: '月度复盘', desc: '生成月度经营分析 + 环比 + 趋势' },
  { key: 'ad-optimization', icon: '\u{1F4C8}', name: '广告优化', desc: 'ACoS 诊断 + 关键词/出价建议' },
  { key: 'action-plan', icon: '\u{2705}', name: '行动计划', desc: '按优先级排序的止损/优化/机会执行清单' },
]

async function runReviewAction(action: typeof REVIEW_ACTIONS[0]) {
  if (activeReviewAction.value) return
  activeReviewAction.value = action.key

  // 构造发送给 AI 的 prompt
  const prompts: Record<string, string> = {
    'weekly-report': '请生成本周的运营复盘周报，包含：1) 销售概况（GMV/订单量/环比）2) 广告表现（ACoS/ROAS/Campaign 级别分析）3) 库存健康度 4) 利润核算 5) 下周重点行动项。用表格和结构化输出。',
    'monthly-review': '请生成本月的运营复盘报告，包含：1) 月度业绩总览（与上月/去年同期对比）2) 各 SKU 表现排名 3) 广告投放效果归因 4) Listing 质量变化 5) 库存周转分析 6) 下月策略建议。',
    'ad-optimization': '请基于当前广告数据生成优化方案：1) 整体 ACoS 分析（是否达标，偏差原因）2) 各 Campaign 表现评级（S/A/B/C）3) 高 ACoS Campaign 的具体优化建议（砍词/降价/关停）4) 低 ACoS Campaign 的扩量机会 5) 预期改善目标。',
    'action-plan': '请基于当前数据输出行动计划，按优先级分为三档：\n🔴 止损项（需24h内处理）：高ACoS Campaign / 断货风险SKU / 差评激增\n🟡 优化项（本周内处理）：Listing优化 / 出价调整 / 库存调拨\n🟢 机会点（本月规划）：新品上架 / 新关键词拓展 / 促销活动\n每项给出负责人、截止时间、预期效果。',
  }

  const userMessage = prompts[action.key] || `请帮我${action.name}`

  // 通过标准发送链路触发 AI 回复（含 review-analyst 专用 mock 回复分支）
  inputMessage.value = userMessage
  await handleSend()
  activeReviewAction.value = null
}

// ====== 广告分析师·快捷操作（出价建议 / 预算分配）======
const activeAdAction = ref<string | null>(null)

const AD_QUICK_ACTIONS = [
  { key: 'bid-suggest', icon: '\u{1F4A1}', name: '出价建议', desc: '基于转化数据的智能出价优化建议，预计降低 ACoS' },
  { key: 'budget-alloc', icon: '\u{1F4B3}', name: '预算分配', desc: '多 Campaign 预算优化分配方案，提升整体 RoAS' },
]

/** 广告工具默认参数（chip 快捷入口不带配置表单，用合理默认值） */
const AD_DEFAULT_PARAMS: Record<string, any> = {
  'bid-suggest': { strategy: 'balanced', target_acos: 20, budget_change_limit: 20 },
  'budget-alloc': { total_daily_budget: 1000, target_roas: 4, seasonality: 'medium' },
}

async function runAdQuickAction(action: typeof AD_QUICK_ACTIONS[0]) {
  if (activeAdAction.value) return
  activeAdAction.value = action.key

  // 从工具定义中找到完整工具对象
  const allTools = getAgentTools('ad-analysis')
  const toolDef = allTools.find(t => t.id === action.key)
  if (!toolDef) {
    activeAdAction.value = null
    return
  }

  // 注意：不再调用 setSelectedTool(toolDef) 切换右侧面板，
  // 保持广告分析师大屏看板不变（与运营复盘师 chip 行为对齐）

  // 延迟一帧后直接触发分析（对话流渲染，不动右侧看板）
  setTimeout(() => {
    window.dispatchEvent(new CustomEvent('tool-analysis', {
      detail: { tool: toolDef, params: AD_DEFAULT_PARAMS[action.key] || {} }
    }))
    activeAdAction.value = null
  }, 100)
}
const intelChips = [
  { id: 'intel-weekly', name: '竞品周报', icon: '📋', intent: 'weekly', question: '请生成本周期竞品周报：谁降价、谁爆发差评、谁改Listing抢流量、促销节奏如何，并给出下一周期关注重点。' },
  { id: 'intel-anomaly', name: '异动洞察', icon: '🚨', intent: 'anomaly', question: '请检测这些竞品近期的异动（BSR暴涨/差评激增/价格骤降/Listing改动/断货），识别主动进攻还是被动暴露，并解读原因。' },
  { id: 'intel-strategy', name: '策略推演', icon: '🧠', intent: 'strategy', question: '请基于这些竞品的近期动作，推演我方的反制与定价/上新/广告节奏建议。' },
]
// Listing 优化师·快入口（针对顶部「载入产品」选定的产品做诊断/辅助）
// 选品分析师·候选快入口（针对顶部「载入选品」选定的单个候选做 AI 推理）
// 5 个 chip 全部走 AI 推理模式，评估对象 = 载入的候选；form 类工具（蓝海挖掘/利润测算）保留在顶部工具栏
const candidateIntelChips = [
  { id: 'cand-feasibility', name: '市场可行性', icon: '📊', intent: 'feasibility', question: '评估该选品的市场可行性与优先级' },
  { id: 'cand-launch',       name: '上架建议',   icon: '🚀', intent: 'launch',      question: '给出该选品上架/运营的前置建议' },
  { id: 'cand-pain',         name: '痛点分析',   icon: '🔍', intent: 'pain',        question: '分析该选品的潜在用户痛点与改进机会' },
  { id: 'cand-pitfall',      name: '选品避坑',   icon: '⚠️', intent: 'pitfall',     question: '对该选品做专利/认证/合规/红海多维风险扫描' },
  { id: 'cand-compare',      name: '竞品对比',   icon: '⚔️', intent: 'compare',     question: '对该选品已挂的对标竞品做对比分析' },
]
const periodOptions = [
  { value: 7, label: '近 7 天' },
  { value: 14, label: '近 14 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
]

/** 选品分析师当前「载入」的评估主角（由顶部 CandidateLoaderButton 写入 workingCandidate） */
const loadedCandidate = inject<Ref<any>>('workingCandidate', ref(null))

/** Listing 优化师当前「载入」的产品（由顶部 ProductLoaderButton 写入 workingProduct） */
const loadedProduct = inject<Ref<any>>('workingProduct', ref(null))

/** 确保候选库已加载 */
async function ensureCandidateLoaded() {
  if (!candStore.items.length && !candStore.isLoading) {
    try { await candStore.fetchItems() } catch (e) { /* 忽略 */ }
  }
}

/** 点选选品 chip → 针对「载入的候选」跑 AI 推理评估；未载入则提示先载入 */
const runCandidateChip = async (c: (typeof candidateIntelChips)[number]) => {
  if (isLoading.value) return
  // 未载入选品 → 提示先载入，不发起评估
  if (!loadedCandidate.value) {
    chatStore.addMessage({ role: 'assistant', content: '> 💡 请先在顶部点击 **【载入选品】**，从选品库选定要评估的候选后，再执行本操作。' })
    return
  }
  activeIntelChip.value = c.id
  isLoading.value = true
  const { analyzeCandidateSelection } = await import('@/mock/competitorIntel')
  try {
    await ensureCandidateLoaded()
    // 若载入的候选已不在选品库（被删除等），回退到仍按快照评估
    const cands = [loadedCandidate.value]
    const reply = analyzeCandidateSelection(cands, c.intent as any)
    chatStore.addMessage({ role: 'user', content: `${c.icon} **${c.name}** · ${loadedCandidate.value.title}` })
    chatStore.addMessage({ role: 'assistant', content: reply })
    await scrollToBottom()
  } catch (error) {
    console.error('选品评估失败:', error)
    chatStore.addMessage({ role: 'assistant', content: '❌ 评估执行失败，请重试。' })
  } finally {
    isLoading.value = false
    setTimeout(() => { activeIntelChip.value = null }, 400)
  }
}

/** 点选 chip → 直接跑竞品监控 mock 推理（读右侧圈选 ASIN） */
const runIntelChip = async (c: (typeof intelChips)[number]) => {
  if (isLoading.value) return
  activeIntelChip.value = c.id
  isLoading.value = true
  const { analyzeCompetitorIntel } = await import('@/mock/competitorIntel')
  try {
    const out = analyzeCompetitorIntel(c.question, {
      forceIntent: c.intent as any,
      scopeAsins: pool.selectedAsins.length ? [...pool.selectedAsins] : undefined,
      days: intelDays.value,
    })
    chatStore.addMessage({ role: 'user', content: `📋 **${c.name}** · ${periodOptions.find(o => o.value === intelDays.value)?.label}分析` })
    chatStore.addMessage({
      role: 'assistant',
      content: out.reply,
      data: out.evidence,
      displayType: 'competitor_intel_analysis',
    })
    await scrollToBottom()
  } catch (error) {
    console.error('竞品监控动作条推理失败:', error)
    chatStore.addMessage({ role: 'assistant', content: '❌ 分析执行失败，请重试。' })
  } finally {
    isLoading.value = false
    // 保留高亮一小会便于看到来源，随后复位
    setTimeout(() => { activeIntelChip.value = null }, 400)
  }
}

// SEO 诊断已下线（原 Listing 优化师 chip `runListingChip` + `buildSeoDiagnosticResult` 已删除）

// Markdown 渲染器
const md = new MarkdownIt()

// ========== 状态管理 ==========

// 当前模式: tool(工具) / chat(对话)
const currentMode = ref<'tool' | 'chat'>('chat')

// 当前选中的工具
const selectedTool = ref<ToolDefinition | null>(null)

// 工具执行结果通过消息流展示（displayType: 'tool_result'），无需独立状态

// 消息列表（Pinia 已解包 computed，直接引用即可保持响应式）
const messages = computed(() => chatStore.messages)

// 输入框内容
const inputMessage = ref('')

// 加载状态
const isLoading = ref(false)

// 引用
const messageListRef = ref<HTMLElement>()
const mainContentRef = ref<HTMLElement>()

// 输入框提示文字
const inputPlaceholder = computed(() => {
  if (!agentStore.currentAgent) return '请先在左侧选择一个 Agent...'
  return `向 ${agentStore.currentAgent.name} 提问...`
})

// 从消息流中移除指定工具结果
const removeToolResult = (index: number) => {
  chatStore.removeMessage(index)
}

// 导航到其他视图（产品库/知识库）
const handleNavigateTo = (view: string) => {
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view } }))
}

// ========== 监听右侧面板的分析请求 ==========
onMounted(() => {
  window.addEventListener('tool-analysis', handleToolAnalysisEvent as unknown as EventListener)
})

onUnmounted(() => {
  window.removeEventListener('tool-analysis', handleToolAnalysisEvent as unknown as EventListener)
})

// 处理来自右侧面板的分析请求
const handleToolAnalysisEvent = async (event: CustomEvent) => {
  const { tool, params } = event.detail

  if (!tool) return

  // 设置当前工具状态
  selectedTool.value = { ...tool }
  currentMode.value = 'tool'
  isLoading.value = true

  // ===== 竞品监控员·智能推理工具（读监控池 → 解读+证据，不走 form 结果表）=====
  if (['intel-chat', 'intel-weekly', 'intel-anomaly', 'intel-strategy'].includes(tool.id)) {
    try {
      const { analyzeCompetitorIntel } = await import('@/mock/competitorIntel')
      const q = params?.question || ''
      const out = analyzeCompetitorIntel(q)
      // 用户消息（问题）
      chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}**：${q}` })
      // 推理解读文本 + 证据联动卡
      chatStore.addMessage({
        role: 'assistant',
        content: out.reply,
        data: out.evidence,
        displayType: 'competitor_intel_analysis',
      })
      await scrollToBottom()
    } catch (error) {
      console.error('竞品监控智能推理失败:', error)
      chatStore.addMessage({ role: 'assistant', content: `❌ 智能推理执行失败，请重试。` })
    } finally {
      isLoading.value = false
    }
    return
  }

  // ===== 步骤1：添加用户消息（独立 try-catch）=====
  try {
    const paramSummary = getParamSummary(tool.id, params || {})
    chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${paramSummary}` })
  } catch (msgError) {
    console.warn('参数摘要生成失败（使用 fallback）:', msgError)
    chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${JSON.stringify(params || {}, null, 2)}` })
  }

  // ===== 步骤2：执行分析（主 try-catch）=====
  try {
    let result: any
    switch (tool.id) {
      case 'blue-ocean':
        result = await executeBlueOceanAnalysis(params)
        break
      case 'pain-points':
        result = await executePainPointAnalysis(params)
        break
      case 'competitor':
        result = await executeCompetitorAnalysis(params)
        break
      case 'profit-calc':
        result = await executeProfitAnalysis(params)
        break
      case 'ad-diagnosis':
        result = await executeAdDiagnosis(params)
        break
      case 'keyword-report':
        result = await executeSearchTermReport(params)
        break
      case 'bid-suggest':
        result = await executeBidSuggest(params)
        break
      case 'competitor-ad':
        result = await executeCompetitorAd(params)
        break
      case 'budget-alloc':
        result = await executeBudgetAlloc(params)
        break
      case 'anomaly-detect':
        result = await executeAnomalyDetect(params)
        break
      case 'order-track':
        result = await executeOrderTrack(params)
        break
      case 'ticket-create':
        result = await executeTicketCreate(params)
        break
      case 'monitor-dashboard':
        result = await executeMonitorDashboard(params)
        break
      case 'price-track':
        result = await executePriceTrack(params)
        break
      case 'market-share':
        result = await executeMarketShare(params)
        break
      case 'pricing-analysis':
        result = await executePricingAnalysis(params)
        break
      case 'review-spy':
        result = await executeReviewSpy(params)
        break
      case 'intruder-alert':
        result = await executeIntruderAlert(params)
        break
      case 'buy-box-analysis':
        result = await executeBuyBoxAnalysis(params)
        break
      case 'compare-grid':
        result = await executeCompareGrid(params)
        break
      // ===== Listing 优化师工具 =====
      case 'keyword-miner':
        result = await executeKeywordMiner(params)
        break
      case 'title-gen':
        result = await executeTitleGen(params)
        break
      case 'bullet-gen':
        result = await executeBulletGen(params)
        break
      case 'desc-gen':
        result = await executeDescGen(params)
        break
      case 'seo-audit':
        result = await executeSEOAudit(params)
        break
      case 'ab-test':
        result = await executeABTest(params)
        break
      // ===== 选品分析师补充 =====
      case 'pitfalls':
        result = await executePitfalls(params)
        break
      // ===== AIGC 媒体生成器 =====
      case 'static-asset-gen':
        result = await executeStaticAssetGen(params)
        break
      case 'video-script-gen':
        result = await executeVideoScriptGen(params)
        break
      case 'ai-video-generator':
        result = await executeAIVideoGenerator(params)
        break
      // ===== 运营复盘师 =====
      case 'weekly-report':
        result = await executeWeeklyReport(params)
        break
      case 'monthly-review':
        result = await executeMonthlyReview(params)
        break
      case 'ad-review':
        result = await executeAdReview(params)
        break
      case 'product-performance':
        result = await executeProductPerformance(params)
        break
      case 'inventory-health':
        result = await executeInventoryHealth(params)
        break
      case 'profit-audit':
        result = await executeProfitAudit(params)
        break
      case 'action-plan':
        result = await executeActionPlan(params)
        break
      default:
        throw new Error(`未知工具: ${tool.id}`)
    }

    // 视频脚本同步到共享 store（供 AI 短视频生成「分镜脚本专业模式」复用）
    if (tool.id === 'video-script-gen') {
      saveScriptToStore(result)
    }

    // Listing 工具结果同步到「Listing 工作区」草稿（右侧面板可直接接着编辑/保存）
    syncListingDraft(tool.id, params, result)

    // ===== 步骤3：将结果插入对话流 =====
    chatStore.addMessage({
      role: 'assistant',
      content: '',
      displayType: 'tool_result',
      data: {
        toolId: tool.id,
        toolName: tool.name,
        resultData: result,
      },
    })

    // 摘要消息（独立 try-catch，防止摘要生成错误导致主流程报错）
    try {
      addResultSummaryToChat(tool.id, result)
    } catch (summaryError) {
      console.warn('结果摘要生成失败（不影响主结果）:', summaryError)
    }

  } catch (error: unknown) {
    const err = error as Error
    console.error('=== 工具执行失败详情 ===')
    console.error('工具 ID:', tool?.id)
    console.error('错误类型:', err?.constructor?.name)
    console.error('错误消息:', err?.message)
    console.error('接收到的 params:', JSON.stringify(params || {}))
    console.error('错误堆栈:', err?.stack)
    console.error('========================')
    chatStore.addMessage({
      role: 'assistant',
      content: `❌ 分析执行失败，请检查参数后重试。\n\n\`${err?.message || '未知错误'}\``,
    })
  } finally {
    isLoading.value = false
    await scrollToBottom()
  }
}

// 获取参数摘要文本
const getParamSummary = (toolId: string, params: any): string => {
  switch (toolId) {
    case 'blue-ocean':
      return `- 站点：${params.marketplace || 'US'}\n- 类目：${params.category?.join(' > ') || '全部'}\n- 价格：$${params.priceMin || 0} ~ $${params.priceMax || '不限'}\n- 评论上限：${params.maxReviews || '不限'}条\n- 最小月销：${params.minMonthlySales || '不限'}件\n- 最低ROI：${params.minRoi || 0}%`
    case 'pain-points':
      return `- ASIN：${params.asin}\n- 分析深度：${params.depth === 'deep' ? '深度' : '快速'}\n- 评论范围：${params.reviewRange} 条`
    case 'competitor':
      return `- 竞品数：${params.validAsins?.length || params.asins?.filter((a: string) => a)?.length || 0} 个\n- 对比维度：${params.dimensions?.join('、') || '全部'}`
    case 'profit-calc':
      return `- 成本：$${params.costPrice || 0}\n- 售价：$${params.sellingPrice || 0}\n- 模式：${params.mode === 'reverse' ? '逆向定价' : '正向计算'}`
    case 'ad-diagnosis':
      return `- 时间范围：${timeRangeLabel(params.time_range)}\n- Campaign：${params.campaign_ids?.join('、') || '全部'}\n- 行业基准对比：${params.include_benchmark ? '是' : '否'}`
    case 'keyword-report':
      return `- 时间范围：${timeRangeLabel(params.time_range)}\n- Campaign类型：${params.campaign_types?.join('、') || 'SP/SB/SD'}\n- 最小花费过滤：$${params.min_spend || 0}\n- 排序方式：${params.sort_by || 'spend'}`
    case 'bid-suggest':
      return `- 策略：${({ aggressive: '激进', balanced: '平衡', conservative: '保守' } as Record<string, string>)[params.strategy] || '平衡'}\n- 目标ACoS：${params.target_acos || 20}%\n- 预算变动上限：±${params.budget_change_limit || 20}%`
    case 'competitor-ad':
      return `- 竞品ASIN：${params.asin_tags?.join('、') || '未指定'}\n- 自动检测：${params.auto_detect ? '是' : '否'}\n- 关键词重叠分析：${params.analyze_overlap ? '是' : '否'}`
    case 'budget-alloc':
      return `- 总日预算：$${params.total_daily_budget || 1000}\n- 目标RoAS：${params.target_roas || 4}x\n- 季节性因素：$(({ low: '低', medium: '中', high: '高', peak: '旺季' } as Record<string, string>)[params.seasonality] || '中')`
    case 'anomaly-detect':
      return `- 检测周期：$(({ '7d': '近7天', '14d': '近14天', '30d': '近30天' } as Record<string, string>)[params.check_period] || '近7天'}\n- 敏感度：${params.sensitivity || 'medium'}`
    case 'order-track':
      return `- 查询方式：${params.order_id ? `订单号 ${params.order_id}` : params.email ? `邮箱 ${params.email}` : params.phone_last4 ? `手机后四位 ${params.phone_last4}` : '未知'}`
    case 'ticket-create':
      return `- 标题：${params.subject}\n- 分类：${params.category || 'general'}\n- 优先级：${params.priority || 'medium'}\n- 关联订单：${params.order_id || '无'}`
    case 'monitor-dashboard':
      return `- 目标ASIN：${params.asin || '全部竞品'}\n- 时间范围：近 ${params.days || 30} 天`
    case 'price-track':
      return `- 追踪ASIN：${params.asins?.join('、') || '-'}（${params.asins?.length || 0}个）\n- 历史趋势：${params.include_history ? '包含' : '不含'}`
    case 'market-share':
      return `- 类目：${params.category}\n- 估算方法：${params.estimate_method === 'revenue_based' ? '收入估算' : 'BSR排名估算'}`
    case 'pricing-analysis':
      return `- 目标ASIN：${params.asin || '全部'}\n- 对比竞品：${params.compare_asins?.join('、') || '无'}\n- 分析深度：${({ basic: '基础', standard: '标准', deep: '深度' } as Record<string, string>)[params.analysis_depth] || '标准'}`
    case 'review-spy':
      return `- 目标ASIN：${params.asin}\n- 关注维度：${params.aspects?.join('、') || '全部'}\n- 采样数：${params.sample_size || 100} 条`
    case 'intruder-alert':
      return `- 监控类目：${params.category}\n- 回溯天数：${params.lookback_days || 30} 天\n- 评论阈值：≥ ${params.min_reviews_threshold || 50} 条`
    case 'buy-box-analysis':
      return `- 目标ASIN：${params.asin || '全部'}\n- 站点：${params.marketplace || 'US'}`
    case 'compare-grid':
      return `- 对比ASIN：${params.asins?.join('、') || '-'}（${params.asins?.length || 0}个）\n- 维度：${params.dimensions?.join('、') || '全部'}`
    // ===== Listing 优化师 =====
    case 'keyword-miner':
      return `- 种子词：${params.seed_keywords?.join('、') || '未指定'}\n- 目标数量：${params.target_count || 20} 个\n- 来源：${['种子词扩展', '竞品词', '类目词', '长尾词'].join(' / ')}`
    case 'title-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 语言：${params.language || '英语(美国)'}\n- 风格：${params.style || '专业电商'}`
    case 'bullet-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 卖点数：5 条\n- 风格：${params.style || '利益驱动型'}`
    case 'desc-gen':
      return `- 产品名称：${params.product_name || '未指定'}\n- 模块：${params.modules?.join('、') || '品牌故事+规格+场景'}\n- 风格：${params.tone || '专业可信'}`
    case 'seo-audit':
      return `- ASIN：${params.asin || '未指定'}\n- 站点：${params.marketplace || 'US'}\n- 深度：${({ basic: '基础', full: '全面' } as Record<string, string>)[params.depth] || '全面'}`
    case 'ab-test':
      return `- 测试变量：标题+主图\n- 流量分配：A(40%) / B(30%) / C(30%)\n- 周期：${params.duration || 14} 天`
    // ===== 选品分析师 =====
    case 'pitfalls':
      return `- 目标产品：${params.asin || params.product_name || '未指定'}\n- 扫描维度：8 项全扫描\n- 严重程度过滤：全部`
    // ===== AIGC 媒体生成器 =====
    case 'static-asset-gen':
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 素材类型：${(params.imageTypes || []).join('、') || '三视图'}\n- 数量：${params.quantity || 4} 张\n- 模式：图生图（${params.source_image_name || '已上传原图'}）`
    case 'video-script-gen':
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 平台：${({ tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' } as Record<string, string>)[params.platform] || 'TikTok'}\n- 风格：${params.videoStyle || '痛点解决型'}\n- 分镜数：${params.scenes?.length || 5} 个镜头\n- 总时长：${params.total_scene_duration || 30}s`
    case 'ai-video-generator':
      const modeLabel = params.mode === 'single-image' ? '🖼️ 单图极速生成' : '🎬 分镜脚本专业模式'
      return `- 产品：${params._sourceProduct?.title || params.productName || '未指定'}\n- 生成模式：${modeLabel}\n` +
        (params.mode === 'single-image'
          ? `- 底图：${params.singleImageUrl ? '已选择 ✓' : '未选择'}\n- 产品文案：${params.singleCopyText?.slice(0, 50) || '未填写'}\n- 平台：${params.targetPlatform || 'TikTok'}`
          : `- 镜头数：${params.storyboardScenes?.length || 0} 个\n- 各镜头素材来源：${params.storyboardScenes?.filter((s: any) => s.imageUrl).length || 0}/${params.storyboardScenes?.length || 0} 已就绪\n- 平台：${params.targetPlatform || 'TikTok'}`)
    // ===== 运营复盘师 =====
    case 'weekly-report':
      return `- 报告周期：${params.week_label || '本周'}\n- 包含模块：销售/广告/库存/客诉/预警`
    case 'monthly-review':
      return `- 复盘月份：${params.month_label || new Date().toISOString().slice(0, 7)}\n- 包含模块：GMV趋势/SKU排名/战略建议`
    case 'ad-review':
      return `- 时间范围：${params.period || '近30天'}\n- 分析深度：Campaign归因 + 关键词 attribution`
    case 'product-performance':
      return `- 时间范围：${params.period || '近30天'}\n- 排序维度：${params.sort_by || '营收降序'}`
    case 'inventory-health':
      return `- 检查日期：${new Date().toISOString().slice(0, 10)}\n- 预警阈值：<14天断货 / >50天滞销`
    case 'profit-audit':
      return `- 审计周期：${params.period || '本月'}\n- 核算维度：收入-COGS-佣金-FBA-广告-退货-仓储=净利`
    case 'action-plan':
      return `- 复盘周期：${params.dateRange ? '已选择' : '默认本月'}\n- 自动分类：止损项 + 优化项 + 机会点\n- 输出：${params.detailLevel || '标准'}版`
    default:
      return JSON.stringify(params, null, 2)
  }
}

// 执行蓝海挖掘分析（Mock）
const executeBlueOceanAnalysis = async (params: any): Promise<any> => {
  // 模拟异步处理
  await new Promise(resolve => setTimeout(resolve, 600))

  // 使用 Mock 数据生成结果（从 mock/data.ts 取带图片的真实商品数据）
  const products = await generateMockBlueOceanProducts(params)

  return {
    type: 'blue_ocean',
    params,
    products,
    summary: {
      total_candidates: products.length,
      high_potential: products.filter((p: any) => p.blue_ocean_score >= 65).length,
      medium_potential: products.filter((p: any) => p.blue_ocean_score >= 40 && p.blue_ocean_score < 65).length,
      high_competition: products.filter((p: any) => p.blue_ocean_score < 40).length,
    },
    report: `## 蓝海市场分析报告\n\n基于您设定的筛选条件，系统在 **${params.marketplace || 'US'}** 站点发现 **${products.length}** 个候选商品。\n\n### 市场洞察\n1. **Home & Kitchen** 类目竞争度相对较低，新进入者有较大机会\n2. 价格区间 $15-$35 的商品 ROI 表现最优\n3. 评论数 <100 的商品平均月销量达 800+，验证了"低竞争+有需求"的蓝海特征\n\n### TOP3 推荐\n1. **便携式加湿器** - 蓝海评分 82，建议定价 $24.99\n2. **硅胶厨具套装** - 蓝海评分 76，差异化空间大\n3. **LED植物生长灯** - 蓝海评分 74，季节性需求稳定`
  }
}

/**
 * 生成 Mock 蓝海产品数据
 * 从 mock/data.ts 的增强蓝海候选（getBlueOceanCandidates）取数，
 * 已含 main_image 及变体数/卖家数/头程/类目/趋势等扩展字段。
 */
const generateMockBlueOceanProducts = async (params: any): Promise<any[]> => {
  const { getBlueOceanCandidates } = await import('@/mock/data')
  const products = getBlueOceanCandidates(8)

  // 追加 params 信息（marketplace/category 透传给上层渲染）
  return products.map(p => ({
    ...p,
    marketplace: params.marketplace || p.marketplace || 'us',
    category: params.category?.join(' > ') || p.category_l2 || p.category_path?.join(' > ') || p.category || 'Home & Kitchen',
  }))
}

// 执行痛点分析（Mock）
const executePainPointAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))
  const { getMockPainPointAnalysis } = await import('@/mock/data')
  return getMockPainPointAnalysis(params.asin)
}

// 执行竞品对比（Mock）
const executeCompetitorAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))
  const { getMockCompetitorComparison } = await import('@/mock/data')
  return getMockCompetitorComparison(params.validAsins || params.asins.filter((a: string) => a))
}

// 执行利润测算（Mock）
const executeProfitAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 400))

  const sellingPrice = params.sellingPrice || 29.99
  const costPrice = params.costPrice || 8.5
  const shippingCost = params.shippingCost || 3.2

  const referralFee = sellingPrice * 0.15
  const fbaFee = sellingPrice * 0.12
  const totalCost = costPrice + shippingCost + referralFee + fbaFee
  const netProfit = sellingPrice - totalCost
  const roi = (netProfit / totalCost) * 100

  return {
    type: 'profit_analysis',
    params,
    calculation: {
      selling_price: sellingPrice,
      cost_price: costPrice,
      shipping_cost: shippingCost,
      referral_fee: parseFloat(referralFee.toFixed(2)),
      fba_fee: parseFloat(fbaFee.toFixed(2)),
      total_cost: parseFloat(totalCost.toFixed(2)),
      net_profit: parseFloat(netProfit.toFixed(2)),
      roi: parseFloat(roi.toFixed(1)),
    },
    breakdown: [
      { item: '采购成本', amount: costPrice },
      { item: '头程运费', amount: shippingCost },
      { item: '平台佣金 (15%)', amount: parseFloat(referralFee.toFixed(2)) },
      { item: 'FBA 配送费', amount: parseFloat(fbaFee.toFixed(2)) },
    ]
  }
}

// ========== 广告分析 Mock 执行函数 ==========

// 执行广告诊断（Mock）
const executeAdDiagnosis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 600))

  const timeRangeMap: Record<string, string> = { '7d': '近7天', '30d': '近30天', '90d': '近90天' }
  const grades = ['A', 'B', 'C', 'D', 'F']
  const grade = grades[Math.floor(Math.random() * 2)] // 倾向给较好评级
  const score = grade === 'A' ? 85 + Math.floor(Math.random() * 12) : grade === 'B' ? 72 + Math.floor(Math.random() * 12) : 58 + Math.floor(Math.random() * 15)

  return {
    overall_score: score,
    grade,
    summary: `账户整体表现${grade === 'A' ? '优秀' : grade === 'B' ? '良好' : '一般'}，${timeRangeMap[params.time_range] || '近30天'}内各项指标${score >= 75 ? '基本达标' : '存在优化空间'}。`,
    metrics: [
      { name: 'ACoS', value: 18 + Math.random() * 17, unit: '%', benchmark: 22.0, status: Math.random() > 0.4 ? 'good' : 'warning', change_pct: (Math.random() - 0.5) * 10 },
      { name: 'RoAS', value: 2.8 + Math.random() * 2.7, unit: 'x', benchmark: 4.5, status: Math.random() > 0.35 ? 'good' : 'warning', change_pct: (Math.random() - 0.5) * 8 },
      { name: 'CTR', value: 0.25 + Math.random() * 0.4, unit: '%', benchmark: 0.40, status: Math.random() > 0.35 ? 'good' : 'warning', change_pct: (Math.random() - 0.5) * 6 },
      { name: 'CVR', value: 5 + Math.random() * 9, unit: '%', benchmark: 9.0, status: Math.random() > 0.45 ? 'good' : 'warning', change_pct: (Math.random() - 0.5) * 10 },
      { name: 'CPC', value: 0.45 + Math.random() * 0.75, unit: '$', benchmark: 0.75, status: Math.random() > 0.4 ? 'good' : 'warning', change_pct: (Math.random() - 0.5) * 8 },
    ],
    campaigns: [
      { campaign_name: '自动广告-广泛', campaign_type: 'SP', status: 'active', spend: 450 + Math.random() * 500, impressions: 80000 + Math.floor(Math.random() * 150000), clicks: 1200 + Math.floor(Math.random() * 2000), orders: 40 + Math.floor(Math.random() * 60), sales: (orders: any) => orders * (25 + Math.random() * 20), acos: (s: any) => (s.spend / s.sales(s) * 100), roas: (s: any) => s.sales(s) / s.spend, ctr: (c: any) => c.clicks / c.impressions * 100, cvr: (c: any) => c.orders / c.clicks * 100, cpc: (c: any) => c.spend / c.clicks, health_score: 60 + Math.floor(Math.random() * 30) },
      { campaign_name: '手动-精准-核心词', campaign_type: 'SP', status: 'active', spend: 600 + Math.random() * 600, impressions: 40000 + Math.floor(Math.random() * 60000), clicks: 2000 + Math.floor(Math.random() * 2500), orders: 80 + Math.floor(Math.random() * 80), sales: (o: any) => o * (28 + Math.random() * 18), acos: (s: any) => (s.spend / s.sales(s) * 100), roas: (s: any) => s.sales(s) / s.spend, ctr: (c: any) => c.clicks / c.impressions * 100, cvr: (c: any) => c.orders / c.clicks * 100, cpc: (c: any) => c.spend / c.clicks, health_score: 70 + Math.floor(Math.random() * 25) },
      { campaign_name: '手动-短语-长尾词', campaign_type: 'SP', status: 'active', spend: 220 + Math.random() * 180, impressions: 50000 + Math.floor(Math.random() * 70000), clicks: 600 + Math.floor(Math.random() * 900), orders: 18 + Math.floor(Math.random() * 30), sales: (o: any) => o * (22 + Math.random() * 16), acos: (s: any) => (s.spend / s.sales(s) * 100), roas: (s: any) => s.sales(s) / s.spend, ctr: (c: any) => c.clicks / c.impressions * 100, cvr: (c: any) => c.orders / c.clicks * 100, cpc: (c: any) => c.spend / c.clicks, health_score: 65 + Math.floor(Math.random() * 28) },
      { campaign_name: '品牌-SB-品牌词', campaign_type: 'SB', status: 'active', spend: 150 + Math.random() * 120, impressions: 12000 + Math.floor(Math.random() * 18000), clicks: 350 + Math.floor(Math.random() * 500), orders: 14 + Math.floor(Math.random() * 25), sales: (o: any) => o * (32 + Math.random() * 15), acos: (s: any) => (s.spend / s.sales(s) * 100), roas: (s: any) => s.sales(s) / s.spend, ctr: (c: any) => c.clicks / c.impressions * 100, cvr: (c: any) => c.orders / c.clicks * 100, cpc: (c: any) => c.spend / c.clicks, health_score: 72 + Math.floor(Math.random() * 23) },
      { campaign_name: '展示-SD-竞品定向', campaign_type: 'SD', status: 'active', spend: 280 + Math.random() * 220, impressions: 30000 + Math.floor(Math.random() * 50000), clicks: 420 + Math.floor(Math.random() * 650), orders: 10 + Math.floor(Math.random() * 20), sales: (o: any) => o * (30 + Math.random() * 18), acos: (s: any) => (s.spend / s.sales(s) * 100), roas: (s: any) => s.sales(s) / s.spend, ctr: (c: any) => c.clicks / c.impressions * 100, cvr: (c: any) => c.orders / c.clicks * 100, cpc: (c: any) => c.spend / c.clicks, health_score: 50 + Math.floor(Math.random() * 30) },
    ].map(c => ({
      ...c,
      spend: Math.round(c.spend * 100) / 100,
      sales: Math.round(c.sales(c) * 100) / 100,
      acos: Math.round(c.acos(c) * 10) / 10,
      roas: Math.round(c.roas(c) * 100) / 100,
      ctr: Math.round(c.ctr(c) * 100) / 100,
      cvr: Math.round(c.cvr(c) * 10) / 10,
      cpc: Math.round(c.cpc(c) * 100) / 100,
    })),
    top_issues: [
      { type: 'acos_high', title: '部分 Campaign ACoS 偏高', description: '展示广告(SD) Campaign 的 ACoS 超过 35%，建议优化定向或降低出价', priority: 'high' },
      { type: 'ctr_low', title: '品牌词 CTR 有提升空间', description: 'SB 品牌 Campaign CTR 仅 0.29%，建议测试新创意素材', priority: 'medium' },
      { type: 'negative_missing', title: '否定关键词可能不足', description: '搜索词报告中发现多笔无转化花费，建议加强否词管理', priority: 'medium' },
    ],
    recommendations: [
      '🔥 暂停 SD Campaign 中 ACoS > 50% 的低效投放，转移预算到 SP 精准匹配',
      '📝 对 SB 品牌词 Campaign 进行 A/B 测试，选择 CTR 更高的创意素材',
      '📊 本周下载搜索词报告，新增不少于 10 个精确否定词',
      '💰 对 RoAS > 5 的核心词 Campaign 适当提高预算 15%',
      '🎯 开启商品投放(PAT)扩展流量来源，降低对单一关键词的依赖',
    ],
  }
}

// 执行搜索词报告（Mock）
const executeSearchTermReport = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 550))

  const termPool = [
    { term: 'portable coffee grinder manual', impr: 12500, clicks: 380, spend: 342.00, sales: 1280.00, acos: 26.7, roas: 3.7, orders: 42, cpc: 0.90, match_type: 'exact', efficiency: 'high' },
    { term: 'ceramic burr coffee grinder', impr: 8900, clicks: 290, spend: 261.00, sales: 956.00, acos: 27.3, roas: 3.7, orders: 34, cpc: 0.90, match_type: 'phrase', efficiency: 'high' },
    { term: 'hand coffee bean grinder travel', impr: 15600, clicks: 520, spend: 468.00, sales: 1872.00, acos: 25.0, roas: 4.0, orders: 62, cpc: 0.90, match_type: 'exact', efficiency: 'high' },
    { term: 'coffee mill hand crank stainless', impr: 4300, clicks: 98, spend: 88.20, sales: 198.00, acos: 44.5, roas: 2.2, orders: 8, cpc: 0.90, match_type: 'broad', efficiency: 'low' },
    { term: 'best coffee grinder under 30', impr: 22000, clicks: 1100, spend: 990.00, sales: 0, acos: 999, roas: 0, orders: 0, cpc: 0.90, match_type: 'broad', efficiency: 'waste' },
    { term: 'aeropress coffee grinder recommendation', impr: 3100, clicks: 78, spend: 70.20, sales: 0, acos: 999, roas: 0, orders: 0, cpc: 0.90, match_type: 'phrase', efficiency: 'waste' },
    { term: 'cold brew coffee grinder coarse', impr: 6700, clicks: 185, spend: 148.00, sales: 444.00, acos: 33.3, roas: 3.0, orders: 15, cpc: 0.80, match_type: 'exact', efficiency: 'medium' },
    { term: 'hario mini mill slim plus', impr: 2900, clicks: 92, spend: 82.80, sales: 265.00, acos: 31.3, roas: 3.2, orders: 10, cpc: 0.90, match_type: 'exact', efficiency: 'low' },
  ]

  return {
    period: timeRangeLabel(params.time_range),
    total_terms: 42,
    high_performers: termPool.filter(t => t.efficiency === 'high'),
    low_performers: termPool.filter(t => t.efficiency === 'low'),
    waste_terms: termPool.filter(t => t.efficiency === 'waste'),
    new_opportunities: [
      { term: 'camping coffee equipment compact', impr: 2400, clicks: 68, spend: 54.60, sales: 163.80, acos: 33.3, roas: 3.0, orders: 6, cpc: 0.80, match_type: 'exact', efficiency: 'high' },
      { term: 'gift for coffee lover dad', impr: 1800, clicks: 52, spend: 41.60, sales: 145.60, acos: 28.6, roas: 3.5, orders: 5, cpc: 0.80, match_type: 'phrase', efficiency: 'high' },
    ],
    suggestions: [
      `立即将 ${termPool.filter(t => t.efficiency === 'waste').length} 个浪费词（$${termPool.filter(t => t.efficiency === 'waste').reduce((s, t) => s + t.spend, 0).toFixed(2)}/月）添加为精确否定`,
      `对 ${termPool.filter(t => t.efficiency === 'low').length} 个低效词降低出价 20-30%，或改为 phrase/exact 匹配`,
      `对 ${termPool.filter(t => t.efficiency === 'high').length} 个高效词提高预算 15-25%，测试扩大曝光`,
      '每周一导出搜索词报告，新增否定词不少于 10 个',
    ],
  }
}

// 执行出价建议（Mock）
const executeBidSuggest = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))

  const keywords = [
    { keyword: 'coffee grinder manual', match_type: 'exact', current_bid: 0.85, suggested_bid: 1.08, bid_change_pct: 27, reason: '该词转化率高且 ACoS 优于平均，提高出价可获得更多优质流量', expected_impact: '预计+27% 点击量，ACoS ↓', priority: 'high' },
    { keyword: 'ceramic burr grinder', match_type: 'phrase', current_bid: 0.72, suggested_bid: 0.91, bid_change_pct: 26, reason: '近期该词转化有明显上升趋势，建议抢占更多曝光', expected_impact: '预计+26% 点击量，ACoS ~', priority: 'high' },
    { keyword: 'portable coffee grinder', match_type: 'exact', current_bid: 1.15, suggested_bid: 0.89, bid_change_pct: -23, reason: '该词长期 ACoS 偏高，降低出价以控制成本', expected_impact: '预计-23% 点击量，ACoS ↓', priority: 'high' },
    { keyword: 'hand crank coffee mill', match_type: 'phrase', current_bid: 0.65, suggested_bid: 0.49, bid_change_pct: -25, reason: '点击量大但转化不稳定，先降低出价观察', expected_impact: '预计-25% 点击量，ACoS ↓', priority: 'medium' },
    { keyword: 'best coffee grinder 2024', match_type: 'broad', current_bid: 1.35, suggested_bid: 1.02, bid_change_pct: -24, reason: 'Broad 匹配 CPC 偏高但 ROI 不理想，建议降至合理区间', expected_impact: '预计-24% 点击量，ACoS ↓', priority: 'low' },
  ]

  const budgetImpact = keywords.reduce((sum, k) => sum + k.suggested_bid - k.current_bid, 0)

  return {
    strategy_type: params.strategy || 'balanced',
    total_keywords: keywords.length,
    recommendations: keywords,
    budget_impact: Math.round(budgetImpact * 100) / 100,
    expected_acos_change: -(4 + Math.random() * 4),
    rationale: '基于近30天转化数据、竞争强度、季节性因素综合计算。平衡策略兼顾曝光与效率。',
  }
}

// 执行竞品广告分析（Mock）
const executeCompetitorAd = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 550))

  const yourSOV = 18.5

  return {
    competitors: [
      { competitor_name: 'BrewMaster Pro', asin: 'B08XXXXXX1', share_of_voice: 24.2, overlap_keywords: 38, avg_position: 2.1, estimated_spend: 520, top_keywords: ['coffee grinder', 'burr mill', 'manual grinder'], strengths: ['高品质陶瓷磨芯', '调节粗细度高'], weaknesses: ['价格偏高', '款式单一'] },
      { competitor_name: 'GrindElite', asin: 'B09XXXXXX2', share_of_voice: 19.8, overlap_keywords: 31, avg_position: 2.8, estimated_spend: 380, top_keywords: ['portable grinder', 'travel coffee'], strengths: ['性价比突出', '评价数量多'], weaknesses: ['质量参差', '退货率略高'] },
      { competitor_name: 'CoffeeCraft', asin: 'B07XXXXXX3', share_of_voice: 14.5, overlap_keywords: 22, avg_position: 3.4, estimated_spend: 260, top_keywords: ['ceramic grinder', 'aeropress'], strengths: ['设计精美', '包装用心'], weaknesses: ['价格虚高', '发货慢'] },
      { competitor_name: 'BaristaBasics', asin: 'B0AXXXXXX4', share_of_voice: 11.2, overlap_keywords: 18, avg_position: 3.9, estimated_spend: 190, top_keywords: ['kitchen gadget', 'coffee tool'], strengths: ['SKU丰富', '物流快'], weaknesses: ['缺乏创新', '同质化严重'] },
    ],
    your_share_of_voice: yourSOV,
    market_position: 'nicher',
    actionable_insights: [
      '**BrewMaster Pro** 是最大威胁（SOV 24.2%），重点关注其 38 个重叠关键词的广告策略',
      '**GrindElite** SOV 仅 19.8%，可尝试抢夺其展示份额',
      '建议增加品牌防御广告（SBV）预算，保护品牌词展示份额',
      '关注竞品的新品上架节奏，提前布局防御性广告',
    ],
  }
}

// 执行预算分配（Mock）
const executeBudgetAlloc = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 480))

  const allocations = [
    { campaign_name: '自动广告-广泛', current_budget: 300, suggested_budget: 285, allocation_pct: 21.2, reason: '流量入口，保持稳定', expected_roas: 3.2 },
    { campaign_name: '手动-精准-核心词', current_budget: 450, suggested_budget: 562, allocation_pct: 41.8, reason: '主力转化，建议加码', expected_roas: 5.1 },
    { campaign_name: '手动-短语-长尾词', current_budget: 250, suggested_budget: 238, allocation_pct: 17.7, reason: '低成本拓量', expected_roas: 3.8 },
    { campaign_name: '品牌-SB-品牌词', current_budget: 180, suggested_budget: 162, allocation_pct: 12.0, reason: '品牌防御，维持现状', expected_roas: 4.5 },
    { campaign_name: '展示-SD-竞品定向', current_budget: 220, suggested_budget: 264, allocation_pct: 19.6, reason: '抢量渠道，适度增加', expected_roas: 2.8 },
    { campaign_name: 'SD-再营销', current_budget: 120, suggested_budget: 216, allocation_pct: 16.1, reason: '高ROI，建议翻倍', expected_roas: 6.8 },
  ]

  const totalCurrent = allocations.reduce((s, a) => s + a.current_budget, 0)
  const totalSuggested = allocations.reduce((s, a) => s + a.suggested_budget, 0)

  return {
    total_current_budget: totalCurrent,
    total_suggested_budget: totalSuggested,
    allocations,
    projected_improvement: {
      expected_roas_increase: '+22.5%',
      expected_acos_decrease: '-5.2%',
      efficiency_gain: '+16.8%',
    },
    risk_assessment: '中等风险 — 建议分两周逐步调整，每周监测效果',
  }
}

// 执行异常检测（Mock）
const executeAnomalyDetect = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 450))

  return {
    check_period: params.check_period === '7d' ? '近7天 vs 前7天' : params.check_period === '14d' ? '近14天 vs 前14天' : '近30天 vs 前30天',
    anomalies: [
      { type: 'spend_spike', severity: 'high', campaign: '手动-精准-核心词', metric: '日花费', current_value: 280, expected_value: 150, deviation_pct: 86.7, detected_at: new Date(Date.now() - 86400000).toISOString().slice(0, 10), possible_cause: '某关键词出价被意外调高或竞争加剧导致 CPC 飙升', suggested_action: '立即检查出价设置，必要时暂停高价词' },
      { type: 'conversion_drop', severity: 'high', campaign: '自动广告-广泛', metric: '转化率', current_value: 3.2, expected_value: 8.5, deviation_pct: -62.4, detected_at: new Date(Date.now() - 172800000).toISOString().slice(0, 10), possible_cause: 'Listing 被差评拉低转化率，或出现恶意竞争点击', suggested_action: '检查 Listing 评价情况，排查无效点击' },
      { type: 'impression_anomaly', severity: 'medium', campaign: '品牌-SB-品牌词', metric: '展示量', current_value: 8500, expected_value: 25000, deviation_pct: -66.0, detected_at: new Date(Date.now() - 86400000).toISOString().slice(0, 10), possible_cause: '品牌词搜索量季节性下降或预算耗尽提前', suggested_action: '确认预算是否充足，考虑拓展非品牌词' },
      { type: 'ctr_drop', severity: 'medium', campaign: '展示-SD-竞品定向', metric: 'CTR', current_value: 0.12, expected_value: 0.35, deviation_pct: -65.7, detected_at: new Date(Date.now() - 43200000).toISOString().replace('T', ' ').slice(0, 16), possible_cause: '创意素材疲劳或竞品更新了更有吸引力的素材', suggested_action: '轮换 SD 广告创意，A/B 测试新素材' },
    ],
    summary: '⚠️ 发现 **2 个高风险异常**，需立即关注 📋 还有 **2 个** 中等风险项',
    alert_count: 2,
  }
}

// ========== 客服 Mock 执行函数 ==========

// 执行订单追踪（Mock）
const executeOrderTrack = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 400))

  const statuses = [
    { key: 'delivered', text: '已签收', icon: '✅' },
    { key: 'shipped', text: '已发货', icon: '🚚' },
    { key: 'processing', text: '处理中', icon: '⏳' },
  ]
  const status = statuses[Math.floor(Math.random() * statuses.length)]
  const products = ['Portable Coffee Grinder Pro', 'Wireless Bluetooth Earbuds', 'Smart Home Security Camera']
  const carriers = ['UPS', 'FedEx', 'USPS', 'Amazon Logistics']

  const orderInfo = {
    order_id: params.order_id || `ORD-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}${Math.floor(Math.random() * 100000).toString().padStart(8, '0')}`,
    status: status.key,
    status_text: status.text,
    created_at: new Date(Date.now() - Math.floor(Math.random() * 14) * 86400000).toLocaleString('zh-CN').replace(/\//g, '-'),
    product_name: products[Math.floor(Math.random() * products.length)],
    quantity: Math.floor(Math.random() * 3) + 1,
    total: parseFloat((Math.random() * 180 + 19.99).toFixed(2)),
  }

  if (status.key === 'shipped') {
    Object.assign(orderInfo, {
      tracking_number: `1Z${Math.floor(Math.random() * 9000000000 + 1000000000)}`,
      carrier: carriers[Math.floor(Math.random() * carriers.length)],
      estimated_delivery: new Date(Date.now() + Math.floor(Math.random() * 5 + 1) * 86400000).toISOString().slice(0, 10),
    })
  }

  return { order: orderInfo }
}

// 执行工单创建（Mock）
const executeTicketCreate = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 380))

  const ticketId = `TKT-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${Math.floor(Math.random() * 90000 + 10000)}`
  const slaMap: Record<string, string> = { urgent: '2h', high: '4h', medium: '24h', low: '48h' }

  return {
    success: true,
    ticket: {
      ticket_id: ticketId,
      subject: params.subject,
      description: params.description,
      category: params.category || 'general',
      priority: params.priority || 'medium',
      status: 'open',
      customer_id: '',
      order_id: params.order_id || undefined,
      created_at: new Date().toISOString(),
      sla_deadline: undefined,
      tags: [params.category || 'general', params.priority || 'medium'],
    },
    estimated_response_time: slaMap[params.priority] || '24h',
    auto_replies: [
      '您好！我们已收到您的售后申请，将在 24 小时内处理完毕。',
      '请您放心，我们会全力协助您解决问题。',
      ...(params.priority === 'urgent' || params.priority === 'high' ? ['由于问题较紧急，已升级为优先处理。'] : []),
    ],
    message: `工单 ${ticketId} 创建成功！`,
  }
}

// ========== 竞品监控员 Mock 执行函数 ==========

// 执行监控仪表盘 —— 改为读取统一监控池（MonitorPool），不再各自随机造数
const executeMonitorDashboard = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 300))

  const pool = useMonitorPoolStore()
  const records = pool.records.filter(r => {
    if (params.asin) return r.asin === params.asin
    return true
  })

  const stockMap: Record<string, string> = { in_stock: 'In Stock', low_stock: 'Low Stock', out_of_stock: 'Out of Stock' }
  const competitors = records.map(r => {
    const priceDrop = r.price_change_7d < -5
    const stockRisk = r.stock_status !== 'in_stock'
    const neg7 = r.review_events.slice(-7).filter(e => e.negative).length
    let health_score = 90
    if (priceDrop) health_score -= 15
    if (stockRisk) health_score -= 18
    if (neg7 > 0) health_score -= 12
    if (r.rating < 4) health_score -= 8
    return {
      asin: r.asin,
      brand: r.brand,
      title: r.title,
      price: r.latest_price,
      bsr_rank: r.latest_bsr,
      review_count: r.review_count,
      rating: r.rating,
      stock_status: stockMap[r.stock_status] || 'In Stock',
      health_score: Math.max(0, health_score),
      price_change: r.price_change_7d,
      alert_count: (priceDrop ? 1 : 0) + (stockRisk ? 1 : 0) + (neg7 > 0 ? 1 : 0),
    }
  })

  // 从池动态生成异动提醒
  const recent_alerts: any[] = []
  for (const r of records) {
    if (r.price_change_7d < -5)
      recent_alerts.push({ type: 'price_drop', severity: 'warning', message: `${r.brand} 价格骤降 ${Math.abs(r.price_change_7d)}%，可能发起价格战`, timestamp: new Date().toISOString().slice(0, 10) })
    if (r.stock_status === 'out_of_stock')
      recent_alerts.push({ type: 'stock_out', severity: 'critical', message: `${r.brand} 缺货，可能退出竞争或补货中`, timestamp: new Date().toISOString().slice(0, 10) })
    if (r.bsr_change_7d > 150)
      recent_alerts.push({ type: 'rank_jump', severity: 'info', message: `${r.brand} BSR 排名下降 ${r.bsr_change_7d} 位`, timestamp: new Date().toISOString().slice(0, 10) })
  }

  return {
    total_competitors: competitors.length,
    competitors,
    summary: {
      overview: `监控概览 — ${params.asin ? `聚焦 ${params.asin}` : `监控池 ${pool.totalCount} 个竞品`}，近 ${params.days || 30} 天内发现 ${competitors.filter(c => c.alert_count > 0).length} 个竞品存在异常警报。`,
      recent_alerts: recent_alerts.slice(0, 5),
    },
  }
}

// 执行价格追踪 —— 读取统一监控池的真实价格时序，不再随机造数
const executePriceTrack = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 300))

  const pool = useMonitorPoolStore()
  const asins = (params.asins || []).filter(Boolean)
  const records = asins.length
    ? pool.records.filter(r => asins.includes(r.asin))
    : pool.records

  const competitors = records.map(r => {
    const ph = r.price_history
    const p30 = ph[0]?.price ?? r.latest_price
    return {
      asin: r.asin,
      brand: r.brand,
      current_price: r.latest_price,
      price_30d_ago: +p30.toFixed(2),
      price_change_pct: r.price_change_7d,
      rank_change: r.bsr_change_7d,
      competitiveness_score: Math.max(10, Math.min(99, Math.round(100 - r.latest_bsr / 100 + r.rating * 5))),
    }
  })

  return {
    tracked_count: competitors.length,
    competitors,
    comparison_matrix: {
      ranking: competitors
        .map(c => ({ ...c, score: c.competitiveness_score }))
        .sort((a, b) => b.score - a.score)
        .map((c, i) => ({ asin: c.asin, brand: c.brand, score: c.score })),
    },
    insights: [
      `${competitors.filter(c => c.price_change_pct < -5).length} 个竞品近期降价超过 5%`,
      `数据源：统一竞品池（MonitorPool）近 30 天价格时序`,
      '建议关注排名变化最大的竞品策略调整',
    ],
  }
}

// 执行市场份额分析（Mock）
const executeMarketShare = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 600))

  const brands = [
    { competitor_asin: 'B08LEAD001', brand_name: 'MarketLeader', estimated_market_share: 28.5, bsr_rank: 120, revenue_estimate: 125000, trend: 'stable' },
    { competitor_asin: 'B08CHAL002', brand_name: 'ChallengerA', estimated_market_share: 18.2, bsr_rank: 350, revenue_estimate: 80000, trend: 'rising' },
    { competitor_asin: 'B09FOLLOW3', brand_name: 'ChallengerB', estimated_market_share: 14.8, bsr_rank: 520, revenue_estimate: 65000, trend: 'rising' },
    { competitor_asin: 'B07NICHE04', brand_name: 'NichePlayer', estimated_market_share: 9.5, bsr_rank: 1200, revenue_estimate: 42000, trend: 'stable' },
    { competitor_asin: 'B06OLDGU5', brand_name: 'LegacyBrand', estimated_market_share: 12.3, bsr_rank: 280, revenue_estimate: 54000, trend: 'declining' },
    { competitor_asin: 'B0ANEWCOM6', brand_name: 'NewEntrant', estimated_market_share: 6.2, bsr_rank: 2500, revenue_estimate: 27000, trend: 'rising' },
    { competitor_asin: 'B05OTHERS7', brand_name: 'Others', estimated_market_share: 10.5, bsr_rank: 8000, revenue_estimate: 46000, trend: 'stable' },
  ]

  return {
    category: params.category,
    total_market_estimate: 439000,
    competitors: brands,
    concentration_ratio: { cr4: 73.8, hhi: 1820 },
    insights: [
      `市场由 **${brands[0].brand_name}** 主导（份额 ${brands[0].estimated_market_share}%），但 CR4=${73.8}% 表明存在中等集中度`,
      '**ChallengerA** 和 **NewEntrant** 呈上升趋势，值得关注其增长策略',
      'LegacyBrand 份额持续下滑，可能存在市场机会',
      'HHI=1820 属于中度集中市场，新进入者仍有空间',
    ],
  }
}

// 执行定价策略分析（Mock）
const executePricingAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))

  return {
    analyzed_count: 4,
    strategies: [
      { strategy_type: 'premium', base_price: 69.99, avg_discount: 8, promo_frequency: 'low', price_elasticity: -0.8, price_volatility: 0.03, recommendations: ['定位高端市场，强调品质差异化', '促销频率低但折扣力度大时转化率高'] },
      { strategy_type: 'competitive', base_price: 34.99, avg_discount: 15, promo_frequency: 'medium', price_elasticity: -1.5, price_volatility: 0.08, recommendations: ['跟随市场领导者定价', '关注竞品调价动态快速响应'] },
      { strategy_type: 'economy', base_price: 19.99, avg_discount: 22, promo_frequency: 'high', price_elasticity: -2.2, price_volatility: 0.12, recommendations: ['低价走量策略，利润薄但销量大', '需控制成本以维持微利'] },
      { strategy_type: 'dynamic', base_price: 42.99, avg_discount: 18, promo_frequency: 'high', price_elasticity: -1.8, price_volatility: 0.15, recommendations: ['使用算法动态调价', '根据时段/库存/竞争灵活变动'] },
    ],
    market_positioning_map: {
      segments: [
        { name: '溢价区', count: 1, color: '#cf1322' },
        { name: '竞争区', count: 2, color: '#1890ff' },
        { name: '经济区', count: 1, color: '#52c41a' },
      ],
    },
  }
}

// 执行评论侦探（Mock）
const executeReviewSpy = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 650))

  return {
    analyzed_products: 1,
    analyses: [{
      asin: params.asin || 'B08TARGET01',
      brand: 'TargetCompetitor',
      product: 'Premium Coffee Grinder Pro',
      overall_rating: 4.2,
      total_reviews: 2840,
      insights: [
        { aspect: '研磨质量', topic: '研磨均匀度好，粗细可调', sentiment_score: 0.82, mention_count: 420, example_quotes: ['研磨非常均匀', '粗细调节很方便'] },
        { aspect: '噪音', topic: '噪音偏大，早起使用有顾虑', sentiment_score: 0.35, mention_count: 180, example_quotes: ['声音有点大', '像电钻一样响'] },
        { aspect: '清洁难度', topic: '清理麻烦，粉容易飞溅', sentiment_score: 0.28, mention_count: 150, example_quotes: ['每次用完都要认真清', '粉到处都是'] },
        { aspect: '耐用性', topic: '使用半年后电机异响', sentiment_score: 0.40, mention_count: 95, example_quotes: ['用了几个月开始有杂音', '感觉不太耐用'] },
        { aspect: '容量', topic: '容量适中，够日常使用', sentiment_score: 0.75, mention_count: 310, example_quotes: ['容量刚好', '一次能磨够一家人用的'] },
        { aspect: '外观设计', topic: '颜值高，摆着好看', sentiment_score: 0.88, mention_count: 260, example_quotes: ['放在厨房很好看', '设计感很强'] },
      ],
      swot: {
        strengths: ['研磨质量获得广泛认可', '颜值和设计受好评', '容量满足大多数用户需求'],
        weaknesses: ['噪音问题突出（-1星主因）', '清洁不便导致差评', '长期耐用性存疑'],
        opportunities: ['推出静音升级版可抢占市场', '开发易清洁配件包', '强化质保承诺消除顾虑'],
        threats: ['已有竞品主打静音卖点', '用户对耐用性要求提升', '差评积累影响转化率'],
      },
      actionable_intelligence: [
        '🎯 最大痛点是**噪音**（提及率 6.3%），可开发"静音版"作为差异化卖点',
        '🎯 **清洁问题**排第二（提及率 5.3%），附赠清洁刷/防飞溅罩可作为赠品营销点',
        '⚠️ 耐用性负面评价在 6 个月后集中爆发，建议加强质保宣传',
        '💡 外观设计是强项（正面提及率 9.2%），可在Listing图片和视频中重点展示',
      ],
    }],
  }
}

// 执行入侵者检测（Mock）
const executeIntruderAlert = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 500))

  return {
    category: params.category,
    detection_date: new Date().toISOString().slice(0, 10),
    new_competitors: [
      { asin: 'B0NEW001', title: 'Ultra Quiet Ceramic Coffee Grinder', brand: 'SilentGrind', entry_date: new Date(Date.now() - 14 * 86400000).toISOString().slice(0, 10), price: 27.99, threat_level: 'high', reasons: ['价格低于我方主力产品 30%', '主打静音卖点直接针对最大痛点', '14天内已获 68 条评论且评分 4.5'], our_product_affected: true },
      { asin: 'B0NEW002', title: 'Smart WiFi Coffee Grinder App Control', brand: 'TechBrew', entry_date: new Date(Date.now() - 21 * 86400000).toISOString().slice(0, 10), price: 54.99, threat_level: 'medium', reasons: ['智能功能差异化明显', '定价处于中高端区间', '品牌知名度较低暂未形成威胁'], our_product_affected: false },
      { asin: 'B0NEW003', title: 'Budget Manual Coffee Mill Compact', brand: 'ValueGrind', entry_date: new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10), price: 12.99, threat_level: 'low', reasons: ['纯手动低端产品', '目标客群与我方不重叠', '评论数少影响力有限'], our_product_affected: false },
    ],
    threat_summary: { high: 1, medium: 1, low: 1 },
    response_strategies: [
      { target: 'SilentGrind (B0NEW001)', strategy: '防御性应对', actions: ['立即采购样品进行全方位分析', '监控其广告投放关键词是否重叠', '准备静音版产品线规划'], priority: 'P0' },
      { target: 'TechBrew (B0NEW002)', strategy: '观察跟踪', actions: ['每周追踪其排名和评论变化', '评估智能化功能的用户接受度', '储备技术方案以备跟进'], priority: 'P1' },
      { target: 'ValueGrind (B0NEW003)', strategy: '无需行动', actions: ['持续监控即可', '目标客群不同不构成直接威胁'], priority: 'P2' },
    ],
  }
}

// 执行 Buy Box 分析（Mock）
const executeBuyBoxAnalysis = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 480))

  return {
    analyzed_count: 1,
    analyses: [{
      asin: params.asin || 'B08SAMPLE01',
      brand: 'SampleBrand',
      product: 'Coffee Grinder Sample Product',
      buy_box_analysis: {
        sellers: [
          { seller_name: 'SampleBrand (FBA)', price: 34.99, shipping: 0, in_stock: true, is_winner: true },
          { seller_name: 'OtherSeller A', price: 36.50, shipping: 4.99, in_stock: true, is_winner: false },
          { seller_name: 'OtherSeller B', price: 33.99, shipping: 5.99, in_stock: true, is_winner: false },
          { seller_name: 'Reseller C', price: 38.00, shipping: 0, in_stock: false, is_winner: false },
        ],
        factors: {
          price_competitiveness: { score: 82, status: 'good' },
          shipping_speed: { score: 95, status: 'excellent' },
          seller_rating: { score: 88, status: 'good' },
          fulfillment_method: { score: 100, status: 'excellent' },
          availability: { score: 90, status: 'good' },
          feedback_quality: { score: 75, status: 'fair' },
        },
      },
      competitiveness_score: 87,
    }],
    best_practices: [
      '保持 FBA 履约方式，这是赢取 Buy Box 的最重要因素之一',
      '当前价格竞争力良好，但 OtherSeller B 价格更低，需警惕',
      '卖家反馈质量（75分）有提升空间，建议优化售后响应速度',
      '确保库存充足避免缺货失去 Buy Box',
      '考虑注册 Amazon Vine 计划提升评论数量和质量',
    ],
  }
}

// 执行多维对比（Mock）
const executeCompareGrid = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  const asins = params.asins || ['B08AAAA01', 'B08BBBB02', 'B08CCCC03']
  const dimensions = params.dimensions || ['价格', '评分', '评论数', 'BSR排名']

  return {
    type: 'compare_grid',
    params,
    compared_count: asins.length,
    comparison: {
      products: asins.map((asin: string, i: number) => ({
        asin,
        brand: [`Brand${String.fromCharCode(65 + i)}`, 'CompetitorA', 'TargetBrand', 'MarketLeader'][i] || `Brand${i}`,
        name: [`Product Alpha`, `Product Beta`, `Product Gamma`][i] || `Product ${i + 1}`,
        price: 19.99 + Math.random() * 40,
        rating: (3.8 + Math.random() * 1.2).toFixed(1),
        review_count: Math.floor(100 + Math.random() * 5000),
        bsr_rank: Math.floor(100 + Math.random() * 10000),
        size: `${(8 + Math.random() * 20).toFixed(1)}" x ${(6 + Math.random() * 12).toFixed(1)}" x ${(3 + Math.random() * 8).toFixed(1)}"`,
        weight: `${(0.5 + Math.random() * 3).toFixed(2)} lbs`,
        features: ['Feature A', 'Feature B', 'Feature C'].slice(0, 2 + Math.floor(Math.random() * 2)),
      })),
      differentiation: {
        price_spread: parseFloat((Math.max(...asins.map(() => 19.99 + Math.random() * 40)) - Math.min(...asins.map(() => 19.99 + Math.random() * 40))).toFixed(2)),
        rating_spread: parseFloat((1.4).toFixed(1)),
      },
      value_ranking: asins.map((asin: string, i: number) => ({
        asin,
        brand: `Brand${String.fromCharCode(65 + i)}`,
        value_score: Math.floor(60 + Math.random() * 35),
        reasoning: [
          '性价比突出，价格低于均价 15%',
          '综合表现均衡无明显短板',
          '高端定位品质优秀但溢价较高',
        ][i] || '表现中规中矩',
      })).sort((a: any, b: any) => b.value_score - a.value_score),
    },
    insights: [
      `价格区间 $${Math.min(...asins.map(() => 19.99 + Math.random() * 40)).toFixed(2)} - $${Math.max(...asins.map(() => 19.99 + Math.random() * 40)).toFixed(2)}`,
      '建议从价格、质量、功能三个维度综合评估',
      '最高性价比产品不一定是最低价产品',
    ],
  }
}

// ========== Listing 优化师 Mock 执行函数 ==========

// 执行关键词挖掘（Mock）
const executeKeywordMiner = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  const seedKeywords = params.seed_keywords || ['coffee grinder', 'portable grinder']
  const mockKeywords = [
    { keyword: 'manual coffee grinder ceramic burr', search_volume: 12500, competition: 'medium', suggested_bid: 0.92, relevance: 98, source: 'seed_expand' },
    { keyword: 'portable coffee bean grinder travel', search_volume: 8900, competition: 'low', suggested_bid: 0.75, relevance: 95, source: 'seed_expand' },
    { keyword: 'hand coffee grinder stainless steel', search_volume: 6700, competition: 'low', suggested_bid: 0.68, relevance: 92, source: 'competitor' },
    { keyword: 'electric coffee grinder small', search_volume: 15800, competition: 'high', suggested_bid: 1.25, relevance: 88, source: 'category' },
    { keyword: 'aeropress compatible coffee grinder', search_volume: 3200, competition: 'low', suggested_bid: 0.52, relevance: 85, source: 'long_tail' },
    { keyword: 'cold brew coffee grinder coarse', search_volume: 4500, competition: 'medium', suggested_bid: 0.78, relevance: 82, source: 'long_tail' },
    { keyword: 'best coffee grinder under 30 dollars', search_volume: 9200, competition: 'medium', suggested_bid: 0.88, relevance: 90, source: 'question' },
    { keyword: 'quiet coffee grinder for office', search_volume: 2800, competition: 'low', suggested_bid: 0.45, relevance: 80, source: 'long_tail' },
    { keyword: 'hario mini mill slim plus alternative', search_volume: 1900, competition: 'low', suggested_bid: 0.38, relevance: 75, source: 'competitor' },
    { keyword: 'camping coffee equipment manual', search_volume: 5100, competition: 'low', suggested_bid: 0.58, relevance: 78, source: 'category' },
    { keyword: 'gift for coffee lover dad birthday', search_volume: 3400, competition: 'low', suggested_bid: 0.55, relevance: 72, source: 'question' },
    { keyword: 'coffee mill hand crank adjustable', search_volume: 4100, competition: 'medium', suggested_bid: 0.72, relevance: 86, source: 'seed_expand' },
  ]

  return {
    type: 'keyword_miner',
    params,
    seed_keywords: seedKeywords,
    total_found: mockKeywords.length,
    // 透传来源产品，供结果卡「应用到当前产品」定位
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    keywords: mockKeywords.sort((a, b) => b.relevance - a.relevance),
    summary: `## 关键词挖掘报告\n\n基于 **${seedKeywords.join('、')}** 种子词，共挖掘 **${mockKeywords.length}** 个候选关键词。\n\n### 分布\n- 🔍 高搜索量 (>10K)：${mockKeywords.filter(k => k.search_volume > 10000).length} 个\n- 🎯 低竞争高相关：${mockKeywords.filter(k => k.competition === 'low' && k.relevance >= 85).length} 个\n- 📈 推荐立即投放：${mockKeywords.filter(k => k.relevance >= 90 && k.competition !== 'high').length} 个`,
  }
}

// 执行标题生成（Mock）
const executeTitleGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 800))

  const productName = params.product_name || 'Portable Coffee Grinder'
  // 根据店铺平台切换返回结构
  const isSimplified = params.is_simplified === true
  const platformMode = params.platform_mode || 'amazon'

  // ===== Temu / Shopee 简化模式：短标题 + 商品详情（无五点/Search Term/A+） =====
  if (isSimplified) {
    const platformLabel = platformMode === 'temu' ? 'Temu' : 'Shopee'
    const shortTitleList = [
      { title: `${productName} 静音USB 卧室便携`, score: 94, char_count: 28, seo_score: 92, notes: '短标题，核心词前置' },
      { title: `${productName} 大容量 低噪 办公室桌面`, score: 91, char_count: 26, seo_score: 90, notes: '突出场景词' },
      { title: `${productName} 两档雾量 自动断电`, score: 88, char_count: 22, seo_score: 87, notes: '突出差异化功能' },
      { title: `${productName} 迷你便携 七彩夜灯`, score: 85, char_count: 20, seo_score: 85, notes: '突出情感/颜值卖点' },
      { title: `${productName} 送礼佳选 母婴可用`, score: 82, char_count: 18, seo_score: 83, notes: '突出人群标签' },
    ]
    return {
      type: 'title_gen',
      params,
      platform_mode: platformMode,
      is_simplified: true,
      // 来源标记：产品库模式 → 走「应用到当前产品 Listing」；手动模式 → 走「保存为草稿」
      _source: params.source === 'product_library' ? 'product' : 'manual',
      product_id: params.product_id,
      product_name: productName,
      short_titles: shortTitleList,
      // 兼容 TitleGenerator.vue 的字段
      recommended_title: shortTitleList[0].title,
      char_count: shortTitleList[0].char_count,
      word_count: shortTitleList[0].title.length,
      variants: shortTitleList.slice(1).map((t: any) => ({ title: t.title, seo_score: t.seo_score })),
      detail_desc: {
        title: `${productName} 商品详情`,
        sections: [
          { heading: '产品亮点', content: `这款${productName}采用 500ml 大容量水箱，整夜加湿无需频繁加水；双雾量模式（持续/间歇）满足不同场景需求，USB 供电搭配静音运行，办公、卧室两相宜。` },
          { heading: '核心卖点', content: '① 顶置注水口，无需拆机加水；② 智能自动断电保护，水位低自动停机；③ 内置七彩夜灯，营造温馨氛围；④ 8 小时定时，安心入睡。' },
          { heading: '适用场景', content: '卧室 / 办公室 / 母婴房 / 宿舍，干燥季节的保湿利器，缓解皮肤干燥、嘴唇起皮。' },
          { heading: '规格参数', content: '容量：500ml · 雾量：双档可调 · 噪音：≤25dB · 供电：5V USB · 尺寸：小巧便携 · 材质：食品级安全材质' },
        ],
      },
      tips: [
        `${platformLabel} 短标题建议 20-40 字符，核心卖点前置`,
        '商品详情用「短段落 + 符号列表」结构，移动端易读',
        '关键词自然植入标题与详情首段，避免堆砌',
        '突出价格优势与使用场景，引导冲动下单',
      ],
    }
  }

  // ===== 亚马逊完整模式：标题 + 五点 + Search Term + A+ =====
  const titleList = [
    { title: `${productName} with Ceramic Burrs, Manual Hand Coffee Bean Grinder Adjustable Coarseness, Portable Compact for Travel Camping Office Home Kitchen`, score: 94, char_count: 148, features: ['Ceramic Burrs', 'Adjustable', 'Portable'], seo_score: 91 },
    { title: `Premium ${productName}, Stainless Steel Manual Coffee Grinder with Conical Burr Mill, Quiet Operation & Easy Clean, Perfect for Aeropress Pour Over French Press`, score: 89, char_count: 152, features: ['Stainless Steel', 'Quiet', 'Easy Clean'], seo_score: 88 },
    { title: `${productName} Professional, Hand Crank Coffee Mill with Precision Engineering, No Battery Needed, Eco-Friendly & Durable Design`, score: 86, char_count: 138, features: ['Professional', 'No Battery', 'Eco-Friendly'], seo_score: 84 },
    { title: `Manual ${productName} Portable Mini, Ceramic Burr Coffee Bean Grinder Fine to Coarse Setting, Travel-Friendly Hand Coffee Mill Small Size`, score: 83, char_count: 140, features: ['Portable Mini', 'Fine to Coarse', 'Travel'], seo_score: 82 },
    { title: `${productName} with Brush & Storage Bag, Ergonomic Hand Coffee Grinder Anti-Slip Base, Dishwasher Safe Parts, Gift Box Included`, score: 80, char_count: 136, features: ['With Accessories', 'Ergonomic', 'Gift Ready'], seo_score: 79 },
  ]
  return {
    type: 'title_gen',
    params,
    platform_mode: platformMode,
    is_simplified: false,
    // 来源标记：产品库模式 → 走「应用到当前产品 Listing」；手动模式 → 走「保存为草稿」
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    product_name: productName,
    titles: titleList,
    // 兼容 TitleGenerator.vue 的字段
    recommended_title: titleList[0].title,
    char_count: titleList[0].char_count,
    word_count: titleList[0].title.split(' ').length,
    variants: titleList.slice(1).map((t: any) => ({ title: t.title, seo_score: t.seo_score })),
    core_keywords: [
      { word: 'Portable Coffee Grinder', search_volume: 45000, competition: 'high', placed_in_title: true },
      { word: 'Manual Coffee Grinder', search_volume: 32000, competition: 'medium', placed_in_title: true },
      { word: 'Ceramic Burr', search_volume: 18000, competition: 'low', placed_in_title: true },
      { word: 'Adjustable Coarseness', search_volume: 12000, competition: 'low', placed_in_title: true },
      { word: 'Travel', search_volume: 28000, competition: 'high', placed_in_title: true },
    ],
    tips: [
      '标题前 80 字符最重要，核心关键词前置',
      '避免全大写或特殊符号（!@#$）',
      '数字用阿拉伯数字（如 "5 Settings" 而非 "Five"）',
      '品牌名 + 核心卖点 + 材质 + 适用场景 + 兼容性',
    ],
  }
}

// 执行五点描述生成（Mock）
const executeBulletGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 750))

  const productName = params.product_name || 'Coffee Grinder'
  return {
    type: 'bullet_gen',
    params,
    product_name: productName,
    // 透传来源产品，供结果卡「应用到当前产品 Listing」定位（对齐 title-gen）
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    bullets: [
      { point: `【PREMIUM CERAMIC BURRS】${productName} features high-density ceramic conical burrs that deliver consistent grind size every time. Unlike metal burrs that overheat and alter flavor, our ceramic burrs stay cool, preserving your coffee's essential oils and aroma for a richer, more authentic taste.`, emoji: '💎', char_count: 248 },
      { point: `【ADJUSTABLE COARSENESS SETTINGS】Customize your grind from ultra-fine for espresso to coarse for French press with 15+ precision settings. The intuitive dial mechanism lets you find the perfect texture for ANY brewing method — AeroPress, pour-over, drip, cold brew, or Turkish coffee.`, emoji: '⚙️', char_count: 256 },
      { point: `【PORTABLE & TRAVEL-FRIENDLY】Compact size (5.2 x 3.1 inches) fits perfectly in your backpack or suitcase. No batteries, no cords — just pure manual grinding anywhere you go. Ideal for camping, hiking, office use, or small kitchens where space is at a premium.`, emoji: '🧳', char_count: 238 },
      { point: `【BUILT TO LAST】Crafted from food-grade 304 stainless steel with a reinforced ergonomic handle. The transparent powder chamber holds up to 40g of beans (4 cups), and the anti-slip silicone base keeps it stable during use. Backed by our 5-year warranty.`, emoji: '🔩', char_count: 245 },
      { point: `【COMPLETE PACKAGE】Includes a cleaning brush, storage pouch, and user manual. Our 24/7 customer support team is ready to help. Makes an excellent gift for coffee lovers — presented in premium gift-ready packaging.`, emoji: '🎁', char_count: 218 },
    ],
    optimization_suggestions: [
      '每条 Bullet 以【大写关键词】开头，移动端首屏可见',
      '全大写括号内的卖点词，吸引快速浏览的买家',
      '融入场景词（camping/office/AeroPress）提升搜索覆盖',
      '数字具体化（15+ settings / 40g / 4 cups）增加可信度',
    ],
  }
}

// 执行描述生成（Mock）
const executeDescGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 800))

  const productName = params.product_name || 'Premium Coffee Grinder'
  return {
    type: 'desc_gen',
    params,
    product_name: productName,
    _source: params.source === 'product_library' ? 'product' : 'manual',
    product_id: params.product_id,
    description: {
      title: `Discover the Art of Perfect Coffee with ${productName}`,
      sections: [
        { heading: 'Why Choose Our Manual Coffee Grinder?', content: 'In a world of electric everything, there\'s something deeply satisfying about grinding your own beans by hand. Our ceramic burr grinder puts YOU in control — from powder-fine espresso grounds to chunky cold brew bits. The result? Coffee that tastes noticeably fresher, more aromatic, and more YOU.' },
        { heading: 'Ceramic vs Steel: The Clear Winner', content: 'While steel burrs generate heat during grinding (literally cooking your beans and killing flavor), our advanced ceramic burrs remain naturally cool. This means every cup preserves the delicate volatile compounds that give coffee its complex taste profile. Professional baristas know this secret — now you do too.' },
        { heading: 'Engineered for Every Brewing Method', content: 'Whether you\'re an AeroPress enthusiast, a pour-over purist, or a French press fanatic, our 15+ coarseness settings have you covered. The smooth adjustment dial clicks into place with satisfying precision, so you can recreate your perfect grind every single time.' },
        { heading: 'Built for Adventure', content: 'At just 6 ounces and compact enough to slip into any bag, this grinder is your ultimate travel companion. Campsite mornings, office desk breaks, hotel rooms — enjoy freshly ground coffee anywhere. No cords, no batteries, no problem.' },
        { heading: 'Specifications', content: '- Material: Food-grade 304 Stainless Steel + High-Density Ceramic\n- Dimensions: 5.2" x 3.1" x 3.1"\n- Capacity: ~40g coffee beans (4 cups)\n- Weight: 6 oz (170g)\n- Warranty: 5-Year Full Coverage\n- Package Includes: Grinder, Cleaning Brush, Storage Pouch, User Manual' },
      ],
    },
    aplus_tips: [
      'A+ Content 使用品牌故事+场景化图片组合',
      '标准模块：产品对比表 → 使用场景图 → 规格参数 → 品牌故事',
      '图片建议：7张横幅(1460x600) + 7张方图(600x600)',
    ],
  }
}

// 执行 SEO 诊断（Mock）
const executeSEOAudit = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 650))

  const asin = params.asin || 'B08SAMPLE01'
  const platformMode = params.platform_mode || 'amazon'
  const isSimplified = params.is_simplified === true

  // ===== Temu / Shopee：简化 SEO 校验规则 =====
  if (isSimplified) {
    const platformLabel = platformMode === 'temu' ? 'Temu' : 'Shopee'
    return {
      type: 'seo_audit',
      params,
      asin,
      platform_mode: platformMode,
      is_simplified: true,
      overall_score: 76,
      grade: 'B',
      categories: [
        { category: '短标题', score: 82, status: 'good', issues: ['标题长度 28 字符，符合 20-40 区间', '核心词已前置，但可再精简修饰词'], suggestions: ['保持核心词前置', '控制在 40 字符内，突出价格/卖点'] },
        { category: '商品详情', score: 70, status: 'warning', issues: ['详情段落偏长，移动端需下滑 3 屏', '缺少规格参数表'], suggestions: ['用符号列表+短段落结构', '补充规格参数、售后说明'] },
        { category: '关键词覆盖', score: 68, status: 'warning', issues: ['站内搜索词仅覆盖 6/12 目标词', '缺少长尾场景词'], suggestions: ['在标题+详情首段自然植入高频词', '补充场景词（卧室/办公室/送礼）'] },
        { category: '主图质量', score: 74, status: 'warning', issues: ['主图背景不够纯净', '缺少多角度展示图'], suggestions: ['重拍白底主图', '补充细节图+场景图'] },
        { category: '价格竞争力', score: 80, status: 'good', issues: [`价格处于${platformLabel}类目中位水平`, '缺少促销标签'], suggestions: ['可设置限时折扣标签', '突出性价比话术'] },
      ],
      top_recommendations: [
        '🔥 P0：短标题核心词前置，控制在 30 字符内',
        '📌 P1：商品详情改为「符号列表 + 规格参数表」结构',
        '📌 P1：主图重拍白底，补充细节/场景图',
        '💡 P2：补充长尾场景词，提升站内搜索曝光',
      ],
    }
  }

  // ===== 亚马逊：完整 SEO 校验规则 =====
  return {
    type: 'seo_audit',
    params,
    asin,
    platform_mode: platformMode,
    is_simplified: false,
    overall_score: 72,
    grade: 'B',
    categories: [
      { category: '标题优化', score: 78, status: 'good', issues: ['标题长度 185 字符，略超推荐 150-200 区间上限', '品牌名位置偏后，建议移至最前面'], suggestions: ['将品牌名移至标题开头', '精简修饰词，控制在 200 字符以内'] },
      { category: '五点描述', score: 85, status: 'good', issues: ['第3条 Bullet 未以大写关键词开头', '缺少数字量化卖点'], suggestions: ['每条以【KEYWORD】格式开头', '加入具体数据（尺寸/容量/时长等）'] },
      { category: '搜索词覆盖率', score: 65, status: 'warning', issues: ['核心搜索词 "portable coffee grinder" 未出现在标题前 50 字符', '长尾词覆盖不足，仅命中 12/25 目标词'], suggestions: ['在标题/五点/A+ 中自然植入 Top 20 搜索词', '利用后台搜索词报告补充遗漏的高频词'] },
      { category: '图片质量', score: 70, status: 'warning', issues: ['主图背景不够纯净，存在轻微阴影', '缺少信息图表(infographic)风格的辅助图', '生活场景图仅 3 张，建议增加到 5 张'], suggestions: ['重新拍摄白底主图，确保纯白背景(#FFF)', '增加尺寸对比图、使用场景拼图'] },
      { category: 'A+ 页面', score: 55, status: 'poor', issues: ['未开通 A+ Content（品牌注册 prerequisite）', '缺少增强版产品描述模块'], suggestions: ['尽快完成 Brand Registry 注册', 'A+ 可提升转化率 5-10%'] },
      { category: '评价管理', score: 80, status: 'good', issues: ['近 30 天收到 2 条差评未回复', 'Vine 计划未启用'], suggestions: ['及时回复差评并展示解决方案', '申请 Amazon Vine 获取早期评论'] },
    ],
    top_recommendations: [
      '🔥 P0：将核心搜索词 "portable coffee grinder" 移至标题前 50 字符内',
      '🔥 P0：申请 Brand Registry 开通 A+ Content',
      '📌 P1：重拍白底主图，消除阴影和反光',
      '📌 P1：每条 Bullet 加入至少 1 个数字化卖点',
      '💡 P2：启用 Vine 计划获取 30 条早期评论',
    ],
  }
}

// 执行 A/B 测试（Mock）
const executeABTest = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  return {
    type: 'ab_test',
    params,
    test_id: `AB-${Date.now().toString(36).toUpperCase()}`,
    variants: [
      {
        name: 'Control (当前)',
        id: 'A',
        title: 'Portable Coffee Grinder Manual with Ceramic Burrs, Hand Coffee Bean Grinder Adjustable Coarseness',
        main_image: '/mock/control.jpg',
        projected_ctr: 2.8,
        projected_conversion: 9.5,
      },
      {
        name: 'Variant B (新标题)',
        id: 'B',
        title: 'Premium Manual Coffee Grinder - Ceramic Conical Burr, 15 Settings, Portable for Travel & Camping',
        main_image: '/mock/variant_b.jpg',
        projected_ctr: 3.4,
        projected_conversion: 11.2,
        changes: ['标题更简洁，去除冗余词汇', '突出 "Premium" 和 "15 Settings"', '加入 "Camping" 场景词'],
      },
      {
        name: 'Variant C (新主图)',
        id: 'C',
        title: 'Portable Coffee Grinder Manual with Ceramic Burrs, Hand Coffee Bean Grinder Adjustable Coarseness',
        main_image: '/mock/variant_c.jpg',
        projected_ctr: 3.8,
        projected_conversion: 10.8,
        changes: ['保持原标题不变', '更换为手持展示图（人手握持）', '增加尺寸参照物'],
      },
    ],
    test_config: {
      duration_days: 14,
      traffic_split: { A: 40, B: 30, C: 30 },
      confidence_target: 95,
      minimum_sample_size: 500,
      estimated_completion: new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10),
    },
    hypothesis: '假设：更简洁的标题 + 场景化主图可提升 CTR 20%+',
  }
}

// ===== 选品分析师补充 =====

// 执行选品避坑（Mock）— 5大类风险评估
const executePitfalls = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1200))

  const product = params.product || {}
  const productName = product.title || product.keyword || '目标产品'
  const platform = params.platform_label || '亚马逊'
  const isAmazon = params.is_amazon !== false

  // ====== 5 大类风险数据（四段式：等级 + 说明 + 原因 + 规避方案）======
  const risks = [
    // ----- 1. 知识产权侵权风险 -----
    {
      category: 'ip_infringement',
      category_name: '知识产权侵权风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '存在外观专利冲突风险',
      description: '检测到该类目（手动研磨器/厨房工具）存在 2 个活跃外观专利，产品外形与专利 D897,123 高度相似度 >70%，存在被诉侵权风险。',
      reason: 'USPTO 数据显示同类手持研磨器已有 3+ 项授权外观专利覆盖；头部品牌 Cuisinart / Breville 有主动维权记录，年均投诉 15+ 起。',
      solution: '① 聘请 IP 律师做 FTO（Freedom to Operate）分析报告（$800-1500）；② 外形差异化改款：改变握柄弧度/旋钮位置/材质拼接方式；③ 避开专利保护范围重新设计 ID。',
    },
    {
      category: 'ip_infringement',
      category_name: '知识产权侵权风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '关键词可能触发品牌词拦截',
      description: '核心关键词 "portable coffee grinder" 中包含部分品牌通用化词汇，若在标题中使用可能触发品牌方自动化投诉。',
      reason: 'Amazon Brand Registry 允许品牌方对注册商标词设置自动监控；"coffee grinder" 本身非商标但组合使用时易被误判。',
      solution: '标题中避免直接使用品牌名变体；使用同义词替换（如 hand mill / manual bean grinder）；保留使用证据截图以备申诉。',
    },

    // ----- 2. 平台合规与认证风险 -----
    ...isAmazon ? [{
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '缺少 FCC 认证（如含电动部件）',
      description: '若产品含任何电动/电子元件（即使仅是 LED 指示灯），美国站强制要求 FCC Part 15 认证，否则面临下架 + 销毁风险。',
      reason: 'FCC 对含 >9kHz 振荡电路的设备一律要求认证；亚马逊美国站对电子产品实行「零容忍」政策，无证商品直接下架并冻结资金。',
      solution: '① 确认是否含电子元件 → 如有必须做 FCC SDoC（$2000-5000，周期 2-4 周）；② 纯机械产品可提交免责声明；③ 提前准备测试报告备查。',
    }] : [{
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: `${platform} 平台禁售品类审核`,
      description: `${platform} 对食品接触类材料有特殊资质要求，陶瓷/不锈钢制品需提供食品级检测报告方可上架。`,
      reason: `${platform} 平台对 Kitchen 类目实行类目审核制；新卖家首次上架需提交材质证明；无证商品审核不通过且影响店铺评分。`,
      solution: `① 提前准备 FDA/LFGB 食品接触材料检测报告（$300-800）；② 在 ${platform} Seller Center 提前申请类目白名单；③ 准备产品实拍图+说明书供审核。`,
    }],
    {
      category: 'compliance',
      category_name: '平台合规与认证风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '不属于危险品/禁售品类',
      description: '产品为纯机械/手动操作，不含电池/液体/粉末/磁性物质，不属于平台禁售或需特殊物流申报的品类。',
      reason: 'IATA 危险品清单中手工研磨器不在受限列表；无需 MSDS/UN 编号；常规 FBA 入仓即可。',
      solution: '保持现有包装合规即可；建议在运输标签上标注 "Non-hazardous, Manual Device" 加速入库。',
    },

    // ----- 3. 供应链 & 物流损耗风险 -----
    {
      category: 'supply_chain',
      category_name: '供应链 & 物流损耗风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '陶瓷部件易碎 — 退货破损率预警',
      description: '陶瓷磨芯属于易碎材质，FBA 配送过程破损率预估 6-12%，远高于类目均值 3%。高破损率将导致差评激增和退货成本飙升。',
      reason: '陶瓷莫氏硬度虽高但脆性大；FBA 多次分拣抛掷易产生微裂纹；买家退货二次上架后破损概率翻倍；竞品差评中 "arrived broken" 占比达 18%。',
      solution: '① 包装升级：EVA 内衬 + 独立泡沫卡槽（增加 $0.8-1.2/件 成本）；② 考虑替换为不锈钢/钛合金磨芯（供应链询价对比）；③ 设置破损赔付预算（售价的 3-5%）。',
    },
    {
      category: 'supply_chain',
      category_name: '供应链 & 物流损耗风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '尺寸重量适合 FBA 小件标准',
      description: '预估尺寸 15x10x8cm / 重量 <0.5kg，属于 FBA 小件标准费率区间，头程运费和仓储费用可控。',
      reason: '小件标准 FBA 费率约 $2.41-3.22/件（取决于尺寸档位）；海运头程约 $1.2-1.8/kg；无超大件附加费。',
      solution: '优化包装体积争取落入 Small Standard 尺寸档（≤18x14x8cm 可降费率 $0.5/件）；批量发货降低头程单价。',
    },

    // ----- 4. 市场商业盈利风险 -----
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'high' as const,
      level_label: '🔴 高危',
      title: '头部寡头垄断 — 前 3 名占 72% 份额',
      description: '类目 Top3 链接（Cuisinart / Breville / OXO）合计占据 BSR 前 10 中的 7 席，新品自然排名突破 Top100 需 150+ 评论门槛。',
      reason: '头部链接评论数均 >5000 且持续投放 SB/SD 广告；类目月均新品存活率仅 23%；价格带 $20-40 区间竞争最激烈（红海区）。',
      solution: '① 避开红海价格带 → 定位 $45-65 细分高端市场（手动精品路线）；② 差异化卖点：可调节粗细度 + 陶瓷防氧化（竞品多为不锈钢）；③ 预算 $3000-5000 用于 Vine + SBV 冷启动。',
    },
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '竞品差评高频缺陷：陶瓷掉粉/调节松动',
      description: '分析 Top10 竞品共 2847 条差评，高频原生缺陷 TOP3：① 陶瓷磨芯掉粉污染咖啡（34%）② 粗细度调节钮松动回弹（28%）③ 收纳盖难清洗（19%）。',
      reason: '这些是结构性设计问题而非个别品控问题；说明全行业都未解决此痛点 = **差异化机会点**。',
      solution: '① 产品设计阶段加入「不掉粉」陶瓷烧结工艺要求；② 调节机构改用金属卡扣式替代螺纹式；③ 将以上三点作为 Listing 核心卖点 + A+ 页面重点突出。',
    },
    {
      category: 'market_profit',
      category_name: '市场商业盈利风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '毛利空间偏紧 — 推广预算不足',
      description: '按成本 $8 + 头程 $2 + FBA $3.5 + 佣金 15% 测算，定价 $29.99 时毛利仅 $11.99（40%），扣除广告 ACoS 25% 后净利仅 ~$4.5/件。',
      reason: '类目平均 CPC $0.85-$1.35（厨房小家电属高价词）；新品冷启动期 CVR 仅 3-6%；需要至少 50-80 单/月才能跑出足够数据优化广告。',
      solution: '① 目标定价 $39.99-44.99（毛利提升至 48-53%）；② 供应链端压价到 $6.5 以下（MOQ 500+）；③ 预留首 3 个月广告亏损预算 $2000-3000。',
    },

    // ----- 5. 运营推广风险 -----
    {
      category: 'operation_risk',
      category_name: '运营推广风险',
      level: 'medium' as const,
      level_label: '🟡 中风险',
      title: '变体泛滥 — 同质化变体过多稀释流量',
      description: '类目头部链接普遍采用 5-8 个颜色/尺寸变体策略，若只上单 SKU 会失去变体权重加成和关联流量优势。',
      reason: 'Amazon 变体系统会将父 ASIN 的评论/销量聚合到子链接；单 SKU 新品在搜索结果中视觉占比远低于多变体竞品。',
      solution: '① 上线时至少准备 3 个颜色变体（黑/白/原木色）；② 后续可增加尺寸变体（Standard / Mini / Travel）；③ 变体间保持差异化定位避免内部互搏。',
    },
    {
      category: 'operation_risk',
      category_name: '运营推广风险',
      level: 'low' as const,
      level_label: '🟢 低风险',
      title: '测评风控可控 — 该类目非敏感类目',
      description: '手动研磨器类目不属于 Amazon 高危测评监控类目（不像耳机/充电宝/保健品），Vine 计划和早期亲友测评风险较低。',
      reason: 'Amazon 测评风控重点在 3C 电子/健康保健/美妆等刷单重灾区；厨具类目相对宽松；Vine 官方计划完全合规。',
      solution: '① 上线即注册 Vine Voice（$60/ASIN，最多 30 条评论）；② 首月亲友测评控制在 5 单以内并确保真实购买路径；③ 避免任何形式的折扣返现操作。',
    },
  ]

  // 统计各级别数量
  const highCount = risks.filter(r => r.level === 'high').length
  const mediumCount = risks.filter(r => r.level === 'medium').length
  const lowCount = risks.filter(r => r.level === 'low').length

  // 最终开发建议
  let verdict = ''
  if (highCount >= 2) {
    verdict = '❌ **放弃开发** — 存在多项致命风险（IP侵权 + 利润/垄断），建议更换选品方向或大幅改款后再评估'
  } else if (highCount >= 1) {
    verdict = '⚠️ **谨慎推进** — 存在高危风险项，必须在备货前解决（尤其是 IP 专利排查），其余中风险项制定应对预案后可启动'
  } else if (mediumCount >= 3) {
    verdict = '🟡 **有条件推进** — 无致命风险，但中风险项较多，建议逐条制定规避方案并预留额外预算后启动'
  } else {
    verdict = '✅ **推荐开发** — 风险整体可控，低风险为主，正常推进即可'
  }

  return {
    type: 'pitfalls_report',
    params,
    report_title: `《${productName} 选品风险评估报告》`,
    platform,
    is_amazon: isAmazon,
    product_info: {
      name: productName,
      asin: product.asin || '-',
      keywords: product.keywords || product.keyword || [],
      competitor_asins: product.competitor_asins || params.manual_asins || [],
    },
    summary: {
      high_count: highCount,
      medium_count: mediumCount,
      low_count: lowCount,
      total: risks.length,
      verdict,
      risk_score: Math.max(20, 100 - highCount * 20 - mediumCount * 8),
    },
    risks,
    generated_at: new Date().toLocaleString('zh-CN'),
  }
}

// ========== AIGC 媒体生成器 Mock 执行函数 ==========

// 执行静态素材生成（Mock）— 替代 AI商品绘图 + 主图诊断
const executeStaticAssetGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1500))

  const productName = params._sourceProduct?.title || params.productName || 'Coffee Grinder'
  const imageTypes = params.imageTypes || ['three-view']
  const quantity = params.quantity || 4

  // 根据类型生成不同的 mock 图片
  const generatedAssets: any[] = []
  const typeMap: Record<string, { desc: string; prompt: string }[]> = {
    'three-view': [
      { desc: '正面 45° 白底图', prompt: 'Pure white #FFF background, front 45° angle, studio soft-box lighting, e-commerce standard, 2000x2000' },
      { desc: '侧面轮廓白底图', prompt: 'Pure white background, side profile 90°, clean drop shadow minimal, product photography' },
      { desc: '俯视图白底图', prompt: 'Pure white background, top-down view, flat lay composition, all accessories visible' },
      { desc: '细节特写白底图', prompt: 'Pure white background, macro close-up of key detail texture, sharp focus' },
    ],
    'detail': [
      { desc: '材质纹理特写', prompt: 'Macro close-up, material texture detail, shallow depth of field, studio lighting' },
      { desc: '工艺细节展示', prompt: 'Close-up craftsmanship detail, precision engineering visible, dramatic side lighting' },
      { desc: '尺寸对比参照', prompt: 'Product with size reference object (hand/ruler), natural proportion demonstration' },
    ],
    'scene': [
      { desc: '厨房使用场景', prompt: 'Lifestyle scene on modern kitchen countertop, morning sunlight, warm cozy atmosphere' },
      { desc: '户外露营场景', prompt: 'Outdoor camping lifestyle shot, portable product in nature, adventure aesthetic, golden hour' },
      { desc: '办公桌面场景', prompt: 'Minimalist office desk setup, clean workspace, productivity aesthetic, soft window light' },
    ],
    'lifestyle': [
      { desc: '礼品开箱瞬间', prompt: 'Gift unboxing moment, premium packaging, warm ambient lighting, celebration feeling' },
      { desc: '社交分享场景', prompt: 'Social media style flat lay, product with coffee/phone/laptop, Instagram aesthetic' },
    ],
    'character': [
      { desc: '人物手持产品', prompt: 'Person holding product naturally, casual lifestyle, authentic expression, soft bokeh background' },
      { desc: '人物使用场景', prompt: 'Person actively using product in real scenario, candid moment, documentary style' },
    ],
    'storyboard-frame': [
      { desc: '分镜首帧-钩子开头', prompt: 'Cinematic storyboard frame, dramatic opening hook, high contrast, TikTok 9:16 vertical format' },
      { desc: '分镜首帧-痛点展示', prompt: 'Storyboard frame showing pain point, emotional storytelling, close-up reaction shot' },
      { desc: '分镜首帧-CTA 结尾', prompt: 'Storyboard final frame CTA, product showcase with price tag overlay, call-to-action composition' },
    ],
  }

  let assetIdx = 0
  for (const t of imageTypes) {
    const items = typeMap[t] || typeMap['three-view']
    for (const item of items) {
      if (assetIdx >= quantity) break
      generatedAssets.push({
        id: `asset_${Date.now()}_${assetIdx}`,
        url: `https://picsum.photos/seed/${productName.replace(/\s/g, '')}_${t}_${assetIdx}/600/600`,
        type: t,
        desc: item.desc,
        prompt_hint: item.prompt,
        created_at: new Date().toISOString(),
      })
      assetIdx++
    }
  }

  return {
    type: 'static_asset_gen',
    params,
    product_name: productName,
    generated_assets: generatedAssets,
    generation_params: {
      mode: 'image-to-image',
      source_image: params.source_image_name || 'uploaded',
      style: params.style || 'studio',
      types: imageTypes,
      total_generated: generatedAssets.length,
    },
    tips: [
      '确认满意后，点结果卡片「归档到素材库」手动保存（可选择分组、绑定产品）',
      '白底图符合 Amazon 主图规范（纯白 #FFFFFF 背景，产品占 85% 以上面积）',
      '场景图注意文化中性（避免特定节日/宗教元素）',
      '分镜首帧图可关联到带货脚本的对应镜头',
    ],
  }
}

// 执行短视频带货脚本生成（Mock）— 替代 分镜脚本
const executeVideoScriptGen = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1000))

  const productName = params._sourceProduct?.title || params.productName || 'Portable Coffee Grinder'
  const platform = params.platform || 'tiktok'
  const videoStyle = params.videoStyle || 'problem-solution'
  const sellingPoints = params.selling_points || '静音研磨、陶瓷磨芯、便携小巧'
  const painPoints = params.painPoints || '电动噪音大、研磨不均匀、难清洗'

  const platformLabel: Record<string, string> = { tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' }

  // 根据风格生成不同脚本
  const scriptTemplates: Record<string, { summary: string; scenes: any[] }> = {
    'problem-solution': {
      summary: `**痛点驱动型脚本**：前3秒用「电动研磨器吵得邻居敲门」钩住注意力 → 展示本产品静音优势 → 多场景便携证明 → CTA 限时优惠`,
      scenes: [
        { duration: 3, visual: '黑屏+音效"咚咚咚"：模拟邻居敲门声，画面出现"又来了？"', narration: '你的电动研磨器是不是也…', cameraMovement: 'static', shotSize: 'closeup', bgm: 'silence', subtitleStyle: 'bold-bottom', frameRef: '' },
        { duration: 5, visual: '产品 360° 缓慢旋转，手指轻触磨芯，完全无声', narration: '陶瓷磨芯，静音到…（耳语）…听不见', cameraMovement: 'rotate', shotSize: 'medium-shot', bgm: 'asmr', subtitleStyle: 'highlight', frameRef: '' },
        { duration: 5, visual: '分屏左=电动（噪音波形满格），右=本产品（波形平缓）', narration: '零电机噪音，只有咖啡豆碎裂的治愈声', cameraMovement: 'static', shotSize: 'full-shot', bgm: 'asmr', subtitleStyle: 'bold-bottom', frameRef: '' },
        { duration: 5, visual: '快切4场景：厨房→办公室→露营→旅行箱（各2秒）', narration: '家用、办公、户外、旅行…走到哪带到哪', cameraMovement: 'zoom-dolly', shotSize: 'wide-angle', bgm: 'upbeat', subtitleStyle: 'typewriter', frameRef: '' },
        { duration: 4, visual: '手握产品倒入咖啡粉，蒸汽升腾，满足表情', narration: '现磨的香气，真的不一样', cameraMovement: 'push-in-slow', shotSize: 'closeup', bgm: 'lo-fi', subtitleStyle: 'none', frameRef: '' },
        { duration: 3, visual: '产品+价格$24.99+购物车动画+倒计时', narration: '限时8折，链接在左下角，手慢无！', cameraMovement: 'static', shotSize: 'medium-shot', bgm: 'swoosh', subtitleStyle: 'highlight', frameRef: '' },
      ],
    },
    'product-showcase': {
      summary: `**产品展示型脚本**：纯视觉冲击路线，ASMR 研磨音效 + 电影级运镜 + 每帧都是壁纸级别`,
      scenes: [
        { duration: 3, visual: '暗光环境，一束聚光灯打在产品上，缓慢推近', narration: '', cameraMovement: 'push-in-slow', shotSize: 'closeup', bgm: 'cinematic', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '产品拆解动画：外壳→磨芯→粉仓→组装，每步微距', narration: '', cameraMovement: 'rotate', shotSize: 'extreme-closeup', bgm: 'asmr', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '咖啡豆落入→研磨→出粉→冲泡 全流程慢动作', narration: '', cameraMovement: 'ken-burns', shotSize: 'closeup', bgm: 'lo-fi', subtitleStyle: 'none', frameRef: '' },
        { duration: 6, visual: '不同产地咖啡豆拼配特写（埃塞俄比亚/哥伦比亚/巴西）', narration: '', cameraMovement: 'pan-left-right', shotSize: 'extreme-closeup', bgm: 'acoustic', subtitleStyle: 'typewriter', frameRef: '' },
        { duration: 4, visual: '成品拉花特写，产品在背景虚化处若隐若现', narration: '', cameraMovement: 'pull-out-reveal', shotSize: 'medium-shot', bgm: 'cinematic', subtitleStyle: 'none', frameRef: '' },
        { duration: 5, visual: 'Logo + 品牌名 + Slogan 渐显', narration: '', cameraMovement: 'static', shotSize: 'full-shot', bgm: 'cinematic', subtitleStyle: 'bold-bottom', frameRef: '' },
      ],
    },
  }

  const template = scriptTemplates[videoStyle] || scriptTemplates['problem-solution']
  const totalDuration = template.scenes.reduce((sum, s) => sum + s.duration, 0)

  return {
    type: 'video_script_gen',
    params,
    product_name: productName,
    platform,
    platform_label: platformLabel[platform],
    video_style: videoStyle,
    total_duration: totalDuration,
    script_summary: template.summary,
    selling_points_used: sellingPoints,
    pain_points_used: painPoints,
    storyboard: template.scenes.map((s, i) => ({
      ...s,
      scene: i + 1,
      time: template.scenes.slice(0, i).reduce((sum, x) => sum + x.duration, 0),
    })),
    shooting_tips: [
      `${platformLabel[platform]} 竖版 9:16 适配`,
      '前 3 秒必须有视觉或听觉钩子（痛点/悬念/反差）',
      '字幕要大且醒目（占画面 1/3），关键信息用高亮色',
      '每个镜头控制在 3-6 秒，保持节奏紧凑',
      '音乐版权：使用无版权素材库或原创 BGM',
    ],
  }
}

// 将最近生成的脚本写入共享 store，供 AI 短视频生成「分镜脚本专业模式」导入
const saveScriptToStore = async (result: any) => {
  try {
    const { useVideoScriptsStore } = await import('@/stores/videoScripts')
    useVideoScriptsStore().saveLastScript(result)
  } catch (e) {
    console.warn('写入 lastVideoScript 失败：', e)
  }
}

/**
 * 把 Listing 工具的执行结果同步到「Listing 工作区」草稿，
 * 让右侧面板与对话结果保持一致（对话里生成 → 面板里继续编辑/保存）
 */
const syncListingDraft = (toolId: string, params: any, result: any) => {
  try {
    const draft = useListingDraftStore()
    // 有产品来源时，先用产品预填一次，保证面板上下文正确
    if (params?.product_id && !draft.productId) {
      const p = productLibraryStore.items.find((i: any) => i.id === params.product_id)
      if (p) draft.loadFromProduct(p)
    }
    if (!draft.productName && params?.product_name) draft.productName = params.product_name
    if (!draft.brand && params?.brand) draft.brand = params.brand

    switch (toolId) {
      case 'keyword-miner':
        if (Array.isArray(result?.keywords)) draft.setKeywords(result.keywords)
        break
      case 'title-gen':
        if (result?.recommended_title) {
          draft.setTitle(result.recommended_title, (result.variants || []).map((v: any) => v.title || v))
        }
        break
      case 'bullet-gen':
        if (Array.isArray(result?.bullets)) {
          draft.setBullets(result.bullets.map((b: any) => ({ title: b.title || '', content: b.content || b.point || '' })))
        }
        break
      case 'desc-gen':
        if (result?.description) draft.setAPlus(draft.aplusModules.length ? draft.aplusModules : normalizeDescToModules(result.description))
        break
      case 'seo-audit':
        if (Array.isArray(result?.dimensions) || Array.isArray(result?.checks)) {
          draft.setSeo(result.checks || result.dimensions, result.overall_score)
        }
        break
    }
  } catch (e) {
    console.warn('同步 Listing 草稿失败：', e)
  }
}

/** desc-gen 的 description（含 sections）→ A+ 模块结构 */
const normalizeDescToModules = (desc: any): any[] => {
  if (Array.isArray(desc?.modules)) return desc.modules
  if (Array.isArray(desc?.sections)) {
    return desc.sections.map((s: any) => ({ type: 'text', heading: s.heading || '', content: s.content || '' }))
  }
  return []
}

// 执行 AI 短视频生成（Mock）— 支持 分镜脚本专业模式 / 单图极速生成
const executeAIVideoGenerator = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 2000))

  const productName = params._sourceProduct?.title || params.productName || 'Coffee Grinder'
  const mode = params.mode || 'storyboard-pro'     // storyboard-pro | single-image
  const sceneCount = params.storyboardScenes?.length || 1
  const clipCount = mode === 'single-image' ? 1 : sceneCount

  // 单图极速模式：围绕底图自动规划镜头
  const previewFrames = mode === 'single-image'
    ? [
        { timestamp: '00:02', url: params.singleImageUrl || `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_0/480/854`, desc: '底图 → 开场画面' },
        { timestamp: '00:06', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_1/480/854`, desc: '卖点演绎画面' },
        { timestamp: '00:10', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_2/480/854`, desc: '场景氛围画面' },
        { timestamp: '00:14', url: `https://picsum.photos/seed/single_${productName.replace(/\s/g, '')}_3/480/854`, desc: 'CTA 结尾画面' },
      ]
    : Array.from({ length: Math.min(clipCount, 6) }, (_, i) => ({
        timestamp: `00:${String(i * 4 + 2).padStart(2, '0')}`,
        url: (params.storyboardScenes?.[i]?.imageUrl) || `https://picsum.photos/seed/vframe_${productName.replace(/\s/g, '')}_${i}/480/854`,
        desc: `镜头 ${i + 1}${params.storyboardScenes?.[i]?.desc ? '：' + params.storyboardScenes[i].desc : ' 预览帧'}`,
      }))

  return {
    type: 'ai_video_generator',
    params,
    product_name: productName,
    mode,
    mode_label: mode === 'single-image' ? '单图极速生成' : '分镜脚本专业模式',
    video_url: '/mock/generated_video.mp4',
    thumbnail_url: params.singleImageUrl || `/mock/video_thumb_${Date.now()}.jpg`,
    clip_count: clipCount,
    metadata: {
      duration: (mode === 'single-image' ? 15 : clipCount * 4 + 2),
      resolution: (params.aspectRatio === '16:9') ? '1920x1080 (16:9)' : '1080x1920 (9:16)',
      format: 'MP4 H.264',
      fps: parseInt(params.fps) || 30,
      file_size: `${(clipCount * 3.2).toFixed(1)} MB`,
    },
    preview_frames: previewFrames,
    archived: false,  // 不再自动归档，由用户手动确认
    archive_target: params._sourceProduct ? params._sourceProduct.title : null,
    next_steps: [
      '预览视频，确认内容无误',
      '可选择：添加配音/更换背景音乐/调整节奏',
      '确认后可归档到营销素材库',
      `一键分发到 ${params.targetPlatform === 'tiktok' ? 'TikTok' : params.targetPlatform === 'reels' ? 'Instagram Reels' : '各平台'}`,
    ],
  }
}

// ========== 运营复盘师 Mock 执行函数 ==========

// 执行周报生成（Mock）
const executeWeeklyReport = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 800))

  const weekLabel = params.week_label || '本周'
  return {
    type: 'weekly_report',
    params,
    period: weekLabel,
    report_date: new Date().toISOString().slice(0, 10),
    kpis: {
      total_revenue: { value: 28450, change_pct: 12.3, target: 25000, status: 'excellent' },
      total_orders: { value: 892, change_pct: 8.5, target: 850, status: 'good' },
      ad_spend: { value: 3850, change_pct: 5.2, target: 4000, status: 'good' },
      acos: { value: 22.8, change_pct: -3.1, target: 25, status: 'good' },
      conversion_rate: { value: 9.8, change_pct: 1.2, target: 9.0, status: 'good' },
      return_rate: { value: 6.2, change_pct: 0.8, target: 8, status: 'excellent' },
    },
    highlights: [
      '🏆 周三单日销售额突破 $5,200，创历史新高',
      '📦 新品 SKU-0027 首周销量达 120 件，超出预期 50%',
      '🎯 广告 RoAS 从 3.8 提升至 4.4，精准匹配优化见效',
    ],
    concerns: [
      '⚠️ 周五下午出现 2 小时断货（SKU-0015），预计损失 $800 销售额',
      '⚠️ 竞品 B08XXXXX2 在周三降价 10%，我们的 CTR 当日下降 15%',
    ],
    next_week_priorities: [
      '补货 SKU-0015 至安全库存水位（≥200 件）',
      '监控竞品价格变动，准备应对方案',
      '测试新的视频广告素材（已完成分镜脚本）',
    ],
  }
}

// 执行月度复盘（Mock）
const executeMonthlyReview = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 1000))

  return {
    type: 'monthly_review',
    params,
    period: params.month_label || '2026年8月',
    executive_summary: {
      total_gmv: 118000,
      mom_change: 15.2,
      yoy_change: 42.5,
      net_profit: 18200,
      net_margin: 15.4,
      total_ad_spend: 16500,
      blended_acos: 23.5,
    },
    trend_analysis: {
      revenue_trend: [92000, 98000, 102000, 118000],
      acos_trend: [26.8, 25.2, 24.1, 23.5],
      conversion_trend: [8.5, 8.9, 9.3, 9.8],
      labels: ['5月', '6月', '7月', '8月'],
    },
    top_products: [
      { sku: 'SKU-001', name: 'Premium Coffee Grinder', revenue: 35400, margin: 18.2, growth: 22.0 },
      { sku: 'SKU-007', name: 'Silicone Utensil Set', revenue: 22800, margin: 21.5, growth: 15.0 },
      { sku: 'SKU-012', name: 'LED Plant Grow Light', revenue: 15600, margin: 16.8, growth: 35.0 },
      { sku: 'SKU-003', name: 'Portable Humidifier', revenue: 12200, margin: 14.2, growth: -5.0 },
      { sku: 'SKU-019', name: 'Acrylic Makeup Organizer', revenue: 9800, margin: 25.1, growth: 8.0 },
    ],
    key_insights: [
      '📈 GMV 连续 4 个月增长，月复合增长率 8.6%',
      '💰 整体净利率从 12% 提升至 15.4%，主要得益于 ACoS 下降',
      '⭐ SKU-012（植物灯）增速最快（+35%），Q4 需求旺季提前备货',
      '⚠️ SKU-003 加湿器首次负增长，需关注竞品动态和评价变化',
    ],
    strategic_recommendations: [
      '加大 SKU-001 和 SKU-012 的广告预算投入（ROI 最高）',
      '启动 SKU-003 的 Listing 优化和价格策略 review',
      'Q4 备货计划：基于 30% 增长预期，建议 9 月中旬入库完毕',
      '新品线规划：基于选品蓝海分析结果，Q4 上线 2-3 个新 SKU',
    ],
  }
}

// 执行广告复盘（Mock）
const executeAdReview = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 900))

  return {
    type: 'ad_review',
    params,
    period: params.period || '近30天',
    overview: {
      total_spend: 16500,
      total_sales: 70200,
      blended_roas: 4.25,
      blended_acos: 23.5,
      total_clicks: 42500,
      total_impressions: 2800000,
      avg_ctr: 1.52,
      avg_cpc: 0.39,
      avg_cvr: 9.6,
    },
    campaign_breakdown: [
      { campaign: 'SP-自动广告', spend: 4200, sales: 13440, roas: 3.2, acos: 31.3, trend: '↓ 改善中' },
      { campaign: 'SP-手动-精准', spend: 5800, sales: 34800, roas: 6.0, acos: 16.7, trend: '↑ 稳定优秀' },
      { campaign: 'SP-手动-短语', spend: 2100, sales: 8820, roas: 4.2, acos: 23.8, trend: '→ 持平' },
      { campaign: 'SB-品牌广告', spend: 1600, sales: 7200, roas: 4.5, acos: 22.2, trend: '↑ 提升中' },
      { campaign: 'SD-展示广告', spend: 2800, sales: 5940, roas: 2.1, acos: 47.1, trend: '↓ 需优化' },
    ],
    attribution_analysis: {
      top_converting_keywords: [
        { keyword: 'ceramic coffee grinder', spend: 2200, sales: 14300, roas: 6.5, attribution: 'last_click' },
        { keyword: 'portable manual grinder', spend: 1800, sales: 9000, roas: 5.0, attribution: 'last_click' },
        { keyword: 'hand coffee mill', spend: 1200, sales: 4800, roas: 4.0, attribution: 'assist' },
      ],
      assist_metrics: {
        total_assisted_conversions: 280,
        assist_value: 11200,
        assisted_roas_boost: '+0.6x',
      },
    },
    actionable_items: [
      '🔴 SD 展示广告 ACoS 47.1% 过高，建议暂停低效 PAT 定向，释放 $1200 预算给 SP',
      '🟢 SP 手动精准 Campaign 表现优异（RoAS 6.0），可追加 $800 预算测试扩量',
      '🟡 自动广告 ACoS 31.3% 仍有空间，本周下载搜索词报告新增否定词',
      '📊 建议开启品牌防御（SBV），保护品牌词 SOV 不被竞品抢占',
    ],
  }
}

// 执行商品表现（Mock）
const executeProductPerformance = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  return {
    type: 'product_performance',
    params,
    period: params.period || '近30天',
    products: [
      { sku: 'SKU-001', name: 'Premium Coffee Grinder', revenue: 35400, units: 1180, margin_pct: 18.2, profit: 6443, turnover_days: 32, rating: 4.6, reviews: 3420, trend: '📈 +22%', tier: 'star' },
      { sku: 'SKU-007', name: 'Silicone Utensil Set', revenue: 22800, units: 760, margin_pct: 21.5, profit: 4902, turnover_days: 28, rating: 4.4, reviews: 1890, trend: '📈 +15%', tier: 'star' },
      { sku: 'SKU-012', name: 'LED Plant Grow Light', revenue: 15600, units: 446, margin_pct: 16.8, profit: 2621, turnover_days: 45, rating: 4.5, reviews: 680, trend: '📈 +35%', tier: 'rising' },
      { sku: 'SKU-019', name: 'Acrylic Makeup Organizer', revenue: 9800, units: 490, margin_pct: 25.1, profit: 2460, turnover_days: 18, rating: 4.8, reviews: 2150, trend: '📈 +8%', tier: 'stable' },
      { sku: 'SKU-003', name: 'Portable Humidifier', revenue: 12200, units: 610, margin_pct: 14.2, profit: 1732, turnover_days: 55, rating: 4.1, reviews: 890, trend: '📉 -5%', tier: 'declining' },
      { sku: 'SKU-025', name: 'Wireless Charging Pad', revenue: 4500, units: 225, margin_pct: 12.8, profit: 576, turnover_days: 72, rating: 3.9, reviews: 320, trend: '📉 -18%', tier: 'at_risk' },
    ],
    summary: {
      total_skus: 6,
      star_products: 2,
      rising: 1,
      stable: 1,
      declining: 1,
      at_risk: 1,
      total_revenue: 100300,
      avg_margin: 18.1,
    },
    alerts: [
      { sku: 'SKU-025', alert: '连续 4 周下滑，库存周转 72 天，考虑清仓或下架', severity: 'high' },
      { sku: 'SKU-003', alert: '月度首次负增长，近期差评增加 12 条（质量问题？）', severity: 'medium' },
    ],
  }
}

// 执行库存健康度（Mock）
const executeInventoryHealth = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 650))

  return {
    type: 'inventory_health',
    params,
    check_date: new Date().toISOString().slice(0, 10),
    overall_health_score: 72,
    inventory_items: [
      { sku: 'SKU-001', name: 'Premium Coffee Grinder', fba_stock: 285, inbound: 200, daily_sales_avg: 38, days_of_stock: 7.5, status: 'healthy', reorder_point: 200, suggestion: '库存健康，在途 200 件预计 7 天内入仓' },
      { sku: 'SKU-007', name: 'Silicone Utensil Set', fba_stock: 45, inbound: 0, daily_sales_avg: 25, days_of_stock: 1.8, status: 'critical', reorder_point: 250, suggestion: '⚠️ 即将断货！仅剩 1.8 天库存，紧急补货' },
      { sku: 'SKU-012', name: 'LED Plant Grow Light', fba_stock: 520, inbound: 300, daily_sales_avg: 15, days_of_stock: 54.7, status: 'overstock', reorder_point: 150, suggestion: '库存偏高（55天），Q4 旺季前暂不额外补货' },
      { sku: 'SKU-003', name: 'Portable Humidifier', fba_stock: 180, inbound: 100, daily_sales_avg: 20, days_of_stock: 14.0, status: 'warning', reorder_point: 200, suggestion: '低于安全水位，在途 100 件到货后恢复' },
      { sku: 'SKU-019', name: 'Acrylic Makeup Organizer', fba_stock: 380, inbound: 0, daily_sales_avg: 16, days_of_stock: 23.8, status: 'healthy', reorder_point: 160, suggestion: '库存正常，建议 2 周后安排补货' },
      { sku: 'SKU-025', name: 'Wireless Charging Pad', fba_stock: 420, inbound: 0, daily_sales_avg: 7.5, days_of_stock: 56.0, status: 'slow_moving', reorder_point: 80, suggestion: '周转过慢（56天），长期仓储费风险。建议促销清仓' },
    ],
    financial_impact: {
      estimated_long_term_storage_fee: 285,
      tied_up_capital: 18600,
      lost_sales_risk: 6750, // SKU-007 断货预估
    },
    recommendations: [
      '🚨 P0：SKU-007 紧急补货，联系供应商加急发货（预计损失 $6,750 销售额）',
      '📋 P1：SKU-025 制定清仓计划（折扣 30-40% + Bundle 搭配）',
      '💡 P2：SKU-012 库存充足，暂停补货直至 Q4 旺季开始',
      '📊 建议设置自动补货阈值：FBA 库存 < 14 天销量时触发采购',
    ],
  }
}

// 执行利润审计（Mock）
const executeProfitAudit = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 900))

  return {
    type: 'profit_audit',
    params,
    period: params.period || '本月',
    pnl_summary: {
      total_revenue: 118000,
      cogs: 58200,          // 销售成本
      gross_profit: 59800,
      gross_margin: 50.7,
      expenses: [
        { item: 'Amazon 佣金 (15%)', amount: -17700 },
        { item: 'FBA 配送费', amount: -8920 },
        { item: '广告花费', amount: -16500 },
        { item: '退货损耗', amount: -3540 },
        { item: '长期仓储费', amount: -285 },
        { item: '头程运费摊销', amount: -4200 },
        { item: '其他杂费', amount: -1455 },
      ],
      total_expenses: -52600,
      net_profit: 7200,
      net_margin: 6.1,
    },
    profitability_by_sku: [
      { sku: 'SKU-001', revenue: 35400, cogs: 16500, fulfillment: 2680, ad_cost: 4960, returns: 1062, net_profit: 10198, net_margin: 28.8 },
      { sku: 'SKU-007', revenue: 22800, cogs: 9120, fulfillment: 1730, ad_cost: 3200, returns: 684, net_profit: 8066, net_margin: 35.4 },
      { sku: 'SKU-012', revenue: 15600, cogs: 7800, fulfillment: 1180, ad_cost: 2180, returns: 468, net_profit: 3972, net_margin: 25.5 },
      { sku: 'SKU-003', revenue: 12200, cogs: 6588, fulfillment: 924, ad_cost: 1830, returns: 488, net_profit: 2370, net_margin: 19.4 },
      { sku: 'SKU-025', revenue: 4500, cogs: 2700, fulfillment: 342, ad_cost: 1350, returns: 225, net_profit: -117, net_margin: -2.6 },
    ],
    insights: [
      '💰 SKU-007（硅胶厨具）净利率最高 35.4%，应作为主力推广款',
      '⚠️ SKU-025（无线充电板）净亏损 $117，需立即审查定价或考虑下架',
      '📊 广告占总收入 14%，处于健康区间（行业平均 10-20%）',
      '🔄 退货率 3% 控制良好，低于类目平均值 5-8%',
    ],
    optimization_plan: [
      '将 SKU-007 广告预算提升 20%，发挥高利润优势',
      'SKU-025 进行盈利能力审查：提价 $3 或寻找更低价供应链',
      '目标下月净利率从 6.1% 提升至 8%+',
    ],
  }
}

// 执行行动计划（Mock）
const executeActionPlan = async (params: any): Promise<any> => {
  await new Promise(resolve => setTimeout(resolve, 700))

  return {
    type: 'action_plan',
    params,
    period: params.period || '本月',
    generated_at: new Date().toISOString(),
    // 止损项（红色 - 需立即处理）
    stop_loss: [
      { id: 1, priority: 'P0', category: '广告', title: '硅胶厨具 ACOS 高达 45%', impact: '月浪费 $2,400+', action: '降低手动关键词出价 20%，否词搜索词 >$3', owner: '广告优化师', deadline: '3天内' },
      { id: 2, priority: 'P0', category: '库存', title: 'SKU-025 无线充电板断货风险', impact: '预计 5 天后断货，月损失 $4,500', action: '紧急补货 500 件，开启加速模式', owner: '供应链', deadline: '立即' },
      { id: 3, priority: 'P1', category: 'Listing', title: '便携加湿器差评率升至 8%', impact: '转化率下降 1.2%，BSR 下跌 15 名', action: '分析差评根因，优化产品描述+跟进客服', owner: '运营', deadline: '7天内' },
    ],
    // 优化项（黄色 - 可提升效率）
    optimize: [
      { id: 4, priority: 'P1', category: '广告', title: 'LED 植物灯 ROAS 提升空间大', impact: '当前 ROAS 2.8，目标可达 4.0+', action: '新增长尾词 20 个，测试视频广告格式', owner: '广告优化师', deadline: '14天内' },
      { id: 5, priority: 'P2', category: '定价', title: ' acrylic 收纳盒定价偏低', impact: '竞品均价 $24.99，我们 $19.99', action: '提价至 $22.99 并 A/B 测试', owner: '运营', deadline: '30天内' },
      { id: 6, priority: 'P2', category: 'FBA', title: 'LTF 费用超支 $285/月', action: '移库滞销 SKU-018/023 至卖家自配送', owner: '供应链', deadline: '本月' },
    ],
    // 机会点（绿色 - 增长潜力）
    opportunity: [
      { id: 7, priority: 'P2', category: '新品', title: '秋季新品：电动剥皮器蓝海验证', impact: '关键词搜索量月增 300%+，竞争度低', action: '快速上架 + SBV 视频 + Vine 计划', owner: '选品+运营', deadline: '下季' },
      { id: 8, priority: 'P3', category: '拓展', title: '加拿大站扩展机会', impact: 'US 畅销 SKU 在 CA 无竞品', action: '同步 Top 5 SKU 至 CA，启用 NARF', owner: '运营', deadline: 'Q4' },
      { id: 9, priority: 'P3', category: '品牌', title: 'Brand Store 访客转化提升', impact: 'Store 访客 CVR 仅 12%，行业 18%', action: '优化 Store 首页 + A+ 页面关联', owner: '品牌', deadline: '60天' },
    ],
    summary: {
      total_actions: 9,
      urgent: 3,
      in_progress: 3,
      opportunity: 3,
      estimated_impact: '+$8,200/月潜在利润提升',
    },
  }
}

// 辅助：时间范围标签
const timeRangeLabel = (tr: string): string => ({ '7d': '近7天', '30d': '近30天', '90d': '近90天' }[tr] || '近30天')

// 添加结果摘要到对话区
const addResultSummaryToChat = (toolId: string, result: any) => {
  let content = ''
  switch (toolId) {
    case 'blue-ocean':
      content = `✅ **蓝海挖掘完成** - 发现 ${result.products?.length || 0} 个候选商品\n\n` +
        `- 优质蓝海（≥70分）：${result.summary?.high_potential || 0} 个\n` +
        `- 一般潜力（40-69分）：${result.summary?.medium_potential || 0} 个\n` +
        `- 高竞争（<40分）：${result.summary?.high_competition || 0} 个\n\n` +
        `详细结果已展示在上方表格中，可在此继续提问或调整参数重新分析。`
      break
    case 'pain-points':
      content = `🔍 **痛点分析完成** - 发现 ${result.pain_points?.length || 0} 个核心痛点\n\n` +
        `- 分析评论：${result.total_reviews_analyzed || 0} 条（差评 ${result.negative_review_count || 0} 条）\n` +
        `- 市场空白评分：${result.market_gap_score || 0}/100\n\n` +
        `详细报告已展示在上方。`
      break
    case 'competitor':
      content = `⚔️ **竞品对比完成** - 对比 ${result.competitors?.length || 0} 个竞品\n\n` +
        `- 价格区间：$${result.price_range?.min || 0} - $${result.price_range?.max || 0}\n` +
        `- 平均评分：${result.avg_rating?.toFixed(1) || '-'} ⭐\n\n` +
        `${result.recommendation || ''}`
      break
    case 'profit-calc':
      content = `💰 **利润测算完成**\n\n` +
        `- 售价：$${result.calculation?.selling_price}\n` +
        `- 总成本：$${result.calculation?.total_cost}\n` +
        `- 净利润：$${result.calculation?.net_profit}\n` +
        `- ROI：${result.calculation?.roi}%\n\n` +
        `费用明细已展示在上方。`
      break
    case 'ad-diagnosis':
      content = `📊 **广告诊断完成** - 综合评分 **${result.grade || '-'}**（${result.overall_score || 0}分）\n\n` +
        `${result.summary || ''}\n\n` +
        `- 发现 Campaign：${result.campaigns?.length || 0} 个\n` +
        `- 重点关注问题：${result.top_issues?.filter((i: any) => i.priority === 'high').length || 0} 个高优先级\n\n` +
        `详细诊断报告已展示在上方。`
      break
    case 'keyword-report':
      content = `🔍 **搜索词报告完成**\n\n` +
        `- 总搜索词数：${result.total_terms || 0}\n` +
        `- 🟢 高效词：${result.high_performers?.length || 0} 个\n` +
        `- 🔴 低效词：${result.low_performers?.length || 0} 个\n` +
        `- ⚠️ 浪费词：${result.waste_terms?.length || 0} 个\n` +
        `- 💡 机会词：${result.new_opportunities?.length || 0} 个\n\n` +
        `优化建议已展示在上方。`
      break
    case 'bid-suggest':
      content = `💡 **出价建议完成** — 策略：${({ aggressive: '激进', balanced: '平衡', conservative: '保守' } as Record<string, string>)[result.strategy_type] || '平衡'}\n\n` +
        `- 分析关键词：${result.total_keywords || 0} 个\n` +
        `- 预计预算变动：$${result.budget_impact > 0 ? '+' : ''}${result.budget_impact}\n` +
        `- 预期 ACoS 变化：${result.expected_acos_change > 0 ? '+' : ''}${result.expected_acos_change.toFixed(1)}%\n\n` +
        `调价详情已展示在上方。`
      break
    case 'competitor-ad':
      content = `🎯 **竞品广告分析完成**\n\n` +
        `- 你的 SOV：${result.your_share_of_voice}%\n` +
        `- 分析竞品：${result.competitors?.length || 0} 个\n` +
        `- 最大威胁：${result.competitors?.[0]?.competitor_name || '-'}（SOV ${result.competitors?.[0]?.share_of_voice || 0}%）\n\n` +
        `可执行洞察已展示在上方。`
      break
    case 'budget-alloc':
      content = `📋 **预算分配方案完成**\n\n` +
        `- 当前总预算：$${result.total_current_budget}/天\n` +
        `- 建议总预算：$${result.total_suggested_budget}/天\n` +
        `- 变动幅度：${(((result.total_suggested_budget - result.total_current_budget) / result.total_current_budget) * 100).toFixed(1)}%\n\n` +
        `预期改善：RoAS ${result.projected_improvement?.expected_roas_increase} | ACoS ${result.projected_improvement?.expected_acos_decrease}`
      break
    case 'anomaly-detect':
      content = `🚨 **异常检测完成** ${result.alert_count > 0 ? `— 发现 **${result.alert_count}** 个高风险异常！` : '— 一切正常 ✅'}\n\n` +
        `${result.summary || ''}\n` +
        `- 检测周期：${result.check_period}\n` +
        `- 异常项数：${result.anomalies?.length || 0}\n\n` +
        `详细异常报告已展示在上方。`
      break
    case 'order-track':
      const ord = result.order
      content = `📦 **订单查询完成**\n\n` +
        `- 订单号：${ord.order_id}\n` +
        `- 状态：${ord.status_icon || '📋'} ${ord.status_text}\n` +
        `- 商品：${ord.product_name}\n` +
        `- 数量：${ord.quantity} | 金额：$${ord.total}` +
        (ord.tracking_number ? `\n- 物流：${ord.carrier} | 单号：${ord.tracking_number}` : '') +
        (ord.estimated_delivery ? `\n- 预计送达：${ord.estimated_delivery}` : '')
      break
    case 'ticket-create':
      const tkt = result.ticket
      content = `🎫 **工单创建成功**\n\n` +
        `- 工单号：**${tkt.ticket_id}**\n` +
        `- 标题：${tkt.subject}\n` +
        `- 分类：${tkt.category} | 优先级：${tkt.priority}\n` +
        `- SLA响应时间：${result.estimated_response_time}\n\n` +
        `${result.message}`
      break
    case 'monitor-dashboard':
      content = `📊 **监控仪表盘完成** — 共 **${result.total_competitors}** 个竞品\n\n` +
        `${result.summary?.overview || ''}\n\n` +
        `- 🟢 健康分 ≥80：${result.competitors?.filter((c: any) => c.health_score >= 80).length || 0} 个\n` +
        `- 🟡 警报竞品：${result.competitors?.filter((c: any) => c.alert_count > 0).length || 0} 个\n\n` +
        `详细数据已展示在上方。`
      break
    case 'price-track':
      content = `📉 **价格追踪完成** — 追踪 **${result.tracked_count}** 个竞品\n\n` +
        `- 价格下降最多：${(Math.min(...(result.competitors?.map((c: any) => c.price_change_pct) || [0]))).toFixed(1)}%\n` +
        `- 排名上升最快：+${Math.max(...(result.competitors?.map((c: any) => c.rank_change) || [0]))} 位\n\n` +
        `竞争力排名已展示在上方。`
      break
    case 'market-share':
      content = `🌍 **市场份额分析完成** — ${result.category}\n\n` +
        `- 预估市场规模：$${(result.total_market_estimate / 1000).toFixed(0)}K/月\n` +
        `- 竞争品牌数：${result.competitors?.length || 0}\n` +
        `- CR4集中度：${result.concentration_ratio?.cr4?.toFixed(1)}%（${({ high: '高度集中', medium: '中度集中', low: '充分竞争' } as Record<string, string>)[(result.concentration_ratio?.cr4 || 0) >= 75 ? 'high' : (result.concentration_ratio?.cr4 || 0) >= 50 ? 'medium' : 'low'] || '-'}）\n\n` +
        `市场格局详情已展示在上方。`
      break
    case 'pricing-analysis':
      content = `💵 **定价策略分析完成** — 分析 **${result.analyzed_count}** 个竞品\n\n` +
        `- 发现策略类型：${result.strategies?.map((s: any) => ({ premium: '溢价', economy: '经济', competitive: '竞争', dynamic: '动态' } as Record<string, string>)[s.strategy_type] || s.strategy_type).join(' / ') || '-'}\n` +
        `- 最高均价：$${Math.max(...(result.strategies?.map((s: any) => s.base_price) || [0])).toFixed(2)}\n` +
        `- 最大波动率：${(Math.max(...(result.strategies?.map((s: any) => s.price_volatility) || [0])) * 100).toFixed(1)}%\n\n` +
        `策略详情已展示在上方。`
      break
    case 'review-spy':
      const reviewProduct = result.analyses?.[0]
      content = `🔎 **评论侦探完成** — 分析 **${reviewProduct?.brand || '-'}}** (${reviewProduct?.asin || '-'})\n\n` +
        `- 总评分：${reviewProduct?.overall_rating?.toFixed(1)} ⭐（${reviewProduct?.total_reviews || 0} 条评论）\n` +
        `- 洞察维度：${reviewProduct?.insights?.length || 0} 个\n` +
        `- 可行动情报：${reviewProduct?.actionable_intelligence?.length || 0} 条\n\n` +
        `SWOT分析已展示在上方。`
      break
    case 'intruder-alert':
      content = `🚨 **入侵者检测完成** — 发现 **${result.new_competitors?.length || 0}** 个新竞争者\n\n` +
        `- 🔴 高威胁：${result.threat_summary?.high || 0} 个\n` +
        `- 🟡 中威胁：${result.threat_summary?.medium || 0} 个\n` +
        `- 🟢 低威胁：${result.threat_summary?.low || 0} 个\n\n` +
        `${result.new_competitors?.some((c: any) => c.our_product_affected) ? '⚠️ 有新竞争者影响我方产品，建议立即查看应对策略！' : '暂未发现直接影响我方产品的入侵者。'}`
      break
    case 'buy-box-analysis':
      const bbItem = result.analyses?.[0]
      content = `🛒 **Buy Box 分析完成** — 竞争力评分 **${bbItem?.competitiveness_score || 0}** 分\n\n` +
        `- Buy Box 卖家数：${bbItem?.buy_box_analysis?.sellers?.length || 0} 家\n` +
        `- 当前赢家：${bbItem?.buy_box_analysis?.sellers?.find((s: any) => s.is_winner)?.seller_name || '-'}\n` +
        `- 最低价格卖家：$${Math.min(...(bbItem?.buy_box_analysis?.sellers?.map((s: any) => s.price + s.shipping) || [999]))?.toFixed(2)}\n\n` +
        `提升建议已展示在上方。`
      break
    case 'compare-grid':
      content = `⚔️ **多维对比完成** — 对比 **${result.compared_count}** 个竞品\n\n` +
        `- 性价比最高：${result.comparison?.value_ranking?.[0]?.brand || '-'}（${result.comparison?.value_ranking?.[0]?.value_score || 0} 分）\n` +
        `- 价格跨度：$${result.comparison?.differentiation?.price_spread?.toFixed(2)}\n` +
        `- 评分跨度：${result.comparison?.differentiation?.rating_spread?.toFixed(1)} ⭐\n\n` +
        `各维度对比和差异化分析已展示在上方。`
      break
    // ===== Listing 优化师 =====
    case 'keyword-miner':
      content = `🔑 **关键词挖掘完成** — 基于 **${result.seed_keywords?.join('、') || '-'}** 种子词\n\n` +
        `- 挖掘候选词：**${result.total_found || 0}** 个\n` +
        `- 🎯 高相关低竞争：${result.keywords?.filter((k: any) => k.competition === 'low' && k.relevance >= 85).length || 0} 个\n` +
        `- 📊 推荐立即投放：${result.keywords?.filter((k: any) => k.relevance >= 90).length || 0} 个\n\n` +
        `完整关键词列表和搜索量数据已展示在上方。`
      break
    case 'title-gen':
      if (result.is_simplified) {
        content = `📝 **短标题生成完成** — 为「**${result.product_name || '-'}**」生成 **${result.short_titles?.length || 0}** 个短标题方案\n\n` +
          `- 🥇 最佳方案：${result.short_titles?.[0]?.title || '-'}（${result.short_titles?.[0]?.char_count || 0} 字符）\n` +
          `- 商品详情章节：${result.detail_desc?.sections?.length || 0} 个\n\n` +
          `优化建议已展示在上方，可直接复制使用。`
      } else {
        content = `📝 **标题生成完成** — 为「**${result.product_name || '-'}**」生成 **${result.titles?.length || 0}** 个标题方案\n\n` +
          `- 🥇 最佳方案评分：${result.titles?.[0]?.score || 0} 分（SEO ${result.titles?.[0]?.seo_score || 0}）\n` +
          `- 字符范围：${Math.min(...(result.titles?.map((t: any) => t.char_count) || [0]))}-${Math.max(...(result.titles?.map((t: any) => t.char_count) || [0]))} 字符\n\n` +
          `优化建议已展示在上方，可直接复制使用。`
      }
      break
    case 'bullet-gen':
      content = `✨ **五点描述生成完成** — 共 **${result.bullets?.length || 0}** 条卖点\n\n` +
        `- 总字符数：${result.bullets?.reduce((s: number, b: any) => s + (b.char_count || 0), 0) || 0}\n` +
        `- 平均每条：${Math.round((result.bullets?.reduce((s: number, b: any) => s + (b.char_count || 0), 0) || 0) / (result.bullets?.length || 1))} 字符\n` +
        `- 格式规范：全大写括号关键词开头 ✅\n\n` +
        `每条 Bullet 已按 Amazon 最佳实践格式化。`
      break
    case 'desc-gen':
      content = `📄 **A+ 描述生成完成** — 「**${result.product_name || '-'}**」\n\n` +
        `- 包含模块：${result.description?.sections?.length || 0} 个章节\n` +
        `- 标题：${result.description?.title?.slice(0, 40) || '-'}...\n` +
        `- A+ 优化建议：${result.aplus_tips?.length || 0} 条\n\n` +
        `富文本描述内容已展示在上方，支持复制到后台。`
      break
    case 'seo-audit':
      content = `📊 **SEO 诊断完成** — 综合评分 **${result.grade}**（${result.overall_score || 0}/100）\n\n` +
        `- 🟢 优秀项：${result.categories?.filter((c: any) => c.status === 'good' || c.status === 'excellent').length || 0}\n` +
        `- 🟡 需改进：${result.categories?.filter((c: any) => c.status === 'warning').length || 0}\n` +
        `- 🔴 急需处理：${result.categories?.filter((c: any) => c.status === 'poor').length || 0}\n\n` +
        `${result.top_recommendations?.[0] || ''}`
      break
    case 'ab-test':
      content = `🧪 **A/B 测试方案生成完成** — 测试 ID：**${result.test_id}**\n\n` +
        `- 变体数量：${result.variants?.length || 0} 个\n` +
        `- 测试周期：${result.test_config?.duration_days || 14} 天\n` +
        `- 流量分配：${Object.entries(result.test_config?.traffic_split || {}).map(([k, v]) => `${k}=${v}%`).join(' / ')}\n` +
        `- 预计完成：${result.test_config?.estimated_completion || '-'}\n\n` +
        `假设：${result.hypothesis || '-'}`
      break
    // ===== 选品分析师 — 风险评估报告 =====
    case 'pitfalls_report':
      const rpt = result
      const sm = rpt.summary
      content = `## ${rpt.report_title}\n\n` +
        `> 🏪 目标平台：**${rpt.platform}** | 生成时间：${rpt.generated_at}\n\n` +
        `### 📋 基础产品信息\n\n` +
        `- **产品名称**：${rpt.product_info.name}\n` +
        `- **ASIN**：${rpt.product_info.asin}\n` +
        `- **核心关键词**：${(rpt.product_info.keywords || []).join(' / ') || '-'}\n` +
        `- **参考竞品**：${(rpt.product_info.competitor_asins || []).join('、') || '-'}\n\n` +
        `### ⚠️ 风险汇总总览\n\n` +
        `| 等级 | 数量 | 说明 |\n` +
        `|:---:|:---:|:---|\n` +
        `| 🔴 高危 | **${sm.high_count}** | 不建议开发，存在下架/封店/巨额赔偿风险 |\n` +
        `| 🟡 中风险 | **${sm.medium_count}** | 可做，但必须提前准备方案，评估额外成本 |\n` +
        `| 🟢 低风险 | **${sm.low_count}** | 风险可控，正常推进 |\n` +
        `| **综合评分** | **${sm.risk_score}/100** | ${sm.verdict}\n\n` +
        `---\n\n` +
        `### 🔍 逐条风险详情\n\n` +
        rpt.risks.map((r: any) =>
          `#### ${r.level_label} ${r.title}\n\n` +
          `> **类别**：${r.category_name}\n\n` +
          `**📌 风险说明**：${r.description}\n\n` +
          `**🔎 风险原因**：${r.reason}\n\n` +
          `**✅ 规避方案**：${r.solution}\n`
        ).join('\n\n---\n\n') +
        `\n\n---\n\n### 💡 最终建议\n\n${sm.verdict}`
      break
    // ===== AIGC 媒体生成器 =====
    case 'static-asset-gen': {
      const typeLabels: Record<string, string> = {
        'three-view': '白底三视图', 'detail': '细节特写', 'scene': '场景图',
        'lifestyle': '生活方式图', 'character': '人物场景图', 'storyboard-frame': '分镜首帧图',
      }
      const types = (result.generated_assets || []).map((a: any) => typeLabels[a.type] || a.type)
      content = `🎨 **静态素材生成完成** — 「**${result.product_name || '-'}**」\n\n` +
        `- 生成素材：**${result.generated_assets?.length || 0}** 张\n` +
        `- 素材类型：${types.length > 0 ? [...new Set(types)].join('、') : (result.params?.imageTypes || []).join('、')}\n` +
        `- 生成模式：图生图（${result.params?.source_image_name || '已上传原图'}）\n` +
        `- 风格：${result.params?.style || '专业棚拍'}\n\n` +
        `> 素材生成完毕，可点上方结果卡片的「归档到素材库」手动保存；归档后可分组管理、并在「AI 短视频生成」中选作首帧。`
      break
    }
    case 'video-script-gen': {
      const platformLabel: Record<string, string> = { tiktok: 'TikTok', reels: 'Reels', 'youtube-shorts': 'Shorts', 'amazon-post': 'Amazon Post' }
      const styleLabelMap: Record<string, string> = { 'problem-solution': '痛点驱动', 'product-showcase': '产品展示' }
      content = `🎬 **带货脚本 + 分镜表已生成** — 「**${result.product_name || '-'}**」\n\n` +
        `- 平台：${platformLabel[result.platform] || result.platform}｜风格：${styleLabelMap[result.video_style] || result.video_style}｜总时长 ${result.total_duration || 0}s\n` +
        `- 分镜数：**${result.storyboard?.length || 0}** 个镜头（每个镜头含画面/旁白/运镜/字幕，可人工编辑）\n\n` +
        `> 完整分镜表见上方卡片。脚本确认后，可切换到「AI 短视频生成」按首帧 + 运镜逐镜头出片。`
      break
    }
    case 'ai-video-generator':
      const modeLabelsMap: Record<string, string> = { 'single-image': '🖼️ 单图极速生成', 'storyboard-pro': '🎬 分镜脚本专业模式' }
      const avMode = result.mode || result.params?.mode || 'storyboard-pro'
      content = `🎥 **短视频生成完成** ✅ — ${modeLabelsMap[avMode] || result.mode_label || 'AI 短视频'}\n\n` +
        `- 生成模式：${result.mode_label || (avMode === 'single-image' ? '单图极速生成' : '分镜脚本专业模式')}\n` +
        (avMode === 'single-image'
          ? `- 底图 → 全自动绘制画面成片\n`
          : `- 镜头数：${result.clip_count || result.params?.storyboardScenes?.length || 0} 个片段（各镜独立生成后拼接）\n`) +
        `- 时长：${result.metadata?.duration || 0}s | 分辨率：${result.metadata?.resolution || '-'}\n` +
        `- 文件大小：${result.metadata?.file_size || '-'}\n\n` +
        `可点上方结果卡片的「归档到素材库」手动保存视频与关键帧。` +
        `视频已就绪，可预览或一键分发到各平台。`
      break
    // ===== 运营复盘师 =====
    case 'weekly-report':
      const wk = result.kpis
      content = `📋 **周报生成完成** — **${result.period || '-'}**\n\n` +
        `- 💰 营收：$${wk?.total_revenue?.value || 0}（${wk?.total_revenue?.change_pct > 0 ? '+' : ''}${wk?.total_revenue?.change_pct || 0}%）\n` +
        `- 📦 订单：${wk?.total_orders?.value || 0} 单\n` +
        `- 📈 ACoS：${wk?.acos?.value || 0}%${wk?.acos?.change_pct < 0 ? ' ↓' : ''}\n` +
        `- 🔄 转化率：${wk?.conversion_rate?.value || 0}%\n\n` +
        `亮点 ${result.highlights?.length || 0} 项 | 风险 ${result.concerns?.length || 0} 项`
      break
    case 'monthly-review':
      const es = result.executive_summary
      content = `📊 **月度复盘完成** — **${result.period || '-'}**\n\n` +
        `- 💰 GMV：$${es?.total_gmv || 0}（MoM ${es?.mom_change > 0 ? '+' : ''}${es?.mom_change || 0}%）\n` +
        `- 📈 净利率：${es?.net_margin || 0}%\n` +
        `- 📊 ACoS：${es?.blended_acos || 0}%\n` +
        `- TOP5 SKU 已排名，战略建议 ${result.strategic_recommendations?.length || 0} 条`
      break
    case 'ad-review':
      const ov = result.overview
      content = `📈 **广告复盘完成** — **${result.period || '-'}**\n\n` +
        `- 💰 总花费：$${ov?.total_spend || 0} | 销售：$${ov?.total_sales || 0}\n` +
        `- 📊 RoAS：**${ov?.blended_roas || 0}x** | ACoS：${ov?.blended_acos || 0}%\n` +
        `- Campaign 数：${result.campaign_breakdown?.length || 0} 个\n` +
        `- 可执行事项：${result.actionable_items?.length || 0} 条`
      break
    case 'product-performance':
      const ps = result.summary
      content = `🏆 **商品表现分析完成** — 共 **${ps?.total_skus || 0}** 个 SKU\n\n` +
        `- ⭐ 爆款：${ps?.star_products || 0} 个 | 📈 增长款：${ps?.rising || 0} 个\n` +
        `- 📉 下滑款：${ps?.declining || 0} 个 | ⚠️ 风险款：${ps?.at_risk || 0} 个\n` +
        `- 总营收：$${ps?.total_revenue || 0} | 均净利率：${ps?.avg_margin || 0}%\n` +
        `${result.alerts?.length ? `\n⚠️ ${result.alerts.length} 个预警` : ''}`
      break
    case 'inventory-health':
      content = `📦 **库存健康度检查完成** — 整体评分 **${result.overall_health_score || 0}/100**\n\n` +
        `- 🟢 健康：${result.inventory_items?.filter((i: any) => i.status === 'healthy').length || 0} 个\n` +
        `- 🔴 即将断货：${result.inventory_items?.filter((i: any) => i.status === 'critical').length || 0} 个\n` +
        `- 🟡 库存偏高：${result.inventory_items?.filter((i: any) => i.status === 'overstock').length || 0} 个\n` +
        `- ⚠️ 周转过慢：${result.inventory_items?.filter((i: any) => i.status === 'slow_moving').length || 0} 个\n` +
        `- 预估长期仓储费：$${result.financial_impact?.estimated_long_term_storage_fee || 0}`
      break
    case 'profit-audit':
      const pnl = result.pnl_summary
      content = `💰 **利润审计完成** — **${result.period || '-'}**\n\n` +
        `- 💵 总营收：$${pnl?.total_revenue || 0}\n` +
        `- 📊 毛利率：${pnl?.gross_margin || 0}% | 净利率：**${pnl?.net_margin || 0}%**\n` +
        `- 🏆 净利润：$${pnl?.net_profit || 0}\n` +
        `- SKU 盈亏分析：${result.profitability_by_sku?.length || 0} 个\n` +
        `${result.profitability_by_sku?.some((s: any) => s.net_margin < 0) ? '\n⚠️ 存在亏损 SKU，需重点关注' : ''}`
      break
    case 'action-plan':
      const ap = result.summary
      content = `🎯 **行动计划已生成** — **${result.period || '-'}**\n\n` +
        `- 🔴 止损项（立即）：${result.stop_loss?.length || 0} 个\n` +
        `- 🟡 优化项（进行中）：${result.optimize?.length || 0} 个\n` +
        `- 🟢 机会点（增长）：${result.opportunity?.length || 0} 个\n` +
        `- 📈 预估影响：**${ap?.estimated_impact || '-'}**`
      break
  }

  chatStore.addMessage({
    role: 'assistant',
    content,
    data: result,
  })
}

// ========== 聊天功能 ==========

// 渲染 Markdown
const renderMarkdown = (content: string) => md.render(content)

// 键盘事件
const handleKeyPress = (e: KeyboardEvent) => {
  if (!e.shiftKey && e.key === 'Enter') {
    e.preventDefault()
    handleSend()
  }
}

// 发送消息
const handleSend = async () => {
  const text = inputMessage.value.trim()
  if (!text || isLoading.value) return

  if (!agentStore.currentAgent) {
    message.warning('请先在左侧选择一个 Agent')
    return
  }

  chatStore.addMessage({ role: 'user', content: text })
  inputMessage.value = ''
  isLoading.value = true

  try {
    await simulateAgentResponse(text)
  } catch (error) {
    message.error('发送失败，请重试')
  } finally {
    isLoading.value = false
  }
  await scrollToBottom()
}

// Agent 响应处理（复用原有逻辑）
const simulateAgentResponse = async (userMessage: string) => {
  // 选品分析师
  if (agentStore.currentAgent?.id === 'product-research') {
    try {
      const { chatWithProductResearcher } = await import('@/api/productResearch')
      const response = await chatWithProductResearcher({ message: userMessage })

      chatStore.addMessage({
        role: 'assistant',
        content: response.reply || '分析完成',
        data: response.data,
        displayType: response.display_type || 'text',
      })

      if (response.data) {
        useResultStore().setResultData(response.data, response.display_type)
      }
      return
    } catch (error) {
      console.error('选品 API 失败:', error)
    }
  }

  // Listing 优化师
  if (agentStore.currentAgent?.id === 'listing-generator') {
    try {
      const { chatWithListingAgent, generateListing } = await import('@/api/listingGenerator')
      const isGenerateRequest =
        userMessage.includes('生成') || userMessage.includes('写') ||
        userMessage.includes('创建') || userMessage.toLowerCase().includes('generate')

      let response: any
      if (isGenerateRequest) {
        response = await generateListing({
          product_name: userMessage.replace(/生成|写|创建|listing|Listing/gi, '').trim() || 'New Product',
          generate_ab_variants: false,
        })
        response = response.data
      } else {
        response = await chatWithListingAgent({ message: userMessage })
        response = response.data
      }

      chatStore.addMessage({
        role: 'assistant',
        content: response.summary || response.response || '完成',
        data: response,
        displayType: response.type || 'complete_listing',
      })

      if (response.listing || response.type) {
        useResultStore().setResultData(response, response.type)
      }
      return
    } catch (error) {
      console.error('Listing API 失败:', error)
    }
  }

  // 广告分析师
  if (agentStore.currentAgent?.id === 'ad-analysis') {
    try {
      const { chatWithAdAnalyst, diagnoseAdAccount, analyzeSearchTerms, detectAnomalies } = await import('@/api/adAnalysis')

      // 判断是否是特定功能请求
      const isDiagnosis = /诊断|体检|健康|状况/.test(userMessage)
      const isSearchTerms = /搜索词|词报告|关键词|search term/.test(userMessage)
      const isAnomaly = /异常|突然|骤降|突增|anomaly/.test(userMessage)

      let response: any

      if (isDiagnosis) {
        response = await diagnoseAdAccount({ time_range: '30d' })
        response = response.data
      } else if (isSearchTerms) {
        response = await analyzeSearchTerms({})
        response = response.data
      } else if (isAnomaly) {
        response = await detectAnomalies({ check_period: '7d' })
        response = response.data
      } else {
        // 默认走对话接口
        response = await chatWithAdAnalyst({ message: userMessage })
        response = response.data
      }

      chatStore.addMessage({
        role: 'assistant',
        content: response.reply || response.summary || '分析完成',
        data: response.data || response,
        displayType: response.display_type || (isDiagnosis ? 'ad_diagnosis' : undefined),
      })

      if (response.data || response.metrics || response.anomalies) {
        useResultStore().setResultData(response.data || response, response.display_type || 'ad_diagnosis')
      }
      return
    } catch (error) {
      console.error('广告分析 API 失败:', error)
    }
  }

  // 智能客服
  if (agentStore.currentAgent?.id === 'customer-service') {
    try {
      const { chatWithCustomerService, trackOrder, createTicket } = await import('@/api/customerService')

      // 判断是否是订单追踪
      const isOrderTrack = /订单|order|物流|tracking|到哪里/.test(userMessage)
      // 判断是否是工单创建
      const isTicketCreate = /工单|投诉|问题|ticket|创建/.test(userMessage)

      let response: any

      if (isOrderTrack) {
        // 提取订单号
        const orderMatch = userMessage.match(/ORD[-–]?\d{8,}|(\d{10,})/i)
        const orderId = orderMatch ? orderMatch[0] : undefined
        response = await trackOrder({ order_id: orderId })
        response = response.data
      } else if (isTicketCreate) {
        response = await createTicket({
          subject: userMessage.slice(0, 50),
          description: userMessage,
          category: 'general',
        })
        response = response.data
      } else {
        // 默认走对话接口
        response = await chatWithCustomerService({ message: userMessage })
        response = response.data
      }

      chatStore.addMessage({
        role: 'assistant',
        content: response.reply || response.message || '处理完成',
        data: response.data || response,
        displayType: response.display_type || 'text',
      })

      // 特殊展示类型
      if (response.display_type === 'order_info' || response.order) {
        useResultStore().setResultData(response.order || response, 'order_info')
      } else if (response.data) {
        useResultStore().setResultData(response.data, response.display_type)
      }
      return
    } catch (error) {
      console.error('客服 API 失败:', error)
    }
  }

  // 竞品监控员：自然语言 → 基于监控池 mock 推理（第 3 层推理层）
  if (agentStore.currentAgent?.id === 'competitor-intel') {
    try {
      const m = await import('@/mock/competitorIntel')
      const out = m.analyzeCompetitorIntel(userMessage)
      chatStore.addMessage({
        role: 'assistant',
        content: out.reply,
        data: out.evidence,
        displayType: 'competitor_intel_analysis',
      })
      return
    } catch (error) {
      console.error('竞品监控推理失败:', error)
    }
  }

  // 选品分析师：若已「载入选品」→ 针对该候选做静态快照可行性；未载入 → 走默认回复引导载入
  if (agentStore.currentAgent?.id === 'product-research' && loadedCandidate.value) {
    try {
      await ensureCandidateLoaded()
      const { analyzeCandidateSelection } = await import('@/mock/competitorIntel')
      const reply = analyzeCandidateSelection([loadedCandidate.value])
      chatStore.addMessage({ role: 'assistant', content: reply })
      return
    } catch (error) {
      console.error('选品分析师候选评估失败:', error)
    }
  }

  // 运营复盘师：点击快捷卡片（周报/月度复盘/广告优化/行动计划）→ 基于右侧数据看板生成结构化复盘 mock
  if (agentStore.currentAgent?.id === 'review-analyst') {
    try {
      const m = await import('@/mock/reviewDashboard')
      const intent = /本月|月度/.test(userMessage) ? 'monthly'
        : /广告/.test(userMessage) ? 'ad'
        : /行动计划|止损项/.test(userMessage) ? 'action'
        : 'weekly'
      const out = m.buildReviewReply(intent)
      chatStore.addMessage({ role: 'assistant', content: out.reply, displayType: out.displayType || 'text' })
      return
    } catch (error) {
      console.error('运营复盘生成失败:', error)
    }
  }

  // 默认模拟响应
  await new Promise(resolve => setTimeout(resolve, 800))
  const tip = agentStore.currentAgent?.id === 'competitor-intel'
    ? `> 💡 提示：可点下方「竞品周报 / 异动洞察 / 策略推演」生成针对性分析。`
    : agentStore.currentAgent?.id === 'product-research'
      ? `> 💡 提示：先在顶部点击 **【载入选品】** 选定评估对象，再点下方「市场可行性 / 上架建议」，或直接提问。`
      : `> 💡 提示：可以使用上方的工具卡片获得更精准的分析结果。`
  chatStore.addMessage({
    role: 'assistant',
    content: `收到：「${userMessage}」\n\n我是 **${agentStore.currentAgent?.name}**，正在为您分析...\n\n${tip}`,
  })
}

// HITL 审批
const handleHitlAccept = async (msg: any) => {
  message.success('已批准执行')
}
const handleHitlReject = async (msg: any) => {
  message.info('已拒绝执行')
}

// 滚动到底部
const scrollToBottom = async () => {
  await nextTick()
  const target = messageListRef.value || mainContentRef.value
  if (target) target.scrollTop = target.scrollHeight
}

watch(messages, () => scrollToBottom(), { deep: true })
</script>

<style scoped>
.chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-elevated);
  overflow: hidden;
}

/* 主内容区域（唯一滚动容器） */
.main-content {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  min-height: 0; /* 关键：允许 flex 子项收缩 */
}

/* 工具结果消息（内联在对话流中） */
.tool-result-message {
  flex-direction: column;
  gap: 0;
  margin-bottom: 16px;
}

.tool-result-content {
  max-width: 100%;
  padding: 0;
  background: transparent;
  border-radius: 8px;
  overflow: hidden;
}

/* 兜底：无专用 Result 组件的工具显示 JSON */
.raw-result-fallback {
  padding: 12px 16px;
}

.result-json-preview {
  background: var(--bg-hover-light);
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 消息列表（不再独立滚动，随 main-content 一起滚动） */
.message-list {
  flex: 1;
  padding: 16px 24px;
}

.empty-state {
  height: 100%;
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
}

.empty-state .hint {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-disabled);
}

/* 消息项 */
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 12px;
  background-color: var(--bg-hover-light);
}

.message-item.user .message-content {
  background-color: var(--bg-active-light);
}

.message-text {
  line-height: 1.6;
  word-break: break-word;
}

.hitl-card {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background-color: var(--bg-hover-light);
}

/* 竞品监控员·统一分析动作条（输入框上方） */
.intel-action-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 8px 24px;
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-base);
}
.iab-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.iab-scope { margin: 0; font-size: 11px; }
.iab-scope-float { margin: 0; font-size: 11px; }
.iab-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.iab-period { display: flex; align-items: center; gap: 6px; }
.iab-period-label { font-size: 12px; color: var(--text-tertiary); white-space: nowrap; }
.iab-chips { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.iab-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 14px;
  border-radius: 15px;
  border: 1px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.18s ease;
}
.iab-chip:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); background: var(--bg-active-light); }
.iab-chip.active {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.25);
}
.iab-chip:disabled { opacity: 0.5; cursor: not-allowed; }
.iab-chip-icon { font-size: 14px; line-height: 1; }

/* 运营复盘师·快捷 chip 正在执行时的脉冲提示（复用 iab-chip 布局） */
.iab-chip.rqa-loading {
  border-color: var(--primary);
  background: rgba(24, 144, 255, 0.08);
  color: var(--primary);
  animation: rqa-pulse 1.2s ease-in-out infinite;
}
@keyframes rqa-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(24, 144, 255, 0.25); }
  50% { box-shadow: 0 0 0 6px rgba(24, 144, 255, 0); }
}

/* 输入区域（卡片式，冻结在底部） */
.input-area {
  padding: 10px 24px 14px;
  flex-shrink: 0;
  border-top: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
}

.input-card {
  background-color: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: 10px;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.06);
  padding: 10px 14px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.input-card:focus-within {
  border-color: var(--primary);
  box-shadow: 0 1px 8px rgba(24, 144, 255, 0.15);
}

.chat-textarea {
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  resize: none;
  font-size: 14px;
  line-height: 1.6;
}

.chat-textarea:focus {
  box-shadow: none !important;
}

.input-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding-top: 6px;
}

.input-hint {
  font-size: 11px;
  color: var(--text-disabled);
  user-select: none;
}
</style>

<template>
  <div class="chat-panel">
    <!-- ===== 主内容区域（对话 + 结果共存） ===== -->
    <div class="main-content" ref="mainContentRef">
      <!-- 最近结果条：对话是线性流，结论会被后来的消息冲出视野、清空会话更会全丢；
           这里按 agentId 存一份最近结论，随时可找回（展开即为结论卡） -->
      <div v-if="recentForCurrentAgent" class="recent-result-bar">
        <span class="rrb-label">📌 最近结果</span>
        <span class="rrb-summary" :title="recentForCurrentAgent.summary">
          {{ recentForCurrentAgent.summary || '（无摘要）' }}
        </span>
        <button
          class="rrb-btn"
          :disabled="!recentComponent"
          @click="recentExpanded = !recentExpanded"
        >
          {{ recentExpanded ? '收起' : '查看' }}
        </button>
        <button class="rrb-btn rrb-close" title="清除最近结果" @click="clearRecentResult">×</button>
      </div>
      <div
        v-if="recentForCurrentAgent && recentExpanded && recentComponent"
        class="recent-result-body"
      >
        <component :is="recentComponent" :data="recentForCurrentAgent.data" />
      </div>

      <!-- 店秘书「当前计划」（第 155 轮）：它是**会话级状态**、不是某条消息的
           附件（后端刻意把计划放在图状态而非消息序列里，好让它不随历史裁剪
           丢失），所以这里独立于消息流渲染在列表上方 —— 对话滚到哪都看得见。
           详见 PlanChecklist.vue 头注释。 -->
      <PlanChecklist :plan="secretaryPlan" />

      <!-- 对话消息区域（始终显示） -->
      <div class="message-list" ref="messageListRef">
          <div v-if="messages.length === 0 && !agentStore.currentAgent" class="empty-state">
            <RobotOutlined style="font-size: var(--font-size-48); color: var(--text-tertiary); margin-bottom: var(--space-16)" />
            <p>选择一个 Agent 开始对话</p>
            <p class="hint">或从顶部工具栏选择功能</p>
          </div>

          <div v-else-if="messages.length === 0 && agentStore.currentAgent" class="empty-state">
            <span style="font-size: var(--font-size-48)">{{ agentStore.currentAgent.icon?.render?.() || '🤖' }}</span>
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
              <a-avatar style="background-color: var(--success)">AI</a-avatar>
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
                  <a-alert type="success" show-icon :message="`${msg.data?.toolName || '复盘'} 报告生成完成`" style="margin-bottom: var(--space-8)" />
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
              :class="['message-item', msg.role, { 'has-conversation-result': !!resolveConversationResult(msg.displayType) }]"
            >
            <a-avatar
              :style="{ backgroundColor: msg.role === 'user' ? SEM.primary : SEM.success }"
            >
              {{ msg.role === 'user' ? 'U' : 'AI' }}
            </a-avatar>
            <div class="message-content">
              <div class="message-text" v-html="renderMarkdown(msg.content)"></div>

              <!-- 会话结论卡：对话直接跑出的结构化结论（后端 SSE meta 下发），
                   与工具结果卡**同区、同规则**——都在对话消息流里、都查表渲染，
                   只是轻量只读。正文已自带清单，卡片是同一份结论的结构化承托。 -->
              <component
                v-if="resolveConversationResult(msg.displayType)"
                :is="resolveConversationResult(msg.displayType)"
                :data="msg.data"
              />

              <!-- 竞品监控员：推理证据联动卡（数据底座背书 AI 解读） -->
              <CompetitorIntelEvidence
                v-if="msg.displayType === 'competitor_intel_analysis' && msg.data?.per_asin?.length"
                :data="msg.data"
              />

            </div>
          </div>
          </div>

          <!-- 加载中：tip 显示后端阶段进度 + 已用时长，长任务期间不再是干转圈 -->
          <div v-if="isLoading" class="message-item assistant">
            <a-avatar style="background-color: var(--success)">AI</a-avatar>
            <div class="message-content">
              <a-spin :tip="loadingTip" />
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
            <span class="input-hint">{{ footerHint }}</span>
            <div class="input-actions">
              <!-- 增强提示词：把草稿扩写成更可执行的提示词 -->
              <a-tooltip :title="enhanceTip">
                <button
                  class="input-action-btn"
                  :disabled="enhancing || !inputMessage.trim()"
                  @click="handleEnhance"
                >
                  <LoadingOutlined v-if="enhancing" />
                  <svg v-else class="sparkle-icon" viewBox="0 0 22 22" width="16" height="16" aria-hidden="true">
                    <path d="M9 3 C9.36 7.2 9.8 7.64 14 8 C9.8 8.36 9.36 8.8 9 13 C8.64 8.8 8.2 8.36 4 8 C8.2 7.64 8.64 7.2 9 3 Z" />
                    <path d="M17 12.5 C17.2 14.8 17.45 15.05 19.75 15.25 C17.45 15.45 17.2 15.7 17 18 C16.8 15.7 16.55 15.45 14.25 15.25 C16.55 15.05 16.8 14.8 17 12.5 Z" />
                  </svg>
                </button>
              </a-tooltip>
              <!-- 语音输入：浏览器原生识别，不支持时点击给出原因（不静默失效） -->
              <a-tooltip :title="speechTip">
                <button
                  class="input-action-btn"
                  :class="{
                    'is-listening': speechState.listening,
                    'is-unsupported': !speechState.supported,
                  }"
                  @click="handleToggleSpeech"
                >
                  <AudioOutlined />
                </button>
              </a-tooltip>
              <!-- 发送：Enter 亦可。圆形容器交给 antd —— 主色底上的前景色由算法决定，
                   避免自己写死白字（presets 里 --text-inverse 深色下是深色，语义不符） -->
              <a-button
                class="input-send-btn"
                type="primary"
                shape="circle"
                title="发送（Enter）"
                :disabled="!inputMessage.trim() || isLoading"
                @click="handleSend"
              >
                <template #icon>
                  <LoadingOutlined v-if="isLoading" />
                  <ArrowUpOutlined v-else />
                </template>
              </a-button>
            </div>
          </div>
        </div>
      </div>
    </div>
</template>

<script setup lang="ts">
import { SEM } from '@/theme/semantic'
import { ref, computed, watch, inject, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { RobotOutlined, AudioOutlined, ArrowUpOutlined, LoadingOutlined } from '@ant-design/icons-vue'

// 输入框辅助：提示词增强（走后端 LLM）+ 语音输入（浏览器原生识别）
import { enhancePrompt } from '@/api/aigcMedia'
import {
  speechState,
  speechUnsupportedReason,
  speechErrorText,
  toggleSpeech,
  stopSpeech,
  clearSpeechError,
} from '@/composables/useSpeechInput'

import { useAgentStore } from '@/stores/agent'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { useShopStore } from '@/stores/shop'

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

// 店秘书「当前计划」条（第 155 轮 · 批 C3 的前端消费端）
import PlanChecklist from './PlanChecklist.vue'

// 会话结论卡（display_type → 组件映射表）与「最近结果」槽
import { resolveConversationResult } from './results/conversation/registry'
import { useRecentResultStore } from '@/stores/recentResult'

// 编排层：发送链路 / 工具分析 / 快捷 chip / HITL（S3 拆分）
import { useChatOrchestrator } from '@/composables/useChatOrchestrator'

// ===== 模板直接引用的 store（Agent 判定与 scope tag 用）=====
const agentStore = useAgentStore()
const pool = useMonitorPoolStore()
const shopStore = useShopStore()

// ===== 无法搬入 composable 的三类绑定（必须由组件持有）=====
// 1) v-model 绑定的 ref —— 若改由 composable 拥有，v-model 会退化成给 const 赋值
const inputMessage = ref('')
const intelDays = ref(30)
// 2) 模板 ref —— 只在模板里声明
const messageListRef = ref<HTMLElement>()
const mainContentRef = ref<HTMLElement>()
// 3) inject 注入值 —— 只能在组件 setup 中 inject（选品分析师评估主角）
const loadedCandidate = inject<Ref<any>>('workingCandidate', ref(null))

// ===== 会话结论卡 + 最近结果：对话结果的「卡片承托」与「找回入口」=====
// 结论卡渲染在消息流内（与工具结果卡同区）；最近结果按 agentId 独立存活，
// 因此「清空对话」不会连带清掉结论，随时可从顶部条找回。
const recentResultStore = useRecentResultStore()
const currentAgentId = computed(() => agentStore.currentAgent?.id || 'default')
const recentForCurrentAgent = computed(() => recentResultStore.getRecent(currentAgentId.value))
const recentComponent = computed(() =>
  resolveConversationResult(recentForCurrentAgent.value?.displayType),
)
const recentExpanded = ref(false)

// 切换 Agent 时收起展开态，避免把 A 的结论当成 B 的展开着
watch(currentAgentId, () => {
  recentExpanded.value = false
})

function clearRecentResult() {
  recentResultStore.clearRecent(currentAgentId.value)
  recentExpanded.value = false
}

// 其余全部编排逻辑下沉到 composable，此处仅解构模板所需出口
const {
  // 店秘书计划（第 155 轮）
  secretaryPlan,
  // 状态
  messages,
  isLoading,
  loadingTip,
  inputPlaceholder,
  // Agent 判定
  isCompetitorIntelAgent,
  isProductResearchAgent,
  isListingAgent,
  isReviewAgent,
  isAdAnalyst,
  // 竞品监控动作条
  intelChips,
  periodOptions,
  activeIntelChip,
  runIntelChip,
  // 选品分析动作条
  candidateIntelChips,
  runCandidateChip,
  // 运营复盘动作条
  REVIEW_ACTIONS,
  activeReviewAction,
  runReviewAction,
  reviewScopeColor,
  reviewScopeText,
  // 广告分析动作条
  AD_QUICK_ACTIONS,
  activeAdAction,
  runAdQuickAction,
  // 消息 / 输入 / 渲染
  removeToolResult,
  handleNavigateTo,
  renderMarkdown,
  handleKeyPress,
  handleSend,
} = useChatOrchestrator({
  inputMessage,
  messageListRef,
  mainContentRef,
  intelDays,
  loadedCandidate,
})

// AIGC 工具结果（静态素材 / 短视频脚本 / AI 视频）新进入消息流时，
// 广播 aigc-result-ready 给右栏 AIGCMediaWrapper —— 触发「自动切大屏模式 + 大屏显示本次结果」。
// AIGCMediaWrapper 在 onBeforeUnmount 已移除监听，无需担心泄漏。
const AIGC_TOOLS = ['static-asset-gen', 'video-script-gen', 'ai-video-generator']
watch(messages, (newMsgs, oldMsgs) => {
  const oldIds = new Set((oldMsgs || []).map((m: any) => m?.id).filter(Boolean))
  for (const m of newMsgs) {
    const mm = m as any
    if (!mm?.id || oldIds.has(mm.id)) continue
    const d = mm.data
    if (!d?.toolId || !AIGC_TOOLS.includes(d.toolId)) continue
    if (!d.resultData) continue
    window.dispatchEvent(new CustomEvent('aigc-result-ready', {
      detail: { toolId: d.toolId, result: d.resultData }
    }))
  }
}, { deep: false })

// ===== 输入框辅助：增强提示词 + 语音输入 =====
// 两个入口的共同点是**不替用户做决定**：增强只补维度、不改原意，
// 语音只做转写、不改字。所以它们都不自动发送，改完仍由用户按 Enter 决定。

const enhancing = ref(false)

/** 底部提示：收音中要让位给录音状态，否则用户不知道还在录 */
const footerHint = computed(() =>
  speechState.listening ? '正在听… 说完点麦克风结束' : 'Enter 发送 · Shift+Enter 换行',
)

const enhanceTip = computed(() => {
  if (enhancing.value) return '正在增强…'
  if (!inputMessage.value.trim()) return '先写一句需求，再点这里增强'
  return '增强提示词：补齐任务目标 / 约束条件 / 输出形式'
})

const speechTip = computed(() => {
  if (!speechState.supported) return speechUnsupportedReason.value
  return speechState.listening ? '结束录音' : '语音输入（说话转文字）'
})

async function handleEnhance() {
  const draft = inputMessage.value.trim()
  if (!draft || enhancing.value) return
  enhancing.value = true
  try {
    const res = await enhancePrompt({ draft })
    const data = res?.response
    // 后端 LLM 不可用时显式给 degraded —— 此时**保持用户输入原样**，不覆盖
    if (data?.degraded || !data?.enhanced) {
      message.warning('提示词增强暂不可用，请稍后重试')
      return
    }
    inputMessage.value = data.enhanced
    message.success('已增强，可直接发送或继续修改')
  } catch (e) {
    message.warning('提示词增强暂不可用，请稍后重试')
  } finally {
    enhancing.value = false
  }
}

function handleToggleSpeech() {
  if (!speechState.supported) {
    // 不静默失效：明确告诉用户为什么不能用
    message.warning(speechUnsupportedReason.value)
    return
  }
  toggleSpeech({
    base: inputMessage.value,
    // 回填的是**完整文本**（既有内容 + 已确认 + 临时），直接赋给 v-model
    onText: (text) => {
      inputMessage.value = text
    },
  })
}

// 语音错误只提示一次，提示完清掉错误码，避免反复弹
watch(
  () => speechState.error,
  (code) => {
    if (!code) return
    const text = speechErrorText.value
    if (text) message.warning(text)
    clearSpeechError()
  },
)

// 切 Agent 时停掉录音：否则上一段话会被灌进新会话的输入框
watch(currentAgentId, () => {
  if (speechState.listening) stopSpeech()
})
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

/* ===== 最近结果条（中列顶部）：结论被冲走 / 会话被清空后的找回入口 ===== */
.recent-result-bar {
  position: sticky;
  top: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: var(--space-8);
  padding: var(--space-6) var(--space-24);
  background: var(--bg-toolbar);
  border-bottom: 1px solid var(--border-base);
  font-size: var(--font-size-12);
}

.rrb-label {
  flex: none;
  font-weight: 600;
  color: var(--text-secondary);
}

.rrb-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-tertiary);
}

.rrb-btn {
  flex: none;
  height: 22px;
  padding: 0 var(--space-8);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-4);
  background: transparent;
  color: var(--primary);
  font-size: var(--font-size-12);
  line-height: 1;
  cursor: pointer;
}

.rrb-btn:hover:not(:disabled) {
  border-color: var(--primary);
}

.rrb-btn:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.rrb-close {
  padding: 0 var(--space-6);
  color: var(--text-tertiary);
}

.recent-result-body {
  padding: 0 var(--space-24) var(--space-8);
}

/* 带会话结论卡的消息：放宽气泡宽度，给结构化卡片留出横向空间 */
.message-item.has-conversation-result .message-content {
  max-width: 100%;
  flex: 1;
}

/* 工具结果消息（内联在对话流中） */
.tool-result-message {
  flex-direction: column;
  gap: 0;
  margin-bottom: var(--space-16);
}

.tool-result-content {
  max-width: 100%;
  padding: 0;
  background: transparent;
  border-radius: var(--radius-8);
  overflow: hidden;
}

/* 兜底：无专用 Result 组件的工具显示 JSON */
.raw-result-fallback {
  padding: var(--space-12) var(--space-16);
}

.result-json-preview {
  background: var(--bg-hover-light);
  border-radius: var(--radius-6);
  padding: var(--space-12);
  font-size: var(--font-size-12);
  line-height: 1.5;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 消息列表（不再独立滚动，随 main-content 一起滚动） */
.message-list {
  flex: 1;
  padding: var(--space-16) var(--space-24);
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
  margin-top: var(--space-8);
  font-size: var(--font-size-13);
  color: var(--text-disabled);
}

/* 消息项 */
.message-item {
  display: flex;
  gap: var(--space-12);
  margin-bottom: var(--space-20);
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
  padding: var(--space-12) var(--space-16);
  border-radius: var(--radius-12);
  background-color: var(--bg-hover-light);
}

.message-item.user .message-content {
  background-color: var(--bg-active-light);
}

.message-text {
  line-height: 1.6;
  word-break: break-word;
}

/* markdown 渲染出的清单（v-html 内容不带 scoped 属性，必须走 :deep） */
.message-text :deep(ol),
.message-text :deep(ul) {
  margin: var(--space-6) 0;
  padding-left: var(--space-20);
}
.message-text :deep(li) {
  margin: var(--space-4) 0;
}
.message-text :deep(ol li::marker) {
  color: var(--text-secondary, #8c8c8c);
  font-weight: 600;
}
.message-text :deep(li > ul) {
  margin: var(--space-2) 0;
  padding-left: var(--space-16);
}
.message-text :deep(li > ul li) {
  color: var(--text-secondary, #8c8c8c);
  font-size: 0.92em;
}
.message-text :deep(strong) {
  font-weight: 600;
}

/* 竞品监控员·统一分析动作条（输入框上方） */
.intel-action-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
  flex-wrap: wrap;
  padding: var(--space-8) var(--space-24);
  background: var(--bg-elevated);
  border-top: 1px solid var(--border-base);
}
.iab-label {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  font-size: var(--font-size-13);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.iab-scope { margin: 0; font-size: var(--font-size-11); }
.iab-scope-float { margin: 0; font-size: var(--font-size-11); }
.iab-controls {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  flex-wrap: wrap;
  justify-content: flex-end;
}
.iab-period { display: flex; align-items: center; gap: var(--space-6); }
.iab-period-label { font-size: var(--font-size-12); color: var(--text-tertiary); white-space: nowrap; }
.iab-chips { display: flex; gap: var(--space-8); align-items: center; flex-wrap: wrap; }
.iab-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-6);
  height: 28px;
  padding: 0 var(--space-14);
  border-radius: var(--radius-15);
  border: 1px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: var(--font-size-13);
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
.iab-chip-icon { font-size: var(--font-size-14); line-height: 1; }

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
  padding: var(--space-10) var(--space-24) var(--space-14);
  flex-shrink: 0;
  border-top: 1px solid var(--border-base);
  background-color: var(--bg-elevated);
}

.input-card {
  background-color: var(--bg-elevated);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-10);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.06);
  padding: var(--space-10) var(--space-14);
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
  font-size: var(--font-size-14);
  line-height: 1.6;
}

.chat-textarea:focus {
  box-shadow: none !important;
}

.input-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-6);
  padding-top: var(--space-6);
}

.input-hint {
  font-size: var(--font-size-11);
  color: var(--text-disabled);
  user-select: none;
}

/* ===== 右下角动作区：增强提示词 / 语音输入 / 发送 ===== */
.input-actions {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

/* 图标按钮（增强 / 语音）：无边框圆形，hover 才出底色，保持输入区安静 */
.input-action-btn {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  border-radius: var(--radius-circle);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-16);
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s, opacity 0.2s;
}

.input-action-btn:hover:not(:disabled) {
  background: var(--bg-hover-light);
  color: var(--primary);
}

.input-action-btn:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

/* 浏览器不支持语音时置灰，但仍可点击 —— 点击会说明原因，比静默失效好 */
.input-action-btn.is-unsupported {
  opacity: 0.4;
}

/* 收音中：用 danger 的浅底 + 前景色（两侧都是变量），不用实心红避免自己写死白字 */
.input-action-btn.is-listening {
  color: var(--danger);
  background: var(--danger-bg);
  animation: speech-pulse 1.4s ease-in-out infinite;
}

@keyframes speech-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}

@media (prefers-reduced-motion: reduce) {
  .input-action-btn.is-listening {
    animation: none;
  }
}

/* 星芒图标：路径不填色，跟随 button 的 color */
.sparkle-icon {
  fill: currentColor;
}

/* 发送按钮由 antd 提供配色（主色底 + 算法决定的前景色），这里只协调布局 */
.input-send-btn {
  flex: none;
}
</style>

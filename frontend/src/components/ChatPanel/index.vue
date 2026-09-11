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
import { ref, inject, type Ref } from 'vue'
import { SendOutlined, RobotOutlined } from '@ant-design/icons-vue'

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

// 其余全部编排逻辑下沉到 composable，此处仅解构模板所需出口
const {
  // 状态
  messages,
  isLoading,
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
  handleHitlAccept,
  handleHitlReject,
} = useChatOrchestrator({
  inputMessage,
  messageListRef,
  mainContentRef,
  intelDays,
  loadedCandidate,
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

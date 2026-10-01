<template>
  <div class="chat-panel">
    <!-- ===== 主内容区域（对话 + 结果共存） ===== -->
    <div
      ref="mainContentRef"
      class="main-content"
      data-tour="tour-chat-stream"
    >
      <!-- 最近结果条：对话是线性流，结论会被后来的消息冲出视野、清空会话更会全丢；
           这里按 agentId 存一份最近结论，随时可找回（展开即为结论卡） -->
      <div
        v-if="recentForCurrentAgent"
        class="recent-result-bar"
      >
        <span class="rrb-label">📌 最近结果</span>
        <span
          class="rrb-summary"
          :title="recentForCurrentAgent.summary"
        >
          {{ recentForCurrentAgent.summary || '（无摘要）' }}
        </span>
        <button
          class="rrb-btn"
          :disabled="!recentComponent"
          @click="recentExpanded = !recentExpanded"
        >
          {{ recentExpanded ? '收起' : '查看' }}
        </button>
        <button
          class="rrb-btn rrb-close"
          title="清除最近结果"
          @click="clearRecentResult"
        >
          ×
        </button>
      </div>
      <div
        v-if="recentForCurrentAgent && recentExpanded && recentComponent"
        class="recent-result-body"
      >
        <component
          :is="recentComponent"
          :data="recentForCurrentAgent.data"
        />
      </div>

      <!-- 店秘书「当前计划」（第 155 轮）：它是**会话级状态**、不是某条消息的
           附件（后端刻意把计划放在图状态而非消息序列里，好让它不随历史裁剪
           丢失），所以这里独立于消息流渲染在列表上方 —— 对话滚到哪都看得见。
           详见 PlanChecklist.vue 头注释。 -->
      <PlanChecklist :plan="secretaryPlan" />

      <!-- 对话消息区域（始终显示） -->
      <div
        ref="messageListRef"
        class="message-list"
      >
        <div
          v-if="messages.length === 0 && !agentStore.currentAgent"
          class="empty-state"
        >
          <RobotOutlined style="font-size: var(--font-size-48); color: var(--text-tertiary); margin-bottom: var(--space-16)" />
          <p>选择一个 Agent 开始对话</p>
          <p class="hint">
            或从顶部工具栏选择功能
          </p>
        </div>

        <div
          v-else-if="messages.length === 0 && agentStore.currentAgent"
          class="empty-state"
        >
          <span style="font-size: var(--font-size-48)">{{ agentStore.currentAgent.icon?.render?.() || '🤖' }}</span>
          <p>{{ agentStore.currentAgent.name }} 已就绪</p>
          <p
            v-if="isCompetitorIntelAgent"
            class="hint"
          >
            在右侧圈选竞品后，点下方「竞品周报 / 异动洞察 / 策略推演」或直接提问
          </p>
          <p
            v-else-if="isProductResearchAgent"
            class="hint"
          >
            先在顶部「载入选品」选定候选，再点下方「市场可行性 / 上架建议 / 痛点分析 / 选品避坑 / 竞品对比」任一评估
          </p>
          <p
            v-else-if="isListingAgent"
            class="hint"
          >
            先在顶部「载入产品」选定要优化的商品，再点下方「SEO 诊断」诊断其 Listing 或从顶部工具栏生成文案
          </p>
          <p
            v-else
            class="hint"
          >
            输入问题或点击顶部工具栏开始分析
          </p>
        </div>

        <div
          v-for="(msg, index) in messages"
          :key="index"
          :data-msg-index="index"
        >
          <!-- ===== 工具结果消息（内联渲染，支持折叠/展开）===== -->
          <div
            v-if="msg.displayType === 'tool_result'"
            class="message-item tool-result-message"
          >
            <div class="message-content tool-result-content">
              <!-- 工具结果组件（各自带标题栏+关闭按钮） -->
              <BlueOceanResult
                v-if="msg.data?.toolId === 'blue-ocean'"
                :data="msg.data?.resultData"
                @close="removeToolResult(index)"
                @navigate-to="handleNavigateTo"
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
                @navigate-to="handleNavigateTo"
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
              <!-- 出价建议 -->
              <BidOptimizeResult
                v-else-if="msg.data?.toolId === 'bid-suggest'"
                :data="msg.data?.resultData"
                @close="removeToolResult(index)"
              />
              <!-- 订单追踪 -->
              <OrderTrackResult
                v-else-if="msg.data?.toolId === 'order-track'"
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
              <!-- 兜底 -->
              <div
                v-else
                class="raw-result-fallback"
              >
                <a-alert
                  type="warning"
                  show-icon
                  message="未知工具类型"
                />
              </div>
            </div>
          </div>

          <!-- ===== 普通文本消息 ===== -->
          <div
            v-else
            :class="['message-item', msg.role, { 'has-conversation-result': !!resolveConversationResult(msg.displayType) }]"
          >
            <div class="message-content">
              <!-- 思考过程（第 210 轮）：流光中默认展开、出结果后自动折叠。
                   放在正文**之上**——时序上它先发生，折叠后也只是不打扰的一条。 -->
              <ThinkingTrace
                :steps="msg.thinkingSteps || []"
                :loading="isLoading && index === messages.length - 1"
              />
              <div
                class="message-text"
                v-html="renderMarkdown(msg.content)"
              />

              <!-- 会话结论卡：对话直接跑出的结构化结论（后端 SSE meta 下发），
                   与工具结果卡**同区、同规则**——都在对话消息流里、都查表渲染，
                   只是轻量只读。正文已自带清单，卡片是同一份结论的结构化承托。 -->
              <component
                :is="resolveConversationResult(msg.displayType)"
                v-if="resolveConversationResult(msg.displayType)"
                :data="msg.data"
              />
            </div>
          </div>
        </div>

        <!-- 加载中：tip 显示后端阶段进度 + 已用时长。
               ★ 第 210 轮起它是**兜底**：一旦已有步骤可看（思考过程轨迹出现），
                 就不再叠一个转圈 —— 老板的原话是「目前只是转圈显示几秒钟」，
                 该退场的地方就得退场，而不是和轨迹各占一块。
                 它仍然保留，是因为「第一秒还没有任何步骤」时总得有反馈。 -->
        <div
          v-if="isLoading && !hasLiveTrace"
          class="message-item assistant"
        >
          <div class="message-content">
            <a-spin :tip="loadingTip" />
          </div>
        </div>
      </div>
    </div>

    <!-- 技能卡动作条（第 189 轮「skill 当源」）：
           卡片 = 技能（方法）· 右侧 tag = 上下文条（参数）。
           四组旧硬编码 chip（竞品 3 / 选品 5 / 复盘 4 / 广告 2）已统一为「读技能列表」——
           点卡 → 点名技能 → 后端 LLM（技能正文由后端注入 system prompt，不进用户消息）。
           ★ 无技能时不渲染：一条空壳动作条比「没有动作条」更让人困惑。 -->
    <div
      v-if="agentStore.currentAgent"
      class="intel-action-bar"
    >
      <div class="iab-controls">
        <!-- 管理技能入口（第 274 轮）：跳转 Skill 仓库。始终显示（只要有 Agent）——
               没有技能卡时**更要**给一个进仓库增删的入口。侧栏虽有「能力」入口，
               但对话窗口内的直达更顺手。 -->
        <button
          class="iab-manage-btn"
          type="button"
          title="管理技能（快捷卡片）"
          @click="goSkillManager"
        >
          <SettingOutlined />
        </button>
        <!-- 分析周期是**竞品专属**的上下文参数，保留原下拉；其余 Agent 用隐藏占位保持同宽 -->
        <div
          v-if="isCompetitorIntelAgent"
          class="iab-period"
        >
          <span class="iab-period-label">分析周期</span>
          <a-select
            v-model:value="intelDays"
            size="small"
            :options="periodOptions"
            style="width: 96px"
            :disabled="isLoading"
          />
        </div>
        <div
          v-else
          class="iab-period"
          style="visibility:hidden"
        >
          <span class="iab-period-label">{{ agentScopeLabel }}</span>
        </div>
        <div class="iab-chips">
          <button
            v-for="c in skillCards"
            :key="c.id"
            class="iab-chip"
            :class="{ 'rqa-loading': activeSkillCard === c.id }"
            :disabled="isLoading || activeSkillCard !== null"
            :title="c.description"
            @click="runSkillCard(c)"
          >
            <span class="iab-chip-icon">{{ c.icon || '🧩' }}</span>
            <span>{{ c.title }}</span>
          </button>
        </div>
      </div>
      <!-- 上下文条只在有技能卡时显示：无技能卡时这一行只剩管理入口，空 tag 反而突兀 -->
      <a-tag
        v-if="skillCards.length"
        :color="agentScopeColor"
        class="iab-scope-float"
      >
        {{ agentScopeText }}
        <!-- ★ 第 298 轮（老板 bug2）：「对象载得进来、出不去」的出口。
               起因（老板原话）：「上下文被某条处置差评填入后，你没有给取消按钮」。
               ★ 只在 `scopeTargetLoaded`（= `contextTarget` 真有值）时出现：
                 它判的与请求体走的是**同一个** computed ⇒ 「界面有 ×」与
                 「这轮真会带对象」不可能各说各话；取消完变 `null` ⇒ × 自己消失，
                 不会留一个"点了没反应"的按钮。
               ★ 与左边那个「本次对话使用：X ×」（`pending-skill-chip`，第 250 轮）
                 同形态：**"还在生效"必须可见 + 必须能撤销**。 -->
        <button
          v-if="scopeTargetLoaded"
          type="button"
          class="iab-scope-clear"
          :title="`取消本次作用对象（不再把这条${agentScopeLabel}带进对话）`"
          aria-label="取消本次作用对象"
          @click="clearScopeTarget()"
        >
          ×
        </button>
      </a-tag>
    </div>


    <!-- 输入区域（卡片式，冻结在底部） -->
    <div
      class="input-area"
      data-tour="tour-chat-input"
    >
      <div class="input-card">
        <!-- 「本次对话使用：X ×」chip（第 250 轮）。
               ★ 为什么必须存在：点名（pendingSkill）在「本轮只出纯文本」时会留到下一轮
                 —— 这是**故意**的（追问的答案必须还能用上点名）。但它对用户不可见 ⇒
                 用户会以为「我没点名」，然后被一个看不见的点名改写结果，且无法撤销。
               ★ 这里**不缩短窗口**，只把窗口**变可见**并给出显式撤销入口。
               ★ v-if 只判 pendingSkillCard，**不与** skillCards.length 联动：
                 点名生效与否跟"当前有没有卡片"无关，联动会让它在边界处静默消失。 -->
        <div
          v-if="pendingSkillCard"
          class="pending-skill-chip"
        >
          <span class="psc-icon">{{ pendingSkillCard.icon || '🧩' }}</span>
          <span class="psc-label">本次对话使用：</span>
          <span class="psc-title">{{ pendingSkillCard.title }}</span>
          <button
            class="psc-close"
            type="button"
            title="撤销本次技能点名（不影响已发出的消息）"
            @click="dismissPendingSkill()"
          >
            ×
          </button>
        </div>
        <a-textarea
          v-model:value="inputMessage"
          :placeholder="inputPlaceholder"
          :auto-size="{ minRows: 3, maxRows: 6 }"
          class="chat-textarea"
          @press-enter="handleKeyPress"
        />
        <div class="input-card-footer">
          <span class="input-hint">{{ footerHint }}</span>
          <div class="input-actions">
            <!-- 增强提示词：唯一实现在 common/PromptEnhanceButton，别在这里再内联一份 -->
            <PromptEnhanceButton
              v-model="inputMessage"
              context="ecommerce"
            />
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
            <!-- 发送 / 停止：同一位置二选一（第 241 轮）。
                   ★ 生成中**不能**把一个禁用按钮留在原地 —— 店秘书 / 竞品等链路要跑
                     十几秒到几十秒，用户唯一的出路是关掉页面。
                   ★ 判定必须 `isStreaming || isLoading`：六条流式链在**首个 token**到达时
                     就退掉 loading（spinner 让位给正文），此后只剩 `isStreaming` 为真；
                     而结构化调用（广告诊断 / Listing 生成等）没有流，只有 `isLoading` 为真。
                     两个都要看 —— 只看一个就会漏掉一半的"生成中"。
                   ★ 圆形容器交给 antd —— 主色底上的前景色由算法决定，
                     避免自己写死白字（presets 里 --text-inverse 深色下是深色，语义不符） -->
            <a-button
              v-if="isStreaming || isLoading"
              class="input-send-btn input-stop-btn"
              shape="circle"
              title="停止生成"
              @click="handleCancel"
            >
              <template #icon>
                <StopOutlined />
              </template>
            </a-button>
            <a-button
              v-else
              class="input-send-btn"
              type="primary"
              shape="circle"
              title="发送（Enter）"
              :disabled="!inputMessage.trim()"
              @click="handleSend"
            >
              <template #icon>
                <ArrowUpOutlined />
              </template>
            </a-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { message } from 'ant-design-vue'
import { RobotOutlined, AudioOutlined, ArrowUpOutlined, StopOutlined, SettingOutlined } from '@ant-design/icons-vue'

// 输入框辅助：提示词增强（公共组件，全站唯一实现）+ 语音输入（浏览器原生识别）
import PromptEnhanceButton from '@/components/common/PromptEnhanceButton.vue'
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
import BidOptimizeResult from './results/BidOptimizeResult.vue'
import OrderTrackResult from './results/OrderTrackResult.vue'
import AIGCMediaResult from './results/AIGCMediaResult.vue'

// 思考过程轨迹（第 210 轮）：流光中展开、出结果后折叠可回看
import ThinkingTrace from './ThinkingTrace.vue'

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
// 3) inject 注入值 —— 只能在组件 setup 中 inject
//    ① 选品分析师的评估主角（`workingCandidate`）—— 第 251 轮接进「作用对象」
//    ② Listing / AIGC 的工作商品（`workingProduct`）—— ★ 第 257 轮接进同一条通道
//    ③ 智能客服当前处置的差评（`workingReview`）—— ★ 第 298 轮接进同一条通道
//    ★ 三者的**默认值口径一致**（`ref(null)` = 没有对象），别让其中一个退化成
//      `undefined`：`undefined` 在 `contextTarget` 里表示"本 Agent 不参与该机制"
//      （见 `chat/types.ts` 的三态表），混用会让"工作区没 provide"伪装成"不参与"。
const loadedCandidate = inject<Ref<any>>('workingCandidate', ref(null))
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))
const workingReview = inject<Ref<any>>('workingReview', ref(null))
// ★ 第 298 轮（老板 bug2）：与上面三个 `working*` **成对**的写口 ——
//   `Workspace.vue` 的 `provide` 一直是成对给出的（`set*` / `clear*`），
//   此前只打通了 `set*` ⇒ **对象载得进来、出不去**（老板原话：
//   「上下文被某条处置差评填入后，你没有给取消按钮」）。
//   默认 noop：`provide` 缺位时"点了没反应"，而不是抛错。
const clearWorkingCandidate = inject<() => void>('clearWorkingCandidate', () => {})
const clearWorkingProduct = inject<() => void>('clearWorkingProduct', () => {})
const clearWorkingReview = inject<() => void>('clearWorkingReview', () => {})

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

/**
 * 跳转 Skill 仓库（第 274 轮）：快捷卡片栏左侧的管理入口。
 *
 * ★ 走 `view-navigate` 事件，不在这里拼 `currentView`：视图切换、侧栏高亮、
 *   关闭右面板，Workspace 已有一套唯一实现（`handleKnowledgeNavigate`），
 *   这里再写一遍就是「同一切换两份实现」—— 加第三个视图时必然漏一处。
 */
function goSkillManager() {
  window.dispatchEvent(new CustomEvent('view-navigate', { detail: { view: 'skills' } }))
}

/**
 * 对话工具栏（查找 / 历史提问）的**跳转落点**（第 283 轮）。
 *
 * ★ 为什么落点只在这里：工具栏住在 Workspace 的顶栏，但它要跳的**消息 DOM**只在本组件
 *   —— 滚动容器是 `.main-content`（本文件里唯一的滚动容器），而下标与
 *   「工具结果 / 普通文本」两套渲染分支的对应关系也只有这里知道。让工具栏自己去
 *   `document.querySelector`，它就得**复刻**这套下标口径 ⇒ 同一个下标两份实现，
 *   将来加一种消息类型必然错位一处。
 *
 * ★ 下标取的是**消息数组下标**（`data-msg-index` 写在 v-for 的 wrapper 上），不是 DOM 序号：
 *   两类消息在模板里是 `v-if / v-else` 两套分支，按 DOM 数会漏算或错位。
 */
function handleScrollToMessage(e: Event) {
  const index = (e as CustomEvent).detail?.index
  if (typeof index !== 'number') return
  const root = messageListRef.value
  if (!root) return
  const el = root.querySelector<HTMLElement>(`[data-msg-index="${index}"]`)
  // 找不到就什么都不做（不抛错、也不谎报成功）：工具栏那边已经把面板关掉了，
  // 硬跳到一个不存在的位置只会让用户以为跳错了地方。
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.classList.add('msg-flash')
  window.setTimeout(() => el.classList.remove('msg-flash'), 1800)
}

onMounted(() => {
  window.addEventListener('chat-scroll-to-message', handleScrollToMessage as EventListener)
})
onBeforeUnmount(() => {
  window.removeEventListener('chat-scroll-to-message', handleScrollToMessage as EventListener)
})

// 其余全部编排逻辑下沉到 composable，此处仅解构模板所需出口
const {
  // 店秘书计划（第 155 轮）
  secretaryPlan,
  // 状态
  messages,
  isLoading,
  // 「生成中」只看活跃流 —— 首 token 到达后 isLoading 已是 false（见按钮处注释）
  isStreaming,
  loadingTip,
  inputPlaceholder,
  // Agent 判定
  isCompetitorIntelAgent,
  isProductResearchAgent,
  isListingAgent,
  isReviewAgent,
  isAdAnalyst,
  // 技能卡动作条（第 189 轮）：卡片 = 技能（方法）；上下文条（参数）由 agentScope* 提供
  skillCards,
  activeSkillCard,
  runSkillCard,
  periodOptions,
  agentScopeText,
  agentScopeColor,
  agentScopeLabel,
  // 点名可见 chip（第 250 轮）：本轮生效的技能点名 + 用户撤销入口
  pendingSkillCard,
  dismissPendingSkill,
  // 作用对象的取消入口（第 298 轮 · 老板 bug2）：上下文条上的 ×
  scopeTargetLoaded,
  clearScopeTarget,
  // 消息 / 输入 / 渲染
  removeToolResult,
  handleNavigateTo,
  renderMarkdown,
  handleKeyPress,
  handleSend,
  // 「停止生成」（第 241 轮）
  handleCancel,
} = useChatOrchestrator({
  inputMessage,
  messageListRef,
  mainContentRef,
  intelDays,
  loadedCandidate,
  // ★ 第 257 轮：Listing / AIGC 的工作商品 —— 对话链路与右栏工具此后看**同一个**对象
  workingProduct,
  // ★ 第 298 轮：客服的处置差评 —— 差评工作台「💬 在对话里处置这条」把对象送到这里
  workingReview,
  // ★ 第 298 轮（老板 bug2）：三个与 `set*` 成对的**取消写口**，供上下文条上的 × 用
  clearWorkingCandidate,
  clearWorkingProduct,
  clearWorkingReview,
})

/**
 * 本轮是否已经能看到思考过程（决定上面那个转圈要不要退场）。
 *
 * ★ 只认**最后一条**消息：轨迹写在「正在跑的那条」上。拿历史消息里的旧轨迹
 *   来判断，会让转圈在该出现的时候不出现，而那一轮可能**压根没有工具调用**
 *   ⇒ 用户面对零反馈。这里要问的正是「该出现的时候有没有出现」。
 */
const hasLiveTrace = computed(() => {
  const last = messages.value[messages.value.length - 1]
  return !!last?.thinkingSteps?.length
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

/** 底部提示：收音中要让位给录音状态，否则用户不知道还在录 */
const footerHint = computed(() =>
  speechState.listening ? '正在听… 说完点麦克风结束' : 'Enter 发送 · Shift+Enter 换行',
)

const speechTip = computed(() => {
  if (!speechState.supported) return speechUnsupportedReason.value
  return speechState.listening ? '结束录音' : '语音输入（说话转文字）'
})

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

/* 消息项（第 212 轮：**对话区不再有头像**，对齐 WorkBuddy 的形态）。
   ★ 左右归属改由 `justify-content` 表达，**不再用 `row-reverse`** ——
     没有头像之后，`row-reverse` 会把用户气泡推到左边（读起来像 AI 说的），
     而这个退化**零报错**、也没有任何测试会红。
   ★ AI 回复**不带气泡**（无底色、占满宽度）：一是 WorkBuddy 的形态；
     二是思考过程 / 结论卡这类结构化内容本来就需要横向空间。 */
.message-item {
  display: flex;
  margin-bottom: var(--space-20);
}

.message-item.user {
  justify-content: flex-end;
}

/* 从工具栏（查找 / 历史提问）跳过来时闪一下（第 283 轮）。
   没有这个反馈，用户不知道「到底跳没跳到」—— 尤其目标消息本来就贴着视口边缘时，
   滚动前后看起来几乎一样。 */
.msg-flash {
  border-radius: var(--radius-8);
  animation: msg-flash 1.8s ease-out;
}

@keyframes msg-flash {
  0% {
    background: var(--bg-active-light);
  }
  100% {
    background: transparent;
  }
}

@media (prefers-reduced-motion: reduce) {
  .msg-flash {
    animation: none;
    background: var(--bg-active-light);
  }
}

.message-content {
  max-width: 100%;
  min-width: 0;
}

/* 用户消息：右对齐的浅色气泡（保留气泡的只有这一侧） */
.message-item.user .message-content {
  max-width: 76%;
  padding: var(--space-10) var(--space-14);
  border-radius: var(--radius-12);
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
/* ★ 第 298 轮（老板 bug2）：作用对象的取消按钮。视觉与左邻的「本次对话使用 ×」
   （`.psc-close`）同族 —— 两处都是"还在生效 -> 可撤销"，样式漂移会让其中一个
   看起来像装饰。颜色跟随所在 a-tag 的色系（继承 currentColor），
   不写死主色（tag 的底色是 `agentScopeColor` 给的，写死会撞色）。 */
.iab-scope-clear {
  flex: none;
  margin-left: var(--space-4);
  padding: 0 var(--space-2);
  border: none;
  border-radius: var(--radius-4);
  background: transparent;
  color: inherit;
  font-size: var(--font-size-11);
  line-height: 1;
  cursor: pointer;
  opacity: 0.7;
}
.iab-scope-clear:hover { opacity: 1; text-decoration: underline; }
.iab-controls {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  flex-wrap: wrap;
  justify-content: flex-end;
}
/* 管理技能入口（第 274 轮）：快捷卡片栏最左侧，跳转 Skill 仓库 */
.iab-manage-btn {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: var(--font-size-14);
  cursor: pointer;
  transition: all 0.18s ease;
  padding: 0;
  line-height: 1;
}
.iab-manage-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-active-light);
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

/* 「本次对话使用：X ×」chip（第 250 轮）—— 点名可见化 + 显式撤销入口 */
.pending-skill-chip {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  width: fit-content;
  max-width: 100%;
  margin-bottom: var(--space-8);
  padding: var(--space-4) var(--space-10);
  border-radius: var(--radius-15);
  border: 1px solid var(--border-strong);
  background: var(--bg-active-light);
  color: var(--text-secondary);
  font-size: var(--font-size-12);
}
.psc-icon { line-height: 1; font-size: var(--font-size-13); }
.psc-label { color: var(--text-tertiary); white-space: nowrap; }
.psc-title {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.psc-close {
  flex-shrink: 0;
  padding: 0 var(--space-2);
  border: none;
  border-radius: var(--radius-4);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--font-size-14);
  line-height: 1;
  cursor: pointer;
}
.psc-close:hover { color: var(--primary); background: var(--bg-elevated); }

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
  color: var(--text-tertiary);
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


/* 发送按钮由 antd 提供配色（主色底 + 算法决定的前景色），这里只协调布局 */
.input-send-btn {
  flex: none;
}

/* 「停止生成」（第 241 轮）：与发送按钮同位置同尺寸，用 antd 的 default 变体
   （不指定 type ⇒ 底色/边框来自 default token，深浅主题自动跟随，不写死颜色）。
   hover 转 danger 色，让"这是一个中断操作"一眼可辨，而不是又一个普通按钮。 */
.input-send-btn.input-stop-btn {
  color: var(--text-secondary);
}

.input-send-btn.input-stop-btn:hover {
  color: var(--danger);
  border-color: var(--danger);
}
</style>

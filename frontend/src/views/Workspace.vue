<template>
  <a-layout
    class="workspace-container"
    :class="{
      'review-data-mode': isReviewDataMode,
      'listing-data-mode': isReviewDataMode && isListingAgent,
      'aigc-data-mode': isReviewDataMode && isAigcAgent,
      'product-research-data-mode': isReviewDataMode && isProductResearchWideTool,
    }"
  >
    <!-- 左侧边栏 -->
    <a-layout-sider
      :width="PANEL_W.sidebar"
      :collapsed="sidebarCollapsed"
      theme="light"
      class="sidebar"
    >
      <!-- Logo 区域 + 店铺群触发器 -->
      <!-- data-tour：新手引导锚点。取值必须逐字对齐 src/config/tourAnchors.ts，
           双向对账（注册了没标 / 标了没注册）由 scripts/check-tour-anchors.cjs 钉住 -->

      <div class="logo-row" data-tour="tour-brand">
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
          <button
            class="shop-trigger-btn"
            :class="{ active: shopPopoverVisible }"
            data-tour="tour-shop-switch"
          >
            <ShopOutlined />
            <span v-if="!sidebarCollapsed" class="shop-trigger-count">{{ shopCount }}</span>
          </button>
        </a-popover>
      </div>

      <!-- Agent 群 -->
      <SidebarAgentList />

      <!-- 资料库 -->
      <SidebarKnowledgeBase ref="knowledgeBaseRef" @navigate="handleKnowledgeNavigate" />

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
            <!-- 运营复盘师/广告分析师/AIGC：仅对话模式显示工具按钮 —— 它们在数据模式下
                 **面板里自带工具 Tab**（rv-tabs / aigc-tool-tabs），顶部再挂一排是重复入口。
                 ★ 第 292 轮修：**差评工作台不在此名单**。它同为「工具级宽看板」，但面板里
                   **没有**替代的工具 Tab（只有它自己内部的三个视图）⇒ 把功能栏一起隐藏的
                   后果是**用户再也切不回「订单追踪」**（真机复现见
                   `scripts/cdp-review-desk-ui-probe-panel-bug.mjs` 的 R6）。
                   ⇒ 判据：**只有「面板里真的另有入口」才允许隐藏这一排。** -->
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
          <!-- 对话工具栏（查找 / 分享 / 历史提问）—— 对齐 WorkBuddy 的对话窗口右上角。
               只在对话视图出现：资料库视图下它要操作的对象根本不在屏幕上，放出来就是误导。 -->
          <ConversationToolbar v-if="currentView === 'chat'" />

          <!-- 右侧面板展开按钮（第 283 轮）。
               ★ 右栏是 <a-layout-sider :collapsed-width="0" :trigger="null">，收起后宽度归零、
                 默认把手也关掉了 —— 界面上不留任何痕迹，于是「收起」曾是个**单向操作**：
                 只有「选工具 / 切 Agent / 从资料库返回」会顺带展开，用户主动收起后找不回来
                 （老板原话：「右侧边栏的折叠按钮当折叠后，在对话窗口右上角没有展开按钮」）。
               ★ 显示条件与右栏自身的挂载条件同源（对话视图 + 非店秘书）—— 店秘书压根没有右栏，
                 对它显示这个按钮 = 一个点了没反应的按钮。 -->
          <button
            v-if="canExpandRightPanel"
            type="button"
            class="panel-expand-btn"
            title="展开右侧面板"
            @click="rightPanelCollapsed = false"
          >
            <RightOutlined />
          </button>

          <!-- 宽看板场景（复盘 / Listing / 广告 / 竞品监控 / AIGC / 差评台账 / 选品三工具）：
               双模式切换（对话模式 / 大屏模式；Listing 为文案模式）
               ★ 第 313 轮：选品三工具（选品大盘 / 蓝海挖掘 / 利润测算）**全部进**。
                 第 312 轮只把「选品大盘」放了进来，蓝海/利润落在双模式之外 ⇒
                 点这两个工具时 `hasWideBoard` 变假：根节点丢 `review-data-mode`、
                 右栏缩回 340、对话区回到全宽；而右栏顶部的工具 Tab 栏只认
                 `reviewMode === 'data'`，照样显示 ⇒ 出现「布局退回对话模式、
                 右栏却还挂着功能栏」的错位（老板 09-29 截图）。
                 一份「是否大屏」的判定不许两处各写一遍，故三个工具收进同一判据。
               差评台账**进**：同样是工具级，但台账是 8 列表格，528 不够 ⇒ 要双模式
               （它不是 Agent 级 ⇒ 只在选中该工具时出现，见 isReviewDeskTool）。 -->
          <div v-if="hasWideBoard && currentView === 'chat'" class="mode-switch">
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

        <!-- 复盘库视图（第 251 轮；第 7 个资料库，与上面 6 个同组：都按 X-Shop-ID 过滤） -->
        <ReviewLibrary v-else-if="currentView === 'reviews'" />

        <!-- Skill 仓库 / 快捷卡片管理视图（平台级：技能是账号级的，不随当前店铺变化） -->
        <SkillManager v-else-if="currentView === 'skills'" />
        <!-- ★ 第 209 轮：工具仓库与 Skill 仓库**平级**（各自一个侧边栏入口）。 -->
        <ToolManager v-else-if="currentView === 'tools'" />
      </a-layout-content>
    </a-layout>

    <!-- 右侧任务配置面板（仅对话视图显示） -->
    <a-layout-sider
      v-if="currentView === 'chat' && !isSecretaryAgent"
      data-tour="tour-right-panel"
      :width="isWidePanel ? PANEL_W.panelWide : PANEL_W.panelNormal"
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
      />
    </a-layout-sider>

    <!-- 记忆与进化 Drawer（全局，由侧栏菜单触发） -->
    <MemoryEvolution v-model:open="memoryDrawerOpen" />

    <!-- 设置 Drawer（全局，由侧栏菜单触发） -->
    <Settings v-model:open="settingsDrawerOpen" />

    <!-- 审计日志 Drawer（全局；只有平台超管的菜单项会派发 `open-audit-drawer`） -->
    <AuditLogPanel v-model:open="auditDrawerOpen" />

    <!-- 划词翻译浮层（全局一次，选中英文商品文字即出译文） -->
    <SelectionTranslateLayer />
  </a-layout>
</template>

<script setup lang="ts">
import { PANEL_W } from '@/config/layout'
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
  // 第 283 轮：右栏折叠后的展开入口（面板收进 0 宽时唯一能把它叫回来的按钮）
  RightOutlined,
} from '@ant-design/icons-vue'

import SidebarAgentList from '@/components/Sidebar/AgentList.vue'
import SidebarKnowledgeBase from '@/components/Sidebar/KnowledgeBase.vue'
import SidebarAccountMenu from '@/components/Sidebar/AccountMenu.vue'
import ShopPopoverContent from '@/components/Sidebar/ShopPopoverContent.vue'
import ChatPanel from '@/components/ChatPanel/index.vue'
// 对话窗口右上角的「查找 / 分享 / 历史提问」（第 283 轮）
import ConversationToolbar from '@/components/ChatPanel/ConversationToolbar.vue'
import TaskConfigPanel from '@/components/TaskConfigPanel/index.vue'
import FaqKnowledgeBase from '@/components/KnowledgeBase/FaqKnowledgeBase.vue'
import CandidateLibrary from '@/components/KnowledgeBase/CandidateLibrary.vue'
import ProductLibrary from '@/components/KnowledgeBase/ProductLibrary.vue'
import MonitorPoolLibrary from '@/components/KnowledgeBase/MonitorPoolLibrary.vue'
import AssetLibrary from '@/components/KnowledgeBase/AssetLibrary.vue'
import PlatformRules from '@/components/KnowledgeBase/PlatformRules.vue'
import ReviewLibrary from '@/components/KnowledgeBase/ReviewLibrary.vue'
import SkillManager from '@/components/SkillStore/SkillManager.vue'
import ToolManager from '@/components/ToolStore/ToolManager.vue'
import IntelPickButton from '@/components/TaskConfigPanel/configs/IntelPickButton.vue'
import MemoryEvolution from '@/views/MemoryEvolution.vue'
import Settings from '@/views/Settings.vue'
// 审计日志抽屉（第 328 轮）：住在 `components/` 而不是 `views/` ——
// 它**刻意没有路由**（读口要求平台超管，做路由等于给所有人一条 403 死路由）。
import AuditLogPanel from '@/components/AuditLog/AuditLogPanel.vue'
import SelectionTranslateLayer from '@/components/Translate/SelectionTranslateLayer.vue'
import VoiceSpeakerButton from '@/components/common/VoiceSpeakerButton.vue'
import { VOICE_CLONE_ENABLED } from '@/config/featureFlags'
import type { ToolDefinition } from '@/components/ChatPanel/tools/toolDefinitions'
import { getAgentTools, getToolDefinition, resolveDefaultTool } from '@/components/ChatPanel/tools/toolDefinitions'

import { useAgentStore } from '@/stores/agent'
import { useChatStore } from '@/stores/chat'
import { useShopStore } from '@/stores/shop'
// ★ C 档（2026-09-17）：当前账户上下文（应用级）。见 account store 的模块 docstring。
import { useAccountStore } from '@/stores/account'
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
const accountStore = useAccountStore()
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
/** 审计日志抽屉（第 328 轮）。入口在账户菜单，且只对平台超管渲染。 */
const auditDrawerOpen = ref(false)

// 店铺群 Popover 状态
const shopPopoverVisible = ref(false)

// 店铺数量
const shopCount = computed(() => shopStore.shopList.length)

// 当前选中店铺（用于标题栏显示）
const currentShop = computed(() => shopStore.currentShop)

// 内容区视图切换：chat（Agent 对话）| faq（业务话术库）| candidates（选品库）| products（产品/Listing 库）| assets（营销素材库）| rules（平台规则库）| reviews（复盘库，第 251 轮）| skills（Skill 仓库）| tools（工具仓库，第 209 轮）
// 竞品监控看板已并入竞品监控员的右侧边栏，不再是独立视图
//
// ★ 联合类型与下面 handleKnowledgeNavigate 的 cast 是**同一份名单的两处**，
//   新增视图必须两处都改（漏改 cast 的症状是「菜单点得到、切不过去」）。
//   这两处的**集合相等**由 `scripts/check-review-library-view.cjs` 钉住 ——
//   刻意保留内联写法而不是抽成 `type KnowledgeView`：抽成别名后，
//   `check-tool-repo-view.cjs` 那两条按内联联合写的断言会**静默失配**
//   （门禁失配 = 门禁失效，且症状是"门禁还在跑、其实已经查不到东西了"）。
const currentView = ref<'chat' | 'faq' | 'candidates' | 'products' | 'competitors' | 'assets' | 'rules' | 'reviews' | 'skills' | 'tools'>('chat')

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

// ====== 当前处置的差评（智能客服·差评应对，Agent 级共享上下文）======
// ★ 第 298 轮：差评工作台里点「💬 在对话里处置这条」时写入（三个入口共用出口）。
//   在此之前客服链路**完全没有**这条通道（前端只发 `{message, skill}`）——
//   于是「在台账里选中了某条差评、进对话只说『帮我处理这条』」时，
//   模型只能从**会话历史**里挑一条顶上 ——
//   第 250 轮那个洞在客服线上的**同一形状**。
//   ★ 与 `workingProduct` / `workingCandidate` 同构：三个 provide 一起，
//     代表「工作区当前选中的对象」这一件事的三份真源。
const currentWorkingReview = ref<any>(null)
provide('workingReview', currentWorkingReview)
provide('setWorkingReview', (review: any) => {
  currentWorkingReview.value = review
})
provide('clearWorkingReview', () => {
  currentWorkingReview.value = null
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

/**
 * 右栏折叠后的**回程入口**判据（第 283 轮）。
 *
 * ★ 条件必须与右栏自身的挂载条件（`currentView === 'chat' && !isSecretaryAgent`）同源：
 *   写宽了就会出现「按钮在、点了没反应」；写窄了就是「面板关了回不来」。
 *   两份条件各写一遍必然漂移，所以这里只写这一处，模板里只认这一个值。
 */
const canExpandRightPanel = computed(
  () => currentView.value === 'chat' && rightPanelCollapsed.value && !isSecretaryAgent.value
)

// 选品分析师三工具（选品大盘 / 蓝海挖掘 / 利润测算）的**统一**判据见下方
// `isProductResearchWideTool`（第 313 轮收口）。
// ⚠️ 这里原先拆着 `isWideProfitTool`（只有利润测算），蓝海挖掘两边都没有 ⇒ 点它就掉出大屏模式。
//    历史约束「利润测算只借宽度、不接大屏」（09-13 老板拍板）已被第 312 轮推翻：
//    当时怕的是"右栏吃满剩余宽度 ⇒ 成本表『说明』列被撑成空白"
//    （1477px 实测说明列 1216px，其中 1110px 纯空白）；
//    第 312 轮把大屏改成「右栏**内部**左右分栏」，表单列由 `minmax(280px, 1fr)` 封顶，
//    说明列只剩 ~160px ⇒ 该理由不再成立。

// AIGC 媒体生成器（3 工具）：与复盘/Listing/广告/竞品监控一样，接「对话模式 / 大屏模式」。
// 09-13 老板纠偏：AIGC 大屏**参照其他 Agent**，走 Workspace 顶栏 mode-switch（reviewMode 切 chat/data），
//   不要在每个工具配置窗口里自造「对话/大屏」按钮（AIGCMediaWrapper 头部按钮已删除）。
// 第 9 轮进一步细化：AIGC 用 **Agent 级**判定（与具体工具无关），点 AIGC Agent 就该显示顶栏 mode-switch，
// 不用先选「静态素材生成/脚本/视频」。3 个工具共用同一对「对话/大屏」按钮。
// 大屏模式 = 右栏「左右分栏」：左半边是表单（继续可见），右半边是预览窗口（图片网格/分镜卡片/视频播放器）。
const isAigcAgent = computed(() => currentAgent.value?.id === 'aigc-media')

// ★ 第 291 轮：差评工作台（智能客服 → 差评台账）—— **工具级**宽看板。
//   里面第三个视图「处置台账」是 8 列表格（SKU / 评分 / 标题 / 通道 / 补偿 /
//   状态 / 更新 / 操作），340 与 528 都放不下 ⇒ 需要对话模式与大屏模式。
//   ★ 为什么不像 AIGC 那样做成 Agent 级：客服的主形态是聊天，点进去就挂一个
//     「大屏」开关是干扰；只有真的选中这个工具才需要。这与选品三工具
//     （`isProductResearchWideTool`）的粒度一致 —— 同样是"选中该工具才给双模式"。
const isReviewDeskTool = computed(
  () =>
    currentAgent.value?.id === 'customer-service' &&
    currentSelectedTool.value?.id === 'review-desk'
)

// ★ 第 305 轮起就是**工具级**双模式，第 313 轮把三个工具收进同一判据。
//   与 isReviewDeskTool 同粒度：选品分析师的主形态是聊天 + 常规表单，
//   点进去就挂「大屏」开关是干扰；只有选中下面这三个工具之一才需要。
//
//   三个工具的大屏形态（第 312 轮，对齐 AIGC「右栏内部左右分栏」范式）：
//     · market-insight（选品大盘）：左 Treemap + 右六维度明细
//     · blue-ocean    （蓝海挖掘）：左筛选表单 + 右产品清单（BlueOceanResult）
//     · profit-calc   （利润测算）：左成本明细表单 + 右计算结果（ProfitResult）
//
//   ★ 为什么必须是**集合**而不是逐个 `||`：这份名单同时决定
//     `hasWideBoard`（整页大屏布局 + 顶栏 mode-switch + 根节点 class）
//     与 `isWidePanel`（右栏加宽），漏一个成员 = 该工具点下去时
//     「布局退回对话模式、右栏却还挂着功能栏」。
const PRODUCT_RESEARCH_WIDE_TOOL_IDS = ['market-insight', 'blue-ocean', 'profit-calc']
const isProductResearchWideTool = computed(
  () =>
    currentAgent.value?.id === 'product-research' &&
    PRODUCT_RESEARCH_WIDE_TOOL_IDS.includes(currentSelectedTool.value?.id ?? '')
)

// 需要「宽看板」场景（复盘 / Listing / 广告 / 竞品监控 / AIGC / 差评台账）
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

// 是否拥有「对话模式 / 大屏模式」这套能力 —— 上面那五个是 Agent 级，
// 差评台账 / 选品三工具是工具级，汇总后给右侧的「是否被 hook 到双模式」用。
// ★ 不能把工具级判据直接并进 `isWideBoardAgent`：
//   那个名字与其注释明写「需要宽看板场景」是 **Agent 级**判定，混进工具级会让名字说谎。
const hasWideBoard = computed(
  () => isWideBoardAgent.value || isReviewDeskTool.value || isProductResearchWideTool.value
)

// 右栏「加宽」的判定（对话模式下右栏 = 528 = `PANEL_W.panelWide`，大屏模式下被
// `.review-data-mode .right-panel` 覆盖成"吃剩余宽度"）。
// ★ 第 313 轮起它与 `hasWideBoard` **同一集合**：拥有双模式能力的场景，在对话模式下
//   也都需要比 340 更宽。以前两者差一个 `isWideProfitTool`（只加宽、不给大屏），
//   那条差异随选品三工具收口一起消失。
// ★ 写成 `hasWideBoard.value` 而不是再抄一遍成员列表 —— 抄一遍就是第二份实现，迟早漂移
//   （本轮的 bug 正是这么来的：整页布局认 hasWideBoard，右栏 Tab 栏认 reviewMode）。
const isWidePanel = computed(() => hasWideBoard.value)

// ====== 宽看板 Agent·双模式布局 ======
// chat = 对话优先（中间对话宽，右侧看板窄）
// data = 面板优先（右侧看板占大部分宽度，对话压缩成窄侧边栏）
const REVIEW_MODE_KEY = 'review-analyst-layout-mode'
// ★★ 第 292 轮修：模式偏好**按 Agent 分键**。
//   原实现是**全局单键**，被 5 个宽看板 Agent/工具（复盘 / Listing / 广告 / 竞品 / AIGC /
//   差评工作台）共用 ⇒ **跨 Agent 状态泄漏**：在复盘师切了「大屏模式」，转头到智能客服
//   点【差评处理】就直接进大屏，顶栏功能栏随之隐藏，用户莫名其妙（老板原话：
//   「一开始功能栏显示正常，点【差评处理】弹出右侧边栏，再折叠右侧边栏之后，功能栏不见了」）。
//   ★ 时序上"折叠"是无辜的 —— 真机探针路径 1 已证：reviewMode=chat 时折叠右栏功能栏仍在；
//     消失发生在**点差评处理那一刻**（路径 2，R4/R5）。
//   ★ 注：本段（含引语）里的【差评处理】是该按钮在第 296 轮之前的旧名，
//     现名「差评台账」；引语保留当时的叫法，不改写。
//   ★ 语义上这份键记的是「**这个 Agent** 上次用的布局」，本来就该按 Agent 分开；
//     未存过 ⇒ 回到对话模式，而不是继承上一个 Agent 的选择。
const reviewMode = ref<'chat' | 'data'>('chat')
const reviewModeKey = (agentId?: string) => `${REVIEW_MODE_KEY}:${agentId || 'none'}`
watch(
  () => currentAgent.value?.id,
  (id) => {
    const saved = localStorage.getItem(reviewModeKey(id))
    reviewMode.value = saved === 'data' ? 'data' : 'chat'
  },
  { immediate: true }
)
function setReviewMode(mode: 'chat' | 'data') {
  reviewMode.value = mode
  localStorage.setItem(reviewModeKey(currentAgent.value?.id), mode)
}
// 仅宽看板 Agent + 面板优先模式 + 右侧面板未收起时，才应用**整页**看板布局
// （中间对话压缩成窄边栏、右栏吃剩余宽度）。
// AIGC 也在这里：大屏模式下中间对话变窄，右栏预览窗口吃满剩余宽度（与其他看板 Agent 一致）。
const isReviewDataMode = computed(
  () => hasWideBoard.value && reviewMode.value === 'data' && !rightPanelCollapsed.value
)

// 向 ListingBoard / ReviewConfig 提供当前「对话/文案(数据)」模式（= **用户的偏好**本身）
provide('reviewMode', reviewMode)

// ★ 第 313 轮：另 provide 一个「**整页大屏布局此刻是否真的生效**」。
//   两者不是一回事：`reviewMode` 是用户的选择（按 Agent 存，可能是 'data'），
//   而 `isReviewDataMode` 还要求 `hasWideBoard && !rightPanelCollapsed`。
//   ★ 下游若拿"偏好"当"我现在在大屏里"用，就会出现本次故障的另一半 ——
//     布局已经退回对话模式，右栏顶部却还挂着一排工具 Tab 栏
//     （老板 09-29 截图：点「蓝海挖掘 / 利润测算」后右栏有功能栏、中间却是对话模式大小）。
//   ⇒ **想让某块 UI「只在大屏模式出现」的，一律 inject 这一个值**，
//     不要自己再算一遍 `reviewMode === 'data'`（那就是第二份实现，两份必然漂移）。
//   ⚠️ 尚未迁移的自算点：各 `configs/*.vue` 里的 `isDataMode`（10 个文件）。
//     它们**今天是等价的** —— 那些 config 只在自己所属 Agent 下渲染，而该 Agent
//     （复盘 / Listing / 广告 / 竞品 / AIGC / 差评台账 / 选品三工具）的 `hasWideBoard` 恒真。
//     若将来出现「同一 Agent 内有不参与大屏的工具」，这些自算点必须一并改成 inject 本值。
provide('isWideBoardDataMode', isReviewDataMode)

// 注：原先还 provide('isWidePanel') 让右栏自己决定「配置 | 预览」是否并排；
// 09-13 取消 AIGC 右栏预览后已无消费方，故移除（右栏宽度只由 :width 的 isWidePanel 决定）。

// 当前 Agent 的工具列表（广告分析师：出价建议已移至输入框上方 chip，顶部不再重复展示）
// ★ 第 316 轮：`budget-alloc`（预算分配）已整条退役（老板「广告分析师删除异常检测、
//   广告预算再平衡」）⇒ 它连卡片一起没了，不再需要在顶部工具栏里排除。
const AD_TOOLBAR_EXCLUDE = new Set(['bid-suggest'])
const currentAgentTools = computed(() => {
  const tools = currentAgent.value ? getAgentTools(currentAgent.value.id) : []
  if (currentAgent.value?.id === 'ad-analysis') {
    return tools.filter(t => !AD_TOOLBAR_EXCLUDE.has(t.id))
  }
  return tools
})

/**
 * 「Agent 级共享上下文」的**属主判定 —— 唯一真源**。
 *
 * ★ 为什么必须是函数、不能各写一遍字符串比较：同一判定要在**两个地方**用 ——
 *   ① 顶部按钮显不显示；② 切 Agent 时要不要清空。
 *   两份实现必然漂移（本仓既有先例：candidate 侧「显示判 `===`、清空判 `!==`」已是两份），
 *   而漂移的后果是**状态跨 Agent 残留** —— 表现为别的 Agent 右栏顶部挂着上一个商品。
 */
const PRODUCT_LOADER_AGENTS = ['listing-generator', 'aigc-media']
const isProductLoaderAgent = (id?: string) => !!id && PRODUCT_LOADER_AGENTS.includes(id)
const isCandidateLoaderAgent = (id?: string) => id === 'product-research'
// ★ 第 298 轮：智能客服（差评应对）。它的「处置差评」与上面两个 ref 同属
//   「载入型」语义 —— 离开属主就该清空，否则别的 Agent 的对话会把上一条
//   差评当成本次作用对象。
const isReviewLoaderAgent = (id?: string) => id === 'customer-service'

// 是否显示「载入产品」按钮（仅 Listing 优化师 / AIGC 媒体生成器）
const showProductLoader = computed(() => isProductLoaderAgent(currentAgent.value?.id))

// 是否显示「载入选品」按钮（仅选品分析师）—— 载入选品库中的未上架候选作为评估主角
const showCandidateLoader = computed(() => isCandidateLoaderAgent(currentAgent.value?.id))

// 切换左侧边栏
const toggleSidebar = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

// ====== 新手引导的布局命令（第 284 轮）======
// `sidebarCollapsed` / `rightPanelCollapsed` 是本文件的局部 ref，
// 而引导宿主挂在 App.vue 根上、拿不到它们。两条路：
//   ① 把它们提成 store —— 要动 Workspace 的所有消费点，为一个 MVP 不划算；
//   ② 发命令事件、由属主自己执行 —— 本仓既有范式
//      （open-memory-drawer / view-navigate / product-listing-optimize 都是这么做的）。
// 选 ②。
// ★ 两条命令都**只展开、不折叠**：引导无权把一个用户自己收起来的侧栏反过来扣回去，
//   也不该负责把它恢复成原样（首次进入时默认本来就是展开态，副作用天然为零）。
function ensureSidebar() {
  sidebarCollapsed.value = false
}
function ensureRightPanel() {
  rightPanelCollapsed.value = false
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
  currentView.value = key as 'faq' | 'candidates' | 'products' | 'competitors' | 'assets' | 'rules' | 'reviews' | 'skills' | 'tools'
  // 同步侧边栏高亮：来自 CustomEvent（如大屏的「在资料库中管理」）的跳转不会经过菜单点击，
  // 不补这一步就会出现「视图已切、菜单没高亮」的错位。
  knowledgeBaseRef.value?.navigateTo(key)
  // 切换到资料库视图时，关闭右侧配置面板（工具面板不适用）
  if (key !== 'chat') {
    currentSelectedTool.value = null
    rightPanelCollapsed.value = true
  }
}

// 点击 Agent 时自动切回对话视图 + 恢复该 Agent 上次离开时的工具
// 同时监听 currentAgent 引用变化 + agentClickCounter（处理同一 agent 重复点击场景）
//
// ★ 第 311 轮：状态记忆 —— 老板要求「切到别的 agent 再切回来，要回到上次离开的状态」。
//   · agentToolMemory：agentId → 上次离开时选中的 toolId；
//   · 切走时**记录当前工具**（覆盖工具栏点击、大盘点色块预填跳转等所有改工具的路）；
//   · 切回时按「记忆 > 默认工具 > 空态」恢复；同 agent 重复点击则保持现状不重置。
let lastAgentId: string | null = null
const agentToolMemory: Record<string, string> = {}

watch([() => agentStore.currentAgent, () => agentStore.agentClickCounter], () => {
  if (agentStore.currentAgent) {
    const nextAgentId = agentStore.currentAgent.id
    const leavingId = lastAgentId
    const isSameAgent = nextAgentId === leavingId
    lastAgentId = nextAgentId

    if (isSameAgent) {
      // 同一 agent 重复点击（如产品库视图下再点当前 agent）：保持当前工具不变，
      // 只切回对话视图 + 展开右栏，不重置工具、也不清共享上下文。
    } else {
      // 切走：把「离开的 agent」当前选中的工具记进记忆（含预填跳转改的）
      if (leavingId && currentSelectedTool.value) {
        agentToolMemory[leavingId] = currentSelectedTool.value.id
      }
      // 切回：恢复记忆工具；无记忆才用默认工具（规格表 AGENT_DEFAULT_TOOL，唯一真源）。
      // ⚠️ 禁止在这里写 agent id 字面量，也禁止「取工具数组第一个」——理由见 toolDefinitions.ts。
      const rememberedId = agentToolMemory[nextAgentId]
      const rememberedTool = rememberedId ? getToolDefinition(nextAgentId, rememberedId) : null
      const defaultTool = resolveDefaultTool(nextAgentId)
      // 记忆 id 若已失效（工具退役），fallback 到默认工具，不挂一个不存在的工具
      currentSelectedTool.value = rememberedTool ?? defaultTool
      if (currentSelectedTool.value) {
        // 选中工具时同步展开右栏，避免工具已选但面板折叠看不到
        rightPanelCollapsed.value = false
      }
    }
    // 离开属主：清空 Agent 级共享上下文，避免携带到其它 Agent。
    // ★ 两个 ref 必须**成对**处理 —— 只清一个，另一个会静默残留：
    //   实测 listing 载入商品后切走，其它 Agent 右栏顶部仍挂着该商品名，
    //   且 `PitfallsConfig` 的 `canSubmit` / `CompetitorConfig` 的「当前主角」会读到它。
    // ★ 属主判定一律走上面那两个函数（唯一真源），不要在这里再写一遍 agent id 字面量。
    //   （nextAgentId 已在本 watch 顶部声明，直接复用，不重复 const）
    if (!isProductLoaderAgent(nextAgentId)) {
      currentWorkingProduct.value = null
    }
    if (!isCandidateLoaderAgent(nextAgentId)) {
      currentWorkingCandidate.value = null
    }
    // ★ 第 298 轮：第三个 ref 同样要成对处理 —— 只清前两个，它会静默残留。
    //   ⚠️ 这不影响「台账 → 对话」那条路径：它切的目标正是 customer-service
    //     （本谓词的属主）⇒ `!isReviewLoaderAgent(...)` 为假、不会清刚写进去的对象。
    if (!isReviewLoaderAgent(nextAgentId)) {
      currentWorkingReview.value = null
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
  // ★ 第 298 轮：差评工作台「💬 在对话里处置这条」（三个入口共用出口）
  window.addEventListener('review-send-to-chat', handleReviewToChat as EventListener)
  window.addEventListener('open-memory-drawer', () => { memoryDrawerOpen.value = true })
  window.addEventListener('open-settings-drawer', () => { settingsDrawerOpen.value = true })
  window.addEventListener('open-audit-drawer', () => { auditDrawerOpen.value = true })
  // 新手引导的两条幂等布局命令（发命令侧：components/Tour/TourHost.vue）
  window.addEventListener('tour:ensure-sidebar', ensureSidebar)
  window.addEventListener('tour:ensure-right-panel', ensureRightPanel)

  // ★★ 店铺列表 = 应用级基础数据，必须在主界面挂载时主动拉一次。
  //    曾经它只在「店铺群」弹层挂载时（ShopPopoverContent.onMounted）加载，
  //    导致不点开弹层就 `shops=[]`：左上角店铺名不显示（`currentShop` 算不出）、
  //    AI 说「切换到 X 店」时 `switch_shop` 找不到目标被静默丢弃。
  //    这里是**唯一权威的启动加载点**；弹层内的 refreshShopList 保留（增删后刷新用）。
  //    下面 `watch(currentShopId)` 会在本调用写回 currentShopId 后自动触发资料库加载。
  // ★★ C 档（2026-09-17）：账户上下文也是应用级基础数据，与店铺列表同批加载。
  //
  //   顺序是**串行**的（先店铺 → 后账户 → 再校正），不是并发，理由是：
  //     · `syncCurrentShopToAccount()` 需要 `shops` 已就绪才知道"该切到哪一家"。
  //       并发时它可能先跑（此时列表为空 ⇒ 无从校正），而店铺加载完成后
  //       **不会**再回来纠正 —— 表现为「切了账户，列表仍停在上一个账户的店」。
  //     · `loadAccounts()` 在演示模式下**直接早退**（demo-token 不是身份，
  //       发请求会 401 并触发跳登录页）⇒ 此时 currentAccountId 保持 null，
  //       店铺列表不做账户过滤，与演示模式"业务数据不设限"的既有语义一致。
  void (async () => {
    await shopStore.ensureShopsLoaded()
    await accountStore.loadAccounts()
    accountStore.syncCurrentShopToAccount()
  })()

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
  window.removeEventListener('review-send-to-chat', handleReviewToChat as EventListener)
  window.removeEventListener('tour:ensure-sidebar', ensureSidebar)
  window.removeEventListener('tour:ensure-right-panel', ensureRightPanel)
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
 * 差评工作台「💬 在对话里处置这条」跳转（第 298 轮）。
 *
 * 三个界面入口共用一个出口（`ReviewDeskConfig.vue::emitReviewToChat`）：
 * 抽屉右上角 / 台账行 / 差评列表卡片 —— 事件名 `review-send-to-chat`。
 *
 * 时序与 `launchProductToAgent` 同族（清工具 → 切视图 → 载对象 → 切 Agent），
 * 差别只在对象写进的是 `currentWorkingReview` —— 与 `currentWorkingProduct` /
 * `currentWorkingCandidate` 并列的第三份真源，由 `useAgentShortcuts` 的
 * `contextTarget` 派生成请求体里的 `context_target`。
 */
const handleReviewToChat = (e: Event) => {
  const review = (e as CustomEvent).detail
  if (!review) return
  // Step 0: 清掉旧工具选择 —— **只在真的要换 Agent 时**清。
  //   ★★ 第 298 轮修（老板 bug1「点【带进对话】大屏模式直接没了」）：
  //     原实现**无条件** `currentSelectedTool.value = null`，而
  //     `hasWideBoard = isWideBoardAgent || isReviewDeskTool`，
  //     `isReviewDeskTool` 判的正是 `currentSelectedTool?.id === 'review-desk'`
  //     ⇒ 点下去那一刻 `hasWideBoard` 变假：顶栏「对话/大屏」切换器消失、
  //       根节点 `review-data-mode` 类消失、右栏从「吃满剩余宽度」缩回 340、
  //       连台账面板本身都被清空。真机实测（前→后）：
  //       `{dataMode:true, switchN:2, siderW:1004, rdRoot:true}`
  //       → `{dataMode:false, switchN:0, siderW:340, rdRoot:false}`。
  //   ★ 那段清空是从 `launchProductToAgent` / `handleMonitorLaunchAnalysis` 抄来的，
  //     但那两处的**源在资料库视图**（面板本就不该活着）、目标 Agent 也不同；
  //     本处的源**就是那个面板本身**，且目标 Agent **就是当前 Agent**
  //     （`review-desk` 只挂在 customer-service 名下）⇒ 清空是错的。
  //   ★ 语义：用户自己选的「大屏模式」不该被一个"带进对话"的按钮悄悄撤销。
  const needSwitch = currentAgent.value?.id !== 'customer-service'
  if (needSwitch) currentSelectedTool.value = null
  // Step 1: 切到对话视图
  currentView.value = 'chat'
  rightPanelCollapsed.value = false
  // Step 2: 载入全局「当前处置的差评」
  currentWorkingReview.value = review
  // Step 3: 若目标 Agent 未选中则切换（Agent 侧 watch 会自动把 view 带回 chat）
  if (needSwitch) {
    const targetAgent = agentStore.agentList.find((a: any) => a.id === 'customer-service')
    if (targetAgent) agentStore.setCurrentAgent(targetAgent)
  }
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
  /* ★ 第 260 轮：老板要求「左侧边栏不出现滚轮」。两条一起做才成立 ——
     ① 把内容压到不溢出（规格见 src/styles/sidebar-nav.css）；
     ② 万一窗口比内容还矮、确实需要滚动，也**不显示**滚动条：
        滚轮 / 触控板照旧可滚，内容不会丢，账户入口另有粘底兜住。
     scrollbar-width 是标准属性（Chrome 121+ / Firefox）；::-webkit- 那条覆盖旧内核。 */
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.sidebar::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

:deep(.ant-layout-sider-children) {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 100%;
  /* ★ 第 260 轮：这两行**保持原样**，刻意不动。
     曾按「写死 height 会让 sticky 无处可粘」的推断把它改成只留 min-height，
     实测否定：856 / 768 两档下把 `height: 100%` 去掉前后，
     这个盒子的 computed height **都是 768px**、账户入口的位置逐像素相同
     （`.ant-layout-sider` 自己是 flex 容器，这个盒子被拉伸定高，height 与 min-height 谁在都一样）。
     ⇒ 无收益的改动不留（改了还得配一条永远测不出差别的判据）。
     窗口变矮时账户入口靠 `.account-entry` 自己的 `position: sticky; bottom: 0` 兜住，
     与这里写哪一行无关。 */
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

/* 右侧面板展开按钮（第 283 轮）：带边框，与三个无边框的对话操作按钮区分开 ——
   它是「面板控制」，不是「对话操作」，混在一起用户看不出哪个会改变布局。 */
.panel-expand-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: var(--space-12);
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-8);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  font-size: var(--font-size-13);
  line-height: 1;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.18s ease;
}

.panel-expand-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--bg-active-light);
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
  /* 400px = PANEL_W.boardChat（src/config/layout.ts）—— 改宽度两处一起改 */
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
   —— AIGC 也保留：大屏模式下仍需顶部工具栏切换 3 个工具（静态素材/脚本/视频）
   —— 选品三工具也保留（第 313 轮从"只有选品大盘"扩到全部三个，与 AIGC 对齐）：
      右栏顶部已有同一份工具 Tab 栏（`aigc-tool-tabs`，数据源同为
      `getAgentTools('product-research')`）⇒ 这里保留是刻意的**同源冗余入口**，
      两条路都能切工具，不会出现"切不回来"
      （判据同第 292 轮差评台账：面板里另有入口才允许隐藏这一排）。
   ★ class 名与判据同名（`isProductResearchWideTool` ↔ `product-research-data-mode`）：
     判据改名时这里必须一起改，否则整页布局生效而这一排工具栏被误隐藏。 */
.workspace-container.review-data-mode:not(.listing-data-mode):not(.aigc-data-mode):not(.product-research-data-mode) .inline-toolbar .toolbar-tools,
.workspace-container.review-data-mode:not(.listing-data-mode):not(.aigc-data-mode):not(.product-research-data-mode) .inline-toolbar .ant-divider {
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

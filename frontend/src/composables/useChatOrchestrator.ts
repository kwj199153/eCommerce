/**
 * ChatPanel 编排层（S3 拆分）
 *
 * 承载 ChatPanel 的全部「行为主干」：
 *   - 发送链路（SSE 流式渲染 + 非流式降级 + 各 Agent 分流）
 *   - 右侧面板 tool-analysis 事件的接收与执行
 *   - 各 Agent 顶部动作条 chip（竞品/选品/复盘/广告）
 *   - 工具结果摘要、Listing 草稿同步、脚本落库
 *   - 滚动定位
 *
 * 组件层（index.vue）只保留三类无法搬走的东西：
 *   1. v-model 绑定的 ref（inputMessage / intelDays）—— ref 必须由组件持有
 *   2. 模板 ref（messageListRef / mainContentRef）
 *   3. inject 注入值（loadedCandidate 等）—— 只能在组件 setup 中 inject
 * 这些通过 ChatOrchestratorOptions 以参数传入，保持 v-model 与 inject 语义不变。
 */
import { ref, computed, nextTick, watch, onMounted, onUnmounted, type Ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { message } from 'ant-design-vue'

import { useAgentStore } from '@/stores/agent'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import { useChatStore } from '@/stores/chat'
import { useShopStore } from '@/stores/shop'
import { useListingDraftStore } from '@/stores/listingDraft'
import { useProductLibraryStore } from '@/stores/productLibrary'
import { useRecentResultStore } from '@/stores/recentResult'
import { useVoiceTtsStore } from '@/stores/voiceTts'

import { ToolDefinition, getAgentTools } from '@/components/ChatPanel/tools/toolDefinitions'
import { toolExecutors, getParamSummary } from '@/mock/toolExecutors'
import { renderClarification, extractProductName } from '@/utils/clarification'
import { bandOf } from '@/theme/bands'

/** AIGC 三个工具：orchestrator 派发 aigc-result-ready 给右栏预览时用（与 ChatPanel AIGC_TOOLS 对齐）。 */
const AIGC_TOOL_IDS = new Set(['static-asset-gen', 'video-script-gen', 'ai-video-generator'])
/** CR4 市场集中度档位 → 中文标签（阈值见 bands.ts `cr4`） */
const CR4_LABEL: Record<string, string> = { high: '高度集中', medium: '中度集中', low: '充分竞争' }


export interface ChatOrchestratorOptions {
  /** 输入框内容：v-model 绑在组件模板上，须由组件持有 */
  inputMessage: Ref<string>
  /** 消息滚动容器：模板 ref，须由组件持有 */
  messageListRef: Ref<HTMLElement | undefined>
  /** 主内容区容器：模板 ref，须由组件持有 */
  mainContentRef: Ref<HTMLElement | undefined>
  /** 竞品监控分析周期：v-model 绑在组件模板上，须由组件持有 */
  intelDays: Ref<number>
  /** 选品分析师当前载入的评估主角：inject 自 Workspace，须由组件注入后传入 */
  loadedCandidate: Ref<any>
}

export function useChatOrchestrator(opts: ChatOrchestratorOptions) {
  const agentStore = useAgentStore()
  const chatStore = useChatStore()
  const pool = useMonitorPoolStore()
  const candStore = useCandidateLibraryStore()
  const shopStore = useShopStore()
  const productLibraryStore = useProductLibraryStore()
  const recentResultStore = useRecentResultStore()

  const { inputMessage, messageListRef, mainContentRef, intelDays, loadedCandidate } = opts

  // ===== 语音播报：边生成边念（首期只服务店秘书） =====
  //
  // 为什么放在编排层、而不是去每个 Agent 的回复分支里各加一行：
  // 「扩展到其他 Agent」应该是**改白名单**，而不是回头改 6 个分支。
  // 所以这里统一监听「当前对话区最后一条 assistant 消息」，把它渐进喂给播报队列。
  //
  // ★★ 已废弃的旧做法（P0+P1，2026-09-14）：`SPEAK_SETTLE_MS = 700` 防抖。
  //    它的语义是「每个 delta 都重置计时器」⇒ 等价于「等整段说完，再等 700ms 才
  //    开始合成」⇒ 首声实测 8.7s（正文 7.6s 与合成 5.2s 串起来）。
  //    现在改成**分句流水线**：每个 delta 都把「目前为止的正文」交给 store，
  //    由它调后端 /speak-plan 算出**已定型**的段，边生成边合成、边合成边播 ⇒
  //    首声只等第一段（实测 ~1.1s）。
  //
  // 仍然必须处理的时序问题（都不是理论问题）：
  // 1. **认本轮**：`runKey` = `agentId#timestamp`，变了就是新回复 → store 重置游标。
  //    ★ runKey **不能带正文长度** —— 长度随每个 delta 变，含进去等于每次增量都
  //    开新一轮、从头重念。长度只用于**触发** watch（见下面的 getter）。
  // 2. **交接**：店秘书回复后 ~700ms 会切到子 Agent，对话区随之切换 ——
  //    所以每次都从**当前快照**取正文，不缓存旧引用。
  // 3. **收尾**：正文停止增长后再喂一次 `streaming=false`，让 store 念掉结尾那段
  //    尚未定型的碎片（否则最后半句永远不念）。这个 300ms 只影响**尾巴**，
  //    不影响首声 —— 首声由流式期间**已定型**的段决定。
  const voiceTts = useVoiceTtsStore()
  const SPEAK_TAIL_MS = 300
  let speakTailTimer: ReturnType<typeof setTimeout> | null = null

  /**
   * 取「当前对话区最后一条 assistant 消息」。
   *
   * 用 `chatStore.activeAgentId`（而不是 `agentStore.currentAgent`）判归属：
   * `chatStore.messages` 就是按 activeAgentId 切的，两者必须同源，
   * 否则会拿 A 的回复去套 B 的白名单。
   */
  function lastAssistantSnapshot(): { agentId: string; text: string; runKey: string } | null {
    const list = chatStore.messages
    const last = list[list.length - 1]
    if (!last || last.role !== 'assistant') return null
    const text = (last.content || '').trim()
    if (!text) return null
    const agentId = chatStore.activeAgentId
    return { agentId, text, runKey: `${agentId}#${last.timestamp}` }
  }

  watch(
    () => {
      const snap = lastAssistantSnapshot()
      // ★ 触发源必须含正文长度：`appendToLastMessage` 只改 content，
      //   不含长度的话 watch 在流式期间根本不会触发。
      return snap ? `${snap.runKey}#${snap.text.length}` : ''
    },
    () => {
      const snap = lastAssistantSnapshot()
      if (!snap) return
      // 白名单判定只认 store（唯一真源），这里不重复写 Agent id
      if (!voiceTts.supports(snap.agentId)) return
      if (!voiceTts.enabled) return
      // ★★ 「本轮」闸门：只念**刚刚被提问的那个对话区**的回复。
      //   没有这道闸，下面两种情况会凭空开口：
      //   ① 开屏欢迎语 —— 它也是 assistant 消息，于是每次刷新都念一遍；
      //   ② 切面板回来 —— activeAgentId 一变 watch 就触发，读到的是历史回复，
      //      而此时 runKey 没见过 ⇒ setupRun 重置游标 ⇒ 从头再念一遍。
      //   判据来自 chatStore.lastUserMessage（唯一写入点在 chatStore.addMessage）。
      if (chatStore.lastUserMessage?.agentId !== snap.agentId) return

      // ① 立刻喂：已定型的段马上开始合成 ⇒ 首声不必等正文说完
      voiceTts.feed(snap.text, { runKey: snap.runKey, streaming: true })

      // ② 尾部兜底：正文停 300ms 没再长 ⇒ 认为说完了，把结尾碎片也念掉
      if (speakTailTimer) clearTimeout(speakTailTimer)
      speakTailTimer = setTimeout(() => {
        speakTailTimer = null
        if (!voiceTts.enabled) return
        voiceTts.feed(snap.text, { runKey: snap.runKey, streaming: false })
      }, SPEAK_TAIL_MS)
    }
  )

  /**
   * 会话结论入库（SSE meta 事件）。
   *
   * 一处分发、两处落点：
   * - chatStore：回填最后一条消息的 displayType/data → 消息流里渲染「结论卡」
   * - recentResultStore：按 agentId 存「最近结果」→ 清空对话后仍可从顶部找回
   *
   * 注意 meta 只是**增强**：正文（content）已自带完整结论清单，
   * 后端未下发 meta 时对话照常可读，只是少了卡片承托。
   */
  function handleAgentMeta(meta: { display_type?: string; data?: any }) {
    if (!meta?.display_type) return
    chatStore.setLastMessageResult(meta.display_type, meta.data)
    recentResultStore.setRecent(agentStore.currentAgent?.id || 'default', {
      displayType: meta.display_type,
      data: meta.data,
      summary: meta.data?.summary || '',
    })
  }

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
    setLoading(true, 'candidate-chip')
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
      setLoading(false, 'candidate-chip-finally')
      setTimeout(() => { activeIntelChip.value = null }, 400)
    }
  }

  /** 点选 chip → 直接跑竞品监控 mock 推理（读右侧圈选 ASIN） */
  const runIntelChip = async (c: (typeof intelChips)[number]) => {
    if (isLoading.value) return
    activeIntelChip.value = c.id
    setLoading(true, 'intel-chip')
    const { analyzeCompetitorIntel } = await import('@/mock/competitorIntel')
    // 监控池是后端权威源：推理读的是 store 快照，先确保已加载（否则会把"未加载"当成"池是空的"）
    await pool.ensureLoaded()
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
      setLoading(false, 'intel-chip-finally')
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

  // 加载状态
  const isLoading = ref(false)

  // 长任务反馈：阶段进度文案（后端 progress 事件驱动）+ 已用秒数（前端计时）
  // 背景：结构化分析（蓝海/竞品/广告诊断等）后端需 15-25s 才能吐出结果，
  // 期间零输出，只显示「AI 正在思考…」会让用户以为卡死。
  const loadingStatus = ref('')
  const elapsedSec = ref(0)
  let elapsedTimer: ReturnType<typeof setInterval> | null = null
  const startElapsedTimer = () => {
    elapsedSec.value = 0
    if (elapsedTimer) clearInterval(elapsedTimer)
    elapsedTimer = setInterval(() => { elapsedSec.value += 1 }, 1000)
  }
  const stopElapsedTimer = () => {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
  }
  /** 加载提示文案：默认「AI 正在思考...」，有阶段进度则用之；超过 3s 追加已用时长 */
  const loadingTip = computed(() => {
    const base = loadingStatus.value || 'AI 正在思考...'
    return isLoading.value && elapsedSec.value >= 3 ? `${base}（已用 ${elapsedSec.value}s）` : base
  })

  // 看门狗：兜底"AI 正在思考…"卡死
  // 任何路径把 isLoading=true 后若 60s 内未释放（流式网络挂起、同步函数异常吞掉等），
  // 强制置 false 并插入一条错误消息，避免用户面对永久 spinner 无可操作。
  const LOADING_WATCHDOG_MS = 60_000
  let loadingWatchdogTimer: ReturnType<typeof setTimeout> | null = null
  const setLoading = (on: boolean, source: string) => {
    isLoading.value = on
    if (on) {
      startElapsedTimer()
      if (loadingWatchdogTimer) clearTimeout(loadingWatchdogTimer)
      loadingWatchdogTimer = setTimeout(() => {
        if (isLoading.value) {
          isLoading.value = false
          loadingWatchdogTimer = null
          stopElapsedTimer()
          console.warn(`[isLoading 看门狗] 60s 未释放（来源：${source}），强制重置`)
          try {
            chatStore.addMessage({
              role: 'assistant',
              content: '⏱️ **请求超时**：超过 60 秒未收到响应，可能是网络异常或后端服务未启动。\n\n请确认：① 后端 `uvicorn main:app --port 8000` 是否运行；② 网络是否可达。点击重试。',
            })
          } catch { /* 兜底中的兜底 */ }
        }
      }, LOADING_WATCHDOG_MS)
    } else {
      stopElapsedTimer()
      loadingStatus.value = ''
      if (loadingWatchdogTimer) {
        clearTimeout(loadingWatchdogTimer)
        loadingWatchdogTimer = null
      }
    }
  }

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
    window.addEventListener('secretary-handoff', handleSecretaryHandoff as unknown as EventListener)
    window.addEventListener('agent-auto-task', handleAgentAutoTask as unknown as EventListener)
  })

  onUnmounted(() => {
    window.removeEventListener('tool-analysis', handleToolAnalysisEvent as unknown as EventListener)
    window.removeEventListener('secretary-handoff', handleSecretaryHandoff as unknown as EventListener)
    window.removeEventListener('agent-auto-task', handleAgentAutoTask as unknown as EventListener)
    // 对话区销毁（离开对话视图）→ 立刻停声，别再触发播报
    if (speakTailTimer) clearTimeout(speakTailTimer)
    voiceTts.stop()
  })

  // 处理主 Agent 交接：切到子 Agent 后，由子 Agent「接管」并逐项追问缺失字段
  const handleSecretaryHandoff = (event: CustomEvent) => {
    const { agentId, intent, missingFields } = event.detail || {}
    if (!agentId) return

    const targetAgent = agentStore.agentList.find(a => a.id === agentId)
    const agentName = targetAgent?.name || agentId

    // 在目标 Agent 对话区渲染「子 Agent 接管 + 追问」消息
    chatStore.setActiveAgent(agentId)

    // 字段 → 口语化问答模板（含产品名）
    const productName = extractProductName(intent)
    const { greeting, questions } = renderClarification({
      fields: Array.isArray(missingFields) ? missingFields : [],
      productName,
    })

    // 招呼语 + 追问气泡
    const questionLines = questions.map(q => {
      const ex = q.examples?.length ? `\n   比如：${q.examples.slice(0, 3).join(' / ')}` : ''
      return `• **${q.label}**：${q.question}${ex}`
    }).join('\n')

    const takeoverMsg = questionLines
      ? `${greeting}\n\n${questionLines}\n\n不想挨个说也行，直接给我一段描述，我来拆。`
      : greeting

    chatStore.addMessage({
      role: 'assistant',
      content: takeoverMsg,
    }, agentId)
    scrollToBottom()
  }

  // 处理主 Agent「路由带参」：切到子 Agent 后，把老板原话注入它的对话区并自动续跑。
  // 触发方：dispatchAppAction（switch_agent 带 query）→ agent-auto-task 事件。
  const handleAgentAutoTask = async (event: CustomEvent) => {
    const { agentId, query } = event.detail || {}
    if (!agentId || !query) return

    // 确保对话区路由到目标 Agent（switch_agent 已切过，这里幂等兜底）
    chatStore.setActiveAgent(agentId)

    // 回显老板原话（标注来源，便于追溯），再让子 Agent 接着执行
    chatStore.addMessage({ role: 'user', content: `（店秘书转达）${query}` }, agentId)
    await scrollToBottom()

    setLoading(true, 'agent-auto-task')
    try {
      // 此时 agentStore.currentAgent 已是子 Agent，simulateAgentResponse 会分流到它自己的链路
      await simulateAgentResponse(query)
    } catch (e) {
      console.error('[路由续跑] 子 Agent 执行失败:', e)
      chatStore.addMessage({ role: 'assistant', content: '（子 Agent 执行失败，请稍后重试）' }, agentId)
    } finally {
      setLoading(false, 'agent-auto-task-finally')
      await scrollToBottom()
    }
  }

  // 处理来自右侧面板的分析请求
  const handleToolAnalysisEvent = async (event: CustomEvent) => {
    const { tool, params, mode } = event.detail

    if (!tool) return

    // AIGC 大屏模式：结果只在右侧预览区显示，不进对话流（避免对话区和大屏结果冗余）
    const skipChatStream = mode === 'data' && AIGC_TOOL_IDS.has(tool.id)

    // 设置当前工具状态
    selectedTool.value = { ...tool }
    currentMode.value = 'tool'
    // AIGC 大屏模式：loading 交给右栏预览区展示。
    // 结果不进对话流，若仍在对话区转圈，用户会以为卡在了一个没有输出的地方。
    if (skipChatStream) {
      window.dispatchEvent(new CustomEvent('aigc-generating', {
        detail: { toolId: tool.id, generating: true }
      }))
    } else {
      setLoading(true, 'tool-click')
    }

    // ===== 竞品监控员·智能推理工具（读监控池 → 解读+证据，不走 form 结果表）=====
    if (['intel-chat', 'intel-weekly', 'intel-anomaly', 'intel-strategy'].includes(tool.id)) {
      try {
        const { analyzeCompetitorIntel } = await import('@/mock/competitorIntel')
        await pool.ensureLoaded()
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
        setLoading(false, 'tool-click-finally')
      }
      return
    }

    // ===== 步骤1：添加用户消息（独立 try-catch）=====
    // AIGC 大屏模式：跳过对话流，结果直接展示在右侧预览区
    if (!skipChatStream) {
      try {
        const paramSummary = getParamSummary(tool.id, params || {})
        chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${paramSummary}` })
      } catch (msgError) {
        console.warn('参数摘要生成失败（使用 fallback）:', msgError)
        chatStore.addMessage({ role: 'user', content: `📋 **${tool.name}** 参数：\n${JSON.stringify(params || {}, null, 2)}` })
      }
    }

    // ===== 步骤2：执行分析（主 try-catch）=====
    try {
      // 利润测算：与右栏面板同源。面板已经调后端算过一份就原样沿用，
      // 绝不在前端用另一套公式复算 —— 「一个表单两个结果」就是这么来的。
      let result: any
      if (tool.id === 'profit-calc') {
        result = await resolveProfitResult(params)
      } else {
        const executor = toolExecutors[tool.id]
        if (!executor) {
          throw new Error(`未知工具: ${tool.id}`)
        }
        result = await executor(params)
      }

      // 视频脚本同步到共享 store（供 AI 短视频生成「分镜脚本专业模式」复用）
      if (tool.id === 'video-script-gen') {
        saveScriptToStore(result)
      }

      // Listing 工具结果同步到「Listing 工作区」草稿（右侧面板可直接接着编辑/保存）
      syncListingDraft(tool.id, params, result)

      // ===== 步骤3：将结果插入对话流（或大屏下直接派发给右栏预览）=====
      if (skipChatStream) {
        // AIGC 大屏模式：直接广播给右栏预览，不经对话流（避免对话区与大屏结果冗余）
        window.dispatchEvent(new CustomEvent('aigc-result-ready', {
          detail: { toolId: tool.id, result }
        }))
      } else {
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
      if (skipChatStream) {
        // AIGC 大屏模式：失败提示走顶部 toast，不污染对话流
        message.error(`❌ ${tool.name} 执行失败：${err?.message || '未知错误'}`)
      } else {
        chatStore.addMessage({
          role: 'assistant',
          content: `❌ 分析执行失败，请检查参数后重试。\n\n\`${err?.message || '未知错误'}\``,
        })
      }
    } finally {
      // AIGC 大屏模式：收掉预览区 loading（setLoading(false) 此时幂等无害，保留兜底）
      if (skipChatStream) {
        window.dispatchEvent(new CustomEvent('aigc-generating', {
          detail: { toolId: tool.id, generating: false }
        }))
      }
      setLoading(false, 'tool-click-finally2')
      await scrollToBottom()
    }
  }

  /**
   * 利润测算结果：以后端 /stores/profit/calculate 为唯一计算源。
   * 面板带过来的 _preview 就是后端响应，直接沿用；没有（从对话侧触发）才自己调一次。
   */
  const resolveProfitResult = async (params: any) => {
    const { calculateProfit, toProfitRequest } = await import('@/api/stores')
    if (params?._preview) return params._preview
    const shopId = shopStore.currentShopId
    if (!shopId) throw new Error('未选择店铺，无法获取费率模板')
    return await calculateProfit(toProfitRequest(params), shopId)
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
          `- CR4集中度：${result.concentration_ratio?.cr4?.toFixed(1)}%（${CR4_LABEL[bandOf('cr4', result.concentration_ratio?.cr4 || 0)] || '-'}）\n\n` +
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
        content = `🔎 **评论侦探完成** — 分析 **${reviewProduct?.brand || '-'}** (${reviewProduct?.asin || '-'})\n\n` +
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
    setLoading(true, 'send-message')

    try {
      await simulateAgentResponse(text)
    } catch (error) {
      message.error('发送失败，请重试')
    } finally {
      setLoading(false, 'send-finally')
    }
    await scrollToBottom()
  }

  // Agent 响应处理（复用原有逻辑）
  const simulateAgentResponse = async (userMessage: string) => {
    // 店秘书（全局入口 · 编排层）：一个大脑，既能导航（切 Agent / 开资料库）又能执行（调工具出结果）
    if (agentStore.currentAgent?.id === 'secretary') {
      const { dispatchAppAction } = await import('@/utils/appActions')

      // 首选：后端主 Agent（LLM + bind_tools，导航与执行统一用 tool_calls 表达）
      try {
        const { chatWithSecretary } = await import('@/api/secretary')

        // 会话级记忆：取本 Agent（secretary）对话区的历史消息，排除刚 push 的当前这条，
        // 截取最近 N 条传给后端，让 LLM 感知多轮上下文（如「再切换」能理解上一轮主题）。
        const HISTORY_LIMIT = 10
        const currentHistory = chatStore.getMessages('secretary')
        const history = currentHistory
          .slice(0, -1) // 去掉最后一条（= 当前 userMessage）
          .slice(-HISTORY_LIMIT)
          .filter((m: any) => m.content && typeof m.content === 'string')
          .map((m: any) => ({ role: m.role, content: m.content }))

        // 决策层 B：跨会话记忆 —— 取持久化的 sessionId（若有），后端据此从 DB 恢复历史
        const sessionId = chatStore.getSessionId('secretary')

        const res = await chatWithSecretary({ message: userMessage, history, session_id: sessionId })

        // 保存后端返回的 sessionId（跨会话记忆的关键：刷新后凭它恢复历史）
        if (res.session_id) {
          chatStore.setSessionId('secretary', res.session_id)
        }

        // 动作：交给 dispatchAppAction 按顺序落地（切 Agent / 打开资料库 / 选中产品）
        // 后端返回有序 actions 列表（如「先选产品，再切 Agent」），依次执行；
        // 向后兼容：无 actions 时退回单个 action。
        const actionList = (res.actions && res.actions.length > 0)
          ? res.actions
          : (res.action ? [res.action] : [])

        const hasHandoff = actionList.some((a: any) => a?.action === 'handoff')

        // ★ 店铺切换必须**同步**落地并检查结果：
        //   它是「环境切换」而非异步副作用 —— 用户说完就该看到左上角变了。
        //   若只把它塞进下面的 setTimeout 里、又不看返回值，就会出现
        //   「回复说已切换、左上角却没换」——用户读到的是 AI 撒谎，实际是动作被静默丢弃。
        //   所以：先同步执行 → 拿到成败 → 再决定回复文案。
        //   注：`switch_shop` 本身只依赖 id（无前置依赖），正常恒成功；
        //   失败路径仅兜底「后端给了空 id」这种畸形数据。
        const shopAction: any = actionList.find((a: any) => a?.action === 'switch_shop' && a?.shop?.id)
        let shopSwitchFailed = false
        let shopSwitchName = ''
        if (shopAction) {
          shopSwitchName = shopAction.shop?.name || ''
          shopSwitchFailed = !dispatchAppAction({
            type: 'switch_shop',
            shopId: shopAction.shop.id,
            shopName: shopAction.shop?.name,
            platform: shopAction.shop?.platform,
          })
        }

        // 渲染回复文本
        // 若有 handoff 动作：LLM 的 reply 通常会复述字段名/工具名，对用户不友好，
        // 这里覆盖为简洁的"已交接"模板，详细追问交给子 Agent 对话区渲染。
        let displayReply = res.reply || '处理完成'
        if (shopSwitchFailed) {
          // 显式降级 + 给原因（项目铁律：禁止静默假装成功）
          displayReply = shopSwitchName
            ? `> ⚠️ 没能切换到「${shopSwitchName}」——后端未给出有效的店铺标识。请在左上角「店铺群」里手动选择。`
            : '> ⚠️ 没能切换店铺——后端未给出有效的店铺标识，请在左上角「店铺群」里手动选择。'
        } else if (hasHandoff) {
          const handoffAct: any = actionList.find((a: any) => a?.action === 'handoff')
          const targetAgent = agentStore.agentList.find(a => a.id === handoffAct?.agentId)
          const agentLabel = targetAgent?.name || '专业助手'
          displayReply = `好嘞，这事儿交给 **${agentLabel}** 处理，他会在自己的对话里跟你确认几个细节，确认完就开干。`
        }
        chatStore.addMessage({ role: 'assistant', content: displayReply })
        await scrollToBottom()

        actionList.forEach((act, i) => {
          // 每个动作稍作错开（700ms + 序号），让前一个动作先落地
          setTimeout(() => {
            const { action, agentId, view, product, drawer, target, intent, missing_fields, mode, shop, query } = act as any
            if (action === 'switch_agent' && agentId) {
              // query 非空 → 路由带参：dispatchAppAction 会派发 agent-auto-task 事件，
              // 由 handleAgentAutoTask 把老板原话注入子 Agent 对话区并自动续跑。
              dispatchAppAction({ type: 'switch_agent', agentId, query })
            } else if (action === 'navigate' && view) {
              dispatchAppAction({ type: 'navigate', view })
            } else if (action === 'select_product' && product?.id) {
              dispatchAppAction({ type: 'select_product', productId: product.id })
            } else if (action === 'open_drawer' && drawer) {
              dispatchAppAction({ type: 'open_drawer', drawer })
            } else if (action === 'account_menu' && target) {
              dispatchAppAction({ type: 'account_menu', target })
            } else if (action === 'set_theme' && mode) {
              dispatchAppAction({ type: 'set_theme', mode })
            } else if (action === 'switch_shop') {
              // 已在上方同步执行（含失败回报），此处跳过，避免重复 dispatch。
            } else if (action === 'handoff' && agentId) {
              dispatchAppAction({
                type: 'handoff',
                agentId,
                intent: intent || '',
                missingFields: Array.isArray(missing_fields) ? missing_fields : [],
              })
            }
          }, 700 + i * 300)
        })
        return
      } catch (error) {
        // 后端不可用（演示模式 401 / 后端未启动）→ 降级到前端正则识别
        console.warn('[店秘书] 后端 orchestrator 不可用，降级到本地正则识别:', error)
      }

      // 降级：前端正则识别（规则式，覆盖常见说法）
      try {
        const { recognizeSecretaryIntent } = await import('@/mock/secretaryBrain')
        const out = recognizeSecretaryIntent(userMessage)
        // 显式提示降级原因：静默降级会让用户误以为「AI 变笨了 / React 没做好」，
        // 实际是后端服务不可用（未启动 / 500）。提示后用户能自行判断是否需要排查服务。
        chatStore.addMessage({
          role: 'assistant',
          content: `> ⚠️ 后端服务暂时不可用，已切换到本地简易识别（能力有限）\n\n${out.reply}`,
        })
        await scrollToBottom()
        const fallbackAction = out.action
        if (fallbackAction) {
          setTimeout(() => dispatchAppAction(fallbackAction), 700)
        }
      } catch (error) {
        console.error('店秘书调度失败:', error)
        chatStore.addMessage({ role: 'assistant', content: '❌ 调度执行失败，请重试。' })
      }
      return
    }

    // 选品分析师
    if (agentStore.currentAgent?.id === 'product-research') {
      try {
        const { chatWithProductResearcher } = await import('@/api/productResearch')
        const { streamSSE } = await import('@/api/stream')

        // 文本对话：优先 SSE 流式渲染，失败降级到非流式
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        // 会话 ID 必须带上：后端「入库待补槽位」「上一轮蓝海结果」都按会话隔离，
        // 不带就退化成全局共享（多会话串数据），而且「追问 → 补充 → 入库」
        // 这种多轮补齐也无从进行。
        const contextId = chatStore.ensureSessionId('product-research')
        await streamSSE(
          '/product-research/chat/stream',
          { message: userMessage, context_id: contextId },
          {
          onProgress: (text) => { loadingStatus.value = text },
          onMeta: handleAgentMeta,
          onDelta: (text) => {
            streamed = true
            setLoading(false, 'sse-delta-product')
            chatStore.appendToLastMessage(text)
          },
          onDone: (fullText) => {
            // 结构化结果（蓝海/利润等）在 done 事件前通过 meta 推送，此处兜底
            if (!fullText && !streamed) {
              chatStore.appendToLastMessage('（未获取到分析结果）')
            }
          },
          onError: async () => {
            // 流式失败（如鉴权 401）→ 回退到非流式对话
            if (streamed) return  // 已输出部分内容，不再追加全文避免重复
            try {
              const response = await chatWithProductResearcher({
                message: userMessage,
                context_id: contextId,
              })
              chatStore.appendToLastMessage(response.reply || '分析完成')
              // ★ 兜底路径**同样要回填结构化结果**（第 131 轮 item2-C）。
              //   只 append 正文的话，流式失败时用户会看到后端那句
              //   「请选择『批准』或『拒绝』」却**没有任何按钮可点** ——
              //   一句无法执行的指令，比不显示更糟。
              //   审批卡与结论卡都只靠 `display_type` + `data` 渲染。
              if (response?.display_type) {
                chatStore.setLastMessageResult(response.display_type, response.data)
              }
            } catch (e2) {
              if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
                chatStore.appendToLastMessage('（对话失败，请重试）')
              }
            }
          },
          },
        )
        return
      } catch (error) {
        console.error('选品 API 失败:', error)
      }
    }

    // Listing 优化师
    if (agentStore.currentAgent?.id === 'listing-generator') {
      try {
        const { chatWithListingAgent, generateListing } = await import('@/api/listingGenerator')
        const { streamSSE } = await import('@/api/stream')
        const isGenerateRequest =
          userMessage.includes('生成') || userMessage.includes('写') ||
          userMessage.includes('创建') || userMessage.toLowerCase().includes('generate')

        // 完整 Listing 生成走结构化接口（结果落右栏）
        if (isGenerateRequest) {
          let response: any = await generateListing({
            product_name: userMessage.replace(/生成|写|创建|listing|Listing/gi, '').trim() || 'New Product',
            generate_ab_variants: false,
          })
          response = response.data

          chatStore.addMessage({
            role: 'assistant',
            content: response.summary || response.response || '完成',
            data: response,
            displayType: response.type || 'complete_listing',
          })
          return
        }

        // 文本类对话：SSE 流式渲染（打字机效果）
        chatStore.addMessage({ role: 'assistant', content: '' })
        await streamSSE('/listing/chat/stream', { message: userMessage }, {
          onProgress: (text) => { loadingStatus.value = text },
          onMeta: handleAgentMeta,
          onDelta: (text) => {
            setLoading(false, 'sse-delta-listing')  // 首 token 到达即隐藏"思考中"spinner
            chatStore.appendToLastMessage(text)
          },
          onError: () => {
            // 流式失败兜底：回退到非流式对话
            if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
              chatStore.appendToLastMessage('（流式连接中断，已切换普通模式）')
            }
          },
        })
        return
      } catch (error) {
        console.error('Listing API 失败:', error)
        // 兜底：非流式对话
        try {
          const { chatWithListingAgent } = await import('@/api/listingGenerator')
          const response: any = await chatWithListingAgent({ message: userMessage })
          const data = response.data
          chatStore.addMessage({
            role: 'assistant',
            content: data.summary || data.response || '完成',
            data: data,
            displayType: data.type || 'text',
          })
        } catch (e2) {
          console.error('Listing 兜底也失败:', e2)
        }
      }
    }

    // 广告分析师
    if (agentStore.currentAgent?.id === 'ad-analysis') {
      try {
        const { chatWithAdAnalyst, diagnoseAdAccount, analyzeSearchTerms, detectAnomalies } = await import('@/api/adAnalysis')
        const { streamSSE } = await import('@/api/stream')

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
        }

        if (response) {
          // 结构化结果：一次性渲染 + 落右栏
          // ★ P0-2 批 1 修正：原来 isDiagnosis 给的是 `displayType: 'ad_diagnosis'`，
          //   但 ChatPanel 的结果卡分派只认 `msg.data?.toolId` ⇒ 该 displayType
          //   **全仓没有任何渲染分支** ⇒ metrics / campaigns / top_issues 其实一直渲染不出来，
          //   用户只看得到一行 summary（「接线了但没渲染」比纯 mock 更隐蔽）。
          //   现改为与工具卡**共用同一个结果卡**，两个入口同一份真数据。
          chatStore.addMessage({
            role: 'assistant',
            content: response.reply || response.summary || '分析完成',
            data: isDiagnosis
              ? { toolId: 'ad-diagnosis', toolName: '广告诊断', resultData: response }
              : (response.data || response),
            displayType: isDiagnosis ? 'tool_result' : (response.display_type || undefined),
          })
          return
        }

        // 纯文本对话：SSE 流式渲染
        chatStore.addMessage({ role: 'assistant', content: '' })
        await streamSSE('/ad-analysis/chat/stream', { message: userMessage }, {
          onProgress: (text) => { loadingStatus.value = text },
          onMeta: handleAgentMeta,
          onDelta: (text) => {
            setLoading(false, 'sse-delta-ad')
            chatStore.appendToLastMessage(text)
          },
          onError: () => {
            if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
              chatStore.appendToLastMessage('（流式连接中断，已切换普通模式）')
            }
          },
        })
        return
      } catch (error) {
        console.error('广告分析 API 失败:', error)
      }
    }

    // 智能客服
    if (agentStore.currentAgent?.id === 'customer-service') {
      try {
        const { chatWithCustomerService, trackOrder, createTicket } = await import('@/api/customerService')
        const { streamSSE } = await import('@/api/stream')

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
        }

        if (response) {
          // 结构化结果（订单/工单）：一次性渲染 + 落右栏
          chatStore.addMessage({
            role: 'assistant',
            content: response.reply || response.message || '处理完成',
            data: response.data || response,
            displayType: response.display_type || 'text',
          })
          return
        }

        // 纯文本对话：SSE 流式渲染
        chatStore.addMessage({ role: 'assistant', content: '' })
        await streamSSE('/customer-service/chat/stream', { message: userMessage }, {
          onProgress: (text) => { loadingStatus.value = text },
          onMeta: handleAgentMeta,
          onDelta: (text) => {
            setLoading(false, 'sse-delta-cs')
            chatStore.appendToLastMessage(text)
          },
          onError: () => {
            if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
              chatStore.appendToLastMessage('（流式连接中断，已切换普通模式）')
            }
          },
        })
        return
      } catch (error) {
        console.error('客服 API 失败:', error)
      }
    }

    // 竞品监控员：自然语言 → 基于监控池 mock 推理（第 3 层推理层）
    if (agentStore.currentAgent?.id === 'competitor-intel') {
      try {
        const m = await import('@/mock/competitorIntel')
        await pool.ensureLoaded()
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

  // 滚动到底部
  // 注意：滚动容器是 .main-content（overflow-y:auto），.message-list 自身不滚动
  // （见 index.vue 样式注释「不再独立滚动，随 main-content 一起滚动」）。
  // 因此必须优先取 mainContentRef —— 取 messageListRef 时 scrollTop 设了也没用，
  // 表现为「新消息不自动滚到底」。
  const scrollToBottom = async () => {
    await nextTick()
    const target = mainContentRef.value || messageListRef.value
    if (target) target.scrollTop = target.scrollHeight
  }

  watch(messages, () => scrollToBottom(), { deep: true })

  return {
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
    // 消息/输入
    removeToolResult,
    handleNavigateTo,
    renderMarkdown,
    handleKeyPress,
    handleSend,
  }
}

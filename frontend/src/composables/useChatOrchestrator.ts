/**
 * ChatPanel 编排层（S3 拆分）
 *
 * 承载 ChatPanel 的全部「行为主干」：
 *   - 发送链路（SSE 流式渲染 + 非流式降级 + 各 Agent 分流）
 *   - 右侧面板 tool-analysis 事件的接收与执行
 *   - 各 Agent 顶部动作条 chip（竞品/选品/复盘/广告）
 *   - 工具结果摘要、Listing 草稿同步、脚本落库
 *   - HITL 审批、滚动定位
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

import { ToolDefinition, getAgentTools } from '@/components/ChatPanel/tools/toolDefinitions'
import { toolExecutors, getParamSummary } from '@/mock/toolExecutors'

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

  const { inputMessage, messageListRef, mainContentRef, intelDays, loadedCandidate } = opts

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

  // 看门狗：兜底"AI 正在思考…"卡死
  // 任何路径把 isLoading=true 后若 60s 内未释放（流式网络挂起、同步函数异常吞掉等），
  // 强制置 false 并插入一条错误消息，避免用户面对永久 spinner 无可操作。
  const LOADING_WATCHDOG_MS = 60_000
  let loadingWatchdogTimer: ReturnType<typeof setTimeout> | null = null
  const setLoading = (on: boolean, source: string) => {
    isLoading.value = on
    if (on) {
      if (loadingWatchdogTimer) clearTimeout(loadingWatchdogTimer)
      loadingWatchdogTimer = setTimeout(() => {
        if (isLoading.value) {
          isLoading.value = false
          loadingWatchdogTimer = null
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
    setLoading(true, 'tool-click')

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
        setLoading(false, 'tool-click-finally')
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
      const executor = toolExecutors[tool.id]
      if (!executor) {
        throw new Error(`未知工具: ${tool.id}`)
      }
      const result: any = await executor(params)

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
      setLoading(false, 'tool-click-finally2')
      await scrollToBottom()
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
    // 选品分析师
    if (agentStore.currentAgent?.id === 'product-research') {
      try {
        const { chatWithProductResearcher } = await import('@/api/productResearch')
        const { streamSSE } = await import('@/api/stream')

        // 文本对话：优先 SSE 流式渲染，失败降级到非流式
        chatStore.addMessage({ role: 'assistant', content: '' })
        let streamed = false
        await streamSSE('/product-research/chat/stream', { message: userMessage }, {
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
              const response = await chatWithProductResearcher({ message: userMessage })
              chatStore.appendToLastMessage(response.reply || '分析完成')
            } catch (e2) {
              if (!chatStore.messages[chatStore.messages.length - 1]?.content) {
                chatStore.appendToLastMessage('（对话失败，请重试）')
              }
            }
          },
        })
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
          chatStore.addMessage({
            role: 'assistant',
            content: response.reply || response.summary || '分析完成',
            data: response.data || response,
            displayType: response.display_type || (isDiagnosis ? 'ad_diagnosis' : undefined),
          })
          return
        }

        // 纯文本对话：SSE 流式渲染
        chatStore.addMessage({ role: 'assistant', content: '' })
        await streamSSE('/ad-analysis/chat/stream', { message: userMessage }, {
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
    handleHitlAccept,
    handleHitlReject,
  }
}

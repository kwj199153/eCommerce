/**
 * 对话编排层 · Agent 判定与技能卡动作条（第 169 轮 #664 拆分 / 第 189 轮改造）
 *
 * 四条动作条（竞品监控 / 选品分析 / 运营复盘 / 广告分析）与「当前是哪个 Agent」的判定。
 *
 * ★ 第 189 轮老板原话：「skill 当源（skill 列表 → 卡片）」「卡片 = skill（方法）+
 *   上下文条（参数）」「10 张不走 LLM 的卡片改成走 llm，前端调用后端」。
 *   落点就是本文件：卡片**不再是前端硬编码的常量数组**，而是当前 Agent 已启用的技能。
 *   改动前后对照（旧 → 新）：
 *
 *   | 组 | 旧来源 | 旧行为 | 新行为 |
 *   |---|---|---|---|
 *   | 竞品 3 | `intelChips` 常量 | 本地 mock 推理 | 点名技能 → 后端 LLM |
 *   | 选品 5 | `candidateIntelChips` 常量 | 本地 mock 推理 | 点名技能 → 后端 LLM |
 *   | 复盘 4 | `REVIEW_ACTIONS` 常量 | 填死长 prompt → `handleSend` | 点名技能 → 后端 LLM |
 *   | 广告 2 | `AD_QUICK_ACTIONS` 常量 | 派发 `tool-analysis` → 本地 mock 执行器 | 点名技能 → 后端 LLM |
 *
 * ★ 为什么卡片必须**从后端读**、而不是在前端再抄一份清单：
 *   技能正文的注入判定在后端（`enabled && enabled_agents 含本 Agent`）。前端抄一份的下场是
 *   「卡片上有、点下去却没注入」—— 而且**不报任何错**（请求照发、回复照出，只是 system
 *   prompt 里少了一段）。本仓「同一判定两份实现 ⇒ 至少一份永远测不到」。
 *   同理，前端 id ↔ 后端 `agent_name` 的桥接**只认** `GET /agents`（见 `stores/skills.ts` 头注）。
 *
 * ★ 上下文条（参数）没有随卡片来源变化：每个 Agent 差异提供（分析周期 / 已圈选竞品 /
 *   载入选品 / 当前店铺），既渲染在右侧 tag 上，也**拼进用户消息** —— 这样模型才拿得到
 *   「这次针对谁、什么周期」。技能正文（方法）由后端注入 system prompt，两者职责不重叠。
 *
 * ★ 作用域命名（第 190 轮老板裁决）——「**同一个底层字段只能有一个名字**」
 *   本仓的数据作用域**只有一层**：`X-Shop-ID → store_id`（`core/tenant/scoping.py` 的
 *   `SHOP_SCOPE_ATTR`）。八个 Agent 走的是同一个依赖，`AGENT_CATALOG` 也**没有** scope 字段。
 *   曾经复盘写「店铺：X」而广告写「广告账户：X」—— 两者读的却是**同一个**
 *   `shopStore.currentShop.name`，于是界面上凭空多出一个不存在的层级
 *   （老板看截图后追问「是不是不同 Agent 有不同作用域」）。
 *   ⇒ 现统一为「店铺：」。`scripts/check-chat-domain-split.cjs` 的 A9 钉住这条不变量：
 *     这个字段在**全前端只允许一个消费点**，且它的前缀必须是「店铺：」。
 */
import { ref, computed, watch } from 'vue'

import { useAgentStore } from '@/stores/agent'
import type { ContextTargetPayload } from './types'
import { useMonitorPoolStore } from '@/stores/monitorPool'
import { useCandidateLibraryStore } from '@/stores/candidateLibrary'
import { useShopStore } from '@/stores/shop'
import { useSkillStore, type Skill } from '@/stores/skills'
import type { ChatCtx } from './types'

/**
 * 「本次对话使用：X ×」chip 的展示模型（第 250 轮）。
 * `name` 恒有值（= 点名的存值）；`title` 查不到目录条目时**退回 `name`**（不许静默消失）。
 */
interface PendingSkillChip {
  name: string
  title: string
  icon: string
}

export function useAgentShortcuts(ctx: ChatCtx) {
  const agentStore = useAgentStore()
  const shopStore = useShopStore()
  const candStore = useCandidateLibraryStore()
  const pool = useMonitorPoolStore()
  const skillStore = useSkillStore()

  const {
    inputMessage, intelDays, loadedCandidate, workingProduct, workingReview,
    isLoading, handleSend, pendingSkill,
    // ★ 第 298 轮（老板 bug2）：「取消本次作用对象」的三个写口。默认 noop ⇒
    //   `provide` 缺位时"点了没反应"，而不是抛错把整条链带崩。
    clearWorkingCandidate = () => {}, clearWorkingProduct = () => {}, clearWorkingReview = () => {},
  } = ctx

  // ===== 当前是哪个 Agent（判定口径不变：`agentStore.currentAgent?.id`）=====
  const isCompetitorIntelAgent = computed(() => agentStore.currentAgent?.id === 'competitor-intel')
  const isProductResearchAgent = computed(() => agentStore.currentAgent?.id === 'product-research')
  const isListingAgent = computed(() => agentStore.currentAgent?.id === 'listing-generator')
  const isReviewAgent = computed(() => agentStore.currentAgent?.id === 'review-analyst')
  const isAdAnalyst = computed(() => agentStore.currentAgent?.id === 'ad-analysis')

  // ===== 技能卡（卡片 = 技能）=====

  /**
   * ★ 技能目录必须**在这里加载一次**。
   *
   *   `skillStore.loadAll()` 此前只被快捷卡片管理页（`SkillManager.vue`）调用，而卡片现在读的
   *   就是它 —— 不补这一次，对话页的卡片区会**恒空且不报任何错**（本仓「接线了但没渲染」的
   *   经典形态：零报错、零测试红，只有用户看到一排不存在）。
   *
   * ★ 只在 `agents` 为空时拉：`/agents` 是**静态平台元数据**（8 个 Agent 的名字），
   *   一次会话内不会变 ⇒ 等价于「每会话一次」。技能条目本身由管理页 / store 的写口
   *   （`create` / `update` / `remove` / `saveAgents` 都会 `loadSkills()`）刷新。
   */
  if (!skillStore.agents.length) {
    void skillStore.loadAll()
  }

  /** 当前 Agent 的**后端 `agent_name`**（= 技能启用的存值口径；桥接表只认后端） */
  const currentBackendAgent = computed(() => {
    const id = agentStore.currentAgent?.id
    if (!id) return ''
    return skillStore.agents.find((a) => a.id === id)?.name || ''
  })

  /**
   * 切换 Agent ⇒ **丢弃未完成的任务级点名**（第 249 轮）。
   *
   * ★ 为什么必须清：点名存的是 `skills.name`，而技能是**按 Agent 启用**的。
   *   带到别的 Agent 上，后端的技能读取器会按该 Agent 过滤 ⇒ 取不到正文 ⇒
   *   用户看到「你指定的技能当前不可用」，而**他并没有指定**（是他上一步的操作残留）。
   *   这类"界面看不出原因"的失败正是本仓反复治理的形态，所以在源头掐掉。
   */
  watch(currentBackendAgent, () => {
    ctx.clearPendingSkill()
  })

  /**
   * 当前 Agent 已启用的技能 = 卡片。
   *
   * ★ 过滤口径**复用 store 的 `skillsOfAgent()`**（`enabled && enabledAgents.includes`），
   *   不在这里重写一遍 —— 那会立刻变成第二份实现。
   *
   * ★★★ 第 248 轮：在它之上再摘掉 `isShortcut === false` 的那几条。
   *
   *   起因（老板原话）：「我看了【复盘结论写法】是被周报月报**引用**的，那么这个
   *   【复盘结论写法】是否不应该出现在快捷卡片栏」。
   *
   *   根因是 `enabledAgents` 此前**同时承担两个语义**（一个字段两个意思）：
   *       语义 A · 对本 Agent **生效** —— 进目录 / 可 `load_skill` / 可被点名；
   *       语义 B · 在对话页**显示为可点卡片**。
   *   而「复盘结论写法」必须保留 A（周报的正文逐字声明「表达结构
   *   沿用「复盘结论写法」」），却**不该**是卡片 —— 点下去拿到的不是一份东西，
   *   而是一套"怎么写"的规矩。⇒ 语义 B 拆成独立字段 `isShortcut`
   *   （DB 列 `skills.as_shortcut`，默认 true = 保持现行为）。
   *
   *   ★ 为什么**不能**改成「取消启用」：`enabled` 是**三处共用**的全局开关
   *     （目录注入 / `load_skill` / 本卡片区），关它三条一起断，且上面那几处
   *     引用会变成悬空引用 ⇒ 结构定义丢失。没有"零改动的正确解法"。
   *   ★ 为什么**不能**在前端加一份隐藏名单：那是第二份实现
   *     （本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到）。
   *
   * ★ 排序按 `name` 升序，与后端 `provider.build_catalog_for` 同口径：
   *   两边不一致的话，同一个 Agent 的技能在管理页与对话页**顺序不同**，用户会当成两套数据。
   *   （★ 这里只需与**卡片集合**对齐 —— `as_shortcut` 只影响本卡片区，
   *     后端目录与 `load_skill` 都不看它。）
   */
  const skillCards = computed<Skill[]>(() =>
    [...skillStore.skillsOfAgent(currentBackendAgent.value)]
      // ★ `!== false` 而不是 `=== true`：后端恒下发布尔值，但**缺字段的旧响应**
      //   一律按"显示"处理 —— 反向取值会让整排卡片静默消失且零报错。
      .filter((c) => c.isShortcut !== false)
      .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)),
  )

  /**
   * ★ 第 250 轮（遗留项 B）：**「本次对话使用：X ×」chip** —— 残留窗口的**显式出口**。
   *
   *   背景：点名（`ctx.pendingSkill`）的生命周期是**一个任务**，而任务何时结束由
   *   分派器按「本轮有没有产出结果」判定。于是存在一个**窗口**：本轮只产出纯文本答复
   *   （后端 `display_type='text'`）⇒ 点名会留到下一轮。
   *
   *   ★ 窗口本身是**对的**（第 249 轮：追问的答案必须还能用上点名），坏的是它
   *     **对用户不可见** —— 界面上没有任何地方写着"你上一步点的那个技能还生效着"。
   *     ⇒ 用户会以为"我没点名"，然后被一个看不见的点名改写结果，**且无法撤销**
   *     （唯一的出口是切 Agent，那是用户想不到的）。
   *
   *   ⇒ 本 chip **不缩短窗口**，而是把窗口**变可见** + 给一个**明确的撤销入口**。
   *
   *   ★ 为什么解析 `title` 要**回查目录**：点名的存值是 `skills.name`（kebab-case，
   *     模型 `load_skill` 用的标识），界面要显示的是 `skills.title`（中文）——
   *     直接把 name 显示给用户等于把内部标识暴露到界面上。
   *     回查口径**复用** `skillStore.skillsOfAgent()`，不在这里重写过滤
   *     （本仓：同一判定两份实现 ⇒ 至少一份永远测不到）。
   *
   *   ★ 查不到时**不许让 chip 静默消失**：目录还没拉回来、或技能刚被停用，都会查不到。
   *     此时退回显示 `name` 本身 —— 显示一个略生僻的标识，远好于「点名生效着、
   *     界面上却没有任何提示」：后者正是本条要治的形态。
   *     （同 `skillCards` 的 `.filter(c => c.isShortcut !== false)`：假值方向取宽。）
   */
  const pendingSkillCard = computed<PendingSkillChip | null>(() => {
    const name = pendingSkill.value
    if (!name) return null
    const card = skillStore.skillsOfAgent(currentBackendAgent.value).find((c) => c.name === name)
    if (card) return { name: card.name, title: card.title, icon: card.icon || '' }
    return { name, title: name, icon: '' }
  })

  /**
   * 用户点 chip 上的 × ⇒ **显式撤销**这一轮的点名。
   *
   * ★ 这是 `clearPendingSkill` 的**第三个**合法调用点（第 250 轮新增）。
   *   前两个（本轮产出结果 / 切换 Agent）的共同点是**用户没参与**，都是系统判定；
   *   这一条不同：它是用户主动说"我不要了"。第 249 轮把清除点收口为两个，防的是
   *   「任务级」被误改成「一次性」；而**用户显式撤销**不属于那个方向
   *   （它只会缩短窗口，不会在任务中途丢掉点名）。
   *   ⇒ `scripts/check-chat-failure-path.cjs` 的 L7 已同步从 2 处扩到 **3 处**，
   *     并把这一处**钉在本文件里**（删掉这个出口，那条判据立刻红）。
   *
   * ★ 写成**花括号体**而不是一行式箭头：L7 的行过滤是「含 `=>` 的行不算调用点」
   *   （为了不把类型声明与定义算进去）。一行式会让**这个真实调用点对门禁隐形** ——
   *   于是"用户撤销出口"既不在门禁的数里、也没人守着它别被删。刻意用块体让它可见。
   */
  function dismissPendingSkill(): void {
    ctx.clearPendingSkill()
  }

  /** 点卡后的高亮态。同一时刻只允许一张卡在跑（点第二张直接忽略） */
  const activeSkillCard = ref<string | null>(null)

  const periodOptions = [
    { value: 7, label: '近 7 天' },
    { value: 14, label: '近 14 天' },
    { value: 30, label: '近 30 天' },
    { value: 90, label: '近 90 天' },
  ]

  /**
   * 参与「本次请求的作用对象」机制的 Agent —— **唯一名单**（第 257 轮建 · 第 298 轮补客服）。
   *
   * ★ 为什么是具名常量、而不是在 computed 与文案里各写一遍 agent id：
   *   `contextTarget`（结构化）与 `contextParamText()`（人话）必须**同生共死**。
   *   两处各写一遍的那个版本，加第三个 Agent 时必然漏掉一处 —— 而漏掉的那处
   *   **不报任何错**：tag 上写着「未载入」、请求里却带着对象（或反之），
   *   用户只会相信屏幕上那句话。本仓「同一判定两份实现 ⇒ 至少一份永远测不到」。
   * ★ 判据：`scripts/check-chat-failure-path.cjs` 的 L11 逐字钉住这两份名单
   *   （成员与 label 都不许漂移），`check-agent-scope-lifecycle.cjs` 的 S1 同源。
   * ★ 对象来源也是唯一的：候选来自 `workingCandidate`（选品），商品来自
   *   `workingProduct`（Listing / AIGC），差评来自 `workingReview`（客服）
   *   —— 三份 provide 各自的一份真源。
   */
  const CANDIDATE_TARGET_AGENT = 'product-research'
  const PRODUCT_TARGET_AGENTS: readonly string[] = ['listing-generator', 'aigc-media']
  // ★ 第 298 轮：智能客服（差评应对）。它的作用对象是**台账里选中的那条差评**，
  //   来源 `workingReview` —— 与 `workingCandidate` / `workingProduct` 并列为
  //   三份 provide 之一（Workspace 各一份真源）。
  const REVIEW_TARGET_AGENT = 'customer-service'

  /** 两类作用对象各自的人话名（**唯一产地**：tag、消息里的参数、请求体三处共用）。 */
  const TARGET_LABELS = {
    candidate: '候选选品',
    product: '工作商品',
    review: '处置差评',
  } as const

  /**
   * 本次请求的「作用对象」（第 251 轮建 · 第 257 轮扩到三个 Agent · 第 298 轮补客服）
   * —— **唯一产地**。
   *
   * | 返回值       | 含义                       | 后端收到后                   |
   * |-------------|----------------------------|-----------------------------|
   * | `undefined` | 本 Agent 不参与该机制        | 请求体不带该字段 ⇒ 不注入     |
   * | `null`      | 参与了，但本次**没有**对象    | 带 `null` ⇒ 注入「本次没有」 |
   * | `{…}`       | 本次的对象                   | 注入对象三要素                |
   *
   * ★ 为什么 `null` 不能省成 `undefined`：后端要靠「明确没有」去挡
   *   「点名的技能需要对象却没给」那条路径（第 250 轮的洞）。
   *   压成一个 ⇒ 门禁只在"新客户端"上生效，等于留了个静默旁路。
   * ★ 为什么它和 `contextParamText()` 必须同源：两处各写一遍就会出现
   *   「tag 上写着未载入、请求里却带着对象」——同一事实的两份表达，
   *   而人只会相信屏幕上那句。所以**参数文案也从这里派生**。
   * ★ 第 257 轮为什么必须扩到 Listing / AIGC：这两家的对话链路此前只能从
   *   用户消息文本里抽品名（Listing 后端 `_extract_product_info(query, …)`），
   *   用户在顶部【载入产品】选好了商品、然后只说「帮我优化标题」时模型只能猜，
   *   而猜错的结论打在别的品上时界面/日志/测试全绿。
   */
  const contextTarget = computed<ContextTargetPayload | null | undefined>(() => {
    const id = agentStore.currentAgent?.id
    if (id === CANDIDATE_TARGET_AGENT) {
      const c = loadedCandidate.value
      if (!c) return null
      return { label: TARGET_LABELS.candidate, title: c.title || '', ref: c.asin || c.id || '' }
    }
    if (PRODUCT_TARGET_AGENTS.includes(id || '')) {
      const p = workingProduct.value
      if (!p) return null
      // ★ 第 272 轮：把工作商品的**完整字段**塞进 `detail`，随技能一起传给模型。
      //   此前只传 label/title/ref，模型拿不到「终检清单」要核对的类目/五点/
      //   库存/价格等，只能反过来问用户「类目？标题？库存？」。
      //   detail 是机制层「原样渲染」的键值表，这里放的是商品对象已有的字段，
      //   缺的字段自然为空 ⇒ 模型看到空也会如实问，而不是瞎编。
      const detail: Record<string, unknown> = {
        类目: p.category ? `${p.category}${p.sub_category ? ' / ' + p.sub_category : ''}` : undefined,
        标题: p.title || p.generated_title || undefined,
        五点描述: Array.isArray(p.bullets)
          ? p.bullets.map((b: any) => b.title ? `${b.title}：${b.content || ''}` : b.content || '').join('；')
          : (Array.isArray(p.generated_bullets)
              ? p.generated_bullets.map((b: any) => b.title ? `${b.title}：${b.content || ''}` : b.content || '').join('；')
              : undefined),
        产品描述: p.description || undefined,
        价格: p.price != null ? p.price : undefined,
        成本: p.cost != null ? p.cost : undefined,
        尺寸重量: p.dimensions || p.package_size || undefined,
        材质: p.material || undefined,
        颜色: p.color || undefined,
        库存: p.fba_stock != null || p.fbm_stock != null
          ? `FBA ${p.fba_stock ?? 0} / FBM ${p.fbm_stock ?? 0}`
          : undefined,
        变体: Array.isArray(p.variants) && p.variants.length ? JSON.stringify(p.variants) : undefined,
        关键词: Array.isArray(p.keywords) ? p.keywords.join(', ') : undefined,
      }
      // 去掉所有空值（避免把一堆 undefined 发给模型）
      const cleaned: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(detail)) {
        if (v !== undefined && v !== null && v !== '') cleaned[k] = v
      }
      return {
        label: TARGET_LABELS.product,
        title: p.title || '',
        ref: p.asin || p.sku || p.id || '',
        detail: Object.keys(cleaned).length ? cleaned : undefined,
      }
    }
    // ★ 第 298 轮：智能客服（差评应对）。
    //   `ref` 必须是 **review_id** —— 差评应对技能第 0 步就是
    //   `get_customer_review_context(review_id)`（`modules/trade/tools.py`），
    //   在那之前它只能从用户消息文本或**会话历史**里找这个 id（第 250 轮那个洞）。
    //   ★ 字段名取自 `ReviewDeskConfig.vue::DetailView`（三个入口的**唯一归一形状**），
    //     不是猜的 —— 台账 / 近期差评 / 孤儿差评三个入口在这一层已经统一。
    if (id === REVIEW_TARGET_AGENT) {
      const r = workingReview.value
      if (!r) return null
      const reviewId = r.id || r.review_id || ''
      const detail: Record<string, unknown> = {
        评论ID: reviewId || undefined,
        ASIN: r.asin || undefined,
        SKU: r.sku || undefined,
        星级: r.rating ?? undefined,
        评论时间: r.review_at || undefined,
        买家: r.buyer_name || undefined,
        评论标题: r.title || undefined,
        评论正文: r.body || undefined,
      }
      // 去掉空值（与上面商品那支同款：别把一堆 undefined 发给模型）
      const cleanedReview: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(detail)) {
        if (v !== undefined && v !== null && v !== '') cleanedReview[k] = v
      }
      return {
        label: TARGET_LABELS.review,
        title: r.title || reviewId,
        ref: reviewId,
        detail: Object.keys(cleanedReview).length ? cleanedReview : undefined,
      }
    }
    return undefined
  })

  /**
   * 本次作用对象**是否真有值** —— 决定上下文条上要不要给取消按钮。
   *
   * ★ 判据与 `contextTarget` **同源**（不另算一遍）：`contextTarget` 非空才说明
   *   这一轮真会把对象带过去。`null` / `undefined` 时给一个 × 就是"点了没反应"，
   *   而 `null`（参与了但本次没有）正是**已经取消之后**的状态 ⇒ 用别的判据
   *   （比如"当前 Agent 是不是载入型"）会让 × 取消完还赖着不走。
   */
  const scopeTargetLoaded = computed(() => !!contextTarget.value)

  /**
   * 「取消本次作用对象」（第 298 轮 · 老板 bug2）。
   *
   * 起因（老板原话）：「上下文被某条处置差评填入后，你没有给取消按钮」。
   * ★ 对照 `pendingSkillCard` 那个 chip（第 250 轮加的 ×）：点名有出口，
   *   而**作用对象**没有 —— 一旦载入某条差评，唯一的解法是"切走 Agent 再切回来"，
   *   而那个办法用户想不到（第 250 轮的原话：「唯一的出口是切 Agent，
   *   那是用户想不到的」）。淘汰赛式的"能进不能出"是本仓反复出现的形态。
   *
   * ★ 分派映射**只在这里写一份**，且紧挨着上面 `contextTarget` 的三支分支 ——
   *   新增第四个载入型 Agent 时两处一起加，放在一起就是为了这个。
   *   在编排层按 Agent 再分派一次 = 同一条判定两份实现。
   */
  function clearScopeTarget() {
    const id = agentStore.currentAgent?.id
    if (id === CANDIDATE_TARGET_AGENT) {
      clearWorkingCandidate()
      return
    }
    if (PRODUCT_TARGET_AGENTS.includes(id || '')) {
      clearWorkingProduct()
      return
    }
    if (id === REVIEW_TARGET_AGENT) {
      clearWorkingReview()
    }
  }

  /**
   * 上下文条的**参数字面**。四个 Agent 各自不同，其余 Agent 无参数（返回空串）。
   *
   * ★ 这里是**唯一**产出上下文参数的地方：右侧 tag 与用户消息都用它 ⇒ 界面显示什么、
   *   模型收到什么，逐字一致（不会出现「tag 上写着已圈 3 个竞品、消息里却是全池」）。
   */
  function contextParamText(): string {
    const id = agentStore.currentAgent?.id
    if (id === 'competitor-intel') {
      const days =
        periodOptions.find((o) => o.value === intelDays.value)?.label || `近 ${intelDays.value} 天`
      const n = pool.selectedAsins.length
      return `分析周期：${days}；范围：${n ? `已圈选的 ${n} 个竞品` : '监控池全池'}`
    }
    if (id === CANDIDATE_TARGET_AGENT) {
      // ★ 第 251 轮：从结构化字段**派生**（不再直接读源），
      //   于是「tag 上写什么」与「请求里带什么」不可能各说各话。
      const t = contextTarget.value
      return t ? `评估对象：${t.title}` : '未载入选品（请先点顶部【载入选品】选定评估对象）'
    }
    // ★ 第 257 轮：Listing 优化师 / AIGC 媒体生成器同源派生。
    //   改前这两家在这里落空（返回空串）⇒ 上下文条显示「（无上下文参数）」，
    //   字面没错（请求里确实还没有这个字段）但它给出的暗示是错的：
    //   「本 Agent 不需要对象」—— 而它需要（这正是老板截图里那一问的来源）。
    //   ★ 与选品那条**同一条规则**：有对象就报对象，没有对象时报的**不是**
    //     「无参数」而是"下一步点哪里"（含糊的说明在界面上与故障同形）。
    if (PRODUCT_TARGET_AGENTS.includes(id || '')) {
      const t = contextTarget.value
      return t
        ? `${TARGET_LABELS.product}：${t.title}`
        : `未载入产品（请先点顶部【载入产品】选定${TARGET_LABELS.product}）`
    }
    // ★ 第 298 轮：客服同源派生。没有对象时报的是"下一步点哪里"，
    //   不是一句含糊的「无参数」—— 后者在界面上与故障同形（第 257 轮的教训）。
    if (id === REVIEW_TARGET_AGENT) {
      const t = contextTarget.value
      return t
        ? `${TARGET_LABELS.review}：${t.title}`
        : '未选择差评（请在右侧「差评处置」里点【在对话里处置这条】）'
    }
    // ★ 第 190 轮：复盘与广告**合并为一支**。
    //   原实现分两支各写一遍，且广告那支前缀写成「广告账户：」—— 而它读的是**同一个**
    //   `shopStore.currentShop.name`，后端作用域也是同一个 `X-Shop-ID`。
    //   后果：界面上凭空多出一个不存在的层级（用户会推断「这两个 Agent 作用域不同」）。
    //   合并后作用域只有一个名字、一份实现；将来真要引入账户级，只改这一处。
    if (id === 'review-analyst' || id === 'ad-analysis') {
      return shopStore.currentShop ? `店铺：${shopStore.currentShop.name}` : '未选店铺（默认全店数据）'
    }
    return ''
  }

  /** 上下文条的**展示文案**（右侧 tag 上那句话） */
  const agentScopeText = computed(() => contextParamText() || '（无上下文参数）')

  /** 上下文条配色：拿到了「具体对象」是蓝系，退化成默认范围是橙系 */
  const agentScopeColor = computed(() => {
    const id = agentStore.currentAgent?.id
    if (id === 'competitor-intel') return pool.selectedAsins.length ? 'blue' : 'orange'
    // ★ 第 257 轮：状态色也从**结构化字段**派生，不再直接读 `loadedCandidate`。
    //   直接读源会让「选品读 candidate / Listing 读 product」成为两份实现 ——
    //   加第三个 Agent 时必然漏一处，而漏掉的那处只是 tag 颜色不对，
    //   没人会为它开一个 bug 单。`contextTarget` 已经是"谁参与 + 有没有对象"
    //   的唯一判定，这里只是消费它。
    if (
      id === CANDIDATE_TARGET_AGENT ||
      id === REVIEW_TARGET_AGENT ||
      PRODUCT_TARGET_AGENTS.includes(id || '')
    ) {
      return contextTarget.value ? 'geekblue' : 'orange'
    }
    if (id === 'review-analyst' || id === 'ad-analysis') {
      return shopStore.currentShop ? 'geekblue' : 'orange'
    }
    return 'default'
  })

  /** 隐藏占位标签：与竞品那条「分析周期下拉」保持同宽，避免切 Agent 时整排卡片横向跳动 */
  const agentScopeLabel = computed(() => {
    const id = agentStore.currentAgent?.id
    if (id === 'competitor-intel') return '分析周期'
    if (id === CANDIDATE_TARGET_AGENT) return '评估对象'
    // ★ 第 257 轮：这两家的上下文条前缀就是 `TARGET_LABELS.product`
    //   （与 `contextParamText()` 同源，见那边注释）
    if (PRODUCT_TARGET_AGENTS.includes(id || '')) return TARGET_LABELS.product
    if (id === REVIEW_TARGET_AGENT) return TARGET_LABELS.review
    // ★ 与 `contextParamText()` 同口径：店铺级 Agent 只有一个名字（第 190 轮）
    if (id === 'review-analyst' || id === 'ad-analysis') return '店铺'
    return '上下文'
  })

  /**
   * 点一张技能卡 → 走**标准发送链路**（`handleSend`）。
   *
   * ★ 消息形状（第 246 轮 P0-b 修正后）：`请按「{title}」执行。` + 换行 + `（{上下文参数}）`
   *
   *   **`description` 已从消息里拿掉**。老板第 189 轮的原形状是
   *   `请按「{title}」执行：{description}`，本轮的实测证明它是**误路由的直接来源**：
   *   `description` 是「什么场景该用它」的**方法说明**，天然夹带别主题的词 ——
   *     · 「周报」那条 desc 写着「销售 / **广告** / 库存 / 利润四条线」⇒ 命中广告路由；
   *     · 「复盘结论写法」那条 desc 写着「输出周报/**月报**时使用」⇒ 命中月度复盘。
   *   实测 5 张卡里 3 张被路由到**别的报表**（后端关键词短路跑在这些词上）。
   *   `description` 本来就随技能正文进 system prompt（后端按 `skill` 参数从库里取，
   *   与 `load_skill` 走同一套过滤）⇒ 塞进用户消息是**纯重复**，且是唯一的误判源。
   *
   * ★ 技能名走 `ctx.setPendingSkill()` 这条**一次性点名通道**，而不是塞进消息文本：
   *   模型看不到它，也伪造不了它；且它由后端解析（不存在 / 不属于我 / 未启用 一律同一文案）。
   *   ★ 后端拿到点名后必须**让关键词短路让路**（`ai_infra.skills.is_skill_requested`），
   *     否则消息文本仍会撞上关键词表 —— 那边已同步收口（第 246 轮 P0-a）。
   */
  async function runSkillCard(card: Skill) {
    if (isLoading.value || activeSkillCard.value) return
    activeSkillCard.value = card.id
    try {
      ctx.setPendingSkill(card.name)
      const param = contextParamText()
      inputMessage.value = `请按「${card.title}」执行。` + (param ? `\n（${param}）` : '')
      await handleSend()
    } finally {
      // ★ 成功失败都要复位：异常时留着高亮会让**整排卡片永久点不动**
      //   （`activeSkillCard` 非空即拒绝下一次点击），而界面上看不出原因。
      activeSkillCard.value = null
    }
  }

  /** 确保候选库已加载 */
  async function ensureCandidateLoaded() {
    if (!candStore.items.length && !candStore.isLoading) {
      try { await candStore.fetchItems() } catch (e) { /* 忽略 */ }
    }
  }

  return {
    isCompetitorIntelAgent,
    isProductResearchAgent,
    isListingAgent,
    isReviewAgent,
    isAdAnalyst,
    skillCards,
    activeSkillCard,
    runSkillCard,
    periodOptions,
    agentScopeText,
    agentScopeColor,
    agentScopeLabel,
    // 本次请求的作用对象（第 251 轮）：回复链路据此下发结构化字段
    contextTarget,
    // 作用对象的**取消入口**（第 298 轮 · 老板 bug2「没有给取消按钮」）：
    // `scopeTargetLoaded` 决定上下文条上要不要出 ×，`clearScopeTarget` 是它的动作。
    // ★ 按钮文案里的对象名**不另开一个键** —— 复用 `agentScopeLabel`
    //   （它判的是同一个 `id`、给的是同一份 `TARGET_LABELS`），多一个键就是
    //   同一事实的第二份表达。
    scopeTargetLoaded,
    clearScopeTarget,
    ensureCandidateLoaded,
    // 点名可见 chip（第 250 轮）：残留窗口的显式出口
    pendingSkillCard,
    dismissPendingSkill,
  }
}

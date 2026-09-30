/**
 * 技能仓库 store（第 181 轮 · 批 B）
 *
 * ============================================================================
 * ★ 与 `agent.ts` 的关系：**不改它**
 * ============================================================================
 * `agent.ts` 里的 `AGENT_LIST` 是前端的界面路由表（8 个 Agent 的 id + 图标 + 名称）。
 * 技能装配需要的是「后端 agent_name」，两者**对不上**（第 181 轮实测：只有
 * `secretary` 一个完全一致，其余大小写或语种都不同）。
 *
 * ⇒ 桥接表在**后端**（`modules/skills/agents.py`），前端通过 `GET /agents` 拉取。
 *   前端**不再抄一份**：两套 ID 空间的映射只能有一个源，
 *   抄一份的下场是改一处、另一处静默失效（本仓真实吃过这个形态的亏）。
 *
 * ============================================================================
 * ★ 为什么 `enabledAgents` 存**后端 agent_name** 而不是前端 id
 * ============================================================================
 * 注入发生在后端：`PromptContext.agent_name` 就是后端那个值，
 * `enabled_agents` 拿它做匹配。前端 id 在后端**查不到任何东西** ——
 * 存 id 的症状是「勾选了但技能永不注入」，且不报错。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api/skills'

/** 平台 Agent（后端目录项） */
export interface AgentCatalogItem {
  /** ★ 后端 `agent_name` —— 技能启用的**存值**（权威 key） */
  name: string
  /** 前端 agent id（界面路由用） */
  id: string
  /** 展示名（中文） */
  title: string
  description: string
}

/** 平台工具（后端目录项，第 185 轮） */
export interface ToolCatalogItem {
  /** 所属 Agent 的后端 `agent_name`（工具是**按 Agent 装配**的） */
  agent: string
  /** ★ 工具名 —— 存进 `skills.tools` 的值，也是模型看到的函数名 */
  name: string
  /** 展示名（中文短语，界面上一行一个） */
  title: string
  /** 一句话说明（写给**人**看：这个工具解决什么问题） */
  description: string
  /** read_only（免审批）| approval（每次调用弹人工审批） */
  effect: 'read_only' | 'approval'
  /**
   * 跨 Agent 共用时的**归属全集**（后端 `TOOL_CATALOG` 的可选字段，第 205 轮）。
   *
   * ★ 缺省 = 只有 `agent` 那一个。**不要在前端补默认值**：
   *   补了就等于前端自己声明了一份归属，与后端那份必然漂移
   *   （门禁 `test_shared_tool_convergence.py` 钉住的是后端那一份）。
   * ★ 判共用走 `(t.agents || []).length > 1`：**读后端字段**，
   *   而不是前端去比对 `grouped` 里出现几次（那是第二份口径）。
   */
  agents?: string[]
}

/** 按 Agent 分组的工具（**分组口径由后端给**，前端不自己再分一遍） */
export interface ToolGroup {
  agent: string
  agentTitle: string
  tools: ToolCatalogItem[]
}

/**
 * 「配套工具」下拉的一组候选项（第 255 轮）。
 *
 * ★ 这是**组结构**而不是 antd 的组件类型：下拉由两个页面共用，
 *   结构在这里定死，两边都只做绑定，不各自拼一份。
 */
export interface ToolOptionGroup {
  label: string
  /**
   * 本组是「已绑定、但不在当前候选里」的**兜底组**。
   *
   * ★ 有它的地方就必须能**取消勾选**（那是唯一的删除路径），
   *   所以它只能是"多显示一组已选值"，不能变成"不可选/只读"。
   */
  orphan?: boolean
  options: { value: string; label: string }[]
}

/** 一条反向引用：**引用某个工具的那个技能**（第 208 轮） */
export interface ToolUsageRef {
  id: string
  /** 技能标识（kebab-case） */
  name: string
  /** 展示名（后端已兜底为 `title || name`，前端不再判空） */
  title: string
  /** 该技能是否全局启用（停用的技能不会进入任何 Agent 的技能目录） */
  enabled: boolean
  /**
   * 该技能对哪些 Agent 生效（存后端 `agent_name`）。
   *
   * ★ 随引用一起下发，而不是让前端再拉一次技能列表去对账 ——
   *   两步拉取会引入「两次请求之间技能被改了」的时间窗，
   *   以及只能靠约定维持的口径分叉（同 `list_skills` 内联收藏标记的判据）。
   */
  enabledAgents: string[]
}

/**
 * 工具 ← 技能 的**反向引用索引**（第 208 轮「工具仓库」的数据源）。
 *
 * ★ 三个投影**必须同源**（`usage` / `unknownTools` / `unusedTools`），
 *   由后端在同一次遍历里算好并由门禁
 *   `tests/test_skill_gate.py::test_tool_usage_reverse_index_over_http` 钉住。
 *   前端拿两张表自己做差集 = 第二份实现。
 */
export interface ToolUsage {
  /** 工具名 → 引用它的技能（后端已按调用者**归属**过滤） */
  usage: Record<string, ToolUsageRef[]>
  /**
   * 库里被引用、却**不在目录表**里的工具名。
   *
   * ★ 这是一个真实存在的数据缺陷面：读口（`render_skill_tools`）**不校验**
   *   工具名存在性，所以本表登记之前写入的名字可能还留在库里。
   *   它此前**完全没有展示面**（用户看不见、也就删不掉）。
   */
  unknownTools: string[]
  /** 目录里有、却没有任何技能引用的工具名（工具仓库最有行动价值的信号） */
  unusedTools: string[]
  /** 被引用的工具名个数（= `Object.keys(usage).length`） */
  referencedTools: number
  /** 参与统计的**可见技能**数（归属过滤后的） */
  totalSkills: number
}

/** 技能实体 */
export interface Skill {
  id: string
  /** 技能标识（kebab-case，全局唯一，模型调 `load_skill` 用的名字） */
  name: string
  /** 展示名（中文） */
  title: string
  /**
   * 图标（emoji）。
   *
   * ★ 后端 `service.serialize` 早就下发了这个字段（第 188 轮 #774 加列时落的），
   *   前端类型**漏了它** —— 于是卡片渲染 `skill.icon` 时 TS 报「属性不存在」。
   *   空串是**合法值**（= 没生成 / 没填），渲染方自己兜底，这里不给默认值。
   */
  icon: string
  /** ★ 第一级披露的唯一依据：模型只看它决定要不要加载 */
  description: string
  /** ★ 第二级披露的内容（列表接口不返回；详情接口才有） */
  content?: string
  /**
   * 配套工具名列表（**工具技能**专用；留空 = 纯提示词技能）。
   *
   * ★ 值必须是 `/tools` 下发的工具名之一 —— 第 185 轮起后端写口会拒绝
   *   未注册的名字（在此之前可以存进任意字符串，然后**静默不生效**：
   *   模型调不到、界面照常显示、保存不报错）。
   * ★ 顺序有意义：后端原样保序返回。
   */
  tools: string[]
  /**
   * 当前身份是否收藏了它（⭐）。
   *
   * ★ 由**后端内联下发**，不是前端自己维护的本地状态：收藏住在
   *   `skill_favorites` 表、键是「用户 × 技能」，换个人登录看到的就是另一个值
   *   —— 前端存一份必然分叉。
   * ★ 无身份（未登录 / 纯浏览）时后端恒给 `false`。
   */
  favorited: boolean
  version: string
  /** 可见范围：account（账号内共享）| private（仅创建者） */
  visibility: 'account' | 'private'
  /** 全局启用开关 */
  enabled: boolean
  /** ★ 对哪些 Agent 生效（存后端 agent_name） */
  enabledAgents: string[]
  /**
   * 是否在 Agent 对话页显示为**快捷卡片**（第 248 轮）。
   *
   * ★★ 与 `enabledAgents` 是**两个判定**，不要合并理解：
   *      `enabledAgents` = 「对本 Agent **生效**」⇒ 进技能目录（第一级披露）/
   *                        `load_skill` 可加载（第二级披露）/ 可被点名通道命中；
   *      `isShortcut`    = 「要不要在对话框下方给它一张可点的卡」。
   *
   *   ⇒ 「不显示卡片」**不等于**「停用」。停用（`enabled=false`）会让**别条技能**
   *     正文里对它的引用变成**悬空引用** —— 典型是「复盘结论写法」：
   *     周报的正文逐字写着「表达结构沿用「复盘结论写法」」，
   *     关掉启用之后那几处引用指不到任何东西，而 `_load_skill` 还会回一句
   *     「没有找到名为 … 的技能」，模型被明令禁止自行补全 ⇒ 结构定义整体丢失。
   *
   * ★ 假值方向（**故意取宽**）：后端恒下发本字段，但 `undefined`（旧响应 /
   *   缓存里的旧对象）一律按 **true** 处理 —— 取假会让整排卡片**静默消失**，
   *   零报错、零测试红，属于最难归因的一类缺陷（本仓「降级方向取安全侧」）。
   */
  isShortcut: boolean
  /** 演示技能标记（只读；由后端 seed 双向收敛，接口不可写） */
  isDemo: boolean
  accountId: string | null
  createdAt: string | null
  updatedAt: string | null
}

/** 版本快照 */
export interface SkillRevision {
  id: string
  skillId: string
  version: string
  content: string
  note: string
  /** create | update | rollback */
  action: string
  changedBy: string | null
  changedAt: string | null
}

export const useSkillStore = defineStore('skills', () => {
  const items = ref<Skill[]>([])
  const agents = ref<AgentCatalogItem[]>([])
  /** 平铺工具清单（卡片上把 `analyze_profit` 显示成「利润测算」用） */
  const tools = ref<ToolCatalogItem[]>([])
  /** 按 Agent 分组的工具（编辑抽屉里按已勾选的 Agent 收窄候选用） */
  const toolGroups = ref<ToolGroup[]>([])
  /**
   * 工具 ← 技能 的反向引用（工具仓库 tab 用；第 208 轮）。
   *
   * ★ `null` 表示"还没拉到"，与"拉到了但是空"（`usage: {}`）是**两种状态** ——
   *   合并成一个空对象会让加载失败与"真的没人引用"长得一模一样
   *   （本仓判据：拿不到权威清单 ≠ 清单为空）。
   */
  const toolUsage = ref<ToolUsage | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')

  // 当前打开的技能详情（含正文）与它的版本历史
  const current = ref<Skill | null>(null)
  const revisions = ref<SkillRevision[]>([])

  const total = computed(() => items.value.length)

  // ====== 筛选 / 排序 / 分组 / 收藏（第 194 轮）======
  //
  // ★ 形态照抄 `candidateLibrary.ts`（同项目同类页面的既有范式）：
  //   筛选状态住在 store，UI 只做 v-model 绑定，派生一律用 computed。
  //   在组件里另存一份的问题是：切页面就丢，且两个视图会各自算一遍。
  //
  // ★ 所有筛选的默认值都是「不过滤」（`undefined` / 空串 / false）：
  //   默认状态下 `filteredItems === items` —— 用户第一眼看到的仍是全部技能。
  const searchQuery = ref('')
  /** 所属 Agent。存**后端 agent_name**，与 `enabledAgents` 同一口径 */
  const filterAgent = ref<string | undefined>(undefined)
  /** 技能类型：'prompt'（纯提示词）| 'tool'（绑定工具） */
  const filterKind = ref<string | undefined>(undefined)
  /** 状态：'enabled' | 'disabled' | 'demo' */
  const filterStatus = ref<string | undefined>(undefined)
  const onlyFavorites = ref(false)
  /**
   * 按 Agent 分组（老板拍板：方案 A「按 Agent 分组」）。
   * ★ 默认**勾选**（`ref(true)`）：老板要求进仓库第一眼就是按 Agent 分组，
   *   一眼看到「哪些 Agent 挂了哪些技能」。它不是「筛选条件」—— 属于视图/分组偏好，
   *   所以 `resetFilters()` **不重置**它（「重置筛选」只清搜索/Agent/类型/状态/收藏）。
   */
  const groupByAgent = ref(true)
  /** 'updated_at'（默认，最新在前）| 'name'（A→Z）| 'version'（高版本在前） */
  const sortBy = ref<string>('updated_at')
  /** 分组折叠状态：分组 key → 是否折叠（默认全部展开） */
  const collapsedGroups = ref<Record<string, boolean>>({})

  /**
   * 版本号比较（**语义化**：逐段按数字比）。
   *
   * ★ 不能直接按字符串比：字典序下 `'1.10.0' < '1.9.0'` —— 排出来的「版本顺序」
   *   是错的，而界面上**看不出这是错的**（用户只会觉得排序不灵）。
   * ★ 解析不出数字的段按 0 处理（不抛错）：版本号是展示信息，历史数据里
   *   可能有 `1.0`、`v2`、空串，格式怪不该让一次排序失败。
   */
  function cmpVersion(a: string, b: string): number {
    const pa = String(a ?? '').split('.')
    const pb = String(b ?? '').split('.')
    const n = Math.max(pa.length, pb.length)
    for (let i = 0; i < n; i++) {
      const x = parseInt(pa[i] ?? '', 10)
      const y = parseInt(pb[i] ?? '', 10)
      const xi = Number.isFinite(x) ? x : 0
      const yi = Number.isFinite(y) ? y : 0
      if (xi !== yi) return xi - yi
    }
    return 0
  }

  /**
   * 筛选后的技能 —— **两个视图唯一的数据消费口**。
   *
   * ★ 顺序是先过滤、再排序；反过来会把「排序」也算进筛选条件里。
   * ★ 搜索覆盖 **name / title / description** 三处（老板原文要求）。
   *   第 195 轮起不再搜 `tags` —— 自定义标签概念已整体退役。
   */
  const filteredItems = computed(() => {
    let result = items.value

    if (filterAgent.value) {
      result = result.filter((s) => (s.enabledAgents || []).includes(filterAgent.value!))
    }
    if (filterKind.value === 'prompt') {
      result = result.filter((s) => !(s.tools || []).length)
    } else if (filterKind.value === 'tool') {
      result = result.filter((s) => (s.tools || []).length > 0)
    }
    if (filterStatus.value === 'enabled') {
      result = result.filter((s) => s.enabled)
    } else if (filterStatus.value === 'disabled') {
      result = result.filter((s) => !s.enabled)
    } else if (filterStatus.value === 'demo') {
      result = result.filter((s) => s.isDemo)
    }
    if (onlyFavorites.value) {
      result = result.filter((s) => s.favorited)
    }
    const q = searchQuery.value.trim().toLowerCase()
    if (q) {
      result = result.filter(
        (s) =>
          (s.name || '').toLowerCase().includes(q) ||
          (s.title || '').toLowerCase().includes(q) ||
          (s.description || '').toLowerCase().includes(q)
      )
    }

    return [...result].sort((a, b) => {
      switch (sortBy.value) {
        case 'name':
          return (a.title || a.name).localeCompare(b.title || b.name, 'zh-Hans-CN')
        case 'version':
          return cmpVersion(b.version, a.version) // 高版本在前
        default:
          return (
            new Date(b.updatedAt || 0).getTime() - new Date(a.updatedAt || 0).getTime()
          )
      }
    })
  })

  /**
   * 分组后的技能 —— **「不分组」= 只有一个「无标题分组」**。
   *
   * ★★ 这个设计是刻意的，不是多此一举：把「不分组」当成单组特例，
   *   模板里的两个渲染分支（卡片 / 行）就**只写一遍**。若另写一份
   *   「不分组」的渲染，就会造出第三、四份渲染 —— 而它们必然分叉
   *   （本仓铁律：同一份数据的第二套渲染必然漂移，且全是静默的）。
   *
   * ★ 一条技能可挂**多个** Agent ⇒ 分组后它会在多个分组里各出现一次。
   *   这是**正确的多归属语义**，不是重复 bug：用户的预期是
   *   「我给选品分析师找技能，就在这个分组里找到它」。
   *   将来若要做去重展示，正确做法是在分组标题上标注
   *   「该技能同时属于 N 个分组」，而不是让它从某些分组里消失。
   *
   * ★ 「未分配」兜底组：`enabledAgents` 为空的技能不属于任何 Agent 分组，
   *   不给它落点就会在分组模式下**彻底看不见** —— 而它很可能正是
   *   用户刚建好、还没分配的那一条。
   */
  const groupedItems = computed(() => {
    const rows = filteredItems.value
    if (!groupByAgent.value) {
      return [{ key: '__all__', title: '', items: rows }]
    }
    const out: { key: string; title: string; items: Skill[] }[] = []
    for (const a of agents.value) {
      const hit = rows.filter((s) => (s.enabledAgents || []).includes(a.name))
      if (hit.length) out.push({ key: a.name, title: a.title, items: hit })
    }
    const orphan = rows.filter((s) => !(s.enabledAgents || []).length)
    if (orphan.length) out.push({ key: '__none__', title: '未分配', items: orphan })
    return out
  })

  /**
   * 已生效的筛选条件数（顶栏「已筛选 N 项」用）。
   * ★ 只数**筛选**，不数组与排序 —— 那两个不改变「显示哪些技能」，
   *   混进来会让这个数字的含义变得无法解释。
   */
  const activeFilterCount = computed(() => {
    let n = 0
    if (searchQuery.value.trim()) n++
    if (filterAgent.value) n++
    if (filterKind.value) n++
    if (filterStatus.value) n++
    if (onlyFavorites.value) n++
    return n
  })

  function resetFilters() {
    searchQuery.value = ''
    filterAgent.value = undefined
    filterKind.value = undefined
    filterStatus.value = undefined
    onlyFavorites.value = false
  }

  function toggleGroup(key: string) {
    collapsedGroups.value[key] = !collapsedGroups.value[key]
  }

  /**
   * 收藏 / 取消收藏（**幂等**：传目标值，不传「切换」）。
   *
   * ★ 乐观更新：先改本地标记，星标点击必须立刻有反馈，否则用户会连点
   *   （而连点在不幂等的 toggle 下会把状态翻回原样）。
   * ★ 失败时把本地值**改回去**并写 `error` —— 本仓铁律：失败路径必须
   *   回写界面状态，否则所有失败都被转译成「随机失败」。
   * ★ 成功后以**服务端回执**为准（`res.favorited`），不用本地推测值。
   */
  async function toggleFavorite(skill: Skill, favorited?: boolean): Promise<boolean> {
    const next = favorited === undefined ? !skill.favorited : favorited
    const prev = skill.favorited
    const row = items.value.find((s) => s.id === skill.id)
    if (row) row.favorited = next
    error.value = ''
    try {
      const res = await api.setSkillFavorite(skill.id, next)
      if (row) row.favorited = res?.favorited ?? next
      return true
    } catch (e: any) {
      if (row) row.favorited = prev
      error.value = e?.message || String(e)
      return false
    }
  }

  /** 按后端 agent_name 反查展示名（列表上标注"启用于哪几个 Agent"用） */
  const titleOfAgent = computed(() => {
    const map: Record<string, string> = {}
    for (const a of agents.value) map[a.name] = a.title
    return (name: string) => map[name] || name
  })

  /** 工具名 → 展示名（**未知工具原样返回** —— 老数据必须能显示，否则连删都删不掉） */
  const titleOfTool = computed(() => {
    const map: Record<string, string> = {}
    for (const t of tools.value) map[t.name] = t.title
    return (name: string) => map[name] || name
  })

  /** 该工具是否每次调用都需人工审批（`effect === 'approval'`） */
  const isApprovalTool = computed(() => {
    const set = new Set(
      tools.value.filter((t) => t.effect === 'approval').map((t) => t.name)
    )
    return (name: string) => set.has(name)
  })

  /**
   * 某个工具**被哪些技能引用**（后端给的反向索引，前端不自己推）。
   *
   * ★ 未知工具返回空数组而不是抛错：界面要能显示"这个工具没人引用"，
   *   而不是让整页渲染挂掉（同 `titleOfTool` 的「未知工具原样返回」判据）。
   */
  const usageOfTool = computed(() => {
    const map = toolUsage.value?.usage || {}
    return (name: string): ToolUsageRef[] => map[name] || []
  })

  /** 目录里有、却没有任何技能引用的工具名（后端算好，口径与 `usage` 同源） */
  const unusedTools = computed(() => toolUsage.value?.unusedTools || [])

  /** 库里被引用、但不在目录表里的工具名（第 207 轮那处真缺口的可见面） */
  const unknownTools = computed(() => toolUsage.value?.unknownTools || [])

  /** 某个 Agent 已启用的技能（Agent 装配视图用） */
  function skillsOfAgent(agentName: string): Skill[] {
    return items.value.filter((s) => s.enabled && s.enabledAgents.includes(agentName))
  }

  async function loadAgents() {
    try {
      const res = await api.fetchAgents()
      agents.value = res.items || []
    } catch (e: any) {
      // Agent 目录是**静态元数据**，拉不到只影响勾选界面的标签显示，
      // 不该让整个页面空掉 —— 记错误、保留空数组（界面会退化成显示原始名）。
      error.value = e?.message || String(e)
    }
  }

  async function loadTools() {
    try {
      const res = await api.fetchTools()
      tools.value = res.items || []
      toolGroups.value = res.grouped || []
    } catch (e: any) {
      // ★ 与 `loadAgents` 同判据：工具目录是**静态元数据**，
      //   拉不到只影响勾选界面的候选列表（界面会退化成"显示原始工具名"），
      //   不该让整个技能仓库页面空掉。
      error.value = e?.message || String(e)
    }
  }

  async function loadToolUsage() {
    try {
      toolUsage.value = await api.fetchToolUsage()
    } catch (e: any) {
      // ★ 与 `loadAgents` / `loadTools` 同判据：反向引用是**增益信息**，
      //   拉不到只让工具仓库 tab 退化成"显示工具目录、不显示引用"，
      //   不该让整个技能仓库页面空掉（失败路径必须回写错误，不静默吞）。
      error.value = e?.message || String(e)
    }
  }

  async function loadSkills() {
    loading.value = true
    error.value = ''
    try {
      const res = await api.fetchSkills()
      items.value = res.items || []
    } catch (e: any) {
      error.value = e?.message || String(e)
    } finally {
      loading.value = false
    }
  }

  async function loadAll() {
    await Promise.all([loadAgents(), loadTools(), loadSkills(), loadToolUsage()])
  }

  /** 取详情（含正文）。★ 列表不带正文，编辑前必须拉一次详情。 */
  async function loadDetail(id: string): Promise<Skill | null> {
    try {
      const skill = await api.fetchSkill(id)
      current.value = skill
      return skill
    } catch (e: any) {
      error.value = e?.message || String(e)
      return null
    }
  }

  async function create(payload: Partial<Skill>): Promise<boolean> {
    saving.value = true
    error.value = ''
    try {
      await api.createSkill(payload)
      await loadSkills()
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    } finally {
      saving.value = false
    }
  }

  async function update(id: string, payload: Partial<Skill>): Promise<boolean> {
    saving.value = true
    error.value = ''
    try {
      await api.updateSkill(id, payload)
      await loadSkills()
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    } finally {
      saving.value = false
    }
  }

  async function remove(id: string): Promise<boolean> {
    error.value = ''
    try {
      await api.deleteSkill(id)
      await loadSkills()
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    }
  }

  /** 「Agent 内勾选启用」——全量覆盖该技能的启用 Agent 集合 */
  async function saveAgents(id: string, agentNames: string[]): Promise<boolean> {
    error.value = ''
    try {
      await api.setSkillAgents(id, agentNames)
      await loadSkills()
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    }
  }

  // ====== 工具仓库的筛选（第 209 轮）======
  //
  // ★ 与上面技能那套**同一范式**（照抄 `candidateLibrary.ts`）：
  //   筛选状态住 store、UI 只做 v-model、派生一律用 computed。
  //   放组件本地 ref 的后果一样：切 tab 回来被清空，用户以为"筛选不管用"。
  // ★ 默认值一律「不过滤」⇒ 默认状态下 `filteredToolGroups` 等价于 `toolGroups`。
  const toolSearchQuery = ref('')
  /** 归属 Agent（存**后端 agent_name**，与 `TOOL_CATALOG.agents` 同口径）*/
  const filterToolAgent = ref<string | undefined>(undefined)
  /** 副作用档：'approval'（需审批）| 'read_only'（只读）*/
  const filterToolEffect = ref<string | undefined>(undefined)
  /** 引用状态：'cited'（有技能引用）| 'uncited'（没有技能引用）*/
  const filterToolCited = ref<string | undefined>(undefined)

  /**
   * 筛选后的工具分组 —— **平铺与列表两个视图唯一的数据消费口**。
   *
   * ★ 顺手丢掉**空分组**：那是"筛空即空"这条体验的实现处。
   *   不丢的话界面会剩一堆只有标题的空卡片，看起来像加载失败。
   * ★ 搜索覆盖 name / title / description（工具名与说明都要能搜到）；
   *   额外带上归属 Agent 的中文名，因为筛选栏里 Agent 是按中文名选的。
   */
  const filteredToolGroups = computed(() => {
    const q = toolSearchQuery.value.trim().toLowerCase()
    const agent = filterToolAgent.value
    const effect = filterToolEffect.value
    const cited = filterToolCited.value
    return toolGroups.value
      .filter((g) => !agent || g.agent === agent)
      .map((g) => ({
        ...g,
        tools: g.tools.filter((t) => {
          if (effect && (t.effect || 'read_only') !== effect) return false
          // ★ store 内部：这两个是 computed ref（返回函数），⇒ 必须 .value
          const hasRef = usageOfTool.value(t.name).length > 0
          if (cited === 'cited' && !hasRef) return false
          if (cited === 'uncited' && hasRef) return false
          if (q) {
            const hay = [t.name, t.title, t.description, g.agentTitle,
              titleOfAgent.value(t.agent)].filter(Boolean).join(' ').toLowerCase()
            if (!hay.includes(q)) return false
          }
          return true
        }),
      }))
      .filter((g) => g.tools.length > 0)
  })

  /** 激活中的工具筛选数（挂在「重置筛选」按钮上，不另起一行 badge）*/
  const toolFilterCount = computed(() => {
    let n = 0
    if (toolSearchQuery.value.trim()) n++
    if (filterToolAgent.value) n++
    if (filterToolEffect.value) n++
    if (filterToolCited.value) n++
    return n
  })

  function resetToolFilters() {
    toolSearchQuery.value = ''
    filterToolAgent.value = undefined
    filterToolEffect.value = undefined
    filterToolCited.value = undefined
  }

  /**
   * 「配套工具」候选集 —— **收窄判定的唯一实现**（第 255 轮）。
   *
   * ★★ 为什么要收窄：工具是**按 Agent 装配**的（真源 `TOOL_CATALOG[].agent /
   *    agents`）。一条技能若绑了**不属于它启用 Agent** 的工具，运行期**调不到** ——
   *    模型会被技能正文引导去调一个它手上根本没有的名字。
   *    收窄 = 把这道校验**前移到界面**，而不是等运行期报"工具不存在"。
   *
   * ★★ 为什么必须是**唯一**实现：同一个字段 `skills.tools` 有**两个编辑入口** ——
   *    技能仓库的编辑抽屉、工具仓库的「skill 配装」tab。两份实现一定会漂移，
   *    而漂移的表现是「其中一个入口能造出运行期调不到的绑定」，
   *    界面上完全看不出来（门禁 `check-skill-tool-options-parity.cjs` 钉住唯一性）。
   *
   * ★ 已绑定但**不在候选里**的项必须**保留**（下面那个 orphan 分组）：
   *   编辑一条老技能时它的 `tools` 可能含当前 Agent 集合下不该有的项
   *   （Agent 勾选后来被改过）。直接丢弃 = 用户打开抽屉、什么都没动、
   *   一保存就**静默删掉了绑定**。
   *   ⇒ 判据「拿不到权威清单 ≠ 清单为空」：两个方向的代价不对称，
   *     保留旧值是安全方向（多做一次显式删除，好过静默丢数据）。
   *
   * ★ 分组标题带**后端给的原始 `agent` 名**（不只中文标题）：两个 Agent 的中文名
   *   可能相近，而"到底属于哪个 Agent"正是这个界面要判的东西。
   * ★ 工具名以下拉候选为准（`toolGroups` 来自后端 `/tools`）—— 库里的**退役名字**
   *   不在候选里，会落进 orphan 组，用户看得见也删得掉（这是唯一的清理路径）。
   */
  function toolOptionsFor(
    enabledAgents: string[],
    boundTools: string[]
  ): ToolOptionGroup[] {
    const selected = new Set(enabledAgents || [])
    const groups: ToolOptionGroup[] = []
    const shown = new Set<string>()

    for (const g of toolGroups.value) {
      if (!selected.has(g.agent)) continue
      const options = g.tools.map((t) => ({
        value: t.name,
        label: `${t.title}（${t.name}）${t.effect === 'approval' ? ' · 需审批' : ''}`,
      }))
      options.forEach((o) => shown.add(o.value))
      groups.push({ label: `${g.agentTitle} · ${g.agent}`, options })
    }

    const orphans = (boundTools || []).filter((t) => !shown.has(t))
    if (orphans.length) {
      groups.push({
        orphan: true,
        label: '已绑定（不属于上面勾选的 Agent，运行期不会被引导使用）',
        options: orphans.map((t) => ({
          value: t,
          label: `${titleOfTool.value(t)}（${t}）`,
        })),
      })
    }
    return groups
  }

  /**
   * 「skill 配装」——全量覆盖该技能**配备**的工具集合。
   *
   * ★ 成功后必须把 `loadToolUsage()` 也刷一遍：工具绑定变了 ⇒ **反向引用**
   *   跟着变。只刷技能列表的话，「被引用于」还停在旧答案上 ——
   *   界面不报错，只会**说谎**（本仓判据：静默错位比报错更难查）。
   */
  async function saveSkillTools(id: string, toolNames: string[]): Promise<boolean> {
    error.value = ''
    try {
      await api.setSkillTools(id, toolNames)
      await loadSkills()
      await loadToolUsage()
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    }
  }

  async function loadRevisions(id: string): Promise<void> {
    error.value = ''
    try {
      const res = await api.fetchSkillRevisions(id)
      revisions.value = res.items || []
    } catch (e: any) {
      error.value = e?.message || String(e)
      revisions.value = []
    }
  }

  async function rollback(id: string, revisionId: string): Promise<boolean> {
    saving.value = true
    error.value = ''
    try {
      await api.rollbackSkill(id, revisionId)
      await loadSkills()
      await loadRevisions(id)
      return true
    } catch (e: any) {
      error.value = e?.message || String(e)
      return false
    } finally {
      saving.value = false
    }
  }

  function clearError() {
    error.value = ''
  }

  return {
    items,
    agents,
    tools,
    toolGroups,
    loading,
    saving,
    error,
    current,
    revisions,
    total,
    // ---- 筛选 / 排序 / 分组 / 收藏（第 194 轮）----
    searchQuery,
    filterAgent,
    filterKind,
    filterStatus,
    onlyFavorites,
    groupByAgent,
    sortBy,
    collapsedGroups,
    filteredItems,
    groupedItems,
    activeFilterCount,
    resetFilters,
    toggleGroup,
    toggleFavorite,
    titleOfAgent,
    titleOfTool,
    isApprovalTool,
    skillsOfAgent,
    usageOfTool,
    unusedTools,
    unknownTools,
    toolUsage,
    // ---- 工具仓库筛选（第 209 轮）----
    toolSearchQuery,
    filterToolAgent,
    filterToolEffect,
    filterToolCited,
    filteredToolGroups,
    toolFilterCount,
    resetToolFilters,
    saveSkillTools,
    toolOptionsFor,
    loadAgents,
    loadTools,
    loadSkills,
    loadToolUsage,
    loadAll,
    loadDetail,
    create,
    update,
    remove,
    saveAgents,
    loadRevisions,
    rollback,
    clearError,
  }
})

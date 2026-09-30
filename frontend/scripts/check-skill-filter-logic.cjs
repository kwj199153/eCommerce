#!/usr/bin/env node
/**
 * 技能仓库「筛选 / 排序 / 分组」逻辑门禁（第 194 轮）
 *
 * ============================================================================
 * ★ 这条门禁为什么存在（而不是靠肉眼点页面）
 * ============================================================================
 * 本轮给技能仓库加了筛选器 + 排序 + 分组。这三样都是**纯派生逻辑**：
 * 没有接口、没有后端、页面上「看起来能用」。而它们各自都有一个
 * 「看起来对、其实错了」的形态，且**界面上看不出来**：
 *
 *   ① `cmpVersion` 若按字符串比，`'2.0.0' vs '10.0.0'` 的降序结果是**反的**——
 *      用户只会觉得「排序不太灵」，不会有人怀疑版本号比较。
 *   ② 分组的「未分配兜底」若漏了，`enabledAgents` 为空的技能在分组模式下
 *      **彻底消失**——而它很可能正是用户刚建好、还没分配的那一条。
 *   ③ `activeFilterCount` 若把排序/分组也算进去，「已筛选 N 项」这个数字的
 *      含义就无法解释了（用户会以为筛掉了东西）。
 *
 * 而这段逻辑住在 `defineStore(setup)` 里，**无法被独立单测**。
 * ⇒ 本脚本用 `ts.transpileModule` + `vm` 把整个 store 模块跑起来：
 *     `pinia` 换成 `defineStore = (_, setup) => setup`（setup 风格 store 直接
 *     拿到一整个 store 对象）、`@/api/skills` 换成空壳、
 *     `vue` 用**真的**（`ref` / `computed` 在 Node 里独立于组件即可工作）。
 *     零新依赖：`typescript` 与 `vue` 都是既有依赖。
 *
 * ★ 为什么不用 CDP 点页面：那样只能证明「我点的那一下对了」，
 *   而且每次都得重来。这条门禁是**永久**的，且能钉住边界值。
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 被测源文件可用环境变量指向**副本树**（依赖仍取真仓）：
 *   SKILL_FILTER_SRC_ROOT=<副本 frontend 目录>
 * 覆盖**两个**被测文件（第 248 轮起）：
 *   src/stores/skills.ts                        —— 筛选 / 排序 / 分组 + 「生效于」
 *   src/composables/chat/useAgentShortcuts.ts   —— 快捷卡片派生（isShortcut）
 * ★ 每条注入之间必须**从真文件重新生成副本**，否则上一条的注入会把
 *   下一条判红（假红）。参考实现：
 *     · `frontend/scripts/probe_248_inject.py`（本文件，第 248 轮加 F38~F39c 者）
 *     · `.workbuddy/tmp/r195_inject.py`
 *   ★★ 台架**必须用 Python 驱动**：写成 `.cjs` 用 `execFileSync(process.execPath,…)`
 *      在本机沙箱下必然 `EBUSY`（受管 node 不能再 spawn 受管 node），
 *      症状是"门禁输出为空 ⇒ 一条 FAIL 都抽不到"，会被误读成"注入没被拦住"。
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
/** 依赖（typescript / vue）永远取自**真仓** */
const SRC_ROOT = process.env.SKILL_FILTER_SRC_ROOT
  ? path.resolve(process.env.SKILL_FILTER_SRC_ROOT)
  : ROOT
const TARGET = 'src/stores/skills.ts'

let pass = 0
let fail = 0
const failures = []

function check(name, ok, detail) {
  if (ok) {
    pass++
    console.log('PASS  ' + name)
  } else {
    fail++
    failures.push(name + (detail ? '  | ' + detail : ''))
    console.log('FAIL  ' + name + (detail ? '  | ' + detail : ''))
  }
}

// ---------------------------------------------------------------------------
// 把 store 模块加载起来
// ---------------------------------------------------------------------------

function loadStore() {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const vue = require(path.join(ROOT, 'node_modules', 'vue'))
  const file = path.join(SRC_ROOT, TARGET)
  const src = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(src, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
    fileName: file,
  }).outputText

  const sandbox = {
    exports: {},
    module: { exports: {} },
    console: { log() {}, warn() {}, error() {} },
    require(id) {
      if (id === 'pinia') {
        // setup 风格 store：`defineStore(name, setup)` 直接返回 setup 本身
        return { defineStore: (_name, setup) => setup }
      }
      if (id === 'vue') return vue
      if (id === '@/api/skills') {
        // 空壳 api：所有导出都是 async noop（用例不触发网络）
        return new Proxy({}, { get: () => async () => ({}) })
      }
      throw new Error('沙箱未预期到的 import：' + id)
    },
  }
  sandbox.exports = sandbox.module.exports
  vm.runInNewContext(js, sandbox, { filename: file })

  const mod = sandbox.module.exports
  if (typeof mod.useSkillStore !== 'function') {
    throw new Error('模块里没有 useSkillStore 导出（转译后：' +
      Object.keys(mod).join(',') + '）')
  }
  return mod.useSkillStore()
}

// ---------------------------------------------------------------------------
// 造数据
// ---------------------------------------------------------------------------

function sk(o) {
  return Object.assign(
    {
      id: 'id-' + Math.random().toString(36).slice(2, 8),
      name: 'n',
      title: '',
      icon: '',
      description: '',
      tools: [],
      version: '1.0.0',
      visibility: 'account',
      enabled: true,
      enabledAgents: [],
      isDemo: false,
      accountId: null,
      createdAt: null,
      updatedAt: null,
    },
    o
  )
}

const AGENTS = [
  { name: 'product_research', id: 'research', title: '选品分析师', description: '' },
  { name: 'competitor_intel', id: 'competitor', title: '竞品监控员', description: '' },
]

function fresh(rows, agents) {
  const s = loadStore()
  s.agents.value = agents || AGENTS
  s.items.value = rows
  return s
}

// ---------------------------------------------------------------------------
// 载入
// ---------------------------------------------------------------------------

console.log('技能仓库「筛选 / 排序 / 分组」逻辑门禁 —— 盘面读数')
console.log('  目标        ' + TARGET)

let store
try {
  store = loadStore()
  check('L1 能把 store 模块加载起来（pinia/vue/api 三个依赖都被隔离）', true)
  console.log('  导出键数    ' + Object.keys(store).length)
} catch (e) {
  check('L1 能把 store 模块加载起来（pinia/vue/api 三个依赖都被隔离）', false,
    String(e && e.message))
  console.log('\n---- 0/1 通过（加载即失败，后续跳过）----')
  process.exit(1)
}

// ---------------------------------------------------------------------------
// 1. 默认不过滤
// ---------------------------------------------------------------------------

{
  const s = fresh([
    sk({ name: 'a', updatedAt: '2024-01-01T00:00:00' }),
    sk({ name: 'b', updatedAt: '2024-03-01T00:00:00' }),
  ])
  check('F1 默认状态下不过滤（条数 = 全部）', s.filteredItems.value.length === 2)
  check('F2 默认排序是「最近修改在前」',
    s.filteredItems.value[0].name === 'b',
    s.filteredItems.value.map((x) => x.name).join(','))
  check('F3 默认状态下 activeFilterCount = 0', s.activeFilterCount.value === 0)
}

// ---------------------------------------------------------------------------
// 2. 搜索覆盖三个字段（第 195 轮起不再搜 tags —— 概念已退役）
// ---------------------------------------------------------------------------

{
  const rows = [
    sk({ name: 'candidate-market-feasibility', title: '市场可行性' }),
    sk({ name: 'x2', title: '痛点分析' }),
    sk({ name: 'x3', title: '别的', description: '差评挖掘专用' }),
    sk({ name: 'x4', title: '第四' }),
  ]
  check('F4 搜索命中 name', (() => {
    const s = fresh(rows); s.searchQuery.value = 'market'; return s.filteredItems.value.length === 1
  })())
  check('F5 搜索命中 title', (() => {
    const s = fresh(rows); s.searchQuery.value = '痛点'; return s.filteredItems.value.length === 1
  })())
  check('F6 搜索命中 description', (() => {
    const s = fresh(rows); s.searchQuery.value = '差评'; return s.filteredItems.value.length === 1
  })())
  // ★ F7 是**概念退役钉子**：自定义标签已在第 195 轮整体退役（它只有筛选口、
  //   没有任何录入口 ⇒ 永远筛出 0 条）。
  //
  //   ★★ 这条钉子**必须自带诱饵**：单独塞一个带 tags 值的行进来。
  //      否则一旦有人把 tags 搜索加回 store，**也没有任何行能被命中**
  //      ⇒ 钉子永远绿（空跑）。诱饵让"把它加回来"这件事立刻转红。
  //      ——本仓铁律：没被反向注入验证过的门禁 = 没有门禁。
  //   ★ 诱饵只在这条用例里生效：F4~F9 其它用例各自 fresh(rows)，吃不掉它。
  check('F7 搜索**不再**命中已退役的 tags 字段（概念退役钉子）', (() => {
    const decoy = { ...sk({ name: 'x5', title: '第五' }), tags: ['合规', '选品'] }
    const s = fresh([...rows, decoy]); s.searchQuery.value = '合规'
    return s.filteredItems.value.length === 0
  })())
  check('F8 搜索大小写不敏感', (() => {
    const s = fresh(rows); s.searchQuery.value = 'MARKET'; return s.filteredItems.value.length === 1
  })())
  check('F9 搜索两头空白被忽略', (() => {
    const s = fresh(rows); s.searchQuery.value = '   痛点   '; return s.filteredItems.value.length === 1
  })())
}

// ---------------------------------------------------------------------------
// 3. 三个下拉 + 仅看收藏（标签筛选已随概念退役，第 195 轮）
// ---------------------------------------------------------------------------

{
  const rows = [
    sk({ name: 'r1', enabledAgents: ['product_research'], tools: [], enabled: true }),
    sk({ name: 'r2', enabledAgents: ['competitor_intel'], tools: ['analyze_profit'], enabled: false }),
    sk({ name: 'r3', enabledAgents: ['product_research'], isDemo: true }),
  ]
  check('F10 按 Agent 收窄', (() => {
    const s = fresh(rows); s.filterAgent.value = 'product_research'
    return s.filteredItems.value.map((x) => x.name).sort().join(',') === 'r1,r3'
  })())
  check('F11 类型=纯提示词（tools 为空）', (() => {
    const s = fresh(rows); s.filterKind.value = 'prompt'
    return s.filteredItems.value.map((x) => x.name).sort().join(',') === 'r1,r3'
  })())
  check('F12 类型=绑定工具（tools 非空）', (() => {
    const s = fresh(rows); s.filterKind.value = 'tool'
    return s.filteredItems.value.map((x) => x.name).join(',') === 'r2'
  })())
  check('F13 状态=已停用', (() => {
    const s = fresh(rows); s.filterStatus.value = 'disabled'
    return s.filteredItems.value.map((x) => x.name).join(',') === 'r2'
  })())
  check('F14 状态=演示', (() => {
    const s = fresh(rows); s.filterStatus.value = 'demo'
    return s.filteredItems.value.map((x) => x.name).join(',') === 'r3'
  })())
  // ★ F15 由「标签筛选命中任意一个」改为**fail-closed 钉子**（第 195 轮）：
  //   自定义标签概念已整体退役（它只有筛选口、没有任何录入口 ⇒ 永远筛出 0 条），
  //   原用例依赖的 `filterTags` 已不存在。
  //   新判据钉住一件更要紧的事：按**不存在的 Agent** 筛选必须得到**空**，
  //   不许 fail-open 回落成"筛不动就全给你"。这类静默回落是最难发现的假绿源。
  check('F15 按不存在的 Agent 筛选 ⇒ 空结果（fail-closed，不回落成全部）', (() => {
    const s = fresh(rows); s.filterAgent.value = '__no_such_agent__'
    return s.filteredItems.value.length === 0
  })())
  check('F16 仅看收藏', (() => {
    const s = fresh(rows.map((r, i) => ({ ...r, favorited: i === 1 })))
    s.onlyFavorites.value = true
    return s.filteredItems.value.map((x) => x.name).join(',') === 'r2'
  })())
  check('F17 多个条件叠加（交集）', (() => {
    const s = fresh(rows); s.filterAgent.value = 'product_research'; s.filterStatus.value = 'demo'
    return s.filteredItems.value.map((x) => x.name).join(',') === 'r3'
  })())
}

// ---------------------------------------------------------------------------
// 4. 排序（★ 版本号必须语义化）
// ---------------------------------------------------------------------------

{
  const rows = [
    sk({ name: 'v-old', version: '2.0.0', title: 'B 名', updatedAt: '2024-01-01T00:00:00' }),
    sk({ name: 'v-new', version: '10.0.0', title: 'A 名', updatedAt: '2024-02-01T00:00:00' }),
  ]

  // 自检（反向）：字符串降序会给出**相反**的答案 —— 证明 F19 的判据真的在测语义化
  const strOrder = ['2.0.0', '10.0.0'].slice().sort().reverse()[0]
  check('B1 自检（反向）：字符串序下 2.0.0 排在 10.0.0 前（所以字符串比较是错的）',
    strOrder === '2.0.0', strOrder)

  check('F18 按名称 A→Z', (() => {
    const s = fresh(rows); s.sortBy.value = 'name'
    return s.filteredItems.value[0].name === 'v-new'
  })())
  check('F19 ★ 按版本号降序是**语义化**的（10.0.0 在 2.0.0 之前）', (() => {
    const s = fresh(rows); s.sortBy.value = 'version'
    const got = s.filteredItems.value.map((x) => x.version).join(',')
    return got === '10.0.0,2.0.0'
  })(), '字符串序会得到 2.0.0,10.0.0')
  check('F20 版本号段数不等也能比（1.10 vs 1.9.0）', (() => {
    const s = fresh([
      sk({ name: 'a', version: '1.9.0' }),
      sk({ name: 'b', version: '1.10' }),
    ])
    s.sortBy.value = 'version'
    return s.filteredItems.value[0].version === '1.10'
  })())
  check('F21 版本号有怪格式也不抛错（按 0 处理）', (() => {
    const s = fresh([
      sk({ name: 'a', version: '' }),
      sk({ name: 'b', version: 'v2' }),
      sk({ name: 'c', version: '1.0.0' }),
    ])
    s.sortBy.value = 'version'
    return s.filteredItems.value.length === 3
  })())
}

// ---------------------------------------------------------------------------
// 5. 分组
// ---------------------------------------------------------------------------

{
  check('F22 不分组 = 只有一个「无标题分组」', (() => {
    const s = fresh([sk({ name: 'a' })])
    // ★★ 必须**显式**关掉分组，不能指望默认值 —— 这条判据断言的是
    //    `groupedItems` 的**不分组分支**，而 `groupByAgent` 的 store 默认值
    //    已经从 `false` 改成了 `true`（产品改为"默认按 Agent 分组"）。
    //    靠默认值表达"走哪个分支"会让判据与产品默认值**隐式耦合**：
    //    默认值一变，这条就恒红（本仓第 269 轮就是这样把整条 build 链卡住的），
    //    而红的原因看起来像"分组逻辑坏了"，归因方向完全错。
    //    本文件里其余分组用例（F23~F26）本来就写了 `= true`，F22 是唯一漏的。
    s.groupByAgent.value = false
    const g = s.groupedItems.value
    return g.length === 1 && g[0].title === '' && g[0].items.length === 1
  })())
  check('F23 分组按 Agent 目录顺序出组', (() => {
    const s = fresh([
      sk({ name: 'a', enabledAgents: ['product_research'] }),
      sk({ name: 'b', enabledAgents: ['competitor_intel'] }),
    ])
    s.groupByAgent.value = true
    return s.groupedItems.value.map((g) => g.key).join(',') ===
      'product_research,competitor_intel'
  })())
  check('F24 ★ 未分配的技能有兜底组（不能凭空消失）', (() => {
    const s = fresh([
      sk({ name: 'a', enabledAgents: ['product_research'] }),
      sk({ name: 'orphan', enabledAgents: [] }),
    ])
    s.groupByAgent.value = true
    const g = s.groupedItems.value
    const none = g.find((x) => x.key === '__none__')
    return !!none && none.items.map((x) => x.name).join(',') === 'orphan'
  })())
  check('F25 ★ 多归属技能在每个相关分组里各出现一次（正确语义）', (() => {
    const s = fresh([sk({ name: 'multi', enabledAgents: ['product_research', 'competitor_intel'] })])
    s.groupByAgent.value = true
    const g = s.groupedItems.value
    return g.length === 2 && g.every((x) => x.items.length === 1)
  })())
  check('F26 筛选后空掉的分组不出现（不留空标题）', (() => {
    const s = fresh([sk({ name: 'a', enabledAgents: ['product_research'] })])
    s.groupByAgent.value = true
    return s.groupedItems.value.map((g) => g.key).join(',') === 'product_research'
  })())
  check('F27 分组后各组条目数之和 ≥ 技能数（多归属会重复计数）', (() => {
    const s = fresh([
      sk({ name: 'multi', enabledAgents: ['product_research', 'competitor_intel'] }),
      sk({ name: 'one', enabledAgents: ['product_research'] }),
    ])
    s.groupByAgent.value = true
    const sum = s.groupedItems.value.reduce((n, g) => n + g.items.length, 0)
    return sum === 3
  })())
  check('F28 筛选与分组串起来（分组消费的是筛选后的行）', (() => {
    const s = fresh([
      sk({ name: 'a', enabledAgents: ['product_research'], title: '选品专用' }),
      sk({ name: 'b', enabledAgents: ['product_research'], title: '广告专用' }),
    ])
    s.groupByAgent.value = true
    s.searchQuery.value = '选品'
    const g = s.groupedItems.value
    return g.length === 1 && g[0].items.map((x) => x.name).join(',') === 'a'
  })())
}

// ---------------------------------------------------------------------------
// 6. activeFilterCount / resetFilters（+ 已退役符号的防复活钉子）
// ---------------------------------------------------------------------------

{
  const s = fresh([sk({ name: 'a' }), sk({ name: 'b' })])

  // ★ F29 由「tagOptions 并集」改为**防复活钉子**：第 195 轮整体退役了
  //   自定义标签概念，store 不应再导出这两个符号。若有人把它们加回来，这里转红。
  check('F29 ★ 已退役的标签符号不再从 store 导出（防概念复活）',
    s.filterTags === undefined && s.tagOptions === undefined,
    'filterTags=' + typeof s.filterTags + ', tagOptions=' + typeof s.tagOptions)

  s.searchQuery.value = 'a'
  s.filterAgent.value = 'product_research'
  s.filterKind.value = 'prompt'
  s.filterStatus.value = 'enabled'
  s.onlyFavorites.value = true
  check('F30 ★ activeFilterCount 累加全部筛选条件', s.activeFilterCount.value === 5,
    '实际 ' + s.activeFilterCount.value)

  s.sortBy.value = 'name'
  s.groupByAgent.value = true
  check('F31 ★ 排序与分组**不计入** activeFilterCount（它们不改变"显示哪些"）',
    s.activeFilterCount.value === 5, '实际 ' + s.activeFilterCount.value)

  s.resetFilters()
  check('F32 resetFilters 清空全部筛选', s.activeFilterCount.value === 0)
  check('F33 resetFilters 之后筛选结果回到全部', s.filteredItems.value.length === 2)
  check('F34 resetFilters 不动排序与分组（那两项不是筛选）',
    s.sortBy.value === 'name' && s.groupByAgent.value === true)
}

// ---------------------------------------------------------------------------
// 7. 折叠状态
// ---------------------------------------------------------------------------

{
  const s = fresh([sk({ name: 'a', enabledAgents: ['product_research'] })])
  s.groupByAgent.value = true
  check('F35 折叠状态默认全展开（未点过的组不是折叠的）',
    !s.collapsedGroups.value['product_research'])
  s.toggleGroup('product_research')
  check('F36 toggleGroup 能折叠', s.collapsedGroups.value['product_research'] === true)
  s.toggleGroup('product_research')
  check('F37 再点一次能展开', s.collapsedGroups.value['product_research'] === false)
}

// ---------------------------------------------------------------------------
// 8. ★★ 快捷卡片开关（`isShortcut`）—— 第 248 轮
// ---------------------------------------------------------------------------
//
// 背景（老板原话）：「我看了【复盘结论写法】是被周报月报**引用**的，那么这个
// 【复盘结论写法】是否不应该出现在快捷卡片栏」。
// 根因：`enabledAgents` 此前同时承担两个语义 ——「对本 Agent **生效**」与
// 「在对话页**显示为卡片**」。而「复盘结论写法」必须保留前者（周报 / 广告效果
// 复盘的正文逐字写着「表达结构沿用「复盘结论写法」」），只是不该占一格卡片。
// ⇒ 拆出 `isShortcut`（DB 列 `skills.as_shortcut`，默认 true = 保持现行为）。
//
// ★ 本节钉的是**两把闸的分工**，少任何一边都漏：
//     · 「卡片区」才看 `isShortcut` ⇒ 住在 `useAgentShortcuts.ts` 的卡片派生里；
//     · 「生效于」（`skillsOfAgent`）**不看** `isShortcut` ⇒ 管理页 / 工具仓库
//       仍然看得见这些技能（它们是「生效但无卡片」，不是「停用」）。
//     把过滤搬进 `skillsOfAgent` 的后果：管理页按 Agent 分组时这些技能
//     **凭空消失**，用户会以为被删了 —— 且没有任何一处会报错。

{
  // ---- F38：「生效于」不受 isShortcut 影响 ----
  // ★★★ 这一条**必须带诱饵**：塞一条 enabled + 已勾该 Agent + `isShortcut:false`
  //     的行。没有它，"把过滤搬进 skillsOfAgent" 这个注入**永远不会被察觉** ——
  //     普通测试行没有 `isShortcut` 字段，`!== false` 对 `undefined` 恒真
  //     ⇒ 断言恒绿。本仓铁律：没被反向注入验证过的门禁 = 没有门禁。
  check('F38 ★ skillsOfAgent（「生效于」）不受 isShortcut 影响（含 isShortcut:false 诱饵行）', (() => {
    const decoy = sk({
      name: 'no-card',
      enabled: true,
      enabledAgents: ['product_research'],
      isShortcut: false,
    })
    const normal = sk({
      name: 'with-card',
      enabled: true,
      enabledAgents: ['product_research'],
    })
    const s = fresh([decoy, normal])
    return s.skillsOfAgent('product_research').map((x) => x.name).sort().join(',') ===
      'no-card,with-card'
  })(), '把 isShortcut 过滤搬进 skillsOfAgent ⇒ 管理页按 Agent 分组时这些技能凭空消失')
}

{
  // ---- F39：卡片派生自己按 isShortcut 过滤 ----
  // ★ 读 `SRC_ROOT` 下的文件（而不是硬编码真仓路径）：这样它同样可以被
  //   `SKILL_FILTER_SRC_ROOT` 指向的副本树反向注入 —— 否则这条断言无法证明
  //   自己不是空跑（本仓：没被反向注入验证过的门禁 = 没有门禁）。
  const cards = fs.readFileSync(
    path.join(SRC_ROOT, 'src/composables/chat/useAgentShortcuts.ts'),
    'utf8',
  )
  const CARD_FILTER = /\.filter\(\(c\) => c\.isShortcut !== false\)/
  const STRICT_FILTER = /\.filter\(\(c\) => c\.isShortcut === true\)/

  check('F39 卡片派生（skillCards）按 isShortcut 过滤', CARD_FILTER.test(cards),
    'useAgentShortcuts.ts 里找不到 `.filter((c) => c.isShortcut !== false)`')

  check('F39b ★ 过滤方向是 `!== false`（缺字段按「显示」处理，取宽）',
    !STRICT_FILTER.test(cards),
    '用 `=== true` 会让缺该字段的旧响应 / 缓存里的旧对象静默丢光整排卡片（零报错）')

  check('F39c 卡片派生仍复用 store 的 skillsOfAgent（没有第二份「启用 + 归属 Agent」判定）',
    /skillStore\.skillsOfAgent\(/.test(cards),
    '卡片派生自己重写了一遍生效判定 ⇒ 立刻变成第二份实现（本仓判据：两份实现必有一份永远测不到）')
}

// ---------------------------------------------------------------------------
// 9. ★★ 撤卡片的 chip 措辞必须对**两类**撤卡技能都为真 —— 第 295 轮
// ---------------------------------------------------------------------------
//
// 起因（老板第 295 轮拍板 A 档）：「原则上我需要 agent 有相关领域技能，我可以
// 对话实现，功能栏和看板只是辅助（因为是要做 ai native saas）」⇒ 把「差评应对」
// 的快捷卡片撤下（`as_shortcut=False`），但技能本身留着当 Agent 的内功。
//
// ★★★ chip 此前写死了两句话：「仅方法论」+ tooltip「它是「怎么写」的规矩，
//   不是一份成品」。那两句话对第 248 轮那条（**规矩型**：复盘结论写法）为真，
//   对第 295 轮这条（**入口重复型**：差评应对 —— 4 步流程 + 5 个取证工具）为**假**。
//   ⇒ 用户看到「仅方法论」会以为"这条只是个写法规范"，从而低估它、
//     也不会想到去对话里用它 —— 而这恰恰是本轮要保住的那条路。
//   这是界面文案「字面为真、暗示为假」的又一形态，且**零报错**。
//
// ⇒ 判据必须是**对所有撤卡技能都为真**的中性措辞 + 必须承诺"能力仍在"
//   （"仍照常生效"是这张 chip 唯一有用的信息：用户真正要问的是
//    "撤了卡片，这条技能还用得上吗？"）。

{
  // ★ 读 `SRC_ROOT` 下的文件（同 F39）：这样它也能被 `SKILL_FILTER_SRC_ROOT`
  //   指向的副本树反向注入 —— 否则这条断言无法证明自己不是空跑。
  const mgrSrc = fs.readFileSync(
    path.join(SRC_ROOT, 'src/components/SkillStore/SkillManager.vue'),
    'utf8',
  )

  check('F40 ★ 撤卡片的 chip 不含「仅方法论」（那个词只对「规矩型」为真）',
    !mgrSrc.includes('仅方法论'),
    'chip 把「入口重复型」也说成了「只是方法论」⇒ 用户低估该技能、不去对话里用它')

  check('F40b ★ 两个视图都改了（卡片视图 + 列表视图，同一 chip 渲染两遍）',
    (mgrSrc.match(/>不设卡片</g) || []).length === 2,
    '`SkillManager.vue` 把同一个 chip 渲染了两遍；只改一处 ⇒ 另一处仍显示旧文案，' +
    '而两者的差异只在用户切换显示样式时才暴露')

  check('F40c chip 的 tooltip 承诺「仍照常生效」',
    /仍照常生效/.test(mgrSrc),
    'chip 只说"没有卡片"、不说"能力还在" ⇒ 用户会以为撤卡片 = 能力没了 ' +
    '（而撤卡片**只**关掉三条通道里的一条：目录注入 / load_skill 照常）')
}

// ---------------------------------------------------------------------------

console.log('')
if (fail === 0) {
  console.log('---- ' + pass + '/' + (pass + fail) + ' 通过 ----')
  console.log('技能仓库筛选/排序/分组逻辑成立（搜索四字段 · 版本号语义化 · 未分配兜底 · 多归属语义 ✓）')
  process.exit(0)
} else {
  console.log('---- ' + pass + '/' + (pass + fail) + ' 通过 ----')
  console.log('失败项：')
  failures.forEach((f) => console.log('  · ' + f))
  process.exit(1)
}

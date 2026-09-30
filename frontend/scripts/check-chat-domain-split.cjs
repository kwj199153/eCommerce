#!/usr/bin/env node
/**
 * 对话编排域「按域拆分」门禁（★ 第 169 轮 · #664）
 *
 * 为什么值得单独一个门禁
 * ====================
 * #664 把 `src/composables/useChatOrchestrator.ts` 从 **1,744 行 / 91 KB 的巨型闭包**
 * 拆成「装配壳 + `composables/chat/**`（18 个文件）」。这种拆分有**两类**典型翻车方式，
 * 而且两类都不会被类型系统或构建拦住：
 *
 *   ① **对外契约漂移**：`ChatPanel/index.vue` 解构了 30 个键；
 *      少一个 ⇒ 界面上某个动作条凭空消失（`undefined` 调不出错，只是不响应）；
 *      顺序改了 ⇒ 解构对不上号（同名字段不会，但改名 + 重排就会）。
 *   ② **拆分即重写**：搬的过程中「顺手优化」了某条分支，于是行为变了却没人知道。
 *      最危险的是**降级链被吞掉** —— 原来「API 挂了会退回通用提示」，
 *      拆完变成「静默什么都不做」，用户看到的是「点了没反应」。
 *
 * ⇒ 所以本门禁钉的是**结构不变量**，不是代码风格：
 *   A1  壳必须**薄**（棘轮：只减不增）—— 否则下次又会往里堆分支
 *   A2  域文件清单**冻结**（不多不少）—— 新增域要显式登记，防止「拆了又长回去」
 *   A3  壳的 `return { … }` 键**序列**与冻结清单逐项相等（顺序敏感）
 *   A4  分派器里 `agentId === '…'` 的**顺序**与冻结清单相等 ——
 *      它等价于「降级链的优先级」，改顺序就是改行为
 *   A5  4 个 mock 的消费者**必须落在允许清单内**（棘轮，目标全 0）
 *      —— 这是 #740/#741/#742/#743 的解锁凭据：拆分让每个 mock 只剩 1~3 个消费文件
 *   A6  装配槽守卫存在（稳定 thunk + 未回填即抛错 + 三处 set）
 *      —— 「同一个 handler 只能有一份实现」这条靠它守住
 *   A7  每个回复分支**必须**有 `return 'fallthrough'`（降级链不准被静默吞掉）
 *   A8  旧名 `simulateAgentResponse` 只允许在本域的分派器文件里作为内部别名出现
 *   A9  shop 作用域文案**只有一个名字**（第 190 轮）
 *      —— 数据作用域只有一层（X-Shop-ID），承载它的字段只允许一个消费点、前缀固定「店铺：」
 *
 * 怎么跑
 * ======
 *   node scripts/check-chat-domain-split.cjs            做判定
 *   node scripts/check-chat-domain-split.cjs --report    只打印盘面读数
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**：
 *   CHAT_SPLIT_SRC_ROOT=<副本 src 目录>
 * ★ 每条注入之间必须**从真文件重新生成副本**，否则上一条的注入会把下一条判红（假红）。
 *   还必须有一条**基线绿**（副本不改 ⇒ 必须全绿）和一条**对照绿**（只动注释 ⇒ 必须仍全绿）——
 *   否则「红」到底是注入打中了、还是副本本身不完整，读数上分不出来。
 *   参考实现：`.workbuddy/probes/i169_t664_inject.py`（14 例：基线 4 / 注入 8 / 对照 2，全绿）。
 *
 * ★ 与相邻门禁的分工
 *   · `check-plan-consumption.cjs` / `check-hitl-approval.cjs` / `check-app-actions.py`
 *     —— 判「某条业务链路通了没」；拆分后它们改读**整个编排域**（`scripts/_orch-domain.cjs`）
 *   · 本门禁 —— 判「编排域**结构**有没有退化」；它不管业务对不对
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.CHAT_SPLIT_SRC_ROOT
  ? path.resolve(process.env.CHAT_SPLIT_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 冻结清单

/** 壳的行数上限（棘轮：只减不增）。拆分后实测 154 行 ⇒ 留一点余量到 200。 */
const SHELL_MAX_LINES = 200

/** A2 域文件清单（相对 `src/`）。新增一个域 = 显式改动本清单。 */
const DOMAIN_FILES = [
  'composables/useChatOrchestrator.ts',
  'composables/chat/types.ts',
  // ★ 第 221 轮：失败文案的唯一实现（被四条回复链共同消费）
  'composables/chat/chatFailure.ts',
  // ★ 第 241 轮：取消收口的唯一实现（被 6 条流式链共同消费）
  'composables/chat/streamCancel.ts',
  'composables/chat/useChatRuntime.ts',
  'composables/chat/useVoiceAnnounce.ts',
  'composables/chat/useAgentShortcuts.ts',
  'composables/chat/toolResultPost.ts',
  'composables/chat/resultSummary.ts',
  'composables/chat/useChatEventBridge.ts',
  'composables/chat/useSecretaryPlan.ts',
  'composables/chat/replies/index.ts',
  'composables/chat/replies/secretary.ts',
  'composables/chat/replies/productResearch.ts',
  'composables/chat/replies/listing.ts',
  'composables/chat/replies/adAnalysis.ts',
  'composables/chat/replies/customerService.ts',
  'composables/chat/replies/competitorIntel.ts',
  'composables/chat/replies/review.ts',
  'composables/chat/replies/fallback.ts',
]

/**
 * A3 对外契约：`useChatOrchestrator()` 返回的键序列。
 * ★ 来源 = 拆分**前**那个 1,744 行版本的 `return { … }`（第 1703–1742 行），逐字复制。
 *   任何增删/重排都要同时改 `ChatPanel/index.vue` 的解构块。
 *
 * ★ 第 189 轮是**有意的功能变更**（老板批准，不是契约漂移）：
 *   四组硬编码动作条（竞品 3 / 选品 5 / 复盘 4 / 广告 2）合并为「**技能卡**动作条」
 *   （卡片 = 技能，读后端技能列表）。30 键 → 23 键：
 *   · 退场 13 = intelChips / activeIntelChip / runIntelChip / candidateIntelChips /
 *              runCandidateChip / REVIEW_ACTIONS / activeReviewAction / runReviewAction /
 *              reviewScopeColor / reviewScopeText / AD_QUICK_ACTIONS / activeAdAction /
 *              runAdQuickAction
 *   · 进场  6 = skillCards / activeSkillCard / runSkillCard / agentScopeText /
 *              agentScopeColor / agentScopeLabel
 *   本条仍按「逐项相等」判 —— 用意是**逼任何增删都显式落到本清单与组件解构两处**，
 *   而不是禁止变更（禁止变更会让「功能演进」与「契约漂移」没法区分）。
 *
 * ★ 第 241 轮再 +2（同样是老板批准的功能变更，不是漂移）：
 *   生成中要能**取消** ⇒ 壳对外多给 `isStreaming`（「生成中」的判据 —— 它**不是**
 *   `isLoading` 的同义词，六条流式链在首个 token 就到时把 isLoading 置回 false 了）
 *   与 `handleCancel`（「停止生成」按钮的落点）。23 键 → 25 键。
 *
 * ★ 第 250 轮再 +2（同样是老板批准的功能变更，不是漂移）：
 *   点名（`pendingSkill`）在「本轮只出纯文本」时会留到下一轮——这是**故意**的
 *   （追问的答案必须还能用上点名），但它对用户**不可见**。⇒ 新增可见 chip 与撤销出口：
 *   `pendingSkillCard`（点名的中文标题，查不到退回 name）+ `dismissPendingSkill`（chip 的 ×）。
 *   25 键 → 27 键。形态判据在 `check-chat-failure-path.cjs` 的 L10。
 *   ★ 第 251 轮再加一个 `contextTarget`（本次请求的「作用对象」，三态）——
 *   27 键 → 28 键。它是配「前置缺失却凭会话历史凑出评估对象」那个洞的：
 *   前端必须把「本次有没有对象」**明确**告诉后端（`null` ≠ 不带该字段）。
 */
const RETURN_KEYS = [
  'messages', 'isLoading', 'isStreaming', 'loadingTip', 'inputPlaceholder',
  'secretaryPlan', 'loadSecretaryPlan',
  'isCompetitorIntelAgent', 'isProductResearchAgent', 'isListingAgent', 'isReviewAgent', 'isAdAnalyst',
  'skillCards', 'activeSkillCard', 'runSkillCard',
  'periodOptions', 'agentScopeText', 'agentScopeColor', 'agentScopeLabel',
  'removeToolResult', 'handleNavigateTo', 'renderMarkdown', 'handleKeyPress', 'handleSend',
  'handleCancel',
  // 第 250 轮：点名可见 chip（残留窗口的显式出口）
  'pendingSkillCard', 'dismissPendingSkill', 'contextTarget',
  // ★ 第 298 轮：**作用对象**的取消入口（老板 bug2「上下文被某条处置差评填入后，
  //   你没有给取消按钮」）。与 `pendingSkillCard/dismissPendingSkill` 同族 ——
  //   "还在生效"必须可见 + 必须能撤销；两者都从壳里转发出去。
  //   ★ 只有两个键：按钮文案里的对象名复用既有的 `agentScopeLabel`
  //     （同一 `id`、同一份 `TARGET_LABELS`）—— 多开一个键就是同一事实的第二份表达。
  'scopeTargetLoaded', 'clearScopeTarget',
]

/**
 * A4 分派顺序 = 降级链优先级。改顺序就是改行为 ⇒ 冻结。
 * （原实现是「一串 `if (agentId === …) { try … catch … }`」，未 return 的 catch 会穿透到下一个。）
 */
const DISPATCH_ORDER = [
  'secretary',
  'product-research',
  'listing-generator',
  'ad-analysis',
  'customer-service',
  'competitor-intel',
  'review-analyst',
]

/**
 * A5 每个 mock 的**允许消费者**（相对 `src/`）。
 * ★ 这是一条**棘轮**：只允许变少。每退役一个 mock，就把它的行删掉。
 *   拆分前 `@/mock/toolExecutors` 的消费者是「那个 1,744 行的编排器」；
 *   拆分后收敛到**一个文件** —— 这就是 #740 的落点。
 */
const MOCK_ALLOWLIST = {
  '@/mock/toolExecutors': ['composables/chat/useChatEventBridge.ts'],
  '@/mock/competitorIntel': [
    'composables/chat/useAgentShortcuts.ts',
    'composables/chat/useChatEventBridge.ts',
    'composables/chat/replies/competitorIntel.ts',
  ],
  '@/mock/secretaryBrain': ['composables/chat/replies/secretary.ts'],
  // `@/mock/data` 只被 toolExecutors 自己间接消费 ⇒ 退役顺序上它排最后（#743）
  '@/mock/data': ['mock/toolExecutors.ts'],
}

/** A8 旧名只允许出现在分派器里（作为内部别名） */
const LEGACY_ALIAS = 'simulateAgentResponse'
const LEGACY_ALLOWED = ['composables/chat/replies/index.ts']

/** A7：最后一跳（通用兜底）。它天然不会提前终止，因此不要求有 'handled' 出口。 */
const LAST_RESORT = 'composables/chat/replies/fallback.ts'

/**
 * A9 作用域文案的唯一真源（★ 第 190 轮老板裁决）。
 *
 * 背景：老板看动作条截图后追问「是不是不同 Agent 有不同作用域？有的是账户级别，
 * 有的是店铺级别」。实测**没有** —— 本仓的数据作用域**只有一层**：
 *
 *     X-Shop-ID → store_id      （core/tenant/scoping.py 的 SHOP_SCOPE_ATTR）
 *     accounts（团队容器）       —— 只是归属容器，不是数据分区
 *
 * 八个 Agent 走的是**同一个** `Depends(get_current_shop_id)`，`AGENT_CATALOG` 里
 * 也没有 scope 字段。但界面上复盘写「店铺：X」、广告写「广告账户：X」，两者读的
 * 却是同一个 `shopStore.currentShop.name` ⇒ **凭空多出一个不存在的层级**，
 * 用户据此推断两个 Agent 作用域不同。这正是「同一个底层事实有两个名字」的经典形态。
 *
 * 判据用**代码形态**而不是禁词表：这个字段的消费点数只允许为 1，且前缀固定。
 * 再造第二个名字 ⇒ 计数变 2 ⇒ 直接红（不关心新名字叫什么，禁词表必漏）。
 */
const SHOP_SCOPE_RE = /shopStore\s*\.\s*currentShop\s*\??\.\s*name/
const SHOP_SCOPE_PREFIX = '店铺：'

// ---------------------------------------------------------------- 工具

function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const c2 = src[i + 1]
    if (c === '/' && c2 === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue }
    if (c === '`' || c === '"' || c === "'") {
      const q = c
      out += c; i++
      while (i < n && src[i] !== q) { if (src[i] === '\\') { out += src[i]; i++ } if (i < n) { out += src[i]; i++ } }
      out += q; i++; continue
    }
    out += c; i++
  }
  return out
}

function readSrc(rel) {
  const p = path.join(SRC_ROOT, rel)
  if (!fs.existsSync(p)) throw new Error('文件不存在：' + rel)
  return fs.readFileSync(p, 'utf8')
}

/**
 * 抽出 `return { … }` 里的键序列（跳过注释行）。
 *
 * ★ 必须取**最后一个** `return {`：壳里 `slot()` 也有一句
 *   `return { get, set: (fn) => {...} }`（单行对象字面量）。用 indexOf 会命中它，
 *   于是键序列恒为空 —— 而空序列与「键全丢了」在读数上无法区分（本门禁第一版就是这么假绿的）。
 */
function extractReturnKeys(code) {
  const i = code.lastIndexOf('  return {')
  if (i < 0) return []
  const seg = code.slice(i + '  return {'.length)
  const j = seg.indexOf('\n  }')
  const body = j >= 0 ? seg.slice(0, j) : seg
  const keys = []
  for (const raw of body.split('\n')) {
    const s = raw.trim()
    if (!s || s.startsWith('//')) continue
    const t = s.replace(/,$/, '')
    if (/^[A-Za-z_$][\w$]*$/.test(t)) keys.push(t)
  }
  return keys
}

/** 抽出 `if (agentId === '…')` 的顺序 */
function extractDispatchOrder(code) {
  const out = []
  const re = /if\s*\(\s*agentId\s*===\s*'([a-z-]+)'\s*\)/g
  let m
  while ((m = re.exec(code)) !== null) out.push(m[1])
  return out
}

/** 抽出模块说明符 */
function extractSpecifiers(code) {
  const out = []
  const re = /(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g
  let m
  while ((m = re.exec(code)) !== null) out.push(m[1])
  return out
}

function walkSrc(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (['node_modules', 'dist', '.git'].includes(e.name)) continue
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walkSrc(p, out)
    else if (/\.(ts|vue|tsx|js|mts)$/.test(e.name)) out.push(p)
  }
  return out
}

// ---------------------------------------------------------------- 判定框架

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) }
  catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

// ---------------------------------------------------------------- 盘面读数

const shellCode = readSrc('composables/useChatOrchestrator.ts')
const shellClean = stripComments(shellCode)
const shellLines = shellCode.split(/\r?\n/).length
const replyIndex = readSrc('composables/chat/replies/index.ts')

console.log('对话编排域拆分门禁 —— 盘面读数')
console.log(`  src 根      ${path.relative(ROOT, SRC_ROOT) || '.'}`)
console.log(`  壳          composables/useChatOrchestrator.ts  ${shellLines} 行（上限 ${SHELL_MAX_LINES}）`)
console.log(`  域文件      ${DOMAIN_FILES.length} 个`)
console.log(`  返回面      ${extractReturnKeys(shellClean).length} 个键`)
console.log(`  分派顺序    ${extractDispatchOrder(stripComments(replyIndex)).join(' → ')}`)
console.log('')

if (REPORT_ONLY) {
  const files = walkSrc(SRC_ROOT, [])
  for (const mock of Object.keys(MOCK_ALLOWLIST)) {
    const hit = []
    for (const f of files) {
      const rel = path.relative(SRC_ROOT, f).replace(/\\/g, '/')
      if (stripComments(fs.readFileSync(f, 'utf8')).includes(mock)) hit.push(rel)
    }
    console.log(`  ${mock.padEnd(26)} ${hit.length} 个消费者：${hit.join(', ') || '无'}`)
  }
  process.exit(0)
}

// ==================== A. 结构不变量 ====================

check(`A1 装配壳必须薄（≤ ${SHELL_MAX_LINES} 行）`, () => {
  assert(shellLines <= SHELL_MAX_LINES,
    `壳已 ${shellLines} 行（上限 ${SHELL_MAX_LINES}）。` +
    '拆开的目的是**不让它再长回去** —— 新逻辑请落到 composables/chat/ 下的对应域文件里。')
  assert(shellLines >= 40, `壳只有 ${shellLines} 行 —— 装配逻辑不该少到这个程度，检查是不是被误删了。`)
})

check('A2 域文件清单与冻结清单逐项相等（不多不少）', () => {
  const found = new Set()
  const inst = ['composables/useChatOrchestrator.ts']
  for (const rel of DOMAIN_FILES) inst.push(rel)
  for (const rel of inst) assert(fs.existsSync(path.join(SRC_ROOT, rel)), `缺文件：${rel}`)
  for (const f of walkSrc(path.join(SRC_ROOT, 'composables', 'chat'), [])) {
    found.add(path.relative(SRC_ROOT, f).replace(/\\/g, '/'))
  }
  const expect = new Set(DOMAIN_FILES.filter((d) => d.startsWith('composables/chat/')))
  const extra = [...found].filter((f) => !expect.has(f))
  const miss = [...expect].filter((f) => !found.has(f))
  assert(extra.length === 0 && miss.length === 0,
    `域文件清单漂移。多出：${extra.join(', ') || '无'}；缺失：${miss.join(', ') || '无'}` +
    '（新增域请显式登记进 DOMAIN_FILES，别让编排域悄悄长回去）')
})

check('A3 对外键序列与冻结清单逐项相等（顺序敏感；第 298 轮起为 30 键）', () => {
  const got = extractReturnKeys(shellClean)
  assert(got.length === RETURN_KEYS.length,
    `返回键从 ${RETURN_KEYS.length} 个变成 ${got.length} 个：${got.join(', ')}`)
  const diff = got.findIndex((k, i) => k !== RETURN_KEYS[i])
  assert(diff < 0,
    `返回键第 ${diff + 1} 个是 '${got[diff]}'，应为 '${RETURN_KEYS[diff]}'。` +
    'ChatPanel/index.vue 解构这些键。增删请同时改本清单与该组件的解构块 —— ' +
    '只改一处的结果是「界面少了一个动作条」或「返回了一个没人用的键」，两者都不报错。')
})

check('A4 分派顺序（= 降级链优先级）与冻结清单相等', () => {
  const got = extractDispatchOrder(stripComments(replyIndex))
  assert(got.join(',') === DISPATCH_ORDER.join(','),
    `分派顺序变了。\n        实测 = ${got.join(' → ')}\n        应为 = ${DISPATCH_ORDER.join(' → ')}\n` +
    '原实现是一串 `if (agentId === …) { try … catch … }`，未 return 的 catch 会「穿透」到下一个分支 —— ' +
    '所以顺序等价于降级链优先级，改顺序就是改行为。')
})

check('A5 4 个 mock 的消费者必须落在允许清单内（棘轮：只减不增）', () => {
  const files = walkSrc(SRC_ROOT, [])
  const bad = []
  const report = []
  for (const [mock, allowed] of Object.entries(MOCK_ALLOWLIST)) {
    const hit = []
    for (const f of files) {
      const rel = path.relative(SRC_ROOT, f).replace(/\\/g, '/')
      if (stripComments(fs.readFileSync(f, 'utf8')).includes(mock)) hit.push(rel)
    }
    report.push(`${mock} → ${hit.length} 个：${hit.join(', ') || '无'}`)
    for (const h of hit) if (!allowed.includes(h)) bad.push(`${mock} @ ${h}`)
    for (const a of allowed) if (!hit.includes(a)) {
      // 允许清单里的条目消失了 = 好方向（mock 又少了一个消费者）⇒ 只提示，不红
      console.log(`  --   ${mock} 的消费者 ${a} 已消失（这是好事，请把该条目从白名单删掉）`)
    }
  }
  assert(bad.length === 0,
    `出现了白名单之外的新消费者：\n        ${bad.join('\n        ')}\n` +
    `        现状：${report.join(' | ')}\n` +
    '这四个 mock 是待退役对象（#740 toolExecutors / #741 competitorIntel / #742 secretaryBrain / #743 data）。' +
    '新代码请调 api/**，不要再 import mock/**；若确实必须，请显式更新本门禁的白名单并说明理由。')
})

check('A6 装配槽守卫存在（稳定 thunk + 未回填即抛错 + 三处 set）', () => {
  // ★ `slot<T extends …>(name)` 带泛型形参 ⇒ 正则必须允许 `<` 紧跟函数名
  //   （只写 `slot\s*\(` 会漏掉，本门禁第一版就是这么假红的）
  assert(/function\s+slot\s*[<(]/.test(shellClean), '壳里没有 slot() —— 跨域回调的装配期回填机制不见了')
  assert(/装配完成前被调用/.test(shellCode),
    'slot() 缺少「未回填即抛错」的守卫 ⇒ 编排顺序写错时会静默变成「点了没反应」')
  // 槽名 ↔ ctx 字段名（槽名与字段名**故意不同名**：槽是装配细节，字段才是契约）
  const SLOTS = { handleSend: 'sendSlot', runAgentReply: 'replySlot', ensureCandidateLoaded: 'candSlot' }
  for (const [field, slotName] of Object.entries(SLOTS)) {
    assert(new RegExp(`${slotName}\\s*\\.\\s*set\\s*\\(`).test(shellClean),
      `没有回填 ${slotName} ⇒ ctx.${field} 永远是那个抛错的占位 thunk`)
    assert(new RegExp(`${field}\\s*:\\s*${slotName}\\.get`).test(shellClean),
      `ctx.${field} 没有接上 ${slotName}.get ⇒ 跨域调用拿不到实现`)
  }
})

check("A7 每个回复分支必须有 return 'fallthrough'（降级链不准被吞）", () => {
  const dir = path.join(SRC_ROOT, 'composables', 'chat', 'replies')
  const missing = []
  for (const f of walkSrc(dir, [])) {
    const rel = path.relative(SRC_ROOT, f).replace(/\\/g, '/')
    if (rel.endsWith('/index.ts')) continue
    const code = stripComments(fs.readFileSync(f, 'utf8'))
    if (!/Promise<ReplyOutcome>/.test(code)) { missing.push(`${rel}（签名不是 ReplyOutcome）`); continue }
    if (!/return\s+'fallthrough'/.test(code)) missing.push(`${rel}（没有 fallthrough 出口）`)
    // ★ 最后一跳（通用兜底）本来就**不会**提前终止 ⇒ 它没有 'handled' 是对的，
    //   不要为了「整齐」给它补一个 —— 那会把「什么都没接住」伪装成「已处理」。
    if (rel !== LAST_RESORT && !/return\s+'handled'/.test(code)) {
      missing.push(`${rel}（没有任何 handled 出口）`)
    }
  }
  assert(missing.length === 0,
    `以下分支的降级语义不完整：\n        ${missing.join('\n        ')}\n` +
    "拆分前这些分支是「catch 之后不 return ⇒ 控制流继续往下走到通用兜底」；" +
    "拆开后必须显式表达为 'fallthrough'，否则「API 挂了」会变成「点了没反应」。")
})

check(`A8 旧名 ${LEGACY_ALIAS} 只允许留在分派器里（作为内部别名）`, () => {
  const files = walkSrc(SRC_ROOT, [])
  const hits = []
  for (const f of files) {
    const rel = path.relative(SRC_ROOT, f).replace(/\\/g, '/')
    if (stripComments(fs.readFileSync(f, 'utf8')).includes(LEGACY_ALIAS)) hits.push(rel)
  }
  const bad = hits.filter((h) => !LEGACY_ALLOWED.includes(h))
  assert(bad.length === 0,
    `${LEGACY_ALIAS} 又扩散到：${bad.join(', ')}。` +
    '这个名字把「真后端链路」和「本地假数据」混在一起 —— 别再往外传。')
})

check('A9 shop 作用域文案只有一个消费点，且前缀固定为「店铺：」', () => {
  const hits = []
  for (const f of walkSrc(SRC_ROOT, [])) {
    const rel = path.relative(SRC_ROOT, f).replace(/\\/g, '/')
    const code = stripComments(fs.readFileSync(f, 'utf8'))
    const n = (code.match(new RegExp(SHOP_SCOPE_RE.source, 'g')) || []).length
    if (n) hits.push({ rel, n, code })
  }
  const total = hits.reduce((a, h) => a + h.n, 0)
  assert(total > 0,
    `全前端找不到取值点 —— 右侧上下文条会永远显示「（无上下文参数）」，且零报错。`)
  assert(total === 1,
    `shopStore.currentShop.name 出现 ${total} 次（应为 1）：\n        ` +
    hits.map((h) => `${h.rel} × ${h.n}`).join('\n        ') +
    '\n        这个字段承载**唯一的一层数据作用域**（店铺）。多点读取 = 又给同一层起了' +
    '第二个名字（第 190 轮之前的形态：复盘「店铺：X」与广告「广告账户：X」读的是同一个字段），' +
    '用户会据此推断两个 Agent 作用域不同。')
  const h = hits[0]
  const line = h.code.split('\n').find((l) => SHOP_SCOPE_RE.test(l)) || ''
  assert(line.includes(SHOP_SCOPE_PREFIX),
    `作用域文案前缀不是「${SHOP_SCOPE_PREFIX}」，实测该行：${line.trim()}\n        ` +
    '本仓没有「广告账户」「站点」这一层 —— 后端作用域只有 stores_store（X-Shop-ID）；' +
    '广告分析那 10 个端点用的也是同一个 get_current_shop_id。')
})

// ==================== B. 自检（证明上面的提取器不是空跑）====================

check('B1 自检（正向）：return 键提取器能认出带注释与尾逗号的对象字面量', () => {
  const sample = [
    'function f() {',
    '  return {',
    '    // 状态',
    '    a,',
    '    b,',
    '    // 更多的',
    '    c,',
    '  }',
    '}',
  ].join('\n')
  const got = extractReturnKeys(sample)
  assert(got.join(',') === 'a,b,c', `提取器读数 ${JSON.stringify(got)}，应为 ["a","b","c"]`)
})

check('B2 自检（正向）：分派顺序提取器认得出 agentId 三元判断的书写形态', () => {
  const sample = "if (agentId === 'x-y') {\n}\nif (agentId === 'z') {\n}"
  assert(extractDispatchOrder(sample).join(',') === 'x-y,z', '顺序提取器失配')
})

check('B3 自检（反向）：把 mock 说明符塞进注释，A5 的扫描必须不受影响', () => {
  const sample = stripComments("// import { x } from '@/mock/toolExecutors'\n/* from '@/mock/secretaryBrain' */")
  assert(!sample.includes('@/mock/'), '剥注释没生效 —— 注释里的模块名会让 A5 假红')
  const live = stripComments("const x = await import('@/mock/secretaryBrain')")
  assert(live.includes('@/mock/secretaryBrain'), '真 import 没被认出来 —— A5 会假绿')
})

check('B4 自检（反向）：注释里的旧措辞不算数，真代码里的第二个名字必须被 A9 抓到', () => {
  const commented = stripComments(
    '// 曾经写 `广告账户：${shopStore.currentShop.name}`\n/* 同理，这是历史 */')
  assert(!SHOP_SCOPE_RE.test(commented),
    '剥注释没生效 —— 解释性注释里引用的旧写法会被 A9 当成真消费点（假红）')
  const twice = 'const a = `店铺：${shopStore.currentShop.name}`\n' +
    'const b = `广告账户：${shopStore.currentShop?.name}`'
  const n = (stripComments(twice).match(new RegExp(SHOP_SCOPE_RE.source, 'g')) || []).length
  assert(n === 2, `扫描器读数 ${n}，应为 2 —— A9 会假绿（放过了第二个名字）`)
})

// ---------------------------------------------------------------- 汇总

console.log('')
let failed = 0
for (const [name, err] of results) {
  if (err) { failed++; console.log(`FAIL  ${name}\n        ${err}`) }
  else console.log(`PASS  ${name}`)
}
console.log('')
if (failed) {
  console.log(`---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
  process.exit(1)
}
console.log(`---- ${results.length}/${results.length} 通过 ----`)
console.log('编排域结构不变量成立（壳薄 · 域清单冻结 · 对外键序列与冻结清单相等 · 降级链完整 · mock 消费者受限 ✓）')

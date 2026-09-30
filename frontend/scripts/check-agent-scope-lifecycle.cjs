#!/usr/bin/env node
/**
 * 「Agent 级共享上下文」生命周期门禁（★ 第 251 轮）
 *
 * 为什么值得单独一个门禁
 * ====================
 * `Workspace.vue` 用 `provide()` 挂了三个**Agent 级共享上下文**：
 *   · `workingProduct`   —— Listing 优化师 / AIGC 媒体生成器的「载入产品」
 *   · `workingCandidate` —— 选品分析师的「载入选品」
 *   · `workingReview`    —— 智能客服的「处置差评」（第 298 轮；由差评处置台账
 *     的「在对话里处置这条」写入）。它与上面两个同属「载入型」语义：
 *     离开属主就清空 —— 否则别的 Agent 的对话会把上一条差评当成本次作用对象。
 * 它们是一次性 `ref`，**生命周期完全靠人手工维护** —— 切 Agent 时要有人清空。
 *
 * 实测事故（第 251 轮报障，老板截图）：listing 载入商品后切到别的 Agent，
 * 右栏顶部仍挂着那个商品名。根因是**清空只做了一半**：
 * 切 Agent 的 watch 里只清了 `currentWorkingCandidate`（注释还明写着「避免携带到
 * 其它 Agent」），`currentWorkingProduct` **整条漏了**。
 *
 * 为什么是「静默」的、必须靠门禁守
 * ------------------------------
 * 残留不是崩溃，而是**别的 Agent 读到上一个 Agent 的对象**：
 *   · `TaskConfigPanel/index.vue` 的 `v-if="workingProduct"` 标签 → 全部 Agent 右栏顶部可见
 *   · `PitfallsConfig` 的 `canSubmit` 会因残留而**直接变可提交**
 *   · `CompetitorConfig` 会把残留商品当成竞品集的**「当前主角」**
 *   · `SEOConfig` / `ABTestConfig` / `VideoGeneratorConfig` 的 `watch(workingProduct, …)`
 *     会把上一个商品的字段**自动填进表单**
 * 而且**删掉那行显示并不能修它** —— 显示判的就是泄漏的状态；修法只有一条：
 * 在切 Agent 时**成对**清空。
 *
 * 三个典型翻车方式（本门禁各钉一条）
 * ----------------------------------
 *   S1 **属主判定出现第二份实现** ⇒ 显示与清空漂移 ⇒ 漏清/误清
 *   S2 **清空不成对**（只清一个 ref）⇒ 另一个静默残留（就是本次事故）
 *   S3 **新增 Agent 级上下文忘了登记** ⇒ 它压根没有清空策略，且没人会注意到
 *   S6 **默认工具登记了一条不存在的工具 id** ⇒ 死登记：看着像有，其实永远不生效
 *   S7 **默认工具退化成「取工具数组第一个」** ⇒ 默认值被数组顺序决定，插一个工具就静默改
 *
 * 怎么跑
 * ======
 *   node scripts/check-agent-scope-lifecycle.cjs            做判定
 *   node scripts/check-agent-scope-lifecycle.cjs --report    只打印盘面读数
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**：
 *   AGENT_SCOPE_SRC_ROOT=<副本 src 目录>
 * ★ 每条注入之间必须**从真文件重新生成副本**，否则上一条的注入会把下一条判红（假红）。
 *   还必须有一条**基线绿**（副本不改 ⇒ 全绿）与一条**对照绿**（只动注释 ⇒ 仍全绿）。
 *   参考实现：`.workbuddy/probes/` 下第 251 轮的注入台架。
 *
 * ★ 与相邻门禁的分工
 *   · `check-chat-domain-split.cjs` —— 判**编排域**结构（壳薄 / 域清单 / 降级链）
 *   · 本门禁 —— 判 **Agent 级共享上下文的生命周期**；它不管业务对不对
 *   · `check-agent-sort-parity.cjs` —— 判 Agent 列表排序相关，与本门禁主题不同
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.AGENT_SCOPE_SRC_ROOT
  ? path.resolve(process.env.AGENT_SCOPE_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 冻结清单

/**
 * S3 的登记表：**所有** Agent 级共享上下文 ref 都必须在这里出现。
 *
 * ★ 它与「按命名约定自动发现」是**互补的两半**，缺一不可：
 *   · 自动发现（S3-a）负责「新增了却没登记」—— 它只看得到名字
 *   · 本表（S3-b）负责「登记了却没清空」—— 它给出每个 ref 的**守护谓词名**
 *   只做前一半 ⇒ 新增能被发现，但没人知道该配哪个谓词；
 *   只做后一半 ⇒ 新增的 ref 根本不进检查范围（静默漏管）。
 */
const AGENT_SCOPE_REFS = [
  {
    ref: 'currentWorkingProduct',
    predicate: 'isProductLoaderAgent',
    why: 'Listing 优化师 / AIGC 的「载入产品」—— 残留会让别的 Agent 的 canSubmit / 竞品主角 / 表单预填读到它',
  },
  {
    ref: 'currentWorkingCandidate',
    predicate: 'isCandidateLoaderAgent',
    why: '选品分析师的「载入选品」—— 残留会让别的 Agent 继续拿它当评估对象',
  },
  {
    ref: 'currentWorkingReview',
    predicate: 'isReviewLoaderAgent',
    why: '客服的「处置差评」（第 298 轮）—— 残留会让别的 Agent 的对话把上一条差评当成本次作用对象',
  },
]

/** 判定所在文件（唯一：Agent 级上下文只挂在 Workspace 这一层） */
const WORKSPACE = 'views/Workspace.vue'

/**
 * 默认工具规格表所在文件（相对 SRC_ROOT）。
 * ★ 为什么门禁要读它：`AGENT_DEFAULT_TOOL` 的**取值**合法性（登记的 toolId 是否真存在）
 *   只能拿 `AGENT_TOOLS` 对账；文本层判不出「死登记」。
 */
const TOOL_DEFS = 'components/ChatPanel/tools/toolDefinitions.ts'

/** 切 Agent 的 watch 起点（S2 的定位锚点） */
const WATCH_ANCHOR = 'watch([() => agentStore.currentAgent, () => agentStore.agentClickCounter]'

// ---------------------------------------------------------------- 读取与工具

function readSrc(rel) {
  // ★ 行尾归一化：本仓 CRLF / LF 混存 ⇒ 不归一化会让锚点静默 0 命中
  return fs.readFileSync(path.join(SRC_ROOT, rel), 'utf8').replace(/\r\n/g, '\n')
}

/** 剥注释（字符串内的 `//` 不能误伤；本仓既有实现同构） */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  let quote = null
  while (i < n) {
    const c = src[i]
    const nxt = src[i + 1]
    if (quote) {
      out += c
      if (c === '\\') { out += nxt || ''; i += 2; continue }
      if (c === quote) quote = null
      i++
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i++; continue }
    if (c === '/' && nxt === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '/' && nxt === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue }
    out += c
    i++
  }
  return out
}

/**
 * 取从 `startIdx` 起第一个 `(` 到**匹配** `)` 的整块。
 * ★ 不用「往后截 N 字符」的窗口写法：窗口长度一旦不够，判据会**静默假绿**
 *   （清空语句掉在窗口外 ⇒ 门禁看不见 ⇒ 却报通过）。括号平衡不依赖长度假设。
 */
function balancedBlock(src, startIdx) {
  const i0 = src.indexOf('(', startIdx)
  if (i0 < 0) return ''
  let depth = 0
  for (let i = i0; i < src.length; i++) {
    if (src[i] === '(') depth++
    else if (src[i] === ')') {
      depth--
      if (depth === 0) return src.slice(i0, i + 1)
    }
  }
  return ''
}

/** 统计子串出现次数（用 split 而不是正则，避免特殊字符要转义） */
function countOf(hay, needle) {
  if (!needle) return 0
  return hay.split(needle).length - 1
}

/** 读文件；不存在返回 null（**由 S0 显式判红**，不许在这里抛异常把整个门禁弄崩） */
function readSrcSafe(rel) {
  const p = path.join(SRC_ROOT, rel)
  if (!fs.existsSync(p)) return null
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/**
 * 取从 `fromIdx` 起第一个 `open` 到**匹配** `close` 的整块（含两端）。
 * ★ 与 balancedBlock 的区别：这个能配 [] {} 而不仅是 ()，且**认字符串与模板串**，
 *   否则对象字面量里的 'a]b' 会把深度算飞。
 */
function balancedDelims(src, fromIdx, open, close) {
  const i0 = src.indexOf(open, fromIdx)
  if (i0 < 0) return ''
  let depth = 0
  let quote = null
  for (let i = i0; i < src.length; i++) {
    const c = src[i]
    if (quote) {
      if (c === '\\') { i++; continue }
      if (c === quote) quote = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue }
    if (c === open) depth++
    else if (c === close) {
      depth--
      if (depth === 0) return src.slice(i0, i + 1)
    }
  }
  return ''
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

// ---------------------------------------------------------------- 读盘面

const rawWs = readSrc(WORKSPACE)
const ws = stripComments(rawWs)
const watchBlock = balancedBlock(ws, ws.indexOf(WATCH_ANCHOR))

// 默认工具两张表（S6 / S7 用）—— 读不到就留空，由 S0 显式判红
const rawTd = readSrcSafe(TOOL_DEFS)
const td = rawTd ? stripComments(rawTd) : ''

const atTools = td.indexOf('export const AGENT_TOOLS')
const toolsBody = atTools >= 0 ? balancedDelims(td, atTools, '{', '}') : ''

const atDefaults = td.indexOf('export const AGENT_DEFAULT_TOOL')
const defaultsBody = atDefaults >= 0 ? balancedDelims(td, atDefaults, '{', '}') : ''

/** `AGENT_DEFAULT_TOOL` 的登记项 [agentId, toolId] */
const defaultPairs = [...defaultsBody.matchAll(/'([^']+)'\s*:\s*'([^']+)'/g)]
  .map((m) => [m[1], m[2]])

/** 取某个 Agent 在 AGENT_TOOLS 里的工具 id 列表；没有这个 Agent 返回 null */
function agentToolIds(agentId) {
  for (const key of ["'" + agentId + "'", '"' + agentId + '"', agentId]) {
    const i = toolsBody.indexOf(key + ':')
    if (i < 0) continue
    const arr = balancedDelims(toolsBody, i, '[', ']')
    return [...arr.matchAll(/id:\s*'([^']+)'/g)].map((m) => m[1])
  }
  return null
}

// ---------------------------------------------------------------- 基线自检
// 先证明「读到了、认得出」—— 否则后面所有判据都可能在全空文本上跑成「全绿」

check('S0 基线：Workspace.vue 可读且关键锚点都在（防路径错导致全空跑）', () => {
  assert(rawWs.length > 5000, `Workspace.vue 只有 ${rawWs.length} B —— 路径或扫描根不对（AGENT_SCOPE_SRC_ROOT）`)
  assert(ws.includes('provide('), '剥注释后找不到 provide( —— 剥注释器把代码吃掉了')
  assert(ws.includes(WATCH_ANCHOR), `找不到切 Agent 的 watch 锚点：${WATCH_ANCHOR}`)
  assert(watchBlock.length > 100, `切 Agent 的 watch 块只解析出 ${watchBlock.length} 字符 —— 括号平衡器失效`)
  assert(rawTd !== null,
    `读不到 ${TOOL_DEFS}（扫描根 ${SRC_ROOT}）—— S6/S7 的权威工具表**不可得**。` +
    '★ 拿不到权威清单 ≠ 清单为空：这里必须判红，不许让 S6 在空文本上跑成「通过」')
  assert(toolsBody.length > 200, `AGENT_TOOLS 对象字面量只解析出 ${toolsBody.length} 字符 —— 解析器失效`)
  assert(defaultsBody.length > 20, `AGENT_DEFAULT_TOOL 对象字面量只解析出 ${defaultsBody.length} 字符 —— 解析器失效`)
})

// ---------------------------------------------------------------- S1 唯一真源

check('S1 属主判定只有一份实现：显示与清空读同一个谓词', () => {
  for (const { predicate } of AGENT_SCOPE_REFS) {
    const defs = countOf(ws, `const ${predicate} =`)
    assert(defs === 1, `\`${predicate}\` 在 Workspace.vue 里定义了 ${defs} 次（要求恰好 1）—— 两份实现必然漂移`)
  }
  // 显示的 computed 必须**调用**谓词，不能自己再写一遍字面量
  const showPairs = [
    ['showProductLoader', 'isProductLoaderAgent'],
    ['showCandidateLoader', 'isCandidateLoaderAgent'],
  ]
  for (const [showName, predicate] of showPairs) {
    const i = ws.indexOf(`const ${showName} = computed(`)
    assert(i >= 0, `没找到 \`const ${showName} = computed(\``)
    const body = ws.slice(i, i + 200)
    assert(body.includes(`${predicate}(`),
      `\`${showName}\` 里没有调用 \`${predicate}(...) \`—— 它自己又写了一遍 agent id 判定（第二份实现）`)
  }
})

// ---------------------------------------------------------------- S2 成对清空

check('S2 切 Agent 时成对清空：每个 Agent 级 ref 都由**自己的**谓词守护', () => {
  assert(watchBlock, '切 Agent 的 watch 块为空 —— 无法判定清空（不许当成通过）')
  for (const { ref, predicate, why } of AGENT_SCOPE_REFS) {
    const clear = `${ref}.value = null`
    assert(watchBlock.includes(clear),
      `切 Agent 的 watch 里没有 \`${clear}\` —— 该 ref 会跨 Agent 残留。${why}`)
    assert(watchBlock.includes(`!${predicate}(`),
      `\`${clear}\` 没有被属主判定守护（缺 \`!${predicate}(\`）—— 会把同属主的两个 Agent 之间也清掉`)
  }
})

check('S3 清空判据不得回退成裸的 agent id 字面量', () => {
  const bare = ["!== 'product-research'", "!== 'listing-generator'", "!== 'aigc-media'", "!== 'customer-service'"]
  for (const b of bare) {
    assert(!watchBlock.includes(b),
      `切 Agent 的 watch 里又出现了裸字面量 \`${b}\` —— 属主判定必须走 S1 的谓词（唯一真源）`)
  }
})

// ---------------------------------------------------------------- S3 登记表完整

check('S4 新增 Agent 级上下文必须登记（按 `working*` 命名约定自动发现）', () => {
  // 名字形如 workingXxx 的 provide 键 = Agent 级共享上下文（排除 set/clear 动词前缀）
  const provided = [...ws.matchAll(/provide\(\s*'([A-Za-z]+)'/g)].map((m) => m[1])
  const discovered = provided.filter((k) => /^working[A-Z]/.test(k))
  const registered = AGENT_SCOPE_REFS.map((x) => {
    // currentWorkingProduct ←→ provide 键 workingProduct
    const m = x.ref.match(/^current([A-Z].*)$/)
    return m ? m[1][0].toLowerCase() + m[1].slice(1) : x.ref
  })
  for (const key of discovered) {
    assert(registered.includes(key),
      `provide('${key}') 看起来是 Agent 级共享上下文，但没登记进 AGENT_SCOPE_REFS —— ` +
      '它会**没有任何清空策略**地跨 Agent 残留。请在清单里登记并补上守护谓词。')
  }
  for (const key of registered) {
    assert(discovered.includes(key),
      `AGENT_SCOPE_REFS 登记了 \`${key}\`，但 Workspace.vue 里没有 \`provide('${key}')\` —— 登记表过期了`)
  }
})

// ---------------------------------------------------------------- 自检（反向）

check('S5 自检（反向）：清空语句被注释掉后必须判不出来', () => {
  const fake = stripComments(
    "// currentWorkingProduct.value = null\n/* if (!isProductLoaderAgent(nextAgentId)) { } */")
  assert(!fake.includes('currentWorkingProduct.value = null'),
    '剥注释没生效 —— 注释里的清空语句会让 S2 假绿（这才是最危险的假绿）')
  const real = stripComments(
    'if (!isProductLoaderAgent(nextAgentId)) {\n  currentWorkingProduct.value = null\n}')
  assert(real.includes('currentWorkingProduct.value = null') && real.includes('!isProductLoaderAgent('),
    '真代码里的清空+守护没被认出来 —— S2 会假红')
})

// ---------------------------------------------------------------- S6 默认工具登记表

check('S6 默认工具登记表：登记的 toolId 必须真实存在于该 Agent 的工具表里', () => {
  const defs = countOf(td, 'export const AGENT_DEFAULT_TOOL')
  assert(defs === 1,
    `AGENT_DEFAULT_TOOL 在 ${TOOL_DEFS} 里定义了 ${defs} 次（要求恰好 1）—— 两张表必然漂移`)
  assert(defaultPairs.length >= 1,
    'AGENT_DEFAULT_TOOL 一条都没解析出来 —— 要么表空了（那「点 Agent 默认选工具」是死代码），' +
    '要么解析锚点没跟上新写法')
  for (const [agentId, toolId] of defaultPairs) {
    const ids = agentToolIds(agentId)
    assert(ids !== null,
      `AGENT_DEFAULT_TOOL 登记了 agent \`${agentId}\`，但 AGENT_TOOLS 里没有这个 Agent —— 死登记`)
    assert(ids.includes(toolId),
      `AGENT_DEFAULT_TOOL['${agentId}'] = '${toolId}'，但该 Agent 的工具表里没有这个 id\n` +
      `        现有：${ids.join(' / ') || '(空)'}\n` +
      '        ⇒ 这是一条**永远不会生效**的登记：resolveDefaultTool 会 fail-closed 成 null，' +
      '右栏静默落回空态，而没人知道为什么「说好的默认选中」没出现')
  }
})

// ---------------------------------------------------------------- S7 默认工具走规格表

check('S7 默认工具必须走规格表：watch 调 resolveDefaultTool，且不得写死 agent / 取数组第一个', () => {
  assert(watchBlock.includes('resolveDefaultTool('),
    '切 Agent 的 watch 里没有调用 `resolveDefaultTool(...)` —— 默认工具判定离开了唯一真源 ' +
    '(AGENT_DEFAULT_TOOL)，退化成散落的 if 分支')
  assert(!/getAgentTools\s*\([^)]*\)\s*\[\s*0\s*\]/.test(watchBlock),
    '切 Agent 的 watch 里出现「取工具数组第一个」⇒ 默认工具被**数组顺序**决定：' +
    '哪天有人在列表中间插一个工具，默认选中就静默变了，而且没人看得出来')
  for (const a of ['aigc-media', 'product-research', 'listing-generator', 'competitor-intel',
                   'ad-analysis', 'customer-service', 'review-analyst', 'secretary']) {
    assert(!watchBlock.includes(`=== '${a}'`),
      `切 Agent 的 watch 里又出现裸 agent 字面量 \`=== '${a}'\` —— ` +
      '默认工具必须走 AGENT_DEFAULT_TOOL 规格表（唯一真源）')
  }
  assert(!/export const AGENT_DEFAULT_TOOL/.test(ws),
    'Workspace.vue 里又定义了一份 AGENT_DEFAULT_TOOL ⇒ 与 toolDefinitions.ts 的两张表必然漂移')
})

// ---------------------------------------------------------------- 盘面 / 汇总

if (REPORT_ONLY) {
  console.log(`扫描根：${SRC_ROOT}`)
  console.log(`Workspace.vue：${rawWs.length} B / 剥注释后 ${ws.length} B`)
  console.log(`切 Agent watch 块：${watchBlock.length} B`)
  console.log(`已登记 Agent 级上下文：${AGENT_SCOPE_REFS.length} 个 —— ${AGENT_SCOPE_REFS.map((x) => x.ref).join(' / ')}`)
  console.log(`默认工具规格表：${defaultPairs.length} 条 —— ${defaultPairs.map((p) => p[0] + '→' + p[1]).join(' / ')}`)
}

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
console.log('Agent 级共享上下文生命周期成立（属主判定唯一真源 · 切 Agent 成对清空 · 新上下文必须登记 ✓）')

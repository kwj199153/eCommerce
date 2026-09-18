#!/usr/bin/env node
/**
 * HITL 审批闭环契约门禁（★ 第 131 轮 · item2-C）
 *
 * 为什么值得单独一个门禁 —— 这一块在本轮之前是**全仓最危险的一段代码**：
 *   `ChatPanel/index.vue` 有一张「需要人工审批」的卡，`stores/chat.ts` 有两个
 *   承载字段（`hitlRequired` / `hitlToolName`），`useChatOrchestrator.ts` 有两个
 *   handler。**三个文件都在，看起来整条链子都在**。实际是：
 *     · `hitlRequired` / `hitlToolName` 全仓**0 个写入点** ⇒ 那张卡**永远不显示**；
 *     · `handleHitlAccept` 只弹一句 `message.success('已批准执行')`，
 *       **不发任何请求** ⇒ 用户以为批了，后端从未收到，操作从未执行。
 *   这是「接线了但没渲染」+「假成功提示」的叠加，且**零报错、零测试红**。
 *   （同一族缺陷本项目已实测 3 次，见 `check-tool-adapters.cjs` 头注释。）
 *
 * ⇒ 本门禁要能对下面每一维度「说不」：
 *   A 链路完整性：api 出口 → 编排模块真调用它 → 卡片登记 → 四档决策齐全
 *   B 死桩不得复活：旧字段 / 旧 class / 旧 handler 全仓归零
 *   C 诚实性：缺会话 ID 时不发请求；请求失败必须回写界面
 *   D 契约对齐：字段名 snake_case、decision 四档与**后端 Literal** 一致
 *   E 门禁自身挂进 `npm run build`（否则它是死脚本，本项目已 1 个先例）
 *
 * ★ 本文件里所有「查某符号在不在」的断言都走 `stripComments()` 之后的源码。
 *   起因是本门禁第一次跑就踩了这个坑：审批卡的注释里写着「刻意不使用 thread_id」，
 *   裸文本断言当场把**这句注释**当成了违规用法。源码字符串包含式判据在
 *   本项目已被证伪 3 次（docstring / 注释逐字引用被禁的那行代码）——
 *   形态判据要么走 AST，要么先把注释剥掉。
 *
 * 怎么跑：node scripts/check-hitl-approval.cjs
 *
 * 反向注入（证明本门禁不是空跑）：
 *   HITL_SRC_DIR=<src 副本> HITL_<X>_SRC=<改坏的副本> node scripts/check-hitl-approval.cjs
 *   允许覆盖的变量见下面 ENV 表。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const SRC_DIR = process.env.HITL_SRC_DIR
  ? path.resolve(process.env.HITL_SRC_DIR)
  : path.join(ROOT, 'src')

/**
 * 覆盖口。[环境变量, 默认路径, 是否锚在仓库外(不受 HITL_SRC_DIR 影响)]
 * 后端 schemas 与 package.json 在 `src/` 之外 ⇒ 必须锚住，否则反向注入
 * 把 SRC_DIR 指向副本时会连带找不到它们（本门禁第一次跑就是这么红的）。
 */
const ENV = {
  api: ['HITL_API_SRC', 'api/productResearch.ts', false],
  flow: ['HITL_FLOW_SRC', 'composables/useApprovalFlow.ts', false],
  registry: ['HITL_REGISTRY_SRC', 'components/ChatPanel/results/conversation/registry.ts', false],
  card: ['HITL_CARD_SRC', 'components/ChatPanel/results/conversation/PendingApprovalCard.vue', false],
  schemas: ['HITL_SCHEMAS_SRC', path.join('..', 'backend', 'modules', 'product_research', 'schemas.py'), true],
  pkg: ['HITL_PKG_SRC', 'package.json', true],
}

function pick(key) {
  const [envName, rel, anchored] = ENV[key]
  if (process.env[envName]) return path.resolve(process.env[envName])
  return anchored ? path.join(ROOT, rel) : path.join(SRC_DIR, rel)
}
function read(p) {
  if (!fs.existsSync(p)) throw new Error('文件不存在：' + p)
  return fs.readFileSync(p, 'utf8')
}

/**
 * 剥掉 `//` `/* *\/` 注释（保留字符串字面量原样 + 保留换行）。
 *
 * 不引依赖：一个简单的字符状态机，够用且零风险。
 */
function stripComments(code) {
  let out = ''
  let i = 0
  const n = code.length
  let state = null // 'line' | 'block' | 'sq' | 'dq' | 'tpl'
  while (i < n) {
    const c = code[i]
    const d = code[i + 1]
    if (state === null) {
      if (c === '/' && d === '/') { state = 'line'; i += 2; continue }
      if (c === '/' && d === '*') { state = 'block'; i += 2; continue }
      // HTML 注释（.vue 模板里大量使用）—— **少了这一支，模板注释会被当成代码**。
      // 本门禁第一次发布就是这么误报的：审批卡的模板注释里写着
      // 「刻意不显示 / 不使用 thread_id」，E2 当场把它判成违规用法。
      if (c === '<' && code.startsWith('<!--', i)) { state = 'html'; i += 4; continue }
      if (c === "'") { state = 'sq'; out += c; i += 1; continue }
      if (c === '"') { state = 'dq'; out += c; i += 1; continue }
      if (c === '`') { state = 'tpl'; out += c; i += 1; continue }
      out += c; i += 1; continue
    }
    if (state === 'line') {
      if (c === '\n') { state = null; out += c }
      i += 1; continue
    }
    if (state === 'block') {
      if (c === '*' && d === '/') { state = null; i += 2 }
      else { if (c === '\n') out += c; i += 1 }
      continue
    }
    if (state === 'html') {
      if (c === '-' && code.startsWith('-->', i)) { state = null; i += 3 }
      else { if (c === '\n') out += c; i += 1 }
      continue
    }
    // 字符串里：整体照抄，遇转义跳过下一个字符
    if (c === '\\') { out += c + (d === undefined ? '' : d); i += 2; continue }
    out += c; i += 1
    if ((state === 'sq' && c === "'") || (state === 'dq' && c === '"') || (state === 'tpl' && c === '`')) {
      state = null
    }
  }
  return out
}
/** 读源码并剥注释 —— 本文件所有「符号在不在」的断言都走它 */
function readCode(p) {
  return stripComments(read(p))
}

const results = []
function check(name, fn) {
  try {
    fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

// ==================== A. 链路完整性 ====================

check('A1 api 层导出 resumeApproval，且打到 /product-research/approval/resume', () => {
  const s = readCode(pick('api'))
  assert(/export\s+function\s+resumeApproval\s*\(/.test(s), '缺 export function resumeApproval')
  assert(s.includes("request.post('/product-research/approval/resume'"),
    '未 POST 到 /product-research/approval/resume')
})

check('A2 编排模块真的调用 resumeApproval（不是自己拼 URL / 不是只弹提示）', () => {
  const s = readCode(pick('flow'))
  assert(/import\s*\{[^}]*\bresumeApproval\b[^}]*\}\s*from\s*'@\/api\/productResearch'/.test(s),
    'useApprovalFlow 未从 @/api/productResearch 导入 resumeApproval')
  assert(/await\s+resumeApproval\s*\(/.test(s), 'useApprovalFlow 未调用 resumeApproval')
  assert(!/request\.post\(/.test(s), '编排模块不该自己发 axios 请求（应复用 api 层出口）')
})

check('A3 registry 登记了 pending_approval → 组件', () => {
  const s = readCode(pick('registry'))
  const m = s.match(/CONVERSATION_RESULT_COMPONENTS[\s\S]*?=\s*\{([\s\S]*?)\n\}/)
  assert(m, '未找到 CONVERSATION_RESULT_COMPONENTS 定义')
  assert(/pending_approval\s*:/.test(m[1]),
    'registry 未登记 pending_approval ⇒ 后端下发的审批请求**渲染不出来**')
  assert(/import\s+PendingApprovalCard\s+from/.test(s), '未导入 PendingApprovalCard')
})

check('A4 审批卡四档决策齐全（accept / reject / edit / response）', () => {
  const s = readCode(pick('card'))
  for (const d of ['accept', 'reject', 'edit', 'response']) {
    assert(s.includes(`decide('${d}')`), `审批卡缺 decision=${d} 的入口（后端四档之一不可达）`)
  }
  assert(s.includes('DECIDED_TEXT'), '缺终态文案映射')
})

check('A5 流式降级到非流式时也必须回填 display_type/data（否则审批卡在降级路径上不可达）', () => {
  // 起因：`/chat/stream` 失败时降级到 `/chat`，原实现只 `appendToLastMessage(reply)`，
  // 把 display_type / data 直接丢掉 ⇒ 用户在降级路径上会读到后端那句
  // 「请选择『批准』或『拒绝』」却**没有任何按钮可点** —— 一句无法执行的指令。
  // （路径直接用 SRC_DIR 拼，反向注入时自动跟着副本走。）
  const p = path.join(SRC_DIR, 'composables', 'useChatOrchestrator.ts')
  assert(fs.existsSync(p), '未找到 composables/useChatOrchestrator.ts')
  const s = readCode(p)
  const i = s.indexOf('chatWithProductResearcher({')
  assert(i >= 0, '未找到 chatWithProductResearcher 调用点')
  const seg = s.slice(i, i + 700)
  assert(/setLastMessageResult/.test(seg),
    '选品对话的降级兜底没有回填 display_type/data ⇒ 审批卡在流式失败时渲染不出来')
})

// ==================== B. 死桩不得复活 ====================

const DEAD_SYMBOLS = ['hitlRequired', 'hitlToolName', 'hitl-card', 'handleHitlAccept', 'handleHitlReject']

function walkSrc(cb) {
  const walk = (dir) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) {
        if (['node_modules', 'dist', '.git'].includes(e.name)) continue
        walk(p)
      } else if (/\.(ts|vue|js)$/.test(e.name)) {
        cb(p, readCode(p))
      }
    }
  }
  walk(SRC_DIR)
}

check('B1 全 src 不得再出现旧死桩符号（剥注释后 0 命中）', () => {
  const hits = {}
  walkSrc((p, t) => {
    for (const d of DEAD_SYMBOLS) {
      if (t.includes(d)) (hits[d] = hits[d] || []).push(path.relative(SRC_DIR, p))
    }
  })
  const bad = Object.entries(hits).map(([k, v]) => `${k}@${v.join(',')}`)
  assert(bad.length === 0,
    `死桩复活：${bad.join(' | ')}。` +
    '这些符号以前是「看起来接好了、实际永不生效」的那套壳 —— 别再写回来。')
})

check('B2 不得存在「只弹提示、不发请求」的审批 handler（假成功提示）', () => {
  const found = []
  walkSrc((p, t) => {
    // 形态：文件里出现「已批准执行 / 已拒绝执行」这类**结论文案**（字符串字面量），
    //       但既没有自己的审批请求出口，也没有把动作交给带出口的编排模块。
    const claims = /已批准执行|已拒绝执行/.test(t)
    const hasExit = /resumeApproval|approval\/resume|submitApprovalDecision|useApprovalFlow/.test(t)
    if (claims && !hasExit) found.push(path.relative(SRC_DIR, p))
  })
  assert(found.length === 0,
    `以下文件自称「已批准/已拒绝」却没有任何审批请求出口：${found.join(', ')}`)
})

// ==================== C. 诚实性 ====================

check('C1 缺会话 ID 时必须在调用 resumeApproval 之前就返回（不发请求）', () => {
  const s = readCode(pick('flow'))
  const guard = s.indexOf('if (!sessionId)')
  const call = s.indexOf('resumeApproval({')
  assert(guard >= 0, '缺 `if (!sessionId)` 前置守卫 ⇒ 无会话 ID 也会发请求，失败原因会被归到别处')
  assert(call >= 0, '未找到 resumeApproval 调用')
  assert(guard < call,
    '前置守卫出现在调用**之后** ⇒ 等于没有守卫（发完请求才发现没会话 ID）')
})

check('C2 resumeApproval 调用必须被 try 包住，且 catch 里必须回写对话', () => {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const file = pick('flow')
  const sf = ts.createSourceFile(file, read(file), ts.ScriptTarget.ES2019, true)

  const calls = []
  const walk = (node, stack) => {
    if (ts.isCallExpression(node)) {
      if (node.expression.getText(sf) === 'resumeApproval') calls.push({ node, stack: stack.slice() })
    }
    const next = stack.concat(node)
    node.forEachChild((c) => walk(c, next))
  }
  walk(sf, [])

  assert(calls.length > 0, 'AST 未找到 resumeApproval 调用（文本断言之外的第二道口径也对不上）')

  for (const c of calls) {
    const tryNode = c.stack.filter((n) => ts.isTryStatement(n)).pop()
    assert(tryNode, 'resumeApproval 调用不在 try 块里 ⇒ 请求失败会把异常抛穿整个 UI')
    // catch / finally 段里的调用不算「被保护」
    const inRecovery = c.stack.some(
      (n) => ts.isCatchClause(n) || n.kind === ts.SyntaxKind.FinallyBlock
    )
    assert(!inRecovery, 'resumeApproval 出现在 catch/finally 段内，不是受保护的正常路径')
    const cc = tryNode.catchClause
    assert(cc && cc.block && cc.block.getText(sf).includes('addMessage'),
      'catch 段没有 addMessage ⇒ 请求失败只弹 toast，卡片会停在「已批准」的假象上')
  }
})

// ==================== D. 契约对齐 ====================

check('D1 请求体字段名是 snake_case `context_id`（不得写成 contextId）', () => {
  const s = readCode(pick('flow'))
  assert(s.includes('context_id:'), 'useApprovalFlow 未传 context_id')
  assert(!/\bcontextId\b/.test(s),
    '出现了 contextId ⇒ Pydantic 会丢掉这个字段 ⇒ 必填缺失 ⇒ 稳定 422（本项目已踩过一次）')
})

check('D2 四档 decision 与后端 ApprovalResumeRequest 的 Literal 逐字一致', () => {
  const be = read(pick('schemas'))
  const m = be.match(/decision\s*:\s*Literal\[([^\]]*)\]/)
  assert(m, '未能在后端 schemas 里找到 decision 的 Literal 声明')
  const beVals = m[1].split(',').map((x) => x.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean).sort()

  const fe = readCode(pick('api'))
  const fm = fe.match(/decision\s*:[^\n]*/)
  assert(fm, '未能从前端 api 里找到 decision 的类型声明')
  const feVals = (fm[0].match(/'(accept|reject|edit|response)'/g) || [])
    .map((x) => x.replace(/'/g, '')).sort()

  assert(beVals.join('|') === feVals.join('|'),
    `前后端 decision 档位不一致：后端=[${beVals}] 前端=[${feVals}]`)
  assert(beVals.length === 4, `后端 decision 应有 4 档，实际 ${beVals.length}`)
})

check('D3 审批卡消费的字段名与后端下发的 data 结构一致', () => {
  const card = readCode(pick('card'))
  for (const k of ['approval', 'session_id', 'action', 'args']) {
    assert(card.includes(k),
      `审批卡未消费 \`${k}\` ⇒ 后端 _pending_approval_from_interrupt() 下发的结构用不上`)
  }
})

// ==================== E. 门禁自身挂载 ====================

check('E1 本门禁已挂进 `npm run build`（否则它只是死脚本）', () => {
  const pkg = JSON.parse(read(pick('pkg')))
  const build = pkg.scripts?.build || ''
  assert(build.includes('check-hitl-approval.cjs'),
    'build 未包含 check-hitl-approval.cjs ⇒ 门禁不会在任何 CI / 构建里执行')
  assert(!!pkg.scripts?.['check:hitl-approval'], '缺 npm script `check:hitl-approval`（无法单独复跑）')
})

check('E2 审批卡不得引用 thread_id（归属只能服务端注入）', () => {
  const card = readCode(pick('card'))
  assert(!/\bthread_id\b/.test(card),
    '审批卡的**代码**里引用了 thread_id —— thread_id 里含 user_id，' +
    '交给客户端等于把「谁的操作能被恢复」交给请求方')
})

// ==================== 输出 ====================
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\nHITL 审批闭环门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log('HITL 审批闭环门禁通过（api → 编排 → 卡片 → 四档 → 后端契约 ✓）')

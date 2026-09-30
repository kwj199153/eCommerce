#!/usr/bin/env node
/**
 * 差评处置「**写动作出口唯一**」门禁（第 291 轮）
 *
 * ============================================================================
 * ★ 为什么需要它
 * ============================================================================
 * 第 290 轮盘出来的真缺陷：`approve` / `reject` / `issue` 这三个**不可逆的
 * 人审动作**同时有两个 UI 出口 —— 资料库的 `DispositionLibrary.vue` 和客服
 * 功能栏的 `ReviewDeskConfig.vue` 各挂一排按钮。
 * 后果不是「重复劳动」而是 **HITL 的唯一把关点失效**：任何一个 UI 出口里的
 * 校验被绕过都无人察觉，而券码 / 退款一旦发出即既成事实。
 *
 * 判据选的是「**被多少个 .vue import**」而不是「界面上看有没有重复按钮」：
 *   · 后者要靠人眼，改一轮就失效；
 *   · 前者是可执行的形态判据 —— 想再加第二个面板，必先点这个文件左下钉着的三行。
 *
 * ============================================================================
 * ★ 为什么必须剥注释 + 用 AST 式提取，而不是 `grep 源码字符串`
 * ============================================================================
 * 本仓铁律：源码字符串包含会被注释喂饱。典型假绿 —— 在某个 .vue 的注释里写
 * 「这里不要调 approveDisposition」，字符串判据照样命中，**判据被它自己的
 * 注释 satisfying**。这里统一走 `code()`（剥 HTML/块/行注释）后再取 import 花括号。
 *
 * ★ 并且配了 B0 级自检（证明解析没落空）：三个函数必须**至少各被 import 过一次**。
 *   否则「0 处 == 0 处」的空集恒真会让这条门禁变成装饰 —— 那是本仓踩过的最贵的一类坑。
 */

const fs = require('fs')
const path = require('path')

const SRC = process.env.WRITE_EXIT_SRC_ROOT || path.join(__dirname, '..', 'src')
const OWNER = 'components/TaskConfigPanel/configs/ReviewDeskConfig.vue'
const GONE = 'components/KnowledgeBase/DispositionLibrary.vue'
const WRITES = [
  'approveDisposition',
  'rejectDisposition',
  'issueDisposition',
  // ★ 第 304 轮：登记平台执行回执也是**人**的终态动作
  //   （`issued` → `executed`，不可逆）。它同样只能有一个 UI 出口 ——
  //   两个出口里的校验被绕过都无人察觉，而「平台上已经执行」是可追责断言。
  'recordExecutionReceipt',
  // ★ 第 304 轮后半：补归因 + 规则 CRUD 是「差评处置」域新增的**写**动作。
  //   · setReviewAttribution —— 把 unknown 差评手工标成因（落 manual，进处置链）；
  //   · create/update/deleteCompensationRule —— 配置补偿规则（金额唯一真源）。
  //   它们与上面的批准/核准同属「人操作、写库」这一族 ⇒ 同样只许一个 UI 出口，
  //   否则「补归因」或「配规则」又会像当年 approve 那样长出第二个面板、
  //   而第二个面板里的归属校验被绕过无人察觉。
  'setReviewAttribution',
  'createCompensationRule',
  'updateCompensationRule',
  'deleteCompensationRule',
]

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

/** 剥三类注释得到「只有代码」的文本（见文件头 ★）。 */
function code(t) {
  return String(t || '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
}

/** 递归收集某后缀的文件（相对 SRC 的 posix 路径）。 */
function walk(dir, ext, acc = []) {
  if (!fs.existsSync(dir)) return acc
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, ext, acc)
    else if (e.name.endsWith(ext)) acc.push(p)
  }
  return acc
}

/**
 * 抽 `import { ... } from '...'` 花括号里的名字（**代码形态**，不是子串）。
 *
 * ★ 第 304 轮后半修一个正则脆弱点：旧实现用 `import\s+...\{([\s\S]*?)\}`，
 *   `[\s\S]*?` 会**跨 import 吞并** —— 从文件里第一个 `import {` 一路吃到
 *   第一个 `from '...api/trade'`，把中间所有 import 的正文都装进捕获组，
 *   于是「反向注入到文件末尾的第二出口」被 `split(',')` 拆成带换行前缀的
 *   脏字符串，`Set.has(name)` 恒 false ⇒ 门禁假绿（第二出口根本测不出来）。
 *
 * ★ 修法：先把正文按 `import` 语句**切块**（以 `from '...'` 为界、限定在
 *   同一条语句内，用 `[^;]` 而非 `[\s\S]` 挡住跨语句），再在每条命中
 *   `from '...<moduleHint>'` 的语句里、取 `{` 到 `}` 之间**不含 `}`** 的
 *   名字（`[^}]*` 挡住再往后吞）。这样每个名字都被干净拆出。
 */
function importedNamesFrom(srcBody, moduleHint) {
  const names = new Set()
  // 一条 import 语句：从 `import` 到 `from '...moduleHint'`（同一语句内，
  // 不含分号；`[^;]` 保证不跨到下一句 —— 本仓 import 一律单语句无分号内嵌）。
  const stmtRe = new RegExp(
    "import\\s+(?:type\\s+)?\\{([^;]*?)\\}\\s*from\\s*['\"][^'\"]*" + moduleHint + "['\"]",
    'g'
  )
  let m
  while ((m = stmtRe.exec(srcBody)) !== null) {
    for (const raw of m[1].split(',')) {
      const n = raw.trim().replace(/^type\s+/, '')
      if (n) names.add(n)
    }
  }
  return names
}

const vues = walk(SRC, '.vue')
const tses = walk(SRC, '.ts')

const vueOwners = {}
const tsOwners = {}
for (const name of WRITES) {
  vueOwners[name] = []
  tsOwners[name] = []
}
for (const f of vues) {
  const body = code(fs.readFileSync(f, 'utf8'))
  const names = importedNamesFrom(body, 'api/trade')
  for (const w of WRITES) if (names.has(w)) vueOwners[w].push(path.relative(SRC, f).split(path.sep).join('/'))
}
for (const f of tses) {
  const body = code(fs.readFileSync(f, 'utf8'))
  const names = importedNamesFrom(body, 'api/trade')
  for (const w of WRITES) if (names.has(w)) tsOwners[w].push(path.relative(SRC, f).split(path.sep).join('/'))
}

// ============================================================ B 自检：证明没空跑
check(vues.length > 50, 'B0 扫描到的 .vue 数量合理（>50）', `实际 ${vues.length} —— 扫不到 ⇒ 后面全是空集恒真`)
for (const w of WRITES) {
  check(
    vueOwners[w].length >= 1,
    `B1 ${w} 至少被一个 .vue import（证明解析没落空）`,
    `实际 ${JSON.stringify(vueOwners[w])} —— 0 处说明 import 提取器失配，不是"好消息"`
  )
}

// ============================================================ C 核心判据
for (const w of WRITES) {
  check(
    vueOwners[w].length === 1 && vueOwners[w][0] === OWNER,
    `C1 ${w} 的 UI 出口 == 1（且只在 ${OWNER}）`,
    `实际 ${vueOwners[w].length} 处 ${JSON.stringify(vueOwners[w])}`
  )
  check(
    tsOwners[w].length === 0,
    `C2 ${w} 没有 .ts 层再包一层（UI 之外无第二个调用面）`,
    `实际 ${JSON.stringify(tsOwners[w])} —— 多一层包装 ⇒ 又一处可能漏 HITL 的入口`
  )
}

// ============================================================ D 旧出口已消失
check(
  !fs.existsSync(path.join(SRC, GONE)),
  `D1 旧的资料库页面已删除（${GONE}）`,
  '文件还在 ⇒ 说明有过一条删除没落实，或被人加回来了'
)
const ws = fs.readFileSync(path.join(SRC, 'views', 'Workspace.vue'), 'utf8')
check(
  !/currentView === 'dispositions'/.test(code(ws)),
  "D2 Workspace 里没有 currentView === 'dispositions' 的渲染分支",
  '分支还在 ⇒ 菜单/跳转指向一个不存在的视图'
)
const actions = fs.readFileSync(path.join(SRC, 'utils', 'appActions.ts'), 'utf8')
check(
  !/AppView[\s\S]*'dispositions'/.test(actions) && !/'dispositions'/.test(code(actions)),
  "D3 appActions 的 AppView 里没有 'dispositions'",
  '留着 ⇒ AI 动作能跳到一个已删除的视图，界面不动却回「已打开」'
)

// ============================================================ 报告
const bad = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.label}`)
  if (!r.ok && r.detail) console.log(`        ↳ ${r.detail}`)
}
console.log('')
if (bad.length) {
  console.log(`差评写动作出口门禁失败：${bad.length} / ${results.length}`)
  process.exit(1)
}
console.log(`差评写动作出口门禁通过（${results.length} 条形态断言 ✓）`)

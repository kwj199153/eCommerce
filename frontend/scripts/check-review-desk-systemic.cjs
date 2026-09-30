#!/usr/bin/env node
/**
 * 差评面板 ↔ 后端判定链路门禁（★ 第 294 轮 B 档）
 *
 * 它保护什么
 * ==========
 * 本轮把「这条差评是个案还是系统性问题」从**只有对话通道能算**搬进了面板：
 *   · 后端新增两个读端点：`GET /trade/reviews/{id}/systemic-check`、`GET /trade/skus/{sku}/health`；
 *   · 前端抽屉新增「🔎 个案 / 系统性判定」区块（含「采纳：勾选升级通道」）。
 * 这条链路横跨两端，任何一半单独改动都会**静默失效**：
 *   · 后端改路径、前端不改 ⇒ 前端 404，而 404 会被 catch 成「判定失败」，
 *     看起来像后端偶发故障，不像路径写错；
 *   · 前端自己算 verdict ⇒ 界面上有结论、后端也有结论，两者不一致时**没人报错**
 *     （本仓铁律：同一可见性两份实现 ⇒ 至少一份永远测不到）。
 *
 * 判据组
 * ======
 *   S1 跨端路径对账：api 层两个函数请求的（方法 + 路径）必须与后端 `router.py`
 *      里登记的一致（占位符段归一成 `{}` 再比，不钉死参数名）
 *   S2 面板**确实在用**这两个函数（import 之外还有调用点）——
 *      「后端有端点」≠「前端在用」（本仓反复踩过）
 *   S3 面板**不得自己推算**判定：不出现 `verdict === / == / in` 这类比较
 *   S4 阈值**不得写死**在界面：必须用 `systemic.threshold`（唯一真源在后端常量）
 *   S5 结论文案取自后端：必须出现 `systemic.verdict_label`
 *   S6 反向自检：把一条**错的**路径喂给比对器必须报错（证明 S1 不是恒真）
 *   S7 防空跑：三个源文件都必须真的读到内容
 *
 * 可注入（供反向验证用，不设则走真实路径）
 * ======================================
 *   SYSTEMIC_API_FILE / SYSTEMIC_PANEL_FILE / SYSTEMIC_ROUTER_FILE
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const API_FILE = process.env.SYSTEMIC_API_FILE || path.join(ROOT, 'src', 'api', 'trade.ts')
const PANEL_FILE = process.env.SYSTEMIC_PANEL_FILE
  || path.join(ROOT, 'src', 'components', 'TaskConfigPanel', 'configs', 'ReviewDeskConfig.vue')
const ROUTER_FILE = process.env.SYSTEMIC_ROUTER_FILE
  || path.join(ROOT, '..', 'backend', 'modules', 'trade', 'router.py')

const PREFIX = '/api/v1/trade'

/** 前端 api 里被登记的两个函数 */
const WANTED = ['getReviewSystemicCheck', 'getSkuHealth']

const read = (p) => {
  if (!fs.existsSync(p)) throw new Error(`文件不存在：${p}`)
  return fs.readFileSync(p, 'utf8')
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

/**
 * 归一成「相对 prefix」的形态 ⇒ 只比「方法 + 段序 + 字面段」。
 *
 * ★ 为什么要剥前缀而不是补前缀（本门禁第一版就栽在这里）：前端 api 写的是
 *   `/trade/reviews/...`、后端 `router.py` 写的是 `/reviews/...`，两者都是
 *   **相对** `/api/v1/trade` 的。给它们补前缀会得到 `/api/v1/trade/trade/...`
 *   ⇒ 正确路径反而判不出（假红）。
 */
function normPath(p) {
  let s = String(p).replace(/\$\{[^}]*\}/g, '{}').replace(/\{[^}]*\}/g, '{}')
  s = s.replace(/^\/api\/v1\/trade/, '').replace(/^\/trade/, '')
  return s.startsWith('/') ? s : '/' + s
}

/** 从 api 文件里取某导出函数真正请求的 (方法, 路径模板) */
function apiCall(src, fnName) {
  const re = new RegExp(
    `export\\s+async\\s+function\\s+${fnName}\\s*\\([^)]*\\)[^{]*\\{([\\s\\S]*?)\\n\\}`,
  )
  const m = src.match(re)
  assert(m, `未在 api 文件里找到函数 ${fnName}（判据会空跑）`)
  const call = m[1].match(
    /request\s*\.\s*(get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*([`'"])([\s\S]*?)\2/,
  )
  assert(call, `${fnName} 函数体里没找到 request.<verb>(...)`)
  return { method: call[1].toUpperCase(), path: call[3].trim() }
}

/** 后端 `@router.<verb>("<path>")` 全表 */
function routerEntries(src) {
  const out = []
  const re = /@router\.(get|post|put|patch|delete)\(\s*(['"])([^'"]+)\2/g
  let m
  while ((m = re.exec(src))) out.push({ method: m[1].toUpperCase(), path: m[3] })
  return out
}

const apiSrc = read(API_FILE)
const panelSrc = read(PANEL_FILE)
const routerSrc = read(ROUTER_FILE)

/**
 * 剥掉 TS/Vue 里的注释 —— 判据不许被注释骗过。
 *
 * ★ 这条是反向注入逼出来的（I3）：把 `await getSkuHealth(sku)` 注释掉之后，
 *   S2 仍然数到它（计数的是**文本出现**）⇒ 判据判不出来。本仓铁律：
 *   源码字符串判据会被注释 / docstring 骗过，必须先剥注释再判。
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:\\])\/\/[^\n]*/g, '$1')
}
const panelCode = stripComments(panelSrc)

// ---------------------------------------------------------------- S7 防空跑
check('S7 三个源文件都读到了内容（防空跑）', () => {
  assert(apiSrc.length > 1000, `api 文件只有 ${apiSrc.length} 字节 ⇒ 读错了文件`)
  assert(panelSrc.length > 5000, `面板文件只有 ${panelSrc.length} 字节 ⇒ 读错了文件`)
  assert(routerSrc.length > 3000, `router 只有 ${routerSrc.length} 字节 ⇒ 读错了文件`)
})

// ---------------------------------------------------------------- S1 跨端路径对账
const bePaths = routerEntries(routerSrc)
const beIndex = new Set(bePaths.map((e) => `${e.method} ${normPath(e.path)}`))

check('S1 api 层请求的路径与后端 router 登记一致', () => {
  assert(beIndex.size > 5, `后端只解析出 ${beIndex.size} 条路由 ⇒ 解析器失明，判据无效`)
  const bad = []
  for (const fn of WANTED) {
    const { method, path: p } = apiCall(apiSrc, fn)
    const key = `${method} ${normPath(p)}`
    if (!beIndex.has(key)) bad.push(`${fn} -> ${key}`)
  }
  assert(!bad.length, `前端请求的端点后端没有：${bad.join(' / ')}`)
})

// ---------------------------------------------------------------- S6 反向自检
check('S6 反向自检：错的路径必须被 S1 判红（证明 S1 非恒真）', () => {
  assert(
    !beIndex.has('GET ' + normPath('/trade/reviews/x/systemic-check-z')),
    'S1 的比对器连错路径都放行 ⇒ 它恒真，等于没守',
  )
  // ★ 这条只验证**归一化函数自己**：不能去查 beIndex（那会让 S6 跟着后端一起红，
  //   与 S1 失去区分度 —— 反向注入 I2 实测出来的）。
  assert(
    normPath('/trade/skus/${encodeURIComponent(sku)}/health')
      === normPath('/skus/{sku}/health'),
    '占位符归一化失效 ⇒ 正确路径反而判不出，S1 是假红',
  )
})

// ---------------------------------------------------------------- S2 面板确实在用
check('S2 面板真的调了这两个 api（不只是 import）', () => {
  // ★ 计数口径：import 行写的是 `getSkuHealth,`（**没有括号**），
  //   所以「`fn(` 出现 ≥1 次」就已经证明存在**调用点**，不是只有 import。
  const bad = WANTED.filter(
    (fn) => (panelCode.match(new RegExp(`${fn}\\s*\\(`, 'g')) || []).length < 1,
  )
  assert(!bad.length, `面板里只有 import、没有调用：${bad.join(' / ')} —— 后端有端点不等于前端在用`)
})

// ---------------------------------------------------------------- S3 不自算判定
check('S3 面板不得自己推算 verdict（组合规则是后端判据）', () => {
  const re = /\bverdict\s*(===|==|!==|!=)/
  assert(!re.test(panelCode), '面板里出现了 verdict 比较 —— 判定口径必须只有后端一份')
})

// ---------------------------------------------------------------- S4 阈值不写死
check('S4 阈值必须取自后端（界面不得写死 3）', () => {
  assert(!/≥\s*3\s*次/.test(panelCode), '面板里写死了阈值「≥3 次」—— 真源是后端 REPEAT_ISSUE_THRESHOLD')
  assert(panelCode.includes('systemic.threshold'), '面板没有使用后端返回的 threshold')
})

// ---------------------------------------------------------------- S5 结论文案取自后端
check('S5 结论文案来自后端 verdict_label', () => {
  assert(panelCode.includes('verdict_label'), '面板没显示 verdict_label ⇒ 结论要么自己命名、要么没显示')
})

// ---------------------------------------------------------------- 输出
let failed = 0
for (const [name, err] of results) {
  if (err) { failed++; console.log(`FAIL  ${name}\n        ${err}`) }
  else console.log(`PASS  ${name}`)
}
console.log(`\n---- ${results.length - failed}/${results.length} 通过 ----`)
if (failed) {
  console.log(
    '判定链路两端必须成对：后端端点 `modules/trade/router.py`（systemic-check / skus/{sku}/health）' +
    '，前端消费点 `api/trade.ts` + `ReviewDeskConfig.vue`。判定口径与阈值只有后端一份。',
  )
  process.exit(1)
}
console.log(`判定链路对账通过：${WANTED.join(' / ')} ⇄ ${PREFIX}`)

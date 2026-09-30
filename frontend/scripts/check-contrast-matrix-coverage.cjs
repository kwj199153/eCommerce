#!/usr/bin/env node
/**
 * 对比度矩阵「覆盖面」对账门禁
 *
 * ============================================================================
 * 为什么值得单独一个门禁
 * ============================================================================
 * `cdp-contrast-matrix.mjs` 把「发现」自动化了 —— 但它自己在源码里带**两份副本**：
 *
 *     const DEFAULT_ROUTES = ['/', '/team', ..., '/verify-email']   ← router/index.ts 的副本
 *     const DEFAULT_THEMES = ['light', 'dark', 'macaron']           ← presets.ts 的副本
 *
 * 任何"清单副本"的失效方式都不是报错，而是**静默变小**：
 *   · 新加一条路由、忘了加进 DEFAULT_ROUTES
 *       ⇒ 那个页面**天然免检**，而门禁照样全绿（连一行提示都没有）
 *   · 加第 4 套主题、忘了加进 DEFAULT_THEMES
 *       ⇒ 新主题一次都没被体检过，同样全绿
 *
 * 这正是本仓反复记过的那个形状：**门禁的失效方式是"变成空集"，不是"报错"**。
 * 所以必须有一条**静态**门禁去对账这三份清单（router / presets / 探针），
 * 它不跑浏览器，因此永远不会因为环境问题而跳过。
 *
 * 本门禁守四条：
 *   ① **router 路由 ⊆ 探针路由清单** —— 新页面不许天然免检 ★★★
 *   ② **探针路由清单 ⊆ router 路由** —— 探针不许留已删路由的陈旧条目
 *       （陈旧条目不会红，它会变成一条**永久"元素不存在"的噪声红**，
 *        而噪声红的下场是整条门禁被关掉）
 *   ③ **presets.ts 的 ThemeName union == 探针主题清单** —— 新主题不许漏检 ★★★
 *   ④ 动态路由（含 `:`）必须显式登记样例地址，否则红 —— 强制一次人工决策
 *
 * 怎么跑：node scripts/check-contrast-matrix-coverage.cjs
 *
 * 反向注入（证明本门禁不是空跑，三个源都可用环境变量改指向副本）：
 *   ROUTER_SRC=<副本>    ⇒ 往 router 里加一条新路由 ⇒ ① 必须变红
 *   PRESETS_SRC=<副本>   ⇒ 往 ThemeName 里加一个主题 ⇒ ③ 必须变红
 *   MATRIX_SRC=<副本>    ⇒ 从探针清单里删一条路由 ⇒ ② 必须变红
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const ROUTER = pick('ROUTER_SRC', path.join(ROOT, 'src', 'router', 'index.ts'))
const PRESETS = pick('PRESETS_SRC', path.join(ROOT, 'src', 'theme', 'presets.ts'))
const MATRIX = pick(
  'MATRIX_SRC',
  path.join(ROOT, 'scripts', 'cdp-contrast-matrix.mjs')
)

/**
 * 动态路由的样例地址登记表。
 * ★ 故意留空并要求"新增动态路由时必须来填" —— 一行都填不进去说明没有动态路由，
 *   那时「④ 动态路由必须登记」这条判据**恒真**，但它是"当下无此类对象"的恒真，
 *   不是"判据写错"的恒真：下一行就是它被触发的地方。
 */
const DYNAMIC_SAMPLE = {}

const ts = require(path.join(ROOT, 'node_modules', 'typescript'))

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
const read = (p) => fs.readFileSync(p, 'utf8')

function parse(file) {
  return ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
}
function firstDecl(sf, name, pred) {
  let hit = null
  ;(function walk(n) {
    if (!hit && pred(n)) hit = n
    ts.forEachChild(n, walk)
  })(sf)
  return hit
}

// ============================================================
// 抽取
// ============================================================

/** router/index.ts 的 `routes` 数组 ⇒ 路径字符串列表（AST，避免被注释里的路径骗到） */
function routerPaths() {
  const sf = parse(ROUTER)
  const decl = firstDecl(
    sf,
    'routes',
    (n) => ts.isVariableDeclaration(n) && n.name.getText(sf) === 'routes'
  )
  assert(!!decl, 'router/index.ts 里找不到 `routes` 声明')
  let init = decl.initializer
  while (init && (ts.isAsExpression(init) || ts.isSatisfiesExpression(init))) init = init.expression
  assert(ts.isArrayLiteralExpression(init), '`routes` 不是数组字面量')
  const out = []
  for (const el of init.elements) {
    if (!ts.isObjectLiteralExpression(el)) continue
    for (const p of el.properties) {
      if (
        ts.isPropertyAssignment(p) &&
        p.name.getText(sf) === 'path' &&
        ts.isStringLiteral(p.initializer)
      ) {
        out.push(p.initializer.text)
      }
    }
  }
  return out
}

/** 探针里的 `const DEFAULT_ROUTES = [ '/', ... ]` ⇒ 字符串列表 */
function matrixRoutes() {
  const body = read(MATRIX)
  const m = body.match(/const\s+DEFAULT_ROUTES\s*=\s*\[([\s\S]*?)\]/)
  assert(!!m, '探针里找不到 `const DEFAULT_ROUTES = [...]`')
  return [...m[1].matchAll(/'([^']*)'/g)].map((x) => x[1])
}

/** 探针里的 `const DEFAULT_THEMES = [...]` */
function matrixThemes() {
  const body = read(MATRIX)
  const m = body.match(/const\s+DEFAULT_THEMES\s*=\s*\[([\s\S]*?)\]/)
  assert(!!m, '探针里找不到 `const DEFAULT_THEMES = [...]`')
  return [...m[1].matchAll(/'([^']*)'/g)].map((x) => x[1])
}

/** presets.ts 的 `export type ThemeName = 'light' | 'dark' | 'macaron'` */
function presetThemes() {
  const body = read(PRESETS)
  const m = body.match(/export\s+type\s+ThemeName\s*=\s*([^\n]+)/)
  assert(!!m, 'presets.ts 里找不到 `export type ThemeName = ...`')
  return [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1])
}

const ROUTE_PATHS = routerPaths()
const M_ROUTES = matrixRoutes()
const M_THEMES = matrixThemes()
const P_THEMES = presetThemes()

// ============================================================
// [1] 自检：防「什么都没抽到 ⇒ 永远通过」
// ============================================================
console.log('=== 对比度矩阵覆盖面门禁 ===')
console.log(
  `router 路由 ${ROUTE_PATHS.length} 条 | 探针路由 ${M_ROUTES.length} 条 | ` +
    `探针主题 ${M_THEMES.join('/')} | presets 主题 ${P_THEMES.join('/')}`
)
console.log()
console.log('[1] 抽取器自检（防空跑）')

check('自检① router 至少抽出 8 条路由', () => {
  assert(ROUTE_PATHS.length >= 8, `只抽出 ${ROUTE_PATHS.length} 条 —— AST 走空了`)
})
check('自检② 探针至少声明 8 条路由', () => {
  assert(M_ROUTES.length >= 8, `只抽出 ${M_ROUTES.length} 条 —— 正则失效`)
})
check('自检③ 两份主题清单都非空', () => {
  assert(M_THEMES.length >= 2, `探针主题只抽出 ${M_THEMES.length} 个`)
  assert(P_THEMES.length >= 2, `presets 主题只抽出 ${P_THEMES.length} 个`)
})

// ============================================================
// [2] 核心不变量：router ⊆ 探针
// ============================================================
console.log()
console.log('[2] router 的每条路由都在探针清单里（新页面不许天然免检）')

check('router 路由 ⊆ 探针路由清单 ★★★', () => {
  const missing = ROUTE_PATHS.filter((p) => !M_ROUTES.includes(p))
  assert(
    missing.length === 0,
    `${missing.join(', ')} 在 router/index.ts 里存在，但探针的 DEFAULT_ROUTES 里没有 ` +
      `⇒ 这些页面**天然免检**（对比度探针永远不会去量它们），而门禁照样全绿。` +
      `请把它们加进 scripts/cdp-contrast-matrix.mjs 的 DEFAULT_ROUTES（沿用手写清单是有意的：` +
      `手写清单会被这条门禁逼着更新，自动抽取则会让"新页面免检"重新变回静默）`
  )
})

// ============================================================
// [3] 核心不变量：探针 ⊆ router（防陈旧条目）
// ============================================================
console.log()
console.log('[3] 探针清单里没有 router 已删的路由（防陈旧条目变噪声红）')

check('探针路由清单 ⊆ router 路由 ★', () => {
  const stale = M_ROUTES.filter((p) => !ROUTE_PATHS.includes(p))
  assert(
    stale.length === 0,
    `${stale.join(', ')} 还在探针清单里，但 router/index.ts 已经没有这些路由了 ` +
      `⇒ 它们会变成"元素不存在"的**永久噪声红**，而噪声红的下场是整条门禁被关掉`
  )
})

// ============================================================
// [4] 核心不变量：主题清单三方一致
// ============================================================
console.log()
console.log('[4] 主题清单：presets.ts 的 ThemeName == 探针的 DEFAULT_THEMES')

check('presets 的 ThemeName union == 探针 DEFAULT_THEMES ★★★', () => {
  const a = [...P_THEMES].sort().join(',')
  const b = [...M_THEMES].sort().join(',')
  assert(
    a === b,
    `presets.ts 声明 ${P_THEMES.length} 个主题（${P_THEMES.join(', ')}），` +
      `探针只跑 ${M_THEMES.length} 个（${M_THEMES.join(', ')}）` +
      `⇒ 没被跑到的主题**一次都没被体检过**，而门禁照样全绿`
  )
})

// ============================================================
// [5] 动态路由必须显式登记样例地址
// ============================================================
console.log()
console.log('[5] 动态路由（含 :）必须登记可访问的样例地址')

check('没有未登记的动态路由 ★', () => {
  const dyn = ROUTE_PATHS.filter((p) => p.includes(':'))
  const unlisted = dyn.filter((p) => !DYNAMIC_SAMPLE[p])
  assert(
    unlisted.length === 0,
    `${unlisted.join(', ')} 是动态路由 —— 探针不能直接访问带 : 的路径，` +
      `必须在 scripts/cdp-contrast-matrix.mjs 的 DEFAULT_ROUTES 里写一个**具体样例地址**，` +
      `并到本文件的 DYNAMIC_SAMPLE 里登记"它代表哪条动态路由"`
  )
})

// ===== 输出 =====
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n对比度矩阵覆盖面门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `对比度矩阵覆盖面门禁通过（${ROUTE_PATHS.length} 路由 × ${P_THEMES.length} 主题 = ` +
    `${ROUTE_PATHS.length * P_THEMES.length} 格全部在体检范围内 ✓）`
)

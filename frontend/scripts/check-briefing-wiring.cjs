#!/usr/bin/env node
/**
 * 每日经营简报「接线」门禁（check-briefing-wiring · 第 371 轮）
 * ============================================================================
 * 为什么值得单独一个门禁
 * ============================================================================
 * 头部的通知铃铛在本轮之前是**装饰**：`Workspace.vue` 里写死
 *
 *     <a-badge :count="0" dot><BellOutlined style="font-size: 18px; cursor: pointer" /></a-badge>
 *
 * 它**没有 `@click`**、计数是字面量 `0`。而这一形态能骗过所有现成门禁：
 *   · `vue-tsc` —— 类型完全正确（`count` 收 number，`0` 就是 number）；
 *   · `check-window-widths` —— 它只管窗口宽度，不关心窗口里有没有数据；
 *   · vitest —— 组件照常挂载、照常渲染，没有一处会抛；
 *   · `eslint` —— 没有未使用变量（`BellOutlined` 确实在模板里被用了）。
 * 唯一能观察到的是「用户点了没反应 / 徽标永远是 0」，而那要靠人眼。
 * 这正是本仓反复记过的形状：**缺陷不报错，只是永远不生效**。
 *
 * 本轮把它接成真入口（`components/Header/NotificationBell.vue` + `stores/briefing.ts`
 * + `api/briefings.ts` ⇒ 后端 `modules/monitors/router.py`）。本门禁守两件事：
 *
 *   A 组「铃铛不是装饰」——计数必须来自**绑定表达式**（不是字面量）、
 *     点击必须真的打开一个抽屉、抽屉必须真的挂在 Workspace 上。
 *   B 组「跨语言对账」——前端调的**路径**与后端注册的路径一致、前端声明的
 *     **字段名**与后端 `_to_dict()` 的键一致。
 *     ★ 这一组的失效形态是**静默 404 / 静默 undefined**：后端把 `/briefings`
 *       改成 `/briefing`、或把 `item_count` 改名，前端界面只会「空白 / 0 项」，
 *       没有任何一层会报错。本仓对同族问题已有先例（`check-glossary-parity.cjs`）。
 *
 * 判据分组
 *   S0  扫描面：三个源文件都读到且非空（否则后面全在空串上恒假）
 *   S1  徽标计数是**表达式**，不是字面量（`"0"` 这种死铃铛形态 ⇒ 红）
 *   S2  点击真的打开抽屉：`:width` 走 WINDOW_W + `@click` 指向的函数体里
 *       真有「把某个开关置 true」的赋值（防「有 @click 但 handler 空转」）
 *   S3  `Workspace.vue` 模板里真的渲染了 `<NotificationBell />`（逐调用点）
 *   S4  `Workspace.vue` 里不再有死铃铛形态（`<a-badge :count="0"`）
 *   S5  前端 API 路径集合 == 后端 router 的 briefing 路径集合（参数段归一化为 `{}`）
 *   S6  前端 `DailyBriefing` 字段 ⊆ 后端 `_to_dict()` 键集合
 *   S7  package.json 登记了 check:briefing-wiring
 *   S8  本门禁已接入 npm run build 链
 *   S9  自检：S1/S5 的匹配器有正反样本（防「两边都抽不到 ⇒ 相等 ⇒ 恒绿」）
 *
 * 退出码：0 = PASS；1 = FAIL；2 = 探针自身失效（读不到源，不予判定）
 *
 * 反向注入（证明本门禁不是空跑）：
 *   BRIEFING_SRC_ROOT=<副本>  BRAIN_ROUTER=<副本>  指向副本树后改动其中一处，
 *   对应判据必须变红 —— 台架见 `.workbuddy/probes/revinject-r371-bell-gate.py`
 */

'use strict'

const fs = require('node:fs')
const path = require('node:path')

const ROOT = path.resolve(__dirname, '..')             // frontend/
const SRC = process.env.BRIEFING_SRC_ROOT
  ? path.resolve(process.env.BRIEFING_SRC_ROOT)
  : path.join(ROOT, 'src')
const REPO = path.dirname(ROOT)
const ROUTER_PY = process.env.BRAIN_ROUTER
  ? path.resolve(process.env.BRAIN_ROUTER)
  : path.join(REPO, 'backend', 'modules', 'monitors', 'router.py')
// ★ 字段对账要读的是**业务模块**而不是 router：`_to_dict()` 住在
//   `briefing.py`（router 只做 HTTP 面）。只读 router 的话 S6 会「抽不到键」
//   —— 那种红是**判据写错**，不是产品缺陷（本仓记过的归因陷阱）。
const BRIEFING_PY = process.env.BRAIN_BRIEFING
  ? path.resolve(process.env.BRAIN_BRIEFING)
  : path.join(REPO, 'backend', 'modules', 'monitors', 'briefing.py')

// ---------------------------------------------------------------- 台架

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

/** 行尾归一化**必须真做**：同一目录下 CRLF / LF 混存是本仓常态。 */
function read(abs) {
  if (!fs.existsSync(abs)) return null
  try {
    return fs.readFileSync(abs, 'utf8').replace(/\r\n/g, '\n')
  } catch {
    return null
  }
}

/**
 * 剥 HTML 注释；**保留换行**使行号不失真（同 check-window-widths 的理由）。
 */
function stripHtmlComments(src) {
  if (src == null) return ''
  return src.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ''))
}

/** 剥 JS 行注释与块注释；保留换行。★ 先剥注释再判「字面量」，否则注释里的例子会骗过判据。 */
function stripJsComments(src) {
  if (src == null) return ''
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m) => (m[0] === '/' && m[1] === '/' ? m.replace(/[^\n]/g, '') : m[0] + m.slice(2).replace(/[^\n]/g, '')))
}

// ---------------------------------------------------------------- 读源

const BELL_REL = 'components/Header/NotificationBell.vue'
const API_REL = 'api/briefings.ts'
const WS_REL = 'views/Workspace.vue'

const bellRaw = read(path.join(SRC, BELL_REL))
const apiRaw = read(path.join(SRC, API_REL))
const wsRaw = read(path.join(SRC, WS_REL))
const routerRaw = read(ROUTER_PY)
const briefingRaw = read(BRIEFING_PY)

/**
 * ★ 两个剥注释函数**都要用**，缺一个就会**假红**（本轮实测）：
 *   本组件文件头的 JSDoc 里逐字写了前身的形态 `<a-badge :count="0" dot>`，
 *   只剥 HTML 注释的话，那句「举例说明」会被当成真代码 ——
 *   S1 当场报「找到 2 个 :count 绑定（要求恰好 1 个）」。
 *   这正是本仓记过的同族陷阱（判据读到了文档而非代码），只是方向相反：
 *   那边是**假绿**，这边是**假红** —— 而假红的下场是门禁被关掉。
 */
const bell = stripHtmlComments(stripJsComments(bellRaw))
const apiCode = stripJsComments(apiRaw)
const ws = stripHtmlComments(stripJsComments(wsRaw))
const routerCode = routerRaw ? routerRaw.replace(/"""[\s\S]*?"""/g, '') : null
const briefingCode = briefingRaw || null

// ---------------- S0 扫描面 ----------------
check(
  bell != null && bell.length > 200,
  'S0a 读到 NotificationBell.vue 且非空（=0 说明路径写错，后面判据全在空串上恒假）',
  bell == null ? `未找到 ${BELL_REL}` : `${bell.length} 字符`
)
check(apiCode != null && apiCode.length > 100, 'S0b 读到 api/briefings.ts 且非空',
  apiCode == null ? `未找到 ${API_REL}` : `${apiCode.length} 字符`)
check(ws != null && ws.length > 1000, 'S0c 读到 views/Workspace.vue 且非空',
  ws == null ? `未找到 ${WS_REL}` : `${ws.length} 字符`)
check(routerCode != null && routerCode.length > 500, 'S0d 读到后端 monitors/router.py 且非空',
  routerCode == null ? `未找到 ${ROUTER_PY}` : `${routerCode.length} 字符`)
check(briefingCode != null && briefingCode.length > 1000, 'S0e 读到后端 monitors/briefing.py 且非空',
  briefingCode == null ? `未找到 ${BRIEFING_PY}` : `${briefingCode.length} 字符`)

// ---------------- S1 徽标计数必须是表达式 ----------------
/** 抽出 `<a-badge …>` 起始标签（跨行、跳过引号内的 `>`）。 */
function scanTag(src, tag) {
  const out = []
  const re = new RegExp(`<${tag}\\b`, 'g')
  let m
  while ((m = re.exec(src)) !== null) {
    let j = m.index + m[0].length
    let q = null
    while (j < src.length) {
      const c = src[j]
      if (q) { if (c === q) q = null }
      else if (c === '"' || c === "'") q = c
      else if (c === '>') break
      j++
    }
    out.push({ text: src.slice(m.index, j + 1), line: src.slice(0, m.index).split('\n').length })
  }
  return out
}

const badges = scanTag(bell, 'a-badge')
const countBindings = badges.map((b) => /:count\s*=\s*"([^"]*)"/.exec(b.text)).filter(Boolean).map((m) => m[1])
const literalCounts = countBindings.filter((v) => /^\s*-?\d+(\.\d+)?\s*$/.test(v))

check(
  countBindings.length === 1 && literalCounts.length === 0,
  'S1 徽标计数走**绑定表达式**而不是字面量（`:count="0"` 就是死铃铛的形态）',
  countBindings.length !== 1
    ? `找到 ${countBindings.length} 个 :count 绑定（要求恰好 1 个）`
    : literalCounts.length
      ? `字面量：${literalCounts.join(', ')}`
      : `:count="${countBindings[0]}"`
)

// ---------------- S2 点击真的打开抽屉 ----------------
const drawerTags = scanTag(bell, 'a-drawer')
const drawerOk = drawerTags.length >= 1 && /:width\s*=\s*"WINDOW_W\.\w+"/.test(drawerTags[0]?.text || '')
check(
  drawerOk,
  'S2a 组件里有一个抽屉，且宽度取自 WINDOW_W（本地前提；宽度口径另由 check-window-widths 全仓守）',
  drawerTags.length ? drawerTags[0].text.split('\n')[0].trim() : '没有 <a-drawer>'
)

const openRef = /v-model:open\s*=\s*"(\w+)"/.exec(drawerTags[0]?.text || '')
const clickRef = /@click\s*=\s*"(\w+)"/.exec(scanTag(bell, 'button').map((b) => b.text).join('\n'))
/** 取 `function NAME(` 的函数体（花括号配平），判「真的把开关置 true」 */
function fnBody(src, name) {
  const i = src.indexOf(`function ${name}(`)
  if (i < 0) return null
  const j = src.indexOf('{', i)
  if (j < 0) return null
  let depth = 0
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++
    else if (src[k] === '}') {
      depth--
      if (depth === 0) return src.slice(j, k + 1)
    }
  }
  return null
}
const openFnName = openRef ? openRef[1] : null
const clickFnName = clickRef ? clickRef[1] : null
const body = clickFnName ? fnBody(bell, clickFnName) : null
const flips = body != null && openFnName != null && new RegExp(`${openFnName}\\.value\\s*=\\s*true`).test(body)

check(
  !!openFnName && !!clickFnName && !!body && flips,
  'S2b 铃铛的 @click 指向的函数**真的打开了抽屉**（防「有 @click 但 handler 空转」）',
  !openFnName
    ? '抽屉没有 v-model:open 绑定'
    : !clickFnName
      ? '铃铛按钮没有 @click'
      : !body
        ? `找不到 function ${clickFnName} 的函数体`
        : flips
          ? `${clickFnName}() ⇒ ${openFnName}.value = true`
          : `${clickFnName}() 的函数体里没有 \`${openFnName}.value = true\``
)

// ---------------- S3/S4 Workspace 侧 ----------------
check(
  /<NotificationBell\s*\/>/.test(ws),
  'S3 Workspace.vue 模板里真的渲染 <NotificationBell />（剥掉注释后再判 —— 注释里提到组件名不算）'
)

const deadBells = scanTag(ws, 'a-badge').filter((b) => /:count\s*=\s*"(0|\d+)"/.test(b.text))
check(
  deadBells.length === 0,
  'S4 Workspace.vue 里不再有死铃铛形态（`<a-badge :count="0">`）',
  deadBells.length ? `第 ${deadBells.map((b) => b.line).join(', ')} 行` : '零残留'
)

// ---------------- S5 路径对账（跨语言）----------------
/** 参数段归一化成 `{}`：前端写 `${id}`、后端写 `{briefing_id}`，比较的是**形状**不是变量名。 */
function normPath(p) {
  return p
    .replace(/\$\{[^}]*\}/g, '{}')
    .replace(/\{[^}]*\}/g, '{}')
    .replace(/\/+$/, '')
}
function frontPaths(src) {
  const out = new Set()
  const re = /\b(get|post|put|del)\s*\(\s*(`|'|")([^`'"]+)\2/g
  let m
  while ((m = re.exec(src)) !== null) {
    if (m[3].startsWith('/')) out.add(normPath(m[3]))
  }
  return out
}
function backendBriefingPaths(src) {
  const out = new Set()
  // 只取 briefing 相关：`@router.<verb>("/briefings…")`
  const re = /@router\.(get|post|put|delete)\s*\(\s*"([^"]*)"/g
  let m
  while ((m = re.exec(src)) !== null) {
    if (m[2].includes('/briefings')) out.add(normPath(m[2]))
  }
  return out
}
const fePaths = frontPaths(apiCode || '')
const bePaths = backendBriefingPaths(routerCode || '')
const onlyFe = [...fePaths].filter((p) => !bePaths.has(p))
const onlyBe = [...bePaths].filter((p) => !fePaths.has(p))

check(
  fePaths.size > 0 && bePaths.size > 0 && onlyFe.length === 0 && onlyBe.length === 0,
  'S5 前端 API 路径集合 == 后端 router 的 briefing 路径集合（参数段归一化为 `{}`）',
  fePaths.size === 0
    ? '前端一个路径都没抽到（匹配器坏了？）'
    : bePaths.size === 0
      ? '后端一个 /briefings 路径都没抽到（匹配器坏了？）'
      : `前端多：${onlyFe.join(', ') || '无'}；后端多：${onlyBe.join(', ') || '无'}`
)

// ---------------- S6 字段对账（跨语言）----------------
/** 后端 `_to_dict()` 的 `return { "k": …, }` 键集合 */
function backendDictKeys(src) {
  const i = src.indexOf('def _to_dict(')
  if (i < 0) return null
  const j = src.indexOf('return {', i)
  if (j < 0) return null
  const k = src.indexOf('\n    }', j)
  const block = k < 0 ? null : src.slice(j, k)
  if (!block) return null
  const out = new Set()
  const re = /"(\w+)"\s*:/g
  let m
  while ((m = re.exec(block)) !== null) out.add(m[1])
  return out
}
/** 前端 `export interface DailyBriefing { … }` 的字段名 */
function tsInterfaceFields(src, name) {
  const i = src.indexOf(`export interface ${name} {`)
  if (i < 0) return null
  const k = src.indexOf('\n}', i)
  const block = k < 0 ? null : src.slice(i, k)
  if (!block) return null
  const out = new Set()
  const re = /^\s{2}(\w+)\??\s*:/gm
  let m
  while ((m = re.exec(block)) !== null) out.add(m[1])
  return out
}
const beKeys = backendDictKeys(briefingCode || '')
const feFields = tsInterfaceFields(apiCode || '', 'DailyBriefing')
const missing = beKeys && feFields ? [...feFields].filter((f) => !beKeys.has(f)) : null

check(
  !!beKeys && beKeys.size > 0 && !!feFields && feFields.size > 0 && missing.length === 0,
  'S6 前端 DailyBriefing 字段 ⊆ 后端 _to_dict() 的键（后端单方面改名 ⇒ 界面静默 undefined）',
  !beKeys || beKeys.size === 0
    ? '后端 _to_dict() 的键集合没抽到'
    : !feFields || feFields.size === 0
      ? '前端 DailyBriefing 接口没抽到'
      : `前端多出：${missing.join(', ') || '无'}`
)

// ---------------- S7/S8 登记 ----------------
const pkg = (() => {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')) } catch { return null }
})()
check(
  !!pkg && /check-briefing-wiring\.cjs/.test(String(pkg.scripts?.['check:briefing-wiring'] || '')),
  'S7 package.json 登记了 check:briefing-wiring'
)
check(
  !!pkg && /check-briefing-wiring\.cjs/.test(String(pkg.scripts?.build || '')),
  'S8 本门禁已接入 npm run build 链'
)

// ---------------- S9 自检：匹配器有正反样本 ----------------
const lit = (s) => /^\s*-?\d+(\.\d+)?\s*$/.test(s)
check(
  lit('0') && lit(' 12 ') && !lit('store.unread') && !lit('items.length'),
  'S9a S1 的字面量判定有正反样本（`0` / `12` 判真；表达式判假）'
)
check(
  normPath('/briefings/${id}/read') === '/briefings/{briefing_id}/read'.replace(/\{[^}]*\}/g, '{}') &&
    normPath('/briefings') === '/briefings',
  'S9b S5 的路径归一化有正反样本（`${id}` 与 `{briefing_id}` 必须归一成同一形状）'
)

// ---------------- 汇总 ----------------
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.label}${r.ok || !r.detail ? '' : '  ⟵ ' + r.detail}`)
}
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)

if (bell == null || apiCode == null || ws == null || routerCode == null || briefingCode == null) {
  console.log('探针自身失效：有源文件读不到，本门禁不予判定（退出码 2，不并进通过）')
  process.exit(2)
}
if (failed.length) {
  console.log('红：' + failed.map((r) => r.label.split(' ')[0]).join(', '))
  process.exit(1)
}
console.log('简报接线门禁通过（徽标计数走绑定 · 点击真开抽屉 · Workspace 真渲染 · 前后端路径/字段对账 ✓）')

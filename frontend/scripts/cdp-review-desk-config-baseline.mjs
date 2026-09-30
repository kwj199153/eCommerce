// CDP 真实浏览器「行为基线」—— 拆 ReviewDeskConfig.vue（抽 composable）的前置（第 340 轮 · #1252）。
//
// ============================================================================
// ★ 为什么先建基线，而不是直接拆
// ============================================================================
// 抽 composable 是**纯重构**：目标是「行为一点不变」，只是把状态与逻辑从
// `.vue` 里搬到 `.ts`。这种改动**静态门禁天生看不见**它改坏了什么：
//   · `vue-tsc` 只保证类型对得上，不保证运行期状态真的被共享（拆错时常见症状：
//     两个 ref 各持一份副本，界面「看起来对」但改一处另一处不跟）；
//   · `check-review-desk-*.cjs` 判的是源码文本形态，改完仍是那些文本；
//   · 单测覆盖不到「点击 → 视图切换 → 抽屉结构」这条真链路。
// ⇒ 先把**当前可观测的行为**用真实浏览器钉成一份 JSON 基线；拆完复跑，
//   逐字段比对。这才是「行为没变」的证据，而不是「我觉得没变」。
//
// ============================================================================
// ★ 被钉住的是什么（只钉「对外可见」的行为，不钉内部实现）
// ============================================================================
//   1. 面板能否挂出（`.rd-root`）；
//   2. 四个视图 tab 的**文案 / 顺序 / 激活态**；
//   3. 每个视图下**哪些容器出现**（risk-bar / ledger / rules / list 的互斥关系）；
//   4. 各视图下的行数、表数、分节标题；
//   5. 按钮 title 集合（本仓把「读 / 写 / 只能人点」口径挂在 title 上）；
//   6. 抽屉结构（detail-grid / section / kv / block / chips 的计数）；
//   7. ★ 计算样式（第 341 轮补）：`.rd-table` 系列 / `.rd-table-act` / `.rd-rule-cond` /
//      `.rd-detail-grid` 等的 getComputedStyle 读数 —— **只读 DOM 结构看不见样式丢失**，
//      而「把表格拆成子组件会让父组件 scoped 的后代选择器失效」正是最隐蔽的破坏。
//   8. ★ 子组件**事件契约**（第 342 轮补）：规则表拆成子组件后，3 个动作改走
//      `emit('edit'|'toggle'|'remove')` —— emit 名与父组件的 `@edit`/`@toggle`/`@remove`
//      对不上时按钮**静默失效**，而 DOM 计数 / class / 行数 / 计算样式**一概不变**。
//      ⇒ 必须**真点**：点【编辑】断言弹窗与参数；【启用】/【删除】先把写请求拦在浏览器层
//      （不落共享库），再断言「请求真的发出了」。
//   ★ 刻意**不**钉：DOM 顺序、`style=` 内联属性、行内容文案、以及百分比宽度换算出的 px
//     —— 那些会随 seed / 浮点抖动变，钉住只会让基线自己变得易碎。
//
// ============================================================================
// ★ 两条本仓纪律
// ============================================================================
//   · **先注入真身份**（`access_token` 必须是非 demo 的真 JWT，`isRealLogin` 才为真）：
//     不注入 ⇒ 首屏带空 token 打一轮 401，面板可能挂不出来，表现为「全红」——
//     那是**注入失败**，不是功能坏了，报告时必须区分这两件事。
//   · **基线要自证可复读**：每个状态**连采两遍**，两遍不等就当场 FAIL
//     （读数不稳定 ⇒ 这样的基线拿去做比对只会制造假红）。
//   · **基线要自证有牙齿**（第 341 轮补）：样式类判据若对「样式丢失」不敏感，基线就是白做的。
//     ⇒ 用 `.workbuddy/probes/r341_inject_style.py` 做两次受控注入，实测两条都转红：
//       - `inject th`（`.rd-table th,` 后缀改名 ⇒ 后代选择器失效）：B3c/B4c 红（th padding 4px→0px…）
//       - `inject act`（`.rd-table-act {` 改名 ⇒ sticky 列失效）：B3c/B4c 红（position sticky→static…）
//     ★ 教训：**读数抓到了 ≠ 判据会红**。第一版 B3c 只断言 th.fontWeight（由另一条幸存的规则提供），
//       注入后表头 padding/对齐/边框全变、判据却照样 PASS ⇒ 判据必须把抓到的字段**逐条**断言。
//     ★ 另注：探针与被测应用**共享限流配额**（60/min），密集连跑会出 429 ⇒ B5a 之类的伪红；
//       元数据里的 rateHits / netTail 就是用来把「限流降级」与「真红」分开的。
//     ★ 写操作的接线怎么测才不动数据（第 342 轮补）：用 `Network.setBlockedURLs` 把该资源的
//       写请求在浏览器层拦掉 —— 请求发不出去、库不变，但 `Network.requestWillBeSent` 照旧触发
//       ⇒ 用 `sentLog` 断言「应用真的试图发这个请求」。
//       ★ 判据**必须**取「请求发出了」，不能取「页面没报错」：拦掉后前端必然 message.error，
//         判「有没有报错」等于恒真 = fail-open 的假门禁。
//       ★ 拦截是**全局**的 ⇒ 只在该段的点击前后开关，结束立刻解封（否则后续取数一并被挡，
//         症状看起来像限流降级 B5a）。
//
// 用法：node scripts/cdp-review-desk-config-baseline.mjs
//   PROBE_URL   覆盖地址（默认 http://127.0.0.1:5173/）
//   PROBE_OUT   覆盖输出 JSON 路径
//   PROBE_TAG   给本次运行打标（默认 run），用于「连跑两次比对」
// 前置：dev server(:5173) 在跑；.workbuddy/probes/r328_tokens.json 存在
//       （由 .workbuddy/probes/r328_mint_tokens.py 用后端自己的签发器生成）。
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9391 // 避开既有探针：9377(ui) / 9382(systemic) / 9368(r328)
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const TAG = process.env.PROBE_TAG || 'run'
const OUT_DIR = 'D:/ai/eCommerce/.workbuddy/probes/r340_review_desk_baseline'
const OUT_FILE = process.env.PROBE_OUT || join(OUT_DIR, `baseline-${TAG}.json`)
const TOKEN_FILE = 'D:/ai/eCommerce/.workbuddy/probes/r328_tokens.json'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  let d = ''
  if (ok !== true) {
    const s = JSON.stringify(detail ?? null)
    d = '  <- ' + (s.length > 420 ? s.slice(0, 420) + '...' : s)
  }
  console.log(`${state}  ${id}  ${name}${d}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(OUT_DIR, { recursive: true })

// ------------------------------------------------------------------ 身份注入
let TOKENS
try {
  TOKENS = JSON.parse(readFileSync(TOKEN_FILE, 'utf8'))
} catch {
  console.error('缺少身份令牌文件（先跑 .workbuddy/probes/r328_mint_tokens.py）：' + TOKEN_FILE)
  process.exit(1)
}
const who = TOKENS?.admin?.token ? 'admin' : TOKENS?.user?.token ? 'user' : null
if (!who) { console.error('令牌文件结构不对（需要 admin / user 至少一枚 token）'); process.exit(1) }
const tk = TOKENS[who]
const BOOT = [
  'try {',
  `  localStorage.setItem("access_token", ${JSON.stringify(tk.token)});`,
  '  localStorage.setItem("refresh_token", "r340-probe-refresh-not-demo");',
  `  localStorage.setItem("user_info", ${JSON.stringify(JSON.stringify({
    id: tk.user_id, email: tk.email, name: 'RD基线', role: who === 'admin' ? 'admin' : 'user',
    is_active: true, is_verified: true,
  }))});`,
  '  localStorage.setItem("theme_mode", "light");',
  '  localStorage.setItem("onboarding_tour_v1", JSON.stringify({v:1,seen:true,lastIndex:0,ts:Date.now()}));',
  '} catch (e) {}',
].join('\n')

// ------------------------------------------------------------------ 浏览器
const profile = mkdtempSync(join(tmpdir(), 'cdp-r340-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking', 'about:blank',
], { stdio: 'ignore' })

const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 240s，强制退出')
  try { chrome.kill() } catch { /* ignore */ }
  process.exit(2)
}, 240000)

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
    if (targets.some((t) => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) { console.log('FAIL: no page target'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
/** 接口调用留痕：用于区分「抽屉数据没回来」是限流 / 失败 / 单纯慢。 */
const netLog = []
const rateHits = []
/** ★ 「应用**试图**发出的请求」（第 342 轮补）：被 `setBlockedURLs` 拦掉的请求不会有
 *  responseReceived，只有 requestWillBeSent 能证明接线通、处理器真的打了 API。 */
const sentLog = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Network.responseReceived') {
    const r = m.params?.response || {}
    const url = String(r.url || '')
    if (url.includes('/api/v1/')) netLog.push({ path: url.split('/api/v1')[1]?.split('?')[0], status: r.status })
    // ★ 探针与被测应用**共享限流配额**（60/min，按 IP）：429 会让页面降级成残缺态，
    //   症状会伪装成「功能坏了」。记下来才能与真红区分。
    if (r.status === 429) rateHits.push(url.slice(0, 100))
  }
  if (m.method === 'Network.requestWillBeSent') {
    const req = m.params?.request || {}
    const u = String(req.url || '')
    if (u.includes('/api/v1/')) {
      const p = u.split('/api/v1')[1]?.split('?')[0] || ''
      const segs = p.split('/').filter(Boolean)
      sentLog.push({
        m: req.method,
        path: p,
        // 末段是资源 id —— 用来对账「两个按钮作用在同一行」
        id: segs.length ? segs[segs.length - 1] : '',
        body: req.postData ? String(req.postData).slice(0, 300) : null,
      })
    }
  }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => {
  const i = ++seq
  pending.set(i, (m) => res(m.result ?? m.error ?? null))
  ws.send(JSON.stringify({ id: i, method, params }))
})

/** 裸表达式求值：**不要**在这里引用任何外部 helper —— 作用域不同会 ReferenceError，
 *  而表达式仍可能 return，静默假绿。需要 helper 的写法一律自带定义。 */
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.exceptionDetails) throw new Error(String(r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 300))
  return r?.result?.value
}
const shot = async (name) => {
  try {
    const r = await send('Page.captureScreenshot', { format: 'png' })
    if (r?.data) writeFileSync(join(OUT_DIR, `${TAG}-${name}.png`), Buffer.from(r.data, 'base64'))
  } catch { /* 截图失败不影响判定 */ }
}

await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')
// ★ 身份在**导航前**注入：否则首屏会带空 token 打一轮接口（刷 401 噪音）。
await send('Page.addScriptToEvaluateOnNewDocument', { source: BOOT })
await send('Page.navigate', { url: URL })

// ---------------------------------------------------------------- 原语
/** 按**精确文本**点最内层可点元素（避免点到大容器）—— 与 cdp-review-desk-ui-probe.mjs 同口径。 */
const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found', have: [...new Set(all.map(e => norm(e.textContent)).filter(t => t.includes(${JSON.stringify(label.slice(0, 2))})))].slice(0, 8) })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, cls: String(target.className) })
})()`

/** 切视图：按 tab 文本点（textContent 含 icon + label + 可选 count，故用 includes）。 */
const switchView = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const t = [...document.querySelectorAll('.rd-root .rd-tab')].find(b => norm(b.textContent).includes(${JSON.stringify(label)}))
  if (!t) return JSON.stringify({ ok: false, have: [...document.querySelectorAll('.rd-root .rd-tab')].map(b => norm(b.textContent)) })
  t.click()
  return JSON.stringify({ ok: true, label: norm(t.textContent) })
})()`

const CAPTURE = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const q = (s) => document.querySelector(s)
  const qa = (s) => [...document.querySelectorAll(s)]
  const root = q('.rd-root')
  if (!root) return JSON.stringify({ root: false })
  // ★ label 的 textContent = icon + 纯文案 + 可选计数（如「📉近期差评20」）⇒ 拿它做**相等**比对会因计数假红。
  //   ⇒ 另取「无 class 的那个 span」（源码 L14）作为**纯文案**，供相等判据使用。
  const tabs = qa('.rd-root .rd-tab').map(b => {
    const pureEl = [...b.children].find(el => el.tagName === 'SPAN' && !el.className)
    return {
      label: norm(b.textContent),
      pure: pureEl ? norm(pureEl.textContent) : '',
      active: b.classList.contains('active'),
      hasCount: !!b.querySelector('.rd-tab-count'),
    }
  })
  const hint = q('.rd-root .rd-hint')
  const filters = qa('.rd-root .rd-filter')
  const main = [!!hint, !!q('.rd-root .rd-ledger'), !!q('.rd-root .rd-rules'), !!q('.rd-root .rd-list')]
  // ★★ 计算样式读数（第 341 轮 · #1253 补）—— 为什么非要有它：
  //   scoped CSS 只作用在**本组件模板**的元素上，且父组件的 scopeId 只加在**子组件根元素**上
  //   ⇒ 把 rules 视图里的 table.rd-table 拆成子组件后，父组件 scoped 的**后代选择器**
  //     （.rd-table th / .rd-table td / .rd-table-act / .rd-rule-cond …）不再命中子组件内部元素
  //     ⇒ rules 表**静默丢样式**（padding / sticky 列 / 字号回落默认值）。
  //   而只读 DOM 结构（计数 / class / 行数）**完全看不出**这件事 —— 必须量计算样式。
  //   ★ 只取**稳定量**：类别型（collapse / table / nowrap / sticky / 整数字号）与整数像素；
  //     刻意**不取 width**（百分比宽度换算成 px 可能带小数 ⇒ 会制造假红）。
  //   ★ 注释里**禁写反引号**：本表达式整体是模板字符串，反引号会当场截断它（第 340 轮踩过）。
  const csOf = (el, props) => {
    if (!el) return null
    const s = getComputedStyle(el)
    const o = {}
    for (const p of props) o[p] = s[p]
    return o
  }
  const tbl = q('.rd-root table.rd-table')
  const act = q('.rd-root .rd-table-act')
  const styles = {
    table: csOf(tbl, ['display', 'borderCollapse', 'whiteSpace', 'fontSize', 'tableLayout']),
    th: csOf(tbl && tbl.querySelector('thead th'), ['paddingTop', 'paddingLeft', 'backgroundColor', 'fontWeight', 'textAlign', 'borderBottomWidth']),
    td: csOf(tbl && tbl.querySelector('tbody td'), ['paddingTop', 'paddingLeft', 'textAlign', 'borderBottomWidth']),
    act: csOf(act, ['position', 'right', 'backgroundColor', 'borderLeftWidth', 'textAlign']),
    // ★ 按钮必须**直接查**，不能从 act 里 querySelector：DOM 顺序里第一个 .rd-table-act 是 thead 的
    //   **空 th**（里面没有按钮）⇒ 取到 null（第 341 轮实测踩过，B3c/B4c 因此假红）。
    actBtn: csOf(q('.rd-root .rd-table-act .ant-btn'), ['paddingLeft', 'paddingRight']),
    ruleCond: csOf(q('.rd-root .rd-rule-cond'), ['whiteSpace', 'fontSize', 'color']),
    ruleOff: csOf(q('.rd-root .rd-rule-off'), ['opacity']),
    ledger: csOf(q('.rd-root .rd-ledger'), ['overflowX', 'borderTopWidth', 'borderRadius']),
    rulesWrap: csOf(q('.rd-root .rd-rules'), ['display', 'flexDirection', 'rowGap']),
    rulesBar: csOf(q('.rd-root .rd-rules-bar'), ['display', 'justifyContent', 'alignItems']),
    // 差评列表卡片（default / orphan 视图）—— 刀 3（CSS 外移）同样要有覆盖。
    list: csOf(q('.rd-root .rd-list'), ['display', 'flexDirection', 'rowGap']),
    item: csOf(q('.rd-root .rd-item'), ['paddingTop', 'paddingLeft', 'borderTopWidth', 'borderTopLeftRadius', 'cursor']),
    itemTop: csOf(q('.rd-root .rd-item-top'), ['display', 'alignItems', 'columnGap', 'marginBottom']),
    body: csOf(q('.rd-root .rd-body'), ['fontSize', 'overflow']),
    stars: csOf(q('.rd-root .rd-stars'), ['letterSpacing', 'color']),
    riskBarBox: csOf(q('.rd-root .rd-risk-bar'), ['display', 'alignItems', 'flexWrap', 'rowGap']),
  }
  return JSON.stringify({
    root: true,
    tabs,
    titles: [...new Set(qa('.rd-root [title]').map(e => norm(e.getAttribute('title'))).filter(Boolean))].sort(),
    // —— .rd-filter 有两个（源码 L39 view!==ledger 的「时间窗+星级」/ L120 配 risk-bar v-if 的 v-else，
    //    内含「状态」筛选 + 生成待处置）：所以 recent/ledger 各 1 个、orphan/rules 各 2 个。
    filterCount: filters.length,
    filterHasTimeWindow: filters.some(f => norm(f.textContent).includes('时间窗')),
    filterHasGenerate: filters.some(f => norm(f.textContent).includes('生成待处置')),
    riskBar: !!q('.rd-root .rd-risk-bar'),
    alertCount: qa('.rd-root .rd-alert').length,
    // —— 主内容是**同一条 v-if/v-else-if 链**（源码 L161→163→167→182→251→306）：
    //    hint(加载中/空态) / ledger / rules / list 四者**互斥**，走哪一支由 hasRows（数据）决定。
    //    ★ 不得写死「recent 一定是 list」—— 数据为空时它同样走 hint。
    main: {
      hint: main[0],
      hintTitle: norm(hint ? (hint.querySelector('.rd-hint-title')?.textContent || '') : ''),
      ledger: main[1],
      rules: main[2],
      list: main[3],
      exclusiveCount: main.filter(Boolean).length,
    },
    tables: qa('.rd-root table.rd-table').length,
    itemCount: qa('.rd-root .rd-list .rd-item').length,
    ledgerRows: qa('.rd-root .rd-ledger tbody tr').length,
    ledgerCols: qa('.rd-root .rd-ledger thead th').length,
    rulesRows: qa('.rd-root .rd-rules tbody tr').length,
    rulesCols: qa('.rd-root .rd-rules thead th').length,
    styles,
  })
})()`

const CAPTURE_DRAWER = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const q = (s) => document.querySelector(s)
  const qa = (s) => [...document.querySelectorAll(s)]
  // ★ 抽屉是 a-drawer（ant-design-vue）：内容 **teleport 到 body**，**不在 .rd-root 内**。
  //   第一版写 .rd-root .rd-detail-grid ⇒ 恒 0，把「选择器写错」误报成「抽屉没渲染」。
  const D = '.ant-drawer-content'
  const sections = qa(D + ' .rd-section')
  // ★ 抽屉区块的计算样式（第 341 轮补）—— 同 CAPTURE：scoped 后代选择器拆子组件后会失配。
  //   只取稳定量；注释里禁写反引号（模板字符串会被截断）。
  const csOf = (el, props) => {
    if (!el) return null
    const s = getComputedStyle(el)
    const o = {}
    for (const p of props) o[p] = s[p]
    return o
  }
  const styles = {
    grid: csOf(q(D + ' .rd-detail-grid'), ['display', 'flexDirection', 'alignItems', 'columnGap']),
    col: csOf(q(D + ' .rd-detail-col'), ['flexGrow', 'flexShrink', 'flexBasis', 'minWidth']),
    section: csOf(q(D + ' .rd-section'), ['marginTop']),
    kv: csOf(q(D + ' .rd-kv'), ['display', 'fontSize', 'marginBottom']),
    block: csOf(q(D + ' .rd-block'), ['marginBottom']),
    chip: csOf(q(D + ' .rd-chip'), ['paddingTop', 'paddingLeft', 'fontSize']),
    warn: csOf(q(D + ' .rd-warn'), ['paddingTop', 'fontSize', 'borderTopWidth', 'backgroundColor']),
    steps: csOf(q(D + ' .rd-steps'), ['display', 'columnGap', 'marginBottom']),
  }
  return JSON.stringify({
    drawerContent: !!q(D),
    drawerTitle: norm(q('.ant-drawer-title')?.textContent || ''),
    detailGrid: qa(D + ' .rd-detail-grid').length,
    detailCol: qa(D + ' .rd-detail-col').length,
    section: sections.length,
    sectionHeads: sections.map(e => norm(e.querySelector('h4')?.textContent || '')).filter(Boolean),
    kv: qa(D + ' .rd-kv').length,
    warn: qa(D + ' .rd-warn').length,
    tip: qa(D + ' .rd-tip').length,
    steps: qa(D + ' .rd-steps').length,
    block: qa(D + ' .rd-block').length,
    chips: qa(D + ' .rd-chips').length,
    chipDesc: qa(D + ' .rd-chip-desc').length,
    buttons: [...new Set(qa(D + ' button').map(b => norm(b.textContent)).filter(Boolean))].sort(),
    styles,
  })
})()`

const OPEN_DRAWER = `
(() => {
  const btn = document.querySelector('.rd-root .rd-act-open')
  if (!btn) return JSON.stringify({ ok: false, nButtons: document.querySelectorAll('.rd-root button').length })
  const text = (btn.textContent || '').trim()
  btn.click()
  return JSON.stringify({ ok: true, text })
})()`

/** 连采两遍并比对 —— 基线必须自证可复读。 */
const twoPass = async (name, expr) => {
  const a = await run(expr)
  await sleep(420)
  const b = await run(expr)
  let pa, pb
  try { pa = JSON.parse(a) } catch { pa = { __raw: String(a) } }
  try { pb = JSON.parse(b) } catch { pb = { __raw: String(b) } }
  const same = JSON.stringify(pa) === JSON.stringify(pb)
  check(`S:${name}`, '采样可复读（同状态连采两遍一致）', same, { a: pa, b: pb })
  return pa
}

/** 等抽屉里的「处置」区块**就绪** —— 出现状态标签才算异步数据回来了（否则是加载中/空壳）。 */
const waitDrawerReady = async (timeoutMs = 15000) => {
  const probe = `(() => {
    const hs = [...document.querySelectorAll('.ant-drawer-content .rd-section h4')].map(e => (e.textContent || ''))
    return hs.some(t => t.includes('处置') && /待批准|已批准|已核准|已驳回|待执行|已完成|已发出/.test(t))
  })()`
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    if ((await run(probe)) === true) return true
    await sleep(400)
  }
  return false
}

// ---------------------------------------------------------------- B0 自检
let bodyLen = 0
for (let i = 0; i < 40; i++) {
  bodyLen = (await run('document.body?.innerText?.length || 0')) || 0
  if (bodyLen > 200) break
  await sleep(500)
}
check('B0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

const agentHit = JSON.parse(await run(clickByText('智能客服')))
check('B0b', '侧栏能点到「智能客服」', agentHit.ok === true, agentHit)
await sleep(1500)

const toolHit = JSON.parse(await run(clickByText('差评台账')))
await sleep(1800)
check('B0c', '能点到「差评台账」入口卡片', toolHit.ok === true, toolHit)

// ══════════════════════════════════════════════════════════════════════
// ★ 判据模型 —— 第一版按「脑中的结构」写死，实测当场打红两处，记在这里防复发：
//   · `.rd-filter` 其实有**两个**：源码 L39（`view !== 'ledger'`，时间窗 + 星级）与
//     L120（配 risk-bar `v-if` 的 `v-else`，状态筛选 + 【生成待处置】）
//     ⇒ recent/ledger 各 1 个、orphan/rules 各 2 个。第一版断言 ledger `filter=false` ⇒ 错。
//   · 主内容是**单条 v-if/v-else-if 链**（L161→163→167→182→251→306）：
//     hint/ledger/rules/list **互斥**，走哪一支由 `hasRows`（数据）决定。
//     ⇒ 不能写死「orphan 一定 list」；空数据时它走 `.rd-hint`。第一版断言 `list=true` ⇒ 错。
//   · `.rd-list` 是**卡片**（`.rd-item`）不是 table ⇒ `.rd-list tbody tr` 恒 0；
//     真正的「行」判据在 ledger / rules 的 `table.rd-table`。
// ══════════════════════════════════════════════════════════════════════
const exclusivity = (s) => s.main?.exclusiveCount === 1

/** 从捕获结果里取一条计算样式读数 —— 用于「读数真的抓到了东西」的自检。
 *  ★ 没有这层自检，选择器写错 ⇒ styles 全 null ⇒ 拆完 null === null 照样「一致」= 假绿。 */
const st = (o, group, prop) => o?.styles?.[group]?.[prop]

// ---------------------------------------------------------------- B1 默认视图
const stDefault = await twoPass('default', CAPTURE)
check('B1', '默认落在「近期差评」：risk-bar 在场、主内容互斥链恰好一支、ledger/rules 均不在场',
  stDefault.root === true && stDefault.riskBar === true && exclusivity(stDefault)
  && stDefault.main.ledger === false && stDefault.main.rules === false, stDefault)
// ★ 实测并回源码核实：recent 视图下 filter **是 2 个**（第一版断言 1 个 ⇒ 错）。
//   原因：L120 的 `v-else` 配对的**不是** L67 的 risk-bar `v-if`（中间隔着 L103 / L111 两个 alert 的 v-if），
//   而是紧邻的 L111 `<a-alert v-if="view === 'recent' && riskError">`。
//   ⇒ 只要 riskError 为空，`v-else` 就成立 ⇒ 台账专用的「状态筛选 + 生成待处置」块
//     也会渲染到 recent / orphan / rules 视图；ledger 下 L39 不出现 ⇒ 只剩 1 个。
//   ★ 这是**拆前既有行为**，本基线如实记录（重构须保持一致；是否该修正另开一轮）。
check('B1b', 'recent 视图 filter = 2（L39 时间窗型 + L120 状态/生成待处置型并存，见上方说明）',
  stDefault.filterCount === 2 && stDefault.filterHasTimeWindow === true && stDefault.filterHasGenerate === true,
  { filterCount: stDefault.filterCount, tw: stDefault.filterHasTimeWindow, gen: stDefault.filterHasGenerate })
// ★ 这里必须用**严格相等**：第一版写 `labels0[i].includes(w)`，反向注入
//   `label: '处置台账' -> '处置台账ZZ'` 时**照样 PASS**（`'处置台账ZZ'.includes('处置台账')` 为真）
//   ⇒ 变异抓不到、探针等于没牙齿。改用不含 icon / 计数的纯文案 + 严格相等。
const labels0 = (stDefault.tabs || []).map((t) => t.pure)
const want = ['近期差评', '未关联产品', '处置台账', '补偿规则']
check('B1c', '四个 tab 纯文案与顺序 = [近期差评, 未关联产品, 处置台账, 补偿规则]（严格相等）',
  labels0.length === 4 && want.every((w, i) => labels0[i] === w), labels0)
check('B1d', '激活态恰好一个、且落在第 1 个 tab',
  (stDefault.tabs || [])[0]?.active === true && (stDefault.tabs || []).filter((t) => t.active).length === 1,
  (stDefault.tabs || []).map((t) => ({ l: t.label, a: t.active })))
// ★★ 自检（default 视图）：差评列表卡片 = **没有表格**的那一支，这里证明列表侧的计算样式也真抓到了。
//   非表格视图（recent/orphan）此前 styles 全 null ⇒ 拆/改只覆盖了表格，列表侧是盲区。
//   ★ 条件化：空数据时走 .rd-hint，此时没有 .rd-list（本检查如实说明「本轮无卡片可比」）。
check('B1e', '差评列表卡片计算样式非空且为预期特征值（.rd-list 列向 flex / .rd-item 圆角·内边距 / .rd-body 12px / risk-bar flex）',
  stDefault.main?.list !== true || (
    st(stDefault, 'list', 'display') === 'flex'
    && st(stDefault, 'list', 'rowGap') === '6px'
    && st(stDefault, 'item', 'paddingTop') === '8px'
    && st(stDefault, 'item', 'borderTopLeftRadius') === '6px'
    && st(stDefault, 'itemTop', 'alignItems') === 'center'
    && st(stDefault, 'body', 'fontSize') === '12px'
    && st(stDefault, 'riskBarBox', 'display') === 'flex'
  ),
  { hasList: stDefault.main?.list, list: stDefault.styles?.list, item: stDefault.styles?.item, body: stDefault.styles?.body, riskBarBox: stDefault.styles?.riskBarBox })
await shot('default')

// ---------------------------------------------------------------- B2 orphan 视图
const swOrphan = JSON.parse(await run(switchView('未关联产品')))
await sleep(1300)
const stOrphan = await twoPass('orphan', CAPTURE)
check('B2', '「未关联产品」：risk-bar 退场（风险扫描只在近期差评视图）、主内容互斥链恰好一支',
  swOrphan.ok === true && stOrphan.riskBar === false && exclusivity(stOrphan),
  { swOrphan, riskBar: stOrphan.riskBar, exclusive: stOrphan.main?.exclusiveCount, main: stOrphan.main })
check('B2b', '非 recent 视图下 filter 为 2 个（时间窗型 + 状态/生成待处置型并存）',
  stOrphan.filterCount === 2 && stOrphan.filterHasGenerate === true,
  { filterCount: stOrphan.filterCount, gen: stOrphan.filterHasGenerate })
await shot('orphan')

// ---------------------------------------------------------------- B3 ledger 视图
const swLedger = JSON.parse(await run(switchView('处置台账')))
await sleep(1300)
const stLedger = await twoPass('ledger', CAPTURE)
check('B3', '「处置台账」：ledger 在场、risk-bar 退场、主内容互斥链恰好一支',
  swLedger.ok === true && stLedger.main?.ledger === true && stLedger.riskBar === false && exclusivity(stLedger),
  { swLedger, main: stLedger.main, riskBar: stLedger.riskBar })
check('B3b', '台账视图 filter 恰好 1 个（只剩 L120 状态型）、9 列表头、表内有行',
  stLedger.filterCount === 1 && stLedger.filterHasGenerate === true && stLedger.ledgerCols === 9
  && stLedger.ledgerRows > 0,
  { filterCount: stLedger.filterCount, cols: stLedger.ledgerCols, rows: stLedger.ledgerRows })
// ★★ 自检：证明台账表的计算样式**真的抓到了**（选择器没错）—— 这是拆子组件后比对的牙齿。
//   ★ 铁律教训（第 341 轮实测）：**读数抓到了 ≠ 判据会红**。第一版只断言了 th.fontWeight，
//     而注入「`.rd-table th,` 选择器失效」时表头 padding 4px→0px、textAlign left→center、
//     border 1px→0px 全变了，判据却**照样 PASS**（fontWeight 来自另一条幸存的 `.rd-table th{}`）。
//     ⇒ 判据必须把**所有**已抓到的字段逐条断言，否则就是留了盲区的假门禁。
check('B3c', '台账表计算样式非空且为预期特征值（nowrap·collapse·12px / th:4px·6px·600·left·1px / td:4px·6px·1px / act:sticky·0px·1px·left / actBtn:2px / 外框 6px）',
  st(stLedger, 'table', 'borderCollapse') === 'collapse'
  && st(stLedger, 'table', 'whiteSpace') === 'nowrap'
  && st(stLedger, 'table', 'fontSize') === '12px'
  && st(stLedger, 'th', 'paddingTop') === '4px'
  && st(stLedger, 'th', 'paddingLeft') === '6px'
  && st(stLedger, 'th', 'fontWeight') === '600'
  && st(stLedger, 'th', 'textAlign') === 'left'
  && st(stLedger, 'th', 'borderBottomWidth') === '1px'
  && st(stLedger, 'td', 'paddingTop') === '4px'
  && st(stLedger, 'td', 'paddingLeft') === '6px'
  && st(stLedger, 'td', 'borderBottomWidth') === '1px'
  && st(stLedger, 'act', 'position') === 'sticky'
  && st(stLedger, 'act', 'right') === '0px'
  && st(stLedger, 'act', 'borderLeftWidth') === '1px'
  && st(stLedger, 'act', 'textAlign') === 'left'
  && st(stLedger, 'actBtn', 'paddingLeft') === '2px'
  && st(stLedger, 'ledger', 'borderRadius') === '6px',
  { table: stLedger.styles?.table, th: stLedger.styles?.th, td: stLedger.styles?.td, act: stLedger.styles?.act, actBtn: stLedger.styles?.actBtn, ledger: stLedger.styles?.ledger })
await shot('ledger')

// ---------------------------------------------------------------- B4 rules 视图
const swRules = JSON.parse(await run(switchView('补偿规则')))
await sleep(1300)
const stRules = await twoPass('rules', CAPTURE)
check('B4', '「补偿规则」：rules 在场、risk-bar 退场、主内容互斥链恰好一支',
  swRules.ok === true && stRules.main?.rules === true && stRules.riskBar === false && exclusivity(stRules),
  { swRules, main: stRules.main, riskBar: stRules.riskBar })
check('B4b', '规则视图 filter 2 个、9 列表头（金额规则的唯一落点）',
  stRules.filterCount === 2 && stRules.rulesCols === 9,
  { filterCount: stRules.filterCount, cols: stRules.rulesCols })
// ★★ 自检：规则表与台账表**共享** .rd-table 那一段 scoped 样式（源码 L2287-2337）
//   ⇒ 拆 rules 表为子组件后这一段最容易静默失配，必须有读数才有牙齿。
//   ruleCond 的 white-space 是**冲突值**：.rd-table 给 nowrap，.rd-rule-cond 显式改回 normal
//   —— 若子组件丢了 .rd-rule-cond，它会被 nowrap 接管，恰恰是最灵敏的探针。
//   （ruleCond 只在表内有行时才存在 ⇒ 无行时不参与判定，避免因数据为空而假红。）
check('B4c', '规则表计算样式非空且为预期特征值（共享段同台账 + .rd-rule-cond 把 white-space 从 nowrap 改回 normal + .rd-rules 列向 flex）',
  st(stRules, 'table', 'borderCollapse') === 'collapse'
  && st(stRules, 'table', 'whiteSpace') === 'nowrap'
  && st(stRules, 'table', 'fontSize') === '12px'
  && st(stRules, 'th', 'paddingTop') === '4px'
  && st(stRules, 'th', 'paddingLeft') === '6px'
  && st(stRules, 'th', 'fontWeight') === '600'
  && st(stRules, 'th', 'textAlign') === 'left'
  && st(stRules, 'th', 'borderBottomWidth') === '1px'
  && st(stRules, 'td', 'paddingTop') === '4px'
  && st(stRules, 'td', 'borderBottomWidth') === '1px'
  && st(stRules, 'act', 'position') === 'sticky'
  && st(stRules, 'act', 'right') === '0px'
  && st(stRules, 'act', 'borderLeftWidth') === '1px'
  && st(stRules, 'actBtn', 'paddingLeft') === '2px'
  && st(stRules, 'rulesWrap', 'display') === 'flex'
  && st(stRules, 'rulesWrap', 'flexDirection') === 'column'
  && (stRules.rulesRows > 0 ? st(stRules, 'ruleCond', 'whiteSpace') === 'normal' : true),
  { rows: stRules.rulesRows, table: stRules.styles?.table, th: stRules.styles?.th, td: stRules.styles?.td,
    act: stRules.styles?.act, actBtn: stRules.styles?.actBtn, ruleCond: stRules.styles?.ruleCond, rulesWrap: stRules.styles?.rulesWrap })
await shot('rules')

// ------------------------------ B4d~g 规则表动作接线（子组件事件契约，第 342 轮补）
// ★★ 为什么必须**真点**（而不是继续只采结构）：
//   规则表拆成 `ReviewDeskRulesTable.vue` 后，3 个动作从「直接调父函数」改成
//   `emit('edit'|'toggle'|'remove')`。只要 emit 名与父组件的 `@edit`/`@toggle`/`@remove`
//   对不上，按钮就**静默失效** —— 而 DOM 数量、class、行数、行高、计算样式**一概不变**
//   ⇒ B4 / B4b / B4c 一律照样绿，这条缺口正是上一刀（1426b74）如实记下的。
// ★ 三个动作「不落共享库」的测法：
//   · edit   —— 纯前端（`openRuleEdit` 只填表单、不打接口）⇒ 直接点，零副作用。
//   · toggle —— 打 `PATCH /trade/compensation-rules/{id}`。
//   · remove —— 打 `DELETE /trade/compensation-rules/{id}`，且 emit 挂在 popconfirm 的
//               `@confirm` 上 ⇒ 必须先点【删除】让它弹出，再点【确定】。
//   后两者用 `Network.setBlockedURLs` 把写请求在浏览器层拦掉：请求**发不出去**、库**不变**，
//   而 `Network.requestWillBeSent` 仍会触发 ⇒ 既能证接线通、又不动数据。
//   ★ 拦截是**全局**的：本段之内**只准**点这三处；结束立刻解封再进 B5，
//     否则会把抽屉的取数请求一起挡掉（症状＝B5a 伪红，看起来像限流降级）。
// ★ 断言取「请求真的发出了」（sentLog）而**不是**「页面没报错」：拦掉后前端必然 message.error，
//   判「有没有报错」等于恒真 —— 那是 fail-open 的假门禁。
// ★ 也不取「点击后行数变了」：拦掉后本来就不该变，这条既不能证通也不能证不通。
const WRITE_BLOCK = ['*/api/v1/trade/compensation-rules/*']
const isRuleWrite = (x) => /^\/trade\/compensation-rules\//.test(x.path) && x.m !== 'GET'
/** 把路径末段的资源 id 归一化（基线要能跨 seed 复跑，不能钉死某条规则的 uuid）。 */
const normPath = (p) => (p ? p.replace(/\/[^/]+$/, '/<id>') : null)

/** 读规则表**第一行**：行数 / code / 动作按钮清单 / 是否有启停开关。 */
const READ_RULE_ROW = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const t = document.querySelector('.rd-root .rd-rules table.rd-table')
  if (!t) return JSON.stringify({ table: false })
  const tr = t.querySelector('tbody tr')
  if (!tr) return JSON.stringify({ table: true, rows: 0 })
  const codeEl = tr.querySelector('td code')
  return JSON.stringify({
    table: true,
    rows: t.querySelectorAll('tbody tr').length,
    code: codeEl ? norm(codeEl.textContent) : '',
    actBtns: [...tr.querySelectorAll('.rd-table-act button')].map(b => norm(b.textContent)),
    hasSwitch: !!tr.querySelector('td .ant-switch'),
  })
})()`

/** 在规则表第一行里按**精确文案**点动作按钮。
 *  ★ 必须限定在 `.rd-rules` 内：全页第一个 `.rd-table-act .ant-btn` 是**台账表**的。 */
const clickRuleAct = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const t = document.querySelector('.rd-root .rd-rules table.rd-table')
  if (!t) return JSON.stringify({ ok: false, why: 'no rules table' })
  const tr = t.querySelector('tbody tr')
  if (!tr) return JSON.stringify({ ok: false, why: 'no row' })
  const btns = [...tr.querySelectorAll('.rd-table-act button')]
  const hit = btns.find(b => norm(b.textContent) === ${JSON.stringify(label)})
  if (!hit) return JSON.stringify({ ok: false, why: 'no btn', have: btns.map(b => norm(b.textContent)) })
  hit.click()
  return JSON.stringify({ ok: true })
})()`

/** 读当前**可见**的规则编辑弹窗。
 *  ★ 必须过滤 `display !== none`：a-modal 关掉后 DOM 仍在，只看 `.ant-modal` 会拿到**残留**。 */
const READ_RULE_MODAL = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const wraps = [...document.querySelectorAll('.ant-modal-wrap')].filter(w => getComputedStyle(w).display !== 'none')
  const w = wraps[0] || null
  const form = w ? w.querySelector('.rd-rule-form') : null
  const input = form ? form.querySelector('input') : null
  return JSON.stringify({
    visible: wraps.length,
    form: !!form,
    title: w ? norm(w.querySelector('.ant-modal-title')?.textContent || '') : '',
    codeValue: input ? input.value : null,
    codeDisabled: input ? input.disabled === true : null,
  })
})()`

/** 关掉规则编辑弹窗：点 footer 里**非 primary** 的那个（= 取消）。
 *  ★ 不按文案点：antd 会在两个 CJK 字之间插空格（「取 消」）⇒ 精确文案匹配必然落空。 */
const CLOSE_RULE_MODAL = `
(() => {
  const wraps = [...document.querySelectorAll('.ant-modal-wrap')].filter(w => getComputedStyle(w).display !== 'none')
  const w = wraps[0]
  if (!w) return JSON.stringify({ ok: true, alreadyClosed: true })
  const btns = [...w.querySelectorAll('.ant-modal-footer button')]
  const cancel = btns.find(b => !b.classList.contains('ant-btn-primary')) || btns[0]
  if (!cancel) return JSON.stringify({ ok: false, why: 'no footer button', have: btns.map(b => (b.textContent || '').trim()) })
  cancel.click()
  return JSON.stringify({ ok: true, closedBy: (cancel.textContent || '').trim() })
})()`

/** 点规则表第一行的启停开关（写请求会被拦掉）。 */
const CLICK_RULE_SWITCH = `
(() => {
  const t = document.querySelector('.rd-root .rd-rules table.rd-table')
  const tr = t ? t.querySelector('tbody tr') : null
  const sw = tr ? tr.querySelector('td .ant-switch') : null
  if (!sw) return JSON.stringify({ ok: false, why: 'no switch' })
  sw.click()
  return JSON.stringify({ ok: true })
})()`

/** 读当前**可见**的 popconfirm（文案 + 是否有确定按钮）。 */
const READ_POPCONFIRM = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const ps = [...document.querySelectorAll('.ant-popover')]
    .filter(p => !p.classList.contains('ant-popover-hidden') && getComputedStyle(p).display !== 'none')
  const p = ps[0] || null
  return JSON.stringify({
    visible: ps.length,
    text: p ? norm(p.textContent || '') : '',
    confirmFound: !!p && !!p.querySelector('.ant-popconfirm-buttons .ant-btn-primary'),
  })
})()`

/** 点 popconfirm 的【确定】—— 这一步才触发 emit('remove')。 */
const CONFIRM_POPCONFIRM = `
(() => {
  const ps = [...document.querySelectorAll('.ant-popover')]
    .filter(p => !p.classList.contains('ant-popover-hidden') && getComputedStyle(p).display !== 'none')
  const b = ps[0] ? ps[0].querySelector('.ant-popconfirm-buttons .ant-btn-primary') : null
  if (!b) return JSON.stringify({ ok: false, why: 'no confirm btn' })
  b.click()
  return JSON.stringify({ ok: true })
})()`

const ruleRow = JSON.parse(await run(READ_RULE_ROW))

let rulesAct = { skipped: 'no-rule-rows' }
if (ruleRow.rows === 0) {
  // ★ 与 B5 同惯例：**数据条件**达不到就如实 SKIP，不伪装成代码回归。
  check('B4d0', '规则表动作接线（当前规则表无行 ⇒ 无法验证，如实 SKIP）', null, ruleRow)
} else {
  check('B4d0', '规则表前置：有行、行内有【编辑】【删除】按钮与启停开关（拆成子组件后动作按钮仍渲染）',
    ruleRow.table === true && ruleRow.code !== ''
    && (ruleRow.actBtns || []).includes('编辑') && (ruleRow.actBtns || []).includes('删除')
    && ruleRow.hasSwitch === true,
    ruleRow)

  // ---- B4d：edit（纯前端，零副作用）
  const editClick = JSON.parse(await run(clickRuleAct('编辑')))
  let rModal = null
  for (let i = 0; i < 25; i++) {
    rModal = JSON.parse(await run(READ_RULE_MODAL))
    if (rModal.form) break
    await sleep(300)
  }
  check('B4d', '点规则表【编辑】⇒ 编辑弹窗出现（证明子组件 emit(edit) 接到了父组件 openRuleEdit）',
    editClick.ok === true && rModal.form === true, { click: editClick, modal: rModal })
  check('B4d2', '弹窗标题 = 「编辑补偿规则 · <被点那一行的 code>」且 code 已回填并只读（参数就是那一行，不是别的行）',
    rModal.form === true && ruleRow.code !== ''
    && rModal.title === `编辑补偿规则 · ${ruleRow.code}`
    && rModal.codeValue === ruleRow.code && rModal.codeDisabled === true,
    { wantTitle: `编辑补偿规则 · ${ruleRow.code}`, gotTitle: rModal?.title,
      wantCode: ruleRow.code, gotCode: rModal?.codeValue, disabled: rModal?.codeDisabled })
  const closeRes = JSON.parse(await run(CLOSE_RULE_MODAL))
  await sleep(700)
  const modalAfter = JSON.parse(await run(READ_RULE_MODAL))
  check('B4d3', '编辑弹窗已关闭（证据收干净：残留的 modal 会污染后面的抽屉读数）',
    closeRes.ok === true && modalAfter.visible === 0 && modalAfter.form === false,
    { close: closeRes, after: modalAfter })
  await shot('rules-act-edit')

  // ---- B4e：toggle（写请求拦截，不落库）
  await send('Network.setBlockedURLs', { urls: WRITE_BLOCK })
  sentLog.length = 0
  const swToggle = JSON.parse(await run(CLICK_RULE_SWITCH))
  await sleep(1500)
  const toggleReqs = sentLog.filter(isRuleWrite)
  await send('Network.setBlockedURLs', { urls: [] })
  let toggleBody = null
  try { toggleBody = toggleReqs[0]?.body ? JSON.parse(toggleReqs[0].body) : null } catch { toggleBody = null }
  check('B4e', '点规则表【启用】开关 ⇒ 恰好对**本行**发起 1 个 PATCH（body 为 {enabled:布尔}）——证明 emit(toggle) 接到了 toggleRule',
    swToggle.ok === true && toggleReqs.length === 1 && toggleReqs[0].m === 'PATCH'
    && typeof toggleBody?.enabled === 'boolean',
    { click: swToggle, reqs: toggleReqs, body: toggleBody })

  // ---- B4f / B4g：remove（emit 挂在 popconfirm 的 @confirm 上；同样拦截）
  await send('Network.setBlockedURLs', { urls: WRITE_BLOCK })
  sentLog.length = 0
  const delClick = JSON.parse(await run(clickRuleAct('删除')))
  await sleep(900)
  const pop = JSON.parse(await run(READ_POPCONFIRM))
  // ★ 关键判据：**点确定之前**应当零写请求 —— 这条同时钉住「emit 挂在 @confirm 上」这个契约。
  const beforeConfirm = sentLog.filter((x) => x.m !== 'GET').length
  const confirmClick = JSON.parse(await run(CONFIRM_POPCONFIRM))
  await sleep(1500)
  const delReqs = sentLog.filter(isRuleWrite)
  await send('Network.setBlockedURLs', { urls: [] })
  check('B4f', '点规则表【删除】⇒ popconfirm 弹出（含「确定删除这条规则」）且**点确定前零写请求**（证明 emit 挂在 @confirm 上，不是挂在点击上）',
    delClick.ok === true && pop.visible === 1 && pop.text.includes('确定删除这条规则')
    && pop.confirmFound === true && beforeConfirm === 0,
    { click: delClick, pop, beforeConfirm })
  check('B4g', '点 popconfirm【确定】⇒ 恰好对**本行**发起 1 个 DELETE —— 证明 emit(remove) 接到了 removeRule',
    confirmClick.ok === true && delReqs.length === 1 && delReqs[0].m === 'DELETE' && delReqs[0].id !== '',
    { confirm: confirmClick, delReqs })
  // ★ 「两次请求打到**同一行**」单独成条，且**只在 B4e 也拿到 PATCH 时**才判（否则 null = SKIP）。
  //   为什么必须拆开：第一版把 `id === toggleReqs[0]?.id` 写在 B4g 里，实测注入
  //   「toggle 的 emit 改名」时 **B4g 也转红** —— 可 remove 其实好好的。
  //   ⇒ 归因被指错方向（本仓铁律：FAIL 行必须指向真正坏掉的那一处）。B4e 坏时本条如实 SKIP。
  check('B4g2', '【启用】与【删除】打到**同一行**（两次写请求的资源 id 相同）—— 证明行内动作没串到别的行',
    toggleReqs.length === 1 && delReqs.length === 1 ? delReqs[0].id === toggleReqs[0].id : null,
    { toggleId: toggleReqs[0]?.id, delId: delReqs[0]?.id, note: 'B4e 未拿到 PATCH ⇒ 条件化 SKIP' })

  rulesAct = {
    rowCode: ruleRow.code,
    actBtns: ruleRow.actBtns,
    hasSwitch: ruleRow.hasSwitch,
    modalTitle: rModal?.title || null,
    codeBackfilled: rModal?.codeValue === ruleRow.code,
    codeReadonly: rModal?.codeDisabled === true,
    // ★ 存**归一化**路径（id → <id>）：基线要能跨 seed 复跑，不钉死某条规则的 uuid
    toggle: { m: toggleReqs[0]?.m || null, path: normPath(toggleReqs[0]?.path), body: toggleBody },
    remove: { m: delReqs[0]?.m || null, path: normPath(delReqs[0]?.path) },
    popTextHasDeleteConfirm: pop.text.includes('确定删除这条规则'),
  }
}

// ---------------------------------------------------------------- B5 抽屉（从台账打开）
// ★ 第一版漏了这一步：B4 结束时视图停在 rules，直接找 `.rd-act-open` 找不到 ⇒ 误报 SKIP。
//   抽屉入口长在**台账行**上，必须先切回台账。
await run(switchView('处置台账'))
await sleep(1400)
let drawer = null
const od = JSON.parse(await run(OPEN_DRAWER))
if (!od.ok) {
  check('B5', '抽屉结构（当前台账无行/无动作按钮 ⇒ 无法验证，如实 SKIP）', null, od)
} else {
  // ★★ 关键：抽屉内的「处置」区块是**异步拉回来的**（openDispositionDetail 打后端）。
  //   第一版固定 sleep 1300ms 就采 ⇒ run1 采到完整态、run2 采到残缺态（**同一行**！），
  //   表现为 kv 4→2、block 4→0 —— 差点被当成「行为变了」。
  //   ⇒ 必须**等就绪**：处置区块出现状态标签（待批准 / 已核准 / …）才算加载完成。
  const ready = await waitDrawerReady()
  check('B5a', '抽屉数据就绪（「处置」区块带状态标签，非加载中/空壳）', ready,
    { ready, rateHits: rateHits.length, net: netLog.filter(n => /reviews|disposition/.test(n.path || '')).slice(-8) })
  drawer = await twoPass('drawer', CAPTURE_DRAWER)
  check('B5', `抽屉已开（点「${od.text}」，标题「${drawer.drawerTitle}」）且左右两栏 + 详情容器在场`,
    drawer.drawerContent === true && drawer.detailGrid === 1 && drawer.detailCol === 2
    && String(drawer.drawerTitle).startsWith('差评处置'), drawer)
  // ★ 通道相关容器（.rd-block / .rd-chips）**随该行的处置状态出现**（待批准 / 已驳回才有通道编辑）
  //   ⇒ 只记录进基线、不单独判 —— 写死会因数据变动而假红。
  check('B5b', '抽屉标题为「差评处置 · …」且左右两栏结构正确（通道区块随状态出现，仅记录）',
    String(drawer.drawerTitle).startsWith('差评处置') && drawer.detailCol === 2,
    { title: drawer.drawerTitle, cols: drawer.detailCol, block: drawer.block, chips: drawer.chips, kv: drawer.kv })
  // ★★ 自检：抽屉内计算样式也真的抓到了（.rd-detail-grid 两栏 flex / .rd-detail-col 的 flex:1 1 0 + min-width:0）。
  //   ★ 实测：`flex: 1 1 0` 里的单位零被计算成 **0px**（不是 0%）—— 第一版按 0% 断言 ⇒ 假红。
  check('B5c', '抽屉计算样式非空且为预期特征值（两栏 display:flex / col 的 flex:1 1 0 与 min-width:0）',
    st(drawer, 'grid', 'display') === 'flex'
    && st(drawer, 'grid', 'alignItems') === 'flex-start'
    && st(drawer, 'grid', 'columnGap') === '20px'
    && st(drawer, 'col', 'flexGrow') === '1'
    && st(drawer, 'col', 'flexBasis') === '0px'
    && st(drawer, 'col', 'minWidth') === '0px',
    { grid: drawer.styles?.grid, col: drawer.styles?.col })
  await shot('drawer')
}

// ---------------------------------------------------------------- 落盘
const baseline = {
  default: stDefault, orphan: stOrphan, ledger: stLedger, rules: stRules, rulesAct, drawer,
}
const payload = {
  meta: {
    tag: TAG, url: URL, at: new Date().toISOString(),
    chrome: CHROME, port: PORT, identity: who,
    rateHits: rateHits.slice(0, 10),
    netTail: netLog.slice(-30),
    note: '拆 ReviewDeskConfig.vue（抽 composable）的行为基线；比对时只比 baseline 字段，忽略 meta。',
  },
  baseline,
  checks: results,
}
writeFileSync(OUT_FILE, JSON.stringify(payload, null, 2))

clearTimeout(watchdog)
try { chrome.kill() } catch { /* ignore */ }

const nPass = results.filter((r) => r.state === 'PASS').length
const nFail = results.filter((r) => r.state === 'FAIL').length
const nSkip = results.filter((r) => r.state === 'SKIP').length
if (!stDefault.root) {
  console.log('\nNOTE: .rd-root 未挂出 —— 后续读数无意义。先查：身份注入是否生效 / 侧栏「智能客服」+「差评台账」链路是否可达。')
}
console.log(`\n汇总：PASS=${nPass} FAIL=${nFail} SKIP=${nSkip} / 共 ${results.length}`)
console.log(`基线已落盘：${OUT_FILE}`)
process.exit(nFail ? 1 : 0)

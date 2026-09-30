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
//   6. 抽屉结构（detail-grid / section / kv / block / chips 的计数）。
//   ★ 刻意**不**钉：DOM 顺序、style 属性、行内容文案 —— 那些会随 seed 变，
//     钉住它们只会让基线自己变得易碎。
//
// ============================================================================
// ★ 两条本仓纪律
// ============================================================================
//   · **先注入真身份**（`access_token` 必须是非 demo 的真 JWT，`isRealLogin` 才为真）：
//     不注入 ⇒ 首屏带空 token 打一轮 401，面板可能挂不出来，表现为「全红」——
//     那是**注入失败**，不是功能坏了，报告时必须区分这两件事。
//   · **基线要自证可复读**：每个状态**连采两遍**，两遍不等就当场 FAIL
//     （读数不稳定 ⇒ 这样的基线拿去做比对只会制造假红）。
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
await shot('rules')

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
  await shot('drawer')
}

// ---------------------------------------------------------------- 落盘
const baseline = {
  default: stDefault, orphan: stOrphan, ledger: stLedger, rules: stRules, drawer,
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

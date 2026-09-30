// CDP 真机判据（第 299 轮 P1）：差评工作台「风险识别 → 标红置顶」必须在**真浏览器**上成立。
//
// 为什么需要真机判据（而不是只看单测 / 门禁）
// ------------------------------------------
// 后端单测证明「算得对」、静态门禁证明「代码里调了那个 api」，
// 但都证明不了**界面上真的渲染出来了、顺序真的跟着后端走**。本仓反复踩过
// 「后端有端点 ≠ 前端在用 ≠ 接上了会渲染」。
//
// ★ 这一跑就抓到了两个真问题（都不是单测能发现的）：
//   ① 探针自身口径错：后端对账用了 days=3650 而面板用的是 days=30，
//      拿两个不同窗口比 ⇒ 假红。（已改成「拦截面板真实请求的 URL，再用它去对账」）
//   ② 真缺陷：定论 `clean` 但命中 r5 的卡片照样渲染证据块，而块里的类别名
//      （`.rd-risk-hit-cat` 用 `--danger-strong`）是**红字** ⇒ 干净卡片挂红字。
//      已加 `showRiskEvidence` 守卫 + 门禁 R11，本探针用 T19 在真机上钉住。
//
// 判据分四组，每组都配一条能转红的反向判据：
//   ① 真实数据：chip 计数 / 皮肤数 / 卡片顺序 与 `/reviews/risk` **逐项对账**；
//   ② ★ 后端改序 ⇒ 页面必须跟着变（网络层把 items 逆序）；
//   ③ 标红：真实库四类风险零正样本 ⇒ 网络层塞一条合成正例，验红皮 + 🛡 标签；
//   ④ 降级：`degraded=true` 时警示必须上屏。
// ★ ②③④ 全部在**网络层**做桩：不改库、不改列表、不动被测代码。
//
// 用法：node scripts/cdp-review-risk-view-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9391
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r299_risk_view')
const RISK_PATTERN = '*/trade/reviews/risk*'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r299-risk-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,1000',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking', 'about:blank',
], { stdio: 'ignore' })

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await r.json()
    if (targets.some((t) => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()

// ---- 网络层：只暂停风险端点（其余请求不经过我们，避免拖慢整页） ----
let stub = null            // { body: string } = 桩；null = 放行（但记录 URL）
let lastRiskUrl = null     // 面板**真实**发出的请求 URL（对账必须用它，不能自己猜参数）
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Fetch.requestPaused') {
    const { requestId, request } = m.params
    lastRiskUrl = request.url
    if (!stub) { send('Fetch.continueRequest', { requestId }).catch(() => {}); return }
    send('Fetch.fulfillRequest', {
      requestId,
      responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
      body: Buffer.from(stub.body, 'utf8').toString('base64'),
    }).catch(() => {})
  }
})

await new Promise((res, rej) => {
  ws.addEventListener('open', res)
  ws.addEventListener('error', rej)
})
const send = (method, params = {}) => new Promise((res) => {
  const i = ++seq
  pending.set(i, res)
  ws.send(JSON.stringify({ id: i, method, params }))
})
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400))
  return r?.result?.result?.value
}
const runJson = async (expr) => JSON.parse(await run(expr))
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const exact = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  const loose = all.filter(e => norm(e.textContent).includes(${JSON.stringify(label)}))
  const pool = exact.length ? exact : loose
  if (!pool.length) return JSON.stringify({ err: 'not found' })
  const target = pool.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, text: norm(target.textContent).slice(0, 40) })
})()`

const CLICK_RISK_BTN = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const btn = [...document.querySelectorAll('button')].find(b => norm(b.textContent).includes('风险识别'))
  if (!btn) return JSON.stringify({ err: 'no risk button' })
  if (btn.classList.contains('ant-btn-loading') || btn.disabled) return JSON.stringify({ err: 'busy' })
  btn.click()
  return JSON.stringify({ ok: true })
})()`

// 打开「时间窗」下拉（.rd-filter 里第一个 .rd-days）
const OPEN_WINDOW_SELECT = `
(() => {
  const sel = document.querySelector('.rd-filter .rd-days')
  if (!sel) return JSON.stringify({ err: 'no window select' })
  const box = sel.querySelector('.ant-select-selector') || sel
  box.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  box.click()
  return JSON.stringify({ ok: true })
})()`

const PICK_OPTION = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const opts = [...document.querySelectorAll('.ant-select-item-option')]
  const hit = opts.find(o => norm(o.textContent) === ${JSON.stringify(label)})
  if (!hit) return JSON.stringify({ err: 'no option', have: opts.map(o => norm(o.textContent)) })
  hit.click()
  return JSON.stringify({ ok: true, picked: norm(hit.textContent) })
})()`

const READ_PANEL = `(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const bar = document.querySelector('.rd-risk-bar')
  const chips = [...(bar ? bar.querySelectorAll('.rd-risk-chip') : [])].map(e => norm(e.textContent))
  const cards = [...document.querySelectorAll('.rd-item')].map(e => ({
    title: norm(e.querySelector('.rd-title')?.textContent),
    cls: [...e.classList].filter(c => c.startsWith('rd-risk-')),
    tags: [...e.querySelectorAll('.rd-item-top .ant-tag')].map(t => norm(t.textContent)),
    ev: norm(e.querySelector('.rd-risk-ev')?.textContent),
  }))
  const alerts = [...document.querySelectorAll('.rd-alert')].map(e => norm(e.textContent).slice(0, 160))
  return JSON.stringify({
    barExists: !!bar, chips, cards, alerts,
    tip: bar ? norm(bar.querySelector('.rd-risk-tip')?.textContent) : null,
  })
})()`

// 用**面板真实发出的** URL 去后端对账（页面上下文：同源、走 vite 代理）
const backendAt = (url) => `(async () => {
  const shop = localStorage.getItem('current_shop_id')
  const r = await fetch(${JSON.stringify(url)}, { headers: { 'X-Shop-ID': shop || '' } })
  const d = await r.json()
  return JSON.stringify({ ok: r.ok, shop: !!shop, status: r.status, d })
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(4200)

// ---------------------------------------------------------------- T0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('T0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// ---------------------------------------------------------------- 进入差评工作台
await run(clickByText('智能客服'))
await sleep(1700)
await run(clickByText('差评台账'))
await sleep(2600)
await run(clickByText('近期差评'))
await sleep(1800)

const opened = await runJson(READ_PANEL)
check('T1', '风险条已出现（默认落在「近期差评」视图）', opened.barExists === true, opened)
check('T2', '未点之前给的是**操作说明**（不是空计数）',
  typeof opened.tip === 'string' && opened.tip.includes('只读'), { tip: opened.tip })

// ★ 把时间窗切到「全部」：默认 30 天窗口里只有 1 条 ⇒ 顺序/置顶类判据会空跑
await send('Fetch.enable', { patterns: [{ urlPattern: RISK_PATTERN, requestStage: 'Request' }] })
await run(OPEN_WINDOW_SELECT)
await sleep(700)
const picked = await runJson(PICK_OPTION('全部'))
await sleep(2600)
const listed = await runJson(READ_PANEL)
check('T2b', '时间窗已切到「全部」（否则顺序判据没东西可比）',
  picked.ok === true && listed.cards.length >= 2,
  { picked, cards: listed.cards.length })

// ---------------------------------------------------------------- 点按钮 → 出计数
const btn = await runJson(CLICK_RISK_BTN)
check('T3', '【风险识别】按钮可点', btn.ok === true, btn)
for (let i = 0; i < 60; i++) {
  await sleep(500)
  const s = await runJson(READ_PANEL)
  if (s.chips.length) break
}
const after = await runJson(READ_PANEL)
check('T4', '点完按钮出现「风险 / 未定论 / 干净」三个计数',
  after.chips.length === 3, { chips: after.chips })

// ---------------------------------------------------------------- 后端对账（用面板真实 URL）
check('T4b', '拿到了面板真实发出的风险请求 URL（对账口径必须与面板一致）',
  typeof lastRiskUrl === 'string' && lastRiskUrl.includes('/trade/reviews/risk'),
  { lastRiskUrl })
const be = await runJson(backendAt(lastRiskUrl))
const beD = be.d || {}
check('T5', '后端同一 URL 可达且带店铺', be.ok === true && be.shop === true,
  { status: be.status, shop: be.shop, url: lastRiskUrl })

const num = (s) => Number((String(s).match(/(\d+)/) || [])[1])
const chipOf = (chips, label) => num((chips.find((c) => c.startsWith(label)) || ''))
check('T6', '★ chip 计数 == 后端 risk/unknown/clean 计数',
  chipOf(after.chips, '风险') === beD.risk_count
  && chipOf(after.chips, '未定论') === beD.unknown_count
  && chipOf(after.chips, '干净') === beD.clean_count,
  { page: { risk: chipOf(after.chips, '风险'), unknown: chipOf(after.chips, '未定论'), clean: chipOf(after.chips, '干净') },
    be: { risk: beD.risk_count, unknown: beD.unknown_count, clean: beD.clean_count } })

// ---------------------------------------------------------------- 顺序对账
const beTitles = (beD.items || []).map((x) => (x.title || '（无标题）').trim())
const domTitles = after.cards.map((c) => c.title)
const uniq = new Set(beTitles).size === beTitles.length
check('T7', '★ 页面卡片顺序 == 后端返回顺序（置顶的唯一真源在后端）',
  uniq && beTitles.length === domTitles.length
    ? JSON.stringify(domTitles) === JSON.stringify(beTitles) : null,
  { domTitles, beTitles, titlesUnique: uniq })

const RANK = { 'rd-risk-risk': 0, 'rd-risk-unknown': 1 }
const ranks = after.cards.map((c) => (c.cls.length ? RANK[c.cls[0]] ?? 9 : 2))
check('T8', '★ 皮肤「秩单调」：风险 → 未定论 → 干净（未定论不得沉到干净后面）',
  after.cards.length > 1 && ranks.every((r, i) => i === 0 || ranks[i - 1] <= r),
  { ranks, classes: after.cards.map((c) => c.cls[0] || '(无)') })

const countCls = (k) => after.cards.filter((c) => c.cls.includes(k)).length
const beDecR = (beD.items || []).filter((x) => x.risk?.decision === 'risk').length
const beDecU = (beD.items || []).filter((x) => x.risk?.decision === 'unknown').length
check('T9', '皮肤个数 == 后端各定论条数（界面没有自己造标记）',
  countCls('rd-risk-risk') === beDecR && countCls('rd-risk-unknown') === beDecU,
  { page: { risk: countCls('rd-risk-risk'), unknown: countCls('rd-risk-unknown') },
    be: { risk: beDecR, unknown: beDecU } })

const hasWarn = after.alerts.some((a) => a.includes('语义判定通道不可用'))
check('T10', '降级提示与后端 degraded 一致（不降级时不得出现）',
  hasWarn === Boolean(beD.degraded), { hasWarn, beDegraded: beD.degraded, alerts: after.alerts })

// ★ 干净卡片不得挂红字证据块（本轮修的缺陷）
const dirty = after.cards.filter((c) => !c.cls.includes('rd-risk-risk') && c.ev)
check('T11', '★【回归】干净 / 未定论以外的卡片不得挂证据块（红字类别名）',
  after.cards.length > 0 && dirty.every((c) => c.cls.includes('rd-risk-unknown')),
  { offenders: dirty.map((c) => ({ cls: c.cls[0] || '(无)', ev: c.ev.slice(0, 50) })) })

await shot('01-real-data')

// ---------------------------------------------------------------- ★ ② 后端改序 ⇒ 页面跟变
const reversed = JSON.parse(JSON.stringify(beD))
reversed.items = (reversed.items || []).slice().reverse()
stub = { body: JSON.stringify(reversed) }
await run(CLICK_RISK_BTN)
await sleep(2500)
const rev = await runJson(READ_PANEL)
const revBeTitles = reversed.items.map((x) => (x.title || '（无标题）').trim())
check('T12', '★【反向】后端把顺序反转 ⇒ 页面顺序必须跟着反转（前端没有自己排）',
  JSON.stringify(rev.cards.map((c) => c.title)) === JSON.stringify(revBeTitles),
  { dom: rev.cards.map((c) => c.title), be: revBeTitles })
check('T13', '空跑自检：反转后的顺序确实与原顺序不同',
  JSON.stringify(revBeTitles) !== JSON.stringify(beTitles), { revBeTitles, beTitles })
await shot('02-reversed')

// ---------------------------------------------------------------- ★ ③ 合成正例 ⇒ 标红
const synth = JSON.parse(JSON.stringify(beD))
let synthRan = false
if ((synth.items || []).length >= 2) {
  synthRan = true
  const victim = synth.items[synth.items.length - 1]   // 原本排最后的挪到第一位
  victim.risk = {
    decision: 'risk', level: 'high', level_label: '高危',
    suggested_action: '24h 内人工确认',
    is_risk: true, categories: ['r1'], risk_categories: ['r1'],
    hits: [{ category: 'r1', label: '威胁差评', level: 'high', channel: 'fuse',
             evidence: ['I will leave a 1-star review and tell everyone'], note: 'probe' }],
    channel: 'fuse', note: '',
  }
  synth.items = [victim, ...synth.items.filter((x) => x.id !== victim.id)]
  synth.risk_count = 1
  synth.unknown_count = 0
  synth.clean_count = synth.items.length - 1
  stub = { body: JSON.stringify(synth) }
  await run(CLICK_RISK_BTN)
  await sleep(2500)
  const s = await runJson(READ_PANEL)
  const first = s.cards[0] || { cls: [], tags: [], ev: '' }
  const expectTitle = (victim.title || '（无标题）').trim()
  check('T14', '★【合成正例】判 risk 的那条被置顶（顺序来自后端）',
    first.title === expectTitle, { firstTitle: first.title, expect: expectTitle })
  check('T15', '★【合成正例】红皮渲染出来（.rd-risk-risk）',
    first.cls.includes('rd-risk-risk'), { cls: first.cls })
  check('T16', '★【合成正例】🛡 风险标签渲染，且类别/等级名**取自后端**',
    first.tags.some((t) => t.includes('🛡') && t.includes('威胁差评') && t.includes('高危')),
    { tags: first.tags })
  check('T17', '★【合成正例】原文证据块渲染（老板能拿去原文里搜）',
    first.ev.includes('1-star review'), { ev: first.ev.slice(0, 90) })
  await shot('03-synthetic-risk')
} else {
  check('T14', '★【合成正例】需要 ≥2 条真实差评做底', null, { n: (synth.items || []).length })
}

// ---------------------------------------------------------------- ★ ④ 降级提示上屏
const deg = JSON.parse(JSON.stringify(beD))
deg.degraded = true
deg.llm_used = false
deg.risk_count = 0
deg.unknown_count = (deg.items || []).length
deg.clean_count = 0
deg.items = (deg.items || []).map((x) => ({
  ...x,
  risk: { decision: 'unknown', level: 'unknown', level_label: '未定论',
          suggested_action: '人工判', is_risk: false, categories: [], risk_categories: [],
          hits: [], channel: 'llm', note: '' },
}))
stub = { body: JSON.stringify(deg) }
await run(CLICK_RISK_BTN)
await sleep(2600)
const d2 = await runJson(READ_PANEL)
check('T18', '★【合成降级】「语义判定通道不可用」警示上屏',
  d2.alerts.some((a) => a.includes('语义判定通道不可用')), { alerts: d2.alerts })
check('T19', '★【合成降级】全部卡片标成「未定论」（不得显示成干净）',
  d2.cards.length > 0 && d2.cards.every((c) => c.cls.includes('rd-risk-unknown')),
  { classes: d2.cards.map((c) => c.cls[0] || '(无)') })
check('T20', '★【合成降级】计数如实：未定论 = 条数，风险/干净 = 0',
  chipOf(d2.chips, '未定论') === deg.items.length
  && chipOf(d2.chips, '干净') === 0 && chipOf(d2.chips, '风险') === 0,
  { chips: d2.chips, n: deg.items.length })
await shot('04-degraded')

// ---------------------------------------------------------------- 收尾
stub = null
await send('Fetch.disable').catch(() => {})

console.log('\n关键读数：', JSON.stringify({
  panelRequestUrl: lastRiskUrl,
  backend: { risk: beD.risk_count, unknown: beD.unknown_count, clean: beD.clean_count,
             degraded: beD.degraded, capped: beD.capped, llm_used: beD.llm_used },
  chipsAfterClick: after.chips,
  domOrder: domTitles,
  beOrder: beTitles,
  classes: after.cards.map((c) => c.cls[0] || '(无)'),
  synthRan,
}, null, 2))

const failed = results.filter((r) => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过（SKIP 不计入失败）----`)
console.log('截图：', SHOT_DIR)
chrome.kill()
process.exit(failed.length ? 1 : 0)

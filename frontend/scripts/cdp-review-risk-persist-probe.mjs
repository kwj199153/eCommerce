// CDP 真机判据（第 300 轮）：风险识别结果**不得**因为切视图而被重置。
//
// 为什么单独一个探针
// ----------------
// 老板实测报的缺陷：「点击处置台账后，原本已经风险识别的又被重置了」。
// 静态门禁（`check-review-risk-view.cjs` R13/R14）只能钉住**代码形态**，
// 证明不了「界面上真的没丢、且真的没重扫一次」。本仓反复踩过
// 「后端有端点 ≠ 前端在用 ≠ 接上了会渲染」，所以这里必须真机跑一遍。
//
// 判据（每条都配一条能反向对照的）
//   P1  点【风险识别】→ 出三个 chip（结果落地信号取 `.rd-risk-chip`）
//   P2  记录「已识别」快照：chips + 每张卡片的标题/风险皮肤类名
//   P3  ★ 切到【处置台账】：风险条消失（视图真的切了），**且没有重发扫描请求**
//   P4  ★ 切回【近期差评】：chips 与卡片皮肤**逐项等于** P2 的快照，扫描请求数不变
//       —— 这一条就是老板报的缺陷本身
//   P5  ★ 反向对照：改「时间窗」把清单换掉 ⇒ 标记**必须**消失
//       （证明 P4 不是「永远不清」这种假修复）
//
// ★ 网络层只**观察**不改造：拦截 `/trade/reviews/risk` 并放行，只用来数请求次数。
// ★ profile 用**固定目录**（复用），只清 `Singleton*` 锁文件 ——
//   `mkdtempSync` 每次新建一个 profile 会产生 1500+ 文件，撞沙箱批量删除守卫。
//
// 用法：node scripts/cdp-review-risk-persist-probe.mjs
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9393
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r300_risk_persist')
const PROFILE_DIR = join(SHOT_DIR, 'chrome-profile')
const RISK_PATTERN = '*/trade/reviews/risk*'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(PROFILE_DIR, { recursive: true })
for (const f of readdirSync(PROFILE_DIR)) {
  if (/^Singleton/.test(f)) rmSync(join(PROFILE_DIR, f), { force: true })
}

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${PROFILE_DIR}`, '--window-size=1680,1000',
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
let riskReqCount = 0            // 面板真实发出的风险扫描请求次数
const consoleErrors = []        // 页面侧报错（页面空白时必须能归因，不能只报 bodyLen=0）
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    consoleErrors.push('EXC ' + JSON.stringify(m.params?.exceptionDetails?.exception?.description || m.params).slice(0, 300))
  }
  if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params?.type)) {
    consoleErrors.push(m.params.type.toUpperCase() + ' ' +
      (m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300))
  }
  if (m.method === 'Fetch.requestPaused') {
    const { requestId, request } = m.params
    if (request.url.includes('/trade/reviews/risk')) riskReqCount++
    send('Fetch.continueRequest', { requestId }).catch(() => {})
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
// ★ 每个动作后都必须**等一下再读**，并显式轮询到目标状态；
//   退出判据一律用「点了按钮之后才可能出现」的元素（`.rd-risk-chip`），
//   不能用扫描前就已存在的东西（`.rd-risk-tip` 在 `v-else` 空态分支里就有 ⇒ 会假结束）。

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

const OPEN_WINDOW_SELECT = `
(() => {
  const sel = document.querySelector('.rd-filter .rd-days')
  if (!sel) return JSON.stringify({ err: 'no window select' })
  const box = sel.querySelector('.ant-select-selector') || sel
  box.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  box.click()
  return JSON.stringify({ ok: true })
})()`

const READ_OPTIONS = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  return JSON.stringify([...document.querySelectorAll('.ant-select-item-option')].map(o => norm(o.textContent)))
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

const SNAPSHOT = `(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const bar = document.querySelector('.rd-risk-bar')
  const chips = [...(bar ? bar.querySelectorAll('.rd-risk-chip') : [])].map(e => norm(e.textContent))
  const cards = [...document.querySelectorAll('.rd-item')].map(e => ({
    title: norm(e.querySelector('.rd-title')?.textContent),
    cls: [...e.classList].filter(c => c.startsWith('rd-risk-')).join(','),
  }))
  return JSON.stringify({
    barExists: !!bar, chips, cards,
    marked: cards.filter(c => c.cls).length,
    hasFilter: !!document.querySelector('.rd-filter'),
  })
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(4200)

// ★ 页面就绪必须**轮询**到，不能「睡 4.2 秒就假定好了」：
//   第一次实测就是这样拿到 bodyLen=0，而且下面几条「两个空快照相等」的断言
//   会**假绿通过**（空数组 == 空数组）—— 门禁最忌讳的形态。
let bodyLen = 0
for (let i = 0; i < 40; i++) {
  await sleep(500)
  bodyLen = await run('document.body?.innerText?.length || 0')
  if (bodyLen > 200) break
}
check('P0', '页面已渲染（自检：选择器有东西可选；未渲染则后面全部无意义）', bodyLen > 200,
  { bodyLen, url: await run('location.href'), consoleErrors: consoleErrors.slice(0, 6) })
if (bodyLen <= 200) {
  console.log('★ 页面没渲染 ⇒ 后面所有「相等」类断言都会因空快照而假绿，直接中止。')
  writeFileSync(join(SHOT_DIR, 'result.json'), JSON.stringify(results, null, 2))
  chrome.kill()
  process.exit(1)
}

// ---------------------------------------------------------------- 进入差评工作台
await run(clickByText('智能客服'))
await sleep(1700)
await run(clickByText('差评台账'))
await sleep(2600)
await run(clickByText('近期差评'))
await sleep(1800)

const opened = await runJson(SNAPSHOT)
check('P1a', '风险条已出现（默认落在「近期差评」视图）', opened.barExists === true, opened)
check('P1b', '切视图之前**没有**任何标记（自检：后面的对比才有意义）',
  opened.chips.length === 0 && opened.marked === 0, opened)

// 把时间窗切到「全部」，否则默认 30 天窗口条数太少
await send('Fetch.enable', { patterns: [{ urlPattern: RISK_PATTERN, requestStage: 'Request' }] })
await run(OPEN_WINDOW_SELECT)
await sleep(700)
const options = await runJson(READ_OPTIONS)
await run(PICK_OPTION('全部'))
await sleep(2800)
const listed = await runJson(SNAPSHOT)
check('P1c', '时间窗已切到「全部」且列表非空', listed.cards.length >= 2,
  { options, cards: listed.cards.length })

// ---------------------------------------------------------------- 点按钮 → 出计数
const btn = await runJson(CLICK_RISK_BTN)
check('P2a', '【风险识别】按钮可点', btn.ok === true, btn)
// ★ 轮询到 `.rd-risk-chip`（点了按钮才可能出现的信号）
let after = null
for (let i = 0; i < 180; i++) {
  await sleep(1000)
  const s = await runJson(SNAPSHOT)
  if (s.chips.length) { after = s; break }
}
after = after || (await runJson(SNAPSHOT))
check('P2b', '点完按钮出现「风险 / 未定论 / 干净」三个计数', after.chips.length === 3,
  { chips: after.chips, waitedSec: '<=180' })
const reqAfterScan = riskReqCount
check('P2c', '扫描请求计数 == 1（按钮只发了一次）', reqAfterScan === 1, { riskReqCount })

const snapA = { chips: after.chips, cards: after.cards, marked: after.marked }
await shot('01-scanned')

// ---------------------------------------------------------------- ★ P3 切到处置台账
await run(clickByText('处置台账'))
await sleep(2600)
const ledger = await runJson(SNAPSHOT)
check('P3a', '已切到【处置台账】（风险条消失、台账筛选出现）',
  after.chips.length === 3 && ledger.barExists === false && ledger.hasFilter === true, ledger)
check('P3b', '切视图期间**没有重发**风险扫描请求',
  after.chips.length === 3 && riskReqCount === reqAfterScan,
  { before: reqAfterScan, after: riskReqCount })
await shot('02-ledger')

// ---------------------------------------------------------------- ★ P4 切回近期差评
await run(clickByText('近期差评'))
await sleep(2600)
const back = await runJson(SNAPSHOT)
// ★★ 必须先确认「快照本身是真的」再比相等：两个空快照也相等 ⇒ 假绿。
//   第 300 轮第一次跑就踩到过（页面没渲染，P4a/P4b 双双"PASS"）。
const realSnap = snapA.chips.length === 3 && snapA.marked > 0
check('P4-pre', '前置：P2 的快照非空（否则 P4 的"相等"是空快照相等 = 假绿）',
  realSnap, { chips: snapA.chips, marked: snapA.marked, cards: snapA.cards.length })
check('P4a', '★ 切回后风险计数仍在（老板报的缺陷：不得被重置）',
  realSnap && JSON.stringify(back.chips) === JSON.stringify(snapA.chips),
  { before: snapA.chips, after: back.chips })
check('P4b', '★ 切回后卡片皮肤逐项不变（含顺序）',
  realSnap && JSON.stringify(back.cards) === JSON.stringify(snapA.cards),
  {
    diff: back.cards.map((c, i) => (JSON.stringify(c) === JSON.stringify(snapA.cards[i]) ? null : { i, a: snapA.cards[i], b: c })).filter(Boolean),
  })
check('P4c', '★ 切回后**没有**重跑扫描（否则说明是靠重扫兜的，不是真保住）',
  realSnap && riskReqCount === reqAfterScan, { before: reqAfterScan, after: riskReqCount })
await shot('03-back-to-recent')

// ---------------------------------------------------------------- ★ P5 反向对照：换清单必须清
const other = options.find((o) => o && o !== '全部')
if (!other) {
  check('P5', '反向对照：换时间窗后标记必须消失', null, { options })
} else {
  await run(OPEN_WINDOW_SELECT)
  await sleep(700)
  const picked = await runJson(PICK_OPTION(other))
  await sleep(2800)
  const changed = await runJson(SNAPSHOT)
  const listIsNonEmpty = changed.cards.length >= 1
  check('P5', `反向对照：时间窗换成「${other}」后标记必须消失（证明 P4 不是「永远不清」）`,
    listIsNonEmpty ? (changed.chips.length === 0 && changed.marked === 0) : null,
    { picked, listIsNonEmpty, chips: changed.chips, marked: changed.marked,
      cards: changed.cards.length })
  await shot('04-window-changed')
}

// ---------------------------------------------------------------- 汇总
const failed = results.filter((r) => r.state === 'FAIL')
const skipped = results.filter((r) => r.state === 'SKIP')
console.log(`\n---- ${results.length - failed.length - skipped.length}/${results.length} 通过` +
  (skipped.length ? `（${skipped.length} SKIP）` : '') + ' ----')
writeFileSync(join(SHOT_DIR, 'result.json'), JSON.stringify(results, null, 2))
chrome.kill()
process.exit(failed.length ? 1 : 0)

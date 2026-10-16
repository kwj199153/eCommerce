// CDP 真机探针（第 365b 轮）—— 站内英文类目中文化：treemap / 短标签「口径统一」。
//
// 老板原话：「treemap 和短标签展示是联动的，你要统一口径」。
// 这一条**只能**在真实浏览器里验：treemap 的类目名由 ECharts 的 formatter **画在 canvas 上**，
// 页面 DOM 里根本没有那段文字 —— 拿 innerText 去查「有没有英文残留」永远是空集（假绿），
// 截图肉眼又只能看个大概。故本探针取的是**真实渲染所用的那份数据**：
//   `document.querySelector('.et-wrap').__vueParentComponent.props.cells`
// 即 MarketInsightConfig 传给 EChartsTreemap 的 `treemapCells`（Vue 3 dev 下组件实例挂在元素上）。
//
// 判据口径（沿用本仓纪律）：
//   · 每条集合判据都配 L0 自检（选择器真选到东西、cells 真的是非空数组）；
//   · 「没有英文」必须配一条**正控**（确有中文色块）—— 只判「不含字母」的话，
//     空数组 / 选择器失效也照样绿；
//   · 与真源对账：色块名去掉 ` · US` 后缀后必须落在 `CATEGORY_ZH` 的 values 里，
//     而不是「看起来像中文就行」（自造译法、半中半英都能骗过后者）。
//
// 用法：node scripts/cdp-r365-category-zh.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9399
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r365b_category_zh')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r365b-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking', 'about:blank',
], { stdio: 'ignore' })

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await r.json()
    if (targets.some(t => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find(t => t.type === 'page')
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise(res => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })

const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400))
  return r?.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

// 演示身份：token 只需 `demo-` 前缀（后端只看前缀，身份由服务端解析）
const AUTH = {
  access_token: 'demo-token',
  refresh_token: 'demo-refresh-token',
  user_info: { id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' },
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', ${JSON.stringify(AUTH.access_token)});
    localStorage.setItem('refresh_token', ${JSON.stringify(AUTH.refresh_token)});
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify(AUTH.user_info))});
  `,
})

await send('Page.navigate', { url: URL })
await sleep(3500)

const NORM = `(s) => (s || '').replace(/\\s+/g, ' ').trim()`
const clickByText = (label) => `
(() => {
  const norm = ${NORM}
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found' })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName })
})()`

const closeAll = `document.querySelectorAll('.ant-modal-close, .ant-drawer-close').forEach(b => b.click())`

/** 取真源（在真实浏览器里动态 import 前端模块，顺带证明 displayCategory 在页面环境可用） */
const ZH_JSON = await run(`
(async () => {
  const m = await import('/src/config/categoryTaxonomy.ts')
  return JSON.stringify({
    values: Object.values(m.CATEGORY_ZH),
    keys: Object.keys(m.CATEGORY_ZH),
    wide: m.displayCategory('Home & Kitchen', 'wide'),
    narrow: m.displayCategory('Home & Kitchen', 'narrow'),
    unknown: m.displayCategory('Seafood & Raw Bar', 'wide'),
  })
})()`)
const ZH = JSON.parse(ZH_JSON || '{}')
const ZH_VALUES = new Set(ZH.values || [])

/** 读**真实渲染所用的数据**：MarketInsightConfig 传给 EChartsTreemap 的 cells */
const readCells = () => run(`
(() => {
  const el = document.querySelector('.et-wrap')
  if (!el) return JSON.stringify({ err: 'no .et-wrap' })
  const canvas = !!el.querySelector('canvas')
  const comp = el.__vueParentComponent
  const p = comp && comp.props ? comp.props : null
  const cells = p && p.cells
  if (!Array.isArray(cells)) {
    return JSON.stringify({ err: 'no cells', hasComp: !!comp, propKeys: p ? Object.keys(p) : [] })
  }
  return JSON.stringify({
    canvas,
    n: cells.length,
    cells: cells.map(c => ({ name: c.name, group: c.group, tipName: c.tipName, extra: c.extra })),
  })
})()`)

const SITE_RE = /^(.*) · (US|UK|DE|JP|SG)$/
const WIDE_RE = /^(.+)（(.+)） · (US|UK|DE|JP|SG)$/

/** 对一批 cells 做同一组判定（对话/大屏两处复用，口径只有一份） */
function judge(tag, data) {
  const cells = data.cells || []
  const okList = []
  const bad = []
  for (const c of cells) {
    const m = SITE_RE.exec(c.name || '')
    if (!m) { bad.push({ name: c.name, why: '不匹配「中文 · 站点」' }); continue }
    if (!ZH_VALUES.has(m[1])) bad.push({ name: c.name, why: `色块名「${m[1]}」不在 CATEGORY_ZH 真源里` })
    if (!ZH_VALUES.has(c.group)) bad.push({ name: c.name, group: c.group, why: '组标题条不在真源里' })
    const w = WIDE_RE.exec(c.tipName || '')
    if (!w) bad.push({ name: c.name, tipName: c.tipName, why: 'tipName 不是宽档「中文（English） · 站点」' })
    else if (w[1] !== m[1] || !ZH_VALUES.has(w[1])) bad.push({ name: c.name, tipName: c.tipName, why: 'tipName 的中文段与 label 不同源' })
    okList.push(c)
  }
  check(`${tag}-a`, `★${tag}：色块名 / 组条 / tipName 全部落在 CATEGORY_ZH 真源（${cells.length} 块）`,
    cells.length > 0 && bad.length === 0, { bad: bad.slice(0, 4) })
  // 正控：确有中文（防「全是英文但集合判据写歪了」或空数组恒绿）
  check(`${tag}-b`, `正控：${tag} 确有中文色块`,
    okList.some(c => /[\u4e00-\u9fff]/.test(c.name || '')), { sample: cells.slice(0, 3).map(c => c.name) })
  // 反控：没有「纯 ASCII 的色块名」（去掉站点后缀后）
  const asciiOnly = cells.filter(c => {
    const m = SITE_RE.exec(c.name || '')
    return m && /^[\x20-\x7e]+$/.test(m[1])
  })
  check(`${tag}-c`, `反控：${tag} 无色块名残留纯英文`,
    cells.length > 0 && asciiOnly.length === 0, { asciiOnly: asciiOnly.map(c => c.name).slice(0, 4) })
  // tooltip extra 的「细分品类」也走中英对照
  const extraBad = cells.filter(c => c.extra && !/^细分品类 .+（.+） · /.test(c.extra))
  check(`${tag}-d`, `${tag}：tooltip 的「细分品类」走中英对照`,
    cells.length > 0 && extraBad.length === 0, { extraBad: extraBad.map(c => c.extra).slice(0, 3) })
}

// ================================================================ 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('P0', '页面已渲染（自检：有东西可选）', bodyLen > 200, { bodyLen })

await run(clickByText('选品分析师'))
await sleep(2400)
await run(closeAll)
await sleep(400)

const d0raw = await readCells()
const d0 = JSON.parse(d0raw || '{}')
check('P0b', '★自检：treemap 真渲染了（.et-wrap + canvas + props.cells 非空）',
  d0.canvas === true && Array.isArray(d0.cells) && d0.cells.length > 0, d0.err ? d0 : { canvas: d0.canvas, n: d0.n })

check('R0', '★真源在真实浏览器里可用（dynamic import 页面模块）',
  ZH.wide === '家居与厨房（Home & Kitchen）' && ZH.narrow === '家居与厨房' && ZH.unknown === 'Seafood & Raw Bar',
  { wide: ZH.wide, narrow: ZH.narrow, unknown: ZH.unknown })
await shot('00-chat-mode')

if (d0.cells) judge('对话模式', d0)

// ---------------------------------------------------------------- 大屏模式
const hitData = JSON.parse(await run(clickByText('大屏模式')) || '{}')
check('P0c', '顶栏出现「对话/大屏」切换（自检：选品大盘已选中）', hitData.ok === true, hitData)
await sleep(1400)
const d1 = JSON.parse(await readCells() || '{}')
check('P0d', '★自检：大屏模式下 treemap 仍在渲染',
  d1.canvas === true && Array.isArray(d1.cells) && d1.cells.length > 0, { canvas: d1.canvas, n: d1.n })
if (d1.cells) judge('大屏模式', d1)
await shot('01-data-mode')

// ---------------------------------------------------------------- tooltip（宽档人工可核证据）
const box = await run(`(() => {
  const e = document.querySelector('.et-wrap')
  if (!e) return null
  const r = e.getBoundingClientRect()
  return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) })
})()`)
if (box) {
  const { x, y } = JSON.parse(box)
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, buttons: 0 })
  await sleep(700)
  await shot('02-tooltip')
}

// ---------------------------------------------------------------- 联动：点色块 → 蓝海 cascader
// 老板点名的「treemap 和短标签展示是联动的」—— 这条链路另一端的口径也要真机看：
// 点色块会切到「蓝海挖掘」并把类目预填进 cascader，cascader 的 label 走宽档（中英对照）。
const cellPos = await run(`(() => {
  const e = document.querySelector('.et-wrap')
  if (!e) return null
  const r = e.getBoundingClientRect()
  return JSON.stringify({ x: Math.round(r.left + r.width * 0.22), y: Math.round(r.top + r.height * 0.28) })
})()`)
if (!cellPos) {
  check('R1', '联动：点色块 → 蓝海 cascader（SKIP：拿不到色块坐标）', null, null)
} else {
  const { x, y } = JSON.parse(cellPos)
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1, buttons: 1 })
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1, buttons: 0 })
  await sleep(1800)
  const blue = JSON.parse(await run(`(() => {
    const sel = [...document.querySelectorAll('.ant-select-selection-item')]
      .map(e => e.getAttribute('title') || e.textContent || '').filter(Boolean)
    const hint = document.querySelector('.prefill-hint')
    return JSON.stringify({ sel, hint: hint ? hint.textContent : '' })
  })()`) || '{}')
  const wideOnes = (blue.sel || []).filter(s => /^.+（.+）$/.test(s))
  check('R1', '★联动：点色块 → 蓝海 cascader 显示宽档「中文（English）」',
    wideOnes.length > 0 && (blue.sel || []).every(s => !/^[\x20-\x7e]+$/.test(s)),
    blue)
  check('R2', '联动：预填提示带中文类目名', /已按「/.test(blue.hint || ''), { hint: blue.hint })
  await shot('03-blue-ocean-cascader')
}

chrome.kill()

const failed = results.filter(r => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length} PASS / ${failed.length} FAIL / ${results.filter(r => r.state === 'SKIP').length} SKIP ----`)
console.log(`截图目录： ${SHOT_DIR}`)
process.exit(failed.length ? 1 : 0)

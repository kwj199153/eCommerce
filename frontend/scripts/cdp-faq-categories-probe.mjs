// CDP 真机判据（第 293 轮）—— 业务话术库的**分类渲染**是否正确
//
// 背景：`knowledge_faqs.category` 存的是英文 code（shipping / aftersale / ...），
// 前端 `FAQ_CATEGORIES` 负责把 code 翻成中文标签。两份字典漂移过一次：
//   第 293 轮实测：库里有 32 行 `aftersale` + 16 行 `order`，
//   而前端字典里没有这两个 key ⇒ `getCategoryLabel()` 的兜底 `|| key` 生效，
//   列表里直接显示英文原串 `aftersale` / `order`，且筛选下拉里选不到它们。
//
// 本探针要证明的就是「修完真的不一样了」，所以判据分**正反两组**：
//   正向：下拉里**有**「订单」「售后」；表格里**有**这两个中文标签
//   反向：表格里**不再有**英文原串（`/^[a-z_]+$/` 命中的 tag）
// 只有正反都报，才能区分「翻译生效」与「这两类数据根本不在当前店铺」——
// 后者会让正向判据空跑（本仓判据：HIT 数必须与总数对账）。
//
// 用法：node scripts/cdp-faq-categories-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9381
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r293_faq_categories')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ← ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-faqcat-'))
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
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => {
  const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }))
})
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400))
  return r?.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found' })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName })
})()`

// 打开「全部分类」下拉（a-select 的选项在 body 级 portal 里，必须先点开才存在）
const OPEN_CATEGORY_SELECT = `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const selects = [...document.querySelectorAll('.ant-select')]
  // 按占位符文案定位「全部分类」那个 select —— 比按 DOM 层级猜 .filter-bar 稳
  const target = selects.find(el => norm(el.textContent).includes('全部分类'))
    || selects.find(el => (el.querySelector('.ant-select-selection-placeholder')?.textContent || '').includes('全部分类'))
  if (!target) {
    return JSON.stringify({
      err: 'no category select',
      selectCount: selects.length,
      placeholders: selects.map(el => norm(el.querySelector('.ant-select-selection-placeholder')?.textContent || '')),
    })
  }
  const box = target.querySelector('.ant-select-selector') || target
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
    box.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }))
  }
  return JSON.stringify({ ok: true, selectCount: selects.length })
})()`

const READ_DROPDOWN = `
(() => {
  const opts = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-content')]
  return JSON.stringify(opts.map(e => (e.textContent || '').replace(/\\s+/g, ' ').trim()))
})()`

// 表格「分类」列的标签文案（按表头定位列序号，避免把 priority / keywords 的 tag 混进来）
const READ_TABLE = `
(() => {
  const ths = [...document.querySelectorAll('.ant-table-thead th')]
  const idx = ths.findIndex(th => (th.textContent || '').includes('分类'))
  const rows = [...document.querySelectorAll('.ant-table-tbody tr.ant-table-row')]
  const cells = rows.map(tr => {
    const td = tr.querySelectorAll('td')[idx]
    return td ? (td.textContent || '').replace(/\\s+/g, ' ').trim() : null
  }).filter(v => v !== null)
  const allTags = [...document.querySelectorAll('.ant-table-tbody .ant-tag')]
    .map(e => (e.textContent || '').trim())
  return JSON.stringify({
    colIdx: idx,
    rowCount: rows.length,
    cells,
    rawCodeTags: allTags.filter(t => /^[a-z_]+$/.test(t)),
    allTagCount: allTags.length,
  })
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(3800)

// ---------------------------------------------------------------- Q0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('Q0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// 进入业务话术库
const nav = await run(clickByText('业务话术库'))
await sleep(2200)
const t = JSON.parse(await run(READ_TABLE))
check('Q0b', '话术库已打开且表格有行（否则后续判据空跑）', t.rowCount > 0, { nav, ...t })
await shot('faq-list')

// ---------------------------------------------------------------- Q1/Q2/Q3 下拉
await run(OPEN_CATEGORY_SELECT)
await sleep(900)
const opts = JSON.parse(await run(READ_DROPDOWN))
await shot('faq-category-dropdown')

check('Q1', '分类下拉共 10 项', opts.length === 10, { count: opts.length, opts })
check('Q2', '下拉里有「订单」与「售后」两类（第 293 轮新增）',
  opts.some((o) => o.includes('订单')) && opts.some((o) => o.includes('售后')), { opts })
check('Q3', '下拉里有「评价」、不再有「差评台账」',
  opts.some((o) => o.includes('评价')) && !opts.some((o) => o.includes('差评台账')), { opts })

// 关掉下拉，避免挡住后续读数
await run("document.body.click(); 'ok'")
await sleep(500)

// ---------------------------------------------------------------- Q4 反向：不许再出英文原串
// ★ 口径只认**分类列**：`.ant-table-tbody .ant-tag` 会把关键词列的小标签一起扫进来
//   （实测 rawCodeTags = shipping / defective / pay，那是 `record.keywords`）——
//   全表扫 = 判据打错靶子，会给出与事实相反的红。
const rawInCategoryCol = t.cells.filter((c) => /^[a-z_]+$/.test(c))
check('Q4', '分类列不再出现英文原串（aftersale / order 这类）',
  rawInCategoryCol.length === 0,
  { rawInCategoryCol, sampleCells: t.cells.slice(0, 10), keywordsTagSample: t.rawCodeTags.slice(0, 5) })

// ---------------------------------------------------------------- Q5 正向：中文标签真的渲染出来了
const hasAftersale = t.cells.some((c) => c === '售后')
const hasOrder = t.cells.some((c) => c === '订单')
if (!hasAftersale && !hasOrder) {
  check('Q5', '表格里出现「售后」/「订单」中文标签', null,
    { note: '当前店铺列表里没有这两类条目 ⇒ 正向判据空跑（不是失败）', cells: t.cells.slice(0, 8) })
} else {
  check('Q5', '表格里出现「售后」/「订单」中文标签', hasAftersale && hasOrder,
    { hasAftersale, hasOrder, cells: t.cells.slice(0, 12) })
}

// ---------------------------------------------------------------- 输出
const failed = results.filter((r) => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
console.log('[cells]', JSON.stringify(t.cells.slice(0, 15)))
console.log('[opts ]', JSON.stringify(opts))

chrome.kill()
process.exit(failed.length ? 1 : 0)

// CDP 真机探针（第 296 轮）—— 差评工作台「改名」+「抽屉改版」。
//
// 判据分两组：
//   N 组：功能栏按钮与**右侧边栏面板标题**：`差评处理` → `差评台账`
//         （二者同源 —— `panelTitle = props.currentTool?.name`，改一处两处都变，
//           所以必须**两处都实测**：只测功能栏的话，标题没跟着变也照样绿）
//   D 组：列表弹出的抽屉：标题最终定为 `差评处置`（第 298 轮术语统一把 296 轮
//         那一次改名反转了回来）、宽度 480 → 720、
//
// 为什么非真机不可：
//   · 改名改的是**渲染出来的文案** —— 静态门禁只能证明源码里有那个字符串；
//   · 两栏是**几何**（并排还是堆叠）—— 只有真实布局算得出来。DOM 里有两个
//     `.rd-detail-col` 不等于它们左右并排：CSS 没生效时它们是上下堆叠的。
//
// 判据口径（本仓纪律）：
//   · 先自检选择器真的选到东西，否则选择器写错会静默全绿；
//   · 依赖 seed 数据的判据允许 SKIP，但**必须如实打印**（不许当成通过）；
//   · 对照组必需：断言「右栏不含评价正文」，否则「两栏各渲染一份全部内容」
//     这种实现也会全绿；
//   · 几何用相对条件，不写死像素（但宽度这次是**明确规格**，故直接钉 720）。
//
// 用法：node scripts/cdp-review-desk-drawer-layout-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
//   PROBE_SHOT_DIR 覆盖截图目录
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9379
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r296_review_desk_drawer')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r296-'))
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

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(3500)

const NORM = `(s) => (s || '').replace(/\\s+/g, ' ').trim()`

// 按精确文本点最内层可点元素（避免点到大容器）
const clickByText = (label) => `
(() => {
  const norm = ${NORM}
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found' })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, cls: String(target.className).slice(0, 60) })
})()`

// 功能栏工具按钮集合（不点击，只读文本）
// ★ 类名取自本仓既有探针（`cdp-review-desk-ui-probe-panel-bug.mjs` 的 R12/R11），
//   不是我猜的 —— 第一版写成 .tool-btn 等五个候选全不命中，于是 `texts` 为空，
//   下游的「不再有旧名」取反后**恒真**（空跑假绿）。⇒ 必须带数量自检。
const TOOL_BTNS = `
(() => {
  const norm = ${NORM}
  const els = [...document.querySelectorAll('.toolbar-tool-btn')]
  return JSON.stringify({ sel: '.toolbar-tool-btn', n: els.length, texts: els.map(e => norm(e.textContent)) })
})()`

// ---------------------------------------------------------------- N0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('N0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

const agentHit = await run(clickByText('智能客服'))
check('N0b', '侧栏能点到「智能客服」', JSON.parse(agentHit).ok === true, JSON.parse(agentHit))
await sleep(1500)

// ---------------------------------------------------------------- N1 功能栏改名
const tools = JSON.parse(await run(TOOL_BTNS))
const hasNew = tools.texts.some(t => t.includes('差评台账'))
const hasOld = tools.texts.some(t => t.includes('差评处理'))
// ★ 前置自检：选择器没选到东西时，下面两条必须 FAIL 而不是"取反恒真"。
check('N1a', '功能栏按钮选择器自检（`.toolbar-tool-btn` 选到了按钮）', tools.n > 0, tools)
check('N1', '功能栏工具按钮叫「差评台账」', tools.n > 0 && hasNew, tools)
check('N1b', '功能栏里**不再**有「差评处理」（旧名清干净）', tools.n > 0 && !hasOld, tools)

// ---------------------------------------------------------------- N2 右栏标题同步
const toolHit = await run(clickByText('差评台账'))
await sleep(1800)
const titleInfo = JSON.parse(await run(`
(() => {
  const t = document.querySelector('.task-config-panel .panel-title')
  return JSON.stringify({ title: t ? (t.textContent || '').trim() : null })
})()`))
check('N2', '★ 右侧边栏面板标题同步为「差评台账」（与功能栏同源）',
  titleInfo.title === '差评台账', titleInfo)

const rootOk = await run(`!!document.querySelector('.rd-root')`)
check('N2b', '点「差评台账」后右栏出工作台（.rd-root）', rootOk === true, { rootOk })
// ------------------------------------------------- N2c 差评卡片上的直达对话入口
//   ★ 第 298 轮：默认视图是「近期差评」⇒ 卡片列表此刻就在页面上（先量，再切台账）。
const itemChat = JSON.parse(await run(`
(() => {
  const it = document.querySelector('.rd-item')
  if (!it) return JSON.stringify({ ok: false, skip: '近期差评列表为空' })
  const btn = it.querySelector('.rd-item-chat')
  if (!btn) return JSON.stringify({ ok: false, reason: '卡片上没有 💬 按钮' })
  const br = btn.getBoundingClientRect(), ir = it.getBoundingClientRect()
  return JSON.stringify({ ok: true, text: (btn.textContent||'').trim(),
    w: Math.round(br.width), h: Math.round(br.height),
    inCard: br.top >= ir.top - 1 && br.bottom <= ir.bottom + 1 })
})()`))
if (itemChat.skip) check('N2c', '差评卡片有「💬 直达对话」按钮', null, itemChat)
else check('N2c', '差评卡片有「💬 直达对话」按钮（第 298 轮补的缺口）',
  itemChat.ok === true && itemChat.text.includes('💬') && itemChat.w > 0 && itemChat.h > 0
  && itemChat.inCard === true, itemChat)

// ---------------------------------------------------------------- 进入「处置台账」并打开抽屉
await run(`
(() => {
  const norm = ${NORM}
  const t = [...document.querySelectorAll('.rd-tab')].find(e => norm(e.textContent).includes('处置台账'))
  if (t) t.click()
  return true
})()`)
await sleep(1500)
// ------------------------------------------------- N3 台账行的直达对话入口
//   ★ 第 298 轮补的缺口：此前 💬 只长在抽屉里，列表行没有按钮。
const rowChat = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, skip: '台账为空' })
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-chat')
  if (!btn) return JSON.stringify({ ok: false, reason: '行内没有 💬 按钮' })
  const br = btn.getBoundingClientRect(), rr = rows[0].getBoundingClientRect()
  return JSON.stringify({ ok: true, text: (btn.textContent||'').trim(), rows: rows.length,
    w: Math.round(br.width), h: Math.round(br.height),
    inRow: br.top >= rr.top - 1 && br.bottom <= rr.bottom + 1 })
})()`))
if (rowChat.skip) check('N3', '台账行有「💬 直达对话」按钮', null, rowChat)
else check('N3', '台账行有「💬 直达对话」按钮（第 298 轮补的缺口）',
  rowChat.ok === true && rowChat.text.includes('💬') && rowChat.w > 0 && rowChat.h > 0
  && rowChat.inRow === true, rowChat)

const drawerOpen = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, reason: '台账为空（无行可点）', rows: 0 })
  // ★ 第 298 轮：这一列多了 💬 按钮 ⇒ 必须点名 `.rd-act-open`（开抽屉那个）。
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-open') || rows[0].querySelector('button')
  if (!btn) return JSON.stringify({ ok: false, reason: '行内无按钮', rows: rows.length })
  btn.click()
  return JSON.stringify({ ok: true, rows: rows.length, btn: (btn.textContent || '').trim() })
})()`))
await sleep(1800)

if (drawerOpen.ok !== true) {
  check('D1', '打开处置抽屉（台账有行才可验证）', null, drawerOpen)
} else {
  // ------------------------------------------------------------ D1 抽屉标题
  const dt = JSON.parse(await run(`
(() => {
  const t = document.querySelector('.ant-drawer-title')
  const open = !!document.querySelector('.ant-drawer-open')
  return JSON.stringify({ title: t ? (t.textContent || '').trim() : null, open })
})()`))
  // ★ 第 298 轮方向反转：296 轮要求标题叫「处理」，术语统一后必须叫「处置」。
  //   反向注入对照：把 :title 改回「处理」⇒ 这一条必须 FAIL。
  check('D1', '★ 抽屉标题是「差评处置」（第 298 轮术语统一，不再是「处理」）',
    dt.open && typeof dt.title === 'string' && dt.title.includes('差评处置') && !dt.title.includes('差评处理'),
    dt)

  // ------------------------------------------------------------ D2 宽度 720
  const dw = JSON.parse(await run(`
(() => {
  const el = document.querySelector('.ant-drawer-content-wrapper')
  if (!el) return JSON.stringify({ err: 'no wrapper' })
  const r = el.getBoundingClientRect()
  return JSON.stringify({ width: Math.round(r.width), styleWidth: el.style.width || null })
})()`))
  check('D2', '★ 抽屉宽度 = 720（原 480，改后不再被挤成长条）',
    Math.abs((dw.width || 0) - 720) <= 2, dw)

  // ------------------------------------------------------------ D3 两栏结构
  const cols = JSON.parse(await run(`
(() => {
  const grid = document.querySelector('.rd-detail-grid')
  const cs = [...document.querySelectorAll('.rd-detail-grid > .rd-detail-col')]
  if (!grid) return JSON.stringify({ grid: false, n: 0 })
  const gr = grid.getBoundingClientRect()
  const box = cs.map(c => {
    const r = c.getBoundingClientRect()
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }
  })
  return JSON.stringify({ grid: true, n: cs.length, gridW: Math.round(gr.width), box })
})()`))
  check('D3', '抽屉里有左右两栏（.rd-detail-grid 下恰好 2 个 .rd-detail-col）',
    cols.grid === true && cols.n === 2, cols)

  // ------------------------------------------------------------ D4 两栏真的**并排**
  // ★ DOM 里有两个 col ≠ 它们左右并排：CSS 没生效时是上下堆叠的。
  let sideBySide = false
  if (cols.n === 2) {
    const [a, b] = cols.box
    sideBySide = a.w > 100 && b.w > 100 && a.x + a.w <= b.x + 1 && Math.abs(a.y - b.y) <= 5
  }
  check('D4', '★ 两栏是**左右并排**（不是上下堆叠）：左栏右边界 ≤ 右栏左边界，且顶部对齐',
    sideBySide, cols.box)

  // ------------------------------------------------------------ D5/D6 内容归位 + 对照组
  const split = JSON.parse(await run(`
(() => {
  const cs = [...document.querySelectorAll('.rd-detail-grid > .rd-detail-col')]
  if (cs.length !== 2) return JSON.stringify({ err: 'not 2 cols' })
  const txt = cs.map(c => (c.innerText || ''))
  return JSON.stringify({ left: txt[0], right: txt[1] })
})()`))
  const L = split.left || '', Rr = split.right || ''
  check('D5', '左栏＝事实 + 设置（含 评价正文 / 个案判定 / 处置）',
    L.includes('评价正文') && L.includes('个案') && L.includes('处置'), { leftHead: L.slice(0, 60) })
  check('D6', '右栏＝生成（含 📤 生成）', Rr.includes('生成'), { rightHead: Rr.slice(0, 60) })
  // ★ 对照组：右栏**不该**有只读的正文/判定 —— 否则「两栏各渲染一份全部内容」也会全绿
  check('D6b', '★ 对照组：右栏不含只读事实（评价正文 / 个案判定）',
    !Rr.includes('评价正文') && !Rr.includes('个案'), { rightHead: Rr.slice(0, 60) })

  // ------------------------------------------------------------ D7 标题形态
  // ★ 第 298 轮方向反转：标题定为「差评处置 · <差评标题>」⇒ 由「不得出现」改为「必须出现」。
  const hasSep = await run(`(document.body.innerText || '').includes('差评处置 ·')`)
  check('D7', '抽屉标题是「差评处置 · <差评标题>」形态', hasSep === true, { hasSep })

  await shot('drawer-720-twocol')
}

// ---------------------------------------------------------------- 汇总
const pass = results.filter(r => r.state === 'PASS').length
const fail = results.filter(r => r.state === 'FAIL').length
const skip = results.filter(r => r.state === 'SKIP').length
console.log(`\n---- ${pass} PASS / ${fail} FAIL / ${skip} SKIP ----`)
console.log('截图目录：', SHOT_DIR)
ws.close(); chrome.kill()
process.exit(fail ? 1 : 0)

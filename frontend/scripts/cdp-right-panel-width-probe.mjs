// CDP 真机探针（第 297 轮）—— 右栏 sider 宽度是否真的取自 `PANEL_W`。
//
// 为什么需要它：
//   第 297 轮把 `:width="isWidePanel ? 528 : 340"` 改成了
//   `:width="isWidePanel ? PANEL_W.panelWide : PANEL_W.panelNormal"`。
//   值**没有变**，所以「静态门禁 + 类型检查 + 页面没白屏」都不能证明：
//     · 两个档位真的分别落到 340 / 528（而不是两边都取到同一个值）；
//     · 没有退化成 `width="undefined"`（Vue 会把未定义渲染成空属性，布局悄悄塌成默认宽）。
//   这两件事只有**真实布局**答得出来。
//
// 判据口径（本仓纪律）：
//   · 先自检 `.right-panel` 真的存在，否则选择器写错会静默全绿；
//   · 量的是 `getBoundingClientRect().width`（布局的真实结果），不是读 inline style 的字面量；
//   · 两条判据必须是**同一个元素在两个状态下**的不同值 —— 只测一边的话，
//     「两档都写成 528」也照样绿。
//
// 用法：node scripts/cdp-right-panel-width-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9381
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r297_right_panel_width')

const PANEL_NORMAL = 340
const PANEL_WIDE = 528

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r297-'))
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

// 量右栏真实布局宽度（不是读 inline style）
const measure = `
(() => {
  const el = document.querySelector('.right-panel')
  if (!el) return JSON.stringify({ err: 'no .right-panel' })
  const r = el.getBoundingClientRect()
  return JSON.stringify({ found: true, w: Math.round(r.width), h: Math.round(r.height) })
})()`

const closeAll = `(() => {
  document.querySelectorAll('.ant-modal-close, .ant-drawer-close').forEach(b => b.click())
  return 'ok'
})()`

// ---------------------------------------------------------------- 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('P0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// ---------------------------------------------------------------- 档位 1：常规 340
// ★ 必须先切到非「店秘书」的 Agent：店秘书下右栏 `v-if="currentView==='chat' && !isSecretaryAgent"`
//   **根本不渲染**（第一版直接量 `.right-panel` 就吃了这个亏）
// 用「选品分析师」：它不在 `isWideBoardAgent` 里，默认工具也不是 `profit-calc`
// ⇒ `isWidePanel = false` ⇒ 右栏 = panelNormal。（用「智能客服」不行：默认工具就可能是差评台账）
const hitCS = await run(clickByText('选品分析师'))
check('P1a', '侧栏能点到「选品分析师」', JSON.parse(hitCS).ok === true, JSON.parse(hitCS))
await sleep(2000)
await run(closeAll)
await sleep(400)
const r0 = JSON.parse(await run(measure))
check('P0b', '.right-panel 存在（自检：量测目标选得到）', r0.found === true, r0)
const rN = r0
check('P1', `选品分析师（非宽看板）下右栏 = PANEL_W.panelNormal(${PANEL_NORMAL})`,
  rN.w === PANEL_NORMAL, rN)
await shot('01-normal-340')

// ---------------------------------------------------------------- 档位 2：加宽 528
// 「差评台账」是智能客服的工具 ⇒ 先切到智能客服，再点它
await run(clickByText('智能客服'))
await sleep(1800)
const hitRD = await run(clickByText('差评台账'))
await sleep(2200)
await run(closeAll)
await sleep(400)
const rW = JSON.parse(await run(measure))
check('P2', `点「差评台账」后右栏 = PANEL_W.panelWide(${PANEL_WIDE})`, rW.w === PANEL_WIDE, rW)
await shot('02-wide-528')

// ---------------------------------------------------------------- 两档必须不同
check('P3', '两档确实是**不同**的宽度（防「两边都取到同一个值」）',
  rN.w !== rW.w, { normal: rN.w, wide: rW.w })

// ---------------------------------------------------------------- 宽度有效
check('P4', '两档都是**有限正数**（防 `undefined` 让布局静默塌掉）',
  Number.isFinite(rN.w) && rN.w > 0 && Number.isFinite(rW.w) && rW.w > 0, { normal: rN.w, wide: rW.w })

chrome.kill()

const failed = results.filter(r => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length} PASS / ${failed.length} FAIL / ${results.filter(r => r.state === 'SKIP').length} SKIP ----`)
console.log(`截图目录： ${SHOT_DIR}`)
if (failed.length) process.exit(1)
console.log(`右栏宽度真机验证通过（${PANEL_NORMAL} / ${PANEL_WIDE} 两档分别生效，且同元素取值不同 ✓）`)

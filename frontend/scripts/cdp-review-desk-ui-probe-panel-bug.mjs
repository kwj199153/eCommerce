// CDP 回归判据（第 292 轮）—— 「点差评处理 → 顶部功能栏**必须还在**」（原为 bug 复现探针）
//
// ★ 本文件的性质在修复后**反转**了，改动前后读数都在这里留痕：
//   修复前：路径 2 的 R5（点差评处理后功能栏消失）与 R7（折叠后仍为 0）都是 PASS
//           —— 那是**成功复现**老板报的现象。
//   修复后：同样两条必须变成「功能栏仍在」，即原判据被有意反转（不是放宽）。

//
// 老板现象：智能客服一开始功能栏正常；点【差评处理】弹出右侧边栏；再折叠右侧边栏之后，
//   功能栏整排消失（只剩「智能客服」四个字）。
//
// 静态读码得到的候选根因（待真机证伪）：
//   `frontend/src/views/Workspace.vue:81` 的隐藏条件里有
//   `!(isReviewDeskTool && reviewMode === 'data')` —— 设计意图是「大屏模式下功能栏让位给
//   面板自带的工具 Tab」，但**只有 AIGC 实现了那个 Tab**（`TaskConfigPanel/index.vue:32`
//   的 `v-if="isAigcAgent && isDataMode"`）；差评工作台**没有**对应 Tab。
//   而 `reviewMode` 存在 **全局 localStorage**（`review-analyst-layout-mode`）里，
//   被复盘师 / 广告 / 竞品 / AIGC / 差评工作台**共用** ⇒ 在别的 Agent 切过大屏，
//   回到客服点差评处理就会直接命中隐藏条件。
//
// 因此本探针分**两条路径**，把「是折叠动作导致的」与「是 reviewMode 早已是 data 导致的」分开：
//   路径 1（干净 profile，reviewMode=chat）：走老板描述的**原始操作序列**，看功能栏是否消失；
//   路径 2（预置 localStorage='data'）：只做「点差评处理」，看功能栏是否消失。
//   ★ 只有把这两条分开报，才不会把「环境残留」误判成「折叠动作的副作用」。
//
// ★ 第 296 轮改名注：本文（尤其是引语与修复前后读数）里的【差评处理】是该按钮
//   第 296 轮之前的旧名，现名「差评台账」。历史叫法**刻意不改写**；
//   但 R2/R4/R5/R10/R11 等**可执行判据**连同 clickByText 已同步改名 ——
//   不同步的后果不是报错，而是 clickByText 找不到按钮、静默变成「点了没反应」。
//
// 用法：node scripts/cdp-review-desk-ui-probe-panel-bug.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9378
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r292_panel_bug')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-panelbug-'))
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

// —— 通用：按精确文本点最内层可点元素 ——
const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found' })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, cls: String(target.className).slice(0, 60) })
})()`

// —— 读数：顶部功能栏 + 模式 + 折叠态（一次拿全，避免多次 evaluate 时序漂移）——
const READ = `(() => {
  const wrap = document.querySelector('.toolbar-tools')
  const btns = wrap ? [...wrap.querySelectorAll('.toolbar-tool-btn')].map(e => (e.textContent||'').replace(/\\s+/g,' ').trim()) : []
  const label = document.querySelector('.toolbar-agent-label')
  const sider = document.querySelector('.right-panel')
  const active = document.querySelector('.mode-switch-btn.active')
  return JSON.stringify({
    toolbarExists: !!document.querySelector('.inline-toolbar'),
    agentLabel: label ? (label.textContent||'').trim() : null,
    toolsWrap: !!wrap,
    toolCount: btns.length,
    tools: btns,
    modeSwitch: !!document.querySelector('.mode-switch'),
    activeMode: active ? (active.textContent||'').replace(/\\s+/g,' ').trim() : null,
    lsMode: localStorage.getItem('review-analyst-layout-mode'),
    siderCollapsed: sider ? sider.classList.contains('ant-layout-sider-collapsed') : null,
    siderWidth: sider ? Math.round(sider.getBoundingClientRect().width) : null,
    rdRoot: !!document.querySelector('.rd-root'),
  })
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(3800)

// ---------------------------------------------------------------- R0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('R0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// ================================================================ 路径 1
// 干净 profile（reviewMode 应为 chat）⇒ 走老板描述的原始操作序列
console.log('\n---- 路径 1：干净状态，走老板的原始操作序列 ----')

const agentHit1 = await run(clickByText('智能客服'))
await sleep(1600)
const s1 = JSON.parse(await run(READ))
check('R1', '点「智能客服」后功能栏有工具按钮', s1.toolCount > 0,
  { toolCount: s1.toolCount, tools: s1.tools, lsMode: s1.lsMode, activeMode: s1.activeMode })

const toolHit1 = await run(clickByText('差评台账'))
await sleep(1900)
const s2 = JSON.parse(await run(READ))
check('R2', '点「差评台账」后功能栏仍在（干净状态）', s2.toolCount > 0,
  { toolCount: s2.toolCount, tools: s2.tools, activeMode: s2.activeMode, rdRoot: s2.rdRoot, hit: JSON.parse(toolHit1) })

// 折叠右栏：点面板头部的 collapse-trigger
const collapseHit = await run(`(() => {
  const b = document.querySelector('.collapse-trigger')
  if (!b) return JSON.stringify({ err: 'no .collapse-trigger' })
  b.click()
  return JSON.stringify({ ok: true })
})()`)
await sleep(1200)
const s3 = JSON.parse(await run(READ))
check('R3', '折叠右栏后功能栏仍在（干净状态）', s3.toolCount > 0,
  { toolCount: s3.toolCount, tools: s3.tools, siderCollapsed: s3.siderCollapsed, siderWidth: s3.siderWidth, hit: JSON.parse(collapseHit) })
await shot('clean-after-collapse')

// 展开回去，恢复现场
await run(`(() => { const b = document.querySelector('.collapse-trigger'); if (b) b.click() })()`)
await sleep(1000)

// ================================================================ 路径 2
// 预置 localStorage='data'（模拟老板环境里被别的宽看板 Agent 写过的残留）
console.log('\n---- 路径 2：该 Agent 自己的模式偏好就是 data（按 Agent 分键之后）----')
// ★ 修 B 之后要模拟的是「**这个 Agent** 上次用了大屏」，所以要写**分键**。
//   同时**故意不动**旧的全局单键，R8 用来看它有没有被新代码写坏。

await run(`localStorage.setItem('review-analyst-layout-mode:customer-service','data')`)
await send('Page.reload')
await sleep(3800)

const agentHit2 = await run(clickByText('智能客服'))
await sleep(1700)
const s4 = JSON.parse(await run(READ))
check('R4', '预置 data 后、未点差评台账时功能栏仍在', s4.toolCount > 0,
  { toolCount: s4.toolCount, tools: s4.tools, lsMode: s4.lsMode, activeMode: s4.activeMode, hit: JSON.parse(agentHit2) })

await run(clickByText('差评台账'))
await sleep(1900)
const s5 = JSON.parse(await run(READ))
check('R5', '★ 偏好为大屏时，点「差评台账」后功能栏**仍在**（修复判据·修前此处复现消失）',
  s5.toolCount > 0,
  { toolCount: s5.toolCount, toolsWrap: s5.toolsWrap, tools: s5.tools, activeMode: s5.activeMode, rdRoot: s5.rdRoot })
await shot('data-mode-toolbar-kept')

// R9：确认不是「把大屏功能改坏了」—— 布局本身必须仍然进大屏
check('R9', '大屏模式本身仍生效（只保留功能栏，没有把大屏改坏）',
  s5.activeMode === '大屏模式' && s5.rdRoot === true,
  { activeMode: s5.activeMode, rdRoot: s5.rdRoot })

// 关键后果：面板里有没有替代的工具切换入口？（AIGC 有 aigc-tool-tabs，差评工作台该有吗）
const alt = await run(`(() => {
  const panel = document.querySelector('.right-panel')
  const tabs = panel ? [...panel.querySelectorAll('.aigc-tool-tabs, .rd-tool-tabs, [class*="tool-tabs"]')].map(e => String(e.className)) : []
  // 面板里所有可点的「工具级」按钮文案（排除 tab 内的业务按钮）
  const names = panel ? [...panel.querySelectorAll('button')].map(e => (e.textContent||'').replace(/\\s+/g,' ').trim()).filter(Boolean) : []
  return JSON.stringify({ altTabClasses: tabs, panelButtonCount: names.length, sample: names.slice(0, 14) })
})()`).then(JSON.parse)
check('R6', '大屏模式下右栏内**没有**替代的工具切换 Tab（⇒ 切不回订单追踪）',
  alt.altTabClasses.length === 0, alt)

// 折叠右栏后，功能栏与模式切换条分别是什么状态
await run(`(() => { const b = document.querySelector('.collapse-trigger'); if (b) b.click() })()`)
await sleep(1200)
const s6 = JSON.parse(await run(READ))
check('R7', '★ 大屏模式下折叠右栏后功能栏**仍在**（修复判据·修前此处仍为 0）', s6.toolCount > 0,
  { toolCount: s6.toolCount, modeSwitch: s6.modeSwitch, activeMode: s6.activeMode, siderCollapsed: s6.siderCollapsed })
await shot('data-mode-after-collapse')

// R8：根因已治 —— 偏好写在按 Agent 分键上，不再污染全局单键
const keys = await run(`JSON.stringify({
  scoped: localStorage.getItem('review-analyst-layout-mode:customer-service'),
  legacy: localStorage.getItem('review-analyst-layout-mode'),
})`).then(JSON.parse)
check('R8', '模式偏好写在按 Agent 分键上，旧全局单键未被写（跨 Agent 泄漏已堵）',
  keys.scoped === 'data' && keys.legacy === null, keys)

// R12：★ 「存在≠可见」—— 个数 > 0 只说明节点在 DOM 里。
//   老板的原始截图是「那一行看上去什么都没有」，而 flex 挤压 / overflow 裁切
//   完全可以让节点在、宽高为 0。⇒ 必须量几何。
const geo = await run(`(() => {
  const btns = [...document.querySelectorAll('.toolbar-tool-btn')]
  const rects = btns.map(e => {
    const r = e.getBoundingClientRect()
    return { text: (e.textContent||'').replace(/\\s+/g,' ').trim(),
             w: Math.round(r.width), h: Math.round(r.height),
             x: Math.round(r.x), y: Math.round(r.y) }
  })
  const bar = document.querySelector('.intel-action-bar')
  return JSON.stringify({
    toolRects: rects,
    allVisible: rects.length > 0 && rects.every(r => r.w > 0 && r.h > 0 && r.y >= -1 && r.x >= -1),
    vw: window.innerWidth,
    actionBarH: bar ? Math.round(bar.getBoundingClientRect().height) : null,
  })
})()`).then(JSON.parse)
check('R12', '功能栏按钮几何上真的可见（宽高 > 0 且在视口内，非「存在≠可见」）',
  geo.allVisible, geo)

// ================================================================ 改名（第 292 轮第四条）
// ★ 必须**成对**断言：技能卡该叫「差评应对」，而功能栏那个**工具**叫「差评台账」。
//   两个名字同源不同物 —— 只验前者会把"工具被顺手改掉"这种错漏放过去。
const naming = await run(`JSON.stringify({
  skillChips: [...document.querySelectorAll('.iab-chip')].map(e => (e.textContent||'').replace(/\\s+/g,' ').trim()),
  toolBtns: [...document.querySelectorAll('.toolbar-tool-btn')].map(e => (e.textContent||'').replace(/\\s+/g,' ').trim()),
})`).then(JSON.parse)

// ★★★ 第 295 轮：本判据**方向反转**（产品决策变了，不是探针坏了）。
//   第 292 轮立它时，技能卡该叫「差评应对」；
//   第 295 轮老板拍板 A 档撤下这张卡片（`as_shortcut=False`）——
//   差评的取证 / 判定 / 处置统一到【差评台账】工作台，
//   技能本身留着当 Agent 的内功（对话里仍可被自主加载）。
//   ⇒ 卡片区**不该**再有「差评应对」；有 = 撤卡片没生效。
//   ★ 这条同时就是 A 档的真机验收点。
const chipHas = naming.skillChips.some(t => t.includes('差评应对'))
const chipStale = naming.skillChips.some(t => t.includes('差评台账'))
check('R10', '★ 撤卡片后：卡片区**不再**出现「差评应对」（也不该有「差评台账」）',
  naming.skillChips.length === 0 ? null : (!chipHas && !chipStale), naming)

const toolHas = naming.toolBtns.some(t => t.includes('差评台账'))
const toolStale = naming.toolBtns.some(t => t.includes('差评应对'))
check('R11', '功能栏的工具按钮叫「差评台账」（第 296 轮改名）',
  naming.toolBtns.length === 0 ? null : (toolHas && !toolStale), naming)

// ================================================================ 汇总
const pass = results.filter(r => r.state === 'PASS').length
const fail = results.filter(r => r.state === 'FAIL').length
const skip = results.filter(r => r.state === 'SKIP').length
console.log(`\n---- ${pass}/${results.length} 通过${skip ? `（SKIP ${skip}）` : ''}${fail ? ` · FAIL ${fail}` : ''} ----`)
console.log(`截图：${SHOT_DIR}`)
const verdict = await run(READ)
console.log('末态读数：' + verdict)

chrome.kill()
process.exit(fail ? 1 : 0)

// CDP 真机探针（第 315 轮）—— 运营复盘师退掉「广告数据」卡 + 「广告复盘」大屏 tab + 「广告效果复盘」技能 chip。
//
// 老板原话：「运营复盘删除【广告数据】和广告效果复盘」；拍板：**前后端一起退 + 都不搬**。
//
// 为什么必须用真实浏览器：三处都是**渲染结果**，源码里删了不等于界面不显示 ——
//   ① 功能栏那排按钮来自 AGENT_TOOLS（删了卡片，但按钮是 v-for 渲染的）；
//   ② 大屏 tab 来自 ReviewConfig.DATA_VIEW_TABS（且**只在** reviewMode==='data' 时渲染）；
//   ③ 技能 chip 来自**后端库行**（`RETIRED_DEMO_SKILLS` 清库后才消失）—— 前端改不动它。
//
// 判据口径（本仓纪律）：
//   · 每个集合判据都配一条 **L0 自检**（选择器真选到东西），否则选择器写错会静默全绿；
//   · 「删掉了 X」必须配一条**正控**（同类的东西还在）—— 只判「不含 X」的话，
//     页面白屏/选择器失效也照样绿（本仓踩过多次的空跑形态）；
//   · 数量与**名字集合**一起判：只判数量会让「删错了一个、重名补回来一个」蒙混过关；
//   · ★ 排序比较**两侧都排**：JS 的 `.sort()` 按 UTF-16 码元（汉字不按拼音），
//     只给一侧排序 = 假红（本探针第一版就是这么挂的）。
//
// 用法：node scripts/cdp-r315-review-retire.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9388
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r315_review_retire')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}
// 两侧都按同一口径（默认 Array.sort = UTF-16 码元）排序后比较
const sameSet = (actual, expected) =>
  JSON.stringify([...actual].sort()) === JSON.stringify([...expected].sort())

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r315-'))
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
  if (r?.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 300)
  return r?.result?.result?.value
}
// 统一走这个：表达式自己定义 norm（不再把 norm 源串插进表达式 —— 上一版那样插会
// 展开成 `(s) => ...(x)` 这种"箭头函数当场被调用"的形态，取到 null）
const evalJson = async (body) => JSON.parse(await run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  ${body}
})()`))

const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })

// ★ 演示身份（与老板实况一致；本仓教训：固定注入无订阅的 JWT ⇒ 业务 API 全 429）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', 'demo-token');
    localStorage.setItem('refresh_token', 'demo-refresh-token');
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }))});
  `,
})
await send('Page.navigate', { url: URL })

// ★ 等**具体元素**就绪，不用固定 sleep —— 刚做过 HMR/Vite 重编译时，固定等待会取到
//   空列表 ⇒ L0 全红（看着像功能坏了，其实是页面还没渲染完；本探针第一版实踩：12/14）。
let ready = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".agent-list .ant-menu-item").length')
  if (typeof n === 'number' && n >= 5) { ready = true; break }
  await sleep(1000)
}
if (!ready) {
  await shot('r315_00_boot_fail')
  console.log('FAIL: 左侧 Agent 列表未渲染（截图见 ' + SHOT_DIR + '）—— 先修环境（dev server / 登录态）')
  chrome.kill(); process.exit(1)
}

// ---- L0 自检：Agent 列表选到了
const agentProbe = await evalJson(`
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /运营复盘师/.test(e.textContent || ''))
  return JSON.stringify({ n: items.length, found: !!t })
`)
check('L0a', '左侧 Agent 列表渲染且含「运营复盘师」', agentProbe.n >= 5 && agentProbe.found, agentProbe)

await run(`(() => {
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /运营复盘师/.test(e.textContent || ''))
  if (t) t.click()
  return true
})()`)
// 等工具条渲染出来（同上：不用固定 sleep）
for (let i = 0; i < 20; i++) {
  const n = await run('document.querySelectorAll(".inline-toolbar .toolbar-tools .toolbar-tool-btn").length')
  if (typeof n === 'number' && n > 0) break
  await sleep(500)
}

// ---- ① 对话模式：功能栏工具按钮（title = "名字 — 描述"）
const tools = await evalJson(`
  return JSON.stringify([...document.querySelectorAll('.inline-toolbar .toolbar-tools .toolbar-tool-btn')]
    .map(b => b.getAttribute('title') || ''))
`)
check('L0b', '功能栏工具按钮渲染（选择器有效）', Array.isArray(tools) && tools.length > 0, tools)
const toolNames = (tools || []).map(t => String(t).split(' — ')[0].trim())
check('R1a', '功能栏工具卡恰好 5 个', toolNames.length === 5, toolNames)
check('R1b', '功能栏**没有**「广告数据」', !toolNames.includes('广告数据'), toolNames)
check('R1c', '功能栏名字集合 == 期望 5 个（正控：其余都在）',
  sameSet(toolNames, ['经营概览', '月度数据', '商品表现', '库存健康', '利润分析']), toolNames)

// ---- ② 技能 chip（来源是后端库行）
const chips = await evalJson(`
  return JSON.stringify([...document.querySelectorAll('.iab-chips .iab-chip')].map(c => norm(c.textContent)))
`)
check('L0c', '技能 chip 容器渲染（选择器有效）', Array.isArray(chips) && chips.length > 0, chips)
check('R2a', '**没有**「广告效果复盘」技能 chip',
  !(chips || []).some(c => String(c).includes('广告效果复盘')), chips)
check('R2b', '正控：同类技能 chip 仍在（周报 / 月度复盘 / 行动计划）',
  ['周报', '月度复盘', '行动计划'].some(x => (chips || []).some(c => String(c).includes(x))), chips)
await shot('r315_01_chat')

// ---- ③ 切大屏模式 → tab 栏
const switched = await run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  const b = [...document.querySelectorAll('.mode-switch-btn')].find(e => /大屏模式/.test(norm(e.textContent)))
  if (!b) return 'no-btn'
  b.click(); return 'clicked'
})()`)
await sleep(600)
// 等大屏 tab 渲染出来
for (let i = 0; i < 20; i++) {
  const n = await run('document.querySelectorAll(".rv-tabs .rv-tab").length')
  if (typeof n === 'number' && n > 0) break
  await sleep(500)
}
check('L0d', '顶栏「大屏模式」可切换', switched === 'clicked', switched)

const tabs = await evalJson(`
  return JSON.stringify([...document.querySelectorAll('.rv-tabs .rv-tab')].map(t => norm(t.textContent)))
`)
check('L0e', '大屏 tab 栏渲染（选择器有效）', Array.isArray(tabs) && tabs.length > 0, tabs)
// tab 文案形如「📈 广告复盘」（图标 + 空格 + 名称）⇒ 去掉前导图标与空白
const tabNames = (tabs || []).map(t => String(t).replace(/^[^\p{L}]+/u, '').trim())
check('R3a', '大屏 tab 恰好 5 个', tabNames.length === 5, tabNames)
check('R3b', '大屏 tab **没有**「广告复盘」', !tabNames.some(t => t.includes('广告复盘')), tabNames)
check('R3c', '大屏 tab 名字集合 == 期望 5 个',
  sameSet(tabNames, ['经营概览', '月度数据', '商品表现', '库存健康', '利润统计']), tabNames)

// ★ 大屏模式下顶部工具条应隐藏（模板 `!(isReviewAgent && reviewMode==='data')`）
const toolbarW = await run(`(() => {
  const e = document.querySelector('.inline-toolbar .toolbar-tools')
  if (!e) return 0
  return Math.round(e.getBoundingClientRect().width)
})()`)
check('R3d', '大屏模式下顶部工具条隐藏（宽度 0 / 不存在）', toolbarW === 0, toolbarW)
await shot('r315_02_data')

// ---- 汇总
const failed = results.filter(r => !r.ok).length
console.log(`\n---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(failed === 0 ? 0 : 1)

// CDP 真机探针（第 316 轮）—— 广告分析师退掉「异常检测」+「预算分配 / 广告预算再平衡」。
//
// 老板原话：「广告分析师删除异常检测、广告预算再平衡」；两项拍板：
//   · 广告预算再平衡 → **技能 + 预算分配卡全退**（第 189 轮已合并成一条）；
//   · 异常检测       → **前后端全退**（无历史归档表，留端点就是零调用假路径）。
//
// 为什么必须用真实浏览器（三处都是**渲染结果**，源码删了不等于界面不显示）：
//   ① 功能栏那排按钮来自 AGENT_TOOLS（卡已删，但按钮是 v-for 渲染的）；
//   ② 大屏 tab 来自 AdDashboardConfig.AD_TABS（且**只在** reviewMode==='data' 时渲染）；
//   ③ 技能 chip 来自**后端库行**（`RETIRED_DEMO_SKILLS` 清库后才消失）—— 前端改不动它。
//
// 判据口径（本仓纪律）：
//   · 每个集合判据都配一条 **L0 自检**（选择器真选到东西），否则选择器写错会静默全绿；
//   · 「删掉了 X」必须配一条**正控**（同类的东西还在）—— 只判「不含 X」的话，
//     页面白屏 / 选择器失效也照样绿；
//   · 数量与**名字集合**一起判：只判数量会让「删错一个、重名补回来一个」蒙混过关；
//   · 排序比较**两侧都排**（JS `.sort()` 按 UTF-16 码元，汉字不按拼音）。
//
// 用法：node scripts/cdp-r316-ad-retire.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9389
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r316_ad_retire')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
// ★ 三态：`true` 绿 / `false` 红 / **`null` 跳过**（第 316 轮补）。
//   `null` 只给「环境条件」用 —— 本轮实测：连着跑几轮探针会把后端限流配额打满
//   （60 次 / 60s），此时 `R3e` 的 `.ad-state` 是「读取失败 · 请求过于频繁」。
//   把它判红 = 把**环境**说成**面板坏了**（归因错方向）；判绿 = 骗自己这条验过了。
//   ⇒ 必须**显式 SKIP**：单独计数、单独打印，且不进"通过"里凑数。
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  const tail = ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)
  console.log(`${state}  ${id}  ${name}${tail}`)
}
const sameSet = (actual, expected) =>
  JSON.stringify([...actual].sort()) === JSON.stringify([...expected].sort())

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r316-'))
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
// 统一走这个：表达式内自带 norm（不要把 norm 源串插进表达式 —— 会展开成"箭头函数当场被调用"）
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

// ★ 演示身份（与老板实况一致；固定注入无订阅的 JWT ⇒ 业务 API 全 429）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', 'demo-token');
    localStorage.setItem('refresh_token', 'demo-refresh-token');
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }))});
  `,
})
await send('Page.navigate', { url: URL })

// ★ 等**具体元素**就绪（不用固定 sleep）
let ready = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".agent-list .ant-menu-item").length')
  if (typeof n === 'number' && n >= 5) { ready = true; break }
  await sleep(1000)
}
if (!ready) {
  await shot('r316_00_boot_fail')
  console.log('FAIL: 左侧 Agent 列表未渲染（截图见 ' + SHOT_DIR + '）—— 先修环境（dev server / 登录态）')
  chrome.kill(); process.exit(1)
}

// ---- L0a：Agent 列表选到了「广告分析师」
const agentProbe = await evalJson(`
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /广告分析师/.test(e.textContent || ''))
  return JSON.stringify({ n: items.length, found: !!t })
`)
check('L0a', '左侧 Agent 列表渲染且含「广告分析师」', agentProbe.n >= 5 && agentProbe.found, agentProbe)

await run(`(() => {
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /广告分析师/.test(e.textContent || ''))
  if (t) t.click()
  return true
})()`)
for (let i = 0; i < 20; i++) {
  const n = await run('document.querySelectorAll(".inline-toolbar .toolbar-tools .toolbar-tool-btn").length')
  if (typeof n === 'number' && n > 0) break
  await sleep(500)
}
// ★★ 技能 chip 必须**另等一轮**（第 316 轮实测：这两处不同步）。
//   功能栏按钮来自前端静态表 `AGENT_TOOLS` ⇒ 点完就有；而 chip 来自**后端库行** ——
//   `useAgentShortcuts` 里 `loadAll()`（`/skills` + `/agents` 并行）是异步的，
//   且 `currentBackendAgent` 还要等 `/agents` 回来才由 `''` 变成 `ad_analysis`。
//   不等它的下场是读到**空数组**：R2b「正控仍在」假红、R2c「恰好 1 条」也假红 ——
//   两条红的原因与「本轮退役改坏东西」毫无关系（本探针第一版就是这么挂的，实测 15/17）。
for (let i = 0; i < 40; i++) {
  const c = await run('document.querySelectorAll(".iab-chips .iab-chip").length')
  if (typeof c === 'number' && c > 0) break
  await sleep(500)
}

// ---- ① 对话模式：功能栏工具按钮（title = "名字 — 描述"）
const tools = await evalJson(`
  return JSON.stringify([...document.querySelectorAll('.inline-toolbar .toolbar-tools .toolbar-tool-btn')]
    .map(b => b.getAttribute('title') || ''))
`)
check('L0b', '功能栏工具按钮渲染（选择器有效）', Array.isArray(tools) && tools.length > 0, tools)
const toolNames = (tools || []).map(t => String(t).split(' — ')[0].trim())
check('R1a', '功能栏工具卡恰好 3 个（广告诊断 / 词报告 / 竞品广告；出价建议本就在排除集）',
  toolNames.length === 3, toolNames)
check('R1b', '功能栏**没有**「预算分配」', !toolNames.includes('预算分配'), toolNames)
check('R1c', '功能栏**没有**「异常检测」', !toolNames.includes('异常检测'), toolNames)
check('R1d', '功能栏名字集合 == 期望 3 个（正控：未被误删）',
  sameSet(toolNames, ['广告诊断', '词报告', '竞品广告']), toolNames)

// ---- ② 技能 chip（来源是后端库行）
const chipProbe = await evalJson(`
  const box = document.querySelector('.iab-chips')
  const chips = [...document.querySelectorAll('.iab-chips .iab-chip')].map(c => norm(c.textContent))
  return JSON.stringify({ boxExists: !!box, chips })
`)
const chips = chipProbe.chips
// ★ L0c 判「容器存在 **且** 非空」—— 上一版只判 `Array.isArray(chips)`：
//   空数组也是数组 ⇒ 恒真 = 空跑，chip 全丢了它照样绿（本仓「选择器写错会静默全绿」的翻版）。
check('L0c', '技能 chip 容器存在且已加载（空数组会让 R2a~R2c 全变空跑）',
  chipProbe.boxExists && Array.isArray(chips) && chips.length > 0, chipProbe)
if (!(chips || []).length) {
  // ★ 把「能力本身没配上」与「接口没拉到」分开报 —— 否则两种情况都只显示一个 `[]`，
  //   会得出相反结论（前者要改数据，后者只需重试/修环境）。
  const api = await run(`(async () => {
    try { const r = await fetch('/api/v1/skills'); const j = await r.json()
          return JSON.stringify({ status: r.status, total: (j.items || []).length }) }
    catch (e) { return 'ERR ' + String(e) }
  })()`)
  console.log('  ↳ 诊断：chip 为空 ⇒ /api/v1/skills 实况 = ' + api)
}
check('R2a', '**没有**「广告预算再平衡」技能 chip',
  !(chips || []).some(c => String(c).includes('广告预算再平衡')), chips)
check('R2b', '正控：广告侧保留的那条技能 chip 仍在（出价建议）',
  (chips || []).some(c => String(c).includes('出价建议')), chips)
check('R2c', '技能 chip 恰好 1 条（广告侧只剩 `ad-bid-suggest`）',
  (chips || []).length === 1, chips)
await shot('r316_01_chat')

// ---- ③ 切大屏模式 → AdDashboardConfig 的 tab 栏
const switched = await run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  const b = [...document.querySelectorAll('.mode-switch-btn')].find(e => /大屏模式/.test(norm(e.textContent)))
  if (!b) return 'no-btn'
  b.click(); return 'clicked'
})()`)
await sleep(600)
for (let i = 0; i < 20; i++) {
  const n = await run('document.querySelectorAll(".ad-tabs .ad-tab").length')
  if (typeof n === 'number' && n > 0) break
  await sleep(500)
}
check('L0d', '顶栏「大屏模式」可切换', switched === 'clicked', switched)

const tabs = await evalJson(`
  return JSON.stringify([...document.querySelectorAll('.ad-tabs .ad-tab')].map(t => norm(t.textContent)))
`)
check('L0e', '大屏 tab 栏渲染（选择器有效）', Array.isArray(tabs) && tabs.length > 0, tabs)
// tab 文案形如「📊 账户总览」（图标 + 空格 + 名称）⇒ 去掉前导图标与空白
const tabNames = (tabs || []).map(t => String(t).replace(/^[^\p{L}]+/u, '').trim())
check('R3a', '大屏 tab 恰好 4 个', tabNames.length === 4, tabNames)
check('R3b', '大屏 tab **没有**「预算分配」', !tabNames.some(t => t.includes('预算分配')), tabNames)
check('R3c', '大屏 tab **没有**「异常检测」', !tabNames.some(t => t.includes('异常检测')), tabNames)
check('R3d', '大屏 tab 名字集合 == 期望 4 个',
  sameSet(tabNames, ['账户总览', '搜索词', '出价优化', '竞品广告']), tabNames)

// ★ 正控：切到「出价优化」tab 仍能取到数（确认没把整块面板改坏）
//
// ★★ 第 316 轮反向注入实测修正：**上一版这条判据写弱了**。
//   它只 `if (.ad-state 数 === 0) break` 然后读 `.ad-pane >= 1` —— 而 `.ad-pane` 是四个
//   互斥 pane 共用的类名，**任何一个**在屏都算 ≥1；且点完 tab 后 `.ad-state` 可能还没
//   出现（请求尚未发出）就先 break 了 ⇒ 它读到的可能是**上一个** tab 的 pane。
//   反向注入（把「预算分配」tab 塞回来后）实测转红，但红的原因是 activeTab 落在一个
//   **没有对应 pane** 的 key 上 —— 也就是说它当时真的在判活性，只是判得含糊。
//   ⇒ 收紧成三条一起判：**激活的 tab 就是它**、**状态层已退出**、**pane 在屏**；
//     并把三个读数都放进 detail，红的时候能直接看出是哪一条不成立。
await run(`(() => {
  const b = [...document.querySelectorAll('.ad-tabs .ad-tab')].find(e => /出价优化/.test(e.textContent || ''))
  if (b) b.click(); return true
})()`)
let bidDiag = null
for (let i = 0; i < 40; i++) {
  bidDiag = await evalJson(`
    const active = document.querySelector('.ad-tabs .ad-tab.active')
    const st = document.querySelector('.ad-state')
    return JSON.stringify({
      activeTab: active ? norm(active.textContent) : null,
      panes: document.querySelectorAll('.ad-pane').length,
      state: st ? norm(st.innerText).slice(0, 80) : null,
    })
  `)
  if ((bidDiag.activeTab || '').includes('出价优化') && bidDiag.panes >= 1 && !bidDiag.state) break
  await sleep(500)
}
const bidOk = !!bidDiag && (bidDiag.activeTab || '').includes('出价优化') && bidDiag.panes >= 1 && !bidDiag.state
// ★ 限流是**环境**，不是面板缺陷：显式 SKIP，并在 detail 里写明原因与"没验到"这个事实。
//   若把 `null` 当成绿，这条正控就可能在"从来没真验过"的情况下一直看着没问题。
const bidSkipped = !bidOk && !!bidDiag && /请求过于频繁/.test(bidDiag.state || '')
check('R3e', '正控：切到「出价优化」后该 tab 激活且 pane 在屏（面板整体未改坏）',
  bidOk ? true : (bidSkipped ? null : false),
  bidSkipped
    ? { ...bidDiag, 说明: '后端限流（60 次/60s）⇒ 环境条件，非面板缺陷；本条**本轮未验到**，需间隔重跑' }
    : bidDiag)
await shot('r316_02_data')

// ---- 汇总（SKIP 单独计数，**不并进"通过"** —— 否则"没验到"会被读成"验过了"）
const failed = results.filter(r => r.ok === false).length
const skipped = results.filter(r => r.ok === null).length
const passed = results.filter(r => r.ok === true).length
console.log(`\n---- ${passed}/${results.length} 通过${skipped ? ` · SKIP ${skipped}（环境条件，未验到）` : ''}${failed ? ` · FAIL ${failed}` : ''} ----`)
if (skipped) console.log(`⚠️ SKIP 条目：${results.filter(r => r.ok === null).map(r => r.id).join(', ')} —— 间隔重跑后才算数`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(failed === 0 ? 0 : 1)

// CDP 真机探针（第 313 轮）—— 选品三工具在大屏模式下**都必须**进入整页大屏布局。
//
// 老板 09-29 现象（截图）：大屏模式下点「蓝海挖掘 / 利润测算」，页面**退回对话模式大小**，
//   但右侧边栏**又**挂着功能栏。
//
// 根因（静态读码）：
//   · 整页大屏布局认 `Workspace.isReviewDataMode = hasWideBoard && reviewMode==='data'`，
//     而 `hasWideBoard` 当时只收了 `isMarketInsightTool`（选品大盘）⇒ 点蓝海/利润时它变假：
//     根节点丢 `review-data-mode`、`.main-content` 回到全宽、`.right-panel` 缩回 340/528；
//   · 右栏顶部那排工具 Tab 栏认的是 `reviewMode === 'data'`（按 Agent 存，早就是 data）
//     ⇒ 照样显示。**同一判定两份实现**，于是出现"半大屏"的错位。
//
// 判据口径（本仓纪律）：
//   · 量的是 `getBoundingClientRect().width`（布局的真实结果），不是读 inline style；
//   · 每个"应为大屏"的状态都要有**同时**成立的三件事：根节点类、窄对话区、右栏吃剩余；
//   · 单侧为真不算 —— 只测一边的话，「只有 Tab 栏在、布局没切」也照样绿（那正是本 bug）。
//   · 对照臂：切回对话模式后 `.main-content` 必须**不再**是 400 ⇒ 证明那个 400 是大屏造成的，
//     而不是本来就 400（否则判据恒真）。
//
// 用法：node scripts/cdp-r313-product-research-wideboard.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9386
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r313_pr_wideboard')
// 与 src/config/layout.ts 的 PANEL_W.boardChat 同源（改宽度两处一起改）
const BOARD_CHAT = 400
// 登录态（第 314 轮改）：默认走**演示身份**，与老板实况一致。
//   ★ 原实现在这里固定注入 cdp-pay-probe 的 JWT —— 那个账号是为「扫码支付弹窗」
//     造的（无订阅）⇒ 业务 API 一律 429「订阅无效或已过期」⇒ 选品大盘永远空态，
//     热力图色块根本没渲染（判据全在量空容器，属于「量错了对象」）。
//   前端 .env.development 里 VITE_DEMO_MODE=true + `demo-token` 哨兵串 ⇒
//   后端 is_demo_credential 认它、解析成演示账号并给 mock 大盘。
//   PROBE_AUTH=jwt 回到旧行为（需先跑 cdp_pay_seed.py）。
const AUTH_MODE = process.env.PROBE_AUTH || 'demo'
const CTX = process.env.PROBE_CTX
  || 'D:\\ai\\eCommerce\\backend\\.workbuddy\\probes\\.cdp_pay_ctx.json'

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r313-'))
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

let AUTH
if (AUTH_MODE === 'demo') {
  // 演示身份：token 只需 `demo-` 前缀（后端只看前缀，身份由服务端解析）
  AUTH = {
    access_token: 'demo-token',
    refresh_token: 'demo-refresh-token',
    user_info: { id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' },
  }
  console.log('[auth] demo —— demo-token ⇒ 后端解析为演示账号，可拿 mock 大盘')
} else {
  if (!existsSync(CTX)) {
    console.log(`FAIL: 找不到登录上下文 ${CTX} —— 先跑 backend/.workbuddy/probes/cdp_pay_seed.py none`)
    chrome.kill(); process.exit(2)
  }
  const ctx = JSON.parse(readFileSync(CTX, 'utf8'))
  if (!ctx.access_token) { console.log('FAIL: 上下文里没有 access_token'); chrome.kill(); process.exit(2) }
  AUTH = {
    access_token: ctx.access_token,
    refresh_token: ctx.access_token,
    user_info: { id: ctx.user_id, email: ctx.email, name: 'CDP 探针', role: 'user' },
  }
  console.log('[auth] jwt —— 注意该账号可能无订阅（业务 API 429）')
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })

// ★ 登录态必须在**导航之前**注入。否则首屏带空 token ⇒ 停在登录页（bodyLen ≈ 50），
//   后面每个量测都取不到 `.right-panel`（读数是 -1）—— 那种『全红』看着像功能坏了，
//   其实是**注入失败**。所以下面 P0/P0b 两条自检必须先过，再看 R 系列。
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

// 一次量全（每个字段都会被下面的判据分别使用）
const measure = `
(() => {
  const root = document.querySelector('.workspace-container')
  const mc = document.querySelector('.main-content')
  const rp = document.querySelector('.right-panel')
  const tabs = document.querySelectorAll('.task-config-panel .aigc-tool-tabs')
  const toolbar = document.querySelector('.inline-toolbar .toolbar-tools')
  return JSON.stringify({
    rootClass: root ? String(root.className) : null,
    mainW: mc ? Math.round(mc.getBoundingClientRect().width) : -1,
    panelW: rp ? Math.round(rp.getBoundingClientRect().width) : -1,
    tabsN: tabs.length,
    boGrid: !!document.querySelector('.bo-content.data-layout'),
    prGrid: !!document.querySelector('.profit-content.data-layout'),
    boResultW: (() => { const e = document.querySelector('.bo-result'); return e ? Math.round(e.getBoundingClientRect().width) : -1 })(),
    prResultW: (() => { const e = document.querySelector('.profit-result-panel'); return e ? Math.round(e.getBoundingClientRect().width) : -1 })(),
    miSplit: !!document.querySelector('.mi-detail--split'),
    toolbarN: toolbar ? toolbar.getBoundingClientRect().width : -1,
    // 第 314 轮：选品大盘面板密度（黄条 / KPI 卡高 / 热力图与明细的并排几何）
    miBannerWarn: document.querySelectorAll('.mi-banner.warning').length,
    kpiHi: (() => { const e = document.querySelector('.kpi-card');
      return e ? Math.round(e.getBoundingClientRect().height) : -1 })(),
    miCard: (() => { const e = document.querySelector('.mi-treemap-card'); if (!e) return null;
      const b = e.getBoundingClientRect();
      return { w: Math.round(b.width), l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right) } })(),
    miSplitR: (() => { const e = document.querySelector('.mi-detail--split'); if (!e) return null;
      const b = e.getBoundingClientRect();
      return { w: Math.round(b.width), l: Math.round(b.left), t: Math.round(b.top) } })(),
    // ★ 量 .mi-treemap-body（空态与图表态共有）而不是 .mi-map：
    //   后者只在「有数据」时渲染，真实账号空态下取到 -1 ⇒ 判据假红。
    //   容器宽度与「有没有色块」无关，空态也能代表热力图将来的宽度。
    miBodyW: (() => { const e = document.querySelector('.mi-treemap-body');
      return e ? Math.round(e.getBoundingClientRect().width) : -1 })(),
    miMapW: (() => { const e = document.querySelector('.mi-map');
      return e ? Math.round(e.getBoundingClientRect().width) : -1 })(),
  })
})()`

const closeAll = `(() => {
  document.querySelectorAll('.ant-modal-close, .ant-drawer-close').forEach(b => b.click())
  return 'ok'
})()`

const M = async () => JSON.parse(await run(measure))

// ================================================================ 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('P0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// 选品分析师（默认工具 = 选品大盘 ⇒ 顶栏应出现「对话/大屏」切换）
await run(clickByText('选品分析师'))
await sleep(2200)
await run(closeAll)
await sleep(400)

const d0 = await M()
check('P0b', '.right-panel / .main-content 都存在（自检：量测目标选得到）',
  d0.mainW > 0 && d0.panelW > 0, d0)
// 对话模式基线截图（第 314 轮加）：老板同时要看「对话模式下面板长什么样」，
// 少了这张就没法对比 KPI 卡/明细在两种模式下的密度。
await shot('00-market-insight-chat')
// （原写法 `(await run(...)) !== null` 恒真 —— run 返回的是字符串，永远不为 null。
//   本仓纪律：自检判据自己也得能被反向注入打红。）
const hitData = JSON.parse(await run(clickByText('大屏模式')))
check('P0c', '顶栏出现「对话/大屏」切换（自检：选品大盘已选中）', hitData.ok === true, hitData)

// ================================================================ 大屏模式
await sleep(900)
const d1 = await M()
check('R1', `选品大盘·大屏：根节点带 review-data-mode + product-research-data-mode`,
  /review-data-mode/.test(d1.rootClass || '') && /product-research-data-mode/.test(d1.rootClass || ''), d1)
check('R2', `选品大盘·大屏：.main-content 压到 ${BOARD_CHAT}`,
  d1.mainW === BOARD_CHAT, d1)
check('R3', '选品大盘·大屏：.right-panel 吃剩余宽度（> 600，既非 340 也非 528）',
  d1.panelW > 600, d1)

// -------- 第 314 轮：面板密度（老板「取消黄条 / 卡片一堆空白 / 主要区域留给热力图」）
check('R3b', '★选品大盘：演示数据黄条已取消（.mi-banner.warning 计数为 0）',
  d1.miBannerWarn === 0, { miBannerWarn: d1.miBannerWarn })
check('R3c', '★选品大盘：KPI 卡已压成横排紧凑条（单卡高 <= 50px）',
  d1.kpiHi > 0 && d1.kpiHi <= 50, { kpiHi: d1.kpiHi })
// ★ 核心几何判据：只判 `.mi-detail--split` 在不在会假绿 —— flex-wrap 把明细
//   踹到第二行时它**照样在**（r313 已踩过同形坑）。必须量「同行顶部对齐 +
//   明细落在热力图右边界之外」= 真并排；退化（换行）时 top 差 ≈ 整个热力图高。
check('R3d', '★选品大盘：热力图与明细真并排（同行对齐 + 明细在热力图右边界之外）',
  !!d1.miCard && !!d1.miSplitR
    && Math.abs(d1.miCard.t - d1.miSplitR.t) < 8
    && d1.miSplitR.l >= d1.miCard.r - 2, d1)
check('R3e', '★选品大盘：热力图占主体（宽 >= 并排两列之和的 60%）',
  !!d1.miCard && !!d1.miSplitR && d1.miSplitR.w > 0
    && d1.miCard.w / (d1.miCard.w + d1.miSplitR.w) >= 0.6,
  { miCardW: d1.miCard && d1.miCard.w, miSplitW: d1.miSplitR && d1.miSplitR.w })
check('R3f', '★选品大盘：热力图容器够宽（.mi-treemap-body >= 600px，不是被挤成窄条）',
  d1.miBodyW >= 600, { miBodyW: d1.miBodyW, miMapW: d1.miMapW })
check('R3g', '选品大盘：色块真的渲染出来了（.mi-map 存在 ⇒ 不是空态）',
  d1.miMapW > 0, { miMapW: d1.miMapW })
await shot('01-market-insight-data')

// ---------------------------------------------------------------- 蓝海挖掘（老板报的两处之一）
await run(clickByText('蓝海挖掘'))
await sleep(1200)
const d2 = await M()
check('R4', '★蓝海挖掘·大屏：根节点仍带 review-data-mode + product-research-data-mode',
  /review-data-mode/.test(d2.rootClass || '') && /product-research-data-mode/.test(d2.rootClass || ''), d2)
check('R5', `★蓝海挖掘·大屏：.main-content 仍压到 ${BOARD_CHAT}（不能退回对话模式大小）`,
  d2.mainW === BOARD_CHAT, d2)
check('R6', '★蓝海挖掘·大屏：.right-panel 仍吃剩余宽度',
  d2.panelW > 600, d2)
// ★ 不能只判 `.data-layout` class 在不在：那个 class 只由 `reviewMode === 'data'` 决定，
//   整页布局退回对话模式时它**照样在**（在 340px 窄栏里硬塞两列）⇒ 恒真。
//   量大屏下右列真的够宽，退化时（≈280px）会红。
check('R7', '★蓝海挖掘·大屏：右栏内部真的分得开（结果窗口 >= 400px，不是挤在 340 窄栏里）',
  d2.boGrid === true && d2.boResultW >= 400, d2)
check('R8', '★蓝海挖掘·大屏：右栏工具 Tab 栏在（.aigc-tool-tabs）',
  d2.tabsN >= 1, d2)
check('R9', '蓝海挖掘·大屏：切走选品大盘后，大盘的右栏分栏已卸载（防"两份同时在"）',
  d2.miSplit === false, d2)
await shot('02-blue-ocean-data')

// ---------------------------------------------------------------- 利润测算（老板报的另一处）
await run(clickByText('利润测算'))
await sleep(1200)
const d3 = await M()
check('R10', '★利润测算·大屏：根节点仍带 review-data-mode + product-research-data-mode',
  /review-data-mode/.test(d3.rootClass || '') && /product-research-data-mode/.test(d3.rootClass || ''), d3)
check('R11', `★利润测算·大屏：.main-content 仍压到 ${BOARD_CHAT}`,
  d3.mainW === BOARD_CHAT, d3)
check('R12', '★利润测算·大屏：.right-panel 仍吃剩余宽度', d3.panelW > 600, d3)
check('R13', '★利润测算·大屏：右栏内部真的分得开（结果窗口 >= 400px）',
  d3.prGrid === true && d3.prResultW >= 400, d3)
check('R14', '利润测算·大屏：右栏工具 Tab 栏在', d3.tabsN >= 1, d3)
await shot('03-profit-calc-data')

// ================================================================ 对照臂：切回对话模式
await run(clickByText('对话模式'))
await sleep(1000)
const d4 = await M()
check('R15', '对照臂：切回「对话模式」后 .main-content **不再**是 400（证明 400 是大屏造成的）',
  d4.mainW !== BOARD_CHAT && d4.mainW > BOARD_CHAT, d4)
check('R16', '对照臂：对话模式下右栏回到固定档位（340 或 528），不再吃剩余宽度',
  d4.panelW === 340 || d4.panelW === 528, d4)
check('R17', '对照臂：对话模式下右栏工具 Tab 栏消失（大屏专属）', d4.tabsN === 0, d4)
// 对话模式下蓝海/利润也该是 528（拥有双模式能力 ⇒ 也加宽）；选品大盘同理
await shot('04-back-to-chat')

chrome.kill()

const failed = results.filter(r => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length} PASS / ${failed.length} FAIL / ${results.filter(r => r.state === 'SKIP').length} SKIP ----`)
console.log(`截图目录： ${SHOT_DIR}`)
if (failed.length) process.exit(1)
console.log('选品三工具大屏双模式真机验证通过（根节点类 / 窄对话区 / 右栏吃剩余 / 右栏分栏，四处同时成立 ✓）')

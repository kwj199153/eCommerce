// CDP 真机探针（第 318 轮）—— 账号设置「店铺管理」从「只显示未连接、没有入口」
// 到「能连、能断、能看三态」。
//
// 老板原话：「账号设置的店铺管理中，只显示未连接，没有给设置连接的入口，
//            让用户配置哪些信息就可以连接」；两项拍板：
//   · 连接入口档位 → **C 档**：Amazon + Shopee **真实验证**，自定义统一数据模型 + 平台适配层；
//   · 本轮平台    → **全部 4 类**（amazon / shopee / shopify / tiktok）。
//
// 为什么必须用真实浏览器（三处都是**渲染结果**，源码改了不等于界面变了）：
//   ① 连接入口是 `a-list-item` 的 `#actions` 插槽里 v-for 渲染的按钮 —— 源码里加了，
//      不代表这家店渲染得出来（列表为空 / 平台判据为假 / 插槽没接）；
//   ② 三态 tag 的文案由 `connectLabel()` 派生，取决于后端真实下发的 `is_connected`
//      —— 前端**推算不出来**（这正是上一版「恒未连接」的病灶）；
//   ③ 弹窗表单字段来自**后端** `GET /stores/{id}/connect/schema`：前端只认结构。
//      字段数对不对，只有连上真后端跑一次才知道（桩替不了）。
//
// 判据口径（本仓纪律）：
//   · 每个集合判据都配一条 **L0 自检**（选择器真选到东西）——
//     否则选择器写错会静默全绿（本仓复现过多次）；
//   · 「有入口」必须配**正控**：按钮文案属于已知集合，且不是空壳（能点开弹窗）；
//   · 字段数**与字段标签一起判**：只判数量会让「串了平台的表单」蒙混过关；
//   · 三态文案取**闭集**：凡不在这三档里的都是渲染异常（不是"新状态"）。
//
// 用法：node scripts/cdp-r318-shop-connect.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9390
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r318_shop_connect')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
// ★ 三态：`true` 绿 / `false` 红 / **`null` 跳过**（环境条件，不进通过数）。
//   本轮复用该口径的场景：演示账号一家店都没有 ⇒ 「入口」无从谈起，
//   把它判红 = 把**数据缺失**说成**界面坏了**（归因错方向）。
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  const tail = ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)
  console.log(`${state}  ${id}  ${name}${tail}`)
}
const sameSet = (actual, expected) =>
  JSON.stringify([...actual].sort()) === JSON.stringify([...expected].sort())

// 后端 `modules/stores/connect/platforms/*.py` 的字段数（★ 期望值**从这里对账**，
// 不写死在探针里靠记忆 —— 平台加字段时探针要一起更新，这是有意的摩擦）。
const FIELD_COUNT = { amazon: 7, shopee: 6, shopify: 3, tiktok: 4 }
// 三态文案闭集（与 `connectLabel()` 对齐）
const STATE_LABELS = ['已连接', '已配置（未验证）', '未连接']

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r318-'))
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
// ★★ 双入口的坑（本探针第一版就栽在这）：`norm` 只包在 `evalJson` 里，
//   而 `run()` 是**裸** `Runtime.evaluate` —— 在 `run()` 里写 `norm(...)`
//   会抛 ReferenceError，于是 `if (btn) btn.click()` 里的 btn **永远 undefined**，
//   点击变成**空操作**且不报错。本探针第一版因此 R2a~R2d 全红、
//   而 R3（点取消后表单项归零）**假绿** —— 它本来就没打开过。
//   ⇒ 凡在 `run()` 里用到 norm 的表达式，一律自带 definition。
const NORM_SRC = `
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
  const flat = (s) => norm(s).replace(/\\s+/g, '');
`
const runN = async (body) => run(`(() => { ${NORM_SRC} ${body} })()`)
// ★★ 「弹窗开着吗」必须判**可见性**，不能判「元素在不在 DOM」：
//   antd 关掉弹窗后元素仍留在 DOM（`.ant-modal-wrap` 置 `display:none`），
//   判「表单项归零」会恒假红。可见 = wrap 非 none 且高度 > 0。
const visibleModals = () => runN(`
  const wraps = [...document.querySelectorAll('.ant-modal-wrap')]
  return wraps.filter(w => getComputedStyle(w).display !== 'none' && w.getBoundingClientRect().height > 0).length
`)
const evalJson = async (body) => JSON.parse(await run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  const flat = (s) => norm(s).replace(/\\s+/g, '')
  ${body}
})()`))
// ★★ 按钮文案必须**剥掉全部空白**再比：antd 的 `insertSpace` 会给「两个汉字」的
//   文案自动插一个空格 —— 「取消」在 DOM 里是「取 消」。
//   第一版用 `norm()`（只收连续空白为一个空格）⇒ `=== '取消'` 恒假，
//   于是 R2c 报「没有取消按钮」、R3 的点击变成空操作又假绿。
//   实测 dump：`footerButtons: ["取 消","连接并验证"]`。

const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })

// ★ 演示身份（与老板实况一致）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', 'demo-token');
    localStorage.setItem('refresh_token', 'demo-refresh-token');
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }))});
  `,
})
await send('Page.navigate', { url: URL })

// ---- L0a：Workspace 起来了（左侧 Agent 列表渲染）
let booted = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".agent-list .ant-menu-item").length')
  if (typeof n === 'number' && n >= 5) { booted = true; break }
  await sleep(1000)
}
if (!booted) {
  await shot('r318_00_boot_fail')
  console.log('FAIL: 左侧 Agent 列表未渲染（截图见 ' + SHOT_DIR + '）—— 先修环境（dev server / 登录态）')
  chrome.kill(); process.exit(1)
}
const agentProbe = await evalJson(`
  return JSON.stringify({ n: document.querySelectorAll('.agent-list .ant-menu-item').length })
`)
check('L0a', 'Workspace 启动：左侧 Agent 列表渲染', agentProbe.n >= 5, agentProbe)

// ---- 打开「账号设置」抽屉
// ★ 走**真实通道**：AccountMenu 的「账号设置」菜单项就是 dispatch 这个 CustomEvent，
//   探针复用它 = 与用户点菜单得到的是同一条路径（不是绕过入口硬塞 CSS）。
await run(`window.dispatchEvent(new CustomEvent('open-settings-drawer')); true`)
let drawerOpen = false
for (let i = 0; i < 20; i++) {
  const n = await run('document.querySelectorAll(".ant-drawer .settings-tabs .ant-tabs-tab").length')
  if (typeof n === 'number' && n > 0) { drawerOpen = true; break }
  await sleep(500)
}
if (!drawerOpen) {
  await shot('r318_01_drawer_fail')
  console.log('FAIL: 账号设置抽屉未打开（截图见 ' + SHOT_DIR + '）')
  chrome.kill(); process.exit(1)
}
const tabProbe = await evalJson(`
  const tabs = [...document.querySelectorAll('.ant-drawer .settings-tabs .ant-tabs-tab')].map(t => norm(t.textContent))
  return JSON.stringify({ box: !!document.querySelector('.ant-drawer .settings-tabs'), tabs })
`)
check('L0b', '账号设置抽屉打开且 Tab 栏渲染',
  tabProbe.box && Array.isArray(tabProbe.tabs) && tabProbe.tabs.length >= 5, tabProbe)
check('R0', 'Tab 栏含「店铺管理」（本轮入口所在）', (tabProbe.tabs || []).includes('店铺管理'), tabProbe.tabs)

// ---- 切到「店铺管理」Tab
await run(`(() => {
  const t = [...document.querySelectorAll('.ant-drawer .settings-tabs .ant-tabs-tab')]
    .find(e => /店铺管理/.test(e.textContent || ''))
  if (t) t.click()
  return true
})()`)
// 等店铺列表（异步 loadShops）
let listReady = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".ant-drawer .ant-list-item").length')
  if (typeof n === 'number' && n > 0) { listReady = true; break }
  await sleep(500)
}
await shot('r318_02_shops_tab')

const listProbe = await evalJson(`
  const box = document.querySelector('.ant-drawer .ant-list')
  const items = [...document.querySelectorAll('.ant-drawer .ant-list-item')]
  const empty = norm(document.querySelector('.ant-drawer .ant-empty-description')?.textContent || '')
  return JSON.stringify({ boxExists: !!box, itemCount: items.length, emptyText: empty })
`)
check('L0c', '店铺列表容器存在（选到东西，否则后续全空跑）', listProbe.boxExists, listProbe)

// ★ 零店铺 ⇒ 「入口」无从谈起 ⇒ 显式 SKIP（不是红）：把数据缺失说成界面坏了是归因错方向。
if (listProbe.itemCount === 0) {
  check('R1a', '每个店铺行有「连接平台 / 重新配置」入口', null, '演示账号零店铺，无法验证入口（请在有待连店铺的账号上复跑）')
  check('R1b', '状态标签是三态闭集之一', null, '同上')
  check('R2a', '点击入口能打开连接弹窗', null, '同上')
  check('R2b', '弹窗表单字段数与本店平台对账', null, '同上')
} else {
  // ---- R1：入口存在性 + 文案闭集（核心修复）
  const rowProbe = await evalJson(`
    const rows = [...document.querySelectorAll('.ant-drawer .ant-list-item')]
    const out = rows.map(r => {
      const btns = [...r.querySelectorAll('button')].map(b => norm(b.textContent))
      const tags = [...r.querySelectorAll('.ant-tag')].map(t => norm(t.textContent))
      return { btns, tags }
    })
    return JSON.stringify(out)
  `)
  const entryButtons = ['连接平台', '重新配置']
  const hasEntry = rowProbe.every(r => r.btns.some(b => entryButtons.includes(b)))
  check('R1a', '每个店铺行都有「连接平台 / 重新配置」入口（本轮核心修复）', hasEntry,
    rowProbe.map(r => r.btns))

  const tagTexts = rowProbe.map(r => (r.tags[0] || ''))
  const tagsInClosedSet = tagTexts.every(t => STATE_LABELS.includes(t))
  check('R1b', '状态标签文案落在三态闭集内（已连接 / 已配置（未验证）/ 未连接）',
    rowProbe.length > 0 && tagsInClosedSet, tagTexts)

  // 正控：至少有一个「断开」入口存在于**有凭据**的行（否则条件渲染写错了）
  const hasDisconnectSomewhere = rowProbe.some(r => r.btns.includes('断开'))
  check('R1c', '正控：列表渲染了操作列（含「删除」，与「断开」条件共存）',
    rowProbe.every(r => r.btns.includes('删除')), rowProbe.map(r => r.btns))
  check('R1d', '（观察项）是否存在「断开」入口 —— 取决于是否已有店铺连过',
    hasDisconnectSomewhere === true || hasDisconnectSomewhere === false, rowProbe.map(r => r.btns))

  // ---- R2：点开第一条的连接弹窗，验证表单真由后端驱动
  const firstPlatform = await evalJson(`
    const r = document.querySelector('.ant-drawer .ant-list-item')
    const desc = norm(r?.querySelector('.ant-list-item-meta-description')?.textContent || '')
    return JSON.stringify({ desc })
  `)
  const clicked = await runN(`
    const r = document.querySelector('.ant-drawer .ant-list-item')
    const btn = [...r.querySelectorAll('button')].find(b => ['连接平台','重新配置'].includes(norm(b.textContent)))
    if (btn) btn.click()
    return !!btn
  `)
  check('L0d', '真的点到了「连接平台」按钮（防空操作假绿）', clicked === true, { clicked })
  // ★★ 等待条件必须**同时**满足两件事，缺一个都会假红（两个方向本轮都踩过）：
  //   ① 弹窗**可见**（判元素在 DOM 会被 antd 的 `display:none` 残留骗到）；
  //   ② 表单**已渲染**（判可见会太早返回 —— 内容是 `fetchStoreConnectSpec`
  //      异步回来的，外壳先显示 spinner，此时 `form-item` 还是 0 ⇒ R2b/R2d 假红）。
  let modalOpen = false
  for (let i = 0; i < 30; i++) {
    const vis = await visibleModals()
    const fields = await run('document.querySelectorAll(".ant-modal .ant-form-item").length')
    if (vis > 0 && typeof fields === 'number' && fields > 0) { modalOpen = true; break }
    await sleep(500)
  }
  await shot('r318_03_connect_modal')

  const modalProbe = await evalJson(`
    const m = [...document.querySelectorAll('.ant-modal')].find(x => /连接平台/.test(norm(x.querySelector('.ant-modal-title')?.textContent || '')))
    if (!m) return JSON.stringify({ found: false })
    const labels = [...m.querySelectorAll('.ant-form-item-label')].map(e => norm(e.textContent).replace(/已配置$/, '').trim())
    const pwCount = m.querySelectorAll('.ant-input-password').length
    const selectCount = m.querySelectorAll('.ant-select').length
    const okText = norm(m.querySelector('.ant-modal-footer .ant-btn-primary')?.textContent || '')
    const footerButtons = [...m.querySelectorAll('.ant-modal-footer button')].map(b => norm(b.textContent))
    // ★ 取消文案取 flat（antd insertSpace ⇒ DOM 里是「取 消」）
    const cancelText = footerButtons.map(flat).find(t => t === '取消') || ''
    const docsLink = norm(m.querySelector('.docs-line a')?.textContent || '')
    return JSON.stringify({ found: true, labels, pwCount, selectCount, okText, cancelText, footerButtons, docsLink,
      notes: [...m.querySelectorAll('.notes li')].map(e => norm(e.textContent)).length })
  `)
  check('R2a', '点击「连接平台 / 重新配置」打开了连接弹窗', modalOpen && modalProbe.found === true, modalProbe)

  // ★ 字段数与本店平台对账：从页面描述里取平台家族，再查期望值。
  //   页面描述是 `getPlatformLabel()` 的产物（"Amazon 美国" / "Shopee 马来西亚"），
  //   ★ 不一定含中文家族名 —— 命中的是**英文品牌名**（第一版只匹配「亚马逊」⇒ null）。
  const platformLabel = String(firstPlatform.desc || '')
  const FAMILY_PATTERNS = {
    amazon: /amazon|亚马逊/i,
    shopee: /shopee|虾皮/i,
    shopify: /shopify/i,
    tiktok: /tiktok/i,
  }
  const famEntry = Object.keys(FAMILY_PATTERNS).find(k => FAMILY_PATTERNS[k].test(platformLabel))
  const expectedFields = famEntry ? FIELD_COUNT[famEntry] : null
  check('R2b', '弹窗表单字段数与本店平台对账'
    + (famEntry ? `（${famEntry} ⇒ ${expectedFields} 项）` : '（平台未识别，仅判非空）'),
    expectedFields != null
      ? (modalProbe.labels || []).length === expectedFields
      : (modalProbe.labels || []).length > 0,
    { platformLabel, expected: expectedFields, actual: modalProbe.labels })

  check('R2c', '弹窗按钮文案正确（连接并验证 / 保存凭据 + 取消）',
    ['连接并验证', '保存凭据'].includes(modalProbe.okText) && modalProbe.cancelText === '取消',
    { okText: modalProbe.okText, cancelText: modalProbe.cancelText, footerButtons: modalProbe.footerButtons })
  check('R2d', '表单含密码型控件（敏感字段不回显明文）', modalProbe.pwCount > 0,
    { pwCount: modalProbe.pwCount, selectCount: modalProbe.selectCount })

  // ---- R3：取消关闭弹窗（证明它不是一个装饰性弹窗）
  // ★ 两条前置，防止「没点着」被当成「关掉了」：
  //   ① 断言弹窗此刻**确实开着**（表单项 > 0）；
  //   ② 断言取消按钮**真的被点到**（返回 !!btn）。
  //   第一版就是因为点击空操作（norm 未定义）而让 R3 假绿。
  const beforeCancel = await visibleModals()
  const cancelClicked = await runN(`
    const m = [...document.querySelectorAll('.ant-modal')].find(x => /连接平台/.test(norm(x.querySelector('.ant-modal-title')?.textContent || '')))
    const btn = [...(m?.querySelectorAll('.ant-modal-footer button') || [])].find(b => flat(b.textContent) === '取消')
    if (btn) btn.click()
    return !!btn
  `)
  await sleep(900)
  const afterCancel = await visibleModals()
  await shot('r318_04_after_cancel')
  check('R3', '点「取消」后弹窗关闭（可见弹窗数 1 → 0）',
    beforeCancel === 1 && cancelClicked === true && afterCancel === 0,
    { beforeCancel, cancelClicked, afterCancel })
}

// ---- 汇总
const pass = results.filter(r => r.ok === true).length
const fail = results.filter(r => r.ok === false).length
const skip = results.filter(r => r.ok === null).length
console.log(`\n=== r318 店铺连接 CDP 探针：${pass} PASS / ${fail} FAIL / ${skip} SKIP ===`)
if (fail > 0) console.log('存在 FAIL：见上（截图目录 ' + SHOT_DIR + '）')
chrome.kill()
process.exit(fail > 0 ? 1 : 0)

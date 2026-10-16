// CDP 真机探针（第 371 轮 · 每日经营简报 / 能力广场）
//
// 为什么这一段必须真机跑（静态门禁与单测**结构上**覆盖不到）：
//   ① `check-briefing-wiring.cjs` 是**源码形态**门禁 —— 它能证明「计数绑的是表达式、
//      @click 会打开抽屉」，但证明不了「打开抽屉真的渲染出后端那 9 条明细」。
//   ② `briefingStore.test.ts` 跑在 `environment: 'node'`（本项目不装 jsdom），
//      它钉的是 store 的赋值语义；`api/briefings` 被整份 mock 掉了 ——
//      于是「HTTP 路径 / 响应字段 / 归属头」这三段**一次都没被真跑过**。
//   ③ 本轮最危险的形态恰恰在②与①的缝隙里：**徽标与列表来自不同实现**。
//      store 的用例全绿、门禁全绿，而真机上可能「徽标说 1 条、点开是空的」。
//
// 所以本探针全程用**真后端**（不桩任何网络）：读的就是 `daily_briefings` 那 4 行，
// 且每条判据都拿**接口读数**当期望值 —— 不手写数字（手写期望正是「期望值过期
// 伪装成真回归」的来源）。
//
// 被测对象是**真代码**：真 dev server 上的真 Workspace（真 `NotificationBell`
// 挂在 `a-layout-header` 里，真 `AbilityPlazaDrawer` 挂在侧栏菜单上）。
//
// ★ 已知的假红陷阱（照抄既有探针的血泪，缺一个就会误判）：
//   ① **抽屉关着时 DOM 仍在**（antd 默认 `destroyOnClose=false`）。
//      ⇒ 判「打开了没」必须看 `ant-drawer-open` 状态类，不能判「元素存在」。
//   ② **`localStorage` 要在导航前注入**，且换了店铺必须**重新导航** ——
//      `request.ts` 的 `X-Shop-ID` 是从 `localStorage` 每次现读的，
//      但 `shopStore.currentShopId` 是**启动时读一次**的 ref。
//   ③ 探针自身失效（工作台没起来 / 后端没跑）⇒ 退出码 **2**，不并进 PASS/FAIL。
//
// 判据分组：
//   B* 铃铛与简报抽屉（含**两条负控**：只打开不展开 ⇒ 未读数不动；标记已读 ⇒ 服务端也动）
//   A* 能力广场（侧栏入口 → 抽屉 → 分组/卡片 → 点卡片切回对话）
//   C* 空态诚实性（没有简报的店铺 ⇒ 说「还没有」而不是「加载失败」）
//
// 跑法：node scripts/cdp-r371-briefing-bell.mjs
//   前置：后端 8000 在跑、前端 dev server 5173 在跑。
//   PROBE_URL / PROBE_SHOP / PROBE_SHOT_DIR 可覆盖。

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9412
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
/** 有简报的店铺（`daily_briefings` 里 4 行之一） */
const SHOP = process.env.PROBE_SHOP || 'store_a498a7d5'
/** 空态那组用的店铺由 C 组**现场探测**选出（见 C0），不写死 —— 理由见 C0 的注释 */
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r371')
/** 抽屉标题（两处 UI 文案的真源；改文案时这里必须同步 —— 它是判据的定位串） */
const BELL_TITLE = '每日经营简报'
const PLAZA_TITLE = '能力广场'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`PROBE-ERR: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r371-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', 'about:blank',
], { stdio: 'ignore' })

const bail = async (msg, code = 2) => {
  console.log(`PROBE-ERR  ${msg}`)
  console.log(`\n---- ${results.filter((r) => r.state === 'PASS').length} PASS / `
    + `${results.filter((r) => r.state === 'FAIL').length} FAIL / `
    + `${results.filter((r) => r.state === 'SKIP').length} SKIP（探针无效，退出码 ${code}）----`)
  try { chrome.kill() } catch { /* 已退出 */ }
  process.exit(code)
}

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
if (!page) await bail('headless chrome 没起来（拿不到 page target）')

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
  const ex = r?.result?.exceptionDetails
  if (ex) throw new Error((ex.exception?.description || ex.text || '').slice(0, 300))
  return r?.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}
const waitFor = async (expr, ms = 25000, step = 150) => {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await run(expr)) return true } catch { /* 渲染中途 */ }
    await sleep(step)
  }
  return false
}

const clickAt = async (x, y) => {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none', buttons: 0 })
  await sleep(60)
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1 })
  await sleep(50)
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1 })
}
const rectOf = async (sel) => await run(
  `(() => {
     const e = document.querySelector(${JSON.stringify(sel)})
     if (!e) return null
     const r = e.getBoundingClientRect()
     return { top: r.top, left: r.left, width: r.width, height: r.height }
   })()`,
)
const clickSel = async (sel) => {
  const r = await rectOf(sel)
  if (!r || !r.width) throw new Error(`不可点的元素：${sel}`)
  await clickAt(Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2))
}

/** ★ 真后端读数（页面内 fetch，走 dev server 代理到 :8000；带真实 X-Shop-ID） */
const apiBriefings = async (shop) => {
  const txt = await run(
    `fetch('/api/v1/briefings', { headers: { 'X-Shop-ID': ${JSON.stringify(shop)} } }).then(r => r.text())`,
  )
  try { return JSON.parse(txt) } catch { return { __raw: String(txt).slice(0, 200) } }
}

/** 抽屉是否**打开**：判 antd 自己的状态类，不判元素是否存在（关着时 DOM 还在） */
const drawerOpenExpr = (needle) => `!![...document.querySelectorAll('.ant-drawer')].find(
  d => (d.innerText || '').includes(${JSON.stringify(needle)}) && d.className.includes('ant-drawer-open'))`

/** 徽标数字（0 条时 antd 不渲染节点 ⇒ 读回 0，而不是 null）。
 *
 * ★ 为什么不能直接读 sup 的 `textContent`：antd 的 `SingleNumber` 是**数字滚筒**，
 *   内部会为 `value..value+10` 生成 11 个「数字格」（`.ant-scroll-number-only-unit`），
 *   只有一个是 `.current`。整段 `textContent` 是那一串数字的**拼接**
 *   （实测读数会变成 12345678901 这种），换个位数就是另一个数 ——
 *   于是「徽标读数」变成了「滚筒内部结构读数」，判据随机化。
 *   ⇒ 只取 `.current` 那一格；并用 `display` 判隐藏（0 条时 antd 用样式藏，不是删节点）。
 */
const badgeCountExpr = `(() => {
  const b = document.querySelector('.nb-bell')?.closest('.ant-badge')
  if (!b) return null
  const sup = b.querySelector('.ant-badge-count')
  if (!sup) return 0
  if (getComputedStyle(sup).display === 'none') return 0
  const unit = sup.querySelector('.ant-scroll-number-only-unit.current')
  const raw = unit ? unit.textContent : sup.textContent
  return Number(String(raw || '').replace(/\\D/g, '')) || 0
})()`

/** 诊断用：失败时把徽标的真实 DOM 形态一并打出来（免得下次又要靠猜） */
const badgeDumpExpr = `(() => {
  const b = document.querySelector('.nb-bell')?.closest('.ant-badge')
  if (!b) return { badge: false }
  const sup = b.querySelector('.ant-badge-count')
  if (!sup) return { sup: false }
  const units = [...sup.querySelectorAll('.ant-scroll-number-only-unit')]
  return {
    sup: true,
    cls: String(sup.className),
    display: getComputedStyle(sup).display,
    current: units.filter(u => u.className.includes('current')).map(u => u.textContent),
    units: units.length,
    text: String(sup.textContent || '').slice(0, 24),
  }
})()`

// ---------------------------------------------------------------------------
// 启动 + 演示身份 + 指定店铺
// ---------------------------------------------------------------------------
const AUTH = {
  access_token: 'demo-token',
  refresh_token: 'demo-refresh-token',
  user_info: { id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' },
}
await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })

const bootScript = (shop) => `
  localStorage.setItem('access_token', ${JSON.stringify(AUTH.access_token)});
  localStorage.setItem('refresh_token', ${JSON.stringify(AUTH.refresh_token)});
  localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify(AUTH.user_info))});
  localStorage.setItem('current_shop_id', ${JSON.stringify(shop)});
`
const boot = await send('Page.addScriptToEvaluateOnNewDocument', { source: bootScript(SHOP) })
await send('Page.navigate', { url: URL })

if (!await waitFor(`!!document.querySelector('.ant-layout') && (document.body.innerText || '').length > 200`, 40000)) {
  await shot('00-boot-fail')
  await bail('Workspace 没渲染出来（dev server / 路由 / 演示身份有问题）')
}

// ---------------------------------------------------------------------------
// B 组：铃铛 —— 徽标数字必须与**接口读数**一致
// ---------------------------------------------------------------------------
const before = await apiBriefings(SHOP)
if (before.__raw != null || !Array.isArray(before.items)) {
  await bail(`/api/v1/briefings 没回预期 JSON（后端没跑？）：${JSON.stringify(before).slice(0, 200)}`)
}

check('B1', '铃铛是**可点元素**（真组件，不是原来的死图标）', !!(await rectOf('.nb-bell')), await rectOf('.nb-bell'))
await waitFor(badgeCountExpr + ' !== null', 8000)
const badge0 = await run(badgeCountExpr)
check('B2', '★ 徽标数字 == 接口的 unread（**同一份事实**，不是各自算的）',
  badge0 === before.unread, { badge: badge0, api: before.unread })

// 打开抽屉（真实鼠标点击）
await clickSel('.nb-bell')
const opened = await waitFor(drawerOpenExpr(BELL_TITLE), 8000)
check('B3', `点击铃铛 → 「${BELL_TITLE}」抽屉打开`, opened, { open: await run(drawerOpenExpr(BELL_TITLE)) })
await shot('01-bell-drawer')

// 负控：只打开、不展开 ⇒ 服务端未读数**不许**变
const afterOpen = await apiBriefings(SHOP)
check('B4', '★ 负控：只打开抽屉**不**改服务端未读数（「展开才算读过」）',
  afterOpen.unread === before.unread, { before: before.unread, afterOpen: afterOpen.unread })

// 列表内容与接口对账
const cardCount = await run(`document.querySelectorAll('.nb-card').length`)
check('B5', '抽屉里的简报条数 == 接口 items 条数',
  cardCount === before.items.length, { dom: cardCount, api: before.items.length })

const firstSummary = await run(`document.querySelector('.nb-card .nb-summary')?.textContent?.trim() || ''`)
check('B6', '首条的摘要逐字来自后端（不是前端拼的）',
  firstSummary === (before.items[0]?.summary || ''), { dom: firstSummary, api: before.items[0]?.summary })

// 展开第一条 ⇒ 明细条数 == item_count
await clickSel('.nb-card .nb-card-head')
await waitFor(`document.querySelectorAll('.nb-card .nb-item').length > 0`, 6000)
const itemCount = await run(`document.querySelectorAll('.nb-card .nb-item').length`)
const expectItems = before.items[0]?.item_count
check('B7', '展开首条 ⇒ 明细条数 == 后端 item_count',
  itemCount === expectItems, { dom: itemCount, api: expectItems })
const firstText = await run(`document.querySelector('.nb-card .nb-item-text')?.textContent?.trim() || ''`)
check('B8', '明细文案逐字来自后端（`text` 字段）',
  firstText === (before.items[0]?.items?.[0]?.text || ''), { dom: firstText })
await shot('02-bell-expanded')

// 徽标 -1，且**服务端也 -1**（这是「不伪成功」的核心）
// ★ 给数字滚筒的过渡留时间：比值，而不是比 DOM 的某一瞬间
await waitFor(`${badgeCountExpr} === ${Math.max(0, before.unread - 1)}`, 3000)
const badge1 = await run(badgeCountExpr)
const afterRead = await apiBriefings(SHOP)
// ★ 若这家店本来就是全已读（上一轮跑过 / 人工点过），「减一」这条**测不到** ——
//   此时报 SKIP 而不是 FAIL：判据为空跑时不许伪装成通过，也不许伪装成回归。
const canDec = before.unread > 0
check('B9', '展开后徽标减一',
  canDec ? badge1 === before.unread - 1 : null,
  canDec
    ? { before: before.unread, now: badge1, dom: await run(badgeDumpExpr) }
    : { 说明: '该店起点未读=0，减一不可测', badge: badge1 })
check('B10', '★ 服务端未读数**也**减一（不是只改了界面）',
  canDec ? afterRead.unread === before.unread - 1 : null,
  canDec ? { before: before.unread, serverNow: afterRead.unread } : { 说明: '该店起点未读=0，减一不可测' })
const stillUnreadDot = await run(
  `!!document.querySelector('.nb-card .nb-dot--unread')`,
)
check('B11', '该条的未读圆点消失（已读态落到界面）', stillUnreadDot === false, { stillUnread: stillUnreadDot })

// ---------------------------------------------------------------------------
// A 组：能力广场（侧栏入口 → 抽屉 → 分组/卡片 → 点卡片切回对话）
// ---------------------------------------------------------------------------
/** 按文案找侧栏菜单项（类名定位在 check-sidebar-layout 里另有一条）。
 *  ★ 必须**先滚进视口**再取矩形：侧栏 8 个数字员工 + 资料库一长串，
 *    900px 高的视口里「能力广场」在折叠线以下 —— 直接按 rect 点会落在**别的元素**上，
 *    症状是「入口明明在，点了没反应」（探针第一次跑就是这么假红的）。 */
const menuItemExpr = (text) => `(() => {
  const it = [...document.querySelectorAll('.ant-menu-item')]
    .find(e => (e.innerText || '').trim().includes(${JSON.stringify(text)}))
  if (!it) return null
  it.scrollIntoView({ block: 'center' })
  const r = it.getBoundingClientRect()
  return { top: r.top, left: r.left, width: r.width, height: r.height }
})()`

// ★ 必须先关掉简报抽屉：它的**遮罩**盖住整页，侧栏点不到 ——
//   探针第一次跑就是这么假红的（入口明明在，点了没反应）。
if (await rectOf('.ant-drawer-close')) {
  await clickSel('.ant-drawer-close')
  await waitFor(`!(${drawerOpenExpr(BELL_TITLE)})`, 6000)
  // ★ 「抽屉关了」≠「遮罩没了」：antd 的遮罩有 ~300ms 的 leave 动画，
  //   期间它**仍在 DOM 里、仍吃指针** —— 实测 A1b 的 elementFromPoint 正好
  //   指到 `ant-drawer-mask-motion-leave-active`。这是侧栏点不到的全部原因，
  //   而不是「入口没生效」。（先看到这条再改代码，就不会去改对的实现。）
  await waitFor(`!document.querySelector('.ant-drawer-mask')`, 6000)
}
const plazaItem = await run(menuItemExpr(PLAZA_TITLE))
check('A1', `侧栏存在「${PLAZA_TITLE}」入口`, !!plazaItem, plazaItem)
// ★ 前置自证：简报抽屉若还开着，它的**遮罩**会吃掉这次点击 ——
//   症状是「入口明明在，点了没反应」。把它列成判据，不靠 waitFor 沉默兜住。
const bellStillOpen = await run(drawerOpenExpr(BELL_TITLE))
check('A1c', '前置：简报抽屉已关闭（遮罩不会吃掉侧栏点击）', !bellStillOpen, { open: bellStillOpen })
if (plazaItem) {
  const px = Math.round(plazaItem.left + plazaItem.width / 2)
  const py = Math.round(plazaItem.top + plazaItem.height / 2)
  // ★ 落点自证：「点了没反应」有两种归因（被浮层挡住 / 坐标算错），
  //   这条判据一次分清 —— 否则只能靠猜，而猜错的方向就是去改本来正确的代码。
  const hit = await run(`(() => {
    const e = document.elementFromPoint(${px}, ${py})
    if (!e) return null
    return {
      cls: String(e.className || '').slice(0, 40),
      txt: String(e.textContent || '').trim().slice(0, 16),
      inMenuItem: !!e.closest('.ant-menu-item'),
    }
  })()`)
  // ★ 口径是「点落在菜单项**内部**」而不是「最上层元素就是菜单项」：
  //   菜单项里套着 `<span class="ant-menu-title-content">能力广场</span>`，
  //   按 `cls.includes('ant-menu-item')` 判会把**正确**的点判成失败（本轮实测）
  check('A1b', '点击落点未被遮挡（elementFromPoint 落在菜单项内部）',
    !!hit && hit.inMenuItem === true, { at: { px, py }, hit })
  await clickAt(px, py)
}
const plazaOpen = await waitFor(drawerOpenExpr(PLAZA_TITLE), 8000)
check('A2', `点击 → 「${PLAZA_TITLE}」抽屉打开`, plazaOpen, { open: await run(drawerOpenExpr(PLAZA_TITLE)) })

const groupCount = await run(`document.querySelectorAll('.ap-group').length`)
const cardTotal = await run(`document.querySelectorAll('.ap-card').length`)
check('A3', '广场按「数字员工」分组陈列，且卡片总数为正',
  groupCount > 0 && cardTotal > 0, { groups: groupCount, cards: cardTotal })
const groupTitles = await run(
  `[...document.querySelectorAll('.ap-group-title')].map(e => e.textContent.trim())`,
)
check('A4', '分组标题有名有值，且与分组数一致（逐字取自后端 Agent 目录）',
  // ★ `length > 0` 必须有：A3 失败时 groupTitles 是空数组，
  //   而 `every()` 在空数组上恒真、`0 === 0` 也成立 ⇒ 空跑**假绿**（本轮实测）
  Array.isArray(groupTitles) && groupTitles.length > 0 && groupTitles.length === groupCount
  && groupTitles.every((t) => typeof t === 'string' && t.trim().length > 0), { titles: groupTitles })
await shot('03-plaza-drawer')

const firstCardTitle = await run(`document.querySelector('.ap-card-title')?.textContent?.trim() || ''`)
// ★ 抽屉没打开时 `.ap-card` 不存在 —— 报 SKIP（`ok===null`），而不是让 clickSel
//   抛异常把整支探针打断（那样后面的 C 组一条都跑不到，「假红」会掩盖真读数）
if (plazaOpen && (await rectOf('.ap-card'))) {
  // ★ 先滚进视口再点：卡片住在抽屉可滚动区里，拿 rect 直接点可能落在视口外
  const crect = await run(`(() => {
    const c = document.querySelector('.ap-card')
    if (!c) return null
    c.scrollIntoView({ block: 'center' })
    const r = c.getBoundingClientRect()
    const cx = Math.round(r.left + r.width / 2)
    const cy = Math.round(r.top + r.height / 2)
    const e = document.elementFromPoint(cx, cy)
    return { cx, cy, w: Math.round(r.width), h: Math.round(r.height),
             inCard: !!e && !!e.closest('.ap-card'),
             hitCls: e ? String(e.className || '').slice(0, 40) : null }
  })()`)
  check('A4b', '卡片的点击落点未被遮挡（elementFromPoint 落在卡片内部）',
    !!crect && crect.inCard === true, crect)
  await clickAt(crect.cx, crect.cy)
  const plazaClosed = await waitFor(`!(${drawerOpenExpr(PLAZA_TITLE)})`, 6000)
  const drawersDump = await run(`[...document.querySelectorAll('.ant-drawer')].map(d => ({
    cls: String(d.className).slice(0, 60),
    plaza: (d.innerText || '').includes(${JSON.stringify(PLAZA_TITLE)}),
  }))`)
  check('A5', '点一张能力卡 ⇒ 广场抽屉自动关闭', plazaClosed, { drawers: drawersDump })
  const chatMounted = await waitFor(`!!document.querySelector('.chat-panel')`, 8000)
  check('A6', '点卡片后切回对话视图（ChatPanel 真的挂载了，不是静默丢弃）', chatMounted)
  const pickedVisible = await waitFor(
    `(document.body.innerText || '').includes(${JSON.stringify(firstCardTitle)})`, 6000,
  )
  check('A7', '被点的那条能力在对话页可见（技能名出现在界面上）', pickedVisible, { card: firstCardTitle })
} else {
  check('A5', '点一张能力卡 ⇒ 广场抽屉自动关闭', null, { 说明: '抽屉没打开，A5–A7 不可测' })
  check('A6', '点卡片后切回对话视图', null, { 说明: '同上' })
  check('A7', '被点的那条能力在对话页可见', null, { 说明: '同上' })
}
await shot('04-plaza-picked')

// ---------------------------------------------------------------------------
// C 组：空态诚实性（换个没有简报的店铺 ⇒ 说「还没有」而不是「加载失败」）
// ---------------------------------------------------------------------------
// ★ 前置：演示身份**只绑定了 4 家店铺**，且四家全都有简报（实测）——
//   写死一个假 shop id 会被后端判 403（"无权访问该店铺"），那是**前置失败**
//   而不是「空态撒谎」。所以这里自动挑一个「可访问且 0 条」的；
//   挑不到就 SKIP —— 空跑不许伪装成通过。
const emptyCandidates = [process.env.PROBE_EMPTY_SHOPS || '', 'store_16f776b2', 'store_27a9e7ec', 'store_c3529ab1']
  .join(',').split(',').map((s) => s.trim()).filter((s) => s && s !== SHOP)
let emptyShop = null
for (const cand of emptyCandidates) {
  const probe = await apiBriefings(cand)
  if (Array.isArray(probe.items) && probe.items.length === 0) { emptyShop = cand; break }
}
// ★ 这一条是**环境前置**（不是产品判据）⇒ 拿不到时报 SKIP 而不是 FAIL：
//   「没有空店铺可测」是探针的取样限制，报 FAIL 会让它变成一条**常驻假红**，
//   而常驻假红的下场是整条探针被关掉 —— 那才是真的没有门禁。
check('C0', '前置：存在「可访问且 0 条简报」的店铺（空态真机可达）',
  emptyShop !== null ? true : null,
  emptyShop ? { shop: emptyShop } : { 说明: '演示身份绑定的店铺全部有简报 ⇒ 空态不可达', tried: emptyCandidates })
if (emptyShop === null) {
  check('C1', '该店铺接口确实返回 0 条（前置：这是空态而不是失败）', null, { 说明: '无可达空店铺' })
  check('C2', '无未读时徽标**不显示**（0 条不渲染数字）', null, { 说明: '同上' })
  check('C3', '★ 空态说「还没有简报…」而不是「加载失败」', null, { 说明: '同上' })
  await shot('05-bell-empty-skipped')
}
await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: boot.result.identifier })
await send('Page.addScriptToEvaluateOnNewDocument', { source: bootScript(emptyShop || SHOP) })
await send('Page.navigate', { url: URL })
if (!await waitFor(`!!document.querySelector('.nb-bell')`, 40000)) {
  await bail('换店铺后 Workspace 没渲染出来')
}
if (emptyShop !== null) {
const emptyApi = await apiBriefings(emptyShop)
check('C1', '该店铺接口确实返回 0 条（前置：这是空态而不是失败）',
  Array.isArray(emptyApi.items) && emptyApi.items.length === 0, emptyApi)
const badgeEmpty = await run(badgeCountExpr)
check('C2', '无未读时徽标**不显示**（0 条不渲染数字）', badgeEmpty === 0, { badge: badgeEmpty })
await waitFor(`!!document.querySelector('.nb-bell')`, 5000)
await clickSel('.nb-bell')
await waitFor(drawerOpenExpr(BELL_TITLE), 8000)
const emptyTxt = await run(
  `(() => {
     const d = [...document.querySelectorAll('.ant-drawer')].find(x => (x.innerText || '').includes(${JSON.stringify(BELL_TITLE)}))
     return d ? d.innerText : ''
   })()`,
)
check('C3', '★ 空态说「还没有简报…」而不是「加载失败」（空态不得撒谎）',
  emptyTxt.includes('还没有简报') && !emptyTxt.includes('加载失败'), { text: String(emptyTxt).slice(0, 120) })
await shot('05-bell-empty')
}

// ---------------------------------------------------------------------------
try { chrome.kill() } catch { /* 已退出 */ }
const p = results.filter((r) => r.state === 'PASS').length
const f = results.filter((r) => r.state === 'FAIL').length
console.log(`\n---- ${p} PASS / ${f} FAIL / ${results.filter((r) => r.state === 'SKIP').length} SKIP ----`)
console.log(`截图：${SHOT_DIR}`)
process.exit(f ? 1 : 0)

// 验收「两条死路由做成可访问页面」+「头像品牌绿压深」（第 323 轮）。
//
// 背景 —— 两条路由此前直接访问是**空白页**，根因两个（都跟直觉相反）：
//   · /settings：`Settings.vue` 把 `open` 声明成**必填**（`open: boolean`）⇒
//     路由不传 ⇒ `a-drawer` 永远关着。
//   · /memory  ：`props.open ?? true` 是**结构性死代码** —— `defineProps<{open?: boolean}>()`
//     编译出的运行时类型是 `Boolean`，Vue 会把「缺席」强制转成 `false`（不是 `undefined`）
//     ⇒ `false ?? true === false`。
// 修法：两处都改成 `withDefaults(defineProps<{ open?: boolean }>(), { open: undefined })`
// + 「路由模式（open 缺席）」分支：自行打开、关闭时退回 `/`。
//
// 本探针要盯的**三件矩阵管不到的事**：
//   1. 路由模式下抽屉**真的开**（不是白页），且内容真渲染出来了；
//   2. 路由模式下点关闭 ⇒ **退回工作台**（不是停在只剩背景色的空白路由上）；
//   3. **抽屉模式没被改坏**：在 `/` 上开抽屉、关抽屉，路径必须**始终是 `/`**。
//      （这条最容易被漏：把 `open` 改成可选 + 加 ROUTE_MODE 分支，
//        稍不注意就会让 Workspace 里的抽屉也去 push('/')。）
//
// 用法：node scripts/cdp-r323-drawer-routes.mjs
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9353
const BASE = 'http://127.0.0.1:5173'
const SHOT_DIR = 'D:/ai/eCommerce/.workbuddy/probes/r323_shots'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const el = () => String(Date.now() - t0).padStart(6) + 'ms'

mkdirSync(SHOT_DIR, { recursive: true })

// demo 身份：与 `cdp-contrast-matrix.mjs` 的 BOOT 同源（键名取自 src/config/demoMode.ts +
// src/stores/tour.ts）。不注入的话 `/settings` `/memory` 的 requiresAuth 守卫会弹登录页。
const BOOT = [
  'try {',
  "  localStorage.setItem('access_token', 'demo-token');",
  "  localStorage.setItem('refresh_token', 'demo-refresh-token');",
  "  localStorage.setItem('theme_mode', 'light');",
  "  localStorage.setItem('user_info', JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }));",
  "  localStorage.setItem('onboarding_tour_v1', JSON.stringify({ v: 1, seen: true, lastIndex: 0, ts: Date.now() }));",
  '} catch (e) {}',
].join('\n')

const profile = mkdtempSync(join(tmpdir(), 'cdp-r323-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  '--window-size=1440,900',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-gpu',
  '--disable-extensions',
  'about:blank',
], { stdio: 'ignore' })

const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 300s，强制退出')
  try { chrome.kill() } catch { /* ignore */ }
  process.exit(2)
}, 300000)

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
    if (targets.some((t) => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) { console.log('FAIL: no page target'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
const pageErrors = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails
    pageErrors.push(String(d.exception?.description || d.text || '').slice(0, 300))
  }
})
const send = (method, params = {}) => new Promise((res) => {
  const id = ++seq
  pending.set(id, (m) => res(m.result ?? m.error ?? null))
  ws.send(JSON.stringify({ id, method, params }))
})
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
await send('Runtime.enable')
await send('Page.enable')

/** 裸表达式求值（**不要**在这里用 evalJson 才有的 helper —— 作用域不同，会 ReferenceError） */
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
  if (r?.exceptionDetails) return { __err: String(r.exceptionDetails.exception?.description || '').slice(0, 200) }
  return r?.result?.value
}
const shot = async (name) => {
  try {
    const r = await send('Page.captureScreenshot', { format: 'png' })
    if (r?.data) writeFileSync(join(SHOT_DIR, name), Buffer.from(r.data, 'base64'))
  } catch { /* 截图失败不影响判定 */ }
}

// ---- 探针作用域自检（skill 坑 ①）----
const scopeCheck = await run("typeof norm + '|' + typeof visibleTextEls")
console.log('探针自检（两个都应为 undefined）:', scopeCheck)

// ---- 页面级快照 ----
const SNAP = `(() => {
  const ds = [...document.querySelectorAll('.ant-drawer')]
  const open = ds.filter((d) => d.classList.contains('ant-drawer-open'))
  const body = open[0]?.querySelector('.ant-drawer-body')
  return JSON.stringify({
    path: location.pathname,
    drawerCount: ds.length,
    openCount: open.length,
    title: (open[0]?.querySelector('.ant-drawer-title')?.innerText || '').trim(),
    bodyLen: (body?.innerText || '').replace(/\\s+/g, ' ').trim().length,
    body: (body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
  })
})()`
const snap = async () => {
  const raw = await run(SNAP)
  if (raw?.__err) return { __err: raw.__err }
  try { return JSON.parse(raw) } catch (e) { return { __err: 'parse: ' + String(e) } }
}

const nav = async (path) => {
  const add = await send('Page.addScriptToEvaluateOnNewDocument', { source: BOOT })
  await send('Page.navigate', { url: BASE + path })
  for (let i = 0; i < 25; i++) {
    const p = await run('location.pathname')
    if (p === path) break
    await sleep(400)
  }
  await sleep(1800)
  return add?.identifier
}

const click = async (sel) => await run(
  `(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return false; b.click(); return true })()`,
)

const results = []
const check = (id, desc, ok, got) => {
  results.push({ id, desc, ok: !!ok, got })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${desc}  ⟵ ${JSON.stringify(got)}`)
}

// ============================================================
// A. 路由模式：/settings 直接访问
// ============================================================
console.log('\n===== A. /settings 路由模式 =====')
let id = await nav('/settings')
let s = await snap()
console.log('  ', el(), JSON.stringify(s))
await shot('A1_settings_page.png')
check('A1', '/settings 不是空白页：抽屉已打开', s.openCount === 1, s)
check('A2', '/settings 标题 = 账号设置', s.title === '账号设置', s.title)
check('A3', '/settings 内容真渲染（含 6 个 tab）',
  typeof s.body === 'string' && s.body.includes('个人资料') && s.body.includes('客服语音'), s.body)
check('A4', '/settings 无未捕获异常', pageErrors.length === 0, pageErrors.slice(0, 3))

// 关闭 ⇒ 退回工作台
const okClose = await click('.ant-drawer-close')
for (let i = 0; i < 25; i++) {
  const p = await run('location.pathname')
  if (p === '/') break
  await sleep(400)
}
const afterClose = await run('location.pathname')
check('A5', '/settings 点关闭 ⇒ 退回 /（不是停在空白路由）', okClose && afterClose === '/', { okClose, afterClose })
if (id) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: id })

// ============================================================
// B. 路由模式：/memory 直接访问
// ============================================================
console.log('\n===== B. /memory 路由模式 =====')
id = await nav('/memory')
s = await snap()
console.log('  ', el(), JSON.stringify(s))
await shot('B1_memory_page.png')
check('B1', '/memory 不是空白页：抽屉已打开', s.openCount === 1, s)
check('B2', '/memory 标题 = 记忆与进化', s.title === '记忆与进化', s.title)
// ★ 正文长度**不写死阈值**：demo 身份下后端返 401，这里渲染的是错误卡片
//   （"长期记忆加载失败 / 无效的认证凭据 / 重试 / 去登录"）—— 那是**认真实登录用户**
//   会看到的失败态，不是空白。真实登录用户看到的是数据。（写死"必须含某段数据文案"
//   会变成钉住 demo 环境的负资产。）
check('B3', '/memory 有正文（非空白；demo 下是如实报错态）',
  typeof s.body === 'string' && s.bodyLen >= 8, s.body)
check('B4', '/memory 无未捕获异常', pageErrors.length === 0, pageErrors.slice(0, 3))

const okClose2 = await click('.ant-drawer-close')
for (let i = 0; i < 25; i++) {
  const p = await run('location.pathname')
  if (p === '/') break
  await sleep(400)
}
const afterClose2 = await run('location.pathname')
check('B5', '/memory 点关闭 ⇒ 退回 /', okClose2 && afterClose2 === '/', { okClose2, afterClose2 })
if (id) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: id })

// ============================================================
// C. 抽屉模式没被改坏：在 / 上开/关抽屉，路径必须始终是 /
// ============================================================
console.log('\n===== C. 抽屉模式（Workspace 挂载）=====')
id = await nav('/')
const c0 = await snap()
check('C0', '/ 上初始无打开的抽屉', c0.openCount === 0, c0)

// 走**真实入口**：账户菜单里的「设置」发的就是这个事件（src/components/Sidebar/AccountMenu.vue::openSettings）
await run("window.dispatchEvent(new CustomEvent('open-settings-drawer'))")
for (let i = 0; i < 20; i++) {
  const x = await snap()
  if (x.openCount === 1) break
  await sleep(300)
}
const c1 = await snap()
await shot('C1_workspace_drawer_open.png')
check('C1', '/ 上设置抽屉能打开（抽屉模式仍生效）', c1.openCount === 1, c1)
check('C2', '抽屉模式下路径仍是 /（没被路由模式分支带走）', c1.path === '/', c1.path)

const okClose3 = await click('.ant-drawer-close')
await sleep(1200)
const c2 = await snap()
check('C3', '抽屉模式关闭后抽屉收起', okClose3 && c2.openCount === 0, { okClose3, openCount: c2?.openCount })
check('C4', '抽屉模式关闭后路径**仍**是 /（关键回归点）', c2.path === '/', c2.path)
if (id) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: id })

// ============================================================
// D. 头像品牌绿（旧绿必须清干净，新绿必须到位）
// ============================================================
console.log('\n===== D. 头像品牌绿 =====')
const av = await run(`(() => {
  const a = document.querySelector('.account-entry .avatar')
  if (!a) return JSON.stringify({ found: false })
  const bg = getComputedStyle(a).backgroundImage
  const c = getComputedStyle(a).color
  return JSON.stringify({ found: true, bg, color: c })
})()`)
let avj = null
try { avj = JSON.parse(av) } catch { /* ignore */ }
await shot('D1_avatar.png')
check('D1', '侧栏头像存在', !!avj?.found, avj)
check('D2', '头像渐变已压深（rgb(44, 132, 9) / rgb(35, 120, 4)）',
  !!avj?.bg && avj.bg.includes('44, 132, 9') && avj.bg.includes('35, 120, 4'), avj?.bg)
check('D3', '旧亮绿 rgb(82, 196, 26) 已清干净', !!avj?.bg && !avj.bg.includes('82, 196, 26'), avj?.bg)

// ============================================================
clearTimeout(watchdog)
chrome.kill()

const bad = results.filter((r) => !r.ok)
console.log(`\n===== ${results.length - bad.length}/${results.length} PASS =====`)
console.log(`★ VERDICT routes=${results.slice(0, 10).every((r) => r.ok)} drawerMode=${results.slice(10, 15).every((r) => r.ok)} avatarGreen=${results.slice(15).every((r) => r.ok)}`)
console.log(`★ PASS=${bad.length === 0}`)
console.log(`截图目录：${SHOT_DIR}`)
process.exit(bad.length === 0 ? 0 : 1)

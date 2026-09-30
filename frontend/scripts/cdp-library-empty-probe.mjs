// CDP 真实浏览器端到端（第 280 轮）—— 知识库三页的「空态 / 失败态」口径。
//
// 为什么必须用真实浏览器：本轮把 5 处空态口径收进了 `common/AsyncEmpty.vue`，
// 但「组件写对了」不等于「页面上真的显示了那句人话」——
//   · 表格类页面（ProductLibrary / CandidateLibrary）要靠 `#emptyText` 插槽**换掉**
//     antd 自带的「暂无数据」，插槽名写错不会报错、只会什么都不渲染；
//   · 三页的失败态都挂在 `store.loadError` 上，而 store 的 catch 是否真跑到、
//     `loadError` 是否真被读，静态门禁看不出来。
//
// 判据口径（本仓纪律）：
//   · 先自检「侧栏菜单项真的选到东西」（L1），否则 selector 写错会静默全绿。
//   · 三页**逐页独立**判：每一页都必须自己说「加载失败」，不许别的页说了就顶替（V1）。
//   · **排他**判据：失败态下**不得**出现「XX为空」的空态文案（V3）——
//     「暂无」与「加载失败」并存正是本轮要根除的那个自相矛盾。
//   · **反假数据**判据（V4）：页面上不得有任何真实数据行/卡（读口被拦，有数据就是灌了 mock）。
//
// 用法：
//   node scripts/cdp-library-empty-probe.mjs
//   先跑 backend/.workbuddy/probes/cdp_pay_seed.py none 取一份有效登录态（复用其 token）。
//
//   PROBE_BASE     覆盖前端地址（默认 http://127.0.0.1:5173）
//   PROBE_LIB_CTX  覆盖登录上下文 json（默认后端探针目录的 .cdp_pay_ctx.json）
//   PROBE_LIB_SHOT 覆盖截图目录
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9353
const BASE = process.env.PROBE_BASE || 'http://127.0.0.1:5173'
const CTX = process.env.PROBE_LIB_CTX || 'D:\\ai\\eCommerce\\backend\\.workbuddy\\probes\\.cdp_pay_ctx.json'
const SHOT_DIR = process.env.PROBE_LIB_SHOT || join(process.cwd(), '..', '.workbuddy', 'probes', 'r280_cdp')

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
if (!existsSync(CTX)) { console.log(`FAIL: 找不到登录上下文 ${CTX} —— 先跑 cdp_pay_seed.py none`); process.exit(2) }
const ctx = JSON.parse(readFileSync(CTX, 'utf8'))
if (!ctx.access_token) { console.log('FAIL: 上下文里没有 access_token'); process.exit(2) }

// 三个知识库视图：侧栏文案取自 components/Sidebar/KnowledgeBase.vue
const VIEWS = [
  {
    key: 'candidates', label: '选品库', label2: '候选池',
    failed: '选品库加载失败，请重试', emptyMark: '选品库为空',
    kind: 'table', shot: 'r280_empty_candidates.png',
  },
  {
    key: 'assets', label: '营销素材库', label2: '素材库',
    failed: '素材库加载失败，请重试', emptyMark: '素材库为空',
    kind: 'grid', shot: 'r280_empty_assets.png',
  },
  {
    key: 'products', label: '自有产品库', label2: '产品库',
    failed: '产品库加载失败，请重试', emptyMark: '产品库为空',
    kind: 'table', shot: 'r280_empty_products.png',
  },
]

// 三个库的读口（含分组接口）—— 全部拦死，等价于"接口挂了 / 断网"
const BLOCKED = [
  '*api/v1/spus*', '*api/v1/skus*', '*api/v1/product-groups*',
  '*api/v1/assets*', '*api/v1/asset-groups*',
  '*api/v1/candidates*', '*api/v1/candidate-groups*',
]

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail)}`)
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-lib-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  '--window-size=1440,900',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking',
  'about:blank',
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
if (!page) { console.log('FAIL: 拿不到调试目标'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise(res => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })

const run = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 300)
  return r.result?.result?.value
}
const runJson = async expr => {
  const raw = await run(expr)
  if (typeof raw !== 'string' || raw.startsWith('EXC:')) return { __err: String(raw) }
  try { return JSON.parse(raw) } catch { return { __err: `不是 JSON: ${String(raw).slice(0, 200)}` } }
}
const shot = async file => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r.result?.data) {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, Buffer.from(r.result.data, 'base64'))
    return true
  }
  return false
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

// ★ 登录态在**导航前**注入（否则首屏会带空 token 打一轮，刷 401 噪音）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', ${JSON.stringify(ctx.access_token)});
    localStorage.setItem('refresh_token', ${JSON.stringify(ctx.access_token)});
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: ctx.user_id, email: ctx.email, name: 'CDP 空态探针', role: 'user' }))});
  `,
})

// ★ 拦截必须在 navigate **之前**开：三个库都在 onMounted 里首轮取数，
//   晚了就拦不到（那轮请求已经打完了）。
await send('Network.enable')
await send('Network.setBlockedURLs', { urls: BLOCKED })

const URL = `${BASE}/`
await send('Page.navigate', { url: URL })
console.log(`url = ${URL} | 拦截 ${BLOCKED.length} 条读口规则`)

// ---------- L0：Workspace 外壳 ----------
let shellReady = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".sidebar-nav-menu").length')
  if (typeof n === 'number' && n >= 1) { shellReady = true; break }
  await sleep(500)
}
check('L0', 'Workspace 外壳与资料库侧栏渲染出来了（.sidebar-nav-menu）', shellReady, { url: URL })
if (!shellReady) {
  await shot(join(SHOT_DIR, 'r280_empty_boot_fail.png'))
  console.log('FAIL: 页面没渲染出来 —— 先修环境')
  chrome.kill(); process.exit(1)
}

// ---------- L1：侧栏菜单项自检（selector 写错会静默全绿） ----------
const menuLabels = await runJson(`(() => {
  const items = [...document.querySelectorAll('.sidebar-nav-menu .ant-menu-item')]
  return JSON.stringify({ labels: items.map(e => e.textContent.replace(/\\s+/g, '')) })
})()`)
const labels = Array.isArray(menuLabels.labels) ? menuLabels.labels : []
const missing = VIEWS.filter(v => !labels.some(l => l.includes(v.label) || l.includes(v.label2))).map(v => v.label)
check('L1', '三个资料库入口都在侧栏里（自检：selector 没选错）', missing.length === 0 && labels.length >= 3,
  { labels, missing })

/** 切到某个视图（点侧栏菜单项），返回是否点中 */
async function gotoView(v) {
  const r = await runJson(`(() => {
    const items = [...document.querySelectorAll('.sidebar-nav-menu .ant-menu-item')]
    const hit = items.find(e => {
      const t = e.textContent.replace(/\\s+/g, '')
      return t.includes(${JSON.stringify(v.label)}) || t.includes(${JSON.stringify(v.label2)})
    })
    if (!hit) return JSON.stringify({ ok: false })
    hit.click()
    return JSON.stringify({ ok: true })
  })()`)
  return r.ok === true
}

/** 采样当前视图的空态/数据面 */
async function scanView() {
  return runJson(`(() => {
    const empties = [...document.querySelectorAll('.ant-empty-description')]
      .map(e => e.textContent.replace(/\\s+/g, ' ').trim())
    const btns = [...document.querySelectorAll('button')]
      .map(b => b.textContent.replace(/\\s+/g, '').trim()).filter(Boolean)
    return JSON.stringify({
      empties,
      retryBtns: btns.filter(t => t === '重试').length,
      dataRows: document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length,
      cards: document.querySelectorAll('.asset-card').length,
      rawText: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 400),
    })
  })()`)
}

// ---------- 逐视图判定 ----------
for (const v of VIEWS) {
  console.log(`\n=================== 视图 ${v.key}（${v.label}）===================`)
  const clicked = await gotoView(v)
  if (!clicked) {
    check(`V0-${v.key}`, `能切到「${v.label}」视图`, false, { menuLabels })
    continue
  }

  // 等失败态上屏（Vue 渲染 + 请求被拦 + catch ⇒ loadError）
  let state = null
  for (let i = 0; i < 40; i++) {
    state = await scanView()
    if (!state.__err && Array.isArray(state.empties) && state.empties.some(t => t.includes('加载失败'))) break
    await sleep(400)
  }
  if (!state || state.__err) { check(`V0-${v.key}`, `读取「${v.label}」空态面`, false, state); continue }

  const joined = (state.empties || []).join(' ｜ ')
  check(`V1-${v.key}`, `「${v.label}」读失败时说明「${v.failed}」`,
    (state.empties || []).includes(v.failed), state)

  check(`V2-${v.key}`, `「${v.label}」失败态给了「重试」出口`,
    state.retryBtns >= 1, { retryBtns: state.retryBtns, empties: state.empties })

  // ★ 排他：失败时**不许**出现空态文案（「暂无」与「加载失败」并存是自相矛盾）
  check(`V3-${v.key}`, `「${v.label}」失败态**没有**混进空态文案（不许说「${v.emptyMark}」）`,
    !joined.includes(v.emptyMark), { empties: state.empties })

  // ★★ 唯一性：失败态必须是页面上**唯一**的空态说明。
  //    这条专门抓「表格自带的『暂无数据』与我们的失败说明并排」——
  //    V3 只认我们自己的空态措辞，抓不到 antd 自带那句；两句摆一起同样是自相矛盾。
  check(`V5-${v.key}`, `「${v.label}」失败态是页面上**唯一**的空态说明（不与 antd 自带「暂无数据」并列）`,
    (state.empties || []).length === 1 && state.empties[0] === v.failed, { empties: state.empties })

  // ★ 反假数据：读口被拦，页面上就不该有任何真实数据
  check(`V4-${v.key}`, `「${v.label}」读失败时**没有**任何数据行/卡（没灌 mock）`,
    state.dataRows === 0 && state.cards === 0, { dataRows: state.dataRows, cards: state.cards })

  await shot(join(SHOT_DIR, v.shot))
}

// ---------- 汇总 ----------
const failed = results.filter(r => !r.ok)
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
chrome.kill()
if (failed.length) {
  console.log(`FAIL: ${failed.length} 条`)
  process.exit(1)
}
console.log('PASS: 三个知识库的失败态都如实上屏、且都没混进空态文案、也都没灌假数据')

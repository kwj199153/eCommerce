// CDP 真机探针 —— **全路由 × 全主题 对比度矩阵体检**
//
// 为什么要有这一条（= 它补的洞）
// ============================
// `cdp-dark-contrast.mjs` 已经把「对比度怎么算」做对了（合成链 / 渐变全色标 / alpha 合成 /
// 引擎自检 / 跨主题配对），但它有**一个结构性的盲区**：
//
//     const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/subscription'
//
// —— **一次只体检一个路由**，点名判据还只列了两页。于是本仓的实际验收面是：
//
//     全站 8 条路由 × 3 主题 = 24 格        探针实跑：1 格（订阅页）
//
// 剩下 23 格只能靠**人眼**。这就是「发现一处改一处」的机制性根因：
// **改法早就是收敛的（改 presets.ts 的 token，一处改三主题生效），
//   不收敛的是「发现」—— 它依赖老板截图。**
//
// 本探针把「发现」也变成机器活：24 格全跑，任何一格的「看不见」（< 3:1）都点名到
// `路由 | 主题 | 选择器 | 文案 | 实测比值`，不必等人报告。
//
// 与既有门禁的分工（四条防线，各管一段，不重叠）
// ============================================
//   · `check-theme-boot.py`       生产者侧：主题清单 / 首帧兜底色 跨文件一致
//   · `check-theme-var-refs.py`   消费者侧：`var(--x)` 的**名字**是否存在
//   · `check-hardcoded-pastel.py` 静态全仓：`background` 里的**硬编码粉彩亮底**
//   · **本探针**                  唯一能判「同一句 `color: var(--text-primary)`
//                                 在浅色对、在深色错」的一条 ——
//                                 因为它带着**当时是哪个主题 + 什么底色**一起量
//   · `cdp-dark-contrast.mjs`     单页深挖版（可带 PROBE_DRIVE 点开默认不挂载的面板）
//                                 ⇒ 矩阵管**广度**，它管**深度**
//
// 实测（第 321 轮首跑，24 格）它一次抓出 3 件既有 4 条门禁全漏的事：
//   ① `ChatPanel .input-hint` 三主题全 < 3:1（1.84 / 2.28 / 1.75）——
//      **token 语义误用**：常驻提词用了 `--text-disabled`。名字存在 ⇒ var-refs 过；
//      不是 background ⇒ 硬编码门禁过；不在订阅页 ⇒ 单页探针过。**四条全漏。**
//   ② `/settings` 与 `/memory` **整页空白**（bodyLen=0）—— 它们是抽屉组件
//      （模板根节点是 `<a-drawer :open>`）却被注册成了路由。
//   ③ `/team` 被守卫弹去 `/login` ⇒ 那一格**从来没被体检过**，而旧探针不会告诉你。
//
// 判据口径（沿用本仓纪律，逐条都有理由）
// ================================
//   ① 对比度 = WCAG 相对亮度公式；正文 ≥ 4.5:1、大字 ≥ 3:1；
//   ② 背景取**元素自身到 root 的完整合成链**（含渐变全部色标）并取**最差的**那个色标；
//   ③ `color` 带 alpha 时先**合成到背景**再算（否则 `rgba(255,255,255,.45)` 被当成纯白，
//      算出虚高的比值 —— 深色下「灰得很浅看不清」就是这么算假的）；
//   ④ **判定项只钉 `< 3:1`**（"看不见"的硬门槛）。`3:1 ~ need` 的 AA 缺口**打印但不判定**
//      —— 本仓存在**数学上到不了 AA** 的已知取舍（macaron 的 `--text-tertiary` 被
//      `--text-secondary` 4.72:1 天花板压到 3.82:1）。把它入判定 ⇒ 永久红 ⇒
//      整条门禁会被关掉，那才是最坏结果。
//   ⑤ **必须区分三种"没量到"**，混在一起就会得出相反结论（判据里记过的那条）：
//        · `auth`  被守卫弹去登录页 ⇒ **该页需要真身份，demo 下不可体检**
//        · `blank` 页面渲染了但 0 个文字节点 ⇒ **空白页**（真缺陷）
//        · `wrong` 落在了第三个路径 ⇒ **探针量错了对象**（最严重，必须红）
//      —— 三种都进"未覆盖"台账；前两种允许**逐条写豁免**，第三种直接红。
//   ⑥ 每格配 **L0 自检**（主题真生效 / 真扫到节点 / 无未捕获异常），否则静默全绿。
//   ⑦ 棘轮白名单**每条必须真的命中**，否则报红（防"永久免检区"）。
//
// 用法
// ====
//   node scripts/cdp-contrast-matrix.mjs           判定（有非豁免 `<3:1` ⇒ 退出码 1）
//   node scripts/cdp-contrast-matrix.mjs --report  只打印盘面、不判定（先量后定阈值）
//   PROBE_ROUTES=/subscription,/settings   只跑指定路由（默认全路由）
//   PROBE_THEMES=light,dark                只跑指定主题（默认三主题）
//   PROBE_BASE=http://127.0.0.1:5173       覆盖站点地址
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9392
const BASE = (process.env.PROBE_BASE || 'http://127.0.0.1:5173').replace(/\/$/, '')

// ★ 路由清单必须与 `src/router/index.ts` 对账 —— 本清单是**一份副本**，
//   新增路由忘了加进来 = 新页面天然免检（"新页面天然免检"是这条门禁最可能的失效方式）。
//   `check-contrast-matrix-coverage.cjs` 把这条对账钉成静态门禁：
//   它从 router/index.ts 抠出所有 `path: '...'`，逐个要求在本文件里出现。
const DEFAULT_ROUTES = [
  '/',
  '/team',
  '/settings',
  '/subscription',
  '/memory',
  '/login',
  '/reset-password',
  '/verify-email',
]
const DEFAULT_THEMES = ['light', 'dark', 'macaron']

// 「非空白」下限：空白页 = 0 个文字节点，本仓实测最小的有内容页 = 6（/verify-email）。
// ★ 它是**区分"有/没有内容"的地板**，不是"钉住某一页的节点数"（后者是负资产）。
const MIN_SAMPLES = 5

const parseList = (v, fallback) => {
  const arr = String(v || '').split(',').map((s) => s.trim()).filter(Boolean)
  return arr.length ? arr : fallback
}
const ROUTE_LIST = parseList(process.env.PROBE_ROUTES, DEFAULT_ROUTES)
const THEME_LIST = parseList(process.env.PROBE_THEMES, DEFAULT_THEMES)
const REPORT_ONLY = process.argv.includes('--report')

const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'contrast_matrix')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}
mkdirSync(SHOT_DIR, { recursive: true })

// ====== 注入到页面里的对比度引擎 ======
//
// ★ 与 `cdp-dark-contrast.mjs` 的引擎**刻意保持逐字一致** —— 两份不同算法 = 两份真源，
//   迟早有一份是错的。要改请两边一起改。（本段住在模板串里：注释中不能出现反引号。）
const HELPERS = `
const parseColor = (s) => {
  const m = String(s || '').match(/rgba?\\(([^)]+)\\)/)
  if (!m) return null
  const p = m[1].split(/[,\\s\\/]+/).filter(x => x !== '').map(Number)
  if (p.length < 3 || p.some(isNaN)) return null
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]
}
const blend = (f, b) => [
  f[0] * f[3] + b[0] * (1 - f[3]),
  f[1] * f[3] + b[1] * (1 - f[3]),
  f[2] * f[3] + b[2] * (1 - f[3]),
  1,
]
const lum = (c) => {
  const g = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
  return 0.2126 * g(c[0]) + 0.7152 * g(c[1]) + 0.0722 * g(c[2])
}
const ratio = (a, b) => {
  const l1 = lum(a), l2 = lum(b)
  const hi = Math.max(l1, l2), lo = Math.min(l1, l2)
  return (hi + 0.05) / (lo + 0.05)
}
const gradStops = (bi) => {
  const out = []; const re = /rgba?\\([^)]+\\)/g; let m
  while ((m = re.exec(bi))) out.push(m[0])
  return out
}
const rootBg = (() => {
  for (const el of [document.documentElement, document.body]) {
    const c = parseColor(getComputedStyle(el).backgroundColor)
    if (c && c[3] >= 0.999) return c
  }
  return [255, 255, 255, 1]
})()
const bgCandidates = (el) => {
  const layers = []
  let n = el
  while (n && n.nodeType === 1) {
    const cs = getComputedStyle(n)
    const bc = parseColor(cs.backgroundColor) || [0, 0, 0, 0]
    const bi = cs.backgroundImage || 'none'
    const stops = bi.includes('gradient') ? gradStops(bi).map(parseColor).filter(Boolean) : []
    layers.push({ bc, stops })
    if (bc[3] >= 0.999 && !stops.length) break
    n = n.parentElement
  }
  let bases = [rootBg]
  for (let i = layers.length - 1; i >= 0; i--) {
    const L = layers[i]
    const cands = L.stops.length ? L.stops : [L.bc]
    const next = []
    for (const b of bases) for (const c of cands) next.push(blend(c, b))
    bases = next
  }
  return bases
}
const worstContrast = (el) => {
  const cs = getComputedStyle(el)
  const fgRaw = parseColor(cs.color)
  if (!fgRaw) return null
  const bgs = bgCandidates(el)
  let worst = Infinity, bg = null
  for (const b of bgs) {
    const r = ratio(blend(fgRaw, b), b)
    if (r < worst) { worst = r; bg = b }
  }
  const fs = parseFloat(cs.fontSize)
  const fw = parseInt(cs.fontWeight, 10) || 400
  const large = fs >= 24 || (fs >= 18.66 && fw >= 700)
  return {
    ratio: Math.round(worst * 100) / 100,
    need: large ? 3 : 4.5,
    size: fs, weight: fw,
    color: cs.color,
    bg: 'rgb(' + bg.map(v => Math.round(v)).join(', ') + ')',
  }
}
const visibleTextEls = () => [...document.querySelectorAll('*')].filter((e) => {
  const own = [...e.childNodes].some((n) => n.nodeType === 3 && (n.textContent || '').trim())
  if (!own) return false
  const cs = getComputedStyle(e)
  if (cs.visibility === 'hidden' || cs.display === 'none') return false
  if (parseFloat(cs.opacity) < 0.05) return false
  const r = e.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) return false
  return !!parseColor(cs.color)
})
const descOf = (e) => {
  const cls = (typeof e.className === 'string' ? e.className : '')
    .split(/\\s+/)
    .filter(Boolean)
    .filter((c) => !c.startsWith('css-'))
    .slice(0, 2)
    .join('.')
  return e.tagName.toLowerCase() + (cls ? '.' + cls : '')
}
const audit = () => {
  const out = []
  for (const e of visibleTextEls()) {
    const info = worstContrast(e)
    if (!info) continue
    out.push({ sel: descOf(e), text: norm(e.textContent).slice(0, 24), ...info })
  }
  return out
}
`

// ====== CDP 骨架 ======
const profile = mkdtempSync(join(tmpdir(), 'cdp-cm-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1440,900',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking', 'about:blank',
], { stdio: 'ignore' })

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
if (!page) { console.log('FAIL: no page（Chrome 起不来）'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
// ★ 每格的**未捕获异常**必须单独收：页面抛异常时往往只是"少渲染了半页"，
//   文字节点数照样 > 0 ⇒ 只看对比度会把它读成"这页没问题"。
let cellExceptions = []
// ★ 限流（429）必须**单独收**，理由见 openCellStable 的注释。
let throttledCell = null
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params?.exceptionDetails
    cellExceptions.push(String(d?.exception?.description || d?.text || '').slice(0, 200))
  }
  if (m.method === 'Network.responseReceived' && m.params?.response?.status === 429) {
    const h = m.params.response.headers || {}
    const key = Object.keys(h).find((k) => k.toLowerCase() === 'x-ratelimit-reset')
    const reset = Number(key ? h[key] : NaN)
    throttledCell = { url: m.params.response.url, reset: Number.isFinite(reset) ? reset : 60 }
  }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => {
  const i = ++seq
  pending.set(i, res)
  ws.send(JSON.stringify({ id: i, method, params }))
})
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) {
    return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 400)
  }
  return r?.result?.result?.value
}
const evalJson = async (body) => JSON.parse(await run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  ${HELPERS}
  ${body}
})()`))
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
// ★ 开 Network 域只为一件事：**看见 429**（见 openCellStable 的注释）。
await send('Network.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

// ====== 单元格：导航到「路由 + 主题」并采集 ======
//
// ★ 每格独立注入引导脚本，采完**立刻摘掉**（`removeScriptToEvaluateOnNewDocument`）：
//   不摘的话 24 格会攒 24 份脚本，**最后一份的值赢** —— 那时"为什么全是 macaron"
//   会变成一个极难查的幽灵。
const BOOT = (theme) => `
  try {
    localStorage.setItem('access_token', 'demo-token');
    localStorage.setItem('refresh_token', 'demo-refresh-token');
    localStorage.setItem('theme_mode', ${JSON.stringify(theme)});
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({
      id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin',
    }))});
    // ★ 关掉新手引导浮层：它跨路由常驻，会污染「这页有没有内容」的度量
    //   （键名与载荷形状取自 src/stores/tour.ts 的 STORAGE_KEY / Persisted）
    localStorage.setItem('onboarding_tour_v1', JSON.stringify({ v: 1, seen: true, lastIndex: 0, ts: Date.now() }));
  } catch (e) {}
`

async function openCell(route, theme) {
  cellExceptions = []
  // ★ 每次导航前清空上一格的 429 记录：上一个页面在途的请求可能晚到，
  //   不清就会把「上一格被限流」算到这一格头上（归因错方向）。
  throttledCell = null
  const add = await send('Page.addScriptToEvaluateOnNewDocument', { source: BOOT(theme) })
  const identifier = add?.result?.identifier
  await send('Page.navigate', { url: BASE + route })
  for (let i = 0; i < 40; i++) {
    const n = await run('(document.body && document.body.innerText || "").length')
    if (typeof n === 'number' && n > 80) break
    await sleep(500)
  }
  await sleep(1500)   // 主题生效 + 异步数据落地
  const state = await evalJson(`
    return JSON.stringify({
      path: location.pathname,
      dataTheme: document.documentElement.dataset.theme || null,
      bodyLen: norm(document.body.innerText).length,
      samples: visibleTextEls().length,
    })
  `)
  const nodes = await evalJson(`return JSON.stringify(audit())`)
  if (identifier) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier })
  return { state, nodes, exceptions: [...cellExceptions] }
}

// ====== 带限流退避的采格 ======
//
// ★★ 为什么必须做（第 323 轮实测逼出来的）：
//    本探针与被测应用**共享同一份限流配额**（后端 `core/middleware/rate_limit.py`，
//    60 次/分钟、按 IP 共享，连 `/static/*` 都计数）。全量 24 格是串行导航，
//    总请求量会超过 60/min ⇒ 排在后面的路由吃到 429 ⇒ 页面**降级成错误/空态**，
//    而本探针只会照常去量那个降级页面。实测后果是**两种错一起出现**：
//      ① 降级态里冒出一条并不存在的「硬缺口」（假红）；
//      ② 正常态才渲染的元素没出现 ⇒ 它的豁免条目「没命中」⇒ P1b 报「过期白名单」（假红）。
//    ⇒ 撞到 429 的格必须**等窗口回血后重采**；重采仍失败就如实记成
//      `kind: 'throttled'`（没体检到），而不是拿降级页面凑一个结论出来。
async function openCellStable(route, theme) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const r = await openCell(route, theme)
    if (!throttledCell) return { ...r, throttle: null }
    const waitS = Math.min(Math.round(throttledCell.reset) + 2, 95)
    console.log(`       ⚠️ ${route} @ ${theme} 撞 429 ⇒ 本格量到的是**降级页面**`
      + `（假红来源）；等 ${waitS}s 回血重采（第 ${attempt}/3 次）`)
    await sleep(waitS * 1000)
  }
  const r = await openCell(route, theme)
  return { ...r, throttle: throttledCell ? { ...throttledCell } : null }
}

// ====== 引擎自检（一次，与路由无关）======
const engineProbe = await evalJson(`
  const r1 = ratio([0, 0, 0, 1], [255, 255, 255, 1])
  const half = ratio(blend([255, 255, 255, 0.45], [0, 0, 0, 1]), [0, 0, 0, 1])
  return JSON.stringify({
    blackOnWhite: Math.round(r1 * 100) / 100,
    white45OnBlack: Math.round(half * 100) / 100,
  })
`)
check('L0a', '对比度引擎自检（黑/白 = 21:1，且 alpha 合成生效）',
  Math.abs(engineProbe.blackOnWhite - 21) < 0.05
  && engineProbe.white45OnBlack > 4 && engineProbe.white45OnBlack < 12,
  engineProbe)

// ====== 跑满矩阵 ======
console.log(`\n===== 矩阵：${ROUTE_LIST.length} 路由 × ${THEME_LIST.length} 主题 = ${ROUTE_LIST.length * THEME_LIST.length} 格 =====`)
const cells = []
for (const route of ROUTE_LIST) {
  for (const theme of THEME_LIST) {
    const { state, nodes, exceptions, throttle } = await openCellStable(route, theme)
    const bad = nodes.filter((x) => x.ratio < x.need)
    const hard = nodes.filter((x) => x.ratio < 3)
    cells.push({ route, theme, state, nodes, bad, hard, exceptions, throttle })
    const warn = hard.length ? ` ★<3:1 ${hard.length}` : ''
    const exc = exceptions.length ? ` ✖异常 ${exceptions.length}` : ''
    const th = throttle ? ' ⏳429未回血（本格未体检）' : ''
    console.log(`  ${`${route} @ ${theme}`.padEnd(28)} 扫 ${String(state.samples).padStart(4)} 节点 ·`
      + ` 不达 AA ${String(bad.length).padStart(3)} · <3:1 ${String(hard.length).padStart(2)}${warn}${exc}${th}`)
    await shot(`cell_${route === '/' ? 'root' : route.replace(/\//g, '_')}_${theme}`)
  }
}

// ====== L0 自检：每格都必须「真到了目标 + 主题真生效 + 真扫到东西 + 没崩」======
check('L0b', `每格主题都真的生效（${cells.filter((c) => c.state.dataTheme === c.theme).length}/${cells.length}）`,
  cells.every((c) => c.state.dataTheme === c.theme),
  cells.filter((c) => c.state.dataTheme !== c.theme).map((c) => `${c.route}@${c.theme}→${c.state.dataTheme}`))

check('L0c', '无未捕获异常（页面抛异常时"文字节点数>0"会把半页崩掉读成"没问题"）',
  cells.every((c) => c.exceptions.length === 0),
  cells.filter((c) => c.exceptions.length).map((c) => ({ cell: `${c.route}@${c.theme}`, e: c.exceptions[0] })))

// ---- 未覆盖台账：三种"没量到"必须分开报（混在一起会得出相反结论）----
const uncovered = []
for (const c of cells) {
  const p = c.state.path
  // ★ throttled 必须排在**最前**：降级页往往也「文字节点少」，会被后面的
  //   `blank` 吞掉 ⇒ 那时报告会说"页面是空白的"，而真相是"我们被限流了，没测到"。
  if (c.throttle) uncovered.push({ route: c.route, theme: c.theme, kind: 'throttled', url: c.throttle.url })
  else if (c.route !== '/login' && p === '/login') uncovered.push({ route: c.route, theme: c.theme, kind: 'auth' })
  else if (p !== c.route) uncovered.push({ route: c.route, theme: c.theme, kind: 'wrong', path: p })
  else if (c.state.samples < MIN_SAMPLES) uncovered.push({ route: c.route, theme: c.theme, kind: 'blank' })
}
const byKind = (k) => uncovered.filter((u) => u.kind === k)
console.log(`\n---- 未覆盖台账（共 ${uncovered.length}/${cells.length} 格）----`)
for (const k of ['throttled', 'auth', 'blank', 'wrong']) {
  const list = byKind(k)
  if (!list.length) continue
  const label = { throttled: '被**限流(429)**打降级 ⇒ 等窗口回血重采后仍未恢复，本格没有体检', auth: '被守卫弹去登录页（需真身份，demo 下不可体检）', blank: '页面渲染了但 0 文字节点 ⇒ 空白页', wrong: '落在第三个路径 ⇒ 探针量错了对象' }[k]
  console.log(`  [${k}] ${list.length} 格 —— ${label}`)
  for (const u of list) console.log(`       ${u.route} @ ${u.theme}${u.path ? ' → ' + u.path : ''}`)
}
if (!uncovered.length) console.log('  （无：24 格全部真量到了内容）')

// ====== 明细：硬缺口 / AA 缺口 / 主题间劣化 ======
const keyOf = (route, theme, x) => `${route}|${theme}|${x.sel}|${x.text}`
const flat = []
for (const c of cells) for (const x of c.nodes) flat.push({ ...x, route: c.route, theme: c.theme, key: keyOf(c.route, c.theme, x) })

const hardBad = flat.filter((x) => x.ratio < 3)
const aaGap = flat.filter((x) => x.ratio >= 3 && x.ratio < x.need)

if (aaGap.length) {
  console.log(`\n---- AA 缺口（3:1 ≤ r < 需值，**不判定**，只作盘面）：${aaGap.length} 条 ----`)
  const seen = new Set()
  for (const x of aaGap.sort((a, b) => a.ratio - b.ratio)) {
    const k = x.sel + '|' + x.text
    if (seen.has(k)) continue
    seen.add(k)
    console.log(`  ${String(x.ratio).padStart(6)}:1 (需 ${x.need})  ${x.route}@${x.theme}  ${x.sel}  「${x.text}」`)
  }
}

if (hardBad.length) {
  console.log(`\n---- ★ 硬缺口（< 3:1，"看不见"）：${hardBad.length} 条 ----`)
  for (const x of hardBad.sort((a, b) => a.ratio - b.ratio)) {
    console.log(`  ${String(x.ratio).padStart(6)}:1  ${x.route}@${x.theme}  ${x.sel}  「${x.text}」  ${x.color} on ${x.bg}`)
  }
} else {
  console.log('\n---- 硬缺口（< 3:1）：0 条 ----')
}

// 跨主题配对：同一元素在某主题达标、另一主题不达标 ⇒ **主题适配缺陷**
//（设计取舍在三主题上是一致的：要么都过、要么都不过）
const byKey = new Map()
for (const x of flat) {
  const k = `${x.route}|${x.sel}|${x.text}`
  if (!byKey.has(k)) byKey.set(k, [])
  byKey.get(k).push(x)
}
const coupled = []
let pairedKeys = 0
for (const arr of byKey.values()) {
  if (arr.length < 2) continue
  pairedKeys++
  const ok = arr.some((x) => x.ratio >= x.need)
  if (ok) for (const x of arr.filter((y) => y.ratio < y.need)) coupled.push({ ...x })
}
if (coupled.length) {
  console.log(`\n---- 主题间劣化（同元素：某主题达标 / 某主题不达标）：${coupled.length} 条 ----`)
  for (const x of coupled.sort((a, b) => a.ratio - b.ratio)) {
    console.log(`  ${String(x.ratio).padStart(6)}:1 (需 ${x.need})  ${x.route}@${x.theme}  ${x.sel}  「${x.text}」`)
  }
}

// ====== 棘轮白名单 ======
//
// ★ 每条**必须真的命中**，否则报红。理由：不这样，白名单会退化成"永久免检区"，
//   而它守的恰是"我们现在还不想修、但明确知道它存在"的东西 —— 它必须可回收。
const WAIVER_HARD = [
  {
    re: /^\/subscription\|(light|macaron)\|span\|当前套餐$/,
    why: '「当前套餐」是**被禁用的 antd 按钮文字**（antd 的 colorTextDisabled '
      + 'rgba(0,0,0,.25) 压在本仓 --success-bg 浅绿底上）。WCAG 1.4.3 对 disabled '
      + '控件**明确豁免**对比度要求 ⇒ 不属"看不清"缺陷。深色下本项 ≥3:1，'
      + '故只在 light/macaron 出现。',
  },
]

const uncovKey = (u) => `${u.route}|${u.kind}`
const WAIVER_UNCOVERED = [
  {
    route: '/team', kind: 'auth',
    why: 'Team.vue 的 goLogin() 在账号列表被后端拒时清 demo token 并跳登录页 —— '
      + 'demo 身份下**设计如此**。代价：/team 这一格在演示态永远体检不到，'
      + '所以它被显式记进台账而不是静默跳过。',
  },
]

const danglingHard = WAIVER_HARD.filter((w) => !hardBad.some((x) => w.re.test(x.key)))
const unwaivedHard = hardBad.filter((x) => !WAIVER_HARD.some((w) => w.re.test(x.key)))
const danglingUncov = WAIVER_UNCOVERED.filter((w) => !uncovered.some((u) => uncovKey(u) === `${w.route}|${w.kind}`))
const unwaivedUncov = uncovered.filter((u) => !WAIVER_UNCOVERED.some((w) => uncovKey(u) === `${w.route}|${w.kind}`))

writeFileSync(join(SHOT_DIR, 'matrix.json'), JSON.stringify({
  generatedAt: new Date().toISOString(),
  routes: ROUTE_LIST, themes: THEME_LIST, minSamples: MIN_SAMPLES,
  cells: cells.map((c) => ({ route: c.route, theme: c.theme, ...c.state, aaGap: c.bad.length, hard: c.hard.length, exceptions: c.exceptions })),
  uncovered, aaGap, hardBad, coupled,
}, null, 2), 'utf8')

if (!REPORT_ONLY) {
  // ★ 用 PROBE_ROUTES / PROBE_THEMES 缩了范围时，**"豁免表必须命中"这两条自检必须跳过**：
  //   没被跑到的条目天然不会命中，那会变成一串**假红**。缩范围是本地调试的常规动作，
  //   若它会引发假红，人就会习惯性忽略红 —— 那比没有门禁更糟。
  //   口径与 `cdp-dark-contrast.mjs` 的 PROBE_TARGETS 一致：缩范围时**明确报出来**，不静默。
  const NARROWED = ROUTE_LIST !== DEFAULT_ROUTES || THEME_LIST !== DEFAULT_THEMES

  check('P1', `无「几乎看不见」的文字（三主题 × 全路由，< 3:1 非豁免 ${unwaivedHard.length} 条 / 共 ${hardBad.length} 条）`,
    unwaivedHard.length === 0, unwaivedHard.slice(0, 12))

  const measured = cells.length - uncovered.length
  check('P2', `无「未覆盖」的格（${unwaivedUncov.length} 格非豁免 / 共 ${uncovered.length} 格）`,
    unwaivedUncov.length === 0, unwaivedUncov)
  check('P3', `真的量到了东西（实测 ${measured}/${cells.length} 格被体检 ≥ 路由数 ${ROUTE_LIST.length}；P1 不是空扫）`,
    measured > 0 && measured >= ROUTE_LIST.length,
    { measured, total: cells.length, routes: ROUTE_LIST.length })
  check('P4', `跨主题配对率达标（本报告不自欺，配到 ${pairedKeys} 组键）`,
    pairedKeys > 0, { pairedKeys })

  if (NARROWED) {
    console.log(`\n（本轮用 PROBE_ROUTES/PROBE_THEMES 缩了范围：只跑 ${ROUTE_LIST.length} 路由 × ${THEME_LIST.length} 主题`
      + ` ⇒ 跳过 P1b/P2b「豁免表必须命中」自检 —— 没跑到的条目天然不命中，那会是假红）`)
  } else {
    check('P1b', '硬缺口豁免表每条都真的命中（不用过期白名单凑绿）',
      danglingHard.length === 0, danglingHard.map((w) => String(w.re)))
    check('P2b', '未覆盖豁免表每条都真的命中',
      danglingUncov.length === 0, danglingUncov.map((w) => `${w.route}|${w.kind}`))
  }
}

const failed = results.filter((r) => !r.ok).length
console.log(`\n---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
console.log(`盘面 JSON：${join(SHOT_DIR, 'matrix.json')}`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(REPORT_ONLY || failed === 0 ? 0 : 1)

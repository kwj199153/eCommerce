// 验收「审计日志面板接入」（第 328 轮 · P0-5c）。
//
// 被测：`components/AuditLog/AuditLogPanel.vue`（抽屉）+ `api/audit.ts`
//       + `components/Sidebar/AccountMenu.vue`（**仅超管可见**的入口）
//       + `views/Workspace.vue`（挂载 + `open-audit-drawer` 事件）
//
// ============================================================================
// ★ 为什么走**真后端 + 真身份**，而不是 CDP Fetch 打桩
// ============================================================================
// 打桩能让面板"渲染出东西"，但那样验的是我编的响应，不是读口。
// 本探针改走真链路：由 `.workbuddy/probes/r328_mint_tokens.py` 用后端**自己的签发器**
// 为库里两个**已存在**的身份各签一枚真 token（超管 / 普通用户），注入 localStorage。
// ⇒ 这里看到的是 audit_logs 表里的**真实行**，403 也是后端**真的**回的。
//
// ============================================================================
// ★ 本探针要盯的**四件**静态门禁与单测都管不到的事
// ============================================================================
//   1. 抽屉**真的开**、真渲染出行（不是空壳）；
//   2. 三种「没有数据」**真的分开**呈现：403 → 「无权访问」，
//      读失败 → 失败态 + 重试，无匹配 → 「暂无审计记录」；
//   3. 入口的可见性**真的**按平台角色分流（超管有、普通用户无）；
//   4. 越权**直接发事件**（绕过入口）时，面板如实说「无权」，**不**谎称"暂无记录"
//      —— 这条最要紧：把 403 说成"没有记录"会让管理员以为审计没生效。
//
// 用法：node scripts/cdp-r328-audit-panel.mjs
//   前置：dev server(:5173) + 后端(:8000) 在跑；先执行过 r328_mint_tokens.py
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9368
const BASE = 'http://127.0.0.1:5173'
const SHOT_DIR = 'D:/ai/eCommerce/.workbuddy/probes/r328_shots'
const TOKEN_FILE = 'D:/ai/eCommerce/.workbuddy/probes/r328_tokens.json'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const el = () => String(Date.now() - t0).padStart(6) + 'ms'

mkdirSync(SHOT_DIR, { recursive: true })

let TOKENS
try {
  TOKENS = JSON.parse(readFileSync(TOKEN_FILE, 'utf8'))
} catch (e) {
  console.error('缺少身份令牌文件（先跑 .workbuddy/probes/r328_mint_tokens.py）：' + TOKEN_FILE)
  process.exit(1)
}
if (!TOKENS?.admin?.token || !TOKENS?.user?.token) {
  console.error('令牌文件结构不对（需要 admin.user 两枚 token）')
  process.exit(1)
}

/** 注入身份：access_token 必须是**非 demo** 的真 JWT，`isRealLogin` 才为真。 */
const bootFor = (who) => {
  const t = TOKENS[who]
  const info = {
    id: t.user_id, email: t.email, name: who === 'admin' ? '审计超管' : '普通用户',
    role: who === 'admin' ? 'admin' : 'user',
    is_active: true, is_verified: true,
  }
  return [
    'try {',
    '  localStorage.setItem("access_token", ' + JSON.stringify(t.token) + ');',
    '  localStorage.setItem("refresh_token", "r328-probe-refresh-not-demo");',
    '  localStorage.setItem("user_info", ' + JSON.stringify(JSON.stringify(info)) + ');',
    '  localStorage.setItem("theme_mode", "light");',
    '  localStorage.setItem("onboarding_tour_v1", JSON.stringify({v:1,seen:true,lastIndex:0,ts:Date.now()}));',
    '} catch (e) {}',
  ].join('\n')
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-r328-'))
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
const rateHits = []
/**
 * 审计读口的**真实**请求记录（渲染判据的前提）。
 * ★ 记它是因为第一版探针栽在这里：抽屉刚打开、请求还没发出去时，
 *   `rows=[] && loading=false` 这个**瞬时态**渲染出来与本面板的「暂无审计记录」
 *   **长得一模一样** ⇒ 只判文字就会把"还没请求"读成"确实没有"（假红/假绿各一次）。
 *   ⇒ 渲染判据之前，必须先证「那一轮请求真的发生、且状态码是这个」。
 */
const netAudit = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails
    pageErrors.push(String(d.exception?.description || d.text || '').slice(0, 300))
  }
  // ★ 坑 20：探针与被测应用**共享限流配额**（60/min，按 IP）。429 会让页面降级，
  //   而症状会伪装成"功能坏了"。这里把它记下来，好与真红区分。
  if (m.method === 'Network.responseReceived') {
    const url = String(m.params?.response?.url || '')
    if (m.params?.response?.status === 429) rateHits.push(url.slice(0, 120))
    if (url.includes('/api/v1/audit/')) {
      netAudit.push({
        path: url.split('/api/v1')[1].split('?')[0],
        status: m.params.response.status,
        at: Date.now(),
      })
    }
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
await send('Network.enable')

/**
 * 裸表达式求值（**不要**在这里用任何外部 helper —— 作用域不同，会 ReferenceError，
 * 而表达式仍可能 `return true` ⇒ 空操作假绿）。需要 helper 的写法一律**自带定义**。
 */
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

// ---- 探针作用域自检（坑 1：两个都应为 undefined，说明 run() 里确实没有全局 helper）----
console.log('探针作用域自检（应为 undefined|undefined）:', await run("typeof norm + '|' + typeof flatLn"))

const nav = async (who, path) => {
  const id = await send('Page.addScriptToEvaluateOnNewDocument', { source: bootFor(who) })
  let landed = false
  // ★ 坑 8：改完源码后第一次 navigate 可能落 about:blank ⇒ 必须重试一次
  for (let attempt = 0; attempt < 2 && !landed; attempt++) {
    await send('Page.navigate', { url: BASE + path })
    for (let i = 0; i < 30; i++) {
      const p = await run('location.pathname')
      if (p === path) { landed = true; break }
      await sleep(400)
    }
  }
  await sleep(2200)
  if (id) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: id })
  return landed
}

/** 抽屉快照。★ 判**可见性**（坑 3）：antd 关掉抽屉后元素仍在 DOM。 */
const DRAWER_SNAP = `(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
  const flat = (s) => norm(s).replace(/\\s/g, '')
  const ds = [...document.querySelectorAll('.ant-drawer')].filter((d) => {
    const st = getComputedStyle(d)
    return st.display !== 'none' && st.visibility !== 'hidden' && d.getBoundingClientRect().width > 0
  })
  const d = ds[0] || null
  // ★★ 无抽屉时也要返回**完整形状**（各字段给空默认值）。
  //   第一版这里只返回 open=false，于是谓词里的 s.emptyDesc.length
  //   直接 TypeError ⇒ 探针**崩在中途**，后面的判据（含汇总行）全部没打印。
  //   症状极具欺骗性：看板上只有前 11 条 FAIL，看着像"就这么几条坏了"，
  //   实际是"看板被截断了" —— 与 skill 坑 15 的"整块看板假绿"同族。
  //   （★ 本注释里刻意不写字面反引号：这段整体住在模板串里，裸反引号会提前闭合它。）
  if (!d) {
    return {
      open: false, title: '', hasTable: false, rowCount: 0, firstRow: [], tags: [],
      emptyDesc: '', totalText: '', leadText: '', resetBtn: false, refreshBtn: false,
      placeholders: [], spinning: false, text: '',
    }
  }
  const rows = [...d.querySelectorAll('.ant-table-tbody tr.ant-table-row')]
  const cells = (tr) => [...tr.querySelectorAll('td')].map((td) => norm(td.innerText))
  const btns = [...d.querySelectorAll('button')].map((b) => flat(b.innerText))
  return {
    open: true,
    title: norm(d.querySelector('.ant-drawer-title')?.innerText || ''),
    hasTable: !!d.querySelector('.ant-table'),
    rowCount: rows.length,
    firstRow: rows[0] ? cells(rows[0]) : [],
    tags: [...d.querySelectorAll('.ant-table-tbody .ant-tag')].map((t) => norm(t.innerText)).slice(0, 6),
    emptyDesc: norm(d.querySelector('.ant-empty-description')?.innerText || ''),
    totalText: norm(d.querySelector('.ant-pagination-total-text')?.innerText || ''),
    leadText: norm(d.querySelector('.audit-lead-text')?.innerText || ''),
    resetBtn: btns.includes('重置筛选'),
    refreshBtn: btns.includes('刷新'),
    placeholders: [...d.querySelectorAll('.audit-filters input')].map((i) => i.placeholder || ''),
    spinning: !!d.querySelector('.ant-spin-spinning'),
    text: norm(d.innerText).slice(0, 1600),
  }
})()`

const snap = async () => {
  const v = await run(DRAWER_SNAP)
  if (v && v.__err) return { open: false, __err: v.__err }
  return v || { open: false }
}

/** ★ 坑 14：任何「动作」都要有一条「动作真的发生了」的判据 ⇒ 这些函数**返回字符串**。 */
const clickAccountTrigger = () => run(`(() => {
  const t = document.querySelector('.account-entry .user-trigger')
  if (!t) return 'no-trigger'
  t.click()
  return 'ok'
})()`)

const readMenuLabels = () => run(`(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, '').trim()
  const items = [...document.querySelectorAll('.ant-dropdown:not(.ant-dropdown-hidden) .account-menu .mi-label')]
  return items.map((x) => norm(x.innerText))
})()`)

const dispatchOpenAudit = () => run(`(() => {
  window.dispatchEvent(new CustomEvent('open-audit-drawer'))
  return 'ok'
})()`)

const setTargetId = (val) => run(`(() => {
  const inp = [...document.querySelectorAll('.audit-filters input')]
    .find((i) => (i.placeholder || '').indexOf('目标 ID') >= 0)
  if (!inp) return 'no-input'
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(inp, ${JSON.stringify(val)})
  inp.dispatchEvent(new Event('input', { bubbles: true }))
  return 'ok'
})()`)

/**
 * 点抽屉里文案为 `label` 的按钮。
 * ★ 作用域是**整个抽屉**，不是 `.audit-lead` —— 「刷新」在说明条里、「重置筛选」
 *   在筛选条里，写死 `.audit-lead button` 会对着一个真实存在的按钮报 `no-btn`
 *   （本轮实测踩到，属坑 10「驱动失败伪装成页面没有」）。
 */
const clickLeadButton = (label) => run(`(() => {
  const flat = (s) => String(s == null ? '' : s).replace(/\\s/g, '').trim()
  const d = [...document.querySelectorAll('.ant-drawer')]
    .find((x) => getComputedStyle(x).display !== 'none')
  if (!d) return 'no-drawer'
  const b = [...d.querySelectorAll('button')].find((x) => flat(x.innerText) === ${JSON.stringify(label)})
  if (!b) return 'no-btn'
  b.click()
  return 'ok'
})()`)

const expandFirstRow = () => run(`(() => {
  const d = [...document.querySelectorAll('.ant-drawer')]
    .find((x) => getComputedStyle(x).display !== 'none')
  if (!d) return 'no-drawer'
  const b = d.querySelector('.ant-table-tbody .ant-table-row-expand-icon')
  if (!b) return 'no-expand'
  b.click()
  return 'ok'
})()`)

/** 等抽屉快照满足条件；★ 等待口径与判据口径一致（坑 4）。 */
const waitDrawer = async (pred, tries = 25, gap = 400) => {
  let last = { open: false }
  for (let i = 0; i < tries; i++) {
    last = await snap()
    if (pred(last)) return last
    await sleep(gap)
  }
  return last
}

/**
 * 「取数已落地」——三态里**任意一态**出现即算落地（有行 / 无权 / 暂无 / 加载失败）。
 *
 * ★★ 这条是本轮探针自己踩出来的坑 4：第一版只等 `open === true` 就去断言"有多少行"，
 *    而抽屉外壳先渲染、数据后到 ⇒ 8 条判据一起假红，看起来像面板坏得很彻底。
 *    **等待口径必须与断言口径一致**（断言行数就等行数到位）。
 */
const isSettled = (s) =>
  s.open === true &&
  (s.rowCount > 0 || /暂无审计记录|无权访问|加载失败/.test(String(s.text || '')))

/**
 * 等「审计读口这一轮请求真的回来」——`after` 是调用前 `netAudit` 的长度。
 * 这是**渲染判据的前提**（坑 19：前提自己也要成立并记账）。
 */
const waitNet = async (after, tries = 40, gap = 300) => {
  for (let i = 0; i < tries; i++) {
    if (netAudit.length > after) return netAudit.slice(after)
    await sleep(gap)
  }
  return []
}

const results = []
const check = (id, desc, ok, got) => {
  results.push({ id, desc, ok, got })
  console.log(`${ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'}  ${id}  ${desc}  ⟵ ${JSON.stringify(got)}`)
}

/** 限流余量：读后端响应头（读不到就不阻塞，别把探针拖死）。 */
const rateHeadroom = async () => {
  const r = await run(`(async () => {
    try {
      const res = await fetch('/api/v1/audit/actions', { headers: { Authorization: 'Bearer ' + (localStorage.getItem('access_token') || '') } })
      return JSON.stringify({ status: res.status, rem: Number(res.headers.get('x-ratelimit-remaining')) })
    } catch (e) { return JSON.stringify({ status: -1, rem: -1 }) }
  })()`)
  try { return JSON.parse(r) } catch { return { status: -1, rem: -1 } }
}

/**
 * 等限流窗口**回血**再开跑。
 *
 * ★★ 坑 17/20：探针与被测应用**共享**同一份按 IP 的配额（60/分钟）。
 *   本探针一轮约 40 个请求 ⇒ 连跑两轮就吃光 ⇒ 后续请求全 429 ⇒ 页面降级，
 *   而症状看着像"面板坏了"（本轮实测：`/audit/logs` 429 ⇒ 面板如实报
 *   「加载失败，请重试」，于是 B3/B4 假红）。
 *   ⇒ **不是**调低断言，是每段开跑前把窗口等回来。读到余量恰好也是
 *     「限流没把结论带跑」的取证。
 */
const waitHeadroom = async (need = 30, tries = 8, waitSec = 20) => {
  let h = await rateHeadroom()
  for (let i = 0; i < tries; i++) {
    if (!Number.isFinite(h.rem) || h.rem < 0 || h.rem >= need) return h
    console.log(`  限流余量 ${h.rem} < ${need}，等 ${waitSec}s 回血…`)
    await sleep(waitSec * 1000)
    h = await rateHeadroom()
  }
  return h
}

// ============================================================
// A. 平台超管身份
// ============================================================
console.log('\n===== A. 平台超管 =====')
const landedA = await nav('admin', '/')
// ★ 配额检查必须在**导航之后**：页面还在 about:blank 时相对 fetch 失败，
//   读到 -1 ⇒ 按约定「读不到就不阻塞」⇒ 这一关等于空转（本轮实测踩到）。
const headA = await waitHeadroom(45)
console.log('  ', el(), '限流余量 =', JSON.stringify(headA))
console.log('  ', el(), 'landed=', landedA)

// ★ 坑 19：前提自己也是一条判据 —— 没落在 `/` 的话后面全部无意义
check('A0', 'A 段前提：确实落在 / 且工作台外壳已渲染',
  landedA === true && (await run("typeof document.querySelector('.account-entry')")) === 'object',
  { landedA })
await shot('A0_landed.png')

// A1 入口可见（先开菜单）
const openA = await clickAccountTrigger()
await sleep(700)
const labelsA = await readMenuLabels()
check('A1', '账户菜单能打开（点到了触发器，非空操作）', openA === 'ok' && Array.isArray(labelsA), { openA, n: Array.isArray(labelsA) ? labelsA.length : labelsA })
check('A2', '超管的账户菜单里**有**「审计日志」入口',
  Array.isArray(labelsA) && labelsA.includes('审计日志'), labelsA)
// 关掉菜单，免得挡住抽屉判据
await run('document.body.click()')
await sleep(300)

// A3 打开抽屉（走真实事件通路，与账户菜单派发的是同一个）
const nA = netAudit.length
const fireA = await dispatchOpenAudit()
const dA = await waitDrawer((s) => s.open === true && s.title === '审计日志')
check('A3', '派发 open-audit-drawer ⇒ 抽屉真的打开且标题为「审计日志」',
  fireA === 'ok' && dA.open === true && dA.title === '审计日志', { fireA, open: dA.open, title: dA.title })

// ★ 前提：这一轮 /audit/logs 真的发出去了，且后端回的是 200
const callsA = await waitNet(nA)
const logCallA = callsA.find((c) => c.path === '/audit/logs')
check('A3b', '前提：GET /audit/logs 真的发出且状态 200（超管）',
  !!logCallA && logCallA.status === 200, { calls: callsA })
await sleep(700)
const dAS = await waitDrawer(isSettled, 20, 400)
await shot('A3_drawer_open.png')

// A4 真渲染出行（后端真实数据）
check('A4', '抽屉里渲染出真实审计行（≥1 行）',
  typeof dAS.rowCount === 'number' && dAS.rowCount >= 1, { rowCount: dAS.rowCount, firstRow: dAS.firstRow, text: (dAS.text || '').slice(0, 80) })
check('A5', '表格结构存在（不是空壳抽屉）', dAS.hasTable === true, { hasTable: dAS.hasTable })

// A6 动作列显示**中文标签** ⇒ 证明 /audit/actions 目录真的下来了（前端没有第二份清单）
const rowText = Array.isArray(dAS.firstRow) ? dAS.firstRow.join(' | ') : ''
check('A6', '动作列显示目录里的中文标签（证明 GET /actions 真的接上了）',
  rowText.includes('登录成功') || rowText.includes('连接店铺') || rowText.includes('删除店铺'), rowText)

// A7 结果列是 tag
check('A7', '结果列渲染为 tag（成功 / 失败）',
  Array.isArray(dAS.tags) && dAS.tags.length >= 1 && dAS.tags.every((t) => t === '成功' || t === '失败'), dAS.tags)

// A8 时间列已格式化（不是裸 ISO）
// ★ 不写死列索引：antd 在有展开列时会在最前面多插一个 `<td>`（本轮实测踩到 ——
//   `firstRow[0]` 拿到的是展开图标那一格的空串）。按**形态**找那一格。
const timeCell = (Array.isArray(dAS.firstRow) ? dAS.firstRow : [])
  .find((c) => /\d{4}-\d{2}-\d{2}/.test(String(c)))
check('A8', '时间列已格式化（YYYY-MM-DD HH:mm:ss，非裸 ISO）',
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(String(timeCell || '')), { cells: dAS.firstRow })

// A9 分页总数来自后端 total
check('A9', '分页显示「共 N 条」且 N ≥ 1（total 真来自后端）',
  /^共 \d+ 条$/.test(String(dAS.totalText || '')) && Number(String(dAS.totalText).replace(/\D/g, '')) >= 1, dAS.totalText)

// A10 筛选栏结构
check('A10', '筛选栏存在（动作/结果/目标/时间 + 执行者 ID / 目标 ID 输入）',
  Array.isArray(dAS.placeholders) && dAS.placeholders.some((p) => p.includes('执行者 ID')) && dAS.placeholders.some((p) => p.includes('目标 ID')), dAS.placeholders)

// A11 展开行显示来源 IP / User-Agent
const exA = await expandFirstRow()
await sleep(700)
const dEx = await waitDrawer((s) => /来源 IP/.test(String(s.text || '')) && /User-Agent/.test(String(s.text || '')), 12, 400)
check('A11', '展开行显示「来源 IP」与「User-Agent」（点到了展开图标）',
  exA === 'ok' && /来源 IP/.test(String(dEx.text || '')) && /User-Agent/.test(String(dEx.text || '')),
  { exA, hasIp: /来源 IP/.test(String(dEx.text || '')), hasUa: /User-Agent/.test(String(dEx.text || '')) })

// A12 空态：填一个不存在的 target_id ⇒ 「暂无审计记录」（**不是**"加载失败"）
const setA = await setTargetId('r328-no-such-target-zzz')
await sleep(200)
const refA = await clickLeadButton('刷新')
const dEmpty = await waitDrawer((s) => s.emptyDesc.length > 0)
check('A12', '无匹配时如实说「暂无审计记录」（不是"加载失败"）',
  setA === 'ok' && refA === 'ok' && dEmpty.emptyDesc === '暂无审计记录', { setA, refA, emptyDesc: dEmpty.emptyDesc })
await shot('A12_empty_state.png')

// A13 重置筛选出现且能恢复
const dReset = await snap()
const resetA = await clickLeadButton('重置筛选')
await sleep(200)
const dBack = await waitDrawer((s) => (s.rowCount || 0) >= 1)
check('A13', '「重置筛选」在有筛选时出现，且点它后行数恢复 ≥1',
  dReset.resetBtn === true && resetA === 'ok' && dBack.rowCount >= 1,
  { beforeReset: dReset.resetBtn, resetA, rowCount: dBack.rowCount })

// A14 无未捕获异常
check('A14', '超管路径无未捕获异常', pageErrors.length === 0, pageErrors.slice(0, 3))

// ============================================================
// B. 普通用户身份（403 第三态 + 入口不可见）
// ============================================================
console.log('\n===== B. 普通用户（非超管）=====')
const landedB = await nav('user', '/')
const head = await waitHeadroom(30)
console.log('  ', el(), '限流余量 =', JSON.stringify(head))
check('B0', 'B 段前提：确实落在 /',
  landedB === true && (await run("typeof document.querySelector('.account-entry')")) === 'object', { landedB })

const openB = await clickAccountTrigger()
await sleep(700)
const labelsB = await readMenuLabels()
check('B1', '普通用户的账户菜单里**没有**「审计日志」入口（展示收敛生效）',
  openB === 'ok' && Array.isArray(labelsB) && !labelsB.includes('审计日志'), labelsB)
check('B1b', '对照：菜单本身是打开的（否则 B1 是空跑）',
  Array.isArray(labelsB) && labelsB.length >= 3, labelsB)
await shot('B1_menu_nonadmin.png')
await run('document.body.click()')
await sleep(300)

const nB = netAudit.length
const fireB = await dispatchOpenAudit()
await waitDrawer((s) => s.open === true)
// ★ 前提：403 是异步回来的。先证「请求真发生且真的是 403」，再判渲染
//   —— 否则会把请求发出前的瞬时空态读成"面板说了暂无记录"（坑 4/19）。
const callsB = await waitNet(nB)
const logCallB = callsB.find((c) => c.path === '/audit/logs')
check('B2b', '前提：GET /audit/logs 真的发出且后端回 **403**（非超管）',
  !!logCallB && logCallB.status === 403, { calls: callsB })
await sleep(700)
const dB = await waitDrawer(isSettled, 20, 400)
check('B2', '越权直接发事件 ⇒ 面板仍打开（说明入口收敛不是唯一防线）',
  fireB === 'ok' && dB.open === true, { fireB, open: dB.open })

// ★★ 本探针最要紧的一条：403 必须说「无权」，不许说「暂无记录」
const bStr = String(dB.text || '')
check('B3', '403 呈现为「无权访问」（不是"暂无记录"、也不是"加载失败"）',
  bStr.includes('无权访问') && !bStr.includes('暂无审计记录') && !bStr.includes('加载失败'),
  { hasForbidden: bStr.includes('无权访问'), hasEmpty: bStr.includes('暂无审计记录'), hasFail: bStr.includes('加载失败'), text: bStr.slice(0, 100) })
// ★ 必须同时要求「抽屉确实当着」——否则在"面板压根没渲染出来"的情况下
//   `hasTable === false` 会**恒真**（本轮 I3 注入实测：摘掉挂载后 B4 反而 PASS）。
check('B4', '403 时**不**渲染表格（第三态与表格互斥；且抽屉确实开着）',
  dB.open === true && dB.hasTable === false, { open: dB.open, hasTable: dB.hasTable })
await shot('B3_forbidden.png')
check('B5', '普通用户路径无未捕获异常', pageErrors.length === 0, pageErrors.slice(0, 3))

// ============================================================
clearTimeout(watchdog)
chrome.kill()

const bad = results.filter((r) => r.ok === false)
const skipped = results.filter((r) => r.ok === null)
console.log(`\n===== ${results.length - bad.length - skipped.length}/${results.length} PASS` +
  (skipped.length ? ` · ${skipped.length} SKIP` : '') + ` =====`)
if (rateHits.length) console.log(`★ 本轮撞到 429 x${rateHits.length}：`, rateHits.slice(0, 3))
console.log(`★ PASS=${bad.length === 0}`)
console.log(`截图目录：${SHOT_DIR}`)
process.exit(bad.length === 0 ? 0 : 1)

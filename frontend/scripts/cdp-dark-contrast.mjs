// CDP 真机探针 —— **深色模式可读性体检**（基于 WCAG 对比度）。
//
// 起因（老板截图报的）：订阅 & 计费页在深色模式下「要么字看不见，要么字颜色灰的很浅
// 看不清」。两处都住在 `views/Subscription.vue` 的 `<style scoped>` 里：
//
//   ① `.current-plan-banner.status-active { background: linear-gradient(135deg,
//      #f6ffed 0%, #e6fffb 100%) }` —— 硬编码**浅色**底不随主题翻，而里面的
//      `--text-primary`（深色下 = rgba(255,255,255,.92)）是**白字** ⇒ 白字压浅绿底，
//      对比度约 1.0:1（= 完全看不见）。
//   ② `.plan-features li { color: #434343 }` —— 硬编码**深灰**字压在深色卡片底上，
//      对比度约 1.4:1（= 老板说的"灰的很浅看不清"）。
//
// 为什么必须用**真实浏览器 + 算对比度**（三个理由，缺一条这个探针就没意义）：
//   ① `vite build` / `vue-tsc` / 单测**全都不报** —— 它们是颜色值，不是类型错误；
//   ② 同一句 `color: var(--text-primary)` 在浅色下**是对的**、在深色下才是错的
//      ⇒ 判据必须**带上"当时是哪个主题"**，静态扫描判断不出来；
//   ③ `check-theme-var-refs.py` 只管"引用的变量名是否存在"，硬编码色是它的盲区
//      （所以这条缺陷从它眼皮底下过去了）。
//
// 判据口径（本仓纪律）：
//   · 对比度 = WCAG 相对亮度公式，正文需 ≥ 4.5:1、大字（≥24px 或 ≥18.66px 且 bold）≥ 3:1；
//   · 背景取**元素自身到 root 的完整合成链**（含渐变的所有色标）并取**最差**的那个
//     色标 —— 只取渐变的第一个色标会自我安慰（另一端可能更差）；
//   · `color` 带 alpha 时先**合成到背景上再算**（否则 `rgba(255,255,255,.45)`
//     会被当成纯白，算出虚高的比值）；
//   · 每个集合判据配一条 **L0 自检**（选择器真选到东西），否则选择器写错会静默全绿；
//   · 「深色模式不达标 0 条」必须配 **浅色模式对照**（同口径同扫描器），否则
//     分不清"深色修好了"与"扫描器坏了"；
//   · 引擎自身要有**已知值自检**（黑字白底 = 21:1）—— 算错公式会让全页恒绿。
//
// 用法：
//   node scripts/cdp-dark-contrast.mjs           判定（有不达标 ⇒ 退出码 1）
//   node scripts/cdp-dark-contrast.mjs --report  只打印盘面、不判定
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/subscription）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9391
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/subscription'
// ★ 有些消费点**得点进去才挂载** —— 右栏「任务配置面板」是按「当前 Agent + 当前工具」
//   用 v-else-if 渲染的，默认首页一个都不在。`PROBE_DRIVE` = 一段**在页面里求值的 JS
//   表达式**（可以是 async IIFE），用来把目标面板点出来。
//   深色 / 浅色两轮**跑同一段驱动** ⇒ 跨主题配对（P2/P3）照样成立，不必另造扫描器。
//   用法：PROBE_PAGE=task-config PROBE_DRIVE='(async()=>{…})()' node scripts/cdp-dark-contrast.mjs
const DRIVE = (process.env.PROBE_DRIVE || '').trim()
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'dark_contrast')
const REPORT_ONLY = process.argv.includes('--report')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-dc-'))
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
  if (r?.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 400)
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

// ====== 注入到页面里的对比度引擎 ======
//
// ★ 这些函数**必须住页面**（要读 `getComputedStyle`），且**不能**用 Node 侧模板串
//   里的 `${}` 展开 —— 所以下面所有反斜杠都是**双写**的（`\\(` 在 JS 串里 = `\(`）。
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
// 元素自身到 root 的**背景候选**（收集所有层的所有色标 → 逐层合成 → 得候选集）
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
    // ★ 字色带 alpha：先合成到该背景上再算 —— 否则 rgba(255,255,255,.45)
    //   会被当成纯白，比值虚高（浅色字在深底上的真实可读性就是这么被算假的）
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
// ★ 判「有没有**自己的**文字」，而不是「是不是叶子元素」。
//   带图标的行（CheckCircleOutlined + 文本）children.length > 0 ——
//   用"叶子"当条件会把**整张功能清单排除在体检之外**（第二版实测：反向注入
//   .plan-features li 时 P1/P2 不红，才发现扫描器根本没读这些节点）。
//   改成「存在直接文本子节点」后，父子不会重复计（父的 childNodes 里只有元素）。
//   ⚠️ 本段住在 HELPERS **模板串**里：注释中**不能出现反引号**，否则提前闭合串
//      （本节已被这个坑绊过两次 —— 第一次是 descOf 的注释）。
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
// ★ 必须**剔掉 antd 的 cssinjs 哈希类**（css-dev-only-do-not-override-xxxx）：
//   那个哈希是**按主题算法生成**的 —— 浅色轮是 ...-4xb6ri、深色轮是 ...-1dgcvgq
//   ⇒ 带着它做跨主题配对会**全部配不上**，P2 于是恒真（空跑）。
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

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

/** 用指定主题打开订阅页并等它就绪 —— 两轮体检（深色 / 浅色）共用这一条通路 */
async function openWith(mode) {
  // ★ 每轮用新的 addScriptToEvaluateOnNewDocument 之前先清掉上一轮的，否则
  //   第二轮的 localStorage 会被第一轮的脚本**再写一遍**（先注入先执行，后写的赢）
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('access_token', 'demo-token');
      localStorage.setItem('refresh_token', 'demo-refresh-token');
      localStorage.setItem('theme_mode', ${JSON.stringify(mode)});
      localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }))});
    `,
  })
  await send('Page.navigate', { url: URL })
  // ★ 等**页面真有内容**（不用固定 sleep，也不用订阅页专属选择器 —— 本探针要能体检任意页）
  for (let i = 0; i < 40; i++) {
    const n = await run('(document.body && document.body.innerText || "").length')
    if (typeof n === 'number' && n > 100) break
    await sleep(1000)
  }
  // 主题生效 + 异步数据落地（订阅页的套餐/账单要等接口回来）后再量
  await sleep(1800)
  // ★ 驱动（可选）：把「默认不挂载」的目标面板点出来。
  //   驱动失败必须**显式红** —— 否则后面的点名选择器会全报「元素不存在」，
  //   把「我点错了」伪装成「页面确实没这个元素」（判据里记过的那条：两种失败要分开报）。
  if (DRIVE) {
    const out = await run(DRIVE)
    const err = typeof out === 'string' && out.startsWith('EXC:')
    check(`D0-${mode}`, `驱动脚本执行成功（${mode}，返回 ${JSON.stringify(out)}）`, !err, { ret: out })
    await sleep(1500)   // 等 Vue 渲染出面板
  }
  return run('document.documentElement.classList.contains("dark")')
}

// ====== 第一轮：深色模式 ======
const isDark = await openWith('dark')
await shot('dark_00_page')

// ---- L0 自检 ----
const themeProbe = await evalJson(`
  const cs = getComputedStyle(document.documentElement)
  return JSON.stringify({
    hasDarkClass: document.documentElement.classList.contains('dark'),
    bgBase: cs.getPropertyValue('--bg-base').trim(),
    textPrimary: cs.getPropertyValue('--text-primary').trim(),
  })
`)
check('L0a', '深色主题真的生效（html.dark + --bg-base 实测为深色值）',
  themeProbe.hasDarkClass && /#141414|rgb\(20, 20, 20\)/.test(themeProbe.bgBase), themeProbe)

// 引擎自检：黑字白底必须算出 21:1 —— 公式写错会让全页恒绿
const engineProbe = await evalJson(`
  const black = [0, 0, 0, 1], white = [255, 255, 255, 1]
  const r1 = ratio(black, white)
  const r2 = ratio([255, 255, 255, 1], [0, 0, 0, 1])
  // 半透明白字压在纯黑上 = 灰 (.45 → 114.75) 的比值，用来验证 alpha 合成没被跳过
  const half = ratio(blend([255, 255, 255, 0.45], black), black)
  return JSON.stringify({
    blackOnWhite: Math.round(r1 * 100) / 100,
    whiteOnBlack: Math.round(r2 * 100) / 100,
    white45OnBlack: Math.round(half * 100) / 100,
    samples: visibleTextEls().length,
  })
`)
check('L0b', '对比度引擎自检（黑/白 = 21:1，且 alpha 合成生效）',
  Math.abs(engineProbe.blackOnWhite - 21) < 0.05
  && Math.abs(engineProbe.whiteOnBlack - 21) < 0.05
  && engineProbe.white45OnBlack > 4 && engineProbe.white45OnBlack < 12,
  engineProbe)
check('L0c', '扫描器真的扫到了文字节点（> 20 个），不是空扫',
  engineProbe.samples > 20, { samples: engineProbe.samples })

// ---- 逐元素判据（**仅订阅页**）----
//
// ★ 泛化：本探针的 L0（主题生效 / 引擎自检 / 扫描器自检）与 P1~P3（全页体检）
//   与页面无关 —— 换 `PROBE_URL=http://127.0.0.1:5173/<其它页>` 即可体检任意页面。
//   只有下面这几条是订阅页的**点名判据**，所以用 PROBE_PAGE 显式开关：
//   别的页面照跑会因选择器找不到而报「元素不存在」，那是**噪声红**不是真发现。
const PAGE = process.env.PROBE_PAGE || 'subscription'
const TARGETS = PAGE === 'subscription' ? [
  ['C1', '.current-plan-banner .plan-badge span', '当前套餐横幅 · 套餐名'],
  ['C2', '.current-plan-banner .plan-price', '当前套餐横幅 · 价格（大字）'],
  ['C3', '.current-plan-banner .period-text', '当前套餐横幅 · 当前周期'],
  ['C4', '.plan-features li', '套餐卡 · 功能清单行'],
  ['C5', '.plan-limits li', '套餐卡 · 额度表行（正控：本来就用主题变量）'],
] : PAGE === 'task-config' ? [
  // ★ 第 319 轮：这些站点原来写死粉彩浅底（`#f6ffed` / `#fff` / `#f0f9ff` 渐变），
  //   深色下「亮底 + 跟随主题的浅字」≈ 1:1 ⇒ 逐条钉住「改成语义变量后真的翻了底」。
  //   必须配 `PROBE_DRIVE` 把对应 Agent + 工具点出来，否则选择器恒空（= 噪声红）。
  //
  // ⚠️ **刻意不列 `.product-banner` / `.kw-type-card`**：它们住在
  //   `BulletConfig.vue` / `DescConfig.vue` / `KeywordMinerConfig.vue` 里，而这三个组件
  //   **不可达**（死代码）—— 依据是**可达性复算**，不是"看着没人用"：
  //     · `keyword-miner / title-gen / bullet-gen / desc-gen` 只挂在 `listing-generator` 的
  //       `AGENT_TOOLS` 上；而该 Agent 在 `TaskConfigPanel/index.vue` 里被**更靠前**的
  //       `v-else-if="isListingAgent && LISTING_TOOL_IDS.includes(currentTool.id)"` 拦去
  //       `ListingBoard`（`listingSections/*`）⇒ 后面那几个 `currentTool.id === '…'` 分支永不命中；
  //     · `currentSelectedTool` 的**全部写入点**只有两处：工具栏点击（限 `currentAgentTools`）、
  //       切 Agent 时的记忆恢复（`getToolDefinition(新 agent, id)`，跨 Agent 查不到 ⇒ 回落默认工具）；
  //       没有任何 appAction / 深层链接能塞进一个别家的工具 id。
  //   列进来只会是一条**永久红**（选择器恒不存在）—— 判据里记过：「永久假红」比没有更糟。
  ['T2', '.archive-section', 'AIGC 配置 · 归档区（原 #f6ffed，与订阅页逐字同形）'],
  ['T3', '.mode-card', 'AIGC 配置 · 模式卡（原底 #fff / active #e6f7ff）'],
  ['T5', '.product-card-mini', '利润测算 · 产品卡（原渐变 #f0f9ff → #e6f7ff）']
    // ⚠️ T5 有前置：`.product-card-mini` 要**先在顶部「载入选品」选定候选**才渲染；
    //    驱动里没做这一步就会报「元素不存在」—— 那是噪声红，别当缺陷读。
] : []
if (!TARGETS.length) {
  console.log(`（PROBE_PAGE=${PAGE}：跳过订阅页点名判据，只做主题自检 + 全页体检）`)
}
// ★ 点名判据是**按页**列的一张扁平表；但「任务配置面板」每个 Agent/工具只挂一个，
//   其它面板的 id 天然不存在 ⇒ 全量跑会产出一批**噪声红**（看着像缺陷，其实是"这轮不测它"）。
//   `PROBE_TARGETS=T1,T3` 只判列出的 id；没列出的**明确报为"本轮跳过"**而不是 red。
//   未设置 = 全判（订阅页那条既有通路行为不变）。
const ONLY = (process.env.PROBE_TARGETS || '').split(',').map((s) => s.trim()).filter(Boolean)
const ACTIVE = ONLY.length ? TARGETS.filter((t) => ONLY.includes(t[0])) : TARGETS
const SKIPPED = TARGETS.filter((t) => !ACTIVE.includes(t))
if (SKIPPED.length) {
  console.log(`（本轮只判 ${ONLY.join('/')}；跳过 ${SKIPPED.map((t) => t[0]).join('/')}）`)
}
for (const [id, sel, label] of ACTIVE) {
  const info = await evalJson(`
    const el = document.querySelector(${JSON.stringify(sel)})
    if (!el) return JSON.stringify({ missing: true })
    return JSON.stringify({ missing: false, ...worstContrast(el) })
  `)
  if (info.missing) {
    check(id, `${label} 对比度达标`, false, { reason: '元素不存在（选择器或数据有问题）' })
    continue
  }
  check(id, `${label} 对比度 ≥ ${info.need}:1（实测 ${info.ratio}）`, info.ratio >= info.need, info)
}

// ---- 采集深色全页（判定留到浅色轮之后：P2 需要两侧数据）----
const darkNodes = await evalJson(`return JSON.stringify(audit())`)
const darkBad = darkNodes.filter(x => x.ratio < x.need)
console.log(`\n---- 深色模式全页体检：扫 ${darkNodes.length} 个文字节点，不达标 ${darkBad.length} 条 ----`)
for (const b of darkBad) {
  console.log(`  ${String(b.ratio).padStart(6)}:1 (需 ${b.need})  ${b.sel}  「${b.text}」  ${b.color} on ${b.bg}`)
}

// ====== 第二轮：浅色模式对照（同口径、同扫描器）======
//
// ★ 为什么必须做：只判「深色下不达标 == 0」的话，扫描器坏掉 / 页面白屏也照样绿。
//   浅色侧同时给出**基线**：订阅页在浅色下本来就有若干 antd token 的边缘值
//   （例：`.price-unit` 的 `--text-tertiary` = 3.2~3.4:1，全站一致）——
//   那些是**既有设计取舍**，不是本轮的深色适配缺陷，不该混在一条判据里。
const isLight = await openWith('light')
await shot('light_00_page')
check('L1', '浅色模式对照轮真的切回了浅色（不是同一轮重复量）',
  isLight === false, { hasDarkClass: isLight })

const lightNodes = await evalJson(`return JSON.stringify(audit())`)
const lightBad = lightNodes.filter(x => x.ratio < x.need)
console.log(`\n---- 浅色模式对照：扫 ${lightNodes.length} 个文字节点，不达标 ${lightBad.length} 条 ----`)
for (const b of lightBad) {
  console.log(`  ${String(b.ratio).padStart(6)}:1 (需 ${b.need})  ${b.sel}  「${b.text}」  ${b.color} on ${b.bg}`)
}
writeFileSync(join(SHOT_DIR, 'audit.json'), JSON.stringify({ dark: darkBad, light: lightBad }, null, 2), 'utf8')

if (!REPORT_ONLY) {
  // 跨主题配对的键。★ 必须**先定义**（P1 的豁免表也用同一个键）
  const key = (x) => x.sel + '|' + x.text

  // ★ 已既存例外（棘轮）：每一条都**必须真的命中**，否则说明它已过期、该删 ——
  //   不然白名单会退化成「永久免检区」。
  const UNDER3_WAIVER = [
    {
      prefix: 'button.to-close|',
      why: 'TourHost 引导浮层的关闭按钮（src/components/Tour/TourHost.vue，'
        + '--text-disabled 刻意弱化成 0.25 alpha）；浅色 1.84 / 深色 2.28 **两侧同在** '
        + '⇒ 与「订阅页深色适配」无关，且它出现在全站每一页，改它属于组件库议题',
    },
  ]

  // P1 —— 绝对不可读（< 3:1）清零。这是"看不见"的硬门槛，与设计取舍无关。
  const darkUnder3 = darkBad.filter(x => x.ratio < 3)
  const hitWaiver = UNDER3_WAIVER.filter(w => darkUnder3.some(x => key(x).startsWith(w.prefix)))
  const unwaived = darkUnder3.filter(x => !UNDER3_WAIVER.some(w => key(x).startsWith(w.prefix)))
  check('P1', `深色模式无「几乎看不见」的文字（< 3:1，豁免 ${hitWaiver.length} 条，实测 ${darkUnder3.length} 条）`,
    unwaived.length === 0, unwaived.slice(0, 12))
  check('P1b', '豁免表每条都真的命中（不用过期白名单凑绿）',
    hitWaiver.length === UNDER3_WAIVER.length,
    { declared: UNDER3_WAIVER.map(w => w.prefix), hit: hitWaiver.map(w => w.prefix) })

  // P2 —— **深色特有劣化**：同一个元素深色不达标、浅色达标 ⇒ 这才是深色适配缺陷。
  const lightByKey = new Map(lightNodes.map(x => [key(x), x]))
  const paired = darkNodes.filter(x => lightByKey.has(key(x))).length
  const regressions = darkBad.filter((x) => {
    const l = lightByKey.get(key(x))
    return !!l && l.ratio >= l.need
  })
  check('P2', `无「深色特有」的可读性劣化（深色不达标而浅色达标，实测 ${regressions.length} 条）`,
    regressions.length === 0, regressions.slice(0, 12))

  // P3 —— P2 的**自检**：配对率不够高 ⇒ P2 那两个集合天然为空 ⇒ 判据空跑。
  //   （本仓纪律：集合判据必须配一条"我真的看到东西了"的自检）
  check('P3', `跨主题配对率达标（P2 不自欺，配到 ${paired}/${darkNodes.length}）`,
    darkNodes.length > 0 && paired >= darkNodes.length * 0.9, { paired, dark: darkNodes.length })
}

const failed = results.filter(r => !r.ok).length
console.log(`\n---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(REPORT_ONLY || failed === 0 ? 0 : 1)

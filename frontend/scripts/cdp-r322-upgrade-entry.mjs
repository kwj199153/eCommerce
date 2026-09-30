// CDP 真机探针（第 322 轮）—— 「更换套餐」入口 + 计费周期弹窗语义
//
// ★★★ 本探针要证的是什么
//
//   改前：`Subscription.vue` 的两个入口（banner「升级套餐」:30 / 空态「选择套餐」:54）
//         只写 `showUpgradeModal = true`，**从不设 `selectedPlanForUpgrade`**；
//         而弹窗正文是 `v-if="selectedPlanForUpgrade"`(:319)
//         ⇒ ① 全新会话第一次点 = **空白弹窗**
//            ② 之后点 = 显示**上一次残留**的套餐（最坏那次正是用户当前在用的
//               那个，按钮还会写「确认续费」—— 老板截图就是这个形态）
//
//   改后：入口改为**滚到套餐对比区**（不开弹窗）；弹窗只服务
//         「已选定某套餐 → 选月付/年付」；关闭即清场。
//
//   这些都是**交互行为**，源码里写了 `scrollIntoView` / `watch` ≠ 用户真的看到。
//   ⇒ 必须真机跑，而且必须区分「我点击失败」与「业务上就是没有」。
//
// ============================================================================
// ★★★ 判据之间怎么互相作证（单条判据都会被"恒真/恒假"骗过去）
// ============================================================================
//   · 「弹窗出现」这个度量被用在**两处**，且方向相反：
//       J2 点 banner 入口  ⇒ 必须**不出现**  （本轮修复点）
//       J4 点卡片按钮      ⇒ 必须**出现**    （改前就正确的路径）
//     两条同时成立才说明这个度量真的能区分，而不是"永远查不到弹窗"。
//   · J3 不判"元素在不在视口"（banner+用量卡只有 ~400px 高，`.plans-card`
//     一开始就在 900px 视口里 ⇒ 恒真）。改判 **scrollY 真的增加了** +
//     目标顶部落在视口上部 —— 这才是"滚动发生且落到正确位置"。
//   · J8 才是"残留"的解药：开 A 卡 → 关 → 开 B 卡，标题必须是 **B**。
//     只开同一个卡片两次是**看不出残留的**。
//
// 用法：node scripts/cdp-r322-upgrade-entry.mjs
//   PROBE_BASE 覆盖站点根（默认 http://127.0.0.1:5173）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9397
const BASE = (process.env.PROBE_BASE || 'http://127.0.0.1:5173').replace(/\/$/, '')
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r322_upgrade_entry')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  const tail = ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)
  console.log(`${state}  ${id}  ${name}${tail}`)
}

if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r322-'))
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
  '--disable-background-networking',
  'about:blank',
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
if (!page) { console.log('FAIL: 拉不到 CDP page target'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => {
  ws.addEventListener('open', res)
  ws.addEventListener('error', rej)
})
const send = (method, params = {}) =>
  new Promise((res) => {
    const i = ++seq
    pending.set(i, res)
    ws.send(JSON.stringify({ id: i, method, params }))
  })

// ★★ 坑 1：`run()` 是**裸** Runtime.evaluate，顶层作用域里没有 norm/flat。
//    凡在 run() 里要用 helper 的，一律自带 definition —— 否则
//    ReferenceError 会让"点击 / 取值"变成静默空操作，看板却全绿。
const run = async (expr) => {
  const r = await send('Runtime.evaluate', {
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  })
  if (r?.result?.exceptionDetails) {
    return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 300)
  }
  return r?.result?.result?.value
}
const NORM_SRC = `
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
`
const runN = async (body) => run(`(() => { ${NORM_SRC} ${body} })()`)
// ★★ 坑（本轮真机第 1 次跑就踩了）：`body` **自带** `return JSON.stringify(...)`
//    （与 r320 / 矩阵探针同一约定），所以这里**不能再包一层**。
//    双重 stringify 的产物是一个**字符串**，`JSON.parse` 回来仍是字符串
//    ⇒ `snap().path` / `.cards` 全是 undefined，而像
//    `plansCardTop !== null` 这种判据在 undefined 时**为真** ⇒ 看板静默全绿。
const evalJson = async (body) => {
  const raw = await run(`(() => { ${NORM_SRC} ${body} })()`)
  if (typeof raw !== 'string' || raw.startsWith('EXC:')) return { __err: raw }
  try { return JSON.parse(raw) } catch { return { __err: raw } }
}

const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', {
  width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
})

// 演示身份（订阅页需要登录）+ 关掉新手引导浮层（它跨路由常驻，会污染读数）
const BOOT = `
  try {
    localStorage.setItem('access_token', 'demo-token');
    localStorage.setItem('refresh_token', 'demo-refresh-token');
    localStorage.setItem('theme_mode', 'light');
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({
      id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin',
    }))});
    localStorage.setItem('onboarding_tour_v1', JSON.stringify({ v: 1, seen: true, lastIndex: 0, ts: Date.now() }));
  } catch (e) {}
`

async function nav(route, waitMs = 1800) {
  await send('Page.navigate', { url: BASE + route })
  for (let i = 0; i < 40; i++) {
    const n = await run('(document.body && document.body.innerText || "").length')
    if (typeof n === 'number' && n > 80) break
    await sleep(400)
  }
  await sleep(waitMs)
}

/** 读一次全量盘面。★ 所有判据都从这一个快照算，避免"分几次读、中间状态漂移"。 */
const snap = () => evalJson(`
  const cards = [...document.querySelectorAll('.plan-card')].map(el => {
    const btn = el.querySelector('button')
    const priceTxt = (el.querySelector('.price-monthly') || {}).textContent || ''
    return {
      name: norm((el.querySelector('.plan-name') || {}).textContent || ''),
      price: parseFloat(String(priceTxt).replace(/[^0-9.]/g, '')) || 0,
      isCurrent: el.classList.contains('is-current'),
      btnText: norm(btn ? btn.textContent : ''),
      btnDisabled: !!(btn && btn.disabled),
    }
  })
  const bannerBtn = document.querySelector('.current-plan-banner .banner-right button')
  const plansCard = document.querySelector('.plans-card')
  const rect = plansCard ? plansCard.getBoundingClientRect() : null
  const modals = []
  for (const w of document.querySelectorAll('.ant-modal-wrap')) {
    const cs = getComputedStyle(w)
    if (cs.display === 'none' || cs.visibility === 'hidden') continue
    const t = w.querySelector('.ant-modal-title')
    const b = w.querySelector('.ant-modal-body')
    // 当前被选中的计费周期（.cycle-option.active 那个类）—— J9 用它判「粘性状态」
    // ★★ 本行原来写成了反引号包住的 .cycle-option.active ——
    //    而 snap() 整个 body 就是**模板字符串**，那个反引号会把它**提前闭合**，
    //    于是后半句被当成 JS 代码 ⇒ ReferenceError: option is not defined。
    //    ⇒ 模板字符串里要写字面反引号必须转义（\`），或者干脆别写。
    const act = w.querySelector('.cycle-option.active .cycle-period')
    modals.push({
      title: t ? norm(t.textContent) : '',
      bodyText: b ? norm(b.innerText || b.textContent || '') : '',
      cycleActive: act ? norm(act.textContent) : '',
    })
  }
  return JSON.stringify({
    path: location.pathname,
    scrollY: Math.round(window.scrollY),
    innerH: window.innerHeight,
    bodyHasOldLabel: norm(document.body.innerText).includes('升级套餐'),
    bannerBtnText: bannerBtn ? norm(bannerBtn.textContent) : null,
    plansCardTop: rect ? Math.round(rect.top) : null,
    cards,
    modals,
  })
`)

/** 点第 n 张套餐卡片的按钮。返回是否**真的点到**（false ≠ 业务上没有）。 */
const clickCardBtn = (nth) => runN(`
  const cards = [...document.querySelectorAll('.plan-card')]
  const el = cards[${nth}] && cards[${nth}].querySelector('button')
  if (!el) return false
  el.click()
  return true
`)

const clickBannerBtn = () => runN(`
  const el = document.querySelector('.current-plan-banner .banner-right button')
  if (!el) return false
  el.click()
  return true
`)

/** 点**可见**弹窗的关闭按钮。页面上有多个 a-modal（升级 / 支付），
 *  只有 display 不为 none 的那个才是当前可见的。 */
/** 点可见弹窗里的「按月付费」。★ 返回是否真的点到 —— 点不到 ≠ 业务上没有。 */
const clickMonthlyCycle = () => runN(`
  for (const w of document.querySelectorAll('.ant-modal-wrap')) {
    const cs = getComputedStyle(w)
    if (cs.display === 'none' || cs.visibility === 'hidden') continue
    for (const o of w.querySelectorAll('.cycle-option')) {
      const p = o.querySelector('.cycle-period')
      if (p && norm(p.textContent) === '按月付费') { o.click(); return true }
    }
  }
  return false
`)

/** 可见弹窗个数 */
const visibleModalCount = () => runN(`
  let n = 0
  for (const w of document.querySelectorAll('.ant-modal-wrap')) {
    const cs = getComputedStyle(w)
    if (cs.display === 'none' || cs.visibility === 'hidden') continue
    n++
  }
  return n
`)

const closeVisibleModal = () => runN(`
  for (const w of document.querySelectorAll('.ant-modal-wrap')) {
    const cs = getComputedStyle(w)
    if (cs.display === 'none' || cs.visibility === 'hidden') continue
    const btn = w.querySelector('.ant-modal-close')
    if (btn) { btn.click(); return true }
  }
  return false
`)

// ===========================================================================
// L0 —— 选择器自检：地基不成立时后面每条判据都会"看着通过"
// ===========================================================================
const addBoot = await send('Page.addScriptToEvaluateOnNewDocument', { source: BOOT })
const bootId = addBoot?.result?.identifier

await nav('/subscription', 2200)
const s0 = await snap()
if (s0.__err) {
  console.log('FAIL: 快照读取异常 —— ' + s0.__err)
  chrome.kill()
  process.exit(1)
}
// ★ 结构自检：后面**每一条**判据都建立在这个快照上。
//   一旦取值为 undefined（双重 stringify / 选择器写错 / 页面没起来），
//   随之而来的是一整片假绿 —— 所以这里必须硬中止，而不是「看着办」。
if (typeof s0.path !== 'string' || !Array.isArray(s0.cards)) {
  console.log('FAIL L0z 快照结构不完整 —— path=' + JSON.stringify(s0.path)
    + ' cards=' + JSON.stringify(s0.cards) + '，后续判据全部无意义，中止')
  console.log('      原始快照: ' + JSON.stringify(s0).slice(0, 300))
  chrome.kill()
  process.exit(1)
}
check('L0z', `快照结构完整（path=${s0.path}，cards=${s0.cards.length}）`,
  true, null)
await shot('01_initial')

check('L0a', `落在 /subscription（实得 ${s0.path}）`, s0.path === '/subscription', s0.path)
// ★ `!== null` 在 undefined 时也是真 —— 必须判**类型**，否则快照坏了也全绿
check('L0b', '套餐对比区 `.plans-card` 存在（选择器自检）',
  typeof s0.plansCardTop === 'number', s0.plansCardTop)
check('L0c', `套餐卡片数 ≥ 1（实得 ${s0.cards.length}）—— 0 说明探针选择器或页面挂了`,
  s0.cards.length >= 1, s0.cards.map((c) => c.name))
check('L0d', '能识别出「当前套餐」卡片（否则方向类判据改判 SKIP）',
  s0.cards.some((c) => c.isCurrent) ? true : null,
  s0.cards.map((c) => `${c.name}${c.isCurrent ? '(当前)' : ''}`))

const cur = s0.cards.find((c) => c.isCurrent) || null
const others = s0.cards.filter((c) => !c.isCurrent)

// ===========================================================================
// J1 —— 入口文案已改为准确的「更换套餐」
// ===========================================================================
check('J1a', `banner 入口文案 = 「更换套餐」（实得 ${JSON.stringify(s0.bannerBtnText)}）`,
  s0.bannerBtnText === '更换套餐', s0.bannerBtnText)
// ★ 「升级套餐」必须从页面上彻底消失：当前已是最高档时，"升级"没有落点
check('J1b', '页面正文里不再出现「升级套餐」（字面为假的说法已清掉）',
  s0.bodyHasOldLabel === false, { bodyHasOldLabel: s0.bodyHasOldLabel })
// ★ 当前套餐卡片必须是 disabled 的「当前套餐」——这是"套餐选择只有一处"的既有设计
check('J1c', '当前套餐卡片的按钮是 disabled 的「当前套餐」',
  cur ? (cur.btnDisabled === true && cur.btnText === '当前套餐') : null,
  cur ? { text: cur.btnText, disabled: cur.btnDisabled } : null)

// ===========================================================================
// J2 / J3 —— 点 banner 入口：不开弹窗 + 真的滚到套餐区
//   ★ J2 与 J4 用的是**同一个度量**、方向相反 ⇒ 互证它不是恒真/恒假
// ===========================================================================
const beforeClick = { scrollY: s0.scrollY, top: s0.plansCardTop, modals: s0.modals.length }
const clickedBanner = await clickBannerBtn()
check('J2a', 'banner 入口点击**真的发生**了（false ⇒ 后面两条判据无意义）', clickedBanner === true, clickedBanner)
await sleep(1600)   // 等 smooth 滚动落位
const s1 = await snap()
await shot('02_after_banner_click')

check('J2b', `点 banner 入口后**不开弹窗**（可见弹窗 ${s1.modals.length} 个）★本轮修复点`,
  s1.modals.length === 0, s1.modals)
check('J3a', `滚动**真的发生**了（scrollY ${beforeClick.scrollY} → ${s1.scrollY}）`,
  typeof s1.scrollY === 'number' && s1.scrollY > beforeClick.scrollY + 50,
  { before: beforeClick.scrollY, after: s1.scrollY })
// ★ 不用「top < 某个常数」（那是估的）：判「顶部落在视口内」+「相对初始位置明显上移」。
//   基线（beforeClick.top）来自同轮实测，delta 取 100px —— 页头 + 状态卡 ≈ 400px，
//   真实落位后 top ≈ 16（= scroll-margin-top），远大于 100 的位移。
check('J3b', `套餐区落到视口内且明显上移（top ${beforeClick.top} → ${s1.plansCardTop}，视口高 ${s1.innerH}）`,
  typeof s1.plansCardTop === 'number' && s1.plansCardTop >= 0
    && typeof beforeClick.top === 'number' && s1.plansCardTop < beforeClick.top - 100,
  { before: beforeClick.top, after: s1.plansCardTop })

// ===========================================================================
// J4 / J5 / J6 —— 点**非当前**套餐卡片：弹窗出现 + 标题点名 + 正文非空
// ===========================================================================
let s2 = null
if (others.length === 0) {
  check('J4', '点非当前套餐卡片 → 弹窗出现', null, '没有非当前套餐（环境条件）')
} else {
  const idx = s0.cards.findIndex((c) => !c.isCurrent)
  const clickedCard = await clickCardBtn(idx)
  check('J4a', `卡片按钮点击真的发生了（第 ${idx + 1} 张 = ${others[0].name}）`,
    clickedCard === true, clickedCard)
  await sleep(900)
  s2 = await snap()
  await shot('03_modal_from_card')

  check('J4b', `点卡片按钮后弹窗**必须出现**（与 J2b 互证）★`,
    s2.modals.length === 1, s2.modals)
  const title = s2.modals[0]?.title ?? ''
  check('J5', `弹窗标题点名套餐「${others[0].name} · 选择计费周期」（实得 ${JSON.stringify(title)}）`,
    title === `${others[0].name} · 选择计费周期`, title)
  const body = (s2.modals[0]?.bodyText ?? '').replace(/\s+/g, '')
  // ★ 「不是空白弹窗」：改前从 banner 进来时正文一个字符都没有
  check('J6', `弹窗正文非空（${body.length} 字符）—— 不是改前那个空白弹窗`,
    body.length > 0, { bodyLen: body.length, head: body.slice(0, 80) })
}

// ===========================================================================
// J7 —— 确认按钮的动词与档位一致（升级 / 降级）
// ===========================================================================
if (s2 && cur) {
  const pick = (pred) => {
    const i = s0.cards.findIndex((c) => pred(c))
    return i >= 0 ? { i, card: s0.cards[i] } : null
  }
  const higher = pick((c) => !c.isCurrent && c.price > cur.price)
  const lower = pick((c) => !c.isCurrent && c.price < cur.price)
  const btnText = (s2.modals[0]?.bodyText ?? '').match(/确认(升级|降级|续费|切换)/)?.[0] ?? ''
  const expect = others[0].price > cur.price ? '确认升级'
    : others[0].price < cur.price ? '确认降级' : '确认切换'
  check('J7a', `选到${others[0].price > cur.price ? '更贵' : others[0].price < cur.price ? '更便宜' : '同价'}的套餐 ⇒ 按钮动词必须是「${expect}」（实得 ${JSON.stringify(btnText)}）★`,
    btnText === expect, { btnText, expect, cardPrice: others[0].price, curPrice: cur.price })
  check('J7b', `存在更贵档（可测「升级」）：${higher ? higher.card.name : '无'}`, higher ? true : null,
    higher ? higher.card.name : null)
  check('J7c', `存在更便宜档（可测「降级」）：${lower ? lower.card.name : '无'}`, lower ? true : null,
    lower ? lower.card.name : null)
}

// ===========================================================================
// J8 —— 关窗清场：开 A → 关 → 开 B，标题必须是 **B**（残留的解药）
//   只开同一个卡片两次是**看不出残留的**，所以必须有第二张卡可用。
// ===========================================================================
if (others.length >= 2) {
  const closed = await closeVisibleModal()
  check('J8a', '弹窗关闭按钮点击真的发生了', closed === true, closed)
  await sleep(900)
  const s3 = await snap()
  check('J8b', `关闭后可见弹窗归零（实得 ${s3.modals.length}）`, s3.modals.length === 0, s3.modals)

  // others 是 s0.cards 过滤出来的**同一批对象引用**，直接 indexOf 取真实下标
  const idxB = s0.cards.indexOf(others[1])
  const clickedB = await clickCardBtn(idxB)
  await sleep(900)
  const s4 = await snap()
  await shot('04_modal_second_card')
  const titleB = s4.modals[0]?.title ?? ''
  check('J8c', `换一张卡片后标题是**新**套餐「${others[1].name}」（实得 ${JSON.stringify(titleB)}）★残留已消除`,
    clickedB === true && titleB === `${others[1].name} · 选择计费周期`,
    { titleB, expect: `${others[1].name} · 选择计费周期` })
  check('J8d', `标题里**不再**出现上一张卡片的套餐名「${others[0].name}」`,
    titleB.includes(others[0].name) === false, titleB)
} else {
  check('J8', '关窗清场（开 A → 关 → 开 B）', null,
    `只有 ${others.length} 张非当前套餐 ⇒ 无法做 A/B 对比（环境条件）`)
}

// ===========================================================================
// J9 —— 计费周期不能是**粘性**的：开弹窗 → 切月付 → 关 → 再开 ⇒ 回年付
//   ★ 这一条才真正咬住「粘性状态」。J8（换卡片标题变新）在删掉清场
//     之后**照样绿** —— 因为 handleSwitchPlan 每次都重新赋值。
//   ★ J9a 是**注入有效性自检**：先证明「点月付真的会变成月付」，
//     否则 J9b 的红可能是「点了没反应」造成的假象。
// ===========================================================================
if (others.length >= 1) {
  const idx = s0.cards.indexOf(others[0])
  if ((await visibleModalCount()) === 0) {
    await clickCardBtn(idx)
    await sleep(900)
  }
  const opened = await snap()
  check('J9-0', `重新打开弹窗后默认周期是「按年付费」（实得 ${JSON.stringify(opened.modals[0] && opened.modals[0].cycleActive)}）`,
    opened.modals.length === 1 && opened.modals[0].cycleActive === '按年付费',
    opened.modals[0] && opened.modals[0].cycleActive)

  const clickedMonthly = await clickMonthlyCycle()
  await sleep(400)
  const afterSwitch = await snap()
  check('J9a', `注入有效性自检：点「按月付费」后它真的变成选中态（实得 ${JSON.stringify(afterSwitch.modals[0] && afterSwitch.modals[0].cycleActive)}）`,
    clickedMonthly === true && afterSwitch.modals[0] && afterSwitch.modals[0].cycleActive === '按月付费',
    { clicked: clickedMonthly, active: afterSwitch.modals[0] && afterSwitch.modals[0].cycleActive })

  await closeVisibleModal()
  await sleep(900)
  const closedOk = (await visibleModalCount()) === 0
  await clickCardBtn(idx)
  await sleep(900)
  const reopened = await snap()
  const cycle = reopened.modals[0] ? reopened.modals[0].cycleActive : ''
  check('J9b', `重新打开后周期回到「按年付费」，不吃上一次的月付残留（实得 ${JSON.stringify(cycle)}）★`,
    closedOk && reopened.modals.length === 1 && cycle === '按年付费',
    { closedOk, cycle, modals: reopened.modals.length })
}

// ===========================================================================
// Z —— 对照：证明"页面可能压根没有 .plans-card" ⇒ L0b/J3 不是恒真
// ===========================================================================
const ctl = await evalJson(`
  return JSON.stringify({
    plansCard: document.querySelectorAll('.plans-card').length,
    planCard: document.querySelectorAll('.plan-card').length,
    impossible: document.querySelectorAll('.plan-card__no-such-thing').length,
  })
`)
check('Z1', '对照：另一个路由/选择器下这三个计数可以不为 1（证明判据能区分，不是查什么都命中）',
  ctl.plansCard === 1 && ctl.planCard >= 2 && ctl.impossible === 0, ctl)

if (bootId) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: bootId })

// ===========================================================================
const pass = results.filter((r) => r.ok === true).length
const fail = results.filter((r) => r.ok === false)
const skip = results.filter((r) => r.ok === null).length
console.log(`\n===== ${pass} PASS / ${fail.length} FAIL / ${skip} SKIP =====`)
if (fail.length) console.log('FAIL 明细:\n' + fail.map((f) => `  ${f.id}  ${f.name}`).join('\n'))
console.log(`截图目录: ${SHOT_DIR}`)

ws.close()
chrome.kill()
process.exit(fail.length ? 1 : 0)

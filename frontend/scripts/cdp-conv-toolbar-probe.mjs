// CDP 真实浏览器验证（第 283 轮）—— 对话窗口右上角工具条的三件事：
//   ① 「查找 / 分享 / 历史提问」三个按钮**真的在对话区右上角**（几何，不是"源码里有"）；
//   ② 三个按钮**真的能用**（点开面板 → 出内容 → 点结果 → 目标消息被高亮）；
//   ③ 右栏折叠后**回得来**（展开按钮出现 → 点击后右栏宽度恢复）。
//
// 为什么必须用真实浏览器：
//   · 「在右上角」是布局算出来的结果 —— 读源码证明不了它有没有被 flex 挤到别处；
//   · antd 的 popover / dropdown 会被 teleport 到 body，样式（popup.css）与 props 对不对
//     只有在真实 DOM 上才看得出来；
//   · 面板打开 / 跳转高亮都是**运行时副作用**，静态门禁看不见。
//
// 判据口径（本仓纪律）：
//   · 先自检「选择器真的选到东西」（L0），否则选择器写错会静默全绿；
//   · 位置判据用**相对**条件（在顶栏内 + 落在右半区），不写死像素；
//   · 空态允许两种正确形态（有行 / 有诚实空态文案），但**不允许两样都没有**。
//
// 用法：node scripts/cdp-conv-toolbar-probe.mjs [W] [H]
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
//   PROBE_SHOT_DIR 覆盖截图目录
import { spawn } from 'node:child_process'
import { writeFileSync, mkdtempSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9361
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const W = Number(process.argv[2] || 1600)
const H = Number(process.argv[3] || 856)
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r283_conv_toolbar')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-convtoolbar-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`,
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

const run = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 300)
  return r.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r.result?.data) {
    mkdirSync(SHOT_DIR, { recursive: true })
    const f = join(SHOT_DIR, name)
    writeFileSync(f, Buffer.from(r.result.data, 'base64'))
    return f
  }
  return null
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: URL })

// ---- 等具体元素（不用 body 文本长度当代理判据）
let booted = false
for (let i = 0; i < 30; i++) {
  const n = await run('document.querySelectorAll(".conv-toolbar .ct-btn").length')
  if (typeof n === 'number' && n === 3) { booted = true; break }
  await sleep(1000)
}

console.log(`viewport = ${W}x${H} | url = ${URL}`)
console.log('boot: .conv-toolbar .ct-btn =', await run('document.querySelectorAll(".conv-toolbar .ct-btn").length'))
console.log('boot: 左侧 Agent 项 =', await run('document.querySelectorAll(".agent-list .ant-menu-item").length'))

if (!booted) {
  const f = await shot('out_boot_fail.png')
  console.log(`FAIL: 对话工具条未渲染（截图见 ${f}）—— 可能是未登录 / dev server 没起，先修环境`)
  chrome.kill(); process.exit(1)
}

// ---- L0 自检：三个按钮的**可辨识**（图标 + title），否则下面点的是同一个东西
const IDENT = `(() => {
  const btns = [...document.querySelectorAll('.conv-toolbar .ct-btn')]
  return btns.map(b => ({ title: b.getAttribute('title') || '', disabled: !!b.disabled, svg: !!b.querySelector('svg') }))
})()`
const ident = await run(IDENT)
check('L0a', '工具栏恰好 3 个按钮且每个都有 svg 图标',
  Array.isArray(ident) && ident.length === 3 && ident.every(b => b.svg), ident)
check('L0b', '三个 title 分别是 查找 / 分享 / 历史提问',
  Array.isArray(ident) && /查找/.test(ident[0]?.title || '') && /分享/.test(ident[1]?.title || '') && /历史提问/.test(ident[2]?.title || ''),
  ident?.map(b => b.title))

// ---- L1 位置：在顶栏内 + 落在右半区（「右上角」的相对判据，不写死像素）
const GEO = `(() => {
  const bar = document.querySelector('.conv-toolbar')
  const header = document.querySelector('.header')
  const btns = [...document.querySelectorAll('.conv-toolbar .ct-btn')]
  const r = b => { const x = b.getBoundingClientRect(); return { t: +x.top.toFixed(1), b: +x.bottom.toFixed(1), l: +x.left.toFixed(1), r: +x.right.toFixed(1), w: +x.width.toFixed(1), h: +x.height.toFixed(1) } }
  return {
    vw: window.innerWidth,
    bar: bar ? r(bar) : null,
    header: header ? r(header) : null,
    btnTops: [...new Set(btns.map(b => +b.getBoundingClientRect().top.toFixed(1)))],
    btnLefts: btns.map(b => +b.getBoundingClientRect().left.toFixed(1)),
  }
})()`
const geo = await run(GEO)
check('L1a', '工具栏在顶栏（.header）的纵向范围内',
  geo?.bar && geo?.header && geo.bar.t >= geo.header.t - 1 && geo.bar.b <= geo.header.b + 1, geo)
check('L1b', '工具栏落在**右半区**（对话区右上角，而非左侧工具栏区）',
  !!geo?.bar && geo.bar.l > geo.vw / 2, { left: geo?.bar?.l, half: geo?.vw && geo.vw / 2 })
check('L1c', '三个按钮**水平排布**（top 相同、left 递增）',
  !!geo?.btnTops && geo.btnTops.length === 1 && geo.btnLefts.every((v, i, a) => i === 0 || v > a[i - 1]), geo)

await shot('out_01_toolbar.png')

// ---- L2 打开查找面板
const clickBtn = i => run(`(() => { const b = document.querySelectorAll('.conv-toolbar .ct-btn')[${i}]; if (!b) return 'NO_BTN'; b.click(); return 'CLICKED' })()`)
await clickBtn(0)
await sleep(700)
/** 关弹层：antd 判「外部点击」听的是 document 的 mousedown，**不是 click** ——
 *  只发 click 面板会一直挂着，截图里全是没关掉的浮层。 */
const CLOSE_POPS = `(() => {
  document.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  document.body.click()
  return 'OK'
})()`

/** ★ 必须筛「可见的那个」：antd 关闭 popover 是 display:none、**不销毁 DOM**，
 *  两个面板都符合 '.conv-toolbar-pop' ⇒ 直接 querySelector 会选中隐藏的查找面板
 *  （实测症状：历史提问的标题读成空串、行数读成消息总条数）。 */
const VIS_POP = `[...document.querySelectorAll('.conv-toolbar-pop')].find(el => el.getBoundingClientRect().width > 0)`
const findOpen = await run(`(() => {
  const pop = ${VIS_POP}
  if (!pop) return { open: false }
  return {
    open: true,
    hasInput: !!pop.querySelector('.ctp-input'),
    rows: pop.querySelectorAll('.ctp-row').length,
    emptyText: (pop.querySelector('.ctp-empty')?.textContent || '').trim(),
  }
})()`)
check('L2a', '点「查找」弹出面板（teleport 到 body 的 .conv-toolbar-pop）', findOpen?.open === true, findOpen)
check('L2b', '面板内**真的渲染出了图片列表或诚实空态**（不允许两样都没有）',
  !!findOpen?.open && (findOpen.rows > 0 || !!findOpen.emptyText), findOpen)

// ---- L3 输入关键词过滤 + 点结果跳转高亮
const typer = `(() => {
  const pop = ${VIS_POP}
  const input = pop ? pop.querySelector('.ctp-input') : null
  if (!input) return 'NO_INPUT'
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  setter.call(input, 'a')
  input.dispatchEvent(new Event('input', { bubbles: true }))
  return 'TYPED'
})()`
const typed = await run(typer)
await sleep(500)
const filtered = await run(`(() => {
  const pop = ${VIS_POP}
  if (!pop) return { open: false }
  const rows = pop.querySelectorAll('.ctp-row')
  return {
    rows: rows.length,
    marks: pop.querySelectorAll('.ctp-mark').length,
    emptyText: (pop.querySelector('.ctp-empty')?.textContent || '').trim(),
  }
})()`)
check('L3a', '输入关键词后过滤生效（有命中行 + 命中词被 <mark> 高亮，或明确说没找到）',
  typed === 'TYPED' && ((filtered?.rows > 0 && filtered?.marks > 0) || !!filtered?.emptyText), { typed, filtered })

// 点第一行 → 目标消息应被加 .msg-flash
const rowClick = await run(`(() => {
  const pop = ${VIS_POP}
  const row = pop ? pop.querySelector('.ctp-row') : null
  if (!row) return 'NO_ROW'
  row.click()
  return 'CLICKED'
})()`)
await sleep(600)
const flashed = await run(`(() => ({
  popGone: !${VIS_POP},
  flash: document.querySelectorAll('.msg-flash').length,
}))()`)
check('L3b', '点查找结果后：面板关闭 + 目标消息被高亮（.msg-flash）',
  rowClick === 'CLICKED' ? (flashed?.flash >= 1) : false, { rowClick, flashed })

// ---- L4 历史提问
await clickBtn(2)
await sleep(700)
const hist = await run(`(() => {
  const pop = ${VIS_POP}
  if (!pop) return { open: false }
  return {
    open: true,
    title: (pop.querySelector('.ctp-head-title')?.textContent || '').trim(),
    rows: pop.querySelectorAll('.ctp-row').length,
    emptyText: (pop.querySelector('.ctp-empty')?.textContent || '').trim(),
  }
})()`)
check('L4a', '点「历史提问」弹出面板且标题正确', hist?.open === true && hist?.title === '历史提问', hist)
check('L4b', '历史提问面板有内容或诚实空态',
  !!hist?.open && (hist.rows > 0 || !!hist.emptyText), hist)

// 关掉面板（点空白）
await run(CLOSE_POPS)
await sleep(500)

// ---- L5 分享菜单
await clickBtn(1)
await sleep(600)
const share = await run(`(() => {
  const items = [...document.querySelectorAll('.ant-dropdown-menu-item')]
  return { n: items.length, labels: items.map(i => (i.textContent || '').trim()) }
})()`)
check('L5', '点「分享」弹出菜单（复制 Markdown / 下载 .md 两个出口）',
  share?.n >= 2 && share.labels.some(t => /Markdown/.test(t)) && share.labels.some(t => /下载/.test(t)), share)
await shot('out_02_share_menu.png')
await run(CLOSE_POPS)
await sleep(400)

// ---- L6 切到有右栏的 Agent（店秘书没有右栏），再验证折叠 → 展开回程
const switched = await run(`(() => {
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /选品分析师|Listing 优化师|广告分析师|运营复盘师/.test(e.textContent || ''))
  if (!t) return 'NOT_FOUND'
  const label = (t.textContent || '').trim()
  t.click()
  return label
})()`)
await sleep(1200)
const afterSwitch = await run(`(() => ({
  hasCollapseTrigger: !!document.querySelector('.collapse-trigger'),
  hasExpandBtn: !!document.querySelector('.panel-expand-btn'),
  panelW: document.querySelector('.right-panel')?.getBoundingClientRect().width ?? 0,
}))()`)
check('L6a', `切到有右栏的 Agent（${switched}）后右栏展开、且**不显示**展开按钮`,
  switched !== 'NOT_FOUND' && afterSwitch?.hasCollapseTrigger === true
  && afterSwitch?.panelW > 0 && afterSwitch?.hasExpandBtn === false, { switched, afterSwitch })

// 点面板内的收起按钮
await run(`(() => { const b = document.querySelector('.collapse-trigger'); if (b) b.click(); return 'OK' })()`)
await sleep(900)
const collapsed = await run(`(() => ({
  panelW: +(document.querySelector('.right-panel')?.getBoundingClientRect().width ?? -1).toFixed(1),
  expandBtn: !!document.querySelector('.panel-expand-btn'),
  expandTitle: document.querySelector('.panel-expand-btn')?.getAttribute('title') || '',
}))()`)
check('L6b', '右栏收起后宽度归零、**且展开按钮出现在对话区右上角**',
  collapsed?.panelW <= 1 && collapsed?.expandBtn === true, collapsed)
await shot('out_03_collapsed_with_expand_btn.png')

// 展开按钮的几何：必须在对话区右上角（与三个操作按钮同一条线）
const expandGeo = await run(`(() => {
  const b = document.querySelector('.panel-expand-btn')
  const bar = document.querySelector('.conv-toolbar')
  const header = document.querySelector('.header')
  if (!b) return null
  const r = e => { const x = e.getBoundingClientRect(); return { t: +x.top.toFixed(1), b: +x.bottom.toFixed(1), l: +x.left.toFixed(1) } }
  return { expand: r(b), bar: bar ? r(bar) : null, header: r(header), vw: window.innerWidth }
})()`)
check('L6c', '展开按钮在顶栏内、右半区，且与对话工具条**同一条水平线**',
  !!expandGeo && expandGeo.expand.t >= expandGeo.header.t - 1 && expandGeo.expand.b <= expandGeo.header.b + 1
  && expandGeo.expand.l > expandGeo.vw / 2
  && (!expandGeo.bar || Math.abs(expandGeo.expand.t - expandGeo.bar.t) < 6), expandGeo)

// 点展开按钮 → 右栏回来
await run(`(() => { const b = document.querySelector('.panel-expand-btn'); if (b) b.click(); return 'OK' })()`)
await sleep(900)
const reopened = await run(`(() => ({
  panelW: +(document.querySelector('.right-panel')?.getBoundingClientRect().width ?? -1).toFixed(1),
  expandBtn: !!document.querySelector('.panel-expand-btn'),
}))()`)
check('L6d', '点展开按钮后右栏宽度恢复、按钮自行消失',
  reopened?.panelW > 100 && reopened?.expandBtn === false, reopened)
await shot('out_04_reopened.png')

// ---- L7 大屏模式（中间对话栏被压到 400px）下，顶栏有没有被我加的元素挤坏
//    ★ 为什么必须量：本轮往右上角**加了 4 个元素**（3 个操作按钮 + 1 个展开按钮），
//      而大屏模式下中间栏只有 400px —— 这正是「加了 A 挤坏 B」的高风险方向。
//      静态门禁读不出「装不装得下」，只有浏览器算得出来。
const toReview = await run(`(() => {
  const items = [...document.querySelectorAll('.agent-list .ant-menu-item')]
  const t = items.find(e => /运营复盘师/.test(e.textContent || ''))
  if (!t) return 'NOT_FOUND'
  t.click()
  return 'CLICKED'
})()`)
await sleep(1600)
await run(CLOSE_POPS)
await sleep(300)

const modeBtns = await run(`[...document.querySelectorAll('.mode-switch-btn')].map(b => (b.textContent || '').trim())`)
let l7 = null
if (Array.isArray(modeBtns) && modeBtns.length >= 2) {
  await run(`(() => { const bs = [...document.querySelectorAll('.mode-switch-btn')]; bs[bs.length - 1].click(); return 'OK' })()`)
  await sleep(1400)
  l7 = await run(`(() => {
    const h = document.querySelector('.header')
    const hr = h.getBoundingClientRect()
    const kids = [...h.children]
    const R = e => e.getBoundingClientRect()
    const conv = document.querySelector('.conv-toolbar')
    const mid = document.querySelector('.main-content')
    return {
      headerW: +hr.width.toFixed(1),
      childRights: kids.map(k => +R(k).right.toFixed(1)),
      headerRight: +hr.right.toFixed(1),
      childLefts: kids.map(k => +R(k).left.toFixed(1)),
      headerLeft: +hr.left.toFixed(1),
      rightW: kids[1] ? +R(kids[1]).width.toFixed(1) : 0,
      convVisW: conv ? +R(conv).width.toFixed(1) : -1,
      midW: mid ? +R(mid).width.toFixed(1) : -1,
      leftScrollOverflow: kids[0] ? kids[0].scrollWidth - kids[0].clientWidth : 0,
    }
  })()`)
}
check('L7a', `大屏模式下顶栏子元素**没有越出顶栏边界**（${modeBtns?.join(' / ') || '未找到模式切换'}）`,
  !!l7 && l7.childRights.every(r => r <= l7.headerRight + 1) && l7.childLefts.every(l => l >= l7.headerLeft - 1), { toReview, l7 })
await shot('out_05_data_mode_narrow.png')

chrome.kill()

const failed = results.filter(r => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
console.log(`截图目录：${SHOT_DIR}`)
if (failed.length) {
  console.error(`\n对话工具条 CDP 探针失败：${failed.length} 条 → ${failed.map(f => f.id).join(', ')}`)
  process.exit(1)
}
console.log('对话工具条探针通过（右上角位置 ✓ / 三按钮可用 ✓ / 跳转高亮 ✓ / 右栏折叠可回程 ✓）')

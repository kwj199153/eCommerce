// CDP 真实浏览器验证（第 260 轮建）——左侧边栏的两条**几何**不变量：
//   ① 三个分组标题行（Agent 群 / 资料库 / 能力）的盒子高度**两两相等**，
//      且它们上下的留白也相等（老板原话：「3 个红框的高度要统一」）；
//   ② 左侧边栏**不出现滚轮**（内容不溢出，且即使溢出也不显示滚动条）。
//
// 为什么必须用真实浏览器：这两条都是**布局算出来的**结果 ——
// 静态门禁读源码字符串证明不了「padding 叠加后到底多高」，也证明不了「有没有溢出」。
// 本仓既有 `cdp-repo-banner-tab-probe.mjs` 的范式：headless chrome + CDP，只测渲染结果。
//
// 判据口径（本仓纪律）：
//   - 先自检「选择器真的选到东西」（L0），否则 selector 写错会静默全绿。
//   - 高度比较用**两两相等**，不写死期望像素值（写死就成墓志铭，改设计必红）。
//   - 溢出判定用 `scrollHeight <= clientHeight + 1`（1px 容差给亚像素）。
//   - 「滚轮不可见」用 computed `scrollbar-width`（Chrome 121+ 支持）——
//     不是「有没有溢出」的同义词：溢出可以隐藏滚轮，不溢出也可以强制显示。
//
// 用法：node scripts/cdp-sidebar-layout-probe.mjs [W] [H]
//   PROBE_URL 覆盖地址（默认 http://localhost:5174/）
//   PROBE_SHOT 覆盖截图输出路径
import { spawn } from 'node:child_process'
import { writeFileSync, mkdtempSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9351
const URL = process.env.PROBE_URL || 'http://localhost:5174/'
const W = Number(process.argv[2] || 1600)
// 目标视口高度取自老板截图实测（856px）。**这一档必须过**，其余档只作参考输出。
const H = Number(process.argv[3] || 856)
// 分组标题的选择器。默认是**改造后**的唯一真源类名；
// 量改造前的基线时用 TITLE_SEL=.section-title 覆盖（探针要能对自己的靶子前后各量一次，
// 否则「改完变好了」只是一句无对照的话）。
const TITLE_SEL = process.env.TITLE_SEL || '.sidebar-section-title'

const sleep = ms => new Promise(r => setTimeout(r, ms))

const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail)}`)
}

if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-sidebar-'))
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
const shot = async (file, clip) => {
  const params = { format: 'png' }
  if (clip) params.clip = { ...clip, scale: 1 }
  const r = await send('Page.captureScreenshot', params)
  if (r.result?.data) {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, Buffer.from(r.result.data, 'base64'))
    return true
  }
  return false
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: URL })

// 等**具体元素**出现，不用 body 文本长度当代理判据（本仓纪律）
const ready = 'document.querySelectorAll(".knowledge-base .ant-menu-item").length'
let booted = false
for (let i = 0; i < 25; i++) {
  const n = await run(ready)
  if (typeof n === 'number' && n >= 8) { booted = true; break }
  await sleep(1000)
}

console.log(`viewport = ${W}x${H} | url = ${URL}`)
console.log('boot: 资料库菜单项 =', await run(ready), '| 分组标题 =', await run('document.querySelectorAll("'+TITLE_SEL+'").length'))

if (!booted) {
  const f = process.env.PROBE_SHOT || join(process.cwd(), '..', '.workbuddy', 'probes', 'r260_review_library', 'out_sidebar_boot_fail.png')
  await shot(f)
  console.log('FAIL: 侧边栏未渲染出来（截图见 ' + f + '）—— 先修环境再谈几何')
  chrome.kill(); process.exit(1)
}

// ---------------- 几何测量 ----------------
const MEASURE = `((SEL)=>{
  const r = el => { const b = el.getBoundingClientRect(); return { t:+b.top.toFixed(2), b:+b.bottom.toFixed(2), h:+b.height.toFixed(2), l:+b.left.toFixed(2), r:+b.right.toFixed(2) } }
  const norm = s => (s||'').replace(/\\s+/g,' ').trim()
  const titles = [...document.querySelectorAll(SEL)]
  const sidebar = document.querySelector('.sidebar')
  const account = document.querySelector('.account-entry')

  const refFor = t => {
    const wrap = t.parentElement
    const prev = t.previousElementSibling
    if (prev) { const it = prev.querySelectorAll('.ant-menu-item'); return it.length ? it[it.length-1] : prev }
    const p = wrap.previousElementSibling
    if (!p) return null
    const it = p.querySelectorAll('.ant-menu-item')
    return it.length ? it[it.length-1] : p
  }

  const groups = titles.map(t => {
    const ref = refFor(t)
    const next = t.nextElementSibling
    const first = next ? next.querySelector('.ant-menu-item') : null
    // ★ 只数**该标题紧跟的那个菜单**里的条目：外层容器（.knowledge-base）里有两个菜单，
    //   按 parentElement 数会把「资料库」7 条 +「能力」2 条都算给同一组（实测曾报 9 个）。
    const items = next ? [...next.querySelectorAll('.ant-menu-item')] : []
    return {
      label: norm(t.textContent),
      rect: r(t),
      gapAbove: ref ? +(r(t).t - r(ref).b).toFixed(2) : null,
      gapBelow: first ? +(r(first).t - r(t).b).toFixed(2) : null,
      itemCount: items.length,
      itemHeights: [...new Set(items.map(e => +e.getBoundingClientRect().height.toFixed(2)))],
    }
  })

  // ★ 「自然高度」必须**逐子元素求和**，两个更省事的写法都是假绿：
  //   ① 用 scrollHeight —— .ant-layout-sider-children 有 min-height:100%，
  //      容器被锁在视口高，scrollHeight 永远 == clientHeight（不管内容多短）；
  //   ② 只看 clientHeight —— .account-entry 的 margin-top: auto 会把内容撑满视口，
  //      内容比视口短时同样相等。
  //   所以：把 auto 边距临时置 0，再把每个直接子元素的高度 + 上下外边距加起来。
  //   量完立刻还原，不留副作用。
  const ac = document.querySelector('.account-entry')
  const savedMargin = ac ? ac.style.marginTop : null
  if (ac) ac.style.marginTop = '0px'
  const kids = [...document.querySelector('.ant-layout-sider-children').children]
  let naturalHeight = 0
  const kidH = kids.map(k => {
    const c = getComputedStyle(k)
    const mt = c.marginTop === 'auto' ? 0 : (parseFloat(c.marginTop) || 0)
    const mb = c.marginBottom === 'auto' ? 0 : (parseFloat(c.marginBottom) || 0)
    const h = k.getBoundingClientRect().height
    naturalHeight += h + mt + mb
    return { cls: String(k.className || '').slice(0, 26), h: +h.toFixed(2), mt, mb }
  })
  naturalHeight = +naturalHeight.toFixed(2)
  if (ac) ac.style.marginTop = savedMargin

  // ★ 滚到底再看一次账户入口：这才是 sticky 存在的**唯一理由**。
  //   只测「未滚动时可见」抓不到 sticky 失效 —— 未滚动时它的常规位置本来就在底部附近。
  const sbTop = sidebar.scrollTop
  sidebar.scrollTop = sidebar.scrollHeight
  const acAfter = ac ? (r => ({ t: r.top, b: r.bottom }))(ac.getBoundingClientRect()) : null
  // ★ 判据必须锋利到「**贴住**底边」，不能只判「在视口内」：
  //   实测过一种假绿 —— sider-children 写死 height:100% 时，粘底的包含块只有视口那么高，
  //   滚到底后账户入口被夹在包含块底边（768-ScrollTop），**仍然可见但没贴底**。
  //   「可见」放过它，「贴底」抓住它。
  const acVisibleAfterScroll = !!acAfter && Math.abs(acAfter.b - window.innerHeight) <= 1
  sidebar.scrollTop = sbTop

  const cs = getComputedStyle(sidebar)
  return JSON.stringify({
    naturalHeight,
    acAfterScroll: acAfter,
    acVisibleAfterScroll,
    kidH,
    groups,
    sidebar: {
      ...r(sidebar),
      clientHeight: sidebar.clientHeight,
      scrollHeight: sidebar.scrollHeight,
      overflowY: cs.overflowY,
      scrollbarWidth: cs.scrollbarWidth,
    },
    account: account ? r(account) : null,
    innerHeight: window.innerHeight,
    titleCss: (() => { const t = titles[0]; if (!t) return null; const c = getComputedStyle(t); return { height: c.height, marginTop: c.marginTop, padding: c.padding, fontSize: c.fontSize, lineHeight: c.lineHeight } })(),
  })
})(${JSON.stringify(TITLE_SEL)})`

const raw = await run(MEASURE)
let m = null
try { m = JSON.parse(raw) } catch { /* 下面会报出来 */ }
if (!m) {
  console.log('FAIL: 测量脚本没返回可解析结果 ⟵', String(raw).slice(0, 400))
  chrome.kill(); process.exit(1)
}

const g = m.groups
console.log('\n---- 三个分组标题（实测）----')
for (const x of g) {
  console.log(`  「${x.label}」  y ${x.rect.t}..${x.rect.b}  高 ${x.rect.h}  上间距 ${x.gapAbove}  下间距 ${x.gapBelow}  本组菜单项 ${x.itemCount} 个（高度 ${JSON.stringify(x.itemHeights)}）`)
}
console.log('---- 侧边栏 ----')
console.log(`  clientHeight=${m.sidebar.clientHeight} scrollHeight=${m.sidebar.scrollHeight} 自然内容高=${m.naturalHeight} overflowY=${m.sidebar.overflowY} scrollbar-width=${m.sidebar.scrollbarWidth} 视口高=${m.innerHeight}`)
console.log('  账户入口 rect =', JSON.stringify(m.account))
console.log('  自然高度分解 =', JSON.stringify(m.kidH))
console.log('  滚到底后账户入口 =', JSON.stringify(m.acAfterScroll), '可见 =', m.acVisibleAfterScroll)
console.log('  标题 CSS =', JSON.stringify(m.titleCss))

const spread = arr => Math.max(...arr) - Math.min(...arr)
check('L0', '自检：恰好选到 3 个分组标题（选择器没写错）', g.length === 3, g.map(x => x.label))
check('L1', '三个分组标题的盒子高度两两相等（≤0.5px）', spread(g.map(x => x.rect.h)) <= 0.5, g.map(x => x.rect.h))
check('L2', '三个分组标题的**上间距**相等（≤1px）', spread(g.map(x => x.gapAbove)) <= 1, g.map(x => x.gapAbove))
check('L3', '三个分组标题的**下间距**相等（≤0.5px）', spread(g.map(x => x.gapBelow)) <= 0.5, g.map(x => x.gapBelow))
// 小视口（< 老板实测的 856）本来就装不下 16 个菜单项 —— 那一档只要求「不出滚轮 + 账户入口可见」，
// 用 PROBE_ALLOW_OVERFLOW=1 把本条降级成 INFO，避免用一个装不下的高度去断言「装得下」。
const fits = m.naturalHeight <= m.sidebar.clientHeight
if (process.env.PROBE_ALLOW_OVERFLOW === '1') {
  console.log(`INFO  L4  自然内容高 ${m.naturalHeight} vs 视口 ${m.sidebar.clientHeight}（本档允许溢出，不判红）`)
} else {
  check('L4', '侧边栏自然内容高 ≤ 视口（置零 auto 边距后实测）⇒ 确实没有可滚的东西', fits, { natural: m.naturalHeight, ch: m.sidebar.clientHeight })
}
check('L5', '即使溢出也不显示滚轮（computed scrollbar-width === none）', m.sidebar.scrollbarWidth === 'none', m.sidebar.scrollbarWidth)
check('L6', '账户入口完整落在视口内（没被挤出可视区）', !!m.account && m.account.b >= -0.5 && m.account.b <= m.innerHeight + 0.5, m.account)
check('L7', '每组菜单项高度内部一致（同一组内不出现两种行高）', g.every(x => x.itemHeights.length === 1), g.map(x => x.itemHeights))
// 条目装不下时（小窗档）才需要这条；装得下时它恒真，但不会假绿 —— 恒真只是冗余，不是错。
check('L8', '滚到底后账户入口**贴住视口底边**（粘底真的生效，不是靠"刚好在里面"）', m.acVisibleAfterScroll === true, { rect: m.acAfterScroll, vh: m.innerHeight })

// ---------------- 截图（给老板看效果） ----------------
const shotPath = process.env.PROBE_SHOT || join(process.cwd(), '..', '.workbuddy', 'probes', 'r260_review_library', `out_sidebar_${W}x${H}.png`)
const okShot = await shot(shotPath, { x: 0, y: 0, width: 300, height: H })
console.log('\n截图：', okShot ? shotPath : '(失败)')

const failed = results.filter(x => !x.ok)
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
if (failed.length) console.log('红：' + failed.map(x => x.id).join(', '))

chrome.kill()
await sleep(300)
process.exit(failed.length ? 1 : 0)

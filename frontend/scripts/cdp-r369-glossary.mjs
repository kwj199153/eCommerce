// CDP 真机探针（第 369 轮 P0）—— 店铺术语表的**整链**：设置页 → localStorage → 划词请求体。
//
// 为什么必须真机跑（单测 / AST 门禁 / 对账门禁都覆盖不到的那一段）：
//   1. `tests/unit/glossary.test.ts` 跑在 `environment: 'node'`（本项目不装 jsdom）：
//      它钉得住解析与存取**语义**，但钉不住「设置页那块 UI 真的渲染出来了、真的把值写进了
//      localStorage、真的显示出了读数」。UI 接线错（v-model 没接、watch 没挂、tab 里没插进去）
//      在单测与 `vue-tsc` 面前**全是绿的**。
//   2. `check-glossary-parity.cjs` 是 **AST 常量对账** —— 它证明两端常量一致，
//      证明不了「这次划词请求的 body 里真的有 glossary 这个键」。
//   3. 最关键的一条：**「前端把 glossary 拼进了 payload」与「后端真的收到了」是两件事。**
//      字段名拼错时 pydantic 会静默忽略多余字段（不报 422、术语表只是不生效），
//      而这条链上任何一个环节错，症状都只是「译法没按我配的走」——用户无从归因。
//      ⇒ 只有真机拦下**真请求**才能证明它接通了。
//
// 判据口径（沿用本仓纪律）：
//   · 每条集合判据配 L0 自检（设置页真的渲染了 / 工作台真的渲染了 / 拖选真的产生了选区）；
//   · 「空表不带键」配**正控**（同一轮里配了表的那次必须带键，否则「不带键」是空跑）；
//   · 读数不靠单一来源：DOM 渲染 + `localStorage` 实体各读一次，两者必须一致；
//   · 探针自身失效（dev server 没起 / 演示身份进不去）⇒ 退出码 **2**，不并进 PASS/FAIL。
//
// 用法：node scripts/cdp-r369-glossary.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/，需 dev server 在跑）
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9406
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r369')

/**
 * 探针专用店铺 id —— 只用它的**字符串**做分键验证，不要求后端真有这家店
 * （术语表是纯前端本地偏好，存储键只是个字符串，与后端归属无关）。
 *
 * ★ 副作用（如实登记，别误判成产品缺陷）：这个 id 后端并不认识，所以工作台加载店铺
 *   数据时会被归属校验拒掉，画面右上角会刷出若干条「无权访问该店铺」的红色提示。
 *   那是**探针自己造的**，不是本轮引入的缺陷 —— 截图里看到它们时别慌。
 *   不改成「真店铺 id」是有意的：那要多查一次后端，而本探针要证的只是「按 key 分桶存」，
 *   用一个后端不认识的 key 反而把「存储与归属解耦」这件事一并钉住了。
 */
const PROBE_SHOP = 'store_probe_369'
const GLOSSARY_KEY = `translate_glossary::${PROBE_SHOP}`
/** 预置的术语表：3 条有效 + 1 行坏行（用来验读数里的「未生效」提示） */
const SEED_GLOSSARY = [
  'Noise Cancelling=主动降噪',
  'Gift Box=礼盒装',
  'Portable=便携式',
  '# 这行是注释，不算条目',
  '这行没有等号',
].join('\n')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r369-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,1020',
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', 'about:blank',
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
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
/** 非请求类事件一并收：Network 请求体（本探针的核心读数）+ 页面异常 */
const events = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method) events.push(m)
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  const ex = r?.result?.exceptionDetails
  if (ex) throw new Error((ex.exception?.description || ex.text || '').slice(0, 400))
  return r?.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}
const waitFor = async (expr, ms = 25000, step = 250) => {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await run(expr)) return true } catch { /* 渲染中途 */ }
    await sleep(step)
  }
  return false
}

const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', {
  type, x, y, button: 'left', clickCount: 1,
  buttons: type === 'mouseReleased' ? 0 : 1,
  ...extra,
})

const rectOf = async (sel) => JSON.parse(await run(
  `(() => {
     const e = document.querySelector(${JSON.stringify(sel)})
     if (!e) return 'null'
     const r = e.getBoundingClientRect()
     return JSON.stringify({ top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height })
   })()`,
) || 'null')

const dragIn = async (sel, ox1, ox2, yFrac = 0.5, steps = 14) => {
  const r = await rectOf(sel)
  if (!r) throw new Error(`元素不存在：${sel}`)
  const y = Math.round(r.top + r.height * yFrac)
  const x1 = Math.round(r.left + ox1)
  const x2 = Math.round(r.left + ox2)
  await mouse('mouseMoved', x1, y, { buttons: 0 })
  await mouse('mousePressed', x1, y)
  for (let i = 1; i <= steps; i++) {
    await mouse('mouseMoved', Math.round(x1 + ((x2 - x1) * i) / steps), y)
    await sleep(12)
  }
  await mouse('mouseReleased', x2, y)
  return { r, x1, x2, y }
}

/**
 * 把「当前选区」复位成空。
 * ★ 第 366 轮实测踩过：控件里**已有选区**时，下一次 mousePressed 落在选区内部会走
 *   「原生拖拽已选文字」，`mouseup` 不再派发 ⇒ `onMouseUp` 那个唯一入口根本不执行。
 *   那是**探针操作方式**造成的假红，不是产品缺陷。
 */
const resetField = async (sel) => {
  await run(`(() => {
    try { const ae = document.activeElement; if (ae && ae.blur) ae.blur() } catch (e) {}
    const s = window.getSelection(); if (s && s.removeAllRanges) s.removeAllRanges()
    const e = document.querySelector(${JSON.stringify(sel)})
    if (e) { try { e.setSelectionRange(0, 0) } catch (err) {} }
    return true
  })()`)
  await sleep(120)
}

/** 取「画布上真实发出的」translate-selection 请求体（字符串 payload） */
const selectRequests = () => events
  .filter((e) => e.method === 'Network.requestWillBeSent')
  .map((e) => e.params && e.params.request)
  .filter((r) => r && typeof r.url === 'string' && r.url.indexOf('translate-selection') >= 0)

const parseBody = (req) => {
  try { return JSON.parse(req.postData || '{}') } catch { return null }
}

// ---------------------------------------------------------------------------
// 启动（演示身份 + 探针店铺 + 预置术语表）
// ★ 用 sessionStorage 守卫「只 seed 一次」：本探针要**导航两次**（/settings → /），
//   而 addScriptToEvaluateOnNewDocument 每次导航都会执行 —— 不守卫的话第二次导航会把
//   术语表**重新写回去**，B2（清空后不带键）就永远是假红。
// ---------------------------------------------------------------------------
const AUTH = {
  access_token: 'demo-token',
  refresh_token: 'demo-refresh-token',
  user_info: { id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' },
}
await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 1020, deviceScaleFactor: 1, mobile: false })
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', ${JSON.stringify(AUTH.access_token)});
    localStorage.setItem('refresh_token', ${JSON.stringify(AUTH.refresh_token)});
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify(AUTH.user_info))});
    if (!sessionStorage.getItem('r369_seeded')) {
      localStorage.setItem('current_shop_id', ${JSON.stringify(PROBE_SHOP)});
      localStorage.setItem(${JSON.stringify(GLOSSARY_KEY)}, ${JSON.stringify(SEED_GLOSSARY)});
      sessionStorage.setItem('r369_seeded', '1');
    }
  `,
})

// ===========================================================================
// A 组 · 设置页（/settings 路由模式，自行打开抽屉）
// ===========================================================================
await send('Page.navigate', { url: URL.replace(/\/$/, '') + '/settings' })

const settingsUp = await waitFor(`(document.body.innerText || '').indexOf('交互偏好') >= 0`, 30000)
if (!settingsUp) {
  console.log('\nPROBE-ERR  设置页没渲染出来（dev server / 路由 / 演示身份），探针自身无效。')
  check('P0', '★自检：设置页已渲染', null, { url: await run('location.href') })
  chrome.kill()
  console.log('\n---- 0 PASS / 0 FAIL / 1 SKIP（探针无效，退出码 2）----')
  process.exit(2)
}
check('P0', '★自检：/settings 路由页已渲染（真 app，非空壳）', true, null)

// A1 切到「交互偏好」tab
await run(`(() => {
  const tab = [...document.querySelectorAll('.ant-tabs-tab')]
    .find((t) => (t.innerText || '').indexOf('交互偏好') >= 0)
  if (tab) tab.click()
  return !!tab
})()`)
await sleep(500)
const tabSwitched = await waitFor(`!!document.querySelector('.glossary-input')`, 8000)
check('A1', '切「交互偏好」⇒ 翻译分区里出现术语表输入框', tabSwitched,
  { hasTextarea: await run(`!!document.querySelector('.glossary-input')`) })

// A2 预置的术语表被读出来了（v-model ← loadGlossary(currentShopId)）
const initial = JSON.parse(await run(`(() => {
  const el = document.querySelector('.glossary-input')
  return JSON.stringify({ value: el ? el.value : null, key: localStorage.getItem('current_shop_id') })
})()`) || '{}')
check('A2', '输入框初值 = 该店铺 localStorage 里的术语表（按 current_shop_id 分键读出来）',
  !!initial.value && initial.value === SEED_GLOSSARY && initial.key === PROBE_SHOP,
  { key: initial.key, gotLen: (initial.value || '').length, wantLen: SEED_GLOSSARY.length })

// A3 读数：3 条有效 / 1 行未生效
const statText = await run(`(() => {
  const p = document.querySelector('.glossary-stat')
  return p ? p.innerText.trim() : null
})()`)
check('A3', '读数如实报「已识别 3 条」+「1 行未生效」（后端宽松跳错在界面上可见化）',
  !!statText && statText.indexOf('已识别 3 条') >= 0 && statText.indexOf('1 行未生效') >= 0,
  { statText })
await shot('a3-settings-glossary')

// A4 改内容 ⇒ 立即落本机（无保存按钮），且键仍是当前店铺那个
const NEXT = 'Noise Cancelling=主动降噪\nWaterproof=防水'
await run(`(() => {
  const el = document.querySelector('.glossary-input')
  el.value = ${JSON.stringify(NEXT)}
  el.dispatchEvent(new Event('input', { bubbles: true }))
  return true
})()`)
await sleep(300)
const afterEdit = JSON.parse(await run(`(() => JSON.stringify({
  stored: localStorage.getItem(${JSON.stringify(GLOSSARY_KEY)}),
  otherKeys: Object.keys(localStorage).filter((k) => k.indexOf('translate_glossary::') === 0),
  stat: (document.querySelector('.glossary-stat') || {}).innerText || '',
}))()`) || '{}')
check('A4', '改动即落本机（无保存按钮）且写进**当前店铺**的键',
  afterEdit.stored === NEXT
  && Array.isArray(afterEdit.otherKeys) && afterEdit.otherKeys.length === 1
  && afterEdit.otherKeys[0] === GLOSSARY_KEY,
  afterEdit)
check('A5', '读数跟着变（3 条 → 2 条，坏行提示消失）',
  String(afterEdit.stat).indexOf('已识别 2 条') >= 0 && String(afterEdit.stat).indexOf('未生效') < 0,
  { stat: afterEdit.stat })

// A6 ★ 术语表区**不显示店铺名** —— 第 369 轮实测踩到的取舍（A9 判据：全前端
//    `shopStore.currentShop.name` 的消费点只允许 1 个）。这条是**防回归**：
//    谁要是「顺手把店名加回来」，A9 会红，而 A9 是 AST 门禁、看不到渲染结果，
//    这里补一条渲染面的读数。
const blockText = await run(`(() => {
  const el = document.querySelector('.pref-block')
  return el ? el.innerText : null
})()`)
check('A6', '★术语表区**不渲染店铺名**（不引入 shop 作用域文案的第二个消费点）',
  !!blockText && blockText.indexOf('店铺：') < 0 && blockText.indexOf('当前编辑的是') < 0,
  { blockText: String(blockText).slice(0, 120) })

// ===========================================================================
// B 组 · 划词链路（回工作台；全局监听挂在 Workspace 上）
// ===========================================================================
await send('Page.navigate', { url: URL })
const workspaceUp = await waitFor(
  `!!document.querySelector('.ant-layout') && (document.body.innerText || '').length > 200`, 30000)
if (!workspaceUp) {
  check('P1', '★自检：Workspace 已渲染（B 组前提）', null, { url: await run('location.href') })
  chrome.kill()
  console.log('\n---- 探针在 B 组失效（退出码 2）----')
  process.exit(2)
}

// 插入一个**原生** textarea（原生控件就是被测对象要处理的东西本身）
await run(`(() => {
  const host = document.createElement('div')
  host.id = 'r369-host'
  host.style.cssText = 'position:fixed;left:120px;top:430px;width:660px;z-index:900;'
    + 'background:#fff;border:1px solid #d9d9d9;border-radius:6px;padding:10px;box-sizing:border-box'
  host.innerHTML = '<textarea id="r369-area" style="display:block;width:620px;height:56px;'
    + 'font-size:14px;line-height:20px;padding:4px 8px;box-sizing:border-box"></textarea>'
  document.body.appendChild(host)
  document.getElementById('r369-area').value = 'Noise Cancelling Wireless Earbuds with 40H Playtime'
  return true
})()`)
await sleep(300)

// B1 有术语表 ⇒ 请求体带 glossary 且与 localStorage 逐字相同
await resetField('#r369-area')
await dragIn('#r369-area', 12, 300, 0.3)
const layerUp = await waitFor(`!!document.querySelector('.stl-layer')`, 12000)
const reqs1 = selectRequests()
const body1 = reqs1.length ? parseBody(reqs1[reqs1.length - 1]) : null
check('B0', '★自检：真实鼠标拖选真的触发了划词（浮层出现 + 请求已发出）',
  layerUp && reqs1.length > 0, { layerUp, reqCount: reqs1.length })
check('B1', '★ 请求体带了 glossary，且逐字等于本店 localStorage 的值',
  !!body1 && typeof body1.glossary === 'string' && body1.glossary === NEXT,
  { glossary: body1 ? String(body1.glossary).slice(0, 60) : null, keys: body1 ? Object.keys(body1) : null })

// B2 空表 ⇒ 请求体**不带这**个键（正控：上一条已证明「带」是能出现的）
await run(`(() => {
  const el = document.querySelector('.glossary-input')
  return localStorage.removeItem(${JSON.stringify(GLOSSARY_KEY)})
})()`)
await sleep(200)
const cleared = await run(`localStorage.getItem(${JSON.stringify(GLOSSARY_KEY)}) === null`)
const before = selectRequests().length
await resetField('#r369-area')
await dragIn('#r369-area', 12, 300, 0.3)
await waitFor(`!!document.querySelector('.stl-layer')`, 12000)
await sleep(600)
const reqs2 = selectRequests()
const body2 = reqs2.length > before ? parseBody(reqs2[reqs2.length - 1]) : null
// ★ 这里刻意**不**逐字期望「拖选出来的那串字」：选区边界由像素决定（textarea 宽度、
//   字体渲染），逐字期望会把「探针坐标差了几像素」变成一条假红（本轮实测踩过一次：
//   期望 25 字符、实际拖到整行 48 字符）。要证的只有一件事 —— 这一条确实是划词请求、
//   且带上了原文 ⇒ 用前缀断言。
const AREA_TEXT = 'Noise Cancelling Wireless Earbuds with 40H Playtime'
check('B2', '★★ 本店没配术语表 ⇒ 请求体**连 glossary 键都不带**（清空后立即生效，无需重启）',
  cleared && !!body2 && !('glossary' in body2) && !!body2.text && AREA_TEXT.startsWith(body2.text),
  { cleared, keys: body2 ? Object.keys(body2) : null, text: body2 ? body2.text : null })
await shot('b2-workspace-selection')

// B3 后端接受（非 422）—— 「接线通了」的最后一段。
// ★ 轮询而不是立刻读：划词要真的走一趟 LLM，响应可能比拖选晚几秒。
const statusesOf = () => events
  .filter((e) => e.method === 'Network.responseReceived')
  .map((e) => e.params && e.params.response)
  .filter((r) => r && typeof r.url === 'string' && r.url.indexOf('translate-selection') >= 0)
  .map((r) => r.status)
let statuses = []
for (let i = 0; i < 60; i++) {
  statuses = statusesOf()
  if (statuses.length) break
  await sleep(500)
}
check('B3', '后端接受请求体（无 422 —— 字段名拼错时 pydantic 会静默忽略，只有 422 能暴露）',
  statuses.length > 0 && statuses.every((s) => s >= 200 && s < 300),
  {
    statuses,
    // 诊断用：读不到响应时至少能看出 Network 域到底送来了哪些事件
    netMethods: [...new Set(events.filter((e) => /^Network\./.test(e.method)).map((e) => e.method))],
  })

// ---------------------------------------------------------------------------
const failed = results.filter((r) => r.state === 'FAIL')
const passed = results.filter((r) => r.state === 'PASS')
console.log(`\n---- ${passed.length} PASS / ${failed.length} FAIL / ${results.filter((r) => r.state === 'SKIP').length} SKIP ----`)
console.log(`截图：${SHOT_DIR}`)
ws.close()
chrome.kill()
process.exit(failed.length ? 1 : 0)

// CDP 真机探针（第 366 轮第三刀）—— **表单控件内真实鼠标拖选**的划词翻译。
//
// 为什么必须真机跑（单测与 AST 门禁都覆盖不到的那一段）：
//   1. 单测跑在 `environment: 'node'`（本项目**不装 jsdom**）—— 它能钉住
//      `readFieldSelection` 的取值语义、也能钉住 `rectOfFieldSelection` 的**算术**，
//      但它在文件头里就写明了「★ 证明不了真实浏览器几何」。
//   2. `check-selection-field-rule.cjs` 是 **AST 形态门禁** —— 它只能证明
//      「源码里那条通道是可达的」，证明不了「真按下鼠标拖过一段文字之后，
//      浮层真的出现在控件附近、原文真的等于选中的那串字」。
//   3. 本探针的输入方式是 **CDP 真实鼠标事件**
//      （`Input.dispatchMouseEvent`: mouseMoved → mousePressed → N×mouseMoved → mouseReleased），
//      不是 `el.setSelectionRange()` 那种「自己造一个选区」——
//      后者会把「浏览器到底为什么会在控件里产生选区」这一步整个跳过，
//      而那正是上一轮踩坑的地方（控件内的 range 是挂在 BODY 上的伪 range，rect 恒 0×0）。
//
// 被测对象是**真代码**：真 dev server 上的真 Workspace（`GlobalTranslateLayers` 里挂着
// 真的 `SelectionTranslateLayer` ⇒ 真的全局 `startSelectionWatcher()`）。
// 探针往页面里插几个**原生** input/textarea（原生控件不是「行为等价的本地拷贝」），
// 全局监听照样能收到 —— 因为它是 document 级的。
//
// 判据口径（沿用本仓纪律）：
//   · 每条集合判据配 L0 自检（工作台已渲染 / 元素真的在指针下 / 拖选真的产生了选区）；
//   · 「不许弹」必须配**正控**（同一轮里普通 input 必须弹，否则「password 不弹」是空跑）；
//   · 读数**不靠浮层自己**：同时读「渲染出来的 DOM」与「模块单例里的 state」，
//     并用「两者一致」自证探针拿到的 state 就是驱动浮层的那个（对象身份那条纪律的行为版）；
//   · 探针自身失效（工作台没起来 / 全局监听没装）⇒ 退出码 **2**，不并进 PASS/FAIL。
//
// ★★ 写这个探针时踩到的两个坑（都不是产品缺陷，但都会让人**归错因**）：
//   ① **`import('/src/composables/useSelectionTranslate.ts')` 会拿到另一份模块实例。**
//      应用实际请求的 URL 带 Vite 的 HMR 后缀 `?t=<ts>`（该文件被改过就有），
//      裸路径是新实例 ⇒ 行为完全等价、对象身份不同。症状极具误导性：
//      浮层 DOM 明明弹了，探针读到的 `state.original` 却是空、`visible` 是 false，
//      看起来像「全局监听没装」。⇒ 必须从 `performance.getEntriesByType('resource')`
//      里捞出**浏览器真正请求过的那条 URL** 再 import（见 setup 段）。
//   ② **在「已有选区」内部按下鼠标，Chrome 会走原生拖拽已选文字，`mouseup` 不再派发。**
//      于是 `onMouseUp` 这个唯一入口根本不执行、浮层不弹 —— 与功能无关。
//      ⇒ 每次拖选前必须把待测控件复位成**无选区**（见 `resetField` 的注释）。
//      实测证据：`.workbuddy/probes/r366/diag_drag_timeline.mjs`、
//      `.workbuddy/probes/r366/diag_module_identity.mjs`。
//
// 用法：node scripts/cdp-r366c-textfield-selection.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/，需 dev server 在跑）
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9404
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r366')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r366c-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
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
/** 非请求类事件（异常 / console）也要收：用来判「探针跑的路上有没有真错误」 */
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

// ---------------------------------------------------------------------------
// 真实鼠标（CDP Input 域）。★ 这是本探针的**全部价值**：不用 setSelectionRange。
// ---------------------------------------------------------------------------
const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', {
  type, x, y, button: 'left', clickCount: 1,
  buttons: type === 'mouseReleased' ? 0 : 1,
  ...extra,
})
const keyStroke = (k, code, vk) => send('Input.dispatchKeyEvent', {
  type: 'keyDown', key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, text: k,
})

const rectOf = async (sel) => JSON.parse(await run(
  `(() => {
     const e = document.querySelector(${JSON.stringify(sel)})
     if (!e) return 'null'
     const r = e.getBoundingClientRect()
     return JSON.stringify({ top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height })
   })()`,
) || 'null')

/**
 * 在元素上做一次真实拖选。
 * @param ox1/ox2  起止点相对元素 left 的像素偏移（**不是**比例 —— 比例会把「右边缘」算成
 *                 width，落进边框/滚动条里，得到 0 长度选区而假红）
 * @param yFrac    纵向落点比例（textarea 用 0.28 落在第一行）
 */
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

const selOf = async (sel) => JSON.parse(await run(`(() => {
  const e = document.querySelector(${JSON.stringify(sel)})
  if (!e) return '{}'
  const v = e.value
  const s = e.selectionStart
  const n = e.selectionEnd
  return JSON.stringify({
    value: v, start: s, end: n,
    text: (typeof s === 'number' && typeof n === 'number') ? v.slice(s, n) : null,
    focused: document.activeElement === e,
  })
})()`) || '{}')

/** 同时读「渲染出的 DOM」与「模块单例 state」——两者必须一致，否则探针看的是另一个对象 */
const readLayer = async () => JSON.parse(await run(`(() => {
  const el = document.querySelector('.stl-layer')
  const st = window.__r366c.state
  return JSON.stringify({
    dom: !!el,
    src: el ? (el.querySelector('.stl-src') || {}).innerText || '' : '',
    dst: el ? (el.querySelector('.stl-dst') || {}).innerText || '' : '',
    visible: !!st.visible,
    original: st.original,
    loading: !!st.loading,
    error: st.error || '',
    anchor: st.anchor ? { top: st.anchor.top, bottom: st.anchor.bottom, left: st.anchor.left, width: st.anchor.width } : null,
  })
})()`) || '{}')

const hideLayer = () => run('window.__r366c.api.hide(), true')

/**
 * 把「当前选区」复位成**空**。
 *
 * ★★ 为什么每次拖选前都必须做（实测踩过，不是洁癖）：
 *   如果控件里**已经有一段选区**（比如上一次拖选留下的），下一次 `mousePressed`
 *   落在那段选区**内部**时，Chrome 会走 **「原生拖拽已选文字」** 那条路，
 *   而不是「塌陷到点击点再拖」——后果是 **`mouseup` 不再派发到 document**，
 *   于是 `onMouseUp` 这个唯一入口根本不执行、翻译不触发、浮层不出现。
 *   实测读数（`.workbuddy/probes/r366/diag_drag_timeline.mjs`）：
 *     press 在 45% 处立刻读 → selectionStart=0 selectionEnd=51（**旧选区原封不动**）
 *     随后 14 步 mouseMoved + mouseReleased → `state.visible` 全程 false、DOM 全程无
 *   ⇒ 这是**探针操作方式**造成的假红（真实用户也不会「在选区里按住再拖」去翻译），
 *     不是产品缺陷。修法是把待测状态复位干净 —— 复位只把选区清**空**，
 *     真正要被测量的选区仍然完全由**真实鼠标拖选**产生。
 */
const resetField = async (sel) => {
  await run(`(() => {
    try { const ae = document.activeElement; if (ae && ae.blur) ae.blur() } catch (e) {}
    const s = window.getSelection(); if (s && s.removeAllRanges) s.removeAllRanges()
    const e = document.querySelector(${JSON.stringify(sel)})
    if (e) { try { e.setSelectionRange(0, 0) } catch (err) { /* number 之类不支持 */ } }
    return true
  })()`)
  await sleep(120)
}

const inRect = (a, r, pad = 2) => !!a && a.width > 0
  && a.top >= r.top - pad && a.bottom <= r.bottom + pad
  && a.left >= r.left - pad && a.left + a.width <= r.right + pad

// ---------------------------------------------------------------------------
// 启动 + 演示身份登录（沿用既有探针：dev server 的 DEMO_MODE 会自动注入，这里显式给上）
// ---------------------------------------------------------------------------
const AUTH = {
  access_token: 'demo-token',
  refresh_token: 'demo-refresh-token',
  user_info: { id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' },
}
await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1680, height: 900, deviceScaleFactor: 1, mobile: false })
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', ${JSON.stringify(AUTH.access_token)});
    localStorage.setItem('refresh_token', ${JSON.stringify(AUTH.refresh_token)});
    localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify(AUTH.user_info))});
  `,
})
await send('Page.navigate', { url: URL })

const rendered = await waitFor(
  `!!document.querySelector('.ant-layout') && (document.body.innerText || '').length > 200`,
  30000,
)
if (!rendered) {
  console.log('\nPROBE-ERR  工作台没渲染出来（dev server / 路由 / 演示身份），探针自身无效。')
  check('P0', '★自检：Workspace 已渲染', null, { url: await run('location.href') })
  chrome.kill()
  console.log('\n---- 0 PASS / 0 FAIL / 1 SKIP（探针无效，退出码 2）----')
  process.exit(2)
}
check('P0', '★自检：Workspace 已渲染（真 app，非空壳）', true, null)

// ===========================================================================
// 插入**原生**控件（真 input / textarea）。原生控件就是被测对象要处理的东西本身，
// 不是「行为等价的本地拷贝」；全局监听是 document 级的，插进去照样生效。
// ===========================================================================
const setupRes = await run(`
(async () => {
  try {
    // ★★ 这里踩过一次真坑，务必看清：
    //   应用请求的模块 URL **可能带 Vite 的 HMR 时间戳**（?t=<ts>，该文件被改过就有），
    //   而 import('/src/composables/useSelectionTranslate.ts') 会**另建一份模块实例**
    //   —— 两份行为完全等价，只有对象身份不同（本仓记录过这类陷阱）。
    //   症状极具误导性：浮层 DOM 明明出现了，探针读到的 state 却是 original:'' / visible:false，
    //   看起来像「全局监听没装上」。实测证据（.workbuddy/probes/r366/diag_module_identity.mjs）：
    //     应用实际请求 → /src/composables/useSelectionTranslate.ts?t=1790952321539
    //     探针裸路径   → 另一个实例（sameAB=false）
    //   ⇒ 正确做法：从浏览器**真正请求过的 URL** 里把那条捞出来再 import。
    const pick = (frag) => {
      const hit = performance.getEntriesByType('resource')
        .map((e) => e.name)
        .filter((n) => n.indexOf(frag) >= 0)
      return hit.length ? hit[hit.length - 1] : frag
    }
    const url = pick('/src/composables/useSelectionTranslate.ts')
    const utilUrl = pick('/src/utils/textSelection.ts')
    const mod = await import(url)
    const util = await import(utilUrl)
    const api = mod.useSelectionTranslate()
    api.setAutoEnabled(true)   // 自动弹开关：本探针要测的正是「自动弹」

    const line = String.fromCharCode(10)   // ★ 不用反斜杠转义：外层是模板字符串
    const host = document.createElement('div')
    host.id = 'r366c-host'
    host.style.cssText = 'position:fixed;left:120px;top:420px;width:660px;z-index:900;'
      + 'background:#ffffff;border:1px solid #d9d9d9;border-radius:6px;padding:10px;'
      + 'box-sizing:border-box;font-family:system-ui;color:#222;user-select:text'
    host.innerHTML =
        '<p id="r366c-plain" style="margin:0 0 10px;font-size:15px;line-height:22px">Whisper-Quiet Ultrasonic Humidifier with 30dB Noise Level for Bedroom Use</p>'
      + '<input id="r366c-input" style="display:block;width:620px;height:34px;font-size:14px;font-family:system-ui;line-height:20px;padding:4px 8px;box-sizing:border-box" value="Noise Cancelling Wireless Earbuds with 40H Playtime">'
      + '<textarea id="r366c-area" style="display:block;width:620px;height:64px;margin-top:8px;font-size:14px;font-family:system-ui;line-height:20px;padding:4px 8px;box-sizing:border-box"></textarea>'
      + '<input id="r366c-pwd" type="password" style="display:block;width:620px;height:34px;margin-top:8px;font-size:14px;font-family:system-ui;padding:4px 8px;box-sizing:border-box" value="S3cret-Passw0rd-XYZ">'
      + '<input id="r366c-num" type="number" style="display:block;width:220px;height:34px;margin-top:8px;font-size:14px;font-family:system-ui;padding:4px 8px;box-sizing:border-box" value="1234567890">'
      + '<input id="r366c-type" style="display:block;width:420px;height:34px;margin-top:8px;font-size:14px;font-family:system-ui;padding:4px 8px;box-sizing:border-box" value="Portable Travel Case with Carabiner Clip">'
    document.body.appendChild(host)

    const area = document.getElementById('r366c-area')
    area.value = ['Bluetooth 5.3 Stable Connection and Touch Control',
                  'Crystal Clear Calls with Dual Microphone Array'].join(line)

    window.__r366c = {
      api, util, host, url, utilUrl,
      state: api.state,
      // 门禁/单测都钉「唯一真源」，这里也用它 —— 直接问真代码「这个控件可读吗」
      readField: (sel) => util.readFieldSelection(document.querySelector(sel)),
      under: (sel, dx, frac) => {
        const e = document.querySelector(sel)
        const r = e.getBoundingClientRect()
        const hit = document.elementFromPoint(Math.round(r.left + dx), Math.round(r.top + r.height * frac))
        return hit === e ? 'self' : (hit ? (hit.id || hit.tagName) : 'null')
      },
    }
    return JSON.stringify({ ok: true, url, utilUrl, hasApi: typeof api.hide === 'function', hasUtil: typeof util.readFieldSelection === 'function' })
  } catch (e) {
    return JSON.stringify({ ok: false, err: String(e && e.stack || e).slice(0, 800) })
  }
})()`)

const setup = JSON.parse(setupRes || '{}')
if (!setup.ok) {
  console.log(`\nPROBE-ERR  导入真模块失败，探针自身无效：\n${setup.err}\n`)
  check('H0', '★自检：真 useSelectionTranslate / textSelection 已导入', null, setup.err)
  chrome.kill()
  console.log('\n---- 0 PASS / 0 FAIL / 1 SKIP（探针无效，退出码 2）----')
  process.exit(2)
}
check('H0', '★自检：真 useSelectionTranslate / textSelection 已导入', true, null)
// ★ 身份自检：必须是应用**正在用的那一份**（含 HMR 后缀，见上面那段注释）
check('H0b', '★自检：按浏览器实际请求的 URL 取模块（否则是另一份实例、行为等价但身份不同）',
  !!setup.url, { url: setup.url, utilUrl: setup.utilUrl })
console.log(`      · 模块实际 URL：${setup.url}`)

// 自检：元素真的在指针下（否则「浮层没弹」的归因会指错方向）
const hits = JSON.parse(await run(`JSON.stringify({
  input: window.__r366c.under('#r366c-input', 40, 0.5),
  area: window.__r366c.under('#r366c-area', 40, 0.28),
  pwd: window.__r366c.under('#r366c-pwd', 40, 0.5),
  plain: window.__r366c.under('#r366c-plain', 40, 0.5),
})`) || '{}')
check('H1', '★自检：四个被测控件都真的在指针下（没被任何浮层/遮罩盖住）',
  Object.values(hits).every((v) => v === 'self'), hits)
await shot('30-host-mounted')

// ===========================================================================
// G1 —— 正控①：**正文选区**回归不坏。
//        这条同时是本探针的「全局监听是否装上」自检 —— 它不绿，后面全部无意义。
// ===========================================================================
await hideLayer()
await resetField('#r366c-plain')
await dragIn('#r366c-plain', 3, 220, 0.5, 12)
const g1shown = await waitFor(`!!document.querySelector('.stl-layer')`, 4000, 120)
const g1 = await readLayer()
const g1text = await run(`(window.getSelection() || { toString: () => '' }).toString().trim()`)
const g1ok = g1shown && g1.dom && g1.visible && g1text.length > 5 && g1.original === g1text
check('G1', '★★ 正控①：正文（<p>）真实拖选 ⇒ 浮层出现，原文 === window.getSelection()',
  g1ok, { g1shown, original: g1.original, g1text })

if (!g1ok) {
  // 「浮层 DOM 在、但**我们手里的** state 说没显示」⇒ 只能是两份实例（DOM 查询与实例无关）
  const mismatch = g1shown === true && g1.visible === false
  console.log(mismatch
    ? '\nPROBE-ERR  浮层 DOM 出现过，但探针手里的 state 是空 ⇒ **拿到了另一份模块实例**'
      + '（Vite `?t=` HMR 后缀，见 setup 段注释），不是功能没生效。'
    : '\nPROBE-ERR  正文选区都不弹 ⇒ 全局监听没装上（不在 Workspace？路由/演示身份异常？），探针自身无效。')
  check('G1x', '★自检：全局划词监听已装载（正文正控）', null, { original: g1.original, g1text, dom: g1.dom, visible: g1.visible, url: setup.url })
  await shot('31-global-watcher-missing')
  chrome.kill()
  console.log('\n---- 0 PASS / 0 FAIL / 1 SKIP（探针无效，退出码 2）----')
  process.exit(2)
}

// 自证：探针手里的 state **就是**驱动浮层的那个（渲染出的原文与它一致）
// ★ 必须带 `!!g1.original` —— 否则两份实例都返回空串时 `'' === ''` 会假绿
check('G1b', '★自检：探针读的 state 就是驱动浮层的那个（DOM 原文 === state.original，非空）',
  !!g1.original && g1.src === g1.original,
  { domSrc: g1.src, stateOriginal: g1.original, textMatch: g1.src === g1text })

// ===========================================================================
// G2 —— 核心：input 里真实拖选（左边缘 → 右边缘）
// ===========================================================================
await hideLayer()
await resetField('#r366c-input')
const rIn = await rectOf('#r366c-input')
await dragIn('#r366c-input', 3, rIn.width - 3, 0.5, 14)
const g2shown = await waitFor(`!!document.querySelector('.stl-layer')`, 4000, 120)
const g2 = await readLayer()
const s2 = await selOf('#r366c-input')

check('G2a', '★★ 输入框里真实拖选 ⇒ 浮层出现（上一轮「整条短路」的症状是**什么都不弹**）',
  g2shown && g2.dom && g2.visible === true, { g2shown, dom: g2.dom, visible: g2.visible })
check('G2b', '★自检：拖选真的产生了选区（不是「点了两下 0 长度选区」而空跑）',
  typeof s2.start === 'number' && (s2.end - s2.start) >= 10
  && s2.start <= 1 && s2.end >= s2.value.length - 1,
  { start: s2.start, end: s2.end, len: s2.value.length })
check('G2c', '★★ 原文 === 控件里真正选中的文字（`value.slice(selectionStart, selectionEnd)`）',
  !!g2.original && g2.original === s2.text && s2.text === s2.value.slice(s2.start, s2.end),
  { original: g2.original, selected: s2.text })
check('G2d', '★★ 锚点落在控件矩形内（伪 range 恒 0×0 ⇒ 走旧路必然落在 (0,0)）',
  inRect(g2.anchor, rIn), { anchor: g2.anchor, rect: { top: rIn.top, left: rIn.left, right: rIn.right, bottom: rIn.bottom } })
await shot('32-input-selection')

// ===========================================================================
// G3 —— 局部拖选：证明「原文跟着真实选区走」，而不是碰巧等于整个 value
// ===========================================================================
await hideLayer()
await resetField('#r366c-input')
await dragIn('#r366c-input', Math.round(rIn.width * 0.45), rIn.width - 3, 0.5, 14)
const g3shown = await waitFor(`!!document.querySelector('.stl-layer')`, 4000, 120)
const g3 = await readLayer()
const s3 = await selOf('#r366c-input')
check('G3', '★局部拖选（中段 → 右边缘）⇒ 原文 === 那一段（不是整个 value，也不串位）',
  g3shown && s3.start > 0 && s3.end > s3.start && g3.original === s3.text && !!s3.text,
  { start: s3.start, end: s3.end, original: g3.original, selected: s3.text })

// ===========================================================================
// G4 —— 「划词只见闪一下」的回归：焦点在控件里时，selectionchange 不许把浮层收掉
//        这条正是 `onSelectionChange` 里那个 `document.activeElement` 分流守护的现场。
// ===========================================================================
check('G4a', '★自检：此时焦点确实在控件里（守卫的前提条件成立）', s3.focused === true, { focused: s3.focused })

// (a) 拖完静置：浏览器补发的 selectionchange 不许把它收掉
await sleep(1500)
const g4stillDom = await run(`!!document.querySelector('.stl-layer')`)
const g4still = await readLayer()
check('G4b', '★★ 拖选后静置 1.5s 浮层仍在（真实现场：控件内选区会触发连环 selectionchange）',
  g4stillDom === true && g4still.visible === true, { dom: g4stillDom, visible: g4still.visible })
await shot('33-after-settle')

// (b) 直接派发一次 selectionchange（确定性：不依赖浏览器是否补发）
await run(`document.dispatchEvent(new Event('selectionchange')), true`)
await sleep(250)
const g4syn = await readLayer()
check('G4c', '★★ 焦点在控件里时派发 selectionchange ⇒ 浮层**仍不被收**（否则症状就是「闪一下」）',
  g4syn.dom === true && g4syn.visible === true, { dom: g4syn.dom, visible: g4syn.visible, focused: (await selOf('#r366c-input')).focused })

// (c) 反控：焦点移出控件 + 清空正文选区 ⇒ 同一个事件必须**真的**能收起浮层
//     （不然 G4c 是「事件根本没到处理器」造成的假绿）
await run(`document.querySelector('#r366c-input').blur(); window.getSelection().removeAllRanges(); true`)
await run(`document.dispatchEvent(new Event('selectionchange')), true`)
await sleep(300)
const g4ctl = await readLayer()
check('G4d', '★反控：焦点不在控件里且正文无选区 ⇒ 同一事件确实收起浮层（证明 G4c 不是空跑）',
  g4ctl.dom === false && g4ctl.visible === false, { dom: g4ctl.dom, visible: g4ctl.visible })

// ===========================================================================
// G5 —— textarea：多行控件，拖第一行
// ===========================================================================
await hideLayer()
await resetField('#r366c-area')
const rAr = await rectOf('#r366c-area')
await dragIn('#r366c-area', 3, 300, 0.28, 14)
const g5shown = await waitFor(`!!document.querySelector('.stl-layer')`, 4000, 120)
const g5 = await readLayer()
const s5 = await selOf('#r366c-area')
check('G5', '★★ textarea 第一行真实拖选 ⇒ 浮层出现，原文 === 选中文字，锚点在控件内',
  g5shown && g5.original === s5.text && !!s5.text && (s5.end - s5.start) >= 8 && inRect(g5.anchor, rAr),
  { original: g5.original, selected: s5.text, anchor: g5.anchor })
await shot('34-textarea-selection')

// ===========================================================================
// G6 —— password：**必须不弹**的那一栏（唯一显式排除的 input 类型）
//        关键：这里要能证明「它**本来**有选区」——否则「不弹」是空跑。
// ===========================================================================
await hideLayer()
await resetField('#r366c-pwd')
const rPw = await rectOf('#r366c-pwd')
await dragIn('#r366c-pwd', 3, rPw.width - 3, 0.5, 14)
await sleep(600)
const g6 = await readLayer()
const s6 = await selOf('#r366c-pwd')
const util6 = await run(`window.__r366c.readField('#r366c-pwd') === null`)
check('G6a', '★自检：密码框里**确实**拖出了选区（否则 G6 是空跑）',
  typeof s6.start === 'number' && s6.end > s6.start, { start: s6.start, end: s6.end, len: (s6.value || '').length })
check('G6b', '★★ 唯一真源判定：readFieldSelection(密码框) === null',
  util6 === true, { utilNull: util6 })
check('G6c', '★★ 密码框里拖选 ⇒ **不弹浮层**（密码原文绝不许送第三方翻译）',
  g6.dom === false && g6.visible === false, { dom: g6.dom, visible: g6.visible })
await shot('35-password-no-layer')

// ===========================================================================
// G7 —— 不支持选区的类型（number）：运行期判据放行的反面
// ===========================================================================
await hideLayer()
await resetField('#r366c-num')
const rNum = await rectOf('#r366c-num')
await dragIn('#r366c-num', 3, rNum.width - 3, 0.5, 12)
await sleep(600)
const g7 = await readLayer()
const s7 = await selOf('#r366c-num')
const util7 = await run(`window.__r366c.readField('#r366c-num') === null`)
check('G7a', '★自检：number 框的 selectionStart 是 null（浏览器就不给选区）',
  s7.start === null && s7.end === null, { start: s7.start, end: s7.end })
check('G7b', '★★ number 框拖选 ⇒ 不弹浮层（运行期判据 `typeof selectionStart !== number` 生效）',
  util7 === true && g7.dom === false && g7.visible === false, { utilNull: util7, dom: g7.dom, visible: g7.visible })

// ===========================================================================
// G8 —— 「别打扰打字」：浮层开着时按下可见字符 ⇒ 立即让路
// ===========================================================================
await hideLayer()
await resetField('#r366c-type')
const rTy = await rectOf('#r366c-type')
await dragIn('#r366c-type', 3, rTy.width - 3, 0.5, 14)
const g8shown = await waitFor(`!!document.querySelector('.stl-layer')`, 4000, 120)
check('G8a', '★自检：先让浮层真的开出来（否则「打字收起」无从谈起）', g8shown === true, { g8shown })

await keyStroke('x', 'KeyX', 88)
const g8gone = await waitFor(`!document.querySelector('.stl-layer')`, 3000, 100)
const g8 = await readLayer()
check('G8b', '★★ 打字即收：按下一个可见字符 ⇒ 浮层让路（不挡住正在编辑的输入框）',
  g8gone === true && g8.dom === false && g8.visible === false, { gone: g8gone, visible: g8.visible })
await shot('36-typing-dismiss')

// ===========================================================================
// G9 —— 真实错误：只认「提到本链路」的异常（无关噪音不背锅）
// ===========================================================================
const ownErrs = events
  .filter((m) => m.method === 'Runtime.exceptionThrown')
  .map((m) => {
    const d = m.params && m.params.exceptionDetails
    return (d && (d.exception && d.exception.description)) || (d && d.text) || ''
  })
  .filter((t) => /textSelection|useSelectionTranslate|stl-layer/.test(String(t)))
check('G9', '★无本链路相关的未捕获异常（过滤到 textSelection / useSelectionTranslate / stl-layer）',
  ownErrs.length === 0, { ownErrs: ownErrs.map((t) => String(t).slice(0, 200)) })

const pass = results.filter((r) => r.state === 'PASS').length
const fail = results.filter((r) => r.state === 'FAIL').length
const skip = results.filter((r) => r.state === 'SKIP').length
console.log(`\n---- ${pass} PASS / ${fail} FAIL / ${skip} SKIP ----`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(fail === 0 ? 0 : 1)

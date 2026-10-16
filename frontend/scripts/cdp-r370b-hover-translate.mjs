// CDP 真机探针（第 370 轮 P1）—— **悬停翻译 + 双语/仅译文切换**。
//
// 为什么这一段必须真机跑（单测与 AST 门禁**结构上**覆盖不到）：
//   1. 单测跑在 `environment: 'node'`（本项目**不装 jsdom**）。
//      `hoverTranslate.test.ts` 能钉住 `decideHover` 的 7 条判定，
//      `selectionTranslate.test.ts` 能钉住「监听器接没接上」和「定时器先清后起」，
//      但它们**都证明不了**「真实鼠标停在真文本块上 350ms，浏览器的 `mouseover`
//      真的到了那个 handler」——单测里的 `mouseover` 是手搓 `document` 桩派发的。
//   2. `check-hover-translate.cjs` 是 **AST 形态门禁** —— 它只能证明
//      「源码里那条通道是可达的」（`decisionGuardsReturn` / `signalIsLive`），
//      证明不了「真机几何算对了、浮层真的没遮住被悬停的那块文字」。
//   3. 本探针的输入是 **CDP 真实鼠标**（`Input.dispatchMouseEvent: mouseMoved`），
//      不是 `dispatchEvent(new MouseEvent('mouseover'))` —— 后者会把
//      「浏览器到底把指针下的哪个元素当 target」这一步整个跳过，而那正是
//      `nearestTextBlock` 的输入（指针落在子元素 vs 落在块上，结论不同）。
//
// 被测对象是**真代码**：真 dev server 上的真 Workspace（`GlobalTranslateLayers`
// 里挂着真的 `SelectionTranslateLayer` ⇒ 真的全局 `startSelectionWatcher()`）。
// 探针往页面里插的原生 `<p>` / `<input>` / `contenteditable` 不是「行为等价的本地拷贝」，
// 全局监听是 document 级的，插进去照样生效。
//
// ★★ 唯一被打桩的是**网络边界**（LLM）：`Fetch.enable` 拦
//    `POST /api/v1/aigc/content/translate-selection`，回一个确定性的信封。
//    为什么只桩这一层：探针要验的是**前端**（悬停触发、浮层渲染、显示方式切换），
//    不是 DashScope 的时延与产出。真调模型会让本探针**不可复现**（时延 / 降级 /
//    上游抖动都会改读数），却对上面三条判据没有任何增量。注意被打桩的**不是**
//    `translateSelection` 这个函数 —— 请求、axios 拦截器、`resolveTranslateOutcome`
//    四态判定、`state` 赋值、渲染，整条链路全是真的，桩只吃掉了「远端那把模型」。
//    桩体回显请求体里的 `text`，于是「悬停读到的文本 → 请求体 → 响应 → DOM」
//    这条链能被逐环对账（V3）。
//
// 判据口径（沿用本仓纪律）：
//   · 每条「不许弹」都配**反控**（同一元素 / 同一坐标，只翻一个属性，必须能弹）——
//     否则「纯中文不弹」可能其实是被 `no-block` 挡掉的**归因错方向**（见 E2/E3、E6/E7、E8/E9）；
//   · 读数同时取「渲染出的 DOM」与「模块单例里的 state」，并自证两者一致（V5）；
//   · 计时判据是**两侧**的：150ms 不许弹（不早弹）、停满阈值必须弹（真的到点了）；
//   · 探针自身失效（工作台没起来 / 全局监听没装 / 拿到了另一份模块实例）⇒ 退出码 **2**，
//     不并进 PASS/FAIL。
//
// ★★ 三个已知的**假红**陷阱（前两个抄自 `cdp-r366c-textfield-selection.mjs`，血泪）：
//   ① **`import('/src/composables/useSelectionTranslate.ts')` 会拿到另一份模块实例。**
//      应用实际请求的 URL 带 Vite 的 HMR 后缀 `?t=<ts>`（该文件被改过就有）；
//      裸路径是新实例 ⇒ 行为完全等价、对象身份不同。症状极具误导性：浮层 DOM 明明弹了，
//      探针读到的 `state.original` 却是空、`visible` 是 false，看起来像「全局监听没装」。
//      ⇒ 必须从 `performance.getEntriesByType('resource')` 捞**浏览器真正请求过的那条 URL**。
//   ② **页面上若已有非空选区，悬停会被 `has-selection` 挡掉。** 这是**产品设计**
//      （用户已经用划词拿到浮层了，悬停再弹一次只会打架），不是缺陷。所以每次悬停前
//      必须把选区复位成空 —— 而且本探针**刻意不做任何拖选**，全程只用悬停，
//      免得自己给自己造出 `has-selection`。
//   ③ **`mouseover` 只有指针**真的换了目标**才会派发。** 指针已经在目标上再 `mouseMoved`
//      到同一点，浏览器不会重发 ⇒ 计时器不会起。所以每次悬停前先 `moveAway()`，
//      并配 `hoverHits` 计数自检（S4）证明 CDP 的鼠标移动确实产生了 `mouseover`。
//
// 用法：node scripts/cdp-r370b-hover-translate.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/，需 dev server 在跑）
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9410
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r370')

/** 悬停阈值（与 `utils/hoverTranslate.ts` 的 `HOVER_DELAY_MS` 同值；探针里再对一次账，见 S5） */
const DELAY = 350

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r370b-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--remote-allow-origins=*`,
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
/** LLM 桩的命中次数（V3 / V6 用它判「有没有发第二次请求」） */
const stubHit = { n: 0, lastText: '', lastReq: '' }
/** 桩返回的译文的固定前缀 —— 断言里靠它认「DOM 里那段就是桩给的」 */
const STUB_TAG = 'HOVER-STUB:'

ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }

  // ★★ 网络边界打桩：只吃 LLM，不吃前端链路（理由见文件头）
  if (m.method === 'Fetch.requestPaused') {
    const { requestId, request } = m.params
    if (!/translate-selection/.test(request.url)) {
      send('Fetch.continueRequest', { requestId })
      return
    }
    let echo = ''
    try { echo = String(JSON.parse(request.postData || '{}').text || '') } catch { /* 非 JSON 就回显空 */ }
    stubHit.n++
    stubHit.lastText = echo
    stubHit.lastReq = request.url
    const envelope = {
      success: true,
      response: {
        original_text: echo,
        translation: `${STUB_TAG}${echo.slice(0, 40)}`,
        source_lang: 'en',
        target_lang: 'zh',
        degraded: false,
        same_lang: false,
      },
    }
    const body = Buffer.from(JSON.stringify(envelope), 'utf8').toString('base64')
    send('Fetch.fulfillRequest', {
      requestId,
      responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json; charset=utf-8' }],
      body,
    })
    return
  }
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
const waitFor = async (expr, ms = 25000, step = 120) => {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await run(expr)) return true } catch { /* 渲染中途 */ }
    await sleep(step)
  }
  return false
}

// ---------------------------------------------------------------------------
// 真实鼠标（CDP Input 域）。★ 这是本探针的**全部价值**：不用 dispatchEvent 造事件。
// ---------------------------------------------------------------------------
const moveTo = (x, y) => send('Input.dispatchMouseEvent', {
  type: 'mouseMoved', x, y, button: 'none', buttons: 0,
})
const clickAt = async (x, y) => {
  await moveTo(x, y)
  await sleep(60)
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1 })
  await sleep(50)
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1 })
}

const rectOf = async (sel) => JSON.parse(await run(
  `(() => {
     const e = document.querySelector(${JSON.stringify(sel)})
     if (!e) return 'null'
     const r = e.getBoundingClientRect()
     return JSON.stringify({ top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height })
   })()`,
) || 'null')

/** 元素中心点（略偏左，避开右侧可能的控件） */
const pointOf = async (sel) => {
  const r = await rectOf(sel)
  if (!r) throw new Error(`元素不存在：${sel}`)
  return { x: Math.round(r.left + Math.min(40, Math.max(8, r.width * 0.25))), y: Math.round(r.top + r.height / 2), r }
}

/** 指针下的元素自检 —— 「浮层没弹」到底是没触发，还是指针被别的东西挡住了 */
const underAt = async (x, y) => run(`(() => {
  const e = document.elementFromPoint(${x}, ${y})
  return e ? (e.id || (e.tagName + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : ''))) : 'null'
})()`)

/** 把选区复位成空（`has-selection` 是产品设计的拦截，别自己造出来，见文件头 ②） */
const resetSelection = () => run(`(() => {
  try { const ae = document.activeElement; if (ae && ae.blur) ae.blur() } catch (e) {}
  const s = window.getSelection(); if (s && s.removeAllRanges) s.removeAllRanges()
  return true
})()`)

/** 同时读「渲染出的 DOM」与「模块单例 state」——两者必须一致，否则探针看的是另一个对象 */
const readLayer = async () => JSON.parse(await run(`(() => {
  const el = document.querySelector('.stl-layer')
  const st = window.__r370.state
  const btns = el ? Array.from(el.querySelectorAll('.stl-btn')).map((b) => b.textContent.trim()) : []
  const modeBtn = el ? Array.from(el.querySelectorAll('.stl-btn')).find((b) => b.textContent.trim() === '仅译文' || b.textContent.trim() === '双语') : null
  const src = el ? el.querySelector('.stl-src') : null
  const sep = el ? el.querySelector('.stl-sep') : null
  const dst = el ? el.querySelector('.stl-dst') : null
  const r = el ? el.getBoundingClientRect() : null
  return JSON.stringify({
    dom: !!el,
    hasSrc: !!src,
    src: src ? src.textContent.trim() : null,
    hasSep: !!sep,
    dst: dst ? dst.textContent.trim() : null,
    btns,
    modeBtnText: modeBtn ? modeBtn.textContent.trim() : null,
    rect: r ? { top: r.top, left: r.left, bottom: r.bottom, right: r.right, width: r.width, height: r.height } : null,
    visible: !!st.visible,
    original: st.original,
    translation: st.translation,
    loading: !!st.loading,
    error: st.error || '',
    displayMode: window.__r370.api.displayMode.value,
    anchor: st.anchor ? { top: st.anchor.top, bottom: st.anchor.bottom, left: st.anchor.left, width: st.anchor.width } : null,
  })
})()`) || '{}')

const hideLayer = () => run('window.__r370.api.hide(), true')

/** 真实鼠标：先移开（换目标）再移到目标元素上。`hold` 是移上去之后静置的毫秒数。 */
const hoverAt = async (sel, hold = 0) => {
  const p = await pointOf(sel)
  await moveTo(p.x, p.y)
  if (hold) await sleep(hold)
  return p
}
/** 移到「不是文本块」的空隙上（用来制造 mouseout，同时不启动新的计时器） */
const moveAway = async () => {
  const p = await pointOf('#r370-away')
  await moveTo(p.x, p.y)
  await sleep(80)
  return p
}
/** 收起浮层 + 复位选区 + 把指针移开：每个用例开跑前的统一前置 */
const arming = async () => {
  await hideLayer()
  await resetSelection()
  await moveAway()
  await sleep(120)
}

const inViewport = (r) => !!r && r.top >= 0 && r.left >= 0 && r.bottom <= 900 + 1 && r.right <= 1680 + 1
/** 浮层与被悬停的块**不重叠**（上或下）—— 遮住光标会把 `mouseover` 抖成一串 */
const clearOf = (layer, block) => !!layer && !!block
  && (layer.bottom <= block.top + 2 || layer.top >= block.bottom - 2)
/**
 * 复刻 `SelectionTranslateLayer.reposition()` 的**纵向规则**（`gap = 8`）。
 *
 * ★ 为什么要在探针侧再算一遍期望值，而不是断言「top 变大 / 变小」：
 *   那个方向**不是**产品契约 —— 实测（本探针第一次跑）双语态 h≈128 时 91-128-8 < 8
 *   ⇒ 落到块**下方**（top=121）；切成仅译文 h≈73 时 91-73-8 = 10 ≥ 8
 *   ⇒ 翻到块**上方**（top=10）。方向反了但**完全正确**：规则本来就是
 *   「优先上方，上方不够落下方」。真正的契约是「位置由**当下量到的**高度算出」，
 *   所以判据要比对**公式**，并且要能区分「按新高度算的」与「沿用旧高度的陈旧值」。
 */
const expectTop = (anchor, h, vh = 900) => {
  const gap = 8
  let top = anchor.top - h - gap
  if (top < 8) top = anchor.bottom + gap
  if (top + h > vh - 8) top = Math.max(8, vh - h - 8)
  return Math.round(top)
}

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
await send('Fetch.enable', { patterns: [{ urlPattern: '*translate-selection*', requestStage: 'Request' }] })
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
// 插入测试用真元素。
// ★ 每块都是**原生**元素，且刻意造成「悬停它应该弹 / 不应该弹」两组的**同形对照**：
//   · 纯中文块 与 同一块换成英文  —— 只差文本内容；
//   · 输入框   与 同一容器里的标签文字 —— 只差「指针落在控件上还是标签上」；
//   · contenteditable 块 与 同一个元素去掉该属性 —— 只差一个属性。
//   有了这三对，每条负例的归因才是唯一的（否则「不弹」可能是被 no-block 挡的）。
// ===========================================================================
const setupRes = await run(`
(async () => {
  try {
    // ★★ 见文件头 ①：必须按浏览器**实际请求过**的 URL 取模块，否则是另一份实例。
    const pick = (frag) => {
      const hit = performance.getEntriesByType('resource')
        .map((e) => e.name)
        .filter((n) => n.indexOf(frag) >= 0)
      return hit.length ? hit[hit.length - 1] : frag
    }
    const url = pick('/src/composables/useSelectionTranslate.ts')
    const hoverUrl = pick('/src/utils/hoverTranslate.ts')
    const mod = await import(url)
    const hover = await import(hoverUrl)
    const api = mod.useSelectionTranslate()

    const host = document.createElement('div')
    host.id = 'r370-host'
    host.style.cssText = 'position:fixed;left:140px;top:80px;width:720px;z-index:900;'
      + 'background:#ffffff;border:1px solid #d9d9d9;border-radius:6px;padding:10px;'
      + 'box-sizing:border-box;font-family:system-ui;color:#222;user-select:text'
    host.innerHTML =
        '<p id="r370-en" style="margin:0 0 8px;font-size:15px;line-height:22px">Whisper-Quiet Ultrasonic Humidifier with 30dB Noise Level for Bedroom Use</p>'
      + '<p id="r370-zh" style="margin:0 0 8px;font-size:15px;line-height:22px">静音超声波加湿器，适合卧室使用的低噪音设计</p>'
      + '<p id="r370-mix" style="margin:0 0 8px;font-size:15px;line-height:22px">Noise Cancelling 主动降噪无线耳机 with 40H Playtime</p>'
      + '<p id="r370-long" style="margin:0 0 8px;font-size:15px;line-height:22px"></p>'
      + '<div id="r370-iwrap" style="margin:0 0 8px;padding:4px 0">'
      +   '<span id="r370-ilabel" style="font-size:15px;line-height:22px">Search products by keyword</span>'
      +   '<input id="r370-input" style="display:block;width:600px;height:32px;font-size:14px;font-family:system-ui;padding:4px 8px;box-sizing:border-box" value="Noise Cancelling Wireless Earbuds with 40H Playtime">'
      + '</div>'
      + '<div id="r370-ce" contenteditable="true" style="margin:0 0 8px;font-size:15px;line-height:22px;border:1px dashed #bbb;padding:2px 4px">Wireless Charging Pad with Anti-Slip Base</div>'
      + '<div id="r370-away" style="height:26px"></div>'
    document.body.appendChild(host)

    // 超上限块：240 字符（上限 200）—— 「不弹」必须归因于 too-long，长度得自证，不能手写
    const longText = ('Ergonomic Adjustable Laptop Stand with Aluminum Alloy Body and Cooling Ventilation Design ')
      .repeat(3).trim()
    document.getElementById('r370-long').textContent = longText

    // 悬停命中计数：证明 CDP 的 mouseMoved **真的**产生了浏览器 mouseover（见文件头 ③）
    window.__r370 = { api, mod, hover, url, hoverUrl, hoverHits: 0, longLen: longText.length, state: api.state }
    document.getElementById('r370-en').addEventListener('mouseover', () => { window.__r370.hoverHits++ })

    // 悬停必须**显式打开**（缺省关是产品设计，见 readHoverEnabled）
    api.setAutoEnabled(false)      // 本探针不做任何拖选，关掉它以免干扰
    api.setHoverEnabled(true)
    api.setDisplayMode('bilingual')  // 确定起点
    // ★ 把落盘抹掉，让后面的 D5 能证明「是那一次点击写的」，而不是起点就是它
    try { localStorage.removeItem('selection_translate_display') } catch (e) {}

    return JSON.stringify({
      ok: true, url, hoverUrl,
      hasApi: typeof api.setHoverEnabled === 'function' && typeof api.hide === 'function',
      hoverEnabled: api.hoverEnabled.value,
      delay: hover.HOVER_DELAY_MS,
      max: hover.MAX_HOVER_CHARS,
      longLen: longText.length,
      displayKey: (() => { try { return localStorage.getItem('selection_translate_display') } catch (e) { return 'ERR' } })(),
    })
  } catch (e) {
    return JSON.stringify({ ok: false, err: String(e && e.stack || e).slice(0, 800) })
  }
})()`)

const setup = JSON.parse(setupRes || '{}')
if (!setup.ok) {
  console.log(`\nPROBE-ERR  导入真模块 / 挂载测试块失败，探针自身无效：\n${setup.err}\n`)
  check('S1', '★自检：真 useSelectionTranslate / hoverTranslate 已导入', null, setup.err)
  chrome.kill()
  console.log('\n---- 0 PASS / 0 FAIL / 1 SKIP（探针无效，退出码 2）----')
  process.exit(2)
}
check('S1', '★自检：真 useSelectionTranslate / hoverTranslate 已导入，且 setHoverEnabled / hide 可用',
  setup.hasApi === true, { hasApi: setup.hasApi })
// ★ 身份自检：必须是应用**正在用的那一份**（含 HMR 后缀，见文件头 ①）
check('S1b', '★自检：按浏览器实际请求的 URL 取模块（否则是另一份实例、行为等价但身份不同）',
  !!setup.url, { url: setup.url, hoverUrl: setup.hoverUrl })
console.log(`      · 模块实际 URL：${setup.url}`)
console.log(`      · 悬停参数实测：HOVER_DELAY_MS=${setup.delay}  MAX_HOVER_CHARS=${setup.max}  超限块长度=${setup.longLen}`)
check('S2', '★自检：悬停开关已显式打开、无选区（两个前提缺一，后面全是空跑）',
  setup.hoverEnabled === true, { hoverEnabled: setup.hoverEnabled })
check('S3', '★自检：显示方式的落盘此刻是空的（后面 D5 才能证明是「那一次点击」写的）',
  setup.displayKey === null, { displayKey: setup.displayKey })
// 探针侧的阈值副本与真源码对账（写死数字漂移会静默改口径）
check('S5', '★自检：探针里的等待阈值与真源码 HOVER_DELAY_MS 同值',
  setup.delay === DELAY, { src: setup.delay, probe: DELAY })

// 指针自检：每个被测元素都真的在指针下（否则「没弹」的归因会指错方向）
const PTS = ['#r370-en', '#r370-zh', '#r370-mix', '#r370-long', '#r370-input', '#r370-ilabel', '#r370-ce', '#r370-away']
const under = {}
for (const sel of PTS) {
  const p = await pointOf(sel)
  under[sel] = { at: await underAt(p.x, p.y), y: p.y }
}
check('S4', '★自检：八个被测点都真的在指针下（没被任何浮层/遮罩盖住）',
  Object.entries(under).every(([sel, v]) => v.at === sel.slice(1)), under)
await shot('10-host-mounted')

// ===========================================================================
// V —— 悬停核心：计时器是**两侧**的（不早弹 + 停满必弹），且译文真的来自网络桩
// ===========================================================================
await arming()
const before = stubHit.n
const vPt = await hoverAt('#r370-en')          // ★ 只移上去，不等待
await sleep(150)
const vEarly = await readLayer()
check('V1', `★★ 移上去只停 150ms（< ${DELAY}）⇒ **不弹**（早了就是「鼠标横扫全页乱弹」）`,
  vEarly.dom === false && vEarly.visible === false, { dom: vEarly.dom, visible: vEarly.visible })

await sleep(700)                                // 累计 850ms，远超阈值
const vShown = await waitFor(`!!document.querySelector('.stl-layer')`, 3000, 100)
const v = await readLayer()
const vExpect = await run(`document.getElementById('r370-en').textContent.replace(/\\s+/g, ' ').trim()`)
check('V2', `★★ 原地停满阈值（累计 ≈850ms）⇒ 浮层出现，原文 === 该块的归一化文本`,
  vShown === true && v.dom === true && v.visible === true && !!v.original && v.original === vExpect,
  { dom: v.dom, visible: v.visible, original: v.original, expect: vExpect })
// 自证：探针手里的 state **就是**驱动浮层的那个（否则是另一份实例，见文件头 ①）
check('V2b', '★自检：探针读的 state 就是驱动浮层的那个（DOM 原文 === state.original 且非空）',
  !!v.original && v.src === v.original, { domSrc: v.src, stateOriginal: v.original })
check('V3', '★★ 网络桩被命中，且浮层里的译文**就是桩返回的那串**（悬停文本 → 请求体 → 响应 → DOM 环环对账）',
  stubHit.n === before + 1 && stubHit.lastText === vExpect
  && typeof v.dst === 'string' && v.dst.indexOf(STUB_TAG) === 0 && v.translation === v.dst,
  { before, now: stubHit.n, reqText: stubHit.lastText, expect: vExpect, dst: v.dst, stateTranslation: v.translation })
check('V4', '★★ 浮层落在被悬停块的**上或下**，不遮住光标下的文字（遮住会把 mouseover 抖成一串）',
  inViewport(v.rect) && clearOf(v.rect, vPt.r), { layer: v.rect, block: { top: vPt.r.top, bottom: vPt.r.bottom } })
await shot('11-hover-shown')

// V6 —— 同文本不重弹（H6 门禁的真机对应）：移开再移回，**不许**发第二次请求
const beforeDedup = stubHit.n
await moveAway()
await hoverAt('#r370-en', 700)
const vDedup = await readLayer()
check('V6', '★★ 移开再移回同一块 ⇒ 浮层仍在、原文不变，且**没有**发第二次请求（同文本去重）',
  vDedup.dom === true && vDedup.original === vExpect && stubHit.n === beforeDedup,
  { before: beforeDedup, now: stubHit.n, original: vDedup.original })

// ===========================================================================
// D —— 双语 / 仅译文切换（复用上面那个已经弹出来的浮层）
// ===========================================================================
check('D1', '★自检：此时有译文 ⇒ 「仅译文」切换按钮出现（它 `v-if="state.translation"`）',
  !!vDedup.translation && vDedup.modeBtnText === '仅译文', { modeBtnText: vDedup.modeBtnText, btns: vDedup.btns })
check('D2', '★★ 双语态：原文区与分隔线都在，原文 === 被悬停的块文本',
  vDedup.hasSrc === true && vDedup.hasSep === true && vDedup.src === vExpect,
  { hasSrc: vDedup.hasSrc, hasSep: vDedup.hasSep, src: vDedup.src })
await shot('12-bilingual')

/** 取「显示方式」按钮的视口中心（按文案认，不按位置 —— 按钮顺序变了也不影响） */
const modeBtnPoint = async () => JSON.parse(await run(`(() => {
  const b = Array.from(document.querySelectorAll('.stl-layer .stl-btn'))
    .find((x) => x.textContent.trim() === '仅译文' || x.textContent.trim() === '双语')
  if (!b) return 'null'
  const r = b.getBoundingClientRect()
  return JSON.stringify({ x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), text: b.textContent.trim() })
})()`) || 'null')

const bp = await modeBtnPoint()
check('D2b', '★自检：找得到那颗切换按钮，且它的中心点在指针下（真点击的前提）',
  !!bp && (await underAt(bp.x, bp.y)) !== 'null', bp)
await clickAt(bp.x, bp.y)
await sleep(320)
const d3 = await readLayer()
check('D3', '★★ 真实鼠标点击切换 ⇒ 模式变 target，原文区与分隔线**双双**消失，译文一字不改',
  d3.displayMode === 'target' && d3.hasSrc === false && d3.hasSep === false
  && !!vDedup.translation && d3.translation === vDedup.translation,
  { displayMode: d3.displayMode, hasSrc: d3.hasSrc, hasSep: d3.hasSep, before: vDedup.translation, after: d3.translation })
check('D4', '★ 按钮文案跟着翻面（「仅译文」⇒「双语」，否则用户无从回到双语）',
  d3.modeBtnText === '双语', { modeBtnText: d3.modeBtnText, btns: d3.btns })
const d5key = await run(`(() => { try { return localStorage.getItem('selection_translate_display') } catch (e) { return 'ERR' } })()`)
check('D5', '★★ 切换落本机（localStorage）—— 且**只有**走 setter 才会写（起点是 null，见 S3）',
  d5key === 'target', { key: d5key })
const d6Anchor = vDedup.anchor
const d6HOld = vDedup.rect && Math.round(vDedup.rect.height)
const d6HNew = d3.rect && Math.round(d3.rect.height)
const d6ExpNow = d6Anchor && expectTop(d6Anchor, d6HNew)
const d6Stale = d6Anchor && expectTop(d6Anchor, d6HOld)
check('D6', '★★ 切换后浮层**重定位**：位置由**新量到的**高度算出（且与「沿用旧高度」的陈旧值不同 —— 否则这条判据没牙齿）',
  !!d3.rect && !!vDedup.rect && d3.rect.height < vDedup.rect.height
  && Math.abs(d3.rect.top - d6ExpNow) <= 1 && d3.rect.top !== d6Stale,
  { hOld: d6HOld, hNew: d6HNew, topActual: d3.rect && d3.rect.top,
    topExpectNow: d6ExpNow, topStale: d6Stale, anchor: d6Anchor })
// 「不遮住块」在**新高度**下仍要成立（重定位不能把浮层推到块上）
check('D6b', '★ 新高度下仍不遮住被悬停的块', clearOf(d3.rect, vPt.r), { layer: d3.rect, block: { top: vPt.r.top, bottom: vPt.r.bottom } })
await shot('13-target-only')

const bp2 = await modeBtnPoint()
await clickAt(bp2.x, bp2.y)
await sleep(320)
const d7 = await readLayer()
const d7key = await run(`(() => { try { return localStorage.getItem('selection_translate_display') } catch (e) { return 'ERR' } })()`)
check('D7', '★★ 再点一次 ⇒ 回到双语，原文区回来，落盘回到 bilingual（切回去的路走得通）',
  d7.displayMode === 'bilingual' && d7.hasSrc === true && d7.hasSep === true && d7.src === vExpect && d7key === 'bilingual',
  { displayMode: d7.displayMode, hasSrc: d7.hasSrc, key: d7key })

// ===========================================================================
// E —— 三条**结构性排除**与两条**文本判据**：每组都配反控
// ===========================================================================
// E1：空隙点不弹 —— 这条同时是「我们造的 mouseout 不启动计时器」的自检
await arming()
const beforeE1 = stubHit.n
await hoverAt('#r370-away', 900)
const e1 = await readLayer()
check('E1', '★自检：停在空隙块上 ⇒ 不弹、也不发请求（后面的负例都靠「移到这里」来取消待触发）',
  e1.dom === false && stubHit.n === beforeE1, { dom: e1.dom, requests: stubHit.n - beforeE1 })
await shot('14-away')

// E2 / E3：纯中文不弹，**同一元素**换成英文必须弹（否则 E2 是被 no-block 挡的）
await arming()
const zhText = await run(`document.getElementById('r370-zh').textContent.trim()`)
const beforeE2 = stubHit.n        // ★ 必须在悬停**之前**取快照，否则 `n === n` 恒真 = 空跑
await hoverAt('#r370-zh', 900)
const e2 = await readLayer()
check('E2', '★★ 纯中文块（无拉丁字母）⇒ 不弹、也不发请求（悬停是「猜你想看」，猜错就是无提示的打扰）',
  e2.dom === false && stubHit.n === beforeE2, { dom: e2.dom, requests: stubHit.n - beforeE2, text: zhText })

await arming()
await run(`document.getElementById('r370-zh').textContent = 'Ultrasonic Humidifier for Bedroom with Quiet Design'`)
await hoverAt('#r370-zh', 900)
const e3 = await readLayer()
check('E3', '★★ 反控：**同一个元素**只把文字换成英文 ⇒ 弹（证明 E2 归因于 no-latin，而不是 no-block）',
  e3.dom === true && e3.original === 'Ultrasonic Humidifier for Bedroom with Quiet Design',
  { dom: e3.dom, original: e3.original })
await run(`document.getElementById('r370-zh').textContent = ${JSON.stringify(zhText)}`)

// E4：中英混排必须弹（刻意**不加**「不得含 CJK」第二道判据 —— 那道会误杀真实商品标题）
await arming()
await hoverAt('#r370-mix', 900)
const e4 = await readLayer()
check('E4', '★★ 中英混排（`Noise Cancelling 主动降噪…`）⇒ 弹（刻意不加 CJK 第二道，混排正是最该翻的样本）',
  e4.dom === true && !!e4.original && /[A-Za-z]/.test(e4.original) && /[\\u4e00-\\u9fff]/.test(e4.original),
  { dom: e4.dom, original: e4.original })

// E5：超 200 字不弹（长度自证，不手写）
await arming()
const beforeE5 = stubHit.n
const longLen = await run(`document.getElementById('r370-long').textContent.trim().length`)
await hoverAt('#r370-long', 900)
const e5 = await readLayer()
check('E5', `★★ 超上限块（实测 ${longLen} 字 > ${setup.max}）⇒ 不弹、也不发请求（上限小到「一眼能读完」）`,
  longLen > setup.max && e5.dom === false && stubHit.n === beforeE5,
  { len: longLen, max: setup.max, dom: e5.dom, requests: stubHit.n - beforeE5 })
await shot('15-long-no-layer')

// E6 / E7：指针落在输入框上不弹；落在**同一容器**的标签文字上必须弹
await arming()
const beforeE6 = stubHit.n
await hoverAt('#r370-input', 900)
const e6 = await readLayer()
check('E6', '★★ 指针落在输入框（input）上 ⇒ 不弹、也不发请求（正在编辑的内容，悬停翻译会跟输入打架）',
  e6.dom === false && stubHit.n === beforeE6, { dom: e6.dom, requests: stubHit.n - beforeE6 })

await arming()
await hoverAt('#r370-ilabel', 900)
const e7 = await readLayer()
check('E7', '★★ 反控：落在**同一个容器**里的标签文字上 ⇒ 弹（证明 E6 归因于 inside-editable，而不是 no-block）',
  e7.dom === true && e7.original === 'Search products by keyword', { dom: e7.dom, original: e7.original })

// E8 / E9：contenteditable 不弹；同一元素去掉该属性必须弹
await arming()
const ceText = await run(`document.getElementById('r370-ce').textContent.trim()`)
const beforeE8 = stubHit.n
await hoverAt('#r370-ce', 900)
const e8 = await readLayer()
// ★ 判据只能取「没弹 **且** 没发请求」：`state.original` 是**故意的脏值** ——
//   `hide()` 只清 visible/loading，不删 original（留着是为了同文本去重的比对），
//   拿它当「没触发」的读数会假红（本探针第一次跑就这么红了一条）。
check('E8', '★★ contenteditable 块 ⇒ 不弹，且**没发翻译请求**（它有真 range、划词那条路能用，但悬停属于「正在编辑」）',
  e8.dom === false && stubHit.n === beforeE8, { dom: e8.dom, requests: stubHit.n - beforeE8, text: ceText })

await arming()
await run(`document.getElementById('r370-ce').setAttribute('contenteditable', 'false')`)
await hoverAt('#r370-ce', 900)
const e9 = await readLayer()
check('E9', '★★ 反控：**同一个元素**去掉 contenteditable ⇒ 弹（证明 E8 归因于 inside-editable）',
  e9.dom === true && e9.original === ceText, { dom: e9.dom, original: e9.original, expect: ceText })
await run(`document.getElementById('r370-ce').setAttribute('contenteditable', 'true')`)

// ===========================================================================
// F —— 开关与取消：关掉不弹（反控：开回来必须弹）；中途移开必须取消
// ===========================================================================
const HOVER_KEY = 'selection_translate_hover'
await arming()
await run(`window.__r370.api.setHoverEnabled(false)`)
const f1key = await run(`(() => { try { return localStorage.getItem(${JSON.stringify(HOVER_KEY)}) } catch (e) { return 'ERR' } })()`)
const beforeF1 = stubHit.n
await hoverAt('#r370-en', 900)
const f1 = await readLayer()
check('F1', '★★ 关掉悬停开关 ⇒ 不再弹、也不发请求（且落盘为 0）',
  f1.dom === false && f1key === '0' && stubHit.n === beforeF1,
  { dom: f1.dom, key: f1key, requests: stubHit.n - beforeF1 })

await arming()
await run(`window.__r370.api.setHoverEnabled(true)`)
const f2key = await run(`(() => { try { return localStorage.getItem(${JSON.stringify(HOVER_KEY)}) } catch (e) { return 'ERR' } })()`)
await hoverAt('#r370-en', 900)
const f2 = await readLayer()
check('F2', '★★ 反控：开关开回来 ⇒ 同一块立刻又能弹（证明 F1 归因于开关，不是别的原因）',
  f2.dom === true && f2key === '1', { dom: f2.dom, key: f2key })

await arming()
const beforeF3 = stubHit.n
await hoverAt('#r370-en', 200)     // 只停 200ms
await moveAway()                   // 差一点点就满阈值时移开
await sleep(700)                   // 远超阈值
const f3 = await readLayer()
check('F3', `★★ 停 ${200}ms 后移开 ⇒ 待触发的计时器被取消、不发请求（否则等于「移开还会迟到一个浮层」）`,
  f3.dom === false && stubHit.n === beforeF3, { dom: f3.dom, requests: stubHit.n - beforeF3 })
await shot('16-hover-off-and-cancel')

// ===========================================================================
// G —— 真实错误：只认「提到本链路」的异常（无关噪音不背锅）
// ===========================================================================
const ownErrs = events
  .filter((m) => m.method === 'Runtime.exceptionThrown')
  .map((m) => {
    const d = m.params && m.params.exceptionDetails
    return (d && (d.exception && d.exception.description)) || (d && d.text) || ''
  })
  .filter((t) => /hoverTranslate|useSelectionTranslate|stl-layer|SelectionTranslateLayer/.test(String(t)))
check('G1', '★无本链路相关的未捕获异常（过滤到 hoverTranslate / useSelectionTranslate / stl-layer）',
  ownErrs.length === 0, { ownErrs: ownErrs.map((t) => String(t).slice(0, 200)) })
check('G2', '★自检：LLM 桩确实被命中过（否则 V3 的「译文来自桩」无从谈起）',
  stubHit.n > 0, { hits: stubHit.n, lastReq: stubHit.lastReq })

const pass = results.filter((r) => r.state === 'PASS').length
const fail = results.filter((r) => r.state === 'FAIL').length
const skip = results.filter((r) => r.state === 'SKIP').length
console.log(`\n---- ${pass} PASS / ${fail} FAIL / ${skip} SKIP ----`)
console.log(`LLM 桩命中 ${stubHit.n} 次`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(fail === 0 ? 0 : 1)

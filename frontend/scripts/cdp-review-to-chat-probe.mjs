// CDP 真机端到端探针（第 298 轮）—— 「台账 → 对话」作用对象通道**全链路**。
//
// 老板给的验收流程（原话）：
//   台账点按钮 → 切到智能客服 → 上下文条显示对象 → Network 里请求体含 context_target
//   → 后端 prompt 段落确认注入
//
// 本探针覆盖前四步（第五步由后端探针 `.workbuddy/probes/r298_prompt_injection_e2e.py`
// 用真端点 + 捕获 SystemMessage 证明，二者合起来才是"端到端"）。
//
// 为什么非真机不可：
//   · 「切到对话」「上下文条显示什么」都是**渲染后的事实** —— 静态门禁只能证明源码里
//     有那个字符串、有那个事件名；事件到底有没有被 `Workspace` 接住、接住后
//     `workingReview` 有没有被写进 `contextTarget`，只有在真机点一次才知道。
//   · 「请求体里带的是不是 **这条** 差评」是**跨层数据流**：前端 DOM 选了第几行 →
//     provide 里的对象 → computed 派生 → 请求体 JSON。任何一层错位，静态判据都看不出来
//     （比如把 `d.id`（处置 id）当成 `review_id` 发出去 —— 字面上"带了个 id"，
//       语义上 Agent 会去处置**另一条**差评）。
//
// 判据口径（本仓纪律）：
//   · 先自检选择器真的选到东西，否则选择器写错会静默全绿；
//   · 依赖 seed 数据的判据允许 SKIP，但**必须如实打印**（不许当成通过）；
//   · **对照组成对**：只断言「点 💬 没开抽屉」是不够的 —— 抽屉要真开不了
//     （`.rd-act-open` 点不开）这条也照样绿。故先立基线「点行内按钮确实能开抽屉」。
//   · 对照组的另一半：`ref` 必须等于 `review_id` **且**不等于 `id`
//     —— 本仓 seed 里 `id` 是 `disp-<review_id>`，两个串不同 ⇒ 这条判据有区分力
//     （若 seed 里两者恰好相同，本判据会退化成恒真，故先断言二者确实不同）。
//
// 用法：node scripts/cdp-review-to-chat-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
//   PROBE_SHOP 覆盖钉住的店铺（默认 store_c3529ab1 = 亚马逊1，seed 里唯一有处置的店）
//   PROBE_SHOT_DIR 覆盖截图目录
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9381
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
// ★ seed 里只有「亚马逊1」有处置数据（另外三家 total=0）⇒ 台账行判据全靠它。
//   钉死在探针里而不是"取 shops[0]"：取 [0] 会被后端返回顺序决定，seed 一变就静默 SKIP。
const SHOP = process.env.PROBE_SHOP || 'store_c3529ab1'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r298_review_to_chat')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state, detail })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r298chat-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
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
// ★ 事件（无 id）另走一条通道：`Network.requestWillBeSent` 用来做"请求真发出去了"的旁证。
const events = []
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method) events.push(m)
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise(res => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })

const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400))
  return r?.result?.result?.value
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

// --------------------------------------------------------------------------
// ① 文档创建期注入：钉店铺 + 请求记录器（fetch **和** XHR 两条都要）
//    ★ 必须在 `Page.navigate` **之前**注册，否则 app 的首批请求就记不到了。
//    ★★★ 第 298 轮实测教训：**只包 `window.fetch` 会漏掉几乎全部业务请求**。
//       本仓数据层走 axios ⇒ 浏览器里默认走 `XMLHttpRequest`，`window.fetch`
//       在整个"进客服 → 开台账"过程中**一次都没被调用**（诊断实跑 `n=0`，
//       而 `boot` 计数为 1 ⇒ 不是文档被重建）。只有 `/chat/stream`（`streamSSE`）
//       用原生 fetch。于是「从响应里现取期望值」这条设计**静默取空**，
//       下游三条比对全部 FAIL 且 E9b 变成**空跑假绿**（拿 undefined 去比不等）。
//    ★ 只记 JSON 响应体：`/chat/stream` 是 SSE，`res.clone().text()`
//      会把整条流缓冲到底 ⇒ 既拖慢点击，又可能永远不 resolve。
// --------------------------------------------------------------------------
const PRELUDE = `
(() => {
  try { localStorage.setItem('current_shop_id', ${JSON.stringify(SHOP)}) } catch (e) {}
  window.__probeCalls = []

  // ---- fetch（/chat/stream 走这条）----
  const origFetch = window.fetch
  window.fetch = function (input, init) {
    const url = (typeof input === 'string') ? input : ((input && input.url) || '')
    const method = (init && init.method) || (input && input.method) || 'GET'
    let reqBody = null
    try { reqBody = (init && init.body != null) ? String(init.body) : null } catch (e) {}
    const rec = { kind: 'fetch', url, method, reqBody, resBody: null, status: null }
    window.__probeCalls.push(rec)
    return origFetch.apply(this, arguments).then(res => {
      rec.status = res.status
      try {
        const ct = res.headers.get('content-type') || ''
        if (ct.includes('json')) res.clone().text().then(t => { rec.resBody = t }).catch(() => {})
      } catch (e) {}
      return res
    })
  }

  // ---- XHR（axios 默认适配器走这条）----
  //   ★ 改**原型方法**而不是替换 XMLHttpRequest 构造器：替换会让
  //     「xhr instanceof XMLHttpRequest」之类的探测失配，风险远大于收益。
  const XP = window.XMLHttpRequest && window.XMLHttpRequest.prototype
  if (XP && !XP.__probeWrapped) {
    XP.__probeWrapped = true
    const origOpen = XP.open, origSend = XP.send
    XP.open = function (method, url) {
      this.__probe = { kind: 'xhr', url: String(url), method: String(method), reqBody: null, resBody: null, status: null }
      return origOpen.apply(this, arguments)
    }
    XP.send = function (body) {
      const rec = this.__probe
      if (rec) {
        try { rec.reqBody = (body == null) ? null : String(body) } catch (e) {}
        window.__probeCalls.push(rec)
        this.addEventListener('load', () => {
          try {
            rec.status = this.status
            if (!this.responseType || this.responseType === 'text') rec.resBody = this.responseText
          } catch (e) {}
        })
      }
      return origSend.apply(this, arguments)
    }
  }
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')
await send('Page.addScriptToEvaluateOnNewDocument', { source: PRELUDE })
await send('Page.navigate', { url: URL })
await sleep(4000)

const NORM = `(s) => (s || '').replace(/\\s+/g, ' ').trim()`

const clickByText = (label) => `
(() => {
  const norm = ${NORM}
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found' })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, cls: String(target.className).slice(0, 60) })
})()`

const drawerState = `
(() => {
  const t = document.querySelector('.ant-drawer-title')
  const open = !!document.querySelector('.ant-drawer-open')
  return JSON.stringify({ open, title: t ? (t.textContent || '').trim() : null })
})()`

const closeDrawer = `
(() => {
  const c = document.querySelector('.ant-drawer-close')
  if (c) { c.click(); return JSON.stringify({ via: 'close-btn' }) }
  const m = document.querySelector('.ant-drawer-mask')
  if (m) { m.click(); return JSON.stringify({ via: 'mask' }) }
  return JSON.stringify({ via: 'none' })
})()`

// ---------------------------------------------------------------- E0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('E0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })
const recArmed = await run('JSON.stringify({ armed: Array.isArray(window.__probeCalls), shop: localStorage.getItem("current_shop_id") })')
const recInfo = JSON.parse(recArmed)
check('E0b', '★ fetch 记录器已装载 + 店铺已钉住（自检：否则下面全部空跑）',
  recInfo.armed === true && recInfo.shop === SHOP, recInfo)

// ---------------------------------------------------------------- E1 进智能客服
const agentHit = await run(clickByText('智能客服'))
check('E1', '侧栏能点到「智能客服」', JSON.parse(agentHit).ok === true, JSON.parse(agentHit))
await sleep(1600)

// ---------------------------------------------------------------- E2 台账
const toolHit = await run(clickByText('差评台账'))
await sleep(1800)
const rdOk = await run(`!!document.querySelector('.rd-root')`)
check('E2', '点「差评台账」后右栏出工作台（.rd-root）', rdOk === true, { rdOk })

const tabHit = JSON.parse(await run(`
(() => {
  const norm = ${NORM}
  const tabs = [...document.querySelectorAll('.rd-tab')]
  const t = tabs.find(e => norm(e.textContent).includes('处置台账'))
  if (!t) return JSON.stringify({ ok: false, tabs: tabs.map(e => norm(e.textContent)) })
  t.click()
  return JSON.stringify({ ok: true, tabs: tabs.map(e => norm(e.textContent)) })
})()`))
await sleep(1600)
check('E2b', '能切到「处置台账」页签', tabHit.ok === true, tabHit)

// ---------------------------------------------------------------- E3 台账数据（跨层对账的"期望值"来源）
// ★ 期望值不手写：从**页面自己那次请求的响应**里现取。
//   这样「我点的是哪一行」与「我断言 ref 该等于什么」用的是同一份数据。
const dispInfo = JSON.parse(await run(`
(() => {
  const calls = window.__probeCalls || []
  const hits = calls.filter(c => c.url.includes('/trade/dispositions') && c.resBody)
  const c = hits[hits.length - 1]
  if (!c) return JSON.stringify({ found: false, n: calls.length })
  let first = null
  try { const j = JSON.parse(c.resBody); first = (j.items || [])[0] || null } catch (e) {}
  return JSON.stringify({ found: true, url: c.url, total: (() => { try { return JSON.parse(c.resBody).total } catch (e) { return null } })(),
    first: first ? { id: first.id, review_id: first.review_id, title: (first.review || {}).title || null } : null })
})()`))
check('E3', '★ 从页面自己那次 `/trade/dispositions` 响应里取到台账首行（期望值来源）',
  dispInfo.found === true && dispInfo.first != null, dispInfo)

const firstRow = dispInfo.first || {}
const twoIdsDiffer = !!(firstRow.id && firstRow.review_id && firstRow.id !== firstRow.review_id)
check('E3b', '★ 对照组前提：该行 `id`(处置 id) 与 `review_id` **确实不同**（否则下面 E9b 无区分力）',
  twoIdsDiffer === true, { id: firstRow.id, review_id: firstRow.review_id })

// ---------------------------------------------------------------- E4 台账行有 💬
const rowChat = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, skip: '台账为空' })
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-chat')
  if (!btn) return JSON.stringify({ ok: false, rows: rows.length, reason: '行内没有 💬 按钮' })
  const br = btn.getBoundingClientRect(), rr = rows[0].getBoundingClientRect()
  const titleCell = rows[0].querySelector('.rd-table-title')
  return JSON.stringify({ ok: true, rows: rows.length, text: (btn.textContent || '').trim(),
    disabled: btn.disabled === true,
    w: Math.round(br.width), h: Math.round(br.height),
    inRow: br.top >= rr.top - 1 && br.bottom <= rr.bottom + 1,
    rowTitle: titleCell ? (titleCell.textContent || '').trim() : null })
})()`))
if (rowChat.skip) {
  check('E4', '台账行有「💬 直达对话」按钮', null, rowChat)
} else {
  check('E4', '★ 台账行有「💬 直达对话」按钮且可点（第 298 轮补的缺口）',
    rowChat.ok === true && rowChat.text.includes('💬') && rowChat.disabled === false
    && rowChat.w > 0 && rowChat.h > 0 && rowChat.inRow === true, rowChat)
  // 交叉对账：DOM 首行的标题必须与 E3 取到的首行标题一致 ⇒ 证明"我点的行"就是"我比的数"
  check('E4b', '★ 交叉对账：DOM 首行标题 == 响应首行标题（证明点的是同一行）',
    !!rowChat.rowTitle && rowChat.rowTitle === firstRow.title,
    { dom: rowChat.rowTitle, api: firstRow.title })
}

// ---------------------------------------------------------------- E5 基线：点行内「查看/编辑」确实能开抽屉
// ★ 没有这条基线，「点 💬 没开抽屉」可能是"抽屉本来就打不开"而照样绿。
const openHit = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, skip: '台账为空' })
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-open')
  if (!btn) return JSON.stringify({ ok: false, reason: '没有 .rd-act-open' })
  btn.click()
  return JSON.stringify({ ok: true, label: (btn.textContent || '').trim() })
})()`))
await sleep(1600)
const baseDrawer = JSON.parse(await run(drawerState))
check('E5', '★ 基线（对照组）：点行内 `.rd-act-open` **能**开抽屉 ⇒ 抽屉自身是好的',
  openHit.ok === true && baseDrawer.open === true, { openHit, baseDrawer })
check('E5b', '抽屉标题是「差评处置」（第 298 轮术语统一）',
  typeof baseDrawer.title === 'string' && baseDrawer.title.includes('差评处置')
  && !baseDrawer.title.includes('差评处理'), baseDrawer)

const closed = JSON.parse(await run(closeDrawer))
await sleep(1200)
const afterClose = JSON.parse(await run(drawerState))
check('E5c', '基线收尾：抽屉能关掉（否则 E6 的"没开"无从判断）',
  afterClose.open === false, { closed, afterClose })

// ---------------------------------------------------------------- E6 点 💬 ⇒ 不弹抽屉（@click.stop 生效）
const chatHit = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, skip: '台账为空' })
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-chat')
  if (!btn) return JSON.stringify({ ok: false, reason: '没有 .rd-act-chat' })
  btn.click()
  return JSON.stringify({ ok: true })
})()`))
await sleep(1600)
const drawAfterChat = JSON.parse(await run(drawerState))
check('E6', '★ 点台账行 💬 **不弹抽屉**（`@click.stop` 挡住行级 `@click`）',
  chatHit.ok === true && drawAfterChat.open === false, { chatHit, drawAfterChat })

// ---------------------------------------------------------------- E7 视图切到对话 + 上下文条显示对象
const scope = JSON.parse(await run(`
(() => {
  const norm = ${NORM}
  const tag = document.querySelector('.iab-scope-float')
  const cards = document.querySelectorAll('.iab-chip')
  return JSON.stringify({
    hasTag: !!tag,
    text: tag ? norm(tag.textContent) : null,
    chipN: cards.length,
    viewChat: !!document.querySelector('.chat-textarea'),
    panelTitle: (document.querySelector('.task-config-panel .panel-title') || {}).textContent || null,
  })
})()`))
check('E7', '★ 点 💬 后切到对话视图（输入框在页面上）', scope.viewChat === true, scope)
// ★★★ 前提哨兵：上下文条按**设计**只在 `skillCards.length` 时渲染
//     （`ChatPanel/index.vue`：`<a-tag v-if="skillCards.length" class="iab-scope-float">`）。
//     不把这条单独判出来的话，「技能卡没加载出来」会让下面 E7b 报
//     「上下文条不显示对象」—— **归因反向**（它按设计就不该渲染，
//     真正坏的是技能目录没到）。本仓既有教训：门禁的前提哨兵与实装不符 ⇒ 恒红 + 归因反向。
//     ★ 连带把「技能目录那次取数」的结果一起报出来：`chipN===0` 时分得清
//       「请求失败 / 请求没发 / 请求成功但过滤后为空」三种，而不是只有一个 0。
const skillFetch = JSON.parse(await run(`
(() => {
  const calls = (window.__probeCalls || []).filter(c => c.url.includes('/skills'))
  const c = calls[calls.length - 1]
  return JSON.stringify({ n: calls.length, status: c ? c.status : null,
    items: (() => { try { return (JSON.parse(c.resBody || '{}').items || []).length } catch (e) { return null } })() })
})()`))
check('E7a', '★ 前提哨兵：技能卡已加载（`skillCards.length > 0`）—— 否则 E7b 按设计必然不成立，问题不在"对象没显示"',
  scope.chipN > 0, { chipN: scope.chipN, skillFetch })
check('E7b', '★ 上下文条 `.iab-scope-float` 显示对象（含「处置差评：」）',
  scope.hasTag === true && typeof scope.text === 'string' && scope.text.includes('处置差评：'), scope)
check('E7c', '上下文条上那句对象名 == 台账首行标题（tag 与数据同源）',
  typeof scope.text === 'string' && !!firstRow.title && scope.text.includes(firstRow.title),
  { tag: scope.text, expect: firstRow.title })

// ---------------------------------------------------------------- E8 发送 ⇒ 请求体含 context_target
await run(`
(() => {
  const el = document.querySelector('.chat-textarea')
  if (!el) return false
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  setter.call(el, '请按这条差评走一遍处置流程')
  el.dispatchEvent(new Event('input', { bubbles: true }))
  return true
})()`)
await sleep(700)
const sendHit = JSON.parse(await run(`
(() => {
  const btn = document.querySelector('.input-send-btn:not(.input-stop-btn)')
  if (!btn) return JSON.stringify({ ok: false, reason: '没有发送按钮' })
  if (btn.disabled) return JSON.stringify({ ok: false, reason: '发送按钮被禁用（输入未生效）' })
  btn.click()
  return JSON.stringify({ ok: true })
})()`))

let chatCall = { found: false }
for (let i = 0; i < 30; i++) {
  await sleep(500)
  chatCall = JSON.parse(await run(`
(() => {
  const calls = window.__probeCalls || []
  const hits = calls.filter(c => c.url.includes('/customer-service/chat/stream'))
  const c = hits[hits.length - 1]
  if (!c) return JSON.stringify({ found: false, n: calls.length, tail: calls.slice(-6).map(x => x.url) })
  let body = null
  try { body = JSON.parse(c.reqBody || 'null') } catch (e) { body = { __parseError: String(e), raw: String(c.reqBody).slice(0, 200) } }
  return JSON.stringify({ found: true, method: c.method, url: c.url, body })
})()`))
  if (chatCall.found) break
}

check('E8', '★ 发送按钮点了之后真的发出了 `/customer-service/chat/stream` 请求',
  sendHit.ok === true && chatCall.found === true, { sendHit, chatCall })

const sentBody = (chatCall.body || {})
const ct = sentBody.context_target
check('E8b', '★ 请求体里有 `context_target`（不是 undefined / 不是缺字段）',
  !!ct && typeof ct === 'object', { context_target: ct, keys: Object.keys(sentBody) })

// ---------------------------------------------------------------- E9 送的是 review_id，不是处置 id
check('E9', '★ `context_target.ref` == 台账首行的 `review_id`',
  !!ct && ct.ref === firstRow.review_id, { ref: ct && ct.ref, expect: firstRow.review_id })
check('E9b', '★ 对照组：`ref` **不是**处置 id（`d.id`）—— 取错字段会把结论打到另一条差评上',
  !!ct && !!firstRow.id && ct.ref !== firstRow.id, { ref: ct && ct.ref, wrong: firstRow.id })
check('E9c', '`context_target.label` == 「处置差评」（与上下文条同源）',
  !!ct && ct.label === '处置差评', { label: ct && ct.label })
check('E9d', '`context_target.title` == 台账首行标题',
  !!ct && ct.title === firstRow.title, { title: ct && ct.title, expect: firstRow.title })

// 旁证：CDP Network 域也看到了这次请求（证明真发出去了，不是被 fetch 包装骗过）
const netSeen = events.some(e => e.method === 'Network.requestWillBeSent'
  && String(e.params?.request?.url || '').includes('/customer-service/chat/stream'))
check('E9e', '旁证：CDP Network 域也捕获到该请求（真的上了网）', netSeen === true, { netSeen })

await shot('ledger-to-chat')

// ---------------------------------------------------------------- E10 切走再切回 ⇒ 不残留
await run(clickByText('选品分析师'))
await sleep(1600)
const afterAway = JSON.parse(await run(`
(() => {
  const tag = document.querySelector('.iab-scope-float')
  return JSON.stringify({ text: tag ? (${NORM})(tag.textContent) : null })
})()`))
check('E10', '切到别的 Agent 后，上下文条**不显示**那条差评（属主谓词成对清空）',
  !(afterAway.text || '').includes('处置差评：'), afterAway)

await run(clickByText('智能客服'))
await sleep(1600)
const afterBack = JSON.parse(await run(`
(() => {
  const tag = document.querySelector('.iab-scope-float')
  return JSON.stringify({ text: tag ? (${NORM})(tag.textContent) : null })
})()`))
check('E10b', '★ 切回智能客服后**不残留**（对象已随离开被清空，不会拿旧对象继续跑）',
  !(afterBack.text || '').includes('处置差评：'), afterBack)
check('E10c', '对照组：切回后上下文条也不是空白/异常（给出的是"下一步点哪里"）',
  typeof afterBack.text === 'string' && afterBack.text.includes('未选择差评'), afterBack)

// ==========================================================================
// F 组（第 298 轮 · 老板 bug1）：点台账行的 💬 **不得把「大屏模式」打掉**
//
//   根因：`hasWideBoard = isWideBoardAgent || isReviewDeskTool`，而
//   `isReviewDeskTool` 判的是 `currentSelectedTool?.id === 'review-desk'` ——
//   即**工具级**宽看板。`handleReviewToChat` 的 Step 0 无条件
//   `currentSelectedTool.value = null` ⇒ 点按钮的那一刻 `hasWideBoard` 变假
//   ⇒ 顶栏 `.mode-switch` 消失、根节点 `review-data-mode` 类消失、右栏从 528
//   回到 340、面板内容被清空 —— 老板看到的「大屏模式直接没了」。
//   ★ 那段清空是从 `launchProductToAgent` / `handleMonitorLaunchAnalysis` 抄来的，
//     那两处的**源在资料库视图**、目标 Agent 也不同，清空是对的；
//     本处的源**就是那个面板本身**、目标 Agent 也**就是当前 Agent** ⇒ 清空是错的。
// ==========================================================================
// 先确保没有残留的活跃流（E8 发过一轮），否则下面点不动。
await run(`
(() => { const s = document.querySelector('.input-send-btn.input-stop-btn'); if (s) { s.click(); return true } return false })()`)
await sleep(1200)

// 重新走一遍：客服 → 差评台账 → 处置台账（此时对象已被 E10 清空）
await run(clickByText('智能客服'))
await sleep(1500)
await run(clickByText('差评台账'))
await sleep(1800)
await run(`
(() => {
  const norm = ${NORM}
  const t = [...document.querySelectorAll('.rd-tab')].find(e => norm(e.textContent).includes('处置台账'))
  if (t) t.click()
  return true
})()`)
await sleep(1600)

// ---- F1 基线：切「大屏模式」确实生效（否则 F2 是空断言）
//   ★ 先把**点击前**哪个模式是 active 记下来：`reviewMode` 是按 Agent 存 localStorage 的，
//     若进台账时已经是 data，那 F1 的点击就是空操作 —— 判据本身照样成立
//     （F2d 比的是"点 💬 前后是否一致"），但**读数**必须如实写出来，
//     否则「基线绿」会被误读成"这一步真的从 chat 切到了 data"。
const wideOn = JSON.parse(await run(`
(() => {
  const norm = ${NORM}
  const btns = [...document.querySelectorAll('.mode-switch-btn')]
  const activeBefore = (btns.find(b => b.classList.contains('active')) || {}).textContent
  const t = btns.find(b => norm(b.textContent).includes('大屏模式'))
  if (!t) return JSON.stringify({ ok: false, reason: '没有 .mode-switch-btn[大屏模式]', n: btns.length })
  t.click()
  return JSON.stringify({ ok: true, n: btns.length, activeBefore: norm(activeBefore) })
})()`))
await sleep(1400)

const wideState = `
(() => {
  const root = document.querySelector('.workspace-container')
  const sider = document.querySelector('.right-panel')
  return JSON.stringify({
    dataMode: !!(root && root.classList.contains('review-data-mode')),
    switchN: document.querySelectorAll('.mode-switch-btn').length,
    siderW: sider ? Math.round(sider.getBoundingClientRect().width) : null,
    rdRoot: !!document.querySelector('.rd-root'),
  })
})()`
const wideBefore = JSON.parse(await run(wideState))
check('F1', '★ 基线（对照组）：切「大屏模式」确实生效（点击前是「对话模式」→ 点后根节点带 `review-data-mode` + 右栏吃满剩余宽度 > 528 + 台账仍在）',
  wideOn.ok === true && wideOn.activeBefore === '对话模式'
  && wideBefore.dataMode === true && wideBefore.switchN === 2
  && (wideBefore.siderW || 0) > 528 && wideBefore.rdRoot === true, { wideOn, wideBefore })

// ---- F2 点 💬 ⇒ 大屏模式**仍在**
const chatHit2 = JSON.parse(await run(`
(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ ok: false, skip: '台账为空' })
  const btn = rows[0].querySelector('.rd-table-act button.rd-act-chat')
  if (!btn) return JSON.stringify({ ok: false, reason: '没有 .rd-act-chat' })
  btn.click()
  return JSON.stringify({ ok: true })
})()`))
await sleep(1800)
const wideAfter = JSON.parse(await run(wideState))
check('F2', '★★ bug1：点台账行 💬 之后**大屏模式仍在**（根节点仍带 `review-data-mode`）',
  chatHit2.ok === true && wideAfter.dataMode === true, { chatHit2, wideAfter })
check('F2b', '★★ bug1：顶栏「对话/大屏」切换器仍在（`hasWideBoard` 没被清掉）',
  wideAfter.switchN === 2, wideAfter)
check('F2c', '★★ bug1：右栏仍吃满剩余宽度（> 528）且台账面板未被清空（`.rd-root` 还在）',
  (wideAfter.siderW || 0) > 528 && wideAfter.rdRoot === true, wideAfter)
// ★ 最强的一条：**布局状态逐字未变**。逐项判据都过、但整体漂移（比如某个类没了）
//   也能被这条抓到；反过来它红了也能一眼看出漂在哪一项（上一行有明细）。
check('F2d', '★★ bug1：点按钮前后布局状态**完全一致**（大屏模式没被"带进对话"撤销）',
  JSON.stringify(wideAfter) === JSON.stringify(wideBefore), { before: wideBefore, after: wideAfter })

// ==========================================================================
// G 组（第 298 轮 · 老板 bug2）：对象载入后必须给**取消入口**
//
//   现状：`pendingSkillCard` 有「本次对话使用：X ×」（第 250 轮加的撤销口），
//   但 `contextTarget`（本次作用对象）**一个出口都没有** —— 一旦载入某条差评，
//   除了「切走 Agent 再切回来」没有任何办法取消。而那个办法用户想不到。
// ==========================================================================
await sleep(400)
const clearBtn = JSON.parse(await run(`
(() => {
  const tag = document.querySelector('.iab-scope-float')
  if (!tag) return JSON.stringify({ ok: false, reason: '没有上下文条' })
  const b = tag.querySelector('.iab-scope-clear')
  if (!b) return JSON.stringify({ ok: false, reason: '上下文条上没有取消按钮', text: (tag.textContent || '').trim() })
  const br = b.getBoundingClientRect()
  return JSON.stringify({ ok: true, w: Math.round(br.width), h: Math.round(br.height),
    title: b.getAttribute('title') || null, text: (tag.textContent || '').trim() })
})()`))
check('G1', '★★ bug2：对象已载入时，上下文条上有取消按钮 `.iab-scope-clear`',
  clearBtn.ok === true && clearBtn.w > 0 && clearBtn.h > 0, clearBtn)

const beforeClearCount = JSON.parse(await run(`
JSON.stringify((window.__probeCalls || []).filter(c => c.url.includes('/customer-service/chat/stream')).length)`))
await run(`(() => { const b = document.querySelector('.iab-scope-clear'); if (b) b.click(); return true })()`)
await sleep(1000)
const afterClearText = JSON.parse(await run(`
(() => {
  const tag = document.querySelector('.iab-scope-float')
  return JSON.stringify({ text: tag ? (${NORM})(tag.textContent) : null,
    hasClear: !!(tag && tag.querySelector('.iab-scope-clear')) })
})()`))
check('G2', '★★ bug2：点取消后上下文条**不再**带那条差评（回到「未选择差评…」）',
  typeof afterClearText.text === 'string' && !afterClearText.text.includes('处置差评：')
  && afterClearText.text.includes('未选择差评'), afterClearText)
check('G2b', '取消按钮随之消失（没有对象时不该留一个点了没反应的 ×）',
  afterClearText.hasClear === false, afterClearText)

// ---- G3 取消之后发一轮 ⇒ 请求体 `context_target` 必须是 **null**（不是旧对象、也不是缺字段）
await run(`
(() => {
  const el = document.querySelector('.chat-textarea')
  if (!el) return false
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
  setter.call(el, '这条我已经处理完了，换个话题')
  el.dispatchEvent(new Event('input', { bubbles: true }))
  return true
})()`)
await sleep(700)
await run(`(() => { const b = document.querySelector('.input-send-btn:not(.input-stop-btn)'); if (b && !b.disabled) { b.click(); return true } return false })()`)

let ct2 = 'NOT_FOUND'
for (let i = 0; i < 30; i++) {
  await sleep(500)
  const seen = JSON.parse(await run(`
JSON.stringify((window.__probeCalls || []).filter(c => c.url.includes('/customer-service/chat/stream')).length)`))
  if (seen > beforeClearCount) {
    ct2 = await run(`
(() => {
  const calls = (window.__probeCalls || []).filter(c => c.url.includes('/customer-service/chat/stream'))
  const c = calls[calls.length - 1]
  try { return JSON.stringify(JSON.parse(c.reqBody || 'null').context_target) } catch (e) { return 'PARSE_ERR' }
})()`)
    break
  }
}
check('G3', '★★ bug2：取消后再发一轮，请求体 `context_target` == null（明确「本次没有对象」）',
  ct2 === 'null', { context_target: ct2, beforeClearCount })
await run(`(() => { const s = document.querySelector('.input-send-btn.input-stop-btn'); if (s) s.click(); return true })()`)

// ---------------------------------------------------------------- 取证打印
// ★ 只判 PASS/FAIL 不够 —— 汇报时要能一眼看到**实际观测到的值**。
console.log('\n---- 证据 ----')
console.log('期望值来源   :', dispInfo.url || '(未捕获)')
console.log('台账首行     :', JSON.stringify({ id: firstRow.id, review_id: firstRow.review_id, title: firstRow.title }))
console.log('DOM 首行标题 :', JSON.stringify(rowChat.rowTitle ?? null))
console.log('上下文条文案 :', JSON.stringify(scope.text ?? null))
console.log('请求 URL     :', JSON.stringify(chatCall.url ?? null))
console.log('请求体 ct    :', JSON.stringify(ct ?? null))
console.log('请求体顶层键 :', JSON.stringify(Object.keys(sentBody)))
console.log('切走后文案   :', JSON.stringify(afterAway.text ?? null))
console.log('切回后文案   :', JSON.stringify(afterBack.text ?? null))
console.log('大屏模式 前/后:', JSON.stringify(wideBefore), '→', JSON.stringify(wideAfter))
console.log('切大屏前 active:', JSON.stringify((wideOn || {}).activeBefore))
console.log('取消后文案   :', JSON.stringify(afterClearText.text ?? null))
console.log('取消后再发 ct:', JSON.stringify(ct2))

// ---------------------------------------------------------------- 汇总
const pass = results.filter(r => r.state === 'PASS').length
const fail = results.filter(r => r.state === 'FAIL').length
const skip = results.filter(r => r.state === 'SKIP').length
console.log(`\n---- ${pass} PASS / ${fail} FAIL / ${skip} SKIP ----`)
console.log('截图目录：', SHOT_DIR)
ws.close(); chrome.kill()
process.exit(fail ? 1 : 0)

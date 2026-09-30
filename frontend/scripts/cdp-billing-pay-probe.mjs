// CDP 真实浏览器端到端（第 277 轮）—— 支付宝扫码支付弹窗。
//
// 为什么必须用真实浏览器：本轮的交付物里，**倒计时**与**二维码渲染**都是
// 「算出来的结果」——静态门禁能证明「代码里有 409 分支」，证明不了
// 「打开页面时倒计时是 29:xx 而不是已过期」。而后者正是本轮主线缺陷的形态。
//
// 判据口径（本仓纪律）：
//   - 先自检「选择器真的选到东西」，否则 selector 写错会静默全绿（L0）。
//   - 倒计时用**区间**判（28:00 ~ 30:00），不写死秒数 —— 写死就成墓志铭。
//   - 排他性判据：.pay-status 与 .pay-status-expired **必须互斥**（这是产品语义，不是巧合）。
//   - 账单必须带探针前缀（INV-CDP-）：若后端读失败，页面会灌 mock 账单
//     （`loadInvoices` 的 catch 分支）⇒ 这条能把「假绿」挡在门外。
//
// 用法：node scripts/cdp-billing-pay-probe.mjs <scenario>
//   scenario ∈ a（pending+二维码）/ b（pending+无 pay_url）/ c（paid）/ none（无单）
//              f（两个读口被 Network.setBlockedURLs 拦掉 ⇒ 验"加载失败"说不说真话；
//                 复用 none 的造数结果）
//   先跑 backend/.workbuddy/probes/cdp_pay_seed.py <scenario> 造数。
//
//   PROBE_BASE  覆盖前端地址（默认 http://127.0.0.1:5173）
//   PROBE_API_PATH 覆盖后端 API 路径前缀（默认 /api/v1）—— 必须走**同源**，见 C4 注释
//   PROBE_SHOT  覆盖截图输出目录
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9352
const BASE = process.env.PROBE_BASE || 'http://127.0.0.1:5173'
const API_PATH = process.env.PROBE_API_PATH || '/api/v1'
const CTX = process.env.PROBE_CTX || 'D:\\ai\\eCommerce\\backend\\.workbuddy\\probes\\.cdp_pay_ctx.json'
const SHOT_DIR = process.env.PROBE_SHOT || join(process.cwd(), '..', '.workbuddy', 'probes', 'r277_cdp')

const scenario = (process.argv[2] || 'a').toLowerCase()
if (!['a', 'b', 'c', 'none', 'f'].includes(scenario)) {
  console.log(`FAIL: 未知场景 ${scenario}（可选 a / b / c / none / f）`)
  process.exit(2)
}
if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}
if (!existsSync(CTX)) {
  console.log(`FAIL: 找不到造数上下文 ${CTX} —— 先跑 cdp_pay_seed.py ${scenario}`)
  process.exit(2)
}
const ctx = JSON.parse(readFileSync(CTX, 'utf8'))
// ★ 场景 f（读口失败）复用 none 的造数结果：它要验的是"接口挂了时界面说什么"，
//   与"库里有没有 pending 单"无关，所以不必另造数据。
const expectCtxScenario = scenario === 'f' ? 'none' : scenario
if (ctx.scenario !== expectCtxScenario) {
  console.log(`FAIL: 数据上下文是场景 «${ctx.scenario}»，但本次要验 «${scenario}»（需要 «${expectCtxScenario}»）—— 先重跑造数脚本`)
  process.exit(2)
}
if (!ctx.access_token) {
  console.log('FAIL: 上下文里没有 access_token')
  process.exit(2)
}

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail)}`)
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-pay-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  '--window-size=1440,900',
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
if (!page) { console.log('FAIL: 拿不到调试目标'); chrome.kill(); process.exit(1) }

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
const runJson = async expr => {
  const raw = await run(expr)
  if (typeof raw !== 'string' || raw.startsWith('EXC:')) return { __err: String(raw) }
  try { return JSON.parse(raw) } catch { return { __err: `不是 JSON: ${String(raw).slice(0, 200)}` } }
}
const shot = async file => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r.result?.data) {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, Buffer.from(r.result.data, 'base64'))
    return true
  }
  return false
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

// ★ 用 addScriptToEvaluateOnNewDocument 而不是「先 navigate 到根再 setItem」：
//   后者要跑两次导航，且中途 SPA 会带着空 token 打一轮接口（刷出 401 噪音）。
const userInfo = JSON.stringify({
  id: ctx.user_id, email: ctx.email, name: 'CDP 支付探针', role: 'user',
})
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `
    localStorage.setItem('access_token', ${JSON.stringify(ctx.access_token)});
    localStorage.setItem('refresh_token', ${JSON.stringify(ctx.access_token)});
    localStorage.setItem('user_info', ${JSON.stringify(userInfo)});
  `,
})

// ★ 场景 f：让**两个读口**的请求根本发不出去（不是让后端返 500）——
//   这正是"接口挂了 / 断网"时用户会走的那条路。必须在 navigate **之前**开拦截，
//   否则首屏那轮请求已经打完了。
if (scenario === 'f') {
  await send('Network.enable')
  await send('Network.setBlockedURLs', {
    urls: ['*billing/invoices*', '*billing/plans*'],
  })
}

const URL = `${BASE}/subscription`
await send('Page.navigate', { url: URL })
console.log(`scenario = ${scenario} | url = ${URL} | invoice = ${ctx.invoice_id || '(无)'}`)

// ---------- L0：页面真的渲染出来了吗 ----------
let shellReady = false
for (let i = 0; i < 40; i++) {
  const n = await run('document.querySelectorAll(".subscription-container").length')
  if (typeof n === 'number' && n >= 1) { shellReady = true; break }
  await sleep(500)
}
check('L0', '订阅页外壳渲染出来了（.subscription-container）', shellReady, { url: URL })
if (!shellReady) {
  await shot(join(SHOT_DIR, `r277_pay_${scenario}_boot_fail.png`))
  console.log('FAIL: 页面没渲染出来 —— 先修环境再谈支付')
  chrome.kill(); process.exit(1)
}

// 等弹窗（场景 a/b 应出现；c/none 不应出现）
const findDialog = () => run('document.querySelectorAll(".pay-dialog").length')
let dialogAppeared = false
if (scenario === 'a' || scenario === 'b') {
  for (let i = 0; i < 40; i++) {
    const n = await findDialog()
    if (typeof n === 'number' && n >= 1) { dialogAppeared = true; break }
    await sleep(500)
  }
} else {
  // 反向：给 restorePendingPayment（在 Promise.all 之后）充足时间，确认它**打开不了**弹窗
  await sleep(8000)
  dialogAppeared = (await findDialog()) >= 1
}

// ---------- 场景 a：主场景 ----------
if (scenario === 'a') {
  check('A1', '存在 pending 单时自动弹出扫码弹窗（.pay-dialog）', dialogAppeared, { dialogAppeared })

  if (dialogAppeared) {
    const probe = await runJson(`(() => {
      const img = document.querySelector('.pay-qr-img')
      const statusEl = document.querySelector('.pay-status')
      const expiredEl = document.querySelector('.pay-status-expired')
      const strong = statusEl ? statusEl.querySelector('strong') : null
      const m = (strong ? strong.textContent : '').trim().match(/^(\\d{2}):(\\d{2})$/)
      const rows = [...document.querySelectorAll('.invoices-card tbody tr')].map(tr => tr.textContent.replace(/\\s+/g,' ').trim())
      return JSON.stringify({
        hasImg: !!img,
        imgComplete: img ? img.complete : null,
        imgNaturalWidth: img ? img.naturalWidth : null,
        imgSrcHead: img ? String(img.src).slice(0, 34) : '',
        statusText: statusEl ? statusEl.textContent.replace(/\\s+/g,' ').trim() : null,
        expiredText: expiredEl ? expiredEl.textContent.replace(/\\s+/g,' ').trim() : null,
        remaining: m ? (Number(m[1]) * 60 + Number(m[2])) : null,
        seconds: m ? m[2] : null,
        rowCount: rows.length,
        cdpRows: rows.filter(r => r.includes('INV-CDP-')).length,
      })
    })()`)

    if (probe.__err) {
      check('A2', '读取弹窗内部状态', false, probe)
    } else {
      check('A2', '二维码 <img> 真的渲染出来（naturalWidth > 0）',
        probe.hasImg && probe.imgComplete === true && probe.imgNaturalWidth > 0, probe)
      check('A3', '二维码 src 是 SVG data URI（后端出的图，不是占位）',
        String(probe.imgSrcHead).startsWith('data:image/svg+xml'), probe)
      check('A4', '倒计时文案形态为「请在 mm:ss 内扫码完成支付」',
        typeof probe.statusText === 'string' && /请在 \d{2}:\d{2} 内扫码完成支付/.test(probe.statusText), probe)
      // ★ 本轮主线：修好时间口径之前，这两条必红（倒计时为负 ⇒ 直接进"已过期"分支）
      // ★ 区间取 20~30 分钟而**不是** 28~30：账单签发时刻与本次运行之间隔着
      //   造数 + 起浏览器的时间（实测第二遍跑只剩 27:53）。把「我跑得多快」变成
      //   断言的隐藏输入，等于写了一句墓志铭。
      check('A5', '倒计时落在 20~30 分钟区间（退化时会直接归零并转入「已过期」分支）',
        typeof probe.remaining === 'number' && probe.remaining > 20 * 60 && probe.remaining <= 30 * 60, probe)
      check('A6', '「已过期」节点**不存在**（与倒计时互斥）',
        probe.expiredText === null && !/已过期/.test(String(probe.statusText)), probe)
      check('A7', '账单历史里有探针账单（证明是后端真数据，没灌 mock）',
        probe.cdpRows >= 1, probe)

      // ★★ 本组**最锐利**的一条：后端的时间串必须自带时区偏移。
      //   上面所有「界面 remaining 是多少」的断言，在时间串丢掉偏移时会**一起**偏
      //   —— 浏览器按本地时区解析，我在别处若也按本地解析，两边互相吻合 ⇒ 假绿。
      //   只有「串里到底有没有偏移标记」是字符串层面的客观事实，任何时区都吞不掉。
      const rawTs = await runJson(`(async () => {
        const r = await fetch(${JSON.stringify(API_PATH + '/billing/payment/' + ctx.invoice_id)}, {
          headers: { Authorization: 'Bearer ' + localStorage.getItem('access_token') },
        })
        const j = await r.json()
        return JSON.stringify({ created_at: j.payment.created_at, expires_at: j.payment.expires_at })
      })()`)
      const OFFSET_RE = /(?:[+-]\d{2}:\d{2}|Z)$/
      check('A5OFF', '后端 expires_at / created_at 自带时区偏移（与时区无关的客观判据）',
        !rawTs.__err
          && OFFSET_RE.test(String(rawTs.created_at))
          && OFFSET_RE.test(String(rawTs.expires_at)), rawTs)

      // 倒计时在走：间隔 3 秒再采样
      const before = probe.remaining
      await sleep(3000)
      const after = await runJson(`(() => {
        const s = document.querySelector('.pay-status strong')
        const m = (s ? s.textContent : '').trim().match(/^(\\d{2}):(\\d{2})$/)
        return JSON.stringify({ remaining: m ? (Number(m[1]) * 60 + Number(m[2])) : null })
      })()`)
      const delta = (typeof before === 'number' && typeof after.remaining === 'number') ? before - after.remaining : null
      check('A8', '倒计时真的在走（3 秒内少了 2~5 秒，容差给渲染与定时器抖动）',
        delta !== null && delta >= 2 && delta <= 5, { before, after: after.remaining, delta })
    }
  }
  await shot(join(SHOT_DIR, `r277_pay_${scenario}.png`))
}

// ---------- 场景 b：取码失败必须上屏 ----------
if (scenario === 'b') {
  check('B1', '有 pending 单（即使没码）也会打开弹窗', dialogAppeared, { dialogAppeared })
  if (dialogAppeared) {
    const probe = await runJson(`(() => {
      const ph = document.querySelector('.pay-qr-placeholder')
      const alert = document.querySelector('.pay-qr-placeholder .ant-alert')
      return JSON.stringify({
        hasPlaceholder: !!ph,
        placeholderText: ph ? ph.textContent.replace(/\\s+/g,' ').trim() : null,
        hasAlert: !!alert,
        alertText: alert ? alert.textContent.replace(/\\s+/g,' ').trim() : null,
      })
    })()`)
    if (probe.__err) {
      check('B2', '读取取码失败态', false, probe)
    } else {
      // ★ 失败必须**可见**：空白中央会让用户以为"码还没出来"而一直等
      check('B2', '取码失败时错误信息真的渲染到界面上（.ant-alert 非空）',
        probe.hasAlert && typeof probe.alertText === 'string' && probe.alertText.length > 0, probe)
      check('B3', '失败文案说的是「没有二维码」这类实情，而非空占位',
        typeof probe.alertText === 'string' && probe.alertText.includes('二维码'), probe)
    }
  }
  await shot(join(SHOT_DIR, `r277_pay_${scenario}.png`))
}

// ---------- 场景 c / none：不该有弹窗 ----------
if (scenario === 'c' || scenario === 'none') {
  check('C1', `${scenario === 'c' ? '已支付' : '无 pending'}账单打开页面时**不**弹出扫码弹窗`,
    !dialogAppeared, { dialogAppeared })

  const table = await runJson(`(() => {
    const card = document.querySelector('.invoices-card')
    const rows = [...document.querySelectorAll('.invoices-card tbody tr')]
    return JSON.stringify({
      rowCount: rows.length,
      cdpRows: rows.filter(tr => tr.textContent.includes('INV-CDP-')).length,
      emptyTexts: [...(card ? card.querySelectorAll('.ant-empty-description') : [])]
        .map(el => el.textContent.replace(/\\s+/g, ' ').trim()),
      // ★ 问「有没有账单号」而不是问行数：antd 的 dataSource 为空时**仍然**渲染一行占位
      invoiceNumbers: [...(card ? card.querySelectorAll('.ant-table-cell') : [])]
        .map(el => el.textContent.trim()).filter(t => /^INV-/.test(t)),
      payButtons: [...document.querySelectorAll('.invoices-card button')].filter(b => b.textContent.trim() === '去支付').length,
    })
  })()`)
  if (table.__err) {
    check('C2', '读取账单表', false, table)
  } else if (scenario === 'c') {
    check('C2', '已支付账单来自后端真数据（含 INV-CDP- 行，排除 mock 兜底）', table.cdpRows >= 1, table)
    // ★ v-if="record.status === 'pending'" ⇒ 已支付行**不该**有「去支付」
    check('C3', '已支付账单行没有「去支付」按钮（不给用户扫一张已付的码）',
      table.payButtons === 0, table)
  } else {
    check('C2', '清空场景显示空状态「暂无账单记录」，且不含任何账单号（没有 mock 兜底灌入）',
      (table.emptyTexts || []).includes('暂无账单记录') && (table.invoiceNumbers || []).length === 0, table)
  }

  // 409 契约：直接问后端「已支付账单的二维码」——必须是 409，不是 200
  if (scenario === 'c' && ctx.invoice_id) {
    const qr = await runJson(`(async () => {
      const r = await fetch(${JSON.stringify(API_PATH + '/billing/payment/qr/' + ctx.invoice_id)}, {
        headers: { Authorization: 'Bearer ' + localStorage.getItem('access_token') },
      })
      let detail = ''
      try { detail = (await r.json()).detail || '' } catch {}
      return JSON.stringify({ status: r.status, detail })
    })()`)
    // ★ 409 是「已付过」而非错误：前端把它当成功处理（loadPayQr 的 409 分支）
    check('C4', '后端对已支付账单的二维码请求返回 409（前端据此走成功分支）',
      qr.status === 409, qr)
  }
  await shot(join(SHOT_DIR, `r277_pay_${scenario}.png`))

  // ★ 支付方式卡的文案住在页面最下方（首屏之外）⇒ 不滚动就拍不到。
  //   这一段是第 282 轮「矛盾文案」改动的取证点：
  //   改前写的是「添加信用卡或借记卡用于自动续费」+ 一个点了没反应的添加按钮，
  //   与「扫码一次性收款」的架构直接矛盾。
  await run(`document.querySelector('.payment-card')?.scrollIntoView({ block: 'center' })`)
  await sleep(500)
  await shot(join(SHOT_DIR, `r277_pay_${scenario}_paymethod.png`))
}

// ---------- 场景 f：读口失败 ⇒ 界面必须说真话（★ 第 279 轮新增）----------
//
// 这一组守的是「空状态优于虚构默认」的**完整半边**：不虚构（没有假数据）
// + 如实说明（说清是"加载失败"而不是"暂无"）。
// ★ 判据问的是**数据本身**（有没有假账单号 / 假套餐卡片），不是问文案在不在 ——
//   假数据的形态就是"看起来和真数据一模一样"，只有问数据才抓得住。
if (scenario === 'f') {
  const state = await runJson(`(() => {
    const invCard = document.querySelector('.invoices-card')
    const plansCard = document.querySelector('.plans-card')
    const empties = el => [...(el ? el.querySelectorAll('.ant-empty-description') : [])]
      .map(x => x.textContent.replace(/\\s+/g, ' ').trim())
    return JSON.stringify({
      invoiceEmpties: empties(invCard),
      plansEmpties: empties(plansCard),
      invoiceNumbers: [...(invCard ? invCard.querySelectorAll('.ant-table-cell') : [])]
        .map(el => el.textContent.trim()).filter(t => /^INV-/.test(t)),
      planCards: plansCard ? plansCard.querySelectorAll('.plan-card').length : -1,
      // ★ antd-vue 会给**两个汉字**的按钮自动插入一个空格（「重试」渲染成「重 试」，
      //   即 autoInsertSpaceInButton 特性）⇒ 文案判据必须先归掉空白再比，
      //   否则会得出"按钮根本没渲染"这种**相反**的结论。
      retryButtons: [...document.querySelectorAll('.plans-card button, .invoices-card button')]
        .filter(b => b.textContent.replace(/\\s+/g, '') === '重试').length,
    })
  })()`)
  if (state.__err) {
    check('F1', '读取失败态', false, state)
  } else {
    check('F1', '账单读失败时说明「加载失败，请重试」，而不是伪装成「暂无账单记录」',
      (state.invoiceEmpties || []).includes('账单加载失败，请重试'), state)
    check('F2', '套餐读失败时说明「加载失败，请重试」',
      (state.plansEmpties || []).includes('套餐加载失败，请重试'), state)
    check('F3', '读失败时**一条假账单都没有**（改前这里会灌出 3 条不存在的已支付账单）',
      (state.invoiceNumbers || []).length === 0, state)
    check('F4', '读失败时**一个假套餐卡片都没有**（改前这里会灌出 3 个后端不存在的套餐）',
      state.planCards === 0, state)
    check('F5', '两个读口各给了一个「重试」出口',
      state.retryButtons >= 2, state)
  }
  // ★ 分两张拍：失败态住在套餐卡与账单卡里，都在首屏之下 ——
  //   不滚动的话截图只看得到页头，"加载失败"四个字一张都留不下。
  await run(`document.querySelector('.plans-card')?.scrollIntoView({ block: 'start' })`)
  await sleep(500)
  await shot(join(SHOT_DIR, `r277_pay_${scenario}_plans.png`))
  await run(`document.querySelector('.invoices-card')?.scrollIntoView({ block: 'start' })`)
  await sleep(500)
  await shot(join(SHOT_DIR, `r277_pay_${scenario}.png`))
}

// ---------- 汇总 ----------
const failed = results.filter(r => !r.ok)
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(failed.length ? 1 : 0)

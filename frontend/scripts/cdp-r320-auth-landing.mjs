// CDP 真机探针（第 320 轮 / 台账 #1155）—— 两条邮件落地页
//
// ★★★ 本探针要证的是什么
//
//   `backend/core/identity/email_tokens.py::_link()` 发出的邮件链接是
//     `{PUBLIC_SITE_URL}/reset-password?token=…`   （send_reset_email）
//     `{PUBLIC_SITE_URL}/verify-email?token=…`     （send_verify_email）
//   而 `frontend/src/router/index.ts` 此前只有 6 条路由，**两条都不在其中**。
//   ⇒ 用户在邮箱里点「重置密码」/「验证邮箱」，浏览器打开的是**空白页**。
//
//   本轮把两条路由 + 两个落地页补齐。这个"补上了"是**渲染结果**，
//   源码里加了路由 ≠ 用户点开有东西 —— 所以必须真机跑。
//
// ============================================================================
// ★★★ 「不是空白页」这条判据是怎么一步步定下来的（两个坑，都是探针自己的）
// ============================================================================
//  第 1 版：`bodyLen > 60`。写死的常数。⇒ B 页只有 50 字符，**假红**。
//          根因：那个 60 是估的，不是量的。
//  第 2 版：先跑「不存在的路由」量出空白基线 BLANK_LEN，再要求
//          `bodyLen >= BLANK_LEN + 30`。⇒ 仍然假红，而且暴露出**更糟的事**：
//          那个"空白页"其实有 50 字符 —— 是**全局新手引导浮层**
//          （「👋 第一次来？…跳过 开始引导」）盖在了不存在的路由上。
//          ⇒ 基线被污染了，而且污染量恰好等于 B 页的真实内容量（都是 50）。
//  第 3 版（现行）：
//    · 落地后**先关掉引导浮层**（点「跳过」），把污染从所有读数里去掉；
//    · 「非空」判据锚定在**页面自己的容器 `.auth-card`** 上，
//      不用整页 `document.body.innerText` —— 后者会把全局浮层、
//      顶栏、任何跨路由常驻的东西一起算进来，"这页有没有内容"根本量不准；
//    · 阈值 = **控制组卡片的实测文本长度（0，因为它压根没卡片）+ 20**。
//      基线来自本轮实测，没有估的常数。
//
// 用法：node scripts/cdp-r320-auth-landing.mjs
//   PROBE_URL 覆盖站点根（默认 http://127.0.0.1:5173）
//   ★ 路由**写死在脚本里**，不走环境变量 ——
//     Git Bash 会把看起来像路径的环境变量值翻转成 Windows 路径
//     （见 skill cdp-probe-authoring-pitfalls 坑 7）。
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9396
const BASE = process.env.PROBE_URL || 'http://127.0.0.1:5173'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r320_auth_landing')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
// 三态：true 绿 / false 红 / null 跳过（环境条件，不进通过数）
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  const tail = ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)
  console.log(`${state}  ${id}  ${name}${tail}`)
}

// ---------------------------------------------------------------------------
// 被测面
// ---------------------------------------------------------------------------
const BOGUS = 'probe-bogus-token-320'
/** 对照：一条**不存在**的路由。它应当"落地成功"但**没有本页容器** —— 这就是"空白页"的形状。 */
const CONTROL = { id: 'Z', route: '/no-such-route-320', query: '', label: '对照：不存在的路由' }

const CASES = [
  { id: 'A', route: '/reset-password', query: '', label: '重置密码（邮件链接降级：没有 token）' },
  { id: 'B', route: '/reset-password', query: `?token=${BOGUS}`, label: '重置密码（带 token）' },
  { id: 'C', route: '/verify-email', query: `?token=${BOGUS}`, label: '邮箱验证（带假 token，后端必然 400）' },
]

/** 「非空」判据在控制组基线之上要求的增量。控制组卡片文本为 0 ⇒ 阈值 = 20。 */
const DELTA = 20

if (!existsSync(CHROME)) {
  console.log(`FAIL: 找不到 chrome：${CHROME}`)
  process.exit(2)
}
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r320-'))
const chrome = spawn(
  CHROME,
  [
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
  ],
  { stdio: 'ignore' }
)

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/list`)
    targets = await r.json()
    if (targets.some((t) => t.type === 'page')) break
  } catch {
    /* 还没起来 */
  }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) {
  console.log('FAIL: 拉不到 CDP page target')
  chrome.kill()
  process.exit(1)
}

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m)
    pending.delete(m.id)
  }
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
  const flat = (s) => norm(s).replace(/\\s+/g, '');
`
const runN = async (body) => run(`(() => { ${NORM_SRC} ${body} })()`)

const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) {
    writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
  }
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
})

// ★ 清掉登录态：这正是真实场景 —— 点邮件的人**根本没登录**
//   （"忘记密码"本来就是"登不上才用"的功能）。
//   若带着演示身份，verify-email 页会走「已登录 ⇒ 可重发」那一支，
//   掩盖住"未登录用户看到什么"这个真问题。
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `try { localStorage.clear() } catch (e) {}`,
})

/** 关掉新手引导浮层。
 *
 * ★ 为什么必须有这一步：清掉 localStorage 之后，引导浮层会在**每一次**导航后
 *   重新出现，而它是**跨路由常驻**的 —— 于是它会混进任何"整页正文"读数里。
 *   本轮实测：不关它时，一条不存在的路由也会显示 50 字符正文
 *   （「👋 第一次来？…跳过 开始引导」），把"空白页基线"整个污染掉。
 *   ★ 判据纪律：任何"我点了它"的动作都要返回**是否真的点到**，
 *     否则点击失败会被后面读成"业务上没有这个东西"。
 */
async function dismissTour() {
  // ★ 第 4 版修正：原来只查 `button, .ant-tour-close, [class*=tour] [class*=close]`，
  //   而实况那个「跳过」**不是 `<button>`** ⇒ 从来没点到过。
  //   现在扫**所有元素**，在文案命中的那些里取 **textContent 最短的那个**
  //   （最短 = 最靠近叶子节点 = 真正被点的那个，而不是把整块浮层点一遍）。
  const clicked = await runN(`
    const WANT = ['跳过', '跳过引导', '跳过教程', '知道了', '关闭']
    const hits = [...document.querySelectorAll('*')]
      .filter(el => WANT.includes(flat(el.textContent)))
      .sort((a, b) => a.textContent.length - b.textContent.length)
    if (hits.length) { hits[0].click(); return true }
    return false
  `)
  if (clicked === true) await sleep(600)
  return clicked === true
}

/** 导航并等「落地」。
 *
 * ★ 坑 8：改完源码后的**第一次** Page.navigate 可能落 about:blank
 *   （Vite 整页重载与紧接的导航撞车）⇒ 必须重试，并区分
 *   「我这边没打开」与「页面确实没有内容」。
 */
async function goto(pathAndQuery, { waitText = true } = {}) {
  const want = BASE + pathAndQuery
  const wantPath = pathAndQuery.split('?')[0]
  for (let attempt = 1; attempt <= 3; attempt++) {
    await send('Page.navigate', { url: want })
    for (let i = 0; i < 30; i++) {
      const st = await runN(`
        return JSON.stringify({
          path: location.pathname,
          href: location.href,
          ready: document.readyState,
        })
      `)
      if (typeof st === 'string' && st.startsWith('{')) {
        const o = JSON.parse(st)
        if (o.path === wantPath && o.ready !== 'loading') {
          if (!waitText) return { landed: true, attempt }
          // 等正文稳定（异步请求回来 / spin 停）
          for (let k = 0; k < 24; k++) {
            const spinning = await run(`!!document.querySelector('.ant-spin-spinning')`)
            const len = await run(`(document.body.innerText || '').trim().length`)
            if (spinning === false && typeof len === 'number' && len > 0) {
              return { landed: true, attempt }
            }
            await sleep(400)
          }
          return { landed: true, attempt, settled: false }
        }
      }
      await sleep(400)
    }
  }
  return { landed: false }
}

/** 采集页面读数。
 *
 * ★ 关键：判定"这页有没有内容"用 **`.auth-card` 自己的文本**，
 *   不用 `document.body.innerText` —— 后者含所有跨路由常驻元素
 *   （新手引导、顶栏…），量不出"本页渲染了什么"。
 */
const probePage = () =>
  runN(`
    const card = document.querySelector('.auth-card')
    const cardText = card ? norm(card.innerText) : ''
    return JSON.stringify({
      path: location.pathname,
      bodyLen: (document.body.innerText || '').trim().length,
      bodyText: norm((document.body.innerText || '')).slice(0, 300),
      hasCard: !!card,
      cardTextLen: cardText.length,
      cardText: cardText.slice(0, 300),
      inputs: card ? card.querySelectorAll('input').length : 0,
      pwInputs: card ? card.querySelectorAll('input[type=password]').length : 0,
      buttons: card ? [...card.querySelectorAll('button')].map(b => flat(b.textContent)) : [],
      alerts: card ? [...card.querySelectorAll('.ant-alert')].map(a => norm(a.textContent).slice(0, 120)) : [],
    })
  `)

const parse = (s, id, label) => {
  if (typeof s !== 'string' || !s.startsWith('{')) {
    check(id, `${label} · 读数采集成功`, false, s)
    return null
  }
  return JSON.parse(s)
}

console.log('=== 第 320 轮 · 账号安全邮件落地页真机探针 ===')
console.log(`站点 ${BASE} | 截图 ${SHOT_DIR}`)
console.log()

// ===========================================================================
// 第 0 步：先量「空白页」的基线 —— 基准必须来自本轮实测，不能写死
// ===========================================================================
console.log(`--- 基准 Z：${CONTROL.route}（不存在的路由）---`)
const navZ = await goto(CONTROL.route, { waitText: false })
await sleep(1000)
const tourZ = await dismissTour()
const tourSeen = tourZ ? '有（已关闭）' : '无'
await sleep(500)
await shot('r320_Z_control_blank')
const pz = navZ.landed ? parse(await probePage(), 'Z', '对照') : null
const zLanded = !!pz && pz.path === CONTROL.route
check('Z-L0', '基准 · 不存在的路由也**落地**了（说明后面比的不是"打开失败"）', zLanded, {
  nav: navZ,
  path: pz && pz.path,
})

const BLANK_CARD_LEN = zLanded ? pz.cardTextLen : null
const MIN_CARD_LEN = BLANK_CARD_LEN === null ? null : BLANK_CARD_LEN + DELTA
console.log(
  `  ·· 引导浮层本轮：${tourSeen}` +
    ` | 空白页基线 BLANK_CARD_LEN = ${BLANK_CARD_LEN} 字符` +
    ` ⇒ 真实页面卡片文本阈值 = ${BLANK_CARD_LEN}+${DELTA} = ${MIN_CARD_LEN}`
)
if (zLanded) {
  check(
    'Z-L1',
    '基准 · 它没有本页容器 .auth-card ★（这就是"空白页"的**结构**特征）',
    pz.hasCard === false,
    { hasCard: pz.hasCard, cardTextLen: pz.cardTextLen }
  )
  check('Z-L2', '基准 · 卡片文本为 0（阈值基线的来源）', BLANK_CARD_LEN === 0, {
    cardTextLen: BLANK_CARD_LEN,
  })
  // ★ 第 4 版删掉了原来的 Z-L3「整页正文也确实为空」。
  //   它不是一条**有效**判据：本仓有**跨路由常驻**的新手引导浮层，
  //   一条不存在的路由也会显示 50 字符正文
  //   （「👋 第一次来？…跳过 开始引导」）。
  //   ⇒ 与其断言一件做不到的事（"整页为空"），不如把"抗污染"钉在
  //     **被测页面的度量口径**上：见下面每条用例里的 `X-J4`。
  //   这里只把观测到的事实如实打出来，供人对照。
  console.log(
    `  ·· 备注：控制组整页正文字符数 = ${pz.bodyLen}` +
      (pz.bodyLen > 0
        ? `（含跨路由常驻元素；raw = ${JSON.stringify(pz.bodyText.slice(0, 60))}）` +
          ' ⇒ 本探针的"非空"判据**只**看 .auth-card 文本，不看整页正文'
        : '')
  )
}
if (MIN_CARD_LEN === null) {
  check('Z-L4', '基准可用 —— 取不到时**不得**默默用常数兜底', false, {
    note: '基线没量到，"非空"判据无从谈起；这里显式判红而不是退化成写死阈值',
  })
}
console.log()

// ===========================================================================
// 逐条用例
// ===========================================================================
for (const c of CASES) {
  console.log(`--- 用例 ${c.id}：${c.label}  (${c.route}${c.query}) ---`)
  const nav = await goto(c.route + c.query)
  const tour = await dismissTour()
  await sleep(400)
  await shot(`r320_${c.id}_landing`)

  // L0：页面真的打开了
  //  ★ 坑 7 的解药：「页面没打开」必须表现为**一条 FAIL**，
  //    而不是让后面的测量撞 null 崩掉（或把 null 读成"页面里没这个元素"）。
  const p = nav.landed ? parse(await probePage(), c.id, c.label) : null
  const reallyLanded = !!p && p.path === c.route
  check(
    `${c.id}-L0`,
    `${c.label} · 页面真的打开了（pathname == ${c.route}）`,
    reallyLanded,
    nav.landed ? p && { path: p.path, bodyLen: p.bodyLen } : { nav, note: '3 次重试都没落地' }
  )
  if (!reallyLanded) {
    console.log()
    continue
  }

  // J1 ★★★ 主判据：本页容器存在（控制组明确没有）
  check(
    `${c.id}-J1`,
    `${c.label} · 本页容器 .auth-card 已渲染（对照：无）★`,
    p.hasCard === true,
    { hasCard: p.hasCard, cardTextLen: p.cardTextLen }
  )

  // J2 ★★★ 二次判据：容器里**真的有内容** —— 与同轮实测的空白基线比
  check(
    `${c.id}-J2`,
    `${c.label} · 卡片内有实际内容（${p.cardTextLen} >= ${MIN_CARD_LEN}）★不是空白页`,
    MIN_CARD_LEN !== null && p.cardTextLen >= MIN_CARD_LEN,
    { cardTextLen: p.cardTextLen, blankBase: BLANK_CARD_LEN, min: MIN_CARD_LEN, cardText: p.cardText }
  )

  // J3：容器里**至少有一个可点的出路**（空白页不可能满足）。
  //   ★ 第 4 版修正：原来写 `inputs + buttons >= 3` —— 又是估的常数。
  //     verify-email 的**失败态合法地没有输入框**（链接无效，本来就没得填），
  //     只有「去登录 / 返回登录」两枚按钮（2 < 3）⇒ 把一个正确的页面判红了。
  //     「至少有一个可点的出路」才是这条判据的本意，且控制组为 0，天然可分。
  check(
    `${c.id}-J3`,
    `${c.label} · 卡片内至少有一条可点的出路（按钮 >= 1）`,
    p.buttons.length >= 1,
    { inputs: p.inputs, buttons: p.buttons }
  )

  // J9：卡片文本里**不得**出现跨路由常驻浮层的文案 ★
  //   这条直接证明「非空」度量没有被全局浮层污染 ——
  //   若哪天有东西被塞进 .auth-card 里，它会立刻红。
  //   ★ 编号取 J9（跳过 J4~J8）：那几号被下面各用例的专属判据占着，
  //     撞号会让报告里出现两条同名判据，读日志的人分不清红的是哪一条。
  check(
    `${c.id}-J9`,
    `${c.label} · 卡片文本不含引导浮层文案（度量未被跨路由常驻元素污染）★`,
    !/第一次来|开始引导/.test(p.cardText),
    { cardText: p.cardText.slice(0, 120) }
  )

  if (c.id === 'A') {
    check('A-J4', '无 token 时给出「没有重置代码」的手输兜底提示', /没有重置代码/.test(p.cardText), p.cardText)
    check('A-J5', '手输兜底下有 3 个输入框（重置代码 / 新密码 / 确认新密码）', p.inputs === 3, { inputs: p.inputs })
    check('A-J6', '两个密码框都是 type=password', p.pwInputs === 2, { pwInputs: p.pwInputs })
    check('A-J7', '有「重置密码」提交按钮', p.buttons.includes('重置密码'), p.buttons)
    check(
      'A-J8',
      '有「返回登录」与「重新申请一封」两个出路',
      p.buttons.includes('返回登录') && p.buttons.includes('重新申请一封'),
      p.buttons
    )
  }

  if (c.id === 'B') {
    check('B-J4', '带 token 时**不再**显示手输兜底提示', !/没有重置代码/.test(p.cardText), p.cardText)
    check('B-J5', '带 token 时只有 2 个输入框（新密码 / 确认新密码）', p.inputs === 2, { inputs: p.inputs })
    check('B-J6', '两个都是密码框', p.pwInputs === 2, { pwInputs: p.pwInputs })
    check('B-J7', '有「重置密码」提交按钮', p.buttons.includes('重置密码'), p.buttons)
  }

  if (c.id === 'C') {
    check('C-J4', '页面标题是「邮箱验证」', /邮箱验证/.test(p.cardText), p.cardText)
    check('C-J5', '假 token 被如实报错（失败态显示，且**留在页面上**）', p.alerts.length >= 1, p.alerts)
    check(
      'C-J6',
      '未登录用户看到的是「登录后才能重发」而不是一个必然失败的按钮',
      /登录后才能重发/.test(p.cardText) && !p.buttons.includes('重新发送验证邮件'),
      { cardText: p.cardText, buttons: p.buttons }
    )
    check('C-J7', '给出「去登录」出路', p.buttons.includes('去登录'), p.buttons)
  }

  console.log()
}

// ===========================================================================
// 汇总
// ===========================================================================
const failed = results.filter((r) => r.ok === false)
const skipped = results.filter((r) => r.ok === null)
const passed = results.filter((r) => r.ok === true)
console.log('='.repeat(72))
console.log(`PASS ${passed.length} | FAIL ${failed.length} | SKIP ${skipped.length}`)
if (failed.length) {
  console.log('失败项：')
  for (const f of failed) console.log(`  · ${f.id}  ${f.name}`)
}
console.log(`截图目录：${SHOT_DIR}`)

chrome.kill()
process.exit(failed.length ? 1 : 0)

// 第 322 轮 B 段真机验收：三处 UI 修正。
//
//   ① 团队页有返回按钮，且点了**真的离开 /team**（订阅页早有，团队页此前没有）
//   ② 「删除音色」在**面板最上方**（业务顺序：先删旧音色 → 才能创建新音色）
//   ③ 点「试听」**直接出声**（不再要求生成之后再点一次播放）
//
// ★ 为什么 A 段要给 `/api/v1/accounts*` 打桩：
//   `.env.development` 里 `VITE_DEMO_MODE=true` ⇒ 守卫自动注入 `demo-token`。
//   而 `/team` 的账户接口带 `requiresIdentity`，后端回 401；
//   拦截器四道判定后必然 `clearAuth()` + `router.push(Login)`（实测）——
//   页面会被弹走，返回按钮根本来不及量。
//   ⇒ 用 CDP `Fetch` 域把这一族请求就地应答（空列表），让页面壳留住。
//   这不是"伪造产品行为"：本探针要验的是**表头有没有返回入口、点了走不走**，
//   与团队成员列表的内容无关。B 段会关掉拦截，读真实后端数据。
//
// ★ 自动播放：显式 `--autoplay-policy=no-user-gesture-required`。
//   要测的是「我们的代码有没有 play()」，不是 Chrome 的自动播放策略；
//   探针里的 `.click()` 是合成事件，不关掉策略会把做对的判成红（假红）。
//
// 用法：node scripts/cdp-r322b-ui-tweaks.mjs
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9348
const HOME_URL = 'http://localhost:5173/'
// 本机唯一有 ready 音色的店铺（`GET /api/v1/voice-clone/status` 实测 ready=true）
const SHOP_WITH_VOICE = 'store_a498a7d5'
const SHOT_DIR = 'D:/ai/eCommerce/.workbuddy/probes/r322b_ui'

mkdirSync(SHOT_DIR, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const at = () => String(Date.now() - t0).padStart(6) + 'ms'

let chrome
const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 300s，强制退出')
  try { chrome?.kill() } catch { /* ignore */ }
  process.exit(2)
}, 300000)
process.on('unhandledRejection', (e) => console.error('UNHANDLED REJECTION:', e))

const profile = mkdtempSync(join(tmpdir(), 'cdp-r322b-'))
chrome = spawn(
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
    // ★ 见文件头：测「我们的代码有没有 play()」，不是浏览器的自动播放策略
    '--autoplay-policy=no-user-gesture-required',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let targets = []
for (let i = 0; i < 80; i++) {
  try {
    targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
    if (targets.some((t) => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
const pageErrors = []
const netLog = []
const stubbed = []

ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails
    pageErrors.push(String(d.exception?.description || d.text || '').slice(0, 400))
    return
  }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    pageErrors.push('[console.error] ' + m.params.args.map((a) => String(a.value ?? a.description ?? '')).join(' ').slice(0, 300))
    return
  }
  if (m.method === 'Network.responseReceived') {
    const r = m.params.response
    // ★ 必须把 `/static/voice/` 也收进来：B11 判的是「音频真取到了」，
    //   而只收 `/api/v1/` 会让那条判据**结构上恒空**（永远红 = 空跑）。
    if (r.url.includes('/api/v1/') || r.url.includes('/static/voice/')) {
      netLog.push({ at: at(), status: r.status, path: new URL(r.url).pathname })
    }
    return
  }
  // ★ A 段的桩：把 /accounts 一族就地应答，避免 401 → 强制跳登录
  if (m.method === 'Fetch.requestPaused') {
    const p = m.params
    if (p.responseStatusCode) return  // 已到响应阶段，不处理
    const url = p.request.url
    const path = (() => { try { return new URL(url).pathname } catch { return url } })()
    let body = {}
    if (path.endsWith('/accounts/me')) body = { account: null }
    else if (/\/accounts\/?$/.test(path)) body = { accounts: [], total: 0 }
    else if (/\/members\/?$/.test(path)) body = { members: [], total: 0 }
    stubbed.push({ at: at(), path })
    send('Fetch.fulfillRequest', {
      requestId: p.requestId,
      responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json; charset=utf-8' }],
      body: Buffer.from(JSON.stringify(body), 'utf8').toString('base64'),
    })
    return
  }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
const run = async (expr, userGesture = false) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, userGesture })
  const ex = r.result?.exceptionDetails
  if (ex) return 'EXC: ' + String(ex.exception?.description || ex.text || '').slice(0, 400)
  return r.result?.result?.value
}
// ★ 点击一律走这里：userGesture 让它等价于真实点按（自动播放判定依赖它）
const click = (expr) => run(expr, true)

const checks = []
const check = (id, label, ok, extra) => {
  checks.push({ id, label, ok: !!ok, extra })
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${id}  ${label}${extra !== undefined ? '  ' + JSON.stringify(extra) : ''}`)
}
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r.result?.data) {
    const p = join(SHOT_DIR, name)
    writeFileSync(p, Buffer.from(r.result.data, 'base64'))
    console.log('        截图 → ' + p)
  }
}
const waitReady = async (minLen = 300) => {
  for (let i = 0; i < 4; i++) {
    const n = await run('document.body?.textContent?.length || 0')
    if (typeof n === 'number' && n > minLen) return n
    await send('Page.reload')
    await sleep(6000)
  }
  return await run('document.body?.textContent?.length || 0')
}

await send('Page.enable')
await send('Runtime.enable')
await send('Network.enable')

// 与守卫注入的演示身份一致（显式写，避免依赖 DEMO_MODE 的注入时机）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `try{
    localStorage.setItem('access_token','demo-token');
    localStorage.setItem('refresh_token','demo-refresh-token');
    localStorage.setItem('current_shop_id', ${JSON.stringify(SHOP_WITH_VOICE)});
  }catch(e){}`,
})

// ★★ 后端限流是**按 IP 共享的 60 次/分钟**（`core/middleware/rate_limit.py`），
//   连 `/static/*` 都计数。本探针一轮要发上百个请求，A 段跑完窗口往往已经见底。
//   实测形态：`/voice-clone/status` 回 429 ⇒ 音色面板整体降级成「该功能未启用」
//   空态 ⇒ **B 段十四条判据一起假红**。所以在两处必须等窗口回血：
//     · 进 B 段之前（否则面板根本渲染不出来）
//     · 点「试听」之前（否则音频链接 429 ⇒ 媒体元素报 Format error）
const API_BASE = 'http://127.0.0.1:8000'

async function rateHeadroom() {
  try {
    const r = await fetch(`${API_BASE}/api/v1/voice-clone/config`, { headers: { 'X-Shop-ID': SHOP_WITH_VOICE } })
    const rem = Number(r.headers.get('x-ratelimit-remaining'))
    const rst = Number(r.headers.get('x-ratelimit-reset'))
    return { rem: Number.isFinite(rem) ? rem : null, rst: Number.isFinite(rst) ? rst : null, status: r.status }
  } catch { return { rem: null, rst: null, status: 0 } }
}

async function waitHeadroom(need) {
  for (let i = 0; i < 6; i++) {
    const h = await rateHeadroom()
    if (h.rem == null || h.rem >= need) return h
    const waitMs = Math.min(75, (h.rst ?? 60) + 2) * 1000
    console.log(`  限流余量 ${h.rem} < ${need}（HTTP ${h.status}），等 ${Math.round(waitMs / 1000)}s 回血`)
    await sleep(waitMs)
  }
  return await rateHeadroom()
}

// ════════════════════════════════════════════════════════════════
// PHASE A —— 团队页返回按钮
// ════════════════════════════════════════════════════════════════
console.log('\n===== PHASE A：团队页返回按钮 =====')
await send('Fetch.enable', {
  patterns: [{ urlPattern: '*/api/v1/accounts*', requestStage: 'Request' }],
})

console.log('--- A.1 先落到 / （制造一条历史，返回才有落点）')
await send('Page.navigate', { url: HOME_URL })
// ★ 必须确认**真的落地了**：实测出现过导航没完成、history 里只剩 about:blank，
//   于是点「返回」落在 about:blank（pathname === 'blank'），把 A7 判成红。
let a1Path = null
for (let i = 0; i < 25; i++) {
  await sleep(800)
  a1Path = await run('location.pathname')
  if (a1Path === '/') break
}
console.log('  path=', a1Path)

console.log('--- A.2 再进 /team')
await send('Page.navigate', { url: 'http://localhost:5173/team' })
await sleep(9000)
let aReady = null
for (let i = 0; i < 12; i++) {
  aReady = await run(`!!document.querySelector('.team-back')`)
  if (aReady === true) break
  await sleep(600)
}
console.log('  .team-back 出现 =', aReady)

const A = await run(`(()=>{
  const b=document.querySelector('.team-back');
  const r=b?b.getBoundingClientRect():null;
  const svg=b?b.querySelector('svg'):null;
  const sr=b?svg&&svg.getBoundingClientRect():null;
  return JSON.stringify({
    path: location.pathname,
    historyLen: history.length,
    btnCount: document.querySelectorAll('.team-back').length,
    enabled: b? !b.disabled : null,
    aria: b? b.getAttribute('aria-label') : null,
    w: r?Math.round(r.width):null, h: r?Math.round(r.height):null,
    iconW: sr?Math.round(sr.width):null, iconH: sr?Math.round(sr.height):null,
    inHead: b? !!b.closest('.team-head') : null,
    titleText: (document.querySelector('.team-title')||{}).textContent||null,
    titleLeft: (()=>{const t=document.querySelector('.team-title');return t?Math.round(t.getBoundingClientRect().left):null})(),
    // 图标是否在标题左侧（返回按钮的语义位置）
    btnLeft: r?Math.round(r.left):null,
    // 返回按钮不应出现在 /team 之外的地方（下方会切页再验一次）
  });
})()`)
console.log('  A 快照:', A)
let AJ = null
try { AJ = JSON.parse(A) } catch { /* ignore */ }
await shot('01_team_header.png')

console.log('--- A.3 点返回（期望回到 /）')
const aClick = await click(`(()=>{
  const b=document.querySelector('.team-back');
  if(!b) return 'NO_BTN';
  if(b.disabled) return 'DISABLED';
  b.click(); return 'clicked';
})()`)
console.log('  点击结果 =', aClick)
await sleep(3000)
const aAfter = await run(`JSON.stringify({path:location.pathname, hasTeamBack:!!document.querySelector('.team-back')})`)
console.log('  点击后:', aAfter)
let A2 = null
try { A2 = JSON.parse(aAfter) } catch { /* ignore */ }
await shot('02_after_back.png')

check('A0', 'A 段前提：确实先落在 /（否则「返回」没有落点，A7 会假红）', a1Path === '/', a1Path)
check('A1', '团队页有返回按钮（.team-back 恰好 1 个）', AJ?.btnCount === 1, AJ?.btnCount)
check('A2', '返回按钮可见（rect 宽高 > 0）', (AJ?.w ?? 0) > 0 && (AJ?.h ?? 0) > 0, { w: AJ?.w, h: AJ?.h })
check('A3', '按钮内有箭头图标（svg 真实渲染）', (AJ?.iconW ?? 0) > 0 && (AJ?.iconH ?? 0) > 0, { iconW: AJ?.iconW, iconH: AJ?.iconH })
check('A4', '按钮可访问（aria-label=返回）', AJ?.aria === '返回', AJ?.aria)
check('A5', '按钮位于表头内且在标题左侧（是"返回"不是装饰）', AJ?.inHead === true && AJ?.btnLeft != null && AJ?.titleLeft != null && AJ.btnLeft < AJ.titleLeft, { inHead: AJ?.inHead, btnLeft: AJ?.btnLeft, titleLeft: AJ?.titleLeft })
check('A6', '对照组：点击前确实停在 /team（A7 不是恒真）', AJ?.path === '/team', AJ?.path)
check('A7', '★ 点返回后离开 /team 回到 /', A2?.path === '/', A2?.path)
check('A8', '返回页面上不再有团队返回按钮（证明按钮属团队页）', A2?.hasTeamBack === false, A2?.hasTeamBack)

// ════════════════════════════════════════════════════════════════
// PHASE B —— 音色克隆面板：删除音色在最上 + 试听一键出声
// ════════════════════════════════════════════════════════════════
console.log('\n===== PHASE B：音色克隆面板 =====')
await send('Fetch.disable')   // 关掉桩，读真实后端数据
// ★ 见文件头的限流说明：不等这一下，A 段耗尽的窗口会让面板 429 降级 ⇒ B 段全红
await waitHeadroom(30)
console.log('--- B.1 回 / 并打开设置抽屉 → 客服语音')
await send('Page.navigate', { url: HOME_URL })
await sleep(9000)
await waitReady()
await run(`window.dispatchEvent(new CustomEvent('open-settings-drawer'))`)
await sleep(3500)
console.log('  抽屉 =', await run(`!!document.querySelector('.ant-drawer-open')`))
console.log('  tab =', await run(`(()=>{
  const t=[...document.querySelectorAll('.ant-tabs-tab')].find(e=>e.textContent.includes('客服语音'));
  if(!t) return 'NO_TAB';
  t.click(); return 'clicked';
})()`))
await sleep(4000)

let bReady = null
for (let i = 0; i < 12; i++) {
  bReady = await run(`!!document.querySelector('.vc-danger-row')`)
  if (bReady === true) break
  await sleep(700)
}
console.log('  .vc-danger-row 出现 =', bReady)

const B = await run(`(()=>{
  const strip=(s)=>(s||'').replace(/\\s+/g,'');
  const btns=[...document.querySelectorAll('button')];
  const delRow=document.querySelector('.vc-danger-row');
  const delBtn=btns.find(b=>strip(b.textContent)==='删除音色');
  const pvBtn=btns.find(b=>strip(b.textContent)==='试听');
  const oldBtn=btns.find(b=>b.textContent.includes('生成试听'));
  const firstCard=[...document.querySelectorAll('.vc-card')][0];
  const cards=[...document.querySelectorAll('.vc-card')];
  const step3=cards.find(c=>{const t=c.querySelector('.ant-card-head-title');return t && t.textContent.includes('3')});
  const rect=(e)=>{if(!e)return null;const r=e.getBoundingClientRect();return {top:Math.round(r.top),h:Math.round(r.height)}};
  return JSON.stringify({
    dangerRowCount: document.querySelectorAll('.vc-danger-row').length,
    delInAnyCard: delRow? !!delRow.closest('.vc-card') : null,
    delBtnText: delBtn? delBtn.textContent.trim() : null,
    delIsDanger: delBtn? delBtn.classList.contains('ant-btn-dangerous') : null,
    step3HasDelete: step3? [...step3.querySelectorAll('button')].some(b=>strip(b.textContent)==='删除音色') : null,
    step3Title: step3? step3.querySelector('.ant-card-head-title').textContent.trim() : null,
    cardCount: cards.length,
    firstCardTitle: firstCard? firstCard.querySelector('.ant-card-head-title').textContent.trim() : null,
    delTop: rect(delRow).top,
    firstCardTop: rect(firstCard).top,
    pvText: pvBtn? pvBtn.textContent.trim() : null,
    pvDisabled: pvBtn? pvBtn.disabled : null,
    pvCardTitle: pvBtn? (()=>{const c=pvBtn.closest('.vc-card');const t=c&&c.querySelector('.ant-card-head-title');return t?t.textContent.trim():null})() : null,
    oldBtnExists: !!oldBtn,
  });
})()`)
console.log('  B 快照:', B)
let BJ = null
try { BJ = JSON.parse(B) } catch { /* ignore */ }
await shot('03_panel_top_delete.png')

check('B1', '「删除音色」容器存在且唯一（没留第二份在步骤 3）', BJ?.dangerRowCount === 1, BJ?.dangerRowCount)
check('B2', '★ 删除入口不在任何步骤卡内（inCard = null/false）', BJ?.delInAnyCard === false, BJ?.delInAnyCard)
check('B3', '★ 删除入口坐标高于第一张步骤卡（真在最上）', BJ?.delTop != null && BJ?.firstCardTop != null && BJ.delTop < BJ.firstCardTop, { delTop: BJ?.delTop, firstCardTop: BJ?.firstCardTop })
check('B4', '步骤 3（创建音色）卡里已无删除按钮', BJ?.step3HasDelete === false, { step3Title: BJ?.step3Title, has: BJ?.step3HasDelete })
check('B5', '删除按钮仍带 danger 样式 + 文案不变', BJ?.delIsDanger === true && BJ?.delBtnText === '删除音色', { danger: BJ?.delIsDanger, text: BJ?.delBtnText })
check('B6', '★ 试听按钮文案已改为「试听」', BJ?.pvText === '试听', BJ?.pvText)
check('B7', '★ 页面上不再存在「生成试听」按钮（不是新增了一个）', BJ?.oldBtnExists === false, BJ?.oldBtnExists)
check('B8', '试听按钮归属步骤 4（位置未被误移）', String(BJ?.pvCardTitle || '').includes('4'), BJ?.pvCardTitle)

console.log('--- B.2 点「试听」→ 期望直接出声')

/**
 * ★ 后端限流是**按 IP 共享的 60 次/分钟**（`core/middleware/rate_limit.py`），
 *   连 `/static/*` 都计数。本探针一轮要发上百个请求 ⇒ 试听那一步很容易撞上 429，
 *   形态是「音频取不到 → 媒体报 Format error」，**看起来像功能坏了**（实测假红）。
 *   ⇒ 点之前先确认窗口里有余量；真失败也只在**看起来是环境问题**时才重试。
 */
// （助手 `rateHeadroom` / `waitHeadroom` 已在 PHASE A 之前定义，此处不再重复）

const measureAudio = async () => {
  const raw = await run(`(()=>{
    const a=document.querySelector('.vc-preview audio')||document.querySelector('audio.vc-audio');
    const out={audio:!!a};
    if(a){
      const r=a.getBoundingClientRect(), cs=getComputedStyle(a);
      out.rect={w:Math.round(r.width),h:Math.round(r.height)};
      out.css={display:cs.display,visibility:cs.visibility};
      out.paused=a.paused; out.currentTime=a.currentTime; out.readyState=a.readyState;
      out.duration=(typeof a.duration==='number'&&isFinite(a.duration))?Math.round(a.duration*10)/10:null;
      out.src=a.getAttribute('src');
      out.err=a.error?{code:a.error.code,msg:a.error.message}:null;
    }
    out.errBanner=(document.querySelector('.ant-alert-error')||{}).textContent||null;
    return JSON.stringify(out);
  })()`)
  try { return JSON.parse(raw) } catch { return null }
}

let bClick = null
let BDJ = null
for (let attempt = 1; attempt <= 3; attempt++) {
  await waitHeadroom(10)
  bClick = await click(`(()=>{
    const strip=(s)=>(s||'').replace(/\\s+/g,'');
    const b=[...document.querySelectorAll('button')].find(x=>strip(x.textContent)==='试听');
    if(!b) return 'NO_BTN';
    if(b.disabled) return 'DISABLED';
    b.click(); return 'clicked';
  })()`)
  console.log(`  第 ${attempt} 次点击结果 =`, bClick)

  let st = null
  for (let i = 0; i < 70; i++) {
    await sleep(500)
    st = await run(`(()=>{
      const a=document.querySelector('.vc-preview audio')||document.querySelector('audio.vc-audio');
      const er=document.querySelector('.ant-alert-error');
      return JSON.stringify({audio:!!a, err:er?er.textContent.trim().slice(0,140):null,
        paused:a?a.paused:null, t:a?Math.round(a.currentTime*100)/100:null});
    })()`)
    try { const p = JSON.parse(st); if (p.audio || p.err) break } catch { /* ignore */ }
  }
  console.log('  试听轮询:', st)

  // play() 是异步的：不等一拍就量 paused 会量到加载瞬间（假红）
  await sleep(2800)
  BDJ = await measureAudio()
  console.log('  播放器快照:', JSON.stringify(BDJ))

  const notPlaying = !(BDJ?.audio && BDJ?.paused === false)
  // 只在「看起来是环境问题」时重试：没音频 / 媒体错误 / 错误横幅
  const looksEnvironmental = !BDJ?.audio || !!BDJ?.err || !!BDJ?.errBanner
  if (!notPlaying || !looksEnvironmental || attempt === 3) break
  console.log('  ↻ 本次像环境问题（无音频/媒体错误/错误横幅），重试一次')
  await sleep(3000)
}

// ★ 截图前滚到试听区：否则人眼看到的还是面板顶部，看不到播放器与「试听」按钮
await run(`(()=>{const p=document.querySelector('.vc-preview');if(p&&p.scrollIntoView)p.scrollIntoView({block:'center'});return 'scrolled'})()`)
await sleep(700)
await shot('04_after_audition.png')

const voiceNet = netLog.filter((n) => n.path.includes('/static/voice/'))
check('B9', '点完试听后播放器出现在 DOM', BDJ?.audio === true, !!BDJ?.audio)
check('B10', '播放器可见（rect 宽高 > 0）', (BDJ?.rect?.w ?? 0) > 0 && (BDJ?.rect?.h ?? 0) > 0 && BDJ?.css?.display !== 'none', BDJ?.rect)
check('B11', '音频真的取到了（/static/voice/ 命中 200/206）', voiceNet.some((n) => n.status === 200 || n.status === 206), voiceNet.map((n) => n.status))
check('B12', '音频元数据有效（duration > 0，不是坏文件）', typeof BDJ?.duration === 'number' && BDJ.duration > 0, BDJ?.duration)
check('B13', '★ 点完**已在播放**（paused=false）—— 无需再点一次播放', BDJ?.paused === false, { paused: BDJ?.paused, currentTime: BDJ?.currentTime })
check('B14', '播放进度真的在走（currentTime > 0）', (BDJ?.currentTime ?? 0) > 0, BDJ?.currentTime)
check('B15', '无错误横幅（失败被如实提示，不是静默）', !BDJ?.errBanner, String(BDJ?.errBanner || '').slice(0, 80))

// ── 桩是否真的生效过（A 段前提自检）──
console.log('\n--- 台架自检')
console.log('  被桩住的请求数 =', stubbed.length, JSON.stringify(stubbed.slice(0, 6)))
console.log('  /api/v1 响应状态分布 =', JSON.stringify(netLog.reduce((m, n) => { const k = n.path.replace(/\d+/g, ':id'); m[k] = m[k] || {}; m[k][n.status] = (m[k][n.status] || 0) + 1; return m }, {})))
check('Z1', 'A 段的 /accounts 桩真的被命中过（否则 A6/A7 的"页面留住"前提不成立）', stubbed.length > 0, stubbed.length)

if (pageErrors.length) {
  console.log('\n=== 页面运行期错误')
  for (const e of pageErrors.slice(0, 8)) console.log('  ' + e)
}

// ════════════════════════════════════════════════════════════════
const pass = checks.filter((c) => c.ok).length
const fail = checks.filter((c) => !c.ok)
console.log('\n===== 汇总 =====')
console.log(`  ${pass}/${checks.length} 通过`)
if (fail.length) for (const f of fail) console.log(`  FAIL ${f.id} ${f.label} → ${JSON.stringify(f.extra)}`)
console.log('  ★★ PASS=' + (fail.length === 0))
console.log('  ★★ EXIT ' + (fail.length === 0 ? 0 : 1))

ws.close()
chrome.kill()
clearTimeout(watchdog)
process.exit(fail.length === 0 ? 0 : 1)

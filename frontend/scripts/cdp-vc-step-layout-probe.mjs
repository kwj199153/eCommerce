// 验收「删除音色」是否真的落在步骤 3（创建音色），而不是步骤 4（试听）。
//
// 为什么必须真跑浏览器：`v-if="record.exists"` + popconfirm 包裹 + 卡片归属，
// 这些读源码「看起来对」，但只有真实 DOM 才知道按钮落在哪张卡片里、是否分行、
// 点击后到底弹不弹二次确认。
//
// 安全约束（极重要）：老板的音色已 ready，删除会**真删远端 + 释放配额**。
// 所以本探针：
//   · 只点「删除音色」触发 popconfirm，**绝不点「确定」**，只按「取消」关闭；
//   · 结束后比对音色状态，必须与开始时一致（没被误删）。
//   · 点击本身是安全的：按钮现在是 @confirm 触发，不弹框就不会执行删除。
//
// 用法：node scripts/cdp-vc-step-layout-probe.mjs
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9345
const HOME_URL = 'http://localhost:5173/'
const API = 'http://127.0.0.1:8000'
// 本机唯一有 ready 音色的店铺（实测 store_a498a7d5「亚马逊2」）
const SHOP_WITH_VOICE = 'store_a498a7d5'
const SHOT = 'D:/ai/_vc_step3_shot.png'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const el = () => String(Date.now() - t0).padStart(6) + 'ms'

let chrome
const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 240s，强制退出')
  try { chrome?.kill() } catch { /* ignore */ }
  process.exit(2)
}, 240000)
process.on('unhandledRejection', (e) => console.error('UNHANDLED REJECTION:', e))

async function voiceStatus(shop) {
  const r = await fetch(`${API}/api/v1/voice-clone/status`, { headers: { 'X-Shop-ID': shop } })
  return await r.json()
}

const statusBefore = await voiceStatus(SHOP_WITH_VOICE)
console.log('=== 0. 前置：店铺音色状态')
console.log('  ', JSON.stringify(statusBefore))
if (!statusBefore.ready) {
  console.log('  ⚠️ 该店铺没有 ready 音色 —— 删除按钮根本不会渲染，本探针失去判别力')
  console.log('  ★★ VERDICT layout=false popconfirm=false stateKept=false')
  console.log('  ★★ PASS=false')
  process.exit(1)
}

const profile = mkdtempSync(join(tmpdir(), 'cdp-vcstep-'))
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
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails
    pageErrors.push(String(d.exception?.description || d.text || '').slice(0, 400))
  }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    pageErrors.push('[console.error] ' + m.params.args.map((a) => String(a.value ?? a.description ?? '')).join(' ').slice(0, 300))
  }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise((res) => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  const ex = r.result?.exceptionDetails
  if (ex) return 'EXC: ' + String(ex.exception?.description || ex.text || '').slice(0, 400)
  return r.result?.result?.value
}

await send('Page.enable')
await send('Runtime.enable')

// 店铺必须在应用初始化前落 localStorage：currentShopId 是 ref 初值，
// 晚设不会重新触发面板的 fetchVoiceStatus（面板只在 onMounted 拉一次）。
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `try{localStorage.setItem('current_shop_id', ${JSON.stringify(SHOP_WITH_VOICE)})}catch(e){}`,
})

console.log('\n=== 1. 打开应用（店铺锁定 ' + SHOP_WITH_VOICE + '）')
await send('Page.navigate', { url: HOME_URL })
await sleep(10000)
for (let i = 0; i < 3; i++) {
  const len = await run('document.body?.textContent?.length || 0')
  if (typeof len === 'number' && len > 300) break
  console.log('  retry reload, len=', len)
  await send('Page.reload')
  await sleep(8000)
}

console.log('\n=== 2. 打开设置抽屉 + 切「客服语音」Tab')
await run(`window.dispatchEvent(new CustomEvent('open-settings-drawer'))`)
await sleep(4000)
console.log('  ', await run(`(()=>{const t=[...document.querySelectorAll('.ant-tabs-tab')].find(e=>e.textContent.includes('客服语音'));if(!t)return 'NO_TAB';t.click();return 'clicked'})()`))
await sleep(4000)

// ── 3. 控件归属：按钮属于哪张卡片 ────────────────────────────────────────
console.log('\n=== 3. 量测控件归属（按钮落在哪张步骤卡里）')
const layout = await run(`(()=>{
  const cardTitle=(el)=>{const c=el&&el.closest('.vc-card');if(!c)return null;const t=c.querySelector('.ant-card-head-title');return t?t.textContent.trim().replace(/\\s+/g,' '):'(无标题)'};
  const btn=(re)=>[...document.querySelectorAll('button')].find(b=>re.test(b.textContent));
  const del=btn(/^删除音色$/);
  const pv=btn(/生成试听/);
  const en=btn(/开始克隆|已有可用音色/);
  const rect=(e)=>{if(!e)return null;const r=e.getBoundingClientRect();return {top:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height)}};
  return JSON.stringify({
    cardCount: document.querySelectorAll('.vc-card').length,
    cardTitles: [...document.querySelectorAll('.vc-card .ant-card-head-title')].map(e=>e.textContent.trim().replace(/\\s+/g,' ')),
    del: del? {text:del.textContent.trim(), inCard:cardTitle(del), danger:del.classList.contains('ant-btn-dangerous'), primary:del.classList.contains('ant-btn-primary'), disabled:del.disabled, rect:rect(del), popParent: !!(del.closest('.ant-popconfirm')||del.parentElement&&del.parentElement.className.includes('popconfirm'))} : null,
    pv:  pv?  {text:pv.textContent.trim(),  inCard:cardTitle(pv),  disabled:pv.disabled, rect:rect(pv)} : null,
    enroll: en? {text:en.textContent.trim(), inCard:cardTitle(en), disabled:en.disabled, rect:rect(en)} : null,
    dangerRowExists: !!document.querySelector('.vc-danger-row'),
    dangerRowParentCard: (()=>{const d=document.querySelector('.vc-danger-row');return d?cardTitle(d):null})(),
  },null,1);
})()`)
console.log(String(layout))

let Lnow = null
try { Lnow = JSON.parse(layout) } catch { /* ignore */ }

// ── 4. 点删除按钮 → 必须弹二次确认（且此刻不能真删）────────────────────
// ⚠️⚠️ 血泪防护（2026-09-15 实测事故）：本探针的点击在**修复前版本**上是破坏性的 ——
//   旧代码的按钮是 `@click="handleDelete"`（点击即执行删除），不是 @confirm。
//   上一轮做反向注入时切回旧版本跑本探针，直接把老板的真实音色删了（远端配额一并释放，日志
//   `已删除音色记录 shop=store_a498a7d5 remote_deleted=True`）。
//   ⇒ 两道闸：① `--readonly` 显式只读；② 没看到 .vc-danger-row（修复后才有的标记）就拒绝点击。
const READONLY = process.argv.includes('--readonly')
console.log('\n=== 4. 点「删除音色」→ 断言弹出确认框（绝不点确定）')
let pop
if (READONLY) {
  console.log('  (--readonly：跳过点击)')
  pop = JSON.stringify({ exists: false, skipped: true })
} else if (!Lnow?.dangerRowExists) {
  console.log('  ⚠️ 未检测到 .vc-danger-row —— 当前很可能是「点击即删」的旧版本，拒绝点击（防止误删真实音色）')
  pop = JSON.stringify({ exists: false, refused: true })
} else {
  console.log('  ', await run(`(()=>{
  const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='删除音色');
  if(!b) return 'NO_BTN';
  b.scrollIntoView({block:'center'});
  b.click(); return 'clicked';
})()`))
  await sleep(1500)
  pop = await run(`(()=>{
  const p=document.querySelector('.ant-popover');
  if(!p) return JSON.stringify({exists:false});
  const btns=[...p.querySelectorAll('button')].map(b=>b.textContent.trim());
  return JSON.stringify({exists:true, hidden:p.classList.contains('ant-popover-hidden'), text:p.textContent.trim().replace(/\\s+/g,' ').slice(0,140), btns});
})()`)
}
console.log('  ', pop)

console.log('\n=== 5. 关闭确认框（点取消，不点确定）')
// ⚠️ antd 中文 locale 会给两字按钮插空格（实际渲染成「取 消」「确 定」），
//    直接 /取消/ 匹配不上 ⇒ 必须剥掉空白再匹配。踩过一次：浮层关不掉、后续截图被遮挡。
console.log('  ', await run(`(()=>{
  const p=document.querySelector('.ant-popover');
  if(!p) return 'NO_POP';
  const btns=[...p.querySelectorAll('button')];
  const c=btns.find(b=>/^(取消|Cancel)$/i.test(b.textContent.replace(/\\s+/g,'')));
  if(c){c.click();return 'cancel-clicked'}
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,bubbles:true}));
  return 'esc-sent(none-of:'+btns.map(b=>b.textContent.replace(/\\s+/g,'')).join('|')+')';
})()`))
await sleep(1200)
const popClosed = await run(`!document.querySelector('.ant-popover:not(.ant-popover-hidden)')`)
console.log('  浮层已关闭 = ' + popClosed)
if (!popClosed) {
  // 兜底：再点一次取消，避免浮层残留污染截图
  console.log('  ', await run(`(()=>{const p=document.querySelector('.ant-popover');if(!p)return 'gone';const c=[...p.querySelectorAll('button')].find(b=>/^(取消|Cancel)$/i.test(b.textContent.replace(/\\s+/g,'')));if(c){c.click();return 'cancel-clicked-2'}return 'still-open'})()`))
  await sleep(1000)
}

// ── 6. 事后：音色必须还在（没被误删）──────────────────────────────────
const statusAfter = await voiceStatus(SHOP_WITH_VOICE)
const uiAfter = await run(`(()=>{
  const ok=document.querySelector('.ant-alert-success');
  return JSON.stringify({readyAlert:!!ok, text:ok?ok.textContent.trim().replace(/\\s+/g,' ').slice(0,90):null, delBtnStill:!![...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='删除音色'), popGone:!document.querySelector('.ant-popover:not(.ant-popover-hidden)')});
})()`)
console.log('\n=== 6. 事后核对（音色必须还在）')
console.log('  后端 status:', JSON.stringify(statusAfter))
console.log('  UI:', uiAfter)

// ── 7. 截图 ────────────────────────────────────────────────────────────
console.log('\n=== 7. 截图（步骤 3 + 步骤 4 交界处）')
await run(`(()=>{
  const d=document.querySelector('.vc-danger-row');
  if(d) d.scrollIntoView({block:'center'});
  return 'scrolled'
})()`)
await sleep(900)
const shot = await send('Page.captureScreenshot', { format: 'png' })
if (shot.result?.data) { writeFileSync(SHOT, Buffer.from(shot.result.data, 'base64')); console.log('  已写 ' + SHOT) }
else console.log('  截图失败:', JSON.stringify(shot).slice(0, 200))

if (pageErrors.length) { console.log('\n=== 页面错误'); for (const e of pageErrors.slice(0, 6)) console.log('  ' + e) }

// ======================= 判定 =======================
let L = null
try { L = JSON.parse(layout) } catch { /* ignore */ }
let P = null
try { P = JSON.parse(pop) } catch { /* ignore */ }

const delInStep3 = !!L?.del && String(L.del.inCard || '').includes('3')
const delNotStep4 = !!L?.del && !String(L.del.inCard || '').includes('4')
const pvInStep4 = !!L?.pv && String(L.pv.inCard || '').includes('4')
// 与主操作分行：删除按钮 top 明显大于「开始克隆」top（不是并排）
const stacked = !!(L?.del?.rect && L?.enroll?.rect && L.del.rect.top - L.enroll.rect.top > 20)
// 删除按钮必须在试听按钮上方（顺序：步骤 3 在步骤 4 之前）
const orderOk = !!(L?.del?.rect && L?.pv?.rect && L.del.rect.top < L.pv.rect.top)
const popconfirmOk = !!P?.exists
const stateKept = statusAfter.ready === true && statusAfter.voice_id === statusBefore.voice_id

console.log('\n=== 汇总')
console.log('  卡片标题 = ' + JSON.stringify(L?.cardTitles || []))
console.log('  删除音色   → 所属卡片 ' + JSON.stringify(L?.del?.inCard ?? null) + '  danger=' + (L?.del?.danger ?? '-'))
console.log('  生成试听   → 所属卡片 ' + JSON.stringify(L?.pv?.inCard ?? null))
console.log('  开始克隆   → 所属卡片 ' + JSON.stringify(L?.enroll?.inCard ?? null) + '  top=' + (L?.enroll?.rect?.top ?? '-'))
console.log('  垂直位置：开始克隆 ' + (L?.enroll?.rect?.top ?? '-') + ' / 删除音色 ' + (L?.del?.rect?.top ?? '-') + ' / 生成试听 ' + (L?.pv?.rect?.top ?? '-'))
console.log('  .vc-danger-row 存在 = ' + (L?.dangerRowExists ?? '-'))
console.log('  二次确认弹框 = ' + (P?.exists ?? false) + ' 内容=' + JSON.stringify(P?.text ?? null))
console.log('  音色仍在（后端）= ' + statusAfter.ready + ' voice_id=' + statusAfter.voice_id)
console.log(
  '  ★★ VERDICT layout=' + (delInStep3 && delNotStep4 && pvInStep4) +
  ' stack=' + stacked +
  ' order=' + orderOk +
  ' popconfirm=' + popconfirmOk +
  ' dangerRow=' + !!L?.dangerRowExists +
  ' stateKept=' + stateKept +
  (READONLY ? ' mode=readonly' : ' mode=interactive'),
)
const pass = delInStep3 && delNotStep4 && pvInStep4 && stacked && orderOk && popconfirmOk && !!L?.dangerRowExists && stateKept
console.log('  ★★ PASS=' + pass)
console.log('  ★★ EXIT ' + (pass ? 0 : 1))

ws.close()
chrome.kill()
clearTimeout(watchdog)
process.exit(pass ? 0 : 1)

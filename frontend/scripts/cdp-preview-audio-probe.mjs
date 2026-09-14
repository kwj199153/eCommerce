// CDP 复现「生成试听只有文字、没有语音播放器」。
//
// 为什么必须真跑浏览器：后端 `POST /voice-clone/preview` 实测 HTTP 200 且返回
// `audio_url=/static/voice/tts-*.mp3`（80KB 真 MP3，5173 代理取得到）。
// 也就是说「后端没返回音频」这个假设**已经被证伪**，只剩渲染/可见性问题 ——
// 那必须看真实 DOM 与真实截图，读代码判不出来。
//
// 量测项：
//   ① 面板是否出现 .vc-preview（= previewUrl 有值）
//   ② <audio> 是否真的在 DOM 里、有没有被 CSS 压成 0 高 / 隐藏
//   ③ audio.src 是什么、音频请求的真实 HTTP 状态
//   ④ 截图一张（人眼对照老板看到的东西）
//
// 用法：node scripts/cdp-preview-audio-probe.mjs
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9341
const HOME_URL = 'http://localhost:5173/'
// 本机唯一有 ready 音色的店铺（实测 store_a498a7d5「亚马逊2」）
const SHOP_WITH_VOICE = 'store_a498a7d5'
const SHOT = 'D:/ai/_preview_shot.png'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const t0 = Date.now()
const el = () => String(Date.now() - t0).padStart(6) + 'ms'

const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 240s，强制退出')
  try { chrome.kill() } catch { /* ignore */ }
  process.exit(2)
}, 240000)
process.on('unhandledRejection', (e) => console.error('UNHANDLED REJECTION:', e))

const profile = mkdtempSync(join(tmpdir(), 'cdp-prev-'))
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
    'about:blank',
  ],
  { stdio: 'ignore' }
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
const netLog = []
const pageErrors = []
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails
    pageErrors.push(String(d.exception?.description || d.text || '').slice(0, 400))
    return
  }
  if (m.method === 'Network.responseReceived') {
    const u = m.params.response.url
    if (u.includes('/static/voice/')) netLog.push({ at: el(), status: m.params.response.status, mime: m.params.response.mimeType, url: u.split('/').pop() })
  }
  if (m.method === 'Runtime.consoleAPICalled') {
    const s = m.params.args.map((a) => String(a.value ?? a.description ?? '')).join(' ')
    if (/voice|speak|preview|audio/i.test(s)) console.log('  [page] ' + s.slice(0, 220))
    if (m.params.type === 'error') pageErrors.push('[console.error] ' + s.slice(0, 300))
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
await send('Network.enable')

// ★ 店铺必须在应用初始化之前就落进 localStorage：currentShopId 是 ref 初值，
//   晚设不会重新触发面板的 fetchVoiceStatus（面板只在 onMounted 拉一次）。
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: `try{localStorage.setItem('current_shop_id', ${JSON.stringify(SHOP_WITH_VOICE)})}catch(e){}`,
})

console.log('=== 1. 打开 ' + HOME_URL + '（店铺锁定 ' + SHOP_WITH_VOICE + ' 亚马逊2）')
await send('Page.navigate', { url: HOME_URL })
await sleep(10000)
for (let i = 0; i < 3; i++) {
  const len = await run('document.body?.textContent?.length || 0')
  if (typeof len === 'number' && len > 300) break
  console.log('  retry reload, len=', len)
  await send('Page.reload')
  await sleep(8000)
}
console.log('  ', await run(`JSON.stringify({href:location.pathname, appLen:(document.querySelector('#app')||{}).innerHTML?.length||0, tabs:document.querySelectorAll('.ant-tabs-tab').length})`))
if (pageErrors.length) { console.log('  页面错误：'); for (const e of pageErrors.slice(0, 6)) console.log('    ' + e) }

console.log('\n=== 2. 打开设置抽屉（Workspace 监听的自定义事件 open-settings-drawer）')
console.log('  ', await run(`(()=>{window.dispatchEvent(new CustomEvent('open-settings-drawer')); return 'dispatched';})()`))
await sleep(4000)
console.log('  ', await run(`JSON.stringify({drawerOpen:!!document.querySelector('.ant-drawer-open'), tabs:[...document.querySelectorAll('.ant-tabs-tab')].map(e=>e.textContent.trim())})`))

console.log('\n=== 3. 切到「客服语音」Tab')
console.log('  ', await run(`(()=>{
  const t=[...document.querySelectorAll('.ant-tabs-tab')].find(e=>e.textContent.includes('客服语音'));
  if(!t) return 'NO_TAB';
  t.click(); return 'clicked';
})()`))
await sleep(3000)

const panelState = () => run(`(()=>{
  const btns=[...document.querySelectorAll('button')];
  const pv=btns.find(b=>b.textContent.includes('生成试听'));
  const warn=document.querySelector('.vc-hint-warn');
  return JSON.stringify({
    hasPanel: !!document.querySelector('.vc-preview, .vc-audio, .vc-hint'),
    previewBtn: pv? {disabled:pv.disabled, loading:pv.classList.contains('ant-btn-loading'), text:pv.textContent.trim()} : null,
    warn: warn? warn.textContent.trim().slice(0,90) : null,
  });
})()`)
console.log('  面板状态:', await panelState())

console.log('\n=== 4. 点「生成试听」')
console.log('  ', await run(`(()=>{
  const pv=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('生成试听'));
  if(!pv) return 'NO_BTN';
  if(pv.disabled) return 'BTN_DISABLED';
  pv.click(); return 'clicked';
})()`))

console.log('\n=== 5. 等试听结果落地')
let st = null
for (let i = 0; i < 60; i++) {
  await sleep(500)
  st = await run(`(()=>{
    const a=document.querySelector('audio.vc-audio');
    const er=document.querySelector('.ant-alert-error');
    return JSON.stringify({audio:!!a, src:a?(a.currentSrc||a.getAttribute('src')||''):null, err:er?er.textContent.trim().slice(0,120):null, btn:!![...document.querySelectorAll('button')].find(b=>b.textContent.includes('生成试听'))});
  })()`)
  try { const p = JSON.parse(st); if (p.audio || p.err) break } catch { /* ignore */ }
}
console.log('  ', st)

console.log('\n=== 6. 量测 <audio> 真实可见性')
const dump = await run(`(()=>{
  const wrap=document.querySelector('.vc-preview');
  const a=document.querySelector('.vc-preview audio') || document.querySelector('audio.vc-audio');
  const out={wrapExists:!!wrap};
  if(wrap){
    const wc=getComputedStyle(wrap), wr=wrap.getBoundingClientRect();
    out.wrap={w:Math.round(wr.width),h:Math.round(wr.height),display:wc.display,flexDir:wc.flexDirection};
    out.wrapHTML=wrap.outerHTML.slice(0,400);
  }
  if(a){
    const cs=getComputedStyle(a), r=a.getBoundingClientRect();
    out.audio={rect:{w:Math.round(r.width),h:Math.round(r.height)},client:{w:a.clientWidth,h:a.clientHeight},
      css:{display:cs.display,visibility:cs.visibility,opacity:cs.opacity,height:cs.height,width:cs.width,flex:cs.flex},
      controls:a.controls, readyState:a.readyState, networkState:a.networkState, duration:a.duration,
      paused:a.paused, src:a.getAttribute('src'), currentSrc:a.currentSrc,
      err:a.error?{code:a.error.code,msg:a.error.message}:null,
      offsetParent: !!a.offsetParent};
  } else { out.audio=null; }
  out.hint=(document.querySelector('.vc-preview .vc-hint')||{}).textContent||'(无)';
  out.voiceReq=performance.getEntriesByType('resource').filter(e=>e.name.includes('/static/voice/'))
    .map(e=>({n:e.name.split('/').pop(),size:e.transferSize,dur:Math.round(e.duration),status:e.responseStatus}));
  return JSON.stringify(out,null,1);
})()`)
console.log(String(dump))

console.log('\n=== 7. 截图（人眼对照）')
await run(`(()=>{
  const b=document.querySelector('.ant-drawer-body');
  if(b) b.scrollTop=b.scrollHeight;
  const p=document.querySelector('.vc-preview');
  if(p&&p.scrollIntoView) p.scrollIntoView({block:'center'});
  return 'scrolled';
})()`)
await sleep(900)
const shot = await send('Page.captureScreenshot', { format: 'png' })
if (shot.result?.data) { writeFileSync(SHOT, Buffer.from(shot.result.data, 'base64')); console.log('  已写 ' + SHOT) }
else console.log('  截图失败:', JSON.stringify(shot).slice(0, 200))

console.log('\n=== 8. 音频请求真实状态（Network 域）')
if (netLog.length === 0) console.log('  (无 /static/voice/ 请求到达网络层)')
for (const n of netLog) console.log(`  ${n.at} HTTP ${n.status} ${n.mime} ${n.url}`)

if (pageErrors.length) { console.log('\n=== 页面运行期错误'); for (const e of pageErrors.slice(0, 8)) console.log('  ' + e) }

// ======================= 判定 =======================
const parsed = (() => { try { return JSON.parse(dump) } catch { return null } })()
const a = parsed?.audio
const visible = !!(a && a.rect.w > 0 && a.rect.h > 0 && a.css.display !== 'none' && a.css.visibility !== 'hidden')
const hasReq = netLog.some((n) => n.status === 200 || n.status === 206)
const errText = (() => { try { return JSON.parse(st).err } catch { return null } })()

console.log('\n=== 汇总')
console.log('  wrapExists = ' + (parsed?.wrapExists ?? 'n/a'))
console.log('  audio 在 DOM = ' + !!a)
if (a) console.log('  audio 尺寸 = ' + a.rect.w + 'x' + a.rect.h + ' css.height=' + a.css.height + ' display=' + a.css.display + ' visibility=' + a.css.visibility)
console.log('  audio 可加载 = readyState=' + (a?.readyState ?? '-') + ' duration=' + (a?.duration ?? '-') + ' loadErr=' + JSON.stringify(a?.err ?? null))
console.log('  音频 HTTP = ' + JSON.stringify(netLog.map((n) => n.status)))
console.log('  页内错误条 = ' + (errText || '(无)'))
console.log('  ★★ VERDICT preview audioInDom=' + !!a + ' visible=' + visible + ' netOk=' + hasReq + ' duration=' + (a?.duration ?? '-'))

// ★ 判定必须落到**退出码**上：只打印 VERDICT 而恒 exit 0，等于「FAIL 了但 CI 绿」——
//   那是假绿的另一面（反向注入时实测到过：visible=false 而 EXIT=0）。
const playable = typeof a?.duration === 'number' && a.duration > 0
const pass = !!a && visible && hasReq && playable
console.log('  ★★ PASS=' + pass + '（要求：在 DOM + 可见 + 音频 HTTP 200/206 + duration>0）')
console.log('  ★★ EXIT ' + (pass ? 0 : 1))

ws.close()
chrome.kill()
clearTimeout(watchdog)
process.exit(pass ? 0 : 1)

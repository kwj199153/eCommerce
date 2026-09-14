// CDP 验证「语音播报本轮闸门」：只念**刚被提问的那个对话区**的回复。
//
// 为什么需要这个探针（而不是靠读代码判断）：
//   闸门要拦掉的两件事都是**时序相关**的，代码看起来没问题不代表真被拦住：
//     ① 开屏欢迎语 —— 它是 assistant 消息、前面没有 user 消息，照样可能被念出来；
//     ② 切面板回来 —— activeAgentId 一变 watch 就触发，读到的却是历史回复。
//   反过来，闸门写狠了会把功能整个打死（永远不念），所以必须有**正向对照**。
//
// 三段：
//   A. 冷启动观察（不碰 store）      → 历史/无提问的 assistant 消息**不许出声**
//   B. 正向对照（user + assistant）  → 刚提问后的回复**必须出声**   ← 防「修成永不播报」
//   C. 切面板往返                    → 不许重复出声（回归护栏）
//
// 诚实边界：真实浏览器 / 真实 store / 真实后端 `/speak-plan` / 真实 Web Audio；
//   只桩 `/voice-clone/speak`（DashScope 合成）与 `/voice-clone/status`（音色体检），
//   因为本机当前店铺没有已审核通过的音色。
//
// 用法：
//   node scripts/cdp-tts-gate-probe.mjs
//   （配 scripts/_flip_tts_gate.cjs prefix 可切到修复前版本，验证本探针**确实抓得住**这个 bug）
import { spawn } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9339
const APP_URL = 'http://localhost:5173/'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const SYNTH_FIXED_MS = 900
const SYNTH_PER_CHAR_MS = 25
const PLAY_PER_CHAR_MS = 200

/** 正向对照用的正文：短一点，探针跑得快；三段句 ⇒ 计划器切 2~3 段 */
const TEXT = '这周广告花费涨了三成，主要原因是自动广告转化率下滑。建议暂停两个最差的词组。另外主图点击率低于类目均值，本周换一版。'

function wavSilence(seconds, sampleRate = 16000) {
  const n = Math.max(1, Math.round(seconds * sampleRate))
  const dataLen = n * 2
  const buf = Buffer.alloc(44 + dataLen)
  buf.write('RIFF', 0)
  buf.writeUInt32LE(36 + dataLen, 4)
  buf.write('WAVE', 8)
  buf.write('fmt ', 12)
  buf.writeUInt32LE(16, 16)
  buf.writeUInt16LE(1, 20)
  buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(sampleRate, 24)
  buf.writeUInt32LE(sampleRate * 2, 28)
  buf.writeUInt16LE(2, 32)
  buf.writeUInt16LE(16, 34)
  buf.write('data', 36)
  buf.writeUInt32LE(dataLen, 40)
  return buf
}

const jsonBody = (obj) => Buffer.from(JSON.stringify(obj), 'utf8').toString('base64')
const t0All = Date.now()
const el = () => String(Date.now() - t0All).padStart(6) + 'ms'

const stubLog = []
function resolveStub(url, post) {
  // ★ `/speak-plan` 放行给真后端（纯计算 0.22ms）。匹配顺序：先判它，
  //   否则会被 `*voice-clone/speak` 模式吞掉。
  if (url.includes('/voice-clone/speak-plan')) return null
  if (url.includes('/voice-clone/status')) {
    return { json: { exists: true, status: 'ready', ready: true, error_msg: '' } }
  }
  if (url.includes('/voice-clone/speak')) {
    const txt = (post && post.text) || ''
    const chars = [...txt].length
    const waitMs = SYNTH_FIXED_MS + SYNTH_PER_CHAR_MS * chars
    const playMs = Math.max(400, PLAY_PER_CHAR_MS * chars)
    stubLog.push({ at: el(), chars, head: txt.slice(0, 24) })
    console.log(`  ${el()} [stub /speak] chars=${chars} «${txt.slice(0, 24)}»`)
    return {
      delay: waitMs,
      json: {
        audio_url: 'data:audio/wav;base64,' + wavSilence(playMs / 1000).toString('base64'),
        spoken_text: txt,
        model: 'stub',
        truncated: false,
        source_chars: chars,
        expires_hint: 'stub',
      },
    }
  }
  return null
}

// ======================= 启动 Chrome + 连 CDP =======================
const profile = mkdtempSync(join(tmpdir(), 'cdp-gate-'))
const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 240s 未结束，强制退出')
  try { chrome.kill() } catch { /* ignore */ }
  process.exit(2)
}, 240000)
process.on('unhandledRejection', (e) => console.error('UNHANDLED REJECTION:', e))

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
    '--autoplay-policy=no-user-gesture-required',
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
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) {
  console.log('FAIL: no page')
  chrome.kill()
  process.exit(1)
}

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
const consoleLogs = []
ws.addEventListener('message', async (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m)
    pending.delete(m.id)
    return
  }
  if (m.method === 'Runtime.consoleAPICalled') {
    const s = m.params.args.map((a) => String(a.value ?? a.description ?? '')).join(' ')
    if (s.includes('voice-tts')) consoleLogs.push(s.slice(0, 300))
    return
  }
  if (m.method === 'Fetch.requestPaused') {
    const p = m.params
    let post = null
    if (p.request.postData) {
      try { post = JSON.parse(p.request.postData) } catch { /* 非 JSON */ }
    }
    const hit = resolveStub(p.request.url, post)
    if (!hit) {
      // 放行必须显式回带 postData，否则 Chrome 会丢 body（`/speak-plan` 收到空 body → 422）
      await send('Fetch.continueRequest', {
        requestId: p.requestId,
        ...(p.request.postData ? { postData: p.request.postData } : {}),
      })
      return
    }
    if (hit.delay) await sleep(hit.delay)
    await send('Fetch.fulfillRequest', {
      requestId: p.requestId,
      responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }],
      body: jsonBody(hit.json),
    })
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
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  const ex = r.result?.exceptionDetails
  if (ex) return 'EXC: ' + String(ex.exception?.description || ex.text || '').slice(0, 300)
  return r.result?.result?.value
}

await send('Page.enable')
await send('Runtime.enable')
await send('Fetch.enable', {
  patterns: [
    { urlPattern: '*voice-clone/speak', requestStage: 'Request' },
    { urlPattern: '*voice-clone/status*', requestStage: 'Request' },
  ],
})
// 开关必须在 store 初始化之前就为 true（readEnabled() 只在 store 首次创建时读一次）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: "try{localStorage.setItem('voice_tts_enabled','true')}catch(e){}",
})
await send('Page.navigate', { url: APP_URL })
await sleep(12000)
for (let i = 0; i < 3; i++) {
  const len = await run('document.body?.textContent?.length || 0')
  if (len > 200) break
  console.log('retry reload, len=', len)
  await send('Page.reload')
  await sleep(8000)
}

const readState = () =>
  run(`(()=>{
  const chat=window.__chat, tts=window.__tts;
  const l=chat.messages||[];
  const last=l[l.length-1];
  return JSON.stringify({
    active:chat.activeAgentId, n:l.length,
    lastRole:last&&last.role, lastHead:last?String(last.content||'').slice(0,18):'',
    supports:tts.supports(chat.activeAgentId), enabled:tts.enabled, phase:tts.phase,
    metrics:tts.lastRunMetrics,
  });
})()`)

console.log('=== 0. 取 store（★ 故意**不**切走对话区：本探针要的正是开屏现场）')
console.log(
  '  ',
  await run(`(()=>{
  const el=document.querySelector('#app');
  const app=el&&el.__vue_app__;
  const pinia=app&&app.config.globalProperties&&app.config.globalProperties.$pinia;
  if(!pinia||!pinia._s) return 'NO_PINIA';
  const tts=pinia._s.get('voiceTts'); const chat=pinia._s.get('chat');
  if(!tts||!chat) return 'NO_TTS_OR_CHAT';
  window.__pinia=pinia; window.__tts=tts; window.__chat=chat;
  return JSON.stringify({tts:!!tts, chat:!!chat, enabled:tts.enabled});
})()`)
)

// ======================= A. 冷启动：历史消息不许出声 =======================
console.log('\n=== A. 冷启动观察（不动 store；开屏 welcome 已落库，看是否被念）')
const stA = await readState()
console.log('  ', stA)
const A = JSON.parse(stA)
const preOk =
  A.lastRole === 'assistant' && A.n > 0 && A.supports === true && A.enabled === true && A.active === 'secretary'
const spokeA = stubLog.length
const runKeyA = A.metrics ? String(A.metrics.runKey) : ''
const histOk = spokeA === 0 && !runKeyA.startsWith('secretary#')
console.log(`  前置条件 preOk=${preOk}（要求：活跃对话区=secretary、最后一条是 assistant 消息、白名单命中、开关已开）`)
console.log(`  判定 histOk=${histOk}（要求：/speak 调用 0 次，且本轮无 secretary 播报；实测 /speak=${spokeA} runKey=«${runKeyA}»）`)

// ======================= B. 正向对照：刚提问后的回复必须出声 =======================
console.log('\n=== B. 正向对照：先落 user 消息，再落 assistant 消息')
await run(`(()=>{window.__chat.addMessage({role:'user',content:'（探针）把这段念给我听'});return 'ok'})()`)
await sleep(150)
const nBeforeB = stubLog.length
await run(`(()=>{window.__chat.addMessage({role:'assistant',content:${JSON.stringify(TEXT)}});return 'ok'})()`)
let stB = null
for (let i = 0; i < 100; i++) {
  await sleep(400)
  stB = JSON.parse(await readState())
  if (stB.metrics && String(stB.metrics.runKey).startsWith('secretary#') && stB.phase === 'idle') break
}
const B = stB
console.log('  ', JSON.stringify({ metrics: B.metrics, phase: B.phase }))
const runKeyB = B.metrics ? String(B.metrics.runKey) : ''
const liveOk = runKeyB.startsWith('secretary#') && stubLog.length > nBeforeB
console.log(`  判定 liveOk=${liveOk}（要求：本轮 runKey 以 secretary# 开头且 /speak 有新增；实测 /speak +${stubLog.length - nBeforeB}）`)

// ======================= C. 切面板往返：不许重复出声 =======================
console.log('\n=== C. 切面板往返（secretary → product-research → secretary）')
const nBeforeC = stubLog.length
const runKeyC = runKeyB
await run(`window.__chat.setActiveAgent('product-research')`)
await sleep(600)
await run(`window.__chat.setActiveAgent('secretary')`)
await sleep(3500)
const stC = JSON.parse(await readState())
const runKeyC2 = stC.metrics ? String(stC.metrics.runKey) : ''
const switchOk = runKeyC2 === runKeyC && stubLog.length === nBeforeC
console.log(`  判定 switchOk=${switchOk}（要求：runKey 不变且 /speak 无新增；实测 runKey «${runKeyC2}» /speak +${stubLog.length - nBeforeC}）`)

// ======================= 汇总 =======================
const overall = preOk && histOk && liveOk && switchOk
console.log('\n=== 汇总')
console.log('  A 历史消息不出声 histOk = ' + histOk)
console.log('  B 刚提问后的回复出声 liveOk = ' + liveOk + '（正向对照，防「修成永不播报」）')
console.log('  C 切面板往返不重复 switchOk = ' + switchOk)
console.log('  ★★ VERDICT gate overall=' + overall + ' preOk=' + preOk +
  ' histOk=' + histOk + ' liveOk=' + liveOk + ' switchOk=' + switchOk)
if (consoleLogs.length) {
  console.log('  页面内自报指标：')
  for (const l of consoleLogs) console.log('    ' + l)
}
ws.close()
chrome.kill()
clearTimeout(watchdog)
await sleep(300)
process.exit(overall ? 0 : 1)

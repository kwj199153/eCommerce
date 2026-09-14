// CDP 量测「分句流水线」播报：首声延迟 + 段间间隙（验收指标 <50ms）。
//
// 诚实边界（别把这当成真实端到端）：
//   ✅ 真实：真实浏览器、真实 store 代码、真实后端 `POST /voice-clone/speak-plan`、
//      真实 Web Audio 调度与解码、真实时间轴。
//   ⛔ 打桩：`/voice-clone/speak`（DashScope 合成）、`/voice-clone/status`（音色体检）、
//      `/orchestrator/chat`。原因：当前店铺没有已审核通过的音色，真跑要先录样本 +
//      等远端审核，不是本机能自主完成的。
//      桩**按上一轮实测常数**延迟：合成 ≈ 900ms 固定 + 25ms/字、播放 ≈ 200ms/字
//      ⇒ 首声的绝对值可以照搬到真实链路（真实链路还要再加 T_llm）。
//
// 四个部分：
//   ① 时钟健康：AudioContext 是否 running、currentTime 是否推进（headless 前提）
//   ② 基线：旧路径 = 等正文说完 → 整段合成一次（= 首声下限）
//   ③ 新路径：分句流水线（模拟流式喂入）→ 首声 + 逐段间隙
//   ④ 真实编排层：往 chat store 压 assistant 消息，验证 watch → feed 真的接上了
//
// 用法：node scripts/cdp-tts-pipeline-measure.mjs
import { spawn } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9337
const APP_URL = 'http://localhost:5173/'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * 快速模式（`TTS_FAST=1`）：只跑 ③（流水线 + 不变量）。
 * 用途是**反向注入验证** —— 注入一个错误实现后，只需要看这一条不变量是否变红，
 * 没必要再跑基线与编排层那两段（省 30s+）。
 */
const FAST = !!process.env.TTS_FAST

// ---- 实测常数（`.workbuddy/probes/_probe_tts_latency.py`）----
const SYNTH_FIXED_MS = 900
const SYNTH_PER_CHAR_MS = 25
const PLAY_PER_CHAR_MS = 200

const TEXT =
  '老板，我看了这家店最近一周的广告投放数据，整体情况是广告花费上涨了大约三成。\n\n' +
  '主要原因是自动广告的转化率下滑，同时竞价成本上升了百分之十八。\n\n' +
  '建议先把表现最差的两个关键词组暂停，把预算集中到三个高转化的手动广告组。\n\n' +
  '另外主图的点击率低于同类目均值，建议本周内换一版主图再观察三天。'

// ---- 极简 WAV 编码器（16kHz 单声道 16bit 静音）----
// 静音就够：量的是**时长**与**调度时刻**，不是音色。
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
let planHits = 0
function resolveStub(url, post) {
  // ★ `/speak-plan` **必须放行给真后端**：它是纯计算端点（0.22ms），而且是本次要验证的
  //   核心（切句规则的后端唯一真源）。注意匹配顺序 —— 桩模式 `*voice-clone/speak*`
  //   会连 `speak-plan` 一起吃掉，所以这一条必须排在最前。
  if (url.includes('/voice-clone/speak-plan')) {
    planHits += 1
    return null
  }
  if (url.includes('/voice-clone/status')) {
    return { json: { exists: true, status: 'ready', ready: true, error_msg: '' } }
  }
  if (url.includes('/voice-clone/speak')) {
    const txt = (post && post.text) || ''
    const chars = [...txt].length
    const waitMs = SYNTH_FIXED_MS + SYNTH_PER_CHAR_MS * chars
    const playMs = Math.max(400, PLAY_PER_CHAR_MS * chars)
    stubLog.push({ at: el(), chars, waitMs, playMs, head: txt.slice(0, 24), text: txt })
    console.log(`  ${el()} [stub /speak] chars=${chars} 合成模拟=${waitMs}ms 播放=${playMs}ms «${txt.slice(0, 24)}»`)
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
  if (url.includes('/orchestrator/chat')) {
    return { json: { reply: TEXT, actions: [], session_id: 'stub-session' } }
  }
  return null
}

// ======================= 启动 Chrome + 连 CDP =======================
const profile = mkdtempSync(join(tmpdir(), 'cdp-tts-'))
// 看门狗：任何环节挂住都不要让进程无限等（宁可报错退出，也别留一个僵尸）
const watchdog = setTimeout(() => {
  console.error('WATCHDOG: 超过 300s 未结束，强制退出')
  try { chrome.kill() } catch { /* ignore */ }
  process.exit(2)
}, 300000)
process.on('unhandledRejection', (e) => {
  console.error('UNHANDLED REJECTION:', e)
})
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
    // ★ headless 没有用户手势，不关自动播放策略 AudioContext 会一直 suspended
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
  } catch {
    /* 还没起来 */
  }
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
      try {
        post = JSON.parse(p.request.postData)
      } catch {
        /* 非 JSON，忽略 */
      }
    }
    const hit = resolveStub(p.request.url, post)
    if (!hit) {
      // ★ 放行时必须**显式回带 postData** —— 只调 continueRequest 不带 body 时，
      //   Chrome 会把 JSON 请求体丢掉（实测 `/speak-plan` 收到空 body → 422）。
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

/**
 * 每段量测之前/之后核对开关状态。
 *
 * ★ 为什么必须查：store 有一条「失败即自动关开关」的规则（防止每条回复刷一次错），
 *   一旦某步真失败，后面的 feed 会**静默 no-op**，量测结果就会变成一串看着正常的
 *   假数字。这里把状态与 `lastError` 打出来，并显式复位，避免误判。
 */
async function checkEnabled(tag) {
  const st = await run('JSON.stringify({enabled:window.__tts.enabled, err:window.__tts.lastError})')
  console.log('  [开关/错误 @' + tag + '] ' + st)
  await run(
    "if(!window.__tts.enabled){window.__tts.enabled=true;try{localStorage.setItem('voice_tts_enabled','true')}catch(e){}}"
  )
  return st
}

await send('Page.enable')
await send('Runtime.enable')
await send('Fetch.enable', {
  patterns: [
    // ★ 模式要**收窄到 URL 结尾**：`*voice-clone/speak*` 会连 `/speak-plan` 一起吃掉
    //   （曾因此把纯计算端点也桩掉，注入错的 JSON，反而触发了「失败自动关开关」）。
    // ★ `/speak-plan` **一条都不拦**：它必须原封不动到真后端。
    //   （试过「拦下来计数再 continueRequest 回带 postData」—— 那条路会把请求挂死：
    //     `Fetch.continueRequest` 的 postData 语义与原始 POST body 不一致，页面 fetch 永不返回。
    //     所以计数改用**后端日志**做，见 countPlanCalls()。）
    { urlPattern: '*voice-clone/speak', requestStage: 'Request' },
    { urlPattern: '*voice-clone/status*', requestStage: 'Request' },
    { urlPattern: '*orchestrator/chat', requestStage: 'Request' },
  ],
})
// ★ 开关要在 store 初始化**之前**就为 true（readEnabled() 只在 store 首次创建时读一次）
await send('Page.addScriptToEvaluateOnNewDocument', {
  source: "try{localStorage.setItem('voice_tts_enabled','true')}catch(e){}",
})
await send('Page.navigate', { url: APP_URL })
await sleep(11000)
for (let i = 0; i < 3; i++) {
  const len = await run('document.body?.textContent?.length || 0')
  if (len > 200) break
  console.log('retry reload, len=', len)
  await send('Page.reload')
  await sleep(7000)
}

console.log('=== 0. 隔离干扰 + 取 store')
const grab = `(()=>{
  const el=document.querySelector('#app');
  const app=el&&el.__vue_app__;
  const pinia=app&&app.config.globalProperties&&app.config.globalProperties.$pinia;
  if(!pinia||!pinia._s) return 'NO_PINIA';
  const tts=pinia._s.get('voiceTts'); const chat=pinia._s.get('chat');
  if(!tts||!chat) return 'NO_TTS_OR_CHAT';
  window.__pinia=pinia; window.__tts=tts; window.__chat=chat;
  // ★ 关键隔离：把当前对话区切到**非白名单** Agent。
  //   开屏那条「店秘书欢迎语」也是 assistant 消息，watch 会把它念一遍；
  //   切走之后 watch 的 supports() 直接返回 false ⇒ 本轮量测不受开屏遗留干扰。
  chat.setActiveAgent('product-research');
  tts.stop();
  return JSON.stringify({enabled:tts.enabled, agent:chat.activeAgentId, suppressed:!tts.supports('product-research')});
})()`
console.log('  ', await run(grab))
for (let i = 0; i < 40; i++) {
  if ((await run('window.__tts.phase')) === 'idle') break
  await sleep(200)
}

// ======================= ① 时钟健康 =======================
console.log('\n=== ① AudioContext 时钟健康（headless 前提）')
console.log(
  '  ',
  await run(`(async()=>{
  const C=(window.AudioContext||window.webkitAudioContext);
  if(!C) return JSON.stringify({err:'no AudioContext'});
  const c=new C();
  const a=c.currentTime;
  await new Promise(r=>setTimeout(r,1200));
  return JSON.stringify({state:c.state, advanced:+(c.currentTime-a).toFixed(3)});
})()`)
)

// ======================= ② 基线：旧路径 =======================
let baseline = '（FAST 模式跳过）'
if (!FAST) {
  console.log('\n=== ② 基线：旧路径 = 等正文说完 → 整段合成一次（= 旧首声的下限）')
  baseline = await run(`(async()=>{
  const TEXT=${JSON.stringify(TEXT)};
  const t0=performance.now();
  const r=await fetch('/api/v1/voice-clone/speak',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({text:TEXT})});
  const j=await r.json();
  return JSON.stringify({firstSoundMs:Math.round(performance.now()-t0), chars:[...TEXT].length, spoken:(j.spoken_text||'').length});
})()`)
  console.log('  ', baseline)
}

// ======================= ②b 后端分句计划转储 =======================
console.log('\n=== ②b 后端 /speak-plan 对同一段正文的切分（真后端）')
const plan = await run(`(async()=>{
  const r=await fetch('/api/v1/voice-clone/speak-plan',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({text:${JSON.stringify(TEXT)}})});
  const j=await r.json();
  const segs=j.segments||[];
  return JSON.stringify({n:segs.length, segs:segs.map(s=>s.chars+'/'+(s.stable?'S':'u')+'@'+s.raw_end), clean:j.clean_chars, truncated:j.truncated, texts:segs.map(s=>s.text)});
})()`)
console.log('  ', plan)

// 记住 ③ 开始前的桩调用数（后端日志不记这个端点，所以计数改用页面内挂 XHR 做）
let stubMark3 = stubLog.length
await run(`(()=>{
  window.__planCalls=0; window.__speakCalls=0;
  const orig=XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open=function(m,u){
    try{
      const s=String(u);
      if(s.indexOf('/voice-clone/speak-plan')>=0) window.__planCalls++;
      else if(/\\/voice-clone\\/speak$/.test(s)) window.__speakCalls++;
    }catch(e){}
    return orig.apply(this,arguments);
  };
  return 'hooked';
})()`)
await checkEnabled('② 之后 / ③ 之前')

// ======================= ③ 新路径：流水线喂入 =======================
console.log('\n=== ③ 新路径：分句流水线（模拟流式，每 130ms 加 14 字）')
const RK = 'probe-pl#' + Date.now()
const pipeline = await run(`(async()=>{
  const tts=window.__tts;
  const TEXT=${JSON.stringify(TEXT)};
  const runKey=${JSON.stringify(RK)};
  const CHUNK=14, STEP=130;
  const t0=performance.now();
  for(let i=CHUNK;i<=TEXT.length;i+=CHUNK){
    tts.feed(TEXT.slice(0,i),{runKey,streaming:true});
    await new Promise(r=>setTimeout(r,STEP));
  }
  const feedDoneMs=Math.round(performance.now()-t0);
  tts.feed(TEXT,{runKey,streaming:false});
  for(let k=0;k<240;k++){
    await new Promise(r=>setTimeout(r,250));
    const m=tts.lastRunMetrics;
    if(m&&m.runKey===runKey&&tts.phase==='idle') break;
  }
  return JSON.stringify({feedDoneMs, metrics:tts.lastRunMetrics});
})()`)
console.log('  ', pipeline)
const run3Texts = stubLog.slice(stubMark3).map((s) => s.text)
let plan3 = { texts: [] }
try {
  plan3 = JSON.parse(plan)
} catch {
  console.log('  ⚠️ 计划转储解析失败，不变量无法比对')
}
const planTexts = plan3.texts || []

// ★★ 端到端不变量：**流式拼出来的段 == 一次算完的段**（不重不漏，逐字相同）。
//    这条是整套游标协议（raw_end 去重 + 只吃 stable）的总验收 ——
//    任一条判据写歪，这里都会立刻红（重念会多出内容，漏念会少内容）。
const joinedRun = run3Texts.join('')
const joinedPlan = planTexts.join('')
const sameTexts = JSON.stringify(run3Texts) === JSON.stringify(planTexts)
console.log('\n=== 端到端不变量：流式念的段 vs 一次算完的段')
console.log('  流式 ' + run3Texts.length + ' 段 / 计划 ' + planTexts.length + ' 段；逐段逐字相同 = ' + sameTexts)
console.log('  拼接相同 = ' + (joinedRun === joinedPlan) + '（流式 ' + joinedRun.length + ' 字 / 计划 ' + joinedPlan.length + ' 字）')
if (!sameTexts) {
  console.log('  流式：' + JSON.stringify(run3Texts).slice(0, 400))
  console.log('  计划：' + JSON.stringify(planTexts).slice(0, 400))
}

// ★★ 第二条断言（**反向注入逼出来的**）：只看「发了哪些 /speak 请求」是不够的 ——
//    重复入队的段会命中 `urlCache`，根本不发 HTTP，所以请求列表看着完美。
//    真正能抓到重复的是**排期段数**（`lastRunMetrics.segments` = 实际 enqueue 次数）。
//    实测：去掉游标去重后 4 段正文会被排 10 次，而请求仍只有 4 次 ⇒ 第一条断言全绿。
const metrics3 = (() => {
  try {
    return JSON.parse(pipeline).metrics
  } catch {
    return null
  }
})()
const segOk = !!metrics3 && metrics3.segments === planTexts.length
const gapOk = !metrics3
  ? false
  : planTexts.length <= 1
    ? metrics3.maxGapMs === -1
    : metrics3.maxGapMs === 0 && metrics3.gaps.length === planTexts.length - 1
const overall = sameTexts && segOk && gapOk
console.log(
  `  排期段数 = ${metrics3 ? metrics3.segments : '?'}（期望 ${planTexts.length}）⇒ segOk=${segOk}；` +
    ` 段间间隙 max=${metrics3 ? metrics3.maxGapMs : '?'}ms gaps=[${metrics3 ? metrics3.gaps.join(',') : ''}] ⇒ gapOk=${gapOk}`
)
console.log(
  `★★ VERDICT overall=${overall} textOk=${sameTexts} segOk=${segOk} gapOk=${gapOk} firstSoundMs=${
    metrics3 ? Math.round(metrics3.firstSoundMs) : '?'
  }`
)

const planCalls3 = await run('window.__planCalls')
console.log('  ③ 这一轮实际请求次数：/speak-plan = ' + planCalls3 + '，/speak = ' + (await run('window.__speakCalls')))
console.log('  （正文 143 字、喂了 10 次增量；逐 delta 无节流的话会是 ~20+ 次，逼近全局限流 60/60s）')

await checkEnabled('③ 之后 / ④ 之前')

// ======================= ④ 真实编排层：watch → feed =======================
let orch = '（FAST 模式跳过）'
if (!FAST) {
  console.log('\n=== ④ 真实编排层：切回店秘书 + 压一条 assistant 消息（只靠 watch，不直接调 feed）')
  const RK4 = 'secretary#' + Date.now()
  orch = await run(`(async()=>{
  const chat=window.__chat, tts=window.__tts;
  const TEXT=${JSON.stringify(TEXT)};
  chat.setActiveAgent('secretary');
  const before=tts.lastRunMetrics?tts.lastRunMetrics.runKey:'';
  await new Promise(r=>setTimeout(r,600));
  // ★ 必须先落一条 user 消息：播报有「本轮」闸门（只念刚被提问的那个对话区），
  //   上来直接塞 assistant 消息属于「历史回复」，本来就该被拦掉。
  chat.addMessage({role:'user',content:'（探针）把这段念给我听'});
  await new Promise(r=>setTimeout(r,80));
  chat.addMessage({role:'assistant',content:TEXT});
  for(let k=0;k<240;k++){
    await new Promise(r=>setTimeout(r,250));
    const m=tts.lastRunMetrics;
    if(m&&m.runKey!==before&&m.runKey.indexOf('secretary')===0&&tts.phase==='idle') break;
  }
  const m=tts.lastRunMetrics;
  return JSON.stringify({wired:!!m&&m.runKey!==before&&m.runKey.indexOf('secretary')===0, metrics:m});
})()`)
  console.log('  ', orch)
}

console.log('\n=== 汇总')
console.log('  基线（整段一次合成）首声 = ' + baseline)
console.log('  新路径 = ' + pipeline)
console.log('  编排层接通 = ' + orch)
console.log('  打桩 /speak 共 ' + stubLog.length + ' 次；③ 一轮 /speak-plan 共 ' + planCalls3 + ' 次')
console.log('  ⚠️ 后端是**全局**限流 60 次/60s（整个 App 按 IP 共用）⇒ 计划调用必须远低于 60')
console.log('  ★ 端到端不变量（流式段 == 一次算完的段）= ' + sameTexts)
console.log('  ★ 总判定 overall = ' + overall + '（textOk && segOk && gapOk，三项全绿才算过）')
if (consoleLogs.length) {
  console.log('  页面内自报指标：')
  for (const l of consoleLogs) console.log('    ' + l)
}
ws.close()
chrome.kill()
clearTimeout(watchdog)
await sleep(300)
process.exit(0)

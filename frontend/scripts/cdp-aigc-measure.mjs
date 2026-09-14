// CDP 量测 AIGC 三个工具右栏配置面板。
// 验证目标（09-13 老板三连纠偏后的新形态）：
//   ① 表单态：平铺 section（非 a-collapse），标题层级统一，操作栏恒可见
//   ② 大屏态：走 Workspace 顶栏 mode-switch（reviewMode=data），右栏变预览窗口
//   ③ 表单态默认无向下滚轮（over 尽量小），操作栏 abBottom <= vh
// 用法：node cdp-aigc-measure.mjs <W> <H> <tool> [mode]
//   mode: form（默认，对话模式） | data（大屏模式）
import { spawn } from 'node:child_process'
import { writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9333
const URL = 'http://localhost:5173/'

const W = Number(process.argv[2] || 1264)
const H = Number(process.argv[3] || 600)
const TOOL = process.argv[4] || 'static-asset-gen'
const MODE = process.argv[5] || 'form'  // form | data

const sleep = ms => new Promise(r => setTimeout(r, ms))

const AGENT_NAME = 'AIGC 媒体生成器'
const TOOL_LABELS = {
  'static-asset-gen': '静态素材生成',
  'video-script-gen': '短视频带货脚本',
  'ai-video-generator': 'AI 短视频生成',
}
const TOOL_LABEL = TOOL_LABELS[TOOL] || TOOL_LABELS['static-asset-gen']

const NAV = `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const all=[...document.querySelectorAll('*')].filter(e=>e.children.length===0);
  const agent=all.find(e=>(e.textContent||'').trim().startsWith('${AGENT_NAME}'));
  if(!agent) return JSON.stringify({err:'no AIGC agent'});
  (agent.closest('[class*=agent],[class*=item]')||agent).click();
  await sleep(1500);
  const toolBtns=[...document.querySelectorAll('.toolbar-tool-btn')];
  const toolBtn=toolBtns.find(b=>(b.textContent||'').includes('${TOOL_LABEL}'));
  if(toolBtn) { toolBtn.click(); await sleep(1500); }
  const inner=document.querySelector('.static-asset-config,.video-script-config,.video-generator-config');
  const modeSwitch=document.querySelector('.mode-switch');
  return JSON.stringify({inner:!!inner,modeSwitch:!!modeSwitch,clicked:!!toolBtn,tb:toolBtns.map(b=>(b.textContent||'').trim())});
})()`

// 切到指定模式（点顶栏 mode-switch 的「大屏模式/对话模式」按钮）
const SWITCH_MODE = `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const sw=document.querySelector('.mode-switch');
  if(!sw) return 'NO_MODE_SWITCH';
  const btns=[...sw.querySelectorAll('.mode-switch-btn')];
  const target='${MODE==='data' ? '大屏模式' : '对话模式'}';
  const btn=btns.find(b=>(b.textContent||'').includes(target));
  if(!btn) return 'NO_BTN:'+btns.map(b=>b.textContent.trim()).join(',');
  btn.click();
  await sleep(1200);
  return 'ok:'+target;
})()`

// 量测：区分表单态 / 大屏态
const measure = tag => `(()=>{
  const q=s=>document.querySelector(s);
  const qa=s=>[...document.querySelectorAll(s)];
  const h=e=>e?Math.round(e.getBoundingClientRect().height):null;
  const formBody=q('.form-body');
  const preview=q('.preview-canvas');
  const ab=q('.action-bar');
  const body=formBody||preview;
  const rc=ab?ab.getBoundingClientRect():null;
  const kids=body?[...body.children]:[];
  const br=body?body.getBoundingClientRect():null;
  const last=kids[kids.length-1];
  const first=kids[0];
  const bottomGap=(br&&last)?Math.round(br.bottom-last.getBoundingClientRect().bottom):null;
  const sections=qa('.cfg-section');
  return JSON.stringify({
    tag:'${tag}', tool:'${TOOL}', mode:'${MODE}',
    isForm:!!formBody, isPreview:!!preview,
    sectionCount:sections.length,
    bodyH:h(body),
    realOver:body?(body.scrollHeight-body.clientHeight):null,
    bottomGap,
    abVisible:rc?(rc.bottom<=innerHeight&&rc.top>0):null,abBottom:rc?Math.round(rc.bottom):null,
    vh:innerHeight,
    modeSwitchActive:[...qa('.mode-switch-btn')].map(b=>({t:(b.textContent||'').trim(),a:b.classList.contains('active')})),
    overflowX:document.documentElement.scrollWidth-document.documentElement.clientWidth
  });
})()`

// 注入产品
const INJECT_PRODUCT = `(()=>{
  const inner=document.querySelector('.static-asset-config,.video-script-config,.video-generator-config');
  if(!inner) return 'NO_INNER';
  const inst=inner.__vueParentComponent;
  if(!inst) return 'NO_INST';
  const p={title:'Stainless Steel Manual Coffee Grinder',main_image:'/static/aigc/1d3fd5aa6a76fb80.png',
    selling_points:['大容量 25g','防锈不锈钢刀盘','便携易清洗'],
    description:'手摇咖啡磨豆机，适合户外与家用'};
  if('pickedProduct' in inst.setupState) inst.setupState.pickedProduct=p;
  return 'ok';
})()`

// 注入大屏结果（latestResult）
const INJECT_RESULT = `(()=>{
  const inner=document.querySelector('.static-asset-config,.video-script-config,.video-generator-config');
  if(!inner) return 'NO_INNER';
  const inst=inner.__vueParentComponent;
  if(!inst||!inst.setupState) return 'NO_INST';
  const t='${TOOL}';
  if(t==='static-asset-gen'){
    inst.setupState.latestResult={type:'static_asset_gen',generated_assets:[
      {id:'1',url:'/static/aigc/1d3fd5aa6a76fb80.png',type:'three-view',desc:'白底三视图'},
      {id:'2',url:'/static/aigc/1d3fd5aa6a76fb80.png',type:'scene',desc:'场景图'},
      {id:'3',url:'/static/aigc/1d3fd5aa6a76fb80.png',type:'detail',desc:'细节特写'},
    ]};
  } else if(t==='video-script-gen'){
    inst.setupState.latestResult={type:'video_script_gen',script_summary:'**卖点驱动**的30秒脚本',storyboard:[
      {duration:3,visual:'特写产品正面',narration:'开场钩子',cameraMovement:'push-in',shotSize:'closeup'},
      {duration:5,visual:'360度展示',narration:'惊艳登场',cameraMovement:'rotate',shotSize:'medium-shot'},
      {duration:4,visual:'核心卖点',narration:'静音研磨',cameraMovement:'zoom-dolly',shotSize:'full-shot'},
    ]};
  } else {
    inst.setupState.latestResult={type:'ai_video_generator',video_url:'',preview_frames:[
      {url:'/static/aigc/1d3fd5aa6a76fb80.png',timestamp:'0:00',desc:'镜头1'},
      {url:'/static/aigc/1d3fd5aa6a76fb80.png',timestamp:'0:03',desc:'镜头2'},
    ]};
  }
  return 'ok';
})()`

const RECT = `(()=>{const e=document.querySelector('.task-config-panel');if(!e)return 'null';
  const r=e.getBoundingClientRect();
  return JSON.stringify({x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height});})()`

// ===== 启动 Chrome =====
const profile = mkdtempSync(join(tmpdir(), 'cdp-prof-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu',
  '--disable-extensions', '--disable-background-networking',
  '--hide-scrollbars=false',
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
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej) })
const send = (method, params = {}) => new Promise(res => { const i = ++seq; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })

const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) return 'EXC: ' + JSON.stringify(r.result.exceptionDetails.exception?.description || '').slice(0, 200)
  return r.result?.result?.value
}
const shot = async (file, clip) => {
  const params = { format: 'png' }
  if (clip) params.clip = { ...clip, scale: 1 }
  const r = await send('Page.captureScreenshot', params)
  if (r.result?.data) { writeFileSync(file, Buffer.from(r.result.data, 'base64')); return true }
  return false
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: URL })
// 等 vite dev 首次编译 + 异步 store 初始化完成
await sleep(10000)
// 诊断：如果 body 文本很短，反复 reload 直到侧栏渲染出 AIGC 文本
for (let i = 0; i < 3; i++) {
  const len = await run('document.body?.textContent?.length || 0')
  if (len > 500) break
  console.log('retry reload, len=', len, 'attempt', i + 1)
  await send('Page.reload')
  await sleep(6000)
}

console.log('viewport =', W, 'x', H, '| tool =', TOOL, '| mode =', MODE)

const nav = await run(NAV)
console.log('NAV:', nav)

if (String(nav).includes('"inner":true')) {
  // 切换模式
  const sw = await run(SWITCH_MODE)
  console.log('SWITCH:', sw)

  if (MODE === 'data') {
    // 大屏态：注入结果后量测
    await run(INJECT_RESULT); await sleep(800)
    console.log('DATA 大屏态 :', await run(measure('data-大屏')))
    const rect = JSON.parse(await run(RECT))
    await shot(`.shot-${TOOL}-data-${W}x${H}.png`)
    await shot(`.shot-${TOOL}-data-panel-${W}x${H}.png`, rect)
  } else {
    // 表单态：空态 → 载入产品
    console.log('FORM 空态   :', await run(measure('form-空态')))
    const rect = JSON.parse(await run(RECT))
    await shot(`.shot-${TOOL}-form-empty-${W}x${H}.png`)
    await shot(`.shot-${TOOL}-form-panel-${W}x${H}.png`, rect)
    await run(INJECT_PRODUCT); await sleep(500)
    console.log('FORM 载入产品:', await run(measure('form-载入产品')))
    await shot(`.shot-${TOOL}-form-loaded-${W}x${H}.png`)
  }
} else {
  console.log('落空，页面状态：', await run(`(()=>JSON.stringify({text:document.body.innerText.replace(/\\s+/g,' ').slice(0,400)}))()`))
}

ws.close()
chrome.kill()
await sleep(300)
process.exit(0)
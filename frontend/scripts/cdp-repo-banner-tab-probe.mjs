// CDP 真实浏览器验证（第 255 轮建、第 256 轮改口径）——只测「渲染出来的东西」。
//
// 验证目标（第 256 轮老板原话：「介绍都太长了」）：
//   ① 工具仓库横幅写明判据「确定可计算 → 工具」
//   ② Skill 仓库横幅写明判据「有取舍、需人判 → 技能」
//   ③ 第 255 轮那两条长判据文案已**退役**（否定断言钉住，防回归）
//   ④ Skill 仓库 tab 名为「快捷卡片管理」，且「技能管理」这个名字已不在页面上
//   ⑤ 「skill 配装」tab 的候选集**真的按 Agent 收窄**（DOM 里数 option 个数）
//
// 判据口径（本仓纪律）：
//   - 文案断言一律 `innerText` 归一化后**做子串包含**，且断言在**横幅元素内部**做，
//     不在整页文本上做（整页匹配会被 docstring / 别处注释喂饱，产生假绿）。
//   - 「有没有渲染」不数个数，取真实字符串。
//   - 收窄断言落在 **DOM 的 option 个数**上，不落在 store 的函数返回值上
//     （后者等于自己证明自己）。
//
// 用法：node scripts/cdp-repo-banner-tab-probe.mjs [W] [H]
import { spawn } from 'node:child_process'
import { writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9347
const URL = process.env.PROBE_URL || 'http://localhost:5173/'
const W = Number(process.argv[2] || 1600)
const H = Number(process.argv[3] || 950)

const sleep = ms => new Promise(r => setTimeout(r, ms))

const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail)}`)
}

const CLICK_SIDEBAR = label => `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const items=[...document.querySelectorAll('.knowledge-base .ant-menu-item')];
  const hit=items.find(e=>(e.textContent||'').trim()=== ${JSON.stringify(label)});
  if(!hit) return JSON.stringify({err:'no sidebar item', have:items.map(e=>(e.textContent||'').trim())});
  const el=hit.querySelector('span')||hit;
  el.click();
  await sleep(1800);
  return JSON.stringify({ok:true, clicked:${JSON.stringify(label)}});
})()`

const READ_TOOL_PAGE = `(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const banner=document.querySelector('.tm-head-sub');
  const tabs=[...document.querySelectorAll('.tm-tabs .ant-tabs-tab')].map(t=>norm(t.textContent));
  return JSON.stringify({
    bannerExists: !!banner,
    bannerText: banner ? norm(banner.innerText) : null,
    tabs,
    pageText: norm(document.querySelector('.tool-manager')?.innerText).slice(0,200)
  });
})()`

const READ_SKILL_PAGE = `(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const banner=document.querySelector('.sm-sub');
  const tabs=[...document.querySelectorAll('.ant-tabs-tab')].map(t=>norm(t.textContent));
  const root=document.querySelector('.skill-manager');
  return JSON.stringify({
    bannerExists: !!banner,
    bannerText: banner ? norm(banner.innerText) : null,
    tabs,
    rootExists: !!root,
    pageText: norm(root?.innerText).slice(0,200)
  });
})()`

// 切工具仓库的第 2 个 tab（skill 配装）
const GOTO_SKILL_TOOLS_TAB = `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const tabs=[...document.querySelectorAll('.tm-tabs .ant-tabs-tab')];
  const t=tabs.find(e=>(e.textContent||'').trim()==='skill 配装');
  if(!t) return JSON.stringify({err:'no tab', have:tabs.map(e=>(e.textContent||'').trim())});
  t.click();
  await sleep(1500);
  return JSON.stringify({ok:true, rows:document.querySelectorAll('.tm-skill-row').length});
})()`

// 在 skill 配装 tab 上：挑一行「生效 Agent 数 == 1 且已配备工具数 > 0」的技能，
// 打开它的工具下拉，数 DOM 里的 option 个数，并与「该 Agent 的工具数 + orphan 数」比对。
const MEASURE_NARROWING = `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const rows=[...document.querySelectorAll('.tm-skill-row')];
  const out=[];
  for(const row of rows){
    const key=(row.querySelector('.tm-skill-key')||{}).textContent||'?';
    const chips=[...row.querySelectorAll('.tm-card-line .tm-chip')].map(c=>norm(c.textContent));
    const sel=row.querySelector('.ant-select');
    if(!sel) { out.push({key, chips, err:'no select'}); continue; }
    // 判「空态 placeholder」文案（证明 toolPlaceholderOf 接上了）
    const ph=(row.querySelector('.ant-select-selection-placeholder')||{}).textContent||null;
    if(chips.length===1 && !ph){
      sel.querySelector('.ant-select-selector').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
      await sleep(700);
      const dd=[...document.querySelectorAll('.ant-select-dropdown')]
        .filter(d=>!d.classList.contains('ant-select-dropdown-hidden'));
      const last=dd[dd.length-1];
      const optCount=last?last.querySelectorAll('.ant-select-item-option').length:null;
      const groupTitles=last?[...last.querySelectorAll('.ant-select-item-group')].map(g=>norm(g.textContent)):null;
      const optTexts=last?[...last.querySelectorAll('.ant-select-item-option')].map(o=>norm(o.textContent)):null;
      out.push({key, chips, ph, optCount, groupTitles, optTexts});
      document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
      await sleep(400);
      break;
    }
  }
  return JSON.stringify(out);
})()`

// 取「该技能生效 Agent 的工具数」真值（从 store 的 toolGroups 读，不从被验函数读）
const EXPECT_FOR = skillName => `(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const root=document.querySelector('.tool-manager');
  const inst=root&&root.__vueParentComponent;
  let st=null;
  try { st=inst.setupState.store } catch(e) {}
  if(!st) return JSON.stringify({err:'no store on setupState'});
  const groups=st.toolGroups||[];
  const s=(st.items||[]).find(x=>x.name===${JSON.stringify(skillName)})||{};
  const agents=s.enabledAgents||[];
  let expected=0; const perAgent={};
  for(const g of groups){ if(agents.includes(g.agent)){ perAgent[g.agent]=g.tools.length; expected+=g.tools.length; } }
  const allNames=new Set(); for(const g of groups) for(const t of g.tools) allNames.add(t.name);
  const inExpected=new Set(); for(const g of groups) if(agents.includes(g.agent)) for(const t of g.tools) inExpected.add(t.name);
  const orphans=(s.tools||[]).filter(t=>!inExpected.has(t));
  return JSON.stringify({agents, perAgent, expected, orphanCount:orphans.length, orphans});
})()`

// 技能列表是**异步加载**的（store.loadAll 拉后端）。tab 一渲染就量测会取到 0 行，
// 而「0 行」会让后面所有逐行断言变成**空跑恒真** —— 所以必须显式等到有行为止，
// 且把「最终行数」当作断言输入（0 行一律判红，不许静默通过）。
// 拿不到行时先点一次页面上的「刷新」（= store.loadAll 的合法入口），再等一轮；
// 不在这里自己造数据、也不静默降级成 0 行。
const WAIT_ROWS = `(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const n=()=>document.querySelectorAll('.tm-skill-row').length;
  for(let i=0;i<24;i++){ if(n()>0) return n(); await sleep(500); }
  const btn=[...document.querySelectorAll('.tm-head-actions button')].find(b=>(b.textContent||'').includes('刷新'));
  if(btn){ btn.click(); await sleep(500); }
  for(let i=0;i<24;i++){ if(n()>0) return n(); await sleep(500); }
  return n();
})()`

// 扫全部行的「生效 Agent 数 / 下拉 placeholder」——用来抓「0 个 Agent」那一类行。
// 这条断言必须落在**真实 DOM 的 placeholder 文本**上：
// 「未勾选 Agent」的技能若给空白下拉，用户会以为「这个 Agent 没工具」，
// 而真实原因是「技能根本没对任何 Agent 生效，所以没有候选」。
const SCAN_PLACEHOLDERS = `(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  return JSON.stringify([...document.querySelectorAll('.tm-skill-row')].map(row=>{
    const key=norm((row.querySelector('.tm-skill-key')||{}).textContent);
    const chips=[...row.querySelectorAll('.tm-card-line .tm-chip')].map(c=>norm(c.textContent));
    const boundCount=row.querySelectorAll('.ant-select-selection-item').length;
    const phEl=row.querySelector('.ant-select-selection-placeholder');
    return {key, chipCount:chips.length, boundCount, ph: phEl ? norm(phEl.textContent) : null};
  }));
})()`

// body 兜底：把整页操作区文本抓出来，便于失败时定位
const BODY = `(()=>document.body.innerText.replace(/\\s+/g,' ').slice(0,300))()`

// ===== 启动 Chrome =====
const profile = mkdtempSync(join(tmpdir(), 'cdp-r255-'))
const chrome = spawn(CHROME, [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  '--remote-allow-origins=*',
  `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`,
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

const run = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 300)
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

// ★ 启动等待写成「等**具体元素**出现」，不用 body 文本长度当代理判据。
// 曾经这里写的是「body 文本 < 800 字符就 reload」，连 reload 4 次 ——
// 副作用是应用被反复重启 4 遍，`store.loadAll()` 在后端限流窗口里打偏，
// 结果技能列表恒 0 行（同一份代码手工跑一次就正常拿到 22 行）。
// 现在：只等侧栏出现；15s 还没出现才 reload 一次（最多一次）。
const sidebarN = () => 'document.querySelectorAll(".knowledge-base .ant-menu-item").length'
for (let i = 0; i < 20; i++) {
  const n = await run(sidebarN())
  if (typeof n === 'number' && n >= 8) break
  await sleep(1000)
}
if (!((await run(sidebarN())) >= 8)) {
  console.log('side bar 未出现，reload 一次')
  await send('Page.reload'); await sleep(8000)
}

console.log(`viewport = ${W}x${H} | url = ${URL}`)
console.log('boot: sidebar items =', await run(sidebarN()), '| body len =', await run('document.body?.textContent?.length || 0'))

// ---------- ① 工具仓库 ----------
console.log('\n===== 工具仓库 =====')
console.log('CLICK:', await run(CLICK_SIDEBAR('工具仓库')))
await sleep(1500)
const toolPage = await run(READ_TOOL_PAGE)
console.log('READ:', toolPage)
let tp = null
try { tp = JSON.parse(toolPage) } catch { /* ignore */ }
const tb = tp?.bannerText || ''

check('T0', '工具仓库页已渲染（横幅元素存在）', !!tp?.bannerExists, tp)
check('T1', '工具仓库横幅含「确定可计算 → 工具」', tb.includes('确定可计算 → 工具'), tb.slice(0, 260))
// 第 256 轮老板要求「介绍太长了，改为短句」⇒ 旧长判据文案是**退役**状态，
// 用否定断言钉住，防回归（本仓纪律：棘轮只收紧、不放松）。
check('T2', '旧长判据文案已退役（能确定性算出来 / 答案由代码给出 / 需要判断（有方法、要取舍））',
  !/能确定性算出来的做成工具|答案由代码给出|需要判断（有方法、要取舍）的做成技能/.test(tb), tb.slice(0, 260))
// ★ 这里刻意写成三条**精确短语**的合取，不写 `A || (B && C)`：
//   后者只要横幅里任意处出现「代码」「不能新建工具」就恒真（子序列恒真），
//   等于给缺陷盖章。三条缺一即红。
check('T3', '工具仓库保留原有「代码定义 / 不能新建工具 / 不改归属」三句原文',
  tb.includes('工具由代码定义') && tb.includes('不能新建工具') && tb.includes('也不改工具归属'), tb.slice(0, 200))
check('T4', '工具仓库三个 tab 齐（工具管理 / skill 配装 / Agent 配装）',
  ['工具管理', 'skill 配装', 'Agent 配装'].every(x => (tp?.tabs || []).includes(x)), tp?.tabs)
await shot('.shot-r255-tool-repo.png')

// ---------- ⑤ skill 配装：候选集真的按 Agent 收窄 ----------
console.log('\n===== skill 配装（收窄实测）=====')
const goto = await run(GOTO_SKILL_TOOLS_TAB)
console.log('GOTO:', goto)
const rowCount = await run(WAIT_ROWS)
console.log('ROWS(after wait) =', rowCount)
check('N0', '「skill 配装」tab 取到技能行（0 行会让后续逐行断言空跑恒真，一律判红）',
  typeof rowCount === 'number' && rowCount > 0, { rowCount, goto })
await sleep(400)
const narrowing = await run(MEASURE_NARROWING)
console.log('NARROWING:', narrowing)
let nr = null
try { nr = JSON.parse(narrowing) } catch { /* ignore */ }
const picked = Array.isArray(nr) ? nr[0] : null
if (picked && picked.optCount != null) {
  const exp = await run(EXPECT_FOR(picked.key))
  console.log('EXPECT:', exp)
  let ex = null
  try { ex = JSON.parse(exp) } catch { /* ignore */ }
  check('N1', '候选集由「生效于」的 Agent 收窄：下拉 option 数 == 该 Agent 工具数（+ 已绑定 orphan）',
    !!ex && picked.optCount === (ex.expected + ex.orphanCount),
    { pick: picked, exp: ex })
  check('N2', '下拉里的分组标题只出现该技能生效的 Agent（非全量 8 个）',
    !!picked.groupTitles && picked.groupTitles.every(t => (ex?.perAgent ? Object.keys(ex.perAgent) : []).some(a => t.includes(a)) || t.includes('已绑定')),
    { groupTitles: picked.groupTitles, agents: ex?.agents })
} else {
  check('N1', '候选集收窄实测（未取到样本）', false, { narrowing, picked })
  check('N2', '分组标题收窄（未取到样本）', false, { narrowing })
}

// N3/N4：三态穷尽对账 —— placeholder 与「生效 Agent 数 × 已配备工具数」必须严格对应。
//   A 态 chipCount==0                ⇒ placeholder == '该技能未对任何 Agent 生效…'（无候选）
//   B 态 chipCount>0 且 bound==0     ⇒ placeholder == '（未配备任何工具）'
//   C 态 chipCount>0 且 bound>0      ⇒ **不得**有 placeholder（有值就显示值）
// 三态互斥且穷尽；任一态错配即转红。
const phScan = await run(SCAN_PLACEHOLDERS)
let phRows = []
try { phRows = JSON.parse(phScan) } catch { /* ignore */ }
console.log('PLACEHOLDER SCAN:', phScan)

const stateA = phRows.filter(r => r.chipCount === 0)
const stateB = phRows.filter(r => r.chipCount > 0 && r.boundCount === 0)
const stateC = phRows.filter(r => r.chipCount > 0 && r.boundCount > 0)
const badA = stateA.filter(r => !(r.ph && r.ph.includes('该技能未对任何 Agent 生效')))
const badB = stateB.filter(r => r.ph !== '（未配备任何工具）')
const badC = stateC.filter(r => !!r.ph)
console.log(`覆盖率：A(无生效Agent)=${stateA.length} B(生效但未配工具)=${stateB.length} C(已配工具)=${stateC.length} / 共 ${phRows.length} 行`)

check('N3', 'B 态（已对 Agent 生效但一个工具都没配）给出「（未配备任何工具）」引导，不是空白下拉',
  phRows.length > 0 && stateB.length > 0 && badB.length === 0, { badB, stateB: stateB.map(r => r.key) })
check('N4', '三态穷尽且互斥：A 态给空岗引导、C 态有值就不显示 placeholder',
  phRows.length > 0 && badA.length === 0 && badC.length === 0
    && stateA.length + stateB.length + stateC.length === phRows.length
    && stateC.length > 0,
  { badA, badC, coverage: { A: stateA.length, B: stateB.length, C: stateC.length, total: phRows.length } })
await shot('.shot-r255-skill-tools.png')

// ---------- ②③④ Skill 仓库 ----------
console.log('\n===== Skill 仓库 =====')
console.log('CLICK:', await run(CLICK_SIDEBAR('Skill 仓库')))
await sleep(2000)
const skillPage = await run(READ_SKILL_PAGE)
console.log('READ:', skillPage)
let sp = null
try { sp = JSON.parse(skillPage) } catch { /* ignore */ }
const sb = sp?.bannerText || ''

check('S0', 'Skill 仓库页已渲染（横幅元素存在）', !!sp?.bannerExists, sp)
check('S1', 'Skill 仓库横幅含「有取舍、需人判 → 技能」', sb.includes('有取舍、需人判 → 技能'), sb.slice(0, 260))
check('S2', '旧长判据文案已退役（需要判断（有方法、要取舍） / 仍要自己判断 / 能确定性算出来的）',
  !/需要判断（有方法、要取舍）的做成技能|仍要自己判断|能确定性算出来的做成工具/.test(sb), sb.slice(0, 300))
check('S3', 'Skill 仓库保留原有「集中维护 / 按需勾选启用」口径',
  sb.includes('集中维护') && sb.includes('按需勾选启用'), sb.slice(0, 200))
check('S4', 'repo tab 已改名「快捷卡片管理」', (sp?.tabs || []).includes('快捷卡片管理'), sp?.tabs)
// 否定型断言必须自带非空前置：tab 列表为空时 `!some(...)` **恒真**
// —— 上一步刚踩过（空列表把 S7 判成 PASS）。这里显式要求 tabs 非空。
check('S5', '旧名「技能管理」已不在 tab 上（且 tab 列表非空，防空集合恒真）',
  (sp?.tabs || []).length > 0 && !(sp?.tabs || []).some(t => t === '技能管理'), sp?.tabs)
await shot('.shot-r255-skill-repo.png')

// ---------- 汇总 ----------
const failed = results.filter(r => !r.ok)
console.log('\n===== SUMMARY =====')
console.log(`断言总数 ${results.length} / 通过 ${results.length - failed.length} / 失败 ${failed.length}`)
if (failed.length) console.log('失败项：' + failed.map(f => f.id).join(', '))
console.log(`RESULT=${failed.length === 0 ? 'PASS' : 'FAIL'}`)

ws.close()
chrome.kill()
await sleep(300)
process.exit(failed.length === 0 ? 0 : 1)

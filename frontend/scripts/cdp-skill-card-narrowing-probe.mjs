// CDP 真机判据（第 295 轮 A 档）—— 「撤卡片」在 **Skill 仓库**上的落点读数。
//
// ★ 与 `cdp-review-desk-ui-probe-panel-bug.mjs` 的 R10 **分工明确，不要合并**：
//     · R10 判的是**对话页卡片区**（`.iab-chip`）里不再有「差评应对」；
//     · 本文件判的是**Skill 仓库**里那条技能**还在**、且它身上挂的 chip 说
//       「不设卡片」并且**承诺能力仍在**。
//   两件事合起来才是「撤卡片」的完整语义：
//       撤的是**入口**（对话页那格卡），不是**能力**（技能仍在仓库、仍在 Agent 目录）。
//   只验前者的后果：用户以为技能被删了。
//
// ★ 判据为什么必须有**对照组**（U6）：如果全表技能都显示「不设卡片」，那这个 chip
//   就毫无区分度 —— 而那种实现会**全绿**。所以必须同时断言"存在**没有**这个 chip
//   的技能"。这是本仓「必须带诱饵」纪律的又一形态。
//
// 用法：node scripts/cdp-skill-card-narrowing-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9388
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r295_card_narrowing')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-narrow-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,1000',
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
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
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
  if (r?.result?.data) {
    const { writeFileSync } = await import('node:fs')
    writeFileSync(join(SHOT_DIR, name + '.png'), Buffer.from(r.result.data, 'base64'))
  }
}

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(4000)

const bodyText = await run(`document.body ? document.body.innerText.slice(0,200) : ''`)
check('U0', '页面已渲染（自检）', !!bodyText && bodyText.length > 0, bodyText)

// ---- 进入 Skill 仓库 ----
const clicked = JSON.parse(await run(`(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const items=[...document.querySelectorAll('.knowledge-base .ant-menu-item')];
  const hit=items.find(e=>(e.textContent||'').trim()==='Skill 仓库');
  if(!hit) return JSON.stringify({err:'no sidebar item', have:items.map(e=>(e.textContent||'').trim())});
  (hit.querySelector('span')||hit).click();
  await sleep(2500);
  return JSON.stringify({ok:true, clicked:'Skill 仓库'});
})()`))
check('U1', '能进入「Skill 仓库」（左侧知识库菜单）', clicked.ok === true, clicked)

// ---- 等技能卡真正加载出来 ----
const rowCount = await run(`(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const n=()=>document.querySelectorAll('.sm-card, .sm-row').length;
  for(let i=0;i<30;i++){ if(n()>0) return n(); await sleep(500); }
  return n();
})()`)
// ★ 0 行会让后面所有逐行断言变成**空跑恒真** ⇒ 必须显式判红，不静默通过。
check('U2', 'Skill 仓库的技能卡已加载（>0 行，而非空跑）', rowCount > 0, { rowCount })

const read = JSON.parse(await run(`(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const cards=[...document.querySelectorAll('.sm-card, .sm-row')];
  const items=cards.map(c=>{
    const t=c.querySelector('.sm-card-title, .sm-row-title');
    const noCard=[...c.querySelectorAll('.sm-chip-no-card')].map(e=>({
      text:norm(e.textContent), tip:e.getAttribute('title')||''
    }));
    return { title: t?norm(t.textContent):null, noCard };
  });
  const root=document.querySelector('.skill-manager');
  const pageText=norm(root ? root.innerText : '');
  return JSON.stringify({
    total: items.length,
    withChip: items.filter(i=>i.noCard.length>0).map(i=>i.title),
    firstChip: (items.find(i=>i.noCard.length>0)||{noCard:[{}]}).noCard[0] || null,
    titles: items.map(i=>i.title),
    hasYiFaFaLun: pageText.indexOf('仅方法论') >= 0,
  });
})()`))

const triageTitle = '差评应对'
const narrativeTitle = '复盘结论写法'
const withChip = new Set(read.withChip || [])

// ---- U3：撤卡片的那条，在仓库里**还在**，且 chip 写着「不设卡片」 ----
check('U3 ★ 「差评应对」仍在仓库里（撤的是入口，不是技能）',
  (read.titles || []).includes(triageTitle),
  { searched: triageTitle, titles: (read.titles || []).slice(0, 30) })

check('U4 ★ 「差评应对」身上挂着「不设卡片」chip',
  withChip.has(triageTitle),
  { withChip: read.withChip })

// ---- U5：chip 必须承诺「能力仍在」（撤卡片最容易被误读成"能力没了"） ----
const triageCard = (await run(`(()=>{
  const norm=s=>(s||'').replace(/\\s+/g,' ').trim();
  const cards=[...document.querySelectorAll('.sm-card, .sm-row')];
  const c=cards.find(x=>{
    const t=x.querySelector('.sm-card-title, .sm-row-title');
    return t && norm(t.textContent).includes(${JSON.stringify(triageTitle)});
  });
  if(!c) return null;
  const chip=c.querySelector('.sm-chip-no-card');
  return JSON.stringify({
    chipText: chip?norm(chip.textContent):null,
    chipTip: chip?(chip.getAttribute('title')||''):null,
  });
})()`))
const tc = triageCard ? JSON.parse(triageCard) : null
check('U5 ★ 「差评应对」的 chip 承诺「仍照常生效」（能力仍在）',
  !!tc && (tc.chipTip || '').includes('仍照常生效'),
  tc)

// ---- U6：全页不得再出现「仅方法论」（那个词只对「规矩型」为真） ----
check('U6 ★ 页面上不再有「仅方法论」这个说法',
  read.hasYiFaFaLun === false,
  { hasYiFaFaLun: read.hasYiFaFaLun })

// ---- U7：先例「复盘结论写法」也显示「不设卡片」（第 248 轮那条未被误伤） ----
check('U7 「复盘结论写法」同样显示「不设卡片」（第 248 轮那条未受影响）',
  withChip.has(narrativeTitle),
  { withChip: read.withChip })

// ---- U8：★ 对照组 —— 必须有**没有**这个 chip 的技能，否则 chip 无区分度 ----
const withoutChip = (read.titles || []).filter(t => !withChip.has(t))
check('U8 ★ 对照组：存在**没有**该 chip 的技能（否则 chip 无区分度）',
  withoutChip.length > 0,
  { total: read.total, withChip: [...withChip], withoutChipCount: withoutChip.length })

// ---- U9：chip 数量 == 2（两条撤卡技能，不多不少） ----
// ★ 这条防的是"chip 被实现成无条件显示"（那样 U8 也会红，但这条给出了确切口径）。
check('U9 ★ 恰好 2 条技能带该 chip（第 248 轮那条 + 第 295 轮这条）',
  (read.withChip || []).length === 2,
  { withChip: read.withChip })

await shot('skill-repo-narrowing')

const pass = results.filter(r => r.state === 'PASS').length
const fail = results.filter(r => r.state === 'FAIL').length
const skip = results.filter(r => r.state === 'SKIP').length
console.log(`\n---- ${pass}/${results.length} 通过${skip ? `（SKIP ${skip}）` : ''}${fail ? ` · FAIL ${fail}` : ''} ----`)
console.log(`截图：${SHOT_DIR}`)
console.log('末态读数：' + JSON.stringify({
  total: read.total, withChip: read.withChip,
  chipText: tc && tc.chipText, chipTip: tc && tc.chipTip,
  hasYiFaFaLun: read.hasYiFaFaLun,
}))

chrome.kill()
process.exit(fail ? 1 : 0)

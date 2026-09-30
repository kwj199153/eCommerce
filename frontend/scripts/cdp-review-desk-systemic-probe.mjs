// CDP 真机判据（第 294 轮 B 档）—— 「个案 / 系统性判定」必须真的渲染出来，且与后端一致。
//
// 为什么需要真机判据（而不是只看单测）
// ----------------------------------
// 单测证明的是**后端算得对**；前端「有没有把它渲染出来」完全没被覆盖 ——
// 本仓反复踩过这个坑（「后端有端点」≠「前端在用」≠「接上了会渲染」）。
// 所以这里量三件事：
//   ① 区块真的在（DOM 存在 + 几何可见 —— 个数 > 0 不等于看得见）；
//   ② 结论文案取自后端（四个合法 label 之一，不是界面自己编的）；
//   ③ **数值与后端对账**：页面上那个「N 次」与 `systemic-check` 返回的
//      `historical_count` 相等、健康分与 `skus/{sku}/health` 相等。
//      ⇒ 若界面自己算了一份，这一步会红。
//
// 用法：node scripts/cdp-review-desk-systemic-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9382
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r294_systemic')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-systemic-'))
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
    if (targets.some((t) => t.type === 'page')) break
  } catch { /* 还没起来 */ }
  await sleep(300)
}
const page = targets.find((t) => t.type === 'page')
if (!page) { console.log('FAIL: no page'); chrome.kill(); process.exit(1) }

const ws = new WebSocket(page.webSocketDebuggerUrl)
let seq = 0
const pending = new Map()
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
})
await new Promise((res, rej) => {
  ws.addEventListener('open', res)
  ws.addEventListener('error', rej)
})
const send = (method, params = {}) => new Promise((res) => {
  const i = ++seq
  pending.set(i, res)
  ws.send(JSON.stringify({ id: i, method, params }))
})
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400))
  return r?.result?.result?.value
}
const runJson = async (expr) => JSON.parse(await run(expr))
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

// 按文本点最内层可点元素（精确优先，其次包含；取最短 ⇒ 避开外层容器）
const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const exact = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  const loose = all.filter(e => norm(e.textContent).includes(${JSON.stringify(label)}))
  const pool = exact.length ? exact : loose
  if (!pool.length) return JSON.stringify({ err: 'not found' })
  const target = pool.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, text: norm(target.textContent).slice(0, 40) })
})()`

// 判定区块读数（一次拿全，避免多次 evaluate 的时序漂移）
const READ_SECTION = `(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const secs = [...document.querySelectorAll('.rd-section')]
  const sec = secs.find(e => norm(e.querySelector('h4')?.textContent).includes('个案 / 系统性判定'))
  const drawer = document.querySelector('.ant-drawer')
  if (!sec) return JSON.stringify({ found: false, sectionHeads: secs.map(e => norm(e.querySelector('h4')?.textContent)) })
  const tag = sec.querySelector('.ant-tag')
  const kvs = [...sec.querySelectorAll('.rd-kv')].map(e => ({
    k: norm(e.querySelector('.rd-k')?.textContent),
    v: norm(e.querySelector('.rd-v')?.textContent),
  }))
  const warn = sec.querySelector('.rd-warn')
  const btn = warn ? warn.querySelector('button') : null
  const r = sec.getBoundingClientRect()
  // 「补偿方案」块里的依据行
  const compSec = secs.find(e => norm(e.querySelector('h4')?.textContent).includes('处置'))
  const compKvs = compSec ? [...compSec.querySelectorAll('.rd-kv')].map(e => ({
    k: norm(e.querySelector('.rd-k')?.textContent),
    v: norm(e.querySelector('.rd-v')?.textContent),
  })) : []
  return JSON.stringify({
    found: true,
    tagText: tag ? norm(tag.textContent) : null,
    kvs, compKvs,
    warnText: warn ? norm(warn.textContent).slice(0, 200) : null,
    adoptBtn: btn ? norm(btn.textContent) : null,
    rect: { w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y) },
    inViewport: r.width > 0 && r.height > 0 && r.top >= -1 && r.left >= -1 && r.bottom <= innerHeight + 2,
    drawer: !!drawer,
  })
})()`

// 后端对账：在**页面上下文**里直接请求（同源、走 vite 代理），带 X-Shop-ID
const BACKEND_COMPARE = `(async () => {
  const shop = localStorage.getItem('current_shop_id')
  const h = { 'X-Shop-ID': shop || '' }
  const list = await (await fetch('/api/v1/trade/reviews?max_rating=3&days=30&limit=5', { headers: h })).json()
  const rid = (list.items || [])[0]?.id
  if (!rid) return JSON.stringify({ err: 'no review in list', shop, total: list.total })
  const sc = await (await fetch('/api/v1/trade/reviews/' + encodeURIComponent(rid) + '/systemic-check', { headers: h })).json()
  let health = null
  if (sc.sku) health = await (await fetch('/api/v1/trade/skus/' + encodeURIComponent(sc.sku) + '/health', { headers: h })).json()
  return JSON.stringify({ shop: !!shop, rid, sc, health })
})()`

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(4200)

// ---------------------------------------------------------------- T0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('T0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

// ---------------------------------------------------------------- 进入差评工作台
await run(clickByText('智能客服'))
await sleep(1700)
await run(clickByText('差评台账'))
await sleep(2200)

const listInfo = await runJson(`(() => {
  const rows = [...document.querySelectorAll('.rd-item, .rd-table tbody tr')]
  return JSON.stringify({ rdRoot: !!document.querySelector('.rd-root'), rowCount: rows.length,
    firstRowText: rows[0] ? (rows[0].textContent||'').replace(/\\s+/g,' ').trim().slice(0, 60) : null })
})()`)
check('T1', '差评工作台面板已打开且有差评行', listInfo.rdRoot === true && listInfo.rowCount > 0, listInfo)

// 点开第一条差评 → 抽屉
const rowHit = await run(`(() => {
  const rows = [...document.querySelectorAll('.rd-item, .rd-table tbody tr')]
  if (!rows.length) return JSON.stringify({ err: 'no row' })
  rows[0].click()
  return JSON.stringify({ ok: true })
})()`)
await sleep(2600)

const sec = await runJson(READ_SECTION)
check('T2', '抽屉已打开（点开一条差评后）', sec.drawer === true, { drawer: sec.drawer, heads: sec.sectionHeads || [] })
check('T3', '抽屉里出现「🔎 个案 / 系统性判定」区块', sec.found === true, sec.sectionHeads || sec)

// ★ 「存在≠可见」：几何必须非零且在视口内
check('T4', '判定区块几何可见（w>0 && h>0 && 在视口内）',
  sec.found === true && sec.rect?.w > 0 && sec.rect?.h > 0 && sec.inViewport === true,
  sec.rect ? { ...sec.rect, inViewport: sec.inViewport } : null)

// 结论文案必须取自后端（四个合法 label 之一）
const LEGAL = ['个案', '重复问题', '系统性风险', '判不出（缺归因）']
check('T5', '判定结论 tag 是后端给的 label（不是界面自编）',
  !!sec.tagText && LEGAL.includes(sec.tagText), { tagText: sec.tagText, legal: LEGAL })

const kvKeys = (sec.kvs || []).map((x) => x.k)
check('T6', '判定区块含「同因历史」与「SKU 健康分」两行',
  kvKeys.includes('同因历史') && kvKeys.includes('SKU 健康分'), { kvKeys })

// ---------------------------------------------------------------- 后端对账
const cmp = await runJson(BACKEND_COMPARE)
if (cmp.err) {
  check('T7', '与后端对账（historical_count / threshold / 健康分）', null, cmp)
} else {
  const histRow = (sec.kvs || []).find((x) => x.k === '同因历史')
  const healthRow = (sec.kvs || []).find((x) => x.k === 'SKU 健康分')
  const pageHist = histRow ? Number((histRow.v.match(/(\d+)\s*次/) || [])[1]) : NaN
  const pageThr = histRow ? Number((histRow.v.match(/阈值\s*≥\s*(\d+)\s*次/) || [])[1]) : NaN
  const pageScore = healthRow ? (healthRow.v.match(/^([\d.]+)/) || [])[1] : null
  const beScore = cmp.health && cmp.health.found ? String(cmp.health.health_score) : null
  const ok =
    (cmp.sc.ready === false || pageHist === cmp.sc.historical_count) &&
    pageThr === cmp.sc.threshold &&
    (beScore === null || pageScore === beScore)
  check('T7', '★ 与后端对账：页面数值 == 端点返回值（界面没自算）', ok, {
    pageHist, beHist: cmp.sc.historical_count,
    pageThr, beThr: cmp.sc.threshold,
    pageScore, beScore, verdict: cmp.sc.verdict, verdictLabel: cmp.sc.verdict_label,
  })
  check('T8', '页面 tag 文本 == 端点 verdict_label',
    sec.tagText === cmp.sc.verdict_label, { tagText: sec.tagText, beLabel: cmp.sc.verdict_label })
}

// ---------------------------------------------------------------- 补偿依据（有处置时）
const compKv = sec.compKvs || []
const hasComp = compKv.some((x) => x.k === '补偿方案' || x.v)
check('T9', '处置块出现时，「依据」行（归因 / 命中规则）同时出现',
  hasComp ? compKv.some((x) => x.k === '依据') : null, { compKvs: compKv })

await shot('systemic-section')

// 关键读数（留痕：老板要看的是**真机上的数**，不是「PASS」两个字）
console.log('\n关键读数：', JSON.stringify({
  sectionTag: sec.tagText,
  sectionKvs: sec.kvs,
  dispositionKvs: sec.compKvs,
  adoptBtn: sec.adoptBtn,
  warnText: sec.warnText,
  rect: sec.rect,
  backend: cmp.err ? cmp : {
    review_id: cmp.rid,
    historical_count: cmp.sc.historical_count,
    threshold: cmp.sc.threshold,
    verdict: cmp.sc.verdict,
    verdict_label: cmp.sc.verdict_label,
    recommend_escalate: cmp.sc.recommend_escalate,
    reason: cmp.sc.reason,
    health_found: cmp.health?.found,
    health_score: cmp.health?.health_score,
    health_delta: cmp.health?.delta,
    health_negative_rate: cmp.health?.negative_rate,
  },
}, null, 2))

// ---------------------------------------------------------------- 汇总
const failed = results.filter((r) => r.state === 'FAIL')
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过（SKIP 不计入失败）----`)
console.log('截图：', SHOT_DIR)
chrome.kill()
process.exit(failed.length ? 1 : 0)

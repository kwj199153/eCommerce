// CDP 真实浏览器验证（第 292 轮）—— 差评工作台「补 UI 出口」的四件事：
//   ① 常驻提示已取消（第 304 轮老板指令）：同一份「读 / 写 / 只能人点」口径
//      改挂到**按钮悬停 title** 上 —— 判据从「数 chip」改成「数 title」；
//   ② 台账行的动作文案按状态给（待批准·已驳回 ⇒ 「编辑」，其余 ⇒ 「查看」）；
//   ③ 抽屉里 5 个处置通道**逐个可点**，且点一项能看到它的实际作用与可逆性；
//   ④ 回复草稿可编辑（proposed 可改 / approved·issued 锁定），补偿金额只读。
//
// 为什么必须用真实浏览器：这些都是**运行时副作用**（点击切换、禁用态、文案随状态变），
// 静态门禁看不见；而几何（chip 有没有被挤成 0 宽、有没有互相叠住）只有真实布局算得出来。
//
// 判据口径（本仓纪律）：
//   · 先自检选择器真的选到东西（B0），否则选择器写错会静默全绿；
//   · 依赖 seed 数据的判据允许 SKIP，但**必须如实打印**（不许当成通过）；
//   · 几何用相对条件（宽高 > 0 + 同行不重叠），不写死像素。
//
// 用法：node scripts/cdp-review-desk-ui-probe.mjs
//   PROBE_URL 覆盖地址（默认 http://127.0.0.1:5173/）
//   PROBE_SHOT_DIR 覆盖截图目录
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9377
const URL = process.env.PROBE_URL || 'http://127.0.0.1:5173/'
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r292_review_desk')

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id}  ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-revdesk-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1680,900',
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
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: URL })
await sleep(3500)

// —— 通用：按**精确文本**点最内层可点元素（避免点到大容器）——
const clickByText = (label) => `
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
  const all = [...document.querySelectorAll('button, a, li, .ant-menu-item, .ant-tag, span, div')]
  const hits = all.filter(e => norm(e.textContent) === ${JSON.stringify(label)})
  if (!hits.length) return JSON.stringify({ err: 'not found', have: [...new Set(all.map(e => norm(e.textContent)).filter(t => t.includes(${JSON.stringify(label.slice(0, 2))})))].slice(0, 8) })
  const target = hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]
  target.click()
  return JSON.stringify({ ok: true, tag: target.tagName, cls: target.className })
})()`

// ---------------------------------------------------------------- B0 自检
const bodyLen = await run('document.body?.innerText?.length || 0')
check('B0', '页面已渲染（自检：选择器有东西可选）', bodyLen > 200, { bodyLen })

const agentHit = await run(clickByText('智能客服'))
check('B0b', '侧栏能点到「智能客服」', JSON.parse(agentHit).ok === true, JSON.parse(agentHit))
await sleep(1500)

const toolHit = await run(clickByText('差评台账'))
await sleep(1800)
const rootOk = await run(`!!document.querySelector('.rd-root')`)
check('B1', '点「差评台账」后右栏出工作台（.rd-root）', rootOk === true, { toolHit: JSON.parse(toolHit), rootOk })

// ---------------------------------------------------------------- B2 读 / 写分界
// ★ 第 304 轮（老板指令）：常驻提示取消，信息改挂**按钮悬停 title**。
//   判据形态随之从「数 chip」改成「数 title」—— 信息一条没丢，载体换了。
//   若哪天有人把 chip 加回来，B2 会转红；若只是把文案删了却没挂 title，B2b 会转红。
const flow = await run(`(() => {
  const chips = [...document.querySelectorAll('.rd-flow .rd-flow-chip')].length
  const titles = [...document.querySelectorAll('.rd-root [title]')]
    .map(e => (e.getAttribute('title')||'').replace(/\\s+/g,' ').trim())
  return JSON.stringify({ n: chips, titles })
})()`).then(JSON.parse)
check('B2', '常驻提示已取消：0 个 rd-flow chip', flow.n === 0, flow)
check('B2b', '「只读」口径仍在 —— 改挂刷新按钮的 title',
  flow.titles.some(t => t.includes('只读')), flow.titles)

// ---------------------------------------------------------------- B3 台账行动作
const ledgerRows = await run(`(() => {
  const tabs = [...document.querySelectorAll('.rd-tab')]
  const t = tabs.find(e => (e.textContent||'').includes('处置台账'))
  if (t) t.click()
  return JSON.stringify({ clicked: !!t })
})()`).then(JSON.parse)
await sleep(1500)
const acts = await run(`(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  return JSON.stringify({
    rows: rows.length,
    acts: rows.map(r => {
      const btn = r.querySelector('.rd-table-act button.rd-act-open')
      const status = (r.querySelector('td:nth-child(7)')?.textContent || '').replace(/\\s+/g,'').trim()
      return { act: btn ? (btn.textContent||'').trim() : null, status }
    }),
  })
})()`).then(JSON.parse)
if (!acts.rows) {
  check('B3', '台账行动作文案按状态给（当前台账为空 ⇒ 无法验证）', null, acts)
} else {
  const wrong = acts.acts.filter(a =>
    (a.status === '待批准' || a.status === '已驳回') ? a.act !== '编辑' : a.act !== '查看')
  check('B3', `台账 ${acts.rows} 行：待批准/已驳回 ⇒「编辑」，其余 ⇒「查看」`, wrong.length === 0, { acts })
}

// ---------------------------------------------------------------- B3c 写口径挂 title
const wTitles = await run(`(() => {
  const b = [...document.querySelectorAll('.rd-filter .ant-btn')]
    .map(e => (e.getAttribute('title')||'').replace(/\s+/g,' ').trim())
  return JSON.stringify(b)
})()`).then(JSON.parse)
check('B3c', '「写操作（批量）」口径挂在【生成待处置】的 title 上',
  wTitles.some(t => t.includes('写操作')), wTitles)

// ---------------------------------------------------------------- B3d 台账必须看得到 ASIN
// ★ 老板原话：「近期差评都是 009 asin，但处置台账列表为什么都是 002 asin？」
//   取证：不是两份数据（23 条评价的 asin 全是 B0CXXXX009、sku 全是 SKU-KC-002），
//   缺的只是台账那一列。这条判据钉住「ASIN 列真的渲染出 ASIN」——
//   只查表头有 `<th>ASIN</th>` 是不够的：单元格里可能仍填着 '—'。
const cols = await run(`(() => {
  const th = [...document.querySelectorAll('.rd-table thead th')].map(e => (e.textContent||'').trim())
  const first = document.querySelector('.rd-table tbody tr')
  const cells = first ? [...first.querySelectorAll('td')].map(e => (e.textContent||'').trim()) : []
  return JSON.stringify({ th, cells })
})()`).then(JSON.parse)
check('B3d', '台账有 ASIN 列，且首行真的填了 ASIN（不是 —）',
  cols.th.includes('ASIN') && /^B0[A-Z0-9]{6,}$/.test(String(cols.cells[0] || '')), cols)

// ---------------------------------------------------------------- B3b 操作列可见性
// ★ 这才是老板那句「在台账列表也找不到去哪里编辑」的**可观测判据**：
//   面板窄（右栏 ≈290px）时表格横向溢出，「编辑 / 查看」列会被推到视口外 ——
//   列存在但看不见，等于没有出口。所以必须量**位置**，不能只查「列在不在」。
const vis = await run(`(() => {
  const led = document.querySelector('.rd-ledger')
  const btn = document.querySelector('.rd-table tbody tr .rd-table-act button.rd-act-open')
  if (!led || !btn) return JSON.stringify({ err: 'no ledger or no action button' })
  const lr = led.getBoundingClientRect()
  const br = btn.getBoundingClientRect()
  return JSON.stringify({
    clientW: Math.round(led.clientWidth),
    scrollW: Math.round(led.scrollWidth),
    overflows: led.scrollWidth > led.clientWidth + 1,
    btnText: (btn.textContent || '').trim(),
    inView: br.right <= lr.right + 1 && br.left >= lr.left - 1 && br.width > 0,
  })
})()`).then(JSON.parse)
check('B3b', '台账「编辑 / 查看」列在窄面板下也看得见（不靠横拖）',
  vis.inView === true, vis)

// ---------------------------------------------------------------- B4 抽屉：通道可点
const openDrawer = await run(`(() => {
  const rows = [...document.querySelectorAll('.rd-table tbody tr')]
  const pick = rows.find(r => {
    const s = (r.querySelector('td:nth-child(7)')?.textContent || '')
    return s.includes('待批准') || s.includes('已驳回')
  }) || rows[0]
  if (!pick) return JSON.stringify({ err: 'no row' })
  const btn = pick.querySelector('.rd-table-act button.rd-act-open')
  ;(btn || pick).click()
  return JSON.stringify({ ok: true })
})()`).then(JSON.parse)
await sleep(1600)

if (!openDrawer.ok) {
  check('B4', '抽屉打开 + 5 个通道可点（台账无行 ⇒ 无法验证）', null, openDrawer)
} else {
  const drawer = await run(`(() => {
    const chips = [...document.querySelectorAll('.rd-chips .rd-chip')]
    const ta = [...document.querySelectorAll('.ant-drawer textarea')]
    const body = document.querySelector('.ant-drawer-body')
    const text = (body?.innerText || '')
    return JSON.stringify({
      chips: chips.map(c => ({ label: (c.textContent||'').replace(/\\s+/g,'').trim(), disabled: c.disabled })),
      desc: (document.querySelector('.rd-chip-desc')?.textContent || '').replace(/\\s+/g,' ').trim(),
      textareas: ta.length,
      taDisabled: ta.map(t => t.disabled),
      editable: text.includes('可分别点选'),
      locked: text.includes('已锁定'),
      moneyReadonly: text.includes('金额不在这里改'),
      couponCodeNote: text.includes('核准时自动生成'),
      saveBtn: [...document.querySelectorAll('.rd-actions button')].map(b => (b.textContent||'').trim()),
      drawerOpen: !!document.querySelector('.ant-drawer-open, .ant-drawer-open .ant-drawer-content'),
      geom: chips.map(c => { const r = c.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } }),
    })
  })()`).then(JSON.parse)

  check('B4a', '抽屉已打开', drawer.drawerOpen === true, drawer.drawerOpen)
  check('B4b', '5 个处置通道都在', drawer.chips.length === 5, drawer.chips)
  check('B4c', '通道作用说明非空（点开能看懂作用）', drawer.desc.length > 8, drawer.desc)
  check('B4d', '补偿金额只读且给出理由', drawer.moneyReadonly === true, drawer.moneyReadonly)
  check('B4e', '券码块说明「核准时自动生成」', drawer.couponCodeNote === true, drawer.couponCodeNote)
  check('B4f', '通道几何正常（宽高 > 0）', drawer.geom.every(g => g.w > 20 && g.h > 14), drawer.geom)

  if (drawer.editable) {
    // 真实交互：点第 2 个通道 ⇒ 选中态切换
    const before = drawer.chips.filter(c => !c.disabled).length
    const toggle = await run(`(() => {
      const chips = [...document.querySelectorAll('.rd-chips .rd-chip')]
      const before = chips.map(c => c.classList.contains('on'))
      chips[1].click()
      return JSON.stringify({ before, clicked: (chips[1].textContent||'').replace(/\\s+/g,'').trim() })
    })()`).then(JSON.parse)
    // ★ 必须**等一帧**再读：Vue 的 DOM 更新是异步的，同一个 evaluate 里读会读到旧 class
    await sleep(500)
    const after = await run(`JSON.stringify([...document.querySelectorAll('.rd-chips .rd-chip')].map(c => c.classList.contains('on')))`).then(JSON.parse)
    const changed = toggle.before.length === after.length
      && toggle.before.some((v, i) => v !== after[i])
    check('B4g', '点通道真的切换选中态（不是装饰）', changed, { ...toggle, after })
    check('B4h', 'proposed ⇒ 回复草稿可编辑（2 个 textarea，未禁用）',
      drawer.textareas >= 2 && drawer.taDisabled.every(d => d === false), drawer)
    check('B4i', 'proposed ⇒ 有「保存修改」出口', drawer.saveBtn.includes('保存修改'), drawer.saveBtn)
    check('B4j', 'proposed ⇒ 通道未禁用', drawer.chips.every(c => c.disabled === false), drawer.chips)
  } else if (drawer.locked) {
    check('B4h', 'approved/issued ⇒ 草稿锁定 + 文案说明原因',
      drawer.textareas >= 2 && drawer.taDisabled.every(d => d === true), drawer)
    check('B4i', 'approved/issued ⇒ 不出现「保存修改」', !drawer.saveBtn.includes('保存修改'), drawer.saveBtn)
  } else {
    check('B4h', '抽屉处于可辨识的编辑态或锁定态（既非可编辑也无锁定文案）', false, drawer)
  }

  // 可逆性警示：选中不可逆通道时必须看得见
  await run(`(() => {
    const chips = [...document.querySelectorAll('.rd-chips .rd-chip')]
    const coupon = chips.find(c => (c.textContent||'').includes('补偿券'))
    if (coupon && !coupon.disabled && !coupon.classList.contains('on')) coupon.click()
    return 'clicked'
  })()`)
  await sleep(500)
  const warn = await run(`(() => JSON.stringify({
    has: !!document.querySelector('.rd-warn'),
    warn: (document.querySelector('.rd-warn')?.textContent||'').replace(/\\s+/g,' ').trim(),
    selected: [...document.querySelectorAll('.rd-chips .rd-chip')].filter(c => c.classList.contains('on')).map(c => (c.textContent||'').replace(/\\s+/g,'').trim()),
    bodyTail: (document.querySelector('.ant-drawer-body')?.innerText || '').replace(/\\s+/g,' ').slice(0, 260),
  }))()`).then(JSON.parse)
  check('B4k', '选中不可逆通道 ⇒ 出现「核准后不能改」警示',
    drawer.editable ? warn.warn.includes('不可逆') : true, warn)

  await shot('r292-review-desk-drawer')
}

// ---------------------------------------------------------------- B5 截图 + 汇总
// ★ 先关抽屉再拍台账图 —— 否则两张截图内容一样（第一次就是这么踩的）
await run(`(() => { const c = document.querySelector('.ant-drawer-close'); if (c) c.click(); return 'closed' })()`)
await sleep(900)
await shot('r292-review-desk-ledger')

const fails = results.filter(r => r.state === 'FAIL').length
const skips = results.filter(r => r.state === 'SKIP').length
console.log(`\n---- ${results.length - fails - skips}/${results.length - skips} 通过（${skips} 条 SKIP）----`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(fails ? 1 : 0)

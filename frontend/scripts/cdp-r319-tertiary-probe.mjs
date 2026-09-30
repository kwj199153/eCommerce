// CDP 真机探针 —— `--text-tertiary` 三主题提亮（WCAG 对比度实测 + 反向注入对照）。
//
// 为什么这个判据不能静态做（三条，与 cdp-dark-contrast.mjs 同源）：
//   ① `vue-tsc` / `vite build` / 单测**全都不报** —— 它们是颜色值，不是类型错误；
//   ② 同一句 `color: var(--text-tertiary)` 在浅色下 3.36:1、深色下 4.40:1
//      ⇒ 判据必须**带上"当时是哪个主题"**；
//   ③ `check-theme-var-refs.py` 只管「引用的名字是否存在」，值够不够黑是它的盲区。
//
// 本探针要钉的三件事：
//   · **值**：三个主题的 `--text-tertiary` 计算值 == 规格值（antd token 也钉成同一值）；
//   · **读得到**：三个主题各自都能在真实页面上**找到**用该色的文字节点（否则 = 空扫恒绿）；
//   · **够黑**：light / dark 的最差节点 ≥ 4.5:1（AA）；macaron ≥ 4.0:1（天花板见下）。
//
// ★ macaron 为什么只判 4.0：它的 `--text-tertiary` 必须比 `--text-secondary`(#7d6a72)
//   更浅，而 secondary 自己在粉底上只有 4.72:1 ⇒ tertiary **结构上**到不了 4.5。
//   探针把这条**如实写成 4.0 的阈值 + 一条"天花板"断言**，而不是把阈值悄悄降到 4.5 以下
//   却仍叫它 AA（那是「三态压两态 = 静默洗白」的同类错误）。
//
// ★ 多路由扫描：单页扫不到 ≠ 没这个色。第一个版本只扫 `/subscription`，实测命中 0 个节点
//   （T2 红），而 `--text-tertiary` 全仓 324 处消费点主要不在订阅页 ⇒ 单页会让判据**空跑**。
//   故改成按路由清单逐页累计，并把「每个主题总命中数 ≥ 3」当硬判据。
//
// 用法：
//   node scripts/cdp-r319-tertiary-probe.mjs           判定（有不达标 ⇒ 退出码 1）
//   node scripts/cdp-r319-tertiary-probe.mjs --report  只打印盘面、不判定
//   PROBE_DIAG=1 …                                     额外打印每页颜色直方图（定位用）
//   PROBE_ROUTES=/a,/b 覆盖路由清单
import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const CHROME = 'C:\\Users\\Administrator\\.agent-browser\\browsers\\chrome-153.0.8010.36\\chrome.exe'
const PORT = 9393
const ORIGIN = process.env.PROBE_ORIGIN || 'http://127.0.0.1:5173'
// ★ 坑 ⑤（本轮新踩）：**Git Bash 会把 `PROBE_ROUTES=/subscription` 里的 `/subscription`
//   当成 POSIX 绝对路径，翻转成 `C:/Users/.../PortableGit/versions/1.2.0/subscription`**
//   ⇒ `ORIGIN + path` 变成非法 URL ⇒ 导航失败、停在 about:blank ⇒
//   `--text-tertiary` 读到 null、命中 0 个节点（**看起来像"页面没这个色"，实际是没打开页面**）。
//   故：路由一律取 basename 再补前导 `/`，并额外断言「落地 pathname == 请求路由」。
const normRoute = (p) => {
  const seg = String(p).split(/[\\/]/).filter(Boolean)
  return '/' + (seg.length ? seg[seg.length - 1] : '')
}
const ROUTES = (process.env.PROBE_ROUTES || '/')
  .split(',').map(s => s.trim()).filter(Boolean).map(normRoute)

// ★ 为什么还要「点一下」：`--text-tertiary` 的消费点**不在路由页面上** ——
//   实测 `/subscription` 的 796 字里一个都没有（light 直方图 43 处是 --text-secondary），
//   全仓最大的消费方住在「资料库」各库视图里（ProductLibrary 17 / PlatformRules 18），
//   而它们是在 `/` 里靠**侧栏切换 view**挂载的，不是独立路由。
//   不点这一下 ⇒ 命中 0 个节点 ⇒ T1/T2/T3 全是空跑（"看着像业务没问题"）。
const CLICK_TEXT = (process.env.PROBE_CLICK === '' ? '' : (process.env.PROBE_CLICK || '自有产品库')).trim()
const SHOT_DIR = process.env.PROBE_SHOT_DIR
  || join(process.cwd(), '..', '.workbuddy', 'probes', 'r319_tertiary')
const REPORT_ONLY = process.argv.includes('--report')
const DIAG = !!process.env.PROBE_DIAG

// 规格表（真源 = frontend/src/theme/presets.ts；改真源必须同步这张表，否则本探针会红）
// ★ macaron 的 min 是**棘轮**而非 AA 声明：它的 tertiary 结构上到不了 4.5（见文件头），
//   3.8 = 本轮真机达成值（修掉 `.pl-group-count` 把 --border-base 当底色之后）。
const SPEC = {
  light:   { var: '#6c6c6c',                    rgb: [108, 108, 108, 1],     min: 4.5 },
  dark:    { var: 'rgba(255, 255, 255, 0.52)',  rgb: [255, 255, 255, 0.52],  min: 4.5 },
  macaron: { var: '#827379',                    rgb: [130, 115, 121, 1],     min: 3.8 },
}
const THEMES = Object.keys(SPEC)

const sleep = ms => new Promise(r => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  results.push({ id, name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${id}  ${name}${ok ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

if (!existsSync(CHROME)) { console.log(`FAIL: 找不到 chrome：${CHROME}`); process.exit(2) }
mkdirSync(SHOT_DIR, { recursive: true })

const profile = mkdtempSync(join(tmpdir(), 'cdp-r319-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
  `--user-data-dir=${profile}`, '--window-size=1440,900',
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

// ★ 坑 ①（本仓已踩过）：`norm` 只定义在某个包装里，裸 run() 里用它 = ReferenceError
//   ⇒ 后续 `if (btn)` 恒 undefined ⇒ 点击变**空操作且不报错**（下游假红 + 「点完归零」型断言恒真假绿）。
//   故公共片段抽成 NORM_SRC，统一走 runN()。
const NORM_SRC = `
const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim()
const flat = (s) => norm(s).replace(/\\s+/g, '')
`
const run = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  if (r?.result?.exceptionDetails) return 'EXC: ' + String(r.result.exceptionDetails.exception?.description || '').slice(0, 400)
  return r?.result?.result?.value
}

// ====== 注入到页面里的对比度引擎 ======
// ★ 住在 HELPERS **模板串**里 ⇒ 注释里**不能出现反引号**（会提前闭合串）。
const HELPERS = `
const parseColor = (s) => {
  const m = String(s || '').match(/rgba?\\(([^)]+)\\)/)
  if (!m) return null
  const p = m[1].split(/[,\\s\\/]+/).filter(x => x !== '').map(Number)
  if (p.length < 3 || p.some(isNaN)) return null
  return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]
}
const hexToRgb = (s) => {
  const m = String(s || '').trim().match(/^#([0-9a-fA-F]{6})$/)
  if (!m) return null
  const h = m[1]
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), 1]
}
const anyColor = (s) => parseColor(s) || hexToRgb(s)
const blend = (f, b) => [
  f[0] * f[3] + b[0] * (1 - f[3]),
  f[1] * f[3] + b[1] * (1 - f[3]),
  f[2] * f[3] + b[2] * (1 - f[3]),
  1,
]
const lum = (c) => {
  const g = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
  return 0.2126 * g(c[0]) + 0.7152 * g(c[1]) + 0.0722 * g(c[2])
}
const ratio = (a, b) => {
  const l1 = lum(a), l2 = lum(b)
  const hi = Math.max(l1, l2), lo = Math.min(l1, l2)
  return (hi + 0.05) / (lo + 0.05)
}
const gradStops = (bi) => {
  const out = []; const re = /rgba?\\([^)]+\\)/g; let m
  while ((m = re.exec(bi))) out.push(m[0])
  return out
}
const rootBg = (() => {
  for (const el of [document.documentElement, document.body]) {
    const c = parseColor(getComputedStyle(el).backgroundColor)
    if (c && c[3] >= 0.999) return c
  }
  return [255, 255, 255, 1]
})()
const bgCandidates = (el) => {
  const layers = []
  let n = el
  while (n && n.nodeType === 1) {
    const cs = getComputedStyle(n)
    const bc = parseColor(cs.backgroundColor) || [0, 0, 0, 0]
    const bi = cs.backgroundImage || 'none'
    const stops = bi.includes('gradient') ? gradStops(bi).map(parseColor).filter(Boolean) : []
    layers.push({ bc, stops })
    if (bc[3] >= 0.999 && !stops.length) break
    n = n.parentElement
  }
  let bases = [rootBg]
  for (let i = layers.length - 1; i >= 0; i--) {
    const L = layers[i]
    const cands = L.stops.length ? L.stops : [L.bc]
    const next = []
    for (const b of bases) for (const c of cands) next.push(blend(c, b))
    bases = next
  }
  return bases
}
const worstContrast = (el) => {
  const cs = getComputedStyle(el)
  const fgRaw = parseColor(cs.color)
  if (!fgRaw) return null
  const bgs = bgCandidates(el)
  let worst = Infinity, bg = null
  for (const b of bgs) {
    const r = ratio(blend(fgRaw, b), b)
    if (r < worst) { worst = r; bg = b }
  }
  const fs = parseFloat(cs.fontSize)
  const fw = parseInt(cs.fontWeight, 10) || 400
  const large = fs >= 24 || (fs >= 18.66 && fw >= 700)
  return {
    ratio: Math.round(worst * 100) / 100,
    need: large ? 3 : 4.5,
    size: fs, weight: fw,
    color: cs.color,
    bg: 'rgb(' + bg.map(v => Math.round(v)).join(', ') + ')',
  }
}
const visibleTextEls = () => [...document.querySelectorAll('*')].filter((e) => {
  const own = [...e.childNodes].some((n) => n.nodeType === 3 && (n.textContent || '').trim())
  if (!own) return false
  const cs = getComputedStyle(e)
  if (cs.visibility === 'hidden' || cs.display === 'none') return false
  if (parseFloat(cs.opacity) < 0.05) return false
  const r = e.getBoundingClientRect()
  if (r.width < 1 || r.height < 1) return false
  return !!parseColor(cs.color)
})
// antd 的 cssinjs 哈希类**按主题算法生成**，跨主题配对会全都配不上 ⇒ 一律剔掉
const descOf = (e) => {
  const cls = (typeof e.className === 'string' ? e.className : '')
    .split(/\\s+/).filter(Boolean).filter((c) => !c.startsWith('css-')).slice(0, 2).join('.')
  return e.tagName.toLowerCase() + (cls ? '.' + cls : '')
}
// ★ 本探针的核心取数：只挑**计算色 == 该主题 --text-tertiary** 的文字节点
const tertiaryNodes = () => {
  const tv = anyColor(getComputedStyle(document.documentElement).getPropertyValue('--text-tertiary'))
  if (!tv) return { tv: null, nodes: [], histogram: {} }
  const same = (a) => Math.abs(a[0] - tv[0]) < 1 && Math.abs(a[1] - tv[1]) < 1
    && Math.abs(a[2] - tv[2]) < 1 && Math.abs(a[3] - tv[3]) < 0.02
  const out = []
  const hist = {}
  for (const e of visibleTextEls()) {
    const cs = getComputedStyle(e)
    const c = parseColor(cs.color)
    if (!c) continue
    const k = cs.color
    hist[k] = (hist[k] || 0) + 1
    if (!same(c)) continue
    const info = worstContrast(e)
    if (!info) continue
    const cls = typeof e.className === 'string' ? e.className : ''
    out.push({ sel: descOf(e), antd: /(^|\\s)ant-/.test(cls), text: norm(e.textContent).slice(0, 22), ...info })
  }
  const top = Object.entries(hist).sort((a, b) => b[1] - a[1]).slice(0, 12)
  return { tv: tv.map((v, i) => (i === 3 ? Math.round(v * 100) / 100 : Math.round(v))), nodes: out, histogram: top }
}
`

const evalJson = async (body) => {
  // ★ HELPERS 必须拼进来 —— 漏了它 `tertiaryNodes` 就是 undefined，
  //   而 `JSON.parse('EXC: ...')` 会直接抛错（比"静默空跑"好，但同样不是判据）。
  const raw = await run(`(() => { ${NORM_SRC} ${HELPERS}\n${body} })()`)
  if (typeof raw !== 'string' || raw.startsWith('EXC:')) throw new Error('页面求值失败：' + raw)
  return JSON.parse(raw)
}

const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  if (r?.result?.data) writeFileSync(join(SHOT_DIR, `${name}.png`), Buffer.from(r.result.data, 'base64'))
}

await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

let seedSid = null
async function openWith(mode, path) {
  // ★ 每轮先清上一轮的 addScriptToEvaluateOnNewDocument，否则第二轮 localStorage 会被
  //   第一轮脚本**再写一遍**（先注入先执行，后写的赢）⇒ 主题切换静默失效
  if (seedSid) await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: seedSid })
  const r = await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      localStorage.setItem('access_token', 'demo-token');
      localStorage.setItem('refresh_token', 'demo-refresh-token');
      localStorage.setItem('theme_mode', ${JSON.stringify(mode)});
      localStorage.setItem('user_info', ${JSON.stringify(JSON.stringify({ id: 'demo-user-001', email: 'demo@ecommerce.ai', name: '演示用户', role: 'admin' }))});
    `,
  })
  seedSid = r?.result?.identifier
  // ★ 导航重试：改过源码后 Vite 会整页重载，**紧接着的第一次 navigate 可能落在 about:blank**
  //   （实测踩到：`path: "blank", textLen: 0`）。重试一次；两次都不行就交给落地断言报红
  //   —— 「页面没打开」必须表现为一条 FAIL，而不是让探针在后面撞 null 崩掉。
  for (let attempt = 0; attempt < 2; attempt++) {
    await send('Page.navigate', { url: ORIGIN + path })
    // 20 轮 × 1s 上限：再多也只是把"页面根本没打开"拖成 40s，不如早点交给落地断言报出来
    for (let i = 0; i < 20; i++) {
      const n = await run('(document.body && document.body.innerText || "").length')
      if (typeof n === 'number' && n > 100) break
      await sleep(1000)
    }
    await sleep(1200)
    const at = await run('location.pathname')
    if (at && at !== 'blank') break
    await sleep(2500)
  }
  return evalJson(`
    const el = document.documentElement
    return JSON.stringify({
      darkClass: el.classList.contains('dark'),
      dataTheme: el.getAttribute('data-theme'),
      path: location.pathname,
      textLen: norm(document.body.innerText || '').length,
    })
  `)
}

// ---- L0：引擎自检（公式写错会让全页恒绿）----
const engine = await evalJson(`
  return JSON.stringify({
    blackOnWhite: Math.round(ratio([0, 0, 0, 1], [255, 255, 255, 1]) * 100) / 100,
    hexParsed: hexToRgb('#6c6c6c'),
    halfOnBlack: Math.round(ratio(blend([255, 255, 255, 0.5], [0, 0, 0, 1]), [0, 0, 0, 1]) * 100) / 100,
  })
`)
check('L0a', '对比度引擎自检（黑/白 = 21:1，且 hex 解析器可用）',
  Math.abs(engine.blackOnWhite - 21) < 0.05
  && JSON.stringify(engine.hexParsed) === JSON.stringify([108, 108, 108, 1]), engine)

const summary = {}
for (const mode of THEMES) {
  const nodes = []
  const byRoute = {}
  let themeOk = true
  let themeDetail = null
  let landedAny = false

  for (const path of ROUTES) {
    const applied = await openWith(mode, path)
    if (path === ROUTES[0]) await shot(`${mode}_00_page`)
    // ★ 前提自检：先证明「页面真的打开了」，再谈它的颜色 —— 否则导航失败会伪装成
    //   「这一页没用 --text-tertiary」（命中 0），把「探针打错目标」误报成「业务没问题」。
    const landed = applied.path === path && applied.textLen > 100
    check(`L1-${mode}${path}`, `${mode} 导航落到 ${path}（实测 ${applied.path}，正文 ${applied.textLen} 字）`,
      landed, applied)
    if (!landed) {
      themeOk = false
      themeDetail = { requested: path, ...applied }
      byRoute[path] = 'MISS'
      continue
    }
    landedAny = true
    const ok = mode === 'dark'
      ? (applied.darkClass === true && applied.dataTheme === 'dark')
      : (applied.dataTheme === mode && applied.darkClass === false)
    if (!ok) { themeOk = false; themeDetail = applied }

    // ---- 点侧栏切到「资料库」某库（否则 tertiary 消费点根本不挂载）----
    if (CLICK_TEXT) {
      const clickInfo = await evalJson(`
        const want = flat(${JSON.stringify(CLICK_TEXT)})
        const items = [...document.querySelectorAll('.ant-menu-item')]
        const el = items.find(e => flat(e.textContent) === want)
        if (el) el.click()
        return JSON.stringify({ found: !!el, total: items.length, before: norm(document.body.innerText || '').length })
      `)
      // ★ 不能只 sleep 固定时长：资料库的数据是异步拉的，等短了主区还没渲染
      //   ⇒ 命中节点数会在 10~74 之间跳（同样代码两轮读数不同 = 判据不稳）。
      //   改成**轮询到主区内容真的长出来**，并把 before/after 字数写进断言明细。
      let after = clickInfo.before
      for (let i = 0; i < 12; i++) {
        await sleep(400)
        after = await run('(document.body && document.body.innerText || "").length')
        if (typeof after === 'number' && after > clickInfo.before + 200) break
      }
      const sel = await evalJson(`
        const items = [...document.querySelectorAll('.ant-menu-item')]
        const cur = items.find(e => e.classList.contains('ant-menu-item-selected'))
        return JSON.stringify({ selected: cur ? flat(cur.textContent) : null })
      `)
      // ★ 踩坑记录：第一版判「点完正文变多 200 字」，结果 dark/macaron 两轮报红 ——
      //   因为**视图选择是持久化的**（本仓就是"回到上次的状态"），导航回来时
      //   `before` 已经是资料库了，再点一次反而是折叠/重渲染 ⇒ 字数**变少**。
      //   正确判据 = 「点击命中」∧「目标项处于选中态」∧「主区确有实体内容」，
      //   与"变多变少"无关。
      check(`L2-${mode}${path}`,
        `${mode} 点「${CLICK_TEXT}」命中且处于选中态，主区有内容（正文 ${clickInfo.before}→${after} 字）`,
        clickInfo.found === true && sel.selected === CLICK_TEXT
        && typeof after === 'number' && after >= 300,
        { clickInfo, sel, after })
    }

    const info = await evalJson(`return JSON.stringify(tertiaryNodes())`)
    byRoute[path] = info.nodes.length
    for (const n of info.nodes) nodes.push({ ...n, route: path })
    if (DIAG) {
      console.log(`\n  [diag ${mode} ${path}] --text-tertiary=${JSON.stringify(info.tv)} 命中 ${info.nodes.length}；`
        + `文字节点颜色直方图 top12 = ${JSON.stringify(info.histogram)}`)
    }
  }

  check(`L0-${mode}`, `主题 ${mode} 真的生效（data-theme=${JSON.stringify(mode)}，全部 ${ROUTES.length} 页）`,
    themeOk, themeDetail)

  const bad = nodes.filter(x => x.ratio < SPEC[mode].min)
  const antdNodes = nodes.filter(x => x.antd)
  const min = nodes.length ? Math.min(...nodes.map(x => x.ratio)) : null

  // T-值：**计算值 == 规格值** —— 规格表是本探针的"真源镜像"。
  //   ★ 这条不能省：少了它，规格表就只是摆设 —— 把 presets 改回旧值也能靠"扫到的
  //     那几个节点恰好都在亮面上"混过去（判据必须能指认"是哪个值不对"）。
  const tvNow = landedAny ? await evalJson(`
    const c = anyColor(getComputedStyle(document.documentElement).getPropertyValue('--text-tertiary'))
    return JSON.stringify(c ? c.map((v, i) => (i === 3 ? Math.round(v * 100) / 100 : Math.round(v))) : null)
  `) : null
  check(`T2-${mode}`, `${mode} --text-tertiary 计算值 == 规格 ${SPEC[mode].var}`,
    JSON.stringify(tvNow) === JSON.stringify(SPEC[mode].rgb), { computed: tvNow, spec: SPEC[mode].rgb })
  // 层级不变量的取数：**tertiary 必须比 secondary 更弱**（更靠近底色）。
  // ★ 这里不能直接比亮度 —— 深色主题底色是暗的，"更浅的层级"反而**亮度更低**
  //   （第一版就写成 `lum(t) > lum(s)` 并把正确的暗色调色板判红：dark t=0.294 < s=0.437）。
  //   与明暗无关的正确表述是「对背景的对比度更弱」⇒ 一律换成 ratio 比。
  const vsPair = landedAny ? await evalJson(`
    const cs = getComputedStyle(document.documentElement)
    const bg = anyColor(cs.getPropertyValue('--bg-elevated')) || [31, 31, 31, 1]
    const t = anyColor(cs.getPropertyValue('--text-tertiary'))
    const s = anyColor(cs.getPropertyValue('--text-secondary'))
    return JSON.stringify({
      tertiary: Math.round(ratio(blend(t, bg), bg) * 1000) / 1000,
      secondary: Math.round(ratio(blend(s, bg), bg) * 1000) / 1000,
    })
  `) : { tertiary: null, secondary: null }
  summary[mode] = { var: SPEC[mode].var, count: nodes.length, antd: antdNodes.length, min, byRoute, vs: vsPair }

  // T-读得到：必须真扫到用该色的文字节点，否则下面的达标判据是空跑
  check(`T1-${mode}`, `${mode} 扫到用 --text-tertiary 的文字节点（实测 ${nodes.length} 个，期望 ≥3）`,
    nodes.length >= 3, { count: nodes.length, byRoute })

  // ★ 这里刻意**不**判「页面上有 antd 组件用到该 token」：实测 `/` 与 `/subscription`
  //   都没有 antd 组件消费 colorTextTertiary（antd 节点数 = 0）⇒ 那样判是一条**永久假红**。
  //   「CSS 变量 ↔ antd token 逐字一致」改由静态门禁 `check-theme-boot.py` 第 [5] 节钉住
  //   —— 不变量要在能判它的地方判。（antd 命中数只作信息打印）

  // T-够黑：最差节点 ≥ 阈值
  check(`T3-${mode}`, `${mode} 全部 tertiary 文字 ≥ ${SPEC[mode].min}:1（实测最差 ${min}）`,
    nodes.length > 0 && bad.length === 0, bad.slice(0, 8))

  console.log(`\n---- [${mode}] --text-tertiary = ${SPEC[mode].var}；命中 ${nodes.length} 个节点（antd ${antdNodes.length}），最差 ${min}:1 ----`)
  console.log(`     分路由命中：${JSON.stringify(byRoute)}`)
  const worst = [...nodes].sort((a, b) => a.ratio - b.ratio).slice(0, 6)
  for (const b of worst) {
    console.log(`  ${String(b.ratio).padStart(6)}:1 (需 ${b.need})  ${b.route}  ${b.sel}  「${b.text}」  ${b.color} on ${b.bg}`)
  }
  console.log('')
}

// macaron 天花板：两条**结构不变量**，比一条拍脑袋的阈值有用得多 ——
//   T4a 层级不倒挂：tertiary 对背景的对比度必须**弱于** secondary（与主题明暗无关）。
//       若哪天有人为了"凑到 4.5"把 tertiary 压得比 secondary 还抢眼，这条立刻红
//       （那是在毁层级，不是修可读性）。
//   T4b 如实：macaron 到不了 AA（< 4.5）必须仍然成立 —— 若它突然达标，
//       说明有人改了 secondary 或色域，该回来**改规格**而不是让这条悄悄绿着。
const mac = summary.macaron
const order = THEMES.map(t => `${t}:${summary[t].vs.tertiary}${summary[t].vs.tertiary < summary[t].vs.secondary ? '<' : '>='}${summary[t].vs.secondary}`)
check('T4', `层级正序（tertiary 对比度弱于 secondary：${order.join(' / ')}）且 macaron 如实 <4.5（实测 ${mac.min}）`,
  THEMES.every(t => summary[t].vs && summary[t].vs.tertiary !== null
    && summary[t].vs.tertiary < summary[t].vs.secondary)
  && mac.min !== null && mac.min < 4.5,
  { order, macaronMin: mac.min })

// T5 —— 棘轮：三主题的"已达成最差值"不得回退（改主题变量时最容易悄悄做过头）
const RATCHET = { light: 4.6, dark: 4.7, macaron: 3.8 }
for (const t of THEMES) {
  check(`T5-${t}`, `${t} 最差读数不回退（棘轮 ≥ ${RATCHET[t]}，实测 ${summary[t].min}）`,
    summary[t].min !== null && summary[t].min >= RATCHET[t], summary[t])
}

writeFileSync(join(SHOT_DIR, 'summary.json'), JSON.stringify(summary, null, 2), 'utf8')
const failed = results.filter(r => !r.ok).length
console.log(`\n---- ${results.length - failed}/${results.length} 通过，${failed} 条红 ----`)
console.log(`读数汇总：${JSON.stringify(summary)}`)
console.log(`截图目录：${SHOT_DIR}`)
chrome.kill()
process.exit(REPORT_ONLY || failed === 0 ? 0 : 1)

#!/usr/bin/env node
/**
 * 官网判据（site/ 的唯一门禁）
 * ============================================================================
 * ★ 钉的都是「**不报错但坏掉**」那一类 —— 没有一个会让页面打不开：
 *   品牌色没被引用、免责声明被删掉、占位符被偷偷填成假信息、
 *   手机上横向溢出、关掉动效后内容不见了、多页站写成 SPA 兜底…
 *   这些**只有判据会说话**。
 *
 * ★★ 判据的所有期望值都**从文件/产品现算**，不手写：
 *   · Agent 清单 ⇒ 现读 `backend/modules/skills/agents.py::AGENT_CATALOG`
 *   · 对比度 ⇒ 现算 WCAG 相对亮度（见 contrast()）
 *   · 占位符 ⇒ 现从 docs/legal/*.md 与 site/*.html 各取集合比对
 *   手写期望值正是「期望值过期伪装成真回归」的来源。
 *
 * 用法：node site/verify-site.mjs [--shots] [--keep]
 *   --shots  顺便把三个页面整页截图写到 .workbuddy/probes/site-verify/
 *   --keep   跑完不关浏览器（调试用）
 * 退出码：0=全过 / 1=有 FAIL / 2=探针自身失效（环境问题，不并进 PASS/FAIL）
 */
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { readFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { join, extname, resolve, sep } from 'node:path'

const SITE_DIR = fileURLToPath(new URL('.', import.meta.url))
const ROOT = resolve(SITE_DIR, '..')
const SHOT_DIR = join(ROOT, '.workbuddy', 'probes', 'site-verify')
const CHROME = process.env.CHROME_PATH
  || 'C:/Users/Administrator/.agent-browser/browsers/chrome-153.0.8010.36/chrome.exe'
const ARGS = process.argv.slice(2)
const WANT_SHOTS = ARGS.includes('--shots')
const KEEP = ARGS.includes('--keep')
/** 只跑静态段（变异自证用：不必要每次起 Chrome） */
const STATIC_ONLY = ARGS.includes('--static')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const results = []
const check = (id, name, ok, detail) => {
  const state = ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'
  results.push({ id, name, state })
  console.log(`${state}  ${id.padEnd(6)} ${name}${ok === true ? '' : '  ⟵ ' + JSON.stringify(detail ?? null)}`)
}

const read = (p) => readFileSync(p, 'utf8')

/* ============================================================ 静态判据 */

/** 页面清单 */
const PAGES = ['index.html', 'privacy.html', 'terms.html']

/** ① 三页存在且非空 */
function st1() {
  const missing = PAGES.filter((p) => !existsSync(join(SITE_DIR, p)) || statSync(join(SITE_DIR, p)).size < 800)
  check('ST1', '三个页面都存在且非空（index / privacy / terms）', missing.length === 0, missing)
}

/** ② 零外部依赖 —— 站外资源一个都不能有（谁加个 CDN 字体，页面照样能开，只是被拖慢/被墙） */
function st2() {
  const bad = []
  for (const p of PAGES) {
    const html = read(join(SITE_DIR, p))
    // src="http..." / href="http..." （排掉 <a href> 外链：那是访客导航，不是资源依赖）
    const re = /<(?:img|script|link|iframe|video|audio|source)\b[^>]*\b(?:src|href)\s*=\s*["'](https?:)?\/\//gi
    let m
    while ((m = re.exec(html))) bad.push(`${p}: ${m[0].slice(0, 70)}`)
  }
  check('ST2', '零外部依赖（无站外图片/脚本/样式/字体）', bad.length === 0, bad)
}

/** ③ 零 JS —— 没有 script / 内联事件 / javascript: 协议 */
function st3() {
  const bad = []
  for (const p of PAGES) {
    const html = read(join(SITE_DIR, p)).replace(/<!--[\s\S]*?-->/g, '') // 注释里提到不算
    if (/<script\b/i.test(html)) bad.push(`${p}: <script>`)
    const ev = html.match(/\son[a-z]+\s*=\s*["']/gi)
    if (ev) bad.push(`${p}: 内联事件 ${ev.slice(0, 3).join(',')}`)
    if (/javascript:/i.test(html)) bad.push(`${p}: javascript:`)
  }
  check('ST3', '零 JS（无 script / 内联事件 / javascript: 协议）', bad.length === 0, bad)
}

/** ④ 合规红线词 —— 电商工具类对外文案**不能承诺经营结果** */
const REDLINES = [
  [/保证(出单|销量|排名|爆款|盈利|收益|利润|回本|提升|增长)/g, '保证+结果'],
  [/包(出单|爆款|销量|排名)/g, '包+结果'],
  [/(稳赚|躺赚|必爆|必出单|零风险|百分百出单|100%\s*出单)/g, '收益承诺'],
  [/(规避审核|绕过审核|防封号|黑科技|内部渠道)/g, '违规手法'],
]
// ★ 刻意**不**把「刷单/刷评」列进来：它在服务条款的「可接受使用」一节里
//   必然以**禁止**形式出现（"不得利用本服务进行刷单…"），那是合规要求本身。
//   禁词法在这里会**假红** —— 判据钉的应该是"承诺"，不是"提到"。
const CONTEXT = 26 // 报错时左右各截多少字符，便于定位
function st4() {
  const bad = []
  for (const p of PAGES) {
    const html = read(join(SITE_DIR, p)).replace(/<!--[\s\S]*?-->/g, '')
    for (const [re, label] of REDLINES) {
      let m
      while ((m = re.exec(html))) {
        const s = Math.max(0, m.index - CONTEXT)
        bad.push(`${p} [${label}] …${html.slice(s, m.index + m[0].length + CONTEXT).replace(/\s+/g, ' ')}…`)
      }
    }
  }
  check('ST4', '无合规红线词（不承诺出单/销量/排名/收益）', bad.length === 0, bad)
}

/** ⑤ 负对照 —— 免责声明**必须在**（否则"把该说的话删掉"反而能变绿） */
function st5() {
  const html = read(join(SITE_DIR, 'index.html'))
  const footer = html.slice(html.indexOf('<footer'))
  const hasDisclaimer = /不承诺(出单|销量|排名|收益)/.test(footer)
  const hasTrademark = /(商标|不存在官方)/.test(footer)
  check('ST5', '负对照：页脚免责声明（不承诺经营结果 + 商标归属）必须在', hasDisclaimer && hasTrademark,
    { hasDisclaimer, hasTrademark })
}

/** ⑥ 「待填」占位必须还在 —— 钉的是"没有人偷偷把占位填成假信息"
 *  ★ 口径演进（变异自证逼出来的）：原来只判「index 里【待填】个数 ≥5」，
 *    而变异测试把**其中一处**填成假信息时它**仍然是绿的**（6−1=5 还够）。
 *    ⇒ 改成**逐处**判：联系区每一行都必须是待填 + 页脚必须有 ICP 占位。
 *      这两处正是"上线前必须由主体填"的核心信息位。 */
function st6() {
  const idx = read(join(SITE_DIR, 'index.html'))
  const fills = idx.match(/【待填[^】]*】/g) || []

  // 联系区：每个 <li> 都必须含一个 .fill
  const start = idx.indexOf('contact-list')
  const contactBlock = start >= 0 ? idx.slice(start, idx.indexOf('</ul>', start)) : ''
  const liCount = (contactBlock.match(/<li>/g) || []).length
  const liWithFill = (contactBlock.match(/<li>[\s\S]*?<\/li>/g) || [])
    .filter((li) => li.includes('class="fill"')).length

  // 页脚必须有 ICP 备案占位
  const footer = idx.slice(idx.indexOf('<footer'))
  const hasIcp = /【待填：ICP/.test(footer)

  const legalPh = {}
  for (const p of ['privacy.html', 'terms.html']) {
    legalPh[p] = new Set(read(join(SITE_DIR, p)).match(/\{\{[A-Z0-9_]+\}\}/g) || [])
  }
  const ok = liCount >= 5 && liWithFill === liCount && hasIcp
    && [...Object.values(legalPh)].every((s) => s.size >= 5)
  check('ST6', `待填占位仍在：联系区 ${liWithFill}/${liCount} 行待填 · 页脚 ICP ${hasIcp ? '在' : '缺失'} · 法务页占位 ${Object.values(legalPh).map((s) => s.size).join('/')}`,
    ok, { fillsIndex: fills.length, liCount, liWithFill, hasIcp })
}

/** ⑦ 图片引用与文件一一对应（两个方向都查） */
function st7() {
  const idx = read(join(SITE_DIR, 'index.html'))
  const refs = [...new Set((idx.match(/assets\/shots\/[A-Za-z0-9_.-]+\.png/g) || []))]
  const missing = refs.filter((r) => !existsSync(join(SITE_DIR, r)))
  const shotsDir = join(SITE_DIR, 'assets', 'shots')
  const onDisk = existsSync(shotsDir)
    ? readdirSync(shotsDir).filter((f) => f.endsWith('.png')).map((f) => `assets/shots/${f}`)
    : []
  const unused = onDisk.filter((f) => !refs.includes(f))
  check('ST7', '配图：引用都存在、且磁盘上没有未被引用的图', missing.length === 0 && unused.length === 0,
    { missing, unused })
}

/** ⑧ 每张图都有非空 alt（无障碍 + 也是"图是什么"的书面记录） */
function st8() {
  const bad = []
  for (const p of PAGES) {
    const html = read(join(SITE_DIR, p))
    const imgs = html.match(/<img\b[^>]*>/gi) || []
    for (const tag of imgs) {
      const m = /\balt\s*=\s*["']([^"']*)["']/i.exec(tag)
      if (!m || m[1].trim().length < 8) bad.push(`${p}: ${tag.slice(0, 60)}`)
    }
  }
  check('ST8', '每个 <img> 都有实质 alt', bad.length === 0, bad)
}

/** ⑨ 视差带窄屏必须回退 scroll（iOS Safari 不支持 background-attachment: fixed） */
function st9() {
  const css = read(join(SITE_DIR, 'assets', 'style.css'))
  const hasFixed = /\.band\s*\{[^}]*background-attachment:\s*fixed/s.test(css)
  const narrowBlock = css.slice(css.indexOf('@media (max-width: 768px)'))
  const hasScroll = /\.band\s*\{[^}]*background-attachment:\s*scroll/s.test(narrowBlock)
  check('ST9', '视差带：宽屏 fixed、窄屏回退 scroll（iOS Safari 兼容）', hasFixed && hasScroll,
    { hasFixed, hasScroll })
}

/** ⑩ 对比度（WCAG 2.1 AA）—— 品牌色四档的取值依据 */
function lum(hex) {
  const h = hex.replace('#', '')
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const contrast = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}
/**
 * `#2b20df` → `rgb(43, 32, 223)`
 *
 * ★ 为什么要这个函数：`getComputedStyle()` 返回的是 `rgb(...)` 形态，
 *   如果判据里直接写死 `rgb(9, 88, 217)`，那「换品牌色」就会**必然**让判据红，
 *   而它红了会被读成"页面坏了"（本判据上一版就是这样红的）。
 *   ⇒ 期望值一律**从 style.css 现取再换算**，与 ST10 同源。
 */
function hexToRgbCss(hex) {
  const h = String(hex || '').trim().replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`
}
/** 去掉所有空白后比较（`rgb(1,2,3)` 与 `rgb(1, 2, 3)` 等价） */
const tight = (s) => String(s).replace(/\s+/g, '')
function st10() {
  const css = read(join(SITE_DIR, 'assets', 'style.css'))
  const pick = (name) => (new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css) || [])[1]
  const brandInk = pick('brand-ink')
  const brandLift = pick('brand-lift')
  const bandBg = pick('band-bg')
  if (!brandInk || !brandLift || !bandBg) {
    check('ST10', '品牌色对比度：三档取值必须能从 style.css 现取', false, { brandInk, brandLift, bandBg })
    return
  }
  const cWhite = contrast(brandInk, '#ffffff')       // 白底按钮 / 链接（放白字）
  const cBand = contrast(brandLift, bandBg)          // 深色视差带上的强调
  const ok = cWhite >= 4.5 && cBand >= 4.5
  check('ST10', `品牌色对比度：白底按钮 ${cWhite.toFixed(2)}:1 · 深带强调 ${cBand.toFixed(2)}:1（均需 ≥4.5）`, ok,
    { brandInk, brandLift, bandBg })
}

/** ⑪ 导航锚点都在（`#xxx` 必须有对应 id） */
function st11() {
  const idx = read(join(SITE_DIR, 'index.html'))
  const hrefs = [...new Set((idx.match(/href="#([A-Za-z0-9_-]+)"/g) || []).map((s) => s.slice(7, -1)))]
  const ids = new Set((idx.match(/\sid="([A-Za-z0-9_-]+)"/g) || []).map((s) => s.slice(5, -1)))
  const broken = hrefs.filter((h) => !ids.has(h))
  check('ST11', `导航锚点：${hrefs.length} 个 #锚点都有对应元素`, broken.length === 0, broken)
}

/** ⑫ 页脚三件（隐私政策 / 服务条款 / ICP 备案占位） */
function st12() {
  const idx = read(join(SITE_DIR, 'index.html'))
  const footer = idx.slice(idx.indexOf('<footer'))
  const ok = /privacy\.html/.test(footer) && /terms\.html/.test(footer) && /【待填：ICP/.test(footer)
  check('ST12', '页脚三件：隐私政策 / 服务条款 / ICP 备案占位', ok)
}

/** ⑬ ★★★ 跨语言对账：官网写的数字员工，必须在后端 AGENT_CATALOG 里真存在 */
function st13() {
  const idx = read(join(SITE_DIR, 'index.html'))
  const teamSection = idx.slice(idx.indexOf('id="team"'), idx.indexOf('id="data"'))
  // 卡片 <h3> 就是数字员工名
  const names = [...teamSection.matchAll(/<h3>([^<]+)<\/h3>/g)].map((m) => m[1].trim())
  const py = read(join(ROOT, 'backend', 'modules', 'skills', 'agents.py'))
  const catalogBlock = py.slice(py.indexOf('AGENT_CATALOG'), py.indexOf('#: `agent_name`'))
  const titles = new Set([...catalogBlock.matchAll(/"title":\s*"([^"]+)"/g)].map((m) => m[1]))
  const unknown = names.filter((n) => !titles.has(n))
  const notShown = [...titles].filter((t) => !names.includes(t))
  check('ST13',
    `跨语言对账：官网 ${names.length} 个数字员工 ⊆ 后端 AGENT_CATALOG ${titles.size} 个（写未完成的能力即红）`,
    unknown.length === 0, { unknown, 官网未列出的: notShown })
}

/** ⑭ 法务页是产物，不得含工程侧内容；字段名不得凭空造 */
function st14() {
  const bad = []
  const mdPh = new Set()
  for (const md of ['privacy-policy.md', 'terms-of-service.md']) {
    const t = read(join(ROOT, 'docs', 'legal', md))
    for (const m of t.matchAll(/\{\{([A-Z0-9_]+)\}\}/g)) mdPh.add(m[1])
  }
  for (const p of ['privacy.html', 'terms.html']) {
    // ★ 必须先剥 HTML 注释：产物顶部的**源码注释**里本来就写着 ★ / PLACEHOLDERS
    //   与 `{{FIELD_NAME}}` 举例 —— 不剥注释会得到三条假红（判据自己骗自己）。
    const html = read(join(SITE_DIR, p)).replace(/<!--[\s\S]*?-->/g, '')
    for (const kw of ['★', '门禁', '草案状态', 'PLACEHOLDERS']) {
      if (html.includes(kw)) bad.push(`${p}: 含工程侧内容「${kw}」`)
    }
    for (const m of html.matchAll(/\{\{([A-Z0-9_]+)\}\}/g)) {
      if (!mdPh.has(m[1])) bad.push(`${p}: 凭空出现的字段 {{${m[1]}}}`)
    }
  }
  check('ST14', '法务页与 docs/legal/*.md 同源（无工程侧内容、无凭空字段）', bad.length === 0, bad)
}

/* ================================== 品牌色 L1 专项（对外识别 · 不随主题变） */

/** 从 style.css 现取一个 `--x: #rrggbb`（判据一律现取，不写死色值） */
function pickVar(cssText, name) {
  return (new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(cssText) || [])[1]
}

/** 色相（0–360）：用于「是不是靛族」与「和占位色拉不拉得开」两条 */
function hue(hex) {
  const h = String(hex).replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  const mx = Math.max(r, g, b)
  const mn = Math.min(r, g, b)
  const d = mx - mn
  if (!d) return 0
  let x
  if (mx === r) x = (g - b) / d + (g < b ? 6 : 0)
  else if (mx === g) x = (b - r) / d + 2
  else x = (r - g) / d + 4
  return x * 60
}

/** 色相环上的最短距离（≤180°） */
function hueDist(a, b) {
  const d = Math.abs(a - b) % 360
  return Math.min(d, 360 - d)
}

/**
 * ⑮ 品牌色的**源头**是不是靛族
 *
 * ★ 为什么必须与 ⑯ 拆成两条（这是 eEducation 447 做设计变异时发现的同一条）：
 *   只写"页面上有 ≥N 个靛色元素"是不够的 —— 把 `--brand` 改回旧蓝，
 *   页面上仍有十几处 `--brand-ink`（深靛）在渲染，⑯ 照样绿。
 *   ⇒ ⑮ 钉「源头」，⑯ 钉「它真的渲染出来了」。两条一起才有意义。
 */
function st15() {
  const brand = pickVar(read(join(SITE_DIR, 'assets', 'style.css')), 'brand')
  if (!brand) {
    check('ST15', '品牌色源头：`--brand` 必须能从 style.css 现取', false, null)
    return
  }
  const h = hue(brand)
  const d = hueDist(h, 243.4)
  // 容差 ±6°：同色相推导家族实测最大偏离 3.4°（.workbuddy/probes/tools/indigo-final.py）
  check('ST15', `品牌色源头是靛族：--brand ${brand} 色相 ${h.toFixed(1)}°（期望 243.4°±6）`,
    d <= 6, { brand, 色相: +h.toFixed(1), 偏离: +d.toFixed(1) })
}

/**
 * ⑯ 品牌色与「待填」占位色**必须能一眼分开**
 *
 * 这条保护的是上线前**唯一**那个"这里还没填"的提醒：占位色一旦与品牌色混了，
 * 就没人会注意到占位还在（eEducation 447 §1 有过同一条判断，那边差 8° 就换了色）。
 */
function st16() {
  const css = read(join(SITE_DIR, 'assets', 'style.css'))
  const brand = pickVar(css, 'brand')
  const fill = pickVar(css, 'fill-ink')
  if (!brand || !fill) {
    check('ST16', '品牌色 / 占位色都必须能从 style.css 现取', false, { brand, fill })
    return
  }
  const d = hueDist(hue(brand), hue(fill))
  check('ST16', `品牌色与「待填」占位色色相差 ${d.toFixed(1)}°（≥90 才不会误读）`, d >= 90,
    { brand, fill, 色相差: +d.toFixed(1) })
}

/**
 * ⑰ 旧的蓝色 token 在**剥注释后**彻底消失（style.css + 三页 + favicon）
 *
 * ★ 必须剥注释：注释里**故意**留着旧值（用来记录"旧值为什么不达 AA"、
 *   "为什么换这个色相"），不剥就是三条假红 —— 这正是本仓铁律
 *   「判据禁源码字符串包含」的由来。
 */
function st17() {
  const OLD = ['#1890ff', '#0958d9', '#91caff', '#f0f7ff', '#40a9ff', '#e6f7ff']
  const bad = []
  const css = read(join(SITE_DIR, 'assets', 'style.css')).replace(/\/\*[\s\S]*?\*\//g, '')
  for (const c of OLD) if (css.toLowerCase().includes(c)) bad.push(`style.css: ${c}`)
  for (const p of PAGES) {
    const t = read(join(SITE_DIR, p)).replace(/<!--[\s\S]*?-->/g, '').toLowerCase()
    for (const c of OLD) if (t.includes(c)) bad.push(`${p}: ${c}`)
  }
  const fav = read(join(SITE_DIR, 'assets', 'favicon.svg')).toLowerCase()
  for (const c of OLD) if (fav.includes(c)) bad.push(`favicon.svg: ${c}`)
  check('ST17', '旧的蓝色 token 已彻底退场（剥注释后 0 命中；注释里的留痕不算）', bad.length === 0, bad)
}

/**
 * ⑱ favicon 的底 = `--brand-ink`（**站内自洽**）
 *
 * ★ 期望值从 style.css **现取**、不手写 —— 与 RT6 同一处来源
 *   （手写 = 给"换品牌色"埋第二处必改点，而且它红了会被误读成"页面坏了"）。
 * ★ 为什么这条值得独立存在：favicon 是**唯一一个不带 CSS 环境**的资产 ——
 *   它拿不到 `var()`，色值是**写死**在文件里的副本 ⇒ 换品牌色时它最容易漏。
 */
function st18() {
  const css = read(join(SITE_DIR, 'assets', 'style.css'))
  const ink = (new RegExp('--brand-ink:\\s*(#[0-9a-fA-F]{6})').exec(css) || [])[1]
  const fav = read(join(SITE_DIR, 'assets', 'favicon.svg'))
  const fills = [...fav.matchAll(/<rect\b[^>]*fill="([^"]+)"/g)].map((m) => m[1].toLowerCase())
  const whites = [...fav.matchAll(/(?:fill|stroke)="#ffffff"/gi)].length
  check('ST18', `favicon 的底 = --brand-ink ${ink}（实测 ${fills[0]}）；白笔画 ${whites} 处`,
    !!ink && fills.length === 1 && fills[0] === ink.toLowerCase() && whites >= 2,
    { ink, fills, whites })
}

/**
 * ⑲ 官网 favicon 与**产品站**的标识几何逐字相同（跨仓对账）
 *
 * ★ 为什么必须有这一条：官网是**独立部署**的（发包方是网站管理员），
 *   前端自己的 `scripts/check-brand-mark.cjs` 管不到这里。
 *   而"两站标识不同形"是**静默**的 —— 没有人会同时开两个 tab 去比。
 * ★ 关系的准确表述：官网 favicon 是产品站组件的**严格子集**
 *   （少「笑」那一条 path —— 16px 下笑脸会与墙体糊成一体，是结构性下限）。
 *   所以判「官网的两条 == 产品的前两条且逐字相同」，而不是"三条都相同"。
 * ⚠️ 产品站源码不在场（比如只部署了 `site/`）时判 **SKIP**，不并进 PASS。
 */
function st19() {
  const brand = join(ROOT, 'frontend', 'src', 'components', 'BrandMark.vue')
  if (!existsSync(brand)) {
    check('ST19', '跨仓几何对账（产品站源码不在场 ⇒ 跳过）', null, { brand })
    return
  }
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim()
  const pathsOf = (t) => {
    const body = t.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
    return [...body.matchAll(/<path\b([^>]*?)\/?>/g)].map((m) =>
      norm((/\bd="([^"]*)"/.exec(m[1]) || [])[1]),
    )
  }
  const mine = pathsOf(read(join(SITE_DIR, 'assets', 'favicon.svg')))
  const theirs = pathsOf(read(brand))
  const strict =
    mine.length === 2 && theirs.length === 3 && mine.every((d, i) => d === theirs[i])
  check('ST19', `官网 favicon 的 ${mine.length} 条 path 与产品站 BrandMark 的**前 ${mine.length} 条逐字相同**（严格子集）`,
    strict, { mine: mine.map((d) => d.slice(0, 26) + '…'), theirs: theirs.map((d) => d.slice(0, 26) + '…') })
}

/* ========================================================== 真机判据 */

let ws, msgId = 0
const pending = new Map()
const send = (method, params = {}) => {
  const id = ++msgId
  return new Promise((res, rej) => { pending.set(id, { res, rej }); ws.send(JSON.stringify({ id, method, params })) })
}
async function run(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
  if (r.exceptionDetails) throw new Error(String(r.exceptionDetails.exception?.description || r.exceptionDetails.text).split('\n')[0])
  return r.result?.value
}

async function rt(base) {
  const goto = async (path, w = 1440, h = 900) => {
    await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false })
    await send('Page.navigate', { url: base + path })
    for (let i = 0; i < 40; i++) {
      const s = await run('document.readyState')
      if (s === 'complete') break
      await sleep(200)
    }
    await sleep(500)
  }

  /** RT1 三页都能打开 */
  const codes = {}
  for (const p of PAGES) { codes[p] = (await fetch(`${base}/${p}`)).status }
  check('RT1', '三个页面 HTTP 200', Object.values(codes).every((c) => c === 200), codes)

  /** RT2 四宽度无横向溢出（判的是**渲染后**，不是读 CSS） */
  const overflow = {}
  for (const w of [1440, 1024, 768, 420]) {
    await goto('/index.html', w, 900)
    overflow[w] = await run('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  }
  check('RT2', `无横向溢出（1440/1024/768/420：${JSON.stringify(overflow)}）`,
    Object.values(overflow).every((v) => v <= 1), overflow)

  /** RT3 视差带：宽屏 fixed、窄屏 scroll（实测，不是读 CSS）
   *  ⚠️ 计算值是**按背景层**返回的（.band 有两个 radial-gradient ⇒ "fixed, fixed"），
   *     所以必须逐层判，直接比字符串会得到假红。 */
  await goto('/index.html', 1440, 900)
  const wide = await run(`getComputedStyle(document.querySelector('.band')).backgroundAttachment`)
  await goto('/index.html', 420, 900)
  const narrow = await run(`getComputedStyle(document.querySelector('.band')).backgroundAttachment`)
  const layers = (v) => String(v).split(',').map((s) => s.trim())
  const wideOk = layers(wide).every((v) => v === 'fixed')
  const narrowOk = layers(narrow).length > 0 && layers(narrow).every((v) => v === 'scroll')
  check('RT3', `视差带实测：宽屏 ${wide} / 窄屏 ${narrow}`, wideOk && narrowOk, { wide, narrow })

  /** RT4 ★★★ 降级安全：关掉动效后每个 .reveal 必须完全可见（不是"读 CSS 说它会可见"） */
  await send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
  })
  await goto('/index.html', 1440, 900)
  const opac = await run(`[...document.querySelectorAll('.reveal')].map(e => getComputedStyle(e).opacity)`)
  const hidden = opac ? opac.filter((o) => Number(o) < 1).length : -1
  check('RT4', `关动效后 ${opac ? opac.length : 0} 个 .reveal 全部不透明度=1（降级方向是"没动画"不是"内容不见"）`,
    hidden === 0, { hidden, sample: opac && opac.slice(0, 6) })
  await send('Emulation.setEmulatedMedia', { features: [] })

  /** RT5 页脚三件真的渲染出来了（DOM，不是源码） */
  await goto('/index.html', 1440, 900)
  const foot = await run(`(() => {
    const f = document.querySelector('footer.site-footer')
    if (!f) return null
    const t = f.innerText
    return { privacy: !!f.querySelector('a[href*="privacy"]'), terms: !!f.querySelector('a[href*="terms"]'),
             icp: /ICP/.test(t), disclaimer: /不承诺/.test(t) }
  })()`)
  check('RT5', '页脚三件 + 免责声明在渲染结果里都在', !!foot && foot.privacy && foot.terms && foot.icp && foot.disclaimer, foot)

  /** RT6 品牌色真的被用上了（不是定义了没人用）
   *  ★ 期望值从 style.css **现取**（与 ST10 同一处来源），不在判据里手写 rgb：
   *    手写 = 给「换品牌色」埋第二处必改点，而且它红了会被误读成"页面坏了"。 */
  await goto('/index.html', 1440, 900)
  const btnBg = await run(`getComputedStyle(document.querySelector('.btn-primary')).backgroundColor`)
  const inkHex = (new RegExp('--brand-ink:\\s*(#[0-9a-fA-F]{6})')
    .exec(read(join(SITE_DIR, 'assets', 'style.css'))) || [])[1]
  const want = hexToRgbCss(inkHex)
  check('RT6', `品牌色落地：主按钮实测底色 ${btnBg}（期望 = --brand-ink ${inkHex} ⇒ ${want}）`,
    !!inkHex && tight(btnBg) === tight(want), { btnBg, inkHex, want })

  /**
   * RT7 品牌色**真的渲染出来了**（不是只在 CSS 里定义着）
   *
   * ★ 与 ⑮ 配对：⑮ 钉源头色相，本条钉"页面上真的有元素在用它"。
   *   只留 ⑮ ⇒ 定义了没人用也能绿（`--brand` 面积≈0，等于没用）；
   *   只留本条 ⇒ 把源头改回旧蓝时，页面上还有十几处 --brand-ink 在渲染，照样绿。
   */
  const cssText = read(join(SITE_DIR, 'assets', 'style.css'))
  const brandTokens = ['brand', 'brand-ink', 'brand-lift', 'brand-wash']
    .map((n) => pickVar(cssText, n))
    .filter(Boolean)
  const wantRgbs = brandTokens.map((hx) => tight(hexToRgbCss(hx)))
  const usedCount = await run(`(() => {
    const want = ${JSON.stringify(wantRgbs)}
    const norm = (s) => String(s).replace(/\\s+/g, '')
    let n = 0
    for (const el of document.querySelectorAll('*')) {
      const cs = getComputedStyle(el)
      const vals = [cs.color, cs.backgroundColor, cs.borderLeftColor, cs.borderTopColor, cs.borderBottomColor]
      if (vals.some((v) => want.includes(norm(v)))) n++
    }
    return n
  })()`)
  // 阈值 10：旧蓝版实测 26 个元素在用它（eEducation 447 同口径也是量出 26）。
  // 取 10 留出"合理重构会换掉几个元素"的余量，同时远高于"面积≈0"的失败态。
  check('RT7', `品牌色真的渲染出来了：${usedCount} 个元素在用它（四档 token = ${brandTokens.join(' ')}，需 ≥10）`,
    usedCount >= 10, { usedCount, brandTokens })

  /** 截图（给人工目视用）
   *  ⚠️ 必须**先关动效**再抓整页：`.reveal` 初始态是 opacity:0，
   *     而整页截图不会滚动 ⇒ 不关的话抓到的图除首屏外全是空白
   *     （判据全绿、图却像坏了 —— 这类"尺子自己的问题"最容易被误读成产品缺陷）。 */
  if (WANT_SHOTS) {
    mkdirSync(SHOT_DIR, { recursive: true })
    await send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    })
    for (const p of PAGES) {
      await goto('/' + p, 1440, 900)
      // ★ 整页截图**不滚动** ⇒ `loading="lazy"` 的图永远不加载，抓出来是一片空白。
      //   这是"尺子自己的问题"，不是页面缺陷（真实浏览时懒加载正常）。
      //   ⇒ 抓图前把 loading 全改 eager 并等 decode 完。
      await run(`(async () => {
        document.querySelectorAll('img[loading="lazy"]').forEach(i => { i.loading = 'eager' })
        await Promise.all([...document.images].map(i => i.decode().catch(() => {})))
      })()`)
      await sleep(400)
      const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
      writeFileSync(join(SHOT_DIR, p.replace('.html', '.png')), Buffer.from(r.data, 'base64'))
    }
    await send('Emulation.setEmulatedMedia', { features: [] })
    console.log(`\n截图 → ${SHOT_DIR}`)
  }
}

/* =============================================================== main */
async function main() {
  console.log('=== 静态判据 ===')
  st1(); st2(); st3(); st4(); st5(); st6(); st7(); st8(); st9(); st10(); st11(); st12(); st13(); st14()
  st15(); st16(); st17(); st18(); st19()

  if (!existsSync(CHROME)) { console.log(`\nPROBE-ERR: 找不到 chrome：${CHROME}`); process.exit(2) }

  if (STATIC_ONLY) {
    const n0 = (s) => results.filter((r) => r.state === s).length
    console.log(`\n=== 汇总（静态段）：${n0('PASS')} PASS / ${n0('FAIL')} FAIL / ${n0('SKIP')} SKIP ===`)
    if (n0('FAIL')) for (const r of results.filter((x) => x.state === 'FAIL')) console.log(`  ${r.id}  ${r.name}`)
    process.exit(n0('FAIL') ? 1 : 0)
  }

  // 自起静态服务器（不依赖手动开端口）
  const server = createServer((req, res) => {
    let p = decodeURIComponent((req.url || '/').split('?')[0])
    if (p.endsWith('/')) p += 'index.html'
    const fp = join(SITE_DIR, p)
    if (!fp.startsWith(SITE_DIR) || !existsSync(fp) || statSync(fp).isDirectory()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('404'); return
    }
    const mime = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png' }[extname(fp)] || 'application/octet-stream'
    res.writeHead(200, { 'Content-Type': mime }); res.end(readFileSync(fp))
  })
  const port = await new Promise((res) => server.listen(0, '127.0.0.1', () => res(server.address().port)))
  const base = `http://127.0.0.1:${port}`
  console.log(`\n=== 真机判据（自起静态服务器 ${base}）===`)

  const profile = mkdtempSync(join(tmpdir(), 'cdp-site-'))
  const cdpPort = 9550 + Math.floor(Math.random() * 60)
  const chrome = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${cdpPort}`, '--remote-allow-origins=*',
    `--user-data-dir=${profile}`, '--window-size=1440,900',
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--disable-extensions', 'about:blank',
  ], { stdio: 'ignore' })

  let wsUrl = ''
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${cdpPort}/json/list`)).json()
      const page = list.find((t) => t.type === 'page')
      if (page?.webSocketDebuggerUrl) { wsUrl = page.webSocketDebuggerUrl; break }
    } catch { /* retry */ }
    await sleep(400)
  }
  if (!wsUrl) { console.log('PROBE-ERR: 连不上 CDP'); server.close(); process.exit(2) }

  ws = new WebSocket(wsUrl)
  ws.addEventListener('message', (ev) => {
    let m
    try { m = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString()) } catch { return }
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id)
      if (m.error) rej(new Error(m.error.message)); else res(m.result)
    }
  })
  await new Promise((res) => ws.addEventListener('open', res, { once: true }))
  await send('Page.enable'); await send('Runtime.enable')

  try {
    await rt(base)
  } catch (e) {
    console.log('PROBE-ERR（真机段）:', e.message)
    results.push({ id: 'RT*', name: '真机段异常终止', state: 'FAIL' })
  }

  server.close()
  if (!KEEP) { try { chrome.kill() } catch { /* ignore */ } }
  try { ws.close() } catch { /* ignore */ }

  const n = (s) => results.filter((r) => r.state === s).length
  console.log(`\n=== 汇总：${n('PASS')} PASS / ${n('FAIL')} FAIL / ${n('SKIP')} SKIP ===`)
  if (n('FAIL')) {
    console.log('FAIL 明细：')
    for (const r of results.filter((x) => x.state === 'FAIL')) console.log(`  ${r.id}  ${r.name}`)
  }
  process.exit(n('FAIL') ? 1 : 0)
}

main().catch((e) => { console.log('PROBE-ERR:', e.message); process.exit(2) })

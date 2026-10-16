#!/usr/bin/env node
/**
 * 品牌标识门禁（零依赖 · 只读源码 · 不起服务）
 *
 * ============================================================================
 * 为什么需要它
 * ============================================================================
 * 第 373 轮实锤（老板截图报的）：切到马卡龙主题后，侧栏 logo 变成**玫红** `#c33a76`。
 * 根因不是配色失误，是**层级搞错了** —— `.logo-avatar` 的底色取的是
 * `var(--primary)`（**L2 主题主色**），而"品牌标识"是 **L1 资产**，定义就是
 * "不管在哪儿都是这个色"。
 *
 * 这一类缺陷的共同形态：**类型系统不报、`vite build` 不报、单测不报**，
 * 只在"特定主题 + 特定尺寸"上被人眼发现。所以必须有静态断言：
 *
 *   · 标识底色被改回 `var(--primary)`（下次有人"顺手统一一下"）；
 *   · 三处几何（组件 / 产品站 favicon / 官网 favicon）悄悄漂移成三个形；
 *   · favicon 不再是组件的**严格子集**（有人在 favicon 上单独加了一笔）；
 *   · `BRAND_VARS` 被"顺手"挪进某张主题表 ⇒ 品牌色重新跟着主题变；
 *   · `index.html` 又指回一个不存在的图标（实测此前指的 `/vite.svg` **文件不存在**，
 *     而 `public/favicon.svg` 零引用 —— 两处都不对，且都没人发现）；
 *   · 16px 场景下笔画细到消失（favicon 是"最小尺寸"的极端场景）。
 *
 * ============================================================================
 * 判据设计口径（照本仓既有铁律）
 * ============================================================================
 *   · **一律剥注释**再判 —— 注释里故意留着旧值当"为什么这么改"的留痕。
 *     ★ 例外：B7 判的**正是标记的存在性**，但它只认属性、不认注释（见 B7 说明）。
 *   · **期望几何硬写在本文件**（不从别处现推）：几何是**设计决策**，
 *     改它必须**显式**改本文件 —— 与 `check-theme-colors.cjs` 的 T2 同口径。
 *     反面：favicon 是**派生**（子集），它不能当源头，否则"两份实现互相印证"。
 *   · 色值/对比度**不手写**：从 `presets.ts` 的 `BRAND_VARS` 现取后现算。
 *   · 每条判据配**自检**（防正则写错 ⇒ 空集恒真 ⇒ 假绿）。
 *   · 判"某块内不含 X"必须**先切出那个块**（用宽松串做 `includes` 会串到别处，
 *     本轮实测踩过：`.logo-avatar` 的探测串在 badge / 模式切换按钮上也命中）。
 *
 * 反向注入（证明本门禁不是空跑；全部源都可用环境变量改指向副本）：
 *   BRAND_SRC / PRESETS_SRC / FAVICON_PUB_SRC / FAVICON_SITE_SRC /
 *   WORKSPACE_SRC / LOGIN_SRC / INDEX_HTML_SRC
 * 见 `.workbuddy/probes/mutate-brand-mark.mjs`。
 *
 * 怎么跑：node scripts/check-brand-mark.cjs
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const SRC = {
  brand: pick('BRAND_SRC', path.join(ROOT, 'src', 'components', 'BrandMark.vue')),
  presets: pick('PRESETS_SRC', path.join(ROOT, 'src', 'theme', 'presets.ts')),
  favPub: pick('FAVICON_PUB_SRC', path.join(ROOT, 'public', 'favicon.svg')),
  favSite: pick('FAVICON_SITE_SRC', path.join(ROOT, '..', 'site', 'assets', 'favicon.svg')),
  workspace: pick('WORKSPACE_SRC', path.join(ROOT, 'src', 'views', 'Workspace.vue')),
  login: pick('LOGIN_SRC', path.join(ROOT, 'src', 'views', 'Login.vue')),
  indexHtml: pick('INDEX_HTML_SRC', path.join(ROOT, 'index.html')),
}

/* ------------------------------------------------------------------ 期望值 */

/**
 * 几何真源（48×48 网格）—— ★ 改这里 = 一次**显式**的品牌标识决策。
 * 顺序即语义：檐（fill）→ 体（描边 3.4）→ 笑（描边 3.6）。
 */
const EXPECTED = [
  {
    name: '檐',
    d: 'M11.7 8.4 H36.3 Q37.9 8.4 38.7 10.5 L41 15.4 a5.667 3.3 0 0 1 -11.333 0 a5.667 3.3 0 0 1 -11.333 0 a5.667 3.3 0 0 1 -11.333 0 L9.3 10.5 Q10.1 8.4 11.7 8.4 Z',
    sw: null,
  },
  {
    name: '体',
    d: 'M10.5 21 V36.8 Q10.5 39.4 13 39.4 H35 Q37.5 39.4 37.5 36.8 V21',
    sw: '3.4',
  },
  {
    name: '笑',
    d: 'M17.3 27.6 A6.7 4.2 0 0 0 30.7 27.6',
    sw: '3.6',
  },
]
/** favicon = 删掉「笑」之后的两条 */
const FAVICON_COUNT = 2
/** favicon 底：48×48 圆角方，rx = 9（= 18.75%，与侧栏位 36px 上的比例一致） */
const BADGE = { size: '48', rx: '9' }
/** 白 / 画幅 */
const WHITE = '#ffffff'
/** 16px 场景下笔画不得细于此（px） */
const MIN_STROKE_AT_16 = 1.0
const GRID = 48

/* ------------------------------------------------------------------ 工具 */

let failed = 0
const results = []
function check(id, desc, ok, detail) {
  results.push({ id, desc, ok, detail })
  if (!ok) failed++
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${id.padEnd(4)} ${desc}`)
  if (!ok && detail !== undefined) {
    console.log(`        ↳ ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
  }
}

/** 剥 JS/CSS/HTML/Vue 注释（判据铁律：注释会骗过字符串判据） */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 空白归一化：`d` 属性在多行书写与单行书写下必须等价 */
const normSpace = (s) => (s == null ? null : s.replace(/\s+/g, ' ').trim())

const read = (p) => fs.readFileSync(p, 'utf8')

function attr(attrs, name) {
  const m = new RegExp(`\\b${name}\\s*=\\s*"([^"]*)"`).exec(attrs)
  return m ? normSpace(m[1]) : null
}

/** 提 SVG 里的 `<path>`：{d, sw, fill, stroke} */
function pathsOf(src) {
  const body = stripComments(src)
  const out = []
  const re = /<path\b([^>]*?)\/?>/g
  let m
  while ((m = re.exec(body))) {
    const a = m[1]
    out.push({
      d: attr(a, 'd'),
      sw: attr(a, 'stroke-width'),
      fill: attr(a, 'fill'),
      stroke: attr(a, 'stroke'),
    })
  }
  return out
}

/** 提 SVG 里的 `<rect>`（底徽章） */
function rectsOf(src) {
  const body = stripComments(src)
  const out = []
  const re = /<rect\b([^>]*?)\/?>/g
  let m
  while ((m = re.exec(body))) {
    const a = m[1]
    out.push({
      w: attr(a, 'width'),
      h: attr(a, 'height'),
      rx: attr(a, 'rx'),
      fill: attr(a, 'fill'),
    })
  }
  return out
}

/** 取 `<svg ...>…</svg>` 整块（空白归一）—— 用于跨文件"几何逐字一致"对账 */
function svgBlock(src) {
  const s = stripComments(src)
  const i = s.indexOf('<svg')
  const j = s.lastIndexOf('</svg>')
  return i < 0 || j < i ? null : normSpace(s.slice(i, j + '</svg>'.length))
}

/** 取出 `const NAME = {` 到配平 `}` 的块（与 check-theme-colors.cjs 同口径） */
function blockAfter(src, marker) {
  const i = src.indexOf(marker)
  if (i < 0) return null
  const start = src.indexOf('{', i)
  if (start < 0) return null
  let depth = 0
  for (let j = start; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}' && --depth === 0) return src.slice(start, j + 1)
  }
  return null
}

/** 取出**已剥注释**源码里某个 CSS 类的声明块（`.` 起头，大括号配平） */
function cssBlockAfter(src, selector) {
  const s = stripComments(src)
  const i = s.indexOf(selector)
  if (i < 0) return null
  const start = s.indexOf('{', i)
  if (start < 0) return null
  let depth = 0
  for (let j = start; j < s.length; j++) {
    if (s[j] === '{') depth++
    else if (s[j] === '}' && --depth === 0) return s.slice(start, j + 1)
  }
  return null
}

function lum(hex) {
  const h = hex.replace('#', '')
  const c = [0, 2, 4]
    .map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
const contrast = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
  return (x + 0.05) / (y + 0.05)
}

/* ------------------------------------------------------------------ 读源 */

const src = {}
for (const [k, p] of Object.entries(SRC)) {
  try {
    src[k] = read(p)
  } catch (e) {
    console.error(`!! 读不到 ${k}: ${p}\n   ${e.code}`)
    process.exit(2)
  }
}

/* 品牌四档 —— 从 presets.ts 现取（**不手写**） */
const brandBlock = blockAfter(src.presets, 'export const BRAND_VARS')
const brandVars = brandBlock
  ? Object.fromEntries(
      [...brandBlock.matchAll(/'(--brand[a-z-]*)'\s*:\s*'(#[0-9a-fA-F]{6})'/g)].map((m) => [
        m[1],
        m[2].toLowerCase(),
      ]),
    )
  : {}
const brandInk = brandVars['--brand-ink'] || null

console.log('=== 品牌标识门禁（几何唯一真源 · L1 不随主题 · 16px 下限）===')
console.log(
  `读源 7 个 | BRAND_VARS ${Object.keys(brandVars).length} 档 | --brand-ink = ${brandInk || '（取不到！）'}`,
)
console.log()

/* ================================================================ [1] 自检 */
console.log('[1] 解析器自检（防「正则写错 ⇒ 空集恒真 ⇒ 假绿」）')

const brandPaths = pathsOf(src.brand)
const pubPaths = pathsOf(src.favPub)
const sitePaths = pathsOf(src.favSite)

check('S1', `BrandMark.vue 解析到 3 条 path（实测 ${brandPaths.length}）`, brandPaths.length === 3, {
  paths: brandPaths.length,
})
check(
  'S2',
  `两处 favicon 各解析到 ${FAVICON_COUNT} 条 path（实测 ${pubPaths.length} / ${sitePaths.length}）`,
  pubPaths.length === FAVICON_COUNT && sitePaths.length === FAVICON_COUNT,
  { pub: pubPaths.length, site: sitePaths.length },
)
check(
  'S3',
  '合成样本能被 pathsOf 提到（正则活性）',
  pathsOf('<svg><path d="M1 2" fill="none"/><path d="M3 4"/></svg>').length === 2,
  null,
)
check(
  'S4',
  'BRAND_VARS 解析到全部 4 档（含 --brand-ink）',
  Object.keys(brandVars).length === 4 && !!brandInk,
  { keys: Object.keys(brandVars) },
)
check(
  'S5',
  'CSS 块切分器可用（自检：切出的块首尾必须是花括号）',
  (() => {
    const b = cssBlockAfter('.logo-avatar {\n  color: red;\n}', '.logo-avatar')
    return !!b && b.startsWith('{') && b.endsWith('}')
  })(),
  null,
)

/* ============================================== [2] B1 几何真源（组件） */
console.log()
console.log('[2] B1 几何真源逐字（改几何 = 显式改本文件）')
const EXPECT_LABEL = EXPECTED.map((e) => e.name).join('→')
check('B1a', `BrandMark.vue 三条 path 的 d 逐字等于真源（顺序 ${EXPECT_LABEL}）`,
  EXPECTED.every((e, i) => brandPaths[i] && brandPaths[i].d === e.d),
  {
    实际: brandPaths.map((p) => (p.d || '').slice(0, 28) + '…'),
    期望: EXPECTED.map((e) => e.d.slice(0, 28) + '…'),
  })
check('B1b', 'BrandMark.vue 两条描边的 stroke-width 逐字等于真源（体 3.4 / 笑 3.6）',
  brandPaths[1]?.sw === EXPECTED[1].sw && brandPaths[2]?.sw === EXPECTED[2].sw,
  { 实际: [brandPaths[1]?.sw, brandPaths[2]?.sw], 期望: [EXPECTED[1].sw, EXPECTED[2].sw] })
check('B1c', 'BrandMark.vue 的笔画全部走 currentColor（只画笔触、不管底色）',
  brandPaths[0]?.fill === 'currentColor' &&
    brandPaths[1]?.stroke === 'currentColor' &&
    brandPaths[2]?.stroke === 'currentColor',
  { fills: brandPaths.map((p) => p.fill), strokes: brandPaths.map((p) => p.stroke) })

/* ================================== [3] B2 favicon 是「删笑脸」严格子集 */
console.log()
console.log('[3] B2 favicon = 组件的**严格子集**（只少「笑」那一条，其余逐字相同）')
for (const [label, ps, key] of [
  ['产品站', pubPaths, 'favPub'],
  ['官网', sitePaths, 'favSite'],
]) {
  const ids = ['B2a', 'B2b'][key === 'favPub' ? 0 : 1]
  const same = ps.every((p, i) => p.d === brandPaths[i]?.d)
  const missing = brandPaths.filter((bp) => !ps.some((p) => p.d === bp.d)).map((p) => p.d)
  const onlySmileMissing = missing.length === 1 && missing[0] === EXPECTED[2].d
  check(ids, `${label} favicon 两条 path 与组件**前两条逐字相同**，且**恰少「笑」**`,
    same && onlySmileMissing, { 逐字相同: same, 缺失条数: missing.length, 缺的不是笑: !onlySmileMissing })
}

/* ================================================ [4] B3 跨仓几何对账 */
console.log()
console.log('[4] B3 两处 favicon 几何块逐字一致（跨仓：frontend/public ↔ site/assets）')
const blockPub = svgBlock(src.favPub)
const blockSite = svgBlock(src.favSite)
check('B3', '两处 favicon 的 <svg> 整块逐字一致（注释可不同、几何不可不同）',
  !!blockPub && blockPub === blockSite,
  { pub: (blockPub || '').slice(0, 60) + '…', site: (blockSite || '').slice(0, 60) + '…' })

/* ================================================ [5] B4 徽章底与 L1 同源 */
console.log()
console.log('[5] B4 favicon 底徽章 = 48 圆角方 + `--brand-ink`（色值现取，不手写）')
for (const [label, code, rects] of [
  ['产品站', 'B4a', rectsOf(src.favPub)],
  ['官网', 'B4b', rectsOf(src.favSite)],
]) {
  const r = rects[0]
  check(code, `${label} favicon 只有 1 个 rect 且 = ${BADGE.size}×${BADGE.size} / rx ${BADGE.rx} / fill ${brandInk}`,
    rects.length === 1 && r.w === BADGE.size && r.h === BADGE.size && r.rx === BADGE.rx && r.fill === brandInk,
    { rectCount: rects.length, 实得: r })
}

/* ============================== [6] B5+B6 L1 结构上不随主题（最强的一条） */
console.log()
console.log('[6] B5/B6 L1 品牌层**结构上**住在主题表之外（不是「三档碰巧同值」）')
const themeTables = ['LIGHT_VARS', 'DARK_VARS', 'MACARON_VARS']
const leaked = themeTables.filter((t) => {
  const b = blockAfter(src.presets, `const ${t}`)
  return b ? /--brand\b/.test(b) : false
})
check('B5a', `三张主题表（${themeTables.join(' / ')}）里**一处** --brand* 都没有`,
  leaked.length === 0, { 泄漏在: leaked })
check('B5b', '三张主题表都解析到了（防"切不出块 ⇒ 空集恒真"）',
  themeTables.every((t) => !!blockAfter(src.presets, `const ${t}`)), null)
check('B6a', 'installThemeStyles 把 BRAND_VARS 拼成 `:root {` 块（**不带** [data-theme] 限定）',
  /const brand = `:root \{/.test(src.presets) && /Object\.entries\(BRAND_VARS\)/.test(src.presets), null)
check('B6b', 'brand 块真的进了最终注入的 CSS（`el.textContent` 里引用了它）',
  /el\.textContent = `\$\{brand\}/.test(src.presets), null)
check('B6c', '主题块的模板串里**不含** --brand（否则品牌色会被某一档覆盖）',
  (() => {
    const i = src.presets.indexOf('return `html[data-theme="')
    if (i < 0) return false
    const seg = src.presets.slice(i, src.presets.indexOf('`', i + 30))
    return !/--brand/.test(seg)
  })(), null)

/* ================================================ [7] B7 标识点枚举 */
console.log()
console.log('[7] B7 `data-brand-mark` 机器可读标记（枚举全部品牌标识点）')
const marked = []
for (const [label, key, file] of [
  ['侧栏 Workspace', 'workspace', 'src/views/Workspace.vue'],
  ['登录 Login', 'login', 'src/views/Login.vue'],
]) {
  const t = stripComments(src[key])
  const n = (t.match(/data-brand-mark/g) || []).length
  // 同一元素里必须有 BrandMark（标记了却没挂组件 = 假标记）
  const hasComp = /<BrandMark\b/.test(t)
  marked.push({ label, n, hasComp, file })
}
check('B7a', `恰好 2 处 data-brand-mark（实测 ${marked.reduce((a, b) => a + b.n, 0)} 处）`,
  marked.every((m) => m.n === 1), marked)
check('B7b', '每处标记所在文件都真的挂了 <BrandMark />（防「标了没挂」）',
  marked.every((m) => m.hasComp), marked.map((m) => ({ [m.label]: m.hasComp })))
// 注释里**提属性名**是必要的（本组判据就是按它枚举的）；危险的是**标签形式**的示例 ——
// 那会让"未剥注释"的文本判据把注释当成一个真实标识点多算一处。判据只认标签形式。
check('B7c', 'BrandMark.vue 注释里没有**标签形式**的示例（`<… data-brand-mark …>`）',
  !/<[a-zA-Z][^>]{0,200}data-brand-mark/.test(src.brand),
  { 说明: '属性名单独出现无害；带尖括号的示例会被未剥注释的文本判据枚举成假标识点' })

/* ================================================ [8] B8 旧写法 0 残留 */
console.log()
console.log('[8] B8 旧写法 0 残留（本轮修掉的病，不许回来）')
const logoAvatars = {
  workspace: cssBlockAfter(src.workspace, '.logo-avatar'),
  login: cssBlockAfter(src.login, '.logo-avatar'),
}
check('B8a', 'Workspace `.logo-avatar` 块内不再取 var(--primary)（★ 传家宝：必须**切出块**再判）',
  !!logoAvatars.workspace && !/var\(--primary\)/.test(logoAvatars.workspace),
  { 块: logoAvatars.workspace })
check('B8b', 'Login `.logo-avatar` 块内不再取 var(--primary)',
  !!logoAvatars.login && !/var\(--primary\)/.test(logoAvatars.login),
  { 块: logoAvatars.login })
// ★★ 这条与 B8a/B8b **方向相反**，是刻意的 —— 判据是「**直接坐在页面底上的东西
//    必须随主题变**」：标识是自成一体的块（对比度由块内部保证），标题是坐在卡片底上的
//    文字（深色档下 L1 靛蓝只有 2.08:1，连大字号 AA 的 3:1 都不到）。
//    这一条是**真机截图**抓出来的 —— 我第一版的期望值写反了，30 条全绿却深档发暗。
check('B8c', 'Login `.logo h1` 取的是 **L2**（--primary）而不是 L1 —— 坐页面底上的文字必须随主题提亮',
  (() => {
    const b = cssBlockAfter(src.login, '.logo h1')
    return !!b && /color:\s*var\(--primary\)/.test(b) && !/var\(--brand-ink\)/.test(b)
  })(), { 块: cssBlockAfter(src.login, '.logo h1') })
check('B8d', 'index.html 不再引 /vite.svg（实测该文件**根本不存在** ⇒ 此前 favicon 是 404）',
  !/vite\.svg/.test(stripComments(src.indexHtml)), null)
check('B8e', 'index.html 引的是 /favicon.svg',
  /rel="icon"[^>]*href="\/favicon\.svg"/.test(src.indexHtml), null)

/* ================================================ [9] B9/B10/B11 三道硬约束 */
console.log()
console.log('[9] B9 对比度 / B10 16px 下限 / B11 消费点同源')
const cInk = brandInk ? contrast(brandInk, WHITE) : 0
check('B9', `--brand-ink ${brandInk} 上的白笔画 ≥ 4.5:1（实测 ${cInk.toFixed(2)}:1）`,
  cInk >= 4.5, { 对比度: +cInk.toFixed(3) })

// ★ 读的是**源文件里实际的 stroke-width**，不是本文件的 EXPECTED ——
//   后者是自证（拿常量算常量，永远成立）。这样"有人把描边改细"才真能打穿这一条。
const swValues = brandPaths.map((p) => parseFloat(p.sw)).filter((n) => !isNaN(n))
const minSw = Math.min(...swValues)
const px16 = (minSw / GRID) * 16
check('B10', `最细笔画 ${minSw} 在 16px 下 = ${px16.toFixed(3)}px ≥ ${MIN_STROKE_AT_16}px（favicon 绝不糊成一片）`,
  px16 >= MIN_STROKE_AT_16, { minStroke: minSw, at16: +px16.toFixed(3) })

check('B11a', '两处 .logo-avatar 的底色都取 var(--brand-ink)（与 favicon 同源）',
  /background:\s*var\(--brand-ink\)/.test(logoAvatars.workspace || '') &&
    /background:\s*var\(--brand-ink\)/.test(logoAvatars.login || ''), null)
check('B11b', '`.logo-avatar` 的圆角与 favicon 的 rx 同比例（18.75% = 9/48）',
  /border-radius:\s*18\.75%/.test(logoAvatars.workspace || '') &&
    /border-radius:\s*18\.75%/.test(logoAvatars.login || ''), null)

/* ------------------------------------------------------------------ 汇总 */
console.log()
const pass = results.filter((r) => r.ok).length
console.log(`=== 汇总：${pass} PASS / ${failed} FAIL ===`)
if (failed) {
  console.log(
    'RESULT: FAIL —— 品牌标识的三处几何 / L1 分层 / 16px 下限有一处不成立。\n' +
      '        改几何请**显式**改本文件的 EXPECTED（那是设计决策的唯一入口）。',
  )
  process.exit(1)
}
console.log('RESULT: PASS（几何唯一真源 · favicon 严格子集 · L1 不随主题 · 16px 不糊）')

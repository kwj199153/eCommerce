#!/usr/bin/env node
/**
 * 主题色门禁（零依赖 · 只读源码 · 不起服务）
 *
 * ============================================================================
 * 为什么需要它（这是 eEducation `docs/产品色分层与主题-456.md` §4 的建议，我们先落地）
 * ============================================================================
 * 实测：本仓此前**没有任何**判据校验主题色。后果是下面这些**全部无声**：
 *   · 三档 `--primary` 被改成任意值；
 *   · `vars --primary` 与 antd `colorPrimary` 分家（"自定义的主色 ≠ antd 的主色"）；
 *   · 文件头注释说"三档一致"，而实际三档不一致（本仓最忌讳的**静默不一致**）；
 *   · 主按钮底 + 白字掉到 AA 以下（旧值 `#1890ff` 就是 3.24:1，肉眼看不出来）；
 *   · 图表组件里那份主色**副本**与 presets.ts 悄悄漂移。
 *
 * 判据设计口径（照本仓既有铁律）：
 *   · **一律剥注释**再判 —— 注释里故意留着旧值当"为什么换色"的留痕；
 *     ★ 唯一例外是 T3：它判的**正是注释内容的存在性**（文件头有没有写清分层），
 *       剥注释等于判了个空 ⇒ T3 必须读**未剥注释**的原文。
 *   · **期望值不手写色值以外的东西**：三档主色是"已知值"，改它必须**显式**改本文件
 *     （这是刻意的：品牌色是设计决策，不该被"顺手调一下"带走）；
 *   · 每条判据都配**自检**（防正则写错 ⇒ 空集恒真 ⇒ 假绿）。
 *
 * 反向注入（证明本门禁不是空跑；两个源都可用环境变量改指向副本）：
 *   PRESETS_SRC=<副本>    ⇒ 改主色 / 改一档不一致 / 拆掉分层注释 ⇒ 对应判据必须变红
 *   TREEMAP_SRC=<副本>    ⇒ 改图表里的 blue 副本 ⇒ T6 必须变红
 *
 * 怎么跑：node scripts/check-theme-colors.cjs
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const PRESETS = pick('PRESETS_SRC', path.join(ROOT, 'src', 'theme', 'presets.ts'))
const TREEMAP = pick('TREEMAP_SRC', path.join(ROOT, 'src', 'components', 'charts', 'EChartsTreemap.vue'))

/* ------------------------------------------------------------------ 期望值 */

/** 三档主题主色 —— ★ 改这个表 = 一次**显式**的品牌决策（不是随手调色） */
const EXPECTED_PRIMARY = {
  light: '#4f46e5', // 深海靛（= L1 品牌色本体）
  dark: '#756eea', // 同色相抬明度（L≈0.21，两角色等痛点）
  macaron: '#c33a76', // 树莓（暖粉底上换档 —— L2 允许不同色相）
}

/** 品牌色色相与家族容差 */
const BRAND_HUE = 243.4
const HUE_TOL = 6

/** 画布底（算对比度用） */
const WHITE = '#ffffff'
const PAGE_LIGHT = '#f5f7fa' // = light --bg-base
const PANEL_DARK = '#1f1f1f' // = dark --bg-elevated

/** 旧蓝色 token：不应再出现在主色家族里 */
const OLD_BLUES = ['#1890ff', '#40a9ff', '#177ddc', '#3d9be6', '#0958d9']

/* ------------------------------------------------------------------ 工具 */

let failed = 0
const results = []
function check(id, desc, ok, detail) {
  results.push({ id, desc, ok, detail })
  if (!ok) failed++
  const tag = ok ? 'PASS' : 'FAIL'
  console.log(`  ${tag}  ${id.padEnd(4)} ${desc}`)
  if (!ok && detail !== undefined) {
    console.log(`        ↳ ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`)
  }
}

/** 剥掉 TS / CSS / HTML 注释（判据铁律：注释会骗过字符串判据） */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
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
function hue(hex) {
  const h = hex.replace('#', '')
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
const hueDist = (a, b) => {
  const d = Math.abs(a - b) % 360
  return Math.min(d, 360 - d)
}

/** 取出 `const NAME = {` 之后到 `}` 那一段（大括号配平） */
function blockAfter(src, marker) {
  const i = src.indexOf(marker)
  if (i < 0) return null
  const start = src.indexOf('{', i)
  if (start < 0) return null
  let depth = 0
  for (let j = start; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') {
      depth--
      if (depth === 0) return src.slice(start, j + 1)
    }
  }
  return null
}

/**
 * 从一个块里取 `'--name': <颜色字面量>`，两种形态都认：
 *   · `'#rrggbb'`                —— 亮档 / macaron 档
 *   · `'rgba(r, g, b, a)'`       —— 深档的半透明底/边（#1f1f1f 底上靠 alpha 混色）
 * ★ 只认 hex 是一个**实测踩过的坑**：深档 5 个家族键是 rgba，只匹配 hex 会让
 *   T4.dark 静默只扫到 3 键 —— 看起来通过，实际漏了 5 个键没判。色相交由 rgb 三元组决定，
 *   与 alpha 无关，所以取三元组换 hex 后照常算色相。
 */
function varOf(block, name) {
  if (!block) return null
  const src = new RegExp(`'--${name}'\\s*:\\s*'([^']+)'`).exec(block)
  if (!src) return null
  const v = src[1].trim()
  const hex = /^#[0-9a-fA-F]{6}$/.test(v) ? v.toLowerCase() : rgbLiteralToHex(v)
  return hex
}

/** `rgba(79, 70, 229, 0.18)` / `rgb(79,70,229)` → `#4f46e5`；不识别返回 null */
function rgbLiteralToHex(v) {
  const m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(v)
  if (!m) return null
  return (
    '#' +
    m
      .slice(1, 4)
      .map((n) => Math.min(255, parseInt(n, 10)).toString(16).padStart(2, '0'))
      .join('')
  )
}

/** 从一个块里取 `key: '#rrggbb'`（不带引号的键） */
function tokenOf(block, key) {
  if (!block) return null
  const m = new RegExp(`\\b${key}\\s*:\\s*'(#[0-9a-fA-F]{6})'`).exec(block)
  return m ? m[1].toLowerCase() : null
}

/* ------------------------------------------------------------------ 解析 */

const rawPresets = fs.readFileSync(PRESETS, 'utf8')
const srcPresets = stripComments(rawPresets)
const srcTreemap = stripComments(fs.readFileSync(TREEMAP, 'utf8'))

const BLOCKS = {
  light: blockAfter(srcPresets, 'const LIGHT_VARS'),
  dark: blockAfter(srcPresets, 'const DARK_VARS'),
  macaron: blockAfter(srcPresets, 'const MACARON_VARS'),
  darkPin: blockAfter(srcPresets, 'const DARK_PIN'),
}
// 三档 entry 里的 antd seed：按 entry 名切段后再找 colorPrimary
function entryBlock(name) {
  const i = srcPresets.indexOf(`\n  ${name}: {`)
  if (i < 0) return null
  // 到下一个顶层 entry（缩进 2 空格的 `xxx: {`）为止
  const rest = srcPresets.slice(i + 1)
  const m = /\n  (light|dark|macaron): \{/.exec(rest.slice(1))
  return m ? rest.slice(0, m.index + 1) : rest
}
const ENTRIES = { light: entryBlock('light'), dark: entryBlock('dark'), macaron: entryBlock('macaron') }

/* ------------------------------------------------------------------ 判据 */

console.log('=== 主题色门禁（零依赖 · 只读源码）===\n')

console.log('[1] 自检：解析器真的读到了东西（防「正则写错 ⇒ 空集恒真」）')
check('S1', 'LIGHT_VARS / DARK_VARS / MACARON_VARS / DARK_PIN 四块都解析到',
  !!(BLOCKS.light && BLOCKS.dark && BLOCKS.macaron && BLOCKS.darkPin),
  Object.fromEntries(Object.entries(BLOCKS).map(([k, v]) => [k, v ? v.length : 0])))
check('S2', '三个 entry 段都切出来了',
  !!(ENTRIES.light && ENTRIES.dark && ENTRIES.macaron),
  Object.fromEntries(Object.entries(ENTRIES).map(([k, v]) => [k, v ? v.length : 0])))
const LIGHT_KEYS = BLOCKS.light ? (BLOCKS.light.match(/'--[a-z0-9-]+'/g) || []).length : 0
// —— S3 用**独立实现**对账（数 `--` 开头的键名），不是复用上面的 varOf
const rawKeyCount = (BLOCKS.light.match(/'--/g) || []).length
check('S3', `light 档变量数 = ${LIGHT_KEYS}（两种数法必须一致：${LIGHT_KEYS} / ${rawKeyCount}）`,
  LIGHT_KEYS === rawKeyCount && LIGHT_KEYS >= 60, { LIGHT_KEYS, rawKeyCount })

console.log('\n[2] T1 三档 vars --primary 与 antd colorPrimary 逐档一致（防「自定义的主色 ≠ antd 的主色」）')
for (const name of ['light', 'dark', 'macaron']) {
  const varsPrimary = varOf(BLOCKS[name], 'primary')
  // light / macaron：渲染值 = entry 的 seed；dark：渲染值由 DARK_PIN 决定（seed 会被 formatToken 删掉）
  const antdPrimary = name === 'dark' ? tokenOf(BLOCKS.darkPin, 'colorPrimary') : tokenOf(ENTRIES[name], 'colorPrimary')
  check(`T1.${name}`, `${name}: vars ${varsPrimary} == antd ${antdPrimary}`,
    !!varsPrimary && varsPrimary === antdPrimary, { varsPrimary, antdPrimary })
}

console.log('\n[3] T2 三档主色是已知值（改它必须显式改本门禁）')
for (const [name, want] of Object.entries(EXPECTED_PRIMARY)) {
  const got = varOf(BLOCKS[name], 'primary')
  check(`T2.${name}`, `${name} --primary = ${got}（期望 ${want}）`, got === want, { got, want })
}

console.log('\n[4] T3 文件头必须写明 L1 / L2 分层（防注释与代码再次分家）')
// ★ T3 读**未剥注释**的原文：这三条判的就是"注释里有没有写清分层"，
//   用 stripComments 之后的结果去判，等于判了个空（这是本文件第一版的实际 bug）。
const rawHead = rawPresets.slice(0, 4000)
const flatHead = rawHead.replace(/\s+/g, ' ')
check('T3a', '文件头出现 L1 / L2 / L3 三个层号',
  ['L1', 'L2', 'L3'].every((k) => rawHead.includes(k)),
  { 缺失: ['L1', 'L2', 'L3'].filter((k) => !rawHead.includes(k)) })
check('T3b', '文件头点名「品牌色」与「主题主色」两个概念',
  rawHead.includes('品牌色') && rawHead.includes('主题主色'),
  { 缺失: ['品牌色', '主题主色'].filter((k) => !rawHead.includes(k)) })
check('T3c', '文件头含「不要把三档不一致当漂移去修」的防误改警告',
  /不(要|得).{0,20}三档.{0,20}(不一致|不同).{0,20}(漂移|漂|修)/.test(flatHead),
  null)

console.log('\n[5] T4 主色家族同色相（品牌色 ±6°）—— L2 的定义就是「一个色相 + 多档明度」')
const FAMILY = ['primary', 'primary-hover', 'primary-strong', 'info-bg', 'info-border', 'info-bg-2', 'primary-bg-subtle', 'primary-border-subtle']
for (const name of ['light', 'dark']) {
  const off = []
  for (const k of FAMILY) {
    const v = varOf(BLOCKS[name], k)
    if (!v) continue // 差值表可能不覆盖某些键
    const d = hueDist(hue(v), BRAND_HUE)
    if (d > HUE_TOL) off.push(`${k}=${v}(${d.toFixed(1)}°)`)
  }
  const scanned = FAMILY.filter((k) => varOf(BLOCKS[name], k)).length
  check(`T4.${name}`, `${name} 家族 ${scanned} 键全部在 ${BRAND_HUE}°±${HUE_TOL} 内`,
    off.length === 0 && scanned >= 6, off.length ? off : { scanned })
}

console.log('\n[6] T5 主色家族的 AA 硬约束（旧值 #1890ff 白字只有 3.24:1，肉眼看不出来）')
const lightPairs = [
  ['light --primary 白字', varOf(BLOCKS.light, 'primary'), WHITE, 4.5],
  ['light --primary-hover 白字', varOf(BLOCKS.light, 'primary-hover'), WHITE, 4.5],
  ['light --primary-strong 对页底', varOf(BLOCKS.light, 'primary-strong'), PAGE_LIGHT, 4.5],
  ['dark --primary-hover 对深面板', varOf(BLOCKS.dark, 'primary-hover'), PANEL_DARK, 4.5],
  ['dark --primary-strong 对深面板', varOf(BLOCKS.dark, 'primary-strong'), PANEL_DARK, 4.5],
]
let aaBad = []
for (const [label, v, bg, need] of lightPairs) {
  if (!v) { aaBad.push(`${label}: 取不到值`); continue }
  const c = contrast(v, bg)
  const ok = c >= need
  if (!ok) aaBad.push(`${label} = ${c.toFixed(2)} < ${need}`)
  console.log(`         ${label.padEnd(30)} ${c.toFixed(2)}:1  ${ok ? 'OK' : '不达'}`)
}
check('T5', '五条硬约束全部达标', aaBad.length === 0, aaBad)
// ★ dark --primary 刻意**不列入**：它身兼「按钮底 / 强调文字」两个相反角色，
//   数学上限 4.06:1（解 (L+0.05)² = 1.05×0.0637）。这里把它**打印出来**而不是判红 ——
//   判红只会逼人把两个角色塞回一个 token，问题不会消失。见 docs 的登记项。
const dp = varOf(BLOCKS.dark, 'primary')
console.log(`         dark --primary 白字 ${contrast(dp, WHITE).toFixed(2)}:1 / 对深面板 ${contrast(dp, PANEL_DARK).toFixed(2)}:1`
  + `  ← 两角色折中，上限 4.06（登记项，不判红）`)

console.log('\n[7] T6 图表里的主色**副本**必须与 presets.ts 逐字一致（跨文件对账）')
const treemapDark = tokenOf(srcTreemap, 'blue')
// 亮色那份在文件后半段，取第二处
const allBlue = [...srcTreemap.matchAll(/\bblue:\s*'(#[0-9a-fA-F]{6})'/g)].map((m) => m[1].toLowerCase())
check('T6a', `从 EChartsTreemap.vue 解析出 2 处 blue（实得 ${allBlue.length}）`, allBlue.length === 2, allBlue)
check('T6b', `暗档 blue ${allBlue[0]} == presets dark --primary ${varOf(BLOCKS.dark, 'primary')}`,
  allBlue[0] === varOf(BLOCKS.dark, 'primary'), { treemap: allBlue[0], presets: varOf(BLOCKS.dark, 'primary') })
check('T6c', `亮档 blue ${allBlue[1]} == presets light --primary ${varOf(BLOCKS.light, 'primary')}`,
  allBlue[1] === varOf(BLOCKS.light, 'primary'), { treemap: allBlue[1], presets: varOf(BLOCKS.light, 'primary') })

console.log('\n[8] T7 负对照：旧蓝色不允许出现在主色家族里')
const oldHits = []
for (const name of ['light', 'dark']) {
  for (const k of FAMILY) {
    const v = varOf(BLOCKS[name], k)
    if (v && OLD_BLUES.includes(v)) oldHits.push(`${name}.${k}=${v}`)
  }
}
check('T7', '主色家族 0 处旧蓝', oldHits.length === 0, oldHits)

/* ------------------------------------------------------------------ 汇总 */

const total = results.length
console.log(`\n=== 汇总：${total - failed} PASS / ${failed} FAIL ===`)
if (failed) {
  console.log('FAIL 明细：')
  for (const r of results.filter((x) => !x.ok)) console.log(`  ${r.id}  ${r.desc}`)
  console.log(`\nRESULT: FAIL（${failed}/${total} 红）`)
  process.exit(1)
}
console.log('RESULT: PASS（主题色三档 + 分层注释 + 图表副本 + AA 硬约束全部对账通过）')
process.exit(0)

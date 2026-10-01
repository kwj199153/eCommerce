#!/usr/bin/env node
/**
 * 窗口宽度「档位阶梯」门禁（第 297 轮）
 *
 * ============================================================================
 * ★ 为什么需要它（老板原话：「即使是手动写也要有规格……以后才好复用」）
 * ============================================================================
 * 第 297 轮盘点：全仓 `a-drawer` / `a-modal` 共 51 个窗口，宽度铺成 **14 个数值档**
 * （400/420/440/460/480/500/520/540/560/600/620/640/680/720），全部是手写魔法数。
 * 老板拍板两件事：只建**规格常量表**（`src/config/layout.ts`）、本轮**收敛到 6 档**。
 *
 * 「有规格」如果只写在文档里，下一轮就会漂移 —— 文档不会自己变红。所以真正的形态
 * 是这条门禁：**新窗口要么从 `WINDOW_W` 取档，要么红**。
 *
 * ============================================================================
 * ★ 判据口径（本仓纪律，逐条都有来源）
 * ============================================================================
 *   · **先剥注释再判**：本文件自己的注释里就写着 `<a-drawer :width="520">` 这类示例，
 *     不剥注释就是自己喂饱自己（假绿）。剥除时**保留换行**，让报错行号仍然精确。
 *   · **档位表从源码正则抽取**，不 `require` 一个 `.ts`（门禁是 `.cjs`，没有 TS 运行时）；
 *     抽取范围**限定在 `export const WINDOW_W = {` … `} as const` 之内** ——
 *     layout.ts 的注释里写着全部 14 档的旧分布，全文抓数字必然误判。
 *   · **必须自证没空跑**：扫到 0 个窗口标签时直接失败。历史上出现过「扫描器坏了 ⇒
 *     命中 0 ⇒ 全部通过」的假绿。
 *   · **不钉「恰好 51 处」**：数量是钉住旧形态的负资产；判据是**每个窗口的形态**。
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   WINDOW_SRC_ROOT=<副本或空目录>    ⇒ 规格表与窗口扫描全线红（含「扫到 0 直接失败」）
 *
 */

const fs = require('fs')
const path = require('path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const SRC = pick('WINDOW_SRC_ROOT', path.join(__dirname, '..', 'src'))
const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

function read(rel) {
  const p = path.join(SRC, rel)
  if (!fs.existsSync(p)) return null
  // 行尾归一化必须**真做**：本仓同一目录下 CRLF / LF 混存
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/**
 * 剥 HTML 注释；**保留换行**，使行号不失真。
 *
 * ★ **刻意不剥块注释**（星号注释）—— 这不是偷懒，是本轮踩出来的坑：
 *   块注释正则 `\/\*[\s\S]*?\*\//` 会误伤**字符串里的「斜杠 + 星号」**。
 *   `views/Settings.vue` 的 `<a-upload accept="image/*">` 恰好含这一对字符，
 *   正则把它当成注释开始，一路匹配到 `<script>` 区 JSDoc 的结尾，
 *   **吞掉 L25~L378 共 13,483 字符**（含 3 个真实弹窗）⇒ 门禁静默漏检。
 *   当时的症状是：全仓窗口数从 51 掉到 48，而自检 `S0d` 照样通过
 *   （它只判「> 0」，看不出「少扫了」）。
 *   ⇒ 窗口标签只可能出现在 `<template>` 区，那里只有 HTML 注释，所以剥它一个就够。
 */
function stripComments(src) {
  if (src == null) return ''
  return src.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ''))
}

/** 扫描 `a-drawer` / `a-modal` 起始标签（跨行、跳过引号内的 `>`）。 */
function scanWindows(src) {
  const out = []
  const re = /<(a-drawer|a-modal)\b/g
  let m
  while ((m = re.exec(src)) !== null) {
    let j = m.index + m[0].length
    let q = null
    while (j < src.length) {
      const c = src[j]
      if (q) { if (c === q) q = null }
      else if (c === '"' || c === "'") q = c
      else if (c === '>') break
      j++
    }
    out.push({
      tag: m[1],
      text: src.slice(m.index, j + 1),
      line: src.slice(0, m.index).split('\n').length,
    })
  }
  return out
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = path.join(dir, d.name)
    if (d.isDirectory()) return walk(p)
    return d.name.endsWith('.vue') ? [p] : []
  })
}

// ---------------- 抽取规格表 ----------------
const layout = read('config/layout.ts')
const flat = layout || ''

const blockM = /export const WINDOW_W = \{([\s\S]*?)\} as const/.exec(flat)
const steps = []
if (blockM) {
  const re = /(\w+):\s*(\d+)\s*,/g
  let m
  while ((m = re.exec(blockM[1])) !== null) steps.push({ token: m[1], value: Number(m[2]) })
}
const valuesM = /export const WINDOW_W_VALUES[^=]*=\s*\[([^\]]*)\]/.exec(flat)
const declaredValues = valuesM
  ? (valuesM[1].match(/\d+/g) || []).map(Number)
  : []

// ---------------- S0 自检：先证明没空跑 ----------------
check(!!layout, 'S0a 读到 src/config/layout.ts')
check(!!blockM && steps.length > 0, 'S0b 能从 layout.ts 抽出 WINDOW_W 档位块', blockM ? `抽出 ${steps.length} 档` : '未匹配到 `export const WINDOW_W = {` … `} as const`')
check(!!valuesM && declaredValues.length > 0, 'S0c 能从 layout.ts 抽出 WINDOW_W_VALUES 数组')

const vueFiles = walk(SRC)
const allWindows = []
for (const p of vueFiles) {
  const raw = fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
  for (const w of scanWindows(stripComments(raw))) {
    allWindows.push({ rel: path.relative(SRC, p).replace(/\\/g, '/'), ...w })
  }
}
check(allWindows.length > 0, 'S0d 扫到了窗口标签（=0 说明扫描器坏了，不能算通过）', `扫到 ${allWindows.length} 个`)

// ---------------- S1 阶梯形状 ----------------
const stepValues = steps.map((s) => s.value)
const ascending = stepValues.every((v, i) => i === 0 || v > stepValues[i - 1])
check(steps.length === 6, 'S1a 窗口阶梯恰好 6 档（第 297 轮收敛目标）', stepValues.join(', '))
check(ascending, 'S1b 6 档升序（阶梯是有序的，后续并档规则依赖这个不变量）', stepValues.join(' < '))
check(new Set(stepValues).size === stepValues.length, 'S1c 档位无重复')
check(new Set(steps.map((s) => s.token)).size === steps.length, 'S1d token 名无重复')

// ---------------- S2 两张表对账 ----------------
const sameSet = declaredValues.length === stepValues.length
  && [...declaredValues].sort((a, b) => a - b).join(',') === [...stepValues].sort((a, b) => a - b).join(',')
check(sameSet, 'S2 WINDOW_W_VALUES 与 WINDOW_W 的档位集合一致（drift ⇒ 红）',
  `数组=[${declaredValues.join(', ')}] 块=[${stepValues.join(', ')}]`)

// ---------------- S3 每个窗口都走常量 ----------------
const tokenSet = new Set(steps.map((s) => s.token))
const attrRe = /:width\s*=\s*"WINDOW_W\.(\w+)"/
const bad = []
for (const w of allWindows) {
  const m = attrRe.exec(w.text)
  if (!m) { bad.push(`${w.rel}:${w.line} <${w.tag}> 没有 :width="WINDOW_W.<token>"`); continue }
  if (!tokenSet.has(m[1])) { bad.push(`${w.rel}:${w.line} <${w.tag}> 用了阶梯外的 token: ${m[1]}`) }
}
check(bad.length === 0, 'S3 全仓窗口的宽度一律取自 WINDOW_W（未写 / 字面量 / 野 token 都算红）',
  bad.length ? `${bad.length} 处：\n      ` + bad.join('\n      ') : `${allWindows.length} 个窗口全部合规`)

// ---------------- S4 字面量残留必须为 0 ----------------
const litRe = /(?<![-\w:])(?::width\s*=\s*"(\d+)")|(?<![-\w:])\bwidth\s*=\s*"(\d+)(?:px)?"/
const lits = []
for (const w of allWindows) {
  const m = litRe.exec(w.text)
  if (m) lits.push(`${w.rel}:${w.line} <${w.tag}> ${m[0].trim()}`)
}
check(lits.length === 0, 'S4 窗口标签内没有宽度字面量（含 `width="720px"` 这种带后缀的写法）',
  lits.length ? `${lits.length} 处：\n      ` + lits.join('\n      ') : '零残留')

// ---------------- S5 布局槽位也收了口 ----------------
const ws = read('views/Workspace.vue')
const wsCode = stripComments(ws || '')
check(/:width="isWidePanel \? PANEL_W\.panelWide : PANEL_W\.panelNormal"/.test(wsCode),
  'S5a 右栏 sider 宽度取自 PANEL_W（340 / 528 不再手写）')
check(/:width="PANEL_W\.sidebar"/.test(wsCode),
  'S5b 左栏 sider 宽度取自 PANEL_W.sidebar（260）')

// ---------------- S6 登记 ----------------
const pkg = (() => {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')) } catch { return null }
})()
check(!!pkg && /check-window-widths\.cjs/.test(String(pkg.scripts?.['check:window-widths'] || '')),
  'S6a package.json 登记了 check:window-widths')
check(!!pkg && /check-window-widths\.cjs/.test(String(pkg.scripts?.build || '')),
  'S6b 本门禁已接入 npm run build 链')

// ---------------- 汇总 ----------------
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.label}${r.ok ? '' : '  ⟵ ' + (r.detail || '')}`)
}
console.log(`\n---- ${results.length - failed.length}/${results.length} 通过 ----`)
if (failed.length) {
  console.log('红：' + failed.map((r) => r.label.split(' ')[0]).join(', '))
  process.exit(1)
}
console.log(
  `窗口宽度门禁通过（6 档阶梯 [${stepValues.join(', ')}] · ${allWindows.length} 个窗口全走 WINDOW_W · 零字面量 · 布局槽位走 PANEL_W ✓）`
)

#!/usr/bin/env node
/**
 * 窄屏（pad / 手机）适配 · 静态门禁
 * ================================
 * 第 375 轮。真机门禁是同目录外的 `.workbuddy/probes/tools/cdp-viewport-audit.mjs`
 * （七档视口 × 三态），但它要起 dev server + 浏览器，**不进 build 链**。
 * 本文件是能在 build 链里跑的那一半：它保证「代码长成这个样子」，
 * 真机门禁保证「跑起来真的是这个样子」——两层各管一段，缺一不可。
 *
 * ★ 本仓铁律（照 r373 的做法）：
 *   · 一律**先剥注释再判**：注释里故意写满了旧值/反例（比如"原先用 innerWidth"），
 *     不剥就会把它们当成代码命中。
 *   · 每条判据都要能自证：开头 S 组先证明"源读到了、关键块切出来了"，
 *     否则空集会让断言恒真（`.includes()` 在不存在的块上恒 False，取反就恒真）。
 *
 * 用法：node scripts/check-responsive.cjs
 * 退出码：0=全通过 / 1=有失败
 */
'use strict'

const fs = require('fs')
const path = require('path')

const FE = path.join(__dirname, '..')
const R = (p) => path.join(FE, p)

// ★ 三个路径都可用环境变量改指向 —— 变异自证脚本（`.workbuddy/probes/mutate-responsive.mjs`）
//   靠这个把"改坏的副本"喂进来，**全程不碰真源**（真源被改坏 = 门禁自己失去意义）。
const FILES = {
  layout: process.env.RESP_LAYOUT || R('src/config/layout.ts'),
  workspace: process.env.RESP_WORKSPACE || R('src/views/Workspace.vue'),
  // ★ 第 376 轮：新手引导的发命令侧。它与 Workspace 是一对**反过来**的命令
  //   （ensure-* 打开浮层 / reset-layout 收回），任何一边缺失都会让窄屏左栏回不到折叠态。
  tour: process.env.RESP_TOUR || R('src/components/Tour/TourHost.vue'),
  // 真机门禁（Node 脚本）：只读它的常量，防止它与 layout.ts 漂移
  probe: process.env.RESP_PROBE || R('../.workbuddy/probes/tools/cdp-viewport-audit.mjs'),
}

let pass = 0
let fail = 0
const check = (ok, id, label, detail) => {
  if (ok) pass++
  else fail++
  const d = detail === undefined ? '' : `  ⟵ ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${id}  ${label}${d}`)
}

const read = (p) => {
  if (!fs.existsSync(p)) return null
  return fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
}

/* ---------------------------------------------------------------- 剥注释 */
/** 剥 HTML 注释（Vue 模板段用） */
const stripHtml = (s) => s.replace(/<!--[\s\S]*?-->/g, '')
/** 剥块注释 + 行注释（TS/JS 用）。`//` 前必须不是 `:`（避开 `https://`） */
const stripJs = (s) =>
  s
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:\\])\/\/[^\n]*/g, '$1')
/** 剥 CSS 块注释（CSS 里 `//` 不是注释，所以只剥块注释） */
const stripCss = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')

/** 从 .vue 源码里切出三段（未剥注释的原文） */
function vueSections(src) {
  const tpl = src.match(/<template>([\s\S]*)<\/template>/)
  const script = src.match(/<script[^>]*>([\s\S]*)<\/script>/)
  const style = src.match(/<style[^>]*>([\s\S]*)<\/style>/)
  return {
    template: tpl ? tpl[1] : '',
    script: script ? script[1] : '',
    style: style ? style[1] : '',
  }
}

/* ------------------------------------------------------------------ 读取 */
console.log('=== 窄屏适配 · 静态门禁（第 375 轮）===\n')
console.log('[S] 自检：源文件与关键块都得真的读到')

const layoutSrc = read(FILES.layout)
const wsSrc = read(FILES.workspace)
const tourSrc = read(FILES.tour)
const probeSrc = read(FILES.probe)

check(!!layoutSrc && layoutSrc.length > 1000, 'S1a', 'config/layout.ts 读到了且非空', layoutSrc ? `${layoutSrc.length} B` : 'MISSING')
check(!!wsSrc && wsSrc.length > 10000, 'S1b', 'views/Workspace.vue 读到了且非空', wsSrc ? `${wsSrc.length} B` : 'MISSING')
check(!!tourSrc && tourSrc.length > 3000, 'S1c', 'Tour/TourHost.vue 读到了且非空', tourSrc ? `${tourSrc.length} B` : 'MISSING')
check(!!probeSrc && probeSrc.length > 3000, 'S1d', '真机门禁探针读到了且非空', probeSrc ? `${probeSrc.length} B` : 'MISSING')

const ws = wsSrc ? vueSections(wsSrc) : { template: '', script: '', style: '' }
const tpl = stripHtml(ws.template)
const scr = stripJs(ws.script)
const sty = stripCss(ws.style)
const lay = stripJs(layoutSrc || '')

check(tpl.length > 1000, 'S2a', 'Workspace 模板段切出来了', `${tpl.length} B`)
check(scr.length > 5000, 'S2b', 'Workspace 脚本段切出来了', `${scr.length} B`)
check(sty.length > 5000, 'S2c', 'Workspace 样式段切出来了', `${sty.length} B`)
check(/@media|\.is-narrow/.test(sty), 'S2d', '样式段里确实含有响应式相关规则（防空集）')

/* ------------------------------------------------- ① 断点真源（唯一一处） */
console.log('\n[B] 断点真源：VIEWPORT_BP / NARROW_MEDIA_QUERY')

const bpBlock = (lay.match(/export const VIEWPORT_BP\s*=\s*\{[\s\S]*?\}\s*as const/) || [''])[0]
check(!!bpBlock, 'B1a', 'layout.ts 里存在 `VIEWPORT_BP = {...} as const`')
const narrowNum = (bpBlock.match(/narrow:\s*(\d+)/) || [])[1]
check(!!narrowNum && Number(narrowNum) > 0, 'B1b', 'VIEWPORT_BP.narrow 是个正数', narrowNum)
check(
  narrowNum === '1100',
  'B1c',
  '阈值 = 1100（788 是中栏归零硬下限，iPad 横 1024 必须覆盖 ⇒ >1024；1280 不误伤）',
  narrowNum,
)
check(
  /export const NARROW_MEDIA_QUERY\s*=\s*`\(max-width:\s*\$\{VIEWPORT_BP\.narrow\}px\)`/.test(lay),
  'B1d',
  'NARROW_MEDIA_QUERY 由 VIEWPORT_BP 拼出（不是硬编码 1100 的第二份真源）',
)

// matchMedia 的消费点：全仓只许 Workspace.vue 一处（主题的 prefers-color-scheme 不算）
const mmWorkspace = (scr.match(/matchMedia\(/g) || []).length
check(mmWorkspace === 1, 'B1e', 'Workspace 脚本里 `matchMedia(` 恰好 1 处（禁第二份实现）', mmWorkspace)
check(
  /matchMedia\(NARROW_MEDIA_QUERY\)/.test(scr),
  'B1f',
  '该处 matchMedia 用的是 NARROW_MEDIA_QUERY（不是自己拼的字符串）',
)

// 除 NARROW_MEDIA_QUERY 之外，脚本里不该再出现 1100 这个字面量
const thresholdLits = (scr.match(/\b1100\b/g) || []).length
check(thresholdLits === 0, 'B1g', 'Workspace 脚本里没有裸 1100（阈值只有真源那一处）', thresholdLits)

// 探针里的 NARROW 常量必须与真源同值（漂移 = 真机门禁按错误阈值判 ⇒ 假绿）
const probeNarrow = (stripJs(probeSrc || '').match(/const NARROW = (\d+)/) || [])[1]
check(
  !!probeNarrow && probeNarrow === narrowNum,
  'B1h',
  '真机门禁探针的 NARROW 与 layout.ts 同值（防漂移导致假绿）',
  `${probeNarrow} vs ${narrowNum}`,
)

/* ----------------------------------------------------------- ② 下发方式 */
console.log('\n[D] 下发与行为')

check(/provide\('isNarrow',\s*isNarrow\)/.test(scr), 'D1a', "provide('isNarrow', isNarrow) 存在（禁消费方各算一遍）")
check(
  /'is-narrow':\s*isNarrow/.test(tpl),
  'D1b',
  '根 a-layout 绑定了 `is-narrow` 类',
)
check(
  /flush:\s*'post'/.test(scr),
  'D2a',
  '★ 导航收起用的 watch 带 `flush: \'post\'`（默认 pre 会被 12 处自动展开覆盖）',
)
check(
  /isNarrow\.value\)\s*collapsePanesForNarrow\(\)/.test(scr),
  'D2b',
  'watch 里按 `isNarrow` 收起两栏（不是无条件收）',
)
check(
  /:collapsed-width="isNarrow \? 0 : 80"/.test(tpl),
  'D2c',
  '窄屏左栏收起宽度为 0（不留 80px 常驻窄条）',
)
check(
  /v-if="narrowScrimVisible"/.test(tpl),
  'D2d',
  '遮罩节点带 v-if="narrowScrimVisible"（宽屏不渲染）',
)

/* -------------------------------------------------------------- ③ 形态 */
console.log('\n[C] 窄屏形态：脱流浮层 + 遮罩')

const sidebarBlock = (sty.match(/\.is-narrow \.sidebar\s*\{[\s\S]*?\}/) || [''])[0]
const rightBlock = (sty.match(/\.is-narrow \.right-panel\s*\{[\s\S]*?\}/) || [''])[0]
const scrimBlock = (sty.match(/\.ws-scrim\s*\{[\s\S]*?\}/) || [''])[0]

check(!!sidebarBlock, 'C1a', '存在 `.is-narrow .sidebar { … }` 规则')
check(!!rightBlock, 'C1b', '存在 `.is-narrow .right-panel { … }` 规则')
check(!!scrimBlock, 'C1c', '存在 `.ws-scrim { … }` 规则')

check(/position:\s*fixed/.test(sidebarBlock), 'C2a', '窄屏左栏 position: fixed（脱流，不占中栏宽度）')
check(/position:\s*fixed/.test(rightBlock), 'C2b', '窄屏右栏 position: fixed')
check(/z-index:\s*60/.test(sidebarBlock) && /z-index:\s*60/.test(rightBlock), 'C2c', '两栏 z-index: 60')
check(
  /max-width:\s*84vw\s*!important/.test(sidebarBlock),
  'C2d',
  '左栏宽度上限 84vw（极窄屏留出可点遮罩的边缘）',
)
check(
  /max-width:\s*92vw\s*!important/.test(rightBlock),
  'C2e',
  '右栏宽度上限 92vw（528 在手机上必然超宽）',
)

// ★★★ 这条是本轮实测踩出来的：antd 把 min-width 写在 inline style，
//     而 min-width 优先于 max-width ⇒ 只写 max-width 等于没夹。
check(
  /min-width:\s*0\s*!important/.test(sidebarBlock) && /min-width:\s*0\s*!important/.test(rightBlock),
  'C2f',
  '★ 两栏都写了 `min-width: 0 !important`（否则 antd 的 inline min-width 会顶回宽度）',
)

const scrimZ = Number((scrimBlock.match(/z-index:\s*(\d+)/) || [])[1])
check(!!scrimZ && scrimZ < 60, 'C3a', '遮罩 z-index 低于两栏（55 < 60，否则灰罩盖住浮层）', scrimZ)
check(/inset:\s*0/.test(scrimBlock), 'C3b', '遮罩铺满（inset: 0）')
check(/background:\s*rgba\(0,\s*0,\s*0,/.test(scrimBlock), 'C3c', '遮罩有半透明底色')

/* ------------------------------------------------- ④ 顶栏窄屏降级 */
console.log('\n[E] 顶栏降级')

check(
  /class="ms-label"/.test(tpl),
  'E1a',
  '模式切换按钮的文字包了 `.ms-label`（窄屏要能单独收掉）',
)
check(
  /\.is-narrow \.mode-switch-btn \.ms-label\s*\{[\s\S]*?display:\s*none/.test(sty),
  'E1b',
  '窄屏下 `.ms-label` 被收起（否则 360 屏上顶栏溢出）',
)

/* --------------------------------- ⑤ 引导不得把窄屏左栏留在展开态（第 376 轮） */
console.log('\n[F] 引导的布局命令不得破坏折叠态')

const tourScr = tourSrc ? (tourSrc.match(/<script[^>]*>([\s\S]*)<\/script>/) || ['', ''])[1] : ''
const tourJs = stripJs(tourScr)

check(tourJs.length > 2000, 'F1a', 'TourHost 脚本段切出来了', `${tourJs.length} B`)

// 接收侧（Workspace）：复位函数必须带 isNarrow 守卫 —— 宽屏三栏是默认形态，复位会误收
const resetFn = (scr.match(/function resetLayoutForNarrow\(\)\s*\{[\s\S]*?\n\}/) || [''])[0]
check(!!resetFn, 'F1b', 'Workspace 定义了 resetLayoutForNarrow()')
check(
  /if\s*\(isNarrow\.value\)\s*collapsePanesForNarrow\(\)/.test(resetFn),
  'F1c',
  '★ 复位函数带 isNarrow 守卫（宽屏不许把三栏收成浮层）',
)
const resetAdd = (scr.match(/addEventListener\('tour:reset-layout'/g) || []).length
const resetRm = (scr.match(/removeEventListener\('tour:reset-layout'/g) || []).length
check(
  resetAdd === 1 && resetRm === 1,
  'F1d',
  'tour:reset-layout 的监听与卸载**成对**（少一边 = 组件卸载后仍被外部命令驱动）',
  { add: resetAdd, remove: resetRm },
)

// 发送侧（TourHost）：每步开头先复位、再按需展开；收尾也要复位
const gotoBlock = (tourJs.match(/async function goto\([\s\S]*?\n\}/) || [''])[0]
check(!!gotoBlock, 'F2a', 'TourHost 的 goto() 切出来了', `${gotoBlock.length} B`)
const iReset = gotoBlock.indexOf('runReset()')
const iPrepare = gotoBlock.indexOf('runPrepare(')
check(iReset >= 0, 'F2b', '★ goto() 里有 runReset()（否则上一步打开的浮层永不被收回）')
check(
  iReset >= 0 && iPrepare > iReset,
  'F2c',
  '★ runReset() 在 runPrepare() **之前**（顺序反了 = 打开后又被自己关掉）',
  { reset: iReset, prepare: iPrepare },
)
const finishBlock = (tourJs.match(/function finish\(\)\s*\{[\s\S]*?\n\}/) || [''])[0]
check(!!finishBlock, 'F2d', 'finish() 切出来了')
check(
  /runReset\(\)/.test(finishBlock),
  'F2e',
  '★ finish() 里也复位（最后一步正是 ensure-sidebar，讲完别把浮层留在屏上）',
)

/* ================================================================
 * [G] 资料库（7 个库组件）的窄屏形态
 * ----------------------------------------------------------------
 * 第 380 轮：老板在 pad 上看素材库发现卡片重叠，牵出「7 个资料库共用同一套
 * `height:100% + header + .stat-cards + .toolbar + 表格` 骨架、全都没有媒体查询」。
 * 375 轮那组 [A]~[F] 只覆盖 Workspace 的三栏骨架，管不到库内部。
 *
 * 这一组是**形态判据**：它保证"该有的 CSS 规则写在那儿"，真机门禁
 * （.workbuddy/probes/cdp-kb-narrow-audit.mjs）保证"写在那儿真的管用"。
 * 两层分工与 [A] 组一致 —— 静态这层能在 build 链里跑，真机那层不能。
 *
 * ★ 每条都对应一次实测（对照组实验剔除了不承重的声明，见
 *   docs/资料库窄屏统一适配-r380.md）：
 *     · 删掉 `.toolbar-left/.toolbar-right` 的 wrap ⇒ 768/390 顶出容器
 *     · 删掉主容器的 wrap ⇒ 溢出判据仍绿，但两组**交错**（截图可见）
 *     · 删掉话术库表格的 scroll.x ⇒ 390 档「问题」列被压成 0px
 * ================================================================ */
console.log('\n[G] 资料库窄屏形态（第 380 轮 · 7 个库）')

const KB_DIR = process.env.RESP_KB_DIR || R('src/components/KnowledgeBase')

/** 取出 `<style>` 段并剥注释 —— 注释里写满了这些选择器名，不剥必然假绿 */
const kbStyle = (name) => {
  const p = path.join(KB_DIR, name)
  const raw = read(p)
  if (!raw) return null
  const m = raw.match(/<style[^>]*>([\s\S]*)<\/style>/)
  if (!m) return null
  return m[1].replace(/\/\*[\s\S]*?\*\//g, '')
}

/** 按花括号配平切出 `@media (max-width: Npx) { ... }` 的**内容**（不含外层大括号） */
const mediaBlock = (css, px) => {
  const tag = `@media (max-width: ${px}px)`
  const i = css.indexOf(tag)
  if (i < 0) return null
  let j = css.indexOf('{', i)
  if (j < 0) return null
  let depth = 0
  for (let k = j; k < css.length; k++) {
    if (css[k] === '{') depth++
    else if (css[k] === '}') {
      depth--
      if (depth === 0) return css.slice(j + 1, k)
    }
  }
  return null
}

/**
 * 在某个块里判断「某选择器块内含有某声明」。
 * ★ 不用正则拼装：选择器里有点号、逗号、换行，转义一层套一层很容易写错，
 *   而且这个文件是**手写 CSS 文本**，不是要解析成 AST 的代码 ——
 *   先压平空白，再按 `{`/`}` 切片，够用且不会出错。
 */
const hasDecl = (block, selector, decl) => {
  if (!block) return false
  const squash = (x) => x.split('\n').join(' ').split('\r').join(' ').split('\t').join(' ')
  const collapse = (x) => x.replace(/ +/g, ' ')
  const flat = collapse(squash(block))
  const want = collapse(squash(selector)).trim()
  const i = flat.indexOf(want)
  if (i < 0) return false
  const open = flat.indexOf('{', i)
  const close = flat.indexOf('}', open)
  if (open < 0 || close < 0) return false
  const body = flat.slice(open, close)
  const d = collapse(squash(decl)).trim()
  return body.indexOf(d) >= 0
}

const KB_FILES = {
  assets: 'AssetLibrary.vue',
  products: 'ProductLibrary.vue',
  candidates: 'CandidateLibrary.vue',
  competitors: 'MonitorPoolLibrary.vue',
  faq: 'FaqKnowledgeBase.vue',
  reviews: 'ReviewLibrary.vue',
  rules: 'PlatformRules.vue',
}

const kbStyles = {}
for (const [key, name] of Object.entries(KB_FILES)) kbStyles[key] = kbStyle(name)

// G0 自检：7 个库的 style 段都得真的切出来（空集会让下面所有断言变成"什么都没检查"）
const missing = Object.entries(kbStyles).filter(([, v]) => !v || v.length < 300).map(([k]) => k)
check(missing.length === 0, 'G0', '7 个库的 style 段全部切出来且剥掉注释', missing.length ? missing : undefined)

// 复盘库的骨架是「单列竖向流」，本来就没有要换行的 header，不要求 900 断点
const NEED_900 = ['assets', 'products', 'candidates', 'competitors', 'faq', 'rules']
for (const key of NEED_900) {
  const blk = mediaBlock(kbStyles[key], 900)
  check(!!blk, 'G1', `${key} 有 @media (max-width: 900px)`, blk ? undefined : '断点缺失')
}

// 逐库的承重声明
const blk900 = (k) => mediaBlock(kbStyles[k], 900)
const blk480 = (k) => mediaBlock(kbStyles[k], 480)

check(
  hasDecl(blk900('candidates'), '.toolbar-left, .toolbar-right', 'flex-wrap: wrap'),
  'G2a',
  '★ 选品库 .toolbar-left/.toolbar-right 换行（删掉 ⇒ 768 顶出 32px / 390 顶出 410px）',
)
check(
  hasDecl(blk900('candidates'), '.toolbar', 'flex-wrap: wrap'),
  'G2b',
  '★ 选品库 .toolbar 自身换行（删掉不红，但两组会**交错** —— 真机门禁的「交错」尺子管这条）',
)
check(
  hasDecl(blk900('competitors'), '.mp-head', 'flex-wrap: wrap'),
  'G3',
  '★ 竞品池 .mp-head 换行（删掉 ⇒ 390 档标题折 6 行）',
)
check(
  hasDecl(blk900('faq'), '.header-left, .header-actions', 'flex-wrap: wrap'),
  'G4a',
  '★ 话术库 .header-left/.header-actions 换行（删掉 ⇒ 390 档按钮组顶出 363px）',
)
check(
  hasDecl(blk900('faq'), '.page-header', 'flex-wrap: wrap'),
  'G4b',
  '★ 话术库 .page-header 自身换行（排版：标题组与按钮组各占整行）',
)
check(
  hasDecl(blk480('faq'), '.filter-bar', 'flex-wrap: wrap'),
  'G4c',
  '★ 话术库手机档 .filter-bar 换行（删掉 ⇒ 搜索框被压到 140px，只剩「搜...」）',
)
check(
  hasDecl(blk900('rules'), '.header-actions', 'flex: 1 1 100%'),
  'G5a',
  '★ 规则库 .header-actions 占满一行（原样式 flex-shrink:0 ⇒ 换行后仍按 max-content 溢出 66px）',
)
check(
  hasDecl(blk900('rules'), '.toolbar-left', 'flex-wrap: wrap'),
  'G5b',
  '★ 规则库 .toolbar-left 换行（删掉 ⇒ 390 档三个下拉顶出 314px）',
)

// 统计卡：两个四卡库在 390 档必须收 padding，否则标签折行
for (const key of ['candidates', 'rules']) {
  check(
    hasDecl(blk480(key), '.stat-card', 'padding:'),
    'G6',
    `★ ${key} 手机档收窄 .stat-card padding（删掉 ⇒ 390 档四张 80px 卡里标签折 2 行）`,
  )
}

// 表格：宽表必须能横滚（话术库这条是实测承重的 —— 删掉「问题」列被压成 0px）
const faqRaw = read(path.join(KB_DIR, KB_FILES.faq)) || ''
const faqTpl = stripHtml(faqRaw)
check(
  /:scroll="\{\s*x:\s*\d+/.test(faqTpl),
  'G7',
  '★ 话术库表格带 scroll.x（删掉 ⇒ 390 档「问题」列被压成 0px，整列消失）',
)

/* --------------------------------------------------------------- 汇总 */
console.log(`\n=== ${pass} PASS / ${fail} FAIL ===`)
if (fail) {
  console.log('RESULT: FAIL')
  process.exit(1)
}
console.log('RESULT: PASS（断点真源唯一 · 窄屏浮层形态齐全 · 顶栏降级就位 · 资料库窄屏形态齐全）')

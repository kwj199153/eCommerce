#!/usr/bin/env node
/**
 * 「悬停翻译」门禁（第 370 轮 P1）
 *
 * ════════════════════════════════════════════════════════════════════════
 * 这条门禁守的是三条**加回去不会有任何报错**的产品属性
 * ════════════════════════════════════════════════════════════════════════
 * 悬停翻译本身是个新功能，但它有三处「改一个字符就静默变味」的地方：
 *
 *   ① **开关缺省必须是关**。产品口径是「悬停是额外打扰，默认不给」，
 *      所以判据是 `=== '1'`。而隔壁 `autoEnabled` 的判据是 `!== '0'`（缺省开）——
 *      两者**挨着写**，复制粘贴一下方向就反了：全站用户默认被悬停打扰，
 *      代码照样编译、单测照样绿（如果没人专门钉这一条）。
 *
 *   ② **三条结构性排除必须真的参与判定**（浮层内 / 可编辑区内 / 已有选区）。
 *      把它们写成 `insideLayer: false` 这种**硬编码常量**，AST 里那个属性名还在、
 *      `decideHover` 也还在被调用 —— 只是永不生效。这是「可达性形态」的变体：
 *      判「有没有传这个键」会失明，必须判「值是不是字面量 false」。
 *
 *   ③ **定时器必须被取消**。`onMouseOver` 每次先清上一个、`mouseout` 时清、
 *      关掉开关时也要清。少任何一处，症状是「鼠标早移开了、浮层 350ms 后自己冒出来」
 *      或「关掉开关又弹一个」—— 都不会报错。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 判据口径
 * ════════════════════════════════════════════════════════════════════════
 *   · **全部走 AST**。本仓的注释必然逐字引用 `hoverEnabled` / `'1'` / `clearTimeout`
 *     这些名字（文件头就解释了一大段），字符串扫描会把注释算成代码。
 *     TS 的 AST 里没有注释节点。
 *   · **判定抽成纯函数** ⇒ 同一条判据能喂**坏样本**自证不是恒绿（见 R 组）。
 *   · **必须自证没空跑**：抽不到符号 / 调用计数为 0 时直接失败。
 *   · **不钉「恰好 N 次」**：数量是钉住旧形态的负资产；判据是形态。
 *
 * ## 读集注入开口（零副作用自证）
 *
 *   HOVER_UTIL_SRC=<副本>   WATCHER_SRC=<副本>
 *   指向**空文件 / 坏样本**时，本门禁**必须变红**。仍绿即说明判据没真读它。
 *   ★ 边界：空源注入只能**证伪**（证明判据读了内容），不证明它读对了字段。
 *
 * 怎么跑：node scripts/check-hover-translate.cjs
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, rel) =>
  process.env[env] ? path.resolve(process.env[env]) : path.join(ROOT, ...rel)

const HOVER_UTIL = pick('HOVER_UTIL_SRC', ['src', 'utils', 'hoverTranslate.ts'])
const WATCHER = pick('WATCHER_SRC', ['src', 'composables', 'useSelectionTranslate.ts'])

const ts = require(path.join(ROOT, 'node_modules', 'typescript'))

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

function parse(file) {
  const src = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
  return { src, sf: ts.createSourceFile(file, src, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }
}

function walk(node, visit) {
  visit(node)
  ts.forEachChild(node, (c) => walk(c, visit))
}

/** 函数声明 + 箭头函数（赋给变量 或 **赋值给已声明的变量**） */
function collectFns(sf) {
  const out = {}
  walk(sf, (n) => {
    if (ts.isFunctionDeclaration(n) && n.name) out[n.name.getText(sf)] = n
    else if (
      ts.isVariableDeclaration(n) &&
      ts.isIdentifier(n.name) &&
      n.initializer &&
      (ts.isArrowFunction(n.initializer) || ts.isFunctionExpression(n.initializer))
    ) {
      out[n.name.getText(sf)] = n.initializer
    } else if (
      // ★ `let teardown = null` 之后再 `teardown = () => {...}` 的**赋值**形态。
      //   漏掉这一支的真实代价：H4e 会假红（判据说「teardown 里没清定时器」，
      //   而它根本没拿到 teardown 的函数体）。本仓 watcher 的 teardown 正是这么写的。
      ts.isBinaryExpression(n) &&
      n.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isIdentifier(n.left) &&
      (ts.isArrowFunction(n.right) || ts.isFunctionExpression(n.right))
    ) {
      out[n.left.getText(sf)] = n.right
    }
  })
  return out
}

function propsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isPropertyAccessExpression(n)) out.push(n.getText(sf))
  })
  return out
}

function callsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isCallExpression(n)) out.push({ node: n, callee: n.expression.getText(sf) })
  })
  return out
}

// =====================================================================
// 判据（全部导出给坏样本复用 —— 纯函数，无副作用）
// =====================================================================

/** H1a：watcher 从唯一真源 import 悬停判定（含 decideHover 与两个常量至少其一） */
function watcherImportsHoverUtil(sf) {
  let ok = false
  walk(sf, (n) => {
    if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier)) {
      const mod = n.moduleSpecifier.text
      const named = n.importClause && n.importClause.namedBindings
      if (/utils\/hoverTranslate$/.test(mod) && named && ts.isNamedImports(named)) {
        for (const e of named.elements) {
          if (['decideHover', 'HOVER_DELAY_MS', 'MAX_HOVER_CHARS'].includes(e.name.text)) ok = true
        }
      }
    }
  })
  return ok
}

/**
 * H1b：watcher **不得**自己实现悬停的语言判据。
 *
 * 只查「拉丁字母」那一条正则（`[A-Za-z]` / `[a-zA-Z]`）——
 * 本文件里还有一条**划词用的** `MEANINGFUL` 正则（含汉字与数字范围），
 * 那是既有且正确的，不能误伤。⇒ 判据必须精确到「拉丁字母」这一形态。
 */
function hasLatinRegexInWatcher(sf) {
  let found = null
  walk(sf, (n) => {
    if (ts.isRegularExpressionLiteral(n)) {
      const t = n.getText(sf)
      if (/\[A-Za-z\]|\[a-zA-Z\]/.test(t)) found = t
    }
  })
  return found
}

/** H1c：onMouseOver 里真的调了 decideHover，且它的结果**参与 return**（不是调了不用） */
function callsDecideHover(sf, fn) {
  return callsIn(sf, fn).some((c) => c.callee === 'decideHover')
}

/**
 * ★ 可达性形态：`const d = decideHover(...)` 之后必须有一条
 *   `if (!d.ok ...) return` —— 只看「调没调过」对「调了但从不 use」完全失明。
 */
function decisionGuardsReturn(sf, fn) {
  let ok = false
  walk(fn, (n) => {
    if (
      ts.isIfStatement(n) &&
      /\.ok\b/.test(n.expression.getText(sf)) &&
      ts.isReturnStatement(n.thenStatement)
    ) {
      ok = true
    }
  })
  return ok
}

/** H2a/H2b：某个函数体里是否出现 `<expr> <op> '<lit>'` 的比较 */
function comparesToLiteral(sf, fn, op, lit) {
  let found = false
  walk(fn, (n) => {
    if (ts.isBinaryExpression(n)) {
      const k = n.operatorToken.kind
      const wantEq = op === '===' && k === ts.SyntaxKind.EqualsEqualsEqualsToken
      const wantNe = op === '!==' && k === ts.SyntaxKind.ExclamationEqualsEqualsToken
      if (!wantEq && !wantNe) return
      const r = n.right
      const isLit =
        (ts.isStringLiteral(r) || ts.isNoSubstitutionTemplateLiteral(r)) && r.text === lit
      if (isLit) found = true
    }
  })
  return found
}

/** H2c：onMouseOver 里有 `if (!hoverEnabled...) return` 形态的早退守卫 */
function hasHoverGuard(sf, fn) {
  let ok = false
  walk(fn, (n) => {
    if (!ts.isIfStatement(n)) return
    const cond = n.expression.getText(sf).trim()
    // ★ 必须是**否定**形态：写成 `if (hoverEnabled.value) return` 语义正好反了
    if (/^!/.test(cond) && /hoverEnabled/.test(cond) && ts.isReturnStatement(n.thenStatement)) {
      ok = true
    }
  })
  return ok
}

/** H3：找出 onMouseOver 里那个「信号对象」字面量（含 insideLayer 与 hasSelection 两个键） */
function signalsLiteral(sf, fn) {
  let found = null
  walk(fn, (n) => {
    if (ts.isObjectLiteralExpression(n)) {
      const keys = n.properties.map((p) => (p.name && p.name.getText(sf)) || '')
      if (keys.includes('insideLayer') && keys.includes('hasSelection')) found = n
    }
  })
  return found
}

/**
 * H3 ★★ 逐键判「值是不是**硬编码的 false**」。
 *
 * 这是本门禁最容易被写成假绿的地方：`insideLayer: false` 让属性名照样出现、
 * `decideHover` 照样被调用，只是那一条排除**永不生效**。
 * 找不到该键也判不合规（必须显式参与）。
 */
function signalIsLive(sf, lit, key) {
  if (!lit) return false
  let seen = false
  for (const p of lit.properties) {
    if (p.name && p.name.getText(sf) === key) {
      seen = true
      if (p.initializer && p.initializer.kind === ts.SyntaxKind.FalseKeyword) return false
    }
  }
  return seen
}

/** H4a：onMouseOver 里「先清定时器、再起定时器」（顺序判据 —— 反了会留下多个定时器） */
function clearsBeforeSetTimeout(sf, fn) {
  let clearAt = -1
  let setAt = -1
  walk(fn, (n) => {
    if (!ts.isCallExpression(n)) return
    const name = ts.isIdentifier(n.expression) ? n.expression.text : ''
    if (name === 'clearHoverTimer' && clearAt < 0) clearAt = n.getStart()
    if (name === 'setTimeout' && setAt < 0) setAt = n.getStart()
  })
  return clearAt >= 0 && setAt >= 0 && clearAt < setAt
}

/** H4b：某个函数里是否调了 clearTimeout */
function callsClearTimeout(sf, fn) {
  return callsIn(sf, fn).some((c) => c.callee === 'clearTimeout')
}

/** H4c：某个函数里是否调了 clearHoverTimer */
function callsClearHoverTimer(sf, fn) {
  return callsIn(sf, fn).some((c) => c.callee.includes('clearHoverTimer'))
}

/** H5：addEventListener/removeEventListener 是否成对（按事件名判） */
function listenerPair(sf, node, type) {
  const out = { add: 0, rem: 0 }
  walk(node, (n) => {
    if (!ts.isCallExpression(n) || !ts.isPropertyAccessExpression(n.expression)) return
    const m = n.expression.name.getText(sf)
    const a0 = n.arguments[0]
    const isType =
      a0 && (ts.isStringLiteral(a0) || ts.isNoSubstitutionTemplateLiteral(a0)) && a0.text === type
    if (!isType) return
    if (m === 'addEventListener') out.add++
    if (m === 'removeEventListener') out.rem++
  })
  return out
}

/** H6：onMouseOver 的定时器回调里做了「同文本不重弹」的比对 */
function hasSameTextDedup(sf, fn) {
  const ps = propsIn(sf, fn)
  return ps.includes('state.original') && ps.includes('state.visible')
}

/** H7：叶子模块的纯度 —— 零 import、且不引用 document/window */
function leafIsPure(sf) {
  let imports = 0
  let domRefs = 0
  walk(sf, (n) => {
    if (ts.isImportDeclaration(n) || ts.isImportEqualsDeclaration(n)) imports++
    if (ts.isIdentifier(n) && (n.text === 'document' || n.text === 'window')) domRefs++
  })
  return { imports, domRefs }
}

// =====================================================================
// 读取与断言
// =====================================================================
const util = parse(HOVER_UTIL)
const watcher = parse(WATCHER)
const wFns = collectFns(watcher.sf)
const uFns = collectFns(util.sf)

const onMouseOver = wFns.onMouseOver
const onMouseOut = wFns.onMouseOut
const clearHoverTimerFn = wFns.clearHoverTimer
const readHoverEnabledFn = wFns.readHoverEnabled
const setHoverEnabledFn = wFns.setHoverEnabled
const teardownFn = wFns.teardown

// ---------------- H0 自检：判据读到的东西必须存在（防空跑） ----------------
check(!!uFns.decideHover, 'H0a 悬停判定唯一真源里抽到了 decideHover', HOVER_UTIL)
check(
  !!uFns.decideHover && !!util.sf && /HOVER_DELAY_MS/.test(util.src) && /MAX_HOVER_CHARS/.test(util.src),
  'H0b 叶子导出两个常量（HOVER_DELAY_MS / MAX_HOVER_CHARS）',
)
check(!!onMouseOver && !!onMouseOut, 'H0c watcher 里抽到了 onMouseOver 与 onMouseOut', WATCHER)
check(!!clearHoverTimerFn, 'H0d watcher 里有 clearHoverTimer（定时器取消的唯一入口）')
check(!!readHoverEnabledFn, 'H0e watcher 里有 readHoverEnabled（缺省判据的唯一入口）')

// ---------------- H1 唯一实现 ----------------
check(watcherImportsHoverUtil(watcher.sf),
  'H1a watcher 从 @/utils/hoverTranslate 取判定（不得自写第二份）')
check(!hasLatinRegexInWatcher(watcher.sf),
  'H1b watcher 里不得出现「拉丁字母」正则 —— 那是悬停的语言判据，必须住在叶子里',
  String(hasLatinRegexInWatcher(watcher.sf) || ''))
check(!!onMouseOver && callsDecideHover(watcher.sf, onMouseOver),
  'H1c onMouseOver 真的调了 decideHover')
check(!!onMouseOver && decisionGuardsReturn(watcher.sf, onMouseOver),
  'H1d ★ decideHover 的结果**参与 return**（只判「调没调过」对「调了不用」失明）')

// ---------------- H2 开关缺省为关 ----------------
check(!!readHoverEnabledFn && comparesToLiteral(watcher.sf, readHoverEnabledFn, '===', '1'),
  'H2a ★ 缺省判据是 `=== "1"`（只有显式开过才为真）')
check(!!readHoverEnabledFn && !comparesToLiteral(watcher.sf, readHoverEnabledFn, '!==', '0'),
  'H2b ★ 不得写成 `!== "0"` —— 那是 autoEnabled 的口径，方向与本开关相反')
check(!!onMouseOver && hasHoverGuard(watcher.sf, onMouseOver),
  'H2c onMouseOver 有 `if (!hoverEnabled...) return` 早退守卫（且必须是否定形态）')
check(!!setHoverEnabledFn && callsClearHoverTimer(watcher.sf, setHoverEnabledFn),
  'H2d 关掉开关时取消已排队的悬停（否则「刚关掉又弹一个」）')

// ---------------- H3 三条结构性排除必须真的参与 ----------------
const sigLit = onMouseOver ? signalsLiteral(watcher.sf, onMouseOver) : null
check(!!sigLit, 'H3a onMouseOver 构造了信号对象（含 insideLayer / hasSelection）')
check(signalIsLive(watcher.sf, sigLit, 'insideLayer'),
  'H3b ★ insideLayer 的值不是字面量 false（硬编码 = 那条排除永不生效，AST 却看不出来）')
check(signalIsLive(watcher.sf, sigLit, 'insideEditable'),
  'H3c ★ insideEditable 的值不是字面量 false（同上）')
check(signalIsLive(watcher.sf, sigLit, 'hasSelection'),
  'H3d ★ hasSelection 的值不是字面量 false（同上）')
check(signalIsLive(watcher.sf, sigLit, 'isTextBlock') && signalIsLive(watcher.sf, sigLit, 'text'),
  'H3e 信号对象还带 text / isTextBlock（缺了它们判定只剩三条排除）')

// ---------------- H4 定时器取消 ----------------
check(!!onMouseOver && clearsBeforeSetTimeout(watcher.sf, onMouseOver),
  'H4a ★ onMouseOver **先清后起**（顺序判据：反了会留下多个定时器一起到点）')
check(!!onMouseOut && callsClearHoverTimer(watcher.sf, onMouseOut),
  'H4b onMouseOut 取消待触发的悬停（鼠标移开就不该再弹）')
check(!!onMouseOut && propsIn(watcher.sf, onMouseOut).includes('e.relatedTarget'),
  'H4c onMouseOut 自检 relatedTarget —— 否则「在本块的后代间移动」会不断重置计时，永远等不满')
check(!!clearHoverTimerFn && callsClearTimeout(watcher.sf, clearHoverTimerFn),
  'H4d clearHoverTimer 里真的调了 clearTimeout（否则只是把句柄丢了，任务照跑）')
check(!!teardownFn && callsClearHoverTimer(watcher.sf, teardownFn),
  'H4e teardown 里也清定时器（卸载后不该还有待触发的悬停）')

// ---------------- H5 注册 / 卸载成对 ----------------
for (const t of ['mouseover', 'mouseout']) {
  const p = listenerPair(watcher.sf, watcher.sf, t)
  check(p.add > 0 && p.rem > 0 && p.add === p.rem,
    `H5 ${t} 的 add/remove 成对（add=${p.add} remove=${p.rem}）—— 只挂不摘会跨视图泄漏`)
}

// ---------------- H6 同文本不重弹 ----------------
check(!!onMouseOver && hasSameTextDedup(watcher.sf, onMouseOver),
  'H6 定时器回调里比对 state.visible && state.original（这就是「同文本去重」，不需要 LRU）')

// ---------------- H7 叶子纯度 ----------------
const pure = leafIsPure(util.sf)
check(pure.imports === 0, `H7a 悬停判定是**纯叶子**：零 import（实测 ${pure.imports}）`)
check(pure.domRefs === 0, `H7b 叶子不引用 document/window（实测 ${pure.domRefs} 处）—— 否则无法零成本单测`)

// ---------------- H8 登记 ----------------
let pkg = null
try {
  pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'))
} catch {
  pkg = null
}
const scripts = (pkg && pkg.scripts) || {}
check(/check-hover-translate\.cjs/.test(String(scripts['check:hover-translate'] || '')),
  'H8a package.json 登记了 check:hover-translate')
check(/check-hover-translate\.cjs/.test(String(scripts.build || '')),
  'H8b 本门禁已接入 npm run build 链')

// =====================================================================
// 反向注入自检：证明上面每条判据**不是恒绿**
// =====================================================================
const mk = (name, code) => ({
  sf: ts.createSourceFile(name, code, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS),
})

/** 坏样本①：自己写拉丁正则判语言、不 import 叶子、无守卫、硬编码三条排除 */
const BAD_WATCHER = `
const LATIN = /[A-Za-z]/
const onMouseOver = (e) => {
  const t = (e.target.textContent || '').trim()
  if (!LATIN.test(t)) return
  setTimeout(() => { translate(t, null) }, 350)
}
const onMouseOut = () => {}
const readHoverEnabled = () => localStorage.getItem('k') !== '0'
const setHoverEnabled = (v) => { hoverEnabled.value = v }
`
const badW = mk('bad-hover-watcher.ts', BAD_WATCHER)
const badWFns = collectFns(badW.sf)

/** 坏样本②：三条排除写成字面量 false（AST 里属性名都在，只是永不生效） */
const HARDCODED_SIGNALS = `
const onMouseOver = (e) => {
  const decision = decideHover({
    text: 'x', isTextBlock: true,
    insideLayer: false, insideEditable: false, hasSelection: false,
  })
  if (!decision.ok) return
}
`
const hardW = mk('hardcoded-signals.ts', HARDCODED_SIGNALS)
const hardFns = collectFns(hardW.sf)

/** 坏样本③：定时器只起不清 */
const NO_CLEAR = `
const onMouseOver = (e) => {
  setTimeout(() => { translate('x', null) }, 350)
}
const clearHoverTimer = () => { hoverTimer = null }
`
const noClearW = mk('no-clear.ts', NO_CLEAR)
const noClearFns = collectFns(noClearW.sf)

/** 坏样本④：只 add 不 remove */
const NO_REMOVE = `
document.addEventListener('mouseover', onMouseOver, true)
document.addEventListener('mouseout', onMouseOut, true)
`
const noRemoveW = mk('no-remove.ts', NO_REMOVE)

/** 正向对照：形态正确的一份必须被判成合规（判据太紧会误伤真实现） */
const GOOD_WATCHER = `
import { HOVER_DELAY_MS, MAX_HOVER_CHARS, decideHover } from '@/utils/hoverTranslate'
const onMouseOver = (e) => {
  clearHoverTimer()
  if (!hoverEnabled.value) return
  const block = nearestTextBlock(e.target)
  const sel = window.getSelection()
  const signals = {
    text: block ? block.text : '',
    isTextBlock: !!block,
    insideLayer: inLayer(e.target),
    insideEditable: isEditableTarget(e.target),
    hasSelection: !!(sel && sel.toString().trim()),
  }
  const decision = decideHover(signals)
  if (!decision.ok || !block) return
  hoverTimer = setTimeout(() => {
    if (state.visible && state.original === decision.text) return
    translate(decision.text, null)
  }, HOVER_DELAY_MS)
}
const onMouseOut = (e) => {
  const from = e.target
  const to = e.relatedTarget
  if (to && from && from.contains(to)) return
  clearHoverTimer()
}
const clearHoverTimer = () => { if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null } }
const readHoverEnabled = () => localStorage.getItem('k') === '1'
const setHoverEnabled = (v) => { if (!v) clearHoverTimer() }
const teardown = () => { clearHoverTimer() }
document.addEventListener('mouseover', onMouseOver, true)
document.addEventListener('mouseout', onMouseOut, true)
document.removeEventListener('mouseover', onMouseOver, true)
document.removeEventListener('mouseout', onMouseOut, true)
`
const goodW = mk('good-hover-watcher.ts', GOOD_WATCHER)
const goodFns = collectFns(goodW.sf)

// R1：唯一实现
check(!watcherImportsHoverUtil(badW.sf),
  'R1 坏样本（不 import 叶子、自己判语言）被判为不合规 —— 否则 H1a 恒绿')
check(!!hasLatinRegexInWatcher(badW.sf),
  'R1b 坏样本里确实有拉丁正则（用于构造 R1 的陷阱：只判 import 会漏掉「既 import 又自写」）')
check(!hasLatinRegexInWatcher(watcher.sf) && hasLatinRegexInWatcher(badW.sf),
  'R1c 判据对真实现放行、对坏样本拦下（双向都真的在判）')

// R2：缺省方向
check(!comparesToLiteral(badW.sf, badWFns.readHoverEnabled, '===', '1'),
  'R2 坏样本（缺省判据写成 !== "0"）被判为不合规 —— 否则 H2a 恒绿')
check(comparesToLiteral(badW.sf, badWFns.readHoverEnabled, '!==', '0'),
  'R2b 坏样本确实写的是 !== "0"（陷阱成立，不是判据恒真）')

// R3：三条排除的「硬编码 false」形态
check(!signalIsLive(hardW.sf, signalsLiteral(hardW.sf, hardFns.onMouseOver), 'insideLayer'),
  'R3 ★ 坏样本（insideLayer 硬编码 false）被判为不合规 —— 这条是「属性名在、但永不生效」的失明形态')
check(
  !signalIsLive(hardW.sf, signalsLiteral(hardW.sf, hardFns.onMouseOver), 'hasSelection') &&
    !signalIsLive(hardW.sf, signalsLiteral(hardW.sf, hardFns.onMouseOver), 'insideEditable'),
  'R3b 坏样本的三条排除都被判为不合规（不是只抓了其中一条）',
)

// R4：可达性 —— 调了不用
check(!!hardFns.onMouseOver && callsDecideHover(hardW.sf, hardFns.onMouseOver),
  'R4 前提：坏样本确实调了 decideHover（否则 R4b 的对照不成立）')
check(
  !decisionGuardsReturn(hardW.sf, hardFns.onMouseOver) ||
    !signalIsLive(hardW.sf, signalsLiteral(hardW.sf, hardFns.onMouseOver), 'insideLayer'),
  'R4b ★ 「调了 decideHover 但把三条排除写死」必须被拦下 —— 只看调用会失明',
)

// R5：定时器
check(!clearsBeforeSetTimeout(noClearW.sf, noClearFns.onMouseOver),
  'R5 坏样本（只起 setTimeout、不清上一个）被判为不合规 —— 否则 H4a 恒绿')
check(!callsClearTimeout(noClearW.sf, noClearFns.clearHoverTimer),
  'R5b 坏样本（clearHoverTimer 只丢句柄、不调 clearTimeout）被判为不合规 —— 否则 H4d 恒绿')

// R6：成对
const noRem = listenerPair(noRemoveW.sf, noRemoveW.sf, 'mouseover')
check(noRem.add > 0 && noRem.rem === 0,
  'R6 坏样本（只 add 不 remove）被数出 add>0/remove=0 —— 否则 H5 恒绿')

// R7：正向对照
check(watcherImportsHoverUtil(goodW.sf) && !hasLatinRegexInWatcher(goodW.sf),
  'R7 正向对照：合规形态在「唯一实现」这组判据上全过（判据太紧会误伤真实现）')
check(
  comparesToLiteral(goodW.sf, goodFns.readHoverEnabled, '===', '1') &&
    !comparesToLiteral(goodW.sf, goodFns.readHoverEnabled, '!==', '0'),
  'R7b 正向对照：缺省判据 `=== "1"` 被放行',
)
check(
  signalIsLive(goodW.sf, signalsLiteral(goodW.sf, goodFns.onMouseOver), 'insideLayer') &&
    signalIsLive(goodW.sf, signalsLiteral(goodW.sf, goodFns.onMouseOver), 'insideEditable') &&
    signalIsLive(goodW.sf, signalsLiteral(goodW.sf, goodFns.onMouseOver), 'hasSelection'),
  'R7c 正向对照：三条排除「有真实取值」的被放行',
)
check(clearsBeforeSetTimeout(goodW.sf, goodFns.onMouseOver),
  'R7d 正向对照：先清后起 被放行')
check(
  callsClearHoverTimer(goodW.sf, goodFns.onMouseOut) &&
    propsIn(goodW.sf, goodFns.onMouseOut).includes('e.relatedTarget'),
  'R7e 正向对照：onMouseOut 取消 + 自检 relatedTarget 被放行',
)
const goodPair = listenerPair(goodW.sf, goodW.sf, 'mouseover')
check(goodPair.add === 1 && goodPair.rem === 1, 'R7f 正向对照：成对的 add/remove 被放行')

// R8：空源注入 —— 判据必须真的读了文件内容
const emptyW = mk('empty.ts', '')
check(!watcherImportsHoverUtil(emptyW.sf) && !collectFns(emptyW.sf).onMouseOver,
  'R8 空源注入 ⇒ 抽不到符号（证明判据确实读了内容，而不是恒取真值）')
const emptyU = mk('empty-util.ts', '')
check(!collectFns(emptyU.sf).decideHover,
  'R8b 空源注入 ⇒ 叶子抽不到 decideHover（同上）')

// R9：叶子纯度判据有牙齿
const impure = mk('impure.ts', "import { ref } from 'vue'\nconst x = document.body\n")
const imp = leafIsPure(impure.sf)
check(imp.imports > 0 && imp.domRefs > 0,
  'R9 坏样本（叶子引了 vue + DOM）被数出 imports>0 / domRefs>0 —— 否则 H7 恒绿')

// =====================================================================
// 汇总
// =====================================================================
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
  '悬停翻译门禁通过（判定唯一真源 · 开关缺省关 · 三条结构性排除真的生效 · 定时器先清后起且成对摘除 · 叶子零 import 零 DOM ✓）',
)

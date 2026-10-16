#!/usr/bin/env node
/**
 * 「表单控件内划词」门禁（第 366 轮 · 阶段 B）
 *
 * ════════════════════════════════════════════════════════════════════════
 * 这条门禁守的是一次**行为放开**，而不是一次新增功能
 * ════════════════════════════════════════════════════════════════════════
 * 老板原话：「是否有办法划线选择输入框的内容然后弹出译文？」→ 范围＝全站所有输入框。
 *
 * 改动前 `useSelectionTranslate.ts` 的 `onMouseUp` 里有一行
 *
 *     if (isTextField(e.target)) return   // 输入框里选字是要编辑，不是要阅读
 *
 * 它把 input/textarea 整条短路掉。**这一行不会被任何类型检查或测试拦住** ——
 * 删掉它只是"少了一次 early return"，代码仍然编译、单测仍然可能全绿，
 * 唯一变化是用户在输入框里划词又能/不能拿到译文。属于典型的**静默行为回归**。
 *
 * 而且**只删掉那一行是不够的**（这是本门禁存在的第二个理由）：
 * 控件内的选区 `getSelection().getRangeAt(0).getBoundingClientRect()` 恒为 0×0
 * （真机实测：containerNode 是 `BODY#1`），紧接着那行
 *
 *     if (!r || (!r.width && !r.height)) return
 *
 * 会把它变成**静默 return**。⇒ 必须同时存在一条**另一套取值通道**，
 * 于是本门禁要钉的其实是「那条通道真的被接上了」。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 判据口径
 * ════════════════════════════════════════════════════════════════════════
 *   · **全部走 AST**。这个仓库里"为什么这么做"的解释性注释必然逐字引用
 *     `isTextField` / `selectionStart` / `password` 这些名字 —— 字符串扫描会把
 *     注释算成代码，得到「代码是对的、门禁是红的」。TS 的 AST 里没有注释节点。
 *     （唯一例外：**函数体文本**在最后两条断言里被用于"是否还认得某条语句"，
 *      那里用的是 AST 节点而非常量串匹配。）
 *   · **判定函数抽成纯函数**，这样同一条判据能喂**坏样本**自证不是恒绿
 *     （见文件末尾「反向注入自检」）。
 *   · **必须自证没空跑**：解析出的导出符号、AST 节点计数为 0 时直接失败。
 *   · **不钉「恰好 N 次」**：数量是钉住旧形态的负资产；判据是形态。
 *
 * ## 读集注入开口（零副作用自证）
 *
 *   FIELD_UTIL_SRC=<副本>   WATCHER_SRC=<副本>
 *   指向**空文件 / 坏样本**时，本门禁**必须变红**。仍绿即说明判据没真读它。
 *   ★ 边界：空源注入只能**证伪**（证明判据读了内容），不证明它读对了字段。
 *
 * 怎么跑：node scripts/check-selection-field-rule.cjs
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const pick = (env, rel) =>
  process.env[env] ? path.resolve(process.env[env]) : path.join(ROOT, ...rel)

const FIELD_UTIL = pick('FIELD_UTIL_SRC', ['src', 'utils', 'textSelection.ts'])
const WATCHER = pick('WATCHER_SRC', ['src', 'composables', 'useSelectionTranslate.ts'])

const ts = require(path.join(ROOT, 'node_modules', 'typescript'))

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

function parse(file) {
  const src = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
  return { src, sf: ts.createSourceFile(file, src, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }
}

function walk(node, visit) {
  visit(node)
  ts.forEachChild(node, (c) => walk(c, visit))
}

/** 函数声明 + 赋给变量的箭头函数/函数表达式（与 check-auth-vault.cjs 同口径） */
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
    }
  })
  return out
}

function callsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isCallExpression(n)) {
      out.push({ callee: n.expression.getText(sf), args: n.arguments.map((a) => a.getText(sf)) })
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

function identifiersIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isIdentifier(n)) out.push(n.text)
  })
  return out
}

/** 具名导出（函数 / 接口 / 类型 / 变量 / export {} 列表） */
function exportedNames(sf) {
  const out = new Set()
  const isExported = (n) =>
    !!n.modifiers && n.modifiers.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
  walk(sf, (n) => {
    if (isExported(n) && (n.name || n.declarationList)) {
      if (n.name && ts.isIdentifier(n.name)) out.add(n.name.text)
      if (n.declarationList) {
        for (const d of n.declarationList.declarations) {
          if (ts.isIdentifier(d.name)) out.add(d.name.text)
        }
      }
    }
    if (ts.isExportDeclaration(n) && n.exportClause && ts.isNamedExports(n.exportClause)) {
      for (const e of n.exportClause.elements) out.add(e.name.text)
    }
  })
  return out
}

function importSpecs(sf) {
  const out = []
  ts.forEachChild(sf, (n) => {
    if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier)) {
      const names = []
      const nb = n.importClause && n.importClause.namedBindings
      if (nb && ts.isNamedImports(nb)) for (const e of nb.elements) names.push(e.name.text)
      out.push({ src: n.moduleSpecifier.text, names })
    }
  })
  return out
}

function interfaceMembers(sf, name) {
  let found = null
  walk(sf, (n) => {
    if (!found && ts.isInterfaceDeclaration(n) && n.name.getText(sf) === name) found = n
  })
  if (!found) return null
  return found.members.map((m) => (m.name ? m.name.getText(sf) : '')).filter(Boolean).sort()
}

// =====================================================================
// 第一部分 · 取值通道的形态判据（纯函数：可被坏样本复用）
// =====================================================================

/** 读 selectionStart / selectionEnd（两个都要） */
function readsSelectionOffsets(sf, fn) {
  if (!fn) return false
  const ps = propsIn(sf, fn)
  return ps.some((p) => p.endsWith('.selectionStart')) && ps.some((p) => p.endsWith('.selectionEnd'))
}

/**
 * 找模块级「密码类型」常量：`const X = 'password'`。
 *
 * ★ 为什么判据要分两半（常量 + 比对），而不是"函数体里出现 'password' 字面量"：
 *   第一版就是这么写的，结果**真源码直接判红** —— 因为实现把字面量放在模块级
 *   常量 `NEVER_READ_TYPE = 'password'` 上（那是更好的写法：具名、只有一处）。
 *   ⇒ 判据形状写错会把**正确的实现**判成错的（本仓记录过的「期望值过期
 *   伪装成真回归」）。于是改成：常量必须存在，**且**函数里必须拿 `el.type` 与它比对。
 *   两半缺一都拦不住 —— 只留常量 = 常量摆着没人用；只留比对 = 比对的可能是别的值。
 */
function passwordConstName(sf) {
  const names = []
  ts.forEachChild(sf, (n) => {
    if (!ts.isVariableStatement(n)) return
    for (const d of n.declarationList.declarations) {
      if (
        ts.isIdentifier(d.name) &&
        d.initializer &&
        ts.isStringLiteral(d.initializer) &&
        d.initializer.text === 'password'
      ) {
        names.push(d.name.text)
      }
    }
  })
  return names
}

const CMP_EQ = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
])

/** 函数里必须拿「某元素的 .type」与 password 常量比过 */
function comparesElTypeToPasswordConst(sf, fn, constNames) {
  if (!fn || !constNames || constNames.length === 0) return false
  let ok = false
  walk(fn, (node) => {
    if (!ts.isBinaryExpression(node) || !CMP_EQ.has(node.operatorToken.kind)) return
    const sides = [node.left, node.right]
    const hasConst = sides.some((s) => ts.isIdentifier(s) && constNames.includes(s.text))
    const hasTypeProp = sides.some(
      (s) => ts.isPropertyAccessExpression(s) && s.name.getText(sf) === 'type'
    )
    if (hasConst && hasTypeProp) ok = true
  })
  return ok
}

/**
 * 「该类型不支持选区」必须用**运行期判据**（`typeof selectionStart !== 'number'`），
 * 而不是抄一份 input type 名单（名单会漏、会随浏览器版本过期）。
 * ★ 判 AST：`typeof X ===|!== 'number'` 的 BinaryExpression 至少 2 处（start / end）。
 */
function hasTypeofNumberGuard(sf, fn) {
  if (!fn) return false
  let n = 0
  walk(fn, (node) => {
    if (!ts.isBinaryExpression(node)) return
    if (!CMP_EQ.has(node.operatorToken.kind)) return
    if (!ts.isTypeOfExpression(node.left)) return
    if (ts.isStringLiteral(node.right) && node.right.text === 'number') n++
  })
  return n >= 2
}

/** 镜像节点必须在 `finally` 里被摘掉（每次划词都往 body 挂一个 div = DOM 泄漏） */
function removesMirrorInFinally(sf, fn) {
  if (!fn) return false
  let ok = false
  walk(fn, (n) => {
    if (!ts.isTryStatement(n) || !n.finallyBlock) return
    const calls = callsIn(sf, n.finallyBlock)
    if (calls.some((c) => /removeChild$/.test(c.callee))) ok = true
  })
  return ok
}

/** 尺寸口径：镜像宽度必须按 clientWidth 推（排除边框与滚动条），不是 offsetWidth 硬搬 */
function usesClientWidth(sf, fn) {
  if (!fn) return false
  return propsIn(sf, fn).some((p) => p.endsWith('.clientWidth'))
}

// =====================================================================
// 第二部分 · 接线判据（纯函数）
// =====================================================================

const FIELD_NEEDED = ['isFieldElement', 'readFieldSelection', 'rectOfFieldSelection']

/** useSelectionTranslate 必须从唯一真源取这三个符号 */
function watcherImportsFieldUtil(sf) {
  const decl = importSpecs(sf).find((i) => i.src === '@/utils/textSelection')
  if (!decl) return false
  return FIELD_NEEDED.every((n) => decl.names.includes(n))
}

/**
 * 定位 `onMouseUp` 里的**表单控件分支**（`if (isFieldElement(...)) { … }`）。
 *
 * ★ 判据必须锚到**这个 if 块内部**，而不是"onMouseUp 里某处调了这两个函数"。
 *   第 366 轮反向注入实测踩到：把分支体开头插一条 `return`（模拟"改回旧行为"），
 *   两个调用**仍然在 AST 里**（只是不可达）⇒ 「是否调过」型判据**照绿**。
 *   这是本仓记录过的典型盲区：「源码字符串包含」与「AST 里有这个节点」
 *   都拦不住"被提前掐掉"。⇒ 必须判**可达性形态**：then 块非空、且第一条语句
 *   不是 return / throw。
 */
function fieldBranch(sf) {
  const fn = collectFns(sf).onMouseUp
  if (!fn) return null
  let hit = null
  walk(fn, (n) => {
    if (hit || !ts.isIfStatement(n)) return
    const c = n.expression
    if (ts.isCallExpression(c) && c.expression.getText(sf) === 'isFieldElement') hit = n
  })
  return hit
}

/** 控件分支存在、非空、且第一条语句不是 return/throw（= 没被提前掐掉） */
function fieldBranchUsable(sf) {
  const node = fieldBranch(sf)
  if (!node) return false
  const then = node.thenStatement
  if (!ts.isBlock(then) || then.statements.length === 0) return false
  const first = then.statements[0]
  if (ts.isReturnStatement(first) || ts.isThrowStatement(first)) return false
  return true
}

/** 两个函数都必须被调在**控件分支内部**（在块的旁边调 = 分支白写） */
function fieldChannelInsideBranch(sf) {
  const node = fieldBranch(sf)
  if (!node) return false
  const callees = callsIn(sf, node.thenStatement).map((c) => c.callee)
  return callees.includes('readFieldSelection') && callees.includes('rectOfFieldSelection')
}

/**
 * 监听器里**不得**再自己读 selectionStart/End —— 那是第二份实现。
 * 两份实现必然漂移，且必有一份测不到（本仓既有判据）。
 */
function noSecondSourceInWatcher(sf) {
  const ps = propsIn(sf, sf)
  return !ps.some((p) => p.endsWith('.selectionStart') || p.endsWith('.selectionEnd'))
}

/** 旧形态 `isTextField` 必须整条退役（形态判据已上移到 isFieldElement） */
function isTextFieldRetired(sf) {
  return !identifiersIn(sf, sf).includes('isTextField')
}

/** onSelectionChange 必须按「焦点是否落在控件里」决定收不收浮层 */
function onSelectionChangeGuardsField(sf) {
  const fn = collectFns(sf).onSelectionChange
  if (!fn) return false
  return propsIn(sf, fn).some((p) => p === 'document.activeElement')
}

// =====================================================================
// 第三部分 · 真读源码跑判据
// =====================================================================

const util = parse(FIELD_UTIL)
const watcher = parse(WATCHER)
const utilExports = exportedNames(util.sf)
const utilFns = collectFns(util.sf)
const watcherFns = collectFns(watcher.sf)

// ---------------- S0 自检：先证明没空跑 ----------------
check(utilExports.has('readFieldSelection'), 'S0a 抽到 utils/textSelection.ts 的 readFieldSelection 导出', `实测导出 = ${[...utilExports].join(', ')}`)
check(utilExports.has('rectOfFieldSelection'), 'S0b 抽到 utils/textSelection.ts 的 rectOfFieldSelection 导出')
check(utilExports.has('isFieldElement'), 'S0c 抽到 utils/textSelection.ts 的 isFieldElement 导出')
check(!!utilFns.readFieldSelection && !!utilFns.rectOfFieldSelection, 'S0d 两个函数都有 AST 函数节点（=0 说明解析器坏了，不能算通过）')
check(!!watcherFns.onMouseUp && !!watcherFns.onSelectionChange, 'S0e 抽到监听器的 onMouseUp / onSelectionChange 节点')
const PW_CONSTS = passwordConstName(util.sf)
check(PW_CONSTS.length > 0, 'S0f 抽到模块级「密码类型」常量（const X = \'password\'）', `实测 ${JSON.stringify(PW_CONSTS)}`)

// ---------------- S1 取值通道形态 ----------------
check(readsSelectionOffsets(util.sf, utilFns.readFieldSelection),
  'S1a readFieldSelection 读 selectionStart **与** selectionEnd（控件内选区的唯一真源）')
check(comparesElTypeToPasswordConst(util.sf, utilFns.readFieldSelection, PW_CONSTS),
  'S1b readFieldSelection 显式排除 password（常量 + 在函数里与 el.type 比对，两半缺一都拦不住）')
check(hasTypeofNumberGuard(util.sf, utilFns.readFieldSelection),
  'S1c 不支持选区的类型走**运行期判据**（typeof selectionStart !== \'number\'），不是硬编码 type 名单')
check(removesMirrorInFinally(util.sf, utilFns.rectOfFieldSelection),
  'S1d 镜像节点在 finally 里被 removeChild（否则每次划词都往 body 挂一个 div）')
check(usesClientWidth(util.sf, utilFns.rectOfFieldSelection),
  'S1e 镜像宽度按 clientWidth 推（排除边框与滚动条，换行位置才对得上）')
check(!utilExports.has('isTextField'), 'S1f 旧形态 isTextField 不得在唯一真源里复活')

// ---------------- S2 接线形态 ----------------
check(watcherImportsFieldUtil(watcher.sf),
  'S2a onMouseUp 的宿主从 @/utils/textSelection 取 isFieldElement + readFieldSelection + rectOfFieldSelection',
  `实测该模块 import = ${JSON.stringify(importSpecs(watcher.sf).map((i) => i.src))}`)
check(fieldBranchUsable(watcher.sf),
  'S2b 表单控件分支非空、且第一条语句不是 return/throw（"提前掐掉"型改动 ⇒ 红）')
check(fieldChannelInsideBranch(watcher.sf),
  'S2c readFieldSelection 与 rectOfFieldSelection 都调在**控件分支内部**（在分支旁边调 = 分支白写）')
check(noSecondSourceInWatcher(watcher.sf),
  'S2d 监听器里**不得**自己读 selectionStart/selectionEnd —— 那是第二份实现，必然漂移且必有一份测不到')
check(isTextFieldRetired(watcher.sf),
  'S2e isTextField 已退役（重加回来 ⇒ 输入框划词被整条短路，且不会有任何报错）')
check(onSelectionChangeGuardsField(watcher.sf),
  'S2f onSelectionChange 按 document.activeElement 区分控件内选区（否则"刚划好的词"会被当场收掉，症状是"划词只见闪一下"）')

// ---------------- S3 锚点形状对账 ----------------
const rectMembers = interfaceMembers(util.sf, 'SelectionRect')
const anchorMembers = interfaceMembers(watcher.sf, 'TranslateAnchor')
check(!!rectMembers && !!anchorMembers,
  'S3a 两个锚点接口都能抽到（SelectionRect / TranslateAnchor）')
check(
  !!rectMembers && !!anchorMembers && rectMembers.join(',') === anchorMembers.join(','),
  'S3b SelectionRect 与 TranslateAnchor 的字段集合一致（漂移会让"零适配"变成静默错位）',
  `SelectionRect=[${(rectMembers || []).join(', ')}] TranslateAnchor=[${(anchorMembers || []).join(', ')}]`
)

// ---------------- S4 登记 ----------------
let pkg = null
try {
  pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'))
} catch {
  pkg = null
}
check(!!pkg && /check-selection-field-rule\.cjs/.test(String(pkg.scripts && pkg.scripts['check:selection-field'] || '')),
  'S4a package.json 登记了 check:selection-field')
check(!!pkg && /check-selection-field-rule\.cjs/.test(String((pkg.scripts && pkg.scripts.build) || '')),
  'S4b 本门禁已接入 npm run build 链')

// =====================================================================
// 第四部分 · 反向注入自检：证明上面每条判据**不是恒绿**
// =====================================================================
const BAD_UTIL = `
const NEVER_READ_TYPE = 'password'
export function readFieldSelection(el: any) {
  return { start: el.selectionStart, end: el.selectionEnd, text: el.value }
}
export function rectOfFieldSelection(el: any) {
  const d = document.createElement('div')
  document.body.appendChild(d)
  d.style.width = el.offsetWidth + 'px'
  return null
}
`
const badUtil = { sf: ts.createSourceFile('bad-util.ts', BAD_UTIL, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }
const badUtilFns = collectFns(badUtil.sf)
const BAD_PW_CONSTS = passwordConstName(badUtil.sf)

// ★ R1 刻意做成"常量在、但没人拿它比对"的形态 —— 这是**最容易被误判为合规**的坏样本：
//   只判「有没有 password 字面量」的门禁会被它骗过去
check(BAD_PW_CONSTS.length === 1, 'R0 坏样本里确实摆着一个 password 常量（用于构造 R1 的陷阱）')
check(!comparesElTypeToPasswordConst(badUtil.sf, badUtilFns.readFieldSelection, BAD_PW_CONSTS),
  'R1 坏样本（摆了 password 常量但没人用它比对 el.type）被判为不合规 —— 否则 S1b 恒绿')
check(!hasTypeofNumberGuard(badUtil.sf, badUtilFns.readFieldSelection),
  'R2 坏样本（不判 typeof === number）被判为不合规 —— 否则 S1c 恒绿')
check(!removesMirrorInFinally(badUtil.sf, badUtilFns.rectOfFieldSelection),
  'R3 坏样本（挂上镜像不摘）被判为不合规 —— 否则 S1d 恒绿')
check(!usesClientWidth(badUtil.sf, badUtilFns.rectOfFieldSelection),
  'R4 坏样本（按 offsetWidth 推宽度）被判为不合规 —— 否则 S1e 恒绿')

const BAD_WATCHER = `
const onMouseUp = (e) => {
  const sel = window.getSelection()
  const text = sel.toString()
  const r = sel.getRangeAt(0).getBoundingClientRect()
  const s = e.target.selectionStart
  const t = e.target.selectionEnd
  translate(text, r, s, t)
}
const onSelectionChange = () => { if (!window.getSelection().toString()) hide() }
function isTextField(t) { return t.tagName === 'INPUT' }
`
const badWatcher = { sf: ts.createSourceFile('bad-watcher.ts', BAD_WATCHER, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }

/**
 * ★ 最阴的一个坏样本：**两个函数都调了、名字都对、AST 节点都在**，
 *   只在块首插了一条 `return`。这正是"把行为改回旧样子"的最小 diff，
 *   而「是否调过」型判据对它**完全失明**（第 366 轮外部注入实测踩到，见到 rc=0/0 fail）。
 */
const NEUTERED_WATCHER = `
const onMouseUp = (e) => {
  if (isFieldElement(e.target)) {
    return
    const picked = readFieldSelection(e.target)
    const anchor = rectOfFieldSelection(e.target, picked.start, picked.end)
    translate(picked.text, anchor)
  }
  const sel = window.getSelection()
  translate(sel.toString(), null)
}
`
const neuteredWatcher = { sf: ts.createSourceFile('neutered.ts', NEUTERED_WATCHER, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }

/** 正向对照：形态正确的一份必须被判成合规（否则判据"太紧"，会误伤真实现） */
const GOOD_WATCHER = `
const onMouseUp = (e) => {
  if (isFieldElement(e.target)) {
    const picked = readFieldSelection(e.target)
    const anchor = rectOfFieldSelection(e.target, picked.start, picked.end)
    translate(picked.text, anchor)
    return
  }
  const sel = window.getSelection()
  translate(sel.toString(), null)
}
`
const goodWatcher = { sf: ts.createSourceFile('good.ts', GOOD_WATCHER, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }

check(!watcherImportsFieldUtil(badWatcher.sf),
  'R5 坏样本（不从唯一真源 import）被判为不合规 —— 否则 S2a 恒绿')
check(!fieldBranchUsable(badWatcher.sf) && !fieldChannelInsideBranch(badWatcher.sf),
  'R6 坏样本（onMouseUp 没有表单控件分支）被判为不合规 —— 否则 S2b/S2c 恒绿')
check(fieldChannelInsideBranch(neuteredWatcher.sf) && !fieldBranchUsable(neuteredWatcher.sf),
  'R7 ★ 坏样本（分支里两个函数都调了，只在块首插了一条 return）被判为**不合规** '
  + '—— 这条就是本门禁第一版失明的那个形态：只看"调没调过"会 rc=0/0 fail')
check(fieldBranchUsable(goodWatcher.sf) && fieldChannelInsideBranch(goodWatcher.sf),
  'R7b 正向对照：形态正确的一份被判成合规（判据太紧会误伤真实现）')
check(!noSecondSourceInWatcher(badWatcher.sf),
  'R8 坏样本（监听器里自己读 selectionStart）被判为不合规 —— 否则 S2d 恒绿')
check(!isTextFieldRetired(badWatcher.sf),
  'R9 坏样本（isTextField 复活）被判为不合规 —— 否则 S2e 恒绿')
check(!onSelectionChangeGuardsField(badWatcher.sf),
  'R10 坏样本（onSelectionChange 不看 activeElement）被判为不合规 —— 否则 S2f 恒绿')

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
  '表单控件划词门禁通过（取值真源 selectionStart/End · password 显式排除 · 运行期判据 · 镜像法带清理与 clientWidth 口径 · 接线到 useSelectionTranslate · 锚点形状对账 ✓）'
)

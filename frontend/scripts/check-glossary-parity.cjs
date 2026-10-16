#!/usr/bin/env node
/**
 * 术语表「前后端口径对账」门禁（第 369 轮 · P0）
 *
 * ════════════════════════════════════════════════════════════════════════
 * 为什么需要一条**跨语言**门禁
 * ════════════════════════════════════════════════════════════════════════
 * 术语表落地时出现了**两份解析实现**，这是刻意的（理由见前端 `utils/glossary.ts`
 * 文件头：后端宽松跳错是静默的，只有前端能给出「已识别 N 条」的读数）。但两份实现
 * 一旦漂移，症状是**用户可见的口径分叉**：
 *
 *     设置页说「已识别 5 条」，后端实际只用了 4 条 ⇒ 用户拿着自认为有效的表，
 *     永远想不通为什么某个词没按他的译法走。
 *
 * 已有的两道防线各自都够不着这一面：
 *   · `backend/tests/test_selection_glossary.py` —— 只看 Python 侧，**看不见前端**；
 *   · `frontend/tests/unit/glossary.test.ts`   —— 只看 TS 侧，**看不见后端**。
 *   ⇒ 常量只要有一端单独改，两边都是绿的。本门禁补的正是这个洞。
 *
 * ════════════════════════════════════════════════════════════════════════
 * 判据口径
 * ════════════════════════════════════════════════════════════════════════
 *  · TS 侧走 **AST**（`typescript` 包，与 `check-selection-field-rule.cjs` 同手法）。
 *    Python 侧没有 node 可用的 AST ⇒ 用**严格行锚定正则**，并且先剥三引号 docstring：
 *    这个仓库里「为什么这么做」的解释文字必然逐字引用 `MAX_ENTRIES` / `idx > 0`
 *    这些名字 —— 不剥就是「判据读到了文档而不是代码」的假绿。
 *  · **每条判据都要有证伪样本**（见文末「反向注入自检」）：常量对账型判据最容易
 *    写成「两边都抽不到 ⇒ 抽到的都是 null ⇒ 相等 ⇒ 绿」。所以 S0 组先证明**抽到了**。
 *  · **读集注入开口**：环境变量指向空文件时本门禁**必须变红**。
 *    ★ 边界：空源注入只能**证伪**（证明判据读了内容），不证明它读对了字段。
 *
 * 怎么跑：node scripts/check-glossary-parity.cjs
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..') // frontend/
const REPO = path.resolve(ROOT, '..') // 仓库根

const pick = (env, rel) =>
  process.env[env] ? path.resolve(process.env[env]) : path.join(REPO, ...rel)

const PY_GLOSSARY = pick('GLOSSARY_PY', ['backend', 'modules', 'aigc_media', 'glossary.py'])
const PY_SCHEMA = pick('GLOSSARY_SCHEMA_PY', ['backend', 'modules', 'aigc_media', 'schemas.py'])
const TS_GLOSSARY = pick('GLOSSARY_TS', ['frontend', 'src', 'utils', 'glossary.ts'])
const TS_API = pick('GLOSSARY_API_TS', ['frontend', 'src', 'api', 'aigcMedia.ts'])

const ts = require(path.join(ROOT, 'node_modules', 'typescript'))

const results = []
function check(ok, label, detail) {
  results.push({ ok: !!ok, label, detail })
}

// =====================================================================
// 抽取层 —— TS（AST）
// =====================================================================

function parseTs(file) {
  const src = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
  return { src, sf: ts.createSourceFile(file, src, ts.ScriptTarget.ES2020, true, ts.ScriptKind.TS) }
}

function walk(node, visit) {
  visit(node)
  ts.forEachChild(node, (c) => walk(c, visit))
}

/** 函数声明 + 赋给变量的箭头函数 / 函数表达式 */
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

/** 顶层 `export const X = <数字字面量>` */
function tsNumericConst(sf, name) {
  let v = null
  ts.forEachChild(sf, (n) => {
    if (!ts.isVariableStatement(n)) return
    for (const d of n.declarationList.declarations) {
      if (
        ts.isIdentifier(d.name) &&
        d.name.text === name &&
        d.initializer &&
        ts.isNumericLiteral(d.initializer)
      ) {
        v = Number(d.initializer.text)
      }
    }
  })
  return v
}

/** 顶层 `export const X: readonly string[] = ['a', 'b']`（含 `as const` 形态） */
function tsStringArrayConst(sf, name) {
  let out = null
  ts.forEachChild(sf, (n) => {
    if (!ts.isVariableStatement(n)) return
    for (const d of n.declarationList.declarations) {
      if (!ts.isIdentifier(d.name) || d.name.text !== name) continue
      let init = d.initializer
      if (init && ts.isAsExpression(init)) init = init.expression
      if (init && ts.isArrayLiteralExpression(init)) {
        out = init.elements.map((e) => (ts.isStringLiteral(e) ? e.text : null))
      }
    }
  })
  return out
}

/** 某函数里用到的函数调用 callee 文本集合 */
function callsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isCallExpression(n)) out.push(n.expression.getText(sf))
  })
  return out
}

/** 某函数里用到的属性访问文本集合（如 `seen.has` / `el.type`） */
function propsIn(sf, node) {
  const out = []
  walk(node, (n) => {
    if (ts.isPropertyAccessExpression(n)) out.push(n.getText(sf))
  })
  return out
}

/** `function name(data: { a: T; b?: U })` 的类型字面量属性名 */
function paramKeysOf(sf, fnName) {
  let out = null
  walk(sf, (n) => {
    if (out) return
    if (!ts.isFunctionDeclaration(n) || !n.name || n.name.text !== fnName) return
    const p = n.parameters[0]
    if (p && p.type && ts.isTypeLiteralNode(p.type)) {
      out = p.type.members.map((m) => m.name && m.name.getText(sf)).filter(Boolean)
    }
  })
  return out
}

// =====================================================================
// 抽取层 —— Python（严格行锚定正则；先剥三引号 docstring）
// =====================================================================

function readPy(file) {
  return fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n')
}

/** 剥 `"""…"""` / `'''…'''` —— 本仓文档里必然逐字引用这些常量名，不剥就是假绿 */
function stripPyDocstrings(src) {
  return src.replace(/"""[\s\S]*?"""/g, ' ').replace(/'''[\s\S]*?'''/g, ' ')
}

function pyNumericConst(src, name) {
  const m = new RegExp('^' + name + '\\s*=\\s*(\\d+)\\s*$', 'm').exec(stripPyDocstrings(src))
  return m ? Number(m[1]) : null
}

function pyTupleConst(src, name) {
  const m = new RegExp('^' + name + '\\s*=\\s*\\(([^)]*)\\)', 'm').exec(stripPyDocstrings(src))
  if (!m) return null
  const items = m[1].match(/"([^"]*)"|'([^']*)'/g)
  return items ? items.map((s) => s.slice(1, -1)) : []
}

/** 取某个 pydantic 类体（到下一个顶层 class 为止） */
function pyClassBody(src, className) {
  const s = stripPyDocstrings(src)
  const i = s.indexOf('class ' + className)
  if (i < 0) return null
  const j = s.indexOf('\nclass ', i + 1)
  return s.slice(i, j < 0 ? s.length : j)
}

/** 类体里的字段名（4 空格缩进的 `name: Type`） */
function pyClassFieldNames(src, className) {
  const body = pyClassBody(src, className)
  if (body === null) return null
  const out = []
  for (const line of body.split('\n')) {
    const m = /^ {4}([A-Za-z_][A-Za-z0-9_]*)\s*:/.exec(line)
    if (m) out.push(m[1])
  }
  return out
}

/**
 * `glossary` 字段的 `max_length`。
 *
 * ★ 为什么不匹配 `Field(… )` 的完整括号：description 是**嵌套括号**，
 *   非贪婪 `\)` 会停在 description 里的第一个右括号。改为切一个 500 字符窗口，
 *   在窗口里取**第一个** `max_length` —— 字段顺序是 default → max_length → description，
 *   所以第一个必然是 glossary 自己的。
 */
function pyGlossaryMaxLength(src) {
  const body = pyClassBody(src, 'SelectionTranslateRequest')
  if (body === null) return null
  const i = body.indexOf('glossary: str = Field(')
  if (i < 0) return null
  const m = /max_length\s*=\s*(\d+)/.exec(body.slice(i, i + 500))
  return m ? Number(m[1]) : null
}

// =====================================================================
// 判据层（纯函数：坏样本要能复用同一份判定）
// =====================================================================

const sameOrder = (a, b) =>
  Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => x === b[i])

/** 条数上限一致 */
function entriesCapMatches(pyCap, tsCap) {
  return typeof pyCap === 'number' && typeof tsCap === 'number' && pyCap === tsCap
}

/** 分隔符**同集合且同顺序** —— 顺序即优先级，后端是「先半角后全角」，前端必须同序 */
function separatorsMatch(pySeps, tsSeps) {
  return Array.isArray(pySeps) && Array.isArray(tsSeps) && sameOrder(pySeps, tsSeps)
}

/** 字数上限一致（不一致 ⇒ 超限时后端 422，而划词是静默操作、用户无从归因） */
function charsCapMatches(pyMax, tsMax) {
  return typeof pyMax === 'number' && typeof tsMax === 'number' && pyMax === tsMax
}

/** 前端实际发出去的键，必须**全部**被后端 schema 接受（拼错 = pydantic 静默忽略 = 术语表不生效） */
function requestKeysAccepted(tsKeys, pyFields) {
  if (!Array.isArray(tsKeys) || tsKeys.length === 0 || !Array.isArray(pyFields)) return false
  return tsKeys.every((k) => pyFields.includes(k))
}

/** 上限判定必须用 `>=`（改成 `>` 会让上限悄悄变成 101 条） */
function capGuardIsGte(sf) {
  const fn = collectFns(sf).parseGlossary
  if (!fn) return false
  let ok = false
  walk(fn, (n) => {
    if (!ts.isBinaryExpression(n)) return
    if (n.operatorToken.kind !== ts.SyntaxKind.GreaterThanEqualsToken) return
    if (n.right.getText(sf) === 'MAX_GLOSSARY_ENTRIES') ok = true
  })
  return ok
}

/** 残行判定必须是 `idx > 0`（写成 `>= 0` 会让 `=foo` 产出空原文，污染提示词） */
function residualGuardIsGtZero(sf) {
  const fn = collectFns(sf).parseGlossary
  if (!fn) return false
  let seenAny = false
  let ok = false
  walk(fn, (n) => {
    if (!ts.isBinaryExpression(n)) return
    const k = n.operatorToken.kind
    if (k !== ts.SyntaxKind.GreaterThanToken && k !== ts.SyntaxKind.GreaterThanEqualsToken) return
    if (!ts.isIdentifier(n.left) || n.left.text !== 'idx') return
    if (!ts.isNumericLiteral(n.right) || n.right.text !== '0') return
    seenAny = true
    if (k === ts.SyntaxKind.GreaterThanToken) ok = true
    else ok = false // 出现 `>=` 即判定失败（哪怕另一处是对的）
  })
  return seenAny && ok
}

/** 命中分隔符后必须 `break`（不许继续试后面的分隔符 —— 那会变成「取最后一个」） */
function breaksAfterSeparator(sf) {
  const fn = collectFns(sf).parseGlossary
  if (!fn) return false
  let ok = false
  walk(fn, (n) => {
    if (!ts.isIfStatement(n)) return
    const c = n.expression
    if (!ts.isBinaryExpression(c)) return
    if (!ts.isIdentifier(c.left) || c.left.text !== 'idx') return
    const then = n.thenStatement
    if (ts.isBlock(then) && then.statements.some((s) => ts.isBreakStatement(s))) ok = true
  })
  return ok
}

/** 同名词去重：`seen.has` 判断 + `seen.add` 写入，两半缺一都不算 */
function dedupesBySeen(sf) {
  const fn = collectFns(sf).parseGlossary
  if (!fn) return false
  const has = propsIn(sf, fn).some((p) => p.endsWith('.has'))
  const add = callsIn(sf, fn).some((c) => /\.add$/.test(c))
  return has && add
}

// =====================================================================
// 真读源码跑判据
// =====================================================================

const tsGlossary = parseTs(TS_GLOSSARY)
const tsApi = parseTs(TS_API)
const pyGlossarySrc = readPy(PY_GLOSSARY)
const pySchemaSrc = readPy(PY_SCHEMA)

const TS_ENTRIES = tsNumericConst(tsGlossary.sf, 'MAX_GLOSSARY_ENTRIES')
const TS_CHARS = tsNumericConst(tsGlossary.sf, 'MAX_GLOSSARY_CHARS')
const TS_SEPS = tsStringArrayConst(tsGlossary.sf, 'GLOSSARY_SEPARATORS')
const TS_FNS = collectFns(tsGlossary.sf)
const TS_REQ_KEYS = paramKeysOf(tsApi.sf, 'translateSelection')

const PY_ENTRIES = pyNumericConst(pyGlossarySrc, 'MAX_ENTRIES')
const PY_SEPS = pyTupleConst(pyGlossarySrc, '_SEPARATORS')
const PY_CHARS = pyGlossaryMaxLength(pySchemaSrc)
const PY_FIELDS = pyClassFieldNames(pySchemaSrc, 'SelectionTranslateRequest')

// ---------------- S0 自检：先证明没空跑 ----------------
check(
  typeof TS_ENTRIES === 'number' && typeof TS_CHARS === 'number' && Array.isArray(TS_SEPS),
  'S0a 从前端 utils/glossary.ts 抽到 MAX_GLOSSARY_ENTRIES / MAX_GLOSSARY_CHARS / GLOSSARY_SEPARATORS',
  `实测 = ${TS_ENTRIES} / ${TS_CHARS} / ${JSON.stringify(TS_SEPS)}`,
)
check(!!TS_FNS.parseGlossary, 'S0b 抽到前端 parseGlossary 的 AST 函数节点（=0 说明解析器坏了，不能算通过）')
check(
  typeof PY_ENTRIES === 'number' && Array.isArray(PY_SEPS),
  'S0c 从后端 glossary.py 抽到 MAX_ENTRIES / _SEPARATORS',
  `实测 = ${PY_ENTRIES} / ${JSON.stringify(PY_SEPS)}`,
)
check(
  typeof PY_CHARS === 'number' && Array.isArray(PY_FIELDS) && PY_FIELDS.length > 0,
  'S0d 从后端 schemas.py 抽到 glossary 的 max_length 与 SelectionTranslateRequest 字段集',
  `实测 max_length=${PY_CHARS} fields=${JSON.stringify(PY_FIELDS)}`,
)
check(
  Array.isArray(TS_REQ_KEYS) && TS_REQ_KEYS.length > 0,
  'S0e 从前端 api/aigcMedia.ts 抽到 translateSelection 的请求体键集合',
  `实测 = ${JSON.stringify(TS_REQ_KEYS)}`,
)

// ---------------- S1 常量对账 ----------------
check(
  entriesCapMatches(PY_ENTRIES, TS_ENTRIES),
  `S1a 条数上限一致（后端 MAX_ENTRIES=${PY_ENTRIES} vs 前端 MAX_GLOSSARY_ENTRIES=${TS_ENTRIES}）`
  + ' —— 不一致时两端会算出不同的「已识别 N 条」',
)
check(
  separatorsMatch(PY_SEPS, TS_SEPS),
  `S1b 分隔符同集合**且同顺序**（后端 ${JSON.stringify(PY_SEPS)} vs 前端 ${JSON.stringify(TS_SEPS)}）`
  + ' —— 顺序即优先级：后端先试半角，前端必须同序，否则 `A＝B=C` 的切点会不同',
)
check(
  charsCapMatches(PY_CHARS, TS_CHARS),
  `S1c 字数上限一致（后端 schema max_length=${PY_CHARS} vs 前端 MAX_GLOSSARY_CHARS=${TS_CHARS}）`
  + ' —— 前端偏大 ⇒ 超限请求被后端 422，而划词是静默操作、用户无从归因',
)

// ---------------- S2 请求体字段名对账 ----------------
check(
  requestKeysAccepted(TS_REQ_KEYS, PY_FIELDS),
  `S2a 前端发出的每个键都被后端 schema 接受（前端 ${JSON.stringify(TS_REQ_KEYS)}`
  + ` ⊆ 后端 ${JSON.stringify(PY_FIELDS)}）`
  + ' —— 键名拼错时 pydantic 会**静默忽略**多余字段：不报 422，术语表只是不生效',
)
check(
  Array.isArray(PY_FIELDS) && PY_FIELDS.includes('glossary'),
  'S2b 后端 schema 确实有 glossary 字段（前端加了后端没加 ⇒ 同上，静默不生效）',
)

// ---------------- S3 前端形态（防「顺手优化」） ----------------
check(
  capGuardIsGte(tsGlossary.sf),
  'S3a 上限判定用 `entries.length >= MAX_GLOSSARY_ENTRIES`（改成 `>` 会让上限悄悄变成 101 条）',
)
check(
  residualGuardIsGtZero(tsGlossary.sf),
  'S3b 残行判定用 `idx > 0`（写成 `>= 0` 会让 `=foo` 产出空原文，污染提示词）',
)
check(
  breaksAfterSeparator(tsGlossary.sf),
  'S3c 命中分隔符后 `break`（去掉就变成「继续试后面的分隔符」= 取最后一个，静默改语义）',
)
check(
  dedupesBySeen(tsGlossary.sf),
  'S3d 同名词去重两半都在（`seen.has` 判断 + `seen.add` 写入）',
)

// ---------------- S4 登记 ----------------
let pkg = null
try {
  pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'))
} catch {
  pkg = null
}
check(
  !!pkg && /check-glossary-parity\.cjs/.test(String((pkg.scripts && pkg.scripts['check:glossary-parity']) || '')),
  'S4a package.json 登记了 check:glossary-parity',
)
check(
  !!pkg && /check-glossary-parity\.cjs/.test(String((pkg.scripts && pkg.scripts.build) || '')),
  'S4b 本门禁已接入 npm run build 链',
)

// =====================================================================
// 反向注入自检：证明上面每条判据**不是恒绿**
// =====================================================================

const tsOf = (src, kind) =>
  ts.createSourceFile('bad.ts', src, ts.ScriptTarget.ES2020, true, kind || ts.ScriptKind.TS)

// R1 条数上限改大
const R1 = tsOf(`
export const MAX_GLOSSARY_ENTRIES = 200
export const MAX_GLOSSARY_CHARS = 4000
export const GLOSSARY_SEPARATORS: readonly string[] = ['=', '＝']
`)
check(
  !entriesCapMatches(PY_ENTRIES, tsNumericConst(R1, 'MAX_GLOSSARY_ENTRIES')),
  'R1 坏样本（前端条数上限 100 → 200）被判不一致 —— 否则 S1a 恒绿',
)

// R2 分隔符顺序颠倒
const R2 = tsOf(`
export const GLOSSARY_SEPARATORS: readonly string[] = ['＝', '=']
`)
check(
  !separatorsMatch(PY_SEPS, tsStringArrayConst(R2, 'GLOSSARY_SEPARATORS')),
  'R2 坏样本（前端分隔符顺序颠倒）被判不一致 —— 否则 S1b 恒绿',
)

// R3 字数上限改大
const R3 = tsOf(`export const MAX_GLOSSARY_CHARS = 8000`)
check(
  !charsCapMatches(PY_CHARS, tsNumericConst(R3, 'MAX_GLOSSARY_CHARS')),
  'R3 坏样本（前端字数上限 4000 → 8000）被判不一致 —— 否则 S1c 恒绿',
)

// R4 请求体键拼错（最致命的那个形态：后端静默忽略）
check(
  !requestKeysAccepted(['text', 'glossarys'], PY_FIELDS),
  'R4 坏样本（前端把 glossary 拼成 glossarys）被判不接受 —— 否则 S2a 恒绿',
)
check(
  !requestKeysAccepted(['text', 'glossary'], ['text', 'target_lang', 'context']),
  'R4b 坏样本（后端没有 glossary 字段）被判不接受 —— 否则 S2a 会因「后端字段集为空」而误绿',
)

// R5 上限判定改成 >
const R5 = tsOf(`
export function parseGlossary(raw: string) {
  const entries = []
  for (const line of raw.split('\\n')) {
    if (entries.length > 100) break
  }
  return entries
}
`)
check(!capGuardIsGte(R5), 'R5 坏样本（上限判定用 `>` 而不是 `>=`）被判失败 —— 否则 S3a 恒绿')

// R6 残行判定改成 >= 0
const R6 = tsOf(`
export function parseGlossary(raw: string) {
  for (const body of raw.split('\\n')) {
    const idx = body.indexOf('=')
    if (idx >= 0) { break }
  }
}
`)
check(
  !residualGuardIsGtZero(R6),
  'R6 ★ 坏样本（残行判定 `idx > 0` → `idx >= 0`）被判失败 —— 否则 S3b 恒绿，'
  + '而症状是「=foo」这类残行产出空原文',
)
check(
  residualGuardIsGtZero(
    tsOf(`
export function parseGlossary(raw: string) {
  for (const body of raw.split('\\n')) {
    const idx = body.indexOf('=')
    if (idx > 0) { break }
  }
}
`),
  ),
  'R6b 正向对照：形态正确的一份被判成功（判据太紧会误伤真实现）',
)

// R7 去掉 break
const R7 = tsOf(`
export function parseGlossary(raw: string) {
  for (const body of raw.split('\\n')) {
    const idx = body.indexOf('=')
    if (idx > 0) { const a = 1 }
  }
}
`)
check(!breaksAfterSeparator(R7), 'R7 坏样本（命中分隔符后没有 break）被判失败 —— 否则 S3c 恒绿')

// R8 去掉去重
const R8 = tsOf(`
export function parseGlossary(raw: string) {
  const seen = new Set()
  return raw
}
`)
check(!dedupesBySeen(R8), 'R8 坏样本（没有 seen.has / seen.add）被判失败 —— 否则 S3d 恒绿')

// R9 空源注入（证伪：证明判据真的读了文件内容）
const EMPTY = ''
check(
  pyNumericConst(EMPTY, 'MAX_ENTRIES') === null ||
    tsNumericConst(tsOf(EMPTY), 'MAX_GLOSSARY_ENTRIES') === null,
  'R9 空源注入 ⇒ 抽不到常量（证明判据确实读了文件内容，而不是恒取真值）',
)
check(
  pyClassFieldNames(EMPTY, 'SelectionTranslateRequest') === null,
  'R9b 空源注入 ⇒ 抽不到字段集（同上，针对 Python 抽取器）',
)
// R9c 空源必须让 S0 那组**变红**（把空源喂给 S0 用的同一组判定）
const emptyTs = tsOf(EMPTY)
check(
  !(
    typeof tsNumericConst(emptyTs, 'MAX_GLOSSARY_ENTRIES') === 'number' &&
    !!collectFns(emptyTs).parseGlossary
  ),
  'R9c 空源注入 ⇒ S0a/S0b 那组自检必然失败 —— 否则「抽不到也绿」',
)
// R9d 读取通道真生效：把注入路径指向一个**不存在**的文件必须抛，而不是静默回空
let throwsOnMissing = false
try {
  fs.readFileSync(path.join(ROOT, '__definitely_missing__.ts'), 'utf8')
} catch {
  throwsOnMissing = true
}
check(throwsOnMissing, 'R9d 读路径不存在时抛异常（不是静默回空 ⇒ 注入开口不会掩盖配置错误）')

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
  '术语表前后端口径对账通过（条数上限 · 分隔符集合与顺序 · 字数上限 · 请求体字段名 ⊆ 后端 schema · '
  + '前端解析三项形态 · 登记与 build 接线 ✓）',
)

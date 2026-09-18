#!/usr/bin/env node
/**
 * 工具执行真伪门禁（★ 第 128 轮 · P0-2 批 1）
 *
 * 为什么值得单独一个门禁：`src/mock/toolExecutors.ts` 是「对话里点一个工具卡 → 出结果」
 * 的唯一入口。它的函数**签名完全一样**，返回**形状也完全一样** —— 所以「真调后端」和
 * 「`Math.random()` 编一份」在类型系统、在单测、在界面上**全都长得一模一样**。
 * 本项目已经因此吃过大亏：广告诊断存在**两条路径**，对话关键词那条真调后端，
 * 工具卡那条全是 `Math.random()`（两个数字来源，谁也不报错）。
 *
 * ⇒ 必须有一条断言**能对「这里其实是假数据」说不**。
 *
 * 三道断言：
 *   A「本轮已接线的 4 个必须永远为真」—— 具名钉死，防偷偷退回去
 *   B「其余 mock 执行器数量不得增长」—— 总量封顶，防新工具一路 mock 下去
 *   C「命名的执行器必须真的存在」—— 防止改名后门禁静默失去覆盖（最隐蔽的失效）
 *
 * 怎么跑：node scripts/check-tool-reality.cjs
 *   加 --report 只打印分类表、不做判定（用于盘点）。
 *
 * 反向注入（证明本门禁不是空跑）：
 *   TOOL_EXECUTORS_SRC=<一份把 4 个里的某个 api 调用删掉的副本> node scripts/check-tool-reality.cjs
 *   —— 断言 A 必须变红。见 .workbuddy/probes/_r128s_bad_executors.ts
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const SRC = process.env.TOOL_EXECUTORS_SRC
  ? path.resolve(process.env.TOOL_EXECUTORS_SRC)
  : path.join(ROOT, 'src', 'mock', 'toolExecutors.ts')

/** ★ A：本轮（第 128 轮 · P0-2 批 1）已接线为真调后端的执行器，永久钉死 */
const MUST_BE_REAL = [
  'executeAdDiagnosis',
  'executeCompetitorAnalysis',
  'executeSEOAudit',
  'executeBulletGen',
]

/** ★ B：允许仍为本地 mock 的 execute* 数量上限（只许减不许增）
 *
 * 基线不是手写的，是**现算**的 —— 手写的期望值已经错过三次：
 *   git show HEAD:frontend/src/mock/toolExecutors.ts > /tmp/head.ts   （Windows 下用项目内路径）
 *   TOOL_EXECUTORS_SRC=<该副本> node scripts/check-tool-reality.cjs --report
 * 实测：第 128 轮前 = 36 个 execute*，真调用 1 / **mock 35**；
 *       第 128 轮 P0-2 批 1 接线后 = 真调用 5 / **mock 31**（本轮消掉 4 个）。
 */
const MOCK_LIMIT = 31

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 工具

/**
 * 剥注释（字符串/模板字面量感知）。
 * ★ 这一步是**必须**的：本文件里到处是解释性注释，注释里恰好会提到 `diagnoseAdAccount`、
 *   `Math.random()` 这些词 ⇒ 不剥注释就会把「注释里提过」误判成「代码里调过」。
 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    const nx = src[i + 1]
    if (ch === '/' && nx === '*') {
      const k = src.indexOf('*/', i + 2)
      i = k < 0 ? n : k + 2
      continue
    }
    if (ch === '/' && nx === '/') {
      const k = src.indexOf('\n', i)
      i = k < 0 ? n : k
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      const q = ch
      out += ch
      i++
      while (i < n) {
        if (src[i] === '\\') {
          out += src.slice(i, i + 2)
          i += 2
          continue
        }
        out += src[i]
        if (src[i] === q) {
          i++
          break
        }
        i++
      }
      continue
    }
    out += ch
    i++
  }
  return out
}

/** 从 `{` 处找配对 `}`（字符串/模板/注释感知），返回其索引，找不到返回 -1 */
function matchBrace(src, openIdx) {
  let depth = 0
  let i = openIdx
  const n = src.length
  while (i < n) {
    const ch = src[i]
    const nx = src[i + 1]
    if (ch === '/' && nx === '*') {
      const k = src.indexOf('*/', i + 2)
      i = k < 0 ? n : k + 2
      continue
    }
    if (ch === '/' && nx === '/') {
      const k = src.indexOf('\n', i)
      i = k < 0 ? n : k
      continue
    }
    if (ch === "'" || ch === '"' || ch === '`') {
      const q = ch
      i++
      while (i < n) {
        if (src[i] === '\\') {
          i += 2
          continue
        }
        if (src[i] === q) {
          i++
          break
        }
        i++
      }
      continue
    }
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) return i
    }
    i++
  }
  return -1
}

/** 收集 `import { a, b as c } from '@/api/...'` 的**本地名**集合 */
function collectApiImports(src) {
  const names = new Set()
  const re = /import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['"]@\/api\/[^'"]+['"]/g
  let m
  while ((m = re.exec(src))) {
    for (const piece of m[1].split(',')) {
      const t = piece.trim()
      if (!t) continue
      const asMatch = t.match(/^(\S+)\s+as\s+(\S+)$/)
      names.add(asMatch ? asMatch[2] : t)
    }
  }
  // 默认导入 / 命名空间导入也收
  const re2 = /import\s+(\w+)\s+from\s*['"]@\/api\/[^'"]+['"]/g
  while ((m = re2.exec(src))) names.add(m[1])
  const re3 = /import\s+\*\s+as\s+(\w+)\s+from\s*['"]@\/api\/[^'"]+['"]/g
  while ((m = re3.exec(src))) names.add(m[1])
  return names
}

/** 抽出所有 `export const executeXxx = ...` 的 { name, body } */
function collectExecutors(src) {
  const out = []
  const re = /export\s+const\s+(execute[A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*/g
  let m
  while ((m = re.exec(src))) {
    const name = m[1]
    // 从 = 之后找第一个顶层 '{'，再配对它的 '}'
    let i = m.index + m[0].length
    // 跳过可能的泛型/返回类型标注
    while (i < src.length && src[i] !== '{' && src[i] !== ';') i++
    if (i >= src.length || src[i] === ';') {
      out.push({ name, body: '' })
      continue
    }
    const close = matchBrace(src, i)
    out.push({ name, body: close < 0 ? src.slice(i) : src.slice(i, close + 1) })
  }
  return out
}

// ---------------------------------------------------------------- 判定

const raw = fs.readFileSync(SRC, 'utf8')
const code = stripComments(raw)
const apiNames = collectApiImports(code)
const executors = collectExecutors(code)

const rows = []
for (const { name, body } of executors) {
  const apiCalls = [...apiNames].filter((fn) => new RegExp('(?<![\\w$.])' + fn + '\\s*\\(').test(body))
  rows.push({
    name,
    apiCalls,
    real: apiCalls.length > 0,
    random: /Math\.random\s*\(/.test(body),
    delay: /setTimeout\s*\(/.test(body),
    bytes: Buffer.byteLength(body, 'utf8'),
  })
}

const mocks = rows.filter((r) => !r.real)
const real = rows.filter((r) => r.real)

console.log(`工具执行真伪门禁 —— 源文件 ${path.relative(ROOT, SRC)}`)
console.log(`  共 ${rows.length} 个 execute*：真调用 ${real.length} / 本地 mock ${mocks.length}`)
console.log(`  @/api/* 命名导入：${[...apiNames].join(', ') || '(无)'}\n`)

if (REPORT_ONLY || process.env.TOOL_EXECUTORS_REPORT === '1') {
  console.log('  真调用：')
  for (const r of real) console.log(`    REAL  ${r.name.padEnd(32)} ${r.apiCalls.join(', ')}`)
  console.log('  本地 mock：')
  for (const r of mocks) {
    const flags = [r.random ? 'Math.random' : '', r.delay ? 'setTimeout' : ''].filter(Boolean).join('+')
    console.log(`    MOCK  ${r.name.padEnd(32)} ${String(r.bytes).padStart(6)} B  ${flags}`)
  }
  process.exit(0)
}

// ---------------------------------------------------------------- 断言

const results = []
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}
function check(name, fn) {
  try {
    fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}

// ★ C：命名钉死的执行器必须真的存在（防改名后静默失效）
for (const target of MUST_BE_REAL) {
  check(`C 存在：${target}`, () => {
    assert(rows.some((r) => r.name === target), `未找到 export const ${target} —— 若已改名，本门禁的断言 A 就静默失效了`)
  })
}

// ★ A：已接线的必须真调后端，且不得有 mock 特征
for (const target of MUST_BE_REAL) {
  check(`A 真调用：${target}`, () => {
    const r = rows.find((x) => x.name === target)
    assert(r, `${target} 不存在`)
    assert(r.real, `${target} 没有任何 @/api/* 调用 —— 它退回本地 mock 了`)
    assert(!r.random, `${target} 里出现了 Math.random() —— 真数据不会被随机数编出来`)
    assert(!r.delay, `${target} 里出现了 setTimeout —— mock 假延迟不该出现在真调用路径`)
  })
}

// ★ B：mock 总量封顶
check(`B mock 数量不增长：${mocks.length} <= ${MOCK_LIMIT}`, () => {
  assert(
    mocks.length <= MOCK_LIMIT,
    `本地 mock 执行器 ${mocks.length} 个，超过上限 ${MOCK_LIMIT}（新增工具请接真后端，或先上调本上限并说明理由）`,
  )
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n工具执行真伪门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `工具执行真伪门禁通过（已接线 ${MUST_BE_REAL.length} 个真调用 ✓ / 本地 mock ${mocks.length} 个 ≤ ${MOCK_LIMIT} ✓）`,
)

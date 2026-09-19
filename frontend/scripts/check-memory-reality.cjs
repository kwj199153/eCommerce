#!/usr/bin/env node
/**
 * 长期记忆「真伪门禁」（★ 第 152 轮 · 批 C2）
 *
 * 为什么值得单独一个门禁
 * ====================
 * `MemoryEvolution.vue` 曾经是**假页面**（r141 §2.4）：34 行硬编码的
 * 「跨境电商卖家画像」+ 7 条编造的学习日志 + 四个操作全部只改本地 `ref`
 * ——「保存」零 API 调用、「重置」只是把内容赋成一句占位文案、「开关」只弹一个
 * toast。而界面文案写着**「每晚自动整理更新」**：承诺了一件后端没实现的事。
 *
 * 这种形态最要命的地方是：**它在类型系统、在单测、在界面上全都长得一模一样**。
 * 假页面不会报错、不会红、不会警告 —— 它只是安静地展示一份编出来的数据，
 * 而用户没有任何办法知道那是编的。
 * ⇒ 必须有一条断言**能对「这里其实是假数据」说不**。
 *
 * 九组断言
 * ========
 *   A 契约对账：`src/api/memory.ts` 的 (method, path) 集合与后端
 *     `backend/modules/memory/router.py` 的端点集合**双向**相等。
 *     · 后端有、前端没调 ⇒ 某个后端能力永远没人用（`/accounts/*` 就是 9 个端点全闲置）
 *     · 前端有、后端没有 ⇒ 在调一个不存在的端点，运行时 404
 *   B 视图真的在用：必须 import；api 层**导出的每个函数**都必须在视图里被**调用**
 *     （只 import 不调用 = 接线了但不工作，同样是零报错零测试红）
 *   C 没有本地假数据：视图里不得出现超长字符串字面量（假画像就是一大坨字面量）；
 *     不得再出现 `rawMemory` / `dailyLogs` 这种"本地自造的记忆/日志"标识符
 *   D 五个写口都真的发请求：开关 / 保存 / 导入 / 重置 / 立即整理，逐个具名钉死
 *     （具名的函数必须真的存在，否则改名后本组断言会静默失去覆盖）
 *   E 失败路径必须回写界面状态：三个 error 出口各有渲染位置，且每个写 handler
 *     的 catch 里都要有出口。只弹 toast 不行 —— 抽屉里会显示"没有记忆"，
 *     而"没有记忆"和"读不到记忆"对用户是两件完全不同的事
 *   F v-html 安全：正文渲染必须走 markdown-it 且显式 `html: false`
 *     （手写正则那版完全不转义，导入一个含 `<img onerror>` 的 .md 就直接执行）
 *   G 失败判据来自后端：时间线的"是不是坏消息"由后端 `is_failure` 给，
 *     前端不得再列一份 `kind` 名单（新增失败类型时那份名单不会跟着变）
 *   H 上限来自后端：界面展示的条数上限必须取自 `GET /memory` 的 `limits`，
 *     不得在前端写死（写死的那份永远不会红，只会安静地显示错的数字）
 *   I 归属不进请求体：api 层不得出现 `owner_id`（会造出可越权的自报字段）
 *
 * 怎么跑
 * ======
 *   node scripts/check-memory-reality.cjs            做判定
 *   node scripts/check-memory-reality.cjs --report    只打印盘面读数、不判定
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 三处源文件都可以用环境变量指向**副本**，于是能在不改工作区的前提下逐条打穿：
 *   MEMORY_VIEW_SRC=<副本.vue>  MEMORY_API_SRC=<副本.ts>  MEMORY_ROUTER_SRC=<副本.py>
 * 见 .workbuddy/probes/r152c_reverse_inject.py（A~I 逐条 + 一条「不该红」的对照）。
 *
 * ★ 边界（诚实说明）：本门禁只判**活代码**（先剥注释再判）。
 *   "把假数据注释掉留着"这类残留它看不到 —— 那属于 code review 的事，
 *   而不是靠一条字符串断言能可靠解决的（本仓已被 docstring 骗过四次）。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

const VIEW_SRC = process.env.MEMORY_VIEW_SRC
  ? path.resolve(process.env.MEMORY_VIEW_SRC)
  : path.join(ROOT, 'src', 'views', 'MemoryEvolution.vue')
const API_SRC = process.env.MEMORY_API_SRC
  ? path.resolve(process.env.MEMORY_API_SRC)
  : path.join(ROOT, 'src', 'api', 'memory.ts')
const ROUTER_SRC = process.env.MEMORY_ROUTER_SRC
  ? path.resolve(process.env.MEMORY_ROUTER_SRC)
  : path.join(ROOT, '..', 'backend', 'modules', 'memory', 'router.py')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 口径常量
//
// ★ 这些数字**不是手写的**，是用 `--report` 在真文件上现量出来的（第 152 轮）：
//   C 最长字符串字面量 = **99 字符**（Modal 确认框那段带插值的模板串）
//     ⇒ 上限取 400，留 4 倍余量。
//     参照：被删掉的假画像单条字面量 ~1500 字符。阈值过紧会把正常文案判红。
const MAX_STRING_LITERAL = 400
const WRITE_HANDLERS = [
  'onToggleAutoMemory', // 开关
  'onSaveMemory', // 保存整份
  'handleFileImport', // 导入文件
  'onResetMemory', // 重置
  'onDistillNow', // 立即整理
]
const ERROR_OUTLETS = ['loadError', 'saveError', 'logsError']
const FAKE_PAGE_MARKERS = ['rawMemory', 'dailyLogs']
/** 必须被视图消费的后端下发病据（不由前端推算） */
const BACKEND_OWNED = ['is_failure', 'limits', 'last_distilled_at', 'reason']

// ---------------------------------------------------------------- 解析工具

/**
 * 剥注释（字符串 / 模板字面量感知）。
 *
 * ★ 与 `check-tool-reality.cjs` 同源。必须做这一步的原因本仓已反复踩到：
 *   `api/memory.ts` 里 `owner_id` 出现 4 次，**全在解释"为什么不能有它"的注释里**
 *   —— 不剥注释的话，I 组会把一份正确的实现判成违反。
 * ★ 比 tool-reality 那版多剥 `<!-- -->`（.vue 模板里的注释）。
 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    const nx = src[i + 1]
    if (ch === '<' && src.startsWith('<!--', i)) {
      const k = src.indexOf('-->', i + 4)
      i = k < 0 ? n : k + 3
      continue
    }
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

/** 收集所有字符串 / 模板字面量的值（不做反转义，长度统计够用） */
function collectStringLiterals(src) {
  const out = []
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    if (ch === "'" || ch === '"' || ch === '`') {
      const q = ch
      const start = i + 1
      i++
      while (i < n) {
        if (src[i] === '\\') {
          i += 2
          continue
        }
        if (src[i] === q) break
        i++
      }
      out.push(src.slice(start, i))
      i++
      continue
    }
    i++
  }
  return out
}

/** 抽出 `function NAME(` / `async function NAME(` 的函数体；找不到返回 null */
function extractFunctionBody(src, name) {
  const re = new RegExp('(?:async\\s+)?function\\s+' + name + '\\s*\\(', 'g')
  const m = re.exec(src)
  if (!m) return null
  let i = m.index + m[0].length - 1 // 停在 '('
  // 跳过参数表
  let depth = 0
  for (; i < src.length; i++) {
    if (src[i] === '(') depth++
    else if (src[i] === ')') {
      depth--
      if (depth === 0) {
        i++
        break
      }
    }
  }
  // 找函数体的第一个 '{'
  while (i < src.length && src[i] !== '{' && src[i] !== ';') i++
  if (i >= src.length || src[i] === ';') return null
  const close = matchBrace(src, i)
  return close < 0 ? null : src.slice(i, close + 1)
}

/** 列出 `export function NAME` 的名字 */
function collectExportedFunctions(src) {
  const names = []
  const re = /export\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)/g
  let m
  while ((m = re.exec(src))) names.push(m[1])
  return names
}

/** 收集 `import { a, b as c } from '@/api/memory'` 的本地名 */
function collectImportedNames(src, moduleSuffix) {
  const names = new Set()
  const re = new RegExp(
    'import\\s+(?:type\\s+)?\\{([^}]*)\\}\\s*from\\s*[\'"]' + moduleSuffix + '[\'"]',
    'g',
  )
  let m
  while ((m = re.exec(src))) {
    for (const piece of m[1].split(',')) {
      const t = piece.trim()
      if (!t || t.startsWith('type ')) continue
      const asMatch = t.match(/^(\S+)\s+as\s+(\S+)$/)
      names.add(asMatch ? asMatch[2] : t)
    }
  }
  return names
}

/** `foo(...)` 形态的调用（排除成员访问 `x.foo(`） */
function isCalled(src, name) {
  return new RegExp('(?<![\\w$.])' + name + '\\s*\\(').test(src)
}

// ---------------------------------------------------------------- 后端端点

/**
 * 从 FastAPI router 源码抽出 `METHOD /prefix/path` 集合。
 * ★ 读的是**后端源码**而不是某个手写清单 —— 手写清单正是"改了后端忘改前端"的来源。
 */
function collectBackendEndpoints(src) {
  const prefixMatch = src.match(/APIRouter\s*\(([^)]*)\)/)
  let prefix = ''
  if (prefixMatch) {
    const pm = prefixMatch[1].match(/prefix\s*=\s*['"]([^'"]*)['"]/)
    if (pm) prefix = pm[1]
  }
  const out = new Set()
  const re = /@router\.(get|post|put|patch|delete)\s*\(\s*['"]([^'"]*)['"]/g
  let m
  while ((m = re.exec(src))) {
    out.add(`${m[1].toUpperCase()} ${normalizePath(prefix + m[2])}`)
  }
  return out
}

/** 路径归一化：去掉尾部斜杠、把重复斜杠收成一个 */
function normalizePath(p) {
  let s = String(p || '').replace(/\/{2,}/g, '/')
  if (s.length > 1 && s.endsWith('/')) s = s.slice(0, -1)
  return s || '/'
}

/** 从 api 层源码抽出 `METHOD /path` 集合（只看从 ./request 导入的 helper） */
function collectApiCalls(src) {
  const helpers = collectImportedNames(src, '\\.\\/request')
  const map = { get: 'GET', post: 'POST', put: 'PUT', patch: 'PATCH', del: 'DELETE' }
  const out = new Set()
  for (const h of helpers) {
    const method = map[h]
    if (!method) continue
    const re = new RegExp('(?<![\\w$.])' + h + '\\s*\\(\\s*[\'"]([^\'"]+)[\'"]', 'g')
    let m
    while ((m = re.exec(src))) out.add(`${method} ${normalizePath(m[1])}`)
  }
  return out
}

// ---------------------------------------------------------------- 读盘盘点

const rawView = fs.readFileSync(VIEW_SRC, 'utf8')
const rawApi = fs.readFileSync(API_SRC, 'utf8')
const rawRouter = fs.readFileSync(ROUTER_SRC, 'utf8')

const view = stripComments(rawView)
const api = stripComments(rawApi)

const backendEndpoints = collectBackendEndpoints(rawRouter)
const apiCalls = collectApiCalls(api)

const literals = collectStringLiterals(view)
const longest = literals.reduce((a, b) => (b.length > a.length ? b : a), '')

const apiExports = collectExportedFunctions(api)
const viewImports = collectImportedNames(view, '@\\/api\\/memory')
const viewUnusedExports = apiExports.filter((n) => !isCalled(view, n))
const viewImportedMissing = [...viewImports].filter((n) => !apiExports.includes(n))

const handlerBodies = {}
for (const name of WRITE_HANDLERS) handlerBodies[name] = extractFunctionBody(view, name)

const templatePart = view.slice(0, view.indexOf('<script'))
const scriptPart = view.slice(view.indexOf('<script'))

console.log('长期记忆真伪门禁 —— 盘面读数')
console.log(`  视图  ${path.relative(ROOT, VIEW_SRC)}`)
console.log(`  api   ${path.relative(ROOT, API_SRC)}`)
console.log(`  router ${path.relative(ROOT, ROUTER_SRC)}`)
console.log(
  `  后端端点 ${backendEndpoints.size} 个：${[...backendEndpoints].sort().join(' | ') || '(无)'}`,
)
console.log(
  `  api 调用 ${apiCalls.size} 处：${[...apiCalls].sort().join(' | ') || '(无)'}`,
)
console.log(
  `  api 导出 ${apiExports.length} 个：${apiExports.join(', ') || '(无)'}`,
)
console.log(
  `  视图导入 ${viewImports.size} 个：${[...viewImports].join(', ') || '(无)'}`,
)
console.log(`  最长字符串字面量 ${longest.length} 字符`)
for (const name of WRITE_HANDLERS) {
  const b = handlerBodies[name]
  const hasCatch = b ? /\bcatch\s*\(/.test(b) : false
  console.log(
    `  handler ${name.padEnd(22)} ${b ? 'FOUND' : 'MISSING'}${b ? `  ${b.length} B  catch=${hasCatch}` : ''}`,
  )
}
console.log(`  md.render 在视图里 ${isCalled(view, 'md.render') ? 'YES' : 'NO'}`)
console.log(
  `  后端下发字段被消费：${BACKEND_OWNED.map((k) => `${k}=${view.includes(k) ? 'YES' : 'NO'}`).join('  ')}`,
)

if (REPORT_ONLY) process.exit(0)

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

// ★ A 契约对账（双向）
check('A1 后端每个端点都被前端 api 层覆盖', () => {
  const missing = [...backendEndpoints].filter((e) => !apiCalls.has(e))
  assert(
    missing.length === 0,
    `后端有 ${missing.length} 个端点前端没人调：${missing.join(' | ')} —— 这些能力在界面上永远用不到`,
  )
})
check('A2 前端 api 层不调用后端不存在的端点', () => {
  const extra = [...apiCalls].filter((e) => !backendEndpoints.has(e))
  assert(
    extra.length === 0,
    `前端在调后端没有的端点：${extra.join(' | ')} —— 运行时只会 404`,
  )
})

// ★ B 视图真的在用
check('B1 视图 import 了 @/api/memory', () => {
  assert(viewImports.size > 0, '视图没有从 @/api/memory 导入任何东西')
})
check('B2 api 层每个导出函数都被视图**调用**（不是只 import）', () => {
  assert(
    viewUnusedExports.length === 0,
    `api 层导出了但视图没调用：${viewUnusedExports.join(', ')} —— 接线了但不工作，零报错零测试红`,
  )
})
check('B3 视图导入的名字都在 api 层真实存在', () => {
  assert(
    viewImportedMissing.length === 0,
    `视图导入了 api 层不存在的名字：${viewImportedMissing.join(', ')}`,
  )
})

// ★ C 没有本地假数据
check(`C1 视图里没有超长字符串字面量（<= ${MAX_STRING_LITERAL} 字符）`, () => {
  assert(
    longest.length <= MAX_STRING_LITERAL,
    `最长字面量 ${longest.length} 字符，超过 ${MAX_STRING_LITERAL}：${JSON.stringify(longest.slice(0, 60))}… —— 假画面/假画像就是这样一大坨字面量`,
  )
})
for (const marker of FAKE_PAGE_MARKERS) {
  check(`C2 不再有「本地自造的记忆/日志」标识符：${marker}`, () => {
    assert(
      !new RegExp(`(?<![\\w$.])${marker}(?![\\w$])`).test(view),
      `视图里又出现了 ${marker} —— 那是"本地自造数据"的形态，真数据只从后端来`,
    )
  })
}

// ★ D 五个写口都真的发请求
for (const name of WRITE_HANDLERS) {
  check(`D 写口真的发请求：${name}`, () => {
    const body = handlerBodies[name]
    assert(body, `没有找到 ${name} 的函数体 —— 若已改名，本组断言就静默失效了，请同步更新 WRITE_HANDLERS`)
    const called = apiExports.filter((fn) => isCalled(body, fn))
    assert(
      called.length > 0,
      `${name} 内没有任何 @/api/memory 调用 —— 它把自己变成了只改本地状态的假操作`,
    )
  })
}

// ★ E 失败路径必须回写界面状态
for (const outlet of ERROR_OUTLETS) {
  check(`E1 失败出口存在且在模板里被渲染：${outlet}`, () => {
    assert(
      new RegExp(`(?<![\\w$.])${outlet}(?![\\w$])`).test(scriptPart),
      `脚本里没有 ${outlet} 这个失败状态`,
    )
    assert(
      new RegExp(`(?<![\\w$.])${outlet}(?![\\w$])`).test(templatePart),
      `${outlet} 没有在模板里被消费 —— 失败状态没人渲染，等于失败被静默吞掉`,
    )
  })
}
for (const name of WRITE_HANDLERS) {
  check(`E2 写口有失败出口：${name}`, () => {
    const body = handlerBodies[name]
    assert(body, `${name} 不存在`)
    assert(/\bcatch\s*\(/.test(body), `${name} 没有 catch —— 失败会变成 unhandled rejection`)
    const tail = body.slice(body.search(/\bcatch\s*\(/))
    assert(
      /message\.(error|warning)\s*\(/.test(tail) ||
        /(loadError|saveError|logsError)\s*\.value\s*=/.test(tail),
      `${name} 的 catch 里既没报错也没写回状态 —— 失败没有被送到任何出口`,
    )
  })
}

// ★ F v-html 安全
check('F1 正文渲染走 markdown-it 且显式 html:false', () => {
  // ★ 这一条排在最前：`html: true` 是最凶的那一档（等于把用户内容当代码执行），
  //   若排在"找不到 html: false"之后，报出来的文案会指向另一个方向
  //   —— 实测就是这样（反向注入 F1 第一次红的文案说的是"没有看到 html: false"）。
  assert(
    !/html\s*:\s*true/.test(view),
    '出现了 html: true —— 记忆内容（手写/导入/AI 归纳）三条来路都不可信，允许裸 HTML 就是给 v-html 递刀子',
  )
  assert(isCalled(view, 'md.render'), '视图里没有 md.render(...) —— 正文不是用 markdown-it 渲染的')
  assert(
    /new\s+MarkdownIt\s*\(\s*\{[^}]*html\s*:\s*false/.test(view),
    '没有看到 new MarkdownIt({ html: false }) —— 要显式写出来，别依赖库的默认值（默认值会随版本变）',
  )
})
check('F2 v-html 的绑定只有渲染函数，没有直接绑原始数据', () => {
  const bindings = [...view.matchAll(/v-html\s*=\s*"([^"]+)"/g)].map((m) => m[1].trim())
  assert(bindings.length > 0, '找不到任何 v-html 绑定（若已改渲染方式，请同步本断言）')
  const bad = bindings.filter((b) => !/^render|^md\.render/.test(b))
  assert(
    bad.length === 0,
    `v-html 直接绑了非渲染函数：${bad.join(', ')} —— 原始文本未经 markdown 渲染/转义`,
  )
})

// ★ G 失败判据来自后端
check('G1 时间线的"是不是坏消息"用了后端的 is_failure', () => {
  assert(view.includes('is_failure'), '视图没有消费 is_failure —— 失败记录的渲染依据从哪来？')
})
check('G2 前端没有自己列一份失败类型名单', () => {
  assert(
    !/[A-Za-z_]*[Ff]ailure[Kk]ind/.test(view),
    '视图里出现了 failureKind* 之类的标识符 —— 后端新增失败类型时这份名单不会跟着变，一条失败记录会被渲染成正常记录',
  )
})

// ★ H 上限来自后端
check('H1 条数上限取自后端 limits', () => {
  assert(/limits\??\.\s*max_entries/.test(view), '没有看到从 limits.max_entries 取上限')
  assert(
    !/MAX_ENTRIES/.test(view),
    '视图里出现了 MAX_ENTRIES —— 上限是后端判据，前端写一份就是第二份实现',
  )
})

// ★ I 归属不进请求体
check('I 归属字段不进请求体：api 层不得出现 owner_id', () => {
  assert(
    !/owner_id/.test(api),
    'api 层出现了 owner_id —— 归属只能由服务端从身份取，客户端自报就是越权通道',
  )
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n长期记忆真伪门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `长期记忆真伪门禁通过（契约 ${apiCalls.size} 条端点双向对齐 ✓ / 写口 ${WRITE_HANDLERS.length} 个真发请求 ✓ / 失败出口 ${ERROR_OUTLETS.join('+')} ✓）`,
)

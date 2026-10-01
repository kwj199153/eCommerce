#!/usr/bin/env node
/**
 * 追踪链路门禁（L3-3 · 第 351 轮）
 *
 * 钉住「一次请求的 trace 在**前后端 + 两个 HTTP 出口**上都是通的」。
 * 它是**跨端**判据：读 2 个前端源 + 2 个后端源。
 *
 * 为什么值得单独一个门禁（第 350 轮归档报告实测的三段断点）：
 *   ① 前端 `frontend/src` 全文搜 `X-Request-ID|requestId|traceId` —— **0 命中**。
 *      后端早就回写 X-Request-ID，前端从不发、也不读。而且前端有**两个**
 *      HTTP 出口（axios 实例 + SSE 的裸 fetch），只修一个 ⇒ 所有流式对话
 *      那条链路的 trace 永远是断的。
 *   ② 后端 `X-Process-Time-Ms` 只有**总耗时**，没有 DB / LLM 分段 ——
 *      总耗时只说明「慢」，分段才说明「慢在哪」（等数据库还是等模型）。
 *   ③ `main.py` 的 CORSMiddleware **没有 expose_headers** ⇒
 *      跨域部署下浏览器 JS 读不到自定义响应头，①② 做了也白做
 *      （本地同源 dev 下看不出来 —— 这正是它一直没被发现的原因）。
 *
 * 判据分组：
 *   T1  traceId.ts 的导出面 + **零依赖**（它是唯一实现，且被台架以空桩表加载）
 *   T2  request.ts 真引用并**真调用** traceId（防死导入）
 *   T3  request.ts 请求拦截器注入 X-Request-ID（窗口限定在拦截器块内）
 *   T4  request.ts 成功分支读 x-request-id 响应头（窗口限定在成功分支内）
 *   T5  request.ts 错误分支**每一处** toast 都走 withTraceId（逐调用点判数据流）
 *   T6  stream.ts 真引用并注入 X-Request-ID
 *   T7  stream.ts 读 x-request-id，且**不破坏** `请求失败 (${status}) ` 前缀
 *   T8  main.py CORSMiddleware 的 expose_headers 覆盖必需响应头
 *   T9  request_log.py 回写 DB / LLM 分段头，且真的归零 / 清理计时
 *   T10 反向自检：抹掉注入后 T3/T4/T6/T7 的判据必须失配（否则判据恒真）
 *   T11 规模达标：5 个源文件都读到且非空（否则前面判据在空串上恒假）
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *     TRACE_TRACEID_SRC=<副本或空文件>  ⇒ T1 红
 *     TRACE_REQUEST_SRC=<副本或空文件>  ⇒ T2 / T3 / T4 / T5 红
 *     TRACE_STREAM_SRC=<副本或空文件>   ⇒ T6 / T7 红
 *     TRACE_MAIN_SRC=<副本或空文件>     ⇒ T8 红
 *     TRACE_LOG_SRC=<副本或空文件>      ⇒ T9 红
 *
 * 用法：node scripts/check-trace-propagation.cjs   （0 = 通过；1 = 有漂移）
 */

const fs = require('fs')
const path = require('path')

/**
 * 可注入路径（反向注入用副本 / 空源；默认真文件）。
 * ★ 必须逐个可注入：判据扫真文件、注入打在副本上 ⇒ 永远照旧绿（本仓登记形态）。
 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const ROOT = path.resolve(__dirname, '..')
const FE = path.join(ROOT, 'src')
const BE = path.resolve(ROOT, '..', 'backend')

const SRC_TRACE_ID = pick('TRACE_TRACEID_SRC', path.join(FE, 'api', 'traceId.ts'))
const SRC_REQUEST = pick('TRACE_REQUEST_SRC', path.join(FE, 'api', 'request.ts'))
const SRC_STREAM = pick('TRACE_STREAM_SRC', path.join(FE, 'api', 'stream.ts'))
const SRC_MAIN = pick('TRACE_MAIN_SRC', path.join(BE, 'main.py'))
const SRC_LOG = pick('TRACE_LOG_SRC', path.join(BE, 'core', 'middleware', 'request_log.py'))

// ---------------------------------------------------------------- 工具

function read(p) {
  try {
    return fs.readFileSync(p, 'utf8')
  } catch (e) {
    console.log(`  FAIL  读不到源文件：${p}`)
    console.log(`        ${e.code || 'ENOENT'} —— 本门禁靠它做判定，拿不到不许放行`)
    process.exit(1)
  }
}

/** 剥 JS/TS 注释（判据不能被注释骗过 —— 本仓铁律）。 */
function stripComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const c2 = src[i + 1]
    if (c === '/' && c2 === '/') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue }
    if (c === '`' || c === '"' || c === "'") {
      const q = c
      out += c; i++
      while (i < n && src[i] !== q) { if (src[i] === '\\') { out += src[i]; i++ } if (i < n) { out += src[i]; i++ } }
      out += q; i++; continue
    }
    out += c; i++
  }
  return out
}

/** 剥 Python 的 `#` 注释（docstring 保留 —— 判据一律写成**代码形态**，不吃字符串）。 */
function stripPyComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    if (c === '#') { while (i < n && src[i] !== '\n') i++; continue }
    if (c === '"' || c === "'") {
      const q = c
      out += c; i++
      while (i < n && src[i] !== q) { if (src[i] === '\\') { out += src[i]; i++ } if (i < n) { out += src[i]; i++ } }
      out += q; i++; continue
    }
    out += c; i++
  }
  return out
}

/** 取 `a` 与 `b` 之间的片段（`b` 缺省 = 取到文件尾）。找不到 `a` 返回空串。 */
function sliceBetween(src, a, b) {
  const i = src.indexOf(a)
  if (i < 0) return ''
  if (!b) return src.slice(i)
  const j = src.indexOf(b, i + a.length)
  return j < 0 ? src.slice(i) : src.slice(i, j)
}

/** 取出 `callee(` 起、括号配平为止的完整调用串（逐调用点判数据流用）。 */
function callsOf(src, callee) {
  const out = []
  const re = new RegExp(callee.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\(', 'g')
  let m
  while ((m = re.exec(src)) !== null) {
    const start = m.index + m[0].length - 1
    let depth = 0
    let i = start
    for (; i < src.length; i++) {
      if (src[i] === '(') depth++
      else if (src[i] === ')') { depth--; if (depth === 0) break }
    }
    out.push(src.slice(start, Math.min(i + 1, src.length)))
  }
  return out
}

// ---------------------------------------------------------------- 读入被测源

const traceRaw = read(SRC_TRACE_ID)
const reqRaw = read(SRC_REQUEST)
const streamRaw = read(SRC_STREAM)
const mainRaw = read(SRC_MAIN)
const logRaw = read(SRC_LOG)

const traceSrc = stripComments(traceRaw)
const reqSrc = stripComments(reqRaw)
const streamSrc = stripComments(streamRaw)
const mainSrc = stripPyComments(mainRaw)
const logSrc = stripPyComments(logRaw)

// ---------------------------------------------------------------- 判据（纯函数，供 T10 反向自检复用）

/** 请求头赋值形态：`headers['X-Request-ID'] =` */
const RE_XRID_SET = /\[['"]X-Request-ID['"]\]\s*=/
/** 响应头读取形态：任意处出现 `'x-request-id'` 字面量 */
const RE_XRID_READ = /['"]x-request-id['"]/
/** stream.ts 的失败文案前缀（既有契约，被 check-chat-failure-path.cjs 逐字引用） */
const FAIL_PREFIX = '请求失败 (${response.status}) ${detail}'

const hasXRequestIdInject = (t) => RE_XRID_SET.test(t)
const hasXRequestIdRead = (t) => RE_XRID_READ.test(t)
const keepsFailPrefix = (t) => t.includes(FAIL_PREFIX)

// 窗口：三个块必须各自限定，不能在全文件里找（否则别处同形调用会旁路满足 ⇒ 假绿）
const reqInterceptorBlock = sliceBetween(reqSrc, 'request.interceptors.request.use(', '// ====== 响应拦截器')
const okBlock = sliceBetween(reqSrc, '(response: AxiosResponse) => {', '\n    return data')
const errBlock = sliceBetween(reqSrc, 'async (error) => {', '// ====== 便捷方法')
const sseHeaderBlock = sliceBetween(streamSrc, 'const headers: Record<string, string> = {', 'const fullUrl')
const sseFailBlock = sliceBetween(streamSrc, 'if (!response.ok) {', 'if (!response.body)')
const dispatchBlock = sliceBetween(logSrc, 'async def dispatch(', undefined)
const corsBlock = (() => {
  const i = mainSrc.indexOf('CORSMiddleware,')
  if (i < 0) return ''
  const j = mainSrc.indexOf('\n)', i)
  return j < 0 ? mainSrc.slice(i) : mainSrc.slice(i, j)
})()

// ---------------------------------------------------------------- 判定框架

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) }
  catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

// ---------------------------------------------------------------- T1

check('T1 traceId.ts：唯一实现的导出面齐全，且**零依赖**', () => {
  for (const fn of ['newTraceId', 'rememberTraceId', 'withTraceId']) {
    assert(
      new RegExp(`export\\s+function\\s+${fn}\\b`).test(traceSrc),
      `缺 export function ${fn} —— 两个 HTTP 出口靠它共用一份生成规则`
    )
  }
  // ★ 零依赖是**硬契约**：check-chat-failure-path.cjs 以**空桩表**加载这个文件
  //   （`loadTs(P_TRACE_ID, {})`），任何 import 都会让它直接抛。
  assert(
    !/^\s*import\s/m.test(traceSrc),
    'traceId.ts 出现了 import —— 它必须零依赖（台架用空桩表加载它）'
  )
})

// ---------------------------------------------------------------- T2

check('T2 request.ts 真引用并**真调用** traceId（防死导入）', () => {
  assert(/from\s+['"]@\/api\/traceId['"]/.test(reqSrc), 'request.ts 没有 import @/api/traceId')
  assert(/newTraceId\s*\(/.test(reqSrc), 'import 了却从不调用 newTraceId ⇒ 死导入')
  assert(/rememberTraceId\s*\(/.test(reqSrc), 'import 了却从不调用 rememberTraceId ⇒ 死导入')
  assert(/withTraceId\s*\(/.test(reqSrc), 'import 了却从不调用 withTraceId ⇒ 死导入')
})

// ---------------------------------------------------------------- T3

check('T3 request.ts 请求拦截器注入 X-Request-ID', () => {
  assert(reqInterceptorBlock.length > 0, '定位不到请求拦截器块（锚点失效必须 FAIL，不许放行）')
  assert(
    hasXRequestIdInject(reqInterceptorBlock),
    '请求拦截器没有注入 X-Request-ID ⇒ 服务端日志有 ID、用户看到的报错没有'
  )
})

// ---------------------------------------------------------------- T4

check('T4 request.ts 成功分支读 x-request-id 响应头（在 return data 之前）', () => {
  assert(okBlock.length > 0, '定位不到响应成功分支块（锚点失效必须 FAIL）')
  assert(
    hasXRequestIdRead(okBlock),
    '成功分支没读 x-request-id —— 且必须在 `return data` 之前读：'
    + '这里返回的是 data 不是 response，出了这个函数就拿不到响应头了'
  )
})

// ---------------------------------------------------------------- T5

check('T5 request.ts 错误分支每一处 toast 都走 withTraceId', () => {
  assert(errBlock.length > 0, '定位不到响应错误分支块（锚点失效必须 FAIL）')
  const calls = [
    ...callsOf(errBlock, 'message.error'),
    ...callsOf(errBlock, 'message.warning'),
  ]
  assert(
    calls.length >= 5,
    `错误分支只找到 ${calls.length} 处 toast（应 ≥ 5：403/404/429/500/default）`
    + ' —— 找不到就等于这条判据在空集上恒真'
  )
  const unwrapped = calls.filter((c) => !c.includes('withTraceId('))
  assert(
    unwrapped.length === 0,
    `以下 toast 没带追踪 ID（用户无法回报可定位的 ID）：\n        `
    + unwrapped.map((c) => c.replace(/\s+/g, ' ').slice(0, 90)).join('\n        ')
  )
})

// ---------------------------------------------------------------- T6

check('T6 stream.ts（第二个出口）真引用并注入 X-Request-ID', () => {
  assert(/from\s+['"]@\/api\/traceId['"]/.test(streamSrc), 'stream.ts 没有 import @/api/traceId')
  assert(/newTraceId\s*\(/.test(streamSrc), 'import 了却从不调用 newTraceId ⇒ 死导入')
  assert(sseHeaderBlock.length > 0, '定位不到 streamSSE 的请求头块（锚点失效必须 FAIL）')
  assert(
    hasXRequestIdInject(sseHeaderBlock),
    'SSE 出口没有注入 X-Request-ID ⇒ 所有流式对话的 trace 永远是断的'
  )
})

// ---------------------------------------------------------------- T7

check('T7 stream.ts 读 x-request-id，且**不破坏**既有失败文案前缀', () => {
  assert(sseFailBlock.length > 0, '定位不到 `!response.ok` 分支（锚点失效必须 FAIL）')
  assert(
    hasXRequestIdRead(sseFailBlock),
    'SSE 失败分支没读 x-request-id —— 用户拿到的报错无法与服务端日志对上'
  )
  assert(
    keepsFailPrefix(streamSrc),
    `失败文案前缀被改动了。它是**既有契约**：${FAIL_PREFIX}`
    + '（check-chat-failure-path.cjs 逐字引用它）⇒ 追踪 ID 只能加在 detail **之后**'
  )
})

// ---------------------------------------------------------------- T8

check('T8 main.py 的 CORSMiddleware 暴露追踪响应头（否则跨域下前端读不到）', () => {
  assert(corsBlock.length > 0, 'main.py 里定位不到 CORSMiddleware 配置块')
  assert(
    /expose_headers\s*=/.test(corsBlock),
    'CORSMiddleware 没有 expose_headers ⇒ 跨域部署下 JS 读不到 X-Request-ID / X-*-Time-Ms'
  )
  for (const h of ['X-Request-ID', 'X-Process-Time-Ms', 'X-DB-Time-Ms', 'X-LLM-Time-Ms']) {
    assert(
      corsBlock.includes(`"${h}"`),
      `expose_headers 缺 ${h} —— 后端回写了但浏览器读不到`
    )
  }
})

// ---------------------------------------------------------------- T9

check('T9 request_log.py 回写 DB / LLM 分段头，且真的归零与清理计时', () => {
  assert(dispatchBlock.length > 0, 'locate 不到 request_log 的 dispatch（锚点失效必须 FAIL）')
  // ★ 判据写成**代码形态**：`response.headers["X-DB-Time-Ms"] =`。
  //   只判「源码里含 X-DB-Time-Ms」会被 docstring 骗过（本仓登记形态：假绿）。
  const setNames = new Set(
    [...dispatchBlock.matchAll(/response\.headers\[["'](X-[\w-]+)["']\]\s*=/g)].map((m) => m[1])
  )
  for (const h of ['X-Request-ID', 'X-Process-Time-Ms', 'X-DB-Time-Ms', 'X-LLM-Time-Ms']) {
    assert(setNames.has(h), `dispatch 没有回写 ${h}（现有：${[...setNames].join(', ')}）`)
  }
  assert(/\bstart_timing\s*\(\)/.test(dispatchBlock), 'dispatch 没有调 start_timing() ⇒ 分段永远为 0')
  assert(/\bclear_timing\s*\(\)/.test(dispatchBlock), 'dispatch 没有调 clear_timing() ⇒ keep-alive 会把耗时串到下一个请求')
})

// ---------------------------------------------------------------- T10

check('T10 反向自检：抹掉注入后 T3/T4/T6/T7 的判据必须失配（判据不许恒真）', () => {
  assert(
    hasXRequestIdInject(reqInterceptorBlock)
      && !hasXRequestIdInject(reqInterceptorBlock.replace(RE_XRID_SET, '')),
    'T3 的判据在抹掉注入后依旧成立 ⇒ 它判的不是「有没有注入」'
  )
  assert(
    hasXRequestIdRead(okBlock) && !hasXRequestIdRead(okBlock.replace(/x-request-id/gi, '')),
    'T4 的判据在抹掉响应头读取后依旧成立 ⇒ 恒真'
  )
  assert(
    hasXRequestIdInject(sseHeaderBlock)
      && !hasXRequestIdInject(sseHeaderBlock.replace(RE_XRID_SET, '')),
    'T6 的判据在抹掉注入后依旧成立 ⇒ 恒真'
  )
  assert(
    keepsFailPrefix(streamSrc)
      && !keepsFailPrefix(streamSrc.replace(FAIL_PREFIX, '流式请求失败')),
    'T7 的前缀判据在改掉前缀后依旧成立 ⇒ 它守不住那个契约'
  )
})

// ---------------------------------------------------------------- T11

check('T11 规模达标：5 个源文件都读到且非空（防「路径写错 ⇒ 空集 ⇒ 恒绿」）', () => {
  const sizes = [
    ['traceId.ts', traceSrc, 400],
    ['request.ts', reqSrc, 4000],
    ['stream.ts', streamSrc, 2000],
    ['main.py', mainSrc, 5000],
    ['request_log.py', logSrc, 3000],
  ]
  for (const [name, src, min] of sizes) {
    assert(src.length >= min, `${name} 只有 ${src.length} 字符（应 ≥ ${min}）—— 扫描面可疑`)
  }
  const files = new Set([SRC_TRACE_ID, SRC_REQUEST, SRC_STREAM, SRC_MAIN, SRC_LOG])
  assert(files.size === 5, '五个源路径出现重复 ⇒ 有判据其实在读同一个文件')
})

// ---------------------------------------------------------------- 输出

let failed = 0
for (const [name, err] of results) {
  if (err) {
    failed++
    console.log(`FAIL  ${name}`)
    console.log(`        ${err}`)
  } else {
    console.log(`PASS  ${name}`)
  }
}
console.log(`\n---- ${results.length - failed}/${results.length} 通过 ----`)
if (failed) {
  console.log('追踪链路的任何一段断了，用户回报的 ID 都无法定位到服务端日志。')
  process.exit(1)
}

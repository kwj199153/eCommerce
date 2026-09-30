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
 *   D「真跑一遍：后端回空响应时**必须显式失败**」—— 见文件末尾 `checkLive()`。
 *   E「声明表不许撒谎」（#746）：`TOOL_DATA_SOURCE` ↔ 注册表 ↔ 源码判据三方对账 ——
 *     完整性（每个注册 id 必须登记来源）+ 真实性（声明 backend 的必须真是真调用，
 *     声明 local-mock 的必须真的不是，声明 backend-then-mock 的必须确实调了后端）。
 *     E5「动态真调用不许成为孤儿」：真调用若写在**模块级 helper** 体内
 *     （`tryBackendBlueOcean` 那种），按「执行器 body 区间」归属会整个漏掉 ——
 *     而且是**静默**漏掉（门禁照绿，只是把它归进了 mock 计数）⇒ 必须做一跳归属，
 *     且文件里每一条 `await import('@/api/*')` 都必须有归属。
 *   F「注册表里不允许有**无入口**的 id」（#746）：#740 实测发现 13 个执行器没有任何入口
 *     —— 它们挂着的 `AdDashboardConfig` / `ReviewConfig` / `IntelBoardConfig` 三个面板
 *     **声明了 emits 却一次都不 emit**；再往下查，`ListingBoard` 也接了 `@startAnalysis`
 *     却从不 emit，而它排在 4 个 listing 配置之前 ⇒ 那 4 个配置被永久遮蔽。
 *     这些执行器编译得通、测试过得，只是永远跑不到；危害不是报错，而是
 *     「留在 `mock/` 里等着被重新 import 成第二条假数据路径」。
 *     F 从**源码形态**复算可达性（工具目录 → 模板分支 → 绑定面板是否 emit），不是名单；
 *     确有未接线者必须写进 `REACH_WAIVER` 并写明去向，且**只许减不许增**。
 *     ⚠️ 本判据用的是**目录级**口径（id 在不在某个 `AGENT_TOOLS[agent]` 里）。
 *        还有更严的**渲染级**口径（顶部工具栏是否真的对该 Agent 渲染 —— 竞品监控员
 *        刻意不展示工具卡）。
 *        ★ 第 255 轮（#918）已按渲染级口径把竞品监控员那 **12 个 id 整体退役**
 *          （连同 7 个配置面板 / 6 个结果卡 / 6 个 mock 执行器）—— 因为它们的
 *          三个可能落点（顶部工具栏 / `AGENT_DEFAULT_TOOL` / `provide(
 *          'currentSelectedTool')` 的消费者）**全部为空**。⇒ 两种口径在**工具执行器**上
 *          不再有差集。
 *     ★ 第 261 轮新增 **F4~F6**：把口径从**工具执行器**扩展到**结果卡**（渲染级的另一半）——
 *       `CompetitorIntelEvidence.vue` 实测是「前端有卡、后端永不下发」的死卡，而 F1~F3
 *       只看 `mock/toolExecutors.ts`、跨端 pytest 只钉了 `review_report` 一个键
 *       ⇒ 这类死码过去**没有任何判据看得见**（详见 F4~F6 注释）。
 *   G「被删执行器的活路径不能失守」（#744 迁移）：广告诊断的工具卡路径已删，
 *     它现在只有对话分支 `chat/replies/adAnalysis.ts` 这一条活路径 ⇒ 在本门禁里钉住。
 *     ★ 第 166 轮 #732 补：A 只问「有没有调 @/api/*」，而 fail-closed 端点照样返回
 *       HTTP 200 + 空信封 ⇒ 「诚实地报告查不到」在 A 眼里与「真链路可用」一模一样。
 *
 * 怎么跑：node scripts/check-tool-reality.cjs
 *   加 --report 只打印分类表、不做判定（用于盘点）。
 *
 * 反向注入（证明本门禁不是空跑）：
 *   ① TOOL_EXECUTORS_SRC=<一份把 4 个里的某个 api 调用删掉的副本> node scripts/check-tool-reality.cjs
 *      —— 断言 A 必须变红。见 .workbuddy/probes/_r128s_bad_executors.ts
 *   ② 第 255 轮（#918）改过 F0 的三条自检下限与 `MOCK_LIMIT`，逐条注入验证过：
 *      · 往 F0 的**锚点清单**里塞一个不存在的 id ⇒ F0 转红（证明锚点断言是活的）；
 *      · 承载下限抬到 9999 ⇒ F0 转红（证明下限真的在判）；
 *      · 把已退役的 `price-track` 加回目录 + 注册表 ⇒ **B / E1 / F1 三条同时转红**
 *        （这就是「F1 是防复发判据」的实证）；
 *      · 基线必须 34/34（否则上面的结论都不成立）。
 *      手法：门禁副本 + `INJ_ROOT` 指向 src 副本树（不碰生产文件）。
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const SRC = process.env.TOOL_EXECUTORS_SRC
  ? path.resolve(process.env.TOOL_EXECUTORS_SRC)
  : path.join(ROOT, 'src', 'mock', 'toolExecutors.ts')

/** ★ A：已接线为真调后端的执行器，永久钉死（只许加不许减） */
const MUST_BE_REAL = [
  // 第 128 轮 · P0-2 批 1
  // ★ #744（2026-09-18）起 `executeAdDiagnosis` 已删除：「广告诊断」这个工具由
  //   `AdDashboardConfig` 接管（按 currentToolId 映射 Tab，直调 @/api/adAnalysis），
  //   对话路径在 `composables/chat/replies/adAnalysis.ts` 直调 `diagnoseAdAccount`。
  //   注册表里那条**没有任何入口** ⇒ 属于 #740 清掉的「假数据坟墓」。
  //   它的活路径改由断言 G 钉住（判据迁移，不是消失）。
  'executeCompetitorAnalysis',
  'executeSEOAudit',
  'executeBulletGen',
  // 批 2（第 164 轮 #727）：订单追踪改真调用后一并钉死 ——
  // 原实现与后端 `agent_cs._mock_order_info` 是同一份谎话的两处实现。
  'executeOrderTrack',
  // 第 166 轮 #732：真调用实测 6 个，此前只具名钉死 5 个 —— 补上这一个。
  'executeStaticAssetGen',
]

/** ★ B：允许仍为本地 mock 的 execute* 数量上限（只许减不许增）
 *
 * 基线不是手写的，是**现算**的 —— 手写的期望值已经错过三次：
 *   git show HEAD:frontend/src/mock/toolExecutors.ts > /tmp/head.ts   （Windows 下用项目内路径）
 *   TOOL_EXECUTORS_SRC=<该副本> node scripts/check-tool-reality.cjs --report
 * 实测：第 128 轮前 = 36 个 execute*，真调用 1 / **mock 35**；
 *       第 128 轮 P0-2 批 1 接线后 = 真调用 5 / **mock 31**（本轮消掉 4 个）。
 *       批 2（第 164 轮 #727）`order-track` 接线后 = 真调用 6 / **mock 30**。
 *       #744（第 170 轮）删掉 13 个无入口执行器后 = 执行器 23，真调用 6 / **mock 17**。
 *       #918（第 255 轮）删掉竞品监控员那 6 个**不可达**执行器后 = 执行器 17，
 *         真调用 6 / **mock 11**。（为什么该删：`currentSelectedTool` 对竞品监控员
 *         没有任何非 null 写入路径 ⇒ 这 6 个执行器永远不会被调用；
 *         同批删掉的还有它们的工具定义 / 配置面板 / 结果组件。）
 *         （真调用 5 → 6 **不是新增接线**，而是本轮修了一个判据盲点：
 *          `executeBlueOceanAnalysis` 的真调用藏在 `tryBackendBlueOcean()` 的
 *          **动态** `await import('@/api/productResearch')` 里，旧的 `collectApiImports`
 *          只看静态 import ⇒ 它被误判成 mock 至今。）
 */
const MOCK_LIMIT = 11

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

/**
 * ★ #746 补：执行器体内的**动态** `await import('@/api/...')`。
 * 盲点实例：`executeBlueOceanAnalysis` 把真调用包在 `tryBackendBlueOcean()` 里，
 * 用 `await import('@/api/productResearch')` 延迟加载 ⇒ 只认静态 import 的旧判据
 * 把它整个判成「本地 mock」，于是「这条路径到底有没有接后端」在门禁里是隐形的。
 * 只收 `@/api/`，不收 `@/mock/*`（后者才是真正的本地兜底）。
 */
function collectDynamicApiImports(src) {
  const out = []
  const re = /await\s+import\(\s*['"]@\/api\/[^'"]+['"]\s*\)/g
  let m
  while ((m = re.exec(src))) out.push({ index: m.index, text: m[0] })
  return out
}

/**
 * ★ #746 补：文件里的**模块级 helper**（`const NAME = async (…) => {…}` / `function NAME(…) {…}`）。
 *
 * 存在的原因：真调用常常**不在执行器体内**，而在它调用的小工具函数里。实例：
 *   `executeBlueOceanAnalysis` → `const fromBackend = await tryBackendBlueOcean(params)`
 *   `tryBackendBlueOcean`      → `const { analyzeBlueOcean } = await import('@/api/productResearch')`
 * 只按执行器 body 的字符区间归属动态 import，这条真调用就永久隐形 —— 且是静默的：
 * 门禁照样绿，只是把 blue-ocean 归进了 mock 计数（本轮第一次改造的实测后果）。
 * 排除 `execute*`：那些是断言对象本身，不该被当成别人的 helper。
 */
function collectModuleFns(src) {
  const out = []
  const push = (name, at) => {
    if (/^execute/.test(name)) return
    const i = src.indexOf('{', at)
    if (i < 0) return
    const c = matchBrace(src, i)
    if (c < 0) return
    out.push({ name, start: i, end: c })
  }
  let m
  const reFn = /(?:^|\n)\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(/g
  while ((m = reFn.exec(src))) push(m[1], m.index + m[0].length)
  const reConst = /(?:^|\n)\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(/g
  while ((m = reConst.exec(src))) push(m[1], m.index + m[0].length)
  return out
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
    out.push({
      name,
      body: close < 0 ? src.slice(i) : src.slice(i, close + 1),
      bodyStart: i,
    })
  }
  return out
}

// ---------------------------------------------------------------- 判定

const raw = fs.readFileSync(SRC, 'utf8')
const code = stripComments(raw)
const apiNames = collectApiImports(code)
const executors = collectExecutors(code)
// ★ #746：动态 `await import('@/api/...')` 也是真调用 —— 归属到所属执行器。
//   归属口径 = 「执行器 body 内**直接**出现」**或**「执行器 body 内**调用到**的模块级 helper
//   体内出现」（一跳）。之所以必须有一跳：
//       export const executeBlueOceanAnalysis = … => { const r = await tryBackendBlueOcean(p) }
//       const tryBackendBlueOcean = … => { await import('@/api/productResearch') }   ← 在 body 之外
//   只按 body 区间归属会把它整个漏掉，且不报任何错。
const dynApi = collectDynamicApiImports(code)
const moduleFns = collectModuleFns(code)

const rows = []
for (const { name, body, bodyStart } of executors) {
  const apiCalls = [...apiNames].filter((fn) => new RegExp('(?<![\\w$.])' + fn + '\\s*\\(').test(body))
  const bodyEnd = bodyStart + body.length
  const dynHits = dynApi.filter((d) => d.index >= bodyStart && d.index < bodyEnd)
  // 一跳：body 里调用到的模块级 helper（非 execute*）体内若含动态 @/api 调用，也算本执行器真调了后端
  for (const fn of moduleFns) {
    if (!new RegExp('(?<![\\w$.])' + fn.name + '\\s*\\(').test(body)) continue
    for (const d of dynApi) {
      if (d.index >= fn.start && d.index < fn.end && !dynHits.includes(d)) dynHits.push(d)
    }
  }
  const dynamicApi = dynHits.map((d) => d.text.replace(/\s+/g, ' '))
  rows.push({
    name,
    apiCalls,
    dynamicApi,
    dynIndexes: dynHits.map((d) => d.index),
    real: apiCalls.length > 0 || dynamicApi.length > 0,
    random: /Math\.random\s*\(/.test(body),
    delay: /setTimeout\s*\(/.test(body),
    bytes: Buffer.byteLength(body, 'utf8'),
  })
}

const mocks = rows.filter((r) => !r.real)
const real = rows.filter((r) => r.real)

console.log(`工具执行真伪门禁 —— 源文件 ${path.relative(ROOT, SRC)}`)
console.log(`  共 ${rows.length} 个 execute*：真调用 ${real.length} / 本地 mock ${mocks.length}`)
console.log(`  @/api/* 命名导入：${[...apiNames].join(', ') || '(无)'}`)
console.log(`  @/api/* 动态导入：${[...new Set(dynApi.map((d) => d.text.replace(/\s+/g, ' ')))].join(' | ') || '(无)'}`)
console.log(`  模块级 helper：${moduleFns.length} 个（用于一跳归属 ⇒ 动态真调用不会被漏成 mock）\n`)

if (REPORT_ONLY || process.env.TOOL_EXECUTORS_REPORT === '1') {
  console.log('  真调用：')
  for (const r of real) {
    const how = [...r.apiCalls, ...r.dynamicApi.map((d) => '动态 ' + d)].join(', ')
    console.log(`    REAL  ${r.name.padEnd(32)} ${how}`)
  }
  console.log('  本地 mock：')
  for (const r of mocks) {
    const flags = [r.random ? 'Math.random' : '', r.delay ? 'setTimeout' : ''].filter(Boolean).join('+')
    console.log(`    MOCK  ${r.name.padEnd(32)} ${String(r.bytes).padStart(6)} B  ${flags}`)
  }
  process.exit(0)
}

// ---------------------------------------------------------------- 断言 D 之前的静态断言

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


// ---------------------------------------------------------------- 断言 D（真跑）

// ★ 第 166 轮 · #732：把「真调用」判据从「**发了请求**」升级为「**拿不到数据必须显式失败**」。
//
//   痛点：`fail-closed` 端点**照样返回 HTTP 200 + 空信封**（本项目三个端点刚这么做）。
//   旧的断言 A 只看函数体里有没有 `@/api/*` 调用 ⇒ 「诚实地报告查不到」与
//   「真链路可用」在它眼里**长得一模一样**。
//
//   实测（`.workbuddy/probes/o732_live.txt`，喂空响应真跑）当场抓出 3 个执行器：
//     · `executeAdDiagnosis` / `executeBulletGen` 返回**没有任何失败信号**的空壳
//       （`{type,params}` / `{bullets:[], total_characters:0}`）⇒ 结果卡会渲染成
//       「诊断完成、无任何指标」「五点描述：0 条」，用户与「后端真的没数据」无法区分；
//     · `executeStaticAssetGen` 把「**没有任务号**（提交就没成功）」错报成
//       「任务仍在后台执行（已等待约 4 分钟）」⇒ 用户会去「我的任务」里找一个不存在的编号。
//
//   手法复用 `scripts/check-tool-adapters.cjs`：devDependency `typescript` 的
//   `ts.transpileModule` + `vm` 沙箱（**零新依赖**）；适配层**真加载**（它是零 import
//   的纯函数模块），`@/api/*` 一律桩成「HTTP 200 + 空响应」。

const EXEC_SRC = process.env.TOOL_EXECUTORS_SRC
  ? path.resolve(process.env.TOOL_EXECUTORS_SRC)
  : path.join(ROOT, 'src', 'mock', 'toolExecutors.ts')
const ADAPTER_SRC = process.env.TOOL_ADAPTERS_SRC
  ? path.resolve(process.env.TOOL_ADAPTERS_SRC)
  : path.join(ROOT, 'src', 'utils', 'toolResultAdapters.ts')

/** 空响应真跑用例：执行器名 → 入参。必须与 `MUST_BE_REAL` **一一对应**（见 D-0）。 */
const LIVE_CASES = {
  executeCompetitorAnalysis: { asins: ['B0AAAAAAAA', 'B0BBBBBBBB'], dimensions: ['price'] },
  executeOrderTrack: { order_id: '112-1234567-8901234' },
  executeBulletGen: { product_name: 'Manual Coffee Grinder', style: 'benefit' },
  // ★ 必须带全 Listing 文本，否则会在**入参校验**处就抛错 —— 那条 D 用例只测到入参分支（弱通过）。
  executeSEOAudit: {
    listing_title: 'Manual Coffee Grinder, Ceramic Burr',
    listing_bullets: ['A', 'B', 'C', 'D', 'E'],
    listing_description: 'A compact manual coffee grinder.',
  },
  executeStaticAssetGen: { productName: 'Manual Coffee Grinder', imageTypes: ['三视图'], quantity: 1 },
}

/**
 * ★ 判据本体（**唯一实现**）：空响应下什么样的返回值算「显式」。
 * 返回 `''` = 合格；否则返回不可接受的理由。
 * 抽成函数是为了让正向对照能用**同一份**判据（否则对照本身可能是第二份实现）。
 */
function emptyResponseVerdict(out) {
  if (out && typeof out === 'object') {
    if (out.success === false) return ''
    if (out.found === false) return ''
    if (out.degraded === true) return ''
    if (typeof out.error === 'string' && out.error.length > 0) return ''
  }
  return '没有给出任何「显式失败信号」（success:false / found:false / degraded:true / error 非空）'
}

/**
 * ★ 判据 D-2（第 166 轮 · #732 补）：**声称「有任务在后台跑」，就必须带出可核验的任务号**。
 *
 * 反例（反向注入 INJ-D2 实测）：`executeStaticAssetGen` 在没有任务号时仍返回
 * 「任务仍在后台执行（已等待约 4 分钟）… 可稍后在「我的任务」里查看结果」——
 * 用户会去「我的任务」里找一个**根本不存在的编号**（归因错方向）。
 * 只判「有没有显式失败信号」抓不到它：`degraded: true` 本身就是一个合格信号。
 */
function pendingJobVerdict(out) {
  if (!out || typeof out !== 'object') return ''
  // ★ 判据刻意**只看结构化字段，不看文案** —— 文案会说反话：
  //   修复后的 executeStaticAssetGen 里写着「（后端**未返回**任务编号）」，
  //   用关键词匹配会把它当成「声称有任务」而误报（实测踩到，见 o732_gate3.txt）。
  //   可判的形态是「**声明了有任务在挂**」：出现 pending_job_id / job_status 字段。
  const declaresPending = 'pending_job_id' in out || 'job_status' in out
  if (!declaresPending) return ''
  const ref = out.pending_job_id || out.job_id || out.jobId || ''
  if (typeof ref === 'string' && ref.length > 0) return ''
  return (
    '返回值里声明了「有任务在挂」（出现 pending_job_id / job_status 字段），' +
    '却没给出非空的任务号 ⇒ 用户会去「我的任务」里找一个不存在的编号'
  )
}

const cut = (s, n) => (s && s.length > n ? s.slice(0, n) + `…(+${s.length - n})` : s)

async function checkAsync(name, fn) {
  try {
    await fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}

/** 用 devDependency `typescript` 把 TS 转成 CJS 并在 vm 沙箱里取导出（零新依赖） */
function loadTsModule(srcPath, fakeRequire) {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const code = fs.readFileSync(srcPath, 'utf8')
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 },
    fileName: srcPath,
  }).outputText
  const sandbox = {
    module: { exports: {} },
    exports: {},
    require: fakeRequire,
    console,
    setTimeout,
    clearTimeout,
    Promise,
  }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename: srcPath })
  return sandbox.module.exports
}

/** `@/api/*` 全部返回空响应 —— 这正是 fail-closed 端点的真实形态 */
const EMPTY_API = async () => ({})

async function checkLive() {
  // ★ 依赖缺失**不得静默跳过** —— 跳过 = 这条判据没跑 = 假绿
  check('D0 typescript 可用（否则断言 D 无法执行）', () => {
    try {
      require(path.join(ROOT, 'node_modules', 'typescript'))
    } catch (e) {
      assert(false, `无法加载 devDependency typescript：${e.message}`)
    }
  })
  if (!results[results.length - 1].ok) return

  // ★ 清单对账：防「新钉死为真调用，却没补空响应用例」⇒ 那条等于没判
  check('D0 用例清单与具名清单一一对应', () => {
    const missing = MUST_BE_REAL.filter((n) => !(n in LIVE_CASES))
    const extra = Object.keys(LIVE_CASES).filter((n) => !MUST_BE_REAL.includes(n))
    assert(missing.length === 0, `MUST_BE_REAL 里有 ${missing.length} 个执行器没有空响应用例：${missing.join(', ')}`)
    assert(extra.length === 0, `LIVE_CASES 里有不在 MUST_BE_REAL 的多余条目：${extra.join(', ')}`)
  })

  // ★ 正向对照（元判据）：证明判据**不是恒绿**
  check('D0 正向对照：合成的静默空壳必须被判红', () => {
    assert(
      emptyResponseVerdict({ type: 'ad_diagnosis', params: {} }) !== '' &&
        emptyResponseVerdict({ bullets: [], total_characters: 0 }) !== '',
      '把已知的静默空壳判成了合格 ⇒ 判据写反了/恒绿',
    )
  })
  check('D0 正向对照：声明有任务在挂却没任务号必须被判红', () => {
    assert(
      pendingJobVerdict({ degraded: true, pending_job_id: '', job_status: 'running' }) !== '',
      '声明了 pending 却给空任务号，应判红',
    )
    assert(
      pendingJobVerdict({ degraded: true, pending_job_id: 'job-1', job_status: 'running' }) === '',
      '带出了非空任务号，应判合格',
    )
    assert(
      pendingJobVerdict({ degraded: true, degraded_reason: '未提交成功' }) === '',
      '没声明 pending ⇒ 本条不适用',
    )
    assert(
      pendingJobVerdict({ degraded: true, degraded_reason: '任务仍在后台执行' }) === '',
      '★ 刻意不靠文案判定 —— 文案会说反话（见本函数注释）',
    )
  })
  check('D0 正向对照：显式空状态必须被判合格', () => {
    assert(emptyResponseVerdict({ found: false, order: null }) === '', 'found:false 应判合格')
    assert(emptyResponseVerdict({ degraded: true, degraded_reason: 'x' }) === '', 'degraded:true 应判合格')
    assert(emptyResponseVerdict({ success: false, message: 'x' }) === '', 'success:false 应判合格')
  })

  let adapters
  let EX
  try {
    adapters = loadTsModule(ADAPTER_SRC, () => ({}))
    const fakeRequire = (id) => {
      if (id === '@/utils/toolResultAdapters') return adapters
      if (id.startsWith('@/api/')) return new Proxy({}, { get: () => EMPTY_API })
      if (id === '@/stores/monitorPool') {
        return { useMonitorPoolStore: () => ({ monitors: [], getByShop: () => [], list: () => [] }) }
      }
      if (id === '@/mock/data') return new Proxy({}, { get: () => () => null })
      return new Proxy({}, { get: () => () => null })
    }
    EX = loadTsModule(EXEC_SRC, fakeRequire)
  } catch (e) {
    check('D 沙箱可加载执行器模块', () => assert(false, `加载 ${path.relative(ROOT, EXEC_SRC)} 失败：${e.message}`))
    return
  }

  for (const name of MUST_BE_REAL) {
    await checkAsync(`D 空响应必须显式失败：${name}`, async () => {
      const fn = EX[name]
      assert(typeof fn === 'function', `${name} 未被导出 —— 断言 D 无法执行（不得静默跳过）`)
      const params = LIVE_CASES[name]
      assert(params, `${name} 缺少空响应用例`)
      let out
      try {
        out = await fn(params)
      } catch (e) {
        return // 抛错 = 合格（给的是可执行的下一步，不是一份空报告）
      }
      // ★ 先判 D-2（更具体）：声称后台在跑却没任务号，归因错方向
      const jobBad = pendingJobVerdict(out)
      assert(
        jobBad === '',
        `${name} 在空响应下${jobBad}。实际返回：${cut(JSON.stringify(out), 300)}`,
      )
      const bad = emptyResponseVerdict(out)
      assert(
        bad === '',
        `${name} 在后端返回空响应时${bad} ⇒ 结果卡会渲染成一份「体检通过」的空报告，` +
          `用户与「后端真的没数据」无法区分。实际返回：${cut(JSON.stringify(out), 300)}`,
      )
    })
  }
}


// ---------------------------------------------------------------- 断言 E / F / G（#746）

/** 从一段 TS 里取出某个 `export const X = { ... }` 对象字面量的内容 */
function objectLiteralBody(src, name, label) {
  const re = new RegExp('export const ' + name + '[^{]*\\{([\\s\\S]*?)\\n\\}')
  const m = src.match(re)
  assert(m, `未找到 ${label} 的对象字面量 —— 判据无法执行（不得静默跳过）`)
  return m[1]
}

/**
 * ★ 断言 E：`TOOL_DATA_SOURCE` ↔ 注册表 ↔ 源码判据 **三方双向对账**。
 *
 * 存在的意义：「哪条路径会吐演示数据」此前只活在门禁报告里，代码里不可见。
 * 现在它在 `toolExecutors.ts` 里是一张声明表 ⇒ 必须钉住「**不许撒谎、不许漏登记**」。
 */
const registry = {}
for (const m of objectLiteralBody(code, 'toolExecutors', 'toolExecutors 注册表')
  .matchAll(/'([a-z0-9-]+)'\s*:\s*(execute\w+)/g)) {
  registry[m[1]] = m[2]
}

const declared = {}
for (const m of objectLiteralBody(code, 'TOOL_DATA_SOURCE', 'TOOL_DATA_SOURCE 声明表')
  .matchAll(/'([a-z0-9-]+)'\s*:\s*'(backend|backend-then-mock|local-mock)'/g)) {
  declared[m[1]] = m[2]
}

check('E0 注册表 / 声明表都解析到了（否则本条判据空跑）', () => {
  assert(Object.keys(registry).length >= 15, `注册表只解析出 ${Object.keys(registry).length} 条，解析器可能失效`)
  assert(Object.keys(declared).length >= 15, `声明表只解析出 ${Object.keys(declared).length} 条，解析器可能失效`)
})

check('E1 双向对账：注册表每个 id 都必须声明来源，反之亦然', () => {
  const onlyReg = Object.keys(registry).filter((k) => !(k in declared))
  const onlyDec = Object.keys(declared).filter((k) => !(k in registry))
  assert(onlyReg.length === 0, `这些 id 已注册但**没声明数据来源**：${onlyReg.join(', ')}（漏登记 ⇒ 这条路径的数据性质在代码里不可见）`)
  assert(onlyDec.length === 0, `这些 id 声明了数据来源但**没注册**：${onlyDec.join(', ')}（悬空声明）`)
})

check('E2 声明的取值必须合法', () => {
  const bad = Object.entries(declared).filter(([, v]) => !['backend', 'backend-then-mock', 'local-mock'].includes(v))
  assert(bad.length === 0, `非法取值：${bad.map(([k, v]) => `${k}='${v}'`).join(', ')}`)
})

check('E3 声明不许撒谎：backend / backend-then-mock 必须真调了后端', () => {
  const bad = []
  for (const [id, v] of Object.entries(declared)) {
    if (v !== 'local-mock') {
      const row = rows.find((r) => r.name === registry[id])
      if (!row || !row.real) bad.push(`${id}(→${registry[id]}) 声明 '${v}' 但源码里没有任何 @/api/* 调用`)
    }
  }
  assert(bad.length === 0, bad.join('; '))
})

check('E4 声明不许撒谎：local-mock 必须真的不是真调用', () => {
  const bad = []
  for (const [id, v] of Object.entries(declared)) {
    if (v === 'local-mock') {
      const row = rows.find((r) => r.name === registry[id])
      if (row && row.real) {
        bad.push(`${id}(→${row.name}) 声明 'local-mock' 但调了 @/api/*：${[...row.apiCalls, ...row.dynamicApi].join(', ')}`)
      }
    }
  }
  assert(bad.length === 0, bad.join(', '))
})

/**
 * ★ 断言 E5（#746 补）：动态真调用**不许成为孤儿**。
 *
 * 第一次改造时踩到的坑：`executeBlueOceanAnalysis` 的真调用写在模块级 helper
 * `tryBackendBlueOcean` 体内，按「执行器 body 区间」归属收不到 ⇒ 它被误判成 mock，
 * 于是 E3（声明 backend-then-mock 却查不到 @/api 调用）报了一条**假红**。
 * 反过来更危险：若归属器彻底失效（永远返回空数组），E3/E4 会「双双通过」——
 * 因为「真调用」集合里根本没有动态导入这一项，没有任何执行器因它被判真。
 * ⇒ 必须钉一条**非名单化**的完整性断言：文件里每一条 `await import('@/api/*')`
 *   都必须有归属（口径与 rows 构建**共用同一份** dynIndexes，不另算一遍）。
 */
check("E5 动态真调用不许成为孤儿：每条 await import('@/api/*') 都必须归属到某个执行器", () => {
  assert(dynApi.length > 0, "文件里解析不到任何 await import('@/api/*') —— 归属判据空跑（源码形态已变？）")
  const owned = new Set(rows.reduce((acc, r) => acc.concat(r.dynIndexes), []))
  const orphans = dynApi
    .filter((d) => !owned.has(d.index))
    .map((d) => d.text.replace(/\s+/g, ' '))
  assert(
    orphans.length === 0,
    `这些动态后端调用没有被任何执行器归属（对门禁隐形 ⇒ 该执行器会被静默误判成 mock）：${orphans.join('; ')}`,
  )
})

/**
 * ★ 断言 F：**可达性判据** —— 注册表里不允许存在「没有任何入口」的 id。
 *
 * `toolExecutors[id]` 的唯一触发口是 window 上的 `tool-analysis` 事件，它只有两个派发点：
 *   (A) `views/Workspace.vue::handleToolAnalysis` ← `TaskConfigPanel` 的 `@startAnalysis`
 *   (B) ~~`chat/useAgentShortcuts.ts::runAdQuickAction`（广告快捷 chip）~~
 *       ★ 第 189 轮 #782 已**删除**该派发点：广告快捷卡改读技能列表、走 LLM
 *       （老板原话「10 张不走 LLM 的卡片改成走 llm，前端调用后端」）。
 *       ⇒ 现在只剩 (A) 一个派发点；`bid-suggest` / `budget-alloc` 因此失去唯一入口，
 *         已登记进 `REACH_WAIVER`（见下表）。
 *       ★ 第 316 轮：`budget-alloc` 已整条退役（卡片 + 大屏 Tab + api 层 + 执行器
 *         一起删）⇒ 从 `REACH_WAIVER` 移除，棘轮上限 11 → 10。
 * ⇒ id 可达 ⟺ (B 的 chip key) 或 (① 能成为 currentTool 且 ② 渲染出的面板真的 emit)
 *
 * 判据完全从源码复算：
 *   ① 「能成为 currentTool」= id 在 `AGENT_TOOLS[some]` 里（目录级口径，见文件头注）
 *   ② 「面板真的 emit」  = 模板分支绑定的 config 文件里有 `emit('startAnalysis'`
 * 未接线者必须登记在 `REACH_WAIVER` 并写明去向；本表是**棘轮**，且每次重新复算。
 */
const REACH_WAIVER = {
  // —— A 桶：功能已被同一产品的另一套界面**取代**（调同一组后端端点），执行器是死副本 ——
  'keyword-miner': 'A 已被 ListingBoard 取代（listing 工作区调 /listing/generate/keywords）',
  'title-gen': 'A 已被 ListingBoard 取代（listing 工作区调 /listing/optimize/title）',
  'bullet-gen': 'A 已被 ListingBoard 取代（listing 工作区调 /listing/generate/bullets）',
  'desc-gen': 'A 已被 ListingBoard 取代（listing 工作区调 /listing/generate/description）',
  // —— B 桶：工具卡已被产品决策移除，但**没有替代品**，执行器保留待接线或退役 ——
  'pain-points': 'B 工具卡已移入候选评估 chip 区（#28），执行器保留待接线或退役',
  'competitor': 'B 工具卡已移入候选评估 chip 区（#28），执行器保留待接线或退役',
  'pitfalls': 'B 工具卡已移入候选评估 chip 区（#28），执行器保留待接线或退役',
  'seo-audit': 'B listing 顶栏已删该工具（#201），执行器保留待接线或退役',
  'ab-test': 'B listing 顶栏已删该工具（#201），执行器保留待接线或退役',
  // —— 第 189 轮 #782：广告快捷卡改走 LLM ——
  //    老板原话「10 张不走 LLM 的卡片改成走 llm，前端调用后端」。出价建议 / 预算分配的
  //    **唯一入口**原本是 `runAdQuickAction` 派发的 `tool-analysis`；卡片改读技能列表后
  //    该派发点整体删除 ⇒ 两个执行器失去入口。成因与上面 #28 那三条完全同族
  //    （产品决策把工具卡从可达面移走），沿用同一处置：**保留 + 登记去向**。
  //    为什么不删执行器：删了会连带 `BidOptimizeResult` / `BudgetAllocResult` 两张结果卡
  //    变成没有生产者的死组件 —— 本仓「先问删了有没有损失」。
  //    真数据路径**未受影响**：`AdDashboardConfig` 的 bid / budget 两个 Tab 直调
  //    `/ad-analysis/bid-optimize` 与 `/ad-analysis/budget`（那才是这两件事的权威源）。
  //    ★ 第 316 轮：`budget-alloc` 已**整条退役** —— 执行器与结果卡
  //      `BudgetAllocResult.vue` 同时删除（不再有「留下没有生产者的死组件」这一顾虑），
  //      其权威源 `/ad-analysis/budget` 端点也一并退役 ⇒ 本表只剩 `bid-suggest`。
  'bid-suggest': 'B 工具卡已移入技能卡区（第 189 轮 #782），执行器保留待接线或退役',
}
/**
 * ★ 棘轮：无入口 id 的数量上限（只许减不许增）。
 *   9 → 11（第 189 轮 #782）：新增的 2 条与既有 3 条同成因（工具卡被产品决策移出可达面），
 *   而它们的执行器都还有可用结果卡，不宜删。本上限记录的是**已知欠账**，不是许可 ——
 *   接线或退役之后必须把它降回去。
 *   ★ 第 316 轮：11 → 10（`budget-alloc` 整条退役 ⇒ 从 REACH_WAIVER 移除）。
 */
const REACH_WAIVER_LIMIT = 10

const PANEL_INDEX = path.join(ROOT, 'src', 'components', 'TaskConfigPanel', 'index.vue')
const SHORTCUTS_SRC = path.join(ROOT, 'src', 'composables', 'chat', 'useAgentShortcuts.ts')
const CHAT_PANEL_SRC = path.join(ROOT, 'src', 'components', 'ChatPanel', 'index.vue')

/** 工具目录：agentId → [id] */
function agentToolIds() {
  const td = fs.readFileSync(path.join(ROOT, 'src', 'components', 'ChatPanel', 'tools', 'toolDefinitions.ts'), 'utf8')
  const out = new Set()
  for (const m of td.matchAll(/id:\s*'([a-z0-9-]+)'/g)) out.add(m[1])
  return out
}

/** ① ChatPanel 里所有「`v-for` 一个数组」+「点它时调哪个 handler」对 —— 正向解析，不猜函数名。
 *    （第一版写成「在 useAgentShortcuts.ts 里 grep 出带 dispatchEvent 的函数名」，结果
 *      非贪婪跨函数匹配抓到了 composable 自身的名字 useAgentShortcuts ⇒ 判据整体失效。）
 *  第 189 轮拆出来单独一个函数，是为了让 F0 能**单独证明「解析器没空跑」**——
 *  那时起合法的 `chip` 可能是空数组（见 F0 注释），需要一个不依赖 `chip` 非空的证据。 */
function parseChipPairs() {
  const cp = fs.readFileSync(CHAT_PANEL_SRC, 'utf8')
  const pairs = []
  for (const m of cp.matchAll(/v-for="\s*\w+\s+in\s+(\w+)\s*"([\s\S]{0,700}?)@click="(\w+)\(\s*\w+\s*\)"/g)) {
    pairs.push({ arr: m[1], handler: m[3] })
  }
  return pairs
}

/** ② 该 handler **真正的函数体**（花括号配对，不用固定字符窗口）；找不到定义返回 `null` */
function locateHandlerBody(h) {
  const sc = fs.readFileSync(SHORTCUTS_SRC, 'utf8')
  const m = new RegExp('(?:const|function)\\s+' + h + '\\s*[=(]').exec(sc)
  if (!m) return null
  const b = sc.indexOf('{', m.index + m[0].length)
  if (b < 0) return ''
  const e = matchBrace(sc, b)
  return e < 0 ? sc.slice(b) : sc.slice(b, e + 1)
}

/** 解析 useAgentShortcuts 里**真的会派发 tool-analysis** 的那个 chip 数组的 key。
 *
 *  ★ 第 189 轮 #782 起合法结果就是**空数组**：四组硬编码卡片统一为「技能卡」，
 *   `runSkillCard` 走 `handleSend`（点技能 → LLM），不再派发 `tool-analysis`。
 *   本函数保留的价值 = F0 的负向对照仍能对「又有人往卡片里塞 tool-analysis 派发」说不。 */
function shortcutDispatchIds() {
  const pairs = parseChipPairs()
  assert(pairs.length > 0, 'ChatPanel 里解析不出任何 chip（v-for + @click）—— 判据无法执行')
  const sc = fs.readFileSync(SHORTCUTS_SRC, 'utf8')
  const out = []
  for (const { arr, handler } of pairs) {
    const body = locateHandlerBody(handler)
    assert(body !== null, `useAgentShortcuts.ts 里找不到 ${handler} 的定义 —— 判据需同步`)
    if (!body.includes("'tool-analysis'")) continue
    const a = new RegExp('const\\s+' + arr + '\\s*=\\s*\\[([\\s\\S]*?)\\n  \\]').exec(sc)
    assert(a, `useAgentShortcuts.ts 里找不到 const ${arr} = [...]`)
    for (const k of a[1].matchAll(/key:\s*'([a-z0-9-]+)'/g)) out.push(k[1])
  }
  return [...new Set(out)]
}

/** 模板分支：tool id → 绑定面板文件；以及该面板是否 emit startAnalysis */
function carrierMap() {
  const idx = fs.readFileSync(PANEL_INDEX, 'utf8')
  const tpl = idx.split('<template>')[1].split('</template>')[0]
  const ls = idx.match(/const\s+LISTING_TOOL_IDS\s*=\s*\[([\s\S]*?)\]/)
  const listingIds = ls ? [...ls[1].matchAll(/'([a-z0-9-]+)'/g)].map((x) => x[1]) : []
  assert(listingIds.length > 0, '解析不出 LISTING_TOOL_IDS')

  const branches = []
  for (const m of tpl.matchAll(/<([A-Z]\w*)\s*\n?\s*v-else-if="([^"]*)"/g)) {
    branches.push({ comp: m[1], cond: m[2] })
  }
  assert(branches.length >= 20, `模板分支只解析出 ${branches.length} 条，解析器可能失效`)

  const map = {}
  for (const { comp, cond } of branches) {
    const ids = []
    for (const m of cond.matchAll(/currentTool\s*\??\.\s*id\s*===\s*'([a-z0-9-]+)'/g)) ids.push(m[1])
    for (const m of cond.matchAll(/\[([^\]]*)\]\s*\.\s*includes\(\s*currentTool/g)) {
      for (const q of m[1].matchAll(/'([a-z0-9-]+)'/g)) ids.push(q[1])
    }
    if (/LISTING_TOOL_IDS\s*\.\s*includes\(\s*currentTool/.test(cond)) ids.push(...listingIds)
    if (!ids.length) continue
    let file = path.join(ROOT, 'src', 'components', 'TaskConfigPanel', 'configs', comp + '.vue')
    if (!fs.existsSync(file)) file = null
    const emits = !!file && /emit\(\s*'startAnalysis'/.test(fs.readFileSync(file, 'utf8'))
    for (const id of ids) {
      // v-else-if 链：**先命中者胜**，后面的同 id 分支被永久遮蔽
      if (!(id in map)) map[id] = { comp, file, emits }
    }
  }
  return map
}

function reachability() {
  const carriers = carrierMap()
  const chip = shortcutDispatchIds()
  const catalog = agentToolIds()
  const reachable = new Set()
  const unreachable = []
  for (const id of Object.keys(registry)) {
    if (chip.includes(id)) {
      reachable.add(id)
      continue
    }
    const c = carriers[id]
    if (catalog.has(id) && c && c.emits) reachable.add(id)
    else unreachable.push(id)
  }
  return { carriers, chip, catalog, reachable, unreachable: unreachable.sort() }
}

check('F0 判据的输入都解析到了（否则本条空跑/恒绿）', () => {
  const { carriers, catalog } = reachability()
  // ★ 第 255 轮（#918）：退役 12 个不可达工具后实测 **29** 个被承载 id / **26** 个目录 id
  //   （退役前 37 / 38）。下限取实测的约 2/3 —— 它的职责是「证明解析器没空跑」，
  //   不是逐条钉死（钉死会让任何一次合法退役都变成假红，本仓判据：门禁是墓志铭）。
  assert(Object.keys(carriers).length >= 20, `只解析出 ${Object.keys(carriers).length} 个被承载的 id`)
  assert(catalog.size >= 18, `工具目录只解析出 ${catalog.size} 个 id`)
  // ★ 比"数量下限"更强的正向对照：**已知存在的 id 必须被解析到**。
  //   数量下限挡不住"解析器退化到只认识一半"（仍可能 > 下限），
  //   锚点断言能 —— 而且它不会因为将来合法删掉别的工具而红。
  // ★ 第 284 轮：`ticket-create` 工具卡退役（连同配置面板）⇒ 从锚点清单摘除。
  //   本清单钉的是「解析器**没退化**」，不是「这些 id 永远存在」——
  //   留着已退役的 id 会让每次合法退役都变成假红（门禁是墓志铭，不是保证书）。
  for (const id of ['blue-ocean', 'static-asset-gen', 'order-track']) {
    assert(catalog.has(id), `目录解析器漏掉了**已知存在**的 id：${id}（判据本身已失配）`)
    assert(carriers[id], `承载解析器漏掉了**已知有分支**的 id：${id}（判据本身已失配）`)
  }
  assert(carriers['blue-ocean'].emits, '承载解析器把**已知 emit** 的 blue-ocean 判成不 emit —— 判据写反了')
  // ★ 第 189 轮 #782 起 `chip` **合法为空**（见 F0 负向对照），所以不能再拿它当
  //   「解析器没空跑」的证据。改判**解析器本体**：ChatPanel 里的 v-for/@click 对要解析得到，
  //   且至少一个 handler 能在 useAgentShortcuts.ts 里定位。否则后面 F1 会
  //   「因为什么都没解析到」而永远通过 —— 那正是本门禁最怕的假绿。
  const pairs = parseChipPairs()
  assert(pairs.length > 0, 'ChatPanel 里解析不出任何 `v-for` + `@click="handler(x)"` 对 —— 解析器已失效')
  const located = pairs.filter((p) => locateHandlerBody(p.handler) !== null)
  assert(located.length > 0,
    `解析到的 ${pairs.length} 个 handler 一个都没能在 useAgentShortcuts.ts 里定位 —— 判据已失配`)
})

check('F0 负向对照：不得再有卡片派发 tool-analysis（第 189 轮的判据本体）', () => {
  const { chip } = reachability()
  assert(chip.length === 0,
    `第 189 轮 #782 起卡片走的是技能（handleSend），不应再有 chip 派发 tool-analysis，实测：${chip.join(', ')}`)
  // 技能卡动作条本体必须存在 —— 否则「chip 为空」可能只是「卡片整排没接上」造成的假象
  const sc = fs.readFileSync(SHORTCUTS_SRC, 'utf8')
  assert(/const\s+skillCards\s*=/.test(sc),
    'useAgentShortcuts.ts 里找不到 const skillCards —— 技能卡的数据源没接上')
  assert(/v-for="c in skillCards"/.test(fs.readFileSync(CHAT_PANEL_SRC, 'utf8')),
    'ChatPanel 里找不到 `v-for="c in skillCards"` —— 技能卡动作条没渲染')
  assert(/runSkillCard\(c\)/.test(fs.readFileSync(CHAT_PANEL_SRC, 'utf8')),
    'ChatPanel 里找不到 `@click="runSkillCard(c)"` —— 卡片点了没反应')
})

check('F0 正向对照：已 emit 的面板不得被判成「不 emit」', () => {
  const { carriers } = reachability()
  const emitTrue = Object.values(carriers).filter((c) => c.emits)
  // ★ 第 255 轮实测 12 个（退役前 19）；下限取 8 = 约 2/3，理由同上。
  assert(emitTrue.length >= 8, `只有 ${emitTrue.length} 个面板被判为 emit —— 判据可能写反了（恒假）`)
  for (const [id, c] of Object.entries(carriers)) {
    if (!c.file) continue
    const src = fs.readFileSync(c.file, 'utf8')
    assert(c.emits === /emit\(\s*'startAnalysis'/.test(src), `${id} → ${c.comp} 的 emit 判定与文件内容不一致`)
  }
})

check('F1 注册表里不允许出现「无入口」的 id（未接线者必须登记去向）', () => {
  const { unreachable, carriers, chip } = reachability()
  const waived = Object.keys(REACH_WAIVER).sort()
  const extra = unreachable.filter((id) => !waived.includes(id))
  const stale = waived.filter((id) => !unreachable.includes(id))
  const detail = []
  for (const id of unreachable) {
    const c = carriers[id]
    detail.push(
      `      ${id.padEnd(24)} ${chip.includes(id) ? 'chip' : c ? `${c.comp}${c.emits ? '' : '(声明 emits 但模板不 emit)'}` : '(模板里没有任何承载分支)'}`,
    )
  }
  assert(
    stale.length === 0,
    `这些 id 已登记为「无入口」，但**现在可达了** —— 请把 REACH_WAIVER 里的条目删掉（否则棘轮只会越来越松）：${stale.join(', ')}`,
  )
  assert(
    extra.length === 0,
    `这些 id 已注册但**没有任何入口**，且没有登记去向：${extra.join(', ')}\n` +
      `    当前全部无入口 id：\n${detail.join('\n')}\n` +
      `    —— 它们是「假数据坟墓」：编译得通、测试过得，但永远跑不到，还留在 mock/ 里等着被重新 import 成第二条假数据路径。\n` +
      `    要么删掉，要么把面板接回 startAnalysis 事件，要么在 REACH_WAIVER 里写明去向。`,
  )
})

check(`F2 棘轮：无入口 id 数量不增长（${Object.keys(REACH_WAIVER).length} <= ${REACH_WAIVER_LIMIT}）`, () => {
  assert(
    Object.keys(REACH_WAIVER).length <= REACH_WAIVER_LIMIT,
    `无入口 id 已达 ${Object.keys(REACH_WAIVER).length} 个，超过上限 ${REACH_WAIVER_LIMIT}（接线或退役，别再加豁免）`,
  )
})

check('F3 每条豁免都必须写明去向（接线/退役/已被取代）', () => {
  const bad = Object.entries(REACH_WAIVER).filter(([, why]) => !/接线|退役|取代/.test(why))
  assert(bad.length === 0, `这些豁免没写清去向：${bad.map(([k]) => k).join(', ')}`)
})

// ----------------------------------------------- F4~F6：结果卡 ↔ 生产者（第 261 轮）

/**
 * ★ 断言 F4 / F5 / F6（第 261 轮新增）：**渲染级口径的第二半 —— 结果卡 ↔ 生产者**。
 *
 * 为什么必须补（第 261 轮实锤）
 * ============================
 * `CompetitorIntelEvidence.vue` 是全仓唯一「前端有卡、**后端永不下发**」的结果卡：
 *   · 它的 `v-if="msg.displayType === 'competitor_intel_analysis'"` 写在
 *     `ChatPanel/index.vue` 的**模板里**，绕过了 `results/conversation/registry.ts`
 *     第 5 行明文规定的「结论卡一律通过本表映射，**模板里不散落 if-else**」；
 *   · 后端不下发该 display_type（全仓 grep 零命中）⇒ `v-if` 恒假、卡片永不出现。
 * 它能活这么久的唯一原因是**没有任何判据看得见它**：
 *   · F1~F3 管的是**工具执行器**（toolId）的可达性，扫的是 `mock/toolExecutors.ts`；
 *   · 跨端 pytest 只钉了 `review_report` **一个**键
 *     （`backend/tests/test_skill_shortcut_compat.py::test_review_report_display_type_has_a_frontend_card`）；
 *   · 注册表里其余 5 个键**从没有过**「后端是否真的下发」的对账。
 * ⇒ 本条把 F 的对象从**工具执行器**扩展到**结果卡**：
 *     F4 输入自检（防空跑）· F5 注册表每个键必须有生产者证据 · F6 模板不得绕过注册表。
 *
 * 口径与边界（为什么**不做**双向对账）
 * ================================
 * · **单向**：只要求「注册表的键 → 后端有证据」。**反向不要求** —— 后端大量
 *   display_type（`faq_answer` / `order_info` / `return_guide` / `text` …）是
 *   **故意不渲染卡片**的（各自域内纯文本或自绘），要求双向相等会造出一堆假红。
 * · **生产者证据取宽**：剥注释后该 display_type 的**字符串字面量**在后端任意 `.py`
 *   里出现过即算。理由是实测到的形态至少三种，只认一种会漏：
 *     ① `display_type="ad_diagnosis"`（直接赋值）
 *     ② `"analyze_blue_ocean": "blue_ocean_analysis"`（工具名 → display_type 映射表；
 *        `modules/product_research/agent_product_research.py` 用的正是这种）
 *     ③ `assert meta["display_type"] == "blue_ocean_analysis"`（跨端测试断言）
 *   取宽只会**少报**不会误报；更严的「哪个 Agent 在哪个分支下发」留给 pytest。
 */

const BACKEND_DIR = path.resolve(ROOT, '..', 'backend')
const REGISTRY_SRC = path.join(
  ROOT,
  'src',
  'components',
  'ChatPanel',
  'results',
  'conversation',
  'registry.ts',
)

/** 递归收集目录下的文件（跳过 __pycache__ / node_modules / .git） */
function walkFiles(dir, ext, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) {
      if (e.name === '__pycache__' || e.name === 'node_modules' || e.name === '.git') continue
      walkFiles(path.join(dir, e.name), ext, out)
    } else if (e.name.endsWith(ext)) {
      out.push(path.join(dir, e.name))
    }
  }
  return out
}

/**
 * 剥 Python 注释（`#` 行注释 + 三引号 docstring）。
 *
 * ★ 不能复用上面的 `stripComments`：它只认 JS 的块注释与行注释，喂 Python 会**一条注释都不剥**
 *   ⇒ 注释里写过的 display_type 被当成「后端真的下发过」= **漏报**（本仓最怕的假绿）。
 */
function stripPyComments(src) {
  let out = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const ch = src[i]
    if (ch === '"' || ch === "'") {
      const tri = src.slice(i, i + 3)
      if (tri === '"'.repeat(3) || tri === "'".repeat(3)) {
        const k = src.indexOf(tri, i + 3)
        i = k < 0 ? n : k + 3
        out += ' '
        continue
      }
      let j = i + 1
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue }
        if (src[j] === ch) { j++; break }
        if (src[j] === '\n') break
        j++
      }
      out += src.slice(i, j)
      i = j
      continue
    }
    if (ch === '#') {
      const k = src.indexOf('\n', i)
      i = k < 0 ? n : k
      continue
    }
    out += ch
    i++
  }
  return out
}

/** 后端「生产者证据」：display_type → 命中它的前若干个文件（报错够用） */
function displayTypeEvidence() {
  assert(
    fs.existsSync(BACKEND_DIR),
    `后端目录不存在：${BACKEND_DIR} —— 「结果卡有生产者」这条判据无法执行（**不允许静默变绿**）`,
  )
  const files = walkFiles(BACKEND_DIR, '.py')
  assert(files.length > 50, `后端只扫到 ${files.length} 个 .py —— 扫描器可能失配`)
  const map = new Map()
  for (const f of files) {
    const src = stripPyComments(fs.readFileSync(f, 'utf8'))
    for (const m of src.matchAll(/(['"])([A-Za-z][A-Za-z0-9_]*)\1/g)) {
      const v = m[2]
      if (!map.has(v)) map.set(v, [])
      const hit = map.get(v)
      const rel = path.relative(BACKEND_DIR, f).split(path.sep).join('/')
      if (hit.length < 3 && !hit.includes(rel)) hit.push(rel)
    }
  }
  return map
}

/** 前端注册表声明的 display_type 键（`CONVERSATION_RESULT_COMPONENTS` 的对象键） */
function registryDisplayTypes() {
  assert(fs.existsSync(REGISTRY_SRC), `前端结论卡注册表不存在：${REGISTRY_SRC}`)
  const src = stripComments(fs.readFileSync(REGISTRY_SRC, 'utf8'))
  const block = /CONVERSATION_RESULT_COMPONENTS\s*:\s*Record<[^>]*>\s*=\s*\{([\s\S]*?)\n\}/.exec(src)
  assert(block, '解析不出 CONVERSATION_RESULT_COMPONENTS 的对象字面量 —— 注册表结构变了，判据需同步')
  return [...block[1].matchAll(/^\s*([a-z][a-z0-9_]*)\s*:/gm)].map((m) => m[1])
}

/**
 * 模板里**绕过注册表**的裸 displayType 比较。
 * 白名单是「另一套规则」的合法例外，只允许**必须**写在这里的东西。
 */
const NAKED_DISPLAYTYPE_WHITELIST = new Set([
  // 工具结果卡：key = toolId（**不是** display_type），渲染规则与结论卡不同，
  // 见 `registry.ts` 头注「工具结果卡 vs 会话结论卡」。它是当前唯一合法例外。
  'tool_result',
])

function nakedDisplayTypeBranches(src) {
  // 两层剥离缺一不可：JS 注释（stripComments）+ HTML 注释（`<!-- -->`）。
  // 注释里提到某个 display_type 不算分支 —— 不剥就会把作者的好意注释变成红灯。
  const only = stripComments(src).replace(/<!--[\s\S]*?-->/g, '')
  const hits = []
  for (const m of only.matchAll(/\bdisplay_?[Tt]ype\s*===?\s*(['"])([A-Za-z0-9_]+)\1/g)) {
    if (!NAKED_DISPLAYTYPE_WHITELIST.has(m[2]) && !hits.includes(m[2])) hits.push(m[2])
  }
  return hits
}

check('F4 结果卡对账的输入都解析到了（否则 F5/F6 空跑/恒绿）', () => {
  const keys = registryDisplayTypes()
  const ev = displayTypeEvidence()
  const cp = fs.readFileSync(CHAT_PANEL_SRC, 'utf8')
  // 注册表侧：数量下限 + **已知锚点**（数量下限挡不住「解析器退化到只认一半」）
  assert(keys.length >= 5, `注册表只解析出 ${keys.length} 个键（实测 6）—— 解析器可能失配`)
  assert(
    keys.includes('review_report'),
    '注册表解析器漏掉了**已知存在**的键 review_report —— 判据本身已失配',
  )
  // 后端侧：数量下限 + 已知锚点（三种形态各取一个）
  assert(ev.size >= 50, `后端只解析出 ${ev.size} 种字符串字面量（实测 >500）—— 解析器可能失配`)
  for (const known of ['review_report', 'competitor_analysis', 'blue_ocean_analysis', 'pending_approval']) {
    assert(ev.has(known), `后端生产者解析器漏掉了**已知存在**的 ${known}（判据本身已失配）`)
  }
  // 扫描器本体不得空跑：白名单成员必须在源码里**真的**被找到，否则白名单是空壳
  assert(
    /\bdisplay_?[Tt]ype\s*===?\s*(['"])tool_result\1/.test(
      stripComments(cp).replace(/<!--[\s\S]*?-->/g, ''),
    ),
    "找不到 `msg.displayType === 'tool_result'` —— 白名单成了空壳（放行一个不存在的名字），判据需同步",
  )
})

check('F5 注册表里每个 display_type 都必须在后端找得到生产者证据', () => {
  const keys = registryDisplayTypes()
  const ev = displayTypeEvidence()
  const orphans = keys.filter((k) => !ev.has(k))
  assert(
    orphans.length === 0,
    `这些 display_type 在前端注册了卡片，但**后端源码里从没有过这个字符串** ⇒ 卡片永远不会出现：\n` +
      `      ${orphans.join(', ')}\n` +
      `    —— 这就是「无生产者死卡」。第 261 轮实锤：\`CompetitorIntelEvidence\` 正是这个形态\n` +
      `       （后端 grep 零命中 / \`v-if\` 恒假 / \`vue-tsc\` 全绿 / 构建正常，**没有任何判据看得见它**）。\n` +
      `    要么后端补下发（并在 \`backend/tests/test_skill_shortcut_compat.py\` 里对账），要么从前端注册表删掉这个键。`,
  )
})

check('F6 模板不得绕过注册表：结论卡必须登记进 CONVERSATION_RESULT_COMPONENTS', () => {
  const naked = nakedDisplayTypeBranches(fs.readFileSync(CHAT_PANEL_SRC, 'utf8'))
  assert(
    naked.length === 0,
    `模板/脚本里出现**绕过注册表**的裸 displayType 分支：${naked.join(', ')}\n` +
      `    \`registry.ts\` 第 5 行明文规定「结论卡一律通过本表映射，**模板里不散落 if-else**」。\n` +
      `    裸分支绕过的不是风格，而是**对账**：后端不下发该 display_type 时无人报错、\n` +
      `    \`v-if\` 恒假却编译得过、\`vue-tsc\` 全绿 —— 第 261 轮 \`CompetitorIntelEvidence\` 的实锤形态。\n` +
      `    要么登记进注册表走 \`resolveConversationResult\`，要么删掉该分支；\n` +
      `    确有另一套规则的（如工具结果卡 \`tool_result\`，key=toolId）才可进 NAKED_DISPLAYTYPE_WHITELIST 并写明理由。`,
  )
})

check('F6 正/负向对照：合成的裸分支必须被判红，注册表驱动与白名单必须合格', () => {
  const RED_NAKED = `  <X v-if="msg.displayType === 'competitor_intel_analysis'" />`
  // ★ `anomaly_report` 只作「snake_case 字面量」的**合成样本**使用，与被退役的
  //   异常检测能力无关（该 display_type 前端从未注册过渲染分支）。
  const RED_SNAKE = `  <Y v-if="msg.display_type === 'anomaly_report'" />`
  const OK_REGISTRY = `  <component v-if="resolveConversationResult(msg.displayType)" />`
  const OK_WHITELIST = `  <div v-if="msg.displayType === 'tool_result'">`
  const OK_COMMENT = `  <!-- 曾经用 msg.displayType === 'bogus_type' 判断过，已删除 -->`
  assert(nakedDisplayTypeBranches(RED_NAKED).length === 1, '负向对照失败：合成的裸分支（camelCase）没被判红 ⇒ F6 恒绿')
  assert(nakedDisplayTypeBranches(RED_SNAKE).length === 1, '负向对照失败：合成的裸分支（snake_case）没被判红')
  assert(nakedDisplayTypeBranches(OK_REGISTRY).length === 0, '正向对照失败：注册表驱动被误判成裸分支')
  assert(nakedDisplayTypeBranches(OK_WHITELIST).length === 0, '正向对照失败：白名单 tool_result 被误判')
  assert(
    nakedDisplayTypeBranches(OK_COMMENT).length === 0,
    '正向对照失败：**注释里**的比较被误判成代码（注释没剥干净）—— 会把作者的好意注释变成红灯',
  )
})

/**
 * ★ 断言 G（#744 迁移）：广告诊断的**活路径**必须真调后端。
 *
 * `executeAdDiagnosis`（工具卡路径）已删，广告诊断现在只有一条活路径：
 * 对话关键词分支 `chat/replies/adAnalysis.ts` → `diagnoseAdAccount`。
 * 「广告诊断走真源」这条判据不能因为文件改名就消失 ⇒ 钉在新的落点上。
 */
// --------------------------------------------------------------------------- //
// F7（第 284 轮）：目录里 status: 'active' 的 id 必须在执行器注册表里找得到
// --------------------------------------------------------------------------- //
//
// ★ 为什么必须补这一条（本轮实测暴露的盲区）：
//   F1 查的是**反方向** —— 「执行器注册表里的 id 有没有入口」。
//   而 AGENT_TOOLS 里 status:'active' 的 id **有没有执行器**，此前**没有任何
//   判据看得见**。代价已经发生：`faq-search` / `sentiment` 两张卡挂着 active
//   却零接线（无执行器 / 无配置面板 / 前端 api 零调用），点下去右栏只有一句
//   「配置面板开发中」，而本门禁当时 38/38 全绿。
//
//   coming_soon **豁免**：它表达的就是「明确还没做」，那是诚实占位、不是缺陷。
//   把「假装做了」和「诚实说没做」判成一样，判据就失去了分辨力。
//
//   ★ 第 284 轮第三段：生产目录里已经**没有任何 coming_soon 样例**（唯一的
//     `reply-draft` 也退役了 —— 它被豁免了两轮，最后按「占位须有规格表依据」
//     退役）。**豁免分支仍必须保留**（它是规范，不是特例），也因此不能靠生产
//     文件来验证它 —— 由反向注入脚本**自造样例**来验：
//     `.workbuddy/probes/r284_tool_reality_f7_inject.py` 第 ② 组新增一条
//     `coming_soon` 幽灵工具，要求 F7 **不得**为它转红（负向对照）。
//
// ★ 与 F1 合起来，两个方向的差集都被钉住 —— 单查任一边都会留下无人看守的盲区。
check('F7 目录里 active 的 id 必须有承载面板（F1 的反方向）', () => {
  const td = fs.readFileSync(
    path.join(ROOT, 'src', 'components', 'ChatPanel', 'tools', 'toolDefinitions.ts'), 'utf8')
  const entries = [...td.matchAll(/id:\s*'([a-z0-9-]+)'[^}]*?status:\s*'(active|coming_soon)'/g)]
    .map((m) => ({ id: m[1], status: m[2] }))

  // L0：解析器没空跑 —— 否则下面的全称判断会在空集上恒真
  assert(entries.length >= 15,
    `工具目录只解析出 ${entries.length} 条带 status 的定义（期望 >= 15）—— 解析器已失配`)
  const active = entries.filter((e) => e.status === 'active')
  assert(active.length > 0, '一条 active 都没解析到 —— 判据会在空集上恒真')

  // ★ 口径用**承载面板**（carriers），不用执行器注册表 —— 第一版就是那么写的，
  //   结果是**假红**，这里留档防止改回去：
  //   「点工具卡 → 右栏」有**三条**落点，注册表只覆盖第 ① 条：
  //     ① 面板 emit `startAnalysis` → `tool-analysis` → `toolExecutors[id]`（注册表）
  //     ② 同一条事件，但事件桥对它**特判** —— `useChatEventBridge` 里
  //        `if (tool.id === 'profit-calc') resolveProfitResult(...)`，不经注册表
  //     ③ **面板自己直调 `@/api/*`**，根本不发事件 —— AdDashboard / Review /
  //        IntelBoard 三个统一大面板就是这个形态（`toolExecutors` 头注 #744 也记着：
  //        正因如此才删掉了 13 个执行器）
  //   ⇒ 只查注册表会把 ②③ 全判成 orphan（`profit-calc` + 广告 4 个 = 5 条假红）。
  //   `carriers` 是「谁在 TaskConfigPanel 里被**具名**接管」的解析结果，三条落点都归它管；
  //   落到末尾兜底 `v-else`（「配置面板开发中」）的才会漏出集合 —— 那正是本轮要抓的形态。
  const { carriers } = reachability()
  assert(Object.keys(carriers).length >= 15,
    `承载解析器只解析出 ${Object.keys(carriers).length} 个 id —— 判据会假绿`)

  const orphans = active.filter((e) => !carriers[e.id]).map((e) => e.id)
  assert(orphans.length === 0,
    `目录里挂着 active 却没有承载面板的 id：${orphans.join(' / ')}` +
    ' —— 点开右栏只会看到「配置面板开发中」。' +
    '三条出路：接线 / 把 status 改成 coming_soon（诚实占位）/ 从目录删掉。')
})

check('G 广告诊断对话分支必须真调 diagnoseAdAccount', () => {
  const f = path.join(ROOT, 'src', 'composables', 'chat', 'replies', 'adAnalysis.ts')
  assert(fs.existsSync(f), `广告诊断的对话分支不存在：${f} —— 若已改名，「广告诊断走真源」这条判据与它一起静默失效了`)
  const only = stripComments(fs.readFileSync(f, 'utf8'))
  assert(/(?<![\w$.])diagnoseAdAccount\s*\(/.test(only), 'adAnalysis.ts 没有调用 diagnoseAdAccount —— 广告诊断退回本地假数据了')
  assert(!/Math\.random\s*\(/.test(only), 'adAnalysis.ts 里出现 Math.random() —— 真诊断不会被随机数编出来')
})

// ---------------------------------------------------------------- 输出

;(async () => {
await checkLive()

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
  `工具执行真伪门禁通过（已接线 ${MUST_BE_REAL.length} 个真调用 ✓ / 本地 mock ${mocks.length} 个 ≤ ${MOCK_LIMIT} ✓` +
    ` / 注册 ${Object.keys(registry).length} 个 id 全部有数据来源声明 ✓` +
    ` / 无入口 ${Object.keys(REACH_WAIVER).length} 个已登记去向 ≤ ${REACH_WAIVER_LIMIT} ✓` +
    ` / 结论卡 ${registryDisplayTypes().length} 个键全部有后端生产者证据 ✓` +
    ` / 模板 0 处绕过注册表的裸 displayType 分支 ✓）`,
)
})()

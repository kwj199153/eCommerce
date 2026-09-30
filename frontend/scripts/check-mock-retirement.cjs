#!/usr/bin/env node
/**
 * 前端 mock「退役」门禁（★ 第 167 轮 · #725）
 *
 * 为什么值得单独一个门禁
 * ====================
 * 这个仓里已经有过多次「删了 mock、但某个角落还 import 着它」的经历，
 * 而这类残留的形态特征最要命：
 *
 *   · **类型系统不报**（路径还解析得到，因为文件也还在或 vite 别名仍命中）；
 *   · **单测不红**（前端没有覆盖到那条分支）；
 *   · **界面不报**（编造的数字看起来和真数据一模一样）。
 *
 * 于是「退役」这件事会**看起来完成了**，而实际上假数据还在某条路径上流着。
 * ⇒ 必须有一条断言**能对「这个 mock 又被接回来了」说不**。
 *
 * 与相邻门禁的分工
 * ================
 *   · `check-tool-reality.cjs`  —— 工具执行器**是否真的调后端**（运行时出口）
 *   · `check-memory-reality.cjs` —— 某**一个页面**是不是假页面（页面级形态）
 *   · 本门禁 —— 某**一个 mock 文件**是不是真的退役了（模块级引用面）
 * 三者互补：本门禁只管「谁还在 import 已退役的 mock」，不管它调得对不对。
 *
 * 八组断言
 * ========
 *   A1 退役清单里的文件**已从磁盘删除**（没删就不算退役）
 *   A2 扫描面里**没有任何**（注释已剥的）模块说明符指向退役清单 ——
 *      三条形态都要抓：`from '...'`（含**跨行** import 语句）、
 *      动态 `import('...')`、裸 `import '...'`；包名形态与**相对路径**形态都要抓
 *   A3 正向对照（自检）：匹配器能抓「跨行 import」
 *   A4 正向对照（自检）：匹配器能抓「动态 import」与「相对路径」
 *   A5 反向对照（自检）：匹配器不会误命中非退役模块
 *   A6 扫描面规模达标（文件数 / 说明符数；否则 A2 会「因为什么都没扫到」而永远通过）
 *
 *   ── 以下两条是 ★ 第 279 轮新增（同一主题的**另一个形态**）──
 *   A7 **catch 块里不得把读失败回退成内联 mock**
 *      与 A1/A2 的分工：A1/A2 管「模块级的 mock 文件」（import 面），
 *      A7 管「文件内联的 mock 常量」（赋值面）。
 *      ★ 后者**结构上逃得过 A2** —— 它不是一个 import，扫描器看不见。
 *      于是它活到了第 279 轮：`Subscription.vue` 的 loadPlans / loadInvoices
 *      在 catch 里灌 mockPlans / mockInvoices（用户看到 3 个后端不存在的套餐 ——
 *      假价格、且「选择此套餐」还能点、点下去真的会拿一个不存在的 plan_id
 *      去下单；以及 3 条不存在的已支付账单），`candidateLibrary.ts` 灌假 ASIN 候选。
 *   A8 A7 匹配器的四条自检（2 正 / 2 反）：
 *      合法的「置空 + 记原因」写法与「不在 catch 里的同名变量」都必须**不**命中。
 *
 * ★ A3 的样本**故意写成跨行**：本门禁的第一版扫描器用的是 `[^;\n]*?`，
 *   它匹配不到 `import {\n  A,\n  B,\n} from '@/mock/x'` 这种写法 ——
 *   实测 `AdDashboardConfig.vue` 的 import 就是这样，**被静默漏掉**。
 *   用跨行样本做自检，等于把这个 bug 的复发变成一次红灯。
 *
 * 怎么跑
 * ======
 *   node scripts/check-mock-retirement.cjs           做判定
 *   node scripts/check-mock-retirement.cjs --report   只打印盘面读数、不判定
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 * 扫描根可用环境变量指向**副本树**，于是能在不改工作区的前提下逐条打穿：
 *   MOCK_RETIRE_SRC_ROOT=<副本 src 目录>
 * 见 `.workbuddy/probes/h725_reverse.py`（4 条注入 + 1 条「不该红」的对照）。
 *
 * ★ 已知欠账（诚实说明）
 *   下面的 `stripComments` 与 `check-memory-reality.cjs` / `check-tool-reality.cjs`
 *   里的是**同一份实现的第 3 份拷贝**。抽成 `scripts/_lib/` 是对的，但抽的时候
 *   **必须一次改三处** —— 只改一处会留下两份口径不同的剥注释逻辑，
 *   那比现在这份重复更糟（本仓「同一判定两份实现 ⇒ 至少一份永远测不到」那条）。
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')

/** 扫描根：默认 `frontend/src`；反向注入时指向副本树 */
const SRC_ROOT = process.env.MOCK_RETIRE_SRC_ROOT
  ? path.resolve(process.env.MOCK_RETIRE_SRC_ROOT)
  : path.join(ROOT, 'src')

const REPORT_ONLY = process.argv.includes('--report')

// ---------------------------------------------------------------- 口径常量

/** 扫描的文件类型 */
const EXTS = ['.ts', '.vue', '.tsx', '.js']

/**
 * ★ 已退役清单 —— 新增条目时**必须**同时登记（这是本门禁的唯一入口）。
 *
 * `key`   = 相对 `src/` 的路径（不带前导 `./`）
 * `value` = { round, reason, replacement }
 *
 * ★ 为什么在门禁里维护这份清单、而不是从 api 层读：
 *   退役是一桩**有先后顺序**的事（先换调用点 → 再删文件 → 再登记）。
 *   清单放在门禁里，就等于「登记」这一步是**显式动作**；放进被测源码里，
 *   删文件的人可能连那份清单一起删了 —— 门禁随即静默空跑。
 */
const RETIRED = {
  'mock/reviewDashboard.ts': {
    round: '第 167 轮 #725',
    reason:
      '281 行硬编码假数据 + buildReviewReply 里编造的环比（+12.3% / +8.1%）。' +
      '后端 6 个结构化端点与 POST /review/chat 早已就绪，前端一个都没调。',
    replacement:
      'src/api/review.ts（7 端点）+ ReviewConfig.vue（接真源，缺维度显式占位）' +
      '+ useChatOrchestrator.ts 的 review-analyst 分支走 /review/chat',
  },
  'mock/competitorRecommend.ts': {
    round: '第 167 轮 #725',
    reason:
      '内部 `[...MOCK_PRODUCTS, ...universe]` 把假商品**前置掺进**调用方已经从' +
      '后端收集好的真实候选集（产品库 + 候选库），并用兜底分 `score += 1`' +
      '保证假数据必然进结果 —— 比纯 mock 更难发现，因为列表里确实混着真东西。',
    replacement:
      'src/utils/competitorSimilarity.ts（纯算法，零数据源，去兜底分，空来源 fail-closed）' +
      '+ stores/competitorPool.ts（数据只用 sourceUniverse）' +
      '+ CompetitorManager.vue（库为空时给可行动提示，不再静默落到「未找到更多」）',
  },
  'mock/adDashboard.ts': {
    round: '第 169 轮 #737',
    reason:
      '289 行硬编码假数据 / 27 个导出常量，整份以「手摇咖啡 grinder」产品线为统一场景。' +
      '它比一般残留更隐蔽 —— **不是残留，而是唯一数据源**：AdDashboardConfig.vue 的 6 个 Tab ' +
      '全部吃它，组件**从不发任何请求**（`defineEmits` 声明了 startAnalysis 却一次都没 emit）。' +
      '搜索词 Tab 的 4 个 KPI（总搜索词 / 高效 / 低效 / 浪费）甚至是模板里写死的 42 / 3 / 2 / 2，' +
      '**连 mock 都没走**。而后端 modules/ad_analysis/router.py 的 6 个结构化端点' +
      '（diagnose / search-terms / bid-optimize / competitors / budget / anomalies）早已就绪、' +
      '且都做了 fail-closed（`success=False` + `data_status=no_data`，HTTP 仍 200）—— 前端一个都没调。',
    replacement:
      'src/api/adAnalysis.ts（6 端点 + 与后端 schemas 逐字对齐的类型 + `isAdDataOk` 唯一真源判据）' +
      '+ AdDashboardConfig.vue 按 Tab 懒加载真源（补 loading / 空 / 错误三态；' +
      '竞品按 asin 去重取 SOV Top 6；无环比、无日粒度序列、零异常三处**显式占位而非补数**；' +
      '补 `.grade-F` 配色 —— 后端 `_score_to_grade` 是 A/B/C/D/F 五档，原 CSS 只写了四档）',
  },
  'mock/listingBoard.ts': {
    round: '第 169 轮 #738',
    reason:
 '184 行硬编码假文案 / 6 个导出，整份以「Portable Coffee Grinder」单一产品线为场景。' +
 '★ 它比一般残留更隐蔽：**不是残留，而是唯一数据源** —— ListingBoard.vue 的四个模块' +
 '（关键词 / 标题 / 五点 / 长描述）全部由它一次 `genAll()` 同步吐出，组件**从不发任何请求**。' +
 '更麻烦的是它**编了后端没有的东西**：' +
 '① `genKeywords` 给每行配了 search_volume(45200 等) / competition / relevance，' +
 '而这三项在全后端只存在于 `modules/product_research`（选品），' +
 '`listing_generator` 的 SearchTermsResponse 只有扁平的 `terms: string[]` + 总字节数；' +
 '② `genTitle` 返回 4 条 `variants`，而后端 `ListingTitle` **根本没有 variants 字段**；' +
 '③ `genSeo` 造了 5 行 `{category,score,status,issues,suggestions}`，' +
 '而后端 SEOAnalysisResponse 是 `{overall_score,title_score,...,checklist:dict,grade}`，' +
 '没有「按维度分行」这种结构。（顺带：`genSeo` 是**死代码** —— ' +
 '`applyGenerated` 里根本没有 `draft.setSeo(...)`，唯一的 setSeo 调用在 ' +
 '`composables/useChatOrchestrator.ts` 的 SEO 诊断 chip 那条链上。）',
    replacement:
 'src/api/listingGenerator.ts（补类型 + 信封 + config，字段名与后端逐字对齐）' +
 '+ ListingBoard.vue 四个模块改调 /listing/* 真端点（各走最贴的那个；' +
 '「一键生成全部」走 POST /generate 一次往返；失败给**常驻**横幅而非只弹 toast）' +
 '+ stores/listingDraft.ts 三处修正：' +
 '① `setKeywords` 对账两个生产者的键（工作区用 `word`、关键词挖掘透传用 `keyword`，' +
 '只认前者会让挖掘结果变成 N 行空关键词）；' +
 '② 三个指标字段改 `| null`，`null` = **后端未提供**（不再用 0/medium/80 冒充' +
 '「搜索量 0、相关度 80」这种编出来的数）；' +
 '③ `normalizeModule` 把后端 `sections[*].type`（语义枚举 intro/features/scenarios）' +
 '映射到 A+ **版式**类型 —— 两者同名不同义，不映射则 AplusSection 的三个 v-if 全不命中，正文一个字都不显示',
  },
}

/**
 * ★ 扫描面下限，**不是手写猜的**：用 `--report` 在本仓现量（第 167 轮 #725
 *   退掉第 1 个 mock 后）为 `files=186, specifiers=723`。下限取 150/500，
 *   留足余量 —— 它的作用只有一个：让「什么都没扫到」这件事变成红灯，
 *   而不是变成一条永远通过的假断言。
 *
 * ★ 说明符总数会**随退役而减少**（本轮 724 → 723，正是删掉那条动态 import 所致），
 *   所以下限必须留足余量；要读「现量」请用 `--report`，不要读这个注释。
 */
const MIN_FILES_SCANNED = 150
const MIN_SPECIFIERS = 500

// ---------------------------------------------------------------- 解析工具

/**
 * 剥注释（字符串 / 模板字面量感知）。
 *
 * ★ 必须做这一步的**具体理由**（本门禁自己的现场）：
 *   退役说明会以注释形式写进 `api/review.ts`、`ReviewUnsupportedNote.vue`、
 *   `useChatOrchestrator.ts`（"退役 `@/mock/reviewDashboard`"）。
 *   不剥注释 ⇒ 这些**解释性注释**会把一份正确的实现判成违反。
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

/**
 * 找「读失败回退内联 mock」的形态（★ 第 279 轮）：
 * **catch 块内**把某个 ref 赋值为以 mock/MOCK 命名的标识符
 * （含 `[...MOCK_X]` 这种展开形态）。
 *
 * ★ 为什么必须先切出 catch 块再判，而不是全文件正则：
 *   本仓就有一个**合法**的反例 —— `src/mock/toolExecutors.ts` 里
 *   函数内的 `const mockKeywords = [...]`（是关键词生成的中转数据，
 *   与"读失败兜底"毫无关系）。全文件正则会把这类用法一起判成违规，
 *   而**假红灯同样会让人把门禁关掉**。判据的作用域必须等于断言的作用域。
 *
 * ★ 为什么用「同缩进 } 收尾」切块、而不是括号配平：
 *   括号配平还要处理字符串 / 模板字面量里的 `}`（注释已由 stripComments 剥掉），
 *   成本高、易错；本仓风格稳定（catch 块以同缩进 `}` 结束）。
 *   万一将来风格变了，A8 的正向自检样本会先红 —— 这是刻意的。
 */
function findMockFallbacks(text) {
  const lines = text.split('\n')
  const hits = []
  const CATCH_RE = /^(\s*)\}\s*catch\s*[({]/
  const ASSIGN_RE = /\.value\s*=\s*(?:\[\.\.\.)?(?:mock|MOCK)[A-Za-z0-9_]*/
  for (let i = 0; i < lines.length; i++) {
    const m = CATCH_RE.exec(lines[i])
    if (!m) continue
    const indent = m[1].length
    let end = lines.length - 1
    for (let k = i + 1; k < lines.length; k++) {
      const lead = /^\s*/.exec(lines[k])[0].length
      if (/^\s*\}/.test(lines[k]) && lead <= indent) {
        end = k
        break
      }
    }
    const body = lines.slice(i, end + 1)
    const bad = body.find((l) => ASSIGN_RE.test(l))
    if (bad) hits.push({ line: i + 1, text: bad.trim() })
  }
  return hits
}

/**
 * 三条模块说明符形态。
 *
 * ★ 为什么要有三条、且第一条不带 `[^\n]` 约束：
 *   1) `from '...'`      —— 覆盖 `import ... from` / `export ... from`，
 *                           且**必须**容忍跨行（本仓 `ReviewConfig.vue` /
 *                           `AdDashboardConfig.vue` 的 import 都是多行的）
 *   2) `import('...')`   —— 动态 import（`useChatOrchestrator.ts` 大量使用）
 *   3) 裸 `import '...'` —— 副作用 import
 */
const FROM_RE = /\bfrom\s*['"]([^'"]+)['"]/g
const DYN_RE = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g
const BARE_RE = /(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g

/** 收集一段源码里的全部模块说明符（调用方负责先 `stripComments`） */
function collectSpecifiers(text) {
  const out = []
  for (const rx of [FROM_RE, DYN_RE, BARE_RE]) {
    rx.lastIndex = 0
    let m
    while ((m = rx.exec(text))) out.push(m[1])
  }
  return out
}

/** 归一化：反斜杠 → 正斜杠；去掉查询串；去掉尾部斜杠 */
function normalizeSpecifier(spec) {
  return String(spec || '')
    .replace(/\\/g, '/')
    .split('?')[0]
    .replace(/\/+$/, '')
}

/**
 * 判断一个模块说明符是否指向某个退役目标。
 *
 * 命中三种写法（`retiredRel` 形如 `mock/reviewDashboard.ts`）：
 *   `@/mock/reviewDashboard`     —— vite 别名（本仓主流写法）
 *   `./mock/reviewDashboard` / `../mock/reviewDashboard` —— 相对路径
 *   `mock/reviewDashboard`       —— 裸相对
 * 后缀 `.ts` / `.vue` 可省（TS 允许省略扩展名），所以两个方向都要判。
 */
function specifierTargets(retiredRel, spec) {
  const norm = normalizeSpecifier(spec)
  const noExt = norm.replace(/\.(ts|tsx|js|vue)$/, '')
  const target = retiredRel.replace(/\.(ts|tsx|js|vue)$/, '')
  const targetBase = target.split('/').pop()
  if (!targetBase) return false

  // 完整路径命中（`@/mock/x` / `./mock/x` / `mock/x`）
  if (noExt === target || noExt.endsWith('/' + target)) return true

  // 相对同目录的简写（`./x` / `../mock/x` 的极端形态）：只认 basename 且必须落在 mock 面
  const base = noExt.split('/').pop()
  if (base === targetBase && /(^|\/)mock(\/|$)/.test(noExt)) return true

  return false
}

// ---------------------------------------------------------------- 读盘盘点

function walk(root) {
  const out = []
  const stack = [root]
  while (stack.length) {
    const dir = stack.pop()
    let entries
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      continue
    }
    for (const e of entries) {
      if (e.name === 'node_modules' || e.name === 'dist' || e.name === '.vite') continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) stack.push(p)
      else if (EXTS.some((x) => e.name.endsWith(x))) out.push(p)
    }
  }
  return out
}

const retiredKeys = Object.keys(RETIRED)

/** A1 靶：退役文件在磁盘上是否还存在 */
const stillOnDisk = retiredKeys.filter((rel) =>
  fs.existsSync(path.join(SRC_ROOT, rel)),
)

const files = walk(SRC_ROOT)

/** A2 靶：谁还在 import 退役目标 */
const offenders = []
/** A7 靶：谁在 catch 块里回退内联 mock（★ 第 279 轮新增） */
const mockFallbacks = []
let specifierCount = 0
for (const f of files) {
  let text
  try {
    text = stripComments(fs.readFileSync(f, 'utf8'))
  } catch {
    continue
  }
  for (const h of findMockFallbacks(text)) {
    mockFallbacks.push({
      file: path.relative(SRC_ROOT, f).replace(/\\/g, '/'),
      line: h.line,
      text: h.text,
    })
  }
  const specs = collectSpecifiers(text)
  specifierCount += specs.length
  for (const spec of specs) {
    for (const rel of retiredKeys) {
      if (specifierTargets(rel, spec)) {
        offenders.push({
          file: path.relative(SRC_ROOT, f).replace(/\\/g, '/'),
          spec,
          target: rel,
        })
      }
    }
  }
}

/** A3/A4 自检样本 */
const SELF_HIT_MULTILINE = [
  "import {",
  "  REVIEW_ASINS,",
  "  DAILY_SALES,",
  "} from '@/mock/reviewDashboard'",
].join('\n')
const SELF_HIT_DYNAMIC = "const m = await import('@/mock/reviewDashboard')"
const SELF_HIT_RELATIVE = "import x from '../mock/reviewDashboard'"
const SELF_MISS = "import { fetchWeeklyReport } from '@/api/review'"

/** A7/A8 自检样本（★ 第 279 轮） */
const SELF_FALLBACK_SPREAD = [
  '  } catch (e) {',
  "    console.warn('拉取失败', e)",
  '    items.value = [...MOCK_CANDIDATES]',
  '  }',
].join('\n')
const SELF_FALLBACK_DIRECT = [
  '  } catch (e) {',
  '    plans.value = mockPlans',
  '  }',
].join('\n')
// ★ 反样本一：正确的修法（置空 + 记原因）—— 必须**不**命中
const SELF_FALLBACK_HONEST = [
  '  } catch (e) {',
  "    console.warn('拉取失败', e)",
  '    items.value = []',
  "    loadError.value = (e as Error)?.message || '选品库加载失败'",
  '  }',
].join('\n')
// ★ 反样本二：不在 catch 块里的同名标识符（本仓真实存在：mock/toolExecutors.ts）
const SELF_FALLBACK_OUTSIDE = "  const mockKeywords = [\n    'a',\n  ]"

function selfHit(sample) {
  return collectSpecifiers(sample).some((s) =>
    retiredKeys.some((rel) => specifierTargets(rel, s)),
  )
}

// ---------------------------------------------------------------- 盘面读数

console.log('前端 mock 退役门禁 —— 盘面读数')
console.log(`  扫描根 ${SRC_ROOT}`)
console.log(`  退役清单 ${retiredKeys.length} 条：${retiredKeys.join(', ') || '(空)'}`)
console.log(`  扫描面 ${files.length} 个文件 / ${specifierCount} 个模块说明符`)
if (stillOnDisk.length) {
  console.log(`  ★ 仍在磁盘上的退役文件：${stillOnDisk.join(', ')}`)
} else {
  console.log('  ★ 退役文件均已从磁盘删除 ✓')
}
if (offenders.length) {
  console.log(`  ★ 仍在引用退役 mock 的位置 ${offenders.length} 处：`)
  for (const o of offenders) console.log(`      ${o.file}  <- ${o.spec}`)
} else {
  console.log('  ★ 无任何引用 ✓')
}
if (mockFallbacks.length) {
  console.log(`  ★ catch 块内回退内联 mock 的位置 ${mockFallbacks.length} 处：`)
  for (const o of mockFallbacks) console.log(`      ${o.file}:${o.line}  ${o.text}`)
} else {
  console.log('  ★ 无 catch 内联 mock 兜底 ✓')
}
console.log(
  `  自检 跨行=${selfHit(SELF_HIT_MULTILINE)} 动态=${selfHit(SELF_HIT_DYNAMIC)} ` +
    `相对=${selfHit(SELF_HIT_RELATIVE)} 反向对照=${selfHit(SELF_MISS)}`,
)
for (const rel of retiredKeys) {
  const info = RETIRED[rel]
  console.log(`  · ${rel}  [${info.round}]  替代：${info.replacement}`)
}

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

for (const rel of retiredKeys) {
  check(`A1 退役文件已删除：${rel}`, () => {
    assert(
      !fs.existsSync(path.join(SRC_ROOT, rel)),
      `${rel} 还在磁盘上 —— 登记成"已退役"却留着文件，下一个人会以为它还能用（也随时可能被重新 import）`,
    )
  })
}

check('A2 没有任何源码在 import 已退役的 mock', () => {
  assert(
    offenders.length === 0,
    `${offenders.length} 处仍在引用退役 mock：\n` +
      offenders.map((o) => `      ${o.file}  <- ${o.spec}`).join('\n') +
      '\n  假数据就是这样悄悄流回来的：类型不报、测试不红、界面看不出来。',
  )
})

check('A3 自检：匹配器能抓到「跨行 import」形态', () => {
  assert(
    selfHit(SELF_HIT_MULTILINE),
    '自检样本（跨行 import）未被命中 —— 匹配器坏了。' +
      '历史事故：`[^;\\n]*?` 版本的扫描器漏掉本仓所有多行 import（AdDashboardConfig.vue 就是这么漏的）',
  )
})

check('A4 自检：匹配器能抓到「动态 import」与「相对路径」形态', () => {
  assert(selfHit(SELF_HIT_DYNAMIC), '动态 `import(...)` 形态未被命中')
  assert(selfHit(SELF_HIT_RELATIVE), '相对路径 `../mock/x` 形态未被命中')
})

check('A5 反向对照：匹配器不会误命中非退役模块', () => {
  assert(
    !selfHit(SELF_MISS),
    `自检样本 ${SELF_MISS} 被误判成退役目标 —— 匹配器过宽，会产生假红灯（假红灯同样会让人把门禁关掉）`,
  )
})

check(`A6 扫描面规模达标（>= ${MIN_FILES_SCANNED} 文件 / >= ${MIN_SPECIFIERS} 说明符）`, () => {
  assert(
    files.length >= MIN_FILES_SCANNED,
    `只扫到 ${files.length} 个文件（下限 ${MIN_FILES_SCANNED}）—— 扫描根可能指错了，A2 会因为"什么都没扫到"而永远通过`,
  )
  assert(
    specifierCount >= MIN_SPECIFIERS,
    `只扫到 ${specifierCount} 个模块说明符（下限 ${MIN_SPECIFIERS}）—— 说明匹配器退化了`,
  )
})

check('A7 没有任何 catch 块把读失败回退成内联 mock', () => {
  assert(
    mockFallbacks.length === 0,
    `${mockFallbacks.length} 处在 catch 里回退内联 mock：\n` +
      mockFallbacks.map((o) => `      ${o.file}:${o.line}  ${o.text}`).join('\n') +
      '\n  ★ 读失败必须**置空 + 记错误态**（由界面显示「加载失败」+ 重试），' +
      '\n    而不是伪造一屏假数据 —— 假 ASIN / 假账单 / 假价格与真数据**同形**，' +
      '\n    类型不报、测试不红、界面也看不出来（这正是它们能活到第 279 轮的原因）。',
  )
})

check('A8 自检：回退匹配器能抓两种形态、且不误命中（2 正 / 2 反）', () => {
  assert(
    findMockFallbacks(SELF_FALLBACK_SPREAD).length === 1,
    '自检样本（`items.value = [...MOCK_X]`）未被命中 —— 匹配器坏了',
  )
  assert(
    findMockFallbacks(SELF_FALLBACK_DIRECT).length === 1,
    '自检样本（`plans.value = mockX`）未被命中',
  )
  assert(
    findMockFallbacks(SELF_FALLBACK_HONEST).length === 0,
    '正确的修法（置空 + loadError）被误判成回退 mock —— 假红灯',
  )
  assert(
    findMockFallbacks(SELF_FALLBACK_OUTSIDE).length === 0,
    '不在 catch 块里的 `mockXxx` 被误判 —— 判据的作用域比断言宽了',
  )
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n前端 mock 退役门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  `前端 mock 退役门禁通过（${retiredKeys.length} 个退役文件已删净 ✓ / 扫描 ${files.length} 文件 ${specifierCount} 说明符无残留 ✓ / 自检 3 正 1 反 ✓）`,
)

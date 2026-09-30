#!/usr/bin/env node
/**
 * 差评面板 ↔ 风险识别链路门禁（★ 第 299 轮 P1）
 *
 * 它保护什么
 * ==========
 * P0 已经把「这条差评是不是威胁 / 索赔 / A-to-Z / 投诉」判出来了
 * （`modules/trade/risk_scan.py`），但那份能力**只有脚本能到达**：没有端点、
 * 界面看不见 ⇒ 能力在而用户摸不到，等于没有。P1 把它接到了面板上：
 *   · 后端新增只读端点 `GET /trade/reviews/risk`（service.scan_reviews_risk）；
 *   · 前端点【🛡 风险识别】→ 命中的差评**标红并置顶**。
 *
 * 这条链路横跨两端，任何一半单独改动都会**静默失效**：
 *   · 后端改路径、前端不改 ⇒ 前端 404，被 catch 成「风险识别失败」，
 *     看起来像后端偶发故障，不像路径写错；
 *   · **前端自己排一次序** ⇒ 「谁该置顶」有了两份实现，两边不一致时没人报错；
 *   · 前端自己写一份类别 / 等级中文名 ⇒ 后端改了名，界面还显示旧名；
 *   · 前端不消费 `degraded` ⇒ 一次「没扫成」的扫描在界面上变成「全部清白」。
 *
 * 判据组
 * ======
 *   R1 跨端路径对账：api 层 `scanReviewsRisk` 请求的（方法 + 路径）必须与后端
 *      `router.py` 登记的一致（占位符段归一成 `{}` 再比）
 *   R2 面板**确实在用**它（import 之外还有调用点）
 *   R3 面板**不得自己排序**（`排序`/`置顶` 的唯一真源在后端 service）
 *   R4 面板不得写死类别码（`r1..r5`）—— 类别词汇归后端
 *   R5 面板不得自写等级中文名（`高危/中危/低危/未定论`）—— 必须用后端 `level_labels`
 *   R6 面板必须消费 `degraded`（降级不得被吞掉）
 *   R7 三态不得压成两态：面板必须同时出现「未定论」与 `is_risk` 两条分支
 *   R8 后端 `router.py` 在该端点里也不得排序（排序只在 service 一处）
 *   R9 反向自检：把错的路径喂给比对器必须报错，且归一化器必须能把两边归一成同一个键
 *   R10 防空跑：四个源文件都真的读到内容，且 `scanReviewsRisk` 能被抽出来
 *   R11 证据块必须由「可执行的定论」守卫（不得只判 `hits.length`）
 *   R12 深扫必须按调用放宽超时（全局 30s 会掐断 43s 的深扫）
 *   R13 清单指纹 `listKeyOf` 是唯一实现，且必须含 days / maxRating / 行 id 三成分
 *   R14 reload 里**不得有**无条件的 `clearRisk()`：每一处都必须挂在
 *       「`listKeyOf(...) !== riskListKey.value`」之下（切视图不得重置判定）
 *   R15 反向自检：R14 的条件判据必须能判出「无条件 clearRisk」（非恒真），
 *       且不能把受保护的写法判红（非假红）
 *
 * 可注入（供反向验证用，不设则走真实路径）
 * ======================================
 *   RISK_API_FILE / RISK_PANEL_FILE / RISK_ROUTER_FILE
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const API_FILE = process.env.RISK_API_FILE || path.join(ROOT, 'src', 'api', 'trade.ts')
const PANEL_FILE = process.env.RISK_PANEL_FILE
  || path.join(ROOT, 'src', 'components', 'TaskConfigPanel', 'configs', 'ReviewDeskConfig.vue')
const ROUTER_FILE = process.env.RISK_ROUTER_FILE
  || path.join(ROOT, '..', 'backend', 'modules', 'trade', 'router.py')
/** 全局超时的**真源** —— R12 不再硬编码 30s，而是从这里读 */
const REQUEST_FILE = process.env.RISK_REQUEST_FILE
  || path.join(ROOT, 'src', 'api', 'request.ts')
/** 后端分类学真源 —— R19 的类别中文名从**这里读**，不在本门禁里另写一份词表 */
const TAXONOMY_FILE = process.env.RISK_TAXONOMY_FILE
  || path.join(ROOT, '..', 'backend', 'modules', 'trade', 'risk_scan.py')

/** 前端 api 里被登记的入口 */
const WANTED = ['scanReviewsRisk']

const read = (p) => {
  if (!fs.existsSync(p)) throw new Error(`文件不存在：${p}`)
  return fs.readFileSync(p, 'utf8')
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

/**
 * 归一成「相对 prefix」的形态 ⇒ 只比「方法 + 段序 + 字面段」。
 * ★ 前端写 `/trade/reviews/risk`、后端写 `/reviews/risk`，两者都是**相对**
 *   `/api/v1/trade` 的；给它们补前缀会得到 `/api/v1/trade/trade/...` ⇒ 正确路径
 *   反而判不出（假红）。所以统一**剥**前缀。
 */
function normPath(p) {
  let s = String(p).replace(/\$\{[^}]*\}/g, '{}').replace(/\{[^}]*\}/g, '{}')
  s = s.replace(/^\/api\/v1\/trade/, '').replace(/^\/trade/, '')
  return s.startsWith('/') ? s : '/' + s
}

/** 从 api 文件里取某导出函数真正请求的 (方法, 路径模板) */
function apiCall(src, fnName) {
  const re = new RegExp(
    `export\\s+async\\s+function\\s+${fnName}\\s*\\([\\s\\S]*?\\)[^{]*\\{([\\s\\S]*?)\\n\\}`,
  )
  const m = src.match(re)
  assert(m, `未在 api 文件里找到函数 ${fnName}（判据会空跑）`)
  const call = m[1].match(
    /request\s*\.\s*(get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*([`'"])([\s\S]*?)\2/,
  )
  assert(call, `${fnName} 函数体里没找到 request.<verb>(...)`)
  return { method: call[1].toUpperCase(), path: call[3].trim() }
}

/** 后端 `@router.<verb>("<path>")` 全表 */
function routerEntries(src) {
  const out = []
  const re = /@router\.(get|post|put|patch|delete)\(\s*(['"])([^'"]+)\2/g
  let m
  while ((m = re.exec(src))) out.push({ method: m[1].toUpperCase(), path: m[3] })
  return out
}

/**
 * 剥掉 TS/Vue 里的注释 —— 判据不许被注释骗过。
 *
 * ★ 本仓铁律：源码字符串判据会被注释 / docstring 骗过。本门禁自己就踩过：
 *   实现里写了一句「不得出现 `.sort(`」的**说明性注释**，未剥注释的判据
 *   当场把自己判红。
 * ★ 与兄弟门禁 `check-review-desk-systemic.cjs` 的差别：这里的对象是 `.vue`，
 *   还有 **HTML 注释** `<!-- -->`（模板区），也必须一起剥。
 */
function stripComments(src) {
  return src
    .replace(/<!--[\s\S]*?-->/g, '')          // HTML 注释（.vue 模板区）
    .replace(/\/\*[\s\S]*?\*\//g, '')         // 块注释
    .replace(/(^|[^:\\])\/\/[^\n]*/g, '$1')   // 行注释（避开 http:// 与转义）
}
const panelCode = stripComments(read(PANEL_FILE))

/**
 * 只看**模板区**（`<script` 之前）。
 *
 * ★ 窗口必须收窄（反向注入实测的教训）：P1b 新增的 `showRiskEvidence()`
 *   守卫住在脚本区，体内同样有 `is_risk` 与 `decision === 'unknown'`。
 *   对整份文件做 `includes('is_risk')` 会被这处同形代码满足 ⇒
 *   把模板里的三态分支整段删掉也照样「通过」（F7a / F7b 双漏检）。
 *   三态是**界面分支**，只可能住在模板里，所以窗口就该是模板。
 */
const templateCode = panelCode.split(/<script[\s\S]*/)[0]

const apiSrc = read(API_FILE)
const routerSrc = read(ROUTER_FILE)

/**
 * 后端第 300 轮落地的**分层读数**：面板必须把它们显示出来。
 *
 * ★ 为什么这算「守卫」而不是「美化」：方案里写了三条通道（规则预筛 / 跳过 /
 *   批量），落地时只做其中一条、界面上一句不显示 —— 就叫**执行缩水**，
 *   而且没有人会发现（功能看起来是好的，只是白花了钱）。
 */
const LAYER_READOUT_KEYS = ['semantic_sent', 'semantic_skipped', 'llm_calls']
function missingLayerReadouts(src) {
  return LAYER_READOUT_KEYS.filter((k) => !src.includes(`riskMeta.${k}`))
}

/** 取出 `scanReviewsRisk(...)` 的**调用点**实参文本（不是 api 定义处） */
function riskCallArgs(src) {
  const i = src.indexOf('scanReviewsRisk({')
  if (i < 0) return null
  const j = src.indexOf('})', i)
  return j < 0 ? null : src.slice(i, j + 2)
}

/** 全局超时（`request.ts`）—— 深扫的 per-call timeout 必须明显大于它 */
function globalTimeoutMs() {
  const m = read(REQUEST_FILE).match(/timeout\s*:\s*(\d[\d_]*)/)
  assert(m, '没在 request.ts 里读到全局 timeout ⇒ R12 会空跑')
  return Number(m[1].replace(/_/g, ''))
}

// ---------------------------------------------------------------- R10 防空跑
check('R10 源文件都读到了内容（防空跑）', () => {
  assert(apiSrc.length > 1000, `api 文件只有 ${apiSrc.length} 字节 ⇒ 读错了文件`)
  assert(panelCode.length > 5000, `面板文件只有 ${panelCode.length} 字节 ⇒ 读错了文件`)
  assert(routerSrc.length > 3000, `router 只有 ${routerSrc.length} 字节 ⇒ 读错了文件`)
  // 防空跑：两条判据的关键串必须真的在文件里，否则后面的断言全是恒真
  for (const kw of ['scanReviewsRisk', 'riskMap', 'riskMeta']) {
    assert(panelCode.includes(kw), `面板里找不到 ${kw} ⇒ 判据会空跑`)
  }
})

// ---------------------------------------------------------------- R1 跨端路径对账
const beIndex = new Set(routerEntries(routerSrc).map((e) => `${e.method} ${normPath(e.path)}`))

check('R1 api 层请求的路径与后端 router 登记一致', () => {
  assert(beIndex.size > 5, `后端只解析出 ${beIndex.size} 条路由 ⇒ 解析器失明，判据无效`)
  const bad = []
  for (const fn of WANTED) {
    const { method, path: p } = apiCall(apiSrc, fn)
    const key = `${method} ${normPath(p)}`
    if (!beIndex.has(key)) bad.push(`${fn} -> ${key}`)
  }
  assert(!bad.length, `前端请求的端点后端没有：${bad.join(' / ')}（写了没挂 ⇒ 前端永远 404）`)
})

// ---------------------------------------------------------------- R9 反向自检
check('R9 反向自检：错的路径必须被 R1 判红（证明 R1 非恒真）', () => {
  assert(
    !beIndex.has('GET ' + normPath('/trade/reviews/risk-zzz')),
    'R1 的比对器连错路径都放行 ⇒ 它恒真，等于没守',
  )
  assert(
    normPath('/trade/reviews/risk') === normPath('/reviews/risk'),
    '前缀归一化失效 ⇒ 正确路径反而判不出，R1 是假红',
  )
})

// ---------------------------------------------------------------- R2 面板确实在用
check('R2 面板真的调了这个 api（不只是 import）', () => {
  const bad = WANTED.filter(
    (fn) => (panelCode.match(new RegExp(`${fn}\\s*\\(`, 'g')) || []).length < 1,
  )
  assert(!bad.length, `面板里只有 import、没有调用：${bad.join(' / ')} —— 后端有端点不等于前端在用`)
})

// ---------------------------------------------------------------- R3 不自排序
check('R3 面板不得自己排序（「置顶」的唯一真源在后端）', () => {
  // ★ 为什么这条是本轮最要紧的：置顶 = 按风险排序，而「谁风险高」是**判定**。
  //   界面再排一次 ⇒ 同一判定两份实现，两边不一致时谁都不报错。
  //   面板只允许「按后端给的 id 序列重排」（一次查表 + 拼接），不允许比较大小。
  assert(
    !/\.sort\s*\(/.test(panelCode) && !/\bsorted\s*\(/.test(panelCode),
    '面板里出现了 sort ⇒ 排序有了第二份实现；顺序必须由后端给',
  )
  assert(
    panelCode.includes('riskOrder'),
    '面板没有按后端返回的顺序重排（riskOrder 不见了）',
  )
})

// ---------------------------------------------------------------- R4 类别码不写死
check('R4 面板不得写死类别码（r1..r5 归后端）', () => {
  const m = panelCode.match(/['"`]r[1-5]['"`]/g) || []
  assert(!m.length, `面板里写死了类别码 ${m.join(',')} —— 类别词汇与中文名都归后端`)
})

// ---------------------------------------------------------------- R5 等级中文名
check('R5 等级中文名必须取自后端 level_labels', () => {
  assert(
    panelCode.includes('level_labels'),
    '面板没有使用后端下发的 level_labels ⇒ 等级名要么自己写了一份、要么没显示',
  )
  const local = ['高危', '中危', '低危', '未定论'].filter((w) => panelCode.includes(w))
  // ★ 例外只有一处：三态分支里必须能把 `unknown` 说成「未定论」（那是**定论**名，
  //   不是**等级**名；后端 LEVEL_LABELS 里恰好也叫「未定论」，但界面上这一处
  //   是从 `decision === 'unknown'` 推出来的，属于状态标签而非等级映射）。
  const hard = local.filter((w) => w !== '未定论')
  assert(!hard.length, `面板里写死了等级中文名 ${hard.join('/')} —— 真源是后端 LEVEL_LABELS`)
})

// ---------------------------------------------------------------- R6 降级必须消费
check('R6 面板必须消费 degraded（降级不得被吞掉）', () => {
  // ★ fail-closed 的界面侧一半：服务端「没扫成」必须能被用户看见。
  //   面板不读 degraded ⇒ 一次没扫成的扫描显示成「全部清白」。
  assert(
    panelCode.includes('degraded'),
    '面板没有消费 degraded ⇒ 语义通道不可用时界面看不出区别（失败被伪装成通过）',
  )
})

// ---------------------------------------------------------------- R7 三态不压成两态
check('R7 三态不得压成两态（未定论与 is_risk 是两条分支）', () => {
  // ★ 窗口是**模板区**，不是整份文件 —— 理由见 `templateCode` 的注释。
  assert(
    templateCode.includes('is_risk'),
    '模板里没有用后端的 is_risk 判定 ⇒ 命中口径可能自己算了一遍',
  )
  // ★ 必须钉 **`decision === 'unknown'` 这条分支本身**，不能只查 `unknown` 子串 ——
  //   面板里还有 `riskMeta.unknown_count`（计数），只查子串的话把未定论分支删掉
  //   也照样命中（反向注入实测：判据失明）。
  assert(
    /decision\s*===\s*['"]unknown['"]/.test(templateCode),
    '模板里没有「未定论」这条分支 ⇒ 三态被压成两态（未定论被当成干净）',
  )
})

// ---------------------------------------------------------------- R11 证据块守卫
check('R11 证据块必须由「可执行的定论」守卫（不得只判 hits 非空）', () => {
  // ★ 为什么：规则通道**只命中 r5（高情绪）**时定论是 `clean`。
  //   证据块若只判 `hits.length`，一张**没有任何风险标记**的干净卡片上会出现
  //   一行红字类别名（`.rd-risk-hit-cat` 用 `--danger-strong`）——
  //   字面为真、暗示为假。第 299 轮真机实测撞到过。
  const tag = panelCode.match(/<div[^>]*class="rd-risk-ev"[^>]*>/)
  assert(tag, '面板里找不到证据块（.rd-risk-ev）⇒ 判据会空跑')
  assert(
    /showRiskEvidence\s*\(/.test(tag[0]),
    '证据块的渲染条件不是 showRiskEvidence ⇒ 干净卡片可能挂上红字证据',
  )
  const fn = panelCode.match(/function\s+showRiskEvidence[\s\S]*?\n\}/)
  assert(fn, '找不到 showRiskEvidence 的实现')
  assert(/is_risk/.test(fn[0]), '守卫里没有 is_risk ⇒ 命中四类也进不来')
  assert(
    /decision\s*===\s*['"]unknown['"]/.test(fn[0]),
    '守卫里没有「未定论」分支 ⇒ 未定论的证据（为什么判不出来）会被藏掉',
  )
})

// ---------------------------------------------------------------- R8 后端端点也不排序
check('R8 后端 router 在该端点里也不得排序（排序只在 service 一处）', () => {
  assert(
    !/\.sort\s*\(/.test(routerSrc) && !/\bsorted\s*\(/.test(routerSrc),
    'router.py 里出现了排序 ⇒ 排序有了第二份实现（真源在 service._RISK_DECISION_RANK）',
  )
})

// ---------------------------------------------------------------- R12 深扫超时
/**
 * 从 `open` 处的 `openChar` 出发，用**迷你词法器**配平到对应的 `closeChar`。
 *
 * ★ 为什么要自己数而不是正则：正则数不了嵌套括号（`params?: { ... }` 里就有一层），
 *   而且会被字符串 / 注释里的括号带偏（`'/a/b'`、`// )` 之类）。
 */
function matchPair(src, open, openChar, closeChar) {
  let depth = 0
  let j = open
  while (j < src.length) {
    const c = src[j]
    const two = src.slice(j, j + 2)
    if (two === '//') { const nl = src.indexOf('\n', j); j = nl < 0 ? src.length : nl; continue }
    if (two === '/*') { const e = src.indexOf('*/', j + 2); j = e < 0 ? src.length : e + 2; continue }
    if (c === "'" || c === '"' || c === '`') {
      j++
      while (j < src.length && src[j] !== c) j += src[j] === '\\' ? 2 : 1
      j++
      continue
    }
    if (c === openChar) depth++
    else if (c === closeChar) { depth--; if (depth === 0) return j }
    j++
  }
  return -1
}

/**
 * 取出具名函数的**函数体**（`{` 到配平 `}`），不含花括号本身。
 *
 * ★ 为什么要跳过形参表：`scanReviewsRisk(params?: { ... })` 里有一层 Object 类型
 *   花括号，直接取「签名后第一个 `{`」拿到的是**形参类型那一层** ——
 *   于是体里写没写 `timeout` 一律判不出。第 299 轮实测：加了 timeout 仍判「没传」。
 */
function sliceFunctionBody(src, signature) {
  let j = src.indexOf(signature)
  if (j < 0) return null
  j += signature.length
  while (j < src.length && /\s/.test(src[j])) j++
  if (src[j] === '(') {
    const close = matchPair(src, j, '(', ')')
    if (close < 0) return null
    j = close + 1
  }
  const b0 = src.indexOf('{', j)
  if (b0 < 0) return null
  const b1 = matchPair(src, b0, '{', '}')
  return b1 < 0 ? null : src.slice(b0 + 1, b1)
}

check('R12 深扫必须按调用放宽超时（否则必被全局 30s 掐断）', () => {
  // ★ 为什么必须钉（第 299 轮 P1 实测，第 300 轮改了前提）：
  //   第 299 轮后端是**逐条串行**调模型（20 条 = 20 次调用），实测 43.4s，
  //   而全局 timeout 是 30s ⇒ **深扫必然超时**，界面上只留一句
  //   `timeout of 30000ms exceeded`（真机 CDP 撞到过）。
  //   第 300 轮后端改成分层 + 批量（20 条约 2s），但**尾延迟**没消失：
  //   一次批量请求要等服务端模型，且 `core/resilience.py` 对它最多重试 3 次。
  //   判据盯三件事：① deep 调用确实带了 per-call timeout；
  //                ② 该值**明显大于全局值**（不是硬编码一个数就算过）；
  //                ③ 它是**有界的**（不是 0 = 永不超时，那会让失败永远转不成错误）。
  const body = sliceFunctionBody(apiSrc, 'export async function scanReviewsRisk')
  assert(body, '抽不到 scanReviewsRisk 的函数体 ⇒ 判据会空跑（签名变了就修这里）')
  assert(/deep/.test(body), 'timeout 不是按 deep 条件加的 ⇒ 浅层也被拖到超时才报错')
  const t = body.match(/timeout:\s*([A-Za-z_]\w*|\d[\d_]*)/)
  assert(t, 'scanReviewsRisk 没有传 per-call timeout ⇒ 深扫会被全局 30s 掐断')
  let ms
  if (/^\d/.test(t[1])) {
    ms = Number(t[1].replace(/_/g, ''))
  } else {
    const def = apiSrc.match(new RegExp(`const\\s+${t[1]}\\s*=\\s*([\\d_]+)`))
    assert(def, `找不到常量 ${t[1]} 的数值定义 ⇒ 判据读不到真实超时（会空跑）`)
    ms = Number(def[1].replace(/_/g, ''))
  }
  const globalMs = globalTimeoutMs()
  assert(globalMs >= 10000 && globalMs <= 60000, `全局 timeout 读到 ${globalMs}ms，疑似读错文件`)
  assert(
    ms >= globalMs * 3,
    `per-call timeout ${ms}ms 不到全局 ${globalMs}ms 的 3 倍 ⇒ 尾延迟（模型抖动 + 3 次重试）`
      + '会把深扫掐断，界面上只剩一句 timeout exceeded',
  )
})

// ------------------------------------------------- R13 清单指纹（唯一实现）
check('R13 清单指纹 listKeyOf 是唯一实现，且含 days/maxRating/行 id 三成分', () => {
  // ★ 为什么指纹要含这三样（第 300 轮）：
  //   判定（贵，实测深扫 43.4s）与清单（便宜）生命周期不同 ⇒ 必须能区分
  //   「清单没换，别丢判定」与「清单换了，必须丢判定」。
  //     少了 days / maxRating：改了时间窗而恰好 id 没变（小店很常见）会被当成同一份；
  //     少了行 id：期间新来差评/某条被处置后消失，也会被当成同一份
  //       ⇒ 用一份**缺行的旧结论**冒充当前清单。
  const fn = sliceFunctionBody(panelCode, 'function listKeyOf')
  assert(fn, '找不到 listKeyOf 的实现 ⇒ 判据会空跑（改名了就来改这里）')
  for (const part of ['days.value', 'maxRating.value', 'r.id']) {
    assert(fn.includes(part), `listKeyOf 里没有 ${part} ⇒ 指纹少了成分，会把两份清单误判成同一份`)
  }
  // 判据的落点必须真的存在（否则 R14 会「因为找不到 clearRisk 而通过」）
  assert(
    /const\s+riskListKey\s*=\s*ref\(/.test(panelCode),
    '没有 riskListKey 状态 ⇒ 指纹无处记录，R14 会空跑',
  )
  assert(
    /riskListKey\.value\s*=\s*listKeyOf\s*\(/.test(panelCode),
    '扫描成功后没有记下指纹（riskListKey.value = listKeyOf(...)）⇒ 判定永远被判成过期',
  )
  const clearBody = sliceFunctionBody(panelCode, 'function clearRisk')
  assert(clearBody, '找不到 clearRisk 的实现 ⇒ 判据会空跑')
  assert(
    /riskListKey\.value\s*=\s*''/.test(clearBody),
    'clearRisk 没有一起清掉指纹 ⇒ 下一份**恰好同构**的清单会继承这批已不存在的标记，'
      + '把「指纹变了才清」这条判据骗过去',
  )
})

// ------------------------------------------------- R14 切视图不得重置判定
/**
 * reload 体内**每一处** `clearRisk()` 是否都挂在「清单指纹变了」这个条件之下。
 * 返回问题清单（空数组 = 全部受保护）。
 *
 * ★ 判据口径说明：这里盯的不是「出现几次」，而是「**每一处都带条件**」——
 *   将来合法地多一处受保护的清空也不该判红（「恰好 N 处」是钉住旧形态的负资产）。
 */
function reloadClearFailures(source) {
  const body = sliceFunctionBody(source, 'async function reload')
  if (!body) return ['抽不到 reload 的函数体 ⇒ 判据会空跑（签名变了就修这里）']
  const idxs = [...body.matchAll(/clearRisk\s*\(/g)].map((m) => m.index)
  if (!idxs.length) return ['reload 里没有 clearRisk 的落点 ⇒ 指纹判据没了落点，判据会空跑']
  const bad = []
  for (const i of idxs) {
    const before = body.slice(Math.max(0, i - 240), i)
    if (!/listKeyOf\s*\([\s\S]*?\)\s*!==\s*riskListKey\.value/.test(before)) {
      bad.push(`offset ${i}`)
    }
  }
  return bad
}

check('R14 reload 不得无条件清空风险标记（切视图不得重置已跑出来的判定）', () => {
  // ★★★ 第 300 轮：老板实测报的缺陷 —— 点「处置台账」视图后，之前跑出来的
  //   风险识别标记被重置（要重跑 43s）。根因：`reload()` **开头无条件**
  //   `clearRisk()`，而 `switchView()` 每次都 reload ⇒ 那两份视图与「近期差评
  //   清单」无关，却把判定一起作废了。
  //   ★ 修法不是「不清」，而是把判据换成「**这份清单的指纹真的变了**才清」，
  //     并把它收成**唯一写入点**。判据反过来钉住这个口径。
  const bad = reloadClearFailures(panelCode)
  assert(
    !bad.length,
    `reload 里有无条件的 clearRisk（${bad.join(', ')}）⇒ 任何 reload（含 switchView）都会`
      + '作废判定：点一次「处置台账」就得重跑一次 43s 深扫。有效性只允许一个写入点，'
      + '且必须写在 `listKeyOf(items.value) !== riskListKey.value` 之下',
  )
})

// ------------------------------------------------- R15 反向自检（防空跑/防假红）
check('R15 反向自检：R14 的条件判据能判出「无条件 clearRisk」，且不误伤受保护写法', () => {
  const badReload = [
    'async function reload() {',
    '  loading.value = true',
    '  clearRisk()',
    '  try { x() } finally { y() }',
    '}',
    '',
  ].join('\n')
  const goodReload = [
    'async function reload() {',
    "  if (view.value === 'recent' && listKeyOf(items.value) !== riskListKey.value) {",
    '    clearRisk()',
    '  }',
    '}',
    '',
  ].join('\n')
  assert(
    reloadClearFailures(badReload).length > 0,
    '自检失败：**无条件** clearRisk 被判成受保护 ⇒ R14 恒真，等于没守',
  )
  assert(
    reloadClearFailures(goodReload).length === 0,
    '自检失败：受保护的写法被判红 ⇒ R14 是假红（会把正确实现挡在门外）',
  )
  const noClear = ['async function reload() {', '  loading.value = true', '}', ''].join('\n')
  assert(
    reloadClearFailures(noClear).length > 0,
    '自检失败：reload 里根本没有 clearRisk 却被放行 ⇒ 判据会「因为找不到而通过」',
  )
})


// ------------------------------------------------- R16 分层读数必须被消费
check('R16 面板必须消费后端的分层读数（semantic_sent/skipped/llm_calls）', () => {
  // ★ 第 300 轮：后端落地的分层是「规则预筛 → 四类命中跳过语义 → 其余一次批量」，
  //   读数是 semantic_sent / semantic_skipped / llm_calls。
  //   界面一条都不显示 = **执行缩水**：老板看不到省下来的钱花在哪，
  //   也就无法判断这次改动到底有没有生效（功能看起来是好的，只是白花了钱）。
  const missing = missingLayerReadouts(panelCode)
  assert(
    !missing.length,
    `面板没有消费分层读数 ${missing.join(' / ')} ⇒ 后端省了钱但界面上看不见`,
  )
})

check('R17 面板必须在调用点**显式**传 deep（不得依赖后端默认值）', () => {
  // ★ 为什么：`deep` 的默认值是**浅层**（后端 service / router 两处都钉了 False）。
  //   依赖默认值 ⇒ 哪天默认值改了，前端会静默地开始花钱；显式写出来，
  //   这个动作的「贵」就写在调用点上，改默认值的人也能立刻看出影响面。
  const args = riskCallArgs(panelCode)
  assert(args, '找不到 scanReviewsRisk 的调用点 ⇒ R17 会空跑（调用形态变了就来改这里）')
  assert(
    /\bdeep\s*:/.test(args),
    `调用点没有显式传 deep：${args.replace(/\s+/g, ' ')}`,
  )
})

check('R18 反向自检：R16 / R17 的判据都非恒真', () => {
  assert(
    missingLayerReadouts('riskMeta.risk_count').length === LAYER_READOUT_KEYS.length,
    'R16 的比对器连「一个读数都没有」都放行 ⇒ 它恒真，等于没守',
  )
  assert(
    missingLayerReadouts(panelCode).length === 0,
    'R16 把真实面板判红 ⇒ 它是假红（会把正确实现挡在门外）',
  )
  assert(!/\bdeep\s*:/.test('scanReviewsRisk({ limit: 100 })'), 'R17 连「没传 deep」都放行')
  assert(/\bdeep\s*:/.test('scanReviewsRisk({ deep: true })'), 'R17 把正确写法判红（假红）')
})

// ------------------------------------------------- R19 界面不得写死类别中文名
/**
 * 后端 `CATEGORY_LABELS` 的字面值（ipa-friendly 中文名）。
 *
 * ★ 为什么从后端源码读而不是在本文件里抄一份词表：抄一份 = **第三份**同名实现
 *   （后端真源 / 面板 / 门禁各一份），第 302 轮「威胁差评」→「加码要挟」那次改名
 *   就是这么漂掉的。这里string parsing 失败必须**炸**（见下面的 assert），
 *   不允许静默退回空集 —— 空集会让它下面的「不含任何名字」恒真。
 */
function backendCategoryLabels() {
  const src = read(TAXONOMY_FILE)
  const block = src.match(/CATEGORY_LABELS\s*=\s*\{([\s\S]*?)\n\}/)
  assert(block, '没在 risk_scan.py 里找到 CATEGORY_LABELS ⇒ R19 会空跑（结构变了就修这里）')
  // ★ 键是**裸标识符**（`CAT_THREAT: "加码要挟"`），不是引号串 —— 照着 JSON 写会数出 0 个
  const out = [...block[1].matchAll(/[A-Za-z_]\w*\s*:\s*(["'])([\s\S]*?)\1/g)].map((m) => m[2])
  assert(out.length >= 5, `只解析出 ${out.length} 个类别名 ⇒ 解析器失明，R19 会假绿`)
  return out
}

function hardCodedLabels(panelSource, labels) {
  return labels.filter((w) => panelSource.includes(w))
}

check('R19 面板文案不得写死类别中文名（真源是后端 category_labels）', () => {
  // ★ 第 302 轮：判定口径改了（r1「威胁差评」的定义自相矛盾 —— 这条文本**本身就是**
  //   那条已经公开的差评，不可能同时是「还没发出来的筹码」），后端改名成「加码要挟」；
  //   而面板说明里还挂着旧名 ⇒ 界面在说一套、后端在判另一套，且没人报错。
  //   同一意向已经在 R4（类别码）/ R5（等级名）上有守卫，**中文名这半缺失**。
  const bad = hardCodedLabels(panelCode, backendCategoryLabels())
  assert(
    !bad.length,
    `面板里写死了类别中文名 ${bad.join(' / ')} —— 后端下发了 category_labels，`
      + '界面一律从那里取；写死一份就是同一个词表的第二份实现（改名时只有一处跟着走）',
  )
})

check('R20 反向自检：R19 对「原样照抄后端名字」必须判红', () => {
  const labels = backendCategoryLabels()
  // ① 非恒真：把四个名字原样写回面板文案，必须被抓出来
  const injected = '逐条判定「' + labels.join(' / ') + '」四类话术。'
  assert(
    hardCodedLabels(injected, labels).length === labels.length,
    '自检失败：照抄后端全部类别名却被放行 ⇒ R19 恒真，等于没守',
  )
  // ② 非假红：真实面板必须判得过
  assert(
    hardCodedLabels(panelCode, labels).length === 0,
    `自检失败：R19 把真实面板判红了 ⇒ 它是假红：${hardCodedLabels(panelCode, labels).join('/')}`,
  )
})

// ---------------------------------------------------------------- 输出
let failed = 0
for (const [name, err] of results) {
  if (err) { failed++; console.log(`FAIL  ${name}\n        ${err}`) }
  else console.log(`PASS  ${name}`)
}
console.log(`\n---- ${results.length - failed}/${results.length} 通过 ----`)
if (failed) {
  console.log(
    '风险识别链路两端必须成对：后端 `modules/trade/router.py`（GET /reviews/risk）' +
    '+ `modules/trade/service.py`（scan_reviews_risk = 排序与降级判定的唯一真源），' +
    '前端 `api/trade.ts` + `ReviewDeskConfig.vue`。顺序、类别名、等级名、定论三态都只有后端一份。',
  )
  process.exit(1)
}
console.log(`风险识别链路对账通过：${WANTED.join(' / ')} ⇄ /reviews/risk`)

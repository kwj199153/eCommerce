#!/usr/bin/env node
/**
 * 「提示归属」门禁（第 267 轮）
 *
 * ## 为什么需要它
 *
 * 老板报障（原话）：「为什么一点击运营 agent 中间对话区域顶部就弹出字？」
 *
 * 取证结论是三段链叠加，而中间那段是**病根**：
 *
 *   链1 后端  `review_analyst/router.py` 的 `_report`：把**结论**塞进 `message`
 *        （`message = data.get("summary") or f"{label}已生成"`）
 *        ★ **链1 已在后端收口**（第 268 轮 B 档）：`message` 的语义收窄为短回执
 *          （「周报已生成」/「复盘完成」），结论一律由 `data.summary` 承载。
 *          守它的门禁在后端 —— `backend/tests/test_review_analyst_api.py` 的
 *          `test_envelope_message_has_no_payload_ref`（AST 形态判据）。
 *          **只此一处**，本脚本里不重复实现（本仓铁律：同一判定两份实现 ⇒
 *          至少一份永远测不到）。
 *   链2 前端  `api/request.ts` 响应拦截器：**非 GET + 响应体带 `message` ⇒ 无条件
 *        `message.success(data.message)`**  ← 病根
 *   链3 前端  `TaskConfigPanel` 预载：点「运营复盘师」自动发 2 个 POST
 *
 * 于是「点一次 Agent」就弹 2 条绿勾，**文本逐字等于响应体的 `message` 字段**，
 * 且与界面上已经渲染好的看板内容重复。
 *
 * 这条拦截器规则的问题不在「弹了不该弹的」，而在**它替调用点做了决定**：
 * 后端任何 `message` 字段都被当成「给用户的成功回执」，包括
 * 「订单查不到」「工单创建失败」这类**业务结论**（被渲染成绿色「成功」提示）。
 * 而原来的 `silent` 开关只是补丁 —— 它只覆盖「调用方**记得**声明」的场景，
 * 没声明的调用点（对话卡的几个分支）照样刷屏。
 *
 * ## 定稿口径（C 档）
 *
 *   · **成功提示归调用点**：拦截器默认不弹，谁要给回执谁自己 `message.success(...)`；
 *   · **错误提示归拦截器**：4xx/5xx 照旧由拦截器弹（可被 `silentError` 让路）；
 *   · 拦截器**补判一条业务失败通道**：HTTP 200 + `success === false` ⇒ `message.error`
 *     （受 `silentError` 管）—— 否则它既不是 4xx、也不进 error 分支，没人看得见；
 *   · `silent` 开关因此彻底失去语义，全仓清理。
 *
 * ## 判据
 *
 *   ① `src/api/request.ts` 全文**不得**出现 `message.success`（成功提示只能在调用点发）；
 *   ② 响应成功分支块内必须**补判** `data?.success === false`，受 `!response.config.silentError`
 *      管，且必须走 `message.error`；
 *   ③ `AxiosRequestConfig` 声明里不得再有 `silent?: boolean`；
 *   ④ `src/**` 剥注释后不得再出现标识符 `silent`（`silentError` 不受影响）——
 *      `\bsilent\b` 的词边界天然排除 `silentError`；
 *   ⑤ **对账**：`success===false` 的响应点，其消费方若自带**常驻**错误面，
 *      必须显式声明 `silentError`（否则同一个原因两处报）：
 *        · `ad_analysis` 四端点 → `AdDashboardConfig.vue` 的内联横幅 ⇒ `QUIET`
 *        · `customer_service` 工单 2 处 → 对话卡「工单未能创建」 ⇒ `createTicket`
 *        · `review_analyst` 对话（`success = not degraded`）⇒ `chatWithReviewAnalyst`
 *
 * ★ 每条锚点找不到就 **FAIL**（不是「跳过」）—— 「拿不到清单 ≠ 清单为空」。
 * ★ 判据一律跑在**剥离注释后**的源码上（本仓铁律：注释里的旧文案会骗过检查）。
 *   剥注释时**保护 `://`**：否则 `https://…` 会把整行当注释吃掉，反而漏掉真代码。
 *
 * ## 反向注入（见 `.workbuddy/probes/r267_toast_ownership_reverse_inject.py`，13/13 逐条实测能转红）
 *
 *   · 在 `request.ts` 里加一行 `message.success('x')` ⇒ ① 红；
 *   · 删掉 `data?.success === false` 的 if ⇒ ② 红；
 *   · 把 `!response.config.silentError` 去掉 ⇒ ② 红；
 *   · 把补判的 `message.error` 改成 `message.warning` ⇒ ② 红；
 *   · 类型声明里加回 `silent?: boolean` ⇒ ③ 红；
 *   · 任意调用点传 `{ silent: true }` ⇒ ④ 红；
 *   · `AdDashboardConfig` 少传一个 `QUIET` / `QUIET` 不再是 `silentError`
 *     / `createTicket` 去掉 `silentError` / `chatWithReviewAnalyst` 去掉
 *     `silentError` ⇒ ⑤ 红；
 *   · **锚点失效也必须红**（不许静默放行）：接口改名 / 拦截器形参改名 / 派生清单为空
 *     ⇒ ②③⑤a 红。★ 其中「接口改名」这条实测抓到过一个真 bug：`indexOf` 会把
 *     `AxiosRequestConfigX` 当成 `AxiosRequestConfig` 命中（前缀匹配）⇒ 改名后
 *     照样 PASS。已改 `blockByRegex`（词边界 + 紧跟 `{`）。
 *
 * 用法：node scripts/check-toast-ownership.cjs   （0 = 通过；1 = 有漂移）
 */
const fs = require('fs')
const path = require('path')

const FE = path.resolve(__dirname, '..')
const SRC = path.join(FE, 'src')

const read = (p) => fs.readFileSync(path.join(FE, p), 'utf8')

/**
 * 剥离注释：块注释 / HTML 注释 / 行注释。
 * ★ 行注释用 `(^|[^:])//` 保护 `://`（`https://x` 不是注释）。
 */
function stripComments(t) {
  return t
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|[^:])\/\/[^\n]*/gm, '$1')
}

const fails = []
function check(ok, label, detail) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}`)
  if (!ok) {
    if (detail) console.log(`        ${detail}`)
    fails.push(label)
  }
}

/** 花括号配对扫描：从 `from`（必须指向 `{`）起，取到与之配对的 `}` 之间 */
function braceAt(src, from) {
  if (src[from] !== '{') return ''
  let depth = 0
  for (let j = from; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') {
      depth--
      if (depth === 0) return src.slice(from + 1, j)
    }
  }
  return ''
}

/**
 * 花括号配对扫描：从 **正则** 命中处之后第一个 `{` 起，取到与之配对的 `}` 之间。
 *
 * ★★ 为什么必须用正则而不是 `indexOf(marker)`（第 267 轮反向注入 J 用例实测）：
 *   `indexOf('export interface AxiosRequestConfig')` 会**把 `AxiosRequestConfigX`
 *   也当成命中**（前缀匹配）⇒ 接口被改名后「定位到声明块」照样 PASS ⇒
 *   锚点失效被静默放行。所以名字后面必须带词边界（`\b`），且要求紧跟 `{`。
 *   本仓铁律：判据的正则禁「能当前缀」。
 */
function blockByRegex(src, re) {
  const m = src.match(re)
  if (!m) return ''
  const open = src.indexOf('{', m.index + m[0].length - 1)
  if (open < 0) return ''
  return braceAt(src, open)
}

/**
 * 取 `export [async] function <name>(…) { … }` 的**函数体**。
 *
 * ★ 为什么不能「取 marker 之后第一个 `{`」：下面这几个函数的**参数**里有类型
 *   字面量（`data: { query: string; … }`），marker 之后第一个 `{` 是那个类型字面量
 *   —— 于是「函数体」会取成参数类型，里面的 `silentError: true` 永远搜不到
 *   （反向注入实测：⑤b/⑤c 会**假红**，看着像代码没写对，其实是判据取错了窗口）。
 *   ⇒ 必须先配对参数表的括号，再取之后的第一个 `{`。
 */
function fnBody(src, name) {
  const m = src.match(new RegExp(`export\\s+(?:async\\s+)?function\\s+${name}\\s*\\(`))
  if (!m) return ''
  const openParen = src.indexOf('(', m.index + m[0].length - 1)
  if (openParen < 0) return ''
  let depth = 0
  let j = openParen
  for (; j < src.length; j++) {
    if (src[j] === '(') depth++
    else if (src[j] === ')') {
      depth--
      if (depth === 0) break
    }
  }
  const openBrace = src.indexOf('{', j)
  if (openBrace < 0) return ''
  return braceAt(src, openBrace)
}

/** 与 `request.ts` 里补判的形态**逐字对齐**（改实现必须同步改这里） */
const RE_COMPLEMENT = /if\s*\(\s*data\?\.success\s*===\s*false\s*&&\s*!response\.config\.silentError\s*\)/
const RE_SUCCESS_TOAST = /message\.success\s*\(/
const RE_BARE_SILENT = /\bsilent\b/

console.log('=== 提示归属门禁（第 267 轮）===')

// ---------------- ① request.ts 不得再自动弹成功提示 ----------------
const P_REQ = 'src/api/request.ts'
let reqRaw = ''
try {
  reqRaw = read(P_REQ)
} catch (e) {
  reqRaw = ''
}
check(reqRaw.length > 0, '① 读到 src/api/request.ts',
  `读不到 ${P_REQ} —— 拦截器是本次改造的唯一产地，拿不到它**不许**放行`)

const req = stripComments(reqRaw)
check((req.match(RE_SUCCESS_TOAST) || []).length === 0,
  '① request.ts 全文无 message.success（成功提示只能在调用点发）',
  '拦截器一旦自己弹成功提示，就会替调用点做决定 —— 正是「点击运营 Agent 就弹字」的病根；'
  + '要回执请在调用点自己 message.success(...)')

// ---------------- ② 成功分支必须补判 success === false ----------------
const successBlock = blockByRegex(req, /\bresponse\s*:\s*AxiosResponse\s*\)\s*=>\s*\{/)
check(successBlock.length > 0, '② 定位到响应成功分支块（(response: AxiosResponse) => { … }）',
  '拦截器被重构 / 改了形参名？锚点失效必须 FAIL 而不是放行')

check(RE_COMPLEMENT.test(successBlock),
  '② 成功分支补判 data?.success === false 且受 !response.config.silentError 管',
  '缺这条补判 ⇒ 「HTTP 200 + 业务失败」既不是 4xx、也不进 error 分支 ⇒ 失败**没人看得见**'
  + '（响应点：ad_analysis 六处 + customer_service 工单两处）')

check(/message\.error\s*\(/.test(successBlock),
  '② 补判走 message.error（不是 warning / 静默）',
  '业务失败必须是错误级提示；判成 warning 会让「失败」与「提醒」在视觉上不可区分')

// ---------------- ③ 类型声明不得再有 silent ----------------
const ifaceBlock = blockByRegex(req, /\bexport\s+interface\s+AxiosRequestConfig\b\s*\{/)
check(ifaceBlock.length > 0, '③ 定位到 AxiosRequestConfig 声明块',
  '类型声明被改名 / 移走？锚点失效必须 FAIL（注意：`AxiosRequestConfig` 是 '
  + '`AxiosRequestConfigX` 的前缀，所以必须用词边界匹配，不能用 indexOf）')
check(!/\bsilent\s*\?/.test(ifaceBlock),
  '③ AxiosRequestConfig 不再声明 silent 开关',
  '类型上还能写 `silent:` ⇒ TypeScript 不会报错，下一个人会继续用它当补丁'
  + '（真正的口径是「成功提示归调用点」）')

// ---------------- ④ 全仓不得再出现裸 silent ----------------
const walk = (dir, out = []) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(ts|vue)$/.test(e.name)) out.push(p)
  }
  return out
}
const files = walk(SRC)
check(files.length > 100, '④ 扫到 src/** 文件数 > 100',
  `只扫到 ${files.length} 个 —— 扫描面太小，下面的「零命中」会退化成空集恒真`)

const silentHits = []
for (const f of files) {
  const code = stripComments(fs.readFileSync(f, 'utf8'))
  code.split('\n').forEach((line, i) => {
    if (RE_BARE_SILENT.test(line)) {
      silentHits.push(`${path.relative(FE, f).replace(/\\/g, '/')}:${i + 1}  ${line.trim().slice(0, 90)}`)
    }
  })
}
check(silentHits.length === 0, '④ 全仓（剥注释后）再无裸 silent 标识符',
  `命中 ${silentHits.length} 处：\n        ${silentHits.slice(0, 8).join('\n        ')}\n`
  + '        说明：`\\bsilent\\b` 不会命中 `silentError`（词边界），所以这里报的都是真残留')

// ---------------- ⑤ 对账：自带常驻错误面的消费点必须声明 silentError ----------------
console.log('  ---- ⑤ 对账：success===false 的消费方 ----')

// ⑤a 从 api/adAnalysis.ts **派生**端点清单（不是手写「恰好 4 处」）
const P_AD_API = 'src/api/adAnalysis.ts'
const adApi = stripComments(read(P_AD_API))
const adFns = []
for (const m of adApi.matchAll(/export\s+function\s+(\w+)\s*\(/g)) {
  const name = m[1]
  const body = fnBody(adApi, name)
  if (/request\.post\(\s*'\/ad-analysis\//.test(body) && !/\/chat/.test(body)) adFns.push(name)
}
check(adFns.length >= 4, `⑤a 从 api/adAnalysis.ts 派生出 ${adFns.length} 个分析端点函数（≥ 4）`,
  `派生到：${adFns.join(', ')} —— 太少说明锚点过期，下面的断言会退化成空集恒真`)

const P_AD_VUE = 'src/components/TaskConfigPanel/configs/AdDashboardConfig.vue'
const adVue = stripComments(read(P_AD_VUE))
check(/const\s+QUIET\s*=\s*\{\s*silentError:\s*true\s*\}/.test(adVue),
  '⑤a AdDashboardConfig 的 QUIET 常量就是 { silentError: true }',
  '看板自带**常驻**内联横幅（fail() + 重试按钮），拦截器再弹一条就是同一个原因两处报')

const calledInBoard = adFns.filter((n) => new RegExp(`\\b${n}\\s*\\(`).test(adVue))
check(calledInBoard.length >= 4, `⑤a 看板实际调用其中 ${calledInBoard.length} 个分析端点（≥ 4）`,
  `调用：${calledInBoard.join(', ')}`)
const boardBad = calledInBoard.filter((n) => {
  const m = adVue.match(new RegExp(`\\b${n}\\s*\\(([^)]*)\\)`))
  return !m || !/\bQUIET\b/.test(m[1])
})
check(boardBad.length === 0, '⑤a 看板的每个分析端点调用都传 QUIET',
  `未声明 silentError 的调用：${boardBad.join(', ')}\n`
  + '        漏一个的后果：那个 Tab 失败时「横幅 + 红 toast」同时报同一个原因')

// ⑤b 工单：对话卡自带错误面
const csApi = stripComments(read('src/api/customerService.ts'))
const ticketBody = fnBody(csApi, 'createTicket')
check(ticketBody.length > 0, '⑤b 定位到 createTicket',
  '被改名 / 移走？锚点失效必须 FAIL')
check(/silentError:\s*true/.test(ticketBody),
  '⑤b createTicket 声明 silentError（失败由对话卡呈现）',
  '写库失败是 HTTP 200 + success:false + message，而对话卡已把 message 渲染成'
  + '「🎫 工单未能创建」⇒ 拦截器再弹一次就是两处报')

// ⑤c 复盘对话：success = not degraded
const reviewApi = stripComments(read('src/api/review.ts'))
const chatBody = fnBody(reviewApi, 'chatWithReviewAnalyst')
check(chatBody.length > 0, '⑤c 定位到 chatWithReviewAnalyst',
  '被改名 / 移走？锚点失效必须 FAIL')
check(/silentError:\s*true/.test(chatBody),
  '⑤c chatWithReviewAnalyst 声明 silentError',
  '后端 `success = not result.degraded` ⇒ 降级时 HTTP 200 但 success=false，'
  + '拦截器补判会弹 `message`（第 268 轮 B 档后它已是短回执「复盘未取到数据」，'
  + '不再是整篇回复）；但对话卡里那条 `> ⚠️ …` 已经写清了同一个原因 ⇒ '
  + '再弹一次就是同一原因两处报')

// ---------------- 判据自检（防正则恒真 / 恒不匹配）----------------
console.log('  ---- 判据自检 ----')
const SELF = [
  [RE_SUCCESS_TOAST, "message.success(data.message)", 1],
  [RE_SUCCESS_TOAST, "message.error('x')", 0],
  [RE_COMPLEMENT, 'if (data?.success === false && !response.config.silentError) {', 1],
  [RE_COMPLEMENT, 'if (data?.success === false) {', 0],
  [RE_COMPLEMENT, 'if (data?.success == false && !response.config.silentError) {', 0],
  [RE_BARE_SILENT, '{ silent: true }', 1],
  [RE_BARE_SILENT, '{ silentError: true }', 0],
  [RE_BARE_SILENT, 'const silentError = !!config?.silentError', 0],
  [RE_BARE_SILENT, '// 这里不再需要 silent', 1],
  [/\bsilent\s*\?/, 'silent?: boolean', 1],
  [/\bsilent\s*\?/, 'silentError?: boolean', 0],
]
let selfBad = 0
for (const [re, sample, want] of SELF) {
  const got = [...sample.matchAll(new RegExp(re.source, re.flags.includes('g') ? re.flags : re.flags + 'g'))].length
  const ok = got === want
  if (!ok) selfBad++
  check(ok, `自检：${JSON.stringify(sample.slice(0, 46))} 命中 ${got} 次（期望 ${want}）`)
}
// 剥注释器本身也要自检：URL 不许被当成注释吃掉
const stripProbe = stripComments('const u = "https://x.com/a" // tail\nconst v = 1')
check(stripProbe.includes('https://x.com/a'),
  '自检：剥注释保护了 ://（URL 不被误当行注释）',
  `剥离结果是 ${JSON.stringify(stripProbe)} —— 吃掉 URL 会把整行真代码一起删掉，`
  + '于是「零命中」可能是假的')
check(!stripProbe.includes('tail'), '自检：真行注释仍被剥掉', '剥不掉注释 ⇒ 注释里的旧文案会骗过 ④')
check(selfBad === 0, '自检：全部判据既不是恒真也不是恒不匹配')

console.log('')
if (fails.length) {
  console.log(`RESULT: FAIL（${fails.length} 处）—— 提示归属已漂移：拦截器又替调用点做决定，或对账缺声明`)
  process.exit(1)
}
console.log(`RESULT: PASS（成功提示归调用点 · 业务失败有补判 · 裸 silent 0 处 · `
  + `对账 3 组：看板 ${calledInBoard.length} 调用 / 工单 / 复盘对话）`)

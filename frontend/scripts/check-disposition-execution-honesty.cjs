#!/usr/bin/env node
/**
 * 差评处置「**已执行 ≠ 已核准**」诚实性门禁（第 304 轮 P0·A 档）
 *
 * ============================================================================
 * ★ 它治的是什么病
 * ============================================================================
 * 老板问：「差评台账处置后，是不是应该接 API 到平台真实处置？」
 *
 * 取证：`issue_disposition` **零出站调用** —— `modules/trade` 里没有任何 HTTP
 * 客户端（httpx / requests / aiohttp / urllib 全仓命中 0 次），SP-API 与 Shopee
 * 适配层清一色是只读的 `fetch_*`。于是
 *
 *     库里此前**没有任何字段**能回答「平台上做没做」
 *     而界面写着「已发放」+ `effect: '退回部分或全部货款'`
 *
 * 这是**字面为真、暗示为假**：本地确实改了状态，但「钱退回去了」是界面自己编的。
 *
 * A 档的修法不是去接平台 API（那是 B/C 档），而是**先把两个语义在数据层拆开**：
 *   · `issued`   ＝ 本地已核准（券码已生成、回复可对外），平台侧还没动；
 *   · `executed` ＝ 平台上真的执行完了，且有回执（五列 + 人 + 时间 + 凭证）。
 *
 * ============================================================================
 * ★ 为什么必须钉成门禁，而不是「这轮改完就算了」
 * ============================================================================
 * 「已发放」这三个字**没有任何守卫**地活了 8 个轮次 —— 它不是被谁改错的，
 * 是**从来没人判过它**。语义欺诈的复发方式永远是「有人顺手把文案改回顺口的那个
 * 词」，而且不会红。所以这里把「`issued` 不许叫已发放」钉成可执行判据。
 *
 * ============================================================================
 * ★ 判据形态（一律走**代码形态**，不许被注释喂饱）
 * ============================================================================
 * 本仓铁律：源码字符串包含会被注释 / docstring 骗过。典型假绿 —— 在注释里写
 * 「`issued` 不得叫已发放」，字符串判据照样命中 ⇒ **判据被它自己的注释 satisfying**。
 * 所以：先 `stripComments()`，再按**声明行**取字段（`^\s*key\s*:`），而不是子串。
 *
 *   H0  防空跑：四个源文件都得读到内容，且关键串真的存在
 *   H1  `issued` 的中文标签**不得**是「已发放」，且必须含「待平台执行」
 *   H2  必须存在 `executed` 状态，且标签含「平台已执行」
 *   H3  `Disposition` 接口必须带 5 个回执字段（按**声明行**判，不是子串）
 *   H4  跨端路径对账：`recordExecutionReceipt` 的（方法 + 路径）必须与后端一致
 *   H5  面板必须把「登记回执」挂成按钮（`issued` 分支里出现 `confirmAct('receipt')`）
 *   H6  `runBackfill` 必须消费后端 `failed[].reason`（不许猜原因）
 *   H7  面板**不得**出现「多半是」（猜原因的旧毛病）
 *   H8  券 / 退款两个通道的说明必须写明「本系统不调用平台接口」
 *   H9  反向自检：把假的源喂给 H1 / H4 的提取器 ⇒ 必须判红（证明不是恒真）
 */

const fs = require('fs')
const path = require('path')

const ROOT = path.resolve(__dirname, '..')
const API_FILE = process.env.EXEC_API_FILE || path.join(ROOT, 'src', 'api', 'trade.ts')
const PANEL_FILE = process.env.EXEC_PANEL_FILE
  || path.join(ROOT, 'src', 'components', 'TaskConfigPanel', 'configs', 'ReviewDeskConfig.vue')
const ROUTER_FILE = process.env.EXEC_ROUTER_FILE
  || path.join(ROOT, '..', 'backend', 'modules', 'trade', 'router.py')

const RECEIPT_FIELDS = [
  'execution_mode', 'platform_ref', 'executed_by', 'executed_at', 'receipt_note',
]

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }
const read = (p) => {
  if (!fs.existsSync(p)) throw new Error(`文件不存在：${p}`)
  return fs.readFileSync(p, 'utf8')
}

/** 剥三类注释（HTML 模板注释 / 块注释 / 行注释），避免判据被注释喂饱 */
function stripComments(src) {
  return String(src || '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:\\])\/\/[^\n]*/g, '$1')
}

/** 取「对象/接口字面量」的花括号块（停在第一个换行+`}`，够本文件的形态用） */
function blockOf(src, decl) {
  const i = String(src).indexOf(decl)
  if (i < 0) return ''
  const s = src.indexOf('{', i)
  if (s < 0) return ''
  const e = src.indexOf('\n}', s)
  return e < 0 ? src.slice(s) : src.slice(s, e)
}

/** 按**声明行**取字段值（注释里的同名词不算） */
function fieldValue(block, key) {
  const re = new RegExp("^\\s*['\"]?" + key + "['\"]?\\s*:\\s*(['\"`])([\\s\\S]*?)\\1", 'm')
  const m = re.exec(String(block))
  return m ? m[2] : null
}

/** 归一成「相对 prefix」的形态 ⇒ 只比「方法 + 段序 + 字面段」 */
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
  const m = re.exec(String(src))
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

// ============================================================ H0 防空跑
const apiRaw = read(API_FILE)
const panelRaw = read(PANEL_FILE)
const routerRaw = read(ROUTER_FILE)
const apiCode = stripComments(apiRaw)
const panelCode = stripComments(panelRaw)
const templateCode = panelCode.split(/<script[\s\S]*/)[0]

check('H0 三个源文件都读到了内容 + 关键串真的存在（防空跑）', () => {
  assert(apiCode.length > 1000, `api 只有 ${apiCode.length} 字节 ⇒ 读错文件`)
  assert(panelCode.length > 5000, `面板只有 ${panelCode.length} 字节 ⇒ 读错文件`)
  assert(routerRaw.length > 3000, `router 只有 ${routerRaw.length} 字节 ⇒ 读错文件`)
  for (const kw of ['DISPOSITION_STATUS_LABELS', 'recordExecutionReceipt', 'DispositionReview']) {
    assert(apiCode.includes(kw), `api 里找不到 ${kw} ⇒ 后面的断言全是恒真`)
  }
  for (const kw of ['runBackfill', 'CHANNEL_META', 'confirmAct']) {
    assert(panelCode.includes(kw), `面板里找不到 ${kw} ⇒ 后面的断言全是恒真`)
  }
})

// ============================================================ H1 / H2 状态文案
const labelsBlock = blockOf(apiCode, 'DISPOSITION_STATUS_LABELS')

check('H1 `issued` 的中文标签不得是「已发放」，且必须含「待平台执行」', () => {
  assert(labelsBlock, '没取到 DISPOSITION_STATUS_LABELS 的块 ⇒ 判据空跑')
  const v = fieldValue(labelsBlock, 'issued')
  assert(v !== null, '块里没有 issued 字段 ⇒ 判据空跑')
  assert(v !== '已发放', `issued 又写回「已发放」了 —— 那句话暗示平台已执行，而本系统根本没调接口（现值 ${v}）`)
  assert(v.includes('待平台执行'), `issued 标签必须说清「待平台执行」：${v}`)
})

check('H2 必须存在 `executed` 状态，且标签含「平台已执行」', () => {
  const v = fieldValue(labelsBlock, 'executed')
  assert(v !== null, 'DISPOSITION_STATUS_LABELS 里没有 executed ⇒ 平台执行没有落点')
  assert(v.includes('平台已执行'), `executed 的标签必须含「平台已执行」：${v}`)
})

// ============================================================ H3 回执字段
check('H3 `Disposition` 接口必须带 5 个回执字段（按声明行判）', () => {
  const b = blockOf(apiCode, 'export interface Disposition ')
  assert(b, '没取到 Disposition 接口块 ⇒ 判据空跑')
  const missing = RECEIPT_FIELDS.filter(
    (k) => !new RegExp('^\\s*' + k + '\\s*:', 'm').test(b),
  )
  assert(missing.length === 0, `Disposition 缺回执字段：${missing.join(' / ')}`)
})

// ============================================================ H4 跨端路径对账
check('H4 `recordExecutionReceipt` 的（方法 + 路径）与后端一致', () => {
  const fe = apiCall(apiCode, 'recordExecutionReceipt')
  const want = { method: fe.method, path: normPath(fe.path) }
  const hit = routerEntries(routerRaw).some(
    (e) => e.method === want.method && normPath(e.path) === want.path,
  )
  assert(hit, `后端没有登记 ${want.method} ${want.path} —— 前端点了会 404，被 catch 成「随机失败」`)
})

// ============================================================ H5 / H6 / H7 / H8 面板
check('H5 面板必须把「登记回执」挂成按钮（issued 分支里出现 confirmAct(\'receipt\')）', () => {
  assert(
    templateCode.includes("confirmAct('receipt')"),
    'executed 状态没有任何 UI 出口 —— 它是死登记（看得见的终态，点不出来）',
  )
  assert(
    templateCode.includes("disposition.status === 'issued'"),
    '面板里没有 issued 分支 ⇒ 回执按钮无处可挂',
  )
})

check('H6 `runBackfill` 必须消费后端 failed[].reason（不许猜原因）', () => {
  assert(
    panelCode.includes('backfillFailureText(out.failed)'),
    'runBackfill 没把 out.failed 喂给原因聚合 —— 后端白给了 reason',
  )
  assert(
    /f\?\.reason|\.reason\b/.test(panelCode),
    '聚合函数里没读 reason ⇒ 又退回「给不出方案」这种无信息量的说法',
  )
})

check('H6b 失败原因必须按后端 reason_code 分流（不许前端正则猜形状）', () => {
  // ★ 第 304 轮第二次修正：同一句「没有针对「X」的启用规则」底下藏着两种**动作相反**的
  //   情况 —— 真没规则（该配）vs 有规则但这条不满足条件（配了也命中不了）。
  //   靠文案正则分不出来 ⇒ 必须读码。把码读没了，这条会红。
  assert(
    panelCode.includes("reason_code"),
    '聚合函数没读 reason_code ⇒ 又回到「从文案里猜形状」，两种情况会被再说成一件',
  )
  assert(
    panelCode.includes("'no_rule'"),
    '没有把 no_rule（这一类真没规则）单独识别出来',
  )
  assert(
    panelCode.includes("'rule_conditions_unmet'"),
    '没有把 rule_conditions_unmet（有规则但这条不满足）单独识别出来 —— 这正是本轮的错案',
  )
  assert(
    !panelCode.includes('没有针对'),
    '面板里又出现旧文案「没有针对…的启用规则」—— 对「有规则但条件不符」是假陈述',
  )
})

check('H7 面板不得出现「多半是」（猜原因）', () => {
  assert(
    !panelCode.includes('多半是'),
    '面板里又出现了「多半是…」—— 第 304 轮实测：猜「缺归因」而真因是「没配补偿规则」，方向错 ⇒ 人跑去重跑归因，永远跑不出结果',
  )
})

check('H8 券 / 退款通道说明必须写明「本系统不调用平台接口」', () => {
  const b = blockOf(panelCode, 'const CHANNEL_META')
  assert(b, '没取到 CHANNEL_META 块 ⇒ 判据空跑')
  assert(
    b.includes('不调用平台接口'),
    'coupon / refund 的说明必须写明「本系统不调用平台接口」—— 否则「发券 / 退回货款」又在暗示钱已经动了',
  )
})

// ============================================================ H9 反向自检
check('H9 反向自检：H1 / H4 的提取器必须能判红（证明不是恒真）', () => {
  // ① 把 issued 改回「已发放」⇒ H1 必须拿不到「待平台执行」
  const bad = labelsBlock.replace(/issued:\s*['"][^'"]*['"]/, "issued: '已发放'")
  assert(bad !== labelsBlock, '替换没生效 ⇒ 自检本身空跑')
  const bv = fieldValue(bad, 'issued')
  assert(bv === '已发放' && !bv.includes('待平台执行'), 'H1 提取器失配：改坏了也读不出')

  // ② 把路径改错一位 ⇒ H4 必须对不上
  const fake = apiCode.replace('/receipt`', '/receipt2`')
  assert(fake !== apiCode, '路径替换没生效 ⇒ 自检本身空跑')
  const fe2 = apiCall(fake, 'recordExecutionReceipt')
  const stillHit = routerEntries(routerRaw).some(
    (e) => e.method === fe2.method && normPath(e.path) === normPath(fe2.path),
  )
  assert(!stillHit, 'H4 比对器失配：路径都改错了还判相等 ⇒ 恒真')

  // ③ 正面对照：真实路径必须**能**对上（否则 H4 是假红）
  const fe1 = apiCall(apiCode, 'recordExecutionReceipt')
  const okHit = routerEntries(routerRaw).some(
    (e) => e.method === fe1.method && normPath(e.path) === normPath(fe1.path),
  )
  assert(okHit, 'H4 比对器把正确的路径也判成不匹配 ⇒ 假红')
})

// ============================================================ 报告
const bad = results.filter((r) => r[1])
for (const [name, err] of results) {
  console.log(`  ${err ? 'FAIL' : 'PASS'}  ${name}`)
  if (err) console.log(`        ↳ ${err}`)
}
console.log('')
if (bad.length) {
  console.log(`处置执行诚实性门禁失败：${bad.length} / ${results.length}`)
  process.exit(1)
}
console.log(`处置执行诚实性门禁通过（${results.length} 条形态断言 ✓）`)

#!/usr/bin/env node
/**
 * 「候选排序维度」跨端三方对齐门禁（第 216 轮）
 *
 * ## 为什么需要它
 *
 * 老板的追问：「换成真正的数据源的数据，也能很好地工作吗？是否具有通用性？
 * （换个问法问 —— 不是预估销量前 3，而是售价前 5、评审状态通过的产品……）」
 *
 * 实测发现这不是「少写一个功能」，而是**同一份能力散成了三份口径**：
 *
 *   · 页面（`CandidateLibrary.vue` 的排序下拉）：6 个维度，用户在页面上点一下就
 *     能得到正确答案；
 *   · store（`stores/candidateLibrary.ts` 的 `sortBy` 分支）：同一份 6 个维度，
 *     在前端内存里自己排；
 *   · 后端（`modules/candidates/service.py` 的 `CANDIDATE_SORT_FIELDS`）：
 *     **一个都没有** —— 排序在 SQL 里被硬编码成 `updated_at` 倒序。
 *
 * 于是 Agent 答不了「销量前 3」「售价前 5」，而**页面答得对** ——
 * 这就是「同一能力两份实现（且只有一份齐全）」。第 216 轮把后端补齐后，
 * 三处口径**必须继续同步**，否则下一次「页面加了新维度、Agent 又答不了」
 * 会**静默**发生（没有任何东西会报错）。
 *
 * ## 判据
 *
 * ① 后端白名单非空，且每个键都指向真实列名（形如 `"sales": ("estimated_monthly_sales", "desc")`）；
 * ② 三方**集合完全相等**（不是「包含」—— 多了少了都算漂移）：
 *      后端 `CANDIDATE_SORT_FIELDS` 的键
 *      == store 的 `switch (sortBy.value)` 里的 `case '<key>':`
 *      == 页面排序下拉里的 `<a-select-option value="<key>">`
 * ③ `updated_at` 必须在三方都有（它是默认排序，缺了会导致「不传参」行为变样）；
 * ④ 每处锚点找不到就 **FAIL**（不是「跳过」）—— 「拿不到权威清单 ≠ 清单为空」。
 *
 * ## 反向注入（已实测）
 *
 *  · 后端白名单里加一个前端没有的键（如 `bsr`） ⇒ ② 红；
 *  · 页面下拉删掉「售价」一项 ⇒ ② 红；
 *  · store 的 `case 'rating'` 删掉 ⇒ ② 红；
 *  · 把 `CANDIDATE_SORT_FIELDS = {` 改名 ⇒ ① 红（锚点失效，不静默放行）。
 *
 * 用法：node scripts/check-agent-sort-parity.cjs   （0 = 通过；1 = 有漂移）
 *
 * ★ 本门禁**跨树读后端文件**（`../backend/modules/candidates/service.py`）——
 *   这是它存在的全部意义（跨端口径）。两棵树在本仓是固定兄弟目录；
 *   后端文件读不到时**报 FAIL**，绝不静默放行。
 * ★ 判据一律在**剥离注释后**的源码上跑（本仓铁律：注释里的旧文案会骗过检查）。
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   SORT_FE_ROOT=<副本或空目录>      ⇒ ② / ③ 红（store / 页面读不到）
 *   SORT_SERVICE_SRC=<副本或空文件>  ⇒ ① 红（后端白名单读不到）
 *
 */
const fs = require('fs')
const path = require('path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const FE = pick('SORT_FE_ROOT', path.resolve(__dirname, '..'))
const SERVICE = pick(
  'SORT_SERVICE_SRC',
  path.resolve(__dirname, '..', '..', 'backend', 'modules', 'candidates', 'service.py'),
)
const STORE = 'src/stores/candidateLibrary.ts'
const VUE = 'src/components/KnowledgeBase/CandidateLibrary.vue'

const read = p => fs.readFileSync(path.join(FE, p), 'utf8')

/** 剥离注释：`//` 行注释、块注释、HTML 注释 */
function stripComments(t) {
  return t
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\/[^\n]*/g, '')
}

const fails = []
function check(ok, label, detail) {
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}`)
  if (!ok) {
    if (detail) console.log(`        ${detail}`)
    fails.push(label)
  }
}
const sorted = a => [...a].sort().join(',')

/** 花括号配对扫描：从 marker 之后第一个 `{` 起，取到与之配对的 `}` 之间 */
function braceBlock(src, marker) {
  const i = src.indexOf(marker)
  if (i < 0) return ''
  const open = src.indexOf('{', i)
  if (open < 0) return ''
  let depth = 0
  for (let j = open; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}') {
      depth--
      if (depth === 0) return src.slice(open + 1, j)
    }
  }
  return ''
}

console.log('=== 候选排序维度三方对齐门禁（第 216 轮）===')

// ---------------- 后端白名单 ----------------
let backendKeys = []
let backendPairs = []
let serviceSrc = ''
try {
  serviceSrc = stripComments(fs.readFileSync(SERVICE, 'utf8'))
} catch (e) {
  serviceSrc = ''
}
check(serviceSrc.length > 0, '① 读到后端 service.py',
  `读不到 ${SERVICE} —— 两棵树应是固定兄弟目录；拿不到权威清单**不许**当作「清单为空」`)

const beBlock = braceBlock(serviceSrc, 'CANDIDATE_SORT_FIELDS =')
check(beBlock.length > 0, '① 定位到 CANDIDATE_SORT_FIELDS 字面量块',
  '被改名了？后端排序白名单是唯一真源，锚点失效必须 FAIL 而不是放行')

for (const m of beBlock.matchAll(/"([a-z_]+)"\s*:\s*\(\s*"([a-z_]+)"\s*,\s*"(asc|desc)"\s*\)/g)) {
  backendKeys.push(m[1])
  backendPairs.push([m[1], m[2], m[3]])
}
check(backendKeys.length >= 5, '① 白名单键数 ≥ 5',
  `实测 ${backendKeys.length} 个：${backendKeys.join(', ')} —— 太少说明漏了页面已有的排序项`)

// 每个键指向的「列名」必须长得像真列（蛇形小写），且方向合法
const badPairs = backendPairs.filter(([, col, dir]) => !/^[a-z][a-z0-9_]*$/.test(col) || !['asc', 'desc'].includes(dir))
check(badPairs.length === 0, '① 每个维度都给出 (列名, 方向)',
  `异常的项：${JSON.stringify(badPairs)}`)

// ---------------- store 的 sortBy 分支 ----------------
const storeSrc = stripComments(read(STORE))
const storeBlock = braceBlock(storeSrc, 'switch (sortBy.value)')
check(storeBlock.length > 0, '② 定位到 store 的 switch (sortBy.value)',
  '被重构了？请同步更新本门禁的锚点')

const storeKeys = []
for (const m of storeBlock.matchAll(/case\s+'([a-z_]+)'\s*:/g)) storeKeys.push(m[1])
// `default:` 分支就是默认排序 —— 与后端 DEFAULT_SORT_FIELD（updated_at）同义
const storeHasDefault = /default\s*:/.test(storeBlock)
check(storeHasDefault, '② store 的 switch 有 default 分支（= 默认排序那一档）',
  '没有 default ⇒ 未知 sortBy 值会 fallthrough 到第一个 case，排序结果随机')
if (storeHasDefault) storeKeys.push('updated_at')

// ---------------- 页面排序下拉 ----------------
const vueSrc = stripComments(read(VUE))
const uiKeys = []
{
  const i = vueSrc.indexOf('v-model:value="store.sortBy"')
  const tail = i < 0 ? '' : vueSrc.slice(i)
  const end = tail.indexOf('</a-select>')
  const block = end < 0 ? '' : tail.slice(0, end)
  check(block.length > 0, '② 定位到页面排序下拉（v-model:value="store.sortBy" … </a-select>）',
    '下拉被换成动态生成 / 改名了？锚点失效必须 FAIL')
  for (const m of block.matchAll(/<a-select-option\s+value="([a-z_]+)"/g)) uiKeys.push(m[1])
}

// ---------------- 三方相等 ----------------
const sets = {
  后端: backendKeys,
  'store.sortBy': storeKeys,
  '页面下拉': uiKeys,
}
for (const [name, arr] of Object.entries(sets)) {
  check(arr.length > 0, `② ${name} 的排序维度清单非空`, '空清单 ⇒ 下面的相等断言会恒真（假绿）')
}
check(sorted(backendKeys) === sorted(storeKeys), '② 后端白名单 == store.sortBy 支持集',
  `后端 [${sorted(backendKeys)}]  vs  store [${sorted(storeKeys)}]`)
check(sorted(backendKeys) === sorted(uiKeys), '② 后端白名单 == 页面下拉选项',
  `后端 [${sorted(backendKeys)}]  vs  页面 [${sorted(uiKeys)}]`)
check(
  new Set(backendKeys).size === backendKeys.length &&
  new Set(storeKeys).size === storeKeys.length &&
  new Set(uiKeys).size === uiKeys.length,
  '② 三方内部都无重复项', '重复项会让「相等」在多一层校验下失真')
check(backendKeys.includes('updated_at') && storeKeys.includes('updated_at') && uiKeys.includes('updated_at'),
  '③ 三方都含 updated_at（默认排序）',
  '缺了它 ⇒ 「不传 order_by」的行为会与前端的默认排序分叉')

// ---------------- 判据自检（防正则恒真 / 恒不匹配）----------------
console.log('  ---- 判据自检 ----')
const SELF = [
  [/"([a-z_]+)"\s*:\s*\(\s*"([a-z_]+)"\s*,\s*"(asc|desc)"\s*\)/g, '"sales": ("estimated_monthly_sales", "desc")', 1],
  [/"([a-z_]+)"\s*:\s*\(\s*"([a-z_]+)"\s*,\s*"(asc|desc)"\s*\)/g, '"sales": (estimated_monthly_sales, "desc")', 0],
  [/case\s+'([a-z_]+)'\s*:/g, "case 'sales': return 1", 1],
  [/case\s+'([a-z_]+)'\s*:/g, 'case sales: return 1', 0],
  [/<a-select-option\s+value="([a-z_]+)"/g, '<a-select-option value="sales">售价</a-select-option>', 1],
  [/<a-select-option\s+value="([a-z_]+)"/g, '<a-select-option :value="x">售价</a-select-option>', 0],
]
let selfBad = 0
for (const [re, sample, want] of SELF) {
  const got = [...sample.matchAll(re)].length
  const ok = got === want
  if (!ok) selfBad++
  check(ok, `自检：${JSON.stringify(sample.slice(0, 42))} 命中 ${got} 次（期望 ${want}）`)
}
check(selfBad === 0, '自检：全部正则既不是恒真也不是恒不匹配')

console.log('')
if (fails.length) {
  console.log(`RESULT: FAIL（${fails.length} 处）—— 排序维度三处口径已漂移（页面能排、Agent 排不了）`)
  process.exit(1)
}
console.log(`RESULT: PASS（三方对齐：${backendKeys.length} 个排序维度 · ${backendKeys.join(' / ')}）`)

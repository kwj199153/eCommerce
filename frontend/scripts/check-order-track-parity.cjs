#!/usr/bin/env node
/**
 * 订单追踪「四条渲染通道共用一份真源」门禁（★ 第 292 轮）
 *
 * 它保护什么
 * ==========
 * 同一份订单数据，前端有**四处**渲染出口，从前各写各的字段清单：
 *   ① 对话通道 `composables/chat/replies/customerService.ts`（Markdown 表格）
 *   ② 工具卡   `components/ChatPanel/results/OrderTrackResult.vue`（结构化卡片）
 *   ③ 结果摘要 `composables/chat/resultSummary.ts`（结果卡上方那句 bullet）
 *   ④ 配置面板 `components/TaskConfigPanel/configs/OrderTrackConfig.vue`（「查询结果包含」）
 * 后果（第 292 轮实测）：
 *   · 后端 `_map_order_from_trade` 早就返回了运单号 / 承运商 / 轨迹 5 项，
 *     但**对话那条连运单号都没进模板**，**工具卡那条没渲染轨迹**；
 *   · 面板还写着「运单号与承运商不在 Orders 接口中，需登录卖家后台查看」——
 *     自有订单库那条链**是给的**，这句话把用户指去了错的地方。
 * ⇒ 数据在库里，卡在渲染层。四份清单靠人肉同步，漏一处就有一条路看不见。
 *
 * 判据组
 * ======
 *   T1 唯一真源 `utils/orderTracking.ts` 存在，导出面齐全
 *   T2 规格表自洽（**运行期真调用**）：满值订单能产出的键集合 == 规格里非 header 的键集合
 *      （加了规格忘了 `pick` ⇒ 面板说会给、实际永远不给）
 *   T3 「有值才成行」：空订单 ⇒ 物流组必须为空，基础组不许凭空冒出编造的字段
 *   T4 四个消费方都从真源取（各自用对应的那个函数）
 *   T5 四个消费方**不得**再自行解 `order?.xxx`（第二份字段清单的入口）
 *   T6 与后端对账：`_map_order_from_trade` 产出的业务键必须全部被前端接住
 *      （**这正是「数据在库里、卡在渲染层」的防复发判据**）；
 *      显式豁免的键（`status` / `total` / `data_source` / `is_mock_data`）必须
 *      在真源里真的被消费 —— 否则就是「登记了但不消费」的死登记
 *   T7 反向自检：把**旧实现**（各写各的）喂给 T5 的匹配器 ⇒ 必须命中
 *   T8 扫描面规模达标（否则判据会「因为什么都没扫到」而恒真）
 *
 * 为什么走 `ts.transpileModule` + `vm` 真加载
 * ==========================================
 * T2/T3 是**行为**（哪个字段进清单）而不是源码形态。源码字符串能被注释骗过
 * （本仓已有教训），运行期观测不能。
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   ORDER_SRC_ROOT=<副本或空目录>     ⇒ T1~T5 / T7 / T8 红（真源与四个消费方读不到）
 *   ORDER_BACKEND_SRC=<副本或空文件>  ⇒ T6 红（后端字段清单读不到）
 *
 */

const fs = require('fs')
const path = require('path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback
const vm = require('vm')
const ts = require(path.join(__dirname, '..', 'node_modules', 'typescript'))

const ROOT = path.resolve(__dirname, '..')
const SRC = pick('ORDER_SRC_ROOT', path.join(ROOT, 'src'))
const TS_SRC = path.join(SRC, 'utils', 'orderTracking.ts')
const BACKEND_CS = pick(
  'ORDER_BACKEND_SRC',
  path.resolve(ROOT, '..', 'backend', 'modules', 'customer_service', 'agent_cs.py'),
)

/** 四个消费方（id → { 文件, 必须出现的符号, 说明 }） */
const CONSUMERS = [
  {
    id: '工具卡',
    file: path.join(SRC, 'components', 'ChatPanel', 'results', 'OrderTrackResult.vue'),
    must: 'buildOrderTrackingView',
  },
  {
    id: '对话通道',
    file: path.join(SRC, 'composables', 'chat', 'replies', 'customerService.ts'),
    must: 'renderOrderTrackingText',
  },
  {
    id: '结果摘要',
    file: path.join(SRC, 'composables', 'chat', 'resultSummary.ts'),
    must: 'orderSummaryLines',
  },
  {
    id: '配置面板',
    file: path.join(SRC, 'components', 'TaskConfigPanel', 'configs', 'OrderTrackConfig.vue'),
    must: 'orderFieldPreview',
  },
]

/** 后端产出、但**故意**不由字段表渲染的键 —— 每个都要说清谁在消费 */
const CONSUMED_ELSEWHERE = {
  status: '原始状态码 ⇒ `orderHeader()`',
  total: '原始金额（无币种）⇒ `orderAmountText()` 的兜底分支',
  data_source: '取数来源 ⇒ `orderSourceNote()`',
  is_mock_data: '演示数据标记 ⇒ `orderSourceNote()`',
}

/** 后端字段名 —— T5 用它判「消费方有没有自己解 payload」 */
const BACKEND_KEYS = [
  'order_id', 'status', 'status_text', 'created_at', 'product_name', 'quantity',
  'total', 'total_text', 'estimated_delivery', 'shipping_to', 'shipped_at',
  'delivered_at', 'tracking_number', 'carrier', 'ship_status_text', 'transit_days',
  'delay_days', 'last_location', 'last_event_text', 'data_source', 'is_mock_data',
]

/**
 * ★ 第 351 轮 L3-11：读不到源 ⇒ 打印**可读 FAIL** 后退出（不再抛裸异常）。
 * 裸异常只有栈、没有「哪条判据红了」——外部聚合会把「门禁坏了」误当成「真红」。
 * 「拿不到权威清单 ≠ 清单为空」⇒ 红也要红得可读，且绝不放行。
 */
function read(p) {
  try {
    return fs.readFileSync(p, 'utf8')
  } catch (e) {
    console.log(`  FAIL  读不到源文件：${p}`)
    console.log(`        ${e.code || 'ENOENT'} —— 本门禁靠它做判定，拿不到不许放行`)
    process.exit(1)
  }
}

/** 把 TS 源码转成 CJS 并在独立沙箱里取导出（每例新沙箱，避免 module.exports 互相污染） */
function loadTs(code, filename) {
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText
  const sandbox = { module: { exports: {} }, exports: {}, require, console }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename })
  return sandbox.module.exports
}

/** 去掉 `//` 与 `/* *\/` 注释（判据必须剥注释，否则一句解释就能满足它） */
function stripComments(src) {
  let out = ''
  let i = 0
  while (i < src.length) {
    const c = src[i]
    const c2 = src[i + 1]
    if (c === '/' && c2 === '/') { while (i < src.length && src[i] !== '\n') i++; continue }
    if (c === '/' && c2 === '*') {
      i += 2
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
      continue
    }
    out += c
    i++
  }
  return out
}

/**
 * 「消费方自己解 payload」的匹配器 —— T5 与 T7 共用**同一个**实现。
 * 命中的形态：`order?.tracking_number` / `data.order.carrier` / `order["carrier"]`
 */
function selfAccessHits(code, keys) {
  const hits = []
  const alt = keys.join('|')
  const re = new RegExp(`order\\s*\\??\\s*(?:\\.\\s*\\[\\s*['"](?:${alt})['"]\\s*\\]|\\.\\s*(?:${alt})\\b)`, 'g')
  const noComment = stripComments(code)
  let m
  while ((m = re.exec(noComment)) !== null) hits.push(m[0])
  return hits
}

/** 从后端 `_map_order_from_trade` 抽出它 return 的那个 dict 的顶层键 */
function backendKeys() {
  const src = read(BACKEND_CS)
  const a = src.indexOf('def _map_order_from_trade')
  const b = src.indexOf('def _map_order_info')
  if (a < 0 || b < 0 || b <= a) throw new Error('在 agent_cs.py 里定位不到 _map_order_from_trade')
  const body = src.slice(a, b)
  const keys = []
  const re = /"([a-z_]+)":/g
  let m
  while ((m = re.exec(body)) !== null) if (!keys.includes(m[1])) keys.push(m[1])
  return keys
}

// ---------------------------------------------------------------- 判定框架
const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

const MOD = loadTs(read(TS_SRC), TS_SRC)
const SPECS_PREVIEW = MOD.orderFieldPreview()
const SPEC_KEYS = SPECS_PREVIEW.map((s) => s.key)
const RENDER_KEYS = SPECS_PREVIEW.filter((s) => s.group !== 'header').map((s) => s.key)
const HEADER_KEYS = SPECS_PREVIEW.filter((s) => s.group === 'header').map((s) => s.key)

// ---------------------------------------------------------------- T1
check('T1 唯一真源存在，导出面齐全', () => {
  const need = [
    'orderFields', 'orderFieldPreview', 'renderOrderTrackingText', 'orderSummaryLines',
    'buildOrderTrackingView', 'orderSourceNote', 'orderHeader',
    'orderToneOf', 'orderStatusIcon', 'orderAmountText',
  ]
  const missing = need.filter((n) => typeof MOD[n] !== 'function')
  assert(!missing.length, `真源缺少导出：${missing.join(' / ')}`)
  assert(SPEC_KEYS.length >= 10, `字段规格表太小（${SPEC_KEYS.length} 项），可能被清空了`)
})

// ---------------------------------------------------------------- T2
check('T2 规格表自洽：满值订单能产出的键 == 非 header 的规格键', () => {
  // ★ 数值型字段要喂数字：喂字符串会让 `positiveInt` 判空 ⇒ 变成"夹具的错"假红
  const NUMERIC = new Set(['quantity', 'transit_days', 'delay_days'])
  const full = {}
  for (const k of RENDER_KEYS) full[k] = NUMERIC.has(k) ? 3 : 'x'
  const got = new Set(MOD.orderFields(full).map((f) => f.key))
  const missing = RENDER_KEYS.filter((k) => !got.has(k))
  assert(
    !missing.length,
    `规格里登记了却产不出来的字段（多半是漏了 pick）：${missing.join(' / ')}`,
  )
  const extra = [...got].filter((k) => !SPEC_KEYS.includes(k))
  assert(!extra.length, `产出了规格表里没有的字段：${extra.join(' / ')}`)
})

// ---------------------------------------------------------------- T3
check('T3 有值才成行：空订单不得凭空冒出字段', () => {
  const fields = MOD.orderFields({})
  const logistics = fields.filter((f) => f.group === 'logistics')
  assert(
    logistics.length === 0,
    `空订单不该有物流行（不许编造轨迹）：${logistics.map((f) => f.label).join(' / ')}`,
  )
  const allowedBase = ['total_text']
  const extra = fields.filter((f) => f.group === 'base' && !allowedBase.includes(f.key))
  assert(
    !extra.length,
    `空订单冒出了基础字段：${extra.map((f) => f.key).join(' / ')}（拿不到就该留空）`,
  )
})

// ---------------------------------------------------------------- T4
check('T4 四个消费方都从真源取', () => {
  const problems = []
  for (const c of CONSUMERS) {
    const code = read(c.file)
    const imp = code.match(/import\s*\{[^}]*\}\s*from\s*['"]@\/utils\/orderTracking['"]/)
    if (!imp) problems.push(`${c.id} 没有从 '@/utils/orderTracking' 取真源`)
    else if (!imp[0].includes(c.must)) problems.push(`${c.id} 没取它该用的 \`${c.must}\``)
    if (!new RegExp(`\\b${c.must}\\s*\\(`).test(stripComments(code))) {
      problems.push(`${c.id} 取了 \`${c.must}\` 却没调用（死导入）`)
    }
  }
  assert(!problems.length, problems.join('；'))
})

// ---------------------------------------------------------------- T5
check('T5 消费方不得再自行解 `order?.xxx`（第二份字段清单的入口）', () => {
  const problems = []
  for (const c of CONSUMERS) {
    const hits = selfAccessHits(read(c.file), BACKEND_KEYS)
    if (hits.length) problems.push(`${c.id}: ${[...new Set(hits)].slice(0, 4).join(', ')}`)
  }
  assert(
    !problems.length,
    `又出现自己解订单字段的写法（字段清单必须只有真源一份）：\n      ` + problems.join('\n      '),
  )
})

// ---------------------------------------------------------------- T6
check('T6 与后端 `_map_order_from_trade` 对账：产出的键必须全部被前端接住', () => {
  const be = backendKeys()
  assert(be.length >= 15, `只从后端抽出 ${be.length} 个键，解析器可能坏了：${be.join(',')}`)
  const src = read(TS_SRC)
  const unhandled = be.filter(
    (k) => !SPEC_KEYS.includes(k) && !Object.prototype.hasOwnProperty.call(CONSUMED_ELSEWHERE, k),
  )
  assert(
    !unhandled.length,
    `后端给了、前端一处都没接（数据在库里、卡在渲染层）：${unhandled.join(' / ')}`,
  )
  // 豁免的键必须真的在真源里被消费 —— 否则是一句「登记了但不消费」的空话
  const fake = Object.entries(CONSUMED_ELSEWHERE)
    .filter(([k]) => !SPEC_KEYS.includes(k))
    .filter(([k]) => !new RegExp(`['"]${k}['"]|\\b${k}\\b`).test(src))
    .map(([k]) => k)
  assert(!fake.length, `这些键登记为「别处消费」，真源里却找不到：${fake.join(' / ')}`)
})

// ---------------------------------------------------------------- T7
check('T7 反向自检：旧实现（各写各的）必须被 T5 的匹配器抓住', () => {
  const legacy = [
    "const order = payload?.order",
    "lines.push(`| 快递单号 | \\`${order.tracking_number}\\` |`)",
    "if (order.estimated_delivery) lines.push(order.estimated_delivery)",
    "const carrier = data.order.carrier",
  ].join('\n')
  const hits = selfAccessHits(legacy, BACKEND_KEYS)
  assert(
    hits.length >= 3,
    `T5 的匹配器抓不到旧实现（判据空跑）：命中 ${hits.length} 处 ${JSON.stringify(hits)}`,
  )
  assert(
    !selfAccessHits('orderFieldPreview()\nconst x = orderTracking\nbuildOrderTrackingView(payload)', BACKEND_KEYS).length,
    'T5 的匹配器把合法写法也当成了自行解字段（假红）',
  )
})

// ---------------------------------------------------------------- T8
check('T8 扫描面规模达标（否则前面的判据恒真）', () => {
  assert(fs.existsSync(TS_SRC), `真源文件不存在：${TS_SRC}`)
  assert(SPEC_KEYS.length >= 12, `规格项 ${SPEC_KEYS.length} 条，太少`)
  assert(HEADER_KEYS.length >= 2, 'header 组（订单号 / 状态）不该为空')
  const loaded = CONSUMERS.filter((c) => read(c.file).length > 200).length
  assert(loaded === CONSUMERS.length, `只有 ${loaded}/${CONSUMERS.length} 个消费方读到了内容`)
})

// ---------------------------------------------------------------- 输出
let failed = 0
for (const [name, err] of results) {
  if (err) { failed++; console.log(`FAIL  ${name}\n        ${err}`) }
  else console.log(`PASS  ${name}`)
}
console.log(`\n---- ${results.length - failed}/${results.length} 通过 ----`)
if (failed) {
  console.log('订单追踪四条通道必须共用 `src/utils/orderTracking.ts` 这一份渲染真源。')
  process.exit(1)
}
console.log(
  '订单追踪单一渲染真源成立（字段清单 / 状态三态 / 金额 · 四个消费方共用 · ' +
  `与后端映射对账 ${BACKEND_KEYS.length} 键 ✓）`,
)

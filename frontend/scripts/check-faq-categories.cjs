#!/usr/bin/env node
/**
 * FAQ 分类字典「前后端键集合恒等」门禁（★ 第 293 轮）
 *
 * 它保护什么
 * ==========
 * `knowledge_faqs.category` 的合法取值由后端两处真源收口：
 *   · `backend/modules/knowledge_base/ai_split_faq.py::FAQ_CATEGORY_CODES`（表 owner）
 *   · `backend/modules/customer_service/faq_source.py::CATEGORY_LABELS`（客服检索层）
 * 这两者之间**已有**后端测试断言恒等
 * （`tests/test_kb_doc_ai_split.py::test_category_codes_match_customer_service`）。
 *
 * 但前端 `src/stores/knowledge.ts::FAQ_CATEGORIES` 是**第三份手写实现**，
 * 没有任何判据钉它 —— 于是它安安静静地漂了：
 *   第 293 轮实测：库里有 32 行 `aftersale` + 16 行 `order`，
 *   而前端字典里**没有这两个 key**。后果是双重的：
 *     ① 列表里这些条目显示成英文 code（`getCategoryLabel` 的兜底是 `|| key`）；
 *     ② 筛选下拉与表头筛选里根本没有这两项 ⇒ 用户**筛不到**它们。
 *   根因不是手滑，是**门禁只钉了后端↔后端，前端这一侧无人看守**。
 *
 * 判据组
 * ======
 *   F1 两边键集合**恒等**（主判据：少了 / 多了都红）
 *   F2 前端每条都要有非空 label / icon / color（加了 key 忘配展示 ⇒ 白板标签）
 *   F3 反向自检：把**旧的前端块**（少 order / aftersale）喂给比对器 ⇒ 必须报出差集
 *      （不反向注入验证过的门禁等于没有门禁）
 *   F4 扫描面规模达标（两边都真读到了内容，否则前面的判据「什么都没扫到」而恒真）
 *   F5 前端**不得**再出现第二处同类字典（防止有人加个新数组绕过本门禁）
 *
 * 口径说明（为什么不一并钉 label）
 * ==============================
 * 前端 label 允许有展示自由度（现存写法带前缀：「物流配送」「商品咨询」），
 * 强行要求与后端逐字相同会变成「钉住旧形态」的负资产。
 * ⇒ 本门禁钉**键集合**（这是「字典必须覆盖实际数据」的最小不变量），
 *   label 只要求非空。`review` 的命名分歧（后端「评价」）本轮已按真源对齐。
 *
 * ## 读集注入开口（★ 第 351 轮 L3-11：零副作用自证）
 *
 * 扫描根可用环境变量指向**空源**（空目录 / 空文件）。空源时本门禁**必须变红** ——
 * 仍绿即说明判据没真读它（fail-open）。
 * ★ 边界：空源注入只能**证伪**（证明判据读了内容），**不证明**它读对了字段。
 *
 *   FAQ_FE_ROOT=<副本或空目录>       ⇒ F4 / F5 红（前端字典与扫描面读不到）
 *   FAQ_BE_SPEC_SRC=<副本或空文件>   ⇒ F1 红（后端 code 真源读不到）
 *   FAQ_BE_LABELS_SRC=<副本或空文件> ⇒ F1 红（客服 label 层读不到）
 *
 */

const fs = require('fs')
const path = require('path')

/** ★ 第 351 轮 L3-11：读集注入开口 —— 把扫描根指向副本树 / 空源，用于零副作用自证。
 *  空源（空目录 / 空文件）时本门禁**必须变红**；仍绿即说明判据没真读它。 */
const pick = (env, fallback) =>
  process.env[env] ? path.resolve(process.env[env]) : fallback

const ROOT = pick('FAQ_FE_ROOT', path.resolve(__dirname, '..'))
/** 后端真源根：与前端根**解耦**，避免前端注入把它一起带走（不可注入的兜底） */
const REPO = path.resolve(__dirname, '..', '..')
const FE_FILE = path.join(ROOT, 'src', 'stores', 'knowledge.ts')
const BE_SPEC = pick('FAQ_BE_SPEC_SRC', path.join(
  REPO, 'backend', 'modules', 'knowledge_base', 'ai_split_faq.py',
))
const BE_LABELS = pick('FAQ_BE_LABELS_SRC', path.join(
  REPO, 'backend', 'modules', 'customer_service', 'faq_source.py',
))

/**
 * ★ 第 351 轮 L3-11：读不到源 ⇒ 打印**可读 FAIL** 后退出（不再抛裸异常）。
 * 裸异常只有栈、没有「哪条判据红了」——外部聚合会把「门禁坏了」误当成「真红」。
 * 「拿不到权威清单 ≠ 清单为空」⇒ 红也要红得可读，且绝不放行。
 */
const read = (p) => {
  try {
    return fs.readFileSync(p, 'utf8')
  } catch (e) {
    console.log(`FAIL  F0 读不到源文件：${p}`)
    console.log(`        ${e.code || 'ENOENT'} —— 本门禁靠它做判定，拿不到不许放行`)
    process.exit(1)
  }
}

const results = []
function check(name, fn) {
  try { fn(); results.push([name, null]) } catch (e) { results.push([name, e.message]) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

/**
 * 从源码里取 `KEY: "中文"` 形态的键集合。
 *
 * ★ `anchor` 必须是**定义行**而不只是变量名：本仓踩过「按变量名切，
 *   第一个 `]` 属于类型标注（`FAQ_CATEGORIES: FaqCategory[]`）⇒ 切出空块」，
 *   所以这里显式要求锚点里带上 `= {` / `= [`。
 */
function collectKeys(src, anchor, keyRe) {
  const at = src.indexOf(anchor)
  assert(at >= 0, `锚点未命中：${anchor}`)
  const rest = src.slice(at + anchor.length)
  const end = rest.indexOf('\n}')
  const endAlt = rest.indexOf('\n]')
  const cut = [end, endAlt].filter((i) => i >= 0).sort((a, b) => a - b)[0]
  assert(cut !== undefined, `找不到块结束符（锚点：${anchor}）`)
  const block = rest.slice(0, cut)
  const keys = []
  for (const m of block.matchAll(keyRe)) keys.push(m[1])
  return { keys, block }
}

const FE_ANCHOR = 'export const FAQ_CATEGORIES: FaqCategory[] = ['
const BE_SPEC_ANCHOR = 'FAQ_CATEGORY_CODES: Dict[str, str] = {'
const BE_LABELS_ANCHOR = 'CATEGORY_LABELS: Dict[str, str] = {'

/** 比对器 —— 与正向判据共用，反向自检也喂给它（否则自检证明不了判据本身有效） */
function diffKeys(feKeys, beKeys) {
  const fe = new Set(feKeys)
  const be = new Set(beKeys)
  return {
    missingInFe: [...be].filter((k) => !fe.has(k)),
    extraInFe: [...fe].filter((k) => !be.has(k)),
  }
}

const feSrc = read(FE_FILE)
const beSpecSrc = read(BE_SPEC)
const beLabelsSrc = read(BE_LABELS)

const fe = collectKeys(feSrc, FE_ANCHOR, /key:\s*'([a-z_]+)'/g)
const beSpec = collectKeys(beSpecSrc, BE_SPEC_ANCHOR, /^\s*"([a-z_]+)":/gm)
const beLabels = collectKeys(beLabelsSrc, BE_LABELS_ANCHOR, /^\s*"([a-z_]+)":/gm)

// ---------------------------------------------------------------- F1
check('F1 前端 FAQ_CATEGORIES 与后端真源键集合恒等', () => {
  const d = diffKeys(fe.keys, beSpec.keys)
  assert(
    !d.missingInFe.length && !d.extraInFe.length,
    `前端与后端真源不一致 —— 前端缺：${JSON.stringify(d.missingInFe)}；` +
    `前端多：${JSON.stringify(d.extraInFe)}\n` +
    '        （缺的 key 会让库里该类话术显示成英文 code 且筛不到；' +
    '多的 key 是没有数据能落进去的死选项）',
  )
  assert(
    beSpec.keys.length > 0,
    '后端真源键集合为空 —— 判据空跑',
  )
})

// ---------------------------------------------------------------- F2
check('F2 前端每条都有非空 label / icon / color', () => {
  const entries = [...fe.block.matchAll(
    /key:\s*'([a-z_]+)',\s*label:\s*'([^']*)',\s*icon:\s*'([^']*)',\s*color:\s*'([^']*)'/g,
  )].map((m) => ({ key: m[1], label: m[2], icon: m[3], color: m[4] }))
  assert(
    entries.length === fe.keys.length,
    `解析到 ${entries.length} 条完整登记，但键有 ${fe.keys.length} 个 —— 有登记缺字段（会渲染成白板标签）`,
  )
  for (const e of entries) {
    assert(e.label.trim(), `${e.key} 的 label 为空`)
    assert(e.icon.trim(), `${e.key} 的 icon 为空`)
    assert(e.color.trim(), `${e.key} 的 color 为空`)
  }
})

// ---------------------------------------------------------------- F3
check('F3 反向自检：旧的前端块（少 order / aftersale）必须被比对器抓住', () => {
  const legacyFeKeys = fe.keys.filter((k) => k !== 'order' && k !== 'aftersale')
  assert(
    legacyFeKeys.length === fe.keys.length - 2,
    '自检前置不成立：当前前端键集合里本来就没有 order / aftersale',
  )
  const d = diffKeys(legacyFeKeys, beSpec.keys)
  assert(
    d.missingInFe.length === 2 &&
      d.missingInFe.includes('order') && d.missingInFe.includes('aftersale'),
    `比对器抓不到旧形态（判据空跑）：差集 = ${JSON.stringify(d.missingInFe)}`,
  )
  // 另一方向：前端凭空多一个 key 也必须报出来
  const d2 = diffKeys([...fe.keys, 'ghost'], beSpec.keys)
  assert(
    d2.extraInFe.length === 1 && d2.extraInFe[0] === 'ghost',
    `比对器抓不到「前端多出死选项」：${JSON.stringify(d2.extraInFe)}`,
  )
})

// ---------------------------------------------------------------- F4
check('F4 扫描面规模达标（否则前面的判据恒真）', () => {
  assert(fe.keys.length >= 8, `前端分类只有 ${fe.keys.length} 条，太少`)
  assert(beSpec.keys.length >= 8, `后端真源只有 ${beSpec.keys.length} 条，太少`)
  assert(beLabels.keys.length >= 8, `后端客服侧真源只有 ${beLabels.keys.length} 条，太少`)
  // 同时把后端两处真源也核一遍：本门禁在「只跑前端门禁链」的场景下也要能发现后端侧漂移
  const d = diffKeys(beSpec.keys, beLabels.keys)
  assert(
    !d.missingInFe.length && !d.extraInFe.length,
    `后端两处真源自己就漂了 —— ai_split_faq 缺：${JSON.stringify(d.missingInFe)}；` +
    `faq_source 缺：${JSON.stringify(d.extraInFe)}`,
  )
})

// ---------------------------------------------------------------- F5
check('F5 前端不存在第二处 FAQ 分类字典', () => {
  const hits = []
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const p = path.join(dir, name)
      const st = fs.statSync(p)
      if (st.isDirectory()) { walk(p); continue }
      if (!/\.(ts|vue)$/.test(name)) continue
      if (p === FE_FILE) continue
      const src = fs.readFileSync(p, 'utf8')
      // 判据形态：一个数组里**同时**登记了 3 个以上已知分类 code
      const codes = ['shipping', 'aftersale', 'return', 'review']
      const n = codes.filter((c) => new RegExp(`key:\\s*'${c}'`).test(src)).length
      if (n >= 3) hits.push(path.relative(ROOT, p))
    }
  }
  walk(path.join(ROOT, 'src'))
  assert(
    !hits.length,
    `发现第二处分类字典：${hits.join(', ')} —— 收唯一真源，别让它再漂一份`,
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
    'FAQ 分类字典只有一份真源：`backend/modules/knowledge_base/ai_split_faq.py`。' +
    '前端 `stores/knowledge.ts` 的键集合必须与它恒等。',
  )
  process.exit(1)
}
console.log(
  `FAQ 分类字典前后端键集合恒等（${fe.keys.length} 类 ✓：` +
  `${fe.keys.join(' / ')}）`,
)

#!/usr/bin/env node
/**
 * 工具结果适配层契约门禁（★ 第 128 轮 · P0-2 批 1）
 *
 * 为什么值得单独一个门禁：`src/utils/toolResultAdapters.ts` 是「后端真形状 →
 * 结果卡形状」的**唯一转换点**。它出的错**不会报错**，只会让结果卡少一块内容 ——
 * 本项目第 128 轮已经实测到两次「接线了但没渲染」：
 *   · 广告诊断：对话路径给的是 `displayType: 'ad_diagnosis'`，而 ChatPanel 只认
 *     `msg.data.toolId` ⇒ 真数据一直渲染不出来；
 *   · 竞品卡：适配层如实传了 `differentiation`（对象），而组件只认
 *     `key_differentiators` / `differentiators`（后端**不存在**的键）⇒ 区块永不渲染。
 * 两次都是**真数据接进来了，用户看不见**，且零报错、零测试失败。
 *
 * ⇒ 必须把「fixtures（真后端响应）→ 适配层 → 断言结果卡能消费的字段」钉住。
 *
 * 夹具来源：`.workbuddy/probes/_r129e_responses/`，第 128 轮从**真实后端**
 * （`fastapi.testclient` + 真 DB + LLM 离线兜底）抓取；`seo-audit.json` 是
 * **schema-valid 样本** —— 因为 `/listing/analyze/seo` 在降级路径当时返回 500
 * （同轮已修，见 backend/tests/test_listing_seo_contract.py）。
 *
 * 怎么跑：node scripts/check-tool-adapters.cjs
 *
 * 反向注入（证明本门禁不是空跑）：
 *   TOOL_ADAPTERS_SRC=<把 flattenDifferentiation 改成直接 return '' 的副本> \
 *     node scripts/check-tool-adapters.cjs   —— 必须变红
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const SRC = process.env.TOOL_ADAPTERS_SRC
  ? path.resolve(process.env.TOOL_ADAPTERS_SRC)
  : path.join(ROOT, 'src', 'utils', 'toolResultAdapters.ts')
const FIXTURES = path.join(__dirname, '__fixtures__', 'tool-responses')

const results = []
function check(name, fn) {
  try {
    fn()
    results.push({ name, ok: true })
  } catch (e) {
    results.push({ name, ok: false, msg: e.message })
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

/** 用 devDependency `typescript` 把适配层转成 CJS 并在沙箱里取导出（零新依赖） */
function loadAdapters() {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const code = fs.readFileSync(SRC, 'utf8')
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 },
    fileName: SRC,
  }).outputText
  const sandbox = { module: { exports: {} }, exports: {}, require }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename: SRC })
  return sandbox.module.exports
}

function fixture(name) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'))
}

const A = loadAdapters()
for (const fn of ['adaptAdDiagnosis', 'adaptBulletGen', 'adaptSeoAudit', 'adaptCompetitorCompare', 'flattenDifferentiation']) {
  check(`导出存在：${fn}`, () => assert(typeof A[fn] === 'function', `${fn} 不是函数`))
}

// ===== 1. 广告诊断（真响应）=====
check('广告诊断：真响应逐字透传，结果卡消费的字段全在', () => {
  const d = A.adaptAdDiagnosis(fixture('ad-diagnosis.json'), { time_range: '30d' })
  assert(d.type === 'ad_diagnosis', 'type 应为 ad_diagnosis')
  assert(typeof d.overall_score === 'number', '缺 overall_score')
  assert(typeof d.grade === 'string' && d.grade, '缺 grade')
  assert(Array.isArray(d.metrics) && d.metrics.length > 0, 'metrics 为空')
  assert(Array.isArray(d.campaigns) && d.campaigns.length > 0, 'campaigns 为空')
  assert(Array.isArray(d.top_issues), 'top_issues 应为数组')
  assert(Array.isArray(d.recommendations), 'recommendations 应为数组')
  const m = d.metrics[0]
  for (const k of ['name', 'value', 'unit', 'benchmark', 'status']) {
    assert(k in m, `metrics[] 缺字段 ${k}`)
  }
  const c = d.campaigns[0]
  for (const k of ['campaign_name', 'spend', 'impressions', 'clicks', 'orders', 'sales', 'acos']) {
    assert(k in c, `campaigns[] 缺字段 ${k}`)
  }
})

// ===== 2. 五点描述（真响应）=====
check('五点描述：bullets 结构化（title+content 同时存在）且不编造 emoji', () => {
  const d = A.adaptBulletGen(fixture('bullet-gen.json'), { product_name: 'Manual Coffee Grinder' })
  assert(d.type === 'bullet_gen', 'type 应为 bullet_gen')
  assert(d.product_name === 'Manual Coffee Grinder', 'product_name 丢了')
  assert(Array.isArray(d.bullets) && d.bullets.length > 0, 'bullets 为空')
  for (const b of d.bullets) {
    assert(typeof b.title === 'string' && b.title, `bullet 缺 title：${JSON.stringify(b)}`)
    assert(typeof b.content === 'string' && b.content, `bullet 缺 content`)
    assert(typeof b.char_count === 'number' && b.char_count > 0, `bullet 缺 char_count`)
    assert(!('emoji' in b), 'emoji 是后端没有的字段，不该编造出来')
  }
  assert(typeof d.total_characters === 'number', '缺 total_characters')
  assert(d.coverage_score === null || typeof d.coverage_score === 'number', 'coverage_score 类型不对')
  assert(Array.isArray(d.optimization_suggestions), 'optimization_suggestions 应来自后端 tips')
})

// ===== 3. 竞品对比（真响应，happy path）=====
check('竞品对比：competitors[] 的 6 个真值列全部还原（价格/评分/评论/BSR/性价比/排名）', () => {
  const d = A.adaptCompetitorCompare(fixture('competitor-compare.json'), {})
  assert(d.type === 'competitor_comparison', 'type 应为 competitor_comparison')
  assert(d.competitors.length === 3, `应有 3 个竞品，实际 ${d.competitors.length}`)
  for (const c of d.competitors) {
    assert(typeof c.asin === 'string' && c.asin, `缺 asin：${JSON.stringify(c)}`)
    for (const k of ['price', 'rating', 'review_count', 'bsr_rank', 'value_score', 'rank']) {
      assert(c[k] !== null && c[k] !== undefined, `competitor ${c.asin} 缺真值列 ${k}（后端 comparison.* 里有，映射断了）`)
    }
  }
  // market_leader 必须与 overall_ranking 里 rank === 1 的那条一致
  assert(d.market_leader, 'market_leader 为空')
  const top = d.competitors.find((c) => c.rank === 1)
  assert(top && top.asin === d.market_leader, 'market_leader 不是 rank 1 那个竞品')
  assert(Array.isArray(d.overall_ranking) && d.overall_ranking.length === 3, 'overall_ranking 丢了')
  assert(typeof d.recommendation === 'string' && d.recommendation.length > 0, 'recommendation 为空')
  // 不编造：后端没有的字段不得出现
  for (const c of d.competitors) {
    assert(!('listing_quality_score' in c), 'listing_quality_score 是前端自造字段，不该出现')
    assert(!('price_positioning' in c), 'price_positioning 是前端自造字段，不该出现')
  }
})

check('竞品对比：差异化分析被展平成非空文本（展平逻辑的唯一实现）', () => {
  const d = A.adaptCompetitorCompare(fixture('competitor-compare.json'), {})
  assert(typeof d.differentiation_text === 'string', 'differentiation_text 不是字符串')
  assert(d.differentiation_text.length > 0,
    'differentiation_text 为空 ⇒ 结果卡「差异化分析」区块不渲染（真数据接线进来却看不见）')
  assert(d.differentiation_text.includes('价格跨度'), '未含价格跨度：' + d.differentiation_text)
  assert(d.differentiation_text.includes('市场档次'), '未含市场档次：' + d.differentiation_text)
  assert(d.differentiation && typeof d.differentiation === 'object', '原始对象应保留')
})

check('flattenDifferentiation：空 / 无关键字段 ⇒ 返回空串（整块隐藏，不编造）', () => {
  assert(A.flattenDifferentiation(null) === '', 'null 应返回空串')
  assert(A.flattenDifferentiation(undefined) === '', 'undefined 应返回空串')
  assert(A.flattenDifferentiation({}) === '', '空对象应返回空串')
  assert(A.flattenDifferentiation({ gap_opportunities: [] }) === '', '空数组段不应产出文本')
  assert(A.flattenDifferentiation('已是字符串') === '已是字符串', '字符串应原样返回')
})

check('竞品对比：后端「伪成功」（200 + data.error）⇒ 适配层只能给出 0 行，须由执行器拦', () => {
  const d = A.adaptCompetitorCompare(fixture('competitor-compare-pseudo-success.json'), {})
  assert(d.competitors.length === 0, '伪成功样本本就没有竞品数据')
  assert(d.market_leader === '', 'market_leader 应为空')
  // ★ 这条断言的意义：证明**光靠适配层救不了伪成功** ⇒ executeCompetitorAnalysis
  //   里那两道 data.error / 空数组的拦截是必需的（门禁 check-tool-reality.cjs 之外的第二道）
})

// ===== 4. SEO 诊断（schema-valid 样本）=====
check('SEO 诊断：4 个维度 + checklist 计数 + 后端 grade', () => {
  const d = A.adaptSeoAudit(fixture('seo-audit.json'), {})
  assert(d.type === 'seo_audit', 'type 应为 seo_audit')
  assert(typeof d.overall_score === 'number', '缺 overall_score')
  assert(d.dimensions.length === 4, `应有 4 个维度，实际 ${d.dimensions.length}`)
  for (const dim of d.dimensions) {
    assert(typeof dim.key === 'string' && typeof dim.name === 'string' && typeof dim.score === 'number',
      `维度形状不对：${JSON.stringify(dim)}`)
  }
  assert(d.total_count === 5, `checklist 应有 5 项，实际 ${d.total_count}`)
  assert(d.passed_count === 3, `应通过 3 项，实际 ${d.passed_count}`)
  assert(d.failed_items.length === 2, `应有 2 项未通过，实际 ${d.failed_items.length}`)
  assert(d.grade === 'C', `grade 应透传后端（C），实际 ${JSON.stringify(d.grade)}`)
  assert(Array.isArray(d.improvement_areas) && d.improvement_areas.length > 0, 'improvement_areas 为空')
  // 后端只做文本 SEO ⇒ 不得出现图片/定价/评论等维度
  const names = d.dimensions.map((x) => x.name).join('|')
  for (const wrong of ['主图', '定价', '评论']) {
    assert(!names.includes(wrong), `维度里出现了后端给不出的「${wrong}」`)
  }
})

check('适配层：出参不得出现来自 mock 的假数据痕迹', () => {
  const dumped = JSON.stringify([
    A.adaptAdDiagnosis(fixture('ad-diagnosis.json'), {}),
    A.adaptBulletGen(fixture('bullet-gen.json'), {}),
    A.adaptCompetitorCompare(fixture('competitor-compare.json'), {}),
    A.adaptSeoAudit(fixture('seo-audit.json'), {}),
  ])
  for (const bad of ['Coffee Grinder Premium', 'lorem', 'placeholder', 'TODO', 'undefined']) {
    assert(!dumped.includes(bad), `出参里出现可疑字样「${bad}」`)
  }
})

// ===== 输出 =====
const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n工具结果适配层门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log('工具结果适配层门禁通过（真响应 → 适配层 → 结果卡字段 ✓）')

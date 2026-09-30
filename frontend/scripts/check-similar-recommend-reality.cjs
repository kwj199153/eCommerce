#!/usr/bin/env node
/**
 * 相似 ASIN 推荐「真数据」门禁（★ 第 167 轮 · #725）
 *
 * 为什么值得单独一个门禁
 * ====================
 * `src/utils/competitorSimilarity.ts` 的前身是 `mock/competitorRecommend.ts`，
 * 它做的事**看起来完全正常**：
 *
 *   · 排序是真的（类目 +10 / 类目包含 +6 / 关键词命中 +4）；
 *   · 返回的 ASIN 也是真的（有 title / brand / main_image）。
 *
 * 但它内部写的是 `const src = [...MOCK_PRODUCTS, ...universe]` ——
 * 调用方（`stores/competitorPool.ts`）**已经**从后端收集好了真实候选集
 * （产品库 + 候选库 ⇒ `sourceUniverse`），结果被**前置掺进**一批假商品；
 * 后面还有一句兜底 `if (score === 0 && p.title) score += 1`，
 * 而假数据的 `title` 一定存在 ⇒ 它们**必然拿到分、必然出现在「已推荐的竞品」里**。
 *
 * ★ 这是比纯 mock 更难发现的一类：列表里确实混着真东西，人一眼看不出哪几个是假的；
 *   而且**没有任何东西会红** —— 类型对、编译过、界面不报错。
 *   ⇒ 必须有一条断言**能对「又掺回来了」说不**。
 *
 * 为什么用**真跑**而不是源码形态判据
 * ================================
 * 本仓已有过「docstring 会骗过源码字符串判据」的教训（判据禁「源码包含」）。
 * 而这两件事**都能在运行期直接观测**，没必要退化成源码匹配：
 *
 *   ① 「内部还藏着数据源」 ⇒ **空 universe 必须返回空数组**。藏什么都拦得住。
 *   ② 「兜底分又加回来了」 ⇒ **毫无相似信号的项不得进入结果**。
 * 于是本门禁全部走 `ts.transpileModule` + `vm` 沙箱**真加载真调用**（零新依赖，
 * 与 `check-tool-adapters.cjs` / `check-session-registry.cjs` 同一套做法）。
 *
 * 六条断言
 * ========
 *   R1 空来源 ⇒ 必须返回 `[]`（**禁止任何内置兜底**：这是「掺假」的入口）
 *   R2 无相似信号 ⇒ 不得进入结果（**禁止兜底分凑数**：score<=0 必须剔除）
 *   R3 有真命中 ⇒ 主品被排除 / ASIN 去重 / 按分降序 / 类目命中 > 仅关键词命中
 *   R4 条数上限被夹到 `SIMILAR_RECOMMEND_MAX`，且 `count=0` ⇒ `[]`
 *   R5 自检 · 反向对照：把**旧实现**（内部种子 + 兜底分）喂给同一批用例，
 *      R1 / R2 **必须失败** —— 否则说明这两条断言是空跑的（「没被反向注入验证过的
 *      门禁 = 没有门禁」）
 *   R6 导出面完整性：`rankSimilarAsins` 与 `SIMILAR_RECOMMEND_MAX` 都在
 *
 * 怎么跑
 * ======
 *   node scripts/check-similar-recommend-reality.cjs
 *
 * 反向注入（证明本门禁不是空跑）
 * ============================
 *   SIMILAR_RECOMMEND_SRC=<改坏过的 competitorSimilarity.ts **副本文件路径**> \
 *     node scripts/check-similar-recommend-reality.cjs   —— 必须变红
 *   ★ 该变量吃的是**文件**路径，不是目录（本仓踩过一次：指成目录 ⇒
 *     `readFileSync` 抛 EISDIR ⇒ 进程 rc=1 但**一行 FAIL 都没有**，
 *     看起来像「门禁红了」，实际是崩了 —— 见 `h725g_reverse.py` 的第一次读数）。
 *   ★ 注意：R5 是**门禁内部**的反向对照，它守的是「R1/R2 有没有牙」；
 *     上面那个环境变量守的是「源码被改坏时门禁会不会红」。两者都要。
 */

const fs = require('fs')
const path = require('path')
const vm = require('vm')

const ROOT = path.resolve(__dirname, '..')
const SRC = process.env.SIMILAR_RECOMMEND_SRC
  ? path.resolve(process.env.SIMILAR_RECOMMEND_SRC)
  : path.join(ROOT, 'src', 'utils', 'competitorSimilarity.ts')

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

/**
 * 把任意 TS 源码转成 CJS 并在独立沙箱里取导出。
 * ★ 每例用**新沙箱**（本仓铁律：同一沙箱跨例会共享 module.exports，互相污染）。
 */
function loadFrom(code, filename) {
  const ts = require(path.join(ROOT, 'node_modules', 'typescript'))
  const out = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 },
    fileName: filename,
  }).outputText
  const sandbox = { module: { exports: {} }, exports: {}, require }
  sandbox.exports = sandbox.module.exports
  vm.createContext(sandbox)
  vm.runInContext(out, sandbox, { filename })
  return sandbox.module.exports
}

const R = loadFrom(fs.readFileSync(SRC, 'utf8'), SRC)

// ---------------------------------------------------------------- 测试素材

const MAIN = 'B000MAIN'
const OPTS = { title: 'Manual Coffee Grinder', category: 'kitchen', keywords: ['coffee'] }

/**
 * 主品自己 + 一个弱命中（类目不同，只中关键词）+ 一个真命中（同类目且多关键词）
 * + 一条重复。
 *
 * ★★ 顺序是刻意的：**弱命中必须排在强命中之前**。
 *   否则插入顺序本身就是降序 ⇒ 把 `scored.sort()` 整行删掉，R3 的降序断言
 *   照样通过（**素材自己让断言空跑了**）。
 *   这是「自检样本必须用它能漏掉的形态」在**测试素材**上的翻版：
 *   正则的漏网形态是跨行 import，排序断言的漏网形态是「插入序恰好正确」。
 */
const UNIVERSE = [
  { asin: MAIN, title: 'Manual Coffee Grinder', category: 'kitchen', keywords: ['coffee'] },
  { asin: 'B000B002', title: 'Coffee Mill', category: 'wrongcat', keywords: ['coffee'] },
  { asin: 'B000B001', title: 'Coffee Grinder Pro', category: 'kitchen', keywords: ['coffee', 'grinder'] },
  { asin: 'B000B001', title: '重复条目', category: 'kitchen', keywords: [] },
]

/** 没有任何相似信号：类目不同、关键词一个都不中 ⇒ score 必须是 0 */
const UNRELATED = [
  { asin: 'B000Z001', title: 'Completely Unrelated Thing', category: 'zzz', keywords: ['zzz'] },
  { asin: 'B000Z002', title: 'Yoga Mat', category: 'sports', keywords: ['yoga'] },
]

// ---------------------------------------------------------------- R6 导出面

check('R6 导出面：rankSimilarAsins 与 SIMILAR_RECOMMEND_MAX 都在', () => {
  assert(typeof R.rankSimilarAsins === 'function', 'rankSimilarAsins 不是函数（导出被改名/删掉了）')
  assert(
    typeof R.SIMILAR_RECOMMEND_MAX === 'number' && R.SIMILAR_RECOMMEND_MAX > 0,
    'SIMILAR_RECOMMEND_MAX 缺失或不是正数'
  )
})

// ---------------------------------------------------------------- R1 空来源

check('R1 空来源 ⇒ 必须返回 []（禁止任何内置兜底数据源）', () => {
  // ★ 诚实的说明（反向注入实测得出）：
  //   单把 `if (!universe.length) return []` 这行删掉，**本条仍会通过** ——
  //   因为空数组走下面的循环本来就产出 `[]`。所以那个提前返回是**意图声明**，
  //   不是防线；本条的牙在于「有人把子集扩成 `[...SEED, ...universe]`」这种改动。
  //   （反向注入必须**同时**删掉提前返回 + 加回种子，才能构成真回归 ——
  //     两者是耦合的，见 `.workbuddy/probes/h725g_reverse.py` 的 INJ-A / INJ-A2。）
  const r = R.rankSimilarAsins(MAIN, OPTS, 12, [])
  assert(Array.isArray(r), '返回值不是数组')
  assert(
    r.length === 0,
    `universe 为空时却返回了 ${r.length} 条（${r.map((x) => x.asin).slice(0, 3).join(',')}…）` +
      ' —— 说明模块内部又藏了数据源（旧实现就是在这里掺 `MOCK_PRODUCTS`）。' +
      '本模块必须零数据源，没有来源就返回空，由调用方显式告知用户。'
  )
  // 顺带：不传第 4 个参数（默认空数组）也必须一样
  const r2 = R.rankSimilarAsins(MAIN, OPTS, 12)
  assert(r2.length === 0, '不传 universe（默认空）时也必须返回 []')
})

// ---------------------------------------------------------------- R2 无信号

check('R2 无相似信号 ⇒ 不得进入结果（禁止兜底分凑数）', () => {
  const r = R.rankSimilarAsins(MAIN, OPTS, 12, UNRELATED)
  assert(
    r.length === 0,
    `类目与关键词**一个都没中**，却返回了 ${r.length} 条` +
      '（得分为 ' + r.map((x) => `${x.asin}:${x.score}`).join(',') + '）' +
      ' —— 这是旧实现的兜底分 `if (score === 0 && p.title) score += 1` 又回来了。' +
      '0 分意味着「没有任何相似信号」，返回它等于**编造相似性**。'
  )
  assert(
    UNRELATED.every((u) => (u.title || '') !== ''),
    '素材自身有问题：无信号样本不该带 title（否则测不出兜底分）'
  )
})

// ---------------------------------------------------------------- R3 真命中

check('R3 真命中：主品被排除 / ASIN 去重 / 按分降序 / 类目命中 > 仅关键词命中', () => {
  const r = R.rankSimilarAsins(MAIN, OPTS, 12, UNIVERSE)

  assert(!r.some((x) => x.asin === MAIN), '主品自己出现在推荐里（必须排除）')
  assert(new Set(r.map((x) => x.asin)).size === r.length, 'ASIN 未去重')
  assert(r.length === 2, `应恰好 2 条（排除主品 + 去重），实际 ${r.length}: ${r.map((x) => x.asin).join(',')}`)

  for (const x of r) {
    assert(typeof x.score === 'number' && x.score > 0, `${x.asin} 的 score 非法：${x.score}`)
  }
  for (let i = 0; i + 1 < r.length; i++) {
    assert(r[i].score >= r[i + 1].score, '未按 score 降序排列')
  }

  const strong = r.find((x) => x.asin === 'B000B001')
  const weak = r.find((x) => x.asin === 'B000B002')
  assert(strong && weak, '真命中样本没被返回全（B000B001 / B000B002）')
  assert(
    strong.score > weak.score,
    `同类目+多关键词命中的 B000B001(${strong.score}) 应高于仅关键词命中的 B000B002(${weak.score})`
  )
  // 字段必须原样透传（不许自造 / 不许丢）
  assert(strong.title === 'Coffee Grinder Pro', 'title 未原样透传')
})

// ---------------------------------------------------------------- R4 上限

check('R4 条数上限：夹到 SIMILAR_RECOMMEND_MAX；count=0 ⇒ []', () => {
  const many = Array.from({ length: 40 }, (_, i) => ({
    asin: 'B1' + String(i).padStart(8, '0'),
    title: 'Coffee Grinder',
    category: 'kitchen',
    keywords: ['coffee'],
  }))
  const r = R.rankSimilarAsins(MAIN, OPTS, 40, many)
  assert(
    r.length === R.SIMILAR_RECOMMEND_MAX,
    `期望夹到 ${R.SIMILAR_RECOMMEND_MAX} 条，实际 ${r.length}`
  )
  const z = R.rankSimilarAsins(MAIN, OPTS, 0, many)
  assert(z.length === 0, 'count=0 时必须返回 []')
})

// ---------------------------------------------------------------- R5 自检

check('R5 自检（反向对照）：旧实现喂给同一批用例，R1/R2 必须失败', () => {
  // 「旧实现」= 内部掺种子 + 兜底分。逐字复刻 mock 的两个要害，用来证明 R1/R2 有牙。
  const OLD_IMPL = `
    const SEED = [
      { asin: 'B000SEED1', title: 'Mock Coffee Grinder', category: 'kitchen', keywords: ['coffee'] },
    ]
    function norm(s) { return (s || '').toLowerCase().trim() }
    export const SIMILAR_RECOMMEND_MAX = 20
    export function rankSimilarAsins(mainAsin, opts, count = 12, universe = []) {
      const main = (mainAsin || '').toUpperCase()
      const keywordTerms = [
        ...(opts.keywords || []),
        ...(opts.title ? opts.title.split(/\\s+/).filter(w => w.length > 3) : []),
      ].map(norm)
      const category = norm(opts.category)
      const src = [...SEED, ...universe]
      const seen = new Set()
      const scored = []
      for (const p of src) {
        const asin = (p.asin || '').toUpperCase()
        if (!asin || asin === main || seen.has(asin)) continue
        seen.add(asin)
        let score = 0
        const c = norm(p.category)
        if (category && c && c === category) score += 10
        else if (category && c && c.includes(category)) score += 6
        const hay = norm((p.title || '') + ' ' + ((p.keywords || []).join(' ')))
        for (const kw of keywordTerms) { if (kw && hay.includes(kw)) score += 4 }
        if (score === 0 && p.title) score += 1
        scored.push({ asin, title: p.title, score })
      }
      scored.sort((a, b) => b.score - a.score)
      return scored.slice(0, Math.min(count, 20))
    }
  `
  const O = loadFrom(OLD_IMPL, 'old-impl.ts')

  // ① 空来源：旧实现会吐出内置种子 ⇒ R1 的断言必须在这里失败
  const r1 = O.rankSimilarAsins(MAIN, OPTS, 12, [])
  assert(
    r1.length > 0,
    'R1 的断言对旧实现**没有失败** ⇒ R1 是空跑的（它根本不能区分「有内置数据源」）'
  )
  // ② 无信号：旧实现靠兜底分把无关项捞回来 ⇒ R2 的断言必须在这里失败
  const r2 = O.rankSimilarAsins(MAIN, OPTS, 12, UNRELATED)
  assert(
    r2.length > 0,
    'R2 的断言对旧实现**没有失败** ⇒ R2 是空跑的（它根本不能区分「有兜底分」）'
  )
  // ③ 同时确认我的复刻确实复刻到位（否则上面两条的「失败」可能是别的原因）
  assert(r1.some((x) => x.asin === 'B000SEED1'), '复刻的旧实现没有掺种子，自检无效')
  //    ★ 只挑**无关样本**那两条来判兜底分：r2 里还混着种子项（它因类目命中得 11 分），
  //      用 `every` 判整个数组会把这个无关事实也算进来 ⇒ 假红。
  const foreign = r2.filter((x) => x.asin.startsWith('B000Z'))
  assert(
    foreign.length === UNRELATED.length && foreign.every((x) => x.score === 1),
    '复刻的旧实现没有兜底分（无关项得分应为 1），自检无效：' +
      JSON.stringify(foreign.map((x) => `${x.asin}:${x.score}`))
  )
})

// ---------------------------------------------------------------- 输出

const failed = results.filter((r) => !r.ok)
for (const r of results) {
  console.log(`  ${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '  ← ' + r.msg}`)
}
console.log(`\n${results.length - failed.length}/${results.length} 通过`)
if (failed.length) {
  console.error(`\n相似 ASIN 推荐「真数据」门禁失败：${failed.length} 条`)
  process.exit(1)
}
console.log(
  '相似 ASIN 推荐「真数据」门禁通过（空来源 fail-closed ✓ / 无兜底分 ✓ / ' +
    '主品排除+去重+降序 ✓ / 上限夹取 ✓ / 反向对照有牙 ✓）'
)

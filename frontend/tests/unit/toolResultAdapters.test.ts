/**
 * `utils/toolResultAdapters.ts` 行为契约（第 356 轮 · 前端单测第二批）
 * ============================================================================
 * 为什么挑它：文件头自己列了三条硬规则，而**每一条的违反都是静默的** ——
 * 适配层是「后端真值 → 结果卡形状」的唯一关口，它一旦开始编造或丢弃，
 * 界面不会报错，只会**多出一个假数字**或**少显示一块真信息**：
 *
 *   ① 后端**没有**的字段一律**不编造**（留空或退化）
 *      —— 例：五点的 `emoji`、竞品的 `listing_quality_score` / `price_positioning`。
 *      这三个字段在旧 mock 里存在，是「顺手补上」的天然诱因。
 *   ② 后端**多出来**的真实信息尽量带上，不丢
 *      —— 例：`coverage_score` / `total_characters` / `checklist` /
 *      `differentiation_analysis`。它们不在旧 mock 的字段表里，容易被过滤掉。
 *   ③ 评分档位一律走真源，**本文件不另立阈值**。
 *
 * ★ 另外本文件钉住 `flattenDifferentiation` 的「**逐段独立**」语义：
 *   只有价格就只显示价格，**不**为了凑格式补「评分跨度 -」。
 *   那是把「没有真值」渲染成「有真值」的经典形态。
 *
 * ★ 本文件**只测纯逻辑**。适配层不碰 DOM / 网络 / Pinia ⇒ 在
 *   `environment: 'node'` 下直接跑，不需要任何桩（若哪天需要，请先看
 *   `vitest.config.ts` 文件头为什么首批刻意不开 jsdom）。
 */
import { describe, it, expect } from 'vitest'
import {
  adaptAdDiagnosis,
  adaptBulletGen,
  adaptSeoAudit,
  adaptCompetitorCompare,
  flattenDifferentiation,
} from '@/utils/toolResultAdapters'

describe('toolResultAdapters · unwrap（后端两种包装层都要认）', () => {
  it('带 success 的响应 ⇒ 取 data', () => {
    const r = adaptBulletGen({ success: true, data: { product_name: '来自 data' } }, {})
    expect(r.product_name).toBe('来自 data')
  })

  it('不带 success 的裸响应 ⇒ 原样使用（不能把整包当 data 丢掉）', () => {
    const r = adaptBulletGen({ product_name: '来自裸响应' }, {})
    expect(r.product_name).toBe('来自裸响应')
  })

  it('resp 为 null / undefined ⇒ 退化到空对象，不抛错', () => {
    expect(adaptBulletGen(null, {}).bullets).toEqual([])
    expect(adaptBulletGen(undefined, {}).bullets).toEqual([])
  })
})

describe('toolResultAdapters · adaptBulletGen（★ 规则①不编造 / 规则②不丢真值）', () => {
  it('★ coverage_score 后端没给 ⇒ null（不是 0 —— 0 是一个具体分数）', () => {
    const r = adaptBulletGen({ bullets: [] }, {})
    expect(r.coverage_score).toBeNull()
    // 后端给了才带上（0 也要带上：那是真值）
    expect(adaptBulletGen({ bullets: [], coverage_score: 0 }, {}).coverage_score).toBe(0)
  })

  it('★ 不产出 `emoji` 字段（后端没有；结果卡也不依赖它）', () => {
    const r = adaptBulletGen({ bullets: [{ title: 't', content: 'c' }] }, {})
    expect(r.bullets[0]).not.toHaveProperty('emoji')
  })

  it('char_count：后端给就用；没给则**算** content 长度（不是留空）', () => {
    const r = adaptBulletGen({ bullets: [{ content: 'abcd' }, { content: 'xy', character_count: 99 }] }, {})
    expect(r.bullets[0].char_count).toBe(4)
    expect(r.bullets[1].char_count).toBe(99)
  })

  it('bullet_id：后端给就用（含 0）；没给则退化为序号（1 起）', () => {
    const r = adaptBulletGen({ bullets: [{}, {}, { bullet_id: 0 }] }, {})
    expect(r.bullets.map((b: any) => b.bullet_id)).toEqual([1, 2, 0])
  })

  it('★ `_source` 由 params 推出（前端自用字段，不是伪造后端数据）', () => {
    expect(adaptBulletGen({}, { source: 'product_library' })._source).toBe('product')
    expect(adaptBulletGen({}, { source: 'manual' })._source).toBe('manual')
    expect(adaptBulletGen({}, {})._source).toBe('manual')
  })

  it('product_name：后端优先，退到 params，再退到空串', () => {
    expect(adaptBulletGen({ product_name: 'A' }, { product_name: 'B' }).product_name).toBe('A')
    expect(adaptBulletGen({}, { product_name: 'B' }).product_name).toBe('B')
    expect(adaptBulletGen({}, {}).product_name).toBe('')
  })

  it('★ 规则②不丢真值：`tips` 映射到结果卡沿用的 `optimization_suggestions`', () => {
    expect(adaptBulletGen({ tips: ['a', 'b'] }, {}).optimization_suggestions).toEqual(['a', 'b'])
    expect(adaptBulletGen({ tips: 'not-an-array' }, {}).optimization_suggestions).toEqual([])
  })

  it('★ 规则②不丢真值：`total_characters` 带上（缺省 0）', () => {
    expect(adaptBulletGen({ total_characters: 123 }, {}).total_characters).toBe(123)
    expect(adaptBulletGen({}, {}).total_characters).toBe(0)
  })

  it('bullets 不是数组 ⇒ 空数组（不抛错）', () => {
    expect(adaptBulletGen({ bullets: 'oops' }, {}).bullets).toEqual([])
  })
})

describe('toolResultAdapters · adaptAdDiagnosis（对齐即可，不转换）', () => {
  it('顶层字段原样透传，并补上前端元字段', () => {
    const r = adaptAdDiagnosis({ overall_score: 72, grade: 'B', campaigns: [{ id: 1 }] }, { shop: 's1' })
    expect(r.overall_score).toBe(72)
    expect(r.grade).toBe('B')
    expect(r.campaigns).toEqual([{ id: 1 }])
    expect(r.type).toBe('ad_diagnosis')
    expect(r.params).toEqual({ shop: 's1' })
  })
})

describe('toolResultAdapters · adaptSeoAudit（★ checklist 是真值，不摊派）', () => {
  it('★ 未通过项 = 值为 false 的键（`passed` 严格判 `=== true`）', () => {
    const r = adaptSeoAudit(
      { checklist: { a: true, b: false, c: 1, d: 'true', e: null } },
      {},
    )
    expect(r.failed_items).toEqual(['b', 'c', 'd', 'e'])
    expect(r.passed_count).toBe(1)
    expect(r.total_count).toBe(5)
  })

  it('checklist 不是对象（数组 / null / 字符串）⇒ 退化成空表，不抛错', () => {
    for (const bad of [[], null, 'x', 42]) {
      const r = adaptSeoAudit({ checklist: bad }, {})
      expect(r.checklist).toEqual([])
      expect(r.failed_items).toEqual([])
    }
  })

  it('★ dimensions 只收后端**真给了数字**的维度（没给的维度不出现、不补 0）', () => {
    const r = adaptSeoAudit({ title_score: 80, keywords_score: 0 }, {})
    expect(r.dimensions.map((d: any) => d.key)).toEqual(['title_score', 'keywords_score'])
    expect(r.dimensions.map((d: any) => d.score)).toEqual([80, 0])
  })

  it('★ grade 原样透传（前端**不**自算等级）', () => {
    expect(adaptSeoAudit({ grade: 'C' }, {}).grade).toBe('C')
    expect(adaptSeoAudit({}, {}).grade).toBe('')
  })

  it('overall_score 缺省 ⇒ 0（不是 null —— 结果卡按数字渲染）', () => {
    expect(adaptSeoAudit({}, {}).overall_score).toBe(0)
  })

  it('★ 规则②不丢真值：`improvement_areas` 整体带上（不做按维度摊派）', () => {
    const r = adaptSeoAudit({ improvement_areas: ['加长标题'] }, {})
    expect(r.improvement_areas).toEqual(['加长标题'])
  })
})

describe('toolResultAdapters · flattenDifferentiation（★ 逐段独立，缺就不显示）', () => {
  it('后端改回字符串形态 ⇒ 原样返回（兼容旧形态）', () => {
    expect(flattenDifferentiation('已经是一句话')).toBe('已经是一句话')
  })

  it('null / 非对象 ⇒ 空串（整块隐藏，不是渲染 "undefined"）', () => {
    expect(flattenDifferentiation(null)).toBe('')
    expect(flattenDifferentiation(42)).toBe('')
    expect(flattenDifferentiation(undefined)).toBe('')
  })

  it('★ 只有价格跨度 ⇒ **只**出价格那一段（不补「评分跨度 -」凑格式）', () => {
    expect(flattenDifferentiation({ price_spread: 12.5 })).toBe('价格跨度 $12.5')
  })

  it('★★ 全空对象 ⇒ 空串（这是「没有真值」与「有真值」的分界）', () => {
    expect(flattenDifferentiation({})).toBe('')
    expect(flattenDifferentiation({ market_segments: [], gap_opportunities: [] })).toBe('')
  })

  it('市场档次拼成一行（品牌(档次)、顿号分隔）', () => {
    const text = flattenDifferentiation({ market_segments: [{ brand: 'A', segment: '高端' }, { brand: 'B', segment: '入门' }] })
    expect(text).toBe('市场档次：A(高端)、B(入门)')
  })

  it('缺 brand / segment 用 `-` 占位（不产出 "undefined(undefined)"）', () => {
    const text = flattenDifferentiation({ market_segments: [{}] })
    expect(text).toBe('市场档次：-(-)')
  })

  it('空白机会用分号连接；空串项被过滤', () => {
    const text = flattenDifferentiation({ gap_opportunities: ['防晒', '', '便携'] })
    expect(text).toBe('空白机会：防晒；便携')
  })

  it('★ 多段之间用 ` ｜ ` 连接，顺序固定（价格 → 评分 → 档次 → 机会）', () => {
    const text = flattenDifferentiation({
      price_spread: 10,
      rating_spread: 0.4,
      market_segments: [{ brand: 'A', segment: '高端' }],
      gap_opportunities: ['x'],
    })
    expect(text).toBe('价格跨度 $10 ｜ 评分跨度 0.4 ｜ 市场档次：A(高端) ｜ 空白机会：x')
  })
})

describe('toolResultAdapters · adaptCompetitorCompare（★ 按 asin 重建，不编造）', () => {
  const RESP = {
    compared_count: 2,
    competitors: [
      { asin: 'B1', brand: 'A', title: 'T1' },
      { asin: 'B2', brand: 'B', title: 'T2' },
    ],
    comparison: {
      price_comparison: { values: [{ asin: 'B1', value: 10 }, { asin: 'B2', value: 20 }] },
      rating_comparison: { values: [{ asin: 'B1', value: 4.5 }] },
      review_count_comparison: { values: [{ asin: 'B2', value: 100 }] },
      bsr_comparison: { values: [{ asin: 'B1', value: 7 }] },
      value_score: [{ asin: 'B1', value_score: 88 }],
      overall_ranking: [{ asin: 'B2', rank: 1 }],
      differentiation_analysis: { price_spread: 10 },
      recommendations: ['保持价格'],
    },
  }

  it('★ 按 asin 把散在各处的比较值重建到行上', () => {
    const r = adaptCompetitorCompare(RESP, {})
    expect(r.competitors[0]).toMatchObject({ asin: 'B1', price: 10, rating: 4.5, review_count: null, bsr_rank: 7, value_score: 88 })
    expect(r.competitors[1]).toMatchObject({ asin: 'B2', price: 20, rating: null, review_count: 100, rank: 1 })
  })

  it('★ 缺的比较值保持 null（**不是 0** —— 0 会被读成「免费/零评分」）', () => {
    const r = adaptCompetitorCompare({ competitors: [{ asin: 'B1' }] }, {})
    expect(r.competitors[0]).toMatchObject({ price: null, rating: null, review_count: null, bsr_rank: null })
  })

  it('★ 不产出后端没有的字段（`listing_quality_score` / `price_positioning` 是旧 mock 的）', () => {
    const r = adaptCompetitorCompare(RESP, {})
    expect(r.competitors[0]).not.toHaveProperty('listing_quality_score')
    expect(r.competitors[0]).not.toHaveProperty('price_positioning')
  })

  it('★ price_range 只对**真有数字**的价格求 min/max；一个都没有 ⇒ null（不是 {0,0}）', () => {
    expect(adaptCompetitorCompare(RESP, {}).price_range).toEqual({ min: 10, max: 20 })
    expect(adaptCompetitorCompare({ competitors: [{ asin: 'B1' }] }, {}).price_range).toBeNull()
  })

  it('★ avg_rating 是本次对比集内的平均；无有效评分 ⇒ null', () => {
    const r = adaptCompetitorCompare(
      { competitors: [{ asin: 'B1' }, { asin: 'B2' }], comparison: { rating_comparison: { values: [{ asin: 'B1', value: 4 }, { asin: 'B2', value: 5 }] } } },
      {},
    )
    expect(r.avg_rating).toBe(4.5)
    expect(adaptCompetitorCompare({ competitors: [] }, {}).avg_rating).toBeNull()
  })

  it('★ market_leader = rank 恰为 1 的那条（没有 rank 1 ⇒ 空串）', () => {
    expect(adaptCompetitorCompare(RESP, {}).market_leader).toBe('B2')
    expect(adaptCompetitorCompare({ competitors: [{ asin: 'B1' }] }, {}).market_leader).toBe('')
  })

  it('compared_count 缺省 ⇒ 退回 competitors 条数', () => {
    expect(adaptCompetitorCompare({ competitors: [{ asin: 'B1' }, { asin: 'B2' }] }, {}).compared_count).toBe(2)
  })

  it('recommendations 拼成换行文本；非数组 ⇒ 空串', () => {
    expect(adaptCompetitorCompare(RESP, {}).recommendation).toBe('保持价格')
    expect(adaptCompetitorCompare({}, {}).recommendation).toBe('')
  })

  it('★ differentiation_text 由 flattenDifferentiation 产出（组件不自己拼）', () => {
    expect(adaptCompetitorCompare(RESP, {}).differentiation_text).toBe('价格跨度 $10')
  })

  it('comparison 不是对象 ⇒ 各行字段全是 null，不抛错', () => {
    const r = adaptCompetitorCompare({ competitors: [{ asin: 'B1' }], comparison: 'x' }, {})
    expect(r.competitors[0].price).toBeNull()
  })
})

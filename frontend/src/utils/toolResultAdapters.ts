/**
 * 工具结果适配层（P0-2 批 1）
 *
 * 后端 4 个端点的响应形状与前端结果卡期望形状**并不一致**。
 * 本模块集中承载「后端真值 → 结果卡形状」的转换，三条硬规则：
 *
 *   ① 后端**没有**的字段一律**不编造** —— 留空或退化，由结果卡自身容错；
 *      （例：五点描述的 `emoji`、竞品的 `listing_quality_score` / `price_positioning`）
 *   ② 后端**多出来**的真实信息尽量带上，不丢；
 *      （例：`coverage_score` / `total_characters` / `checklist` / `differentiation_analysis`）
 *   ③ 评分档位与等级一律走 `theme/bands.ts` 真源，**本文件不另立阈值**。
 *
 * 字段级映射证据见 `.workbuddy/probes/out-r128-contract.md`。
 */

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** 后端各端点包装层不同：`/ad-analysis`·`/listing` 是 {data}，`/competitor/compare` 也是 {data} */
const unwrap = (resp: any): any => {
  if (resp && typeof resp === 'object' && 'data' in resp && resp.success !== undefined) return resp.data
  return resp
}

// ==================== 广告诊断 ====================

/**
 * 广告诊断：后端 `DiagnosisResponse{overall_score, grade, summary, metrics[],
 * campaigns[], top_issues[], recommendations[]}` 与结果卡 `AdDiagnosisResult.vue`
 * 消费的字段**逐字对齐** ⇒ 无需字段转换，只补前端自用的元字段。
 */
export function adaptAdDiagnosis(resp: any, params: any) {
  const d = unwrap(resp) || {}
  return {
    ...d,
    type: 'ad_diagnosis',
    params,
  }
}

// ==================== 五点描述 ====================

/**
 * 五点描述
 *
 * 后端 `BulletPoint{bullet_id, title, content, character_count, emotion_trigger}`
 * ⇒ `BulletGenerator.vue` 的 `normalizeBullet()`「已结构化」分支要求
 *   `title` 与 `content` **同时存在**（该分支优先于 `point` 分支）。
 *
 * ★ 后端没有 `emoji` ⇒ 不输出该字段（组件不依赖它）。
 * ★ `_source` / `product_id` 是**前端自用**字段（结果卡「应用到当前产品」定位），
 *   后端没有、也不该有 ⇒ 由 params 回填，不是伪造数据。
 */
export function adaptBulletGen(resp: any, params: any) {
  const d = unwrap(resp) || {}
  const raw = Array.isArray(d.bullets) ? d.bullets : []

  return {
    type: 'bullet_gen',
    params,
    product_name: d.product_name || params?.product_name || '',
    _source: params?.source === 'product_library' ? 'product' : 'manual',
    product_id: params?.product_id,
    bullets: raw.map((b: any, i: number) => ({
      bullet_id: isNum(b?.bullet_id) ? b.bullet_id : i + 1,
      title: b?.title || '',
      content: b?.content || '',
      char_count: isNum(b?.character_count)
        ? b.character_count
        : String(b?.content || '').length,
      emotion_trigger: b?.emotion_trigger || '',
    })),
    /** 后端真值：总字符数与卖点覆盖度（原 mock 没有这两项） */
    total_characters: isNum(d.total_characters) ? d.total_characters : 0,
    coverage_score: isNum(d.coverage_score) ? d.coverage_score : null,
    /** 结果卡沿用的字段名：后端叫 tips */
    optimization_suggestions: Array.isArray(d.tips) ? d.tips : [],
  }
}

// ==================== SEO 诊断 ====================

/**
 * SEO 诊断
 *
 * 后端 `SEOScore{overall_score, title_score, bullet_score, description_score,
 * keywords_score, checklist: Record<string,boolean>, improvement_areas: string[]}` + `grade`
 *
 * ★ 关键取舍：
 *   - `checklist` 是 `{检查项: 是否通过}` ⇒ **未通过项 = 值为 false 的键**，这是真值，
 *     直接作为「待修问题」暴露；
 *   - `improvement_areas` 是**全局**列表，**分不到具体维度** ⇒ 不做「按维度摊派」，
 *     整体放到 `improvement_areas` 由结果卡单独成块显示；
 *   - 后端只做**文本** SEO，**没有**图片 / 定价 / 评论 / A+ / 类目排名维度
 *     ⇒ 这些维度**不产出**，结果卡也不应展示（旧 UI 的对应 tab 属演示虚构，已删）。
 */
export function adaptSeoAudit(resp: any, params: any) {
  const d = unwrap(resp) || {}

  const DIMS: Array<{ key: string; name: string }> = [
    { key: 'title_score', name: '标题 SEO' },
    { key: 'bullet_score', name: '五点描述' },
    { key: 'description_score', name: '产品描述' },
    { key: 'keywords_score', name: '关键词覆盖' },
  ]

  const checklist =
    d.checklist && typeof d.checklist === 'object' && !Array.isArray(d.checklist)
      ? (d.checklist as Record<string, any>)
      : {}

  const items = Object.keys(checklist).map((k) => ({ item: k, passed: checklist[k] === true }))

  return {
    type: 'seo_audit',
    params,
    overall_score: isNum(d.overall_score) ? d.overall_score : 0,
    /** 后端已给 grade（`_calculate_grade`），前端不再自算 */
    grade: d.grade || '',
    dimensions: DIMS.filter((x) => isNum(d[x.key])).map((x) => ({
      key: x.key,
      name: x.name,
      score: d[x.key] as number,
    })),
    checklist: items,
    failed_items: items.filter((x) => !x.passed).map((x) => x.item),
    passed_count: items.filter((x) => x.passed).length,
    total_count: items.length,
    improvement_areas: Array.isArray(d.improvement_areas) ? d.improvement_areas : [],
  }
}

// ==================== 竞品对比 ====================

/**
 * 差异化分析展平（★ 唯一实现，放适配层而非组件 —— 组件里的逻辑门禁测不到）。
 *
 * 后端 `comparison.differentiation_analysis` 实测是**对象**：
 *   { price_spread: number, rating_spread: number,
 *     market_segments: [{ brand, segment }], gap_opportunities: string[] }
 * 结果卡只显示一行文本 ⇒ 在这里展平。
 *
 * ★ 不编造：任一段没有真值就**不显示那一段**；全空返回 `''`（整块隐藏）。
 * ★ 兼容后端改回字符串的形态（原样返回）。
 */
export function flattenDifferentiation(d: any): string {
  if (!d) return ''
  if (typeof d === 'string') return d
  if (typeof d !== 'object') return ''

  const parts: string[] = []
  if (isNum(d.price_spread)) parts.push(`价格跨度 $${d.price_spread}`)
  if (isNum(d.rating_spread)) parts.push(`评分跨度 ${d.rating_spread}`)

  const segs = Array.isArray(d.market_segments) ? d.market_segments : []
  const segText = segs
    .map((s: any) => `${s?.brand || '-'}(${s?.segment || '-'})`)
    .filter(Boolean)
    .join('、')
  if (segText) parts.push(`市场档次：${segText}`)

  const gaps = Array.isArray(d.gap_opportunities) ? d.gap_opportunities.filter(Boolean) : []
  if (gaps.length) parts.push(`空白机会：${gaps.join('；')}`)

  return parts.join(' ｜ ')
}

/**
 * 竞品对比
 *
 * 后端 `data.competitors[]` **只回** `{asin, brand, title}`；
 * 价格 / 评分 / 评论数 / BSR 分散在 `comparison.{price,rating,review_count,bsr}_comparison.values[]`
 * （每项 `{asin, brand, value}`），性价比与排名分别在 `comparison.value_score[]` /
 * `comparison.overall_ranking[]`。本函数按 `asin` 把它们重建成结果卡需要的表格行。
 *
 * ★ 不编造：
 *   - 旧结果卡的 `listing_quality_score` / `price_positioning` 后端**没有** ⇒ 不产出，
 *     结果卡改用后端真有的 `value_score`（性价比）与 `rank`（综合排名）；
 *   - `price_range` / `avg_rating` 是**本次对比集内的聚合**（纯粹展示口径），
 *     **不是**业务判据，也不参与任何阈值比较。
 */
export function adaptCompetitorCompare(resp: any, params: any) {
  const d = unwrap(resp) || {}
  const cmp = (d.comparison && typeof d.comparison === 'object') ? d.comparison : {}

  const flat = (name: string): Record<string, number> => {
    const out: Record<string, number> = {}
    const arr = cmp[name]?.values
    if (Array.isArray(arr)) {
      for (const v of arr) {
        if (v?.asin != null && isNum(v.value)) out[String(v.asin)] = v.value
      }
    }
    return out
  }

  const price = flat('price_comparison')
  const rating = flat('rating_comparison')
  const reviews = flat('review_count_comparison')
  const bsr = flat('bsr_comparison')

  const byAsin = (list: any, field: string): Record<string, number> => {
    const out: Record<string, number> = {}
    if (Array.isArray(list)) {
      for (const v of list) {
        if (v?.asin != null && isNum(v[field])) out[String(v.asin)] = v[field]
      }
    }
    return out
  }
  const valueMap = byAsin(cmp.value_score, 'value_score')
  const rankMap = byAsin(cmp.overall_ranking, 'rank')

  const base: any[] = Array.isArray(d.competitors) ? d.competitors : []
  const competitors = base.map((c: any) => {
    const asin = String(c?.asin ?? '')
    return {
      asin,
      brand: c?.brand || '',
      title: c?.title || '',
      price: price[asin] ?? null,
      rating: rating[asin] ?? null,
      review_count: reviews[asin] ?? null,
      bsr_rank: bsr[asin] ?? null,
      value_score: valueMap[asin] ?? null,
      rank: rankMap[asin] ?? null,
    }
  })

  const prices = competitors.map((c) => c.price).filter(isNum)
  const ratings = competitors.map((c) => c.rating).filter(isNum)
  const leader = competitors.find((c) => c.rank === 1)
  const recs: string[] = Array.isArray(cmp.recommendations) ? cmp.recommendations : []

  return {
    type: 'competitor_comparison',
    params,
    compared_count: isNum(d.compared_count) ? d.compared_count : competitors.length,
    competitors,
    price_range: prices.length ? { min: Math.min(...prices), max: Math.max(...prices) } : null,
    avg_rating: ratings.length ? ratings.reduce((a, b) => a + b, 0) / ratings.length : null,
    market_leader: leader?.asin || '',
    recommendation: recs.join('\n'),
    /** 后端真有的额外信息（旧 mock 没有） */
    differentiation: cmp.differentiation_analysis || null,
    /** 展平后的展示文本（组件直接渲染它，不再自己拼） */
    differentiation_text: flattenDifferentiation(cmp.differentiation_analysis),
    overall_ranking: Array.isArray(cmp.overall_ranking) ? cmp.overall_ranking : [],
  }
}

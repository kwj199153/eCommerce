/**
 * 相似 ASIN 排序器 —— **纯函数，零数据源**
 *
 * ★ 为什么从 `mock/competitorRecommend.ts` 搬到这里（第 167 轮 · #725）
 * ================================================================
 * 原实现第二行就是 `const src = [...MOCK_PRODUCTS, ...universe]`。
 * 而调用方（`stores/competitorPool.ts` 的 `recommendSimilar`）**已经**
 * 从后端收集了真实候选集 —— 产品库 `prodStore.items` + 候选库 `candStore.items`
 * （见同文件的 `sourceUniverse`），再作为 `universe` 传进来。
 * 也就是说：**真数据是有的，假数据是额外加进去的**。这比纯 mock 更难发现，
 * 因为结果列表里确实混着真东西，看起来「像在工作」。
 *
 * 更隐蔽的是兜底分：
 *   `if (score === 0 && p.title) score += 1`
 * 假数据的 `title` 一定存在 ⇒ 它们**必然拿到分、必然出现在结果里**；
 * 而真数据里那些「类目不同、关键词也没命中」的项，本来**不该**被推荐。
 * 于是「没有相似信号」与「有一丁点相似」变得**不可区分**。
 *
 * 本模块因此只保留**算法**，数据一律由调用方注入，并加两条硬约束：
 *   1. **没有兜底分** —— `score <= 0` 表示「没有任何相似信号」，
 *      返回它就等于**编造相似性**。现在只返回 `score > 0` 的项（宁少不假）。
 *   2. **`universe` 为空 ⇒ 直接返回 `[]`** —— fail-closed。
 *      本模块**不持有任何内置数据**，也永远不会用内置数据凑数；
 *      「没有可用来源」这件事由调用方负责**显式告诉用户**。
 *
 * 相似度口径（与旧实现逐字一致，只是去掉了兜底分）：
 *   · 类目完全相同        +10
 *   · 类目包含（弱匹配）  +6
 *   · 每个关键词命中      +4   （关键词 = `opts.keywords` + 标题中长度 > 3 的词）
 */

export interface SimilarHit {
  asin: string
  title?: string
  brand?: string
  main_image?: string
  score: number
}

/** 供排序器消费的候选条目（与 `competitorPool` 的 `CompetitorCandidateInput` 同形） */
export interface SimilarUniverseItem {
  asin: string
  title?: string
  brand?: string
  category?: string
  main_image?: string
  keywords?: string[]
}

/** 单次排序的条数上限（算法侧上限；竞品池自身的上限由 store 决定） */
export const SIMILAR_RECOMMEND_MAX = 20

function norm(s?: string): string {
  return (s || '').toLowerCase().trim()
}

/**
 * 从 `universe` 里挑出与主品相似的 ASIN，按相似度降序，最多 `count` 个。
 *
 * @param mainAsin 主品 ASIN（会被排除）
 * @param opts     主品特征（标题 / 类目 / 关键词），用于算相似度
 * @param count    期望条数（会被夹到 `[0, SIMILAR_RECOMMEND_MAX]`）
 * @param universe 候选来源。**空 ⇒ 返回 `[]`**，本函数不会用任何内置数据兜底
 */
export function rankSimilarAsins(
  mainAsin: string,
  opts: { title?: string; category?: string; keywords?: string[] },
  count = 12,
  universe: SimilarUniverseItem[] = []
): SimilarHit[] {
  const main = (mainAsin || '').toUpperCase()

  // ★ fail-closed：没有来源就返回空。绝不内置商品，也不用随机/占位填充
  if (!universe.length) return []

  const keywordTerms = [
    ...(opts.keywords || []),
    ...(opts.title ? opts.title.split(/\s+/).filter(w => w.length > 3) : []),
  ].map(norm).filter(Boolean)
  const category = norm(opts.category)

  const seen = new Set<string>()
  const scored: SimilarHit[] = []

  for (const p of universe) {
    const asin = (p.asin || '').toUpperCase()
    if (!asin || asin === main || seen.has(asin)) continue
    seen.add(asin)

    let score = 0
    const c = norm(p.category)
    if (category && c && c === category) score += 10
    else if (category && c && c.includes(category)) score += 6

    const kw = Array.isArray(p.keywords) ? p.keywords : []
    const hay = norm((p.title || '') + ' ' + kw.join(' '))
    for (const term of keywordTerms) {
      if (term && hay.includes(term)) score += 4
    }

    // ★ 无兜底：score <= 0 = 没有任何相似信号 ⇒ 不进结果
    if (score <= 0) continue

    scored.push({ asin, title: p.title, brand: p.brand, main_image: p.main_image, score })
  }

  scored.sort((a, b) => b.score - a.score)
  const n = Math.min(Math.max(count | 0, 0), SIMILAR_RECOMMEND_MAX)
  return scored.slice(0, n)
}

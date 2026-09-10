/**
 * 竞品自动推荐 mock 引擎
 *
 * 在无真实亚马逊相似商品接口的演示/离线环境，从本地数据源（产品库 + 候选库 + MOCK_PRODUCTS）
 * 按主品的类目/关键词相似度返回一批“相似 ASIN”，供竞品池「一键自动抓取」预加载。
 *
 * 真实上线：此处替换为后端 /api/.../similar 端点（亚马逊 Similar Items / 选品数据源）。
 */

import { MOCK_PRODUCTS } from './data'

export interface RecommendHit {
  asin: string
  title?: string
  brand?: string
  main_image?: string
  score: number
}

export interface RecommendUniverseItem {
  asin: string
  title?: string
  brand?: string
  category?: string
  main_image?: string
  keywords?: string[]
}

function norm(s?: string): string {
  return (s || '').toLowerCase().trim()
}

/**
 * 返回一批相似竞品候选，按相似度排序，最多 count 个。
 * @param mainAsin 主品 ASIN（会被排除）
 * @param opts 主品特征（标题/类目/关键词），用于算相似度
 * @param universe 可选：真实库商品（产品库+候选库），叠加在 MOCK 之上，避免循环依赖由调用方注入
 */
export function recommendSimilarAsins(
  mainAsin: string,
  opts: { title?: string; category?: string; keywords?: string[] },
  count = 12,
  universe: RecommendUniverseItem[] = []
): RecommendHit[] {
  const keywordTerms = [
    ...(opts.keywords || []),
    ...(opts.title ? opts.title.split(/\s+/).filter(w => w.length > 3) : []),
  ].map(norm)
  const category = norm(opts.category)

  const src: RecommendUniverseItem[] = [...MOCK_PRODUCTS, ...universe]

  const scored: RecommendHit[] = []
  const seen = new Set<string>()

  for (const p of src) {
    const asin = (p.asin || '').toUpperCase()
    if (!asin || asin === mainAsin.toUpperCase() || seen.has(asin)) continue
    seen.add(asin)

    let score = 0
    const t = norm(p.title)
    const c = norm(p.category)

    // 同类目加权
    if (category && c && c === category) score += 10
    else if (category && c && c.includes(category)) score += 6

    // 关键词命中
    const hay = norm((p.title || '') + ' ' + ((p.keywords || []) as string[]).join(' '))
    for (const kw of keywordTerms) {
      if (kw && hay.includes(kw)) score += 4
    }

    // 兜底：至少给个基础分，确保能推荐满
    if (score === 0 && p.title) score += 1

    scored.push({ asin, title: p.title, brand: p.brand, main_image: p.main_image, score })
  }

  scored.sort((a, b) => b.score - a.score)
  return scored.slice(0, Math.min(count, 20))
}

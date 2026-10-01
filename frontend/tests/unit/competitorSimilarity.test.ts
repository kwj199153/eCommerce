/**
 * `utils/competitorSimilarity.ts` 行为契约（第 355 轮 · #1282 前端单测起步）
 * ============================================================================
 * 这个模块的 docstring 是一份**缺陷复盘**：#725 之前它住在
 * `mock/competitorRecommend.ts`，第二行就是 `[...MOCK_PRODUCTS, ...universe]`，
 * 于是「真数据里混进了假数据」，且假数据必然拿到兜底分、必然出现在结果里。
 * 搬到这里时立了三条硬约束，本文件把它们**逐条变成可执行断言**：
 *
 *   ① **没有兜底分** —— `score <= 0` = 没有任何相似信号 ⇒ 不进结果。
 *      老实现的 `if (score === 0 && p.title) score += 1` 就是「编造相似性」。
 *   ② **`universe` 为空 ⇒ `[]`** —— fail-closed，本模块不持有任何内置数据。
 *   ③ 计分口径：类目完全相同 +10 / 类目包含 +6（与①互斥，不叠加）/ 每关键词命中 +4。
 *
 * ★ 为什么这些断言值得写（违反时的后果都是**静默**的）：
 *   把 ① 改回去 ⇒ 结果列表里全是「零相似」的商品，界面看着"有推荐"，
 *   调用方无从分辨「真有相似信号」与「兜底凑数」；
 *   把 ② 改松 ⇒ 无来源时返回内置数据，等于把假数据重新引回业务链路。
 *   两者都不会抛错、不会红任何既有门禁 —— 只有这里能拦住。
 */
import { describe, it, expect } from 'vitest'
import {
  SIMILAR_RECOMMEND_MAX,
  rankSimilarAsins,
  type SimilarUniverseItem,
} from '@/utils/competitorSimilarity'

/** 造一条候选（只写关心的字段，其余留空 ⇒ 断言更聚焦） */
function item(over: Partial<SimilarUniverseItem> & { asin: string }): SimilarUniverseItem {
  return { ...over }
}

/** 造 n 条同品类候选（用于测条数夹取） */
function manySameCategory(n: number): SimilarUniverseItem[] {
  return Array.from({ length: n }, (_, i) => ({ asin: `B0N${i}`, category: 'Electronics' }))
}

describe('competitorSimilarity · 约束② fail-closed（没有来源就不产出）', () => {
  it('universe 为空 ⇒ 返回 []（绝不内置商品、也不随机/占位填充）', () => {
    const universe: SimilarUniverseItem[] = []
    expect(rankSimilarAsins('B0MAIN', { title: 'Wireless Mouse', category: 'Electronics' }, 12, universe)).toEqual([])
  })

  it('universe 参数整个缺省（不传第 4 参）⇒ 同样返回 []', () => {
    // 走的是形参默认值 `universe = []` 这条路径，与显式传 [] 不是同一行代码
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' })).toEqual([])
  })
})

describe('competitorSimilarity · 约束① 没有兜底分（★ 回归守卫）', () => {
  it('候选有 title 但零相似信号 ⇒ 仍不进结果（老实现的兜底分会把它们塞进来）', () => {
    // ★ 这是本文件最重要的一条：#725 修的就是「假数据 title 一定存在 ⇒ 必然拿分」。
    //   若把 `if (score <= 0) continue` 改回 `if (score <= 0 && !p.title) continue`，
    //   下面两条「类目完全无关、关键词也不命中」的项会各得 1 分并出现在结果里。
    const universe = [
      item({ asin: 'B0TOY', title: 'Plush Bear', category: 'Toys' }),
      item({ asin: 'B0KIT', title: 'Chef Knife', category: 'Kitchen' }),
    ]
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, universe)).toEqual([])
  })

  it('返回的每一条 score 都严格 > 0（不存在 0 分或负分条目）', () => {
    const universe = [
      item({ asin: 'B0HIT', category: 'Electronics' }),
      // ★ B0MISS **带 title**：老实现的兜底分条件正是「score 为 0 且有 title」，
      //   不带 title 的零信号项靠兜底分也进不来 ⇒ 那样写这条用例就抓不到兜底分注入。
      item({ asin: 'B0MISS', category: 'Toys', title: 'Plush Bear' }),
      item({ asin: 'B0WEAK', category: 'Consumer Electronics' }),
    ]
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, universe)
    expect(r.length).toBeGreaterThan(0)
    for (const hit of r) expect(hit.score, `ASIN ${hit.asin}`).toBeGreaterThan(0)
    // 零信号的那条必须被剔除
    expect(r.map((h) => h.asin)).not.toContain('B0MISS')
  })
})

describe('competitorSimilarity · 约束③ 计分口径', () => {
  it('类目完全相同 ⇒ +10', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [item({ asin: 'B0A', category: 'Electronics' })])
    expect(r).toHaveLength(1)
    expect(r[0].score).toBe(10)
  })

  it('类目包含（弱匹配）⇒ +6', () => {
    // 'consumer electronics'.includes('electronics') ⇒ 弱匹配，不是相等
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: 'B0A', category: 'Consumer Electronics' }),
    ])
    expect(r).toHaveLength(1)
    expect(r[0].score).toBe(6)
  })

  it('相等与包含**不叠加**（else-if：完全相同时就是 10，不是 16）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: 'B0A', category: 'Electronics' }),
    ])
    expect(r[0].score).toBe(10)
  })

  it('主品没给类目 ⇒ 类目分不参与（不发散成「全都弱匹配」）', () => {
    const r = rankSimilarAsins('B0MAIN', { keywords: ['mouse'] }, 12, [
      item({ asin: 'B0A', category: 'Anything At All', title: 'Optical Mouse' }),
    ])
    // 只有关键词 'mouse' 命中 ⇒ 4；类目项因 opts.category 为空而整体跳过
    expect(r).toHaveLength(1)
    expect(r[0].score).toBe(4)
  })

  it('每个关键词命中 ⇒ +4（来自 opts.keywords）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['wireless'] }, 12, [
      item({ asin: 'B0A', category: 'Electronics', title: 'Wireless Mouse' }),
    ])
    expect(r[0].score).toBe(10 + 4)
  })

  it('多个关键词分别命中 ⇒ 每个各 +4（可叠加）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['wireless', 'mouse'] }, 12, [
      item({ asin: 'B0A', category: 'Electronics', title: 'Wireless Mouse' }),
    ])
    expect(r[0].score).toBe(10 + 4 + 4)
  })

  it('关键词匹配是**子串**匹配（hay 里包含 term 即算命中）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['mouse'] }, 12, [
      item({ asin: 'B0A', category: 'Electronics', title: 'Gaming Mousepad' }),
    ])
    // 'gaming mousepad'.includes('mouse') ⇒ 命中
    expect(r[0].score).toBe(10 + 4)
  })

  it('opts.title 会分词成关键词，但**只有长度 > 3 的词**才算（边界：3 字符不计、4 字符计入）', () => {
    // ★ 边界守卫：把 `w.length > 3` 放宽成 `>= 3`，'aaa' 就会成为关键词；
    //   因为候选自身标题里含 'aaa' ⇒ 会多拿 4 分（4 → 8）。这条断言就是为它准备的。
    const r = rankSimilarAsins('B0MAIN', { title: 'aaa bbbb' }, 12, [item({ asin: 'B0A', title: 'aaa bbbb' })])
    expect(r).toHaveLength(1)
    expect(r[0].score).toBe(4) // 只有 'bbbb' 计分
  })

  it('候选的 keywords 数组也进 hay（不只是 title）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['ergonomic'] }, 12, [
      item({ asin: 'B0A', category: 'Electronics', title: 'Mouse', keywords: ['Ergonomic'] }),
    ])
    expect(r[0].score).toBe(10 + 4)
  })

  it('候选的 keywords 不是数组时按空处理，不抛错', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['ergonomic'] }, 12, [
      item({ asin: 'B0A', category: 'Electronics', title: 'Mouse', keywords: undefined }),
    ])
    expect(r).toHaveLength(1)
    expect(r[0].score).toBe(10)
  })
})

describe('competitorSimilarity · 候选过滤（谁不能进结果）', () => {
  it('主品自身被排除（ASIN 大小写不敏感）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: 'b0main', category: 'Electronics' }),
    ])
    expect(r).toEqual([])
  })

  it('ASIN 为空的候选被跳过（不能产出无标识的命中）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: '', category: 'Electronics' }),
    ])
    expect(r).toEqual([])
  })

  it('重复 ASIN 只保留**先出现**的那条（大小写归一后判重）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: 'b0a', category: 'Electronics', brand: 'First' }),
      item({ asin: 'B0A', category: 'Electronics', brand: 'Second' }),
    ])
    expect(r).toHaveLength(1)
    expect(r[0].brand).toBe('First')
  })
})

describe('competitorSimilarity · 输出形态', () => {
  it('按 score 降序返回', () => {
    const universe = [
      item({ asin: 'B0LOW', category: 'Electronics' }), // 10
      item({ asin: 'B0HIGH', category: 'Electronics', title: 'wireless' }), // 10 + 4 = 14
      item({ asin: 'B0MID', category: 'Consumer Electronics' }), // 6
    ]
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics', keywords: ['wireless'] }, 12, universe)
    expect(r.map((h) => h.asin)).toEqual(['B0HIGH', 'B0LOW', 'B0MID'])
    expect(r.map((h) => h.score)).toEqual([14, 10, 6])
  })

  it('ASIN 归一成大写，其余展示字段原样透传', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, [
      item({ asin: 'b0a', title: 'T', brand: 'B', main_image: '/i.png', category: 'Electronics' }),
    ])
    expect(r[0]).toEqual({ asin: 'B0A', title: 'T', brand: 'B', main_image: '/i.png', score: 10 })
  })
})

describe('competitorSimilarity · count 夹取到 [0, SIMILAR_RECOMMEND_MAX]', () => {
  it('上限常量是 20（算法侧上限，竞品池自身的上限另由 store 决定）', () => {
    expect(SIMILAR_RECOMMEND_MAX).toBe(20)
  })

  it('count 超上限 ⇒ 截到 20', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 999, manySameCategory(30))
    expect(r).toHaveLength(SIMILAR_RECOMMEND_MAX)
  })

  it('count 为 0 或负数 ⇒ 返回空（不是"最少给一条"）', () => {
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 0, manySameCategory(30))).toEqual([])
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' }, -5, manySameCategory(30))).toEqual([])
  })

  it('count 在区间内 ⇒ 按需返回', () => {
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 7, manySameCategory(30))).toHaveLength(7)
  })

  it('count 缺省 ⇒ 12', () => {
    expect(rankSimilarAsins('B0MAIN', { category: 'Electronics' }, undefined, manySameCategory(30))).toHaveLength(12)
  })

  it('候选不足 count ⇒ 有多少返回多少（不补齐、不重复）', () => {
    const r = rankSimilarAsins('B0MAIN', { category: 'Electronics' }, 12, manySameCategory(3))
    expect(r).toHaveLength(3)
    expect(new Set(r.map((h) => h.asin)).size).toBe(3)
  })
})

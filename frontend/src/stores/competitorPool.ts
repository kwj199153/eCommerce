/**
 * 竞品池（主-竞品绑定关系）状态管理
 *
 * 为「主产品 / 主候选」维护一个对标竞品集合。竞品只是轻量引用（ASIN + 展示快照 + 来源），
 * 价格/评分等完整快照在“使用竞品时”（如竞品对比）实时拉取，不在此全量拷贝。
 *
 * 三种来源：auto(系统自动推荐) / manual(手动输入ASIN) / copied(从别的竞品池复制)。
 *
 * 两种持久化模式：
 *  - ownerType='session'：仅会话内存，切出/离开即弃（模式A）
 *  - ownerType='product'：写入 productLibrary 对应 ProductItem.competitor_asins（模式B，走现有后端JSON列）
 *  - ownerType='candidate'：写入 candidateLibrary 对应 CandidateItem.competitor_asins
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useCandidateLibraryStore } from './candidateLibrary'
import { useProductLibraryStore } from './productLibrary'

// ====== 类型定义 ======

export type CompetitorSource = 'auto' | 'manual' | 'copied'

export type CompetitorOwnerType = 'session' | 'candidate' | 'product'

/** 竞品引用（轻量，仅 ASIN + 展示/来源/启停，不存完整快照） */
export interface CompetitorRef {
  asin: string
  title?: string
  brand?: string
  main_image?: string
  source: CompetitorSource
  note?: string
  /** 是否参与对比；未启用视为保留但不参与本次对比 */
  enabled: boolean
  added_at: string
}

export interface CompetitorPool {
  ownerType: CompetitorOwnerType
  ownerAsin: string
  ownerTitle?: string
  competitors: CompetitorRef[]
}

/** 供推荐器/复制的候选输入（统一竞品字段，避免依赖具体 store 类型） */
export interface CompetitorCandidateInput {
  asin: string
  title?: string
  brand?: string
  main_image?: string
  category?: string
  keywords?: string[]
}

/** 竞品池上限与单次对比上限 */
export const COMPETITOR_POOL_LIMIT = 20
export const COMPARE_SELECT_LIMIT = 5

// ====== Store ======

export const useCompetitorPoolStore = defineStore('competitorPool', () => {
  /** 按 `${ownerType}|${ownerAsin}` 分组的竞品池 */
  const pools = ref<Record<string, CompetitorPool>>({})

  // ====== 内部 helpers ======
  const key = (ownerType: CompetitorOwnerType, ownerAsin: string) => `${ownerType}|${ownerAsin}`

  const getPool = (ownerType: CompetitorOwnerType, ownerAsin: string): CompetitorPool | undefined => {
    return pools.value[key(ownerType, ownerAsin)]
  }

  const ensurePool = (ownerType: CompetitorOwnerType, ownerAsin: string, ownerTitle?: string): CompetitorPool => {
    const k = key(ownerType, ownerAsin)
    if (!pools.value[k]) {
      pools.value[k] = { ownerType, ownerAsin, ownerTitle, competitors: [] }
    } else if (ownerTitle) {
      pools.value[k].ownerTitle = ownerTitle
    }
    return pools.value[k]
  }

  // ====== Getters ======
  /** 某主品的竞品列表（按添加顺序） */
  const poolCompetitors = (ownerType: CompetitorOwnerType, ownerAsin: string): CompetitorRef[] =>
    getPool(ownerType, ownerAsin)?.competitors || []

  /** 某主品的已启用竞品数 */
  const enabledCount = (ownerType: CompetitorOwnerType, ownerAsin: string): number =>
    poolCompetitors(ownerType, ownerAsin).filter(c => c.enabled).length

  // ====== Actions ======

  /** 从本地库/mock 数据源里按关键词自动推荐一批相似 ASIN（来源 auto） */
  async function recommendSimilar(ownerType: CompetitorOwnerType, ownerAsin: string, opts: {
    title?: string
    category?: string
    keywords?: string[]
    count?: number
  }): Promise<CompetitorRef[]> {
    const count = Math.min(opts.count || 12, COMPETITOR_POOL_LIMIT)
    // 汇总真实库（产品库+候选库）作为推荐候选源
    const candStore = useCandidateLibraryStore()
    const prodStore = useProductLibraryStore()
    if (!candStore.items.length && !candStore.isLoading) await candStore.ensureLoaded?.()
    if (!prodStore.items.length && !prodStore.isLoading) await prodStore.fetchItems().catch(() => {})
    const { recommendSimilarAsins } = await import('@/mock/competitorRecommend')
    const found = recommendSimilarAsins(ownerAsin, opts, count, sourceUniverse.value)
    // 存推荐结果进池（默认全部启用，用户可删减）
    const pool = ensurePool(ownerType, ownerAsin, opts.title)
    const existing = new Set(pool.competitors.map(c => c.asin))
    let added = 0
    for (const r of found) {
      if (existing.has(r.asin)) continue
      if (pool.competitors.length + added >= COMPETITOR_POOL_LIMIT) break
      pool.competitors.push({
        asin: r.asin,
        title: r.title,
        brand: r.brand,
        main_image: r.main_image,
        source: 'auto',
        enabled: true,
        added_at: new Date().toISOString(),
      })
      added++
    }
    return pool.competitors.filter(c => c.source === 'auto' && !existing.has(c.asin))
  }

  /** 手动新增一批竞品 ASIN（来源 manual）。若在现有库里命中则补全展示字段 */
  async function addManual(ownerType: CompetitorOwnerType, ownerAsin: string, opts: {
    ownerTitle?: string
    asins: string[]
  }): Promise<number> {
    const pool = ensurePool(ownerType, ownerAsin, opts.ownerTitle)
    const candStore = useCandidateLibraryStore()
    const prodStore = useProductLibraryStore()
    const known = new Map<string, { title?: string; brand?: string; main_image?: string }>()
    // 预加载，避免推荐时库空
    if (!candStore.items.length && !candStore.isLoading) await candStore.ensureLoaded?.()
    if (!prodStore.items.length && !prodStore.isLoading) await prodStore.fetchItems().catch(() => {})
    ;[...candStore.items, ...prodStore.items].forEach(p => {
      if (!known.has(p.asin)) known.set(p.asin, { title: p.title, brand: p.brand, main_image: p.main_image })
    })
    const existing = new Set(pool.competitors.map(c => c.asin))
    let added = 0
    for (const a of opts.asins) {
      const asin = a.trim().toUpperCase()
      if (!asin || existing.has(asin)) continue
      if (pool.competitors.length >= COMPETITOR_POOL_LIMIT) break
      const meta = known.get(asin)
      pool.competitors.push({
        asin,
        title: meta?.title,
        brand: meta?.brand,
        main_image: meta?.main_image,
        source: 'manual',
        enabled: true,
        added_at: new Date().toISOString(),
      })
      existing.add(asin)
      added++
    }
    return added
  }

  /** 从另一个主品的竞品池复制过来（来源 copied） */
  function copyFromPool(targetOwnerType: CompetitorOwnerType, targetAsin: string, opts: {
    targetTitle?: string
    sourceOwnerType: CompetitorOwnerType
    sourceAsin: string
    sourceTitle?: string
  }): number {
    const src = getPool(opts.sourceOwnerType, opts.sourceAsin)
    if (!src) return 0
    const pool = ensurePool(targetOwnerType, targetAsin, opts.targetTitle)
    const existing = new Set(pool.competitors.map(c => c.asin))
    let added = 0
    for (const c of src.competitors) {
      if (existing.has(c.asin)) continue
      if (pool.competitors.length >= COMPETITOR_POOL_LIMIT) break
      pool.competitors.push({
        asin: c.asin,
        title: c.title,
        brand: c.brand,
        main_image: c.main_image,
        source: 'copied',
        enabled: true,
        note: c.note,
        added_at: new Date().toISOString(),
      })
      existing.add(c.asin)
      added++
    }
    return added
  }

  /** 移除一个竞品 */
  function removeRef(ownerType: CompetitorOwnerType, ownerAsin: string, asin: string) {
    const pool = getPool(ownerType, ownerAsin)
    if (pool) pool.competitors = pool.competitors.filter(c => c.asin !== asin)
  }

  /** 批量移除（勾选删除） */
  function removeRefs(ownerType: CompetitorOwnerType, ownerAsin: string, asins: string[]) {
    const rm = new Set(asins)
    const pool = getPool(ownerType, ownerAsin)
    if (pool) pool.competitors = pool.competitors.filter(c => !rm.has(c.asin))
  }

  /** 启停单个竞品 */
  function setEnabled(ownerType: CompetitorOwnerType, ownerAsin: string, asin: string, enabled: boolean) {
    const pool = getPool(ownerType, ownerAsin)
    const c = pool?.competitors.find(x => x.asin === asin)
    if (c) c.enabled = enabled
  }

  /** 清空整个池（不是删池记录，保留主品壳） */
  function clearCompetitors(ownerType: CompetitorOwnerType, ownerAsin: string) {
    const pool = getPool(ownerType, ownerAsin)
    if (pool) pool.competitors = []
  }

  /** 删除整个池（含壳） */
  function dropPool(ownerType: CompetitorOwnerType, ownerAsin: string) {
    delete pools.value[key(ownerType, ownerAsin)]
  }

  /**
   * 模式B持久化：把当前池的已启用竞品 ASIN 写回 productLibrary / candidateLibrary 对应记录的 competitor_asins。
   * 返回写入的竞品 ASIN 数组。无匹配 owner 记录时静默返回 null（调用方决定是否提示）。
   */
  async function persistToOwner(ownerType: 'product' | 'candidate', ownerAsin: string): Promise<string[] | null> {
    const pool = getPool(ownerType, ownerAsin)
    if (!pool) return null
    const asins = pool.competitors.filter(c => c.enabled).map(c => c.asin)
    if (ownerType === 'product') {
      const prodStore = useProductLibraryStore()
      const item = prodStore.items.find(p => p.asin === ownerAsin)
      if (item) {
        await prodStore.updateItem(item.id, { competitor_asins: asins })
        return asins
      }
      return null
    }
    const candStore = useCandidateLibraryStore()
    const item = candStore.items.find(c => c.asin === ownerAsin)
    if (item) {
      await candStore.updateItem(item.id, { competitor_asins: asins } as any)
      return asins
    }
    return null
  }

  /**
   * 将会话池（ownerType='session'）升级为持久主品：以主 ASIN 建池，并把原有竞品复制过去。
   * 用于「入口1 蓝海候选 → 保存至产品库」后，把本次会话维护的竞品一并带过去。
   */
  function adoptSessionToOwner(sessionAsin: string, ownerType: 'product' | 'candidate', ownerAsin: string, ownerTitle?: string): number {
    const sessionPool = getPool('session', sessionAsin)
    if (!sessionPool) return 0
    const pool = ensurePool(ownerType, ownerAsin, ownerTitle)
    const existing = new Set(pool.competitors.map(c => c.asin))
    let copied = 0
    for (const c of sessionPool.competitors) {
      if (existing.has(c.asin)) continue
      if (pool.competitors.length >= COMPETITOR_POOL_LIMIT) break
      pool.competitors.push({ ...c, added_at: new Date().toISOString() })
      existing.add(c.asin)
      copied++
    }
    return copied
  }

  /** 离开对话/会话结束：清掉所有 session 池（模式A数据） */
  function clearSessionPools() {
    Object.keys(pools.value).forEach(k => {
      if (k.startsWith('session|')) delete pools.value[k]
    })
  }

  /** 给推荐器/下拉提供的候选输入视图：从产品库+候选库+现有池收集可作“相似源”的条目 */
  const sourceUniverse = computed<CompetitorCandidateInput[]>(() => {
    const candStore = useCandidateLibraryStore()
    const prodStore = useProductLibraryStore()
    const seen = new Map<string, CompetitorCandidateInput>()
    ;[...prodStore.items, ...candStore.items].forEach(p => {
      if (!seen.has(p.asin)) {
        seen.set(p.asin, {
          asin: p.asin,
          title: p.title,
          brand: p.brand,
          main_image: p.main_image,
          category: p.category,
          keywords: p.keywords,
        })
      }
    })
    return Array.from(seen.values())
  })

  return {
    pools,
    // getters/fns
    getPool,
    poolCompetitors,
    enabledCount,
    sourceUniverse,
    // actions
    recommendSimilar,
    addManual,
    copyFromPool,
    removeRef,
    removeRefs,
    setEnabled,
    clearCompetitors,
    dropPool,
    persistToOwner,
    adoptSessionToOwner,
    clearSessionPools,
  }
})

/**
 * 候选选品库（草稿池）状态管理
 *
 * 管理选品分析师产出的候选商品：CRUD、搜索、分组、评审状态流转、评审通过迁移到产品库。
 * 数据源：后端 PostgreSQL（/api/v1/candidates），失败回退 mock 供离线演示。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchCandidates,
  fetchCandidateGroups,
  createCandidate,
  updateCandidate,
  reviewCandidate,
  approveCandidate,
  deleteCandidate,
  batchDeleteCandidates,
  createCandidateGroup,
  updateCandidateGroup,
  deleteCandidateGroup,
} from '@/api/candidates'

// ====== 类型定义 ======

/** 评审状态机：待评审 / 评审中 / 已通过 / 已淘汰 */
export type ReviewStatus = 'pending' | 'under_review' | 'approved' | 'rejected'

export interface CandidateItem {
  id: string
  asin: string
  sku: string
  title: string
  brand: string
  category: string
  sub_category: string

  // 价格站点
  price: number
  currency: string
  site?: string

  // 市场数据
  estimated_monthly_sales: number
  review_count: number
  rating: number
  bsr: number | null
  bsr_category?: string
  listed_date?: string

  // 蓝海评分核心
  roi_estimated: number
  margin: number
  blue_ocean_score: number
  overall_listing_score?: number

  // 关键词 / 竞品 / 卖点
  keywords?: string[]
  competitor_asins?: string[]
  selling_points?: string

  // 图片
  main_image: string
  images?: string[]

  // 来源
  source: string

  // 评审状态机
  review_status: ReviewStatus
  review_notes: string
  reviewed_at?: string | null
  reviewed_by?: string | null

  // 竞品监控回填快照
  monitor_data?: Record<string, any> | null
  last_monitored_at?: string | null

  // 元数据
  shop_id: string
  tags: string[]
  notes: string
  groups: string[]
  created_at: string
  updated_at: string
}

export interface CandidateGroup {
  id: string
  name: string
  color: string
  createdAt: string
  updatedAt: string
}

// ====== 评审状态配置 ======

export const REVIEW_STATUS_MAP: Record<ReviewStatus, { label: string; color: string }> = {
  pending: { label: '草稿', color: 'default' },
  under_review: { label: '评审中', color: 'blue' },
  approved: { label: '已通过', color: 'green' },
  rejected: { label: '已淘汰', color: 'red' },
}

export const GROUP_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f',
  '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16',
]

// ====== Mock 数据（离线兜底用） ======

const MOCK_CANDIDATES: CandidateItem[] = [
  {
    id: 'cand-000',
    asin: 'B0CAND0001',
    sku: 'SKU-CAND-000',
    title: 'Sunset Projection Alarm Clock with Sunrise Simulation & White Noise',
    brand: 'SunRise',
    category: 'home',
    sub_category: '智能家居',
    price: 32.99,
    currency: 'USD',
    site: 'Amazon US',
    estimated_monthly_sales: 4200,
    review_count: 856,
    rating: 4.4,
    bsr: 2345,
    bsr_category: 'Home & Kitchen > Alarm Clocks',
    listed_date: '2025-11-20',
    roi_estimated: 142,
    margin: 58,
    blue_ocean_score: 86,
    overall_listing_score: 71,
    keywords: ['sunrise alarm clock', 'wake up light', 'white noise machine'],
    competitor_asins: ['B0COMP0001', 'B0COMP0002'],
    selling_points: '日出模拟自然唤醒 | 白噪音助眠 | 星空投影',
    main_image: '/mock/products/B0CAND0001.png',
    images: [],
    source: 'blue_ocean',
    review_status: 'pending',
    review_notes: '',
    reviewed_at: null,
    reviewed_by: null,
    monitor_data: null,
    last_monitored_at: null,
    shop_id: 'shop-1',
    tags: ['蓝海挖掘', '评分:86'],
    notes: '高潜力蓝海，竞争度低',
    groups: [],
    created_at: '2026-09-05T09:00:00Z',
    updated_at: '2026-09-05T09:00:00Z',
  },
]

// ====== Store ======

export const useCandidateLibraryStore = defineStore('candidateLibrary', () => {
  const items = ref<CandidateItem[]>([])
  const isLoading = ref(false)
  const searchQuery = ref('')
  // filter 默认值改为 undefined；占位符文本用 'all'/'all_status'/'all_category' 之类的字符串在 a-select option 里
  const filterReviewStatus = ref<string | undefined>(undefined)
  const filterCategory = ref<string | undefined>(undefined)
  const sortBy = ref<string>('updated_at')

  const groups = ref<CandidateGroup[]>([])
  const currentGroupId = ref<string | null>(null)

  // ====== Getters ======

  const filteredItems = computed(() => {
    let result = items.value

    if (currentGroupId.value) {
      if (currentGroupId.value === '__ungrouped__') {
        result = result.filter(item => !item.groups || item.groups.length === 0)
      } else {
        result = result.filter(item => item.groups?.includes(currentGroupId.value!))
      }
    }
    if (filterReviewStatus.value && filterReviewStatus.value !== 'all') {
      result = result.filter(item => item.review_status === filterReviewStatus.value)
    }
    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.title.toLowerCase().includes(q) ||
        item.asin.toLowerCase().includes(q) ||
        item.brand.toLowerCase().includes(q) ||
        item.tags.some(t => t.toLowerCase().includes(q))
      )
    }

    result = [...result].sort((a, b) => {
      switch (sortBy.value) {
        case 'price': return b.price - a.price
        case 'sales': return b.estimated_monthly_sales - a.estimated_monthly_sales
        case 'rating': return b.rating - a.rating
        case 'blue_ocean_score': return b.blue_ocean_score - a.blue_ocean_score
        case 'roi': return b.roi_estimated - a.roi_estimated
        default:
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      }
    })
    return result
  })

  const totalCount = computed(() => items.value.length)
  const pendingCount = computed(() => items.value.filter(i => i.review_status === 'pending').length)
  const underReviewCount = computed(() => items.value.filter(i => i.review_status === 'under_review').length)
  const approvedCount = computed(() => items.value.filter(i => i.review_status === 'approved').length)
  const rejectedCount = computed(() => items.value.filter(i => i.review_status === 'rejected').length)

  const groupProductCount = computed(() => {
    const map: Record<string, number> = {}
    groups.value.forEach(g => {
      map[g.id] = items.value.filter(p => p.groups?.includes(g.id)).length
    })
    return map
  })

  // ====== Actions ======

  async function fetchItems() {
    isLoading.value = true
    try {
      const res = await fetchCandidates()
      items.value = res.items || []
      try {
        const gres = await fetchCandidateGroups()
        groups.value = gres.groups || []
      } catch (e) {
        console.warn('[CandidateLibrary] 分组拉取失败', e)
      }
    } catch (e) {
      console.warn('[CandidateLibrary] 拉取候选失败，回退 Mock 数据', e)
      items.value = [...MOCK_CANDIDATES]
    } finally {
      isLoading.value = false
    }
  }

  let ensured = false
  /** 确保至少拉取过一次（供其它库回流写入选品库前查重，避免重复写入） */
  async function ensureLoaded() {
    if (ensured || items.value.length) return
    ensured = true
    try { await fetchItems() } catch (e) { /* 忽略 */ }
  }

  async function addItem(data: Omit<CandidateItem, 'id' | 'created_at' | 'updated_at'>): Promise<CandidateItem> {
    try {
      const created = await createCandidate(data as any)
      items.value.unshift(created)
      return created
    } catch (e) {
      console.warn('[CandidateLibrary] 新增候选失败，本地兜底', e)
      const newItem: CandidateItem = {
        ...data,
        id: `cand-${Date.now()}`,
        groups: data.groups || [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      items.value.unshift(newItem)
      return newItem
    }
  }

  async function updateItem(id: string, data: Partial<Omit<CandidateItem, 'id' | 'created_at'>>): Promise<void> {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = { ...items.value[index], ...data, updated_at: new Date().toISOString() }
    }
    try {
      await updateCandidate(id, data as any)
    } catch (e) {
      console.warn('[CandidateLibrary] 更新候选失败', e)
    }
  }

  /** 某 ASIN 是否已在选品库（监控页据此显示「前往选品库」） */
  function isAsinInCandidate(asin: string): boolean {
    return items.value.some(i => i.asin === asin)
  }

  /** 从竞品监控快照写入选品库（链路3 反向回流，用于新品可行性复盘）。纯前端 mock；返回新候选 */
  async function addFromMonitorSnapshot(snap: {
    asin: string
    title: string
    brand?: string
    main_image?: string
    price?: number
    rating?: number
    review_count?: number
    bsr?: number | null
    bsr_category?: string
    est_monthly_sales?: number
  }): Promise<CandidateItem | null> {
    if (isAsinInCandidate(snap.asin)) {
      return items.value.find(i => i.asin === snap.asin) || null
    }
    try {
      const created = await addItem({
        asin: snap.asin,
        sku: `SKU-CAND-${snap.asin}`,
        title: snap.title || snap.asin,
        brand: snap.brand || '',
        category: 'other',
        sub_category: '',
        price: snap.price ?? 0,
        currency: 'USD',
        estimated_monthly_sales: snap.est_monthly_sales ?? 0,
        review_count: snap.review_count ?? 0,
        rating: snap.rating ?? 0,
        bsr: snap.bsr ?? null,
        bsr_category: snap.bsr_category || '',
        roi_estimated: 0,
        margin: 0,
        blue_ocean_score: 0,
        overall_listing_score: 0,
        main_image: snap.main_image || '',
        source: 'monitor_page',
        review_status: 'pending',
        review_notes: '从竞品监控回流，待市场可行性评估',
        reviewed_at: null,
        reviewed_by: null,
        monitor_data: null,
        last_monitored_at: null,
        shop_id: '',
        tags: ['竞品回流'],
        notes: '发现于竞品监控，评估是否拓展为新 SKU',
        groups: [],
      })
      return created
    } catch (e) {
      console.warn('[CandidateLibrary] 从监控回流候选失败', e)
      return null
    }
  }

  /** 评审状态流转 */
  async function setReviewStatus(id: string, reviewStatus: ReviewStatus, reviewNotes?: string): Promise<void> {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = {
        ...items.value[index],
        review_status: reviewStatus,
        review_notes: reviewNotes ?? items.value[index].review_notes,
        reviewed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
    }
    try {
      await reviewCandidate(id, { review_status: reviewStatus, review_notes: reviewNotes })
    } catch (e) {
      console.warn('[CandidateLibrary] 评审状态更新失败', e)
    }
  }

  /**
   * 评审通过：复制到自有产品库（草稿待完善），候选本身保留为「已通过评估基线」。
   * 语义：选品库=评估基线，自有产品库=上架物料基线，双库并存；不删除候选。
   */
  async function approve(id: string): Promise<void> {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = {
        ...items.value[index],
        review_status: 'approved',
        reviewed_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
    }
    try {
      await approveCandidate(id)
    } catch (e) {
      console.warn('[CandidateLibrary] 评审通过（保留基线）失败', e)
      throw e
    }
  }

  async function deleteItem(id: string): Promise<void> {
    items.value = items.value.filter(i => i.id !== id)
    try {
      await deleteCandidate(id)
    } catch (e) {
      console.warn('[CandidateLibrary] 删除候选失败', e)
    }
  }

  async function batchDelete(ids: string[]): Promise<void> {
    items.value = items.value.filter(i => !ids.includes(i.id))
    try {
      await batchDeleteCandidates(ids)
    } catch (e) {
      console.warn('[CandidateLibrary] 批量删除失败', e)
    }
  }

  /**
   * 批量导入候选（JSON / CSV / TXT）
   * JSON：数组，每项含 asin/title/price/estimated_monthly_sales/blue_ocean_score 等
   * CSV：header 含 asin,title 两列（可选 price,sales,score）
   * TXT：每行 "ASIN /// 标题"
   */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const text = await file.text()
    const imported: Omit<CandidateItem, 'id' | 'created_at' | 'updated_at'>[] = []
    const errors: string[] = []
    const ext = file.name.split('.').pop()?.toLowerCase()

    try {
      if (ext === 'json') {
        const json = JSON.parse(text)
        const arr = Array.isArray(json) ? json : [json]
        for (const row of arr) {
          if (row.asin && row.title) {
            imported.push({
              asin: String(row.asin),
              sku: `SKU-CAND-${row.asin}`,
              title: String(row.title),
              brand: row.brand || '',
              category: row.category || 'other',
              sub_category: row.sub_category || '',
              price: Number(row.price) || 0,
              currency: 'USD',
              estimated_monthly_sales: Number(row.estimated_monthly_sales) || 0,
              review_count: Number(row.review_count) || 0,
              rating: Number(row.rating) || 0,
              bsr: row.bsr ?? null,
              roi_estimated: Number(row.roi_estimated) || 0,
              margin: Number(row.margin) || 0,
              blue_ocean_score: Number(row.blue_ocean_score) || 0,
              main_image: row.main_image || '',
              source: 'import',
              review_status: 'pending',
              review_notes: '',
              shop_id: '',
              tags: ['导入'],
              notes: row.notes || '',
              groups: [],
            })
          } else {
            errors.push(`缺少 asin 或 title 字段: ${JSON.stringify(row).slice(0, 80)}`)
          }
        }
      } else if (ext === 'csv') {
        const lines = text.split('\n').filter(l => l.trim())
        const startIdx = lines[0].toLowerCase().includes('asin') ? 1 : 0
        for (let i = startIdx; i < lines.length; i++) {
          const cols = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''))
          if (cols.length >= 2 && cols[0] && cols[1]) {
            imported.push({
              asin: cols[0],
              sku: `SKU-CAND-${cols[0]}`,
              title: cols[1],
              brand: '',
              category: cols[2] || 'other',
              sub_category: '',
              price: Number(cols[3]) || 0,
              currency: 'USD',
              estimated_monthly_sales: Number(cols[4]) || 0,
              review_count: 0,
              rating: 0,
              bsr: null,
              roi_estimated: Number(cols[5]) || 0,
              margin: 0,
              blue_ocean_score: Number(cols[6]) || 0,
              main_image: '',
              source: 'import',
              review_status: 'pending',
              review_notes: '',
              shop_id: '',
              tags: ['导入'],
              notes: '',
              groups: [],
            })
          } else if (lines[i].trim()) {
            errors.push(`第 ${i + 1} 行格式错误`)
          }
        }
      } else if (ext === 'txt') {
        const lines = text.split('\n').filter(l => l.trim())
        for (const line of lines) {
          let asin = '', title = ''
          if (line.includes('///')) {
            const parts = line.split('///')
            asin = parts[0].trim()
            title = parts.slice(1).join('///').trim()
          } else if (line.includes('|')) {
            const parts = line.split('|')
            asin = parts[0].trim()
            title = parts.slice(1).join('|').trim()
          }
          if (asin && title) {
            imported.push({
              asin,
              sku: `SKU-CAND-${asin}`,
              title,
              brand: '',
              category: 'other',
              sub_category: '',
              price: 0,
              currency: 'USD',
              estimated_monthly_sales: 0,
              review_count: 0,
              rating: 0,
              bsr: null,
              roi_estimated: 0,
              margin: 0,
              blue_ocean_score: 0,
              main_image: '',
              source: 'import',
              review_status: 'pending',
              review_notes: '',
              shop_id: '',
              tags: ['导入'],
              notes: '',
              groups: [],
            })
          } else if (line.trim()) {
            errors.push(`无法解析: ${line.slice(0, 60)}`)
          }
        }
      } else {
        errors.push(`不支持的文件格式: .${ext}`)
      }

      for (const item of imported) {
        await addItem(item)
      }

      return { success: imported.length, failed: errors.length, errors }
    } catch (e) {
      return { success: 0, failed: 1, errors: [`文件解析失败: ${e instanceof Error ? e.message : String(e)}`] }
    }
  }

  // ====== 分组 Actions ======

  async function createGroup(input: { name: string; color?: string }): Promise<CandidateGroup> {
    try {
      const created = await createCandidateGroup(input)
      groups.value.push(created)
      return created
    } catch (e) {
      console.warn('[CandidateLibrary] 创建分组失败，本地兜底', e)
      const group: CandidateGroup = {
        id: `cgroup-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        name: input.name.trim(),
        color: input.color || GROUP_COLORS[groups.value.length % GROUP_COLORS.length],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }
      groups.value.push(group)
      return group
    }
  }

  function renameGroup(id: string, name: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) {
      g.name = name.trim()
      g.updatedAt = new Date().toISOString()
      updateCandidateGroup(id, { name: g.name }).catch(e => console.warn('[CandidateLibrary] 重命名分组失败', e))
    }
  }

  function setGroupColor(id: string, color: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) {
      g.color = color
      g.updatedAt = new Date().toISOString()
      updateCandidateGroup(id, { color }).catch(e => console.warn('[CandidateLibrary] 改分组颜色失败', e))
    }
  }

  function deleteGroup(id: string) {
    groups.value = groups.value.filter(g => g.id !== id)
    items.value.forEach(p => {
      if (p.groups) p.groups = p.groups.filter(gid => gid !== id)
    })
    if (currentGroupId.value === id) currentGroupId.value = null
    deleteCandidateGroup(id).catch(e => console.warn('[CandidateLibrary] 删除分组失败', e))
  }

  function selectGroup(id: string | null) {
    currentGroupId.value = id
  }

  /** 当前是否启用了任何过滤条件（用于显示"清空过滤"按钮） */
  const hasActiveFilters = computed(() =>
    Boolean(searchQuery.value.trim()) ||
    (filterReviewStatus.value && filterReviewStatus.value !== 'all') ||
    (filterCategory.value && filterCategory.value !== 'all') ||
    currentGroupId.value !== null
  )

  /** 当前已应用的过滤条件数（用于显示 chip 计数） */
  const activeFilterCount = computed(() => {
    let n = 0
    if (searchQuery.value.trim()) n++
    if (filterReviewStatus.value && filterReviewStatus.value !== 'all') n++
    if (filterCategory.value && filterCategory.value !== 'all') n++
    if (currentGroupId.value !== null) n++
    return n
  })

  /** 一键清空所有过滤条件（分组 + 评审状态 + 分类 + 搜索） */
  function clearAllFilters() {
    searchQuery.value = ''
    filterReviewStatus.value = undefined
    filterCategory.value = undefined
    currentGroupId.value = null
  }

  return {
    // State
    items,
    isLoading,
    searchQuery,
    filterReviewStatus,
    filterCategory,
    sortBy,
    groups,
    currentGroupId,

    // Getters
    filteredItems,
    totalCount,
    pendingCount,
    underReviewCount,
    approvedCount,
    rejectedCount,
    groupProductCount,
    hasActiveFilters,
    activeFilterCount,

    // Actions
    fetchItems,
    ensureLoaded,
    addItem,
    updateItem,
    isAsinInCandidate,
    addFromMonitorSnapshot,
    setReviewStatus,
    approve,
    deleteItem,
    batchDelete,
    parseAndImport,
    createGroup,
    renameGroup,
    setGroupColor,
    deleteGroup,
    selectGroup,
    clearAllFilters,
  }
})

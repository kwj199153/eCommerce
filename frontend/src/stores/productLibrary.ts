/**
 * 产品库状态管理（SPU + SKU 分表架构）
 *
 * SPU（Standard Product Unit，主产品）：无 ASIN、不可售，聚合公共属性 + 公共文案模板。
 * SKU（Stock Keeping Unit，具体规格）：独立 ASIN、价格、库存、BSR/评分，Listing 可覆盖。
 *
 * store 内部用 spus + skus 两个 ref 管理，treeItems 计算属性输出「SPU 挂 SKU children」的树形结构。
 * 为兼容产品库表格 / Listing 加载器 / Listing 编辑器的展示，统一映射为 ProductItem 树行类型：
 *   - SPU 行：is_spu=true、asin=''、price=0、带 children（SKU 行）
 *   - SKU 行：is_spu=false、spu_id 指向主产品、spec_value 规格值
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchSpus,
  fetchSkus,
  createSpu,
  updateSpu,
  deleteSpu,
  createSku,
  updateSku,
  deleteSku,
  updateSkuListing,
  fetchProductGroups,
  createProductGroup,
  updateProductGroup,
  deleteProductGroup,
  moveProductGroup,
} from '@/api/products'

// ====== 类型定义 ======

/** 公共基础文案（SPU 共享底稿，SKU 继承后可单独改，支持批量同步） */
export interface SpuCommon {
  brand?: string
  category?: string
  keywords?: string[]           // 核心关键词（SKU 继承为种子）
  selling_points?: string       // 核心卖点（` | ` 分隔）
  bullets?: Array<{ title: string; content: string }>  // 五点底稿模板
  a_plus?: any                  // A+ 底稿模板
}

/** 兼容旧类型别名：ParentContent = SpuCommon */
export type ParentContent = SpuCommon

/** SPU（主产品） */
export interface Spu {
  id: string
  title: string
  brand: string
  category: string
  sub_category: string
  spu_theme: string | null       // Color / Size / Style / Package / Color-Size
  keywords?: string[]
  selling_points?: string
  description?: string
  main_image: string
  images: string[]
  spu_common?: SpuCommon
  shop_id: string
  tags: string[]
  notes: string
  status: 'active' | 'archived' | 'draft'
  groups: string[]
  created_at: string
  updated_at: string
}

/** SKU（具体规格） */
export interface Sku {
  id: string
  spu_id: string
  spec_value?: string | null    // 规格值（如「红色」「M」）
  asin: string
  sku_code: string
  price: number
  cost: number
  currency: string
  site?: string
  fba_stock: number
  fbm_stock: number
  fulfillment_type: 'FBA' | 'FBM'
  bsr: number | null
  rating: number
  review_count: number
  daily_sales_avg: number
  roi: number
  margin: number
  listing_status: 'active' | 'inactive' | 'suppressed' | 'pending' | 'draft' | 'ready'
  generated_title?: string
  generated_bullets?: Array<{ title: string; content: string }>
  generated_a_plus?: any
  seo_score?: number
  generated_at?: string
  listing_version?: number
  listing_history?: Array<{ version: number; title: string; bullets: Array<{ title: string; content: string }>; updated_at: string }>
  has_a_plus?: boolean
  has_video?: boolean
  rating_breakdown?: { [star: string]: number }
  tags: string[]
  notes: string
  status: 'active' | 'archived' | 'draft'
  created_at: string
  updated_at: string
}

/**
 * 树行展示类型（SPU 行 / SKU 行统一）。
 * 兼容产品库表格、Listing 加载器、Listing 编辑器的展示字段。
 */
export interface ProductItem {
  id: string
  is_spu: boolean                // 是否为 SPU（主产品）行
  spu_id?: string | null         // SKU 行指向的主产品 id
  spec_value?: string | null     // SKU 行的规格值
  spu_theme?: string | null      // 规格主题（SPU 行 / SKU 行都带，便于展示）
  children?: ProductItem[]       // SPU 行挂的 SKU 子行

  asin: string
  sku: string                    // 兼容别名 = sku_code
  sku_code?: string
  title: string
  brand: string
  category: string
  sub_category: string
  price: number
  cost: number
  currency: string
  site?: string
  keywords?: string[]
  competitor_asins?: string[]
  selling_points?: string
  description?: string
  listing_status: 'active' | 'inactive' | 'suppressed' | 'pending' | 'draft' | 'ready'
  bsr: number | null
  rating: number
  review_count: number
  generated_title?: string
  generated_bullets?: Array<{ title: string; content: string }>
  generated_a_plus?: any
  seo_score?: number
  generated_at?: string
  listing_version?: number
  listing_history?: Array<{ version: number; title: string; bullets: Array<{ title: string; content: string }>; updated_at: string }>
  main_image: string
  images: string[]
  has_a_plus?: boolean
  has_video?: boolean
  rating_breakdown?: { [star: string]: number }
  spu_common?: SpuCommon
  fba_stock: number
  fbm_stock: number
  fulfillment_type: 'FBA' | 'FBM'
  daily_sales_avg: number
  roi: number
  margin: number
  shop_id: string
  tags: string[]
  notes: string
  status: 'active' | 'archived' | 'draft'
  groups: string[]
  created_at: string
  updated_at: string
}

export interface ProductGroup {
  id: string
  name: string
  color: string
  createdAt: string
  updatedAt: string
}

export interface VariationInfo {
  asin: string
  size?: string
  color?: string
  price: number
  stock: number
}

export interface ProductCategory {
  key: string
  label: string
  icon: string
}

// ====== 内置分类 ======

export const PRODUCT_CATEGORIES: ProductCategory[] = [
  { key: 'electronics', label: '电子产品', icon: '💻' },
  { key: 'home', label: '家居厨卫', icon: '🏠' },
  { key: 'beauty', label: '美妆个护', icon: '💄' },
  { key: 'sports', label: '运动户外', icon: '⚽' },
  { key: 'clothing', label: '服装鞋帽', icon: '👕' },
  { key: 'toys', label: '玩具母婴', icon: '🧸' },
  { key: 'automotive', label: '汽车用品', icon: '🚗' },
  { key: 'other', label: '其他', icon: '📦' },
]

/** 预置分组标签颜色 */
export const GROUP_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f',
  '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16',
]

// ====== Mock 数据（离线兜底用，SPU + SKU 结构） ======

const MOCK_SPUS: Spu[] = [
  {
    id: 'spu-000',
    title: 'Portable Mini Humidifier for Bedroom Desk USB Cool Mist',
    brand: 'CoolMist',
    category: 'home',
    sub_category: '加湿器',
    spu_theme: null,
    keywords: ['mini humidifier', 'usb humidifier', 'bedroom humidifier'],
    selling_points: '500ml 大容量水箱 | 双雾量模式 | USB 供电 | 自动断电保护',
    description: 'Portable mini humidifier for bedroom and desk.',
    main_image: '/mock/products/B0CXXXX001.png',
    images: ['/mock/products/B0CXXXX001.png'],
    spu_common: { brand: 'CoolMist', category: 'home', keywords: ['mini humidifier'], selling_points: '500ml 大容量水箱', bullets: [], a_plus: null },
    shop_id: 'shop-1',
    tags: ['蓝海', '新品'],
    notes: '从蓝海挖掘保存的草稿',
    status: 'draft',
    groups: [],
    created_at: '2026-09-01T07:00:00Z',
    updated_at: '2026-09-01T07:00:00Z',
  },
  {
    id: 'spu-001',
    title: '无线蓝牙耳机 降噪头戴式 长续航40小时 HiFi音质',
    brand: 'SoundMax',
    category: 'electronics',
    sub_category: '耳机/音响',
    spu_theme: 'Color',
    keywords: ['wireless headphone', 'noise cancelling', 'over ear headphone'],
    selling_points: '主动降噪 -35dB | 蓝牙 5.3 | 40 小时续航 | HiFi 音质',
    description: 'ANC wireless headphones with 40H battery.',
    main_image: '/mock/products/B0DGXRLVLC.png',
    images: ['/mock/products/B0DGXRLVLC.png', '/mock/products/B0DGXRLVLC.png'],
    spu_common: { brand: 'SoundMax', category: 'electronics', keywords: ['wireless headphone'], selling_points: '主动降噪 -35dB', bullets: [], a_plus: null },
    shop_id: 'shop-1',
    tags: ['热销', 'Prime'],
    notes: 'Q4 主推款',
    status: 'active',
    groups: [],
    created_at: '2026-07-15T10:00:00Z',
    updated_at: '2026-08-29T10:00:00Z',
  },
]

const MOCK_SKUS: Sku[] = [
  {
    id: 'sku-000-0', spu_id: 'spu-000', spec_value: null, asin: 'B0CXXXX001',
    sku_code: 'SKU-BL-000', price: 24.99, cost: 14.48, currency: 'USD',
    fba_stock: 0, fbm_stock: 0, fulfillment_type: 'FBA',
    bsr: null, rating: 0, review_count: 0, daily_sales_avg: 0, roi: 0, margin: 26,
    listing_status: 'draft', seo_score: 68, listing_version: 1,
    has_a_plus: false, has_video: false,
    tags: ['蓝海', '新品'], notes: '从蓝海挖掘保存的草稿，待 Listing 优化',
    status: 'draft', created_at: '2026-09-01T07:00:00Z', updated_at: '2026-09-01T07:00:00Z',
  },
  {
    id: 'sku-001-0', spu_id: 'spu-001', spec_value: '黑色', asin: 'B0DGXRLVLC',
    sku_code: 'SKU-WL-001-BK', price: 49.99, cost: 18.5, currency: 'USD',
    fba_stock: 450, fbm_stock: 0, fulfillment_type: 'FBA',
    bsr: 1234, rating: 4.6, review_count: 2890, daily_sales_avg: 45, roi: 170, margin: 63,
    listing_status: 'active', seo_score: 86, listing_version: 1,
    has_a_plus: true, has_video: true,
    tags: ['热销', 'Prime'], notes: 'Q4 主推款',
    status: 'active', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-08-29T10:00:00Z',
  },
  {
    id: 'sku-001-1', spu_id: 'spu-001', spec_value: '白色', asin: 'B0DGXRLVLD',
    sku_code: 'SKU-WL-001-WH', price: 49.99, cost: 18.5, currency: 'USD',
    fba_stock: 320, fbm_stock: 0, fulfillment_type: 'FBA',
    bsr: 2100, rating: 4.5, review_count: 1560, daily_sales_avg: 32, roi: 170, margin: 63,
    listing_status: 'active', seo_score: 82, listing_version: 1,
    has_a_plus: true, has_video: true,
    tags: ['热销'], notes: '白色款',
    status: 'active', created_at: '2026-07-15T10:00:00Z', updated_at: '2026-08-29T10:00:00Z',
  },
]

// ====== Store ======

export const useProductLibraryStore = defineStore('productLibrary', () => {
  // ====== State ======
  const spus = ref<Spu[]>([])
  const skus = ref<Sku[]>([])
  const isLoading = ref(false)
  const searchQuery = ref('')
  const filterCategory = ref<string | undefined>(undefined)
  const filterStatus = ref<string | undefined>(undefined)
  const sortBy = ref<string>('updated_at')

  const groups = ref<ProductGroup[]>([])
  const currentGroupId = ref<string | null>(null)

  // ====== 转换工具：SPU/SKU → 树行 ProductItem ======

  function spuToRow(spu: Spu, children: ProductItem[] = []): ProductItem {
    return {
      id: spu.id,
      is_spu: true,
      spu_id: null,
      spec_value: null,
      spu_theme: spu.spu_theme,
      children,
      asin: '',
      sku: '',
      sku_code: '',
      title: spu.title,
      brand: spu.brand,
      category: spu.category,
      sub_category: spu.sub_category,
      price: 0,
      cost: 0,
      currency: 'USD',
      keywords: spu.keywords,
      selling_points: spu.selling_points,
      description: spu.description,
      listing_status: 'draft',
      bsr: null,
      rating: 0,
      review_count: 0,
      main_image: spu.main_image,
      images: spu.images,
      spu_common: spu.spu_common,
      fba_stock: 0,
      fbm_stock: 0,
      fulfillment_type: 'FBA',
      daily_sales_avg: 0,
      roi: 0,
      margin: 0,
      shop_id: spu.shop_id,
      tags: spu.tags,
      notes: spu.notes,
      status: spu.status,
      groups: spu.groups,
      created_at: spu.created_at,
      updated_at: spu.updated_at,
    }
  }

  function skuToRow(sku: Sku, spu?: Spu): ProductItem {
    return {
      id: sku.id,
      is_spu: false,
      spu_id: sku.spu_id,
      spec_value: sku.spec_value ?? null,
      spu_theme: spu?.spu_theme ?? null,
      asin: sku.asin,
      sku: sku.sku_code,
      sku_code: sku.sku_code,
      title: spu ? `${spu.title}${sku.spec_value ? ` - ${sku.spec_value}` : ''}` : sku.asin,
      brand: spu?.brand ?? '',
      category: spu?.category ?? 'other',
      sub_category: spu?.sub_category ?? '',
      price: sku.price,
      cost: sku.cost,
      currency: sku.currency,
      site: sku.site,
      selling_points: spu?.selling_points,
      description: spu?.description,
      listing_status: sku.listing_status,
      bsr: sku.bsr,
      rating: sku.rating,
      review_count: sku.review_count,
      generated_title: sku.generated_title,
      generated_bullets: sku.generated_bullets,
      generated_a_plus: sku.generated_a_plus,
      seo_score: sku.seo_score,
      generated_at: sku.generated_at,
      listing_version: sku.listing_version,
      listing_history: sku.listing_history,
      main_image: spu?.main_image ?? '',
      images: spu?.images ?? [],
      has_a_plus: sku.has_a_plus,
      has_video: sku.has_video,
      rating_breakdown: sku.rating_breakdown,
      fba_stock: sku.fba_stock,
      fbm_stock: sku.fbm_stock,
      fulfillment_type: sku.fulfillment_type,
      daily_sales_avg: sku.daily_sales_avg,
      roi: sku.roi,
      margin: sku.margin,
      shop_id: spu?.shop_id ?? '',
      tags: sku.tags,
      notes: sku.notes,
      status: sku.status,
      groups: spu?.groups ?? [],
      created_at: sku.created_at,
      updated_at: sku.updated_at,
    }
  }

  // ====== Getters ======

  /** 平铺的 SKU 行（用于统计/搜索/Listing 加载） */
  const allSkuRows = computed<ProductItem[]>(() =>
    skus.value.map(s => skuToRow(s, spus.value.find(p => p.id === s.spu_id)))
  )

  /**
   * 树形列表：SPU 行挂 SKU children。
   * 单品（SKU 数 == 1）时，SPU 行不挂 children（树形表格只渲染 SPU 这一行），
   * SPU 行单元格走「只读投影」展示唯一 SKU 的数据，避免重复渲染两行一样的信息。
   */
  const treeItems = computed<Array<ProductItem & { children?: ProductItem[] }>>(() => {
    return spus.value.map(spu => {
      const children = skus.value.filter(s => s.spu_id === spu.id)
      if (children.length !== 1) return spuToRow(spu, children.map(s => skuToRow(s, spu)))
      // 单品：不挂 children，让 SPU 行成为叶子节点（前端投影展示 SKU 数据）
      return spuToRow(spu)
    })
  })

  /**
   * 平铺列表：只展示 SPU（产品款）行，不挂 SKU children。
   * 多变体 SPU 在此视图下也只显示一行（汇总），SKU 规格点进详情看。
   * 单品 SPU 行为叶子（前端投影唯一 SKU 数据）。
   */
  const flatSpuRows = computed<Array<ProductItem & { children?: ProductItem[] }>>(() => {
    return spus.value.map(spu => spuToRow(spu))
  })

  /** 过滤 + 排序后的 SKU 行（用于统计/搜索） */
  const filteredItems = computed(() => {
    let result = allSkuRows.value
    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    if (filterStatus.value && filterStatus.value !== 'all') {
      result = result.filter(item => item.status === filterStatus.value)
    }
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.title.toLowerCase().includes(q) ||
        item.asin.toLowerCase().includes(q) ||
        item.sku.toLowerCase().includes(q) ||
        item.brand.toLowerCase().includes(q) ||
        item.tags.some(t => t.toLowerCase().includes(q))
      )
    }
    result = [...result].sort((a, b) => {
      switch (sortBy.value) {
        case 'price': return b.price - a.price
        case 'price_asc': return a.price - b.price
        case 'sales': return b.daily_sales_avg - a.daily_sales_avg
        case 'rating': return b.rating - a.rating
        case 'margin': return b.margin - a.margin
        case 'bsr': return (a.bsr ?? 999999) - (b.bsr ?? 999999)
        default:
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      }
    })
    return result
  })

  /** 统计（基于 SKU 行） */
  const totalCount = computed(() => skus.value.length)
  const totalValue = computed(() =>
    skus.value.reduce((sum, s) => sum + s.price * (s.fba_stock + s.fbm_stock), 0)
  )
  const avgMargin = computed(() =>
    skus.value.length > 0
      ? Math.round(skus.value.reduce((s, x) => s + x.margin, 0) / skus.value.length)
      : 0
  )
  const categoryStats = computed(() => {
    const stats: Record<string, number> = {}
    spus.value.forEach(spu => {
      stats[spu.category] = (stats[spu.category] || 0) + 1
    })
    return stats
  })

  // ====== 分组 Getters ======

  const currentGroup = computed(() =>
    groups.value.find(g => g.id === currentGroupId.value) || null
  )
  const groupProductCount = computed(() => {
    const map: Record<string, number> = {}
    groups.value.forEach(g => {
      map[g.id] = spus.value.filter(p => p.groups?.includes(g.id)).length
    })
    return map
  })
  const currentGroupProducts = computed(() => {
    if (!currentGroupId.value) return []
    return spus.value.filter(p => p.groups?.includes(currentGroupId.value!))
  })
  const ungroupedCount = computed(() =>
    spus.value.filter(p => !p.groups || p.groups.length === 0).length
  )
  const getProductsByGroup = (groupId: string): ProductItem[] => {
    const spuIds = spus.value.filter(p => p.groups?.includes(groupId)).map(p => p.id)
    return skus.value.filter(s => spuIds.includes(s.spu_id)).map(s => skuToRow(s, spus.value.find(p => p.id === s.spu_id)))
  }

  // ====== SPU/SKU 关系 Getters ======

  /** 获取某 SPU 下的所有 SKU */
  const getSkus = (spuId: string): Sku[] =>
    skus.value.filter(s => s.spu_id === spuId)

  /** 获取某 SKU 所属的 SPU */
  const getSpu = (skuId: string): Spu | undefined => {
    const sku = skus.value.find(s => s.id === skuId)
    if (!sku) return undefined
    return spus.value.find(p => p.id === sku.spu_id)
  }

  /** 判断某 id 是否为 SPU */
  const isSpu = (id: string): boolean =>
    spus.value.some(p => p.id === id)

  // 兼容旧 API：getChildren / getParent / isParent
  const getChildren = (spuId: string): ProductItem[] =>
    skus.value.filter(s => s.spu_id === spuId).map(s => skuToRow(s, spus.value.find(p => p.id === spuId)))
  const getParent = (skuId: string): ProductItem | undefined => {
    const spu = getSpu(skuId)
    return spu ? spuToRow(spu) : undefined
  }
  const isParent = (id: string): boolean => isSpu(id)

  // ====== Actions ======

  async function fetchItems() {
    isLoading.value = true
    try {
      const [sres, kres] = await Promise.all([fetchSpus(), fetchSkus()])
      spus.value = sres.items || []
      skus.value = kres.items || []
      try {
        const gres = await fetchProductGroups()
        groups.value = gres.groups || []
      } catch (e) {
        console.warn('[ProductLibrary] 分组拉取失败', e)
      }
    } catch (e) {
      console.warn('[ProductLibrary] 拉取失败，回退 Mock 数据', e)
      spus.value = [...MOCK_SPUS]
      skus.value = [...MOCK_SKUS]
    } finally {
      isLoading.value = false
    }
  }

  /** 新增 SPU（主产品，可带初始 SKU） */
  async function addSpu(data: Partial<Spu>, initialSkus: Array<Partial<Sku>> = []): Promise<Spu> {
    try {
      const created = await createSpu(data)
      spus.value.unshift(created)
      for (const s of initialSkus) {
        await createSku({ ...s, spu_id: created.id })
      }
      // 重新拉取 SKU 以保持同步
      const kres = await fetchSkus()
      skus.value = kres.items || []
      return created
    } catch (e) {
      console.warn('[ProductLibrary] 新增 SPU 失败，本地兜底', e)
      const now = new Date().toISOString()
      const newSpu: Spu = {
        id: `spu-${Date.now()}`,
        title: data.title || '未命名主产品',
        brand: data.brand || '',
        category: data.category || 'other',
        sub_category: data.sub_category || '',
        spu_theme: data.spu_theme ?? null,
        keywords: data.keywords || [],
        selling_points: data.selling_points,
        description: data.description,
        main_image: data.main_image || '',
        images: data.images || [],
        spu_common: data.spu_common,
        shop_id: data.shop_id || '',
        tags: data.tags || [],
        notes: data.notes || '',
        status: data.status || 'draft',
        groups: data.groups || [],
        created_at: now,
        updated_at: now,
      }
      spus.value.unshift(newSpu)
      return newSpu
    }
  }

  async function updateSpuItem(id: string, data: Partial<Spu>): Promise<void> {
    const idx = spus.value.findIndex(i => i.id === id)
    if (idx !== -1) {
      spus.value[idx] = { ...spus.value[idx], ...data, updated_at: new Date().toISOString() }
    }
    try {
      await updateSpu(id, data)
    } catch (e) {
      console.warn('[ProductLibrary] 更新 SPU 失败', e)
    }
  }

  async function deleteSpuCascade(id: string): Promise<void> {
    spus.value = spus.value.filter(i => i.id !== id)
    skus.value = skus.value.filter(s => s.spu_id !== id)
    try {
      await deleteSpu(id)
    } catch (e) {
      console.warn('[ProductLibrary] 删除 SPU 失败', e)
    }
  }

  async function addSku(data: Partial<Sku>): Promise<Sku> {
    try {
      const created = await createSku(data)
      skus.value.unshift(created)
      return created
    } catch (e) {
      console.warn('[ProductLibrary] 新增 SKU 失败，本地兜底', e)
      const now = new Date().toISOString()
      const newSku: Sku = {
        id: `sku-${Date.now()}`,
        spu_id: data.spu_id || '',
        spec_value: data.spec_value ?? null,
        asin: data.asin || '',
        sku_code: data.sku_code || `SKU-${Date.now()}`,
        price: data.price || 0,
        cost: data.cost || 0,
        currency: data.currency || 'USD',
        fba_stock: data.fba_stock || 0,
        fbm_stock: data.fbm_stock || 0,
        fulfillment_type: data.fulfillment_type || 'FBA',
        bsr: data.bsr ?? null,
        rating: data.rating || 0,
        review_count: data.review_count || 0,
        daily_sales_avg: data.daily_sales_avg || 0,
        roi: data.roi || 0,
        margin: data.margin || 0,
        listing_status: data.listing_status || 'draft',
        generated_title: data.generated_title,
        generated_bullets: data.generated_bullets,
        generated_a_plus: data.generated_a_plus,
        seo_score: data.seo_score,
        generated_at: data.generated_at,
        listing_version: data.listing_version || 1,
        listing_history: data.listing_history,
        has_a_plus: data.has_a_plus || false,
        has_video: data.has_video || false,
        rating_breakdown: data.rating_breakdown,
        tags: data.tags || [],
        notes: data.notes || '',
        status: data.status || 'active',
        created_at: now,
        updated_at: now,
      }
      skus.value.unshift(newSku)
      return newSku
    }
  }

  async function updateSkuItem(id: string, data: Partial<Sku>): Promise<void> {
    const idx = skus.value.findIndex(i => i.id === id)
    if (idx !== -1) {
      skus.value[idx] = { ...skus.value[idx], ...data, updated_at: new Date().toISOString() }
    }
    try {
      await updateSku(id, data)
    } catch (e) {
      console.warn('[ProductLibrary] 更新 SKU 失败', e)
    }
  }

  async function deleteSkuItem(id: string): Promise<void> {
    skus.value = skus.value.filter(s => s.id !== id)
    try {
      await deleteSku(id)
    } catch (e) {
      console.warn('[ProductLibrary] 删除 SKU 失败', e)
    }
  }

  /** 自我组化：独立 SKU → 拆成 1 SPU + 1 SKU（SKU 保留原 ASIN/价格/库存） */
  async function promoteToSpu(sku: Sku, theme: string, specValue: string): Promise<{ spu: Spu; sku: Sku }> {
    const spuData: Partial<Spu> = {
      id: `spu-${Date.now()}`,
      title: sku.asin,
      brand: '',
      category: 'other',
      sub_category: '',
      spu_theme: theme,
      keywords: [],
      selling_points: '',
      main_image: '',
      images: [],
      spu_common: {
        brand: '',
        category: 'other',
        keywords: [],
        selling_points: '',
        bullets: sku.generated_bullets?.length ? sku.generated_bullets : [],
        a_plus: sku.generated_a_plus || null,
      },
      shop_id: '',
      tags: ['SPU主产品'],
      notes: '由独立产品组化生成，请维护标题/品牌/分类等公共信息',
      status: 'draft',
      groups: [],
    }
    const spu = await addSpu(spuData)
    const updatedSku = { ...sku, spu_id: spu.id, spec_value: specValue }
    await updateSkuItem(sku.id, { spu_id: spu.id, spec_value: specValue })
    return { spu, sku: updatedSku }
  }

  /** 创建 SPU + 批量 SKU（1 主 + N 规格） */
  async function createSpuWithSkus(
    spuData: Partial<Spu>,
    skuList: Array<{ spec_value: string; asin: string; price: number; stock: number; sku_code?: string }>,
  ): Promise<{ spu: Spu; skus: Sku[] }> {
    const spu = await addSpu(spuData)
    const createdSkus: Sku[] = []
    for (const s of skuList) {
      createdSkus.push(await addSku({
        spu_id: spu.id,
        spec_value: s.spec_value,
        asin: s.asin,
        sku_code: s.sku_code || `SKU-${s.asin}`,
        price: s.price,
        cost: 0,
        fba_stock: s.stock,
        margin: s.price > 0 ? Math.round(((s.price - 0) / s.price) * 100) : 0,
        tags: ['SKU规格'],
        notes: `规格值：${s.spec_value}`,
      }))
    }
    return { spu, skus: createdSkus }
  }

  /** 同步 SPU 公共文案到全部 SKU（覆盖式） */
  async function syncSpuCommonToSkus(spuId: string): Promise<number> {
    const spu = spus.value.find(p => p.id === spuId)
    if (!spu) return 0
    const pc = spu.spu_common || {}
    const children = skus.value.filter(s => s.spu_id === spuId)
    let synced = 0
    for (const s of children) {
      await updateSkuItem(s.id, {
        generated_bullets: pc.bullets?.length ? [...pc.bullets] : s.generated_bullets,
        generated_a_plus: pc.a_plus ?? s.generated_a_plus,
      } as any)
      synced++
    }
    return synced
  }

  /** 更新 SKU 的 Listing（Listing 优化工具写回） */
  async function updateListing(id: string, listingData: {
    generated_title?: string
    generated_bullets?: Array<{ title: string; content: string }>
    generated_a_plus?: any
    seo_score?: number
    generated_at?: string
    version?: number
  }): Promise<{ synced: boolean; error?: string }> {
    const idx = skus.value.findIndex(i => i.id === id)
    if (idx === -1) throw new Error(`SKU ${id} not found`)
    const sku = skus.value[idx]
    const currentVersion = sku.listing_version || 0
    const history = sku.listing_history || []
    if (sku.generated_title) {
      history.unshift({
        version: currentVersion,
        title: sku.generated_title,
        bullets: sku.generated_bullets || [],
        updated_at: sku.generated_at || new Date().toISOString(),
      })
      if (history.length > 3) history.length = 3
    }
    const updated: Partial<Sku> = {
      ...listingData,
      listing_version: currentVersion + 1,
      listing_history: history,
      listing_status: listingData.generated_title && sku.listing_status === 'draft' ? 'ready' : sku.listing_status,
    }
    skus.value[idx] = { ...sku, ...updated, updated_at: new Date().toISOString() }
    try {
      await updateSkuListing(id, listingData)
    } catch (e: any) {
      // 不能静默吞掉：调用方（如「保存全部」）必须能区分
      // 「已落库」与「只更新了内存」，否则会显示成功却查不到数据。
      console.warn('[ProductLibrary] Listing 写回失败', e)
      return { synced: false, error: e?.message || '后端同步失败' }
    }
    return { synced: true }
  }

  // ====== 分组 Actions ======

  async function createGroup(input: { name: string; color?: string }): Promise<ProductGroup> {
    try {
      const g = await createProductGroup(input)
      groups.value.push(g)
      return g
    } catch (e) {
      console.warn('[ProductLibrary] 新建分组失败', e)
      const g: ProductGroup = {
        id: `group-${Date.now()}`,
        name: input.name,
        color: input.color || '#1890ff',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }
      groups.value.push(g)
      return g
    }
  }

  function renameGroup(id: string, name: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) g.name = name
    updateProductGroup(id, { name }).catch(() => {})
  }

  function setGroupColor(id: string, color: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) g.color = color
    updateProductGroup(id, { color }).catch(() => {})
  }

  function deleteGroup(id: string) {
    groups.value = groups.value.filter(g => g.id !== id)
    deleteProductGroup(id).catch(() => {})
  }

  function moveGroup(id: string, direction: 'up' | 'down') {
    moveProductGroup(id, direction).then(() => {
      const idx = groups.value.findIndex(g => g.id === id)
      const target = direction === 'up' ? idx - 1 : idx + 1
      if (idx === -1 || target < 0 || target >= groups.value.length) return
      const arr = groups.value
      ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
    }).catch(() => {})
  }

  function selectGroup(id: string | null) {
    currentGroupId.value = id
  }

  function addProductsToGroups(spuIds: string[], groupIds: string[]): number {
    let n = 0
    spus.value.forEach(p => {
      if (spuIds.includes(p.id)) {
        const merged = Array.from(new Set([...(p.groups || []), ...groupIds]))
        p.groups = merged
        updateSpuItem(p.id, { groups: merged }).catch(() => {})
        n++
      }
    })
    return n
  }

  // ====== 兼容层（供 ProductLibrary.vue 等旧消费方平滑过渡） ======

  /** 平铺所有 SKU 行（兼容旧 items：可售商品列表） */
  const items = computed<ProductItem[]>(() => allSkuRows.value)

  /** 兼容 addItem：创建 1 SPU + 1 SKU（payload 混合 SPU/SKU 字段） */
  async function addItem(data: any): Promise<ProductItem> {
    const spu = await addSpu({
      title: data.title || '未命名主产品',
      brand: data.brand || '',
      category: data.category || 'other',
      sub_category: data.sub_category || '',
      spu_theme: data.spu_theme ?? null,
      keywords: data.keywords || [],
      selling_points: data.selling_points,
      description: data.description,
      main_image: data.main_image || '',
      images: data.images || [],
      spu_common: data.spu_common,
      shop_id: data.shop_id || '',
      tags: data.tags || [],
      notes: data.notes || '',
      status: data.status || 'draft',
      groups: data.groups || [],
    })
    const sku = await addSku({
      spu_id: spu.id,
      spec_value: data.spec_value ?? null,
      asin: data.asin || '',
      sku_code: data.sku || data.sku_code || `SKU-${data.asin || Date.now()}`,
      price: data.price || 0,
      cost: data.cost || 0,
      fba_stock: data.fba_stock || 0,
      fbm_stock: data.fbm_stock || 0,
      fulfillment_type: data.fulfillment_type || 'FBA',
      bsr: data.bsr ?? null,
      rating: data.rating || 0,
      review_count: data.review_count || 0,
      daily_sales_avg: data.daily_sales_avg || 0,
      roi: data.roi || 0,
      margin: data.margin || 0,
      listing_status: data.listing_status || 'draft',
      tags: data.tags || [],
      notes: data.notes || '',
      status: data.status || 'active',
    })
    return skuToRow(sku, spu)
  }

  /** 兼容 updateItem：按 id 判断 SPU / SKU */
  async function updateItem(id: string, data: any): Promise<void> {
    if (isSpu(id)) {
      await updateSpuItem(id, data)
    } else {
      await updateSkuItem(id, data)
    }
  }

  /** 兼容 deleteItem：SPU 级联删除，SKU 单独删除 */
  async function deleteItem(id: string): Promise<void> {
    if (isSpu(id)) {
      await deleteSpuCascade(id)
    } else {
      await deleteSkuItem(id)
    }
  }

  /** 兼容 createVariationGroup：创建 1 SPU + N SKU */
  async function createVariationGroup(
    parent: {
      title: string; brand: string; category: string; sub_category?: string
      spu_theme: string; main_image?: string; images?: string[]
      selling_points?: string; keywords?: string[]; groups?: string[]; spu_common?: SpuCommon
    },
    children: Array<{ spec_value: string; asin: string; price: number; stock: number; sku?: string }>,
  ): Promise<{ parent: ProductItem; children: ProductItem[] }> {
    const { spu, skus: createdSkus } = await createSpuWithSkus(
      {
        title: parent.title,
        brand: parent.brand,
        category: parent.category,
        sub_category: parent.sub_category || '',
        spu_theme: parent.spu_theme,
        main_image: parent.main_image || '',
        images: parent.images || [],
        selling_points: parent.selling_points || '',
        keywords: parent.keywords || [],
        groups: parent.groups || [],
        spu_common: parent.spu_common,
        tags: ['SPU主产品'],
        notes: 'SPU主产品，请在下方展开面板维护 SKU',
      },
      children.map(c => ({
        spec_value: c.spec_value,
        asin: c.asin,
        price: c.price,
        stock: c.stock,
        sku_code: c.sku,
      })),
    )
    return {
      parent: spuToRow(spu, createdSkus.map(s => skuToRow(s, spu))),
      children: createdSkus.map(s => skuToRow(s, spu)),
    }
  }

  /** 兼容 promoteToVariationGroup：独立产品（SKU 行）→ 拆成 1 SPU + 1 SKU */
  async function promoteToVariationGroup(
    product: ProductItem,
    theme: string,
    firstChildValue: string,
  ): Promise<{ parent: ProductItem; child: ProductItem }> {
    const sku = skus.value.find(s => s.id === product.id)
    if (!sku) throw new Error(`SKU ${product.id} 不存在`)
    const { spu, sku: updatedSku } = await promoteToSpu(sku, theme, firstChildValue)
    return { parent: spuToRow(spu), child: skuToRow(updatedSku, spu) }
  }

  /** 兼容 addChildVariation：给 SPU 新增一个 SKU */
  async function addChildVariation(
    parent: ProductItem,
    child: { spec_value: string; asin: string; price: number; stock: number; sku?: string },
  ): Promise<ProductItem> {
    const sku = await addSku({
      spu_id: parent.id,
      spec_value: child.spec_value,
      asin: child.asin,
      sku_code: child.sku || `SKU-${child.asin || Date.now()}`,
      price: child.price,
      cost: 0,
      fba_stock: child.stock,
      margin: child.price > 0 ? Math.round(((child.price - 0) / child.price) * 100) : 0,
      tags: ['SKU规格'],
      notes: `规格值：${child.spec_value}`,
    })
    return skuToRow(sku, spus.value.find(p => p.id === parent.id))
  }

  /** 兼容 syncParentContentToChildren：同步 SPU 公共文案到全部 SKU */
  async function syncParentContentToChildren(parent: ProductItem): Promise<number> {
    return syncSpuCommonToSkus(parent.id)
  }

  /** 兼容 findRowById：按 id 查 ProductItem（SPU 行 / SKU 行），涵盖两种来源 */
  function findRowById(id: string): ProductItem | undefined {
    return (
      treeItems.value.find(r => r.id === id) ||
      flatSpuRows.value.find(r => r.id === id) ||
      allSkuRows.value.find(r => r.id === id) ||
      undefined
    )
  }

  /** 兼容 batchDelete */
  async function batchDelete(ids: string[]): Promise<void> {
    for (const id of ids) {
      await deleteItem(id)
    }
  }

  /** 兼容 parseAndImport：解析 JSON/CSV 文件并批量新增（1 产品 = 1 SPU + 1 SKU） */
  async function parseAndImport(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
    const errors: string[] = []
    let success = 0
    try {
      const text = await file.text()
      let rows: any[] = []
      if (file.name.endsWith('.json')) {
        const parsed = JSON.parse(text)
        rows = Array.isArray(parsed) ? parsed : (parsed.items || [])
      } else {
        // 简单 CSV 解析
        const lines = text.split(/\r?\n/).filter(l => l.trim())
        const header = lines[0].split(',').map(h => h.trim())
        rows = lines.slice(1).map(l => {
          const vals = l.split(',')
          const o: any = {}
          header.forEach((h, i) => { o[h] = vals[i]?.trim() })
          return o
        })
      }
      for (const r of rows) {
        try {
          await addItem(r)
          success++
        } catch (e) {
          errors.push(`${r.asin || r.title || '?'}: ${e instanceof Error ? e.message : String(e)}`)
        }
      }
    } catch (e) {
      errors.push(`文件解析失败: ${e instanceof Error ? e.message : String(e)}`)
    }
    return { success, failed: errors.length, errors }
  }

  return {
    // State
    spus,
    skus,
    items,
    isLoading,
    searchQuery,
    filterCategory,
    filterStatus,
    sortBy,
    groups,
    currentGroupId,

    // 转换
    spuToRow,
    skuToRow,

    // Getters
    allSkuRows,
    treeItems,
    flatSpuRows,
    filteredItems,
    totalCount,
    totalValue,
    avgMargin,
    categoryStats,
    currentGroup,
    groupProductCount,
    currentGroupProducts,
    ungroupedCount,
    getProductsByGroup,
    getSkus,
    getSpu,
    isSpu,
    // 兼容旧 API
    getChildren,
    getParent,
    isParent,

    // Actions
    fetchItems,
    addSpu,
    updateSpuItem,
    deleteSpuCascade,
    addSku,
    updateSkuItem,
    deleteSkuItem,
    promoteToSpu,
    createSpuWithSkus,
    syncSpuCommonToSkus,
    updateListing,
    createGroup,
    renameGroup,
    setGroupColor,
    deleteGroup,
    moveGroup,
    selectGroup,
    addProductsToGroups,

    // 兼容旧 API（ProductLibrary.vue 等旧消费方）
    addItem,
    updateItem,
    deleteItem,
    createVariationGroup,
    promoteToVariationGroup,
    addChildVariation,
    syncParentContentToChildren,
    batchDelete,
    parseAndImport,
    findRowById,
  }
})

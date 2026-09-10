/**
 * 素材库状态管理
 *
 * 管理跨境电商营销素材（图片/视频）的 CRUD、分组归档。
 * 与产品库的 AIGC 工具链打通：
 *  - 静态素材生成器 / AI 短视频生成 的产出可归档到素材库
 *  - 素材可绑定到具体产品档案（productId / productName）
 *  - 短视频工具可反向从素材库选取首帧 / 分镜图
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchAssets,
  fetchAssetGroups,
  createAsset,
  updateAsset,
  deleteAsset,
  batchDeleteAssets,
  createAssetGroup,
  updateAssetGroup,
  deleteAssetGroup,
} from '@/api/assets'

// ====== 类型定义 ======

/** 素材大类：图片 / 视频 */
export type AssetKind = 'image' | 'video'

export interface AssetItem {
  id: string
  name: string                    // 素材名称
  kind: AssetKind                 // 图片 / 视频
  category: string                // 类型：white-bg / three-view / detail / lifestyle / scene / storyboard-frame / video / main-image
  url: string                     // 图片 URL / 视频封面 URL
  videoUrl?: string               // 视频播放地址（kind=video 时）
  thumbnail?: string              // 缩略图
  productId?: string              // 绑定产品 id（可空）
  productName?: string            // 绑定产品名快照（用于展示，产品改名不回写）
  asin?: string                   // 产品 ASIN（快照）
  prompt?: string                 // 生成提示词（AIGC 产出物时保留）
  source: string                  // 来源：aigc / upload / video-gen / manual
  width?: number
  height?: number
  tags: string[]
  groups: string[]                // 所属分组 id（一素材多组）
  notes: string
  createdAt: string
  updatedAt: string
}

export interface AssetGroup {
  id: string
  name: string
  color: string
  createdAt: string
  updatedAt: string
}

export interface AssetCategoryDef {
  key: string
  label: string
  icon: string
}

// ====== 内置分类（素材类型） ======

export const ASSET_CATEGORIES: AssetCategoryDef[] = [
  { key: 'white-bg', label: '白底图', icon: '⚪' },
  { key: 'three-view', label: '多角度三视图', icon: '🔄' },
  { key: 'detail', label: '细节特写', icon: '🔍' },
  { key: 'lifestyle', label: '生活方式', icon: '🏠' },
  { key: 'scene', label: '场景图', icon: '🎬' },
  { key: 'storyboard-frame', label: '分镜首帧', icon: '🎞️' },
  { key: 'video', label: '短视频', icon: '🎥' },
  { key: 'other', label: '其他', icon: '📦' },
]

export const CATEGORY_ICON: Record<string, string> = Object.fromEntries(
  ASSET_CATEGORIES.map(c => [c.key, c.icon])
)
export const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  ASSET_CATEGORIES.map(c => [c.key, c.label])
)

/** 预置分组标签颜色 */
export const ASSET_GROUP_COLORS = [
  '#1890ff', '#52c41a', '#faad14', '#ff4d4f',
  '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16',
]

// ====== Mock 素材（离线兜底用） ======

const MOCK_ASSETS: AssetItem[] = [
  {
    id: 'asset-000',
    name: '便携加湿器 - 白底主图',
    kind: 'image',
    category: 'white-bg',
    url: '/mock/products/B0CXXXX001.png',
    thumbnail: '/mock/products/B0CXXXX001.png',
    productId: 'prod-000',
    productName: 'Portable Mini Humidifier for Bedroom Desk USB Cool Mist',
    asin: 'B0CXXXX001',
    prompt: 'Pure white background, portable mini humidifier, front 45° angle, studio lighting',
    source: 'aigc',
    tags: ['主图', '白底'],
    groups: [],
    notes: 'AI 静态素材生成 - 白底图',
    createdAt: '2026-09-01T07:00:00Z',
    updatedAt: '2026-09-01T07:00:00Z',
  },
  {
    id: 'asset-001',
    name: '无线蓝牙耳机 - 三视图 1',
    kind: 'image',
    category: 'three-view',
    url: '/mock/products/B0DGXRLVLC.png',
    thumbnail: '/mock/products/B0DGXRLVLC.png',
    productId: 'prod-001',
    productName: '无线蓝牙耳机 降噪头戴式 长续航40小时 HiFi音质',
    asin: 'B0DGXRLVLC',
    prompt: 'Product three-view: front, side, back on pure white background',
    source: 'aigc',
    tags: ['三视图'],
    groups: [],
    notes: 'AI 静态素材生成 - 多角度三视图',
    createdAt: '2026-09-01T07:30:00Z',
    updatedAt: '2026-09-01T07:30:00Z',
  },
  {
    id: 'asset-002',
    name: '无线蓝牙耳机 - 细节特写（耳罩）',
    kind: 'image',
    category: 'detail',
    url: '/mock/products/B0DGXRLVLC.png',
    thumbnail: '/mock/products/B0DGXRLVLC.png',
    productId: 'prod-001',
    productName: '无线蓝牙耳机 降噪头戴式 长续航40小时 HiFi音质',
    asin: 'B0DGXRLVLC',
    source: 'aigc',
    tags: ['细节图'],
    groups: [],
    notes: 'AI 静态素材生成 - 细节特写',
    createdAt: '2026-09-01T07:31:00Z',
    updatedAt: '2026-09-01T07:31:00Z',
  },
  {
    id: 'asset-003',
    name: '瑜伽垫 - 生活方式场景',
    kind: 'image',
    category: 'lifestyle',
    url: '/mock/products/B0GHI23456.png',
    thumbnail: '/mock/products/B0GHI23456.png',
    productId: 'prod-004',
    productName: '瑜伽垫 加厚10mm 双面防滑 TPE环保 无味',
    asin: 'B0GHI23456',
    prompt: 'Woman doing yoga on thick mat in bright living room, morning light, lifestyle photography',
    source: 'aigc',
    tags: ['场景图', 'A+ 配图'],
    groups: [],
    notes: '可作 A+ Content 配图',
    createdAt: '2026-09-01T08:00:00Z',
    updatedAt: '2026-09-01T08:00:00Z',
  },
  {
    id: 'asset-004',
    name: '加湿器带货视频 - 分镜首帧 01',
    kind: 'image',
    category: 'storyboard-frame',
    url: '/mock/products/B0CXXXX001.png',
    thumbnail: '/mock/products/B0CXXXX001.png',
    productId: 'prod-000',
    productName: 'Portable Mini Humidifier for Bedroom Desk USB Cool Mist',
    asin: 'B0CXXXX001',
    source: 'video-gen',
    tags: ['首帧'],
    groups: [],
    notes: '短视频脚本 - 镜头 1 首帧',
    createdAt: '2026-09-01T09:00:00Z',
    updatedAt: '2026-09-01T09:00:00Z',
  },
  {
    id: 'asset-005',
    name: '智能保温杯 - 30s 种草短视频',
    kind: 'video',
    category: 'video',
    url: '/mock/products/B0CXXXX009.png',
    thumbnail: '/mock/products/B0CXXXX009.png',
    videoUrl: '/mock/generated_video.mp4',
    productId: 'prod-002',
    productName: '智能保温杯 温度显示 304不锈钢 大容量500ml',
    asin: 'B0CXXXX009',
    source: 'video-gen',
    width: 1080,
    height: 1920,
    tags: ['短视频'],
    groups: [],
    notes: 'AI 短视频生成 - 9:16 竖版',
    createdAt: '2026-09-01T10:00:00Z',
    updatedAt: '2026-09-01T10:00:00Z',
  },
  {
    id: 'asset-006',
    name: '电动牙刷 - 拍摄原图（用户上传）',
    kind: 'image',
    category: 'other',
    url: '/mock/products/B0DEF67890.png',
    thumbnail: '/mock/products/B0DEF67890.png',
    productId: 'prod-003',
    productName: '电动牙刷 成人声波震动 5档模式 IPX7防水 续航90天',
    asin: 'B0DEF67890',
    source: 'upload',
    tags: ['实拍原图'],
    groups: [],
    notes: '图生图输入原图',
    createdAt: '2026-09-01T11:00:00Z',
    updatedAt: '2026-09-01T11:00:00Z',
  },
]

// ====== Store ======

export const useAssetLibraryStore = defineStore('assetLibrary', () => {
  // ====== State ======
  // 数据源：后端 PostgreSQL。初始为空，靠 fetchItems() 拉取（失败回退 mock 离线演示）
  const items = ref<AssetItem[]>([])
  const groups = ref<AssetGroup[]>([])
  const isLoading = ref(false)
  const currentGroupId = ref<string | null>(null)
  const searchQuery = ref('')
  // 初始值改为 undefined：避免 a-select allow-clear 清空后被误判为「过滤生效」
  const filterCategory = ref<string | undefined>(undefined)
  const filterKind = ref<string | undefined>(undefined)

  // ====== Getters ======

  /** 全部素材（按创建时间倒序） */
  const allItems = computed(() =>
    [...items.value].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  )

  /** 过滤 + 分组筛选后的素材 */
  const filteredItems = computed(() => {
    let result = [...items.value]

    // 分组过滤
    if (currentGroupId.value) {
      if (currentGroupId.value === '__ungrouped__') {
        result = result.filter(item => !item.groups || item.groups.length === 0)
      } else {
        result = result.filter(item => item.groups?.includes(currentGroupId.value!))
      }
    }

    // 类型过滤
    if (filterCategory.value && filterCategory.value !== 'all') {
      result = result.filter(item => item.category === filterCategory.value)
    }
    // 媒体类型过滤
    if (filterKind.value && filterKind.value !== 'all') {
      result = result.filter(item => item.kind === filterKind.value)
    }
    // 搜索
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(item =>
        item.name.toLowerCase().includes(q) ||
        (item.productName || '').toLowerCase().includes(q) ||
        (item.asin || '').toLowerCase().includes(q) ||
        item.tags.some(t => t.toLowerCase().includes(q))
      )
    }

    return [...result].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  })

  /** 统计 */
  const totalCount = computed(() => items.value.length)
  const imageCount = computed(() => items.value.filter(i => i.kind === 'image').length)
  const videoCount = computed(() => items.value.filter(i => i.kind === 'video').length)
  const ungroupedCount = computed(() =>
    items.value.filter(i => !i.groups || i.groups.length === 0).length
  )
  const boundCount = computed(() =>
    items.value.filter(i => i.productId).length
  )

  /** 每个分组的素材数 */
  const groupCount = computed(() => {
    const map: Record<string, number> = {}
    groups.value.forEach(g => {
      map[g.id] = items.value.filter(i => i.groups?.includes(g.id)).length
    })
    return map
  })

  /** 分类统计（用于工具栏计数） */
  const categoryStats = computed(() => {
    const stats: Record<string, number> = {}
    items.value.forEach(i => {
      stats[i.category] = (stats[i.category] || 0) + 1
    })
    return stats
  })

  /** 获取指定分组的所有素材 */
  const getAssetsByGroup = (groupId: string): AssetItem[] =>
    items.value.filter(i => i.groups?.includes(groupId))

  /** 根据产品 id 获取素材（AIGC 归档检索用） */
  const getAssetsByProduct = (productId: string): AssetItem[] =>
    items.value.filter(i => i.productId === productId)

  // ====== Actions ======

  async function fetchItems() {
    isLoading.value = true
    try {
      const res = await fetchAssets()
      items.value = res.items || []
      try {
        const gres = await fetchAssetGroups()
        groups.value = gres.groups || []
      } catch (e) {
        console.warn('[AssetLibrary] 分组拉取失败', e)
      }
    } catch (e) {
      console.warn('[AssetLibrary] 拉取素材失败，回退 Mock 数据', e)
      items.value = [...MOCK_ASSETS]
    } finally {
      isLoading.value = false
    }
  }

  /** 新增素材（AIGC 工具产出归档 / 手动添加 共用入口） */
  function addItem(data: Partial<AssetItem> & { name: string; url: string }): AssetItem {
    const now = new Date().toISOString()
    const item: AssetItem = {
      id: `asset-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: data.name,
      kind: data.kind || 'image',
      category: data.category || 'other',
      url: data.url,
      videoUrl: data.videoUrl,
      thumbnail: data.thumbnail || data.url,
      productId: data.productId,
      productName: data.productName,
      asin: data.asin,
      prompt: data.prompt,
      source: data.source || 'manual',
      tags: data.tags || [],
      groups: data.groups || [],
      notes: data.notes || '',
      createdAt: data.createdAt || now,
      updatedAt: now,
    }
    items.value.unshift(item)
    // 异步写后端（AIGC 归档持久化；失败不影响本地展示）
    createAsset(item).catch(e => console.warn('[AssetLibrary] 归档素材失败', e))
    return item
  }

  function updateItem(id: string, data: Partial<Omit<AssetItem, 'id' | 'createdAt'>>): void {
    const index = items.value.findIndex(i => i.id === id)
    if (index !== -1) {
      items.value[index] = {
        ...items.value[index],
        ...data,
        updatedAt: new Date().toISOString(),
      }
      updateAsset(id, data as any).catch(e => console.warn('[AssetLibrary] 更新素材失败', e))
    }
  }

  function deleteItem(id: string): void {
    items.value = items.value.filter(i => i.id !== id)
    deleteAsset(id).catch(e => console.warn('[AssetLibrary] 删除素材失败', e))
  }

  function batchDelete(ids: string[]): void {
    items.value = items.value.filter(i => !ids.includes(i.id))
    batchDeleteAssets(ids).catch(e => console.warn('[AssetLibrary] 批量删除失败', e))
  }

  // ====== 分组 Actions（仿产品库） ======

  function createGroup(input: { name: string; color?: string }): AssetGroup {
    const group: AssetGroup = {
      id: `asset-group-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: input.name.trim(),
      color: input.color || ASSET_GROUP_COLORS[groups.value.length % ASSET_GROUP_COLORS.length],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    groups.value.push(group)
    createAssetGroup({ name: group.name, color: group.color })
      .then(created => {
        // 后端返回的 id 为准，替换本地临时 id
        const idx = groups.value.findIndex(x => x.id === group.id)
        if (idx !== -1) groups.value[idx] = created
      })
      .catch(e => console.warn('[AssetLibrary] 创建分组失败', e))
    return group
  }

  function renameGroup(id: string, name: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) {
      g.name = name.trim()
      g.updatedAt = new Date().toISOString()
      updateAssetGroup(id, { name: g.name }).catch(e => console.warn('[AssetLibrary] 重命名分组失败', e))
    }
  }

  function setGroupColor(id: string, color: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) {
      g.color = color
      g.updatedAt = new Date().toISOString()
      updateAssetGroup(id, { color }).catch(e => console.warn('[AssetLibrary] 改分组颜色失败', e))
    }
  }

  function deleteGroup(id: string) {
    groups.value = groups.value.filter(g => g.id !== id)
    items.value.forEach(i => {
      if (i.groups) i.groups = i.groups.filter(gid => gid !== id)
    })
    if (currentGroupId.value === id) currentGroupId.value = null
    deleteAssetGroup(id).catch(e => console.warn('[AssetLibrary] 删除分组失败', e))
  }

  function moveGroup(id: string, direction: 'up' | 'down') {
    const idx = groups.value.findIndex(g => g.id === id)
    if (idx === -1) return
    const target = direction === 'up' ? idx - 1 : idx + 1
    if (target < 0 || target >= groups.value.length) return
    const arr = [...groups.value]
    ;[arr[idx], arr[target]] = [arr[target], arr[idx]]
    groups.value = arr
  }

  function selectGroup(id: string | null) {
    currentGroupId.value = id
  }

  /** 将素材加入分组（一素材多组，去重） */
  function addAssetsToGroups(assetIds: string[], groupIds: string[]): number {
    if (!groupIds.length) return 0
    let added = 0
    assetIds.forEach(aid => {
      const a = items.value.find(x => x.id === aid)
      if (!a) return
      if (!a.groups) a.groups = []
      let changed = false
      groupIds.forEach(gid => {
        if (!a.groups!.includes(gid)) {
          a.groups!.push(gid)
          changed = true
        }
      })
      if (changed) {
        a.updatedAt = new Date().toISOString()
        added++
        updateAsset(aid, { groups: a.groups }).catch(e => console.warn('[AssetLibrary] 分组归属同步失败', e))
      }
    })
    return added
  }

  /** 批量设置素材分组（编辑时整体覆盖） */
  function setAssetsGroups(assetId: string, groupIds: string[]) {
    const a = items.value.find(x => x.id === assetId)
    if (a) {
      a.groups = [...groupIds]
      a.updatedAt = new Date().toISOString()
      updateAsset(assetId, { groups: a.groups }).catch(e => console.warn('[AssetLibrary] 设置分组失败', e))
    }
  }

  /** 当前是否启用了任何过滤条件（用于显示"清空过滤"按钮） */
  const hasActiveFilters = computed(() =>
    Boolean(searchQuery.value.trim()) ||
    (filterCategory.value && filterCategory.value !== 'all') ||
    (filterKind.value && filterKind.value !== 'all') ||
    currentGroupId.value !== null
  )

  /** 当前已应用的过滤条件数（用于显示 chip 计数） */
  const activeFilterCount = computed(() => {
    let n = 0
    if (searchQuery.value.trim()) n++
    if (filterCategory.value && filterCategory.value !== 'all') n++
    if (filterKind.value && filterKind.value !== 'all') n++
    if (currentGroupId.value !== null) n++
    return n
  })

  /** 一键清空所有过滤条件（分组 + 媒体 + 类型 + 搜索） */
  function clearAllFilters() {
    searchQuery.value = ''
    filterCategory.value = undefined
    filterKind.value = undefined
    currentGroupId.value = null
  }

  return {
    // State
    items,
    groups,
    isLoading,
    currentGroupId,
    searchQuery,
    filterCategory,
    filterKind,

    // Getters
    allItems,
    filteredItems,
    totalCount,
    imageCount,
    videoCount,
    ungroupedCount,
    boundCount,
    groupCount,
    categoryStats,
    hasActiveFilters,
    activeFilterCount,
    getAssetsByGroup,
    getAssetsByProduct,

    // Actions
    fetchItems,
    addItem,
    updateItem,
    deleteItem,
    batchDelete,
    createGroup,
    renameGroup,
    setGroupColor,
    deleteGroup,
    moveGroup,
    selectGroup,
    clearAllFilters,
    addAssetsToGroups,
    setAssetsGroups,
  }
})

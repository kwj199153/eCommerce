/**
 * 竞品监控统一监控池（MonitorPool）
 *
 * 核心思想：所有竞品 ASIN 只在此录入/分组一次，抓取数据只做一遍，
 * 竞品监控工作台内 6 个面板（价格/BSR/评论星级/变体/Listing快照/库存）
 * 都只是这份监控池的「不同查看面板」，不各自为政。
 *
 * 数据源：后端 PostgreSQL（/api/v1/monitors、/api/v1/monitor-groups），唯一权威源。
 *
 * 两个关键约定（本次改造确立，改代码前务必理解）：
 * 1. **时序数据（price_history / bsr_history / review_events / variations /
 *    listing_changes）不从前端传**。它们在**入池那一刻**由后端 `snapshot.build_time_series`
 *    按 ASIN 确定性生成一次并落库，此后固定不变 —— 原先前端每次进页面重算，
 *    刷新就"重掷"一套曲线，7 日变化/差评预警全跟着跳，数据不可信。
 *    将来接真实抓取时只替换后端生成器，表结构与前端契约都不动。
 * 2. **UI 状态（selectedAsins / currentGroupId / currentOwnership / activePanel）
 *    是纯内存的会话态，刻意不持久化** —— 它们是"当前在看哪一批"的临时圈选，
 *    跟着用户当前操作走；持久化反而会让下次进页面被昨天的圈选绑架。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchMonitors,
  createMonitor,
  batchDeleteMonitors,
  batchUpsertMonitors,
  assignMonitorsToGroup,
  unassignMonitorsFromGroup,
  fetchMonitorGroups,
  createMonitorGroup,
  updateMonitorGroup,
  deleteMonitorGroup,
} from '@/api/monitors'
import { GROUP_PALETTE } from '@/theme/palette'

// ====== 类型定义 ======

/** 分组类型（对标维度），亦允许自由创建自定义分组 */
export type PoolGroupKind = 'product' | 'store' | 'brand' | 'custom'

export interface MonitorGroup {
  id: string
  name: string
  kind: PoolGroupKind
  color: string
  createdAt: string
}

/** 单日价格采样（含促销标记） */
export interface PricePoint {
  date: string
  price: number
  coupon?: number          // Coupon 金额（有则代表当天有优惠券）
  is_prime_deal?: boolean  // Prime 会员专享折扣
  deal_type?: 'ld' | '7dd' | 'bdf' | null // LD 秒杀 / 7天秒杀 / 降价促销
}

/** 单日 BSR 采样 */
export interface BsrPoint {
  date: string
  bsr: number
}

/** 评论事件（每日新增 + 差评预警） */
export interface ReviewEvent {
  date: string
  added: number          // 当日新增评论数
  rating_delta: number   // 当日星级变化（可负）
  negative?: boolean     // 是否触发差评预警
  snippet?: string       // 新增差评原文片段（差评预警用）
}

/** 变体快照 */
export interface VariationItem {
  child_asin: string
  color?: string
  size?: string
  price: number
  in_stock: boolean
  added_on?: string
}

/** Listing 变更日志条目 */
export interface ListingChange {
  id: string
  changed_at: string
  field: 'title' | 'bullet' | 'a_plus' | 'main_image' | 'video' | 'description'
  field_name: string
  old_preview: string
  new_preview: string
}

/** 监控池里单个竞品（一条 ASIN 的完整档案 + 历史序列） */
export interface MonitorPoolRecord {
  id: string
  asin: string
  title: string
  brand: string
  main_image: string
  marketplace: string
  currency: string

  // 最新快照（派生，面板读取这里的当刻值）
  latest_price: number
  price_change_7d: number     // %  7日价格变化（负=降价）
  latest_bsr: number
  bsr_category: string
  bsr_change_7d: number       // 差值（负数=排名上升=变好）
  rating: number
  review_count: number
  reviews_added_7d: number
  stock_status: 'in_stock' | 'low_stock' | 'out_of_stock'
  estimated_units_remaining: number | null // 按近期销量估剩余可售（供入仓估算）
  est_monthly_sales: number

  // 时间序列（各面板共用）
  price_history: PricePoint[]
  bsr_history: BsrPoint[]
  review_events: ReviewEvent[]
  variations: VariationItem[]
  listing_changes: ListingChange[]

  // 分组归属 + 元数据
  group_ids: string[]
  added_at: string

  // 来源溯源（闭环用）：候选库开启监控→'candidate'；监控页手填→'manual'；监控页回流新建→'monitor_page'
  origin?: 'manual' | 'candidate' | 'monitor_page'
  /** 若来自候选库开启监控，记录来源候选 id（用于回流/联动） */
  source_candidate_id?: string

  /**
   * 项目定向归属：该条监控是「哪个主品/候选项目」的对标竞品（定向监控）被纳入统一池。
   * 有值 = 归属某自有产品/选品候选项目；无值 = 游离监控（蓝海随手盯 / 监控页手填），即「无归属」。
   */
  owned_by?: {
    type: 'product' | 'candidate'
    asin: string      // 归属的主品/候选 ASIN
    title?: string    // 归属对象标题（便于监控页展示「归属哪个」）
  }
}

/** 游离监控（蓝海随手盯 / 监控页手填）所需的静态快照：无 owned_by 归属，仅独立跟踪 */
export interface FreeMonitorInput {
  asin: string
  title: string
  brand?: string
  main_image?: string
  latest_price?: number
  latest_bsr?: number
  rating?: number
  review_count?: number
  est_monthly_sales?: number
  bsr_category?: string
  groupId?: string | null
}

/** 从选品库开启监控所需的静态快照（不含时序，首采后由后端补齐） */
export interface MonitorFromCandidateInput {
  asin: string
  title: string
  brand?: string
  main_image?: string
  latest_price?: number
  latest_bsr?: number
  rating?: number
  review_count?: number
  est_monthly_sales?: number
  bsr_category?: string
  groupId?: string | null
  source_candidate_id?: string
  owned_by?: { type: 'product' | 'candidate'; asin: string; title?: string }
}

/** 对标竞品入池（定向监控）入参 */
export interface MonitorFromCompetitorInput {
  asin: string
  title?: string
  brand?: string
  main_image?: string
  category?: string
  marketplace?: string
  ownedBy?: { type: 'product' | 'candidate'; asin: string; title?: string }
}

// ====== 常量 ======

export const POOL_GROUP_COLORS: readonly string[] = GROUP_PALETTE

/** 入池 payload（后端能补的字段一律不带） */
type MonitorWritePayload = Partial<MonitorPoolRecord> & { asin: string }

/**
 * 请求体瘦身：把「前端并不知道」的字段整条丢掉，让后端按 ASIN 推导。
 *
 * 为什么必须丢而不是传空值：
 * - 传 `price_history: []` → 新建时 `_prefer_list` 会把空数组当缺失、回退成生成序列（尚可），
 *   但**合并**已有记录时 `apply_fields` 会把已有的 30 天序列覆写成空（数据丢失）。
 * - 传 `latest_price: 0` → 0 是合法数值，后端 `_prefer` 只认 None，会真的写成 0，
 *   面板上就会出现「售价 $0」这种脏数据。而 0 在此语境下就是"不知道"。
 *
 * 判据：`undefined / null / '' / 0 / []` 一律视为「未提供」。这是**入池**专用语义，
 * 不用于通用编辑（编辑要能显式把字段改成 0）。
 */
function compactPayload(payload: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(payload)) {
    if (v === undefined || v === null || v === '') continue
    if (typeof v === 'number' && v === 0) continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  return out
}

// ====== Store ======

export const useMonitorPoolStore = defineStore('monitorPool', () => {
  // —— 监控池：所有竞品 ASIN 的统一清单（后端权威源，初值空态） ——
  const records = ref<MonitorPoolRecord[]>([])
  // —— 分组 —— 用户自建（无预设）
  const groups = ref<MonitorGroup[]>([])
  // —— 加载态（供库页/大屏显示骨架或空态） ——
  const isLoading = ref(false)

  // —— 多选池：跨面板共用的「当前圈定」ASIN 集（纯内存会话态） ——
  const selectedAsins = ref<string[]>([])

  // —— 面板主导航（保持在哪一个 tab） ——
  const activePanel = ref<'pool' | 'price' | 'bsr' | 'review' | 'variation' | 'listing' | 'inventory'>('pool')

  // —— 分组过滤状态（默认未分组，避免一上来就被拉到"全部"）
  const currentGroupId = ref<string | null>('__ungrouped__')
  // —— 归属过滤状态：'all'全部 | 'owned'有归属(定向) | 'free'无归属(游离) ——
  const currentOwnership = ref<'all' | 'owned' | 'free'>('all')

  // —— 监控额度（付费增值点，纯前端软提示；后端接入后转硬限制） ——
  const monitorQuota = ref(20)     // 允许同时开启定时采集的 ASIN 上限
  const monitoringCount = computed(() => records.value.length)

  // ====== Getters ======

  const totalCount = computed(() => records.value.length)

  /** 是否已达 / 超过额度（软提醒阈值，仅提示不硬拦） */
  const quotaReached = computed(() => monitoringCount.value >= monitorQuota.value)

  /** 按分组/未分组过滤后的监控池清单 */
  const filteredRecords = computed(() => {
    let list = records.value
    if (currentGroupId.value) {
      if (currentGroupId.value === '__ungrouped__') {
        list = list.filter(r => !r.group_ids || r.group_ids.length === 0)
      } else {
        list = list.filter(r => r.group_ids?.includes(currentGroupId.value!))
      }
    }
    // 归属过滤（与分组过滤可叠加）
    if (currentOwnership.value === 'owned') {
      list = list.filter(r => !!r.owned_by)
    } else if (currentOwnership.value === 'free') {
      list = list.filter(r => !r.owned_by)
    }
    return [...list].sort((a, b) => a.asin.localeCompare(b.asin))
  })

  /** 全池归属统计（供「全部/有归属/游离」按钮计数展示） */
  const ownershipCount = computed(() => {
    let owned = 0
    let free = 0
    for (const r of records.value) {
      if (r.owned_by) owned++
      else free++
    }
    return { owned, free, all: records.value.length }
  })

  const groupCount = computed(() => groups.value.length)

  /** 当前选中的监控记录（所有面板共用，避免每个面板各自选 ASIN） */
  const selectedRecords = computed(() =>
    records.value.filter(r => selectedAsins.value.includes(r.asin))
  )

  /** 每个 ASIN 是否在选中池 */
  const selectedSet = computed(() => new Set(selectedAsins.value))

  /** 是否有差评预警 / 变体变化 / 价格异动 等「提醒项」（用于告警条） */
  const alertStats = computed(() => {
    let negative = 0
    let price_drop = 0
    let low_stock = 0
    for (const r of records.value) {
      if (r.review_events.slice(-7).some(e => e.negative)) negative++
      if (r.price_change_7d < -5) price_drop++
      if (r.stock_status === 'low_stock' || r.stock_status === 'out_of_stock') low_stock++
    }
    return { negative, price_drop, low_stock }
  })

  // ====== 加载 / 重置 ======

  let ensured = false

  /**
   * 拉取监控池 + 分组。
   *
   * 失败时**不清空本地数据** —— 网络抖动不该让用户看到"监控池被清空了"。
   * 首屏 records 本来就是 `[]`；切店铺的场景由 `resetForShopSwitch()` 负责清。
   */
  async function fetchItems() {
    ensured = true
    isLoading.value = true
    try {
      const res = await fetchMonitors()
      records.value = res.items || []
      try {
        const gres = await fetchMonitorGroups()
        groups.value = gres.groups || []
      } catch (e) {
        console.warn('[MonitorPool] 分组拉取失败', e)
      }
    } catch (e) {
      console.warn('[MonitorPool] 拉取监控池失败', e)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 确保至少拉取过一次。
   *
   * 库页/大屏 `onMounted` 调它做兜底：正常路径上 Workspace 的
   * `watch(currentShopId)` 已经拉过（`ensured` 为 true），这里会直接返回。
   */
  async function ensureLoaded() {
    if (ensured) return
    try { await fetchItems() } catch (e) { /* 忽略 */ }
  }

  /**
   * 切换店铺时重置。
   *
   * 必须同时清 `ensured` —— 它是一次性闭包标记，只清 records 的话
   * `ensureLoaded()` 仍会因 `ensured === true` 提前返回，切店铺后不再拉取。
   * UI 会话态（圈选/过滤）也一并回到默认，否则会残留上一个店铺的 ASIN 圈选。
   */
  function resetForShopSwitch() {
    records.value = []
    groups.value = []
    selectedAsins.value = []
    currentGroupId.value = '__ungrouped__'
    currentOwnership.value = 'all'
    ensured = false
  }

  // ====== 内部工具 ======

  /** 把一条后端记录并入本地列表（同 ASIN 覆盖，新 ASIN 置顶） */
  function mergeLocal(rec: MonitorPoolRecord) {
    const idx = records.value.findIndex(r => r.asin === rec.asin)
    if (idx >= 0) records.value[idx] = rec
    else records.value.unshift(rec)
  }

  /**
   * 批量入池公共实现。
   *
   * 走 `batch-upsert` 而不是循环单条 POST：后端在一次调用里就能算出
   * added/existing 计数（前端 toast 要用），且判重逻辑只有后端一份，
   * 不会出现"前端以为已存在、后端其实是新增"的口径分裂。
   */
  async function addMany(payloads: MonitorWritePayload[]): Promise<{ added: number; existing: number }> {
    const valid = payloads
      .filter(p => p.asin)
      .map(p => compactPayload(p) as MonitorWritePayload)
    if (!valid.length) return { added: 0, existing: 0 }
    try {
      const res = await batchUpsertMonitors(valid)
      ;(res.items || []).forEach(mergeLocal)
      return { added: res.added || 0, existing: res.existing || 0 }
    } catch (e) {
      console.warn('[MonitorPool] 批量入池失败', e)
      return { added: 0, existing: 0 }
    }
  }

  // ====== Actions ======

  /**
   * 池管理：新增/编辑一条监控 ASIN。
   *
   * 后端同店铺同 ASIN 会**合并**而非新增（唯一写入口），所以本地只需按
   * 返回结果覆盖，不用自己判重。编辑场景传 0 有效（如把价格改成 0 不可用，
   * 但传 `price_change_7d: 0` 表示"没变"是合法的），故此处不做 compact。
   */
  async function upsertRecord(input: MonitorWritePayload): Promise<MonitorPoolRecord | null> {
    try {
      const saved = await createMonitor(input)
      mergeLocal(saved)
      return saved
    } catch (e) {
      console.warn('[MonitorPool] 入池失败', e)
      return null
    }
  }

  /** 批量移出监控池（按 ASIN） */
  async function removeRecords(asins: string[]) {
    if (!asins.length) return
    const set = new Set(asins)
    records.value = records.value.filter(r => !set.has(r.asin))
    selectedAsins.value = selectedAsins.value.filter(a => !set.has(a))
    try {
      await batchDeleteMonitors(asins)
    } catch (e) {
      console.warn('[MonitorPool] 批量移出失败', e)
    }
  }

  // —— 闭环：候选库快照入池 ——

  /**
   * 某 ASIN 是否已在监控池（选品库/产品库据此显示「前往竞品监控」）。
   *
   * 注意：这是**本地缓存**的判断，调用前需确保已 `ensureLoaded()`，
   * 否则刚切店铺时会误判为"未监控"（后端还有兜底合并，不会产生重复行）。
   */
  function isAsinInPool(asin: string): boolean {
    return records.value.some(r => r.asin === asin)
  }

  /**
   * 选品库→开启监控：将一条候选静态快照写入监控池。
   * 时序数据不传，由后端按 ASIN 生成 30 天基线（"首采"）。返回写入后的记录。
   */
  async function addFromCandidate(input: MonitorFromCandidateInput): Promise<MonitorPoolRecord | null> {
    if (isAsinInPool(input.asin)) return records.value.find(r => r.asin === input.asin) || null
    return upsertRecord(compactPayload({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand,
      main_image: input.main_image,
      latest_price: input.latest_price,
      latest_bsr: input.latest_bsr,
      rating: input.rating,
      review_count: input.review_count,
      est_monthly_sales: input.est_monthly_sales,
      bsr_category: input.bsr_category,
      group_ids: input.groupId ? [input.groupId] : undefined,
      origin: 'candidate',
      source_candidate_id: input.source_candidate_id,
      owned_by: input.owned_by,
    }) as MonitorWritePayload)
  }

  /** 批量开启监控（多选候选 → 批量入池），返回 新增 / 已存在 计数 */
  async function addManyFromCandidates(inputs: MonitorFromCandidateInput[]): Promise<{ added: number; existing: number }> {
    return addMany(inputs.map(i => ({
      asin: i.asin,
      title: i.title || i.asin,
      brand: i.brand,
      main_image: i.main_image,
      latest_price: i.latest_price,
      latest_bsr: i.latest_bsr,
      rating: i.rating,
      review_count: i.review_count,
      est_monthly_sales: i.est_monthly_sales,
      bsr_category: i.bsr_category,
      group_ids: i.groupId ? [i.groupId] : undefined,
      origin: 'candidate' as const,
      source_candidate_id: i.source_candidate_id,
      owned_by: i.owned_by,
    })))
  }

  /**
   * 对标竞品 → 定向监控：把「某主品/候选项目下的对标竞品 ASIN」纳入统一监控池，
   * 并打上 owned_by 归属，表示它是该项目定向跟踪的对标。origin='manual'（非候选自身）。
   * 已存在（同 ASIN 已在池）则仅补挂归属（可能归属多个项目，这里记录主归属）。
   */
  async function addFromCompetitor(input: MonitorFromCompetitorInput): Promise<{ record: MonitorPoolRecord | null; added: boolean }> {
    const exist = records.value.find(r => r.asin === input.asin)
    if (exist) {
      if (input.ownedBy && !exist.owned_by) {
        const saved = await upsertRecord({ asin: input.asin, owned_by: input.ownedBy })
        return { record: saved || exist, added: false }
      }
      return { record: exist, added: false }
    }
    const saved = await upsertRecord(compactPayload({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand,
      main_image: input.main_image,
      marketplace: input.marketplace,
      bsr_category: input.category,
      origin: 'manual',
      owned_by: input.ownedBy,
    }) as MonitorWritePayload)
    return { record: saved, added: !!saved }
  }

  /** 批量把一批对标竞品 ASIN 纳入监控池（同一归属项目下），返回 added / existing */
  async function addManyFromCompetitors(inputs: MonitorFromCompetitorInput[]): Promise<{ added: number; existing: number }> {
    return addMany(inputs.map(i => ({
      asin: i.asin,
      title: i.title || i.asin,
      brand: i.brand,
      main_image: i.main_image,
      marketplace: i.marketplace,
      bsr_category: i.category,
      origin: 'manual' as const,
      owned_by: i.ownedBy,
    })))
  }

  /**
   * 游离监控入池：蓝海随手盯 / 监控页手填 → 无 owned_by（不归属任何主品/候选项目），
   * 独立在监控池跟踪。时序由后端补齐。
   */
  async function addFreeMonitor(input: FreeMonitorInput): Promise<{ record: MonitorPoolRecord | null; added: boolean }> {
    const exist = records.value.find(r => r.asin === input.asin)
    if (exist) return { record: exist, added: false }
    const saved = await upsertRecord(compactPayload({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand,
      main_image: input.main_image,
      latest_price: input.latest_price,
      latest_bsr: input.latest_bsr,
      rating: input.rating,
      review_count: input.review_count,
      est_monthly_sales: input.est_monthly_sales,
      bsr_category: input.bsr_category,
      group_ids: input.groupId ? [input.groupId] : undefined,
      origin: 'manual',
    }) as MonitorWritePayload)
    return { record: saved, added: !!saved }
  }

  /** 切归属视图过滤：'all' | 'owned' | 'free' */
  function selectOwnership(v: 'all' | 'owned' | 'free') {
    currentOwnership.value = v
  }

  // —— 分组 Actions ——

  async function createGroup(input: { name: string; kind: PoolGroupKind; color?: string }): Promise<MonitorGroup | null> {
    try {
      const created = await createMonitorGroup({
        name: input.name.trim(),
        kind: input.kind,
        color: input.color || POOL_GROUP_COLORS[groups.value.length % POOL_GROUP_COLORS.length],
      })
      groups.value.push(created)
      return created
    } catch (e) {
      console.warn('[MonitorPool] 创建分组失败', e)
      return null
    }
  }

  async function renameGroup(id: string, name: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) g.name = name.trim()
    try {
      await updateMonitorGroup(id, { name: name.trim() })
    } catch (e) {
      console.warn('[MonitorPool] 重命名分组失败', e)
    }
  }

  async function setGroupColor(id: string, color: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) g.color = color
    try {
      await updateMonitorGroup(id, { color })
    } catch (e) {
      console.warn('[MonitorPool] 改分组颜色失败', e)
    }
  }

  /**
   * 删除分组。**组内 ASIN 不删**，只把它们从该分组摘掉（回落到「未分组」）。
   * 后端同语义，本地同步摘除避免等一次往返才刷新界面。
   */
  async function deleteGroup(id: string) {
    groups.value = groups.value.filter(g => g.id !== id)
    records.value.forEach(r => {
      r.group_ids = r.group_ids.filter(gid => gid !== id)
    })
    if (currentGroupId.value === id) currentGroupId.value = null
    try {
      await deleteMonitorGroup(id)
    } catch (e) {
      console.warn('[MonitorPool] 删除分组失败', e)
    }
  }

  /** 把若干 ASIN 归入某分组（追加） */
  async function assignToGroup(asins: string[], groupId: string) {
    if (!asins.length || !groupId) return
    records.value.forEach(r => {
      if (asins.includes(r.asin) && !r.group_ids.includes(groupId)) r.group_ids.push(groupId)
    })
    try {
      await assignMonitorsToGroup(asins, groupId)
    } catch (e) {
      console.warn('[MonitorPool] 归入分组失败', e)
    }
  }

  /** 把若干 ASIN 移出某分组 */
  async function unassignFromGroup(asins: string[], groupId: string) {
    if (!asins.length || !groupId) return
    records.value.forEach(r => {
      if (asins.includes(r.asin)) r.group_ids = r.group_ids.filter(gid => gid !== groupId)
    })
    try {
      await unassignMonitorsFromGroup(asins, groupId)
    } catch (e) {
      console.warn('[MonitorPool] 移出分组失败', e)
    }
  }

  // —— 多选池 Actions（纯内存，不持久化） ——
  function toggleSelect(asin: string) {
    const i = selectedAsins.value.indexOf(asin)
    if (i >= 0) selectedAsins.value.splice(i, 1)
    else selectedAsins.value.push(asin)
  }

  function setSelected(asins: string[]) {
    selectedAsins.value = [...asins]
  }

  function selectAllFiltered() {
    selectedAsins.value = filteredRecords.value.map(r => r.asin)
  }

  function clearSelected() {
    selectedAsins.value = []
  }

  function selectGroup(id: string | null) {
    currentGroupId.value = id
  }

  return {
    // State
    records,
    groups,
    isLoading,
    selectedAsins,
    activePanel,
    currentGroupId,
    currentOwnership,
    monitorQuota,

    // Getters
    monitoringCount,
    quotaReached,
    totalCount,
    filteredRecords,
    ownershipCount,
    groupCount,
    selectedRecords,
    selectedSet,
    alertStats,

    // 加载 / 重置
    fetchItems,
    ensureLoaded,
    resetForShopSwitch,

    // Actions
    upsertRecord,
    removeRecords,
    createGroup,
    renameGroup,
    setGroupColor,
    deleteGroup,
    assignToGroup,
    unassignFromGroup,
    toggleSelect,
    setSelected,
    selectAllFiltered,
    clearSelected,
    selectGroup,
    isAsinInPool,
    selectOwnership,
    addFreeMonitor,
    addFromCandidate,
    addManyFromCandidates,
    addFromCompetitor,
    addManyFromCompetitors,
  }
})

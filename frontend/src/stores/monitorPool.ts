/**
 * 竞品监控统一监控池（MonitorPool）
 *
 * 核心思想：所有竞品 ASIN 只在此录入/分组一次，抓取数据只做一遍，
 * 竞品监控工作台内 6 个面板（价格/BSR/评论星级/变体/Listing快照/库存）
 * 都只是这份监控池的「不同查看面板」，不各自为政。
 *
 * 本阶段为纯前端实现（Pinia + 确定性 mock 快照），后端 monitors 表/接口留 TODO，
 * 产品逻辑验证跑通后再接真实数据源。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

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

/** 从选品库开启监控所需的静态快照（不含时序，首次抓取后补齐） */
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

// ====== 常量 ======

export const POOL_GROUP_COLORS = ['#1890ff', '#52c41a', '#faad14', '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16', '#f5222d']

// ====== Mock：确定性历史生成 ======

/** 生成近 30 天日期（YYYY-MM-DD，不含今天） */
function lastNDays(n: number): string[] {
  const out: string[] = []
  for (let i = n; i >= 1; i--) {
    const d = new Date(Date.now() - i * 24 * 3600 * 1000)
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`)
  }
  return out
}

/** ASIN 尾数确定性伪随机（0-1），保证刷新不跳动 */
function seedRand(seedStr: string, salt = 0): number {
  let h = 2166136261
  const s = seedStr + salt
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 1000) / 1000
}

interface SeedSpec {
  asin: string
  brand: string
  title: string
  /** 该 ASIN 关联的 mock 主图（public/mock/products/*.png） */
  image: string
  basePrice: number
  baseBsr: number
  rating: number
  reviewCount: number
  monthSales: number
  group: string
  desc: string
}

const MOCK_SPECS: SeedSpec[] = [
  { asin: 'B0MONPRO01', brand: 'ZestPro',     title: 'Portable Espresso Maker 20 Bar Electric for Travel', image: '/mock/products/B0CXXXX001.png', basePrice: 69.99, baseBsr: 842,  rating: 4.3, reviewCount: 3120,  monthSales: 3600,  group: 'grp-product', desc: '核心对标爆款，主图/五点每周更新一次' },
  { asin: 'B0MONPRO02', brand: 'BrewMate',    title: 'Manual Espresso Machine Portable Mini Coffee Press', image: '/mock/products/B0CXXXX002.png', basePrice: 34.99, baseBsr: 1805, rating: 3.9, reviewCount: 958,   monthSales: 1200,  group: 'grp-product', desc: '低价走量款，近两周连续降价抢排名' },
  { asin: 'B0MONSTO01', brand: 'CafeNow',     title: 'CafeNow Cold Brew Maker 2L with Reusable Filter', image: '/mock/products/B0CXXXX003.png', basePrice: 45.5,  baseBsr: 2660, rating: 4.1, reviewCount: 5241,  monthSales: 2100,  group: 'grp-store',   desc: '同一店铺多链接，重点跟踪店铺整体上新节奏' },
  { asin: 'B0MONBRD01', brand: 'Voltage',     title: 'Voltage 100W Fast Charger USB C GaN Wall Charger', image: '/mock/products/B0CXXXX004.png', basePrice: 29.99, baseBsr: 421,  rating: 4.6, reviewCount: 18732, monthSales: 15000, group: 'grp-brand',   desc: '类目头部品牌，监视其促销节奏与变体扩张' },
  { asin: 'B0MONBRD02', brand: 'Voltage',     title: 'Voltage 3-in-1 Magnetic Wireless Charging Stand', image: '/mock/products/B0CXXXX005.png', basePrice: 49.99, baseBsr: 980,  rating: 4.5, reviewCount: 6404,  monthSales: 6800,  group: 'grp-brand',   desc: '同品牌衍生款，注意是否复制爆款打法' },
  { asin: 'B0MONPRO03', brand: 'AeroHeat',    title: 'Smart Portable Heater with Thermostat & Remote', image: '/mock/products/B0CXXXX006.png', basePrice: 55.0,  baseBsr: 3200, rating: 3.7, reviewCount: 402,   monthSales: 640,   group: 'grp-product', desc: '新进入者，评分偏低，观察差评是否限制起量' },
]

/** 依据 spec 生成带 30 天历史序列的完整监控记录 */
function buildMockRecord(spec: SeedSpec, idx: number): MonitorPoolRecord {
  const days = lastNDays(30)
  const base = spec.basePrice
  const p0 = seedRand(spec.asin, 1)

  // 价格历史：缓慢波动 + 几次促销（部分 ASIN 近几天降价）
  const price_history: PricePoint[] = days.map((date, i) => {
    const wave = Math.sin(i / 4 + p0 * 6) * 1.2
    let price = +(base + wave).toFixed(2)
    const pp: PricePoint = { date, price }
    const r = seedRand(spec.asin + date, 2)
    if (r > 0.72) pp.coupon = +(price * 0.08).toFixed(2)
    if (r > 0.9) pp.is_prime_deal = true
    if (i > days.length - 6 && seedRand(spec.asin, 3 + i) > 0.55) {
      // 近几天秒杀
      pp.price = +(base * 0.86).toFixed(2)
      pp.deal_type = seedRand(spec.asin, 4 + i) > 0.5 ? 'ld' : '7dd'
    }
    return pp
  })
  const latest_price = price_history[price_history.length - 1].price
  const price_7d_ago = price_history[price_history.length - 8]?.price || base
  const price_change_7d = +(((latest_price - price_7d_ago) / price_7d_ago) * 100).toFixed(1)

  // BSR 历史：随排名波动
  const bsr_history: BsrPoint[] = days.map((date, i) => {
    const drift = (seedRand(spec.asin + date, 5) - 0.5) * (spec.baseBsr * 0.25)
    let bsr = Math.round(spec.baseBsr + drift + Math.sin(i / 5 + idx) * spec.baseBsr * 0.12)
    return { date, bsr: Math.max(1, bsr) }
  })
  const latest_bsr = bsr_history[bsr_history.length - 1].bsr
  const bsr_7d_ago = bsr_history[bsr_history.length - 8]?.bsr || spec.baseBsr
  const bsr_change_7d = latest_bsr - bsr_7d_ago

  // 评论事件：多数日为 0 新增，偶有新增，差评预警
  const review_events: ReviewEvent[] = days.map((date, i) => {
    const r = seedRand(spec.asin + date, 6)
    if (r < 0.55) return { date, added: 0, rating_delta: 0 }
    const added = 1 + Math.floor(seedRand(spec.asin + date, 7) * (spec.monthSales > 5000 ? 9 : 3))
    const neg = seedRand(spec.asin + date, 8) > 0.88
    return {
      date,
      added,
      rating_delta: +(seedRand(spec.asin + date, 9) * 0.12 - 0.05).toFixed(2),
      negative: neg,
      snippet: neg ? 'Product stopped working after a week, poor quality control.' : undefined,
    }
  })
  const reviews_added_7d = review_events.slice(-7).reduce((s, e) => s + e.added, 0)
  const has_negative_7d = review_events.slice(-7).some(e => e.negative)

  // 变体（部分记录有几个变体）
  const variation_count = 1 + Math.floor(seedRand(spec.asin, 10) * 4)
  const variations: VariationItem[] = Array.from({ length: variation_count }, (_, v) => ({
    child_asin: `${spec.asin.slice(0, -1)}${v}`,
    color: ['Black', 'White', 'Silver', 'Blue', 'Rose Gold'][v % 5],
    size: v % 2 === 0 ? 'Standard' : 'Large',
    price: +(base + (v * 3 - (variation_count / 2))).toFixed(2),
    in_stock: seedRand(spec.asin, 11 + v) > 0.25,
  }))

  // Listing 变更日志（近 30 天 1-3 条）
  const change_count = 1 + Math.floor(seedRand(spec.asin, 12) * 3)
  const fieldPool: Array<[ListingChange['field'], string]> = [
    ['title', '标题'], ['bullet', '五点描述'], ['a_plus', 'A+ 页面'],
    ['main_image', '主图'], ['video', '主图视频'], ['description', '描述'],
  ]
  const listing_changes: ListingChange[] = Array.from({ length: change_count }, (_, ci) => {
    const [field, field_name] = fieldPool[Math.floor(seedRand(spec.asin, 13 + ci) * fieldPool.length)]
    return {
      id: `${spec.asin}-lc-${ci}`,
      changed_at: days[6 + Math.floor(seedRand(spec.asin, 20 + ci) * 20)],
      field,
      field_name,
      old_preview: '旧版本内容……',
      new_preview: `${field_name}已更新：优化关键词 / 调整卖点表达（mock 预览）`,
    }
  })

  // 库存 / 入仓估算（低分/低库存倾向 out_of_stock）
  const stock_roll = seedRand(spec.asin, 30)
  const stock_status: MonitorPoolRecord['stock_status'] = stock_roll > 0.82 ? 'low_stock' : stock_roll > 0.92 ? 'out_of_stock' : 'in_stock'
  const estimated_units_remaining = stock_status === 'out_of_stock'
    ? null
    : stock_status === 'low_stock'
      ? Math.round(80 + seedRand(spec.asin, 31) * 400)
      : Math.round(1500 + seedRand(spec.asin, 32) * 9000)

  return {
    id: `mon-${spec.asin}`,
    asin: spec.asin,
    title: spec.title,
    brand: spec.brand,
    main_image: spec.image,
    marketplace: 'us',
    currency: 'USD',
    latest_price,
    price_change_7d,
    latest_bsr,
    bsr_category: spec.desc,
    bsr_change_7d,
    rating: spec.rating,
    review_count: spec.reviewCount,
    reviews_added_7d,
    stock_status,
    estimated_units_remaining,
    est_monthly_sales: spec.monthSales,
    price_history,
    bsr_history,
    review_events,
    variations,
    listing_changes,
    group_ids: [spec.group],
    added_at: '2026-09-01T00:00:00Z',
  }
}

const MOCK_RECORDS: MonitorPoolRecord[] = MOCK_SPECS.map((s, i) => buildMockRecord(s, i))

// ====== Store ======

export const useMonitorPoolStore = defineStore('monitorPool', () => {
  // —— 监控池：所有竞品 ASIN 的统一清单 ——
  const records = ref<MonitorPoolRecord[]>([...MOCK_RECORDS])
  // —— 分组 —— 用户自建（无预设）
  const groups = ref<MonitorGroup[]>([])
  // —— 多选池：跨面板共用的「当前圈定」ASIN 集 ——
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

  // ====== Actions ======

  /** 池管理：新增/编辑一条监控 ASIN（纯前端，后端留 TODO） */
  function upsertRecord(input: Partial<MonitorPoolRecord> & { asin: string }) {
    const exist = records.value.find(r => r.asin === input.asin)
    if (exist) {
      Object.assign(exist, input)
    } else {
      records.value.unshift({
        id: `mon-${input.asin}`,
        asin: input.asin,
        title: input.title || input.asin,
        brand: input.brand || '',
        main_image: input.main_image || '',
        marketplace: input.marketplace || 'us',
        currency: input.currency || 'USD',
        latest_price: input.latest_price ?? 0,
        price_change_7d: input.price_change_7d ?? 0,
        latest_bsr: input.latest_bsr ?? 0,
        bsr_category: input.bsr_category || '',
        bsr_change_7d: input.bsr_change_7d ?? 0,
        rating: input.rating ?? 0,
        review_count: input.review_count ?? 0,
        reviews_added_7d: 0,
        stock_status: input.stock_status || 'in_stock',
        estimated_units_remaining: input.estimated_units_remaining ?? null,
        est_monthly_sales: input.est_monthly_sales ?? 0,
        price_history: input.price_history || [],
        bsr_history: input.bsr_history || [],
        review_events: input.review_events || [],
        variations: input.variations || [],
        listing_changes: input.listing_changes || [],
        group_ids: input.group_ids || [],
        origin: input.origin || 'manual',
        source_candidate_id: input.source_candidate_id,
        owned_by: input.owned_by,
        added_at: new Date().toISOString(),
      })
    }
  }

  function removeRecords(asins: string[]) {
    const set = new Set(asins)
    records.value = records.value.filter(r => !set.has(r.asin))
    selectedAsins.value = selectedAsins.value.filter(a => !set.has(a))
  }

  // —— 闭环：候选库快照入池 ——

  /** 某 ASIN 是否已在监控池（选品库据此显示「前往竞品监控」） */
  function isAsinInPool(asin: string): boolean {
    return records.value.some(r => r.asin === asin)
  }

  /**
   * 选品库→开启监控：将一条候选静态快照写入监控池。
   * 时序字段留空，模拟「本次为首采，后续后台定时采集累积」。
   * 返回写入后的记录。
   */
  function addFromCandidate(input: MonitorFromCandidateInput): MonitorPoolRecord | null {
    if (isAsinInPool(input.asin)) return records.value.find(r => r.asin === input.asin) || null
    const group_ids = input.groupId ? [input.groupId] : []
    upsertRecord({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand || '',
      main_image: input.main_image || '',
      latest_price: input.latest_price ?? 0,
      latest_bsr: input.latest_bsr ?? 0,
      rating: input.rating ?? 0,
      review_count: input.review_count ?? 0,
      est_monthly_sales: input.est_monthly_sales ?? 0,
      bsr_category: input.bsr_category || '',
      price_history: [],
      bsr_history: [],
      review_events: [],
      variations: [],
      listing_changes: [],
      group_ids,
      origin: 'candidate',
      source_candidate_id: input.source_candidate_id,
      owned_by: input.owned_by,
    })
    return records.value.find(r => r.asin === input.asin) || null
  }

  /** 批量开启监控（多选候选 → 循环 addFromCandidate），返回成功 / 已存在 / 待处理计数 */
  function addManyFromCandidates(inputs: MonitorFromCandidateInput[]): { added: number; existing: number } {
    let added = 0
    let existing = 0
    inputs.forEach(i => {
      if (isAsinInPool(i.asin)) existing++
      else { addFromCandidate(i); added++ }
    })
    return { added, existing }
  }

  /**
   * 对标竞品 → 定向监控：把「某主品/候选项目下的对标竞品 ASIN」纳入统一监控池，
   * 并打上 owned_by 归属，表示它是该项目定向跟踪的对标。origin='manual'（非候选自身）。
   * 已存在（同 ASIN 已在池）则仅补挂归属（可能归属多个项目，这里记录主归属）。
   */
  function addFromCompetitor(input: {
    asin: string
    title?: string
    brand?: string
    main_image?: string
    category?: string
    marketplace?: string
    ownedBy?: { type: 'product' | 'candidate'; asin: string; title?: string }
  }): { record: MonitorPoolRecord | null; added: boolean } {
    const exist = records.value.find(r => r.asin === input.asin)
    if (exist) {
      if (input.ownedBy && !exist.owned_by) {
        exist.owned_by = input.ownedBy
      }
      return { record: exist, added: false }
    }
    upsertRecord({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand || '',
      main_image: input.main_image || '',
      marketplace: input.marketplace || 'us',
      latest_price: 0,
      latest_bsr: 0,
      bsr_category: input.category || '',
      price_history: [],
      bsr_history: [],
      review_events: [],
      variations: [],
      listing_changes: [],
      group_ids: [],
      origin: 'manual',
      owned_by: input.ownedBy,
    })
    return { record: records.value.find(r => r.asin === input.asin) || null, added: true }
  }

  /** 批量把一批对标竞品 ASIN 纳入监控池（同一归属项目下），返回 added / existing */
  function addManyFromCompetitors(inputs: Parameters<typeof addFromCompetitor>[0][]): { added: number; existing: number } {
    let added = 0
    let existing = 0
    inputs.forEach(i => {
      const { added: a } = addFromCompetitor(i)
      if (a) added++
      else existing++
    })
    return { added, existing }
  }

  /**
   * 游离监控入池：蓝海随手盯 / 监控页手填 → 无 owned_by（不归属任何主品/候选项目），
   * 独立在监控池跟踪。时序留空，首采由后台补齐。origin='manual'（非候选自身）。
   */
  function addFreeMonitor(input: FreeMonitorInput): { record: MonitorPoolRecord | null; added: boolean } {
    const exist = records.value.find(r => r.asin === input.asin)
    if (exist) return { record: exist, added: false }
    const group_ids = input.groupId ? [input.groupId] : []
    upsertRecord({
      asin: input.asin,
      title: input.title || input.asin,
      brand: input.brand || '',
      main_image: input.main_image || '',
      latest_price: input.latest_price ?? 0,
      latest_bsr: input.latest_bsr ?? 0,
      rating: input.rating ?? 0,
      review_count: input.review_count ?? 0,
      est_monthly_sales: input.est_monthly_sales ?? 0,
      bsr_category: input.bsr_category || '',
      price_history: [],
      bsr_history: [],
      review_events: [],
      variations: [],
      listing_changes: [],
      group_ids,
      origin: 'manual',
    })
    return { record: records.value.find(r => r.asin === input.asin) || null, added: true }
  }

  /** 切归属视图过滤：'all' | 'owned' | 'free' */
  function selectOwnership(v: 'all' | 'owned' | 'free') {
    currentOwnership.value = v
  }

  // —— 分组 Actions ——
  function createGroup(input: { name: string; kind: PoolGroupKind; color?: string }): MonitorGroup {
    const g: MonitorGroup = {
      id: `grp-${Date.now()}`,
      name: input.name.trim(),
      kind: input.kind,
      color: input.color || POOL_GROUP_COLORS[groups.value.length % POOL_GROUP_COLORS.length],
      createdAt: new Date().toISOString(),
    }
    groups.value.push(g)
    return g
  }

  function deleteGroup(id: string) {
    groups.value = groups.value.filter(g => g.id !== id)
    records.value.forEach(r => {
      r.group_ids = r.group_ids.filter(gid => gid !== id)
    })
    if (currentGroupId.value === id) currentGroupId.value = null
  }

  function renameGroup(id: string, name: string) {
    const g = groups.value.find(x => x.id === id)
    if (g) g.name = name
  }

  /** 把若干 ASIN 归入某分组（追加） */
  function assignToGroup(asins: string[], groupId: string) {
    records.value.forEach(r => {
      if (asins.includes(r.asin) && !r.group_ids.includes(groupId)) r.group_ids.push(groupId)
    })
  }

  function unassignFromGroup(asins: string[], groupId: string) {
    records.value.forEach(r => {
      if (asins.includes(r.asin)) r.group_ids = r.group_ids.filter(gid => gid !== groupId)
    })
  }

  // —— 多选池 Actions ——
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

  /** 触发一次「抓取」：纯前端本轮仅更新时间戳与微调（模拟），后续接真实抓取任务 */
  function refresh() {
    records.value.forEach(r => {
      r.price_history.push({ date: today(), price: r.latest_price })
      if (r.price_history.length > 90) r.price_history.shift()
    })
  }

  return {
    records,
    groups,
    selectedAsins,
    activePanel,
    currentGroupId,
    currentOwnership,
    monitorQuota,
    monitoringCount,
    quotaReached,
    totalCount,
    filteredRecords,
    ownershipCount,
    groupCount,
    selectedRecords,
    selectedSet,
    alertStats,
    upsertRecord,
    removeRecords,
    createGroup,
    deleteGroup,
    renameGroup,
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
    refresh,
  }
})

function today(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

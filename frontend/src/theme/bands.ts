/**
 * 评分分档口径真源（bands.ts）
 *
 * ## 它解决什么问题
 *
 * 项目里「把 0–100 分切成几档、按档上色」这件事，曾经散落在 15 个组件里各写各的 ——
 * 最典型的是**同名函数 `getScoreColor` 在 4 个文件里用了 3 种阈值**（70/40、80/60、75/50）。
 * 维护者改一处，以为改的是「评分配色」，其实只改了 1/3。
 *
 * 本模块把每套口径**具名**收敛到这里：阈值、档位名、档位色只在此处出现一次。
 *
 * ## ⚠️ 三条铁律（防「误并」）
 *
 * 1. **同名 ≠ 同指标。** 两个地方都叫「健康分」，可能是完全不同的指标：
 *    `campaignHealth`（广告 Campaign 健康）与 `monitorHealth`（商品监控健康度）
 *    数值区间相同但语义无关，**不可合并**。
 * 2. **量纲不同不可并。** `0–100` / `0–1` / `0–5` / `0–10` 各自成套。
 *    把 `sentiment`（0–1 比率）并进 `score`（0–100）会让「0.8 分的情感」被当成「差评」。
 * 3. **方向不同不可并。** `usage` / `share` 是**反向**（越大越危险）。
 *    并进正向档会把「风险高=红」和「机会大=绿」缝在一起，做出来的颜色是反的。
 *
 * ## 色彩与分档的关系
 *
 * 档位**数值**是产品决策（决定告警灵敏度），档位**颜色**是本模块的映射。
 * 改一套阈值只改这里一处；改配色同样只改这里。
 */

import { SEM } from './semantic'

type BandDef = {
  /** 量纲区间 `[min, max]`，仅作文档与防误并用；不参与计算 */
  scale: readonly [number, number]
  /** `higher` = 越大越好；`lower` = 越大越危险（反向） */
  dir: 'higher' | 'lower'
  /**
   * 阈值比较方式，决定 `cuts` 的排列方向与边界归属：
   * - `'>='`（默认）→ `cuts` **降序**，`value >= cuts[i]` 即命中第 i 档（阈值含等号，落在「好」的一侧）
   * - `'<='` → `cuts` **升序**，`value <= cuts[i]` 即命中第 i 档（阈值含等号，落在「好」的一侧）
   *
   * 加这个字段是因为**边界等号的归属是会变的**：`acos <= 25 ? ok` 与 `acos < 25 ? ok`
   * 在 `acos = 25` 时给出不同档位。要用原判定就得原样保留比较方向，不能靠改写不等式糊过去。
   */
  cmp?: '>=' | '<='
  /** 分界阈值。`cmp='>='` 时必须降序；`cmp='<='` 时必须升序。档位 = `cuts.length + 1` 个 */
  cuts: readonly number[]
  /**
   * 档位名，长度必须 = `cuts.length + 1`。
   * 顺序与 `cuts` **一一对应**：`cuts[i]` 命中即取 `keys[i]`，最后一档是「谁都没命中」。
   * 所以 `dir='higher'` 时天然是「最好 → 最差」，`dir='lower'` 时是「最危险 → 最安全」。
   */
  keys: readonly string[]
  /** 档位色，与 `keys` 等长同序 */
  colors: readonly string[]
  /** 用途 + 真源出处。**新增口径时必填** —— 这段注释就是「防误并」的最后一道闸 */
  note: string
}

const DEFS = {
  // ==================== 正向 · 0–100 越高越好 ====================

  /** 通用综合评分：SEO 总分 / 标题 SEO 分 / 竞品 Listing 质量分 / 排名潜力 */
  score: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [80, 60],
    keys: ['excellent', 'good', 'poor'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '通用 0–100 综合评分三分档。适用：SEODiagnostic 总分、TitleGenerator SEO 分 / 排名潜力、CompetitorResult listing_quality_score。',
  },

  /** 蓝海评分 —— 阈值对齐后端 `product_research/service.py:62-64` */
  ocean: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [70, 40],
    keys: ['premium', 'moderate', 'crowded'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '蓝海评分。**真源在后端**：`product_research/service.py` premium_count(≥70) / moderate_count(40–70) / high_competition_count(<40)。前端 BlueOceanResult、BlueOceanDetailDrawer、CandidateLibrary 必须跟这里走，不要各写。',
  },

  /**
   * 广告 Campaign 健康分 —— **红界对齐后端告警阈值 `< 50`**
   *
   * 后端 `ad_analysis/agent_ad.py:902` 用 `worst_campaign.health_score < 50`
   * 生成「Campaign 表现差」issue、并建议「暂停健康度 < 50 的 Campaign」。
   * 前端若用 60 当红界，会出现「后端报告里没有这条问题，前端却标红」的分叉。
   */
  campaignHealth: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [80, 50],
    keys: ['good', 'warn', 'poor'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '广告 Campaign 健康分（AdDiagnosisResult 的 Campaign 表）。**红界 50 对齐后端** `ad_analysis/agent_ad.py:902` 的 `health_score < 50` 告警阈值 —— 改这个数就等于改「前端标红 == 后端报问题」的一致性。',
  },

  /** 竞争力评分：BuyBox 分析 / 价格追踪 */
  competitiveness: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [75, 50],
    keys: ['strong', 'medium', 'weak'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '竞争力评分。适用：BuyBoxAnalysisResult、PriceTrackResult（两处 `competitiveness_score` 必须同档，勿各写一份）。',
  },

  /** 关键词相关度：关键词挖掘 */
  relevance: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [90, 75],
    keys: ['high', 'medium', 'low'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '关键词相关度（KeywordMinerResult）。阈值偏严是有意的：相关度是「这个词值不值得投」的门槛，与泛化「评分」不是一回事。⚠️ `mock/toolExecutors.ts` 里「推荐立即投放」用的 `relevance >= 90` 是同一口径的**业务判定**（不只是颜色），改这里要同步。',
  },

  /** 商品监控健康度 —— 与 campaignHealth 是**不同指标**，勿并 */
  monitorHealth: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [80, 60, 40],
    keys: ['good', 'warn', 'weak', 'poor'],
    colors: [SEM.success, SEM.warning, SEM.orangeStrong, SEM.danger],
    note: '商品监控健康度（MonitorDashboardResult，四档）。⚠️ **与 `campaignHealth` 名字像但指标不同** —— 它由商品侧价格下跌 / 库存风险扣分得出（见 `mock/toolExecutors.ts` 的 health_score 推导），与广告 Campaign 无关，**不要合并**。',
  },

  /** 等级 A–F —— 阈值对齐后端两处实现 */
  grade: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [90, 80, 70, 60],
    keys: ['A', 'B', 'C', 'D', 'F'],
    colors: [SEM.success, SEM.primary, SEM.warning, SEM.danger, SEM.danger],
    note: '等级 A–F。**真源在后端**：`listing_generator/service.py:272-278` 与 `ad_analysis/agent_ad.py:983-986` 都是 90/80/70/60 → A/B/C/D/F。后端已经把 `grade` 算好放进返回体，前端**优先直接读 `data.grade`**；本档只用于后端没给 grade 时的回退计算。',
  },

  // ==================== 正向 · 非 0–100 量纲 ====================

  /** 标题可读性 0–10 */
  readability: {
    scale: [0, 10],
    dir: 'higher',
    cuts: [8, 6, 4],
    keys: ['优秀', '良好', '一般', '需优化'],
    colors: [SEM.success, SEM.primary, SEM.warning, SEM.danger],
    note: '标题可读性（TitleGenerator）。⚠️ **量纲是 0–10，不是 0–100** —— 并进 `score` 会把「8 分的好标题」判成「poor」。',
  },

  /** 星级 / 评分 0–5 */
  rating: {
    scale: [0, 5],
    dir: 'higher',
    cuts: [4, 3],
    keys: ['good', 'fair', 'low'],
    colors: [SEM.success, SEM.primary, SEM.warning],
    note: '星级 / 评分（0–5）。适用：ABTestGenerator 指标色、CompetitorAnalysisCard 与 CompetitorIntelEvidence 的星级。⚠️ **量纲 0–5**，勿并进 0–100 档。',
  },

  /** 情感得分 0–1 */
  sentiment: {
    scale: [0, 1],
    dir: 'higher',
    cuts: [0.7, 0.45],
    keys: ['pos', 'neu', 'neg'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '评论情感得分（ReviewSpyResult）。⚠️ **量纲 0–1 比率**，勿并进 0–100 档。',
  },

  // ==================== 领域专用口径（量纲/方向各不相同，勿互相合并） ====================

  /** 商品利润率 % */
  margin: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [60, 30],
    keys: ['high', 'mid', 'low'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '商品利润率（ProductLibrary 的 margin-badge）。⚠️ 区间同为 0–100，但阈值 60/30 与 `score`(80/60)、`competitiveness`(75/50) 都不同 —— **形似而实不同，勿并**。',
  },

  /** ROI % */
  roi: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [25, 15],
    keys: ['high', 'mid', 'low'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: 'ROI 百分比（ProfitResult 标签色）。⚠️ 25/15 与利润率的 60/30 是两个独立口径（ROI 40% 已很高，利润率 40% 只算中等），**勿并**。',
  },

  /** 广告 ACoS % —— 反向 */
  acos: {
    scale: [0, 100],
    dir: 'lower',
    // 原判定写的是 `acos <= 25 ? ok : acos <= 35 ? warn : danger`，含等号且为升序 → 必须用 cmp '<='，否则 25/35 两个边界会串档
    cmp: '<=',
    cuts: [25, 35],
    keys: ['ok', 'warn', 'danger'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '广告 ACoS（AdDashboardConfig）—— **反向：越低越好**。`keys` 直接就是 CSS 类名 + `ACOS_TAG` / `ACOS_LABEL` 的键。⚠️ 原判定用 `<=`（升序），故这里 `cmp: \'<=\'` —— 写成降序 `>=` 会让 ACoS 恰好 = 25 / 35 时串档。⚠️ 与 `roas` 是同一张表的两个指标、方向相反，**勿并**。',
  },

  /** 广告 RoAS 倍数 */
  roas: {
    scale: [0, 100],
    dir: 'higher',
    cuts: [4, 2.5],
    keys: ['ok', 'warn', 'danger'],
    colors: [SEM.success, SEM.warning, SEM.danger],
    note: '广告 RoAS（AdDashboardConfig）—— ⚠️ **量纲是倍数**（4x / 2.5x），不是百分比，**勿并进 `acos` 或 `score`**。',
  },

  // ==================== 反向 · 越大越危险 ====================

  /** 可售天数（补货紧迫度）—— 反向 */
  restockDays: {
    scale: [0, 365],
    dir: 'lower',
    cmp: '<=',
    cuts: [14, 30],
    keys: ['danger', 'warn', 'ok'],
    colors: [SEM.danger, SEM.warning, SEM.success],
    note: '库存可售天数（ReviewConfig 补货表）—— **反向：剩余天数越少越紧急**。⚠️ 量纲是「天」，**勿并进 `acos` / `usage` 这些百分比档**。',
  },

  /** 配额用量百分比（反向） */
  usage: {
    scale: [0, 100],
    dir: 'lower',
    cuts: [90, 70],
    keys: ['critical', 'high', 'ok'],
    colors: [SEM.danger, SEM.warning, SEM.success],
    note: '订阅配额用量百分比（Subscription）。⚠️ **反向：用得越多越危险** —— 千万不要并进 `score`，否则「用量 95%」会被染成绿色。',
  },

  /** CR4 市场集中度（反向） */
  cr4: {
    scale: [0, 100],
    dir: 'lower',
    cuts: [75, 50],
    keys: ['high', 'medium', 'low'],
    colors: [SEM.danger, SEM.warning, SEM.success],
    note: 'CR4 市场集中度（useChatOrchestrator 的市场份额摘要文案）—— **反向：越集中，新玩家越难切入**。目前只驱动文案（高度集中/中度集中/充分竞争），配色留作备用。',
  },

  /** 市场份额（反向） */
  share: {
    scale: [0, 100],
    dir: 'lower',
    cuts: [30, 15, 5],
    keys: ['dominated', 'competitive', 'emerging', 'open'],
    colors: [SEM.dangerStrong, SEM.orangeStrong, SEM.primary, SEM.success],
    note: '市场份额（MarketShareResult）。⚠️ **反向：份额越高说明该市场越拥挤、越难切** —— 蓝色（`emerging`）才是机会档，勿并进正向档。',
  },
} as const

/** 具名口径表（键 = 口径名） */
const BANDS: Record<keyof typeof DEFS, BandDef> = DEFS

/** 口径名。新增口径时这里会自动扩展 */
export type BandName = keyof typeof BANDS

/**
 * 分档 → 档位序号（0 = 最好 / 最安全，越大越差）。
 *
 * 实现注意：**比较方向由 `cmp` 决定**，不是恒定一种 ——
 * `cmp = '>='`（默认）时 `cuts` 降序、判定 `value >= cuts[i]`；
 * `cmp = '<='` 时 `cuts` **必须升序**、判定 `value <= cuts[i]`
 * （原写法含等号且落在「好」的一侧，不能靠改写不等式抹平，详见 `BandDef.cmp` 注释）。
 * `dir` 只影响**键名与配色顺序**、以及 NaN 兜底方向，不影响比较数学；
 * 它的价值在于**读代码的人不会把反向档当正向用**。
 *
 * 非法值（`NaN` / 非有限数）落到**最差那一档**（宁可误报，不可漏报风险）——
 * 注意 `dir` 不同「最差」的下标也不同：`higher` 是末档，`lower` 是首档。
 */
export function bandIndex(name: BandName, value: number): number {
  const b = BANDS[name]
  const v = Number(value)
  if (!Number.isFinite(v)) return b.dir === 'higher' ? b.cuts.length : 0
  const cuts = b.cuts as readonly number[]
  const ge = (b.cmp ?? '>=') === '>='
  for (let i = 0; i < cuts.length; i++) {
    if (ge ? v >= cuts[i] : v <= cuts[i]) return i
  }
  return cuts.length
}

/** 分档 → 档位名（如 `'premium'` / `'A'` / `'neg'`） */
export function bandOf(name: BandName, value: number): string {
  const b = BANDS[name]
  const keys = b.keys as readonly string[]
  return keys[bandIndex(name, value)] ?? keys[keys.length - 1]
}

/** 分档 → 档位色（CSS 变量表达式，可直接用于内联 style / SVG 属性） */
export function bandColor(name: BandName, value: number): string {
  const b = BANDS[name]
  const colors = b.colors as readonly string[]
  return colors[bandIndex(name, value)] ?? SEM.danger
}

/** 全部口径名（供自查脚本 / 文档生成用） */
export function bandNames(): BandName[] {
  return Object.keys(BANDS) as BandName[]
}

/** 取某口径的完整定义（供文档生成 / 断言用） */
export function bandDef(name: BandName): BandDef {
  return BANDS[name]
}

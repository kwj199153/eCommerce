/**
 * 颜色语义规范（Color Semantic System）
 *
 * 目标：杜绝「蓝紫黄随意分配」，让「业务含义 → 颜色」固定成一套规则。
 *
 * 使用原则：
 * 1. 同类业务含义的标签，全项目固定用同一颜色，不允许乱换。
 * 2. 操作类颜色（删除=红、编辑/详情=灰、星级/赢家=金）可保留其约定俗成含义。
 * 3. 优先用下面导出的语义常量，而不是散落的 color="blue/purple/gold"。
 *
 * ====== 语义色盘（业务 → 颜色） ======
 * 蓝  blue    —— 新品 / 蓝海 / 信息类 / 中性信息标签（ASIN、平台、AI 提取、数量统计）
 * 绿  green   —— 爆款 / 高周转 / 正常 / 成功 / 已生效
 * 红  red     —— 风险 / 淘汰 / 异常 / 差评 / 告警 / 删除
 * 橙  orange  —— 预警 / 待处理 / 即将到期 / 草稿（介于正常与风险之间）
 * 金  gold    —— 评分星级 / 领导者 / 赢家 / 排名第一
 * 灰  default —— 详情 / 编辑 / 中性 / 版本号 / 无状态
 * 紫  purple  —— SPU（规格层级）/ 多维分析 / 规格值（专属，尽量少用）
 * 青  cyan    —— 平台/渠道分类（保留给需要区分多平台场景）
 */

export type SemanticColor =
  | 'blue'
  | 'green'
  | 'red'
  | 'orange'
  | 'gold'
  | 'purple'
  | 'cyan'
  | 'geekblue'
  | 'default'

/** 新品 / 蓝海 / 信息类 → 蓝 */
export const COLOR_NEW = 'blue' as const
/** 爆款 / 高周转 / 正常 / 成功 → 绿 */
export const COLOR_HOT = 'green' as const
/** 风险 / 淘汰 / 异常 / 删除 → 红 */
export const COLOR_RISK = 'red' as const
/** 预警 / 待处理 / 即将到期 / 草稿 → 橙 */
export const COLOR_WARN = 'orange' as const
/** 评分星级 / 领导者 / 赢家 → 金 */
export const COLOR_STAR = 'gold' as const
/** 详情 / 编辑 / 中性 / 版本号 → 灰 */
export const COLOR_NEUTRAL = 'default' as const
/** SPU / 规格 / 多维分析 → 紫 */
export const COLOR_SPEC = 'purple' as const
/** 平台 / 渠道分类 → 青 */
export const COLOR_PLATFORM = 'cyan' as const

/**
 * 产品标签（tags）语义映射表。
 *
 * 产品库 / 候选库的 record.tags 是自由文本（如「蓝海」「爆款」「风险」），
 * 这里把常见业务标签归类到固定颜色，未命中的走「信息蓝」兜底。
 */
export const PRODUCT_TAG_COLOR: Record<string, SemanticColor> = {
  // 新品 / 蓝海 / 机会
  新品: 'blue',
  蓝海: 'blue',
  潜力: 'blue',
  新品机会: 'blue',
  // 爆款 / 高周转 / 表现好
  爆款: 'green',
  高周转: 'green',
  热销: 'green',
  畅销: 'green',
  // 风险 / 淘汰 / 异常
  风险: 'red',
  淘汰: 'red',
  异常: 'red',
  滞销: 'red',
  清仓: 'orange',
  // 待处理 / 预警
  待处理: 'orange',
  待评审: 'orange',
  草稿: 'orange',
  // 规格 / 层级（尽量少用）
  SPU: 'purple',
  规格: 'purple',
}

/**
 * 产品/商品状态（status）→ 颜色。
 * 统一：draft=橙、active/正常=绿、风险/异常=红、其他=灰。
 */
export const PRODUCT_STATUS_COLOR: Record<string, SemanticColor> = {
  draft: 'orange',
  草稿: 'orange',
  active: 'green',
  normal: 'green',
  正常: 'green',
  risk: 'red',
  风险: 'red',
  archived: 'default',
  归档: 'default',
}

/**
 * 根据自由文本 tag 返回语义颜色（未命中兜底「信息蓝」）。
 */
export function productTagColor(tag: string): SemanticColor {
  return PRODUCT_TAG_COLOR[tag] ?? 'blue'
}

/**
 * 根据产品 status 返回语义颜色（未命中兜底灰）。
 */
export function productStatusColor(status?: string | null): SemanticColor {
  if (!status) return 'default'
  return PRODUCT_STATUS_COLOR[status] ?? 'default'
}

/** 计数/数量统计类 tag（"N 个候选/竞品/产品"）→ 信息蓝 */
export const COLOR_COUNT = 'blue' as const
/** 模式/形态标签（"表单模式"/"多维分析"/"评论洞察"）→ 中性灰 */
export const COLOR_MODE = 'default' as const
/** 信息提示（"已绑定"/"数据源"/"AI 提取"）→ 信息蓝 */
export const COLOR_INFO = 'blue' as const

/**
 * 订阅/账号状态 → 颜色。
 * trialing=橙（试用中，介于正常与风险之间）、active=绿、cancel=橙、过期/欠费=红。
 */
export const SUBSCRIPTION_STATUS_COLOR: Record<string, SemanticColor> = {
  trialing: 'orange',
  试用中: 'orange',
  active: 'green',
  正常: 'green',
  cancel_at_period_end: 'orange',
  past_due: 'red',
  canceled: 'default',
  inactive: 'default',
}


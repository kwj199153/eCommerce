/**
 * 差评工作台 —— **展示层词汇**（第 341 轮从 `ReviewDeskConfig.vue` 外移）。
 *
 * ★ 为什么只搬这一层（这是本轮最重要的结论，不是「顺手拆一下」）
 * ------------------------------------------------------------------------
 * 本组件的**行为层**被 6 部门禁逐字钉在 `ReviewDeskConfig.vue` 里，搬走即变红：
 *   · `check-disposition-write-exit.cjs` C1/C2 —— 8 个写 API 的 UI 出口 == 1，
 *     且 `.ts` 层 import 数必须为 0（HITL 唯一把关点）；
 *   · `check-review-risk-view.cjs` R13/R14/R11 —— 清单指纹 `listKeyOf`、`reload`
 *     里的条件 `clearRisk()`、证据块守卫 `showRiskEvidence` 都必须在面板内；
 *   · `check-review-chat-entries.cjs` R1/R2 —— `window.dispatchEvent` 恰好 1 处、
 *     出口函数与入口数对齐；
 *   · `check-disposition-execution-honesty.cjs` H5/H6/H8 —— 回执按钮、`runBackfill`
 *     的原因分流、`const CHANNEL_META` 的「不调用平台接口」说明；
 *   · `check-review-desk-systemic.cjs` S2 —— 两个判定端点的调用点。
 * ⇒ 能搬的是**没有任何门禁消费、也不持有响应式状态**的纯词汇：常量表 + 纯格式化
 *   函数。搬它们只改「定义在哪」，不改任何行为 —— 这是唯一能同时满足
 *   「减行数」与「零行为变化」的切法。
 *
 * ★ 本文件必须保持「纯」
 * ------------------------------------------------------------------------
 * 不许 import 任何 api **写**函数（C2 会把 `.ts` 层打红），不许 import
 * `vue` 的 `ref` / `computed` —— 一旦引入就退化成第二个状态源。
 * 允许 import **类型**与只读常量表。
 */
import {
  DISPOSITION_STATUS_LABELS,
  CAUSE_LABELS,
  ATTRIBUTABLE_CAUSES,
  type DispositionStatus,
  type SystemicVerdict,
  type CompensationRule,
  type Disposition,
} from '@/api/trade'

/** 差评状态中文名 */
export const REVIEW_STATUS_LABELS: Record<string, string> = {
  new: '待处理',
  triaged: '已归因',
  replied: '已回复',
  closed: '已结案',
}

/** 补偿类型中文名 —— 额度为 0 时也要能把「升级处理」这类无额度的通道说清楚 */
export const COMPENSATION_TYPE_LABELS: Record<string, string> = {
  coupon: '优惠券',
  refund: '退款',
  reship: '重发',
  escalate: '升级处理',
}

/** 台账状态筛选项 —— 与 `DISPOSITION_STATUS_LABELS` 同源，不手写第二份 */
export const DISPOSITION_STATUS_OPTIONS = (
  Object.keys(DISPOSITION_STATUS_LABELS) as DispositionStatus[]
).map((s) => ({ label: DISPOSITION_STATUS_LABELS[s], value: s }))

/** 四个视图的文案与提示 —— ★ 顺序即 tab 顺序，行为基线探针按此逐字对账 */
export const VIEWS = [
  { key: 'recent', label: '近期差评', icon: '📉', hint: '本店时间窗内的中差评' },
  { key: 'orphan', label: '未关联产品', icon: '🧩', hint: 'ASIN / SKU 码对不上本店任何产品的差评' },
  { key: 'ledger', label: '处置台账', icon: '📋',
    hint: '已发起的处置：草稿在这里由人批准 / 核准（平台执行需人工完成后登记回执）' },
  { key: 'rules', label: '补偿规则', icon: '⚙️',
    hint: '给每个归因配补偿方案：金额由这里唯一算出，处置草稿按它现算' },
] as const

export type ViewKey = (typeof VIEWS)[number]['key']

/** 判定结论的语义色（与 `DISPOSITION_STATUS_COLORS` 同一套取值口径） */
export const SYSTEMIC_COLORS: Record<SystemicVerdict, string> = {
  isolated: 'green',
  repeat: 'orange',
  systemic: 'red',
  unknown: 'default',
}

/** ★ 必须显式声明成 `Record<string, string>`：字面量对象的键会被推成
 *   `'approve' | 'reject' | 'issue'`，而 `pendingAct` 的合法默认值是 `''`
 *   ⇒ 拿 `''` 去索引会直接 TS2339（不是 lint 洁癖，是真编译不过）。 */
export const CONFIRM_TITLES: Record<string, string> = {
  approve: '批准这条处置？',
  reject: '驳回这条处置？',
  issue: '核准这条处置？（不可逆）',
  receipt: '登记平台执行回执？',
}
export const CONFIRM_TEXTS: Record<string, string> = {
  approve: '批准后进入待核准状态；核准仍需你再点一次。',
  reject: '驳回后这条处置会标记为 rejected，可以重新生成草稿。',
  issue: '核准后生成券码并写进回复，不可撤销。'
    + '★ 本步只在本地登记 —— 不会调用任何平台接口，不会真的退款 / 发券；'
    + '平台侧动作需人工去后台执行，做完回来登记回执。',
  receipt: '只有在平台上真的做完（发券 / 退款 / 补发）之后才登记。'
    + '登记后进入终态，不可再改。',
}

/** 归因下拉选项（补归因与规则编辑器共用；**不含 unknown**） */
export const CAUSE_OPTIONS = ATTRIBUTABLE_CAUSES.map((c) => ({
  value: c,
  label: CAUSE_LABELS[c],
}))

/** 补偿方式下拉选项（与后端 `ACTION_TYPES` 对齐） */
export const ACTION_TYPE_OPTIONS = [
  { value: 'coupon', label: '优惠券' },
  { value: 'refund', label: '退款' },
  { value: 'none', label: '不补偿' },
]

/** 币种下拉（本仓电商语境默认 USD，可扩展） */
export const CURRENCY_OPTIONS = [
  { value: 'USD', label: 'USD' },
  { value: 'CNY', label: 'CNY' },
]

/** 规则命中条件的展示文案（列表行用） */
export function ruleCondText(r: CompensationRule): string {
  const c = r.conditions || {}
  const parts: string[] = []
  if (typeof c.max_rating === 'number') parts.push(`≤${c.max_rating}星`)
  if (typeof c.min_delay_days === 'number') parts.push(`延迟≥${c.min_delay_days}天`)
  if (c.verified_purchase) parts.push('仅已购')
  return parts.length ? parts.join(' · ') : '无条件'
}

/** 规则补偿方案的展示文案（列表行用） */
export function ruleActionText(r: CompensationRule): string {
  const a = r.action || {}
  if (a.type === 'none' || !a.type) return '不补偿'
  const amt = typeof a.amount === 'number' ? `${a.amount} ${a.currency || 'USD'}` : ''
  return a.type === 'coupon' ? `券 ${amt}` : a.type === 'refund' ? `退 ${amt}` : amt || '—'
}

/** 补偿金额文案 —— ★ 退款可以按**百分比**给（`refund_percent`），要先赛过金额 */
export function compensationText(comp: Record<string, any> | null | undefined): string {
  if (!comp) return '—'
  const type = String(comp.type || '')
  const amount = Number(comp.amount || 0)
  const currency = comp.currency || 'USD'
  if (type === 'refund' && comp.refund_percent) return `退款 ${comp.refund_percent}%`
  const label = COMPENSATION_TYPE_LABELS[type] || type
  return amount > 0 ? `${label} ${amount} ${currency}` : label || '—'
}

/** 台账行右侧的动作名 —— 用户靠它判断「点进去能不能改」 */
export function rowActionLabel(d: Disposition): string {
  return d.status === 'proposed' || d.status === 'rejected' ? '编辑' : '查看'
}

/** 台账行的用途提示 */
export function rowHint(d: Disposition): string {
  return rowActionLabel(d) === '编辑'
    ? '点击打开处置：可改通道与回复措辞（金额由规则算，不可改）'
    : '点击打开处置：已进入' + DISPOSITION_STATUS_LABELS[d.status] + '，内容只读'
}

/** 时间戳裁到分钟（列表行用） */
export function shortTime(v: string): string {
  return (v || '').replace('T', ' ').slice(0, 16)
}

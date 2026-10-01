/**
 * 订单追踪 · **渲染真源**（第 292 轮）
 *
 * ★ 为什么要有这个文件：同一份订单数据此前有 **四处各写一份**渲染口径 ——
 *   ① 对话通道 `composables/chat/replies/customerService.ts::renderOrderTracking`
 *      （Markdown 表格，字段只有 7 个，**连运单号都没进模板**）；
 *   ② 工具卡 `components/ChatPanel/results/OrderTrackResult.vue`
 *      （结构化卡片，有运单号/承运商，**但没渲染轨迹**）；
 *   ③ 结果摘要 `composables/chat/resultSummary.ts` 的 `order-track` 分支
 *      （又一份 bullet，字段清单与 ①② 都不同）；
 *   ④ 工具配置面板 `components/TaskConfigPanel/configs/OrderTrackConfig.vue`
 *      （「查询结果包含」硬编码 4 条，还写着「运单号不在接口里」）。
 *   四份清单只靠人肉同步 ⇒ 后端加一个字段要改四处、漏一处就有一路看不见，
 *   用户还会被过期文案误导 —— 这正是本仓反复踩的「同一判定两份实现」病。
 *
 * ⇒ 现在**字段清单只有 `ORDER_FIELD_SPECS` 这一张表**；四个消费方都从它派生：
 *   `orderFields()`（有值才成行）、`orderFieldPreview()`（可能的字段清单）、
 *   `renderOrderTrackingText()`（对话正文）、`orderSummaryLines()`（结果摘要）。
 *
 * ★ 字段清单的**对账锚点**：后端 `_map_order_from_trade`
 *   （`backend/modules/customer_service/agent_cs.py`）是自有订单库那条链的唯一
 *   映射口径，它产出的业务键必须在本文件的表里出现。平台适配层版
 *   `_map_order_info` 是其**子集**（无运单号/承运商/轨迹，见 `ownDbOnly`），
 *   本文件对缺键一律**留空不渲染**，绝不补值。
 */

/** 订单状态 → 展示三态。 */
export type OrderTone = 'delivered' | 'shipped' | 'processing' | 'unknown'

/** 字段分组：`header` 只在抬头，`base` 走基础信息区，`logistics` 走物流区。 */
export type OrderFieldGroup = 'header' | 'base' | 'logistics'

/**
 * 后端订单状态 → 展示三态。
 *
 * ★ 后端 `order.status` 是 **SP-API 原始枚举**（Pending / Unshipped /
 *   PartiallyShipped / Shipped / DeliveredToCarrier / Canceled，见
 *   `backend/platforms/amazon/sp_api/models.py::OrderStatus`），而自有库那条链
 *   给的是小写库内码。两路都要认 ⇒ 一律 `toLowerCase()` 后查表。
 */
const TONE_OF: Record<string, OrderTone> = {
  pending: 'processing',
  unshipped: 'processing',
  partiallyshipped: 'shipped',
  shipped: 'shipped',
  deliveredtocarrier: 'shipped',
  delivered: 'delivered',
  canceled: 'unknown',
  cancelled: 'unknown',
  // 历史 mock 用过的 key（兼容旧载荷）
  processing: 'processing',
}

const ICON_OF: Record<OrderTone, string> = {
  delivered: '✅',
  shipped: '🚚',
  processing: '⏳',
  unknown: '📦',
}

export function orderToneOf(status?: string): OrderTone {
  return TONE_OF[(status || '').toLowerCase()] || 'unknown'
}

export function orderStatusIcon(status?: string): string {
  return ICON_OF[orderToneOf(status)]
}

/**
 * 金额文案。
 *
 * ★ 不写 `Number(total || 0).toFixed(2)` —— 那会把「后端没给金额」渲染成
 *   `$0.00`（编造一个具体数字），且真实币种未必是 USD。后端已给 `total_text`
 *   （带币种、查不到时是「—」），优先用它。
 *
 * ★ 第 357 轮：`orderFields()` 的 `total_text` 走 `text(orderAmountText(o))`
 *   ⇒ 这里返回的 `'—'` 在**清单**里被归一成 `''`（不成行），与其它字段同口径。
 *   本函数自身仍返回 `'—'`（它是「给人看的金额文案」，语义未变）。
 */
export function orderAmountText(order: any): string {
  if (order?.total_text) return order.total_text
  return order?.total == null ? '—' : String(Number(order.total).toFixed(2))
}

/** 订单头部（订单号 + 状态）—— 卡片、对话正文与摘要共用。 */
export interface OrderHeader {
  orderId: string
  statusCode: string
  statusText: string
  tone: OrderTone
  icon: string
}

export function orderHeader(order: any): OrderHeader {
  const statusCode = order?.status || ''
  return {
    orderId: order?.order_id || '—',
    statusCode,
    statusText: order?.status_text || statusCode || '未知状态',
    tone: orderToneOf(statusCode),
    icon: orderStatusIcon(statusCode),
  }
}

const DASH = '—'

/**
 * 有值才成行：空串 / undefined / null / 'N/A' / '—' 一律丢弃（**不补占位**）。
 *
 * ★ 第 357 轮起**无例外**：`total_text` 曾绕过本函数直接返回 `'—'`
 *   （界面上「金额 | —」永远存在），现已与其它字段统一走本函数。
 */
function text(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = String(v).trim()
  if (!s || s === 'N/A' || s === DASH) return ''
  return s
}

/** 正整数（天数 / 件数）∈ 有效范围才成行。 */
function positiveInt(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : null
}

/**
 * 字段规格 —— **唯一真源**。
 *
 * 数组顺序即展示顺序；`group` 决定落在抬头 / 基础信息区 / 物流区。
 * `ownDbOnly` 标的是「只有自有订单库那条链才给」的字段（平台适配层给不出）
 * —— 配置面板的「查询结果包含」靠它如实说明，不再写「运单号不在接口里」。
 */
interface OrderFieldSpec {
  /** 后端字段名（对账用） */
  key: string
  label: string
  group: OrderFieldGroup
  /** 取值器 —— 空串 = 这一项这次没有值，不进清单；`header` 三项由 `orderHeader()` 承载 */
  pick?: (o: any) => string
  /** 等宽显示（机器码） */
  mono?: boolean
  /** 需要视觉强调 */
  emphasis?: boolean
  /** 结果摘要行是否带上 */
  summary?: boolean
  /** 只有自有订单库那条链才有 */
  ownDbOnly?: boolean
}

const ORDER_FIELD_SPECS: OrderFieldSpec[] = [
  // ── 抬头（由 `orderHeader()` 渲染，不参与 `orderFields()`）─────────────
  { key: 'order_id', label: '订单号', group: 'header', mono: true, summary: true },
  { key: 'status_text', label: '订单状态', group: 'header', summary: true },

  // ── 基础信息 ──────────────────────────────────────────────────────────
  { key: 'created_at', label: '下单时间', group: 'base', pick: (o) => text(o?.created_at) },
  { key: 'product_name', label: '商品', group: 'base', summary: true, pick: (o) => text(o?.product_name) },
  {
    key: 'quantity', label: '数量', group: 'base', summary: true,
    pick: (o) => { const n = positiveInt(o?.quantity); return n === null ? '' : `${n} 件` },
  },
  {
    key: 'total_text', label: '金额', group: 'base', emphasis: true, summary: true,
    // ★ 第 357 轮统一口径：`orderAmountText()` 查不到金额时返回 `'—'`（非空），
    //   直接当值会让「金额 | —」这一行**永远存在** —— 成为「有值才成行」
    //   的唯一例外。过一道 `text()` ⇒ `'—'` / `'N/A'` / 空串一律不成行。
    pick: (o) => text(orderAmountText(o)),
  },
  { key: 'shipping_to', label: '收货地', group: 'base', summary: true, pick: (o) => text(o?.shipping_to) },

  // ── 物流轨迹（`ownDbOnly`：平台适配层 `_map_order_info` 全都不产出）────
  {
    key: 'estimated_delivery', label: '预计送达', group: 'logistics', emphasis: true, summary: true,
    pick: (o) => { const v = text(o?.estimated_delivery); return v ? `${v}（按发货状态估算）` : '' },
  },
  {
    key: 'tracking_number', label: '快递单号', group: 'logistics', mono: true, summary: true,
    ownDbOnly: true, pick: (o) => text(o?.tracking_number),
  },
  {
    key: 'carrier', label: '承运商', group: 'logistics', summary: true,
    ownDbOnly: true, pick: (o) => text(o?.carrier),
  },
  {
    key: 'ship_status_text', label: '物流状态', group: 'logistics',
    ownDbOnly: true, pick: (o) => text(o?.ship_status_text),
  },
  {
    key: 'shipped_at', label: '发货时间', group: 'logistics',
    ownDbOnly: true, pick: (o) => text(o?.shipped_at),
  },
  {
    key: 'delivered_at', label: '签收时间', group: 'logistics',
    ownDbOnly: true, pick: (o) => text(o?.delivered_at),
  },
  {
    key: 'transit_days', label: '运输时长', group: 'logistics',
    ownDbOnly: true,
    pick: (o) => { const n = positiveInt(o?.transit_days); return n === null ? '' : `${n} 天` },
  },
  {
    key: 'delay_days', label: '迟到天数', group: 'logistics', emphasis: true,
    ownDbOnly: true,
    pick: (o) => { const n = positiveInt(o?.delay_days); return n === null ? '' : `晚到 ${n} 天` },
  },
  {
    key: 'last_location', label: '最新位置', group: 'logistics',
    ownDbOnly: true, pick: (o) => text(o?.last_location),
  },
  {
    key: 'last_event_text', label: '最新动态', group: 'logistics',
    ownDbOnly: true, pick: (o) => text(o?.last_event_text),
  },
]

/** 一个可渲染字段 —— 标签与取值都在真源里定死，消费方只管摆版面。 */
export interface OrderField {
  key: string
  label: string
  value: string
  mono?: boolean
  emphasis?: boolean
  inSummary?: boolean
  group: Exclude<OrderFieldGroup, 'header'>
}

/** 订单字段清单（**有值才成行，无例外**）—— 四个消费方共用的唯一真源。 */
export function orderFields(order: any): OrderField[] {
  const out: OrderField[] = []
  for (const s of ORDER_FIELD_SPECS) {
    if (s.group === 'header' || !s.pick) continue
    const value = s.pick(order)
    if (!value) continue
    out.push({
      key: s.key, label: s.label, value, mono: s.mono,
      emphasis: s.emphasis, inSummary: s.summary, group: s.group,
    })
  }
  return out
}

/** 「查询结果可能包含哪些字段」的封面清单 —— 给配置面板用（**不是第二份手写清单**）。 */
export interface OrderFieldPreview {
  key: string
  label: string
  group: OrderFieldGroup
  /** 只有自有订单库那条链才会给；平台接口不返回这类字段 */
  ownDbOnly: boolean
}

export function orderFieldPreview(): OrderFieldPreview[] {
  return ORDER_FIELD_SPECS.map((s) => ({
    key: s.key, label: s.label, group: s.group, ownDbOnly: Boolean(s.ownDbOnly),
  }))
}

/** 归一的订单视图 —— 消费方都从这里取，不再各自解 `payload.order`。 */
export interface OrderTrackingView {
  found: boolean
  message: string
  orderId: string
  header: OrderHeader
  base: OrderField[]
  logistics: OrderField[]
  /** 物流组有没有内容（决定要不要渲染整块） */
  hasLogistics: boolean
  /** 取数来源（`order.data_source`）—— 演示数据不得冒充真实数据 */
  dataSource: string
  isMock: boolean
}

export function buildOrderTrackingView(payload: any): OrderTrackingView {
  const order = payload?.order
  const found = Boolean(payload?.found && order)
  const fields = found ? orderFields(order) : []
  return {
    found,
    message: payload?.message || '',
    orderId: found ? (order?.order_id || DASH) : DASH,
    header: found ? orderHeader(order) : {
      orderId: DASH, statusCode: '', statusText: '', tone: 'unknown', icon: ICON_OF.unknown,
    },
    base: fields.filter((f) => f.group === 'base'),
    logistics: fields.filter((f) => f.group === 'logistics'),
    hasLogistics: fields.some((f) => f.group === 'logistics'),
    dataSource: (found && order?.data_source) || '',
    isMock: Boolean(found && order?.is_mock_data),
  }
}

/**
 * 演示数据脚注 —— 空串表示「真实数据，无需提示」。
 *
 * ★ 本仓硬口径：`is_mock_data` 为真时，界面上必须看得见，不许让演示数据
 *   冒充真实订单。此处只产出文案，怎么摆由消费方决定。
 */
export function orderSourceNote(view: OrderTrackingView): string {
  if (!view.isMock) return ''
  return `⚠️ 演示数据（来源：${view.dataSource || 'mock_seed'}）—— 非真实订单`
}

/**
 * 对话通道渲染：把结构化出参写成 Markdown 正文。
 *
 * ★ 为什么必须自己渲染：后端返回的是结构化 `{found, order, message}`，
 *   而会话结论卡注册表（`results/conversation/registry.ts`）里**没有**
 *   `order_info` ⇒ 不渲染的话用户只会看到「订单信息获取成功」六个字，
 *   看不到订单内容。
 */
export function renderOrderTrackingText(payload: any): string {
  const view = buildOrderTrackingView(payload)
  if (!view.found) {
    return `📦 **未能查到该订单**\n\n${view.message || '请确认订单号是否正确。'}`
  }

  const lines: string[] = ['**订单信息** 📦', '', '| 项目 | 详情 |', '|------|------|']
  lines.push(`| 订单号 | \`${view.header.orderId}\` |`)
  lines.push(`| 状态 | **${view.header.statusText}** |`)
  for (const f of view.base) {
    lines.push(`| ${f.label} | ${f.mono ? '`' + f.value + '`' : f.value} |`)
  }

  if (view.hasLogistics) {
    lines.push('', '**物流** 🚚')
    for (const f of view.logistics) {
      lines.push(`- ${f.label}：${f.mono ? '`' + f.value + '`' : f.value}`)
    }
  }

  const note = orderSourceNote(view)
  if (note) lines.push('', `> ${note}`)
  return lines.join('\n')
}

/** 摘要行（结果卡上方那句 bullet 列表）—— 取 `summary` 字段，避免第二份清单。 */
export function orderSummaryLines(payload: any): string[] {
  const view = buildOrderTrackingView(payload)
  if (!view.found) {
    return ['📦 **订单查询未完成**', '', view.message || '未能查询到该订单，请确认订单号是否正确。']
  }
  const lines = ['📦 **订单查询完成**', '']
  lines.push(`- 订单号：${view.header.orderId}`)
  lines.push(`- 状态：${view.header.statusText}`)
  for (const f of [...view.base, ...view.logistics]) {
    if (f.inSummary) lines.push(`- ${f.label}：${f.value}`)
  }
  const note = orderSourceNote(view)
  if (note) lines.push(`- ${note}`)
  lines.push('', '完整信息已展示在上方。')
  return lines
}

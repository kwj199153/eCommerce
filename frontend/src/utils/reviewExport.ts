/**
 * 复盘报告 → 导出表格的**摊平唯一真源**（第 266 轮）
 *
 * ============================================================================
 * ★ 为什么要有这个文件
 * ============================================================================
 * 导出的摊平口径有**两个消费点**：
 *   ① 对话里的结果卡（`ReviewReportCard.vue`）底部的「导出」；
 *   ② 资料库 → 复盘库详情抽屉（`ReviewLibrary.vue`）的「导出」。
 * 两处各写一份摊平逻辑的后果，与「同一类型在两个地方叫两个中文名」同族：
 * **谁都不报错**，但同一份复盘从两个入口导出的表格内容不一样。
 * 本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到。
 *
 * ★ 口径（(b)：`类型 | 条目 | 数值` 三列 + JSON 完整快照）：
 *   · 表格 = 把报告里**所有**条目摊平成一列「条目」+ 一列「数值」；
 *   · 完整嵌套结构交给 JSON 格式 —— `jsonData` 一律是后端**原样**的
 *     `ReviewReport`，本文件**不重算**任何数值（重算会拿到另一批数字）。
 *
 * ★★ 摊平必须绕开三个已实测的坑（三个都是「界面看不出、导出会丢」）：
 *   ① `insights` / `actions` 后端**六项能力全是空数组** ⇒ 界面上「观察」
 *      「建议动作」两块**恒不渲染**。导出**不能**因此把它们写死成空 ——
 *      schema 允许多种写法（`string` / `{text}` / `{title}` / `{content}` /
 *      `{priority, content}`），后端哪天开始给值，导出必须已经接得住。
 *   ② `details` 里 `sales` / `ad` / `commission` 这几块**界面完全不渲染**
 *      （结果卡与详情抽屉都只渲染 `campaigns`/`products`/`sku_rank`/`items`
 *      明细表）⇒ 导出若不纳入，老板拿到的表格比界面**还少**信息。
 *   ③ 旧 `toTextList` 取 `x?.text ?? x?.title`，遇上 `{priority, content}`
 *      会得到空串 ⇒ 整个「建议动作」被**整行丢掉**。这里由 `textListOf`
 *      收唯一实现并修掉该洞（两处消费点都改import它）。
 *
 * ★ 依赖层级说明：`money` / `num` 住在
 *   `components/ChatPanel/results/conversation/format.ts`（会话结论卡共用）。
 *   复盘库页面本来就已经从这个模块取格式化函数，这里沿用同一个真源，
 *   而不是在 utils 里再造一份「金额怎么显示」的规则。
 */

import { money, num } from '@/components/ChatPanel/results/conversation/format'
import { todayStamp } from '@/utils/download'

// ==================== 表头 ====================

/**
 * 导出表头（(b) 口径三列）。
 *
 * ★ 类型必须是 `string[]`（不能是 `as const` 只读元组）—— `ExportModal`
 *   的 prop 就是 `string[]`，传只读元组会被 `vue-tsc` 拒。
 */
export const REVIEW_EXPORT_COLUMNS: string[] = ['类型', '条目', '数值']

/** 库存状态内部标识 → 中文（绝不把 CRITICAL / STAGNANT 这类内部值示人） */
const HEALTH_CN: Record<string, string> = {
  HEALTHY: '健康',
  WARNING: '预警',
  CRITICAL: '断货',
  STAGNANT: '滞销',
  UNKNOWN: '未知',
}

// ==================== 格式化（与界面同口径）====================

/**
 * 指标渲染：`unit` 是**唯一的**格式化依据（USD 走金额、% 走后缀、其余带单位）。
 *
 * ★ 与结果卡 / 详情抽屉顶部那排格子**逐字同口径** —— 导出里的数字必须和
 *   屏幕上看到的一模一样，否则老板会对不上账。
 */
export function metricTextOf(m: any): string {
  const v = Number(m?.value)
  if (!Number.isFinite(v)) return '—'
  if (m?.unit === 'USD') return money(v)
  if (m?.unit === '%') return `${v}%`
  return m?.unit ? `${num(v)} ${m.unit}` : num(v)
}

/**
 * 库存状态 → 中文。**未知标识回「—」**（与本仓既有界面同口径）：
 * 把一个没见过的英文标识直接示人，等于把内部枚举泄到给老板看的文件里；
 * 原始值在 JSON 快照里仍然完整保留。
 */
export function healthStatusText(s: unknown): string {
  return HEALTH_CN[String(s ?? '')] || '—'
}

/**
 * 从一条**异构**的文本条目里取正文。
 *
 * 兼容 `string` / `{text}` / `{title}` / `{content}` 四种写法 —— 后端 schema
 * 是 `insights: string[]` + `actions: {priority?, content?}[]`，但同一个
 * `details` 家族已经出现过多种写法，这里按「有哪个取哪个」而不猜默认值。
 */
export function textOf(x: any): string {
  if (x === null || x === undefined) return ''
  if (typeof x === 'string') return x.trim()
  if (typeof x === 'object') {
    const v = x.text ?? x.title ?? x.content
    return v === null || v === undefined ? '' : String(v).trim()
  }
  return String(x).trim()
}

/** 文本列表 → 字符串数组（保留后端给的顺序，丢掉空项）。 */
export function textListOf(v: any): string[] {
  if (!Array.isArray(v)) return []
  return v.map((x) => textOf(x)).filter(Boolean)
}

/**
 * `actions` 的规范化形态：**同时**保住 `priority` 与 `content`。
 *
 * ★ 导出要用到 `priority`（条目里带上），而界面只显示正文 —— 所以这里给
 *   结构化形态，消费方各取所需，而不是让两边各写一次解析。
 * ★ `priority` **不做中英映射**：后端目前恒不给值，词汇表未知 ——
 *   把没见过的值翻译成「高/中/低」是在编造（本仓「不猜默认」那条）。
 */
export function actionListOf(v: any): Array<{ priority: string; content: string }> {
  if (!Array.isArray(v)) return []
  return v
    .map((x) => {
      if (typeof x === 'string') return { priority: '', content: x.trim() }
      const priority = x?.priority === null || x?.priority === undefined ? '' : String(x.priority).trim()
      // 正文取 `content` 优先，再退到 text / title（兼容其它写法）
      const content = x?.content ?? x?.text ?? x?.title
      return {
        priority,
        content: content === null || content === undefined ? '' : String(content).trim(),
      }
    })
    .filter((a) => a.content || a.priority)
}

// ==================== details 的字段表 ====================
//
// ★ 为什么要把字段名写成「表」而不是在循环里 if/else：
//   `details` 的键是后端 schema 的一部分，写漏一个键的后果是**导出静默少一列**
//   （没有任何报错）。写成表以后，新增字段只改一处，且能对着后端
//   `service.py` 的 `_sum_sales` / `_sum_ad` 逐字核对。

type CellFmt = 'money' | 'pct' | 'num' | 'raw' | 'health'

interface FieldSpec {
  key: string
  label: string
  fmt: CellFmt
}

/** `_sum_sales`（service.py）的字段 + 中文名 */
const SALES_SUM_FIELDS: FieldSpec[] = [
  { key: 'units', label: '订单数', fmt: 'num' },
  { key: 'revenue', label: '销售额', fmt: 'money' },
  { key: 'refunds', label: '退款', fmt: 'money' },
  { key: 'net_revenue', label: '净收入', fmt: 'money' },
  { key: 'estimated_profit', label: '预估利润', fmt: 'money' },
]

/** `_sum_ad`（service.py）的字段 + 中文名 */
const AD_SUM_FIELDS: FieldSpec[] = [
  { key: 'impressions', label: '曝光', fmt: 'num' },
  { key: 'clicks', label: '点击', fmt: 'num' },
  { key: 'spend', label: '广告花费', fmt: 'money' },
  { key: 'orders', label: '广告订单', fmt: 'num' },
  { key: 'sales', label: '广告销售额', fmt: 'money' },
  { key: 'acos', label: 'ACoS', fmt: 'pct' },
  { key: 'roas', label: 'ROAS', fmt: 'num' },
  { key: 'ctr', label: 'CTR', fmt: 'pct' },
]

/**
 * 明细字段表。
 *
 * `idKey` = 一行记录的**主标识**字段：它出现在「条目」列的前缀里
 * （`<标识> · <字段名>`），所以**不再单独出一行自己的值**（否则会得到
 * 「ASIN B0XXX · ASIN」这种同义重复）。主标识取不到时退成「第 N 条」。
 */
interface DetailSpec {
  /** `details` 里的数组键 */
  listKey: string
  /** 用作「条目」前缀的主标识字段 */
  idKey: string
  fields: FieldSpec[]
}

const DETAIL_SPECS: DetailSpec[] = [
  {
    listKey: 'campaigns',
    idKey: 'campaign',
    fields: [
      { key: 'spend', label: '花费', fmt: 'money' },
      { key: 'sales', label: '销售额', fmt: 'money' },
      { key: 'acos', label: 'ACoS', fmt: 'pct' },
      { key: 'roas', label: 'ROAS', fmt: 'num' },
      { key: 'cpc', label: 'CPC', fmt: 'money' },
      { key: 'ctr', label: 'CTR', fmt: 'pct' },
      { key: 'grade', label: '评级', fmt: 'raw' },
    ],
  },
  {
    listKey: 'products',
    idKey: 'asin',
    fields: [
      { key: 'units', label: '销量', fmt: 'num' },
      { key: 'revenue', label: '营收', fmt: 'money' },
      { key: 'profit', label: '利润', fmt: 'money' },
      { key: 'rating', label: '评分', fmt: 'num' },
      { key: 'bsr_rank', label: 'BSR 排名', fmt: 'num' },
      { key: 'days_supply', label: '库存天数', fmt: 'num' },
      { key: 'health_status', label: '库存状态', fmt: 'health' },
    ],
  },
  {
    listKey: 'sku_rank',
    idKey: 'asin',
    fields: [
      { key: 'units', label: '销量', fmt: 'num' },
      { key: 'revenue', label: '营收', fmt: 'money' },
      { key: 'profit', label: '利润', fmt: 'money' },
    ],
  },
  {
    listKey: 'items',
    idKey: 'asin',
    fields: [
      { key: 'sku', label: 'SKU', fmt: 'raw' },
      { key: 'fulfillable', label: '可售', fmt: 'num' },
      { key: 'inbound', label: '在途', fmt: 'num' },
      { key: 'days_supply', label: '库存天数', fmt: 'num' },
      { key: 'health_status', label: '库存状态', fmt: 'health' },
    ],
  },
]

// ==================== 单元格取值 ====================

/** 值是否"存在"（`null` / `undefined` / 空串都不算 —— 与 `?? `语义区分开）。 */
function present(v: unknown): boolean {
  return v !== null && v !== undefined && v !== ''
}

function cellText(v: unknown, fmt: CellFmt): string {
  if (fmt === 'health') return healthStatusText(v)
  if (!present(v)) return '—'
  if (fmt === 'raw') return String(v)
  const n = Number(v)
  // 非数字（后端偶发给了字符串）原样示人，不吞成「—」——吞了就是丢信息
  if (!Number.isFinite(n)) return String(v)
  if (fmt === 'money') return money(n)
  if (fmt === 'pct') return `${n}%`
  return num(n)
}

// ==================== 主函数 ====================

/**
 * 把一份 `ReviewReport` 摊平成导出表格的行。
 *
 * 顺序固定为：**结论 → 指标 → 汇总 → 明细 → 观察 → 建议**。
 * 不按 `report_type` 分支 —— `report_type` 与 `details` 的键是同一份信息，
 * 按类型分支等于把同一判定写两份（结果卡/详情抽屉已有同样的取舍）。
 *
 * @param data 后端给的报告**原样**（对话里的 `result.data`、复盘库的 `detail.data`）
 */
export function reviewReportToRows(data: any): (string | number)[][] {
  const rows: (string | number)[][] = []
  const details: any =
    data && typeof data.details === 'object' && data.details !== null ? data.details : {}

  // ── 1) 一句话结论 ─────────────────────────────────────────────
  // ★ 界面是渲染它的，但它是个「字符串」而不是「条目」；不放进表格会让
  //   Excel 里没有标题行 —— 而它恰恰是这份复盘里最像人话的一句。
  const summary = String(data?.summary ?? '').trim()
  if (summary) rows.push(['结论', '一句话结论', summary])

  // ── 2) 指标 ──────────────────────────────────────────────────
  const metrics: any[] = Array.isArray(data?.metrics) ? data.metrics : []
  for (const m of metrics) {
    rows.push(['指标', String(m?.label ?? '—'), metricTextOf(m)])
  }

  // ── 3) 汇总（界面**完全不渲染**的那几块）────────────────────
  pushSumBlock(rows, '销售', details.sales, SALES_SUM_FIELDS)
  pushSumBlock(rows, '广告', details.ad, AD_SUM_FIELDS)
  // `profit_audit` 的标量；`weekly_report` 的两个派生标量
  if (present(details.commission)) rows.push(['汇总', '平台佣金(估)', cellText(details.commission, 'money')])
  if (present(details.refund_rate)) rows.push(['汇总', '退货率', cellText(details.refund_rate, 'pct')])
  if (present(details.stock_risk_count)) {
    rows.push(['汇总', '库存风险 SKU 数', cellText(details.stock_risk_count, 'num')])
  }

  // ── 4) 明细 ──────────────────────────────────────────────────
  for (const spec of DETAIL_SPECS) {
    pushDetailBlock(rows, details[spec.listKey], spec)
  }

  // ── 5) 观察 ──────────────────────────────────────────────────
  textListOf(data?.insights).forEach((t, i) => {
    rows.push(['观察', `第 ${i + 1} 条`, t])
  })

  // ── 6) 建议动作 ──────────────────────────────────────────────
  // ★ 优先级写进“条目”列而不是新开一列：(b) 口径就是三列；也**不按优先级重排**
  //   —— 顺序是后端给的，重排等于替老板做了一次判断（越权）。
  actionListOf(data?.actions).forEach((a, i) => {
    const entry = a.priority ? `第 ${i + 1} 条（优先级 ${a.priority}）` : `第 ${i + 1} 条`
    rows.push(['建议', entry, a.content || '—'])
  })

  return rows
}

function pushSumBlock(
  rows: (string | number)[][],
  group: string,
  block: any,
  fields: FieldSpec[]
): void {
  if (!block || typeof block !== 'object') return
  for (const f of fields) {
    // ★ 用 `in` 判存在而不是判真值：`0` 是**有意义的数据**（真实的花费/订单数），
    //   用真值判断会把「确实是 0」整行丢掉。
    if (!(f.key in block)) continue
    rows.push(['汇总', `${group} · ${f.label}`, cellText(block[f.key], f.fmt)])
  }
}

function pushDetailBlock(rows: (string | number)[][], list: any, spec: DetailSpec): void {
  if (!Array.isArray(list) || !list.length) return
  list.forEach((row, i) => {
    if (!row || typeof row !== 'object') return
    const id = String(row[spec.idKey] ?? '').trim() || `第 ${i + 1} 条`
    for (const f of spec.fields) {
      if (!(f.key in row)) continue
      rows.push(['明细', `${id} · ${f.label}`, cellText(row[f.key], f.fmt)])
    }
  })
}

// ==================== 文件名 ====================

/**
 * 导出文件名前缀：`复盘_<类型中文名>_<周期末日>`。
 *
 * ★ 周期末日必须进**文件名**而不是往 JSON 快照里塞字段：`ReviewReport` 里
 *   没有 `period_end`（它是复盘库归档时服务端写的），所以同一类型同一周期
 *   长度的两份归档，导出的 JSON **彼此不可区分** —— 用文件名兜住这一层。
 * ★ `period_end` 缺失或不是 `YYYY-MM-DD` 时退成今天（对话卡里就没这个值）。
 */
export function reviewExportBaseName(title: string, periodEnd?: unknown): string {
  const raw = String(periodEnd ?? '').trim()
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
  const stamp = m ? `${m[1]}${m[2]}${m[3]}` : todayStamp()
  return `复盘_${title}_${stamp}`
}

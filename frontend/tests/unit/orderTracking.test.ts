/**
 * `utils/orderTracking.ts` 行为契约（第 356 轮 · 前端单测第二批）
 * ============================================================================
 * 为什么挑它：这个模块的 docstring 自己写着一条**跨语言契约** ——
 *
 *   「后端 `_map_order_from_trade` 是自有订单库那条链的唯一映射口径，
 *     它产出的业务键必须在本文件的表里出现。」
 *
 * 而 `_map_order_from_trade` 所在的 `agent_cs.py` **刚被拆成 mixin 包**
 * （第 356 轮）。后端一改字段、前端这张表若没跟上，症状是**静默**的：
 * 界面不报错、只是某个字段**永远不显示**（`orderFields` 对缺值一律留空）。
 * 只有这里能把「口径必须与后端一致」钉成可执行断言。
 *
 * ★ 本文件**不重复**做跨仓对账 —— 那件事已由
 *   `frontend/scripts/check-order-track-parity.cjs` 完成（它直接读后端源码
 *   抽 `_map_order_from_trade` 的字段键，再与本文件比对）。**不要**在这里
 *   再抄一份后端契约，那是「同一判定两份实现」（两份都会漂移，且只有一份
 *   被修到）。这里只钉**前端自己的行为**。
 *
 * ★ 三个最值钱的断言（违反时的后果都是静默的）：
 *   ① `total == null` 时**绝不能**渲染成 `$0.00` —— 那是「编造一个具体数字」，
 *      且币种未必是 USD。改回 `Number(total || 0).toFixed(2)` 就会这样。
 *   ② 空值 / `'N/A'` / `'—'` **不进清单**（不补占位）—— 否则界面会出现
 *      一列「—」，用户分不清「字段没有」与「字段是空」。
 *   ③ `is_mock_data` 为真 ⇒ 演示数据脚注**必须**出现 —— 本仓硬口径：
 *      演示数据不许冒充真实订单。删掉 `orderSourceNote` 的调用即可静默违反。
 */
import { describe, it, expect } from 'vitest'
import {
  orderToneOf,
  orderStatusIcon,
  orderAmountText,
  orderHeader,
  orderFields,
  orderFieldPreview,
  buildOrderTrackingView,
  orderSourceNote,
  renderOrderTrackingText,
  orderSummaryLines,
} from '@/utils/orderTracking'

/** 一条「字段全给」的订单 —— 用来测「有哪些字段真的会被渲染」 */
const FULL_ORDER = {
  order_id: 'O1',
  status: 'Shipped',
  status_text: '已发货',
  created_at: '2026-01-01',
  product_name: '保温杯',
  quantity: 2,
  total_text: '$29.99',
  shipping_to: 'US-CA',
  estimated_delivery: '2026-01-05',
  tracking_number: 'TRK-1',
  carrier: 'UPS',
  ship_status_text: '在途',
  shipped_at: '2026-01-02',
  delivered_at: '2026-01-06',
  transit_days: 4,
  delay_days: 2,
  last_location: 'Los Angeles',
  last_event_text: '已到达分拨中心',
}

function withOrder(order: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return { found: true, order, message: '', ...extra }
}

describe('orderTracking · 状态三态（后端两套枚举都要认）', () => {
  it('SP-API 原始枚举（大写）经 toLowerCase 后命中', () => {
    expect(orderToneOf('Pending')).toBe('processing')
    expect(orderToneOf('Unshipped')).toBe('processing')
    expect(orderToneOf('PartiallyShipped')).toBe('shipped')
    expect(orderToneOf('Shipped')).toBe('shipped')
    expect(orderToneOf('DeliveredToCarrier')).toBe('shipped')
    expect(orderToneOf('Delivered')).toBe('delivered')
  })

  it('已取消的两种拼写都归 unknown（★ 说明性断言，非守卫 —— 见下）', () => {
    // ★★ 边界（如实登记，别把它当回归守卫）：
    //   这条**无法被反向注入打红** —— 实测：把 `TONE_OF` 里的 `cancelled` 那一行
    //   整行删掉，结果仍是 'unknown'（兜底表达式 `|| 'unknown'` 同值）
    //   ⇒ 它对这一行代码**没有区分力**。
    //   留着它的价值是**记录事实**：「后端 Canceled / Cancelled 两种拼写都出现过」。
    //   真正的守卫是下面那条「未知状态一律 unknown」（删掉 TONE_OF 的兜底即可打红它）。
    expect(orderToneOf('Canceled')).toBe('unknown')
    expect(orderToneOf('Cancelled')).toBe('unknown')
  })

  it('★ 未知状态一律 unknown —— 不猜成 processing（猜错会让用户以为还在途中）', () => {
    expect(orderToneOf('Weird_New_Status')).toBe('unknown')
    expect(orderToneOf('')).toBe('unknown')
    expect(orderToneOf(undefined)).toBe('unknown')
  })

  it('图标由三态决定（四态各一个）', () => {
    expect(orderStatusIcon('Delivered')).toBe('✅')
    expect(orderStatusIcon('Shipped')).toBe('🚚')
    expect(orderStatusIcon('Pending')).toBe('⏳')
    expect(orderStatusIcon('Canceled')).toBe('📦')
  })
})

describe('orderTracking · 金额文案（★ 不编造数字）', () => {
  it('★ 后端给了 total_text ⇒ 优先用它（带币种，就该原样展示）', () => {
    expect(orderAmountText({ total_text: '¥199.00', total: 199 })).toBe('¥199.00')
  })

  it('★★ total 为 null / 缺失 ⇒ 返回「—」，**绝不能**是 $0.00', () => {
    // 改回 `Number(order.total || 0).toFixed(2)` 会让下面两条变成 '0.00' ——
    // 那就是把「后端没给金额」渲染成一个具体的、错误的数字。
    expect(orderAmountText({})).toBe('—')
    expect(orderAmountText({ total: null })).toBe('—')
    expect(orderAmountText(null)).toBe('—')
  })

  it('total = 0 是**有效值**（不是缺失）⇒ 如实渲染 0.00', () => {
    // 守卫上一条：若有人用 `if (!order.total)` 判缺失，0 元订单会被显示成「—」
    expect(orderAmountText({ total: 0 })).toBe('0.00')
  })

  it('total 为数字 ⇒ 两位小数', () => {
    expect(orderAmountText({ total: 12.5 })).toBe('12.50')
  })
})

describe('orderTracking · 头部（缺值兜底，不编造）', () => {
  it('字段齐 ⇒ 原样映射', () => {
    expect(orderHeader({ order_id: 'O1', status: 'Shipped', status_text: '已发货' })).toEqual({
      orderId: 'O1',
      statusCode: 'Shipped',
      statusText: '已发货',
      tone: 'shipped',
      icon: '🚚',
    })
  })

  it('缺 status_text ⇒ 退回原始 statusCode（比显示空好）', () => {
    expect(orderHeader({ order_id: 'O1', status: 'Shipped' }).statusText).toBe('Shipped')
  })

  it('两者都缺 ⇒ 「未知状态」；order_id 缺 ⇒ 「—」', () => {
    const h = orderHeader({})
    expect(h.statusText).toBe('未知状态')
    expect(h.orderId).toBe('—')
    expect(h.statusCode).toBe('')
    expect(h.tone).toBe('unknown')
  })
})

describe('orderTracking · 字段清单「有值才成行」（★ 不补占位）', () => {
  it('★ 空串 / 空白 / N/A / — / null 一律不进清单', () => {
    const keys = orderFields({
      created_at: '',
      product_name: '   ',
      shipping_to: 'N/A',
      last_location: '—',
      carrier: null,
      tracking_number: undefined,
    }).map((f) => f.key)
    expect(keys).toEqual([])
  })

  it('★ 正整数守卫：quantity / transit_days 为 0 或负数或非数字 ⇒ 丢（不是渲染成 0 件）', () => {
    const keys = orderFields({ quantity: 0, transit_days: -1, delay_days: 'abc' }).map((f) => f.key)
    expect(keys).toEqual([])
  })

  it('★★ 无例外：缺金额时「金额」也不成行（与其它字段同口径）', () => {
    // ★ 第 357 轮修正。此前 `total_text` 的 pick 直接返回 `orderAmountText()`，
    //   而它在拿不到金额时返回 `'—'`（**非空字符串**）⇒ 过得了 `if (!value) continue`，
    //   界面上「金额 | —」这一行**永远存在**，成了「有值才成行」的唯一例外。
    //   现在 pick 统一过一道 `text()` ⇒ `'—'` 被归一成 `''` ⇒ 不成行。
    //   （同步点：`check-order-track-parity.cjs` 的 T3 白名单也已删除。）
    const empty = orderFields({ product_name: 'X' })
    expect(empty.map((f) => f.key)).toEqual(['product_name'])

    // ★ 反向自证：不是「整条清单都空」而碰巧通过 —— 给了金额就必须成行。
    const amount = orderFields({ product_name: 'X', total_text: '$9.99' })
      .find((f) => f.key === 'total_text')
    expect(amount?.value).toBe('$9.99')
    // 后端只给原始 `total`（无 `total_text`）时也成行（走 `orderAmountText()` 兜底分支）
    const fallback = orderFields({ product_name: 'X', total: 12.5 })
      .find((f) => f.key === 'total_text')
    expect(fallback?.value).toBe('12.50')
  })

  it('数量与天数带单位渲染', () => {
    const byKey = Object.fromEntries(orderFields({ quantity: 3, transit_days: 5, delay_days: 2 }).map((f) => [f.key, f.value]))
    expect(byKey.quantity).toBe('3 件')
    expect(byKey.transit_days).toBe('5 天')
    expect(byKey.delay_days).toBe('晚到 2 天')
  })

  it('★ 预计送达带口径说明（让用户知道这是**估算**，不是承诺）', () => {
    const f = orderFields({ estimated_delivery: '2026-01-05' }).find((x) => x.key === 'estimated_delivery')
    expect(f?.value).toBe('2026-01-05（按发货状态估算）')
  })

  it('抬头三项由 orderHeader 承载 ⇒ 不进 orderFields（否则界面会重复渲染）', () => {
    const keys = orderFields(FULL_ORDER).map((f) => f.key)
    expect(keys).not.toContain('order_id')
    expect(keys).not.toContain('status_text')
  })

  it('字段全给 ⇒ base 5 项 + logistics 10 项', () => {
    const fs = orderFields(FULL_ORDER)
    expect(fs.filter((f) => f.group === 'base')).toHaveLength(5)
    expect(fs.filter((f) => f.group === 'logistics')).toHaveLength(10)
  })

  it('mono / emphasis / summary 标记随 spec 透传（消费方据此决定排版）', () => {
    const byKey = Object.fromEntries(orderFields(FULL_ORDER).map((f) => [f.key, f]))
    expect(byKey.tracking_number.mono).toBe(true)
    expect(byKey.total_text.emphasis).toBe(true)
    expect(byKey.product_name.inSummary).toBe(true)
    expect(byKey.last_location.inSummary).toBeFalsy()
  })
})

describe('orderTracking · 封面清单与渲染清单同源（不是第二份手写表）', () => {
  it('★ 能渲染的 key 必须都在 orderFieldPreview() 里（唯一真源自洽）', () => {
    // 若有人往 ORDER_FIELD_SPECS 加了一项却没走同一张表，或另写一份 preview
    // 清单，这条会把不一致暴露出来。
    const preview = new Set(orderFieldPreview().map((p) => p.key))
    const renderable = orderFields(FULL_ORDER).map((f) => f.key)
    const orphan = renderable.filter((k) => !preview.has(k))
    expect(orphan).toEqual([])
  })

  it('preview 含两个抬头项（配置面板要如实说明「查询结果包含」订单号/状态）', () => {
    const keys = orderFieldPreview().map((p) => p.key)
    expect(keys).toContain('order_id')
    expect(keys).toContain('status_text')
  })

  it('★ ownDbOnly 只标在物流轨迹上（平台适配层给不出，安全失败方向如实说明）', () => {
    const own = orderFieldPreview().filter((p) => p.ownDbOnly).map((p) => p.key)
    expect(own).toContain('tracking_number')
    expect(own).toContain('carrier')
    expect(own).not.toContain('product_name')
    expect(own).not.toContain('total_text')
    // 预计送达是后端按发货状态估出来的，两条链都能给 ⇒ 不属于 ownDbOnly
    expect(own).not.toContain('estimated_delivery')
  })
})

describe('orderTracking · 归一视图', () => {
  it('found 需要 found 与 order **同时**为真（只有一个不算）', () => {
    expect(buildOrderTrackingView({ found: true, order: { order_id: 'O1' } }).found).toBe(true)
    expect(buildOrderTrackingView({ found: true }).found).toBe(false)
    expect(buildOrderTrackingView({ order: { order_id: 'O1' } }).found).toBe(false)
  })

  it('未找到 ⇒ 头部退化成 unknown，orderId 为「—」，不抛错', () => {
    const v = buildOrderTrackingView({})
    expect(v.found).toBe(false)
    expect(v.orderId).toBe('—')
    expect(v.header.tone).toBe('unknown')
    expect(v.base).toEqual([])
    expect(v.logistics).toEqual([])
    expect(v.hasLogistics).toBe(false)
  })

  it('payload 整个为 null ⇒ 同样安全退化', () => {
    expect(buildOrderTrackingView(null).found).toBe(false)
  })

  it('hasLogistics 由实际成行的物流字段决定（物流全为空 ⇒ false，整块不渲染）', () => {
    expect(buildOrderTrackingView(withOrder({ order_id: 'O1', carrier: 'UPS' })).hasLogistics).toBe(true)
    expect(buildOrderTrackingView(withOrder({ order_id: 'O1', product_name: 'X' })).hasLogistics).toBe(false)
  })

  it('isMock 取 order.is_mock_data；message 原样透传', () => {
    const v = buildOrderTrackingView({ found: true, order: { order_id: 'O1', is_mock_data: true }, message: '来自演示' })
    expect(v.isMock).toBe(true)
    expect(v.message).toBe('来自演示')
  })
})

/** 造一个最小可用视图（脚注只看 isMock / dataSource 两字段） */
function view(over: { isMock?: boolean; dataSource?: string }) {
  return {
    found: true,
    message: '',
    orderId: 'O1',
    header: { orderId: 'O1', statusCode: '', statusText: '', tone: 'unknown' as const, icon: '📦' },
    base: [],
    logistics: [],
    hasLogistics: false,
    dataSource: over.dataSource ?? '',
    isMock: over.isMock ?? false,
  }
}

describe('orderTracking · 演示数据脚注（★ 本仓硬口径）', () => {
  it('★ is_mock_data 为真 ⇒ 脚注必须出现且点明「演示数据」', () => {
    const note = orderSourceNote(view({ isMock: true, dataSource: 'mock_seed' }))
    expect(note).toContain('演示数据')
    expect(note).toContain('mock_seed')
  })

  it('dataSource 为空 ⇒ 兜底写 mock_seed（不能不写来源）', () => {
    expect(orderSourceNote(view({ isMock: true, dataSource: '' }))).toContain('mock_seed')
  })

  it('真实数据 ⇒ 空串（不打扰用户）', () => {
    expect(orderSourceNote(view({ isMock: false, dataSource: 'sp_api' }))).toBe('')
  })
})

describe('orderTracking · 渲染形态', () => {
  it('未查到 ⇒ 明说未查到 + 带上 message', () => {
    const text = renderOrderTrackingText({ found: false, message: '订单号格式不对' })
    expect(text).toContain('未能查到该订单')
    expect(text).toContain('订单号格式不对')
  })

  it('未查到且 message 为空 ⇒ 有兜底文案（不留空白）', () => {
    expect(renderOrderTrackingText({}).length).toBeGreaterThan(10)
  })

  it('查到 ⇒ Markdown 表格含订单号与状态，且物流单独成块', () => {
    const text = renderOrderTrackingText(withOrder(FULL_ORDER))
    expect(text).toContain('| 订单号 | `O1` |')
    expect(text).toContain('**物流** 🚚')
    expect(text).toContain('- 快递单号：`TRK-1`')
  })

  it('★ 演示数据 ⇒ 正文里带引用块脚注（用户一定看得见）', () => {
    const text = renderOrderTrackingText(withOrder({ ...FULL_ORDER, is_mock_data: true }))
    expect(text).toContain('> ⚠️ 演示数据')
  })

  it('摘要行：未查到 ⇒ 「订单查询未完成」', () => {
    expect(orderSummaryLines({ found: false, message: 'x' })[0]).toContain('订单查询未完成')
  })

  it('摘要只收 inSummary 字段（避免摘要变成第二份全量清单）', () => {
    const lines = orderSummaryLines(withOrder(FULL_ORDER))
    expect(lines.some((l) => l.startsWith('- 订单号：'))).toBe(true)
    expect(lines.some((l) => l.includes('快递单号'))).toBe(true)
    // last_location 没有 summary 标记 ⇒ 不该出现在摘要里
    expect(lines.some((l) => l.includes('最新位置'))).toBe(false)
  })

  it('摘要末尾有指向完整信息的收束语（不让用户以为摘要就是全部）', () => {
    expect(orderSummaryLines(withOrder(FULL_ORDER)).some((l) => l.includes('完整信息'))).toBe(true)
  })
})

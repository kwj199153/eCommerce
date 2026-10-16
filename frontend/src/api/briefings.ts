/**
 * 每日经营简报 API（第 371 轮）
 * ============================
 *
 * 简报 = 后端**每天早上自动生成**的一份「今天需要你处理的变化」清单，
 * 由 `monitors` 模块的 beat 任务产出（`modules/monitors/tasks.py`），
 * 与监控池同源（读的是同一批 `monitors` 行，按 `X-Shop-ID` 隔离）。
 *
 * 端点（两个，都是「读 + 标记已读」语义）：
 *   GET  /api/v1/briefings                → { items, total, unread }
 *   POST /api/v1/briefings/{id}/read      → 该条简报（含已读态）
 *
 * ★ 为什么**没有**「生成 / 重算」接口：生成是**全店**动作（一次扫所有监控池），
 *   放进 REST 就意味着任何客户端都能让整个平台重算一遍。手动补跑走运维通道
 *   （`celery call monitors.generate_daily_briefings`）。
 *
 * ★ 字段名保持**下划线**：后端 `briefing._to_dict()` 原样吐列名（与 `monitors`
 *   的 `record_to_dict` 同款），转换由消费方做，不在这一层偷偷改名 ——
 *   否则后端加一个字段，前端这一层会静默把它吃掉。
 */

import { get, post } from './request'

/** 简报里的一条明细（由监控池当刻快照派生，是**计算产物**，不落第二张表）。 */
export interface BriefingItem {
  /** 商品 ASIN */
  asin: string
  /** 商品标题（后端保证非空：取不到时退化成 ASIN） */
  title: string
  /** 类型：price_drop / stock_out / stock_low / review_surge / bsr_climb / listing_change */
  type: string
  /** 严重度：high（今天就该动）/ medium（还来得及）/ info（知道就好） */
  severity: 'high' | 'medium' | 'info'
  /** 量化指标（`-18.3%` / `断货` / `+42`），列表右侧那个短标记 */
  metric: string
  /** 一句人话。**后端拼好，前端不再二次加工** —— 两处拼同一句话必然漂移 */
  text: string
}

/** 一份简报（一天一份、按店铺）。 */
export interface DailyBriefing {
  id: string
  /** 本地日历日 `YYYY-MM-DD`（**生成时刻**的口径，不是 UTC 日） */
  brief_date: string
  shop_id: string
  items: BriefingItem[]
  /** 一句话摘要。**空简报也有话**（后端保证不返回空串） */
  summary: string
  item_count: number
  /** 已读时刻；`null` = 未读（铃铛徽标的数据源） */
  read_at: string | null
  /** 生成时刻（UTC ISO）。★ 与 `brief_date` 口径**刻意不同**，理由见后端文件头 */
  generated_at: string | null
}

export interface BriefingListResult {
  items: DailyBriefing[]
  total: number
  unread: number
}

/** 简报列表（日期倒序，最新在前）+ 未读数。
 *
 * ★ 未读数与列表走**同一个响应**而不是两个请求：拆开会让
 *   「徽标说 3 条、点开只有 2 条」成为可能（两次请求之间恰好又生成了一份）。
 */
export async function fetchBriefings(limit = 30): Promise<BriefingListResult> {
  return get('/briefings', { limit })
}

/** 标记一条简报已读（服务端**幂等**：重复调用不改首次的 `read_at`）。
 *
 * ★ 拿不到时后端回 **404**、不静默成功 —— 静默成功会让前端把徽标清掉，
 *   而服务端仍是未读 ⇒ 刷新一下又冒出来（用户看到「点了没反应、还越来越多」）。
 *   ⇒ 这里**不吞异常**，由 store 决定怎么呈现。
 */
export async function markBriefingRead(id: string): Promise<DailyBriefing> {
  return post(`/briefings/${id}/read`)
}

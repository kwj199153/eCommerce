/**
 * 后端 `detail` 的**结构化形态** → 界面上能看懂的一句话（唯一真源）。
 *
 * ======================================================================
 * 为什么要有这个文件（第 386 轮）
 * ======================================================================
 * 后端从第 385 轮起，失败响应不再只有字符串 `detail`，还有**对象**形态：
 *
 *   · 402 `{code: "PLAN_LIMIT_EXCEEDED", message, limit, current, upgrade_url}`
 *   · 409 `{code: "STORE_NOT_CONNECTED", store_id, reason, message}`   ← 本轮新增
 *   · 422 `{code: "UNSUPPORTED_MARKETPLACE", store_id, …}`             ← 本轮新增
 *
 * 而前端有 **19 处** 写着 `e?.response?.data?.detail || '兜底文案'`。字符串 detail
 * 时代这是对的；一旦 detail 是对象，这行代码会把对象塞进 `ref<string>` / toast，
 * 界面渲染出 `[object Object]` —— 比「没提示」更糟：它看起来像前端崩了。
 *
 * 更要紧的是第二种错误：**把「未授权」当成「加载失败」**。
 *   `detail` 对象里明明写着 `code=STORE_NOT_CONNECTED`（客户还没点授权），
 *   而界面说「加载失败，请重试」⇒ 客户会一直点重试，而正确操作是去授权。
 *   这两个状态必须能分开，否则「重试」这个按钮就是骗人的。
 *
 * ⇒ 收成一处：**谁都不许再直接读 `response.data.detail`**，一律走这里。
 *   这样「结构化 detail 怎么显示」只有一份实现，下一轮新增一种 code 也只改这里。
 *
 * ★ 本文件故意**零依赖**（不 import axios / antd / vue）：它要能被 request.ts、
 *   store、组件、单测同时引用而不引入循环。
 */

/** 409 那条的语义别名（同形状，只是让调用点读起来贴场景）。 */
export type StoreNotConnectedInfo = ConnectIssue

/** 后端结构化 detail 的最小公共形状（具体 code 各自扩展字段）。 */
export interface StructuredDetail {
  code?: string
  message?: string
  [key: string]: unknown
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

/**
 * 把后端 `detail` 归一成一句可读文案。
 *
 * ★ 为什么优先取 `message` 而不是 `JSON.stringify`：后者会把
 *   `{"code":"PLAN_LIMIT_EXCEEDED",...}` 整块甩到 toast 里，对用户是无信息噪声。
 * ★ 对象里没有 `message` 时**不**退回 `String(detail)`：那正是 `[object Object]`。
 */
export function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  const obj = asRecord(detail)
  if (obj) {
    const msg = asText(obj.message)
    if (msg) return msg
  }
  return fallback
}

type Axiosish = {
  response?: { status?: number; data?: { detail?: unknown } }
  message?: string
}

/**
 * 从错误对象里取「该给用户看的那句话」。
 *
 * ★ 刻意**不**退回 `err.message`：axios 的 `message` 是
 *   `Request failed with status code 500` 这类开发者语言，铺到界面上等于没说，
 *   而且会掩盖调用点本来写好的兜底文案（「登录已过期，请重新登录」之类）。
 */
export function errorText(err: unknown, fallback: string): string {
  const detail = (err as Axiosish)?.response?.data?.detail
  if (detail !== undefined && detail !== null) return detailText(detail, fallback)
  return fallback
}

/** 「这家店现在取不到数」的一个可处理原因（未授权 / 站点不支持）。 */
export interface ConnectIssue {
  storeId: string
  /** 后端给的原因：`no_credentials` / `store_not_found` / `oauth_missing` … */
  reason: string
  /** 已经归一成人话的说明（可直接上屏） */
  message: string
}

/**
 * 识别 `409 + code=STORE_NOT_CONNECTED`，返回结构化信息；不是则返回 `null`。
 *
 * ★ 为什么必须**同时**判状态码和 code：409 在本 API 里不止一种含义
 *   （账单退款那条回 `INVOICE_NOT_REFUNDABLE`）。只判状态码会让运营点「退款」
 *   时看到「请去授权店铺」，归因直接指向错的地方。
 *
 * ★ 调用点拿到非 null 后要做的是「换成授权引导」，**不是**「显示重试」：
 *   重试改变不了「这家店没授权」这个事实。
 */
export function storeNotConnectedInfo(err: unknown): ConnectIssue | null {
  const resp = (err as Axiosish)?.response
  if (resp?.status !== 409) return null
  const obj = asRecord(resp.data?.detail)
  if (!obj || obj.code !== 'STORE_NOT_CONNECTED') return null
  return {
    storeId: asText(obj.store_id),
    reason: asText(obj.reason) || 'not_connected',
    message: asText(obj.message) || '该店铺尚未完成平台授权',
  }
}

/**
 * 识别 `422 + code=UNSUPPORTED_MARKETPLACE`（站点不在支持的 10 个之内）。
 *
 * ★ 与 409 分开：这不是「去授权就能好」，而是「这个站点我们还不支持」——
 *   客户该做的是联系我们，不是反复授权/重试。
 */
export function unsupportedMarketplaceInfo(err: unknown): ConnectIssue | null {
  const resp = (err as Axiosish)?.response
  if (resp?.status !== 422) return null
  const obj = asRecord(resp.data?.detail)
  if (!obj || obj.code !== 'UNSUPPORTED_MARKETPLACE') return null
  return {
    storeId: asText(obj.store_id),
    reason: 'unsupported_marketplace',
    message: asText(obj.message) || '该店铺所在站点暂不支持',
  }
}

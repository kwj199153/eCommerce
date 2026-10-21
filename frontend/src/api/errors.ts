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

/* ======================================================================
 * 429：**两种业务原因，不是一种**（第 387 轮 · 网站管理员 P1-1）
 * ======================================================================
 * 后端改造前，两种完全不同的情况都长成「额度用完」：
 *
 *   · `QUOTA_EXCEEDED`        —— 真的用完了。等额度重置 / 升级套餐 **有用**。
 *   · `SUBSCRIPTION_INACTIVE` —— 订阅无效或已过期。用的次数可能才 3 次；
 *                               等多久都不会好，只有恢复订阅有用。
 *
 * 把后者显示成前者，代价不是"文案不好看"：用户去充值（无效）、运维去查
 * 用量曲线（没有异常）、支持同学按"提额度"处理（越处理越离谱）。
 * 管理员本人的原话是「我自己刚踩过这个坑」。
 *
 * ★ 429 还有**第三种**来源：登录锁定（`core/identity/login_guard.py`，带
 *   `Retry-After` 剩余秒数）与边缘限流。它们不是配额问题，`detail` 是字符串。
 *   ⇒ 本函数只认 `code`，认不出就返回 `null`，由调用方走通用文案。
 *   否则「密码错太多次」会被显示成「请升级套餐」——同一个错误在两个方向上。
 */

/** 后端 `QuotaDenial.to_payload()` 的 code 全集。 */
export type QuotaCode =
  | 'QUOTA_EXCEEDED'
  | 'SUBSCRIPTION_INACTIVE'
  | 'QUOTA_USAGE_TYPE_UNKNOWN'

export interface QuotaDenialInfo {
  code: QuotaCode
  /** 后端写好的一句话（已含「与调用次数无关」这类消歧说明） */
  message: string
  usageType: string
  /** 后端建议的下一步：升级 / 续费 / 联系支持 */
  action: 'upgrade_plan' | 'renew_subscription' | 'contact_support'
  used?: number
  limit?: number
  remaining?: number
}

const QUOTA_CODES: readonly string[] = [
  'QUOTA_EXCEEDED',
  'SUBSCRIPTION_INACTIVE',
  'QUOTA_USAGE_TYPE_UNKNOWN',
]

function asNum(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/**
 * 识别「配额类 429」（429 + 已知 code），否则 `null`。
 *
 * ★ 为什么必须判 429：`QUOTA_EXCEEDED` 只会出现在 429 上，但同一个 code
 *   将来可能出现在别的状态码（例如预检接口回 200 + 余额不足标记）。
 *   只按 code 判会把"余额提醒"误认成"被拦下了"。
 */
export function quotaDenialInfo(err: unknown): QuotaDenialInfo | null {
  const resp = (err as Axiosish)?.response
  if (resp?.status !== 429) return null
  const obj = asRecord(resp.data?.detail)
  if (!obj) return null
  const code = asText(obj.code)
  if (!QUOTA_CODES.includes(code)) return null
  const action = asText(obj.action)
  return {
    code: code as QuotaCode,
    message: asText(obj.message) || '当前套餐的额度不足以完成这次操作',
    usageType: asText(obj.usage_type),
    action:
      action === 'upgrade_plan' || action === 'renew_subscription'
        ? action
        : 'contact_support',
    used: asNum(obj.used),
    limit: asNum(obj.limit),
    remaining: asNum(obj.remaining),
  }
}

/**
 * 把配额拒绝归一成「一句话 + 下一步」。
 *
 * ★ 两种原因给**不同**的下一步，这正是本条需求的核心：
 *   额度用完 ⇒ 升级；订阅失效 ⇒ 续费。**都不给"重试"** ——
 *   重试既不会让额度回来，也不会让订阅复活。
 */
export function quotaGuidance(info: QuotaDenialInfo): string {
  switch (info.action) {
    case 'renew_subscription':
      return `${info.message}。请到「设置 → 订阅」恢复订阅（重试无效）`
    case 'upgrade_plan':
      return info.limit !== undefined
        ? `${info.message}。可在「设置 → 订阅」升级套餐，或等待下个计费周期重置`
        : `${info.message}。可在「设置 → 订阅」升级套餐`
    default:
      return info.message
  }
}

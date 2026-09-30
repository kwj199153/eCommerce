/**
 * 对话失败路径 · 唯一实现（★ 第 221 轮）
 *
 * 为什么必须只有一份
 * ================
 * 「流式 + 非流式**都**失败」之后要跟用户说一句什么样的话，这件事此前在四条回复链里
 * **各写了一份**（`productResearch.ts` / `listing.ts` / `adAnalysis.ts` /
 * `customerService.ts`），而且只有选品那一份是「如实说」：
 *   · 选品：`⚠️ 选品分析请求失败（HTTP 429）：API 调用次数不足，剩余 0 次`
 *   · 另外三条：`console.error` 之后落回 `return 'fallthrough'`
 *     ⇒ 降级链又补一句「⚠️ X 这次没有返回结果」甚至「正在为您分析…」（伪成功）。
 * 于是「同一个事实有两个说法」，而**只有被看过的那一份会被修** —— 这正是本仓那条
 * 「同一判定两份实现 ⇒ 至少一份永远测不到」的现场。
 *
 * 设计约束
 * ======
 *   ① **纯函数模块**：不 import store / 不发请求 / 不读全局 —— 门禁可以直接调它做单测，
 *      也不会有第二个「谁来写界面」的实现。**写回界面**那一步
 *      （`setLastMessageContent` / `addMessage`）留在各分支里，因为它取决于
 *      「当前有没有一条占位消息」—— 那是各分支自己的控制流事实，不是文案事实。
 *   ② **只输出客观事实**：HTTP 状态码 + 后端 `detail`。后端 `detail` 给的是
 *      **可解释的业务结论**（400 = 没选店铺 / 403 = 店铺不属于你 / 429 = 额度用尽），
 *      原样透出用户才知道下一步该干什么；写「（对话失败，请重试）」会让用户只能反复重试
 *      —— 因为配额耗尽与网络抖动在界面上**完全同形**。
 *   ③ **不得出现「正在进行」的措辞**：一个已经失败的分支不可能同时「正在分析」，
 *      那正是「伪装成成功的失败」。
 */

/** 从异常里取出的客观事实。 */
export interface ChatHttpFacts {
  /** HTTP 状态码；网络层失败（压根没有响应）时为 `undefined` */
  status?: number
  /** 后端 `detail` 字段（可能是字符串，也可能是结构化对象） */
  detail?: unknown
}

/**
 * ★ 只认「HTTP 响应」这两个位置，**不猜**：
 *   axios 的 `error.response.status` / `error.response.data.detail`。
 *   非同族异常（`import()` 失败 / `TypeError`）没有这两个字段 ⇒ 返回全空，
 *   由 `describeChatFailure` 退回「原样带出 `message`」那条路。
 */
export function collectHttpFacts(err: unknown): ChatHttpFacts {
  const e: any = err
  return { status: e?.response?.status, detail: e?.response?.data?.detail }
}

/**
 * 把「流式 + 非流式都失败」转成一句**可行动**的中文说明。
 *
 * @param label          业务名（如「选品分析请求」）⇒ 文案为 `⚠️ <label>失败…`
 * @param retryError     非流式重试的异常（走 axios ⇒ 有 `response.status` / `response.data.detail`）
 * @param transportError 更早那次失败的异常（`streamSSE` 抛的普通 `Error`，文案形如
 *                       `请求失败 (429) {...}`；或模块加载失败的原生错误）
 */
export function describeChatFailure(
  label: string,
  retryError: unknown,
  transportError: unknown,
): string {
  const { status, detail } = collectHttpFacts(retryError)
  if (status || detail) {
    const reason = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : '服务端未返回原因。'
    return `⚠️ ${label}失败${status ? `（HTTP ${status}）` : ''}：${reason}`
  }
  // 没有 HTTP 响应（网络层失败 / 模块加载失败）⇒ 退回更早那条文案，
  // 它至少带了状态码与响应体原文。
  const raw = transportError instanceof Error ? transportError.message : String(transportError ?? '')
  return raw ? `⚠️ ${label}失败：${raw}` : `⚠️ ${label}失败，请稍后重试。`
}

/**
 * 前端请求追踪 ID（trace id）
 *
 * ★ 为什么单独一个模块（不住 `request.ts` / `stream.ts`）：
 *   本仓有**两个互相独立**的 HTTP 出口 —— axios 实例（`api/request.ts`）与
 *   SSE 的裸 `fetch`（`api/stream.ts`）。追踪 ID 的「生成 / 记忆 / 回写」规则
 *   必须**只有一份实现**，否则两个出口的 ID 形态会漂移，而契约方（后端）
 *   用的是 `uuid4().hex[:16]`。
 *   本模块**零依赖、无副作用**，只被那两个出口 import —— 与
 *   `utils/sessionContext.ts` 同一条「拓扑上永不进 ESM 环」的原则。
 *
 * ★ 为什么前端要主动发 `X-Request-ID`：
 *   后端中间件对**没带**的请求会自己生成一个（`core/middleware/request_log.py`），
 *   但它只把 ID 回写在响应头里 —— 请求发起方手里没有同一个串，就无法把
 *   「用户看到的那句报错」与「服务端那一行访问日志」对上。
 *   前端先发一个，后端原样透传（这是既有契约，有测试钉住）。
 *
 * ★ 边界：这不是安全标识，不参与鉴权，也不保证全局唯一 ——
 *   它唯一的用途是让一次失败请求在前后端日志里能被同一个串串起来。
 */

/** 生成一个与后端同构的短追踪 ID（16 位十六进制，对齐 `uuid4().hex[:16]`） */
export function newTraceId(): string {
  try {
    const c = globalThis.crypto
    if (c) {
      if (typeof c.randomUUID === 'function') {
        return c.randomUUID().replace(/-/g, '').slice(0, 16)
      }
      if (typeof c.getRandomValues === 'function') {
        const bytes = new Uint8Array(8)
        c.getRandomValues(bytes)
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
      }
    }
  } catch {
    // 非安全上下文（http 且非 localhost）下 crypto 可能不存在或直接抛错，
    // 落到下面的时间戳兜底 —— 追踪 ID 退化一点，总好过整个请求发不出去。
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`.slice(0, 16)
}

/** 最近一次请求的追踪 ID（由下面两个出口写入；还没发过请求时为 null） */
let lastId: string | null = null

/**
 * 记下这次的追踪 ID。
 *
 * ★ 服务端回写的 `X-Request-ID` 优先于本地生成值 —— 中间件会把上游传来的
 *   原样透传，若网关改写过 ID，只有响应头里那个才是让服务端日志能对上的串。
 */
export function rememberTraceId(id: string | null | undefined): void {
  if (typeof id === 'string' && id.trim()) lastId = id.trim()
}

/**
 * 给用户可见的失败文案挂上追踪 ID 尾巴。
 *
 * ★ 为什么只加尾巴、不改前缀：失败文案的前缀是**既有契约**
 *   （例如 `stream.ts` 的 `请求失败 (${status}) ` 被
 *   `scripts/check-chat-failure-path.cjs` 逐字引用）。改前缀既会打红门禁，
 *   也会让用户已经习惯的排障读法失效。
 * ★ 没有 ID 时**原样返回**：编一个假 ID 比没有更糟 —— 它会把排障引到
 *   一个根本不存在的日志行上。
 */
export function withTraceId(text: string): string {
  return lastId ? `${text}（追踪 ID：${lastId}）` : text
}

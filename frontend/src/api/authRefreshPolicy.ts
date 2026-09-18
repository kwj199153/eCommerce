/**
 * 401 刷新判定真源（★ 第 117 轮）
 *
 * 为什么把这段判定从拦截器里抽出来单独成模块：
 *
 * 修复前它深埋在 `api/request.ts` 的 401 分支里，且**靠猜后端文案**：
 *
 * ```ts
 * if (data?.detail?.includes('Token') || data?.detail?.includes('认证')) { … }
 * ```
 *
 * 三个后果，全部实测复现过：
 *
 *  ① **判定与文案耦合**。后端 401 有 6 种不同文案，改一个字前端行为就变；
 *    最典型的是「完全没带 Authorization 头」时后端回 `Not authenticated`，
 *    两个关键词都不含 ⇒ 永远不会尝试刷新，直接登出。
 *
 *  ② **递归刷新**。`/auth/refresh` 自己失败时返回的文案是
 *    「Refresh Token 已过期，请重新登录」—— **含「Token」**。而它走的是
 *    **同一个 axios 实例**，拦截器对它的 401 同样生效，且没有路径豁免。
 *    按源码控制流复现的结果是：一次 401 引发 13 次刷新且不会自然停止。
 *
 *  ③ **没有并发锁**。页面首屏同时发 5 个请求、同时 401，就会各刷一次。
 *
 * 收敛后的判据**只看四个客观事实**，一个文案都不看：
 *    `401` + `手里确有真实 refresh_token` + `该请求不是认证端点` + `本次还没重试过`
 *
 * 本模块是**纯函数 + 常量**，不 import axios / vue / pinia：
 * 这样门禁脚本可以在 `vm` 沙箱里直接跑真值表（见 scripts/check-auth-refresh-guard.cjs）。
 */

/**
 * 认证端点：它们**自身**就是认证入口，返回 401 是业务结论
 * （密码错、凭据过期、已登出），必须原样交给调用方，
 * 任何一次都不该触发刷新 —— 否则就是上面第 ② 条那个递归。
 *
 * ★ 用相对路径的**后缀**匹配（见 `isAuthEndpoint`），
 *   所以这条清单不会被 baseURL 或前缀变化打穿。
 */
export const NO_REFRESH_ENDPOINTS = [
  '/auth/login',
  '/auth/register',
  '/auth/refresh',
  '/auth/logout',
  // ★ 第 119 轮：本机免密端点全部豁免。
  //
  //   `/auth/device/switch` 返回 401 是**业务结论**（"这枚凭据已被撤销/过期，
  //   请输密码"），不是"当前会话该刷新了"的信号。若不豁免，会走出这样一条路：
  //   切换失败 → 拦截器拿**当前账号**的 refresh_token 去刷 → 刷成功后
  //   拿新 token 重试 switch → 仍然 401（因为问题在目标凭据，不在当前会话）
  //   → 白白多两跳，还可能把用户当前**正常**的会话搅乱
  //   （刷新会轮换 refresh_token，而此刻用户正打算离开这个账号）。
  //
  //   `/auth/device/enroll` 同理：它在登录后 fire-and-forget 调用，
  //   401 只说明"当前 access token 不认"，登记失败即可，无需刷新重试。
  '/auth/device/enroll',
  '/auth/device/accounts',
  '/auth/device/switch',
  '/auth/device/forget',
  '/auth/device/forget-all',
] as const

/**
 * 挂在 axios config 上的一次性重试标记。
 *
 * ★ 它是「重试护栏」的载体：重试后的请求若**仍然** 401
 *   （例如服务端把新签发的 token 也拒了），必须直接走向登出，
 *   而不是再刷一轮 —— 否则会形成「刷新→重试→401→刷新」的第二个循环。
 *   （第一个循环由 `isAuthEndpoint` 堵住，这是第二个。）
 *
 * 对应的类型声明在 `api/request.ts` 的 `declare module 'axios'` 里，
 * 那里是 axios 配置类型的唯一扩展点。
 */
export const AUTH_RETRY_FLAG = '_authRetried'

/** 去掉 query 与 hash，只留路径部分 */
function pathOf(url: string): string {
  return url.split('?')[0].split('#')[0]
}

/**
 * 这个请求是不是认证端点自身。
 *
 * 用 `endsWith` 而非严格相等，是为了同时覆盖：
 *   `/auth/refresh`（config.url 的常态）与 `/api/v1/auth/refresh`（绝对形式）。
 */
export function isAuthEndpoint(url?: string | null): boolean {
  if (!url) return false
  const path = pathOf(url)
  return NO_REFRESH_ENDPOINTS.some((p) => path === p || path.endsWith(p))
}

export interface RefreshDecisionInput {
  /** HTTP 状态码；只有 401 才谈得上刷新 */
  status: number
  /** `error.config.url`，用于豁免认证端点 */
  url?: string | null
  /**
   * 手里是否有一枚真实可用的 refresh_token。
   *
   * ★ 传的是 `userStore.hasRefreshToken`（内存态 + 排除 demo 伪凭据），
   *   **不是** `localStorage.getItem('refresh_token')`——
   *   演示模式下那个键里躺着 `demo-refresh-token`，后端一律不认，
   *   照着它去刷只会得到一次注定失败的请求。
   */
  hasRefreshToken: boolean
  /** 本次请求是否已经因刷新失败重试过一次（读 `AUTH_RETRY_FLAG`） */
  alreadyRetried?: boolean
}

/**
 * 唯一判定：这次 401 要不要尝试刷新 token。
 *
 * 四个出口全部是 `false`，且都是**客观事实**，与后端文案无关。
 */
export function shouldAttemptRefresh(input: RefreshDecisionInput): boolean {
  const { status, url, hasRefreshToken, alreadyRetried } = input

  // 不是 401 就没有这个话题
  if (status !== 401) return false
  // ★ 单次护栏：已经重试过仍 401 ⇒ 不再刷新
  if (alreadyRetried) return false
  // ★ 手里没牌就别刷（未登录 / 演示模式 / refresh 已过期被清）
  if (!hasRefreshToken) return false
  // ★ 认证端点自身豁免（堵住递归刷新）
  if (isAuthEndpoint(url)) return false

  return true
}

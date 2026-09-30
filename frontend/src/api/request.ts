/**
 * API 请求封装
 *
 * 基于 Axios 的 HTTP 客户端，提供：
 * - JWT Token 自动注入
 * - 统一错误处理
 * - 请求/响应拦截器
 * - 自动刷新 Token
 */

import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { message } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import router from '@/router'
import { isDemoToken } from '@/config/demoMode'
import { resetSessionContext } from '@/utils/sessionContext'
import {
  AUTH_RETRY_FLAG,
  isAuthEndpoint,
  shouldAttemptRefresh,
} from '@/api/authRefreshPolicy'

/**
 * 提示归属（第 267 轮定稿）：**成功提示归调用点，错误提示归拦截器**。
 *
 * ★ 为什么不再有 `silent` 开关 —— 起因「一点击运营复盘师，中间对话区顶部就弹字」：
 *   此前响应拦截器对「非 GET + 响应体带 message」**无条件**弹 `message.success`，
 *   于是后端任何 `message="XX已生成"` 都被翻译成一条绿勾。而爆点那个端点
 *   （`review_analyst` 的 6 个结构化 POST）本就由调用点渲染成看板/卡片 ⇒
 *   用户看到的字**逐字等于**响应体的 `message` 字段，且与界面内容重复。
 *
 *   `silent` 就是为压这类刷屏而打的补丁，但它只覆盖「调用方**记得**声明」的场景：
 *   没声明的调用点（对话卡那几个分支）照样刷屏 —— 补丁治不了病根。
 *
 *   改成**默认不弹成功提示**：谁要在操作完成后给回执，谁自己拿到结果后调
 *   `message.success(...)`。`silent` 因此彻底失去语义，已全仓清理
 *   （门禁 `check-toast-ownership.cjs` 钉住）。
 */
declare module 'axios' {
  export interface AxiosRequestConfig {
    /**
     * `silentError: true` —— **错误提示**也交给调用方处理。
     *
     * 语音播报这类**后台自动触发**的请求失败时，调用方自己会给出更精确的原因
     * （「当前店铺还没有克隆音色，去设置里创建」）并顺手关掉开关；
     * 若拦截器再按 `detail` 弹一次，用户就会看到两条重复提示。
     * 同理：自带**常驻**错误面（内联横幅 / 对话卡）的调用点也声明它 ——
     * 免得同一个原因既上横幅又弹 toast。
     */
    silentError?: boolean
    /**
     * `requiresIdentity: true` —— 该请求读的是**身份与授权数据**
     * （账户 / 成员 / 自助资料 / API 密钥），必须绑定真实账号。
     *
     * ★ 为什么需要这个标志（2026-09-16，起因「提示要登录可是没有入口」）：
     *   演示模式下 `access_token` 是 `demo-token`（不是 JWT），后端 401 时
     *   下面的拦截器**静默放行**，由业务页面自行降级到 mock —— 这对
     *   业务数据（选品 / 广告 / 素材库）是合理的。
     *
     *   但身份数据**没有可降级的东西**：编不出一份"你的团队成员"。
     *   被静默吞掉的结果是用户只看到一句"请先登录"，
     *   而页面既不跳登录页、也不给入口 —— 失败没有被送到任何出口。
     *   所以这类请求显式声明，让 401 走正常通路（清状态 + 跳登录 + 带回跳）。
     */
    requiresIdentity?: boolean

    /**
     * 一次性重试标记（值取自 `api/authRefreshPolicy.ts` 的 `AUTH_RETRY_FLAG`）。
     *
     * ★ 为什么必须有它：401 分支在刷新成功后会**重发原请求**。
     *   如果服务端把新签发的 token 也拒了，那个重发请求会再回到 401 分支 ——
     *   而那时手里**依然**有 refresh_token、请求也不是认证端点，
     *   按四条客观事实看它会再次尝试刷新 ⇒ 形成「刷新→重试→401→刷新」的循环。
     *   本标记就是打在这个岔路上的唯一一枪。
     */
    _authRetried?: boolean
  }
}

// 创建 Axios 实例
const request: AxiosInstance = axios.create({
  baseURL: '/api/v1',  // 通过 Vite proxy 转发到后端
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ====== 刷新并发锁 ======

/**
 * 正在进行中的刷新。同一时刻**只允许一次** `/auth/refresh` 在飞。
 *
 * ★ 为什么需要锁：页面首屏会同时发多个请求（店铺 / 团队 / 账户…），
 *   若 access token 恰好过期，它们会同时收到 401。没有锁的话
 *   每一个都去刷一次 —— 既浪费往返，也会让后端一次撤销多条 refresh 记录，
 *   极端情况下先到的那次刷新会使后到的 refresh_token 失效。
 *   加锁后它们共享同一个 promise。
 */
let refreshPromise: Promise<boolean> | null = null

/**
 * 加锁地刷新一次。
 *
 * ★ `finally` 里必须把它清空：否则一次失败会把后续**所有**刷新
 *   永久钉死在这个已经 resolve 的 promise 上（表现为「再也刷不动了」）。
 * ★ `.catch(() => false)`：`refreshToken()` 内部虽然已经吞掉了异常，
 *   但这里再兜一层 —— 让「刷新这事本身炸了」与「刷新返回了 false」
 *   对调用方完全等价，调用方只需判布尔值。
 */
function refreshOnce(): Promise<boolean> {
  if (refreshPromise) return refreshPromise
  const p = useUserStore()
    .refreshToken()
    .catch(() => false)
    .finally(() => {
      refreshPromise = null
    })
  refreshPromise = p
  return p
}

// ====== 请求拦截器 ======
request.interceptors.request.use(
  (config) => {
    const userStore = useUserStore()

    // 自动注入 JWT Token
    if (userStore.token) {
      config.headers.Authorization = `Bearer ${userStore.token}`
    }

    // 注入店铺 ID（多租户）
    const shopId = getShopId()
    if (shopId) {
      config.headers['X-Shop-ID'] = shopId
    }

    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// ====== 响应拦截器 ======
request.interceptors.response.use(
  (response: AxiosResponse) => {
    // 统一处理成功响应
    const data = response.data

    // ★ 成功提示不再由拦截器自动弹（理由见文件顶部「提示归属」）：
    //   回执交给调用点自己决定 —— 有的渲染成对话卡、有的弹 toast、有的只更新横幅。
    //   旧的「非 GET + 带 message ⇒ 弹绿勾」已删：它会把「订单查不到」
    //   「工单创建失败」这类业务结论也渲染成绿色「成功」提示。
    //
    // ★ 这里只补一条**业务失败**通道：后端对「HTTP 200 + 业务失败」用
    //   `success: false` 表达（响应点见 `ad_analysis` 6 处 + `customer_service`
    //   工单 2 处），它既不是 4xx、也不进下面的 error 分支 ⇒ 不补判就没人看见。
    //   受 `silentError` 管：自带常驻错误面的调用点（如广告看板的内联横幅）
    //   声明它，避免同一个原因两处报。
    if (data?.success === false && !response.config.silentError) {
      message.error(data?.message || data?.detail || '操作失败')
    }

    return data
  },
  async (error) => {
    const { response, config } = error
    // silentError：调用方自会给出更精确的原因（语音播报失败会连开关一起关掉）
    const silentError = !!config?.silentError

    if (!response) {
      // 网络错误
      if (!silentError) message.error('网络连接失败，请检查网络')
      return Promise.reject(error)
    }

    const { status, data } = response
    const userStore = useUserStore()

    switch (status) {
      case 401: {
        // ★ 身份类请求（requiresIdentity）**不能**被下面的演示模式分支吞掉：
        //   吞掉的后果是"需要登录"这件事永远送不到登录入口上（见类型声明处说明）。
        const needsIdentity = !!config?.requiresIdentity

        // ★ 第 117 轮：**认证端点自身**的 401 是业务结论，不是「登录过期」。
        //     `/auth/login` 的 401   = 邮箱或密码错误；
        //     `/auth/refresh` 的 401 = refresh 已过期/被撤销；
        //     `/auth/logout` 的 401  = 凭据本就无效（登出照样要成功）。
        //
        //   这类 401 必须**原样交回调用方**去解释，拦截器不得：
        //     · 清状态 / 清上下文 / 跳登录页
        //       —— 那会把「密码打错」渲染成「你被踢出去了」；
        //     · 弹提示
        //       —— `/auth/refresh` 的失败是外层 401 处理的**内部细节**，
        //          在这里弹出来就是同一次失败弹出两条一样的提示。
        //
        //   ★ 用的是与 `shouldAttemptRefresh` 里**同一个** isAuthEndpoint，
        //     不是又抄一份判定（两份实现必有一份永远测不到）。
        if (isAuthEndpoint(config?.url)) {
          return Promise.reject(error)
        }

        // Token 过期或无效
        // 演示模式：demo-token 被拒时静默处理，由**业务页面**自行降级到 mock。
        // （业务数据在演示模式下的离线兜底依赖这个行为，不要动它。）
        if (isDemoToken(userStore.token) && !needsIdentity) {
          console.warn('[Demo Mode] API 返回 401，业务数据降级处理')
          return Promise.reject(error)
        }

        // ★ 第 117 轮：要不要刷新这件事，收敛到 api/authRefreshPolicy
        //   这一个纯函数里（唯一真源，门禁钉住）。
        //
        //   修复前这里写的是：
        //     `data?.detail?.includes('Token') || data?.detail?.includes('认证')`
        //   —— 靠**猜后端文案**。它有两个实测可复现的后果：
        //     · 后端回 `Not authenticated`（完全没带 Authorization 头）时
        //       两个关键词都不含 ⇒ 永不刷新，直接登出；
        //     · `/auth/refresh` 自己失败时的文案是
        //       「Refresh Token 已过期，请重新登录」——**含「Token」**，
        //       而它走的是同一个 axios 实例 ⇒ 递归刷新。
        //
        //   现在只看四个客观事实：
        //     401 + 手里确有真实 refresh_token + 不是认证端点 + 本次没重试过
        if (
          shouldAttemptRefresh({
            status,
            url: config?.url,
            hasRefreshToken: userStore.hasRefreshToken,
            alreadyRetried: !!config?.[AUTH_RETRY_FLAG],
          })
        ) {
          // 并发锁：此刻可能已有一次刷新在飞，那就搭它的车
          const refreshed = await refreshOnce()
          if (refreshed && config) {
            // ★ 打标记再重发：新 token 若仍被拒，下一次进来
            //   alreadyRetried=true ⇒ 直接登出，不再刷第二轮。
            config[AUTH_RETRY_FLAG] = true
            // 重试原请求（请求拦截器会用刚写入 store 的新 token 覆盖 Authorization）
            return request(config)
          }
        }

        // 刷新失败，清除状态并跳转登录
        // ★ 这里必须用 clearAuth()（纯本地）而不是 logout()：
        //   logout() 会发 /auth/logout 请求，而此刻后端正在回 401 —— 会递归打转。
        //
        // ★ 同样必须把 demo token 一并清掉：路由守卫已改为按"是不是真身份"
        //   判断，但只清状态、不留残留，才能保证进登录页这一步是确定的。
        userStore.clearAuth()

        // ★ 第 113 轮：身份失效，**上下文也得一起清**。
        //   401 之后若还留着上一个身份的 current_shop_id / current_account_id，
        //   下一个身份登录后、在店铺/团队列表加载完成之前发出去的请求，
        //   会带着**上一个账号的** X-Shop-ID —— 后端归属校验 403，
        //   而用户看到的是"我的店铺不见了"。
        //   ★ 仍保持"纯本地、不发请求"：此刻后端正在回 401，
        //     任何出网调用都会变成递归打转。
        resetSessionContext()

        // 带回跳地址，登录后回到刚才那一页。
        // 已在登录页时不再跳，避免自我重定向。
        const current = router.currentRoute.value
        if (current.name !== 'Login') {
          router.push({ name: 'Login', query: { redirect: current.fullPath } })
        }
        message.error(
          needsIdentity
            ? (data?.detail || '该功能需要登录后使用')
            : '登录已过期，请重新登录'
        )
        break
      }

      case 403:
        if (!silentError) message.error(data?.detail || '没有权限执行此操作')
        break

      case 404:
        // 演示模式：404 静默处理（后端接口不存在时页面用 Mock 数据）
        if (isDemoToken(userStore.token)) {
          console.warn('[Demo Mode] API 返回 404，使用 Mock 数据')
          return Promise.reject(error)
        }
        if (!silentError) message.error(data?.detail || '请求的资源不存在')
        break

      case 429:
        // 限流
        if (!silentError) message.warning(data?.detail || '操作过于频繁，请稍后再试')
        break

      case 500:
        if (!silentError) message.error(data?.detail || '服务器内部错误')
        break

      default:
        if (!silentError) message.error(data?.detail || `请求失败 (${status})`)
    }

    return Promise.reject(error)
  }
)

// ====== 便捷方法 ======

/**
 * GET 请求
 */
export function get<T = any>(
  url: string,
  params?: Record<string, any>,
  config?: AxiosRequestConfig
): Promise<T> {
  return request.get(url, { ...config, params }) as Promise<T>
}

/**
 * POST 请求
 */
export function post<T = any>(
  url: string,
  data?: Record<string, any> | FormData | URLSearchParams,
  config?: AxiosRequestConfig
): Promise<T> {
  return request.post(url, data, config) as Promise<T>
}

/**
 * PUT 请求
 */
export function put<T = any>(
  url: string,
  data?: Record<string, any>,
  config?: AxiosRequestConfig
): Promise<T> {
  return request.put(url, data, config) as Promise<T>
}

/**
 * PATCH 请求（**部分更新**）
 *
 * ★ 补它的原因：账户与成员管理后端用的是 PATCH 语义
 *   （`PATCH /accounts/{id}`、`PATCH /accounts/{id}/members/{member_id}`）——
 *   只改传进来的字段。前端此前只有 put/get/post/del，没有 patch，
 *   于是这块能力在补前端时**根本无法被调用**。
 */
export function patch<T = any>(
  url: string,
  data?: Record<string, any>,
  config?: AxiosRequestConfig
): Promise<T> {
  return request.patch(url, data, config) as Promise<T>
}

/**
 * DELETE 请求
 */
export function del<T = any>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  return request.delete(url, config) as Promise<T>
}

// 读取店铺 ID（直接读 localStorage 避免 ESM 循环依赖）
// shop.ts ↔ request.ts 存在互相引用，不能静态 import
function getShopId(): string | null {
  try {
    return localStorage.getItem('current_shop_id')
  } catch {
    return null
  }
}

export default request

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

/**
 * 给 Axios 配置加一个 silent 开关。
 *
 * 划词翻译这类**高频**请求不该每选一次就弹一次「翻译完成」——
 * 调用方传 `{ silent: true }` 即可跳过响应拦截器的成功提示。
 */
declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
    /**
     * `silentError: true` —— 连**错误提示**也交给调用方处理。
     *
     * 与上面的 `silent`（只压成功提示）分开命名，是因为两者语义真的不同：
     * 语音播报这类**后台自动触发**的请求失败时，调用方自己会给出更精确的原因
     * （「当前店铺还没有克隆音色，去设置里创建」）并顺手关掉开关；
     * 若拦截器再按 `detail` 弹一次，用户就会看到两条重复提示。
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

    // 如果响应包含 message，显示提示（silent 请求跳过：高频调用弹提示会刷屏）
    if (data?.message && response.config.method !== 'get' && !response.config.silent) {
      message.success(data.message)
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

        // Token 过期或无效
        // 演示模式：demo-token 被拒时静默处理，由**业务页面**自行降级到 mock。
        // （业务数据在演示模式下的离线兜底依赖这个行为，不要动它。）
        if (isDemoToken(userStore.token) && !needsIdentity) {
          console.warn('[Demo Mode] API 返回 401，业务数据降级处理')
          return Promise.reject(error)
        }

        if (data?.detail?.includes('Token') || data?.detail?.includes('认证')) {
          // 尝试刷新 Token
          const refreshed = await userStore.refreshToken()
          if (refreshed) {
            // 重试原请求
            return request(error.config)
          }
        }

        // 刷新失败，清除状态并跳转登录
        // ★ 这里必须用 clearAuth()（纯本地）而不是 logout()：
        //   logout() 会发 /auth/logout 请求，而此刻后端正在回 401 —— 会递归打转。
        //
        // ★ 同样必须把 demo token 一并清掉：路由守卫已改为按"是不是真身份"
        //   判断，但只清状态、不留残留，才能保证进登录页这一步是确定的。
        userStore.clearAuth()

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

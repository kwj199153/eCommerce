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

    // 如果响应包含 message，显示提示
    if (data?.message && response.config.method !== 'get') {
      message.success(data.message)
    }

    return data
  },
  async (error) => {
    const { response } = error

    if (!response) {
      // 网络错误
      message.error('网络连接失败，请检查网络')
      return Promise.reject(error)
    }

    const { status, data } = response

    switch (status) {
      case 401:
        // Token 过期或无效
        const userStore = useUserStore()

        // 演示模式：demo-token 被拒时不强制登出，静默处理
        if (isDemoToken(userStore.token)) {
          // 静默失败，由各页面自行使用 Mock 数据兜底
          console.warn('[Demo Mode] API 返回 401，使用 Mock 数据')
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
        userStore.logout()
        router.push('/login')
        message.error('登录已过期，请重新登录')
        break

      case 403:
        message.error(data?.detail || '没有权限执行此操作')
        break

      case 404:
        // 演示模式：404 静默处理（后端接口不存在时页面用 Mock 数据）
        if (isDemoToken(userStore.token)) {
          console.warn('[Demo Mode] API 返回 404，使用 Mock 数据')
          return Promise.reject(error)
        }
        message.error(data?.detail || '请求的资源不存在')
        break

      case 429:
        // 限流
        message.warning(data?.detail || '操作过于频繁，请稍后再试')
        break

      case 500:
        message.error(data?.detail || '服务器内部错误')
        break

      default:
        message.error(data?.detail || `请求失败 (${status})`)
    }

    return Promise.reject(error)
  }
)

// ====== 便捷方法 ======

/**
 * GET 请求
 */
export function get<T = any>(url: string, params?: Record<string, any>): Promise<T> {
  return request.get(url, { params })
}

/**
 * POST 请求
 */
export function post<T = any>(url: string, data?: Record<string, any>): Promise<T> {
  return request.post(url, data)
}

/**
 * PUT 请求
 */
export function put<T = any>(url: string, data?: Record<string, any>): Promise<T> {
  return request.put(url, data)
}

/**
 * DELETE 请求
 */
export function del<T = any>(url: string): Promise<T> {
  return request.delete(url)
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

/**
 * 用户状态管理
 *
 * 管理用户登录状态、Token、用户信息等。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { post, get } from '@/api/request'

// ====== 类型定义 ======

export interface UserInfo {
  id: string
  email: string
  name: string
  role: 'admin' | 'user'
  is_active: boolean
  is_verified: boolean
  created_at: string | null
  last_login_at: string | null
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface RegisterData {
  email: string
  password: string
  name?: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserInfo
}

// ====== Store ======

export const useUserStore = defineStore('user', () => {
  // ====== State ======
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<UserInfo | null>(
    localStorage.getItem('user_info')
      ? JSON.parse(localStorage.getItem('user_info')!)
      : null
  )
  const isLoading = ref(false)

  // ====== Getters ======
  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const userEmail = computed(() => user.value?.email || '')
  const userName = computed(() => user.value?.name || user.value?.email || '')

  // ====== Actions ======

  /**
   * 登录
   */
  async function login(credentials: LoginCredentials): Promise<AuthResponse> {
    isLoading.value = true

    try {
      // 使用 URL-encoded 格式（后端 OAuth2PasswordRequestForm 期望 x-www-form-urlencoded）
      const formData = new URLSearchParams()
      formData.append('username', credentials.email)
      formData.append('password', credentials.password)

      const response = await post<AuthResponse>('/auth/login', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })

      // 保存 Token 和用户信息
      setAuthData(response)

      return response
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 注册
   */
  async function register(data: RegisterData): Promise<AuthResponse> {
    isLoading.value = true

    try {
      const response = await post<AuthResponse>('/auth/register', {
        email: data.email,
        password: data.password,
        name: data.name,
      })

      setAuthData(response)
      return response
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 刷新 Access Token
   */
  async function refreshTokenAction(): Promise<boolean> {
    if (!refreshToken.value) {
      return false
    }

    try {
      const response = await post<{ access_token: string; refresh_token: string }>(
        '/auth/refresh',
        { refresh_token: refreshToken.value }
      )

      token.value = response.access_token
      refreshToken.value = response.refresh_token

      localStorage.setItem('access_token', response.access_token)
      localStorage.setItem('refresh_token', response.refresh_token)

      return true
    } catch (error) {
      console.error('Token 刷新失败:', error)
      return false
    }
  }

  /**
   * 获取当前用户信息
   */
  async function fetchUserInfo(): Promise<UserInfo | null> {
    try {
      // /auth/me 返回平铺字段（与 login/register 的 user 字段一致）
      const response = await get<UserInfo>('/auth/me')
      user.value = response
      localStorage.setItem('user_info', JSON.stringify(response))
      return response
    } catch (error) {
      console.error('获取用户信息失败:', error)
      return null
    }
  }

  /**
   * 登出
   */
  function logout() {
    token.value = null
    refreshToken.value = null
    user.value = null

    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
  }

  /**
   * 更新用户名（本地同步）
   */
  function updateUserName(name: string) {
    if (user.value) {
      user.value.name = name
      localStorage.setItem('user_info', JSON.stringify(user.value))
    }
  }

  /**
   * 更新头像 URL（本地同步）
   */
  function updateAvatar(avatarUrl: string) {
    if (user.value) {
      (user.value as any).avatar_url = avatarUrl
      localStorage.setItem('user_info', JSON.stringify(user.value))
    }
  }

  /**
   * 设置认证数据（内部方法）
   */
  function setAuthData(response: AuthResponse) {
    token.value = response.access_token
    refreshToken.value = response.refresh_token
    user.value = response.user

    localStorage.setItem('access_token', response.access_token)
    localStorage.setItem('refresh_token', response.refresh_token)
    localStorage.setItem('user_info', JSON.stringify(response.user))
  }

  // 别名（供拦截器使用）
  const refreshTokenFn = refreshTokenAction

  return {
    // State
    token,
    user,
    isLoading,

    // Getters
    isLoggedIn,
    isAdmin,
    userEmail,
    userName,

    // Actions
    login,
    register,
    refreshToken: refreshTokenFn,
    fetchUserInfo,
    logout,
    updateUserName,
    updateAvatar,
  }
})

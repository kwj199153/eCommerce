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
  // ★ 第 100 轮：自助管理资料（后端 /auth/me 与 /users/profile 都会带回）
  phone?: string | null
  company?: string | null
  avatar_url?: string | null
  /** 通知偏好（后端保证返回**完整**六项，见 models.merge_notification_prefs） */
  notification_prefs?: Record<string, boolean>
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

  /**
   * 手里是否有一枚**真实可用**的 refresh_token。
   *
   * ★ 第 117 轮新增，供 `api/request.ts` 的 401 判定使用。
   *   修复前拦截器**读不到**这个事实 —— 那时 401 分支靠猜后端文案
   *   （`detail.includes('Token')`）来决定要不要刷新，于是文案一变行为就变。
   *
   * ★ 为什么 `isDemoToken` 那一层判断不是冗余：
   *   `refreshToken` 的初值读的是 `localStorage.getItem('refresh_token')`，
   *   而演示登录恰恰往那个键里写了 `demo-refresh-token`（见 views/Login.vue）。
   *   所以**刷新页面之后**内存里真的会握着一枚 demo 伪凭据 ——
   *   后端一律不认，照它去刷只会得到一次注定失败的请求。
   */
  const hasRefreshToken = computed(
    () => !!refreshToken.value && !isDemoToken(refreshToken.value)
  )
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
   * 清空本地认证态（**纯本地、同步、不发请求**）
   *
   * ★ 必须与 `logout()` 分开：401 拦截器里调的就是这一个。
   *   若在 401 分支里调 `logout()`（会发请求），一旦后端仍返回 401，
   *   就会「401 → 登出 → 又 401 → 又登出」递归打转。
   */
  function clearAuth() {
    token.value = null
    refreshToken.value = null
    user.value = null

    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_info')
  }

  /**
   * 登出：**先让服务端撤销，再清本地**
   *
   * ★ 只清 localStorage 不叫登出：那枚 token 在服务端仍然有效，
   *   有效期内谁拿到它都能继续用（access token 有 30 分钟窗口）。
   *   后端 `/auth/logout` 会把 jti 写进黑名单，所以必须真的发这一枪。
   *
   * ★ 同时带上 refresh_token：只撤 access 的话，refresh 还能换出全新的 access，
   *   「登出」等于被绕过（后端 `LogoutRequest` 注释里写明了这一点）。
   *
   * ★ 撤销失败也**必须**清本地 —— 不能因为 Redis 挂了（后端回 503）
   *   就把用户卡在「以为登出了、其实还登录着」的状态里。
   */
  async function logout() {
    try {
      if (token.value) {
        await post(
          '/auth/logout',
          { refresh_token: refreshToken.value },
          { silent: true }
        )
      }
    } catch (error) {
      console.warn('服务端登出撤销失败，本地状态仍会清除:', error)
    }
    clearAuth()
  }

  /**
   * 换发新 token 对（改密码后调用）
   *
   * ★ 后端 `/auth/change-password` 会提升 token_version ⇒ **当前这枚 token 也会失效**，
   *   所以它在响应里直接返回了一对新 token。前端不消费 = 用户改完密码当场掉线。
   */
  function applyTokenPair(accessToken: string, refreshTokenValue?: string | null) {
    if (!accessToken) return
    token.value = accessToken
    localStorage.setItem('access_token', accessToken)
    if (refreshTokenValue) {
      refreshToken.value = refreshTokenValue
      localStorage.setItem('refresh_token', refreshTokenValue)
    }
  }

  /**
   * 用后端返回的 user 整体替换本地用户信息
   *
   * ★ 为什么必须"整体替换"而不是逐字段改：
   *   `PUT /users/profile` 的响应里带回了**完整** user（含 phone / company）。
   *   只调 `updateUserName()` 的话，用户改了电话、界面却仍显示旧值 ——
   *   要等下次刷新才更新，看起来就像"没保存成功"。
   */
  function setUser(next: UserInfo) {
    user.value = next
    localStorage.setItem('user_info', JSON.stringify(next))
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
    clearAuth,
    applyTokenPair,
    setUser,
    updateUserName,
    updateAvatar,
  }
})

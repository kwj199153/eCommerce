/**
 * 用户状态管理
 *
 * 管理用户登录状态、Token、用户信息等。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { post, get } from '@/api/request'
import { message } from 'ant-design-vue'
import { rememberAccount } from '@/config/knownAccounts'
import { isDemoToken } from '@/config/demoMode'
import { forgetRemembered, getRemembered, isRemembered, setRemembered } from '@/config/authVault'

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
  /**
   * 是否把这枚登录凭据交给服务端托管（= 本机免密切换）。
   *
   * ★ 缺省 true —— 不传即沿用「登录后就记住」的既有行为。
   *   只有登录页的「记住登录状态」勾选框会传 false。
   * ★ 名字叫 remember 而不是 rememberPassword：本项目不保存密码，
   *   服务端加密托管的是 refresh token（第 119 轮决策）。
   */
  remember?: boolean
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
      //
      // ★ 第 122 轮：第二个参数是「要不要在本机记住」，由登录页的
      //   「记住登录状态」勾选框给出。不传视为 true，所以 register()
      //   那条路不受影响（刚注册的账号必然要常用，默认记住）。
      setAuthData(response, credentials.remember !== false)

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

      // ★ 第 119 轮：本机不再保存凭据（改由服务端加密托管），
      //   但 `/auth/refresh` **会签发新的一枚** refresh token（且不拉黑旧的），
      //   所以服务端那份容器必须跟着更新 —— 否则下次免密切换拿到的是
      //   「上一代」凭据：短期仍有效，但语义已经不是「最近一次登录状态」了。
      //   ★ 不 await、不抛错：刷新本身已经成功，登记失败不该把它拖垮。
      void enrollDevice()

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
   *   有效期内谁拿到它都能继续用（access token 默认 60 分钟，本地 .env 覆盖为 24 小时）。
   *   后端 `/auth/logout` 会把 jti 写进黑名单，所以必须真的发这一枪。
   *
   * ★ 同时带上 refresh_token：只撤 access 的话，refresh 还能换出全新的 access，
   *   「登出」等于被绕过（后端 `LogoutRequest` 注释里写明了这一点）。
   *
   * ★ 撤销失败也**必须**清本地 —— 不能因为 Redis 挂了（后端回 503）
   *   就把用户卡在「以为登出了、其实还登录着」的状态里。
   */
  async function logout() {
    // ★ 第 118 轮：先取出当前身份 —— 本函数结尾的 clearAuth() 会把 user 清掉，
    //   而下面清理凭据仓库时还需要它。
    const leavingUserId = user.value?.id || ''

    // ★★★ 第 119 轮：顺序不变量 —— `/auth/device/forget` 必须在 `/auth/logout` **之前**。
    //
    //   `logout` 会把当前 access / refresh 的 jti 写进 Redis 黑名单。之后再拿这枚
    //   access token 去调 `/auth/device/forget` 会直接 401 ⇒ 结果是
    //   「已经退出登录，但这个账号在本机仍然免密」—— 名不副实。
    //
    //   ★ 万一这一步失败也不影响正确性：logout 撤销的正是容器里那一枚，
    //     它随即成为死凭据，下次免密切换会被服务端拒绝并自动清除（自愈）。
    if (leavingUserId) {
      await forgetDeviceAccount(leavingUserId)
    }

    try {
      if (token.value) {
        // ★ silentError 与 silent 语义不同（见 request.ts 的类型声明）：
        //   `silent` 只压「成功提示」，`silentError` 才压错误提示。
        //   登出是**用户主动行为**，它失败不该以「登录已过期，被踢出去」
        //   的姿态呈现 —— 而且紧接着本函数就会 clearAuth()，
        //   再弹一条错误提示纯属噪声。
        await post(
          '/auth/logout',
          { refresh_token: refreshToken.value },
          { silent: true, silentError: true }
        )
      }
    } catch (error) {
      console.warn('服务端登出撤销失败，本地状态仍会清除:', error)
    }
    clearAuth()
    // ★ 退出登录 = **这个**账号不再在本机保留登录状态。
    //   只删它自己、不动其它账号 —— 精确语义；彻底清干净由「清空记录」承担。
    //   ★ 不删的话「退出登录」名不副实：那枚凭据还在**服务端**躺着，
    //     下一次点它就又能直接进来。
    forgetRemembered(leavingUserId)
  }

  // ==================================================================
  //  本机免密（★ 第 119 轮）：凭据由**服务端**加密托管
  // ------------------------------------------------------------------
  //  为什么网络调用放在这里而不是 config/authVault.ts：
  //    `api/request.ts` 已经 import 了 `@/stores/user`，若 authVault 再
  //    import request，就构成 user → authVault → request → user 的**循环依赖**。
  //    所以本地索引（零依赖）与网络调用（此处）刻意分成两层。
  // ==================================================================

  /**
   * 把当前这枚 refresh token 交给服务端托管（本机免密的前提）。
   *
   * ★ 这是**独立的一次调用**，与登录解耦：它失败只意味着
   *   「这次没记住、下次切换要输密码」，绝不该让登录看起来失败。
   *   故调用点一律 `void enrollDevice()`，不 await、不抛错。
   *
   * ★ 服务端返回的 `accounts` 是**权威清单**，直接覆盖本地索引 ——
   *   本地那份只是「首屏不闪」的缓存。
   *
   * ★★★ 第 120 轮新增 `notify`：**只有「用户用密码登录」那条路才该有反馈。**
   *
   *   起因是老板的实测反馈「现在切换账号还是要重新输入密码」——
   *   他刚用密码登录过一次，那一次**已经**把免密通道建好了，
   *   但整个过程完全静默，界面上没有任何变化 ⇒ 他无从知道
   *   「刚才那次输密码是有价值的」，于是下次再切又以为是坏的。
   *
   *   ★ 为什么必须做成参数而不是无条件提示：本函数还会被
   *     `refreshTokenAction()` 调用 —— 那是 access token 每次过期时的
   *     **后台刷新**，一条提示会在用户毫不知情的情况下反复弹出来刷屏。
   *   ★ 为什么还要「仅当账号是新增的」才提示：同一个账号反复登录
   *     （比如每次清缓存后重登）不该每次都弹 ——
   *     只有**清单从无到有**那一刻才是真正的新信息。
   */
  async function enrollDevice(notify = false): Promise<boolean> {
    // 演示模式的伪凭据后端一律不认，不必白跑一次请求
    if (!refreshToken.value || isDemoToken(refreshToken.value)) return false
    // 记录「调用前是不是已经在清单里」—— 服务端响应回来后会整体覆盖索引，
    // 那时再判断就问不出「是不是新增」了。
    const uid = user.value?.id || ''
    const wasRemembered = uid ? isRemembered(uid) : true
    try {
      const res = await post<{ ok: boolean; accounts: string[]; total: number }>(
        '/auth/device/enroll',
        { refresh_token: refreshToken.value },
        { silent: true, silentError: true }
      )
      if (res && Array.isArray(res.accounts)) setRemembered(res.accounts)
      const ok = !!(res && res.ok)
      if (ok && notify && uid && !wasRemembered) {
        // ★ 只在这一刻提示：这正是「以后不用再输密码」这件事发生的时候。
        //   措辞刻意点明"下次"，因为用户此刻刚输完密码，
        //   他最想知道的就是"下次还要不要输"。
        message.success('已记住此账号，下次可直接免密切换')
      }
      return ok
    } catch (error) {
      // ★ 不弹提示：这是「便利功能」的登记失败，用户此刻并不在做切换动作，
      //   弹一条错误只会造成困惑。但必须留下日志，便于排查。
      console.warn('本机免密未生效（服务端拒绝写入凭据）:', error)
      return false
    }
  }

  /**
   * 拉取服务端的权威清单（本机记住了哪些账号）。
   *
   * ★ 失败时返回空数组而不是保留旧值：宁可界面上不显示「免密」标记、
   *   让用户多输一次密码，也不要显示一个点了会失败的标记。
   */
  async function fetchRememberedAccounts(): Promise<string[]> {
    try {
      const res = await get<{ accounts: string[]; total: number }>(
        '/auth/device/accounts',
        { silent: true, silentError: true }
      )
      const ids = res && Array.isArray(res.accounts) ? res.accounts : []
      setRemembered(ids)
      return ids
    } catch (error) {
      // ★★★ 第 120 轮修正：失败时**保留本地已有标记**，删除原来的 `setRemembered([])`。
      //
      //   原实现把「拿不到权威清单」与「权威清单是空的」当成了同一件事。
      //   后果：access token 恰好过期、或后端抖一下，这个请求就失败，
      //   本地索引被整体清空 ⇒ 界面立刻把所有账号渲染成「需密码」，
      //   而服务端其实一条都没丢、点下去照样能免密。
      //   （本项目既有判据：缺失应表现为「序列不存在」，而不是「值恒为 0」。）
      //
      //   ★ 两个方向的失败代价并不对称，这一点决定了该往哪边兜：
      //     · 保留旧值 → 最坏是「显示免密、点了要密码」，
      //       后端会正确拒绝并顺手清掉坏凭据 —— **安全的失败方向**；
      //     · 清空索引 → 用户以为免密全失效，转头去输密码，
      //       而真实状态是我们自己弄丢的。
      console.warn('读取本机已记住账号失败，保留本地已有标记:', error)
      return getRemembered()
    }
  }

  /**
   * 免密切换到本机记住的另一个账号（★ 第 119 轮起走服务端托管）
   *
   * ★ 与第 118 轮的实现差别：那时前端自己存着目标账号的 refresh token，
   *   要「先换 token、再拉 /me」两步；现在服务端一次就把 token 对与
   *   user 一起给了 ⇒ **少一次往返**，也少一处「身份与界面错位」的可能。
   *
   * ★ 失败一律返回 null 让调用方处理（清掉本地标记 + 去登录页）：
   *   常见原因是服务端已把它撤销（在别处登出过）、改密导致 `tv` 比对失败、
   *   或该凭据已过期。
   *
   * ★ 不会触发 401 递归：`/auth/device/*` 已列入拦截器豁免端点
   *   （见 `api/authRefreshPolicy.ts`）—— 它返回 401 是**业务结论**
   *   （「这枚凭据失效了」），不是「该刷新当前会话」的信号。
   */
  async function switchToAccount(targetUserId: string): Promise<UserInfo | null> {
    if (!targetUserId) return null
    try {
      const res = await post<{
        access_token: string
        refresh_token: string
        user: UserInfo
        remembered: boolean
      }>('/auth/device/switch', { user_id: targetUserId })

      if (!res || !res.access_token || !res.user) return null

      // ★ 顺序要紧：先落 token 再落 user。反过来的话，紧接着发出的请求
      //   会带着**上一个账号**的 token，而界面已经显示新名字了。
      token.value = res.access_token
      refreshToken.value = res.refresh_token
      user.value = res.user
      localStorage.setItem('access_token', res.access_token)
      localStorage.setItem('refresh_token', res.refresh_token)
      localStorage.setItem('user_info', JSON.stringify(res.user))
      rememberAccount(res.user)

      if (!res.remembered) {
        // 切换本身成功了，但新凭据没能记进本机 ⇒ 下次还得输密码。
        // ★ 本地标记必须跟着去掉，否则界面会继续显示「免密」骗人。
        forgetRemembered(res.user.id)
      }

      return res.user
    } catch (error) {
      console.warn('免密切换失败（凭据可能已被撤销或过期）:', error)
      return null
    }
  }

  /**
   * 让服务端忘掉本机上的某一个账号（退出登录 / 从列表移除时调用）。
   *
   * ★ 语义边界：只删**这一个**。清空整台机器归 `forgetDeviceAll`。
   * ★ 失败不抛错：调用方（登出流程）已经完成了真正的撤销，
   *   这一步只是「顺手清理」，不该让登出报错。
   */
  async function forgetDeviceAccount(targetUserId: string): Promise<boolean> {
    if (!targetUserId) return false
    try {
      const res = await post<{ ok: boolean; accounts: string[]; total: number }>(
        '/auth/device/forget',
        { user_id: targetUserId },
        { silent: true, silentError: true }
      )
      if (res && Array.isArray(res.accounts)) setRemembered(res.accounts)
      return true
    } catch (error) {
      console.warn('通知服务端忘记本机凭据失败（将靠撤销后自愈）:', error)
      return false
    }
  }

  /**
   * 清空整台设备记住的全部账号（「清空记录」走这条）。
   *
   * ★ 返回 false 表示**服务端没清掉**（例如 Redis 不可达）——
   *   调用方必须据此提示用户，不能假装清空了。
   *   用户以为凭据已经没了（可能因此把电脑借给别人），
   *   而服务端还留着，是典型的静默假成功。
   */
  async function forgetDeviceAll(): Promise<boolean> {
    try {
      await post('/auth/device/forget-all', {}, { silent: true, silentError: true })
      return true
    } catch (error) {
      console.warn('清空本机凭据失败:', error)
      return false
    }
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
      // ★ 第 119 轮：改密会提升 token_version ⇒ 服务端容器里那枚旧凭据已失效，
      //   必须把换发出来的这一枚重新登记，否则切回时拿到的是死凭据。
      void enrollDevice()
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
   *
   * ★ 第 113 轮：这里同时是**账号历史的唯一写入点**（「切换账号」用）。
   *
   *   为什么记在这里、而不是别处：
   *     · 本函数只被 `login()` / `register()` 调用 —— 也就是**真实登录**的
   *       必经之路。演示模式走的是 `$patch` + 直接写 localStorage
   *       （见 views/Login.vue、router/index.ts），不经过它，
   *       于是"演示身份不进历史"是**结构性保证**，不需要额外判断。
   *     · 注释只写标识（id/email/name），**绝不写 token**，
   *       理由见 `config/knownAccounts.ts` 顶部。
   */
  function setAuthData(response: AuthResponse, remember = true) {
    token.value = response.access_token
    refreshToken.value = response.refresh_token
    user.value = response.user

    localStorage.setItem('access_token', response.access_token)
    localStorage.setItem('refresh_token', response.refresh_token)
    localStorage.setItem('user_info', JSON.stringify(response.user))

    // ★ 账号历史与免密清单是**两件事**，别混：这一行记的是「用过这台机器的
    //   账号」（只存 id/email/name/时间），与下面的 remember 无关 ——
    //   用户取消勾选时，他也不该从「最近登录」里消失：那只是历史，
    //   点一下仍然要输密码，从没承诺过免密。
    rememberAccount(response.user)

    if (remember) {
      // ★ 第 119 轮：把凭据交给**服务端**托管 —— 「切换账号」免密全靠它。
      //   落点与 rememberAccount 相同：本函数是**真实登录**的唯一必经之路，
      //   演示模式走 $patch + 直接写 localStorage、不经过这里，
      //   所以 demo 伪凭据是**结构性**进不来的，不需要额外判断
      //   （enrollDevice 里另有一道 isDemoToken 校验，两层都留着）。
      //   ★ 不等它完成：登录已经成功，免密登记失败不该让登录看起来失败。
      //   ★ 第 120 轮：这里传 `true` —— 用户**刚刚用密码登录**，
      //     如果这个账号此前没被本机记住，正是该告诉他
      //     「以后不用再输密码了」的那一刻（见 enrollDevice 的 notify 说明）。
      //   ★ 第 122 轮：整段移进 if (remember) —— 用户取消勾选时不走这里。
      //     另外两处调用（refreshTokenAction / applyTokenPair）是后台行为，
      //     与勾选框无关，保持静默。
      void enrollDevice(true)
    } else {
      // ★★★ 第 122 轮：用户**明确**选择了「不要在这台设备记住我」。
      //
      //   ★ 为什么不能只是「不 enroll、什么都不做」：
      //     这个账号可能**之前已经被记住过**（上一次登录时勾着）。
      //     若这里什么都不做，他取消勾选后再去切换 —— 依然免密进来。
      //     勾选框于是成了摆设，而且正是最令人反感的那类偏差：
      //     「我明明取消了，却还是照旧」。
      //   ⇒ 取消勾选 = **撤销**，而不是「这次不新增」。
      //
      //   ★ 顺序：先清本地标记，再让服务端删。这样即便服务端那一步失败，
      //     界面也只会显示「需密码」（安全方向：最多多输一次密码），
      //     而不会出现「显示免密、点了却失败」这种骗人的状态。
      forgetRemembered(response.user.id)
      void forgetDeviceAccount(response.user.id)
    }
  }

  // 别名（供拦截器使用）
  const refreshTokenFn = refreshTokenAction

  return {
    // State
    token,
    user,
    isLoading,
    /**
     * refresh_token 的**值**（只读出口）。
     *
     * ★ 为什么会多出这么个名字：`refreshToken` 这个名字在下面被
     *   **动作函数**占用了（`refreshToken: refreshTokenFn`），
     *   于是本 state 一直没有对外出口 —— 这就是 views/Login.vue 里那段
     *   「store 暴露的 state 里没有 refreshToken」注释的由来。
     *   改名会破坏 `userStore.refreshToken()` 这个既有调用（拦截器在用），
     *   所以给它一个独立出口，两边都不动。
     */
    refreshTokenValue: refreshToken,

    // Getters
    isLoggedIn,
    isAdmin,
    userEmail,
    userName,
    hasRefreshToken,

    // Actions
    login,
    register,
    refreshToken: refreshTokenFn,
    fetchUserInfo,
    logout,
    clearAuth,
    switchToAccount,
    enrollDevice,
    fetchRememberedAccounts,
    forgetDeviceAccount,
    forgetDeviceAll,
    applyTokenPair,
    setUser,
    updateUserName,
    updateAvatar,
  }
})

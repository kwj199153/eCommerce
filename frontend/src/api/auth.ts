/**
 * 账号安全 API（台账 #1151）
 *
 * ============================================================================
 * ★ 为什么单独一个文件
 * ============================================================================
 * 后端 `core/identity/security_router.py` **早就**实现了 7 个端点
 * （前缀 `/api/v1/auth`，见 `main.py` 的 `include_router(..., prefix="/api/v1")`），
 * 但前端此前**一个都没调用**：全仓 grep `forgot-password` / `reset-password` /
 * `verify-email` / `logout-all` 均为 **0 处**。
 *
 * 后果不是"少个按钮"，而是**两条断链**：
 *   `core/identity/email_tokens.py::_link()` 拼出的邮件链接形如
 *   `{PUBLIC_SITE_URL}/reset-password?token=…` 与 `{PUBLIC_SITE_URL}/verify-email?token=…`，
 *   而 `router/index.ts` 里**没有这两条路由** ⇒ 用户点开邮件是**空白页**。
 *
 * ⇒ 本文件负责"能调到"，`views/ResetPassword.vue` / `views/VerifyEmail.vue`
 *   负责"点得开"，`scripts/check-auth-frontend-wiring.cjs` 负责
 *   "以后再加一条邮件链接却没建路由时，构建直接红"。
 *
 * ============================================================================
 * ★ 三条必须原样带上的后端语义（改这里之前先读 security_router.py 的 docstring）
 * ============================================================================
 *  ① `/forgot-password` **无论邮箱是否存在，响应完全一致**
 *     （`_FORGOT_GENERIC_MESSAGE`：防邮箱枚举）。
 *     ⇒ 前端**不得**按响应去区分"这个账号存不存在"，也**不得**自己另写话术 ——
 *       两处各写一份，早晚分叉成"能枚举账号"的那一版。
 *
 *  ② `/forgot-password` 在**邮件服务未启用**时回 **503**。
 *     这是与具体邮箱无关的**全局配置状态**，不构成枚举通道，
 *     而且是唯一"必须让用户知道"的失败 —— 否则他会一直等一封永远不会来的信。
 *     ⇒ 必须显式显示这句 detail，不能当成普通错误吞掉。
 *
 *  ③ `/reset-password` 的 400 是**统一话术**「重置链接无效或已过期，请重新申请」
 *     （无效 / 过期 / 已用过三者刻意不区分），直接透传即可，不要自作聪明细化。
 *     成功话术「密码已重置，请用新密码登录」同理。
 *
 * ============================================================================
 * ★ 为什么每个函数都留一个 `config` 口子
 * ============================================================================
 * 这 5 个端点的调用方**都要自己渲染常驻的错误面**（页面级 alert / 表单下方红字），
 * 而不是"弹一下就没了"的 toast —— 例如"重置链接已过期"必须**留在页面上**，
 * 用户才看得见下一步该干什么。
 * 不传 `silentError: true` 的话，同一个原因会被拦截器再弹一次（两份提示、文案还不同）。
 * 这与 `api/billing.ts` / `api/adAnalysis.ts` 的做法一致。
 */

import type { AxiosRequestConfig } from 'axios'

import { post } from '@/api/request'

// ====== 响应类型（与 security_router.py 的 return 一一对应）======

/** 后端多数端点统一返回 `{"message": "..."}` */
export interface AuthMessageResponse {
  message: string
}

/** `POST /auth/verify-email`：成功时额外带回更新后的用户（`user_to_dict`） */
export interface VerifyEmailResponse {
  message: string
  user?: Record<string, unknown>
}

/** `POST /auth/verify-email/resend`：**如实回报发信结果**，不谎报成功 */
export interface ResendVerifyEmailResponse {
  message: string
  email_sent: boolean
  /** 本来就已验证过 ⇒ `message` 是"无需重复发送" */
  email_sent_already?: boolean
}

/** `POST /auth/logout-all` */
export interface LogoutAllResponse {
  message: string
  /** 提升后的 token_version（该用户全部旧 token 已结构性失效） */
  token_version: number
}

// ====== 忘记密码 / 重置密码 ======

/**
 * 申请密码重置邮件。
 *
 * ★ 成功与"邮箱不存在"返回的是**同一个对象**，调用方只能把它当"已受理"处理。
 * ★ 需要单独处理的失败只有一种：503（`邮件服务未启用…`）——
 *   调用方应把它的 `detail` 原样显示出来。其余失败交给统一拦截器。
 */
export function forgotPassword(
  email: string,
  config?: AxiosRequestConfig
): Promise<AuthMessageResponse> {
  return post<AuthMessageResponse>('/auth/forgot-password', { email }, config)
}

/**
 * 用邮件里的一次性 token 重置密码。
 *
 * ★ 成功后**不会**自动登录（后端刻意如此：重置密码往往意味着"账号可能已失窃"）——
 *   调用方应当把用户引导到登录页，让他用新密码主动登一次。
 *
 * @param token 邮件链接 `?token=` 带过来的原串（或用户手工粘贴的降级路径）
 * @param newPassword 新密码，后端要求 ≥6 位（`Field(..., min_length=6)`）
 */
export function resetPassword(
  token: string,
  newPassword: string,
  config?: AxiosRequestConfig
): Promise<AuthMessageResponse> {
  return post<AuthMessageResponse>(
    '/auth/reset-password',
    { token, new_password: newPassword },
    config
  )
}

// ====== 邮箱验证 ======

/**
 * 用邮件里的 token 完成邮箱验证（置 `is_verified = True`）。
 *
 * ★ 无需登录：用户可能是在**未登录**状态下点的邮件链接。
 */
export function verifyEmail(
  token: string,
  config?: AxiosRequestConfig
): Promise<VerifyEmailResponse> {
  return post<VerifyEmailResponse>('/auth/verify-email', { token }, config)
}

/**
 * 重发验证邮件。
 *
 * ★ **需要登录**：收件人由服务端从当前登录态取（`get_current_user`），
 *   请求体是空的 —— 不要把邮箱塞进来，服务端不认，也不该认。
 * ★ 该端点即使发信失败也回 200（"你已登录"这件事成功了），
 *   失败信息在 `email_sent: false` + `message` 里 ⇒ 调用方**必须读 `email_sent`**，
 *   不能只看"没抛异常"就报成功。
 */
export function resendVerifyEmail(
  config?: AxiosRequestConfig
): Promise<ResendVerifyEmailResponse> {
  return post<ResendVerifyEmailResponse>('/auth/verify-email/resend', {}, config)
}

// ====== 登出所有设备 ======

/**
 * 登出**所有**设备（含当前这台）。
 *
 * ★ 别被名字骗了：它走的是 `token_version += 1`，**不是**"踢掉其他设备"。
 *   语义与 `/auth/change-password` 的后半段相同 —— 当前这枚 token **也会立刻失效**。
 *   ⇒ 调用方在成功后必须清本地登录态并跳登录页；按钮文案也不能写"其他设备"。
 * ★ 它存在的意义不是"功能更全"，而是**给用户一条永远可用的出路**：
 *   当 Redis 故障导致 `/auth/logout` 返回 503 时，走 DB 版本号的这条路依然生效。
 */
export function logoutAll(config?: AxiosRequestConfig): Promise<LogoutAllResponse> {
  return post<LogoutAllResponse>('/auth/logout-all', {}, config)
}

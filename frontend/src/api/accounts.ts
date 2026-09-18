/**
 * 账户与成员管理 API
 *
 * 对应后端 `core/auth/accounts_router.py`（prefix `/api/v1/accounts`）——
 * 这条链路在后端**早已建成**（9 个端点 + 4 角色 × 5 能力的能力矩阵），
 * 但前端此前**零调用点**：后端能力全部闲置，成员管理在界面上完全没有入口。
 * 本文件把它接上。
 *
 * ★ 权限判定**只在后端**（`core/auth/accounts.require_account_permission`）。
 *   本文件里的 `ACCOUNT_ROLES` 是**展示元数据**（中文标签、说明、可否分配），
 *   不是第二套判定 —— 前端只据此隐藏按钮，越权请求后端照样拒。
 *   两套判定的必然结果是"按钮能点，点了报错"。
 */

import type { AxiosRequestConfig } from 'axios'
import { get, post, patch, del } from '@/api/request'

/**
 * 本文件所有请求读的都是**身份与授权数据**（账户 / 成员）⇒ 统一声明
 * `requiresIdentity`，让 401 走正常通路（清状态 + 跳登录 + 带回跳），
 * 而不是被演示模式的静默分支吞掉。
 *
 * ★ 抽成常量而不是每处写字面量：这条标志的语义是"**整个模块**读的是身份数据"，
 *   属于模块级属性，不是每个调用各自的决定。将来加第 10 个端点时就不会再有人
 *   漏写 —— 而漏写的症状（"401 被静默吞掉，页面只说一句请登录却没有入口"）
 *   在 code review 里几乎看不出来。
 */
const IDENTITY: AxiosRequestConfig = { requiresIdentity: true }

export type AccountRoleValue = 'owner' | 'admin' | 'member' | 'viewer'

/**
 * 容器（后端 `accounts` 表）。
 *
 * ★ 第 110 轮：此处曾有 `kind`（personal / team），已删除 —— 那个二分被证伪：
 *   「私有」不是一种**容器类型**，而是**成员数的一个取值**（成员数 = 1 时
 *   观感私有，> 1 就是共享）——「一个人也可以是一人团」。
 *   ⇒ 界面一律显示容器**自己的名字**，不再有「个人 / 团队」标签。
 *   ★ 这**不只是**前端去掉了几个导出：后端字段与枚举也已由迁移
 *     `b7e3f1a9c2d4` 删除。字段只要还在，标签就会被重新长出来。
 */
export interface AccountInfo {
  id: string
  name: string
  owner_user_id: string
  is_active: boolean
  created_at: string | null
  updated_at: string | null
  /** 当前用户在本账户内的**团队角色**；平台超管但非成员时为 null */
  role: AccountRoleValue | null
  is_owner: boolean
  is_platform_admin: boolean
  store_count: number
  member_count: number
}

export interface AccountMember {
  id: string
  account_id: string
  user_id: string
  email: string | null
  name: string | null
  role: AccountRoleValue
  status: 'active' | 'removed'
  invited_by: string | null
  created_at: string | null
  joined_at: string | null
  /** ★ 后端派生的只读标记：owner 那条记录不可改角色 / 不可移除 */
  is_owner: boolean
}

/**
 * 角色展示元数据 —— 与后端 `AccountRole` **一一对应**。
 *
 * ★ `owner` 的 `assignable` 恒为 false：账户只能有一个所有者，
 *   后端 `ASSIGNABLE_ACCOUNT_ROLES` 明确把 owner 排除在外（尝试分配会被 400 拒）。
 *   前端下拉里因此不该出现它 —— 否则用户会一直点到报错为止。
 *
 * ★ 权限能力（`ACCOUNT_PERMISSIONS`：account.read / store.write /
 *   store.delete / member.manage / account.manage）的真源在后端，
 *   这里只写**给人看的一句话说明**，不参与任何判定。
 */
export const ACCOUNT_ROLES: {
  value: AccountRoleValue
  label: string
  desc: string
  assignable: boolean
  color: string
}[] = [
  { value: 'owner', label: '所有者', desc: '账户唯一所有者，可管理账户本身', assignable: false, color: 'gold' },
  { value: 'admin', label: '管理员', desc: '可邀请与调整成员、管理店铺', assignable: true, color: 'blue' },
  { value: 'member', label: '成员', desc: '可管理店铺，不能管理成员', assignable: true, color: 'green' },
  { value: 'viewer', label: '只读', desc: '仅查看，不能修改', assignable: true, color: 'default' },
]

/** 可分配角色（下拉用） */
export const ASSIGNABLE_ROLES = ACCOUNT_ROLES.filter((r) => r.assignable)

export function roleLabel(role?: string | null): string {
  return ACCOUNT_ROLES.find((r) => r.value === role)?.label || '—'
}

export function roleColor(role?: string | null): string {
  return ACCOUNT_ROLES.find((r) => r.value === role)?.color || 'default'
}

/**
 * 当前用户能否管理该账户的成员（`member.manage` 的 UI 镜像）。
 *
 * ★ 只用来决定"按钮显不显示"，**不是**授权。真判定在后端，
 *   越权调用会得到 404（后端刻意用 404 而非 403，避免暴露资源是否存在）。
 */
export function canManageMembers(account: AccountInfo | null): boolean {
  if (!account) return false
  return account.is_platform_admin || account.role === 'owner' || account.role === 'admin'
}

// ====== 账户 ======

/** 我可见的账户（自己拥有的 + 我是 ACTIVE 成员的；平台超管拿到全部） */
export function listAccounts() {
  return get<{ accounts: AccountInfo[]; total: number }>('/accounts', undefined, IDENTITY)
}

/** 当前用户的默认容器（后端幂等 get-or-create；判据见 `ensure_default_account`） */
export function getMyAccount() {
  return get<{ account: AccountInfo }>('/accounts/me', undefined, IDENTITY)
}

/**
 * 新建账户（当前用户成为 owner）。后端返回 `{"account": {...}}`。
 *
 * ★ 修正返回类型（B 档 2026-09-17）：此前这里声明为 `AccountInfo`，
 *   而响应体实际是 `{"account": {...}}` ⇒ 调用方写的 `res.id` **恒为 undefined**
 *   （新建账户后不会切到新账户），且**不报任何错** ——
 *   类型断言不是运行时校验，tsc 拦不住这种不一致。
 */
export function createAccount(name: string) {
  return post<{ account: AccountInfo }>('/accounts', { name }, IDENTITY)
}

export function getAccount(accountId: string) {
  return get<AccountInfo>(`/accounts/${accountId}`, undefined, IDENTITY)
}

/** 改账户名（需 account.manage，即仅 owner） */
export function updateAccount(accountId: string, name: string) {
  return patch<AccountInfo>(`/accounts/${accountId}`, { name }, IDENTITY)
}

// ====== 成员 ======

export function listMembers(accountId: string, includeRemoved = false) {
  const qs = includeRemoved ? '?include_removed=true' : ''
  return get<{ members: AccountMember[]; total: number }>(
    `/accounts/${accountId}/members${qs}`,
    undefined,
    IDENTITY
  )
}

/** 邀请成员（需 member.manage）。★ 用 email：邀请人不知道也不该知道对方 UUID */
export function inviteMember(accountId: string, email: string, role: AccountRoleValue) {
  return post<AccountMember>(`/accounts/${accountId}/members`, { email, role }, IDENTITY)
}

/** 改成员角色 / 状态（需 member.manage）。owner 那条记录后端会以 400 拒绝 */
export function updateMember(
  accountId: string,
  memberId: string,
  data: { role?: AccountRoleValue; status?: 'active' | 'removed' }
) {
  return patch<AccountMember>(`/accounts/${accountId}/members/${memberId}`, data, IDENTITY)
}

/** 移除成员（软删：status -> removed）。owner 不可移除 */
export function removeMember(accountId: string, memberId: string) {
  return del<AccountMember>(`/accounts/${accountId}/members/${memberId}`, IDENTITY)
}

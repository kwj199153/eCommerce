/**
 * 审计日志 API
 *
 * 对应后端 `core/audit/router.py`（prefix `/api/v1/audit`）——**只有两个只读端点**：
 *   · `GET /logs`    分页 + 过滤查询（动作 / 结果 / 目标类型 / 目标 id / 执行者 id / 时间区间）
 *   · `GET /actions` 动作目录（筛选下拉的**唯一真源**）
 *
 * ============================================================================
 * ★★ 权限不在本文件判定
 * ============================================================================
 * 读口要求**平台超管**（后端一律挂 `Depends(get_admin_user)`）：
 *   匿名 / 无效 token ⇒ **401**；已登录但非平台超管 ⇒ **403**。
 * 本文件不做任何权限判定，只声明"这里读的是身份与授权数据"（`requiresIdentity`），
 * 让 401 走正常通路（清状态 + 跳登录 + 带回跳），而不是像业务数据那样
 * 被演示模式的静默分支吞掉 —— 吞掉的后果是"需要登录"这件事永远送不到登录入口上。
 *
 * 界面上那层"非超管不显示入口"只是**展示层**的收敛（见 `AccountMenu.vue`），
 * 是后端判定的镜像而不是替代品：越权请求后端照样 403。
 *
 * ============================================================================
 * ★ 刻意**不写第二份动作清单**
 * ============================================================================
 * `GET /actions` 下发的是 `core/audit/actions.py::ACTIONS` 的投影。前端再列一份
 * 必然在某次新增动作后不同步 —— 而表现是「新动作记进了库、筛选框里却选不到」，
 * 排查时极难想到（后端有记录、前端说没有，两边都"自洽"）。
 */

import type { AxiosRequestConfig } from 'axios'
import { get } from '@/api/request'

/**
 * 本模块所有请求读的都是**身份与授权数据**（审计日志按平台角色授权）。
 *
 * ★ 抽成模块级常量而不是每处写字面量：`requiresIdentity` 的语义是
 *   "**整个模块**读的是身份数据"，属于模块属性，不是每个调用各自的决定。
 *   将来加端点时就不会再有人漏写 —— 而漏写的症状在 code review 里几乎看不出来。
 */
const IDENTITY: AxiosRequestConfig = { requiresIdentity: true }

/**
 * 面板自带**常驻**错误面（`AsyncEmpty` 失败态 / 403 无权态）⇒ 声明 `silentError`，
 * 免得同一个原因既上面板又弹一条 toast。
 * ★ 401 的**跳转**行为不受它影响：`requiresIdentity` 分支照常清状态 + 去登录页，
 *   被压掉的只是那句重复提示。
 */
const QUIET: AxiosRequestConfig = { ...IDENTITY, silentError: true }

// ====== 类型 ======

/** 写入时记录的结果。后端 `core/audit/actions.py` 的 `STATUSES`。 */
export type AuditStatus = 'success' | 'failure'

export interface AuditLogItem {
  id: string
  /** 执行者用户 id（审计表**无外键**，主体被删后此处仍保留） */
  actor_id: string | null
  /** 写入时点的执行者邮箱快照 —— 主体改名/删号后仍可读 */
  actor_email: string | null
  /** 动作码，如 `store.delete` */
  action: string
  status: AuditStatus | string
  target_type: string | null
  target_id: string | null
  /** 一行中文描述（写入时就地生成，不是渲染时拼的） */
  summary: string
  detail: Record<string, unknown> | null
  ip: string | null
  user_agent: string | null
  /** RFC3339 带偏移（后端 `utc_iso`）⇒ `dayjs()` 可直接解析并转本地时区 */
  created_at: string | null
}

/** `GET /actions` 的元素：动作目录条目 */
export interface AuditActionMeta {
  action: string
  label: string
  target_type: string | null
}

export interface AuditLogQuery {
  action?: string
  actor_id?: string
  target_type?: string
  target_id?: string
  status?: string
  /** ISO 8601；后端接受 `Date.toISOString()` 的 `Z` 结尾 */
  since?: string
  until?: string
  limit?: number
  offset?: number
}

export interface AuditLogPage {
  items: AuditLogItem[]
  total: number
  limit: number
  offset: number
}

export interface AuditActionPage {
  items: AuditActionMeta[]
  total: number
}

// ====== 端点 ======

/**
 * 分页查询审计日志（时间倒序）。
 *
 * ★ 传空串的字段**会被 `JSON.stringify` 之外的方式处理**：axios 会把它序列化成
 *   `action=`，后端 `if action:` 判空串为假 ⇒ 等同于不过滤。所以调用方可以
 *   放心地把"未选择"表达成空串，无需自己剔除字段。
 */
export function listAuditLogs(params: AuditLogQuery = {}) {
  return get<AuditLogPage>('/audit/logs', params, QUIET)
}

/** 动作目录（筛选下拉的唯一真源） */
export function listAuditActions() {
  return get<AuditActionPage>('/audit/actions', undefined, QUIET)
}

// ====== 展示元数据 ======

/**
 * 结果标签 —— **展示元数据**，不参与任何判定。
 *
 * ★ 与后端 `core/audit/actions.py` 的 `STATUSES` 一一对应。这里写死两份中文标签
 *   是**可以**的（它只是给人看的两行字，后端不提供该投影）；但若 `STATUSES`
 *   加了第三种，必须回来补 —— 因此 `statusLabel()` 对未知值是**原样回显**
 *   而不是兜底成"成功"：把未知洗成已知是审计场景里最不能接受的一种错。
 */
export const AUDIT_STATUS_META: { value: string; label: string; color: string }[] = [
  { value: 'success', label: '成功', color: 'green' },
  { value: 'failure', label: '失败', color: 'red' },
]

export function statusLabel(status?: string | null): string {
  if (!status) return '—'
  return AUDIT_STATUS_META.find((s) => s.value === status)?.label || status
}

export function statusColor(status?: string | null): string {
  return AUDIT_STATUS_META.find((s) => s.value === status)?.color || 'default'
}

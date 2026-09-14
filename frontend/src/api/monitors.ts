/**
 * 竞品监控池 API
 *
 * 监控池 ASIN 的 CRUD、分组管理、批量入池/出池、归属与分组流转。
 * 数据源：后端 PostgreSQL（/api/v1/monitors、/api/v1/monitor-groups）。
 *
 * 与时序数据的关系：30 天历史（价格/BSR/评论/变体/Listing 变更）在**入池那一刻**
 * 由后端生成一次并落库，此后固定不变。前端只读，不再本地随机生成。
 */

import { get, post, put, del } from './request'
import type { MonitorPoolRecord, MonitorGroup, PoolGroupKind } from '@/stores/monitorPool'

// ====== 监控池 CRUD ======

export async function fetchMonitors(): Promise<{ items: MonitorPoolRecord[]; total: number }> {
  return get('/monitors')
}

export async function fetchMonitor(id: string): Promise<MonitorPoolRecord> {
  return get(`/monitors/${id}`)
}

/** 入池（同店铺同 ASIN 已存在则后端合并，不新增行） */
export async function createMonitor(data: Partial<MonitorPoolRecord> & { asin: string }): Promise<MonitorPoolRecord> {
  return post('/monitors', data as any)
}

export async function updateMonitor(id: string, data: Partial<MonitorPoolRecord>): Promise<MonitorPoolRecord> {
  return put(`/monitors/${id}`, data as any)
}

export async function deleteMonitor(id: string): Promise<{ message: string; id: string }> {
  return del(`/monitors/${id}`)
}

/** 批量移出监控池（按 ASIN） */
export async function batchDeleteMonitors(asins: string[]): Promise<{ deleted: number; asins: string[] }> {
  return post('/monitors/batch-delete', { asins })
}

/** 批量入池（候选库 / 对标竞品批量开启监控），返回 added / existing 计数 */
export async function batchUpsertMonitors(items: (Partial<MonitorPoolRecord> & { asin: string })[]): Promise<{
  added: number
  existing: number
  items: MonitorPoolRecord[]
}> {
  return post('/monitors/batch-upsert', { items })
}

/** 批量把 ASIN 归入某分组（追加） */
export async function assignMonitorsToGroup(asins: string[], groupId: string): Promise<{ updated: number }> {
  return post('/monitors/assign-group', { asins, group_id: groupId })
}

/** 批量把 ASIN 移出某分组 */
export async function unassignMonitorsFromGroup(asins: string[], groupId: string): Promise<{ updated: number }> {
  return post('/monitors/unassign-group', { asins, group_id: groupId })
}

// ====== 分组 CRUD ======

export async function fetchMonitorGroups(): Promise<{ groups: MonitorGroup[] }> {
  return get('/monitor-groups')
}

export async function createMonitorGroup(data: { name: string; kind?: PoolGroupKind; color?: string }): Promise<MonitorGroup> {
  return post('/monitor-groups', data)
}

export async function updateMonitorGroup(id: string, data: { name?: string; kind?: PoolGroupKind; color?: string }): Promise<MonitorGroup> {
  return put(`/monitor-groups/${id}`, data)
}

/** 删除分组（组内 ASIN 不删，只从该分组摘掉） */
export async function deleteMonitorGroup(id: string): Promise<{ message: string; id: string; detached: number }> {
  return del(`/monitor-groups/${id}`)
}

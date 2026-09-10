/**
 * 候选选品库 API
 *
 * 候选选品（草稿池）的 CRUD、分组管理、评审状态流转、评审通过迁移到产品库。
 * 数据源：后端 PostgreSQL（/api/v1/candidates、/api/v1/candidate-groups）。
 */

import { get, post, put, del } from './request'
import request from './request'
import type { CandidateItem, CandidateGroup, ReviewStatus } from '@/stores/candidateLibrary'

// ====== 候选 CRUD ======

export async function fetchCandidates(): Promise<{ items: CandidateItem[]; total: number }> {
  return get('/candidates')
}

export async function fetchCandidate(id: string): Promise<CandidateItem> {
  return get(`/candidates/${id}`)
}

export async function createCandidate(data: Partial<CandidateItem>): Promise<CandidateItem> {
  return post('/candidates', data)
}

export async function updateCandidate(id: string, data: Partial<CandidateItem>): Promise<CandidateItem> {
  return put(`/candidates/${id}`, data)
}

/** 评审状态流转 */
export async function reviewCandidate(
  id: string,
  data: { review_status: ReviewStatus; review_notes?: string; reviewed_by?: string },
): Promise<CandidateItem> {
  return request.patch(`/candidates/${id}/review`, data)
}

/** 竞品监控员回填数据快照 */
export async function monitorCandidate(
  id: string,
  data: { monitor_data?: Record<string, any>; last_monitored_at?: string },
): Promise<CandidateItem> {
  return request.post(`/candidates/${id}/monitor`, data)
}

/** 评审通过：迁移到产品/Listing 库 */
export async function approveCandidate(id: string): Promise<{ message: string; candidate_id: string; product: any }> {
  return post(`/candidates/${id}/approve`, {})
}

export async function deleteCandidate(id: string): Promise<void> {
  return del(`/candidates/${id}`)
}

export async function batchDeleteCandidates(ids: string[]): Promise<void> {
  return post('/candidates/batch-delete', { ids })
}

// ====== 分组 CRUD ======

export async function fetchCandidateGroups(): Promise<{ groups: CandidateGroup[] }> {
  return get('/candidate-groups')
}

export async function createCandidateGroup(data: { name: string; color?: string }): Promise<CandidateGroup> {
  return post('/candidate-groups', data)
}

export async function updateCandidateGroup(id: string, data: { name?: string; color?: string }): Promise<CandidateGroup> {
  return put(`/candidate-groups/${id}`, data)
}

export async function deleteCandidateGroup(id: string): Promise<void> {
  return del(`/candidate-groups/${id}`)
}

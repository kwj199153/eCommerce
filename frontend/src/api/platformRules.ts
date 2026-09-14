/**
 * 平台规则库 API
 *
 * 规则 CRUD、批量导入、AI 拆分、来源文档素材管理。
 * 数据源：后端 PostgreSQL（/api/v1/platform-rules、/api/v1/platform-rule-docs），唯一权威源。
 *
 * 两个设计取舍（与后端一致，改动时别顺手"修正"）：
 *  1. 列表一次拉全「规则 + 文档」——两者同页渲染，分两次请求只多一次往返和两个 loading 态。
 *  2. 文档列表**不含正文**（content）——正文动辄数千字符，点开预览时再按 id 单独拉。
 */

import { get, post, put, del } from './request'
import type { PlatformRule, PlatformRuleDoc } from '@/stores/platformRules'

// ====== 规则 ======

/** 一次拉全：规则 + 文档素材（文档不含 content） */
export async function fetchPlatformRules(): Promise<{
  items: PlatformRule[]
  docs: PlatformRuleDoc[]
  total: number
}> {
  return get('/platform-rules')
}

export async function createPlatformRule(data: Partial<PlatformRule>): Promise<PlatformRule> {
  return post('/platform-rules', data as any)
}

export async function updatePlatformRule(id: string, data: Partial<PlatformRule>): Promise<PlatformRule> {
  return put(`/platform-rules/${id}`, data as any)
}

export async function deletePlatformRule(id: string): Promise<{ message: string; id: string }> {
  return del(`/platform-rules/${id}`)
}

/**
 * 批量导入（前端解析文件后提交）。
 * 后端逐条校验必填，跳过坏行并返回 `skipped` 计数，不整批 422。
 */
export async function batchCreatePlatformRules(items: Partial<PlatformRule>[]): Promise<{
  added: number
  items: PlatformRule[]
  skipped: number
}> {
  return post('/platform-rules/batch', { items })
}

/**
 * AI 从文档正文拆分规则。
 *
 * 返回的 `rules` **未标注查重**，由前端 store 补 `_dupStatus`（查重逻辑刻意留在前端：
 * 用户勾选时的 Layer 3 终检要复用同一份实现，搬到后端会造成两份实现分叉）。
 *
 * `degraded=true` 表示 LLM 不可用 / 文档无正文 / 提取为空，此时 `rules` 为空且
 * `reason` 是可直接展示给用户的中文原因 —— **后端绝不返回编造的规则**。
 */
export async function aiSplitPlatformRules(docId: string): Promise<{
  extracted: number
  rules: Omit<PlatformRule, 'id' | 'created_at' | 'updated_at'>[]
  degraded: boolean
  reason: string
}> {
  return post('/platform-rules/ai-split', { doc_id: docId })
}

// ====== 文档素材 ======

export async function createPlatformRuleDoc(data: Partial<PlatformRuleDoc>): Promise<PlatformRuleDoc> {
  return post('/platform-rule-docs', data as any)
}

/** 取单篇文档**含正文**（预览用；列表接口不返回 content） */
export async function fetchPlatformRuleDoc(id: string): Promise<PlatformRuleDoc> {
  return get(`/platform-rule-docs/${id}`)
}

/** 删除文档素材（不级联删除引用它的规则） */
export async function deletePlatformRuleDoc(id: string): Promise<{ message: string; id: string }> {
  return del(`/platform-rule-docs/${id}`)
}

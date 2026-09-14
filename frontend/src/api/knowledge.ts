/**
 * 业务话术库 API
 *
 * 知识库容器 / 话术条目 / 文档素材的 CRUD、批量导入与批量删除。
 * 数据源：后端 PostgreSQL（/api/v1/knowledge-base），唯一权威源。
 *
 * 两个设计取舍（与后端一致，改动时别顺手"统一"掉）：
 *  1. 列表一次拉全「容器 + 话术 + 文档」——三者同页渲染，且话术/文档由前端按 kb_id 分组。
 *  2. 文档列表**不含正文**（content）——整篇动辄数千字符，按需单独取。
 */

import { get, post, put, del } from './request'
import type { KnowledgeBase, FaqItem, KnowledgeDoc } from '@/stores/knowledge'

// ====== 一次性拉全 ======

/** 容器 + 话术 + 文档一次返回（容器自带实时统计的 faq_count / doc_count） */
export async function fetchKnowledgeBase(): Promise<{
  bases: KnowledgeBase[]
  faqs: FaqItem[]
  docs: KnowledgeDoc[]
  total: number
}> {
  return get('/knowledge-base')
}

// ====== 知识库容器 ======

export async function createKnowledgeBase(data: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
  return post('/knowledge-base', data as any)
}

export async function updateKnowledgeBase(id: string, data: Partial<KnowledgeBase>): Promise<KnowledgeBase> {
  return put(`/knowledge-base/${id}`, data as any)
}

/** 删除容器（后端级联删除其下话术与文档），返回被连带删除的条数 */
export async function deleteKnowledgeBase(id: string): Promise<{
  message: string
  id: string
  deleted_faqs: number
  deleted_docs: number
}> {
  return del(`/knowledge-base/${id}`)
}

// ====== 话术条目 ======

export async function createFaq(data: Partial<FaqItem>): Promise<FaqItem> {
  return post('/knowledge-base/faqs', data as any)
}

export async function updateFaq(id: string, data: Partial<FaqItem>): Promise<FaqItem> {
  return put(`/knowledge-base/faqs/${id}`, data as any)
}

export async function deleteFaq(id: string): Promise<{ message: string; id: string }> {
  return del(`/knowledge-base/faqs/${id}`)
}

/** 批量导入（前端解析文件后提交）。后端跳过坏行并返回 `skipped` 计数，不整批 422 */
export async function batchCreateFaqs(items: Partial<FaqItem>[]): Promise<{
  added: number
  items: FaqItem[]
  skipped: number
}> {
  return post('/knowledge-base/faqs/batch', { items })
}

/** 批量删除（列表勾选删除），返回实际删除条数 */
export async function batchDeleteFaqs(ids: string[]): Promise<{ deleted: number; ids: string[] }> {
  return post('/knowledge-base/faqs/batch-delete', { ids })
}

// ====== 文档素材 ======

export async function createKnowledgeDoc(data: Partial<KnowledgeDoc>): Promise<KnowledgeDoc> {
  return post('/knowledge-base/docs', data as any)
}

/** 取单篇文档**含正文**（列表接口不返回 content） */
export async function fetchKnowledgeDoc(id: string): Promise<KnowledgeDoc> {
  return get(`/knowledge-base/docs/${id}`)
}

export async function deleteKnowledgeDoc(id: string): Promise<{ message: string; id: string }> {
  return del(`/knowledge-base/docs/${id}`)
}

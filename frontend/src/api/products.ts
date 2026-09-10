/**
 * 产品库 API（SPU + SKU 分表）
 *
 * SPU（主产品）/ SKU（具体规格）的 CRUD、分组管理、Listing 写回。
 * 数据源：后端 PostgreSQL（/api/v1/spus、/api/v1/skus、/api/v1/product-groups）。
 */

import { get, post, put, del } from './request'
import request from './request'
import type { Spu, Sku, ProductGroup } from '@/stores/productLibrary'

// ====== SPU CRUD ======

export async function fetchSpus(): Promise<{ items: Spu[]; total: number }> {
  return get('/spus')
}

export async function fetchSpu(id: string): Promise<Spu> {
  return get(`/spus/${id}`)
}

export async function createSpu(data: Partial<Spu>): Promise<Spu> {
  return post('/spus', data)
}

export async function updateSpu(id: string, data: Partial<Spu>): Promise<Spu> {
  return put(`/spus/${id}`, data)
}

export async function deleteSpu(id: string): Promise<void> {
  return del(`/spus/${id}`)
}

// ====== SKU CRUD ======

export async function fetchSkus(spuId?: string): Promise<{ items: Sku[]; total: number }> {
  const q = spuId ? `?spu_id=${encodeURIComponent(spuId)}` : ''
  return get(`/skus${q}`)
}

export async function fetchSku(id: string): Promise<Sku> {
  return get(`/skus/${id}`)
}

export async function createSku(data: Partial<Sku>): Promise<Sku> {
  return post('/skus', data)
}

export async function updateSku(id: string, data: Partial<Sku>): Promise<Sku> {
  return put(`/skus/${id}`, data)
}

export async function deleteSku(id: string): Promise<void> {
  return del(`/skus/${id}`)
}

/** SKU Listing 优化工具写回 */
export async function updateSkuListing(
  id: string,
  data: {
    generated_title?: string
    generated_bullets?: Array<{ title: string; content: string }>
    generated_a_plus?: any
    seo_score?: number
    generated_at?: string
    version?: number
  },
): Promise<Sku> {
  return request.patch(`/skus/${id}/listing`, data)
}

// ====== 分组 CRUD ======

export async function fetchProductGroups(): Promise<{ groups: ProductGroup[] }> {
  return get('/product-groups')
}

export async function createProductGroup(data: { name: string; color?: string }): Promise<ProductGroup> {
  return post('/product-groups', data)
}

export async function updateProductGroup(id: string, data: { name?: string; color?: string }): Promise<ProductGroup> {
  return put(`/product-groups/${id}`, data)
}

export async function deleteProductGroup(id: string): Promise<void> {
  return del(`/product-groups/${id}`)
}

export async function moveProductGroup(id: string, direction: 'up' | 'down'): Promise<void> {
  return post(`/product-groups/${id}/move`, { direction })
}

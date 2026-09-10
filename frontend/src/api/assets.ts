/**
 * 素材库 API
 *
 * 营销素材（图片/视频）的 CRUD、分组管理。
 * 数据源：后端 PostgreSQL（/api/v1/assets、/api/v1/asset-groups）。
 */

import { get, post, put, del } from './request'

// ====== 类型（与 stores/assetLibrary.ts 的 AssetItem 对齐） ======

export type AssetKind = 'image' | 'video'

export interface AssetItem {
  id: string
  name: string
  kind: AssetKind
  category: string
  url: string
  videoUrl?: string
  thumbnail?: string
  productId?: string
  productName?: string
  asin?: string
  prompt?: string
  source: string
  width?: number
  height?: number
  tags: string[]
  groups: string[]
  notes: string
  createdAt: string
  updatedAt: string
}

export interface AssetGroup {
  id: string
  name: string
  color: string
  createdAt: string
  updatedAt: string
}

// ====== 素材 CRUD ======

export async function fetchAssets(): Promise<{ items: AssetItem[]; total: number }> {
  return get('/assets')
}

export async function fetchAsset(id: string): Promise<AssetItem> {
  return get(`/assets/${id}`)
}

export async function createAsset(data: Partial<AssetItem>): Promise<AssetItem> {
  return post('/assets', data)
}

export async function updateAsset(id: string, data: Partial<AssetItem>): Promise<AssetItem> {
  return put(`/assets/${id}`, data)
}

export async function deleteAsset(id: string): Promise<void> {
  return del(`/assets/${id}`)
}

export async function batchDeleteAssets(ids: string[]): Promise<void> {
  return post('/assets/batch-delete', { ids })
}

// ====== 分组 CRUD ======

export async function fetchAssetGroups(): Promise<{ groups: AssetGroup[] }> {
  return get('/asset-groups')
}

export async function createAssetGroup(data: { name: string; color?: string }): Promise<AssetGroup> {
  return post('/asset-groups', data)
}

export async function updateAssetGroup(id: string, data: { name?: string; color?: string }): Promise<AssetGroup> {
  return put(`/asset-groups/${id}`, data)
}

export async function deleteAssetGroup(id: string): Promise<void> {
  return del(`/asset-groups/${id}`)
}

export async function moveAssetGroup(id: string, direction: 'up' | 'down'): Promise<void> {
  return post(`/asset-groups/${id}/move`, { direction })
}

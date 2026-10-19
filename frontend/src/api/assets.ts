/**
 * 素材库 API
 *
 * 营销素材（图片/视频）的 CRUD、分组管理。
 * 数据源：后端 PostgreSQL（/api/v1/assets、/api/v1/asset-groups）。
 */

import { get, post, put, del } from './request'
import { assetUrl } from '@/config/runtimeApi'

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

// ====== 站内路径归一化 ======

/**
 * 把后端返回的站内路径补成壳里可用的绝对地址（浏览器里 `API_ORIGIN === ''` ⇒ 逐字不变）。
 *
 * ★ 为什么必须在这一层做：素材有**两种来源**
 *   ① 演示素材 `/mock/products/*.png` —— 本身就是 `dist/mock/` 里的文件，随包发布，
 *      壳里相对路径能命中 ⇒ 一直正常，掩盖了问题；
 *   ② AIGC 生成素材 `/static/aigc/*.png` —— 存在服务端 `backend/static/`，**不在包里**，
 *      壳的 origin 是 `tauri.localhost` ⇒ `/static/...` 打到自己身上 ⇒ 图裂
 *      （Web 端同源所以看不出来）。
 *
 * 判据：桌面/平板壳里「营销素材库」的 AIGC 图与演示图**都必须出图**；
 *       Web 端 `API_ORIGIN === ''` 时字节级行为不变。
 */
function withOrigin(a: AssetItem): AssetItem {
  return {
    ...a,
    url: assetUrl(a.url),
    thumbnail: assetUrl(a.thumbnail),
    videoUrl: assetUrl(a.videoUrl),
  }
}

// ====== 素材 CRUD ======

export async function fetchAssets(): Promise<{ items: AssetItem[]; total: number }> {
  const r = await get<{ items: AssetItem[]; total: number }>('/assets')
  return { ...r, items: (r.items || []).map(withOrigin) }
}

export async function fetchAsset(id: string): Promise<AssetItem> {
  return withOrigin(await get<AssetItem>(`/assets/${id}`))
}

export async function createAsset(data: Partial<AssetItem>): Promise<AssetItem> {
  return withOrigin(await post<AssetItem>('/assets', data))
}

export async function updateAsset(id: string, data: Partial<AssetItem>): Promise<AssetItem> {
  return withOrigin(await put<AssetItem>(`/assets/${id}`, data))
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

/**
 * 店铺状态管理
 *
 * 管理当前选中的店铺、店铺列表等。
 * 支持多租户场景下的店铺切换。
 *
 * Phase 10: 扩展支持 Shopee + 费率模板关联
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { get, post, put, del } from '@/api/request'
import type { Store } from '@/api/stores'

// ====== 类型定义 ======

export interface Shop {
  id: string
  name: string
  platform: 'amazon_us' | 'amazon_uk' | 'amazon_de' | 'amazon_jp'
           | 'shopee_my' | 'shopee_tw' | 'shopee_ph' | 'shopee_th'
           | 'shopee_sg' | 'shopee_vn' | 'shopee_id' | 'shopee_br'
           | 'temu' | 'temu_us' | 'temu_uk' | 'temu_de'
           | 'tiktok' | 'shopify'

  // Phase 10 新增字段
  currency: string                    // 默认货币: USD, MYR, TWD 等
  region_code: string                 // 地区代码: US, MY, TW
  fee_template_id: string | null      // 关联的费率模板 ID
  discount_template_id: string        // 折扣规则模板 ID

  is_active: boolean
  is_connected: boolean
  marketplace_id: string | null
  last_sync_at: string | null
  sync_status: string
  created_at: string | null
}

// ====== Store ======

export const useShopStore = defineStore('shop', () => {
  // ====== State ======
  const shops = ref<Shop[]>([])
  const currentShopId = ref<string | null>(
    localStorage.getItem('current_shop_id')
  )
  const isLoading = ref(false)

  // ====== Getters ======
  const currentShop = computed(() =>
    shops.value.find((s) => s.id === currentShopId.value) || null
  )

  /** 店铺列表别名（供组件使用） */
  const shopList = computed(() => shops.value)

  const activeShops = computed(() =>
    shops.value.filter((s) => s.is_active)
  )

  const connectedShops = computed(() =>
    shops.value.filter((s) => s.is_connected)
  )

  // ====== Actions ======

  /**
   * 加载店铺列表
   */
  async function fetchShops() {
    isLoading.value = true

    try {
      // 使用正确的 API 路径 /stores（不是 /shops）
      const response = await get<{ stores: Shop[]; total: number }>('/stores')
      shops.value = response.stores || []

      // 如果当前选中的店铺不在列表中，自动切换到第一个
      if (currentShopId.value && !currentShop.value) {
        if (shops.value.length > 0) {
          setCurrentShop(shops.value[0].id)
        }
      }

      // 数据层隔离：未选店铺时后端返回空，这里兜底自动选中第一个店铺，
      // 避免「一打开全空」影响演示体验
      if (!currentShopId.value && shops.value.length > 0) {
        setCurrentShop(shops.value[0].id)
      }
    } catch (error) {
      console.error('加载店铺列表失败:', error)
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 确保店铺列表已加载（幂等）。
   *
   * ★★ 为什么需要这个：`shops` 的唯一填充点曾是 `ShopPopoverContent.vue` 的
   *    `onMounted` —— 而该组件挂在左上角「店铺群」弹层的 `#content` slot 里，
   *    **只有用户点开弹层才会挂载**。后果：
   *      1. 刷新页面后不点弹层 → `shops` 恒为 `[]` → 左上角店铺名不显示
   *         （`currentShop = shops.find(...)` 算不出）
   *      2. AI 说「切换到虾皮2」时 `switch_shop` 找不到目标 → 动作被丢弃
   *    ⇒ 店铺列表属于**应用级基础数据**，必须在入口处主动拉，不能寄生在弹层里。
   *
   * 幂等：已加载过就不再重复请求（除非 `force`）。并发安全：用 `_loadPromise`
   * 去重，避免启动期 Workspace / 弹层 / 动作分发同时触发三个请求。
   */
  let _loadPromise: Promise<void> | null = null
  async function ensureShopsLoaded(force = false): Promise<void> {
    if (!force && shops.value.length > 0) return
    if (_loadPromise) return _loadPromise
    _loadPromise = (async () => {
      try {
        const response = await get<{ stores: Store[]; total: number }>('/stores')
        // 复用 setShopList（其参数就是后端 Store[]）：它内含「未选店铺则自动
        // 选中第一个」的兜底，且内部做 `Store[] → Shop[]` 的断言转换。
        // ⚠️ 别在这里自己 `as Shop[]` 再传 —— setShopList 的形参是 Store[]，
        //    传 Shop[] 会被 tsc 拒绝（Shop 缺 status / connection_status）。
        setShopList(response?.stores || [])
      } catch (error) {
        console.error('加载店铺列表失败:', error)
      } finally {
        _loadPromise = null
      }
    })()
    return _loadPromise
  }

  /**
   * 设置当前选中店铺（接受 Shop 对象或 ID 字符串）
   */
  function setCurrentShop(shopOrId: Shop | string) {
    const id = typeof shopOrId === 'string' ? shopOrId : shopOrId.id
    currentShopId.value = id
    localStorage.setItem('current_shop_id', id)
  }

  /**
   * 从外部设置店铺列表（API 响应后直接设置）
   *
   * 参数用后端 Store 类型（/stores 数据源）；Shop 是前端富类型，
   * 二者描述同一批店铺数据，字段差异为历史遗留（marketplace_id 等可空）。
   */
  function setShopList(newShops: Store[]) {
    shops.value = newShops as unknown as Shop[]
    // 数据层隔离：未选店铺时后端一律返回空列表。真实加载路径是
    // `ShopPopoverContent` / `ShopList` 调 `fetchStores()` → 本方法，
    // 而 `fetchShops()`（曾内置这段兜底）其实从未被调用 —— 兜底一度是死代码，
    // 导致新用户（localStorage 无 current_shop_id）进去「一打开全空」。
    if (!currentShopId.value && shops.value.length > 0) {
      setCurrentShop(shops.value[0])
    }
  }

  /**
   * 创建新店铺
   */
  async function createNewShop(data: {
    name: string
    platform: string
    currency?: string
    fee_template_id?: string
  }): Promise<Shop> {
    isLoading.value = true

    try {
      const response = await post<Shop>('/stores', data)
      const newShop = response

      // 添加到列表
      shops.value.push(newShop)

      // 自动选中新创建的店铺
      setCurrentShop(newShop.id)

      return newShop
    } finally {
      isLoading.value = false
    }
  }

  /**
   * 更新店铺信息
   */
  async function updateShop(
    shopId: string,
    data: { name?: string; status?: string }
  ): Promise<void> {
    try {
      const response = await put<Shop>(`/stores/${shopId}`, data)

      // 更新本地状态
      const index = shops.value.findIndex((s) => s.id === shopId)
      if (index !== -1) {
        shops.value[index] = response
      }
    } catch (error) {
      console.error('更新店铺失败:', error)
      throw error
    }
  }

  /**
   * 删除店铺
   */
  async function deleteShopById(shopId: string): Promise<void> {
    try {
      await del(`/stores/${shopId}`)

      // 从列表中移除
      shops.value = shops.value.filter((s) => s.id !== shopId)

      // 如果删除的是当前选中店铺，切换到第一个
      if (currentShopId.value === shopId) {
        if (shops.value.length > 0) {
          setCurrentShop(shops.value[0])
        } else {
          currentShopId.value = null
          localStorage.removeItem('current_shop_id')
        }
      }
    } catch (error) {
      console.error('删除店铺失败:', error)
      throw error
    }
  }

  /**
   * 连接平台 API
   */
  async function connectPlatform(
    shopId: string,
    credentials?: Record<string, any>
  ): Promise<void> {
    try {
      await post(`/stores/${shopId}/connect`, credentials)

      // 更新连接状态
      const shop = shops.value.find((s) => s.id === shopId)
      if (shop) {
        shop.is_connected = true
      }
    } catch (error) {
      console.error('连接平台失败:', error)
      throw error
    }
  }

  /**
   * 断开平台 API
   */
  async function disconnectPlatform(shopId: string): Promise<void> {
    try {
      await post(`/stores/${shopId}/disconnect`)

      // 更新连接状态
      const shop = shops.value.find((s) => s.id === shopId)
      if (shop) {
        shop.is_connected = false
      }
    } catch (error) {
      console.error('断开平台失败:', error)
      throw error
    }
  }

  return {
    // State
    shops,
    shopList,
    currentShopId,
    isLoading,

    // Getters
    currentShop,
    activeShops,
    connectedShops,

    // Actions
    fetchShops,
    ensureShopsLoaded,
    setCurrentShop,
    setShopList,
    createNewShop,
    updateShop,
    deleteShop: deleteShopById,
    connectPlatform,
    disconnectPlatform,
  }
})

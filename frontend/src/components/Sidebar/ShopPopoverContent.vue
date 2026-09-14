<template>
  <div class="shop-popover">
    <!-- 头部 -->
    <div class="popover-header">
      <span class="popover-title">🏪 店铺群</span>
      <span class="popover-count">{{ shopList.length }} 个店铺</span>
      <a-button type="link" size="small" @click="openAddModal">
        <PlusOutlined /> 添加
      </a-button>
    </div>

    <!-- 店铺列表 -->
    <div class="popover-body">
      <div
        v-for="shop in shopList"
        :key="shop.id"
        class="popover-shop-item"
        :class="{ active: currentShopId === shop.id }"
        @click="handleSelectShop(shop)"
      >
        <div class="item-left">
          <span class="shop-name">{{ shop.name }}</span>
          <a-tag :color="platformColor(shop.platform)" size="small">{{ platformLabel(shop.platform) }}</a-tag>
        </div>
        <div class="item-right">
          <span :class="['status-dot', shop.is_connected ? 'connected' : 'disconnected']"></span>
          <a-tooltip title="编辑">
            <button class="icon-btn" @click.stop="openEditModal(shop)">
              <EditOutlined />
            </button>
          </a-tooltip>
          <a-popconfirm title="确定删除？" ok-text="删除" cancel-text="取消" @confirm="handleDelete(shop)">
            <a-tooltip title="删除">
              <button class="icon-btn danger" @click.stop>
                <DeleteOutlined />
              </button>
            </a-tooltip>
          </a-popconfirm>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="shopList.length === 0" class="empty-state">
        <p>暂无店铺</p>
        <span>点击「添加」创建第一个店铺</span>
      </div>
    </div>

    <!-- 添加/编辑弹窗 -->
    <a-modal
      v-model:open="modalVisible"
      :title="isEditing ? '编辑店铺' : '添加店铺'"
      :confirm-loading="submitting"
      @ok="handleSubmit"
      width="480px"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form :model="formState" :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="formState.name" placeholder="如：Amazon US Store" :maxlength="50" show-count />
        </a-form-item>
        <a-form-item label="平台" required>
          <a-select v-model:value="formState.platform" placeholder="选择平台站点" :disabled="isEditing" @change="handlePlatformChange">
            <a-select-opt-group label="Amazon">
              <a-select-option value="amazon_us">🇺🇸 Amazon US</a-select-option>
              <a-select-option value="amazon_uk">🇬🇧 Amazon UK</a-select-option>
              <a-select-option value="amazon_de">🇩🇪 Amazon DE</a-select-option>
              <a-select-option value="amazon_jp">🇯🇵 Amazon JP</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Shopee">
              <a-select-option value="shopee_my">🇲🇾 Shopee MY</a-select-option>
              <a-select-option value="shopee_tw">🇹🇼 Shopee TW</a-select-option>
              <a-select-option value="shopee_ph">🇵🇭 Shopee PH</a-select-option>
              <a-select-option value="shopee_th">🇹🇭 Shopee TH</a-select-option>
              <a-select-option value="shopee_sg">🇸🇬 Shopee SG</a-select-option>
              <a-select-option value="shopee_vn">🇻🇳 Shopee VN</a-select-option>
              <a-select-option value="shopee_id">🇮🇩 Shopee ID</a-select-option>
              <a-select-option value="shopee_br">🇧🇷 Shopee BR</a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="其他">
              <a-select-option value="tiktok">TikTok Shop</a-select-option>
              <a-select-option value="shopify">Shopify</a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea v-model:value="formState.description" placeholder="可选" :rows="2" :maxlength="200" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { useShopStore } from '@/stores/shop'
import { createShop, fetchStores, updateShop as apiUpdateShop, deleteShop as apiDeleteShop } from '@/api/stores'
import type { Shop } from '@/stores/shop'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const shopStore = useShopStore()
const currentShopId = computed(() => shopStore.currentShop?.id || '')
const shopList = computed(() => shopStore.shopList)

// Modal
const modalVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const formState = reactive({ id: '', name: '', platform: '', currency: '', description: '' })

const PLATFORM_CURRENCY_MAP: Record<string, string> = {
  amazon_us: 'USD', amazon_uk: 'GBP', amazon_de: 'EUR', amazon_jp: 'JPY',
  shopee_my: 'MYR', shopee_tw: 'TWD', shopee_ph: 'PHP', shopee_th: 'THB',
  shopee_sg: 'SGD', shopee_vn: 'VND', shopee_id: 'IDR', shopee_br: 'BRL',
  tiktok: 'USD', shopify: 'USD',
}

const platformLabel = (p: string) => ({ amazon_us: 'US', amazon_uk: 'UK', amazon_de: 'DE', amazon_jp: 'JP', shopee_my: 'MY', shopee_tw: 'TW', shopee_ph: 'PH', shopee_th: 'TH', shopee_sg: 'SG', shopee_vn: 'VN', shopee_id: 'ID', shopee_br: 'BR', tiktok: 'TK', shopify: 'SF' }[p] || p)
const platformColor = (p: string) => p.startsWith('amazon') ? 'orange' : p.startsWith('shopee') ? 'green' : p === 'tiktok' ? 'blue' : 'purple'

const handleSelectShop = (shop: Shop) => { shopStore.setCurrentShop(shop) }

const openAddModal = () => { isEditing.value = false; resetForm(); modalVisible.value = true }
const openEditModal = (shop: Shop) => {
  isEditing.value = true
  formState.id = shop.id; formState.name = shop.name; formState.platform = shop.platform
  formState.currency = shop.currency || PLATFORM_CURRENCY_MAP[shop.platform] || ''
  formState.description = (shop as any).description || ''
  modalVisible.value = true
}
const resetForm = () => { formState.id = ''; formState.name = ''; formState.platform = ''; formState.currency = ''; formState.description = '' }
const handlePlatformChange = (v: string) => { formState.currency = PLATFORM_CURRENCY_MAP[v] || 'USD' }

const handleSubmit = async () => {
  if (!formState.name.trim()) return message.warning('请输入店铺名称')
  if (!formState.platform) return message.warning('请选择平台')
  submitting.value = true
  try {
    const payload = { name: formState.name.trim(), platform: formState.platform, currency: formState.currency, description: formState.description.trim() || undefined }
    if (isEditing.value && formState.id) {
      await apiUpdateShop(formState.id, payload)
      message.success('已更新')
    } else {
      const res = await createShop(payload)
      message.success(`"${(res as any).name}" 已创建`)
      const newShop = shopList.value.find(s => s.name === formState.name)
      if (newShop) shopStore.setCurrentShop(newShop)
    }
    await refreshShopList()
    modalVisible.value = false
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || '操作失败')
  } finally { submitting.value = false }
}

const handleDelete = async (shop: Shop) => {
  try {
    await apiDeleteShop(shop.id)
    message.success('已删除')
    await refreshShopList()
  } catch (e: any) { message.error(e?.response?.data?.detail || e?.message || '删除失败') }
}

/**
 * 刷新店铺列表。
 *
 * 用途：**增 / 删 / 改店铺后**让列表跟上（打开弹层时也顺手刷新一次）。
 *
 * 注：启动期的首次加载已由 `Workspace.vue` 的 `shopStore.ensureShopsLoaded()` 负责，
 *     这里不再是唯一填充点。此前的写法 `res.shops || res.stores` 是笔误 ——
 *     `fetchStores()` 只返回 `{ stores, total }`，没有 `shops` 字段（恒 undefined）。
 */
const refreshShopList = async () => {
  try {
    const res = await fetchStores()
    if (res?.stores) shopStore.setShopList(res.stores)
  } catch (e) { console.error('刷新店铺列表失败:', e) }
}

onMounted(async () => { await refreshShopList() })
</script>

<style scoped>
.shop-popover { display: flex; flex-direction: column; gap: 0; }

.popover-header {
  display: flex; align-items: center; gap: var(--space-8);
  padding-bottom: var(--space-10); border-bottom: 1px solid var(--border-base);
}
.popover-title { font-size: var(--font-size-14); font-weight: 600; color: var(--text-primary); }
.popover-count { font-size: var(--font-size-11); color: var(--text-tertiary); background: var(--bg-base); padding: var(--space-1) var(--space-6); border-radius: var(--radius-8); }
.popover-header :deep(.ant-btn-link) { padding: 0 var(--space-4); font-size: var(--font-size-12); margin-left: auto; }

.popover-body { max-height: 320px; overflow-y: auto; padding: var(--space-4) 0; }
.popover-shop-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-8) var(--space-10); border-radius: var(--radius-6); cursor: pointer;
  transition: all 0.15s; border: 1px solid transparent; margin-bottom: var(--space-2);
}
.popover-shop-item:hover { background: var(--bg-hover-light); }
.popover-shop-item.active { background: rgba(24, 144, 255, 0.12); border-color: var(--primary); }

.item-left { display: flex; align-items: center; gap: var(--space-6); min-width: 0; flex: 1; overflow: hidden; }
.shop-name { font-size: var(--font-size-13); font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.item-right { display: flex; align-items: center; gap: var(--space-4); flex-shrink: 0; }

.status-dot { width: 6px; height: 6px; border-radius: var(--radius-circle); flex-shrink: 0; }
.status-dot.connected { background: var(--success); }
.status-dot.disconnected { background: #d9d9d9; }

.icon-btn { width: 24px; height: 24px; border: none; background: transparent; cursor: pointer; color: var(--text-tertiary); border-radius: var(--radius-4); display: inline-flex; align-items: center; justify-content: center; font-size: var(--font-size-12); padding: 0; }
.icon-btn:hover { background: var(--bg-hover-light); color: var(--primary); }
.icon-btn.danger:hover { color: var(--danger); background: rgba(255, 77, 79, 0.1); }

.empty-state { display: flex; flex-direction: column; align-items: center; padding: 30px var(--space-16); color: var(--text-tertiary); gap: var(--space-6); }
.empty-state p { margin: 0; font-size: var(--font-size-13); }
.empty-state span { font-size: var(--font-size-12); color: var(--text-disabled); }
</style>

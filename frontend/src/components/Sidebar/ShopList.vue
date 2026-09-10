<template>
  <div class="shop-list">
    <div class="section-header">
      <span class="section-title">店铺群</span>
      <a-button type="link" size="small" @click="openAddModal">
        <PlusOutlined /> 添加
      </a-button>
    </div>

    <!-- 店铺列表 -->
    <div class="shop-list-container">
      <div
        v-for="shop in shopList"
        :key="shop.id"
        class="shop-item"
        :class="{ active: currentShopId === shop.id }"
        @click="handleSelectShop(shop)"
      >
        <!-- 左侧：店铺名 + 区域 + 状态 -->
        <div class="shop-main">
          <span class="shop-name">{{ shop.name }}</span>
          <a-tag
            :color="platformColor(shop.platform)"
            size="small"
            class="region-tag"
          >
            {{ platformLabel(shop.platform) }}
          </a-tag>
          <span :class="['status-dot', shop.is_connected ? 'connected' : 'disconnected']"></span>
          <span :class="['status-text', shop.is_connected ? 'connected' : '']">
            {{ shop.is_connected ? '已连接' : '未连接' }}
          </span>
        </div>

        <!-- 右侧：编辑 / 删除（常显） -->
        <div class="shop-actions">
          <a-tooltip title="编辑店铺">
            <a-button
              type="text"
              size="small"
              class="action-btn"
              @click.stop="openEditModal(shop)"
            >
              <EditOutlined />
            </a-button>
          </a-tooltip>
          <a-popconfirm
            title="确定删除此店铺？"
            ok-text="删除"
            cancel-text="取消"
            @confirm="handleDelete(shop)"
          >
            <a-tooltip title="删除店铺">
              <a-button
                type="text"
                size="small"
                danger
                class="action-btn"
                @click.stop
              >
                <DeleteOutlined />
              </a-button>
            </a-tooltip>
          </a-popconfirm>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="shopList.length === 0" class="empty-state">
        <p>暂无店铺</p>
        <span class="empty-hint">点击右上角「添加」按钮创建店铺</span>
      </div>
    </div>

    <!-- 添加/编辑店铺对话框 -->
    <a-modal
      v-model:open="modalVisible"
      :title="isEditing ? '编辑店铺' : '添加店铺'"
      :confirm-loading="submitting"
      @ok="handleSubmit"
      @cancel="handleCancel"
      width="520px"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form
        :model="formState"
        :label-col="{ span: 6 }"
        :wrapper-col="{ span: 16 }"
        layout="horizontal"
      >
        <!-- 店铺名称 -->
        <a-form-item label="店铺名称" required>
          <a-input
            v-model:value="formState.name"
            placeholder="如：Amazon US Store、Shopee Malaysia"
            :maxlength="50"
            show-count
          />
        </a-form-item>

        <!-- 平台选择（编辑时禁用） -->
        <a-form-item label="平台站点" required>
          <a-select
            v-model:value="formState.platform"
            placeholder="选择电商平台和站点"
            :disabled="isEditing"
            @change="handlePlatformChange"
          >
            <a-select-opt-group label="Amazon">
              <a-select-option value="amazon_us">
                <span class="opt-icon orange">A</span> Amazon US (美国)
              </a-select-option>
              <a-select-option value="amazon_uk">
                <span class="opt-icon orange">A</span> Amazon UK (英国)
              </a-select-option>
              <a-select-option value="amazon_de">
                <span class="opt-icon orange">A</span> Amazon DE (德国)
              </a-select-option>
              <a-select-option value="amazon_jp">
                <span class="opt-icon orange">A</span> Amazon JP (日本)
              </a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="Shopee">
              <a-select-option value="shopee_my">
                <span class="opt-icon green">S</span> Shopee MY (马来西亚)
              </a-select-option>
              <a-select-option value="shopee_tw">
                <span class="opt-icon green">S</span> Shopee TW (台湾)
              </a-select-option>
              <a-select-option value="shopee_ph">
                <span class="opt-icon green">S</span> Shopee PH (菲律宾)
              </a-select-option>
              <a-select-option value="shopee_th">
                <span class="opt-icon green">S</span> Shopee TH (泰国)
              </a-select-option>
              <a-select-option value="shopee_sg">
                <span class="opt-icon green">S</span> Shopee SG (新加坡)
              </a-select-option>
              <a-select-option value="shopee_vn">
                <span class="opt-icon green">S</span> Shopee VN (越南)
              </a-select-option>
              <a-select-option value="shopee_id">
                <span class="opt-icon green">S</span> Shopee ID (印尼)
              </a-select-option>
              <a-select-option value="shopee_br">
                <span class="opt-icon green">S</span> Shopee BR (巴西)
              </a-select-option>
            </a-select-opt-group>
            <a-select-opt-group label="其他">
              <a-select-option value="tiktok">
                <span class="opt-icon blue">T</span> TikTok Shop
              </a-select-option>
              <a-select-option value="shopify">
                <span class="opt-icon purple">S</span> Shopify
              </a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>

        <!-- 备注 -->
        <a-form-item label="备注">
          <a-textarea
            v-model:value="formState.description"
            placeholder="可选：店铺备注信息"
            :rows="2"
            :maxlength="200"
          />
        </a-form-item>
      </a-form>

      <!-- 费用预览（根据平台显示，只读展示） -->
      <div v-if="formState.platform" class="fee-preview">
        <a-divider style="margin: 12px 0;" />
        <div class="preview-title">
          <CheckCircleOutlined style="color: #52c41a;" />
          系统将自动使用 {{ platformLabel(formState.platform) }} 费率
          <a-tag size="small" style="margin-left: 8px;">{{ formState.currency }}</a-tag>
        </div>

        <!-- Amazon 费用项 -->
        <div v-if="isAmazonPlatform" class="fee-items">
          <div class="fee-row">
            <span class="fee-name">佣金 Referral Fee</span>
            <span class="fee-value">{{ currentFeeConfig?.referral_fee_pct || 15 }}%</span>
          </div>
          <div class="fee-row">
            <span class="fee-name">FBA 配送费</span>
            <span class="fee-value">${{ currentFeeConfig?.fba_fulfillment_fee || '3.22' }}</span>
          </div>
          <div class="fee-row">
            <span class="fee-name">月仓储费</span>
            <span class="fee-value">${{ currentFeeConfig?.storage_fee_monthly || '0.87' }}</span>
          </div>
          <div v-if="(currentFeeConfig?.vat_rate || 0) > 0" class="fee-row">
            <span class="fee-name">VAT 税率</span>
            <span class="fee-value warning">{{ currentFeeConfig?.vat_rate }}%</span>
          </div>
        </div>

        <!-- Shopee 费用项 -->
        <div v-else-if="isShopeePlatform" class="fee-items">
          <div class="fee-row">
            <span class="fee-name">佣金 Commission</span>
            <span class="fee-value">{{ currentFeeConfig?.commission_pct || 5.5 }}%</span>
          </div>
          <div class="fee-row">
            <span class="fee-name">交易费 Transaction Fee</span>
            <span class="fee-value">{{ currentFeeConfig?.transaction_fee || '4.74' }}</span>
          </div>
          <div class="fee-row highlight">
            <span class="fee-name">商业增长费 Growth Fee</span>
            <span class="fee-value warning">{{ currentFeeConfig?.growth_fee_pct || 6.41 }}%</span>
          </div>
          <div class="fee-row highlight">
            <span class="fee-name">基础设施费 Infrastructure</span>
            <span class="fee-value">{{ currentFeeConfig?.infrastructure_fee || '1.07' }}</span>
          </div>
          <div class="fee-row">
            <span class="fee-name">物流成本 SLS</span>
            <span class="fee-value">{{ currentFeeConfig?.logistics_cost || '12.50' }}</span>
          </div>
          <div class="fee-row">
            <span class="fee-name">提现手续费率</span>
            <span class="fee-value">{{ (currentFeeConfig?.withdrawal_fee_rate || 0.01) * 100 }}%</span>
          </div>
          <div v-if="(currentFeeConfig?.vat_rate || 0) > 0" class="fee-row">
            <span class="fee-name">VAT 税率</span>
            <span class="fee-value warning">{{ currentFeeConfig?.vat_rate }}%</span>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

import { useShopStore } from '@/stores/shop'
import { createShop, fetchStores, updateShop as apiUpdateShop, deleteShop as apiDeleteShop } from '@/api/stores'
import type { Shop } from '@/stores/shop'

const shopStore = useShopStore()

// 当前选中的店铺 ID
const currentShopId = computed(() => shopStore.currentShop?.id || '')

// 店铺列表
const shopList = computed(() => shopStore.shopList)

// Modal 状态
const modalVisible = ref(false)
const isEditing = ref(false)
const submitting = ref(false)

// 表单数据
const formState = reactive({
  id: '',
  name: '',
  platform: '' as string,
  currency: '',
  description: '',
})

// 平台 → 货币映射
const PLATFORM_CURRENCY_MAP: Record<string, string> = {
  amazon_us: 'USD', amazon_uk: 'GBP', amazon_de: 'EUR', amazon_jp: 'JPY',
  shopee_my: 'MYR', shopee_tw: 'TWD', shopee_ph: 'PHP',
  shopee_th: 'THB', shopee_sg: 'SGD', shopee_vn: 'VND',
  shopee_id: 'IDR', shopee_br: 'BRL',
  tiktok: 'USD', shopify: 'USD',
}

// 判断平台类型
const isAmazonPlatform = computed(() => formState.platform.startsWith('amazon'))
const isShopeePlatform = computed(() => formState.platform.startsWith('shopee'))

// 当前平台的默认费率配置（用于预览）
const currentFeeConfig = computed(() => {
  if (!formState.platform) return null

  if (isAmazonPlatform.value) {
    return {
      referral_fee_pct: 15,
      fba_fulfillment_fee: 3.22,
      storage_fee_monthly: 0.87,
      vat_rate: formState.platform === 'amazon_uk' ? 20 : 0,
    }
  }
  if (isShopeePlatform.value) {
    return {
      commission_pct: 5.5,
      transaction_fee: 4.74,
      growth_fee_pct: 6.41,
      infrastructure_fee: 1.07,
      logistics_cost: 12.5,
      withdrawal_fee_rate: 0.01,
      vat_rate: formState.platform === 'shopee_tw' ? 5 : 0,
    }
  }
  return null
})

// 平台标签映射
const platformLabel = (platform: string) => {
  const labels: Record<string, string> = {
    amazon_us: 'Amazon US', amazon_uk: 'Amazon UK',
    amazon_de: 'Amazon DE', amazon_jp: 'Amazon JP',
    shopee_my: 'Shopee MY', shopee_tw: 'Shopee TW',
    shopee_ph: 'Shopee PH', shopee_th: 'Shopee TH',
    shopee_sg: 'Shopee SG', shopee_vn: 'Shopee VN',
    shopee_id: 'Shopee ID', shopee_br: 'Shopee BR',
    tiktok: 'TikTok', shopify: 'Shopify',
  }
  return labels[platform] || platform
}

// 平台颜色映射
const platformColor = (platform: string): string => {
  if (platform.startsWith('amazon')) return 'orange'
  if (platform.startsWith('shopee')) return 'green'
  if (platform === 'tiktok') return 'blue'
  if (platform === 'shopify') return 'purple'
  return 'default'
}

// 选择店铺
const handleSelectShop = (shop: Shop) => {
  shopStore.setCurrentShop(shop)
}

// 打开添加店铺弹窗
const openAddModal = () => {
  isEditing.value = false
  resetForm()
  modalVisible.value = true
}

// 打开编辑店铺弹窗
const openEditModal = (shop: Shop) => {
  isEditing.value = true
  formState.id = shop.id
  formState.name = shop.name
  formState.platform = shop.platform
  formState.currency = shop.currency || PLATFORM_CURRENCY_MAP[shop.platform] || ''
  formState.description = (shop as any).description || ''
  modalVisible.value = true
}

// 重置表单
const resetForm = () => {
  formState.id = ''
  formState.name = ''
  formState.platform = ''
  formState.currency = ''
  formState.description = ''
}

// 平台切换时自动填充货币
const handlePlatformChange = (value: string) => {
  formState.currency = PLATFORM_CURRENCY_MAP[value] || 'USD'
}

// 提交表单（创建或更新）
const handleSubmit = async () => {
  // 验证必填字段
  if (!formState.name.trim()) {
    message.warning('请输入店铺名称')
    return
  }
  if (!formState.platform) {
    message.warning('请选择平台站点')
    return
  }

  submitting.value = true
  try {
    const payload = {
      name: formState.name.trim(),
      platform: formState.platform,
      currency: formState.currency,
      description: formState.description.trim() || undefined,
    }

    if (isEditing.value && formState.id) {
      // 编辑模式
      const res = await apiUpdateShop(formState.id, payload)
      message.success(`店铺 "${res.name}" 已更新`)
      await refreshShopList()
      modalVisible.value = false
    } else {
      // 创建模式
      const res = await createShop(payload)
      // 修复：axios 返回 res 就是数据本身，不是 res.data
      message.success(`店铺 "${(res as any).name || formState.name}" 创建成功`)
      await refreshShopList()

      // 自动选中新创建的店铺
      const newShop = shopList.value.find(s => s.name === formState.name)
      if (newShop) {
        shopStore.setCurrentShop(newShop)
      }

      modalVisible.value = false
    }
  } catch (error: any) {
    const msg = error?.response?.data?.detail || error?.message || '操作失败，请重试'
    message.error(msg)
  } finally {
    submitting.value = false
  }
}

// 删除店铺
const handleDelete = async (shop: Shop) => {
  try {
    await apiDeleteShop(shop.id)
    message.success(`店铺 "${shop.name}" 已删除`)
    await refreshShopList()
  } catch (error: any) {
    const msg = error?.response?.data?.detail || error?.message || '删除失败'
    message.error(msg)
  }
}

// 取消/关闭
const handleCancel = () => {
  modalVisible.value = false
  resetForm()
}

// 刷新店铺列表
const refreshShopList = async () => {
  try {
    const res = await fetchStores()
    // axios 返回格式：res.data = { stores: [...], total: N }
    if (res && (res as any).stores) {
      shopStore.setShopList((res as any).shops || (res as any).stores || [])
    }
  } catch (e) {
    console.error('刷新店铺列表失败:', e)
  }
}

// 组件挂载时加载店铺列表
onMounted(async () => {
  await refreshShopList()
})
</script>

<style scoped>
.shop-list {
  flex: 1;
  padding: 8px 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px 8px;
  flex-shrink: 0;
}

.section-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
}

/* 店铺列表容器 */
.shop-list-container {
  flex: 1;
  padding: 0 8px;
  overflow-y: auto;
}

/* 单个店铺项（单行紧凑） */
.shop-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  margin-bottom: 2px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.shop-item:hover {
  background: var(--bg-hover-light);
}

.shop-item.active {
  background: rgba(24, 144, 255, 0.12);
  border-color: var(--primary);
}

.shop-main {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.shop-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.region-tag {
  font-size: 10px;
  line-height: 16px;
  padding: 0 4px;
  flex-shrink: 0;
}

/* 连接状态圆点 + 文字 */
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.connected {
  background-color: #52c41a;
}
.status-dot.disconnected {
  background-color: #d9d9d9;
}

.status-text {
  font-size: 11px;
  flex-shrink: 0;
  color: var(--text-tertiary);
}
.status-text.connected {
  color: #52c41a;
}

/* 操作按钮（常显） */
.shop-actions {
  display: flex;
  gap: 0;
  flex-shrink: 0;
  opacity: 1;
}

.action-btn {
  padding: 2px 4px;
  font-size: 12px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--text-tertiary);
  gap: 12px;
}

.empty-state p {
  margin: 0;
  font-size: 13px;
}

.empty-state .empty-hint {
  font-size: 12px;
  color: var(--text-disabled);
}

/* 下拉选项图标 */
.opt-icon {
  display: inline-block;
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  color: #fff;
  margin-right: 6px;
}
.opt-icon.orange { background: #fa8c16; }
.opt-icon.green { background: #52c41a; }
.opt-icon.blue { background: #1890ff; }
.opt-icon.purple { background: #722ed1; }

/* 费用预览区域 */
.fee-preview {
  background: var(--bg-base);
  border-radius: 8px;
  padding: 0 16px 12px;
}

.preview-title {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.fee-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fee-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding: 2px 0;
}

.fee-row.highlight {
  background: rgba(250, 140, 22, 0.08);
  margin: 0 -8px;
  padding: 2px 8px;
  border-radius: 4px;
}

.fee-name {
  color: var(--text-secondary);
}

.fee-value {
  font-weight: 500;
  color: var(--text-primary);
}

.fee-value.warning {
  color: #fa8c16;
}
</style>

<template>
  <div class="pain-point-config">
    <!-- ====== 智能统一输入框 ====== -->
    <div class="form-group">
      <label>目标商品</label>
      <div class="smart-input-row">
        <div class="smart-input-wrapper" style="flex: 1">
          <a-input
            v-model:value="form.productInput"
            :placeholder="inputPlaceholder"
            size="small"
            allow-clear
            @pressEnter="handleInputConfirm"
            @change="onInputChange"
          >
            <template #prefix>
              <SearchOutlined style="color: #bfbfbf" />
            </template>
            <template v-if="detectedType" #suffix>
              <a-tag :color="platformTagColor" size="small" style="margin-right: 4px; font-size: 10px">
                {{ platformLabel }}
              </a-tag>
            </template>
          </a-input>
        </div>
        <ProductPickerButton
          :model-value="selectedProduct"
          @select="onProductSelect"
          :show-label="true"
        />
      </div>
      <!-- 输入提示 -->
      <div class="input-hints">
        <span
          v-for="hint in inputHints"
          :key="hint.type"
          class="hint-chip"
          :class="{ active: detectedType === hint.type }"
          @click="fillHint(hint)"
        >{{ hint.label }}</span>
      </div>
    </div>

    <!-- 已识别的商品信息展示 -->
    <div v-if="detectedProduct" class="product-card">
      <div class="product-card-header">
        <ShopOutlined />
        <span class="product-card-platform">{{ detectedProduct.platform }}</span>
        <a-button type="link" size="small" danger @click="clearProduct">清除</a-button>
      </div>
      <div class="product-card-body">
        <div class="product-card-title">{{ detectedProduct.displayId }}</div>
        <div v-if="detectedProduct.title" class="product-card-desc">{{ detectedProduct.title }}</div>
      </div>
    </div>

    <div class="form-group">
      <label>分析深度</label>
      <a-radio-group v-model:value="form.depth" size="small">
        <a-radio-button value="quick">快速分析</a-radio-button>
        <a-radio-button value="deep">深度分析</a-radio-button>
      </a-radio-group>
    </div>

    <div class="form-group">
      <label>评论范围</label>
      <a-slider
        v-model:value="form.reviewRange"
        :min="10"
        :max="500"
        :step="10"
        :tooltip-formatter="(v: number) => `最近 ${v} 条`"
      />
      <div class="range-labels">
        <span>10条</span>
        <span class="current">{{ form.reviewRange }} 条</span>
        <span>500条</span>
      </div>
    </div>

    <div class="form-group">
      <label>痛点分类筛选</label>
      <a-checkbox-group v-model:value="form.categories" style="width: 100%">
        <div class="checkbox-row">
          <a-checkbox value="quality">产品质量</a-checkbox>
          <a-checkbox value="function">功能体验</a-checkbox>
        </div>
        <div class="checkbox-row">
          <a-checkbox value="logistics">物流包装</a-checkbox>
          <a-checkbox value="service">售后服务</a-checkbox>
        </div>
      </a-checkbox-group>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <a-button @click="handleReset" block>
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block :loading="loading">
        <SearchOutlined /> 开始分析
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ReloadOutlined, SearchOutlined, ShopOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

// ====== 输入类型检测 ======
type InputType = 'url' | 'asin' | 'keyword' | ''
type PlatformType = 'amazon' | 'shopee' | 'tiktok' | 'shopify' | 'other' | ''

interface DetectedProduct {
  raw: string
  type: InputType
  platform: PlatformType
  displayId: string       // 展示用的 ID（ASIN / Item ID / 关键词）
  extractedId?: string    // 提取的纯 ID
  url?: string            // 原始 URL
  title?: string          // 从 Mock 匹配到的标题
}

const form = reactive({
  productInput: '' as string,
  depth: 'quick' as 'quick' | 'deep',
  reviewRange: 100,
  categories: ['quality', 'function'] as string[],
})

const detectedType = ref<InputType>('')
const detectedPlatform = ref<PlatformType>('')
const detectedProduct = ref<DetectedProduct | null>(null)

// 输入提示快捷标签
const inputHints: { type: InputType; label: string; example: string }[] = [
  { type: 'url', label: '商品链接', example: 'https://www.amazon.com/dp/B0XXXXX' },
  { type: 'asin', label: 'ASIN/ID', example: 'B0CG7KQZ1N' },
  { type: 'keyword', label: '关键词', example: 'LED 植物生长灯' },
]

const inputPlaceholder = computed(() => {
  switch (detectedType.value) {
    case 'url': return '粘贴商品链接...'
    case 'asin': return '输入 ASIN 或商品 ID...'
    case 'keyword': return '输入搜索关键词...'
    default: return '输入商品链接、ASIN、或关键词...'
  }
})

const platformLabel = computed(() => {
  const map: Record<PlatformType, string> = {
    amazon: 'Amazon',
    shopee: 'Shopee',
    tiktok: 'TikTok Shop',
    shopify: 'Shopify',
    other: '其他平台',
    '': '',
  }
  return map[detectedPlatform.value] || ''
})

const platformTagColor = computed(() => {
  const map: Record<PlatformType, string> = {
    amazon: '#FF9900',
    shopee: '#EE4D2D',
    tiktok: 'black',
    shopify: 'green',
    other: '#999',
    '': '#d9d9d9',
  }
  return map[detectedPlatform.value] || '#d9d9d9'
})

/**
 * 核心检测逻辑：自动识别输入类型和平台
 */
function detectInput(input: string): { type: InputType; platform: PlatformType; displayId: string; extractedId?: string } {
  const trimmed = input.trim()
  if (!trimmed) return { type: '', platform: '', displayId: '' }

  // 1. URL 检测
  if (/^https?:\/\//i.test(trimmed)) {
    const lowerUrl = trimmed.toLowerCase()

    // Amazon URL → 提取 ASIN
    const amazonAsinMatch = trimmed.match(/(?:\/dp\/|\/product\/|\/ASIN\/|asins=)([A-Z0-9]{10})/i)
    if (lowerUrl.includes('amazon') && amazonAsinMatch) {
      return { type: 'url', platform: 'amazon', displayId: amazonAsinMatch[1], extractedId: amazonAsinMatch[1] }
    }
    if (lowerUrl.includes('amazon')) {
      return { type: 'url', platform: 'amazon', displayId: 'Amazon 商品页' }
    }

    // Shopee URL → 提取 Item ID
    const shopeeIdMatch = trimmed.match(/[-i](\d{8,})/i)
    if (lowerUrl.includes('shopee') && shopeeIdMatch) {
      return { type: 'url', platform: 'shopee', displayId: `Item ${shopeeIdMatch[1]}`, extractedId: shopeeIdMatch[1] }
    }
    if (lowerUrl.includes('shopee')) {
      return { type: 'url', platform: 'shopee', displayId: 'Shopee 商品' }
    }

    // TikTok Shop URL
    if (lowerUrl.includes('tiktok')) {
      return { type: 'url', platform: 'tiktok', displayId: 'TikTok Shop 商品' }
    }

    // Shopify URL（*.myshopify.com）
    if (/\.myshopify\.com/.test(lowerUrl) || lowerUrl.includes('shopify')) {
      return { type: 'url', platform: 'shopify', displayId: 'Shopify 商品' }
    }

    // 其他 URL
    return { type: 'url', platform: 'other', displayId: '商品链接' }
  }

  // 2. ASIN 格式检测（B0 + 9位字母数字）
  const asinMatch = trimmed.match(/^(B[0-9]{2}[A-Z0-9]{7}|B0[A-Z0-9]{8})$/i)
  if (asinMatch) {
    return { type: 'asin', platform: 'amazon', displayId: trimmed.toUpperCase(), extractedId: trimmed.toUpperCase() }
  }

  // 3. Shopee Item ID（纯数字，8位以上）
  if (/^\d{8,}$/.test(trimmed)) {
    return { type: 'asin', platform: 'shopee', displayId: `Item ${trimmed}`, extractedId: trimmed }
  }

  // 4. 默认为关键词
  return { type: 'keyword', platform: '', displayId: trimmed }
}

function onInputChange(e: any) {
  const val = e?.target?.value ?? e
  if (!val || !val.trim()) {
    detectedType.value = ''
    detectedPlatform.value = ''
    detectedProduct.value = null
    return
  }

  const result = detectInput(val)
  detectedType.value = result.type
  detectedPlatform.value = result.platform
  detectedProduct.value = {
    raw: val,
    type: result.type,
    platform: result.platform,
    displayId: result.displayId,
    extractedId: result.extractedId,
    url: result.type === 'url' ? val : undefined,
  }
}

function handleInputConfirm() {
  // 回车确认，保持当前检测结果
}

function fillHint(hint: { type: InputType; label: string; example: string }) {
  form.productInput = hint.example
  onInputChange(hint.example)
}

function clearProduct() {
  form.productInput = ''
  detectedType.value = ''
  detectedPlatform.value = ''
  detectedProduct.value = null
}

// ====== 持久化 ======
onMounted(() => {
  try {
    const saved = localStorage.getItem('pain_point_config')
    if (saved) {
      const parsed = JSON.parse(saved)
      Object.assign(form, parsed)
      // 恢复时重新检测
      if (form.productInput) {
        onInputChange(form.productInput)
      }
    }
  } catch (e) {}
})

const handleSubmit = () => {
  if (!form.productInput?.trim()) {
    message.warning('请输入目标商品（链接/ASIN/关键词）')
    return
  }
  loading.value = true

  const params = {
    ...form,
    // 附上结构化的检测结果
    _detection: detectedProduct.value ? {
      type: detectedProduct.value.type,
      platform: detectedProduct.value.platform,
      id: detectedProduct.value.extractedId || detectedProduct.value.displayId,
      url: detectedProduct.value.url,
    } : undefined,
  }

  // 只保存表单字段，不保存内部状态
  const toSave = { ...form }
  delete (toSave as any)._detection
  localStorage.setItem('pain_point_config', JSON.stringify(toSave))

  emit('startAnalysis', params)
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  form.productInput = ''
  form.depth = 'quick'
  form.reviewRange = 100
  form.categories = ['quality', 'function']
  detectedType.value = ''
  detectedPlatform.value = ''
  detectedProduct.value = null
  selectedProduct.value = null
  localStorage.removeItem('pain_point_config')
  message.success('已重置')
}

// ====== 产品库选择 ======
const selectedProduct = ref<any>(null)

const onProductSelect = (product: any) => {
  selectedProduct.value = product
  // 用商品 ASIN 填充智能输入框（触发自动检测）
  form.productInput = product.asin || product.title
  onInputChange(form.productInput)
}
</script>

<style scoped>
.pain-point-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 4px;
  font-weight: 500;
}

/* 智能输入框 */
.smart-input-wrapper {
  position: relative;
}

/* 输入提示快捷标签 */
.input-hints {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.hint-chip {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  background: #f5f5f5;
  color: #8c8c8c;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.hint-chip:hover {
  background: #e6f7ff;
  color: #1890ff;
  border-color: #91d5ff;
}

.hint-chip.active {
  background: #e6f7ff;
  color: #1890ff;
  border-color: #1890ff;
}

/* 已识别商品卡片 */
.product-card {
  background: linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%);
  border: 1px solid #bae7ff;
  border-radius: 8px;
  overflow: hidden;
}

.product-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: rgba(24, 144, 255, 0.06);
  font-size: 11px;
  color: #595959;
}

.product-card-platform {
  font-weight: 600;
  color: #1890ff;
  flex: 1;
}

.product-card-body {
  padding: 8px 10px;
}

.product-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
  font-family: 'SF Mono', Monaco, monospace;
}

.product-card-desc {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #8c8c8c;
}

.range-labels .current {
  color: #1890ff;
  font-weight: 600;
}

.checkbox-row {
  display: flex;
  gap: 16px;
  margin-bottom: 4px;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

/* 智能输入 + 产品库按钮 */
.smart-input-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>

<template>
  <div class="profit-config">
    <!-- ====== 智能统一输入框 ====== -->
    <div class="form-group">
      <label>目标商品（可选）</label>
      <div class="smart-input-wrapper">
        <a-input
          v-model:value="form.productInput"
          :placeholder="inputPlaceholder"
          size="small"
          allow-clear
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
        <ProductPickerButton
          class="smart-input-picker"
          :model-value="selectedProduct"
          :show-label="true"
          @select="onProductSelect"
        />
      </div>
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

    <!-- 已识别商品信息 -->
    <div v-if="detectedProduct" class="product-card-mini">
      <ShopOutlined />
      <span class="mini-platform">{{ detectedProduct.platform || '商品' }}</span>
      <span class="mini-id">{{ detectedProduct.displayId }}</span>
      <CloseOutlined class="mini-clear" @click="clearProduct" />
    </div>

    <!-- ====== 基础成本（常显）====== -->
    <div class="section-title">基础成本</div>

    <div class="form-row">
      <div class="form-group flex-1">
        <label>采购成本 ($)</label>
        <a-input-number
          v-model:value="form.costPrice"
          placeholder="0.00"
          :min="0"
          :precision="2"
          size="small"
          style="width: 100%"
        />
      </div>
      <div class="form-group flex-1">
        <label>头程运费 ($)</label>
        <a-input-number
          v-model:value="form.shippingCost"
          placeholder="0.00"
          :min="0"
          :precision="2"
          size="small"
          style="width: 100%"
        />
      </div>
    </div>

    <div class="form-row">
      <div class="form-group flex-1">
        <label>目标售价 ($)</label>
        <a-input-number
          v-model:value="form.sellingPrice"
          placeholder="输入售价"
          :min="0"
          :precision="2"
          size="small"
          style="width: 100%"
        />
      </div>
      <div class="form-group flex-1">
        <label>包装成本 ($)</label>
        <a-input-number
          v-model:value="form.packagingCost"
          placeholder="0.00"
          :min="0"
          :precision="2"
          size="small"
          style="width: 100%"
        />
      </div>
    </div>

    <!-- ====== 高级参数（可折叠）====== -->
    <a-collapse
      v-model:activeKey="advancedActiveKey"
      ghost
      size="small"
      style="margin-top: 4px"
    >
      <a-collapse-panel key="platform" header="平台费用">
        <div class="form-row">
          <div class="form-group flex-1">
            <label>平台佣金 (%)</label>
            <a-input-number
              v-model:value="form.referralFeePct"
              placeholder="15"
              :min="0"
              :max="45"
              :step="0.5"
              :precision="1"
              size="small"
              style="width: 100%"
              addon-after="%"
            />
          </div>
          <div class="form-group flex-1">
            <label>FBA 配送费 ($)</label>
            <a-input-number
              v-model:value="form.fbaFee"
              placeholder="3.22"
              :min="0"
              :precision="2"
              size="small"
              style="width: 100%"
            />
          </div>
        </div>
        <div class="form-row">
          <div class="form-group flex-1">
            <label>月仓储费 ($)</label>
            <a-input-number
              v-model:value="form.storageFee"
              placeholder="0.87"
              :min="0"
              :precision="2"
              size="small"
              style="width: 100%"
            />
          </div>
          <div class="form-group flex-1">
            <label>提现手续费 (%)</label>
            <a-input-number
              v-model:value="form.withdrawalFeePct"
              placeholder="1"
              :min="0"
              :max="5"
              :step="0.1"
              :precision="1"
              size="small"
              style="width: 100%"
              addon-after="%"
            />
          </div>
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="marketing" header="营销 & 税费">
        <div class="form-row">
          <div class="form-group flex-1">
            <label>PPC 广告费 ($)</label>
            <a-input-number
              v-model:value="form.adCost"
              placeholder="0 = 不投广告"
              :min="0"
              :precision="2"
              size="small"
              style="width: 100%"
            />
          </div>
          <div class="form-group flex-1">
            <label>VAT 税率 (%)</label>
            <a-input-number
              v-model:value="form.vatRate"
              placeholder="欧洲站必填"
              :min="0"
              :max="25"
              :step="1"
              :precision="0"
              size="small"
              style="width: 100%"
              addon-after="%"
            />
          </div>
        </div>
        <div class="form-group">
          <label>促销/优惠券折扣 (%)</label>
          <a-slider
            v-model:value="form.discountPct"
            :min="0"
            :max="50"
            :marks="{ 0: '无', 10: '10%', 20: '20%', 30: '30%' }"
            :tooltip-formatter="(v: number) => `${v}%`"
          />
        </div>
      </a-collapse-panel>

      <a-collapse-panel key="other" header="其他成本">
        <div class="form-row">
          <div class="form-group flex-1">
            <label>退货损耗率 (%)</label>
            <a-input-number
              v-model:value="form.returnRatePct"
              placeholder="服装类 5-15%"
              :min="0"
              :max="50"
              :step="1"
              :precision="0"
              size="small"
              style="width: 100%"
              addon-after="%"
            />
          </div>
          <div class="form-group flex-1">
            <label>汇率损失 (%)</label>
            <a-input-number
              v-model:value="form.exchangeLossPct"
              placeholder="通常 1-2%"
              :min="0"
              :max="10"
              :step="0.5"
              :precision="1"
              size="small"
              style="width: 100%"
              addon-after="%"
            />
          </div>
        </div>
        <a-alert
          type="info"
          show-icon
          message="退货损耗会按比例摊入单件成本，影响最终利润计算"
          style="margin-top: 8px; font-size: 11px"
        />
      </a-collapse-panel>
    </a-collapse>

    <!-- ====== 计算模式 ====== -->
    <a-divider style="margin: 12px 0 8px" />

    <div class="section-title">计算模式</div>
    <div class="mode-switch">
      <a-radio-group v-model:value="form.mode" size="small" button-style="solid">
        <a-radio-button value="forward">正向计算</a-radio-button>
        <a-radio-button value="reverse">逆向定价</a-radio-button>
      </a-radio-group>
    </div>

    <div v-if="form.mode === 'reverse'" class="form-group">
      <label>目标毛利 ($)</label>
      <a-input-number
        v-model:value="form.targetProfit"
        placeholder="期望利润"
        :min="0"
        :precision="2"
        size="small"
        style="width: 100%"
      />
    </div>

    <!-- ====== 快速预览（有足够数据时自动显示）====== -->
    <div v-if="quickPreview" class="quick-preview">
      <a-divider style="margin: 8px 0" />
      <!-- 正向模式：显示利润 -->
      <template v-if="form.mode === 'forward'">
        <div class="preview-row">
          <span class="preview-label">预估毛利</span>
          <span class="preview-value" :class="{ positive: quickPreview.grossProfit > 0, negative: quickPreview.grossProfit <= 0 }">
            {{ quickPreview.grossProfit > 0 ? '+' : '' }}${{ quickPreview.grossProfit.toFixed(2) }}
          </span>
        </div>
        <div class="preview-row">
          <span class="preview-label">毛利率</span>
          <span class="preview-value">{{ quickPreview.marginPct.toFixed(1) }}%</span>
        </div>
        <div class="preview-row">
          <span class="preview-label">总费用占比</span>
          <span class="preview-value warning">{{ quickPreview.feePct.toFixed(1) }}%</span>
        </div>
      </template>
      <!-- 逆向模式：显示建议售价 -->
      <template v-else>
        <div class="preview-row">
          <span class="preview-label">建议售价</span>
          <span class="preview-value suggested">
            ${{ (quickPreview.suggestedPrice ?? 0).toFixed(2) }}
          </span>
        </div>
        <div class="preview-row">
          <span class="preview-label">对应毛利率</span>
          <span class="preview-value">{{ quickPreview.marginPct.toFixed(1) }}%</span>
        </div>
        <div class="preview-hint">
          💡 要实现 ${{ (form.targetProfit || 0).toFixed(2) }} 目标毛利，需定价不低于 ${{ (quickPreview.suggestedPrice ?? 0).toFixed(2) }}
        </div>
      </template>
    </div>

    <!-- ====== 操作按钮 ====== -->
    <div class="action-bar">
      <a-button @click="handleReset" block size="small">
        <ReloadOutlined /> 重置
      </a-button>
      <a-button type="primary" @click="handleSubmit" block size="small" :loading="loading">
        <CalculatorOutlined /> {{ form.mode === 'forward' ? '计算利润' : '计算售价' }}
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { ReloadOutlined, CalculatorOutlined, SearchOutlined, ShopOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)
const advancedActiveKey = ref<string[]>([])

// ====== 输入类型检测 ======
type InputType = 'url' | 'asin' | 'keyword' | ''
type PlatformType = 'amazon' | 'shopee' | 'tiktok' | 'shopify' | 'other' | ''

interface DetectedProduct {
  raw: string
  type: InputType
  platform: PlatformType
  displayId: string
  extractedId?: string
  url?: string
}

// ====== 完整表单字段 ======
const defaultForm = () => ({
  // 智能输入（替代原 asin）
  productInput: '' as string,
  // 基础
  costPrice: null as number | null,
  shippingCost: null as number | null,
  sellingPrice: null as number | null,
  packagingCost: null as number | null,

  // 平台费用
  referralFeePct: 15,
  fbaFee: 3.22,
  storageFee: 0.87,
  withdrawalFeePct: 1,

  // 营销 & 税费
  adCost: 0,
  vatRate: 0,
  discountPct: 0,

  // 其他成本
  returnRatePct: 0,
  exchangeLossPct: 1.5,

  // 计算模式
  mode: 'forward' as 'forward' | 'reverse',
  targetProfit: null as number | null,
})

const form = reactive(defaultForm())

// ====== 智能输入检测 ======
const detectedType = ref<InputType>('')
const detectedPlatform = ref<PlatformType>('')
const detectedProduct = ref<DetectedProduct | null>(null)

const inputHints = [
  { type: 'url' as InputType, label: '商品链接', example: 'https://www.amazon.com/dp/B0XXXXX' },
  { type: 'asin' as InputType, label: 'ASIN/ID', example: 'B0CG7KQZ1N' },
  { type: 'keyword' as InputType, label: '关键词', example: 'LED 植物生长灯' },
]

const inputPlaceholder = computed(() => {
  switch (detectedType.value) {
    case 'url': return '粘贴商品链接...'
    case 'asin': return '输入 ASIN 或商品 ID...'
    case 'keyword': return '输入搜索关键词...'
    default: return '输入商品链接、ASIN、或关键词（可选）'
  }
})

const platformLabel = computed(() => {
  const map: Record<PlatformType, string> = { amazon: 'Amazon', shopee: 'Shopee', tiktok: 'TikTok Shop', shopify: 'Shopify', other: '其他平台', '': '' }
  return map[detectedPlatform.value] || ''
})

const platformTagColor = computed(() => {
  const map: Record<PlatformType, string> = { amazon: '#FF9900', shopee: '#EE4D2D', tiktok: 'black', shopify: 'green', other: '#999', '': '#d9d9d9' }
  return map[detectedPlatform.value] || '#d9d9d9'
})

function detectInput(input: string): { type: InputType; platform: PlatformType; displayId: string; extractedId?: string } {
  const trimmed = input.trim()
  if (!trimmed) return { type: '', platform: '', displayId: '' }

  if (/^https?:\/\//i.test(trimmed)) {
    const lowerUrl = trimmed.toLowerCase()
    const amazonAsinMatch = trimmed.match(/(?:\/dp\/|\/product\/|\/ASIN\/|asins=)([A-Z0-9]{10})/i)
    if (lowerUrl.includes('amazon') && amazonAsinMatch) return { type: 'url', platform: 'amazon', displayId: amazonAsinMatch[1], extractedId: amazonAsinMatch[1] }
    if (lowerUrl.includes('amazon')) return { type: 'url', platform: 'amazon', displayId: 'Amazon 商品页' }

    const shopeeIdMatch = trimmed.match(/[-i](\d{8,})/i)
    if (lowerUrl.includes('shopee') && shopeeIdMatch) return { type: 'url', platform: 'shopee', displayId: `Item ${shopeeIdMatch[1]}`, extractedId: shopeeIdMatch[1] }
    if (lowerUrl.includes('shopee')) return { type: 'url', platform: 'shopee', displayId: 'Shopee 商品' }
    if (lowerUrl.includes('tiktok')) return { type: 'url', platform: 'tiktok', displayId: 'TikTok Shop 商品' }
    if (/\.myshopify\.com/.test(lowerUrl) || lowerUrl.includes('shopify')) return { type: 'url', platform: 'shopify', displayId: 'Shopify 商品' }
    return { type: 'url', platform: 'other', displayId: '商品链接' }
  }

  const asinMatch = trimmed.match(/^(B[0-9]{2}[A-Z0-9]{7}|B0[A-Z0-9]{8})$/i)
  if (asinMatch) return { type: 'asin', platform: 'amazon', displayId: trimmed.toUpperCase(), extractedId: trimmed.toUpperCase() }
  if (/^\d{8,}$/.test(trimmed)) return { type: 'asin', platform: 'shopee', displayId: `Item ${trimmed}`, extractedId: trimmed }
  return { type: 'keyword', platform: '', displayId: trimmed }
}

function onInputChange(e: any) {
  const val = e?.target?.value ?? e
  if (!val || !val.trim()) {
    detectedType.value = ''; detectedPlatform.value = ''; detectedProduct.value = null; return
  }
  const result = detectInput(val)
  detectedType.value = result.type
  detectedPlatform.value = result.platform
  detectedProduct.value = { raw: val, type: result.type, platform: result.platform, displayId: result.displayId, extractedId: result.extractedId, url: result.type === 'url' ? val : undefined }
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

// ====== 从产品库选择 ======
const selectedProduct = ref<any>(null)

const onProductSelect = (product: any) => {
  selectedProduct.value = product
  // 用商品 ASIN 填充智能输入框（触发自动检测）
  form.productInput = product.asin || product.title
  onInputChange(form.productInput)
}

// ====== 快速预览计算 ======
interface QuickPreview {
  grossProfit: number
  marginPct: number
  feePct: number
  suggestedPrice?: number  // 逆向定价：建议售价
}

const quickPreview = computed<QuickPreview | null>(() => {
  const { costPrice, sellingPrice, shippingCost, packagingCost,
          referralFeePct, fbaFee, storageFee, withdrawalFeePct,
          adCost, vatRate, discountPct, returnRatePct, exchangeLossPct,
          mode, targetProfit } = form

  // 正向模式：需要售价
  if (mode === 'forward') {
    if (!costPrice || !sellingPrice) return null

    const actualPrice = sellingPrice * (1 - (discountPct || 0) / 100)
    const referralFee = actualPrice * (referralFeePct || 0) / 100
    const vatAmount = actualPrice * (vatRate || 0) / 100
    const withdrawalFee = actualPrice * (withdrawalFeePct || 0) / 100
    const exchangeLoss = actualPrice * (exchangeLossPct || 0) / 100

    const totalFixedCost =
      (costPrice || 0) + (shippingCost || 0) + (packagingCost || 0) +
      (fbaFee || 0) + (storageFee || 0) + (adCost || 0)

    const returnLoss = totalFixedCost * ((returnRatePct || 0) / 100) / (1 - (returnRatePct || 0) / 100)
    const totalCost = totalFixedCost + returnLoss + referralFee + vatAmount + withdrawalFee + exchangeLoss
    const grossProfit = actualPrice - totalCost
    const feePct = (totalCost / actualPrice) * 100

    return {
      grossProfit,
      marginPct: (grossProfit / actualPrice) * 100,
      feePct,
    }
  }

  // 逆向模式：需要成本 + 目标毛利
  if (mode === 'reverse') {
    if (!costPrice || !targetProfit) return null

    // 固定成本（不随售价变化的部分）
    const fixedCost =
      (costPrice || 0) + (shippingCost || 0) + (packagingCost || 0) +
      (fbaFee || 0) + (storageFee || 0) + (adCost || 0)

    // 费率参数
    const r = (referralFeePct || 0) / 100       // 佣金率
    const v = (vatRate || 0) / 100               // VAT 率
    const w = (withdrawalFeePct || 0) / 100      // 提现费率
    const e = (exchangeLossPct || 0) / 100       // 汇率损失率
    const rr = (returnRatePct || 0) / 100        // 退货率
    const d = (discountPct || 0) / 100           // 折扣率

    // 逆向公式推导：
    // 实际售价 = 标价 × (1 - d)
    // 毛利 = 实际售价 - 固定成本 - 退货损耗 - 佣金 - VAT - 提现费 - 汇率损失
    // 其中：退货损耗 = 固定成本 × rr/(1-rr)
    //       佣金 = 实际售价 × r
    //       VAT = 实际售价 × v
    //       提现费 = 实际售价 × w
    //       汇率损失 = 实际售价 × e
    //
    // 整理得：毛利 = 实际售价 × (1 - r - v - w - e) - 固定成本 × (1 + rr/(1-rr))
    // → 实际售价 = (目标毛利 + 固定成本 × (1 + rr/(1-rr))) / (1 - r - v - w - e)
    // → 标价 = 实际售价 / (1 - d)

    const returnMultiplier = 1 + rr / (1 - rr)
    const totalFixedWithReturn = fixedCost * returnMultiplier
    const rateDenominator = 1 - r - v - w - e

    if (rateDenominator <= 0) {
      // 费率过高，无法盈利
      return {
        grossProfit: 0,
        marginPct: 0,
        feePct: 100,
        suggestedPrice: Infinity,
      }
    }

    const actualPriceNeeded = (targetProfit + totalFixedWithReturn) / rateDenominator
    const suggestedPrice = actualPriceNeeded / (1 - d)

    // 用建议售价反算毛利率供参考
    const actualSuggested = suggestedPrice * (1 - d)
    const refFee = actualSuggested * r
    const vatAmt = actualSuggested * v
    const withFee = actualSuggested * w
    const exLoss = actualSuggested * e
    const retLoss = fixedCost * rr / (1 - rr)
    const totalCost = fixedCost + retLoss + refFee + vatAmt + withFee + exLoss
    const verifyProfit = actualSuggested - totalCost

    return {
      grossProfit: verifyProfit,
      marginPct: (verifyProfit / actualSuggested) * 100,
      feePct: (totalCost / actualSuggested) * 100,
      suggestedPrice,
    }
  }

  return null
})

// ====== 持久化 ======
onMounted(() => {
  try {
    const saved = localStorage.getItem('profit_config_v2')
    if (saved) {
      const parsed = JSON.parse(saved)
      Object.assign(form, parsed)
      // 恢复时重新检测输入类型
      if (form.productInput) {
        onInputChange(form.productInput)
      }
    }
  } catch (e) {}
})

// 自动保存
watch(
  () => ({ ...form }),
  (val) => {
    try {
      localStorage.setItem('profit_config_v2', JSON.stringify(val))
    } catch (e) {}
  },
  { deep: true }
)

// ====== 提交 ======
const handleSubmit = () => {
  if (form.mode === 'forward') {
    if (!form.costPrice || !form.sellingPrice) {
      message.warning('正向计算：请填写采购成本和目标售价')
      return
    }
  } else {
    if (!form.costPrice || !form.targetProfit) {
      message.warning('逆向定价：请填写采购成本和目标毛利')
      return
    }
  }

  loading.value = true

  // 构建完整参数对象发给后端/AI
  const params = {
    ...form,
    // 附上快速预览结果供参考
    _preview: quickPreview.value,
  }

  emit('startAnalysis', params)
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
  advancedActiveKey.value = []
  detectedType.value = ''
  detectedPlatform.value = ''
  detectedProduct.value = null
  localStorage.removeItem('profit_config_v2')
  message.success('已重置')
}
</script>

<style scoped>
.profit-config {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group > label {
  display: block;
  font-size: 12px;
  color: #595959;
  margin-bottom: 3px;
  font-weight: 500;
}

.form-row {
  display: flex;
  gap: 8px;
}

.flex-1 { flex: 1; }

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #262626;
  margin-top: 4px;
}

.mode-switch {
  display: flex;
  justify-content: center;
}

/* 折叠面板样式优化 */
.profit-config :deep(.ant-collapse-header) {
  padding: 4px 0 !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  color: #1890ff !important;
}

.profit-config :deep(.ant-collapse-content-box) {
  padding: 8px 0 !important;
}

/* 快速预览 */
.quick-preview {
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 6px;
  padding: 8px 10px;
}

.preview-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 0;
}

.preview-label {
  font-size: 11px;
  color: #8c8c8c;
}

.preview-value {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
}

.preview-value.positive {
  color: #52c41a;
}

.preview-value.negative {
  color: #ff4d4f;
}

.preview-value.warning {
  color: #fa8c16;
}

.preview-value.suggested {
  color: #1890ff;
  font-size: 16px;
}

.preview-hint {
  margin-top: 6px;
  padding: 6px 8px;
  background: #e6f7ff;
  border-radius: 4px;
  font-size: 11px;
  color: #595959;
  line-height: 1.5;
}

/* 操作按钮 */
.action-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid #f0f0f0;
}

/* 智能输入框 */
.smart-input-wrapper { position: relative; }

.smart-input-picker {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
}

.smart-input-picker :deep(.picker-btn) {
  font-size: 11px !important;
  color: #1890ff !important;
  padding: 0 6px !important;
  background: rgba(230, 247, 255, 0.6) !important;
  border: 1px solid #91d5ff !important;
  border-radius: 4px !important;
}

.smart-input-picker :deep(.picker-btn:hover) {
  background: #e6f7ff !important;
}

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

.hint-chip:hover { background: #e6f7ff; color: #1890ff; border-color: #91d5ff; }
.hint-chip.active { background: #e6f7ff; color: #1890ff; border-color: #1890ff; }

/* 迷你商品卡片 */
.product-card-mini {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%);
  border: 1px solid #bae7ff;
  border-radius: 6px;
  font-size: 11px;
}

.mini-platform { font-weight: 600; color: #1890ff; }
.mini-id {
  font-family: 'SF Mono', Monaco, monospace;
  color: #262626;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mini-clear { cursor: pointer; color: #999; }
.mini-clear:hover { color: #ff4d4f; }
</style>

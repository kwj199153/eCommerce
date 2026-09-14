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
            <a-tag :color="platformTagColor" size="small" style="margin-right: var(--space-4); font-size: var(--font-size-10)">
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

    <!-- ====== 成本明细表（Excel 风格：表头 + 一行一项 + 框线 + 分组合并格）======
         输入框去掉自身边框融进单元格，聚焦时整格高亮；金额/费率的含义统一写在「说明」列 -->
    <div class="cost-sheet">
      <table class="cost-table">
        <colgroup>
          <col class="col-group" />
          <col class="col-item" />
          <col class="col-value" />
          <col class="col-hint" />
        </colgroup>
        <thead>
          <tr>
            <th>分组</th>
            <th>成本项</th>
            <th>数值</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in costRows" :key="row.key">
            <td v-if="row.span" :rowspan="row.span" class="cell-group">{{ row.group }}</td>
            <td class="cell-item">{{ row.label }}</td>
            <td class="cell-value">
              <a-input-number
                v-model:value="row.value"
                size="small"
                :min="row.min"
                :max="row.max"
                :step="row.step"
                :precision="row.precision"
                :placeholder="row.placeholder"
                :disabled="row.disabled"
              />
            </td>
            <td class="cell-hint">{{ row.hint }}</td>
          </tr>
        </tbody>
      </table>
      <div class="sheet-note">正向计算：填「目标售价」算利润；逆向定价：填「目标毛利」算售价（「目标售价」自动禁用）。其余空值一律按 0 计算。</div>
    </div>

    <!-- ====== 计算模式 + 操作（同一行，不再各占一段）====== -->
    <div class="mode-bar">
      <a-radio-group v-model:value="form.mode" size="small" button-style="solid">
        <a-radio-button value="forward">正向计算</a-radio-button>
        <a-radio-button value="reverse">逆向定价</a-radio-button>
      </a-radio-group>

      <div v-if="form.mode === 'reverse'" class="mode-target">
        <label>目标毛利 ($)</label>
        <a-input-number v-model:value="form.targetProfit" placeholder="期望利润" :min="0" :precision="2" size="small" style="width: 100%" />
      </div>

      <div class="mode-actions">
        <a-button size="small" @click="handleReset">
          <ReloadOutlined /> 重置
        </a-button>
        <a-button type="primary" size="small" :loading="loading" @click="handleSubmit">
          <CalculatorOutlined /> {{ form.mode === 'forward' ? '计算利润' : '计算售价' }}
        </a-button>
      </div>
    </div>

    <!-- ====== 实时预览（后端唯一计算源，与对话结果卡同源）======
         这里不再有前端公式：输入 → 调 /stores/profit/calculate（费率来自当前店铺）
         → 拿回的 result 同时喂给本预览区与对话结果卡，两处只做渲染差异。 -->
    <div v-if="preview" class="quick-preview">
      <div class="preview-metrics">
        <template v-if="form.mode === 'forward'">
          <div class="preview-item">
            <span class="preview-label">预估毛利</span>
            <span class="preview-value" :class="{ positive: preview.net_profit > 0, negative: preview.net_profit <= 0 }">
              {{ preview.net_profit > 0 ? '+' : '' }}${{ (preview.net_profit ?? 0).toFixed(2) }}
            </span>
          </div>
          <div class="preview-item">
            <span class="preview-label">毛利率</span>
            <span class="preview-value">{{ (preview.profit_margin_pct ?? 0).toFixed(1) }}%</span>
          </div>
          <div class="preview-item">
            <span class="preview-label">总费用占比</span>
            <span class="preview-value warning">{{ previewCostPct.toFixed(1) }}%</span>
          </div>
        </template>
        <template v-else>
          <div class="preview-item">
            <span class="preview-label">建议售价</span>
            <span class="preview-value suggested">${{ (preview.listing_price ?? 0).toFixed(2) }}</span>
          </div>
          <div class="preview-item">
            <span class="preview-label">对应毛利率</span>
            <span class="preview-value">{{ (preview.profit_margin_pct ?? 0).toFixed(1) }}%</span>
          </div>
        </template>
      </div>
      <div v-if="form.mode === 'reverse'" class="preview-hint">
        要实现 ${{ (form.targetProfit || 0).toFixed(2) }} 目标毛利，需定价不低于 ${{ (preview.listing_price ?? 0).toFixed(2) }}
      </div>
      <div class="preview-source">{{ preview.platform }} · {{ preview.currency }} · 费率取当前店铺</div>
    </div>
    <div v-else-if="previewError" class="quick-preview quick-preview--error">{{ previewError }}</div>
    <div v-else class="quick-preview quick-preview--idle">
      {{ previewLoading
        ? '正在按当前店铺费率测算…'
        : `填好「采购成本」和${form.mode === 'forward' ? '目标售价' : '目标毛利'}，这里会实时给出店铺费率下的结果。` }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ReloadOutlined, CalculatorOutlined, SearchOutlined, ShopOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import { calculateProfit, toProfitRequest, type ProfitResult } from '@/api/stores'
import { useShopStore } from '@/stores/shop'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

// 当前店铺决定费率模板 —— 利润测算的「平台规则」部分由它提供
const shopStore = useShopStore()

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

// ====== 成本明细表定义（Excel 风格表格的数据源）======
// 一行一项；group 相同的连续行在表格里合并为一格（rowspan）
interface CostRowDef {
  key: string
  group: string
  label: string
  hint: string
  min?: number
  max?: number
  step?: number
  precision?: number
  placeholder?: string
  /** 逆向定价时禁用（该项由计算得出、不该手填）—— 目前只有「目标售价」 */
  disabledInReverse?: boolean
}

const COST_ROWS_DEF: CostRowDef[] = [
  // 基础成本
  { key: 'costPrice', group: '基础成本', label: '采购成本', hint: '$ / 单件', min: 0, precision: 2, placeholder: '0.00' },
  { key: 'shippingCost', group: '基础成本', label: '头程运费', hint: '$ / 单件', min: 0, precision: 2, placeholder: '0.00' },
  { key: 'packagingCost', group: '基础成本', label: '包装成本', hint: '$ / 单件', min: 0, precision: 2, placeholder: '0.00' },
  // 目标售价：正向计算的核心输入（必填）；逆向定价时它是计算结果，故禁用
  { key: 'sellingPrice', group: '基础成本', label: '目标售价', hint: '$ · 逆向定价无需填', min: 0, precision: 2, placeholder: '0.00', disabledInReverse: true },
  // 平台费用
  { key: 'referralFeePct', group: '平台费用', label: '平台佣金', hint: '% · 亚马逊默认 15', min: 0, max: 45, step: 0.5, precision: 1, placeholder: '15' },
  { key: 'fbaFee', group: '平台费用', label: 'FBA 配送费', hint: '$ / 单件', min: 0, precision: 2, placeholder: '3.22' },
  { key: 'storageFee', group: '平台费用', label: '月仓储费', hint: '$ / 单件', min: 0, precision: 2, placeholder: '0.87' },
  { key: 'withdrawalFeePct', group: '平台费用', label: '提现手续费', hint: '%', min: 0, max: 5, step: 0.1, precision: 1, placeholder: '1' },
  // 营销 + 税费
  { key: 'adCost', group: '营销税费', label: 'PPC 广告费', hint: '$ · 0 = 不投', min: 0, precision: 2, placeholder: '0' },
  { key: 'vatRate', group: '营销税费', label: 'VAT 税率', hint: '% · 欧洲站必填', min: 0, max: 25, step: 1, precision: 0, placeholder: '0' },
  { key: 'discountPct', group: '营销税费', label: '促销折扣', hint: '% · 按标价折', min: 0, max: 50, step: 1, precision: 0, placeholder: '0' },
  // 其他成本
  { key: 'returnRatePct', group: '其他成本', label: '退货损耗率', hint: '% · 服装类 5-15', min: 0, max: 50, step: 1, precision: 0, placeholder: '0' },
  { key: 'exchangeLossPct', group: '其他成本', label: '汇率损失', hint: '% · 通常 1-2', min: 0, max: 10, step: 0.5, precision: 1, placeholder: '1.5' },
]

// 转成可直接 v-model 的行：getter/setter 读写 form 的对应字段，避免模板里写 13 段重复结构；
// 每个分组首行带 span（=该组行数），其余为 0 —— 模板据此只渲染一次分组格并 rowspan 合并
const costRows = COST_ROWS_DEF.map((def, i, arr) => {
  const isGroupStart = i === 0 || arr[i - 1]?.group !== def.group
  const span = isGroupStart ? arr.filter((d) => d.group === def.group).length : 0
  return {
    ...def,
    span,
    get value(): any { return (form as any)[def.key] },
    set value(v: any) { (form as any)[def.key] = v },
    // 是否禁用：随计算模式变化 —— 「目标售价」在逆向定价下由计算得出，不该手填
    get disabled(): boolean {
      return Boolean(def.disabledInReverse && form.mode === 'reverse')
    },
    // 说明文案同样随模式变化：正向计算时它是必填项，不能沿用「无需填」的说法
    get hint(): string {
      if (def.key !== 'sellingPrice') return def.hint
      return form.mode === 'forward' ? '$ · 正向计算必填' : '$ · 由计算得出'
    },
  }
})

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

// ====== 实时预览（后端为唯一计算源）======
// 之前这里是一段前端 computed 公式，与 mock 执行器、后端引擎三方并存 ——
// 同一份输入能算出三个结果。现在只保留一条路：调后端。
const preview = ref<ProfitResult | null>(null)
const previewLoading = ref(false)
const previewError = ref('')

let previewTimer: ReturnType<typeof setTimeout> | null = null

const shopId = computed(() => shopStore.currentShopId || '')

/** 总费用占成交价比例 (%) */
const previewCostPct = computed(() => {
  const p = preview.value
  if (!p || !p.final_price) return 0
  return (p.total_cost / p.final_price) * 100
})

/** 三个必要条件齐了才发请求：选了店铺、填了采购成本、填了售价或目标毛利 */
const canPreview = computed(() => {
  if (!shopId.value) return false
  if (!form.costPrice) return false
  return form.mode === 'forward' ? !!form.sellingPrice : !!form.targetProfit
})

const runPreview = async () => {
  if (!canPreview.value) {
    preview.value = null
    previewError.value = shopId.value ? '' : '未选择店铺，取不到费率模板'
    return
  }
  previewLoading.value = true
  try {
    preview.value = await calculateProfit(toProfitRequest(form), shopId.value)
    previewError.value = ''
  } catch (e: any) {
    // 降级必须给出原因，绝不编一个数字顶上（空状态优于虚构默认）
    preview.value = null
    previewError.value = e?.message || '测算失败，请检查参数或店铺费率配置'
  } finally {
    previewLoading.value = false
  }
}

/** 输入停顿 350ms 再请求：保住「边填边看」的手感，又不至于每敲一个字符打一次后端 */
const schedulePreview = () => {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(runPreview, 350)
}

// 换店铺 = 换费率模板，必须重算
watch(shopId, () => runPreview())

onBeforeUnmount(() => {
  if (previewTimer) clearTimeout(previewTimer)
})


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
  // 恢复上次参数后立刻按当前店铺费率算一次（与恢复出来的表单保持一致）
  runPreview()
})

// 自动保存
watch(
  () => ({ ...form }),
  (val) => {
    try {
      localStorage.setItem('profit_config_v2', JSON.stringify(val))
    } catch (e) {}
    schedulePreview()
  },
  { deep: true }
)

// ====== 提交 ======
const handleSubmit = async () => {
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

  // 同源关键：把后端刚算出的这份结果原样交给对话区，
  // 对话结果卡据此渲染 —— 不再自己算第二遍。
  if (!preview.value) await runPreview()

  const params = {
    ...form,
    _preview: preview.value,
  }

  emit('startAnalysis', params)
  setTimeout(() => (loading.value = false), 500)
}

const handleReset = () => {
  Object.assign(form, defaultForm())
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
  gap: var(--space-6);
}

.form-group > label {
  display: block;
  font-size: var(--font-size-12);
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
  font-weight: 500;
}

/* ====== 成本明细表（Excel 风格）======
   一行一项、表头 + 框线 + 分组合并单元格；输入框去边框融进单元格，
   聚焦时整格高亮 —— 观感对齐 Excel 的「选中单元格」。 */
.cost-sheet {
  border: 1px solid var(--border-base);
  border-radius: var(--radius-6);
  overflow: hidden;
}

.cost-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: var(--font-size-11);
}

.cost-table .col-group { width: 58px; }
.cost-table .col-item { width: 80px; }
/* 数值列定宽：只放数字，把剩余宽度全部让给「说明」列 */
.cost-table .col-value { width: 104px; }

.cost-table th {
  height: 26px;
  padding: 0 var(--space-6);
  font-size: var(--font-size-10);
  font-weight: 500;
  color: var(--text-tertiary);
  text-align: left;
  background: var(--bg-hover-light);
  border-right: 1px solid var(--border-base);
  border-bottom: 1px solid var(--border-base);
}

.cost-table th:last-child { border-right: none; }

.cost-table td {
  height: 28px;
  padding: 0;
  vertical-align: middle;
  border-right: 1px solid var(--border-base);
  border-bottom: 1px solid var(--border-base);
}

.cost-table td:last-child { border-right: none; }
.cost-table tbody tr:last-child td { border-bottom: none; }
.cost-table tbody tr:hover td { background: var(--bg-hover-light); }

.cost-table td.cell-group {
  text-align: center;
  font-size: var(--font-size-10);
  color: var(--text-secondary);
  background: var(--bg-hover-light);
  white-space: nowrap;
}

.cost-table td.cell-item {
  padding: 0 var(--space-6);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cost-table td.cell-hint {
  padding: 0 var(--space-6);
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cost-table td.cell-value { position: relative; }

/* 输入框与单元格融为一体：去边框去圆角，聚焦时由格子的 inset 描边接管 */
.cost-table td.cell-value :deep(.ant-input-number) {
  width: 100%;
  height: 27px;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.cost-table td.cell-value :deep(.ant-input-number-input) {
  height: 26px;
  padding: 0 var(--space-6);
  font-size: var(--font-size-11);
}

.cost-table td.cell-value :deep(.ant-input-number-focused) { box-shadow: none; }

/* 空值占位符：antd 默认色 rgba(0,0,0,.25) 与「禁用态文字色」**完全相同** ——
   于是「待填的空格」看起来和「不能填的格子」一模一样（这就是「目标售价不该灰」的根因）。
   提到 --text-tertiary 后：中灰 = 空且可填；浅灰 + 灰底 = 已禁用，一眼可辨。 */
.cost-table td.cell-value :deep(.ant-input-number-input::placeholder) {
  color: var(--text-tertiary);
}

/* 禁用态（仅逆向定价时的「目标售价」）：垫灰底 + not-allowed，与「空且可填」区分开 */
.cost-table td.cell-value :deep(.ant-input-number-disabled) {
  background: var(--bg-base);
  cursor: not-allowed;
}

.cost-table td.cell-value:focus-within {
  background: var(--info-bg);
  box-shadow: inset 0 0 0 1px var(--primary);
}

.sheet-note {
  padding: var(--space-5) var(--space-8);
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
  line-height: 1.5;
  background: var(--bg-base);
  border-top: 1px solid var(--border-base);
}

/* ====== 计算模式 + 操作（合并到同一行，不再各占一段）====== */
.mode-bar {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  flex-wrap: wrap;
  margin-top: var(--space-4);
  padding-top: var(--space-10);
  border-top: 1px solid var(--border-base);
}

.mode-target {
  flex: 1;
  min-width: 120px;
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.mode-target > label {
  margin: 0;
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  white-space: nowrap;
}

.mode-actions {
  display: flex;
  gap: var(--space-6);
  margin-left: auto;
}

/* ====== 实时预览（横排三格，和表单同屏可见）====== */
.quick-preview {
  background: var(--success-bg);
  border: 1px solid var(--success-border);
  border-radius: var(--radius-6);
  padding: var(--space-8) var(--space-10);
}

.preview-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-8);
}

.preview-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.preview-label {
  font-size: var(--font-size-11);
  color: var(--text-tertiary);
}

.preview-value {
  font-size: var(--font-size-16);
  font-weight: 600;
  color: var(--text-primary);
}

.preview-value.positive { color: var(--success); }
.preview-value.negative { color: var(--danger); }
.preview-value.warning { color: var(--warning); }

.preview-value.suggested { color: var(--primary); }

/* 数据来源标注：让人一眼看出这个数字是店铺费率算出来的，不是本地估的 */
.preview-source {
  margin-top: var(--space-6);
  padding-top: var(--space-5);
  border-top: 1px solid var(--success-border);
  font-size: var(--font-size-10);
  color: var(--text-tertiary);
}

/* 未就绪 / 失败态：明确的空状态或原因，不给假数字 */
.quick-preview--idle {
  background: var(--bg-base);
  border-color: var(--border-base);
  color: var(--text-tertiary);
  font-size: var(--font-size-11);
  line-height: 1.6;
}

.quick-preview--error {
  background: var(--bg-base);
  border-color: var(--border-base);
  color: var(--danger);
  font-size: var(--font-size-11);
  line-height: 1.6;
}

.preview-hint {
  margin-top: var(--space-8);
  padding-top: var(--space-6);
  border-top: 1px solid var(--success-border);
  font-size: var(--font-size-11);
  color: var(--text-secondary);
  line-height: 1.5;
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
  font-size: var(--font-size-11) !important;
  color: var(--primary) !important;
  padding: 0 var(--space-6) !important;
  background: rgba(230, 247, 255, 0.6) !important;
  border: 1px solid var(--info-border) !important;
  border-radius: var(--radius-4) !important;
}

.smart-input-picker :deep(.picker-btn:hover) {
  background: var(--info-bg) !important;
}

.input-hints {
  display: flex;
  gap: var(--space-6);
  margin-top: var(--space-6);
  flex-wrap: wrap;
}

.hint-chip {
  font-size: var(--font-size-10);
  padding: var(--space-2) var(--space-8);
  border-radius: var(--radius-10);
  background: var(--bg-hover-light);
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.hint-chip:hover { background: var(--info-bg); color: var(--primary); border-color: var(--info-border); }
.hint-chip.active { background: var(--info-bg); color: var(--primary); border-color: var(--primary); }

/* 迷你商品卡片 */
.product-card-mini {
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: var(--space-5) var(--space-8);
  background: linear-gradient(135deg, #f0f9ff 0%, #e6f7ff 100%);
  border: 1px solid #bae7ff;
  border-radius: var(--radius-6);
  font-size: var(--font-size-11);
}

.mini-platform { font-weight: 600; color: var(--primary); }
.mini-id {
  font-family: 'SF Mono', Monaco, monospace;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mini-clear { cursor: pointer; color: #999; }
.mini-clear:hover { color: var(--danger); }
</style>

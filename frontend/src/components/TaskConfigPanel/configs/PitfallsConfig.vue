<template>
  <div class="pitfalls-config">
    <!-- 当前店铺平台提示 -->
    <a-alert
      class="platform-banner"
      type="info"
      show-icon
    >
      <template #message>
        <span class="platform-banner-text">
          🏪 目标市场：<b>{{ getPlatformLabel(currentPlatform) }}</b>
          <span class="platform-mode-hint">
            {{ isAmazonMode ? '（亚马逊合规体系：FCC/CPSC/FDA/Prop65 等）' : '（Shopee/Temu 合规体系）' }}
          </span>
        </span>
      </template>
    </a-alert>

    <a-collapse v-model:activeKey="activeKeys" ghost>

      <!-- ====== 输入来源 ====== -->
      <a-collapse-panel key="input" header="📥 输入来源">
        <a-form layout="vertical" :model="form">
          <a-form-item label="输入方式" required>
            <a-radio-group v-model:value="form.input_mode" @change="onInputModeChange; saveForm()">
              <a-radio-button value="product">📦 产品库载入</a-radio-button>
              <a-radio-button value="manual">✏️ 手动输入</a-radio-button>
            </a-radio-group>
          </a-form-item>

          <!-- 模式1：从产品库载入 -->
          <template v-if="form.input_mode === 'product'">
            <a-form-item label="目标商品" required>
              <div class="input-with-picker">
                <a-input
                  :value="productTitle || '未选择产品'"
                  placeholder="请先从产品库载入商品"
                  :disabled="true"
                  size="large"
                  style="flex: 1"
                />
                <ProductPickerButton
                  :model-value="selectedProduct"
                  @select="onProductSelect"
                />
              </div>
              <div v-if="productTitle" class="seed-preview">
                <a-tag color="blue">📦 {{ productTitle }}</a-tag>
                <span v-if="productAsin" class="text-hint">ASIN: {{ productAsin }}</span>
              </div>
            </a-form-item>

            <!-- 产品库自动读取的字段预览 -->
            <div v-if="workingProduct" class="auto-fields-preview">
              <div class="preview-title">📋 自动读取字段</div>
              <div class="preview-grid">
                <div class="preview-item"><span class="label">关键词：</span><span class="value">{{ workingProduct.keywords?.join(', ') || '-' }}</span></div>
                <div class="preview-item"><span class="label">竞品ASIN：</span><span class="value">{{ workingProduct.competitor_asins?.join(', ') || '-' }}</span></div>
                <div class="preview-item"><span class="label">尺寸重量：</span><span class="value">{{ workingProduct.dimensions || workingProduct.package_size || '-' }}</span></div>
                <div class="preview-item"><span class="label">售价区间：</span><span class="value">¥{{ workingProduct.cost || '-' }} ~ ¥{{ workingProduct.price || '-' }}</span></div>
              </div>
            </div>
          </template>

          <!-- 模式2：手动输入 -->
          <template v-if="form.input_mode === 'manual'">
            <a-form-item label="产品关键词" required>
              <a-input
                v-model:value="form.manual_keyword"
                placeholder="例：portable humidifier, mini humidifier, bedroom"
                size="large"
                @change="saveForm"
              />
            </a-form-item>
            <a-form-item label="竞品 ASIN 列表（3-5 个）" required>
              <a-select
                v-model:value="form.manual_asins"
                mode="tags"
                placeholder="输入竞品 ASIN，回车添加"
                style="width: 100%"
                @change="saveForm"
              >
              </a-select>
              <div class="field-hint">输入 3-5 个同类竞品 ASIN 用于对标分析</div>
            </a-form-item>
            <a-form-item label="目标类目（可选）">
              <a-input
                v-model:value="form.category_hint"
                placeholder="例：Home & Kitchen > Humidifiers"
                @change="saveForm"
              />
            </a-form-item>
          </template>
        </a-form>
      </a-collapse-panel>

      <!-- ====== 风险扫描维度（5大类） ====== -->
      <a-collapse-panel key="dimensions" header="🔍 风险扫描维度（5大类）">
        <a-form layout="vertical" :model="form">
          <a-form-item label="选择要检测的风险类别">
            <div class="risk-category-list">
              <div
                v-for="cat in riskCategories"
                :key="cat.id"
                class="risk-category-card"
                :class="{ active: form.risk_categories.includes(cat.id) }"
                @click="toggleRiskCategory(cat.id)"
              >
                <div class="cat-header">
                  <span class="cat-icon">{{ cat.icon }}</span>
                  <span class="cat-name">{{ cat.name }}</span>
                </div>
                <div class="cat-desc">{{ cat.desc }}</div>
                <div class="cat-items">
                  <span v-for="item in cat.items" :key="item" class="cat-item-tag">{{ item }}</span>
                </div>
              </div>
            </div>
          </a-form-item>

          <!-- 亚马逊专属：认证清单提示 -->
          <a-alert
            v-if="isAmazonMode && form.risk_categories.includes('compliance')"
            type="warning"
            show-icon
            message="亚马逊美国站将自动检测 FCC / CPSC / FDA / Prop65 / CE 等强制认证要求"
            style="margin-bottom: 12px"
          />

          <!-- Shopee/Temu 提示 -->
          <a-alert
            v-if="!isAmazonMode && form.risk_categories.includes('compliance')"
            type="info"
            show-icon
            :message="`${getPlatformLabel(currentPlatform)} 平台将检测对应站点的合规要求（禁售品类、资质审核、特殊品类准入）`"
            style="margin-bottom: 12px"
          />
        </a-form>
      </a-collapse-panel>

      <!-- ====== 扫描深度 ====== -->
      <a-collapse-panel key="depth" header="⚙️ 扫描设置">
        <a-form layout="vertical" :model="form">
          <a-form-item label="最低告警级别">
            <a-radio-group v-model:value="form.min_severity" @change="saveForm">
              <a-radio-button value="high">🔴 仅高危</a-radio-button>
              <a-radio-button value="medium">🔴+🟡 高危+中风险</a-radio-button>
              <a-radio-button value="low">全部显示</a-radio-button>
            </a-radio-group>
          </a-form-item>

          <a-form-item label="报告输出选项">
            <a-checkbox-group v-model:value="form.output_options" @change="saveForm">
              <div class="output-options">
                <a-checkbox value="summary">📊 风险汇总总览（高危/中/低 统计 + 开发建议）</a-checkbox>
                <a-checkbox value="actionable">✅ 可执行规避方案清单</a-checkbox>
                <a-checkbox value="cert_map">📜 认证要求清单（含预估成本与周期）</a-checkbox>
                <a-checkbox value="market_analysis">📈 市场饱和度与竞争格局分析</a-checkbox>
                <a-checkbox value="alternative">💡 替代品类建议</a-checkbox>
                <a-checkbox value="save_archive">💾 保存归档到产品库</a-checkbox>
              </div>
            </a-checkbox-group>
          </a-form-item>
        </a-form>
      </a-collapse-panel>

    </a-collapse>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <a-button
        type="primary"
        block
        size="large"
        @click="handleScan"
        :loading="scanning"
        :disabled="!canSubmit"
      >
        ⚠️ 开始风险评估
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, inject, watch, computed, onMounted, type Ref } from 'vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'
import { useShopStore } from '@/stores/shop'
import { getPlatformLabel, isAmazonMode as checkAmazonMode } from '@/utils/platform'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// ====== 店铺平台 ======
const shopStore = useShopStore()
const currentPlatform = computed(() => shopStore.currentShop?.platform || null)
const isAmazonMode = computed(() => checkAmazonMode(currentPlatform.value))

// 注入全局工作商品
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

const productTitle = ref('')
const productAsin = ref('')

watch(() => workingProduct?.value, (p) => {
  try {
    if (p) {
      productTitle.value = p.title || ''
      productAsin.value = p.asin || ''
      selectedProduct.value = p
      // 切换到产品库模式
      form.value.input_mode = 'product'
    }
  } catch (e) {
    console.error('[PitfallsConfig watch ERROR]', e)
  }
}, { immediate: true })

// ====== 5 大类风险定义 ======
const riskCategories = [
  {
    id: 'ip_infringement',
    icon: '📋',
    name: '知识产权侵权风险',
    desc: '检测 IP 形象、专利、品牌垄断',
    items: ['知名IP检索', '外观/实用新型专利', '头部品牌垄断', '侵权隐患判断'],
  },
  {
    id: 'compliance',
    icon: '📜',
    name: '平台合规与认证风险',
    desc: '强制认证、危险品审核、禁售品类',
    items: ['FCC/CE/FDA等认证', '带电/带磁/液体', '类目审核周期', '禁售品类检测'],
  },
  {
    id: 'supply_chain',
    icon: '📦',
    name: '供应链 & 物流损耗风险',
    desc: '尺寸重量、易碎性、季节性库存',
    items: ['超大件/超重预警', '易碎材质识别', '季节性积压风险', 'FBA仓储费用'],
  },
  {
    id: 'market_profit',
    icon: '💰',
    name: '市场商业盈利风险',
    desc: '寡头垄断、价格战、差评缺陷、毛利空间',
    items: ['头部销量集中度', '低价内卷预警', '竞品差评缺陷', '毛利空间测算'],
  },
  {
    id: 'operation_risk',
    icon: '🚀',
    name: '运营推广风险',
    desc: '变体泛滥、测评风控、推广成本',
    items: ['变体泛滥风险', '测评刷单风控', '推广成本评估', '类目竞争强度'],
  },
]

// ====== 表单数据 ======
const activeKeys = ref(['input', 'dimensions'])
const scanning = ref(false)

const defaultForm = {
  // 输入方式
  input_mode: 'product' as 'product' | 'manual',
  // 手动输入字段
  manual_keyword: '',
  manual_asins: [] as string[],
  category_hint: '',
  // 风险类别（默认全选5大类）
  risk_categories: ['ip_infringement', 'compliance', 'supply_chain', 'market_profit', 'operation_risk'] as string[],
  // 扫描设置
  min_severity: 'medium' as 'high' | 'medium' | 'low',
  output_options: ['summary', 'actionable', 'cert_map'] as string[],
}

const form = ref({ ...defaultForm })

// 从 localStorage 恢复
onMounted(() => {
  const saved = localStorage.getItem('pitfalls-config')
  if (saved) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

const saveForm = () => localStorage.setItem('pitfalls-config', JSON.stringify(form.value))

// 输入方式切换
const onInputModeChange = () => {
  saveForm()
}

// 风险类别切换
const toggleRiskCategory = (id: string) => {
  const idx = form.value.risk_categories.indexOf(id)
  if (idx >= 0) {
    form.value.risk_categories.splice(idx, 1)
  } else {
    form.value.risk_categories.push(id)
  }
  saveForm()
}

// 产品库选择
const selectedProduct = ref<any>(null)

const onProductSelect = (product: any) => {
  selectedProduct.value = product
  productTitle.value = product.title || ''
  productAsin.value = product.asin || ''
  form.value.input_mode = 'product'
  saveForm()
  message.success(`已选择产品: ${product.title}`)
}

// 是否可以提交
const canSubmit = computed(() => {
  if (!form.value.risk_categories.length) return false
  if (form.value.input_mode === 'manual') {
    return !!form.value.manual_keyword.trim() && form.value.manual_asins.length >= 1
  }
  // product 模式：需要有工作商品或已选产品
  return !!(workingProduct?.value || selectedProduct.value)
})

// 提交扫描
const handleScan = () => {
  if (!canSubmit.value) return

  scanning.value = true
  setTimeout(() => {
    scanning.value = false

    const params: any = {
      tool: 'pitfalls',
      input_mode: form.value.input_mode,
      risk_categories: form.value.risk_categories,
      min_severity: form.value.min_severity,
      output_options: form.value.output_options,
      platform: currentPlatform.value,
      platform_label: getPlatformLabel(currentPlatform.value),
      is_amazon: isAmazonMode.value,
    }

    // 根据输入方式填充产品信息
    if (form.value.input_mode === 'product') {
      const product = workingProduct?.value || selectedProduct.value
      params.product = {
        title: product.title,
        asin: product.asin,
        keywords: product.keywords || [],
        competitor_asins: product.competitor_asins || [],
        dimensions: product.dimensions || product.package_size,
        cost: product.cost,
        price: product.price,
        category: product.category,
        selling_points: product.selling_points,
      }
    } else {
      params.product = {
        keyword: form.value.manual_keyword.trim(),
        competitor_asins: form.value.manual_asins,
        category: form.value.category_hint.trim(),
      }
    }

    // 保存表单
    saveForm()

    emit('startAnalysis', params)
  }, 600)
}

// 重置
const handleReset = () => {
  form.value = { ...defaultForm }
  selectedProduct.value = null
  productTitle.value = ''
  productAsin.value = ''
  localStorage.removeItem('pitfalls-config')
}
</script>

<style scoped>
.pitfalls-config {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 平台提示条 */
.platform-banner {
  flex-shrink: 0;
  margin-bottom: 10px;
}
.platform-banner-text {
  font-size: 12px;
}
.platform-mode-hint {
  margin-left: 8px;
  color: #8c8c8c;
  font-size: 11px;
}

.pitfalls-config :deep(.ant-collapse) {
  flex: 1;
  overflow-y: auto;
}

.config-actions {
  padding: 16px 0 0;
  border-top: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}
.input-with-picker .ant-input {
  flex: 1;
}

/* 已选产品预览 */
.seed-preview {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.text-hint {
  font-size: 12px;
  color: #8c8c8c;
}

/* 自动读取字段预览 */
.auto-fields-preview {
  margin-top: 12px;
  padding: 10px 12px;
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  border-radius: 6px;
}
.preview-title {
  font-size: 12px;
  font-weight: 600;
  color: #389e0d;
  margin-bottom: 6px;
}
.preview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 16px;
}
.preview-item {
  font-size: 11px;
  line-height: 1.6;
}
.preview-item .label {
  color: #8c8c8c;
}
.preview-item .value {
  color: #262626;
}

/* 字段提示 */
.field-hint {
  font-size: 11px;
  color: #8c8c8c;
  margin-top: 4px;
}

/* 风险类别卡片列表 */
.risk-category-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.risk-category-card {
  padding: 12px 14px;
  border: 1.5px solid #d9d9d9;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #fff;
  user-select: none;
}
.risk-category-card:hover {
  border-color: #faad14;
  background: #fffbe6;
}
.risk-category-card.active {
  border-color: #fa8c16;
  background: #fff7e6;
  box-shadow: 0 0 0 2px rgba(250, 140, 22, 0.12);
}
.cat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.cat-icon {
  font-size: 20px;
  flex-shrink: 0;
}
.cat-name {
  font-size: 13px;
  font-weight: 600;
  color: #262626;
}
.cat-desc {
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 6px;
  margin-left: 28px;
}
.cat-items {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-left: 28px;
}
.cat-item-tag {
  font-size: 10px;
  padding: 1px 6px;
  background: #f5f5f5;
  border-radius: 4px;
  color: #595959;
}
.risk-category-card.active .cat-item-tag {
  background: #fff7e6;
  color: #d46b08;
}

/* 输出选项 */
.output-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.output-options .ant-checkbox-wrapper {
  padding: 6px 10px;
  border-radius: 6px;
  transition: background 0.2s;
}
.output-options .ant-checkbox-wrapper:hover {
  background: #fafafa;
}
</style>

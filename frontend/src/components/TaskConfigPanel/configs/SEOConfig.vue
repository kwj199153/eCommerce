<template>
  <div class="seo-config">
    <a-alert
      type="info"
      show-icon
      message="输入 ASIN 后，系统将自动分析该 Listing 的 SEO 健康度"
      style="margin-bottom: 16px"
    />

    <a-form layout="vertical" :model="form">
      <a-form-item label="Listing ASIN" required>
        <div class="input-with-picker">
          <a-input
            v-model:value="form.asin"
            placeholder="例：B0CXXXX001"
            size="large"
            style="flex: 1"
            @change="saveForm"
          >
            <template #prefix>
              <SearchOutlined />
            </template>
          </a-input>
          <ProductPickerButton
            :model-value="selectedMainProduct"
            @select="onMainProductSelect"
          />
        </div>
      </a-form-item>

      <a-form-item label="诊断维度">
        <a-checkbox-group v-model:value="form.dimensions" @change="saveForm">
          <a-row :gutter="[8, 8]">
            <a-col :span="12">
              <a-checkbox value="title">📝 标题优化</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="bullets">✨ 五点描述</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="images">🖼️ 主图质量</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="price">💰 定价竞争力</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="reviews">⭐ 评论健康度</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="keywords">🔑 关键词覆盖</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="a_plus">📄 A+ Content</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="category">📂 类目排名</a-checkbox>
            </a-col>
          </a-row>
        </a-checkbox-group>
      </a-form-item>

      <a-divider style="margin: 12px 0" />

      <a-form-item label="对比竞品（可选）">
        <div class="input-with-picker">
          <a-select
            v-model:value="form.competitors"
            mode="tags"
            placeholder="输入竞品 ASIN 进行对标分析"
            style="flex: 1"
            @change="saveForm"
          />
          <ProductPickerButton
            :model-value="selectedCompetitorProduct"
            @select="onCompetitorSelect"
          />
        </div>
      </a-form-item>

      <a-form-item label="报告深度">
        <a-radio-group v-model:value="form.depth" @change="saveForm">
          <a-radio-button value="quick">快速概览</a-radio-button>
          <a-radio-button value="standard">标准报告</a-radio-button>
          <a-radio-button value="deep">深度分析</a-radio-button>
        </a-radio-group>
      </a-form-item>

      <a-form-item label="输出语言">
        <a-select v-model:value="form.language" @change="saveForm">
          <a-select-option value="zh">中文</a-select-option>
          <a-select-option value="en">English</a-select-option>
        </a-select>
      </a-form-item>
    </a-form>

    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleAnalyze" :loading="analyzing">
        <ExperimentOutlined /> 开始诊断
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, inject, onMounted, watch, type Ref } from 'vue'
import { SearchOutlined, ExperimentOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import ProductPickerButton from './ProductPickerButton.vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// 注入全局工作商品
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// 监听工作商品变化，自动回填 ASIN
watch(() => workingProduct?.value, (product) => {
  try {
    console.log('[SEOConfig watch] product:', product?.asin || null)
    if (product?.asin) {
      form.value.asin = product.asin
    }
  } catch (e) {
    console.error('[SEOConfig watch ERROR]', e)
  }
}, { immediate: true })

/** 从工作商品回填 */
const fillFromProduct = () => {
  if (!workingProduct?.value) return
  const p = workingProduct.value
  if (p.asin) form.value.asin = p.asin
  if (p.competitor_asins?.length) form.value.competitors = [...p.competitor_asins]
  message.success('已从商品档案回填 ASIN')
}

const analyzing = ref(false)

const defaultForm = {
  asin: '',
  dimensions: ['title', 'bullets', 'images', 'price', 'reviews', 'keywords'],
  competitors: [] as string[],
  depth: 'standard',
  language: 'zh',
}

const form = ref({ ...defaultForm })

onMounted(() => {
  const saved = localStorage.getItem('seo-audit-config')
  if (saved) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

const saveForm = () => localStorage.setItem('seo-audit-config', JSON.stringify(form.value))

const handleAnalyze = () => {
  const asin = form.value.asin.trim()
  if (!asin || !/^B0[A-Z0-9]{8,10}$/.test(asin)) {
    return message.warning('请输入有效的 ASIN 格式（如 B0CXXXX001）')
  }
  analyzing.value = true
  setTimeout(() => { analyzing.value = false; emit('startAnalysis', form.value) }, 800)
}

const handleReset = () => { form.value = { ...defaultForm }; localStorage.removeItem('seo-audit-config'); selectedMainProduct.value = null; selectedCompetitorProduct.value = null }

// ====== 产品库选择 ======
const selectedMainProduct = ref<any>(null)
const selectedCompetitorProduct = ref<any>(null)

const onMainProductSelect = (product: any) => {
  selectedMainProduct.value = product
  if (product.asin) {
    form.value.asin = product.asin
    saveForm()
  }
}

const onCompetitorSelect = (product: any) => {
  selectedCompetitorProduct.value = product
  if (product.asin && !form.value.competitors.includes(product.asin)) {
    form.value.competitors = [...form.value.competitors, product.asin]
    saveForm()
  }
}
</script>

<style scoped>
.seo-config { display: flex; flex-direction: column; height: 100%; }

.seo-config .ant-form { flex: 1; overflow-y: auto; padding-right: 4px; }
.config-actions { padding: 16px 0 0; border-top: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }

/* 输入框 + 产品库按钮 */
.input-with-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>

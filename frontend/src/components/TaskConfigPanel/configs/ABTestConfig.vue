<template>
  <div class="ab-test-config">
    <a-alert
      type="info"
      show-icon
      message="生成多个 Listing 版本变体，用于 A/B 测试找出最优方案"
      style="margin-bottom: 16px"
    />

    <a-form layout="vertical" :model="form">
      <a-form-item label="原始 Listing 信息" required>
        <a-textarea
          v-model:value="form.original_listing"
          :rows="4"
          placeholder="粘贴当前的标题和五点描述，或输入产品基本信息"
          @change="saveForm"
        />
      </a-form-item>

      <a-form-item label="测试变量选择">
        <a-checkbox-group v-model:value="form.test_variables" @change="saveForm">
          <a-row :gutter="[8, 8]">
            <a-col :span="12">
              <a-checkbox value="title">📝 标题结构</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="bullets">✨ 五点风格</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="price">💰 价格定位</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="main_image">🖼️ 主图类型</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="branding">🏷️ 品牌露出</a-checkbox>
            </a-col>
            <a-col :span="12">
              <a-checkbox value="tone">🗣️ 语调风格</a-checkbox>
            </a-col>
          </a-row>
        </a-checkbox-group>
      </a-form-item>

      <a-form-item label="生成版本数">
        <a-slider
          v-model:value="form.version_count"
          :min="2"
          :max="4"
          :marks="{ 2: '2 版本', 3: '3 版本', 4: '4 版本' }"
          @change="saveForm"
        />
      </a-form-item>

      <a-divider style="margin: 12px 0" />

      <a-form-item label="差异化方向">
        <a-select
          v-model:value="form.differentiation_strategy"
          placeholder="选择主要差异化方向"
          style="width: 100%"
          @change="saveForm"
        >
          <a-select-option value="emotional">情感共鸣 vs 功能陈述</a-select-option>
          <a-select-option value="data">数据量化 vs 笼统描述</a-select-option>
          <a-select-option value="scenario">场景化 vs 抽象化</a-select-option>
          <a-select-option value="premium">高端定位 vs 性价比</a-select-option>
          <a-select-option value="mixed">混合策略（推荐）</a-select-option>
        </a-select>
      </a-form-item>

      <a-form-item label="目标指标优先级">
        <a-radio-group v-model:value="form.primary_metric" @change="saveForm">
          <a-radio value="ctr">点击率 (CTR)</a-radio>
          <a-radio value="cvr">转化率 (CVR)</a-radio>
          <a-radio value="balanced">均衡优化</a-radio>
        </a-radio-group>
      </a-form-item>

      <a-form-item label="目标受众画像（可选）">
        <a-textarea
          v-model:value="form.audience_profile"
          :rows="2"
          placeholder="描述目标客户特征，帮助 AI 生成更精准的变体"
          @change="saveForm"
        />
      </a-form-item>
    </a-form>

    <div class="config-actions">
      <a-button type="primary" block size="large" @click="handleGenerate" :loading="generating">
        <ExperimentOutlined /> 生成测试版本
      </a-button>
      <a-button block @click="handleReset"><ReloadOutlined /> 重置</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, inject, onMounted, watch, type Ref } from 'vue'
import { ExperimentOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

// 注入全局工作商品
const workingProduct = inject<Ref<any>>('workingProduct', ref(null))

// 监听工作商品变化，自动回填原始 Listing
watch(() => workingProduct?.value, (product) => {
  try {
    console.log('[ABTestConfig watch] product:', product?.title || null)
    if (product) {
      const lines = [
        product.title || '',
        product.generated_title ? `[当前标题] ${product.generated_title}` : '',
        ...(product.generated_bullets?.map((b: any) => `• ${b.title}: ${b.content}`) || []),
      ].filter(Boolean)
      if (lines.length) form.value.original_listing = lines.join('\n')
    }
  } catch (e) {
    console.error('[ABTestConfig watch ERROR]', e)
  }
}, { immediate: true })

/** 从工作商品回填 */
const fillFromProduct = () => {
  if (!workingProduct?.value) return
  const p = workingProduct.value
  const lines = [
    p.title || '',
    p.generated_title ? `[当前标题] ${p.generated_title}` : '',
    ...(p.generated_bullets?.map((b: any) => `• ${b.title}: ${b.content}`) || []),
  ].filter(Boolean)
  if (lines.length) form.value.original_listing = lines.join('\n')
  message.success('已从商品档案回填 Listing 信息')
}

const generating = ref(false)

const defaultForm = {
  original_listing: '',
  test_variables: ['title', 'bullets'] as string[],
  version_count: 3,
  differentiation_strategy: 'mixed',
  primary_metric: 'balanced',
  audience_profile: '',
}

const form = ref({ ...defaultForm })

onMounted(() => {
  const saved = localStorage.getItem('ab-test-config')
  if (saved) try { form.value = { ...defaultForm, ...JSON.parse(saved) } } catch {}
})

const saveForm = () => localStorage.setItem('ab-test-config', JSON.stringify(form.value))

const handleGenerate = () => {
  if (!form.value.original_listing.trim()) return message.warning('请提供原始 Listing 信息')
  if (!form.value.test_variables.length) return message.warning('请至少选择一个测试变量')
  generating.value = true
  setTimeout(() => { generating.value = false; emit('startAnalysis', form.value) }, 800)
}

const handleReset = () => { form.value = { ...defaultForm }; localStorage.removeItem('ab-test-config') }
</script>

<style scoped>
.ab-test-config { display: flex; flex-direction: column; height: 100%; }

.ab-test-config .ant-form { flex: 1; overflow-y: auto; padding-right: 4px; }
.config-actions { padding: 16px 0 0; border-top: 1px solid #f0f0f0; display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
</style>

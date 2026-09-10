<template>
  <div class="market-share-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 产品类目 -->
      <a-form-item label="产品类目" required>
        <a-select
          v-model:value="formState.category"
          show-search
          placeholder="选择或输入产品类目"
          :options="categoryOptions"
          :filter-option="filterOption"
        />
      </a-form-item>

      <!-- 估算方法 -->
      <a-form-item label="估算方法">
        <a-radio-group v-model:value="formState.estimateMethod" :options="methodOptions" />
        <div class="form-hint">BSR基于排名估算，Revenue基于收入估算</div>
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">🌍 市场份额分析将输出</p>
        <ul>
          <li>各品牌市场份额占比（饼图）</li>
          <li>CR4 集中度与 HHI 指数</li>
          <li>市场格局判断（垄断/寡头/竞争）</li>
          <li>可行动的市场洞察建议</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 分析市场格局
        </a-button>
      </div>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  (e: 'startAnalysis', params: any): void
}>()

const loading = ref(false)

const formState = reactive({
  category: '',
  estimateMethod: 'bsr_based',
})

const categoryOptions = [
  { value: 'Home & Kitchen', label: 'Home & Kitchen' },
  { value: 'Electronics', label: 'Electronics' },
  { value: 'Sports & Outdoors', label: 'Sports & Outdoors' },
  { value: 'Beauty & Personal Care', label: 'Beauty & Personal Care' },
  { value: 'Toys & Games', label: 'Toys & Games' },
  { value: 'Health & Household', label: 'Health & Household' },
]

const methodOptions = [
  { label: 'BSR 排名估算（推荐）', value: 'bsr_based' },
  { label: '收入估算', value: 'revenue_based' },
]

const filterOption = (input: string, option: any) => {
  return option.label.toLowerCase().includes(input.toLowerCase())
}

const handleStart = () => {
  if (!formState.category) return
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      category: formState.category,
      estimate_method: formState.estimateMethod,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.market-share-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #f6ffed; border-radius: 8px; border: 1px solid #b7eb8f; }
.tips-title { font-size: 12px; font-weight: 600; color: #389e0d; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>

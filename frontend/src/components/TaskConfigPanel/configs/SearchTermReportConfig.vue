<template>
  <div class="search-term-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 时间范围 -->
      <a-form-item label="时间范围">
        <a-select v-model:value="formState.timeRange" :options="timeRangeOptions" />
      </a-form-item>

      <!-- Campaign 类型 -->
      <a-form-item label="Campaign 类型">
        <a-select v-model:value="formState.campaignType" :options="campaignTypeOptions" allowClear placeholder="不限" />
      </a-form-item>

      <!-- 过滤条件 -->
      <a-form-item label="过滤条件">
        <div class="filter-row">
          <span class="filter-label">最小花费</span>
          <a-input-number v-model:value="formState.minSpend" :min="0" :precision="2" addon-after="$" style="width: 100%" />
        </div>
        <div class="filter-row" style="margin-top: 8px;">
          <span class="filter-label">最小点击</span>
          <a-input-number v-model:value="formState.minClicks" :min="0" style="width: 100%" />
        </div>
      </a-form-item>

      <!-- 排序方式 -->
      <a-form-item label="排序方式">
        <a-select v-model:value="formState.sortBy" :options="sortByOptions" />
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 分析搜索词
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
  timeRange: '30d',
  campaignType: undefined as string | undefined,
  minSpend: 5.0,
  minClicks: 5,
  sortBy: 'spend',
})

const timeRangeOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天（推荐）', value: '30d' },
  { label: '近 90 天', value: '90d' },
]

const campaignTypeOptions = [
  { label: 'SP - 商品推广', value: 'SP' },
  { label: 'SB - 品牌推广', value: 'SB' },
  { label: 'SD - 展示推广', value: 'SD' },
]

const sortByOptions = [
  { label: '按花费排序', value: 'spend' },
  { label: '按销售额排序', value: 'sales' },
  { label: '按 ACoS 排序', value: 'acos' },
  { label: '按 CTR 排序', value: 'ctr' },
]

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      time_range: formState.timeRange,
      campaign_type: formState.campaignType,
      min_spend: formState.minSpend,
      min_clicks: formState.minClicks,
      sort_by: formState.sortBy,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.search-term-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.filter-row { display: flex; align-items: center; gap: 8px; }
.filter-label { font-size: 12px; color: #595959; white-space: nowrap; min-width: 56px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
</style>

<template>
  <div class="intruder-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 监控类目 -->
      <a-form-item label="监控类目" required>
        <a-select
          v-model:value="formState.category"
          show-search
          placeholder="选择要监控的产品类目"
          :options="categoryOptions"
          :filter-option="filterOption"
        />
      </a-form-item>

      <!-- 回溯天数 -->
      <a-form-item label="回溯天数">
        <a-slider v-model:value="formState.lookbackDays" :min="7" :max="90" :step="7" />
        <div style="text-align: center; font-size: 12px; color: #8c8c8c;">{{ formState.lookbackDays }} 天</div>
      </a-form-item>

      <!-- 评论阈值 -->
      <a-form-item label="新卖家最低评论数">
        <a-input-number
          v-model:value="formState.minReviews"
          :min="10"
          :max="500"
          :step="10"
          style="width: 100%"
          addon-after="条"
        />
        <div class="form-hint">低于此阈值的新卖家将被标记为潜在入侵者</div>
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">🚨 入侵者检测将输出</p>
        <ul>
          <li>近期新进入市场的竞争者列表</li>
          <li>威胁等级评估（高/中/低）</li>
          <li>入侵原因分析（低价/差异化/品牌）</li>
          <li>应对策略建议（P0/P1/P2优先级）</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 开始检测
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
  lookbackDays: 30,
  minReviews: 50,
})

const categoryOptions = [
  { value: 'Home & Kitchen', label: 'Home & Kitchen' },
  { value: 'Electronics', label: 'Electronics' },
  { value: 'Sports & Outdoors', label: 'Sports & Outdoors' },
  { value: 'Beauty & Personal Care', label: 'Beauty & Personal Care' },
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
      lookback_days: formState.lookbackDays,
      min_reviews_threshold: formState.minReviews,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.intruder-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #fff1f0; border-radius: 8px; border: 1px solid #ffa39e; }
.tips-title { font-size: 12px; font-weight: 600; color: #cf1322; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>

<template>
  <div class="ad-diagnosis-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 时间范围 -->
      <a-form-item label="时间范围">
        <a-select v-model:value="formState.timeRange" :options="timeRangeOptions" />
      </a-form-item>

      <!-- Campaign 筛选 -->
      <a-form-item label="Campaign 范围">
        <a-select
          v-model:value="formState.campaignScope"
          :options="campaignScopeOptions"
          placeholder="选择分析范围"
        />
      </a-form-item>

      <!-- 基准对比 -->
      <a-form-item label="对比选项">
        <a-checkbox v-model:checked="formState.includeBenchmark">包含行业基准对比</a-checkbox>
        <div class="form-hint">开启后将显示 ACoS/RoAS/CTR 等指标的行业均值</div>
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 开始诊断
        </a-button>
      </div>
    </a-form>

    <!-- 快捷提示 -->
    <div class="quick-tips">
      <p class="tips-title">💡 诊断将评估</p>
      <ul>
        <li>ACoS / RoAS 核心效益指标</li>
        <li>CTR / CVR 转化漏斗健康度</li>
        <li>CPC 成本控制水平</li>
        <li>各 Campaign 健康评分</li>
        <li>Top 问题识别与优化建议</li>
      </ul>
    </div>
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
  campaignScope: 'all',
  includeBenchmark: true,
})

const timeRangeOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天（推荐）', value: '30d' },
  { label: '近 90 天', value: '90d' },
]

const campaignScopeOptions = [
  { label: '全部 Campaign', value: 'all' },
  { label: '仅 SP（商品推广）', value: 'sp' },
  { label: '仅 SB（品牌推广）', value: 'sb' },
  { label: '仅 SD（展示推广）', value: 'sd' },
]

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      time_range: formState.timeRange,
      campaign_ids: formState.campaignScope === 'all' ? undefined : [formState.campaignScope],
      include_benchmark: formState.includeBenchmark,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.ad-diagnosis-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.quick-tips { margin-top: 16px; padding: 12px; background: #f6ffed; border-radius: 8px; border: 1px solid #b7eb8f; }
.tips-title { font-size: 12px; font-weight: 600; color: #389e0d; margin-bottom: 6px; }
.quick-tips ul { margin: 0; padding-left: 18px; font-size: 11.5px; color: #595959; line-height: 1.7; }
</style>

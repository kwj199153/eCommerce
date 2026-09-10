<template>
  <div class="budget-alloc-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 总日预算 -->
      <a-form-item label="总日预算（可选）">
        <a-input-number
          v-model:value="formState.totalDailyBudget"
          :min="50"
          :max="10000"
          :step="50"
          addon-after="$/天"
          placeholder="留空则基于当前预算优化"
          style="width: 100%"
        />
        <div class="form-hint">设定后将在总预算约束下重新分配</div>
      </a-form-item>

      <!-- 目标 RoAS -->
      <a-form-item label="目标 RoAS（可选）">
        <a-input-number
          v-model:value="formState.targetRoas"
          :min="1"
          :max="20"
          :step="0.5"
          addon-after="x"
          placeholder="留空则自动计算"
          style="width: 100%"
        />
      </a-form-item>

      <!-- 单 Campaign 最小预算 -->
      <a-form-item label="单 Campaign 最小预算">
        <a-input-number
          v-model:value="formState.minCampaignBudget"
          :min="10"
          :max="500"
          addon-after="$"
          style="width: 100%"
        />
      </a-form-item>

      <!-- 季节性因素 -->
      <a-form-item label="季节性因素">
        <a-select v-model:value="formState.seasonalityFactor" :options="seasonalityOptions" />
        <div v-if="formState.seasonalityFactor !== 'normal'" class="season-hint" :class="'hint-' + formState.seasonalityFactor">
          {{ seasonalityHints[formState.seasonalityFactor] }}
        </div>
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 优化预算分配
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
  totalDailyBudget: undefined as number | undefined,
  targetRoas: undefined as number | undefined,
  minCampaignBudget: 20,
  seasonalityFactor: 'normal',
})

const seasonalityOptions = [
  { label: '正常季节', value: 'normal' },
  { label: '淡季（减少投放）', value: 'low' },
  { label: '旺季前（逐步加码）', value: 'high' },
  { label: '旺季（全力投放）', value: 'peak' },
]

const seasonalityHints: Record<string, string> = {
  low: '建议整体缩减 15-25%，保留核心词 Campaign',
  normal: '基于历史 ROI 正常分配',
  high: '建议逐步增加 20-30% 预算，提前预热',
  peak: '全力投入，优先保障高转化 Campaign',
}

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      total_daily_budget: formState.totalDailyBudget,
      target_roas: formState.targetRoas,
      min_campaign_budget: formState.minCampaignBudget,
      seasonality_factor: formState.seasonalityFactor,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.budget-alloc-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.season-hint { padding: 8px 10px; border-radius: 6px; font-size: 11.5px; margin-top: 6px; line-height: 1.5; }
.hint-low { background: #fff7e6; color: #d46b08; border: 1px solid #ffd591; }
.hint-high { background: #e6f7ff; color: #0958d9; border: 1px solid #91d5ff; }
.hint-peak { background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; }
</style>

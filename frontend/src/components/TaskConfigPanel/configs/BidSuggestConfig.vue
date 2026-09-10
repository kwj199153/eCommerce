<template>
  <div class="bid-suggest-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 出价策略 -->
      <a-form-item label="出价策略">
        <a-radio-group v-model:value="formState.strategy" :options="strategyOptions" />
      </a-form-item>

      <!-- 策略说明 -->
      <div v-if="formState.strategy" class="strategy-desc" :class="'desc-' + formState.strategy">
        {{ strategyDescriptions[formState.strategy] }}
      </div>

      <!-- 目标 ACoS -->
      <a-form-item label="目标 ACoS（可选）">
        <a-input-number
          v-model:value="formState.targetAcos"
          :min="5"
          :max="80"
          addon-after="%"
          placeholder="留空则自动计算"
          style="width: 100%"
        />
        <div class="form-hint">设定后出价建议将围绕目标 ACoS 优化</div>
      </a-form-item>

      <!-- 预算变动上限 -->
      <a-form-item label="预算变动上限">
        <a-slider v-model:value="formState.maxBudgetChange" :min="10" :max="50" :step="5" />
        <div style="text-align: center; font-size: 12px; color: #8c8c8c;">{{ formState.maxBudgetChange }}%</div>
      </a-form-item>

      <!-- 指定关键词（可选） -->
      <a-form-item label="指定关键词（可选）">
        <a-select
          v-model:value="formState.keywords"
          mode="tags"
          placeholder="输入关键词，回车添加"
          :token-separators="tokenSeparators"
          style="width: 100%"
        />
        <div class="form-hint">留空则自动分析所有活跃关键词</div>
      </a-form-item>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 生成出价建议
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
const tokenSeparators = [','] as const

const formState = reactive({
  strategy: 'balanced',
  targetAcos: undefined as number | undefined,
  maxBudgetChange: 30,
  keywords: [] as string[],
})

const strategyOptions = [
  { label: '激进型', value: 'aggressive' },
  { label: '平衡型（推荐）', value: 'balanced' },
  { label: '保守型', value: 'conservative' },
]

const strategyDescriptions: Record<string, string> = {
  aggressive: '追求最大曝光和市场份额，建议提高高潜力词出价 15-35%',
  balanced: '兼顾效率与增长，对高效词提价、低效词降价',
  conservative: '控制成本优先，整体降低出价，聚焦高 ROI 词',
}

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      strategy: formState.strategy,
      target_acos: formState.targetAcos,
      max_budget_change: formState.maxBudgetChange / 100,
      keywords: formState.keywords.length > 0 ? formState.keywords : undefined,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.bid-suggest-config { padding: 4px 0; }
.config-form :deep(.ant-form-item) { margin-bottom: 14px; }
.config-form :deep(.ant-form-item-label) { font-size: 13px; font-weight: 500; }
.form-hint { font-size: 11px; color: #8c8c8c; margin-top: 4px; }
.action-bar { margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; }

.strategy-desc {
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 11.5px;
  line-height: 1.6;
  margin-bottom: 4px;
}
.desc-aggressive { background: #fff7e6; color: #d46b08; border: 1px solid #ffd591; }
.desc-balanced { background: #e6f7ff; color: #0958d9; border: 1 solid #91d5ff; }
.desc-conservative { background: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }
</style>

<template>
  <div class="pricing-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 目标 ASIN（可选） -->
      <a-form-item label="目标 ASIN（可选）">
        <a-input
          v-model:value="formState.asin"
          placeholder="输入ASIN，留空分析所有竞品"
          :maxlength="10"
          allow-clear
        />
        <div class="form-hint">指定后聚焦该竞品定价策略</div>
      </a-form-item>

      <!-- 对比 ASIN -->
      <a-form-item label="对比竞品（可选）">
        <a-select
          v-model:value="formState.compareAsins"
          mode="tags"
          placeholder="输入对比ASIN，回车添加"
          :token-separators="tokenSeparators"
          style="width: 100%"
        />
      </a-form-item>

      <!-- 分析深度 -->
      <a-form-item label="分析深度">
        <a-radio-group v-model:value="formState.analysisDepth" :options="depthOptions" />
        <div class="form-hint">{{ depthDescMap[formState.analysisDepth] }}</div>
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">💵 定价策略分析将输出</p>
        <ul>
          <li>竞品定价模式分类（溢价/经济/竞争/动态）</li>
          <li>促销频率与折扣幅度统计</li>
          <li>价格弹性与波动率</li>
          <li>市场定位图与调价建议</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 分析定价策略
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
  asin: '',
  compareAsins: [] as string[],
  analysisDepth: 'standard',
})

const depthOptions = [
  { label: '基础', value: 'basic' },
  { label: '标准（推荐）', value: 'standard' },
  { label: '深度', value: 'deep' },
]

const depthDescMap: Record<string, string> = {
  basic: '仅输出当前价格和基本策略判断',
  standard: '包含促销频率、折扣幅度、价格弹性',
  deep: '完整分析含历史调价模式、心理价位锚定、动态定价算法推测',
}

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      asin: formState.asin || undefined,
      compare_asins: formState.compareAsins.length > 0 ? formState.compareAsins : undefined,
      analysis_depth: formState.analysisDepth,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.pricing-config { padding: var(--space-4) 0; }
.config-form :deep(.ant-form-item) { margin-bottom: var(--space-14); }
.config-form :deep(.ant-form-item-label) { font-size: var(--font-size-13); font-weight: 500; }
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-4); }
.action-bar { margin-top: var(--space-16); padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
.quick-tips { margin-top: var(--space-16); padding: var(--space-12); background: #fff0f6; border-radius: var(--radius-8); border: 1px solid #ffadd2; }
.tips-title { font-size: var(--font-size-12); font-weight: 600; color: #c41d7f; margin-bottom: var(--space-6); }
.quick-tips ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; }
</style>

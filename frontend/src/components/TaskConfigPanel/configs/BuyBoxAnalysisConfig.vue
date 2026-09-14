<template>
  <div class="buybox-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- 目标 ASIN（可选） -->
      <a-form-item label="目标 ASIN（可选）">
        <a-input
          v-model:value="formState.asin"
          placeholder="输入ASIN，留空分析所有竞品"
          :maxlength="10"
          allow-clear
        />
        <div class="form-hint">指定后聚焦该产品的 Buy Box 竞争格局</div>
      </a-form-item>

      <!-- 站点选择 -->
      <a-form-item label="目标站点">
        <a-select v-model:value="formState.marketplace" :options="marketplaceOptions" />
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">🛒 Buy Box 分析将输出</p>
        <ul>
          <li>Buy Box 赢家列表与价格对比</li>
          <li>竞争力评分与赢取概率</li>
          <li>影响 Buy Box 的关键因素分析</li>
          <li>提升 Buy Box 赢取率的策略建议</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading">
          <PlayCircleOutlined /> 分析 Buy Box
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
  asin: '',
  marketplace: 'US',
})

const marketplaceOptions = [
  { label: '美国站 (US)', value: 'US' },
  { label: '英国站 (UK)', value: 'UK' },
  { label: '德国站 (DE)', value: 'DE' },
  { label: '日本站 (JP)', value: 'JP' },
]

const handleStart = () => {
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      asin: formState.asin || undefined,
      marketplace: formState.marketplace,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.buybox-config { padding: var(--space-4) 0; }
.config-form :deep(.ant-form-item) { margin-bottom: var(--space-14); }
.config-form :deep(.ant-form-item-label) { font-size: var(--font-size-13); font-weight: 500; }
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-4); }
.action-bar { margin-top: var(--space-16); padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
.quick-tips { margin-top: var(--space-16); padding: var(--space-12); background: var(--success-bg); border-radius: var(--radius-8); border: 1px solid var(--success-border); }
.tips-title { font-size: var(--font-size-12); font-weight: 600; color: #7cb305; margin-bottom: var(--space-6); }
.quick-tips ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; }
</style>

<template>
  <div class="compare-grid-config">
    <a-form layout="vertical" :model="formState" class="config-form">
      <!-- ASIN 列表 -->
      <a-form-item label="竞品 ASIN 列表（至少2个）" required>
        <a-select
          v-model:value="formState.asins"
          mode="tags"
          placeholder="输入ASIN，回车添加（2-10个）"
          :token-separators="tokenSeparators"
          style="width: 100%"
        />
        <div class="form-hint">已添加 {{ formState.asins.length }} / 10 个</div>
      </a-form-item>

      <!-- 对比维度 -->
      <a-form-item label="对比维度">
        <a-checkbox-group v-model:value="formState.dimensions" :options="dimensionOptions" />
      </a-form-item>

      <!-- 快捷提示 -->
      <div class="quick-tips">
        <p class="tips-title">⚔️ 多维对比将输出</p>
        <ul>
          <li>各维度雷达图对比</li>
          <li>性价比综合得分排名</li>
          <li>差异化分析与市场空白机会</li>
          <li>每个维度的最优竞品标注</li>
        </ul>
      </div>

      <!-- 操作按钮 -->
      <div class="action-bar">
        <a-button type="primary" block @click="handleStart" :loading="loading" :disabled="formState.asins.length < 2">
          <PlayCircleOutlined /> 开始对比
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
  asins: [] as string[],
  dimensions: ['price', 'rating', 'reviews', 'bsr', 'value'],
})

const dimensionOptions = [
  { label: '价格', value: 'price' },
  { label: '评分', value: 'rating' },
  { label: '评论数', value: 'reviews' },
  { label: 'BSR排名', value: 'bsr' },
  { label: '性价比', value: 'value' },
]

const handleStart = () => {
  if (formState.asins.length < 2) return
  loading.value = true
  setTimeout(() => {
    emit('startAnalysis', {
      asins: formState.asins,
      dimensions: formState.dimensions,
    })
    loading.value = false
  }, 300)
}
</script>

<style scoped>
.compare-grid-config { padding: var(--space-4) 0; }
.config-form :deep(.ant-form-item) { margin-bottom: var(--space-14); }
.config-form :deep(.ant-form-item-label) { font-size: var(--font-size-13); font-weight: 500; }
.form-hint { font-size: var(--font-size-11); color: var(--text-tertiary); margin-top: var(--space-4); }
.action-bar { margin-top: var(--space-16); padding-top: var(--space-12); border-top: 1px solid var(--border-base); }
.quick-tips { margin-top: var(--space-16); padding: var(--space-12); background: var(--purple-bg); border-radius: var(--radius-8); border: 1px solid #b37feb; }
.tips-title { font-size: var(--font-size-12); font-weight: 600; color: var(--purple); margin-bottom: var(--space-6); }
.quick-tips ul { margin: 0; padding-left: var(--space-18); font-size: var(--font-size-11-5); color: var(--text-secondary); line-height: 1.7; }
</style>
